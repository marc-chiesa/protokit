"""The pure-Python known-failure inventory hook (0.16.0 U2, KTD10).

``tests/pure_python_expected_failures.txt`` lists the tests that fail under the
pure-Python protobuf runtime (``PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python``)
because of an audit finding a later unit owns. Under that backend — and only
there — this plugin prepends a strict ``xfail`` marker naming the entry's
exception to every listed test, so the ``test-pure-python`` CI cell is red only
on a *new* failure, on an XPASS (a fix landed: delete the entry), on a failure
that changed shape (the ``raises=`` no longer matches), or on a stale entry.
Under upb the file is not even read.

The inventory is data, not source markers, and carries the same discipline
``tests/meta/test_xfail_raises_ratchet.py`` enforces on markers: every entry
names a specific exception, never ``Exception`` / ``BaseException``. Format,
one entry per line, whitespace-separated, node id first::

    protobuf: 5.29.5          # header: the protobuf the entries were measured on
    python: 3.12.11           # header: recorded, not checked
    tests/x_test.py::test_a V34 google.protobuf.descriptor.Error
    tests/x_test.py::test_b V34,U9-1 AssertionError
    tests/x_test.py::test_c V10 AssertionError,json.JSONDecodeError

The finding column cites the audit finding (``V<n>``) and, on a test that
carries its own U1 pin, that pin's id; the exception column is a dotted class
path, comma-joined when one test surfaces more than one type. The ``protobuf:``
header is mandatory once the file has entries: the hook refuses to apply an
inventory measured on a different protobuf ``major.minor`` (one loud
``pytest.UsageError`` naming both versions rather than ~170 raw failures), so a
runtime bump forces a re-harvest instead of a mis-diagnosed XPASS. A patch bump
does not trip it; ``--pure-python-inventory-ignore-version`` is the local-triage
opt-out for a venv that does not match the header, and a run under that flag is
exploratory, never the verification of record.

Entries are harvested from the cell's own run, not from a local measurement:
``--pure-python-inventory-harvest=PATH`` writes every unlisted failure in this
format with its exact exception type (the short test summary strips the type
from rewritten ``assert`` failures) and a placeholder finding column, so the
only manual step is naming the finding.

This module is a plugin rather than the conftest body so its own tests
(``tests/meta/test_pure_python_inventory.py``) can load it into a child session
by name; ``tests/conftest.py`` registers it for the suite.
"""

from __future__ import annotations

import builtins
import contextlib
import importlib
import re
import sys
import warnings
from collections.abc import Generator, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from google.protobuf.internal import api_implementation


def _installed_protobuf_version() -> str:
    from google.protobuf import __version__

    return str(__version__)


_PROTOBUF_VERSION = _installed_protobuf_version()

INVENTORY_PATH = Path(__file__).with_name("pure_python_expected_failures.txt")
INVENTORY_OPTION = "--pure-python-inventory"
IGNORE_VERSION_OPTION = "--pure-python-inventory-ignore-version"
HARVEST_OPTION = "--pure-python-inventory-harvest"
UNTRIAGED = "UNTRIAGED"

_HEADER_KEYS = ("protobuf", "python")
# ``key: value`` with an identifier key; a node id never matches (its first
# non-word character is a ``/`` or ``.`` before the ``::``).
_HEADER_RE = re.compile(r"^(\w+):\s*(.*)$")
_FINDING_RE = re.compile(r"^V\d+(,U\d+[a-z]?-\d+)*$")
_CATCH_ALL = (Exception, BaseException)
# Public spellings for pytest's own outcome exceptions, so an entry never names
# a ``_pytest`` private path.
_PUBLIC_SPELLINGS: dict[type[BaseException], str] = {
    pytest.fail.Exception: "pytest.fail.Exception",
    pytest.skip.Exception: "pytest.skip.Exception",
    pytest.exit.Exception: "pytest.exit.Exception",
}


class InventoryError(ValueError):
    """A malformed inventory; the message carries ``path:line``."""


class PurePythonInventoryWarning(pytest.PytestWarning):
    """A subset run could not check every inventory entry against collection."""


@dataclass(frozen=True)
class Entry:
    nodeid: str
    finding: str
    raises_spelling: str
    raises: tuple[type[BaseException], ...]
    line: int


