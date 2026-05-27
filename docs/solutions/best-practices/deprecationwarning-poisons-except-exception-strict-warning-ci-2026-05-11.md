---
title: "DeprecationWarning poisons defensive except-Exception under strict-warning CI"
date: 2026-05-11
category: docs/solutions/best-practices
module: protokit.schema.lint._config
problem_type: best_practice
component: tooling
severity: high
root_cause: logic_error
resolution_type: code_fix
applies_when:
  - "A defensive `except Exception` arm wraps any third-party library call at a module boundary"
  - "A CI environment uses `PYTHONWARNINGS=error::DeprecationWarning` or `pytest -W error::DeprecationWarning`"
  - "A library dependency deprecates a string identifier passed as a user-visible parameter value (e.g., a factory-method `kind` argument)"
  - "The library constraint range allows a version that has introduced the deprecation decorator"
  - "The failure mode is silent mis-attribution: the defensive catch rewrites a library deprecation as a local-input error"
tags:
  - deprecationwarning
  - except-exception
  - strict-warning-ci
  - pathspec
  - broad-catch
  - warnings-filter
  - protokit-lint
  - ce-review
---

# DeprecationWarning poisons defensive except-Exception under strict-warning CI

## Context

Python's `warnings.warn(..., DeprecationWarning, ...)` is designed to
emit a soft diagnostic under default warning filters and silently
upgrade to a raised exception when a strict-warning environment is
active (`-W error` or `-W error::DeprecationWarning`). This upgrade
behaviour is intentional and well-documented — but it has a
non-obvious interaction with defensive broad catches at library
boundaries.

`DeprecationWarning` inherits `Warning → Exception`. Any
`except Exception` arm catches it. When a library decorator fires a
deprecation at every use of a deprecated identifier, and the call
site wraps the library call in a broad `except Exception` for
robustness, the deprecation exception routes through that catch
arm — and the arm's error-attribution logic blames the call's local
inputs rather than the library's state.

The trap is structurally invisible at code review: broad catches LOOK
conservative ("we're handling all pathspec exceptions"), and the
offending identifier is a string that the developer typed once and
is indistinguishable from any other string argument. The failure only
surfaces when the strict warning filter is active — typically in a
deployment or CI environment with `PYTHONWARNINGS=error::DeprecationWarning`
— and produces a wrong-but-valid result rather than a crash, making
it hard to catch via standard health checks.

**The D5 U3 instance (protokit-lint).** `compile_exclude_patterns` in
`src/protokit/schema/lint/_config.py` called
`pathspec.PathSpec.from_lines("gitwildmatch", patterns)`. The string
literal `"gitwildmatch"` is a factory-method identifier that pathspec
1.1.1 deprecated via `@deprecated` on `GitWildMatchPattern.__init__`.
Under the default warning filter, each call to
`from_lines("gitwildmatch", ...)` emits a `DeprecationWarning` to
stderr. Under `-W error::DeprecationWarning`, each call RAISES
`DeprecationWarning("GitWildMatchPattern ('gitwildmatch') is
deprecated; use 'gitignore' instead.")`.

The defensive `except Exception` arm caught the raised
`DeprecationWarning` and routed it through
`error_exit_with_code("exclude-pattern-invalid", ...)`. The resulting
error message — `invalid exclude pattern (DeprecationWarning):
GitWildMatchPattern...` — looked like a user input error, blamed the
user's perfectly valid `vendor/**` pattern, and exited 2. The cascade
was invisible during development because the deprecation's
warning-filter upgrade only fires in strict-warning CI environments.

The fix was one identifier swap: `"gitwildmatch"` → `"gitignore"`. The
non-deprecated successor has identical match semantics (negation,
glob, leading-`./`, permissive bracket handling), verified across
the full test suite. No behavior change for any valid or invalid
pattern.

