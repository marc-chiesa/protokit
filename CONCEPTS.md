# Concepts

Shared domain vocabulary for this project — entities, named processes, and status concepts with project-specific meaning. Seeded with core domain vocabulary, then accretes as ce-compound and ce-compound-refresh process learnings; direct edits are fine. Glossary only, not a spec or catch-all.

> Seeded 2026-06-16 from the columnar/Parquet fidelity-signal work; covers **storage / data-at-rest**, **forensics / wire-level analysis**, the **testing** vocabulary the audit-remediation work introduced, and the **package-structure** vocabulary its single-owner seams introduced. Other areas (schema lint, compatibility checking, the message differ) are not yet defined here.

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
A module that contributes rules as a unit, supplied by a user or shipped built-in, and executed inside the tool's own process. Both the lint surface and the compatibility surface take them, and a given pack belongs to one surface — it cannot be loaded into both. On the lint surface a pack declares which profiles each of its rules belongs to, so the resolved rule set for a run is composed across packs by profile, and multi-pack runs announce their composition.

The two surfaces diverge on what loading a pack twice, or two packs claiming one rule id, does. Lint fails loudly on a cross-pack id collision and its load is idempotent per module, so a repeated load short-circuits. The compatibility surface allows both: a duplicate id runs both rules and attributes their findings to the same id, and a repeated load registers the pack's rules a second time. A pack is also arbitrary third-party code the tool runs, which makes every point where it executes part of a trust boundary rather than an implementation detail.

### Buf parity
The claim that a protokit lint rule reports the same findings as the equivalent `buf lint` rule, held to a pinned buf version and checked by an in-repo harness that runs each such rule's fixtures through both tools. Parity is asserted per rule and per pinned version; a rule that intentionally diverges documents the divergence rather than claiming parity.

## Testing

### Regression pin
A test that asserts the *correct* behaviour of a defect that is confirmed but not yet fixed, marked as a strict expected-failure whose reason string leads with the finding's identifier. It fails today, keeps the suite green while the defect is live, and turns into a hard failure the day the mechanism is fixed, so a fix cannot land silently and the pin cannot rot into a permanently red test. Distinct from a version pin (a dependency or tool version held fixed) and from a presence ratchet (a meta-test that fails when a required phrase or marker disappears from the tree).
*Avoid:* xfail test, expected failure (too broad: those do not carry a finding identifier or a flip obligation)

A pin is only a pin when it names the exception it fails with; a strict expected-failure alone detects the flip to passing, not the reason for failing, so an unrelated crash before the pin's assertion would otherwise count as the pinned defect. Each pin is paired with a **pin control**: a passing sibling that builds the same construction on the path the mechanism gets right, so a broken precondition shows up as a red control rather than as a pin that never reached its assertion. A pin whose construction cannot be built on some environment is red there, never quietly expected-failed. A pin nobody can make pass is a trap, so the bar for landing one is having shown it flip under a simulated fix.

### Presence ratchet
A meta-test that fails when a required phrase, marker, registration, or property of a checked-in configuration disappears from the tree — a guard on the *existence* of a discipline (a convention paragraph, a lint-gated path, a `raises=` on every expected-failure marker, a CI job that runs the whole suite under a given backend), not on its wording or its application. It starts at zero violations and refuses new ones, so it can be strict from its first commit without an allowlist. Distinct from a Regression pin, which guards a specific defect's fix.

A ratchet over a configuration must model every way the guarded thing can look present while doing something else — a run step that filters, a step that never executes, an override that changes the setting the ratchet checked — because a guard that only looks for the expected text passes while guarding nothing. Each property it asserts is proven by a self-test that injects the violation. When the ratchet derives its answer from source rather than matching text, deleting a rule is too coarse a violation to inject: the way such a rule is proven is to write the plausible wrong version of it and require a self-test to fail, because a wrong rule that is still present passes a suite that only checks the rule exists.

### Known-failure inventory
A committed list of tests expected to fail under one Runtime backend, each entry naming the audit finding it traces to and the exception it fails with, applied at collection time as a strict expected-failure so that backend's CI cell is red only on a new failure, on a fix (the entry starts passing and is deleted), on a failure that changed shape, or on a stale entry. Distinct from a Regression pin (one test, marked in source, kept until its fix) and from a Presence ratchet (guards that a discipline exists, not which tests fail).
*Avoid:* expected-failure list, xfail list (too broad: those carry no finding identifier, no exception, and no record of the runtime they were measured on)

An inventory is harvested from the cell's own run, never from a local measurement, and records the runtime it was measured against; a runtime change is a re-harvest, not a reinterpretation. Its entries govern ahead of a test's own pin, so a fixed defect surfaces as a mismatch on the entry rather than a silent pass. A test whose premise holds only on one backend is a permanent backend skip, not an entry, because no fix can flip it. The inventory's target state is empty, and promoting the cell to a required check waits for that.

### Sibling blindness
The failure mode where a fix lands at the call site that reported the defect while structurally identical sites elsewhere stay broken, and review does not notice because the reported case is now green. The defence is to derive the set of sites from the code (grep the ingredient, not the symptom) rather than from the list someone wrote down, and to fix every site in one change.

A site the derivation finds and then excuses on a written claim that some input kind cannot reach it counts as unfixed until the claim is tested: the claim is an assumption wherever it is written, and the test either builds the excluded input and proves the site handles it or the site is migrated with its siblings.

