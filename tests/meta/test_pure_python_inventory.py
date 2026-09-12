"""Tests for the pure-Python known-failure inventory hook (U2, KTD10).

The hook lives in ``tests/_pure_python_inventory.py`` (registered by
``tests/conftest.py``). Its parsing layer is exercised in-process; the
collection-time behaviour — marker application, pin precedence, the stale-entry
error, the version guard and the harvest — needs the pure-Python protobuf
backend, which is chosen at import time, so those scenarios spawn a child
pytest session with ``PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python`` (the
subprocess shape ``tests/meta/test_proto_builder.py`` uses) and load the plugin
by module name with ``-p``. A child that cannot force the backend fails loudly on
its own ``api_implementation`` assertion rather than skipping.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests import _pure_python_inventory as inv

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PLUGIN = "tests._pure_python_inventory"

_PROTOBUF_VERSION = inv._installed_protobuf_version()
_PROTOBUF_MINOR = ".".join(_PROTOBUF_VERSION.split(".")[:2])


# --- parsing layer (in-process) -------------------------------------------------


def _parse(text: str) -> inv.Inventory:
    return inv.parse_inventory(text, "inventory.txt")


class TestParseInventory:
    def test_entries_header_and_comments(self) -> None:
        text = (
            "# a comment\n"
            "\n"
            "protobuf: 5.29.5\n"
            "python: 3.12.11\n"
            "tests/a_test.py::test_x V34 google.protobuf.descriptor.Error\n"
            "tests/a_test.py::test_y[a b] V34,U9-1 AssertionError\n"
            "tests/a_test.py::test_z V10 pytest.fail.Exception\n"
        )
        result = _parse(text)
        assert result.protobuf_version == "5.29.5"
        assert result.python_version == "3.12.11"
        assert [e.nodeid for e in result.entries] == [
            "tests/a_test.py::test_x",
            "tests/a_test.py::test_y[a b]",
            "tests/a_test.py::test_z",
        ]
        assert [e.finding for e in result.entries] == ["V34", "V34,U9-1", "V10"]
        from google.protobuf import descriptor

        assert result.entries[0].raises == (descriptor.Error,)
        assert result.entries[1].raises == (AssertionError,)
        assert result.entries[2].raises == (pytest.fail.Exception,)
        assert result.entries[1].line == 6

    def test_tuple_of_exceptions(self) -> None:
        text = "protobuf: 5.29.5\ntests/a.py::t V34 AssertionError,json.JSONDecodeError\n"
        import json

        (entry,) = _parse(text).entries
        assert entry.raises == (AssertionError, json.JSONDecodeError)

    def test_empty_inventory_needs_no_header(self) -> None:
        result = _parse("# nothing listed yet\n")
        assert result.entries == ()
        assert result.protobuf_version is None

    def test_entries_without_protobuf_header_are_rejected(self) -> None:
        with pytest.raises(inv.InventoryError, match="protobuf:"):
            _parse("tests/a.py::t V34 AssertionError\n")

    @pytest.mark.parametrize(
        ("line", "fragment"),
        [
            ("tests/a.py::t V34", "3 columns"),
            ("tests/a.py::t nope AssertionError", "finding"),
            ("tests/a.py::t UNTRIAGED AssertionError", "finding"),
            ("tests/a.py::t V34 Exception", "catch-all"),
            ("tests/a.py::t V34 BaseException", "catch-all"),
            ("tests/a.py::t V34 KeyError,Exception", "catch-all"),
            ("tests/a.py::t V34 no.such.module.Error", "resolve"),
            ("tests/a.py::t V34 json.dumps", "not an exception class"),
            ("tests/a.py::t V34 os.path", "not an exception class"),
            ("bogus: 1\ntests/a.py::t V34 AssertionError", "header"),
        ],
    )
    def test_malformed_lines_are_rejected_with_line_numbers(
        self, line: str, fragment: str,
    ) -> None:
        text = "protobuf: 5.29.5\n" + line + "\n"
        with pytest.raises(inv.InventoryError) as exc:
            _parse(text)
        assert "inventory.txt:" in str(exc.value)
        assert fragment in str(exc.value)

    def test_duplicate_node_id_is_rejected(self) -> None:
        text = (
            "protobuf: 5.29.5\n"
            "tests/a.py::t V34 AssertionError\n"
            "tests/a.py::t V10 KeyError\n"
        )
        with pytest.raises(inv.InventoryError, match="duplicate"):
            _parse(text)

    def test_header_after_an_entry_is_rejected(self) -> None:
        text = "protobuf: 5.29.5\ntests/a.py::t V34 AssertionError\npython: 3.12\n"
        with pytest.raises(inv.InventoryError, match="header"):
            _parse(text)


class TestExceptionSpelling:
    def test_builtin_round_trip(self) -> None:
        assert inv.spell_exception(AssertionError) == "AssertionError"
        assert inv.resolve_exception("AssertionError") is AssertionError

    @pytest.mark.parametrize(
        ("exc_type", "spelling"),
        [
            (pytest.fail.Exception, "pytest.fail.Exception"),
            (pytest.skip.Exception, "pytest.skip.Exception"),
            (pytest.exit.Exception, "pytest.exit.Exception"),
        ],
    )
    def test_pytest_outcomes_are_spelled_publicly(
        self, exc_type: type[BaseException], spelling: str,
    ) -> None:
        assert inv.spell_exception(exc_type) == spelling
        assert inv.resolve_exception(spelling) is exc_type

    def test_private_pytest_spelling_still_resolves(self) -> None:
        assert inv.resolve_exception("_pytest.outcomes.Failed") is pytest.fail.Exception

    def test_dotted_round_trip(self) -> None:
        from google.protobuf import descriptor

        assert inv.spell_exception(descriptor.Error) == "google.protobuf.descriptor.Error"
        assert inv.resolve_exception("google.protobuf.descriptor.Error") is descriptor.Error


class TestVersionGuard:
    def test_minor_mismatch_names_both_versions(self) -> None:
        msg = inv.version_mismatch("5.27.5", "5.29.3")
        assert msg is not None
        assert "5.27.5" in msg and "5.29.3" in msg

    def test_patch_only_difference_is_accepted(self) -> None:
        assert inv.version_mismatch("5.29.0", "5.29.3") is None

    def test_major_mismatch_is_rejected(self) -> None:
        assert inv.version_mismatch("4.25.3", "5.25.3") is not None


class TestFullSuiteDetection:
    def _config(self, args: list[str], tmp_path: Path, **option: object) -> SimpleNamespace:
        opts: dict[str, object] = {
            "keyword": "", "markexpr": "", "lf": False, "deselect": None,
            "ignore": None, "ignore_glob": None, "stepwise": False, "stepwise_skip": False,
        }
        opts.update(option)
        return SimpleNamespace(
            args=args,
            option=SimpleNamespace(**opts),
            invocation_params=SimpleNamespace(dir=tmp_path),
        )

    def test_tests_root_and_its_ancestors_are_full_runs(self, tmp_path: Path) -> None:
        root = tmp_path / "tests"
        root.mkdir()
        assert inv.is_full_suite_run(self._config(["tests"], tmp_path), root)
        assert inv.is_full_suite_run(self._config(["tests/"], tmp_path), root)
        assert inv.is_full_suite_run(self._config([str(tmp_path)], tmp_path), root)
        assert inv.is_full_suite_run(self._config(["."], tmp_path), root)

    def test_subpaths_node_ids_and_narrowing_options_are_subsets(
        self, tmp_path: Path,
    ) -> None:
        root = tmp_path / "tests"
        (root / "meta").mkdir(parents=True)
        cfg = self._config
        assert not inv.is_full_suite_run(cfg(["tests/meta"], tmp_path), root)
        assert not inv.is_full_suite_run(cfg(["tests/meta/test_x.py::test_a"], tmp_path), root)
        assert not inv.is_full_suite_run(cfg(["tests", "tests/meta"], tmp_path), root)
        assert not inv.is_full_suite_run(cfg(["tests"], tmp_path, keyword="x"), root)
        assert not inv.is_full_suite_run(cfg(["tests"], tmp_path, markexpr="slow"), root)
        assert not inv.is_full_suite_run(cfg(["tests"], tmp_path, lf=True), root)
        assert not inv.is_full_suite_run(cfg(["tests"], tmp_path, deselect=["tests/x"]), root)
        assert not inv.is_full_suite_run(cfg(["tests"], tmp_path, ignore=["tests/meta"]), root)
        assert not inv.is_full_suite_run(cfg(["tests"], tmp_path, ignore_glob=["*meta*"]), root)
        assert not inv.is_full_suite_run(cfg(["tests"], tmp_path, stepwise=True), root)
        assert not inv.is_full_suite_run(cfg(["tests"], tmp_path, stepwise_skip=True), root)


# --- collection-time behaviour (pure-Python child sessions) ------------------


_SCENARIO = '''\
import pytest
from google.protobuf.internal import api_implementation

PURE = api_implementation.Type() == "python"


def test_listed_fails():
    # listed with KeyError -> xfailed under pure-Python, passes under upb
    if PURE:
        raise KeyError("backend-dependent")


def test_listed_passes():
    # listed, but passes -> XPASS(strict) -> the cell goes red
    pass


def test_listed_wrong_type():
    # listed with KeyError but raises ValueError -> raises= mismatch -> red
    if PURE:
        raise ValueError("a different reason")


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="U9-1: pinned defect")
def test_pinned():
    # its own pin expects AssertionError; under pure-Python it dies earlier with
    # KeyError, so the inventory entry (KeyError) must be evaluated first
    if PURE:
        raise KeyError("dies in the fixture before the pinned assertion")
    assert False, "the pinned defect"


def test_unlisted_fails():
    # not listed -> plain failure -> harvested as UNTRIAGED
    if PURE:
        raise RuntimeError("new backend-dependent failure")


def test_unlisted_pass():
    pass


@pytest.fixture
def dies_in_setup():
    if PURE:
        raise LookupError("fixture dies under pure-Python")
    return None


def test_listed_setup_error(dies_in_setup):
    # listed with LookupError: a setup-phase error is absorbed like a call failure
    pass


def test_unlisted_setup_error(dies_in_setup):
    # not listed -> setup error -> harvested with the fixture's exception
    pass


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="U8-9: passes under pure-Python")
def test_own_pin_xpasses():
    # its own strict pin passes under pure-Python: nothing the inventory can absorb
    if not PURE:
        assert False, "the pinned defect"


@pytest.fixture
def dies_in_teardown():
    yield None
    if PURE:
        raise OSError("finalizer dies under pure-Python")


def test_unlisted_teardown_error(dies_in_teardown):
    # not listed -> the finalizer's error is red and harvested with its phase
    pass
'''

_LISTED = (
    "test_scenario.py::test_listed_fails V34 KeyError\n"
    "test_scenario.py::test_listed_passes V34 KeyError\n"
    "test_scenario.py::test_listed_wrong_type V34 KeyError\n"
    "test_scenario.py::test_pinned V34,U9-1 KeyError\n"
    "test_scenario.py::test_listed_setup_error V34 LookupError\n"
)


def _write_scenario(tmp_path: Path, inventory: str) -> Path:
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "test_scenario.py").write_text(_SCENARIO)
    inventory_path = tmp_path / "inventory.txt"
    inventory_path.write_text(inventory)
    return inventory_path


def _run_child(
    tmp_path: Path, inventory_path: Path, *args: str, pure: bool = True,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, PYTHONPATH=str(_REPO_ROOT))
    env.pop("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", None)
    if pure:
        env["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
    return subprocess.run(
        [
            sys.executable, "-m", "pytest", "-p", _PLUGIN, "-p", "no:cacheprovider",
            "-q", "-rA", "--tb=line", f"--pure-python-inventory={inventory_path}", *args,
        ],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120, check=False,
    )


def _outcomes(stdout: str) -> dict[str, str]:
    """``-rA`` short-summary lines -> {test name: outcome word}."""
    outcomes: dict[str, str] = {}
    for line in stdout.splitlines():
        word, _, rest = line.partition(" ")
        if word in {"PASSED", "FAILED", "XFAIL", "XPASS", "ERROR", "SKIPPED"}:
            nodeid = rest.split(" ")[0]
            if "::" in nodeid:
                name = nodeid.split("::", 1)[1]
                # a test that passed and then errored in teardown lists twice
                if outcomes.get(name) != "ERROR":
                    outcomes[name] = word
    return outcomes


@pytest.mark.parametrize("pure", [True, False], ids=["pure-python", "upb"])
def test_inventory_applies_only_under_pure_python(tmp_path: Path, pure: bool) -> None:
    inventory = _write_scenario(tmp_path, f"protobuf: {_PROTOBUF_VERSION}\n{_LISTED}")
    result = _run_child(tmp_path, inventory, pure=pure)
    outcomes = _outcomes(result.stdout)
    if pure:
        assert outcomes == {
            "test_listed_fails": "XFAIL",
            "test_listed_passes": "FAILED",
            "test_listed_wrong_type": "FAILED",
            "test_pinned": "XFAIL",
            "test_unlisted_fails": "FAILED",
            "test_unlisted_pass": "PASSED",
            "test_listed_setup_error": "XFAIL",
            "test_unlisted_setup_error": "ERROR",
            "test_own_pin_xpasses": "FAILED",
            "test_unlisted_teardown_error": "ERROR",
        }, result.stdout
        assert "[XPASS(strict)]" in result.stdout
        assert "pure-Python known failure V34" in result.stdout
    else:
        # the hook is a no-op under upb: every listed test simply runs, and the
        # scenario module raises nothing there, so the pinned tests' own markers
        # govern (their AssertionError -> xfailed) and everything else passes
        assert outcomes == {
            "test_listed_fails": "PASSED",
            "test_listed_passes": "PASSED",
            "test_listed_wrong_type": "PASSED",
            "test_pinned": "XFAIL",
            "test_unlisted_fails": "PASSED",
            "test_unlisted_pass": "PASSED",
            "test_listed_setup_error": "PASSED",
            "test_unlisted_setup_error": "PASSED",
            "test_own_pin_xpasses": "XFAIL",
            "test_unlisted_teardown_error": "PASSED",
        }, result.stdout
        assert "pure-Python known failure" not in result.stdout


def test_stale_entry_is_a_hard_error_on_a_full_run(tmp_path: Path) -> None:
    inventory = _write_scenario(
        tmp_path, f"protobuf: {_PROTOBUF_VERSION}\ntest_scenario.py::test_missing V34 KeyError\n",
    )
    result = _run_child(tmp_path, inventory)
    assert result.returncode == pytest.ExitCode.USAGE_ERROR, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "test_scenario.py::test_missing" in combined
    assert "inventory.txt:2" in combined


def test_stale_entry_is_a_warning_on_a_subset_run(tmp_path: Path) -> None:
    inventory = _write_scenario(
        tmp_path, f"protobuf: {_PROTOBUF_VERSION}\ntest_scenario.py::test_missing V34 KeyError\n",
    )
    result = _run_child(tmp_path, inventory, "test_scenario.py::test_unlisted_pass")
    assert result.returncode == pytest.ExitCode.OK, result.stdout + result.stderr
    assert "test_scenario.py::test_missing" in result.stdout
    assert "PurePythonInventoryWarning" in result.stdout


def test_protobuf_minor_mismatch_refuses_to_apply_naming_both_versions(
    tmp_path: Path,
) -> None:
    inventory = _write_scenario(tmp_path, f"protobuf: 1.0.0\n{_LISTED}")
    result = _run_child(tmp_path, inventory)
    assert result.returncode == pytest.ExitCode.USAGE_ERROR, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "1.0.0" in combined and _PROTOBUF_VERSION in combined
    assert inv.IGNORE_VERSION_OPTION in combined


def test_ignore_version_flag_applies_a_mismatched_inventory(tmp_path: Path) -> None:
    inventory = _write_scenario(tmp_path, f"protobuf: 1.0.0\n{_LISTED}")
    result = _run_child(tmp_path, inventory, inv.IGNORE_VERSION_OPTION)
    assert _outcomes(result.stdout)["test_listed_fails"] == "XFAIL", result.stdout


def test_patch_only_difference_applies_normally(tmp_path: Path) -> None:
    inventory = _write_scenario(tmp_path, f"protobuf: {_PROTOBUF_MINOR}.999\n{_LISTED}")
    result = _run_child(tmp_path, inventory)
    assert _outcomes(result.stdout)["test_listed_fails"] == "XFAIL", result.stdout


def test_empty_inventory_needs_no_header(tmp_path: Path) -> None:
    inventory = _write_scenario(tmp_path, "# nothing listed\n")
    result = _run_child(tmp_path, inventory, "test_scenario.py::test_unlisted_pass")
    assert result.returncode == pytest.ExitCode.OK, result.stdout + result.stderr


def test_malformed_inventory_is_one_usage_error_line(tmp_path: Path) -> None:
    inventory = _write_scenario(
        tmp_path,
        f"protobuf: {_PROTOBUF_VERSION}\ntest_scenario.py::test_listed_fails V34 Exception\n",
    )
    result = _run_child(tmp_path, inventory)
    assert result.returncode == pytest.ExitCode.USAGE_ERROR, result.stdout + result.stderr
    assert "catch-all" in result.stdout + result.stderr


def test_harvest_writes_unlisted_failures_in_inventory_format(tmp_path: Path) -> None:
    inventory = _write_scenario(tmp_path, f"protobuf: {_PROTOBUF_VERSION}\n{_LISTED}")
    harvest = tmp_path / "harvest.txt"
    result = _run_child(tmp_path, inventory, f"{inv.HARVEST_OPTION}={harvest}")
    assert result.returncode == pytest.ExitCode.TESTS_FAILED, result.stdout + result.stderr
    text = harvest.read_text()
    entry_lines = [
        line for line in text.splitlines() if line and not line.startswith("#")
    ]
    assert entry_lines == [
        f"protobuf: {_PROTOBUF_VERSION}",
        f"python: {sys.version.split()[0]}",
        # a raises= mismatch keeps its entry's finding and reports the actual type
        "test_scenario.py::test_listed_wrong_type V34 ValueError",
        # a new failure is untriaged until a human names its finding
        f"test_scenario.py::test_unlisted_fails {inv.UNTRIAGED} RuntimeError",
        # a setup-phase error is harvested with the fixture's exception
        f"test_scenario.py::test_unlisted_setup_error {inv.UNTRIAGED} LookupError",
        # so is a teardown-phase error: pytest's xfail filter applies there too
        f"test_scenario.py::test_unlisted_teardown_error {inv.UNTRIAGED} OSError",
    ]
    assert "# raised during setup, not the test body:" in text
    assert "# raised during teardown, not the test body:" in text
    # the XPASS of a listed test is an entry to delete ...
    assert "# XPASS(strict): test_scenario.py::test_listed_passes -- delete" in text
    # ... while the XPASS of a test's own pin is something the inventory cannot absorb
    assert "XPASS(strict) on a marker of its own: test_scenario.py::test_own_pin_xpasses" in text
    # the harvest round-trips through the parser once its findings are triaged
    triaged = text.replace(inv.UNTRIAGED, "V99")
    parsed = inv.parse_inventory(triaged, "harvest.txt")
    assert [e.raises for e in parsed.entries] == [
        (ValueError,), (RuntimeError,), (LookupError,), (OSError,),
    ]


def test_harvest_is_empty_when_nothing_is_unlisted(tmp_path: Path) -> None:
    inventory = _write_scenario(tmp_path, f"protobuf: {_PROTOBUF_VERSION}\n{_LISTED}")
    harvest = tmp_path / "harvest.txt"
    _run_child(
        tmp_path, inventory, f"{inv.HARVEST_OPTION}={harvest}",
        "test_scenario.py::test_listed_fails", "test_scenario.py::test_unlisted_pass",
    )
    entry_lines = [
        line for line in harvest.read_text().splitlines()
        if line and not line.startswith("#") and not line.startswith(("protobuf:", "python:"))
    ]
    assert entry_lines == []


def test_harvest_names_an_aborted_session_instead_of_claiming_a_clean_run(
    tmp_path: Path,
) -> None:
    inventory = _write_scenario(tmp_path, f"protobuf: 1.0.0\n{_LISTED}")
    harvest = tmp_path / "harvest.txt"
    result = _run_child(tmp_path, inventory, f"{inv.HARVEST_OPTION}={harvest}")
    assert result.returncode == pytest.ExitCode.USAGE_ERROR, result.stdout + result.stderr
    text = harvest.read_text()
    assert "USAGE_ERROR" in text and "did not complete" in text
    assert "no unlisted failures" not in text


def test_harvest_option_writes_nothing_under_upb(tmp_path: Path) -> None:
    # The plugin is a no-op under upb, harvest option included: no file, no
    # write attempt that an unwritable path could turn into an error.
    inventory = _write_scenario(tmp_path, f"protobuf: {_PROTOBUF_VERSION}\n{_LISTED}")
    harvest = tmp_path / "no-such-dir" / "harvest.txt"
    result = _run_child(tmp_path, inventory, f"{inv.HARVEST_OPTION}={harvest}", pure=False)
    assert result.returncode == pytest.ExitCode.OK, result.stdout + result.stderr
    assert not harvest.exists()


def test_stale_entry_is_a_hard_error_even_with_the_inventory_outside_the_root(
    tmp_path: Path,
) -> None:
    _write_scenario(tmp_path, "")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    inventory = elsewhere / "inventory.txt"
    inventory.write_text(
        f"protobuf: {_PROTOBUF_VERSION}\ntest_scenario.py::test_missing V34 KeyError\n"
    )
    result = _run_child(tmp_path, inventory)
    assert result.returncode == pytest.ExitCode.USAGE_ERROR, result.stdout + result.stderr
    assert "test_scenario.py::test_missing" in result.stdout + result.stderr


# --- the committed inventory ---------------------------------------------------


def test_committed_inventory_parses_under_every_backend() -> None:
    """The file is read only under pure-Python; this keeps a malformed commit
    from reaching main through the upb-only required matrix."""
    result = inv.load_inventory(inv.INVENTORY_PATH)
    if result.entries:
        assert result.protobuf_version is not None
        assert result.python_version is not None
