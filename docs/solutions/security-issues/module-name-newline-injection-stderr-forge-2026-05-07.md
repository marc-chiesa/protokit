---
title: "Rule-pack __name__ newline injection forges fake lint error lines on stderr"
date: 2026-05-07
last_updated: 2026-05-12
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
time. The fix landed in two stages: the initial U3 patch used inline
`.replace()` calls; the post-U3 consolidation generalised the scope
into a single `_safe_for_stderr(value)` helper backed by a control-
character translation table. The current implementation in
`src/protokit/schema/lint/_cli_utils.py` is:

```python
#: Translation table mapping every line-break / control codepoint
#: to a single space. Built once at module-load time so per-call
#: cost is one ``str.translate`` rather than chained ``.replace()``
#: scans.
_CONTROL_CHAR_TABLE: dict[int, int] = {
    codepoint: ord(" ") for codepoint in range(0x20)
}
_CONTROL_CHAR_TABLE[0x7F] = ord(" ")
# Unicode line-terminator codepoints beyond ASCII — see the
# "Unicode line-terminator widening" subsection below.
_CONTROL_CHAR_TABLE[0x85] = ord(" ")    # U+0085 NEXT LINE (NEL)
_CONTROL_CHAR_TABLE[0x2028] = ord(" ")  # U+2028 LINE SEPARATOR
_CONTROL_CHAR_TABLE[0x2029] = ord(" ")  # U+2029 PARAGRAPH SEPARATOR


def _safe_for_stderr(value: object) -> str:
    """Collapse all line-break / control characters in a stringified
    value to spaces.

    Defense-in-depth against attacker-controlled strings flowing
    into single-line ``click.echo(..., err=True)`` output. Paths,
    exception messages, module names, and any other stringified
    field that may include user-controlled bytes is passed through
    this helper before being interpolated into stderr error
    messages.
    """
    return str(value).translate(_CONTROL_CHAR_TABLE)


def _safe_module_name(module: ModuleType) -> str:
    """Return ``module.__name__`` sanitized for stderr emission.

    Thin wrapper that extracts ``module.__name__`` first, then routes
    through ``_safe_for_stderr``. Used at every emission site that
    interpolates a user-loaded module's name into a per-line
    stable-prefix output stream.
    """
    return _safe_for_stderr(module.__name__)
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
  `pack_name` via `_safe_for_stderr` (the dict keys are
  `pack.__name__` strings, not module objects):

```python
safe_pack_name = _safe_for_stderr(pack_name)
click.echo(
    f"info[lint-pack-profiles]: pack={safe_pack_name} "
    f"profiles=[{profiles_str}]",
    err=True,
)
```

- **--rule-pack load-banner** sanitises the user-supplied argv
  string `module_name` (this is the `--rule-pack` argument, not
  `__name__`, but the same defense-in-depth applies):

```python
safe_module_name = _safe_for_stderr(module_name)
click.echo(
    f"protokit lint: loading user-supplied rule pack "
    f"{safe_module_name!r} (executes arbitrary Python from the "
    f"named module)",
    err=True,
)
```

- **`kind=shape:` `LintProfile.from_pack` failure path** also uses
  `_safe_module_name(pack)`.

Also sanitised in the same family of fixes: `runtime_warning.message`
for the human-format CLI-side hook (D5 U5
`_emit_human_runtime_warnings`); `rid` and `profile.name` at the
`unloaded_rule` `LintRuntimeWarning` construction site in
`engine.py` (D5 U5 ce:review follow-up — KTD-9 dual-defense at
construction time + emission time). The single `_safe_for_stderr`
helper covers every emission/construction site uniformly.

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

### Extended principle — every interpolated slot, not just user-supplied fields

(Added 2026-05-12 from the D5 U5 ce:review.) The natural instinct
when adding defense-in-depth sanitization to a string interpolation
boundary is to identify "user-supplied data" fields and sanitize
those. Fields that are typed as closed-set enumerations —
`Literal["rule_exception", "unloaded_rule", "min_severity_relaxed",
"all_files_excluded"]` — feel bounded and safe by inspection. The
trap is that **Python does not enforce `Literal[...]` annotations
at runtime**. A `mypy` check at the construction site catches type
violations only if the developer reads the annotation and respects
it; a future emission site that constructs the dataclass with a
hand-crafted control-character-bearing value bypasses the type
checker entirely.

The U5 initial implementation of `_emit_human_runtime_warnings`
applied `_safe_for_stderr` to `w.message` but interpolated
`w.category` raw — `w.category` was a `Literal[...]`-annotated field
populated internally and the developer reasoned from the annotation
rather than the trust model. Three reviewers (security +
project-standards + adversarial) converged on the asymmetry as a
defense gap. The fix was two additional lines:

```python
# Wrong — asymmetric: only the obviously user-data slot sanitized.
safe_message = _safe_for_stderr(w.message)
click.echo(
    f"protokit lint: warning [{w.category}]: {safe_message}",
    err=True,
)

