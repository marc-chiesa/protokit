"""Regression pins for audit family U9 — compat rule gaps (2026-08-30 audit).

Three CONFIRMED findings in which ``protokit compat`` reports COMPATIBLE
over a schema change that genuinely breaks readers. Every pin here is a
``@pytest.mark.xfail(strict=True)``: the assertion states the outcome a
correct implementation must produce, the test fails today because the gap
is live, and it flips to a loud XPASS the day the gap is closed.

Shared root cause for U9-1 and U9-2
-----------------------------------
``rules.options_changed`` (in ``schema/rules.py``) is the only built-in rule
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

The 0.16.0 re-audit section at the end of the file pins five more rule gaps
the same way (V21, V22 and its extension analogue, R14-C2b, and the R16-C1
rename facet). Its comment block gives each one's mechanism.
"""

from __future__ import annotations

import pytest
from google.protobuf import descriptor_pb2, descriptor_pool, json_format, message_factory
from google.protobuf.message import DecodeError, EncodeError

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
    raises=AssertionError,
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
    raises=AssertionError,
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
    raises=AssertionError,
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


# ---------------------------------------------------------------------------
# 0.16.0 re-audit — five more rule gaps, all owned by U4 (0.18.0)
#
# Every pin below is strict, names ``raises=AssertionError``, leads its reason
# with the finding ID and flips to a loud XPASS the day its gap is closed.
# Each has a passing control built by the same helper, and the hazard behind
# each is in ``TestNumberAndLabelDataHazards``.
#
# V21      A surviving field that becomes ``required`` is silent at every
#          level: ``rules.required_field_added`` examines only a field the old
#          schema lacks, and no rule compares the two sides' requiredness.
# R14-C2b  The two mirrors V21 does not cover. ``required`` -> ``optional`` is
#          silent at every level for the same reason, and removing a
#          ``required`` field is only ``field_removed`` (SEMANTIC/BACKWARD), so
#          the WIRE profile passes it.
# V22      Fields are paired by name, so a number rebound to a different field
#          reads as one ``field_removed`` plus one ``field_added`` (both
#          SEMANTIC/BACKWARD). No rule sees the two as a pair, and WIRE and
#          PRODUCER_SAFE report nothing.
# V22 (extension analogue)
#          Extensions are paired by their ``(pkg.ext)`` key, so a new extension
#          that takes an old extension's number gets the same add-plus-remove
#          reading and the same two silent profiles.
# R16-C1 (rename facet)
#          A message field renamed at its number is also an add plus a remove,
#          and the checker descends only into a name-paired field, so a wire
#          break inside the field's message type is reported at no level.
# ---------------------------------------------------------------------------

#: proto2 spells ``required`` as a label; edition 2023 spells it
#: ``features.field_presence = LEGACY_REQUIRED``. The label pins run on both.
_BOTH_SPELLINGS_OF_REQUIRED = pytest.mark.parametrize(
    "editions", [False, True], ids=["proto2", "editions"]
)


def _x_pool(x: str, *, editions: bool) -> descriptor_pool.DescriptorPool:
    """Build ``t.M`` holding ``string note = 2`` and ``int32 x = 1`` declared as ``x`` says.

    ``x`` is ``"optional"``, ``"required"``, ``"repeated"`` or ``"absent"``.
    """
    fdp = descriptor_pb2.FileDescriptorProto(name="x.proto", package="t", syntax="proto2")
    if editions:
        fdp.syntax = "editions"
        fdp.edition = descriptor_pb2.EDITION_2023
    m = fdp.message_type.add(name="M")
    m.field.add(name="note", number=2, type=T.TYPE_STRING, label=T.LABEL_OPTIONAL)
    if x != "absent":
        fd = m.field.add(name="x", number=1, type=T.TYPE_INT32, label=T.LABEL_OPTIONAL)
        if x == "repeated":
            fd.label = T.LABEL_REPEATED
        elif x == "required" and editions:
            fd.options.features.field_presence = descriptor_pb2.FeatureSet.LEGACY_REQUIRED
        elif x == "required":
            fd.label = T.LABEL_REQUIRED
    pool = descriptor_pool.DescriptorPool()
    pool.Add(fdp)
    return pool


