"""Tests for ``protokit.storage.schema_source`` — the ``SchemaSource`` forms.

Both forms (in-memory ``FileDescriptorSet`` and the channelized
``(fds_bytes, name)`` embed) resolve to an isolated pool + message class by
reusing Lane A (``_pools``). Error paths are driven with **real** malformed /
incomplete descriptor sets — never ``mock.patch`` on a protobuf C-extension
method, which silently no-ops and produces a false green.

``_file`` / ``_fds`` are the shared ``proto_fixtures`` builders (which mirror
``tests/test_pools.py``), so multi-file topo-sort and missing-dependency
fixtures are built programmatically.
"""

from __future__ import annotations

import pytest
from google.protobuf import descriptor_pb2, descriptor_pool

from protokit._pools import (
    DescriptorPoolError,
    MessageTypeNotFoundError,
    MissingDependencyError,
)
from protokit.storage.schema_source import (
    EmbeddedSchema,
    FileDescriptorSetSchema,
    ResolvedSchema,
)
from tests.storage.proto_fixtures import fds as _fds
from tests.storage.proto_fixtures import file_proto as _file


class TestFileDescriptorSetSchema:
    def test_resolves_to_instantiable_class(self) -> None:
        a = _file("a.proto", "a", message="A")
        resolved = FileDescriptorSetSchema(_fds(a), "a.A").resolve()
        assert isinstance(resolved, ResolvedSchema)
        instance = resolved.message_class(x=7)
        assert instance.x == 7

    def test_out_of_dependency_order_set_resolves(self) -> None:
        # b depends on a; the set lists them in REVERSE order. build_pool
        # topo-sorts, so resolve() succeeds where a naive in-order add fails.
        a = _file("a.proto", "a", message="A")
        b = _file("b.proto", "b", deps=("a.proto",), message="B", ref_type=".a.A")
        resolved = FileDescriptorSetSchema(_fds(b, a), "b.B").resolve()
        assert resolved.message_class().DESCRIPTOR.full_name == "b.B"

    def test_out_of_order_naive_add_would_fail_proving_sort_matters(self) -> None:
        # Guards the previous test's meaning: adding b before a into a fresh
        # pool raises, so the topo-sort in resolve() is doing real work.
        b = _file("b.proto", "b", deps=("a.proto",), message="B", ref_type=".a.A")
        pool = descriptor_pool.DescriptorPool()
        with pytest.raises(Exception):  # noqa: B017 - protobuf raises KeyError/TypeError
            pool.Add(b)

    def test_missing_transitive_dependency_raises_typed_error(self) -> None:
        b = _file("b.proto", "b", deps=("a.proto",), message="B", ref_type=".a.A")
        with pytest.raises(MissingDependencyError) as exc:
            FileDescriptorSetSchema(_fds(b), "b.B").resolve()  # a.proto absent
        assert exc.value.file_name == "b.proto"
        assert exc.value.dependency == "a.proto"

    def test_unknown_message_name_raises_typed_error(self) -> None:
        a = _file("a.proto", "a", message="A")
        with pytest.raises(MessageTypeNotFoundError) as exc:
            FileDescriptorSetSchema(_fds(a), "a.Nope").resolve()
        assert exc.value.type_name == "a.Nope"
        assert "not found in descriptor pool" in str(exc.value)


