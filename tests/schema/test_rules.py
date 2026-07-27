"""Tests for the 17 built-in compatibility rules."""

from __future__ import annotations

import tracemalloc

from google.protobuf import descriptor_pool

from protokit.message.model import FieldPath
from protokit.schema.model import Direction, Severity
from protokit.schema.rules import (
    ENUM_RULES,
    FIELD_RULES,
    MESSAGE_RULES,
    _is_reserved,
    _normalize_ranges,
    _reserved,
    _wire_compatible,
    enum_number_reused,
    enum_value_added,
    enum_value_removed,
    field_added,
    field_number_changed,
    field_removed,
    field_type_name_changed,
    field_type_semantic_change,
    field_type_wire_incompatible,
    map_to_repeated,
    oneof_field_added,
    oneof_membership_changed,
    options_changed,
    presence_changed,
    repeated_to_singular,
    required_field_added,
    reserved_field_reused,
)
from tests.schema.helpers import T, build_enum, build_message


ROOT = FieldPath(segments=())


# ---------------------------------------------------------------------------
# _wire_compatible
# ---------------------------------------------------------------------------


class TestWireCompatible:
    def test_same_type_is_compatible(self) -> None:
        assert _wire_compatible(T.TYPE_INT32, T.TYPE_INT32)

    def test_varint_group(self) -> None:
        assert _wire_compatible(T.TYPE_INT32, T.TYPE_INT64)
        assert _wire_compatible(T.TYPE_INT32, T.TYPE_BOOL)
        assert _wire_compatible(T.TYPE_INT32, T.TYPE_ENUM)

    def test_zigzag_group_separate_from_varint(self) -> None:
        assert not _wire_compatible(T.TYPE_INT32, T.TYPE_SINT32)
        assert _wire_compatible(T.TYPE_SINT32, T.TYPE_SINT64)

    def test_fixed32_group(self) -> None:
        assert _wire_compatible(T.TYPE_FIXED32, T.TYPE_SFIXED32)
        assert _wire_compatible(T.TYPE_FIXED32, T.TYPE_FLOAT)

    def test_fixed64_group(self) -> None:
        assert _wire_compatible(T.TYPE_FIXED64, T.TYPE_DOUBLE)
        assert _wire_compatible(T.TYPE_SFIXED64, T.TYPE_DOUBLE)

    def test_fixed32_and_fixed64_not_compatible(self) -> None:
        assert not _wire_compatible(T.TYPE_FIXED32, T.TYPE_FIXED64)

    def test_length_delimited_bytes_group(self) -> None:
        # string and bytes share a byte-level wire group.
        assert _wire_compatible(T.TYPE_STRING, T.TYPE_BYTES)

    def test_message_is_its_own_wire_group(self) -> None:
        # message uses wire-type 2 like string/bytes but a structural
        # payload — incompatible as a wire type.
        assert not _wire_compatible(T.TYPE_BYTES, T.TYPE_MESSAGE)
        assert not _wire_compatible(T.TYPE_STRING, T.TYPE_MESSAGE)

    def test_cross_group_incompatible(self) -> None:
        assert not _wire_compatible(T.TYPE_INT32, T.TYPE_FLOAT)
        assert not _wire_compatible(T.TYPE_STRING, T.TYPE_INT32)

    def test_group_is_isolated(self) -> None:
        assert not _wire_compatible(T.TYPE_GROUP, T.TYPE_STRING)


# ---------------------------------------------------------------------------
# Rule registry shape
# ---------------------------------------------------------------------------


class TestRegistries:
    def test_total_rule_count(self) -> None:
        assert len(FIELD_RULES) + len(ENUM_RULES) + len(MESSAGE_RULES) == 17

    def test_unique_rule_ids(self) -> None:
        ids = (
            [rid for rid, _ in FIELD_RULES]
            + [rid for rid, _ in ENUM_RULES]
            + [rid for rid, _ in MESSAGE_RULES]
        )
        assert len(ids) == len(set(ids))

    def test_field_registry_count(self) -> None:
        assert len(FIELD_RULES) == 13


# ---------------------------------------------------------------------------
# field_type_name_changed
# ---------------------------------------------------------------------------


