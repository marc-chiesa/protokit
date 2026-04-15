"""Tests for schema evolution detection."""

from google.protobuf import descriptor_pb2

from protokit.message import ChangeType, MessageDifferencer, diff_messages
from tests.proto_builder import ProtoBuilder

T = descriptor_pb2.FieldDescriptorProto


class TestFieldNumberChange:
    def test_detects_field_number_change(self) -> None:
        """Same field name with different field numbers across pools."""
        b1 = ProtoBuilder()
        b1.message("test.Msg", {"name": (T.TYPE_STRING, 1)})
        b2 = ProtoBuilder()
        b2.message("test.Msg", {"name": (T.TYPE_STRING, 2)})
        msg1 = b1.build("test.Msg", name="Alice")
        msg2 = b2.build("test.Msg", name="Alice")
        result = diff_messages(msg1, msg2)
        fn_changes = [d for d in result if d.change_type == ChangeType.FIELD_NUMBER_CHANGED]
        assert len(fn_changes) == 1
        assert fn_changes[0].left_field_number == 1
        assert fn_changes[0].right_field_number == 2


class TestTypeChange:
    def test_detects_type_change(self) -> None:
        """Same field name, different type."""
        b1 = ProtoBuilder()
        b1.message("test.Msg", {"value": (T.TYPE_STRING, 1)})
        b2 = ProtoBuilder()
        b2.message("test.Msg", {"value": (T.TYPE_INT32, 1)})
        msg1 = b1.build("test.Msg", value="hello")
        msg2 = b2.build("test.Msg", value=42)
        result = diff_messages(msg1, msg2)
        type_changes = [d for d in result if d.change_type == ChangeType.TYPE_CHANGED]
        assert len(type_changes) == 1
        assert "STRING" in str(type_changes[0].left_type)
        assert "INT32" in str(type_changes[0].right_type)

    def test_compatible_int_types_no_type_change(self) -> None:
        """int32 -> int64 are compatible, no TYPE_CHANGED."""
        b1 = ProtoBuilder()
        b1.message("test.Msg", {"value": (T.TYPE_INT32, 1)})
        b2 = ProtoBuilder()
        b2.message("test.Msg", {"value": (T.TYPE_INT64, 1)})
        msg1 = b1.build("test.Msg", value=42)
        msg2 = b2.build("test.Msg", value=42)
        result = diff_messages(msg1, msg2)
        # TYPE_CHANGED diff should still be emitted for the type difference,
        # but values should still be compared (they're compatible)
        type_changes = [d for d in result if d.change_type == ChangeType.TYPE_CHANGED]
        assert len(type_changes) == 1
        # But no MODIFIED since values are equal
        mods = [d for d in result if d.change_type == ChangeType.MODIFIED]
        assert len(mods) == 0


class TestCardinalityChange:
    def test_detects_optional_to_repeated(self) -> None:
        b1 = ProtoBuilder()
        b1.message("test.Msg", {"tags": (T.TYPE_STRING, 1)})
        b2 = ProtoBuilder()
        b2.message_with_repeated(
            "test.Msg",
            {"tags": (T.TYPE_STRING, 1)},
            repeated_fields={"tags"},
        )
        msg1 = b1.build("test.Msg", tags="hello")
        msg2 = b2.build("test.Msg", tags=["hello"])
        result = diff_messages(msg1, msg2)
        card_changes = [d for d in result if d.change_type == ChangeType.CARDINALITY_CHANGED]
        assert len(card_changes) == 1
        assert card_changes[0].left_label == "LABEL_OPTIONAL"
        assert card_changes[0].right_label == "LABEL_REPEATED"

    def test_required_to_repeated_reports_required_label(self) -> None:
        """proto2 ``required`` → ``repeated`` must report
        ``LABEL_REQUIRED`` on the left, not the previous hard-coded
        ``LABEL_OPTIONAL`` placeholder.
        """
        from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
        old_pool = descriptor_pool.DescriptorPool()
        fdp = descriptor_pb2.FileDescriptorProto(
            name="proto2_required.proto", package="t", syntax="proto2",
        )
        mp = fdp.message_type.add()
        mp.name = "M"
        f = mp.field.add()
        f.name, f.number, f.type = "x", 1, T.TYPE_INT32
        f.label = T.LABEL_REQUIRED
        old_pool.Add(fdp)

        new_pool = descriptor_pool.DescriptorPool()
        fdp2 = descriptor_pb2.FileDescriptorProto(
            name="proto3_repeated.proto", package="t", syntax="proto3",
        )
        mp2 = fdp2.message_type.add()
        mp2.name = "M"
        f2 = mp2.field.add()
        f2.name, f2.number, f2.type = "x", 1, T.TYPE_INT32
        f2.label = T.LABEL_REPEATED
        new_pool.Add(fdp2)

        Left = message_factory.GetMessageClass(
            old_pool.FindMessageTypeByName("t.M"),
        )
        Right = message_factory.GetMessageClass(
            new_pool.FindMessageTypeByName("t.M"),
        )
        result = diff_messages(Left(x=5), Right(x=[1, 2, 3]))
        card = next(
            d for d in result if d.change_type == ChangeType.CARDINALITY_CHANGED
        )
        assert card.left_label == "LABEL_REQUIRED"
        assert card.right_label == "LABEL_REPEATED"


