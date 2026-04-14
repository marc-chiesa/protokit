"""Tests for pytest assertion hook."""

import warnings
from unittest.mock import patch

from google.protobuf import descriptor_pb2

from protokit.message.formatting import format_value as _format_value
from protokit.message.model import EnumValue
from protokit.message.pytest_plugin import pytest_assertrepr_compare
from tests.proto_builder import ProtoBuilder

T = descriptor_pb2.FieldDescriptorProto


def _make_builder() -> ProtoBuilder:
    builder = ProtoBuilder()
    builder.message("test.Msg", {
        "name": (T.TYPE_STRING, 1),
        "value": (T.TYPE_INT32, 2),
    })
    return builder


class TestPytestPlugin:
    def test_returns_none_for_non_protobuf(self) -> None:
        result = pytest_assertrepr_compare("==", "hello", "world")
        assert result is None

    def test_returns_none_for_non_eq_op(self) -> None:
        b = _make_builder()
        msg1 = b.build("test.Msg", name="Alice")
        msg2 = b.build("test.Msg", name="Bob")
        result = pytest_assertrepr_compare("!=", msg1, msg2)
        assert result is None

    def test_returns_none_for_equal_messages(self) -> None:
        b = _make_builder()
        msg1 = b.build("test.Msg", name="Alice")
        msg2 = b.build("test.Msg", name="Alice")
        result = pytest_assertrepr_compare("==", msg1, msg2)
        assert result is None

    def test_returns_diff_for_different_messages(self) -> None:
        b = _make_builder()
        msg1 = b.build("test.Msg", name="Alice", value=1)
        msg2 = b.build("test.Msg", name="Bob", value=2)
        result = pytest_assertrepr_compare("==", msg1, msg2)
        assert result is not None
        assert len(result) >= 3  # header + count + at least one diff line
        assert "2 difference(s)" in result[1]

    def test_diff_shows_modified_field(self) -> None:
        b = _make_builder()
        msg1 = b.build("test.Msg", name="Alice")
        msg2 = b.build("test.Msg", name="Bob")
        result = pytest_assertrepr_compare("==", msg1, msg2)
        assert result is not None
        diff_lines = [line for line in result if "~" in line]
        assert len(diff_lines) == 1
        assert "name" in diff_lines[0]
        assert "'Alice'" in diff_lines[0]
        assert "'Bob'" in diff_lines[0]

    def test_diff_shows_added_field(self) -> None:
        b1 = ProtoBuilder()
        b1.message("test.Left", {"name": (T.TYPE_STRING, 1)})
        b2 = ProtoBuilder()
        b2.message("test.Right", {
            "name": (T.TYPE_STRING, 1),
            "extra": (T.TYPE_STRING, 2),
        })
        msg1 = b1.build("test.Left", name="Alice")
        msg2 = b2.build("test.Right", name="Alice", extra="data")
        result = pytest_assertrepr_compare("==", msg1, msg2)
        assert result is not None
        added_lines = [line for line in result if "+" in line]
        assert len(added_lines) >= 1

    def test_header_shows_type_name(self) -> None:
        b = _make_builder()
        msg1 = b.build("test.Msg", name="Alice")
        msg2 = b.build("test.Msg", name="Bob")
        result = pytest_assertrepr_compare("==", msg1, msg2)
        assert result is not None
        assert "test.Msg" in result[0]

    def test_returns_none_and_warns_on_compare_exception(self) -> None:
        """If differ.compare raises, fall back gracefully with a warning."""
        b = _make_builder()
        msg1 = b.build("test.Msg", name="Alice")
        msg2 = b.build("test.Msg", name="Bob")
        with patch(
            "protokit.message.pytest_plugin.MessageDifferencer.compare",
            side_effect=RuntimeError("boom"),
        ):
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                result = pytest_assertrepr_compare("==", msg1, msg2)
                assert result is None
                assert len(w) == 1
                assert "protokit plugin failed" in str(w[0].message)
                assert "RuntimeError" in str(w[0].message)


class TestFormatValue:
    def test_bool_renders_lowercase(self) -> None:
        assert _format_value(True) == "true"
        assert _format_value(False) == "false"

    def test_float_renders_as_string(self) -> None:
        assert _format_value(3.14) == "3.14"
        assert _format_value(0.0) == "0.0"

    def test_none_renders_unset(self) -> None:
        assert _format_value(None) == "<unset>"

    def test_string_renders_quoted(self) -> None:
        assert _format_value("hello") == "'hello'"

    def test_int_renders_as_string(self) -> None:
        assert _format_value(42) == "42"

    def test_enum_value_renders(self) -> None:
        assert _format_value(EnumValue(name="ACTIVE", number=1)) == "ACTIVE(1)"

    def test_short_bytes_renders_repr(self) -> None:
        assert _format_value(b"\x01\x02") == "b'\\x01\\x02'"

    def test_long_bytes_renders_summary(self) -> None:
        assert _format_value(b"\x00" * 33) == "<33 bytes>"
