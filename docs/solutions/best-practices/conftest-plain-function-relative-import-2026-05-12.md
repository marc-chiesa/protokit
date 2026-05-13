---
title: "conftest.py auto-loads fixtures, not plain functions — use relative imports for shared test helpers"
date: 2026-05-12
category: docs/solutions/best-practices
module: tooling/testing
problem_type: best_practice
component: testing_framework
severity: medium
applies_when:
  - "3+ test files in the same pytest directory duplicate a helper function or shared constant (e.g., an assertion wrapper, an error-prefix literal)"
  - "The helper is being lifted into `conftest.py` to remove duplication"
  - "The helper is a plain Python function or module-level constant — NOT a `@pytest.fixture`"
  - "The test author expects `conftest.py` to auto-export the helper the same way it auto-exports fixtures"
related_components:
  - testing_framework
tags:
  - pytest
  - conftest
  - test-helpers
  - relative-import
  - dry
  - fixture-vs-function
  - test-infrastructure
---

# conftest.py auto-loads fixtures, not plain functions — use relative imports for shared test helpers

## Context

`tests/schema/lint/_config/` contains four test files that each
validate different aspects of `ResolvedLintConfig.from_dict`:
schema validation, severities table parsing, no_builtin_rules
flag parsing, and resolved-config integration. Three of those
files (`test_schema_validation.py`, `test_severities.py`,
`test_no_builtin_rules.py`) shared the same assertion pattern: call
`from_dict`, expect `SystemExit(2)`, capture stderr, assert it
starts with the error prefix and contains a specific substring.

Before D6a U2's ce:review follow-ups, this helper was copy-pasted
across the three test files as `_expect_invalid` along with a
private `_PREFIX` constant. Three identical literal strings of the
error prefix lived in three files; three identical 20-line helper
function bodies lived in three files. A prefix rename would
require three coordinated edits. A new test author writing a fourth
file would have no obvious place to discover the helper and would
likely copy-paste a fourth time.

The fix extracted the helper and the error-prefix constant into
`tests/schema/lint/_config/conftest.py`. But the first attempt
broke: pytest's `conftest.py` mechanism auto-discovers and
auto-injects **fixtures** (functions decorated with
`@pytest.fixture`), but plain Python functions and module-level
constants in conftest.py are NOT automatically available in test
files. They require explicit relative imports (`from .conftest
import expect_invalid`) in each consumer.

## Guidance

**Step 1.** Create `conftest.py` in the shared test directory with
the helper function and any shared constants:

```python
# tests/schema/lint/_config/conftest.py
"""Shared fixtures + helpers for ``tests/schema/lint/_config/``."""

from collections.abc import Mapping
from typing import Any

import pytest

from protokit.schema.lint._config import ResolvedLintConfig

#: Stable stderr prefix emitted by
#: ``error_exit_with_code("pyproject-config-invalid", ...)`` in
#: ``_config.py``. Tests in this directory assert against this exact
#: prefix.
INVALID_PREFIX: str = "error[lint-pyproject-config-invalid]:"


def expect_invalid(
    table: Mapping[str, Any] | None,
    cli_overrides: Mapping[str, Any],
    capsys: pytest.CaptureFixture[str],
    *,
    substring: str,
) -> None:
    """Assert ``from_dict`` raises SystemExit with code 2, stderr starts
    with ``INVALID_PREFIX``, and stderr contains ``substring``.
    """
    with pytest.raises(SystemExit) as excinfo:
        ResolvedLintConfig.from_dict(table, cli_overrides)
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert err.startswith(INVALID_PREFIX), err
    assert substring in err, err
```

**Step 2.** In each consuming test file, use a **relative import**
— the leading dot is mandatory:

```python
# tests/schema/lint/_config/test_schema_validation.py
from __future__ import annotations

import pytest

from protokit.schema.lint._config import ResolvedLintConfig
from protokit.schema.lint.model import LintSeverity

from .conftest import expect_invalid   # <-- relative import, not bare 'from conftest import'

class TestR3UnknownKeys:
    def test_typo_at_top_level(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        expect_invalid(
            {"excldue": []}, {}, capsys, substring="'excldue'",
        )
```

