"""Regression pins for audit family U9 — compat rule gaps (2026-08-30 audit).

Three CONFIRMED findings in which ``protokit compat`` reports COMPATIBLE
over a schema change that genuinely breaks readers. Every pin here is a
``@pytest.mark.xfail(strict=True)``: the assertion states the outcome a
correct implementation must produce, the test fails today because the gap
is live, and it flips to a loud XPASS the day the gap is closed.

Shared root cause for U9-1 and U9-2
-----------------------------------
``rules.options_changed`` (``rules.py:630-635``) is the only built-in rule
that could plausibly notice either change — every other field rule keys off
type, number, cardinality, presence or oneof membership — and its entire
mechanism is::

    old_fd.GetOptions().SerializeToString() != new_fd.GetOptions().SerializeToString()

But ``default_value``, ``json_name`` and ``label`` are members of
``FieldDescriptorProto``, not of ``FieldOptions``. They can never appear in
those serialized bytes, so no options-bytes diff — however strict the
profile — can observe them changing. ``TestOptionsBytesCannotSeeDescriptorAttributes``
below pins that mechanism directly; the xfail pins record the user-visible
consequence.

U9-3 is a different mechanism (wire-group classification) recorded here
because the audit filed it in the same family; see its own pin.
"""

from __future__ import annotations

import pytest
from google.protobuf import descriptor_pb2, descriptor_pool, json_format, message_factory
from google.protobuf.message import DecodeError

from protokit.message.model import FieldPath
from protokit.schema import CompatibilityLevel, check_compatibility
from protokit.schema.rules import options_changed
from tests.schema.helpers import T, build_message


ROOT = FieldPath(segments=())

#: The wrong outcome these pins record: every profile — including STRICT,
#: which by construction retains every severity and every direction — sees
#: nothing at all.
NO_FINDINGS_AT_ANY_LEVEL = {level.name: () for level in CompatibilityLevel}


def _rule_ids_by_level(
    old: descriptor_pool.DescriptorPool,
    new: descriptor_pool.DescriptorPool,
    type_name: str = "t.M",
) -> dict[str, tuple[str, ...]]:
    """Return ``{level name: rule ids}`` for all four compatibility profiles."""
    return {
        level.name: tuple(
            f.rule_id
            for f in check_compatibility(old, type_name, new, type_name, level=level).findings
        )
        for level in CompatibilityLevel
    }


def _two_pools(
    old_field: dict,
    new_field: dict,
    *,
    syntax: str = "proto3",
) -> tuple[descriptor_pool.DescriptorPool, descriptor_pool.DescriptorPool]:
    """Build ``t.M`` into two fresh pools from one field spec each."""
    old = descriptor_pool.DescriptorPool()
    new = descriptor_pool.DescriptorPool()
    build_message(old, "t.M", fields=[old_field], syntax=syntax)
    build_message(new, "t.M", fields=[new_field], syntax=syntax)
    return old, new


def _field(pool: descriptor_pool.DescriptorPool, name: str = "x"):
    return pool.FindMessageTypeByName("t.M").fields_by_name[name]


def _message_class(pool: descriptor_pool.DescriptorPool):
    return message_factory.GetMessageClass(pool.FindMessageTypeByName("t.M"))


# ---------------------------------------------------------------------------
# Mechanism — why an options-bytes diff is structurally blind here
#
# These are facts about protobuf's own descriptor schema and about
# ``options_changed``'s stated contract, not about the gap. They stay true
# after U9-1/U9-2 are fixed (the fix has to compare descriptor attributes
# directly; it cannot make these attributes appear in FieldOptions).
# ---------------------------------------------------------------------------


class TestOptionsBytesCannotSeeDescriptorAttributes:
    def test_field_options_has_no_default_value_json_name_or_label_member(self) -> None:
        """The three attributes live on FieldDescriptorProto, not FieldOptions."""
        option_members = set(descriptor_pb2.FieldOptions.DESCRIPTOR.fields_by_name)
        field_members = set(descriptor_pb2.FieldDescriptorProto.DESCRIPTOR.fields_by_name)
        for attribute in ("default_value", "json_name", "label"):
            assert attribute not in option_members
            assert attribute in field_members

    def test_default_value_change_leaves_serialized_options_identical(self) -> None:
        old, new = _two_pools(
            {"name": "x", "number": 1, "type": T.TYPE_INT32, "default_value": "1"},
            {"name": "x", "number": 1, "type": T.TYPE_INT32, "default_value": "2"},
            syntax="proto2",
        )
        old_fd, new_fd = _field(old), _field(new)
        assert (old_fd.default_value, new_fd.default_value) == (1, 2)
        assert old_fd.GetOptions().SerializeToString() == new_fd.GetOptions().SerializeToString()
        assert options_changed(old_fd, new_fd, ROOT) == []

    def test_json_name_change_leaves_serialized_options_identical(self) -> None:
        old, new = _two_pools(
            {"name": "x", "number": 1, "type": T.TYPE_INT32, "json_name": "oldX"},
            {"name": "x", "number": 1, "type": T.TYPE_INT32, "json_name": "newX"},
        )
        old_fd, new_fd = _field(old), _field(new)
        assert (old_fd.json_name, new_fd.json_name) == ("oldX", "newX")
        assert old_fd.GetOptions().SerializeToString() == new_fd.GetOptions().SerializeToString()
        assert options_changed(old_fd, new_fd, ROOT) == []


