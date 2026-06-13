"""Tests for ignore_fields functionality."""

import pytest
from google.protobuf import descriptor_pb2

from protokit.message import ChangeType, MessageDifferencer
from tests.proto_builder import ProtoBuilder

T = descriptor_pb2.FieldDescriptorProto


def _make_builder() -> ProtoBuilder:
    builder = ProtoBuilder()
    builder.message("test.Msg", {
        "id": (T.TYPE_INT32, 1),
        "name": (T.TYPE_STRING, 2),
        "age": (T.TYPE_INT32, 3),
    })
    return builder


class TestIgnoreBareField:
    def test_ignored_field_not_reported(self) -> None:
        b = _make_builder()
        msg1 = b.build("test.Msg", id=1, name="Alice", age=30)
        msg2 = b.build("test.Msg", id=1, name="Bob", age=31)
        d = MessageDifferencer()
        d.ignore_fields("name", "age")
        result = d.compare(msg1, msg2)
        assert not result.has_changes()

    def test_non_ignored_field_still_reported(self) -> None:
        b = _make_builder()
        msg1 = b.build("test.Msg", id=1, name="Alice", age=30)
        msg2 = b.build("test.Msg", id=2, name="Bob", age=30)
        d = MessageDifferencer()
        d.ignore_fields("name")
        result = d.compare(msg1, msg2)
        assert len(result) == 1
        assert str(result.differences[0].path) == "id"

    def test_bare_name_ignores_globally(self) -> None:
        """A bare name should match the field at any nesting level."""
        builder = ProtoBuilder()
        builder.message("test.Inner", {
            "name": (T.TYPE_STRING, 1),
            "score": (T.TYPE_INT32, 2),
        })
        builder.message("test.Outer", {
            "name": (T.TYPE_STRING, 1),
            "inner": (T.TYPE_MESSAGE, 2, ".test.Inner"),
        })
        Inner = builder.get_message_class("test.Inner")
        msg1 = builder.build("test.Outer", name="A", inner=Inner(name="X", score=1))
        msg2 = builder.build("test.Outer", name="B", inner=Inner(name="Y", score=1))
        d = MessageDifferencer()
        d.ignore_fields("name")
        result = d.compare(msg1, msg2)
        # Both top-level name and inner.name should be ignored
        assert not result.has_changes()


class TestIgnoreDottedPath:
    def test_path_scoped_ignore(self) -> None:
        """Dotted path should only ignore at that exact location."""
        builder = ProtoBuilder()
        builder.message("test.Inner", {
            "name": (T.TYPE_STRING, 1),
        })
        builder.message("test.Outer", {
            "name": (T.TYPE_STRING, 1),
            "inner": (T.TYPE_MESSAGE, 2, ".test.Inner"),
        })
        Inner = builder.get_message_class("test.Inner")
        msg1 = builder.build("test.Outer", name="A", inner=Inner(name="X"))
        msg2 = builder.build("test.Outer", name="B", inner=Inner(name="Y"))
        d = MessageDifferencer()
        d.ignore_fields("inner.name")
        result = d.compare(msg1, msg2)
        # Top-level name should still be reported
        assert len(result) == 1
        assert str(result.differences[0].path) == "name"


class TestIgnoreDottedPathRepeated:
    def test_dotted_ignore_inside_repeated_field(self) -> None:
        """ignore_fields("items.name") should match items[0].name, items[1].name etc."""
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
        msg1 = builder.build("test.Container", items=[
            Item(name="old_a", value=1), Item(name="old_b", value=2),
        ])
        msg2 = builder.build("test.Container", items=[
            Item(name="new_a", value=1), Item(name="new_b", value=2),
        ])
        d = MessageDifferencer()
        d.ignore_fields("items.name")
        result = d.compare(msg1, msg2)
        # name changes should be ignored; values are equal -> no diffs
        assert not result.has_changes()

    def test_dotted_ignore_inside_repeated_still_reports_other_fields(self) -> None:
        """Ignoring items.name should still report items.value changes."""
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
        msg1 = builder.build("test.Container", items=[Item(name="old", value=1)])
        msg2 = builder.build("test.Container", items=[Item(name="new", value=99)])
        d = MessageDifferencer()
        d.ignore_fields("items.name")
        result = d.compare(msg1, msg2)
        # Only value change should be reported
        assert len(result) == 1
        assert result.differences[0].change_type == ChangeType.MODIFIED
        assert "value" in str(result.differences[0].path)


class TestIgnoreFieldConflicts:
    def test_cannot_ignore_treat_as_map_field(self) -> None:
        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        with pytest.raises(ValueError):
            d.ignore_fields("items")

    def test_cannot_ignore_treat_as_map_key_field(self) -> None:
        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        with pytest.raises(ValueError):
            d.ignore_fields("id")
