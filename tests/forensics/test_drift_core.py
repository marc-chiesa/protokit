"""U7 — per-field drift reconciliation against a chosen candidate schema."""

from __future__ import annotations

from google.protobuf import descriptor_pb2

from protokit.forensics._drift import drift
from protokit.storage.schema_source import FileDescriptorSetSchema
from tests.forensics.fixtures import fdp, msg_bytes, proto2_required_fdp
from tests.forensics.wire_ground_truth import typed_fdp
from tests.storage.proto_fixtures import fds

_F = descriptor_pb2.FieldDescriptorProto


def _src(file_proto: descriptor_pb2.FileDescriptorProto) -> FileDescriptorSetSchema:
    return FileDescriptorSetSchema(fds(file_proto), "a.A")


def _kinds(report: object) -> set[str]:
    return {d.kind for d in report.divergences}  # type: ignore[attr-defined]


def test_clean_message_has_no_divergences() -> None:
    schema = fdp({"x": 1, "y": 2})
    report = drift(msg_bytes(schema, {"x": 5, "y": 7}), _src(schema))
    assert report.divergences == ()
    assert report.observed_field_count == 2


def test_undeclared_tag_flagged() -> None:
    rich = fdp({"x": 1, "y": 5})
    poor = fdp({"x": 1})
    report = drift(msg_bytes(rich, {"x": 5, "y": 7}), _src(poor))
    assert "undeclared" in _kinds(report)
    assert any(d.field_number == 5 for d in report.divergences)


def test_wire_type_mismatch_flagged() -> None:
    as_string = typed_fdp({"x": (_F.TYPE_STRING, 1)})
    as_int = fdp({"x": 1})  # field 1 declared int32 (varint)
    data = msg_bytes(as_string, {"x": "hello"})  # field 1 on the wire is length-delimited
    report = drift(data, _src(as_int))
    assert "wire_type_mismatch" in _kinds(report)


def test_proto2_required_missing_flagged() -> None:
    optional_only = proto2_required_fdp(required={}, optional={"x": 1, "y": 2})
    required_x = proto2_required_fdp(required={"x": 1}, optional={"y": 2})
    report = drift(msg_bytes(optional_only, {"y": 7}), _src(required_x))
    assert "required_missing" in _kinds(report)
    assert any(d.field_number == 1 for d in report.divergences)


def test_packed_repeated_not_flagged_as_mismatch() -> None:
    schema = typed_fdp({"xs": (_F.TYPE_INT32, 1)}, repeated=frozenset({"xs"}))
    message = FileDescriptorSetSchema(fds(schema), "a.A").resolve().message_class()
    message.xs.extend([1, 2, 3])
    report = drift(message.SerializeToString(), _src(schema))
    assert report.divergences == ()


def test_reserved_tag_in_use_flagged() -> None:
    producer = fdp({"x": 1, "y": 2})
    reserved = fdp({"x": 1})
    reserved.message_type[0].reserved_range.add(start=2, end=3)  # reserve field 2
    report = drift(msg_bytes(producer, {"x": 5, "y": 7}), _src(reserved))
    assert "reserved_in_use" in _kinds(report)


def test_reserved_to_max_does_not_materialize() -> None:
    """A valid `reserved N to max` must not allocate a half-billion-int set (P1)."""
    producer = fdp({"x": 1, "y": 2})
    reserved = fdp({"x": 1})
    rng = reserved.message_type[0].reserved_range.add()
    rng.start, rng.end = 2, 536_870_912  # `reserved 2 to max;`
    report = drift(msg_bytes(producer, {"x": 5, "y": 7}), _src(reserved))  # must return fast
    assert "reserved_in_use" in _kinds(report)


def test_unpacked_repeated_undeclared_dedups_to_one_divergence() -> None:
    """An undeclared unpacked repeated field is ONE divergence, not one per element."""
    repeated = typed_fdp(
        {"xs": (_F.TYPE_INT32, 5)}, syntax="proto2", repeated=frozenset({"xs"})
    )
    message = FileDescriptorSetSchema(fds(repeated), "a.A").resolve().message_class()
    message.xs.extend([1, 2, 3, 4])  # 4 wire occurrences of field 5
    report = drift(message.SerializeToString(), _src(fdp({"x": 1})))  # field 5 undeclared
    undeclared = [d for d in report.divergences if d.kind == "undeclared"]
    assert len(undeclared) == 1  # collapsed per distinct field number
    assert report.observed_field_count == 1


def test_declared_extension_not_flagged_undeclared() -> None:
    # proto2 a.A { optional int32 x = 1; extensions 100 to 200; }
    # extend a.A { optional int32 ext_y = 100; }
    file_proto = descriptor_pb2.FileDescriptorProto(
        name="a.proto", package="a", syntax="proto2"
    )
    mt = file_proto.message_type.add()
    mt.name = "A"
    base = mt.field.add()
    base.name, base.number, base.type, base.label = "x", 1, _F.TYPE_INT32, _F.LABEL_OPTIONAL
    rng = mt.extension_range.add()
    rng.start, rng.end = 100, 200
    ext = file_proto.extension.add()
    ext.name, ext.number, ext.type, ext.label = "ext_y", 100, _F.TYPE_INT32, _F.LABEL_OPTIONAL
    ext.extendee = ".a.A"

    resolved = FileDescriptorSetSchema(fds(file_proto), "a.A").resolve()
    ext_fd = resolved.pool.FindExtensionByName("a.ext_y")
    message = resolved.message_class()
    message.Extensions[ext_fd] = 42  # populate the declared extension (field 100)

    report = drift(message.SerializeToString(), _src(file_proto))
    assert all(d.kind != "undeclared" for d in report.divergences)


def test_incompatible_occurrence_not_masked_by_a_compatible_one() -> None:
    """A wrong wire type on ONE occurrence is reported, even if another fits.

    Field 1 is declared ``int32`` (varint). Hand-built bytes carry it twice: once
    as a varint (compatible) and once as length-delimited (incompatible). A
    per-field ``any()`` compatibility test would let the good occurrence mask the
    bad one and report a clean message.
    """
    as_int = fdp({"x": 1})
    data = b"\x08\x05" + b"\x0a\x03abc"  # field 1 varint 5, then field 1 len-delimited
    report = drift(data, _src(as_int))
    assert "wire_type_mismatch" in _kinds(report)
    assert [d.field_number for d in report.divergences] == [1]