**The gotcha in detail.** `conftest.py` is a pytest-special
filename. Pytest's collection machinery walks up the directory
tree and registers fixtures from every `conftest.py` it finds, then
makes those fixtures available to tests in that directory and all
subdirectories — fixture injection happens via function-argument
name matching at test-execution time. But this auto-injection is
**fixture-specific**: it only applies to functions decorated with
`@pytest.fixture`. Plain functions, classes, and module-level
constants in `conftest.py` are not auto-injected.

Without the explicit `from .conftest import expect_invalid`, test
files get `NameError: name 'expect_invalid' is not defined`. The
relative import (`from .`) is required because conftest.py is not
installed as a top-level importable module — it lives in the
package path only as a sibling file. Bare `from conftest import
expect_invalid` works on some Python versions because of CWD-on-
sys.path quirks but breaks under newer pytest collection (or when
the test is invoked from a different working directory).

**Step 3.** When the prefix literal or assertion logic needs
strengthening, update once in `conftest.py`. All consumers pick up
the change automatically because there is only one implementation.

## Why This Matters

**Three concrete risks from copy-pasted helpers across N test
files:**

1. **Literal drift.** If the error prefix changes (e.g., from
   `error[lint-pyproject-config-invalid]:` to
   `error[protokit-config]:` during a rename), three files need
   updating. A missed file silently passes because the assertion
   string is now wrong but the test was previously passing on the
   old prefix.
2. **Behavioral drift.** If the assertion logic needs strengthening
   (e.g., also check `excinfo.value.code == 2`, or rstrip
   whitespace before substring matching), three files need the
   same patch. A developer who updates two of three leaves the
   third with weaker assertions — and the third file's tests still
   pass, masking the gap.
3. **Discovery failure.** A new test author writes a fourth file
   (`test_severities_invalid.py`) and reimplements the helper from
   scratch. The project now has four copies with subtle behavioral
   differences. The fixture pattern would have been discoverable
   via grep; an inlined helper buried in a 200-line test file is
   not.

**The conftest extraction eliminates all three risks simultaneously**
— and the prefix constant is the highest-risk single literal: it's
the string that ties every config-error test to the exact format of
the user-facing error prefix.

**Why the auto-load gotcha trips people up.** The mental model
many people have of `conftest.py` is "shared module — drop things
here and they're available." This is correct for fixtures (the
function-argument injection mechanism is opaque enough that it
*feels* like global availability) but incorrect for plain
functions and constants. Empirically, the first attempt at
extraction usually omits the import, and the failure mode
(`NameError`) only surfaces on test invocation — not at write
time. The cost is one round-trip; documenting it eliminates the
round-trip for future extractions.

## When to Apply

Apply at the **3+ duplicate sites** threshold within the same
pytest directory:

- **1 site:** inline — no extraction yet.
- **2 sites:** judgment call. Inline is defensible if the two
  files are closely related (e.g., split for size, not for
  topic). Extract if the helper has meaningful internal logic
  (multiple assertions, error message construction) or if a third
  site is anticipated.
- **3+ sites:** extract unconditionally. Three-file drift risk on
  a literal is a real maintenance hazard.

**Do not extract across directory boundaries via conftest.py.**
Conftest files scope to their directory and all subdirectories. A
conftest at `tests/schema/lint/_config/conftest.py` is appropriate
for that directory's test files. It should NOT be used to share
helpers with `tests/schema/lint/test_canary_naming.py` in the
parent directory — put shared cross-directory helpers in a
`tests/helpers/` or `tests/_shared.py` module instead, and import
explicitly from there.

**Do not put shared constants-only in conftest.py** if they are
also needed by production code. In that case, put the constants in
the production module (or a `_constants.py` sibling) and import
from there in both tests and production code. The conftest path is
for test-only helpers.

