# protokit-lint D6b U5 — R9 `severities_unloaded_rule` category split + `schema_version` bump 0.2 → 0.3

**Status:** brainstorm (requirements). Next step: `/ce:plan`.
**Date:** 2026-05-17.
**Scope:** per-unit. Smallest unit in D6b; independent of R6 (U2/U3) and R7 (U4a/U4b) — no dependencies on prior D6b units beyond the already-shipped 0.2.0 baseline.
**Parent brainstorm:** `docs/brainstorms/2026-05-14-protokit-lint-delivery-6b-option-aware-and-multi-language-requirements.md` (R9 section + R9-bump scope-clarification language).
**Parent plan:** `docs/plans/2026-05-14-001-feat-protokit-lint-d6b-option-aware-and-multi-language-plan.md:485-540` (Unit 5 section + KTD-5 bump-contract docstring refinement).
**Predecessor source artifact:** D6a U9 KTD-2 — the accepted-tradeoff conflation captured in `docs/solutions/best-practices/semantic-category-conflation-accepted-tradeoff-literal-widening-2026-05-13.md`. U5 resolves the deferred design in the same 3-site discipline (in reverse).
**Predecessors shipped:** U1 (`include_source_info` parameter), U2 (`source_info_descriptors` field + `leading_comment` helper), U3 (R6 5-rule deprecated-replacement family + CLI source-info wire-up), U4a (R7 engine plumbing), U4b (R7 PACKAGE_SAME_* family — 7 dormant rules). Suite at 1864 passing + 7 skipped at HEAD (`8c73f00`).

## TL;DR

U5 closes the **D6a U9 KTD-2 deferred-design trip-wire** with a surgical wire-format-additive change. Three coupled edits:

1. **Widen `LintRuntimeWarning.category: Literal[...]`** from 4 to 5 values by adding `"severities_unloaded_rule"`. Switch the CLI-synthesized emit site at `src/protokit/schema/lint/cli.py:1086-1100` from `category="unloaded_rule"` to `category="severities_unloaded_rule"`. The engine-emitted `"unloaded_rule"` at `src/protokit/schema/lint/engine.py:387` remains unchanged. Consumers gain a programmatic discriminator and no longer need to match message substrings to tell the two emit sites apart.

2. **Bump `_LINT_JSON_SCHEMA_VERSION = "0.2"` → `"0.3"`** at `src/protokit/formatters/_builtin_lint.py:250`. Single-constant edit cascades to both consumption sites (`lint_json:329` top-level `schema_version` + `lint_sarif:673` `runs[0].properties.lint_schema_version`) per the cross-format-enum-string-parity discipline. `lint_human` and `lint_junit` unchanged (deliberately don't carry the field).

3. **Refine the bump-contract docstring** at `src/protokit/formatters/_builtin_lint.py:243-249` to distinguish **closed Literal discriminators** (bump trigger — consumers exhaustively switch on the value) from **open severity-string ladders** (NOT a bump trigger — consumers tolerate new values). The current docstring's blanket "enum-value additions don't bump" language would contradict the bump action; refinement is REQUIRED, not optional.

**Bump scope clarification (load-bearing):** The 0.2 → 0.3 bump is scoped to R9's new Literal value ONLY. New `rule_id` strings landing in `LintFinding` output from R6 (already shipped U3) and R7 (already shipped U4b, dormant until U7's `BUILTIN_PACKS` registration) do NOT trigger additional bumps — `findings` is an additive list and consumers already tolerate unknown `rule_id` values. This distinction is what KTD-5's refined docstring formalizes.

**3-site discipline (applied in reverse):** The original accepted-tradeoff doc named THREE sites where the conflation was documented (Literal docstring + CLI emit-site comment + TODOS.md backlog entry). U5 updates each in reverse: the Literal docstring now enumerates 5 values (with the per-emit-site contract refined), the CLI emit-site comment now points back at the resolution-in-place, and the TODOS.md entry retires to "Shipped in D6b 0.3.0" status.

Three deliverables:

1. **Literal widening + CLI emit-site switch** (`src/protokit/schema/lint/model.py:500-505` + `src/protokit/schema/lint/cli.py:1086-1100`). One new Literal value + one `category=` argument swap + docstring updates at both sites.

2. **Schema-version constant bump + bump-contract docstring refinement** (`src/protokit/formatters/_builtin_lint.py:243-250`). One-character constant edit + multi-line docstring rewrite distinguishing closed Literals from open ladders.

3. **README wire-format references + DRAFT-table rows** (`README.md:663, 666, 760, 763`). Update the four sites where the schema version literal `"0.2"` appears, plus the JSON shape's `category` value enumeration (4 → 5 values). Stays in U5 (locality with the constant edit); U7's README refresh handles broader Schema Linting section work for R7 BUILTIN_PACKS registration.

Explicit non-goals (deferred):

