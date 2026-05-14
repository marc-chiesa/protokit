---
title: "Formatter SystemExit bypass flips CLI exit code from 1 to 0"
date: 2026-04-19
last_updated: 2026-05-07
category: docs/solutions/security-issues
module: protokit.formatters
problem_type: security_issue
component: tooling
severity: critical
symptoms:
  - "A formatter registered via --formatter-module could call sys.exit(0) and override the CLI's exit code"
  - "CI gate exits 0 (compatible) even when the compat check found incompatibilities"
  - "try/except Exception silently lets SystemExit through because SystemExit inherits from BaseException, not Exception"
root_cause: logic_error
resolution_type: code_fix
related_components: [development_workflow, testing_framework]
tags:
  - exit-code
  - systemexit
  - baseexception
  - formatter
  - plugin-system
  - ci-gate
  - pytest
  - except-exception
---

# Formatter SystemExit bypass flips CLI exit code from 1 to 0

## Problem

A formatter plugin registered via protokit's `--formatter-module`
flag could call `sys.exit(0)` mid-render and silently flip the CLI's
exit code from `1` (incompatible schema) to `0` (compatible),
defeating the CI gate the README explicitly promises. Root cause:
`except Exception` does not catch `SystemExit`, because `SystemExit`
inherits from `BaseException`, not from `Exception`.

## Symptoms

- A CI pipeline using `protokit compat ci` passes green on an
  incompatible schema change when a buggy or malicious formatter
  plugin calls `sys.exit(0)`.
- No error message is printed; the process simply exits with code
  `0` whenever the formatter runs.
- The formatter's `sys.exit` call propagates silently through
  `run_formatter_safely` as if the exception handler weren't there,
  because `SystemExit` is invisible to `except Exception`.
- The bug is non-obvious to catch in testing because most formatter
  test suites exercise `ValueError` / `RuntimeError` paths only.

## What Didn't Work

The original implementation (commit `06fed4e`, Phase 1.5b Unit 5
wire-up) guarded formatter calls with `except Exception`:

```python
try:
    with redirect_stdout(buffer):
        output = fn(report, ctx)
except Exception as exc:
    error_exit(f"formatter '{name}' raised {type(exc).__name__}: {exc}")
```

This appears comprehensive but silently excludes the entire
`BaseException` branch. The Phase 1.5b plan document explicitly
required "any uncaught exception from a formatter... exits with
code 2" (`docs/plans/2026-04-18-001-feat-pluggable-formatters-junit-plan.md`),
but the implementation narrowed "any uncaught exception" to the
`Exception` subtree without recognising that `SystemExit` lives
outside it.

**Prior precedent caught this class of bug for rule plugins but the
fix was not generalised.** (session history) In the Phase 1 schema
checker work (April 13-14, 2026), a Codex adversarial reviewer
flagged the same structural issue against
`SchemaChecker._dispatch_field_plugin` /
`_dispatch_message_plugin`:

> "The plugin 'exception safety' guarantee is false. Dispatch only
> catches `Exception`, so a rogue plugin can `raise SystemExit` or
> `KeyboardInterrupt` and abort the process outright."

That Phase 1 fix was scoped to rule-plugin dispatch and deliberately
left `SystemExit` uncaught — the reasoning was "if a rule plugin
calls `sys.exit()`, the process should exit." That reasoning does
not hold for formatters, because the formatter's `sys.exit()`
overrides a verdict the CLI has already computed. The class of bug
was known; the fix was not extended when the formatter path landed
in Phase 1.5b.

## Solution

Add an explicit `except SystemExit` clause **before** the general
`except Exception` handler. Python evaluates `except` clauses in
order, so placing the `SystemExit` handler first ensures it is
caught and routed through the same `error_exit` path (exit code 2)
as all other formatter failures.

**Before** (`src/protokit/_cli_utils.py`):

