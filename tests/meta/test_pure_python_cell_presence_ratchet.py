"""Presence ratchet for the pure-Python protobuf CI cell (U2, KTD6 / KTD10).

Three audit defects (V1, V10, the V9 swallow) rely on an exception only the
upb backend raises; under the pure-Python runtime each degrades silently to a
wrong value. The ``test-pure-python`` job in ``.github/workflows/ci.yml`` is
the systemic guard: the full suite under
``PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python``, red on any failure outside
the committed known-failure inventory. A future edit that narrows the run to
one subtree, drops the backend variable, or removes the job would leave the
guard looking present while guarding nothing — the shape this ratchet exists
to catch. ``yaml.safe_load`` in the ``_ci_mypy_paths`` shape
(``tests/meta/test_static_analysis.py``); never ``yaml.load``.

Asserted properties of exactly one job:

* job-level ``env`` sets the backend variable to ``python`` (the axis);
* the job id is ``test-pure-python`` (a matrix added later would rename the
  check context, and the required-checks list names the context);
* a run step invokes ``pytest`` over ``tests/`` with no subpath — a
  ``tests/storage``-scoped cell misses every V34 and most V10 failures;
* a sanity step asserts ``api_implementation.Type()`` is ``python`` so a
  runtime that silently fell back to upb fails the job instead of passing it;
* job-level ``continue-on-error: true`` and the advisory banner, **during the
  advisory phase only** — U23 flips both assertions when the inventory is
  empty and the cell becomes a required check.

KTD3 proof: the injected-violation self-tests below run the same check over a
synthetic workflow with one property removed each and assert the message
names it; there is no ``src`` anchor for ``scripts/mutation_check.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI_YAML = ".github/workflows/ci.yml"

JOB_ID = "test-pure-python"
BACKEND_ENV = "PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"
PYTHON_VERSION = "3.12"
# Shortest uniquely-identifying ASCII run of the advisory banner, on one source
# line (presence-ratchet pattern rule 5). The parity job carries the generic
# "DO NOT add to required-checks" line too, so the pin names this job.
ADVISORY_BANNER = "`test-pure-python` is INTENTIONALLY ADVISORY"
SANITY_FRAGMENT = "api_implementation.Type()"


def load_workflow() -> tuple[dict[str, Any], str]:
    text = (_REPO_ROOT / _CI_YAML).read_text(encoding="utf-8")
    return yaml.safe_load(text), text


def _run_tokens(step: dict[str, Any]) -> list[str]:
    run = step.get("run")
    if not isinstance(run, str):
        return []
    return run.replace("\\\n", " ").split()


def cell_violations(workflow: dict[str, Any], raw_text: str) -> list[str]:
    """Every way the workflow fails to carry the advisory pure-Python cell.

    Each message names the missing property so a red ratchet reads as a
    checklist, not a puzzle. Empty means the cell is present in the shape U2
    landed.
    """
    violations: list[str] = []
    jobs = workflow.get("jobs") or {}
    backend_jobs = {
        job_id: job
        for job_id, job in jobs.items()
        if isinstance(job, dict) and (job.get("env") or {}).get(BACKEND_ENV) == "python"
    }
    if len(backend_jobs) != 1:
        return [
            f"expected exactly one job whose job-level env sets "
            f"{BACKEND_ENV}: python, found {sorted(backend_jobs)}"
        ]
    ((job_id, job),) = backend_jobs.items()
    if job_id != JOB_ID:
        violations.append(f"the pure-Python job id must stay {JOB_ID!r}, found {job_id!r}")

    steps = [s for s in job.get("steps", []) if isinstance(s, dict)]
    versions = [
        str((s.get("with") or {}).get("python-version"))
        for s in steps
        if str(s.get("uses", "")).startswith("actions/setup-python")
    ]
    if PYTHON_VERSION not in versions:
        violations.append(
            f"{job_id} must set up Python {PYTHON_VERSION} (setup-python), found {versions}"
        )

    pytest_steps = [s for s in steps if "pytest" in _run_tokens(s)]
    if not pytest_steps:
        violations.append(f"{job_id} has no run step invoking pytest")
    for step in pytest_steps:
        tokens = _run_tokens(step)
        if not any(t in ("tests", "tests/") for t in tokens) or any(
            t.startswith("tests/") and t != "tests/" for t in tokens
        ):
            violations.append(
                f"{job_id} must run pytest over the full suite (tests/ with no "
                f"subpath); its run step passes {tokens!r}"
            )

    if not any(
        SANITY_FRAGMENT in (s.get("run") or "") and "python" in (s.get("run") or "")
        for s in steps
    ):
        violations.append(
            f"{job_id} has no backend sanity step asserting {SANITY_FRAGMENT} == 'python'"
        )

    if job.get("continue-on-error") is not True:
        violations.append(
            f"{job_id} must carry job-level continue-on-error: true during the "
            f"advisory phase (U23 owns the flip to a required check)"
        )
    if ADVISORY_BANNER not in raw_text:
        violations.append(
            f"{_CI_YAML} no longer carries the advisory banner "
            f"({ADVISORY_BANNER!r}); the DO-NOT-ADD-TO-REQUIRED-CHECKS posture "
            f"was deleted or reworded"
        )
    return violations


class TestPurePythonCellPresenceRatchet:
    def test_ci_workflow_carries_the_advisory_pure_python_cell(self) -> None:
        workflow, text = load_workflow()
        violations = cell_violations(workflow, text)
        assert not violations, (
            f"{_CI_YAML} no longer carries the pure-Python protobuf cell in the "
            f"shape U2 landed (KTD10):\n  " + "\n  ".join(violations)
            + "\nIf you are promoting the cell to a required check, that is U23: "
            "flip the continue-on-error and banner assertions in this ratchet in "
            "the same PR."
        )


# --- injected-violation self-tests (KTD3) --------------------------------------

_SYNTHETIC = f"""\
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: pytest tests/ -v
  {JOB_ID}:
    runs-on: ubuntu-latest
    continue-on-error: true
    env:
      {BACKEND_ENV}: python
    steps:
      - uses: actions/setup-python@v6
        with:
          python-version: "{PYTHON_VERSION}"
      - name: Sanity
        run: |
          python -c "from google.protobuf.internal import api_implementation
          assert {SANITY_FRAGMENT} == 'python'"
      - name: Run test suite
        run: pytest tests/ -q -rfE --tb=short
