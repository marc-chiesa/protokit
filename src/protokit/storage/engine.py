"""The scan engine: route each record to its stream's isolated pool, parse it
inside a confined step, filter, and yield a tagged ``ScanRecord``.

This module carries the plan's single highest-risk decision — the ``on_error``
exception taxonomy — so the safety properties are pinned in code, not left
implicit:

- **Parse-confinement (D5).** The raw record bytes (possibly a ``memoryview``
  over a caller-owned buffer) are handed straight to ``MergeFromString`` and
  never stored on the yielded message. upb copies into its arena during the
  parse, so the caller may free or overwrite the buffer the instant a record is
  consumed; the engine relies on that arena copy rather than making a defensive
  copy of its own (zero-copy frame handoff). The view is local to one loop
  iteration and never escapes.
- **Fail-loud default (D15).** ``on_error='raise'`` propagates the first
  ``FrameError``; ``skip`` / ``collect`` are opt-in and never produce silent
  partial results.
- **Narrow, typed catch (KD-3).** Only ``FrameError`` (the engine's own
  per-record faults) and protobuf ``DecodeError`` (wrapped into one) are subject
  to ``on_error``. ``BaseException`` (``SystemExit`` / ``KeyboardInterrupt`` /
  ``GeneratorExit``) **always** propagates, and a **predicate exception always
  propagates** — a predicate bug is programmer error, not a corrupt-data
  condition.
- **Loud ``.errors`` guard (KD-3 / R6).** Reading ``ScanResult.errors`` before
  the iterator is exhausted raises ``RuntimeError`` rather than returning a
  silent partial tuple.

Public surface:

- ``scan`` — build a ``ScanResult`` over a ``Source`` + ``StreamRegistry``.
- ``ScanRecord`` — a yielded ``(stream_id, record_index, message)`` triple.
- ``ScanResult`` — the iterable result, plus ``.errors`` for ``collect`` mode.
- ``OnError`` — the ``Literal['raise', 'skip', 'collect']`` policy type.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Literal

from google.protobuf.message import DecodeError, Message

from protokit.storage.registry import StreamRegistry
from protokit.storage.source import FrameError, Source

OnError = Literal["raise", "skip", "collect"]

_VALID_ON_ERROR: tuple[OnError, ...] = ("raise", "skip", "collect")

# ScanResult lifecycle. The states gate the .errors loud guard: errors are
# readable only once the scan has reached a terminal state (exhausted or a
# propagated fault), never while still running or after an early close.
_READY = "ready"
_RUNNING = "running"
_EXHAUSTED = "exhausted"


@dataclass(frozen=True)
class ScanRecord:
    """One materialized record produced by :func:`scan`.

    Attributes:
        stream_id: The stream the record was routed to — carried on the output
            so cross-channel correlation is expressible (correlate by
            ``stream_id`` plus a domain key, never by ``record_index``).
        record_index: The record's global feed position (a single
            monotonically-ascending counter over every item the ``Source``
            yields, regardless of stream). A debug/correlation handle.
        message: The fully-parsed protobuf message. It owns its data (upb arena
            copy); the source's record buffer may be freed once this record is
            consumed.
    """

    stream_id: str
    record_index: int
    message: Message


def scan(
    source: Source,
    registry: StreamRegistry,
    *,
    predicate: Callable[[Message], bool] | None = None,
    on_error: OnError = "raise",
) -> ScanResult:
    """Scan ``source``, routing each record through ``registry`` and yielding
    the matching, materialized records.

    Args:
        source: Yields ``(stream_id, record_bytes)`` pairs (see
            :class:`~protokit.storage.source.Source`).
        registry: Maps each ``stream_id`` to its isolated pool + message class.
        predicate: Optional ``(message) -> bool`` filter applied to the
            fully-parsed message; only ``True`` records are yielded. A predicate
            that raises propagates (it is programmer error, not a data fault).
        on_error: ``'raise'`` (default) propagates the first ``FrameError``;
            ``'skip'`` drops faulting records; ``'collect'`` drops them but
            records each in :attr:`ScanResult.errors`.

    Returns:
        A :class:`ScanResult` — iterate it for :class:`ScanRecord`s. Argument
        validation is eager (this call raises ``ValueError`` for a bad
        ``on_error`` before any record is read).

    Raises:
        ValueError: ``on_error`` is not one of ``'raise'``, ``'skip'``,
            ``'collect'``.
    """
    if on_error not in _VALID_ON_ERROR:
        raise ValueError(
            f"on_error must be one of {_VALID_ON_ERROR!r}, got {on_error!r}"
        )
    return ScanResult(source, registry, predicate, on_error)


class ScanResult:
    """Iterable result of a :func:`scan`, plus the ``collect``-mode error report.

    A wrapper (not a bare generator) for two reasons: a generator object cannot
    carry a ``.errors`` attribute, and a wrapper lets ``scan`` validate
    arguments eagerly at call time rather than deferring to the first ``next()``.
    Iterate it once; ``.errors`` is readable only after the iterator is
    exhausted.
    """

    def __init__(
        self,
        source: Source,
        registry: StreamRegistry,
        predicate: Callable[[Message], bool] | None,
        on_error: OnError,
    ) -> None:
        self._source = source
        self._registry = registry
        self._predicate = predicate
        self._on_error = on_error
        self._errors: list[FrameError] = []
        self._state = _READY

    def __iter__(self) -> Iterator[ScanRecord]:
        if self._state != _READY:
            raise RuntimeError(
                "a ScanResult may be iterated only once; call scan() again to "
                "re-run"
            )
        self._state = _RUNNING
        return self._run()

    @property
    def errors(self) -> tuple[FrameError, ...]:
        """The ``FrameError``s captured under ``on_error='collect'``.

        Raises:
            RuntimeError: read before the scan iterator is exhausted — iterate
                to completion (or call ``list(result)``) first. A silent partial
                tuple would be exactly the R2 silent-partial-results risk that
                fail-loud forbids.
        """
        if self._state != _EXHAUSTED:
            raise RuntimeError(
                "read ScanResult.errors only after the scan iterator is "
                "exhausted (iterate to completion or call list(result) first)"
            )
        return tuple(self._errors)

    def _run(self) -> Iterator[ScanRecord]:
        """Drive the record loop with source cleanup and terminal-state marking.

        Cleanup (KD-1): the source is closed on every exit — preferring the
        context-manager protocol, else ``close()`` — including a mid-iteration
        exception. ``_state`` advances to ``_EXHAUSTED`` on natural completion or
        a propagating fault, but **not** on an early ``GeneratorExit`` (a
        ``break`` + GC, or explicit ``close()``), so the ``.errors`` guard stays
        active when the scan did not actually run to completion.
        """
        source = self._source
        try:
            if _supports_context_manager(source):
                with source:  # type: ignore[attr-defined]
                    yield from self._iterate(source)
            elif callable(getattr(source, "close", None)):
                try:
                    yield from self._iterate(source)
                finally:
                    source.close()  # type: ignore[attr-defined]
            else:
                yield from self._iterate(source)
        except GeneratorExit:
            # Closed before exhaustion — not a terminal state; keep the guard on.
            raise
        except BaseException:
            # A propagated fault (raise-mode FrameError, predicate bug, or a
            # BaseException) ends the scan: errors are now readable.
            self._state = _EXHAUSTED
            raise
        else:
            self._state = _EXHAUSTED

    def _iterate(self, source: Source) -> Iterator[ScanRecord]:
        registry = self._registry
        predicate = self._predicate
        record_index = -1
        for item in source:
            record_index += 1

            # Per-record element guard (runs every record — a malformed item may
            # appear at any index). Converts a bad shape into a FrameError rather
            # than leaking a raw ValueError/TypeError.
            try:
                stream_id, raw = _as_record(item, record_index)
            except FrameError as malformed:
                self._dispatch(malformed)
                continue

            resolved = registry.get(stream_id)
            if resolved is None:
                self._dispatch(
                    FrameError(stream_id, record_index, None, "unknown stream_id")
                )
                continue

            # Parse-confined step (D5): hand the raw view straight to upb, which
            # copies into its arena. `raw` is never stored or yielded.
            message = resolved.message_class()
            try:
                message.MergeFromString(raw)
            except DecodeError as exc:
                self._dispatch(
                    FrameError(
                        stream_id,
                        record_index,
                        None,
                        str(exc) or "protobuf decode error",
                    )
                )
                continue

            # `raw` is not referenced beyond this point. A predicate exception
            # propagates (it is not a corrupt-data condition).
            if predicate is None or predicate(message):
                yield ScanRecord(stream_id, record_index, message)

    def _dispatch(self, error: FrameError) -> None:
        """Apply the ``on_error`` policy to a per-record ``FrameError``.

        Returns normally (the caller then ``continue``s to the next record) for
        ``skip`` / ``collect``; ``raise`` re-raises the error so it propagates.
        """
        if self._on_error == "raise":
            raise error
        if self._on_error == "collect":
            self._errors.append(error)
        # 'skip': drop the record and continue.


def _supports_context_manager(source: object) -> bool:
    return hasattr(source, "__enter__") and hasattr(source, "__exit__")


def _as_record(
    item: object, record_index: int
) -> tuple[str, bytes | memoryview]:
    """Validate a yielded item is a ``(str, bytes | memoryview)`` 2-tuple.

    Raises:
        FrameError: the item is not the expected shape. Its ``stream_id`` field
            carries a truncated ``repr`` of the offending item (there is no
            usable tag) and ``offset`` is ``None``.
    """
    if (
        isinstance(item, tuple)
        and len(item) == 2
        and isinstance(item[0], str)
        and isinstance(item[1], (bytes, memoryview))
    ):
        return item[0], item[1]
    raise FrameError(
        repr(item)[:80],
        record_index,
        None,
        "source yielded a malformed record (expected a "
        "(stream_id, record_bytes) 2-tuple)",
    )
