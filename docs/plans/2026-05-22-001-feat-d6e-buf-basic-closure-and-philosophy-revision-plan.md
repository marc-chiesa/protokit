---
title: D6e — buf BASIC Closure + UX Philosophy Revision (0.6.0)
type: feat
status: active
date: 2026-05-22
origin: docs/brainstorms/2026-05-22-d6e-buf-basic-closure-philosophy-revision-requirements.md
---

# D6e — buf BASIC Closure + UX Philosophy Revision (0.6.0)

## Overview

Ship protokit 0.6.0 with the closing headline **"26 of 26 buf v1.69.0 BASIC rules (with one documented divergence on extend-block-required-fields)"** across four implementation units:

- **U1 — UX Philosophy Revision** (atomic with U2): formalize the hard-inverted principle (protokit-UX overrides buf-parity), activate the new `proto2-strict` opt-in profile, demote `file/syntax-specified` from ERROR to WARNING in `recommended` + `default`.
- **U2 — `field/not-required`**: the deferred D6d-U3 rule. Proto2-only buf-parity rule (`buf:FIELD_NOT_REQUIRED`). Ships in `proto2-strict` profile only at ERROR severity, with a documented extend-block divergence asterisked in three sites.
- **U3 — `package/no-import-cycle`**: the 26th buf BASIC rule (`buf:PACKAGE_NO_IMPORT_CYCLE`). Package-level cycle detection via a Tarjan SCC pre-walk accumulator extending D6c's Arch-D pattern; ships in `recommended` + `default` at ERROR (Phase 0 confirms).
- **U4 — Delivery Boundary (0.6.0)**: pyproject `0.5.0 → 0.6.0`, CHANGELOG fold, README "26 of 26 v1.69.0" numerator refresh, parametrized CLI dedup test consolidation (the third-instance trigger), presence-ratchet, bump-contract ratchet pin (no `_LINT_JSON_SCHEMA_VERSION` bump), stale-text sweep.

