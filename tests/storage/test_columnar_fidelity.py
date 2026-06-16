"""Unit tests for the columnar fidelity probe (U1).

These exercise ``_unmodeled_byte_delta`` directly — a pure-protobuf measurement
(clone + ``DiscardUnknownFields`` + ``ByteSize`` delta) with no ptars/pyarrow
dependency, so the module does NOT ``importorskip`` and runs in the core test
environment. The probe is the per-record half of the columnar fidelity signal;
the sink wiring, policy, and CLI behaviour live in ``test_columnar.py`` /
``cli/test_parquet_output.py``.

Empirical anchors (origin brainstorm Sources, verified 2026-06-15 on upb): proto2
closed enum ``08 08`` -> delta 2; proto3 open enum same bytes -> delta 0; nested
unknown -> recursive fire; declared extension -> silent (blind spot); missing
required field -> cannot measure.
"""

from __future__ import annotations

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

from protokit.storage._columnar import _unmodeled_byte_delta

F = descriptor_pb2.FieldDescriptorProto


def _cls(fdp: descriptor_pb2.FileDescriptorProto, type_name: str):
    """Build an isolated pool from one FileDescriptorProto and return a message class."""
    pool = descriptor_pool.DescriptorPool()
    fd = pool.Add(fdp)
    return message_factory.GetMessageClass(fd.message_types_by_name[type_name])


def _enum_file(syntax: str) -> descriptor_pb2.FileDescriptorProto:
    """``message M { optional Color c = 1; }`` with a closed/open enum (valid 0-3)."""
    fdp = descriptor_pb2.FileDescriptorProto(
        name=f"enum_{syntax}.proto", syntax=syntax, package=f"e{syntax[-1]}"
    )
    en = fdp.enum_type.add()
    en.name = "Color"
    for name, num in (("UNSET", 0), ("RED", 1), ("GREEN", 2), ("BLUE", 3)):
        v = en.value.add()
        v.name, v.number = name, num
    msg = fdp.message_type.add()
    msg.name = "M"
    fld = msg.field.add()
    fld.name, fld.number, fld.type = "c", 1, F.TYPE_ENUM
    fld.type_name = f".{fdp.package}.Color"
    fld.label = F.LABEL_OPTIONAL
    return fdp


# field 1, varint, value 8 — outside the enum's valid set (0-3)
_WIRE_ENUM_8 = bytes([0x08, 0x08])


def test_proto2_closed_enum_out_of_range_fires():
    """AE1: a proto2 closed enum relegates the out-of-range value to unknown fields."""
    m = _cls(_enum_file("proto2"), "M")()
    m.ParseFromString(_WIRE_ENUM_8)
    assert m.HasField("c") is False  # relegated, accessor returns default
    assert _unmodeled_byte_delta(m) == 2


def test_proto3_open_enum_out_of_range_silent():
    """AE2: a proto3 open enum keeps the value; nothing is unmodeled."""
    m = _cls(_enum_file("proto3"), "M")()
    m.ParseFromString(_WIRE_ENUM_8)
    assert m.c == 8  # preserved as the field value
    assert _unmodeled_byte_delta(m) == 0


def _nested_file(*, inner_has_extra: bool) -> descriptor_pb2.FileDescriptorProto:
    """``Outer { Inner inner = 1; }``; Inner has ``known`` (+ optional ``extra``)."""
    fdp = descriptor_pb2.FileDescriptorProto(name="nested.proto", syntax="proto3", package="n")
    inner = fdp.message_type.add()
    inner.name = "Inner"
    k = inner.field.add()
    k.name, k.number, k.type, k.label = "known", 1, F.TYPE_INT32, F.LABEL_OPTIONAL
    if inner_has_extra:
        x = inner.field.add()
        x.name, x.number, x.type, x.label = "extra", 5, F.TYPE_INT32, F.LABEL_OPTIONAL
    outer = fdp.message_type.add()
    outer.name = "Outer"
    f = outer.field.add()
    f.name, f.number, f.type, f.label = "inner", 1, F.TYPE_MESSAGE, F.LABEL_OPTIONAL
    f.type_name = ".n.Inner"
    return fdp


def test_nested_undeclared_field_fires_recursively():
    """AE3: an unknown field inside a submessage is caught by the recursive discard."""
    full = _cls(_nested_file(inner_has_extra=True), "Outer")
    reduced = _cls(_nested_file(inner_has_extra=False), "Outer")
    src = full()
    src.inner.known = 7
    src.inner.extra = 99
    wire = src.SerializeToString()

    m = reduced()
    m.ParseFromString(wire)
    assert m.inner.known == 7
    assert _unmodeled_byte_delta(m) > 0  # the nested `extra` is unmodeled here


def test_clean_message_silent():
    """AE4: a message fully within the descriptor produces no false positive."""
    reduced = _cls(_nested_file(inner_has_extra=False), "Outer")
    m = reduced()
    m.inner.known = 7
    assert _unmodeled_byte_delta(m) == 0


