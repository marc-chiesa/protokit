---
date: 2026-05-23
last_revised: 2026-05-24
status: ACTIVE
topic: protokit-lint-delivery-6f-r6-promotion-and-r9b-per-rule-disable
document_review_artifacts:
  - "(initial review 2026-05-23) 5 reviewers — coherence + feasibility + product-lens + scope-guardian + adversarial. 5-reviewer convergence on R9b scope. User chose: keep full surface, address each convergence explicitly. This revision (2026-05-24) lands the resolutions: R6 naming disambiguation + KD-1 disambiguation in new Terminology preamble; R5 expanded with 3 concrete enabled_rules demand cases; R6 expanded with 3 justifications for CLI flags beyond migration; R7 multi-kind expansion semantics specified; R8 cross-tier precedence resolved (polarity-first); R8b warnings requirement added; R8c lenient validation resolved; R9 'Disabling and re-enabling' relabel; R14b CLI dedup test added; KD-3 buf-parity hedge gets explicit 12-week trigger; KD-7 schema-bump resolved affirmatively; OQ-1+OQ-2+OQ-4 closed in-brainstorm; OQ-3 principle resolved (plan validates); migration recipe expanded with 5-rule R6 family-list form."
---

# Protokit Lint Delivery 6f — R6 Promotion to ERROR + R9b Per-Rule Disable (0.7.0)

## Overview

D6f is a **KD-1 demonstration delivery**: the first post-closing-arc release that exercises the inverted UX philosophy (`protokit-UX overrides buf-parity`) on a *user-facing severity decision* rather than a rule-coverage decision. Two paired changes:

