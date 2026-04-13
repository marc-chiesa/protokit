"""Tests for native protobuf map field comparison."""

from google.protobuf import descriptor_pb2, descriptor_pool

from proto_differ import ChangeType, diff_messages
from tests.proto_builder import ProtoBuilder

T = descriptor_pb2.FieldDescriptorProto


def _make_string_map_builder() -> ProtoBuilder:
    """Message with map<string, string>."""
    builder = ProtoBuilder()
    builder.map_message(
        "test.Msg",
        fields={},
        map_fields={"labels": (T.TYPE_STRING, T.TYPE_STRING, 1)},
    )
    return builder


def _make_int_map_builder() -> ProtoBuilder:
    """Message with map<int32, string>."""
    builder = ProtoBuilder()
    builder.map_message(
        "test.Msg",
        fields={},
        map_fields={"counts": (T.TYPE_INT32, T.TYPE_STRING, 1)},
    )
    return builder


class TestMapEqual:
    def test_same_entries(self) -> None:
        b = _make_string_map_builder()
        msg1 = b.build("test.Msg", labels={"env": "prod", "app": "web"})
        msg2 = b.build("test.Msg", labels={"env": "prod", "app": "web"})
        result = diff_messages(msg1, msg2)
        assert not result.has_changes()

    def test_both_empty(self) -> None:
        b = _make_string_map_builder()
        msg1 = b.build("test.Msg")
        msg2 = b.build("test.Msg")
        result = diff_messages(msg1, msg2)
        assert not result.has_changes()


class TestMapModified:
    def test_value_changed(self) -> None:
        b = _make_string_map_builder()
        msg1 = b.build("test.Msg", labels={"env": "prod"})
        msg2 = b.build("test.Msg", labels={"env": "staging"})
        result = diff_messages(msg1, msg2)
        assert len(result) == 1
        d = result.differences[0]
        assert d.change_type == ChangeType.MODIFIED
        assert d.old_value == "prod"
        assert d.new_value == "staging"
        assert '"env"' in str(d.path)


class TestMapAddedRemoved:
    def test_key_added(self) -> None:
        b = _make_string_map_builder()
        msg1 = b.build("test.Msg", labels={"env": "prod"})
        msg2 = b.build("test.Msg", labels={"env": "prod", "app": "web"})
        result = diff_messages(msg1, msg2)
        assert len(result) == 1
        d = result.differences[0]
        assert d.change_type == ChangeType.ADDED
        assert d.new_value == "web"

    def test_key_removed(self) -> None:
        b = _make_string_map_builder()
        msg1 = b.build("test.Msg", labels={"env": "prod", "app": "web"})
        msg2 = b.build("test.Msg", labels={"env": "prod"})
        result = diff_messages(msg1, msg2)
        assert len(result) == 1
        d = result.differences[0]
        assert d.change_type == ChangeType.REMOVED

    def test_empty_to_populated(self) -> None:
        b = _make_string_map_builder()
        msg1 = b.build("test.Msg")
        msg2 = b.build("test.Msg", labels={"a": "1", "b": "2"})
        result = diff_messages(msg1, msg2)
        assert len(result) == 2
        assert all(d.change_type == ChangeType.ADDED for d in result)

    def test_int_key_map(self) -> None:
        b = _make_int_map_builder()
        msg1 = b.build("test.Msg", counts={1: "one"})
        msg2 = b.build("test.Msg", counts={1: "one", 2: "two"})
        result = diff_messages(msg1, msg2)
        assert len(result) == 1
        assert result.differences[0].change_type == ChangeType.ADDED


class TestMapCrossSchema:
    def test_map_only_on_right_uses_key_paths(self) -> None:
        """A map field added in the right schema should use key-based paths."""
        b1 = ProtoBuilder()
        b1.message("test.Msg", {"name": (T.TYPE_STRING, 1)})
        b2 = ProtoBuilder()
        b2.map_message(
            "test.Msg",
            fields={"name": (T.TYPE_STRING, 1)},
            map_fields={"labels": (T.TYPE_STRING, T.TYPE_STRING, 2)},
        )
        msg1 = b1.build("test.Msg", name="Alice")
        msg2 = b2.build("test.Msg", name="Alice", labels={"env": "prod"})
        result = diff_messages(msg1, msg2)
        added = [d for d in result if d.change_type == ChangeType.ADDED]
        assert len(added) == 1
        path_str = str(added[0].path)
        assert '"env"' in path_str
        assert added[0].new_value == "prod"

    def test_map_only_on_left_uses_key_paths(self) -> None:
        """A map field removed in the right schema should use key-based paths."""
        b1 = ProtoBuilder()
        b1.map_message(
            "test.Msg",
            fields={"name": (T.TYPE_STRING, 1)},
            map_fields={"labels": (T.TYPE_STRING, T.TYPE_STRING, 2)},
        )
        b2 = ProtoBuilder()
        b2.message("test.Msg", {"name": (T.TYPE_STRING, 1)})
        msg1 = b1.build("test.Msg", name="Alice", labels={"env": "prod"})
        msg2 = b2.build("test.Msg", name="Alice")
        result = diff_messages(msg1, msg2)
        removed = [d for d in result if d.change_type == ChangeType.REMOVED]
        assert len(removed) == 1
        path_str = str(removed[0].path)
        assert '"env"' in path_str
        assert removed[0].old_value == "prod"


