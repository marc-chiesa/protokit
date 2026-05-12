---
title: "Use Click's ParameterSource API to distinguish explicit user intent from flag defaults when merging CLI flags with a config file"
date: 2026-05-11
category: docs/solutions/best-practices
module: protokit.schema.lint.cli
problem_type: best_practice
component: tooling
severity: high
applies_when:
  - "A CLI flag has a meaningful non-None click default (e.g., --profile default, --format human) AND a config-file layer (pyproject, .ini, etc.) can also supply the same key at lower precedence"
  - "Value-alone cannot distinguish 'user explicitly typed the flag' from 'click applied the built-in default' because the user could have typed the default value verbatim"
  - "The intended precedence rule is CLI flag > environment variable > config file > built-in default, and the config-file value must win when the user did not explicitly supply the flag"
  - "A programmatic caller uses `click.Context(default_map={...})` to inject overrides (test harnesses, parent command groups, plugin wrappers)"
  - "A ce:review correctness or adversarial reviewer flags that config-file values are silently overridden by click defaults the user never typed"
tags:
  - click
  - parameter-source
  - cli-config-precedence
  - pyproject
  - default-map
  - tooling
  - protokit-lint
  - ce-review
---

# Use Click's ParameterSource API to distinguish explicit user intent from flag defaults

## Context

When a CLI flag carries a meaningful default value — for example,
`--profile NAME` declared with `default="default"` — the value that
Click delivers to a callback is indistinguishable between two
scenarios: the user explicitly typed `--profile default`, or Click
simply applied the flag's built-in default. The Python-level signal
is identical. This distinction is load-bearing whenever a config-file
layer (e.g., `[tool.protokit.lint]` in `pyproject.toml`) is supposed
to supply that same value at lower precedence than an explicit CLI
choice but higher precedence than the flag's hard-coded default.

Without source detection, the flag default silently wins over any
config-file value. A user who sets `profile = "strict"` in pyproject
and never touches `--profile` on the command line will see the
built-in default `"default"` applied instead of their pyproject
value, with no error and no diagnostic — a wrong-but-valid run.

The prior project pattern (D3 R10 `--max-warnings`) used a sentinel
`default=None` and branched on `value is None` to detect "flag not
supplied." That approach works only when the flag has no meaningful
default. D3's `--profile NAME` was declared with `default="default"`
because `"default"` is also a real, valid profile name — there is no
out-of-band sentinel available. The D3 plan explicitly noted "no
sentinel value needed" for `--max-warnings` (true) but the same
escape hatch did not exist for `--profile` when D5 added pyproject
config as a competing source.

Click 8.x exposes `Context.get_parameter_source(name)` returning a
`ParameterSource` enum member. The five values are `COMMANDLINE`,
`ENVIRONMENT`, `DEFAULT_MAP`, `DEFAULT`, and `PROMPT`. Only `DEFAULT`
represents "flag's own built-in default fired"; the rest represent
explicit user intent of some kind.

This pattern emerged during D5 U2 of protokit-lint (commit `3463691`,
2026-05-11) and was reinforced by the ce:review follow-up commit
`aa15f98`. Two reviewers — correctness (confidence 0.82) and
adversarial (confidence 0.82) — independently flagged that
`DEFAULT_MAP` was absent from the initial `explicit_sources` tuple.
That 2-way convergence caught the gap before any test failure made
it observable.

## Guidance

### Step 1 — Import `ParameterSource` from `click.core`, not `click`

`ParameterSource` is defined in `click.core` but is NOT re-exported
from the top-level `click` package (verified against Click 8.3.x).
The import path is non-obvious; surface it with an aliased import
that documents its non-public nature:

```python
from click.core import ParameterSource as _ParameterSource
```

The leading underscore mirrors the project's convention for internal
imports (`_cli_utils`, `_config`, etc.) and signals to future readers
that this is a deliberate reach into `click.core`.

### Step 2 — Treat three sources as "explicit user intent"

```python
explicit_sources = (
    _ParameterSource.COMMANDLINE,   # user typed the flag
    _ParameterSource.ENVIRONMENT,   # user set an envvar (e.g., PROTOKIT_FORMAT)
    _ParameterSource.DEFAULT_MAP,   # programmatic caller injected via Context(default_map=...)
)
```

