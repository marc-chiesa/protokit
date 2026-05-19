---
title: "feat: D6c — R8 + R8b cross-file directory/package rules (Arch-D pre-walk accumulator) + 25/26 buf BASIC parity (0.4.0)"
type: feat
status: active
date: 2026-05-18
origin: docs/brainstorms/2026-05-18-d6c-r8-cross-file-package-same-directory-requirements.md
---

# feat: D6c — R8 + R8b cross-file directory/package rules + 25/26 buf BASIC parity (0.4.0)

## Overview

Ship the architectural delivery that introduces cross-file lint rule dispatch to protokit-lint via the **Arch-D pre-walk accumulator pattern** — a sibling to R7's `_build_package_options_accumulator` at `src/protokit/schema/lint/engine.py:488`. The delivery includes two dual cross-file rules sharing one accumulator (R8 `package/same-directory` + R8b `package/directory-same-package`), bumps protokit's buf BASIC coverage from 23/26 to **25/26**, retires two D6b hygiene items, and ships as protokit 0.4.0.

The brainstorm's empirical OQ-1 verification at brainstorm time (3 fixture-pair runs against buf v1.69.0 captured in `/tmp/d6c_oq1_*` artifacts) confirmed Scenario A — per-file findings, `FileLocation` reuse, **no new ElementKind**, **no new LintLocation variant**, **no wire-format change** (`_LINT_JSON_SCHEMA_VERSION` stays `"0.3"`).

## Problem Frame

D6b shipped (0.3.0, 2026-05-18) with the claim "17 of 18 buf BASIC rules" inherited from the U7 delivery boundary. The brainstorm's empirical OQ-1 verification corrected this to **actual buf BASIC = 26 rules; protokit covers 23/26 with `buf:` source_spec (24/26 effective if `naming/snake-case-fields` is credited as semantically-equivalent to FIELD_LOWER_SNAKE_CASE)**. The 4 actual gaps: PACKAGE_SAME_DIRECTORY, DIRECTORY_SAME_PACKAGE, PACKAGE_NO_IMPORT_CYCLE, FIELD_NOT_REQUIRED.

D6c closes the two directory/package rules (R8 + R8b) — both per-file findings, both sharing a single Arch-D pre-walk accumulator. PACKAGE_NO_IMPORT_CYCLE (real cross-file cycle detection) and FIELD_NOT_REQUIRED (proto2-only trivial) defer to D6d on their own merits.

The cross-file dispatch infrastructure ships with **2 specimens at delivery time** (R8 + R8b), addressing the 3-way reviewer convergence (product-lens + scope-guardian + adversarial) on single-specimen abstraction risk surfaced during the brainstorm document-review pass.

See origin: `docs/brainstorms/2026-05-18-d6c-r8-cross-file-package-same-directory-requirements.md`.

## Requirements Trace

