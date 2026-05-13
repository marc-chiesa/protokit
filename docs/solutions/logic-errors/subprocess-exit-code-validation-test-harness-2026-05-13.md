---
title: "Assert subprocess exit codes explicitly in test harness wrappers; empty stdout is not a success signal"
date: 2026-05-13
category: logic-errors
module: tests/parity
problem_type: logic_error
component: testing_framework
symptoms:
  - "Happy-path tests pass when the wrapped subprocess actually crashed"
  - "Sad-path tests fail with misleading 'expected BOTH tools to fire' rather than 'tool exited 1'"
  - "Buf exit 1 with 'resultRules was empty' (deprecated rule, malformed buf.yaml) returns empty findings list"
  - "Protokit exit 127 (CLI rename causing ImportError) returns empty findings list"
root_cause: logic_error
resolution_type: code_fix
severity: high
tags:
  - subprocess
  - exit-codes
  - silent-green
  - parity-harness
  - test-infrastructure
  - buf-parity
  - external-tool
  - noreturn
  - protokit-lint
---

# Assert subprocess exit codes explicitly in test harness wrappers; empty stdout is not a success signal

## Problem

A test harness that wraps an external binary via `subprocess.run(check=False)`
and parses stdout for results will silently pass happy-path tests when the
external tool exits with an error code and empty stdout. The empty-stdout
fall-through is indistinguishable from "clean lint" — the harness returns
`[]` findings, the test compares "neither tool fired" against
`expected_fires=False`, and the suite reports green even though the tool
never actually ran.

## Symptoms

- A happy-path parity test (`expected_fires=False`) passes when buf exits
  1 (e.g., `"resultRules was empty"` from a misconfigured buf.yaml or an
  upstream-deprecated rule on tool upgrade) with empty stdout.
- A sad-path parity test (`expected_fires=True`) fails with
  `"expected BOTH tools to fire, buf_fired=False"` rather than the actual
  diagnosis `"buf exited 1 with stderr: resultRules was empty"`.
- For protokit: exit 127 (binary not on PATH after `which` succeeded),
  128+signal (OOM kill), or 130 (SIGINT) all silently return `[]`.
  An accidental CLI rename (`from protokit.cli import main` becoming an
  ImportError) silently makes every parity test report "neither tool
  fired" — the entire suite goes green when the harness's invocation is
  broken.
- The original protokit guard `if result.returncode == 2: pytest.fail(...)`
  only catches the documented internal-error exit code, not the broader
  family of non-success codes.

## What Didn't Work

The Phase A harness (commit `c270489`) handled only the most-obvious
failure cases:

```python
# BEFORE — run_buf_lint: NO exit-code check at all
result = _run_subprocess(
    [str(buf_binary_path), "lint", "--error-format=json", "."],
    cwd=fixture_dir, label="buf lint",
)
findings: list[dict[str, Any]] = []
if not result.stdout.strip():
    return findings   # <-- silently returns [] on any non-success exit

# BEFORE — run_protokit_lint: only caught exit 2
if result.returncode == 2:
    pytest.fail(...)   # <-- 127, 128+sig, 130 fall through
if not result.stdout.strip():
    return []
```

Two real-world triggers surfaced during Phase A bring-up and ce:review:

1. `buf lint` invoked with `use: [IMPORT_NO_WEAK]` after buf v1.69.0
   deprecated the rule (`categories=[]`, `deprecated=true`): buf exits 1
   with `"Failure: it looks like you have found a bug in buf...
   resultRules was empty"` on stderr, empty stdout — happy-path
   silently green.
2. Hypothetical: a CLI rename causing `from protokit.cli import main` to
   `ImportError`: protokit exits 127 with empty stdout — every parity
   test in the suite reports "neither tool fired" as a clean run.

## Solution

Enumerate each tool's documented success exit codes as a module-level
`frozenset` constant, and assert membership before any stdout parsing.
The check must come **before** the empty-stdout fall-through, not after.

