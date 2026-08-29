"""U6 — the schema-less wire-format field walker + its ground-truth harness."""

from __future__ import annotations

import pytest
from google.protobuf import descriptor_pb2

from protokit.forensics import _wire
from protokit.forensics._wire import (
    _MAX_GROUP_DEPTH,
    WIRETYPE_VARINT,
    WalkError,
    WireObservation,
    walk_top_level,
)
from protokit.forensics.cli import _DEFAULT_MAX_MESSAGE_BYTES
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


def test_group_nesting_at_the_depth_limit_is_accepted() -> None:
    """Nesting exactly at the cap still walks — the cap is protobuf's own limit."""
    # _MAX_GROUP_DEPTH nested start-groups (field 1), all closed, then field 2 = 7.
    data = b"\x0b" * _MAX_GROUP_DEPTH + b"\x0c" * _MAX_GROUP_DEPTH + b"\x10\x07"
    assert walk_top_level(data) == [WireObservation(1, 3), WireObservation(2, 0)]


def test_group_nesting_beyond_the_depth_limit_rejected() -> None:
    """One level past the cap is refused, even though the groups are all balanced.

    Without the bound the walk succeeds and the group stack grows with the input,
    so an attacker's tags — not the byte cap — set the memory ceiling.
    """
    depth = _MAX_GROUP_DEPTH + 1
    data = b"\x0b" * depth + b"\x0c" * depth
    with pytest.raises(WalkError) as excinfo:
        walk_top_level(data)
    assert "group nesting depth" in str(excinfo.value)


def test_deep_start_group_run_fails_on_depth_not_after_the_whole_buffer() -> None:
    """A start-group flood is refused at the cap, not after the buffer is consumed.

    This is the amplification path the observation ceiling cannot see: every tag
    pushes onto the group stack while ``observations`` stays empty, so the walk
    must stop on depth rather than run the input out and report an unterminated
    group.
    """
    with pytest.raises(WalkError) as excinfo:
        walk_top_level(b"\x0b" * 100_000)
    assert "group nesting depth" in str(excinfo.value)


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


# ---------------------------------------------------------------------------
# Cost ceilings — the walk's memory bound, not its logic
# ---------------------------------------------------------------------------


class TestObservationCeiling:
    """``_MAX_OBSERVATIONS`` must be an enforced bound, not a decorative constant.

    Two tests, because the two ways this protection dies need different proofs
    and neither may allocate anything large:

    * delete the guard   -> the behavioural test catches it
    * neuter the constant -> the bound test catches it

    A single test written relative to the constant (``_MAX_OBSERVATIONS + 1``
    inputs, the shape the group-depth tests above can afford) would catch
    neither safely: at the real default it needs ten million tags, and against a
    neutered constant it would try to build 10**30 of them and die by
    MemoryError inside the harness rather than by assertion.
    """

    def test_guard_fires_once_the_ceiling_is_exceeded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Behavioural half: patch the ceiling low, prove the walk refuses."""
        monkeypatch.setattr(_wire, "_MAX_OBSERVATIONS", 3)
        data = b"\x08\x01" * 4  # 4 top-level varint fields, ceiling is 3
        with pytest.raises(WalkError) as excinfo:
            walk_top_level(data)
        assert "top-level fields" in str(excinfo.value)

    def test_at_the_ceiling_is_still_accepted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The bound is exclusive: exactly at the ceiling still walks."""
        monkeypatch.setattr(_wire, "_MAX_OBSERVATIONS", 3)
        assert len(walk_top_level(b"\x08\x01" * 3)) == 3

    def test_default_ceiling_actually_binds(self) -> None:
        """Bound half: the default must be tighter than the byte cap alone.

        The ceiling exists because ``--max-message-bytes`` does not bound
        memory: a one-byte tag becomes a ~35-byte observation, so a maximal
        message of nothing but tags amplifies. The ceiling is only doing work
        if it is reached *before* the byte cap is — expressed against the byte
        cap rather than as a magic number, so ordinary tuning is free and
        neutering is not.
        """
        max_tags_within_the_byte_cap = _DEFAULT_MAX_MESSAGE_BYTES  # 1-byte tags
        assert 0 < _wire._MAX_OBSERVATIONS < max_tags_within_the_byte_cap
