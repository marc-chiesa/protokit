"""Regression pins for deferred storage audit findings (family V, storage).

Every ``xfail`` in this module pins a LIVE defect that a later release owns.
Each pin is
``@pytest.mark.xfail(strict=True, raises=...)`` on the test function itself,
with a ``reason`` that begins with the finding ID and names the owning unit and
release. The suite stays green while the defect exists and the pin flips to a
hard failure (XPASS under strict mode) the day the mechanism is fixed, so a fix
cannot land silently and no pin can rot into a permanently-red test.

Each pin asserts the correct outcome, and ``raises=`` names the exception that
was observed with ``--runxfail --tb=line`` under both protobuf backends, so a
pin that dies anywhere else is red rather than "expected". A passing control
sits beside every pin and shares its construction: a red control says the
harness broke, a red pin says the defect moved.

Pinned here:

* **V15** — ``project`` prunes the ``MessageToDict`` rendering, and a
  well-known type with a custom JSON mapping (``Timestamp``, ``Duration``,
  ``FieldMask``, the wrappers, ``Any``, ``Struct``, ``Value``) renders as a
  scalar or as user data, never as an object keyed by its descriptor's field
  names. ``compile_fields`` validates the path against the descriptor and
  accepts it, so a selection descending into such a type silently projects
  ``{}`` for a value that is set, or grafts whatever user data happens to sit
  under that key (a ``Struct`` data key named ``fields``, a ``Value`` oneof
  member that is not the active one, the packed message's own JSON under
  ``payload.value``). The owning unit rejects the selection with
  ``FieldSelectionError``; the pins assert that rejection.
  ``tests/storage/test_project.py`` documents today's ``{}`` in
  ``test_descent_into_set_wkt_currently_projects_empty_v15``, which the fix
  must delete.
* **V16** — ``project`` renders the whole record before it prunes, and renders
  it without the record's own descriptor pool, so an ``Any`` the caller never
  selected decides whether the projection survives. Recorded with an unknown
  ``type_url``; the cycle-1 re-audit (R08-C1) showed it is the ordinary case
  under ``--desc`` / ``--proto``: every ``Any`` packing a type from the
  schema's own (isolated) pool raises a raw ``TypeError``. The same missing
  pool breaks selecting the ``Any`` itself and the storage CLI's full-record
  JSON renders (R27-X1), which exit 2 on a record ``--format human`` prints.
* **V32** — library ``to_parquet`` opens the destination path directly and, on
  any failure, unlinks that path unconditionally. A run that fails therefore
  deletes a Parquet file that was there before it started: after a collected
  decode fault (``IncompleteScanError``), and (R24-C1) even when the writer
  never opened the file, because a read-only destination raises
  ``PermissionError`` and the unlink runs anyway. The storage CLI is safe (it
  hands ``to_parquet`` a temp sibling and renames), which the controls use as
  the reference behaviour. These tests need the ``protokit[parquet]`` extra and
  skip without it; every path they write is under ``tmp_path``.
* **C21-X1** (silent form) — V16's missing pool has a quiet twin. When the
  default pool already holds an OLDER version of the type an ``Any`` packs,
  ``project`` renders the packed bytes through that older type and returns its
  field names, with no error. Registering a type in the default pool cannot be
  undone, so the pin and its control each run in a fresh interpreter, and a
  child that does not finish raises ``RuntimeError``, which the pin's
  ``raises=AssertionError`` does not accept. Owner: U11 (0.19.0), V16's owner.
* **C21-C3** — the same render-before-prune order, with no ``Any`` involved:
  an unselected well-known-typed field holding a value ``json_format`` refuses
  to render (a ``FieldMask`` path with an uppercase letter, a ``Duration``
  whose seconds and nanos disagree in sign, a NaN ``Value``, a ``Timestamp``
  past year 9999) aborts the projection with ``SerializeToJsonError`` (a raw
  ``OverflowError`` for the ``Timestamp`` on protobuf 4.25), top level and
  nested. Owner: U11 (0.19.0).
* **V17** — the length-delimited source's body read keeps every short read
  in a list of ``bytes`` and joins them at the end, so a stream that
  returns one byte per ``read`` peaks near 90 times the frame, where the
  module promises O(single record) memory. The pin measures peak traced
  memory with ``tracemalloc`` and allows 8 times the frame: one full read
  peaks near 1 times, and a ``bytearray`` accumulation near 2 times under the
  same one-byte reads, so the threshold is a judgement with room on both
  sides. Owner: U11 (0.19.0).
"""

from __future__ import annotations

