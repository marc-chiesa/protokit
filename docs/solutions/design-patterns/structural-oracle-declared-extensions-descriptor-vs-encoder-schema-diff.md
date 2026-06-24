---
title: "Structural fidelity oracle: diff the descriptor's declared set against the encoder's produced schema to catch silently-dropped declared fields"
date: 2026-06-24
category: docs/solutions/design-patterns
module: protokit.storage
problem_type: design_pattern
component: tooling
severity: medium
applies_when:
  - "A per-record / byte-delta / unknown-field probe is your only fidelity check and you also need to catch data the descriptor MODELS but the encoder OMITS"
  - "A schema-driven encoder (e.g. ptars) drops descriptor-declared proto2 extensions from its Arrow/Parquet output, leaving an empty unknown-field set (byte delta 0)"
  - "You can enumerate the declared set (pool.FindAllExtensions via descriptor.file.pool) and the encoder's produced columns (a cached schema from an empty conversion) and diff them at bind time"
  - "You want an O(1)-per-conversion, bind-time completeness check that fails fast under an error policy, keyed by stable identity rather than a fragile name union"
  - "You need the oracle to be forward-defensive so a future encoder that DOES emit the column automatically stops reporting"
tags:
  - structural-oracle
  - declared-extensions
  - proto-to-arrow
  - columnar
  - ptars
  - fidelity-signal
  - proto2-extensions
  - schema-diff
---

# Structural fidelity oracle: diff the descriptor's declared set against the encoder's produced schema

## Context

protokit's columnar sink (`src/protokit/storage/_columnar.py`) converts a proto scan
stream to Arrow/Parquet through **ptars** — a schema-driven encoder that columnizes
exactly `descriptor.fields`. Anything it doesn't model it drops silently: no column, no
error, just absent data.

The v1 fidelity signal was a single **per-record probe** (`_unmodeled_byte_delta`):
serialize a message, `DiscardUnknownFields()`, re-serialize, take the byte delta. A
non-zero delta means the record carried wire data the descriptor doesn't model — an
out-of-range proto2 closed enum or an *undeclared* field — both of which the runtime
relegates to the unknown-field set.

That probe has an **exact structural blind spot**, not an incidental one. A *declared*
proto2 extension — one whose `.proto` the consumer's pool compiled — is not unknown
data: protobuf parses it into `Extensions[...]` with an **empty unknown-field set**. So
`DiscardUnknownFields()` removes nothing, the byte delta is `0`, and the probe reports
clean — yet ptars never emitted a column for it (extensions live in
`descriptor.file.pool`, not in `descriptor.fields`), so the data is gone from the
Parquet. The probe is structurally *incapable* of seeing modeled-but-omitted data,
because its proxy (the unknown-field set) is empty by construction for that loss class.

## Guidance

Add a **second, structural oracle** alongside the per-record probe. Instead of inspecting
each record's runtime state, diff two *schemas* at bind time: what the descriptor
**declares** versus what the encoder **produced**.

- **"Declared":** `descriptor.file.pool.FindAllExtensions(descriptor)` — every extension
  the pool knows extends this message.
- **"Produced":** the encoder's own output schema, which ptars yields for free via an
  *empty* conversion (`messages_to_record_batch([], descriptor).schema`), cached once on
  the adapter. Record-independent, so the whole oracle is O(1) per conversion.

The shipped diff (`_dropped_declared_extensions` in `src/protokit/storage/_columnar.py`):

```python
def _dropped_declared_extensions(descriptor, schema_names):
    extensions = descriptor.file.pool.FindAllExtensions(descriptor)
    if not extensions:
        return ()
    field_names = {field.name for field in descriptor.fields}
    # Only a NON-field column the encoder produced could be an extension column.
    # Subtracting field names first means a regular field sharing a name with an
    # extension cannot mask the extension.
    extension_columns = set(schema_names) - field_names
    return tuple(
        ext.full_name for ext in extensions if ext.name not in extension_columns
    )
```

Two choices carry the weight:

1. **Key on identity, never a name-union.** Iterate the extension *objects* and report by
   `ext.full_name`. Do **not** build `field_names ∪ extension_names` and look for
   absences — a regular field named `id` would then mask a dropped extension also named
   `id`. Subtracting `field_names` from the produced columns *first* makes a same-named
   field unable to suppress the report.

2. **Forward-defensive against a future encoder.** An extension is reported dropped
   *unless* the encoder produced a non-field column attributable to it. For ptars 0.0.17
   no extension is ever columnized, so every declared extension is reported — but a future
   ptars that emits an `ext_val` column would suppress the report automatically, no code
   change. Pin that encoder-behavior assumption **end to end** so a dependency upgrade
   fails a test rather than silently shifting the signal.

Gate it behind the same `fidelity != "ignore"` switch as the per-record probe (so
`ignore` pays nothing — not even the `FindAllExtensions` call), and wire it into the
precedence ladder at bind, before any record or file:

```python
measure = fidelity != "ignore"
dropped = _dropped_declared_extensions(descriptor, adapter.schema.names) if measure else ()
if fidelity == "error" and dropped:
    raise FidelityError(dropped_extensions=dropped)  # fail fast, at bind
```

## Why This Matters

**Two probes cover disjoint loss classes; neither alone is complete.** The same extension
routes to a *different* probe depending solely on whether the consumer's pool loaded its
descriptor:

- The **per-record probe** sees *undeclared* data — including an extension whose `.proto`
  the pool never loaded: from the reduced descriptor's view those bytes are undeclared, so
  they land in the unknown set and the byte delta is non-zero.
- The **structural oracle** sees *declared-but-dropped* data — an extension the pool
  *does* know, parsed into `Extensions[...]`, byte delta `0`, no column emitted.

A single probe — whichever one — is blind to half the loss. The cheaper proxy probe had a
*stated* blind spot; the fix is not to make it smarter (it can't be — its proxy is empty
by construction for declared extensions) but to add a second oracle observing a different
signal.

**Fail-fast and precedence.** The structural signal depends only on the descriptor and the
cached empty-conversion schema, not on any record, so under `error` it raises *before the
scan runs and before the writer opens* — no partial file, no wasted I/O — and it flags
even an empty scan. That fixes its rung in the ladder: **recursion pre-flight → structural
(bind) → decode fault (scan-end) → per-record (scan-end)**. On a streaming/generator
entry point it fires on the first `next()`, before any batch is yielded; the per-record
signal, by contrast, can only be *reported* there (never raised mid-stream), because
already-emitted batches can't be recalled.

## When to Apply

- **proto → Arrow / Avro / ORC / Thrift / Parquet**, or any descriptor-driven encoder that
  emits columns for "regular fields" but not for sidecar constructs (extensions, dynamic
  payloads, well-known-type collapses).
- Any pipeline where a **runtime/per-record proxy** (byte deltas, unknown-field sets,
  round-trip diffs) is the loss detector — audit what that proxy is *structurally* blind
  to, then add a **declared-schema vs produced-schema diff** to cover it.
- Especially when the loss class is **modeled-but-omitted**: the data is legitimate and
  known to the schema, so per-record inspection sees nothing wrong (empty unknown set,
  clean round-trip), yet the encoder didn't carry it.

Cheap to add when the encoder hands you its produced schema for free (here, an empty
conversion), making the oracle O(1) per conversion rather than O(records).

## Examples

**Blind per-record probe vs. structural oracle — same populated declared extension:**

```python
m.id = 7
m.Extensions[ext] = 42                  # declared in the pool
report = to_parquet([("s", m.SerializeToString())], reg, out, stream_id="s")
report.unmodeled_records   # 0              <- per-record probe: byte delta 0, blind
report.dropped_extensions  # ("so.ext_val",) <- structural oracle catches it
pq.read_table(out).schema.names  # ["id"]    <- ptars really did drop the column
```

**The disjoint other half — the extension's `.proto` is not in the consumer's pool:**

```python
report = to_parquet([("s", wire)], reduced_reg, out, stream_id="s")
report.dropped_extensions  # ()   <- oracle can't see an unloaded extension
report.unmodeled_records   # 1    <- ...but the byte-delta probe catches it
```

Same bytes, opposite probe.

**Keying / forward-defense edge cases:**

```python
_dropped_declared_extensions(desc, ["id"])            # ("x.id",)  same-named field does NOT mask
_dropped_declared_extensions(desc, ["id", "ext_val"]) # ()         future encoder column auto-suppresses
_dropped_declared_extensions(outer_desc, [])          # ()         modeled fields are never inspected
```

**The group counter-example — *not* this loss class.** A proto2 group is a `TYPE_GROUP`
field the encoder *does* columnize (a struct column), so the oracle correctly does not
flag it; a *populated* group is a loud decode crash (a raw `ValueError`, a separate
decode-robustness gap), not the silent modeled-but-omitted loss the oracle exists to
catch. (This corrected a v1 doc that miscategorized groups as a drop class.)

These behaviors are pinned in `tests/storage/test_columnar_structural.py` (the pure diff
logic) and `tests/storage/test_columnar.py` (the complementarity, group, and end-to-end
ptars-consistency tests that guard the encoder-behavior assumption).

## Related

- [Detecting unmodeled wire data via a DiscardUnknownFields byte-delta probe (and its declared-extension blind spot)](unmodeled-wire-data-probe-byte-delta-blind-to-declared-extensions.md) — the v1 per-record probe whose **named blind spot** this oracle closes. The two are a deliberate pair: per-record proxy for *undeclared* drift ↔ bind-time structural diff for *declared-but-uncolumnarized* drift, each with a stated domain of validity.
- [Faithful proto-to-Arrow mapping: presence-class structure, Arrow-native values](proto-to-arrow-faithful-mapping-presence-structure-arrow-native-values.md) — the descriptor-derived produced schema this oracle diffs against.
- [Recursive proto schemas segfault ptars during Arrow schema build](../security-issues/recursive-proto-schema-segfaults-ptars-arrow-build.md) — the same "Python-side bind-time pre-flight, before the C boundary, raising a typed error" move the oracle mirrors.
- [ptars over protarrow for proto-to-Arrow on isolated descriptor pools](../tooling-decisions/ptars-over-protarrow-proto-to-arrow-isolated-descriptor-pools.md) — why ptars omits declared extensions (descriptor-handed Rust core; extensions are not regular `descriptor.fields`), the root cause this oracle detects.
- [Tolerant-iteration error taxonomy: narrow typed catch + loud completion guard](tolerant-iteration-error-taxonomy-narrow-catch-loud-completion-guard-2026-05-30.md) — the fail-loud typed-fault channel the oracle's `error`-policy raise slots into.
- **Origin:** issue #25 (columnar real-data go/no-go) surfaced the blind spot; shipped in PR #44.
