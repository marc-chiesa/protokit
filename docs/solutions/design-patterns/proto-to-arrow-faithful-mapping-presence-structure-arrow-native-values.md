---
title: "Faithful proto-to-Arrow mapping: presence-class structure, Arrow-native values, lossless structs for Any/WKT"
date: 2026-06-07
last_updated: 2026-06-10
category: docs/solutions/design-patterns
module: protokit.storage
problem_type: design_pattern
component: tooling
severity: medium
applies_when:
  - "Mapping protobuf messages to an Arrow/Parquet schema while preserving proto3 presence semantics"
  - "Reconciling a JSON faithful view with a columnar view that must share presence parity but diverge on value encoding"
  - "Representing oneof, map, repeated, nested-message, and well-known types in a columnar schema"
  - "Deciding between fail-loud and lossless-struct fallback for Any/Struct/FieldMask and other opaque descriptors"
tags:
  - proto-to-arrow
  - arrow-schema
  - parquet
  - proto3-presence
  - nullability
  - oneof
  - well-known-types
  - value-encoding
---

# Faithful proto-to-Arrow mapping: presence-class structure, Arrow-native values, lossless structs for Any/WKT

## Context

protokit's storage layer already had a "faithful view" for proto→JSON (PR2): a rendering that mirrors proto3 presence semantics rather than naively dumping fields (see [Faithful proto-to-JSON field projection](proto-json-field-projection-presence-class-fill-then-prune-2026-06-01.md)). PR3 extends faithful representation to proto→Arrow/Parquet (`src/protokit/storage/_columnar.py`).

The naive expectation — "the faithful view is the faithful view, so Parquet values should match the JSON output" — is wrong, and that is the central trap. Fidelity in a columnar export is **two independent axes with separate contracts**. All mappings below were verified against ptars 0.0.17 on the engine's real isolated-pool path on 2026-06-02 (brainstorm R5/R6/R7/R13) (provenance — verified against ptars 0.0.17; current behavior re-asserted by the `storage-parquet` CI job running `tests/storage` against the pinned extra).

## Guidance

Treat presence/nullability **structure** and leaf **value representation** as two orthogonal contracts. Do not let a shared "faithful view" label imply byte-identical output across formats.

**Axis 1 — presence/nullability structure** mirrors proto3 presence rules, identical to PR2's faithful JSON view:

- proto3 implicit-presence scalar → **non-nullable** column carrying the default (`0`, `""`, …)
- explicit-`optional` scalar, message field, oneof member, wrapper type → **nullable** column
- repeated → Arrow `list`
- map → native Arrow `map` (not list-of-structs)
- nested message → Arrow `struct`
- WKT temporal/wrapper → natural Arrow types (`Timestamp`/`Duration` → `timestamp`/`duration`), **including nested inside submessages at depth**

**Axis 2 — leaf value representation is Arrow-native and deliberately DIVERGES from the JSON view.** The JSON faithful view renders JSON-domain encodings; Arrow renders machine-native types for the *same field*:

| Field type  | JSON-view value (PR2)   | Arrow-native value (PR3)        |
|-------------|-------------------------|---------------------------------|
| `bytes`     | base64 string           | `binary`                        |
| `int64`     | decimal string          | `int64`                         |
| `fixed64`   | decimal string          | `uint64`                        |
| `sint32`    | decimal string          | `int32`                         |
| enum        | enum NAME (string)      | `int32` (configurable via `enum_repr`) |
| `Timestamp` | RFC-3339 string         | `timestamp`                     |
| `Duration`  | string (e.g. `"3.5s"`)  | `duration`                      |

Consumers must **not** expect Parquet values to byte-match the JSON output. Keep structure parity and value encoding as separately documented contracts.

Three further structural rules:

- **oneof arms → independent nullable columns, no discriminator.** Lossy and *accepted*: an arm set to its type's default value is indistinguishable from an unset arm, and an Arrow→proto round-trip cannot recover which arm was active. Documented tradeoff, not a bug. (The JSON faithful view preserves arm identity; Parquet currently does not — a derived discriminator column is a candidate future addition.)
- **`Any`/`Struct`/`FieldMask` → lossless structs, NEVER blocked** (`Any` → `struct<type_url, value>`). This **superseded** an earlier "fail-loud on `Any`/`Struct`" decision once the spike showed they map losslessly. **Correction (2026-06-15):** this holds for `Any`/`FieldMask` and the scalar WKTs, but NOT for the *recursive* `Struct`/`Value`/`ListValue` family — those have no finite Arrow shape and segfault ptars 0.0.17's schema build, like any recursive type, so they are rejected by the recursion pre-flight (layer 0 above), not mapped. Reserve fail-loud strictly for a descriptor the backend cannot build a handler for *at all* — and raise it **before any output** (build/validate the `HandlerPool` before opening the `ParquetWriter`). The no-partial-file guarantee is **three-layered**: a descriptor pre-flight (`_reject_recursive`) rejects a recursive type before ptars is even invoked — the only catch for the recursive-type segfault, which bypasses both layers below — then handler-build failure raises before the writer ever opens (no file created), AND on any `BaseException` *after* the writer opens — a collected-fault failure, a mid-stream exception, a Ctrl-C — the sink closes the writer and unconditionally unlinks the file it created (`to_parquet` in `src/protokit/storage/_columnar.py`). Callers wrapping the sink own only their own publish step (see the atomic CLI file-publish doc below), not in-write cleanup.
- **Schema is DESCRIPTOR-derived, never inferred from the first observed record.** An empty result still yields a valid, readable zero-row Parquet file carrying the full column schema. This also gives a stable schema across batches (no drift when an early batch happens to omit an optional field).

