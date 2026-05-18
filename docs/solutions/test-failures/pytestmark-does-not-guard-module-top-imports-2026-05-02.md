---
title: "pytestmark does NOT guard module-top imports — use pytest.importorskip"
date: 2026-05-02
category: docs/solutions/test-failures
module: testing/pytest-conventions
problem_type: test_failure
component: testing_framework
symptoms:
  - "Test module fails collection (RED) on a CI matrix cell that lacks an optional dep"
  - "ModuleNotFoundError surfaces during pytest collection, not as a yellow skip"
  - "Test passes locally where the optional dep IS installed; only the matrix axis without the dep breaks"
  - "Requirements/design docs give wrong guidance such as `OR pytestmark skipif guards`"
root_cause: wrong_api
resolution_type: code_fix
severity: high
tags:
  - pytest
  - importorskip
  - pytestmark
  - optional-dependencies
  - ci-matrix
  - collection-error
  - module-skip
---

# pytestmark does NOT guard module-top imports — use pytest.importorskip

## Problem

A test module that needs an optional dependency at module-top level (e.g., `import protoxy` so test bodies can construct `protoxy.ProtoxyError`) was guarded with `pytestmark = pytest.mark.skipif(not _has_dep(), reason="...")` AFTER the import. The `pytestmark` correctly skips every test in the module when the dep is absent — but pytest must IMPORT the module first to discover those tests, and module-top `import optional_dep` runs at import time, BEFORE `pytestmark` is evaluated. The result: any CI cell without the dep produces a collection error (red), not a skip (yellow).

In this codebase, the issue surfaced in `tests/schema/lint/test_compile_protoxy_fallback.py` for a `has_protoxy: [true, false]` CI matrix. The `has_protoxy: false` cells (2 of 4 jobs) would have failed at collection the moment a GitHub remote was configured. The protokit-lint Delivery 1 requirements doc itself gave incorrect guidance ("Audit + add `pytest.importorskip(\"protoxy\")` at module top **OR** `pytestmark` skipif guards") — the OR is wrong; only `importorskip` works for module-top imports.

## Symptoms

- A pytest run on a host without the optional dep emits a collection error: `ModuleNotFoundError: No module named '<dep>'` from the test file's module-top import line, BEFORE any test runs.
- The skipif marker on the class or module-level `pytestmark` never gets a chance to fire.
- The test file passes cleanly on hosts where the dep IS installed, masking the bug during local development.
- CI matrix cells configured to test "without the optional extra" go red the moment the matrix activates.

## What Didn't Work

- **`pytestmark = pytest.mark.skipif(not _has_dep(), reason="...")` at module level, AFTER the import.** This is the documented way to skip every test in a module, and it works for skipping test execution. It does NOT work for guarding module-top imports because pytest evaluates `pytestmark` only after successfully importing the module. The optional-dep import has already raised by then.
- **Class-level `pytestmark` on `TestCompileProtoxyFallback`.** Same root cause: the class is constructed during module import, after the offending import line.
- **Wrapping the import in `try: import protoxy except ImportError: pass`.** Hides the real failure and lets test bodies reference an undefined name. Tests that were supposed to skip would now `NameError` instead.

## Solution

Use `pytest.importorskip("<name>")` at module top, BEFORE any `from <name> import ...` statement. `importorskip` performs the import; on failure it raises `pytest.skip.Exception` with `allow_module_level=True`, which pytest treats as a module-level skip (yellow). It also returns the imported module so the rest of the module can use it as a normal name.

```python
# tests/schema/lint/test_compile_protoxy_fallback.py — fixed shape

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

# Module-level skip via importorskip: when protoxy is absent, the
# module is skipped at collection time WITHOUT a collection error.
# A bare `import protoxy` here would raise ModuleNotFoundError on
# `has_protoxy: false` CI cells, turning the cell red instead of
# skipping it. Subsequent imports run only after the skip gate, so
# E402 is suppressed for them.
protoxy = pytest.importorskip("protoxy")

from protokit.schema import compile as compile_module  # noqa: E402
from protokit.schema.compile import (  # noqa: E402
    LintCompileDiagnostic,
    compile_protos_to_result,
)


def _make_protoxy_error(msg: str) -> protoxy.ProtoxyError:
    return protoxy.ProtoxyError(msg, [], "[]")


# ... rest of tests use `protoxy.ProtoxyError` etc. normally ...
```

Notes on the fix shape:

- The bare `pytest.importorskip("<name>")` line replaces both the `import <name>` AND the `pytestmark = pytest.mark.skipif(...)` block. Don't keep the `pytestmark` — it's redundant after `importorskip`.
- The return value of `importorskip` IS the imported module. Bind it (`protoxy = pytest.importorskip("protoxy")`) so the rest of the file can reference attributes (`protoxy.ProtoxyError`, etc.).
- Other imports that come after `importorskip` need `# noqa: E402` for ruff (module-level import not at top of file). The lateness is intentional — those imports must NOT run on cells where the optional dep is absent.