import functools
import io
import json
import os
import subprocess
import sys
import tracemalloc
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result
from google.protobuf import (
    any_pb2,
    descriptor_pb2,
    duration_pb2,
    field_mask_pb2,
    struct_pb2,
    timestamp_pb2,
    type_pb2,
    wrappers_pb2,
)
from google.protobuf.json_format import SerializeToJsonError
from google.protobuf.message import Message

import protokit
from protokit.cli import main
from protokit.storage import (
    FieldSelectionError,
    IncompleteScanError,
    compile_fields,
    project,
    to_parquet,
)
from protokit.storage.schema_source import FileDescriptorSetSchema
from protokit.storage.sources import length_delimited
from tests.storage.cli.conftest import DECODE_BAD, a_fds, pq_cmd
from tests.storage.proto_fixtures import delimited, registry_and_class

_F = descriptor_pb2.FieldDescriptorProto
_PKG = "auditvstorage"
_WKT = ".google.protobuf."

# The shared schema. ``int`` is an int32 field; a string is a message type name.
_MESSAGES: dict[str, dict[str, int | str]] = {
    "Inner": {"x": _F.TYPE_INT32},
    "Wrap": {"n": _F.TYPE_INT32, "payload": f"{_WKT}Any"},
    "Ev": {
        "n": _F.TYPE_INT32,
        "payload": f"{_WKT}Any",
        "wrap": f".{_PKG}.Wrap",
        "inner": f".{_PKG}.Inner",
        "ts": f"{_WKT}Timestamp",
        "dur": f"{_WKT}Duration",
        "mask": f"{_WKT}FieldMask",
        "wrapped": f"{_WKT}Int32Value",
        "st": f"{_WKT}Struct",
        "v": f"{_WKT}Value",
    },
}
_WKT_MODULES = (any_pb2, duration_pb2, field_mask_pb2, struct_pb2, timestamp_pb2, wrappers_pb2)


def _descriptor_set() -> descriptor_pb2.FileDescriptorSet:
    """``auditvstorage.{Inner, Wrap, Ev}`` (proto3) plus the well-known files they import.

    The same shape ``--desc`` hands the storage CLI: resolving it builds an
    isolated pool, so ``Inner`` is a type the *schema* knows and the default
    pool does not.
    """
    out = descriptor_pb2.FileDescriptorSet()
    for module in _WKT_MODULES:
        module.DESCRIPTOR.CopyToProto(out.file.add())
    file = out.file.add(name="ev.proto", package=_PKG, syntax="proto3")
    file.dependency.extend(module.DESCRIPTOR.name for module in _WKT_MODULES)
    for message_name, fields in _MESSAGES.items():
        message = file.message_type.add(name=message_name)
        for number, (field_name, kind) in enumerate(fields.items(), start=1):
            field = message.field.add(name=field_name, number=number, label=_F.LABEL_OPTIONAL)
            if isinstance(kind, str):
                field.type, field.type_name = _F.TYPE_MESSAGE, kind
            else:
                field.type = kind
    return out


@functools.cache
def _event_class() -> type[Message]:
    return FileDescriptorSetSchema(_descriptor_set(), f"{_PKG}.Ev").resolve().message_class


def _inner(x: int) -> Message:
    """An ``Inner`` built from the schema's own pool."""
    holder = _event_class()()
    holder.inner.x = x
    return holder.inner


def _select(message: Message, spec: str) -> dict[str, object]:
    """What a ``--fields`` scan does with one record: compile the selection, project the record."""
    return project(message, compile_fields(spec, message.DESCRIPTOR))


# ---------------------------------------------------------------------------
# V15 — a selection descending into a well-known type
# ---------------------------------------------------------------------------


def _wkt_event() -> Message:
    """An ``Ev`` with every well-known-typed field SET, so "absent" is never the right answer."""
    event = _event_class()()
    event.inner.x = 4
    event.ts.seconds = 5
    event.dur.seconds = 3
    event.mask.paths.append("a")
    event.wrapped.value = 9
    event.st.update({"fields": 1.0})  # a Struct data key that shadows Struct's field name
    event.v.struct_value.update({"string_value": "phantom"})  # ... and a Value oneof member's
    event.payload.Pack(duration_pb2.Duration(seconds=1))
    return event


@pytest.mark.xfail(
    strict=True,
    raises=pytest.fail.Exception,
    reason=(
        "V15: compile_fields accepts a path that descends into a well-known type "
        "whose JSON form is a scalar, and project then finds no such key in the "
        "rendering and returns {} for a field that is set. Owner: parent plan U11 "
        "(0.19.0), which rejects the selection with FieldSelectionError."
    ),
)
@pytest.mark.parametrize(
    "spec", ["ts.seconds", "dur.seconds", "mask.paths", "wrapped.value", "payload.type_url"]
)
def test_v15_descent_into_a_set_well_known_type_is_rejected_not_projected_empty(
    spec: str,
) -> None:
    with pytest.raises(FieldSelectionError):
        _select(_wkt_event(), spec)