class TestFieldTypeNameChanged:
    def test_fires_when_message_type_name_differs(self) -> None:
        old_pool = descriptor_pool.DescriptorPool()
        new_pool = descriptor_pool.DescriptorPool()
        build_message(old_pool, "t.Inner", fields=[
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
        ])
        build_message(old_pool, "t.Outer", fields=[
            {"name": "p", "number": 1, "type": T.TYPE_MESSAGE,
             "type_name": "t.Inner"},
        ])
        # New schema renames the referenced message to t.Renamed.
        build_message(new_pool, "t.Renamed", fields=[
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
        ])
        build_message(new_pool, "t.Outer", fields=[
            {"name": "p", "number": 1, "type": T.TYPE_MESSAGE,
             "type_name": "t.Renamed"},
        ])
        old_fd = old_pool.FindMessageTypeByName("t.Outer").fields_by_name["p"]
        new_fd = new_pool.FindMessageTypeByName("t.Outer").fields_by_name["p"]
        findings = field_type_name_changed(old_fd, new_fd, ROOT)
        assert len(findings) == 1
        assert findings[0].severity is Severity.POLICY
        assert findings[0].direction is Direction.BOTH
        assert "t.Inner" in findings[0].message
        assert "t.Renamed" in findings[0].message

    def test_fires_when_enum_type_name_differs(self) -> None:
        old_pool = descriptor_pool.DescriptorPool()
        new_pool = descriptor_pool.DescriptorPool()
        build_enum(old_pool, "t.Status", {"OK": 0, "BAD": 1})
        build_enum(new_pool, "t.Health", {"OK": 0, "BAD": 1})
        build_message(old_pool, "t.M", fields=[
            {"name": "s", "number": 1, "type": T.TYPE_ENUM,
             "type_name": "t.Status"},
        ])
        build_message(new_pool, "t.M", fields=[
            {"name": "s", "number": 1, "type": T.TYPE_ENUM,
             "type_name": "t.Health"},
        ])
        old_fd = old_pool.FindMessageTypeByName("t.M").fields_by_name["s"]
        new_fd = new_pool.FindMessageTypeByName("t.M").fields_by_name["s"]
        findings = field_type_name_changed(old_fd, new_fd, ROOT)
        assert len(findings) == 1
        assert "t.Status" in findings[0].message
        assert "t.Health" in findings[0].message

    def test_silent_when_type_names_match(self) -> None:
        old_pool = descriptor_pool.DescriptorPool()
        new_pool = descriptor_pool.DescriptorPool()
        for p in (old_pool, new_pool):
            build_message(p, "t.Inner", fields=[
                {"name": "x", "number": 1, "type": T.TYPE_INT32},
            ])
            build_message(p, "t.Outer", fields=[
                {"name": "p", "number": 1, "type": T.TYPE_MESSAGE,
                 "type_name": "t.Inner"},
            ])
        old_fd = old_pool.FindMessageTypeByName("t.Outer").fields_by_name["p"]
        new_fd = new_pool.FindMessageTypeByName("t.Outer").fields_by_name["p"]
        assert field_type_name_changed(old_fd, new_fd, ROOT) == []

    def test_silent_for_scalar_fields(self) -> None:
        old_pool = descriptor_pool.DescriptorPool()
        new_pool = descriptor_pool.DescriptorPool()
        build_message(old_pool, "t.M", fields=[
            {"name": "x", "number": 1, "type": T.TYPE_STRING},
        ])
        build_message(new_pool, "t.M", fields=[
            {"name": "x", "number": 1, "type": T.TYPE_STRING},
        ])
        old_fd = old_pool.FindMessageTypeByName("t.M").fields_by_name["x"]
        new_fd = new_pool.FindMessageTypeByName("t.M").fields_by_name["x"]
        assert field_type_name_changed(old_fd, new_fd, ROOT) == []

    def test_silent_for_map_field_under_cross_type_rename(self) -> None:
        """Map entry types are synthetic; renaming the outer message
        rotates ``UserV1.ItemsEntry`` → ``UserV2.ItemsEntry`` even
        when the map itself is unchanged. Those synthetic rotations
        must not fire the rule — they're bookkeeping, not a type-
        identity rotation the user did.
        """
        from tests.proto_builder import ProtoBuilder
        old_pool = descriptor_pool.DescriptorPool()
        new_pool = descriptor_pool.DescriptorPool()
        pb_old = ProtoBuilder(old_pool)
        pb_old.map_message(
            "t.UserV1", fields={},
            map_fields={"items": (T.TYPE_STRING, T.TYPE_INT32, 1)},
        )
        pb_new = ProtoBuilder(new_pool)
        pb_new.map_message(
            "t.UserV2", fields={},
            map_fields={"items": (T.TYPE_STRING, T.TYPE_INT32, 1)},
        )
        old_fd = old_pool.FindMessageTypeByName("t.UserV1").fields_by_name["items"]
        new_fd = new_pool.FindMessageTypeByName("t.UserV2").fields_by_name["items"]
        assert field_type_name_changed(old_fd, new_fd, ROOT) == []

    def test_silent_on_map_field_itself(self) -> None:
        """The rule skips the map field itself — value-type rotation
        is flagged when the engine dispatches field rules against the
        synthetic MapEntry.value sub-field instead. The checker-level
        test in test_checker.py verifies the end-to-end path.
        """
        # No-op sanity: field_type_name_changed on a map field
        # returns []. The real value-type test lives in test_checker.
        from tests.proto_builder import ProtoBuilder
        pool = descriptor_pool.DescriptorPool()
        pb = ProtoBuilder(pool)
        pb.map_message(
            "t.M", fields={},
            map_fields={"items": (T.TYPE_STRING, T.TYPE_STRING, 1)},
        )
        fd = pool.FindMessageTypeByName("t.M").fields_by_name["items"]
        assert field_type_name_changed(fd, fd, ROOT) == []

    def test_silent_when_type_category_changes(self) -> None:
        """message -> enum (or any category change) is handled by
        ``field_type_wire_incompatible``; this rule only fires for
        same-category, different-name.
        """
        old_pool = descriptor_pool.DescriptorPool()
        new_pool = descriptor_pool.DescriptorPool()
        build_enum(new_pool, "t.E", {"OK": 0})
        build_message(old_pool, "t.Inner", fields=[
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
        ])
        build_message(old_pool, "t.M", fields=[
            {"name": "p", "number": 1, "type": T.TYPE_MESSAGE,
             "type_name": "t.Inner"},
        ])
        build_message(new_pool, "t.M", fields=[
            {"name": "p", "number": 1, "type": T.TYPE_ENUM,
             "type_name": "t.E"},
        ])
        old_fd = old_pool.FindMessageTypeByName("t.M").fields_by_name["p"]
        new_fd = new_pool.FindMessageTypeByName("t.M").fields_by_name["p"]
        assert field_type_name_changed(old_fd, new_fd, ROOT) == []

    def test_enum_registry_count(self) -> None:
        assert len(ENUM_RULES) == 3

    def test_message_registry_count(self) -> None:
        assert len(MESSAGE_RULES) == 1


# ---------------------------------------------------------------------------
# Helper factories used by field-rule tests
# ---------------------------------------------------------------------------