```python
# AFTER — tests/parity/conftest.py (commit 5eba36b)

#: Buf exit codes that the harness treats as "ran successfully":
#:   0   = clean (no findings)
#:   100 = findings present
#: Anything else (1 = error / misconfiguration, 2 = unknown command,
#: 127 = binary missing, 128+signal, etc.) is a buf-side failure that
#: would otherwise produce silent-green tests via the empty-stdout
#: fall-through. The check below makes those failures loud.
_BUF_OK_EXIT_CODES: frozenset[int] = frozenset({0, 100})


def run_buf_lint(
    buf_binary_path: Path, fixture_dir: Path
) -> list[dict[str, Any]]:
    result = _run_subprocess(
        [str(buf_binary_path), "lint", "--error-format=json", "."],
        cwd=fixture_dir, label="buf lint",
    )
    if result.returncode not in _BUF_OK_EXIT_CODES:
        pytest.fail(
            f"buf lint exited {result.returncode} "
            f"(expected 0=clean or 100=findings) on cwd={fixture_dir}. "
            f"stderr: {result.stderr!r}; stdout: {result.stdout!r}"
        )
    findings: list[dict[str, Any]] = []
    if not result.stdout.strip():
        return findings
    ...


def run_protokit_lint(
    fixture_dir: Path, proto_relpath: str
) -> list[dict[str, Any]]:
    result = _run_subprocess(...)
    # protokit lint exit codes (R20 ladder):
    #   0 = clean (no findings)
    #   1 = findings present (or WARNINGs exceed --max-warnings)
    #   2 = lint-internal error / click usage error
    # Any other exit code (e.g., 127 from CLI rename causing
    # ImportError, 128+signal from OOM, 130 from SIGINT) would
    # otherwise fall through ``if not result.stdout.strip(): return []``
    # and produce a silent-green parity test even when the harness's
    # CLI invocation is broken.
    if result.returncode not in (0, 1):
        pytest.fail(
            f"protokit lint exited {result.returncode} "
            f"(expected 0=clean or 1=findings) on {proto_path}; "
            f"stderr: {result.stderr!r}; stdout: {result.stdout!r}"
        )
    if not result.stdout.strip():
        return []
```

A companion type-system fix lands the `NoReturn` contract for the
subprocess except arms. `_run_subprocess` declares
`-> subprocess.CompletedProcess[str]`, but two except branches call
`pytest.fail()` (which is `NoReturn`). Tests aren't strict-typed, so
mypy can't catch a future arm that forgets to NoReturn-call. The fix
extracts a typed helper and pins the reachability invariant:

```python
def _fail_subprocess(msg: str) -> NoReturn:
    """``pytest.fail`` typed as ``NoReturn`` so mypy/readers see the
    contract: ``_run_subprocess``'s except arms never fall through."""
    pytest.fail(msg)
    raise AssertionError("unreachable")  # defense vs stub rot


def _run_subprocess(...) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(...)
    except subprocess.TimeoutExpired as exc:
        _fail_subprocess(...)  # typed NoReturn; mypy enforces
    except KeyboardInterrupt:
        raise
    except SystemExit:
        raise
    except Exception as exc:
        _fail_subprocess(...)  # typed NoReturn; mypy enforces
```

## Why This Works

Each tool's success exit codes are part of its stable public contract:

- **buf** exits `0` (clean) or `100` (findings present). Any other code
  is anomalous: the tool crashed, the module was misconfigured, or buf
  hit an upstream bug like `"resultRules was empty"`.
- **protokit** exits `0` (clean) or `1` (findings present); `2` is
  reserved for lint-internal / click usage errors. Other exit codes
  (127 binary-not-found, 128+N signal, 130 SIGINT) all indicate the
  wrapper failed to invoke the tool successfully.

The empty-stdout fall-through (`if not result.stdout.strip(): return []`)
is a legitimate code path **only when** the tool ran successfully and
emitted nothing because it had nothing to emit. That precondition
must be enforced first. Enumerating the success codes as a constant
makes the contract machine-checkable and the diagnostic actionable
(the failure message names the actual exit code and the stderr).

