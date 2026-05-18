---
title: D6b U7 — delivery-boundary 0.2.0 → 0.3.0 release
type: feat
status: active
date: 2026-05-18
origin: docs/brainstorms/2026-05-18-d6b-u7-delivery-boundary-0-3-0-release-requirements.md
---

# D6b U7 — delivery-boundary 0.2.0 → 0.3.0 release

## Overview

Ship `protokit` 0.3.0 — the user-visible release that closes D6b. Six coupled edits in one atomic feat commit per established D6b pattern (matches D6a U10 `1b59cae` precedent + U4b/U5/U6 single-commit shape per project memory). R38 (TODOS.md update) is rolled into Unit 6's stale-text sweep rather than promoted to a standalone unit per SCOPE-6:

1. **R31** — register `package_same` in `BUILTIN_PACKS` (R7 7 rules become default-on under `recommended` + `default`); atomically-coupled test updates.
2. **R32** — bump `pyproject.toml:7` `version = "0.2.0"` → `"0.3.0"` (sole canonical version site verified).
3. **R33** — fold `CHANGELOG-DRAFT.md` 3 staged sections into single `### D6b — 0.3.0 (2026-05-18)` CHANGELOG.md section with **pre-upgrade migration recipe** (4-path TOML demotion paths matching D6a U10 precedent at CHANGELOG.md:504-521) + **strategic lede** ("17 of 18 buf BASIC rules") matching D6a U10 precedent at CHANGELOG.md:437-444.
4. **R34** — README refresh: Schema Linting intro (5-pack → 6-pack, 17 → 24 rules); rule table (`recommended` 17 → 24, `default` 17 → 29); new `### Upgrade notes (0.2.x → 0.3.0)` section; Public Surface DRAFT row updates.
5. **R35** — presence-ratchet test for refined bump-contract docstring (closed-Literal-discriminator distinction) via `inspect.getsource(module)` substring assertion (Pattern B per repo research).
6. **R36** — stale-forward-looking-text sweep at 12 enumerated sites (`src/` + `tests/` + README + CHANGELOG only — binary scope rule excludes `docs/brainstorms/`, `docs/plans/`, `docs/solutions/`).
7. **R37** — Public Surface DRAFT updates: `CompileResult.source_info_descriptors` (the actual shipped attribute name; R6b's index concept landed at U2 under this renamed attribute, NOT as `source_locations`) classified **INTERNAL** per parent R6b consensus; do NOT add a `_safe_for_findings` row (function was never implemented — U2 used `_safe_for_stderr` directly); `LintRuntimeWarning.category` row update with CLOSED DISCRIMINATOR marker; corrected `leading_comment` helper signature (free function, not mixin method).
8. **R38** (rolled into Unit 6 per SCOPE-6) — `TODOS.md` update retiring U4b/U5/U6 dormancy entries + updating remaining-deliveries to reflect D6b complete + D6c next; pre-enumerated entries to retire (per ADV-11).

## Problem Frame

After D6b U6 shipped on 2026-05-18, all 7 implementation units (U1+U2+U3+U4a+U4b+U5+U6) are on `main` at HEAD `0f09101`. R7 is operational as DORMANT code: importable, exercised via `--rule-pack` opt-in, NOT in `BUILTIN_PACKS`. U6's parity gate empirically verified byte-parity with buf v1.69.0 across 21 snapshots, then caught a real `_escape_inner_quote` bug (fixed inline + renamed to `_escape_message_value`), then ce:review caught a fix-induced second-order bug (`_truncate_values_payload` orphan-backslash; fixed via odd-count discipline). R9 already shipped at U5 with `_LINT_JSON_SCHEMA_VERSION` 0.2 → 0.3 + bump-contract docstring refinement.

U7 is the **delivery boundary**: flip R7's default-on switch, bump the user-visible version, fold CHANGELOG-DRAFT staging into the released CHANGELOG with the U4-plan-committed pre-upgrade migration section (PROTECTING the multi-language teams' upgrade path), refresh README to reflect the shipping state, add structural ratchets that pin the new contracts, and sweep dormancy-window forward-looking-text artifacts so the codebase reads as "this is what shipped" rather than "this is in flight". See origin: `docs/brainstorms/2026-05-18-d6b-u7-delivery-boundary-0-3-0-release-requirements.md`.