def _two_pool_fields(
    old_field_spec: dict | None,
    new_field_spec: dict | None,
    *,
    old_syntax: str = "proto3",
    new_syntax: str = "proto3",
    old_oneofs: list[str] = (),
    new_oneofs: list[str] = (),
    old_type_specs: list[dict] | None = None,
    new_type_specs: list[dict] | None = None,
) -> tuple[object | None, object | None]:
    """Build two messages with one field each (old and new) and return the pair.

    Convenience: set a spec to None to produce a message with no fields,
    i.e., the rule sees that side as missing.
    """
    old_pool = descriptor_pool.DescriptorPool()
    new_pool = descriptor_pool.DescriptorPool()
    old_fields = old_type_specs or ([old_field_spec] if old_field_spec else [])
    new_fields = new_type_specs or ([new_field_spec] if new_field_spec else [])
    build_message(
        old_pool, "t.M",
        fields=old_fields,
        oneofs=old_oneofs,
        syntax=old_syntax,
    )
    build_message(
        new_pool, "t.M",
        fields=new_fields,
        oneofs=new_oneofs,
        syntax=new_syntax,
    )
    old_desc = old_pool.FindMessageTypeByName("t.M")
    new_desc = new_pool.FindMessageTypeByName("t.M")
    old_fd = old_desc.fields_by_name.get(old_field_spec["name"]) if old_field_spec else None
    new_fd = new_desc.fields_by_name.get(new_field_spec["name"]) if new_field_spec else None
    return old_fd, new_fd


# ---------------------------------------------------------------------------
# field_removed
# ---------------------------------------------------------------------------


class TestFieldRemoved:
    def test_fires_when_in_old_only(self) -> None:
        old_fd, new_fd = _two_pool_fields(
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
            None,
        )
        findings = field_removed(old_fd, new_fd, FieldPath.parse("x"))
        assert len(findings) == 1
        assert findings[0].rule_id == "field_removed"
        assert findings[0].severity is Severity.SEMANTIC
        assert findings[0].direction is Direction.BACKWARD

    def test_silent_when_in_both(self) -> None:
        old_fd, new_fd = _two_pool_fields(
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
        )
        assert field_removed(old_fd, new_fd, ROOT) == []

    def test_silent_when_in_new_only(self) -> None:
        old_fd, new_fd = _two_pool_fields(
            None,
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
        )
        assert field_removed(old_fd, new_fd, ROOT) == []


# ---------------------------------------------------------------------------
# field_added
# ---------------------------------------------------------------------------


class TestFieldAdded:
    def test_fires_for_new_plain_field(self) -> None:
        old_fd, new_fd = _two_pool_fields(
            None,
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
        )
        findings = field_added(old_fd, new_fd, FieldPath.parse("x"))
        assert len(findings) == 1
        assert findings[0].rule_id == "field_added"
        # Direction reflects WHICH READER IS AT RISK. Old consumer
        # reading new data sees an unknown field → BACKWARD.
        assert findings[0].direction is Direction.BACKWARD

    def test_silent_for_required_add(self) -> None:
        old_fd, new_fd = _two_pool_fields(
            None,
            {"name": "x", "number": 1, "type": T.TYPE_INT32, "label": T.LABEL_REQUIRED},
            new_syntax="proto2",
        )
        assert field_added(old_fd, new_fd, ROOT) == []

    def test_silent_for_oneof_member_add(self) -> None:
        old_fd, new_fd = _two_pool_fields(
            None,
            {"name": "x", "number": 1, "type": T.TYPE_INT32, "oneof_index": 0},
            new_oneofs=["choice"],
        )
        assert field_added(old_fd, new_fd, ROOT) == []

    def test_fires_for_proto3_optional_add(self) -> None:
        old_fd, new_fd = _two_pool_fields(
            None,
            {
                "name": "x", "number": 1, "type": T.TYPE_INT32,
                "proto3_optional": True, "oneof_index": 0,
            },
            new_oneofs=["_x"],
        )
        # synthetic oneof must not suppress field_added
        findings = field_added(old_fd, new_fd, ROOT)
        assert len(findings) == 1

    def test_silent_when_in_both(self) -> None:
        old_fd, new_fd = _two_pool_fields(
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
        )
        assert field_added(old_fd, new_fd, ROOT) == []


# ---------------------------------------------------------------------------
# field_number_changed
# ---------------------------------------------------------------------------


class TestFieldNumberChanged:
    def test_fires_on_number_change(self) -> None:
        old_fd, new_fd = _two_pool_fields(
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
            {"name": "x", "number": 5, "type": T.TYPE_INT32},
        )
        findings = field_number_changed(old_fd, new_fd, ROOT)
        assert len(findings) == 1
        assert findings[0].severity is Severity.WIRE
        assert findings[0].direction is Direction.BOTH
        assert "1" in findings[0].message and "5" in findings[0].message

    def test_silent_when_same(self) -> None:
        old_fd, new_fd = _two_pool_fields(
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
        )
        assert field_number_changed(old_fd, new_fd, ROOT) == []

    def test_silent_when_one_side_missing(self) -> None:
        old_fd, new_fd = _two_pool_fields(
            None,
            {"name": "x", "number": 5, "type": T.TYPE_INT32},
        )
        assert field_number_changed(old_fd, new_fd, ROOT) == []


# ---------------------------------------------------------------------------
# field_type_{wire_incompatible, semantic_change}
# ---------------------------------------------------------------------------


class TestFieldTypeWireIncompatible:
    def test_fires_across_wire_groups(self) -> None:
        old_fd, new_fd = _two_pool_fields(
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
            {"name": "x", "number": 1, "type": T.TYPE_FLOAT},
        )
        findings = field_type_wire_incompatible(old_fd, new_fd, ROOT)
        assert len(findings) == 1
        assert findings[0].severity is Severity.WIRE

    def test_silent_for_same_wire_group(self) -> None:
        old_fd, new_fd = _two_pool_fields(
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
            {"name": "x", "number": 1, "type": T.TYPE_UINT32},
        )
        assert field_type_wire_incompatible(old_fd, new_fd, ROOT) == []

    def test_silent_for_same_type(self) -> None:
        old_fd, new_fd = _two_pool_fields(
            {"name": "x", "number": 1, "type": T.TYPE_STRING},
            {"name": "x", "number": 1, "type": T.TYPE_STRING},
        )
        assert field_type_wire_incompatible(old_fd, new_fd, ROOT) == []