Including `stderr` in every `pytest.fail` message is the second half
of the discipline: stderr is the primary surface for actionable
diagnostics when external tools crash (buf's `"resultRules was empty"`,
Python's ImportError traceback, etc.).

## Prevention

A checklist for any new subprocess wrapper in a test harness:

1. **Enumerate success exit codes at module level** as a `frozenset[int]`
   constant with an inline comment naming each code and what it means.
   Do not inline magic numbers like `returncode == 2` — they have no
   self-documenting context.

2. **Place the exit-code check immediately after `subprocess.run()`**,
   before ANY `if not result.stdout.strip()` guard. The ordering matters:
   empty stdout from a crashed tool is indistinguishable from empty
   stdout from a clean run, so the exit code must rule out crashes first.

3. **Always include `result.stderr` in the `pytest.fail()` message** —
   it is the primary diagnostic surface when a tool crashes. A failure
   message that says `"buf lint exited 1"` without stderr forces the
   developer to re-run locally; with stderr the diagnosis ("`resultRules
   was empty`") is in the failed-test log.

4. **Do not assume exit-code conventions are universal across tools.**
   buf uses `100` for "findings present"; protokit uses `1`; many tools
   use `1` for "any error". Look up the actual contract for each tool;
   document it in the constant's comment.

5. **Guard explicitly against** these exit codes: `1` (misconfig / unknown
   on tools that don't use it for findings), `127` (binary not found
   after PATH lookup succeeded — possible after a `which` race), `128+N`
   (OOM kill / signal termination), `130` (SIGINT from Ctrl-C, which
   means the test was likely cancelled but the harness should still
   surface it).

6. **Extract the fail-path as a `-> NoReturn` helper** when the
   subprocess wrapper has multiple except arms. This makes mypy enforce
   the unreachability invariant: a future contributor adding a new
   except arm cannot silently introduce a `None` return path that
   callers then index without a guard.

7. **For each new subprocess wrapper, add a sanity test** that invokes
   the tool with a known-bad input (e.g., a syntactically-broken
   fixture) and asserts the wrapper raises `pytest.Failed` — pinning
   that the exit-code guard fires rather than silently returning `[]`.
   This costs ~10 lines and prevents the entire failure class from
   coming back.

## Related Issues

- [[matcher-backend-path-resolution-skew-silently-empties-output-2026-05-02]] —
  same "silent-green on a broken pipeline" symptom class at a different
  boundary. That doc covers path-resolution skew between protoc and
  protoxy producing `root_files = ()`. This doc covers subprocess exit-
  code skew producing `findings = []`. Together they map two distinct
  mechanisms for the same symptom: a test reports a green run on a
  pipeline that never produced real output.
- [[formatter-systemexit-exit-code-bypass-2026-04-19]] — exit-code
  contract from the OUTBOUND side (CLI emitter wrapping rule execution).
  This doc is the INBOUND companion (test harness consumer reading
  another tool's exit code). Together they cover both sides of the
  exit-code contract boundary.
- [[pytest-static-analysis-gate-ratchet-2026-05-02]] — the `_run()`
  subprocess helper at `tests/test_static_analysis.py` does check
  `result.returncode == 0` explicitly and is the canonical correct
  pattern in this codebase. The new harness's failure was not following
  the established pattern.
- [[keyboardinterrupt-baseexception-bypass-rule-pack-load-2026-05-07]] —
  the triple-arm guard (`SystemExit` + `KeyboardInterrupt` + `Exception`)
  is required at every new `subprocess.run` site. The new harness uses
  this pattern; this doc captures the companion concern of exit-code
  validation after the triple-arm guard returns the subprocess result.
- Commits `c270489` (Phase A — original wrappers without exit-code
  guards) and `5eba36b` (ce:review follow-up — adds the guards).
- 10-reviewer ce:review at `.context/compound-engineering/ce-review/
  20260513-091500-u8phaseA/` — correctness, reliability, adversarial,
  and testing reviewers all independently converged on this finding as
  P1.