@pytest.mark.xfail(
    strict=True,
    raises=pytest.fail.Exception,
    reason=(
        "V15: a path into Struct, Value or Any is resolved against the JSON "
        "rendering, where the keys are user data, so project grafts a Struct data "
        "key named 'fields', a Value oneof member that is not the active one, or "
        "the packed message's own JSON as payload.value. Owner: parent plan U11 "
        "(0.19.0), whose reject list must also cover Value (cycle-1 R08-X2)."
    ),
)
@pytest.mark.parametrize("spec", ["st.fields", "v.string_value", "payload.value"])
def test_v15_descent_into_struct_value_or_any_is_rejected_not_grafted_from_user_data(
    spec: str,
) -> None:
    with pytest.raises(FieldSelectionError):
        _select(_wkt_event(), spec)


@pytest.mark.xfail(
    strict=True,
    raises=pytest.fail.Exception,
    reason=(
        "V15: with a well-known type as the root message, every field selection "
        "projects {} (the audit's own reproduction: Timestamp(seconds=5), "
        "'seconds'), because the root renders as a scalar. Owner: parent plan U11 "
        "(0.19.0), which rejects the selection with FieldSelectionError."
    ),
)
@pytest.mark.parametrize(
    ("root", "spec"),
    [
        (timestamp_pb2.Timestamp(seconds=5), "seconds"),
        (wrappers_pb2.Int32Value(value=5), "value"),
    ],
    ids=["Timestamp", "Int32Value"],
)
def test_v15_field_selection_on_a_well_known_root_type_is_rejected_not_projected_empty(
    root: Message, spec: str
) -> None:
    with pytest.raises(FieldSelectionError):
        _select(root, spec)


def test_v15_descent_into_an_ordinary_submessage_projects_the_leaf_control() -> None:
    assert _select(_wkt_event(), "inner.x") == {"inner": {"x": 4}}


def test_v15_selecting_a_whole_well_known_type_renders_its_json_form_control() -> None:
    # Selecting the well-known field itself is legal and stays legal: only a
    # descent *into* it has no faithful answer. The Struct line shows where the
    # 'fields' key the pin above names comes from: it is the user's data.
    event = _wkt_event()
    assert _select(event, "ts") == {"ts": "1970-01-01T00:00:05Z"}
    assert _select(event, "wrapped") == {"wrapped": 9}
    assert _select(event, "st") == {"st": {"fields": 1.0}}


def test_v15_an_undeclared_field_under_a_well_known_type_is_rejected_control() -> None:
    # The typed rejection the pins ask for already exists for a name the
    # descriptor does not declare, on the same record and the same call.
    with pytest.raises(FieldSelectionError):
        _select(_wkt_event(), "ts.bogus")


def test_v15_field_selection_on_an_ordinary_root_type_projects_the_leaf_control() -> None:
    assert _select(_inner(4), "x") == {"x": 4}


# ---------------------------------------------------------------------------
# V16 — an Any the projection cannot render decides whether the record survives
# ---------------------------------------------------------------------------

_NO_SUCH_URL = "type.googleapis.com/no.such.Type"
_INNER_JSON = {"@type": f"type.googleapis.com/{_PKG}.Inner", "x": 1}
_DURATION_JSON = {"@type": "type.googleapis.com/google.protobuf.Duration", "value": "1s"}


def _any_event(packed: Message | None) -> Message:
    """``Ev(n=7)`` whose ``payload`` packs ``packed`` (left unset for ``None``)."""
    event = _event_class()(n=7)
    if packed is not None:
        event.payload.Pack(packed)
    return event


def _option(type_url: str | None) -> type_pb2.Option:
    """The audit's reproduction: ``Option(name="keep")`` with an ``Any`` in ``value``."""
    option = type_pb2.Option(name="keep")
    if type_url is not None:
        option.value.type_url = type_url
    return option


def _nested_event(type_url: str | None) -> Message:
    """``Ev`` whose ``wrap`` holds the selected leaf ``n`` beside an unselected ``Any``."""
    event = _event_class()()
    event.wrap.n = 7
    if type_url is not None:
        event.wrap.payload.type_url = type_url
    return event


@pytest.mark.xfail(
    strict=True,
    raises=TypeError,
    reason=(
        "V16: project renders the whole record with MessageToDict before pruning, "
        "so an UNSELECTED Any with an unknown type_url kills the projection with a "
        "raw TypeError ('Can not find message descriptor by type_url'). Owner: "
        "parent plan U11 (0.19.0)."
    ),
)
def test_v16_unselected_any_with_an_unknown_type_url_does_not_crash_projection() -> None:
    assert _select(_option(_NO_SUCH_URL), "name") == {"name": "keep"}