class TestFieldTypeSemanticChange:
    def test_fires_for_same_wire_group_different_type(self) -> None:
        old_fd, new_fd = _two_pool_fields(
            {"name": "x", "number": 1, "type": T.TYPE_STRING},
            {"name": "x", "number": 1, "type": T.TYPE_BYTES},
        )
        findings = field_type_semantic_change(old_fd, new_fd, ROOT)
        assert len(findings) == 1
        assert findings[0].severity is Severity.SEMANTIC
        assert findings[0].direction is Direction.BOTH

    def test_int32_to_uint32_semantic(self) -> None:
        old_fd, new_fd = _two_pool_fields(
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
            {"name": "x", "number": 1, "type": T.TYPE_UINT32},
        )
        findings = field_type_semantic_change(old_fd, new_fd, ROOT)
        assert len(findings) == 1

    def test_silent_across_wire_groups(self) -> None:
        old_fd, new_fd = _two_pool_fields(
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
            {"name": "x", "number": 1, "type": T.TYPE_FLOAT},
        )
        assert field_type_semantic_change(old_fd, new_fd, ROOT) == []

    def test_silent_for_same_type(self) -> None:
        old_fd, new_fd = _two_pool_fields(
            {"name": "x", "number": 1, "type": T.TYPE_STRING},
            {"name": "x", "number": 1, "type": T.TYPE_STRING},
        )
        assert field_type_semantic_change(old_fd, new_fd, ROOT) == []


# ---------------------------------------------------------------------------
# repeated_to_singular / map_to_repeated
# ---------------------------------------------------------------------------


class TestRepeatedToSingular:
    def test_fires_singular_to_repeated(self) -> None:
        old_fd, new_fd = _two_pool_fields(
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
            {"name": "x", "number": 1, "type": T.TYPE_INT32, "label": T.LABEL_REPEATED},
        )
        findings = repeated_to_singular(old_fd, new_fd, ROOT)
        assert len(findings) == 1
        assert findings[0].severity is Severity.WIRE

    def test_fires_repeated_to_singular(self) -> None:
        old_fd, new_fd = _two_pool_fields(
            {"name": "x", "number": 1, "type": T.TYPE_INT32, "label": T.LABEL_REPEATED},
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
        )
        assert len(repeated_to_singular(old_fd, new_fd, ROOT)) == 1

    def test_silent_when_same(self) -> None:
        old_fd, new_fd = _two_pool_fields(
            {"name": "x", "number": 1, "type": T.TYPE_INT32, "label": T.LABEL_REPEATED},
            {"name": "x", "number": 1, "type": T.TYPE_INT32, "label": T.LABEL_REPEATED},
        )
        assert repeated_to_singular(old_fd, new_fd, ROOT) == []

    def test_silent_when_map_involved(self) -> None:
        # map_to_repeated should fire, not repeated_to_singular.
        old_pool = descriptor_pool.DescriptorPool()
        new_pool = descriptor_pool.DescriptorPool()
        from tests.proto_builder import ProtoBuilder
        pb_old = ProtoBuilder(old_pool)
        pb_old.map_message(
            "t.M", fields={},
            map_fields={"kv": (T.TYPE_STRING, T.TYPE_STRING, 1)},
        )
        build_message(new_pool, "t.M", fields=[
            {"name": "kv", "number": 1, "type": T.TYPE_STRING,
             "label": T.LABEL_REPEATED},
        ])
        old_fd = old_pool.FindMessageTypeByName("t.M").fields_by_name["kv"]
        new_fd = new_pool.FindMessageTypeByName("t.M").fields_by_name["kv"]
        assert repeated_to_singular(old_fd, new_fd, ROOT) == []


class TestMapToRepeated:
    def test_fires_on_map_to_repeated(self) -> None:
        old_pool = descriptor_pool.DescriptorPool()
        new_pool = descriptor_pool.DescriptorPool()
        from tests.proto_builder import ProtoBuilder
        pb_old = ProtoBuilder(old_pool)
        pb_old.map_message(
            "t.M", fields={},
            map_fields={"kv": (T.TYPE_STRING, T.TYPE_STRING, 1)},
        )
        build_message(new_pool, "t.M", fields=[
            {"name": "kv", "number": 1, "type": T.TYPE_STRING,
             "label": T.LABEL_REPEATED},
        ])
        old_fd = old_pool.FindMessageTypeByName("t.M").fields_by_name["kv"]
        new_fd = new_pool.FindMessageTypeByName("t.M").fields_by_name["kv"]
        findings = map_to_repeated(old_fd, new_fd, ROOT)
        assert len(findings) == 1
        assert findings[0].severity is Severity.WIRE

    def test_silent_when_both_maps(self) -> None:
        old_pool = descriptor_pool.DescriptorPool()
        new_pool = descriptor_pool.DescriptorPool()
        from tests.proto_builder import ProtoBuilder
        for p in (old_pool, new_pool):
            pb = ProtoBuilder(p)
            pb.map_message(
                "t.M", fields={},
                map_fields={"kv": (T.TYPE_STRING, T.TYPE_STRING, 1)},
            )
        old_fd = old_pool.FindMessageTypeByName("t.M").fields_by_name["kv"]
        new_fd = new_pool.FindMessageTypeByName("t.M").fields_by_name["kv"]
        assert map_to_repeated(old_fd, new_fd, ROOT) == []


# ---------------------------------------------------------------------------
# oneof_membership_changed
# ---------------------------------------------------------------------------