Per D6e KD-1, the inverted philosophy is the durable artifact that lets future proto2-specific rules slot into `proto2-strict` without re-debating defaults. The buf-parity arc structurally closes here; D6f+ resumes option-aware deepening (R6 promotion, IDENTIFIER-based field_behavior contradictions, the extend-block engine walker extension that resolves U2's divergence).

## Problem Frame

Two D6d-era deferrals stay open: `FIELD_NOT_REQUIRED` (deferred because the underlying UX-philosophy question was load-bearing) and `PACKAGE_NO_IMPORT_CYCLE` (deferred because its cross-file cycle-detection algorithm does not reuse D6c's Arch-D pre-walk accumulator pattern). D6e resolves both inside one umbrella release plus a formal philosophy revision that unblocks consistent defaults for proto2-specific rules going forward.

"Pragmatic, not dogmatic": proto2 is officially supported with no known deprecation timeline. The hard-inverted philosophy is NOT "proto2 is deprecated" — it is "protokit does not force opinionated proto2 stance into default profiles." Users who want strict proto2 checks opt in via `--profile proto2-strict` or pyproject `profile = ["default", "proto2-strict"]`.

The bundled-umbrella shape (philosophy + two rules + delivery boundary) was chosen over a sequential split (`0.5.1` philosophy patch then `0.6.0` rules) because the inverted-philosophy framing has no user-visible behavior change beyond the two new rules — a standalone patch would be principle-without-substance.

## Requirements Trace

Each requirement traces back to the origin brainstorm.

- **R1** — Hard-inverted philosophy principle: protokit-UX overrides buf-parity when they conflict. Retires U3-KD-6 from the SUPERSEDED D6d U3 brainstorm. (U1)
- **R2** — Pragmatic proto2 stance: proto2 supported, no deprecation timeline, proto2-specific anti-pattern rules ship in opt-in `proto2-strict` profile only. (U1)
- **R3** — `proto2-strict` profile activation: name registered downstream when at least one rule declares `profiles=("proto2-strict",)`. No `_coerce_profile` or `_PROFILE_ALIASES` code change required (verified — see "Resolved During Planning"). (U1 + U2)
- **R4** — Audit pass on D6a–D6c existing rules under the inverted philosophy. No retroactive code changes EXCEPT `file/syntax-specified` (handled in R4b). Other audit findings become D6f+ backlog items with concrete N/M forcing-function triggers. (U1)
- **R4b** — Demote `file/syntax-specified` from ERROR to WARNING in `recommended` + `default`. 1-line severity change at `src/protokit/schema/lint/rules/file.py:61` + module docstring update + CHANGELOG entry. (U1)
- **R5** — Implement `field/not-required` per the SUPERSEDED D6d U3 brainstorm's UR-6 rule body. Profile: `proto2-strict` only. Severity: ERROR. EV-1 / EV-3 / EV-4 bound at U2 Phase 0 against buf v1.69.0; EV-2 (extend-block) **IMPLEMENTATION OUT-OF-SCOPE** per U3-KD-7 (engine walker gap at `engine.py:841-916` does not iterate `fd.extensions_by_name` OR `Message.extensions_by_name` — file-level AND nested-message extend blocks are equally invisible to the walker; this is one architectural gap with two surface forms). **DOCUMENTATION IN-SCOPE** — the four-site protocol per [[buf-parity-divergence-documentation-discipline-2026-05-13]] documents the known divergence in U2 as specimen #2 (D6f+ walker extension resolves both surface forms together). (U2)
- **R6** — Implement `package/no-import-cycle` with package-level edge granularity. Cycle = SCC of size ≥ 2. Profile: `recommended` + `default`. Severity: ERROR (subject to Phase 0). Algorithm: Tarjan SCC pre-walk extending D6c's `_build_directory_package_accumulator` pattern (KD-12 direction-of-travel; planning binds). (U3)

Plus standard delivery-boundary trace from the brainstorm's U4 block:

- pyproject `0.5.0 → 0.6.0`, CHANGELOG `### D6e` fold, README "26 of 26 v1.69.0" numerator refresh, BUILTIN_PACKS expansion (new `field` pack + `package/no-import-cycle` added to `package` pack), presence-ratchet + parametrized CLI dedup test consolidation (KD-13 + KD-14), bump-contract ratchet pin (no `_LINT_JSON_SCHEMA_VERSION` bump per KD-9), stale-text sweep. (U4)

## Scope Boundaries (Non-Goals)

- **No retroactive code changes** to D6a–D6c rules under the inverted philosophy beyond `file/syntax-specified`. Audit findings (if any) become D6f+ backlog items with explicit N/M forcing-function triggers.
- **No `strict` profile activation** in D6e. The deferred `strict` profile (COMMENT_* / ENUM_ZERO_VALUE_SUFFIX style-strictness) stays deferred. `proto2-strict` is distinct.
- **No expanded option-aware rules**: R6 promotion to error, IDENTIFIER-based field_behavior contradictions, MessageSet-aware rules — D6f+ option-aware-deepening.
- **No `LintLocation` exhaustiveness contract** decision; no new `LintLocation` discriminant in U3 (per-file emission uses existing `FileLocation`).
- **No `_LINT_JSON_SCHEMA_VERSION` bump** (no new closed-Literal `LintRuntimeWarning.category` values added in D6e per KD-9).
- **No deep proto2 EV verification beyond U2 Phase 0** (EV-5..EV-8 stay deferred per "verify post-ship only if user reports divergence").

### Deferred to Separate Tasks

- **R9b — per-rule disable/enable CLI flag (specifically the `[severities] = "off"` value)** — stays in D6f+ backlog. `[severities]` overrides at `"error"` / `"warning"` / `"info"` remain the de-facto demote mechanism; full disable via `"off"` is not yet supported.
- **Engine walker extension for `fd.extensions_by_name` AND `Message.extensions_by_name`** (file-level + nested-message extend blocks) — resolves U2's documented extend-block divergence at both surface forms. Tracked in TODOS.md with a concrete user-report-driven trigger ("first user report of a missed proto2 extend-block-required field that buf catches → prioritize for the next delivery") per Product-lens F2, NOT a vague "D6f+" timeline. U2's divergence-documentation sites are the forward-pointers.
- **Structured `LintRuleSpec.parity_note: str` field** — `file/syntax-specified` (D6a U6) is divergence specimen #1; `field/not-required` (D6e U2) is specimen #2. Per the [[buf-parity-divergence-documentation-discipline-2026-05-13]] sentinel ("defer until N=3"), planning explicitly evaluates and defers. Recorded in U2's rule docstring + a brief `docs/solutions/best-practices/` ce:compound entry at U2 boundary so the third specimen triggers the promotion.

## Context & Research

### Relevant Code and Patterns

- **`_coerce_profile` + `_PROFILE_ALIASES`** at `src/protokit/schema/lint/_config.py:491-572` — accepts any normalized string. Verified: no code change required for `proto2-strict` (primary name, not an alias). R3 is correct.
- **Profile validity gate** at `src/protokit/schema/lint/cli.py:1005-1037` — `if not composed_profile.rule_ids:` raises `unknown-profile` exit-2. This is the structural reason U1+U2 must land atomically (see KD-3 below).
- **`@lint_rule` decorator** at `src/protokit/schema/lint/decorator.py` — attaches `LintRuleSpec` to `fn._lint_spec`. `profiles=("proto2-strict",)` on any rule body makes the profile valid at load time via `LintProfile.from_pack` at `src/protokit/schema/lint/model.py:802-861`.
- **`file/syntax-specified` rule** at `src/protokit/schema/lint/rules/file.py:59-72` — severity at line 61, the R4b 1-line edit site. Module docstring already documents the descriptor-cannot-distinguish proto2-explicit-vs-implicit divergence.
- **Pre-walk accumulator (D6c Arch-D)** at `src/protokit/schema/lint/engine.py:707-835` (`_build_directory_package_accumulator`). The model U3's `_build_import_graph_accumulator` mirrors.
- **Engine per-file walker** at `src/protokit/schema/lint/engine.py:841-916` (`_dispatch_file` / `_dispatch_enum` / `_dispatch_message`) — verified NEVER iterates `fd.extensions_by_name` (file-level extend blocks) OR `Message.extensions_by_name` (nested-message extend blocks). Zero grep matches for any `extensions_by_name` surface in engine.py. `_dispatch_message` at `engine.py:902` iterates `message.fields` only; extends nested inside a message live in `Message.extensions_by_name`, not in `message.fields`. **The architectural gap has two surface forms** — file-level AND nested-message — that share the same root cause (no iteration of any `extensions_by_name` accessor). The D6f+ walker extension that resolves U2's divergence covers both surface forms together. **Note**: the brainstorm KD-10 + R5 EV-2 references `engine.py:818-893` for the walker — that range is inside `_build_directory_package_accumulator`, not the walker. All four U2 documentation sites (module docstring, function docstring, message_template, test method docstrings) must cite the corrected `engine.py:841-916` range AND name both extend surfaces.
- **Package pack** at `src/protokit/schema/lint/rules/package.py:1-499` — natural home for U3's cycle rule alongside R8/R8b cross-file siblings. Already imports `posixpath` + uses `_safe_for_stderr` + 500-char cap discipline.
- **Imports access pattern**: `rules/imports.py:85-91` uses `ctx.file.CopyToProto(fdp)` + `fdp.dependency` (list of import filenames). No direct `fd.dependencies` accessor exists; U3 follows the CopyToProto round-trip pattern.
- **`BUILTIN_PACKS`** at `src/protokit/schema/lint/rules/__init__.py:164-173` — module-name tuple. Three docstring substrings hard-pinned by `tests/schema/lint/test_builtin_packs.py:121-171`.
- **CLI dedup helper** at `tests/schema/lint/_cli_dedup_helpers.py:27-82` — `compile_sources_to_descriptor_set(...)` SSOT (D6d new-U4 MAINT-2). Two per-flip files to consolidate per KD-13: `tests/schema/lint/test_cli_rule_pack_dedup_post_d6c.py` + `tests/schema/lint/test_cli_rule_pack_dedup_post_d6d.py`. CLI accumulator at `src/protokit/schema/lint/cli.py:870-885`; `zip(strict=True)` at `cli.py:1058-1060`.
- **Buf parity infrastructure** at `tests/parity/conftest.py`: `_PARITY_EXCEPTIONS` at `:124-135` (posture handling), `_FAMILY_PROTO_TO_BUF` + `_FAMILY_RULE_IDS` partition at `:258-267`, `assert_parity_multi_file` at `:894-1088`. `_BUF_PARITY_PIN = "v1.69.0"` at `src/protokit/schema/lint/cli.py:153`.
- **Multi-file parity exemplar** for U3: `tests/parity/test_parity_package_directory.py` (D6c U3 R8/R8b family). Fixture pattern: `tests/schema/lint/rules/fixtures/<family>/_buf_smoke/<fixture_name>/{*.proto, buf.yaml}` + recorded NDJSON at `_buf_smoke/recorded/<fixture_name>.json`. Snapshot SHA-256 pinned by `tests/schema/lint/test_buf_smoke_recorded_checksums_*.py`.
- **Single-file parity exemplar** for U2: `tests/parity/test_parity_file.py` for `file/syntax-specified`, fixtures at `tests/parity/fixtures/file/syntax-specified/{good,no_syntax,explicit_proto2}.proto`.
- **CHANGELOG presence-ratchet** at `tests/test_changelog_delivery_presence_ratchet.py:71-76` — `DELIVERY_RATCHETS` tuple; D6e appends `DeliveryRatchetSpec(delivery="D6e", version="0.6.0")` with Pattern A line-anchored regex.
- **Bump-contract ratchet** at `tests/test_builtin_lint_formatter.py:705-760` — `_LINT_JSON_SCHEMA_VERSION = "0.5"` stays unchanged (KD-9). No edits to `ratchet_substrings` unless prose around the constant changes.
- **D6d new-U4 boundary plan** at `docs/plans/2026-05-19-001-feat-d6d-option-aware-pack-expansion-plan.md:1170-1262` — the canonical exemplar for U4 structure.

### Institutional Learnings

All are repo-local at `docs/solutions/`. Each is summarized with how it applies to D6e.

- **[[multi-unit-ce-review-stash-pop-coordination-2026-05-21]]** — ALL units. `git stash push --include-untracked -m "d6e-u<n>-wip-pre-review"` BEFORE invoking `/ce:review` when next unit's WIP coexists with current unit at review time. Run `/ce:compound` BEFORE popping so the captured learning does not pick up next unit's mutations.
- **[[delivery-boundary-unit-commit-composition-2026-05-14]]** — U4. 7-component commit: pyproject bump, policy docstring amendments, CHANGELOG section, README refresh including "26 of 26" numerator, TODOS.md update, presence-ratchet additions, canonical stale-text sweep.
- **[[delivery-boundary-bundled-commit-feat-plus-review-followups-2026-05-21]]** — U4. Default split (feat commit + follow-ups commit); FOLD when (a) delivery boundary AND (b) ce:review ran against uncommitted work. Soft cap ~500 LOC code change. Recent commit `67cd7fb` is the canonical D6d worked example.
- **[[pre-1.0-version-bump-as-communication-contract-2026-05-14]]** — U1 + U4. Drop ceremonial `BREAKING:` markers — version bump IS the breaking signal pre-1.0. CHANGELOG body carries the weight. R4b WARNING demotion belongs in a `Changed — behavior delta` framing.
- **[[presence-ratchet-test-pattern-for-prose-substrings-2026-05-14]]** — U1 + U4. 6 disciplines, especially: (5) substring MUST fit on a single source line (verify pre-commit); (6) line-anchored heading regex for per-section ratchets.
- **[[cli-loaded-packs-dedup-zip-strict-builtin-packs-flip-2026-05-18]]** — U2 + U3. Every BUILTIN_PACKS flip can trigger latent `zip(strict=True)` mismatch at `cli.py:1058-1060`. The parametrized consolidation IS the third-instance trigger.
- **[[migration-recipe-severity-aware-template-reuse-2026-05-21]]** — U4 CHANGELOG recipe. Re-verify every severity-dependent claim. `LintSeverity` accepts `"error"`/`"warning"`/`"info"` ONLY (NOT `"off"` — R9b still deferred). Run documented demotion against minimal fixture BEFORE committing recipe.
- **[[changelog-readme-snippet-fixture-byte-equivalence-2026-05-21]]** — U4. Every executable config snippet (TOML, JSON, CLI) in CHANGELOG/README MUST be byte-equivalent to a committed test fixture.
- **[[audit-wire-format-before-claiming-sibling-parity-2026-05-03]]** — U2 + U3 + U4. Layer D grep at U4: `grep -rn 'source_spec="buf:' src/protokit/schema/lint/rules/` must count 26 before shipping the "26 of 26" claim.
- **[[plan-review-verify-prior-art-citations-2026-05-15]]** — applied at this plan-write moment. Verified `engine.py:818-893` claim from brainstorm against the actual walker location (corrected to `engine.py:841-916`). U2 + U3 must re-verify the SUPERSEDED brainstorm's EV claims against buf v1.69.0 at Phase 0.
- **[[apply-institutional-learnings-postdating-plan-during-ce-review-2026-05-09]]** — ALL units' per-unit ce:review pass.
- **[[dual-view-prewalk-accumulator-cross-file-rule-dispatch-2026-05-19]]** — U3. Wrap with `MappingProxyType` 2-level + `frozenset` innermost. Single-view is fine if only one rule consumes; add dual-view only if a second rule needs a complementary access pattern.
- **[[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]]** — U2 + U3. Commit buf v1.69.0 NDJSON snapshots BEFORE writing protocol logic. Three complementary surfaces: parity gate (oracle), integration idempotency (CLI dedup), unit invariant-pin.
- **[[family-aware-partition-pattern-multi-family-parity-harness-2026-05-19]]** — U2 + U3. Each family gets three module-level constants in `tests/parity/conftest.py`: inclusion frozenset, `_PROTO_TO_BUF` dict, `_RULE_IDS` frozenset. `assert_parity_multi_file` consumes union constants only.
- **[[dormant-code-changelog-draft-staging-delivery-boundary-2026-05-17]]** — `CHANGELOG-DRAFT.md` per-unit staging; U4 folds into `CHANGELOG.md`. NOT applying full 5-component dormancy (U2 + U3 ship active in their unit commits, not dormant pending U4 flip).
- **[[builtin-packs-expansion-changelog-migration-recipe-structure-2026-05-18]]** — U4 CHANGELOG recipe. 5 sub-sections: breaking magnitude with worst-case math, demotion paths ranked by SITUATION, pyproject stub, accepted-tradeoff scenarios, upgrade triage walkthrough.
- **[[stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12]]** — U4 sweep step. Grep + triage rubric. Past-tense historical refs and frozen planning artifacts: LEAVE.
- **[[lint-rule-message-templates-must-not-recommend-actions-that-trigger-siblings-2026-05-13]]** — U2 + U3 message_template authoring. Audit recommended remediations against sibling rules in active profile.
- **[[buf-parity-divergence-documentation-discipline-2026-05-13]]** — U2 four-site protocol (module docstring + function docstring + message_template + test method docstrings). Specimen #2 sentinel for structured `parity_note` field — explicitly evaluated and DEFERRED to specimen #3 in this plan.
- **[[clirunner-catch-exceptions-false-explicit-discipline-2026-05-21]]** — every `CliRunner.invoke(...)` in tests for U2/U3/U4 passes `catch_exceptions=False`.
- **[[ruff-fix-scope-discipline-pass-diff-files-explicitly-2026-05-21]]** — ce:review follow-ups across all units pass explicit file paths to `ruff check --fix`.
- **[[wire-format-schema-version-bump-contract-and-absence-semantic-2026-05-13]]** + **[[closed-literal-discriminator-bump-trigger-2026-05-17]]** — U4. No new closed-Literal values in D6e; `_LINT_JSON_SCHEMA_VERSION` stays `"0.5"`. Pre-release intra-cycle renames don't bump.
- **[[programmatic-proto-fixture-builder-multi-file-rule-family-2026-05-17]]** — U3 cycle fixtures (6+ scenarios). Static fixtures are fine since total ≈ 6; planning chooses static unless fixture count climbs.
- **[[rule-pack-extension-ssot-rule-ids-and-test-class-naming-2026-05-12]]** — U2's new `field` pack test file derives `_ALL_FIELD_RULE_IDS = frozenset(fn._lint_spec.rule_id for fn in RULES)`.
- **[[copytoproto-round-trip-for-proto-form-only-descriptor-fields-2026-05-13]]** — U2 (`fdp.syntax` read after `CopyToProto`) + U3 (`fdp.dependency` read).
- **[[pureposixpath-for-proto-descriptor-file-stem-2026-05-12]]** — U3 accumulator uses `posixpath` for protobuf-canonical paths (matches `_build_directory_package_accumulator` precedent at `engine.py:803-814`).

### External References

None gathered. Local patterns are sufficient — every component (profile machinery, accumulator pattern, parity gate, presence-ratchet, CLI dedup, CHANGELOG recipe) has a direct D6a–D6d precedent. The brainstorm's buf v1.69.0 behavior claims are bound at Phase 0 of U2 + U3 via empirical re-invocation, not external doc citation.

## Key Technical Decisions

Planning-bound additions (PD-*) layered onto the brainstorm's KD-1..KD-14:

- **PD-1 — `_coerce_profile` + `_PROFILE_ALIASES` need no code change for `proto2-strict`**: `_config.py:540-565` accepts any normalized string; downstream validity is enforced by `cli.py:1005-1037` (`if not composed_profile.rule_ids:`). R3 confirmed.
- **PD-2 — U1+U2 atomic landing is a hard structural requirement, not a soft norm**: between U1 (profile-name documented but no rule populates it) and U2 (rule body declares `profiles=("proto2-strict",)`), `--profile proto2-strict` exits 2 with `error[lint-unknown-profile]:`. Plan U1+U2 as ONE feat commit per CONV-C; ce:review runs once across the combined surface.
- **PD-3 — Engine walker citation correction + extend surface broadening**: brainstorm KD-10 + R5 EV-2 reference `engine.py:818-893` for the walker — that range is INSIDE `_build_directory_package_accumulator`. Actual walker is `_dispatch_file` / `_dispatch_enum` / `_dispatch_message` at `engine.py:841-916`. All four U2 divergence-documentation sites (module docstring, function docstring, `message_template`, test method docstrings) AND the `_PARITY_EXCEPTIONS` annotation in `tests/parity/conftest.py` use the corrected `engine.py:841-916` citation. The citation must name BOTH extend surfaces — `fd.extensions_by_name` (file-level) AND `Message.extensions_by_name` (nested-message) — because the architectural gap has two surface forms that share one root cause; documenting only the file-level surface would leave a future user with a nested-message extend confused about why their `required` field did not fire.
- **PD-4 — `field/not-required` lives in a NEW `src/protokit/schema/lint/rules/field.py` pack** (resolves OQ-5): mirrors `file.py` shape (single-rule pack); preserves module-per-rule clarity; aligns with SUPERSEDED brainstorm UR-4. The `field` pack name is the namespace anchor for future field-level proto2-strict rules per KD-11 (`field/no-group-syntax`, `field/no-explicit-default`, `field/packed-repeated-primitive`).
- **PD-5 — U3 algorithm is Tarjan SCC (binds KD-12 direction-of-travel)**: planning binds. DFS back-edge fallback is rejected because Tarjan produces the SCC artifact KD-6 needs directly (size-≥2 SCCs); back-edge detection produces only "is there a cycle" without enumerating membership. Kahn's topological sort is excluded per OQ-4 reasoning (does not enumerate SCCs).
- **PD-6 — U3 emission shape: per-file via package→root_files fan-out** (binds KD-12 emission decision). Each root file participating in an SCC of size ≥ 2 gets one finding. Matches D6c R8/R8b precedent. Phase 0 verifies buf v1.69.0 actually emits per-file; if buf diverges (per-cycle or per-package), planning re-opens the decision with buf as the anchor (already noted in KD-12).
- **PD-7 — U3 cycle scope: fire if ANY root file participates in the cycle** (binds KD-12 scope decision). NOT root-files-only (misses cycles routed through vendor packages user could fix); NOT include-transitives (fires on vendor-only cycles user cannot fix). The middle option is the semantically correct fence for a lint rule.
- **PD-8 — `FileLintContext.import_cycles` shape**: `Mapping[str, frozenset[str]] | None = None` (file_name → set of package names participating with this file in its SCC). Single-view (one rule consumes); does not need dual-view per [[dual-view-prewalk-accumulator-cross-file-rule-dispatch-2026-05-19]] unless a sibling rule surfaces.
- **PD-9 — Parametrized CLI dedup test FILE consolidation triggered at third near-copy-paste instance** per [[cli-loaded-packs-dedup-zip-strict-builtin-packs-flip-2026-05-18]] Prevention #6. The SHARED HELPER (`compile_sources_to_descriptor_set` at `tests/schema/lint/_cli_dedup_helpers.py:27-82`) was already extracted at D6d new-U4 MAINT-2 (instance #2 — that consolidation was helper-level). U4's consolidation is the test-FILE level: three near-copy-paste test files (`test_cli_rule_pack_dedup_post_d6c.py`, `test_cli_rule_pack_dedup_post_d6d.py`, the never-created `_post_d6e.py`) become one parametrized `tests/schema/lint/test_cli_rule_pack_dedup.py` iterating over every member of `BUILTIN_PACKS`. Per-pack fixture-source overrides as parametrize-case data (`package` pack needs two-package source for R8/R8b coverage; `field` pack needs proto2-required source). Per KD-14, the consolidated file is CREATED at U2 with `field` pack parameters; U3 EXTENDS the parametrized cases to cover the new `package/no-import-cycle` rule's fixtures.
- **PD-10 — Structured `LintRuleSpec.parity_note: str` field DEFERRED to specimen #3**: U2's extend-block divergence is the second specimen (after D6a U6's `file/syntax-specified` descriptor-cannot-distinguish divergence). Per [[buf-parity-divergence-documentation-discipline-2026-05-13]] sentinel ("evaluate at N=2; defer until N=3"), planning evaluates and defers. Reasoning: (a) the four-site protocol works at N=2 — divergences are findable and properly documented; (b) adding the field now changes `LintRuleSpec` shape + decorator + serialization with broad blast radius; (c) the sentinel is "evaluate" not "implement" — evaluation says wait. Recorded here + in U2's rule docstring + as a brief ce:compound entry at U2 boundary so the third specimen triggers promotion.
- **PD-11 — N/M forcing-function trigger for R4 audit-finding backlog items (resolves brainstorm CONV-A)**: planning-bound defaults of **N=3 reports within M=8 weeks post-D6e-ship** for the generic "if X proto2-related issue reports within Y weeks, pull retroactive demotion into 0.6.1 patch" template. **Caveat on community-size scaling**: at a small user community (e.g., <100 active users with typical 1-5% issue-report rates), N=3 may never fire even when a real regression hits a meaningful fraction of users; M=8 weeks may filter out slow-cycle (quarterly) adopters. Specific backlog items should tighten N/M when the finding has clearly-high blast radius (e.g., a default-severity demotion candidate could use N=1/M=4-weeks; "any credible report with a minimal repro" can override count entirely). Default rationale: 3 reports passes the "not a single anomaly" bar; 8 weeks matches normal beta windows for new behavior; the default is the LOOSE end of the calibration band so future maintainers explicitly opt into tighter triggers per-item. Documented in U4's TODOS.md update alongside the assumed-user-population caveat so the threshold can be re-evaluated as the user base grows.
- **PD-12 — No `_LINT_JSON_SCHEMA_VERSION` bump in D6e** (binds KD-9): no new closed-Literal `LintRuntimeWarning.category` values added; no `LintLocation` discriminant additions (U3 uses existing `FileLocation`). The bump-contract ratchet substrings at `tests/test_builtin_lint_formatter.py:705-760` do not need editing unless prose around the constant changes.
- **PD-13 — Static (not programmatic) fixtures for U3** per [[programmatic-proto-fixture-builder-multi-file-rule-family-2026-05-17]]: cycle-fixture cardinality is ~6, below the programmatic-builder threshold (~5). Hand-authored multi-file fixtures per the `test_parity_package_directory.py` precedent. If Phase 0 reveals more variants are required (e.g., LEGACY_REQUIRED-with-cycle), revisit at U3 implementation time.

## Open Questions

### Resolved During Planning

- **OQ-4 (algorithm choice)** — Tarjan SCC per PD-5.
- **OQ-5 (where `field/not-required` lives)** — new `src/protokit/schema/lint/rules/field.py` pack per PD-4.
- **CONV-A N/M trigger** — N=3 reports / M=8 weeks default per PD-11.
- **Structured `parity_note`** — deferred to specimen #3 per PD-10.
- **U1+U2 atomic-commit shape** — confirmed mandatory per PD-2.
- **Engine walker citation correction** — `engine.py:841-916` per PD-3.

### Deferred to Implementation

- **OQ-1** — Phase 0 of U3 empirically verifies buf v1.69.0's `PACKAGE_NO_IMPORT_CYCLE` emission shape (per cycle vs per file vs per package). PD-6 binds to per-file as direction-of-travel; Phase 0 confirms or re-opens.
- **OQ-2** — Phase 0 of U3 verifies cycle-detection scope: root-files-only vs transitives. PD-7 binds to "any root participates"; Phase 0 confirms or re-opens.
- **OQ-3** — Phase 0 of U3 verifies `PACKAGE_NO_IMPORT_CYCLE` membership in buf BASIC profile (KD-8 direction: probably `recommended` + `default` at ERROR).
- **OQ-6** — Phase 0 of U2 confirms EV-1 (edition LEGACY_REQUIRED 3-outcome matrix), EV-3 (group-typed required), EV-4 (multi-file proto2+proto3 mix) outcomes from SUPERSEDED brainstorm still bind against buf v1.69.0.
- **Co-fire ordering for U3** — `package/no-import-cycle` position in `package.py`'s `RULES` tuple bound at Phase 0 to match buf's alphabetical emission order (per feasibility F4: probably between `PACKAGE_DIRECTORY_MATCH` and `PACKAGE_SAME_DIRECTORY`).
- **Final cycle-detection fixture corpus** — Phase 0 of U3 enumerates exact fixture set; minimum per brainstorm: direct A↔B cycle, 3-node A→B→C→A, self-import-not-cycle, vendor-only cycle (out of scope per likely Phase 0 outcome), root+vendor mixed cycle (in scope).
- **`field/not-required` worked-example scope** — at U2 implementation, decide whether to add a worked-example fixture per [[worked-example-multi-scenario-test-class-template-2026-05-21]] (strategic-differentiator-feature pattern). `proto2-strict` profile activation is a strategic-differentiator surface; lean toward including but defer concrete shape.

## Output Structure

D6e adds one new source file (`field.py`); other changes are modifications to existing files. The tree below is informational, not a constraint — implementer may adjust if discovery reveals a better layout.

```
src/protokit/schema/lint/rules/
├── __init__.py          (modify — BUILTIN_PACKS docstring + add field import; U2 + U4)
├── file.py              (modify — severity demotion at :61, docstring update; U1)
├── package.py           (modify — add check_package_no_import_cycle to RULES; U3)
└── field.py             (CREATE — new pack; U2)
    └── RULES = (check_field_not_required,)

tests/parity/
├── conftest.py          (modify — add 2 _PARITY_EXCEPTIONS entries + _D6E_*_INCLUSION family constants; U2 + U3)
├── fixtures/field/not-required/
│   ├── proto2_required.proto             (CREATE)
│   ├── proto2_optional.proto             (CREATE)
│   ├── proto3_field.proto                (CREATE)
│   └── proto2_extend_block_required.proto (CREATE — divergence specimen)
├── snapshots/field/not-required/         (CREATE — buf v1.69.0 NDJSON snapshots; U2)
├── test_parity_field.py                  (CREATE — single-file parity gate; U2)
└── test_parity_package_no_import_cycle.py (CREATE — multi-file parity gate; U3)

tests/schema/lint/
├── _cli_dedup_helpers.py                 (no change — shared SSOT remains)
├── test_cli_rule_pack_dedup.py           (CREATE — parametrized consolidation; U2)
├── test_cli_rule_pack_dedup_post_d6c.py  (DELETE — folded into parametrized; U2)
├── test_cli_rule_pack_dedup_post_d6d.py  (DELETE — folded into parametrized; U2)
├── test_engine_import_graph_accumulator.py (CREATE — U3 accumulator unit tests)
├── test_buf_smoke_assumptions_package_no_import_cycle.py    (CREATE — U3)
├── test_buf_smoke_recorded_checksums_package_no_import_cycle.py (CREATE — U3)
├── test_builtin_packs.py                 (modify — membership pin + docstring substring ratchets; U2 + U4)
└── rules/
    ├── test_field.py                     (CREATE — U2 rule tests)
    ├── test_package.py                   (modify — U3 rule tests)
    └── fixtures/package_no_import_cycle/_buf_smoke/
        ├── two_node_cycle/{a.proto, b.proto, buf.yaml}      (CREATE; U3)
        ├── three_node_cycle/{a.proto, b.proto, c.proto, buf.yaml} (CREATE; U3)
        ├── self_import_not_cycle/{a.proto, buf.yaml}        (CREATE; U3)
        ├── no_cycle_baseline/{a.proto, b.proto, buf.yaml}   (CREATE; U3)
        ├── root_vendor_mixed_cycle/{a.proto, vendor/v.proto, buf.yaml} (CREATE; U3)
        └── recorded/                                         (CREATE — NDJSON snapshots; U3)

tests/
├── test_changelog_delivery_presence_ratchet.py (modify — add D6e ratchet spec; U4)
├── test_builtin_lint_formatter.py              (no edits expected — verify substrings still hold; U4)
└── test_uxd_philosophy_principle_presence_ratchet.py (CREATE — KD-1 principle text ratchet; U1)

src/protokit/schema/lint/
├── engine.py            (modify — _build_import_graph_accumulator + init + finally + _build_file_ctx threading; U3)
└── model.py             (modify — FileLintContext.import_cycles field; U3)

docs/solutions/best-practices/
├── tarjan-scc-import-cycle-detection-pre-walk-2026-05-XX.md (CREATE — U3 ce:compound)
├── proto2-strict-profile-activation-pattern-2026-05-XX.md  (CREATE — U1 ce:compound)
└── near-copy-paste-third-instance-consolidation-trigger-2026-05-XX.md      (CREATE — U4 ce:compound; resolves the bracketed reference)

CHANGELOG.md             (modify at U4 — fold from CHANGELOG-DRAFT.md)
CHANGELOG-DRAFT.md       (modify each unit; reset at U4)
README.md                (modify at U1 — profile table; at U4 — numerator + worked example)
pyproject.toml           (modify at U4 — 0.5.0 → 0.6.0)
TODOS.md                 (modify at U4 — remove resolved backlog items + add D6f+ items)
```

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

### U3 Tarjan SCC Pre-Walk Accumulator Shape

The accumulator mirrors D6c's `_build_directory_package_accumulator` at `engine.py:707-835`. Single-view (one rule consumes); does not extend to dual-view absent a sibling rule. The accumulator runs once per `LintEngine.run()` between Steps 3.5b and 4; the per-file view is threaded into `FileLintContext.import_cycles` and consumed by `check_package_no_import_cycle` at per-file dispatch time.

```
                       compile_result.root_files
                                  │
                                  ▼
                  ┌─────────────────────────────────┐
                  │ _build_import_graph_accumulator │
                  └─────────────────────────────────┘
                                  │
              ┌───────────────────┼───────────────────┐
              ▼                   ▼                   ▼
     iterate root files     CopyToProto round-trip   pool lookup
     for fname in            fdp.dependency           for dep_name in
     compile_result.        (list of import           fdp.dependency:
     root_files:             filenames per             dep_fd = pool.
       fd = pool.FindFile    [[copytoproto-round-     FindFileByName
         ByName(fname)        trip-for-proto-          (dep_name)
       fdp = FileDescriptor   form-only-descriptor-   dep_pkg = dep_fd.
         Proto()              fields]])                package
       fd.CopyToProto(fdp)
              │
              ▼
     build directed edge set:
     edges[source_pkg] |= {dep_pkg}
     (multi-file P→Q imports collapse to one edge per KD-6)
              │
              ▼
     ┌──────────────────────────┐
     │ Tarjan SCC (size ≥ 2)    │  ← KD-6 cycle definition
     └──────────────────────────┘
              │
              ▼
     for each SCC of size ≥ 2:
       for pkg in SCC:
         for root_file in pkg's root files:
           cycles_by_file[root_file] = frozenset(SCC)
              │
              ▼
     return MappingProxyType({
       file_name: frozenset(packages_in_its_cycle)
       for each root file participating
     })
              │
              ▼
     LintEngine.run() snapshots into
     self._current_import_cycles
              │
              ▼
     _build_file_ctx threads into
     FileLintContext.import_cycles
              │
              ▼
     check_package_no_import_cycle:
       if ctx.import_cycles is None: return
       cycle_pkgs = ctx.import_cycles.get(ctx.file.name)
       if cycle_pkgs is None: return  # not in any cycle
       ctx.emit(
         violation_kind="package/no-import-cycle",
         params={
           "file": ctx.file.name,
           "package": ctx.file.package,
           "cycle_packages": sorted(cycle_pkgs),  # via _safe_for_stderr + 500-char cap
         },
       )
```

**Phase 0 verification points** (executed BEFORE writing the accumulator):

1. Run `buf lint --error-format=json <fixture>` against each candidate fixture; capture emission shape — does buf emit one finding per cycle, per file, or per package? PD-6 binds to per-file; Phase 0 confirms.
2. Run buf against a transitive-cycle fixture (cycle routes through vendor) — does buf emit on user's root files? PD-7 binds to "any root participates"; Phase 0 confirms.
3. Inspect buf's BASIC rule list: is `PACKAGE_NO_IMPORT_CYCLE` in `recommended` + `default` at ERROR? PD-8 direction is yes; Phase 0 confirms.
4. Capture buf's emission ORDER on a co-fire fixture (cycle + same-directory + same-package together) — does buf emit `PACKAGE_NO_IMPORT_CYCLE` alphabetically between `PACKAGE_DIRECTORY_MATCH` and `PACKAGE_SAME_DIRECTORY`? Bind tuple position in `package.py`'s `RULES` to match.

If any Phase 0 verification falsifies a direction-of-travel binding, re-open the decision with the empirical observation as the anchor.

### U2 + U3 Multi-Family Parity Harness Extension

```
tests/parity/conftest.py
├── existing
│   ├── _FAMILY_PROTO_TO_BUF  (union of R7 + R8/R8b)
│   ├── _FAMILY_RULE_IDS      (union)
│   └── _PARITY_EXCEPTIONS    (existing entry for file/syntax-specified explicit_proto2)
└── D6e additions (no signature change to assert_parity_multi_file)
    ├── _D6E_FIELD_NOT_REQUIRED_INCLUSION = frozenset({...fixture stems...})
    ├── _D6E_FIELD_NOT_REQUIRED_PROTO_TO_BUF = {...}
    ├── _D6E_FIELD_NOT_REQUIRED_RULE_IDS = frozenset({"field/not-required"})
    ├── _D6E_PACKAGE_NO_IMPORT_CYCLE_INCLUSION = frozenset({...})
    ├── _D6E_PACKAGE_NO_IMPORT_CYCLE_PROTO_TO_BUF = {...}
    ├── _D6E_PACKAGE_NO_IMPORT_CYCLE_RULE_IDS = frozenset({"package/no-import-cycle"})
    ├── _FAMILY_PROTO_TO_BUF |= _D6E_* dicts        (union extension; 1 line each)
    ├── _FAMILY_RULE_IDS |= _D6E_* frozensets       (union extension; 1 line each)
    └── _PARITY_EXCEPTIONS[("field/not-required", "proto2_extend_block_required")]
        = ("protokit_looser", "engine walker at engine.py:841-916 does not iterate fd.extensions_by_name; resolves with D6f+ walker extension")
```

## Implementation Units

- [ ] **Unit 1: UX Philosophy Revision + `proto2-strict` activation + `file/syntax-specified` WARNING demotion**

**Goal:** Formalize KD-1 inverted philosophy, activate the `proto2-strict` profile name (downstream-validated by U2's rule body declaring it), demote `file/syntax-specified` from ERROR to WARNING in `recommended` + `default`. Audit pass on D6a–D6c rules (documentation-only, no code changes outside file.py).

**Requirements:** R1, R2, R3, R4, R4b.

**Dependencies:** None (lands atomically with U2 per PD-2). U2 follows in the same commit.

**Files:**
- Modify: `src/protokit/schema/lint/rules/file.py` — severity ERROR → WARNING at line 61; update module docstring + function docstring to reference R4b demotion + KD-1 + KD-2 + migration recipe pointer
- Modify: `README.md` — Schema Linting section header + Profile table (around `README.md:549-555`): add `proto2-strict` row with opt-in framing; verify all severity-language updated to reflect WARNING demotion for `file/syntax-specified`; **add the `POSITIONING_STATEMENT`** (defined in U4 canonical headline phrasing block) to the Schema Linting section header so the parity-coverage-vs-defaults distinction is visible before any rule-by-rule detail (Product-lens F1 resolution: name the bet explicitly).
- Modify: `src/protokit/schema/lint/rules/__init__.py` — BUILTIN_PACKS docstring (around `:17-78`): add KD-1 philosophy principle line + KD-11 per-syntax-version profile pattern reference + **the `POSITIONING_STATEMENT` substring** (single source line per [[presence-ratchet-test-pattern-for-prose-substrings-2026-05-14]] rule 5; pins the "parity at coverage, ergonomics at defaults" framing in source-of-truth)
- Modify: `CHANGELOG-DRAFT.md` — append U1 staging content per [[dormant-code-changelog-draft-staging-delivery-boundary-2026-05-17]]
- Modify: `TODOS.md` — document the N=3/M=8-weeks PL-4 forcing-function default (PD-11) in a brief subsection; do NOT remove D6e+ backlog items yet (U4 handles)
- Create: `tests/test_uxd_philosophy_principle_presence_ratchet.py` — line-anchored regex presence ratchet for KD-1 principle text in `BUILTIN_PACKS` docstring + `CHANGELOG-DRAFT.md` AND the `POSITIONING_STATEMENT` substring in BUILTIN_PACKS docstring + README (resolves Product-lens F1); single-source-line substrings per discipline rule 5
- Test: `tests/schema/lint/rules/test_file.py` — add WARNING-severity assertion + override-back-to-ERROR test (extends existing test class)
- Test: verify `tests/parity/conftest.py:124-135` `_PARITY_EXCEPTIONS` entry posture for `("file/syntax-specified", "explicit_proto2")` still asserts `"protokit_stricter"` correctly at WARNING level (rule still fires; just at lower severity). No edit expected; verify pass.

**Approach:**
- Severity demotion is a 1-line change at `file.py:61` (`LintSeverity.ERROR` → `LintSeverity.WARNING`).
- Module + function docstring updates: explain WHY (pragmatic-not-dogmatic per KD-2), reference R4b + migration recipe, point at D6f+ for any walker-extension follow-ups (none required for this rule).
- README profile table: add row `proto2-strict | 1 rule (field/not-required) | opt-in proto2-specific strict checks`. Order: `essentials` / `recommended` / `default` / `proto2-strict` / aliases. Snippet shown as `--profile proto2-strict` or `[tool.protokit.lint] profile = ["default", "proto2-strict"]` — per [[changelog-readme-snippet-fixture-byte-equivalence-2026-05-21]], either reference a committed fixture or commit one.
- BUILTIN_PACKS docstring addition: ONE-LINE pin: `"D6e KD-1: protokit-UX overrides buf-parity when they conflict; proto2-specific strict rules ship in opt-in proto2-strict profile."` — passes presence-ratchet single-line discipline.
- The brainstorm explicitly says U1 ships as ONE atomic commit with U2 per CONV-C. The U1 surface is "profile name + philosophy framing + demotion"; U2 supplies the rule body. Together they form one feat commit per PD-2.

**Execution note:** No special posture — this is straightforward documentation + a 1-line severity flip + ratchet test addition. Standard implementation order.

**Patterns to follow:**
- `src/protokit/schema/lint/rules/file.py` existing module docstring shape (already documents the buf-parity divergence in lines 1-32 — extend, do not replace).
- `tests/test_changelog_delivery_presence_ratchet.py:1-100` for presence-ratchet test pattern (line-anchored regex via Pattern A).
- D6c CHANGELOG section in `CHANGELOG.md` for "Added" + "Changed" subsection conventions.

**Test scenarios:**
- Happy path: `file/syntax-specified` fires at WARNING (not ERROR) in `recommended` + `default` on a proto2 implicit-syntax fixture. Assert `LintSeverity.WARNING` on the emitted finding.
- Happy path: `file/syntax-specified` does NOT fire on a proto3 file with explicit `syntax = "proto3";`.
- Happy path: KD-1 principle presence ratchet test passes (line-anchored regex matches `BUILTIN_PACKS` docstring).
- Happy path: README profile table contains `proto2-strict` row (visual verification + per-doc test if there's an existing README ratchet).
- Edge case: user re-promotes `file/syntax-specified` to ERROR via `[tool.protokit.lint.severities] "file/syntax-specified" = "error"` — assert finding emitted at ERROR severity. (Per [[migration-recipe-severity-aware-template-reuse-2026-05-21]] mechanical verification step.)
- Edge case: user disables `file/syntax-specified` via `[tool.protokit.lint.severities] "file/syntax-specified" = "info"` — assert finding emitted at INFO severity (suppressed by default `--min-severity warning` floor in `recommended` profile).
- Edge case: existing `_PARITY_EXCEPTIONS` entry for `("file/syntax-specified", "explicit_proto2")` still asserts `protokit_stricter` posture correctly at WARNING (rule still emits; protokit's emission set is still strictly larger than buf's).
- Edge case: existing `tests/parity/test_parity_file.py` for `file/syntax-specified` continues to pass with WARNING posture.
- Integration: `--profile proto2-strict` BEFORE U2 rule body lands → exit 2 with `unknown-profile`; AFTER U2 → exit 0 with zero findings on a proto3 fixture. (This integration test ships in U2's commit since U1+U2 are atomic.)

**Verification:**
- `git grep "LintSeverity.ERROR" src/protokit/schema/lint/rules/file.py` returns zero matches in the rule decorator.
- KD-1 presence ratchet passes.
- Existing `file/syntax-specified` test suite passes with adjusted severity assertions.
- Existing parity gate for `file/syntax-specified` passes.

---

- [ ] **Unit 2: `field/not-required` rule + new `field` pack + parametrized CLI dedup consolidation**

**Goal:** Implement the deferred `buf:FIELD_NOT_REQUIRED` rule per SUPERSEDED brainstorm UR-6. Proto2-only; `proto2-strict` profile; ERROR severity. Documented extend-block divergence asterisked in three sites per KD-10 + CONV-F. NEW `field` rule pack home per PD-4. The parametrized CLI dedup test consolidation per PD-9 lands here (third-instance trigger).

**Requirements:** R5 (rule body + EV outcomes + extend-block divergence), plus KD-13 + KD-14 (CLI dedup consolidation + landing site).

**Dependencies:** U1 (must land atomically per PD-2 — same feat commit covers both U1 and U2).

**Files:**
- Create: `src/protokit/schema/lint/rules/field.py` — new pack; single rule `check_field_not_required` with `RULES = (check_field_not_required,)`; module docstring mirrors `file.py` shape including the four-site divergence documentation per [[buf-parity-divergence-documentation-discipline-2026-05-13]] (sites 1 + 2)
- Modify: `src/protokit/schema/lint/rules/__init__.py` — add `from protokit.schema.lint.rules import field` import; append `"protokit.schema.lint.rules.field"` to `BUILTIN_PACKS` tuple at `:164-173`; update BUILTIN_PACKS docstring substring ratchets (will be re-touched in U4 for the "26 of 26" headline)
- Create: `tests/schema/lint/rules/test_field.py` — full rule test class; derive `_ALL_FIELD_RULE_IDS = frozenset(fn._lint_spec.rule_id for fn in RULES)` per [[rule-pack-extension-ssot-rule-ids-and-test-class-naming-2026-05-12]]; use `catch_exceptions=False` on every CliRunner.invoke per [[clirunner-catch-exceptions-false-explicit-discipline-2026-05-21]]
- Modify: `tests/schema/lint/test_builtin_packs.py` — update membership pin at `:71-104` to include `"protokit.schema.lint.rules.field"`; update presence-ratchet substrings at `:121-171` to include `"FIELD_NOT_REQUIRED"` (will be re-touched in U4 for the headline numerator)
- Create: `tests/parity/fixtures/field/not-required/proto2_required.proto` — bad fixture (proto2 file with `required` field)
- Create: `tests/parity/fixtures/field/not-required/proto2_optional.proto` — good fixture (proto2 file with `optional` field; no fire)
- Create: `tests/parity/fixtures/field/not-required/proto3_field.proto` — proto3 baseline (no fire; syntax-skip branch)
- Create: `tests/parity/fixtures/field/not-required/proto2_extend_block_required.proto` — divergence specimen (buf fires; protokit does not)
- Create: `tests/parity/snapshots/field/not-required/{proto2_required,proto2_optional,proto3_field,proto2_extend_block_required}.json` — buf v1.69.0 NDJSON snapshots (commit BEFORE writing protocol logic per [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]])
- Create: `tests/parity/test_parity_field.py` — single-file parity gate using `assert_parity` (mirrors `tests/parity/test_parity_file.py` pattern)
- Modify: `tests/parity/conftest.py` — add `_PARITY_EXCEPTIONS` entry `("field/not-required", "proto2_extend_block_required"): ("protokit_looser", "engine walker at engine.py:841-916 does not iterate fd.extensions_by_name; resolves with D6f+ walker extension")`. Family-aware constants added if multi-file path is chosen (Phase 0 decides — single-file is simpler; multi-file only if EV-4 binding forces multi-file fixtures).
- Create: `tests/schema/lint/test_cli_rule_pack_dedup.py` — parametrized consolidation per PD-9; iterates `BUILTIN_PACKS`; per-pack `param` dict carries `module_name + fixture_sources + expected_exit_code`. Replace files below.
- Delete: `tests/schema/lint/test_cli_rule_pack_dedup_post_d6c.py`
- Delete: `tests/schema/lint/test_cli_rule_pack_dedup_post_d6d.py`
- Modify: `CHANGELOG-DRAFT.md` — append U2 content (Added subsection draft; will be folded by U4)
- Create: `docs/solutions/best-practices/proto2-strict-profile-activation-pattern-2026-05-XX.md` — ce:compound capture during U1+U2 boundary (NOT during write — at boundary)
- Modify: `tests/schema/lint/test_engine_*.py` (if direct `FileLintContext(...)` construction exists) — verify all paths auto-pass via `= None` defaults; no edits expected.

**Approach:**

**Phase 0 of U2** (executed BEFORE writing the rule body):
1. Run `buf lint --error-format=json <fixture>` against each of the four candidate fixtures + capture NDJSON snapshots. Verify byte-equivalent buf v1.69.0 output for proto2_required, proto2_optional, proto3_field, proto2_extend_block_required.
2. Bind EV-1 (edition LEGACY_REQUIRED 3-outcome matrix): run buf against an edition file with LEGACY_REQUIRED feature flag; record outcome (fire / no-fire / different rule_id). If buf fires, decide whether protokit's rule body needs an edition-specific branch.
3. Bind EV-3 (group-typed required): run buf against a proto2 group-typed required field; record buf's output. Per SUPERSEDED brainstorm, buf treats group like message; verify.
4. Bind EV-4 (multi-file proto2+proto3 mix): run buf against a project with both syntaxes; record that buf fires only on proto2 files (matches PD-4 rule body's `fdp.syntax != ""` early return).
5. Decide single-file vs multi-file parity test shape based on EV-1/EV-3/EV-4 fixture count. Default to single-file (`test_parity_field.py` mirroring `test_parity_file.py`); promote to multi-file only if EV-4 forces multi-file fixtures.

**Rule body** (UR-6 from SUPERSEDED brainstorm; bind verbatim):
```python
fdp = descriptor_pb2.FileDescriptorProto()
ctx.file.CopyToProto(fdp)
if fdp.syntax != "":  # skip non-proto2 (proto3 + editions)
    return
if ctx.field.label == proto_descriptor.FieldDescriptor.LABEL_REQUIRED:
    ctx.emit(violation_kind="field/not-required", params={"field_name": ctx.field.name})
```

**Four-site divergence documentation** per [[buf-parity-divergence-documentation-discipline-2026-05-13]]:
1. **Module docstring** at `src/protokit/schema/lint/rules/field.py:1-N` — `buf:FIELD_NOT_REQUIRED` parity claim + extend-block divergence + corrected `engine.py:841-916` citation + forward-pointer to D6f+ walker extension.
2. **Function docstring** for `check_field_not_required` — restate divergence + remediation guidance.
3. **`message_template`** on `@lint_rule` decorator — user-facing template: `"Field {field_name!r} is declared required in a proto2 message. The required label is a known footgun; declare as optional and validate at the application layer."` Per [[lint-rule-message-templates-must-not-recommend-actions-that-trigger-siblings-2026-05-13]] — "declare as optional" does not trigger sibling proto2-strict rules (no `naming/snake-case` collision since field name is unchanged); verify at implementation.
4. **Test method docstrings** in `tests/schema/lint/rules/test_field.py` — separate test methods for buf-parity branch (`test_proto2_required_fires_byte_equivalent_to_buf`) and protokit divergence branch (`test_extend_block_required_does_not_fire_documented_divergence_engine_py_841_916`).

**Parametrized CLI dedup consolidation** per PD-9:
- Read `BUILTIN_PACKS` at test-module import time.
- For each pack, parametrize `(module_name, fixture_sources_dict)` where `fixture_sources_dict` maps proto-file-name to source string. Defaults: single trivial proto3 source (`_PROTO_TRIVIAL`).
- Per-pack overrides:
  - `package`: two-package source (R8/R8b needs `package foo;` + `package bar;` files to fire). After U3 lands, extends to include cycle-fixture source (an A↔B cycle proto).
  - `field`: proto2 source with `required` field (so `field/not-required` actually has something to evaluate when `--profile proto2-strict`).
- Each parametrized case calls `compile_sources_to_descriptor_set(...)` (the existing SSOT at `_cli_dedup_helpers.py:27-82`), invokes `protokit lint --no-config --rule-pack=<module> --profile <name> <descriptor_set>` with `catch_exceptions=False`, asserts `result.exception is None` and `exit_code == 0` (or expected exit code for `field` pack with `--profile proto2-strict` if it would naturally fire).
- Total LOC: ~60 (vs ~540 currently across the two per-flip files).

**Execution note:** Test-first: write the four parity-gate test scenarios + the unit test class skeleton, run them red, then write the rule body — surfaces helper bugs at implementation time per [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]].

**Patterns to follow:**
- `src/protokit/schema/lint/rules/file.py` — single-rule pack shape + module docstring divergence-documentation pattern.
- `tests/parity/test_parity_file.py` — single-file parity gate exemplar.
- `tests/schema/lint/rules/test_file.py` — rule-pack test class shape.
- D6a U6 `file/syntax-specified` divergence treatment for the four-site protocol (specimen #1).

**Test scenarios:**
- **Happy path:** proto2 file with `required` field fires `field/not-required` at ERROR severity under `--profile proto2-strict`. Pin `rule_id`, `severity`, `location_kind`, `params["field_name"]` per [[worked-example-multi-scenario-test-class-template-2026-05-21]].
- **Happy path:** proto2 file with `optional` field does NOT fire under `--profile proto2-strict`.
- **Happy path:** proto3 file does NOT fire under `--profile proto2-strict` (early-return on `fdp.syntax != ""`).
- **Happy path:** editions file does NOT fire under `--profile proto2-strict` (`fdp.syntax == "editions"`, not empty).
- **Happy path:** proto2 required field shows ZERO `field/not-required` findings under `--profile recommended`.
- **Happy path:** proto2 required field shows ZERO `field/not-required` findings under `--profile default`.
- **Happy path:** `--profile proto2-strict` exits 0 (not 2 `unknown-profile`) — verifies U1+U2 atomic landing produces a valid profile.
- **Edge case:** proto2 required field can be demoted via `[tool.protokit.lint.severities] "field/not-required" = "warning"` — fires at WARNING, exits 0 with default `--max-warnings` (per [[migration-recipe-severity-aware-template-reuse-2026-05-21]] mechanical verification).
- **Edge case (EV-3 binding):** proto2 group-typed required field — outcome bound at Phase 0; assert per buf v1.69.0.
- **Edge case (EV-1 binding):** edition file with LEGACY_REQUIRED feature flag — outcome bound at Phase 0.
- **Edge case (EV-4 binding):** mixed proto2+proto3 project — rule fires only on proto2 files.
- **Documented divergence (EV-2 PRE-DECIDED):** proto2 extend-block with required field — protokit does NOT fire; buf v1.69.0 DOES fire. Assert via `_PARITY_EXCEPTIONS` posture `protokit_looser`. Test method docstring cites `engine.py:841-916` + forward-points to D6f+ walker extension.
- **Error path:** `--profile nonexistent` exits 2 with `unknown-profile` (verifies the CLI gate at `cli.py:1005-1037`).
- **Error path:** invalid `[severities]` value `"off"` exits 2 (per [[migration-recipe-severity-aware-template-reuse-2026-05-21]] — `"off"` is invalid; R9b still deferred).
- **Integration:** parity gate against buf v1.69.0 NDJSON snapshots — byte-equivalent on the three non-divergent fixtures + posture-asserted on the divergence fixture.
- **Integration:** BUILTIN_PACKS membership — `field` pack registered, has 1 rule (`field/not-required`).
- **Integration:** parametrized CLI dedup test passes for every pack in BUILTIN_PACKS including the new `field` pack. Three deleted files (`test_cli_rule_pack_dedup_post_d6c.py` + `_post_d6d.py` + the never-created `_post_d6e.py`) absent from the working tree.
- **Integration:** presence-ratchet — BUILTIN_PACKS docstring mentions `"field"` pack + `"FIELD_NOT_REQUIRED"` substring (single-source-line; verified pre-commit).

**Verification:**
- `git ls-files | grep test_cli_rule_pack_dedup` returns ONE file (`test_cli_rule_pack_dedup.py`), not three.
- `pytest tests/parity/test_parity_field.py -v` passes (4 fixtures, 4 assertions; 1 divergence posture).
- `pytest tests/schema/lint/rules/test_field.py -v` passes (full rule scenarios).
- `protokit lint --no-config --profile proto2-strict <proto2_required.descset>` exits 1 (ERROR finding emitted).
- `protokit lint --no-config --profile recommended <proto2_required.descset>` exits 0 (no `field/not-required` finding).
- Four-site divergence documentation visible: module docstring + function docstring + `message_template` mentions divergence + at least one test method docstring cites `engine.py:841-916`.

---

- [ ] **Unit 3: `package/no-import-cycle` rule + Tarjan SCC pre-walk accumulator**

**Goal:** Implement the 26th buf BASIC rule (`buf:PACKAGE_NO_IMPORT_CYCLE`) via package-level cycle detection. Algorithm: Tarjan SCC pre-walk extending D6c's Arch-D pattern per PD-5. Per-file emission via package→root-files fan-out per PD-6. Scope: fire if any root file participates in an SCC per PD-7. Lives in the existing `package` pack alongside R8/R8b. New `FileLintContext.import_cycles` field per PD-8.

**Requirements:** R6.

**Dependencies:** U1 + U2 landed (BUILTIN_PACKS has new `field` pack; profile machinery has `proto2-strict` registered downstream).

**Files:**
- Modify: `src/protokit/schema/lint/engine.py` — add `_build_import_graph_accumulator` method near `_build_directory_package_accumulator` at `:707-835`; declare `self._current_import_cycles: Mapping[str, frozenset[str]] | None = None` in `__init__` at `:200-233`; invoke accumulator in `run()` between Steps 3.5b and 4 at `:529-544`; clear in `finally` at `:577-594`; thread into `FileLintContext` via `_build_file_ctx` at `:1030-1056`
- Modify: `src/protokit/schema/lint/model.py` — add `import_cycles: Mapping[str, frozenset[str]] | None = None` field to `FileLintContext` at `:1045-1138` (with `= None` default — matches `directory_packages` precedent at `:1131`)
- Modify: `src/protokit/schema/lint/rules/package.py` — add `check_package_no_import_cycle` callable; append to `RULES` tuple at the position bound at Phase 0 (likely between `package/directory-match` and `package/same-directory` per feasibility F4); module docstring updated to reference KD-6 + the new pre-walk accumulator
- Create: `tests/schema/lint/rules/fixtures/package_no_import_cycle/_buf_smoke/two_node_cycle/{a.proto, b.proto, buf.yaml}` — direct A↔B cycle (a imports b; b imports a; both root files)
- Create: `tests/schema/lint/rules/fixtures/package_no_import_cycle/_buf_smoke/three_node_cycle/{a.proto, b.proto, c.proto, buf.yaml}` — 3-node A→B→C→A
- Create: `tests/schema/lint/rules/fixtures/package_no_import_cycle/_buf_smoke/self_import_not_cycle/{a.proto, buf.yaml}` — self-import (a imports a — invalid proto syntax, may need different shape: single-file with no imports + alternative inside-package import-to-self if descriptor permits; Phase 0 confirms)
- Create: `tests/schema/lint/rules/fixtures/package_no_import_cycle/_buf_smoke/no_cycle_baseline/{a.proto, b.proto, buf.yaml}` — linear A→B
- Create: `tests/schema/lint/rules/fixtures/package_no_import_cycle/_buf_smoke/root_vendor_mixed_cycle/{a.proto, vendor/v.proto, buf.yaml}` — user A imports vendor V; vendor V imports user A (user-fixable via the root file)
- Create: `tests/schema/lint/rules/fixtures/package_no_import_cycle/_buf_smoke/recorded/<fixture_name>.json` — buf v1.69.0 NDJSON snapshots (commit BEFORE writing accumulator)
- Create: `tests/parity/test_parity_package_no_import_cycle.py` — multi-file parity gate (mirrors `tests/parity/test_parity_package_directory.py` D6c U3 exemplar)
- Create: `tests/schema/lint/test_buf_smoke_assumptions_package_no_import_cycle.py` — buf re-invocation
- Create: `tests/schema/lint/test_buf_smoke_recorded_checksums_package_no_import_cycle.py` — SHA-256 pin on snapshots
- Modify: `tests/parity/conftest.py` — add `_D6E_PACKAGE_NO_IMPORT_CYCLE_INCLUSION` + `_PROTO_TO_BUF` + `_RULE_IDS` family constants; extend `_FAMILY_PROTO_TO_BUF` + `_FAMILY_RULE_IDS` union constants by 1 line each per [[family-aware-partition-pattern-multi-family-parity-harness-2026-05-19]]
- Create: `tests/schema/lint/test_engine_import_graph_accumulator.py` — accumulator unit tests (empty pool, single-file, 2-node cycle, 3-node cycle, multiple disjoint cycles, large graph perf smoke)
- Modify: `tests/schema/lint/rules/test_package.py` — add U3 rule test class with full scenarios
- Modify: `tests/schema/lint/test_cli_rule_pack_dedup.py` — extend `package` pack parametrized case with cycle-fixture source variant (per PD-9 — consolidation already lives here from U2)
- Modify: `tests/schema/lint/test_builtin_packs.py` — update `package` pack rule count from 4 → 5; update presence-ratchet substring to include `"PACKAGE_NO_IMPORT_CYCLE"` (single-source-line)
- Modify: `CHANGELOG-DRAFT.md` — append U3 content
- Create: `docs/solutions/best-practices/tarjan-scc-import-cycle-detection-pre-walk-2026-05-XX.md` — ce:compound capture during U3 boundary; establishes NEW institutional knowledge (no prior cycle-detection art in protokit)

**Approach:**

**Phase 0 of U3** (executed BEFORE writing the accumulator or the rule body):
1. Run `buf lint --error-format=json <fixture>` against each of the five candidate fixtures + capture NDJSON snapshots.
2. **OQ-1 binding**: inspect buf's output — does it emit one finding per cycle, per file, or per package? Bind PD-6 (per-file via fan-out) or re-open.
3. **OQ-2 binding**: run buf against the `root_vendor_mixed_cycle` fixture — does buf emit on user's root files? Bind PD-7 (any-root-participates) or re-open.
4. **OQ-3 binding**: inspect buf's BASIC rule profile membership — is `PACKAGE_NO_IMPORT_CYCLE` in `recommended` + `default` at ERROR? Bind KD-8.
5. **Co-fire ordering binding**: create a fixture with cycle + same-directory + same-package together; observe buf's emission ORDER; bind `package.py`'s `RULES` tuple position to match alphabetical buf order (likely between `PACKAGE_DIRECTORY_MATCH` and `PACKAGE_SAME_DIRECTORY` per feasibility F4).

**Accumulator implementation** (matches the High-Level Technical Design sketch above):
- Iterate `compile_result.root_files`.
- For each root file, use `ctx.file.CopyToProto(fdp)` + `fdp.dependency` to extract import filenames (no direct `fd.dependencies` accessor exists — `rules/imports.py:85-91` is the precedent).
- For each `dep_name` in `fdp.dependency`, resolve via `compile_result.pool.FindFileByName(dep_name)` to get `dep_fd.package`. Collect edges `source_pkg → dep_pkg` (deduplicate multi-file P→Q imports per KD-6).
- Run Tarjan SCC over the directed graph (use `graphlib` or hand-implement Tarjan — graphlib has `TopologicalSorter` for DAG case but not SCC; hand-implement Tarjan is small ~30 LOC).
- For each SCC of size ≥ 2, fan out to per-file view: for each package in the SCC, for each root file in that package, set `cycles_by_file[root_file_name] = frozenset(SCC_packages)`.
- Wrap with `MappingProxyType` per [[dual-view-prewalk-accumulator-cross-file-rule-dispatch-2026-05-19]] discipline.
- Return single-view (per PD-8 — no dual-view needed absent sibling consumer rule).
- Use `posixpath` for path operations per [[pureposixpath-for-proto-descriptor-file-stem-2026-05-12]].

**Rule body** for `check_package_no_import_cycle`:
- Early return if `ctx.import_cycles is None` (accumulator returned None for empty pool).
- Look up `ctx.import_cycles.get(ctx.file.name)`; early return if None (file not in any cycle).
- Emit one finding with `params={"file": ctx.file.name, "package": ctx.file.package, "cycle_packages": sorted(cycle_pkgs)}`. Apply `_safe_for_stderr` + 500-char cap to package-name params per `rules/package.py:284-292` precedent.

**Fixture authoring** per [[programmatic-proto-fixture-builder-multi-file-rule-family-2026-05-17]]: static hand-authored fixtures (5 scenarios = below the programmatic-builder threshold). Use UNIQUE message names across files in the same package to avoid stub collision. Use POSIX path separators in `buf.yaml` per `[[matcher-backend-path-resolution-skew-silently-empties-output-2026-05-02]]`.

**Execution note:** Phase 0 verification + buf snapshot recording happens BEFORE the accumulator is written. Then accumulator unit tests (red), then accumulator implementation (green), then rule body, then parity gate.

**Patterns to follow:**
- `src/protokit/schema/lint/engine.py:707-835` — `_build_directory_package_accumulator` (D6c Arch-D pattern; same shape).
- `src/protokit/schema/lint/rules/package.py:284-292` — R8/R8b cross-file rule structure + `_safe_for_stderr` + 500-char cap discipline.
- `tests/parity/test_parity_package_directory.py` — multi-file parity gate exemplar (D6c U3).
- `tests/schema/lint/test_engine_directory_package_accumulator.py` — accumulator unit test pattern.

**Test scenarios:**
- **Phase 0 verification (executed BEFORE implementation):**
  - Capture buf v1.69.0 NDJSON snapshots for the 5 candidate fixtures.
  - Verify OQ-1/OQ-2/OQ-3 outcomes bind PD-6/PD-7/PD-8 or trigger re-open.
  - Capture co-fire ordering; bind RULES tuple position.
- **Happy path:** 2-node cycle (A↔B) emits one finding per root file (2 findings total) at ERROR.
- **Happy path:** 3-node cycle (A→B→C→A) emits one finding per root file (3 findings total).
- **Happy path:** linear chain (A→B→C, no cycle) emits zero findings.
- **Happy path:** self-import (a imports a, IF descriptor permits) emits zero findings per KD-6 size-≥2 requirement.
- **Happy path:** no-imports baseline (single file, no imports) emits zero findings.
- **Edge case:** empty pool (no root files) → accumulator returns None → rule emits zero findings.
- **Edge case:** cycle entirely within vendor (no root file participates) emits zero findings per PD-7.
- **Edge case:** root+vendor mixed cycle (user A imports vendor V; vendor V imports user A) emits finding on user A — user-fixable per PD-7.
- **Edge case:** multiple disjoint cycles in same compile — each cycle reported independently.
- **Edge case:** cycle of size 4+ exercises Tarjan's lowlink behavior (not just back-edge detection).
- **Edge case:** package with multiple root files in one cycle — each root file gets its own finding (per-file emission per PD-6).
- **Error path:** malformed import (missing `dep_fd`) handled gracefully via pool-lookup guard; no exception bubbles.
- **Documented co-fire:** cycle + same-directory + same-package fixture — `package/no-import-cycle` finding appears in expected position per Phase 0 binding (likely between `package/directory-match` and `package/same-directory`).
- **Integration:** parity gate — byte-equivalent buf v1.69.0 NDJSON output on all 5 fixtures (4 non-divergent + 1 baseline).
- **Integration:** BUILTIN_PACKS — `package` pack now has 5 rules; presence-ratchet substring `"PACKAGE_NO_IMPORT_CYCLE"` matches.
- **Integration:** parametrized CLI dedup test passes for `package` pack with new cycle-fixture parametrized case.
- **Integration:** accumulator dual-view immutability — `MappingProxyType` wrapping verified; `frozenset` innermost.
- **Integration:** `FileLintContext.import_cycles` field accessible from rule body; defaults to `None` when accumulator skipped.
- **Performance smoke:** cycle detection on 100-file pool with no cycles completes in <100ms (sanity gate; not a hard SLA).

**Verification:**
- `protokit lint --no-config <two_node_cycle.descset>` emits 2 findings, exit 1.
- `protokit lint --no-config <no_cycle_baseline.descset>` emits 0 findings, exit 0.
- `pytest tests/parity/test_parity_package_no_import_cycle.py -v` passes.
- `pytest tests/schema/lint/test_engine_import_graph_accumulator.py -v` passes.
- `pytest tests/schema/lint/rules/test_package.py::TestPackageNoImportCycle -v` passes.
- `git grep "PACKAGE_NO_IMPORT_CYCLE" src/protokit/schema/lint/rules/` shows the new rule's `source_spec` line — feeds U4's Layer D grep count.
- New `docs/solutions/best-practices/tarjan-scc-import-cycle-detection-pre-walk-*.md` exists.

---

- [ ] **Unit 4: Delivery Boundary (0.6.0)**

**Goal:** Fold U1-U3 staged CHANGELOG-DRAFT content into CHANGELOG, bump pyproject `0.5.0 → 0.6.0`, refresh README + BUILTIN_PACKS + TODOS.md to reflect the "26 of 26 buf v1.69.0 BASIC rules" closing headline, add D6e presence-ratchet, verify bump-contract ratchet substrings still hold (no `_LINT_JSON_SCHEMA_VERSION` bump per KD-9), apply the canonical stale-text sweep, capture the third-instance-trigger ce:compound learning per PD-9.

**Requirements:** brainstorm U4 block (KD-9 + KD-13 + KD-14 + delivery-boundary discipline).

**Dependencies:** U1, U2, U3 all complete.

**Files:**
- Modify: `pyproject.toml` — `version = "0.5.0"` → `version = "0.6.0"`
- Modify: `CHANGELOG.md` — fold `CHANGELOG-DRAFT.md` content into `### D6e — buf BASIC closure + UX philosophy revision (0.6.0)` section with 5 sub-sections per [[builtin-packs-expansion-changelog-migration-recipe-structure-2026-05-18]]
- Modify (or Delete + recreate empty): `CHANGELOG-DRAFT.md` — reset to staging-empty per [[dormant-code-changelog-draft-staging-delivery-boundary-2026-05-17]]
- Modify: `README.md` — Schema Linting section numerator refresh: `"25 of 26"` → the canonical numerator substring (defined below) + the divergence clause (no "deferred to a future X" timeline framing per Product-lens F2) + the positioning statement (per Product-lens F1) per KD-9. Verify all numerator claim sites at `README.md:484-487`, `:552`, `:586-589`, `:678`, `:686-688`.

**Canonical headline phrasing (byte-identical across README, BUILTIN_PACKS docstring, CHANGELOG, CLI `--help` epilog):**
- `CANONICAL_NUMERATOR_SUBSTRING = "26 of 26 buf v1.69.0 BASIC rules"` (single source line; presence-ratchet candidate per [[presence-ratchet-test-pattern-for-prose-substrings-2026-05-14]] rule 5)
- `DIVERGENCE_CLAUSE = "(with one documented divergence on extend-block-required-fields; protokit's engine walker at engine.py:841-916 does not iterate fd.extensions_by_name or Message.extensions_by_name)"` — NO "deferred to a future X" timeline framing per Product-lens F2 (vague forward-promises erode trust over time when they outlast their stated window). The divergence is documented as a present-tense architectural fact; resolution timing lives in TODOS.md with a concrete user-report-driven trigger ("first user report of a missed proto2 extend-block-required field that buf catches → prioritize for the next delivery"), NOT in the headline copy.
- `POSITIONING_STATEMENT = "protokit ships buf's 26 BASIC rules; default severities reflect Python-protobuf-developer ergonomics, not buf's defaults (see proto2-strict for opt-in proto2 strictness)."` — single source line; pinned via presence-ratchet alongside the numerator substring. Resolves Product-lens F1 (KD-1-vs-26/26-headline latent tension) by naming the bet explicitly: protokit claims parity at COVERAGE (26 of 26 rules implemented), not at DEFAULTS (severity placements diverge by design). Lives in BUILTIN_PACKS docstring + README Schema Linting section header.
- U4 audit gate: `git grep "26 of 26 buf v1.69.0 BASIC rules"` returns ≥3 matches (one per claim site: README + BUILTIN_PACKS docstring + CHANGELOG); `git grep "protokit ships buf's 26 BASIC rules"` returns ≥2 matches (README + BUILTIN_PACKS docstring); secondary Layer D audit per [[audit-wire-format-before-claiming-sibling-parity-2026-05-03]] separately counts `source_spec="buf:` occurrences in `src/protokit/schema/lint/rules/*.py` and verifies it equals 26.
- Modify: `src/protokit/schema/lint/rules/__init__.py` — BUILTIN_PACKS docstring numerator update at `:146-150`; verify single-source-line discipline for the new substring; KD-9 v1.69.0 qualifier prominent
- Modify: `src/protokit/schema/lint/cli.py` — `--help` epilog at `:274-321` — remove any "deferred to D6e" prose; add active framing for `proto2-strict` profile if discoverability prose exists for profiles
- Modify: `TODOS.md` — remove `PACKAGE_NO_IMPORT_CYCLE` + `FIELD_NOT_REQUIRED` from D6e+ backlog (lines 213-244 area); update headline narrative (lines 93-112) from `"25 of 26"` to the canonical numerator substring `"26 of 26 buf v1.69.0 BASIC rules"`; add D6f+ backlog items: (a) walker extension for both `fd.extensions_by_name` AND `Message.extensions_by_name` (file-level + nested-message extends) resolving U2's divergence at both surface forms; (b) any audit findings from U1's R4 audit pass with concrete N=3/M=8-weeks PD-11 forcing-function defaults; (c) `LintRuleSpec.parity_note` structured field promotion at specimen #3 trigger per PD-10; (d) any tightened per-item N/M values for specific audit findings (per PD-11 caveat — small-community-size or high-blast-radius findings should tighten the default)
- Modify: `tests/test_changelog_delivery_presence_ratchet.py` — add `DeliveryRatchetSpec(delivery="D6e", version="0.6.0")` at `:71-76`
- Modify: `tests/schema/lint/test_builtin_packs.py` — update three pinned substrings at `:121-171` from D6d era to D6e era: `"26 of 26 buf v1.69.0 BASIC rules"` (or whatever single-source-line phrasing fits), and verify removed `"PACKAGE_NO_IMPORT_CYCLE"` + `"FIELD_NOT_REQUIRED"` from any "deferred to" substrings (they are now landed)
- Verify (no edit expected): `tests/test_builtin_lint_formatter.py:705-760` — `TestBumpContractDocstring` substrings; per KD-9 NO `_LINT_JSON_SCHEMA_VERSION` bump; no new closed-Literal additions; existing substrings should still pass; verify pre-commit
- Stale-text sweep: `git grep -n 'deferred to D6e\|arrives in D6e\|D6e-bound\|forthcoming\|once U[0-9] ships' src/ tests/ docs/ README.md CHANGELOG.md` — apply triage rubric per [[stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12]]
- Create: `docs/solutions/best-practices/near-copy-paste-third-instance-consolidation-trigger-2026-05-XX.md` — ce:compound capture during U4 boundary; codifies the rule for promoting near-copy-paste helpers to shared SSOTs at N=3 instances (resolves the bracketed reference); names the parametrized CLI dedup consolidation as the worked example
- Layer D audit verification (pre-commit): `grep -rn 'source_spec="buf:' src/protokit/schema/lint/rules/ | wc -l` must equal 26 before the CHANGELOG/README claim ships per [[audit-wire-format-before-claiming-sibling-parity-2026-05-03]] Layer D.

**Approach** (7-component boundary commit per [[delivery-boundary-unit-commit-composition-2026-05-14]]):

1. **pyproject version bump**: 1-line edit. Verify via `pytest tests/test_pyproject_version.py` (if it exists; otherwise grep).

2. **CHANGELOG fold** with 5 sub-sections per [[builtin-packs-expansion-changelog-migration-recipe-structure-2026-05-18]]:
   - **Added** subsection:
     - D6e KD-1 hard-inverted UX philosophy principle (protokit-UX overrides buf-parity)
     - `proto2-strict` opt-in profile (initial population: 1 rule, `field/not-required`)
     - `field/not-required` rule (`buf:FIELD_NOT_REQUIRED` parity; proto2-only; ERROR severity in `proto2-strict`; documented extend-block divergence; corrected `engine.py:841-916` walker citation)
     - `package/no-import-cycle` rule (`buf:PACKAGE_NO_IMPORT_CYCLE` parity; package-level cycle detection via Tarjan SCC pre-walk; per-file emission; ERROR severity in `recommended` + `default`)
     - Parametrized CLI dedup test consolidation (3 per-flip files → 1 parametrized file per PD-9; third-instance-trigger codification)
     - New `FileLintContext.import_cycles` field (single-view accumulator output)
   - **Changed** subsection (per [[pre-1.0-version-bump-as-communication-contract-2026-05-14]]; no ceremonial `BREAKING:`):
     - `file/syntax-specified` ERROR → WARNING in `recommended` + `default` per R4b (D6e KD-2 pragmatic-not-dogmatic)
     - Buf-parity headline `"25 of 26 BASIC rules"` → `"26 of 26 buf v1.69.0 BASIC rules (with one documented divergence on extend-block-required-fields)"` per KD-9
   - **Behavior changes (defaults; demotable)** subsection:
     - `file/syntax-specified` now WARNING in default; users with `--max-warnings 0` will notice; users with `--min-severity error` filtering effectively make invisible
     - No other default-profile behavior changes (U2 rule is opt-in; U3 rule is new at ERROR but lands clean on cycle-free projects)
   - **Pre-upgrade migration recipe** subsection (severity-aware per [[migration-recipe-severity-aware-template-reuse-2026-05-21]]; every demotion path empirically verified against minimal fixture before commit; every snippet byte-equivalent to a committed fixture per [[changelog-readme-snippet-fixture-byte-equivalence-2026-05-21]]):
     - **Worst-case math**: enumerate three CI configurations, since the R4b demotion impact varies by `--max-warnings` posture:
       1. **`--max-warnings` unset (default)** — pre-R4b exit was 1 (ERROR present from `file/syntax-specified`); post-R4b exit is 0 because WARNING does not trigger the error-exit AND the warning-count check is skipped when `max_warnings is None`. **This is a silent-CI-pass regression** for pipelines that depended on `file/syntax-specified` being load-bearing-error. Most dangerous case; user must KNOW their CI silently started passing. Remediation: re-promote per migration path #1 below.
       2. **`--max-warnings 0`** — pre-R4b exit was 1 via the ERROR-exit path; post-R4b exit is still 1 via the warning-count > 0 path. Same exit code, but the FAILURE CAUSE has shifted from error-bin to warning-bin, which may change formatter output and bin-distribution that users grep on. Not cosmetic — the failure now competes with other warnings against the count budget.
       3. **`--min-severity error`** — true zero impact (rule effectively invisible).

       Projects opting into `--profile proto2-strict` ALSO see all proto2 `required` fields flagged at ERROR (orthogonal to the R4b axis).
     - **Demotion paths ranked by SITUATION**:
       1. Want explicit ERROR enforcement of `file/syntax-specified`? Pyproject: `[tool.protokit.lint.severities] "file/syntax-specified" = "error"`
       2. Want proto2-strict checks? Pyproject: `[tool.protokit.lint] profile = ["default", "proto2-strict"]`
       3. Want to demote `field/not-required` after opting in? Pyproject: `[tool.protokit.lint.severities] "field/not-required" = "warning"`
       4. Want to demote `package/no-import-cycle`? Pyproject: `[tool.protokit.lint.severities] "package/no-import-cycle" = "warning"` or `... = "info"`
       5. Want to pin to 0.5.0 indefinitely? `pip install protokit==0.5.0`
     - **No pyproject.toml? Minimal stub**:
       ```toml
       [tool.protokit.lint]
       profile = ["default"]

       [tool.protokit.lint.severities]
       "field/not-required" = "warning"
       ```
     - **Accepted-tradeoff scenarios**: proto3-only shops who want strict explicit-syntax declaration → re-promote `file/syntax-specified`; proto2-heavy shops who can't fix all `required` fields immediately → demote `field/not-required` or stay on 0.5.0
     - **Upgrade triage walkthrough**: (1) install 0.6.0 in a branch; (2) run `protokit lint --no-config` against your descriptors; (3) review WARNING vs ERROR distribution; (4) decide on `--profile proto2-strict` opt-in; (5) apply severity overrides per #2 above; (6) merge
   - **Deferred to D6f+** subsection (per [[scope-guardian]] attribution discipline, include ONLY items deferred DURING D6e planning; prior-delivery carry-forwards live in TODOS.md, not in D6e's CHANGELOG):
     - Engine walker extension for BOTH `fd.extensions_by_name` AND `Message.extensions_by_name` (file-level + nested-message extends) — resolves U2's documented extend-block divergence at both surface forms
     - `LintRuleSpec.parity_note` structured field promotion at specimen #3 trigger per PD-10
     - R9b `"off"` severity value support (existing `[severities]` overrides at `"error"`/`"warning"`/`"info"` continue to work; `"off"` remains rejected as invalid input)
     - Any R4 audit findings from U1's audit pass (with concrete N=3/M=8-weeks PD-11 forcing-function defaults; per-item N/M may tighten — small-community-size or high-blast-radius findings should tighten by 2-3x per the PD-11 caveat)

3. **README "26 of 26 v1.69.0" numerator refresh**:
   - Apply Layer D grep audit per [[audit-wire-format-before-claiming-sibling-parity-2026-05-03]]: `grep -rn 'source_spec="buf:' src/protokit/schema/lint/rules/ | wc -l` MUST equal 26 (not 25; not 27) before shipping.
   - Update all README claim sites: `:484-487`, `:552`, `:586-589`, `:678`, `:686-688`.
   - Verify `_BUF_PARITY_PIN = "v1.69.0"` at `src/protokit/schema/lint/cli.py:153` stays unchanged unless empirically re-verified against a newer buf release.
   - Profile table already includes `proto2-strict` row from U1; verify still present + rule count is 1.

4. **BUILTIN_PACKS docstring refresh** at `src/protokit/schema/lint/rules/__init__.py:17-78`:
   - Update numerator substring to the canonical `CANONICAL_NUMERATOR_SUBSTRING` defined above.
   - Add the `DIVERGENCE_CLAUSE` (no "deferred to a future X" timeline framing — present-tense architectural fact only; resolution timing lives in TODOS.md with a concrete user-report-driven trigger per Product-lens F2).
   - Add the `POSITIONING_STATEMENT` as a single source line (resolves Product-lens F1 by naming the bet: parity at COVERAGE, ergonomics at DEFAULTS).
   - Single-source-line discipline: verify each substring fits on ONE source line per [[presence-ratchet-test-pattern-for-prose-substrings-2026-05-14]] rule 5.

5. **TODOS.md update**:
   - Remove `PACKAGE_NO_IMPORT_CYCLE` and `FIELD_NOT_REQUIRED` from D6e+ backlog (lines ~213-244).
   - Update headline narrative (lines ~93-112) from "25 of 26" to the canonical numerator substring "26 of 26 buf v1.69.0 BASIC rules".
   - Add D6f+ backlog items per the CHANGELOG "Deferred to D6f+" list above, partitioned into TWO subsections per [[scope-guardian]] attribution discipline: (i) **deferred during D6e planning** — engine walker extension (both extend surfaces), `LintRuleSpec.parity_note` field, R4 audit findings, R9b `"off"` severity; (ii) **carried forward from prior deliveries** — R6 promotion, `strict` profile, LintLocation contract, MessageSet-aware rules, IDENTIFIER-based field_behavior contradictions. The (ii) items are NOT D6e-originated and should not appear in D6e's CHANGELOG "Deferred to D6f+" subsection — they live only in TODOS.md.
   - **For the engine walker extension item (D6e-originated)**: name a concrete user-report-driven trigger per Product-lens F2 — *"first user report of a missed proto2 extend-block-required field that buf catches → prioritize for the next delivery."* No vague "deferred to a future X" timeline framing; the trigger is the action signal.
   - Document the N=3/M=8-weeks PD-11 forcing-function default in a brief subsection so future audit-finding-triggered patches have a deterministic threshold, INCLUDING the community-size caveat (small-community thresholds should tighten by 2-3x) so the threshold can be re-evaluated as the user base grows.

6. **Presence-ratchets**:
   - Add `DeliveryRatchetSpec(delivery="D6e", version="0.6.0")` to `tests/test_changelog_delivery_presence_ratchet.py:71-76` (Pattern A line-anchored regex on `^### D6e\b`).
   - Update `tests/schema/lint/test_builtin_packs.py:121-171` substring pins for the new numerator + remove the "PACKAGE_NO_IMPORT_CYCLE" / "FIELD_NOT_REQUIRED" "deferred" substrings (those rules are now landed).
   - Verify KD-1 principle ratchet from U1 still passes.

7. **Bump-contract ratchet pin** (no edits expected):
   - Per KD-9, NO `_LINT_JSON_SCHEMA_VERSION` bump; no new closed-Literal `LintRuntimeWarning.category` values added.
   - Verify `tests/test_builtin_lint_formatter.py::TestBumpContractDocstring` substrings still pass without edit.
   - If U2 or U3 unexpectedly introduced a new closed-Literal value, bump `_LINT_JSON_SCHEMA_VERSION = "0.5"` → `"0.6"` per [[wire-format-schema-version-bump-contract-and-absence-semantic-2026-05-13]] + [[closed-literal-discriminator-bump-trigger-2026-05-17]]. (Not expected; verify pre-commit.)

**Stale-text sweep** per [[stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12]] with triage rubric:
- Run `git grep -n 'deferred to D6e\|arrives in D6e\|D6e-bound\|forthcoming\|once U[0-9] ships' src/ tests/ docs/ README.md CHANGELOG.md`.
- For each hit, apply triage:
  - **Forward-looking-from-now in active surfaces (CLI, README, BUILTIN_PACKS docstring)**: rewrite to present tense or remove.
  - **Past-tense historical references in CHANGELOG D6c/D6d sections**: LEAVE (verb tense is the discriminator).
  - **Frozen planning artifacts in `docs/plans/` / `docs/brainstorms/` / `docs/solutions/`**: LEAVE.
  - **D6d CHANGELOG's "R9b scheduled for D6e+"**: LEAVE (still accurate — R9b is still deferred to D6f+).
  - **"Self-referential delivery target" pattern**: any `deferred to D6e` that landed without execution → generalize to `revisit if <condition>` or `deferred to a future delivery`.

**CHANGELOG snippet byte-equivalence** per [[changelog-readme-snippet-fixture-byte-equivalence-2026-05-21]]: every executable snippet in the CHANGELOG D6e section (pyproject TOML, `--profile` CLI examples, severity overrides) must be byte-equivalent to a committed test fixture. Pick ONE canonical fixture per snippet (typically the U2 or U3 worked example fixture); reference from the CHANGELOG.

**Bundled-commit shape** per [[delivery-boundary-bundled-commit-feat-plus-review-followups-2026-05-21]]: default to splitting (one feat commit + one follow-ups commit). FOLD to a single commit when (a) it's the delivery boundary AND (b) ce:review ran against uncommitted work AND (c) <500 LOC code change. Commit body has explicit `Delivery-boundary work` and `ce:review follow-ups` sections.

**Execution note:** The stale-text sweep is the highest-risk-of-miss step — enumerate every file that mentioned "D6e" as forward-state and convert to active or past-tense framing. Apply the rubric per-hit; do NOT bulk-replace.

**Patterns to follow:**
- `docs/plans/2026-05-19-001-feat-d6d-option-aware-pack-expansion-plan.md:1170-1262` (D6d new-U4) — canonical exemplar for the 7-component commit structure.
- `### D6d` section in `CHANGELOG.md` — section structure + sub-section conventions.
- `tests/test_changelog_delivery_presence_ratchet.py:1-100` — ratchet addition pattern.
- `tests/schema/lint/test_cli_rule_pack_dedup.py` (the new parametrized consolidation) — verify it still passes with all packs.

**Test scenarios:**
- **Happy path:** `pyproject.toml` shows `version = "0.6.0"`. Test asserts version string.
- **Happy path:** D6e CHANGELOG presence-ratchet matches (`^### D6e\b` line-anchored regex finds the section).
- **Happy path:** BUILTIN_PACKS docstring single-source-line substring `"26 of 26 buf v1.69.0 BASIC rules"` present. Test asserts substring in `inspect.getsource(rules.__init__)`.
- **Happy path:** bump-contract ratchet substrings pass without edit. Existing test passes.
- **Happy path:** KD-1 principle presence ratchet from U1 still passes.
- **Happy path:** Layer D audit — `grep -rn 'source_spec="buf:' src/protokit/schema/lint/rules/` returns exactly 26 matches. (Manual pre-commit verification; could also automate via a parametrized test that counts.)
- **Edge case:** stale-text sweep — `git grep "deferred to D6e"` in active surfaces (excluding `docs/plans/`, `docs/brainstorms/`, `docs/solutions/`, CHANGELOG historical sections) returns zero matches.
- **Edge case:** CHANGELOG snippet byte-equivalence — every pyproject TOML snippet in CHANGELOG D6e maps to a committed fixture; spot-check with `grep -A 3 '```toml' CHANGELOG.md` against `tests/...` fixture files.
- **Edge case:** TODOS.md no longer contains `PACKAGE_NO_IMPORT_CYCLE` or `FIELD_NOT_REQUIRED` in D6e+ backlog section. Test asserts substring absence.
- **Edge case:** `_LINT_JSON_SCHEMA_VERSION = "0.5"` unchanged (no bump per KD-9). Test asserts constant value.
- **Edge case:** parametrized CLI dedup test (`tests/schema/lint/test_cli_rule_pack_dedup.py`) passes for all `BUILTIN_PACKS` members including the new `field` pack and the now-5-rule `package` pack.
- **Integration:** full test suite passes (`pytest` clean).
- **Integration:** ruff clean (`ruff check src/ tests/`).
- **Integration:** mypy clean on gated paths (`mypy --strict src/protokit/schema/lint/`).
- **Integration:** parametrized CLI dedup test consolidation IS the single source — `git ls-files | grep test_cli_rule_pack_dedup` returns ONE file.
- **Integration:** new ce:compound learning files exist: `docs/solutions/best-practices/tarjan-scc-import-cycle-detection-pre-walk-*.md` (from U3) + `docs/solutions/best-practices/proto2-strict-profile-activation-pattern-*.md` (from U1+U2) + `docs/solutions/best-practices/near-copy-paste-third-instance-consolidation-trigger-*.md` (from U4).

**Verification:**
- `pyproject.toml`: `version = "0.6.0"`.
- `_LINT_JSON_SCHEMA_VERSION = "0.5"` (unchanged).
- `CHANGELOG.md` has `### D6e — buf BASIC closure + UX philosophy revision (0.6.0)` section with 5 sub-sections.
- README Schema Linting section reads `"26 of 26 buf v1.69.0 BASIC rules (with one documented divergence on extend-block-required-fields)"`.
- BUILTIN_PACKS includes `field` + new `package/no-import-cycle` rule in `package`. Total: 26 buf-parity rules (Layer D grep verified).
- Presence-ratchet tests all pass.
- TODOS.md D6e+ backlog cleared of `PACKAGE_NO_IMPORT_CYCLE` and `FIELD_NOT_REQUIRED`; D6f+ backlog includes engine walker extension, R9b, strict profile, LintLocation, R6 promotion, IDENTIFIER-based contradictions, MessageSet rules, `parity_note` field promotion, and any U1 audit findings with N/M triggers.
- All three new `docs/solutions/best-practices/` files committed (Tarjan SCC, proto2-strict profile activation, third-instance-trigger).
- Stale-text sweep: zero "deferred to D6e" / "arrives in D6e" hits in active surfaces.
- Full suite + ruff + mypy clean.

## System-Wide Impact

- **Interaction graph**: U3 adds a new pre-walk accumulator that runs in `LintEngine.run()` between Steps 3.5b and 4; runs once per `run()` call. No new middleware or observers. The accumulator output is consumed only by `check_package_no_import_cycle` (single-view per PD-8); no sibling consumers exist yet.
- **Error propagation**: U3's accumulator handles malformed dependencies (missing pool entries) gracefully via lookup guards. No new exception types introduced. U2 + U3 rule emissions flow through the existing `ctx.emit(...)` path; no change to `LintFinding` shape.
- **State lifecycle risks**:
  - U3's `self._current_import_cycles` instance state is cleared in `run()`'s `finally` block, matching the D6c precedent at `engine.py:577-594`. Concurrent `run()` calls on the same `LintEngine` instance are already not supported (instance-state cleanup is sequential); U3 inherits this constraint.
  - `proto2-strict` profile registration is implicit (declared in `field/not-required`'s `@lint_rule` decorator); the profile becomes valid as soon as the `field` pack is loaded. Between U1 (profile name documented) and U2 (rule body declares it), `--profile proto2-strict` exits 2 — hence the U1+U2 atomic-commit requirement per PD-2.
  - The R4b WARNING demotion of `file/syntax-specified` is a default-severity change; users with `--max-warnings 0` may see CI behavior changes (handled via migration recipe in U4).
- **API surface parity**:
  - CLI: `--profile proto2-strict` becomes a valid value (no flag shape change). `--rule-pack=protokit.schema.lint.rules.field` becomes loadable.
  - Python API: `LintProfile.from_pack(rule_pack, "proto2-strict")` returns the proto2-strict subset of rules in that pack. `FileLintContext.import_cycles` is a new field (defaults to `None`); existing direct constructions in tests should auto-pass via the default.
  - pyproject: `[tool.protokit.lint] profile = ["default", "proto2-strict"]` becomes valid. `[tool.protokit.lint.severities] "field/not-required" = "warning"` and `"package/no-import-cycle" = "warning"` become valid override paths.
- **Integration coverage** (cross-layer scenarios unit tests alone will not prove):
  - U2: `--profile proto2-strict <proto2_required.descset>` produces ERROR finding flowing through full CLI → engine → formatter pipeline (verify via parity gate + worked-example test).
  - U3: cycle finding for a root file in an SCC of size ≥ 2 flows through full pipeline; cycle_packages param serialized correctly in human / json / junit / sarif formatters.
  - U4: BUILTIN_PACKS expansion does NOT trigger `zip(strict=True)` mismatch at `cli.py:1058-1060` (parametrized CLI dedup test is the integration coverage).
  - The 4-way reviewer convergence on R4b is a coordination risk; ce:review on U1+U2 atomic commit covers it.
- **Unchanged invariants** (blast-radius assurance):
  - `_LINT_JSON_SCHEMA_VERSION` stays `"0.5"` (KD-9 + PD-12). No `LintFinding` schema changes.
  - `LintLocation` discriminant set unchanged (U3 uses existing `FileLocation`).
  - `_PROFILE_ALIASES` unchanged (no `proto2-strict` alias; primary name only per PD-1).
  - `_coerce_profile` unchanged.
  - `_BUF_PARITY_PIN` stays `"v1.69.0"` (no buf bump).
  - Existing 25 rules' default severities + profile placements unchanged (audit-only per R4; `file/syntax-specified` is the lone code change via R4b).
  - All D6a–D6d parity tests continue to pass (verified at each unit's ce:review and at U4 boundary).

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Phase 0 verification of buf v1.69.0 `PACKAGE_NO_IMPORT_CYCLE` emission shape (OQ-1) reveals per-cycle or per-package emission (not per-file). | Re-open PD-6 with buf's empirical shape as anchor; revise rule body emission logic at U3 implementation time; document the deviation from KD-12 direction-of-travel in U3's ce:compound entry. Cost: 1-2 hours of implementation rework; no architectural debt. |
| Phase 0 verification of cycle scope (OQ-2) reveals buf includes vendor-only cycles. | Re-open PD-7; if buf fires on vendor-only cycles user can't fix, document a divergence (third specimen — triggers structured `parity_note` promotion per PD-10) and ship protokit's "any-root-participates" as the protokit-stricter / protokit-looser posture. Cost: extra divergence-documentation work + ce:compound entry. |
| U1+U2 atomic-commit departure from per-unit ce:review pipeline isolation per [[multi-unit-ce-review-stash-pop-coordination-2026-05-21]] | Per PD-2 + brainstorm CONV-C: treat U1+U2 as one unit for ce:review purposes. Single ce:review pass covers both surfaces. Stash-pop discipline still applies for the U2→U3 boundary. |
| Engine walker citation in brainstorm (`engine.py:818-893`) is wrong; future readers may misdiagnose the divergence ground. | Plan corrects to `engine.py:841-916` per PD-3; U2 documentation sites use the corrected citation; CHANGELOG + rule docstring + `--help` epilog all cite the corrected range. |
| Tarjan SCC implementation correctness (no prior art in protokit) | Phase 0 + extensive unit test scenarios for the accumulator (empty pool, single-file, 2-node, 3-node, 4+-node, multiple disjoint, self-import-not-cycle). Mirror well-known Tarjan reference pseudocode; hand-implement ~30 LOC; capture pattern in ce:compound for future maintainers. |
| New `FileLintContext.import_cycles` field breaks direct-construction tests | Field added with `= None` default per existing `directory_packages` precedent at `model.py:1131`. Verify at U3 implementation that no test file constructs `FileLintContext(...)` positionally; if any do, add `import_cycles=None` explicit kwarg. Grep guard: `grep -rn "FileLintContext(" tests/ | grep -v "import_cycles"`. |
| BUILTIN_PACKS expansion triggers latent `zip(strict=True)` mismatch | Parametrized CLI dedup consolidation per PD-9 IS the regression test; lands at U2 with new `field` pack and extends at U3 with `package` pack expansion. Test gates pre-commit. |
| `_LINT_JSON_SCHEMA_VERSION` bump-contract substring drift | KD-9 + PD-12 stipulate no bump; bump-contract ratchet at `tests/test_builtin_lint_formatter.py:705-760` is the gate. If U2 or U3 introduces unexpected closed-Literal values, bump in same commit per [[closed-literal-discriminator-bump-trigger-2026-05-17]]. |
| Stale-text sweep misses a forward-looking reference | Run grep + triage rubric per [[stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12]] at U4. Manual sweep (not automated); ce:review of U4 commit covers second-pair-of-eyes verification. |
| `proto2-strict` profile gets a sibling `strict` profile before D6f+ | KD-3 explicitly says don't consolidate. If a `strict` profile becomes relevant in a future delivery, KD-11's per-syntax-version pattern keeps them distinct. No D6e action needed. |
| R4 audit pass surfaces a high-blast-radius retroactive demotion candidate beyond `file/syntax-specified` | Per R4 + PD-11: document as D6f+ backlog item with concrete N=3/M=8-weeks forcing-function trigger; do NOT bundle into D6e (scope-guardian discipline). Document in U4's TODOS.md update. |
| User confusion between `proto2-strict` opt-in and global `--max-warnings` posture interaction with R4b WARNING demotion. **Silent-CI-pass regression for `--max-warnings` unset users** is the most dangerous case (not "cosmetic" as the brainstorm framed it). | U4 CHANGELOG migration recipe enumerates all three `--max-warnings` postures (unset, 0, explicit error-only filtering) per the Worst-case math subsection. Ranks "CI silently started passing" as the primary remediation trigger. Pre-commit [[changelog-readme-snippet-fixture-byte-equivalence-2026-05-21]] verification ensures every snippet is real (not hypothetical). |

## Alternative Approaches Considered

- **Sequential split: `0.5.1` philosophy patch then `0.6.0` D6e rules.** Rejected per brainstorm Pressure Test: inverted-philosophy framing has no user-visible behavior change beyond the two new rules — standalone patch would be principle-without-substance. The umbrella shape is `0.6.0` with all three deliverables.
- **DFS back-edge detection instead of Tarjan SCC for U3.** Rejected per PD-5: KD-6 defines cycle as SCC of size ≥ 2 — back-edge detection produces only "is there a cycle" without enumerating membership. Tarjan produces the SCC artifact directly. Trade-off: ~30 LOC instead of ~15 LOC for back-edge; the extra LOC buys the artifact the rule needs.
- **Kahn's topological sort for U3.** Rejected per OQ-4: Kahn's detects DAG-ness but does not enumerate SCCs. Excluded from candidates.
- **`field/not-required` lives in an existing pack (e.g., `naming.py` or a new `proto2.py`).** Rejected per PD-4: new `field.py` pack mirrors `file.py` shape and is the namespace anchor for future field-level proto2-strict rules per KD-11 (`field/no-group-syntax`, `field/no-explicit-default`, `field/packed-repeated-primitive`). `proto2.py` was rejected because the namespace is "field-level proto2-strict rules" not "all proto2-strict rules" — future syntax-version-specific packs may be field/enum/file scoped.
- **Rejected: `proto2-friendly` profile (subtractive — REMOVES proto2-hostile rules from a base) vs the chosen `proto2-strict` (additive — ADDS strict checks for opt-in users).** `proto2-friendly` was considered in the SUPERSEDED 2026-05-20 UX-philosophy-revision PLACEHOLDER brainstorm (Piece 3) and explicitly rejected before D6e began. Resolved in brainstorm origin doc: `proto2-strict` per KD-2/KD-11; `proto2-friendly` serves the opposite user population (proto2 shops who want fewer findings) vs `proto2-strict` (proto2 shops who want stricter checks) and is not carried forward. The naming reflects "opt-in to additional strictness," not "opt-out of strictness."
- **Consolidate `proto2-strict` and the deferred `strict` profile.** Rejected per KD-3 + alternative not viable per KD-11: profiles serve distinct user opt-in axes (syntax-version strictness vs style strictness). Consolidation would force users to opt into both axes together.
- **Promote `LintRuleSpec.parity_note` structured field at N=2 (now).** Rejected per PD-10: sentinel says evaluate at N=2 and defer until N=3. Four-site protocol works; broad blast radius of `LintRuleSpec` shape change isn't justified yet.
- **Programmatic fixture builder for U3 cycle scenarios.** Rejected per PD-13: fixture cardinality (~6) is below the threshold (~5). Static hand-authored fixtures are simpler. Reconsider if Phase 0 reveals additional LEGACY_REQUIRED-cycle or large-N variants.
- **Decentralize CLI dedup tests (one per pack, no consolidation).** Rejected per PD-9: three near-copy-paste instances is the third-instance trigger per `[[near-copy-paste-third-instance-consolidation-trigger]]` pattern. Consolidation captures the discipline as institutional knowledge + reduces ~540 LOC to ~60 LOC + makes the next BUILTIN_PACKS flip a 1-line param addition instead of a new file.

## Documentation Plan

- **CHANGELOG.md** — folded at U4 with 5 sub-sections per [[builtin-packs-expansion-changelog-migration-recipe-structure-2026-05-18]].
- **README.md** — Schema Linting section numerator refresh at U4; profile table `proto2-strict` row added at U1.
- **BUILTIN_PACKS docstring** at `src/protokit/schema/lint/rules/__init__.py:17-78` — KD-1 principle line added at U1; numerator refresh + divergence asterisk added at U4.
- **Module + function docstrings** — U1 updates `file.py`; U2 creates `field.py` with 4-site divergence documentation; U3 updates `package.py` module docstring + adds `check_package_no_import_cycle` function docstring.
- **CLI `--help` epilog** at `src/protokit/schema/lint/cli.py:274-321` — stale-text cleanup at U4.
- **TODOS.md** — D6e+ backlog cleanup + D6f+ items added at U4 with N=3/M=8-weeks PL-4 forcing-function defaults documented.
- **`docs/solutions/best-practices/` ce:compound entries** — three new files captured at boundaries:
  - U1+U2 boundary: `proto2-strict-profile-activation-pattern-2026-05-XX.md` — codifies the per-syntax-version profile pattern + the U1+U2 atomic-commit discipline as a structural requirement (CLI gate `cli.py:1005-1037`).
  - U3 boundary: `tarjan-scc-import-cycle-detection-pre-walk-2026-05-XX.md` — codifies the Tarjan SCC pre-walk pattern as new institutional knowledge (no prior art in protokit); names the package-edge granularity + per-file emission via fan-out as the canonical shape.
  - U4 boundary: `near-copy-paste-third-instance-consolidation-trigger-2026-05-XX.md` — codifies the "third near-copy-paste instance triggers consolidation" rule with two sub-patterns: (a) **helper extraction at N=3 call sites** (the D6d new-U4 MAINT-2 `_cli_dedup_helpers.compile_sources_to_descriptor_set` SSOT was instance #2 at the helper-extraction level) and (b) **test-file parametrization at N=3 near-copy-paste files** (this U4's consolidation is instance #3 at the test-file level). The two sub-patterns share the "N=3 triggers consolidation" heuristic but apply to different artifact types (helpers vs test files vs other duplication); naming the patterns distinctly avoids the discovery hazard where a future maintainer searching for "when do I extract a helper?" finds a learning about test-file parametrization. Resolves the `[[near-copy-paste-third-instance-consolidation-trigger]]` bracketed reference from the brainstorm; names the parametrized CLI dedup consolidation as the worked example for sub-pattern (b).
- **Operational / Rollout Notes** — none. D6e ships as a normal release; no migration window, no operational coordination required beyond the standard PyPI release + announcement.

## Sources & References

- **Origin document:** [docs/brainstorms/2026-05-22-d6e-buf-basic-closure-philosophy-revision-requirements.md](../brainstorms/2026-05-22-d6e-buf-basic-closure-philosophy-revision-requirements.md)
- **SUPERSEDED brainstorm (analytical input for U2):** `docs/brainstorms/2026-05-20-d6d-u3-field-not-required-requirements.md` — UR-6 rule body still correct; EV-1..EV-4 binding outcomes; severity/profile decisions superseded by D6e KD-5.
- **PLACEHOLDER brainstorm (Piece 1, 3, 4 resolved in U1; Piece 2 = R4b):** `docs/brainstorms/2026-05-20-protokit-ux-philosophy-revision-requirements.md` — naming divergence (`proto2-friendly` → `proto2-strict`) noted.
- **D6c plan (Arch-D pre-walk accumulator reference for U3):** `docs/plans/2026-05-18-003-feat-d6c-r8-r8b-cross-file-package-rules-plan.md`.
- **D6d new-U4 plan (U4 structural exemplar):** `docs/plans/2026-05-19-001-feat-d6d-option-aware-pack-expansion-plan.md:1170-1262`.
- **Related institutional learnings** (all under `docs/solutions/`):
  - `best-practices/multi-unit-ce-review-stash-pop-coordination-2026-05-21.md`
  - `best-practices/delivery-boundary-unit-commit-composition-2026-05-14.md`
  - `best-practices/delivery-boundary-bundled-commit-feat-plus-review-followups-2026-05-21.md`
  - `best-practices/pre-1.0-version-bump-as-communication-contract-2026-05-14.md`
  - `best-practices/presence-ratchet-test-pattern-for-prose-substrings-2026-05-14.md`
  - `best-practices/migration-recipe-severity-aware-template-reuse-2026-05-21.md`
  - `best-practices/changelog-readme-snippet-fixture-byte-equivalence-2026-05-21.md`
  - `best-practices/audit-wire-format-before-claiming-sibling-parity-2026-05-03.md`
  - `best-practices/plan-review-verify-prior-art-citations-2026-05-15.md`
  - `best-practices/apply-institutional-learnings-postdating-plan-during-ce-review-2026-05-09.md`
  - `best-practices/dual-view-prewalk-accumulator-cross-file-rule-dispatch-2026-05-19.md`
  - `best-practices/empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18.md`
  - `best-practices/family-aware-partition-pattern-multi-family-parity-harness-2026-05-19.md`
  - `best-practices/dormant-code-changelog-draft-staging-delivery-boundary-2026-05-17.md`
  - `best-practices/builtin-packs-expansion-changelog-migration-recipe-structure-2026-05-18.md`
  - `best-practices/stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12.md`
  - `best-practices/lint-rule-message-templates-must-not-recommend-actions-that-trigger-siblings-2026-05-13.md`
  - `best-practices/buf-parity-divergence-documentation-discipline-2026-05-13.md`
  - `best-practices/clirunner-catch-exceptions-false-explicit-discipline-2026-05-21.md`
  - `best-practices/ruff-fix-scope-discipline-pass-diff-files-explicitly-2026-05-21.md`
  - `best-practices/wire-format-schema-version-bump-contract-and-absence-semantic-2026-05-13.md`
  - `best-practices/closed-literal-discriminator-bump-trigger-2026-05-17.md`
  - `best-practices/programmatic-proto-fixture-builder-multi-file-rule-family-2026-05-17.md`
  - `best-practices/rule-pack-extension-ssot-rule-ids-and-test-class-naming-2026-05-12.md`
  - `best-practices/copytoproto-round-trip-for-proto-form-only-descriptor-fields-2026-05-13.md`
  - `best-practices/pureposixpath-for-proto-descriptor-file-stem-2026-05-12.md`
  - `best-practices/worked-example-multi-scenario-test-class-template-2026-05-21.md`
  - `best-practices/audit-trail-correction-as-changelog-subsection-2026-05-19.md`
  - `logic-errors/cli-loaded-packs-dedup-zip-strict-builtin-packs-flip-2026-05-18.md`
  - `logic-errors/matcher-backend-path-resolution-skew-silently-empties-output-2026-05-02.md`
- **TODOS.md D6e+ backlog section** — items rolled forward from D6d Strategic Deferral; U4 prunes the resolved items.
- **External buf documentation** — none used (local Phase 0 empirical verification via `buf lint --error-format=json` is the binding source for emission shape, profile membership, and co-fire ordering).

---

## Per-Unit ce:review Pipeline

Per [[multi-unit-ce-review-stash-pop-coordination-2026-05-21]], the implementation runs on a single feature branch with the per-unit pipeline:

1. **U1+U2 (atomic feat commit)** → `/ce:review` → ce:review follow-ups commit → `/ce:compound` (capture `proto2-strict-profile-activation-pattern` learning) → stash-pop if U3 was WIP.
2. **U3** → `/ce:review` → ce:review follow-ups commit → `/ce:compound` (capture `tarjan-scc-import-cycle-detection-pre-walk` learning) → stash-pop if U4 was WIP.
3. **U4** → `/ce:review` → ce:review follow-ups commit (or bundled per [[delivery-boundary-bundled-commit-feat-plus-review-followups-2026-05-21]] if <500 LOC) → `/ce:compound` (capture `near-copy-paste-third-instance-consolidation-trigger` learning).
4. Branch tip ships protokit 0.6.0.