def _make_message_value_map_builder() -> ProtoBuilder:
    """Message with map<string, Inner> where Inner has scalar fields.

    Builds the descriptor manually since ProtoBuilder.map_message only
    supports scalar value types.
    """
    pool = descriptor_pool.DescriptorPool()
    file_proto = descriptor_pb2.FileDescriptorProto(
        name="msg_map.proto", package="test", syntax="proto3",
    )

    # Inner message
    inner = file_proto.message_type.add()
    inner.name = "Inner"
    f = inner.field.add()
    f.name, f.number, f.type = "x", 1, T.TYPE_INT32
    f.label = T.LABEL_OPTIONAL
    f2 = inner.field.add()
    f2.name, f2.number, f2.type = "y", 2, T.TYPE_STRING
    f2.label = T.LABEL_OPTIONAL

    # Outer message with map<string, Inner>
    outer = file_proto.message_type.add()
    outer.name = "Outer"

    # MapEntry nested type
    entry = outer.nested_type.add()
    entry.name = "DataEntry"
    entry.options.CopyFrom(descriptor_pb2.MessageOptions(map_entry=True))
    ek = entry.field.add()
    ek.name, ek.number, ek.type = "key", 1, T.TYPE_STRING
    ek.label = T.LABEL_OPTIONAL
    ev = entry.field.add()
    ev.name, ev.number, ev.type = "value", 2, T.TYPE_MESSAGE
    ev.type_name = ".test.Inner"
    ev.label = T.LABEL_OPTIONAL

    # Map field on Outer
    mf = outer.field.add()
    mf.name, mf.number = "data", 1
    mf.type = T.TYPE_MESSAGE
    mf.type_name = ".test.Outer.DataEntry"
    mf.label = T.LABEL_REPEATED

    pool.Add(file_proto)
    builder = ProtoBuilder(pool=pool, file_counter=100)
    return builder


class TestMapMessageValues:
    def test_message_value_modified(self) -> None:
        """map<string, Inner> where the Inner value differs."""
        b = _make_message_value_map_builder()
        Inner = b.get_message_class("test.Inner")
        msg1 = b.build("test.Outer", data={"a": Inner(x=1, y="hello")})
        msg2 = b.build("test.Outer", data={"a": Inner(x=2, y="hello")})
        result = diff_messages(msg1, msg2)
        assert len(result) == 1
        d = result.differences[0]
        assert d.change_type == ChangeType.MODIFIED
        assert '"a"' in str(d.path)
        assert "x" in str(d.path)

    def test_message_value_added(self) -> None:
        """map<string, Inner> with a new key."""
        b = _make_message_value_map_builder()
        Inner = b.get_message_class("test.Inner")
        msg1 = b.build("test.Outer", data={"a": Inner(x=1)})
        msg2 = b.build("test.Outer", data={"a": Inner(x=1), "b": Inner(x=2, y="new")})
        result = diff_messages(msg1, msg2)
        added = [d for d in result if d.change_type == ChangeType.ADDED]
        assert len(added) >= 1
        paths = [str(d.path) for d in added]
        assert any('"b"' in p for p in paths)

    def test_message_value_removed(self) -> None:
        """map<string, Inner> with a removed key."""
        b = _make_message_value_map_builder()
        Inner = b.get_message_class("test.Inner")
        msg1 = b.build("test.Outer", data={"a": Inner(x=1), "b": Inner(x=2)})
        msg2 = b.build("test.Outer", data={"a": Inner(x=1)})
        result = diff_messages(msg1, msg2)
        removed = [d for d in result if d.change_type == ChangeType.REMOVED]
        assert len(removed) >= 1
        paths = [str(d.path) for d in removed]
        assert any('"b"' in p for p in paths)


class TestMapOrdering:
    def test_deterministic_output_order(self) -> None:
        """Map diff output should be sorted by key for deterministic results."""
        b = _make_string_map_builder()
        msg1 = b.build("test.Msg", labels={"z": "1", "a": "2", "m": "3"})
        msg2 = b.build("test.Msg", labels={"z": "X", "a": "Y", "m": "Z"})
        result = diff_messages(msg1, msg2)
        paths = [str(d.path) for d in result]
        # Should be sorted by key
        assert paths == sorted(paths)
