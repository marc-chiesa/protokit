"""``length_delimited`` — the file-default reference ``Source``.

Reads protobuf's length-delimited convention: each record is a base-128 varint
length prefix followed by exactly that many message bytes, repeated to EOF. This
is the format ``writeDelimitedTo`` / ``SerializeDelimitedToString`` produce and
the natural shape for a file of concatenated messages.

Read model (one of the two the plan left to implementation): an **incremental
reader over ``file.read``** — varint bytes are pulled one at a time and the body
in a single sized read. This streams in O(single record) memory (no whole-file
buffering) and cleanly distinguishes a 0-byte read at a frame boundary (clean
EOF → stop) from a short read mid-frame (truncation → ``FrameError``). The
private ``google.protobuf.internal.decoder._DecodeVarint`` is deliberately not
used: it needs an indexable buffer (not a file object) and raises ``IndexError``
indistinguishably for clean EOF and truncation.

The source **takes ownership of ``file``** and closes it when iteration finishes
or the generator is closed — so :func:`~protokit.storage.scan`'s source-cleanup
closes the handle on both normal exhaustion and a mid-iteration exception.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import BinaryIO

from protokit.storage.source import FrameError

_DEFAULT_MAX_FRAME_SIZE = 64 * 1024 * 1024  # 64 MiB safety cap
_VARINT_MAX_BITS = 64


class _IncompleteVarintError(Exception):
    """Internal: a length-prefix varint could not be completed."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _read_varint(file: BinaryIO) -> tuple[int, int] | None:
    """Read one base-128 varint from ``file``.

    Returns ``(value, bytes_consumed)``; returns ``None`` for a clean EOF at a
    frame boundary (zero bytes available). Raises :class:`_IncompleteVarintError` if
    the stream ends partway through a varint or the varint overflows 64 bits.
    """
    result = 0
    shift = 0
    consumed = 0
    while True:
        chunk = file.read(1)
        if not chunk:
            if consumed == 0:
                return None  # clean EOF — no partial frame in progress
            raise _IncompleteVarintError("stream ended mid length-prefix varint")
        byte = chunk[0]
        result |= (byte & 0x7F) << shift
        consumed += 1
        if not byte & 0x80:
            return result, consumed
        shift += 7
        if shift >= _VARINT_MAX_BITS:
            raise _IncompleteVarintError("length-prefix varint exceeds 64 bits (malformed)")


def length_delimited(
    file: BinaryIO,
    *,
    stream_id: str,
    max_frame_size: int = _DEFAULT_MAX_FRAME_SIZE,
) -> Iterator[tuple[str, bytes]]:
    """Yield ``(stream_id, record_bytes)`` for each length-delimited frame.

    Args:
        file: A binary readable stream of varint-prefixed frames. **Owned** by
            this source — it is closed when iteration completes or the generator
            is closed.
        stream_id: The fixed routing tag for every frame (a homogeneous stream).
        max_frame_size: Reject a declared frame length above this (default 64
            MiB) with a ``FrameError`` raised **before** the body is read or
            allocated — a corrupt/hostile length prefix cannot drive a huge read
            without the caller raising the cap.

    Yields:
        ``(stream_id, body)`` per frame. A declared length of 0 yields
        ``(stream_id, b"")`` (a valid all-defaults message), distinct from
        whole-stream EOF.

    Raises:
        FrameError: a truncated length prefix, a declared length above
            ``max_frame_size``, or a truncated body. ``offset`` is the byte
            position in the stream where the fault was detected.
    """
    offset = 0
    record_index = -1
    try:
        while True:
            record_index += 1
            frame_start = offset
            try:
                prefix = _read_varint(file)
            except _IncompleteVarintError as incomplete:
                raise FrameError(
                    stream_id, record_index, frame_start, incomplete.reason
                ) from incomplete
            if prefix is None:
                return  # clean EOF at a frame boundary
            length, prefix_len = prefix
            offset += prefix_len  # now positioned at the body

            if length > max_frame_size:
                raise FrameError(
                    stream_id,
                    record_index,
                    offset,
                    f"declared frame length {length} exceeds max_frame_size "
                    f"{max_frame_size} (raise max_frame_size to allow)",
                )

            body = file.read(length)
            if len(body) != length:
                raise FrameError(
                    stream_id,
                    record_index,
                    offset,
                    f"truncated frame body: expected {length} bytes, "
                    f"got {len(body)}",
                )
            offset += len(body)
            yield (stream_id, body)
    finally:
        file.close()