## Why This Works

`pytest.importorskip` is the canonical pytest-aware import. Internally it does roughly:

```python
def importorskip(modname, ...):
    try:
        return importlib.import_module(modname)
    except ImportError:
        raise pytest.skip.Exception(
            f"could not import {modname!r}: ...",
            allow_module_level=True,
        )
```

The `allow_module_level=True` flag is the key — pytest's collection machinery catches this specific exception class and treats it as "skip the entire module, do not report a collection error." A plain `pytest.skip(...)` at module level fails with `Failed: It is not possible to skip from a module-level call ...`; only `importorskip` (or `pytest.skip(..., allow_module_level=True)`) does the right thing.

`pytestmark` is implemented as a marker pytest reads from the imported module's namespace. The reading happens during pytest's collection of test items WITHIN the module, after `importlib.import_module` has already returned successfully. There is no point in time when pytest reads `pytestmark` before the module's top-level statements have all run.

## Prevention

1. **Treat any module-top `import optional_dep` as suspect.** If the dep is optional in `pyproject.toml` (declared in `[project.optional-dependencies]` rather than required), the import line MUST be guarded with `pytest.importorskip` at module top. `pytestmark` is not a substitute.

2. **Don't replicate this pattern from existing test files without checking.** A file that has both an `import optional_dep` and a `pytestmark = pytest.mark.skipif(not _has_dep(), ...)` is broken on the no-dep matrix axis even if it passes locally — the local dev has the dep installed.

3. **Verify by simulation.** A quick sanity check that confirms the gate works:

   ```bash
   python -c "
   import sys, importlib.abc
   class Block(importlib.abc.MetaPathFinder):
       def find_spec(self, name, path=None, target=None):
           if name == '<optional_dep>':
               raise ModuleNotFoundError(\"No module named '<optional_dep>'\")
           return None
   sys.meta_path.insert(0, Block())
   sys.modules.pop('<optional_dep>', None)

   import importlib.util, pytest
   spec = importlib.util.spec_from_file_location('t', 'tests/path/to/test.py')
   mod = importlib.util.module_from_spec(spec)
   try:
       spec.loader.exec_module(mod)
   except pytest.skip.Exception as e:
       print(f'OK: pytest.skip raised at module level: {e}')
   except ModuleNotFoundError as e:
       print(f'BAD: still ModuleNotFoundError: {e}')
   "
   ```

   `OK: pytest.skip raised at module level` means the gate works. `BAD: still ModuleNotFoundError` means the file will fail collection on the no-dep CI cell.

4. **Update requirements / design docs** that prescribe optional-dep guarding. Replace any `pytestmark` guidance for module-top-import cases with `pytest.importorskip`. If a doc says "Audit + add `pytest.importorskip(...)` at module top OR `pytestmark` skipif guards" — fix the OR. The `pytestmark` half is wrong for module-top imports.

5. **Tests that use the optional dep ONLY inside test bodies** (no module-top import) can use `pytestmark` cleanly. The split:

   - **`from optional_dep import ...` at module top → `pytest.importorskip` required.**
   - **Optional dep used only inside test functions → `pytestmark` is sufficient.** (Pytest collects the module without trouble; the inside-test `import` only runs when the test runs, which `pytestmark` skips on the no-dep cell.)

## Related Issues

- `docs/solutions/best-practices/pytest-static-analysis-gate-ratchet-2026-05-02.md` — the static-analysis gate that runs ruff and mypy via subprocess inside pytest tests. Same general theme: the test file IS the test collection; gotchas at the collection layer (like this one) bypass the test logic entirely.
- `docs/brainstorms/2026-04-30-protokit-lint-delivery-1-foundation-requirements.md` (A9-1) — requirements doc that gave the incorrect "OR pytestmark skipif guards" guidance. Future requirements docs should not propagate the OR.
- [[fail-closed-ci-matrix-coverage-meta-test]] — forward complement that closes the loop on optional-dep matrix coverage. Once `pytest.importorskip` is in place at module top, this doc's CI-matrix meta-test pattern verifies the CI YAML actually has the complementary no-dep cell. The two together prevent both the silent-collect-failure (`importorskip` solves) and the silent-skip-on-every-cell (meta-test solves) failure modes.
- [[module-import-time-fixture-mapping-fail-loud-blast-radius-2026-05-18]] — same mechanism, opposite framing. This doc treats collection-time blast radius as a BUG (`pytestmark` cannot guard against collection-time errors from required imports). The D6b U6 doc treats the SAME mechanism as a DELIBERATE design tool (building a fixture-rule_id mapping at module-import time so a misconfigured fixture intentionally fails all tests in the module, surfacing the contract violation immediately). Both perspectives are correct in their own context: use `pytest.importorskip` when the dependency is genuinely optional and the test should skip; use intentional import-time validation when the resource is a required precondition and failure-to-collect is the correct signal.