1. **R6 promotion to ERROR** (the 5-rule `options/deprecated_replacement` family shipped at WARNING in D6b U3a to bound the leading-comment-regex heuristic's blast radius). Promoting to ERROR makes deprecation-without-replacement a CI-blocking signal in the `default` profile. Without a safety net, this would create unaddressable upgrade pain for users who have legitimately-deprecated symbols they can't immediately re-annotate. R9b is the safety net.

2. **R9b first-class per-rule disable** (full surface). Adds `"off"` to the accepted `[severities]` value set, `disabled_rules` / `enabled_rules` pyproject lists, and `--disable-rule` / `--enable-rule` CLI flags. Equivalent to buf's `--except-rule` / `--also-rule` in capability but uses protokit-native names per KD-1.

The narrative is a coherent UX-first story: *"protokit's defaults reflect Python-protobuf-developer ergonomics, not buf's defaults — which means we ship some rules at stricter severities than buf does, AND we give you a first-class per-rule disable to opt out when fixing the schema isn't immediate."* R6 is the worked example proving the R9b mechanism carries weight under real upgrade pressure.

Plus the standard delivery-boundary unit (U3): pyproject `0.6.0` → `0.7.0`, CHANGELOG fold, README refresh, BUILTIN_PACKS docstring update (R9b mechanism documentation; rule counts unchanged), CLI dedup regression coverage (no new packs, but `--disable-rule` / `--enable-rule` interaction with existing dedup needs a per-flag regression test — bound to Requirement R14b below).

## Terminology (Read Before Requirements)

This document uses several overloaded identifiers. To prevent reader confusion:

- **"R6 family" / "R6 deprecated_replacement family"** — the 5-rule `options/deprecated_replacement` rule pack from D6b U3a. NEVER refers to D6f's Requirement #6.
- **"Req-R<n>"** — Requirements R1-R14 below. When the surrounding sentence could plausibly read either way (rule family OR requirement number), the explicit `Req-R<n>` prefix is used. Sections that use bare `R<n>` are referring to requirement numbers because rule families have always been carried in the format `R<digit>` (R4, R6, R7, R8, R8b, R9, R9b) — D6f introduces no new rule families.
- **"D6e KD-1"** — the inverted-UX-philosophy principle established in the D6e brainstorm: *"protokit-UX overrides buf-parity when they conflict."* This is the principle D6f *demonstrates*.
- **"D6f KD-1"** (or the bare "KD-1" within the Key Decisions section) — *this* document's Key Decision #1, which is the decision to ship R6-promotion-as-KD-1-demonstration. When this document refers to KD-1 OUTSIDE the Key Decisions section, it always means D6e's principle (the thing being demonstrated). When INSIDE the Key Decisions section, KD-1 means this doc's decision.
- **"KD-9 upgrade-safety communication contract"** — from the D3 plan; codified in the `BUILTIN_PACKS` module docstring at `src/protokit/schema/lint/rules/__init__.py`. NOT one of D6f's KDs (this doc defines KD-1 through KD-8 only).
- **"R9b"** — the per-rule disable backlog item name, used as a noun (the feature being shipped). Not a requirement number; not a rule family.

## Problem Frame

**R6 promotion has been gated on real-world evidence since D6b ship (2026-05-17), and the PD-11 forcing-function defaults (N=3 reports / M=8 weeks) have not fired.** Per the D6e PD-11 community-size caveat: at a small user community, N=3 may never fire even when a real regression hits a meaningful fraction of users. The choice is to wait indefinitely OR ship the promotion as a *deliberate KD-1 demonstration* — protokit's defaults reflect what Python-protobuf-developer ergonomics demands, not what evidence reaches us through a small user community.

**R9b has been deferred since D6a per the brainstorms, gated on "real-demand evidence to design the 4 collision-shape precedence semantics against."** R6 promotion is exactly that evidence — promoting a 5-rule family to ERROR creates a concrete worked example where the precedence questions have to be answered, and the migration recipe has to be self-contained. Shipping R9b alongside R6 promotion is the cleanest way to design the precedence semantics against a real upgrade scenario rather than a hypothetical one.

**The current `"off"` workaround is a UX defect.** Per D6e CHANGELOG, users wanting to suppress a finding without removing the rule entry must demote to `"info"` AND use `--min-severity warning` to drop it from the surface. This is documented as the recommended path but it's awkward: a 2-step suppression mechanism that requires understanding the severity floor interaction. R9b makes `"off"` a first-class value AND adds the list-shaped `disabled_rules` for bulk disable.

## Pressure Test (Phase 1.2)

- **Real problem?** Yes. R6 promotion is gated only on community size, not on principled doubt — the heuristic is well-understood, the blast radius is bounded by the `default`-only profile placement, and R9b makes the migration painless. R9b's UX-defect framing is independently real (the 2-step suppression workaround is documented as awkward in D6e).
- **Do-nothing cost?** R6 stays at WARNING indefinitely, weakening protokit's KD-1 commitment to Python-protobuf-developer ergonomics (deprecation-without-replacement should be CI-blocking by default per the ergonomics judgment). R9b stays deferred indefinitely; future severity promotions or audit-pass demotions face the same workaround friction; users coming from buf with `--except-rule` muscle memory hit a UX cliff.
- **Higher-upside framing?** Considered: (a) ship R9b standalone first, R6 promotion in a later 0.7.x patch when R9b has been live for evidence — rejected because R9b without a concrete worked example doesn't earn its precedence-design surface. (b) ship R6 promotion without R9b, demote-to-warning as the only migration path — rejected because it creates a per-rule disable demand spike that R9b solves perfectly, and shipping R6 promotion alone is principle-without-substance for KD-1.
- **Single highest-leverage move?** D6f umbrella with R6 promotion + R9b full surface in one release. The pairing is the leverage: each makes the other safer/more useful.
- **Opportunity cost acknowledged.** D6f deferred items: SHA-pinning test for D6e U3 buf snapshots; CLI `--help` epilog `--min-severity` filter visibility note; U3 ce:review residual P2/P3 unit tests; `options/field-behavior-consistent` IDENTIFIER-based contradictions; `strict` profile rule enumeration; MCP/IDE engine-recycle rebuild contract. All are explicitly D6g+. The clean-narrative scope (just R6 + R9b) is the judgment that the UX-first story is more valuable to users than the hardening backlog cleanup, AND that the hardening items don't compound with R6+R9b.
- **Durable capability in 6-12 months?** R9b is foundational — future severity changes (R6 audit-pass demotions, retroactive R4-style adjustments, profile composition refinements) all flow through R9b as the user-facing escape hatch. Once R9b ships, every subsequent rule severity decision can be made KD-1-aligned because users have a first-class disable mechanism.

## Requirements

### U1: R6 Promotion to ERROR

(Requirements R1, R2, R3.)

#### R1 — Promote `options/deprecated_replacement` family from WARNING to ERROR (U1)

All 5 rules in the `options/deprecated_replacement` pack (one per `*Options.deprecated` ElementKind: FIELD, ENUM_VALUE, METHOD, MESSAGE, ENUM) flip from `severity=WARNING` to `severity=ERROR` in the `default` profile.

- `recommended` profile unaffected (R6 has never shipped in `recommended` per the D6b U3a buf-parity scoping — R6 has no buf BASIC analogue).
- `proto2-strict` profile unaffected.
- `essentials` profile unaffected.

The leading-comment-regex heuristic (which determines whether a deprecation comment provides a replacement reference) is not modified — promotion is purely a severity flip, not a behavior change.

#### R2 — Migration recipe (full template per [[migration-recipe-severity-aware-template-reuse-2026-05-21]])

Publish all four standard migration paths in the D6f CHANGELOG section + README upgrade notes. **The R6 family contains 5 distinct rule_ids** (one per `*Options.deprecated` ElementKind: FIELD, ENUM_VALUE, METHOD, MESSAGE, ENUM). Users hit by multiple ElementKinds need to know all 5 rule_ids OR use the list form to suppress the family at once — KD-4 deliberately rejected pack-level disable so the migration recipe MUST enumerate the family explicitly:

1. **Fix the schema** (preferred): add a `replaces=`-style annotation OR remove `deprecated=true` from the symbol.
2. **Demote per-rule via legacy `[severities]`** (back to the pre-0.7.0 WARNING severity; all 5 rule_ids needed if multiple ElementKinds are affected):
   ```toml
   [tool.protokit.lint.severities]
   "options/deprecated-replacement/field" = "warning"
   "options/deprecated-replacement/enum_value" = "warning"
   "options/deprecated-replacement/method" = "warning"
   "options/deprecated-replacement/message" = "warning"
   "options/deprecated-replacement/enum" = "warning"
   ```
3. **Disable per-rule via R9b's new `"off"` sentinel** (single-rule form OR family list form):

   Single-rule form (one ElementKind affected):
   ```toml
   [tool.protokit.lint.severities]
   "options/deprecated-replacement/field" = "off"
   ```
   Family list form (multiple ElementKinds affected — preferred for bulk suppression of the whole R6 family):
   ```toml
   [tool.protokit.lint]
   disabled_rules = [
       "options/deprecated-replacement/field",
       "options/deprecated-replacement/enum_value",
       "options/deprecated-replacement/method",
       "options/deprecated-replacement/message",
       "options/deprecated-replacement/enum",
   ]
   ```
4. **Pin to 0.6.0 indefinitely**: `pip install protokit==0.6.0`

The CHANGELOG migration recipe MUST include the family-list-form example; the README upgrade notes MAY summarize ("disable all 5 R6 rules at once via `disabled_rules`; see CHANGELOG for the full list"). Per [[changelog-readme-snippet-fixture-byte-equivalence-2026-05-21]], the 5-entry `disabled_rules` form must parse cleanly through `_coerce_disabled_rules` (new helper per Requirement Req-R5).

Per the D6e migration-recipe-severity-aware-template-reuse discipline, the recipe MUST be verified against fixtures before commit (the snippets must parse cleanly through `_coerce_severities` / `_coerce_profile` without raising `error[lint-pyproject-config-invalid]`).

#### R3 — Upgrade-impact table by `--max-warnings` posture (U1)

Mirror the D6e R4b exit-code impact table format for the inverse direction (promotion vs demotion):

| Posture | Pre-0.7.0 | Post-0.7.0 |
|---|---|---|
| `--max-warnings` unset | `default` user with R6 finding: exit 0 (WARNING; not counted) | `default` user with R6 finding: exit 1 (ERROR; CI-blocking) — **silent CI-pass → CI-red on upgrade** |
| `--max-warnings 0` | exit 1 (counted as warning) | exit 1 (counted as error) |
| `--min-severity error` | exit 0 (WARNING filtered) | exit 1 (ERROR passes floor) |

Document in CHANGELOG D6f section AND README upgrade notes. Both surfaces. Per the D6e U4 ce:review M2 finding, pin the canonical form in BOTH README and CHANGELOG (byte-identical) and verify against the actual engine exit-code computation at `src/protokit/schema/lint/cli.py:1210-1222` (the `has_error` check + `max_warnings` branch — short-circuit logic where `has_error=True` exits before reaching the warning-count gate) and the min-severity filtering at `src/protokit/schema/lint/engine.py:1458-1462`. Both code locations are load-bearing for the table's accuracy.

### U2: R9b Per-Rule Disable — Full Surface

(Requirements R4, R5, R6, R7, R8, R9.)

#### R4 — `"off"` as a first-class severity value (U2)

Add `"off"` to the accepted `[tool.protokit.lint.severities]` value set. Behavior: rule does not load (zero findings, zero runtime overhead).

- `LintSeverity` enum (or sibling sentinel) extended to accept `"off"`.
- `_coerce_severities` accepts `"off"` without raising `error[lint-pyproject-config-invalid]`.
- The TODOS R9b backlog entry at lines 236–247 ("`"off"` is NOT currently a valid severity value") becomes obsolete; remove + add a positive R9b CHANGELOG reference.

#### R5 — `disabled_rules` / `enabled_rules` pyproject lists (U2)

Add two pyproject keys under `[tool.protokit.lint]`:

```toml
[tool.protokit.lint]
disabled_rules = ["naming/snake-case-fields", "imports/no-public"]
enabled_rules  = ["package/no-import-cycle"]
```

- `disabled_rules`: list of rule_ids that should NOT load regardless of profile membership.
- `enabled_rules`: list of rule_ids that SHOULD load even if profile membership doesn't include them. Concrete demand cases (post-document-review):
  1. **Per-rule opt-in to `proto2-strict`** without committing the whole profile. A proto2-shop with a few proto3 files in a vendor directory wants `field/not-required` enforcement on the proto2 modules but doesn't want to set `profile = ["default", "proto2-strict"]` for the whole project (which would also activate future `proto2-strict` rules they may not be ready for). `enabled_rules = ["field/not-required"]` pins the single rule without committing to the broader opt-in.
  2. **Selective adoption of a deferred rule before delivery promotion**. If protokit ships a rule in `proto2-strict` at D6f and the project wants to verify it ahead of D6g promotion to `default`, `enabled_rules` allows early adoption with explicit acknowledgment of pre-release status.
  3. **Layered config restoration**. A team inherits a base `pyproject.toml` from a parent repo with `disabled_rules` for org policy; per Req-R8 below the precedence resolution (cross-tier disable-wins) means `enabled_rules` does NOT silently override the parent — but `enabled_rules` documents the intent and produces a `LintRuntimeWarning` (per Req-R8b) so the team can see the contradiction explicitly.

Both lists accept built-in rule_ids AND `custom/<suffix>` synthetic rules from `[[tool.protokit.lint.custom_annotation_rules]]` per Requirement R7 below (uniform treatment).

#### R6 — `--disable-rule` / `--enable-rule` CLI flags (U2)

Add two CLI flags accepting one or more rule_ids:

```bash
protokit lint --disable-rule naming/snake-case-fields --disable-rule imports/no-public protos/**/*.proto
protokit lint --enable-rule package/no-import-cycle --no-builtin-rules protos/**/*.proto
```

- Repeatable (Click `multiple=True`).
- CLI > pyproject precedence at SAME polarity (established convention; `--disable-rule R` overrides pyproject `disabled_rules` removal of R; `--enable-rule R` overrides pyproject `enabled_rules` removal of R).
- **Cross-polarity precedence resolution (per Req-R8): disable-wins overrules CLI-wins.** A CLI `--enable-rule R` does NOT override pyproject `disabled_rules = ["R"]`. This is the explicit resolution of OQ-1's cross-tier collision — see Req-R8.
- Validation: rule_id must match the canonical form (`pack/rule-suffix` or `custom/<suffix>`); behavior on unknown rule_ids is governed by Req-R8c (lenient default + `LintRuntimeWarning`).

**Justification for CLI flags as in-scope D6f surface** (beyond pyproject-only migration):

1. **Ad-hoc invocation parity with buf**. Users running protokit in scripted contexts (CI matrix jobs, one-off audits, debugging sessions) expect to vary which rules apply per invocation without touching shared `pyproject.toml`. Buf supports `--except-rule` / `--also-rule` for exactly this reason; shipping `disabled_rules` without CLI parallels makes the protokit-native naming choice (KD-3) appear deficient by contrast.
2. **Audit-CI vs. regular-CI separation**. Common pattern: regular CI runs the full default profile; a periodic audit CI run wants `--enable-rule` to surface deferred rules without committing them to `pyproject.toml`. Pyproject-only R9b cannot express "this rule runs in audit-CI but not regular-CI" without committing both jobs to the same config file.
3. **Reproducibility of one-off investigations**. A developer investigating "why does my CI fail?" can run `protokit lint --disable-rule <suspect> ...` to isolate which rule is firing without editing pyproject and risking accidentally committing the change.

These use cases are distinct from R6 migration. The CLI flags do not duplicate pyproject capability; they extend it to ad-hoc and per-invocation contexts.

#### R7 — Uniform treatment for `custom/<suffix>` synthetic rules (U2)

R9b's disable/enable surface applies uniformly to built-in and synthetic rules. Per D6d's "synthetic rules are first-class" principle:

```toml
[[tool.protokit.lint.custom_annotation_rules]]
rule_suffix    = "audit-required"
option         = "example.audit_level"
element_kinds  = ["method"]
allowed_values = ["LOW", "HIGH", "CRITICAL"]
severity       = "error"

[tool.protokit.lint]
disabled_rules = ["custom/audit-required"]  # temporarily suppress without removing the entry
```

Equivalent CLI: `--disable-rule custom/audit-required`. Same precedence rules.

**Multi-kind expansion semantics (post-document-review F3):** custom annotation rules declared with multiple `element_kinds` register multiple rule_ids via the mangling scheme at `src/protokit/schema/lint/_custom_rules.py:440-476`. The first kind registers as `custom/<suffix>`; subsequent kinds register as `custom/<suffix>__<kind>` (e.g., `custom/audit-required__method`, `custom/audit-required__service`). For R9b uniform treatment to hold without per-kind enumeration:

- **`disabled_rules = ["custom/audit-required"]` MUST suppress ALL kinds** of the `audit-required` entry, not just the first-kind closure. The disable lookup MUST consult `synthetic_rule_ids()` and expand the bare `custom/<suffix>` prefix to cover all mangled variants.
- **Per-kind disable still works** via the explicit mangled form: `disabled_rules = ["custom/audit-required__method"]` suppresses only the method-kind closure while leaving the first-kind closure active.
- **CLI flags follow the same expansion**: `--disable-rule custom/audit-required` covers all kinds; `--disable-rule custom/audit-required__method` is per-kind.

This expansion semantics is the planning-time decision required to make R7's "uniform treatment" claim hold for multi-kind custom entries. Without it, the claim is true only for single-kind entries.

#### R8 — Precedence semantics (U2)

R9b introduces 4 disable/enable mechanisms (`[severities] = "off"`, `disabled_rules`, `--disable-rule`, `--enable-rule`) plus the existing `[severities] = "<value>"` severity override. When mechanisms collide, the engine resolves precedence by a single ordered principle:

> **Disable wins. Higher tier wins WITHIN polarity.**

The two-rule application order:

1. **Polarity first**: if ANY mechanism at ANY tier disables a rule, the rule does not load. Disable beats enable categorically — including cross-tier (CLI `--enable-rule R` does NOT override pyproject `disabled_rules = ["R"]`). Severity override `= "off"` is a disable; non-`"off"` severity is neither disable nor enable (it modifies severity of a loaded rule).
2. **Tier second** (only when polarity agrees): if all colliding mechanisms agree on polarity, the higher tier wins. CLI > pyproject. This applies to the case where pyproject `disabled_rules = []` is the absence of a disable and CLI `--disable-rule R` adds one — CLI wins because pyproject has nothing to override.

**Concrete resolution table** (the OQ-1 4-way matrix, resolved):

| Scenario | Outcome | Reasoning |
|---|---|---|
| `disabled_rules = ["R"]` (pyproject) only | R does NOT load | Single disable signal |
| `enabled_rules = ["R"]` (pyproject) only, R not in profile | R loads (additive per KD-5) | Single enable signal |
| `--disable-rule R` (CLI) only | R does NOT load | Single disable signal |
| `--enable-rule R` (CLI) only, R not in profile | R loads (additive per KD-5) | Single enable signal |
| `disabled_rules = ["R"]` AND `enabled_rules = ["R"]` (same pyproject) | R does NOT load | Polarity: disable wins. Req-R8b warns. |
| `--disable-rule R` AND `--enable-rule R` (same CLI invocation) | R does NOT load | Polarity: disable wins. Req-R8b warns. |
| CLI `--enable-rule R` + pyproject `disabled_rules = ["R"]` | R does NOT load | **Polarity FIRST: disable wins across tiers.** This is the explicit OQ-1 resolution; "CLI > pyproject" applies WITHIN polarity, not across. Req-R8b warns. |
| CLI `--disable-rule R` + pyproject `enabled_rules = ["R"]` | R does NOT load | Polarity: disable wins. No warning (CLI extending pyproject is a normal pattern). |
| `disabled_rules = ["R"]` AND `[severities] "R" = "error"` | R does NOT load | Polarity: `disabled_rules` is a disable; severity override is a load modifier; disable wins. Req-R8b warns (severity override is dead weight). |
| `[severities] "R" = "off"` AND `enabled_rules = ["R"]` | R does NOT load | Polarity: `"off"` is a disable; disable wins. Req-R8b warns. |
| `[severities] "R" = "off"` AND `[severities] "R" = "<value>"` | impossible (same key) | TOML rejects duplicate keys at parse time |
| `disabled_rules = ["R"]` AND `[severities] "R" = "off"` | R does NOT load | Both are disables; idempotent; no warning |

**Cross-tier disable-wins rationale**: Layered configs (org-level pyproject committed to source control + project-level CLI invocations in CI scripts) commonly use pyproject for stricter org-wide policy. Letting a CLI flag silently override a pyproject disable would let any CI script bypass org policy without an audit trail. The disable-wins-across-tiers principle protects pyproject as the durable policy surface; the CLI's role is to add restrictions (further disable), not to relax pyproject restrictions (selective enable). Users who genuinely need to override a pyproject disable for a specific run must either edit the pyproject or use `--no-config` to ignore the pyproject entirely.

**`enabled_rules` is additive, not restrictive**: adding R to `enabled_rules` loads R in addition to whatever the profile selects; it does NOT restrict the load set to only the listed rules. For "only R loads" semantics, users combine `--no-builtin-rules` (or `essentials` profile) with `--enable-rule R`.

#### R8b — Contradictory-configuration warnings (U2)

When R9b mechanisms collide in a way where ONE user-supplied directive becomes dead weight (silently overridden), emit a `LintRuntimeWarning(category="contradictory_disable_config")` per collision. Specifically:

- `disabled_rules = ["R"]` AND `enabled_rules = ["R"]` in the same pyproject → warn: "rule R appears in both disabled_rules and enabled_rules; disabled_rules wins (rule will not load). To enable, remove from disabled_rules."
- `--disable-rule R` AND `--enable-rule R` on the same CLI invocation → warn: similar message at CLI layer.
- CLI `--enable-rule R` + pyproject `disabled_rules = ["R"]` (cross-tier) → warn: "CLI --enable-rule for R is overridden by pyproject disabled_rules; rule will not load. Use --no-config to bypass pyproject."
- `disabled_rules = ["R"]` AND `[severities] "R" = "<non-off>"` → warn: "rule R has a [severities] override but is also in disabled_rules; the severity override is dead weight (rule will not load)."
- `[severities] "R" = "off"` AND `enabled_rules = ["R"]` → warn: "rule R is set to severity 'off' AND in enabled_rules; 'off' wins (rule will not load)."

The new `LintRuntimeWarning.category` value `"contradictory_disable_config"` is a closed-`Literal` discriminator addition per [[closed-literal-discriminator-bump-trigger-2026-05-17]] AND therefore triggers `_LINT_JSON_SCHEMA_VERSION` `"0.5"` → `"0.6"` (resolves OQ-4 affirmatively). KD-7 updated below to reflect this.

Symmetric case (NO warning): `disabled_rules = ["R"]` AND `[severities] "R" = "off"` — both are disables, idempotent, no contradiction.

#### R8c — Rule_id validation strictness (U2; resolves OQ-2)

R9b accepts rule_ids from the user via 4 mechanisms (`[severities]` keys, `disabled_rules`, `enabled_rules`, CLI flags). Validation is **lenient with warnings** (rejecting OQ-2's strict and hybrid options):

- **Format validation** (always strict, exit-2): rule_id must match canonical form `[pack]/[rule-suffix]` or `custom/<suffix>`. Whitespace, empty strings, leading slashes, etc. exit-2 with `error[lint-pyproject-config-invalid]:` or sibling CLI-args category.
- **Existence validation** (lenient with warning): if the rule_id is well-formed but doesn't match any loaded rule (typo, deprecated rule_id from older protokit version, custom rule_suffix not yet declared), emit `LintRuntimeWarning(category="unknown_rule_id")` and continue. The disable/enable directive becomes a no-op.

This is also a new `LintRuntimeWarning.category` value, but it shares the `"0.5"` → `"0.6"` schema bump with `"contradictory_disable_config"` from Req-R8b — single bump for D6f. The `"unknown_rule_id"` category enables forward-compat (users can list rule_ids that aren't yet implemented; the warning surfaces the gap without exit-2 disrupting CI) AND surfaces typos as visible warnings rather than silent no-ops.

Per the D6e `--format=human --quiet` interaction concern (adversarial F4): runtime warnings under `--quiet` are summarized to `<N> runtime warnings (use --format=json to inspect)`. Users running R9b config under `--quiet` see the count and can re-run without `--quiet` to inspect. This matches existing protokit conventions; not a new gap introduced by R9b.

#### R9 — Discoverability surfaces (U2)

Document the new R9b surface in:

- **CLI `--help` epilog**: 2-3 line note that `--disable-rule` / `--enable-rule` accept rule_ids and that `[severities] "rule" = "off"` is equivalent to `disabled_rules = ["rule"]`. Per the U4 ce:review AC-4 deferred finding, this is also a natural slot to surface the `--min-severity` filter visibility caveat — fold the AC-4 documentation gap into the R9b help-text rewrite.
- **README "Schema Linting" section**: new "Disabling and re-enabling rules" subsection between the profile table and the migration-recipe paragraph. Three disable forms (`"off"` severity, `disabled_rules` list, `--disable-rule` CLI) PLUS the additive enable composition pattern (`--no-builtin-rules` or `essentials` profile to start from zero, then `enabled_rules` / `--enable-rule` to add specific rules — explicitly labeled as composition, NOT as a disable form). The subsection's structure should mirror the cross-polarity nature of R9b (disable mechanisms vs. enable mechanisms vs. composition pattern), avoiding the "four disable forms" framing that conflates additive enable with disable.
- **CHANGELOG D6f section**: full migration recipe + 1-line callout per mechanism.
- **BUILTIN_PACKS docstring**: brief addition documenting `disabled_rules` / `enabled_rules` as the R9b first-class disable surface; preserve the KD-9 upgrade-safety communication contract (from the D3 plan; codified in the BUILTIN_PACKS module docstring at `src/protokit/schema/lint/rules/__init__.py`) — every behavior-changing mechanism documented in the docstring + protected by presence ratchet.

### U3: Delivery Boundary (0.7.0)

(Requirements R10, R11, R12, R13, R14.)

#### R10 — Version bump

`pyproject.toml` `version = "0.6.0"` → `version = "0.7.0"`.

- Per the [[pre-1.0-version-bump-as-communication-contract-2026-05-14]] discipline, the bump body carries the contract; no ceremonial BREAKING markers.
- R6 promotion is the user-visible behavior change justifying the minor bump. R9b is additive (new public surface; no behavior change to existing surface).

#### R11 — CHANGELOG fold

Add `### D6f — R6 promotion to ERROR + R9b per-rule disable (0.7.0)` section to `CHANGELOG.md`, structured per the D6e U4 pattern (#### subsections per [[builtin-packs-expansion-changelog-migration-recipe-structure-2026-05-18]] template, severity-aware migration recipe per [[migration-recipe-severity-aware-template-reuse-2026-05-21]]). `CHANGELOG-DRAFT.md` resets to D7+ staging.

#### R12 — README refresh

- Profile table `default` row: rule count unchanged at 33 (R6 promotion is a severity change, not a count change). Update the description to drop the "5 warning-severity option-aware rules" phrasing in favor of "5 error-severity rules (promoted from WARNING in 0.7.0 D6f per KD-1)."
- New `### Upgrade notes (0.6.x → 0.7.0)` section.
- New `### Disabling rules` subsection per R9.

#### R13 — Presence ratchets

- `DELIVERY_RATCHETS` tuple gains `DeliveryRatchetSpec(delivery="D6f", version="0.7.0")` at `tests/test_changelog_delivery_presence_ratchet.py`.
- `tests/schema/lint/test_builtin_packs.py` `ratchet_substrings` extended with substring pinning R9b's existence in the BUILTIN_PACKS docstring (e.g., `"R9b per-rule disable"` or similar canonical phrase).
- Per [[presence-ratchet-pin-canonical-not-local-form-2026-05-23]] discipline: pin the load-bearing phrase from the canonical README/CHANGELOG form, not whatever shorter form the docstring carries. If the docstring needs reflow, fix the docstring; don't shorten the ratchet substring.

#### R14 — Stale-text sweep

Apply the two-pass recipe per [[stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12]] (updated 2026-05-23): Pass 1 verb-pattern across `src/ tests/ docs/ README.md CHANGELOG.md`; Pass 2 bare delivery-label pattern `D[0-9][a-z]+`. Triage hits per the rubric (forward-looking vs historical vs frozen planning artifact). Specifically: the TODOS.md R9b entry (lines 236–247) becomes obsolete and should be removed (R9b LANDED entry replaces it with a strikethrough + LANDED annotation per the D6e U4 pattern).

#### R14b — CLI dedup regression test for R9b flag interaction

Per the Overview's explicit U3 commitment and [[cli-loaded-packs-dedup-zip-strict-builtin-packs-flip-2026-05-18]]: R9b adds `--disable-rule` / `--enable-rule` CLI flags that modify the loaded rule set. Add a regression test at `tests/schema/lint/test_cli_rule_pack_dedup.py` (the parametrized dedup file landed D6e U1+U2) extending the test matrix with new cases:

1. `--disable-rule R` where R is in BUILTIN_PACKS → confirm the dedup invariant holds (rule R is filtered from the loaded set; the remaining loaded rules are unique).
2. `--enable-rule R` where R is NOT in BUILTIN_PACKS for the selected profile → confirm R loads once (not duplicated).
3. `--disable-rule R --rule-pack <pack-containing-R>` → confirm R is filtered even when explicitly loaded via pack (R8 polarity: disable beats include).
4. Repeated `--disable-rule R --disable-rule R` → confirm idempotent (R is filtered once; no dedup error).
5. Family-prefix expansion case from Req-R7: `--disable-rule custom/X` where X is multi-kind → confirm all mangled variants (`custom/X`, `custom/X__method`, etc.) are filtered.

The regression test is the load-bearing guard against silent dedup-invariant breakage when R9b mechanisms are exercised. Without it, a refactor that bypasses the R9b filter could re-introduce duplicate rule loading without test failure.

## Success Criteria

1. **R6 ERROR in `default` profile, verified empirically** — `BUILTIN_PACKS` profile membership counting yields `default`: 33 rules (unchanged), with all 5 `options/deprecated_replacement` rules at `severity=ERROR`. Pinned by a new test in `tests/schema/lint/rules/test_deprecated_replacement.py` (or wherever the family's per-rule tests live).

2. **R9b `"off"` accepted everywhere `LintSeverity` is accepted** — `[tool.protokit.lint.severities] "R" = "off"` parses cleanly; runtime confirms rule R does not load; no findings emitted; no runtime overhead. Coverage: parametrized test over BUILTIN_PACKS members + at least one `custom/<suffix>` rule.

3. **`disabled_rules` / `enabled_rules` round-trip cleanly through pyproject** — parametrized test over the Req-R8 resolution table. ALL 12 cases enumerated in the table must be covered: 4 single-mechanism baselines + 8 collision/idempotency cases. The cross-tier disable-wins case (CLI `--enable-rule R` + pyproject `disabled_rules = ["R"]`) is the load-bearing test; without it the polarity-first principle is unverified.

4. **`--disable-rule` / `--enable-rule` CLI flags work alone and compose with existing flags** — CLI integration tests for: standalone disable, standalone enable, multiple repeated flags, composition with `--profile`, composition with `--no-builtin-rules`, composition with `--rule-pack` (per Req-R14b case 3), composition with `--no-config` (the escape hatch for users genuinely needing to override pyproject disable).

5. **Contradictory-config + unknown-rule_id warnings surface correctly** (per Req-R8b + Req-R8c) — tests covering each `LintRuntimeWarning(category="contradictory_disable_config")` scenario from the Req-R8 resolution table; tests covering `LintRuntimeWarning(category="unknown_rule_id")` for typo and forward-compat cases. JSON formatter renders the category correctly; SARIF formatter handles both new categories without `assert_never` failure.

6. **`_LINT_JSON_SCHEMA_VERSION` bump verified** (per KD-7) — schema-version-bump presence ratchet (mirroring D6d patterns) confirms `_LINT_JSON_SCHEMA_VERSION` is `"0.6"` post-D6f. New `LintRuntimeWarning.category` `Literal` values `"contradictory_disable_config"` and `"unknown_rule_id"` are present in the type alias.

7. **Migration recipe TOML snippets pass byte-equivalent fixture verification** — per [[changelog-readme-snippet-fixture-byte-equivalence-2026-05-21]], every TOML snippet in the CHANGELOG D6f section maps to a fixture under `tests/schema/lint/cli/cli_fixtures/d6f_migration_recipe/` and parses cleanly through `_coerce_severities` / `_coerce_profile` / `_coerce_disabled_rules` / `_coerce_enabled_rules`. The 5-entry family-list form (Req-R2 path 3 family form) is one fixture; the single-entry forms are additional fixtures.

8. **CLI dedup invariant preserved** (per Req-R14b) — 5 new test cases in `tests/schema/lint/test_cli_rule_pack_dedup.py` covering R9b flag interactions with existing rule-pack loading.

9. **Wire-safety invariant** (per KD-7 + Phase 0 verification) — `LintFinding(severity=LintSeverity.OFF)` (or equivalent OFF marker if a sentinel pattern is chosen) is NEVER constructed; runtime assertion or type-system constraint enforces this. SARIF `_lint_severity_to_sarif_level` `assert_never` path is verified unreachable.

10. **All quality gates green on `main` after fast-forward merge** — `ruff` clean, `mypy --strict` clean on gated paths, full suite passes. Current baseline post-D6e: 2171 passed + 7 skipped; D6f adds tests for R9b precedence (Success Criteria #3), R9b warnings (#5), schema bump (#6), R6 promotion verification (#1), and CLI flag integration (#4 + #8).

## Scope Boundaries (Non-Goals)

Explicit deferrals to D6g+ or later:

- **R6 promotion in `recommended` profile**: R6 has no buf BASIC analogue; `recommended` stays at buf-parity scope. Even after D6f, R6 is `default`-only.
- **SHA-pinning test for D6e U3 buf snapshots**: defense-in-depth on the U3 parity gate; not blocked by D6f, but not bundled either. D6g candidate.
- **U3 ce:review residual P2/P3 unit tests**: unit tests for `_tarjan_scc` / `_walk_cycle_forward` / `_import_source_position`; FileLocation pairing invariant via `__post_init__`; cycle_path_rendered truncation. D6g candidate.

(The pre-existing `--help` epilog AC-4 finding from U4 ce:review is NOT deferred — it is folded INTO Requirement R9 as part of the R9b help-text rewrite. Listed here as an explicit cross-reference to avoid the appearance of double-tracking.)
- **`options/field-behavior-consistent` IDENTIFIER-based contradictions**: D6d U2 carry-over. D6g+ candidate.
- **`strict` profile rule enumeration** (COMMENT_*, ENUM_ZERO_VALUE_SUFFIX, etc.): probably its own multi-delivery arc. Not D6f.
- **MCP/IDE engine-recycle rebuild contract**: needs a real long-lived consumer to design against. D6g+ when a consumer materializes.
- **Buf-parity aliases for R9b CLI flags** (`--except-rule` / `--also-rule` as deprecated aliases): rejected per KD-1 (protokit-native naming is canonical; users coming from buf can map mentally). If real migration demand surfaces, ship as a 0.7.x patch.
- **Per-finding suppress mechanism** (`[severities] "custom/audit-required.params.option" = "off"`): substantially larger scope. D6g+ if user demand surfaces.
- **R6 audit findings or evidence-driven calibration**: PD-11 forcing-function defaults remain in effect. If real user reports surface during the D6f window suggesting R6 should re-demote (or apply to `recommended`), evaluate then; not pre-committed.

## Key Decisions

### KD-1 — R6 promotion is a deliberate KD-1 demonstration, not evidence-driven

D6f's R6 promotion is shipped without the PD-11 forcing-function (N=3 reports / M=8 weeks) having fired. The community-size caveat from D6e PD-11 applies: at protokit's current community size, N=3 may never fire. The promotion is justified on the basis that *Python-protobuf-developer ergonomics demand deprecation-without-replacement be CI-blocking by default* — the same KD-1 reasoning that justified `file/syntax-specified` R4b ERROR→WARNING demotion in D6e (inverse direction; same principle).

The PD-11 framework is preserved as the protocol for *future* audit-pass adjustments where evidence is the natural signal (e.g., a rule that turns out to false-positive in real corpora). KD-1 demonstrations are the protocol for severity calibrations driven by ergonomics judgments rather than evidence accumulation.

### KD-2 — R9b ships with full surface (lists + CLI + `"off"` sentinel) in one delivery

Considered shipping R9b incrementally (`"off"` sentinel first; `disabled_rules`/`enabled_rules` second; CLI flags third). Rejected because:

1. R6 promotion needs the full migration recipe in the CHANGELOG; partial R9b would publish a recipe with TBD entries, weakening the KD-1 demonstration.
2. The precedence semantics (R8) are inherent to the full surface — designing them for `"off"` alone and then revising for lists+CLI later would create churn.
3. The user-facing mental model is "per-rule on/off"; partial surfaces fragment the model.

Carrying cost is bounded: the precedence matrix is finite and the design rules (disable > enable; CLI > pyproject; `"off"` ≡ `disabled_rules`) are simple.

### KD-3 — Protokit-native naming wins over buf-parity (per D6e KD-1)

CLI flags are `--disable-rule` / `--enable-rule`; pyproject keys are `disabled_rules` / `enabled_rules`. Buf's `--except-rule` / `--also-rule` are NOT supported as aliases.

Rationale: clearer English semantics; consistency with existing protokit-native naming (`--no-builtin-rules`, `--min-severity`); D6e KD-1 alignment ("defaults reflect Python-protobuf-developer ergonomics, not buf's defaults"). Users coming from buf can map mentally; the cost is one-time learning.

**Explicit revisit trigger (post-document-review F5)**: ship buf-parity aliases as a 0.7.x patch if EITHER condition triggers within 12 weeks of 0.7.0 ship:

- **N≥2 distinct GitHub issues OR discussion posts** explicitly mentioning `--except-rule` / `--also-rule` confusion (typed the buf form, hit exit-2, asked why protokit doesn't accept it). The N=2 threshold reflects the small-community caveat from D6e PD-11; tighten to N=1 if any issue includes a minimal repro showing the user blocked on the missing alias.
- **Buf publishes a migration tool or doc** explicitly directing users to switch from buf to protokit. At that point the migration friction becomes structural and the aliases earn their carrying cost regardless of issue count.

If neither triggers by 2026-08-15 (12 weeks post-0.7.0 ship), the hedge expires — protokit-native naming becomes permanent. The aliases-deferred decision is reaffirmed in the D7 brainstorm (or earlier if 0.7.x stays open).

### KD-4 — `disabled_rules` / `enabled_rules` operate on rule_ids (not pack names)

Distinct from `--rule-pack` / `--no-builtin-rules` which operate at pack granularity. R9b's lists accept canonical rule_ids only (`pack/rule-suffix`). Pack-level disable was considered and rejected:

- `--no-builtin-rules` already provides pack-level disable for built-ins.
- Per-rule granularity is what `[severities]` already operates on; R9b extends that mental model.
- Adding pack-level R9b would introduce a third granularity (rule, pack, profile) and the user mental model becomes harder to predict.

### KD-5 — `enabled_rules` is additive (does not restrict)

`enabled_rules = ["R"]` does NOT mean "only R loads." It means "load R in addition to whatever the profile selects." For "only R loads" semantics, the user must combine `--no-builtin-rules` (or `essentials` profile) with `--enable-rule R`.

Rationale: matches existing additive behavior of `--rule-pack` (which adds packs, doesn't restrict to only the listed packs). Restrictive whitelists are a different mental model that should be handled by profile composition, not by list mechanics.

### KD-6 — `custom/<suffix>` synthetic rules are first-class in R9b (D6d carry-forward)

Per the D6d "synthetic rules look like real rules" principle, all R9b mechanisms accept `custom/<suffix>` rule_ids equivalently to built-in rule_ids. This includes: `[severities] "custom/audit-required" = "off"`, `disabled_rules = ["custom/audit-required"]`, and `--disable-rule custom/audit-required`.

Users who declare a custom rule but want to temporarily suppress it MUST be able to do so without removing or commenting out the `[[tool.protokit.lint.custom_annotation_rules]]` entry (which would lose all the configuration: `option`, `element_kinds`, `allowed_values`, etc.).

### KD-7 — `_LINT_JSON_SCHEMA_VERSION` bumps `"0.5"` → `"0.6"` for R9b (revised per Req-R8b + Req-R8c)

R9b introduces TWO new `LintRuntimeWarning.category` values via Req-R8b + Req-R8c:

- `"contradictory_disable_config"` (Req-R8b) for collisions between disable/enable mechanisms where one directive is silently overridden.
- `"unknown_rule_id"` (Req-R8c) for user-supplied rule_ids that don't match any loaded rule.

`LintRuntimeWarning.category` is a closed `Literal[...]` discriminator on the wire output. Per [[closed-literal-discriminator-bump-trigger-2026-05-17]], adding closed-discriminator values triggers a schema-version bump. D6f therefore bumps `_LINT_JSON_SCHEMA_VERSION` `"0.5"` → `"0.6"` for the two new category values (single bump covers both). This **resolves OQ-4 affirmatively**.

The other R9b surfaces remain bump-neutral:

- **`"off"` severity value** (Req-R4): `LintSeverity` is an open `Enum` (not a closed `Literal` on the wire). `LintFinding.severity` flows as a string in JSON output. CRITICAL invariant: `LintSeverity.OFF` MUST be intercepted at the config-coercion layer (or equivalently, rules with `"off"` severity must never enter the loaded-rules registry) so that `LintFinding(severity=LintSeverity.OFF)` is never constructed. If `LintSeverity.OFF` reached the SARIF formatter, the `assert_never(severity)` exhaustiveness check at `_lint_severity_to_sarif_level` would raise at runtime. This wire-safety invariant is the planning-time decision Phase 0 verification must confirm (which layer enforces "OFF means do not load"). Recommended: config layer (intercept `"off"` in `_coerce_severities`; do not add `OFF` to the `SEVERITY_RANK` dict; do not add `OFF` to `LintSeverity` enum at all — use a sentinel string OR a separate `LintDisabled` marker in `ResolvedLintConfig`).
- **`disabled_rules` / `enabled_rules`** are pyproject-only and CLI-only; not on the wire output.
- **`--disable-rule` / `--enable-rule`** are CLI-only; not on the wire output.

Phase 0 verification (Next Steps below) must confirm: (a) the `LintRuntimeWarning.category` `Literal` declaration shape; (b) the chosen `"off"` enforcement layer (recommended: config) so the wire-safety invariant holds; (c) the SARIF formatter's `assert_never` path is unreachable post-D6f.

### KD-8 — D6f opens a 4th severity-language usage pattern

D6e shipped 3 patterns in the [[migration-recipe-severity-aware-template-reuse-2026-05-21]] template: ERROR demotion (R4b), WARNING preservation, ERROR addition (new rule). D6f adds a 4th: **WARNING promotion to ERROR**. Update the template at the next ce:compound boundary if this is the first 3rd-instance trigger per the document's promotion rule.

## Open Questions (Deferred to Phase 0 / Planning)

### OQ-1: ~~Precedence matrix full enumeration~~ (RESOLVED in Req-R8)

The full 4-way collision matrix is now enumerated in Req-R8's resolution table. The cross-tier ambiguity (CLI `--enable-rule` vs pyproject `disabled_rules`) is resolved as: **polarity-first, tier-second** — disable wins across tiers; CLI > pyproject applies WITHIN polarity only. Planning need only validate the enumerated cases against the parametrized fixture (Success Criteria #3).

### OQ-2: ~~Rule_id validation strictness~~ (RESOLVED in Req-R8c)

Resolved as **lenient with `LintRuntimeWarning(category="unknown_rule_id")`** — format validation is strict (exit-2 on malformed rule_ids); existence validation is lenient (warn on unknown rule_ids, do not exit). This enables forward-compat (users can list rule_ids not yet implemented) AND surfaces typos as visible warnings rather than silent no-ops.

### OQ-3: R9b interaction with `--rule-pack` (RESOLVED principle; confirm at plan time)

**Resolved principle**: rule-level R9b mechanisms (`disabled_rules`, `--disable-rule`) win over pack-level loading (`--rule-pack <module>`). R9b's polarity-first principle from Req-R8 holds: disable beats load regardless of mechanism granularity. Concretely: `protokit lint --rule-pack foo.bar --disable-rule R` where R is in `foo.bar` results in R NOT loading. Test case enumerated in Req-R14b. Confirm at plan time that the implementation slot for R9b filtering runs AFTER `--rule-pack` loading in the engine's setup sequence.

### OQ-4: ~~`_LINT_JSON_SCHEMA_VERSION` bump trigger~~ (RESOLVED in KD-7 above)

Resolved affirmatively: `"0.5"` → `"0.6"` for the two new `LintRuntimeWarning.category` values introduced by Req-R8b (`"contradictory_disable_config"`) and Req-R8c (`"unknown_rule_id"`). Single bump covers both.

### OQ-5: README "Disabling and re-enabling rules" subsection placement

Req-R9 specifies a new subsection between the profile table and migration-recipe paragraph. The subsection title was updated from "Disabling rules" to "Disabling and re-enabling rules" (post-document-review F9) to reflect that R9b includes additive enable mechanisms. Confirm at plan time whether this is the right placement or whether a top-level section under "Schema Linting" reads better — this is a documentation-structure decision, not a behavioral one; defer to README author's judgment during the R12 implementation.

## Inputs (Prior Art / References)

- **D6e closing-arc delivery**: `docs/brainstorms/2026-05-22-d6e-buf-basic-closure-philosophy-revision-requirements.md` — establishes KD-1 (the inverted UX philosophy) and the `proto2-strict` opt-in pattern. D6f is the first post-closing-arc delivery exercising KD-1 on a severity decision.
- **D6e PD-11 forcing-function defaults**: `TODOS.md` lines 298–317 — the N=3/M=8-weeks framework for retroactive severity adjustments. D6f's R6 promotion is the KD-1-demonstration counterpart to PD-11's evidence-driven framework.
- **D6b U3a R6 introduction**: `CHANGELOG.md` D6b section — original WARNING-severity ship rationale.
- **D6e R4b file/syntax-specified demotion**: `CHANGELOG.md` D6e section — the inverse-direction worked example. R6 promotion follows the same migration-recipe template applied to the ERROR-promotion direction.
- **R9b TODOS backlog entry**: `TODOS.md` lines 236–247 — the prior framing ("`"off"` is NOT currently a valid severity value"). Becomes obsolete in D6f.
- **D6d custom annotation rules**: `CHANGELOG.md` D6d section + `src/protokit/schema/lint/_custom_rules.py` — establishes the "synthetic rules look like real rules" principle that KD-6 carries forward.
- **Buf's `--except-rule` / `--also-rule`**: prior art for CLI flag shape; named differently per KD-3 (protokit-native naming).
- **[[migration-recipe-severity-aware-template-reuse-2026-05-21]]**: severity-language template for the CHANGELOG migration recipe; D6f opens the 4th pattern (ERROR promotion) per KD-8.
- **[[changelog-readme-snippet-fixture-byte-equivalence-2026-05-21]]**: every TOML snippet in CHANGELOG/README must map to a verified fixture.
- **[[presence-ratchet-pin-canonical-not-local-form-2026-05-23]]**: brand-new D6e U4 learning; applies directly to R9b discoverability ratchets (R13 + R9 BUILTIN_PACKS docstring).
- **[[stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12]]** (updated 2026-05-23): two-pass sweep recipe; R14 invokes it.
- **[[delivery-boundary-unit-commit-composition-2026-05-14]]**: 7-component delivery-boundary checklist; U3 follows it.
- **[[pre-1.0-version-bump-as-communication-contract-2026-05-14]]**: minor-bump rationale for 0.6.0 → 0.7.0.
- **[[delivery-boundary-bundled-commit-feat-plus-review-followups-2026-05-21]]**: governs whether U3 boundary commit bundles ce:review follow-ups (default split; bundle when work is uncommitted at review time).
- **[[builtin-packs-expansion-changelog-migration-recipe-structure-2026-05-18]]**: 5-sub-section template; D6f's CHANGELOG section follows it (Added — R9b; Changed — R6 promotion + behavior delta; Pre-upgrade migration recipe; Test coverage; Deferred to D6g+).

## Visual: D6f Scope at a Glance

```
                          D6f UMBRELLA (0.7.0)
                          ────────────────────
                          KD-1 demonstration:
                          protokit-UX > buf-parity
                                  │
        ┌─────────────────────────┼─────────────────────────┐
        │                         │                         │
       U1                        U2                        U3
   R6 PROMOTION              R9b FULL SURFACE         DELIVERY BOUNDARY
   ────────────              ────────────────         ─────────────────
   WARNING → ERROR           "off" severity           pyproject 0.7.0
   default profile           disabled_rules           CHANGELOG fold
   5-rule family             enabled_rules            README refresh
   migration recipe          --disable-rule           BUILTIN_PACKS docstring
                             --enable-rule            presence ratchets
                             uniform: built-in        stale-text sweep
                                + custom/<suffix>     R9b discoverability

                          KD-2: ship R9b full surface in one delivery
                          KD-3: protokit-native naming (D6e KD-1 alignment)
                          KD-5: enabled_rules is additive, not restrictive
                          KD-6: custom rules first-class
                          KD-7: schema_version bumps 0.5 → 0.6 (2 new
                                LintRuntimeWarning categories from R8b+R8c)
                          KD-8: opens 4th severity-recipe pattern

                          Resolution table for R8 precedence matrix:
                          POLARITY FIRST (disable wins across all tiers),
                          TIER SECOND (CLI > pyproject within polarity).
                          Contradictory configs emit LintRuntimeWarning
                          (R8b); unknown rule_ids emit LintRuntimeWarning
                          + lenient continue (R8c).
```

## Next Steps

1. **`/ce:plan`** with this requirements doc as input. Post-document-review (2026-05-23), 4 of 5 Open Questions are RESOLVED in the brainstorm itself; planning only needs to validate against fixtures + confirm one implementation detail:
   - ~~**OQ-1**~~ (precedence matrix) — RESOLVED in Req-R8 with explicit polarity-first/tier-second principle + enumerated resolution table. Planning validates the cross-tier disable-wins resolution against the parametrized fixture (Success Criteria #3); no design decision remains.
   - ~~**OQ-2**~~ (rule_id validation strictness) — RESOLVED as lenient + `LintRuntimeWarning("unknown_rule_id")` in Req-R8c.
   - **OQ-3** (R9b interaction with `--rule-pack`) — principle RESOLVED (rule-level wins, per Req-R8 polarity-first). Planning confirms the engine's setup sequence runs R9b filtering AFTER `--rule-pack` loading; test enumerated in Req-R14b case 3.
   - ~~**OQ-4**~~ (`_LINT_JSON_SCHEMA_VERSION` bump) — RESOLVED affirmatively in KD-7 as `"0.5"` → `"0.6"` for the two new `LintRuntimeWarning.category` values from Req-R8b + Req-R8c.
   - **OQ-5** (README "Disabling and re-enabling rules" subsection placement) — title fixed (no longer "four disable forms"); placement confirmed at R12 implementation time as a docs-author judgment call, not a behavioral decision.
   - **Sequence** U2 → U1 → U3 — U2 (R9b) first as additive capability with zero behavior change; U1 (R6 promotion) lands the breaking change against an already-deployed escape hatch; U3 (boundary) wraps. Per-unit ce:review pipeline applies. Bundle U1+U2 only if both land in the same uncommitted state at delivery boundary per [[delivery-boundary-bundled-commit-feat-plus-review-followups-2026-05-21]] — DEFAULT is split per unit.

2. **Phase 0 verification** (expanded per document-review findings): before plan finalization, empirically check:
   - **R6 current state**: `grep -n severity src/protokit/schema/lint/rules/options/deprecated_replacement.py` — confirm WARNING is the actual ship state.
   - **`LintSeverity` enum shape**: `src/protokit/schema/lint/model.py:83-96` — confirm `LintSeverity` is `Enum` (not `Literal[...]`); add `LintSeverity.OFF` cleanly.
   - **`SEVERITY_RANK` dict extension**: `src/protokit/schema/lint/model.py:121-125` — `LintProfile.compose()` at lines 802-813 iterates this dict for `rule_severity_overrides`. `LintSeverity.OFF` MUST either receive a rank (e.g., -1) OR be filtered before reaching `compose()`. Specify which layer enforces "OFF means do not load" — config-coercion layer is preferred so OFF never enters `LintFinding` (preserves KD-7 wire-safety invariant + avoids SARIF formatter `assert_never` failure at `_builtin_lint.py`).
   - **`_ALLOWED_KEYS` extension**: `src/protokit/schema/lint/_config.py:447-458` — currently exit-2s on unknown pyproject keys; extend with `disabled_rules` (and `enabled_rules` if scope confirms).
   - **`from_dict` cli_overrides shape**: `src/protokit/schema/lint/_config.py:1509-1753` — existing `NotImplementedError` guards at lines 1684+1730 for `severities`/`custom_annotation_rules` establish the pattern. If R6 CLI flags ship, the `from_dict` branch for new `cli_overrides` keys must be added; otherwise the CLI override silently drops (the same footgun the codebase explicitly guards against).
   - **`_coerce_severities` error message at `_config.py:781-790`**: adding `LintSeverity.OFF` extends the dynamically-built "valid values" error string — verify it still reads coherently.
   - **`_coerce_*` helpers pattern**: `_config.py:575-607` `_coerce_exclude` — reference pattern for list-only coercion that `_coerce_disabled_rules` / `_coerce_enabled_rules` would follow.
   - **Existing CLI flag patterns**: `src/protokit/schema/lint/cli.py` — confirm `--disable-rule` / `--enable-rule` slot in without conflict with existing flags; confirm `multiple=True` Click pattern usage.
   - **Custom rule_id derivation**: `src/protokit/schema/lint/_custom_rules.py:440-476` (multi-kind mangling loop) + `:482-512` (`synthetic_rule_ids` including mangled forms). Critical: multi-kind entries register additional rule_ids as `custom/<suffix>__<kind>`. `disabled_rules = ["custom/audit-required"]` would suppress only the first-kind closure unless the disable lookup consults `synthetic_rule_ids()` and expands the prefix. R7's "uniform treatment" claim requires this expansion or the brainstorm scope must clarify single-kind-only.
   - **Pyproject.toml current version**: confirm `version = "0.6.0"` on `main` post-D6e-merge. If D6e hasn't merged, version is `0.5.0` and the bump target shifts.
   - **R6 empirical validation** (NEW per product-lens convergence): run protokit 0.7.0-candidate against (a) the project's own test fixtures + (b) a public corpus (e.g., googleapis protos). Count R6 hits AND classify each as genuine (replacement annotation missing) vs noisy (informal comment satisfies intent but heuristic regex doesn't match). If hits are noisy at >10% rate, the KD-1 demonstration framing is unsafe — revise to evidence-driven path OR tighten the heuristic before promotion.
   - **`proto2-strict` rule cross-syntax safety audit** (NEW per adversarial F5): if R5 (`enabled_rules`) is in scope, audit ALL current `proto2-strict` rules for explicit proto2-syntax guards. `enabled_rules = ["proto2-strict-rule"]` on a proto3 codebase must not produce nonsense findings. `field/not-required` (the only current proto2-strict rule) has a clean `LABEL_REQUIRED` cheap-check guard; future rules may not.
