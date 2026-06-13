"""Tests for bytes field comparison."""

from google.protobuf import descriptor_pb2

from protokit.message import ChangeType, diff_messages
from tests.proto_builder import ProtoBuilder

T = descriptor_pb2.FieldDescriptorProto


def _make_bytes_builder() -> ProtoBuilder:
    builder = ProtoBuilder()
    builder.message("test.Msg", {"data": (T.TYPE_BYTES, 1)})
    return builder


class TestBytesEqual:
    def test_same_bytes(self) -> None:
        b = _make_bytes_builder()
        msg1 = b.build("test.Msg", data=b"\x00\x01\x02")
        msg2 = b.build("test.Msg", data=b"\x00\x01\x02")
        result = diff_messages(msg1, msg2)
        assert not result.has_changes()

    def test_both_empty(self) -> None:
        b = _make_bytes_builder()
        msg1 = b.build("test.Msg")
        msg2 = b.build("test.Msg")
        result = diff_messages(msg1, msg2)
        assert not result.has_changes()

    def test_both_empty_bytes(self) -> None:
        b = _make_bytes_builder()
        msg1 = b.build("test.Msg", data=b"")
        msg2 = b.build("test.Msg", data=b"")
        result = diff_messages(msg1, msg2)
        assert not result.has_changes()


class TestBytesDifferences:
    def test_different_bytes(self) -> None:
        b = _make_bytes_builder()
        msg1 = b.build("test.Msg", data=b"hello")
        msg2 = b.build("test.Msg", data=b"world")
        result = diff_messages(msg1, msg2)
        assert len(result) == 1
        d = result.differences[0]
        assert d.change_type == ChangeType.MODIFIED
        assert d.left_value == b"hello"
        assert d.right_value == b"world"

    def test_different_length(self) -> None:
        b = _make_bytes_builder()
        msg1 = b.build("test.Msg", data=b"\x01")
        msg2 = b.build("test.Msg", data=b"\x01\x02\x03")
        result = diff_messages(msg1, msg2)
        assert result.has_changes()

    def test_binary_data(self) -> None:
        b = _make_bytes_builder()
        msg1 = b.build("test.Msg", data=bytes(range(256)))
        msg2 = b.build("test.Msg", data=bytes(range(255, -1, -1)))
        result = diff_messages(msg1, msg2)
        assert result.has_changes()

    def test_large_bytes(self) -> None:
        b = _make_bytes_builder()
        msg1 = b.build("test.Msg", data=b"\x00" * 10000)
        msg2 = b.build("test.Msg", data=b"\xff" * 10000)
        result = diff_messages(msg1, msg2)
        assert result.has_changes()
