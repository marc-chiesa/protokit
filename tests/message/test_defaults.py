"""Tests for default value handling in proto2 and proto3."""

from google.protobuf import descriptor_pb2

from protokit.message import ChangeType, diff_messages
from tests.proto_builder import ProtoBuilder

T = descriptor_pb2.FieldDescriptorProto


class TestProto3Defaults:
    def test_default_int_equal(self) -> None:
        builder = ProtoBuilder()
        builder.message("test.Msg", {"value": (T.TYPE_INT32, 1)})
        msg1 = builder.build("test.Msg")  # value = 0 (default)
        msg2 = builder.build("test.Msg")
        result = diff_messages(msg1, msg2)
        assert not result.has_changes()

    def test_default_string_equal(self) -> None:
        builder = ProtoBuilder()
        builder.message("test.Msg", {"name": (T.TYPE_STRING, 1)})
        msg1 = builder.build("test.Msg")  # name = "" (default)
        msg2 = builder.build("test.Msg")
        result = diff_messages(msg1, msg2)
        assert not result.has_changes()

    def test_default_bool_equal(self) -> None:
        builder = ProtoBuilder()
        builder.message("test.Msg", {"flag": (T.TYPE_BOOL, 1)})
        msg1 = builder.build("test.Msg")  # flag = false (default)
        msg2 = builder.build("test.Msg")
        result = diff_messages(msg1, msg2)
        assert not result.has_changes()

    def test_default_bytes_equal(self) -> None:
        builder = ProtoBuilder()
        builder.message("test.Msg", {"data": (T.TYPE_BYTES, 1)})
        msg1 = builder.build("test.Msg")  # data = b"" (default)
        msg2 = builder.build("test.Msg")
        result = diff_messages(msg1, msg2)
        assert not result.has_changes()

    def test_explicit_default_vs_implicit(self) -> None:
        """Setting a field to its default value should equal leaving it unset in proto3."""
        builder = ProtoBuilder()
        builder.message("test.Msg", {"value": (T.TYPE_INT32, 1)})
        msg1 = builder.build("test.Msg", value=0)
        msg2 = builder.build("test.Msg")
        result = diff_messages(msg1, msg2)
        # Proto3: no presence for plain scalars, so 0 == unset
        assert not result.has_changes()

    def test_explicit_empty_string_vs_implicit(self) -> None:
        builder = ProtoBuilder()
        builder.message("test.Msg", {"name": (T.TYPE_STRING, 1)})
        msg1 = builder.build("test.Msg", name="")
        msg2 = builder.build("test.Msg")
        result = diff_messages(msg1, msg2)
        assert not result.has_changes()

    def test_non_default_vs_default(self) -> None:
        builder = ProtoBuilder()
        builder.message("test.Msg", {"value": (T.TYPE_INT32, 1)})
        msg1 = builder.build("test.Msg", value=42)
        msg2 = builder.build("test.Msg")
        result = diff_messages(msg1, msg2)
        assert result.has_changes()
        d = result.differences[0]
        assert d.change_type == ChangeType.MODIFIED
        assert d.left_value == 42
        assert d.right_value == 0


class TestProto3MessageDefaults:
    def test_unset_message_field(self) -> None:
        builder = ProtoBuilder()
        builder.message("test.Inner", {"x": (T.TYPE_INT32, 1)})
        builder.message("test.Outer", {
            "inner": (T.TYPE_MESSAGE, 1, ".test.Inner"),
        })
        msg1 = builder.build("test.Outer")
        msg2 = builder.build("test.Outer")
        result = diff_messages(msg1, msg2)
        assert not result.has_changes()

    def test_set_vs_unset_message(self) -> None:
        builder = ProtoBuilder()
        builder.message("test.Inner", {"x": (T.TYPE_INT32, 1)})
        builder.message("test.Outer", {
            "inner": (T.TYPE_MESSAGE, 1, ".test.Inner"),
        })
        Inner = builder.get_message_class("test.Inner")
        msg1 = builder.build("test.Outer", inner=Inner(x=5))
        msg2 = builder.build("test.Outer")
        result = diff_messages(msg1, msg2)
        assert result.has_changes()


class TestProto3RepeatedDefaults:
    def test_empty_repeated_equal(self) -> None:
        builder = ProtoBuilder()
        builder.message_with_repeated(
            "test.Msg",
            {"tags": (T.TYPE_STRING, 1)},
            repeated_fields={"tags"},
        )
        msg1 = builder.build("test.Msg")
        msg2 = builder.build("test.Msg")
        result = diff_messages(msg1, msg2)
        assert not result.has_changes()
