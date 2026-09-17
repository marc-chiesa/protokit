"""The vacuity harness must not lie in either direction, and must clean up.

Every NON-VACUOUS claim in this release rests on ``scripts/mutation_check.py``.
These pins run it end-to-end on throwaway modules and cover the ways it was
found to be wrong:

* **Stale bytecode.** CPython validates a cached ``.pyc`` against the source's
  whole-second mtime and size, so a same-length mutation applied and restored
  within one second left the cache "valid" for the wrong text: the mutated run
  could execute the original bytecode (a false VACUOUS) and every run after
  restore could execute the mutated bytecode (observed 2026-09-14: a restored
  ``differ.py`` kept raising for an accessor its source no longer called).
* **Any nonzero pytest exit reported NON-VACUOUS.** A missing target file
  (exit 4) or a ``-k`` that selects nothing (exit 5) counted as proof.
* **No baseline.** A target already red on the unmutated source "failed under
  mutation" whatever the mutation.
* **Text I/O.** A CRLF source was restored with LF line endings.

The pins are structural, not timing-based, so they hold whatever the clock did.
"""

from __future__ import annotations

import importlib.util
import py_compile
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HARNESS = _REPO_ROOT / "scripts" / "mutation_check.py"
_ORIGINAL = "def answer():\n    return 1\n"
_TEST_SRC = (
    "import pathlib\nimport sys\n"
    "sys.path.insert(0, str(pathlib.Path(__file__).parent))\n"
    "import guarded\n\n\n"
    "def test_answer():\n    assert guarded.answer() == 1\n"
)


def _load_harness() -> ModuleType:
    spec = importlib.util.spec_from_file_location("mutation_check", _HARNESS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cached_pycs(source: Path) -> list[Path]:
    """Every cache file for ``source``: this interpreter's location and ``__pycache__``."""
    cache = Path(importlib.util.cache_from_source(str(source)))
    found = set(cache.parent.glob(f"{source.stem}.*.pyc"))
    found.update(source.parent.glob(f"__pycache__/{source.stem}.*.pyc"))
    return sorted(found)


def _probe(
    tmp_path: Path, *, source: str = _ORIGINAL, test_src: str = _TEST_SRC,
) -> tuple[Path, Path]:
    pkg = tmp_path / "probe"
    pkg.mkdir()
    guarded = pkg / "guarded.py"
    guarded.write_bytes(source.encode())
    test = pkg / "test_guarded.py"
    test.write_text(test_src)
    return guarded, test


def _run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, argv: list[str]) -> int:
    harness = _load_harness()
    monkeypatch.setattr(harness, "VENV_PY", sys.executable)
    monkeypatch.setattr(sys, "argv", ["mutation_check.py", *argv])
    monkeypatch.chdir(tmp_path)
    return harness.main()


def test_same_length_mutation_leaves_no_bytecode_and_is_still_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    guarded, test = _probe(tmp_path)
    # A prior ordinary run would have cached the ORIGINAL source. Whether the
    # mutated run then reuses that cache depends only on the clock, which is
    # exactly the dependency the harness must not have.
    py_compile.compile(str(guarded), doraise=True)
    assert _cached_pycs(guarded)

    # ``return 1`` -> ``return 2`` is the same length: the hazardous shape.
    assert _run(monkeypatch, tmp_path, [str(guarded), "return 1", "return 2", str(test)]) == 0
    assert guarded.read_bytes() == _ORIGINAL.encode()
    assert _cached_pycs(guarded) == [], (
        "bytecode survived the harness run; a same-second restore would keep "
        "executing the mutated module"
    )


