---
title: "runtime_checkable Protocol isinstance is presence-only, not a correctness gate"
date: 2026-05-30
category: design-patterns
module: protokit.storage
problem_type: design_pattern
component: service_object
severity: medium
applies_when:
  - "A public extension point is modeled as a runtime_checkable Protocol and you are tempted to validate untrusted inputs with isinstance(x, Proto)"
  - "A third-party adapter feeds items into a trusted engine across a trust boundary"
  - "The Protocol's method (e.g. __iter__) yields a shape the type system cannot express (here a (str, bytes|memoryview) 2-tuple)"
  - "Optional cleanup hooks (close/__enter__/__exit__) are intentionally kept out of the Protocol body so a plain generator still qualifies"
tags:
  - runtime-checkable
  - protocol
  - isinstance
  - pep-544
  - trust-boundary
  - input-validation
  - structural-typing
  - protokit-storage
---

# runtime_checkable Protocol isinstance is presence-only, not a correctness gate

## Context

protokit's storage scan engine takes a single public extension point, `Source`
(`src/protokit/storage/source.py`), modeled as a `runtime_checkable`
`Protocol`. Its structural contract is one method — `__iter__` yielding
`tuple[str, bytes | memoryview]` `(stream_id, record_bytes)` pairs. Third-party
adapters (a pybind11-wrapped C++ buffer source, a length-delimited file source,
an object-store source) are recognised *structurally*, with no base class to
inherit, so a bare generator that yields the right tuples is a `Source`.

When a public adapter boundary like this consumes untrusted / third-party
input, it is tempting to gate inputs with `isinstance(x, Source)` and trust
whatever passes. That reflex is wrong, and the reason is a documented PEP 544
gotcha: **`runtime_checkable` `isinstance` checks method *presence* only.** It
confirms `x` has `__iter__` and says nothing about what that iterator yields.
So *every* iterable — `str`, `list`, `dict`, `tuple` — passes
`isinstance(x, Source)` (verified, protobuf 5.27 / py3.13). `isinstance` is a
recognition aid, not a correctness gate.

The real protection lives one layer in, as a *per-record* element-shape guard
inside the engine (`_as_record` in `src/protokit/storage/engine.py`).

## Guidance

**1. Do not use `runtime_checkable isinstance` as a correctness gate at a trust
boundary.** It verifies the protocol's method names exist on the object and
nothing about their behaviour or yield shape. Treat it as documentation of the
structural contract and (at most) a coarse recognition aid — never as proof the
input is well-formed.

**2. Validate the actual yielded shape per record, inside the engine.** A
malformed item can appear at *any* index, not just the first, so the guard runs
on every record — not once on the first item, and not as an up-front
`isinstance` on the whole source. In protokit each pulled item passes through
`_as_record`, which checks it is a `(str, bytes | memoryview)` 2-tuple:

```python
def _as_record(
    item: object, record_index: int
) -> tuple[str, bytes | memoryview]:
    """Validate a yielded item is a ``(str, bytes | memoryview)`` 2-tuple."""
    if (
        isinstance(item, tuple)
        and len(item) == 2
        and isinstance(item[0], str)
        and isinstance(item[1], (bytes, memoryview))
    ):
        return item[0], item[1]
    ...
```

Note the `isinstance` checks here are on the *concrete element shape* (`tuple`,
`str`, `bytes`/`memoryview`) — the thing the Protocol could never express — not
on the Protocol itself.

**3. Convert a bad shape into a typed fault dispatched through the engine's
error policy — never let a raw `ValueError`/`TypeError` leak.** A malformed item
becomes a `FrameError` (a typed `StorageError` subclass) that the engine routes
through its `on_error` policy (`raise` / `skip` / `collect`), the same path
every other per-record fault takes. The call site routes the guard's typed
exception, not whatever a tuple-unpack would have thrown:

```python
try:
    stream_id, raw = _as_record(item, record_index)
except FrameError as malformed:
    self._dispatch(malformed)
    continue
```

**4. Make the reporting path itself crash-safe.** When describing a malformed
item, a hostile or buggy `__repr__` that raises must not leak past the error
handler. `_as_record` guards the `repr`:

```python
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
```

The error path's job is to *describe* an already-bad input; it must not itself
become a second, uncaught failure.

**5. Keep optional capabilities out of the Protocol body and probe them with
`hasattr`.** `Source`'s structural contract is `__iter__` *only*. Cleanup hooks
(`close()` / `__enter__` / `__exit__`) are deliberately **not** in the Protocol,
so `isinstance` still admits a plain generator — which carries `close()`
natively and gets cleanup for free without being excluded. The engine
capability-probes cleanup rather than requiring it:

```python
def _supports_context_manager(source: object) -> bool:
    return hasattr(source, "__enter__") and hasattr(source, "__exit__")
```

