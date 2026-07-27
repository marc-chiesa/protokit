# Concepts

Shared domain vocabulary for this project — entities, named processes, and status concepts with project-specific meaning. Seeded with core domain vocabulary, then accretes as ce-compound and ce-compound-refresh process learnings; direct edits are fine. Glossary only, not a spec or catch-all.

> Seeded 2026-06-16 from the columnar/Parquet fidelity-signal work, so it currently covers the **storage / data-at-rest** area. Other areas (schema lint, compatibility checking, the message differ) are not yet defined here.

## Storage / data-at-rest

### Stream
A registered source of protobuf records that all share one message type, addressed by a `stream_id` and bound to its schema up front. One scan can carry several streams at once, each parsed against its own descriptors, so their types never collide.

### Isolated descriptor pool
A per-stream descriptor pool that resolves a message type independently of every other stream's pool — protokit's safe-concurrent-multi-version differentiator. Two streams can carry the same fully-qualified type name resolved through different pools and stay distinct types. A consequence that matters downstream: the descriptor a conversion is handed may be *narrower* than the wire bytes a producer actually wrote.

### Scan
The engine pass that reads a source of record bytes, routes each record to its stream's isolated pool, parses it, and yields the materialized message. Per-record faults are governed by an `on_error` policy (raise / skip / collect / route) rather than aborting silently.

### Columnar sink
The conversion of a scan stream to Apache Arrow / Parquet through the descriptor-driven ptars backend, behind the optional parquet extra. Because it is descriptor-driven it emits only columns the descriptor models and drops any wire data outside it — which is exactly what the Fidelity signal exists to surface.

### Unmodeled wire data
Wire bytes a message carried that its supplied descriptor does not model — a proto2 out-of-range closed-enum value, or an undeclared unknown/extension field. Such data vanishes from the columnar output even though a protobuf consumer of the same bytes would still see it.

### Fidelity signal
A per-record measurement of Unmodeled wire data during columnar conversion, surfaced as a count of affected records and total bytes so a lossy conversion is *visible* rather than silently wrong.

A graduated policy: *ignore* (don't measure), *warn* (measure and report, write the file), *error* (fail the conversion and discard the partial output).

The signal has two parts. The **per-record probe** counts records carrying data in the parsed message's unknown-field set (an out-of-range proto2 closed enum or an undeclared field). The **structural oracle** (added in v2) is a record-independent, bind-time check that flags *declared* proto2 extensions ptars drops from the Arrow schema — the per-record probe's blind spot, since a declared extension reads into `Extensions[...]` with an empty unknown set. The two cover disjoint loss classes and surface together (a `dropped_extensions` list alongside the per-record counts); under *error* a structural drop fails fast at bind, before any record is read. (A group field is neither case: ptars emits a column for it but fails to decode populated group bytes — a decode fault surfaced through the scan's fault channel, not a silent drop.)

## Forensics / wire-level analysis

Phase-2 capabilities for proto bytes whose schema relationship is uncertain — "I have some schemas and some bytes and need to know how they relate." Schema-set-aware and corpus-level, distinct from single-blob reverse engineering.

### Schema match
The process of ranking candidate schema versions by how plausibly each produced a serialized proto message that carries no co-located schema. Each candidate is resolved to its own Isolated descriptor pool, the message is parsed under it, and the candidate is scored on parse outcome, Modeled-byte fraction, and how tightly the message exercises the candidate's declared fields (declared-field coverage — what separates an exact producer from a superset schema that also models every byte). Output is ranked hypotheses with evidence, never an assertion that a candidate *is* the schema. Works one message at a time.

### Modeled-byte fraction
The share of a record's bytes that a candidate descriptor accounts for — the complement of Unmodeled wire data (`1 − unmodeled / total`). A higher fraction means the candidate explains more of the data; it is the primary fit signal for Schema match.

### No clean match
The verdict Schema match returns when every candidate leaves significant data unmodeled (no candidate's residual falls below the threshold). It exists so the data drifting from *all* known schemas is reported honestly, rather than the least-bad candidate being presented as the answer.

### Multiple clean matches
The verdict Schema match returns when two or more candidates fit the message equally well after every ranking signal (fraction, declared-field coverage, and the wire-walker tie-break) — reported honestly as ambiguous rather than crowning one by input order. The complement of No clean match: there, nothing fits; here, several fit indistinguishably.

### Wire-format field walker
A schema-less reader that decodes `(field number, wire type)` observations directly from raw record bytes, independent of any descriptor. It is the foundation for Drift and for breaking ties between candidates that Modeled-byte fraction alone cannot separate.

### Drift
The per-field divergence between wire data observed by the Wire-format field walker and a chosen candidate schema: an undeclared tag, a wire-type mismatch on a declared tag, a reserved tag in use, or a proto2 `required` field absent from the data. Where the Fidelity signal counts that bytes are unmodeled, Drift names which field diverges and how.
