"""Tests for repeated field comparison."""

from google.protobuf import descriptor_pb2

from proto_differ import ChangeType, diff_messages
from tests.proto_builder import ProtoBuilder

T = descriptor_pb2.FieldDescriptorProto


def _make_tags_builder() -> ProtoBuilder:
    """Message with a repeated string field."""
    builder = ProtoBuilder()
    builder.message_with_repeated(
        "test.Msg",
        {"tags": (T.TYPE_STRING, 1)},
        repeated_fields={"tags"},
    )
    return builder


def _make_repeated_int_builder() -> ProtoBuilder:
    builder = ProtoBuilder()
    builder.message_with_repeated(
        "test.Msg",
        {"values": (T.TYPE_INT32, 1)},
        repeated_fields={"values"},
    )
    return builder


class TestRepeatedEqual:
    def test_same_elements(self) -> None:
        b = _make_tags_builder()
        msg1 = b.build("test.Msg", tags=["a", "b", "c"])
        msg2 = b.build("test.Msg", tags=["a", "b", "c"])
        result = diff_messages(msg1, msg2)
        assert not result.has_changes()

    def test_both_empty(self) -> None:
        b = _make_tags_builder()
        msg1 = b.build("test.Msg")
        msg2 = b.build("test.Msg")
        result = diff_messages(msg1, msg2)
        assert not result.has_changes()

    def test_same_ints(self) -> None:
        b = _make_repeated_int_builder()
        msg1 = b.build("test.Msg", values=[1, 2, 3])
        msg2 = b.build("test.Msg", values=[1, 2, 3])
        result = diff_messages(msg1, msg2)
        assert not result.has_changes()


class TestRepeatedModified:
    def test_element_changed(self) -> None:
        b = _make_tags_builder()
        msg1 = b.build("test.Msg", tags=["a", "b", "c"])
        msg2 = b.build("test.Msg", tags=["a", "X", "c"])
        result = diff_messages(msg1, msg2)
        assert len(result) == 1
        d = result.differences[0]
        assert d.change_type == ChangeType.MODIFIED
        assert d.old_value == "b"
        assert d.new_value == "X"
        assert "[1]" in str(d.path)

    def test_multiple_elements_changed(self) -> None:
        b = _make_repeated_int_builder()
        msg1 = b.build("test.Msg", values=[1, 2, 3])
        msg2 = b.build("test.Msg", values=[1, 9, 8])
        result = diff_messages(msg1, msg2)
        assert len(result) == 2


class TestRepeatedAddedRemoved:
    def test_elements_added(self) -> None:
        b = _make_tags_builder()
        msg1 = b.build("test.Msg", tags=["a"])
        msg2 = b.build("test.Msg", tags=["a", "b", "c"])
        result = diff_messages(msg1, msg2)
        added = [d for d in result if d.change_type == ChangeType.ADDED]
        assert len(added) == 2

    def test_elements_removed(self) -> None:
        b = _make_tags_builder()
        msg1 = b.build("test.Msg", tags=["a", "b", "c"])
        msg2 = b.build("test.Msg", tags=["a"])
        result = diff_messages(msg1, msg2)
        removed = [d for d in result if d.change_type == ChangeType.REMOVED]
        assert len(removed) == 2

    def test_empty_to_populated(self) -> None:
        b = _make_tags_builder()
        msg1 = b.build("test.Msg")
        msg2 = b.build("test.Msg", tags=["a", "b"])
        result = diff_messages(msg1, msg2)
        assert len(result) == 2
        assert all(d.change_type == ChangeType.ADDED for d in result)

    def test_populated_to_empty(self) -> None:
        b = _make_tags_builder()
        msg1 = b.build("test.Msg", tags=["a", "b"])
        msg2 = b.build("test.Msg")
        result = diff_messages(msg1, msg2)
        assert len(result) == 2
        assert all(d.change_type == ChangeType.REMOVED for d in result)


class TestRepeatedMessage:
    def test_nested_message_in_repeated(self) -> None:
        builder = ProtoBuilder()
        builder.message("test.Item", {
            "name": (T.TYPE_STRING, 1),
            "value": (T.TYPE_INT32, 2),
        })
        builder.message_with_repeated(
            "test.Container",
            {"items": (T.TYPE_MESSAGE, 1, ".test.Item")},
            repeated_fields={"items"},
        )
        Item = builder.get_message_class("test.Item")
        msg1 = builder.build("test.Container", items=[Item(name="a", value=1)])
        msg2 = builder.build("test.Container", items=[Item(name="a", value=2)])
        result = diff_messages(msg1, msg2)
        assert len(result) == 1
        assert result.differences[0].change_type == ChangeType.MODIFIED

    def test_repeated_message_added(self) -> None:
        builder = ProtoBuilder()
        builder.message("test.Item", {"name": (T.TYPE_STRING, 1)})
        builder.message_with_repeated(
            "test.Container",
            {"items": (T.TYPE_MESSAGE, 1, ".test.Item")},
            repeated_fields={"items"},
        )
        Item = builder.get_message_class("test.Item")
        msg1 = builder.build("test.Container", items=[Item(name="a")])
        msg2 = builder.build("test.Container", items=[Item(name="a"), Item(name="b")])
        result = diff_messages(msg1, msg2)
        added = [d for d in result if d.change_type == ChangeType.ADDED]
        assert len(added) >= 1
