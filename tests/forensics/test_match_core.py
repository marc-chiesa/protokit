"""U3 — candidate resolution + single-message scalar fit."""

from __future__ import annotations

import pytest
from google.protobuf import descriptor_pb2

from protokit._pools import DescriptorPoolError
from protokit.forensics import Candidate, match
from protokit.forensics._match import ParseTier, fit_candidate
from protokit.storage.schema_source import FileDescriptorSetSchema
from tests.forensics.fixtures import candidate, fdp, msg_bytes, proto2_required_fdp
from tests.storage.proto_fixtures import encode_varint, fds


def test_clean_full_model() -> None:
    """A candidate that models every byte is the CLEAN tier, fraction 1.0."""
    schema = fdp({"x": 1, "y": 2})
    data = msg_bytes(schema, {"x": 5, "y": 7})

    fit = fit_candidate(data, candidate("full", schema))

    assert fit.tier is ParseTier.CLEAN
    assert fit.parse_outcome == "clean"
    assert fit.unmodeled_bytes == 0
    assert fit.modeled_fraction == 1.0
    assert fit.declared_field_coverage == 1.0


def test_unmodeled_under_poorer_schema() -> None:
    """Bytes from a richer producer leave unmodeled bytes under a poorer schema."""
    rich = fdp({"x": 1, "y": 2})
    poor = fdp({"x": 1})
    data = msg_bytes(rich, {"x": 5, "y": 7})

    fit = fit_candidate(data, candidate("old", poor))

    assert fit.tier is ParseTier.UNMODELED
    assert fit.parse_outcome == "unmodeled"
    assert fit.unmodeled_bytes is not None and fit.unmodeled_bytes > 0
    assert fit.modeled_fraction is not None and fit.modeled_fraction < 1.0


def test_superset_models_all_bytes_but_lower_coverage() -> None:
    """A superset models every byte (clean) yet exercises fewer declared fields."""
    exact = fdp({"x": 1})
    superset = fdp({"x": 1, "y": 2})
    data = msg_bytes(exact, {"x": 5})

    fit = fit_candidate(data, candidate("super", superset))

    assert fit.tier is ParseTier.CLEAN
    assert fit.unmodeled_bytes == 0
    assert fit.declared_field_coverage == 0.5  # 1 of 2 declared fields exercised


def test_proto2_missing_required_is_incomplete() -> None:
    """A proto2 candidate missing a declared required field cannot be measured."""
    optional_only = proto2_required_fdp(required={}, optional={"x": 1, "y": 2})
    required_x = proto2_required_fdp(required={"x": 1}, optional={"y": 2})
    data = msg_bytes(optional_only, {"y": 7})  # x absent

    fit = fit_candidate(data, candidate("v_required", required_x))

    assert fit.tier is ParseTier.FAULT
    assert fit.parse_outcome == "incomplete"
    assert fit.unmodeled_bytes is None
    assert fit.modeled_fraction is None
    assert fit.declared_field_coverage == 0.5  # y present of {x, y}


def test_malformed_bytes_caught_as_decode_error() -> None:
    """A message that does not parse under a candidate is a caught fault."""
    schema = fdp({"x": 1})
    # 0x08 is the tag for field 1 (varint) with no value byte — a truncated varint.
    fit = fit_candidate(b"\x08", candidate("v", schema))

    assert fit.tier is ParseTier.FAULT
    assert fit.parse_outcome == "decode_error"
    assert fit.detail is not None


def test_empty_message_is_clean_against_empty_schema() -> None:
    """A zero-byte message models cleanly; coverage is vacuously 1.0."""
    fit = fit_candidate(b"", candidate("v", fdp({})))

    assert fit.tier is ParseTier.CLEAN
    assert fit.modeled_fraction == 1.0
    assert fit.declared_field_coverage == 1.0


def test_resolution_error_propagates() -> None:
    """A candidate whose schema lacks the target type is a user error, not a fault."""
    bad = Candidate("wrong", FileDescriptorSetSchema(fds(fdp({"x": 1})), "a.Nope"))
    with pytest.raises(DescriptorPoolError):
        fit_candidate(b"", bad)


