"""U3 — candidate resolution + single-message scalar fit."""

from __future__ import annotations

import pytest

from protokit._pools import DescriptorPoolError
from protokit.forensics import Candidate
from protokit.forensics._match import ParseTier, fit_candidate
from protokit.storage.schema_source import FileDescriptorSetSchema
from tests.forensics.fixtures import candidate, fdp, msg_bytes, proto2_required_fdp
from tests.storage.proto_fixtures import fds


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
