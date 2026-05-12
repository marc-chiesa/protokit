"""Meta-test: assert the CI matrix actually exercises ``test_perf_smoke``.

The companion ``test_perf_smoke.py`` is gated by
``@pytest.mark.skipif(sys.platform != "linux" or sys.version_info[:2] != (3, 12))``.
That predicate is correct today, but only because the CI matrix
contains a ``ubuntu-latest`` × ``python: "3.12"`` cell. If a future
change drops py3.12 from the matrix without also updating the skipif,
the perf smoke would silently skip on **every** cell — a fail-open
failure mode (D5 plan / R23b / KTD-3).

This meta-test closes that gap by **statically parsing**
``.github/workflows/ci.yml`` at test time and asserting that the
matrix contains at least one cell matching the perf smoke's predicate.
If the file is absent, unparseable, or doesn't match: this test fails
loudly (fail-closed, NOT skip).

**Implementation note**: this is a static parse of the matrix
declaration, not a cross-cell aggregation. The test verifies the
matrix *contains* the predicate-matching cell; it does NOT verify
that cell *actually ran* the smoke this CI run (which would require
new CI workflow plumbing — artifact upload/download, post-matrix
aggregator job — that D5 plan explicitly keeps out of scope).

**``pytest -m "not slow"`` interaction**: a fast-iteration invocation
that excludes the ``slow`` marker would skip the perf smoke even on
the predicate-matching cell. This is acceptable for D5: fast-iteration
runs are developer-local; CI runs use the default marker set and
exercise the smoke.

**Security: ``yaml.safe_load`` only**. We use ``yaml.safe_load`` —
NEVER ``yaml.load()`` without an explicit ``SafeLoader``. The latter
deserializes arbitrary Python objects from YAML, which is a code-
execution surface. ``ci.yml`` is in-repo and not attacker-controlled
today, but the safe loader keeps the contract robust against future
test-fixture reuse on attacker-influenced YAML.
"""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CI_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"

# The predicate components the perf smoke checks via skipif. Keeping
# these inline (not imported from test_perf_smoke) avoids coupling the
# meta-test to importing the smoke module — the meta-test should be
# able to fail loudly even if the smoke module itself has a bug.
#
# Naming convention: the `_STARTSWITH` / `_EQUALS` suffix encodes the
# match semantics. A future maintainer adding a third predicate axis
# sees the suffix at the constant definition site and knows whether to
# use `str.startswith` (e.g., ubuntu-latest / ubuntu-22.04 / etc.) or
# `==` (exact pin).
_REQUIRED_PYTHON_VERSION_EQUALS = "3.12"
_REQUIRED_RUNNER_OS_STARTSWITH = "ubuntu"


def _load_ci_workflow() -> dict[str, Any]:
    """Parse ``.github/workflows/ci.yml`` via ``yaml.safe_load``.

    Returns the top-level YAML mapping. Fails the test with a clear
    error message if the file is absent or unparseable.
    """
    if not _CI_WORKFLOW_PATH.is_file():
        pytest.fail(
            f"CI workflow not found at {_CI_WORKFLOW_PATH}; perf smoke "
            f"coverage cannot be verified. If the workflow moved, update "
            f"this meta-test's _CI_WORKFLOW_PATH constant."
        )
    text = _CI_WORKFLOW_PATH.read_text()
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        pytest.fail(
            f"CI workflow at {_CI_WORKFLOW_PATH} did not parse as YAML: {exc!r}. "
            f"Fix the workflow before merging."
        )
    if not isinstance(parsed, dict):
        pytest.fail(
            f"CI workflow at {_CI_WORKFLOW_PATH} parsed as "
            f"{type(parsed).__name__}, not a mapping. Top-level workflow "
            f"shape changed; update this meta-test."
        )
    return parsed