def _spec(name: str, ftype: int, number: int = 1) -> dict:
    return {"name": name, "number": number, "type": ftype}


def _two_extension_pools(
    old_ext: dict,
    new_ext: dict,
) -> tuple[descriptor_pool.DescriptorPool, descriptor_pool.DescriptorPool]:
    """Build proto2 ``t.M`` (``extensions 1 to 199;``) with one ``extend t.M`` each."""
    pools = []
    for spec in (old_ext, new_ext):
        fdp = descriptor_pb2.FileDescriptorProto(name="ext.proto", package="t", syntax="proto2")
        fdp.message_type.add(name="M").extension_range.add(start=1, end=200)
        fdp.extension.add(extendee=".t.M", label=T.LABEL_OPTIONAL, **spec)
        pool = descriptor_pool.DescriptorPool()
        pool.Add(fdp)
        pools.append(pool)
    return pools[0], pools[1]


def _address_pool(field_name: str, zip_type: int) -> descriptor_pool.DescriptorPool:
    """Build ``t.M { Address <field_name> = 1; }`` over ``t.Address { <zip_type> zip = 1; }``."""
    pool = descriptor_pool.DescriptorPool()
    build_message(pool, "t.Address", fields=[_spec("zip", zip_type)])
    build_message(
        pool,
        "t.M",
        fields=[{**_spec(field_name, T.TYPE_MESSAGE), "type_name": ".t.Address"}],
    )
    return pool


def _rule_ids_at_leaf(
    old: descriptor_pool.DescriptorPool,
    new: descriptor_pool.DescriptorPool,
    leaf: str,
) -> dict[str, tuple[str, ...]]:
    """Return ``{level name: rule ids}`` for the findings whose path ends in ``leaf``."""
    return {
        level.name: tuple(
            f.rule_id
            for f in check_compatibility(old, "t.M", new, "t.M", level=level).findings
            if [segment.name for segment in f.path.segments[-1:]] == [leaf]
        )
        for level in CompatibilityLevel
    }


#: One number, two different fields: ``(label, old field, new field)``.
#: ``same_type`` is the 2026-08-30 audit's own V22 reproduction; by descriptor
#: alone it is indistinguishable from a rename. The other two change what the
#: old bytes mean: ``zigzag`` reads an old ``-3`` as ``5``, and ``wire_type``
#: drops an old ``"secret"`` and reads ``0``.
_NUMBER_REUSE = [
    ("same_type", _spec("old_a", T.TYPE_STRING), _spec("new_b", T.TYPE_STRING)),
    ("zigzag", _spec("price_cents", T.TYPE_SINT64), _spec("quantity", T.TYPE_INT64)),
    ("wire_type", _spec("email", T.TYPE_STRING), _spec("age", T.TYPE_INT64)),
]
_NUMBER_REUSE_IDS = [label for label, _, _ in _NUMBER_REUSE]

#: The controls for ``_NUMBER_REUSE``: the name is kept, so the pair is seen.
#: ``(label, old field, new field, rule id reported at every level)``.
_NAME_KEPT = [
    (
        "renumbered",
        _spec("email", T.TYPE_STRING),
        _spec("email", T.TYPE_STRING, number=2),
        "field_number_changed",
    ),
    (
        "zigzag",
        _spec("price_cents", T.TYPE_SINT64),
        _spec("price_cents", T.TYPE_INT64),
        "field_type_wire_incompatible",
    ),
    (
        "wire_type",
        _spec("email", T.TYPE_STRING),
        _spec("email", T.TYPE_INT64),
        "field_type_wire_incompatible",
    ),
]
_NAME_KEPT_IDS = [label for label, _, _, _ in _NAME_KEPT]


def _silent_levels(by_level: dict[str, tuple[str, ...]], *levels: str) -> list[str]:
    """Return the names in ``levels`` (default: all four) that reported nothing."""
    return [name for name in (levels or tuple(by_level)) if by_level[name] == ()]


