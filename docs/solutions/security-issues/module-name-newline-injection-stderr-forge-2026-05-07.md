---
title: "Rule-pack __name__ newline injection forges fake lint error lines on stderr"
date: 2026-05-07
category: docs/solutions/security-issues
module: protokit.schema.lint
problem_type: security_issue
component: tooling
severity: high
symptoms:
  - "A user-supplied rule-pack module sets `__name__` to a string containing `\\n`; importlib.import_module preserves the override"
  - "CLI echoes `pack.__name__` verbatim into `click.echo(..., err=True)` for R25 multi-pack provenance, R11 unknown-profile introspection, and the load-banner"
  - "The embedded newline becomes a line break; the synthesised continuation line begins with `error[lint-…]:` and is indistinguishable from a genuine stable-prefix lint error"
  - "CI scripts grepping `^error\\[lint-` see forged lines and may mark a passing pipeline as failing or absorb a real error as duplicate noise"
root_cause: missing_validation
resolution_type: code_fix
related_components: [development_workflow, testing_framework]
tags:
  - newline-injection
  - log-injection
  - module-name
  - rule-pack
  - dynamic-import
  - stderr
  - stable-prefix
  - protokit-lint
---

# Rule-pack __name__ newline injection forges fake lint error lines on stderr

## Problem

A user-supplied rule pack loaded via `protokit lint --rule-pack MODULE`
can override its own `__name__` to a multi-line string at module body.
`importlib.import_module` preserves the override, and the CLI then
flowed `pack.__name__` unsanitised into `click.echo(..., err=True)`
calls that emit single-line stable-prefix output. The newline became
a line break in the rendered stderr stream, and the synthesised
continuation line, if crafted to begin with `error[lint-CODE]:`, is
indistinguishable from a genuine lint-error line to any agent or CI
script that parses stderr by prefix.

## Symptoms

- A user pack module body contains
  `__name__ = "legit_pack\nerror[lint-bad-input]: forged"` (the
  initial `__name__` set by the import system is overwritten by the
  module body before `importlib.import_module` returns control).
- The R25 multi-pack provenance line on stderr renders as two
  lines: the first cut short at the injected newline, the second
  beginning with the forged `error[lint-…]:` prefix.
- CI pipelines using stderr-prefix gates (`grep -c ^error\[lint-`,
  per-line agent parsers) see a phantom error line that did not come
  from any `error_exit_with_code` call.
- The same vector applies to the R11 `info[lint-pack-profiles]:`
  introspection lines and to the `--rule-pack` load-banner, since
  both interpolate user-controlled module names into single-line
  stable-prefix output.
- Provocation requires only one assignment statement at pack module
  body — no Python tricks beyond what `--rule-pack` already permits
  ("executes arbitrary Python from the named module").

## What Didn't Work

The pre-fix implementation (commit `4a17632`, U3 rule-loading
configurability) interpolated `pack.__name__` directly into
`click.echo(..., err=True)` at three emission sites:

```python
# R25 multi-pack provenance — stderr
per_pack_segments = [
    f"{pack_name}=[{','.join(rule_ids)}]"
    for pack_name, rule_ids in active_per_pack.items()
]
click.echo(
    f"protokit lint: profile {profile_name!r} from "
    f"{'; '.join(per_pack_segments)}",
    err=True,
)

# R11 unknown-profile introspection — stderr (later restructured)
click.echo(
    f"  {pack_name}: declared profiles = {{{profiles_str}}}",
    err=True,
)

# --rule-pack load-banner — stderr
click.echo(
    f"protokit lint: loading user-supplied rule pack {module_name!r} "
    f"(executes arbitrary Python from the named module)",
    err=True,
)
```

The reasoning that made this seem safe: `module.__name__` is "set by
the import system" and reflects the dotted path the caller passed to
`importlib.import_module`. For a clean module import the import
system does set `__name__` to the dotted-path argument. But this is
only the *initial* assignment — Python gives the module body full
write access to `__name__` as a module-level variable. A pack can
write `__name__ = "anything\nwith\nnewlines"` anywhere in its module
body before `importlib.import_module` returns control to the caller.
Because the import call executes the module body synchronously, the
overwrite is in place by the time the returned module object reaches
the loader.