```python
def run_formatter_safely(fn, report, ctx, *, name):
    buffer = io.StringIO()
    try:
        with redirect_stdout(buffer):
            output = fn(report, ctx)
    except Exception as exc:
        error_exit(f"formatter '{name}' raised {type(exc).__name__}: {exc}")
    ...
```

**After:**

```python
def run_formatter_safely(fn, report, ctx, *, name):
    buffer = io.StringIO()
    try:
        with redirect_stdout(buffer):
            output = fn(report, ctx)
    except SystemExit as exc:
        # SystemExit subclasses BaseException, not Exception, so
        # the general handler below would let it through. A
        # formatter calling sys.exit(0) would otherwise flip the
        # CI exit code from 1 (incompatible) to 0 (compatible),
        # defeating the gate. Forced through error_exit so the
        # exit code stays the report's verdict.
        error_exit(
            f"formatter '{name}' called sys.exit({exc.code!r}); "
            "formatters must return str only"
        )
    except Exception as exc:
        error_exit(f"formatter '{name}' raised {type(exc).__name__}: {exc}")
    ...
```

## Why This Works

Python's exception hierarchy splits at the top into two branches:

```
BaseException
├── SystemExit          raised by sys.exit() / raise SystemExit
├── KeyboardInterrupt   raised by Ctrl-C (SIGINT)
├── GeneratorExit       raised inside generators on close
└── Exception           everything "normal"
    ├── ValueError
    ├── RuntimeError
    └── ...
```

`except Exception` only catches the bottom branch. When a formatter
calls `sys.exit(0)`, Python raises `SystemExit(0)`, which belongs to
the top branch. The `except Exception` clause does not see it; the
exception unwinds the entire call stack until Python's default
handler catches it and terminates the process with exit code `0`.
Adding `except SystemExit` first intercepts the escape before it
leaves `run_formatter_safely`, converts it into a controlled
`error_exit` (exit code `2`), and preserves the CLI's promise that
the exit code reflects the underlying schema report, not anything
the formatter chose to do.

There is a design subtlety worth capturing for future readers: the
Phase 1 checker's rule-plugin dispatch *also* caught only `Exception`
and left `SystemExit` uncaught, and that was arguably defensible —
a rule plugin calling `sys.exit()` during verdict computation is
ambiguous (does the plugin want the process to die, or is it
mis-using the hook?) and the team chose "let the process die." That
same reasoning does not hold for formatter dispatch. By the time a
formatter runs, the verdict has already been computed; the formatter
is purely rendering. Any `sys.exit()` from a formatter is a contract
violation, never a legitimate process-termination request, so the
right response is to intercept it and surface a controlled
exit-code-2 error. (session history)

## Prevention

### Regression test

Add to the formatter test suite (`tests/test_formatters_cli.py` in
protokit; adapt paths/fixture names for other projects):

```python
def test_systemexit_in_formatter_does_not_flip_exit_code(tmp_path):
    pack = _write_pack(tmp_path, """
        import sys
        from protokit.formatters import FormatterKind
        def evil(report, ctx):
            sys.exit(0)
        FORMATTERS = [("evil", evil, FormatterKind.DIFF)]
    """)
    result = CliRunner().invoke(diff_main, [
        str(unequal_messages_files),
        "--formatter-module", str(pack),
        "--format", "evil",
    ])
    # Must be exit 2 (contract violation), NOT exit 0 (what the
    # formatter tried to force).
    assert result.exit_code == 2
    assert "called sys.exit" in result.output
```

Pair it with a `test_non_string_return_rejected` and a
`test_stdout_write_guard` test — the three together cover the
formatter contract's three failure modes.

### General Python pattern

Whenever process-control integrity matters (CI gates,
exit-code-driven automation, lifecycle hooks, any code whose
caller interprets the process exit code), be explicit about the
full `BaseException` tree. `except Exception` alone is insufficient.
Choose one of:

