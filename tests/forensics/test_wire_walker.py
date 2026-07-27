"""U6 — the schema-less wire-format field walker + its ground-truth harness."""

from __future__ import annotations

import pytest
from google.protobuf import descriptor_pb2

from protokit.forensics._wire import (
    WIRETYPE_VARINT,
    WalkError,
    WireObservation,
    walk_top_level,
)
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


def test_nested_groups_record_outer_once() -> None:
    """A group nested inside a group: only the outer group + trailing field are top-level."""
    # group(1){ group(2){ field3=5 } }  then  field4=7
    data = b"\x0b" b"\x13" b"\x18\x05" b"\x14" b"\x0c" b"\x20\x07"
    assert walk_top_level(data) == [WireObservation(1, 3), WireObservation(4, 0)]


def test_mismatched_end_group_rejected() -> None:
    """A start-group closed by a different field number is malformed -> WalkError."""
    data = b"\x0b" b"\x14"  # start-group field 1, end-group field 2
    with pytest.raises(WalkError) as excinfo:
        walk_top_level(data)
    assert "mismatched end-group" in str(excinfo.value)


def test_undeclared_field_number_observed() -> None:
    """The walker reports any field number with its wire type, schema-free."""
    # field 99, varint, value 1  ->  tag = (99 << 3) | 0 = 792 = 0x98 0x06
    data = b"\x98\x06\x01"
    assert walk_top_level(data) == [WireObservation(99, 0)]


def _tag(field_number: int, wire_type: int) -> bytes:
    """Encode a raw ``(field_number, wire_type)`` tag as a varint — no schema needed."""
    value = (field_number << 3) | wire_type
    out = bytearray()
    while value > 0x7F:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def test_largest_legal_field_number_observed() -> None:
    """2**29 - 1 is protobuf's largest legal field number — the walker must accept it."""
    data = _tag(536_870_911, WIRETYPE_VARINT) + b"\x01"
    assert walk_top_level(data) == [WireObservation(536_870_911, 0)]


@pytest.mark.parametrize("field_number", [536_870_912, 2**35])
def test_field_number_above_the_legal_maximum_rejected(field_number: int) -> None:
    """A field number past 2**29 - 1 cannot come from any encoder; protobuf itself
    rejects these bytes (``DecodeError``), so reporting them as a real observation
    would put an impossible field number into a drift/match verdict."""
    data = _tag(field_number, WIRETYPE_VARINT) + b"\x01"
    with pytest.raises(WalkError) as excinfo:
        walk_top_level(data)
    assert "field number" in str(excinfo.value)


@pytest.mark.parametrize(
    "data, reason",
    [
        (b"\x80", "truncated varint"),  # continuation bit set, no next byte
        (b"\xff" * 10, "varint exceeds 64 bits"),  # 10th byte's low bits > 1
        (b"\xff" * 9 + b"\x81", "varint exceeds 64 bits"),  # 10th byte continuation set
        # A long all-continuation run still stops *at* the 10th byte — the reader
        # never consumes an 11th, so this exits through the same `consumed == max`
        # arm as the case above, not a separate `>` branch.
        (b"\x80" * 11, "varint exceeds 64 bits"),
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
