# Concepts

Shared domain vocabulary for this project — entities, named processes, and status concepts with project-specific meaning. Seeded with core domain vocabulary, then accretes as ce-compound and ce-compound-refresh process learnings; direct edits are fine. Glossary only, not a spec or catch-all.

> Seeded 2026-06-16 from the columnar/Parquet fidelity-signal work; covers **storage / data-at-rest**, **forensics / wire-level analysis**, and the **testing** vocabulary the audit-remediation work introduced. Other areas (schema lint, compatibility checking, the message differ) are not yet defined here.

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

## Lint

### Rule pack
A module that contributes lint rules as a unit: the built-in packs the CLI always loads, plus any user pack loaded on top of them. A pack declares which profiles each of its rules belongs to, so the resolved rule set for a run is composed across packs by profile, and multi-pack runs announce their composition.

### Buf parity
The claim that a protokit lint rule reports the same findings as the equivalent `buf lint` rule, held to a pinned buf version and checked by an in-repo harness that runs each such rule's fixtures through both tools. Parity is asserted per rule and per pinned version; a rule that intentionally diverges documents the divergence rather than claiming parity.

## Testing

### Regression pin
A test that asserts the *correct* behaviour of a defect that is confirmed but not yet fixed, marked as a strict expected-failure whose reason string leads with the finding's identifier. It fails today, keeps the suite green while the defect is live, and turns into a hard failure the day the mechanism is fixed, so a fix cannot land silently and the pin cannot rot into a permanently red test. Distinct from a version pin (a dependency or tool version held fixed) and from a presence ratchet (a meta-test that fails when a required phrase or marker disappears from the tree).
*Avoid:* xfail test, expected failure (too broad: those do not carry a finding identifier or a flip obligation)

A pin is only a pin when it names the exception it fails with; a strict expected-failure alone detects the flip to passing, not the reason for failing, so an unrelated crash before the pin's assertion would otherwise count as the pinned defect. Each pin is paired with a **pin control**: a passing sibling that builds the same construction on the path the mechanism gets right, so a broken precondition shows up as a red control rather than as a pin that never reached its assertion. A pin whose construction cannot be built on some environment is red there, never quietly expected-failed. A pin nobody can make pass is a trap, so the bar for landing one is having shown it flip under a simulated fix.

### Presence ratchet
A meta-test that fails when a required phrase, marker, or registration disappears from the tree — a guard on the *existence* of a discipline (a convention paragraph, a lint-gated path, a `raises=` on every expected-failure marker), not on its wording or its application. It starts at zero violations and refuses new ones, so it can be strict from its first commit without an allowlist. Distinct from a Regression pin, which guards a specific defect's fix.

### Sibling blindness
The failure mode where a fix lands at the call site that reported the defect while structurally identical sites elsewhere stay broken, and review does not notice because the reported case is now green. The defence is to derive the set of sites from the code (grep the ingredient, not the symptom) rather than from the list someone wrote down, and to fix every site in one change.

### Runtime backend
Which implementation of the protobuf Python library executes at test time: upb, the compiled default, or pure-Python, selected by environment variable before the library is imported. The two differ in how a descriptor pool resolves cross-file references (pure-Python only through a file's declared dependencies; upb against the whole pool) and in what registering a file returns, so a suite green under one has expressed one backend's opinion. Distinct from the Compile backend, which produces descriptors rather than executing them.

### Compile backend
Which tool turns `.proto` source into descriptors for a test or a CLI run: the optional in-process compiler, or the system `protoc` it falls back to. The two agree on descriptor semantics but not on byte-level details such as source-code-info layout, so comparisons across them are made on meaning, not bytes. Distinct from the Runtime backend.

## Flagged ambiguities

- "backend" had been used for both the protobuf Runtime backend (upb / pure-Python) and the Compile backend (in-process compiler / system `protoc`) — these are distinct axes, and a finding or CI cell names which one it is about.