**Prefer plain functions to fixtures** when the helper has no
setup/teardown lifecycle (e.g., an assertion wrapper). Fixtures
add complexity (parameter signature, scope rules) that pure
functions avoid. Use a `@pytest.fixture` only when the helper
genuinely needs lazy construction or cleanup.

## Examples

### Before extraction — three-file drift risk

```python
# test_schema_validation.py
_PREFIX = "error[lint-pyproject-config-invalid]:"
def _expect_invalid(table, cli_overrides, capsys, *, substring):
    with pytest.raises(SystemExit) as excinfo:
        ResolvedLintConfig.from_dict(table, cli_overrides)
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert err.startswith(_PREFIX), err
    assert substring in err, err

# test_no_builtin_rules.py  (copy-paste with subtle drift — missing code check)
_PREFIX = "error[lint-pyproject-config-invalid]:"
def _expect_invalid(table, cli_overrides, capsys, *, substring):
    with pytest.raises(SystemExit):
        ResolvedLintConfig.from_dict(table, cli_overrides)
    err = capsys.readouterr().err
    assert substring in err  # BUG: forgot to check the prefix
```

The second file's tests still pass — but they now silently accept
the wrong stderr format if the prefix ever changes.

### After extraction — single source of truth

`tests/schema/lint/_config/conftest.py` defines `INVALID_PREFIX` and
`expect_invalid` once (see the canonical block in the Guidance
section). Each consuming test file uses the same relative import:

```python
# test_schema_validation.py
from .conftest import expect_invalid

# test_no_builtin_rules.py
from .conftest import expect_invalid  # same import, same behavior guaranteed
```

The behavioral drift in the pre-fix `test_no_builtin_rules.py` is
eliminated because there is only one implementation to maintain.

### The failure mode without the relative import

```python
# tests/schema/lint/_config/conftest.py
def expect_invalid(table, cli_overrides, capsys, *, substring):
    ...

# tests/schema/lint/_config/test_severities.py
# Missing: from .conftest import expect_invalid

def test_unknown_severity_value_rejected(capsys):
    expect_invalid(  # NameError: name 'expect_invalid' is not defined
        {"severities": {"naming/foo": "WARN"}}, {}, capsys,
        substring="severity name outside the closed set",
    )
```

Pytest auto-loads fixtures, not plain functions. The fix is
unambiguous: add the relative import.

### Bare import vs relative import

```python
# Works on some Python/pytest versions, breaks on others:
from conftest import expect_invalid

# Always works:
from .conftest import expect_invalid
```

The bare form depends on CWD being on `sys.path`, which pytest
sometimes inserts and sometimes does not depending on rootdir
inference. The relative form is unambiguous because
`tests/schema/lint/_config/__init__.py` (which exists in this
codebase) makes the directory a real Python package — relative
imports work the standard way.

## Related Learnings

- [[pytest-static-analysis-gate-ratchet-2026-05-02]] — sibling pytest-infrastructure learning; covers running ruff/mypy as subprocess tests with directory-scoped path lists
- [[mock-patch-c-extension-method-descriptor-2026-05-06]] — references conftest.py in its Rule 3 ("Establish the pattern in conftest/test-helpers when..."); this learning explains the import semantics gotcha that must be observed when doing so
- [[parametrized-matrix-tests-inherit-schema-validators-2026-05-12]] — pattern for parametrized cross-test inheritance; uses fixture-injection (auto-load) where this learning uses plain functions (explicit import) — choose based on whether the helper has lifecycle needs

## Discovered During

D6a U2 ce:review follow-ups (commit `1dea189`). The maintainability
reviewer (M3) surfaced the three-file `_expect_invalid` duplication
during the 9-reviewer parallel pass on commit `a039a51`. The
relative-import gotcha was discovered during the extraction itself:
the first attempt at `expect_invalid` usage in the consuming test
files failed with `NameError`, requiring the explicit `from
.conftest import expect_invalid` lines.
