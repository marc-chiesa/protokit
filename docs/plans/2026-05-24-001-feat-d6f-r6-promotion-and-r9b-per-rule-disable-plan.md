---
title: "D6f — R6 Promotion to ERROR + R9b Per-Rule Disable (0.7.0)"
type: feat
status: active
date: 2026-05-24
origin: docs/brainstorms/2026-05-23-d6f-r6-promotion-and-r9b-per-rule-disable-requirements.md
---

# D6f — R6 Promotion to ERROR + R9b Per-Rule Disable (0.7.0)

## Overview

D6f is a **D6e KD-1 demonstration delivery**: the first post-closing-arc release that exercises the inverted UX philosophy (`protokit-UX overrides buf-parity`) on a *user-facing severity decision*. Two paired changes shipped in three implementation units:

- **U2 (R9b infrastructure, ships first)** — full per-rule disable surface: `"off"` severity sentinel (intercepted at config-coercion layer; does NOT extend the `LintSeverity` enum), `disabled_rules` / `enabled_rules` pyproject lists, `--disable-rule` / `--enable-rule` CLI flags, `custom/<suffix>` multi-kind prefix-expansion at config-resolution layer, and 2 new `LintRuntimeWarning.category` values (`"contradictory_disable_config"` + `"unknown_rule_id"`).
- **U1 (R6 promotion)** — flip all 5 rules in `options/deprecated_replacement` from `severity=WARNING` to `severity=ERROR` in the `default` profile only.
- **U3 (delivery boundary, 0.7.0)** — pyproject `0.6.0` → `0.7.0`, `_LINT_JSON_SCHEMA_VERSION` `"0.5"` → `"0.6"` (closed-Literal addition trigger), CHANGELOG fold, README refresh with new "Disabling and re-enabling rules" subsection, BUILTIN_PACKS docstring update, presence ratchets, stale-text sweep, CLI dedup regression coverage.

The ordering (U2 → U1 → U3) is deliberate: R9b ships as the safety net BEFORE R6 promotion creates upgrade pressure. Per [[post-ship-adoption-monitoring-pre-1.0-breaking-default-change-2026-05-19]], silent-pinning is the dominant user response to new ERROR-severity rules in pre-1.0 libraries; landing the escape hatch first ensures the migration recipe is real on day one.

## Problem Frame

R6 promotion has been deferred since D6b ship (2026-05-17) gated on real-world evidence via the PD-11 forcing-function (N=3 reports / M=8 weeks). Per D6e PD-11's community-size caveat: at protokit's small user community, N=3 may never fire even when a real regression hits a meaningful fraction of users. The choice is to wait indefinitely OR ship the promotion as a deliberate D6e KD-1 demonstration. R9b has been deferred since D6a gated on "real-demand evidence to design the 4 collision-shape precedence semantics against" — R6 promotion is exactly that evidence. R9b also independently resolves a documented UX defect: per D6e CHANGELOG, the current `"off"` workaround (`= "info"` + `--min-severity warning`) is a 2-step suppression mechanism that requires understanding the severity floor interaction.

(see origin: `docs/brainstorms/2026-05-23-d6f-r6-promotion-and-r9b-per-rule-disable-requirements.md`)

## Requirements Trace

Carried from brainstorm:

- **R1** — R6 family WARNING → ERROR in `default` profile (5 rule_ids enumerated in U1 Approach below).
- **R2** — Migration recipe (4 paths: fix schema, demote-to-warning, R9b disable, version pin); MUST include the 5-rule family-list form per KD-4.
- **R3** — Upgrade-impact table by `--max-warnings` posture (mirrors D6e R4b inverse-direction).
- **R4** — `"off"` as accepted `[severities]` value (sentinel at coercion layer per KD-1 + [[semantic-category-conflation-accepted-tradeoff-literal-widening-2026-05-13]]).
- **R5** — `disabled_rules` / `enabled_rules` pyproject lists.
- **R6** — `--disable-rule` / `--enable-rule` CLI flags (repeatable; CLI > pyproject within polarity).
- **R7** — Uniform `custom/<suffix>` treatment with multi-kind prefix-expansion at config-resolution layer.
- **R8** — Precedence semantics (polarity-first / tier-second; full 13-case resolution table).
- **R8b** — `LintRuntimeWarning(category="contradictory_disable_config")` for collisions where one directive is silently overridden.
- **R8c** — `LintRuntimeWarning(category="unknown_rule_id")` for lenient-with-warning rule_id validation.
- **R9** — Discoverability surfaces (CLI `--help` epilog, README "Disabling and re-enabling rules" subsection, CHANGELOG D6f section, BUILTIN_PACKS docstring).
- **R10** — pyproject package version `0.6.0` → `0.7.0` (U3).
- **R10b** — `_LINT_JSON_SCHEMA_VERSION` `"0.5"` → `"0.6"` (lands in U2 atomic with the new `LintRuntimeWarning.category` Literal values per KD-7; documented here for trace completeness).
- **R11** — CHANGELOG fold (5 subsections per [[builtin-packs-expansion-changelog-migration-recipe-structure-2026-05-18]]).
- **R12** — README refresh (profile table description update; new Upgrade notes section; new "Disabling and re-enabling rules" subsection).
- **R13** — Presence ratchets (`DELIVERY_RATCHETS` D6f entry; BUILTIN_PACKS docstring substring pin for R9b mechanism).
- **R14** — Stale-text sweep (two-pass recipe per updated 2026-05-23 learning).
- **R14b** — CLI dedup regression test for R9b flag interaction (5 enumerated cases).

## Scope Boundaries

Explicit non-goals (deferred to D6g+ or later):

- R6 promotion in `recommended` profile (no buf BASIC analogue)
- SHA-pinning test for D6e U3 buf snapshots
- U3 ce:review residual P2/P3 unit tests (`_tarjan_scc`, `_walk_cycle_forward`, `_import_source_position`)
- `options/field-behavior-consistent` IDENTIFIER-based contradictions
- `strict` profile rule enumeration (COMMENT_*, ENUM_ZERO_VALUE_SUFFIX, etc.)
- MCP/IDE engine-recycle rebuild contract
- Buf-parity aliases (`--except-rule` / `--also-rule`) — 12-week trigger window expires 2026-08-15
- Per-finding suppress mechanism (`[severities] "custom/X.params.option" = "off"`)
- Layered multi-pyproject inheritance (project is **flat-config-only** — see KD-3 below)

The CLI `--help` epilog `--min-severity` filter visibility note (pre-existing AC-4 from D6e U4 ce:review) is **folded INTO R9**, NOT deferred.

## Context & Research

### Relevant Code and Patterns (Phase 0 verification CONFIRMED)

