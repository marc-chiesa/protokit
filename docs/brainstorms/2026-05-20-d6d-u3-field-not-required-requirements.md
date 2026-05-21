---
date: 2026-05-20
topic: protokit-lint-delivery-6d-u3-field-not-required
---

# Protokit Lint Delivery 6d Unit 3 — `field/not-required` Rule + New `field` Rule Pack

**Scope:** narrow per-unit brainstorm refining the umbrella plan's U3
section. Inherits all umbrella decisions verbatim. The doc's load-
bearing contributions (acknowledged narrow per doc-review SG-1/SG-7)
are:
1. EV-1..EV-4 + ADV-3 EV-5..EV-8 empirical Phase 0 verifications with
   concrete decision branches for the failure-mode outcomes.
2. UR-7 — CLI dedup regression test at U3 for the U5 BUILTIN_PACKS
   flip (per [[cli-loaded-packs-dedup-zip-strict-builtin-packs-flip-2026-05-18]]).
3. UR-3 — double-jeopardy migration recipe **staging discipline**
   (U3 stages the demote-both content in `CHANGELOG-DRAFT.md`; U5
   folds into published CHANGELOG; collapsed into U3-S3 sub-bullet
   per doc-review SG-3).
4. Strategic acknowledgment that U3 ships a rule whose user value is
   "buf parity-claim integrity, not incremental defect detection"
   (per doc-review PL-1/PL-2/PL-3). The doc accepts this trade rather
   than escalating to umbrella renegotiation — the user owns the
   choice; the doc records the precedent.

The doc is intentionally narrower than D6b's per-unit brainstorms.
U1/U2 shipped umbrella → /ce:work directly; U3 adds a per-unit
brainstorm only for the four contributions above. No external user
has requested `FIELD_NOT_REQUIRED` coverage (per doc-review PL-4); the
rule ships to discharge KD-17's numerator commitment.

**Parent documents:**
- Umbrella brainstorm:
  `docs/brainstorms/2026-05-19-d6d-option-aware-pack-expansion-requirements.md`
  (R4 = `field/not-required` rule; R7 = severity `error` in
  `recommended` + `default`; KD-5 = bundled close-out framing).
- Umbrella plan U3 section:
  `docs/plans/2026-05-19-001-feat-d6d-option-aware-pack-expansion-plan.md`
  lines 919-1029 — uses KD-13 (new `field` pack), KD-16 (`CopyToProto`-
  based proto2 guard), and KD-17 ("26 of 27" numerator framing). KD-17
  is defined at the plan's Key Decisions section (line 424+), not
  inside the U3 section; U3 inherits it.
- U1 + U2 carry-forward learnings:
  - [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]]
    (snapshots BEFORE implementation; budget inline fix time)
  - [[dormant-code-changelog-draft-staging-delivery-boundary-2026-05-17]]
    (module imported + RULES populated at U3; BUILTIN_PACKS flip at U5)
  - [[copytoproto-round-trip-for-proto-form-only-descriptor-fields-2026-05-13]]
    (the `fdp.syntax` access pattern KD-16 relies on)

## Problem Frame

U3 closes the trivial proto2-only buf BASIC gap (`FIELD_NOT_REQUIRED`)
that was deferred from D6c. The rule itself is mechanically simple — a
single boolean predicate on each `FIELD` element guarded by a proto2-
syntax check. The real U3 work is **empirical**: protokit must match
buf v1.69.0's behavior byte-for-byte on edge cases that the umbrella
plan flagged but did not resolve (edition-2024+ `LEGACY_REQUIRED`,
proto2 `extend` blocks, group-typed fields). Each of these is a
plausible silent-divergence point per
[[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]].

Secondary problem: **double-jeopardy with `file/syntax-specified`**. The
existing `file/syntax-specified` rule (D6a, `recommended` + `default`,
ERROR) fires on every proto2 file. Adding `field/not-required` (also
`recommended` + `default`, ERROR) means a proto2 file with N `required`
fields produces **1 + N** errors. Buf v1.69.0 fires both rules in BASIC
at error severity, so this matches buf parity — but the umbrella plan's
migration recipe Path 1b ("schema-evolution path") only names
`field/not-required` demotion. The umbrella plan's Path 2 ("demote-to-
info") works mechanically but doesn't address that intentional-proto2
codebases already have `file/syntax-specified` to demote.

**Narrative-dilution acknowledgment** (per doc-review PL-2): D6d's
headline is "option-aware pack expansion" — the differentiator that
distinguishes protokit from buf. U3 ships a rule whose primary
user-visible behavior is to AMPLIFY noise (1+N errors) for buf
parity, which pulls in the opposite direction from the differentiator
narrative. A proto2 user upgrading to 0.5.0 plausibly perceives D6d
primarily as "the release that broke my CI with N+1 errors," not "the
release that delivered custom-annotation rules." This is accepted as
a cost of KD-17 + KD-5 (umbrella) rather than triggering umbrella
renegotiation. The U5 CHANGELOG section MUST lead with the option-
aware headline and treat `field/not-required` as a single bullet
under "buf BASIC parity close-out" to keep the narrative ordering
honest. Cross-reference [[post-ship-adoption-monitoring-pre-1.0-breaking-default-change-2026-05-19]]
discipline — silent-pin failure mode is the post-ship signal to
watch for.