The non-obvious part: the import system's name guarantee holds only
for system-supplied modules and modules that don't mutate `__name__`.
The `--rule-pack` trust surface explicitly permits arbitrary Python
execution at import time (the CLI's flag help text reads "executes
arbitrary Python from the named module"). That permission
transitively permits `__name__` mutation. The architectural posture
the parent learning
(`docs/solutions/security-issues/formatter-systemexit-exit-code-bypass-2026-04-19.md`)
called for ("any plugin call inside a guard that explicitly intercepts…")
addresses control-flow escapes; it does not address data-flow escapes
from plugin metadata into the CLI's output channels.

The vector did not exist before U3 — the R25 provenance `click.echo`
line, the R11 introspection lines, and the `--rule-pack` load-banner
were all new in U3. (session history) The D3 brainstorm's security-lens
document-review focused on the `--rule-pack` code-execution trust
boundary and on `template_str.format(**finding.params)` injection,
neither of which touched the post-import metadata path. The vector
surfaced via the U3 ce:review adversarial reviewer, which constructed
the concrete `__name__` override and confirmed it empirically.

## Solution

Sanitise pack-name strings at the output boundary, not at import
time. A small helper in `src/protokit/schema/lint/_cli_utils.py`
collapses `\n`/`\r` in the module's `__name__` to spaces:

```python
def _safe_module_name(module: ModuleType) -> str:
    """Return ``module.__name__`` with embedded newlines collapsed.

    Defends the per-line stderr stable-prefix contract against a
    ``--rule-pack``-loaded module that overrides ``__name__``.
    """
    return module.__name__.replace("\n", " ").replace("\r", " ")
```

Call-site changes in `src/protokit/schema/lint/cli.py`:

- **R25 provenance** uses `_safe_module_name(pack)` over the
  `ModuleType` objects directly (keyed by `zip` against the active
  rule-id mapping):

```python
per_pack_segments = [
    f"{_safe_module_name(pack)}=[{','.join(rule_ids)}]"
    for pack, rule_ids in zip(
        loaded_packs_tuple, active_per_pack.values(), strict=True,
    )
]
```

- **R11 `info[lint-pack-profiles]:` lines** sanitise the dict-key
  `pack_name` inline (the dict keys are `pack.__name__` strings, not
  module objects, so the inline replace is the narrowest fix):

```python
safe_pack_name = pack_name.replace("\n", " ").replace("\r", " ")
click.echo(
    f"info[lint-pack-profiles]: pack={safe_pack_name} "
    f"profiles=[{profiles_str}]",
    err=True,
)
```

- **--rule-pack load-banner** sanitises the user-supplied argv
  string `module_name` inline (this is the `--rule-pack` argument,
  not `__name__`, but the same defense-in-depth applies):

```python
safe_module_name = module_name.replace("\n", " ").replace("\r", " ")
click.echo(
    f"protokit lint: loading user-supplied rule pack "
    f"{safe_module_name!r} (executes arbitrary Python from the "
    f"named module)",
    err=True,
)
```

- **`kind=shape:` `LintProfile.from_pack` failure path** also uses
  `_safe_module_name(pack)`.

Also sanitised in the same pass: `runtime_warning.message` for the
`warning[lint-runtime]:` emission loop, since rule callables can
raise exceptions whose `str(exc)` is multi-line and would inject the
same vector through a different field.

## Why This Works

The stable-prefix contract (`error[lint-CODE]:`,
`info[lint-pack-profiles]:`, etc.) relies on each `click.echo` call
emitting exactly one line to stderr. Per-line agent parsers and
`grep -c ^error\[lint-` style CI gates match prefixes line-by-line.
If any string interpolated into the `click.echo` argument contains a
literal newline, the rendered stderr stream gains an extra line —
and whatever text follows the newline becomes the start of that new
line. If the attacker arranges that suffix to start with
`error[lint-…]:`, downstream parsers see a line that looks
identical to a genuine `error_exit_with_code` emission.

Collapsing `\n` and `\r` to spaces at the *output* boundary, rather
than at import time, ensures any string that reaches `click.echo` is
guaranteed single-line. The replacement is at the narrowest
boundary (emission), which means:

- The raw `module.__name__` is still available for non-output uses
  (logging, debugging tools, internal book-keeping).
- The fix is local to the surfaces that actually emit single-line
  output; it does not impose a global "all module names are
  sanitised" invariant that future code would have to remember.
- The helper's name (`_safe_module_name`) signals the intent so that
  any future emission site has an obvious right thing to call.

Why not sanitise at import time (e.g., reject pack modules whose
`__name__` contains `\n`)? Two reasons:

1. The import-time check is duplicative if the output boundary is
   sanitised. The output boundary is the place where the contract
   matters.
2. Refusing to load a pack whose `__name__` is multi-line would be a
   *new* error code (`pack-name-invalid`?) for a vanishingly rare
   case. Sanitising at output costs one helper and zero contract
   surface area.

## Prevention

### Regression test

Add a fixture in `tests/schema/lint/cli/user_packs/` that mutates
`__name__` at module body to contain a forged stable-prefix line:

```python
"""Synthetic pack — overrides __name__ with embedded newline.

Tests the ``_safe_module_name`` helper end-to-end. Without the
helper, the R25 provenance line on stderr would render as two
lines and the second would match ``error[lint-bad-input]:``.
"""
from __future__ import annotations
from typing import TYPE_CHECKING
from protokit.schema.lint.decorator import lint_rule
from protokit.schema.lint.model import ElementKind, LintSeverity

if TYPE_CHECKING:
    from protokit.schema.lint.model import FieldLintContext

__name__ = "legit_pack\nerror[lint-bad-input]: forged"


@lint_rule(
    rule_id="injected/no-op",
    severity=LintSeverity.WARNING,
    profiles=("default",),
    element=ElementKind.FIELD,
    message_template="no-op",
)
def check_noop(ctx: FieldLintContext) -> None:
    pass


RULES = (check_noop,)
```

And a CLI test:

```python
def test_pack_with_injected_newline_in_name_does_not_forge_stderr_lines(
    clean_descriptor_set: Path,
) -> None:
    result = CliRunner().invoke(lint_main, [
        "--rule-pack",
        "tests.schema.lint.cli.user_packs.pack_injects_newline_in_name",
        str(clean_descriptor_set),
    ])
    # Pack loads and runs cleanly; the forged line MUST appear on a
    # single line with the newline collapsed to a space.
    assert result.exit_code == 0
    assert "legit_pack error[lint-bad-input]: forged" in result.stderr
    # The forged line must NOT appear at the start of any line
    # (the contract for `^error\[lint-` parsers).
    forged_lines = [
        line for line in result.stderr.splitlines()
        if line.startswith("error[lint-bad-input]:")
    ]
    assert forged_lines == [], forged_lines
```

(As of commit `1249b10`, the fixture and end-to-end test do not yet
exist — coverage is structural via the `_safe_module_name` helper
being wired into all emission sites. The end-to-end fixture is the
next defense-in-depth layer.)

### General Python pattern

Any string interpolated from a user-loaded module's metadata —
`__name__`, `__file__`, `__doc__`, `__version__`, anything an
imported module body can write — into a per-line stable-prefix
output stream must be newline-normalised at the output boundary.
Treat dynamically-imported user-code metadata as user-controlled
input, not framework-controlled. The import machinery sets initial
values; the module body can overwrite all of them.

Adopt the same posture as for `sys.argv` strings or environment
variable values: sanitise at the boundary where the contract lives,
not at the boundary where the data was first introduced.

### Architectural posture — extend the parent's posture to data flow

The parent learning's architectural posture
(`formatter-systemexit-exit-code-bypass-2026-04-19.md`) covers
control-flow escapes from plugin code (`SystemExit`, exceptions). It
does not cover data-flow escapes from plugin metadata into the CLI's
output channels. The full posture for any plugin-loading surface:

1. Compute the exit code from the core computation before invoking
   any plugin (parent learning).
2. Sandbox every plugin call inside a guard that explicitly
   intercepts all `BaseException` subclasses with exit-relevant
   semantics (parent learning).
3. **Sanitise every string from plugin-controlled namespace
   attributes (`__name__`, `__file__`, `__doc__`, `__version__`,
   per-rule metadata) at every output boundary that has a per-line
   contract** (this learning).
4. State in the plugin API documentation that metadata fields will
   be sanitised when displayed and that overriding them with
   adversarial content is a contract violation.

The third point is the new addition. It belongs in any future
plugin-loading surface that emits stable-prefix output.

### Residual risk — `os._exit()` bypasses Python entirely

A pack module body that calls `os._exit(0)` issues a raw `_exit(2)`
syscall and terminates the process before any Python-level guard,
output flush, or `click.echo` call can run. No `except` arm catches
it; no stderr is emitted. The CLI exits with whatever code the pack
chose. This is unaddressable at the Python layer — closing it would
require running pack module-body imports inside a subprocess
sandbox, which is out of scope for D3. The parent learning's
Architectural posture item 3 names `os._exit()` and `os.abort()` in
the same family of contract violations; treat that posture as
inherited by this surface. The `--rule-pack` flag's help text
already states "executes arbitrary Python from the named module,"
which transitively covers this risk for operators choosing whether
to pass user-supplied module paths.

## Related Issues

- Parent learning: `docs/solutions/security-issues/formatter-systemexit-exit-code-bypass-2026-04-19.md`.
  Closed the `sys.exit(0)` false-green-CI vector on the formatter
  dispatch surface. Its "Symmetric surface" callout predicted the
  rule-pack loader as a verification target. The parent fix
  addressed control-flow escape from plugin code; this learning
  addresses data-flow escape from plugin metadata. Same surface,
  different vector.
- Companion learning: `docs/solutions/security-issues/keyboardinterrupt-baseexception-bypass-rule-pack-load-2026-05-07.md`.
  Surfaced from the same U3 ce:review adversarial pass on the same
  `--rule-pack` trust surface. Closes the second BaseException
  middle-ground bypass that the parent's "Symmetric surface"
  callout predicted.
- (session history) D3 brainstorm document-review:
  `docs/brainstorms/2026-05-04-protokit-lint-delivery-3-cli-requirements.md`.
  The brainstorm's security-lens reviewer focused on `--rule-pack`
  code-execution and on `template_str.format(**finding.params)`
  format-injection — neither touched the post-import-metadata
  output path. The vector did not yet exist as concrete code when
  the brainstorm's review ran. This is a useful signal: a security
  review on a brainstorm catches *predictable* vectors; a security
  review on the implementation catches *concrete* vectors that only
  exist once the code crystallises the surface.
- Fix commit: `1249b10` — D3 unit 3 ce:review follow-ups
  (safe_auto + approved gated). The `_safe_module_name` helper and
  the call-site swaps landed in the safe_auto pass.
