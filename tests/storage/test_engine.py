"""Tests for ``protokit.storage.engine`` — the parse-confined scan loop.

The headline property this unit exists for is **parse-confinement (D5)**: the
raw record bytes (possibly a ``memoryview`` over a caller-owned buffer) are
parsed inside a confined step and never retained in the yielded message, which
is sound because upb copies into its arena on parse. Per the execution note this
suite is driven test-first by the confinement guard below; the ``on_error`` and
shape tests follow. All fault paths use real bytes / real raising callables —
never ``mock.patch`` on a protobuf C-extension method (which silently no-ops).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from google.protobuf import descriptor_pb2
from google.protobuf.message import Message

from protokit.storage.engine import ScanRecord, scan
from protokit.storage.registry import StreamRegistry
from protokit.storage.schema_source import FileDescriptorSetSchema
from protokit.storage.source import FrameError
from tests.storage.proto_fixtures import fds, file_proto

_TYPE_STRING = descriptor_pb2.FieldDescriptorProto.TYPE_STRING

# A truncated frame for A{int32 x=1}: tag for field 1 (wire type 0), then EOF
# where the varint value should be — a real DecodeError, not a mocked one.
_TRUNCATED = b"\x08"


def _registry_and_class(stream_id: str = "s") -> tuple[StreamRegistry, type[Message]]:
    """Register one stream ``a.A`` with ``{int32 x = 1}``; return (registry, class)."""
    fdp = file_proto("a.proto", "a", message="A")
    registry = StreamRegistry()
    registry.register_stream(stream_id, FileDescriptorSetSchema(fds(fdp), "a.A"))
    resolved = registry.get(stream_id)
    assert resolved is not None
    return registry, resolved.message_class


def _two_stream_registry() -> tuple[StreamRegistry, type[Message], type[Message]]:
    """Register ``a`` -> ``a.A{int32 x}`` and ``b`` -> ``b.B{string s}``."""
    a_fdp = file_proto("a.proto", "a", message="A")
    b_fdp = file_proto(
        "b.proto", "b", message="B", field_name="s", field_type=_TYPE_STRING
    )
    registry = StreamRegistry()
    registry.register_stream("a", FileDescriptorSetSchema(fds(a_fdp), "a.A"))
    registry.register_stream("b", FileDescriptorSetSchema(fds(b_fdp), "b.B"))
    a_resolved = registry.get("a")
    b_resolved = registry.get("b")
    assert a_resolved is not None and b_resolved is not None
    return registry, a_resolved.message_class, b_resolved.message_class


class _BufferInvalidatingSource:
    """Yields a ``memoryview`` over a ``bytearray``, then **zeroes** that buffer
    once the consumer pulls the next item — so a parsed message that aliased the
    live view (instead of copying into the arena) would read back as zeros.
    """

    def __init__(self, stream_id: str, payloads: list[bytes]) -> None:
        self._stream_id = stream_id
        self._payloads = payloads
        self.buffers: list[bytearray] = []  # kept so the test can assert zeroing

    def __iter__(self) -> Iterator[tuple[str, memoryview]]:
        for payload in self._payloads:
            buf = bytearray(payload)
            self.buffers.append(buf)
            yield (self._stream_id, memoryview(buf))
            for i in range(len(buf)):
                buf[i] = 0


class _ClosingSource:
    """Iterable with a ``close()`` that records being closed (no context mgr)."""

    def __init__(self, items: list[tuple[str, bytes]]) -> None:
        self._items = items
        self.closed = False

    def __iter__(self) -> Iterator[tuple[str, bytes]]:
        yield from self._items

    def close(self) -> None:
        self.closed = True


class _ContextManagerSource:
    """Iterable that is also a context manager (records enter/exit)."""

    def __init__(self, items: list[tuple[str, bytes]]) -> None:
        self._items = items
        self.entered = False
        self.exited = False

    def __iter__(self) -> Iterator[tuple[str, bytes]]:
        yield from self._items

    def __enter__(self) -> _ContextManagerSource:
        self.entered = True
        return self

    def __exit__(self, *exc: object) -> None:
        self.exited = True


class TestParseConfinement:
    def test_buffer_invalidated_after_yield_message_unaffected(self) -> None:
        registry, a_cls = _registry_and_class("s")
        payloads = [a_cls(x=7).SerializeToString(), a_cls(x=9).SerializeToString()]
        source = _BufferInvalidatingSource("s", payloads)

        records = list(scan(source, registry))

        # Arena copy held: the messages survive their backing buffers being
        # zeroed. This fails if the engine ever retained the live view.
        assert [r.message.x for r in records] == [7, 9]
        assert all(isinstance(r, ScanRecord) for r in records)
        # Teeth: the buffers really were zeroed (otherwise the assertion above
        # would pass vacuously).
        assert all(set(buf) == {0} for buf in source.buffers)
        assert all(len(buf) > 0 for buf in source.buffers)


class TestHappyPathAndPredicate:
    def test_single_stream_yields_every_record(self) -> None:
        registry, a_cls = _registry_and_class("s")
        src = [("s", a_cls(x=i).SerializeToString()) for i in (1, 2, 3)]
        result = scan(iter(src), registry)
        records = list(result)
        assert [r.message.x for r in records] == [1, 2, 3]
        assert [r.stream_id for r in records] == ["s", "s", "s"]
        assert [r.record_index for r in records] == [0, 1, 2]
        assert result.errors == ()

    def test_predicate_filters_but_record_index_stays_global(self) -> None:
        registry, a_cls = _registry_and_class("s")
        src = [("s", a_cls(x=i).SerializeToString()) for i in range(5)]
        result = scan(iter(src), registry, predicate=lambda m: m.x % 2 == 0)
        records = list(result)
        assert [r.message.x for r in records] == [0, 2, 4]
        # record_index is the GLOBAL feed position, not the filtered position.
        assert [r.record_index for r in records] == [0, 2, 4]

    def test_zero_length_record_is_a_default_message_not_an_error(self) -> None:
        registry, _a_cls = _registry_and_class("s")
        records = list(scan(iter([("s", b"")]), registry))
        assert len(records) == 1
        assert records[0].message.x == 0  # all-defaults, valid protobuf

    def test_zero_length_record_runs_through_predicate(self) -> None:
        registry, _a_cls = _registry_and_class("s")
        seen: list[int] = []

        def record_x(m: Message) -> bool:
            seen.append(m.x)
            return True

        list(scan(iter([("s", b"")]), registry, predicate=record_x))
        assert seen == [0]


class TestMultiStreamRouting:
    def test_interleaved_feed_routes_to_correct_class_and_global_index(self) -> None:
        registry, a_cls, b_cls = _two_stream_registry()
        src = [
            ("a", a_cls(x=1).SerializeToString()),
            ("b", b_cls(s="hello").SerializeToString()),
            ("a", a_cls(x=2).SerializeToString()),
        ]
        records = list(scan(iter(src), registry))
        assert [r.stream_id for r in records] == ["a", "b", "a"]
        # Global counter, not per-stream (which would be 0, 0, 1).
        assert [r.record_index for r in records] == [0, 1, 2]
        assert records[0].message.x == 1
        assert records[1].message.s == "hello"
        assert records[2].message.x == 2


class TestMalformedItemGuard:
    def test_malformed_items_become_frame_errors_not_raw_exceptions(self) -> None:
        registry, a_cls = _registry_and_class("s")
        src: list[object] = [
            ("s", a_cls(x=1).SerializeToString()),
            b"not-a-tuple",  # bare bytes
            (b"bytes-first", "s"),  # transposed: not (str, bytes)
            ("s", a_cls(x=2).SerializeToString()),
        ]
        result = scan(iter(src), registry, on_error="collect")  # type: ignore[arg-type]
        records = list(result)
        assert [r.message.x for r in records] == [1, 2]
        errors = result.errors
        assert [e.record_index for e in errors] == [1, 2]
        assert all("malformed record" in e.reason for e in errors)
        assert all(e.offset is None for e in errors)


class TestOnErrorModes:
    def test_raise_mode_propagates_frame_error_on_decode_failure(self) -> None:
        registry, a_cls = _registry_and_class("s")
        src = [("s", a_cls(x=1).SerializeToString()), ("s", _TRUNCATED)]
        it = iter(scan(iter(src), registry))  # default on_error='raise'
        assert next(it).message.x == 1
        with pytest.raises(FrameError) as exc:
            next(it)
        assert exc.value.stream_id == "s"
        assert exc.value.record_index == 1

    def test_skip_mode_drops_bad_keeps_good(self) -> None:
        registry, a_cls = _registry_and_class("s")
        src = [
            ("s", a_cls(x=1).SerializeToString()),
            ("s", _TRUNCATED),
            ("s", a_cls(x=3).SerializeToString()),
        ]
        result = scan(iter(src), registry, on_error="skip")
        records = list(result)
        assert [r.message.x for r in records] == [1, 3]
        assert result.errors == ()

    def test_collect_mode_reports_errors_after_exhaustion(self) -> None:
        registry, a_cls = _registry_and_class("s")
        src = [
            ("s", a_cls(x=1).SerializeToString()),
            ("s", _TRUNCATED),
            ("s", a_cls(x=3).SerializeToString()),
        ]
        result = scan(iter(src), registry, on_error="collect")
        records = list(result)
        assert [r.message.x for r in records] == [1, 3]
        errors = result.errors
        assert len(errors) == 1
        assert errors[0].stream_id == "s"
        assert errors[0].record_index == 1

    def test_errors_loud_guard_before_exhaustion(self) -> None:
        registry, a_cls = _registry_and_class("s")
        src = [("s", a_cls(x=1).SerializeToString()), ("s", a_cls(x=2).SerializeToString())]
        result = scan(iter(src), registry, on_error="collect")
        it = iter(result)
        next(it)  # consume one; keep `it` referenced so it is not GC-closed
        with pytest.raises(RuntimeError, match="exhausted"):
            _ = result.errors
        list(it)  # finish
        assert result.errors == ()


class TestUnknownStream:
    def test_unknown_stream_id_raises_by_default(self) -> None:
        registry, a_cls = _registry_and_class("known")
        src = [("unknown", a_cls(x=1).SerializeToString())]
        with pytest.raises(FrameError) as exc:
            list(scan(iter(src), registry))
        assert exc.value.stream_id == "unknown"
        assert "unknown stream_id" in exc.value.reason

    def test_unknown_stream_id_collected(self) -> None:
        registry, a_cls = _registry_and_class("known")
        src = [
            ("unknown", a_cls(x=1).SerializeToString()),
            ("known", a_cls(x=2).SerializeToString()),
        ]
        result = scan(iter(src), registry, on_error="collect")
        records = list(result)
        assert [r.message.x for r in records] == [2]
        assert [e.stream_id for e in result.errors] == ["unknown"]


class TestExceptionPropagation:
    def test_predicate_exception_propagates_even_in_skip_mode(self) -> None:
        registry, a_cls = _registry_and_class("s")
        src = [("s", a_cls(x=1).SerializeToString())]

        def boom(_m: Message) -> bool:
            raise ValueError("predicate bug")

        with pytest.raises(ValueError, match="predicate bug"):
            list(scan(iter(src), registry, on_error="skip", predicate=boom))

    def test_base_exception_from_source_is_never_swallowed(self) -> None:
        registry, a_cls = _registry_and_class("s")

        def raising_source() -> Iterator[tuple[str, bytes]]:
            yield ("s", a_cls(x=1).SerializeToString())
            raise KeyboardInterrupt("user interrupt")

        # collect mode must NOT swallow a BaseException (it catches only
        # FrameError). Driven by a real raising generator, not mock.patch.
        with pytest.raises(KeyboardInterrupt):
            list(scan(raising_source(), registry, on_error="collect"))


class TestSourceCleanup:
    def test_close_called_after_normal_exhaustion(self) -> None:
        registry, a_cls = _registry_and_class("s")
        src = _ClosingSource([("s", a_cls(x=1).SerializeToString())])
        list(scan(src, registry))
        assert src.closed

    def test_close_called_after_mid_iteration_exception(self) -> None:
        registry, a_cls = _registry_and_class("s")
        src = _ClosingSource([("s", a_cls(x=1).SerializeToString()), ("s", _TRUNCATED)])
        with pytest.raises(FrameError):
            list(scan(src, registry))  # raise mode; second record decode-fails
        assert src.closed

    def test_context_manager_source_is_entered_and_exited(self) -> None:
        registry, a_cls = _registry_and_class("s")
        src = _ContextManagerSource([("s", a_cls(x=1).SerializeToString())])
        list(scan(src, registry))
        assert src.entered
        assert src.exited


class TestEagerValidationAndLifecycle:
    def test_invalid_on_error_raises_at_call_time(self) -> None:
        registry, _a_cls = _registry_and_class("s")
        with pytest.raises(ValueError, match="on_error"):
            # Raises before any record is read (eager validation).
            scan(iter([]), registry, on_error="bogus")  # type: ignore[arg-type]

    def test_scan_result_iterates_only_once(self) -> None:
        registry, a_cls = _registry_and_class("s")
        result = scan(iter([("s", a_cls(x=1).SerializeToString())]), registry)
        list(result)
        with pytest.raises(RuntimeError, match="once"):
            list(result)
