"""Tests for ``protokit._pools`` — dependency-ordered pool construction and
message-class resolution with typed library exceptions.

These cover the topo-sort gotcha (``DescriptorPool.Add`` requires a file's
dependencies to already be in the pool) that the channelized-schema format
exposes: an embedded ``FileDescriptorSet`` is not guaranteed to be in
dependency order, so a naive in-order add raises unknown-dependency errors.
"""

from __future__ import annotations

import pytest
from google.protobuf import descriptor_pb2, descriptor_pool

from protokit import _pools
from tests._pure_python_inventory import skip_under_pure_python


def _file(
    name: str,
    package: str,
    *,
    deps: tuple[str, ...] = (),
    message: str | None = None,
    ref_type: str | None = None,
) -> descriptor_pb2.FileDescriptorProto:
    """Build a minimal proto3 FileDescriptorProto.

    When ``ref_type`` is given, the message gets a field of that message
    type so the declared ``deps`` are load-bearing (the pool genuinely
    needs the dependency present before this file can be added).
    """
    fdp = descriptor_pb2.FileDescriptorProto()
    fdp.name = name
    fdp.package = package
    fdp.syntax = "proto3"
    for d in deps:
        fdp.dependency.append(d)
    if message is not None:
        mt = fdp.message_type.add()
        mt.name = message
        f = mt.field.add()
        f.name = "x"
        f.number = 1
        f.label = f.LABEL_OPTIONAL
        if ref_type is not None:
            f.type = f.TYPE_MESSAGE
            f.type_name = ref_type
        else:
            f.type = f.TYPE_INT32
    return fdp


def _fds(*files: descriptor_pb2.FileDescriptorProto) -> descriptor_pb2.FileDescriptorSet:
    fds = descriptor_pb2.FileDescriptorSet()
    fds.file.extend(files)
    return fds


class TestSortFilesByDependency:
    def test_reverse_order_is_sorted_so_pool_add_succeeds(self) -> None:
        a = _file("a.proto", "a", message="A")
        b = _file("b.proto", "b", deps=("a.proto",), message="B", ref_type=".a.A")
        # Files listed in REVERSE dependency order (b before a).
        ordered = _pools.sort_files_by_dependency([b, a])
        assert [f.name for f in ordered] == ["a.proto", "b.proto"]

    @skip_under_pure_python(
        "premise holds only on upb: a raw DescriptorPool().Add() of a file whose "
        "dependency is absent raises eagerly there, while the pure-Python pool "
        "resolves lazily and accepts it — not a protokit defect, so a permanent "
        "backend skip rather than an inventory entry (U2, KTD10)"
    )
    def test_naive_in_order_add_would_fail_proving_sort_matters(self) -> None:
        # Guards the test's own meaning: adding b before a into a fresh pool
        # raises, so the topo-sort in build_pool is doing real work.
        b = _file("b.proto", "b", deps=("a.proto",), message="B", ref_type=".a.A")
        pool = descriptor_pool.DescriptorPool()
        with pytest.raises(Exception):  # noqa: B017 - protobuf raises KeyError/TypeError here
            pool.Add(b)

    def test_missing_dependency_raises_typed_error(self) -> None:
        b = _file("b.proto", "b", deps=("a.proto",), message="B", ref_type=".a.A")
        with pytest.raises(_pools.MissingDependencyError) as exc:
            _pools.sort_files_by_dependency([b])  # a.proto absent
        assert exc.value.file_name == "b.proto"
        assert exc.value.dependency == "a.proto"

    def test_cycle_raises(self) -> None:
        a = _file("a.proto", "a", deps=("b.proto",))
        b = _file("b.proto", "b", deps=("a.proto",))
        with pytest.raises(_pools.DescriptorPoolError):
            _pools.sort_files_by_dependency([a, b])

    def test_duplicate_file_name_raises_loudly(self) -> None:
        # Two files sharing a name must fail loudly (DescriptorPool.Add does
        # too) — a silent de-dup would drop a definition and pick an
        # arbitrary, input-order-dependent winner.
        a1 = _file("dup.proto", "dup", message="A")
        a2 = _file("dup.proto", "dup", message="B")
        with pytest.raises(_pools.DuplicateFileError) as exc:
            _pools.sort_files_by_dependency([a1, a2])
        assert exc.value.file_name == "dup.proto"
        # build_pool surfaces it too — no silent drop.
        with pytest.raises(_pools.DuplicateFileError):
            _pools.build_pool(_fds(a1, a2))

    def test_deep_chain_does_not_overflow(self) -> None:
        # Iterative Kahn's must sort a chain deeper than Python's recursion
        # limit (~1000) without a RecursionError — the prior recursive DFS
        # would have overflowed.
        n = 1500
        files = [_file("f0.proto", "p")]
        files += [
            _file(f"f{i}.proto", "p", deps=(f"f{i - 1}.proto",))
            for i in range(1, n)
        ]
        ordered = _pools.sort_files_by_dependency(list(reversed(files)))
        assert len(ordered) == n
        assert [f.name for f in ordered[:2]] == ["f0.proto", "f1.proto"]


