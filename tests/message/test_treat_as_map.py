"""Tests for treat_as_map key-based repeated field matching."""

import pytest
from google.protobuf import descriptor_pb2

from protokit.message import (
    ChangeType,
    DuplicateKeyError,
    MessageDifferencer,
    MissingKeyError,
)
from tests.proto_builder import ProtoBuilder

T = descriptor_pb2.FieldDescriptorProto


def _make_items_builder() -> ProtoBuilder:
    """Message with repeated Item keyed by 'id'."""
    builder = ProtoBuilder()
    builder.message("test.Item", {
        "id": (T.TYPE_STRING, 1),
        "value": (T.TYPE_INT32, 2),
    })
    builder.message_with_repeated(
        "test.Container",
        {"items": (T.TYPE_MESSAGE, 1, ".test.Item")},
        repeated_fields={"items"},
    )
    return builder


def _make_int_key_builder() -> ProtoBuilder:
    """Message with repeated Entry keyed by int 'key'."""
    builder = ProtoBuilder()
    builder.message("test.Entry", {
        "key": (T.TYPE_INT32, 1),
        "name": (T.TYPE_STRING, 2),
    })
    builder.message_with_repeated(
        "test.Container",
        {"entries": (T.TYPE_MESSAGE, 1, ".test.Entry")},
        repeated_fields={"entries"},
    )
    return builder


class TestTreatAsMapEqual:
    def test_same_elements_same_order(self) -> None:
        b = _make_items_builder()
        Item = b.get_message_class("test.Item")
        msg1 = b.build("test.Container", items=[Item(id="a", value=1), Item(id="b", value=2)])
        msg2 = b.build("test.Container", items=[Item(id="a", value=1), Item(id="b", value=2)])
        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        result = d.compare(msg1, msg2)
        assert not result.has_changes()

    def test_same_elements_different_order(self) -> None:
        """Key-based matching should ignore order."""
        b = _make_items_builder()
        Item = b.get_message_class("test.Item")
        msg1 = b.build("test.Container", items=[Item(id="a", value=1), Item(id="b", value=2)])
        msg2 = b.build("test.Container", items=[Item(id="b", value=2), Item(id="a", value=1)])
        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        result = d.compare(msg1, msg2)
        assert not result.has_changes()


class TestTreatAsMapDifferences:
    def test_value_changed(self) -> None:
        b = _make_items_builder()
        Item = b.get_message_class("test.Item")
        msg1 = b.build("test.Container", items=[Item(id="a", value=1)])
        msg2 = b.build("test.Container", items=[Item(id="a", value=2)])
        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        result = d.compare(msg1, msg2)
        assert result.has_changes()
        diff = result.differences[0]
        assert diff.change_type == ChangeType.MODIFIED
        assert 'id="a"' in str(diff.path)

    def test_element_added(self) -> None:
        b = _make_items_builder()
        Item = b.get_message_class("test.Item")
        msg1 = b.build("test.Container", items=[Item(id="a", value=1)])
        msg2 = b.build("test.Container", items=[Item(id="a", value=1), Item(id="b", value=2)])
        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        result = d.compare(msg1, msg2)
        assert result.has_changes()
        added = [x for x in result if x.change_type == ChangeType.ADDED]
        assert len(added) >= 1

    def test_element_removed(self) -> None:
        b = _make_items_builder()
        Item = b.get_message_class("test.Item")
        msg1 = b.build("test.Container", items=[Item(id="a", value=1), Item(id="b", value=2)])
        msg2 = b.build("test.Container", items=[Item(id="a", value=1)])
        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        result = d.compare(msg1, msg2)
        removed = [x for x in result if x.change_type == ChangeType.REMOVED]
        assert len(removed) >= 1

    def test_int_key(self) -> None:
        b = _make_int_key_builder()
        Entry = b.get_message_class("test.Entry")
        msg1 = b.build("test.Container", entries=[Entry(key=1, name="one")])
        msg2 = b.build("test.Container", entries=[Entry(key=1, name="ONE")])
        d = MessageDifferencer()
        d.treat_as_map("entries", key="key")
        result = d.compare(msg1, msg2)
        assert result.has_changes()
        assert result.differences[0].change_type == ChangeType.MODIFIED


class TestTreatAsMapErrors:
    def test_duplicate_key_raises(self) -> None:
        b = _make_items_builder()
        Item = b.get_message_class("test.Item")
        msg1 = b.build("test.Container", items=[Item(id="a", value=1), Item(id="a", value=2)])
        msg2 = b.build("test.Container", items=[Item(id="a", value=1)])
        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        with pytest.raises(DuplicateKeyError):
            d.compare(msg1, msg2)


    def test_missing_key_raises(self) -> None:
        """Proto2 optional key field that is unset should raise MissingKeyError."""
        builder = ProtoBuilder()
        builder.message("test.Item", {
            "id": (T.TYPE_STRING, 1),
            "value": (T.TYPE_INT32, 2),
        }, syntax="proto2")
        builder.message_with_repeated(
            "test.Container",
            {"items": (T.TYPE_MESSAGE, 1, ".test.Item")},
            repeated_fields={"items"},
            syntax="proto2",
        )
        Item = builder.get_message_class("test.Item")
        # Create an element without setting the key field "id"
        msg1 = builder.build("test.Container", items=[Item(value=1)])
        msg2 = builder.build("test.Container", items=[Item(id="a", value=1)])
        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        with pytest.raises(MissingKeyError, match="missing key field 'id'"):
            d.compare(msg1, msg2)


