"""Columnar / Parquet sink tests (PR3 U4/U5).

Skips cleanly when the ``protokit[parquet]`` extra is absent — the module-top
``importorskip`` guards collection (a ``pytestmark`` would NOT guard the
module-top ptars/pyarrow imports). The extra-absent error path (R9/AE6) is
covered separately in ``test_columnar_extra.py`` (which does not importorskip).
"""

from __future__ import annotations

import functools
import os

import pytest

pytest.importorskip("ptars")
pa = pytest.importorskip("pyarrow")
import pyarrow.parquet as pq  # noqa: E402 - after importorskip by design
from google.protobuf import (  # noqa: E402
    any_pb2,
    descriptor_pb2,
    struct_pb2,
    timestamp_pb2,
)

from protokit.storage import (  # noqa: E402
    FidelityError,
    HandlerBuildError,
    IncompleteScanError,
    RecursiveSchemaError,
    SchemaMismatchError,
    StorageError,
    UnknownStreamError,
    UnsupportedWktError,
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
    batches = list(to_arrow_batches(_source("events", [e_set, e_unset]), reg, stream_id="events"))
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
    src = _source("events", [msg_cls(id=1)]) + _source(
        "others", [reg.get("others").message_class(v=5)]
    )
    with pytest.raises(SchemaMismatchError):
        list(to_arrow_batches(src, reg, stream_id="events"))


# --- AE9 / R13: zero-record result -> valid 0-row Parquet, descriptor schema --


def test_ae9_zero_record_valid_parquet(tmp_path):
    reg = _registry()
    msg_cls = _event_class(reg)
    out = tmp_path / "empty.parquet"
    # predicate matches nothing
    report = to_parquet(
        _source("events", [msg_cls(id=1), msg_cls(id=2)]),
        reg,
        out,
        stream_id="events",
        predicate=lambda m: False,
    )
    assert report.rows == 0
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


def test_incomplete_scan_error_carries_collected_faults(tmp_path):
    reg = _registry()
    msg_cls = _event_class(reg)
    out = tmp_path / "partial.parquet"
    src = _source("events", [msg_cls(id=1)]) + [("nope", b"\x00")]
    with pytest.raises(IncompleteScanError) as excinfo:
        to_parquet(src, reg, out, stream_id="events")
    err = excinfo.value
    # The collected FrameErrors are carried verbatim so a caller can report
    # fault locations without scraping the message string.
    assert err.fault_count == len(err.faults) == 1
    first = err.faults[0]
    assert first.stream_id == "nope"
    assert isinstance(first.record_index, int)
    assert first.reason
    # offset is None for this non-positional (unknown-stream) fault — callers
    # must tolerate it.
    assert first.offset is None
    # Backward-compatible message shape: the count still appears verbatim.
    assert "1 record fault(s)" in str(err)


# --- to_parquet happy path + round-trip + batching ---------------------------


def test_to_parquet_roundtrip_and_batching(tmp_path):
    reg = _registry()
    msg_cls = _event_class(reg)
    msgs = _make_events(msg_cls, 5000)
    out = tmp_path / "events.parquet"
    report = to_parquet(_source("events", msgs), reg, out, stream_id="events", batch_size=1024)
    assert report.rows == 5000
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
    with pytest.raises(UnknownStreamError):
        list(to_arrow_batches(_source("events", []), reg, stream_id="missing"))


# --- AE4 / R2: bounded — the sink pulls O(batch), not the whole source --------


def test_ae4_sink_pulls_bounded_not_whole_source():
    reg = _registry()
    msg_cls = _event_class(reg)
    pulled = 0
    payload = msg_cls(id=1).SerializeToString()

    def counting_source(n):
        nonlocal pulled
        for _ in range(n):
            pulled += 1
            yield ("events", payload)

    gen = to_arrow_batches(counting_source(10_000), reg, stream_id="events", batch_size=1000)
    first = next(gen)  # consume only the first batch
    assert first.num_rows == 1000
    # bounded: the sink pulled ~one batch worth, NOT the whole 10k source
    assert pulled <= 1001, pulled
    gen.close()


# --- R14: non-FrameError mid-stream abort still discards the partial file ------


def test_to_parquet_mid_stream_type_mismatch_discards_file(tmp_path):
    reg = _registry()
    msg_cls = _event_class(reg)
    other_cls = reg.get("others").message_class
    out = tmp_path / "mid.parquet"
    # batch_size=2: first batch [E,E] writes a row group (file created); the
    # second batch hits an 'others'-type record -> SchemaMismatchError mid-stream.
    src = _source("events", [msg_cls(id=1), msg_cls(id=2)]) + [
        ("others", other_cls(v=9).SerializeToString()),
        ("events", msg_cls(id=3).SerializeToString()),
    ]
    with pytest.raises(SchemaMismatchError):
        to_parquet(src, reg, out, stream_id="events", batch_size=2)
    assert not out.exists()  # partial file discarded on mid-stream abort


# --- R15: a memoryview-backed source converts (sink consumes parsed messages) --


def test_memoryview_source_converts(tmp_path):
    reg = _registry()
    msg_cls = _event_class(reg)
    out = tmp_path / "mv.parquet"
    # record bytes as a memoryview over a bytearray (a C++-style buffer): the
    # engine takes its defensive copy and the sink consumes only parsed messages,
    # so a memoryview-backed source converts without issue (R15).
    src = [("events", memoryview(bytearray(msg_cls(id=i).SerializeToString()))) for i in range(50)]
    report = to_parquet(src, reg, out, stream_id="events")
    assert report.rows == 50
    assert pq.read_table(out).num_rows == 50


# --- to_arrow_batches surfaces a collected fault after exhaustion -------------


def test_to_arrow_batches_fault_raises_after_exhaustion():
    reg = _registry()
    msg_cls = _event_class(reg)
    src = _source("events", [msg_cls(id=1)]) + [("nope", b"\x00")]
    with pytest.raises(IncompleteScanError):
        list(to_arrow_batches(src, reg, stream_id="events"))


# --- AE3 Any value round-trip (lossless struct, not just shape) ---------------


def test_ae3_any_value_roundtrip():
    reg = _registry()
    msg_cls = _event_class(reg)
    e = msg_cls(id=1)
    e.detail.type_url = "type.googleapis.com/ev.Event"
    e.detail.value = b"\x08\x07"
    table = pa.Table.from_batches(
        list(to_arrow_batches(_source("events", [e]), reg, stream_id="events"))
    )
    detail = table.to_pydict()["detail"][0]
    assert detail["type_url"] == "type.googleapis.com/ev.Event"
    assert detail["value"] == b"\x08\x07"


# --- AE7 nested WKT value round-trip ------------------------------------------


def test_ae7_nested_wkt_value_roundtrip():
    reg = _registry()
    msg_cls = _event_class(reg)
    e = msg_cls(id=1)
    e.meta.ts.seconds = 1_700_000_000
    e.meta.n = 5
    table = pa.Table.from_batches(
        list(to_arrow_batches(_source("events", [e]), reg, stream_id="events"))
    )
    meta = table.to_pydict()["meta"][0]
    assert int(meta["ts"].timestamp()) == 1_700_000_000
    assert meta["n"] == 5


# --- HandlerBuildError fires before the writer opens (no orphan file) ---------


def test_handler_build_error_before_file_created(tmp_path, monkeypatch):
    import ptars

    reg = _registry()
    out = tmp_path / "hb.parquet"

    class _BoomPool:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(ptars, "HandlerPool", _BoomPool)
    with pytest.raises(HandlerBuildError):
        to_parquet(_source("events", []), reg, out, stream_id="events")
    assert not out.exists()  # adapter built before the writer opens -> no file


# --- cross-batch schema drift is an internal invariant breach (RuntimeError) --


def test_cross_batch_schema_drift_raises_runtime_error():
    from protokit.storage._columnar import _PtarsConversionAdapter

    reg = _registry()
    msg_cls = _event_class(reg)
    desc = reg.get("events").message_class.DESCRIPTOR
    adapter = _PtarsConversionAdapter(desc)

    drifted = pa.record_batch({"x": pa.array([1], type=pa.int64())})

    class _DriftPool:
        def messages_to_record_batch(self, messages, descriptor):
            return drifted

    adapter._pool = _DriftPool()
    with pytest.raises(RuntimeError, match="drifted"):
        adapter.to_record_batch([msg_cls(id=1)])


# --- recursive-schema rejection: pre-flight before ptars (U2) -----------------


def _recursive_fds():
    """A single recursive message ``n.Node { repeated Node children }``."""
    fds = descriptor_pb2.FileDescriptorSet()
    f = fds.file.add()
    f.name, f.package, f.syntax = "node.proto", "n", "proto3"
    node = f.message_type.add()
    node.name = "Node"
    fld = node.field.add()
    fld.name, fld.number, fld.type, fld.label = (
        "children",
        1,
        F.TYPE_MESSAGE,
        F.LABEL_REPEATED,
    )
    fld.type_name = ".n.Node"
    return fds


def _mutual_fds():
    """Mutually recursive ``p.A { B b }`` / ``p.B { A a }``."""
    fds = descriptor_pb2.FileDescriptorSet()
    f = fds.file.add()
    f.name, f.package, f.syntax = "ab.proto", "p", "proto3"
    a = f.message_type.add()
    a.name = "A"
    fa = a.field.add()
    fa.name, fa.number, fa.type, fa.label = "b", 1, F.TYPE_MESSAGE, F.LABEL_OPTIONAL
    fa.type_name = ".p.B"
    b = f.message_type.add()
    b.name = "B"
    fb = b.field.add()
    fb.name, fb.number, fb.type, fb.label = "a", 1, F.TYPE_MESSAGE, F.LABEL_OPTIONAL
    fb.type_name = ".p.A"
    return fds


def _wkt_embed_fds(wkt_module, wkt_type, holder="Holder"):
    """A message with one field of the given well-known type."""
    fds = descriptor_pb2.FileDescriptorSet()
    wkt_module.DESCRIPTOR.CopyToProto(fds.file.add())
    f = fds.file.add()
    f.name, f.package, f.syntax = "u.proto", "u", "proto3"
    f.dependency.append(wkt_module.DESCRIPTOR.name)
    h = f.message_type.add()
    h.name = holder
    fld = h.field.add()
    fld.name, fld.number, fld.type, fld.label = "w", 1, F.TYPE_MESSAGE, F.LABEL_OPTIONAL
    fld.type_name = f".google.protobuf.{wkt_type}"
    return fds


def _reg(fds, type_name, stream="s"):
    reg = StreamRegistry()
    reg.register_stream(stream, FileDescriptorSetSchema(fds, type_name))
    return reg


def test_recursive_self_ref_rejected_before_file(tmp_path):
    reg = _reg(_recursive_fds(), "n.Node")
    out = tmp_path / "r.parquet"
    with pytest.raises(RecursiveSchemaError):
        to_parquet([], reg, out, stream_id="s")
    assert not out.exists()  # rejected before the writer opens -> no file


def test_recursive_error_carries_cycle(tmp_path):
    reg = _reg(_recursive_fds(), "n.Node")
    with pytest.raises(RecursiveSchemaError) as excinfo:
        to_parquet([], reg, tmp_path / "r.parquet", stream_id="s")
    err = excinfo.value
    assert err.type_name == "n.Node"
    # length-1 (root self-reference) cycle renders both ends explicitly
    assert err.cycle == ("n.Node", "n.Node")
    assert "n.Node -> n.Node" in str(err)


def test_mutual_recursion_rejected(tmp_path):
    reg = _reg(_mutual_fds(), "p.A")
    with pytest.raises(RecursiveSchemaError) as excinfo:
        to_parquet([], reg, tmp_path / "m.parquet", stream_id="s")
    assert "p.A -> p.B -> p.A" in str(excinfo.value)


def test_unused_recursive_field_still_rejected(tmp_path):
    # The recursive field is never populated, but rejection is type-level: the
    # adapter is built (and rejects) before any record is examined.
    reg = _reg(_recursive_fds(), "n.Node")
    msg = reg.get("s").message_class()  # no children set
    with pytest.raises(RecursiveSchemaError):
        to_parquet(_source("s", [msg]), reg, tmp_path / "u.parquet", stream_id="s")


def test_to_arrow_batches_rejects_on_first_consumption():
    reg = _reg(_recursive_fds(), "n.Node")
    gen = to_arrow_batches([], reg, stream_id="s")  # generator: body not yet run
    with pytest.raises(RecursiveSchemaError):
        list(gen)


def test_struct_embed_rejected_as_unsupported_wkt(tmp_path):
    reg = _reg(_wkt_embed_fds(struct_pb2, "Struct", holder="HasStruct"), "u.HasStruct")
    out = tmp_path / "s.parquet"
    with pytest.raises(UnsupportedWktError) as excinfo:
        to_parquet([], reg, out, stream_id="s")
    assert excinfo.value.type_name == "u.HasStruct"
    assert "google.protobuf.Struct" in str(excinfo.value)
    # The structured cycle is carried verbatim and lies entirely within the WKT
    # struct family (parallel to RecursiveSchemaError.cycle, which is asserted
    # in test_recursive_error_carries_cycle).
    assert len(excinfo.value.cycle) >= 2
    assert all(n.startswith("google.protobuf.") for n in excinfo.value.cycle)
    assert not out.exists()


@pytest.mark.parametrize("wkt", ["Value", "ListValue"])
def test_recursive_wkt_family_rejected_in_process(tmp_path, wkt):
    # The subprocess survival test covers process survival for the whole family;
    # this pins the in-process error TYPE and cycle for Value / ListValue, not
    # just Struct.
    reg = _reg(_wkt_embed_fds(struct_pb2, wkt), "u.Holder")
    out = tmp_path / "w.parquet"
    with pytest.raises(UnsupportedWktError) as excinfo:
        to_parquet([], reg, out, stream_id="s")
    assert all(n.startswith("google.protobuf.") for n in excinfo.value.cycle)
    assert not out.exists()


def test_non_recursive_wkt_embed_converts(tmp_path):
    reg = _reg(_wkt_embed_fds(timestamp_pb2, "Timestamp", holder="HasTs"), "u.HasTs")
    msg = reg.get("s").message_class()
    msg.w.seconds = 5
    out = tmp_path / "t.parquet"
    report = to_parquet(_source("s", [msg]), reg, out, stream_id="s")
    assert report.rows == 1
    assert out.exists()


def test_recursive_errors_are_storage_errors():
    assert issubclass(RecursiveSchemaError, StorageError)
    assert issubclass(UnsupportedWktError, StorageError)


# --- _transitive_file_descriptors: deduped + dependency-ordered ---------------


def test_transitive_file_descriptors_deduped_and_ordered():
    from protokit.storage._columnar import _transitive_file_descriptors

    reg = _registry()
    desc = reg.get("events").message_class.DESCRIPTOR
    names = [f.name for f in _transitive_file_descriptors(desc)]
    assert len(names) == len(set(names))  # deduped by name
    assert "ev.proto" in names
    assert "google/protobuf/timestamp.proto" in names
    # dependency precedes dependent: the WKT files come before the importer
    assert names.index("google/protobuf/timestamp.proto") < names.index("ev.proto")


# --- fidelity signal (U3 wiring + report, U4 strict mode) ---------------------
#
# Setup: register the stream with a REDUCED descriptor (M { int32 id }) but feed
# wire bytes from a FULL M (id + an `extra` field #50). scan parses with the
# reduced class, so `extra` lands in the unknown-field set and the sink's probe
# detects it — the same shape as a real vendor extension outside the descriptor.


def _fid_fds(*, with_extra: bool):
    fds = descriptor_pb2.FileDescriptorSet()
    f = fds.file.add()
    f.name, f.package, f.syntax = "fid.proto", "fid", "proto3"
    m = f.message_type.add()
    m.name = "M"
    idf = m.field.add()
    idf.name, idf.number, idf.type, idf.label = "id", 1, F.TYPE_INT32, F.LABEL_OPTIONAL
    if with_extra:
        ex = m.field.add()
        ex.name, ex.number, ex.type, ex.label = "extra", 50, F.TYPE_INT32, F.LABEL_OPTIONAL
    return fds


def _fid_registry():
    """Registry whose ``M`` lacks ``extra`` — so wire ``extra`` is unmodeled."""
    reg = StreamRegistry()
    reg.register_stream("s", FileDescriptorSetSchema(_fid_fds(with_extra=False), "fid.M"))
    return reg


@functools.lru_cache(maxsize=1)
def _full_m_class():
    # Memoized: the full-M class is shared by _unmodeled_bytes/_modeled_bytes
    # across every fidelity test, so the pool is built once, not per call.
    reg = StreamRegistry()
    reg.register_stream("s", FileDescriptorSetSchema(_fid_fds(with_extra=True), "fid.M"))
    return reg.get("s").message_class


def _unmodeled_bytes(id_val, extra_val):
    msg = _full_m_class()(id=id_val)
    msg.extra = extra_val
    return msg.SerializeToString()


def _modeled_bytes(id_val):
    return _full_m_class()(id=id_val).SerializeToString()


def test_fidelity_warn_default_surfaces_count(tmp_path):  # AE10, AE9, AE1
    reg = _fid_registry()
    src = [("s", _unmodeled_bytes(1, 99)), ("s", _modeled_bytes(2))]
    out = tmp_path / "w.parquet"
    report = to_parquet(src, reg, out, stream_id="s")  # default warn
    assert report.measured is True
    assert report.rows == 2
    assert report.unmodeled_records == 1
    # exact: the unknown field #50 (tag 0x90 0x03) + varint 99 (0x63) = 3 bytes
    assert report.unmodeled_bytes == 3
    assert out.exists()  # warn writes the file regardless
    # conversion proceeds unchanged: the modeled `id` is present in the column
    assert pq.read_table(out).column("id").to_pylist() == [1, 2]


def test_fidelity_ignore_skips_measurement(tmp_path):  # AE11
    reg = _fid_registry()
    out = tmp_path / "i.parquet"
    report = to_parquet(
        [("s", _unmodeled_bytes(1, 99))], reg, out, stream_id="s", fidelity="ignore"
    )
    assert report.measured is False  # not measured, distinct from a measured zero
    assert report.unmodeled_records == 0
    assert report.unmodeled_bytes == 0
    assert report.rows == 1
    assert out.exists()


def test_fidelity_clean_input_measured_zero(tmp_path):
    reg = _fid_registry()
    out = tmp_path / "c.parquet"
    report = to_parquet(
        [("s", _modeled_bytes(1)), ("s", _modeled_bytes(2))], reg, out, stream_id="s"
    )
    assert report.measured is True
    assert report.unmodeled_records == 0
    assert report.unmodeled_bytes == 0


def test_fidelity_empty_scan_builds_report(tmp_path):  # empty/zero-row path
    reg = _fid_registry()
    out = tmp_path / "e.parquet"
    report = to_parquet([], reg, out, stream_id="s")
    assert report.rows == 0
    assert report.measured is True
    assert report.unmodeled_records == 0
    assert out.exists()  # valid zero-row Parquet still written


def test_fidelity_error_raises_and_discards(tmp_path):  # AE5 (U4)
    reg = _fid_registry()
    out = tmp_path / "x.parquet"
    with pytest.raises(FidelityError) as excinfo:
        to_parquet([("s", _unmodeled_bytes(1, 99))], reg, out, stream_id="s", fidelity="error")
    assert excinfo.value.unmodeled_records == 1
    assert excinfo.value.unmodeled_bytes > 0
    assert "unmodeled wire data" in str(excinfo.value)
    assert not out.exists()  # partial discarded, like a decode fault


def test_fidelity_error_clean_input_writes(tmp_path):  # error mode, nothing unmodeled
    reg = _fid_registry()
    out = tmp_path / "x2.parquet"
    report = to_parquet([("s", _modeled_bytes(1))], reg, out, stream_id="s", fidelity="error")
    assert report.rows == 1
    assert out.exists()


def test_fidelity_error_empty_scan_no_raise(tmp_path):  # error mode, empty input
    reg = _fid_registry()
    out = tmp_path / "x3.parquet"
    report = to_parquet([], reg, out, stream_id="s", fidelity="error")
    assert report.rows == 0
    assert out.exists()


def test_decode_fault_takes_precedence_over_fidelity(tmp_path):  # AE8
    reg = _fid_registry()
    out = tmp_path / "p.parquet"
    # one unmodeled-data record AND one decode/frame fault (unknown stream),
    # under fidelity='error': the decode fault wins, not FidelityError.
    src = [("s", _unmodeled_bytes(1, 99)), ("nope", b"\x00")]
    with pytest.raises(IncompleteScanError):
        to_parquet(src, reg, out, stream_id="s", fidelity="error")
    assert not out.exists()


# --- R9: the signal agrees with ptars's column disposition, end to end --------
#
# The probe runs on the parsed Python message; ptars converts a re-serialization
# of it. R9 pins that the two stay consistent against the *actual* conversion,
# not just a SerializeToString round-trip: an undeclared field is dropped from
# the Parquet AND flagged; an out-of-range closed enum is present in the column
# as a raw int AND flagged.


def test_r9_pin_undeclared_field_dropped_and_flagged(tmp_path):
    reg = _fid_registry()
    out = tmp_path / "r9a.parquet"
    report = to_parquet([("s", _unmodeled_bytes(1, 99))], reg, out, stream_id="s")
    table = pq.read_table(out)
    assert table.schema.names == ["id"]  # the undeclared field is NOT a column
    assert report.unmodeled_records == 1  # ...and the signal flagged the loss


def _fid_proto2_enum_fds():
    fds = descriptor_pb2.FileDescriptorSet()
    f = fds.file.add()
    f.name, f.package, f.syntax = "p2.proto", "p2", "proto2"
    en = f.enum_type.add()
    en.name = "Color"
    for n, num in (("UNSET", 0), ("RED", 1), ("GREEN", 2), ("BLUE", 3)):
        v = en.value.add()
        v.name, v.number = n, num
    m = f.message_type.add()
    m.name = "E"
    fld = m.field.add()
    fld.name, fld.number, fld.type = "c", 1, F.TYPE_ENUM
    fld.type_name, fld.label = ".p2.Color", F.LABEL_OPTIONAL
    return fds


def test_r9_pin_out_of_range_closed_enum_present_and_flagged(tmp_path):
    reg = StreamRegistry()
    reg.register_stream("s", FileDescriptorSetSchema(_fid_proto2_enum_fds(), "p2.E"))
    out = tmp_path / "r9b.parquet"
    # wire 08 08: a proto2 closed enum set to 8, outside the valid 0-3 set. A
    # protobuf reader relegates it (HasField=False, default 0); ptars surfaces
    # the raw int in the column. The probe flags the divergence.
    report = to_parquet([("s", bytes([0x08, 0x08]))], reg, out, stream_id="s")
    assert pq.read_table(out).column("c").to_pylist() == [8]  # raw int, present
    assert report.unmodeled_records == 1  # ...and the signal flagged it


@pytest.mark.skipif(
    not os.environ.get("PROTOKIT_BENCH"),
    reason="opt-in cost benchmark (set PROTOKIT_BENCH=1); not a CI gate (U6/R10)",
)
def test_fidelity_probe_cost_benchmark(tmp_path):
    """Measure the warn-tier probe's marginal cost vs ignore on a nested feed.

    Run pre-merge (``PROTOKIT_BENCH=1 pytest -k cost_benchmark -s``); record the
    ratio in the PR. Informs whether the ``warn``-on-by-default posture holds or
    falls back to ``ignore``-default (origin R10).
    """
    import time

    reg = _registry()
    msg_cls = _event_class(reg)
    src = _source("events", _make_events(msg_cls, 20_000))  # nested: Meta, attrs, WKT

    def run(fidelity):
        t0 = time.perf_counter()
        to_parquet(
            src, reg, tmp_path / f"b_{fidelity}.parquet", stream_id="events", fidelity=fidelity
        )
        return time.perf_counter() - t0

    run("ignore")  # warm caches
    off = min(run("ignore") for _ in range(3))
    on = min(run("warn") for _ in range(3))
    ratio = on / off
    print(
        f"\nfidelity probe cost: ignore={off * 1000:.1f}ms "
        f"warn={on * 1000:.1f}ms ratio={ratio:.2f}x"
    )


def test_fidelity_accumulates_across_batches(tmp_path):
    # batch_size=1 forces three separate chunk iterations; the loop-local
    # accumulator must sum records and bytes across all of them.
    reg = _fid_registry()
    src = [("s", _unmodeled_bytes(i, 99)) for i in range(3)]
    out = tmp_path / "multi.parquet"
    report = to_parquet(src, reg, out, stream_id="s", batch_size=1)
    assert report.rows == 3
    assert report.unmodeled_records == 3
    assert report.unmodeled_bytes == 9  # 3 bytes each, summed across 3 batches


# --- structural fidelity oracle: declared proto2 extensions ptars drops (U3) ---
#
# Setup: register a proto2 ``Base { optional int64 id = 1; extensions 100..200; }``
# whose pool DECLARES extension ``ext_val`` #100. ptars columnizes ``id`` only and
# drops the extension column — a loss the per-record byte-delta probe is blind to
# (a declared extension reads into Extensions[...] with an empty unknown set). The
# oracle fires on the DECLARED extension regardless of whether a record sets it.

_BASE_ID7 = bytes([0x08, 0x07])  # Base{id=7}: field 1 (int64 varint) = 7


def _struct_fds(*, with_extension: bool):
    fds = descriptor_pb2.FileDescriptorSet()
    f = fds.file.add()
    f.name, f.package, f.syntax = "so.proto", "so", "proto2"
    m = f.message_type.add()
    m.name = "Base"
    idf = m.field.add()
    idf.name, idf.number, idf.type, idf.label = "id", 1, F.TYPE_INT64, F.LABEL_OPTIONAL
    m.extension_range.add(start=100, end=201)
    if with_extension:
        ext = f.extension.add()
        ext.name, ext.number, ext.type = "ext_val", 100, F.TYPE_INT32
        ext.label, ext.extendee = F.LABEL_OPTIONAL, ".so.Base"
    return fds


def _struct_registry(*, with_extension: bool):
    reg = StreamRegistry()
    reg.register_stream(
        "s", FileDescriptorSetSchema(_struct_fds(with_extension=with_extension), "so.Base")
    )
    return reg


def test_structural_warn_reports_dropped_extension(tmp_path):  # AE1
    reg = _struct_registry(with_extension=True)
    out = tmp_path / "sw.parquet"
    report = to_parquet([("s", _BASE_ID7)], reg, out, stream_id="s")  # default warn
    assert report.measured is True
    assert report.dropped_extensions == ("so.ext_val",)
    assert report.rows == 1
    assert out.exists()  # warn writes the file regardless
    assert pq.read_table(out).schema.names == ["id"]  # extension is not a column


def test_structural_clean_descriptor_silent(tmp_path):  # AE2
    reg = _struct_registry(with_extension=False)
    out = tmp_path / "sc.parquet"
    report = to_parquet([("s", _BASE_ID7)], reg, out, stream_id="s")
    assert report.measured is True
    assert report.dropped_extensions == ()


def test_structural_ignore_skips_computation(tmp_path, monkeypatch):  # AE10 / G8
    reg = _struct_registry(with_extension=True)
    out = tmp_path / "si.parquet"
    import protokit.storage._columnar as columnar

    def _boom(*a, **k):
        raise AssertionError("oracle computed under fidelity='ignore'")

    monkeypatch.setattr(columnar, "_dropped_declared_extensions", _boom)
    report = to_parquet([("s", _BASE_ID7)], reg, out, stream_id="s", fidelity="ignore")
    assert report.measured is False
    assert report.dropped_extensions == ()
    assert out.exists()


def test_structural_error_fails_fast_before_scan(tmp_path):  # AE6
    reg = _struct_registry(with_extension=True)
    out = tmp_path / "se.parquet"
    pulled = 0

    def counting_source():
        nonlocal pulled
        for _ in range(3):
            pulled += 1
            yield ("s", _BASE_ID7)

    with pytest.raises(FidelityError) as excinfo:
        to_parquet(counting_source(), reg, out, stream_id="s", fidelity="error")
    assert excinfo.value.dropped_extensions == ("so.ext_val",)
    assert excinfo.value.unmodeled_records == 0  # bind-time: no record measured
    assert "so.ext_val" in str(excinfo.value)
    assert pulled == 0  # fail-fast: raised before the scan pulled any record
    assert not out.exists()  # ...and before the writer opened


def test_structural_error_pre_empts_decode_fault(tmp_path):  # G1
    reg = _struct_registry(with_extension=True)
    out = tmp_path / "sg1.parquet"
    # A descriptor that trips the oracle AND a decode-faulting record: the
    # structural error (bind) wins over IncompleteScanError (scan-end) — the
    # inverse of v1's "decode beats fidelity," which holds only at scan-end.
    src = [("s", _BASE_ID7), ("nope", b"\x00")]
    with pytest.raises(FidelityError) as excinfo:
        to_parquet(src, reg, out, stream_id="s", fidelity="error")
    assert excinfo.value.dropped_extensions == ("so.ext_val",)
    assert not out.exists()


def test_structural_empty_scan_still_flags(tmp_path):  # G9
    reg = _struct_registry(with_extension=True)
    out = tmp_path / "sg9.parquet"
    # The oracle is record-independent: a zero-record scan still flags the drop
    # under warn (and writes a valid zero-row Parquet).
    report = to_parquet([], reg, out, stream_id="s")
    assert report.rows == 0
    assert report.dropped_extensions == ("so.ext_val",)
    assert out.exists()
    # ...and fails fast under error even with no records.
    out2 = tmp_path / "sg9b.parquet"
    with pytest.raises(FidelityError):
        to_parquet([], reg, out2, stream_id="s", fidelity="error")
    assert not out2.exists()


def test_structural_and_per_record_both_fire_under_warn(tmp_path):  # G2
    reg = _struct_registry(with_extension=True)
    out = tmp_path / "sboth.parquet"
    # Base{id=7} + an UNDECLARED field #50 (tag 0x90 0x03, value 0x63): the
    # undeclared field lands in the unknown set (per-record probe fires) while the
    # declared ext_val drives the structural signal — both surface, no double-count.
    record = _BASE_ID7 + bytes([0x90, 0x03, 0x63])
    report = to_parquet([("s", record)], reg, out, stream_id="s")
    assert report.dropped_extensions == ("so.ext_val",)  # structural
    assert report.unmodeled_records == 1  # per-record, independent
    assert report.unmodeled_bytes == 3
    assert out.exists()
