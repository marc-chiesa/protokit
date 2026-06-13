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
