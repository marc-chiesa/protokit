---
title: "ptars over protarrow for proto-to-Arrow conversion on isolated descriptor pools"
date: 2026-06-07
category: docs/solutions/tooling-decisions
module: protokit.storage
problem_type: tooling_decision
component: tooling
severity: high
applies_when:
  - "Choosing a proto-to-Arrow / proto-reflection dependency for an engine that resolves messages through isolated (non-default) DescriptorPools"
  - "The candidate library detects well-known types by default-pool descriptor identity (Python `is`/`==` on a WKT DESCRIPTOR)"
  - "A constrained protobuf pin is in force (protokit pins `protobuf>=4.21,<6`) and a candidate transitively couples to the protobuf Python API version"
  - "Adopting a young (`0.0.x`, single-maintainer) dependency that is nonetheless the best technical fit"
tags:
  - proto-to-arrow
  - ptars
  - protarrow
  - descriptor-pool
  - well-known-types
  - protobuf-version-pin
  - dependency-risk
  - parquet
---

# ptars over protarrow for proto-to-Arrow conversion on isolated descriptor pools

## Context

protokit's storage scanner decodes proto-at-rest through **per-stream isolated `DescriptorPool`s** (`build_pool` / `get_message_class` in `src/protokit/_pools.py`). Pool isolation is the differentiator: each stream's types resolve in their own pool, never the process-global default pool, so two streams can carry conflicting definitions of the same fully-qualified name without colliding.

PR3 needed a proto→Arrow library to write Parquet directly and skip the proto→JSON→Parquet double-encode. The two real candidates were **protarrow** (pure-Python, descriptor-walking, the more popular/mature option) and **ptars** (Rust/PyO3 over `prost`/`prost-reflect`, `0.0.x`, single-maintainer, ~26★). The choice was settled by **two empirical spikes against the engine's actual isolated-pool path on 2026-06-02** — not by stars, downloads, or maturity signals. The implemented sink lives at `src/protokit/storage/_columnar.py` (PR #17).

## Guidance

When picking a proto-introspection dependency for an engine that uses anything other than the default descriptor pool, apply three rules:

1. **Spike against your real descriptor-provenance model, not a toy default-pool example.** A library that detects well-known types (WKTs) by **default-pool descriptor identity** — Python `is`/`==` against `Timestamp.DESCRIPTOR` — silently fails on isolated pools. The isolated `Timestamp` is a *different descriptor object*, so the identity check returns false and the WKT degrades to a raw `struct` instead of a native Arrow `timestamp`. protarrow falls into exactly this trap (`proto_to_arrow.py`) (provenance — verified against protarrow at the 2026-06-02 spike; protarrow's behavior is external and not re-asserted by protokit's test suite). The failure is silent — no error, just wrong output — and a default-pool demo would never surface it.

