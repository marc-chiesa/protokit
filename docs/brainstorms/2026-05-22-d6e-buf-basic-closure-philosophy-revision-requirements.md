---
date: 2026-05-22
last_revised: 2026-05-22
status: ACTIVE
topic: protokit-lint-delivery-6e-buf-basic-closure-plus-philosophy-revision
---

# Protokit Lint Delivery 6e — buf BASIC Closure + UX Philosophy Revision (0.6.0)

## Overview

D6e ships **"26 of 26 buf v1.69.0 BASIC rules (with one documented divergence on extend-block-required-fields)"** as the closing headline of the buf-parity arc that has been compounding since D6a (17/18 framing) → D6b (23/26 effective) → D6c (25/26) → D6d (parity unchanged; option-aware headline). The v1.69.0 qualifier + extend-block asterisk are load-bearing per D6e KD-9 and KD-10 (see Key Decisions). Plus the inverted UX philosophy revision that the D6d U3 brainstorm surfaced as load-bearing but deferred.

Three new ship surfaces:

1. **UX Philosophy Revision** (U1) — formalize the **hard-inverted** principle: *protokit-UX overrides buf-parity when they conflict*. Resolve U3-KD-6 (the original "buf-parity overrides protokit-UX" precedent) explicitly. State protokit's **pragmatic-not-dogmatic** position on proto2: officially supported, no deprecation timeline known, but proto2-specific style/strictness rules ship in an **opt-in `proto2-strict` profile** rather than fighting proto2 users in `recommended` / `default`. Audit-only pass on D6a–D6c existing rules; document findings (no retroactive code changes).
2. **`field/not-required`** (U2; the deferred D6d U3 rule) — proto2-only buf-parity rule equivalent to `buf:FIELD_NOT_REQUIRED`. Ships in `proto2-strict` profile only (NOT `recommended` / `default`). Severity: ERROR (the name `proto2-strict` carries the strictness; users opting in want hard signals).
3. **`package/no-import-cycle`** (U3) — the 26th buf BASIC rule (`buf:PACKAGE_NO_IMPORT_CYCLE`). Package-level cycle detection on the import graph; emission shape bound to buf v1.69.0 at Phase 0. Cyclic imports are a structural anti-pattern across proto2/proto3/editions — no UX-divergence reason to defer from buf-parity defaults; ships in `recommended` + `default` profiles at ERROR severity (subject to Phase 0 confirmation against buf BASIC profile membership).

Plus the standard delivery-boundary unit (U4): pyproject `0.5.0` → `0.6.0`, CHANGELOG fold, README "26 of 26 buf BASIC rules" numerator refresh, BUILTIN_PACKS expansion (if applicable), presence-ratchet + CLI dedup regression tests per [[cli-loaded-packs-dedup-zip-strict-builtin-packs-flip-2026-05-18]].

## Problem Frame

**The buf-parity arc closes here.** D6a-D6c shipped 25 of 26 buf BASIC rules; the 26th (PACKAGE_NO_IMPORT_CYCLE) was deferred because its cross-file cycle-detection algorithm doesn't reuse D6c's Arch-D pre-walk accumulator pattern. FIELD_NOT_REQUIRED was deferred from D6d U3 because the underlying UX-philosophy question ("does buf-parity override protokit-UX for proto2 patterns?") was load-bearing for its default severity + profile. D6e resolves both.

**The philosophy revision unblocks consistent defaults for proto2-specific rules going forward.** The D6d U3 brainstorm explicitly flagged U3-KD-6 ("buf-parity overrides protokit-UX") as under reconsideration; D6e formalizes the inversion. After D6e, future proto2-specific rules (FIELD_NOT_REQUIRED first; potential MessageSet / extend-block / oneof-required successors per EV-5..EV-8 in the SUPERSEDED brainstorm) ship in `proto2-strict` opt-in with no per-rule philosophy debate.

**"Pragmatic, not dogmatic."** Proto2 is officially supported with no known deprecation timeline. The hard-inverted philosophy is NOT "proto2 is deprecated" — it's "protokit doesn't force opinionated proto2 stance into default profiles." Users who want strict proto2 checks opt in via `--profile proto2-strict` or pyproject `profile = ["default", "proto2-strict"]`.

## Pressure Test (Phase 1.2)

