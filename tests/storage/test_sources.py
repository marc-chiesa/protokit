"""Tests for ``protokit.storage.sources`` — the two reference ``Source`` adapters.

``length_delimited`` framing faults are driven with **real** truncated /
oversized byte streams (never mocked); cleanup and file-vs-view parity are
asserted end-to-end through :func:`scan`.
"""

from __future__ import annotations

import io

import pytest
from google.protobuf.message import Message

from protokit.storage.engine import scan
from protokit.storage.registry import StreamRegistry
from protokit.storage.schema_source import FileDescriptorSetSchema
from protokit.storage.source import FrameError
from protokit.storage.sources import length_delimited, per_message_view
from tests.storage.proto_fixtures import delimited, encode_varint, fds, file_proto


def _registry_and_class(stream_id: str = "s") -> tuple[StreamRegistry, type[Message]]:
    fdp = file_proto("a.proto", "a", message="A")
    registry = StreamRegistry()
    registry.register_stream(stream_id, FileDescriptorSetSchema(fds(fdp), "a.A"))
    resolved = registry.get(stream_id)
    assert resolved is not None
    return registry, resolved.message_class


class TestLengthDelimitedFraming:
    def test_round_trips_records_in_order(self) -> None:
        payloads = [b"\x08\x01", b"\x08\x02", b"\x08\x03"]
        stream = io.BytesIO(delimited(*payloads))
        records = list(length_delimited(stream, stream_id="s"))
        assert [r[0] for r in records] == ["s", "s", "s"]
        assert [r[1] for r in records] == payloads

    def test_empty_input_is_zero_frames_clean_stop(self) -> None:
        records = list(length_delimited(io.BytesIO(b""), stream_id="s"))
        assert records == []

    def test_declared_length_zero_yields_empty_record(self) -> None:
        # A 0-length frame inside a non-empty stream is a valid empty record,
        # distinct from whole-stream EOF.
        stream = io.BytesIO(delimited(b"", b"\x08\x07"))
        records = list(length_delimited(stream, stream_id="s"))
        assert [r[1] for r in records] == [b"", b"\x08\x07"]

    def test_truncated_body_raises_frame_error_with_offset(self) -> None:
        # Declare length 5 but supply only 2 body bytes.
        stream = io.BytesIO(encode_varint(5) + b"\x08\x07")
        with pytest.raises(FrameError) as exc:
            list(length_delimited(stream, stream_id="s"))
        assert exc.value.offset is not None
        assert "truncated frame body" in exc.value.reason

    def test_truncated_varint_prefix_raises_frame_error(self) -> None:
        # A lone continuation byte (0x80) then EOF: the varint never completes.
        stream = io.BytesIO(b"\x80")
        with pytest.raises(FrameError) as exc:
            list(length_delimited(stream, stream_id="s"))
        assert "varint" in exc.value.reason

    def test_oversized_length_rejected_before_body_read(self) -> None:
        # Declare a 128 MiB frame (over the 64 MiB default) with NO body present.
        # The size guard must fire before any body read/allocation, so the error
        # is the oversize one, not a truncated-body one.
        stream = io.BytesIO(encode_varint(128 * 1024 * 1024))
        with pytest.raises(FrameError) as exc:
            list(length_delimited(stream, stream_id="s"))
        assert "exceeds max_frame_size" in exc.value.reason

    def test_oversized_allowed_when_cap_raised(self) -> None:
        payload = b"\x08\x07"
        stream = io.BytesIO(delimited(payload))
        # A tiny cap below the payload rejects; a generous cap accepts.
        records = list(
            length_delimited(stream, stream_id="s", max_frame_size=1024)
        )
        assert [r[1] for r in records] == [payload]


class TestPerMessageView:
    def test_yields_memoryview_per_buffer_not_a_copy(self) -> None:
        buffers = [b"\x08\x01", b"\x08\x02"]
        records = list(per_message_view(buffers, stream_id="s"))
        assert [r[0] for r in records] == ["s", "s"]
        assert all(isinstance(r[1], memoryview) for r in records)
        # The view reflects the source bytes (zero-copy).
        assert bytes(records[0][1]) == b"\x08\x01"

    def test_memoryview_over_bytearray_tracks_mutation(self) -> None:
        # Proves it is a view, not a copy: mutating the bytearray before the
        # view is consumed changes what the view sees.
        buf = bytearray(b"\x08\x01")
        (record,) = list(per_message_view([buf], stream_id="s"))
        buf[1] = 0x09
        assert bytes(record[1]) == b"\x08\x09"


