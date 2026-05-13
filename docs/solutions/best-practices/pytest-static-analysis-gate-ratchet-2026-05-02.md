---
title: "Pytest-driven static analysis gate: ruff + mypy as a ratcheting subprocess test"
date: 2026-05-02
last_updated: 2026-05-12
category: docs/solutions/best-practices
module: tooling/static-analysis
problem_type: best_practice
component: testing_framework
severity: low
symptoms:
  - "ruff and mypy configured in pyproject.toml but not run in CI; regressions accumulate silently"
  - "mypy --strict on the full repo produces ~30+ errors; a full-repo gate would fail forever"
  - "Developers want fast TDD loops on focused test files but still want a full-run gate"
applies_when:
  - "Codebase has mypy or ruff configured but not enforced in CI or local workflow"
  - "Feature branch cleans up static-analysis violations on a subset of paths"
  - "Team wants enforcement without a big-bang cleanup of pre-existing violations"
  - "pytest is the default local quality gate"
related_components:
  - tooling
  - development_workflow
tags:
  - pytest
  - mypy
  - ruff
  - static-analysis
  - ci-gate
  - subprocess-test
  - ratchet-pattern
  - type-checking
---

# Pytest-driven static analysis gate: ruff + mypy as a ratcheting subprocess test

## Context

A full pytest run is the natural moment to catch static-analysis regressions: the developer already has the venv active, the repo is in a known state, and the run is the de-facto gate before pushing. Without a static-analysis test, `mypy` and `ruff` can drift from "passing" to "broken" between CI runs while remaining invisible during local TDD loops.

This pattern was introduced during the protokit-lint Delivery 1 review. The codebase had `[tool.mypy] strict = true` declared in `pyproject.toml` for the full repo, but mypy was absent from dev-deps, not run in CI, and therefore unenforced — strict mode was nominal. A 10-reviewer `ce:review` pass surfaced this, and the fix was a pytest-native static-analysis gate with an explicit ratchet mechanism.

The other constraint that shaped the design: the broader codebase had ~172 ruff errors and ~31 mypy strict-mode errors at the time. Gating the whole repo would fail forever. The gate has to start scoped and widen as cleanup happens.

## Guidance

### The test file

Create `tests/test_static_analysis.py`. The file is a standard pytest module — no plugins, no fixtures. Replace `<package>`, `<file>`, `<subpackage>`, `<test_dir>` with the concrete paths from your repo; angle brackets are not valid in real path lists.

