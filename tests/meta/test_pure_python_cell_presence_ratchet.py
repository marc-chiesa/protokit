"""Presence ratchet for the pure-Python protobuf CI cell (U2 / U23, KTD6 / KTD10).

Two audit defects (V1, V10) rely on an exception only the upb backend raises;
under pure-Python each degrades silently to a wrong value (V9, once listed, fails
alike on both). The ``test-pure-python`` job in ``.github/workflows/ci.yml`` is
the systemic guard: the full suite under
``PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python``, red on any failure outside
the committed known-failure inventory. A future edit that narrows the run to
one subtree, drops the backend variable, or removes the job would leave the
guard looking present while guarding nothing — the shape this ratchet exists
to catch. So would a ``continue-on-error`` that let the job report green on a
failure: the job is a required check, and a required check that cannot fail
gates nothing. ``yaml.safe_load`` in the ``_ci_mypy_paths`` shape
(``tests/meta/test_static_analysis.py``); never ``yaml.load``.

Asserted properties of exactly one job:

* job-level ``env`` sets the backend variable to ``python`` (the axis);
* the job id is ``test-pure-python`` (a matrix added later would rename the
  check context, and the required-checks list names the context);
* a run step invokes ``pytest`` over ``tests/`` with no subpath — a
  ``tests/storage``-scoped cell misses every V34 and most V10 failures;
* a sanity step asserts ``api_implementation.Type()`` is ``python`` so a
  runtime that silently fell back to upb fails the job instead of passing it;
* no ``continue-on-error`` at job level or on any step, and the
  required-check banner rather than the advisory one — U2 landed the cell
  advisory (job-level ``continue-on-error: true``, a DO-NOT-ADD-TO-REQUIRED-
  CHECKS banner) while the known-failure inventory was non-empty; U23 emptied
  it, promoted the job to a required check on ``main``, and flipped both
  assertions here. Either coming back would contradict branch protection.

KTD3 proof: the injected-violation self-tests below run the same check over a
synthetic workflow with one property removed each and assert the message
names it; there is no ``src`` anchor for ``scripts/mutation_check.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI_YAML = ".github/workflows/ci.yml"

JOB_ID = "test-pure-python"
BACKEND_ENV = "PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"
PYTHON_VERSION = "3.12"
# Shortest uniquely-identifying ASCII run of the required-check banner, on one
# source line (presence-ratchet pattern rule 5). The parity job carries the
# opposite posture ("DO NOT add to required-checks"), so the pin names this job.
REQUIRED_BANNER = "`test-pure-python` is a REQUIRED CHECK"
# The advisory-phase banner (U2 until U23). Its return would restate a posture
# branch protection no longer has, so the ratchet names it as a violation.
ADVISORY_BANNER = "`test-pure-python` is INTENTIONALLY ADVISORY"
SANITY_FRAGMENT = "api_implementation.Type()"


def load_workflow() -> tuple[dict[str, Any], str]:
    text = (_REPO_ROOT / _CI_YAML).read_text(encoding="utf-8")
    return yaml.safe_load(text), text


def _pytest_commands(step: dict[str, Any]) -> list[list[str]]:
    """The tokenised ``pytest ...`` / ``python -m pytest ...`` commands in a
    step's ``run`` script, one per command line. A line that merely mentions
    pytest in a message is not an invocation.
    """
    run = step.get("run")
    if not isinstance(run, str):
        return []
    commands: list[list[str]] = []
    for line in run.replace("\\\n", " ").splitlines():
        tokens = line.split()
        if tokens[:1] == ["pytest"]:
            commands.append(tokens)
        elif tokens[:3] == ["python", "-m", "pytest"]:
            commands.append(tokens[2:])
    return commands


# Options that narrow collection or disable the xfail machinery; any of them
# on the cell's command turns "the full suite under pure-Python" into
# something else while the step still says ``pytest tests/``.
_NARROWING_PREFIXES = (
    "-k", "-m", "--deselect", "--ignore", "--ignore-glob", "--lf", "--last-failed",
    "--sw", "--stepwise", "--runxfail", "-p", "--co", "--collect-only", "-x",
    "--maxfail", "--pure-python-inventory=", "--pure-python-inventory-ignore-version",
    "--version", "--help", "-h",
)


def _narrows(token: str) -> bool:
    for prefix in _NARROWING_PREFIXES:
        if token == prefix or token.startswith(prefix.rstrip("=") + "="):
            return True
    # attached short forms: -kexpr, -mexpr, -pno:plugin
    return token[:2] in ("-k", "-m", "-p") and len(token) > 2 and not token.startswith("--")


def _asserts_pure_python(script: str) -> bool:
    """A sanity step must *assert* the backend, not merely print it: the
    script reads the backend through ``api_implementation.Type()`` and some
    line asserts it equal to ``'python'``.
    """
    return SANITY_FRAGMENT in script and any(
        "assert" in line and "'python'" in line for line in script.splitlines()
    )


def cell_violations(workflow: dict[str, Any], raw_text: str) -> list[str]:
    """Every way the workflow fails to carry the pure-Python cell as a
    required check.

    Each message names the missing property so a red ratchet reads as a
    checklist, not a puzzle. Empty means the cell is present in the shape U23
    landed (U2's shape, minus the advisory posture).
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

    pytest_steps = [(step, command) for step in steps for command in _pytest_commands(step)]
    if not pytest_steps:
        violations.append(f"{job_id} has no run step invoking pytest")
    for step, tokens in pytest_steps:
        if not any(t in ("tests", "tests/") for t in tokens) or any(
            t.startswith("tests/") and t != "tests/" for t in tokens
        ):
            violations.append(
                f"{job_id} must run pytest over the full suite (tests/ with no "
                f"subpath); its run step passes {tokens!r}"
            )
        narrowing = [t for t in tokens if _narrows(t)]
        if narrowing:
            violations.append(
                f"{job_id}'s pytest command must not narrow or escape the run; it "
                f"passes {narrowing!r}"
            )
        if "if" in step or "working-directory" in step:
            violations.append(
                f"{job_id}'s pytest step must run unconditionally from the checkout "
                f"root (no if:, no working-directory:)"
            )
        if BACKEND_ENV in (step.get("env") or {}):
            violations.append(
                f"{job_id}'s pytest step must not override {BACKEND_ENV} at step level"
            )
    # Every step, not only the pytest one: a tolerated sanity-step failure
    # would let a silent upb fallback pass the suite with the inventory hook
    # inert, and the ratchet cannot tell which step really runs the tests
    # once the command is spelled unusually.
    for step in steps:
        if "continue-on-error" in step:
            label = step.get("name") or step.get("uses") or "<unnamed>"
            violations.append(
                f"{job_id}'s step {label!r} must not carry step-level "
                f"continue-on-error; a required check whose steps cannot fail gates "
                f"nothing"
            )

    if not any(_asserts_pure_python(s.get("run") or "") for s in steps):
        violations.append(
            f"{job_id} has no backend sanity step asserting {SANITY_FRAGMENT} == 'python'"
        )

    if "continue-on-error" in job:
        violations.append(
            f"{job_id} must not carry job-level continue-on-error (found "
            f"{job['continue-on-error']!r}); it is a required check since U23, "
            f"and a job that cannot fail gates nothing"
        )
    if REQUIRED_BANNER not in raw_text:
        violations.append(
            f"{_CI_YAML} no longer carries the required-check banner "
            f"({REQUIRED_BANNER!r}); the posture comment was deleted or reworded"
        )
    if ADVISORY_BANNER in raw_text:
        violations.append(
            f"{_CI_YAML} carries the advisory-phase banner ({ADVISORY_BANNER!r}) "
            f"again; the cell has been a required check since U23"
        )
    return violations


class TestPurePythonCellPresenceRatchet:
    def test_ci_workflow_carries_the_required_pure_python_cell(self) -> None:
        workflow, text = load_workflow()
        violations = cell_violations(workflow, text)
        assert not violations, (
            f"{_CI_YAML} no longer carries the pure-Python protobuf cell in the "
            f"shape U23 landed (KTD10's tighten step):\n  " + "\n  ".join(violations)
            + "\nThe job is a required check in main's branch protection; do not "
            "demote it here without removing it from the required checks and "
            "saying why in the PR."
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
_SYNTHETIC_BANNER = f"# {REQUIRED_BANNER} since U23.\n"
_SYNTHETIC_ADVISORY_BANNER = f"# {ADVISORY_BANNER} until U23 promotes it.\n"


def _violations(yaml_text: str, banner: str = _SYNTHETIC_BANNER) -> list[str]:
    return cell_violations(yaml.safe_load(yaml_text), banner + yaml_text)


class TestPurePythonCellPresenceRatchetSelfCheck:
    def test_synthetic_cell_in_the_landed_shape_passes(self) -> None:
        assert _violations(_SYNTHETIC) == []

    def test_run_step_scoped_to_a_subtree_is_named(self) -> None:
        mutated = _SYNTHETIC.replace("pytest tests/ -q", "pytest tests/storage -q")
        (violation,) = _violations(mutated)
        assert "full suite" in violation and "tests/storage" in violation

    def test_reintroduced_job_level_continue_on_error_is_named(self) -> None:
        # The advisory-phase shape (U2): the job reports green on a failure.
        mutated = _SYNTHETIC.replace(
            f"  {JOB_ID}:\n    runs-on: ubuntu-latest\n",
            f"  {JOB_ID}:\n    runs-on: ubuntu-latest\n    continue-on-error: true\n",
        )
        (violation,) = _violations(mutated)
        assert "job-level continue-on-error" in violation and "True" in violation

    def test_step_level_continue_on_error_on_the_pytest_step_is_named(self) -> None:
        # The job-level key is absent, but the test step itself cannot fail.
        mutated = _SYNTHETIC.replace(
            "      - name: Run test suite\n",
            "      - name: Run test suite\n        continue-on-error: true\n",
        )
        (violation,) = _violations(mutated)
        assert "step-level continue-on-error" in violation and "Run test suite" in violation

    def test_step_level_continue_on_error_on_the_sanity_step_is_named(self) -> None:
        # A tolerated sanity failure is the silent-upb-fallback shape: the
        # suite then runs green on the wrong backend with the hook inert.
        mutated = _SYNTHETIC.replace(
            "      - name: Sanity\n", "      - name: Sanity\n        continue-on-error: true\n",
        )
        (violation,) = _violations(mutated)
        assert "step-level continue-on-error" in violation and "Sanity" in violation

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
        assert "required-check banner" in violation

    def test_returned_advisory_banner_is_named(self) -> None:
        # Both banners present: the required-check pin passes, the stale
        # advisory posture is still a violation of its own.
        (violation,) = _violations(
            _SYNTHETIC, banner=_SYNTHETIC_BANNER + _SYNTHETIC_ADVISORY_BANNER,
        )
        assert "advisory-phase banner" in violation

    def test_job_with_no_pytest_step_is_named(self) -> None:
        mutated = _SYNTHETIC.replace(
            "      - name: Run test suite\n        run: pytest tests/ -q -rfE --tb=short\n", "",
        )
        (violation,) = _violations(mutated)
        assert "no run step invoking pytest" in violation

    def test_run_step_without_a_tests_path_is_named(self) -> None:
        # ``pytest -q`` with no path collects from the working directory: the
        # ratchet cannot tell what that covers, so the full-suite property fails.
        mutated = _SYNTHETIC.replace("pytest tests/ -q -rfE", "pytest -q -rfE")
        (violation,) = _violations(mutated)
        assert "full suite" in violation

    def test_a_message_mentioning_pytest_is_not_an_invocation(self) -> None:
        # The harvest step's own wording names pytest; only a command that
        # starts with pytest (or python -m pytest) is checked for the suite path.
        mutated = _SYNTHETIC + (
            "      - name: Harvest\n"
            "        run: |\n"
            "          echo \"pytest did not reach session finish\"\n"
        )
        assert _violations(mutated) == []

    def test_python_dash_m_pytest_is_an_invocation(self) -> None:
        mutated = _SYNTHETIC.replace(
            "run: pytest tests/ -q", "run: python -m pytest tests/storage -q",
        )
        (violation,) = _violations(mutated)
        assert "full suite" in violation and "tests/storage" in violation

    @pytest.mark.parametrize(
        "flag",
        ["-k test_x", "-m slow", "--deselect tests/x.py::t", "--ignore=tests/schema",
         "--lf", "--sw", "--runxfail", "-p no:tests._pure_python_inventory", "-x",
         "--pure-python-inventory=/tmp/other.txt", "--pure-python-inventory-ignore-version",
         "--version", "--help", "-h"],
    )
    def test_a_narrowing_or_escaping_option_is_named(self, flag: str) -> None:
        mutated = _SYNTHETIC.replace("pytest tests/ -q", f"pytest tests/ -q {flag}")
        violations = _violations(mutated)
        assert any("narrow or escape" in v for v in violations), violations

    def test_the_landed_flags_do_not_count_as_narrowing(self) -> None:
        mutated = _SYNTHETIC.replace(
            "pytest tests/ -q -rfE --tb=short",
            "pytest tests/ -q -rfE --tb=short --pure-python-inventory-harvest=h.txt",
        )
        assert _violations(mutated) == []

    def test_a_conditioned_or_relocated_pytest_step_is_named(self) -> None:
        for extra in ("        if: 'false'\n", "        working-directory: tests/core\n"):
            mutated = _SYNTHETIC.replace(
                "      - name: Run test suite\n", "      - name: Run test suite\n" + extra,
            )
            (violation,) = _violations(mutated)
            assert "unconditionally" in violation

    def test_a_step_level_backend_override_is_named(self) -> None:
        mutated = _SYNTHETIC.replace(
            "      - name: Run test suite\n",
            f"      - name: Run test suite\n        env:\n          {BACKEND_ENV}: upb\n",
        )
        (violation,) = _violations(mutated)
        assert "step level" in violation

    def test_a_sanity_step_that_only_prints_is_named(self) -> None:
        mutated = _SYNTHETIC.replace(
            f"assert {SANITY_FRAGMENT} == 'python'", f"print({SANITY_FRAGMENT})",
        )
        (violation,) = _violations(mutated)
        assert "sanity" in violation

    def test_a_second_backend_job_is_named(self) -> None:
        # A renamed copy of the cell's job body: two jobs now set the backend
        # variable at job level, so the "exactly one" property names both.
        cell_body = _SYNTHETIC.split(f"  {JOB_ID}:\n", 1)[1]
        mutated = _SYNTHETIC + "  test-pure-python-matrix:\n" + cell_body
        (violation,) = _violations(mutated)
        assert "exactly one job" in violation
        assert JOB_ID in violation and "test-pure-python-matrix" in violation
