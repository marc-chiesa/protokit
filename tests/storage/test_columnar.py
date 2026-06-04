"""Columnar / Parquet sink tests (PR3 U4/U5).

Skips cleanly when the ``protokit[parquet]`` extra is absent — the module-top
``importorskip`` guards collection (a ``pytestmark`` would NOT guard the
module-top ptars/pyarrow imports). The extra-absent error path (R9/AE6) is
covered separately in ``test_columnar_extra.py`` (which does not importorskip).
"""

from __future__ import annotations

import pytest

pytest.importorskip("ptars")
pa = pytest.importorskip("pyarrow")
import pyarrow.parquet as pq  # noqa: E402 - after importorskip by design
from google.protobuf import any_pb2, descriptor_pb2, timestamp_pb2  # noqa: E402

from protokit.storage import (  # noqa: E402
    IncompleteScanError,
    SchemaMismatchError,
    to_arrow_batches,
    to_parquet,
)
from protokit.storage.registry import StreamRegistry  # noqa: E402
from protokit.storage.schema_source import FileDescriptorSetSchema  # noqa: E402

F = descriptor_pb2.FieldDescriptorProto


def _build_fds():
    fds = descriptor_pb2.FileDescriptorSet()
    timestamp_pb2.DESCRIPTOR.CopyToProto(fds.file.add())
    any_pb2.DESCRIPTOR.CopyToProto(fds.file.add())

    f = fds.file.add()
    f.name = "ev.proto"
    f.package = "ev"
    f.syntax = "proto3"
    f.dependency.append("google/protobuf/timestamp.proto")
    f.dependency.append("google/protobuf/any.proto")

    color = f.enum_type.add()
    color.name = "Color"
    for n, num in (("UNKNOWN", 0), ("RED", 1)):
        v = color.value.add()
        v.name, v.number = n, num

    meta = f.message_type.add()  # nested message carrying a WKT at depth (AE7)
    meta.name = "Meta"
    mts = meta.field.add()
    mts.name, mts.number, mts.type, mts.label = "ts", 1, F.TYPE_MESSAGE, F.LABEL_OPTIONAL
    mts.type_name = ".google.protobuf.Timestamp"
    mn = meta.field.add()
    mn.name, mn.number, mn.type, mn.label = "n", 2, F.TYPE_INT32, F.LABEL_OPTIONAL

    ev = f.message_type.add()
    ev.name = "Event"
    entry = ev.nested_type.add()
    entry.name = "AttrsEntry"
    entry.options.map_entry = True
    ek = entry.field.add()
    ek.name, ek.number, ek.type, ek.label = "key", 1, F.TYPE_STRING, F.LABEL_OPTIONAL
    evv = entry.field.add()
    evv.name, evv.number, evv.type, evv.label = "value", 2, F.TYPE_INT32, F.LABEL_OPTIONAL
    od = ev.oneof_decl.add()
    od.name = "choice"

    def addf(name, num, t, label=F.LABEL_OPTIONAL, tn=None, oneof=None):
        fl = ev.field.add()
        fl.name, fl.number, fl.type, fl.label = name, num, t, label
        if tn:
            fl.type_name = tn
        if oneof is not None:
            fl.oneof_index = oneof

    addf("id", 1, F.TYPE_INT32)
    addf("name", 2, F.TYPE_STRING)
    addf("payload", 3, F.TYPE_BYTES)
    addf("color", 4, F.TYPE_ENUM, tn=".ev.Color")
    addf("tags", 5, F.TYPE_INT32, label=F.LABEL_REPEATED)
    addf("attrs", 6, F.TYPE_MESSAGE, label=F.LABEL_REPEATED, tn=".ev.Event.AttrsEntry")
    addf("created_at", 7, F.TYPE_MESSAGE, tn=".google.protobuf.Timestamp")
    addf("meta", 8, F.TYPE_MESSAGE, tn=".ev.Meta")
    addf("detail", 9, F.TYPE_MESSAGE, tn=".google.protobuf.Any")
    addf("a", 20, F.TYPE_STRING, oneof=0)
    addf("b", 21, F.TYPE_INT32, oneof=0)

    other = fds.file.add()
    other.name = "ot.proto"
    other.package = "ot"
    other.syntax = "proto3"
    om = other.message_type.add()
    om.name = "Other"
    of = om.field.add()
    of.name, of.number, of.type, of.label = "v", 1, F.TYPE_INT64, F.LABEL_OPTIONAL
    return fds


def _registry():
    fds = _build_fds()
    reg = StreamRegistry()
    reg.register_stream("events", FileDescriptorSetSchema(fds, "ev.Event"))
    reg.register_stream("others", FileDescriptorSetSchema(fds, "ot.Other"))
    return reg


def _event_class(reg):
    resolved = reg.get("events")
    assert resolved is not None
    return resolved.message_class


def _make_events(msg_cls, n):
    msgs = []
    for i in range(n):
        e = msg_cls(id=i, color=i % 2, tags=[i, i + 1])
        e.name = "x" * (i % 5)
        e.payload = bytes([i % 256])
        if i % 4:  # ~75% have created_at set (presence)
            e.created_at.seconds = 1_700_000_000 + i
        e.attrs["k"] = i
        e.meta.ts.seconds = 1_600_000_000 + i
        e.meta.n = i
        if i % 2:
            e.a = f"A{i}"
        else:
            e.b = i
        msgs.append(e)
    return msgs


def _source(stream_id, msgs):
    return [(stream_id, m.SerializeToString()) for m in msgs]


# --- AE1: presence + value representation -----------------------------------