class TestEmbeddedSchema:
    def test_resolves_identically_to_fds_form(self) -> None:
        a = _file("a.proto", "a", message="A")
        fds_bytes = _fds(a).SerializeToString()
        resolved = EmbeddedSchema((fds_bytes, "a.A")).resolve()
        assert resolved.message_class(x=7).x == 7

    def test_channelized_field_order_is_read_as_documented(self) -> None:
        # Cross-check the pinned format: index 0 is the serialized FDS, index 1
        # is the message name. Transposing them is rejected loudly at
        # construction (index 0 must be bytes-like), proving the order is
        # load-bearing, not coincidental.
        a = _file("a.proto", "a", message="A")
        fds_bytes = _fds(a).SerializeToString()
        EmbeddedSchema((fds_bytes, "a.A")).resolve()  # correct order resolves
        with pytest.raises(ValueError, match="fds_bytes must be bytes-like"):
            EmbeddedSchema(("a.A", fds_bytes))  # type: ignore[arg-type]

    def test_out_of_order_embedded_set_resolves(self) -> None:
        a = _file("a.proto", "a", message="A")
        b = _file("b.proto", "b", deps=("a.proto",), message="B", ref_type=".a.A")
        fds_bytes = _fds(b, a).SerializeToString()  # reverse order
        resolved = EmbeddedSchema((fds_bytes, "b.B")).resolve()
        assert resolved.message_class().DESCRIPTOR.full_name == "b.B"

    def test_missing_dependency_in_channel_raises_typed_error(self) -> None:
        b = _file("b.proto", "b", deps=("a.proto",), message="B", ref_type=".a.A")
        fds_bytes = _fds(b).SerializeToString()  # a.proto absent
        with pytest.raises(MissingDependencyError) as exc:
            EmbeddedSchema((fds_bytes, "b.B")).resolve()
        assert exc.value.file_name == "b.proto"
        assert exc.value.dependency == "a.proto"

    def test_wrong_arity_channel_fails_loudly_at_construction(self) -> None:
        with pytest.raises(ValueError, match="2-tuple"):
            EmbeddedSchema((b"only-one-element",))  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="2-tuple"):
            EmbeddedSchema((b"a", "b.B", "extra"))  # type: ignore[arg-type]

    def test_non_sequence_channel_rejected_with_value_error(self) -> None:
        # A non-Sized input must raise the documented ValueError, not a raw
        # TypeError from len().
        for bad in (None, 42, object()):
            with pytest.raises(ValueError, match="2-tuple"):
                EmbeddedSchema(bad)  # type: ignore[arg-type]

    def test_two_character_str_channel_rejected(self) -> None:
        # A 2-char str is a 2-length sequence but NOT the pinned (bytes, str)
        # shape — it must be rejected, not sneak through len()==2.
        with pytest.raises(ValueError, match="2-tuple"):
            EmbeddedSchema("ab")  # type: ignore[arg-type]

    def test_wrong_element_types_rejected_at_construction(self) -> None:
        with pytest.raises(ValueError, match="fds_bytes must be bytes-like"):
            EmbeddedSchema((123, "a.A"))  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="message_name must be str"):
            EmbeddedSchema((b"fds", 123))  # type: ignore[arg-type]

    def test_corrupt_channel_bytes_raise_typed_error(self) -> None:
        # A truncated/corrupt FDS surfaces as the typed DescriptorPoolError
        # family at the resolve (register) boundary, never a raw DecodeError.
        a = _file("a.proto", "a", message="A")
        corrupt = _fds(a).SerializeToString()[:-1]  # drop the last byte
        with pytest.raises(DescriptorPoolError):
            EmbeddedSchema((corrupt, "a.A")).resolve()


class TestResolvedSchema:
    def test_is_positionally_unpackable_and_attribute_accessible(self) -> None:
        a = _file("a.proto", "a", message="A")
        resolved = FileDescriptorSetSchema(_fds(a), "a.A").resolve()
        pool, message_class = resolved  # positional unpack
        assert pool is resolved.pool  # attribute access
        assert message_class is resolved.message_class


class TestIsolation:
    def test_same_fqn_different_defs_produce_distinct_classes(self) -> None:
        # Two SchemaSources whose FDSs define myapp.X DIFFERENTLY produce two
        # isolated pools; the classes do not collide (isolation at the
        # SchemaSource layer).
        v1 = _file("u.proto", "myapp", message="X", field_name="x")
        v2 = _file(
            "u.proto",
            "myapp",
            message="X",
            field_name="y",
            field_type=descriptor_pb2.FieldDescriptorProto.TYPE_STRING,
        )
        c1 = FileDescriptorSetSchema(_fds(v1), "myapp.X").resolve().message_class
        c2 = FileDescriptorSetSchema(_fds(v2), "myapp.X").resolve().message_class
        assert c1 is not c2
        assert {f.name for f in c1.DESCRIPTOR.fields} == {"x"}
        assert {f.name for f in c2.DESCRIPTOR.fields} == {"y"}
        assert c1(x=7).x == 7
        assert c2(y="hi").y == "hi"
