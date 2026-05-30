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