def test_ae1_presence_and_values():
    reg = _registry()
    msg_cls = _event_class(reg)
    e_set = msg_cls(id=7, name="hi", payload=b"\x01\x02", color=1)
    e_set.created_at.seconds = 100
    e_unset = msg_cls()  # implicit scalars default; created_at unset
    batches = list(
        to_arrow_batches(_source("events", [e_set, e_unset]), reg, stream_id="events")
    )
    table = pa.Table.from_batches(batches)
    schema = table.schema
    # value representation: Arrow-native, NOT JSON encodings
    assert pa.types.is_binary(schema.field("payload").type)  # not base64 string
    assert pa.types.is_integer(schema.field("color").type)  # enum -> int, not name
    assert pa.types.is_timestamp(schema.field("created_at").type)  # not RFC-3339 str
    # presence structure: implicit scalar non-nullable; message field nullable
    assert not schema.field("id").nullable
    assert schema.field("created_at").nullable
    cols = table.to_pydict()
    assert cols["id"] == [7, 0]  # unset implicit scalar -> default 0, not null
    assert cols["created_at"][1] is None  # unset message -> null


# --- AE2: oneof arms -> independent nullable columns, no discriminator -------

def test_ae2_oneof_columns():
    reg = _registry()
    msg_cls = _event_class(reg)
    e_a = msg_cls(id=1)
    e_a.a = "armA"
    e_b = msg_cls(id=2)
    e_b.b = 99
    table = pa.Table.from_batches(
        list(to_arrow_batches(_source("events", [e_a, e_b]), reg, stream_id="events"))
    )
    cols = table.to_pydict()
    assert "choice" not in table.schema.names  # no discriminator column
    assert cols["a"] == ["armA", None]
    assert cols["b"] == [None, 99]


# --- AE3: Any -> lossless struct, never blocked ------------------------------

def test_ae3_any_maps_to_struct_not_error():
    reg = _registry()
    msg_cls = _event_class(reg)
    e = msg_cls(id=1)
    table = pa.Table.from_batches(
        list(to_arrow_batches(_source("events", [e]), reg, stream_id="events"))
    )
    # Conversion did not raise; the Any field is a (struct) column, not blocked.
    assert "detail" in table.schema.names
    assert pa.types.is_struct(table.schema.field("detail").type)


# --- AE7: WKT nested at depth -> nested Arrow timestamp ----------------------

def test_ae7_nested_wkt():
    reg = _registry()
    msg_cls = _event_class(reg)
    e = msg_cls(id=1)
    e.meta.ts.seconds = 123
    table = pa.Table.from_batches(
        list(to_arrow_batches(_source("events", [e]), reg, stream_id="events"))
    )
    meta_type = table.schema.field("meta").type
    assert pa.types.is_struct(meta_type)
    assert pa.types.is_timestamp(meta_type.field("ts").type)


# --- AE5: a second message type in one pass -> typed error -------------------

def test_ae5_second_type_raises(tmp_path):
    reg = _registry()
    msg_cls = _event_class(reg)
    src = _source("events", [msg_cls(id=1)]) + _source("others", [
        reg.get("others").message_class(v=5)
    ])
    with pytest.raises(SchemaMismatchError):
        list(to_arrow_batches(src, reg, stream_id="events"))


# --- AE9 / R13: zero-record result -> valid 0-row Parquet, descriptor schema --

def test_ae9_zero_record_valid_parquet(tmp_path):
    reg = _registry()
    msg_cls = _event_class(reg)
    out = tmp_path / "empty.parquet"
    # predicate matches nothing
    rows = to_parquet(
        _source("events", [msg_cls(id=1), msg_cls(id=2)]),
        reg,
        out,
        stream_id="events",
        predicate=lambda m: False,
    )
    assert rows == 0
    table = pq.read_table(out)  # readable
    assert table.num_rows == 0
    assert "created_at" in table.schema.names  # full descriptor schema present


# --- R14: a collected fault -> IncompleteScanError + partial file discarded ---

def test_r14_fault_fails_loud_and_discards_file(tmp_path):
    reg = _registry()
    msg_cls = _event_class(reg)
    out = tmp_path / "partial.parquet"
    # An unknown stream_id record becomes a collected FrameError under the
    # sink's on_error='collect'; the good records still convert, but the sink
    # must fail loud and not leave a complete-looking file.
    src = _source("events", [msg_cls(id=1)]) + [("nope", b"\x00")]
    with pytest.raises(IncompleteScanError):
        to_parquet(src, reg, out, stream_id="events")
    assert not out.exists()  # partial output discarded


# --- to_parquet happy path + round-trip + batching ---------------------------

def test_to_parquet_roundtrip_and_batching(tmp_path):
    reg = _registry()
    msg_cls = _event_class(reg)
    msgs = _make_events(msg_cls, 5000)
    out = tmp_path / "events.parquet"
    rows = to_parquet(_source("events", msgs), reg, out, stream_id="events", batch_size=1024)
    assert rows == 5000
    table = pq.read_table(out)
    assert table.num_rows == 5000
    # row groups streamed (batch_size 1024 over 5000 rows -> multiple groups)
    assert pq.ParquetFile(out).num_row_groups >= 2
    cols = table.to_pydict()
    assert cols["id"][:3] == [0, 1, 2]


def test_to_arrow_batches_respects_batch_size():
    reg = _registry()
    msg_cls = _event_class(reg)
    msgs = _make_events(msg_cls, 2500)
    batches = list(
        to_arrow_batches(_source("events", msgs), reg, stream_id="events", batch_size=1000)
    )
    assert [b.num_rows for b in batches] == [1000, 1000, 500]


def test_unknown_stream_id_raises():
    reg = _registry()
    with pytest.raises(SchemaMismatchError):
        list(to_arrow_batches(_source("events", []), reg, stream_id="missing"))