2. **Check the dependency's transitive protobuf-version coupling against your pin.** Pure-Python descriptor-walkers are coupled to the protobuf *Python API* version. protarrow `>=0.15` requires protobuf 6 because it calls `FieldDescriptor.is_repeated`; protobuf 6/7 removed `FieldDescriptor.label`, which protokit's lint/compat engine depends on, so protokit pins `protobuf>=4.21,<6`. The newest usable protarrow is therefore 0.14.0 — a version lock layered on top of the WKT shim (provenance — protarrow/protobuf versions verified at the 2026-06-02 spike; these external-version cutoffs are not re-asserted by protokit's test suite, so re-check before relying on the protarrow 0.14.0 ceiling). (See the load-bearing pin: [`protobuf>=4.21,<6` upper-bound pin](protobuf-upper-bound-pin-fielddescriptor-label-removed-in-7-2026-05-27.md).)

3. **Prefer a Rust/decoupled core when your protobuf pin is constrained.** ptars parses wire bytes in Rust over the descriptors it is *handed*; the Python `protobuf` package is used only to register `FileDescriptor`s into a ptars `HandlerPool`. Its conversion correctness does not depend on the protobuf Python API version, so it runs cleanly on protobuf 5.x. The spike verified it maps WKTs correctly on isolated pools (including nested at depth), plus map/repeated/nested/oneof and PR2 presence parity.

Then **contain the maturity risk** of a young best-fit dependency with four mechanisms: a thin swappable conversion adapter (`_PtarsConversionAdapter`, so the backend can be replaced without touching callers), an **exact** version pin (`ptars==0.0.17`), optional-extra isolation (the `protokit[parquet]` extra means the core install never depends on it), and an ABI note (ptars bundles `arrow-rs 57.1`; the pinned pyarrow must stay ABI-compatible).

## Why This Matters

The expensive failure here is *silent correctness loss*, not a crash. Default-pool-identity WKT detection produces a valid-looking Parquet file in which every `Timestamp` has quietly become an opaque `struct` — discovered only downstream, after the data is written. Choosing on reputation would have picked the more popular library straight into that trap. Spiking against the real path converts an invisible architectural mismatch into a measured, up-front decision.

The protobuf-pin coupling is the second invisible cost: a pure-Python walker that needs protobuf 6 forces an indefinite version lock that constrains every future protobuf bump. A Rust/decoupled core severs that coupling entirely — the dependency composes with `protobuf<6` without conflict because its correctness lives in Rust, not in the protobuf Python API surface.

## When to Apply

- Choosing any proto-reflection / descriptor-walking dependency (proto→Arrow, proto→JSON, schema diff, validation) when your engine uses **isolated, non-default, or dynamically-built descriptor pools**.
- More generally: any time a candidate library's behavior depends on **object identity** of objects your architecture deliberately keeps non-identical (isolated pools, sandboxed registries, per-tenant type systems).
- When your project carries a constrained version pin on a foundational runtime (here `protobuf<6`) and a candidate transitively couples to that runtime's *Python API* surface.
- Adopting a `0.0.x` / single-maintainer dependency that is the best technical fit — apply the containment quartet (swappable adapter + exact pin + optional extra + ABI note).

## Examples

The trap — default-pool-identity WKT detection (pure-Python; breaks on isolated pools):

```python
# protarrow-style: WKT detected by descriptor IDENTITY against the default pool
from google.protobuf.timestamp_pb2 import Timestamp
if field.message_type is Timestamp.DESCRIPTOR:        # proto_to_arrow.py
    return pa.timestamp("us")
# On an ISOLATED pool, field.message_type is a *different* descriptor object,
# so this is False -> silently degrades to struct<seconds:int64, nanos:int32>.
```

The fix — descriptor-handed Rust parsing (works regardless of which pool produced the descriptor):

```python
# ptars-style: hand the isolated pool's file descriptors to a Rust HandlerPool;
# WKTs are matched in Rust over the descriptors given, not by Python identity.
pool = build_pool(file_descriptor_protos)             # protokit isolated pool
msg_cls = get_message_class(pool, fully_qualified_name)
handler_pool = HandlerPool(transitive_file_descriptors)
batch = handler_pool.messages_to_record_batch(messages, msg_cls.DESCRIPTOR)
# -> Timestamp maps to Arrow `timestamp` even though the descriptor came from an
#    isolated pool, and it runs on protobuf 5.x (no FieldDescriptor.label dependency).
```

(Both snippets are illustrative composites grounded in the verified API names; the spike ran against the engine's real `build_pool`/`get_message_class` path on 2026-06-02.)

The rule in one line: *spike the candidate against your actual descriptor-provenance model and check its transitive protobuf-Python-API coupling; when both bite, prefer a Rust/decoupled core and contain its maturity with adapter + exact pin + optional extra.*

## Related

- [Faithful proto-to-Arrow mapping (presence structure + Arrow-native values)](../design-patterns/proto-to-arrow-faithful-mapping-presence-structure-arrow-native-values.md) — the conversion fidelity model this library choice enables (this doc = the dependency; that doc = the mapping).
- [`protobuf>=4.21,<6` upper-bound pin is load-bearing](protobuf-upper-bound-pin-fielddescriptor-label-removed-in-7-2026-05-27.md) — the pin that disqualifies protarrow `>=0.15`; the binding premise for rule 2.
- Origin: PR #17 (`feat/storage-pr3-columnar`); sink at `src/protokit/storage/_columnar.py`; decision recorded in `docs/brainstorms/2026-06-02-storage-pr3-columnar-parquet-requirements.md`.
