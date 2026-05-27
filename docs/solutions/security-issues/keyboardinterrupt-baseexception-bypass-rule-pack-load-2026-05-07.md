---
title: "KeyboardInterrupt at rule-pack module load bypasses SystemExit and Exception guards"
date: 2026-05-07
last_updated: 2026-05-11
category: docs/solutions/security-issues
module: protokit.schema.lint
problem_type: security_issue
component: tooling
severity: critical
symptoms:
  - "A user-supplied rule pack whose module body raises KeyboardInterrupt bypasses both the `except SystemExit` and `except Exception` arms of `_load_user_rule_pack`"
  - "Click renders 'Aborted!' with exit code 1 and no `error[lint-rule-pack-load]:` stable prefix appears on stderr"
  - "CI scripts that gate on `error[lint-` prefix on stderr see silence and may treat the failed pack load as a benign cancellation"
  - "The pattern that closed the SystemExit-bypass class of bug (formatter-systemexit-exit-code-bypass-2026-04-19) covers only one of the three BaseException-not-Exception siblings"
root_cause: logic_error
resolution_type: code_fix
related_components: [development_workflow, testing_framework]
tags:
  - keyboardinterrupt
  - baseexception
  - except-exception
  - rule-pack
  - dynamic-import
  - plugin-system
  - stable-prefix
  - protokit-lint
---

# KeyboardInterrupt at rule-pack module load bypasses SystemExit and Exception guards

## Problem

A user pack loaded via `protokit lint --rule-pack MODULE` whose module
body raises `KeyboardInterrupt` (intentionally, or via a signal call)
escapes both arms of the `except SystemExit` / `except Exception`
guard inherited from the formatter-systemexit fix. The CLI exits 1
with `Aborted!` from Click instead of exit 2 with the stable
`error[lint-rule-pack-load]:` prefix the contract requires.

## Symptoms

- A `--rule-pack` MODULE whose body contains `raise KeyboardInterrupt()`
  (or `signal.raise_signal(signal.SIGINT)`) terminates the CLI with
  Click's `Aborted!` banner and exit code 1.
- No `error[lint-rule-pack-load]:` stable prefix is emitted to stderr,
  so CI scripts grepping `^error\[lint-` see no signal.
- The exit-code shape (1) collides with the U4a-future "findings
  emitted" code, so a CI gate that learns to treat exit 1 as "lint
  passed but found problems" cannot distinguish a real result from
  a silently-broken pack load.
- The vector is trivially provokable from adversarial pack code;
  benign packs have no reason to raise `KeyboardInterrupt` at module
  body, so the practical occurrence is a security or QA concern, not
  an end-user accident.

## What Didn't Work

The `--rule-pack` loader inherited the SystemExit-FIRST pattern from
`docs/solutions/security-issues/formatter-systemexit-exit-code-bypass-2026-04-19.md`.
The pre-fix shape:

```python
try:
    module = importlib.import_module(module_name)
except SystemExit as exc:
    error_exit_with_code(
        "rule-pack-load",
        f"kind=import: pack {module_name!r} called sys.exit("
        f"{exc.code!r}) at module-body load time",
    )
except Exception as exc:  # noqa: BLE001
    error_exit_with_code(
        "rule-pack-load",
        f"kind=import: failed to import pack {module_name!r}: "
        f"{type(exc).__name__}: {_scrub_exc_message(exc)}",
    )
```

Two lower-confidence forces deferred the `KeyboardInterrupt` arm into
a follow-up:

- **(session history) The April 19 formatter-systemexit learning's
  Prevention section worded `KeyboardInterrupt` as "possibly"
  needed.** That phrasing was correct for the formatter dispatch
  surface, where `KeyboardInterrupt` from a formatter body is an
  extremely unlikely accident and a Ctrl-C from the user is a
  legitimate process-termination request that should propagate. It
  was carried verbatim into the D3 brainstorm without being
  re-evaluated against the new surface.