- **Real problem?** Yes — "26 of 26 buf BASIC rules" is a clean closing headline; D6d-era deferrals of FIELD_NOT_REQUIRED + PACKAGE_NO_IMPORT_CYCLE were principled (philosophy gating; algorithm difference) but the closing arc is the obvious natural delivery.
- **Do-nothing cost?** Both rules stay deferred. Users needing proto2-required checks or cycle detection keep using buf. Multi-quarter delay on the closing headline + the philosophy revision keeps drift open. Future D6f+ proto2-specific rules would face the same philosophy question.
- **Higher-upside framing?** Bundling philosophy + 2 rules into ONE D6e umbrella (vs sequential 0.5.1 philosophy patch + 0.6.0 D6e rules) gives users "26/26 with a coherent UX story" in one release. The carrying cost of the multi-unit umbrella is bounded by the philosophy revision being audit-only (no retroactive code changes).
- **Single highest-leverage move?** D6e umbrella with philosophy + 2 rules + delivery boundary. The alternative (philosophy-first patch) was considered + rejected because the inverted-philosophy framing has no user-visible behavior change beyond the 2 new rules — releasing it as a standalone patch would be principle-without-substance.
- **Opportunity cost acknowledged.** Closing the buf-parity arc in D6e defers the option-aware differentiator deepening (R6 promotion to error, IDENTIFIER-based field_behavior contradictions, MessageSet-aware rules, the proto-schema-parser integration roadmap item) by one full delivery window. The judgment is that the open buf-parity items have been compounding across D6a-D6d and the credibility cost of leaving them open exceeds the cost of a one-delivery deferral of option-aware-deepening. The "do-nothing" cost in the Pressure Test above focused on users-who-might-evaluate-protokit-against-buf; this acknowledgment surfaces the parallel cost for users-who-adopted-for-option-aware. Both audiences are real; both costs are bounded; closing the arc compounds (the closing headline is a durable artifact); option-aware deepening can resume in D6f with no architectural debt incurred by D6e.
- **Durable capability in 6-12 months?** Complete buf BASIC baseline (26/26 grep-visible audit trail) + a documented UX philosophy that future proto2-specific rules slot into without re-debating defaults. The `proto2-strict` profile becomes the standing home for opt-in strict checks regardless of syntax (could expand to `proto3-strict` or `editions-strict` if future deliveries surface those needs).

## Requirements

### U1: UX Philosophy Revision

(Requirements R1, R2, R3, R4, R4b.)

### R1 — Hard-inverted philosophy principle (U1)

Establish in the brainstorm + CHANGELOG the explicit principle:

> **protokit-UX overrides buf-parity when they conflict.** Buf-parity is protokit's starting point for built-in rule semantics; when buf's behavior conflicts with protokit's UX judgment (e.g., forcing proto2-specific rules into default profiles), protokit's UX wins. Buf-parity for the existing 25 rules currently in BUILTIN_PACKS (D6a-D6c) is preserved. The two new D6e rules (`field/not-required` and `package/no-import-cycle`) set their own buf-parity alignment per D6e KD-5 and KD-8.

Explicitly retire U3-KD-6 (the original "buf-parity overrides protokit-UX" precedent from the SUPERSEDED D6d U3 brainstorm). Cite the new principle as `D6e KD-1` for future cross-reference.

### R2 — Pragmatic proto2 stance (U1)

Document protokit's proto2 position:

- Proto2 is officially supported by protokit; no deprecation timeline.
- Proto2-specific anti-pattern rules (the FIELD_NOT_REQUIRED class) ship in opt-in `proto2-strict` profile only.
- `recommended` + `default` profiles stay proto-syntax-agnostic (no proto2-specific rules).
- Users opt in via `--profile proto2-strict` or pyproject `profile = ["default", "proto2-strict"]`.

### R3 — `proto2-strict` profile activation (U1)

Activate the new `proto2-strict` profile in the profile machinery:

- Initially contains ONE rule: `field/not-required`.
- **Sequencing (CONV-C resolution)**: U1 and U2 ship as ONE atomic commit covering both the profile registration AND the rule that populates it. This is a deliberate departure from the standard per-unit pipeline isolation (per [[multi-unit-ce-review-stash-pop-coordination-2026-05-21]]) — for D6e specifically, treating U1+U2 as one unit for ce:review purposes avoids the empty-profile intermediate state where `--profile proto2-strict` would hard-error with exit-2 (`unknown-profile` or `no-rules`). The brainstorm explicitly documents this departure; ce:review for the combined commit covers both surfaces in one pass.
- Distinct from the deferred `strict` profile (which is reserved for style-strictness rules: COMMENT_* / ENUM_ZERO_VALUE_SUFFIX). The two profiles have different intent; do NOT consolidate.
- Profile-name registration: per feasibility F1 (0.92), `_coerce_profile` does NOT require a code change for new profile names — the coercion machinery accepts any normalized string. The new profile becomes valid as soon as a loaded rule pack declares `profiles=("proto2-strict",)` on at least one rule. This means R3's "activation" reduces to (a) the `field/not-required` rule body declaring `profiles=("proto2-strict",)` in its `@lint_rule` decorator + (b) README profile table updated with `proto2-strict` row + opt-in framing + (c) any explicit alias the brainstorm decides to register in `_PROFILE_ALIASES` (none needed; `proto2-strict` is a primary name, not an alias).
- README profile table updated with `proto2-strict` row + opt-in framing.