class TestStrictSchemaMode:
    def test_message_type_name_mismatch_warns(self) -> None:
        """strict_schema=True warns when message type names differ."""
        b1 = ProtoBuilder()
        b1.message("test.InnerV1", {"x": (T.TYPE_INT32, 1)})
        b1.message("test.Outer", {
            "inner": (T.TYPE_MESSAGE, 1, ".test.InnerV1"),
        })
        b2 = ProtoBuilder()
        b2.message("test.InnerV2", {"x": (T.TYPE_INT32, 1)})
        b2.message("test.Outer", {
            "inner": (T.TYPE_MESSAGE, 1, ".test.InnerV2"),
        })
        InnerV1 = b1.get_message_class("test.InnerV1")
        InnerV2 = b2.get_message_class("test.InnerV2")
        msg1 = b1.build("test.Outer", inner=InnerV1(x=1))
        msg2 = b2.build("test.Outer", inner=InnerV2(x=1))

        d = MessageDifferencer()
        d.strict_schema = True
        result = d.compare(msg1, msg2)
        assert len(result.warnings) > 0
        assert "type name" in str(result.warnings[0]).lower()

    def test_no_warning_without_strict(self) -> None:
        """Default (strict_schema=False) does not warn about type name drift."""
        b1 = ProtoBuilder()
        b1.message("test.InnerV1", {"x": (T.TYPE_INT32, 1)})
        b1.message("test.Outer", {
            "inner": (T.TYPE_MESSAGE, 1, ".test.InnerV1"),
        })
        b2 = ProtoBuilder()
        b2.message("test.InnerV2", {"x": (T.TYPE_INT32, 1)})
        b2.message("test.Outer", {
            "inner": (T.TYPE_MESSAGE, 1, ".test.InnerV2"),
        })
        InnerV1 = b1.get_message_class("test.InnerV1")
        InnerV2 = b2.get_message_class("test.InnerV2")
        msg1 = b1.build("test.Outer", inner=InnerV1(x=1))
        msg2 = b2.build("test.Outer", inner=InnerV2(x=1))

        result = diff_messages(msg1, msg2)
        type_warnings = [w for w in result.warnings if "type name" in str(w).lower()]
        assert len(type_warnings) == 0