- **(session history) The D3 brainstorm explicitly accepted the gap.**
  `docs/brainstorms/2026-05-04-protokit-lint-delivery-3-cli-requirements.md`
  documents the `--rule-pack` catch pattern and states
  "BaseException/KeyboardInterrupt still propagates" as a stated
  design choice, not an oversight. The U3 implementation followed
  the brainstorm's pattern, and the U3 commit message explicitly
  mirrored the formatter learning's phrasing ("with `except SystemExit`
  FIRST then `except Exception`").

The gap surfaced via the U3 ce:review adversarial reviewer, which
constructed the concrete bypass scenario and demonstrated the
`Aborted!` exit-1 + missing stable prefix combination empirically.
The stated-deferral reasoning held for the formatter dispatch
surface but did not survive contact with the rule-pack dispatch
surface, where the trust boundary is explicitly adversarial-input
("executes arbitrary Python from the named module"). The reviewer's
finding was the trigger to revisit the deferral.

## Solution

Add an explicit `except KeyboardInterrupt` arm between
`except SystemExit` and `except Exception` in `_load_user_rule_pack`.
Order matters for clarity: the BaseException-not-Exception siblings
are enumerated explicitly before the broad `except Exception`
fallback.

**After** (`src/protokit/schema/lint/_cli_utils.py`):

```python
try:
    module = importlib.import_module(module_name)
except SystemExit as exc:
    error_exit_with_code(
        "rule-pack-load",
        f"kind=import: pack {module_name!r} called sys.exit("
        f"{exc.code!r}) at module-body load time",
    )
except KeyboardInterrupt:
    error_exit_with_code(
        "rule-pack-load",
        f"kind=import: pack {module_name!r} raised KeyboardInterrupt "
        f"at module-body load time",
    )
except Exception as exc:  # noqa: BLE001 -- intentional broad fallback; SystemExit and KeyboardInterrupt handled above
    error_exit_with_code(
        "rule-pack-load",
        f"kind=import: failed to import pack {module_name!r}: "
        f"{type(exc).__name__}: {_scrub_exc_message(exc)}",
    )
```

The `KeyboardInterrupt` arm has no `as exc` binding because the
exception object carries no payload worth interpolating — its name
in the message is enough. Routing through `error_exit_with_code`
preserves the stable-prefix + exit-2 contract. Order is chosen for
clarity, not correctness: the three exception types are siblings
(none is a subclass of another), but enumerating the
non-`Exception` BaseException subclasses before the broad catch
mirrors the BaseException tree visually for readers.

## Why This Works

Python's exception hierarchy splits at `BaseException`:

```
BaseException
├── SystemExit          raised by sys.exit() / raise SystemExit
├── KeyboardInterrupt   raised by Ctrl-C (SIGINT) / raise KeyboardInterrupt
├── GeneratorExit       raised inside generators on close
└── Exception           everything "normal"
    ├── ValueError
    ├── RuntimeError
    └── ...
```