- **R9b per-rule disable/enable lists** (`disabled_rules` / `enabled_rules`). Different design space — needs real-demand evidence to design against 4 collision-shape precedence semantics. Asymmetry note vs U5/R9: R9 ships in D6b despite identical "no real-demand evidence" status because R9 is wire-format-additive closing a known trip-wire, not new design space. R9b stays deferred to post-D6b.
- **Presence-ratchet test pinning the refined bump-contract docstring wording.** Per parent plan's Risks table (line 666), U7's CHANGELOG presence-ratchet pins this. U5 lands the refined wording; U7 pins it.
- **CHANGELOG-DRAFT.md staging entry collapse.** U5 adds its dormancy-window-style staging entry to `CHANGELOG-DRAFT.md`; U7 owns the final fold into `CHANGELOG.md` at the 0.3.0 delivery-boundary commit.
- **Updating `docs/solutions/` cross-references** (e.g., `semantic-category-conflation-accepted-tradeoff-literal-widening` to note the split landed). That work belongs to U5's ce:compound pass, not the feat commit.

## Problem Frame

D6a U9 R9a wired per-rule severity overrides from `[tool.protokit.lint.severities]` into the CLI's composed profile. Keys naming a rule not in the composed profile needed to surface as a `LintRuntimeWarning`. The natural emit site is the CLI itself.

Rather than widen the `LintRuntimeWarning.category` Literal at the moment of introduction (a wire-format change for a brand-new emit site whose user-feedback signal was unproven), U9 KTD-2 accepted the conflation: reuse the existing `"unloaded_rule"` category value and let consumers distinguish the two emit sites via message substring (`"in profile"` vs `"[tool.protokit.lint.severities]"`). The U9 ce:review F5 finding (cli-readiness reviewer, 2026-05-13) recommended the dedicated category split (`"severities_unloaded_rule"`) be revisited in D6b.

**The cost of leaving the conflation in place compounds.** Programmatic consumers — CI parsers, agent tooling, IDE integrations — must switch on stable message substrings rather than the obvious `category` discriminator. Each new consumer absorbs the substring-matching cost. Each documentation update must explain the conflation. The 3-site discipline used to document the conflation is itself maintenance overhead.

D6b is the next minor bump window. The Literal widening is strictly additive (no existing engine-emit-site consumer breaks). The schema_version bump is the documented wire-format signal that consumers should re-check their switch statements. U5 is the smallest possible unit that closes the trip-wire cleanly while satisfying the bump-contract.

**No alternative approach scored better:**

- *Defer to D6c / post-1.0.* Rejected — each delivery the conflation persists adds carrying cost (documentation, agent-grep anchors, contributor onboarding). The bump-trigger framing makes D6b the right slot.
- *Widen the Literal without bumping schema_version.* Rejected — contradicts the bump contract per KTD-5's refined docstring (closed-discriminator additions DO bump). Skipping the bump would silently break consumer routing logic that uses schema_version to decide whether to re-check switch statements.
- *Bundle R9b (per-rule disable/enable) into U5.* Rejected — R9b is a 4-precedence-shape design space, not a wire-format-additive change. No real-demand evidence yet exists. Bundling would conflate two unrelated decisions.

## Requirements

### R9 — `severities_unloaded_rule` category split

Add `"severities_unloaded_rule"` as the 5th value of `LintRuntimeWarning.category: Literal[...]` at `src/protokit/schema/lint/model.py:500-505`. Existing 4 values (`"rule_exception"`, `"unloaded_rule"`, `"min_severity_relaxed"`, `"all_files_excluded"`) remain unchanged. Update the dataclass-level docstring at `src/protokit/schema/lint/model.py:351-497` to:

- Enumerate 5 values (instead of 4) in the "Four structurally distinct events" preamble (renumber to "Five").
- Split the current numbered item 2 (`"unloaded_rule"`) into two sibling items:
  - **2. `"unloaded_rule"`** (engine-emitted only) — the active profile's `rule_ids` referenced a rule_id not loaded into the engine. Set difference computed at `LintEngine.run` start. Message: `rule {rid} is named in profile {name} but not loaded into the engine`.
  - **3. `"severities_unloaded_rule"`** (CLI-synthesized only) — a key in `[tool.protokit.lint.severities]` is not in the composed profile's `rule_ids`, so the severity override has no effect. Message: `rule {rid} is named in [tool.protokit.lint.severities] but is not in the composed profile — the severity override has no effect`.
- Renumber existing items 3 (`"min_severity_relaxed"`) and 4 (`"all_files_excluded"`) to 4 and 5.
- Remove the prior "Distinguish via message content" subsection (the prior agent-grep anchor for the conflation) — replaced by per-category contracts.
- Add a one-paragraph note explaining the U5 split: `"severities_unloaded_rule"` closes the D6a U9 KTD-2 accepted tradeoff; consumers may now switch on `category` instead of message substring.

Switch the CLI-synthesized emit site at `src/protokit/schema/lint/cli.py:1086-1100` from `category="unloaded_rule"` to `category="severities_unloaded_rule"`. Update the surrounding inline comment block (currently lines 1076-1082) to:

- Remove the "Reuses the existing `unloaded_rule` category rather than introducing a new `severities_unloaded_rule` value... avoids a wire-format change in D6a" rationale.
- Replace with a one-paragraph audit-trail note: the dedicated category landed in D6b U5; semantic provenance lives in the `LintRuntimeWarning.category` docstring; the schema_version 0.2 → 0.3 bump is the consumer-facing wire-format signal.

The engine-emitted `category="unloaded_rule"` at `src/protokit/schema/lint/engine.py:387` remains unchanged. No behavior change for that emit site.

### R9-bump — `_LINT_JSON_SCHEMA_VERSION` 0.2 → 0.3 bump

