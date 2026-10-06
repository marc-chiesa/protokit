"""Presence ratchet for the minimal-install CI cell (U11, R11 / KTD11).

R22-C1: on Python 3.10, every ``protokit`` subcommand crashed, ``--help``
included. ``formatters/_builtin_lint.py`` imports ``typing_extensions`` there,
the CLI loads that module on every invocation, and nothing declared the
package. CI's own 3.10 cells never saw it: ``[dev]`` pulls mypy, mypy pulls
``typing_extensions``, and every CI job that installed protokit installed
``[dev]``. A job that installs more than a user does cannot catch a missing
runtime dependency.

The ``test-minimal-install`` job in ``.github/workflows/ci.yml`` is the guard:
the declared Python floor, a non-editable ``pip install .`` with no extras,
then ``--help`` on every command in the click tree. This ratchet keeps that
shape, because each way of breaking it leaves a job that still looks present
and still passes. ``yaml.safe_load`` in the ``_ci_mypy_paths`` shape
(``tests/meta/test_static_analysis.py``); never ``yaml.load``.

Asserted properties of the job:

* it exists under the id ``test-minimal-install`` with no ``strategy``: a
  matrix renames the check context, and ``matrix.include``/``exclude`` trips
  ``tests/schema/lint/test_perf_smoke_coverage.py``;
* it sets up exactly one Python, the floor read from ``requires-python`` in
  ``pyproject.toml``, so a raised floor that leaves the cell behind fails here;
* it runs exactly one ``pip install``, and that install is ``pip install .``:
  no extras, no ``-e``, and no second install that could supply what the
  declaration should;
* a step before the install asserts the interpreter holds nothing beyond
  pip, setuptools and wheel, so a runner image that happens to ship an
  undeclared dependency cannot make the smoke pass vacuously;
* a step after the install walks ``protokit.cli.main``'s click tree and runs
  ``protokit <command path> --help`` for every command;
* no job-level ``PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION``: the backend is not
  this cell's axis, and ``tests/meta/test_pure_python_cell_presence_ratchet.py``
  counts the jobs that set it there;
* the sanity and smoke steps are each one ``python -c "..."`` command with
  nothing around it, so no ``exit 0`` or ``|| true`` can skip the check;
* no ``continue-on-error`` on the job or any step, and no ``if:`` or
  ``working-directory:`` on the sanity, install or smoke steps.

KTD3 proof: the injected-violation self-tests below run the same check over a
synthetic workflow with one property broken each and assert the message names
it; there is no ``src`` anchor for ``scripts/mutation_check.py``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI_YAML = ".github/workflows/ci.yml"

JOB_ID = "test-minimal-install"
BACKEND_ENV = "PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"
# The only distributions a fresh setup-python interpreter may carry before the
# install. Anything else could satisfy an import the package never declared.
BARE_FRAGMENTS = ("importlib.metadata", "distributions()", "assert")
# The smoke step imports the real CLI group and recurses through it, so a
# subcommand added later is covered without editing the workflow.
WALK_FRAGMENTS = ("from protokit.cli import main", "list_commands", "'--help'")


def python_floor(pyproject_text: str) -> str:
    """The ``X.Y`` in ``requires-python = ">=X.Y"``; anything else fails loudly."""
    spec = tomllib.loads(pyproject_text)["project"]["requires-python"]
    match = re.fullmatch(r"\s*>=\s*(\d+\.\d+)\s*", spec)
    if match is None:
        pytest.fail(
            f"requires-python is {spec!r}; this ratchet reads the floor from a "
            f"single '>=X.Y' bound. Update python_floor() alongside the change."
        )
    return match.group(1)


def load_inputs() -> tuple[dict[str, Any], str]:
    workflow = yaml.safe_load((_REPO_ROOT / _CI_YAML).read_text(encoding="utf-8"))
    floor = python_floor((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return workflow, floor


def _pip_installs(step: dict[str, Any]) -> list[list[str]]:
    """The arguments after ``pip install`` for each install command in a step's
    ``run`` script, whatever launches pip (``pip``, ``python -m pip``,
    ``uv pip``)."""
    run = step.get("run")
    if not isinstance(run, str):
        return []
    installs: list[list[str]] = []
    for line in run.replace("\\\n", " ").splitlines():
        tokens = line.split()
        for i in range(len(tokens) - 1):
            if tokens[i] in ("pip", "pip3") and tokens[i + 1] == "install":
                installs.append(tokens[i + 2:])
                break
    return installs


def _label(step: dict[str, Any]) -> str:
    return str(step.get("name") or step.get("uses") or "<unnamed>")


def _runs_with(step: dict[str, Any], fragments: tuple[str, ...]) -> bool:
    run = step.get("run")
    return isinstance(run, str) and all(f in run for f in fragments)


def _single_python_c(step: dict[str, Any]) -> bool:
    """The step's ``run`` is one ``python -c "..."`` command and nothing else.

    The body may hold no double quote, so it cannot close the string early
    and run shell after it: no ``exit 0`` ahead of the check, no ``|| true``
    behind it, no ``"; exit 0; "`` inside it. What the Python body itself
    does is beyond a shape check; the ratchet guards drift, not a check
    rewritten to pass.
    """
    run = step.get("run")
    if not isinstance(run, str):
        return False
    lines = run.strip().splitlines()
    if len(lines) < 3 or lines[0].strip() != 'python -c "' or lines[-1].strip() != '"':
        return False
    return '"' not in "\n".join(lines[1:-1])


def cell_violations(workflow: dict[str, Any], floor: str) -> list[str]:
    """Every way the workflow fails to carry the minimal-install cell.

    Each message names the broken property, so a red ratchet reads as a
    checklist. Empty means the cell is present in the shape U11 landed.
    """
    jobs = workflow.get("jobs") or {}
    job = jobs.get(JOB_ID)
    if not isinstance(job, dict):
        return [f"{_CI_YAML} has no {JOB_ID!r} job; R11's minimal-install guard is gone"]

    violations: list[str] = []
    if "strategy" in job:
        violations.append(
            f"{JOB_ID} must not carry a strategy/matrix: a matrix renames the check "
            f"context, and include/exclude trips test_perf_smoke_coverage.py"
        )
    if BACKEND_ENV in (job.get("env") or {}):
        violations.append(
            f"{JOB_ID} must not set {BACKEND_ENV} at job level; the backend is not "
            f"this cell's axis"
        )
    if "continue-on-error" in job:
        violations.append(
            f"{JOB_ID} must not carry job-level continue-on-error (found "
            f"{job['continue-on-error']!r}); a job that cannot fail guards nothing"
        )

    steps = [s for s in job.get("steps", []) if isinstance(s, dict)]
    versions = [
        str((s.get("with") or {}).get("python-version"))
        for s in steps
        if str(s.get("uses", "")).startswith("actions/setup-python")
    ]
    if versions != [floor]:
        violations.append(
            f"{JOB_ID} must set up exactly one Python, the declared floor {floor} "
            f"(quoted, so YAML keeps it a string), found {versions}"
        )

    installs = [(i, args) for i, s in enumerate(steps) for args in _pip_installs(s)]
    if len(installs) != 1:
        violations.append(
            f"{JOB_ID} must run exactly one pip install (the package alone), found "
            f"{[args for _, args in installs]}"
        )
    elif installs[0][1] != ["."]:
        violations.append(
            f"{JOB_ID} must install the package as 'pip install .' (non-editable, no "
            f"extras), found 'pip install {' '.join(installs[0][1])}'"
        )
    install_at = installs[0][0] if len(installs) == 1 else None

    bare = [i for i, s in enumerate(steps) if _runs_with(s, BARE_FRAGMENTS)]
    if not bare:
        violations.append(
            f"{JOB_ID} has no sanity step asserting the interpreter is bare before "
            f"the install (importlib.metadata distributions())"
        )
    elif install_at is not None and not any(i < install_at for i in bare):
        violations.append(f"{JOB_ID}'s bare-interpreter sanity step must run before the install")

    walk = [i for i, s in enumerate(steps) if _runs_with(s, WALK_FRAGMENTS)]
    if not walk:
        violations.append(
            f"{JOB_ID} has no smoke step walking protokit.cli.main and running every "
            f"command's '--help'"
        )
    elif install_at is not None and not any(i > install_at for i in walk):
        violations.append(f"{JOB_ID}'s --help smoke step must run after the install")

    for i in sorted({*bare, *walk}):
        if not _single_python_c(steps[i]):
            violations.append(
                f"{JOB_ID}'s step {_label(steps[i])!r} must be a single python -c "
                f'"..." command, with no shell before, after or inside it'
            )
    gated = sorted({*bare, *walk, *([install_at] if install_at is not None else [])})
    for i in gated:
        if "if" in steps[i] or "working-directory" in steps[i]:
            violations.append(
                f"{JOB_ID}'s step {_label(steps[i])!r} must run unconditionally from "
                f"the checkout root (no if:, no working-directory:)"
            )
    for step in steps:
        if "continue-on-error" in step:
            violations.append(
                f"{JOB_ID}'s step {_label(step)!r} must not carry step-level "
                f"continue-on-error"
            )
    return violations


class TestMinimalInstallCellPresenceRatchet:
    def test_ci_workflow_carries_the_minimal_install_cell(self) -> None:
        workflow, floor = load_inputs()
        violations = cell_violations(workflow, floor)
        assert not violations, (
            f"{_CI_YAML} no longer carries the minimal-install cell in the shape U11 "
            f"landed (R11 / KTD11):\n  " + "\n  ".join(violations)
        )


# --- injected-violation self-tests (KTD3) --------------------------------------

_FLOOR = "3.10"
_SYNTHETIC = f"""\
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: pip install -e ".[dev]"
  {JOB_ID}:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: "{_FLOOR}"
      - name: Sanity
        run: |
          python -c "
          from importlib.metadata import distributions
          extra = {{d.metadata['Name'] for d in distributions()}} - {{'pip'}}
          assert not extra, extra
          "
      - name: Install
        run: pip install .
      - name: Smoke
        run: |
          python -c "
          import click
          from protokit.cli import main
          names = main.list_commands(click.Context(main))
          argv = ['protokit', '--help']
          "
