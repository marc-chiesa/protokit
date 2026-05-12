---
title: "Shared error-emitting helpers must accept caller context via a source_label parameter, never hard-code attribution"
date: 2026-05-11
last_updated: 2026-05-11
category: docs/solutions/best-practices
module: protokit.schema.lint._config
problem_type: best_practice
component: tooling
severity: medium
applies_when:
  - "A helper function that emits user-visible error messages is called from two or more callers with different invocation surfaces (e.g., --config path vs. walk-up-discovered pyproject)"
  - "A shared helper is extracted from a single-caller function and the error message wording refers to the original caller's context by name"
  - "An error message hard-codes a CLI flag name (e.g., '--config path') in a helper that is also reachable via an implicit path (e.g., walk-up)"
  - "ce:review correctness or maintainability personas flag that error messages misattribute the source of a failure to a flag the user never passed"
  - "A refactor consolidates duplicated error-handling code into a shared helper"
root_cause: logic_error
resolution_type: code_fix
tags:
  - source-label
  - error-attribution
  - shared-helper
  - caller-context
  - user-visible-errors
  - api-design
  - protokit-lint
  - ce-review
---

# Shared error-emitting helpers must accept caller context via a source_label parameter

## Context

Any helper function that emits user-visible errors and is reachable
from two or more callers with distinct invocation surfaces faces a
quiet correctness trap: error messages that hard-code attribution to
one caller's context will fire — with that wrong attribution — when
any other caller hits the same failure path.

The trap is structurally invisible to standard detection tools:

- **Type checkers cannot catch it.** The error message is a `str`;
  mypy and pyright have no awareness that the string's content must
  accurately reflect the call site.
- **Unit tests of the helper itself cannot catch it.** A test that
  calls the helper directly only exercises it in isolation; it never
  observes whether the caller's attribution matches the hard-coded
  string.
- **Only an integration test that exercises EACH caller path AND
  asserts on the message attribution will catch regressions.**

The pattern surfaced during D5 U1's ce:review with 5-persona
convergence — the highest-confidence finding in that entire review
pass. `_read_and_parse` in `src/protokit/schema/lint/_config.py` was
a shared helper called from two contexts:

1. `_load_explicit` (when the user passed `--config PATH`)
2. `_load_from_walkup` (automatic discovery via CWD walk-up)

The helper hard-coded `'--config path does not exist:'` and
`'--config path unreadable:'` in its error messages. The strings were
accurate for `_load_explicit`. They were false for `_load_from_walkup`:
a user who never typed `--config` saw `error[lint-pyproject-config-load]:
--config path unreadable: /auto/discovered/pyproject.toml`,
attributing the failure to a CLI flag they did not use.

The adversarial reviewer identified a TOCTOU sub-case: a symlink
discovered by walk-up whose target becomes dangling between `is_file()`
and `read_bytes()` triggers the wrong attribution even without any
deliberate misuse.

