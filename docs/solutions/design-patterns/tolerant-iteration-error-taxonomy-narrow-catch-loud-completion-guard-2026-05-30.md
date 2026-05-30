---
title: "Tolerant-iteration error taxonomy: narrow typed catch + loud completion-state guard"
date: 2026-05-30
category: design-patterns
module: protokit.storage
problem_type: design_pattern
component: service_object
severity: medium
applies_when:
  - "Building a tolerant-iteration / fail-loud-with-collect engine that iterates records over untrusted or external data"
  - "An engine offers skip/collect tolerant modes alongside a fail-loud raise default"
  - "A collected errors report (e.g. ScanResult.errors) is exposed and must never be read as a silent partial"
  - "The iteration runs inside a try/finally that also tears down a source (close() / __exit__) which can itself raise or suppress"
  - "User-supplied callbacks (predicates, filters) run inside the per-record loop"
tags:
  - tolerant-iteration
  - fail-loud
  - exception-taxonomy
  - baseexception
  - silent-partial-results
  - completion-state-machine
  - generatorexit
  - protokit-storage
---

# Tolerant-iteration error taxonomy: narrow typed catch + loud completion-state guard

## Context

`protokit.storage`'s scan engine (`src/protokit/storage/engine.py`) iterates
protobuf records over a `Source` that may carry untrusted or externally-produced
bytes. It offers an `on_error` policy with three modes: `raise` (fail-loud
default), `skip` (drop faulting records), and `collect` (drop them but record
each in `ScanResult.errors`). Any engine that mixes tolerant modes with a
fail-loud default over untrusted data must pin three things in code — never leave
them implicit — or it will silently swallow the highest-severity failure modes a
data-scanning tool can have:

1. **A narrow, typed catch** that distinguishes a corrupt-data condition from a
   cancellation signal or a programmer error.
2. **A loud errors-report guard** that refuses to hand back a partial report as
   if it were complete.
3. **A completion-state machine keyed on the record loop**, not on teardown, so a
   completed scan whose `close()` raises is not misfiled as an abort.

This doc is the reusable taxonomy distilled from that engine. It generalizes the
single-surface BaseException lessons in
[[keyboardinterrupt-baseexception-bypass-rule-pack-load-2026-05-07]] and
[[formatter-systemexit-exit-code-bypass-2026-04-19]] from "which sibling to
catch on one call" to "how to structure the whole tolerant-iteration loop."

## Guidance

### 1. Narrow, typed catch — corrupt data only

Catch only the narrow, typed fault set that actually represents a corrupt-record
condition. In the engine that set is exactly two types, with the protobuf
`DecodeError` wrapped into a `FrameError` at the parse step so the rest of the
loop only ever routes one type:

```python
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
```

Three classes of exception MUST escape `on_error` and propagate unconditionally:

- **`BaseException` (`KeyboardInterrupt` / `SystemExit` / `GeneratorExit`)** — a
  Ctrl-C or a `sys.exit()` is not a corrupt-data condition. A `skip`/`collect`
  policy that swallowed `KeyboardInterrupt` would turn an un-cancellable scan
  loose on a large corpus.
- **A predicate (user-callback) exception** — a predicate bug is *programmer
  error*, not corrupt data. The engine yields the parsed message past the
  `DecodeError` guard before calling the predicate precisely so the predicate
  runs outside any data-fault catch:

  ```python
  # `raw` is not referenced beyond this point. A predicate exception
  # propagates (it is not a corrupt-data condition).
  if predicate is None or predicate(message):
      yield ScanRecord(stream_id, record_index, message)
  ```

- **Anything not in the typed fault set.** A bare `except Exception` around the
  parse-or-yield is the anti-pattern: it swallows nothing useful that a typed
  catch doesn't already, and it hides genuine programming errors (a registry bug,
  a malformed message-class) as if they were bad input bytes.

`FrameError` from the source's own framing (e.g. a truncated length prefix) is
routed through `on_error` too — it is a per-record fault like any other and must
not bypass `skip`/`collect`:

```python
try:
    item = next(iterator)
except StopIteration:
    return
except FrameError as framing_error:
    self._dispatch(framing_error)
    continue
```

### 2. Loud errors-report guard — never a silent partial

In `collect` mode the errors report must `raise RuntimeError` if read before the
scan completes — never return a silent partial tuple that "looks complete but
isn't." That partial is exactly the silent-partial-results risk fail-loud exists
to forbid:

```python
@property
def errors(self) -> tuple[FrameError, ...]:
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
```

### 3. Completion-state machine keyed on the RECORD LOOP, not teardown

Distinguish four terminal-ish states and gate `.errors` on them:

- `_EXHAUSTED` — the record loop ran to completion; `.errors` is readable.
- `_ABORTED` — a propagating fault aborted the loop mid-flight; `.errors`
  withheld.
- `_RUNNING` (early close) — a `GeneratorExit` from `break` + GC, or an explicit
  `close()`, before exhaustion; stays `_RUNNING`, `.errors` withheld.
- `_READY` — never iterated.

The subtle trap (a regression caught in re-review): if the terminal state is
decided by whether the *whole `try/finally`* — including source teardown —
succeeded, then a COMPLETED scan whose `close()` / `__exit__` *then* raises lands
in the abort branch and wrongly withholds a COMPLETE report. The fix is to set a
`completed` flag the instant the record loop returns and decide the terminal
state by `completed`, in BOTH the `except` and `else` arms:

```python
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
    # fault that aborted the loop is _ABORTED (report withheld).
    self._state = _EXHAUSTED if completed else _ABORTED
    raise
else:
    # No exception propagated. If the loop nonetheless did not complete,
    # a context manager's __exit__ suppressed an in-flight fault — that
    # is a partial scan, so withhold the report.
    self._state = _EXHAUSTED if completed else _ABORTED
```

Two corollaries fall out of keying on the loop:

- A **completed** scan whose teardown raises is still `_EXHAUSTED` — the report
  is complete; the teardown error propagates to the caller *separately*.
- A context manager whose `__exit__` **suppresses** an in-flight fault means the
  loop did NOT reach `completed = True`, so the `else` arm correctly files it as
  `_ABORTED` and withholds the partial. The `completed` flag is the single source
  of truth that distinguishes these from each other.

`GeneratorExit` gets its own arm that re-raises without touching `_state`,
leaving the result `_RUNNING` so an early-closed iterator never exposes a partial
`.errors`.

## Why This Matters

For a data-scanning tool, the three failure modes this taxonomy closes are worse
than a crash — because they are *invisible*:

- **Silent partial results on a corpus scan.** A `.errors` tuple that looks
  complete but reflects an aborted run leads a caller to conclude "N errors,
  done" when the real answer is "unknown — the scan never finished." The loud
  guard converts that into a `RuntimeError` the caller cannot miss.
- **Swallowed Ctrl-C.** A `skip`/`collect` loop that caught `BaseException` would
  ignore the operator's cancel and keep grinding through untrusted input.
- **Hidden programming errors.** A bare `except Exception` around the parse/yield
  would mis-attribute a registry or predicate bug as "bad input bytes,"
  collecting it as a data fault instead of surfacing it.

The teardown trap is the highest-leverage subtlety here: it is invisible in the
common case (teardown usually succeeds) and only bites when `close()` raises on a
fully-completed scan — at which point the naive design silently withholds a
report that was, in fact, complete.

**Drive every fault path in tests with REAL bytes and real raising callables.**
Never `mock.patch` the C-extension parse method (e.g. `MergeFromString`) to
simulate a `DecodeError` — patching a protobuf-python C-extension method silently
no-ops and produces a false green, exactly as documented in
[[mock-patch-c-extension-method-descriptor-2026-05-06]]. Feed the engine genuinely
malformed bytes, a source whose `__exit__` raises, a source whose `__exit__`
suppresses, a predicate that raises, and a `KeyboardInterrupt` mid-iteration —
each must drive its own state branch with real machinery.

## When to Apply

- Any tolerant-iteration / fail-loud-with-collect engine over untrusted or
  external data — record scanners, log parsers, batch importers, stream
  demultiplexers.
- Any iterator wrapper that exposes a post-hoc report (`.errors`, `.skipped`,
  `.warnings`) whose completeness depends on the iteration having finished.
- Any loop wrapped in `try/finally` source teardown where `close()` / `__exit__`
  can itself raise or suppress, and the terminal state must not conflate
  "loop finished" with "teardown finished."
- Any loop that invokes user-supplied callbacks (predicates, transforms) — keep
  them outside the data-fault catch so a callback bug propagates as programmer
  error.

## Examples

**The taxonomy table the engine pins (from `engine.py`'s module docstring):**

| Source of exception | Treatment | Why |
| --- | --- | --- |
| `FrameError` (framing or wrapped `DecodeError`) | routed through `on_error` | a per-record corrupt-data fault |
| `KeyboardInterrupt` / `SystemExit` / `GeneratorExit` | always propagates | cancellation / teardown, not corrupt data |
| predicate (user-callback) exception | always propagates | programmer error, not corrupt data |
| any other `Exception` | propagates (no broad catch) | a programming error must not masquerade as bad input |

**State → `.errors` behavior:**

```text
_READY      -> RuntimeError ("iterate to completion ... first")  (never started)
_RUNNING    -> RuntimeError                                       (mid-flight / early GeneratorExit close)
_ABORTED    -> RuntimeError ("partial report ... withheld")       (fault aborted the loop, OR __exit__ suppressed an in-flight fault)
_EXHAUSTED  -> tuple(self._errors)                                (loop completed; readable even if teardown then raised)
```

**Source of truth:**

- `src/protokit/storage/engine.py` — `ScanResult._run` (the `completed`-flag
  state machine), `ScanResult.errors` (the loud guard), `ScanResult._iterate`
  (the narrow typed catch and predicate-outside-catch placement), and the module
  docstring's four pinned safety properties.

## Related

- [[keyboardinterrupt-baseexception-bypass-rule-pack-load-2026-05-07]] — the
  single-call BaseException-sibling lesson this loop-level taxonomy generalizes:
  `except Exception` does not catch `KeyboardInterrupt` / `SystemExit` /
  `GeneratorExit`. Here the conclusion is the inverse-by-design: those siblings
  must *not* be caught at all — they propagate past `on_error`.
- [[formatter-systemexit-exit-code-bypass-2026-04-19]] — the per-surface judgment
  that `SystemExit` from delegated code must not silently set the exit code; the
  same "decide each BaseException sibling explicitly, per surface" discipline
  drives the narrow-catch rule above.
- [[no-raise-contract-extends-to-post-init-failures-2026-05-14]] — the
  complementary failure-routing discipline for *no-raise* contracts; this doc
  covers the dual case where a tolerant engine must let specific faults raise
  rather than absorb them, and a partial collected report must be withheld loudly.
- [[mock-patch-c-extension-method-descriptor-2026-05-06]] — why every fault path
  here must be driven by real bytes / real raising callables: patching a
  protobuf-python C-extension method silently no-ops and yields a false green.