class TestNumberAndLabelDataHazards:
    """Protobuf-runtime facts: what each change pinned below costs a reader."""

    @_BOTH_SPELLINGS_OF_REQUIRED
    def test_old_message_cannot_be_reserialized_once_its_field_is_required(
        self, editions: bool
    ) -> None:
        """The V21 hazard: old data is uninitialized under the new schema."""
        old = _message_class(_x_pool("optional", editions=editions))(note="n")
        new = _message_class(_x_pool("required", editions=editions))()
        new.ParseFromString(old.SerializeToString())
        assert not new.IsInitialized()
        with pytest.raises(EncodeError, match="missing required fields: x"):
            new.SerializeToString()

    @_BOTH_SPELLINGS_OF_REQUIRED
    @pytest.mark.parametrize("new_x", ["optional", "absent"])
    def test_old_consumer_holds_an_uninitialized_message_once_the_field_is_not_required(
        self, new_x: str, editions: bool
    ) -> None:
        """The R14-C2b hazard: a new producer may omit what an old consumer requires."""
        new = _message_class(_x_pool(new_x, editions=editions))(note="n")
        old = _message_class(_x_pool("required", editions=editions))()
        old.ParseFromString(new.SerializeToString())
        assert not old.IsInitialized()

    def test_old_bytes_decode_as_the_field_that_took_the_number(self) -> None:
        """The V22 hazard: an old ``sint64 -3`` is a new ``int64 5``."""
        old, new = _two_pools(
            _spec("price_cents", T.TYPE_SINT64), _spec("quantity", T.TYPE_INT64)
        )
        wire = _message_class(old)(price_cents=-3).SerializeToString()
        assert _message_class(new).FromString(wire).quantity == 5

    def test_old_bytes_decode_as_the_extension_that_took_the_number(self) -> None:
        """The same hazard for an extension number."""
        old, new = _two_extension_pools(
            _spec("price_cents", T.TYPE_SINT64), _spec("quantity", T.TYPE_INT64)
        )
        old_msg = _message_class(old)()
        old_msg.Extensions[old.FindExtensionByName("t.price_cents")] = -3
        new_msg = _message_class(new).FromString(old_msg.SerializeToString())
        assert new_msg.Extensions[new.FindExtensionByName("t.quantity")] == 5

    def test_renamed_message_field_still_carries_the_nested_misread(self) -> None:
        """The R16-C1 hazard: the rename changes no bytes, so the nested break is live."""
        old_msg = _message_class(_address_pool("address", T.TYPE_STRING))()
        old_msg.address.zip = "94110"
        new_cls = _message_class(_address_pool("home_address", T.TYPE_DOUBLE))
        new_msg = new_cls.FromString(old_msg.SerializeToString())
        assert new_msg.HasField("home_address")
        assert new_msg.home_address.zip == 0.0


# ---------------------------------------------------------------------------
# V21 and R14-C2b — a surviving field's ``required`` label is never compared
# ---------------------------------------------------------------------------


@_BOTH_SPELLINGS_OF_REQUIRED
def test_adding_a_required_field_is_reported_at_wire_and_strict_control(editions: bool) -> None:
    """Control for V21 and R14-C2b: ``required`` is seen on a field the old schema lacks."""
    by_level = _rule_ids_by_level(
        _x_pool("absent", editions=editions), _x_pool("required", editions=editions)
    )

    assert by_level == {
        "WIRE": ("required_field_added",),
        "CONSUMER_SAFE": (),
        "PRODUCER_SAFE": ("required_field_added",),
        "STRICT": ("required_field_added",),
    }