- **Explicit `except SystemExit` (and `KeyboardInterrupt` on
  trust-delegation surfaces) before the general handler** —
  preferred when you want fine-grained per-escape messaging. This is
  what this fix does for the formatter dispatch surface; the
  rule-pack module-body load surface needs both, see the per-surface
  guidance in
  `docs/solutions/security-issues/keyboardinterrupt-baseexception-bypass-rule-pack-load-2026-05-07.md`.
- **`except BaseException` with deliberate re-raise** — appropriate
  when all escapes should be treated uniformly. Be careful: this
  also catches `KeyboardInterrupt`, which usually means the user
  wanted to stop the process — fine on dispatch surfaces, NOT fine
  on user-code-loading surfaces where a pack body raising
  `KeyboardInterrupt` is adversarial input rather than user intent.

Never assume `except Exception` is a catch-all. The name
"Exception" is a *category*, not a synonym for "anything
throwable."

### Symmetric surface — verify pack-loading path

(session history) A related surface that may need the same
treatment: `_load_rule_packs` / `_load_formatter_packs` in
`src/protokit/_cli_utils.py` and `src/protokit/schema/cli.py`. Both
run `importlib.import_module(name)` under `except Exception`. A
pack module that calls `sys.exit(0)` at module import time (before
any formatter or rule registers) would also escape and flip the
exit code. Verify whether to extend the `except (SystemExit,
Exception)` treatment to the pack-loading path, or document that
pack modules must not call `sys.exit()` at import time.

**Update (2026-05-07 / extended 2026-05-09):** The "Symmetric
surface" prediction named two analogous load-time surfaces.
**Both** were eventually confirmed and closed, but in **different
deliveries** of the protokit-lint D3 work, not a single unit.

Lint-side surface — `_load_user_rule_pack` in
`src/protokit/schema/lint/_cli_utils.py`:

- The `SystemExit` half landed in **D3 Unit 3** (commit `4a17632`):
  the `except SystemExit` first / `except Exception` next pattern
  from this learning.
- The `KeyboardInterrupt` half — predicted parenthetically in this
  doc's Prevention section as "possibly `KeyboardInterrupt`" —
  turned out to be REQUIRED on the rule-pack surface (not
  "possibly"). The D3 Unit 3 ce:review adversarial reviewer
  constructed the bypass and the fix landed in commit `1249b10`.
  The full per-surface rationale is captured in
  `docs/solutions/security-issues/keyboardinterrupt-baseexception-bypass-rule-pack-load-2026-05-07.md`.
- A second, distinct vector was discovered on the same surface
  (`module.__name__` newline injection forging fake
  `error[lint-…]:` lines on stderr); see
  `docs/solutions/security-issues/module-name-newline-injection-stderr-forge-2026-05-07.md`.

Compat-side surface — `load_formatter_packs` in
`src/protokit/_cli_utils.py` (this is the surface the original
"Symmetric surface" callout explicitly named alongside
`_load_rule_packs`):

- The `SystemExit` half landed in **D3 Unit 5** (commit `53f2376`)
  with the same `except SystemExit` first / `except Exception`
  next pattern.
