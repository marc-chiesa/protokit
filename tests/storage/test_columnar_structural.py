"""Unit tests for the columnar structural fidelity oracle (U1).

These exercise ``_dropped_declared_extensions`` directly — a pure descriptor +
schema-name set diff with no ptars/pyarrow dependency, so the module does NOT
``importorskip`` and runs in the core test environment. The oracle is the
*structural* half of the v2 fidelity signal: it detects declared proto2
extensions ptars drops from the Arrow schema — the blind spot the per-record
byte-delta probe cannot see. The sink wiring, policy, and the end-to-end ptars
pin live in ``test_columnar.py``.
"""

from __future__ import annotations

from google.protobuf import descriptor_pb2, descriptor_pool

from protokit.storage._columnar import _dropped_declared_extensions

F = descriptor_pb2.FieldDescriptorProto


def _base_with_extensions(
    ext_specs: list[tuple[str, int]],
) -> descriptor_pb2.FileDescriptorProto:
    """proto2 ``Base { optional int64 id = 1; extensions 100 to 200; }`` plus the
    given top-level extensions on ``.x.Base`` (each ``(name, number)``)."""
    fdp = descriptor_pb2.FileDescriptorProto(name="ext.proto", syntax="proto2", package="x")
    base = fdp.message_type.add()
    base.name = "Base"
    idf = base.field.add()
    idf.name, idf.number, idf.type, idf.label = "id", 1, F.TYPE_INT64, F.LABEL_OPTIONAL
    base.extension_range.add(start=100, end=201)
    for name, number in ext_specs:
        ext = fdp.extension.add()
        ext.name, ext.number, ext.type = name, number, F.TYPE_INT32
        ext.label, ext.extendee = F.LABEL_OPTIONAL, ".x.Base"
    return fdp


def _desc(fdp: descriptor_pb2.FileDescriptorProto, type_name: str = "Base"):
    """Build an isolated pool from one FileDescriptorProto, return the Descriptor."""
    pool = descriptor_pool.DescriptorPool()
    fd = pool.Add(fdp)
    return fd.message_types_by_name[type_name]


def test_declared_extension_reported_dropped():
    """AE1: a declared extension absent from the produced columns is reported."""
    desc = _desc(_base_with_extensions([("ext_val", 100)]))
    assert _dropped_declared_extensions(desc, ["id"]) == ("x.ext_val",)


def test_no_declared_extensions_silent():
    """AE2: a descriptor the pool declares no extension for yields nothing."""
    desc = _desc(_base_with_extensions([]))
    assert _dropped_declared_extensions(desc, ["id"]) == ()


def test_modeled_fields_never_inspected():
    """AE3: the extensions-only diff never inspects modeled fields, so a message
    with message/scalar fields and no extensions cannot be false-flagged — even a
    collapsing well-known type (whose sub-fields ptars omits) is irrelevant here
    because modeled fields are never checked."""
    fdp = descriptor_pb2.FileDescriptorProto(name="m.proto", syntax="proto3", package="m")
    inner = fdp.message_type.add()
    inner.name = "Inner"
    ik = inner.field.add()
    ik.name, ik.number, ik.type, ik.label = "k", 1, F.TYPE_INT32, F.LABEL_OPTIONAL
    outer = fdp.message_type.add()
    outer.name = "Outer"
    s = outer.field.add()
    s.name, s.number, s.type, s.label = "s", 1, F.TYPE_INT32, F.LABEL_OPTIONAL
    nf = outer.field.add()
    nf.name, nf.number, nf.type, nf.label = "nested", 2, F.TYPE_MESSAGE, F.LABEL_OPTIONAL
    nf.type_name = ".m.Inner"
    desc = _desc(fdp, "Outer")
    assert _dropped_declared_extensions(desc, ["s", "nested"]) == ()
    assert _dropped_declared_extensions(desc, []) == ()  # never false-flags fields


def test_extension_named_like_a_field_is_not_masked():
    """G7: an extension whose short name equals a regular field's column is still
    reported — a same-named field must not mask the dropped extension."""
    desc = _desc(_base_with_extensions([("id", 100)]))  # extension also named "id"
    assert _dropped_declared_extensions(desc, ["id"]) == ("x.id",)


def test_multiple_extensions_all_reported():
    desc = _desc(_base_with_extensions([("a", 100), ("b", 101)]))
    assert set(_dropped_declared_extensions(desc, ["id"])) == {"x.a", "x.b"}


def test_forward_defensive_columnized_extension_not_reported():
    """R4: an extension ptars *did* columnize (a non-field column attributable to
    it) is not reported — the schema-name check guards against a future ptars."""
    desc = _desc(_base_with_extensions([("ext_val", 100)]))
    # simulate a future ptars that emitted an "ext_val" column (not a field):
    assert _dropped_declared_extensions(desc, ["id", "ext_val"]) == ()