@pytest.mark.xfail(
    strict=True,
    raises=TypeError,
    reason=(
        "V16: the unselected Any need not be a top-level field: one sitting beside "
        "the selected leaf inside a selected submessage raises the same raw "
        "TypeError, and U11's planned 'clear unselected top-level fields' leaves "
        "it in the rendering. Owner: parent plan U11 (0.19.0)."
    ),
)
def test_v16_unselected_any_beside_a_selected_nested_leaf_does_not_crash_projection() -> None:
    assert _select(_nested_event(_NO_SUCH_URL), "wrap.n") == {"wrap": {"n": 7}}


@pytest.mark.xfail(
    strict=True,
    raises=TypeError,
    reason=(
        "V16: project calls MessageToDict without the record's descriptor pool, so "
        "under an isolated schema pool (--desc / --proto) an unselected Any packing "
        "a type from that same schema raises the raw TypeError: valid data, not "
        "garbage (cycle-1 R08-C1). Owner: parent plan U11 (0.19.0)."
    ),
)
def test_v16_unselected_any_packing_a_schema_own_type_does_not_crash_projection() -> None:
    assert _select(_any_event(_inner(1)), "n") == {"n": 7}


@pytest.mark.xfail(
    strict=True,
    raises=TypeError,
    reason=(
        "V16: selecting the Any itself hits the same pool-less MessageToDict, so "
        "--fields payload cannot render a type the schema declares; clearing "
        "unselected fields does not reach it (cycle-1 R08-C1). Owner: parent plan "
        "U11 (0.19.0)."
    ),
)
def test_v16_selected_any_packing_a_schema_own_type_renders_the_packed_message() -> None:
    assert _select(_any_event(_inner(1)), "payload") == {"payload": _INNER_JSON}


def test_v16_projection_beside_an_unset_any_control() -> None:
    assert _select(_option(None), "name") == {"name": "keep"}
    assert _select(_nested_event(None), "wrap.n") == {"wrap": {"n": 7}}
    assert _select(_any_event(None), "n") == {"n": 7}


def test_v16_projection_of_an_any_the_default_pool_resolves_control() -> None:
    # Same schema, same isolated pool, same two selections as the pins: only the
    # packed type differs, and Duration is one the default pool can resolve.
    event = _any_event(duration_pb2.Duration(seconds=1))
    assert _select(event, "n") == {"n": 7}
    assert _select(event, "payload") == {"payload": _DURATION_JSON}


# The storage CLI's JSON renders of one record: --fields goes through project;
# the last two are the full-record renders in storage/cli.py.
_JSON_RENDERS = pytest.mark.parametrize(
    ("flags", "keys"),
    [
        (("--fields", "n"), ("n",)),
        (("--fields", "payload"), ("payload",)),
        ((), ("n", "payload")),
        (("--explicit-defaults",), ("n", "payload")),
    ],
    ids=["fields-unselected", "fields-selected", "full-record", "explicit-defaults"],
)


def _expected_json(keys: tuple[str, ...], payload: dict[str, object]) -> dict[str, object]:
    full: dict[str, object] = {"n": 7, "payload": payload}
    return {key: full[key] for key in keys}


def _scan(tmp_path: Path, record: Message, *flags: str) -> Result:
    """``protokit storage scan`` over a one-record file of ``Ev``, schema from ``--desc``."""
    desc = tmp_path / "ev.desc"
    desc.write_bytes(_descriptor_set().SerializeToString())
    data = tmp_path / "ev.bin"
    data.write_bytes(delimited(record.SerializeToString()))
    argv = ["storage", "scan", str(data), "--desc", str(desc), "--type", f"{_PKG}.Ev", *flags]
    return CliRunner().invoke(main, argv, catch_exceptions=False)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "V16: `storage scan --format json` exits 2 ('failed to render record 0 as "
        "JSON') on a record whose Any packs a type from the --desc schema, with "
        "--fields (selected or not), plain, and --explicit-defaults alike, while "
        "--format human prints it. The full-record renders are cycle-1 R27-X1: the "
        "same missing descriptor pool, outside project, in the storage CLI's own "
        "MessageToJson call. Owner: parent plan U11 (0.19.0), for both."
    ),
)
@_JSON_RENDERS
def test_v16_cli_json_scan_renders_a_record_whose_any_packs_a_schema_own_type(
    tmp_path: Path, flags: tuple[str, ...], keys: tuple[str, ...]
) -> None:
    result = _scan(tmp_path, _any_event(_inner(1)), "--format", "json", *flags)
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout) == _expected_json(keys, _INNER_JSON)