# ---------------------------------------------------------------------------
# Data hazards — what the silent verdicts cost a reader
#
# Protobuf-runtime facts, independent of protokit; they establish that each
# pinned change is a real break rather than a taxonomy quibble.
# ---------------------------------------------------------------------------


class TestDataHazards:
    def test_identical_wire_bytes_decode_to_different_values_after_default_change(self) -> None:
        """One byte string, two readings — the U9-1 hazard in executable form."""
        old, new = _two_pools(
            {"name": "x", "number": 1, "type": T.TYPE_INT32, "default_value": "1"},
            {"name": "x", "number": 1, "type": T.TYPE_INT32, "default_value": "2"},
            syntax="proto2",
        )
        old_msg, new_msg = _message_class(old)(), _message_class(new)()
        wire = old_msg.SerializeToString()
        assert wire == b""
        old_msg.ParseFromString(wire)
        new_msg.ParseFromString(wire)
        assert (old_msg.x, new_msg.x) == (1, 2)

    def test_json_payloads_do_not_round_trip_across_a_json_name_change(self) -> None:
        """The U9-2 hazard: JSON hard-fails in *both* directions."""
        old, new = _two_pools(
            {"name": "x", "number": 1, "type": T.TYPE_INT32, "json_name": "oldX"},
            {"name": "x", "number": 1, "type": T.TYPE_INT32, "json_name": "newX"},
        )
        old_cls, new_cls = _message_class(old), _message_class(new)
        with pytest.raises(json_format.ParseError, match="newX"):
            json_format.Parse(json_format.MessageToJson(new_cls(x=7)), old_cls())
        with pytest.raises(json_format.ParseError, match="oldX"):
            json_format.Parse(json_format.MessageToJson(old_cls(x=7)), new_cls())

    def test_non_utf8_bytes_payload_fails_to_decode_as_string(self) -> None:
        """The U9-3 hazard: a bytes->string change can crash deserialization."""
        old, new = _two_pools(
            {"name": "x", "number": 1, "type": T.TYPE_BYTES},
            {"name": "x", "number": 1, "type": T.TYPE_STRING},
        )
        wire = _message_class(old)(x=b"\xff\xfe\x00\x80").SerializeToString()
        assert wire == b"\n\x04\xff\xfe\x00\x80"
        with pytest.raises((DecodeError, UnicodeDecodeError)):
            _message_class(new)().ParseFromString(wire)


# ---------------------------------------------------------------------------
# U9-1 — proto2 default_value changes are invisible at every level
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "U9-1: proto2 [default=1] -> [default=2] reports COMPATIBLE at every level "
        "(WIRE, CONSUMER_SAFE, PRODUCER_SAFE, STRICT) with zero findings; "
        "default_value is a FieldDescriptorProto member, so the options-bytes diff "
        "in rules.options_changed cannot see it"
    ),
)
@pytest.mark.parametrize(
    ("label", "old_extra", "new_extra", "ftype"),
    [
        ("changed_int", {"default_value": "1"}, {"default_value": "2"}, T.TYPE_INT32),
        ("added", {}, {"default_value": "99"}, T.TYPE_INT32),
        ("removed", {"default_value": "7"}, {}, T.TYPE_INT32),
        ("changed_string", {"default_value": "alpha"}, {"default_value": "beta"}, T.TYPE_STRING),
    ],
    ids=["changed_int", "added", "removed", "changed_string"],
)
def test_proto2_default_value_change_is_reported_at_some_level(
    label: str,
    old_extra: dict,
    new_extra: dict,
    ftype: int,
) -> None:
    """A proto2 ``default_value`` edit changes what absent fields mean.

    Data hazard: the wire bytes are unchanged — for an unset optional
    field they are ``b""`` in both schemas — yet the two schemas decode
    those identical bytes to different application values (old reads
    ``x == 1``, new reads ``x == 2``). Nothing on the wire signals the
    divergence, so a rollout that lands the new schema on some readers
    and not others silently splits the meaning of every message that
    omits the field.

    Every one of the four flavors below (changed / added / removed /
    string default) is silent at all four profiles today.
    """
    base = {"name": "x", "number": 1, "type": ftype}
    old, new = _two_pools({**base, **old_extra}, {**base, **new_extra}, syntax="proto2")

    by_level = _rule_ids_by_level(old, new)

    assert by_level != NO_FINDINGS_AT_ANY_LEVEL, (
        f"default_value {label}: a breaking change went unreported by every "
        f"compatibility profile, STRICT included -> {by_level}"
    )


