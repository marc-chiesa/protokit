"""``per_message_view`` — the pybind11 reference ``Source``.

Yields a ``memoryview`` over each caller-supplied buffer, tagged with a fixed
``stream_id``. This is the zero-copy shape the maintainer's pybind11 library
exposes — a per-message ``memoryview`` into a C++-owned buffer — and the
``Reader``-shim docs example. It is **view-only**: the caller owns the
underlying buffers' lifetime, and the engine's parse-confinement (upb copies
into its arena) is what makes handing off a live view safe.
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
        ``(stream_id, memoryview)`` — a zero-copy view, never a copy.
    """
    for buffer in buffers:
        yield (stream_id, memoryview(buffer))
