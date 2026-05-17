---
title: protokit-lint D6b U5 — R9 severities_unloaded_rule category split + schema_version 0.2 → 0.3 bump
type: feat
status: active
date: 2026-05-17
origin: docs/brainstorms/2026-05-17-d6b-u5-r9-severities-category-split-requirements.md
---

# protokit-lint D6b U5 — R9 `severities_unloaded_rule` category split + `schema_version` 0.2 → 0.3 bump

## Overview

U5 closes the D6a U9 KTD-2 deferred-design trip-wire with a surgical wire-format-additive change. Three coupled edits ship as one atomic `feat(lint)` commit:

1. **Widen `LintRuntimeWarning.category: Literal[...]`** from 4 to 5 values by adding `"severities_unloaded_rule"`. The CLI-synthesized emit site switches to the new value; the engine-emitted `"unloaded_rule"` path remains unchanged. Consumers gain a programmatic discriminator and no longer need to match message substrings to tell the two emit sites apart.

2. **Bump `_LINT_JSON_SCHEMA_VERSION` from `"0.2"` to `"0.3"`** via a single-constant edit that cascades to both `lint_json` (top-level `schema_version`) and `lint_sarif` (`runs[0].properties.lint_schema_version`) per the cross-format-enum-string-parity discipline.

3. **Refine the bump-contract docstring** to distinguish closed Literal discriminators (bump trigger) from open severity-string ladders (NOT a bump trigger). The refinement is required — the current docstring's blanket "enum-value additions don't bump" language would contradict the bump action.

Six implementation units bundle into the same commit; sequencing is for implementation clarity, not commit boundaries (mirrors D6b U3a / U4a / U4b shape).

## Problem Frame

D6a U9 R9a wired per-rule severity overrides from `[tool.protokit.lint.severities]` into the CLI's composed profile. Keys naming a rule not in the composed profile needed to surface as a `LintRuntimeWarning`. The natural emit site is the CLI itself.

Rather than widen the `LintRuntimeWarning.category` Literal at the moment of introduction (a wire-format change for a brand-new emit site whose user-feedback signal was unproven), U9 KTD-2 accepted the conflation: reuse the existing `"unloaded_rule"` category value and let consumers distinguish via message substring. The U9 ce:review F5 finding (cli-readiness reviewer, 2026-05-13) recommended the dedicated category split land in D6b.

D6b is the next minor bump window. The Literal widening is strictly additive (no existing engine-emit-site consumer breaks). The schema_version bump is the documented wire-format signal that consumers should re-check their switch statements. U5 is the smallest possible unit that closes the trip-wire while satisfying the bump-contract (see origin: `docs/brainstorms/2026-05-17-d6b-u5-r9-severities-category-split-requirements.md`).

## Requirements Trace

- **R9** — `severities_unloaded_rule` category split: Literal widening + CLI emit-site switch (see origin: R9 section, R9-tests-coupled section).
- **R9-bump** — `_LINT_JSON_SCHEMA_VERSION` 0.2 → 0.3 bump (see origin: R9-bump section).
- **R9-docstring** — Bump-contract docstring refinement (KTD-5) + runtime_warnings docstring rewrite (see origin: R9-docstring section).
- **R9-README** — 4-site README wire-format reference update (see origin: R9-README section).
- **R9-changelog-draft** — `CHANGELOG-DRAFT.md` U5 staging entry + U7 eventual-scope list append (see origin: R9-changelog-draft section).
- **R9-TODOS** — `TODOS.md` U9 KTD-2 backlog retirement (see origin: R9-TODOS section).
- **R9-tests-coupled** — Lockstep test/helper updates that pin the 4-value Literal shape (see origin: R9-tests-coupled section).

**Success criteria carried forward from origin:**

- User-outcome SC-1 — programmatic consumers can distinguish engine-emitted vs CLI-synthesized "unloaded rule" warnings by switching on `category`.
- User-outcome SC-2 — `schema_version` reads `"0.3"` in both `lint_json` and `lint_sarif`.
- User-outcome SC-3 — bump-contract docstring justifies the 0.2 → 0.3 bump.
- User-outcome SC-4 — CHANGELOG-DRAFT.md U5 staging entry is consumer-actionable.
- User-outcome SC-5 — README's wire-format references reflect U5 state.
- Engineering invariants 1-8 (engine-emit BEHAVIOR unchanged, dataclass-construction tests survive with coupled updates, helper-mirror sync, cross-format-parity, lint_human/lint_junit unchanged, sanitization preserved, SARIF runtime_warnings co-existence, TODOS slot preserved).

## Scope Boundaries

- **R9b — per-rule disable/enable lists** (`disabled_rules` / `enabled_rules`): different design space, needs real-demand evidence for 4 collision-shape precedence semantics. Stays deferred to post-D6b.
- **Presence-ratchet test pinning the refined bump-contract docstring wording**: per parent plan Risks table line 666, U7's CHANGELOG presence-ratchet handles this. U5 lands the refined wording; U7 pins it.
- **General "wire-format hygiene" sweep** across other potentially-closed Literals: out of scope. Bump-contract refinement is the load-bearing contract for future closed-Literal additions; specific value additions wait for their own delivery slots.
- **U7's broader README Schema Linting section refresh** (R7 BUILTIN_PACKS registration, rule_id enumeration, `--rule-pack` doc-section relocation): owned by U7.
- **U7's CHANGELOG-DRAFT.md fold into `CHANGELOG.md`**: U5 stages content in DRAFT; U7 owns the published CHANGELOG composition at the 0.3.0 delivery-boundary commit.

### Deferred to Separate Tasks

- **`docs/solutions/` cross-reference updates**: U5 ce:compound pass owns updates to `semantic-category-conflation-accepted-tradeoff-literal-widening-2026-05-13.md` (mark resolution) + `wire-format-schema-version-bump-contract-and-absence-semantic-2026-05-13.md` (extend with closed-Literal worked example). Not in the feat commit.
- **U5 ce:review follow-ups**: separate `fix(lint): D6b U5 ce:review follow-ups` commit per established D6b pattern.
- **U5 ce:compound pass**: separate `docs(solutions): D6b U5 ce:compound` commit (expected scope: 1-2 learnings + the discipline-doc resolution annotation).

## Context & Research

### Relevant Code and Patterns

