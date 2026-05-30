---
title: "Released memoryview handed to MergeFromString segfaults the process and bypasses the on_error contract"
date: 2026-05-30
category: security-issues
module: protokit.storage
problem_type: security_issue
component: service_object
severity: high
symptoms:
  - "A Source that yields a released/dangling memoryview (a C++/pybind11-owned buffer freed before the record is consumed) terminates the whole process with an uncatchable SIGSEGV (exit code 139)"
  - "The crash bypasses every on_error mode (raise/skip/collect) identically: no FrameError, no ScanResult.errors entry, no Python traceback"
  - "The fail-loud-but-confined guarantee is silently defeated — a process segfault is not a catchable Python exception, so on_error never runs"
  - "Happy-path unit tests stay green; only an adversarial review that specifically attacks the released-view case surfaces it"
root_cause: wrong_api
resolution_type: code_fix
related_components: [testing_framework, tooling]
tags:
  - memoryview
  - mergefromstring
  - segfault
  - upb
  - zero-copy
  - on-error
  - defensive-copy
  - protokit-storage
---

# Released memoryview handed to MergeFromString segfaults the process and bypasses the on_error contract

## Problem

`protokit.storage.scan` parses each record with protobuf
`MergeFromString`. The storage plan mandated a defensive `bytes(raw)`
copy at the parse step. During implementation that copy was dropped to
keep the `memoryview` path "zero-copy" — the engine parsed straight from
the yielded view (`message.MergeFromString(raw)`).

A `Source` yielding a **released or dangling** `memoryview` — a
*documented* use case, since the boundary explicitly accepts a
`memoryview` over a C++/pybind11-owned buffer (see
`src/protokit/storage/source.py`) — then handed that live view directly
to upb's `MergeFromString`. upb must dereference the buffer to copy it
into its arena, so it reads freed memory and the process dies with an
uncatchable `SIGSEGV` (exit code 139).

The crash bypasses the engine's entire `on_error` taxonomy. The module
docstring pins a deliberate guarantee: only `FrameError` and protobuf
`DecodeError` are subject to `on_error`, everything else fails loud — but
"fails loud" assumes a *catchable Python exception*. A segfault unwinds
nothing: no `FrameError`, no `ScanResult.errors` entry, no traceback, no
chance for `raise`/`skip`/`collect` to run. The fail-loud-but-confined
property the engine was built around is defeated.

## Symptoms

- A `Source` that yields a `.release()`'d (or otherwise freed)
  `memoryview` crashes the interpreter with `SIGSEGV` — the process exits
  139, mid-iteration.
- The crash is identical under all three `on_error` modes. `collect`
  mode produces no `ScanResult.errors` entry; `skip` does not skip it;
  `raise` raises nothing catchable.
- No Python traceback reaches the caller — the C-extension parser
  faulted before any Python-level `except` arm could engage.
- The vector is invisible to happy-path unit tests (which only ever
  feed live `bytes`/valid `memoryview`); it surfaces only under an
  adversarial review that deliberately constructs the released-view
  case.

## What Didn't Work

**Parsing directly from the yielded view.** The dropped-copy
implementation was:

```python
message = resolved.message_class()
message.MergeFromString(raw)  # raw may be a released memoryview
```

For a live `bytes` or valid `memoryview` this works. For a released
view it dereferences freed memory inside upb and the process dies.

**Relying on the upb arena copy alone.** The "zero-copy is safe because
upb copies anyway" reasoning is wrong about *ordering*: upb copies the
record into its arena *during* the parse, but it must **read** the source
buffer first to do so. An invalid buffer crashes during that read,
*before* any copy completes. The arena copy protects the *parsed
message's* lifetime (so the caller can free the buffer after a record is
consumed) — it does nothing to protect the *parse itself* from an
already-invalid input buffer.

## Solution

Materialize with `bytes(raw)` at the parse boundary, exactly as the plan
mandated (`src/protokit/storage/engine.py`):

```python
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
```

`bytes(raw)` is:

- a **no-op for a `bytes` input** — `bytes(b) is b` for a `bytes`
  object, so the common path adds nothing; and
- **one safe copy for a `memoryview`** — and, crucially, for a
  *released* view `bytes(released_mv)` raises a catchable
  `ValueError("operation forbidden on released memoryview object")` in
  pure Python, instead of dereferencing freed memory in C.

That `ValueError` then propagates **fail-loud in all modes**. It is a
**source-contract violation / programming error** (the `Source` handed
the engine a dead buffer), like a predicate bug — **not** a corrupt-data
condition. So it is deliberately *not* wrapped into `FrameError`: the
narrow `on_error` catch stays `{FrameError, DecodeError}` only, and the
`ValueError` flies straight past it to the caller, loud and uncaught,
which is the correct outcome for a contract violation.

## Why This Works

The "zero-copy" framing conflated two distinct handoffs:

1. **The source → engine handoff** — the `Source` yields a `memoryview`
   *without materializing bytes up front*. This copy is genuinely
   avoided: the caller never has to `bytes()` its buffer before yielding,
   and the engine never retains the live view. This is the real
   zero-copy win, and it stays.