### R4 — D6a–D6c existing-rules audit pass (U1)

Audit pass under the inverted philosophy lens:

- Read each rule's docstring + default profile placement.
- Document any rule whose current behavior conflicts with the inverted philosophy in the brainstorm's "Existing Rules Audit" section + a CHANGELOG mention.
- **No retroactive code changes in D6e EXCEPT for `file/syntax-specified` (handled separately in R4b).** Other audit findings (if any) become D6f+ backlog items in TODOS.md with concrete triggers for revisiting (per CONV-A user decision + product-lens PL-4: "if N proto2-related issue reports within M weeks post-ship, pull the demotion into a 0.6.1 patch" — define N + M during planning).

### R4b — `file/syntax-specified` demotion (U1)

The placeholder doc's Piece 2 IS resolved in D6e (revised from the original audit-only fence per CONV-A 4-way reviewer convergence: product-lens PL-2 + feasibility F7 + adversarial ADV-7 + scope-guardian F3 converged on "audit-only here is audit-as-theater because the rule's behavior actively contradicts D6e KD-1 at ship day").

- **Current behavior**: fires at ERROR in `recommended` + `default` profiles on any file where `fdp.syntax == ""`. Per protobuf semantics, this matches ALL proto2 files including those with explicit `syntax = "proto2";` statements (proto2 is the default; descriptors do not carry the explicit value). The rule effectively says "no proto2 files."
- **Post-D6e behavior**: demoted to WARNING in `recommended` + `default`. The rule still surfaces the signal ("we recommend declaring syntax explicitly so future readers don't have to guess proto2 from descriptor shape") but does NOT fail CI on proto2 files. Pragmatic-not-dogmatic per D6e KD-2.
- **Scope of the change**: 1-line severity change in `src/protokit/schema/lint/rules/file.py` + module docstring update + CHANGELOG entry in the D6e "Changed" subsection. The rule body itself is unchanged.
- **Migration recipe**: users who relied on the ERROR severity (proto3-only shops who want explicit syntax declaration enforced) can re-promote via `[tool.protokit.lint.severities] "file/syntax-specified" = "error"` per the established pattern.
- **CHANGELOG framing**: a BREAKING-prefixed subsection per the pre-1.0 communication contract — this is a default-severity downgrade that users with `--max-warnings 0` may notice + users with `--min-severity error` filtering effectively make invisible.

### U2: `field/not-required` Rule

(Requirement R5.)

### R5 — `field/not-required` rule (U2)

Implement per the SUPERSEDED D6d U3 brainstorm's UR-6 rule body (still correct):

```python
fdp = descriptor_pb2.FileDescriptorProto()
ctx.file.CopyToProto(fdp)
if fdp.syntax != "":  # skip non-proto2 (proto3 + editions)
    return
if ctx.field.label == proto_descriptor.FieldDescriptor.LABEL_REQUIRED:
    ctx.emit(violation_kind="field/not-required", params={"field_name": ctx.field.name})
```

Decisions binding from D6e U1 + the SUPERSEDED brainstorm:

- **Profile**: `proto2-strict` only (NOT `recommended` / `default`).
- **Severity**: `error` (opt-in profile's strict semantics).
- **Rule pack**: lives in the `field` pack (NEW; mirrors `file.py` shape per the SUPERSEDED brainstorm UR-4) OR in an existing pack — defer to planning.
- **EV outcomes**, split by resolution status (per U3-KD-8 discipline):
  - **EV-1, EV-3, EV-4: bind at Phase 0 of U2** (open outcomes — EV-1 edition-LEGACY_REQUIRED 3-outcome matrix; EV-3 group-typed required behavior; EV-4 multi-file proto2+proto3 mix). Run buf v1.69.0 on the fixture inputs + bind the rule body's behavior to match.
  - **EV-2 (extend-block extensions): PRE-DECIDED OUT-OF-SCOPE** per the SUPERSEDED D6d U3 brainstorm's U3-KD-7. The engine's per-file walker at `engine.py:818-893` never iterates `fd.extensions_by_name`; the divergence is architectural, not buf-behavior-dependent. No Phase 0 re-verification needed. Still record the buf v1.69.0 snapshot for CHANGELOG-transparent audit-trail wording. **Note**: under the new `proto2-strict` opt-in audience (vs the originally-planned `recommended`+`default` placement), this asterisk may erode opt-in user trust more sharply — see CONV-F open question in the convergences section.
- **Fixture corpus**: 8-9 fixtures; parity gate against buf v1.69.0 NDJSON snapshots.

### U3: `package/no-import-cycle` Rule

(Requirement R6.)

### R6 — `package/no-import-cycle` rule (U3)

Implement cross-file cycle detection on the package-level import graph:

- **Edge granularity**: package → package. A file in package P that imports a file in package Q creates edge `P → Q`. Multi-file P→Q imports collapse to one edge.
- **Cycle definition**: a strongly connected component (SCC) of size ≥ 2 in the package-level digraph. (Self-loops within a single package are unrelated to import cycles — package-internal file imports are not edges.)
- **Profile**: `recommended` + `default` (subject to Phase 0 confirmation against buf BASIC profile membership).
- **Severity**: `error` (Phase 0 confirmation).
- **Rule pack**: lives in the `package` pack alongside R8/R8b (the existing cross-file family from D6c).
- **Emission shape**: bind to buf v1.69.0 at Phase 0 — the open product question is "one finding per cycle vs one finding per file vs one finding per package," with buf-parity as the anchor. The D6c precedent is per-file emission (R8/R8b), but cycle detection may emit differently in buf.
- **Algorithm + engine architecture**: defer to planning. The brainstorm's job is product-level decisions; planning chooses DFS-back-edge vs Tarjan SCC and whether to extend D6c's `_build_directory_package_accumulator` pattern or introduce a new pre-walk phase.
- **Scope**: root_files only vs include transitive imports — defer to Phase 0 buf-parity verification. Likely root_files only (matching R8/R8b precedent), but cycle detection may need transitive traversal to identify cycles that loop through vendor packages.
- **Fixture corpus**: empirically bound at Phase 0; minimum should cover direct A↔B cycle, 3-node A→B→C→A, self-import-not-cycle, vendor-only cycle (out of scope per likely Phase 0 outcome), root+vendor mixed cycle (in scope; user can fix).
- **Buf-parity gate**: parity test against buf v1.69.0 NDJSON snapshots, integrated into `tests/parity/conftest.py:assert_parity_multi_file` family partition.

### U4: Delivery Boundary (0.6.0)

The delivery-boundary unit is documented in full in the **Visual: D6e Scope at a Glance** section below (the U4 block). Standard structure matching D6b U7 + D6c U5 + D6d new-U4 precedent: pyproject version bump, CHANGELOG `### D6e` fold, README "26 of 26" numerator refresh, BUILTIN_PACKS expansion, presence-ratchet + CLI dedup regression test, bump-contract ratchet pin (`_LINT_JSON_SCHEMA_VERSION` does NOT bump — no closed-Literal `LintRuntimeWarning.category` additions in D6e), stale-text sweep.

## Success Criteria

**Output checks (deliverables shipped):**

- [ ] D6e ships as protokit 0.6.0 with the **"26 of 26 buf v1.69.0 BASIC rules (with one documented divergence on extend-block-required-fields)"** headline grep-visible across README, CHANGELOG, BUILTIN_PACKS docstring, and the buf-parity audit trail.
- [ ] `field/not-required` fires under `--profile proto2-strict` only (zero findings under `recommended` + `default` on proto2-required fixtures). Extend-block divergence asterisked LOUDLY in 3 docstring sites per D6e KD-10.
- [ ] `file/syntax-specified` demoted from ERROR to WARNING in `recommended` + `default` per R4b + CONV-A; migration recipe documented for users who want to re-promote to ERROR via `[severities]` override.
- [ ] `package/no-import-cycle` byte-equivalent parity against buf v1.69.0 NDJSON snapshots on the committed fixture corpus, with co-fire ordering verified at Phase 0.
- [ ] The hard-inverted philosophy principle (D6e KD-1) is documented in CHANGELOG (Added section + Consumer-migration framing for future-rule expectations) + cross-referenced from `docs/solutions/best-practices/` (likely a new learning).
- [ ] Audit findings against D6a-D6c rules surfaced in the brainstorm + flagged in TODOS.md as D6f+ backlog items with explicit forcing-function triggers per PL-4 (e.g., "if N proto2-related issue reports within M weeks").
- [ ] CLI dedup parametrized test (per D6e KD-13 + KD-14) covers every BUILTIN_PACKS member + lands at U2/U3 with the new BUILTIN_PACKS members, not at U4.
- [ ] Suite, ruff, mypy all clean on gated paths post-delivery-boundary.

**Outcome checks (strategic goals achieved):**

- [ ] **The KD-1 philosophy principle is durable**: a future per-unit brainstorm for any proto2-specific rule can cite D6e KD-1 as the default-severity/profile decision without re-opening the philosophy question. Falsification: if D6f's first new proto2-specific rule brainstorm re-debates the philosophy, KD-1 was not durable enough.
- [ ] **The buf-parity arc is structurally closed**: TODOS.md's `D6e+ backlog items` section is cleared of buf-parity-arc items (only D6f+ option-aware-deepening items + Phase 3 ecosystem plays remain). Falsification: if the D6e+ backlog still contains "PACKAGE_NO_IMPORT_CYCLE" or "FIELD_NOT_REQUIRED" after D6e ships, the arc didn't actually close.
- [ ] **The `proto2-strict` profile is architecturally founded**: KD-11's per-syntax-version pattern is documented in a way that future deliveries (D6f+) adding `proto3-strict` or `editions-strict` rules can land cleanly without architectural debate. Falsification: if the first new proto2-strict rule (or proto3-strict rule) in a future delivery requires rewriting KD-11, the architecture wasn't durable.

## Scope Boundaries (Non-Goals)

- **No retroactive code changes** to D6a-D6c rules under the inverted philosophy. Audit findings are documentation-only; D6f+ resolves any code-level conflicts.
- **No `strict` profile activation** in D6e. The deferred `strict` profile (intended for COMMENT_* / ENUM_ZERO_VALUE_SUFFIX style-strictness rules) stays deferred. `proto2-strict` is distinct.
- **No expanded option-aware rules** (R6 promotion to error, IDENTIFIER-based field_behavior contradictions, MessageSet-aware rules, etc.). Those are D6f+ option-aware-deepening work.
- **No CLI flag for per-rule disable/enable** (R9b). Continues to be deferred; `[severities] = "off"` is still the de-facto disable mechanism (but the SUPERSEDED D6d brainstorm noted `"off"` is actually invalid — R9b remains deferred regardless).
- **No `LintLocation` exhaustiveness contract** decision in D6e.
- **No deep proto2 EV verification beyond the SUPERSEDED brainstorm's binding outcomes** (EV-5..EV-8 stay deferred per "verify post-ship only if user reports divergence" discipline).

## Key Decisions

**Philosophy + profile architecture (U1):**

- **D6e KD-1**: Hard-inverted philosophy — protokit-UX overrides buf-parity when they conflict. Retires U3-KD-6.
- **D6e KD-2**: Pragmatic proto2 stance — supported, no deprecation timeline, opt-in `proto2-strict` profile for strict checks.
- **D6e KD-3**: `proto2-strict` profile is a NEW profile distinct from the deferred `strict` profile. Do NOT consolidate. The profile is UX-forward signaling for ≥5 credible future proto2-specific rules (see KD-11), not premature abstraction for one rule. Profile name signals intent ("opt-in proto2-specific checks"); `[severities]` overrides require knowing each rule's id in advance.
- **D6e KD-4**: Audit pass on D6a-D6c rules. No retroactive code changes in D6e EXCEPT `file/syntax-specified` demotion (handled separately in R4b per CONV-A 4-way reviewer convergence). Other audit findings (if any) become D6f+ backlog items in TODOS.md with concrete forcing-function triggers per PL-4.

**Rule-shape decisions (U2 + U3):**

- **D6e KD-5**: `field/not-required` ships in `proto2-strict` profile only at ERROR severity.
- **D6e KD-6**: `package/no-import-cycle` uses package-level edge granularity. Cycle = SCC of size ≥ 2.
- **D6e KD-7**: `package/no-import-cycle` emission shape bound to buf v1.69.0 at Phase 0 (no pre-commitment).
- **D6e KD-8**: `package/no-import-cycle` profile + severity probably matches buf BASIC (ERROR in `recommended` + `default`) — confirm at Phase 0.

**Closing-headline framing (U4):**

- **D6e KD-9**: Closing headline = **"26 of 26 buf v1.69.0 BASIC rules (with one documented divergence on extend-block-required-fields, deferred to a future engine walker extension)."** The v1.69.0 qualifier is load-bearing — the denominator was empirically bound to v1.69.0 during D6c per [[audit-wire-format-before-claiming-sibling-parity-2026-05-03]] + [[plan-review-verify-prior-art-citations-2026-05-15]]; pinning the qualifier in every claim site prevents the "26/26 → 26/N" silent drift when buf ships a new BASIC rule in a later version. Numerator + qualifier updated grep-visibly across README, CHANGELOG, BUILTIN_PACKS docstring, CLI --help epilog. Maintenance trigger: when a future buf BASIC audit confirms a new rule (e.g., buf v1.70.0+), update the denominator + add migration note documenting the new gap.
- **D6e KD-10**: `field/not-required` extend-block divergence is **explicit + asterisked**, not silent. Per EV-2 PRE-DECIDED OUT-OF-SCOPE (engine walker gap at `engine.py:818-893` never iterates `fd.extensions_by_name`), buf v1.69.0 fires `FIELD_NOT_REQUIRED` on extend-block required fields while protokit does NOT. **Per CONV-F resolution**: the asterisk must be LOUDLY visible to the `proto2-strict` opt-in audience, whose trust calculus differs from the originally-planned `recommended`+`default` audience (opt-in users want comprehensive proto2 enforcement; silent under-detection is more user-trust-eroding). Three documentation sites for the asterisk: (1) `proto2-strict` profile's README table row + opt-in framing prose, (2) `field/not-required` rule module docstring, (3) the rule's `--help` epilog + CHANGELOG D6e "Behavior changes" subsection. Each site enumerates the extend-block divergence + forward-points to a D6f+ engine-walker extension as the resolution target.

**Architectural commitments (U1 + U3 + U4):**

- **D6e KD-11**: Per-syntax-version profile pattern is the committed architecture. Each syntax version may grow its own opt-in strict profile when strict-only rules surface for that syntax. Expected final-state (when concrete rules ship): `proto2-strict` (now), potentially `proto3-strict` (for proto3-explicit-presence rules, packed-default-vs-explicit rules), `editions-strict` (for edition-feature-flag opt-in patterns). Each profile's rules are syntax-specific; users opt into the profiles that match their syntax. Accepted cost: README profile table grows by one row per syntax-strict profile shipped. Rationale for choosing the per-syntax path over the flat-`strict`-with-syntax-aware-rules path: profile names communicate intent at the CLI surface (`--profile proto2-strict` reads as opt-in to proto2 strictness), and `[severities]` overlays let users tune individual rules without changing the profile machinery. **Concrete proto2-specific rule landscape that motivates the pattern**: `field/no-group-syntax` (proto2-only `group`), `field/no-extend-blocks` (extend-block compatibility risks), `field/no-explicit-default` (proto2's `default = X`), `field/packed-repeated-primitive` (proto2 packed annotation), `file/no-messageset-wire-format` (deprecated proto2 wire format). At least 5 credible rules; the profile architecture is the home for these as they surface in D6f+.
- **D6e KD-12**: U3 cycle-detection architecture direction-of-travel (Phase 0 verifies; planning binds):
  - **Algorithm**: Tarjan SCC pre-walk (matches D6c's Arch-D dual-view accumulator pattern). DFS back-edge as fallback if Tarjan turns out to be overkill for typical graph sizes.
  - **Engine integration**: extend the existing pre-walk pattern with a new accumulator (`_build_import_graph_accumulator` or similar) returning a Tarjan-computed SCC list + a `package → root_files` reverse-lookup view. Adds one field to `FileLintContext` (likely `import_cycles: tuple[frozenset[str], ...]` or similar — planning binds shape).
  - **Scope**: fire if ANY root file participates in the cycle (the middle option per adversarial ADV-4). NOT "root_files only" (misses cycles through vendor packages user could fix). NOT "include transitives" (fires on vendor-only cycles user can't fix). The middle option is the semantically correct fence for a lint rule.
  - **Emission shape**: per-file emission via the package→root_files fan-out — each root file participating in an SCC of size ≥ 2 gets one finding. Matches D6c's R8/R8b precedent. Phase 0 verifies buf v1.69.0 actually emits per-file; if it diverges (per-cycle or per-package), planning re-opens the emission decision with the buf shape as the anchor.
  - **Co-fire ordering**: `package/no-import-cycle` joins `package.py`'s RULES tuple. Phase 0 verifies whether it co-fires with R8/R8b on any fixture and whether buf's emission order alphabetically puts `PACKAGE_NO_IMPORT_CYCLE` between `PACKAGE_DIRECTORY_MATCH` and `PACKAGE_SAME_DIRECTORY` (per feasibility F4). Planning binds the tuple position to match buf's co-fire ordering.

  This is direction-of-travel, not a binding decision — Phase 0 may falsify any branch, and planning is empowered to revise with empirical justification.

- **D6e KD-13**: CLI dedup regression test is **parametrized over BUILTIN_PACKS** at D6e (consolidating the prior per-flip files). Per [[shared-helper-third-instance-trigger]] discipline, the 3rd instance triggers extraction; D6d new-U4 extracted the shared helper, D6e is the consolidation moment. Replace `test_cli_rule_pack_dedup_post_d6c.py` + `test_cli_rule_pack_dedup_post_d6d.py` (post-fold of their bodies into a single parametrized test) + the planned `test_cli_rule_pack_dedup_post_d6e.py` with one file (e.g., `tests/schema/lint/test_cli_rule_pack_dedup.py`) that iterates over every pack in `BUILTIN_PACKS`. ~60 LOC total vs ~540 LOC. The shared helper at `tests/schema/lint/_cli_dedup_helpers.py` remains the descriptor-set compilation SSOT. Per-pack overrides (specific fixture proto shapes that trigger findings) lift into per-parametrize-case data parameters.
- **D6e KD-14**: CLI dedup regression test (now parametrized per KD-13) **lands at U2/U3** — at the unit that introduces the new BUILTIN_PACKS member — NOT at U4 (delivery boundary). This matches the SUPERSEDED D6d U3 brainstorm's UR-7 + [[cli-loaded-packs-dedup-zip-strict-builtin-packs-flip-2026-05-18]]'s "load-bearing test ships with the mechanism" discipline. U4 retains the bump-contract ratchet + presence-ratchet test additions (those belong with the version bump + CHANGELOG section presence ratchet).

## Open Questions (Deferred to Phase 0 / Planning)

- **OQ-1**: Does buf v1.69.0 emit one finding per cycle, per file in cycle, or per package in cycle for `PACKAGE_NO_IMPORT_CYCLE`? Phase 0 empirical binding.
- **OQ-2**: Does buf v1.69.0's cycle detection scope include transitive imports through vendor packages, or only root files? Phase 0.
- **OQ-3**: What is `PACKAGE_NO_IMPORT_CYCLE`'s buf BASIC profile membership empirically? Phase 0.
- **OQ-4**: Algorithm choice for cycle detection (DFS back-edge vs Tarjan SCC). Planning decision; emission shape (OQ-1) affects this. Kahn's topological-sort approach detects DAG-ness but does NOT enumerate SCCs — excluded from candidates because KD-6 defines a cycle as an SCC of size ≥ 2, and Kahn's would not produce that artifact.
- **OQ-5**: Does `field/not-required` live in a new `field` rule pack (mirroring `file.py`) or extend an existing pack? Planning decision; trades off pack-count proliferation against module-per-rule clarity.
- **OQ-6**: For `field/not-required`, do the EV-2 (extend-block extensions) and EV-3 (group-typed required) outcomes from the SUPERSEDED brainstorm still bind? Confirm at Phase 0 of U2.

## Inputs (Prior Art / References)

- `docs/brainstorms/2026-05-20-d6d-u3-field-not-required-requirements.md` (SUPERSEDED-pending-philosophy-revision) — load-bearing analytical input for U2. EV-1..EV-4 binding outcomes; rule body shape UR-6 still correct; severity/profile decisions superseded by D6e KD-5.
- `docs/brainstorms/2026-05-20-protokit-ux-philosophy-revision-requirements.md` (PLACEHOLDER) — the 4 interlocked pieces (principle articulation, file/syntax-specified retroactive treatment, proto2-aware profile, existing-rules audit). U1 of D6e resolves Pieces 1, 3, and 4; Piece 2 (`file/syntax-specified` retroactive treatment) is surfaced as an audit finding and deferred to D6f+ per D6e KD-4 (no retroactive code changes in D6e). Naming divergence: Piece 3 named the profile `proto2-friendly` (subtractive — REMOVES proto2-hostile rules from a default base for intentional-proto2 users); D6e renames to `proto2-strict` (additive — ADDS strict checks for users opting in). These serve opposite user populations; the `proto2-friendly` framing is not carried forward in D6e.
- `docs/brainstorms/2026-05-19-d6d-option-aware-pack-expansion-requirements.md` — D6d umbrella; references the Strategic Deferral that rolled FIELD_NOT_REQUIRED into D6e+.
- `docs/plans/2026-05-18-003-feat-d6c-r8-r8b-cross-file-package-rules-plan.md` — D6c's Arch-D pre-walk accumulator pattern; reference for U3's engine-architecture planning.
- `docs/solutions/best-practices/multi-unit-ce-review-stash-pop-coordination-2026-05-21.md` — apply the per-unit pipeline discipline across U1-U4.
- `docs/solutions/best-practices/delivery-boundary-unit-commit-composition-2026-05-14.md` — U4 boundary commit composition.
- `docs/solutions/logic-errors/cli-loaded-packs-dedup-zip-strict-builtin-packs-flip-2026-05-18.md` — U4 CLI dedup regression test discipline.
- `docs/solutions/best-practices/migration-recipe-severity-aware-template-reuse-2026-05-21.md` — U4 CHANGELOG migration recipe authoring discipline.
- `docs/solutions/best-practices/changelog-readme-snippet-fixture-byte-equivalence-2026-05-21.md` — applies to U2 (FIELD_NOT_REQUIRED fixture pyproject snippets) + U3 (cycle fixture proto files).
- `TODOS.md` D6e+ backlog section — items rolled forward from D6d Strategic Deferral.

## Visual: D6e Scope at a Glance

```
┌─────────────────────────────────────────────────────────────┐
│ D6e — buf BASIC closure + UX philosophy revision (0.6.0)    │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  U1: UX Philosophy Revision (atomic with U2 per CONV-C)     │
│  ├─ Hard inversion principle (D6e KD-1, retires U3-KD-6)    │
│  ├─ Pragmatic proto2 stance (D6e KD-2)                      │
│  ├─ Activate `proto2-strict` profile (D6e KD-3 + KD-11)     │
│  ├─ Audit-only on D6a-D6c rules except file/syntax-spec'd   │
│  │   (D6e KD-4; trigger for D6f+ per PL-4)                  │
│  └─ Demote file/syntax-specified to WARNING (R4b; CONV-A)   │
│                                                              │
│  U2: field/not-required (proto2-only buf BASIC rule)        │
│  ├─ UR-6 rule body (from SUPERSEDED D6d U3 brainstorm)      │
│  ├─ proto2-strict profile, ERROR severity (D6e KD-5)        │
│  ├─ EV-1/EV-3/EV-4 Phase 0 outcomes; EV-2 PRE-DECIDED       │
│  │   OUT-OF-SCOPE (engine walker gap)                       │
│  ├─ Extend-block divergence asterisked LOUDLY in 3 sites    │
│  │   per CONV-F + D6e KD-10                                 │
│  ├─ Buf v1.69.0 parity gate                                 │
│  ├─ CLI dedup parametrized test lands HERE per D6e KD-14    │
│  └─ (Ships atomically with U1 per CONV-C; one feat commit)  │
│                                                              │
│  U3: package/no-import-cycle (26th buf v1.69.0 BASIC rule)  │
│  ├─ Package-level edges, SCC>=2 cycle definition (D6e KD-6) │
│  ├─ Tarjan SCC pre-walk + per-file emission via package→    │
│  │   files fan-out (D6e KD-12 direction-of-travel)          │
│  ├─ Scope: fire if ANY root file participates (KD-12)       │
│  ├─ Phase 0 verifies buf v1.69.0 emission + co-fire order   │
│  └─ Buf v1.69.0 parity gate                                 │
│                                                              │
│  U4: Delivery Boundary (0.6.0)                              │
│  ├─ pyproject 0.5.0 -> 0.6.0                                │
│  ├─ CHANGELOG ### D6e section                               │
│  ├─ README: "26 of 26 buf v1.69.0 BASIC rules (with one     │
│  │   documented divergence on extend-block)" (D6e KD-9)     │
│  ├─ BUILTIN_PACKS: package pack +1 cycle rule, field pack   │
│  │   possibly new (defer to planning)                       │
│  ├─ Presence-ratchet (D6e ChangelogRatchetSpec)             │
│  ├─ Bump-contract ratchet (no schema_version bump in D6e)   │
│  └─ Stale-text sweep                                         │
│                                                              │
└─────────────────────────────────────────────────────────────┘

  Closes the buf-parity arc: D6a (17/18) -> D6b (23/26) ->
  D6c (25/26) -> D6d (25/26; option-aware headline, parity
  unchanged) -> D6e (26/26 v1.69.0 with one documented
  extend-block divergence; D6f+ engine walker work resolves
  the divergence as an architectural delivery).
```

## Next Steps

1. `/ce:plan` against this brainstorm to produce the 4-unit implementation plan with concrete file paths, test scenarios, EV verification scripts, and unit sequencing.
2. The plan should explicitly anchor U2's Phase 0 EV outcomes against the SUPERSEDED brainstorm's analytical work (do NOT re-derive EV-1..EV-4; bind them).
3. The plan should propose the algorithm + engine-architecture decision for U3's cycle detection (DFS back-edge vs Tarjan SCC vs new pre-walk phase) with explicit Phase 0 verification steps for OQ-1 and OQ-2.
4. Per [[multi-unit-ce-review-stash-pop-coordination-2026-05-21]], the implementation will run the per-unit ce:review pipeline (U1 → review → compound → U2 → review → compound → U3 → review → compound → U4 → review → compound) on a single feature branch using stash-pop scope isolation.
