"""Tests for cross-descriptor-pool comparison."""

from google.protobuf import descriptor_pb2

from proto_differ import ChangeType, diff_messages
from tests.proto_builder import ProtoBuilder

T = descriptor_pb2.FieldDescriptorProto


class TestCrossPoolEqual:
    def test_same_schema_different_pools(self) -> None:
        """Two identical schemas in separate pools should compare equal."""
        b1 = ProtoBuilder()
        b1.message("test.Msg", {
            "name": (T.TYPE_STRING, 1),
            "value": (T.TYPE_INT32, 2),
        })
        b2 = ProtoBuilder()
        b2.message("test.Msg", {
            "name": (T.TYPE_STRING, 1),
            "value": (T.TYPE_INT32, 2),
        })
        msg1 = b1.build("test.Msg", name="Alice", value=42)
        msg2 = b2.build("test.Msg", name="Alice", value=42)
        result = diff_messages(msg1, msg2)
        assert not result.has_changes()


class TestCrossPoolDifferences:
    def test_value_change_detected(self) -> None:
        b1 = ProtoBuilder()
        b1.message("test.Msg", {"name": (T.TYPE_STRING, 1)})
        b2 = ProtoBuilder()
        b2.message("test.Msg", {"name": (T.TYPE_STRING, 1)})
        msg1 = b1.build("test.Msg", name="Alice")
        msg2 = b2.build("test.Msg", name="Bob")
        result = diff_messages(msg1, msg2)
        assert len(result) == 1
        assert result.differences[0].change_type == ChangeType.MODIFIED


class TestCrossPoolFieldMismatch:
    def test_field_only_in_left(self) -> None:
        """Left schema has a field that right schema doesn't."""
        b1 = ProtoBuilder()
        b1.message("test.Msg", {
            "name": (T.TYPE_STRING, 1),
            "extra": (T.TYPE_STRING, 2),
        })
        b2 = ProtoBuilder()
        b2.message("test.Msg", {
            "name": (T.TYPE_STRING, 1),
        })
        msg1 = b1.build("test.Msg", name="Alice", extra="data")
        msg2 = b2.build("test.Msg", name="Alice")
        result = diff_messages(msg1, msg2)
        assert result.has_changes()
        paths = {str(d.path) for d in result}
        assert "extra" in paths

    def test_field_only_in_right(self) -> None:
        b1 = ProtoBuilder()
        b1.message("test.Msg", {
            "name": (T.TYPE_STRING, 1),
        })
        b2 = ProtoBuilder()
        b2.message("test.Msg", {
            "name": (T.TYPE_STRING, 1),
            "extra": (T.TYPE_STRING, 2),
        })
        msg1 = b1.build("test.Msg", name="Alice")
        msg2 = b2.build("test.Msg", name="Alice", extra="data")
        result = diff_messages(msg1, msg2)
        assert result.has_changes()

    def test_field_type_changed_across_pools(self) -> None:
        """Same field name but different type across pools."""
        b1 = ProtoBuilder()
        b1.message("test.Msg", {"value": (T.TYPE_STRING, 1)})
        b2 = ProtoBuilder()
        b2.message("test.Msg", {"value": (T.TYPE_INT32, 1)})
        msg1 = b1.build("test.Msg", value="hello")
        msg2 = b2.build("test.Msg", value=42)
        result = diff_messages(msg1, msg2)
        # Should detect TYPE_CHANGED
        type_changes = [d for d in result if d.change_type == ChangeType.TYPE_CHANGED]
        assert len(type_changes) == 1


class TestCrossPoolEnums:
    def test_enum_same_name_same_number(self) -> None:
        b1 = ProtoBuilder()
        b1.message(
            "test.Msg",
            {"status": (T.TYPE_ENUM, 1, ".test.Msg.Status")},
            enums={"Status": {"UNKNOWN": 0, "ACTIVE": 1}},
        )
        b2 = ProtoBuilder()
        b2.message(
            "test.Msg",
            {"status": (T.TYPE_ENUM, 1, ".test.Msg.Status")},
            enums={"Status": {"UNKNOWN": 0, "ACTIVE": 1}},
        )
        msg1 = b1.build("test.Msg", status=1)
        msg2 = b2.build("test.Msg", status=1)
        result = diff_messages(msg1, msg2)
        assert not result.has_changes()

    def test_enum_wire_compatible_different_name(self) -> None:
        """Same number, different name -> wire-compatible, equal."""
        b1 = ProtoBuilder()
        b1.message(
            "test.Msg",
            {"status": (T.TYPE_ENUM, 1, ".test.Msg.Status")},
            enums={"Status": {"UNKNOWN": 0, "ACTIVE": 1}},
        )
        b2 = ProtoBuilder()
        b2.message(
            "test.Msg",
            {"status": (T.TYPE_ENUM, 1, ".test.Msg.Status")},
            enums={"Status": {"UNKNOWN": 0, "ENABLED": 1}},
        )
        msg1 = b1.build("test.Msg", status=1)
        msg2 = b2.build("test.Msg", status=1)
        result = diff_messages(msg1, msg2)
        # Wire-compatible: same number -> equal
        assert not result.has_changes()

    def test_enum_different_name_different_number(self) -> None:
        """Different name AND different number -> not equal."""
        b1 = ProtoBuilder()
        b1.message(
            "test.Msg",
            {"status": (T.TYPE_ENUM, 1, ".test.Msg.Status")},
            enums={"Status": {"UNKNOWN": 0, "ACTIVE": 1, "DELETED": 2}},
        )
        b2 = ProtoBuilder()
        b2.message(
            "test.Msg",
            {"status": (T.TYPE_ENUM, 1, ".test.Msg.Status")},
            enums={"Status": {"UNKNOWN": 0, "ACTIVE": 1, "ARCHIVED": 3}},
        )
        msg1 = b1.build("test.Msg", status=2)  # DELETED
        msg2 = b2.build("test.Msg", status=3)  # ARCHIVED
        result = diff_messages(msg1, msg2)
        assert result.has_changes()

    def test_enum_name_match_number_drift_warns(self) -> None:
        """Same name, different number -> equal with warning."""
        b1 = ProtoBuilder()
        b1.message(
            "test.Msg",
            {"status": (T.TYPE_ENUM, 1, ".test.Msg.Status")},
            enums={"Status": {"UNKNOWN": 0, "ACTIVE": 1}},
        )
        b2 = ProtoBuilder()
        b2.message(
            "test.Msg",
            {"status": (T.TYPE_ENUM, 1, ".test.Msg.Status")},
            enums={"Status": {"UNKNOWN": 0, "ACTIVE": 2}},
        )
        msg1 = b1.build("test.Msg", status=1)  # ACTIVE(1)
        msg2 = b2.build("test.Msg", status=2)  # ACTIVE(2)
        result = diff_messages(msg1, msg2)
        # Should be considered equal but with a warning
        assert not result.has_changes()
        assert len(result.warnings) > 0
        assert "number" in str(result.warnings[0]).lower()