- **`src/protokit/schema/lint/model.py:352-505`** — `LintRuntimeWarning` frozen dataclass + `category: Literal[...]` discriminator + dataclass-level docstring enumerating emit-site contracts.
- **`src/protokit/schema/lint/model.py:543-549`** — `LintReport.runtime_warnings` field docstring containing a sibling 4-category narrative enumeration ("Four categories share the type: `rule_exception` and `unloaded_rule` (engine-emitted) plus ..."). Becomes stale post-Literal-widening; refresh in Unit 1.
- **`src/protokit/schema/lint/cli.py:1076-1100`** — CLI-synthesized severities_unloaded warning emit site + the inline comment block currently rationalizing the U9 KTD-2 conflation reuse.
- **`src/protokit/schema/lint/engine.py:380-395`** — engine-emitted `unloaded_rule` site (UNCHANGED by U5). Surrounding docstring at `:300-315` narrates the "Compute unloaded-rule diff" step.
- **`src/protokit/formatters/_builtin_lint.py:226-260`** — `_LINT_JSON_SCHEMA_VERSION` constant + multi-clause docstring (current bump contract + field-absence semantic from D6a U9).
- **`src/protokit/formatters/_builtin_lint.py:253-340`** — `lint_json` formatter; `schema_version` emit site at `:329`.
- **`src/protokit/formatters/_builtin_lint.py:558-690`** — `lint_sarif` formatter; `lint_schema_version` emit site at `:673`.
- **`src/protokit/formatters/_builtin_lint.py:265-271`** — `lint_json` docstring's `runtime_warnings` characterization (currently engine-vs-CLI null contract — becomes inaccurate post-U5).
- **`tests/schema/lint/cli/_helpers.py:1-113`** — `LINT_RUNTIME_WARNING_CATEGORIES` tuple + `warning_for_category` factory; docstring at `:24-30` explicitly names U5 as the act that requires updating both.
- **`tests/schema/lint/test_model_dataclass_changes.py:38-79`** — `test_literal_lists_all_four_categories` count-pin + `test_test_helper_mirror_stays_in_sync_with_model` drift-detection.
- **`tests/schema/lint/test_model_dataclass_changes.py:140-160`** — `TestFrozen.test_assignment_raises_for_every_category` parametrize over 4 `(category, rule_id)` tuples.
- **`tests/schema/lint/test_model.py:828-883`** — sibling construct tests per category (the pattern to follow for the new value).
- **`tests/schema/lint/cli/test_r9a_severities_overlay.py:80-115`** — currently asserts `category == "unloaded_rule"` for the CLI emit site; assertion flips post-U5.
- **`tests/schema/lint/cli/test_r9d_schema_version.py`** — `_SCHEMA_VERSION = "0.2"` constant + cross-format parity test at `:84`.
- **`tests/test_builtin_lint_runtime_warnings.py:340-380`** — SARIF runtime_warnings + lint_schema_version co-existence tests.
- **`README.md:656-770`** — JSON output shape table (`:663` schema_version row + `:666` category enumeration) + Public Surface DRAFT table (`:740-770` with `:760` and `:763` schema_version rows).
- **`CHANGELOG-DRAFT.md`** — existing D6b U4b dormancy-window section + U7 eventual-scope list (the staging pattern U5 extends).
- **`TODOS.md:163-176`** — D6b backlog items including the U9 KTD-2 severities_unloaded_rule split bullet.

### Institutional Learnings

- **[[semantic-category-conflation-accepted-tradeoff-literal-widening]]** — U5 closes the deferred design captured in this doc. The 3-site discipline applies in reverse: Literal docstring + CLI emit-site comment + TODOS.md bullet all retire as the split lands.
- **[[wire-format-schema-version-bump-contract-and-absence-semantic]]** — U5 is the first closed-Literal-discriminator addition that exercises the bump contract introduced in D6a U9. KTD-5's docstring refinement extends this doc's contract by formalizing the closed-vs-open distinction.
- **[[cross-format-enum-string-parity-2026-05-08]]** — `lint_json["schema_version"]` and `lint_sarif["runs"][0]["properties"]["lint_schema_version"]` continue to emit the SAME string value (`"0.3"` after U5). Single constant enforces structurally.
- **[[pre-1.0-version-bump-as-communication-contract]]** — the 0.2 → 0.3 bump is a pre-1.0 minor bump signaling "wire-format changed in a consumer-detectable way; re-check switch statements" — not a SemVer-major-style breaking-change marker.
- **[[delivery-boundary-unit-commit-composition]]** — U5 is a per-unit commit (additive wire-format change); U7 is the delivery-boundary commit. U5's CHANGELOG-DRAFT staging entry feeds into U7's composition.
- **[[dormant-code-changelog-draft-staging-delivery-boundary-2026-05-17]]** — the established D6b pattern for staging per-unit notes in `CHANGELOG-DRAFT.md` between unit-N and the U_final boundary fold. U5 follows the same shape (a `## D6b U5 (unreleased, ...)` section).
- **[[public-surface-draft-discipline-source-audit]]** — README's Public Surface DRAFT table is the contract surface; U5 updates 2 of its rows.
- **[[stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12]]** — ancillary docstrings at `_cli_utils.py:56,61` + `_builtin_lint.py:411` that enumerate the 4-category Literal in narrative form may need a coupled refresh (handled by Unit 6).
- **[[parametrized-matrix-tests-inherit-schema-validators-2026-05-12]]** — the cross-formatter matrix at `test_builtin_lint_runtime_warnings.py` iterates `LINT_RUNTIME_WARNING_CATEGORIES`; once the new value joins the tuple + the factory branch exists, matrix coverage extends automatically.
- **[[ce-review-cross-reviewer-agreement-shared-misreading-false-positive-amplifier-2026-05-14]]** — the U5 brainstorm's document-review pass surfaced one false-positive (COH-1 terminology drift) that was invalidated when verified against the source — the doc only uses the correct term. Plan-stage verification of reviewer claims remains discipline.

### External References

- Not used. U5 is closing a known internal trip-wire with verified codebase surfaces; no external best-practices research adds value.

## Key Technical Decisions

- **One feat commit, six implementation units** — units exist for sequencing clarity but bundle into a single `feat(lint): D6b U5 — R9 severities_unloaded_rule category split + schema_version 0.2 → 0.3` commit. Mirrors D6b U3a / U4a / U4b shape. Splitting into multiple commits would create intermediate states where docstrings + constants + tests disagree.

- **Test layout — option (a): in-place updates + 1 new module for source-discrimination** (resolves origin Open Question "Test file layout"). Update existing assertions at `test_r9a_severities_overlay.py:104`, `test_r9d_schema_version.py:21`, `test_builtin_lint_runtime_warnings.py:344,374` in place. Add `tests/schema/lint/cli/test_severities_unloaded_rule_category.py` (NEW) holding the source-discrimination contract assertion (both branches in same module). Locality wins over centralization; the new module covers what existing tests don't (the cross-source negative assertion per the document-review ADV-6 finding).

- **Source-discrimination test shape — parametrized + negative assertion** (resolves origin Open Question "Test source-discrimination shape" + addresses ADV-6 document-review residual). The new test module asserts BOTH that the CLI-emit path produces `category="severities_unloaded_rule"` AND that the engine-emit path produces ZERO `unloaded_rule` warnings for the SAME `rule_id` — source disambiguation by positive assertion on the expected branch + negative assertion on the other branch. Prevents the silent-test-confidence failure mode where the test passes for the wrong reason.

- **README JSON-shape table — keep inline 5-value enumeration** (resolves origin Open Question "README JSON-shape table value rendering"). The cell extending from 4 to 5 inlined category values stays at ~95 chars, still readable in markdown rendering. A bullet-list rewrite would scope-creep into broader table-format work owned by U7's README refresh.

