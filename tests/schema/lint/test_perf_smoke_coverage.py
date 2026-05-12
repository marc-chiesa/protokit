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


# ---------------------------------------------------------------------------
# Fail-closed branch coverage for the meta-test's own internal helpers.
#
# The happy-path test above exercises only the case where ci.yml exists,
# parses as YAML, contains a mapping shape, and has no matrix include/exclude
# extensions. The four pytest.fail branches inside _load_ci_workflow and
# _iter_matrix_cells therefore have no synthetic-input coverage — a bug in
# any fail-closed code path would not be caught by the happy-path test.
# The tests below pin each fail-closed branch with synthetic input so the
# meta-test's own fail-closed guarantee is itself fail-closed.
# ---------------------------------------------------------------------------


class TestLoadCiWorkflowFailClosedBranches:
    """Pin each ``pytest.fail`` branch in ``_load_ci_workflow``."""

    def test_absent_workflow_file_fails_loudly(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """An absent ci.yml must `pytest.fail`, not skip."""
        missing = tmp_path / "nonexistent" / "ci.yml"
        monkeypatch.setattr(
            "tests.schema.lint.test_perf_smoke_coverage._CI_WORKFLOW_PATH",
            missing,
        )
        with pytest.raises(pytest.fail.Exception) as exc_info:
            _load_ci_workflow()
        assert "CI workflow not found" in str(exc_info.value)
        assert str(missing) in str(exc_info.value)

    def test_unparseable_yaml_fails_loudly(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """A file that doesn't parse as YAML must `pytest.fail`, not skip."""
        bad = tmp_path / "ci.yml"
        # Tab indentation inside a block is a YAML parser error.
        bad.write_text("jobs:\n\tinvalid: indentation\n")
        monkeypatch.setattr(
            "tests.schema.lint.test_perf_smoke_coverage._CI_WORKFLOW_PATH",
            bad,
        )
        with pytest.raises(pytest.fail.Exception) as exc_info:
            _load_ci_workflow()
        assert "did not parse as YAML" in str(exc_info.value)

    def test_non_dict_root_fails_loudly(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """A workflow whose YAML root is a string/list (not a mapping) must `pytest.fail`."""
        bad = tmp_path / "ci.yml"
        bad.write_text("just a bare string\n")
        monkeypatch.setattr(
            "tests.schema.lint.test_perf_smoke_coverage._CI_WORKFLOW_PATH",
            bad,
        )
        with pytest.raises(pytest.fail.Exception) as exc_info:
            _load_ci_workflow()
        assert "not a mapping" in str(exc_info.value)
        assert "str" in str(exc_info.value)


class TestIterMatrixCellsFailClosedBranches:
    """Pin the ``pytest.fail`` guard inside ``_iter_matrix_cells``."""

    def test_matrix_include_triggers_loud_failure(self) -> None:
        """A matrix with ``include`` must `pytest.fail`, not silently produce wrong cells.

        ``matrix.include`` adds extra cells beyond the cartesian product;
        treating it as a normal axis would produce an incorrect cell list
        and could mask a missing predicate-matching cell.
        """
        workflow = {
            "jobs": {
                "test": {
                    "runs-on": "ubuntu-latest",
                    "strategy": {
                        "matrix": {
                            "python": ["3.10", "3.12"],
                            "include": [{"python": "3.13", "experimental": True}],
                        },
                    },
                },
            },
        }
        with pytest.raises(pytest.fail.Exception) as exc_info:
            _iter_matrix_cells(workflow)
        assert "matrix include/exclude extensions" in str(exc_info.value)
        assert "'test'" in str(exc_info.value)

    def test_matrix_exclude_triggers_loud_failure(self) -> None:
        """A matrix with ``exclude`` must `pytest.fail`, not silently invert fail-closed posture.

        The directional risk: a ``matrix.exclude`` that drops the perf-
        smoke's predicate-matching cell would still appear in the naive
        cartesian product. The guard forces the meta-test to be updated
        before this can land silently.
        """
        workflow = {
            "jobs": {
                "test": {
                    "runs-on": "ubuntu-latest",
                    "strategy": {
                        "matrix": {
                            "python": ["3.10", "3.12"],
                            "exclude": [{"python": "3.12"}],
                        },
                    },
                },
            },
        }
        with pytest.raises(pytest.fail.Exception) as exc_info:
            _iter_matrix_cells(workflow)
        assert "matrix include/exclude extensions" in str(exc_info.value)

    def test_predicate_matches_ubuntu_py312(self) -> None:
        """Positive predicate check: ubuntu* + py3.12 matches."""
        assert _cell_matches_predicate({"runs_on": "ubuntu-latest", "python": "3.12"})
        assert _cell_matches_predicate({"runs_on": "ubuntu-22.04", "python": "3.12"})

    def test_predicate_rejects_non_matching_cells(self) -> None:
        """Negative predicate checks: macos / py3.10 / py3.11 all reject."""
        assert not _cell_matches_predicate({"runs_on": "macos-latest", "python": "3.12"})
        assert not _cell_matches_predicate({"runs_on": "ubuntu-latest", "python": "3.10"})
        assert not _cell_matches_predicate({"runs_on": "ubuntu-latest", "python": "3.11"})
        assert not _cell_matches_predicate({})