def _map_file(*, value_has_extra: bool) -> descriptor_pb2.FileDescriptorProto:
    """``Outer { map<string, Inner> m = 1; }`` (synthetic map-entry submessage)."""
    fdp = descriptor_pb2.FileDescriptorProto(name="map.proto", syntax="proto3", package="mp")
    inner = fdp.message_type.add()
    inner.name = "Inner"
    k = inner.field.add()
    k.name, k.number, k.type, k.label = "known", 1, F.TYPE_INT32, F.LABEL_OPTIONAL
    if value_has_extra:
        x = inner.field.add()
        x.name, x.number, x.type, x.label = "extra", 5, F.TYPE_INT32, F.LABEL_OPTIONAL
    outer = fdp.message_type.add()
    outer.name = "Outer"
    entry = outer.nested_type.add()
    entry.name = "MEntry"
    entry.options.map_entry = True
    ek = entry.field.add()
    ek.name, ek.number, ek.type, ek.label = "key", 1, F.TYPE_STRING, F.LABEL_OPTIONAL
    ev = entry.field.add()
    ev.name, ev.number, ev.type, ev.label = "value", 2, F.TYPE_MESSAGE, F.LABEL_OPTIONAL
    ev.type_name = ".mp.Inner"
    mfld = outer.field.add()
    mfld.name, mfld.number, mfld.type = "m", 1, F.TYPE_MESSAGE
    mfld.label, mfld.type_name = F.LABEL_REPEATED, ".mp.Outer.MEntry"
    return fdp


def test_map_value_undeclared_field_fires():
    """Plan U1 scenario: recursion reaches map-entry value submessages."""
    full = _cls(_map_file(value_has_extra=True), "Outer")
    reduced = _cls(_map_file(value_has_extra=False), "Outer")
    src = full()
    src.m["k"].known = 7
    src.m["k"].extra = 99
    wire = src.SerializeToString()

    m = reduced()
    m.ParseFromString(wire)
    assert m.m["k"].known == 7
    assert _unmodeled_byte_delta(m) > 0


def _extension_file() -> descriptor_pb2.FileDescriptorProto:
    """proto2 ``Base { optional int64 id = 1; extensions 100 to 200; }`` + ``ext_val`` #100."""
    fdp = descriptor_pb2.FileDescriptorProto(name="ext.proto", syntax="proto2", package="x")
    base = fdp.message_type.add()
    base.name = "Base"
    idf = base.field.add()
    idf.name, idf.number, idf.type, idf.label = "id", 1, F.TYPE_INT64, F.LABEL_OPTIONAL
    base.extension_range.add(start=100, end=201)
    ext = fdp.extension.add()
    ext.name, ext.number, ext.type = "ext_val", 100, F.TYPE_INT32
    ext.label, ext.extendee = F.LABEL_OPTIONAL, ".x.Base"
    return fdp


def test_declared_extension_is_a_blind_spot():
    """AE6: a *declared* proto2 extension reads into Extensions[...] with an empty
    unknown set, so the probe stays silent — the documented non-goal."""
    fdp = _extension_file()
    pool = descriptor_pool.DescriptorPool()
    fd = pool.Add(fdp)
    base_cls = message_factory.GetMessageClass(fd.message_types_by_name["Base"])
    ext_field = pool.FindExtensionByName("x.ext_val")

    m = base_cls()
    m.id = 7
    m.Extensions[ext_field] = 42
    reparsed = base_cls()
    reparsed.ParseFromString(m.SerializeToString())
    assert reparsed.Extensions[ext_field] == 42
    assert _unmodeled_byte_delta(reparsed) == 0  # declared -> invisible to the probe


def _required_file() -> descriptor_pb2.FileDescriptorProto:
    """proto2 ``R { required int32 r = 1; optional int32 o = 2; }``."""
    fdp = descriptor_pb2.FileDescriptorProto(name="req.proto", syntax="proto2", package="rq")
    msg = fdp.message_type.add()
    msg.name = "R"
    r = msg.field.add()
    r.name, r.number, r.type, r.label = "r", 1, F.TYPE_INT32, F.LABEL_REQUIRED
    o = msg.field.add()
    o.name, o.number, o.type, o.label = "o", 2, F.TYPE_INT32, F.LABEL_OPTIONAL
    return fdp


def test_missing_required_field_cannot_measure():
    """AE7: ByteSize raises EncodeError on an uninitialized proto2 message; the
    probe returns None ('cannot measure') rather than letting it escape."""
    cls = _cls(_required_file(), "R")
    m = cls()
    m.ParseFromString(bytes([0x10, 0x05]))  # field 2 (o) = 5; required r unset
    assert m.IsInitialized() is False
    assert _unmodeled_byte_delta(m) is None
