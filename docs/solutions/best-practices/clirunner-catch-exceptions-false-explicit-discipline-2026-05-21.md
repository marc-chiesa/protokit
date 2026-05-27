---
title: "Pass catch_exceptions=False explicitly when invoking CliRunner in integration tests"
date: 2026-05-21
category: docs/solutions/best-practices
module: tests/schema/lint/cli/
problem_type: best_practice
component: testing
severity: medium
applies_when:
  - "Writing pytest tests that invoke click commands via click.testing.CliRunner"
  - "The test asserts on exit_code AND parses stdout (JSON, SARIF, XML) — both surfaces are corrupted by a silently-caught crash"
  - "The CLI under test is being newly developed or substantially modified, so unhandled exceptions are a real risk during fixture iteration"
  - "Diagnostic clarity matters — debugging time is dominated by surfacing the real error rather than hunting through tracebacks of the test harness's downstream crash"
tags:
  - click
  - clirunner
  - test-harness
  - exception-handling
  - diagnostic-clarity
  - false-positive-pass
  - integration-test
  - exit-code-discipline
---

# Pass catch_exceptions=False explicitly when invoking CliRunner in integration tests

## Context

`click.testing.CliRunner.invoke()` defaults to `catch_exceptions=True`. When the CLI raises an unhandled exception inside this default, click catches it, stores it in `result.exception`, and surfaces the invocation as `exit_code=1` (matching click's contract for an "uncaught error"). The test never sees the exception unless it explicitly inspects `result.exception` — a step few tests remember to take.

For integration tests that follow the canonical pattern `assert exit_code in (0, 1); payload = json.loads(result.stdout)`, the default `catch_exceptions=True` silently corrupts the diagnostic chain in three steps:

1. The CLI raises an unhandled `AttributeError` / `KeyError` / `TypeError` deep in a formatter, rule, or dependency.
2. `CliRunner` catches it, sets `exit_code=1`, leaves `stdout=''` (the command exited before writing).
3. The test's `exit_code in (0, 1)` guard passes (1 is the allowed-exit space). Then `json.loads('')` raises `json.JSONDecodeError: Expecting value: line 1 column 1 (char 0)`.

The pytest failure surfaces as a `JSONDecodeError` originating in the test helper rather than the real `AttributeError` in the CLI under test. Debug time is spent unwinding the test harness rather than reading the actual stack trace.

Three independent reviewers converged on this trap at the D6d new-U3 ce:review pass (2026-05-21):

- **correctness TG-2**: noted `_run_lint` doesn't check `result.exception` before `json.loads`.
- **kieran-python KP-5**: noted the click runner is "the default everywhere else in the suite" but flagged it as P3 advisory.
- **adversarial ADV-1** (highest-confidence at 0.92): empirically simulated a mid-execution crash → `exit_code=1`, empty `stdout`, invisible `result.exception`, then traced the resulting `JSONDecodeError` from the test helper.

The 3-way convergence is the signal that this is a real diagnostic-quality discipline, not a stylistic preference. The existing codebase already has the canonical-correct pattern documented at `tests/schema/lint/cli/test_version_output.py` — but adopting it everywhere is the discipline.

## Guidance

**Pass `catch_exceptions=False` explicitly on every `CliRunner.invoke()` call inside an integration test that asserts on the CLI's structured output (JSON, SARIF, XML). The default is wrong for this case.**

```python
result = CliRunner().invoke(
    lint_main,
    [...],
    catch_exceptions=False,  # surface unhandled exceptions; do not absorb them
)
```

With `catch_exceptions=False`:

- An unhandled exception in the CLI propagates up to pytest as the actual exception class with its real traceback. Debug time drops to seconds.
- Expected exit codes (the CLI's own `sys.exit(N)` calls + click's user-error exit-2 paths) continue to surface as `result.exit_code` normally — the flag does NOT change CLI-side exit handling, only the test harness's exception-absorption behavior.
- The `assert result.exit_code in (0, 1)` post-condition remains correct and continues to catch the `exit_code == 2` "broken fixture" case as before.

**Three companion disciplines** reinforce the diagnostic-clarity goal:

1. **Centralize the invocation in a test-module helper** (e.g., `_run_lint(pyproject, *, extra_args=...)`). Pass `catch_exceptions=False` once in the helper; every test inherits the discipline.

2. **Return the full result tuple** (`exit_code, parsed_payload, stdout, stderr`) from the helper, not just `exit_code, payload`. When a test fails because the parsed payload's shape is unexpected, the `stdout` and `stderr` values are needed for the failure message — adding them as named return slots is cheaper than reaching back into the helper later.

3. **Include `stdout` and `stderr` in any exit-code assertion message**. The post-condition `assert exit_code in (0, 1)` should embed both streams in its failure message so a CI run failure produces a single-screen diagnostic without needing to re-run with `-s` to capture output.

## Why This Matters

**The diagnostic chain is what separates a 30-second debug from a 30-minute one.** With the default `catch_exceptions=True`:

- The CLI crashes with `AttributeError: 'NoneType' object has no attribute 'rule_id'` deep in a formatter.
- Pytest reports `json.JSONDecodeError` in the test helper at `json.loads(result.stdout)`.
- The contributor opens the test helper, traces the empty `stdout`, then re-runs with print statements to find that `result.exception` is non-None.
- They finally see the `AttributeError`, but only after spending several minutes unwinding the test harness's downstream crash.

The pattern is especially costly for **newly-developed features**, where unhandled exceptions are most likely during fixture iteration — exactly the case where fast-iteration diagnostics matter most. The 3-way reviewer convergence at D6d new-U3 (2026-05-21) emerged precisely because the test file under review was for a freshly-shipped feature.

**The `exit_code in (0, 1)` guard is necessary but not sufficient.** Without `catch_exceptions=False`, the guard absorbs the crash path and produces a misleading downstream error. With `catch_exceptions=False`, the guard continues to catch the "broken fixture" case (`exit_code == 2` from a malformed pyproject or a click usage error) AND gracefully surfaces unhandled exceptions when they happen.

**Pre-existing codebase signal.** `tests/schema/lint/cli/test_version_output.py` documents the canonical-correct pattern; the test even has an inline comment explaining why. New tests should match it.

## When to Apply

Apply on **every `CliRunner.invoke()` call** when ANY of the following hold:

- The test asserts on the CLI's structured output (JSON, SARIF, XML, YAML). The crash-mask risk is at its highest here because the parse step is downstream of the bad input.
- The CLI under test is being newly developed or substantially modified.
- The test's assertion messages or post-conditions don't already inspect `result.exception`.
- The test is part of an integration suite where one slow-to-debug failure blocks faster iteration on other tests.

Apply by default — even when the listed conditions don't strictly hold — because the cost of the flag is zero. The only downside of `catch_exceptions=False` is that a test deliberately exercising an exception path needs to wrap the invocation in `pytest.raises(...)`. That's the correct shape anyway: tests that exercise exception paths should be explicit about it.

**Do NOT apply** (i.e., keep the default `catch_exceptions=True`) when:

- The test deliberately exercises the click runner's exception-absorption behavior (e.g., a self-test of test infrastructure).
- The test is asserting on exit codes only AND already inspects `result.exception` separately before any downstream parsing. Even here, switching to `catch_exceptions=False` + `pytest.raises` is clearer.

## Examples

### Before — silent crash masking via the default `catch_exceptions=True`

```python
# tests/schema/lint/cli/test_d6d_custom_annotation_example.py (pre-fix)

def _run_lint(pyproject: Path) -> tuple[int, dict]:
    result = CliRunner().invoke(
        lint_main,
        ["--config", str(pyproject), "--proto", "service.proto",
         "-I", "proto/", "--format", "json"],
    )
    # CliRunner default: catch_exceptions=True. An AttributeError in
    # the CLI is absorbed into result.exception; result.exit_code = 1.
    assert result.exit_code in (0, 1)  # passes regardless of the crash
    payload = json.loads(result.stdout)  # crashes with JSONDecodeError
    return result.exit_code, payload
```

Failure surface when the CLI crashes: `json.JSONDecodeError: Expecting value: line 1 column 1 (char 0)` from `_run_lint:N`. The real exception lives in `result.exception` and is invisible.

### After — explicit `catch_exceptions=False` propagates the real crash

```python
# tests/schema/lint/cli/test_d6d_custom_annotation_example.py (post-fix)

def _run_lint(
    pyproject: Path,
    *,
    extra_args: tuple[str, ...] = (),
    format_: str = "json",
) -> tuple[int, dict[str, Any], str, str]:
    result = CliRunner().invoke(
        lint_main,
        [
            "--config", str(pyproject),
            "--proto", str(_FIXTURE_SERVICE_PROTO),
            "-I", str(_FIXTURE_PROTO_ROOT),
            *(["--format", format_] if format_ != "raw" else []),
            *extra_args,
        ],
        catch_exceptions=False,  # surface the real exception
    )
    assert result.exit_code in (0, 1), (
        f"expected lint exit 0/1, got {result.exit_code!r}\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    payload = (
        json.loads(result.stdout)
        if format_ in ("json", "sarif")
        else {}
    )
    return result.exit_code, payload, result.stdout, result.stderr
```

Failure surface when the CLI crashes: the actual `AttributeError` (or whatever exception class) with its real traceback. The `assert exit_code in (0, 1)` post-condition still catches the `exit_code == 2` malformed-pyproject case.

### Companion helper for exit-2 paths

```python
def _run_lint_raw(
    pyproject: Path,
    *,
    extra_args: tuple[str, ...] = (),
) -> tuple[int, str, str]:
    """Invoke ``protokit lint`` without exit-code-range assertions.

    Use to exercise exit-2 paths (malformed pyproject, regex-invalid
    suffix, duplicate suffix). Like _run_lint, passes
    catch_exceptions=False so internal crashes surface cleanly.
    """
    result = CliRunner().invoke(
        lint_main,
        [
            "--config", str(pyproject),
            "--proto", str(_FIXTURE_SERVICE_PROTO),
            "-I", str(_FIXTURE_PROTO_ROOT),
            "--format", "json",
            *extra_args,
        ],
        catch_exceptions=False,
    )
    return result.exit_code, result.stdout, result.stderr
```

This shape separates the "happy-path or normal-finding-gate" assertion from the "deliberately-bad-input exit-2" assertion. Both helpers pass `catch_exceptions=False`; the only difference is the exit-code post-condition.

## Related

- [[subprocess-exit-code-validation-test-harness-2026-05-13]] — sibling: exit-code-discipline learning for subprocess-driven CLI tests. That doc covers `subprocess.run` callers; this doc covers click's in-process `CliRunner`. The two harness paths have different default behaviors but the same "always assert on a SPECIFIC exit-code value, then inspect output" discipline.
- ce-review-convergence-rescues-sub-threshold-findings-2026-05-17 — meta-pattern: this learning emerged from a 3-way reviewer convergence at D6d new-U3 ce:review (2026-05-21). correctness TG-2 + kieran KP-5 + adversarial ADV-1 each independently flagged the trap. The convergence is the trust signal.
- [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]] — sibling: latent-bug surface patterns. Where that doc covers parity gates surfacing real CLI bugs that pass-but-shouldn't, this doc covers test-harness behavior that obscures real bugs the CLI did surface.
- Anchor commit: D6d new-U3 ce:review follow-up (2026-05-21, `c8ff42d`). See `tests/schema/lint/cli/test_d6d_custom_annotation_example.py:_run_lint` for the canonical-correct shape. Pre-existing reference: `tests/schema/lint/cli/test_version_output.py` documents the same discipline with its own inline comment.
