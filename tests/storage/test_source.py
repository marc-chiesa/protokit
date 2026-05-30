"""Tests for ``protokit.storage.source`` — the adapter ``Source`` protocol and
the ``StorageError`` / ``FrameError`` exception base.

These pin the two load-bearing facts about ``Source``: a plain generator
satisfies it (so users need not subclass anything), and ``isinstance`` is a
presence check only — every iterable passes, which is why the engine, not
``isinstance``, is the real guard (asserted in ``test_engine``). ``FrameError``
assertions check the *stored attributes*, not just message substrings, so a
later refactor of the message string cannot silently weaken correlation.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from protokit.storage.source import FrameError, Source, StorageError


class TestSourceProtocol:
    def test_plain_generator_satisfies_source(self) -> None:
        def gen() -> Iterator[tuple[str, bytes]]:
            yield ("s", b"\x08\x07")

        assert isinstance(gen(), Source)

    def test_class_with_iter_and_close_satisfies_source(self) -> None:
        class Handle:
            def __iter__(self) -> Iterator[tuple[str, bytes]]:
                yield ("s", b"")

            def close(self) -> None:  # pragma: no cover - presence only
                ...

        assert isinstance(Handle(), Source)

    def test_object_without_iter_is_not_a_source(self) -> None:
        class NotIterable:
            def close(self) -> None:  # pragma: no cover - presence only
                ...

        assert not isinstance(NotIterable(), Source)

    def test_isinstance_is_presence_only_not_a_correctness_gate(self) -> None:
        # Documented caveat (KD-1 / R3): every iterable passes the __iter__
        # presence check, so isinstance is NEVER relied on for record-shape
        # protection — the engine's per-record element guard is.
        assert isinstance([], Source)
        assert isinstance("", Source)
        assert isinstance({}, Source)


class TestFrameError:
    def test_stores_all_attributes_and_renders_reason(self) -> None:
        exc = FrameError("ch_a", 7, 42, "truncated varint")
        assert exc.stream_id == "ch_a"
        assert exc.record_index == 7
        assert exc.offset == 42
        assert exc.reason == "truncated varint"
        rendered = str(exc)
        assert "truncated varint" in rendered
        assert "ch_a" in rendered
        assert "42" in rendered

    def test_is_a_storage_error_and_exception(self) -> None:
        exc = FrameError("s", 0, None, "boom")
        assert isinstance(exc, StorageError)
        assert isinstance(exc, Exception)

    def test_none_offset_renders_cleanly(self) -> None:
        # A non-positional fault (unknown stream, malformed item) carries
        # offset=None and must still render without a stray "None" offset.
        exc = FrameError("ch_a", 3, None, "unknown stream_id")
        assert exc.offset is None
        rendered = str(exc)
        assert "unknown stream_id" in rendered
        assert "offset unknown" in rendered

    def test_storage_error_is_an_exception(self) -> None:
        assert issubclass(StorageError, Exception)
        assert not issubclass(StorageError, FrameError)

    def test_frame_error_can_be_raised_and_caught_as_storage_error(self) -> None:
        with pytest.raises(StorageError) as caught:
            raise FrameError("s", 1, 0, "boom")
        assert isinstance(caught.value, FrameError)