2. **The parse step** — upb's arena copy is *unavoidable* (the message
   must own its data so the caller can free the buffer once a record is
   consumed). `bytes(raw)` adds **one** more copy for a `memoryview` and
   **zero** for `bytes`. Dropping it does not buy zero-copy parsing — upb
   copies regardless — it only removes the safety boundary.

So the defensive copy is **load-bearing safety, not a skippable
micro-optimization**. And this project deliberately de-prioritizes
throughput — it dropped its performance claim as an own-goal — so the
tradeoff is unambiguous: **safety > one copy.**

The deeper mechanism is *where the failure occurs*. Without `bytes()`, an
invalid buffer faults inside a C extension (upb), where Python's
exception machinery cannot intercept it — the result is a process-level
signal, not a language-level exception. `bytes(released_mv)` moves the
exact same "this buffer is dead" detection up into the Python runtime,
where it becomes a `ValueError` that the normal exception path — and
therefore the engine's `on_error` contract and the caller's own
`try/except` — can see and act on. The fix converts an *uncatchable*
failure into a *catchable* one **before** the buffer reaches C.

## Prevention

**Never hand a raw `memoryview` from an externally-owned or untrusted
buffer to a C-extension parser without a defensive `bytes()`
materialization that fails catchably.** The general rule: at any
boundary where a foreign-owned buffer crosses into a C extension,
materialize through a Python-level operation that *raises* (rather than
*dereferences*) on an invalid buffer, so the failure stays inside the
catchable exception model.

**Add a regression test that the process SURVIVES.** Yield a
`.release()`'d `memoryview` under *each* `on_error` mode and assert a
*catchable* error rather than a crash. Because a segfault cannot be
asserted in-process, run the scan in a **subprocess** and assert
`exit_code != 139` (and that a `ValueError` — not a `SIGSEGV` — was the
failure). A test that only checks "an error happened" in-process is
worthless here: the in-process variant of this bug *is* the crash, so
the harness must verify the survival itself.

**This class of bug needs adversarial review, not happy-path tests.** An
uncatchable crash that bypasses the entire error taxonomy is invisible to
every test that feeds only valid inputs. The released-view case was
caught precisely because a reviewer attacked the boundary's *documented
but hostile* input, not its expected one. When a contract advertises an
"anything goes" extension point (here: "a `memoryview` over a C++-owned
buffer is a first-class record bytes value"), the review must include
inputs that honour the type but violate the *lifetime*.

**Know the residual caller-contract boundary.** `bytes()` rescues a
`.release()`'d `memoryview` because `release()` flips a Python-level flag
that `bytes()` checks. A `memoryview` whose *underlying buffer* was
genuinely freed (the C++ owner `delete`d it) without calling `.release()`
can still crash either path — `bytes()` will dereference the same dead
pointer. That is a **hard caller-contract boundary**, not something the
engine can defend: the `Source` contract requires the caller to free the
buffer **only after a record is consumed** (see
`src/protokit/storage/source.py`). `bytes()` closes the
*Python-detectable* half of the failure surface; the *undetectable* half
remains the caller's responsibility, documented at the boundary.

## Related Issues

- [[keyboardinterrupt-baseexception-bypass-rule-pack-load-2026-05-07]] —
  the sibling shape on the lint surface: an uncatchable / `BaseException`
  event (`KeyboardInterrupt` at rule-pack module-body load) that unwinds
  *past* a typed-catch contract and defeats the stable-prefix guarantee.
  Same failure family — "an event the `except` taxonomy cannot see
  defeats a fail-loud contract" — but the mechanism differs: that doc's
  escape is a *Python* exception above `Exception` in the hierarchy
  (catchable with a wider `except`), whereas this doc's escape is a
  *process signal* below the Python layer entirely (not catchable at any
  `except` width — it must be prevented before reaching C with the
  `bytes()` boundary). The two together bracket the contract's blind
  spots from both ends of the runtime.
- [[mock-patch-c-extension-method-descriptor-2026-05-06]] — companion on
  the same protobuf C-extension boundary: why `MergeFromString` and
  friends are method-descriptors on the upb message class and how to
  patch them in tests. Relevant when writing the subprocess regression
  test for this bug.
- [[no-raise-contract-extends-to-post-init-failures-2026-05-14]] — the
  engine's narrow-typed-catch discipline (here `{FrameError,
  DecodeError}` only): a contract-violation `ValueError` is deliberately
  NOT wrapped into the data-fault type and propagates loud, the same way
  a predicate exception propagates rather than being captured by
  `on_error`.
- In-code taxonomy of record: `src/protokit/storage/engine.py` module
  docstring (Parse-confinement D5 + Narrow, typed catch KD-3). The
  `bytes(raw)` boundary and its "catchable `ValueError` propagates
  fail-loud" rationale are pinned in the docstring and at the parse site
  so the safety property is not re-droppable as a "micro-optimization" by
  a future edit.