```python
"""Static-analysis gate run as part of the pytest suite.

Pytest discovers this file like any other test module, so a full
``pytest`` invocation runs ``ruff`` and ``mypy`` against the same
scope CI gates and fails closed on any regression. Running pytest
against a specific file (e.g. ``pytest tests/<dir>/...``) skips this
gate, so focused TDD loops stay fast.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Paths gated by ``ruff check``. Tests are linted but not strict-typed
# in this codebase — the test files appear here but not in
# ``_TYPE_CHECK_PATHS``. When adding a SOURCE module that is now clean
# under both tools, add it to BOTH lists.
_LINT_PATHS: tuple[str, ...] = (
    "src/<package>/<file>.py",
    "src/<package>/<subpackage>",
    "tests/<test_dir>",
    "tests/test_static_analysis.py",
)

# Paths gated by ``mypy --strict`` (configuration in pyproject.toml).
# Mirrors the CI step in .github/workflows/ci.yml; if you add a path
# here also update CI so local and CI stay in lockstep.
_TYPE_CHECK_PATHS: tuple[str, ...] = (
    "src/<package>/<file>.py",
    "src/<package>/<subpackage>",
)


def _run(tool: str, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run ``python -m <tool> <args>``.

    Uses ``sys.executable`` so the test inherits the venv pytest is
    running under — avoids picking up a system mypy/ruff that may not
    match the project's pinned versions. argv is passed as a list, so
    ``shell=False`` applies — no shell interpolation.
    """
    return subprocess.run(
        [sys.executable, "-m", tool, *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _assert_paths_exist(paths: Sequence[str], label: str) -> None:
    """Surface stale gated entries with a clear message before invoking the tool.

    Without this pre-check a typo or a path deleted without updating
    the gate list manifests as a confusing ruff/mypy error rather
    than a clean "path not found" failure.
    """
    missing = [p for p in paths if not (_REPO_ROOT / p).exists()]
    assert not missing, (
        f"{label} references paths that no longer exist: {missing}. "
        f"Update {Path(__file__).name} to remove or rename them."
    )


def test_ruff_check_clean_on_gated_paths() -> None:
    if not _module_available("ruff"):
        pytest.skip("ruff not installed; run `pip install -e '.[dev]'`")
    _assert_paths_exist(_LINT_PATHS, "_LINT_PATHS")
    result = _run("ruff", ["check", *_LINT_PATHS])
    assert result.returncode == 0, (
        "ruff check failed on gated paths.\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def test_mypy_strict_clean_on_gated_paths() -> None:
    if not _module_available("mypy"):
        pytest.skip("mypy not installed; run `pip install -e '.[dev]'`")
    _assert_paths_exist(_TYPE_CHECK_PATHS, "_TYPE_CHECK_PATHS")
    result = _run("mypy", _TYPE_CHECK_PATHS)
    assert result.returncode == 0, (
        "mypy --strict failed on gated paths.\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
```

### pyproject.toml — dev deps

Add `mypy` and `ruff` to the `[dev]` optional-dependency group. Both were missing from the group before this change.

```toml
[project.optional-dependencies]
dev = [
    "pytest",
    # ... project-specific dev deps ...
    "mypy>=1.8",
    "ruff>=0.5",
]
```

### pyproject.toml — mypy configuration

```toml
[tool.mypy]
python_version = "3.10"
strict = true
warn_return_any = true
warn_unused_configs = true

# Third-party libs without published type stubs. Adding stub packages
# (e.g., types-protobuf) risks stub/runtime drift; ignoring missing
# imports here keeps the strict-mode signal-to-noise ratio useful for
# the project's own code.
[[tool.mypy.overrides]]
module = ["google.protobuf.*", "protoxy"]
ignore_missing_imports = true
```

### CI step

Add a dedicated mypy step that runs before the test suite. Scoped to the same paths as `_TYPE_CHECK_PATHS`:

```yaml
- name: Run mypy (scoped to clean surface)
  # Strict-mode mypy is configured in pyproject.toml but the broader
  # codebase has pre-existing strict-mode errors. This step gates ONLY
  # the modules that are currently clean so the strict signal is
  # enforced for new/refactored code without forcing pre-existing
  # modules to clear strict mode in the same PR. Future deliveries
  # widen the scope by extending the path list here.
  run: |
    python -m mypy \
      src/<package>/<file>.py \
      src/<package>/<subpackage>/

- name: Run test suite
  run: pytest tests/ -v
```

The pytest suite run (last step) fires the same gate again via `test_static_analysis.py`, so the paths are validated twice per CI cell: once fast and standalone, once as part of the full test collection. Two gates with the same scope feels redundant but they're complementary — the dedicated step gives faster feedback in CI; the pytest test is what fires on the developer's machine before push.

## Why This Matters

**The ratchet is the key property.** The path list in `_LINT_PATHS` / `_TYPE_CHECK_PATHS` only grows. Once a module passes both tools and gets added, there is no mechanical way to re-introduce a violation without the gate failing. The gate does not need to cover the full repo on day one — it covers the clean surface and holds it.

This is the compound-engineering signature: each delivery that cleans up a file widens the gate, and the gate prevents that file from regressing back. The codebase becomes monotonically cleaner.