@_JSON_RENDERS
def test_v16_cli_json_scan_renders_an_any_the_default_pool_resolves_control(
    tmp_path: Path, flags: tuple[str, ...], keys: tuple[str, ...]
) -> None:
    record = _any_event(duration_pb2.Duration(seconds=1))
    result = _scan(tmp_path, record, "--format", "json", *flags)
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout) == _expected_json(keys, _DURATION_JSON)


def test_v16_cli_human_scan_prints_the_schema_own_any_record_control(tmp_path: Path) -> None:
    # The record the pin feeds the JSON renders decodes and prints: the fault is
    # in the JSON render, not in the data or the schema.
    result = _scan(tmp_path, _any_event(_inner(1)), "--format", "human")
    assert result.exit_code == 0, result.stderr
    assert "n: 7" in result.stdout


# ---------------------------------------------------------------------------
# V32 — a failed library to_parquet run deletes the file already at the destination
# ---------------------------------------------------------------------------

_PRIOR_ROWS = {"important_prior_data": [1, 2, 3]}
_NEW_ROWS = {"x": [7]}


@pytest.fixture
def prior_dest(tmp_path: Path) -> Iterator[Path]:
    """A destination, alone in its own directory under ``tmp_path``, already holding a Parquet file.

    Skips without the ``protokit[parquet]`` extra, so the module still collects
    and the V15 / V16 pins still run where ptars or pyarrow is absent.
    """
    pytest.importorskip("ptars")
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    directory = tmp_path / "out"
    directory.mkdir()
    dest = directory / "data.parquet"
    pq.write_table(pa.table(_PRIOR_ROWS), dest)
    yield dest
    if dest.exists():
        dest.chmod(0o644)  # the read-only tests leave it 0400


def _make_read_only(dest: Path) -> None:
    dest.chmod(0o400)
    if sys.platform == "win32" or os.access(dest, os.W_OK):
        pytest.skip("the read-only bit does not deny writes here (Windows, or running as root)")


def _records(*, faulting: bool) -> list[bytes]:
    _registry, cls = registry_and_class()
    good = cls(x=7).SerializeToString()
    return [good, DECODE_BAD] if faulting else [good]


def _to_parquet(dest: Path, *, faulting: bool) -> None:
    """Library ``to_parquet`` of ``a.A`` records straight onto ``dest``."""
    registry, _cls = registry_and_class()
    source = [("s", payload) for payload in _records(faulting=faulting)]
    to_parquet(source, registry, dest, stream_id="s")


def _cli_to_parquet(tmp_path: Path, dest: Path, *, faulting: bool) -> Result:
    """``protokit storage scan --format parquet -o dest`` over the same records."""
    desc = tmp_path / "a.desc"
    desc.write_bytes(a_fds().SerializeToString())
    data = tmp_path / "a.bin"
    data.write_bytes(delimited(*_records(faulting=faulting)))
    return CliRunner().invoke(main, pq_cmd(data, desc, dest), catch_exceptions=False)


def _assert_all_or_nothing(dest: Path, *, run_failed: bool) -> None:
    """A failed run leaves the prior file exactly as it was; a clean one replaces it.

    Either way the destination is the only entry in its directory: no partial
    and no temp sibling is left behind.
    """
    import pyarrow.parquet as pq  # present: the prior_dest fixture skipped otherwise

    assert dest.exists(), "the run deleted the file that was at the destination before it"
    assert pq.read_table(dest).to_pydict() == (_PRIOR_ROWS if run_failed else _NEW_ROWS)
    assert [entry.name for entry in dest.parent.iterdir()] == [dest.name]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "V32: to_parquet opens the destination path itself and, when the scan "
        "collected a fault, raises IncompleteScanError and unlinks that path, so a "
        "failed run deletes the Parquet file that was there before it. Owner: "
        "parent plan U12 (0.19.0), the _atomic publication seam."
    ),
)
def test_v32_to_parquet_failing_on_a_decode_fault_keeps_the_pre_existing_destination(
    prior_dest: Path,
) -> None:
    with pytest.raises(IncompleteScanError):
        _to_parquet(prior_dest, faulting=True)
    _assert_all_or_nothing(prior_dest, run_failed=True)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "V32: onto a read-only destination the writer raises PermissionError "
        "before it opens anything, and to_parquet's unconditional os.unlink then "
        "deletes the file it never wrote (cycle-1 R24-C1). Owner: parent plan U12 "
        "(0.19.0), whose scenarios name only the IncompleteScanError case."
    ),
)
def test_v32_to_parquet_onto_a_read_only_destination_never_deletes_it(prior_dest: Path) -> None:
    _make_read_only(prior_dest)
    run_failed = False
    try:
        _to_parquet(prior_dest, faulting=False)
    except PermissionError:
        run_failed = True
    # Refusing the read-only file and replacing it atomically (what the CLI does,
    # see the control below) are both all-or-nothing. Deleting it is neither.
    _assert_all_or_nothing(prior_dest, run_failed=run_failed)