- **R1.** protokit lint detects R8 violations (`package/same-directory` — files with the SAME package value split across MULTIPLE directories) per buf parity, fires `error` severity in `recommended` + `default` profiles, with `[severities]` demotion paths. (origin: S1)
- **R2.** protokit lint detects R8b violations (`package/directory-same-package` — files in the SAME directory declare DIFFERENT package values) per buf parity, same severity + profile + demotion shape. (origin: S1b)
- **R3.** Empirical parity gate against buf v1.69.0 covering ≥9 fixtures asserts byte-equivalent output. (origin: S2 + spec-flow-#3)
- **R4.** Arch-D pre-walk accumulator infrastructure documented in `engine.py` module docstring; sibling pattern to R7's `_build_package_options_accumulator`. `FileLintContext.directory_packages` classified INTERNAL in Public Surface DRAFT. (origin: S3)
- **R5.** 0.4.0 released cleanly: pyproject 0.3.0 → 0.4.0; CHANGELOG fold; README parity claim 23/26 → 25/26 with honest 1-rule PACKAGE_NO_IMPORT_CYCLE deferral caveat. NO `_LINT_JSON_SCHEMA_VERSION` bump. (origin: S4)
- **R6.** U7 KD-7 code-health debt retired via consolidation: `tests/parity/test_parity_package_same.py:84-117` `_build_package_same_rule_id_map` + `tests/parity/conftest.py:171-197` `_build_package_same_proto_to_buf` consolidated to derive from `RULE_ID_MAP` (post-U7 the deliberate-isolation rationale is historically obsolete since R7 is now in BUILTIN_PACKS). (origin: S5 + repo-research discrepancy #3)
- **R7.** Compound-backslash+quote BUF_BINARY fixture committed; parity gate asserts byte-equivalence with buf v1.69.0 output for at least one PACKAGE_SAME_* rule with combined `\"` escape. (origin: S6)
<!-- R8 (per-unit ce:review pass + ce:compound capture) and R9 (post-ship monitoring) moved out of Requirements Trace per scope-guardian-#1 — they are recurring workflow steps, not functional deliverables. Captured under Documentation/Operational Notes + Operational/Rollout Notes sections instead. -->

## Scope Boundaries

- **In scope:** R8 + R8b implementation, Arch-D accumulator, empirical buf-parity gate (9 fixtures), 2 hygiene items (U7 KD-7 + compound-backslash), 0.4.0 delivery boundary.
- **Architecture locked at brainstorm time:** Arch-D (sibling pre-walk accumulator); Arch-A/B/C rejected per OQ-2 resolution.
- **Wire format unchanged:** `_LINT_JSON_SCHEMA_VERSION` stays `"0.3"`; no new `LintLocation` variant; no `ElementKind.DIRECTORY`.
- **Pack home:** R8 + R8b live in **`src/protokit/schema/lint/rules/package.py`** alongside existing `package/defined` + `package/directory-match` rules (semantic grouping by package-directory concern). NOT in `package_same.py` (which houses R7 language-namespace rules). Implication: NO new BUILTIN_PACKS append, NO CLI `--help` epilog edit, NO new dormancy-window opt-in line.

### Deferred to Separate Tasks

- **PACKAGE_NO_IMPORT_CYCLE** (buf BASIC rule 25 of 26): D6d. Real cross-file cycle-detection algorithm (DAG construction + cycle detection); not amenable to Arch-D accumulator pattern. Brainstorm Verification Step 5 records the empirical investigation that unblocks D6d planning.
- **FIELD_NOT_REQUIRED** (buf BASIC rule 26 of 26): D6d. Proto2-only trivial rule via existing `ElementKind.FIELD` (`field.label == LABEL_REQUIRED` check). Could ship as a single-unit add in D6d.
- **R6 severity promotion** `warning` → `error`: D6d. Needs real-world 0.3.x miss/hit data.
- **R9b per-rule disable/enable lists**: D6d. Needs ≥2 GitHub issues per D6b's defined evidence channel.
- **`strict` profile rule enumeration**: D6d. No rule declares `profiles=("strict",)` today.
- **Option-aware pack expansion** (R6 family successors): D6d. The strategic differentiator path gets its own delivery.
- **`naming/snake-case-fields` source_spec correction** (`https://google.aip.dev/122` → also `buf:FIELD_LOWER_SNAKE_CASE`): D6d cosmetic-correction scope.
- **`LintLocation` exhaustiveness contract decision** (OQ-7 (a)/(b)/(c)): D6d (not D6c-blocking since R8 + R8b introduce no new variant).

## Context & Research

### Relevant Code and Patterns

- **R7 pre-walk accumulator anatomy** (`src/protokit/schema/lint/engine.py`):
  - `engine.py:148-154` — instance attribute `self._current_package_options: Mapping[...] | None = None` in `__init__`.
  - `engine.py:429` — populated in `run()`: `self._current_package_options = self._build_package_options_accumulator(compile_result)`.
  - `engine.py:473-475` — cleared in `finally` to prevent cross-`run()` leak.
  - `engine.py:488-582` — `_build_package_options_accumulator()` iterates `sorted(compile_result.pool_file_names, key=lambda f: (posixpath.basename(f), f))`; returns `None` when `pool_file_names` empty; returns 3-level `MappingProxyType` wrap otherwise.
  - `engine.py:777-795` — `_build_file_ctx` threads accumulator: `package_options=self._current_package_options` kwarg into `FileLintContext`.
  - **Arch-D mirrors all 4 mechanics** (init / populate / reset / thread) for `_build_directory_package_accumulator`.

- **`FileLintContext.package_options` field declaration** (`src/protokit/schema/lint/model.py`):
  - `model.py:1003-1012` — docstring: `Mapping[package, Mapping[option_attr, Mapping[filename, str | None]]]`; classified **INTERNAL** ("subject to change pre-1.0").
  - `model.py:1021-1033` — field declared at END of engine-injected group with `= None` default. New `directory_packages` field follows same convention.

- **`_check_package_option` helper pattern** (`src/protokit/schema/lint/rules/package_same.py`):
  - `package_same.py:204-232` — `_escape_message_value(value)`: two-step `value.replace("\\", "\\\\").replace('"', '\\"')` — backslash FIRST.
  - `package_same.py:235-282` — `_truncate_values_payload(payload)`: `_safe_for_stderr(payload)[:500]` + odd-count trailing-backslash strip.
  - `package_same.py:285-370` — `_check_package_option(ctx, option_attr, rule_id)`: all-disagreers-fire; alphabetic-by-value sort; lowercase bool render; 3 string params each `_safe_for_stderr(...)[:500]`.
  - R8/R8b emit text uses **package + directory names** (no quote/backslash content in practice); the escape helper may not be needed for D6c, but the truncation guard SHOULD be reused if directory-list joining produces strings >500 chars on N≥3 fixtures.

- **Existing `package.py` rules** (`src/protokit/schema/lint/rules/package.py`):
  - `package.py:29-34` — 5-line deferral-prose docstring paragraph for R8 (the "The `package/same-directory` rule (buf:PACKAGE_SAME_DIRECTORY) is deferred to D6b..." text). Delete + rewrite in U2 per stale-text-sweep discipline. (Corrected from earlier "20-40" per feasibility-#5.)
  - `package.py:57-65` — `_PROTO_IDENTIFIER_RE` constant + preceding rationale comment.
  - `package.py:68-94` — `check_package_defined` (PACKAGE_DEFINED) ElementKind.FILE rule pattern to mirror (decorator-to-function-close range).
  - Existing `check_package_directory_match` rule (PACKAGE_DIRECTORY_MATCH) — already uses `PurePosixPath(fd.name).parent` for directory derivation; R8/R8b leverage the same.

- **BUILTIN_PACKS membership** (`src/protokit/schema/lint/rules/__init__.py`):
  - `__init__.py:125-133` — `BUILTIN_PACKS: tuple[ModuleType, ...]` — 8 packs currently; `package` is element 4. R8 + R8b in `package.py` means NO append needed.
  - `engine.py:241-242` — idempotency short-circuit.
  - `cli.py:828-842` — **CLI-level dedup is LOAD-BEARING** per [[cli-loaded-packs-dedup-zip-strict-builtin-packs-flip-2026-05-18]]; without it, `zip(strict=True)` at `cli.py:998-999` raises `ValueError`. R8/R8b shipping in `package` pack (already in BUILTIN_PACKS) means no flip event — but add a regression test asserting `--rule-pack=protokit.schema.lint.rules.package` continues to dedup correctly post-D6c.

- **Parity test infrastructure** (`tests/parity/conftest.py` + `tests/_buf_helpers.py`):
  - `conftest.py:373-413` — `run_buf_lint(buf_binary_path, fixture_dir)`: exits 0/100 OK; returns parsed NDJSON dicts.
  - `conftest.py:203-247` — `_build_rule_id_map()`: walks BUILTIN_PACKS deriving `protokit_id → buf_id`; fails loud on conflicts. Post-D6c covers R8 + R8b automatically (no manual addition).
  - `conftest.py:252` — `RULE_ID_MAP` module-level constant.
  - `conftest.py:486-582` — `run_protokit_lint_multi_file(fixture_dir, *, rule_pack=None, proto_paths=None)`: recursive `rglob("*.proto")`.
  - `conftest.py:604-667` — `parse_buf_recorded_snapshot(snapshot_path)`: sorted `tuple[BufFinding, ...]`.
  - `conftest.py:812-961` — `assert_parity_multi_file(...)`: three-way partition (in-scope / over-fire / unknown) + multiset equality.
  - `_buf_helpers.py:56-87` — `discover_buf_binary()`: `$BUF_BINARY` then PATH; skip if missing.
  - `_buf_helpers.py:90-133` — `run_buf_subprocess()`: 30s cap + triple-arm guard.
  - `_buf_helpers.py:151-176` — `SMOKE_FIXTURES` 21-tuple SSOT (extend for R8/R8b corpus or add parallel `PACKAGE_DIRECTORY_SMOKE_FIXTURES` — decision in U3).

- **Per-fixture rule_id derivation site (U7 KD-7 hygiene target)** (`tests/parity/test_parity_package_same.py`):
  - Lines 84-117 — `_build_package_same_rule_id_map()` deliberate-isolation pattern.
  - Lines 86-94 — docstring rationale (R7-not-in-BUILTIN_PACKS-during-dormancy). Post-U7 the rationale is obsolete; consolidation to `RULE_ID_MAP` is U4's work.

- **lint_json / lint_sarif duck-typed location handling** (`src/protokit/formatters/_builtin_lint.py`):
  - Line 308 — `"location": str(finding.location)` (works via `__str__`).
  - Line 309 — `"location_file": finding.location.file` — **fragile site, but unaffected by D6c** since R8/R8b emit `FileLocation`.
  - Line 311 — `type(finding.location).__name__.removesuffix("Location").lower()` (works via reflection).
  - **No formatter changes for D6c.**

- **CHANGELOG.md `### D6b` section structure** (`CHANGELOG.md:435+`):
  - Line 435 — heading shape: `### D6b — option-aware path + cross-language buf BASIC parity (0.3.0)`.
  - 5-subsection structure: `#### Added` / `#### Fixed` / `#### Wire format` / `#### Behavior changes (defaults; demotable)` / `#### Pre-upgrade migration recipe`.
  - Lines 440-442 — forward-reference to D6c. D6c CHANGELOG `### D6c` heading fulfills + corrects the inherited "17 of 18" framing.

- **CHANGELOG presence-ratchet test** (`tests/test_changelog_d6b_entry.py`):
  - 57 lines total. Two methods (`test_changelog_exists` + `test_changelog_names_d6b`).
  - D6c sibling = `tests/test_changelog_d6c_entry.py` = trivial copy with `D6b` → `D6c` substring.
  - **Audit (per spec-flow-#7)**: scan `test_changelog_d6b_entry.py` for `"17 of 18"` / `"18 buf BASIC"` substring assertions. If present, remove from ratchet (count claims are unsuitable presence-ratchet targets) OR update wording.

### Institutional Learnings

- [[dormant-code-changelog-draft-staging-delivery-boundary-2026-05-17]] — CHANGELOG-DRAFT staging contract (per-unit append + delivery-boundary fold).
- [[builtin-packs-expansion-changelog-migration-recipe-structure-2026-05-18]] — 5-sub-section migration recipe (worst-case math + 4-path demotion + "no pyproject.toml?" stub + 3 accepted-tradeoff scenarios + triage). **D6c extends to 5-path** by adding Python API path per spec-flow-#2.
- [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]] — 3 prior instances (U6 `_escape_inner_quote`, U7 `cli.py:841-846` dedup, brainstorm-time OQ-1). **D6c U3 expected to surface a 4th instance** at first run.
- [[wire-format-schema-version-bump-contract-and-absence-semantic-2026-05-13]] — closed-Literal contract. D6c **NO BUMP** per KD-4 + ER-1; downstream tests at `test_builtin_lint_formatter.py:535-554` need no update.
- [[stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12]] — stale-text sweep at U5 delivery boundary.
- [[buf-parity-divergence-documentation-discipline]] — applies if R8/R8b's directory-list message format diverges from buf at N≥3 cases (Verification at U3).
- [[ce-review-convergence-rescues-sub-threshold-findings-2026-05-17]] — per-unit ce:review pattern.
- [[presence-ratchet-test-pattern-for-prose-substrings-2026-05-14]] — 5-discipline rule including "single source line"; applies at U1 (lifecycle parity presence-ratchet) + U5 (CHANGELOG D6c presence-ratchet).
- [[plan-review-verify-prior-art-citations-2026-05-15]] — brainstorm-time count-verification gap discovered for D6c is a candidate for an extension here.
- [[cli-loaded-packs-dedup-zip-strict-builtin-packs-flip-2026-05-18]] — **LOAD-BEARING for D6c**: regression test in U2 asserting `--rule-pack=protokit.schema.lint.rules.package` continues to dedup after R8 + R8b additions.
- [[multi-mechanism-fix-docstring-enumerate-each-layer-failure-mode-2026-05-18]] — 3-rule discipline for the accumulator + rule callable + parity-gate test layers.
- [[programmatic-proto-fixture-builder-multi-file-rule-family-2026-05-17]] — R7's prior art for the `dict[filename, source]` builder pattern; **D6c reuses** to avoid 9-12 near-identical `.proto` fixture files.
- [[module-import-time-fixture-mapping-fail-loud-blast-radius-2026-05-18]] — per-fixture rule_id derivation pattern; D6c CONSUMES `RULE_ID_MAP` directly (NOT a sibling-isolated per-fixture map per repo-research discrepancy #3).
- [[per-rule-fixture-symbol-isolation-buf-v2-compile-group-2026-05-13]] — symbol collision risk on cross-file fixtures; U3 fixtures need per-fixture symbol prefix.
- [[rule-pack-extension-ssot-rule-ids-and-test-class-naming-2026-05-12]] — distinct test class names for sibling rules in same module (`TestCheckPackageSameDirectory` + `TestCheckDirectorySamePackage`).

### External References

- buf v1.69.0 `PACKAGE_SAME_DIRECTORY` documentation — empirically verified at brainstorm time via `buf lint --error-format=json` against `/tmp/d6c_oq1_psd/` fixture; per-file findings with directory-list in message body.
- buf v1.69.0 `DIRECTORY_SAME_PACKAGE` documentation — empirically verified at brainstorm time; per-file findings with package-list in message body.
- buf BASIC rule enumeration via `buf config ls-lint-rules --configured-only --format=json` (recount = 26 rules vs the inherited "18" claim).

## Key Technical Decisions

- **KTD-1: R8 + R8b live in `src/protokit/schema/lint/rules/package.py`, NOT `package_same.py` or a new `package_directory.py`.** Rationale: `package.py` already houses `package/defined` + `package/directory-match` — the natural semantic siblings (package-directory concerns) vs `package_same.py`'s language-namespace rules. No BUILTIN_PACKS append needed; no `--help` epilog opt-in line needed; no new dormancy window needed. Resolves repo-research discrepancy #1.

- **KTD-2: Arch-D accumulator is a NEW `_build_directory_package_accumulator`, NOT an extension of `_build_package_options_accumulator`.** Rationale: cleaner concern separation. R7's accumulator tracks language-namespace options (`go_package`, `java_package`); D6c's tracks `{package_name: {file_name: directory_name}}`. Single-pass iteration through `pool_file_names` is cheap; the abstraction cost of mixing two unrelated value classes in one accumulator outweighs the iteration-cost saving.

- **KTD-3: Per-fixture rule_id derivation CONSUMES `RULE_ID_MAP` directly.** Post-U7, R7 is in BUILTIN_PACKS and `RULE_ID_MAP` (built at `tests/parity/conftest.py:203-247`) covers R7 + R8 + R8b once D6c lands. The U6 KD-7 deliberate-isolation rationale is historically obsolete. Resolves repo-research discrepancy #3 + retires U7 KD-7 hygiene debt via consolidation (option (a) per brainstorm KD-7).

- **KTD-4: Pool-scope semantics for `_build_directory_package_accumulator`** (resolves spec-flow-#1; **EMPIRICALLY VERIFIED at /ce:plan-review time** via Phase 0 buf v1.69.0 fixtures at `/tmp/d6c_phase0/`):
  - **WKT files**: INCLUDED (mirror R7's posture at `engine.py:481-486` — no `google/protobuf/*` filter). Phase 0 single-file-test was inconclusive (single-file dir trivially passes); the safest empirical posture is mirror R7 and add a `wkt-conflict.json`-style fixture at U3 that places a user proto in non-WKT-dir with `package google.protobuf`. If U3 surfaces a buf-vs-protokit divergence, document via `_PARITY_EXCEPTIONS` entry per [[buf-parity-divergence-documentation-discipline]].
  - **Empty-package files** (`fd.package == ""`): **NOT SKIPPED — BUF FIRES on them with a DIFFERENT message template**. Empirically verified at `/tmp/d6c_phase0/empty_pkg/`: buf emits 3 findings (one per file) when 2 declared + 1 packageless files share a directory. **Critical message-template implication**: buf uses TWO distinct templates for R8b — the standard `"Multiple packages \"<pkg-list>\" detected within directory \"<dir>\"."` AND a separate `"Package \"<pkg>\" and file with no package detected within directory \"<dir>\"."` for the mixed-declared+undeclared case. Protokit must implement BOTH templates with discriminator on whether the directory contains a packageless file. R8 is unaffected (packageless files don't have a package value to split).
  - **Proto-root files** (`fd.name == "foo.proto"`): canonicalize `PurePosixPath("foo.proto").parent` (returns `PurePosixPath(".")`) explicitly via `str(parent) or "."`. **EMPIRICALLY VERIFIED** at `/tmp/d6c_phase0/proto_root/`: buf renders proto-root as `"directory \".\""`. Protokit's canonicalization matches buf byte-for-byte.
  - **Pool scope (CORRECTED from brainstorm-time posture)**: iterate **per-module-files (`root_files`-equivalent), NOT `pool_file_names`**. Empirically verified at `/tmp/d6c_phase0/transitive/`: buf does NOT cross-fire R8 across separate buf-module boundaries (a `user_protos/` module + `vendor/` module both with `package acme.foo` produces exit=0). protokit doesn't have buf's `modules:` concept, so the analog is `root_files` (the files protokit was invoked on, NOT their transitive imports). **This INVERTS the brainstorm-time KTD-4 (d) decision.** Implication for U1: `_build_directory_package_accumulator` iterates `compile_result.root_files` (or equivalent — verify exact field name from `engine.py:435` walk), NOT `pool_file_names`. R7's `_build_package_options_accumulator` uses `pool_file_names` per its own rule semantics (a user proto + a WKT proto can intentionally conflict on `java_package`); R8/R8b's per-module isolation differs. Document the divergence-from-R7 explicitly in the accumulator docstring.
  - **N=3+ directory/package list separator** (P1 finding): **EMPIRICALLY VERIFIED** at `/tmp/d6c_phase0/n3_dirs/` and `/tmp/d6c_phase0/n3_pkgs/`: buf uses **comma-no-space, alphabetic sort, single message template** at all N values. Example: `"Multiple directories \"d1,d2,d3\" contain files with package \"acme.x\"."` Protokit message_template MUST use the same shape with `",".join(sorted(items))` (no spaces, no Oxford comma, no "and" conjunction).
  - **R8 + R8b co-fire ordering** (KTD-9 verification): **EMPIRICALLY VERIFIED** at `/tmp/d6c_phase0/cofire/`: buf orders `DIRECTORY_SAME_PACKAGE` (R8b) BEFORE `PACKAGE_SAME_DIRECTORY` (R8) when both fire on the same file. This matches both buf-rule-alphabetic AND protokit rule_id-alphabetic (`package/directory-same-package` < `package/same-directory`). Existing protokit engine convention (`sorted(profile.rule_ids - loaded_ids)` at `engine.py:383`) produces correct ordering automatically — no special-case logic needed.

- **KTD-5: R8 + R8b ship in BUILTIN_PACKS via the existing `package` pack at the same unit (U2).** No dormancy window. Matches brainstorm KD-2. Migration recipe handles user-facing impact (see KTD-7).

- **KTD-6: NO `_LINT_JSON_SCHEMA_VERSION` bump.** Stays at `"0.3"`. Per brainstorm KD-4 + ER-1 — R8 + R8b reuse `FileLocation`; no new payload fields; existing `lint_json` / `lint_sarif` formatters need no changes. `test_builtin_lint_formatter.py:535-554` need no update.

- **KTD-7: Migration recipe extends D6b U7's 4-path structure to 5 paths** (resolves spec-flow-#2):
  - Path 1: resolve at source (canonicalize package per directory).
  - Path 2: per-rule demote via `[tool.protokit.lint.severities]`.
  - Path 3: pin to 0.3.x.
  - Path 4: defer / wait (CI severity ratchet pattern with warn-only-then-error progression).
  - **Path 5 (NEW for D6c): Python API users** — callers invoking `LintEngine` directly configure severity through `LintProfile` overrides, not pyproject. Document the API-side equivalent of `[severities]`.
  - Plus the inherited "no pyproject.toml?" stub + 3 accepted-tradeoff scenarios (3+ files migration state, generated-code directories, vendored protos).

- **KTD-8: CHANGELOG correction follows option (d) = (b) + (c)** (resolves spec-flow-#7 + brainstorm Verification Step 6):
  - (b) — D6c CHANGELOG `### D6c` carries the user-visible correction note ("Erratum: actual buf BASIC parity at D6b was 23/26, not 17/18; D6c brings to 25/26").
  - (c) — `docs/solutions/best-practices/` captures the failure mode as a new learning candidate (`brainstorm-time-parity-count-verification-discipline-2026-05-18`) — captured at U5's `/ce:compound` boundary, not pre-emptively.
  - **Actual live stale-text sites** (verified at /ce:plan-review time): `src/protokit/schema/lint/rules/__init__.py:121` (BUILTIN_PACKS docstring contains "Brings ``protokit lint`` to **17 of 18 buf BASIC rules**"), `CHANGELOG.md:439` (D6b section), `README.md:484`, `README.md:541`, `README.md:558`. U5 rewrites `__init__.py:121` to the corrected count; CHANGELOG.md `### D6b` section stays UNMODIFIED as historical artifact (correction lives in `### D6c` per option (b)); README.md sites rewritten with corrected 25/26 framing.
  - **`tests/test_changelog_d6b_entry.py` is NOT a stale-text target.** Verified at /ce:plan-review time: the "17 of 18 buf BASIC rules" substring appears ONLY in the module-level docstring (line 9, descriptive prose explaining historical context), NOT in any assert statement. The two assertions pin only `"D6b"` (a delivery-name substring). No ratchet edit needed; the docstring can optionally be refreshed during U5's sweep if its wording causes confusion, but it is historically accurate as-is.

- **KTD-9: R8 + R8b co-firing UX** (resolves spec-flow-#5; **rewritten** post-/ce:plan-review to eliminate the self-contradictory "fix R8b first then R8 ... correct sequence is the inverse" framing):
  - **The co-fire scenario**: A directory like `pkg/a.proto` (package `acme.foo`) + `pkg/b.proto` (package `acme.bar`) + sibling `other_dir/c.proto` (package `acme.foo`) triggers BOTH R8 (foo split) AND R8b (`pkg` mixed) on `pkg/a.proto`. Empirically verified at `/tmp/d6c_phase0/cofire/`: buf produces 4 findings total with `DIRECTORY_SAME_PACKAGE` ordered BEFORE `PACKAGE_SAME_DIRECTORY` per file. Protokit's `sorted(profile.rule_ids - loaded_ids)` engine ordering produces matching output without special-case logic.
  - **The actual invariant for migration sequencing** (the prior "fix R8b first" framing was wrong because rename-only fixes can trade one rule for another, NOT because there's a strict precedence): **prefer directory-restructuring fixes (move files between directories) over package-renaming fixes (rename `package X;` lines).** Directory-restructuring resolves both rules simultaneously; package-renaming can trade R8 ↔ R8b. Example: renaming `pkg/b.proto`'s package from `acme.bar` to `acme.foo` resolves R8b on `pkg/` but ADDS `pkg/b.proto` to the R8 conflict (`acme.foo` is now in 3 files across 2 dirs instead of 2 files across 2 dirs) — net worse state mid-migration. The correct fix is to MOVE `pkg/b.proto` to a sibling `pkg_bar/` directory, which simultaneously eliminates R8b (each dir has one package) and doesn't affect R8.
  - **Migration recipe (KTD-7) co-fire sub-section** spells out: (1) identify all directories with multiple packages OR all packages split across directories; (2) prefer directory restructuring; (3) if directory restructuring is infeasible (e.g., external consumers depend on file paths), use per-rule `[severities]` demotion + plan a separate refactor PR.

- **KTD-11: Include `naming/snake-case-fields` source_spec correction in D6c** (resolves P1 finding #5 — 25/26 vs 24/26 framing tension; 3-way reviewer convergence at coherence-#4 + adversarial-#8 + feasibility-#10). At `src/protokit/schema/lint/rules/naming.py:80`, change `source_spec="https://google.aip.dev/122"` to either: (a) **dual-source** `source_spec=("https://google.aip.dev/122", "buf:FIELD_LOWER_SNAKE_CASE")` if the LintRuleSpec field supports tuple, OR (b) **buf-source-primary** `source_spec="buf:FIELD_LOWER_SNAKE_CASE"` with AIP-122 attribution moved to the rule's module docstring. Decision (a) vs (b) depends on whether `LintRuleSpec.source_spec` accepts `str | tuple[str, ...]` (verify at U2 time); default to (b) if single-value. This makes 25/26 audit-trail-true: an external auditor running `grep 'buf:' src/protokit/schema/lint/rules/` will count 25 buf-sourced rules post-D6c (not 24). Resolves brainstorm-deferred D6d cosmetic-correction item by folding into D6c at trivial cost (one line). U2 includes the change; U3 parity-gate verifies no regression on the existing FIELD_LOWER_SNAKE_CASE parity coverage.

- **KTD-12: `assert_parity_multi_file` architectural decision** (resolves P1 finding #1 — feasibility-#1 0.88 confidence: `conftest.py:812-961` is R7-hardcoded via `_PACKAGE_SAME_PROTO_TO_BUF` + `_PACKAGE_SAME_RULE_IDS` + `startswith("package/same-")` prefix; R8/R8b findings would silently land in `protokit_unknown` bucket without intervention). **Chosen path: option (c) — derive R7-family membership frozenset from `RULE_ID_MAP`** (minimum-change variant). Concretely: in `tests/parity/conftest.py`, replace the standalone `_build_package_same_proto_to_buf()` walk + `_PACKAGE_SAME_RULE_IDS` set with `_PACKAGE_SAME_PROTO_TO_BUF = {rid: bid for rid, bid in RULE_ID_MAP.items() if rid.startswith("package/same-")}` and `_PACKAGE_SAME_RULE_IDS = frozenset(_PACKAGE_SAME_PROTO_TO_BUF)`. Keep the existing `assert_parity_multi_file` signature unchanged. **For R8/R8b**: add a sibling derived constant in the same conftest module — `_PACKAGE_DIRECTORY_PROTO_TO_BUF = {rid: bid for rid, bid in RULE_ID_MAP.items() if rid in ("package/same-directory", "package/directory-same-package")}` + `_PACKAGE_DIRECTORY_RULE_IDS = frozenset(_PACKAGE_DIRECTORY_PROTO_TO_BUF)`. Extend `assert_parity_multi_file`'s three-way partition logic with a new arm: `elif rule_id in _PACKAGE_DIRECTORY_RULE_IDS: in_scope_bucket` (or sibling helper `assert_parity_for_package_directory` if the in-place extension grows beyond review-load comfort — decide at U3 implementation time). This avoids both the option-(a) full-signature-refactor + option-(b) sibling-function-from-scratch costs. R7 invariants preserved via derived frozenset; R8/R8b coverage via mirrored derived frozenset. Resolves brainstorm KD-7 ambiguity by picking consolidation per [[plan-review-verify-prior-art-citations-2026-05-15]]. Captured in U3 + U4 implementation work.

- **KTD-10: Parity-gate fixture corpus** (resolves spec-flow-#3): 9 fixtures total at U3:
  - 5 base: `matched-dir.json`, `mismatched-dir.json` (R8b), `split-package-multi-dir.json` (R8), `single-file-dir.json`, `proto-root-mixed.json`.
  - 1 from OQ-4 sub-question: `no-package-mixed.json` (mixed-declared with no-package files in same directory).
  - 3 edge-case discriminators: `n3-directories-split.json` (R8 with 3+ directories; tests Oxford-comma / list-separator), `n3-packages-same-dir.json` (R8b with 3+ packages; same test), `cofire-r8-r8b.json` (R8 + R8b firing on same file; tests ordering + multi-finding output).
  - **UTF-8 + reserved-keyword + compound-backslash directory** fixtures (per spec-flow-#3) deferred to D6d unless U3's empirical verification surfaces a divergence requiring them now.

## Open Questions

### Resolved During Planning

- **Pack home (KTD-1)**: `package.py`, not `package_same.py` or new pack.
- **Accumulator strategy (KTD-2)**: NEW accumulator, not extension.
- **Per-fixture rule_id derivation (KTD-3)**: consume `RULE_ID_MAP` directly.
- **Pool-scope semantics (KTD-4)**: WKT-included, empty-package skipped, `.` canonicalized, `pool_file_names` scope.
- **Migration recipe paths (KTD-7)**: 5 paths including Python API.
- **CHANGELOG correction approach (KTD-8)**: option (d) = (b) + (c).
- **Co-fire UX (KTD-9)**: rule_id-alphabetic ordering; resolve R8b before R8.
- **Parity-gate fixture corpus (KTD-10)**: 9 fixtures with N≥3 + cofire + no-package-mixed.

### Deferred to Implementation

- **Exact directory-list-separator + sort-order in R8 message** (e.g., `"dir1,dir2"` vs `"dir1, dir2"` vs `"dir1 and dir2"`): empirical verification at U3 fixture creation against buf v1.69.0 — protokit must match buf exactly.
- **`_truncate_values_payload` applicability** (R8/R8b's directory/package lists may not exceed 500-char cap in practice; truncation guard may be unnecessary): determined at U2 implementation time based on fixture corpus.
- **Programmatic proto fixture builder shape** for U3's 9 fixtures: choose between `tests/schema/lint/rules/fixtures/package_directory/proto_templates.py` builder (per [[programmatic-proto-fixture-builder-multi-file-rule-family-2026-05-17]]) OR static `.proto` files. Default: builder pattern (R7's prior art) unless implementation reveals static is simpler.
- **Whether U3 parity-gate fixtures share `SMOKE_FIXTURES` SSOT or get a parallel `PACKAGE_DIRECTORY_SMOKE_FIXTURES` tuple** in `tests/_buf_helpers.py`: implementation-time choice based on whether the fixtures share helpers vs need independent reuse semantics.

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

**Arch-D pre-walk accumulator shape:**

```text
# engine.py — new sibling to _build_package_options_accumulator

def _build_directory_package_accumulator(
    self, compile_result: CompileResult,
) -> Mapping[str, Mapping[str, str]] | None:
    """Build {package_name: {file_name: directory_name}} pre-walk."""
    # Returns None if pool_file_names is empty.
    # Iterates sorted(pool_file_names, key=(posixpath.basename, full)).
    # Skips files with empty fd.package.
    # Uses PurePosixPath(name).parent canonicalized to "." for root.
    # Wraps result in MappingProxyType at 2 levels.

# FileLintContext (model.py) — new sibling to package_options field
directory_packages: Mapping[str, Mapping[str, str]] | None = None

# engine.py:run() — wires accumulator + ctx field
self._current_directory_packages = self._build_directory_package_accumulator(...)
# engine.py:_build_file_ctx() — threads into ctx
directory_packages=self._current_directory_packages
# engine.py:run() finally — resets to None
self._current_directory_packages = None
```

**R8 + R8b rule shape:**

```text
# package.py

@lint_rule(rule_id="package/same-directory", severity=ERROR,
           profiles=("recommended", "default"), element=ElementKind.FILE,
           message_template=..., source_spec="buf:PACKAGE_SAME_DIRECTORY")
def check_package_same_directory(ctx):
    # For ctx.file.package, look up ctx.directory_packages[package].
    # If >1 distinct directory contains this package: emit per-file finding.

@lint_rule(rule_id="package/directory-same-package", severity=ERROR,
           profiles=("recommended", "default"), element=ElementKind.FILE,
           message_template=..., source_spec="buf:DIRECTORY_SAME_PACKAGE")
def check_directory_same_package(ctx):
    # For directory of ctx.file.name, count distinct packages in that dir.
    # If >1 distinct package: emit per-file finding.
```

**Test scenario coverage matrix (per-unit):**

| Unit | Accumulator | R8 | R8b | Parity gate | Hygiene | Delivery |
|---|---|---|---|---|---|---|
| U1 | ✓ | | | | | |
| U2 | | ✓ | ✓ | | | |
| U3 | | (validated) | (validated) | ✓ | | |
| U4 | | | | (compound-bs) | ✓ | |
| U5 | | | | | | ✓ |

## Phase 0: Pre-Implementation Verification (RUN BEFORE U1)

Executed at /ce:plan-review time (post-document-review). Empirical results inlined throughout the plan (especially KTD-4 sub-decisions). Listed here for replay if /ce:plan is re-run on a different machine or against a newer buf version.

**Verification fixtures** were created at `/tmp/d6c_phase0/` (cleaned up post-extraction; reconstruct via these recipes for re-verification):

1. **KTD-4 (a) WKT inclusion test** — `/tmp/d6c_phase0/wkt_inclusion/`: single user proto declaring `package google.protobuf`. Buf result: exit=0 (no findings; single-file-dir trivially passes). Inconclusive — re-test at U3 with user proto in non-WKT dir, same package as a WKT.
2. **KTD-4 (b) Empty-package mixed test** — `/tmp/d6c_phase0/empty_pkg/`: 3 files in same dir, 1 declares `package acme.foo`, 2 packageless. Buf result: 3 findings, distinct message template: `"Package \"acme.foo\" and file with no package detected within directory \".\"."` **Protokit MUST implement this second message template** alongside the standard "Multiple packages X,Y" template; discriminator is "directory contains packageless file."
3. **KTD-4 (c) Proto-root canonicalization** — `/tmp/d6c_phase0/proto_root/`: 2 files at proto-root with different packages. Buf renders `"directory \".\""`. Protokit's `str(PurePosixPath(name).parent) or "."` matches byte-for-byte.
4. **KTD-4 (d) Transitively-imported conflict (CRITICAL — inverts brainstorm-time decision)** — `/tmp/d6c_phase0/transitive/`: 2-module buf.yaml (`user_protos` + `vendor`), both modules contain a file with `package acme.foo`. Buf result: exit=0 (no findings across module boundaries). **R8/R8b are per-module-isolated, NOT cross-module.** Plan accumulator iterates `root_files`, NOT `pool_file_names`. Documented in KTD-4 above.
5. **KTD-4 (e) N=3+ directory-list separator** — `/tmp/d6c_phase0/n3_dirs/` and `/tmp/d6c_phase0/n3_pkgs/`: 3-directory split + 3-package mixed-dir fixtures. Buf uses comma-no-space, alphabetic-sorted, single message template at all N: `"d1,d2,d3"` / `"acme.a,acme.b,acme.c"`. Protokit's helper uses `",".join(sorted(items))`.
6. **R8 + R8b co-fire ordering (KTD-9)** — `/tmp/d6c_phase0/cofire/`: 3-file fixture triggering both rules. Buf produces 4 findings ordered `DIRECTORY_SAME_PACKAGE` before `PACKAGE_SAME_DIRECTORY` per file. Protokit's `sorted(profile.rule_ids - loaded_ids)` engine ordering produces matching output without special-case logic.
7. **Compound-backslash+quote escape order (U4 fixture prep)** — `/tmp/d6c_phase0/cb_quote/`: 2-file fixture with `java_package` values containing `\"` and `\\` escapes. Buf output: `"com.baz\\\\qux,com.foo\\\"bar"` (JSON-encoded) — confirms protokit's two-step `_escape_message_value` (backslash FIRST then quote) matches buf byte-for-byte. U4's compound-backslash+quote BUF_BINARY fixture will parity-match.

**Worst-case migration impact measurement (P1 finding #3 — T=50 KD-2 falsifiability gate)**:
- Available corpus: protokit's own 39 .proto files (`tests/parity/fixtures/` + `tests/schema/lint/fixtures/`).
- Measurement result: **0 R8 findings + 0 R8b findings** = 0 findings per 39 files = 0/100 ratio.
- T=50 (per KD-2): **Well under threshold**. KD-2's no-dormancy posture remains validated.
- **Limitation acknowledged**: external corpora (googleapis, grpc internals, protobuf-go internals) not accessible in this environment. The protokit-own corpus is well-organized by design (per-rule fixture isolation, no cross-rule package conflicts) — it does NOT represent the migration-state user (team transitioning from raw-protoc with mixed-package directories). KD-2 falsifiability remains conditional on real-world adoption signals. Verification Step 4 (`Operational/Rollout Notes`) re-runs the measurement at U5 if external corpora become accessible; if not, S11 post-ship monitoring is the primary falsifiability gate.

**Strategic Sequencing (resolves P1 finding #6 — 3rd consecutive option-aware deferral; product-lens-#1)**:

D6b deferred option-aware pack expansion to D6c. D6c defers again to D6d. **This is the THIRD consecutive delivery where the strategic differentiator path defers in favor of parity work.** Each parity-only release positions protokit closer to "Python buf clone" vs differentiated tool. The OQ-8 forcing function from the brainstorm anticipates this — restating in-band per coherence + sequencing discipline:

- **D6d brainstorm contract** (binding pre-commit): D6d MUST ship option-aware pack expansion as the headline OR document a concrete external escalation milestone (e.g., "≥3 user requests for option-aware rules" OR "competitive analysis showing differentiator-path is no longer load-bearing") with sign-off from the project owner before opening D6d implementation work.
- **D6e tripwire**: If D6d also defers, this constitutes a strategic-positioning pattern that requires explicit product-level review (not just engineering decision). At that point the project's differentiation story needs re-validation — protokit is either (a) actively differentiated and the option-aware work is critical-path, or (b) re-positioning as a Python parity tool and the differentiation framing should be retired.
- **In-D6c acknowledgment**: D6c's 0.4.0 release notes (CHANGELOG `### D6c`) include a single sentence acknowledging the deferral chain and pointing at the D6d forcing function. This makes the pattern visible to external users tracking the project, not just internal contributors.

## Implementation Units

- [ ] **Unit 1: Arch-D pre-walk accumulator + `FileLintContext.directory_packages` field + lifecycle plumbing**

**Goal:** Ship the cross-file dispatch infrastructure as a standalone unit. No rules consume it yet; this unit is reviewable on its own terms ("does the accumulator have correct shape + lifecycle parity with R7?").

**Requirements:** R4 (Arch-D infrastructure documented).

**Dependencies:** None.

**Files:**
- Modify: `src/protokit/schema/lint/engine.py` (add `_build_directory_package_accumulator` method + `_current_directory_packages` instance attr + wire into `run()` + `_build_file_ctx`)
- Modify: `src/protokit/schema/lint/model.py` (add `directory_packages: Mapping[str, Mapping[str, str]] | None = None` field to `FileLintContext` at end of engine-injected group)
- Test: `tests/schema/lint/test_engine_directory_package_accumulator.py` (new file)
- Test: `tests/schema/lint/test_model_directory_packages.py` (new file)

**Approach:**
- Mirror the 4 lifecycle mechanics of `_current_package_options` exactly: (1) `__init__` declaration with `None` default, (2) `run()` population after compile, (3) `finally` reset to `None`, (4) `_build_file_ctx` thread into context.
- `_build_directory_package_accumulator(compile_result)` returns `MappingProxyType[str, MappingProxyType[str, str]] | None`:
  - **Iterates `compile_result.root_files`** (NOT `pool_file_names`) per KTD-4 (d) empirical verification — buf does not cross-fire R8/R8b across module boundaries; protokit's analog is per-invocation `root_files` scope. Diverges from R7's `pool_file_names` iteration (R7's rule semantics intentionally include WKT options); document the divergence in the accumulator docstring.
  - Returns `None` when `root_files` empty.
  - Iterates `sorted(root_files, key=lambda f: (posixpath.basename(f), f))` per R7 ordering convention.
  - For each file: `pkg = fd.package`; **DO NOT skip empty-package files** — per KTD-4 (b) empirical verification, buf FIRES R8b on packageless files mixed with declared-package files. Track them in the accumulator using a sentinel key (e.g., empty string `""` is fine since `fd.package == ""` is the natural representation); the rule callable handles the mixed-declared+undeclared case with the second message template. `dirname = str(PurePosixPath(fd.name).parent) or "."` (KTD-4 (c) canonicalization).
  - Inner dict keyed by package_name; value is `{file_name: dirname}`.
- Document the new accumulator in `engine.py` module docstring (sibling-pattern reference + cross-ref to `_build_package_options_accumulator`).

**Execution note:** Test-first for the accumulator unit tests. Per [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]], the parity gate (U3) will surface helper bugs — but unit tests for the accumulator shape itself should pin the contract first.

**Technical design:** *(see High-Level Technical Design section)*

**Patterns to follow:**
- `engine.py:148-154, 429, 473-475, 488-582, 777-795` — R7 accumulator full lifecycle.
- `model.py:1003-1012, 1021-1033` — `FileLintContext.package_options` field declaration shape + INTERNAL classification convention.

**Test scenarios:**
- *Happy path:* Accumulator returns `MappingProxyType` with correct 2-level shape on a 3-file fixture (1 file per dir, 1 shared package).
- *Happy path:* Accumulator wires through to `FileLintContext.directory_packages` correctly via `_build_file_ctx`.
- *Edge case:* Empty `pool_file_names` returns `None`.
- *Edge case:* Empty `fd.package` files skipped from accumulator (verify by checking accumulator output).
- *Edge case:* Proto-root files canonicalize parent dir to `"."` (not `""`).
- *Edge case:* Files in nested directories grouped by immediate parent only (not transitive).
- *Edge case:* WKT files (`google/protobuf/*`) INCLUDED in accumulator (per KTD-4 mirror R7 posture).
- *State lifecycle:* Accumulator reset to `None` in `run()` `finally` block (verified by inspecting engine state after `run()`).
- *State lifecycle:* `FileLintContext.directory_packages = None` is acceptable for test-helper construction (no required-arg breakage).
- *Presence-ratchet:* `tests/schema/lint/test_engine_directory_package_accumulator.py` includes a `TestAccumulatorLifecycleParity` class pinning the 4 mechanics via `inspect.getsource(engine.LintEngine)` substring assertions per [[presence-ratchet-test-pattern-for-prose-substrings-2026-05-14]] 5-discipline rule (each substring fits a single source line).

**Verification:**
- New accumulator method exists at `engine.py` with documented shape.
- `FileLintContext.directory_packages` field declared at end of engine-injected group with `None` default.
- All 4 lifecycle mechanics mirror R7 (verified by presence-ratchet test).
- `pytest tests/schema/lint/test_engine_directory_package_accumulator.py tests/schema/lint/test_model_directory_packages.py` passes.
- ruff + mypy clean.

---

- [ ] **Unit 2: R8 + R8b rules in `package.py` + unit tests + CLI dedup regression**

**Goal:** Implement both cross-file rules consuming U1's accumulator. Ships as a single unit because R8 + R8b share the accumulator, are co-located in `package.py`, and have symmetric structure — splitting them would dilute review focus.

**Requirements:** R1 (R8), R2 (R8b).

**Dependencies:** U1 (accumulator + `directory_packages` field).

**Files:**
- Modify: `src/protokit/schema/lint/rules/package.py` (rewrite the deferral-prose docstring at lines 29-34; add `check_package_same_directory` + `check_directory_same_package` rule callables; possibly add shared helper `_emit_directory_finding(...)` if message-building structure repeats)
- Modify: `src/protokit/schema/lint/rules/naming.py:80` (per KTD-11 — change `source_spec` of `check_snake_case_fields` from AIP-only to `"buf:FIELD_LOWER_SNAKE_CASE"`; move AIP-122 attribution to module docstring)
- Test: `tests/schema/lint/rules/test_package_same_directory.py` (new file — R8 + R8b unit tests)
- Test: `tests/schema/lint/test_cli_rule_pack_dedup_post_d6c.py` (new file — regression test for [[cli-loaded-packs-dedup-zip-strict-builtin-packs-flip-2026-05-18]] post-D6c)

**Approach:**
- R8 callable: for `ctx.file.package`, skip if `not pkg`. Look up `ctx.directory_packages.get(pkg)`. If the inner map has >1 distinct directory value: emit per-file finding with message naming all directories.
- R8b callable: derive `current_dir = str(PurePosixPath(ctx.file.name).parent) or "."`; iterate `ctx.directory_packages` to collect `{pkg: dirs}` where `current_dir in dirs.values()`. Two cases:
  - **Standard case** (all collected packages non-empty): if >1 such pkg, emit per-file finding with message naming all packages — template: `"Multiple packages \"<pkg-list>\" detected within directory \"<current_dir>\"."`
  - **Empty-package case** (per KTD-4 (b) empirical verification at `/tmp/d6c_phase0/empty_pkg/`): if the collected `{pkg: dirs}` contains both a packageless entry (empty-string key) AND ≥1 declared-package entry, emit per-file finding with DIFFERENT message template: `"Package \"<declared-pkg>\" and file with no package detected within directory \"<current_dir>\"."` Buf produces exactly one declared-package value in this template even if multiple declared packages exist (verify at U3 — current empirical fixture had only 1 declared pkg + 2 packageless).
- Both rules: ERROR severity, `("recommended", "default")` profiles, `ElementKind.FILE`, `source_spec="buf:PACKAGE_SAME_DIRECTORY"` / `"buf:DIRECTORY_SAME_PACKAGE"`, distinct `rule_id` + `violation_kind` per existing rule conventions.
- Message templates **empirically locked at /ce:plan time** per Phase 0 verifications:
  - R8: `"Multiple directories \"<dir-list>\" contain files with package \"<pkg>\"."` with `<dir-list>` = `",".join(sorted(distinct_dirs))` (comma-no-space, alphabetic). Verified at N=3 fixture.
  - R8b standard: `"Multiple packages \"<pkg-list>\" detected within directory \"<dir>\"."` with `<pkg-list>` = `",".join(sorted(distinct_pkgs))`. Verified at N=3.
  - R8b empty-mixed: `"Package \"<declared-pkg>\" and file with no package detected within directory \"<dir>\"."` Verified at empty-package mixed fixture.
- Include the **`naming/snake-case-fields` source_spec correction per KTD-11**: at `src/protokit/schema/lint/rules/naming.py:80`, change `source_spec="https://google.aip.dev/122"` to `source_spec="buf:FIELD_LOWER_SNAKE_CASE"` (or dual-source tuple if supported); move AIP-122 attribution to the module docstring. Verify the existing AIP-122 parity tests still pass.
- CLI dedup regression test: `--rule-pack=protokit.schema.lint.rules.package` invocation post-D6c should NOT trigger `zip(strict=True)` ValueError at `cli.py:998-999`. Mirror `TestRulePackExplicitLoadIsIdempotent` pattern.
- Rewrite `package.py:20-40` docstring: replace "R8 deferred to D6b" / "deferred to D6c" prose with active framing ("R8 + R8b cross-file rules implementing cross-directory + same-directory package consistency per buf BASIC parity").

**Execution note:** Test-first per the R8 + R8b happy/edge-path test scenarios. The accumulator-consumer contract is U1's; the rule-emit semantic is U2's.

**Patterns to follow:**
- `src/protokit/schema/lint/rules/package.py:68-79` (`check_package_defined`) — ElementKind.FILE rule pattern.
- `src/protokit/schema/lint/rules/package_same.py:285-370` (`_check_package_option`) — all-disagreers-fire + alphabetic-by-value sort semantic. Decide at implementation time whether to extract a shared `_check_directory_package_conflict` helper (likely yes if both rules share message-building code).
- `src/protokit/schema/lint/rules/package_same.py:204-282` — escape + truncation helpers. Likely NOT reused for D6c (path values don't contain quotes/backslashes in practice), but if directory-list joining produces >500-char strings on edge fixtures, reuse `_truncate_values_payload` odd-count discipline.
- `tests/schema/lint/test_cli_package_same_e2e.py` (existing R7 e2e test) — CLI dedup regression test shape.

**Test scenarios:**
- *Happy path R8:* 3-file fixture with package `acme.foo` in 2 directories (`dir1/a.proto`, `dir2/b.proto`) and `acme.bar` in `dir1/c.proto`. R8 emits 2 findings (on `a.proto` + `b.proto`). R8b emits 2 findings (on `a.proto` + `c.proto`).
- *Happy path R8 only:* 2-file fixture with same package across 2 dirs (no R8b trigger). R8 fires; R8b silent.
- *Happy path R8b only:* 2-file fixture with different packages in same dir (no R8 trigger). R8b fires; R8 silent.
- *Edge case:* Single-file fixture — both rules silent.
- *Edge case:* No-package fixture (all files have empty `fd.package`) — both rules silent.
- *Edge case:* WKT-only fixture (all files in `google/protobuf/`) — both rules silent (R7 covers this domain).
- *Edge case:* Proto-root files (no parent dir) — accumulator canonicalizes correctly; rules fire on packageless / mixed-package as expected.
- *Co-fire scenario (KTD-9):* R8 + R8b BOTH fire on `pkg/a.proto` per the example in KTD-9. Output order is rule_id-alphabetic.
- *Severity demotion:* `[tool.protokit.lint.severities] "package/same-directory" = "warning"` demotes R8 to warning; R8b unaffected.
- *Severity disable:* `"package/directory-same-package" = "off"` disables R8b entirely.
- *Profile membership:* Both rules in `recommended` + `default`; absent in `essentials` (zero-rule).
- *CLI dedup regression:* `protokit lint --rule-pack=protokit.schema.lint.rules.package <fixture>` does NOT raise `ValueError` at `cli.py:998-999`. Mirror `TestRulePackExplicitLoadIsIdempotent` from U7.
- *BUILTIN_PACKS membership:* `protokit.schema.lint.rules.package` already in `BUILTIN_PACKS` tuple; verify `package/same-directory` + `package/directory-same-package` appear in `protokit lint --list-rules` output.

**Verification:**
- Both rules registered + appear in `--list-rules` under `package` pack.
- All unit-test scenarios pass.
- CLI dedup regression test passes.
- ruff + mypy clean.
- `package.py:20-40` docstring rewritten with active framing (no "deferred" / "dormant" prose).

---

- [ ] **Unit 3: Empirical buf-parity gate (9 fixtures + parity test module)**

**Goal:** Lock R8 + R8b against buf v1.69.0 byte-for-byte. This is the unit where helper bugs surface per [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]].

**Requirements:** R3 (parity gate).

**Dependencies:** U2 (rules must exist).

**Files:**
- Create: `tests/schema/lint/rules/fixtures/package_directory/proto_templates.py` (programmatic builder per [[programmatic-proto-fixture-builder-multi-file-rule-family-2026-05-17]]; OR static `.proto` files at `tests/schema/lint/rules/fixtures/package_directory/<fixture-name>/` — implementation-time choice)
- Create: `tests/schema/lint/rules/fixtures/package_directory/_buf_smoke/recorded/*.json` (9 buf snapshot files generated via U3's snapshot-generation script)
- Create: `tests/parity/test_parity_package_directory.py` (new parity test module mirroring `test_parity_package_same.py` structure but consuming `RULE_ID_MAP` directly per KTD-3)
- Modify: `tests/_buf_helpers.py` (extend `SMOKE_FIXTURES` tuple OR add parallel `PACKAGE_DIRECTORY_SMOKE_FIXTURES` — decision at implementation time)
- Modify: `tests/schema/lint/rules/fixtures/__init__.py` + create `tests/schema/lint/rules/fixtures/package_directory/__init__.py` (test-collection plumbing per R7 pattern)
- Test: `tests/schema/lint/test_buf_smoke_assumptions_package_directory.py` (new file mirroring `test_buf_smoke_assumptions.py` U4a pattern — pin buf snapshot generation invariants)

**Approach:**
- Create 9 fixtures per KTD-10: 5 base + 1 OQ-4-sub-question + 3 edge-case discriminators (`n3-directories-split`, `n3-packages-same-dir`, `cofire-r8-r8b`).
- For each fixture: build proto sources (programmatic builder preferred), invoke buf v1.69.0 via `run_buf_lint(buf_binary, fixture_dir)` per `tests/parity/conftest.py:373-413`, record JSON output as fixture `*.json` snapshot, commit + SHA256-checksum.
- Parity test module structure: import `RULE_ID_MAP` from `tests/parity/conftest.py` (NO sibling `_build_package_directory_rule_id_map` — KTD-3 resolves U7 KD-7); use `assert_parity_multi_file()` per `conftest.py:812-961` for three-way partition (in-scope/over-fire/unknown). **Per KTD-12 (P1 finding #1)**: `assert_parity_multi_file` is currently R7-hardcoded; D6c extends it with new arm via derived frozenset `_PACKAGE_DIRECTORY_RULE_IDS = frozenset({"package/same-directory", "package/directory-same-package"})` + the R7 path consolidated to derive `_PACKAGE_SAME_PROTO_TO_BUF` from `RULE_ID_MAP`-filter as a side-effect. See KTD-12 in Key Technical Decisions for full architectural decision. Single-element rule scope via `buf.yaml use: [RULE_NAME]` per KD-7 from D6b (exception: `cofire-r8-r8b.json` fixture uses multi-rule `use: [PACKAGE_SAME_DIRECTORY, DIRECTORY_SAME_PACKAGE]` scope per KTD-10). **Per D6b KD-2**, the new `test_parity_package_directory.py` module deliberately does NOT apply `pytestmark = pytest.mark.parity` — tests run in the required `test` CI job per the same KD-2 rationale as `test_parity_package_same.py:8`. Include a module docstring sentence to that effect.
- Snapshot-generation script: `tests/schema/lint/rules/fixtures/package_directory/_regenerate_snapshots.py` (or extend the existing R7 script if any) — invocable manually when buf version bumps; checksums committed.
- Per [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]]: **expect to surface a bug** in U2's helper. The directory-list separator + sort-order is the most likely divergence point.

**Patterns to follow:**
- `tests/parity/test_parity_package_same.py` (overall module structure — but consume `RULE_ID_MAP` not sibling-isolated map per KTD-3).
- `tests/schema/lint/rules/fixtures/package_same/_buf_smoke/recorded/*.json` (snapshot format).
- `tests/parity/conftest.py:486-582` (`run_protokit_lint_multi_file`) + `:604-667` (`parse_buf_recorded_snapshot`) + `:812-961` (`assert_parity_multi_file`) — generic infrastructure, reuse as-is.
- `tests/_buf_helpers.py:56-87` (`discover_buf_binary`) + `:90-133` (`run_buf_subprocess`).
- `tests/schema/lint/test_buf_smoke_assumptions.py` — snapshot-generation-assumption pinning.

**Test scenarios:**
- *Happy path:* All 9 fixtures pass parity gate (protokit findings == buf findings, modulo path normalization).
- *Helper-bug-surface scenarios:* If directory-list separator differs from `","` (e.g., `", "` or `" and "`), parity gate fails on `n3-directories-split.json` and `n3-packages-same-dir.json`. Fix in U2's helper + re-run.
- *Co-fire scenario:* `cofire-r8-r8b.json` produces 2 findings on the shared file with correct rule_id ordering.
- *No-package-mixed scenario (OQ-4 sub-question):* Buf's treatment of mixed-declared + no-package files in same dir is matched exactly.
- *Snapshot integrity:* `tests/schema/lint/test_buf_smoke_assumptions_package_directory.py` pins SHA256 checksums + buf version (per U4a R7 pattern).
- *Test-collection plumbing:* `pytest tests/parity/test_parity_package_directory.py` discovers + runs all fixture cases without import errors.
- *Over-firing complement check:* `assert_parity_multi_file` three-way partition catches any protokit rule firing on files where buf doesn't (KD-7 two-sided check).
- *Skip-on-missing-buf:* Test module skips cleanly via `discover_buf_binary()` if `BUF_BINARY` unset + `buf` not on PATH.

**Verification:**
- 9 fixture snapshots committed at correct path with SHA256 checksums.
- `pytest tests/parity/test_parity_package_directory.py` passes when `BUF_BINARY` resolves.
- `pytest tests/schema/lint/test_buf_smoke_assumptions_package_directory.py` pins snapshot invariants.
- Any helper-bug surfaced by U3 is fixed in U2 + re-tested before U3 closes.

---

- [ ] **Unit 4: U7 KD-7 hygiene consolidation + compound-backslash+quote BUF_BINARY fixture**

**Goal:** Retire two D6b carry-forward items. Bundled because both are small, independent of R8/R8b's correctness, and naturally co-located in the parity-test surface.

**Requirements:** R6 (U7 KD-7 hygiene), R7 (compound-backslash parity fixture).

**Dependencies:** U3 (parity infrastructure reuse).

**Files:**
- Modify: `tests/parity/test_parity_package_same.py` (delete or simplify `_build_package_same_rule_id_map` at lines 84-117; consume `RULE_ID_MAP` from conftest directly per KTD-3)
- Modify: `tests/parity/conftest.py` (consolidate `_build_package_same_proto_to_buf` at lines 171-197 if it's now derivable from `RULE_ID_MAP`-filter; otherwise refresh docstring to remove obsolete deliberate-isolation rationale)
- Create: `tests/schema/lint/rules/fixtures/package_same/_buf_smoke/recorded/compound-backslash-quote.json` (new BUF snapshot for `\"` combined-escape case)
- Modify: programmatic fixture builder (if exists for R7) to support the compound-backslash case; OR create a new static `.proto` fixture at `tests/schema/lint/rules/fixtures/package_same/compound_backslash_quote/`
- Test: extend `tests/parity/test_parity_package_same.py` parametrize cases to include the new fixture
- Modify: `tests/_buf_helpers.py` `SMOKE_FIXTURES` tuple (add 22nd entry for compound-backslash fixture)

**Approach:**
- **U7 KD-7 consolidation:** Delete `_build_package_same_rule_id_map` and `_PACKAGE_SAME_RULE_ID_MAP` constant from `test_parity_package_same.py`; update parametrize source to consume `RULE_ID_MAP` filtered by `"buf:PACKAGE_SAME_"` prefix. Verify `_build_package_same_proto_to_buf` at conftest:171-197 is similarly consolidatable; if not, update the docstring at conftest:181-184 to remove the obsolete deliberate-isolation rationale (since R7 is now in BUILTIN_PACKS).
- **Compound-backslash+quote fixture:** Build a multi-file proto fixture where at least one R7 PACKAGE_SAME_* rule value contains `\"` combined escape (e.g., `option java_package = "com.foo\"bar"`). Generate buf snapshot via `buf lint --error-format=json`. Verify protokit's `_escape_message_value` two-step backslash-then-quote escape order matches buf's output byte-for-byte. Per brainstorm KD-8 pre-committed escalation contingency: **if the fixture surfaces a third-order helper bug** in `_escape_message_value` or `_truncate_values_payload`, split this unit into fixture + fix + regression (3 commits, not 1).
- Update `SMOKE_FIXTURES` SSOT to include the new fixture (22nd entry).

**Patterns to follow:**
- `tests/parity/conftest.py:203-247` (`_build_rule_id_map`) — the SSOT to consume.
- `tests/parity/test_parity_package_same.py:130-160+` (`_parse_fixture_buf_yaml`) — per-fixture rule scoping via `buf.yaml use:[]` (KD-7) stays.
- `tests/schema/lint/rules/fixtures/package_same/_buf_smoke/recorded/mixed-value-with-inner-quote.json` (existing) — analogous shape for the new compound-backslash fixture.

**Test scenarios:**
- *Hygiene consolidation:* `test_parity_package_same.py` parametrize source now reads from `RULE_ID_MAP`; all 27 existing R7 parity tests still pass.
- *Hygiene fail-loud:* If conftest's `_build_rule_id_map` somehow lost a rule (regression), the consolidated parity tests fail loudly with the original "missing rule_id" error.
- *Compound-backslash parity:* New fixture produces matching protokit + buf output. Per-test scenario also covers the BUF NDJSON snapshot integrity check.
- *Escalation contingency:* If `_escape_message_value` or `_truncate_values_payload` need a fix, dedicated regression test + commit captures the bug post-mortem.
- *SMOKE_FIXTURES integrity:* `tests/schema/lint/test_buf_smoke_assumptions.py` continues passing with the 22-entry tuple.

**Verification:**
- `tests/parity/test_parity_package_same.py:84-117` deleted (or simplified to consume `RULE_ID_MAP`).
- `tests/parity/conftest.py:171-197` consolidated OR docstring refreshed to acknowledge historical context.
- New `compound-backslash-quote.json` snapshot committed with SHA256 checksum.
- `pytest tests/parity/test_parity_package_same.py` passes (with 28 cases instead of 27 if the new fixture is included in R7's parametrize).
- ruff + mypy clean.

---

- [ ] **Unit 5: Delivery boundary — 0.4.0 release**

**Goal:** Ship 0.4.0 with corrected buf BASIC parity claim, fold CHANGELOG-DRAFT staging, update README, sweep stale text, add per-delivery presence-ratchet, update Public Surface DRAFT.

**Requirements:** R5 (0.4.0 released cleanly).

**Dependencies:** U1, U2, U3, U4 all complete.

**Files:**
- Modify: `pyproject.toml` (version 0.3.0 → 0.4.0)
- Modify: `src/protokit/__init__.py` (if `__version__` constant present)
- Modify: `CHANGELOG.md` (fold CHANGELOG-DRAFT staging into new `### D6c — cross-file lint dispatch (Arch-D pre-walk accumulator) + 25/26 buf BASIC parity (0.4.0)` section with 5-subsection structure mirroring D6b)
- Modify: `CHANGELOG-DRAFT.md` (reset to header-only stub per [[dormant-code-changelog-draft-staging-delivery-boundary-2026-05-17]])
- Modify: `README.md` (Schema Linting section: parity claim 23/26 → 25/26; honest 1-rule PACKAGE_NO_IMPORT_CYCLE deferral caveat; profile-table updates for R8 + R8b in `recommended` + `default`; rule-table additions)
- Modify: Public Surface DRAFT (location per memory: README's Public Surface DRAFT section) — add `FileLintContext.directory_packages` row classified INTERNAL
- Create: `tests/test_changelog_d6c_entry.py` (57-line copy of `tests/test_changelog_d6b_entry.py` with `D6b` → `D6c` substring)
- Modify: `src/protokit/schema/lint/rules/__init__.py:115-124` (BUILTIN_PACKS docstring "Brings ``protokit lint`` to **17 of 18 buf BASIC rules**" → rewrite to "Brings ``protokit lint`` to **25 of 26 buf BASIC rules** (the 26th, `PACKAGE_NO_IMPORT_CYCLE`, defers to D6d).")
- Modify: `README.md:484, 541, 558` (rewrite "17 of 18" / "18 buf BASIC" framing to corrected 25/26 with PACKAGE_NO_IMPORT_CYCLE caveat)
- (NOT MODIFIED — historical artifact: `CHANGELOG.md:439` D6b section "17 of 18" prose stays as-is per KTD-8 option (b); correction lives in new `### D6c` section.)
- (NOT MODIFIED: `tests/test_changelog_d6b_entry.py` — verified at /ce:plan-review time the substring is in docstring-only, not assertion; no ratchet edit needed.)
- Stale-text sweep across `docs/`, `src/`, `tests/` for `"17 of 18"` / `"18 of 18"` / `"18 buf BASIC"` / `"deferred to D6c"` / `"package/same-directory deferred"` prose

**Approach:**
- **Version bump:** `pyproject.toml` constant edit; verify `__version__` synchronization if applicable.
- **CHANGELOG fold:** Move CHANGELOG-DRAFT staged content into `### D6c` section under existing pre-1.0-framed structure. 5-subsection structure:
  - `#### Added` — R8 + R8b rules; Arch-D `_build_directory_package_accumulator`; `FileLintContext.directory_packages` (INTERNAL); 9 parity fixtures.
  - `#### Corrected` (NEW subsection) — Inherited "17 of 18 buf BASIC" claim from D6b CHANGELOG was empirically wrong; actual buf BASIC = 26 rules; D6b shipped 23/26; D6c brings to 25/26. Reference [[plan-review-verify-prior-art-citations-2026-05-15]] for the prior-art-verification discipline that should have caught this.
  - `#### Fixed` — Compound-backslash+quote helper validation (if U4 surfaced a bug); U7 KD-7 hygiene consolidation.
  - `#### Behavior changes (defaults; demotable)` — R8 + R8b fire `error` in `recommended` + `default` profiles; teams with mixed-package directories will see new findings on upgrade.
  - `#### Pre-upgrade migration recipe` — 5-path recipe per KTD-7 (resolve / demote / pin / wait / Python API). Includes R8 + R8b co-fire sequencing note (KTD-9: fix R8b first then R8). Includes "no pyproject.toml?" stub + 3 accepted-tradeoff scenarios.
- **README refresh:** Schema Linting section intro: "**As of 0.4.0, protokit lint covers 25 of 26 buf BASIC rules** (the 26th, `PACKAGE_NO_IMPORT_CYCLE`, defers to D6d alongside FIELD_NOT_REQUIRED; cross-file cycle detection requires its own architectural design pass)." Rule-table row updates for R8 + R8b. Profile-table updates reflecting both rules in `recommended` + `default`.
- **Public Surface DRAFT update:** Add `FileLintContext.directory_packages` row classified **INTERNAL** ("subject to change pre-1.0"; sibling-pattern note referencing existing `FileLintContext.package_options` row).
- **CHANGELOG-DRAFT.md reset:** preserve header + framing prose; remove all D6c-staged content (folded into CHANGELOG.md).
- **Stale-text sweep:**
  - `git grep -n '17 of 18\|18 of 18\|18 buf BASIC' src/ tests/ docs/ README.md CHANGELOG.md` — audit each hit; correct or remove per KTD-8.
  - `git grep -n 'deferred to D6c\|package/same-directory deferred\|R8 cross-file' src/ tests/ docs/ README.md` — audit; update to active framing post-D6c.
  - `tests/test_changelog_d6b_entry.py`: NO change needed — verified the "17 of 18" substring is in module docstring only, not in any assert statement (per KTD-8 actual-stale-sites enumeration). The two assertions pin only `"D6b"` (delivery-name substring), which remains correct.
  - `src/protokit/schema/lint/rules/package.py:20-40` docstring already rewritten in U2; verify no residue.
- **Per-delivery CHANGELOG ratchet test:** `tests/test_changelog_d6c_entry.py` 57-line copy of D6b sibling with `D6c` substring.
- **NOT EDITED:** Files under `docs/brainstorms/`, `docs/plans/`, `docs/solutions/` per D6b U7 KD-6 (historical artifacts; forward-looking phrasing is the audit trail of past deliberation).

**Patterns to follow:**
- `CHANGELOG.md:435` (D6b heading structure) + the 5-subsection structure inside.
- `tests/test_changelog_d6b_entry.py` (presence-ratchet shape).
- D6b U7 R34 (targeted README refresh — no restructuring).
- [[dormant-code-changelog-draft-staging-delivery-boundary-2026-05-17]] CHANGELOG-DRAFT.md stub pattern.
- [[stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12]] stale-text-sweep grep targets.
- [[builtin-packs-expansion-changelog-migration-recipe-structure-2026-05-18]] 5-sub-section recipe (extended to 6 sub-sections in D6c: + Python API path).

**Test scenarios:**
- *CHANGELOG presence-ratchet:* `pytest tests/test_changelog_d6c_entry.py` passes (asserts `### D6c` substring exists in `CHANGELOG.md`).
- *CHANGELOG D6b ratchet:* `pytest tests/test_changelog_d6b_entry.py` passes (without `"17 of 18"` substring if removed from ratchet).
- *Version bump:* `protokit --version` returns `0.4.0`.
- *Stale-text sweep:* `git grep -n '17 of 18\|18 of 18\|18 buf BASIC' src/ tests/ docs/ README.md CHANGELOG.md -- ':!docs/brainstorms/' ':!docs/plans/' ':!docs/solutions/' ':!CHANGELOG.md:### D6b'` returns no hits (or only intentional historical references in the D6b CHANGELOG section).
- *CHANGELOG-DRAFT stub:* file exists with header only; no D6c-era staged content.
- *Public Surface DRAFT:* `FileLintContext.directory_packages` row exists + classified INTERNAL.
- *Full suite green:* `pytest` (entire test suite) passes; baseline 1906 + N new tests from U1-U4.
- *ruff + mypy clean.*

**Verification:**
- `pyproject.toml` shows `version = "0.4.0"`.
- CHANGELOG.md has new `### D6c — cross-file lint dispatch (Arch-D pre-walk accumulator) + 25/26 buf BASIC parity (0.4.0)` section with 6-subsection structure.
- README.md Schema Linting section reflects 25/26 with PACKAGE_NO_IMPORT_CYCLE deferral caveat.
- CHANGELOG-DRAFT.md is header-only stub.
- `tests/test_changelog_d6c_entry.py` exists + passes.
- Full test suite + ruff + mypy all green.
- 4 `/ce:compound` learning candidates captured at delivery boundary:
  1. **Accumulator-architecture pattern (Arch-D)** — single-pass file-scan accumulator shared across rule callables; interface contract + invalidation rules. NEW.
  2. **MappingProxyType immutability for shared accumulator returns** — protection pattern for 2-3-level wrapped accumulator results. NEW.
  3. **Brainstorm-time empirical verification reshapes architectural choice** — the OQ-1 + buf-BASIC-recount findings; extension or NEW candidate for [[plan-review-verify-prior-art-citations-2026-05-15]]. NEW.
  4. **Cross-file helper design for buf-parity directory-aware rules** — if U2 + U3 produced reusable patterns. NEW (candidate; capture only if novel).
- 3 cross-references to existing learnings: extend [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]] with the 4th instance from U3; extend [[plan-review-verify-prior-art-citations-2026-05-15]] with the brainstorm-time count-verification gap; refresh [[stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12]] with D6c's sweep instance.

## System-Wide Impact

- **Interaction graph:** The new `_build_directory_package_accumulator` runs in `LintEngine.run()` once per invocation; ctx threading is through the existing `_build_file_ctx`. No new entry points or middleware. R8 + R8b are standard `@lint_rule` callables.
- **Error propagation:** Accumulator returns `None` on empty `pool_file_names`; rule callables defensively `if not ctx.directory_packages: return`. Existing `_RULE_EXCEPTION_TUPLE` catch in `LintEngine._invoke_rule` covers any uncaught exceptions from R8/R8b → `LintRuntimeWarning(category="rule_exception")`.
- **State lifecycle risks:** New `_current_directory_packages` reset in `run()` `finally` (per U1 lifecycle parity). No cache; no persistent state. No reentrancy concerns beyond the existing reentrant `run()` guard at `engine.py:340-344`.
- **API surface parity:** None — protokit-lint has no separate APIs to mirror (compat subsystem is independent).
- **Integration coverage:** U3 parity gate provides the cross-layer integration coverage that unit tests alone cannot prove (helper byte-equivalence with buf).
- **Unchanged invariants:**
  - `_LINT_JSON_SCHEMA_VERSION = "0.3"` stays the same — no consumer-visible wire-format change.
  - All 8 existing `ElementKind` values unchanged; no `ElementKind.DIRECTORY`.
  - All 8 existing `LintLocation` variants unchanged; no new variant.
  - `_builtin_lint.py:308-311` duck-typed location handling unchanged.
  - R7 PACKAGE_SAME_* family + accumulator behavior unchanged.
  - BUILTIN_PACKS tuple shape unchanged (no append; R8 + R8b live in existing `package` pack).
  - CLI dedup guard at `cli.py:828-842` unchanged.

## Risks & Dependencies

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| U3 parity gate surfaces a 4th instance of latent helper bug (per [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]] 3-prior-instance pattern) | High | Low-Med | Expected; U3 sequenced after U2 specifically so the gate surfaces bugs. Fix-cycle in U2 + re-run U3 baseline. |
| Buf v1.69.0 directory-list message format diverges from protokit's helper output (separator, sort, pluralization at N≥3) | Med | Low | KTD-10's `n3-directories-split` + `n3-packages-same-dir` fixtures specifically test this. Empirical-first posture catches at U3. |
| Worst-case migration impact measurement (Verification Step 4) reveals high-incidence breakage exceeding threshold T=50 findings/100-file repo | Low-Med | High | KD-2 falsifiability: reopen the no-dormancy decision; consider opt-in dormancy window (R8/R8b dormant in 0.4.0, flip in 0.4.1/0.5.0). U5 includes the measurement explicitly. |
| KTD-1 pack-home decision (`package.py` vs new `package_directory.py`) turns out to be wrong post-implementation (e.g., `package.py` becomes too large) | Low | Low | `package.py` currently has 2 rules; adding 2 more brings to 4 — well within reasonable bounds. If wrong, future delivery can extract to new pack (zero-cost refactor since rule_ids are stable). |
| KTD-3 consolidation (`RULE_ID_MAP` instead of sibling-isolated per-fixture map) breaks U6's KD-7 isolation invariant under some future BUILTIN_PACKS-tuple drift | Low | Low | Post-U7 the isolation rationale is empirically obsolete; the U7 KD-7 deferred decision said either option (a) consolidate or (b) document — choosing (a) is consistent with brainstorm KD-7. If wrong, U4 can be reverted to retain U6's local map. |
| U4 compound-backslash fixture surfaces third-order helper bug in `_escape_message_value` or `_truncate_values_payload` | Low-Med | Med | Per brainstorm KD-8 pre-commit, escalate U4 to 3 commits (fixture + fix + regression). U6 + U7 history shows this is the routine outcome of empirical-parity-gate work, not an exceptional one. |
| `tests/test_changelog_d6b_entry.py` audit (KTD-8) reveals "17 of 18" substring is load-bearing for some downstream consumer | Very Low | Low | The presence-ratchet pattern's purpose is to PIN intentional prose; if "17 of 18" is intentionally pinned, the U7 brainstorm should have flagged it. Audit at U5 + decide case-by-case. |
| Post-ship adoption signal (S11) reveals R8 + R8b cause unexpected breakage in the wild | Low-Med | Med | 4-6 week multi-signal monitoring per revised S11 in Operational/Rollout Notes; escalation path = 0.4.1 with R8/R8b demoted to `warning` in `default` profile until D6d. Migration recipe (KTD-7) plus monitoring provides defense-in-depth. |
| `naming/snake-case-fields` source_spec mismatch (D6d cosmetic-correction deferred) propagates the count-discrepancy if D6c's "25/26" claim depends on the AIP→buf equivalence credit | Low | Low | KTD-8 + ER-2 documentation states the credit explicitly; the 25/26 number depends on `naming/snake-case-fields` being credited as FIELD_LOWER_SNAKE_CASE parity. Alternative honest framing: "24/26 BASIC parity by buf source_spec; 25/26 by semantic equivalence." Decision at U5 wording-review. |

## Phased Delivery

D6c is a single 5-unit delivery, not phased. The unit ordering creates natural review checkpoints:

- **Phase 1 (Infrastructure):** U1 (accumulator + ctx field). Standalone review focused on lifecycle parity with R7.
- **Phase 2 (Rules):** U2 (R8 + R8b + CLI dedup regression). Standalone review focused on rule semantic correctness.
- **Phase 3 (Validation):** U3 (parity gate). Standalone review focused on empirical buf-equivalence + fixture corpus quality. **Expected to surface a U2 helper bug.**
- **Phase 4 (Hygiene):** U4 (U7 KD-7 consolidation + compound-backslash fixture). Independent of R8/R8b correctness.
- **Phase 5 (Release):** U5 (delivery boundary). All-or-nothing 0.4.0 release.

## Documentation Plan

- **README.md** Schema Linting section: parity-claim update + R8 + R8b rule-table rows + profile-table updates (U5).
- **CHANGELOG.md** `### D6c` section per KTD-7 (U5).
- **CHANGELOG-DRAFT.md** reset to header-only stub (U5).
- **`engine.py` module docstring** + Public Surface DRAFT (`FileLintContext.directory_packages` INTERNAL row) (U1 + U5).
- **`package.py:20-40` docstring rewrite** (active framing post-R8/R8b implementation) (U2).
- **`docs/solutions/`** — 4 NEW learning candidates captured at U5 `/ce:compound` boundary + 3 cross-ref extensions (per S8).
- **`tests/parity/test_parity_package_same.py:86-94` docstring** — update or delete the U7 KD-7 deliberate-isolation rationale per consolidation choice (U4).

## Operational / Rollout Notes

- **No feature flag.** R8 + R8b ship in BUILTIN_PACKS at U2; no opt-in window. Per KD-2 + KTD-5.
- **Migration recipe (KTD-7) is the user-facing mitigation.** 5-path recipe ships in CHANGELOG D6c section + README profile-table updates.
- **Post-ship adoption monitoring (S11 — revised per P1 finding #7 product-lens-#3 + product-lens-#4):** Multi-signal 4-6 week window (replacing brainstorm S11's 2-week-issue-absence proxy, which has near-zero signal for pre-1.0 lib adoption).
  - **Positive-signal channels** (any sufficient): GitHub issues/PRs referencing R8 or R8b (success or breakage); PyPI download-rate inversion (0.4.x exceeds pinned-0.3.x within window); proactive direct outreach confirming ≥2 known users evaluated 0.4.0 cleanly.
  - **Negative-signal triggers** (any one triggers 0.4.1 demotion patch): ≥1 GitHub issue reports unexpected breakage WITHOUT a usable demote-path documented in the migration recipe; PyPI download-rate stays inverted (0.3.x > 0.4.x) past week 6 indicating silent-pinning is dominant response; proactive outreach surfaces unaddressed migration pain.
  - **Escalation action**: 0.4.1 patch demoting R8 + R8b to `warning` severity in `default` profile (keep `error` in `recommended`), pending D6d resolution. Release-cadence assumption: 0.4.1 cuttable within 1 week of trigger.
- **Worst-case migration impact measurement (EXECUTED at /ce:plan-review time per P1 finding #3 — moved from U5 to Phase 0).** Result: 0 R8 + 0 R8b findings against protokit's own 39-file corpus (well under T=50). Limitation: external corpora not accessible — KD-2 falsifiability remains conditional on real-world signals via S11.
- **No data migration; no schema migration; no backfill.** Plan touches only lint rules + test infrastructure + release artifacts.

## Sources & References

- **Origin document:** `docs/brainstorms/2026-05-18-d6c-r8-cross-file-package-same-directory-requirements.md`
- **Predecessor plans:** `docs/plans/2026-05-18-002-feat-d6b-u7-delivery-boundary-0-3-0-release-plan.md` (U7 carry-forward source) + `docs/plans/2026-05-18-001-feat-d6b-u6-r7-package-same-parity-tests-plan.md` (parity-gate prior art)
- **D6b parent brainstorm:** `docs/brainstorms/2026-05-14-protokit-lint-delivery-6b-option-aware-and-multi-language-requirements.md` (R8 deferral rationale)
- **Empirical OQ-1 verification artifacts (brainstorm-time):** /tmp/d6c_oq1_psd/, /tmp/d6c_oq1_field/, /tmp/d6c_oq1_cycle/, /tmp/d6c_oq1_verification/, /tmp/d6c_basic_test/ (cleaned up post-extraction)
- **Phase 0 verification artifacts (/ce:plan-review-time):** /tmp/d6c_phase0/{wkt_inclusion, empty_pkg, proto_root, transitive, n3_dirs, n3_pkgs, cofire, cb_quote, worst_case}/ (recipes for reconstruction documented in Phase 0 section)
- **Buf v1.69.0 BASIC rule enumeration:** `buf config ls-lint-rules --configured-only --format=json` against v2 buf.yaml with `use: [BASIC]` — 26 rules total
- **R7 prior art:** `src/protokit/schema/lint/rules/package_same.py` + `src/protokit/schema/lint/engine.py:488-582` + `tests/parity/test_parity_package_same.py` + `tests/schema/lint/rules/fixtures/package_same/`
- **Document-review pass for brainstorm:** 5 reviewers (coherence + feasibility + product-lens + scope-guardian + adversarial); 9 auto-fixes applied; 20 present-class findings; user-refined via OQ-1 empirical verification + top P1 findings.
- **Document-review pass for THIS plan:** 5 reviewers (coherence + feasibility + product-lens + scope-guardian + adversarial); 51 findings total → 7 auto-fixes applied + 7 P1 findings addressed (assert_parity_multi_file architectural decision KTD-12 + KTD-9 rewrite + Phase 0 verifications + KTD-4 (d) `pool_file_names` → `root_files` correction + KTD-11 source_spec correction + Strategic Sequencing subsection + revised S11 multi-signal monitoring) + Phase 0 verifications EXECUTED at /ce:plan-review time.