The secondary benefit is developer experience: the same gate as CI runs without remembering a separate command. `pytest` already runs; the static-analysis tests come along for free on full runs and skip silently on focused runs (`pytest tests/specific.py` never fires these tests, so TDD loops stay fast).

Three smaller-but-important design choices:

- **`sys.executable -m ruff` / `sys.executable -m mypy`** guarantees the test uses the tool versions the project pinned in dev-deps. A system-installed ruff or mypy at a different version produces different output.
- **`pytest.skip` when a tool isn't installed** is intentional softness for fresh-checkout DX. A hard fail would block someone running `pytest` before reading the setup docs. The skip message ("run `pip install -e '.[dev]'`") is actionable.
- **Subprocess test, not a pytest plugin.** `pytest-ruff` / `pytest-mypy` plugins run on every pytest invocation including focused TDD runs (slow), bring their own version constraints, and are another dependency to keep in lockstep with the tool versions in dev-deps. The subprocess test is simpler and only fires on full pytest runs.

## Caveats

- **The pytest skip is NOT a substitute for the dedicated CI step.** A CI job that forgets to install the `[dev]` extra would see green pytest (the gate skips silently) and a missing tool. Only the dedicated CI step (`python -m mypy ...`) catches that failure mode. Keep both — they cover different gaps.
- **The `_LINT_PATHS` / `_TYPE_CHECK_PATHS` ↔ CI yaml duplication** is fine for two callers (one pytest test, one CI step). When a third caller appears (a pre-commit hook, a `Makefile` target, an `nox`/`tox` session), hoist the path list into one source of truth — a `pyproject.toml` table read by all callers, or a `scripts/static_analysis.py` invoked from each. Today the comment "mirrors the CI step" enforces the sync manually; that scales to two.
- **`_REPO_ROOT = Path(__file__).resolve().parent.parent` assumes the test file lives exactly two levels deep.** If you copy this into a project where the gate test is at `tests/static/test_gate.py`, the parent count is wrong. Either keep the gate at `tests/test_static_analysis.py` or compute `_REPO_ROOT` by walking up to a marker file (`pyproject.toml`).
- **New test files at the repo root level require explicit per-file `_LINT_PATHS` entries — directory entries do not cover them.** (Added 2026-05-12 from the D5 U5 ce:review.) `_LINT_PATHS` mixes two entry styles: directory entries that gate every file recursively (`"src/protokit/schema/lint"`, `"tests/schema/lint"`) and per-file entries that gate only the specific path listed (`"tests/test_cli_utils.py"`, `"tests/test_static_analysis.py"`). When a new test file is created at the `tests/` root — not in a subdirectory already covered by a directory entry — it silently escapes the gate until explicitly added. The pass-fail signal is identical to a real green run: ruff/mypy pass on the listed paths and the new file is simply not in the listed paths. The gap is invisible. In the D5 U5 ce:review, project-standards (PS-U5-01 at 0.88) and testing (T-U5-04 at 0.85) both flagged that `tests/test_builtin_lint_runtime_warnings.py` (created in the U5 feat commit) was not in `_LINT_PATHS`. The pre-existing `tests/test_builtin_lint_formatter.py` had been outside the ratchet since D3 — at minimum two complete delivery cycles — and was added in the same follow-up commit under pay-as-you-touch. New test file checklist:
  - Does the parent directory have a directory entry in `_LINT_PATHS`? If so, no action needed (the new file is auto-covered).
  - If not, add the new file path to `_LINT_PATHS` in the **same commit** that creates the file. The ratchet should never lag the implementation.
  - When adding a new per-file entry, grep the same directory level for un-gated neighbors and fix them in the same commit (pay-as-you-touch).
  - Convention recommendation: prefer placing new test files under a directory that already has a directory entry, rather than as per-file entries at the root level. Directory entries auto-scale; per-file entries require manual updates and tend to drift.

## When to Apply

Apply this pattern when:

