"""Tests for protokit._descriptors helpers.

These helpers are underscore-module-private but broadly reused by
differ.py and the schema checker. Test them directly so refactors
that break behavior surface here instead of via distant failures
elsewhere.
"""

from google.protobuf import descriptor_pb2

from protokit._descriptors import (
    format_key,
    get_field_map,
    has_presence,
    is_map_field,
    is_repeated,
    is_required,
    label_name,
    type_name,
)
from tests.proto_builder import ProtoBuilder

T = descriptor_pb2.FieldDescriptorProto


class TestIsMapField:
    def test_map_field_detected(self) -> None:
        builder = ProtoBuilder()
        builder.map_message(
            "test.Msg",
            fields={},
            map_fields={"labels": (T.TYPE_STRING, T.TYPE_STRING, 1)},
        )
        desc = builder.pool.FindMessageTypeByName("test.Msg")
        labels = desc.fields_by_name["labels"]
        assert is_map_field(labels) is True

    def test_repeated_scalar_is_not_map(self) -> None:
        builder = ProtoBuilder()
        builder.message(
            "test.Msg",
            {"tags": (T.TYPE_STRING, 1)},
            repeated_fields={"tags"},
        )
        desc = builder.pool.FindMessageTypeByName("test.Msg")
        assert is_map_field(desc.fields_by_name["tags"]) is False

    def test_singular_message_is_not_map(self) -> None:
        builder = ProtoBuilder()
        builder.message("test.Inner", {"x": (T.TYPE_INT32, 1)})
        builder.message(
            "test.Outer",
            {"inner": (T.TYPE_MESSAGE, 1, "test.Inner")},
        )
        outer = builder.pool.FindMessageTypeByName("test.Outer")
        assert is_map_field(outer.fields_by_name["inner"]) is False

    def test_scalar_field_is_not_map(self) -> None:
        builder = ProtoBuilder()
        builder.message("test.Msg", {"name": (T.TYPE_STRING, 1)})
        desc = builder.pool.FindMessageTypeByName("test.Msg")
        assert is_map_field(desc.fields_by_name["name"]) is False


class TestGetFieldMap:
    def test_maps_each_field_by_name(self) -> None:
        builder = ProtoBuilder()
        builder.message(
            "test.Msg",
            {
                "name": (T.TYPE_STRING, 1),
                "age": (T.TYPE_INT32, 2),
            },
        )
        desc = builder.pool.FindMessageTypeByName("test.Msg")
        fmap = get_field_map(desc)
        assert set(fmap) == {"name", "age"}
        assert fmap["name"].number == 1
        assert fmap["age"].number == 2

    def test_empty_message(self) -> None:
        builder = ProtoBuilder()
        builder.message("test.Empty", {})
        desc = builder.pool.FindMessageTypeByName("test.Empty")
        assert get_field_map(desc) == {}


class TestHasPresence:
    def test_proto2_optional_has_presence(self) -> None:
        builder = ProtoBuilder()
        builder.message(
            "test.Msg",
            {"x": (T.TYPE_INT32, 1)},
            syntax="proto2",
        )
        desc = builder.pool.FindMessageTypeByName("test.Msg")
        assert has_presence(desc.fields_by_name["x"]) is True

    def test_proto3_implicit_scalar_has_no_presence(self) -> None:
        builder = ProtoBuilder()
        builder.message("test.Msg", {"x": (T.TYPE_INT32, 1)})
        desc = builder.pool.FindMessageTypeByName("test.Msg")
        assert has_presence(desc.fields_by_name["x"]) is False

    def test_proto3_message_field_has_presence(self) -> None:
        builder = ProtoBuilder()
        builder.message("test.Inner", {"v": (T.TYPE_INT32, 1)})
        builder.message(
            "test.Outer",
            {"inner": (T.TYPE_MESSAGE, 1, "test.Inner")},
        )
        outer = builder.pool.FindMessageTypeByName("test.Outer")
        assert has_presence(outer.fields_by_name["inner"]) is True

    def test_oneof_member_has_presence(self) -> None:
        builder = ProtoBuilder()
        builder.message(
            "test.Msg",
            {"a": (T.TYPE_STRING, 1), "b": (T.TYPE_INT32, 2)},
            oneofs={"choice": ["a", "b"]},
        )
        desc = builder.pool.FindMessageTypeByName("test.Msg")
        assert has_presence(desc.fields_by_name["a"]) is True
        assert has_presence(desc.fields_by_name["b"]) is True


