"""Adapter boundary for the storage scan engine: the ``Source`` protocol and
the storage exception hierarchy.

A ``Source`` is the single extension point through which user code feeds
stored protobuf into :func:`protokit.storage.scan`. It yields
``(stream_id, record_bytes)`` pairs and nothing more — protokit deliberately
stays out of the I/O and framing business, because the maintainer's storage
layout (a pybind11-wrapped C++ library exposing per-message ``memoryview``,
files of length-delimited frames, an object store, ...) is unbounded and not
protokit's to model.

Why an adapter boundary
-----------------------
Modelling the user's storage would couple protokit to one layout. Instead the
engine names the *minimal* contract — a stream tag plus a record's bytes — and
lets the caller own buffer lifetime and framing. A ``memoryview`` from a
C++-owned buffer is a first-class record bytes value — the source need not
materialize bytes up front: the engine takes one defensive copy at the parse
boundary and never retains the live view, so the caller may free the buffer the
instant a record is consumed (see ``protokit.storage.engine``). The two reference adapters in
``protokit.storage.sources`` are *examples* of the boundary, not protokit's
framing taxonomy.

``runtime_checkable`` caveat
----------------------------
``Source`` is a ``runtime_checkable`` ``Protocol`` so third-party adapters are
recognised structurally. But ``isinstance(x, Source)`` is a **method-presence
check only** — it confirms ``x`` has ``__iter__`` and nothing about what that
iterator yields. Every iterable (``str``, ``list``, ``dict``, ``tuple``)
therefore passes it. Real protection against a malformed record is the engine's
*per-record* element-shape guard, not ``isinstance`` and not a one-time
first-record check.

Public surface:

- ``Source`` — the adapter protocol (``__iter__`` yielding
  ``(stream_id, record_bytes)``).
- ``StorageError`` — base of every typed exception this subpackage raises.
- ``FrameError`` — a per-record fault (framing, unknown stream, decode failure);
  also the element type of the ``collect``-mode errors report.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable


class StorageError(Exception):
    """Base for every typed exception raised by ``protokit.storage``.

    Mirrors the shape of ``protokit._pools.DescriptorPoolError``: a plain
    ``Exception`` subclass whose concrete subclasses store the fault's
    structured attributes and bake a human-readable message. Schema-resolution
    failures are *not* remapped onto this hierarchy — they propagate the Lane A
    ``DescriptorPoolError`` family (``MessageTypeNotFoundError``,
    ``MissingDependencyError``, ``DuplicateFileError``) unwrapped, since those
    are already typed library exceptions.
    """


class FrameError(StorageError):
    """A single record could not be turned into a message.

    Raised by a ``Source`` (its own framing — e.g. a truncated length prefix)
    and by the engine (an unknown ``stream_id``, a malformed yielded item, or a
    protobuf decode failure wrapped here). Under ``on_error='collect'`` it is
    also the element type of ``ScanResult.errors``.

    The four attributes are stored verbatim so callers can correlate and report
    faults precisely rather than scraping the message string:

    Attributes:
        stream_id: The stream the faulting record was routed to. For an
            unknown-stream fault this is the unrecognised tag itself; for a
            malformed yielded item (which has no usable tag) it is a truncated
            ``repr`` of the offending item.
        record_index: The global feed position of the record (a single
            monotonically-ascending counter over every item the ``Source``
            yields, regardless of stream). A debug/correlation handle, *not* a
            cross-stream join key.
        offset: Byte offset within the record where framing failed, or ``None``
            for a non-positional fault (unknown stream, malformed item, a decode
            failure the runtime does not localise).
        reason: Human-readable explanation; always present in ``str(exc)``.
    """

    def __init__(
        self,
        stream_id: str,
        record_index: int,
        offset: int | None,
        reason: str,
    ) -> None:
        self.stream_id = stream_id
        self.record_index = record_index
        self.offset = offset
        self.reason = reason
        where = f"offset {offset}" if offset is not None else "offset unknown"
        super().__init__(
            f"frame error in stream {stream_id!r} at record {record_index} "
            f"({where}): {reason}"
        )


@runtime_checkable
class Source(Protocol):
    """A stream of ``(stream_id, record_bytes)`` records fed to :func:`scan`.

    Iterating a ``Source`` yields ``tuple[str, bytes | memoryview]`` pairs: a
    ``stream_id`` routing tag and the record's serialized protobuf bytes. The
    record bytes may be a ``memoryview`` over a caller-owned (e.g. C++-owned)
    buffer — the source need not materialize bytes; the engine takes one
    defensive copy at the parse boundary and never retains the view, so the
    caller may free or reuse the buffer once a record has been consumed.

    Only ``__iter__`` is part of the structural contract, so a plain generator
    that yields the tuples satisfies ``Source``. Cleanup is *capability-probed,
    not required*: if a source needs deterministic teardown of a file handle or
    a native resource, it may additionally implement either the context-manager
    protocol (``__enter__``/``__exit__``) or ``close()``. :func:`scan` owns the
    source for the scan's duration and will close it — preferring ``with`` when
    available, else ``close()`` — on both normal exhaustion and a mid-iteration
    exception. A bare generator carries ``close()`` natively, so it gets this
    cleanup for free without being excluded from the protocol.

    A source signals a per-record framing fault by raising
    :class:`FrameError`; the engine routes it through the active ``on_error``
    policy.
    """

    def __iter__(self) -> Iterator[tuple[str, bytes | memoryview]]:
        """Yield ``(stream_id, record_bytes)`` pairs in feed order."""
        ...