`scan` prefers `with` when available, else `close()` if present, else nothing —
on both normal exhaustion and a mid-iteration exception.

## Why This Matters

Relying on `runtime_checkable isinstance` at a trust boundary gives *false
confidence*. Because presence-only checking admits every iterable, a `str` or a
`list` of the wrong shape silently passes the gate and then:

- fails *deep* inside the parse with a confusing, far-from-source error (a
  `ValueError`/`TypeError` from tuple-unpacking or from `bytes(raw)`), bypassing
  the `on_error` policy entirely; or, worse,
- is treated as valid and produces garbage downstream.

Pushing validation to a per-record element guard fixes both: the failure is
caught at the exact record that is malformed, attributed with a record index and
a (crash-safe) `repr`, typed as a `FrameError`, and dispatched through the same
`on_error` policy as every other per-record fault — so `raise` fails loud,
`skip` drops it, and `collect` records it. The element shape (`(str, bytes |
memoryview)` 2-tuple) is exactly the contract the Protocol's type annotation
*states* but the runtime `isinstance` *cannot enforce*, so the engine enforces
it itself.

Keeping cleanup out of the Protocol is the other half of the same discipline:
the structural contract stays minimal (a bare generator qualifies), and the
genuinely optional capability is discovered, not demanded — `isinstance`
admitting a generator is a feature, because the generator's native `close()` is
then found by `hasattr` probing, not by protocol membership.

## When to Apply

- **Any `runtime_checkable` Protocol used at a trust boundary for untrusted or
  third-party inputs.** The moment you reach for `isinstance(x, Proto)` to
  *validate* (not merely recognise), stop: it checks method presence only.
- **When the Protocol's method yields or returns a shape the type system can't
  enforce at runtime** (a tuple of a specific arity/element types, a structured
  dict, a constrained `str`). Put the real check on the concrete element shape,
  not the Protocol.
- **When a malformed item can appear at any position**, not just first — make
  the guard per-element, not a one-time front-door check.
- **When the input may be adversarial or buggy** — guard the *reporting* path
  too (e.g. `repr` fallback), so describing a bad input never becomes a second
  failure.
- **When some capability is genuinely optional** — leave it out of the Protocol
  body and `hasattr`-probe it, so the structural contract stays minimal and a
  plain generator still qualifies.

## Examples

**Presence-only `isinstance` admits non-records (verified, protobuf 5.27 /
py3.13):**

```python
from protokit.storage.source import Source

# All True — every iterable has __iter__, the Protocol's only method.
isinstance("a string", Source)        # True  (yields str chars, not 2-tuples)
isinstance(["not", "records"], Source)  # True
isinstance({"k": "v"}, Source)          # True  (yields keys)
isinstance((1, 2, 3), Source)           # True

# None of these would survive _as_record per element — but isinstance can't see that.
```

**The two layers, side by side** (`src/protokit/storage/engine.py`,
`_iterate`): pull a record, then guard its *shape* — the per-record guard is the
real gate, `isinstance(x, Source)` never appears:

```python
try:
    item = next(iterator)
except StopIteration:
    return
except FrameError as framing_error:        # source's own framing fault
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
```

**Source of truth:**
- `src/protokit/storage/source.py` — the `Source` `runtime_checkable` Protocol,
  its "`runtime_checkable` caveat" docstring, and the deliberately-omitted
  cleanup hooks.
- `src/protokit/storage/engine.py` — `_as_record` (the per-record element guard
  with the crash-safe `repr` fallback), its dispatch call site in `_iterate`,
  and `_supports_context_manager` (the `hasattr` capability probe).

## Related

- [[no-raise-contract-extends-to-post-init-failures-2026-05-14]] — the companion
  discipline on the *output* side: a dispatch surface must convert downstream
  failures into typed faults routed through the policy rather than letting a raw
  exception leak. Here `_as_record` does the same for a *malformed input* shape,
  funneling it into `FrameError` + `on_error` instead of a bare
  `ValueError`/`TypeError`.
- [[normalize-at-input-boundary-2026-05-07]] — the general "validate/normalize at
  the input boundary, not at the deep consumer" principle. This doc is the
  trust-boundary variant: the boundary check that *feels* sufficient
  (`isinstance(x, Source)`) is presence-only, so the real validation moves to a
  per-record element guard just inside the boundary.
- [[keyboardinterrupt-baseexception-bypass-rule-pack-load-2026-05-07]] — the
  other half of the engine's typed-catch discipline (KD-3): only the engine's own
  per-record faults (`FrameError`) and protobuf `DecodeError` are subject to
  `on_error`; `BaseException` (`SystemExit` / `KeyboardInterrupt` /
  `GeneratorExit`) and predicate exceptions always propagate. Where that doc is
  about which exceptions must *escape* a guard, this one is about which *inputs*
  a presence-only `isinstance` wrongly admits.