**Session-history context (session history).** The
`"gitignore"` identifier was NEVER mentioned in any prior planning,
brainstorm, or implementation session. The D3 brainstorm
(2026-05-04) locked gitignore-style globs via pathspec; the D5 plan
(2026-05-10) codified `pathspec.PathSpec.from_lines("gitwildmatch",
patterns)` as the API call. The plan's sibling-parity audit
recommendation (audit against ruff's `exclude`) was framed around
behavior-level semantic alignment, not the identifier's deprecation
lifecycle. The deprecation status was not visible to any reviewer
during plan-review or implementation; the U3 adversarial reviewer
caught it post-implementation by tracing the strict-warning code
path empirically.

## Guidance

### Step 1 — Audit broad catches wrapping library calls under `-W error`

Run the test suite with `PYTHONWARNINGS=error::DeprecationWarning`
(or the broader `PYTHONWARNINGS=error`). Any
`DeprecationWarning`-as-exception that leaks into a broad
`except Exception` arm will surface as an unexpected error code or
message shape:

```bash
# pytest invocation
pytest -W error::DeprecationWarning

# or via environment variable
PYTHONWARNINGS=error::DeprecationWarning pytest
```

Look for test failures whose error messages contain the class name
`DeprecationWarning` where a domain error class was expected — this
is the telltale shape of the mis-attribution.

### Step 2 — Identify the deprecated identifier and its successor

When `DeprecationWarning` appears inside an `except Exception` arm,
the exception message names the deprecated identifier and often
names or implies the successor. In the pathspec case:

```
DeprecationWarning: GitWildMatchPattern ('gitwildmatch') is deprecated;
use 'gitignore' instead.
```

The successor (`"gitignore"`) is named inline. Verify that the
successor has the same semantics for the inputs the code actually
sends:

- For glob/gitignore pattern libraries: spot-check negation patterns,
  leading `./` handling, directory-only patterns (`vendor/`), and
  bracket expressions (`[Tt]emp`).
- Verify via the existing test suite — do not rely on documentation
  alone, since "identical semantics" claims are sometimes qualified
  in practice.

### Step 3 — Swap the identifier; do not suppress the warning

The correct fix is to use the non-deprecated successor. Do NOT
suppress the warning via `warnings.filterwarnings("ignore", ...)` or
by wrapping the library call in a `warnings.catch_warnings()`
context — suppressing hides the library's migration signal and will
cause the code to break again at the next major version when the
deprecated identifier is removed.

```python
# WRONG — swallows the deprecation, breaks at next major version
with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    return pathspec.PathSpec.from_lines("gitwildmatch", patterns)

# CORRECT — use the successor; semantics verified by existing tests
return pathspec.PathSpec.from_lines("gitignore", patterns)
```

### Step 4 — Widen the dependency constraint if needed

If the deprecated identifier was introduced by a version OUTSIDE the
declared constraint range (i.e., the constraint allowed a version
the code was not designed for), update the constraint:

```toml
# In pyproject.toml / setup.cfg
# Before — but the actually-installed pathspec was 1.1.1, a constraint mismatch:
pathspec = ">=0.12,<1"

# After — match the deprecation window:
pathspec = ">=0.12,<2"
```

Constraint mismatches compound the deprecation trap by making the
triggering version silently installable. The D5 U3 ce:review's F-10
finding addressed this prerequisite alongside F-01's identifier
swap.

### Step 5 — Pin the absence of the warning in tests

Add a test that exercises the library call under `pytest.warns` (or
`recwarn`) and asserts that NO `DeprecationWarning` is emitted,
pinning the absence of the trap going forward:

```python
def test_compile_exclude_patterns_no_deprecation_warning(
    recwarn: pytest.WarningsChecker,
) -> None:
    """pathspec.PathSpec.from_lines must not emit DeprecationWarning.

    Under strict-warning CI (`-W error::DeprecationWarning`), any
    DeprecationWarning raised inside compile_exclude_patterns would
    route through the defensive `except Exception` arm and surface as
    `error[lint-exclude-pattern-invalid]` — mis-attributing the
    library deprecation as a user input error.
    """
    import warnings
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        compile_exclude_patterns(["vendor/**", "!vendor/public/**"])
    deprecations = [
        w for w in caught if issubclass(w.category, DeprecationWarning)
    ]
    assert not deprecations, (
        f"DeprecationWarning emitted by compile_exclude_patterns: "
        f"{deprecations}"
    )
```

This test runs under default warning filters and catches the trap
before a strict-warning CI environment makes it a hard failure.

## Why This Matters

**Silent mis-attribution.** The user sees
`error[lint-exclude-pattern-invalid]: invalid exclude pattern
(DeprecationWarning): ...` and investigates their `vendor/**`
pattern, which is perfectly valid. The actual cause — a library
deprecation triggered by a string identifier the developer chose,
not the user's pattern — is invisible in the error message.

**Wrong-but-no-crash failure mode.** The CLI exits 2 with a plausible
error message; there is no traceback, no obvious test failure, no
missing import. Standard health checks (exit code, stderr non-empty)
all appear to fire correctly. The failure is only detectable by
checking WHICH error code was emitted and whether the blamed input
is actually invalid.

**Strict-warning CI environment gap.** Many projects run `pytest -W
error::DeprecationWarning` in CI to catch deprecation debt early.
A codebase that does NOT run under strict warning filters will never
see the trap. Deployment to a customer's CI environment that DOES
run strict warnings exposes the bug at the worst possible moment.

**Mirror image of the KeyboardInterrupt sibling.** The sibling
learning ([`keyboardinterrupt-baseexception-bypass-rule-pack-load-2026-05-07.md`](../security-issues/keyboardinterrupt-baseexception-bypass-rule-pack-load-2026-05-07.md))
documents a structurally opposite trap: `KeyboardInterrupt` is a
`BaseException` subclass that is NOT an `Exception` subclass, so
broad `except Exception` MISSES it and the interrupt escapes the
guard. This learning documents the opposite: `DeprecationWarning`
IS an `Exception` subclass (via `Warning`), so broad
`except Exception` CATCHES it and mis-routes it. The two learnings
together map the full `except Exception` boundary:

```
BaseException
├── SystemExit         — NOT Exception → MISSES broad except Exception
├── KeyboardInterrupt  — NOT Exception → MISSES broad except Exception ← sibling
├── GeneratorExit      — NOT Exception → MISSES broad except Exception
└── Exception
    └── Warning
        └── DeprecationWarning — IS Exception → CAUGHT by except Exception ← this doc
```

Both learnings call for the same disciplinary action — audit
defensive broad catches at library boundaries — for opposite
reasons: in one direction the catch is too narrow; in the other,
under specific CI conditions, it is too wide.

## When to Apply

- Any `except Exception` arm that wraps a third-party library call
  where the library uses `@deprecated` (or `warnings.warn(...,
  DeprecationWarning, ...)`) on identifiers passed as string
  parameters or factory-method `kind` arguments.
- Any new library dependency upgrade where the CHANGELOG mentions
  `@deprecated` on previously-valid identifiers — audit existing
  call sites for broad catches.
- When adding `-W error::DeprecationWarning` to CI for the first
  time: run the full test suite under that flag before declaring the
  constraint met; broad catches at library boundaries are the
  expected failure class.
- When a library constraint range is widened (e.g., `<1` → `<2`):
  re-audit call sites for deprecated identifiers introduced in the
  newly-allowed range.
- When ce:review finds that a broad `except Exception` arm emits an
  error code that could be mis-attributed to user input: check
  whether a library `DeprecationWarning` (or any `Warning` subclass)
  could reach that arm under strict-warning CI.

## Examples

### Before — D5 U3 initial implementation (`_config.py`, using deprecated identifier)

```python
# src/protokit/schema/lint/_config.py — pre-fix
try:
    return pathspec.PathSpec.from_lines("gitwildmatch", patterns)
except Exception as exc:  # noqa: BLE001 - intentional broad catch
    error_exit_with_code(
        "exclude-pattern-invalid",
        f"invalid exclude pattern ({type(exc).__name__}): "
        f"{_safe_for_stderr(exc)}",
    )
```

Under `pytest -W error::DeprecationWarning` with pathspec 1.1.1:

1. `from_lines("gitwildmatch", ["vendor/**"])` calls
   `GitWildMatchPattern("vendor/**")`.
2. `GitWildMatchPattern.__init__` calls
   `warnings.warn(..., DeprecationWarning, ...)`.
3. The filter raises `DeprecationWarning("GitWildMatchPattern
   ('gitwildmatch') is deprecated; use 'gitignore' instead.")`.
4. `except Exception` catches it.
5. Exit 2:
   `error[lint-exclude-pattern-invalid]: invalid exclude pattern
   (DeprecationWarning): GitWildMatchPattern...`
6. User's valid `vendor/**` pattern is blamed.

### After — post-ce:review fix (commit `7e5f353`), successor identifier

```python
# src/protokit/schema/lint/_config.py — post-fix
try:
    return pathspec.PathSpec.from_lines("gitignore", patterns)
except Exception as exc:  # noqa: BLE001 - intentional broad catch
    error_exit_with_code(
        "exclude-pattern-invalid",
        f"invalid exclude pattern ({type(exc).__name__}): "
        f"{_safe_for_stderr(exc)}",
    )
```

`"gitignore"` is the non-deprecated successor to `"gitwildmatch"`.
Match semantics are identical: negation patterns (`!path`), glob
wildcards (`**`), leading-`./` normalization, and permissive bracket
handling all behave the same. The existing test suite (1229 tests)
confirmed no behavior change.

### The mirror-image sibling at the same boundary

The
[`keyboardinterrupt-baseexception-bypass-rule-pack-load-2026-05-07.md`](../security-issues/keyboardinterrupt-baseexception-bypass-rule-pack-load-2026-05-07.md)
learning documents the structurally opposite trap at the same kind
of defensive boundary: `KeyboardInterrupt` IS NOT an `Exception`,
so `except Exception` MISSES it. The fix there was to add an
explicit `except KeyboardInterrupt` arm BEFORE the broad catch. The
two traps together justify auditing BOTH directions when adding or
reviewing defensive broad catches:

- Check that non-`Exception` `BaseException` subclasses that need
  interception are enumerated explicitly (the MISSES direction).
- Check that `Warning` subclasses elevated to exceptions under
  strict-warning CI cannot be mis-attributed by the broad catch
  (the CATCHES direction).

## Related Learnings

- [`circular-import-type-checking-cycle-break-2026-05-11.md`](circular-import-type-checking-cycle-break-2026-05-11.md)
  — sibling "discipline near except arms" learning. Both cover an
  unexpected exception class escaping a containment `except` arm
  with wrong attribution. This doc: `DeprecationWarning` promoted
  to exception under strict-warning CI. The sibling: `ImportError`
  raised by a lazy import inside the except arm itself, silently
  dropping the original exception. Different mechanisms, same
  failure-mode family of "containment arm assumes the family it
  caught is the only one that can fire mid-cleanup."
- [`keyboardinterrupt-baseexception-bypass-rule-pack-load-2026-05-07.md`](../security-issues/keyboardinterrupt-baseexception-bypass-rule-pack-load-2026-05-07.md)
  — sibling pattern at the same `except Exception` boundary. That
  doc covers what broad catches MISS (BaseException-not-Exception);
  this doc covers what they CATCH-and-mis-route under strict-warning
  CI. Both call for audit discipline at library boundaries; the
  audit direction differs.
- [`formatter-systemexit-exit-code-bypass-2026-04-19.md`](../security-issues/formatter-systemexit-exit-code-bypass-2026-04-19.md)
  — the grandparent of the defensive-catch pattern in this project.
  Established that `except Exception` is not a catch-all for the
  MISSES direction.
- [`normalize-at-input-boundary-2026-05-07.md`](./normalize-at-input-boundary-2026-05-07.md)
  — adjacent discipline. Normalization of exclude pattern strings
  (strip, etc.) is the sibling normalization concern at the same
  boundary; this doc addresses the pathspec identifier choice that
  controls which syntax the compiler uses.
- [`shared-error-helper-source-label-caller-attribution-2026-05-11.md`](./shared-error-helper-source-label-caller-attribution-2026-05-11.md)
  — adjacent discipline. The `error_exit_with_code(
  "exclude-pattern-invalid", ...)` call site poisoned by the
  `DeprecationWarning` is the same surface that needs source-label
  attribution for multi-source error messages.

## Reference Commits

- `9c79904` — D5 U3 delivery; `"gitwildmatch"` identifier present;
  trap latent (surfaces only under strict-warning CI).
- `a2809ca` — D5 U3 ce:review follow-ups; F-01 finding swapped
  identifier to `"gitignore"`; F-10 widened pathspec constraint from
  `<1` to `<2`.
- ce:review run artifact:
  `.context/compound-engineering/ce-review/20260511-211250-ea0a68bb/`
  (adversarial-reviewer.json ADV-U3-01 with full empirical
  reproduction trace).
