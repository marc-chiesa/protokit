"""U6 — the schema-less wire-format field walker + its ground-truth harness."""

from __future__ import annotations

import pytest
from google.protobuf import descriptor_pb2

from protokit.forensics._wire import WalkError, WireObservation, walk_top_level
from tests.forensics.fixtures import cls_for
from tests.forensics.wire_ground_truth import assert_walker_recovers, typed_fdp

_F = descriptor_pb2.FieldDescriptorProto


def test_round_trip_recovers_mixed_wire_types() -> None:
    """Every wire type (varint / fixed64 / len / fixed32) round-trips through the walker."""
    schema = typed_fdp(
        {
            "a": (_F.TYPE_INT32, 1),  # varint
            "b": (_F.TYPE_STRING, 2),  # length-delimited
            "c": (_F.TYPE_SFIXED32, 3),  # fixed32
            "d": (_F.TYPE_FIXED64, 4),  # fixed64
            "e": (_F.TYPE_BYTES, 5),  # length-delimited
        }
    )
    assert_walker_recovers(
        cls_for(schema), {"a": 5, "b": "hi", "c": 7, "d": 9, "e": b"xy"}
    )


def test_packed_repeated_proto3_recovers() -> None:
    """A proto3 packed repeated scalar is observed once (length-delimited)."""
    schema = typed_fdp({"xs": (_F.TYPE_INT32, 1)}, repeated=frozenset({"xs"}))
    assert_walker_recovers(cls_for(schema), {"xs": [1, 2, 3]})


def test_unpacked_repeated_proto2_recovers() -> None:
    """A proto2 (unpacked) repeated scalar is observed once per element, same number."""
    schema = typed_fdp(
        {"xs": (_F.TYPE_INT32, 1)}, syntax="proto2", repeated=frozenset({"xs"})
    )
    assert_walker_recovers(cls_for(schema), {"xs": [1, 2, 3]})


def test_group_flagged_and_body_skipped() -> None:
    """A top-level group is flagged once; its inner fields are not recorded."""
    # group(field 1) { field 2 = 5 }  then  field 3 = 7
    data = b"\x0b" b"\x10\x05" b"\x0c" b"\x18\x07"
    assert walk_top_level(data) == [WireObservation(1, 3), WireObservation(3, 0)]


def test_undeclared_field_number_observed() -> None:
    """The walker reports any field number with its wire type, schema-free."""
    # field 99, varint, value 1  ->  tag = (99 << 3) | 0 = 792 = 0x98 0x06
    data = b"\x98\x06\x01"
    assert walk_top_level(data) == [WireObservation(99, 0)]


@pytest.mark.parametrize(
    "data, reason",
    [
        (b"\x80", "truncated varint"),  # continuation bit set, no next byte
        (b"\xff" * 10, "varint exceeds 64 bits"),  # 10th byte's low bits > 1
        (b"\x0a\x05ab", "length-delimited prefix exceeds"),  # declares 5, has 2
        (b"\x09\x00", "truncated fixed64"),  # wire type 1 needs 8 bytes
        (b"\x0d\x00", "truncated fixed32"),  # wire type 5 needs 4 bytes
        (b"\x00", "field number 0 is invalid"),  # tag 0
        (b"\x0b", "unterminated group"),  # start-group, no end
        (b"\x0c", "unexpected end-group"),  # end-group at top level
    ],
)
def test_malformed_inputs_raise_walk_error(data: bytes, reason: str) -> None:
    with pytest.raises(WalkError) as excinfo:
        walk_top_level(data)
    assert reason in str(excinfo.value)


def test_empty_buffer_has_no_observations() -> None:
    assert walk_top_level(b"") == []
