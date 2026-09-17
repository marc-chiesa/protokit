"""Tests for protokit._descriptors helpers.

These helpers are underscore-module-private but broadly reused by
differ.py and the schema checker. Test them directly so refactors
that break behavior surface here instead of via distant failures
elsewhere.
"""

from collections.abc import Iterator

import pytest
from google.protobuf import descriptor_pb2
from google.protobuf.descriptor import Descriptor

from protokit import _descriptors
from protokit._descriptors import (
    format_key,
    has_presence,
    is_map_field,
    is_repeated,
    is_required,
    label_name,
    message_proto,
    type_name,
)
from protokit._fieldview import FieldView
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


class TestFieldViewByName:
    """Enumeration moved to the ``_fieldview`` seam in U3.

    These stay at the unit level against ``ProtoBuilder``; the seam's full
    completeness contract (extensions, map entries, namespace separation)
    lives in ``tests/meta/test_fieldview_contract.py``.
    """

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
        fmap = FieldView.of(desc).by_name
        assert set(fmap) == {"name", "age"}
        assert fmap["name"].number == 1
        assert fmap["age"].number == 2

    def test_empty_message(self) -> None:
        builder = ProtoBuilder()
        builder.message("test.Empty", {})
        desc = builder.pool.FindMessageTypeByName("test.Empty")
        assert dict(FieldView.of(desc).by_name) == {}


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


class TestFileProtoCache:
    """``message_proto``'s per-file cache: no thrash within a schema, bounded across pools.

    The cache exists because reading the owning file to get one message turns
    a per-message read into a per-message whole-file serialization, and the
    compat checker calls it once per message pair. Two invariants, each with
    its own history of being wrong:

    * A schema's live pool must be fully cached whatever its file count. At
      32 entries a schema of a few dozen files visited in reference order
      (the checker's traversal is by message reference, not grouped by file)
      evicted on every miss: 9x slower than a larger cap and slower than no
      cache at all.
    * What a ``compat history`` / ``bisect`` walk keeps alive is bounded by
      POOLS, not files. Every entry holds a strong reference to its
      ``FileDescriptor`` and therefore to its pool, so a file cap of 256 let a
      walk over ten-file schemas pin 26 old pools (measured: 3x the memory of
      the cap it replaced). The bound is now a count of distinct pools, with
      a large file backstop only against a single pathological pool.
    """

    @pytest.fixture(autouse=True)
    def _fresh_cache(self) -> Iterator[None]:
        _descriptors._clear_file_proto_cache()
        yield
        _descriptors._clear_file_proto_cache()

    @staticmethod
    def _pool_of_files(n: int) -> tuple[ProtoBuilder, list[Descriptor]]:
        """``n`` single-message files (one per ``ProtoBuilder.message`` call).

        The builder is returned so its pool, and therefore every descriptor,
        stays alive for the test's duration.
        """
        builder = ProtoBuilder()
        descs = []
        for i in range(n):
            builder.message(f"p{i}.M{i}", {"x": (T.TYPE_INT32, 1)})
            descs.append(builder.pool.FindMessageTypeByName(f"p{i}.M{i}"))
        return builder, descs

    def test_a_multi_file_schema_is_serialized_once_per_file(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """64 files visited round-robin twice: the second pass must be all hits.

        Counting ``_index_messages`` calls counts misses — it runs exactly once
        per whole-file read. A cap below the working set makes every access a
        miss on the second pass, which is the thrash this pins against.
        """
        _builder, descs = self._pool_of_files(64)
        reads: list[str] = []
        real_index = _descriptors._index_messages

        def counting_index(proto: descriptor_pb2.FileDescriptorProto) -> dict[
            str, descriptor_pb2.DescriptorProto,
        ]:
            reads.append(proto.name)
            return real_index(proto)

        monkeypatch.setattr(_descriptors, "_index_messages", counting_index)
        for desc in descs:
            message_proto(desc)
        assert len(reads) == 64
        for desc in descs:
            message_proto(desc)
        assert len(reads) == 64, (
            f"{len(reads) - 64} files were re-serialized on the second pass: the cache "
            "cannot hold a 64-file schema and is thrashing"
        )

    def test_a_history_walk_pins_at_most_the_pool_cap(self) -> None:
        """One pool per 'commit', many commits: only the newest pools stay alive.

        Every cached entry pins its pool, so the number of DISTINCT pools the
        cache references is what bounds a long walk's memory. Evicted pools'
        descriptors are re-read correctly when touched again (the walk moved
        on; correctness must not depend on the eviction).
        """
        cap = _descriptors._FILE_PROTO_CACHE_MAX_POOLS
        walk = [self._pool_of_files(3) for _ in range(cap + 6)]
        for _builder, descs in walk:
            for i, desc in enumerate(descs):
                assert message_proto(desc).name == f"M{i}"
        pinned = {id(fd.pool) for fd, _p, _i, _k in _descriptors._FILE_PROTO_CACHE.values()}
        assert len(pinned) == cap, len(pinned)
        newest = {id(builder.pool) for builder, _ in walk[-cap:]}
        assert pinned == newest
        # The oldest pool was evicted; its descriptors still read correctly.
        for i, desc in enumerate(walk[0][1]):
            assert message_proto(desc).name == f"M{i}"
        # Every live entry holds the FileDescriptor whose id() keys it, so that
        # id cannot be reused by another object while the entry lives.
        for key, (file_desc, _proto, _index, _pool_key) in _descriptors._FILE_PROTO_CACHE.items():
            assert id(file_desc) == key

    def test_file_backstop_bounds_a_single_pathological_pool(self) -> None:
        cap = _descriptors._FILE_PROTO_CACHE_MAX_FILES
        _builder, descs = self._pool_of_files(cap + 8)
        for i, desc in enumerate(descs):
            assert message_proto(desc).name == f"M{i}"
        assert len(_descriptors._FILE_PROTO_CACHE) <= cap
        for i, desc in enumerate(descs[:8]):
            assert message_proto(desc).name == f"M{i}"