class TestBuildPool:
    def test_builds_from_unsorted_set_and_resolves_types(self) -> None:
        a = _file("a.proto", "a", message="A")
        b = _file("b.proto", "b", deps=("a.proto",), message="B", ref_type=".a.A")
        pool = _pools.build_pool(_fds(b, a))  # reverse order
        assert pool.FindMessageTypeByName("a.A").full_name == "a.A"
        assert pool.FindMessageTypeByName("b.B").full_name == "b.B"

    def test_pools_are_isolated_same_fqn_different_defs(self) -> None:
        v1 = _file("u.proto", "u", message="User")  # User { int32 x = 1 }
        # Same FQN, different definition.
        v2 = descriptor_pb2.FileDescriptorProto()
        v2.name = "u.proto"
        v2.package = "u"
        v2.syntax = "proto3"
        mt = v2.message_type.add()
        mt.name = "User"
        f = mt.field.add()
        f.name = "y"
        f.number = 2
        f.label = f.LABEL_OPTIONAL
        f.type = f.TYPE_STRING

        pool1 = _pools.build_pool(_fds(v1))
        pool2 = _pools.build_pool(_fds(v2))
        d1 = pool1.FindMessageTypeByName("u.User")
        d2 = pool2.FindMessageTypeByName("u.User")
        assert {fld.name for fld in d1.fields} == {"x"}
        assert {fld.name for fld in d2.fields} == {"y"}

    def test_dangling_symbol_raises_typed_error_not_raw_typeerror(self) -> None:
        # A field references a symbol no file in the set defines (a dangling
        # symbol with no *missing-file* dependency, so the topo-sort passes).
        # pool.Add raises a bare TypeError; build_pool must re-raise it as the
        # typed DescriptorPoolError family.
        a = _file("a.proto", "a", message="A", ref_type=".a.DoesNotExist")
        with pytest.raises(_pools.DescriptorPoolError):
            _pools.build_pool(_fds(a))


class TestLoadPoolFromBytes:
    def test_valid_bytes_round_trip(self) -> None:
        a = _file("a.proto", "a", message="A")
        pool = _pools.load_pool_from_bytes(_fds(a).SerializeToString())
        assert pool.FindMessageTypeByName("a.A").full_name == "a.A"

    def test_corrupt_bytes_raise_typed_error_not_raw_decodeerror(self) -> None:
        # A truncated/corrupt FileDescriptorSet must surface as the typed family,
        # not a raw protobuf DecodeError, so the register boundary stays typed.
        a = _file("a.proto", "a", message="A")
        corrupt = _fds(a).SerializeToString()[:-1]  # drop the trailing byte
        with pytest.raises(_pools.DescriptorPoolError):
            _pools.load_pool_from_bytes(corrupt)

    def test_load_pool_from_bytes_roundtrip(self) -> None:
        a = _file("a.proto", "a", message="A")
        b = _file("b.proto", "b", deps=("a.proto",), message="B", ref_type=".a.A")
        data = _fds(b, a).SerializeToString()
        pool = _pools.load_pool_from_bytes(data)
        assert pool.FindMessageTypeByName("b.B").full_name == "b.B"


class TestGetMessageClass:
    def test_hit_returns_instantiable_class(self) -> None:
        a = _file("a.proto", "a", message="A")
        pool = _pools.build_pool(_fds(a))
        cls = _pools.get_message_class(pool, "a.A")
        msg = cls(x=7)
        assert msg.x == 7

    def test_miss_raises_typed_error_with_legacy_message(self) -> None:
        a = _file("a.proto", "a", message="A")
        pool = _pools.build_pool(_fds(a))
        with pytest.raises(_pools.MessageTypeNotFoundError) as exc:
            _pools.get_message_class(pool, "a.Nope")
        assert exc.value.type_name == "a.Nope"
        # Preserves the exact wording diff/compat CLIs print.
        assert "not found in descriptor pool" in str(exc.value)


class TestAddAndResolveDuplicateFile:
    def test_duplicate_file_name_raises_the_typed_error_on_both_backends(self) -> None:
        """A second file with the same name but different content.

        upb rejects it from ``Add`` with ``TypeError``; the pure-Python pool
        raises its own ``DescriptorDatabaseConflictingDefinitionError``, which
        is neither a ``TypeError`` nor a ``KeyError`` and escaped raw.
        """
        pool = descriptor_pool.DescriptorPool()
        first = _file("d.proto", "d", message="A")
        second = _file("d.proto", "d", message="B")
        _pools.add_and_resolve(pool, first)
        with pytest.raises(_pools.DescriptorPoolError):
            _pools.add_and_resolve(pool, second)