- **Ancillary docstrings — refresh in U5** (resolves origin Engineering Invariant #1 ancillary-docstring deferral). The stale-text accumulation risk per `[[stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12]]` argues for in-U5 inclusion. Scope is narrow: `_cli_utils.py:56,61` (4→5 categories narrative) + `_builtin_lint.py:410-411` (explicit category list — the existing "plus any future category" note already future-proofs the prose). `cli.py:35-45` stays unchanged (engine-only enumeration; U5 adds a CLI-emit category, not an engine-emit one). `engine.py:305` stays unchanged (mentions only the engine-emitted unloaded_rule path, which is UNCHANGED). Verified via codebase grep at planning time.

- **CHANGELOG-DRAFT.md U5 staging entry includes the U7-list append** (resolves document-review SCOPE-1 P1 finding). The brainstorm's R9-changelog-draft requires both a new `## D6b U5 (unreleased, wire-format additive)` section AND an append to `## D6b U7 — eventual CHANGELOG content scope (suggested)`. Plan keeps both per the established D6b dormancy pattern: U4b's CHANGELOG-DRAFT entry similarly pre-wrote U7 scope items as resilience against U7 fold-time content loss. The minor overreach into U7's authorship territory is the accepted tradeoff for delivery-boundary safety.

- **Coupling acknowledgement: R9-bump and R9-docstring are inseparable** (resolves document-review COH-3 P1 finding). The bump-contract docstring refinement is the load-bearing contract that justifies the 0.2 → 0.3 bump; shipping R9-bump without R9-docstring would leave contradictory documentation. Plan units treat them as coupled (single implementation unit — Unit 2). The brainstorm's split into two requirement sections (R9-bump + R9-docstring) is descriptive; the implementation is one.

- **Bump-scope clarification (closed Literal value ONLY)** (resolves document-review ADV-2 P1 finding). The 0.2 → 0.3 bump is justified by R9's `category` Literal widening ONLY. The bump-contract docstring rewrite IS a change-in-meaning to the contract narrative, but the docstring is documentation-only (not a wire payload field that consumers parse) — its rewrite does NOT independently trigger a bump. New `rule_id` strings landing in `LintFinding` output from R6 (shipped U3) and R7 (shipped dormant U4b) also do NOT trigger bumps. The plan's commit message + CHANGELOG-DRAFT staging entry both make this scope-clarification explicit.

- **Scope claim refinement (independent of R6/R7 EXECUTION, dependent on R6/R7 CONTEXT for bump-contract framing)** (addresses document-review COH-2 P1 finding). U5 is independent of R6/R7 for code execution — no shared files, no import dependencies, no engine-plumbing reuse beyond what's already shipped. The bump-contract refinement's closed-vs-open distinction is grounded in BOTH the closed `category` Literal (R9's domain) AND the open `rule_id` ladder (R6/R7's domain), but R6/R7 are shipped predecessors providing context, not blockers. The plan documents both scope dimensions to prevent future re-litigation.

## Open Questions

### Resolved During Planning

- **Test file layout** — Resolved as option (a): update-in-place + 1 new source-discrimination module (see Key Technical Decisions).
- **Test source-discrimination shape** — Resolved as parametrized + negative-assertion pattern (see Key Technical Decisions).
- **README JSON-shape table value rendering** — Resolved as inline 5-value enumeration (see Key Technical Decisions).
- **Ancillary docstring scope** — Resolved as in-U5 inclusion for the 2 narrative-enumeration sites only (`_cli_utils.py:56,61` + `_builtin_lint.py:411`); other potential sites verified clean (see Key Technical Decisions).
- **runtime_warnings docstring rewrite scope** — Resolved at brainstorm document-review stage (FEAS-3 auto-fix); the rewrite is mandatory in U5 and now lives in R9-docstring as a coupled deliverable (see Unit 2).
- **CHANGELOG-DRAFT U7-list append vs. trust-U7 stance** — Resolved as include-the-append per established D6b precedent (see Key Technical Decisions).

### Deferred to Implementation

- **Exact wording of the LintRuntimeWarning.category docstring's "U5 split note"** — the brainstorm requires "a one-paragraph note explaining the U5 split" in the dataclass docstring; the exact phrasing emerges during implementation alongside the refined per-category contracts. Plan provides directional guidance; not pre-written prose.
- **Exact wording of the refined CLI emit-site inline comment** — the brainstorm requires removing the old conflation-rationale and replacing with an audit-trail note pointing at the LintRuntimeWarning.category docstring; the exact phrasing emerges during implementation.
- **Exact phrasing of CHANGELOG-DRAFT U5 staging entry** — the brainstorm enumerates the 4 required content items (version bump scope, new Literal value, consumer-migration note, bump-contract docstring pointer); the prose composition emerges during implementation.
- **Test method name for the new test_model.py construct test** — should mirror sibling pattern (`test_severities_unloaded_rule_category_constructs_with_rule_id_populated` or similar); name emerges during implementation.

## Implementation Units

- [ ] **Unit 1: Literal widening + helper-mirror lockstep updates**

**Goal:** Add `"severities_unloaded_rule"` as the 5th value of `LintRuntimeWarning.category: Literal[...]` + update the dataclass docstring to enumerate 5 emit sites with per-category contracts + bring 4 lockstep test/helper sites into sync with the widened Literal.

**Requirements:** R9, R9-tests-coupled.

**Dependencies:** None.

**Files:**
- Modify: `src/protokit/schema/lint/model.py` (`LintRuntimeWarning.category: Literal[...]` at `:500-505` adds `"severities_unloaded_rule"` as 5th value; dataclass-level docstring at `:352-497` updates to enumerate 5 items — split current item 2 into 2 + 3 with per-emit-site contracts; renumber items 3/4 to 4/5; remove the "Distinguish via message content" subsection; add a one-paragraph "U5 split note" explaining the resolution; also refresh the sibling `LintReport.runtime_warnings` field docstring at `:543-549` from "Four categories share the type: `rule_exception` and `unloaded_rule` (engine-emitted) plus `min_severity_relaxed` ... and `all_files_excluded` ..." to enumerate 5 categories with `severities_unloaded_rule` placed in the CLI-emitted-with-rule_id slot — keeps the field's narrative consistent with the widened Literal)
- Modify: `tests/schema/lint/cli/_helpers.py` (add `"severities_unloaded_rule"` to `LINT_RUNTIME_WARNING_CATEGORIES` tuple at `:31-36`; add 5th branch to `warning_for_category` factory at `:62-113` matching the engine-emit-with-rule_id shape — `category="severities_unloaded_rule"`, `rule_id=f"missing/severities-key-{index}"`, message mirroring CLI emit-site phrasing; update tuple docstring at `:24-30` from "4 categories ... as of D5 U5" to "5 categories ... as of D6b U5")
- Modify: `tests/schema/lint/test_model_dataclass_changes.py` (bump `assert len(literal_args) == 4` to `== 5` at `:54`; rename test method `test_literal_lists_all_four_categories` to `test_literal_lists_all_five_categories`; add `"severities_unloaded_rule"` to the expected-set assertion in same test; append `("severities_unloaded_rule", "rule/id")` as 5th tuple to `TestFrozen.test_assignment_raises_for_every_category` parametrize at `:144-151`; update module docstring's "2 → 4 categories" history note to "2 → 4 → 5 categories"; also refresh stale "all four categories" narrative at `:14` (module docstring) + `:139` (section-divider comment "# Frozen-dataclass discipline preserved across all four categories") to "all five categories" — keeps the module's narrative consistent with the renamed test method and the widened parametrize list)
- Test: `tests/schema/lint/test_model.py` (add a new test method sibling to `test_unloaded_rule_category_constructs_with_optional_fields_none` at `:845-879` — assert `LintRuntimeWarning(category="severities_unloaded_rule", rule_id="some/id", message="m")` constructs cleanly + populates `rule_id` + leaves `exception_type` / `descriptor_path` as `None`)

**Approach:**
- Land the Literal widening + docstring rewrite first; all subsequent units depend on the new value existing in the type system.
- Lockstep updates to `_helpers.py` + `test_model_dataclass_changes.py` are co-required: the `len(literal_args) == 4` ratchet fires on the next test run if not bumped; the drift-detection cross-check at `test_model_dataclass_changes.py:72` fires if the tuple isn't extended.
- Construct test in `test_model.py` follows the per-category construct-test pattern already established in the file (sibling tests for each of the 4 existing categories).
- The dataclass docstring rewrite is the largest single doc change in U5; care with renumbering items 3/4 → 4/5 to avoid stale cross-references in surrounding text.

**Patterns to follow:**
- Per-category construct test at `tests/schema/lint/test_model.py:828-883`.
- Factory branch shape at `tests/schema/lint/cli/_helpers.py:89-94` (the existing `unloaded_rule` branch is the closest sibling — same rule_id-populated shape).
- 3-site discipline application per `[[semantic-category-conflation-accepted-tradeoff-literal-widening]]` (in reverse — the discipline doc's 3 sites all peel off as the split lands).

**Test scenarios:**
- *Happy path:* `LintRuntimeWarning(category="severities_unloaded_rule", rule_id="some/id", message="m")` constructs cleanly; `warning.category == "severities_unloaded_rule"`; `warning.rule_id == "some/id"`; `warning.exception_type is None`; `warning.descriptor_path is None`.
- *Edge case:* `LintRuntimeWarning(category="severities_unloaded_rule", ...).category = "other"` raises `FrozenInstanceError` (covered by parametrized `TestFrozen.test_assignment_raises_for_every_category` extension).
- *Drift-detection:* `len(typing.get_args(LintRuntimeWarning.__dataclass_fields__["category"].type)) == 5` (covered by the renamed `test_literal_lists_all_five_categories`).
- *Helper-mirror:* `set(LINT_RUNTIME_WARNING_CATEGORIES) == set(typing.get_args(...))` (existing cross-check at `test_model_dataclass_changes.py:72` covers this — passes once both sites are updated in lockstep).
- *Factory coverage:* `warning_for_category("severities_unloaded_rule")` returns a populated `LintRuntimeWarning` with `rule_id` set (covered by any existing cross-formatter matrix test that iterates `LINT_RUNTIME_WARNING_CATEGORIES`).

**Verification:**
- 5 Literal values in model.py.
- Helper tuple has 5 entries; factory handles all 5.
- All existing dataclass tests pass; new construct test passes; renamed count-pin test passes at `len == 5`.
- Module docstring history note reflects the 2 → 4 → 5 progression.

---

- [ ] **Unit 2: Formatter constant bump + bump-contract docstring refinement + runtime_warnings docstring rewrite**

**Goal:** Bump `_LINT_JSON_SCHEMA_VERSION` from `"0.2"` to `"0.3"` + refine the bump-contract docstring to distinguish closed Literal discriminators from open severity-string ladders + rewrite the `runtime_warnings` docstring whose engine-vs-CLI null contract becomes inaccurate post-Literal-widening. All three changes ship in the same file because they form one coupled contract.

**Requirements:** R9-bump, R9-docstring.

**Dependencies:** None (independent of Unit 1's Literal widening — the constant bump signals the wire-format change but doesn't reference the new Literal value directly).

**Files:**
- Modify: `src/protokit/formatters/_builtin_lint.py` (constant edit at `:250`: `_LINT_JSON_SCHEMA_VERSION = "0.2"` → `"0.3"`; bump-contract docstring refinement at `:243-249` replaces single sentence with the closed-vs-open dichotomy from origin R9-docstring; `runtime_warnings` docstring at `:265-271` replaces the engine-vs-CLI null contract with a one-line pointer to `LintRuntimeWarning.category`'s per-category contract docstring — null-ness is per-category, not per-emit-site, after U5)
- Test: `tests/schema/lint/cli/test_r9d_schema_version.py` (`_SCHEMA_VERSION = "0.2"` → `"0.3"` at module-level constant `:21`; all 5 test methods using this constant pick up the bump automatically; also refresh module docstring at `:3` from `"schema_version": "0.2"` to `"schema_version": "0.3"` — keeps the docstring narrative consistent with the bumped constant)
- Test: `tests/test_builtin_lint_runtime_warnings.py` (2 SARIF schema_version assertions: `properties["lint_schema_version"] == "0.2"` → `"0.3"` at `:344` and `:374`)

**Approach:**
- Single-constant edit cascades to both consumption sites (`lint_json:329` + `lint_sarif:673`) via existing single-source-of-truth pattern. No format-specific edits needed.
- Bump-contract docstring refinement is the load-bearing contract that JUSTIFIES the constant bump. Without it, the docstring + the code form an inconsistent contract.
- `runtime_warnings` docstring rewrite collapses 6 lines of engine-vs-CLI null contract into a one-line pointer at the authoritative `LintRuntimeWarning.category` docstring (which Unit 1 updates with per-category contracts).
- `lint_human` and `lint_junit` formatters remain unchanged (they deliberately don't carry `schema_version`).

**Patterns to follow:**
- Single-constant cascade pattern per `[[wire-format-schema-version-bump-contract-and-absence-semantic]]` (the constant is the single source of truth; consumption sites read it).
- D6a U10's CHANGELOG section structure for the version-bump communication contract (referenced from parent plan, but the actual fold is U7's owner — U5 stages in DRAFT).
- Docstring pointer pattern: "see :class:`LintRuntimeWarning.category` for the per-category contract" — `_builtin_lint.py` already uses similar cross-pointers (`:260` and `:270`).

**Test scenarios:**
- *Happy path:* `protokit lint --format json <inputs>` produces top-level `"schema_version": "0.3"`.
- *Happy path:* `protokit lint --format sarif <inputs>` produces `runs[0].properties.lint_schema_version == "0.3"`.
- *Edge case:* `lint_human` output unchanged (no `schema_version` substring present); covered by existing human-format tests passing without modification.
- *Edge case:* `lint_junit` output unchanged (no `lint_schema_version` property present); covered by existing junit-format tests passing without modification.
- *Cross-format parity:* `test_json_and_sarif_schema_versions_agree` at `test_r9d_schema_version.py:84` passes with bumped value — JSON top-level + SARIF properties agree on `"0.3"`.
- *SARIF co-existence:* `runtime_warnings` property + `lint_schema_version` property both present under `runs[0].properties` (covered by existing tests at `test_builtin_lint_runtime_warnings.py:344,374` after the literal bump).
- *Documentation:* bump-contract docstring at `:243-260` contains both "closed Literal discriminators" and "open severity-string ladders" wording (verifiable by grep at code-review time; presence-ratchet test owned by U7).
- *Documentation:* `runtime_warnings` docstring at `:265-271` no longer claims null-vs-populated by emit-site; instead points at `LintRuntimeWarning.category` for the per-category contract.

**Verification:**
- `_LINT_JSON_SCHEMA_VERSION == "0.3"` in source.
- Both formatters emit "0.3" in their respective wire-format paths.
- Existing schema_version + runtime_warnings tests pass at the bumped value.
- Bump-contract docstring contains closed-vs-open distinction.
- `runtime_warnings` docstring is now a cross-reference, not a duplicate contract.

---

- [ ] **Unit 3: CLI emit-site category switch + R9a assertion update**

**Goal:** Switch the CLI-synthesized severities_unloaded warning's `category` from `"unloaded_rule"` to `"severities_unloaded_rule"` + rewrite the surrounding inline comment block to retire the conflation rationale + update the existing R9a test assertion that pins the old value.

**Requirements:** R9.

**Dependencies:** Unit 1 (the new Literal value must exist before cli.py can reference it; type-checking would fail otherwise).

**Files:**
- Modify: `src/protokit/schema/lint/cli.py` (`category="unloaded_rule"` → `category="severities_unloaded_rule"` at the CLI-synthesized warning ctor at `:1086-1100`; inline comment block at `:1076-1082` replaces the "Reuses the existing `unloaded_rule` category rather than introducing a new `severities_unloaded_rule` value... avoids a wire-format change in D6a" rationale with a one-paragraph audit-trail note pointing at the `LintRuntimeWarning.category` docstring + the schema_version 0.2 → 0.3 bump)
- Test: `tests/schema/lint/cli/test_r9a_severities_overlay.py` (assertion `if w["category"] == "unloaded_rule"` at `:104` → `if w["category"] == "severities_unloaded_rule"`; surrounding test method docstring + module docstring update to reflect that R9a now emits the dedicated category — the comment at `:13-16` that says "reuses the existing category per KTD-2; no new `LintRuntimeWarning.category` Literal value in D6a" gets a coupled refresh acknowledging U5 introduced the new value)

**Approach:**
- The `category=` argument swap is one line; the inline comment rewrite is the bulk of the cli.py change.
- The `_safe_for_stderr(rid)` sanitization at `cli.py:1090-1096` survives the rename verbatim — sanitization is per-rule_id, not per-category. Engineering invariant #6 from origin.
- The R9a test's assertion update is mechanical; the surrounding docstring refresh ensures future contributors don't read stale rationale.

**Patterns to follow:**
- 3-site discipline reversal per `[[semantic-category-conflation-accepted-tradeoff-literal-widening]]`: the CLI emit-site comment is the second of the 3 sites peeling off (Literal docstring = Unit 1; CLI comment = this unit; TODOS.md bullet = Unit 5).
- Existing inline-comment cross-reference pattern at `cli.py:1060-1062` (the comment pointing at the engine emit-site for ordering context) — the new audit-trail comment follows similar shape.

**Test scenarios:**
- *Happy path:* `[tool.protokit.lint.severities] "nonexistent-rule" = "warning"` invocation produces a `LintRuntimeWarning(category="severities_unloaded_rule", rule_id="nonexistent-rule", ...)` in lint_json output. Asserted by the updated `test_r9a_severities_overlay.py:104`.
- *Edge case:* `_safe_for_stderr` sanitization still applies — a severities key containing U+2028 / control characters surfaces sanitized in both the `rule_id` field and the message embed. Covered by existing R9a content-safety tests (none expected to fail; sanitization is per-rule_id, not per-category).
- *Edge case:* empty `[tool.protokit.lint.severities]` is a no-op (no warning emitted regardless of category value). Covered by existing R9a test.
- *Regression:* engine-emit-site warnings still carry `category="unloaded_rule"` for the profile-named-but-not-loaded case (Unit 4 covers the cross-source assertion; this unit's scope is the CLI emit only).

**Verification:**
- `cli.py:1087-1097` `LintRuntimeWarning(...)` ctor uses `category="severities_unloaded_rule"`.
- Inline comment at `:1076-1082` no longer rationalizes the conflation; instead names U5 as the resolution + points at the bump signal.
- R9a test passes with updated assertion.
- No new test failures elsewhere in the suite (engine-side tests at `test_engine.py:282,977` + content-safety tests at `test_engine_warning_content_safety.py:361-468` all continue asserting `category == "unloaded_rule"` for the engine-emit path).

---

- [ ] **Unit 4: Source-discrimination test (NEW)**

**Goal:** Add a new test module that asserts the source-discrimination contract — engine-emit produces `"unloaded_rule"`, CLI-emit produces `"severities_unloaded_rule"`, for the SAME `rule_id` value, with negative assertions on the other branch in each direction.

**Requirements:** R9 (source-discrimination contract from origin SC-1).

**Dependencies:** Unit 1 (Literal must exist) + Unit 3 (CLI emit-site must emit the new value).

**Files:**
- Create: `tests/schema/lint/cli/test_severities_unloaded_rule_category.py` (NEW — single-file module covering both branches via a parametrized fixture that combines a profile naming an unloaded rule + a `[tool.protokit.lint.severities]` table naming a different unloaded rule; asserts both `category="unloaded_rule"` AND `category="severities_unloaded_rule"` warnings appear with their expected `rule_id` values; asserts the CROSS — no `unloaded_rule` warning carries the severities-table key, no `severities_unloaded_rule` warning carries the profile-named key)

**Approach:**
- Single test module; ~80-120 lines.
- Module docstring names the contract: "U5 split — engine-emit retains `unloaded_rule`, CLI-emit gains `severities_unloaded_rule`; assertions on BOTH branches in same module make the contract structurally explicit."
- Test fixture pattern: a `pyproject.toml` with `[tool.protokit.lint.severities]` naming `"nonexistent-cli-key"` + a profile (loaded via `--rule-pack` pointing at a synthetic pack OR via `--profile` naming an unloaded rule) producing the engine-emit `unloaded_rule` for `"nonexistent-engine-rule"`.
- Two assertion shapes per direction (positive + negative):
  1. CLI-emit positive: at least one warning with `category="severities_unloaded_rule"` AND `rule_id=="nonexistent-cli-key"`.
  2. CLI-emit negative: ZERO warnings with `category="unloaded_rule"` AND `rule_id=="nonexistent-cli-key"` (the severities-table key MUST NOT surface under the engine category).
  3. Engine-emit positive: at least one warning with `category="unloaded_rule"` AND `rule_id=="nonexistent-engine-rule"`.
  4. Engine-emit negative: ZERO warnings with `category="severities_unloaded_rule"` AND `rule_id=="nonexistent-engine-rule"` (the profile-named key MUST NOT surface under the CLI category).
- The negative assertions specifically address the document-review ADV-6 concern about the silent-test-confidence pattern (test passing for the wrong reason if both emit paths fired for the same rule_id).

**Execution note:** Consider writing the negative assertions FIRST. If the negative cases happen to pass against the current code (e.g., the engine-emit site somehow never fires for the severities-table key), that reveals the test fixture isn't actually exercising both paths — re-design before adding the positive assertions.

**Patterns to follow:**
- Test module shape and fixture pattern at `tests/schema/lint/cli/test_r9a_severities_overlay.py` (the closest sibling — same `[tool.protokit.lint.severities]` fixture + `--format=json` consumption + `runtime_warnings` list inspection).
- The `runtime_warnings_from_json` and `first_warning_by_category` helpers at `tests/schema/lint/cli/_helpers.py:39-59` (use them; do not re-implement JSON parsing).
- Source-discrimination assertion shape per `[[silent-test-confidence-...-2026-05-17]]` (the document-review ADV-6 finding's referenced learning family — negative assertion on the OTHER branch is the structural pin).

**Test scenarios:**
- *Happy path (CLI branch):* fixture with `[tool.protokit.lint.severities] "nonexistent-cli-key" = "warning"` → assertion: warning with `category="severities_unloaded_rule"` AND `rule_id=="nonexistent-cli-key"` exists.
- *Happy path (engine branch):* fixture with `--profile` referencing an unloaded rule_id `"nonexistent-engine-rule"` → assertion: warning with `category="unloaded_rule"` AND `rule_id=="nonexistent-engine-rule"` exists.
- *Negative (CLI-key not on engine):* assertion: ZERO warnings match `category="unloaded_rule"` AND `rule_id=="nonexistent-cli-key"`.
- *Negative (engine-key not on CLI):* assertion: ZERO warnings match `category="severities_unloaded_rule"` AND `rule_id=="nonexistent-engine-rule"`.
- *Combined fixture:* single invocation surfacing BOTH branches simultaneously — assertion: `runtime_warnings` list contains BOTH expected warnings (positive cases above) AND neither negative case fires.

**Verification:**
- New test module file exists and is discovered by pytest.
- All 5 test scenarios pass.
- Module produces ZERO new test failures elsewhere (doesn't share state with R9a tests).

---

- [ ] **Unit 5: Documentation surface updates (README + CHANGELOG-DRAFT + TODOS)**

**Goal:** Update the 3 documentation surfaces affected by U5's wire-format change — README's 4 schema_version-related sites (including the category enumeration extending to 5 values), CHANGELOG-DRAFT.md's new U5 staging section + U7 eventual-scope append, and TODOS.md's U9 KTD-2 backlog retirement.

**Requirements:** R9-README, R9-changelog-draft, R9-TODOS.

**Dependencies:** Unit 2 (the schema_version constant must be `"0.3"` to match README's references).

**Files:**
- Modify: `README.md` (6 sites):
  - `:592` (Per-rule severity overrides bullet body) — `"Unknown rule_ids fire an `unloaded_rule` runtime warning naming each id (typo surfacing without blocking)."` → `"Unknown rule_ids fire a `severities_unloaded_rule` runtime warning naming each id (typo surfacing without blocking)."` The bullet is specifically about the `[tool.protokit.lint.severities]` case, which is exactly the emit-site U5 renames; keeping `unloaded_rule` here would tell consumers to switch on the wrong category.
  - `:623` (pyproject keys table row for `[tool.protokit.lint.severities]`) — `"Unknown rule_ids fire an `unloaded_rule` runtime warning (typo surfacing without blocking the run)."` → `"Unknown rule_ids fire a `severities_unloaded_rule` runtime warning (typo surfacing without blocking the run)."` Same prose pattern as `:592`; same renaming for the same reason.
  - `:663` (JSON output shape table) — `"currently \"0.2\""` → `"currently \"0.3\""`. The "Absence of the key... implicit `\"0.1\"`" clause stays unchanged.
  - `:666` (JSON `runtime_warnings` per-warning shape) — TWO coupled edits in this cell:
    1. Extend `category` enumeration from 4 values to 5 by inserting `"severities_unloaded_rule"` between `"unloaded_rule"` and `"min_severity_relaxed"`. Keep inline rendering (still ~95 chars; passes readability threshold).
    2. Rewrite the `rule_id (string for engine-emitted categories, `null` for CLI-emitted categories)` clause — the engine-vs-CLI null contract is FALSE after U5 because `severities_unloaded_rule` is CLI-emitted but populates `rule_id`. Replace with `rule_id (populated for rule-scoped categories — `rule_exception`, `unloaded_rule`, `severities_unloaded_rule` — and `null` for non-rule-scoped categories — `min_severity_relaxed`, `all_files_excluded`)`. This mirrors the per-category contract rewrite Unit 2 applies to `_builtin_lint.py:265-271`.
  - `:760` (Public Surface DRAFT row for `lint_json["schema_version"]`) — `"0.2"` → `"0.3"`.
  - `:763` (Public Surface DRAFT row for `runs[].properties.lint_schema_version`) — `"0.2"` → `"0.3"`.
- Modify: `CHANGELOG-DRAFT.md`:
  - Insert new `## D6b U5 (unreleased, wire-format additive)` section between the existing `## D6b U4b (unreleased, dormancy-window note)` and `## D6b U7 — eventual CHANGELOG content scope (suggested)` sections. The U5 staging section enumerates: (a) `_LINT_JSON_SCHEMA_VERSION` 0.2 → 0.3 bump scope (R9's Literal value ONLY); (b) new `"severities_unloaded_rule"` Literal value + emit-site contract (CLI-synthesized only; engine-emitted `"unloaded_rule"` retained); (c) consumer-migration note for code switching on `category == "unloaded_rule"` from the CLI emit site (the value MIGRATED — it did not vanish, did not become unknown; consumers must audit their `category == "unloaded_rule"` paths, not just add a `severities_unloaded_rule` branch); (d) pointer to the refined bump-contract docstring at `_builtin_lint.py:243-260`.
  - Append to existing `## D6b U7 — eventual CHANGELOG content scope (suggested)` list: (1) schema_version 0.2 → 0.3 bump (R9 Literal widening only); (2) new `"severities_unloaded_rule"` `LintRuntimeWarning.category` value (CLI-synthesized; closes D6a U9 KTD-2); (3) bump-contract docstring refinement (closed Literal vs open ladder distinction); (4) consumer-migration note for the category-value migration.
- Modify: `TODOS.md:165-176` (D6b backlog `severities_unloaded_rule` category split bullet) — replace bullet body with one-line "Shipped in D6b 0.3.0 (U5) — see `docs/brainstorms/2026-05-17-d6b-u5-r9-severities-category-split-requirements.md` + `docs/plans/2026-05-17-003-feat-d6b-u5-r9-severities-category-split-plan.md`." Keep the bullet's structural slot (don't delete the line); the retired content is the bullet's body, not its presence.

**Approach:**
- README updates are mechanical 4-site grep-and-replace + the category enumeration extension (5 values inline).
- CHANGELOG-DRAFT U5 staging section follows the D6b U4b dormancy-window note structure — same heading shape, same audit-trail framing, scoped to the wire-format additive change.
- CHANGELOG-DRAFT U7-list append is the safety net per established D6b precedent; minor overreach into U7's authorship territory is the accepted tradeoff for delivery-boundary safety.
- TODOS.md slot-preservation: the bullet's anchor stays at the same line in the surrounding D6b backlog list; replacement is the bullet body only.

**Patterns to follow:**
- `CHANGELOG-DRAFT.md`'s existing `## D6b U4b (unreleased, dormancy-window note)` section — same heading shape, same "(unreleased, ...)" qualifier convention, same audit-trail framing.
- README's existing wire-format reference convention (`"currently \"X.Y\""` for the JSON output shape table cell; bare `"X.Y"` literals for the Public Surface DRAFT table rows).
- TODOS.md retirement pattern per the D6b backlog section's existing structure (the bullet stays; the body shifts to "Shipped in ..." form).

**Test scenarios:**
- Test expectation: none — pure documentation changes. Verification is by reviewer reading + grep.
- *Verification grep (README):* `grep -n "schema_version.*0\\.2\\|lint_schema_version.*0\\.2" README.md` returns zero matches after the bump. (Tightened from the brainstorm's broader `grep "0\\.2" README.md` per document-review SCOPE-4 finding to avoid false positives on unrelated `0.2` mentions.)
- *Verification grep (README category):* `grep -n "severities_unloaded_rule" README.md` returns at least one match (the `:666` cell extension).
- *Verification (CHANGELOG-DRAFT):* file contains the new `## D6b U5 (unreleased, wire-format additive)` section heading.
- *Verification (CHANGELOG-DRAFT):* `## D6b U7 — eventual CHANGELOG content scope (suggested)` section contains the 4 appended items.
- *Verification (TODOS):* the U9 KTD-2 bullet still exists at its line slot but reads as "Shipped in D6b 0.3.0 (U5)".

**Verification:**
- 4 README sites updated; category enumeration shows 5 values.
- CHANGELOG-DRAFT.md has new U5 section + U7-list append.
- TODOS.md U9 KTD-2 bullet retired in place.
- No unrelated content drift in any of the 3 files (review the diff for inadvertent edits).

---

- [ ] **Unit 6: Ancillary docstring refresh (narrative 4-category enumerations)**

**Goal:** Refresh the 2 ancillary docstrings that enumerate the 4-category Literal in narrative form so they stay consistent with the 5-category Literal after Unit 1's widening. Scope is narrow — only sites where the enumeration is explicit and would become stale narrative.

**Requirements:** Carried-forward Engineering Invariant #1 ancillary-docstring scope decision.

**Dependencies:** Unit 1 (Literal widening must land first to anchor the new narrative).

**Files:**
- Modify: `src/protokit/schema/lint/_cli_utils.py:56,61` (the `_LINT_ERROR_CODES` module docstring's "runtime-warning stderr family (4 categories)" → "(5 categories)" at `:56`; the inline enumeration "(`rule_exception`, `unloaded_rule`, `min_severity_relaxed`, `all_files_excluded`)" → insert `severities_unloaded_rule` to make 5 values at `:61`)
- Modify: `src/protokit/formatters/_builtin_lint.py:410-411` (the `_build_lint_testsuite` inline comment enumerating "every `LintRuntimeWarning` category (`rule_exception`, `unloaded_rule`, `min_severity_relaxed`, `all_files_excluded`, plus any future category)" → insert `severities_unloaded_rule` so the explicit list has 5 entries before the "plus any future category" note. The "plus any future category" framing already future-proofs the prose; only the explicit list needs the 5th value.)
- Modify: `src/protokit/formatters/_builtin_lint.py:631` (SARIF properties illustration block; comment line `"category": "<one of the four categories>"` → `"category": "<one of the five categories>"`. Single-token narrative count update; the surrounding illustration block remains structurally unchanged.)

**Approach:**
- Plan-stage verification used two grep patterns (literal 4-tuple enumeration + narrative "four categories" / "<one of the four" prose); document-review surfaced 3 additional sites that the original literal-only grep missed (model.py:543-549, test_model_dataclass_changes.py:14+139, _builtin_lint.py:631). Those are now distributed across Units 1, 2, 5, and this unit per locality.
- Remaining "stays unchanged" verifications:
  - `cli.py:39-40` enumerates engine-emitted categories (`rule_exception`, `unloaded_rule`); the enumeration is engine-only by intent. STAYS UNCHANGED. (The surrounding docstring's general narration about runtime warnings at `cli.py:30-32` and `:44-45` doesn't enumerate categories by name and also stays unchanged — narrative scope precision per the document-review ADV-5 finding.)
  - `engine.py:300-315` narrates the "Compute unloaded-rule diff" step (engine-emit path only). STAYS UNCHANGED.
  - `engine.py:706` references `rule_exception` only. STAYS UNCHANGED.
  - `_builtin_lint.py:265-271` (`runtime_warnings` lint_json docstring) — handled by Unit 2's rewrite, not this unit.
- This unit's edits are 1-2 line changes per site; total diff size <8 lines for this unit (the cross-unit expansion adds ~5 additional lines across Units 1, 2, and 5).

**Patterns to follow:**
- Stale-text accumulation prevention per `[[stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12]]` — narrative enumerations of closed Literals should track the Literal's current shape; the "plus any future category" qualifier in `_builtin_lint.py:411` is a deliberate future-proofing pattern but doesn't substitute for keeping the explicit list current.

**Test scenarios:**
- Test expectation: none — pure docstring/comment changes with no behavior impact. Verification is by reviewer reading + grep.
- *Verification grep (literal enum sites):* `grep -n "\"rule_exception\".*\"unloaded_rule\".*\"min_severity_relaxed\".*\"all_files_excluded\"" src/` returns zero matches after the edits (no 4-tuple enumeration remains in source).
- *Verification grep (narrative-count sites):* `grep -rn "four categories\|four-category\|<one of the four" src/ tests/` returns zero matches after the edits (catches prose narrative the literal-enum grep would miss; this is the broader pattern that the planning-time grep originally under-covered).
- *Verification grep (renamed-emit-site prose in README):* `grep -n "unloaded_rule.*severities\|severities.*unloaded_rule.*runtime warning" README.md` returns matches that reference the new `severities_unloaded_rule` category (not the old `unloaded_rule`) at the renamed emit-site descriptions (`:592` + `:623`).
- *Verification grep (new value seeded across source + tests):* `grep -rn "severities_unloaded_rule" src/ tests/` returns at least 8 matches across model.py, cli.py, _builtin_lint.py, _cli_utils.py, _helpers.py, test_model.py, test_model_dataclass_changes.py, and test_severities_unloaded_rule_category.py.

**Verification:**
- Both ancillary sites refreshed.
- No stale 4-category narrative enumerations remain in `src/`.
- Other ancillary sites verified clean at planning time (no additional touch points discovered).

## System-Wide Impact

- **Interaction graph:** U5 touches the wire-format produced by `lint_json` + `lint_sarif` (consumed by CI parsers, agent tooling, IDE integrations) + the `LintRuntimeWarning` dataclass (constructed at 2 emit sites: engine + CLI). No new callbacks, middleware, or observers introduced.
- **Error propagation:** unchanged. `LintRuntimeWarning` continues to propagate via `LintReport.runtime_warnings` → formatter render. No new exception paths.
- **State lifecycle risks:** none. U5 adds a new Literal value and bumps a version constant; no persistent state, no migration, no cache invalidation.
- **API surface parity:** `lint_json` top-level `schema_version` + `lint_sarif` `runs[].properties.lint_schema_version` continue to emit the SAME string value per cross-format-enum-string-parity discipline. `lint_human` + `lint_junit` deliberately don't carry the field; unchanged.
- **Integration coverage:** the source-discrimination contract (engine-emit vs CLI-emit) is exercised by Unit 4's new test module across both branches simultaneously — the contract is structurally pinned, not just behaviorally observed.
- **Unchanged invariants:**
  - **Engine-emit `unloaded_rule` BEHAVIOR unchanged.** `tests/schema/lint/test_engine.py:282,977` + `tests/schema/lint/test_engine_warning_content_safety.py:361-468` all continue asserting `category == "unloaded_rule"` for the engine-emit path.
  - **`lint_human` + `lint_junit` formatters unchanged by the bump** (no `schema_version` in their output before or after U5).
  - **`_safe_for_stderr(rid)` sanitization** at the CLI emit site applies verbatim to the renamed category (per-rule_id, not per-category).
  - **Forward-compatibility contract** for unknown values remains — the schema_version bump signals "switch tables need re-checking", not "consumer parsing should break".
  - **Field-absence semantic** (implicit `"0.1"` for pre-introduction output) unchanged — floor stays at 0.1 forever regardless of bumps.
  - **Engine-emit-site category enumerations** in `cli.py:35-45` + `engine.py:305-315` + `engine.py:706` stay as 2-value (engine emits only `rule_exception` + `unloaded_rule`; U5 adds a CLI category, not an engine one).

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Consumers switching on `category == "unloaded_rule"` expecting the CLI emit site silently break after upgrade. | Forward-compatibility addresses NEW values, NOT value migration. The schema_version 0.2 → 0.3 bump IS the documented signal that switch tables need re-checking; the CHANGELOG-DRAFT U5 staging entry explicitly calls out the value-migration (not just the value-addition) so consumers audit their `category == "unloaded_rule"` paths. |
| The bump-contract docstring refinement is rejected at ce:review for being too long / too prescriptive. | KTD-5 marks the refinement REQUIRED in the parent plan. Length is justified by the distinction's load-bearing role — without it, the docstring directly contradicts the U5 bump action. The refined wording is the contract for any future closed-Literal addition. |
| The 4-value count-pin at `test_model_dataclass_changes.py:54` HARD FAILS the moment the Literal widens. Forgetting Unit 1's lockstep update produces a structural CI red. | R9-tests-coupled enumerates this explicitly; Unit 1's file list includes the count-pin update. The drift-detection cross-check at `:72` is a separate guard that fails if the helper tuple isn't extended in lockstep. Both fail loudly, not silently. |
| The `runtime_warnings` docstring rewrite at `_builtin_lint.py:265-271` is forgotten and becomes stale. | Promoted from "deferred to plan" to mandatory R9-docstring deliverable in Unit 2 per document-review FEAS-3 auto-fix. The file is being edited anyway for the constant bump; the docstring rewrite ships in the same commit. |
| The 6-unit structure suggests multiple commits to an implementer; they may split the work and produce intermediate inconsistent states. | Plan-level Key Technical Decisions explicitly call out: "One feat commit, six implementation units — units exist for sequencing clarity but bundle into a single feat(lint) commit." Mirrors established D6b U3a / U4a / U4b shape. |
| Reviewer-cited test files at U5 ce:review pass surface additional drift-detection sites that weren't enumerated at planning time. | Document-review pass already surfaced 4 lockstep sites (model count-pin, parametrize, helper tuple, factory). Plan-time codebase grep verified no additional `len(literal_args)` or `LINT_RUNTIME_WARNING_CATEGORIES` references exist outside these 4. If U5 ce:review finds a 5th, it's a safe_auto follow-up. |
| The README JSON-shape table cell crosses readability threshold with 5 inlined values. | Plan-time inspection: 4-value cell currently ~75 chars; 5-value cell becomes ~95 chars. Still within the doc's standing table-width pattern (other rows in the same table run 100+ chars). If reviewer rejects, fallback is a bullet-list rewrite, scoped within U5. |
| A future contributor adds a 6th closed-Literal value WITHOUT bumping schema_version, assuming the U5 bump "covered the category Literal forever". | The refined bump-contract docstring is the contract — future contributors reading it before adding a 6th value see the bump trigger explicitly. U7's CHANGELOG presence-ratchet pins the refined wording so it can't silently revert. R9-tests-coupled's count-pin at `test_model_dataclass_changes.py:54` fires immediately on any addition that misses the lockstep updates. |
| Ancillary docstring refresh in Unit 6 misses a site that the planning-time grep didn't surface. | Planning-time grep enumerated exactly 2 sites with explicit 4-value narrative enumerations (`_cli_utils.py:56,61` + `_builtin_lint.py:410-411`). Other narrative sites (`cli.py:35-45`, `engine.py:305-315`, `engine.py:706`) verified clean — they enumerate engine-emit-only categories, which U5 doesn't change. If U5 ce:review surfaces an additional site, it's a safe_auto follow-up. |

## Documentation / Operational Notes

- **CHANGELOG-DRAFT.md** lands new content but published `CHANGELOG.md` does NOT change in U5. The fold happens at U7's delivery-boundary commit per `[[delivery-boundary-unit-commit-composition]]`.
- **`pyproject.toml`** package version stays at 0.2.x during the U5 → U7 window — the schema_version bump (0.2 → 0.3) and the package version bump (0.2.0 → 0.3.0) are decoupled signals. The schema_version bump IS the wire-format-change signal; the package version bump waits for U7's delivery boundary. Consumers reading package version as a stability proxy may briefly see 0.2.x with schema_version 0.3 — this is acceptable pre-1.0 since no release happens between U5 and U7 (only main moves). The brainstorm's R9-changelog-draft U5 staging entry communicates this explicitly.
- **No runbook, monitoring, or feature-flag changes.** U5 is a wire-format additive change with no operational rollout shape.
- **README diff** is limited to 4 sites; the broader Schema Linting section refresh (R7 BUILTIN_PACKS registration, rule_id enumeration, `--rule-pack` doc-section relocation) stays scoped to U7.
- **Post-U5 follow-ups (separate commits):**
  - `fix(lint): D6b U5 ce:review follow-ups — N safe_auto + N gated_auto + N manual` per established D6b pattern.
  - `docs(solutions): D6b U5 ce:compound — N new learnings + N reciprocal cross-refs` capturing closed-Literal-bump-trigger ratchet learning + the `semantic-category-conflation-accepted-tradeoff-literal-widening` resolution annotation.

## Sources & References

- **Origin document:** [docs/brainstorms/2026-05-17-d6b-u5-r9-severities-category-split-requirements.md](../brainstorms/2026-05-17-d6b-u5-r9-severities-category-split-requirements.md).
- **Parent brainstorm:** `docs/brainstorms/2026-05-14-protokit-lint-delivery-6b-option-aware-and-multi-language-requirements.md:109` (R9 requirement) + `:118` (R9-bump scope clarification) + `:222` (Unit 5 framing).
- **Parent plan (predecessor U5 section):** `docs/plans/2026-05-14-001-feat-protokit-lint-d6b-option-aware-and-multi-language-plan.md:485-540` (Unit 5 enumeration) + `:116` (KTD-5 bump-contract docstring refinement) + `:235` (KTD-5 refined wording template) + `:666,671` (Risks table entries). This per-unit plan supersedes the parent plan's U5 section for execution; cited above for full lineage.
- **Predecessor source artifact:** D6a U9 KTD-2 commits `c7a426b` (R9d schema_version constant introduction) + `3c828a4` (R9 ce:review follow-ups including the field-absence-semantic docstring clause that this U5 refines).
- **D6a U9 ce:review F5 finding** (cli-readiness reviewer, 2026-05-13) — recommended the dedicated category split land in D6b. Captured in `docs/solutions/best-practices/semantic-category-conflation-accepted-tradeoff-literal-widening-2026-05-13.md`.
- **Related institutional learnings:**
  - `docs/solutions/best-practices/semantic-category-conflation-accepted-tradeoff-literal-widening-2026-05-13.md` (the conflation U5 resolves; ce:compound pass annotates with resolution status).
  - `docs/solutions/best-practices/wire-format-schema-version-bump-contract-and-absence-semantic-2026-05-13.md` (the bump contract U5 extends; ce:compound pass adds R9 as the first closed-Literal worked example).
  - `docs/solutions/best-practices/pre-1.0-version-bump-as-communication-contract-2026-05-14.md` (pre-1.0 bump signaling discipline).
  - `docs/solutions/best-practices/delivery-boundary-unit-commit-composition-2026-05-14.md` (U7's role as the published-CHANGELOG fold boundary).
  - `docs/solutions/best-practices/dormant-code-changelog-draft-staging-delivery-boundary-2026-05-17.md` (the established D6b dormancy-window pattern; U5 follows the same shape).
  - `docs/solutions/best-practices/public-surface-draft-discipline-source-audit-2026-05-12.md` (Public Surface DRAFT table refresh discipline).
  - `docs/solutions/best-practices/stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12.md` (Unit 6 ancillary-docstring scope justification).
  - `docs/solutions/best-practices/parametrized-matrix-tests-inherit-schema-validators-2026-05-12.md` (cross-formatter matrix auto-extends when `LINT_RUNTIME_WARNING_CATEGORIES` + factory grow).
- **External references:** none used. U5 is closing a known internal trip-wire with fully verified codebase surfaces.