(session history) The closest prior institutional precedent in this
project is D3's `run_formatter_safely` accepting an `error_exit_fn`
parameter to let the caller control error routing (D3 brainstorm
review finding #15). That finding was about error-exit *routing*, not
message *attribution*, but it established the same structural
principle: shared helpers that emit errors should receive
caller-provided context rather than hard-coding it.

## Guidance

**Any helper that emits user-visible errors and is called from
multiple contexts MUST accept caller context as a parameter rather
than hard-coding attribution to a single caller's surface.**

The canonical pattern:

1. Add a `source_label: str` parameter, **keyword-only** (use `*,
   source_label: str = ...` in Python ≥3.8) to prevent positional
   ambiguity if the parameter list grows later.
2. Default it to the **stricter-attribution variant** (e.g.,
   `"--config path"` for an explicit-flag mode). A future caller
   that forgets to pass the kwarg generates wrong-but-conservative
   output (over-attributes to an explicit flag) rather than an
   ambiguous "unknown source" message. This is the safe-fail choice
   for a CLI tool where error attribution affects diagnostic time.
3. Interpolate `{source_label}` into all error strings that describe
   the call origin.
4. Each caller passes its own label at the call site, making the
   attribution explicit per surface.

```python
def _read_and_parse(
    path: Path, *, source_label: str = "--config path",
) -> dict[str, Any]:
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        error_exit_with_code(
            "pyproject-config-load",
            f"{source_label} does not exist: {_safe_for_stderr(path)}",
        )
    except OSError as exc:
        error_exit_with_code(
            "pyproject-config-load",
            f"{source_label} unreadable: {_safe_for_stderr(path)}: "
            f"{_safe_for_stderr(exc)}",
        )
    ...
```

```python
# Explicit-path caller:
table = _read_and_parse(path, source_label="--config path")

# Walk-up caller:
table = _read_and_parse(path, source_label="walk-up-discovered pyproject")
```

The same pattern applies beyond file loading. Any helper that
produces per-call output where the call site matters and is called
from more than one context:

- **Logging helpers** that record `operation_name` or `actor`.
- **Telemetry helpers** that emit per-call labels into metrics.
- **Structured-error helpers** that include `source` or `origin` fields.
- **Audit-trail helpers** that record `actor` or `subsystem`.
- **CI-diagnostic helpers** that format failures for human-readable
  output.

In every case, the call-site context is information the helper does
not own and cannot recover from the call itself — only the caller
knows whether the operation was triggered by a flag, an env var, an
auto-discovery path, a default fallback, etc.

## Why This Matters

This bug class is high-impact-per-low-likelihood-of-detection:

- **Diagnostic latency**: On-call engineers seeing
  `error[lint-pyproject-config-load]: --config path unreadable:
  /workspace/pyproject.toml` in CI logs look for a `--config` flag in
  the pipeline definition, find none, and spend time on the wrong
  diagnostic path before realizing the error is about auto-discovery.
- **CI gate misdirection**: Scripts that classify failures by
  attribution (e.g., "flag-related → bug ticket; environment-related
  → infra ticket") route wrong-attributed failures to the wrong
  triage queue.
- **Compound failure**: Wrong attribution typically fires for the
  *common* execution path (the silent default), not the explicit
  flag path. Most users never pass `--config` — so the wrong
  message is what they always see when auto-discovery fails.

The compound nature of the failure is what makes it high-value to
document. The fix is mechanically trivial (one new parameter), but
catching the gap requires:

1. **Architectural awareness** of which helpers are reachable from
   multiple invocation surfaces (a code-review check, not a static
   analyzer check).
2. **Integration tests that exercise each caller path with each
   failure mode AND assert on the attribution text** (the regression
   guard).

Without the architectural awareness, the helper looks correct in
isolation. Without the per-caller integration tests, the misattribution
is invisible until a user reports it in production.

(auto memory [claude]) The
`protokit_lint_delivery_workflow.md` per-delivery pattern positions
ce:review as the designated stage for surfacing this category of
cross-caller correctness gap. The plan phase operates on intent
("the loader should report errors") and cannot evaluate whether the
specific message strings are accurate for each caller; ce:review reads
the actual code with each caller in scope.

## When to Apply

- **When extracting a shared helper from two or more callers** that
  each have distinct user-visible contexts — build `source_label` in
  from the start rather than patching it in after the misattribution
  is observed in production.
- **When reviewing any PR** that introduces a shared error-emitting,
  logging, or telemetry helper: check whether the helper is called
  from multiple call sites with different user-facing contexts, and
  whether the emitted output is accurate for each.
- **When the refactor is "extract duplicated error-handling code
  into a shared helper"** — the act of sharing IS the trigger to add
  `source_label`. (The previously-duplicated code naturally carried
  different attribution strings; sharing without parameterization
  collapses those distinctions.)
- **After any ce:review finding that adds `source_label` to a
  helper** — scan the same module for other helpers that share the
  same pattern (shared helper, multiple callers, user-visible output)
  and apply preemptively.

## Examples

### Before — hard-coded caller attribution

```python
def _read_and_parse(path: Path) -> dict[str, Any]:
    """Read bytes and parse as TOML; shared between explicit-path
    and walk-up callers."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        if isinstance(exc, FileNotFoundError):
            error_exit_with_code(
                "pyproject-config-load",
                f"--config path does not exist: {_safe_for_stderr(path)}",
            )
        error_exit_with_code(
            "pyproject-config-load",
            f"--config path unreadable: {_safe_for_stderr(path)}: "
            f"{_safe_for_stderr(exc)}",
        )
    return _parse_toml_bytes(data, path)
```

**Result from the walk-up caller**:

```text
error[lint-pyproject-config-load]: --config path unreadable: /project/pyproject.toml: [Errno 13] Permission denied
```

The user never typed `--config`. The attribution is factually wrong.

### After — caller-supplied source_label

```python
def _read_and_parse(
    path: Path, *, source_label: str = "--config path",
) -> dict[str, Any]:
    """Read bytes and parse as TOML; callers pass source_label to
    disambiguate explicit-path vs walk-up-discovered attribution."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        if isinstance(exc, FileNotFoundError):
            error_exit_with_code(
                "pyproject-config-load",
                f"{source_label} does not exist: {_safe_for_stderr(path)}",
            )
        error_exit_with_code(
            "pyproject-config-load",
            f"{source_label} unreadable: {_safe_for_stderr(path)}: "
            f"{_safe_for_stderr(exc)}",
        )
    return _parse_toml_bytes(data, path)


def _load_explicit(path: Path) -> dict[str, Any]:
    """--config PATH strict mode."""
    table = _read_and_parse(path, source_label="--config path")
    ...


def _load_from_walkup(path: Path) -> dict[str, Any] | None:
    """Walk-up-discovered pyproject (silent-fallback on table-absent)."""
    table = _read_and_parse(
        path, source_label="walk-up-discovered pyproject",
    )
    ...
```

**Result from walk-up caller**:

```text
error[lint-pyproject-config-load]: walk-up-discovered pyproject unreadable: /project/pyproject.toml: [Errno 13] Permission denied
```

The attribution is now accurate. The engineer reading this in CI
logs immediately knows the failure is in auto-discovery, not in a
flag they passed.

### Regression test — per-caller attribution assertion

```python
def test_walkup_unreadable_pyproject_uses_walkup_label(
    self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Walk-up discovers an unreadable pyproject → error message says
    'walk-up...' NOT '--config path'."""
    pyproject = _write_pyproject(tmp_path, "[tool.protokit.lint]\n")
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)

    def raise_perm(self: Path) -> bytes:
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(Path, "read_bytes", raise_perm)

    with pytest.raises(SystemExit) as exc_info:
        load_pyproject_config(explicit_path=None, no_config=False)

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "error[lint-pyproject-config-load]:" in captured.err
    # KEY: walk-up errors must NOT claim '--config' was passed
    assert "--config" not in captured.err
    assert "walk-up" in captured.err
```

The test exercises the full caller path (`load_pyproject_config` →
`_load_from_walkup` → `_read_and_parse`) with the failure injected
via `monkeypatch.setattr`, then asserts on the negative attribution
(`"--config" not in captured.err`) AND the positive attribution
(`"walk-up" in captured.err`). A future refactor that collapses the
`source_label` parameter back to a hard-coded string would fail this
test.

## Related Learnings

- `docs/solutions/security-issues/keyboardinterrupt-baseexception-bypass-rule-pack-load-2026-05-07.md` —
  companion finding from the same D5 U1 ce:review pass. That doc
  covers the I/O-boundary-exception-guard angle (spatial-scope audit
  for `OSError` on walk-up stat calls); this doc covers the
  caller-attribution angle (parameterized error messages for shared
  helpers). Both fixes landed in commit `89d84ff`.
- `docs/solutions/best-practices/apply-institutional-learnings-postdating-plan-during-ce-review-2026-05-09.md` —
  this finding is itself an example: the gap was caught at
  ce:review, not at plan/brainstorm time, because plan reviewers
  read the helper signature without each caller's context in scope.
  ce:review reads all callers simultaneously.
- `docs/solutions/best-practices/normalize-at-input-boundary-2026-05-07.md` —
  sibling discipline. That doc says "normalize at the input boundary
  (Click callback) so downstream code never sees un-normalized data."
  This doc says "attribute at the call boundary (caller-supplied
  label) so the helper never invents attribution it can't actually
  know." Same structural category: keep context information at the
  layer that owns it, don't let downstream assumptions pollute
  upstream helpers (or vice versa).
- `docs/solutions/security-issues/formatter-systemexit-exit-code-bypass-2026-04-19.md` —
  grandparent of the helper-extraction pattern in this project.
  `run_formatter_safely` was the first shared error-emitting helper
  in protokit-lint; its `error_exit_fn` parameter (added in D3's U4a
  refactor) is the closest prior precedent for the
  `source_label`-style parameter. That earlier parameter handled
  error-routing dispatch (where to send the error); `source_label`
  handles error-content attribution (what the error says). Same
  structural lesson: don't hard-code in a shared helper what the
  caller has to know.
- `docs/solutions/best-practices/source-aware-error-messages-multi-source-resolved-value-2026-05-11.md` —
  **adjacent variant** of the same user-harm (wrong source
  attribution in error messages), but a different structural
  trigger. That doc covers the case where a SINGLE error site
  references a value that can come from multiple RUNTIME SOURCES
  (CLI flag, env var, config file, default); the fix is source-aware
  branching at the check site using a pre-computed source boolean
  from `ctx.get_parameter_source()`. This doc covers the case where
  a SHARED HELPER is reachable from multiple CALL SITES with
  different invocation surfaces; the fix is a `source_label`
  parameter injected from the caller. The disambiguation table at
  the top of the sibling doc enumerates the structural differences
  in detail. Both docs share vocabulary (source, attribution, error
  message) — future readers should consult both when triaging an
  "error message names the wrong source" finding to determine which
  pattern applies.
- The 5-persona convergence on `_read_and_parse` source attribution
  in this doc's Context section is one of the calibration data
  points cited in
  `docs/solutions/best-practices/apply-institutional-learnings-postdating-plan-during-ce-review-2026-05-09.md`
  (see its 2026-05-11 refinement note). 5-persona is among the
  strongest signals to date; the parallel D5 U2 review showed that
  3-way convergence with diverse reasoning chains is also a
  high-reliability indicator — not a weaker form of the same signal.

## Fix Commits

- `c0bbf03` — D5 U1 implementation (the gap was present after this
  commit; `_read_and_parse` hard-coded `--config path` strings).
- `89d84ff` — D5 U1 ce:review follow-ups; the `source_label`
  parameter was added in this 22-finding fix commit.
- ce:review run artifact:
  `.context/compound-engineering/ce-review/20260511-094847-1685ca47/`
  (5-persona convergence captured in correctness.json,
  adversarial.json, kieran-python.json; maintainability and
  reliability convergence is in the orchestrator synthesis).