**The cost of leaving the gap is asymmetric.** Each unit shipped under the dormancy contract carries forward-looking text (`--help` epilog opt-in lines, CHANGELOG-DRAFT staging entries, dormant-code module docstrings, U6's parity test `--rule-pack` flag). After R31's BUILTIN_PACKS flip, those artifacts become CONTRADICTORY signals (`--help` says opt-in; BUILTIN_PACKS says default-on). Per [[stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12]], the sweep is high-leverage: 10 small in-source rewrites eliminate the source of future-contributor confusion.

The pre-upgrade migration section is **independently load-bearing**: cross-language teams whose CI currently passes on protokit 0.2.0 with `--profile recommended` and whose protos have cross-file option disagreement WILL see RED CI on first 0.3.0 invocation. Without a copy-paste-ready demotion recipe in CHANGELOG, the migration path requires grepping docs/source. The U4 plans (`2026-05-17-001` line 51, `2026-05-17-002` line 57) explicitly committed to U7-scoped pre-upgrade migration content as the mitigation for this risk; the brainstorm's R33 + KD-1 restore that commitment.

## Requirements Trace

All requirements carry forward from the origin doc (see origin for full text + decisions).

- **R31**. BUILTIN_PACKS registration of `package_same` (atomic 3-file coupling: `rules/__init__.py` BUILTIN_PACKS tuple + `tests/schema/lint/test_builtin_packs.py` expected-tuple assertion + NEW `tests/test_changelog_d6b_entry.py` mirror of `test_changelog_d6a_entry.py`).
- **R32**. Version bump 0.2.0 → 0.3.0 at `pyproject.toml:7`. Sole canonical version site (verified at plan-writing time: `grep -rn '__version__' src/` returns 0 matches).
- **R33**. CHANGELOG-DRAFT.md fold into CHANGELOG.md with pre-upgrade migration recipe (4-path demotion + 4-step upgrade notes triage, matches D6a U10 precedent) + 2-sentence strategic lede ("17 of 18 buf BASIC rules").
- **R34**. README Schema Linting section refresh (intro paragraph + rule table + new Upgrade notes section + Public Surface DRAFT new row for BUILTIN_PACKS package_same registration).
- **R35**. Presence-ratchet test for refined bump-contract docstring at `src/protokit/formatters/_builtin_lint.py:227-270` (the `#:` comment block above `_LINT_JSON_SCHEMA_VERSION`). Implementation pattern: `inspect.getsource(module)` substring assertion (NOT `__doc__` — the block is Sphinx `#:` syntax, not a Python docstring).
- **R36**. Stale-forward-looking-text sweep at 12 enumerated sites + binary scope rule (`src/` + `tests/` + README + CHANGELOG only; `docs/brainstorms/`, `docs/plans/`, `docs/solutions/` are historical artifacts, NOT edited).
- **R37**. Public Surface DRAFT updates: `CompileResult.source_info_descriptors` = **INTERNAL** (R6b's source-locations index concept; shipped at U2 under this renamed attribute, not as `source_locations` — see KD-7); do NOT add `_safe_for_findings` row (function was never implemented); `LintRuntimeWarning.category` row with CLOSED DISCRIMINATOR + 5 enumerated values marker; new BUILTIN_PACKS row; `leading_comment(source_info_descriptors, file_name, path)` free function in `rules/options/_comments.py` (IN — actual signature, not the brainstorm's `_LintContextEmitMixin.leading_comment(path)`).
- **R38** (NEW per learnings researcher). `TODOS.md` update retiring dormancy entries + updating remaining-deliveries.

Success criteria (carried from origin S1-S7):

- S1. 0.3.0 ships clean (pyproject.toml = 0.3.0; CHANGELOG.md has `### D6b — 0.3.0` section; CHANGELOG-DRAFT.md is header-only stub).
- S2. R7 fires default-on (`pytest tests/schema/lint/test_cli_package_same_e2e.py` passes R7 assertions without `--rule-pack` flag; bare `protokit lint --profile recommended <fixture>` produces R7 findings).
- S3. Suite stays green. Net test-count delta: **+2 new tests** (R35 ratchet at `tests/test_builtin_lint_formatter.py` + D6b changelog ratchet at `tests/test_changelog_d6b_entry.py`) **− 2 deleted tests** (TestDormancyContract's 2 methods); 0 delta from TestRulePackOptIn → TestRulePackExplicitLoadIsIdempotent rename. **Net: 0 change to test count**; suite must remain green throughout. (R31's atomic-coupling test edits modify existing tests in-place, not add/remove.)
- S4. Parity gate continues passing (`pytest tests/parity/test_parity_package_same.py` 27 tests still pass after R36's `--rule-pack` flag removal — engine idempotency carries the contract).
- S5. README reads as 0.3.0-shipped (no "dormant" / "deferred to U7" / "opt-in via --rule-pack" prose in Schema Linting section; rule table reflects 17-of-18 buf BASIC parity claim).
- S6. Presence-ratchet catches docstring drift (deliberate `sed` removal of "Closed Literal discriminators" from `_builtin_lint.py:227-270` causes R35's test to fail with clear diagnostic).
- S7. User-journey: multi-language team can adopt 0.3.0 without leaving CHANGELOG.md (demotion TOML snippet copy-pasted DIRECTLY from CHANGELOG `Pre-upgrade migration recipe` section — testable via dry-run review of CHANGELOG diff before U7's feat commit lands).

## Scope Boundaries

- **No new rule logic.** U7 is delivery-boundary coordination only. R8 `package/same-directory`, `strict` profile, R9b disable/enable all explicitly defer to D6c.
- **No new test scenarios for R6/R7/R9 behavior.** Coverage is complete from prior units. U7 only adds R35's presence-ratchet test + R31's changelog ratchet + the atomic-coupling test edits.
- **No `docs/solutions/` additions.** U6's ce:compound captured substantive learnings; U7 doesn't surface novel patterns (delivery-boundary mechanics well-trodden via D2/D3/D5/D6a U10 precedent). 2 NEW pattern candidates flagged at U7 ce:compound (per learnings researcher): `delivery-boundary-after-empirical-gate-unit-composition` + `pre-upgrade-migration-section-cross-language-rule-default-on-as-error`.
- **No restructuring of README.** Targeted refresh (R34 scope) — Schema Linting section + rule table + new Upgrade notes parallel section + Public Surface DRAFT row. No worked-example rewrites (R6 example from U3 stands).
- **No revisiting of prior brainstorm/plan decisions.** R36's binary scope rule prohibits editing `docs/brainstorms/`, `docs/plans/`, `docs/solutions/` content.
- **No retroactive fix to parent D6b brainstorm's R6b vs R12 contradiction.** Per R36's binary scope rule, the parent brainstorm is a historical artifact; the contradiction is documented in U7's Open Questions resolution but NOT edited in the parent.

### Deferred to Separate Tasks

- **D6c — R8 `package/same-directory` + cross-file rule kind** — separate brainstorm + plan when D6c begins.
- **D6c — `strict` profile rule enumeration** — separate brainstorm.
- **D6c — R9b per-rule disable/enable** — separate brainstorm; needs real-demand evidence per U5 brainstorm.
- **D6c — R8 + R6 README documentation polish** — full Schema Linting rewrite + worked-example expansion; U7 keeps targeted-refresh scope.
- **POST-MERGE: MEMORY.md + project_state.md update** — D6b complete; 0.3.0 shipped; next delivery D6c. Out-of-repo artifact per origin KD-6.
- **POST-MERGE: D6c brainstorm kickoff** — `/ce:brainstorm` against D6c agenda.

## Context & Research

### Relevant Code and Patterns

**Atomic-coupling sites (R31)**:

- `src/protokit/schema/lint/rules/__init__.py:76` — existing `from protokit.schema.lint.rules import ... package_same,  # noqa: F401` line. U7 may remove the `# noqa: F401` since the module becomes actively consumed via BUILTIN_PACKS.
- `src/protokit/schema/lint/rules/__init__.py:117-124` — `BUILTIN_PACKS: tuple[ModuleType, ...]` tuple. U7 appends `package_same,` as the 7th entry.
- `tests/schema/lint/test_builtin_packs.py:78-87` — expected-tuple assertion (6 entries currently). U7 appends `"protokit.schema.lint.rules.package_same"` as 7th. KD-9 guard at L87-97 fires structured 3-step error if not updated.
- `tests/test_changelog_d6a_entry.py` — precedent for the new `tests/test_changelog_d6b_entry.py` (entire structure: module docstring + REPO_ROOT/CHANGELOG_PATH constants + `TestChangelogD6aEntry` class with 2 methods — `test_changelog_exists` + `test_changelog_names_d6a`).
- `tests/schema/lint/test_cli_package_same_e2e.py:85-149` — `TestDormancyContract` class (2 methods become tautological post-flip — DELETE).
- `tests/schema/lint/test_cli_package_same_e2e.py:157-327` — `TestRulePackOptIn` class (4 methods all remain meaningful as idempotency/functional regressions — RENAME to `TestRulePackExplicitLoadIsIdempotent` + update class docstring + each test docstring).

**Version-bump site (R32)**:

- `pyproject.toml:7` — `version = "0.2.0"` (sole canonical version site; verified `grep -rn '__version__' src/` returns 0 matches).
- `src/protokit/_cli_utils.py:42-61` — `_get_protokit_version()` reads `importlib.metadata.version("protokit")` from INSTALLED package metadata. After version bump, local dev workflow requires `pip install -e .[dev]` re-run for runtime version (`protokit lint --version`, SARIF `runs[0].tool.driver.version`) to reflect 0.3.0. CI re-runs `pip install -e ...` fresh per build — no issue.
- `tests/test_builtin_lint_runtime_warnings.py:~346` (per learnings researcher) — co-existence test that may still expect `"0.2"` for `schema_version`. **Verify at implementation time**: if it does, this is a U7 fix obligation (U5 should have updated it; if not, U7 must).

**CHANGELOG fold sites (R33)**:

- `CHANGELOG-DRAFT.md:16-56` — D6b U4b staged section (R7 family, 7 rule_ids, dormancy rationale, empirical foundation).
- `CHANGELOG-DRAFT.md:58-97` — D6b U5 staged section (severities_unloaded_rule Literal, schema_version bump, bump-contract refinement, consumer migration note).
- `CHANGELOG-DRAFT.md:99-173` — D6b U6 staged section (parity gate, 5 invariants, multi-file harness helpers, convention break).
- `CHANGELOG-DRAFT.md:175-219` — "U7 eventual CHANGELOG content scope (suggested)" — U7's authoring guide; 11 enumerated items. NOT verbatim content; use as drafting reference.
- `CHANGELOG.md:435` — D6a section header pattern: `### D6a — \`protokit lint\` rule library expansion + buf BASIC parity (0.2.0)`. U7 mirrors with `### D6b — option-aware path + cross-language buf BASIC parity (0.3.0)`.
- `CHANGELOG.md:437-444` — D6a U10 strategic lede (2-sentence pattern). U7 lede: "D6b adds the first option-aware rules (R6 deprecated-replacement family) + cross-language buf-BASIC parity (R7 PACKAGE_SAME_* family), bringing `protokit lint` to **17 of 18 buf BASIC rules**. The 18th (`package/same-directory`) defers to D6c — its cross-file rule kind requires new ElementKind + LintLocation discriminant work scoped for its own architectural delivery."
- `CHANGELOG.md:504-521` — D6a U10 4-item demotion-paths enumeration (pin `~=0.1.0`, `--no-builtin-rules`, `--min-severity=warning`, per-rule `[severities]`). U7 mirrors with 0.2.0 → 0.3.0 substitution + R7-specific examples.
- `CHANGELOG.md:523-536` — D6a U10 4-step upgrade-notes recipe. U7 mirrors with R7-specific guidance.

**README sites (R34)**:

- `README.md:480-492` — Schema Linting intro paragraph ("5 packs … 17 rules"). U7 updates to "6 packs … 24 rules" + adds `package_same` to inline pack list + adds strategic 17/18 parity claim.
- `README.md:532-538` — Profile table. `recommended` row 17 → 24; `default` row 17 → 29. Default-row description text MUST be rewritten (currently says "Forward-placeholder ... structurally equal to recommended" — wrong post-U7).
- `README.md:545` — Existing `### Upgrade notes (0.1.x → 0.2.0)` heading. U7 adds parallel `### Upgrade notes (0.2.x → 0.3.0)` section.
- `README.md:750-774` — Public Surface DRAFT table (`| Surface | Element | Status |`). Existing rows at L760 + L763 already reference `"0.3"` (U5 updated these). U7 adds new BUILTIN_PACKS row + updates LintRuntimeWarning.category row + adds `CompileResult.source_info_descriptors` row (as INTERNAL — the actual shipped attribute; `source_locations` was the brainstorm-time name that was renamed during U2 implementation, verified at `src/protokit/schema/compile.py:231`).
- `README.md:765` — Profile names row currently reads `default is forward-placeholder for D6b differentiator` — this clause is stale post-0.3.0. U7 rewrites the parenthetical to `default extends recommended with R6 deprecated-replacement family (5 warning-severity option-aware rules as of 0.3.0)`.

**R35 presence-ratchet substrings (`src/protokit/formatters/_builtin_lint.py:227-270`)**:

The bump-contract block is a `#:` Sphinx-style comment above `_LINT_JSON_SCHEMA_VERSION`, NOT a Python `__doc__` attribute. Implementation MUST use `inspect.getsource(_builtin_lint_module)` + substring check (Pattern B per repo research). Pinned substrings (verified at plan-writing time):

- `"Closed Literal discriminators"` (line 257) — closed-Literal-discriminator framing. Single contiguous source line.
- `"additions DO bump the"` (line 262) — directional contract for closed Literals. **NOTE on line-wrap discipline**: the original phrasing `"additions DO bump the version"` spans lines 262-263 (continuation via `#:` prefix on line 263), so the period-terminated 6-word fragment `"additions DO bump the"` is the longest contiguous on-line substring that preserves the positive directional contract.
- `"Open severity-string ladders"` (line 251) — open-ladder distinction. Single contiguous source line.
- `'"severities_unloaded_rule"'` (line 268, with literal double-quote chars) — concrete historical-fact anchor. **Single substring**, not the originally-described pair (`"D6b U5's addition of"` + `'"severities_unloaded_rule"'`); empirical verification showed the value-name substring with its quote delimiters is sufficient as an anchor.

**Stale-text sweep sites (R36, 12 enumerated)**:

**Pre-sweep baseline (mandatory pre-edit step)**: run `git status` + ensure clean working tree. The R36 binary scope rule is an INVARIANT: `git diff --stat -- docs/brainstorms/ docs/plans/ docs/solutions/` MUST be empty before commit. If any docs/ file shows modification after the sweep, run `git checkout -- docs/brainstorms/ docs/plans/ docs/solutions/` to revert (this plan document itself and the origin brainstorm legitimately contain stale-looking forward references — they are historical artifacts).

1. `src/protokit/schema/lint/cli.py:280-283` — `--help` epilog R7 opt-in discovery line ("Opt into the dormant PACKAGE_SAME_* rule family (R7) — not in the default profile until 0.3.0:"). DELETE the block entirely or replace with active-state note.
2. `tests/schema/lint/test_cli_package_same_e2e.py:85-149` — `TestDormancyContract` class (2 methods). DELETE entirely. **Pre-deletion analysis (per ADV-8)**: verify the "clean fixture + recommended profile + exit_code == 0" invariant is covered elsewhere in the suite (`grep -rn 'exit_code == 0' tests/schema/lint/test_cli_package_same_e2e.py tests/schema/lint/test_engine_*.py`). If uncovered, repurpose one deleted method as `test_recommended_profile_clean_fixture_exit_zero` with AGREEING fixture values to preserve the happy-path coverage.
3. `tests/schema/lint/test_cli_package_same_e2e.py:157-327` — `TestRulePackOptIn` class (4 methods). RENAME class to `TestRulePackExplicitLoadIsIdempotent`; update class docstring + each test docstring to reflect that `--rule-pack` is now a redundant explicit load exercising idempotency, NOT opt-in to otherwise-dormant rules.
4. **(merged into Site 5 — inline verification)**: `tests/parity/test_parity_package_same.py:16-22` module docstring contains a forward-looking-tense paragraph (`"When U7 flips BUILTIN_PACKS..."`). The implementer reads it while editing Site 5; if any tense words need updating to past-tense (e.g., `"Since U7 flipped BUILTIN_PACKS..."`), update inline. If the paragraph already reads correctly as historical post-flip context, no edit needed. Original Site 4 enumeration retired to avoid inflating the sweep with a likely-zero-edit checkpoint.
5. `tests/parity/test_parity_package_same.py` — REMOVE `rule_pack=_RULE_PACK` kwarg from the `run_protokit_lint_multi_file(...)` call in `test_parity_byte_matches_recorded_snapshot`; REMOVE the module-level `_RULE_PACK` constant. While editing this file, also handle the Site 4 inline-verification (above).
6. `tests/parity/test_parity_package_same.py:83-90` — `_build_package_same_rule_id_map` docstring. UPDATE: "R7 is NOT in BUILTIN_PACKS until U7 (per KD-4)" → past-tense framing acknowledging the helper is retained for assertion-module isolation, not because R7 is excluded.
7. `tests/parity/conftest.py:171-199` — `_build_package_same_proto_to_buf` docstring. UPDATE: "R7 is dormant (not in BUILTIN_PACKS) until U7" → "Until U7, R7 was dormant; this dedicated walk kept U6's invocation path independent of BUILTIN_PACKS sequencing. Post-U7, `_PACKAGE_SAME_PROTO_TO_BUF` is a subset of `RULE_ID_MAP` but retained for assertion-module isolation."
8. `src/protokit/schema/lint/rules/package_same.py:89-97` — module docstring BUILTIN_PACKS registration block. REWRITE: "This module is loadable but NOT registered in default BUILTIN_PACKS for U4b. Users opt in via --rule-pack=..." → "R7 PACKAGE_SAME_* family — cross-language namespace consistency rules, default-on under `recommended` + `default` profiles as of 0.3.0."
9. `src/protokit/schema/lint/rules/__init__.py:80-94` — dormancy commentary block. PRESERVE historical-fact framing ("imported here so users can opt in via --rule-pack ... AND so the cold-import regression test has a known forbidden-modules target") + DELETE "DELIBERATELY NOT in BUILTIN_PACKS ... deferred to U7" paragraph. The `# noqa: F401` at L76 is REMOVED (Unit 1 handles this — the import is actively consumed via BUILTIN_PACKS, so the F401 silencer is no longer needed).
10. `src/protokit/schema/lint/engine.py:519-526` — deferred-import docstring "Once U7 registers package_same in BUILTIN_PACKS, the package_same module loads at engine-init time anyway, so this deferred import becomes a no-op." UPDATE to past tense: "Since U7 registered `package_same` in BUILTIN_PACKS, the deferred import is a no-op at runtime."
11. **(NEW per FEAS-2 + ADV-2)** `src/protokit/schema/lint/rules/package_same.py:537-540` — RULES tuple section header comment block: `# NOT registered in default BUILTIN_PACKS until U7 (deferred per [[pre-1.0-version-bump-as-communication-contract]] alongside the 0.2.0 -> 0.3.0 version bump).` REWRITE to active-state: `# Registered in default BUILTIN_PACKS as of 0.3.0; the --rule-pack opt-in flag remains supported as an idempotent explicit load.`
12. **(NEW per FEAS-2)** `tests/schema/lint/test_cli_package_same_e2e.py:1-19` — module-level file docstring beginning `"Verifies the dormant-by-default contract: until U7 registers package_same in BUILTIN_PACKS..."`. REWRITE: remove the dormant-contract framing (TestDormancyContract is deleted at Site 2; TestRulePackOptIn is renamed at Site 3). New framing: `"End-to-end CLI tests for the R7 PACKAGE_SAME_* family. Verifies that --rule-pack is an idempotent explicit-load path post-0.3.0; --proto vs --descriptor-set parity; --profile recommended/default both fire R7."`

**Verification grep (post-sweep)**: `git grep -nE 'dormant|dormancy|until U7|deferred to U7|post-U7|U7 flip|not yet in BUILTIN_PACKS|U7 registers|U7 alongside' src/ tests/` should return ZERO hits in active code. No exclusions needed — `tests/test_changelog_d6b_entry.py` (new in Unit 1) and `tests/test_changelog_d6a_entry.py` (existing) reference only "D6b" / "D6a" substrings, not the swept dormancy terms.

**Engine idempotency (R36 site 5 dependency) — two-mechanism contract**:

The parity-test contract that lets R36 site 5 drop the `--rule-pack=...package_same` kwarg safely is preserved by **TWO independent mechanisms**; a future engineer simplifying one without re-checking the other could silently break the contract:

- **Mechanism 1**: `src/protokit/schema/lint/engine.py:241-242` — `LintEngine.load_rule_pack` short-circuits duplicate loads on `module.__name__`: `if module.__name__ in self._loaded_module_names: return  # idempotent`. Verified at plan-writing time.
- **Mechanism 2**: `src/protokit/schema/lint/model.py:717-719` — `LintProfile.compose` uses `frozenset().union(*(p.rule_ids for p in profiles))` set-union semantics, which absorbs duplicate per-pack profiles. The CLI does NOT de-dup `loaded_packs` (`cli.py:831` unconditionally appends): a `--rule-pack` for a pack already in BUILTIN_PACKS produces a doubled list entry; the downstream `compose` frozenset-union eats the duplicate.

The `TestRulePackExplicitLoadIsIdempotent` class docstring (Unit 1, R36 site 3 rename target) MUST cite BOTH mechanisms as the load-bearing contract so a future maintainer cannot remove one without the other being visibly weakened.

**Line-number freshness preamble**: line numbers in this plan are verified at 2026-05-18 commit `0f09101` against current `main`. If implementation begins on a later commit, `git log --oneline -5 -- <file>` should be run on each cited file; if any file has been touched since `0f09101`, re-verify line numbers via substring grep. The substrings in this plan (R35 pinned substrings, R36 sweep targets) are content-based and survive line drift; line numbers are decorative — implementers should navigate by substring, not by line number.

### Institutional Learnings

Comprehensive citation per the U7 ce:plan learnings-researcher pass:

- **[[delivery-boundary-unit-commit-composition-2026-05-14]]** — CORE. D6a U10 established the 7-component checklist this plan maps onto. R38 (TODOS.md update) was missing from my brainstorm and added here per this learning's checklist.
- **[[pre-1.0-version-bump-as-communication-contract-2026-05-14]]** — CORE. R33 + R34 + KD-1 anchor on this. The version bump IS the breaking-change signal; no `BREAKING:` prefix; 4-path demotion paths matching D6a U10 precedent are the migration-recipe requirement.
- **[[presence-ratchet-test-pattern-for-prose-substrings-2026-05-14]]** — CORE. R35 implementation pattern: source-read (not runtime introspection) + substring assertion + failure message naming both correction paths.
- **[[stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12]]** — CORE. R36's binary scope rule + 10-site enumeration directly implement this learning.
- **[[dormant-code-changelog-draft-staging-delivery-boundary-2026-05-17]]** — CORE. U7 executes the "U_final" delivery-boundary trigger exactly as this learning describes; the `TestDormancyContract` deletion is structurally coupled to BUILTIN_PACKS registration.
- **[[wire-format-schema-version-bump-contract-and-absence-semantic-2026-05-17]]** — SUPPORTING. R33's wire-format bullet documents the 0.2 → 0.3 bump that landed at U5; R37's CLOSED DISCRIMINATOR marker structurally pins the bump-trigger.
- **[[closed-literal-discriminator-bump-trigger-2026-05-17]]** — SUPPORTING. R35's substring set pins this learning's load-bearing distinction. `inspect.getsource` pattern is the verified approach.
- **[[value-migrated-vs-value-added-consumer-migration-2026-05-17]]** — SUPPORTING. R33's "Consumer migration (Python API)" bullet MUST say "migrated" not "added" for the `severities_unloaded_rule` value (CLI emit site MIGRATED, not net-new); consumers switching on `category == "unloaded_rule"` need to AUDIT not just extend.
- **[[semantic-category-conflation-accepted-tradeoff-literal-widening-2026-05-13]]** — SUPPORTING. R33's bullet on `severities_unloaded_rule` references the resolution; the doc has a Resolution annotation citing U5 close. Verify the three-site discipline (Literal docstring + CLI emit-site comment + TODOS.md backlog entry) reflects the resolved state.
- **[[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]]** — CONTEXTUAL. R31's BUILTIN_PACKS flip is authorized by U6's empirical parity gate. CHANGELOG section's "Added" bullet should reference the gate as the validation step.
- **[[truncation-guard-odd-count-discipline-for-doubled-escape-pairs-2026-05-18]]** — PERIPHERAL. Helper correctness shipped at U6; U7 CHANGELOG bullet briefly acknowledges as a U6 helper fix under R7.

**NEW pattern candidates for U7's eventual ce:compound** (per learnings researcher):

- `delivery-boundary-after-empirical-gate-unit-composition` — first instance: U7 ships AFTER U6's parity gate validated byte-parity. Distinct from D6a U10's flip-without-preceding-gate pattern. Worth capturing as the "parity-validated flip" boundary shape.
- `pre-upgrade-migration-section-cross-language-rule-default-on-as-error` — D6b U7 is the first protokit-lint release to default-on ERROR-severity cross-language rules. The 4-path demotion section is the inaugural precedent for future cross-language rule additions.

## Key Technical Decisions

### KD-1 (carried from origin: KD-1). Pre-1.0 plain CHANGELOG framing

Matches D6a U10 0.2.0 precedent at `CHANGELOG.md:435-545`. Section header `### D6b — option-aware path + cross-language buf BASIC parity (0.3.0)`. No `BREAKING:` prefix per pre-1.0 communication contract. Strategic 2-sentence lede + enumerated Added + Wire-format + Behavior changes + Pre-upgrade migration recipe + Consumer migration (Python API) + Deferred to D6c sections.

### KD-2 (carried from origin: KD-2). Targeted README refresh

R34 scope: Schema Linting intro + rule table + new Upgrade notes section + Public Surface DRAFT row updates. No full restructure; no new sections beyond the Upgrade notes parallel; no worked-example rewrites.

### KD-3 (carried from origin: KD-3). Full dormancy-window artifact sweep

12 sites enumerated above (10 from origin + 2 added during /ce:plan empirical verification: `package_same.py:537-540` RULES tuple comment + `test_cli_package_same_e2e.py:1-19` file docstring). Binary scope rule prohibits editing `docs/brainstorms/`, `docs/plans/`, `docs/solutions/` content — this is an INVARIANT, not a "don't" (see Sweep sites preamble). U6 KD-4's "retain `--rule-pack` flag as documentation value" framing is superseded — the flag becomes redundant noise post-flip; full sweep eliminates the source of future-contributor confusion.

### KD-4 (carried from origin: KD-4). CHANGELOG-DRAFT.md kept as empty stub

Don't delete the file; preserve as header-only stub explaining the staging mechanism for future D6c+ units. Per [[dormant-code-changelog-draft-staging-delivery-boundary-2026-05-17]].

### KD-5 (carried from origin: KD-5). Presence-ratchet test reads source via `inspect.getsource`

Per repo research finding: the bump-contract block at `_builtin_lint.py:227-270` is a `#:` Sphinx-style comment above `_LINT_JSON_SCHEMA_VERSION`, NOT a Python `__doc__` attribute. `inspect.getsource(_builtin_lint_module)` returns the module source string; substring assertion checks for the 4 pinned substrings (3 contract-pinning + 1 historical-fact-anchor). Origin's KD-5 said `Path(...).read_text()` is also a valid pattern; `inspect.getsource` is preferred because it works with installed-package paths AND source-checkout paths uniformly.

### KD-6 (carried from origin: KD-6). No memory update inside U7's feat commit

`MEMORY.md` + `project_state.md` updates are POST-MERGE maintenance.

### KD-7 (NEW, corrected during /ce:plan empirical verification). `CompileResult.source_info_descriptors` = INTERNAL (resolves parent R6b vs R12 contradiction; attribute was renamed at U2)

**Two-part resolution:**

1. **Attribute-name correction**: The parent D6b brainstorm referenced `CompileResult.source_locations`, but U2's implementation shipped the field under a renamed attribute: `CompileResult.source_info_descriptors: Mapping[str, FileDescriptorProto] | None` at `src/protokit/schema/compile.py:231` (verified at /ce:plan time). The R6b concept (a source-locations index built before `pool.Add()` discards `source_code_info`) DID land at U2; only the attribute name differs from the brainstorm. The free-standing helper that R6b enabled is `leading_comment(source_info_descriptors, file_name, path)` at `src/protokit/schema/lint/rules/options/_comments.py:202` (NOT a `_LintContextEmitMixin.leading_comment(path)` method as the parent brainstorm sketched). All Public Surface DRAFT row references use the actual shipped names.

2. **Classification (INTERNAL vs IN)**: parent D6b brainstorm has internal contradiction on classification: R6b (line 73) + Non-Goals (line 182) both say INTERNAL per security-lens rationale; R12 (line 128) says IN. **Resolution: INTERNAL.** Rationale: security-lens R6b reasoning (limit leakage of source-position data into stable public API) outweighs R12's structural enumeration. Out-of-repo consumer-impact assumption: presumed low because the attribute is undocumented in user-facing README at 0.2.x ship time, and the security-lens framing in R6b was the later/more-considered position. The CHANGELOG `### D6b — 0.3.0` section's Consumer migration (Python API) bullet SHOULD include a one-line note: "`CompileResult.source_info_descriptors` is INTERNAL — not part of the public surface; consumers integrating with the compile-result object should treat it as implementation detail."

Documented as the U7 plan-of-record; the parent brainstorm itself is NOT retroactively edited (per R36's binary scope rule prohibiting `docs/brainstorms/` edits).

### KD-8 (NEW). `_safe_for_findings` was never implemented — no Public Surface DRAFT row to add or delete

`_safe_for_findings` function does not exist in the codebase (`grep -rn '_safe_for_findings' src/ tests/ README.md` returns 0 matches; verified at /ce:plan time). The parent D6b brainstorm planned for it but U2's implementation used the existing `_safe_for_stderr` directly. R37 simply does NOT add a `_safe_for_findings` row to the Public Surface DRAFT — no deletion ceremony required, no Risk row. If `_safe_for_stderr` should be enumerated as INTERNAL in the Public Surface DRAFT, that is a separate decision out of U7 scope.

### KD-9 (NEW). `TestRulePackOptIn` is RENAMED, not deleted (per repo research)

Repo research clarified that `TestRulePackOptIn`'s 4 test methods are ALL meaningful post-flip as idempotency/functional regressions (`test_descriptor_set_mode_*` + `test_proto_mode_produces_same_findings_as_descriptor_set` + `test_message_template_matches_buf_byte_format`). Rename to `TestRulePackExplicitLoadIsIdempotent` + update class docstring + each test docstring to reflect that the `--rule-pack` flag now exercises `LintEngine.load_rule_pack`'s idempotency contract, NOT opt-in to otherwise-dormant rules.

### KD-10 (NEW per ADV-10). R7 default-on at ERROR severity (rather than WARNING)

R7 PACKAGE_SAME_* family fires as `error` on `recommended` + `default` profiles. **This was a deliberate design choice, not an inherited foregone conclusion.** Alternative considered: ship R7 default-on at WARNING severity (lighter touch; multi-language teams see findings without RED CI; severity promotion to ERROR via `[severities]` is opt-in). Alternative rejected because:

1. **buf BASIC parity matching**: `recommended` profile's user-mental-model is "behaves like `buf lint --error-format=...` defaults" — buf treats PACKAGE_SAME_* findings as errors. Surprise on severity divergence is a worse adoption signal than CI breakage on a documented bump.
2. **Migration recipe IS the mitigation**: R33's 4-path demotion recipe (with the "no pyproject.toml?" sub-section) gives teams a frictionless severity escape hatch. The cost of authoring the recipe was paid; making R7 default-on at ERROR realizes that investment.
3. **Path 2 (demote to warning) is first-class**: the migration recipe's path 2 explicitly normalizes per-rule severity demotion as a way to EXPRESS team conventions, not as a workaround.

**Future-revisit triggers** (would justify a 0.4.0 reversal to default-WARNING): (a) PyPI download data shows >70% of 0.2.x users pin to `~=0.2.0` rather than migrate after 4-6 weeks; (b) GitHub issue volume on R7 ERROR exceeds the bug-report rate for the rest of the rule library combined; (c) a future cross-language rule family (D6c+ `package/same-directory`) needs a graduation-from-WARNING path that R7 would benefit from joining.

**Per [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]]**: U6's parity gate validated byte-parity with buf v1.69.0 across 21 snapshots; the empirical foundation authorizes the BUILTIN_PACKS default-on flip at the same severity buf uses.

## Open Questions

### Resolved During Planning

- **CompileResult attribute name**: actual shipped name is `source_info_descriptors` at `compile.py:231`, NOT `source_locations` (brainstorm-time name). Verified at /ce:plan time (KD-7).
- **CompileResult.source_info_descriptors classification**: INTERNAL per parent R6b consensus (KD-7).
- **`leading_comment` helper signature**: actual is `leading_comment(source_info_descriptors, file_name, path)` free function in `rules/options/_comments.py:202`, NOT `_LintContextEmitMixin.leading_comment(path)` method (brainstorm-time sketch). Classification: IN (free function, non-underscore module).
- **`_safe_for_findings` classification**: function does NOT exist (verified `grep -rn '_safe_for_findings' src/ tests/ README.md` → 0 hits). KD-8 collapses to a single "do not add" sentence; no DRAFT row deletion ceremony.
- **`TestRulePackOptIn` disposition**: RENAMED to `TestRulePackExplicitLoadIsIdempotent` (KD-9; all 4 methods remain meaningful).
- **Canonical version source-of-truth**: `pyproject.toml:7` is sole site (R32).
- **R35 implementation pattern**: `inspect.getsource(module)` + substring check (KD-5).
- **R35 substring set**: 4 substrings pinned (see Context & Research section). Substring 2 corrected from `"additions DO bump the version"` (line-wrap bug per FEAS-1) to `"additions DO bump the"` (line 262, single contiguous line). Substring 4 corrected from a pair to a single `'"severities_unloaded_rule"'` substring per FEAS-6.
- **R36 site count + binary scope rule**: 12 sites enumerated (10 from origin + 2 added during /ce:plan empirical verification per FEAS-2 / ADV-2); `docs/brainstorms/`, `docs/plans/`, `docs/solutions/` excluded as INVARIANT (not "don't").
- **TODOS.md as R38**: added per [[delivery-boundary-unit-commit-composition-2026-05-14]] learning.
- **`test_parity_package_same.py:16-22` paragraph**: merged with Site 5 inline-verification — implementer checks tense while editing the `--rule-pack` flag removal. Original Site 4 retired to avoid inflating sweep with a likely-zero-edit checkpoint.
- **`tests/test_builtin_lint_runtime_warnings.py` schema_version state**: verified at /ce:plan time — `lint_schema_version == "0.3"` at lines 347 + 377. U5 already updated this. No U7 fix obligation.
- **CHANGELOG ordering convention**: newest-on-top (verified — D6a section at line 435 sits below the prior unreleased Added section at line 18). U7 inserts `### D6b — 0.3.0` ABOVE the D6a header.
- **KD-9 diagnostic text discrepancy in test_builtin_packs.py:94-96**: existing diagnostic says "Coordinate a major version bump." This is misleading for U7's pre-1.0 minor bump (0.2.0 → 0.3.0). Unit 1 fixes this diagnostic alongside the BUILTIN_PACKS tuple edit (R31 atomic-coupling site).

### Deferred to Implementation

- **U5 three-site discipline state for `semantic-category-conflation`**: verify at implementation time that the Literal docstring + CLI emit-site comment + TODOS.md backlog entry all reflect the resolved state. If TODOS.md backlog entry was never retired, R38 closes that loop.
- **`# noqa: F401` removal on `package_same` import**: at `src/protokit/schema/lint/rules/__init__.py:76`. Once added to BUILTIN_PACKS, the import is actively consumed and noqa is no longer required. **Decision: REMOVE** (consolidated single answer — supersedes any conditional language elsewhere in the plan).
- **Exact CHANGELOG section header wording**: `### D6b — option-aware path + cross-language buf BASIC parity (0.3.0)` is the proposed header; implementer may refine.
- **Exact R7-specific demotion TOML snippet examples**: `/ce:work` chooses 1-2 representative rule_ids (likely `package/same-go-package` as the most common multi-language case).
- **Unit 5 test method location**: place new `test_bump_contract_docstring_preserves_closed_literal_distinction` method under existing class structure in `tests/test_builtin_lint_formatter.py` (implementer picks the closest semantic neighbor; create a `TestBumpContractDocstring` class only if no neighbor fits).
- **Atomic-commit recovery protocol (if ce:review surfaces blocking findings)**: if a P0/P1 ce:review finding lands on Unit 3 (CHANGELOG wording — the highest-judgment unit) or Unit 4 (README refresh), the recovery option is to PARTITION: land Units 1+2+5+6+7 as a smaller delivery-boundary commit, address Unit 3/4 as a follow-up commit before tagging 0.3.0. The atomic-commit-by-default assumption is documented as the happy path; partition is the documented escape valve. Implementer chooses at ce:review-time based on finding severity.

## Implementation Units

Six units bundled atomically into ONE feat commit per established D6b pattern (matches D6a U10 `1b59cae` + U4b/U5/U6 single-commit shape). The "units" are planning notation for implementer mental model + commit message structure; they are NOT separate commits. R38 (TODOS.md update) rolls into Unit 6 per SCOPE-6 finding; the original "Unit 7" entry below is retained as a sub-section of Unit 6 (TODOS.md update with pre-enumerated entries).

- [ ] **Unit 1: BUILTIN_PACKS atomic registration (R31)**

**Goal:** Register `package_same` in `BUILTIN_PACKS`; update the membership-pin test + add the new D6b changelog ratchet; delete the now-tautological dormancy contract tests + rename the rule-pack tests to reflect their post-flip idempotency-regression purpose.

**Requirements:** R31, S2, S3.

**Dependencies:** None (foundational).

**Files:**
- Modify: `src/protokit/schema/lint/rules/__init__.py` (append `package_same,` to BUILTIN_PACKS tuple at L117-124; REMOVE `# noqa: F401` from L76 import — actively consumed via BUILTIN_PACKS post-flip; consolidated single decision per Open Questions resolution)
- Modify: `tests/schema/lint/test_builtin_packs.py` — TWO edits: (a) append `"protokit.schema.lint.rules.package_same"` to expected-tuple at L78-87; (b) fix the KD-9 diagnostic at L94-96 — replace `"Coordinate a major version bump — adding to BUILTIN_PACKS is a breaking change"` with pre-1.0-aware language: `"Coordinate a minor version bump pre-1.0 (or major bump post-1.0) — adding to BUILTIN_PACKS is a user-visible behavior change to protokit lint defaults that the version-bump communication contract requires."` Per [[pre-1.0-version-bump-as-communication-contract-2026-05-14]].
- Create: `tests/test_changelog_d6b_entry.py` (mirror of `tests/test_changelog_d6a_entry.py` with `"D6b"` substring)
- Modify: `tests/schema/lint/test_cli_package_same_e2e.py` (DELETE `TestDormancyContract` class at L85-149 — see ADV-8 pre-deletion analysis at R36 Site 2; RENAME `TestRulePackOptIn` at L157 to `TestRulePackExplicitLoadIsIdempotent` + update class docstring to cite BOTH idempotency mechanisms (engine module-name short-circuit + LintProfile.compose frozenset union); update each test docstring)

**Approach:**
- Add `package_same` as 7th member of `BUILTIN_PACKS` tuple. Tuple ordering is alphabetical-by-import-name (verify pattern from existing 6 members; add at correct alphabetic position OR at end per existing convention).
- The `# noqa: F401` at L76 was needed during dormancy because `package_same` was imported but unused; once added to BUILTIN_PACKS the import is actively consumed and noqa may be removed (cosmetic — preserve if uncertain about ruff rule activation).
- `tests/schema/lint/test_builtin_packs.py:78-87` expected-tuple is the structural intent gate. Failing this test in CI is the KD-9 contract being satisfied at U7 (the test's diagnostic message explicitly enumerates 3-step requirement: update tuple + add CHANGELOG entry + coordinate version bump — all 3 land in U7's commit).
- `tests/test_changelog_d6b_entry.py` mirrors `tests/test_changelog_d6a_entry.py` exactly (substring ratchet for `"D6b"`). Per [[presence-ratchet-test-pattern-for-prose-substrings-2026-05-14]]: failure message must name BOTH correction paths (restore substring OR update RATCHET_SUBSTRING after confirming semantic equivalence).
- `TestDormancyContract` deletion is structurally coupled to BUILTIN_PACKS registration per [[dormant-code-changelog-draft-staging-delivery-boundary-2026-05-17]]. The test methods become tautological post-flip (assert zero R7 findings without `--rule-pack`, but R7 fires automatically now).
- `TestRulePackOptIn` rename per KD-9 (repo research confirmed all 4 methods are meaningful regression coverage for the engine's idempotent-load contract — DO NOT DELETE).

**Patterns to follow:**
- `tests/test_changelog_d6a_entry.py` exact structure (mirror for `D6b`).
- `tests/schema/lint/test_builtin_packs.py:78-87` existing pattern (append to tuple).
- `src/protokit/schema/lint/rules/__init__.py:117-124` BUILTIN_PACKS tuple format.

**Test scenarios:**
- *Happy path (Unit 1 itself is mostly test edits)*: `pytest tests/schema/lint/test_builtin_packs.py` passes — the 7th tuple member is now expected.
- *Happy path*: `pytest tests/test_changelog_d6b_entry.py` passes — `"D6b"` substring is in `CHANGELOG.md` (after Unit 3 lands the fold).
- *Sequencing constraint*: Unit 3 must land before this test passes in CI; the atomic-commit shape handles this (all 7 units in one commit).
- *Edge case*: `pytest tests/schema/lint/test_cli_package_same_e2e.py::TestRulePackExplicitLoadIsIdempotent` (renamed class) — 4 methods still pass, asserting `--rule-pack=...package_same` produces identical findings to bare invocation (idempotency regression).
- *Error path*: deliberate revert of `BUILTIN_PACKS` tuple (remove `package_same,`) — `pytest tests/schema/lint/test_builtin_packs.py` fails with the KD-9 3-step diagnostic.
- *Integration*: `pytest tests/schema/lint/test_cli_package_same_e2e.py` (full file) — `TestDormancyContract` is gone (deleted); other tests pass.

**Verification:**
- `pytest tests/schema/lint/test_builtin_packs.py tests/test_changelog_d6b_entry.py tests/schema/lint/test_cli_package_same_e2e.py -v` all green.
- `grep -n "TestDormancyContract" tests/` returns 0 matches.
- `grep -n "TestRulePackOptIn" tests/` returns 0 matches (renamed away).

---

- [ ] **Unit 2: Version bump 0.2.0 → 0.3.0 (R32)**

**Goal:** Single-line `pyproject.toml` version bump + verify downstream consumers reflect post-bump state.

**Requirements:** R32, S1.

**Dependencies:** None (independent of Unit 1; can land in any order within the atomic commit).

**Files:**
- Modify: `pyproject.toml` (L7: `version = "0.2.0"` → `"0.3.0"`)
- Verify-only: `src/protokit/_cli_utils.py:42-61` (uses `importlib.metadata.version("protokit")`; no edit; runtime version reflects post-bump after `pip install -e .[dev]` re-run)
- ~~`tests/test_builtin_lint_runtime_warnings.py:~346` schema_version~~ — **VERIFIED at /ce:plan time**: `lint_schema_version == "0.3"` already at lines 347 + 377; U5 handled this. No Unit 2 edit required.

**Approach:**
- Single-line edit to `pyproject.toml:7`. Confirm via `grep -n 'version =' pyproject.toml` shows the new value.
- `pyproject.toml` is the SOLE canonical version site (verified at plan-writing time: `grep -rn '__version__' src/` returns 0 matches). Do NOT introduce a derived `__version__` constant; runtime version access uses `importlib.metadata.version("protokit")` per the existing pattern at `_cli_utils.py:42-61`.
- **Runtime version cache**: `importlib.metadata` reads INSTALLED package metadata. After version bump, local dev `pip install -e .[dev]` re-run is required for `protokit lint --version` + SARIF `runs[0].tool.driver.version` to reflect 0.3.0. CI re-runs fresh per build — no CI issue. Local S6 verification + manual smoke test require the `pip install -e .[dev]` step.
- **Downstream-stale-reference verification**: run `grep -n 'schema_version.*"0\.2"' tests/` and `grep -n 'version.*"0\.2\.0"' tests/` after bump. Any hits in non-historical files (i.e., not in `tests/test_changelog_d6a_entry.py` which legitimately references the prior version) are U7 fix obligations.

**Patterns to follow:**
- `pyproject.toml` existing TOML format (no surrounding modifications).
- Prior version bumps in `CHANGELOG.md` (D6a U10's 0.1.x → 0.2.0 pattern at `CHANGELOG.md:435`).

**Test scenarios:**
- *Happy path*: `pyproject.toml` reads `version = "0.3.0"`.
- *Integration*: `pip install -e .[dev]` re-run picks up new metadata; `protokit lint --version` outputs `0.3.0` (manual smoke test).
- *Edge case*: any test that asserts `schema_version == "0.3"` or `version == "0.3.0"` continues passing. /ce:plan empirical verification confirmed zero stale `"0.2"` references in `tests/test_builtin_lint_runtime_warnings.py`.
- *Error path*: deliberate revert of pyproject.toml — version-presence tests fail.

**Verification:**
- `grep -c 'version = "0.3.0"' pyproject.toml` returns 1.
- `pytest tests/` count delta from Unit 2 alone is 0 (no new tests; no stale-reference fixes needed per /ce:plan empirical verification).

---

- [ ] **Unit 3: CHANGELOG-DRAFT fold + pre-upgrade migration recipe + strategic lede (R33)**

**Goal:** Fold the 3 staged CHANGELOG-DRAFT sections into a single `### D6b — 0.3.0` section in CHANGELOG.md with the pre-upgrade migration recipe (4-path TOML demotion + 4-step upgrade notes triage) + 2-sentence strategic lede matching D6a U10 precedent.

**Requirements:** R33, S1, S5, S7.

**Dependencies:** Should land in the same atomic commit as Unit 1 (so `test_changelog_d6b_entry.py` from Unit 1 passes immediately). Independent of Units 2/4/5/6/7 ordering.

**Files:**
- Modify: `CHANGELOG.md` (add new `### D6b — option-aware path + cross-language buf BASIC parity (0.3.0)` section above the existing D6a section; preserve all existing historical sections including BREAKING markers from D5).
- Modify: `CHANGELOG-DRAFT.md` (empty 3 staged sections to a header-only stub explaining the staging mechanism for future D6c+ units; preserve the file).

**Approach:**

Section structure (mirrors D6a U10 at `CHANGELOG.md:435-545`):

1. **Section header**: `### D6b — option-aware path + cross-language buf BASIC parity (0.3.0)`
2. **Strategic 2-sentence lede**: "D6b adds the first option-aware rules (R6 deprecated-replacement family) + cross-language buf-BASIC parity (R7 PACKAGE_SAME_* family), bringing `protokit lint` to **17 of 18 buf BASIC rules**. The 18th (`package/same-directory`) defers to D6c — its cross-file rule kind requires new ElementKind + LintLocation discriminant work scoped for its own architectural delivery."
3. **Added** (bullet list):
   - R6 5-rule deprecated-replacement family (`options/deprecated-{enum,enum-value,field,message,method}-must-have-replacement-comment`) — `warning` severity, `default` profile only. First option-aware rules + first leading-comment-introspection consumer.
   - R7 7-rule PACKAGE_SAME_* family (`package/same-{go-package,java-package,csharp-namespace,php-namespace,ruby-package,swift-prefix,java-multiple-files}`) — `error` severity, `recommended` + `default` profiles. Cross-language buf-BASIC parity. **Validated by U6's empirical parity gate** (21 SHA-pinned buf v1.69.0 NDJSON snapshots) per [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]].
   - R9 `severities_unloaded_rule` category value on `LintRuntimeWarning.category` Literal (**5th value MIGRATED at CLI-synthesized emit site**; engine-synthesized emit site unchanged — programmatic consumers should AUDIT existing `category == "unloaded_rule"` switch branches per [[value-migrated-vs-value-added-consumer-migration-2026-05-17]]).
   - Multi-file parity harness extension at `tests/parity/conftest.py` (`BufFinding` NamedTuple + 3 helpers reusable by future multi-file rule families).
   - Empirical parity gate at `tests/parity/test_parity_package_same.py` (21 parametrized cases + 5 collection-time invariants; recorded-snapshot mode runs in required `test` CI job).
4. **Wire-format**:
   - `lint_json.schema_version` + `lint_sarif.runs[0].properties.lint_schema_version` bumped `"0.2"` → `"0.3"` (shipped at D6b U5 per the closed-Literal-discriminator bump-contract in `_builtin_lint.py:227-270`).
5. **Behavior changes** (defaults; demotable):
   - R6 family fires as `warning` on `default` profile (NOT `recommended`). Multi-language teams using `--profile recommended` see ZERO new R6 findings.
   - **R7 family fires as `error` on `recommended` + `default` profiles. Multi-language teams will see NEW error-severity findings when option values disagree across files in a package** (e.g., `go_package`, `java_package`, `csharp_namespace` differing across files in the same proto package). Buf BASIC parity behavior; surfaces real cross-language config inconsistency.
6. **Pre-upgrade migration recipe** (matches D6a U10 precedent at `CHANGELOG.md:504-521`):

   Cross-language teams whose CI currently passes on protokit 0.2.0 with `--profile recommended` and whose protos have cross-file option disagreement will see RED CI on first 0.3.0 invocation. **4 numbered demotion paths, ranked by preference**:

   1. **Fix the disagreement (recommended)**. R7 fires because option values differ across files in the same package — buf v1.69.0 parity behavior treats this as a correctness signal. Decide a canonical value per `option_attr` per package; update outlier files to match.
   2. **Demote a specific R7 rule to `warning`** (per-rule escape hatch). Add to `pyproject.toml`:
      ```toml
      [tool.protokit.lint.severities]
      "package/same-go-package" = "warning"
      ```
      Multiple keys compose. Demoted rules still report findings but do not fail CI (under default `--min-severity error`). Demote to `info` for fully advisory output.
   3. **Disable a specific R7 rule** (sharper escape hatch — legitimate for INTENTIONAL disagreement):
      ```toml
      [tool.protokit.lint.severities]
      "package/same-go-package" = "off"
      ```
      Use sparingly for findings; legitimate when the disagreement is by design — e.g., a polyrepo where each `.proto` file ships in its own Go module has intentionally divergent `go_package` values; demoting `package/same-go-package` to `"off"` for this repo is the correct long-term answer, NOT a workaround. Disabled rules are invisible to downstream consumers of `lint_json`/`lint_sarif`; prefer demotion to `warning` when you want findings to remain visible.
   4. **Pin to the prior minor version** (deferral fallback — last resort):
      ```toml
      # pyproject.toml or requirements.txt
      "protokit~=0.2.0"
      ```
      Reserves time to address R7 findings on the team's schedule. **Cost**: pinning forgoes future 0.3.x bug fixes for the rule families you already use. Prefer paths 1-3 for teams who plan to remain on protokit beyond one quarter; re-evaluate at each 0.3.x patch release.

   **No pyproject.toml? Create a minimal one.** Paths 2-3 require a `pyproject.toml` for the `[tool.protokit.lint.severities]` overlay. Teams using `requirements.txt`-only Python tooling can add a 3-line stub at the repo root:
   ```toml
   [tool.protokit.lint.severities]
   "package/same-go-package" = "warning"
   ```
   protokit discovers `pyproject.toml` independently of pip/build tooling — the file does not need to define a build system. Path 4 (version pin in `requirements.txt`) is the only `requirements.txt`-only escape hatch.

7. **Upgrade-notes triage recipe** (matches D6a U10 precedent at `CHANGELOG.md:523-536`):
   ```
   1. Run `protokit lint --profile recommended <inputs>` against your protos.
   2. If exit code 0: no migration needed; the bump is clean.
   3. If R7 findings appear: choose one of the 4 demotion paths above per rule.
   4. If R6 findings appear (default profile only): add `[replaced-by: <X>]` comments to deprecated fields/methods/enums, OR demote `options/deprecated-*` rules via `[severities]` (warning → info).
   5. Re-run after applying demotion/fix; commit the updated pyproject.toml or proto fix.
   ```
8. **Consumer migration (Python API)** — uses MIGRATED framing per [[value-migrated-vs-value-added-consumer-migration-2026-05-17]]:
   - The `"severities_unloaded_rule"` value is the 5th `LintRuntimeWarning.category` Literal entry. **CLI-synthesized emit site MIGRATED** from `"unloaded_rule"` to `"severities_unloaded_rule"`; engine-synthesized emit site unchanged. Consumers switching on `category == "unloaded_rule"` should AUDIT their existing branches — not just extend switch tables. The 0.2 → 0.3 `schema_version` bump IS the documented signal that consumer switch tables need re-checking.
   - `LintRuntimeWarning.category` IS a CLOSED Literal DISCRIMINATOR: additions trigger `schema_version` minor bumps; consumer switch statements should be exhaustive. Contrast with `LintSeverity` ordering, which is an open ladder (additions do NOT trigger bumps).
9. **Deferred to D6c**: `package/same-directory` (R8 — 18th buf BASIC rule); R6 promotion to `error`; `strict` profile rule enumeration; per-rule disable/enable (R9b).

**CHANGELOG-DRAFT.md stub** (replace 3 unreleased sections + suggested-scope block; preserve top-of-file header):
```
# CHANGELOG-DRAFT — D6c+ staging

This file stages CHANGELOG content for the next 0.X.0 release. Per
[[dormant-code-changelog-draft-staging-delivery-boundary-2026-05-17]],
each in-flight unit appends its content here; the delivery-boundary
unit folds the staged sections into CHANGELOG.md alongside the
version bump.

D6b content folded into CHANGELOG.md as `### D6b — 0.3.0 (2026-05-18)`.
New D6c+ content begins below.
```

**Execution note:** Authoring the migration recipe is the load-bearing piece. Implementer SHOULD draft the recipe FIRST (before mechanical CHANGELOG-DRAFT fold) since the recipe is what enables S7 (user-journey: multi-language team can adopt without leaving CHANGELOG.md).

**Patterns to follow:**
- `CHANGELOG.md:435-545` D6a U10 0.2.0 section structure exactly (section header format, strategic lede shape, Added/Wire-format/Behavior bullet structure, demotion paths enumeration, upgrade notes recipe).
- `CHANGELOG-DRAFT.md:175-219` U7 eventual content scope suggested block — use as drafting reference (not verbatim copy).

**Test scenarios:**
- *Happy path*: `pytest tests/test_changelog_d6b_entry.py` passes (`"D6b"` substring in CHANGELOG.md).
- *Edge case*: CHANGELOG.md `### D6b` section exists ABOVE the existing `### D6a` section (newest-on-top convention, verified at /ce:plan time).
- *Edge case*: All 3 D6b CHANGELOG-DRAFT staged sections are deleted from CHANGELOG-DRAFT.md; only the header-only stub remains.
- *Integration*: `grep -c "package/same-go-package" CHANGELOG.md` returns at least 1 (the TOML snippet example in the migration recipe).
- *Integration (S7 dry-run)*: a fresh-eyes reader of CHANGELOG.md `### D6b — 0.3.0` section can copy-paste a `[severities]` TOML snippet to demote a specific R7 rule WITHOUT navigating outside the file.
- *Pre-fold preservation check (per ADV-12)*: capture baseline `grep -c "BREAKING" CHANGELOG.md` BEFORE writing the D6b section; post-fold count MUST be unchanged. D5 BREAKING markers at lines ~151, 166, 184, 288, 346 are historical artifacts and must be preserved verbatim. If counts diverge, an accidental truncation occurred during the fold.

**Verification:**
- CHANGELOG.md `### D6b — 0.3.0` section exists with all 8 subsections (Added, Wire-format, Behavior changes, Pre-upgrade migration recipe, Upgrade notes, Consumer migration, Deferred to D6c).
- CHANGELOG-DRAFT.md is header-only stub (no D6b U4b/U5/U6 staged sections; no U7 suggested-scope block).
- Manual S7 dry-run: a multi-language team CI failure can be addressed by copy-pasting from the CHANGELOG migration recipe alone.

---

- [ ] **Unit 4: README Schema Linting refresh + Public Surface DRAFT updates (R34 + R37)**

**Goal:** Update README Schema Linting section intro + rule table + new Upgrade notes parallel section + Public Surface DRAFT row updates (including the parent R6b-vs-R12 contradiction resolution to INTERNAL on the actual `source_info_descriptors` attribute name + simple "do not add" for the non-existent `_safe_for_findings`).

**Requirements:** R34, R37, S5.

**Dependencies:** Should land after Unit 3 (CHANGELOG section exists) so the README Upgrade notes section can reference it. Otherwise independent.

**Files:**
- Modify: `README.md` (Schema Linting intro at L480-492; rule table at L532-538; new Upgrade notes section after L545 [parallel to existing 0.1.x → 0.2.0 section]; Public Surface DRAFT table at L750-774)

**Approach:**

**Schema Linting intro (L480-492)**:
- Current: "5 packs … 17 rules".
- Update: "**6 packs … 24 rules** (`recommended` profile). As of 0.3.0, protokit lint covers **17 of 18 buf BASIC rules** (the 18th, `package/same-directory`, defers to D6c)."
- Add `package_same` to inline pack list.

**Rule table (L532-538)**:
- Current: `recommended | 17 | Buf BASIC parity. The full D6a rule library — naming (9), enum (2), imports (3), package (2), file (1)`.
- Update: `recommended | 24 | Buf BASIC parity (17 of 18 buf BASIC rules; package/same-directory defers to D6c). naming (9), enum (2), imports (3), package (2), file (1), package_same (7).`
- Current: `default | 17 | Forward-placeholder for the D6b option-aware differentiator. Structurally equal to recommended in 0.2.0`. **MUST be rewritten** post-U7.
- Update: `default | 29 | Buf BASIC parity (recommended's 24 rules) + R6 deprecated-replacement family (5 warning-severity option-aware rules).`
- **Optional polish (per FEAS-5)**: `essentials` row at L534 has stale `Empty in the 0.2.0 release` clause; either drop the version-pinned clause entirely or replace with `Empty as of 0.3.0`. Low priority — the semantic content (0 rules) remains accurate.

**Buf BASIC rule-count verification (per FEAS-7)**: the "17 of 18 buf BASIC rules" claim assumes buf v1.69.0's BASIC profile contains exactly 18 rules. Before authoring the claim, verify via `buf config ls-lint-rules --version v1` (or equivalent SHA-pinned reference). If the denominator differs, refine the claim to match. The 21-snapshot empirical foundation at `tests/parity/_buf_smoke/recorded/` covers only the 7 PACKAGE_SAME_* rules, NOT all of buf BASIC, so it does not independently validate the 18-rule denominator.

**New Upgrade notes section (parallel to L545 existing 0.1.x → 0.2.0 section)**:
```markdown
### Upgrade notes (0.2.x → 0.3.0)

D6b adds the first option-aware rules (R6) + cross-language buf-BASIC parity (R7), bringing protokit lint to 17 of 18 buf BASIC rules. Multi-language teams will see new error-severity findings on cross-file option disagreement.

See `CHANGELOG.md` `### D6b — 0.3.0` section for:
- Full additions enumeration (R6 + R7 + R9 + parity gate + multi-file harness)
- Wire-format changes (`schema_version` 0.2 → 0.3)
- Behavior changes (R7 firing default-on as error)
- **Pre-upgrade migration recipe** (4 numbered TOML demotion paths)
- Upgrade-notes triage recipe (5-step adoption walkthrough)
- Consumer migration (Python API audit for `LintRuntimeWarning.category` switch tables)
```

**Public Surface DRAFT updates (L750-774)**:
- ADD: `| Python class field | CompileResult.source_info_descriptors (Mapping[str, FileDescriptorProto] \| None) | INTERNAL |` (per KD-7; R6b's source-locations index concept landed at U2 under this renamed attribute, NOT as `source_locations`; verified at `src/protokit/schema/compile.py:231`).
- ADD: `| Python module | BUILTIN_PACKS (includes package_same family of 7 rules as of 0.3.0) | IN |` (per R31).
- ADD: `| Python function | leading_comment(source_info_descriptors, file_name, path) in protokit.schema.lint.rules.options._comments | IN |` (actual shipped signature; the parent brainstorm's `_LintContextEmitMixin.leading_comment(path)` method sketch was not what U2 implemented).
- ADD: R6 + R7 rule_ids enumerated within the existing rule-set row.
- **Do NOT add a `_safe_for_findings` row** (KD-8; function does not exist — never implemented; U2 used `_safe_for_stderr` directly).
- **UPDATE `Profile names` row at L765**: replace `default is forward-placeholder for D6b differentiator` with `default extends recommended with R6 deprecated-replacement family (5 warning-severity option-aware rules as of 0.3.0)`. Parallels the rule-table rewrite at L536.
- **UPDATE `LintRuntimeWarning.category` row**: from `category Literal` to `category: Literal[<5 values enumerated: "rule_exception", "unloaded_rule", "rule_exit", "rule_pack", "severities_unloaded_rule">] — CLOSED DISCRIMINATOR`. Mark explicitly that additions trigger `_LINT_JSON_SCHEMA_VERSION` minor bump per the bump-contract at `_builtin_lint.py:227-270`. Distinguish from `LintSeverity` ordering (open ladder; additions do NOT trigger bumps).
- VERIFY: `lint_json["schema_version"]: "0.3"` row (L760) + SARIF `lint_schema_version: "0.3"` row (L763) — already at "0.3" per U5; no edit needed.

**Patterns to follow:**
- Existing `### Upgrade notes (0.1.x → 0.2.0)` section at README.md:545 as the template for the 0.2.x → 0.3.0 parallel.
- Existing Public Surface DRAFT row format (`| Surface | Element | Status |`).

**Test scenarios:**
- *Happy path*: `grep -c "17 of 18 buf BASIC rules" README.md` returns at least 1 (intro + rule table claim).
- *Happy path*: `grep -c "Upgrade notes (0.2.x → 0.3.0)" README.md` returns 1.
- *Happy path*: `grep -c "package_same" README.md` returns at least 3 (intro pack list + rule table + Public Surface DRAFT).
- *Edge case*: `grep "_safe_for_findings" README.md` returns 0 matches (vestigial row absent).
- *Edge case*: `grep "CompileResult.source_locations" README.md` returns 1+ match with "INTERNAL" status (not "IN").
- *Edge case*: `grep "CLOSED DISCRIMINATOR" README.md` returns 1 (LintRuntimeWarning.category row).

**Verification:**
- Visual inspection of README Schema Linting section reads as 0.3.0-shipped (no dormant/opt-in/deferred prose).
- Rule counts in the table arithmetic check: `recommended` 24 = 17 D6a + 7 R7; `default` 29 = 24 recommended + 5 R6.

---

- [ ] **Unit 5: Bump-contract docstring presence-ratchet test (R35)**

**Goal:** Add presence-ratchet test pinning the closed-Literal-discriminator distinction in `_builtin_lint.py:227-270` bump-contract block. Source-read pattern via `inspect.getsource(module)`.

**Requirements:** R35, S6.

**Dependencies:** None (independent of other units).

**Files:**
- Modify: `tests/test_builtin_lint_formatter.py` (add new test method, likely under existing test class or new `TestBumpContractDocstring` class)

**Approach:**

**Implementation pattern (Pattern B per [[presence-ratchet-test-pattern-for-prose-substrings-2026-05-14]] + repo research)**:
- Use `inspect.getsource(_builtin_lint_module)` to read the entire module source as a string. The bump-contract block is a `#:` Sphinx-style comment ABOVE `_LINT_JSON_SCHEMA_VERSION`, NOT a Python `__doc__` attribute — runtime introspection via `__doc__` does NOT work.
- Assert presence of the 4 pinned substrings (3 contract-pinning + 1 historical-fact-anchor).
- Failure message names BOTH correction paths (restore substring OR update RATCHET_SUBSTRINGS after confirming semantic equivalence).

**Pinned substring set (verified at /ce:plan time + corrected for line-wrap)**:
1. `"Closed Literal discriminators"` — closed-Literal framing (line 257, single source line).
2. `"additions DO bump the"` — directional contract for closed Literals (line 262). **Corrected from original `"additions DO bump the version"` per FEAS-1 line-wrap bug**: the original 6-word phrase spans lines 262-263 via `#:` continuation prefix, so `inspect.getsource` returns it interrupted by `\n#:         `; the 5-word fragment is the longest contiguous on-line substring preserving the positive directional contract.
3. `"Open severity-string ladders"` — open-ladder distinction (line 251, single source line).
4. `'"severities_unloaded_rule"'` — D6b U5 historical-fact anchor (line 268, includes literal `"` chars).

**Test method structure** (directional sketch, not implementation specification):
```python
def test_bump_contract_docstring_preserves_closed_literal_distinction() -> None:
    """Presence ratchet pinning the bump-contract block at _builtin_lint.py:227-270.

    NOT a stability contract over wording; this asserts that 4 load-bearing
    substrings remain present. If a future docstring rewrite changes the
    wording while preserving the contract, update RATCHET_SUBSTRINGS after
    confirming semantic equivalence. If the contract itself is dropped
    (e.g., the closed-vs-open distinction is removed), restore the
    substring or capture the new contract in a fresh learning + cross-ref.
    """
    import inspect
    from protokit.formatters import _builtin_lint
    source = inspect.getsource(_builtin_lint)
    ratchet_substrings = (
        "Closed Literal discriminators",
        "additions DO bump the",  # FEAS-1: trimmed to avoid #: line-wrap
        "Open severity-string ladders",
        '"severities_unloaded_rule"',
    )
    for substring in ratchet_substrings:
        assert substring in source, (
            f"Bump-contract substring {substring!r} missing from "
            f"src/protokit/formatters/_builtin_lint.py (bump-contract "
            f"block at lines 227-270). Either restore the substring or "
            f"update RATCHET_SUBSTRINGS after confirming the contract "
            f"is preserved semantically. See "
            f"[[closed-literal-discriminator-bump-trigger-2026-05-17]] "
            f"for the load-bearing contract."
        )
```

**Substring selection criterion** (per origin brainstorm R35 refinement): each substring is (a) load-bearing — paraphrasing that preserves the contract keeps all substrings; rewording that drops the contract drops at least one; AND (b) at least one substring pins the DIRECTIONAL contract ("DO bump the version") — not just framing nouns.

**Patterns to follow:**
- Pattern B (inspect.getsource + substring assertion) per `tests/schema/lint/cli/test_r9a_severities_overlay.py:200-218` precedent.
- Pattern C (file-read + substring) used by `tests/test_changelog_d6a_entry.py` for CHANGELOG ratchets — comparable but different file-type target.

**Test scenarios:**
- *Happy path*: at HEAD, the test passes — all 4 substrings present in `_builtin_lint.py`.
- *Error path*: deliberate `sed -i 's/Closed Literal discriminators/Closed type markers/' src/protokit/formatters/_builtin_lint.py` causes test to fail with the structured diagnostic naming the missing substring + both correction paths.
- *Edge case*: ratchet substring contains the literal `"` character (`'"severities_unloaded_rule"'`) — verify escape handling in the assertion message.
- *Future-maintenance note (in test docstring, not implementation work)*: If a future docstring rewrite trips the ratchet, the maintainer applies the criterion at that time — either restore the substring (contract preserved; just reworded) OR update `ratchet_substrings` (contract evolved; capture in a fresh learning). Calibration is reactive, not proactive — the 4 verified substrings are sufficient signal at U7 ship time.

**Verification:**
- `pytest tests/test_builtin_lint_formatter.py::test_bump_contract_docstring_preserves_closed_literal_distinction -v` passes.
- Manual deliberate-break test: revert one substring → test fails with structured diagnostic.

---

- [ ] **Unit 6: Stale-forward-looking-text sweep (R36)**

**Goal:** Sweep 12 enumerated dormancy-window forward-looking-text sites in `src/` + `tests/` (10 from origin + 2 added during /ce:plan empirical verification). Apply binary scope rule as INVARIANT (NEVER edit `docs/brainstorms/`, `docs/plans/`, `docs/solutions/`). Plus R38 TODOS.md update (rolled in from former Unit 7 per SCOPE-6).

**Requirements:** R36, R38, S5.

**Dependencies:** Independent of other units. Site 5 (parity-test `--rule-pack` flag removal) depends conceptually on R31's BUILTIN_PACKS flip + engine idempotency (already-shipped), but mechanically the flag removal works regardless of R31 timing — engine idempotency is unchanged.

**Files** (all 12 sites enumerated in Context & Research + TODOS.md):
- Modify: `src/protokit/schema/lint/cli.py` (site 1: --help epilog)
- Modify: `tests/schema/lint/test_cli_package_same_e2e.py` (sites 2 + 3 + 12: TestDormancyContract DELETE + TestRulePackOptIn RENAME — handled by Unit 1, no duplicate edits — plus site 12 file-level docstring rewrite)
- Modify: `tests/parity/test_parity_package_same.py` (sites 4-inline + 5 + 6: module docstring tense verify inline with Site 5 work + `--rule-pack` flag + `_RULE_PACK` constant removal + `_build_package_same_rule_id_map` docstring update)
- Modify: `tests/parity/conftest.py` (site 7: `_build_package_same_proto_to_buf` docstring update)
- Modify: `src/protokit/schema/lint/rules/package_same.py` (sites 8 + 11: module docstring rewrite + RULES tuple section header comment rewrite)
- Modify: `src/protokit/schema/lint/rules/__init__.py` (site 9: dormancy commentary block — preserve historical-fact framing, delete DELIBERATELY-NOT paragraph; noqa F401 at L76 already removed by Unit 1)
- Modify: `src/protokit/schema/lint/engine.py` (site 10: deferred-import docstring tense update)
- Modify: `TODOS.md` (R38 — see "TODOS.md update (R38)" sub-section below)

**Approach:**

**Pre-sweep INVARIANT step**: before running ANY grep or edit, capture baseline: `git status` (verify clean working tree). Apply binary scope rule rigorously: `git diff --stat -- docs/brainstorms/ docs/plans/ docs/solutions/` MUST be empty after the sweep. If non-empty post-sweep, run `git checkout -- docs/brainstorms/ docs/plans/ docs/solutions/` to revert BEFORE commit. The 68 stale-looking references in those directories are HISTORICAL ARTIFACTS — correct in their original timestamped context.

**Sites 2 + 3 (TestDormancyContract DELETE + TestRulePackOptIn RENAME)** are already handled by Unit 1; no duplicate edits needed.

**Sites 1, 4-inline, 5, 6, 7, 8, 9, 10, 11, 12** are this Unit's actual edits.

Specific text changes (high-level — `/ce:work` resolves exact wording):

- Site 1 (`cli.py:280-283`): DELETE entire `--help` epilog block ("Opt into the dormant PACKAGE_SAME_* rule family (R7) ... until 0.3.0: ... --rule-pack=...") OR replace with active-state note ("PACKAGE_SAME_* (R7) family in `recommended` + `default` profiles since 0.3.0."). Recommend DELETE entirely — `--help` should not enumerate rules; that's README scope.
- Site 4 (inline with Site 5): `test_parity_package_same.py:16-22` module docstring. Verify the paragraph reads as historical post-flip context; minor tense edit if needed (e.g., "When U7 flips BUILTIN_PACKS" → "Since U7's BUILTIN_PACKS registration"). If already correct, no edit.
- Site 5 (`test_parity_package_same.py`): REMOVE `rule_pack=_RULE_PACK` kwarg from `run_protokit_lint_multi_file(...)` call in `test_parity_byte_matches_recorded_snapshot`; REMOVE module-level `_RULE_PACK` constant.
- Site 6 (`test_parity_package_same.py:83-90`): `_build_package_same_rule_id_map` docstring: "R7 is NOT in BUILTIN_PACKS until U7 (per KD-4)" → past tense: "Until U7, R7 was not in BUILTIN_PACKS, so the local walk kept derivation isolated from BUILTIN_PACKS sequencing. Post-U7, retained for assertion-module isolation."
- Site 7 (`conftest.py:171-199`): `_build_package_same_proto_to_buf` docstring: same past-tense framing pattern.
- Site 8 (`package_same.py:89-97`): module docstring rewrite from dormant-code framing to active-state: "R7 PACKAGE_SAME_* family — cross-language namespace consistency rules, default-on under `recommended` + `default` profiles as of 0.3.0."
- Site 9 (`rules/__init__.py:80-94`): preserve "imported here so users can opt in via `--rule-pack` ... AND so the cold-import regression test has a known forbidden-modules target"; DELETE "DELIBERATELY NOT in BUILTIN_PACKS ... deferred to U7" paragraph.
- Site 10 (`engine.py:519-526`): deferred-import docstring "Once U7 registers package_same in BUILTIN_PACKS, ... becomes a no-op" → past tense: "Since U7 registered package_same in BUILTIN_PACKS, the deferred import is a no-op at runtime."
- Site 11 (`package_same.py:537-540`): RULES tuple section header comment block: `# NOT registered in default BUILTIN_PACKS until U7 (deferred per [[pre-1.0-version-bump-as-communication-contract]] alongside the 0.2.0 -> 0.3.0 version bump).` → REWRITE: `# Registered in default BUILTIN_PACKS as of 0.3.0; the --rule-pack opt-in flag remains supported as an idempotent explicit load.`
- Site 12 (`tests/schema/lint/test_cli_package_same_e2e.py:1-19`): file-level module docstring beginning `"Verifies the dormant-by-default contract: until U7 registers package_same in BUILTIN_PACKS..."` → REWRITE: `"""End-to-end CLI tests for the R7 PACKAGE_SAME_* family (D6b U4b; default-on in BUILTIN_PACKS as of 0.3.0).\n\nVerifies that --rule-pack is an idempotent explicit-load path post-0.3.0; --proto vs --descriptor-set parity per SC 14 of the per-unit plan; --profile recommended/default both fire R7 per the @lint_rule metadata."""`

**Verification grep** (post-sweep): `git grep -nE 'dormant|dormancy|until U7|deferred to U7|post-U7|U7 flip|not yet in BUILTIN_PACKS|U7 registers|U7 alongside' src/ tests/`. Should return ZERO hits in active code. No exclusions needed.

**TODOS.md update (R38)** — pre-enumerated entries to retire (per ADV-11):
1. **`severities_unloaded_rule` semantic-category-conflation backlog entry** (`TODOS.md` lines ~165-171 — already says "Shipped in D6b 0.3.0 (U5)"). Verify wording is final post-merge; no further action needed if already complete.
2. **Remaining-deliveries header** (line ~79: "remaining deliveries (D6b, D7)") → change to "remaining deliveries (D6c, D7)".
3. **D6b backlog section header** (line ~163: "D6b backlog items surfaced during D6a") → mark section header as resolved; collapse/retain entries that survived as D6c work, retire those completed.
4. **Cross-language PACKAGE_SAME_* rule family entry** (lines ~176-180): if marked as "in progress" or "deferred", update to "Shipped in D6b 0.3.0 (U4a/U4b/U6/U7)".
5. **Option-aware differentiator path** (lines ~185-190): includes the never-implemented `_safe_for_findings()` reference; remove that bullet (function does not exist per KD-8); update remaining bullets to reflect D6b R6 family is shipped.
6. **New D6c remaining-deliveries entry**: add `### D6c — package/same-directory + strict profile + R9b disable/enable + R8 README polish` as the next-delivery placeholder.

If TODOS.md sections have drifted since /ce:plan-time enumeration (2026-05-18), implementer re-locates via substring search (`grep -n 'D6b\|severities_unloaded\|PACKAGE_SAME' TODOS.md`).

**Patterns to follow:**
- [[stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12]] discipline.
- [[delivery-boundary-unit-commit-composition-2026-05-14]] TODOS.md retirement pattern.
- Past-tense framing for historical rationale; active-tense for present behavior.
- D6a U10's TODOS.md update pattern (look for what was retired at the prior delivery boundary as a reference).

**Test scenarios:**
- *Happy path*: full pytest suite still passes after all 10 site edits (sites 2+3 handled by Unit 1).
- *Edge case*: Parity test `pytest tests/parity/test_parity_package_same.py` 27 tests pass after `--rule-pack` flag removal — engine idempotency carries the contract.
- *Integration*: `git diff --stat -- docs/brainstorms/ docs/plans/ docs/solutions/` is empty (binary scope rule honored as INVARIANT).
- *Verification*: post-sweep grep returns zero meaningful hits.
- *TODOS.md update*: pure documentation; no test expectation.

**Verification:**
- All affected files compile/import cleanly.
- `pytest tests/` count change from Unit 6 alone: -2 tests (TestDormancyContract deletion) handled by Unit 1; no additional delta from Unit 6.
- Manual visual inspection of each site reads as 0.3.0-shipped active framing.
- TODOS.md no longer references R7 dormancy / U7-deferred items; D6c entry exists in remaining-deliveries.

## System-Wide Impact

- **Interaction graph**: R31's BUILTIN_PACKS flip changes the engine's default rule loadout. Every `protokit lint --profile recommended` invocation post-merge loads R7's 7 rules. R31's atomic-coupled test updates (Unit 1) maintain CI integrity at the moment of flip.
- **Error propagation**: R7 fires as `error` on `recommended` + `default` — multi-language teams' CI may go red on the upgrade. R33's pre-upgrade migration recipe is the user-side mitigation; the CHANGELOG provides the demotion syntax escape hatch directly.
- **State lifecycle risks**: None — U7 is metadata + rule-registration + documentation. No persistent state, no caches, no migration concerns.
- **API surface parity**: Public Surface DRAFT updates (Unit 4) pin the new API contracts (`CompileResult.source_info_descriptors` INTERNAL — the actual shipped attribute name; `LintRuntimeWarning.category` 5-value CLOSED DISCRIMINATOR; `leading_comment(source_info_descriptors, file_name, path)` IN as a free function). The Literal type contract is pinned at TWO layers post-U7: (1) R37's DRAFT-table CLOSED DISCRIMINATOR marker (user-facing surface), (2) R35's presence-ratchet test (source-layer contract).
- **Integration coverage**: U6's parity gate (27 tests at `tests/parity/test_parity_package_same.py`) is the runtime verification that R7's BUILTIN_PACKS-loaded behavior byte-matches buf v1.69.0. After Unit 6 removes the `--rule-pack` flag, engine idempotency carries the same contract.
- **Unchanged invariants**: Engine's `load_rule_pack` idempotency (engine.py:241-242) is preserved. The `_LINT_JSON_SCHEMA_VERSION` constant (already "0.3" since U5) is unchanged. The 21 SHA-pinned buf v1.69.0 NDJSON snapshots are unchanged. The R6 + R7 + R9 helper code is unchanged (U7 doesn't modify any production code beyond docstrings in package_same.py + engine.py + rules/__init__.py).

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Multi-language teams hit RED CI on 0.3.0 upgrade without finding the demotion syntax | R33's pre-upgrade migration recipe with 4 numbered TOML demotion paths + "No pyproject.toml?" mini-section (3-line stub) + 4-step upgrade-notes triage matches D6a U10 precedent exactly. S7 verifies copy-paste-from-CHANGELOG is sufficient for both pyproject.toml and requirements.txt-only teams. |
| Parent D6b brainstorm R6b vs R12 contradiction on `source_locations` classification + name | KD-7 resolves to INTERNAL on the actual shipped attribute name (`source_info_descriptors`, not `source_locations` — verified at `compile.py:231`). Documented in U7 plan-of-record + CHANGELOG Consumer migration bullet; parent brainstorm not retroactively edited (per R36 binary scope rule). |
| `TestRulePackOptIn` was originally planned for deletion in brainstorm; repo research reveals 4 methods are meaningful regression coverage | KD-9 RENAMES class (not deletes) + updates docstrings to reflect post-flip purpose (idempotency regression citing BOTH the engine module-name short-circuit AND the LintProfile.compose frozenset union mechanisms). |
| R36 grep sweep surfaces additional hits in `docs/` tree | R36 binary scope rule (Unit 6): pre-sweep INVARIANT step + `git diff --stat -- docs/brainstorms/ docs/plans/ docs/solutions/` MUST be empty post-sweep. Any non-zero diff reverted via `git checkout -- docs/{brainstorms,plans,solutions}/` BEFORE commit. |
| R35 substring set may be too wording-pinned (causes false positives on minor docstring rewrites) | Reactive calibration noted in test docstring; if a future maintainer trips the ratchet, they decide between restore-substring vs update-substrings at that time. Substring 2 already corrected at /ce:plan time (`"additions DO bump the version"` was line-wrapped; trimmed to `"additions DO bump the"`). |
| Atomic-commit shape: any P0/P1 ce:review finding blocks the entire feat commit | **Recovery protocol** (see Open Questions → Deferred to Implementation): partition fallback available — if Unit 3 (CHANGELOG) or Unit 4 (README) draws a P0/P1, land Units 1+2+5+6 as a smaller delivery-boundary commit and address Unit 3/4 as a follow-up commit before tagging 0.3.0. Atomic-by-default; partition is the documented escape. |
| TestDormancyContract deletion may drop happy-path coverage (clean fixture + recommended profile + exit_code == 0) | Unit 6 Site 2 includes ADV-8 pre-deletion analysis: verify coverage elsewhere (`grep -rn 'exit_code == 0' tests/schema/lint/test_cli_package_same_e2e.py tests/schema/lint/test_engine_*.py`); if uncovered, repurpose one deleted method as `test_recommended_profile_clean_fixture_exit_zero` with AGREEING fixture values. |
| Local runtime version cache stale post-bump | Unit 2 documents `pip install -e .[dev]` re-run requirement; CI re-runs fresh per build. S6 manual smoke test requires the re-run step. |
| `pip install -e .[dev]` re-run is required for local runtime version to reflect 0.3.0 | Unit 2 documents this in the Approach section. CI re-runs fresh per build; local S6 manual smoke test requires the step. |
| Atomic-commit shape means any single Unit failing review blocks the entire unit from landing | All 7 units have been verified independently feasible (Unit 1 atomic coupling verified; Unit 2 sole version site verified; Unit 3 CHANGELOG sites verified; Unit 4 README sites verified; Unit 5 source-read pattern verified; Unit 6 10 sites enumerated; Unit 7 TODOS.md update is mechanical). Risk: low. |

## Documentation / Operational Notes

- **CHANGELOG.md** is the user-facing release notes. R33's content is load-bearing for user adoption.
- **README.md** is the project's entry-point documentation. R34's targeted refresh keeps the Schema Linting section accurate at 0.3.0 ship time; full restructure deferred to a future doc-polish unit.
- **No CI workflow changes**. U6's parity tests run in the required `test` job; that arrangement carries forward through U7's flip.
- **`CHANGELOG-DRAFT.md` stays as empty stub** — preserves the file path + pattern for D6c+ units to find.
- **POST-MERGE: `MEMORY.md` + `project_state.md` update** — refresh auto-loaded hooks to reflect "D6b complete; 0.3.0 shipped; next delivery D6c". Out-of-repo artifact per origin KD-6 + KD-6 here.

## Residual Concerns (deferred to ce:work, with brainstorm-decided framing as authoritative)

The U7 plan went through document-review (2026-05-18) with 5 reviewers returning 42 findings. 27 were auto-applied as factual/structural corrections. The 7 product-lens findings below were surfaced and **deferred** — they re-open strategic decisions the user settled at brainstorm time (pre-1.0 plain framing, targeted README scope, no `lite` profile, no `strict` profile in 0.3.0). They are documented here so ce:work has visibility, and so future-revisit triggers are explicit:

- **PROD-1 (P1) — Lede framing optimizes for catch-up narrative**: the strategic lede "17 of 18 buf BASIC rules" leads with parity arithmetic rather than R6's differentiated capability (option-aware leading-comment introspection — a capability buf BASIC does not have). Concern: invites unfavorable buf comparison; lede ceiling effect. **Deferred status**: brainstorm-decided framing stands. **Revisit trigger**: if 0.3.0 adoption stalls and competitive-positioning conversations surface, invert the lede in 0.4.0 CHANGELOG and README intro.

- **PROD-2 (P1) — Migration recipe biases toward "fix; demote is workaround"**: the 4 paths are ranked "fix the disagreement (recommended)" first, demote-paths as 2nd-tier. Concern: teams under deadline pressure pick path 4 (pin) wholesale, becoming effective non-adopters. **Deferred status**: PROD-8 was applied (the path 3 escape-hatch description now includes the polyrepo `go_package` example as legitimate-INTENTIONAL framing). The path-ranking shape remains as drafted. **Revisit trigger**: if PyPI download data shows >40% of 0.2.x users pin to `~=0.2.0` 4-6 weeks post-ship, reframe the recipe in a 0.3.x patch CHANGELOG addendum.

- **PROD-3 (P2) — Pre-1.0 "no BREAKING prefix" too quiet for default-on ERROR flip**: D6a U10 was additive rule expansion; D6b U7 is behavior change for ERROR-severity rules in `recommended`. Concern: adopters with auto-bump dependabot configs hit RED CI without visible signal. **Deferred status**: KD-1 brainstorm decision (pre-1.0 plain framing matching D6a U10) stands. **Revisit trigger**: if GitHub issue volume from "I didn't see the breaking change" reports exceeds 5 within 2 weeks of ship, add a `Behavior change` callout block in a 0.3.1 README patch.

- **PROD-4 (P2) — Opportunity cost: shipping 0.3.0 without `strict` profile commits R7 placement to `recommended`**: alternative architectural shape was: ship `strict` profile in 0.3.0, place R7 there, leave `recommended` unchanged at 17 rules. Concern: locking R7 into `recommended` precludes a future `strict`-first graduation path; `recommended` becomes increasingly the "break my CI on upgrade" profile. **Deferred status**: D6c brainstorm scope (strict profile rule enumeration) will revisit R7 placement options once `strict` machinery exists. KD-10's "Future-revisit triggers" enumerate the conditions that would justify moving R7 out of `recommended`.

- **PROD-5 (P2) — New-adopter friction increases**: post-U7, a brand-new adopter running `protokit lint --profile recommended` on first proto repo sees 24 rule findings (up from 17), including 7 ERROR-severity R7 findings about cross-file option disagreement. Concern: "found 47 problems on first run" is a different product feel from "found 12 problems on first run." **Deferred status**: brainstorm decided "Schema Linting section + rule table + profile descriptions (Recommended)" README scope; no new-adopter-focused first-run-expectations note was scoped. **Revisit trigger**: if a `lite` or first-run-friendly profile becomes a recurring user request, scope it for D6c+.

- **PROD-6 (P2) — Pin-to-old-version inversion check missing**: S7's success criterion is "user can adopt 0.3.0 without leaving CHANGELOG.md." But if 80% of existing 0.2.x users pin (path 4) rather than migrate, U7 has shipped "successfully" by every plan metric and failed at the product level. **Deferred status**: no telemetry mechanism exists; post-ship PyPI version-distribution monitoring is a soft follow-up. **Revisit trigger**: KD-10's PyPI-download trigger covers this; an in-tool nudge (advisory on 0.3.0 install when `~=0.2.0` pin is detected) is a candidate for 0.3.1.

- **PROD-7 (P3) — R9b deferral rationale**: U7's migration recipe routes users to `[severities] = "off"` as the de-facto disable mechanism. R9b (per-rule disable/enable CLI flag) is deferred to D6c pending real-demand evidence. Concern: locking in `severities = "off"` as the disable mechanism may foreclose a cleaner R9b shape later. **Deferred status**: D6c will evaluate whether R9b adds capability beyond what `[severities] = "off"` provides.

These concerns are **structurally documented** so ce:work treats them as known-deferred rather than unknown-unknown; the implementation proceeds with the brainstorm-decided framing as authoritative.

## Sources & References

- **Origin document**: [docs/brainstorms/2026-05-18-d6b-u7-delivery-boundary-0-3-0-release-requirements.md](../brainstorms/2026-05-18-d6b-u7-delivery-boundary-0-3-0-release-requirements.md)
- **Predecessor brainstorm**: [docs/brainstorms/2026-05-14-protokit-lint-delivery-6b-option-aware-and-multi-language-requirements.md](../brainstorms/2026-05-14-protokit-lint-delivery-6b-option-aware-and-multi-language-requirements.md)
- **Predecessor plans**: [docs/plans/2026-05-17-001-feat-d6b-u4-r7-package-same-plan.md](2026-05-17-001-feat-d6b-u4-r7-package-same-plan.md), [docs/plans/2026-05-17-002-feat-d6b-u4-r7-package-same-revised-plan.md](2026-05-17-002-feat-d6b-u4-r7-package-same-revised-plan.md), [docs/plans/2026-05-18-001-feat-d6b-u6-r7-package-same-parity-tests-plan.md](2026-05-18-001-feat-d6b-u6-r7-package-same-parity-tests-plan.md)
- **D6a U10 precedent (delivery-boundary)**: commit `1b59cae`; CHANGELOG.md:435-545 D6a section.
- **Related code**:
  - `src/protokit/schema/lint/rules/__init__.py:76,117-124` (BUILTIN_PACKS + import)
  - `src/protokit/schema/lint/cli.py:280-283` (R7 opt-in --help epilog)
  - `src/protokit/schema/lint/engine.py:241-242` (idempotent load_rule_pack), `:519-526` (deferred-import docstring)
  - `src/protokit/schema/lint/rules/package_same.py:89-97` (module docstring)
  - `src/protokit/formatters/_builtin_lint.py:227-270` (bump-contract block)
  - `tests/parity/conftest.py:171-199` (_build_package_same_proto_to_buf)
  - `tests/parity/test_parity_package_same.py:16-22,83-90` (module + helper docstrings)
  - `tests/schema/lint/test_cli_package_same_e2e.py:85-149` (TestDormancyContract), `:157-327` (TestRulePackOptIn)
  - `tests/schema/lint/test_builtin_packs.py:78-87` (expected-tuple)
  - `tests/test_changelog_d6a_entry.py` (presence-ratchet template)
  - `pyproject.toml:7` (version)
  - `README.md:480-492,532-538,545,750-774` (Schema Linting + rule table + Upgrade notes + Public Surface DRAFT)
  - `CHANGELOG.md:435-545` (D6a U10 precedent)
  - `CHANGELOG-DRAFT.md:16-219` (staged sections + suggested-scope)
- **Related institutional learnings** (per U7 ce:plan learnings-researcher pass):
  - [[delivery-boundary-unit-commit-composition-2026-05-14]] (CORE — 7-component checklist)
  - [[pre-1.0-version-bump-as-communication-contract-2026-05-14]] (CORE — no BREAKING prefix; migration recipe required)
  - [[presence-ratchet-test-pattern-for-prose-substrings-2026-05-14]] (CORE — source-read pattern)
  - [[stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12]] (CORE — binary scope rule)
  - [[dormant-code-changelog-draft-staging-delivery-boundary-2026-05-17]] (CORE — U_final checklist)
  - [[wire-format-schema-version-bump-contract-and-absence-semantic-2026-05-17]] (SUPPORTING — schema_version bump documentation)
  - [[closed-literal-discriminator-bump-trigger-2026-05-17]] (SUPPORTING — R35 substring set)
  - [[value-migrated-vs-value-added-consumer-migration-2026-05-17]] (SUPPORTING — MIGRATED framing for severities_unloaded_rule)
  - [[semantic-category-conflation-accepted-tradeoff-literal-widening-2026-05-13]] (SUPPORTING — three-site discipline verification)
  - [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]] (CONTEXTUAL — gate authorizes BUILTIN_PACKS flip)
  - [[truncation-guard-odd-count-discipline-for-doubled-escape-pairs-2026-05-18]] (PERIPHERAL — U6 helper fix shipped)
