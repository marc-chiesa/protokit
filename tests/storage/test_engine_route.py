"""Tests for ``on_error='route'`` + ``error_sink`` — the live-callback tolerant
mode (the fourth ``OnError`` value, added in PR1.5).

The mode is governed by the three storage learnings the engine already encodes:
the sink runs **outside** the narrow ``{FrameError, DecodeError}`` catch (so a
raising sink propagates, like a predicate bug), the released-``memoryview``
``ValueError`` still flies past on its own fail-loud path, and ``.errors`` refuses
to hand back a silent partial — under ``route`` it raises rather than returning a
misleading ``()``.

Per the engine's execution note this is driven test-first by the raising-sink
propagation property below. Fault paths use real bytes / real raising callables —
never ``mock.patch`` on a protobuf C-extension method.
"""

from __future__ import annotations

import typing
from collections.abc import Iterator

import pytest
from google.protobuf.message import Message

from protokit.storage.engine import OnError, ScanResult, scan
from protokit.storage.source import FrameError
from tests.storage.proto_fixtures import registry_and_class as _registry_and_class

# Truncated frame for A{int32 x=1}: field-1 tag then EOF -> a real DecodeError.
_TRUNCATED = b"\x08"


def _sink() -> tuple[list[FrameError], typing.Callable[[FrameError], None]]:
    """A list-appending error sink plus the list it fills."""
    seen: list[FrameError] = []
    return seen, seen.append


class _ClosingSource:
    """Iterable with a ``close()`` that records being closed."""

    def __init__(self, items: list[tuple[str, bytes]]) -> None:
        self._items = items
        self.closed = False

    def __iter__(self) -> Iterator[tuple[str, bytes]]:
        yield from self._items

    def close(self) -> None:
        self.closed = True


class _ReleasedViewSource:
    """Yields a ``memoryview`` released before the engine parses it."""

    def __init__(self, stream_id: str, payloads: list[bytes]) -> None:
        self._stream_id = stream_id
        self._payloads = payloads

    def __iter__(self) -> Iterator[tuple[str, memoryview]]:
        for payload in self._payloads:
            view = memoryview(bytearray(payload))
            view.release()
            yield (self._stream_id, view)


class TestRoutePropagationProperties:
    def test_raising_error_sink_propagates(self) -> None:
        # Headline safety property (execution note): a sink bug is caller code,
        # not a data fault, so it propagates rather than being swallowed.
        registry, a_cls = _registry_and_class("s")

        def boom(_e: FrameError) -> None:
            raise RuntimeError("sink blew up")

        src = [("s", _TRUNCATED), ("s", a_cls(x=1).SerializeToString())]
        with pytest.raises(RuntimeError, match="sink blew up"):
            list(scan(iter(src), registry, on_error="route", error_sink=boom))

    def test_baseexception_under_route_propagates(self) -> None:
        registry, _a_cls = _registry_and_class("s")
        _seen, sink = _sink()

        def interrupting() -> Iterator[tuple[str, bytes]]:
            raise KeyboardInterrupt
            yield  # pragma: no cover

        with pytest.raises(KeyboardInterrupt):
            list(scan(interrupting(), registry, on_error="route", error_sink=sink))

    def test_predicate_exception_under_route_propagates(self) -> None:
        registry, a_cls = _registry_and_class("s")
        _seen, sink = _sink()

        def boom(_m: Message) -> bool:
            raise ValueError("predicate blew up")

        src = [("s", a_cls(x=1).SerializeToString())]
        with pytest.raises(ValueError, match="predicate blew up"):
            list(
                scan(
                    iter(src),
                    registry,
                    predicate=boom,
                    on_error="route",
                    error_sink=sink,
                )
            )

    def test_released_view_under_route_raises_value_error_not_crash(self) -> None:
        # The released-view ValueError comes from the parse boundary, never
        # reaches _dispatch, and so is unaffected by route. In-process per the
        # repo convention: a regression to MergeFromString(raw) would SIGSEGV and
        # kill the run, which is the signal.
        registry, a_cls = _registry_and_class("s")
        _seen, sink = _sink()
        source = _ReleasedViewSource("s", [a_cls(x=1).SerializeToString()])
        with pytest.raises(ValueError):
            list(scan(source, registry, on_error="route", error_sink=sink))