## Pressure Test (Phase 1.2)

- **Is U3 the right shape?** Yes. The rule is single-predicate, the
  pack is single-rule. The fixture/parity-gate work is the bulk of the
  effort; the rule body is ~10 lines. Bundling adjacent buf parity
  rules (`PACKAGE_NO_IMPORT_CYCLE`) would expand scope into an
  architectural delivery per umbrella plan Scope Boundaries.

- **Inversion: skip `field/not-required` entirely?** Rationale: every
  proto2 file is already error-flagged by `file/syntax-specified`, so
  per-field findings add no marginal-defect-detection value. **Rejected:
  KD-17 commits the post-D6d "26 of 27 buf BASIC rules" numerator. The
  rule ships for parity-claim integrity, not incremental user value.**
  Documented explicitly in U3 docstring + CHANGELOG so future readers
  understand the bundling rationale.

- **Higher-upside alternative: ship `field/not-required` OFF by default
  in proto2 + recommend `file/syntax-specified` as the canonical
  rejection path?** Rationale: avoid double-jeopardy noise. **Rejected:
  diverges from buf v1.69.0 BASIC behavior; breaks KD-17 numerator
  framing.** The right place to address double-jeopardy is the
  migration recipe (Path 1b refinement, see UR-3 below), not the
  rule's default severity or profile membership.

## Phase 0 Empirical Verifications (Pre-Implementation)

These MUST resolve BEFORE writing the rule body. Each produces a
recorded buf v1.69.0 NDJSON snapshot at
`tests/schema/lint/rules/fixtures/field_not_required/_buf_smoke/recorded/`
that becomes the parity-gate ground truth.

**Invocation pattern**: each EV-N fixture follows the established
per-fixture-buf.yaml + `tests/_buf_helpers.py:run_buf_subprocess`
pattern (NOT inline `--config` flag — the existing R7 + R8/R8b
parity helpers all use per-fixture-dir `buf.yaml` files; the inline
flag form is not validated against buf v1.69.0 here). Each fixture
directory contains `buf.yaml` (declaring `use: [FIELD_NOT_REQUIRED]`),
the `.proto` file(s), and after Phase 0 a recorded
`recorded/<name>.json` NDJSON snapshot.