def test_v32_to_parquet_succeeding_replaces_the_pre_existing_destination_control(
    prior_dest: Path,
) -> None:
    _to_parquet(prior_dest, faulting=False)
    _assert_all_or_nothing(prior_dest, run_failed=False)


def test_v32_cli_parquet_scan_failing_on_a_decode_fault_keeps_the_destination_control(
    tmp_path: Path, prior_dest: Path
) -> None:
    result = _cli_to_parquet(tmp_path, prior_dest, faulting=True)
    assert result.exit_code == 2, result.stderr
    _assert_all_or_nothing(prior_dest, run_failed=True)


@pytest.mark.parametrize("faulting", [False, True], ids=["clean-run", "decode-fault"])
def test_v32_cli_parquet_scan_onto_a_read_only_destination_is_all_or_nothing_control(
    tmp_path: Path, prior_dest: Path, faulting: bool
) -> None:
    _make_read_only(prior_dest)
    result = _cli_to_parquet(tmp_path, prior_dest, faulting=faulting)
    assert result.exit_code == (2 if faulting else 0), result.stderr
    _assert_all_or_nothing(prior_dest, run_failed=faulting)


# ---------------------------------------------------------------------------
# C21-X1 — an older same-named type in the default pool renders the Any silently wrong
# ---------------------------------------------------------------------------

_SRC = Path(protokit.__file__).resolve().parents[1]

# argv: which version of auditc21x1.Payload the default pool holds. Prints one
# JSON object: what `--fields payload` projects from an Envelope built from the
# record's own (isolated) pool, whose Any packs the CURRENT Payload.
_C21_X1_CHILD = r"""
import json
import sys

from google.protobuf import any_pb2, descriptor_pb2, descriptor_pool

from protokit._pools import get_message_class
from protokit.storage import compile_fields, project
from protokit.storage.schema_source import FileDescriptorSetSchema

FD = descriptor_pb2.FieldDescriptorProto


def schema(payload_fields):
    f = descriptor_pb2.FileDescriptorProto(
        name="auditc21x1.proto", package="auditc21x1", syntax="proto3",
        dependency=[any_pb2.DESCRIPTOR.name],
    )
    payload = f.message_type.add(name="Payload")
    for number, name in enumerate(payload_fields, start=1):
        payload.field.add(name=name, number=number, type=FD.TYPE_STRING, label=FD.LABEL_OPTIONAL)
    envelope = f.message_type.add(name="Envelope")
    envelope.field.add(name="n", number=1, type=FD.TYPE_INT32, label=FD.LABEL_OPTIONAL)
    envelope.field.add(
        name="payload", number=2, type=FD.TYPE_MESSAGE, label=FD.LABEL_OPTIONAL,
        type_name=".google.protobuf.Any",
    )
    return f


current = ["new_name", "added"]
in_default_pool = {"older": ["old_name"], "same": current}[sys.argv[1]]

fds = descriptor_pb2.FileDescriptorSet()
any_pb2.DESCRIPTOR.CopyToProto(fds.file.add())
fds.file.add().CopyFrom(schema(current))
resolved = FileDescriptorSetSchema(fds, "auditc21x1.Envelope").resolve()
envelope = resolved.message_class(n=7)
payload_class = get_message_class(resolved.pool, "auditc21x1.Payload")
envelope.payload.Pack(payload_class(new_name="keep", added="also"))

# Something else in the process registered the type in the default pool.
descriptor_pool.Default().AddSerializedFile(schema(in_default_pool).SerializeToString())
print(json.dumps(project(envelope, compile_fields("payload", envelope.DESCRIPTOR))))
"""

_C21_X1_EXPECTED = {
    "payload": {
        "@type": "type.googleapis.com/auditc21x1.Payload",
        "new_name": "keep",
        "added": "also",
    }
}