@pytest.mark.parametrize("location", ["top", "nested", "map_key", "group", "extension"])
def test_a_proto2_string_that_is_not_utf8_is_a_decode_error(location: str) -> None:
    """upb parses the record and returns bytes; the fit is a fault on both backends."""
    from tests import invalid_utf8

    cand = Candidate("u", FileDescriptorSetSchema(invalid_utf8.schema(), invalid_utf8.TYPE_NAME))
    fit = fit_candidate(invalid_utf8.BAD_PAYLOADS[location], cand)
    assert fit.tier is ParseTier.FAULT
    assert fit.parse_outcome == "decode_error"
    clean = fit_candidate(invalid_utf8.GOOD, cand)
    assert clean.parse_outcome != "decode_error"


# --- the fidelity-probe call -------------------------------------------------

_F = descriptor_pb2.FieldDescriptorProto


def _tree_fdp() -> descriptor_pb2.FileDescriptorProto:
    """proto3 ``a.A { repeated A children = 1; int32 x = 2; }``."""
    f = descriptor_pb2.FileDescriptorProto(name="a.proto", package="a", syntax="proto3")
    msg = f.message_type.add(name="A")
    msg.field.add(
        name="children", number=1, type=_F.TYPE_MESSAGE, label=_F.LABEL_REPEATED, type_name=".a.A"
    )
    msg.field.add(name="x", number=2, type=_F.TYPE_INT32, label=_F.LABEL_OPTIONAL)
    return f


def _nested_through_children(depth: int) -> bytes:
    """``x = 1`` wrapped in ``depth`` levels of the repeated ``children`` field."""
    data = b"\x10\x01"
    for _ in range(depth):
        data = b"\x0a" + encode_varint(len(data)) + data
    return data


def test_a_probe_that_overflows_the_stack_is_a_decode_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The message parsed, but measuring it ran out of stack: a fault, not a crash."""

    def overflow(message: object) -> int:
        raise RecursionError

    monkeypatch.setattr("protokit.forensics._match.unmodeled_byte_delta", overflow)
    schema = fdp({"x": 1})

    fit = fit_candidate(msg_bytes(schema, {"x": 5}), candidate("v", schema))

    assert fit.tier is ParseTier.FAULT
    assert fit.parse_outcome == "decode_error"
    assert fit.detail


def test_no_nesting_depth_through_a_repeated_field_raises() -> None:
    """Between the depth the probe can copy and the depth the parse refuses, too.

    The pure-Python runtime parses a message nested several hundred levels
    deep that the probe's copy then cannot walk. Where that band starts and
    ends moves with the caller's stack depth, so the sweep crosses all of it.
    """
    cand = candidate("tree", _tree_fdp())
    resolved = cand.source.resolve()

    outcomes = {
        depth: fit_candidate(_nested_through_children(depth), cand, resolved).parse_outcome
        for depth in range(60, 560, 8)
    }

    assert set(outcomes.values()) <= {"clean", "decode_error"}, outcomes


def test_a_type_error_from_the_probe_is_not_ranked_as_a_decode_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only a stack overflow is a property of the message; anything else propagates."""

    def broken(message: object) -> int:
        raise TypeError("'int' object is not callable")

    monkeypatch.setattr("protokit.forensics._match.unmodeled_byte_delta", broken)
    schema = fdp({"x": 1})

    with pytest.raises(TypeError):
        fit_candidate(msg_bytes(schema, {"x": 5}), candidate("v", schema))


def test_a_candidate_with_a_field_named_is_initialized_is_ranked() -> None:
    """Under upb the field's value hides the method the probe's gate calls."""
    plain = fdp({"x": 1, "y": 2})
    shadow = fdp({"x": 1, "IsInitialized": 2})
    data = msg_bytes(plain, {"x": 5, "y": 7})

    report = match(data, [candidate("plain", plain), candidate("shadow", shadow)])

    assert [(fit.label, fit.parse_outcome) for fit in report.ranked] == [
        ("plain", "clean"),
        ("shadow", "clean"),
    ]
    assert report.verdict == "multiple_clean_matches"