- **EV-1. Edition-2024+ `features.field_presence = LEGACY_REQUIRED`.**
  Construct an edition-2024 .proto file declaring a field with
  `[features.field_presence = LEGACY_REQUIRED]` inside a fixture
  directory whose `buf.yaml` declares `use: [FIELD_NOT_REQUIRED]`. Run
  `run_buf_subprocess` against the fixture dir. Record whether buf
  fires.

  **Concrete Outcome Decision Matrix** (per doc-review ADV-1 — no
  hand-waving; each outcome has a binding U3-and-U5 disposition):

  - **Outcome A (buf fires on edition `LEGACY_REQUIRED`):**
    - **Sub-Outcome A.1 (descriptor access path exists)**: U3 rule
      body adds an explicit edition-feature check: after the
      `fdp.syntax != ""` short-circuit excludes proto3, re-enter for
      edition files via `fdp.syntax == "editions"` AND
      `ctx.field.GetOptions().features.field_presence ==
      FeatureSet.FieldPresence.LEGACY_REQUIRED`. **Requires protobuf
      >= 5.26** (Editions GA shipped in protobuf 26.0; the project
      pins `protobuf>=5.26`, verified at `.venv` — current 5.27.5).
      Verify the access path resolves at Phase 0 time before
      committing the code skeleton.
    - **Sub-Outcome A.2 (descriptor access path missing/unstable on
      project's protobuf version)**: SCOPE EXPANSION. Escalate to
      umbrella renegotiation — do NOT inline a descriptor-access shim
      at U3 time. The shim is engine-level work that exceeds U3's
      "trivial close-out" framing per umbrella KD-5.
    - U3 fixture corpus grows from 8 to 9 (adds
      `fixture-edition-legacy-required-fires/` as POSITIVE assertion).
    - U5 CHANGELOG numerator substring becomes
      `"26 of 27 buf BASIC rules (proto2 + edition LEGACY_REQUIRED)"`
      — narrower headline than "26 of 27" alone.
    - U5 release is **NOT blocked**; ships under Outcome A with the
      revised numerator. NO separate escalation plan file is created
      (the U5 CHANGELOG update is the escalation artifact).
    - The umbrella plan KD-16 reference to a hypothetical
      `docs/plans/2026-05-XX-d6d-u3-legacy-required-scope.md` is
      retired — Outcome A handled inline.

  - **Outcome B (buf does NOT fire on edition `LEGACY_REQUIRED`):**
    - U3 ships proto2-only as the umbrella plan envisions.
    - Add `fixture-edition-legacy-required-skip/` to corpus as
      NEGATIVE-assertion (zero findings expected).
    - Document the scope-edge in `field.py` module docstring with the
      explicit reasoning ("buf v1.69.0 BASIC's FIELD_NOT_REQUIRED
      does not visit edition feature-flag-based presence; protokit
      matches").
    - U5 CHANGELOG numerator substring is `"26 of 27 buf BASIC
      rules"` as KD-17 envisions.

  - **Outcome C (buf errors-out on `LEGACY_REQUIRED` syntax / refuses
    to compile edition file):**
    - Drop the edition fixture entirely from the corpus.
    - Document in `field.py` module docstring: "Edition-2024
      `features.field_presence = LEGACY_REQUIRED` not exercised — buf
      v1.69.0 rejects the syntax. Revisit if/when buf adds support."
    - Same U5 CHANGELOG numerator as Outcome B.

  **No pre-commitment to a specific outcome**: run the verification,
  let the result bind. Removed prior "Recommend Outcome B" framing
  per doc-review ADV-1's confirmation-bias concern. Silent under-fire
  is a recurrence of the U1-style latent-bug pattern this learning
  was written to prevent.

- **EV-2. Proto2 `extend` block adding `required` extension field.**
  **PRE-DECIDED OUT-OF-SCOPE FOR U3** (per doc-review FEAS-2, P1
  blocker resolved): `LintEngine._dispatch_file` at
  `src/protokit/schema/lint/engine.py:818-893` walks
  `fd.message_types_by_name` and recurses into nested messages but
  **never iterates `fd.extensions_by_name`**. File-level `extend`
  blocks targeting messages defined in other files are invisible to
  any `ElementKind.FIELD` rule today. Pre-existing acknowledgment of
  this gap lives at `src/protokit/schema/lint/rules/imports.py:170-173`
  for the `unused-imports` parity divergence.

  Adding `extends_by_name` iteration to the engine is engine-level
  architectural work (new `ElementKind.EXTENSION_FIELD` variant +
  corresponding `FieldLintContext.message` handling for None-for-
  file-level-extensions) that exceeds U3's "trivial close-out"
  framing per umbrella KD-5.

  **U3 disposition**: ship `field/not-required` matching protokit's
  current FIELD-walker scope — fires on `required` fields declared
  inside message bodies (and nested messages, oneofs, groups), does
  NOT fire on `extend`-block extension fields targeting other files'
  messages. Add `fixture-required-extend-divergence/` to the corpus
  as a documented buf-parity DIVERGENCE (buf v1.69.0 fires
  somewhere; protokit does not — record the snapshot for transparency,
  assert the divergence in the parity test rather than asserting
  byte-equivalence). **Test-wiring decision** (per doc-review FEAS-8):
  the multi-file parity helper `assert_parity_multi_file` at
  `tests/parity/conftest.py:894-1088` does strict multiset equality
  with no divergence-allowlist hook. Pre-decided: U3 implements
  divergence-fixture handling via a SEPARATE assertion harness — a
  hand-rolled ~15-LOC test that calls the multi-file runners directly
  and asserts `len(protokit_in_scope) == 0 and len(buf_in_scope) > 0`,
  rather than extending `assert_parity_multi_file` itself. The
  divergence fixture is registered in a sibling
  `FIELD_NOT_REQUIRED_DIVERGENCE_FIXTURES: tuple[str, ...]` (parallel
  to `FIELD_NOT_REQUIRED_SMOKE_FIXTURES` per UR-5); the primary
  parity gate skips fixtures named in the divergence tuple. Document
  this in `field.py` module docstring with explicit cross-reference
  to the umbrella plan and to `imports.py:170-173`.

  **U5 CHANGELOG numerator framing implication**: if buf v1.69.0
  fires on `extend`-block extensions and protokit does not, the
  "26 of 27 buf BASIC rules" claim is asterisked. Recommended U5
  CHANGELOG wording: `"26 of 27 buf BASIC rules (proto2 in-message
  required-field detection; cross-file extend-block extensions
  deferred to D6e+ engine work)"`. This is honest about the
  divergence and preserves user trust per
  [[audit-wire-format-before-claiming-sibling-parity-2026-05-03]].

  **D6e+ follow-up**: file an issue / docs/brainstorms entry for
  "engine `ElementKind.EXTENSION_FIELD` support" as a prerequisite
  for full FIELD_NOT_REQUIRED parity. The work is not blocked on
  U3's `field/not-required` shipping (the rule will pick up
  extension-field coverage automatically once the walker visits
  them).

  **No need to verify EV-2 outcomes A/B/C empirically before
  U3** — the engine-walker gap is the binding constraint regardless
  of which file buf attributes the finding to. Still RECORD the buf
  snapshot for the divergence fixture (1-min `run_buf_subprocess`
  invocation) so the U5 CHANGELOG language is grounded.

- **EV-3. Proto2 `group`-typed field with `required` label.** Construct
  a .proto file with `message M { required group G = 1 { required
  string s = 2; } }`. Buf v1.69.0 fires on (a) the `group` field, (b)
  the `s` field inside the group, or (c) both?
  - **Most likely:** buf fires on both (each `FieldDescriptor` with
    `LABEL_REQUIRED` regardless of containing message). Protokit's
    `ElementKind.FIELD` walker handles nested messages structurally so
    this is "free" — no special-case needed.
  - **Verify** the walker visits group-internal fields and fires on
    both. Add `fixture-required-group/` to the corpus.

- **EV-4. Multi-file proto2 + proto3 mix.** Construct a directory with
  one proto2 file (1 `required` field) + one proto3 file (no
  `required`). Run buf with both files. Verify:
  - Proto3 file produces zero `FIELD_NOT_REQUIRED` findings.
  - Proto2 file produces exactly 1 finding.
  - Confirms KD-16's per-file syntax guard works under mixed inputs.

### Known EV Gaps (Out of Phase 0 Scope — D6e+ Verification)

Per doc-review ADV-3: EV-1..EV-4 do not exhaust the
silent-divergence surface. The following are explicitly NOT verified
at U3 Phase 0 but DOCUMENTED as known unknowns. Each is a candidate
post-ship issue if a user reports a parity-divergence:

- **EV-5 (deferred). `oneof`-internal `required` via `extend`.** protoc
  rejects `required` inside source-level `oneof`, but extension fields
  added via `extend` into a oneof-containing message could surface
  `LABEL_REQUIRED` inside synthetic oneofs. Subsumed by EV-2's
  engine-walker gap — moot until D6e+ extension-field support lands.
- **EV-6 (deferred). `map<K, V>` field with `required` desugaring.**
  Proto2 `map<>` desugars to repeated synthetic message-typed fields;
  the synthetic entry message's fields have their own labels. `required
  map<>` is likely protoc-rejected at source-level; verify if reported.
- **EV-7 (deferred). MessageSet (`option message_set_wire_format =
  true`) extension fields.** Proto2-only custom wire-format construct;
  also subsumed by EV-2's engine-walker gap.
- **EV-8 (deferred). `import public` chains crossing the
  proto2/proto3 syntax boundary.** EV-4 covers proto2+proto3 in a
  flat directory; transitive `import public` of a proto2 file into a
  proto3 module isn't verified. The per-file syntax guard suggests
  this is benign (each file independently classified) but record as
  a known unknown.

**Disposition**: do NOT extend the U3 fixture corpus for EV-5..EV-8
proactively. If a parity divergence surfaces in post-0.5.0 issues,
construct the fixture inline at issue-resolution time. Pre-emptively
chasing all imaginable proto2 edge cases violates the umbrella's
"trivial close-out" framing per KD-5.

## Requirements (Delta-Only Against Umbrella Plan)

The umbrella plan U3 section (lines 919-1029) is the authoritative
requirements source. This per-unit doc surfaces deltas:

- **UR-1. Phase 0 empirical verifications EV-1..EV-4 are gating.**
  Generate buf NDJSON snapshots for all four edge cases BEFORE writing
  any rule logic. EV-1 / EV-2 outcomes bind per U3-KD-8 / U3-KD-7 (no
  separate escalation plan file is created — outcomes handled inline
  per the per-EV disposition sections; do NOT silently scope-widen).

- **UR-2. Fixture corpus = 8 or 9 fixtures (count depends on EV-1
  outcome per U3-KD-8).** Beyond the umbrella plan's 5 baseline
  (proto2-no-required / proto2-one-required / proto2-many-required /
  proto3 / edition-2024), add 3 EV-derived fixtures:
  - `fixture-required-extend-divergence/` (EV-2; documented buf-
    parity DIVERGENCE per U3-KD-7 — fixture exists to record the
    snapshot transparently, not for byte-equivalence assertion)
  - `fixture-required-group/` (EV-3)
  - `fixture-proto2-proto3-mixed/` (EV-4, multi-file)

  EV-1 Outcome A adds a 9th fixture
  (`fixture-edition-legacy-required-fires/`); Outcomes B/C add 0/1
  per their dispositions in EV-1's matrix. Final count: 8 (B
  baseline), 9 (A or B+negative-assertion), 7 (C drops the edition
  fixture entirely).

  Each ships with: a `buf.yaml` declaring
  `use: [FIELD_NOT_REQUIRED]`, the `.proto` file(s), and a recorded
  `recorded/<name>.json` NDJSON snapshot. Parity-gate test asserts
  byte-equivalent output per
  [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]].

- **UR-3. Double-jeopardy migration recipe staging discipline** —
  collapsed into U3-S3 sub-bullet per doc-review SG-3 (UR-3 over-
  claimed U3 ownership of U5 work). U3 owns: staging the recipe text
  verbatim in `CHANGELOG-DRAFT.md`. U5 owns: folding the staged text
  into the published `### D6d` CHANGELOG section. The recipe text U3
  stages (per FEAS-6's demote-both directive — quoted here so the doc
  is self-contained):

  > **Intentional-proto2 codebases**: `protokit lint` after 0.5.0
  > upgrade fires BOTH `file/syntax-specified` (one ERROR per proto2
  > file) AND `field/not-required` (one ERROR per proto2 `required`
  > field). Demoting only one rule leaves the other firing at ERROR
  > and still blocks CI. The short-term harm-reduction recipe is:
  >
  > ```toml
  > [tool.protokit.lint.severities]
  > "file/syntax-specified" = "info"
  > "field/not-required"    = "info"
  > ```
  >
  > combined with the CLI flag `--min-severity warning` (filters
  > findings below WARNING before exit-code computation).
  >
  > Long-term resolution: schema migration to proto3 + presence
  > detection (or protovalidate) per umbrella KD-18 Path 1b.
  > Tracking: D6e+ proto2-aware profile may eliminate the need for
  > per-repo demotion entirely.

- **UR-4. `field` pack module structure mirrors `file.py` exactly.**
  Single rule, single `RULES` tuple, no helpers, no shared state
  module. Anti-pattern to avoid: premature `_field_helpers.py` for
  hypothetical future `field/*` rules. Per umbrella plan KD-13 the
  pack is currently single-rule; future additions (D6e+) can introduce
  shared helpers when the second rule lands per the "second
  recurrence is the structural-fix trigger" rule from
  [[bound-method-self-extraction-rule-to-engine-callback-2026-05-20]].

- **UR-5. Parity-helper consolidation in `tests/_buf_helpers.py`.**
  Add a third per-family pattern (consistent with the existing
  `SMOKE_FIXTURES` for R7 + `PACKAGE_DIRECTORY_SMOKE_FIXTURES` for R8/
  R8b): `FIELD_NOT_REQUIRED_SMOKE_FIXTURES: tuple[str, ...]` (8
  entries per UR-2) + `field_not_required_smoke_root() -> Path`
  function. Do NOT extend the existing tuples — the per-family-SSOT
  pattern is load-bearing for byte-comparison-pinned R25 invariants
  (verified in `tests/_buf_helpers.py:216-223` comment block).

- **UR-6. No rule body state, no helpers.** The rule body is:
  ```python
  from google.protobuf import descriptor as proto_descriptor
  from google.protobuf import descriptor_pb2

  # ... inside the rule callable:
  fdp = descriptor_pb2.FileDescriptorProto()
  ctx.file.CopyToProto(fdp)
  if fdp.syntax != "":
      return
  if ctx.field.label == proto_descriptor.FieldDescriptor.LABEL_REQUIRED:
      ctx.emit(violation_kind="field/not-required",
               params={"field_name": ctx.field.name})
  ```
  **Type discipline** (per doc-review FEAS-7): `ctx.field` is typed
  `proto_descriptor.FieldDescriptor` (not `FieldDescriptorProto`) per
  `model.py:1377`; compare `ctx.field.label` against
  `proto_descriptor.FieldDescriptor.LABEL_REQUIRED` (the high-level
  constant), NOT `descriptor_pb2.FieldDescriptorProto.LABEL_REQUIRED`
  (the proto-message-class constant). The integer values are identical
  (LABEL_REQUIRED == 2 in both) so a comparison against the wrong
  constant is silently correct at runtime but produces a mypy strict
  category-error.
  **`ctx.emit()` keyword-only contract**: every existing rule call site
  (see `naming.py:108-112`, `file.py:99-102`, `package_same.py`) uses
  keyword-only `violation_kind=` + `params=` per
  `_LintContextEmitMixin.emit` at `model.py:998-1003`. The umbrella
  plan U3 code block (lines 951-968) writes `ctx.emit(field_name=
  ...)` and `element_kinds=(ElementKind.FIELD,)` — both are inherited
  bugs; the correct decorator argument is `element=ElementKind.FIELD`
  (singular, per `file.py:59` precedent and `decorator.py:60`).
  Implementation must use the corrected forms above, not the
  umbrella's snippet.
  Stateless body; no `WeakKeyDictionary`-per-engine state, no bound-
  method `__self__` extraction is needed because the rule emits no
  runtime warnings. **Performance footnote**: `CopyToProto` is
  O(file-size) not O(1) — the upb backend re-serializes the full
  FileDescriptor on every call, so a 200-field proto2 file does 200
  full-descriptor serializations per lint run. For protokit's mostly-
  proto3 corpus this is a non-issue (~3 ms per proto2 file); for
  external proto2-heavy corpora it could matter. The trivial cache
  via `WeakKeyDictionary[ctx.file, bool]` is ~10 LOC and matches the
  U2 pattern at
  [[weakkeydict-plus-id-resettable-attr-per-engine-per-run-state-2026-05-18]].
  Defer the cache only if a Phase 0 wallclock measurement on the
  protokit corpus (rule active vs inactive) shows <5% delta;
  otherwise land the cache up-front rather than retrofit.

- **UR-7. CLI dedup regression test for `field` pack at U3.** Add a
  `TestRulePackExplicitLoadIsIdempotent::test_field_pack` test (mirror
  of the D6b U7 `package_same` regression test in
  `tests/schema/lint/test_cli_package_same_e2e.py`) that exercises
  `protokit lint --rule-pack=protokit.schema.lint.rules.field` against
  the dormant pack at U3. The test passes because the CLI dedup at
  `cli.py:871-872` is already in place — but landing the regression
  guard at U3 (not U5) catches the `zip(strict=True)` regression class
  per [[cli-loaded-packs-dedup-zip-strict-builtin-packs-flip-2026-05-18]]
  BEFORE the U5 `BUILTIN_PACKS` flip exposes the same surface that
  failed at D6b U7. ~15 LOC; load-bearing per memory.

## Success Criteria (Inherited + Refined)

Inherits S5 + S6 + S7 from the umbrella brainstorm. Adds:

- **U3-S1.** All four Phase 0 verifications (EV-1..EV-4) have recorded
  buf v1.69.0 NDJSON snapshots committed under
  `tests/schema/lint/rules/fixtures/field_not_required/_buf_smoke/recorded/`.
  The parity-gate test `tests/parity/test_parity_field_not_required.py`
  asserts byte-equivalent output for all 8 fixtures.

- **U3-S2.** The rule body is ≤10 lines (excluding the
  `@lint_rule` decorator + module-level imports). Any deviation
  triggers a maintainability-review pass.

- **U3-S3.** Dormancy contract: through U3-U4, the `field` pack is
  importable + has `RULES = (check_field_not_required,)` populated,
  BUT NOT registered in `BUILTIN_PACKS`. The `tests/schema/lint/
  test_builtin_packs.py` membership pin fails loudly if `field` is
  added to `BUILTIN_PACKS` prematurely, forcing the contributor to
  update the expected tuple — the safeguard is **fail-loud-by-
  convention + reviewer attention at PR review**, not a mechanical
  block (the test's failure message instructs the contributor to
  update the expected tuple; a careless contributor following the
  instructions could ship dormancy-broken). Pairs with U2's
  `field_behavior` precedent at `rules/__init__.py:80` (`# noqa: F401
  # D6d U2 — staged dormant`). **Cross-unit coupling note for U5**:
  the existing `TestBuiltinPacksDocstringRatchet` at
  `test_builtin_packs.py:144-170` pins `"25 of 26 buf BASIC rules"`
  and `"``FIELD_NOT_REQUIRED``"` (with double-backticks per Sphinx
  convention) substrings. U5 must update the `BUILTIN_PACKS` expected
  tuple AND the ratchet substrings AND the docstring text
  atomically.

  **Ratchet substring decision per ADV-7** (the substring chosen by
  EV-1 outcome at U3 time MUST be staged in `CHANGELOG-DRAFT.md`
  alongside the migration recipe — U5 cannot author it correctly
  without that staging artifact):
  - EV-1 Outcome A.1 ratchet substring: `"of 27 buf BASIC rules"`
    (hedged-tolerant; passes for both `"26 of 27 buf BASIC rules
    (proto2 + edition LEGACY_REQUIRED)"` and any future
    re-wording per the 5th discipline rule of
    [[presence-ratchet-test-pattern-for-prose-substrings-2026-05-14]]).
  - EV-1 Outcome B ratchet substring: `"26 of 27 buf BASIC rules"`
    (clean form per KD-17).
  - EV-1 Outcome C ratchet substring: `"26 of 27 buf BASIC rules"`
    (clean form, edition not exercised).
  Also pin a SECOND ratchet substring for the EV-2 divergence
  asterisk under U3-KD-7: `"cross-file extend-block extensions
  deferred to D6e+ engine work"` — single-line per discipline rule.

  **CHANGELOG-DRAFT.md staging at U3**: U3 is the first D6d unit to
  stage CHANGELOG-DRAFT.md content (verified: D6d U1 + U2 shipped
  without CHANGELOG-DRAFT staging entries; CHANGELOG-DRAFT.md
  currently contains only header + D6c-folded marker). U3 establishes
  the `### D6d` section header in CHANGELOG-DRAFT.md AND stages:
  (a) the demote-both migration recipe from UR-3 verbatim, (b) the
  EV-1-outcome-bound ratchet substring (one of the three above), (c)
  the EV-2 divergence-asterisk ratchet substring. This staging is the
  contract that prevents content drift between U3 and U5.

  The pack flips into `BUILTIN_PACKS` at U5 delivery
  boundary per
  [[dormant-code-changelog-draft-staging-delivery-boundary-2026-05-17]].

## Scope Boundaries (Inherited from Umbrella + U3-Specific)

Umbrella plan U3 explicitly inherits all D6d Scope Boundaries
(`PACKAGE_NO_IMPORT_CYCLE`, R9b, strict profile, etc., all deferred to
D6e+). U3-specific exclusions:

- **No `field` pack helpers** — see UR-4. Defer until a second
  `field/*` rule lands.
- **No edition-2024+ feature-flag introspection** — see EV-1 Outcome
  B. If EV-1 surfaces Outcome A, U3 escalates to a separate scope-
  expansion plan; does not silent-widen.
- **No `file/syntax-specified` ↔ `field/not-required` deduplication**
  — see Pressure Test inversion-rejection. Both rules fire per buf
  BASIC parity; the migration recipe addresses the UX (UR-3).
- **No CLI flag for proto2-only schema linting** — out of D6d scope;
  use `[severities]` demotion of both rules per UR-3.

## Key Decisions

- **U3-KD-1. Phase 0 empirical verifications gate the rule body.**
  Generate snapshots first, then write code. Recurrence of the U1/U2
  pattern that surfaced multiple latent bugs at implementation time.

- **U3-KD-2. Stateless rule body, no helpers.** Per UR-6. Defer
  optimization until profiling demonstrates need.

- **U3-KD-3 (removed; superseded by U3-KD-8).** Original entry
  pre-committed to EV-1 Outcome B; rewritten to U3-KD-8's run-and-
  bind discipline per doc-review ADV-1 confirmation-bias concern. See
  git history if you need the prior text.

- **U3-KD-4. Double-jeopardy is acceptable; addressed via migration
  prose (U3-S3 staging + U5 CHANGELOG fold), not by changing default
  severity or profile membership.** The migration recipe content
  (per FEAS-6's demote-both directive) now lives in U3-S3's
  CHANGELOG-DRAFT.md staging note rather than a standalone UR. Buf-
  parity is the load-bearing constraint per umbrella KD-17 + KD-5;
  precedent recorded at U3-KD-6 with conscious-revisit trigger.

- **U3-KD-5. Per-family parity-helper pattern continues.** UR-5: add
  `FIELD_NOT_REQUIRED_SMOKE_FIXTURES` + `field_not_required_smoke_root`
  as a third SSOT; do not extend the existing tuples.

- **U3-KD-6. Precedent acknowledgment — buf-parity defaults override
  protokit-UX judgment** (resolves doc-review PL-3 P1 concern). U3
  establishes a precedent: when buf BASIC defaults conflict with
  protokit's own UX judgment (here: double-jeopardy with
  `file/syntax-specified`), protokit defers to buf's defaults +
  patches friction in CHANGELOG migration prose. This precedent will
  recur for D6e+ (`PACKAGE_NO_IMPORT_CYCLE`, future BASIC additions,
  STRICT profile). The cost: moves protokit's identity from "buf-
  compatible with opinionated UX" toward "buf clone in Python." The
  benefit: KD-17 numerator integrity + simpler comparison-table
  shopping experience for buf-evaluating users.
  **Conscious-revisit trigger**: if D6e or later faces a third buf-
  parity-vs-UX conflict, escalate the precedent to umbrella-plan-level
  review. The right discipline at that point may be "protokit defaults
  reflect protokit opinion; buf-parity is measured at rule-existence
  level, not rule-default level." Per
  [[post-ship-adoption-monitoring-pre-1.0-breaking-default-change-2026-05-19]],
  monitor 0.5.0 issue surface for "double-jeopardy" complaints as the
  empirical signal for revisiting.

- **U3-KD-7. EV-2 extension-field walker gap accepted as D6e+ scope.**
  Per FEAS-2 P1 resolution: protokit's engine does not walk
  `fd.extensions_by_name`; `field/not-required` will NOT fire on
  cross-file `extend`-block extension fields. Documented as DIVERGENCE
  in the parity test (not byte-equivalence assertion). U5 CHANGELOG
  numerator framing must be honest about the divergence per UR-2
  fixture-extend-divergence/.

- **U3-KD-8. EV-1 outcome is binding — no pre-commitment to Outcome
  B.** Per ADV-1 P1 resolution: each EV-1 outcome (A/B/C) has a
  concrete U3 + U5 disposition in the brainstorm above. Run the
  verification; let the result bind. No separate escalation plan file
  needed for Outcome A (inline U5 CHANGELOG numerator revision is the
  artifact).

## Open Questions

### Resolve Before Implementation

- **EV-1 outcome determines edition-2024 scope.** 15-min `buf lint`
  invocation against the fixture dir. Block U3 main implementation
  until resolved; outcome binds per U3-KD-8 decision matrix.
- **EV-2 buf snapshot for divergence documentation.** Per U3-KD-7,
  the engine-walker gap is the binding constraint regardless of
  buf's attribution choice; still record the snapshot (1-min) so
  the U5 CHANGELOG language is grounded.
- **EV-3 outcome verifies the walker handles group-internal fields.**
  Almost certainly free; verify to be sure (this is SG-7's genuine
  net-new contribution).
- **EV-4 multi-file proto2+proto3 mix** — straightforward parity
  anchor for the per-file syntax guard.

### Deferred to U5

- **CHANGELOG migration recipe cross-reference for
  `file/syntax-specified` ↔ `field/not-required` double-demotion**
  (UR-3). One-paragraph addition; staged via CHANGELOG-DRAFT.md at U3
  for U5 to fold.

### Deferred to D6e+

- **`field/*` rule pack helpers** — defer until second `field/*` rule
  lands per UR-4.
- **Edition-2024 feature-flag introspection** — handled inline at U3
  per U3-KD-8 if EV-1 surfaces Outcome A; otherwise deferred.
- **Proto2-aware profile** (a hypothetical `proto3-only` profile that
  excludes `file/syntax-specified` + `field/not-required` for
  intentional-proto2 users) — not a U3 question; tracked as a D6e+
  candidate. **Adoption-signal trigger** per U3-KD-6: if 0.5.0 surfaces
  ≥3 issues citing "FIELD_NOT_REQUIRED noise" or "double-jeopardy",
  pull this profile into 0.5.1.
- **Engine `ElementKind.EXTENSION_FIELD` support** — prerequisite for
  full FIELD_NOT_REQUIRED parity per EV-2 + U3-KD-7. File a separate
  brainstorm at D6e if no user reports the divergence first.
- **EV-5..EV-8 verifications** (`oneof`-internal / `map<>` /
  MessageSet / `import public`) — verify post-ship only if a user
  reports parity divergence.

## Visual: U3 Scope at a Glance

| Component | Umbrella plan source | U3 brainstorm delta |
|---|---|---|
| `field/not-required` rule body | KD-16 | UR-6 (stateless; corrected `ctx.emit` signature + `element=` singular vs umbrella's inherited bugs) |
| `src/protokit/schema/lint/rules/field.py` (1-rule pack) | KD-13 | UR-4 (no premature helpers) |
| Buf v1.69.0 parity gate | plan U3 "Pre-implementation parity-gate snapshots" | UR-2 (8-9 fixtures; corpus depends on EV-1 outcome) |
| Edition-2024 `LEGACY_REQUIRED` | KD-16 documented escalation path | EV-1 + **U3-KD-8 binding-outcome matrix** (U3-KD-3 removed; superseded) |
| Extension `extend` block attribution | umbrella OQ | **EV-2 pre-decided OUT-OF-SCOPE per FEAS-2 + U3-KD-7** (engine walker gap deferred to D6e+) |
| Group-typed `required` field | not addressed in umbrella | EV-3 (the genuine net-new contribution per SG-7) |
| Multi-file proto2+proto3 mix | not addressed in umbrella | EV-4 |
| `oneof`/`map`/MessageSet/`import public` | not addressed | EV-5..EV-8 deferred per ADV-3 |
| Dormancy staging + U5 cross-unit ratchet coupling | KD-13 + [[dormant-code-...]] | U3-S3 (fail-loud-by-convention framing per ADV-4) |
| CLI dedup regression test at U3 | not addressed in umbrella | **UR-7** (per ADV-5; prevents U5 `zip(strict)` regression) |
| `tests/_buf_helpers.py` third family | umbrella plan line 938 | UR-5 (do-not-extend constraint added) |
| Double-jeopardy migration UX | KD-18 Path 1b/Path 2 | UR-3 collapsed into U3-S3 staging note (per SG-3 + FEAS-6 demote-both content) |
| Buf-parity precedent for default-on rules | not addressed | **U3-KD-6** (per PL-3; precedent recorded + revisit trigger) |

## Next Steps

`-> /ce:plan` for U3-specific implementation planning, OR `/ce:work`
directly if the umbrella plan's U3 section + this per-unit brainstorm
together provide sufficient implementation detail.

**Recommend** `/ce:work` — the umbrella plan's U3 section (lines
919-1029) is already implementation-grade; this per-unit doc adds the
empirical verification list + edge-case fixture corpus. A separate
per-unit plan would be ceremony without commensurate value, matching
the umbrella-plan-only delivery pattern of D6d U1 + U2.