"""
_SYNTHETIC_BANNER = f"# {ADVISORY_BANNER} until U23 promotes it.\n"


def _violations(yaml_text: str, banner: str = _SYNTHETIC_BANNER) -> list[str]:
    return cell_violations(yaml.safe_load(yaml_text), banner + yaml_text)


class TestPurePythonCellPresenceRatchetSelfCheck:
    def test_synthetic_cell_in_the_landed_shape_passes(self) -> None:
        assert _violations(_SYNTHETIC) == []

    def test_run_step_scoped_to_a_subtree_is_named(self) -> None:
        mutated = _SYNTHETIC.replace("pytest tests/ -q", "pytest tests/storage -q")
        (violation,) = _violations(mutated)
        assert "full suite" in violation and "tests/storage" in violation

    def test_missing_continue_on_error_is_named(self) -> None:
        mutated = _SYNTHETIC.replace("    continue-on-error: true\n", "")
        (violation,) = _violations(mutated)
        assert "continue-on-error" in violation

    def test_missing_backend_env_is_named(self) -> None:
        mutated = _SYNTHETIC.replace(f"      {BACKEND_ENV}: python\n", "")
        (violation,) = _violations(mutated)
        assert BACKEND_ENV in violation and "exactly one job" in violation

    def test_missing_sanity_step_is_named(self) -> None:
        mutated = _SYNTHETIC.replace(SANITY_FRAGMENT, "api_implementation.Kind()")
        (violation,) = _violations(mutated)
        assert "sanity" in violation

    def test_renamed_job_is_named(self) -> None:
        mutated = _SYNTHETIC.replace(f"  {JOB_ID}:", "  pure-python-matrix:")
        (violation,) = _violations(mutated)
        assert JOB_ID in violation and "pure-python-matrix" in violation

    def test_wrong_python_version_is_named(self) -> None:
        mutated = _SYNTHETIC.replace(f'"{PYTHON_VERSION}"', '"3.10"')
        (violation,) = _violations(mutated)
        assert PYTHON_VERSION in violation

    def test_missing_banner_is_named(self) -> None:
        (violation,) = _violations(_SYNTHETIC, banner="")
        assert "banner" in violation
