"""The vacuity harness must leave no bytecode behind for the file it mutates.

CPython validates a cached ``.pyc`` against the source's whole-second mtime
and size. A mutation whose replacement is the same length as its anchor,
applied and restored within one second, therefore leaves the cache "valid"
for the wrong text in both directions: the mutated run can execute the
original bytecode (a false VACUOUS verdict), and every run after restore can
execute the mutated bytecode until something else touches the file. The
second direction was observed 2026-09-14: after a same-length proof, the
restored ``differ.py`` kept raising from an accessor its source no longer
called, and the suite stayed red until the cache was deleted by hand.

The pin is structural rather than timing-based: after a harness run, no cache
file for the target may exist, whatever the clock did.
"""

from __future__ import annotations

import importlib.util
import py_compile
import sys
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HARNESS = _REPO_ROOT / "scripts" / "mutation_check.py"


def _load_harness() -> ModuleType:
    spec = importlib.util.spec_from_file_location("mutation_check", _HARNESS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_same_length_mutation_leaves_no_bytecode_and_is_still_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    pkg = tmp_path / "probe"
    pkg.mkdir()
    guarded = pkg / "guarded.py"
    original = "def answer():\n    return 1\n"
    guarded.write_text(original)
    (pkg / "test_guarded.py").write_text(
        "import pathlib\nimport sys\n"
        "sys.path.insert(0, str(pathlib.Path(__file__).parent))\n"
        "import guarded\n\n\n"
        "def test_answer():\n    assert guarded.answer() == 1\n"
    )
    # A prior ordinary run would have cached the ORIGINAL source. Whether the
    # mutated run then reuses that cache depends only on the clock, which is
    # exactly the dependency the harness must not have.
    py_compile.compile(str(guarded), doraise=True)
    assert list(pkg.glob("__pycache__/guarded.*.pyc"))

    harness = _load_harness()
    monkeypatch.setattr(harness, "VENV_PY", sys.executable)
    monkeypatch.setattr(
        sys, "argv",
        ["mutation_check.py", str(guarded), "return 1", "return 2", str(pkg / "test_guarded.py")],
    )
    monkeypatch.chdir(tmp_path)

    # ``return 1`` -> ``return 2`` is the same length: the hazardous shape.
    assert harness.main() == 0, "a covered mutation must be reported NON-VACUOUS"
    assert guarded.read_text() == original
    assert not list(pkg.glob("__pycache__/guarded.*.pyc")), (
        "bytecode survived the harness run; a same-second restore would keep "
        "executing the mutated module"
    )