def _iter_matrix_cells(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    """Enumerate matrix cells from every job in the workflow.

    Each cell is the cartesian product of ``strategy.matrix`` axes
    PLUS the job's ``runs-on``. Returns a list of dicts where each
    dict carries every axis value plus a ``runs_on`` key.

    A job without a ``strategy.matrix`` block contributes one cell
    (the bare ``runs-on``). A job with a matrix contributes
    ``len(axis_1) × len(axis_2) × ...`` cells.
    """
    cells: list[dict[str, Any]] = []
    jobs = workflow.get("jobs", {})
    if not isinstance(jobs, dict):
        return cells
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        runs_on = job.get("runs-on", "")
        strategy = job.get("strategy", {})
        matrix = strategy.get("matrix", {}) if isinstance(strategy, dict) else {}
        if not isinstance(matrix, dict) or not matrix:
            cells.append({"runs_on": runs_on})
            continue
        # Loud-on-drift guard: matrix.include / matrix.exclude could
        # silently invert the fail-closed posture (e.g. matrix.exclude
        # dropping the ubuntu+py3.12 cell while the cartesian product
        # still matches it). Force the meta-test to be updated when
        # ci.yml adopts those extensions.
        if "include" in matrix or "exclude" in matrix:
            pytest.fail(
                f"job {job_name!r} uses matrix include/exclude extensions; "
                f"update _iter_matrix_cells to honor them or the fail-closed "
                f"coverage guarantee silently inverts."
            )
        axes = [
            (name, values)
            for name, values in matrix.items()
            if isinstance(values, list)
        ]
        if not axes:
            cells.append({"runs_on": runs_on})
            continue
        # Cartesian product over the axis value lists.
        axis_names = [name for name, _ in axes]
        axis_values = [values for _, values in axes]
        for combo_values in itertools.product(*axis_values):
            cell: dict[str, Any] = dict(zip(axis_names, combo_values, strict=True))
            cell["runs_on"] = runs_on
            cells.append(cell)
    return cells


def _cell_matches_predicate(cell: dict[str, Any]) -> bool:
    """Return True if ``cell`` matches the perf smoke's skipif predicate.

    ``ubuntu-latest`` and ``ubuntu-22.04`` both qualify (both are
    linux runners). ``python`` values come from the matrix as strings
    like ``"3.12"``.
    """
    runs_on = str(cell.get("runs_on", ""))
    python = str(cell.get("python", ""))
    return (
        runs_on.startswith(_REQUIRED_RUNNER_OS_STARTSWITH)
        and python == _REQUIRED_PYTHON_VERSION_EQUALS
    )


def test_ci_matrix_contains_perf_smoke_cell() -> None:
    """At least one CI cell must match the perf smoke's skipif predicate.

    Fail-closed (D5 plan / R23b / KTD-3): if the matrix is missing
    a linux + py3.12 cell, this test fails so the regression is
    surfaced loudly rather than the smoke silently skipping on
    every cell.
    """
    workflow = _load_ci_workflow()
    cells = _iter_matrix_cells(workflow)
    assert cells, (
        f"CI workflow at {_CI_WORKFLOW_PATH} produced zero matrix cells. "
        f"The workflow shape may have changed; update this meta-test."
    )

    matching = [c for c in cells if _cell_matches_predicate(c)]
    assert matching, (
        f"CI matrix has no cell matching the perf smoke's skipif "
        f"predicate (runs-on startswith {_REQUIRED_RUNNER_OS_STARTSWITH!r} AND "
        f"python == {_REQUIRED_PYTHON_VERSION_EQUALS!r}). The perf smoke "
        f"will silently skip on every cell — a fail-open regression. "
        f"Either restore the linux + py{_REQUIRED_PYTHON_VERSION_EQUALS} "
        f"cell in {_CI_WORKFLOW_PATH}, or update both test_perf_smoke.py's "
        f"skipif predicate AND this meta-test's "
        f"_REQUIRED_PYTHON_VERSION_EQUALS constant in lockstep. "
        f"Cells observed: {cells}"
    )
