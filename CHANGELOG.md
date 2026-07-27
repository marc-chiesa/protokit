# Changelog

All notable changes to `protokit` are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/).

> **Pre-1.0 stability disclaimer.** `protokit` is pre-1.0. Minor-version
> releases may include breaking changes to public Python APIs and
> machine output formats (JSON, JUnit, SARIF). Breaking changes are
> flagged in `BREAKING`-prefixed section headings below (formats vary
> across the changelog: `### Changed — BREAKING`, `### BREAKING (D5 U3 ...)`,
> etc.). Consumers should pin to a specific minor version (e.g.,
> `protokit~=0.5.0`) until 1.0 ships. The 1.0 release will **define
> the stable public surface** and commit to semver compatibility for
> that surface.

## Unreleased

### Added
- **`protokit forensics match` — schema-less single-message schema identification
  (Phase 2, increment 1).** A new read-only `forensics` command namespace. Given
  one serialized proto message that carries no co-located schema and a set of
  candidate `.proto` (or `FileDescriptorSet`) versions, it ranks which version
  most plausibly produced the message and reports an honest verdict —
  `clean_winner`, `multiple_clean_matches`, or `no_clean_match` — never asserting
  that a candidate *is* the schema. Fit combines parse outcome, the modeled-byte
  fraction (`1 − unmodeled / total`), and declared-field coverage, so an exact
  producer outranks a superset that also models every byte. Each candidate
  resolves to its own isolated descriptor pool. `--format human | json` (the JSON
  carries a `schema_version`); `--max-message-bytes` caps the input before it is
  read; `--max-residual-bytes` and `--tie-margin` tune the verdict. New public
  API `protokit.forensics.match` with `Candidate` / `CandidateFit` /
  `MatchReport`, and a `ForensicsError` / `MessageTooLargeError` family.
- **`protokit forensics drift` + a schema-less wire-format field walker (Phase 2,
  increment 2).** A net-new walker decodes the top-level `(field_number,
  wire_type)` observations from raw, untrusted message bytes with no descriptor —
  rejecting an over-long varint or a length prefix past the buffer, flagging
  groups without recursing, and capping work to the top level. `forensics drift`
  reconciles those observations against one chosen candidate schema and reports
  per-field divergences: an undeclared tag, a wire-type mismatch on a declared
  field (a packable repeated scalar accepts both packed and unpacked), a reserved
  tag in use, or a proto2 declared `required` field absent. A populated declared
  proto2 extension counts as declared. The same reconciliation powers a `match`
  tie-break that re-orders a near-tied top group by per-field wire compatibility.
  New public API `protokit.forensics.drift` with `DriftReport` / `FieldDivergence`.
- **New built-in compat rule `enum_value_number_changed` (WIRE / BOTH),
  bringing the built-in set to 18.** An enum value that keeps its name but is
  assigned a new number fell through every existing enum rule — the two
  name-matched rules see the name on both sides, and `enum_number_reused` is
  number-keyed so it needs the number present on both sides. `E {A = 1}` →
  `E {A = 2}` was therefore reported fully compatible while being a
  bidirectional wire break: old bytes carrying `1` name nothing under the new
  schema, and new producers emit `2` the old schema cannot name. The rule
  compares each surviving name against its set of numbers, so `allow_alias`
  enums only fire when a name's own number genuinely moved.

### Changed — BREAKING
- **Enum renumbers now fail `protokit compat` at every profile.** Schema pairs
  that renumber an enum value under an unchanged name previously reported
  `COMPATIBLE` with zero findings; they now emit an `enum_value_number_changed`
  WIRE / BOTH finding, so `compat` exits non-zero even under the narrowest
  `WIRE` profile. This is a true-positive that was always missing — but CI
  pipelines pinned to the old behaviour will start failing. Suppress per path
  with `SchemaChecker.ignore(...)` if a renumber is deliberate.

### Changed
- **Internal: the unmodeled-byte fidelity measurement moved to a shared seam**
  (`protokit.storage._fidelity_probe.unmodeled_byte_delta`) so both the columnar
  sink and `forensics match` import one named function. Behavior-preserving —
  `protokit.storage._columnar._unmodeled_byte_delta` still resolves it.

## 0.14.0 — 2026-06-24

### Added
- **A structural fidelity oracle for declared proto2 extensions (columnar v2).**
  The columnar path now detects, once per conversion at bind time, declared
  proto2 extensions `ptars` drops from the Arrow schema — a loss the v1
  per-record probe is structurally blind to (a declared extension reads into
  `Extensions[...]` with an empty unknown-field set). It rides the existing
  `--fidelity ignore | warn | error` knob and is surfaced on `FidelityReport`
  through a new `dropped_extensions` tuple. Under `error` it fails fast at bind —
  before any record is read or the writer opens — so a structural drop pre-empts
  both decode faults and the per-record signal; the CLI prints a distinct stderr
  line for it. `FidelityReport.dropped_extensions`,
  `FidelityError.dropped_extensions`, and a composed `FidelityError.summary`
  (a one-line statement of which signal(s) fired) are additive (existing
  construction is unchanged).
- **`to_arrow_batches` gains a `fidelity=` parameter and surfaces the report.**
  The batches API now carries the same fidelity signal as `to_parquet`: it
  returns an iterable result exposing `.report` (a `FidelityReport`) after full
  consumption. The structural signal fails fast on the first `next()` under
  `error`; the per-record signal is reported, never raised mid-stream. Reading
  `.report` before exhaustion or after a mid-stream abort raises `RuntimeError`.
  The default is `warn` (matching `to_parquet`); pass `fidelity='ignore'` to opt
  out of all measurement.

### Changed — BREAKING
- **`to_arrow_batches` returns an `_ArrowBatchStream` wrapper, not a bare
  generator.** The common patterns stay runtime-compatible — `for batch in ...`,
  `list(...)`, `next(...)`, and `.close()` all work unchanged, and the wrapper is
  a valid `Iterator[pa.RecordBatch]`. But the returned value is no longer a
  generator and its annotated return type changed, so code that depends on
  generator identity — `inspect.isgenerator(...)`, `isinstance(..., GeneratorType)`,
  or the generator-only `.send()` / `.throw()` — breaks.
- **`to_arrow_batches` now measures fidelity by default.** v0.13.0 had no
  `fidelity` parameter and did no measurement; callers that omit `fidelity=` now
  run the per-record probe and the bind-time structural oracle on iteration —
  added per-record cost (the same `ByteSize`-based probe the Parquet path
  benchmarks at ~1.63×) and, under the `warn` default, a surfaced `.report`
  rather than silence. Pass `fidelity='ignore'` to restore the v0.13.0
  no-measurement behaviour.