Edit `_LINT_JSON_SCHEMA_VERSION = "0.2"` to `_LINT_JSON_SCHEMA_VERSION = "0.3"` at `src/protokit/formatters/_builtin_lint.py:250`. The constant cascades to both consumption sites (`lint_json:329` top-level `"schema_version"` + `lint_sarif:673` `runs[0].properties.lint_schema_version`) via the existing single-source-of-truth pattern. No `lint_human` or `lint_junit` changes (they deliberately don't carry the field).

**Bump scope (load-bearing for ce:plan + ce:review):** The 0.2 → 0.3 bump is justified by R9's `category` Literal widening ONLY. New `rule_id` strings landing in `LintFinding` output from R6 (U3, shipped) and R7 (U4b, shipped dormant) do NOT trigger additional bumps. `findings` is an additive list; consumers already tolerate unknown `rule_id` values. The CHANGELOG D6b section (composed at U7) enumerates this distinction explicitly per parent brainstorm.

### R9-docstring — Bump-contract docstring refinement (KTD-5)

Refine the docstring at `src/protokit/formatters/_builtin_lint.py:243-249` to distinguish closed-discriminator additions (bump trigger) from open-ladder additions (not a bump trigger).

Current wording (after the (a)/(b)/(c) trigger list):

> Adding new severity-level / category strings to an existing enum field does NOT bump the version (the field's meaning is unchanged; the enum just gains a value).

Refined wording (replaces the single sentence):

> **Bump-trigger refinement (closed Literals vs open ladders):**
>
> - **Open severity-string ladders** — for fields like `severity` (`"error"` / `"warning"` / `"info"`) where consumers tolerate unknown values gracefully (treat unknown as "more severe than I knew about" or "less severe than I knew about" depending on rendering context), additions DO NOT bump the version.
>
> - **Closed Literal discriminators** — for fields like `LintRuntimeWarning.category` (`"rule_exception"` / `"unloaded_rule"` / ...) where consumers exhaustively switch on the value (each case handled with different logic; unknown value would fall through to a default branch the consumer didn't expect), additions DO bump the version. Every consumer must extend their switch / match construct to handle the new case.
>
> The discriminating question: can a consumer that doesn't know about the new value still produce a correct result? Open ladders: yes (the field's role is to be rendered or compared, not switched on). Closed discriminators: no (the field's role is to route logic).

This refinement is REQUIRED — without it the docstring directly contradicts the U5 bump action (the current blanket "enum-value additions don't bump" sentence would make the 0.2 → 0.3 bump look like an over-bump). The refined wording becomes the load-bearing contract for any future closed-Literal addition.

Additionally, the adjacent `runtime_warnings` docstring at `src/protokit/formatters/_builtin_lint.py:265-271` requires a coupled rewrite (`_builtin_lint.py` is already being edited; the docstring becomes factually inaccurate the moment the Literal widens). The current docstring's "rule_id is null for the CLI-emitted categories (`min_severity_relaxed`, `all_files_excluded`)" framing characterizes null-vs-populated by emit-site, but after U5 the CLI emits THREE categories with `severities_unloaded_rule` carrying a populated `rule_id` — breaking the engine-vs-CLI dichotomy. Replace the emit-site framing with a one-line pointer to `LintRuntimeWarning.category`'s per-category contract docstring (which is authoritative). Lands in the same U5 commit as the Literal widening; not deferred.

### R9-README — README wire-format references

Update four sites in `README.md` where the literal `"0.2"` schema version appears or where the 4-value category enumeration is rendered to consumers:

- `README.md:663` (JSON output shape table) — `"currently \"0.2\""` → `"currently \"0.3\""`. The "Absence of the key... implicit `\"0.1\"`" clause stays unchanged (it documents the pre-introduction absence semantic, not the current value).
- `README.md:666` (JSON `runtime_warnings` per-warning shape) — the `category` value enumeration `("\"rule_exception\"" / "\"unloaded_rule\"" / "\"min_severity_relaxed\"" / "\"all_files_excluded\"")` extends to 5 values by inserting `"severities_unloaded_rule"` between `"unloaded_rule"` and `"min_severity_relaxed"`.
- `README.md:760` (Public Surface DRAFT row for `lint_json["schema_version"]`) — `"0.2"` → `"0.3"`.
- `README.md:763` (Public Surface DRAFT row for `runs[].properties.lint_schema_version`) — `"0.2"` → `"0.3"`.

U7's later README refresh boundary handles the broader Schema Linting section work (R7 BUILTIN_PACKS registration, new rule_ids enumerated under `recommended` / `default`, etc.). U5's edits stay scoped to the four sites where R9-bump's value literal already appears.

### R9-changelog-draft — `CHANGELOG-DRAFT.md` staging entry

Add a `## D6b U5 (unreleased, wire-format additive)` section between the existing `## D6b U4b (unreleased, dormancy-window note)` and `## D6b U7 — eventual CHANGELOG content scope (suggested)` sections. The U5 staging entry enumerates:

- The `_LINT_JSON_SCHEMA_VERSION` 0.2 → 0.3 bump scope (R9's Literal value ONLY; new rule_ids do NOT bump).
- The new `"severities_unloaded_rule"` Literal value + its emit-site contract (CLI-synthesized only; engine-emitted `"unloaded_rule"` retained).
- A consumer-migration note for any code currently switching on `category == "unloaded_rule"` expecting the CLI emit site — those consumers now read `category == "severities_unloaded_rule"` from the CLI emit site; the engine-emit site is unchanged.
- A pointer to the refined bump-contract docstring at `_builtin_lint.py:243-249` (closed Literal vs open ladder distinction).

Also append a U5-derived item to the existing `## D6b U7 — eventual CHANGELOG content scope (suggested)` section so U7's CHANGELOG composition does not lose the U5 deltas in the U4b-heavy fold:

- **schema_version 0.2 → 0.3 bump** (driven by R9 Literal widening; rule_id additions do not contribute additional bumps).
- **New `"severities_unloaded_rule"` `LintRuntimeWarning.category` value** (CLI-synthesized; closes D6a U9 KTD-2 accepted tradeoff).
- **Bump-contract docstring refinement** (closed Literal vs open ladder distinction).
- **Consumer-migration note** for the category-switch breakage.

### R9-tests-coupled — Lockstep updates to existing tests + helper that pin the 4-value Literal shape

The Literal widening from 4 → 5 values triggers HARD test failures in two structural-pin sites that the original Output Structure list missed. These are not optional follow-ups; they ship in the same commit as the model edit:

- **`tests/schema/lint/test_model_dataclass_changes.py:54`** — the presence-ratchet `assert len(literal_args) == 4` MUST bump to `== 5`. The test method (`test_literal_lists_all_four_categories`) rename to `test_literal_lists_all_five_categories` for accuracy; the expected-set assertion (currently 4 named values) adds `"severities_unloaded_rule"`. The module docstring's "2 → 4 categories" history note updates to "2 → 4 → 5 categories".
- **`tests/schema/lint/test_model_dataclass_changes.py:144-151`** — the `TestFrozen.test_assignment_raises_for_every_category` parametrize list (currently 4 `(category, rule_id)` tuples) MUST gain a 5th entry: `("severities_unloaded_rule", "rule/id")`. Without this, the frozen-dataclass guarantee is not exercised against the new value.
- **`tests/schema/lint/cli/_helpers.py:31-36`** — the `LINT_RUNTIME_WARNING_CATEGORIES: tuple[str, ...]` tuple (currently 4 values) MUST add `"severities_unloaded_rule"`. The helper's own docstring at `:25-30` explicitly calls U5 out: `"Adding a 5th category is a deliberate D6+ act that requires updating both the model Literal AND this tuple."` The cross-check test at `test_model_dataclass_changes.py:72` (`set(LINT_RUNTIME_WARNING_CATEGORIES) == literal_args`) enforces drift-detection, so missing this edit fails CI immediately.
- **`tests/schema/lint/cli/_helpers.py:62-113`** — the `warning_for_category(category, *, index=0)` factory MUST gain a 5th branch returning `LintRuntimeWarning(category="severities_unloaded_rule", rule_id="rule/id-{index}", message=...)`. The current `raise AssertionError(f"unrecognized category: ...")` fallback would explode any cross-formatter matrix test that iterates `LINT_RUNTIME_WARNING_CATEGORIES` and hits the new value (the factory is the construction-by-category mechanism).

These four edits are co-required with the model.py Literal widening — failing to land them produces a structural CI red, not a behavioral drift. They are listed here (not in Open Questions) because the codebase pattern resolves them mechanically; no plan judgment is required.

### R9-TODOS — `TODOS.md` U9 KTD-2 backlog retirement

Retire the `severities_unloaded_rule` category split bullet at `TODOS.md:165-176`. Replace the bullet content with a one-line "Shipped in D6b 0.3.0 (U5)" note pointing at the U5 brainstorm + plan. Keep the bullet's structural slot (don't delete the line) so cross-references to the bullet's position remain stable; the retired content is the bullet's body, not its presence.

## Non-Goals (deferred)

- **R9b — per-rule disable/enable lists** (`disabled_rules` / `enabled_rules`). Deferred to post-D6b per parent brainstorm. Needs real-demand evidence for the 4 collision-shape precedence semantics design. R9a severity-demote-to-info workaround remains usable.
- **Presence-ratchet test pinning the refined bump-contract docstring wording.** Per parent plan Risks table line 666, U7's CHANGELOG presence-ratchet handles this. U5 lands the refined wording; U7 pins it.
- **Updating `docs/solutions/` cross-references.** `semantic-category-conflation-accepted-tradeoff-literal-widening` and `wire-format-schema-version-bump-contract-and-absence-semantic` both deserve U5-resolution updates; that work belongs to the U5 ce:compound pass, not the feat commit.
- **General "wire-format hygiene" sweep across other potentially-closed Literals.** Out of scope. The bump-contract refinement is what future closed-Literal additions reference; specific value additions wait for their own delivery slots.
- **U7's broader README Schema Linting section refresh** (R7 BUILTIN_PACKS registration, rule_ids enumerated under `recommended`/`default`, `--rule-pack` doc-section relocation, etc.). Owned by U7 per parent plan.
- **U7's CHANGELOG-DRAFT.md fold into `CHANGELOG.md`.** U5 stages content in DRAFT; U7 owns the published CHANGELOG composition at the 0.3.0 delivery-boundary commit.

## Open Questions

### Deferred to Planning

- **Test file layout.** Plan currently names a NEW `tests/schema/lint/cli/test_severities_unloaded_rule_category.py`. But two existing test files already cover adjacent surface area:
  - `tests/schema/lint/cli/test_r9a_severities_overlay.py:104` currently asserts `category == "unloaded_rule"` for the CLI emit site — this assertion MUST change to `"severities_unloaded_rule"` regardless of test-layout choice.
  - `tests/schema/lint/cli/test_r9d_schema_version.py:21` (the `_SCHEMA_VERSION = "0.2"` constant) — MUST update to `"0.3"`.
  - `tests/test_builtin_lint_runtime_warnings.py:344, 374` (SARIF emit-site schema_version assertions) — MUST update to `"0.3"`.

  Two viable layouts: (a) update in-place at each existing file + add ONE new module for source-discrimination (engine-vs-CLI both-branch contract) co-located with R9a tests, OR (b) add a single new `test_severities_unloaded_rule_category.py` module covering source-discrimination + cross-format-parity, and just bump the version literals in the three existing files. Plan owns the choice.

- **Test source-discrimination shape.** The R9 split's load-bearing contract is that the engine-emitted path STILL produces `"unloaded_rule"` while the CLI-emit path produces `"severities_unloaded_rule"`. A single test asserting both branches in the same module (parametrized or sibling tests) makes the contract obvious; two separate modules diffuse it. Plan owns the structure.

- **README JSON-shape table value rendering.** The `runtime_warnings` row currently inlines the 4 category values in markdown table-cell syntax. With 5 values the cell gets longer; if it crosses a readability threshold (~80-100 chars), the plan may choose to bullet-list the values instead of inlining them. Cosmetic; plan owns.

### Resolved Here

- **Should the Literal widening AND the schema_version bump land in the same commit?** YES. They're coupled: the bump is justified ONLY by the closed-Literal-discriminator framing in KTD-5's refined docstring. Splitting them would force a 2-commit micro-sequence where the intermediate state has stale documentation. The plan unit is a single feat commit.
- **Should U5 ship without the bump-contract docstring refinement?** NO. The current docstring's blanket "enum-value additions don't bump" language directly contradicts the U5 bump action. Without the refinement the docstring + the code form an inconsistent contract. KTD-5 marks the refinement REQUIRED.
- **Should the engine-emitted `"unloaded_rule"` migrate too?** NO. The engine-emitted site has a distinct semantic ("rule named in profile but not loaded into engine"). Renaming or splitting it would be a separate trip-wire requiring its own delivery slot. The split is one-directional: the CLI path peels off; the engine path stays.
- **Should `category="unloaded_rule"` be removed from the Literal entirely (deprecated path)?** NO. The engine path actively emits the value; removal would break the engine's emit shape. Both values coexist in the Literal — `"unloaded_rule"` for engine, `"severities_unloaded_rule"` for CLI.
- **Should the wire-format absence semantic ("implicit 0.1") update with the bump?** NO. The absence semantic documents pre-introduction output (output from `protokit < 0.2.0`). Consumers comparing `"0.2" >= "0.1"` and `"0.3" >= "0.1"` both work; the floor stays at 0.1 forever. Renaming or rebumping the absence semantic would create a moving floor that defeats its purpose.
- **Should U5 update the `docs/solutions/` accepted-tradeoff doc to mark resolution?** NOT in the feat commit. U5's ce:compound pass owns docs/solutions/ updates. Likely 1-2 doc updates: the accepted-tradeoff doc gains a "resolution: shipped in D6b U5" annotation, and the wire-format-schema-version-bump-contract doc gains a worked example referencing R9 as the first closed-Literal-discriminator bump.
- **Should U5 add a CHANGELOG-DRAFT entry now, or defer all CHANGELOG work to U7?** ADD NOW. Per the established D6b dormancy-window pattern (U4b already added its dormancy-window note). The DRAFT-vs-published separation per `pre-1.0-version-bump-as-communication-contract` + `delivery-boundary-unit-commit-composition` keeps each unit's public-surface tradeoffs visible to reviewers during the U5 → U7 window. U7's fold collapses the per-unit DRAFT sections into the published CHANGELOG.
- **Should README updates land in U5 or U7?** LAND IN U5. The four affected sites are about the schema_version literal value + the category enumeration — both directly produced by U5's code change. Locality wins. U7's README refresh covers broader Schema Linting section work (R7 BUILTIN_PACKS, rule_id enumeration) — different concerns.
- **Should U5 introduce a new `--rule-pack=...` or other CLI surface?** NO. R9 is wire-format additive, not CLI-surface additive. Zero CLI changes.

## Success Criteria

### User-outcome criteria (these answer "did we deliver value?")

1. **A programmatic consumer can distinguish engine-emitted vs CLI-synthesized "unloaded rule" warnings by switching on `category`** instead of matching message substrings. Verifiable by: running `protokit lint --format json` against a fixture where `[tool.protokit.lint.severities]` names a non-existent rule_id + a profile names a non-loaded rule_id, and asserting the resulting `runtime_warnings` list contains BOTH `category="unloaded_rule"` (engine) AND `category="severities_unloaded_rule"` (CLI) entries.

2. **The `schema_version` value bumps to `"0.3"` in both `lint_json` and `lint_sarif` outputs.** Verifiable by: `protokit lint --format json` and `protokit lint --format sarif` both reading `"0.3"` from their respective version paths.

3. **The bump-contract docstring justifies the 0.2 → 0.3 bump.** Verifiable by: reading `src/protokit/formatters/_builtin_lint.py:243-260` and confirming the closed-Literal-discriminator framing is present and consistent with the Literal widening + version bump.

4. **The CHANGELOG-DRAFT.md U5 staging entry is consumer-actionable.** Verifiable by: a reviewer reading only the staging entry can identify (a) the version bump, (b) the new category value, (c) the consumer-migration path for code currently switching on `category == "unloaded_rule"` from the CLI emit site.

5. **README's wire-format references reflect U5 state.** Verifiable by: `grep "0\.2" README.md` returns no schema_version-related matches (only the implicit-floor "0.1" + unrelated references stay); the JSON output shape's category enumeration lists all 5 values including `"severities_unloaded_rule"`.

### Engineering invariants to preserve (these answer "did we avoid regression?")

1. **Engine-emitted `"unloaded_rule"` BEHAVIOR unchanged.** No new test failures in `tests/schema/lint/test_engine.py:282` (`test_unloaded_rule_warns_once_before_walk`) or `tests/schema/lint/test_engine.py:977` (`test_empty_root_files_with_unloaded_rule_emits_warning`) or `tests/schema/lint/test_engine_warning_content_safety.py:361-468` (3 engine-emit-site safety tests). All continue asserting `category == "unloaded_rule"`. Behavior-only invariant; ancillary docstrings at `engine.py:305, engine.py:706`, `_cli_utils.py:61`, `cli.py:40`, and `_builtin_lint.py:411` that enumerate the 4-category Literal in narrative form may need a coupled refresh to stay consistent with the 5-category Literal — plan owns the scope decision on whether those land in U5 or as a follow-up commit (the stale-text accumulation risk per [[stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12]] argues for in-U5 inclusion).

2. **Existing `LintRuntimeWarning` dataclass-construction tests survive the widening with coupled updates.** `tests/schema/lint/test_model.py:845-879` uses `category="unloaded_rule"` in construction tests — the additive Literal widening doesn't break those (existing assertions stay valid). However, `tests/schema/lint/test_model_dataclass_changes.py:54` contains a presence-ratchet `assert len(literal_args) == 4` that REQUIRES bumping to `== 5` in lockstep with the model change; `tests/schema/lint/test_model_dataclass_changes.py:144-151` parametrizes `TestFrozen.test_assignment_raises_for_every_category` against an exact 4-tuple of `(category, rule_id)` pairs that REQUIRES adding `("severities_unloaded_rule", "rule/id")` as the 5th entry. See R9-tests-coupled for the lockstep file list.

3. **Helper-mirror tuple + factory stay in sync with the model Literal.** `tests/schema/lint/cli/_helpers.py:31-36` exports `LINT_RUNTIME_WARNING_CATEGORIES: tuple[str, ...]` — its own docstring at `:25-30` explicitly names U5 as the act that requires updating both the model Literal AND this tuple. The `warning_for_category` factory at `_helpers.py:62-113` raises `AssertionError(f"unrecognized category: ...")` on any unknown value — extending it with a `severities_unloaded_rule` branch is REQUIRED for the cross-formatter matrix tests at `tests/test_builtin_lint_runtime_warnings.py` (which iterate `LINT_RUNTIME_WARNING_CATEGORIES`) to gain coverage of the new category in all 4 formatters. See R9-tests-coupled.

4. **Cross-format-parity discipline maintained.** `tests/schema/lint/cli/test_r9d_schema_version.py:84` (`test_json_and_sarif_schema_versions_agree`) continues to pass with the bumped value — JSON top-level `schema_version` and SARIF `runs[].properties.lint_schema_version` agree on `"0.3"`.

5. **`lint_human` and `lint_junit` formatters unchanged by the bump.** No schema_version in their output before or after U5. Verifiable by: existing human/junit formatter tests pass without modification.

6. **`_safe_for_stderr` sanitization on CLI-synthesized warning's `rule_id` still applies** at the new `category="severities_unloaded_rule"` emit site. Verifiable by: the existing sanitization at `cli.py:1090-1096` (calling `_safe_for_stderr(rid)` for both the `rule_id` field and the `f"... {_safe_for_stderr(rid)!r} ..."` message embed) survives the category-name change.

7. **`runtime_warnings` SARIF property co-existence with `lint_schema_version`** unchanged. `tests/test_builtin_lint_runtime_warnings.py:344, 374` (asserting both properties co-exist under `runs[0].properties`) continues to pass after the version literal bumps to `"0.3"`.

8. **TODOS.md backlog reference shape preserved.** The U9 KTD-2 bullet's structural slot stays (one-line "Shipped in D6b 0.3.0" replacement, not deletion) so any other documents that reference the bullet's position by line-anchor don't drift.

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Consumers switching on `category == "unloaded_rule"` expecting the CLI emit site silently break after upgrade — they see zero CLI warnings and assume the feature works. | The forward-compatibility contract addresses NEW values (consumers gracefully handle unknown `category` strings via a default branch); it does NOT address a known value semantically MIGRATING off an emit-site it used to populate. The schema_version 0.2 → 0.3 bump IS the documented wire-format signal for "switch tables need re-checking"; the CHANGELOG-DRAFT staging entry calls out the value-migration explicitly (not just the value-addition) so consumers know to audit their `category == "unloaded_rule"` paths, not just add a `severities_unloaded_rule` branch. |
| The bump-contract docstring refinement is rejected at ce:review for being too long / too prescriptive. | The refinement is the load-bearing contract for U5's bump action — its absence would leave the docstring contradicting the code. KTD-5 marks it REQUIRED in the parent plan. Length is justified by the distinction's load-bearing role. |
| U5 lands the schema_version bump but a future delivery (D7+) needs ANOTHER closed-Literal addition before the next minor bump window — forced to bump 0.3 → 0.4 sooner than otherwise. | This is the correct behavior per the refined contract, not a risk. Closed-Literal additions SHOULD bump. The "savings" of batching is illusory — consumers route on schema_version specifically to know when to re-check their switch statements. |
| The README updates miss a site (4 known sites — 663, 666, 760, 763 — but a 5th could exist). | Plan's verification step includes `grep -n "\"0\\.2\"" README.md` (and the related `lint_schema_version` patterns) at the end to confirm no stale references. |
| The `runtime_warnings` docstring at `_builtin_lint.py:265-271` becomes inaccurate without rewriting. | R9-docstring now mandates the rewrite as a coupled deliverable (was previously deferred to plan; promoted in-line because `_builtin_lint.py` is already being edited and the inaccuracy lives in a public API contract surface). |
| `test_r9a_severities_overlay.py:104`'s assertion `if w["category"] == "unloaded_rule"` quietly continues to pass against a stale value because the test ALSO filters by `rule_id == "naming/does-not-exist"`, and an engine-emit `"unloaded_rule"` warning would never carry that rule_id (the engine only emits for profile-named-but-not-loaded rules). | Plan's test update changes the assertion to `"severities_unloaded_rule"`. The risk is structural — test would NOT silently pass against the old value because the test fixture's `[severities]` table is the only emit-site path that produces a warning carrying that rule_id. |
| A future contributor adds a 6th closed-Literal value WITHOUT bumping schema_version, assuming the U5 bump "covered the category Literal forever". | U7's CHANGELOG presence-ratchet pins the refined docstring wording. The refined docstring is the contract — future contributors reading it before adding a 6th value get the bump trigger explicitly. |

## Assumptions

- D6a 0.2.0 baseline is on `main` at HEAD (confirmed — `8c73f00`).
- D6b U1, U2, U3, U4a, U4b have all shipped (confirmed — see `MEMORY.md` project state + recent commits).
- No external consumers have shipped that depend on the CURRENT conflated `category == "unloaded_rule"` shape for the CLI emit site in a way that would block the wire-format bump (assumption — protokit is pre-1.0; the bump contract explicitly permits this).
- The `_LINT_JSON_SCHEMA_VERSION` constant remains the single source of truth for both formatters (no consumer-injected version-override mechanism exists — verified by file scan).
- `pyproject.toml`'s `[tool.protokit.lint.severities]` table parsing produces stable `rule_id` strings that pass through `_safe_for_stderr` without distortion (assumption — pre-existing D6a U9 R9a contract, not introduced here).
- The README is the authoritative public surface document; updating its wire-format references in U5 is sufficient to communicate the change before U7's broader refresh.

## Output Structure (this unit's commit shape)

Single `feat(lint)` commit (mirrors D6b U3a / U4a / U4b shape):

```text
feat(lint): D6b U5 — R9 severities_unloaded_rule category split + schema_version 0.2 → 0.3

Files modified:
- src/protokit/schema/lint/model.py      (+1 Literal value + docstring rewrite at LintRuntimeWarning)
- src/protokit/schema/lint/cli.py        (category= switch + inline comment rewrite)
- src/protokit/formatters/_builtin_lint.py (constant 0.2 → 0.3 + bump-contract docstring refinement + runtime_warnings docstring rewrite per R9-docstring — null-vs-populated framing replaced with pointer to LintRuntimeWarning.category contract)
- README.md                              (4 sites: 2× schema_version literal + 1× category enumeration extends to 5 + 1× duplicate schema_version literal in DRAFT table)
- CHANGELOG-DRAFT.md                     (new U5 staging section + append to U7 eventual-scope list)
- TODOS.md                               (retire U9 KTD-2 bullet to "Shipped in D6b 0.3.0 (U5)")

Tests modified / added:
- tests/schema/lint/cli/test_r9a_severities_overlay.py  (assertion update: "unloaded_rule" → "severities_unloaded_rule" at the CLI-emit site assertion)
- tests/schema/lint/cli/test_r9d_schema_version.py      (_SCHEMA_VERSION literal "0.2" → "0.3")
- tests/test_builtin_lint_runtime_warnings.py           (2 assertions: lint_schema_version "0.2" → "0.3")
- tests/schema/lint/cli/test_severities_unloaded_rule_category.py  (NEW — source-discrimination contract: engine-emit produces "unloaded_rule", CLI-emit produces "severities_unloaded_rule", both branches asserted in same module; see Open Questions for layout choice)
- tests/schema/lint/test_model.py                       (extend existing Literal-coverage tests with a construct test for the new value, sibling to test_unloaded_rule_category_constructs_with_optional_fields_none at :845-879)
- tests/schema/lint/test_model_dataclass_changes.py     (per R9-tests-coupled: bump len ratchet 4 → 5 at :54; rename test_literal_lists_all_four_categories → ..._five_categories; add "severities_unloaded_rule" to expected set; append 5th tuple to TestFrozen parametrize at :144-151; update module docstring "2 → 4" → "2 → 4 → 5")
- tests/schema/lint/cli/_helpers.py                     (per R9-tests-coupled: add "severities_unloaded_rule" to LINT_RUNTIME_WARNING_CATEGORIES tuple at :31-36; add 5th branch to warning_for_category factory at :62-113)
```

Follow-up commits (separate from U5 feat):

- `fix(lint): D6b U5 ce:review follow-ups — N safe_auto + N gated_auto + N manual` (per established D6b ce:review-then-follow-up pattern).
- `docs(solutions): D6b U5 ce:compound — N new learnings + N reciprocal cross-refs` (captures any U5-specific learnings; expected scope: 1-2 learnings — closed-Literal-bump-trigger ratchet as a worked example of the refined bump-contract, and any plan-deviation observations).

## Sources & References

### Parent documents

- **Parent brainstorm:** `docs/brainstorms/2026-05-14-protokit-lint-delivery-6b-option-aware-and-multi-language-requirements.md:109` (R9 requirement definition) + `:118` (R9-bump scope clarification) + `:222` (Unit 5 framing).
- **Parent plan:** `docs/plans/2026-05-14-001-feat-protokit-lint-d6b-option-aware-and-multi-language-plan.md:485-540` (Unit 5 enumeration) + `:116` (KTD-5 bump-contract docstring refinement) + `:235` (KTD-5 refined wording template) + `:666` (Risks table — bump-contract reconciliation entry) + `:671` (Risks table — severities_unloaded_rule wire-format addition entry).

### Predecessor source artifact

- **D6a U9 KTD-2 commit** `c7a426b` (R9d schema_version constant introduction) + `3c828a4` (R9 ce:review follow-ups including the field-absence-semantic docstring clause that this U5 refines).
- **D6a U9 ce:review F5 finding** (cli-readiness reviewer, 2026-05-13) — recommended the dedicated category split land in D6b. Captured at `docs/solutions/best-practices/semantic-category-conflation-accepted-tradeoff-literal-widening-2026-05-13.md` (the accepted-tradeoff doc that U5's split resolves).

### Institutional learnings applied

- **[[semantic-category-conflation-accepted-tradeoff-literal-widening]]** — U5 closes the deferred design captured in this doc. The 3-site discipline (Literal docstring + CLI emit-site comment + TODOS.md backlog) applies in reverse: each of the three documented sites updates as the split lands. U5's ce:compound pass should annotate this doc with the resolution.

- **[[wire-format-schema-version-bump-contract-and-absence-semantic]]** — U5 is the FIRST closed-Literal-discriminator addition that exercises the bump contract introduced in D6a U9. KTD-5's docstring refinement extends this doc's contract by formalizing the closed-vs-open distinction. The absence semantic ("implicit 0.1") is unchanged by the bump — pre-introduction output predates 0.2 too, and the floor doesn't move.

- **[[cross-format-enum-string-parity-2026-05-08]]** — `lint_json["schema_version"]` and `lint_sarif["runs"][0]["properties"]["lint_schema_version"]` continue to emit the SAME string value (`"0.3"` after U5). Single constant `_LINT_JSON_SCHEMA_VERSION` enforces this structurally.

- **[[pre-1.0-version-bump-as-communication-contract]]** — the 0.2 → 0.3 bump is a pre-1.0 minor bump, NOT a 1.0 stability commitment. Consumers reading the schema_version bump should treat it as "wire-format changed in a consumer-detectable way; re-check switch statements" — not as a SemVer-major-style breaking-change marker. The CHANGELOG-DRAFT staging entry phrases the consumer-migration in pre-1.0 terms.

- **[[delivery-boundary-unit-commit-composition]]** — U5 is a per-unit commit (additive wire-format change); U7 is the delivery-boundary commit (0.2.0 → 0.3.0 version bump in `pyproject.toml` + `CHANGELOG-DRAFT.md` fold into `CHANGELOG.md` + final README refresh). U5's CHANGELOG-DRAFT staging entry feeds into U7's composition.

- **[[module-name-newline-injection-stderr-forge]]** — the existing `_safe_for_stderr(rid)` sanitization at the CLI-emit site survives the category rename verbatim. No new sanitization paths.

- **[[public-surface-draft-discipline-source-audit]]** — README's Public Surface DRAFT table is the contract surface; U5 updates 2 of its rows (the two `lint_schema_version` rows). U7's broader DRAFT refresh handles new rows for R7 BUILTIN_PACKS registration.

### Review history

- **(none yet — this brainstorm is being authored)**
- *To be added during `/ce:plan` Phase 1.1:* `document-review` skill output for THIS brainstorm.
- *To be added at U5 ce:review:* personas selected per ce-review skill conditional gates (correctness, testing, maintainability, project-standards always-on; cli-readiness given CLI emit-site changes; api-contract given wire-format additive change; learnings-researcher for cross-doc verification).

### Next step

Run `/ce:plan` against this brainstorm. Plan owns: test layout choice (in-place updates + 1 new module vs separate module-per-concern), `runtime_warnings` docstring rewrite scope, README JSON-shape table cell formatting, and ce:review persona-selection rationale.
