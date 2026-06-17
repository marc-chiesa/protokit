---
title: "Detecting unmodeled wire data in proto-to-columnar conversion via a DiscardUnknownFields byte-delta probe (and its declared-extension blind spot)"
date: 2026-06-16
category: docs/solutions/design-patterns
module: protokit.storage
problem_type: design_pattern
component: tooling
severity: medium
applies_when:
  - "Converting parsed protobuf messages to Arrow/Parquet via a schema-driven encoder (e.g. ptars) that silently drops wire data the descriptor does not model"
  - "You need a per-record signal that the columnar output is lossy relative to the wire bytes, without changing the conversion itself"
  - "Messages may carry proto2 out-of-range closed-enum values or undeclared unknown/extension fields"
  - "Deciding whether a DiscardUnknownFields + ByteSize delta is a sufficient completeness check (it is NOT — declared extensions and group fields are a blind spot)"
  - "Reasoning about why a declared proto2 extension still drops its column despite an empty unknown-field set"
tags:
  - proto-to-arrow
  - columnar
  - parquet
  - ptars
  - unknown-fields
  - proto2-extensions
  - fidelity-signal
---

# Detecting unmodeled wire data in proto-to-columnar conversion via a DiscardUnknownFields byte-delta probe (and its declared-extension blind spot)

## Context

protokit's columnar sink (`src/protokit/storage/_columnar.py`) converts a stream of protobuf messages to Apache Arrow / Parquet through the ptars backend, which is **descriptor-driven**: ptars builds a fixed Arrow schema from the message's `DESCRIPTOR` and emits only columns the descriptor models. Any wire data the descriptor *cannot* model is dropped from the columnar output — silently. A protobuf consumer reading the same bytes through the runtime would still see that data (in the unknown-field set, or as a raw out-of-range value), so the Parquet diverges from "what protobuf would show" with no error and no log line.

The classic cause is **schema drift between writer and reader**: a producer serialized with a richer `.proto` than the reader's compiled descriptor — a new field, a closed-enum value the reader's enum doesn't list, an extension the reader didn't compile. The bytes are well-formed and decode cleanly; the descriptor just doesn't account for all of them.

The goal of this pattern is to make that silent fidelity loss **visible** — to surface a count of records carrying unmodeled wire data and the total such bytes — *without changing the conversion*. The detector is a pure-protobuf side-channel that runs alongside ptars, not a modification to it. That is what makes a columnar go/no-go honest about real data: it can report "this conversion dropped N bytes the descriptor didn't model" instead of producing a confidently-wrong Parquet.

## Guidance

**The probe — measure unmodeled bytes via a discard-and-diff:**

```python
def _unmodeled_byte_delta(message: Message) -> int | None:
    try:
        before: int = message.ByteSize()
        clone = type(message)()
        clone.CopyFrom(message)
        clone.DiscardUnknownFields()
        after: int = clone.ByteSize()
        return before - after
    except EncodeError:
        return None
```

Read the serialized size, clone via `CopyFrom`, discard the clone's unknown-field set, re-measure. The **delta is exactly the wire bytes the descriptor does not model.** Properties that make this work:

- **Pure protobuf.** No ptars, no pyarrow. The probe runs in the core environment with no optional extra, and is unit-tested with zero `importorskip`.
- **Recursive by construction.** `DiscardUnknownFields()` clears the *entire* message tree — submessages, repeated elements, and map-entry value submessages — so an unknown field buried inside a nested message or a `map<string, Inner>` value is caught.
- **`None` means "cannot measure," not zero.** `ByteSize()` raises `EncodeError` on a proto2 message missing a required field. Return `None` there rather than letting it escape; the encoder rejects such a record during conversion anyway, so deferring is correct. Treat `None` as "skip" — note that `if delta:` is false for both `None` and `0`.

**Why the proxy is faithful (the causal link):** the *same* out-of-range value the descriptor can't model is what BOTH (a) the protobuf runtime relegates to the parsed message's unknown-field set — where the probe measures it — AND (b) the encoder surfaces in the column as the actual divergence. They share one cause, so a non-empty unknown-field set is exactly the divergence condition. The detector reads the parsed `Message`; the converter reads a re-serialization; they agree because the cause is upstream of both.

