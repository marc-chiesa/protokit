"""Tests for scalar field comparison."""

from google.protobuf import descriptor_pb2

from protokit.message import ChangeType, diff_messages
from tests.proto_builder import ProtoBuilder

T = descriptor_pb2.FieldDescriptorProto


class TestScalarSameValues:
    def test_equal_strings(self) -> None:
        builder = ProtoBuilder()
        builder.message("test.Msg", {"name": (T.TYPE_STRING, 1)})
        msg1 = builder.build("test.Msg", name="Alice")
        msg2 = builder.build("test.Msg", name="Alice")
        result = diff_messages(msg1, msg2)
        assert not result.has_changes()

    def test_equal_ints(self) -> None:
        builder = ProtoBuilder()
        builder.message("test.Msg", {"value": (T.TYPE_INT32, 1)})
        msg1 = builder.build("test.Msg", value=42)
        msg2 = builder.build("test.Msg", value=42)
        result = diff_messages(msg1, msg2)
        assert not result.has_changes()

    def test_equal_bools(self) -> None:
        builder = ProtoBuilder()
        builder.message("test.Msg", {"flag": (T.TYPE_BOOL, 1)})
        msg1 = builder.build("test.Msg", flag=True)
        msg2 = builder.build("test.Msg", flag=True)
        result = diff_messages(msg1, msg2)
        assert not result.has_changes()

    def test_both_default_proto3(self) -> None:
        """Proto3 scalars at default value should compare as equal."""
        builder = ProtoBuilder()
        builder.message("test.Msg", {"value": (T.TYPE_INT32, 1)})
        msg1 = builder.build("test.Msg")
        msg2 = builder.build("test.Msg")
        result = diff_messages(msg1, msg2)
        assert not result.has_changes()


class TestScalarDifferentValues:
    def test_string_changed(self) -> None:
        builder = ProtoBuilder()
        builder.message("test.Msg", {"name": (T.TYPE_STRING, 1)})
        msg1 = builder.build("test.Msg", name="Alice")
        msg2 = builder.build("test.Msg", name="Bob")
        result = diff_messages(msg1, msg2)
        assert result.has_changes()
        assert len(result) == 1
        d = result.differences[0]
        assert d.change_type == ChangeType.MODIFIED
        assert d.old_value == "Alice"
        assert d.new_value == "Bob"
        assert str(d.path) == "name"

    def test_int_changed(self) -> None:
        builder = ProtoBuilder()
        builder.message("test.Msg", {"value": (T.TYPE_INT32, 1)})
        msg1 = builder.build("test.Msg", value=1)
        msg2 = builder.build("test.Msg", value=2)
        result = diff_messages(msg1, msg2)
        assert result.has_changes()
        d = result.differences[0]
        assert d.change_type == ChangeType.MODIFIED
        assert d.old_value == 1
        assert d.new_value == 2

    def test_bool_changed(self) -> None:
        builder = ProtoBuilder()
        builder.message("test.Msg", {"flag": (T.TYPE_BOOL, 1)})
        msg1 = builder.build("test.Msg", flag=True)
        msg2 = builder.build("test.Msg", flag=False)
        result = diff_messages(msg1, msg2)
        assert result.has_changes()

    def test_bytes_changed(self) -> None:
        builder = ProtoBuilder()
        builder.message("test.Msg", {"data": (T.TYPE_BYTES, 1)})
        msg1 = builder.build("test.Msg", data=b"hello")
        msg2 = builder.build("test.Msg", data=b"world")
        result = diff_messages(msg1, msg2)
        assert result.has_changes()
        d = result.differences[0]
        assert d.old_value == b"hello"
        assert d.new_value == b"world"

    def test_multiple_fields_changed(self) -> None:
        builder = ProtoBuilder()
        builder.message("test.Msg", {
            "name": (T.TYPE_STRING, 1),
            "age": (T.TYPE_INT32, 2),
        })
        msg1 = builder.build("test.Msg", name="Alice", age=30)
        msg2 = builder.build("test.Msg", name="Bob", age=31)
        result = diff_messages(msg1, msg2)
        assert len(result) == 2

    def test_one_field_changed_one_same(self) -> None:
        builder = ProtoBuilder()
        builder.message("test.Msg", {
            "name": (T.TYPE_STRING, 1),
            "age": (T.TYPE_INT32, 2),
        })
        msg1 = builder.build("test.Msg", name="Alice", age=30)
        msg2 = builder.build("test.Msg", name="Alice", age=31)
        result = diff_messages(msg1, msg2)
        assert len(result) == 1
        assert str(result.differences[0].path) == "age"