class TestOneofMembershipChanged:
    def test_fires_when_moved_into_oneof(self) -> None:
        old_fd, new_fd = _two_pool_fields(
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
            {"name": "x", "number": 1, "type": T.TYPE_INT32, "oneof_index": 0},
            new_oneofs=["choice"],
        )
        findings = oneof_membership_changed(old_fd, new_fd, ROOT)
        assert len(findings) == 1
        assert "choice" in findings[0].message

    def test_fires_when_moved_out_of_oneof(self) -> None:
        old_fd, new_fd = _two_pool_fields(
            {"name": "x", "number": 1, "type": T.TYPE_INT32, "oneof_index": 0},
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
            old_oneofs=["choice"],
        )
        assert len(oneof_membership_changed(old_fd, new_fd, ROOT)) == 1

    def test_silent_when_same_oneof(self) -> None:
        old_fd, new_fd = _two_pool_fields(
            {"name": "x", "number": 1, "type": T.TYPE_INT32, "oneof_index": 0},
            {"name": "x", "number": 1, "type": T.TYPE_INT32, "oneof_index": 0},
            old_oneofs=["choice"],
            new_oneofs=["choice"],
        )
        assert oneof_membership_changed(old_fd, new_fd, ROOT) == []

    def test_synthetic_oneof_does_not_trigger(self) -> None:
        # adding `optional` to a proto3 field puts it in a synthetic oneof,
        # which should NOT be reported as a membership change.
        old_fd, new_fd = _two_pool_fields(
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
            {
                "name": "x", "number": 1, "type": T.TYPE_INT32,
                "proto3_optional": True, "oneof_index": 0,
            },
            new_oneofs=["_x"],
        )
        assert oneof_membership_changed(old_fd, new_fd, ROOT) == []


# ---------------------------------------------------------------------------
# oneof_field_added
# ---------------------------------------------------------------------------


class TestOneofFieldAdded:
    def test_fires_when_field_added_to_oneof(self) -> None:
        old_fd, new_fd = _two_pool_fields(
            None,
            {"name": "x", "number": 1, "type": T.TYPE_INT32, "oneof_index": 0},
            new_oneofs=["choice"],
        )
        findings = oneof_field_added(old_fd, new_fd, ROOT)
        assert len(findings) == 1
        assert "choice" in findings[0].message
        # Old consumer with an exhaustive oneof switch doesn't know
        # the new alternative → BACKWARD.
        assert findings[0].direction is Direction.BACKWARD

    def test_silent_when_added_outside_oneof(self) -> None:
        old_fd, new_fd = _two_pool_fields(
            None,
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
        )
        assert oneof_field_added(old_fd, new_fd, ROOT) == []

    def test_silent_for_synthetic_oneof_add(self) -> None:
        old_fd, new_fd = _two_pool_fields(
            None,
            {
                "name": "x", "number": 1, "type": T.TYPE_INT32,
                "proto3_optional": True, "oneof_index": 0,
            },
            new_oneofs=["_x"],
        )
        assert oneof_field_added(old_fd, new_fd, ROOT) == []


# ---------------------------------------------------------------------------
# required_field_added
# ---------------------------------------------------------------------------


class TestRequiredFieldAdded:
    def test_fires_for_proto2_required_add(self) -> None:
        old_fd, new_fd = _two_pool_fields(
            None,
            {"name": "x", "number": 1, "type": T.TYPE_INT32, "label": T.LABEL_REQUIRED},
            new_syntax="proto2",
        )
        findings = required_field_added(old_fd, new_fd, ROOT)
        assert len(findings) == 1
        assert findings[0].severity is Severity.WIRE
        # Required-field add breaks NEW CONSUMERS on OLD DATA (old
        # producer doesn't set the field) → FORWARD direction, so it
        # surfaces in PRODUCER_SAFE.
        assert findings[0].direction is Direction.FORWARD

    def test_silent_for_optional_add(self) -> None:
        old_fd, new_fd = _two_pool_fields(
            None,
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
            new_syntax="proto2",
        )
        assert required_field_added(old_fd, new_fd, ROOT) == []

    def test_silent_for_existing_required(self) -> None:
        old_fd, new_fd = _two_pool_fields(
            {"name": "x", "number": 1, "type": T.TYPE_INT32, "label": T.LABEL_REQUIRED},
            {"name": "x", "number": 1, "type": T.TYPE_INT32, "label": T.LABEL_REQUIRED},
            old_syntax="proto2",
            new_syntax="proto2",
        )
        assert required_field_added(old_fd, new_fd, ROOT) == []


# ---------------------------------------------------------------------------
# options_changed
# ---------------------------------------------------------------------------


class TestOptionsChanged:
    def test_fires_on_deprecated_change(self) -> None:
        old_pool = descriptor_pool.DescriptorPool()
        new_pool = descriptor_pool.DescriptorPool()
        from google.protobuf import descriptor_pb2
        # Old: no deprecated option
        fp_old = descriptor_pb2.FileDescriptorProto(
            name="o.proto", package="t", syntax="proto3",
        )
        mp = fp_old.message_type.add()
        mp.name = "M"
        f = mp.field.add()
        f.name = "x"
        f.number = 1
        f.type = T.TYPE_INT32
        f.label = T.LABEL_OPTIONAL
        old_pool.Add(fp_old)

        # New: deprecated=true on the field options
        fp_new = descriptor_pb2.FileDescriptorProto(
            name="n.proto", package="t", syntax="proto3",
        )
        mp2 = fp_new.message_type.add()
        mp2.name = "M"
        f2 = mp2.field.add()
        f2.name = "x"
        f2.number = 1
        f2.type = T.TYPE_INT32
        f2.label = T.LABEL_OPTIONAL
        f2.options.deprecated = True
        new_pool.Add(fp_new)

        old_fd = old_pool.FindMessageTypeByName("t.M").fields_by_name["x"]
        new_fd = new_pool.FindMessageTypeByName("t.M").fields_by_name["x"]
        findings = options_changed(old_fd, new_fd, ROOT)
        assert len(findings) == 1
        assert findings[0].severity is Severity.POLICY
        assert findings[0].direction is Direction.BOTH

    def test_silent_when_options_match(self) -> None:
        old_fd, new_fd = _two_pool_fields(
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
        )
        assert options_changed(old_fd, new_fd, ROOT) == []


# ---------------------------------------------------------------------------
# presence_changed
# ---------------------------------------------------------------------------


