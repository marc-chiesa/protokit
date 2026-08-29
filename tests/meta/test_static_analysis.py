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
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Paths gated by ``ruff check``. Tests are linted but not strict-typed
# in this codebase — the test files appear here but not in
# ``_TYPE_CHECK_PATHS``. When adding a SOURCE module that is now clean
# under both tools, add it to BOTH lists.
_LINT_PATHS: tuple[str, ...] = (
    "src/protokit/_cli_utils.py",
    "src/protokit/formatters/_builtin_lint.py",
    "src/protokit/message/_presence.py",
    "src/protokit/message/_selector.py",
    "src/protokit/message/_setmatch.py",
    "src/protokit/message/hamcrest.py",
    "src/protokit/message/matchers.py",
    "src/protokit/message/pytest_plugin.py",
    "src/protokit/forensics",
    "src/protokit/schema/compile.py",
    "src/protokit/schema/lint",
    "src/protokit/storage",
    "tests/_buf_helpers.py",
    "tests/forensics",
    "tests/parity",
    "tests/schema/lint",
    "tests/storage",
    "tests/meta/test_buf_parity_pin_drift.py",
    "tests/formatters/test_builtin_lint_formatter.py",
    "tests/formatters/test_builtin_lint_runtime_warnings.py",
    "tests/core/test_cli_utils.py",
    "tests/message/test_field_selector.py",
    "tests/formatters/test_formatters_cli.py",
    "tests/message/test_hamcrest_adapter.py",
    "tests/message/test_hamcrest_extra.py",
    "tests/message/test_ignore_predicate.py",
    "tests/message/test_match_partial.py",
    "tests/message/test_message_public_surface.py",
    "tests/message/test_per_field_tolerance.py",
    "tests/message/test_presence_mode.py",
    "tests/message/test_proto_match.py",
    "tests/meta/test_pytest_policy.py",
    "tests/message/test_set_comparison.py",
    "tests/meta/test_static_analysis.py",
    "tests/meta/test_docs_test_refs.py",
    "tests/meta/test_drift_defense_convention_presence_ratchet.py",
    "scripts/check_docs_test_refs.py",
)

# Paths gated by ``mypy --strict`` (configuration in pyproject.toml).
# Mirrors the CI step in .github/workflows/ci.yml; add a path to BOTH
# sites in one commit. ``test_ci_mypy_step_matches_type_check_paths``
# enforces that — this list alone is not the gate.
_TYPE_CHECK_PATHS: tuple[str, ...] = (
    "src/protokit/_cli_utils.py",
    "src/protokit/forensics",
    "src/protokit/formatters/_builtin_lint.py",
    "src/protokit/message/_presence.py",
    "src/protokit/message/_selector.py",
    "src/protokit/message/_setmatch.py",
    "src/protokit/message/hamcrest.py",
    "src/protokit/message/matchers.py",
    "src/protokit/message/pytest_plugin.py",
    "src/protokit/schema/compile.py",
    "src/protokit/schema/lint",
    "src/protokit/storage",
    "scripts/check_docs_test_refs.py",
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


_CI_YAML = ".github/workflows/ci.yml"
_CI_MYPY_STEP = "Run mypy (scoped to ratcheted surface)"


def _ci_mypy_paths() -> tuple[str, ...]:
    """The paths ci.yml's scoped mypy step actually passes to mypy.

    Reads the workflow's own YAML (``safe_load``, never ``load``) rather than
    regexing the file, so a reformatted ``run:`` block does not silently start
    matching nothing and reporting an empty — and therefore trivially
    "in-lockstep" — path list.
    """
    workflow = yaml.safe_load((_REPO_ROOT / _CI_YAML).read_text())
    scripts = [
        step["run"]
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if step.get("name") == _CI_MYPY_STEP
    ]
    assert len(scripts) == 1, (
        f"expected exactly one {_CI_MYPY_STEP!r} step in {_CI_YAML}, "
        f"found {len(scripts)}. Update this test alongside the workflow."
    )
    tokens = scripts[0].replace("\\\n", " ").split()
    assert tokens[:4] == ["python", "-m", "mypy"] or tokens[:3] == [
        "python", "-m", "mypy",
    ], f"unexpected mypy invocation shape in {_CI_YAML}: {tokens[:4]!r}"
    return tuple(t.rstrip("/") for t in tokens[3:] if not t.startswith("-"))


def test_ci_mypy_step_matches_type_check_paths() -> None:
    """``ci.yml``'s mypy step and ``_TYPE_CHECK_PATHS`` gate the same paths.

    The two lists are maintained by hand in two files, and until this test
    existed nothing compared them: ``test_mypy_strict_clean_on_gated_paths``
    reads only ``_TYPE_CHECK_PATHS`` and never opens the workflow, so a path
    added to one and not the other left a green ratchet that was **not**
    evidence of the lockstep the workflow's comment claimed. It drifted
    exactly that way — ``src/protokit/forensics`` was ratcheted locally while
    CI never type-checked it.

    If this fails, add the path to BOTH sites in the same commit.
    """
    assert set(_ci_mypy_paths()) == set(_TYPE_CHECK_PATHS), (
        f"mypy gate drift between {_CI_YAML} and _TYPE_CHECK_PATHS.\n"
        f"  only in {_CI_YAML}: "
        f"{sorted(set(_ci_mypy_paths()) - set(_TYPE_CHECK_PATHS))}\n"
        f"  only in _TYPE_CHECK_PATHS: "
        f"{sorted(set(_TYPE_CHECK_PATHS) - set(_ci_mypy_paths()))}\n"
        "Add the path to BOTH sites in the same commit."
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
