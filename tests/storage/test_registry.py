"""Tests for ``protokit.storage.registry`` — the register-up-front routing table.

Pins the three load-bearing properties: multi-version isolation (two streams,
same FQN, conflicting defs, no collision), register-time validation (a malformed
schema raises at ``register_stream``, not mid-scan), and resolve-once caching
(``resolve()`` is called exactly once per stream regardless of lookup count).
The duplicate-vs-unknown trust-boundary split (KD-7) is asserted directly.
"""

from __future__ import annotations

import pytest
from google.protobuf import descriptor_pb2

from protokit._pools import MissingDependencyError
from protokit.storage.registry import DuplicateStreamError, StreamRegistry
from protokit.storage.schema_source import (
    FileDescriptorSetSchema,
    ResolvedSchema,
    SchemaSource,
)
from tests.storage.proto_fixtures import fds, file_proto

_TYPE_STRING = descriptor_pb2.FieldDescriptorProto.TYPE_STRING


class _CountingSchemaSource:
    """Wraps a real SchemaSource and counts resolve() calls."""

    def __init__(self, inner: SchemaSource) -> None:
        self._inner = inner
        self.resolve_calls = 0

    def resolve(self) -> ResolvedSchema:
        self.resolve_calls += 1
        return self._inner.resolve()


class TestRegisterAndLookup:
    def test_multi_version_isolation_no_collision(self) -> None:
        # The headline isolation claim: two streams whose FDSs define myapp.X
        # DIFFERENTLY each resolve to a class bound to their own pool.
        v1 = file_proto("u.proto", "myapp", message="X", field_name="x")
        v2 = file_proto(
            "u.proto", "myapp", message="X", field_name="y", field_type=_TYPE_STRING
        )
        registry = StreamRegistry()
        registry.register_stream("ch_a", FileDescriptorSetSchema(fds(v1), "myapp.X"))
        registry.register_stream("ch_b", FileDescriptorSetSchema(fds(v2), "myapp.X"))

        a = registry.get("ch_a")
        b = registry.get("ch_b")
        assert a is not None and b is not None
        assert a.message_class is not b.message_class
        assert a.message_class(x=7).x == 7
        assert b.message_class(y="hi").y == "hi"
        # Cross-pool: a's class has no field "y", b's has no field "x".
        assert {f.name for f in a.message_class.DESCRIPTOR.fields} == {"x"}
        assert {f.name for f in b.message_class.DESCRIPTOR.fields} == {"y"}

    def test_get_returns_resolved_schema(self) -> None:
        a = file_proto("a.proto", "a", message="A")
        registry = StreamRegistry()
        registry.register_stream("s", FileDescriptorSetSchema(fds(a), "a.A"))
        resolved = registry.get("s")
        assert isinstance(resolved, ResolvedSchema)
        assert resolved.message_class(x=1).x == 1

    def test_contains_reflects_registration(self) -> None:
        a = file_proto("a.proto", "a", message="A")
        registry = StreamRegistry()
        assert "s" not in registry
        registry.register_stream("s", FileDescriptorSetSchema(fds(a), "a.A"))
        assert "s" in registry


class TestDuplicateVsUnknown:
    def test_duplicate_registration_raises_at_register_time(self) -> None:
        a = file_proto("a.proto", "a", message="A")
        registry = StreamRegistry()
        registry.register_stream("ch_a", FileDescriptorSetSchema(fds(a), "a.A"))
        with pytest.raises(DuplicateStreamError) as exc:
            registry.register_stream("ch_a", FileDescriptorSetSchema(fds(a), "a.A"))
        assert exc.value.stream_id == "ch_a"

    def test_unknown_lookup_signals_miss_not_exception(self) -> None:
        # KD-7: a lookup miss is the engine's FrameError to raise, not the
        # registry's. The registry returns None without raising.
        registry = StreamRegistry()
        assert registry.get("never-registered") is None


class TestRegisterTimeValidation:
    def test_missing_dependency_raises_at_register_not_scan(self) -> None:
        # b depends on a.proto, which is absent. The fault surfaces at
        # register_stream (the boundary), not deferred to a later lookup.
        b = file_proto(
            "b.proto", "b", deps=("a.proto",), message="B", ref_type=".a.A"
        )
        registry = StreamRegistry()
        with pytest.raises(MissingDependencyError) as exc:
            registry.register_stream("bad", FileDescriptorSetSchema(fds(b), "b.B"))
        assert exc.value.file_name == "b.proto"
        assert "bad" not in registry  # nothing cached on failure


class TestResolveOnceCaching:
    def test_resolve_called_once_regardless_of_lookups(self) -> None:
        a = file_proto("a.proto", "a", message="A")
        counting = _CountingSchemaSource(FileDescriptorSetSchema(fds(a), "a.A"))
        registry = StreamRegistry()
        registry.register_stream("s", counting)
        first = registry.get("s")
        second = registry.get("s")
        # resolve() ran exactly once at register; lookups return the cached
        # instance (same message_class object), never re-resolving.
        assert counting.resolve_calls == 1
        assert first is second
        assert first is not None
        assert first.message_class is second.message_class  # type: ignore[union-attr]