1. A codebase has `mypy` or `ruff` configuration declared but not enforced in CI or local runs.
2. A feature branch cleans up a subset of violations — the delivery introduces clean files that need protection going forward.
3. The team wants static-analysis enforcement without forcing a big-bang cleanup of pre-existing violations.
4. The team runs pytest as the default local quality gate and wants lint/types included without a `Makefile` target to remember.

Do not apply when:

- The full repo already passes both tools — configure `mypy` and `ruff` as pre-commit hooks or top-level CI steps without the path-list scoping.
- The team already uses `pytest-ruff` / `pytest-mypy` plugins and accepts their per-invocation overhead and version-coupling.

## Examples

### Regression injection probe (verifies the gate actually closes)

To verify the gate works, inject a violation into a gated file, run pytest, confirm failure, then restore. This was used to verify the implementation in protokit:

```python
# src/<package>/<gated_file>.py — add at top of file
import os  # unused import — F401 per ruff
```

```text
$ pytest tests/test_static_analysis.py -q
F.
FAILED tests/test_static_analysis.py::test_ruff_check_clean_on_gated_paths
AssertionError: ruff check failed on gated paths.
stdout:
src/<package>/<gated_file>.py:1:1: F401 [*] `os` imported but unused
Found 1 error.
```

Exit code: 1. Gate confirmed closed. Then `git checkout <file>` restores. The same probe works for mypy: add a deliberately un-typed function to a gated module and confirm `test_mypy_strict_clean_on_gated_paths` fails.

### Before / after this pattern

**Before:** `pyproject.toml` contains `[tool.mypy] strict = true`. The CI workflow has no mypy step. `mypy` is not in dev-deps. The setting is nominal — strict mode is declared but never run. New code can ship with `# type: ignore` proliferation or untyped functions without anyone noticing.

**After:** `mypy` and `ruff` are in dev-deps. `pytest` runs the gate on every full invocation. CI has a dedicated mypy step scoped to clean paths. A new file added to the gated surface but left without type annotations fails pytest immediately on the author's machine, before push. Adding a new clean module to the gate is a one-line change to two tuples — and the team can do it incrementally as files clear.

## Related

- `docs/solutions/security-issues/formatter-systemexit-exit-code-bypass-2026-04-19.md` — prior gate-integrity fix; same broad theme of "the CI exit-code contract must not be silently defeated," but different mechanism (BaseException hierarchy, not tooling enforcement).
- `docs/plans/2026-05-01-001-feat-protokit-lint-d1-foundation-plan.md` — plan that introduced per-module ruff/mypy expectations, making the static-analysis gate a natural follow-up.
- `docs/brainstorms/2026-04-30-protokit-lint-delivery-1-foundation-requirements.md` — requirements doc noting `[tool.ruff] target-version = "py310"` was already configured; context for why ruff was a pre-existing tool being formally gated for the first time.
- [[fail-closed-ci-matrix-coverage-meta-test]] — formalizes the CI-yaml ↔ source duplication risk that the caveat section above already flagged. Same gate-as-pytest-test philosophy applied to CI matrix coverage: parse `.github/workflows/ci.yml` via `yaml.safe_load` and assert at-least-one matrix cell exercises a `@pytest.mark.skipif`-gated test's predicate. The "mirrors the CI step" comment pattern in this doc is the informal version of what the meta-test mechanizes.
- [[smoke-not-benchmark-loose-threshold-calibration]] — parallel gate-as-pytest-test pattern for a different quality dimension (performance regression detection instead of static-analysis cleanliness). Both patterns embed enforcement inside pytest rather than in CI YAML; both use generous tolerances (loose threshold / clean-paths-only) to keep the gate stable.
- [[conftest-plain-function-relative-import-2026-05-12]] — sibling pytest-infrastructure learning. This learning gates file-set membership; the conftest learning gates how shared test helpers move between same-directory test files (3+ duplicate threshold) and surfaces the auto-load-fixtures-not-functions gotcha. Both are pytest discipline applied to keep the test infrastructure honest.