### Fixed
- **Corrected the group-field framing in the columnar fidelity docs.** A proto2
  group is *not* a silent structural drop (the v1 learnings called it the "same
  class" as a declared extension): `ptars` emits a column for it, and a
  *populated* group raises a decode `ValueError` instead — a separate,
  pre-existing decode-robustness gap. The structural oracle covers declared
  extensions only.

## 0.13.0 — 2026-06-17

### Added
- **The columnar/Parquet path rejects recursive proto schemas up front.** A
  message type that references itself — directly, mutually, or through
  map / group / oneof message fields — has no finite Arrow/Parquet
  representation. A descriptor pre-flight now detects the cycle before the
  conversion backend is invoked and raises a typed, catchable error naming the
  cycle: `RecursiveSchemaError` for user-authored recursion and
  `UnsupportedWktError` for the recursive `google.protobuf.Struct`/`Value`/
  `ListValue` family (`protokit.storage` exports both). Non-recursive
  well-known types (`Timestamp`, `Any`, `Duration`, `FieldMask`, wrappers) are
  unaffected and convert as before.
- **A columnar/Parquet fidelity signal surfaces unmodeled wire data.** The
  conversion now detects, per record, when a message carried wire data the
  supplied descriptor does not model — a proto2 out-of-range closed-enum value
  (which a protobuf reader relegates to unknown fields but `ptars` surfaces as a
  raw int) or an undeclared unknown/extension field (dropped from the output).
  A graduated `--fidelity` policy (`ignore` | `warn` | `error`, default `warn`)
  governs it, exposed on the CLI and as the `fidelity=` keyword on `to_parquet`:
  `warn` writes the file and prints a one-line count, `error` fails the
  conversion (`exit 2`, all-or-nothing, nothing written), `ignore` skips the
  per-record probe. `protokit.storage` exports the new `FidelityReport` result
  and `FidelityError`. Declared proto2 extensions and group fields are a
  documented blind spot — the unknown-field signal does not see them.

### Changed — BREAKING
- **`to_parquet` now returns a `FidelityReport`, not a bare `int`.** The row
  count moves to `report.rows`; the report also carries the fidelity signal
  (`measured`, `unmodeled_records`, `unmodeled_bytes`). Callers that used the
  former `int` return must read `.rows`. `to_arrow_batches` is unchanged.

### Changed
- **Bumped the buf parity reference from `v1.69.0` to `v1.70.0` (#16).** The
  pinned BASIC-rule parity baseline (`_BUF_PARITY_PIN`, surfaced in
  `protokit lint --version` and exercised by the CI parity job) now tracks
  buf v1.70.0. v1.70.0 changed only the `PROTOVALIDATE` lint rule, which is
  outside protokit's 26-rule BASIC parity surface — no rule mappings,
  fixtures, or divergence annotations change.

### Fixed
- **Recursive proto schemas no longer crash the columnar/Parquet path.**
  Converting a self-referential message type — or one embedding the recursive
  well-known types `google.protobuf.Struct`/`Value`/`ListValue` — previously
  segfaulted the whole process inside the ptars backend (exit 139), bypassing
  every Python guard and orphaning the `.partial` temp file. The new
  descriptor pre-flight (above) turns this into a clean `exit 2` with no
  partial file left behind, restoring the documented all-or-nothing contract.
  Not a breaking change: input that crashed now raises a catchable error.

## 0.12.0 — 2026-06-10

### Added
- **`protokit storage scan --format parquet` — typed Parquet output from the
  CLI (#24).** `scan` gains `parquet` as a `--format` value with a required
  `-o`/`--output PATH`, converting records straight proto→Arrow→Parquet
  through the shipped columnar path (the optional `protokit[parquet]` extra)
  with no JSON intermediate. Full-record only: every field of the resolved
  type maps to a column from the descriptor-derived schema; an empty result
  still writes a valid zero-row file with the full schema; `--where` composes
  (only matching records are converted). The output contract is
  all-or-nothing with an atomic publish: conversion writes a uniquely named
  dot-prefixed `.partial` sibling temp and renames it onto `-o` only after a
  complete, fault-free scan — on any fault the command exits 2 reporting the
  fault count and first fault location, no output file is left behind, and a
  pre-existing `-o` file is preserved (overwritten only by a complete
  result). Misuse is rejected up front (exit 2, before any record is read):
  `--format parquet` without `-o`, `-o` without parquet, `-o -`,
  `--on-error skip|warn` (a tolerant mode could silently write a file that
  under-represents the input), `--fields` / `--explicit-defaults`
  (full-record only; the JSON-only guard now rejects every non-JSON format),
  and env-sourced `PROTOKIT_FORMAT=parquet` (file-writing output must be
  explicit on the command line; `head` keeps the two-value format choice,
  `count` has none; `-o` colliding with the input or schema file is rejected
  too — the publish step would otherwise replace the just-read input).
  Success prints one stderr summary (`wrote N rows to PATH`) and keeps stdout
  clean. Parquet values are Arrow-native by design — bytes → binary, enums →
  int32, timestamps at microsecond resolution — diverging from the JSON
  view's encodings. Library change in support: `IncompleteScanError` now
  carries the collected `FrameError`s verbatim (`faults`, alongside the
  backward-compatible `fault_count`) so fault locations are reportable.

### Changed — BREAKING
- **`IncompleteScanError` constructor signature.**
  `IncompleteScanError(fault_count: int)` is replaced by
  `IncompleteScanError(faults: tuple[FrameError, ...])` — the error now
  carries the collected faults verbatim. Consumers that construct the
  exception directly (e.g. test doubles) must update the call site. Read-only
  consumers are unaffected: catching the error and reading `fault_count`
  (preserved as `len(faults)`) and the message shape work unchanged.

## 0.11.0 — 2026-06-09

### Added
- **Expressive message matchers + comparison parity (`protokit.message`).** A
  framework-agnostic test-assertion layer over the differ: `proto_match(actual,
  expected, *, partial=, as_set=, ignore=, presence=, approx=)` (single-call)
  and `expect_proto(expected).partially().as_set("items").ignoring(pred)
  .approximately(...).matches(actual)` (fluent) raise `AssertionError` with the
  existing per-field diff on mismatch. The same policy is exposed as a
  `hamcrest.BaseMatcher` via `equals_proto(...)` behind a new optional
  `protokit[hamcrest]` extra (used as `assert_that(actual, equals_proto(...))`),
  and as a `proto_matcher` pytest fixture; the bare `assert msg1 == msg2`
  rich-diff rendering gains presentation-only config. Backing the matcher, the
  `MessageDifferencer` engine gains five opt-in, additive capabilities, all
  targeted by one unified field selector (a dotted path **or** a
  `(FieldDescriptor, path)` predicate): partial / sub-shape scope
  (`set_partial()` — only fields present on the expected side are compared);
  keyless set comparison for repeated fields (`treat_as_set(selector)` —
  order-independent multiset, distinct from keyed `treat_as_map`);
  predicate-based field ignore (`ignore_fields(...)` now also accepts a
  predicate); EQUAL vs EQUIVALENT presence (`set_message_field_comparison(...)`);
  and selective per-field float tolerance (`set_float_comparison(..., selector=)`
  overlay). New public surface: `proto_match`, `expect_proto`, `MatchPolicy`,
  `Approx`, `MatcherError`, `equals_proto`, `HamcrestExtraNotInstalledError`,
  `MessageFieldComparison`. The CLI matcher surface is a separate later effort.
  **Behavior note:** the default `EQUIVALENT` presence mode now treats a
  presence-bearing field set to its *default value* as equal to an unset field
  (previously a presence difference); a non-default value vs unset is unchanged.
  Opt into `MessageFieldComparison.EQUAL` for strict set-vs-unset presence.

## 0.10.0 — 2026-06-07

### Added
- **`protokit storage` field selection (`--fields`) + dense full-record JSON
  (`--explicit-defaults`) (PR2).** `protokit storage scan` / `head` (not `count`)
  gain `--fields a,b.c` — a comma-separated list of dotted field paths that emits
  a *faithful nested view* of just the named fields with **snake_case** keys (the
  keys match the paths you typed). Faithfulness is split by presence class:
  **no-presence fields** (implicit proto3 scalars, repeated, map, enum) are shown
  at their default when defaulted — so `--fields error_code` emits
  `{"error_code": 0}` rather than dropping the field — while **presence-bearing
  fields** (proto3 `optional`, `oneof` members, singular submessages) are shown
  only when actually set and are never fabricated. Selecting a whole submessage
  (`--fields header`) emits a dense-filled nested object (every no-presence
  sub-field at its default), not a sparse echo, and the same rule applies
  recursively; leaf values reuse proto's JSON type-mapping (enums by name, int64
  as string, bytes as base64). A path may name a scalar, a whole singular
  submessage, a whole repeated/map field, or a `oneof` member, but may not descend
  into repeated/map elements (rejected up front, exit 2). `--fields` composes with
  `--where` (the predicate runs on the full message first, so it may reference
  unselected fields); under `--format human` the view renders as `path: value`
  lines. A new `--explicit-defaults` flag (**JSON only**) makes a *full* record
  dense — every no-presence field filled at its default, presence-bearing fields
  still by presence — keeping **camelCase** keys as a density variant of the
  default `--format json`; under `--format human` it is a clean error (exit 2).
  The snake_case-vs-camelCase split is deliberate: `--fields` matches the dotted
  paths, `--explicit-defaults` stays byte-aligned with the plain JSON it densifies.
  `--fields` and `--explicit-defaults` are mutually exclusive (clean error, exit
  2). New public library surface: `protokit.storage.project(message, selection) ->
  dict` (the render-time projection that produces the faithful view; the
  `selection` is compiled against a message descriptor) and the typed
  `protokit.storage.FieldSelectionError`. The scan engine is unchanged —
  selection/projection is a render-layer concern.
- **`protokit storage` columnar / Parquet output (PR3).** New optional
  `protokit[parquet]` extra (Rust-backed [ptars](https://github.com/0x26res/ptars)
  + pyarrow) adds a **library-first** proto→Arrow→Parquet path that consumes the
  existing `scan()` stream and skips the proto→JSON→Parquet double-encode. Two
  public functions: `protokit.storage.to_arrow_batches(source, registry, *,
  stream_id, ...)` yields bounded Apache Arrow `RecordBatch`es (peak memory
  O(batch)), and `protokit.storage.to_parquet(source, registry, destination, *,
  stream_id, ...)` streams one row group per batch to a Parquet file. The entry
  points own scan construction (`on_error='collect'` hard-wired): a scan that hits
  any record fault fails loud and discards the partial file rather than writing a
  complete-looking Parquet over a truncated scan, and an empty result still writes
  a valid zero-row Parquet carrying the full descriptor-derived schema. v1 converts
  a single message type per pass (a record of a different type raises
  `SchemaMismatchError`); value mapping is Arrow-native (bytes→binary, enum→int,
  well-known types like `Timestamp` map correctly on the engine's isolated
  descriptor pools), `oneof` arms become independent nullable columns, and
  `Any`/`Struct` map to lossless structs. Using the API without the extra raises
  `protokit.storage.ParquetExtraNotInstalledError` (naming the install), never a
  raw `ImportError`. New typed exceptions: `ParquetExtraNotInstalledError`,
  `SchemaMismatchError`, `UnknownStreamError`, `HandlerBuildError`,
  `IncompleteScanError`. The CLI
  `--format parquet` flag is a separate later effort; the scan engine is unchanged.

## 0.9.0 — 2026-05-31

### Changed — BREAKING — message differ left/right value terminology

- Renamed `Difference.old_value`/`new_value` → `left_value`/`right_value` in the
  message differ. The two compared messages are not a before/after pair, so the
  value pair now matches the dataclass's other `left_*`/`right_*` fields, the
  rule context (`ctx.left_value`), and the CLI (`--left-*`). `old_value`/
  `new_value` remain as deprecated read-only property aliases that emit
  `UserWarning`; removed in protokit 1.0.
- **BREAKING (construction):** `Difference(old_value=..., new_value=...)` is no
  longer accepted and raises `TypeError` immediately — there is no deprecation
  window for *constructing* with the old kwargs (only *reading* the old
  attribute names is aliased). Use `left_value=`/`right_value=`. This is
  asymmetric with the read aliases by design: `Difference` is an output type the
  differ produces, and the audit found no callers that hand-build it.
- **Strict-warnings note:** reading the deprecated `diff.old_value`/`new_value`
  emits a `UserWarning`. Under `warnings.simplefilter("error")` (a strict CI
  warnings policy) or inside a broad `except Exception`, that read now *raises*
  where it previously returned a value. Migrate to `left_value`/`right_value`.
- `protokit diff --format json` now emits `left_value`/`right_value`;
  `old_value`/`new_value` are retained as deprecated duplicate keys, removed in
  protokit 1.0. The output gains a top-level `schema_version` field (`"0.1"`) so
  consumers can detect the shape change programmatically; it bumps when the
  deprecated keys are dropped at 1.0. The JSON object is open/additive —
  consumers should ignore unknown keys rather than validate a closed set.
- Schema compatibility (`protokit compat`) keeps `old`/`new` unchanged — it is a
  directional before→after version check where `old`/`new` is semantically
  correct. The diff-vs-compat terminology split is intentional and documented.
- Fixed a stale README JSON example that showed a `"warnings"` key; the diff JSON
  emits `"diagnostics"`.

### Added
- **`protokit.storage` — schema-aware scan/filter engine for protobuf data at
  rest (API-only, PR1).** `scan(source, registry, *, predicate, on_error)`
  routes each `(stream_id, record_bytes)` record to its stream's **isolated**
  descriptor pool, parses it, and yields a tagged
  `ScanRecord(stream_id, record_index, message)`. A `Source` is any iterable of
  `(stream_id, bytes | memoryview)` — a `memoryview` from a C++ buffer is a
  first-class record, not just files. `StreamRegistry.register_stream` resolves
  each stream's schema up front (`FileDescriptorSetSchema`, or the channelized
  `EmbeddedSchema`) into an isolated pool, so concurrent streams may hold
  conflicting versions of the same fully-qualified type without collision.
  `on_error` is fail-loud by default (`raise`); `skip` / `collect` are opt-in
  and never produce silent partial results — `ScanResult.errors` is withheld
  (raises `RuntimeError`) until the scan runs to completion. Two reference
  adapters ship in `protokit.storage.sources`: `length_delimited`
  (varint-prefixed file frames) and `per_message_view` (the pybind11 per-message
  `memoryview` source). The raw record bytes are parsed inside a confined step
  and never retained (upb arena copy), with a defensive `bytes()` boundary so an
  invalid/released view fails catchably rather than crashing the process.
  Projection and columnar sinks are deferred to a follow-up PR.
- **`protokit storage` CLI + `.proto` schema source + `on_error='route'` (PR1.5).**
  A command line over the scan engine — `protokit storage scan` / `head` /
  `count` — reads a file of length-delimited frames, resolves the message type
  via `--desc` (a `FileDescriptorSet`) or `--proto` (compiled, with
  `--proto-path`/`-I`) + `--type` (alias `--message-type`), optionally filters
  with the minimal `--where` grammar (`path == scalar` / `!=` / `has:path`;
  richer expressions are rejected with a pointer at the Python `predicate=` API),
  and dumps (`--format human`/`json`), heads (`-n`), or counts (`--quiet` adds a
  grep-like `1`=no-match exit). `--on-error` is `raise` (default), `skip`, or
  `warn` (report each fault to stderr and continue). Exit `0`/`2` (`2` = bad
  flag, unresolved schema, malformed `--where`, or a data fault under `raise`).
  New public surface: `on_error='route'` + an `error_sink` callback on `scan()`
  (a strictly non-breaking widening — a raising sink propagates, and
  `ScanResult.errors` raises under `route`); `ProtoFileSchema` (compiles `.proto`
  via the non-exiting compile path; never `SystemExit`); and the typed
  `SchemaCompileError` / `WhereError` exceptions. Cross-channel correlation
  (multi-stream scan) remains a library capability; the CLI is single-stream.

## 0.8.0 — 2026-05-28 (and earlier — cumulative pre-fold record)

> This section is the cumulative changelog for every release through 0.8.0,
> preserved verbatim from the pre-0.9.0 `## Unreleased` accumulation. Per-release
> subsections below carry their own version markers (`### D7 … (0.8.0)`,
> `### 0.7.2 …`, `### D6a … (0.2.0)`, etc.). From 0.9.0 onward, each delivery is
> folded into its own `## <version>` section at release time.

### Added
- `protokit.schema` — descriptor-level compatibility checker with 17 built-in
  rules, four compatibility profiles (`WIRE`, `CONSUMER_SAFE`,
  `PRODUCER_SAFE`, `STRICT`), and a pluggable rule API.
- `protokit compat` CLI subcommand for schema compatibility checks.
- `protokit.schema.SchemaChecker` engine, `CompatibilityPolicy` for
  reusable configuration bundles, and `FieldRuleContext` /
  `MessageRuleContext` for emit-style plugins.
- Rule-pack loading via `SchemaChecker.load_rule_pack(module)` and the
  CLI `--rule-pack MODULE` flag. Rule packs are plain Python modules
  exposing a `RULES = [(rule_id, fn), ...]` list.
- **`protokit.formatters` — pluggable output formatter system** spanning
  both CLIs. Four `FormatterKind` values (`DIFF`, `COMPAT`,
  `COMPAT_HISTORY`, `COMPAT_BISECT`); user packs register via
  `register_formatter(name, fn, *, kind)` or the CLI's
  `--formatter-module MODULE` (repeatable, mirrors `--rule-pack`).
  Built-in names (`human`, `json`, `junit`, `sarif`) are reserved
  against override.
- **JUnit XML built-ins** for every kind. `protokit diff --format junit`
  uses a binary-result single-testcase pattern (one assertion per
  comparison); `protokit compat {check,history,bisect,ci} --format junit`
  uses per-finding testcases. Output validates against the Apache Ant
  reference JUnit xsd consumed by Jenkins, GitLab, GitHub Actions
  test-result actions, CircleCI, and TeamCity.
- **SARIF 2.1.0 built-ins** for every compat kind (`COMPAT`,
  `COMPAT_HISTORY`, `COMPAT_BISECT`) — consumable by GitHub Code
  Scanning, GitLab security dashboards, and any OASIS SARIF
  consumer. Severity mapping: WIRE+SEMANTIC → `"error"`, POLICY →
  `"warning"`. Aggregate kinds attach `partialFingerprints.commit`
  for per-commit grouping. SARIF for the DIFF kind is intentionally
  omitted — message diffs don't fit SARIF's rule/result model.
- `protokit.schema.HistoryReport`, `protokit.schema.BisectReport`,
  `protokit.schema.HistoryEntry`, and `protokit.schema.CommitDiagnostic`
  promoted to public dataclasses. `protokit.schema.Diagnostic` now
  re-exported as well.
- `protokit.schema.git.commit_subject(ref)` helper.
- `examples/custom_formatter.py` Slack-summary demo for the
  pluggable formatter API.
- pytest-based test coverage: 700+ tests including formatter
  registry semantics, built-in coverage, JUnit xsd validation, SARIF
  schema validation, CLI dispatch, two-phase pack rollback, formatter
  exception fail-fast, and the stdout-write guard.

#### Schema linting (D1–D5)

- **`protokit lint` subcommand** — descriptor-level lint runner over
  `.proto` sources or pre-built `FileDescriptorSet` binaries. D1
  landed the engine + cold-import contract; D2 shipped the canonical
  `naming` rule pack (AIP-122 snake_case canary); D3 ratcheted the
  rule-emission contract with the structured `LintRuntimeWarning`
  carrier (`rule_exception`, `unloaded_rule` categories); D5 lands
  the pyproject configuration substrate, file-level exclusion,
  cross-formatter render parity, and the perf-smoke canary.
- **`[tool.protokit.lint]` pyproject table** — auto-discovered by
  walking up from the CWD to the first `.git` directory or file
  (worktree-safe per KTD-7). Recognized keys: `profile` (string or
  list), `exclude` (list of gitignore-style globs), `min_severity`
  (`"info"` / `"warning"` / `"error"`), `max_warnings` (int),
  `format` (formatter name). Unknown keys and type mismatches
  produce a hard exit-2 error naming the recognized keys; list-
  valued keys reject heterogeneous arrays per KTD-5.
- **`--config PATH` / `--no-config`** — pin a specific config file
  or skip pyproject reading entirely. Mutually exclusive at parse
  time. `--config` is strict (missing/unreadable/table-absent/
  invalid-TOML all exit 2 with newline-sanitized stderr); the
  default walk-up is silent-fallback when no `[tool.protokit.lint]`
  table is found.
- **`--exclude PATTERN` (repeatable) / `--no-exclude`** — gitignore-
  style glob exclusion of input files matched against
  `FileDescriptorProto.name`. CLI `--exclude` patterns append to
  the pyproject `exclude` list per R13; `--no-exclude` clears the
  resolved exclude list (CLI + pyproject) at apply-time. When the
  resolved exclude drops every file, a structured
  `LintRuntimeWarning(category="all_files_excluded")` fires and
  `engine.run` short-circuits (no point walking zero files per
  KTD-4).
- **Source-attributed `min_severity_relaxed` warning** — when the
  resolved `min_severity` relaxes the composed profile floor, a
  structured `LintRuntimeWarning(category="min_severity_relaxed")`
  fires post-`engine.run`. The message attributes the source: CLI
  flag, pyproject key, or "both" with the pyproject value carried
  in the message for triage. Replaces the previous unstructured
  stderr breadcrumb.
- **Cross-formatter `LintRuntimeWarning` render parity** — all
  four current categories (`rule_exception`, `unloaded_rule`,
  `min_severity_relaxed`, `all_files_excluded`) render in all four
  built-in formatters: `lint_human` stderr envelope, `lint_json`
  `runtime_warnings` array, `lint_junit` `<system-out>` lines,
  `lint_sarif` `runs[].properties.runtime_warnings` array. Closes
  the D3-era silent-warning regression in three of four formatters.
- **`tests/schema/lint/test_perf_smoke.py`** — catastrophic-regression
  canary on `linux + py3.12` cells. Synthetic 50 files × 20 messages
  × 10 fields = 10,000 fields; threshold loose by design (smoke,
  not benchmark). Skipped via `@pytest.mark.skipif` on other cells;
  the companion `test_perf_smoke_coverage.py` parses
  `.github/workflows/ci.yml` to verify the matrix contains at least
  one predicate-matching cell (fail-closed per KTD-3).
- **`slow` pytest marker** — registered in `pyproject.toml`. The
  D5 perf smoke is the only current consumer; future slow tests
  can join via the same marker. `pytest -m "not slow"` excludes
  them from fast-iteration loops.
- **New deps**: `tomli >= 2.0, < 3` (py<3.11 only; py3.11+ uses
  stdlib `tomllib`) for `[tool.protokit.lint]` parsing; `pathspec
  >= 0.12, < 2` for gitignore-style glob matching. Dev-dep
  additions: `PyYAML >= 6.0, < 7` and `types-PyYAML` for the perf-
  smoke coverage meta-test (uses `yaml.safe_load` exclusively per
  KTD-3 security posture).

### Changed
- `--format` on every CLI subcommand is now a free-form string instead
  of a fixed `click.Choice`. Unknown values exit 2 with the available
  formatter list for the subcommand's kind. Case-insensitivity from
  the prior `Choice(..., case_sensitive=False)` is preserved.
- `--quiet` mutual-exclusion widened: previously rejected
  `--format json` only; now rejects every non-`human` formatter
  (junit, sarif, custom packs) so structured output is never
  silently swallowed.
- **Error message wording** for two existing rejections changed.
  Exit codes are unchanged (still 2 for both), but CI scripts that
  parse stderr text need updating:
  - Unknown `--format`: was Click's auto `"Invalid value for '--format':
    'X' is not 'human' or 'json'"`, now `"unknown formatter 'X'.
    Available for {KIND}: human, json, junit, sarif"`.
  - `--quiet --format json`: was `"--quiet and --format json are
    mutually exclusive"`, now `"--quiet is incompatible with structured
    output format 'X'. Drop --quiet, or pick --format human"`.
  - Built-in formatter shadowing via `--formatter-module` now reports
    `"formatter pack 'X' conflicts with a reserved built-in name: ..."`
    (distinct prefix from the generic `"failed to load formatter pack"`).
- `protokit.schema.Diagnostic` is now exported from
  `protokit.schema.__all__` (was importable only via the
  `protokit.message` path).

### Changed — BREAKING
- **Distribution name renamed** from `proto-differ` to `protokit`.
- **Import root renamed** from `proto_differ` to `protokit`. The
  top-level package is now intentionally empty — import from the two
  subpackages directly:
  - `proto_differ.*` → `protokit.message.*`
  - (no `protokit` top-level re-exports; explicit namespacing only)
- **CLI entry point renamed** from `pbdiff` to `protokit`, now with
  subcommands:
  - `pbdiff [args]` → `protokit diff [args]`
  - `protokit compat [args]` — new schema compatibility command.
- **pytest plugin import path** changed:
  - `from proto_differ.pytest_plugin import pytest_assertrepr_compare`
    → `from protokit.message.pytest_plugin import pytest_assertrepr_compare`

There is no compatibility shim — existing imports must be updated.
The rename lands as a single breaking change on the path to 0.2.

### BREAKING (D5 U3 — `protokit lint` runtime warnings)

- `LintRuntimeWarning.rule_id` widened from `str` to `str | None`
  (D5 U3). Engine-emitted categories (`rule_exception`,
  `unloaded_rule`) continue to populate a non-`None` string at every
  emit site. CLI-emitted categories — `all_files_excluded` (D5 U3,
  fires when `--exclude` / `[tool.protokit.lint] exclude` drops every
  input file) and `min_severity_relaxed` (D5 U4, fires when the
  resolved `min_severity` relaxes the composed profile floor) —
  populate `rule_id=None` because they are not scoped to a single
  rule.
- **JSON wire format**: `report.runtime_warnings[*].rule_id` is now
  `null`-capable. Consumers strictly typing this field as `string`
  must accept `null` or `Optional<string>`.
- **Python API**: code iterating `w.rule_id.upper()` or
  `w.rule_id.startswith(...)` on the new categories raises
  `AttributeError`. Branch on `w.category` first, then narrow:
  ```python
  if w.category in ("rule_exception", "unloaded_rule"):
      assert w.rule_id is not None  # mypy-strict narrowing
      ...use w.rule_id as str...
  ```
  Mirrors the existing `descriptor_path` / `exception_type` narrowing
  pattern in `LintRuntimeWarning`'s docstring.
- **`LintRuntimeWarning.category` Literal** widened from 2 values
  (`"rule_exception"`, `"unloaded_rule"`) to 4 (adds
  `"min_severity_relaxed"`, `"all_files_excluded"`). Exhaustive
  `match`/`if-elif` with `assert_never()` arms require an additional
  branch.

**Migration recipes (D5 U6 fold-in).** Concrete before/after for
each consumer type:

*JSON consumer migration.* The shape of
`report.runtime_warnings[*]` changed only in the `rule_id` field:
it is now `string | null`. When `rule_id` is `null`, the `category`
field tells you the source — `"min_severity_relaxed"` means
pyproject or CLI relaxed the profile floor; `"all_files_excluded"`
means no files survived `--exclude` / `[tool.protokit.lint] exclude`
filtering. Code that previously did:

```python
for w in parsed["runtime_warnings"]:
    print(w["rule_id"].upper())  # AttributeError on None
```

becomes:

```python
for w in parsed["runtime_warnings"]:
    if w["rule_id"] is not None:
        print(w["rule_id"].upper())
    else:
        # rule_id-less category — branch on w["category"] for triage
        print(f"[{w['category']}] {w['message']}")
```

*SARIF consumer migration.* Read
`runs[].properties.runtime_warnings` in addition to the existing
`runs[].invocations[].toolExecutionNotifications` array. The two
arrays carry disjoint event sets — `toolExecutionNotifications`
remains compile-stage diagnostics only (per KTD-1); the new
`runs[].properties.runtime_warnings` array carries
`LintRuntimeWarning` events. Each entry has shape:

```json
{
  "level": "warning",
  "message": {"text": "<warning message>"},
  "properties": {
    "category": "<one of the four categories>",
    "subcategory": "runtime"
  }
}
```

No `descriptor.id` is emitted (per KTD-1) — categorization travels
via `properties.category`. SARIF consumers wanting a unified
warning stream should union the two channels on the client side.
The `runs[].properties` block is **omitted entirely** on clean
runs (zero runtime warnings); existing pre-U5 SARIF documents are
byte-for-byte unchanged when no warnings fire.

*Python API consumer migration.* Add a `None` branch when
narrowing `LintRuntimeWarning.rule_id`. The mypy-strict pattern
mirrors the existing `descriptor_path` / `exception_type`
narrowing in `LintRuntimeWarning`'s docstring:

```python
def handle(w: LintRuntimeWarning) -> None:
    if w.category in ("rule_exception", "unloaded_rule"):
        assert w.rule_id is not None  # mypy-strict narrowing
        process_rule_scoped_warning(w.rule_id, w.message)
    else:
        # category in ("min_severity_relaxed", "all_files_excluded")
        # rule_id is None; warning is global, not rule-scoped
        process_global_warning(w.category, w.message)
```

Exhaustive `match`/`if-elif` arms with `assert_never()` also
require an additional branch — the `category` Literal widened
from 2 values to 4 (`"rule_exception"`, `"unloaded_rule"`,
`"min_severity_relaxed"`, `"all_files_excluded"`).

### BREAKING (D5 U4 — `protokit lint` stderr wire format)

D5 U4 routes all runtime warnings through structured emission. The
following stderr patterns are no longer produced; consumers that
grep stderr must switch to the structured channel until D5 U5
restores a human-format hook.

- **`warning[lint-runtime]:` stderr prefix removed.** The stderr
  loop that mirrored every `LintRuntimeWarning` as
  `warning[lint-runtime]: <category>: <message>` was deleted.
  Runtime warnings now travel exclusively in
  `LintReport.runtime_warnings` and surface only through the machine
  formatters (`--format=json` / `--format=junit` / `--format=sarif`).
  Five patterns disappeared from stderr in one cut:
  `warning[lint-runtime]: rule_exception: ...`,
  `warning[lint-runtime]: unloaded_rule: ...`,
  `warning[lint-runtime]: all_files_excluded: ...`,
  `protokit lint: --min-severity=... relaxes profile floor ...`, and
  `protokit lint: [tool.protokit.lint] min_severity=... relaxes
  profile floor ...`. CI scripts pinned to any of these prefixes
  will silently stop matching.
- **`min_severity_relaxed` message format changed.** The U2
  breadcrumb was prefixed with `protokit lint: `. The U4 structured
  message drops that prefix and starts directly with the source
  attribution: `--min-severity=warning relaxes profile floor from
  error to warning` (CLI-source),
  `[tool.protokit.lint] min_severity=warning relaxes profile floor
  from error to warning` (pyproject-source), or the CLI form with
  `(overriding pyproject min_severity=info)` appended (both-source).
  Read via `parsed["runtime_warnings"][i]["message"]` in
  `--format=json`.
- **`all_files_excluded` message format changed.** The U3 message
  read `all N input file(s) excluded by patterns: PATTERN_LIST`.
  U4 attributes the source: `all N input file(s) excluded by
  --exclude patterns: ...` (CLI-only),
  `all N input file(s) excluded by [tool.protokit.lint] exclude
  patterns: ...` (pyproject-only), or
  `all N input file(s) excluded by --exclude and
  [tool.protokit.lint] exclude patterns: ...` (both). Consumers
  matching the substring `excluded by patterns:` no longer match.
- **`--format=human` regression window (U4 → U5).** The U4 → U5
  window in which `--format=human` (the default) surfaced zero
  runtime warnings is now CLOSED — see the "BREAKING (D5 U5)"
  entry below for the restored envelope shape. Until U5 shipped,
  `--format=human` consumers had to fall back to `--format=json`
  to observe runtime warnings; that fallback is no longer required
  for visibility, though it remains the right choice for full-fidelity
  machine consumption (the human hook truncates per-category above
  an internal threshold; see U5 entry).

  **Migration recipe (human-format CI, transitional):** during the
  U4-only window CI scripts replaced `protokit lint <args>` with
  `protokit lint --format=json <args> | jq '.runtime_warnings'`,
  or set `format = "json"` in `[tool.protokit.lint]` and parsed
  the emitted JSON. Reverting to `--format=human` once U5 shipped
  restores stderr emission under the NEW envelope shape — see U5
  entry for the new prefix.

### BREAKING (D5 U5 — `protokit lint` cross-formatter runtime-warning surfaces)

D5 U5 materializes three consumer-visible wire-format surfaces. The
agent-native `--format=json` channel is unchanged. Each new surface
is additive at the document level but introduces a new shape
consumers may need to parse:

- **`--format=human` stderr envelope restored.** The U4→U5 silent
  window for `--format=human` is closed. Runtime warnings now
  emit to stderr as:

      protokit lint: warning [<category>]: <message>

  This is a NEW shape — distinct from both the U3-era
  `warning[lint-runtime]: <category>: <message>` (REMOVED in U4)
  and the U2-era `protokit lint: <bare-message>` breadcrumb
  (REMOVED in U4). CI scripts grepping `protokit lint: warning [`
  match. The four current categories — `rule_exception`,
  `unloaded_rule`, `min_severity_relaxed`, `all_files_excluded` —
  all render under this envelope. The hook is NOT gated by
  `--quiet` (KTD-6); only stdout findings are. To suppress
  stderr warnings, route them through `--format=json` instead.

  **Summarization above per-category threshold.** When a single
  category produces more than an internal threshold of warnings
  (currently 5; module-level constant `_LINT_HUMAN_SUMMARIZATION_THRESHOLD`),
  the human hook emits the first `<threshold>` individual lines
  then a single collapse line:

      protokit lint: warning [<category>]: ... and <N> more — use --format=json for full details

  Machine formatters (`json` / `junit` / `sarif`) emit ALL warnings
  unconditionally; summarization is human-only. Agents needing
  full fidelity must use `--format=json`.

- **`--format=junit` `<system-out>` dual line format.** The
  testsuite's `<system-out>` body now contains TWO incompatible
  line shapes joined by newlines:

  1. Compile diagnostics (pre-U5; unchanged): `<level> [<category>]: <message>`
  2. Runtime warnings (NEW in U5): `[<category>] <message>`

  Compile diagnostics precede runtime warnings within the block.
  Consumers with a strict prefix regex anchored to the leading
  level token (`^(warning|error|info) \[`) will not match the new
  runtime-warning lines. Two distinguishing tokens:
  compile-diagnostic lines start with a word, runtime-warning
  lines start with `[`.

- **`--format=sarif` `runs[].properties.runtime_warnings` array.**
  SARIF runtime warnings ride on a `propertyBag` extension under
  the run object — INTENTIONALLY separate from the existing
  `runs[].invocations[].toolExecutionNotifications` array (which
  remains compile-stage diagnostics only per KTD-1). Entry shape:

      {
        "level": "warning",
        "message": {"text": "<warning message>"},
        "properties": {
          "category": "<one of the four categories>",
          "subcategory": "runtime"
        }
      }

  No `descriptor.id` is emitted per KTD-1 — categorization
  travels via `properties.category`. SARIF consumers filter
  `properties.subcategory == "runtime"` to get the dedicated
  channel. The `runs[].properties` block is OMITTED entirely on
  clean runs (zero runtime warnings) so existing pre-U5 SARIF
  documents are byte-for-byte unchanged when no warnings fire.

  **Migration recipe (SARIF consumer):** add a second scan of
  `runs[].properties.runtime_warnings` in addition to the existing
  `runs[].invocations[].toolExecutionNotifications` scan. The two
  arrays carry disjoint event sets. If consumers want a unified
  warning stream, union the two channels on the client side.

  **Migration recipe (JUnit consumer):** if scripts parse
  `<system-out>` for warning lines, extend the leading-token
  regex to accept BOTH `^<level> \[<category>\]:` AND
  `^\[<category>\]`. Runtime-warning lines always appear AFTER
  compile-diagnostic lines within the same `<system-out>` body.

  **Migration recipe (human-format consumer):** match the new
  envelope `protokit lint: warning [<category>]:` on stderr. The
  trailing summarization line includes the literal string
  `use --format=json` so a grep-based consumer hitting the
  threshold knows where to find full-fidelity output.

### D7 — Compat plugin-flag rename (0.8.0)

`protokit compat`'s `--rule-pack` flag collided in name with the
`protokit lint --rule-pack` flag added in D3 — they shared a name
across subcommands but loaded different rule systems (compat's are
`FieldPlugin`-shaped via `SchemaChecker.load_rule_pack`; lint's are
`LintRuleSpec`-shaped). D7 renames compat's flag to
`--compat-rule-pack` and keeps the old name as a deprecation alias.
Both flags work today; the legacy name is removed in protokit 1.0.
No behavior change for users who migrate to the new name; no break
for users who don't.

#### Added

- `--compat-rule-pack MODULE` on every sub-subcommand within
  `protokit compat` (`check`, `history`, `bisect`, `ci`). Same
  semantics as the legacy `--rule-pack` (Python module exposing a
  `RULES = [(rule_id, plugin_fn), ...]` list; repeatable; loaded via
  `SchemaChecker.load_rule_pack`). The new name is the canonical
  name going forward and resolves the cross-CLI naming collision
  with `protokit lint --rule-pack` (which retains the unqualified
  name).

#### Deprecated

- `--rule-pack` on `protokit compat {check,history,bisect,ci}` is now
  a deprecation alias for `--compat-rule-pack`. The flag still loads
  packs identically and remains accepted in 0.8.x, but each
  invocation emits a `UserWarning` to stderr:
  `"--rule-pack is deprecated and will be removed in protokit 1.0; use --compat-rule-pack instead."`
  The flag is `hidden=True` in `--help` output to nudge new code
  toward the canonical name.
  - `UserWarning` (not `DeprecationWarning`) is the deliberate class
    choice. `DeprecationWarning` is hidden from CLI users by
    Python's default warning filter, and it gets promoted to an
    exception under `-W error::DeprecationWarning` strict-warning CI
    (which Click traps in its arg-parse pipeline). `UserWarning` is
    visible by default and matches the in-repo precedent at
    `src/protokit/formatters/_registry.py`.
  - The warning fires exactly once per invocation regardless of how
    many times `--rule-pack` is repeated on the command line (Click
    invokes per-option callbacks once per option-collection cycle).
    Mixing the old and new flag names in a single invocation
    accumulates both sets of packs (per Click `multiple=True`
    semantics, not last-wins) and emits exactly one warning.

#### Migration note

Old:

```bash
protokit compat check OLD NEW --type acme.User --rule-pack myorg.proto_rules
```

New:

```bash
protokit compat check OLD NEW --type acme.User --compat-rule-pack myorg.proto_rules
```

Mechanical search-and-replace of the flag name. No changes to the
rule-pack module structure (`RULES = [(rule_id, plugin_fn), ...]`),
no changes to plugin context APIs, no changes to other compat flags
(`--formatter-module`, `--ignore`, `--dedupe-by-type`, `--quiet`,
etc.). `protokit lint --rule-pack` is unchanged — only compat's
flag is renamed.

If you'd rather keep `--rule-pack` working until 1.0, you can — the
deprecation warning is informational, not a CI break. Strict-warning
test environments running `-W error::UserWarning` should wrap legacy
`--rule-pack` invocations in `warnings.catch_warnings()` until the
migration is complete.

#### Test coverage

Three AE-driven tests in `tests/schema/test_cli.py::TestRulePack`
extend the existing class with coverage for the new flag's load path
(`test_compat_rule_pack_loads_pack_no_warning`), the deprecation
warning's exact-token presence
(`test_rule_pack_legacy_emits_user_warning` — asserts `--rule-pack`,
`deprecated`, `1.0`, and `--compat-rule-pack` are all present in the
warning message), and the "exactly one warning when both flags
supplied" semantics (`test_both_flags_accumulate_warn_once`). Three
smoke binding tests in
`tests/schema/test_cli.py::TestCompatRulePackBinding` assert the new
flag is registered on `history`, `bisect`, and `ci` (one test each).
All six tests use `warnings.catch_warnings(record=True) +
warnings.simplefilter("always")` to bypass Python's per-message
warning-dedupe registry, which would otherwise suppress the warning
on second+ invocation in the same test session.

Tag: `v0.8.0`. PyPI: `pip install protokit==0.8.0`.

---

### 0.7.2 — scrub maintainer-side strays from public docs/solutions/

No code change; no behavior change. Removes 27 maintainer-side
learnings from `docs/solutions/` — content about ce:review workflow
meta, CHANGELOG/migration-recipe discipline, delivery-boundary commit
composition, phase-0 brainstorm-verification discipline, plan-review
prior-art audit, pre-release version-bump signaling, fail-closed CI
matrix coverage, public surface DRAFT discipline, PyPI publish
ergonomics, GitHub Actions injection mitigations, and similar
operational discipline. These files were retained in 0.7.0 + 0.7.1 by
the original pre-release cleanup but they are maintainer-side content
irrelevant to library users (they don't describe library behavior,
lint rule design, or anything visible in the public source); they now
live in a private repo. Public `docs/solutions/` retains 81 project-
side learnings about lint rule design, library API, wire format,
debugging patterns, and other content that helps library users.

Git history scrub applied via `git filter-repo --invert-paths`; main
branch + v0.7.0 + v0.7.1 tags force-updated to remove the 27 paths
from all reachable history. 0.7.0 and 0.7.1 sdists on PyPI still
contain the relocated files (PyPI sdists are immutable after
publish) — 0.7.2 is the first version with a clean published
distribution. The relocated paths also disappear from any future
`git clone` checkout.

Tag: `v0.7.2`. PyPI: `pip install protokit==0.7.2`.

---

### 0.7.1 — WKT include-path auto-discovery + protoc 25+ compatibility (system-protoc backend)

Patch release. No new features; no behavior change for the protoxy
backend (which already bundles the well-known-type protos
in-process and does not invoke the protoc binary).

**Fix #1 — WKT include-path auto-discovery.** `_compile_with_protoc`
now auto-discovers WKT include directories (the directory adjacent
to the resolved `protoc` binary, plus `/usr/include` and
`/usr/local/include` as fallbacks) and threads them into the
protoc `-I` argv AFTER caller-supplied include paths and
proto-file parents. Users importing `google/protobuf/*.proto` on
systems with split-package protoc installs — most notably
Debian/Ubuntu's `apt install protobuf-compiler`, which places
protoc at `/usr/bin/protoc` and the WKT files at
`/usr/include/google/protobuf/` without adding `/usr/include` to
protoc's search path — no longer need to pass `-I /usr/include`
themselves.

**Fix #2 — protoc 25+ end-of-options compatibility.** Drop the
`--` end-of-options separator from the protoc argv.
`_compile_with_protoc` previously appended `--` as a hardening
measure for input paths beginning with `--`, but protoc 25+
rejects that separator with `Unknown flag: --`. The separator was
accepted by earlier protoc versions; the blast radius of dropping
it is tiny (a proto path starting with `--` would now be
misinterpreted as a flag — rare-to-nonexistent in practice).

**Test update — cross-backend semantic equivalence (not byte
equivalence).** The cross-backend test that pinned
``source_code_info`` byte-equivalence between the protoxy and
protoc backends now compares **semantic** equivalence of the
``(descriptor-path → leading_comments, trailing_comments,
leading_detached_comments)`` mapping that ``leading_comment()``
actually consumes. The byte-equivalence assertion was a strong
proxy that only held when both backends used the same protoc
version; different protoc versions encode location spans
differently even though the path→comments mapping (the
production-code-visible contract) is identical. No source-code
change in production — only the test invariant was tightened to
match the real contract.

**Fix #3 — protobuf upper bound at ``<6``.** Pin
``protobuf<6`` in pyproject's ``dependencies``. protobuf 6+
removed ``FieldDescriptor.label`` and related attributes that
protokit's lint rule packs and the compatibility checker rely
on; users without the ``[compiler]`` extra (which transitively
pins protoxy → ``protobuf<6``) were silently getting protobuf 7
and an immediately-broken install. Both code paths are now
guaranteed to resolve to a tested combination. Adopting the new
descriptor API is planned for a future release.

**Fix #4 — perf-smoke fixture directory layout.** The perf-smoke
synthetic fixture wrote 50 files with distinct
``perfsmoke.file<N>`` packages into a single directory, which
post-D6c lint rules (``package/directory-same-package``, added
in 0.4.0) correctly flagged as 50 findings — a pre-existing test
bug masked locally because the smoke runs only on linux+py3.12,
which had never executed before the first public CI run.
Restructure each file into its own
``perfsmoke/file<N>/file_<N>.proto`` subtree so package and
directory align.

CI still installs protoc via apt's `protobuf-compiler` package
(protoc 3.21.x on ubuntu-latest). The 0.7.1 runtime
auto-discovery (Fix #1) makes apt's split-package WKT layout work
correctly without callers needing to pass `-I /usr/include`
explicitly. A pinned protoc 25.3 binary release was tried during
the 0.7.1 development cycle but introduced descriptor-encoding
differences from the older protoc embedded in protoxy 0.7.2 that
caused subtle lint-rule behavior drift; apt's protoc keeps the
two backends in lockstep.

Tag: `v0.7.1`. PyPI: `pip install protokit==0.7.1`.

### D6f — R6 promotion to ERROR + R9b per-rule disable (0.7.0)

D6f is a **D6e KD-1 demonstration delivery**: the first
post-closing-arc release that exercises the inverted UX
philosophy (`protokit-UX overrides buf-parity`) on a
user-facing severity decision. Two paired changes ship together:
**R9b** — full per-rule disable surface (`"off"` severity
sentinel, `disabled_rules` / `enabled_rules` pyproject lists,
`--disable-rule` / `--enable-rule` CLI flags, multi-kind
`custom/<suffix>` prefix expansion) — and **R6 promotion** —
all 5 rules in `options/deprecated_replacement` flip
WARNING → ERROR in the `default` profile only. R9b shipped
first (U2 before U1) as the safety net so the migration recipe
is real on day one, per the post-ship-adoption-monitoring
discipline.

#### Added — R9b per-rule disable (full surface)

- **`[severities]` `"<rule_id>" = "off"`** — new accepted
  value alongside `"error"` / `"warning"` / `"info"`. Intercepted
  at the config-coercion layer (`_coerce_severities`) BEFORE
  `LintSeverity` construction; the `LintSeverity` enum stays
  closed at 3 members (ERROR, WARNING, INFO). `OFF` rule_ids
  flow through the unified `ResolvedLintConfig.disabled_rules`
  set and the rule is excluded from `_loaded_specs` at engine
  setup — wire-safety invariant: `LintSeverity.OFF` never
  enters `LintFinding`. Resolves the documented 2-step `"= "info"
  + --min-severity warning"` workaround from D6e.
- **`[tool.protokit.lint] disabled_rules` / `enabled_rules`**
  pyproject lists — explicit per-rule disable + enable
  directives. Entries validated against `_R9B_RULE_ID_REGEX`
  (canonical `pack/rule-suffix`, bare `custom/<suffix>`, or
  mangled `custom/<suffix>__<kind>` forms); normalized via
  `.strip().lower()` per the input-boundary normalization
  discipline. Heterogeneous arrays, non-string elements, and
  unrecognized formats all exit 2 via
  `error[lint-pyproject-config-invalid]`.
- **`--disable-rule` / `--enable-rule` CLI flags**
  (repeatable; env-var override via `PROTOKIT_DISABLE_RULE` /
  `PROTOKIT_ENABLE_RULE`). Bad flag values exit 2 via the new
  `error[lint-cli-option-invalid]` code (distinct from
  `lint-pyproject-config-invalid` so CI scripts can attribute
  CLI-flag failures separately from pyproject-coercion
  failures). Click `multiple=True` natural empty-tuple
  sentinel — no `ParameterSource` machinery; absent flag
  yields `()` which becomes `None` in `cli_overrides`.
- **Multi-kind `custom/<suffix>` prefix expansion** at the
  config-resolution layer — `disabled_rules = ["custom/audit-
  required"]` suppresses every kind of `audit-required` (the
  bare suffix expands to all mangled forms emitted by
  `synthetic_rule_ids()`; e.g., `custom/audit-required`,
  `custom/audit-required__method`, `custom/audit-required__enum_value`).
  Per-kind disable still works via the explicit mangled form
  (`disabled_rules = ["custom/audit-required__method"]`); no
  expansion, exact match. Suffix-equality matching (NOT
  substring) so `"custom/foo"` never matches `"custom/foobar"`.
- **R8 precedence — polarity-first / tier-second** —
  ONE principle, two-step application: (1) any disable at any
  tier wins over any enable; (2) within the same polarity, CLI
  > pyproject. Resolved exhaustively in
  `ResolvedLintConfig.from_dict`; engine hot path sees only the
  effective rule set.
- **NEW `LintRuntimeWarning(category="contradictory_disable_config")`**
  — fires when a disable mechanism silently overrides a
  lower-tier enable directive (5 enumerated cases in the R8
  resolution table). Message text names the rule_id + both
  involved mechanisms so users know exactly which directive
  was overridden.
- **NEW `LintRuntimeWarning(category="unknown_rule_id")`**
  — lenient-with-warning for `disabled_rules` / `enabled_rules`
  entries that don't match any loaded rule_id. Fires at the
  engine's `unloaded_rule_ids` diff step (mirrors the
  pre-existing `severities_unloaded_rule_ids` pattern). Carries
  the normalized rule_id so users see exactly the form that
  failed to match (helps diagnose typos and case-sensitivity
  issues).
- **`_LINT_JSON_SCHEMA_VERSION` bump `"0.5"` → `"0.6"`** —
  triggered ON the two closed-Literal additions to
  `LintRuntimeWarning.category` (items 8 + 9 of the Literal),
  NOT at the delivery boundary. Per the schema-bump policy,
  one bump covers both new categories; the bump lands atomic
  with the model.py Literal additions in U2 rather than
  deferred to U3's package version bump. Consumers parsing
  the schema against `"0.5"` MUST update.
- **SARIF rule catalog `defaultConfiguration.level`** — every
  entry in `tool.driver.rules[]` now emits SARIF 2.1.0 §3.49.3
  `defaultConfiguration.level` derived from the rule's spec
  severity. IDE integrations (VS Code SARIF viewer, GitHub
  Advanced Security, etc.) can now display rule severities in
  the pre-flight rule panel without running a lint. Multi-kind
  rules emit the strictest severity across kinds.
- **SARIF runtime-warning propertyBag rule_id field** — the
  two new D6f categories
  (`contradictory_disable_config`, `unknown_rule_id`) emit a
  `rule_id` key in their SARIF `properties` bag so SARIF
  consumers can correlate warnings to rule_ids without parsing
  message text. Pre-existing rule-scoped categories keep their
  existing shape (no `rule_id` in propertyBag).

#### Changed — R6 promotion (WARNING → ERROR in default profile)

- **All 5 rules in `options/deprecated_replacement` flipped
  WARNING → ERROR** in the `default` profile. The 5 rule_ids:
  - `options/deprecated-field-must-have-replacement-comment`
  - `options/deprecated-enum-value-must-have-replacement-comment`
  - `options/deprecated-method-must-have-replacement-comment`
  - `options/deprecated-message-must-have-replacement-comment`
  - `options/deprecated-enum-must-have-replacement-comment`

  Deprecated elements MUST now carry a replacement reference
  in their leading comment OR be explicitly suppressed via one
  of the R9b mechanisms above. The leading-comment-regex
  heuristic is UNCHANGED — only the severity flips. The
  `recommended` profile is unaffected (R6 has no buf BASIC
  analogue and continues to ship `default`-only).

- **Phase 0 empirical validation** (KD-8 hard gate, captured
  in the U1 commit body): 200 random `.proto` files from
  googleapis (`random.seed(42)`) returned 19 R6 findings;
  manual classification per the KD-8 rubric returned 0 noisy
  hits (0.0%). Gate threshold was >10% OR >5 absolute noisy
  hits → STOP. Result: gate passed with substantial margin.
  Sampled hits inspected: every flag corresponds to a
  deprecated element with no replacement reference in the
  leading comment — the heuristic correctly identifies absence
  of replacement guidance, not noisy informal phrasings.

#### Behavior changes (defaults; demotable)

**R6 promotion — exit-code impact by `--max-warnings` posture:**

| Posture | Pre-0.7.0 | Post-0.7.0 |
|---|---|---|
| `--max-warnings` unset | R6 finding: exit 0 (WARNING; not counted) | R6 finding: exit 1 (ERROR; `has_error` short-circuits) — **SILENT CI-PASS REGRESSION RISK** |
| `--max-warnings 0` | R6 finding: exit 1 (counted as warning) | R6 finding: exit 1 (ERROR; `has_error` short-circuits before `max_warnings` gate) |
| `--min-severity error` | R6 finding: exit 0 (WARNING filtered by floor) | R6 finding: exit 1 (ERROR passes floor) |

This is the inverse-direction sibling of the D6e R4b
`file/syntax-specified` demotion. The posture-1 regression
("silent CI-pass") is the dominant concern: projects that
previously ignored R6 WARNINGs will see their CI flip from
green to red on upgrade.

#### Pre-upgrade migration recipe

Four paths, in increasing specificity. Pick the one matching
your project's posture:

1. **Fix the schema** (recommended). Add a replacement
   reference to the leading comment of every deprecated
   element. The heuristic matches phrasings like `Use FooBar
   instead.`, `Replaced by FooBar.`, etc. — see
   `src/protokit/schema/lint/rules/options/deprecated_replacement.py`
   for the regex.

2. **Demote one rule back to WARNING** via `[severities]`:
   ```toml
   [tool.protokit.lint.severities]
   "options/deprecated-field-must-have-replacement-comment" = "warning"
   ```

3. **Disable one rule via `"off"`** (new in D6f):
   ```toml
   [tool.protokit.lint.severities]
   "options/deprecated-field-must-have-replacement-comment" = "off"
   ```
   Equivalent to `disabled_rules = [...]` with the same rule_id.

4. **Disable the whole R6 family via `disabled_rules`** (new
   in D6f):
   ```toml
   [tool.protokit.lint]
   disabled_rules = [
     "options/deprecated-field-must-have-replacement-comment",
     "options/deprecated-enum-value-must-have-replacement-comment",
     "options/deprecated-method-must-have-replacement-comment",
     "options/deprecated-message-must-have-replacement-comment",
     "options/deprecated-enum-must-have-replacement-comment",
   ]
   ```
   The 5-rule family-list form is load-bearing for users who
   want to suppress R6 wholesale without writing 5 separate
   `[severities]` entries.

5. **Pin to 0.6.0 indefinitely**: `pip install protokit==0.6.0`.

**Cross-tier escape hatch caveat**: `--enable-rule R` does NOT
override pyproject `disabled_rules ⊇ R` (R8 polarity-first;
disable wins across tiers). The `--no-config` flag bypasses
the entire pyproject table — including profile, exclude, and
severities — so users who want to override ONE disabled rule
without losing the rest of their pyproject config MUST edit
the pyproject directly. The `contradictory_disable_config`
runtime warning fires on this case with an actionable message.

#### Flat-config-only convention

D6f explicitly does NOT implement multi-tier pyproject
inheritance (parent `disabled_rules` + child `enabled_rules`
merge semantics). protokit-lint is currently flat-config-only:
the first `pyproject.toml` encountered during the walk-up is
the sole source. The R8 polarity-first / tier-second
resolution applies WITHIN a single pyproject's lists AND
across the CLI-vs-pyproject tier boundary; layered pyproject
inheritance is explicit D6g+ scope.

#### Test coverage

- **R8 13-case precedence parametrization** at
  `tests/schema/lint/test_r9b_precedence.py` — 12 cases from
  the brainstorm R8 resolution table + 1 added post-review
  (`--enable-rule R + [severities] R = "off"`). Each case
  pins the effective load-set + the expected
  `contradictory_disable_config` emission.
- **R8b + R8c runtime warning coverage** at
  `tests/schema/lint/test_r9b_warnings.py` — every
  contradictory-config branch + every unknown-rule_id path
  emits exactly one structured warning with the rule_id +
  mechanism attribution.
- **`_coerce_disabled_rules` / `_coerce_enabled_rules`**
  consolidated parametrized coverage at
  `tests/schema/lint/_config/test_coerce_disable_enable_rules.py`
  (single test file per scope-guardian discipline — saves the
  near-duplicate two-helper split).
- **`_CoercedSeverities` namedtuple return shape** at
  `tests/schema/lint/_config/test_severities.py` — verifies
  `"off"` interception + the two-part return shape +
  rule_id normalization.
- **`cli_overrides` dispatch + intra-`from_dict` ordering** at
  `tests/schema/lint/_config/test_from_dict_r9b.py` — verifies
  the KD-2 ordering (custom_annotation_rules FIRST, then
  disable/enable coercion + prefix expansion, then R8
  precedence, then R8b warnings, then unified-disabled merge).
- **CLI Click integration** at
  `tests/schema/lint/cli/test_cli_disable_enable_rule_flags.py`
  — `multiple=True` repeatability, env-var integration, and
  the `lint-cli-option-invalid` error code path.
- **End-to-end profile-augmentation guard** at
  `tests/schema/lint/cli/test_cli_r9b_profile_augmentation.py`
  — the load-bearing regression test: setting
  `[severities] "<rule>" = "off"` produces ZERO findings on a
  rule-violating fixture via full CLI invocation. Catches the
  silent-no-op risk where `from_dict` bookkeeping never
  reaches engine setup.
- **R6 per-rule severity pin** at
  `tests/schema/lint/rules/options/test_deprecated_replacement_severity.py`
  — parametrized over all 5 R6 rule_ids on TWO surfaces (rule
  spec metadata AND engine-loaded `LintRuleSpec`); pins the
  family count (exactly 5 rules) and `default`-profile-only
  scope. Mirrors the D6e R4b regression-pin pattern.
- **R6 exit-code regression** at
  `tests/schema/lint/cli/test_cli_ci_gating.py::TestR6PromotionExitCodeRegression`
  — 3 postures (`--max-warnings` unset, `--max-warnings 0`,
  `--min-severity error`) all → exit 1 post-promotion; 2
  migration-path integration tests (R9b `--disable-rule`
  restores exit 0; `[severities]` demote restores exit 0);
  multi-ElementKind 2-rule fire pin.
- **R6 migration recipe end-to-end** at
  `tests/schema/lint/cli/test_cli_r6_migration_recipe.py` —
  all 4 migration paths verified via `--proto` + `--config`
  invocations against `cli_fixtures/d6f_r6_migration/` (5
  fixtures including the multi-ElementKind `sad_multi_element.proto`).
- **R9b CLI dedup regression** at
  `tests/schema/lint/test_cli_rule_pack_dedup.py::TestR9bCliInteractionRegression`
  (NEW class — separate from `TestRulePackDedupAcrossBuiltinPacks`
  so a failing R14b test signals R9b-specific issue, not
  `--rule-pack` dedup). 5 cases: `--disable-rule` filters
  BUILTIN_PACKS; `--enable-rule` adds without duplication;
  cross-pack-and-disable-rule interaction; idempotent
  repeated `--disable-rule`; multi-kind custom prefix expansion.
- **Migration-recipe TOML byte-equivalence fixtures** at
  `tests/schema/lint/cli/cli_fixtures/d6f_migration_recipe/`
  — 4 single-entry + 1 family-list TOML snippets that parse
  cleanly through `_coerce_severities` /
  `_coerce_disabled_rules` per the snippet-fixture
  byte-equivalence discipline. Every TOML snippet in the
  migration recipe above maps to a fixture.

#### Deferred to D6g+

- **R6 promotion in `recommended` profile** — no buf BASIC
  analogue, so promotion would diverge from buf parity without
  KD-1 justification. Stays at `default`-only.
- **Per-finding suppress mechanism**
  (`[severities] "custom/X.params.option" = "off"`) — R9b is
  rule-level only; param-level suppression is finer-grained
  scope.
- **Layered multi-pyproject inheritance** — flat-config-only
  is the current architectural reality per KD-3. Layered
  resolution is its own design problem (precedence semantics,
  attribution, override directionality) and is explicit D6g+
  scope.
- **Buf-parity aliases** (`--except-rule` / `--also-rule`) —
  12-week trigger window expires 2026-08-15. Ship if real
  user demand surfaces in that window.
- **`options/field-behavior-consistent` IDENTIFIER-based
  contradictions** — current rule covers VALUE-based
  contradictions only; IDENTIFIER-based scope is a
  rule-expansion task.
- **SHA-pinning test for D6e U3 buf snapshots** — carried
  forward from D6e U4 deferred list; orthogonal to D6f scope.

### D6e — buf BASIC closure + UX philosophy revision (0.6.0)

D6e closes the buf-parity arc: `protokit lint` now matches
**26 of 26 buf v1.69.0 BASIC rules**. Three ship surfaces land
together: a UX philosophy revision (KD-1 inverted: protokit-UX
overrides buf-parity when they conflict), the deferred
`field/not-required` rule in a new opt-in `proto2-strict`
profile, and the 26th buf BASIC rule `package/no-import-cycle`
via a Tarjan SCC pre-walk accumulator. Two Phase 0 falsifications
shaped the delivery (EV-2 for `field/not-required`, two-tier
behavior for `package/no-import-cycle` — both captured as
ce:compound learnings under `docs/solutions/best-practices/`).

#### Added — UX philosophy + `proto2-strict` profile (U1+U2)

- **D6e KD-1: hard-inverted UX philosophy** — protokit-UX
  overrides buf-parity when they conflict; proto2-specific strict
  rules ship in opt-in `proto2-strict` per KD-2 (pragmatic-not-
  dogmatic about proto2). Pinned via presence ratchet in
  `BUILTIN_PACKS` docstring + `tests/test_uxd_philosophy_principle_-
  presence_ratchet.py` so future stale-text edits cannot silently
  revert the stance.
- **D6e POSITIONING_STATEMENT** — `protokit targets buf BASIC
  coverage; defaults reflect Python-protobuf-developer ergonomics,
  not buf's defaults (see proto2-strict for opt-in proto2
  strictness).` Pinned in `BUILTIN_PACKS` docstring + README
  Schema Linting section header. Resolves the KD-1-vs-26/26
  tension by naming the bet explicitly: parity at COVERAGE,
  ergonomics at DEFAULTS.
- **`proto2-strict` opt-in profile** (NEW; D6e KD-3 + KD-11) —
  carries `field/not-required` initially. Activate via
  `--profile proto2-strict` or pyproject
  `profile = ["default", "proto2-strict"]`. Distinct from the
  deferred `strict` profile (style-strictness rules); do NOT
  consolidate per KD-3.
- **`field/not-required` rule** (`buf:FIELD_NOT_REQUIRED` parity;
  proto2-only) shipping in the new `field` rule pack — the
  deferred D6d-U3 rule. ERROR severity in `proto2-strict` profile
  only; ZERO findings in `recommended` + `default` (D6e KD-5).
  Group-typed required fields fire on the implicit lowercased
  field name per buf v1.69.0 (Phase 0 EV-3 binding).
- **NEW `field` rule pack** at `protokit.schema.lint.rules.field`
  — namespace anchor for future field-level proto2-strict rules
  per KD-11 (`field/no-group-syntax`, `field/no-explicit-default`,
  `field/packed-repeated-primitive`; none ship in D6e).
- **Parametrized CLI dedup test consolidation** at
  `tests/schema/lint/test_cli_rule_pack_dedup.py` — replaces the
  two per-flip files (`*_post_d6c.py`, `*_post_d6d.py`) with one
  parametrized test iterating over every `BUILTIN_PACKS` member.
  Promoted at the third near-copy-paste instance. ~60 LOC vs ~360
  LOC across the two prior files.

#### Added — `package/no-import-cycle` (U3, the 26th buf BASIC rule)

- **`package/no-import-cycle` rule** (`buf:PACKAGE_NO_IMPORT_CYCLE`
  parity). ERROR severity in `recommended` + `default` profiles.
  Per Phase 0 binding: file-level cyclic imports are caught at
  the COMPILE phase by both buf and protoxy; this rule fires on
  the rarer case where individual file imports are acyclic but
  the package-level import graph cycles. Emits one finding per
  cycle-closing `import` statement at the import line/column for
  byte-equivalent buf v1.69.0 parity. See `docs/solutions/best-
  practices/tarjan-scc-iterative-dfs-package-cycle-detection-
  2026-05-22.md` for the institutional knowledge captured at U3
  ce:compound.
- **`LintEngine._build_import_graph_accumulator`** pre-walk
  method (`engine.py` Step 3.5c). Iterates `compile_result.
  root_files`, builds a package-level import graph (collapsing
  multi-file P→Q edges to one), runs hand-implemented iterative
  Tarjan SCC, and emits a per-file map of cycle-closing
  `CycleEdge` entries. Reads `compile_result.source_info_-
  descriptors` for per-import line/column. Returns `None` for
  empty `root_files`, empty `MappingProxyType({})` for healthy
  codebases with no cycles.
- **`CycleEdge` dataclass** in `model.py` carrying
  `(imported_file, target_package, cycle_path, line, column)`.
- **`FileLintContext.import_cycles`** field —
  `Mapping[str, tuple[CycleEdge, ...]] | None`; populated by the
  Step 3.5c pre-walk.
- **`FileLocation` extended with optional `line: int | None` +
  `column: int | None`** (PD-12b). Open-extension change; JSON
  formatter renders `location_line` / `location_column`, SARIF
  formatter populates `physicalLocation.region.startLine` /
  `startColumn`. NO `_LINT_JSON_SCHEMA_VERSION` bump per
  [[closed-literal-discriminator-bump-trigger-2026-05-17]]
  (open extension, not a closed-Literal addition).
- **`_LintContextEmitMixin.emit()` extended with optional
  `location` kwarg** so U3's rule can emit per-import-edge with
  explicit `FileLocation(file, line, column)` rather than the
  default whole-file context location.
- **Iterative Tarjan SCC + iterative forward cycle walk**
  (~80 LOC at engine.py module level). Iterative posture
  (explicit work stack, not recursion) guards against
  `RecursionError` on SCCs ≥ ~999 packages. ce:review confirmed
  the discipline must apply to ALL DFS helpers on the same
  graph, not just Tarjan.

#### Changed — behavior delta

- **`file/syntax-specified` demoted ERROR → WARNING** in
  `recommended` + `default` profiles (D6e R4b per KD-2
  pragmatic-not-dogmatic). The rule still surfaces the signal
  but does NOT fail CI on proto2 files by default.
- **Buf-parity headline** `"25 of 26 BASIC rules"` →
  `"26 of 26 buf v1.69.0 BASIC rules"` per KD-9. Closing-arc
  complete; the v1.69.0 qualifier is load-bearing for future
  drift detection if buf ships a new BASIC rule in a later
  version.

#### Behavior changes (defaults; demotable)

**`file/syntax-specified` WARNING demotion — exit-code impact by
`--max-warnings` posture:**

| Posture | Pre-0.6.0 | Post-0.6.0 |
|---|---|---|
| `--max-warnings` unset | proto2 file: exit 1 (ERROR) | proto2 file: exit 0 (WARNING; not counted) — **silent CI-pass regression risk** |
| `--max-warnings 0` | proto2 file: exit 1 | proto2 file: exit 1 (counted as warning instead of error) |
| `--min-severity error` | proto2 file: exit 1 (ERROR passes severity floor) | proto2 file: exit 0 (WARNING filtered by severity floor) |

`package/no-import-cycle` at ERROR in `recommended` + `default`
fires on package-level cycles where individual file imports are
acyclic. Codebases with such cycles (rare in healthy projects;
file-level cycles are caught at COMPILE phase) flip CI from
green to red on upgrade. Demote per the migration recipe.

#### Pre-upgrade migration recipe

- **Want explicit ERROR enforcement of `file/syntax-specified`?**
  ```toml
  [tool.protokit.lint.severities]
  "file/syntax-specified" = "error"
  ```
- **Want proto2-strict checks?**
  ```toml
  [tool.protokit.lint]
  profile = ["default", "proto2-strict"]
  ```
- **Want to demote `field/not-required` after opting in?**
  ```toml
  [tool.protokit.lint.severities]
  "field/not-required" = "warning"
  ```
- **Have package-level import cycles you're not ready to fix?**
  ```toml
  [tool.protokit.lint.severities]
  "package/no-import-cycle" = "warning"
  ```
  Or demote to INFO for filtering out of `--min-severity warning`:
  ```toml
  [tool.protokit.lint.severities]
  "package/no-import-cycle" = "info"
  ```
  **Note**: file-level cyclic imports are caught at the protobuf
  COMPILE phase by both buf and protokit's compiler and are NOT
  affected by this rule.
- **Pin to 0.5.0 indefinitely?** `pip install protokit==0.5.0`

#### Phase 0 falsifications (audit-trail)

Two Phase 0 empirical verifications during D6e revealed
brainstorm-inherited claims that didn't survive contact with
real buf v1.69.0 behavior:

**EV-2 falsification (U2, 2026-05-22)**: the brainstorm framed
a "documented extend-block divergence" where buf would fire
`FIELD_NOT_REQUIRED` on extend-block `required` fields while
protokit (whose engine walker does not iterate
`fd.extensions_by_name` or `Message.extensions_by_name`) would
not. Both buf v1.69.0 AND protokit's compiler reject `required`
extension fields at parse layer (`invalid cardinality: 2`); the
construct cannot be compiled so no rule-level divergence exists.
`field/not-required` ships with clean buf-parity — no asterisk,
no four-site documentation, no `_PARITY_EXCEPTIONS` entry, no
walker-extension backlog. Captured at
`docs/solutions/best-practices/phase-0-empirical-verification-
falsifies-brainstorm-assumption-2026-05-22.md`.

**Two-tier behavior discovery (U3, 2026-05-22)**: the brainstorm
framed `package/no-import-cycle` as generic cross-file cycle
detection. Phase 0 revealed file-level cycles are caught at
COMPILE phase by both buf and protoxy; the rule's actual
operational ground is package-level cycles where individual
file imports are acyclic. Also: emission shape is per-import-
edge (not per-root-file fan-out as PD-6 originally bound). Plan
PD-6/PD-7/PD-8 revised before implementation. Captured at
`docs/solutions/best-practices/phase-0-narrowing-rule-reachable-
but-narrower-than-brainstorm-assumed-2026-05-22.md` (sibling to
EV-2 falsification with a different failure mode).

#### Test coverage

- **U2 parity gate** at `tests/parity/test_parity_field.py` —
  4 fixtures (good, proto2_required, proto2_optional,
  proto3_field) PASS byte-equivalent vs buf v1.69.0.
- **U3 parity gate** at `tests/parity/test_parity_package_no_-
  import_cycle.py` — 5 multi-file fixtures + 3 collection-time
  invariants. All PASS against committed buf v1.69.0 NDJSON
  snapshots at `tests/schema/lint/rules/fixtures/package_no_-
  import_cycle/_buf_smoke/recorded/*.json`.
- **`leaf_files_in_cyclic_pkg` fixture** explicitly verifies
  that sibling leaf files in cyclic packages do NOT emit
  findings — pins the over-emission UX concern as a regression
  guard (per Option B design + ce:review user concern).
- **Two-tier parity assertion** (ce:review U3 follow-up): the
  U3 parity test asserts both finding-set parity (Tier 1 via
  shared helper) AND per-finding line/column byte-equivalence
  (Tier 2 against buf's `start_line`/`start_column`). Without
  Tier 2, the Option B "byte-equivalent buf parity" design claim
  would have been documentation-only. Captured at
  `docs/solutions/best-practices/parity-gate-must-assert-at-
  design-claim-granularity-2026-05-22.md`.
- **R4b CLI exit-code regression test** at
  `tests/schema/lint/cli/test_cli_ci_gating.py::TestMaxWarnings-
  ExitLadder::test_proto2_file_under_default_profile_exits_0_-
  post_r4b_demotion` — pins the post-R4b exit-0 behavior on
  proto2 files end-to-end via CliRunner.
- **EV-1 (editions) + EV-4 (multi-file proto2+proto3 mix)
  coverage** at `tests/schema/lint/rules/test_field.py`.

#### Deferred to D6f+

- **R6 (`options/deprecated-replacement`) severity promotion to
  ERROR.**
- **R9b `"off"` severity value support** (existing `[severities]`
  overrides at `"error"`/`"warning"`/`"info"` continue to work).
- **`LintRuleSpec.parity_note` structured field** at specimen #3
  trigger per PD-10. With EV-2 falsification dropping the
  field/not-required divergence, `file/syntax-specified`
  remains the sole specimen #1; sentinel re-arms at #3.
- **Any R4 audit-pass findings from U1's audit of D6a-D6c rules**
  (with N=3/M=8-weeks PD-11 forcing-function defaults; per-item
  N/M may tighten for high-blast-radius findings).

### D6d — option-aware pack expansion + AIP-203 well-formedness (0.5.0)

D6d ships the strategic-differentiator headline as the
**0.5.0 release**: option-aware pack expansion via user-declarable
custom-annotation rules, plus the first AIP-203 well-formedness
validator for `(google.api.field_behavior)` annotation lists. Two
new rules + one new synthetic-rule infrastructure land:

1. **`custom/<user-suffix>`** — synthetic per-requirement rule_ids
   materialized from pyproject `[[tool.protokit.lint.custom_annotation_rules]]`
   array-of-tables entries. Presence + closed-value-set semantics
   over scalar option values, including enum-identifier
   normalization. Users now declare option-aware lint requirements
   in `pyproject.toml` without writing Python.
2. **`options/field-behavior-consistent`** — well-formedness
   validator for `(google.api.field_behavior)` annotation lists
   (duplicate values, `FIELD_BEHAVIOR_UNSPECIFIED` rejection per
   AIP-203, contradictory-pair detection). Three dict-shaped
   `violation_kind` arms. Ships in the `default` profile only;
   `recommended` users see zero new findings.

The buf BASIC parity numerator is unchanged at **25 of 26 +
1 scheduled**. The +1 scheduled rule is `FIELD_NOT_REQUIRED` (a
proto2-only BASIC rule); it was originally scoped for D6d but
deferred to D6e+ per the 2026-05-20 strategic-deferral note in
`docs/plans/2026-05-19-001-feat-d6d-option-aware-pack-expansion-plan.md`.
The 26th BASIC rule (`PACKAGE_NO_IMPORT_CYCLE`) also remains
deferred — its cross-file cycle-detection algorithm is not
amenable to the D6c Arch-D pre-walk accumulator pattern.

Teams using `recommended` will see no new findings. Teams using
`default` AND consuming `(google.api.field_behavior)` in their
schemas may see new warning-severity findings; the pre-upgrade
migration recipe below covers the demotion paths.

#### Added

- **`custom/<user-suffix>` synthetic-rule infrastructure** — new
  pyproject array-of-tables `[[tool.protokit.lint.custom_annotation_rules]]`
  declares option-aware annotation requirements without writing
  Python. Each entry materializes a synthetic rule_id of the form
  `custom/<rule_suffix>` participating in profile composition +
  `[severities]` overlay exactly like a built-in rule. The per-entry
  field schema (`rule_suffix`, `option`, `element_kinds`,
  `allowed_values`, `severity`) is documented in full in the README
  Schema Linting section under "Custom annotation rules" (the
  canonical source); the worked-example fixture at
  `tests/schema/lint/cli/cli_fixtures/d6d_custom_annotation/pyproject.toml`
  is the executable reference.

  Footgun to flag: `option` is the bare descriptor-pool name
  (`example.audit_level`), NOT the parenthesized proto-source form
  (`(example.audit_level)`). `pool.FindExtensionByName` accepts only
  the bare form; passing parens silently emits one
  `LintRuntimeWarning(category="custom_annotation_extension_unresolved")`
  per file instead of firing.

  Unresolved-extension behavior: when `pool.FindExtensionByName`
  raises `KeyError` (the configured extension is not in any proto
  file's compile set), the rule emits one structured
  `LintRuntimeWarning(category="custom_annotation_extension_unresolved")`
  per `(rule_id, file)` pair naming the synthetic rule_id and skips
  firing. KD-8 invariant: `BUILTIN_PACKS` MUST NEVER ship a
  `custom/*` rule_id — the `custom/` prefix is reserved for user
  declarations.

- **`options/field-behavior-consistent`** — warning-severity rule
  in the `default` profile only. AIP-203 well-formedness validator
  with three dict-shaped `violation_kind` arms:

  * `options/field-behavior-consistent/duplicate-value` — same
    `FieldBehavior` enum identifier appears 2+ times in the
    annotation list. One finding per duplicated value (NOT per
    duplicate occurrence), emitted in alphabetic-by-value order.
  * `options/field-behavior-consistent/unspecified-value` —
    `FIELD_BEHAVIOR_UNSPECIFIED` appears in the list. AIP-203
    forbids the zero value as an explicit annotation.
  * `options/field-behavior-consistent/contradictory-pair` — two
    values appear that are mutually exclusive under AIP-203
    semantics. Curated set (5 pairs): `(OPTIONAL, REQUIRED)`,
    `(REQUIRED, OUTPUT_ONLY)`, `(INPUT_ONLY, OUTPUT_ONLY)`,
    `(IMMUTABLE, OUTPUT_ONLY)`, `(IMMUTABLE, INPUT_ONLY)`.
    `IDENTIFIER`-based contradictions are deliberately excluded —
    AIP-203 contextual semantics make a hard contradiction claim
    harder to defend.

  Unresolved-extension behavior: when the user's compile set does
  NOT include `google/api/field_behavior.proto` (i.e.,
  `pool.FindExtensionByName("google.api.field_behavior")` raises),
  the rule emits one deduplicated
  `LintRuntimeWarning(category="extension_unresolved")` per file and
  skips firing.

- **Dynamic-pool extension-access helper** — new internal module
  `protokit.schema.lint._extension_access` (helpers:
  `get_pool_bound_options_class`,
  `resolve_enum_value_for_comparison`) factors out the bootstrap-
  pool re-parse workaround that lets option-aware rules read
  extension values registered through `protoxy`-built
  `DescriptorPool`. The naive `protokit.options.get_option_value`
  path raises `KeyError("Extension doesn't match")` on dynamic-pool
  extension descriptors; the helper builds a pool-bound options
  class via `message_factory.GetMessageClass` and re-parses the
  serialized options bytes. Classified INTERNAL — consumers should
  not depend on the module path or signatures.

- **Worked example** — `tests/schema/lint/cli/test_d6d_custom_annotation_example.py`
  exercises the full `custom/<suffix>` lifecycle end-to-end:
  pyproject config → synthetic rule materialization → finding
  emission → JSON output, plus presence-only and closed-value-set
  variants and severity-overlay verification.

#### Changed

- **`_LINT_JSON_SCHEMA_VERSION`** advances `"0.3"` → `"0.5"` in two
  closed-Literal-discriminator steps per the bump contract at
  `_builtin_lint.py:227-312`:

  * **U1**: `"0.3"` → `"0.4"` for the sixth `LintRuntimeWarning.category`
    value `"custom_annotation_extension_unresolved"` (synthetic
    `custom/<suffix>` rule skipped because its configured
    extension is not registered in the compile pool).
  * **U2**: `"0.4"` → `"0.5"` for the seventh value
    `"extension_unresolved"` (built-in option-aware rule skipped
    because the compile set is missing the well-known proto
    its depended-on extension lives in). Distinct from the U1
    sixth value: same root condition, different root cause (user
    mis-configured pyproject vs user did not include googleapis).
    Consumers discriminate via the `category` field without text
    parsing.

  Consumers that exhaustively switch on `LintRuntimeWarning.category`
  (per the mypy-strict narrowing pattern documented on the
  dataclass) MUST extend their match construct to handle BOTH new
  cases. The two cases share a deduplication discipline (at most
  one warning per `(rule_id, file)` pair) so consumer cardinality
  is bounded.

- **`BUILTIN_PACKS`** grows from 7 packs to 8 packs with the
  addition of `options.field_behavior`. The auto-load tuple order
  is unchanged for existing packs.

#### Behavior changes (defaults; demotable)

- **`custom/<suffix>` synthetic rules** fire ONLY when the user
  declares them in `pyproject.toml`. Zero-config invocation is
  unaffected.

- **`options/field-behavior-consistent`** fires under the `default`
  profile. `--profile recommended` users see ZERO new findings on
  the 0.5.0 upgrade. `default`-profile users whose schemas consume
  `(google.api.field_behavior)` will see new warning-severity
  findings if their annotation lists contain duplicates, the
  `FIELD_BEHAVIOR_UNSPECIFIED` zero value, or any of the 5 curated
  contradictory pairs. The rule does NOT fire on absence — it is a
  well-formedness validator, not a presence enforcer.

- **Wire format** — both structured-output formats advance their
  schema-version field to `"0.5"` in parity:
  - `lint_json["schema_version"] = "0.5"`
  - `lint_sarif.runs[0].properties.lint_schema_version = "0.5"`

  Both surfaces share the same `_LINT_JSON_SCHEMA_VERSION` constant
  so the values always match. Both new `LintRuntimeWarning.category`
  values must be handled by exhaustive-switch consumers per the
  closed-Literal contract documented above.

#### Pre-upgrade migration recipe

Teams whose CI passes on protokit 0.4.0 fall into four groups:

- **`recommended` users** — no migration needed. Zero new findings
  (this rule ships in `default` only).
- **`default` users without `(google.api.field_behavior)`** —
  zero new findings, but the rule does emit one
  `LintRuntimeWarning(category="extension_unresolved")` per file
  on every invocation (deduplicated per `(rule_id, file)`).
  Visible in `--format=json runtime_warnings`, in `--statistics`
  output as `runtime-warnings: N`, and (above the `_LINT_HUMAN_SUMMARIZATION_THRESHOLD`)
  in stderr. To suppress the warning surface entirely: demote the
  rule (see path 2 below). To keep the warning while suppressing
  the `--statistics` row: `--no-statistics`.
- **`default` users with `(google.api.field_behavior)`** — review
  new findings; choose one of the demotion paths below per rule.
  Each affected field can emit up to ~14 findings (5 contradictory
  pairs + 8 duplicate-value arms + 1 unspecified-value); a
  googleapis-heavy schema with K affected fields has worst-case
  ~14·K findings on first 0.5.0 invocation.
- **`default` users with `--max-warnings N`** — warning-severity
  findings count against `--max-warnings`. Teams with a tight cap
  may need to raise the cap, demote the rule, or fix the schema
  before upgrading.

**Numbered demotion paths**, ranked by team situation:

1. **Fix the schema — preferred** (when the violation is real
   schema drift). Remove duplicate `field_behavior` entries,
   replace `FIELD_BEHAVIOR_UNSPECIFIED` with a meaningful
   value (or drop the annotation entirely), and resolve
   contradictory pairs per AIP-203 guidance.

2. **Demote the rule to `info`** (per-rule severity escape hatch).
   The rule ships at `warning`; demoting to `info` drops the
   findings below the default `min_severity = "warning"` floor at
   `LintProfile.min_severity` (see `model.py`), so they enter
   `report.filtered_count` rather than `report.findings`. The
   `--statistics` footer shows them under `filtered: N`. To
   surface the demoted findings as advisory output, pair with
   `--min-severity info`:
   ```toml
   [tool.protokit.lint.severities]
   "options/field-behavior-consistent" = "info"
   ```
   ```bash
   protokit lint --min-severity info <inputs>   # to see them
   ```
   Note: `"off"` is **NOT** currently a valid severity value
   (`LintSeverity` accepts `"error"` / `"warning"` / `"info"`
   only). The R9b per-rule disable mechanism is scheduled for
   D6e+; until then, demote to `info` instead. If the
   `[tool.protokit.lint.severities]` table already exists in your
   `pyproject.toml`, **add the key to the existing table** rather
   than re-declaring the section header (TOML rejects duplicate
   section headers).

3. **Raise `--max-warnings N`** (or remove the cap) — for teams
   whose only blocker is the warning-count gate, not the findings
   themselves.

**No `pyproject.toml`?** A 3-line stub at the repo root suffices —
protokit discovers `pyproject.toml` independently of pip/build
tooling, so the file does not need to define a build system. (See
the D6c migration recipe for the exact stub shape.)

#### Upgrade notes (triage recipe)

1. Run `protokit lint <inputs>` against your protos under the
   `default` profile.
2. If exit code 0 and `--statistics` shows no warning rows: no
   migration needed beyond optionally suppressing the
   `runtime-warnings: N` row (see groups above).
3. If `options/field-behavior-consistent` findings appear: choose
   one of the demotion paths above. Most teams will land on path
   1 (fix the schema) for AIP-203 well-formedness issues.
4. Re-run after applying demotion/fix; commit the updated
   `pyproject.toml` or schema fix.

#### Worked example (synthetic `custom/<suffix>`)

The CI-runnable fixture at
`tests/schema/lint/cli/test_d6d_custom_annotation_example.py` +
`tests/schema/lint/cli/cli_fixtures/d6d_custom_annotation/`
demonstrates the full custom-annotation lifecycle. A minimal
pyproject entry:

```toml
[[tool.protokit.lint.custom_annotation_rules]]
rule_suffix    = "audit-required"
option         = "example.audit_level"
element_kinds  = ["method"]
allowed_values = ["LOW", "HIGH", "CRITICAL"]
severity       = "error"
```

materializes a synthetic `custom/audit-required` rule that fires
on every method whose `(example.audit_level)` annotation is absent OR set to
a value outside `{LOW, HIGH, CRITICAL}`. The extension itself is
defined in user-controlled proto files (e.g.,
`extend google.protobuf.MethodOptions { optional AuditLevel
audit_level = 50000; }`); protokit reads the option value via the
dynamic-pool re-parse helper at
`protokit.schema.lint._extension_access`.

#### Consumer migration (Python API + JSON / SARIF wire format)

- **`LintRuntimeWarning.category`** Literal grows from 5 values to
  7. Consumers exhaustively switching on `category` (per the
  mypy-strict narrowing pattern documented at
  `src/protokit/schema/lint/model.py:573-581`) MUST add branches
  for `"custom_annotation_extension_unresolved"` (D6d U1) and
  `"extension_unresolved"` (D6d U2). The two values share a root
  symptom (the rule could not resolve its configured extension)
  but discriminate the root cause (user pyproject mis-configuration
  vs user compile-set incomplete).

- **`custom/<suffix>` finding shape** (synthetic-rule path):
  - `violation_kind` is one of `"custom-annotation-absent"` (the
    option is not present on the descriptor) or
    `"custom-annotation-value-mismatch"` (the option is present
    but its value is outside `allowed_values`).
  - `params` always carries `"rule_id"` (the synthetic
    `custom/<suffix>` id) and `"option"` (the configured
    fully-qualified extension name in bare form).
  - `params["actual_value"]` is present only on the value-mismatch
    arm — a string-coerced enum identifier (or raw scalar) of the
    rejected value.

- **`options/field-behavior-consistent` finding shape** (built-in
  AIP-203 rule):
  - `violation_kind` is one of `"options/field-behavior-consistent/duplicate-value"`,
    `"options/field-behavior-consistent/unspecified-value"`, or
    `"options/field-behavior-consistent/contradictory-pair"`.
  - `params` always carries `"field_name"`. The duplicate + unspecified
    arms additionally carry `"value"`; the contradictory-pair arm
    carries `"value_a"` + `"value_b"` (alphabetically sorted).

- **`protokit.schema.lint._extension_access`** is **INTERNAL** —
  not part of the public surface; consumers that need pool-bound
  extension access should use
  `protokit.options.get_option_value` for ordinary descriptor-pool
  cases and treat the dynamic-pool re-parse workaround as
  implementation detail.

- **`protokit.schema.lint._custom_rules`** is similarly
  **INTERNAL** — the synthetic-module materialization contract may
  change pre-1.0 as the option-aware path accumulates real-world
  evidence.

- **`CustomAnnotationRuleSpec`** at
  `protokit.schema.lint._config` is **INTERNAL** — the spec
  dataclass models a validated pyproject entry; consumers should
  treat declarative configuration via the pyproject table as the
  public surface.

#### Deferred to D6e+

D6d explicitly defers the following items (rolled forward from D6c
+ the 2026-05-20 strategic-deferral revision):

- **`FIELD_NOT_REQUIRED`** — the proto2-only buf BASIC rule
  originally scoped for D6d U3. Deferred per the umbrella
  brainstorm Strategic Deferral section: the rule's scope, while
  individually small, would have widened the D6d release surface
  and risked muddying the headline. The +1 scheduled rule rolls
  forward; D6e+ owns implementation.
- **`PACKAGE_NO_IMPORT_CYCLE`** — the 26th buf BASIC rule;
  cross-file cycle-detection algorithm requires DAG construction
  + cycle detection, not amenable to the D6c Arch-D accumulator
  pattern.
- **R6 deprecated-replacement promotion to `recommended`** —
  pending real-world experience with the leading-comment heuristic
  accuracy + the corpus signal from the 0.5.0 release window.
- **`strict` profile rule enumeration** — placeholder profile name
  reserved for a future curation pass.
- **R9b per-rule disable/enable CLI flag** — `[severities] = "off"`
  remains the de-facto disable mechanism.
- **`LintLocation` exhaustiveness contract decision** —
  whether the location discriminator becomes a closed Literal or
  remains an open structural variant.
- **`IDENTIFIER`-based contradictory pairs in
  `options/field-behavior-consistent`** — pending AIP-203 corpus
  evidence; the curated set holds the line at 5 pairs.
- **Long-lived engine config-reload contract for synthetic rules**
  — D6d's `_custom_rules` materialization assumes a CLI-style
  one-shot engine lifecycle (the synthetic module is built once at
  config-load); long-lived consumers (D6e+ MCP / IDE integrations)
  will need a rebuild discipline documented as part of the engine
  API.

### D6c — cross-file lint dispatch (Arch-D pre-walk accumulator) + 25/26 buf BASIC parity (0.4.0)

D6c adds the first cross-file lint dispatch infrastructure (Arch-D
pre-walk accumulator + `FileLintContext.directory_packages` field) and
the first two rules to consume it: R8 `package/same-directory` and R8b
`package/directory-same-package`. Combined with the [Corrected] entry
below, this brings `protokit lint` to **25 of 26 buf BASIC rules**.
The remaining 26th, `PACKAGE_NO_IMPORT_CYCLE`, defers to D6d (its
cross-file cycle-detection algorithm — DAG construction + cycle
detection — is not amenable to the Arch-D accumulator pattern).
`FIELD_NOT_REQUIRED` (a proto2-only buf BASIC rule, not counted in
protokit's 26-rule baseline) also defers to D6d alongside.

Teams whose protos have inconsistent package/directory layout (the
same package declared in multiple directories, or multiple packages
declared in the same directory) will see NEW error-severity findings
on upgrade; the pre-upgrade migration recipe below covers the 5
demotion paths.

#### Added

- **R8 `package/same-directory`** — ERROR-severity cross-file rule in
  both `recommended` + `default` profiles. Fires when files declaring
  the same proto `package` live in two or more distinct directories.
  Message template:
  `Multiple directories "<dir-list>" contain files with package "<pkg>".`
  Directory list is alphabetic, comma-no-space (`d1,d2,d3`); proto-root
  files canonicalize to `"."` (matching buf v1.69.0 byte-for-byte).

- **R8b `package/directory-same-package`** — ERROR-severity cross-file
  rule in both `recommended` + `default` profiles. Fires when a single
  directory contains files declaring two or more distinct packages
  (or, per buf's empirical behavior, a mix of declared-package + no-
  package files). **Three** distinct message templates discriminate
  the directory's package mix, surfaced through three `violation_kind`
  closed-set discriminator values:
  - Standard (`package/directory-same-package`) — 2+ declared packages,
    no packageless files:
    `Multiple packages "<pkg-list>" detected within directory "<dir>".`
  - Empty-mixed-single (`package/directory-same-package/empty-mixed-single`)
    — exactly 1 declared package + ≥1 packageless file:
    `Package "<declared-pkg>" and file with no package detected within directory "<dir>".`
  - Empty-mixed-multi (`package/directory-same-package/empty-mixed-multi`)
    — 2+ declared packages + ≥1 packageless file:
    `Multiple packages "<pkg-list>" and file with no package detected within directory "<dir>".`

  The third arm was added at U3 ce:work after the parity gate's first
  run surfaced a real divergence from buf v1.69.0 on the multi-declared
  + packageless case — the brainstorm-inherited claim that buf produces
  a single declared-package value in this template was empirically
  wrong. See [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]]
  Case 4 for the latent-helper-bug pattern.

- **Arch-D pre-walk accumulator** — `LintEngine._build_directory_package_accumulator`
  returns a dual-view `(by_package, by_directory)` tuple from one
  pass over `compile_result.root_files`. Cross-file rule families
  consume the views via `FileLintContext.directory_packages` (per-
  package inner view) and `FileLintContext.directory_packages_by_dir`
  (per-directory inverted index — O(1) lookup for R8b). Lifecycle
  mirrors R7's `_build_package_options_accumulator`: built once per
  `run()`, threaded into every `FileLintContext`, reset to `None` in
  the `finally` block.

- **10-fixture empirical buf-parity gate** at
  `tests/parity/test_parity_package_directory.py` — SHA-pinned buf
  v1.69.0 NDJSON snapshots covering all R8 + R8b boundary cases:
  matched-dir, mismatched-dir, split-package-multi-dir, single-file-dir,
  proto-root-mixed (5 base); no-package-mixed (multi-declared +
  packageless, the OQ-4 sub-question); n3-directories-split,
  n3-packages-same-dir, cofire-r8-r8b (3 edge-case discriminators);
  single-declared-no-package (ce:review Finding #3 follow-up exercising
  the empty-mixed-single arm separately from the multi case).

- **`assert_parity_multi_file` three-arm partition** at
  `tests/parity/conftest.py` — extended to dispatch on
  R7-family + R8/R8b family + remaining-rules via three frozensets
  derived from `RULE_ID_MAP` (per KTD-3 + KTD-12: no sibling-isolated
  rule_id maps; consume the SSOT directly).

#### Corrected

- **buf BASIC parity numerator: `17 of 18` → `25 of 26`.** The inherited
  "18 buf BASIC rules" claim from D6a / D6b CHANGELOG sections was
  empirically wrong — D6c Phase 0 verification against buf v1.69.0
  documentation enumerated **26 BASIC rules**. Of those, protokit
  shipped 23 by literal `buf:` source_spec attribution through D6b
  (24 effective, with `naming/snake-case-fields` semantic-equivalence
  to `FIELD_LOWER_SNAKE_CASE`). D6c addresses both the count and the
  audit trail:
  - R8 + R8b add 2 rules → 25 of 26.
  - `naming/snake-case-fields` source_spec corrected from
    `"https://google.aip.dev/122"` to `"buf:FIELD_LOWER_SNAKE_CASE"`
    so the 25-of-26 numerator is grep-visible in
    `--list-rules --format=json` output rather than depending on
    semantic-equivalence reasoning. AIP-122 attribution moved to the
    rule module docstring.

  Historical D6a + D6b CHANGELOG sections retain their original
  numerator framing as the audit trail of past deliberation — the
  correction lives here, not as a rewrite of past sections. See
  [[plan-review-verify-prior-art-citations-2026-05-15]] for the
  brainstorm-time discipline that should have caught this earlier
  in the delivery chain.

#### Fixed

- **U7 KD-7 hygiene consolidation** — `_build_package_same_rule_id_map`
  at `tests/parity/test_parity_package_same.py:84-117` deleted in
  favor of consuming `RULE_ID_MAP` from
  `tests/parity/conftest.py` directly. The R7 parametrize source
  now derives the proto-id → buf-id map by filtering `RULE_ID_MAP`
  on the `"buf:PACKAGE_SAME_"` prefix.
- **Compound-backslash+quote escape parity** — new BUF_BINARY snapshot
  at `tests/schema/lint/rules/fixtures/package_same/_buf_smoke/recorded/`
  covers the case where an option value contains both `\` and `"` in
  the same string. Validates `_escape_message_value`'s two-step
  backslash-then-quote order against buf v1.69.0 byte-for-byte.

#### Behavior changes (defaults; demotable)

- **R8 + R8b fire as `error` on both `recommended` and `default`
  profiles.** Teams whose protos have cross-directory package
  scattering OR multiple packages in a single directory will see
  NEW error-severity findings on first 0.4.0 invocation. This is
  buf BASIC parity behavior; both rules surface real cross-file
  consistency issues that buf v1.69.0 also flags.

- **Wire format unchanged** — `lint_json["schema_version"]` stays
  `"0.3"`; `lint_sarif.runs[0].properties.lint_schema_version` stays
  `"0.3"`. R8 + R8b add new `rule_id` strings but `findings` is an
  additive list and `LintRuntimeWarning.category` Literal is
  unchanged.

#### Pre-upgrade migration recipe

Teams whose CI currently passes on protokit 0.3.0 with
`--profile recommended` and whose protos have cross-directory
package scattering OR multiple packages in a single directory will
see RED CI on first 0.4.0 invocation.

**Worst-case adoption math.** A package with M files scattered
across N > 1 directories produces M R8 findings (one per file —
all-disagreers-fire matching buf v1.69.0). A directory containing
K distinct packages produces files_in_dir R8b findings (one per
file in the directory). The combined upper bound on a mixed-
layout legacy corpus is the sum of M_p findings across each
cross-directory package p, plus the sum of files_d findings
across each multi-package directory d.
Mitigations below scale per-rule.

**5 numbered demotion paths**, ranked by team situation (not by
"rightness"):

1. **Fix the layout — preferred** (when the layout drift is
   unintentional). Reorganize files so each package lives in a
   single directory (R8 path) and each directory contains files
   from a single package (R8b path). When co-fire occurs on the
   same file (KTD-9): **resolve R8b first** (split the directory
   into single-package subdirectories), then R8 typically dissolves
   as a side-effect.

2. **Demote a specific R8/R8b rule to `warning`** (per-rule severity
   escape hatch; findings stay visible but don't fail CI). Add to
   `pyproject.toml`:
   ```toml
   [tool.protokit.lint.severities]
   "package/same-directory" = "warning"
   "package/directory-same-package" = "warning"
   ```
   Multiple keys compose. Demoted rules still report findings but
   do not fail CI (under default `--min-severity error`). Demote
   to `info` for fully advisory output.

3. **Disable a specific rule** (legitimate for INTENTIONAL layout
   drift — e.g., a polyrepo monorepo where each subdirectory is
   independently owned and intentionally lives in its own package):
   ```toml
   [tool.protokit.lint.severities]
   "package/same-directory" = "off"
   ```
   Disabled rules are invisible to downstream consumers of
   `lint_json`/`lint_sarif`; prefer demotion to `warning` when you
   want findings to remain visible.

4. **Pin to the prior minor version** (deferral fallback — last
   resort):
   ```toml
   # pyproject.toml or requirements.txt
   "protokit~=0.3.0"
   ```
   Reserves time to address R8 + R8b findings on the team's
   schedule. **Cost**: pinning forgoes future 0.4.x bug fixes for
   the rule families you already use. Prefer paths 1-3 for teams
   who plan to remain on protokit beyond one quarter.

5. **Python API consumers** — for programs invoking `LintEngine`
   directly (not through the `protokit lint` CLI), apply the
   overlay via `dataclasses.replace` on the resolved profile:
   ```python
   from dataclasses import replace
   from protokit.schema.lint.model import LintProfile, LintSeverity
   from protokit.schema.lint.rules import package

   base = LintProfile.from_pack(package, "default")
   overrides = {
       "package/same-directory": LintSeverity.WARNING,
       "package/directory-same-package": LintSeverity.WARNING,
   }
   profile = replace(
       base,
       rule_severity_overrides={
           **base.rule_severity_overrides, **overrides,
       },
   )
   ```
   Notes: `LintProfile` is a frozen dataclass — mutate via
   `dataclasses.replace`, not attribute assignment.
   `rule_severity_overrides` keys are `rule_id` strings; values are
   `LintSeverity` enum members (`ERROR`/`WARNING`/`INFO`), not raw
   strings. `LintProfile.compose(*profiles)` composes multiple
   `LintProfile` instances (most-strict-wins for severity); it does
   NOT accept a profile + dict.

**No `pyproject.toml`? Create a minimal one.** Paths 2-3 require a
`pyproject.toml` for the `[tool.protokit.lint.severities]` overlay.
Teams using `requirements.txt`-only Python tooling can add a 3-line
stub at the repo root:

```toml
[tool.protokit.lint.severities]
"package/same-directory" = "warning"
```

protokit discovers `pyproject.toml` independently of pip/build
tooling — the file does not need to define a build system.

**Accepted-tradeoff scenarios to plan for:**

- **Empty-package mixed-directory.** Files without an explicit
  `package` declaration that share a directory with declared-package
  files will trigger R8b's empty-package message template. Common
  on legacy corpora that gradually added `package` declarations
  per-file rather than per-directory. Mitigations: declare
  `package` on all files in the directory (preferred), OR demote
  `package/directory-same-package` and address gradually.

- **Vendored / generated protos.** Vendored well-known-types,
  generated stubs, or imported third-party protos may have layout
  patterns out of your team's control. Mitigations: `exclude`
  vendored paths via the `exclude` key in `pyproject.toml`
  (gitignore-style globs), OR demote R8/R8b per-rule for repos
  that intentionally vendor cross-layout protos.

- **Co-fire scenarios (KTD-9).** When R8 and R8b both fire on the
  same file, treat R8b as the primary signal: a directory with
  multiple packages is the structural cause; the cross-directory
  package spread is often a secondary consequence. Fix R8b first;
  R8 frequently dissolves once each directory has a single package.

#### Upgrade notes (triage recipe)

1. Run `protokit lint --profile recommended <inputs>` against your
   protos.
2. If exit code 0: no migration needed; the bump is clean.
3. If R8 / R8b findings appear: choose one of the 5 demotion paths
   above per rule. Most teams will land on path 1 (fix the layout)
   for unintentional drift and path 3 (`"off"` overlay) for
   intentional per-subsystem divergence.
4. For co-fire situations, fix R8b first (split directories into
   single-package), then re-run — R8 commonly dissolves.
5. Re-run after applying demotion/fix; commit the updated
   `pyproject.toml` or proto layout fix.

#### Consumer migration (Python API)

- **`FileLintContext.directory_packages`** (new at D6c U1) and
  **`FileLintContext.directory_packages_by_dir`** (new at D6c U1)
  are **INTERNAL** — not part of the public surface; consumers
  integrating with the file-context object should treat them as
  implementation detail. Cross-file rule callables consume them via
  the standard `@lint_rule`-decorated signature; the field shapes
  may change pre-1.0.

- **`LintEngine._build_directory_package_accumulator`** is
  similarly INTERNAL — the dual-view shape `(by_package,
  by_directory)` is the current accumulator contract for D6c's
  cross-file rule family; future rule families may extend the
  return shape.

#### Deferred to D6d

- `PACKAGE_NO_IMPORT_CYCLE` (the 26th buf BASIC rule; cross-file
  cycle-detection algorithm — DAG construction + cycle detection
  — not amenable to Arch-D accumulator pattern).
- `FIELD_NOT_REQUIRED` (proto2-only BASIC rule, not counted in
  protokit's 26-rule baseline; trivial single-unit add via existing
  `ElementKind.FIELD` check).
- R6 promotion to `error` severity (pending real-world experience
  with the leading-comment heuristic accuracy).
- R9b per-rule disable/enable CLI flag (`[severities] = "off"`
  is the current de-facto disable mechanism).
- `strict` profile rule enumeration.
- Option-aware pack expansion (R6 family successors) — the
  strategic differentiator path, gets its own delivery.
- `LintLocation` exhaustiveness contract decision.

### D6b — option-aware path + cross-language buf BASIC parity (0.3.0)

> **Audit-trail note:** The "17 of 18 buf BASIC rules" claim below
> was empirically corrected at D6c — buf BASIC totals 26 rules; D6b
> shipped 23 of 26 by literal `buf:` source_spec attribution (24
> effective with `naming/snake-case-fields` semantic-equivalence).
> See the D6c `#### Corrected` subsection above for the full audit
> trail.

D6b adds the first option-aware rules (R6 deprecated-replacement
family) + cross-language buf-BASIC parity (R7 PACKAGE_SAME_* family),
bringing `protokit lint` to **17 of 18 buf BASIC rules**. The 18th
(`package/same-directory`) defers to D6c — its cross-file rule kind
requires new ElementKind + LintLocation discriminant work scoped for
its own architectural delivery. Multi-language teams whose protos
have cross-file option disagreement will see NEW error-severity
findings on the upgrade; the pre-upgrade migration recipe below
covers the 4 demotion paths.

#### Added

- **R6 deprecated-replacement family** — 5 warning-severity rules in
  the `default` profile only: `options/deprecated-{enum,enum-value,
  field,message,method}-must-have-replacement-comment`. First
  option-aware rules + first leading-comment-introspection consumer.
  Rules fire when `*Options.deprecated = true` is set without a
  `[replaced-by: <X>]` leading-comment pointer. The `recommended`
  profile is untouched (R6 has no buf BASIC analogue); severity
  bounded to `warning` to contain the heuristic-regex blast radius.

- **R7 PACKAGE_SAME_\* family** — 7 ERROR-severity rules in BOTH
  `recommended` + `default` profiles, covering cross-language
  namespace consistency:
  - `package/same-go-package` → buf `PACKAGE_SAME_GO_PACKAGE`
  - `package/same-java-package` → buf `PACKAGE_SAME_JAVA_PACKAGE`
  - `package/same-csharp-namespace` → buf `PACKAGE_SAME_CSHARP_NAMESPACE`
  - `package/same-php-namespace` → buf `PACKAGE_SAME_PHP_NAMESPACE`
  - `package/same-ruby-package` → buf `PACKAGE_SAME_RUBY_PACKAGE`
  - `package/same-swift-prefix` → buf `PACKAGE_SAME_SWIFT_PREFIX`
  - `package/same-java-multiple-files` → buf `PACKAGE_SAME_JAVA_MULTIPLE_FILES`

  All-disagreers-fire semantics: every file in a package with a
  divergent value gets one finding per affected option. **Validated
  by U6's empirical parity gate** against 21 SHA-pinned buf v1.69.0
  NDJSON snapshots committed at U4a.

- **R9 `severities_unloaded_rule` category** — 5th value on
  `LintRuntimeWarning.category` Literal. **CLI-synthesized emit
  site MIGRATED** from `"unloaded_rule"` to
  `"severities_unloaded_rule"`; engine-synthesized emit site
  unchanged. Closes the D6a U9 KTD-2 accepted-conflation trip-wire
  so programmatic consumers can switch on `category` instead of
  matching the `"[tool.protokit.lint.severities]"` message substring.

- **Multi-file parity harness extension** at
  `tests/parity/conftest.py` — `BufFinding` NamedTuple +
  `parse_buf_recorded_snapshot()` + `run_protokit_lint_multi_file()`
  + `assert_parity_multi_file()`. Reusable by future multi-file
  rule families (D6c R8 candidate).

- **Empirical parity gate** at `tests/parity/test_parity_package_same.py`
  — 21 parametrized cases + 5 collection-time invariants R25(a-e);
  recorded-snapshot mode runs in the required `test` CI job (no
  BUF_BINARY dependency).

#### Fixed

- **CLI rule-pack idempotency at the BUILTIN_PACKS boundary.** When
  a user passes `--rule-pack=<pack>` for a pack now in BUILTIN_PACKS
  (post-U7), the engine's load_rule_pack short-circuits the second
  load (`engine.py:241-242`) but the CLI's `loaded_packs` list
  would still append a duplicate. That broke the R25 multi-pack
  provenance line's `zip(loaded_packs_tuple,
  _active_rule_ids_per_pack(...).values(), strict=True)` because
  the helper dict de-dups by `pack.__name__` while the tuple did
  not. Fix: dedup `loaded_packs` at CLI append time. Bug was
  unreachable pre-U7 (since `package_same` was not in BUILTIN_PACKS);
  surfaced by U7's idempotency regression tests at flip time.

#### Wire format

- `lint_json["schema_version"]` + `lint_sarif.runs[0].properties.lint_schema_version`
  bumped `"0.2"` → `"0.3"` (shipped at D6b U5). The bump is driven
  ONLY by R9's `LintRuntimeWarning.category` Literal widening per
  the refined bump-contract at `_builtin_lint.py:227-270` (closed
  Literal discriminators vs open severity-string ladders). New
  `rule_id` strings from R6 + R7 do NOT contribute additional
  bumps — `findings` is an additive list and consumers tolerate
  unknown rule_ids.

#### Behavior changes (defaults; demotable)

- **R6 family fires as `warning` on `default` profile only.**
  Teams using `--profile recommended` (the buf-parity default) see
  ZERO new R6 findings. Teams on `default` (or with custom profile
  composition that includes the R6 ruleset) will see deprecated-
  replacement warnings.

- **R7 family fires as `error` on both `recommended` and `default`
  profiles.** Multi-language teams running `protokit lint --profile
  recommended <inputs>` in CI will see NEW error-severity findings
  when cross-file option values disagree within a proto package
  (e.g., `go_package`, `java_package`, `csharp_namespace` differing
  across files in the same package). This is buf BASIC parity
  behavior; surfaces real cross-language config inconsistency.

#### Pre-upgrade migration recipe

Cross-language teams whose CI currently passes on protokit 0.2.0
with `--profile recommended` and whose protos have cross-file option
disagreement will see RED CI on first 0.3.0 invocation.

**Worst-case adoption math.** A 5-file package with disagreement
produces up to 5 × 7 = 35 findings. A 20-file no-package legacy
corpus where the `""`-namespace aggregation kicks in (proto files
without explicit `package` declarations get grouped into the
empty-package bucket and compared as one cross-file scope)
produces up to **140 findings** (20 × 7) on the upgrade. Plan
adoption sizing against the combined worst case for your repo.

**4 numbered demotion paths**, ranked by team situation (not by
"rightness"):

1. **Fix the disagreement** (when the disagreement is unintentional).
   R7 fires because option values differ across files in the same
   package — buf v1.69.0 parity behavior treats this as a correctness
   signal. Decide a canonical value per `option_attr` per package;
   update outlier files to match.

2. **Demote a specific R7 rule to `warning`** (per-rule severity
   escape hatch; suitable for "I want findings to remain visible
   but not fail CI"). Add to `pyproject.toml`:
   ```toml
   [tool.protokit.lint.severities]
   "package/same-go-package" = "warning"
   ```
   Multiple keys compose. Demoted rules still report findings but
   do not fail CI (under default `--min-severity error`). Demote
   to `info` for fully advisory output.

3. **Disable a specific R7 rule** (legitimate for INTENTIONAL
   disagreement that expresses team convention):
   ```toml
   [tool.protokit.lint.severities]
   "package/same-go-package" = "off"
   ```
   Legitimate when the disagreement is by design — e.g., a polyrepo
   where each `.proto` file ships in its own Go module has
   intentionally divergent `go_package` values; demoting
   `package/same-go-package` to `"off"` for this repo is the
   correct long-term answer, NOT a workaround. Disabled rules are
   invisible to downstream consumers of `lint_json`/`lint_sarif`;
   prefer demotion to `warning` when you want findings to remain
   visible.

4. **Pin to the prior minor version** (deferral fallback — last
   resort):
   ```toml
   # pyproject.toml or requirements.txt
   "protokit~=0.2.0"
   ```
   Reserves time to address R7 findings on the team's schedule.
   **Cost**: pinning forgoes future 0.3.x bug fixes for the rule
   families you already use. Prefer paths 1-3 for teams who plan to
   remain on protokit beyond one quarter; re-evaluate at each 0.3.x
   patch release.

**No `pyproject.toml`? Create a minimal one.** Paths 2-3 require a
`pyproject.toml` for the `[tool.protokit.lint.severities]` overlay.
Teams using `requirements.txt`-only Python tooling can add a 3-line
stub at the repo root:

```toml
[tool.protokit.lint.severities]
"package/same-go-package" = "warning"
```

protokit discovers `pyproject.toml` independently of pip/build
tooling — the file does not need to define a build system. Path 4
(version pin in `requirements.txt`) is the only `requirements.txt`-
only escape hatch.

**Accepted-tradeoff scenarios to plan for:**

- **`""`-package aggregation.** Proto files without an explicit
  `package` declaration get grouped into the empty-package bucket.
  On a 20-file no-package legacy corpus, all 7 R7 rules cross-
  compare every file against every other file in that bucket,
  producing the worst-case 140 findings. Mitigations: declare
  `package` on all protos (preferred — gives R7's per-package
  scope a chance to do useful work), OR demote PACKAGE_SAME_* per-
  rule via `[severities]` for known-no-package globs (combine with
  `exclude` for vendored paths).

- **Transitive-import supply chain.** R7 fires across the cross-
  package boundary when a third-party `import` brings in protos
  with divergent option values from your in-repo protos. The
  upstream change can trip your CI even though your repo didn't
  change. Mitigations: pin dependency versions in your build
  graph; OR demote PACKAGE_SAME_* when third-party imports
  introduce conflicts.

- **WKT enforcement.** Users with non-standard `google/protobuf/`
  vendoring (vendored well-known-type stubs with differing option
  values) may see surprise findings against vendored protos.
  Mitigations: `exclude` the vendored path, OR confirm vendoring
  aligns with upstream protobuf option values.

#### Upgrade notes (triage recipe)

1. Run `protokit lint --profile recommended <inputs>` against your
   protos.
2. If exit code 0: no migration needed; the bump is clean.
3. If R7 findings appear: choose one of the 4 demotion paths above
   per rule. Most teams will land on path 1 (fix) for unintentional
   disagreement and path 3 (`"off"` overlay) for intentional
   per-service divergence.
4. If R6 findings appear (default profile only): add `[replaced-by:
   <X>]` comments to deprecated fields / methods / enums, OR
   demote `options/deprecated-*` rules via `[severities]`
   (warning → info).
5. Re-run after applying demotion/fix; commit the updated
   `pyproject.toml` or proto fix.

#### Consumer migration (Python API)

- **`LintRuntimeWarning.category` is a CLOSED Literal DISCRIMINATOR.**
  The 5 enumerated values (`"rule_exception"`, `"unloaded_rule"`,
  `"severities_unloaded_rule"`, `"min_severity_relaxed"`,
  `"all_files_excluded"`) are the complete set; additions trigger a
  `schema_version` minor bump. Consumer switch statements should be
  exhaustive — contrast with `LintSeverity` ordering (an open ladder
  where additions do NOT trigger bumps).

- **`severities_unloaded_rule` is a value MIGRATION, not an
  ADDITION.** The 5th value is the 5th `LintRuntimeWarning.category`
  Literal entry, but the CLI-synthesized emit site MIGRATED from
  the existing `"unloaded_rule"` value; the engine-synthesized
  emit site is unchanged. Consumers switching on `category ==
  "unloaded_rule"` should AUDIT their existing branches — not just
  extend switch tables. The 0.2 → 0.3 `schema_version` bump IS the
  documented signal that consumer switch tables need re-checking.

- **`CompileResult.source_info_descriptors`** (new at D6b U2, the
  source-locations index built from `FileDescriptorSet` before
  `pool.Add()` discards `source_code_info`) is **INTERNAL** — not
  part of the public surface; consumers integrating with the
  compile-result object should treat it as implementation detail.
  R6's leading-comment introspection consumes it via the
  `leading_comment(source_info_descriptors, file_name, path)`
  free function at `protokit.schema.lint.rules.options._comments`.

#### Deferred to D6c

- `package/same-directory` (R8 — 18th buf BASIC rule; cross-file
  rule kind requires new ElementKind + LintLocation discriminant).
- R6 promotion to `error` severity (pending real-world experience
  with the leading-comment heuristic accuracy).
- `strict` profile rule enumeration.
- Per-rule disable/enable CLI flag (R9b) — `[severities] = "off"`
  in pyproject is the current de-facto disable mechanism.

### D6a — `protokit lint` rule library expansion + buf BASIC parity (0.2.0)

D6a grows `protokit lint` from the D2 `naming` canary (1 pack /
9 rules) into a 5-pack / 17-rule library covering buf BASIC parity
for single-language teams. Existing users upgrading from
`protokit 0.1.x` will see new ERROR-severity findings on
previously-green CI (matching buf's BASIC severity posture per
KD-9). Pin to `protokit~=0.1.0` (which means `>=0.1.0, <0.2.0`) if
you want to defer the upgrade; the demotion paths below cover the
common triage flows for users who choose to upgrade now.

- **`BUILTIN_PACKS` expansion (auto-loaded packs).** Four new
  packs join `naming` in the auto-load set: `enum`
  (`no-allow-alias`, `first-value-zero`), `imports`
  (`no-public`, `no-weak`, `unused`), `package` (`defined`,
  `directory-match`), and `file` (`syntax-specified`). Each rule
  is tagged with `source_spec="buf:<RULE_ID>"` for parity
  introspection; documented buf-parity divergences live in the
  rule docstrings (notably `file/syntax-specified` fires on both
  no-syntax AND explicit `syntax = "proto2";` files because the
  compiler emits `fdp.syntax == ""` for both). The auto-load
  expansion is gated on the `--no-builtin-rules` opt-out below.

- **Wire format — `schema_version` field.** `lint_json` output
  gains a top-level `"schema_version": "0.2"` key; `lint_sarif`
  gains `runs[].properties.lint_schema_version: "0.2"` (namespaced
  under SARIF's reserved property bag to coexist with the SARIF
  spec's own `version` field). The bump contract: this constant
  changes any time the JSON/SARIF wire shapes change in a way
  consumers need to detect. Absence of the key (older output) is
  the implicit "0.1" — consumers that need to support pre-0.2
  output should treat a missing `schema_version` as `"0.1"`. The
  JUnit `<system-out>` and human-stderr surfaces are unchanged.

- **Pyproject schema additions.** `[tool.protokit.lint]` accepts
  two new keys:
  - `no_builtin_rules` (bool, default `false`) — when `true`,
    skip loading `BUILTIN_PACKS` entirely. The `--rule-pack
    MODULE` flag (or future pyproject `rule_packs = [...]`)
    becomes load-bearing; without any user pack the engine has
    no rules and exits 2 via the existing `no-rules` error code.
  - `[tool.protokit.lint.severities]` (table; rule_id → severity
    string) — per-rule severity overrides applied AFTER profile
    composition. User overrides always win on collision via a
    post-compose dict-spread (`{**profile_overrides,
    **user_severities}`). Unknown rule_ids fire an `unloaded_rule`
    runtime warning naming each rule_id but do NOT exit error —
    the warning surfaces typos without blocking the lint run.

- **CLI flags.** `--no-builtin-rules` mirrors the pyproject key;
  parameter-source detection (`COMMANDLINE` / `ENVIRONMENT` /
  `DEFAULT_MAP`) drives precedence per the D5 pattern. `protokit
  lint --version` is new — prints `protokit <version> (parity:
  buf <pin>)` where the buf pin is `_BUF_PARITY_PIN` in
  `src/protokit/schema/lint/cli.py` (currently `v1.69.0`,
  cross-referenced with the parity CI job).

- **Profile names — protokit-native + buf aliases.** The primary
  protokit-native profile names are `essentials` (lightweight
  forward-placeholder), `recommended` (buf BASIC parity; the
  17-rule D6a set), and `default` (forward-placeholder for the
  D6b differentiator; structurally equal to `recommended` in
  D6a). Buf compatibility aliases resolve at the
  `_coerce_profile` input boundary in `_config.py`:
  `minimal → essentials`, `basic → recommended`. A user pack
  declaring `profiles=("basic",)` will never match — the alias
  resolves before pack profile-name lookup. Document this in
  custom rule packs.

- **Opt-out / demotion paths.** Pre-1.0 the version bump itself
  is the breaking-change signal; the four available demotion
  paths are:
  1. **Pin** — `protokit~=0.1.0` means `>=0.1.0, <0.2.0`, so
     pinned users are NOT auto-bumped.
  2. **Full opt-out** — `--no-builtin-rules` (CLI) or
     `[tool.protokit.lint] no_builtin_rules = true` (pyproject)
     skips `BUILTIN_PACKS` entirely. Pair with `--rule-pack
     MODULE` to supply a custom rule set; an empty rule set
     exits 2 via `no-rules`.
  3. **Global severity demotion** — `--min-severity=warning`
     (CLI) or `[tool.protokit.lint] min_severity = "warning"`
     (pyproject) raises the floor across all rules. This is the
     coarse hammer; finer control via the next option.
  4. **Per-rule demotion** —
     `[tool.protokit.lint.severities] "imports/unused" = "warning"`
     (or `"info"`) demotes one rule without touching the rest.
     Multiple keys compose. User overrides always win.

- **Upgrade notes.** The recommended triage path for an existing
  `protokit 0.1.x` user upgrading to `0.2.0`:
  1. Upgrade `protokit` (`pip install -U protokit` or equivalent).
  2. Run `protokit lint --format=json <inputs> | jq
     '.findings[] | {rule_id, severity, location}'` to enumerate
     the new findings.
  3. Decide per finding: fix the schema, or demote the rule. If
     a whole category is noise for your project (e.g.,
     `imports/unused` on third-party vendored protos), the
     pyproject `[severities]` table is the lowest-cost option;
     pair with `exclude` for vendored paths.
  4. For an emergency-revert, pin to `protokit~=0.1.0` and file
     an issue describing the false-positive — pre-1.0 is the
     right time to surface gaps in the rule heuristics.

- **Parity test infrastructure (advisory).** `tests/parity/`
  ships local fixtures + a pinned-buf CI job that runs against
  every PR. The job is **advisory (J2)** — failures surface as a
  yellow check, not a red block, so buf release shifts don't
  hold up unrelated PRs. A separate scheduled "buf release
  watcher" workflow opens a tracking issue weekly when upstream
  ships a newer stable release; pin bumps land as discrete
  reviewed PRs.

- **Public Surface (DRAFT) additions.** Four new rows in the
  README's Public Surface DRAFT table: protokit-native profile
  names, buf alias mapping, `lint_json` top-level
  `schema_version`, and SARIF `runs[].properties.lint_schema_version`.
  Output ordering (sorted by `(file, location, rule_id)` per
  KTD-6) is intentionally NOT listed as a Public Surface row —
  it is an implementation detail subject to change pre-1.0;
  consumers should not parse findings by positional invariants.

### Rationale (design decisions)

See `TODOS.md` for the full decision log. Summary:

- Package split: `message/` and `schema/` are sibling subpackages with
  no cross-dependency beyond `FieldPath` / `Warning`. Shared helpers
  live in the underscore-prefixed `_descriptors` and `_cli_utils`
  modules.
- Direction semantics: `Direction.FORWARD` / `Direction.BACKWARD`
  describe **which reader is at risk**, not which side of the schema
  changed. This keeps profile names (`CONSUMER_SAFE` etc.) aligned
  with what they filter.
- Plugin dispatch is fail-closed in the CLI: any plugin exception
  surfaces in `CompatibilityReport.warnings` and causes `protokit
  compat` to exit with code 2, so a broken custom policy never
  silently passes CI.

## 0.1.0 — 2026-04-07 (pre-rename snapshot)

Original `proto-differ` release — Python equivalent of Google's C++
`MessageDifferencer`. See git history at tag `v0.1.0` for the full
feature list; at a high level: 228 tests, structural message diffing,
cross-pool comparison, schema evolution detection, pytest hook, CLI.