`except Exception` catches only the bottom branch.
`issubclass(KeyboardInterrupt, Exception)` is `False`. Without the
explicit arm, a `raise KeyboardInterrupt()` in a pack module body
unwinds past the loader, past the Click command callback, and into
Click's own `BaseException` handler in `Command.invoke`, which prints
`Aborted!` to stderr and re-raises. The CLI process terminates with
exit code 1 (Click's chosen convention) and zero `error[lint-…]:`
output.

Adding `except KeyboardInterrupt` intercepts the escape inside the
loader and routes it through the same `error_exit_with_code` path as
`SystemExit`, restoring exit-2 + stable prefix. The arm sits
*between* `SystemExit` and `Exception` to mirror the BaseException
tree visually — readers scanning the code see the three top-level
non-`Exception` siblings the loader chose to enumerate before
falling through to the broad catch.

`GeneratorExit` is the third non-`Exception` sibling. For
module-body import code it is essentially unreachable —
`GeneratorExit` is raised inside generator functions on `.close()`,
and `importlib.import_module` does not use generator mechanics. A
deliberate decision was made to NOT add `except GeneratorExit`; the
risk is near-zero and adding it would be confusing boilerplate. The
`except Exception as exc` clause's `noqa: BLE001` already documents
that the broad fallback is intentional.

**`BaseExceptionGroup` (Python 3.11+) is a fourth direct
`BaseException` subclass.** A pack body that does
`raise BaseExceptionGroup("oops", [ValueError("x")])` would unwind
past all three explicit arms (since `BaseExceptionGroup` is not a
subclass of `Exception`, `SystemExit`, or `KeyboardInterrupt`).
Click's top-level handler would then render an unhandled-exception
traceback and exit non-zero, which is not the `Aborted!` shape from
the `KeyboardInterrupt` bypass but still violates the stable-prefix
contract. As of commit `94708dd`, this surface is NOT explicitly
guarded; the deliberate decision is the same as for `GeneratorExit`
(near-zero practical likelihood from a benign or even adversarial
pack — `BaseExceptionGroup` is a contrived choice when simpler
bypasses exist) but should be re-evaluated if Python plugin
ecosystems start using `except*` patterns more widely. Adding
`except BaseExceptionGroup` between the `KeyboardInterrupt` arm and
the `Exception` arm is mechanical if the team chooses to close the
gap proactively.

## Prevention

### Regression test

Pair the existing `pack_sys_exits.py` fixture (which covers the
`except SystemExit` arm) with a `pack_raises_keyboard_interrupt.py`
fixture in `tests/schema/lint/cli/user_packs/`:

```python
"""Synthetic pack — module body raises KeyboardInterrupt directly.

Tests the ``except KeyboardInterrupt`` guard in
``_load_user_rule_pack``. Without the guard, this propagates past
both ``except SystemExit`` AND ``except Exception``, terminating the
CLI with Click's ``Aborted!`` banner and exit code 1 — no
``error[lint-rule-pack-load]:`` stable prefix.
"""
raise KeyboardInterrupt()
```

And a CLI test asserting the regression behaviour:

```python
def test_pack_module_body_raises_keyboard_interrupt(
    clean_descriptor_set: Path,
) -> None:
    result = CliRunner().invoke(lint_main, [
        "--rule-pack",
        "tests.schema.lint.cli.user_packs.pack_raises_keyboard_interrupt",
        str(clean_descriptor_set),
    ])
    assert result.exit_code == 2
    assert "error[lint-rule-pack-load]:" in result.stderr
    assert "kind=import:" in result.stderr
```

The assertions pin the structural contract (exit code, stable
prefix, `kind=import:` discriminator). They deliberately do NOT
assert the literal substring `"KeyboardInterrupt"` in stderr — that
would couple the test to the exact wording of the message body and
break for no behavioural reason if the message is later rephrased.

(As of commit `94708dd`, the fixture and test do not yet exist —
covered in U4a or U5 hardening pass.)

### General Python pattern

Whenever a code path executes user-supplied or plugin-supplied
Python under an `except SystemExit`/`except Exception` chain, treat
the chain as a per-surface judgment rather than a copy-pasted
template:

- **Both `SystemExit` and `KeyboardInterrupt` are required on
  trust-delegation surfaces** (anywhere user-supplied Python is
  loaded and executed under the CLI's stable-prefix contract). The
  trust boundary is adversarial; both BaseException siblings can be
  raised intentionally and either escape would defeat the contract.
- **`SystemExit` alone is sufficient on dispatch surfaces** where
  `KeyboardInterrupt` should still propagate as a legitimate user
  cancel — typically formatter rendering, status reporting, or any
  long-running operation where Ctrl-C aborting the process is the
  desired UX.
- **`GeneratorExit` is virtually always optional**, but should be
  evaluated explicitly when the surface uses generators or async
  context managers — for plain module-body import code, omitting it
  with a `# noqa` comment is acceptable.

The general pattern: when adding `except SystemExit` to close a
`sys.exit()` bypass on a user-code-execution surface, decide each
sibling explicitly. The presence of `except SystemExit` without a
documented `KeyboardInterrupt` decision is a code smell.

### Symmetric surface — verify and document the deferral, do not copy it

The April 19 formatter-systemexit learning's "Symmetric surface"
callout predicted this exact bypass on the rule-pack loader. The
deferral phrase ("possibly `KeyboardInterrupt`") in the parent
learning's Prevention section was correct for the formatter surface
that produced it, but the phrasing transitively justified an
incomplete fix on the inheriting surface. When extending a security
pattern across surfaces:

- Re-evaluate the deferral against the NEW surface's trust
  boundary, not the originating surface's.
- If the deferral still holds, document the per-surface rationale in
  the implementing code (and ideally in the brainstorm document) —
  not just "follows pattern X" without naming the gap explicitly.
- If the deferral does not hold, close the gap when the new surface
  ships, not in a follow-up pass.

### Architectural posture

The architectural posture from `formatter-systemexit-exit-code-bypass-2026-04-19.md`
applies unchanged: compute the exit code from the core computation
before invoking any plugin; sandbox every plugin call inside a guard
that explicitly intercepts all `BaseException` subclasses with
exit-relevant semantics; state contract violations clearly in the
plugin API docs.

This fix narrows that posture for the rule-pack surface
specifically: `SystemExit` *and* `KeyboardInterrupt` MUST both be
intercepted on rule-pack module-body execution. `GeneratorExit` may
be omitted with a documented justification. `BaseExceptionGroup` is
unaddressed today — see Why This Works above for the deferral
rationale.

### Residual risk — `os._exit()` bypasses Python entirely

A pack module body that calls `os._exit(0)` issues a raw `_exit(2)`
syscall and terminates the process before any Python-level guard
can run. No `except` arm catches it; no stderr is emitted. The CLI
exits with whatever code the pack chose. This is unaddressable at
the Python layer — closing it would require running pack
module-body imports inside a subprocess sandbox, which is out of
scope for D3. The parent learning's Architectural posture item 3
already names `os._exit()` and `os.abort()` in the same family of
contract violations; that posture is inherited unchanged. The
`--rule-pack` flag's help text states "executes arbitrary Python
from the named module," which transitively covers this risk for
operators choosing whether to pass user-supplied module paths.

## Symmetric surfaces — D5 U1 walk-up extension (refreshed 2026-05-11)

The "per-surface judgment" rule in the Prevention section above had
its first concrete extension during D5 U1's ce:review. The lesson
captured: when a guard pattern is added to one I/O surface in a
module, audit ALL I/O surfaces in the same function/module — not
just the headline parse call.

### What the D5 U1 ce:review caught

D5 U1 (`src/protokit/schema/lint/_config.py`) correctly applied the
triple-arm guard to `tomllib.loads` in `_parse_toml_bytes`. The plan
KTD-9 named the principle ("every new D5 boundary that loads or
evaluates user input — `tomllib.load`, `pathspec.PathSpec.from_lines`,
`Path.resolve()`, walk-up file existence checks") but the U1 spec
itself enumerated the guard only for the parse call.

ce:review with 5-persona convergence (correctness 0.92, reliability
0.88 HIGH, kieran-python 0.85, maintainability, adversarial) found
two other I/O sites in the same module that produced unhandled
tracebacks bypassing the stable `error[lint-pyproject-config-load]:`
prefix:

1. **`Path.cwd()` at the entry of `load_pyproject_config`** — raises
   `FileNotFoundError` (OSError subclass) when CWD has been deleted
   (rare for plain CLI but realistic in long-running wrapper processes
   and sandboxed environments).
2. **`Path.is_file()` and `(parent / ".git").exists()` in the
   `_walk_up_find_pyproject` loop body** — raise `PermissionError`
   when a mid-walk-up parent directory is unreadable (e.g. shared CI
   workspaces, containerized environments with restricted mounts).

Each escape produced a Python traceback to stderr rather than the
stable lint prefix, making the failure invisible to CI grep gates.
**The exception class is different from the rule-pack case** —
`OSError` is an `Exception` subclass and IS caught by a bare
`except Exception` arm. But the question isn't "which exception
class?", it's "does the failure route through `error_exit_with_code`
with the stable prefix?" An uncaught traceback bypasses the contract
regardless of which class of exception causes it.

### Fix applied

```python
# Walk-up loop — per-iteration OSError guard
for candidate in (start, *start.parents):
    try:
        pyproject = candidate / "pyproject.toml"
        if pyproject.is_file():
            return pyproject
        if (candidate / ".git").exists():
            return None
    except OSError as exc:
        error_exit_with_code(
            "pyproject-config-load",
            f"walk-up filesystem error at "
            f"{_safe_for_stderr(candidate)}: {_safe_for_stderr(exc)}",
        )

# Path.cwd() — entry-point OSError guard
try:
    cwd = Path.cwd()
except OSError as exc:
    error_exit_with_code(
        "pyproject-config-load",
        f"walk-up aborted: current working directory is unavailable "
        f"(deleted or unreachable): {_safe_for_stderr(exc)}",
    )
```

Note: the walk-up `try/except` wraps the entire for-body, not
individual calls — if `is_file()` raises, the `.git` boundary check
must not run (it would silently skip the boundary and continue
walk-up into attacker-writable parent territory).

### Spatial-scope-audit rule

When a guard pattern is added to one I/O surface, the audit scope is
the **entire function and module**, not the single line mentioned in
the plan or brainstorm. Practical checklist for Python I/O modules:

- Every `Path.cwd()` call → `try/except OSError` (deleted CWD, sandbox).
- Every `Path.is_file()` / `.exists()` / `.is_dir()` call in a loop
  that may traverse attacker-reachable directories → `try/except
  OSError` per iteration (with the wrap scope being the iteration
  body, not the individual call).
- Every `path.read_bytes()` / `path.read_text()` call → discriminated
  `OSError` handling (FileNotFoundError vs PermissionError vs
  IsADirectoryError vs other).
- Every `tomllib.loads` / `json.loads` / similar parse on
  user-controlled bytes → triple-arm `(SystemExit,
  KeyboardInterrupt, Exception)` per the headline pattern in this
  doc.
- Every `importlib.import_module` call → same triple-arm.

The "route to stable prefix" rule (the deeper principle behind both
this doc's original scope and the spatial-scope extension): every
`except` arm that handles a user-reachable I/O failure MUST route
to `error_exit_with_code("the-stable-code", ...)` rather than
re-raise or swallow.

### Why pressure-test passes miss the spatial extension

Plans and brainstorms describe **primary I/O intent** ("load and
parse the TOML file") without enumerating the implicit secondary
I/O operations that implement it (CWD resolution, walk-up stat
calls, symlink resolution). Pressure-test passes read intent;
ce:review reads code. The headline I/O surface ends up in
plan-level checklists; the implicit surfaces only become visible
when the code exists. The institutional pattern
(`apply-institutional-learnings-postdating-plan-during-ce-review-2026-05-09.md`)
documents this directly: ce:review is the designated stage for
surfacing gaps the plan phase cannot see.

### Companion fix — source_label parameter for shared helpers

The same D5 U1 ce:review surfaced a separate-but-related pattern:
shared error-emitting helpers must accept caller context as a
parameter so error messages don't misattribute the failure source.
See
`docs/solutions/best-practices/shared-error-helper-source-label-caller-attribution-2026-05-11.md`
for the standalone learning.

### Fix commits

- `c0bbf03` — D5 U1 implementation (the gap was present after this commit)
- `89d84ff` — D5 U1 ce:review follow-ups (the 22-finding fix pass that
  closed the gap; KTD-9 was already named in the plan but the
  spatial-scope audit happened here)
- ce:review run artifact: `.context/compound-engineering/ce-review/20260511-094847-1685ca47/`

## Related Issues

- Parent learning: `docs/solutions/security-issues/formatter-systemexit-exit-code-bypass-2026-04-19.md`.
  Closed the `sys.exit(0)` false-green-CI vector on the formatter
  dispatch surface. Its "Symmetric surface" callout predicted the
  rule-pack loader as the next surface to verify; this learning
  closes both halves of that prediction (the `SystemExit` half
  landed in U3; the `KeyboardInterrupt` half lands in the U3
  ce:review follow-up). The parent doc was refreshed to mark the
  prediction resolved and to harden the "possibly `KeyboardInterrupt`"
  language for trust-delegation surfaces.
- Companion learning: `docs/solutions/security-issues/module-name-newline-injection-stderr-forge-2026-05-07.md`.
  Surfaced from the same U3 ce:review adversarial reviewer pass on
  the same `--rule-pack` trust surface. Distinct attack vector
  (output-channel injection, not exception-hierarchy bypass).
- Brainstorm: `docs/brainstorms/2026-05-04-protokit-lint-delivery-3-cli-requirements.md`.
  Documents the stated deferral ("BaseException/KeyboardInterrupt
  still propagates"). (session history) The brainstorm's
  document-review security-lens reviewer focused on `--rule-pack`
  code-execution and format-injection trust boundaries; the
  KeyboardInterrupt gap was not flagged at brainstorm time, only at
  ce:review time after the implementation crystallised the surface.
- Fix commit: `1249b10` — D3 unit 3 ce:review follow-ups
  (safe_auto + approved gated). The `KeyboardInterrupt` arm landed
  in the safe_auto pass.
- Mirror-image companion (added 2026-05-11): `docs/solutions/best-practices/deprecationwarning-poisons-except-exception-strict-warning-ci-2026-05-11.md`.
  This learning addresses the case where broad `except Exception`
  MISSES a dangerous `BaseException` subclass (KeyboardInterrupt,
  SystemExit). The companion learning addresses the orthogonal case
  on the same kind of defensive boundary: under strict-warning CI
  (`-W error::DeprecationWarning`), a `DeprecationWarning` is
  promoted to a raised exception, AND because `DeprecationWarning`
  IS an `Exception` subclass via `Warning`, the broad
  `except Exception` arm CATCHES it and mis-attributes the
  upstream library deprecation as a local-input error. The
  spatial-scope-audit checklist in this doc's "Symmetric surfaces"
  section (every `Path.is_file()`, every `tomllib.loads`, every
  `importlib.import_module`, every `pathspec.PathSpec.from_lines`)
  is still correct as written, but should be extended with: at
  each of those surfaces, also audit whether the wrapped library
  call could emit a `DeprecationWarning` (or any `Warning`
  subclass) that the broad catch would mis-route under strict-CI.
  Both halves together — what `except Exception` MISSES AND what
  it CATCHES under specific CI conditions — map the full failure
  surface of defensive broad catches at library boundaries.
- [[subprocess-exit-code-validation-test-harness-2026-05-13]] —
  test-harness companion to this doc's triple-arm guard. That doc
  covers what to do AFTER `subprocess.run()` returns successfully
  without triggering any except arm: enumerate the wrapped tool's
  documented success exit codes as a module-level `frozenset` and
  assert membership BEFORE parsing stdout. The two disciplines
  compose at every new `subprocess.run` site — the triple-arm guard
  ensures `KeyboardInterrupt` / `SystemExit` propagate cleanly
  during the call; the exit-code guard ensures a "successful"
  subprocess return that actually crashed (exit 1 + empty stdout)
  fails the test loudly rather than silently returning `[]`.