class TestFormatKey:
    def test_bool_true(self) -> None:
        assert format_key(True) == "true"

    def test_bool_false(self) -> None:
        assert format_key(False) == "false"

    def test_int(self) -> None:
        assert format_key(42) == "42"

    def test_negative_int(self) -> None:
        assert format_key(-7) == "-7"

    def test_string_quoted(self) -> None:
        assert format_key("env") == '"env"'

    def test_string_with_embedded_quote_is_escaped(self) -> None:
        assert format_key('he said "hi"') == '"he said \\"hi\\""'

    def test_string_with_backslash_is_escaped(self) -> None:
        assert format_key("a\\b") == '"a\\\\b"'

    def test_bool_ordered_before_int(self) -> None:
        # isinstance(True, int) is True in Python — the function must check
        # bool before int or it will render True/False as "1"/"0".
        assert format_key(True) != "1"
        assert format_key(False) != "0"


class TestTypeName:
    def test_known_types(self) -> None:
        assert type_name(T.TYPE_STRING) == "TYPE_STRING"
        assert type_name(T.TYPE_INT32) == "TYPE_INT32"
        assert type_name(T.TYPE_MESSAGE) == "TYPE_MESSAGE"
        assert type_name(T.TYPE_BYTES) == "TYPE_BYTES"
        assert type_name(T.TYPE_ENUM) == "TYPE_ENUM"
        assert type_name(T.TYPE_GROUP) == "TYPE_GROUP"

    def test_unknown_type_gets_fallback(self) -> None:
        assert type_name(999) == "TYPE_UNKNOWN_999"


def _build_with_label(label: int, *, syntax: str = "proto3") -> object:
    """Construct a single-field FieldDescriptor with the given label."""
    from google.protobuf import descriptor_pool
    pool = descriptor_pool.DescriptorPool()
    fdp = descriptor_pb2.FileDescriptorProto(
        name=f"label_{label}_{syntax}.proto", package="t", syntax=syntax,
    )
    mp = fdp.message_type.add()
    mp.name = "M"
    f = mp.field.add()
    f.name, f.number, f.type, f.label = "x", 1, T.TYPE_INT32, label
    pool.Add(fdp)
    return pool.FindMessageTypeByName("t.M").fields_by_name["x"]


class TestIsRepeated:
    """``is_repeated`` is the protobuf-5-portable replacement for the
    dropped ``fd.is_repeated`` attribute. Direct unit coverage so a
    future protobuf API shift surfaces here, not via call-site
    breakage."""

    def test_label_repeated_is_repeated(self) -> None:
        fd = _build_with_label(T.LABEL_REPEATED)
        assert is_repeated(fd) is True

    def test_label_optional_is_not_repeated(self) -> None:
        fd = _build_with_label(T.LABEL_OPTIONAL)
        assert is_repeated(fd) is False

    def test_label_required_is_not_repeated(self) -> None:
        fd = _build_with_label(T.LABEL_REQUIRED, syntax="proto2")
        assert is_repeated(fd) is False


class TestIsRequired:
    """``is_required`` is the proto2-only mirror of ``is_repeated``."""

    def test_label_required_is_required(self) -> None:
        fd = _build_with_label(T.LABEL_REQUIRED, syntax="proto2")
        assert is_required(fd) is True

    def test_label_optional_is_not_required(self) -> None:
        fd = _build_with_label(T.LABEL_OPTIONAL)
        assert is_required(fd) is False

    def test_label_repeated_is_not_required(self) -> None:
        fd = _build_with_label(T.LABEL_REPEATED)
        assert is_required(fd) is False


class TestLabelName:
    """``label_name`` returns the canonical ``LABEL_*`` string and is
    used in ``Difference.left_label`` / ``right_label`` for
    cardinality changes — getting it wrong misreports proto2
    ``required`` as ``optional`` in user-visible output."""

    def test_repeated(self) -> None:
        fd = _build_with_label(T.LABEL_REPEATED)
        assert label_name(fd) == "LABEL_REPEATED"

    def test_required(self) -> None:
        fd = _build_with_label(T.LABEL_REQUIRED, syntax="proto2")
        assert label_name(fd) == "LABEL_REQUIRED"

    def test_optional(self) -> None:
        fd = _build_with_label(T.LABEL_OPTIONAL)
        assert label_name(fd) == "LABEL_OPTIONAL"