- The `KeyboardInterrupt` half landed in the **D3 Unit 5
  ce:review follow-up** (commit `7bebc6b`) once the rule-pack
  learning's per-surface framework was applied to the compat
  sibling. The deferral reasoning that originally kept
  `KeyboardInterrupt` propagating ("operator's Ctrl-C still tears
  the process down") was identified as the same reasoning the
  rule-pack ce:review had to walk back; both `SystemExit` and
  `KeyboardInterrupt` are required on every load surface where
  user-supplied Python is executed at module body, regardless of
  which CLI it lives behind.
- The `module.__name__` newline injection vector (originally
  observed on the lint side) was confirmed to apply to the
  compat side too — the user-supplied `--formatter-module`
  argument is interpolated into stderr error messages with the
  identical injection shape. The mitigation (repr-quote the
  module name via `{name!r}`) landed in the same Unit 5
  ce:review follow-up commit.

**Lesson for future similar predictions** (extended): when a
"Symmetric surface" callout names two surfaces in different
modules, treat each as its own delivery item with its own ship
date. The 2026-05-07 first-pass update conflated the two and
named only the lint surface's commits — leaving readers to
discover (during the U5 ce:review of this same learning) that
the compat surface had not actually shipped yet. Plan-letter
parity (one surface) and plan-spirit parity (every analogous
surface) diverge often enough that the doc-update step should
explicitly enumerate every named surface, not just the first
one closed.

The original lesson still holds: when a "Symmetric surface"
callout names a parenthetical "possibly," re-evaluate the
parenthetical against the new surface's trust boundary at the
time the new surface ships, not in a follow-up pass. The trust
boundary of a *dispatch* surface (formatter rendering) and a
*load* surface (plugin module-body execution) is not the same.

### Architectural posture

In any CLI that drives automation through its exit code, the exit
code is a contract with the caller, not an implementation detail.
No plugin, hook, or formatter should be allowed to influence it
unilaterally. Enforce this structurally:

1. Compute the exit code from the core computation (compat report,
   test results, lint findings) **before** invoking any plugin.
2. Sandbox every plugin call inside a guard that explicitly
   intercepts all `BaseException` subclasses that carry exit
   semantics (`SystemExit` at minimum).
3. State in the plugin API documentation that calling `sys.exit()`,
   `os._exit()`, or `os.abort()` from a plugin is a contract
   violation and will be caught and converted to a controlled exit.
4. Include a `SystemExit`-escape test alongside the standard
   `ValueError`/`RuntimeError` tests in the plugin test suite.

## Related Issues

- Original plan: `docs/plans/2026-04-18-001-feat-pluggable-formatters-junit-plan.md`
  — Phase 1.5b formatter release. The exception-policy contract
  ("any uncaught exception from a formatter... exits with code 2")
  is documented here; this fix is what it takes to actually honor it.
- Brainstorm: `~/.gstack/projects/python_message_differencer/marc-main-brainstorm-phase-1.5b-ci-release-20260418-115400.md`
  — formatter trust model and exception policy rationale.
- Phase 1 precedent: Codex adversarial review of
  `SchemaChecker._dispatch_field_plugin` (April 13-14, 2026)
  flagged the same class of bug for rule plugins; fix was scoped
  to checker-side dispatch and deliberately not extended to formatters
  because formatters didn't exist yet. (session history)
- Fix commit: `a83a6d1` (`fix(formatters): apply ce:review safe-auto
  findings (P0 + P1 + P2/P3 cluster)`).
- [[subprocess-exit-code-validation-test-harness-2026-05-13]] —
  exit-code contract discipline from the INBOUND side (test
  harness consumer reading another tool's exit code). This doc
  covers the OUTBOUND side (CLI emitter wrapping rule execution;
  the exit-code contract visible to callers must not be silently
  bypassed by `SystemExit`). Together they cover both sides of
  the exit-code contract boundary: a CLI must emit honest exit
  codes (this doc) AND a test harness consuming another CLI must
  validate the received exit codes against the tool's documented
  contract (sibling doc). Same underlying invariant ("exit codes
  are a stable cross-process contract"), enforced on both sides
  of the process boundary.
- [[sha256sum-strict-flag-supply-chain-silent-bypass-2026-05-13]] —
  same exit-code-contract principle applied to a CLI tool's flag
  semantics. `sha256sum -c -` without `--strict` exits 0 on
  improperly-formatted input lines (the WARNING is informational,
  not a failure signal). The CI step's apparent success does not
  reflect actual verification. Same broader invariant ("the exit
  code is a contract; violations break automation that depends on
  it") at the shell-tool layer.
- [[github-actions-expression-injection-env-block-mitigation-2026-05-13]] —
  sibling CI-security learning from the same ce:review pass. Both
  cover "things that look right in CI logs but aren't": this doc
  covers `sys.exit()` bypassing exit-code wrappers; the cross-ref
  doc covers `${{ }}` injection bypassing shell quoting. Different
  surfaces, same theme of silent-failure-mode prevention at process
  / workflow boundaries.