`DEFAULT_MAP` is the easy-to-omit member. It fires when a value is
supplied via `click.Context(default_map={...})` — used by parent
command groups (`context_settings={"default_map": ...}`), plugin
wrappers, and programmatic test harnesses. Omitting `DEFAULT_MAP`
silently drops those callers' overrides, inverting the precedence
rule with no diagnostic. The D5 U2 ce:review caught this via 2-way
convergence; no individual reviewer needed extraordinary insight,
but the omission was missed during U2 implementation.

`ENVIRONMENT` belongs in this set: a user who sets `PROTOKIT_FORMAT=json`
in their shell is making an explicit intent choice, not triggering a
framework default. Document this in the affected flag's help text so
users understand env-var precedence over config-file values.

`DEFAULT` alone means "no user intent expressed; defer to config-file,
then to built-in default."

### Step 3 — Use the Python kwarg name, not the flag name

```python
profile_explicit = ctx.get_parameter_source("profile_name") in explicit_sources
```

The argument to `get_parameter_source()` is the Python parameter name
(the second positional argument to `@click.option`, often spelled
differently from the user-facing flag). `--profile NAME` bound to
`profile_name` requires the string `"profile_name"`, NOT `"--profile"`,
NOT `"profile"`. A typo here returns `ParameterSource.DEFAULT` for
every invocation — the source-detection logic silently degrades to
"flag always defaulted," reintroducing the bug it was meant to fix.

### Step 4 — Build CLI overrides with `None` as the "not supplied" sentinel

The config-merge layer (typically a `ResolvedConfig.from_dict()`
classmethod) should treat `None` in `cli_overrides` as "CLI did not
supply this key; defer to config file then to built-in default."
Non-`None` values override config file unconditionally.

```python
cli_overrides: dict[str, Any] = {
    "profile": (
        (profile_name.strip().lower(),) if profile_explicit else None
    ),
    "format": (
        format_name.strip().lower() if format_explicit else None
    ),
    # `--min-severity` has default=None natively — None already
    # signals "not supplied"; no parameter-source check needed.
    "min_severity": (
        _MIN_SEVERITY_CHOICES[min_severity.lower()]
        if min_severity is not None else None
    ),
    ...
}
resolved = ResolvedLintConfig.from_dict(pyproject_config, cli_overrides)
```

This composes naturally with the
[`normalize-at-input-boundary`](./normalize-at-input-boundary-2026-05-07.md)
discipline: source detection is the outer gate (was the value
supplied?); normalization is the inner operation on the supplied
value. Both must happen at the CLI input boundary.

## Why This Matters

**Silent precedence inversion.** Omitting `DEFAULT_MAP` from
`explicit_sources` causes test harnesses that use
`CliRunner().invoke(lint_main, [...], default_map={"profile_name": "permissive"})`
to see pyproject win over their explicit override — no error, no
diagnostic, just a wrong run. The same hazard applies to parent
command groups and plugin wrappers in real CLI deployments.

**Config-file UX contract.** The promise of
`[tool.protokit.lint] profile = "strict"` in pyproject is that the
project's stable lint surface lives in the repo, checked in. Without
parameter-source detection, every CLI invocation that omits
`--profile` silently breaks that promise by inheriting the click
default instead — pyproject becomes decorative.

**Regression surface for CI.** A CI invocation that relies on
pyproject-supplied values without typing the corresponding CLI flag
will silently pick up the built-in default instead. The failure mode
is "wrong-but-valid run" (exit 0, plausible output) rather than a
crash, making it especially hard to detect via standard health checks.

**Anti-pattern to avoid.** Do not try to reconstruct source after the
fact by comparing the resolved value against the known click default
(`if value == "default"`) — `"default"` is a real valid value the
user might type. The `ctx.get_parameter_source()` call is the only
reliable signal.

## When to Apply

- Any CLI command where a flag has a non-`None` default AND a
  config-file or environment layer is supposed to supply the same
  key at lower precedence.
- When extracting or designing a config-merge precedence layer
  (`from_dict`, `load_config`, etc.) that receives CLI override
  values: define and document the `None` sentinel contract
  explicitly in the layer's docstring.
- When adding a config file to a CLI that previously only had flags:
  audit every flag declared with `default=<non-None>` for the same
  gap. The audit cost is one grep for `@click.option.*default=` and
  one line of attention per match.
- When writing test harnesses that use `default_map` to inject values
  into CLI tests: confirm `DEFAULT_MAP` is in your production code's
  `explicit_sources`. A test that asserts `default_map` overrides
  pyproject is the cheapest pinning.