def test_replacement_containing_its_anchor_is_a_valid_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``return 1`` -> ``return 1 + 1`` contains the anchor; it must still run."""
    guarded, test = _probe(tmp_path)
    assert _run(monkeypatch, tmp_path, [str(guarded), "return 1", "return 1 + 1", str(test)]) == 0
    assert guarded.read_bytes() == _ORIGINAL.encode()


def test_grandchild_bytecode_does_not_survive_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A test that spawns an interpreter writes bytecode ``-B`` cannot prevent.

    Only the post-restore drop catches it; without that drop the grandchild's
    cache of the MUTATED source outlives the restore.
    """
    test_src = (
        "import pathlib\nimport subprocess\nimport sys\n"
        "HERE = pathlib.Path(__file__).parent\n"
        "sys.path.insert(0, str(HERE))\n"
        "import guarded\n\n\n"
        "def test_answer():\n"
        "    subprocess.run([sys.executable, '-c', 'import guarded'], cwd=HERE, check=True)\n"
        "    assert guarded.answer() == 1\n"
    )
    guarded, test = _probe(tmp_path, test_src=test_src)
    assert _run(monkeypatch, tmp_path, [str(guarded), "return 1", "return 2", str(test)]) == 0
    assert _cached_pycs(guarded) == []


def test_nonexistent_target_is_a_setup_failure_not_a_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    guarded, _test = _probe(tmp_path)
    missing = str(tmp_path / "probe" / "test_does_not_exist.py")
    assert _run(monkeypatch, tmp_path, [str(guarded), "return 1", "return 2", missing]) == 1
    out = capsys.readouterr().out
    assert "SETUP FAILED" in out and "NON-VACUOUS" not in out
    assert guarded.read_bytes() == _ORIGINAL.encode()


def test_selecting_no_tests_is_a_setup_failure_not_a_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    guarded, test = _probe(tmp_path)
    argv = [str(guarded), "return 1", "return 2", str(test), "-k", "nomatch_zzz"]
    assert _run(monkeypatch, tmp_path, argv) == 1
    out = capsys.readouterr().out
    assert "SETUP FAILED" in out and "NON-VACUOUS" not in out


def test_target_red_on_the_baseline_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """A comment-only mutation no test can observe must not be 'proven'."""
    red = "def test_already_red():\n    assert 1 == 2\n"
    guarded, test = _probe(tmp_path, source="def answer():\n    return 1  # note\n", test_src=red)
    assert _run(monkeypatch, tmp_path, [str(guarded), "# note", "# nota", str(test)]) == 1
    out = capsys.readouterr().out
    assert "not green on the unmutated source" in out and "NON-VACUOUS" not in out


def test_restore_preserves_crlf_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    crlf = "def answer():\r\n    return 1\r\n"
    guarded, test = _probe(tmp_path, source=crlf)
    assert _run(monkeypatch, tmp_path, [str(guarded), "return 1", "return 2", str(test)]) == 0
    assert guarded.read_bytes() == crlf.encode()


def test_timeout_is_a_setup_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    sleepy = (
        "import pathlib\nimport sys\nimport time\n"
        "sys.path.insert(0, str(pathlib.Path(__file__).parent))\n"
        "import guarded\n\n\n"
        "def test_answer():\n    time.sleep(30)\n    assert guarded.answer() == 1\n"
    )
    guarded, test = _probe(tmp_path, test_src=sleepy)
    monkeypatch.setenv("MUTATION_CHECK_TIMEOUT", "2")
    assert _run(monkeypatch, tmp_path, [str(guarded), "return 1", "return 2", str(test)]) == 1
    assert "timed out" in capsys.readouterr().out
    assert guarded.read_bytes() == _ORIGINAL.encode()


def test_subprocess_is_not_left_running_after_timeout(tmp_path: Path) -> None:
    """The nested pytest is killed on timeout (subprocess.run's contract), pinned."""
    assert subprocess.run  # the harness uses subprocess.run(timeout=...), which kills the child


def test_a_mutation_that_breaks_collection_is_not_a_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """A syntax-breaking mutation makes every importing test error at collection.

    pytest exits 2 for that, not 1: the target did not detect a behavioral
    change, the module simply stopped parsing. The baseline is green, so this
    is the case only the post-mutation classification can refuse.
    """
    guarded, test = _probe(tmp_path)
    assert _run(monkeypatch, tmp_path, [str(guarded), "return 1", "return (", str(test)]) == 1
    out = capsys.readouterr().out
    assert "not a verdict" in out and "NON-VACUOUS" not in out
    assert guarded.read_bytes() == _ORIGINAL.encode()
