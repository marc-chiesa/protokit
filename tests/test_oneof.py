"""Tests for oneof field comparison."""

from google.protobuf import descriptor_pb2

from proto_differ import ChangeType, diff_messages
from tests.proto_builder import ProtoBuilder

T = descriptor_pb2.FieldDescriptorProto


def _make_oneof_builder() -> ProtoBuilder:
    """Message with a oneof containing string and int."""
    builder = ProtoBuilder()
    builder.message(
        "test.Msg",
        {
            "text": (T.TYPE_STRING, 1),
            "number": (T.TYPE_INT32, 2),
        },
        oneofs={"value": ["text", "number"]},
    )
    return builder


class TestOneofEqual:
    def test_same_string_variant(self) -> None:
        b = _make_oneof_builder()
        msg1 = b.build("test.Msg", text="hello")
        msg2 = b.build("test.Msg", text="hello")
        result = diff_messages(msg1, msg2)
        assert not result.has_changes()

    def test_same_int_variant(self) -> None:
        b = _make_oneof_builder()
        msg1 = b.build("test.Msg", number=42)
        msg2 = b.build("test.Msg", number=42)
        result = diff_messages(msg1, msg2)
        assert not result.has_changes()

    def test_both_unset(self) -> None:
        b = _make_oneof_builder()
        msg1 = b.build("test.Msg")
        msg2 = b.build("test.Msg")
        result = diff_messages(msg1, msg2)
        assert not result.has_changes()


class TestOneofDifferences:
    def test_same_variant_different_value(self) -> None:
        b = _make_oneof_builder()
        msg1 = b.build("test.Msg", text="hello")
        msg2 = b.build("test.Msg", text="world")
        result = diff_messages(msg1, msg2)
        assert len(result) == 1
        d = result.differences[0]
        assert d.change_type == ChangeType.MODIFIED
        assert str(d.path) == "text"

    def test_switch_variant_string_to_int(self) -> None:
        """Switching oneof variant: old field removed, new field added."""
        b = _make_oneof_builder()
        msg1 = b.build("test.Msg", text="hello")
        msg2 = b.build("test.Msg", number=42)
        result = diff_messages(msg1, msg2)
        assert result.has_changes()
        types = {d.change_type for d in result}
        # Should see REMOVED for text and ADDED for number
        assert ChangeType.REMOVED in types
        assert ChangeType.ADDED in types

    def test_switch_variant_int_to_string(self) -> None:
        b = _make_oneof_builder()
        msg1 = b.build("test.Msg", number=42)
        msg2 = b.build("test.Msg", text="hello")
        result = diff_messages(msg1, msg2)
        assert result.has_changes()

    def test_unset_to_set(self) -> None:
        b = _make_oneof_builder()
        msg1 = b.build("test.Msg")
        msg2 = b.build("test.Msg", text="hello")
        result = diff_messages(msg1, msg2)
        assert result.has_changes()
        assert result.differences[0].change_type == ChangeType.ADDED

    def test_set_to_unset(self) -> None:
        b = _make_oneof_builder()
        msg1 = b.build("test.Msg", text="hello")
        msg2 = b.build("test.Msg")
        result = diff_messages(msg1, msg2)
        assert result.has_changes()
        assert result.differences[0].change_type == ChangeType.REMOVED


class TestOneofWithOtherFields:
    def test_oneof_plus_regular_field(self) -> None:
        builder = ProtoBuilder()
        builder.message(
            "test.Msg",
            {
                "id": (T.TYPE_INT32, 1),
                "text": (T.TYPE_STRING, 2),
                "number": (T.TYPE_INT32, 3),
            },
            oneofs={"value": ["text", "number"]},
        )
        msg1 = builder.build("test.Msg", id=1, text="hello")
        msg2 = builder.build("test.Msg", id=2, number=42)
        result = diff_messages(msg1, msg2)
        assert result.has_changes()
        paths = {str(d.path) for d in result}
        assert "id" in paths