## Why This Matters

Conflating the two axes produces wrong consumer code on both sides. A consumer who assumes Parquet `bytes` are base64 strings (because the JSON view rendered them that way) double-decodes; one who assumes enum values are name strings type-mismatches against an `int32` column. Calling both behaviors "faithful" without separating the contracts is the root cause.

Inferring schema from the first record is a second latent footgun: empty results crash or produce schemaless files, and optional-field omission in an early batch silently changes the schema mid-stream. Descriptor-derived schema makes the column set a function of the type, not the data. And flipping `Any`/`FieldMask` (and the scalar WKTs) from fail-loud to lossless-struct turned a hard blocker into a faithful representation — though the recursive `Struct`/`Value`/`ListValue` family stays rejected, since it segfaults the backend. Fail-loud and the recursion pre-flight should guard only true inability, not merely "opaque-looking" types.

## When to Apply

- Designing any cross-format faithful representation (proto→JSON *and* proto→Arrow, or any two serializations of one schema): define presence/nullability structure and leaf value encoding as **separate contracts** and document each.
- Mapping proto3 presence into a nullable type system (Arrow, SQL DDL, Parquet, Avro): use the presence-class table above — implicit→non-nullable-with-default, explicit/message/oneof/wrapper→nullable.
- Building any export whose schema should be **stable across batches and well-defined on empty input**: derive the schema from the type/descriptor, never from observed records.
- Deciding whether to fail-loud on an "exotic" proto type: check first whether the backend maps it **losslessly** (Any/FieldMask and the scalar WKTs do, to structs — but the recursive Struct/Value/ListValue family does NOT: it segfaults ptars and is rejected by the recursion pre-flight); reserve fail-loud for genuine handler-build failure, raised before output.

## Examples

Same field, two contracts — structure is shared, value encoding diverges:

```text
proto3 schema:
  optional bytes  payload = 1;   // explicit presence
  Status          status  = 2;   // enum, implicit presence
  fixed64         seq     = 3;   // implicit presence
  Timestamp       seen_at = 4;   // WKT message field

JSON faithful view (PR2):            Arrow-native (PR3):
  payload: "aGVsbG8="  (base64)        payload: binary,   NULLABLE (unset -> null)
  status:  "ACTIVE"    (enum name)     status:  int32,    NON-nullable (default 0)
  seq:     "42"        (dec string)    seq:     uint64,   NON-nullable (default 0)
  seen_at: "2026-06-02T...Z" (RFC3339) seen_at: timestamp, NULLABLE (unset -> null)
```

Lossless struct instead of fail-loud:

```python
# Layer 0: a recursive descriptor segfaults the backend's schema build, so a
# descriptor pre-flight rejects it (RecursiveSchemaError / UnsupportedWktError)
# BEFORE the build -- the only catch for a fault that bypasses both layers below.
reject_recursive(descriptor)
# Any is NOT blocked -- it maps to a lossless struct, conversion does not error.
#   google.protobuf.Any  ->  struct<type_url: string, value: binary>
# Layer 1: fail-loud is reserved for "cannot build a handler at all", before output:
handler_pool = build_handler_pool(descriptor)   # raises here if unmappable...
writer = pq.ParquetWriter(dest, schema)          # ...so no partial file is ever opened
# Layer 2: once the writer IS open, any BaseException (collected faults,
# mid-stream exception, Ctrl-C) closes the writer and unconditionally
# unlinks the file the sink created -- a truncated Parquet is never left
# looking complete (see to_parquet in src/protokit/storage/_columnar.py).
```

Descriptor-derived, batch-stable schema:

```python
# Schema comes from the message DESCRIPTOR, not the first record.
# A --where that matches nothing still writes a valid 0-row file
# carrying the full column schema a reader can open and inspect.
schema = arrow_schema_from_descriptor(msg_cls.DESCRIPTOR)   # not inferred from data
```

(Snippets are illustrative composites grounded in the verified behavior; see `src/protokit/storage/_columnar.py` for the implemented sink.)

The pattern in one line: *presence-class structure and Arrow-native value encoding are independent contracts; derive the schema from the descriptor so it is stable and empty-safe; map exotic types to lossless structs and reserve fail-loud for true handler-build failure — raised before any output, with the sink discarding its own partial file on any fault after the writer opens.*

## Related

- [Faithful proto-to-JSON field projection: fill-dense-then-prune, split by presence class](proto-json-field-projection-presence-class-fill-then-prune-2026-06-01.md) — the PR2 JSON faithful view whose presence-class structure axis this mirrors; same presence taxonomy, divergent leaf encoding.
- [ptars over protarrow for proto-to-Arrow on isolated descriptor pools](../tooling-decisions/ptars-over-protarrow-proto-to-arrow-isolated-descriptor-pools.md) — the dependency choice that makes this mapping implementable on isolated pools and protobuf 5.x (that doc = the dependency; this doc = the mapping it enables).
- [Atomic CLI file publish: sibling temp + umask-honoring mode + os.replace](atomic-cli-file-publish-sibling-temp-os-replace.md) — the CLI publish layer above this sink: the sink owns in-write disposal (the three-layer guard above — recursion pre-flight, handler-build fail-loud, mid-write unlink); the CLI wrapper owns only the atomic rename window.
- Origin: PR #17 (`feat/storage-pr3-columnar`); design recorded in `docs/brainstorms/2026-06-02-storage-pr3-columnar-parquet-requirements.md` (R5–R7, R11–R13).