## Examples

### Before — initial D5 U2 implementation (commit `3463691`), missing `DEFAULT_MAP`

```python
# src/protokit/schema/lint/cli.py (pre-aa15f98)
from click.core import ParameterSource as _ParameterSource

explicit_sources = (
    _ParameterSource.COMMANDLINE,
    _ParameterSource.ENVIRONMENT,
    # DEFAULT_MAP omitted — programmatic callers' overrides silently dropped
)
profile_explicit = ctx.get_parameter_source("profile_name") in explicit_sources
```

A test harness using `default_map={"profile_name": "default"}` with
pyproject `profile = "strict"` would see `"strict"` (pyproject wins)
rather than `"default"` (DEFAULT_MAP intent) — silent precedence
inversion.

### After — post-ce:review fix (commit `aa15f98`), as shipped

```python
# src/protokit/schema/lint/cli.py
from click.core import ParameterSource as _ParameterSource

explicit_sources = (
    _ParameterSource.COMMANDLINE,
    _ParameterSource.ENVIRONMENT,
    _ParameterSource.DEFAULT_MAP,    # F-02 fix: programmatic callers honored
)
profile_explicit = (
    ctx.get_parameter_source("profile_name") in explicit_sources
)
format_explicit = (
    ctx.get_parameter_source("format_name") in explicit_sources
)
```

### Test pinning the DEFAULT_MAP path

`tests/schema/lint/cli/test_config_flags.py::TestParameterSourceDefaultMap`:

```python
def test_default_map_value_overrides_pyproject(
    self, tmp_path: Path, descriptor_set: Path,
) -> None:
    """DEFAULT_MAP-sourced values must override pyproject (treated as
    explicit user intent, equivalent to COMMANDLINE/ENVIRONMENT).
    """
    config = tmp_path / "pyproject.toml"
    config.write_text(
        "[tool.protokit.lint]\nprofile = \"strict-naming\"\n",
    )
    result = CliRunner().invoke(
        lint_main,
        ["--config", str(config), str(descriptor_set)],
        default_map={"profile_name": "default"},
    )
    # If DEFAULT_MAP were not in explicit_sources, pyproject "strict-naming"
    # would win and the unknown-profile error would fire (exit 2).
    assert "error[lint-unknown-profile]:" not in result.stderr
    assert result.exit_code != 2
```

### The wider precedence picture

The full four-tier precedence as documented in the `--format` help
text after F-06 lands:

```
CLI --format  >  PROTOKIT_FORMAT envvar  >  [tool.protokit.lint] format  >  built-in default
```

`ctx.get_parameter_source()` distinguishes the first three tiers
collectively from the fourth. The merge layer (`from_dict`)
distinguishes within tiers 2-3.

## Related Learnings

- [`normalize-at-input-boundary-2026-05-07.md`](./normalize-at-input-boundary-2026-05-07.md)
  — sibling discipline at the same Click input boundary. That doc
  normalizes VALUES at the boundary (`.lower()`, `.strip()`); this
  doc detects SOURCES at the boundary. They compose: detect source
  first, then normalize the detected value. The normalize doc names
  `--profile` as the "next domino" after `--format`; this doc closes
  the source-detection half of that domino.
- [`source-aware-error-messages-multi-source-resolved-value-2026-05-11.md`](./source-aware-error-messages-multi-source-resolved-value-2026-05-11.md)
  — natural pipeline partner. Once source is detected at the input
  boundary (this doc), error messages downstream must NAME the source
  rather than assume one (that doc). Both are needed for a correct
  precedence-aware CLI.
- [`shared-error-helper-source-label-caller-attribution-2026-05-11.md`](./shared-error-helper-source-label-caller-attribution-2026-05-11.md)
  — adjacent discipline. The config-merge layer (`from_dict`) benefits
  from knowing which source supplied each value, both for precedence
  logic (this learning) and for accurate error-message attribution
  (that learning, in the shared-helper variant).

## Reference Commits

- `3463691` — D5 U2 feature delivery; initial `explicit_sources`
  missing `DEFAULT_MAP`.
- `aa15f98` — D5 U2 ce:review follow-ups; `DEFAULT_MAP` added
  (F-02 finding, 2-way correctness + adversarial convergence).
- ce:review run artifact:
  `.context/compound-engineering/ce-review/20260511-175812-997cfcc3/`
  (correctness-reviewer.json, adversarial-reviewer.json).