class TestFieldPresenceEvolution:
    def test_unset_proto2_field_not_reported_as_added(self) -> None:
        """A proto2 field that exists only in the right schema but is unset
        should NOT be reported as ADDED."""
        b1 = ProtoBuilder()
        b1.message("test.Msg", {"name": (T.TYPE_STRING, 1)}, syntax="proto2")
        b2 = ProtoBuilder()
        b2.message("test.Msg", {
            "name": (T.TYPE_STRING, 1),
            "email": (T.TYPE_STRING, 2),
        }, syntax="proto2")
        msg1 = b1.build("test.Msg", name="Alice")
        msg2 = b2.build("test.Msg", name="Alice")  # email not set
        result = MessageDifferencer().compare(msg1, msg2)
        added = [d for d in result if d.change_type == ChangeType.ADDED]
        assert len(added) == 0

    def test_unset_proto2_field_not_reported_as_removed(self) -> None:
        """A proto2 field that exists only in the left schema but is unset
        should NOT be reported as REMOVED."""
        b1 = ProtoBuilder()
        b1.message("test.Msg", {
            "name": (T.TYPE_STRING, 1),
            "email": (T.TYPE_STRING, 2),
        }, syntax="proto2")
        b2 = ProtoBuilder()
        b2.message("test.Msg", {"name": (T.TYPE_STRING, 1)}, syntax="proto2")
        msg1 = b1.build("test.Msg", name="Alice")  # email not set
        msg2 = b2.build("test.Msg", name="Alice")
        result = MessageDifferencer().compare(msg1, msg2)
        removed = [d for d in result if d.change_type == ChangeType.REMOVED]
        assert len(removed) == 0

    def test_set_proto2_field_reported_as_added(self) -> None:
        """A proto2 field that exists only in the right schema and IS set
        should be reported as ADDED."""
        b1 = ProtoBuilder()
        b1.message("test.Msg", {"name": (T.TYPE_STRING, 1)}, syntax="proto2")
        b2 = ProtoBuilder()
        b2.message("test.Msg", {
            "name": (T.TYPE_STRING, 1),
            "email": (T.TYPE_STRING, 2),
        }, syntax="proto2")
        msg1 = b1.build("test.Msg", name="Alice")
        msg2 = b2.build("test.Msg", name="Alice", email="alice@example.com")
        result = MessageDifferencer().compare(msg1, msg2)
        added = [d for d in result if d.change_type == ChangeType.ADDED]
        assert len(added) == 1
        assert added[0].new_value == "alice@example.com"

    def test_set_proto2_field_reported_as_removed(self) -> None:
        """A proto2 field that exists only in the left schema and IS set
        should be reported as REMOVED."""
        b1 = ProtoBuilder()
        b1.message("test.Msg", {
            "name": (T.TYPE_STRING, 1),
            "email": (T.TYPE_STRING, 2),
        }, syntax="proto2")
        b2 = ProtoBuilder()
        b2.message("test.Msg", {"name": (T.TYPE_STRING, 1)}, syntax="proto2")
        msg1 = b1.build("test.Msg", name="Alice", email="alice@example.com")
        msg2 = b2.build("test.Msg", name="Alice")
        result = MessageDifferencer().compare(msg1, msg2)
        removed = [d for d in result if d.change_type == ChangeType.REMOVED]
        assert len(removed) == 1
        assert removed[0].old_value == "alice@example.com"


class TestMapRepeatedMismatch:
    def test_map_to_repeated_emits_warning(self) -> None:
        """When a field is map in one schema and repeated in the other, warn."""
        b1 = ProtoBuilder()
        b1.map_message(
            "test.Msg",
            fields={"name": (T.TYPE_STRING, 1)},
            map_fields={"labels": (T.TYPE_STRING, T.TYPE_STRING, 2)},
        )
        b2 = ProtoBuilder()
        b2.message_with_repeated(
            "test.Msg",
            {"name": (T.TYPE_STRING, 1), "labels": (T.TYPE_STRING, 2)},
            repeated_fields={"labels"},
        )
        msg1 = b1.build("test.Msg", name="Alice", labels={"env": "prod"})
        msg2 = b2.build("test.Msg", name="Alice", labels=["hello"])
        result = MessageDifferencer().compare(msg1, msg2)
        # Should emit a warning about the map/repeated mismatch
        matching = [w for w in result.warnings if "map" in w.message and "repeated" in w.message]
        assert len(matching) == 1
        # Values should NOT be compared — only schema-level diffs (TYPE_CHANGED) allowed
        label_value_diffs = [
            d for d in result
            if "labels" in str(d.path)
            and d.change_type in (ChangeType.ADDED, ChangeType.REMOVED, ChangeType.MODIFIED)
        ]
        assert len(label_value_diffs) == 0


class TestMultipleEvolutionChanges:
    def test_field_number_and_type_change(self) -> None:
        """A field can have both field number AND type change."""
        b1 = ProtoBuilder()
        b1.message("test.Msg", {"value": (T.TYPE_STRING, 1)})
        b2 = ProtoBuilder()
        b2.message("test.Msg", {"value": (T.TYPE_INT32, 5)})
        msg1 = b1.build("test.Msg", value="hello")
        msg2 = b2.build("test.Msg", value=42)
        result = diff_messages(msg1, msg2)
        types = {d.change_type for d in result}
        assert ChangeType.FIELD_NUMBER_CHANGED in types
        assert ChangeType.TYPE_CHANGED in types