"""


def _violations(yaml_text: str, floor: str = _FLOOR) -> list[str]:
    return cell_violations(yaml.safe_load(yaml_text), floor)


class TestMinimalInstallCellPresenceRatchetSelfCheck:
    def test_synthetic_cell_in_the_landed_shape_passes(self) -> None:
        assert _violations(_SYNTHETIC) == []

    def test_missing_job_is_named(self) -> None:
        (violation,) = _violations(_SYNTHETIC.replace(f"  {JOB_ID}:", "  smoke:"))
        assert JOB_ID in violation and "no" in violation

    @pytest.mark.parametrize(
        "spelling",
        ['".[dev]"', '".[compiler]"', "-e .", "--editable .", "protokit", ". typing_extensions"],
    )
    def test_an_install_other_than_the_bare_package_is_named(self, spelling: str) -> None:
        mutated = _SYNTHETIC.replace("run: pip install .\n", f"run: pip install {spelling}\n")
        (violation,) = _violations(mutated)
        assert "pip install ." in violation and spelling in violation

    def test_a_second_install_is_named(self) -> None:
        # The dev cell's crash was exactly this: something else installed the
        # package the declaration was missing.
        mutated = _SYNTHETIC.replace(
            "run: pip install .\n", "run: |\n          pip install .\n"
            "          python -m pip install typing_extensions\n",
        )
        (violation,) = _violations(mutated)
        assert "exactly one pip install" in violation and "typing_extensions" in violation

    def test_no_install_is_named(self) -> None:
        mutated = _SYNTHETIC.replace("run: pip install .\n", "run: echo skipped\n")
        (violation,) = _violations(mutated)
        assert "exactly one pip install" in violation

    @pytest.mark.parametrize("launcher", ["python -m pip", "uv pip", "pip3"])
    def test_every_pip_launcher_counts_as_an_install(self, launcher: str) -> None:
        mutated = _SYNTHETIC.replace("run: pip install .\n", f'run: {launcher} install ".[dev]"\n')
        (violation,) = _violations(mutated)
        assert ".[dev]" in violation

    def test_wrong_python_version_is_named(self) -> None:
        (violation,) = _violations(_SYNTHETIC.replace(f'"{_FLOOR}"', '"3.12"'))
        assert _FLOOR in violation and "3.12" in violation

    def test_unquoted_floor_is_named(self) -> None:
        # Unquoted, YAML reads 3.10 as the float 3.1, so setup-python is asked
        # for Python 3.1, not the floor.
        (violation,) = _violations(_SYNTHETIC.replace(f'"{_FLOOR}"', _FLOOR))
        assert "quoted" in violation and "3.1'" in violation

    def test_missing_python_pin_is_named(self) -> None:
        mutated = _SYNTHETIC.replace(
            "      - uses: actions/setup-python@v6\n        with:\n"
            f'          python-version: "{_FLOOR}"\n',
            "",
        )
        (violation,) = _violations(mutated)
        assert "exactly one Python" in violation

    def test_a_raised_floor_leaves_the_cell_behind(self) -> None:
        (violation,) = _violations(_SYNTHETIC, floor="3.11")
        assert "3.11" in violation and _FLOOR in violation

    def test_missing_help_walk_is_named(self) -> None:
        (violation,) = _violations(_SYNTHETIC.replace("list_commands", "commands"))
        assert "--help" in violation and "walking" in violation

    def test_help_walk_before_the_install_is_named(self) -> None:
        mutated = _SYNTHETIC.replace("run: pip install .\n", "run: echo moved\n") + (
            "      - name: Install late\n        run: pip install .\n"
        )
        violations = _violations(mutated)
        assert any("smoke step must run after the install" in v for v in violations), violations

    def test_missing_bare_sanity_is_named(self) -> None:
        (violation,) = _violations(_SYNTHETIC.replace("distributions()", "files()"))
        assert "bare" in violation

    def test_bare_sanity_after_the_install_is_named(self) -> None:
        mutated = _SYNTHETIC.replace("run: pip install .\n", "run: echo moved\n").replace(
            "      - name: Sanity\n", "      - name: Install early\n        run: pip install .\n"
            "      - name: Sanity\n",
        )
        (violation,) = _violations(mutated)
        assert "before the install" in violation

    def test_matrix_strategy_is_named(self) -> None:
        mutated = _SYNTHETIC.replace(
            f"  {JOB_ID}:\n    runs-on: ubuntu-latest\n",
            f"  {JOB_ID}:\n    runs-on: ubuntu-latest\n    strategy:\n      matrix:\n"
            f'        python: ["3.10"]\n',
        )
        (violation,) = _violations(mutated)
        assert "strategy" in violation

    def test_job_level_backend_env_is_named(self) -> None:
        mutated = _SYNTHETIC.replace(
            f"  {JOB_ID}:\n    runs-on: ubuntu-latest\n",
            f"  {JOB_ID}:\n    runs-on: ubuntu-latest\n    env:\n      {BACKEND_ENV}: upb\n",
        )
        (violation,) = _violations(mutated)
        assert BACKEND_ENV in violation

    def test_job_level_continue_on_error_is_named(self) -> None:
        mutated = _SYNTHETIC.replace(
            f"  {JOB_ID}:\n    runs-on: ubuntu-latest\n",
            f"  {JOB_ID}:\n    runs-on: ubuntu-latest\n    continue-on-error: true\n",
        )
        (violation,) = _violations(mutated)
        assert "job-level continue-on-error" in violation

    @pytest.mark.parametrize("step", ["Sanity", "Install", "Smoke"])
    def test_step_level_continue_on_error_is_named(self, step: str) -> None:
        mutated = _SYNTHETIC.replace(
            f"      - name: {step}\n", f"      - name: {step}\n        continue-on-error: true\n",
        )
        (violation,) = _violations(mutated)
        assert "step-level continue-on-error" in violation and step in violation

    @pytest.mark.parametrize("step", ["Sanity", "Install", "Smoke"])
    @pytest.mark.parametrize("extra", ["if: 'false'", "working-directory: src"])
    def test_a_conditioned_or_relocated_step_is_named(self, step: str, extra: str) -> None:
        mutated = _SYNTHETIC.replace(
            f"      - name: {step}\n", f"      - name: {step}\n        {extra}\n",
        )
        (violation,) = _violations(mutated)
        assert "unconditionally" in violation and step in violation

    # The last line of each python -c body in _SYNTHETIC, closing quote included.
    _BODY_END = {
        "Sanity": "          assert not extra, extra\n          \"\n",
        "Smoke": "          argv = ['protokit', '--help']\n          \"\n",
    }

    @pytest.mark.parametrize("step", ["Sanity", "Smoke"])
    @pytest.mark.parametrize(
        "bypass", ["exit-before", "or-true-after", "exit-after", "quote-inside"],
    )
    def test_shell_around_the_python_check_is_named(self, step: str, bypass: str) -> None:
        # Each edit keeps every fragment the step is recognised by, yet lets
        # the job go green when the check fails or never runs (exit-before is
        # the gpt-6-astra counterexample). Only a step that is one
        # ``python -c "..."`` command and nothing else is accepted.
        head = f"      - name: {step}\n        run: |\n"
        body_end = self._BODY_END[step]
        assert _SYNTHETIC.count(head) == 1 and _SYNTHETIC.count(body_end) == 1
        if bypass == "exit-before":
            mutated = _SYNTHETIC.replace(head, head + "          exit 0\n")
        elif bypass == "quote-inside":
            opener = head + '          python -c "\n'
            mutated = _SYNTHETIC.replace(opener, opener + '          "; exit 0; "\n')
        else:
            tail = " || true" if bypass == "or-true-after" else "; exit 0"
            mutated = _SYNTHETIC.replace(body_end, body_end.rstrip("\n") + tail + "\n")
        violations = _violations(mutated)
        assert any("single python -c" in v and step in v for v in violations), violations

    def test_the_floor_is_read_from_requires_python(self) -> None:
        assert python_floor('[project]\nrequires-python = ">=3.10"\n') == "3.10"
        assert python_floor('[project]\nrequires-python = ">= 3.12 "\n') == "3.12"

    def test_an_unreadable_floor_fails_loudly(self) -> None:
        with pytest.raises(pytest.fail.Exception, match="single '>=X.Y' bound"):
            python_floor('[project]\nrequires-python = ">=3.10,<4"\n')