@dataclass(frozen=True)
class Inventory:
    path: str
    protobuf_version: str | None
    python_version: str | None
    entries: tuple[Entry, ...]

    def __post_init__(self) -> None:
        if self.entries and self.protobuf_version is None:
            raise InventoryError(
                f"{self.path}: entries need a 'protobuf:' header naming the protobuf "
                f"version they were measured against (installed: {_PROTOBUF_VERSION})"
            )


def runtime_backend() -> str:
    """``python`` for the pure-Python runtime, ``upb`` (or ``cpp``) otherwise."""
    return str(api_implementation.Type())


def skip_under_pure_python(reason: str) -> pytest.MarkDecorator:
    """A ``skipif`` for a test whose premise is a upb runtime fact, not a
    protokit defect (KTD10's permanent backend skips). The reason must name
    the premise; the marker is the single spelling of the backend predicate.
    """
    return pytest.mark.skipif(runtime_backend() == "python", reason=reason)


# --- exception spellings ---------------------------------------------------------


def spell_exception(exc_type: type[BaseException]) -> str:
    if exc_type in _PUBLIC_SPELLINGS:
        return _PUBLIC_SPELLINGS[exc_type]
    if exc_type.__module__ == "builtins":
        return exc_type.__qualname__
    return f"{exc_type.__module__}.{exc_type.__qualname__}"


def resolve_exception(spelling: str) -> type[BaseException]:
    """The exception class a dotted spelling names; specific, never catch-all."""
    parts = spelling.split(".")
    if not all(p.isidentifier() for p in parts):
        raise InventoryError(f"cannot resolve {spelling!r}: not a dotted class path")
    obj: object = None
    if len(parts) == 1:
        obj = getattr(builtins, parts[0], None)
    else:
        for split in range(len(parts) - 1, 0, -1):
            try:
                obj = importlib.import_module(".".join(parts[:split]))
            except ImportError:
                continue
            for attr in parts[split:]:
                obj = getattr(obj, attr, None)
                if obj is None:
                    break
            break
    if obj is None:
        raise InventoryError(f"cannot resolve {spelling!r} to an importable class")
    if not (isinstance(obj, type) and issubclass(obj, BaseException)):
        raise InventoryError(f"{spelling!r} is not an exception class")
    if obj in _CATCH_ALL:
        raise InventoryError(
            f"{spelling!r} is a catch-all raises=; name the specific exception the "
            f"finding raises (the same rule tests/meta/test_xfail_raises_ratchet.py "
            f"applies to source markers)"
        )
    return obj


# --- parsing ---------------------------------------------------------------------


def _parse_lines(text: str, path: str) -> Iterator[tuple[int, str]]:
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if line and not line.startswith("#"):
            yield number, line


def parse_inventory(text: str, path: str) -> Inventory:
    header: dict[str, str] = {}
    entries: list[Entry] = []
    seen: dict[str, int] = {}
    for number, line in _parse_lines(text, path):
        where = f"{path}:{number}"
        header_match = _HEADER_RE.match(line)
        if header_match:
            key, value = header_match.groups()
            if key not in _HEADER_KEYS:
                raise InventoryError(
                    f"{where}: unknown header key {key!r}; the header keys are "
                    f"{', '.join(_HEADER_KEYS)}"
                )
            if entries:
                raise InventoryError(f"{where}: header line {key!r} after the first entry")
            header[key] = value.strip()
            continue
        columns = line.rsplit(None, 2)
        if len(columns) != 3:
            raise InventoryError(
                f"{where}: expected 3 columns '<node id> <finding> <exception>', got {line!r}"
            )
        nodeid, finding, spelling = columns
        if "::" not in nodeid:
            raise InventoryError(f"{where}: {nodeid!r} is not a pytest node id")
        if not _FINDING_RE.match(finding):
            raise InventoryError(
                f"{where}: finding {finding!r} must be an audit finding id such as V34, "
                f"optionally followed by pin ids such as V34,U9-1"
            )
        try:
            raises = tuple(resolve_exception(s) for s in spelling.split(","))
        except InventoryError as exc:
            raise InventoryError(f"{where}: {exc}") from None
        if nodeid in seen:
            raise InventoryError(
                f"{where}: duplicate node id {nodeid!r} (first listed at line {seen[nodeid]})"
            )
        seen[nodeid] = number
        entries.append(Entry(nodeid, finding, spelling, raises, number))
    return Inventory(
        path=path,
        protobuf_version=header.get("protobuf"),
        python_version=header.get("python"),
        entries=tuple(entries),
    )