def _rejected_by_pure_python(shape: str) -> descriptor_pb2.FileDescriptorProto:
    """A proto2 file that parses, and that pure-Python rejects with a builtin exception."""
    fdp = descriptor_pb2.FileDescriptorProto(name="r.proto", package="r", syntax="proto2")
    field = fdp.message_type.add(name="M").field.add(
        name="x", number=1, type=descriptor_pb2.FieldDescriptorProto.TYPE_INT32,
        label=descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL,
    )
    if shape == "unparseable-default":
        field.default_value = "abc"
    elif shape == "public-dependency-out-of-range":
        fdp.public_dependency.append(0)
    elif shape == "oneof-index-out-of-range":
        field.oneof_index = 5
    elif shape == "no-field-type":
        field.ClearField("type")
    return fdp


class TestAddAndResolveBackendValidation:
    """A descriptor the runtime rejects raises the typed error on both backends.

    upb rejects the first three shapes with ``TypeError`` from ``Add``. Pure-Python's
    own descriptor checks raise ``ValueError`` or ``IndexError`` instead, and those
    escaped raw to callers that catch only the typed family, such as the forensics CLI.
    """

    @pytest.mark.parametrize(
        "shape",
        ["unparseable-default", "public-dependency-out-of-range", "oneof-index-out-of-range"],
    )
    def test_rejected_descriptor_raises_the_typed_error(self, shape: str) -> None:
        data = _fds(_rejected_by_pure_python(shape)).SerializeToString()
        with pytest.raises(_pools.DescriptorPoolError) as excinfo:
            _pools.load_pool_from_bytes(data)
        assert excinfo.value.__cause__ is not None

    def test_a_shape_only_pure_python_rejects_never_escapes_raw(self) -> None:
        # upb accepts a field with no type; pure-Python raises AttributeError
        # while building it. Either outcome is fine, a raw exception is not.
        data = _fds(_rejected_by_pure_python("no-field-type")).SerializeToString()
        try:
            _pools.load_pool_from_bytes(data)
        except _pools.DescriptorPoolError as exc:
            assert exc.__cause__ is not None


def _deeply_nested_set(depth: int = 2000) -> bytes:
    """A set whose one message nests ``depth`` message types, deeper than pure-Python parses."""
    def field(tag: int, payload: bytes) -> bytes:
        size, length = len(payload), b""
        while True:
            length += bytes([(size & 0x7F) | (0x80 if size > 0x7F else 0)])
            size >>= 7
            if not size:
                return bytes([tag]) + length + payload

    nested = b""
    for _ in range(depth):
        nested = field(26, nested)  # DescriptorProto.nested_type
    return field(10, field(10, b"a.proto") + field(34, nested))


class TestLoadPoolFromBytesParseFailures:
    """Bytes the runtime cannot parse raise the typed error on both backends.

    The parse catch covered only ``DecodeError``. Pure-Python raises
    ``UnicodeDecodeError`` for a string that is not UTF-8, and
    ``RecursionError`` for deep nesting. upb parses a non-UTF-8 string and
    returns it as ``bytes``: a bad file name then survived ``Add`` and failed
    later, wherever the name was read, and in a cycle it broke the error
    message with ``TypeError``. ``require_decodable_strings`` now rejects it
    at the boundary, so both backends fail in the same place.
    """

    @pytest.mark.parametrize(
        "data",
        [
            pytest.param(bytes.fromhex("0a030a01ff"), id="name-not-utf8"),
            pytest.param(bytes.fromhex("0a060a01ff1a01ff"), id="name-not-utf8-in-a-cycle"),
            pytest.param(
                bytes.fromhex("0a0e0a07612e70726f746f2203" "0a01ff"),
                id="message-name-not-utf8",
            ),
            pytest.param(_deeply_nested_set(), id="nested-too-deep"),
        ],
    )
    def test_unparseable_bytes_raise_the_typed_error(self, data: bytes) -> None:
        with pytest.raises(_pools.DescriptorPoolError):
            _pools.load_pool_from_bytes(data)

    @skip_under_pure_python(
        "premise holds only on upb: its parser keeps a non-UTF-8 string as bytes, "
        "while the pure-Python parser rejects it before this check can run"
    )
    def test_a_non_utf8_file_name_is_rejected_before_it_reaches_a_descriptor(
        self,
    ) -> None:
        fds = descriptor_pb2.FileDescriptorSet.FromString(bytes.fromhex("0a030a01ff"))
        with pytest.raises(_pools.DescriptorPoolError, match="not valid UTF-8"):
            _pools.require_decodable_strings(fds)