# Right — every interpolated slot sanitized.
safe_category = _safe_for_stderr(w.category)
safe_message = _safe_for_stderr(w.message)
click.echo(
    f"protokit lint: warning [{safe_category}]: {safe_message}",
    err=True,
)
```

The cost of sanitizing every slot is one `str.translate` call per
field per emission — negligible at any realistic volume. The cost
of *not* sanitizing is a latent injection vector unlocked the
moment a future emission site forgets construction-time
sanitization.

**Pattern**: when writing a sanitization function call in an
interpolation expression, count all the `{...}` slots in the
f-string and verify every one calls the sanitizer. The type-system
argument ("it's a `Literal`, it's bounded") is the wrong level of
defense for a runtime sanitization layer; the sanitization layer
exists precisely because the type system cannot be trusted at
runtime.

### Unicode line-terminator widening (U+0085, U+2028, U+2029)

(Added 2026-05-12 from the D5 U5 ce:review.) The original
sanitization scope was ASCII control characters: `range(0x20)` plus
`0x7F` DEL. This covers `\n` (0x0A), `\r` (0x0D), NUL, ESC, and all
other ASCII control codepoints. The U5 adversarial reviewer
identified a gap above 0x7F: Unicode-defined line terminators
**U+0085 NEXT LINE (NEL)**, **U+2028 LINE SEPARATOR**, and
**U+2029 PARAGRAPH SEPARATOR**.

A Python terminal does not render these as line breaks — the
attacker payload appears on the same line. But Unicode-aware log
aggregators — Datadog, Splunk, AWS CloudWatch Logs — split records
on them per the Unicode line-terminator rules. An operator
inspecting stderr locally sees one line; the aggregator sees two
records, with the second beginning with a forged `error[lint-...]:`
prefix indistinguishable from a real CLI emission.

The fix adds three entries to `_CONTROL_CHAR_TABLE` (see the full table definition in the **Solution** section above):

```python
_CONTROL_CHAR_TABLE[0x85] = ord(" ")    # U+0085 NEXT LINE (NEL)
_CONTROL_CHAR_TABLE[0x2028] = ord(" ")  # U+2028 LINE SEPARATOR
_CONTROL_CHAR_TABLE[0x2029] = ord(" ")  # U+2029 PARAGRAPH SEPARATOR
```

**Broader principle**: a sanitization function that defends against
"newline injection" must enumerate the codepoints **the downstream
consumer treats as a record boundary**, not just the codepoints the
terminal renders as line breaks. The threat model is what the log
aggregator / XML parser / JSON parser will split on, which is a
superset of what `echo` renders. The full set for the line-
terminator family is:

| Codepoint | Name | Terminal | Aggregators |
|-----------|------|----------|-------------|
| U+000A | LF (line feed) | Yes | Yes |
| U+000D | CR (carriage return) | Yes | Yes |
| U+0085 | NEL (next line) | No | Yes (Unicode) |
| U+2028 | LINE SEPARATOR | No | Yes (Unicode) |
| U+2029 | PARAGRAPH SEPARATOR | No | Yes (Unicode) |

A sanitization function that only covers the "terminal renders as
line break" set silently passes a review that tests with terminals
while remaining exploitable via aggregator-targeted payloads. When
a sanitization table is built programmatically from a `range()`,
`range(0x20)` covers ASCII control chars but stops well before the
Unicode terminator range (U+0085 is at decimal 133, above 0x1F = 31)
— making this an easy gap to miss without an explicit threat-model
check.

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
- [[github-actions-expression-injection-env-block-mitigation-2026-05-13]] —
  the GH Actions YAML-layer analog. This doc covers attacker-controlled
  module names interpolated into stderr lines via f-string (breaking
  the receiver's line parser); the cross-ref doc covers attacker-
  controlled values interpolated into shell scripts via `${{ }}`
  template expressions (breaking the shell's quoting). Same principle
  ("treat dynamically-supplied metadata as user-controlled input and
  sanitise/route at the output boundary"), different output boundary:
  Python stderr line vs. YAML template substitution that feeds bash.
  The architectural posture section's spatial-scope-audit checklist
  extends naturally to GH Actions — every `${{ }}` in a `run:` block
  is an audit site analogous to every `Path.is_file()` /
  `importlib.import_module` in Python.
