"""U8 — walker-based tie-break in match + the compatibility discriminator it uses."""

from __future__ import annotations

from google.protobuf import descriptor_pb2

from protokit.forensics._drift import compatibility_score
from protokit.forensics._match import match
from protokit.forensics._wire import WireObservation
from tests.forensics.fixtures import candidate, cls_for, fdp
from tests.forensics.wire_ground_truth import typed_fdp

_F = descriptor_pb2.FieldDescriptorProto
_BYTES = _F.TYPE_BYTES
_I32 = _F.TYPE_INT32


def _bulky_message(
    schema: descriptor_pb2.FileDescriptorProto, blob_field: str, **scalars: int
) -> bytes:
    message = cls_for(schema)()
    setattr(message, blob_field, b"x" * 1000)
    for name, value in scalars.items():
        setattr(message, name, value)
    return message.SerializeToString()


def test_compatibility_score_prefers_the_fitting_schema() -> None:
    """The discriminator the tie-break uses ranks a declaring schema above one that doesn't."""
    observations = [WireObservation(1, 0), WireObservation(2, 0)]
    declares_both = cls_for(fdp({"x": 1, "y": 2})).DESCRIPTOR
    declares_one = cls_for(fdp({"x": 1})).DESCRIPTOR

    assert compatibility_score(observations, declares_both) == 2
    assert compatibility_score(observations, declares_one) == 0


def test_ambiguous_top_flagged_for_near_fractions() -> None:
    producer = typed_fdp({"blob": (_BYTES, 1), "a": (_I32, 2), "b": (_I32, 3)})
    data = _bulky_message(producer, "blob", a=1, b=1)
    near_a = candidate("a", typed_fdp({"blob": (_BYTES, 1), "a": (_I32, 2)}))
    near_b = candidate("b", typed_fdp({"blob": (_BYTES, 1)}))

    report = match(data, [near_a, near_b])

    assert report.ambiguous_top is True  # ~0.998 vs ~0.996, within the default margin


def test_ambiguous_top_not_flagged_for_far_fractions() -> None:
    producer = typed_fdp({"blob": (_BYTES, 1), "a": (_I32, 2)})
    data = _bulky_message(producer, "blob", a=1)
    full = candidate("full", typed_fdp({"blob": (_BYTES, 1), "a": (_I32, 2)}))  # 1.0
    poor = candidate("poor", typed_fdp({"a": (_I32, 2)}))  # blob unmodeled -> tiny fraction

    report = match(data, [full, poor])

    assert report.ambiguous_top is False


def test_symmetric_tie_remains_multiple_clean() -> None:
    """Two indistinguishable candidates: the walker confirms the tie, not a fake winner."""
    schema = fdp({"x": 1})
    data = cls_for(schema)()
    data.x = 5
    cands = [candidate("a", fdp({"x": 1})), candidate("b", fdp({"x": 1}))]
    report = match(data.SerializeToString(), cands)
    assert report.verdict == "multiple_clean_matches"


def test_tiebreak_is_deterministic_under_input_reordering() -> None:
    producer = typed_fdp({"blob": (_BYTES, 1), "a": (_I32, 2), "b": (_I32, 3)})
    data = _bulky_message(producer, "blob", a=1, b=1)
    a = candidate("a", typed_fdp({"blob": (_BYTES, 1), "a": (_I32, 2)}))
    b = candidate("b", typed_fdp({"blob": (_BYTES, 1)}))

    forward = match(data, [a, b])
    reversed_ = match(data, [b, a])

    assert [f.label for f in forward.ranked] == [f.label for f in reversed_.ranked]