**Wire a policy on top of the probe** (here, `Fidelity = Literal["ignore", "warn", "error"]`): `ignore` skips the per-record probe (a measured-`False` report, counts `0` by convention); `warn` measures and surfaces the count, writing the file regardless; `error` raises and discards the partial file. Distinguish a *measured zero* from *not measured* with an explicit flag — never let `0` ambiguously mean both.

## Why This Matters

**The signal is a proxy, and a proxy has a domain of validity — naming its exact boundary is the load-bearing part.** A naive reading ("non-empty unknown-field set <=> the encoder dropped a column") is wrong in two directions, and both directions are real protobuf semantics, not edge-case trivia.

**1. The declared-extension / group blind spot (false negative — the dangerous one).** A *declared* proto2 extension is read into `Extensions[...]` with an **empty** unknown-field set — yet the encoder still drops the column (it isn't a regular descriptor field). The probe is structurally blind to it:

```python
# proto2 Base with `extensions 100 to 200` and a declared ext_val #100:
m.Extensions[ext_field] = 42
reparsed.ParseFromString(m.SerializeToString())
assert reparsed.Extensions[ext_field] == 42       # data is present, fully modeled
assert _unmodeled_byte_delta(reparsed) == 0       # ...but the probe is SILENT
```

This is the **"forbidden quadrant": descriptor-modeled, encoder-dropped, empty unknown set, signal silent.** It is not exotic — it's the common GTFS-RT / NYCT setup. The painful inversion: **compiling the vendor `.proto` to read the extensions moves the data OUT of the unknown set and *silences* the detector** on the very fields most likely to be lost. An unknown-field check is therefore **NOT a complete fidelity oracle** — it catches undeclared drift, not declared-but-uncolumnarized fields. Group fields are the same class.

**2. The proto2/proto3 enum asymmetry (the signal self-selects correctly).** A proto2 **closed** enum out-of-range value is relegated to the unknown-field set (`HasField` -> `False`, accessor returns the default), so the probe fires; the encoder surfaces the raw int in the column -> genuine divergence, correctly flagged. A proto3 **open** enum keeps the value *as the field value* (not in unknown fields), so the probe stays silent — and that is right: protobuf and the encoder *agree* (both show `8`), so there is no divergence to report. The probe needs no syntax switch; the runtime's own open/closed semantics make it self-select for exactly the proto2 case where divergence occurs.

**3. The byte-stream seam (why an end-to-end test is mandatory).** ptars re-serializes each message with `SerializeToString()` and re-parses it in Rust. So the detector (on the Python `Message`) and the converter (on a re-serialization) read **different byte streams.** The proxy holds only because `SerializeToString()` round-trips the unknown-field set — an assumption about the protobuf runtime, not a guarantee of this code. Pin it with an **end-to-end test** that feeds raw bytes through the real conversion and asserts the column disposition matches the signal's classification. Without it, a runtime change to unknown-field round-tripping would silently desync the detector from the converter.

The deeper lesson: **a side-channel detector that observes a different artifact than the thing it reasons about is only as trustworthy as the causal link between them — and that link has a stated boundary you must encode in tests and docstrings, or future readers will over-trust the signal.**

## When to Apply

- **Schema-driven conversions where the schema is narrower than the wire format** — protobuf -> Arrow/Parquet, but also any "compile a fixed schema, project the data through it" pipeline (Avro, Thrift, ORC) where source records can carry fields the target schema omits.
- **When silent fidelity loss is the failure mode** — the conversion succeeds, the output looks complete, but a consumer of the *source* format would see data the consumer of the *target* format won't. Make it visible at conversion time, not downstream.
- **When you can find a causally-linked proxy in a cheaper representation.** Here: the parsed message's unknown-field set, measurable in pure protobuf, sharing a cause with the encoder's column drops. Look for an artifact already produced by the runtime that is downstream of the *same* cause as the divergence you care about.

**Do NOT rely on it as a complete oracle when:**

- **Declared extensions or group fields are in play** (GTFS-RT, legacy proto2). These are modeled-but-dropped and invisible to an unknown-field probe — you need a separate descriptor-vs-encoder-schema diff for those.
- **You haven't pinned the byte-stream seam** with an end-to-end test through the real converter. The proxy's faithfulness depends on a runtime round-trip property that your test, not your hope, must verify.
- **The probe can't measure** (uninitialized proto2 messages -> `EncodeError` -> `None`). Treat "cannot measure" as a third state, never as zero.

## Examples

Empirical anchors (verified 2026-06-15/16 on the upb runtime / ptars 0.0.17; each is a test in `tests/storage/test_columnar_fidelity.py`):

| Case | Wire | Runtime result | byte-delta | encoder column |
|---|---|---|---|---|
| proto2 closed enum, out-of-range | `08 08` | `HasField('c')==False`; unknown entry (field#1, varint, 8) | **2** | surfaces raw int `8` (divergence — flagged) |
| proto3 open enum, same bytes | `08 08` | `m.c == 8` (kept as field value) | **0** | shows `8` — agrees, no divergence |
| nested undeclared field | inner `extra` field | reachable via submessage | **> 0** (recursion fires) | dropped |
| map-entry value undeclared field | `map<string,Inner>` value `extra` | reachable via map-entry value submessage | **> 0** (recursion fires) | dropped |
| declared proto2 extension #100 (range 100-200, value 42) | reparse -> `Extensions[...]==42` | **empty** unknown set | **0 (BLIND)** | encoder schema `['id']` — column dropped, signal silent |
| clean message | within descriptor | no unknown fields | **0** | full fidelity (no false positive) |
| proto2 missing required field | `10 05` (field 2 set, required field 1 unset) | `IsInitialized()==False`; `ByteSize` raises `EncodeError` | **None** ("cannot measure") | encoder rejects the record anyway |

The declared-extension counterexample is the single most important case to internalize: data is present in `Extensions[...]`, fully readable, yet the byte-delta is `0`. Reading the extension is exactly what silences the detector. An unknown-field check is a strong, cheap signal for *undeclared* drift — and not an oracle for everything the encoder drops.

## Related

- [Faithful proto-to-Arrow mapping: presence-class structure, Arrow-native values](proto-to-arrow-faithful-mapping-presence-structure-arrow-native-values.md) — the two *in-band* fidelity axes (presence structure + Arrow-native value encoding) plus the three-layer disposal guarantee. This learning adds a **third, out-of-band fidelity channel** (the unknown-field signal): wire data the descriptor never models, which the two in-band axes do not cover.
- [Recursive proto schemas segfault ptars during Arrow schema build](../security-issues/recursive-proto-schema-segfaults-ptars-arrow-build.md) — the "raise before C" / descriptor pre-flight precedent this signal's typed error mirrors: a Python-side guard that turns a closed C-extension failure into a catchable, taxonomy-respecting error around the ptars call. Its "measure a pinned closed dependency; don't trust documentation about it" rule is the same discipline behind this probe's empirical anchors.
- [ptars over protarrow for proto-to-Arrow on isolated descriptor pools](../tooling-decisions/ptars-over-protarrow-proto-to-arrow-isolated-descriptor-pools.md) — records that ptars parses wire bytes *in Rust* over handed descriptors; that Rust/wire boundary is the root of the byte-stream seam and is why a schema-modeled-vs-wire-present divergence exists to detect.
- [Tolerant-iteration error taxonomy: narrow typed catch + loud completion guard](tolerant-iteration-error-taxonomy-narrow-catch-loud-completion-guard-2026-05-30.md) — the `protokit.storage` fail-loud / never-silent-partial taxonomy the strict-mode fidelity error slots into.
- **Origin:** issue #25 (columnar real-data go/no-go) surfaced this during real-data validation alongside the recursion fix; shipped in PR #40.