def load_inventory(path: Path) -> Inventory:
    label = str(path)
    with contextlib.suppress(ValueError):
        label = str(path.relative_to(Path.cwd()))
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise InventoryError(f"{label}: inventory file not found") from None
    return parse_inventory(text, label)


def version_mismatch(header: str | None, installed: str) -> str | None:
    """A message when the header's protobuf ``major.minor`` differs, else None."""
    if header is None:
        return None
    if header.split(".")[:2] != installed.split(".")[:2]:
        return (
            f"the inventory was measured against protobuf {header} but protobuf "
            f"{installed} is installed (major.minor differ); re-harvest the "
            f"inventory on the new runtime, or pass {IGNORE_VERSION_OPTION} for "
            f"an exploratory local run"
        )
    return None


def is_full_suite_run(config: pytest.Config, tests_root: Path) -> bool:
    """True when the invocation collected everything under ``tests_root``.

    Positional args must each be the tests root or one of its ancestors, with
    no collection narrowing: ``-k`` / ``-m`` / ``--lf`` / ``--sw`` /
    ``--deselect`` / ``--ignore`` / ``--ignore-glob``. Only then is an
    unmatched inventory entry a stale entry rather than a deselected test.
    """
    opt = config.option
    narrowing = (
        opt.keyword,
        opt.markexpr,
        opt.deselect,
        getattr(opt, "ignore", None),
        getattr(opt, "ignore_glob", None),
        getattr(opt, "lf", False),
        getattr(opt, "stepwise", False),
        getattr(opt, "stepwise_skip", False),
    )
    if any(narrowing):
        return False
    root = tests_root.resolve()
    for arg in config.args:
        path = Path(arg.split("::", 1)[0])
        if not path.is_absolute():
            path = Path(config.invocation_params.dir) / path
        resolved = path.resolve()
        if resolved != root and resolved not in root.parents:
            return False
    return True


# --- pytest hooks -----------------------------------------------------------------

_HARVEST_KEY: pytest.StashKey[list[str]] = pytest.StashKey()
# The inventory entry applied to an item, so the harvest can report a
# raises= mismatch against the entry rather than re-deriving it from the marker.
_APPLIED_KEY: pytest.StashKey[Entry] = pytest.StashKey()


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("pure-python", "pure-Python protobuf known-failure inventory")
    group.addoption(
        INVENTORY_OPTION,
        default=str(INVENTORY_PATH),
        metavar="PATH",
        help="the known-failure inventory to apply under the pure-Python backend "
        "(default: tests/pure_python_expected_failures.txt)",
    )
    group.addoption(
        IGNORE_VERSION_OPTION,
        action="store_true",
        default=False,
        help="apply the inventory even when its protobuf header does not match "
        "the installed runtime; exploratory only, never the verification of record",
    )
    group.addoption(
        HARVEST_OPTION,
        default=None,
        metavar="PATH",
        help="write every failure not absorbed by the inventory to PATH in "
        "inventory format, with its exact exception type",
    )


def _reason(entry: Entry, inventory: Inventory) -> str:
    return (
        f"pure-Python known failure {entry.finding}: listed in {inventory.path}; "
        f"delete the entry once it XPASSes"
    )