@functools.cache
def _c21_x1_projection(in_default_pool: str) -> dict[str, Any]:
    """Run the child for one default-pool version and return what it projected."""
    result = subprocess.run(
        [sys.executable, "-c", _C21_X1_CHILD, in_default_pool],
        capture_output=True, text=True, check=False, timeout=300,
        env={**os.environ, "PYTHONPATH": str(_SRC)},
    )
    if result.returncode != 0:
        # Not an assertion: a pin that expects AssertionError must not accept this.
        raise RuntimeError(f"child {in_default_pool!r} did not run:\n{result.stderr}")
    outcome: dict[str, Any] = json.loads(result.stdout.strip().splitlines()[-1])
    return outcome


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "C21-X1: owned by U11 (0.19.0). project calls MessageToDict without the "
        "record's descriptor pool, so the Any is resolved through the default pool; "
        "when that pool holds an older auditc21x1.Payload the packed bytes render "
        "through it, so the projection returns {'old_name': 'keep'} and drops "
        "'added', with no error (the silent form of V16)."
    ),
)
def test_c21_x1_selected_any_renders_from_the_record_pool_not_an_older_default_pool_type() -> None:
    assert _c21_x1_projection("older") == _C21_X1_EXPECTED


def test_c21_x1_selected_any_renders_when_the_default_pool_holds_the_same_type_control() -> None:
    # The same child, the same record, the same selection: only the version of
    # the type the default pool holds differs, and with the record's own
    # version there the projection is right.
    assert _c21_x1_projection("same") == _C21_X1_EXPECTED


# ---------------------------------------------------------------------------
# C21-C3 — an unselected well-known type json_format refuses kills the projection
# ---------------------------------------------------------------------------

_NAN = float("nan")

# field of Ev -> (a value json_format refuses to render, a value it renders).
_REFUSED_AND_RENDERED: dict[str, tuple[Message, Message]] = {
    "mask": (
        field_mask_pb2.FieldMask(paths=["userId"]),
        field_mask_pb2.FieldMask(paths=["user_id"]),
    ),
    "dur": (duration_pb2.Duration(seconds=1, nanos=-1), duration_pb2.Duration(seconds=1, nanos=1)),
    "v": (struct_pb2.Value(number_value=_NAN), struct_pb2.Value(number_value=1.5)),
    "ts": (timestamp_pb2.Timestamp(seconds=10**12), timestamp_pb2.Timestamp(seconds=5)),
}


def _holding(field: str, *, refused: bool) -> Message:
    """``Ev(n=7)`` whose well-known-typed ``field`` holds a value json_format refuses, or not.

    The value goes in as wire bytes: the field's type is the schema pool's copy of
    the well-known type, not the default pool's class the value was built with.
    """
    event = _event_class()(n=7)
    value = _REFUSED_AND_RENDERED[field][0 if refused else 1]
    getattr(event, field).MergeFromString(value.SerializeToString())
    return event


@pytest.mark.xfail(
    strict=True,
    raises=SerializeToJsonError,
    reason=(
        "C21-C3: owned by U11 (0.19.0). project renders the whole record before it "
        "prunes, so an UNSELECTED well-known-typed field holding a value json_format "
        "refuses (a FieldMask path 'userId', a Duration whose seconds and nanos "
        "disagree in sign, a NaN Value) raises SerializeToJsonError out of "
        "--fields n."
    ),
)
@pytest.mark.parametrize("field", ["mask", "dur", "v"])
def test_c21_c3_unselected_unrenderable_well_known_type_does_not_kill_projection(
    field: str,
) -> None:
    assert _select(_holding(field, refused=True), "n") == {"n": 7}


@pytest.mark.xfail(
    strict=True,
    raises=(SerializeToJsonError, OverflowError),
    reason=(
        "C21-C3: owned by U11 (0.19.0). The Timestamp case of the same render: an "
        "UNSELECTED Timestamp past year 9999 raises SerializeToJsonError out of "
        "--fields n on protobuf 5.x, and a raw OverflowError ('date value out of "
        "range') on protobuf 4.25."
    ),
)
def test_c21_c3_unselected_out_of_range_timestamp_does_not_kill_projection() -> None:
    assert _select(_holding("ts", refused=True), "n") == {"n": 7}


@pytest.mark.parametrize("field", ["mask", "dur", "v", "ts"])
def test_c21_c3_unselected_renderable_well_known_type_beside_the_selection_control(
    field: str,
) -> None:
    # The same record and selection as the pins: only the value differs, and
    # json_format renders this one.
    assert _select(_holding(field, refused=False), "n") == {"n": 7}


