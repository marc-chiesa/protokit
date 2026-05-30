"""``per_message_view`` — the pybind11 reference ``Source``.

Yields a ``memoryview`` over each caller-supplied buffer, tagged with a fixed
``stream_id``. This is the shape the maintainer's pybind11 library exposes — a
per-message ``memoryview`` into a C++-owned buffer — and the ``Reader``-shim
docs example. The adapter itself does not copy; it is **view-only**, and the
caller owns the underlying buffers' lifetime. The engine takes one defensive
copy at the parse boundary (and upb copies into its arena), so a record can be
handed off as a live view and the buffer freed once the record is consumed.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator


def per_message_view(
    buffers: Iterable[bytes | bytearray | memoryview],
    *,
    stream_id: str,
) -> Iterator[tuple[str, memoryview]]:
    """Yield ``(stream_id, memoryview(buffer))`` for each buffer.

    Args:
        buffers: An iterable of message-sized byte buffers (each a serialized
            protobuf message). A ``memoryview`` element is wrapped without
            copying; the caller retains ownership of the underlying memory.
        stream_id: The fixed routing tag for every record.

    Yields:
        ``(stream_id, memoryview)`` — the adapter wraps each buffer in a view
        without copying (the engine copies once, later, at parse).
    """
    for buffer in buffers:
        yield (stream_id, memoryview(buffer))