The derivation can also fail by never running. A defect report names a symptom, and a symptom names one site; taking the report's wording as the site list produces a fix that is complete against the words and partial against the code. The tell is prose that counts — a comment or docstring asserting it covered "both" or "every" site — because an exhaustive count inside one function reads like an exhaustive count of the surface and then blocks the next reader from re-deriving it. Such a claim names the scope it counted over, and a count that surprises the person deriving it is the finding rather than a detail.

### Mutation proof
A check that a specific test is not vacuous: one anchor in the code the test guards is replaced with a plausible wrong version, the test is run, and the test must fail — a test that stays green with its guarded code broken proves nothing. Distinct from a Regression pin, which asserts correct behaviour for a defect not yet fixed; a mutation proof interrogates an already-passing test's power to catch a defect that does not yet exist.
*Avoid:* vacuity check, vacuity gate, mutation test (the last is too broad: this is one anchor and one target, not a mutation-testing campaign)

A proof is a verdict only when the target passed on the unmutated code first and then failed for the mutation, not for a setup problem — a target that never ran, collected nothing, or was already red proves nothing either way. The proof's exit is the evidence, so it must be run through the shared harness, which also keeps the interpreter from executing stale bytecode for the mutated or restored source. A proof of a predicate that only one Runtime backend exercises is legitimately vacuous under the other backend, so it is run under the backend the predicate is for; a vacuous verdict there is a finding about the test, not about the harness.

A proof is also evidence about the tree it ran against, so a fix can silently disarm a neighbouring test that shares the changed path: a test needing an exception to escape stops being able to fail once something upstream starts catching it, and nothing turns red to say so. After a fix lands, the proof is re-run for every test on that path, not only for the test the fix was written with. A test that depends on an exception escaping names in its own docstring which exception and why the code lets it through, since one that escapes only because of a bug is a lever the bug's fix removes.

### Recorded rendering
A meta-test that stores a program's exact rendered output for a fixed set of inputs and fails on any difference, used where the property under test is whether free-form text tells the reader the truth — a question no predicate over that text can decide, because a sentence can always satisfy the predicate and still say the opposite. Distinct from a Presence ratchet, which asserts a required phrase is still present rather than that a whole rendering is unchanged, and from a Regression pin, which asserts one defect's correct behaviour.
*Avoid:* golden test, snapshot test (too broad: neither implies the paired control, the deliberate regeneration step, or the predicates kept alongside)

Each input that carries the condition under test is recorded beside its control — the same input with only that condition removed — so a renderer that prints the same sentence for both shows up as a change rather than as agreement. Recording earns its place only where the rendering is deterministic and the corpus stays small enough that a reviewer reads the diff, because the human reading that diff is the mechanism; normalising nondeterminism into the recording smuggles a predicate back in, with the same blind spots and none of the visibility. Regeneration is a separate named step, never a test flag, since a recording regenerated reflexively guards nothing. The predicates it supersedes are kept alongside it, because a recording reports *that* output changed and never *why* a line is wrong. Its coverage is exactly its fixtures' coverage, so a case no fixture builds is invisible to it.

### Runtime backend
Which implementation of the protobuf Python library executes at test time: upb, the compiled default, or pure-Python, selected by environment variable before the library is imported. The two differ in how a descriptor pool resolves cross-file references (pure-Python only through a file's declared dependencies; upb against the whole pool), in what registering a file returns, and in what a descriptor object is: under pure-Python a long-lived Python object, under upb a wrapper created on demand and released when unreferenced, so its identity is stable only while something holds it, it cannot be weakly referenced, and holding a file's descriptor holds its whole pool. A suite green under one has expressed one backend's opinion. Distinct from the Compile backend, which produces descriptors rather than executing them.

### Compile backend
Which tool turns `.proto` source into descriptors for a test or a CLI run: the optional in-process compiler, or the system `protoc` it falls back to. The two agree on descriptor semantics but not on byte-level details such as source-code-info layout, so comparisons across them are made on meaning, not bytes. Distinct from the Runtime backend.

## Package structure

### Seam
A module that owns one recurring decision for the whole package — how a message's fields are enumerated, how a custom option is resolved, how a result type is frozen — so that the next defect in that class is fixed once, at the owner, rather than at each call site that happens to report it. What makes it a seam rather than a convention is that reaching around it fails: a seam lands together with a guard test that fails when a call site bypasses the owner. A call site that re-derives the owner's answer and happens to agree has reached around it without the guard noticing, so the guard exercises every way the owner can decide rather than one case per call site.

A seam sits at layer 0: it imports nothing from the rest of the package at any scope, which is what makes it safe for every layer above to import. Only a typing-guarded import is exempt, since that never executes. Depending on nothing above it, rather than deferring a dependency into a function body, is what keeps a seam from participating in an import cycle — a deferred import is the sanctioned repair for a cycle that already exists, not a way to give a seam a dependency it should not have.

## Flagged ambiguities

- "backend" had been used for both the protobuf Runtime backend (upb / pure-Python) and the Compile backend (in-process compiler / system `protoc`) — these are distinct axes, and a finding or CI cell names which one it is about.
- "ratchet" had been used for both a Presence ratchet, which starts at zero violations and refuses new ones, and a coverage allowlist, which names the paths a tool runs over and grows as they are cleaned — these fail in opposite directions. A presence ratchet is loud about anything new; an allowlist is silent about anything unlisted, so a file nobody added is indistinguishable from a file with nothing wrong. Say which is meant, and for an allowlist prefer gating a directory over listing its files one by one.