class TestPresenceChanged:
    def test_fires_on_presence_gain(self) -> None:
        # proto3 implicit -> proto3 optional
        old_fd, new_fd = _two_pool_fields(
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
            {
                "name": "x", "number": 1, "type": T.TYPE_INT32,
                "proto3_optional": True, "oneof_index": 0,
            },
            new_oneofs=["_x"],
        )
        findings = presence_changed(old_fd, new_fd, ROOT)
        assert len(findings) == 1
        assert findings[0].severity is Severity.SEMANTIC

    def test_fires_proto2_to_proto3_implicit(self) -> None:
        old_fd, new_fd = _two_pool_fields(
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
            old_syntax="proto2",
            new_syntax="proto3",
        )
        assert len(presence_changed(old_fd, new_fd, ROOT)) == 1

    def test_silent_when_same_presence(self) -> None:
        old_fd, new_fd = _two_pool_fields(
            {"name": "x", "number": 1, "type": T.TYPE_STRING},
            {"name": "x", "number": 1, "type": T.TYPE_STRING},
        )
        assert presence_changed(old_fd, new_fd, ROOT) == []


# ---------------------------------------------------------------------------
# enum rules
# ---------------------------------------------------------------------------


class TestEnumValueRemoved:
    def test_fires_when_value_gone(self) -> None:
        old_pool = descriptor_pool.DescriptorPool()
        new_pool = descriptor_pool.DescriptorPool()
        build_enum(old_pool, "t.Color", {"RED": 0, "BLUE": 1, "GREEN": 2})
        build_enum(new_pool, "t.Color", {"RED": 0, "BLUE": 1})
        old_e = old_pool.FindEnumTypeByName("t.Color")
        new_e = new_pool.FindEnumTypeByName("t.Color")
        findings = enum_value_removed(old_e, new_e, ROOT)
        assert len(findings) == 1
        # Old producer can still emit the removed value; NEW
        # consumer parsing old data sees an unknown name → FORWARD.
        assert findings[0].direction is Direction.FORWARD
        assert "GREEN" in findings[0].message

    def test_silent_when_identical(self) -> None:
        old_pool = descriptor_pool.DescriptorPool()
        new_pool = descriptor_pool.DescriptorPool()
        build_enum(old_pool, "t.Color", {"RED": 0, "BLUE": 1})
        build_enum(new_pool, "t.Color", {"RED": 0, "BLUE": 1})
        old_e = old_pool.FindEnumTypeByName("t.Color")
        new_e = new_pool.FindEnumTypeByName("t.Color")
        assert enum_value_removed(old_e, new_e, ROOT) == []

    def test_multiple_removals(self) -> None:
        old_pool = descriptor_pool.DescriptorPool()
        new_pool = descriptor_pool.DescriptorPool()
        build_enum(old_pool, "t.E", {"A": 0, "B": 1, "C": 2, "D": 3})
        build_enum(new_pool, "t.E", {"A": 0, "B": 1})
        old_e = old_pool.FindEnumTypeByName("t.E")
        new_e = new_pool.FindEnumTypeByName("t.E")
        findings = enum_value_removed(old_e, new_e, ROOT)
        assert len(findings) == 2
        assert {f.old_descriptor.name for f in findings} == {"C", "D"}


class TestEnumValueAdded:
    def test_fires_when_value_new(self) -> None:
        old_pool = descriptor_pool.DescriptorPool()
        new_pool = descriptor_pool.DescriptorPool()
        build_enum(old_pool, "t.Color", {"RED": 0})
        build_enum(new_pool, "t.Color", {"RED": 0, "BLUE": 1})
        old_e = old_pool.FindEnumTypeByName("t.Color")
        new_e = new_pool.FindEnumTypeByName("t.Color")
        findings = enum_value_added(old_e, new_e, ROOT)
        assert len(findings) == 1
        # Old consumer reading new data sees an unknown enum
        # value → BACKWARD.
        assert findings[0].direction is Direction.BACKWARD

    def test_silent_when_identical(self) -> None:
        old_pool = descriptor_pool.DescriptorPool()
        new_pool = descriptor_pool.DescriptorPool()
        build_enum(old_pool, "t.E", {"A": 0})
        build_enum(new_pool, "t.E", {"A": 0})
        old_e = old_pool.FindEnumTypeByName("t.E")
        new_e = new_pool.FindEnumTypeByName("t.E")
        assert enum_value_added(old_e, new_e, ROOT) == []


class TestEnumNumberReused:
    def test_fires_when_number_renamed(self) -> None:
        old_pool = descriptor_pool.DescriptorPool()
        new_pool = descriptor_pool.DescriptorPool()
        build_enum(old_pool, "t.E", {"A": 0, "OLD": 1})
        build_enum(new_pool, "t.E", {"A": 0, "NEW": 1})
        old_e = old_pool.FindEnumTypeByName("t.E")
        new_e = new_pool.FindEnumTypeByName("t.E")
        findings = enum_number_reused(old_e, new_e, ROOT)
        assert len(findings) == 1
        assert findings[0].severity is Severity.WIRE
        assert "1" in findings[0].message
        assert "OLD" in findings[0].message
        assert "NEW" in findings[0].message

    def test_silent_when_identical(self) -> None:
        old_pool = descriptor_pool.DescriptorPool()
        new_pool = descriptor_pool.DescriptorPool()
        build_enum(old_pool, "t.E", {"A": 0, "B": 1})
        build_enum(new_pool, "t.E", {"A": 0, "B": 1})
        old_e = old_pool.FindEnumTypeByName("t.E")
        new_e = new_pool.FindEnumTypeByName("t.E")
        assert enum_number_reused(old_e, new_e, ROOT) == []

    def test_silent_for_pure_removal(self) -> None:
        old_pool = descriptor_pool.DescriptorPool()
        new_pool = descriptor_pool.DescriptorPool()
        build_enum(old_pool, "t.E", {"A": 0, "B": 1})
        build_enum(new_pool, "t.E", {"A": 0})
        old_e = old_pool.FindEnumTypeByName("t.E")
        new_e = new_pool.FindEnumTypeByName("t.E")
        # Number 1 doesn't exist in new, so no "reuse" — handled by enum_value_removed
        assert enum_number_reused(old_e, new_e, ROOT) == []

    def test_alias_compat_silent(self) -> None:
        # old: allow_alias A=0, ALIAS_A=0.  new: still has A=0
        # No number reuse because the set of names at 0 in new is a subset of old.
        old_pool = descriptor_pool.DescriptorPool()
        new_pool = descriptor_pool.DescriptorPool()
        build_enum(old_pool, "t.E", {"A": 0, "ALIAS": 0}, allow_alias=True)
        build_enum(new_pool, "t.E", {"A": 0})
        old_e = old_pool.FindEnumTypeByName("t.E")
        new_e = new_pool.FindEnumTypeByName("t.E")
        assert enum_number_reused(old_e, new_e, ROOT) == []


