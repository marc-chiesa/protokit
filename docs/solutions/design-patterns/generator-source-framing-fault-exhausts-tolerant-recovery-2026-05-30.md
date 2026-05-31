---
title: "A generator Source that raises a framing fault exhausts itself, so tolerant on_error modes can't recover past it"
date: 2026-05-30
category: design-patterns
module: protokit.storage
problem_type: design_pattern
component: service_object
severity: medium
applies_when:
  - "Designing or extending tolerant per-record error modes (skip/collect/route, or a CLI skip/warn) over an iterable/generator source"
  - "A source signals per-record faults by raising from its own __iter__ rather than yielding them as data"
  - "Recovery silently differs by fault origin: an engine-raised decode/unknown-stream fault continues while a source-raised framing fault ends the scan"
  - "A CLI or API exits success (exit 0) after a tolerant run even though every record past a fault was dropped"
tags:
  - tolerant-iteration
  - generator-exhaustion
  - on-error
  - iterator-lifecycle
  - framing-fault
  - silent-partial-results
  - resync-reader
  - protokit-storage
---

# A generator Source that raises a framing fault exhausts itself, so tolerant on_error modes can't recover past it

## Context

`protokit.storage.scan(source, registry, *, on_error=...)` offers tolerant error
modes — `skip`, `collect`, and `route` (the CLI's `warn`) — that dispatch a
per-record `FrameError` and keep going, so one bad record never aborts the whole
feed. The natural reading of "skip bad records and continue" is that the scan
recovers from *any* bad record. It does not, and the gap is invisible if you
only test the obvious case.

A `Source` is just an iterable, and the reference adapter `length_delimited`
(`src/protokit/storage/sources/length_delimited.py`) is a **generator** that
signals a *framing* fault (truncated length prefix, truncated body, or a declared
length over `max_frame_size`) by **raising** `FrameError` from inside its own
iteration. Raising out of a generator terminates it permanently. So when a
framing fault occurs mid-file, the engine *does* dispatch the fault through
`on_error` — but the source is now dead, the next pull yields `StopIteration`,
and the scan simply ends, silently dropping every record after the fault. The
CLI still exits 0.

The asymmetry was caught only because PR1.5's review constructed a file with a
good record *after* the framing fault. A test where the source raises at the very
end (PR1's `_FramingFaultSource`) verifies the fault is dropped/captured but never
exposes the lost tail.

## Guidance

When a tolerant iteration loop consumes a generator source that signals faults by
**raising**, recovery is bounded by whether the *source* is still alive after the
raise — not by whether the engine handled the fault. Both happen; only one lets
the scan continue:

- A fault the **engine** raises mid-loop (a protobuf `DecodeError` wrapped into
  `FrameError`, an `unknown stream_id`, a malformed-item shape) leaves the
  source's iterator intact. The engine drops/collects/routes it and the next
  `next()` keeps producing. **Recoverable — the scan continues.**
- A fault the **source's own `__iter__`** raises (a `length_delimited` framing
  fault) is *also* dispatched through `on_error` (skip drops it, collect captures
  it with its offset, route delivers it to the sink) — **but the generator is
  exhausted by the raise**. The engine's `continue` lands on a dead generator, so
  the next `next(iterator)` raises `StopIteration` and the scan ends.
  **Handled, but not recoverable past — the scan stops.**

The engine loop makes the lifecycle load-bearing (`engine.py`, `_iterate`):

```python
try:
    item = next(iterator)
except StopIteration:
    return
except FrameError as framing_error:
    self._dispatch(framing_error)   # skip / collect / route, then...
    continue                        # ...next pass hits a DEAD generator -> StopIteration -> return
```

The right response is **honesty plus design, not a patch**: do not advertise that
tolerant modes recover from all faults. To make source-origin faults genuinely
recoverable, the *source contract* must change — the source has to **keep
yielding after a fault (resync to the next frame boundary) instead of
raise-and-die**. That is a different source, not a change to `on_error`. Until
such a source exists, scope the guarantee in docs and pin both behaviors with
tests.

## Why This Matters

The failure mode is **silent data loss with a success exit code**. Under
`skip`/`warn`, a single mid-file framing corruption truncates the output there
and the process exits 0 — an operator sees a clean run and a partial result
indistinguishable from a complete one. That is exactly the silent-partial-results
risk the rest of the engine is built to forbid (the fail-loud `raise` default,
the loud `.errors` guard). A tolerant mode that *oversells* its guarantee is worse
than one honestly scoped, because callers make retention/audit decisions on "we
scanned the whole file." Naming the boundary and pinning it with a paired test
means no future refactor can quietly turn "framing faults stop the scan" into an
unstated regression, and the deferral (a resync-capable framing reader) is a known
follow-up rather than a hidden bug.

## When to Apply

- Designing or extending any tolerant per-record loop (`skip`/`continue-on-error`/
  `collect`/`route`) over an iterable or generator source.
- Writing a `Source` (or any producer): decide deliberately whether a per-record
  fault **raises** (terminal for a generator) or is **yielded as data while the
  producer resyncs** (recoverable).
- Reviewing a "skip-bad-and-continue" loop: ask *who raises each fault* — the loop
  body (consumer) or the iterator's `__next__` (producer) — and whether the
  iterator survives the raise. A generator never does.
- Writing the docstring/help for a tolerant mode: scope the guarantee to
  consumer-origin faults unless the source contract guarantees resync.

## Examples

**Misleading — masks the asymmetry.** A single test with only a *decode* fault
"proves" tolerance but says nothing about framing, because a decode fault is
raised by the engine and leaves the source alive:

```python
data = [good(x=7), _DECODE_BAD, good(x=9)]
# scan --on-error skip  ->  both goods survive. Passes regardless of generator death.
```

**Corrected — pins both paths** (`tests/storage/cli/test_on_error.py`):

```python
# (a) DECODE fault: engine-raised, source untouched -> recovers; the good AFTER it emerges.
def test_skip_recovers_past_decode_faults(...):
    data = [good(x=7), _DECODE_BAD, good(x=9)]
    assert result.output.count("# stream=") == 2          # both goods survive

# (b) FRAMING fault: oversized declared length raised by the generator -> scan STOPS.
def test_warn_framing_fault_stops_the_scan(...):
    raw = delimited(good(x=7)) + encode_varint(10**9) + delimited(good(x=9))
    assert result.exit_code == 0                           # exits 0 — the trap
    assert result.output.count("# stream=") == 1           # only good1; good2 is LOST
```

The engine-level twin (`tests/storage/test_engine.py::TestSourceRaisedFrameError`)
drives a **real raising generator** (`_FramingFaultSource`, never a mock) to pin
that `raise` propagates, `skip` drops the fault, and `collect` captures it *with
its byte offset* — establishing the handling. The CLI test above adds the record
*after* the fault to expose the lost tail. Together they make the asymmetry a
tested contract.

The limit is documented at the surfaces it reaches, not papered over: the
`cli.py` module docstring states the framing-vs-decode recovery limit, and the
`_iterate` comment notes "a generator source is finished after raising, so the
next loop pass ends the scan; a resilient source may keep yielding." A
resync-capable framing reader is named as the deferred follow-up that would make
framing faults recoverable.

## Related

- [[tolerant-iteration-error-taxonomy-narrow-catch-loud-completion-guard-2026-05-30]]
  — the engine-side angle (the narrow typed catch, `BaseException` always
  propagates, the loud `.errors` completion-state guard). This doc is the
  source-iteration-lifecycle companion: that catch taxonomy keeps its
  no-silent-partial guarantee only while the source survives to keep yielding.
- [[released-memoryview-mergefromstring-segfault-bypasses-on-error-2026-05-30]] —
  a different bypass of the fail-loud contract (an uncatchable signal vs. a
  generator exhausting itself).
- [[runtime-checkable-protocol-isinstance-is-presence-only-not-correctness-2026-05-30]]
  — the upstream `Source`/element-shape contract this builds on.
- Shipped in PR #11 (storage PR1.5); the recovery limit is also stated in the
  CHANGELOG `## Unreleased` storage CLI entry.
