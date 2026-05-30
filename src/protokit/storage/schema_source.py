"""Schema resolution for a stream: ``SchemaSource`` and its two PR1 forms.

A ``SchemaSource`` answers one question — *what message type are this stream's
records, and in which isolated descriptor pool?* — and answers it
self-containedly: :meth:`SchemaSource.resolve` takes **no** ``name`` argument
because each source already carries everything needed to name its type. This is
a deliberate refinement of the origin's ``resolve(name)`` signature: the
channelized form *carries* its own fully-qualified name, so passing one
separately is redundant and fragile.

``resolve()`` returns a :class:`ResolvedSchema` — a ``NamedTuple`` of
``(pool, message_class)``. ``NamedTuple`` is the one shape that serves both
styles of this public extension point: it is positionally unpackable (a
third-party ``SchemaSource`` may return a plain 2-tuple and still satisfy the
contract structurally) **and** attribute-accessible (``.pool`` /
``.message_class``) for consumer clarity, and it passes ``mypy --strict``.

Pool construction, dependency-order topo-sort, and message-class resolution are
**100% Lane A reuse** (``protokit._pools``); a ``SchemaSource`` is a thin,
self-describing wrapper. Schema faults therefore propagate Lane A's typed
``DescriptorPoolError`` family (``MissingDependencyError``,
``MessageTypeNotFoundError``, ``DuplicateFileError``) unwrapped.

Channelized (embedded) format — pinned 2026-05-29
-------------------------------------------------
``(serialized FileDescriptorSet bytes, fully-qualified message name)``. The FDS
is the full transitive import closure and need **not** be dependency-ordered —
``_pools`` topo-sorts defensively. The name is dotless protobuf form
(``"pkg.Msg"``, not ``".pkg.Msg"``). Versioning is handled by each stream
embedding its own complete FDS, which is exactly why per-stream pools are
isolated.

Public surface:

- ``SchemaSource`` — the resolution protocol (``resolve() -> ResolvedSchema``).
- ``ResolvedSchema`` — the ``(pool, message_class)`` result NamedTuple.
- ``FileDescriptorSetSchema`` — resolve from an in-memory ``FileDescriptorSet``.
- ``EmbeddedSchema`` — resolve from the channelized ``(fds_bytes, name)`` form.
"""

from __future__ import annotations

from typing import NamedTuple, Protocol

from google.protobuf import descriptor_pb2, descriptor_pool

from protokit._pools import build_pool, get_message_class, load_pool_from_bytes


class ResolvedSchema(NamedTuple):
    """A stream's schema resolved to an isolated pool and its message class.

    Attributes:
        pool: A fresh, isolated ``DescriptorPool`` (never the default pool) so
            concurrent streams may hold conflicting versions of the same
            fully-qualified type without collision.
        message_class: The generated message class for this stream's records,
            bound to ``pool``.
    """

    pool: descriptor_pool.DescriptorPool
    message_class: type


class SchemaSource(Protocol):
    """Resolves a stream's schema to a ``(pool, message_class)`` pair.

    A ``SchemaSource`` is self-contained: it names its own message type, so
    :meth:`resolve` takes no arguments. Third-party implementations need only
    provide ``resolve()`` returning a ``ResolvedSchema`` (or any positionally
    compatible 2-tuple of ``(pool, message_class)``).
    """

    def resolve(self) -> ResolvedSchema:
        """Build the isolated pool and resolve this stream's message class.

        Raises:
            protokit._pools.DescriptorPoolError: subclasses for a missing
                transitive dependency, a duplicate file, a dependency cycle, or
                an unknown message type.
        """
        ...


class FileDescriptorSetSchema:
    """Resolve a stream's schema from an in-memory ``FileDescriptorSet``.

    The set must be the full transitive import closure; it need not be in
    dependency order (``_pools.build_pool`` topo-sorts).
    """

    def __init__(
        self,
        fds: descriptor_pb2.FileDescriptorSet,
        message_type_name: str,
    ) -> None:
        """Store the descriptor set and the dotless fully-qualified type name.

        Args:
            fds: The full transitive ``FileDescriptorSet`` for this stream.
            message_type_name: Dotless fully-qualified message name, e.g.
                ``"myapp.Order"``.
        """
        self._fds = fds
        self._message_type_name = message_type_name

    def resolve(self) -> ResolvedSchema:
        pool = build_pool(self._fds)
        message_class = get_message_class(pool, self._message_type_name)
        return ResolvedSchema(pool, message_class)


class EmbeddedSchema:
    """Resolve a stream's schema from the channelized ``(fds_bytes, name)`` form.

    This is the schema-alongside-data shape the maintainer's pybind11 library
    emits: a serialized ``FileDescriptorSet`` paired with the fully-qualified
    message name. The bytes are parsed and topo-sorted by ``_pools`` (input
    order is not assumed), the isolated pool is built, and the name is resolved.
    A dependency referenced but absent from the set is a hard
    ``MissingDependencyError``.
    """

    def __init__(self, channelized: tuple[bytes, str]) -> None:
        """Unpack the pinned channelized tuple at the construction boundary.

        Args:
            channelized: ``(serialized FileDescriptorSet bytes, dotless FQ
                message name)`` — see the module docstring for the pinned
                format.

        Raises:
            ValueError: ``channelized`` is not a 2-element sequence (a
                malformed channel fails loudly here, not mid-scan).
        """
        # Validate arity at the boundary, then unpack the pinned order — index
        # 0 is the serialized FDS, index 1 is the dotless FQ name (the format is
        # defined here, locally, and cross-checked by the round-trip test). A
        # wrong-arity channel fails loudly here rather than mid-scan.
        if len(channelized) != 2:
            raise ValueError(
                f"channelized schema must be a (fds_bytes, message_name) "
                f"2-tuple, got {len(channelized)} elements"
            )
        self._fds_bytes, self._message_type_name = channelized

    def resolve(self) -> ResolvedSchema:
        pool = load_pool_from_bytes(self._fds_bytes)
        message_class = get_message_class(pool, self._message_type_name)
        return ResolvedSchema(pool, message_class)