class TestRouteDelivery:
    def test_route_delivers_each_fault_live_and_yields_good(self) -> None:
        registry, a_cls = _registry_and_class("s")
        seen, sink = _sink()
        good1 = a_cls(x=7).SerializeToString()
        good2 = a_cls(x=9).SerializeToString()
        # good, decode-bad, good, unknown-stream-bad
        src = [
            ("s", good1),
            ("s", _TRUNCATED),
            ("s", good2),
            ("nope", good1),
        ]
        records = list(scan(iter(src), registry, on_error="route", error_sink=sink))

        assert [r.message.x for r in records] == [7, 9]
        assert [e.record_index for e in seen] == [1, 3]
        assert all(isinstance(e, FrameError) for e in seen)
        assert seen[0].stream_id == "s"  # decode fault keeps its tag
        assert seen[1].stream_id == "nope"  # unknown-stream fault carries the tag
        assert seen[1].reason == "unknown stream_id"

    def test_route_all_good_feed_never_calls_sink(self) -> None:
        registry, a_cls = _registry_and_class("s")
        seen, sink = _sink()
        src = [("s", a_cls(x=1).SerializeToString()), ("s", a_cls(x=2).SerializeToString())]
        records = list(scan(iter(src), registry, on_error="route", error_sink=sink))
        assert [r.message.x for r in records] == [1, 2]
        assert seen == []

    def test_route_empty_feed_never_calls_sink(self) -> None:
        registry, _a_cls = _registry_and_class("s")
        seen, sink = _sink()
        records = list(scan(iter([]), registry, on_error="route", error_sink=sink))
        assert records == []
        assert seen == []

    def test_route_early_break_does_not_reach_later_fault(self) -> None:
        # The head -n consumer: break before the fault. The sink never fires for
        # a fault positioned after the break, and the source is closed.
        registry, a_cls = _registry_and_class("s")
        seen, sink = _sink()
        source = _ClosingSource(
            [("s", a_cls(x=1).SerializeToString()), ("s", _TRUNCATED)]
        )
        result = scan(source, registry, on_error="route", error_sink=sink)
        first = next(iter(result))
        assert first.message.x == 1
        del result  # drop the generator -> GeneratorExit closes the source
        import gc

        gc.collect()
        assert seen == []  # the fault after the break never fired
        assert source.closed


class TestRouteErrorsGuard:
    def test_errors_raises_distinct_message_under_route(self) -> None:
        registry, a_cls = _registry_and_class("s")
        seen, sink = _sink()
        src = [("s", _TRUNCATED), ("s", a_cls(x=1).SerializeToString())]
        result = scan(iter(src), registry, on_error="route", error_sink=sink)
        list(result)  # run to completion
        # .errors under route never returns () -> it raises, and the message is
        # distinct from the pre-exhaustion guard's "only after ... exhausted".
        with pytest.raises(RuntimeError, match="route") as exc:
            _ = result.errors
        assert "error_sink" in str(exc.value)
        assert "exhausted" not in str(exc.value)
        assert len(seen) == 1  # the fault did go to the sink


class TestRouteSinkValidation:
    def test_route_without_sink_raises_eagerly(self) -> None:
        registry, _a_cls = _registry_and_class("s")
        with pytest.raises(ValueError, match="error_sink"):
            scan(iter([]), registry, on_error="route")

    @pytest.mark.parametrize("mode", ["raise", "skip", "collect"])
    def test_sink_with_non_route_mode_raises_eagerly(self, mode: OnError) -> None:
        registry, _a_cls = _registry_and_class("s")
        _seen, sink = _sink()
        with pytest.raises(ValueError, match="error_sink"):
            scan(iter([]), registry, on_error=mode, error_sink=sink)

    def test_scanresult_constructor_validates_route_sink(self) -> None:
        registry, _a_cls = _registry_and_class("s")
        with pytest.raises(ValueError, match="error_sink"):
            ScanResult(iter([]), registry, None, "route")


class TestOnErrorRatchet:
    def test_on_error_literal_has_exactly_four_values(self) -> None:
        # Forces a deliberate review when the value set changes (a new value is
        # non-breaking; removing/re-meaning one is not).
        assert set(typing.get_args(OnError)) == {"raise", "skip", "collect", "route"}
        assert len(typing.get_args(OnError)) == 4