class TestTreatAsMapNonMessage:
    def test_non_message_field_emits_warning_and_falls_back(self) -> None:
        """treat_as_map on a repeated scalar should warn and use index comparison."""
        builder = ProtoBuilder()
        builder.message_with_repeated(
            "test.Container",
            {"tags": (T.TYPE_STRING, 1)},
            repeated_fields={"tags"},
        )
        msg1 = builder.build("test.Container", tags=["a", "b"])
        msg2 = builder.build("test.Container", tags=["b", "a"])
        d = MessageDifferencer()
        d.treat_as_map("tags", key="id")
        result = d.compare(msg1, msg2)
        # Should have fallen back to index-based comparison (order matters)
        assert result.has_changes()
        # Should have emitted a warning about non-message field
        assert len(result.warnings) == 1
        assert "treat_as_map configured but field is not a repeated message" in result.warnings[0].message

    def test_non_message_field_equal_values(self) -> None:
        """treat_as_map on a repeated scalar with equal values should still work."""
        builder = ProtoBuilder()
        builder.message_with_repeated(
            "test.Container",
            {"tags": (T.TYPE_STRING, 1)},
            repeated_fields={"tags"},
        )
        msg1 = builder.build("test.Container", tags=["a", "b"])
        msg2 = builder.build("test.Container", tags=["a", "b"])
        d = MessageDifferencer()
        d.treat_as_map("tags", key="id")
        result = d.compare(msg1, msg2)
        assert not result.has_changes()
        # Warning should still be emitted
        assert len(result.warnings) == 1


class TestTreatAsMapDottedPath:
    def test_dotted_selector_matches_nested_field(self) -> None:
        """treat_as_map("wrapper.items", key="id") should match inside a singular parent."""
        builder = ProtoBuilder()
        builder.message("test.Item", {
            "id": (T.TYPE_STRING, 1),
            "value": (T.TYPE_INT32, 2),
        })
        builder.message_with_repeated(
            "test.Wrapper",
            {
                "name": (T.TYPE_STRING, 1),
                "items": (T.TYPE_MESSAGE, 2, ".test.Item"),
            },
            repeated_fields={"items"},
        )
        builder.message("test.Container", {
            "wrapper": (T.TYPE_MESSAGE, 1, ".test.Wrapper"),
        })
        Item = builder.get_message_class("test.Item")
        Wrapper = builder.get_message_class("test.Wrapper")
        msg1 = builder.get_message_class("test.Container")(
            wrapper=Wrapper(
                name="g1",
                items=[Item(id="a", value=1), Item(id="b", value=2)],
            )
        )
        msg2 = builder.get_message_class("test.Container")(
            wrapper=Wrapper(
                name="g1",
                items=[Item(id="b", value=2), Item(id="a", value=1)],
            )
        )
        d = MessageDifferencer()
        d.treat_as_map("wrapper.items", key="id")
        result = d.compare(msg1, msg2)
        # Key-based matching should ignore order
        assert not result.has_changes()


class TestTreatAsMapEmitAll:
    def test_added_subtree_uses_key_paths(self) -> None:
        """When an entire sub-message is added, treat_as_map fields inside
        should use key-based paths, not index-based."""
        # Left schema: Outer with just name
        b1 = ProtoBuilder()
        b1.message("test.Outer", {"name": (T.TYPE_STRING, 1)})

        # Right schema: Outer with name + inner (which has repeated items)
        b2 = ProtoBuilder()
        b2.message("test.Item", {
            "id": (T.TYPE_STRING, 1),
            "value": (T.TYPE_INT32, 2),
        })
        b2.message_with_repeated(
            "test.Inner",
            {"items": (T.TYPE_MESSAGE, 1, ".test.Item")},
            repeated_fields={"items"},
        )
        b2.message("test.Outer", {
            "name": (T.TYPE_STRING, 1),
            "inner": (T.TYPE_MESSAGE, 2, ".test.Inner"),
        })
        Item = b2.get_message_class("test.Item")
        Inner = b2.get_message_class("test.Inner")
        msg1 = b1.build("test.Outer", name="hello")
        msg2 = b2.build("test.Outer",
            name="hello",
            inner=Inner(items=[Item(id="a", value=1), Item(id="b", value=2)]),
        )
        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        result = d.compare(msg1, msg2)
        # Only ADDED diffs expected for a new subtree
        assert all(x.change_type == ChangeType.ADDED for x in result)
        added = list(result)
        # Paths should use key-based brackets
        paths = [str(x.path) for x in added]
        assert any('id="a"' in p for p in paths)
        assert any('id="b"' in p for p in paths)
        # Should NOT use index-based brackets
        assert not any("items[0]" in p for p in paths)
        assert not any("items[1]" in p for p in paths)


class TestTreatAsMapPath:
    def test_path_contains_key(self) -> None:
        """The diff path should include the key bracket notation."""
        b = _make_items_builder()
        Item = b.get_message_class("test.Item")
        msg1 = b.build("test.Container", items=[Item(id="x", value=1)])
        msg2 = b.build("test.Container", items=[Item(id="x", value=9)])
        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        result = d.compare(msg1, msg2)
        path_str = str(result.differences[0].path)
        assert 'id="x"' in path_str
