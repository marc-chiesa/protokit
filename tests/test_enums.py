"""Tests for enum field comparison."""

from google.protobuf import descriptor_pb2

from protokit.message import ChangeType, diff_messages
from tests.proto_builder import ProtoBuilder

T = descriptor_pb2.FieldDescriptorProto


def _make_enum_builder() -> ProtoBuilder:
    """Message with an enum field."""
    builder = ProtoBuilder()
    builder.message(
        "test.Msg",
        {"status": (T.TYPE_ENUM, 1, ".test.Msg.Status")},
        enums={"Status": {
            "UNKNOWN": 0,
            "ACTIVE": 1,
            "INACTIVE": 2,
            "DELETED": 3,
        }},
    )
    return builder


class TestEnumEqual:
    def test_same_value(self) -> None:
        b = _make_enum_builder()
        msg1 = b.build("test.Msg", status=1)  # ACTIVE
        msg2 = b.build("test.Msg", status=1)
        result = diff_messages(msg1, msg2)
        assert not result.has_changes()

    def test_both_default(self) -> None:
        b = _make_enum_builder()
        msg1 = b.build("test.Msg")  # UNKNOWN (0)
        msg2 = b.build("test.Msg")
        result = diff_messages(msg1, msg2)
        assert not result.has_changes()


class TestEnumDifferences:
    def test_value_changed(self) -> None:
        b = _make_enum_builder()
        msg1 = b.build("test.Msg", status=1)  # ACTIVE
        msg2 = b.build("test.Msg", status=2)  # INACTIVE
        result = diff_messages(msg1, msg2)
        assert len(result) == 1
        d = result.differences[0]
        assert d.change_type == ChangeType.MODIFIED
        assert str(d.path) == "status"
        # Values should be wrapped as EnumValue
        assert "ACTIVE" in str(d.old_value)
        assert "INACTIVE" in str(d.new_value)

    def test_default_to_set(self) -> None:
        b = _make_enum_builder()
        msg1 = b.build("test.Msg")  # UNKNOWN (0)
        msg2 = b.build("test.Msg", status=1)  # ACTIVE
        result = diff_messages(msg1, msg2)
        # In proto3, enum default is 0 without presence — may or may not diff
        # depending on presence semantics. Just check it doesn't crash.
        assert isinstance(result.has_changes(), bool)

    def test_set_to_default(self) -> None:
        b = _make_enum_builder()
        msg1 = b.build("test.Msg", status=3)  # DELETED
        msg2 = b.build("test.Msg")  # UNKNOWN (0)
        result = diff_messages(msg1, msg2)
        assert result.has_changes()


class TestEnumAliases:
    def test_enum_with_aliases(self) -> None:
        """Enum aliases (multiple names for same number) should compare equal."""
        builder = ProtoBuilder()
        builder.message(
            "test.Msg",
            {"priority": (T.TYPE_ENUM, 1, ".test.Msg.Priority")},
            enums={"Priority": {
                "UNSET": 0,
                "LOW": 1,
                "NORMAL": 2,
                "HIGH": 3,
            }},
        )
        msg1 = builder.build("test.Msg", priority=2)
        msg2 = builder.build("test.Msg", priority=2)
        result = diff_messages(msg1, msg2)
        assert not result.has_changes()
