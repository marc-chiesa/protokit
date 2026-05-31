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

from pathlib import Path

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
    ProtoFileSchema,
    ResolvedSchema,
    SchemaCompileError,
)
from protokit.storage.source import StorageError
from tests.storage.proto_fixtures import fds as _fds
from tests.storage.proto_fixtures import file_proto as _file


def _write(tmp_path: Path, name: str, source: str) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(source)
    return p


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


# --- ProtoFileSchema (.proto -> compile) -----------------------------------

_ONE_MESSAGE = """\
syntax = "proto3";
package demo;
message Order { int32 id = 1; }
"""

_MAIN_IMPORTS_DEP = """\
syntax = "proto3";
package demo;
import "dep.proto";
message Order { dep.Item item = 1; }
"""

_DEP = """\
syntax = "proto3";
package dep;
message Item { string sku = 1; }
"""

_IMPORTS_WKT = """\
syntax = "proto3";
package demo;
import "google/protobuf/timestamp.proto";
message Event { google.protobuf.Timestamp created_at = 1; }
"""

_INVALID = """\
syntax = "proto3";
package demo;
message Broken { int32 id = ; }
"""

_MESSAGE_LESS = """\
syntax = "proto3";
package demo;
"""


class TestProtoFileSchema:
    def test_resolves_one_message_proto(self, tmp_path: Path) -> None:
        proto = _write(tmp_path, "demo.proto", _ONE_MESSAGE)
        resolved = ProtoFileSchema(proto, "demo.Order").resolve()
        assert isinstance(resolved, ResolvedSchema)
        assert resolved.message_class(id=7).id == 7

    def test_resolves_sibling_import(self, tmp_path: Path) -> None:
        _write(tmp_path, "dep.proto", _DEP)
        main = _write(tmp_path, "main.proto", _MAIN_IMPORTS_DEP)
        # The sibling dep.proto resolves via the input's auto-added parent dir.
        resolved = ProtoFileSchema(main, "demo.Order").resolve()
        instance = resolved.message_class()
        instance.item.sku = "abc"
        assert instance.item.sku == "abc"

    def test_resolves_import_via_explicit_proto_path(self, tmp_path: Path) -> None:
        # dep.proto lives in inc/, NOT a sibling of main.proto -> needs -I inc.
        _write(tmp_path, "inc/dep.proto", _DEP)
        main = _write(tmp_path, "main.proto", _MAIN_IMPORTS_DEP)
        resolved = ProtoFileSchema(
            main, "demo.Order", proto_paths=(str(tmp_path / "inc"),)
        ).resolve()
        assert resolved.message_class().item.sku == ""

    def test_missing_include_dir_raises_typed_not_crash(self, tmp_path: Path) -> None:
        # dep.proto is in inc/ but no -I inc given: the import can't resolve.
        _write(tmp_path, "inc/dep.proto", _DEP)
        main = _write(tmp_path, "main.proto", _MAIN_IMPORTS_DEP)
        with pytest.raises(SchemaCompileError):
            ProtoFileSchema(main, "demo.Order").resolve()

    def test_resolves_wkt_import_and_field_is_usable(self, tmp_path: Path) -> None:
        proto = _write(tmp_path, "event.proto", _IMPORTS_WKT)
        resolved = ProtoFileSchema(proto, "demo.Event").resolve()
        instance = resolved.message_class()
        instance.created_at.seconds = 5  # the WKT field is usable, not just present
        assert instance.created_at.seconds == 5

    def test_invalid_proto_raises_schema_compile_error_not_systemexit(
        self, tmp_path: Path
    ) -> None:
        proto = _write(tmp_path, "broken.proto", _INVALID)
        # pytest.raises(SchemaCompileError) would NOT catch a SystemExit, so this
        # also asserts the no-sys.exit-in-storage contract.
        with pytest.raises(SchemaCompileError) as exc:
            ProtoFileSchema(proto, "demo.Broken").resolve()
        assert isinstance(exc.value, StorageError)
        assert exc.value.proto_path == proto
        assert exc.value.detail  # carries the compiler diagnostic text

    def test_message_less_proto_raises_message_type_not_found(
        self, tmp_path: Path
    ) -> None:
        # A clean compile with no messages -> empty pool, no error diagnostics;
        # the type miss must surface as a typed MessageTypeNotFoundError.
        proto = _write(tmp_path, "empty.proto", _MESSAGE_LESS)
        with pytest.raises(MessageTypeNotFoundError):
            ProtoFileSchema(proto, "demo.Nope").resolve()

    def test_valid_proto_wrong_type_raises_message_type_not_found(
        self, tmp_path: Path
    ) -> None:
        proto = _write(tmp_path, "demo.proto", _ONE_MESSAGE)
        with pytest.raises(MessageTypeNotFoundError):
            ProtoFileSchema(proto, "demo.DoesNotExist").resolve()

    def test_construction_is_backend_free(self, tmp_path: Path) -> None:
        # Constructing the source compiles nothing (only resolve() invokes a
        # backend), so it cannot fail for a nonexistent path or a missing
        # backend. Importing the module already succeeded (top of file), proving
        # `import protokit.storage` stays backend-free after the schema.compile
        # dependency was added.
        schema = ProtoFileSchema(tmp_path / "nope.proto", "demo.Order")
        assert schema is not None