# ---------------------------------------------------------------------------
# U9-2 — json_name changes are invisible at every level
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "U9-2: json_name change (oldX -> newX) reports COMPATIBLE at every level "
        "(WIRE, CONSUMER_SAFE, PRODUCER_SAFE, STRICT) with zero findings; "
        "json_name is a FieldDescriptorProto member, so the options-bytes diff "
        "in rules.options_changed cannot see it"
    ),
)
@pytest.mark.parametrize(
    ("label", "old_field", "new_field"),
    [
        (
            "renamed",
            {"name": "x", "number": 1, "type": T.TYPE_INT32, "json_name": "oldX"},
            {"name": "x", "number": 1, "type": T.TYPE_INT32, "json_name": "newX"},
        ),
        # The realistic one-line edit: annotating a previously unannotated
        # field, which overrides protobuf's derived "userId" with "id".
        (
            "annotated",
            {"name": "user_id", "number": 1, "type": T.TYPE_INT32},
            {"name": "user_id", "number": 1, "type": T.TYPE_INT32, "json_name": "id"},
        ),
    ],
    ids=["renamed", "annotated"],
)
def test_json_name_change_is_reported_at_some_level(
    label: str,
    old_field: dict,
    new_field: dict,
) -> None:
    """A ``json_name`` edit breaks JSON interchange in both directions.

    Data hazard: the binary wire format is untouched, so a wire-level
    reading of the change is "compatible" — but JSON is a first-class
    protobuf encoding and it hard-fails. An old reader given the new
    schema's ``{"newX": 7}`` raises ``ParseError: ... has no field named
    "newX"``, and a new reader given ``{"oldX": 7}`` raises the mirror
    image (see ``TestDataHazards``). Every REST/JSON consumer of the
    message breaks, in both directions, with no finding at any profile.
    """
    old, new = _two_pools(old_field, new_field)

    by_level = _rule_ids_by_level(old, new)

    assert by_level != NO_FINDINGS_AT_ANY_LEVEL, (
        f"json_name {label}: a breaking change went unreported by every "
        f"compatibility profile, STRICT included -> {by_level}"
    )


# ---------------------------------------------------------------------------
# U9-3 — bytes -> string is excluded from the WIRE profile
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "U9-3: bytes -> string reports COMPATIBLE with zero findings at the WIRE "
        "profile even though a non-UTF-8 payload from an old producer raises "
        "DecodeError in a new consumer; string<->bytes share the "
        "_WIRE_LENGTH_BYTES group, so the change is classified SEMANTIC and only "
        "surfaces from CONSUMER_SAFE upward"
    ),
)
def test_bytes_to_string_is_reported_at_the_wire_profile() -> None:
    """``bytes`` -> ``string`` can crash deserialization, which is WIRE severity.

    This is the *narrow* claim, and it is narrower than U9-1/U9-2: the
    change is not invisible everywhere. CONSUMER_SAFE, PRODUCER_SAFE and
    STRICT all report ``field_type_semantic_change`` (SEMANTIC/BOTH). Only
    the WIRE profile is silent — and WIRE is the profile documented to
    answer "will deserialization crash?" (``CompatibilityLevel`` docstring)
    with ``Severity.WIRE`` documented as "bytes on the wire cannot be
    decoded by the other schema version".

    Data hazard: they can't. An old producer's ``bytes`` field carries
    arbitrary octets — a hash digest, a compressed blob — and a new
    ``string``-typed consumer parsing those exact bytes raises
    ``DecodeError`` (see ``TestDataHazards``). A CI gate pinned to
    ``--level WIRE`` passes the change with exit 0.

    The asymmetry is deliberate and this pin respects it: only the
    ``bytes -> string`` direction can fail to decode (a ``string``
    producer emits valid UTF-8, which is always valid ``bytes``), so
    nothing here demands a WIRE finding for ``string -> bytes``.
    """
    old, new = _two_pools(
        {"name": "x", "number": 1, "type": T.TYPE_BYTES},
        {"name": "x", "number": 1, "type": T.TYPE_STRING},
    )

    by_level = _rule_ids_by_level(old, new)

    # Control: this is a WIRE-profile-only miss, not a total miss. If this
    # ever goes empty the pin is measuring the wrong thing.
    assert by_level["STRICT"] != (), f"expected the type change to surface at STRICT -> {by_level}"

    assert by_level["WIRE"] != (), (
        "bytes -> string can raise DecodeError, but the WIRE profile reported "
        f"zero findings -> {by_level}"
    )