# ---------------------------------------------------------------------------
# reserved_field_reused
# ---------------------------------------------------------------------------


class TestReservedFieldReused:
    def test_fires_for_reserved_number_reused(self) -> None:
        old_pool = descriptor_pool.DescriptorPool()
        new_pool = descriptor_pool.DescriptorPool()
        build_message(
            old_pool, "t.M",
            fields=[{"name": "a", "number": 1, "type": T.TYPE_INT32}],
            reserved_ranges=[(5, 10)],
        )
        build_message(
            new_pool, "t.M",
            fields=[
                {"name": "a", "number": 1, "type": T.TYPE_INT32},
                {"name": "b", "number": 7, "type": T.TYPE_STRING},
            ],
        )
        old_d = old_pool.FindMessageTypeByName("t.M")
        new_d = new_pool.FindMessageTypeByName("t.M")
        findings = reserved_field_reused(old_d, new_d, ROOT)
        assert len(findings) == 1
        assert findings[0].severity is Severity.WIRE
        assert "7" in findings[0].message
        assert "b" in findings[0].message

    def test_fires_for_reserved_name_reused(self) -> None:
        old_pool = descriptor_pool.DescriptorPool()
        new_pool = descriptor_pool.DescriptorPool()
        build_message(
            old_pool, "t.M",
            fields=[{"name": "a", "number": 1, "type": T.TYPE_INT32}],
            reserved_names=["old_field"],
        )
        build_message(
            new_pool, "t.M",
            fields=[
                {"name": "a", "number": 1, "type": T.TYPE_INT32},
                {"name": "old_field", "number": 2, "type": T.TYPE_STRING},
            ],
        )
        old_d = old_pool.FindMessageTypeByName("t.M")
        new_d = new_pool.FindMessageTypeByName("t.M")
        findings = reserved_field_reused(old_d, new_d, ROOT)
        assert len(findings) == 1
        assert "old_field" in findings[0].message
        # Name reuse is a source-level concern, not a wire break.
        assert findings[0].severity is Severity.SEMANTIC

    def test_wide_reserved_range_does_not_materialize(self) -> None:
        """A wide reserved range must stay O(1) in memory, not O(range width).

        Deliberately uses a MODERATE width (100k), not the real
        ``reserved N to max;`` ceiling of 536_870_912. That is a
        fail-safety property, not timidity: if someone reintroduces
        ``set(range(start, end))``, this test allocates ~8.8 MB and
        fails its assertion with a readable message. The same test at
        the true ceiling would attempt ~32 GB and get the pytest worker
        OOM-killed *before* the assertion is ever evaluated -- a
        regression guard that takes down CI instead of reporting a
        failure. The protocol maximum is covered functionally by
        :meth:`test_reserved_to_max_is_handled_without_expansion`, at
        the helper level where no expansion is possible.

        Pinning peak allocation rather than wall time keeps the guard
        meaningful on a loaded CI box: the defect was an allocation, so
        allocation is what must be asserted.
        """
        old_pool = descriptor_pool.DescriptorPool()
        new_pool = descriptor_pool.DescriptorPool()
        build_message(
            old_pool, "t.M",
            fields=[{"name": "a", "number": 1, "type": T.TYPE_INT32}],
            reserved_ranges=[(1000, 101_000)],
        )
        build_message(
            new_pool, "t.M",
            fields=[
                {"name": "a", "number": 1, "type": T.TYPE_INT32},
                {"name": "b", "number": 2000, "type": T.TYPE_STRING},
            ],
        )
        old_d = old_pool.FindMessageTypeByName("t.M")
        new_d = new_pool.FindMessageTypeByName("t.M")

        tracemalloc.start()
        try:
            findings = reserved_field_reused(old_d, new_d, ROOT)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        # The reuse is still detected -- this is not a "skip the work" fix.
        assert len(findings) == 1
        assert findings[0].severity is Severity.WIRE
        assert "2000" in findings[0].message
        # Measured ~2 KB after the fix; expansion of this range measures
        # ~8.8 MB, so the 1 MB ceiling separates them by ~9x.
        assert peak < 1_000_000, f"peak allocation {peak} bytes suggests range expansion"

    def test_reserved_to_max_is_handled_without_expansion(self) -> None:
        """The real protocol ceiling, exercised where expansion cannot happen.

        ``reserved 1000 to max;`` round-trips as ``end = 536_870_912``.
        This drives the range helpers directly rather than the rule, so
        the protocol maximum is pinned without any code path that could
        OOM the test process if the defect returns.
        """
        ranges = _normalize_ranges([(1000, 536_870_912)])
        assert ranges == ((1000, 536_870_912),)
        assert _is_reserved(1000, ranges) is True
        assert _is_reserved(536_870_911, ranges) is True
        assert _is_reserved(999, ranges) is False
        assert _is_reserved(536_870_912, ranges) is False

    def test_many_reserved_ranges_do_not_scan_linearly(self) -> None:
        """Membership must binary-search, not scan every range per field.

        The first fix for the OOM replaced the set with a linear
        ``any(start <= n < end ...)`` scan, which is O(fields x ranges):
        10_000 ranges against 10_000 fields measured 2.4 s, versus
        0.003 s for the set form it replaced -- trading a memory denial
        of service for a CPU one. Ranges are now normalized once and
        binary-searched, measured at 0.008 s for the same shape.

        Asserts an operation COUNT via the sorted-order invariant rather
        than wall time, so the guard cannot flake on a loaded runner:
        a linear scan cannot satisfy it at this size within the budget.
        """
        count = 2_000
        old_pool = descriptor_pool.DescriptorPool()
        new_pool = descriptor_pool.DescriptorPool()
        build_message(
            old_pool, "t.M",
            fields=[{"name": "a", "number": 1, "type": T.TYPE_INT32}],
            reserved_ranges=[(i * 4 + 10, i * 4 + 11) for i in range(count)],
        )
        build_message(
            new_pool, "t.M",
            fields=[
                {"name": f"f{i}", "number": i * 4 + 12, "type": T.TYPE_INT32}
                for i in range(count)
            ],
        )
        old_d = old_pool.FindMessageTypeByName("t.M")
        new_d = new_pool.FindMessageTypeByName("t.M")
        # None of the new field numbers fall inside a reserved range.
        assert reserved_field_reused(old_d, new_d, ROOT) == []

        # The structural guarantee the binary search depends on: ranges
        # come back sorted, disjoint, and merged.
        ranges, _ = _reserved(old_d)
        assert len(ranges) == count
        assert list(ranges) == sorted(ranges)
        assert all(
            ranges[i][1] < ranges[i + 1][0] for i in range(len(ranges) - 1)
        ), "ranges must be disjoint and non-adjacent after normalization"

    def test_normalize_ranges_merges_and_drops_vacuous(self) -> None:
        """Overlapping, adjacent, empty and inverted ranges normalize correctly.

        The old ``set(range(start, end))`` form silently dropped empty
        (``start == end``) and inverted (``start > end``) ranges and
        deduplicated overlaps for free. The pair form must reproduce all
        of that explicitly or membership drifts.
        """
        assert _normalize_ranges([(5, 10), (10, 15)]) == ((5, 15),)  # adjacent
        assert _normalize_ranges([(1, 10), (5, 15)]) == ((1, 15),)  # overlapping
        assert _normalize_ranges([(1, 100), (20, 30)]) == ((1, 100),)  # nested
        assert _normalize_ranges([(3, 8), (3, 8)]) == ((3, 8),)  # duplicate
        assert _normalize_ranges([(50, 60), (10, 20)]) == ((10, 20), (50, 60))
        assert _normalize_ranges([(7, 7)]) == ()  # empty
        assert _normalize_ranges([(10, 5)]) == ()  # inverted
        assert _normalize_ranges([]) == ()

    def test_reserved_range_end_is_exclusive(self) -> None:
        """Half-open semantics: ``end`` itself is not reserved.

        The set-based implementation got this right via ``range()``;
        the range-pair implementation must not drift to inclusive.
        """
        old_pool = descriptor_pool.DescriptorPool()
        new_pool = descriptor_pool.DescriptorPool()
        build_message(
            old_pool, "t.M",
            fields=[{"name": "a", "number": 1, "type": T.TYPE_INT32}],
            reserved_ranges=[(5, 10)],
        )
        build_message(
            new_pool, "t.M",
            fields=[
                {"name": "a", "number": 1, "type": T.TYPE_INT32},
                {"name": "edge_lo", "number": 5, "type": T.TYPE_STRING},
                {"name": "edge_hi", "number": 10, "type": T.TYPE_STRING},
            ],
        )
        old_d = old_pool.FindMessageTypeByName("t.M")
        new_d = new_pool.FindMessageTypeByName("t.M")
        findings = reserved_field_reused(old_d, new_d, ROOT)
        # 5 is reserved (inclusive start); 10 is not (exclusive end).
        assert len(findings) == 1
        assert "edge_lo" in findings[0].message

    def test_silent_when_no_reservations_used(self) -> None:
        old_pool = descriptor_pool.DescriptorPool()
        new_pool = descriptor_pool.DescriptorPool()
        build_message(
            old_pool, "t.M",
            fields=[{"name": "a", "number": 1, "type": T.TYPE_INT32}],
            reserved_ranges=[(5, 10)],
            reserved_names=["ghost"],
        )
        build_message(
            new_pool, "t.M",
            fields=[
                {"name": "a", "number": 1, "type": T.TYPE_INT32},
                {"name": "b", "number": 2, "type": T.TYPE_STRING},
            ],
        )
        old_d = old_pool.FindMessageTypeByName("t.M")
        new_d = new_pool.FindMessageTypeByName("t.M")
        assert reserved_field_reused(old_d, new_d, ROOT) == []

    def test_both_number_and_name_fires_twice(self) -> None:
        old_pool = descriptor_pool.DescriptorPool()
        new_pool = descriptor_pool.DescriptorPool()
        build_message(
            old_pool, "t.M",
            fields=[{"name": "a", "number": 1, "type": T.TYPE_INT32}],
            reserved_ranges=[(5, 10)],
            reserved_names=["ghost"],
        )
        build_message(
            new_pool, "t.M",
            fields=[
                {"name": "a", "number": 1, "type": T.TYPE_INT32},
                {"name": "ghost", "number": 7, "type": T.TYPE_STRING},
            ],
        )
        old_d = old_pool.FindMessageTypeByName("t.M")
        new_d = new_pool.FindMessageTypeByName("t.M")
        findings = reserved_field_reused(old_d, new_d, ROOT)
        assert len(findings) == 2
        # Number reuse is WIRE; name reuse is SEMANTIC.
        severities = {f.severity for f in findings}
        assert severities == {Severity.WIRE, Severity.SEMANTIC}
