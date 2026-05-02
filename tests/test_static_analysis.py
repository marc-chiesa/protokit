"""Static-analysis gate run as part of the pytest suite.

Pytest discovers this file like any other test module, so a full
``pytest`` invocation runs ``ruff`` and ``mypy`` against the same
scope CI gates and fails closed on any regression. Running pytest
against a specific file (e.g. ``pytest tests/schema/...``) skips
this gate, so focused TDD loops stay fast.

Scope today is the protokit-lint Delivery 1 surface. Future
deliveries that clean up a pre-existing file should add it to
``_LINT_PATHS`` and/or ``_TYPE_CHECK_PATHS`` so the gate ratchets
forward and prevents regressions in newly-clean files.
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
    "src/protokit/_cli_utils.py",
    "src/protokit/schema/compile.py",
    "src/protokit/schema/lint",
    "tests/schema/lint",
    "tests/test_cli_utils.py",
    "tests/test_static_analysis.py",
)

# Paths gated by ``mypy --strict`` (configuration in pyproject.toml).
# Mirrors the CI step in .github/workflows/ci.yml; if you add a path
# here also update CI so local and CI stay in lockstep.
_TYPE_CHECK_PATHS: tuple[str, ...] = (
    "src/protokit/_cli_utils.py",
    "src/protokit/schema/compile.py",
    "src/protokit/schema/lint",
)


def _run(tool: str, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run ``python -m <tool> <args>``.

    Uses ``sys.executable`` so the test inherits the venv pytest is
    running under — avoids picking up a system mypy/ruff that may not
    match the project's pinned versions. argv is passed as a list, so
    ``shell=False`` applies — no shell interpolation of paths or args.
    """
    return subprocess.run(
        [sys.executable, "-m", tool, *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _module_available(name: str) -> bool:
    """Return True if ``name`` is importable in the current interpreter."""
    return importlib.util.find_spec(name) is not None


def _assert_paths_exist(paths: Sequence[str], label: str) -> None:
    """Surface stale gated entries with a clear message before invoking the tool.

    Without this pre-check a typo or a path that was deleted without
    updating the gate list manifests as a confusing ruff/mypy error
    rather than a clean "path not found" failure.
    """
    missing = [p for p in paths if not (_REPO_ROOT / p).exists()]
    assert not missing, (
        f"{label} references paths that no longer exist: {missing}. "
        f"Update {Path(__file__).name} to remove or rename them."
    )


def test_ruff_check_clean_on_gated_paths() -> None:
    """``ruff check`` must pass on every path in ``_LINT_PATHS``.

    Catches regressions in lint rules selected by ``[tool.ruff.lint]``
    in ``pyproject.toml`` (E, F, W, I, N, UP, B, SIM). Auto-fix is
    NOT used — a regression must be addressed by the author, not
    silently rewritten by the test runner.
    """
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
    """``mypy --strict`` (config in pyproject.toml) on the D1 surface.

    Mirrors the scoped CI step. Strict-mode mypy is configured
    repo-wide but only enforced on these paths today; the broader
    codebase has ~30 pre-existing strict-mode errors that future
    deliveries can clean up incrementally.
    """
    if not _module_available("mypy"):
        pytest.skip("mypy not installed; run `pip install -e '.[dev]'`")
    _assert_paths_exist(_TYPE_CHECK_PATHS, "_TYPE_CHECK_PATHS")
    result = _run("mypy", _TYPE_CHECK_PATHS)
    assert result.returncode == 0, (
        "mypy --strict failed on gated paths.\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