def pytest_collection_modifyitems(
    session: pytest.Session, config: pytest.Config, items: list[pytest.Item],
) -> None:
    if runtime_backend() != "python":
        return
    inventory_path = Path(config.getoption(INVENTORY_OPTION))
    try:
        inventory = load_inventory(inventory_path)
    except InventoryError as exc:
        raise pytest.UsageError(f"pure-Python known-failure inventory: {exc}") from None
    if not inventory.entries:
        return
    mismatch = version_mismatch(inventory.protobuf_version, _PROTOBUF_VERSION)
    if mismatch is not None and not config.getoption(IGNORE_VERSION_OPTION):
        raise pytest.UsageError(f"pure-Python known-failure inventory: {mismatch}")

    by_nodeid = {entry.nodeid: entry for entry in inventory.entries}
    for item in items:
        entry = by_nodeid.pop(item.nodeid, None)
        if entry is None:
            continue
        item.stash[_APPLIED_KEY] = entry
        # Prepended, so the entry's exception governs ahead of a marker the test
        # already carries (a U1 pin): pytest evaluates the first xfail marker.
        item.add_marker(
            pytest.mark.xfail(strict=True, raises=entry.raises, reason=_reason(entry, inventory)),
            append=False,
        )
    if not by_nodeid:
        return
    if is_full_suite_run(config, inventory_path.parent):
        raise pytest.UsageError(
            f"pure-Python known-failure inventory: {len(by_nodeid)} listed node id(s) "
            f"were not collected by a full-suite run; the test was renamed or "
            f"removed, so delete or update the entry:\n{_listing(inventory, by_nodeid)}"
        )
    # A subset run cannot tell an out-of-subset entry from a stale one, except
    # where the entry's own module was collected and the id is still missing.
    collected_files = {item.nodeid.split("::", 1)[0] for item in items}
    suspect = {
        nodeid: entry
        for nodeid, entry in by_nodeid.items()
        if nodeid.split("::", 1)[0] in collected_files
    }
    if suspect:
        warnings.warn(
            PurePythonInventoryWarning(
                f"{len(suspect)} inventory entries name tests that were not collected "
                f"from a module this subset run did collect; they may be stale:\n"
                f"{_listing(inventory, suspect)}"
            ),
            stacklevel=1,
        )


def _listing(inventory: Inventory, entries: dict[str, Entry]) -> str:
    return "\n".join(
        f"  {inventory.path}:{entry.line}: {entry.nodeid}" for entry in entries.values()
    )


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None],
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    harvest = item.config.stash.get(_HARVEST_KEY, None)
    # Teardown failures are a fixture finalizer's, not the test's; a red cell
    # from one shows in -rfE, not here.
    if harvest is None or not report.failed or call.when == "teardown":
        return report
    entry = item.stash.get(_APPLIED_KEY, None)
    if call.excinfo is None:
        # The only exception-free failure of a call phase is a strict XPASS.
        if entry is None:
            harvest.append(
                f"# XPASS(strict) on a marker of its own: {item.nodeid} -- the inventory "
                f"cannot absorb an XPASS; gate that pin on the backend or land its fix"
            )
        else:
            harvest.append(f"# XPASS(strict): {item.nodeid} -- delete its inventory entry")
        return report
    spelling = spell_exception(call.excinfo.type)
    if entry is None:
        harvest.append(f"{item.nodeid} {UNTRIAGED} {spelling}")
    else:
        harvest.append(f"# raises= mismatch: the entry names {entry.raises_spelling}")
        harvest.append(f"{item.nodeid} {entry.finding} {spelling}")
    return report


def pytest_configure(config: pytest.Config) -> None:
    if config.getoption(HARVEST_OPTION) and runtime_backend() == "python":
        config.stash[_HARVEST_KEY] = []


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    target = session.config.getoption(HARVEST_OPTION)
    if not target:
        return
    harvest = session.config.stash.get(_HARVEST_KEY, None)
    lines = [
        "# pure-Python known-failure harvest (tests/_pure_python_inventory.py).",
        f"# Name each {UNTRIAGED} finding (V<n>, plus the U<n>-<m> pin id where the test",
        "# carries one) and add the line to tests/pure_python_expected_failures.txt.",
    ]
    if harvest is None:
        lines.append(f"# backend is {runtime_backend()}, not python: nothing harvested")
    elif exitstatus not in (pytest.ExitCode.OK, pytest.ExitCode.TESTS_FAILED):
        # A usage error (stale entry, version mismatch) or an interrupted run
        # harvested nothing meaningful; say so rather than "no unlisted failures".
        lines.append(
            f"# session ended with {pytest.ExitCode(exitstatus).name}: the run did not "
            f"complete, so nothing was harvested; see the job log"
        )
    else:
        lines += [
            f"protobuf: {_PROTOBUF_VERSION}",
            f"python: {sys.version.split()[0]}",
            *(harvest or ["# no unlisted failures"]),
        ]
    Path(target).write_text("\n".join(lines) + "\n", encoding="utf-8")