| Concern | File:Line | Verified Shape |
|---|---|---|
| `LintSeverity` enum (3 members, plain `Enum`) | `src/protokit/schema/lint/model.py:83-95` | `ERROR="error"`, `WARNING="warning"`, `INFO="info"` |
| `SEVERITY_RANK` dict (3 keys) | `src/protokit/schema/lint/model.py:121-125` | `INFO=0, WARNING=1, ERROR=2` |
| `LintProfile.compose()` most-strict-wins loop | `src/protokit/schema/lint/model.py:802-820` | `KeyError` mode confirmed if `LintSeverity.OFF` entered `rule_severity_overrides` |
| `_ALLOWED_KEYS` frozenset (8 current keys) | `src/protokit/schema/lint/_config.py:447-458` | `disabled_rules` + `enabled_rules` NOT present; must be added |
| `from_dict` + `NotImplementedError` guards (cli_overrides shape) | `src/protokit/schema/lint/_config.py:1684` (severities) + `:1730` (custom_annotation_rules) | Guard-then-resolve pattern established |
| `_coerce_exclude` (reference pattern for list coercers) | `src/protokit/schema/lint/_config.py:575-607` | Type-strict list-of-strings coercion with `error_exit_with_code` |
| `_coerce_severities` dynamic error message | `src/protokit/schema/lint/_config.py:780-791` | Iterates `LintSeverity` for "valid values" string (won't break with sentinel pattern since `OFF` is NOT added to enum) |
| R6 family at `severity=WARNING` (5 rules) | `src/protokit/schema/lint/rules/options/deprecated_replacement.py` | All 5 confirmed; module docstring 27-32 explicitly anticipates promotion |
| Exit-code logic | `src/protokit/schema/lint/cli.py:1210-1222` | `has_error` short-circuit confirmed |
| Min-severity filtering | `src/protokit/schema/lint/engine.py:1458-1462` | Rank-based; `KeyError` mode for `OFF` confirmed |
| Custom multi-kind mangling | `src/protokit/schema/lint/_custom_rules.py:430-476` + `synthetic_rule_ids` at `:482-512` | Separator `__` confirmed; first kind = `custom/<suffix>`; subsequent = `custom/<suffix>__<kind.value>` |
| Existing CLI flag patterns (`--rule-pack`, `--exclude`) | `src/protokit/schema/lint/cli.py:349-362` + `:494-511` | `multiple=True`, `metavar="MODULE"`; reference for `--disable-rule` / `--enable-rule` |
| SARIF formatter `assert_never` | `src/protokit/formatters/_builtin_lint.py:598-613` | Wire-safety invariant: `LintSeverity.OFF` reaching this raises `AssertionError` — never allow OFF to enter `LintFinding` |
| `LintRuntimeWarning.category` Literal (7 current values) | `src/protokit/schema/lint/model.py:593-601` | New `"contradictory_disable_config"` + `"unknown_rule_id"` slot as items 8 + 9 |
| `_LINT_JSON_SCHEMA_VERSION` | `src/protokit/formatters/_builtin_lint.py:312` | Currently `"0.5"`; bumps to `"0.6"` per R10b/U2 (atomic with new `LintRuntimeWarning.category` Literal values; NOT deferred to U3 per KD-7) |
| pyproject package version (DISTINCT from schema version above) | `pyproject.toml` | Currently `"0.6.0"` (post-D6e); bumps to `"0.7.0"` per R10/U3 |
| Parametrized dedup test | `tests/schema/lint/test_cli_rule_pack_dedup.py` | Parametrized over `BUILTIN_PACKS`; R14b extends as new methods, not new parametrize cases |

### Brainstorm vs. Reality — Two corrections

**R6 actual rule_id names** (brainstorm used shortened forms; ACTUAL forms confirmed at `src/protokit/schema/lint/rules/options/deprecated_replacement.py`):

| ElementKind | Actual rule_id |
|---|---|
| FIELD | `options/deprecated-field-must-have-replacement-comment` |
| ENUM_VALUE | `options/deprecated-enum-value-must-have-replacement-comment` |
| METHOD | `options/deprecated-method-must-have-replacement-comment` |
| MESSAGE | `options/deprecated-message-must-have-replacement-comment` |
| ENUM | `options/deprecated-enum-must-have-replacement-comment` |

**The R2 migration recipe TOML snippets in the brainstorm use shortened forms** (e.g., `"options/deprecated-replacement/field"`). U1's CHANGELOG migration recipe MUST use the actual rule_ids verified above. The brainstorm's example forms are pedagogical placeholders only.

**Multi-kind prefix expansion is NEW behavior**: `synthetic_rule_ids()` returns individual mangled forms; there is no existing prefix-match API. R9b's `disabled_rules = ["custom/audit-required"]` prefix-expansion logic must be built fresh at the config-resolution layer (see KD-2 below). This is documented in R7 of the brainstorm.

### Institutional Learnings

Carried from brainstorm (already cited):
- [[migration-recipe-severity-aware-template-reuse-2026-05-21]] (R6 = 4th severity-language pattern: WARNING→ERROR promotion)
- [[changelog-readme-snippet-fixture-byte-equivalence-2026-05-21]] (every TOML snippet maps to a fixture)
- [[presence-ratchet-pin-canonical-not-local-form-2026-05-23]] (R9b ratchet substring discipline)
- [[stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12]] (updated 2026-05-23; two-pass sweep)
- [[delivery-boundary-unit-commit-composition-2026-05-14]] (7-component checklist)
- [[pre-1.0-version-bump-as-communication-contract-2026-05-14]] (0.6.0 → 0.7.0)
- [[delivery-boundary-bundled-commit-feat-plus-review-followups-2026-05-21]] (commit shape; default split)
- [[builtin-packs-expansion-changelog-migration-recipe-structure-2026-05-18]] (5-sub-section template)
- [[closed-literal-discriminator-bump-trigger-2026-05-17]] (schema bump 0.5 → 0.6)
- [[cli-loaded-packs-dedup-zip-strict-builtin-packs-flip-2026-05-18]] (R14b)

NEW for D6f (surfaced by learnings-researcher; brainstorm did not cite):
- [[click-parameter-source-detection-cli-config-precedence-2026-05-11]] — `multiple=True` natural empty-tuple sentinel: NO `ParameterSource` detection needed for `--disable-rule` / `--enable-rule`.
- [[cli-overrides-deferred-key-notimplemented-trip-wire-2026-05-12]] — `NotImplementedError` trip-wire pattern for staged pyproject-then-CLI deliveries. Researched, then EXPLICITLY NOT APPLIED to D6f per KD-4 (U2 ships pyproject + CLI atomically; no inter-unit window to guard). Cited here for traceability; the pattern remains available for future deliveries with staged pyproject/CLI shipping.
- [[symmetric-coercion-strictness-multi-source-field-resolver-2026-05-12]] — CLI path in `from_dict` must use SAME `isinstance` strictness as `_coerce_disabled_rules` / `_coerce_enabled_rules` pyproject coercers. No `list(cli_value)` shortcuts.
- [[normalize-at-input-boundary-2026-05-07]] — rule_ids in `disabled_rules` / `enabled_rules` must be normalized to canonical lowercase (`.strip().lower()`) at parse time. `_loaded_specs` keys are always lowercase.
- [[semantic-category-conflation-accepted-tradeoff-literal-widening-2026-05-13]] — strong institutional precedent for the sentinel pattern (intercept `"off"` before `LintSeverity` construction; do NOT widen the enum).
- [[multi-unit-ce-review-stash-pop-coordination-2026-05-21]] — stash-pop discipline applies symmetrically to the U2 → U1 reverse-order shipping.
- [[post-ship-adoption-monitoring-pre-1.0-breaking-default-change-2026-05-19]] — 4–6 week post-release monitoring window for R6 promotion; positive-signal channels + negative triggers; outreach targets booked BEFORE release.
- [[source-aware-error-messages-multi-source-resolved-value-2026-05-11]] — confirms flat-config-only architecture (no multi-tier pyproject inheritance); supports adversarial-F6 deferral.
- [[parametrized-matrix-tests-inherit-schema-validators-2026-05-12]] — schema_version `"0.5"` → `"0.6"` requires grep audit for literal `"0.5"` assertions in test fixtures.
- [[value-migrated-vs-value-added-consumer-migration-2026-05-17]] — R9b's 2 new `LintRuntimeWarning.category` values are PURE ADDITIONS (no migration of existing emit sites); R6 promotion is a severity change (not value migration). Frame CHANGELOG accordingly.

## Key Technical Decisions

### KD-1 — `"off"` as config-layer sentinel, NOT `LintSeverity` enum member (with explicit propagation contract)

The brainstorm KD-7 recommends config-layer interception; this plan confirms the implementation choice per strong institutional backing from [[semantic-category-conflation-accepted-tradeoff-literal-widening-2026-05-13]]:

- **DO NOT** add `LintSeverity.OFF` to the enum at `src/protokit/schema/lint/model.py:83-95`.
- **DO NOT** add a key to `SEVERITY_RANK` at `:121-125`.
- **DO** intercept the string `"off"` in `_coerce_severities` at `src/protokit/schema/lint/_config.py:780-791` BEFORE the `LintSeverity(normalized)` call. The interception strips `"off"` entries from the severities dict AND accumulates the affected rule_ids in a separate set.

**`_coerce_severities` return-shape change**: change the return type from `dict[str, LintSeverity]` to a `_CoercedSeverities` NamedTuple (or equivalent dataclass) carrying `(severities: dict[str, LintSeverity], off_rule_ids: frozenset[str])`. All existing call sites (currently `from_dict` at `_config.py:1684+` area) are updated to consume the new shape. This is a contained refactor — `_coerce_severities` has a single call site.

**Sentinel propagation path** (resolves the most-acute review finding):

1. `_coerce_severities` returns `(severities_dict_without_off, off_rule_ids)`.
2. `from_dict` accumulates `off_rule_ids` into the same set as `disabled_rules`. There is ONE effective disabled set returned to callers; no split between "disabled via `"off"`" and "disabled via `disabled_rules`" leaks past `from_dict`. This avoids the silent-no-op risk in `cli.py`'s severities overlay path at `:954-961` which would otherwise never consult a separate `disabled_via_off_severity` field.
3. R8b contradictory-config warnings (Req-R8b) MUST be emitted BEFORE the merge, since they need attribution. `from_dict` therefore:
   1. Computes `disabled_via_off_severity` locally (from `_coerce_severities` return).
   2. Compares against `enabled_rules` to emit R8b warnings naming `[severities] "X" = "off"` as the disabling source.
   3. Computes the union with `disabled_rules` to produce the final effective `disabled: frozenset[str]` set.
   4. Returns `ResolvedLintConfig` with a SINGLE unified `disabled_rules: frozenset[str]` field (NOT a separate `disabled_via_off_severity` field).
4. `cli.py` consumes `resolved.disabled_rules` directly when computing `composed_profile.rule_ids` — subtract the disabled set from the composed profile membership BEFORE handing rule_ids to the engine. This requires one explicit step in `cli.py` post-`compose_profile()`: `effective_rule_ids = composed_profile.rule_ids - resolved.disabled_rules`. The plan U2 file list MUST include this `cli.py` change explicitly (added to U2's Modify list below).

**Rationale**: Adding `OFF` to the enum cascades through every consumer of severity (`SEVERITY_RANK` lookup, `_emit()` filter, SARIF formatter `assert_never`, JSON wire-format string, severity-coloring in `human` formatter). The sentinel pattern keeps `LintSeverity` closed to the rank ladder and pushes the "do not load" semantic to the rule-activation layer where it naturally belongs. The merge-at-from_dict design avoids exposing a "two sources of disable truth" public dataclass API per scope-guardian F6.

**Wire-safety invariant**: `LintFinding(severity=...)` MUST NEVER carry an OFF marker. The disabled rules are filtered out at engine setup (before any `_emit()` call); the SARIF formatter `assert_never` path at `_builtin_lint.py:598-613` remains unreachable for OFF.

### KD-2 — Multi-kind custom rule prefix expansion at config-resolution layer (with explicit ordering + matching)

The brainstorm R7 requires that `disabled_rules = ["custom/audit-required"]` suppress ALL kinds of the `audit-required` entry. Per [[rules-tuple-insertion-order-load-bearing-engine-dispatch-2026-05-19]] sibling reasoning, prefix expansion happens at config-resolution time, NOT engine-dispatch time:

- The engine's `_loaded_specs` dict is keyed by exact (possibly mangled) rule_id strings. Engine dispatch remains a hash lookup; no prefix matching in the hot path.
- `synthetic_rule_ids()` at `src/protokit/schema/lint/_custom_rules.py:482-512` takes `Sequence[CustomAnnotationRuleSpec]` and requires NO engine state (the false-alarm concern about engine state has been verified false). It can run inside `from_dict`.

**Intra-`from_dict` ordering** (resolves adversarial F2):

1. Coerce `custom_annotation_rules` FIRST. This produces `resolved_custom_annotation_rules: tuple[CustomAnnotationRuleSpec, ...]` from the pyproject array-of-tables.
2. Coerce `disabled_rules` / `enabled_rules` lists (raw string entries).
3. NOW expand `custom/<suffix>` bare entries: for each entry in `disabled_rules` matching `custom/<suffix>` (without `__<kind>` mangling), find the matching spec via **suffix equality** (NOT substring match): the spec whose `spec.rule_suffix == suffix`. If found, call `synthetic_rule_ids((spec,))` to get the set of mangled forms for that specific spec, and add the result to the effective disabled set. If no spec matches the bare suffix, the entry is preserved as-is (it may match a future-shipped or external rule; the unknown-rule_id warning per Req-R8c fires from the engine layer later).
4. Apply the same expansion to `enabled_rules`.

**Matching algorithm** (resolves feasibility KD2-BARE-PREFIX-MATCH-GAP): strip the `custom/` prefix to get the bare suffix, then iterate `resolved_custom_annotation_rules` and find specs where `spec.rule_suffix == suffix` (exact string equality). This guarantees `"custom/foo"` does NOT match `"custom/foobar"` (a substring-match implementation would).

**Per-kind disable still works** via explicit mangled form: `disabled_rules = ["custom/audit-required__method"]` (no expansion; exact match).

### KD-3 — Flat-config-only (no multi-tier pyproject inheritance)

Per [[source-aware-error-messages-multi-source-resolved-value-2026-05-11]] and codebase architecture inspection: protokit currently uses **flat-config-only**. There is no `find_pyproject_files()` that walks parent directories and merges multiple `[tool.protokit.lint]` tables. The brainstorm adversarial-F6 layered-config scenario (parent `disabled_rules` + child `enabled_rules`) is therefore HYPOTHETICAL — D6f does not implement it.

The brainstorm R8 polarity-first-disable-wins-across-tiers resolution applies WITHIN a single pyproject's `disabled_rules` + `enabled_rules` lists, AND across the CLI-vs-pyproject tier boundary. Multi-pyproject inheritance is explicit D6g+ (or later) scope.

**Document this convention explicitly** in U3's CHANGELOG section and in a new ce:compound learning at the U2 boundary (candidate identified by learnings-researcher).

### KD-4 — Trip-wire pattern does NOT apply to D6f (U2 ships pyproject + CLI atomically)

The brainstorm originally framed R9b as potentially-staged (pyproject parsing first, CLI flags second), which would have invoked [[cli-overrides-deferred-key-notimplemented-trip-wire-2026-05-12]] to guard `cli_overrides["disabled_rules"]` / `cli_overrides["enabled_rules"]` during the intermediate window. **D6f does NOT use that staging.** U2 ships pyproject parsing AND CLI flags AND the `from_dict` precedence branches in a single atomic unit. There is no inter-unit window to guard, so NO `NotImplementedError` trip-wires are added.

The trip-wire learning still applies to FUTURE deliveries where a pyproject key ships in one unit and the corresponding CLI override ships in a later unit (e.g., if D6g adds a new pyproject-only key that becomes CLI-overridable in D6h). Document the decision explicitly so a future reader understands why D6f does NOT follow the trip-wire pattern despite citing the learning in research.

**Consequence:** Skip the `NotImplementedError` guards entirely in U2. Skip the trip-wire deletion step in U1. Risks table no longer includes the trip-wire-related row.

### KD-5 — Click `multiple=True` natural empty-tuple sentinel (no ParameterSource)

Per [[click-parameter-source-detection-cli-config-precedence-2026-05-11]]: `--disable-rule` and `--enable-rule` use `multiple=True`. Click delivers an empty tuple `()` when the flag is absent. Users cannot produce `()` by typing the flag (Click requires a value). Therefore `not disable_rules` is a clean "user did not pass this flag" sentinel — NO `ctx.get_parameter_source()` needed.

CLI override wiring: `cli_override_value = tuple(disable_rules) if disable_rules else None`. NOT `disable_rules or None` (which would treat a programmatic empty-list caller as "defer to pyproject").

### KD-6 — Rule_id normalization at pyproject input boundary

Per [[normalize-at-input-boundary-2026-05-07]]: rule_ids in `disabled_rules`, `enabled_rules`, AND `[severities]` keys are normalized to `.strip().lower()` at parse time inside the `_coerce_*` helpers. The engine's `_loaded_specs` keys are always lowercase canonical IDs (`@lint_rule` decorator convention). Without normalization, a user typo like `"Naming/Snake-Case-Fields"` silently no-ops.

The unknown-rule_id warning from Req-R8c fires AFTER normalization, so users see the normalized form in the warning text (helps diagnose case-sensitivity issues).

### KD-7 — Schema version bump moves to U2 (atomic with Literal additions)

`_LINT_JSON_SCHEMA_VERSION` bumps `"0.5"` → `"0.6"` per [[closed-literal-discriminator-bump-trigger-2026-05-17]]. ONE bump covers BOTH new `LintRuntimeWarning.category` values (`"contradictory_disable_config"` from Req-R8b + `"unknown_rule_id"` from Req-R8c).

**Bump lands in U2, NOT U3** (revised post-review per feasibility SCHEMA-VERSION-INCONSISTENCY-U2-TO-U3): the cited learning's policy is that schema-version bumps trigger ON the closed-Literal change, not at the delivery boundary. U2 adds the two new `LintRuntimeWarning.category` Literal values to `model.py:593-601`; U2 MUST also bump `_LINT_JSON_SCHEMA_VERSION` in the same commit at `src/protokit/formatters/_builtin_lint.py:312`. Deferring the bump to U3 would emit `schema_version: "0.5"` with new category values in the wire format during the U2-shipped / U3-unshipped window — contradicting the policy and breaking any consumer parsing the schema against `"0.5"`.

The **pyproject `0.6.0` → `0.7.0` package version bump** stays in U3 (package release is genuinely a delivery-boundary act tied to the release tag). The two version strings are distinct surfaces with distinct triggers — do NOT conflate them.

Schema-version assertion sites (`grep -rn '"0.5"' tests/`) audited and updated to `"0.6"` in U2 alongside the bump (NOT deferred to U3). Per [[parametrized-matrix-tests-inherit-schema-validators-2026-05-12]] — any new parametrized test class asserting schema_version must use the new value at U2.

### KD-8 — Post-ship monitoring booked BEFORE U1 R6 promotion lands (with explicit "noisy" rubric)

Per [[post-ship-adoption-monitoring-pre-1.0-breaking-default-change-2026-05-19]]: R6 promotion is a "breaking-default-change" with silent-pinning as the dominant user response. U1 implementation MUST be preceded by the empirical-evidence step in Phase 0.

**Step 1 — Run protokit 0.7.0-candidate on two corpora:**
- (a) Project's own test fixtures: all `.proto` files under `tests/parity/fixtures/` and `tests/schema/lint/rules/fixtures/`. This is the **primary** corpus — bounded, fast, exhaustive, contains intentional fixtures exercising the R6 heuristic.
- (b) External corpus: a random 200-file sample from googleapis (clone `https://github.com/googleapis/googleapis` to `/tmp/googleapis-d6f-test`; use `find . -name "*.proto" | shuf -n 200` to sample). The 200-file cap bounds the classification work to ~30 minutes max. If the sample returns zero R6 hits, the primary corpus result is authoritative; do NOT extend to a larger sample.

**Step 2 — Classify each R6 hit:**

The leading-comment-regex heuristic in `deprecated_replacement.py` matches a specific shape (replacement annotation in the leading comment). A hit "fires" when `deprecated=true` is set AND the heuristic does NOT match the comment. Classify each hit by reading the leading comment with this rubric:

| Classification | Comment shape | Action |
|---|---|---|
| **Genuine** (heuristic correctly flags) | No replacement reference at all; `// Deprecated.` or `// TODO: remove` or empty/missing comment | Severity ERROR is appropriate |
| **Noisy — informal replacement** | Replacement exists but in non-canonical form: `// Use FooBar instead.` / `// Replaced by FooBar in v2.` / `// Migrate to package.FooBar.` / `// See FooBar` / `// → FooBar` | Human reviewer would accept; regex misses |
| **Noisy — cross-team deferral** | `// Deprecated, do not remove until team X migrates.` / `// Kept for backward compat with v1 clients.` | Legitimate deprecation-without-replacement-by-design |
| **Noisy — TODO with no immediate fix path** | `// TODO(@username): figure out the replacement story.` | Genuine unknown, not a heuristic miss |

If the "noisy" categories (rows 2-4) collectively exceed **10% of total hits** OR exceed **5 noisy hits** in absolute count (whichever is smaller — protects against small-N rate distortion), the KD-1 demonstration framing is unsafe. STOP and revise: either tighten the heuristic regex in `deprecated_replacement.py` (defensible if Noisy-1 dominates), OR delay R6 promotion to a 0.7.x patch and ship D6f as R9b-only.

**Step 3 — Document results**: ALWAYS record the per-corpus hit count + per-category classification breakdown in the U1 commit message body (mandatory, not optional). If the >10% gate trips, ALSO capture the analysis as `docs/solutions/best-practices/d6f-r6-promotion-phase-0-falsification-2026-05-XX.md` per the EV-2 falsification precedent from D6e.

**Step 4 — Book the post-ship monitoring window** (only if Step 3 passes the gate):
- 4-6 week window starting at 0.7.0 release date.
- PyPI download stats baseline captured before release.
- ≥2 outreach targets recorded (real users of protokit-lint, NOT internal contributors).
- GitHub issue search query saved: `is:issue R6 OR deprecated-replacement OR "deprecated-field-must-have"`.

This is the BACKSTOP for KD-1 demonstrations going wrong. KD-1 is rationalizable; PD-11 is not. Both apply to D6f.

## Open Questions

### Resolved During Planning

- **U2 vs U1 sequencing**: U2 ships first (R9b safety net) per brainstorm Pressure Test rationale + [[post-ship-adoption-monitoring-pre-1.0-breaking-default-change-2026-05-19]] confirming safety-net-first as the correct ergonomic ordering.
- **"off" enforcement layer**: Config-coercion layer (sentinel pattern) per KD-1 above + [[semantic-category-conflation-accepted-tradeoff-literal-widening-2026-05-13]].
- **Multi-kind prefix expansion location**: Config-resolution layer per KD-2 above.
- **R9b interaction with `--rule-pack`** (OQ-3 from brainstorm): Rule-level R9b wins over pack-level loading per R8 polarity-first. Test enumerated in U2 test scenarios + U3 R14b case 3.
- **`_LINT_JSON_SCHEMA_VERSION` bump** (OQ-4 from brainstorm): Affirmative; `"0.5"` → `"0.6"` per KD-7.
- **README placement** (OQ-5 from brainstorm): Between profile table and migration-recipe paragraph; structure mirrors disable/enable/composition trichotomy (R12 in U3).
- **Layered pyproject scope**: Out of scope per KD-3 (flat-config-only architectural reality).

### Deferred to Implementation

- **R6 empirical hit-rate validation**: Phase 0 verification step run at the START of U1 (after U2 is committed). Decision-point: if hit-rate exceeds 10% threshold, revise scope before continuing.
- **`--no-config` escape-hatch path** (CONFIRMED EXISTS per Phase 0 repo-research): exists at `src/protokit/schema/lint/cli.py:483-491` as `is_flag=True`; when set, `load_pyproject_config` returns `None`; `from_dict(table=None, cli_overrides={...})` produces "no disabled_rules / no enabled_rules" semantics correctly. R9 documentation can confidently name `--no-config` as the blunt-instrument escape hatch — but documentation MUST disclose that `--no-config` drops ALL pyproject configuration (profile, exclude, severities, custom_annotation_rules, etc.), not just `disabled_rules`. Users who want to override a single disabled rule without losing the rest of their pyproject must edit the pyproject directly. The R8b warning text for the cross-tier `--enable-rule R + pyproject disabled_rules ⊃ R` case MUST include this caveat to avoid users misusing `--no-config` and losing their lint config.
- (Trip-wire deletion-order question removed: KD-4 was updated post-review to explicitly skip the trip-wire pattern since U2 ships pyproject + CLI atomically. Nothing to delete in U1.)
- **Exact CLI flag positioning in the help epilog**: R9 specifies the flags exist in epilog; the exact position relative to existing `--rule-pack` / `--no-builtin-rules` etc. is a docs-author judgment call at U2 implementation time.

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

### R9b config-resolution layer (U2's load-bearing architecture)

```
   pyproject.toml                CLI flags
   ┌──────────────────┐          ┌──────────────────┐
   │ [severities]     │          │ --disable-rule   │
   │   R = "off"      │          │ --enable-rule    │
   │ disabled_rules   │          │                  │
   │ enabled_rules    │          │                  │
   └────────┬─────────┘          └─────────┬────────┘
            │                              │
            ▼                              ▼
   ┌──────────────────────┐    ┌──────────────────────┐
   │ _coerce_severities   │    │  Click multiple=True │
   │ _coerce_disabled_*   │    │  → tuple OR ()       │
   │ _coerce_enabled_*    │    │                      │
   │                      │    │  cli_overrides[key]  │
   │ • intercept "off"    │    │   = tuple if not     │
   │   → sentinel         │    │     empty else None  │
   │ • .strip().lower()   │    │                      │
   │ • list-of-strs check │    │  (KD-5 natural       │
   └──────────┬───────────┘    │   sentinel)          │
              │                └──────────┬───────────┘
              │                           │
              └────────────┬──────────────┘
                           │
                           ▼
              ┌────────────────────────────┐
              │ ResolvedLintConfig.        │
              │   from_dict(table,         │
              │             cli_overrides) │
              │                            │
              │ 1. Apply precedence per    │
              │    R8 table (polarity      │
              │    first, tier second)    │
              │ 2. Expand custom/<X>      │
              │    prefix via              │
              │    synthetic_rule_ids()    │
              │ 3. Emit R8b warnings on    │
              │    contradictory configs   │
              │ 4. Emit R8c warnings on    │
              │    unknown rule_ids        │
              │ 5. Produce effective       │
              │    {load_set, severity_    │
              │     overrides}             │
              └────────────┬───────────────┘
                           │
                           ▼
                ┌──────────────────────┐
                │ LintEngine.run()     │
                │                      │
                │ • _loaded_specs ←    │
                │   load_set (rule_ids │
                │   in effective set)  │
                │ • severity overrides │
                │   applied            │
                │ • engine dispatch    │
                │   unchanged (hash    │
                │   lookup on exact    │
                │   rule_id)           │
                └──────────────────────┘
```

The architectural commitment is that ALL R9b complexity lives in the config-resolution layer. Engine hot-path (`_emit`, profile composition, rule dispatch) sees only an effective rule set + severity overrides, indistinguishable from prior behavior. The engine never knows about `"off"`, `disabled_rules`, `enabled_rules`, `--disable-rule`, `--enable-rule`, or custom prefix expansion.

### R8 precedence resolution (single principle, two-step application)

```
For each rule_id R appearing in any R9b mechanism:

  Step 1 — POLARITY: Does ANY mechanism at ANY tier disable R?
    YES → R is excluded from load_set. Done.
    NO  → continue to Step 2.

  Step 2 — TIER: Apply CLI > pyproject within same polarity.
    If CLI enables R AND pyproject doesn't mention R → R loads.
    If CLI is silent AND pyproject enables R → R loads.
    Etc.

Contradiction warnings (R8b) fire whenever Step 1 silently
overrides a user-supplied directive at a lower tier. Specifically:
  - disabled_rules ⊃ R AND enabled_rules ⊃ R           → warn
  - --disable-rule R AND --enable-rule R               → warn
  - CLI --enable-rule R AND pyproject disabled_rules ⊃ R → warn
  - disabled_rules ⊃ R AND [severities] R = <non-off>  → warn
  - [severities] R = "off" AND enabled_rules ⊃ R       → warn

(No warning for the idempotent case: [severities] R = "off"
AND disabled_rules ⊃ R — both are disables, no override.)
```

## Implementation Units

- [ ] **Unit 1 (U2): R9b infrastructure (pyproject + CLI + warnings + schema bump)**

**Goal:** Ship the full R9b per-rule disable surface as additive capability with zero existing-behavior change. After U2, users have `"off"` severity, `disabled_rules` / `enabled_rules` pyproject lists, and `--disable-rule` / `--enable-rule` CLI flags. R6 family is still at WARNING (no migration pressure yet). `_LINT_JSON_SCHEMA_VERSION` bumps `"0.5"` → `"0.6"` atomic with the new `LintRuntimeWarning.category` Literal values per KD-7.

**Requirements:** R4, R5, Req-R6, R7, R8, R8b, R8c, R9 (CLI epilog portion only — BUILTIN_PACKS docstring moves to U3 per scope-guardian F2), R10b.

**Dependencies:** None (Phase 0 verification complete).

**Files:**
- Create:
  - `tests/schema/lint/test_r9b_precedence.py` (parametrized over the Req-R8 13-case resolution table — 12 original + 1 added case for `--enable-rule R + [severities] R = "off"`)
  - `tests/schema/lint/test_r9b_warnings.py` (R8b contradictory_disable_config + R8c unknown_rule_id coverage)
  - `tests/schema/lint/cli/cli_fixtures/d6f_r9b/` (pyproject fixtures: `off_severity.toml`, `disabled_rules_only.toml`, `enabled_rules_only.toml`, `disabled_plus_enabled.toml`, `disabled_plus_severity_override.toml`, `off_plus_enabled.toml`, `custom_multikind_disable.toml`, `unknown_rule_id.toml`)
- Modify:
  - `src/protokit/schema/lint/_config.py` — extend `_ALLOWED_KEYS` (lines 447-458) with `disabled_rules` + `enabled_rules`; add `_coerce_disabled_rules` + `_coerce_enabled_rules` helpers (following `_coerce_exclude` pattern at 575-607; regex MUST accept canonical `pack/rule-suffix` AND `custom/<suffix>` AND `custom/<suffix>__<kind>` mangled form — `__` separator is load-bearing); change `_coerce_severities` return type from `dict[str, LintSeverity]` to a `_CoercedSeverities` NamedTuple carrying `(severities: dict[str, LintSeverity], off_rule_ids: frozenset[str])`; extend `ResolvedLintConfig` dataclass with `disabled_rules: frozenset[str]` (UNIFIED field — merges severity-off and disabled_rules per KD-1) + `enabled_rules: frozenset[str]`; extend `from_dict` (lines 1509-1753) with new `cli_overrides` dispatch branches following the ordering specified in KD-2 (custom_annotation_rules FIRST, then disabled/enabled coercion + expansion). **No `NotImplementedError` trip-wires** (KD-4 explicitly skipped). Apply rule_id `.strip().lower()` normalization per KD-6.
  - `src/protokit/schema/lint/cli.py` — add `--disable-rule` + `--enable-rule` Click options (`multiple=True`, slot near `--no-builtin-rules` per CLI flag grouping); plumb to `cli_overrides` per KD-5 (`cli_override_value = tuple(disable_rules) if disable_rules else None`); extend `--help` epilog per R9 (folds in AC-4 `--min-severity` visibility note + documents `--no-config` as the blunt-instrument escape hatch with the caveat that it drops ALL pyproject configuration, not just `disabled_rules`); **ADD the explicit profile-augmentation step**: after `compose_profile()`, compute `effective_rule_ids = composed_profile.rule_ids - resolved.disabled_rules` and use `effective_rule_ids` (NOT `composed_profile.rule_ids`) for the engine setup. This is the load-bearing wiring that makes the KD-1 sentinel actually suppress at runtime per the propagation contract in KD-1.
  - `src/protokit/schema/lint/model.py` — extend `LintRuntimeWarning.category` `Literal` (lines 593-601) with `"contradictory_disable_config"` + `"unknown_rule_id"` (items 8 + 9).
  - `src/protokit/formatters/_builtin_lint.py:312` — `_LINT_JSON_SCHEMA_VERSION = "0.5"` → `"0.6"` (atomic with the model.py Literal additions per KD-7). Update the bump-trigger docstring with D6f as the next worked example.
  - `src/protokit/schema/lint/engine.py` — emit `LintRuntimeWarning(category="unknown_rule_id")` calls in `engine.run()` (the unloaded-rule-diff step is the natural site, mirroring the existing `severities_unloaded_rule_ids` pattern at `cli.py:970`). R8b warnings (`contradictory_disable_config`) emit from `from_dict` itself since they require config-time attribution; R8c (`unknown_rule_id`) emits from the engine path since it requires `_loaded_specs`. **Engine does NOT filter `_loaded_specs` directly** (the diagram says "engine code unchanged" — that means the engine receives a pre-filtered profile, not that it does its own filtering). Engine modifications are LIMITED to the new warning emission.
- Test:
  - `tests/schema/lint/test_r9b_precedence.py` (NEW)
  - `tests/schema/lint/test_r9b_warnings.py` (NEW)
  - `tests/schema/lint/_config/test_coerce_disable_enable_rules.py` (NEW — consolidated parametrized over both helpers per scope-guardian F1; saves one test file)
  - `tests/schema/lint/_config/test_coerce_severities.py` (MODIFY — add `"off"` interception cases; verify `_CoercedSeverities` return shape with severities + off_rule_ids fields)
  - `tests/schema/lint/_config/test_from_dict_r9b.py` (NEW — `cli_overrides` dispatch + precedence + custom prefix expansion + intra-from_dict ordering verification)
  - `tests/schema/lint/cli/test_cli_disable_enable_rule_flags.py` (NEW — Click integration with `multiple=True`, repeatable, env-var integration via `PROTOKIT_DISABLE_RULE` / `PROTOKIT_ENABLE_RULE`)
  - `tests/schema/lint/cli/test_cli_r9b_profile_augmentation.py` (NEW — verifies the `effective_rule_ids = composed_profile.rule_ids - resolved.disabled_rules` step in cli.py actually suppresses runtime findings; this is the load-bearing end-to-end test that catches the silent-no-op risk from review finding F1-adversarial)
  - Schema-version test sites: grep `"0.5"` across `tests/` and update to `"0.6"` IN U2 (audit + bump together, not deferred to U3)

**Approach:**

1. **Sentinel-pattern "off" interception** (KD-1) — `_coerce_severities` intercepts the string `"off"` BEFORE `LintSeverity(normalized)`. Returns `_CoercedSeverities(severities=..., off_rule_ids=frozenset(...))` NamedTuple. `LintSeverity` enum is untouched. `from_dict` merges `off_rule_ids` into the unified `disabled_rules: frozenset[str]` field AFTER emitting any R8b warnings that need to distinguish the two sources.
2. **List coercers follow `_coerce_exclude` pattern** (lines 575-607) — same `error_exit_with_code` shape, same per-element `isinstance(str)` check, PLUS rule_id format validation. The regex MUST match three shapes: canonical `pack/rule-suffix` (e.g., `naming/snake-case-fields`), bare custom (e.g., `custom/audit-required`), AND mangled custom (e.g., `custom/audit-required__method`). Specifically NOT the existing `_CUSTOM_RULE_SUFFIX_REGEX` at `_config.py:467-469` which would reject the `__` mangled form. Plus `.strip().lower()` normalization per KD-6.
3. **Intra-`from_dict` ordering** (KD-2) — process `custom_annotation_rules` FIRST (produces `resolved_custom_annotation_rules`); THEN process `disabled_rules` / `enabled_rules` (raw lists); THEN run multi-kind prefix expansion using `synthetic_rule_ids((spec,))` per spec via **suffix-equality matching** (`spec.rule_suffix == suffix_after_custom_prefix_strip`); THEN compute R8 precedence resolution; THEN emit R8b warnings with attribution; THEN merge `off_rule_ids` into the final unified `disabled_rules` field.
4. **R8 precedence applied as effective disabled-set computation** — polarity-first (disable wins across all tiers including the CLI → pyproject cross-tier case); tier-second (CLI > pyproject within polarity). The result is a unified `disabled_rules: frozenset[str]` that `cli.py` subtracts from `composed_profile.rule_ids` to produce `effective_rule_ids` per the KD-1 propagation contract.
5. **R8b warnings emitted from `from_dict`** (config-resolution boundary, attribution-rich). **R8c warnings emitted from `engine.run()`** at the unloaded-rule-diff step (mirrors existing `severities_unloaded_rule_ids` pattern at `cli.py:970`; this is where the loaded rule registry is finally available). Both warning types carry actionable messages naming the involved rule_id + mechanism(s).
6. **CLI overrides + Click `multiple=True` natural sentinel** (KD-5) — `cli_override_value = tuple(disable_rules) if disable_rules else None`. NO `ParameterSource` machinery.
7. **No trip-wires** (KD-4 explicit) — U2 ships pyproject AND CLI atomically; no inter-unit window to guard.
8. **`_LINT_JSON_SCHEMA_VERSION` BUMPS to `"0.6"` IN U2** (revised post-review) — atomic with the model.py Literal additions per KD-7. Schema-version test sites in `tests/` audited + updated to `"0.6"` in the same U2 commit.
9. **`cli.py` profile-augmentation step** is the load-bearing wiring: after `compose_profile()`, compute `effective_rule_ids = composed_profile.rule_ids - resolved.disabled_rules` and use `effective_rule_ids` for engine setup. Without this, the KD-1 sentinel silently no-ops. The dedicated `test_cli_r9b_profile_augmentation.py` end-to-end test (in the Test list above) catches this regression.

**Execution note:** Test-first for the R8 precedence resolution table — write the parametrized test in `tests/schema/lint/test_r9b_precedence.py` covering all 13 cases (12 from brainstorm R8 + 1 added post-review: `--enable-rule R + [severities] R = "off"` is a cross-tier disable-wins case mirroring the `--enable-rule R + pyproject disabled_rules ⊃ R` case) BEFORE implementing the resolution logic. The 13-case enumeration is the test fixture spec.

**Patterns to follow:**
- `_coerce_exclude` at `src/protokit/schema/lint/_config.py:575-607` (list coercion pattern)
- `NotImplementedError` guards at `:1684` + `:1730` (deferred-key trip-wire pattern)
- `--rule-pack` at `src/protokit/schema/lint/cli.py:349-362` (`multiple=True` Click flag pattern)
- D6d `custom_annotation_extension_unresolved` + `extension_unresolved` ship pattern for the two new `LintRuntimeWarning.category` values
- D6e `field` pack addition for the pyproject `_ALLOWED_KEYS` extension shape

**Test scenarios:**

*Happy path:*
- pyproject `[severities] "naming/snake-case-fields" = "off"` → rule does not load; zero findings on a snake_case-violating fixture.
- pyproject `disabled_rules = ["naming/snake-case-fields"]` → equivalent behavior to `"off"` severity; idempotent when both present.
- pyproject `enabled_rules = ["package/no-import-cycle"]` with `--no-builtin-rules` → only `package/no-import-cycle` loads.
- CLI `--disable-rule naming/snake-case-fields` → rule does not load for that invocation; pyproject unchanged.
- CLI `--disable-rule R1 --disable-rule R2` → both R1 and R2 disabled (Click `multiple=True` repeatable).
- Custom rule single-kind: `disabled_rules = ["custom/my-rule"]` where `my-rule` is single-kind → disables the single closure.
- Custom rule multi-kind: `disabled_rules = ["custom/audit-required"]` where `audit-required` has 3 kinds → disables `custom/audit-required` + `custom/audit-required__method` + `custom/audit-required__service` (prefix expansion per KD-2).

*Edge cases:*
- Empty `disabled_rules = []` → no-op; equivalent to absent.
- Empty `enabled_rules = []` → no-op; equivalent to absent.
- `disabled_rules` with the SAME rule_id twice → deduplicated (no error).
- Rule_id with uppercase: `"Naming/Snake-Case-Fields"` → normalized to `"naming/snake-case-fields"` per KD-6; loads correctly.
- Rule_id with surrounding whitespace: `"  naming/snake-case-fields  "` → `.strip()` per KD-6.

*Error paths:*
- pyproject `disabled_rules = "not-a-list"` → exit 2 with `error[lint-pyproject-config-invalid]`.
- pyproject `disabled_rules = [123]` → exit 2 (non-string element).
- pyproject `disabled_rules = ["invalid-format-no-slash"]` → exit 2 (format validation failure).
- CLI `--disable-rule invalid-no-slash` → exit 2 (format validation; CLI parity with pyproject coercion per [[symmetric-coercion-strictness-multi-source-field-resolver-2026-05-12]]).
- CLI `--disable-rule` (no value) → Click exit 2 (Click default behavior).
- (No trip-wire test — KD-4 explicitly skipped; from_dict accepts `cli_overrides["disabled_rules"]` directly from U2 ship.)

*Integration:*
- All 13 cases from R8 resolution table → effective load_set matches expected for each. Parametrized.
- R8b contradictory_disable_config emission: pyproject `disabled_rules + enabled_rules` containing same R → exactly one `LintRuntimeWarning(category="contradictory_disable_config")` with payload identifying the rule.
- R8c unknown_rule_id emission: `disabled_rules = ["pack/nonexistent-rule"]` → one warning with normalized rule_id in payload.
- Custom prefix expansion + per-kind explicit form composition: `disabled_rules = ["custom/X", "custom/X__method"]` → idempotent (both expand to same set).
- CLI `--disable-rule R` + pyproject `disabled_rules = []` → CLI wins (within polarity; tier-second).
- CLI `--enable-rule R` + pyproject `disabled_rules = ["R"]` → R does NOT load (cross-tier disable-wins per R8); R8b warning fires.
- SARIF formatter `assert_never` reachability: construct `LintFinding(severity=LintSeverity.ERROR)` and verify SARIF emit works; confirm `LintSeverity.OFF` never enters `LintFinding` (KD-1 wire-safety invariant).

**Verification:**
- Full test suite + new tests pass (`pytest tests/schema/lint/test_r9b_precedence.py tests/schema/lint/test_r9b_warnings.py tests/schema/lint/_config/test_coerce_*.py tests/schema/lint/_config/test_from_dict_r9b.py tests/schema/lint/cli/test_cli_disable_enable_rule_flags.py tests/schema/lint/cli/test_cli_r9b_profile_augmentation.py`).
- `ruff check` clean on all touched files.
- `mypy --strict` clean on `_config.py`, `cli.py`, `engine.py`, `model.py`, `_builtin_lint.py`.
- `_LINT_JSON_SCHEMA_VERSION == "0.6"` at runtime; previous `"0.5"` assertions in `tests/` are gone.
- No `NotImplementedError` trip-wires introduced (KD-4 explicit).
- R6 family STILL at `severity=WARNING` (U1 has not happened yet).
- Sentinel propagation verified end-to-end by `test_cli_r9b_profile_augmentation.py`: setting `[severities] "naming/snake-case-fields" = "off"` produces ZERO findings on a snake_case-violating fixture (full CLI invocation, not just `from_dict` unit test).
- All existing 2171 tests pass — R9b is additive; zero existing-behavior change.

---

- [ ] **Unit 2 (U1): R6 promotion to ERROR**

**Goal:** Flip the 5 rules in `options/deprecated_replacement` from `severity=WARNING` to `severity=ERROR` in the `default` profile. Validate empirically that hit-rate is acceptable BEFORE the flip per KD-8.

**Requirements:** R1, R2, R3.

**Dependencies:** Unit 1 (U2) committed — R9b safety net must be live BEFORE R6 promotion lands so the migration recipe is real on day one.

**Files:**
- Modify:
  - `src/protokit/schema/lint/rules/options/deprecated_replacement.py` — flip `severity=LintSeverity.WARNING` → `severity=LintSeverity.ERROR` on all 5 `@lint_rule`-decorated functions; update the module docstring (lines 27-32) to reflect the post-promotion state
- Test:
  - `tests/schema/lint/rules/options/test_deprecated_replacement_severity.py` (NEW) — per-rule severity pin (parametrized over the 5 rule_ids; the rule_ids are the verified-long forms from Context & Research, e.g., `options/deprecated-field-must-have-replacement-comment`)
  - `tests/schema/lint/cli/test_cli_ci_gating.py` — extend with R6-promotion exit-code regression cases (mirroring the D6e R4b pattern at the same file)
  - `tests/schema/lint/cli/cli_fixtures/d6f_r6_migration/` (NEW) — 4 fixtures matching the 4 migration paths in R2 (fix-schema, demote-to-warning, R9b-disable-via-off, R9b-disable-via-list). **Audit for overlap with U2's `d6f_r9b/` fixtures per scope-guardian F9**: if a U2 fixture differs only in rule_id, prefer parametrization over duplication.

**Approach:**

1. **Phase 0 empirical validation** (per KD-8): BEFORE flipping severities, run protokit on (a) the project's own `tests/parity/fixtures/` + (b) a public corpus (clone googleapis to `/tmp/googleapis-d6f-test` and lint). Count R6 hits per the 5 ElementKinds; classify each as genuine vs noisy. If noisy rate >10%, STOP — revise scope to R9b-only and defer R6 promotion. If acceptable, proceed.
2. **Severity flip**: 5-line change in `deprecated_replacement.py`. Each `@lint_rule` decorator's `severity=` argument flips from `LintSeverity.WARNING` to `LintSeverity.ERROR`. The leading-comment-regex heuristic is NOT modified (per R1 scope boundary).
3. **Module docstring update**: lines 27-32 currently note "Promotion to `error` is a post-D6b decision contingent on real-world miss/hit-rate measurement." Update to reflect the post-promotion state with the empirical evidence summary from Phase 0 (cite the U1 commit's Phase 0 report).
4. **Exit-code regression tests**: extend `test_cli_ci_gating.py` with the new R6-promotion-specific cases mirroring the D6e R4b inverse-direction structure. The 3 postures (`--max-warnings` unset / `--max-warnings 0` / `--min-severity error`) each get a test verifying the post-promotion exit code.

**Execution note:** Phase 0 empirical validation is a HARD GATE before the severity flip. The flip commit must NOT be made if Phase 0 reveals >10% noisy hit-rate. Document the Phase 0 results in the commit message body.

**Patterns to follow:**
- D6e R4b `file/syntax-specified` ERROR→WARNING demotion at `src/protokit/schema/lint/rules/file.py` (inverse-direction worked example; same migration-recipe template applies)
- D6e CLI exit-code regression test at `tests/schema/lint/cli/test_cli_ci_gating.py::TestMaxWarningsExitLadder` (same file; mirror the test class structure for R6-promotion)
- `_loaded_specs` direct access NOT used — use `engine.get_spec(rule_id)` public accessor (D6d new-U3 ce:review KP-3)

**Test scenarios:**

*Happy path:*
- `default` profile lint on a proto with `deprecated=true` field WITHOUT replacement annotation → R6 fires at ERROR severity (post-promotion). Pre-promotion: same fixture fired at WARNING.
- `recommended` profile lint on same fixture → no R6 finding (R6 is `default`-only; unchanged from pre-promotion).

*Edge cases:*
- Empty deprecated annotation `deprecated=false` → no R6 finding (severity flip doesn't change trigger logic).
- Deprecated field WITH replacement annotation matching the heuristic regex → no R6 finding (severity flip doesn't change heuristic behavior).
- Multi-ElementKind hit (e.g., deprecated field + deprecated enum value in same file) → 2 R6 findings (one per ElementKind), each at ERROR severity.

*Error paths:*
- `--max-warnings 0` with R6 finding: pre-promotion exit 1 (counted as warning); post-promotion exit 1 (`has_error=True` short-circuits before `max_warnings` gate).
- `--min-severity error` with R6 finding: pre-promotion exit 0 (WARNING filtered by floor); post-promotion exit 1 (ERROR passes floor).
- `--max-warnings` unset with R6 finding: pre-promotion exit 0 (WARNING; not counted); post-promotion exit 1 (`has_error=True`). **SILENT CI-PASS REGRESSION RISK** — documented in CHANGELOG migration table.

*Integration:*
- Migration recipe paths 2 + 3 work end-to-end:
  - Demote: pyproject `[severities] "options/deprecated-field-must-have-replacement-comment" = "warning"` → R6 finding fires at WARNING (pre-promotion behavior restored).
  - Disable via R9b `"off"`: pyproject `[severities] "options/deprecated-field-must-have-replacement-comment" = "off"` → rule does not load; zero R6 findings.
  - Disable via R9b list: pyproject `disabled_rules = ["options/deprecated-field-must-have-replacement-comment"]` → same as above.
  - Disable family via list (all 5 rule_ids): pyproject `disabled_rules = [<all 5 R6 rule_ids>]` → no R6 findings of any ElementKind.
- (No trip-wire deletion verification — KD-4 explicitly skipped the trip-wire pattern; nothing to delete.)

**Verification:**
- Phase 0 empirical hit-rate report attached to commit message (or stored as `docs/solutions/best-practices/d6f-r6-promotion-empirical-validation-2026-05-XX.md` if substantial).
- All 5 R6 rules at `severity=LintSeverity.ERROR` in `_loaded_specs` for `default` profile.
- 0 R6 findings in `recommended` / `proto2-strict` / `essentials` profiles (no scope change to those profiles).
- Exit-code regression tests pass for all 3 `--max-warnings` postures.
- All 4 migration recipe paths verified end-to-end against fixtures.
- All existing 2171 tests pass + new U1 tests (estimated +10-15 tests).
- `ruff check` + `mypy --strict` clean.

---

- [ ] **Unit 3 (U3): Delivery boundary (0.7.0)**

**Goal:** Land the 0.7.0 release: version bump, CHANGELOG fold, README refresh, BUILTIN_PACKS docstring update, presence ratchets, stale-text sweep, CLI dedup regression coverage. Per [[delivery-boundary-unit-commit-composition-2026-05-14]]'s 7-component checklist.

**Requirements:** R9 (remaining surfaces: README + CHANGELOG + BUILTIN_PACKS docstring), R10, R11, R12, R13, R14, R14b. (`_LINT_JSON_SCHEMA_VERSION` bump moved to U2 per KD-7 — atomic with the Literal additions.)

**Dependencies:** Unit 1 (U2) committed AND Unit 2 (U1) committed. U3 packages both into a coherent 0.7.0 release.

**Files:**
- Modify:
  - `pyproject.toml` — `version = "0.6.0"` → `version = "0.7.0"` (R10; package version only — schema version was already bumped in U2 per KD-7)
  - `CHANGELOG.md` — add `### D6f — R6 promotion to ERROR + R9b per-rule disable (0.7.0)` section per [[builtin-packs-expansion-changelog-migration-recipe-structure-2026-05-18]] 5-sub-section template (Added — R9b; Changed — R6 promotion + behavior delta; Pre-upgrade migration recipe; Test coverage; Deferred to D6g+). Use the ACTUAL R6 family rule_ids (long forms verified in Context & Research), not the brainstorm's shortened pedagogical placeholders.
  - `CHANGELOG-DRAFT.md` — reset to D7+ staging (mirror D6e U4 pattern at line 1)
  - `README.md` — profile table `default` row description ("5 warning-severity option-aware rules" → "5 error-severity rules (promoted from WARNING in 0.7.0 D6f per D6e KD-1)"); new `### Upgrade notes (0.6.x → 0.7.0)` section with exit-code impact table; new `### Disabling and re-enabling rules` subsection per R9 (3 disable mechanisms + 1 enable composition pattern, explicitly labeled)
  - `src/protokit/schema/lint/rules/__init__.py` — extend BUILTIN_PACKS docstring with R9b mechanism documentation (preserves the KD-9 upgrade-safety communication contract from the D3 plan, codified in this module's docstring). Numerator unchanged (26 of 26 buf v1.69.0 BASIC rules — D6f doesn't add new rules). **This docstring change moves from U2 to U3** per scope-guardian F2 so it lands atomically with its presence ratchet pin (see Test list below).
  - `TODOS.md` — apply strikethrough + `**LANDED in D6f (0.7.0)**` annotation to the R9b entry at lines 236-247 (in-place markup, NOT deletion — preserves audit trail; mirrors the D6e PACKAGE_NO_IMPORT_CYCLE strikethrough pattern at lines 224-228 of the current TODOS.md)
- Test:
  - `tests/test_changelog_delivery_presence_ratchet.py` — `DELIVERY_RATCHETS` tuple gains `DeliveryRatchetSpec(delivery="D6f", version="0.7.0")`
  - `tests/schema/lint/test_builtin_packs.py` — `ratchet_substrings` extended with a substring pinning R9b's documentation in BUILTIN_PACKS docstring per [[presence-ratchet-pin-canonical-not-local-form-2026-05-23]] (load-bearing phrase from canonical README/CHANGELOG form, NOT docstring truncation)
  - `tests/test_uxd_philosophy_principle_presence_ratchet.py` — verify the POSITIONING_STATEMENT ratchets still pass (no changes expected; documenting the verification)
  - `tests/schema/lint/test_cli_rule_pack_dedup.py` — add a NEW test class `TestR9bCliInteractionRegression` (sibling to `TestRulePackDedupAcrossBuiltinPacks`) per R14b 5 cases (`--disable-rule` filters from BUILTIN_PACKS; `--enable-rule` adds without duplication; cross-pack-and-disable-rule interaction; idempotent repeated `--disable-rule`; multi-kind custom prefix expansion). Separate class avoids the test-design smell of mixing `TestRulePackDedupAcrossBuiltinPacks`'s parametrized-over-BUILTIN_PACKS conceptual scope with R9b-specific non-parametrized regression cases (per adversarial F8). When R14b tests fail, the class name signals R9b-specific issue, not `--rule-pack` dedup.
  - (Schema version assertion audit was performed in U2 alongside the bump per KD-7; no remaining `"0.5"` literals in tests/ at U3 ship.)
- Create:
  - `tests/schema/lint/cli/cli_fixtures/d6f_migration_recipe/` — fixtures for the CHANGELOG migration recipe TOML snippets per [[changelog-readme-snippet-fixture-byte-equivalence-2026-05-21]] (4 single-entry fixtures + 1 5-rule family-list fixture)

**Approach:**

1. **Version bump first** (`pyproject.toml`): single-line change.
2. **Schema version bump** (DONE in U2 per KD-7 — verify here only): confirm `_LINT_JSON_SCHEMA_VERSION == "0.6"` and the bump-trigger docstring at `_builtin_lint.py` was updated with D6f as the next worked example. NO U3 modification to `_builtin_lint.py` — the bump landed atomically with the model.py Literal additions in U2.
3. **CHANGELOG fold**: 5 subsections per the standard template. The 5 subsections:
   - `#### Added — R9b per-rule disable (full surface)`
   - `#### Changed — R6 promotion (WARNING → ERROR in default profile)`
   - `#### Pre-upgrade migration recipe` (4 paths; explicit 5-rule family-list form per KD-4)
   - `#### Test coverage` (R8 13-case fixture, R8b/R8c warnings, CLI integration, CLI dedup regression)
   - `#### Deferred to D6g+` (carry forward from brainstorm scope-boundaries)
4. **README refresh**:
   - Profile table description update for `default` row.
   - New `### Upgrade notes (0.6.x → 0.7.0)` section with exit-code impact table (verified against `cli.py:1210-1222` + `engine.py:1458-1462` per the D6e U4 ce:review M2 discipline; byte-identical across README and CHANGELOG).
   - New `### Disabling and re-enabling rules` subsection between profile table and migration-recipe paragraph. Structure mirrors cross-polarity (disable mechanisms / enable mechanisms / composition pattern). Per R9 / U2 design.
5. **BUILTIN_PACKS docstring extension**: add R9b mechanism documentation as a new section. Preserves KD-9 communication contract. Per [[presence-ratchet-pin-canonical-not-local-form-2026-05-23]]: pin the load-bearing phrase from the canonical README/CHANGELOG form, not docstring truncation.
6. **Presence ratchet additions**: `DeliveryRatchetSpec(delivery="D6f", version="0.7.0")` + new substring pin for R9b. Substring pinned should be the canonical form documented in README (e.g., `"--disable-rule"` or `"disabled_rules"` or `"per-rule disable"` — pick the load-bearing phrase). Run the canonical-form check before settling.
7. **Stale-text sweep** per R14: two-pass per updated 2026-05-23 recipe. Pass 1 verb-pattern across `src/ tests/ docs/ README.md CHANGELOG.md`; Pass 2 bare delivery-label pattern `D[0-9][a-z]+`. Triage hits per rubric (fast-exit: hits in `docs/plans/` or `docs/brainstorms/` with past-tense verbs are frozen artifacts; skip). Specifically apply the strikethrough + LANDED annotation to the TODOS.md R9b entry at lines 236-247 (in-place markup; preserves audit trail per the D6e PACKAGE_NO_IMPORT_CYCLE pattern visible at TODOS.md:224-228).
8. **CLI dedup regression cases** (R14b): add 5 new test methods to `TestRulePackDedupAcrossBuiltinPacks`. Each method targets one R14b case.
9. **Schema_version test sites audit**: `grep -rn '"0.5"' tests/` → review each hit; update literal `"0.5"` schema_version assertions to `"0.6"`. Some hits may be historical (D6e CHANGELOG, prior plan docs) — leave those per [[stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12]] triage rubric.
10. **Migration recipe TOML fixtures** (per [[changelog-readme-snippet-fixture-byte-equivalence-2026-05-21]]): create `cli_fixtures/d6f_migration_recipe/` with one fixture per migration recipe snippet. Parse each through `_coerce_severities` / `_coerce_disabled_rules` to verify byte-equivalence with the published snippets.

**Patterns to follow:**
- D6e U4 boundary commit at `6dd35ca` — same 7-component shape; same heading depth (`####` for subsections inside `### D6f`); same TODOS cleanup pattern
- D6e R4b exit-code impact table at CHANGELOG.md (D6e section) — mirror for the inverse-direction R6 promotion
- D6e U4 ce:compound `[[presence-ratchet-pin-canonical-not-local-form-2026-05-23]]` discipline for the new R9b ratchet substring
- D6e U4 `DELIVERY_RATCHETS` append-only entry pattern at `tests/test_changelog_delivery_presence_ratchet.py:76`

**Test scenarios:**

*Happy path:*
- pyproject `version = "0.7.0"` (parsed correctly by build tooling).
- `_LINT_JSON_SCHEMA_VERSION == "0.6"` at runtime (via `protokit lint --format=json` on a clean fixture; assert in test).
- CHANGELOG renders without markdown errors; D6f section heading at `### D6f — R6 promotion to ERROR + R9b per-rule disable (0.7.0)` (regex pattern matches `tests/test_changelog_delivery_presence_ratchet.py`).
- README profile table shows `default | 33 | ...5 error-severity rules...` after the description update.
- BUILTIN_PACKS docstring contains R9b documentation; ratchet substring pin verified present.

*Edge cases:*
- `DELIVERY_RATCHETS` ratchet for D6f passes after CHANGELOG fold (line-anchored heading regex match).
- Presence ratchet substring for R9b matches the canonical README form (NOT just the docstring's local form).
- TODOS.md R9b entry strikethrough rendering correct.

*Integration:*
- All 5 migration recipe TOML fixtures parse cleanly through `_coerce_*` helpers (byte-equivalence verified).
- CLI dedup regression test class has 5 new methods + still passes the parametrized `BUILTIN_PACKS` matrix (R9b doesn't add a new pack — existing parametrize is unchanged).
- Full test suite passes: 2171 (baseline) + ~25-30 new tests (U2 R9b coverage + U1 R6 promotion verification + U3 R14b dedup regression + migration recipe fixtures) = ~2200 total.
- `ruff check` + `mypy --strict` clean.

**Verification:**
- 7-component delivery-boundary checklist complete per [[delivery-boundary-unit-commit-composition-2026-05-14]]: (1) pyproject version bump ✓, (2) KD-9/policy docstring amendment ✓, (3) CHANGELOG section ✓, (4) README refresh ✓, (5) TODOS.md update ✓, (6) Presence-ratchet tests ✓, (7) Stale-text sweep ✓. Optional 8th component (Corrected subsection) not applicable to D6f.
- `_LINT_JSON_SCHEMA_VERSION` bumped to `"0.6"`; schema-bump test passes.
- All migration recipe fixtures parse cleanly.
- All 5 R14b CLI dedup regression test methods pass.
- Full test suite green; `ruff` + `mypy --strict` clean.
- The R9b TODOS entry has the strikethrough + LANDED annotation applied in-place (NOT deleted; audit trail preserved per the D6e pattern).
- Post-ship monitoring booked per KD-8 (4-6 week window starting at 0.7.0 release; ≥2 outreach targets recorded; PyPI download stats baseline captured).

## System-Wide Impact

- **Interaction graph:** R9b touches the config-resolution layer (`_config.py`) and the engine setup (`engine.py` rule-loading). Engine hot path (`_emit`, profile composition, severity filtering) is unchanged — R9b filtering happens BEFORE the hot path runs. CLI flag additions touch `cli.py`'s Click option declarations.
- **Error propagation:** New `LintRuntimeWarning(category="contradictory_disable_config")` and `LintRuntimeWarning(category="unknown_rule_id")` flow through the existing runtime-warning pipeline. They surface in `--format=json runtime_warnings`, SARIF `properties.runtime_warnings`, and `--format=human` summarized stderr count. No new error-class.
- **State lifecycle risks:** R9b is stateless within an engine run; effective rule set is computed once at config resolution. No partial-write / cache / cleanup risks.
- **API surface parity:** Three interfaces expose lint: CLI (`--disable-rule` / `--enable-rule` added), pyproject (`disabled_rules` / `enabled_rules` added), programmatic `from_dict` (`cli_overrides` keys added). All three must accept R9b inputs uniformly per [[symmetric-coercion-strictness-multi-source-field-resolver-2026-05-12]].
- **Integration coverage:** R9b's effective load_set computation crosses 3 layers (Click → coercion helpers → `from_dict` → engine setup → `_loaded_specs`). Unit tests alone won't prove the full chain; the parametrized R8 13-case test + the CLI integration tests + the migration recipe fixture tests are the load-bearing integration coverage.
- **Unchanged invariants:**
  - `LintSeverity` enum remains 3 members (ERROR, WARNING, INFO). `OFF` is NOT a member per KD-1.
  - `SEVERITY_RANK` dict remains 3 keys. No `OFF` key per KD-1.
  - Engine hot path (`_emit`, profile compose, severity filter) untouched.
  - SARIF formatter `assert_never` path remains unreachable.
  - Multi-kind custom rule_id mangling at `_custom_rules.py:430-476` unchanged (R9b reads from `synthetic_rule_ids()` for prefix expansion; doesn't modify the mangling).
  - All existing 2171 tests pass with R9b additive (zero behavior change for users not using R9b).
  - Buf-parity numerator stays at 26 of 26 buf v1.69.0 BASIC rules (D6f adds no new rules; only severity changes + new disable surface).

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| R6 promotion blast radius higher than KD-1 framing assumes (per product-lens convergence in document-review) | Phase 0 empirical hit-rate validation in U1 (KD-8); hard gate at >10% noisy rate; revise scope if exceeded. Post-ship monitoring window booked per [[post-ship-adoption-monitoring-pre-1.0-breaking-default-change-2026-05-19]]. |
| R8 cross-tier precedence surprises users (CLI `--enable-rule` doesn't override pyproject `disabled_rules`) | R8b warning fires on the contradiction with actionable message naming `--no-config` as the escape hatch. Documented prominently in CHANGELOG migration recipe + README "Disabling and re-enabling rules" subsection. |
| Multi-kind prefix expansion breaks per-kind-only disable expectation | KD-2 documents both modes (bare form = all kinds; mangled form = per-kind). Test coverage verifies both. CHANGELOG explicitly notes the dual semantics. |
| `LintSeverity.OFF` accidentally added to enum during implementation (would cascade through formatters, SARIF assert_never, SEVERITY_RANK) | KD-1 explicitly prohibits; sentinel pattern documented + tested. Code review checks for `LintSeverity.OFF` additions specifically. |
| Sentinel propagation gap: `disabled_via_off_severity` set in `from_dict` but never consulted in `cli.py` profile composition (silent no-op) | Per KD-1, U2 merges `disabled_via_off_severity` into the unified `ResolvedLintConfig.disabled_rules: frozenset[str]` field BEFORE returning. `cli.py` MUST add the explicit `effective_rule_ids = composed_profile.rule_ids - resolved.disabled_rules` step. The end-to-end test `test_cli_r9b_profile_augmentation.py` is the load-bearing regression guard. |
| Migration recipe TOML snippets drift from actual rule_ids (brainstorm used shortened forms) | U1 + U3 use the ACTUAL rule_ids verified at `deprecated_replacement.py`; per [[changelog-readme-snippet-fixture-byte-equivalence-2026-05-21]] every TOML snippet maps to a fixture that parses cleanly. |
| Schema-version test assertions miss the `"0.5"` → `"0.6"` bump (silent drift) | U3 explicit grep audit step + new schema-bump presence ratchet (mirroring D6d pattern). |
| Presence ratchet pinned to docstring's truncated R9b mention rather than canonical README form (drift vulnerability per [[presence-ratchet-pin-canonical-not-local-form-2026-05-23]]) | Explicitly cited in U3 R13; reviewer check: substring pin must come from README/CHANGELOG canonical form, not docstring. |
| R6 actual rule_id names longer than expected (5 rule_ids ~75 chars each in migration recipe) creates verbose CHANGELOG | Acceptable; full names are load-bearing for user copy-paste. README MAY summarize with "see CHANGELOG for the full list" per R2. |
| `--no-config` doesn't exist or doesn't have expected semantics (escape-hatch documented in R9 but unverified) | U2 implementation-time verification (Deferred to Implementation section above). If unverified, fall back to "remove the conflicting entry from pyproject" guidance in R9. |

## Documentation / Operational Notes

- **Per-delivery workflow:** standard `/ce:brainstorm → /ce:plan → per-unit /ce:work → per-unit /ce:review → ce:review follow-ups → /ce:compound` pipeline applies to each of U2, U1, U3.
- **Commit shape:** default split per [[delivery-boundary-bundled-commit-feat-plus-review-followups-2026-05-21]] (feat + fix). Bundle only if work is uncommitted at ce:review time AND it's a delivery boundary.
- **Stash-pop coordination:** U2 → U1 reverse-order pipeline uses the stash-pop discipline per [[multi-unit-ce-review-stash-pop-coordination-2026-05-21]]. When U2 R9b is committed and U1 R6 promotion work is uncommitted WIP, stash U1 WIP before running `/ce:review` on U2.
- **NEW learning candidates for ce:compound boundaries** (surfaced by learnings-researcher):
  - U2 boundary: "Sentinel pattern for `"off"` interception before `LintSeverity` construction" (institutional pattern for avoiding enum widening)
  - U2 boundary: "Multi-kind custom rule prefix expansion at config-resolution time, NOT engine-dispatch time" (engine hot-path discipline)
  - U2 boundary: "Click `multiple=True` empty-tuple as natural None-sentinel for CLI > pyproject merge (no ParameterSource needed)"
  - U2 boundary: "Flat-config-only project convention — layered pyproject inheritance is explicit non-goal" (architectural decision documentation)
  - U1 boundary: "Severity promotion from WARNING to ERROR — Phase 0 empirical validation discipline + post-ship monitoring contract" (KD-1 demonstration backstop)
  - U1 boundary: "R6/R9b naming ambiguity resolution — disambiguation convention in plan/brainstorm docs"
  - U3 boundary: drift refresh on [[wire-format-schema-version-bump-contract-and-absence-semantic-2026-05-13]] (worked example progression `"0.3"` → `"0.5"` → `"0.6"`)
  - U3 boundary: cross-ref extension on [[semantic-category-conflation-accepted-tradeoff-literal-widening-2026-05-13]] noting D6f as the 4th exercise of the pattern (with a NEW twist: sentinel-at-coercion-layer instead of conflation)

## Sources & References

- **Origin document:** `docs/brainstorms/2026-05-23-d6f-r6-promotion-and-r9b-per-rule-disable-requirements.md` (last revised 2026-05-24 after 5-reviewer document-review pass)
- **Related code paths verified in Phase 0** (see Context & Research table above)
- **Related institutional learnings:** 20+ entries cited above (10 carried from brainstorm + 10 NEW from learnings-researcher Phase 1)
- **D6e closing-arc delivery** (immediate predecessor): `docs/brainstorms/2026-05-22-d6e-buf-basic-closure-philosophy-revision-requirements.md` + `docs/plans/2026-05-22-001-feat-d6e-buf-basic-closure-and-philosophy-revision-plan.md`
- **TODOS.md D6f+ backlog**: `TODOS.md:221-287` (R9b entry at `:236-247` becomes obsolete in U3 R14)