@_BOTH_SPELLINGS_OF_REQUIRED
def test_optional_to_repeated_label_change_is_reported_at_every_level_control(
    editions: bool,
) -> None:
    """Control for V21 and R14-C2b: a label change on a surviving field is seen."""
    by_level = _rule_ids_by_level(
        _x_pool("optional", editions=editions), _x_pool("repeated", editions=editions)
    )

    for level_name, rule_ids in by_level.items():
        assert "repeated_to_singular" in rule_ids, (level_name, by_level)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "V21: owned by U4 (0.18.0). optional -> required on a surviving field reports "
        "COMPATIBLE with zero findings at every level, STRICT included; "
        "rules.required_field_added examines only a field the old schema lacks"
    ),
)
@_BOTH_SPELLINGS_OF_REQUIRED
def test_optional_to_required_is_reported_at_strict(editions: bool) -> None:
    """Making an existing field ``required`` strands every message that omits it.

    Data hazard: an old producer never had to set the field. A new consumer
    parses such a message into an uninitialized object and cannot serialize
    it again (``EncodeError: ... missing required fields``); runtimes that
    check on parse reject it outright. Adding the same ``required`` field
    fresh is WIRE/FORWARD (see the control); only the already-present case
    is unexamined.
    """
    by_level = _rule_ids_by_level(
        _x_pool("optional", editions=editions), _x_pool("required", editions=editions)
    )

    assert by_level["STRICT"] != (), (
        "optional -> required went unreported by every compatibility profile, "
        f"STRICT included -> {by_level}"
    )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "R14-C2b: owned by U4 (0.18.0). required -> optional on a surviving field "
        "reports COMPATIBLE with zero findings at every level, STRICT included; "
        "no rule compares the two sides' labels for requiredness"
    ),
)
@_BOTH_SPELLINGS_OF_REQUIRED
def test_required_to_optional_is_reported_at_strict(editions: bool) -> None:
    """Relaxing ``required`` lets a new producer omit what old consumers demand.

    Data hazard: the mirror of V21. A message written under the new schema
    without the field is uninitialized for every consumer still on the old
    one.
    """
    by_level = _rule_ids_by_level(
        _x_pool("required", editions=editions), _x_pool("optional", editions=editions)
    )

    assert by_level["STRICT"] != (), (
        "required -> optional went unreported by every compatibility profile, "
        f"STRICT included -> {by_level}"
    )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "R14-C2b: owned by U4 (0.18.0). Removing a required field reports COMPATIBLE "
        "with zero findings at the WIRE profile; it is only field_removed "
        "(SEMANTIC/BACKWARD), although every message a new producer writes is "
        "uninitialized for an old consumer"
    ),
)
@_BOTH_SPELLINGS_OF_REQUIRED
def test_removing_a_required_field_is_reported_at_the_wire_profile(editions: bool) -> None:
    """Removing a ``required`` field breaks old consumers as adding one breaks new ones.

    This is a WIRE-profile miss, not a total one: CONSUMER_SAFE and STRICT
    report ``field_removed``. The same removal of an ``optional`` field gets
    the identical finding, so nothing marks the ``required`` case as the one
    old consumers cannot accept.
    """
    by_level = _rule_ids_by_level(
        _x_pool("required", editions=editions), _x_pool("absent", editions=editions)
    )

    # Control: the removal is visible where SEMANTIC findings are kept.
    assert _silent_levels(by_level, "CONSUMER_SAFE", "STRICT") == [], by_level

    assert by_level["WIRE"] != (), (
        f"removing a required field passed the WIRE profile with zero findings -> {by_level}"
    )