class TestEngineIntegration:
    def test_file_handle_closed_after_normal_scan(self) -> None:
        registry, a_cls = _registry_and_class("s")
        stream = io.BytesIO(
            delimited(a_cls(x=1).SerializeToString(), a_cls(x=2).SerializeToString())
        )
        records = list(scan(length_delimited(stream, stream_id="s"), registry))
        assert [r.message.x for r in records] == [1, 2]
        assert stream.closed  # source-cleanup closed the handle

    def test_file_handle_closed_after_mid_iteration_exception(self) -> None:
        registry, a_cls = _registry_and_class("s")
        # A good frame followed by a truncated body: raise mode aborts mid-scan.
        good = a_cls(x=1).SerializeToString()
        stream = io.BytesIO(delimited(good) + encode_varint(9) + b"\x08")
        with pytest.raises(FrameError):
            list(scan(length_delimited(stream, stream_id="s"), registry))
        assert stream.closed

    def test_file_and_view_sources_parse_identically(self) -> None:
        registry, a_cls = _registry_and_class("s")
        payloads = [a_cls(x=i).SerializeToString() for i in (10, 20, 30)]

        file_records = list(
            scan(length_delimited(io.BytesIO(delimited(*payloads)), stream_id="s"),
                 registry)
        )
        view_records = list(
            scan(per_message_view(payloads, stream_id="s"), registry)
        )

        assert [r.message.x for r in file_records] == [10, 20, 30]
        assert [r.message.x for r in view_records] == [10, 20, 30]
        assert [r.stream_id for r in file_records] == [r.stream_id for r in view_records]


class _ShortReadStream:
    """A binary stream whose ``read(n)`` returns at most ``cap`` bytes per call,
    modelling a ``RawIOBase`` / pipe / socket that legitimately short-reads.
    """

    def __init__(self, data: bytes, cap: int) -> None:
        self._data = data
        self._pos = 0
        self._cap = cap
        self.closed = False

    def read(self, n: int = -1) -> bytes:
        want = (len(self._data) - self._pos) if n < 0 else min(n, self._cap)
        end = min(self._pos + want, len(self._data))
        out = self._data[self._pos:end]
        self._pos = end
        return out

    def close(self) -> None:
        self.closed = True


class _RaisingCloseStream:
    """Wraps a BytesIO but raises from close()."""

    def __init__(self, data: bytes) -> None:
        self._bio = io.BytesIO(data)

    def read(self, n: int = -1) -> bytes:
        return self._bio.read(n)

    def close(self) -> None:
        raise OSError("close failed")


class TestShortReads:
    def test_short_reads_do_not_cause_false_truncation(self) -> None:
        # read() returns 1 byte at a time; the read-exact loop must reassemble
        # multi-byte bodies instead of declaring a false truncation.
        payloads = [b"\x08\x01\x10\x02", b"\x08\x03"]
        stream = _ShortReadStream(delimited(*payloads), cap=1)
        records = list(length_delimited(stream, stream_id="s"))  # type: ignore[arg-type]
        assert [r[1] for r in records] == payloads

    def test_genuine_truncation_still_detected_under_short_reads(self) -> None:
        # Declares a 4-byte body but only 2 bytes exist; a 0-byte read ends the
        # accumulation and the length mismatch is a real truncation.
        stream = _ShortReadStream(encode_varint(4) + b"\x08\x01", cap=1)
        with pytest.raises(FrameError) as exc:
            list(length_delimited(stream, stream_id="s"))  # type: ignore[arg-type]
        assert "truncated frame body" in exc.value.reason


class TestVarintOverflow:
    def test_over_64_bit_length_prefix_rejected_as_malformed(self) -> None:
        # Ten 0xFF bytes: the 10th carries value bits beyond bit 63 -> overflow.
        blob = b"\xff" * 10
        with pytest.raises(FrameError) as exc:
            list(length_delimited(io.BytesIO(blob), stream_id="s"))
        assert "exceeds 64 bits" in exc.value.reason


class TestCloseDoesNotMask:
    def test_close_error_does_not_clobber_in_flight_frame_error(self) -> None:
        # Truncated body raises FrameError; close() also raises, but the
        # FrameError (the actionable fault) must be what propagates.
        stream = _RaisingCloseStream(encode_varint(9) + b"\x08")
        with pytest.raises(FrameError):
            list(length_delimited(stream, stream_id="s"))  # type: ignore[arg-type]

    def test_close_error_surfaces_on_clean_exhaustion(self) -> None:
        # No framing fault: a close() error is the only signal, so it must
        # surface (suppression applies only when masking an in-flight fault).
        stream = _RaisingCloseStream(delimited(b"\x08\x01"))
        with pytest.raises(OSError, match="close failed"):
            list(length_delimited(stream, stream_id="s"))  # type: ignore[arg-type]
