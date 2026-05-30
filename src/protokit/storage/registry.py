"""``StreamRegistry`` — the routing table from ``stream_id`` to its resolved,
isolated schema.

The registry enforces the **register-up-front / feed-later** split: a stream's
``SchemaSource`` is resolved **once**, at ``register_stream`` time, into a
cached ``(pool, message_class)`` pair. Resolution (and therefore validation —
missing dependencies, unknown types, duplicate files) happens at this boundary,
not mid-scan, so a malformed schema fails loudly before any data is fed.

Two trust boundaries are kept distinct (KD-7):

- **Duplicate registration** is a caller-side *programming error*, raised here as
  :class:`DuplicateStreamError` and never reaching the scan loop.
- **An unknown ``stream_id`` at feed time** is a per-record *data fault* — a
  corrupt file could carry an unexpected tag — so the registry merely signals a
  miss (``get`` returns ``None``) and the engine turns it into a
  ``FrameError`` governed by ``on_error``. The registry itself never raises on a
  lookup miss.

Every pool is a fresh, isolated ``DescriptorPool`` (via the ``SchemaSource`` →
Lane A), never the default pool, so concurrently-registered streams may hold
conflicting versions of the same fully-qualified type without collision.

Public surface:

- ``StreamRegistry`` — register streams, then look them up by ``stream_id``.
- ``DuplicateStreamError`` — a ``stream_id`` was registered twice.
"""

from __future__ import annotations

from protokit.storage.schema_source import ResolvedSchema, SchemaSource
from protokit.storage.source import StorageError


class DuplicateStreamError(StorageError):
    """A ``stream_id`` was registered more than once.

    A programming error at the register boundary (KD-5/KD-7): each stream may be
    registered exactly once. *Not* subject to ``on_error`` — it never reaches
    the scan loop.

    Attributes:
        stream_id: The id whose second registration was rejected.
    """

    def __init__(self, stream_id: str) -> None:
        self.stream_id = stream_id
        super().__init__(
            f"stream_id {stream_id!r} is already registered; each stream may "
            f"be registered exactly once."
        )


class StreamRegistry:
    """Maps each ``stream_id`` to its resolved, isolated ``ResolvedSchema``.

    Resolve every stream up front with :meth:`register_stream`, then hand the
    registry to :func:`protokit.storage.scan`, which consults it per record.
    """

    def __init__(self) -> None:
        self._streams: dict[str, ResolvedSchema] = {}

    def register_stream(self, stream_id: str, schema_source: SchemaSource) -> None:
        """Resolve ``schema_source`` once and cache it under ``stream_id``.

        Resolution happens here, at the boundary, so a malformed or incomplete
        schema raises now rather than mid-scan.

        Args:
            stream_id: The routing tag records of this stream carry.
            schema_source: The stream's schema; ``resolve()`` is called exactly
                once. A third-party source may return a plain ``(pool,
                message_class)`` 2-tuple — it is normalised to a
                ``ResolvedSchema`` here so lookups always expose ``.pool`` /
                ``.message_class``.

        Raises:
            DuplicateStreamError: ``stream_id`` is already registered.
            protokit._pools.DescriptorPoolError: subclasses, propagated from
                ``resolve()`` for a missing dependency, unknown type, duplicate
                file, or dependency cycle.
        """
        if stream_id in self._streams:
            raise DuplicateStreamError(stream_id)
        # Resolve once and normalise at the boundary: a third-party source may
        # return a bare 2-tuple, so unpack positionally and re-wrap.
        pool, message_class = schema_source.resolve()
        self._streams[stream_id] = ResolvedSchema(pool, message_class)

    def get(self, stream_id: str) -> ResolvedSchema | None:
        """Return the cached schema for ``stream_id``, or ``None`` on a miss.

        A miss is **not** an error the registry raises — the engine translates
        ``None`` into a ``FrameError`` under the active ``on_error`` policy
        (KD-7). The returned object is the cached instance, so repeated lookups
        return the *same* ``message_class`` (no re-resolution).
        """
        return self._streams.get(stream_id)

    def __contains__(self, stream_id: object) -> bool:
        """Return whether ``stream_id`` has been registered."""
        return stream_id in self._streams