# ---------------------------------------------------------------------------
# V22 and its extension analogue — a reused number is an add plus a remove
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("as_extension", [False, True], ids=["field", "extension"])
@pytest.mark.parametrize(
    ("label", "old_field", "new_field", "rule_id"), _NAME_KEPT, ids=_NAME_KEPT_IDS
)
def test_number_binding_change_under_a_kept_name_is_reported_at_every_level_control(
    label: str,
    old_field: dict,
    new_field: dict,
    rule_id: str,
    as_extension: bool,
) -> None:
    """Control for both V22 pins: what a number is bound to is WIRE once the name pairs."""
    build = _two_extension_pools if as_extension else _two_pools

    by_level = _rule_ids_by_level(*build(old_field, new_field))

    assert by_level == {level.name: (rule_id,) for level in CompatibilityLevel}, label


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "V22: owned by U4 (0.18.0). A field number reused by a different field reports "
        "COMPATIBLE with zero findings at WIRE and PRODUCER_SAFE; fields pair by name, "
        "so the change is one field_removed plus one field_added (both "
        "SEMANTIC/BACKWARD) and no rule sees the number's two bindings as a pair"
    ),
)
@pytest.mark.parametrize(("label", "old_field", "new_field"), _NUMBER_REUSE, ids=_NUMBER_REUSE_IDS)
def test_field_number_reuse_is_reported_at_wire_and_producer_safe(
    label: str,
    old_field: dict,
    new_field: dict,
) -> None:
    """Rebinding a field number sends old bytes into a field they were not written for.

    Data hazard: the wire carries numbers, not names. Bytes an old producer
    wrote for the old field decode under the new schema as the new field: an
    old ``sint64 price_cents = -3`` reads as ``int64 quantity = 5``. A CI gate
    on ``--level wire`` or ``--level producer-safe`` passes the change.

    This is not a total miss: CONSUMER_SAFE and STRICT report the generic
    add-plus-remove pair.
    """
    by_level = _rule_ids_by_level(*_two_pools(old_field, new_field))

    # Control: the two unpaired names are visible where SEMANTIC/BACKWARD is kept.
    assert _silent_levels(by_level, "CONSUMER_SAFE", "STRICT") == [], by_level

    assert _silent_levels(by_level, "WIRE", "PRODUCER_SAFE") == [], (
        f"number reuse ({label}) passed with zero findings -> {by_level}"
    )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "V22 (extension analogue): owned by U4 (0.18.0). An extension number reused by "
        "a different extension reports COMPATIBLE with zero findings at WIRE and "
        "PRODUCER_SAFE; extensions pair by their (pkg.ext) key, so the change is one "
        "field_removed plus one field_added (both SEMANTIC/BACKWARD)"
    ),
)
@pytest.mark.parametrize(("label", "old_ext", "new_ext"), _NUMBER_REUSE, ids=_NUMBER_REUSE_IDS)
def test_extension_number_reuse_is_reported_at_wire_and_producer_safe(
    label: str,
    old_ext: dict,
    new_ext: dict,
) -> None:
    """A new extension on an old extension's number is the same break as V22.

    Data hazard: identical to the declared-field case, since an extension is
    a field number of the extended message. An old ``(t.price_cents) = -3``
    reads as ``(t.quantity) = 5``.
    """
    by_level = _rule_ids_by_level(*_two_extension_pools(old_ext, new_ext))

    # Control: the two unpaired extensions are visible where SEMANTIC/BACKWARD is kept.
    assert _silent_levels(by_level, "CONSUMER_SAFE", "STRICT") == [], by_level

    assert _silent_levels(by_level, "WIRE", "PRODUCER_SAFE") == [], (
        f"extension number reuse ({label}) passed with zero findings -> {by_level}"
    )


# ---------------------------------------------------------------------------
# R16-C1 (rename facet) — a renamed message field is never descended
# ---------------------------------------------------------------------------


def test_same_name_message_field_reports_its_nested_wire_break_control() -> None:
    """Control for the rename facet: under one name the nested break is WIRE everywhere."""
    by_level = _rule_ids_at_leaf(
        _address_pool("address", T.TYPE_STRING), _address_pool("address", T.TYPE_DOUBLE), "zip"
    )

    assert by_level == {
        level.name: ("field_type_wire_incompatible",) for level in CompatibilityLevel
    }


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "R16-C1 (rename facet): owned by U4 (0.18.0). Address address = 1 renamed to "
        "home_address = 1 while Address.zip changes string -> double reports no finding "
        "on zip at any level; the checker descends only into a name-paired field, and "
        "the rename leaves an unpaired field_removed and field_added"
    ),
)
def test_renamed_message_field_still_reports_its_nested_wire_break() -> None:
    """A rename at the same number must not hide a wire break one level down.

    Data hazard: the rename changes no bytes, so number 1 still carries an
    ``Address`` and its ``zip`` is still misread (an old ``"94110"`` is a
    new ``0.0``). The pin looks only at findings on ``zip``: a finding about
    the rename itself, which a V22 fix will add, does not satisfy it.
    """
    by_level = _rule_ids_at_leaf(
        _address_pool("address", T.TYPE_STRING),
        _address_pool("home_address", T.TYPE_DOUBLE),
        "zip",
    )

    assert _silent_levels(by_level) == [], (
        f"the nested zip break is unreported under the renamed field -> {by_level}"
    )