@functools.cache
def _outer_class() -> type[Message]:
    """``auditc21c3.Outer``: an ``inner`` holding an int ``x`` beside a ``FieldMask`` ``mask``."""
    out = descriptor_pb2.FileDescriptorSet()
    field_mask_pb2.DESCRIPTOR.CopyToProto(out.file.add())
    file = out.file.add(
        name="auditc21c3.proto", package="auditc21c3", syntax="proto3",
        dependency=[field_mask_pb2.DESCRIPTOR.name],
    )
    inner = file.message_type.add(name="Inner")
    inner.field.add(name="x", number=1, type=_F.TYPE_INT32, label=_F.LABEL_OPTIONAL)
    inner.field.add(
        name="mask", number=2, type=_F.TYPE_MESSAGE, label=_F.LABEL_OPTIONAL,
        type_name=f"{_WKT}FieldMask",
    )
    file.message_type.add(name="Outer").field.add(
        name="inner", number=1, type=_F.TYPE_MESSAGE, label=_F.LABEL_OPTIONAL,
        type_name=".auditc21c3.Inner",
    )
    return FileDescriptorSetSchema(out, "auditc21c3.Outer").resolve().message_class


def _outer(mask_path: str) -> Message:
    """``Outer`` whose ``inner`` holds ``x=7`` beside a ``mask`` with one path."""
    outer = _outer_class()()
    outer.inner.x = 7
    outer.inner.mask.paths.append(mask_path)
    return outer


@pytest.mark.xfail(
    strict=True,
    raises=SerializeToJsonError,
    reason=(
        "C21-C3: owned by U11 (0.19.0). The unrenderable field need not be top "
        "level: a FieldMask path 'userId' beside the selected leaf inside a "
        "selected submessage raises the same SerializeToJsonError out of --fields "
        "inner.x, and clearing unselected top-level fields does not reach it (the "
        "nested V16 pin's gap)."
    ),
)
def test_c21_c3_unrenderable_mask_beside_a_selected_nested_leaf_does_not_kill_projection() -> None:
    assert _select(_outer("userId"), "inner.x") == {"inner": {"x": 7}}


def test_c21_c3_renderable_mask_beside_a_selected_nested_leaf_control() -> None:
    assert _select(_outer("user_id"), "inner.x") == {"inner": {"x": 7}}


# ---------------------------------------------------------------------------
# V17 — the length-delimited reader keeps every short read until the frame ends
# ---------------------------------------------------------------------------

_FRAME = 256 * 1024
# Today one-byte reads peak near 90 times the frame and one full read near 1;
# a bytearray accumulation peaks near 2 under one-byte reads. A judgement.
_PEAK_ALLOWED = 8 * _FRAME


class _ShortReads:
    """A blocking stream that never returns more than ``step`` bytes from one ``read``."""

    def __init__(self, data: bytes, step: int) -> None:
        self._data = io.BytesIO(data)
        self._step = step

    def read(self, n: int = -1) -> bytes:
        return self._data.read(self._step if n < 0 else min(n, self._step))

    def close(self) -> None:
        self._data.close()


def _varint(n: int) -> bytes:
    out = bytearray()
    while n > 0x7F:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n)
    return bytes(out)


def _peak_reading_one_frame(step: int) -> int:
    """Peak traced memory while ``length_delimited`` reads one ``_FRAME``-byte frame.

    The stream returns at most ``step`` bytes per read. Measured above what was
    already traced, so a tracer someone else started is left running.
    """
    body = bytes(range(256)) * (_FRAME // 256)
    stream = _ShortReads(_varint(_FRAME) + body, step)
    started_here = not tracemalloc.is_tracing()
    if started_here:
        tracemalloc.start()
    try:
        before, _ = tracemalloc.get_traced_memory()
        tracemalloc.reset_peak()
        frames = list(length_delimited(stream, stream_id="s"))  # type: ignore[arg-type]
        _, peak = tracemalloc.get_traced_memory()
    finally:
        if started_here:
            tracemalloc.stop()
    # The frame really was read whole: a short or wrong body is not a memory answer.
    if frames != [("s", body)]:
        raise RuntimeError(f"length_delimited did not return the one frame: {len(frames)} frame(s)")
    return peak - before


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "V17: owned by U11 (0.19.0). _read_exact appends each short read to a list "
        "of bytes and joins at the end, so a stream returning one byte per read "
        "peaks near 90 times the frame (a list entry per read, and a buffer record "
        "per entry inside join), not the O(single record) the module promises."
    ),
)
def test_v17_one_byte_reads_peak_within_a_small_multiple_of_the_frame() -> None:
    peak = _peak_reading_one_frame(step=1)
    assert peak < _PEAK_ALLOWED, f"peak {peak / _FRAME:.1f} times the frame"


def test_v17_one_full_read_peaks_within_a_small_multiple_of_the_frame_control() -> None:
    # The same frame, the same stream class, the same measurement: only the read
    # size differs.
    peak = _peak_reading_one_frame(step=_FRAME)
    assert peak < _PEAK_ALLOWED, f"peak {peak / _FRAME:.1f} times the frame"
