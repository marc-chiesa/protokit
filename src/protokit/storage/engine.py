"""The scan engine: route each record to its stream's isolated pool, parse it
inside a confined step, filter, and yield a tagged ``ScanRecord``.

This module carries the plan's single highest-risk decision — the ``on_error``
exception taxonomy — so the safety properties are pinned in code, not left
implicit:

- **Parse-confinement (D5).** The raw record bytes (possibly a ``memoryview``
  over a caller-owned buffer) are materialized with ``bytes(raw)`` and parsed
  inside one loop iteration; the view is never stored on the yielded message.
  ``bytes(raw)`` is a no-op for a ``bytes`` input and a single copy for a
  ``memoryview``, and upb copies again into its arena during the parse, so the
  caller may free or overwrite the buffer the instant a record is consumed. The
  defensive copy is also a safety boundary: an invalid or already-released
  ``memoryview`` raises a catchable ``ValueError`` here (which propagates
  fail-loud) instead of letting upb dereference freed memory and crash the
  whole process.
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
- ``OnError`` — the ``Literal['raise', 'skip', 'collect', 'route']`` policy type.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Literal

from google.protobuf.message import DecodeError, Message

from protokit.storage.registry import StreamRegistry
from protokit.storage.source import FrameError, Source

OnError = Literal["raise", "skip", "collect", "route"]

_VALID_ON_ERROR: tuple[OnError, ...] = ("raise", "skip", "collect", "route")

# ScanResult lifecycle. The states gate the .errors loud guard: errors are
# readable ONLY after the scan ran to completion (_EXHAUSTED). They are withheld
# while still running, after an early close (_RUNNING stays set on GeneratorExit),
# and after a propagated fault aborted the scan (_ABORTED) — in those cases the
# collected report is partial, and returning it silently is the very
# silent-partial the loud guard forbids.
_READY = "ready"
_RUNNING = "running"
_EXHAUSTED = "exhausted"
_ABORTED = "aborted"


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
    error_sink: Callable[[FrameError], None] | None = None,
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
            records each in :attr:`ScanResult.errors`; ``'route'`` delivers each
            ``FrameError`` live to ``error_sink`` and continues.
        error_sink: ``(FrameError) -> None`` callback invoked once per fault
            under ``on_error='route'``, before the scan continues. **Required by
            and exclusive to** ``'route'``: passing it with any other mode, or
            omitting it under ``'route'``, raises ``ValueError`` at call entry. A
            raising ``error_sink`` propagates (a sink bug is caller code, like a
            predicate bug — not absorbed). Under ``'route'`` faults are not
            collected, so :attr:`ScanResult.errors` raises.

    Returns:
        A :class:`ScanResult` — iterate it for :class:`ScanRecord`s. Argument
        validation is eager (this call raises ``ValueError`` for a bad
        ``on_error`` or a route/sink mismatch before any record is read).

    Raises:
        ValueError: ``on_error`` is not one of ``'raise'``, ``'skip'``,
            ``'collect'``, ``'route'``; or the route/``error_sink`` pairing is
            violated.
    """
    # Validation is eager and lives in ScanResult.__init__ (so the exported
    # ScanResult constructor enforces it too); constructing here runs it now.
    return ScanResult(source, registry, predicate, on_error, error_sink=error_sink)


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
        *,
        error_sink: Callable[[FrameError], None] | None = None,
    ) -> None:
        if on_error not in _VALID_ON_ERROR:
            raise ValueError(
                f"on_error must be one of {_VALID_ON_ERROR!r}, got {on_error!r}"
            )
        # route <-> error_sink are mutually required-and-exclusive. Eager so a
        # misuse fails at the call site, not mid-scan. `error_sink` is keyword-
        # only so the public positional constructor contract is unchanged.
        if on_error == "route" and error_sink is None:
            raise ValueError("on_error='route' requires an error_sink")
        if on_error != "route" and error_sink is not None:
            raise ValueError("error_sink is only valid with on_error='route'")
        self._source = source
        self._registry = registry
        self._predicate = predicate
        self._on_error = on_error
        self._error_sink = error_sink
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
            RuntimeError: under ``on_error='route'`` (faults stream to
                ``error_sink``, nothing is collected — a silent ``()`` here would
                be indistinguishable from "zero faults"); or read before the scan
                ran to completion — either still mid-iteration / not yet started
                (iterate to completion or call ``list(result)`` first), or aborted
                by a propagating exception (the report is partial and withheld). A
                silent partial tuple would be exactly the R2 silent-partial-results
                risk that fail-loud forbids.
        """
        if self._on_error == "route":
            # route never populates _errors; returning () would read as "zero
            # faults" even when the sink saw many. Raise, with a message distinct
            # from the pre-exhaustion guard so the two are test-distinguishable.
            raise RuntimeError(
                "on_error='route' streams faults to error_sink; "
                ".errors is not collected"
            )
        if self._state == _ABORTED:
            raise RuntimeError(
                "the scan was aborted by a propagating exception before "
                "completion; ScanResult.errors is a partial report and is "
                "withheld"
            )
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
        exception.

        The terminal state is decided by whether the *record loop* completed
        (the ``completed`` flag, set the instant ``_iterate`` returns), NOT by
        whether teardown then succeeded:

        - loop completed → ``_EXHAUSTED`` (``.errors`` readable), even if
          ``close()`` / ``__exit__`` then raises (that error still propagates to
          the caller — the report is simply complete);
        - loop aborted mid-flight (a fault, or a ``with`` whose ``__exit__``
          suppressed the fault) → ``_ABORTED`` (``.errors`` withheld);
        - early ``GeneratorExit`` (``break`` + GC, or explicit ``close()``)
          leaves ``_RUNNING``.

        In every non-completion case the ``.errors`` guard stays active so a
        partial report is never returned as if complete.
        """
        source = self._source
        completed = False
        try:
            if _supports_context_manager(source):
                with source:  # type: ignore[attr-defined]
                    yield from self._iterate(source)
                    completed = True
            elif callable(getattr(source, "close", None)):
                try:
                    yield from self._iterate(source)
                    completed = True
                finally:
                    source.close()  # type: ignore[attr-defined]
            else:
                yield from self._iterate(source)
                completed = True
        except GeneratorExit:
            # Closed before exhaustion — not a terminal state; keep the guard on.
            raise
        except BaseException:
            # The record loop's outcome decides the state, not teardown: a
            # completed loop whose close()/__exit__ then raised is still
            # _EXHAUSTED (report complete, teardown error still propagates); a
            # fault that aborted the loop is _ABORTED (report withheld). A
            # frozen-at-abort partial is exactly the silent partial the guard
            # forbids. (In raise mode .errors is empty anyway.)
            self._state = _EXHAUSTED if completed else _ABORTED
            raise
        else:
            # No exception propagated. If the loop nonetheless did not complete,
            # a context manager's __exit__ suppressed an in-flight fault — that
            # is a partial scan, so withhold the report.
            self._state = _EXHAUSTED if completed else _ABORTED

    def _iterate(self, source: Source) -> Iterator[ScanRecord]:
        registry = self._registry
        predicate = self._predicate
        iterator = iter(source)
        record_index = -1
        while True:
            record_index += 1

            # Pull the next record. A source may raise FrameError from its own
            # framing (e.g. a length_delimited truncated length prefix); that is
            # a per-record fault like any other, so route it through on_error
            # rather than letting it bypass skip/collect. For a single source
            # the source's record_index matches this global counter, so the
            # error is dispatched as-is (preserving its offset). A generator
            # source is finished after raising, so the next loop pass ends the
            # scan; a resilient source may keep yielding.
            try:
                item = next(iterator)
            except StopIteration:
                return
            except FrameError as framing_error:
                self._dispatch(framing_error)
                continue

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

            # Parse-confined step (D5): materialize with bytes(raw) — a no-op
            # for a bytes input, one safe copy for a memoryview — then parse.
            # `raw` is never stored or yielded. The bytes(raw) boundary turns an
            # invalid/released view into a catchable ValueError (which propagates
            # fail-loud) instead of a upb dereference-of-freed-memory crash.
            message = resolved.message_class()
            try:
                message.MergeFromString(bytes(raw))
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
        ``skip`` / ``collect`` / ``route``; ``raise`` re-raises the error so it
        propagates.
        """
        if self._on_error == "raise":
            raise error
        if self._on_error == "route":
            # Deliver live, OUTSIDE any catch: a raising sink propagates (a sink
            # bug is caller code, like a predicate bug), and route collects
            # nothing. error_sink is non-None here (validated at construction).
            assert self._error_sink is not None
            self._error_sink(error)
            return
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
    # The reporting path must not crash while describing the fault, so guard the
    # repr of a possibly-hostile item (a __repr__ that raises would otherwise
    # leak past on_error).
    try:
        tag = repr(item)[:80]
    except Exception:
        tag = f"<unreprable {type(item).__name__}>"
    raise FrameError(
        tag,
        record_index,
        None,
        "source yielded a malformed record (expected a "
        "(stream_id, record_bytes) 2-tuple)",
    )
