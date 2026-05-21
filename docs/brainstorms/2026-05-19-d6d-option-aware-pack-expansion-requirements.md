---
date: 2026-05-19
last_revised: 2026-05-20
topic: protokit-lint-delivery-6d-option-aware-pack-expansion
---

# Protokit Lint Delivery 6d — Option-Aware Pack Expansion (0.5.0)

## Strategic Deferral (added 2026-05-20)

**`field/not-required` is DEFERRED from D6d to D6e+** per the
D6d U3 escalation analysis. The umbrella scope below preserves the
*option-aware pack expansion* headline (R1/R2/R3/R5/R6/R8/R9/R10
remain in scope) but RETIRES the bundled buf-BASIC parity close-out
(R4/R7/KD-5/S5) pending a comprehensive post-D6d UX-philosophy
revision.

**Why deferred (one paragraph):** The U3 per-unit brainstorm at
`docs/brainstorms/2026-05-20-d6d-u3-field-not-required-requirements.md`
+ two doc-review passes surfaced a 4-persona convergence: shipping
`field/not-required` at ERROR in `recommended`+`default` creates
double-jeopardy with the existing `file/syntax-specified` rule
(every proto2 file fires 1+N errors). The escalation also exposed
that protokit's lint defaults have drifted into an implicit anti-
proto2 stance via buf-parity-mirroring, without an explicit product
decision that proto2 is second-class. Resolving this requires a
larger conversation than D6d can host: principle articulation
("UX above buf parity"), retroactive `file/syntax-specified`
treatment, proto2-aware profile design, and an existing-rules audit.
That conversation lives at
`docs/brainstorms/2026-05-20-protokit-ux-philosophy-revision-requirements.md`
(placeholder); D6d defers the rule rather than ship-then-reverse.

**What this revision changes** (in-place markers below; the
forward-compatibility argument is laid out in the U3 brainstorm's
escalation analysis):

- **R4, R7, KD-5, S5** — marked SUPERSEDED/DEFERRED-to-D6e+ inline.
- **R11 CHANGELOG framing** — "buf BASIC FIELD_NOT_REQUIRED close-
  out" removed from the section title and migration recipe; numerator
  language reverts to "25 of 26 + FIELD_NOT_REQUIRED scheduled for
  D6e+" (matches D6c's existing CHANGELOG language).
- **Visual table** — `FIELD_NOT_REQUIRED` row removed.
- **S6** — wording adjusted (the "FIELD_NOT_REQUIRED for proto2
  users" carve-out is removed because the rule isn't shipping).
- **Implementation Units** (in the umbrella plan) — U3 deferred; U4
  becomes new U3; U5 becomes new U4. D6d ships in 4 units instead of
  5.
- **KD-17 numerator framing** (in the umbrella plan) — reverted.

**What this revision does NOT change**:

- Option-aware pack expansion headline (R1-R3, R5-R10, KD-1 through
  KD-4, KD-7 through KD-10) all stay.
- D6d still satisfies OQ-8 (option-aware as headline; the parity
  close-out was a bundled secondary scope item, not the headline).
- `file/syntax-specified` behavior at 0.5.0 — untouched pending the
  post-D6d UX-philosophy revision.
- U3 per-unit brainstorm at `docs/brainstorms/2026-05-20-d6d-u3-...md`
  — kept as analytical context; receives a SUPERSEDED-pending-
  philosophy-revision header but stays committed for the D6e+ unit
  that picks it back up.

**Scope:** strategic-differentiator delivery. D6d satisfies the OQ-8 forcing
function from D6c (binding pre-commit: "D6d MUST ship option-aware pack
expansion as headline OR document a concrete external escalation milestone
with project-owner sign-off"). After three consecutive deferrals of the
option-aware path (D6b → D6c → D6d), D6d lands the differentiator claim in
code: protokit reads custom protobuf options, and users can declare custom
annotation requirements in pyproject without writing Python. Bundles
`FIELD_NOT_REQUIRED` as a trivial proto2-only close-out (one of the seven
D6c-deferred items).

**Parent brainstorms:**
- `docs/brainstorms/2026-05-18-d6c-r8-cross-file-package-same-directory-requirements.md`
  (OQ-8 forcing function; the deferred D6d-bound items; in-D6c CHANGELOG
  acknowledgment of the deferral chain).
- `docs/brainstorms/2026-05-14-protokit-lint-delivery-6b-option-aware-and-multi-language-requirements.md`
  — enumerates the "R6-family-successors": `options/required-field-behavior`,
  `options/required-custom-annotation`, `options/json-name-respects-snake-case`.
  ("R6-family-successors" is the D6b-coined term for **future** option-aware
  rules envisioned beyond R6 — distinct from both D6b R6, the
  deprecated-replacement rule family, and from D6d's R6 requirement,
  the severity/profile defaults for `options/field-behavior-consistent`.)

## Problem Frame

Protokit's strategic differentiation — "the lint pass that reads custom
options and comments to enforce schema policy" — is currently theoretical at
the differentiator-headline level. D6b shipped R6 (deprecated-replacement
family) as the first option-aware rule, but the headline framing
("differentiator path operational") deliberately scoped that as
*plumbing-validation*. The full claim ("users can declare custom-annotation
requirements without writing Python") has been deferred three deliveries in
a row (D6b → D6c → D6d).

D6c's brainstorm + plan made this deferral chain a load-bearing concern:

- **OQ-8 forcing function (D6c brainstorm, line 127):** "D6d's brainstorm
  MUST either (a) ship option-aware pack expansion as headline, or (b)
  explicitly document why D6e is the new target with a concrete user/
  business-value milestone."
- **Strategic Sequencing (D6c plan, lines 293-299):** "D6d brainstorm
  contract (binding pre-commit) … D6e tripwire: If D6d also defers, this
  constitutes a strategic-positioning pattern that requires explicit
  product-level review."
- **In-D6c CHANGELOG `### D6c`:** Documents the deferral chain pointing at
  the D6d forcing function so external users tracking the project see the
  pattern, not just internal contributors.

**D6d resolves the forcing function by shipping headline option-aware
expansion**, not by triggering the escalation-milestone documentation path.

Secondary problem: D6c left seven items in `#### Deferred to D6d`:
(1) `PACKAGE_NO_IMPORT_CYCLE`, (2) `FIELD_NOT_REQUIRED`, (3) R6 promotion,
(4) R9b, (5) strict profile, (6) `LintLocation` exhaustiveness contract,
(7) option-aware pack expansion. D6d ships **two** closures from this
list: item (7) as the option-aware headline delivery, and item (2)
`FIELD_NOT_REQUIRED` as a trivial bundled close-out. The remaining
**five** items — (1) `PACKAGE_NO_IMPORT_CYCLE`, (3) R6 promotion,
(4) R9b, (5) strict profile, (6) `LintLocation` contract — stay
deferred to D6e+ with explicit acknowledgment in the D6d CHANGELOG
section.

## Requirements

**Option-aware pack expansion (headline)**

- **R1.** New rule template `custom/<user-suffix>` — synthetic-rule-id
  template for user-declared custom-annotation requirements. Each
  `[[tool.protokit.lint.custom_annotation_rules]]` array-of-tables entry
  materializes a first-class rule_id under the `custom/` namespace
  (e.g., `custom/audit-level`, `custom/pii-level`). Synthetic rule_ids
  appear in `--list-rules` identically to built-in rules and are
  individually controllable via `[severities]`. The `custom/` namespace
  is reserved for user-defined synthetic rules; protokit's built-in
  option-aware rules continue to live under `options/`.

- **R2.** Each `custom/<user-suffix>` requirement supports **presence +
  closed-value-set semantics on scalar option values**. Pyproject entry:
  `option` (required, full extension reference like `(mycorp.pii_level)`),
  `element_kinds` (required, subset of `ElementKind` enum), `allowed_values`
  (optional, closed set of scalars — strings, identifiers/enums, booleans,
  integers; floats explicitly NOT supported), `severity` (optional,
  per-instance override of default `warning`). When `allowed_values` is
  omitted, the rule fires only on *absence*; when set, the rule fires on
  absence OR on a value not in the set.

  **Value-encoding contract** (pinned; not deferred to planning).
  Comparison maps TOML literals to protobuf wire-format representations
  per-scalar-type as follows:

  | TOML literal type | Protobuf wire field | Comparison semantics |
  |---|---|---|
  | string (e.g., `"HIGH"`) | `identifier_value` (enum/identifier) OR `string_value` (string-typed extension) | String-equality. For enum-typed extensions, the TOML string compares against the enum **name** (e.g., `"HIGH"`) — NOT the enum **number**. For string-typed extensions, byte-exact UTF-8 comparison after TOML unescape. |
  | boolean (e.g., `true`) | `identifier_value = "true"`/`"false"` OR `bool_value` | TOML boolean is normalized to canonical lowercase string `"true"`/`"false"` then matched against `identifier_value`; if the wire-format uses `bool_value` instead (parser-dependent), match the literal bool. Accept either wire-format representation. |
  | integer (e.g., `5`, `-3`) | `positive_int_value`, `negative_int_value` | Signed-integer comparison. `negative_int_value: 3` represents -3; TOML `-3` matches. No automatic int↔float coercion. |
  | (REJECTED) float (e.g., `1.0`) | n/a | Config-load error: floats in `allowed_values` rejected with `error[lint-pyproject-config-invalid]:`. Rationale: float-equality semantics are user-hostile; if users need numeric ranges, defer to D6e+ value-regex. |
  | (REJECTED) mixed-type list (e.g., `["HIGH", 5, true]`) | n/a | Config-load error: a single `allowed_values` list must be homogeneously typed. Rationale: cross-type comparison is undefined; the TOML representation forces explicit type discipline. |

  **Unresolved-extension behavior**: if the user configures
  `option = "(mycorp.foo)"` but `(mycorp.foo)`'s defining proto is NOT
  in the compile set (extension unregistered in the descriptor pool),
  the rule emits `LintRuntimeWarning(category="custom_annotation_extension_unresolved")`
  identifying the synthetic `rule_id` + skips firing for that file.
  The warning's `category` literal is a new value added to
  `LintRuntimeWarning.category` Literal (existing values: 5; D6d adds
  the 6th). This is a wire-format-additive change — no schema_version
  bump required (additive Literal additions are bump-permissive per
  [[wire-format-schema-version-bump-contract-and-absence-semantic-2026-05-13]]).

- **R3.** New rule `options/field-behavior-consistent` — validates
  well-formedness of declared `(google.api.field_behavior)` lists. Fires on
  duplicates, INVALID values, and contradictory pairs (REQUIRED + OPTIONAL,
  REQUIRED + OUTPUT_ONLY, etc.). Single specimen of the "value-validation"
  template family — distinct from `custom/<suffix>`'s presence-checking
  template family. No configuration; AIP-203 anchored. (Renamed from D6b
  brainstorm's `options/required-field-behavior` to remove the misleading
  "required" prefix; the rule does not require presence, only validates
  consistency when present.)

**Buf BASIC parity close-out (bundled)** — **DEFERRED to D6e+ per
Strategic Deferral above (2026-05-20).**

- **R4. [SUPERSEDED — DEFERRED to D6e+]** New rule `FIELD_NOT_REQUIRED`
  (in the `field` rule pack) — fires on every proto2 field with
  `label == LABEL_REQUIRED`. *Original disposition: closes the
  proto2-only buf BASIC gap deferred from D6c.* **Revised disposition
  (2026-05-20):** deferred to D6e+ bundled with engine
  `ElementKind.EXTENSION_FIELD` walker work; that bundling lets the
  rule fire on cross-file `extend`-block extensions too (the divergence
  EV-2 surfaced in the U3 brainstorm), yielding a clean unhedged
  "27 of 27 buf BASIC rules" at D6e instead of a hedged "26 of 27 (with
  asterisks)" at D6d. See post-D6d philosophy revision placeholder for
  the broader context.

**Profile + severity defaults**

- **R5.** `custom/<suffix>` instances default to `severity = "warning"` if
  not specified per-instance. **Profile-firing committed (not deferred):**
  synthetic rule_ids are added to the composed profile's `rule_ids` set
  during config-resolution — i.e., `composed_profile.rule_ids =
  base_profile.rule_ids | synthetic_rule_ids`. The engine's existing
  profile-filter invariant (`active_specs = [spec for rid, spec in
  self._loaded_specs.items() if rid in profile.rule_ids]` at
  `engine.py:466-471`) is **unchanged**; synthetic rules fire because
  they belong to the composed profile, not because the engine bypasses
  the filter. Behavioral consequence: a configured `custom/<suffix>`
  fires on EVERY `--profile` invocation (including `--profile
  recommended`); users who want to scope a synthetic rule to `default`
  only must `[severities].\"custom/<suffix>\" = "off"` and override
  per-environment. Rejected: profile-restricted firing (option (b) in
  the brainstorm dialogue) — would weaken "you configured it, you want
  it to fire" semantics + force a per-instance profile-declaration
  surface (option (c)) for users who DO want all-profile firing.

- **R6.** `options/field-behavior-consistent` ships at `severity = "warning"`
  in `default` profile only (NOT in `recommended`). Matches D6b R6's
  conservative launch posture — limit blast radius until corpus tuning
  evidence accrues. `recommended`-profile users see zero new findings on
  upgrade. Promotion to `error` and/or `recommended` membership deferred
  to D6e+ pending real-world adoption data.

- **R7. [SUPERSEDED — DEFERRED to D6e+]** `FIELD_NOT_REQUIRED` ships at
  `severity = "error"` in both `recommended` + `default` profiles
  (forced by buf BASIC parity — buf v1.69.0 surfaces this rule at
  error severity). *Original rationale.* **Revised (2026-05-20):**
  R4 deferred to D6e+; severity/profile decisions defer to the
  bundling delivery + post-D6d UX-philosophy revision (which may
  conclude buf-parity-default ERROR is the wrong UX call for protokit
  given existing `file/syntax-specified` ERROR already covers proto2-
  file detection).

**Configuration surface**

- **R8.** Pyproject configuration surface for `custom/<suffix>` rules is
  `[[tool.protokit.lint.custom_annotation_rules]]` array-of-tables (key
  is snake_case for consistency with sibling keys `max_warnings`,
  `no_builtin_rules`, `min_severity`). Per-entry schema:

  ```toml
  [[tool.protokit.lint.custom_annotation_rules]]
  rule_suffix    = "audit-level"          # required; matches ^[a-z][a-z0-9]*(-[a-z0-9]+)*$
  option         = "(mycorp.audit_level)" # required; full extension ref
  element_kinds  = ["field", "method"]    # required; ≥1 ElementKind (lowercase)
  allowed_values = ["HIGH", "CRITICAL"]   # optional; homogeneously-typed scalars per R2 table
  severity       = "error"                # optional; default warning
  ```

  Adding `custom_annotation_rules` to `_config.py:_ALLOWED_KEYS`
  frozenset is a delivery prerequisite (current allowlist hard-errors
  on any unknown top-level key); the array-of-tables shape requires a
  new `_coerce_custom_annotation_rules` validator following the existing
  per-coercer pattern in `_config.py:1097-1112`. See KD-9.

- **R9.** Synthetic rule_id validation + collision detection at
  config-load time. Each entry's `rule_suffix` MUST match the regex
  `^[a-z][a-z0-9]*(-[a-z0-9]+)*$` (kebab-case: lowercase ASCII letters
  and digits, single hyphens between segments, no leading or trailing
  hyphen, no path separators, no Unicode). Suffixes are ASCII-only by
  construction — eliminates RTL-override / zero-width-joiner / path-
  traversal classes of injection. Malformed suffixes raise the existing
  `error[lint-pyproject-config-invalid]:` exit-2 surface from
  `_config.py` (NOT a new exception class — reuse the established
  pyproject validation channel). Collision detection: two entries with
  the same `rule_suffix` (case-sensitive; suffixes are ASCII-only so
  case-insensitivity is irrelevant) also raise
  `error[lint-pyproject-config-invalid]:` naming both pyproject
  positions. **KD-8 invariant**: protokit's `BUILTIN_PACKS` MUST NEVER
  ship a rule_id under the `custom/` prefix. Enforced via a regression
  test `test_no_builtin_rule_uses_custom_prefix` that walks
  `BUILTIN_PACKS` and asserts `not spec.rule_id.startswith("custom/")`
  for every loaded spec. Structural enforcement of the namespace
  separation, not social discipline.

- **R10.** Synthetic rule_ids are first-class in **existing** consumer
  surfaces: (a) `protokit lint --format=json` finding output — each
  finding's `rule_id` string matches the synthetic suffix (e.g.,
  `"custom/audit-level"`); (b) `[severities]` table demotion/disable
  (`[tool.protokit.lint.severities]\n"custom/audit-level" = "off"`);
  (c) the engine's loaded-spec registry (`LintEngine._loaded_specs`)
  contains the synthetic `LintRuleSpec` entries alongside built-ins, so
  any future consumer that walks the registry sees them uniformly.
  `source_spec` for synthetic instances is `"protokit:custom-annotation"`
  — a new protokit-namespaced value (not `buf:`, since no buf analogue
  exists; not `None`, since the field is consumer-visible in finding
  JSON via the rule's metadata lookup). A future `--list-rules`
  discoverability command — referenced as a future feature in
  `decorator.py:152` + `engine.py:151` but not implemented today — is
  out of D6d scope; building it is its own delivery. D6d does NOT
  depend on `--list-rules` for synthetic-rule visibility.

**Delivery surface**

- **R11.** CHANGELOG section `### D6d — option-aware pack expansion
  (0.5.0)` documents:
  - Headline framing (OQ-8 forcing function satisfied).
  - The TWO new rules shipping in D6d with severity + profile placement
    (`custom/<user-suffix>` synthetic template + `options/field-
    behavior-consistent`). `FIELD_NOT_REQUIRED` is NOT shipped in D6d.
  - The pre-upgrade migration recipe for `custom/<suffix>` newcomers
    (zero impact unless configured) + `options/field-behavior-
    consistent` (proto teams using `(google.api.field_behavior)` may
    see warnings on `default` profile).
  - Buf BASIC parity numerator: reverts to D6c's "25 of 26 buf BASIC
    rules" (the 26th is `PACKAGE_NO_IMPORT_CYCLE`; `FIELD_NOT_REQUIRED`
    is proto2-only and stays deferred per D6c's existing framing).
    Scheduled for D6e+ bundled with engine `ElementKind.EXTENSION_FIELD`
    walker work for clean "27 of 27" framing.
  - Explicit acknowledgment that D6b R6 promotion (the deprecated-
    replacement family severity promotion — distinct from this
    document's R6 which sets field-behavior-consistent severity
    defaults), R9b, strict profile, `LintLocation` exhaustiveness
    contract, `PACKAGE_NO_IMPORT_CYCLE`, AND `FIELD_NOT_REQUIRED`
    (newly added) STILL defer to D6e+ — with the same in-CHANGELOG
    visibility pattern D6c established.
  - **NEW**: Forward pointer to the post-D6d UX-philosophy revision
    (placeholder at `docs/brainstorms/2026-05-20-protokit-ux-
    philosophy-revision-requirements.md`) — a structural-revisit
    delivery that will re-evaluate buf-parity-vs-protokit-UX defaults
    across the existing rule set.

- **R12.** README updates: Schema Linting section's rule table adds the
  three new rules; profile table reflects updated counts; worked example
  demonstrates `custom/<suffix>` end-to-end (pyproject entry + sample
  proto + resulting `--format=text` finding).

- **R13.** pyproject version bump `0.4.0` → `0.5.0`. Minor bump reflects
  new feature surface (synthetic rule_id mechanism is a new public API
  for pyproject consumers); not a major bump since no existing rule
  semantics or wire-format break.

## Visual: D6d Scope at a Glance

| Rule | Template family | Severity | Profile | Source spec | Migration impact |
|---|---|---|---|---|---|
| `custom/<user-suffix>` | Presence + closed-value-set (synthetic) | `warning` (overridable per-instance) | added to composed profile when configured (fires on all `--profile` invocations) | `protokit:custom-annotation` | Zero unless user configures `[[tool.protokit.lint.custom_annotation_rules]]` |
| `options/field-behavior-consistent` | Value-validation (built-in) | `warning` | `default` only | `https://google.aip.dev/203` | `default`-profile users with `(google.api.field_behavior)` typos/duplicates see warnings |

*(`FIELD_NOT_REQUIRED` row removed 2026-05-20 — rule deferred to D6e+
per Strategic Deferral.)*

## Success Criteria

- **S1.** OQ-8 forcing function satisfied. `### D6d` CHANGELOG section's
  headline is "option-aware pack expansion" — not parity, not hygiene,
  not deferred.

- **S2.** The strategic differentiator claim transitions from theoretical
  to demonstrable AND **provable in CI** (not just documentation prose).
  D6d ships a self-contained integration-test fixture at
  `tests/integration/d6d_custom_annotation_example/` containing: a
  sample proto file using a custom extension (`(example.audit_level)`),
  the extension's defining proto, a sample `pyproject.toml` with a
  `[[tool.protokit.lint.custom_annotation_rules]]` entry, and a pytest
  that invokes `protokit lint` end-to-end and asserts the expected
  `--format=json` finding output. README's Schema Linting section
  references this fixture as the canonical worked example
  (`see tests/integration/d6d_custom_annotation_example/`). This makes
  OQ-8 satisfaction **provable** rather than rhetorical — the
  differentiator claim is backed by a passing test that an external
  user can read, run, and modify.

- **S3.** Synthetic rule_ids are first-class in finding output.
  `protokit lint --format=json` on a project with N configured
  `custom/<suffix>` entries surfaces findings whose `rule_id` strings
  match the synthetic suffixes (e.g., `"custom/audit-level"`,
  `"custom/pii-level"`). Each is individually demoted/disabled via
  `[severities]`. The engine's `_loaded_specs` registry contains the
  synthetic `LintRuleSpec` entries so any future registry-walking
  consumer (`--list-rules`, programmatic API) sees them uniformly. No
  CLI surface beyond the existing `--format=json` is required.

- **S4.** `options/field-behavior-consistent` catches at least 3 distinct
  well-formedness violation classes on a curated test corpus:
  (a) duplicate value within a single field's behavior list,
  (b) INVALID value, (c) at least one contradictory pair (the exact
  curated set deferred to planning per AIP-203 research).

- **S5. [SUPERSEDED — DEFERRED to D6e+]** `FIELD_NOT_REQUIRED` fires
  on every proto2 `required` field + zero proto3 fields. Buf-parity
  gate against v1.69.0 NDJSON snapshots asserts byte-equivalent output
  for a curated fixture corpus. *Original criterion.* **Revised
  (2026-05-20):** rule deferred per Strategic Deferral; success criterion
  moves to the D6e+ bundling delivery.

- **S6.** Multi-language teams using `--profile recommended` with **no
  configured `custom/<suffix>` entries** see ZERO new findings on
  0.5.0 upgrade. `options/field-behavior-consistent` is confined to
  `default` per R6; `custom/<suffix>` is opt-in per R5 (zero-config
  users see no synthetic rules). Teams that DO configure
  `custom/<suffix>` entries see those rules fire on `--profile
  recommended` per R5's all-profile-firing commitment — this is
  intentional and documented in the pre-upgrade migration recipe.
  *(2026-05-20: removed "except `FIELD_NOT_REQUIRED` for proto2 users"
  carve-out since R4/R7 are deferred. Net: zero-config proto2 users
  see ZERO new findings in `recommended` on 0.5.0.)*

- **S7.** D6c's deferral-chain acknowledgment pattern continues — the
  D6d CHANGELOG explicitly names the five items STILL deferred (D6b R6
  promotion, R9b, strict profile, LintLocation contract,
  PACKAGE_NO_IMPORT_CYCLE) and gives the project-owner-visible signal
  that the D6e tripwire criteria still apply to those items. **NOTE:**
  "D6b R6 promotion" = the deprecated-replacement rule family severity
  promotion (D6b origin), distinct from this document's R6 (severity
  defaults for `options/field-behavior-consistent`). The collision in
  the "R6" label is documented; rule-id-stable identifiers downstream
  prevent runtime confusion.

## Scope Boundaries

**Out of scope for D6d (deferred to D6e+):**

- **`PACKAGE_NO_IMPORT_CYCLE`** — its own architectural delivery.
  Cross-file cycle detection over a package-import DAG is not amenable
  to the D6c Arch-D pre-walk accumulator. D6c brainstorm flagged the
  unblocking empirical investigation (§ "Empirical Findings and Open
  Questions That Carry Forward", item 5: construct a fixture where
  files form a DAG but packages form a cycle; verify buf v1.69.0's
  PACKAGE_NO_IMPORT_CYCLE output shape at the JSON layer; record finding
  structure). This work is a D6e+ prerequisite, not D6d scope.

- **`custom/<suffix>` value-regex (`value_pattern`)** — orthogonal to
  `allowed_values`, additively layerable in D6e+ if real demand surfaces.
  Per KD-3 the closed-value-set is the floor for D6d's expressivity; the
  regex layer is the future ceiling. No commitment to regex dialect or
  anchoring rules in D6d.

- **`custom/<suffix>` on message-typed or repeated-typed options** —
  documented as out-of-scope in R2's "scalar option values only" qualifier.
  Users with message-typed custom options can opt into manual enforcement
  pre-D6e+; protokit's contract is "scalar values only" for the closed-set
  comparison. Plan documents the runtime behavior (no-op, or config-load
  rejection) at design time.

- **`options/json-name-respects-snake-case`** — D6b brainstorm enumerated
  this as a third R6-family-successor candidate. Explicitly cut from D6d
  to keep the delivery narrative coherent (one custom-annotation
  template + one value-validation template + one trivial close-out is
  the narrative; adding a narrow style rule dilutes). Carry-forward
  candidate for D6e if `options/field-behavior-consistent` validates the
  value-validation template family.

- **D6b R6 promotion to `error` severity** (the D6b deprecated-replacement
  rule family — NOT this document's R6 which concerns
  `options/field-behavior-consistent` severity defaults) — D6c CHANGELOG
  noted "pending real-world experience with the leading-comment heuristic
  accuracy." D6d does not yet have that evidence; remains deferred.
  Tripwire criteria revised for actionability (no external GitHub issues
  channel exists today): a manual precision audit on protokit's own test
  corpus PLUS ≥3 distinct external proto repositories (located via open-
  source search) showing ≥95% precision of the leading-comment heuristic.
  Audit can be commissioned at any time post-0.5.0 without external
  evidence-channel dependency.

- **R9b per-rule disable/enable CLI flag** — `[severities] = "off"` is
  the current de-facto disable mechanism; still no documented user-demand
  evidence (per D6b's "≥2 GitHub issues" channel).

- **`strict` profile rule enumeration** — no rule declares
  `profiles=("strict",)` today; the "what belongs in strict" design space
  remains open. D6d's `options/field-behavior-consistent` is a
  *candidate* for strict-profile membership if/when strict is enumerated,
  but not pre-committed here.

- **`LintLocation` exhaustiveness contract decision (D6c OQ-7)** — D6d
  introduces no new `LintLocation` variant (R3 and R4 fire at field-
  level; R1 fires at whichever ElementKind the user configures, from
  the 8-value `ElementKind` enum — each kind's option-introspection
  support is verified by the empirical Phase 0 prerequisite in Outstanding
  Questions). The exhaustiveness contract gap (docstring contract vs
  duck-typed in-tree practice) remains unaddressed; tracked for D6e+
  as before.

- **TOML-distributable rule packs** ("(C) restricted to template-based
  rules" from the brainstorm dialogue) — natural future extension of
  R1's synthetic-rule mechanism. Packs would bundle N `custom/<suffix>`
  instances as a shareable artifact, distributable via `--rule-pack=
  path/to/mycorp.protokit-pack.toml`. Not in D6d scope; tracked as the
  next compounding step for the option-aware ecosystem story.

## Key Decisions

- **KD-1. D6d ships option-aware as headline (OQ-8 forcing function
  resolved).** Closes the D6b → D6c → D6d three-consecutive-deferral
  pattern. Avoids triggering the D6e tripwire (strategic-positioning
  pattern requiring explicit product-level review).

- **KD-2. Custom-annotation rule uses synthetic per-requirement rule_ids
  under the `custom/<suffix>` namespace.** Rejected: (a) single-rule
  multi-instance (`options/required-custom-annotation` with internal
  enumeration), because the differentiator narrative depends on each
  user-defined requirement appearing as a first-class rule in
  `--list-rules`. Rejected: (b) putting synthetic ids under
  `options/required-custom-annotation/<suffix>`, because that namespace
  is reserved for protokit's future built-in option-aware rules and
  collides with user-defined suffixes. The `custom/` top-level namespace
  is dedicated to user-defined synthetic rules.

- **KD-3. Custom-annotation rule semantics: presence + closed-value-set
  on scalar option values.** Rejected: presence-only (under-scoped — the
  differentiator headline deflates if the rule can't enforce that an
  annotation has the *right* value). Rejected: value-regex (over-scoped
  — commits to regex dialect + anchoring rules without user evidence to
  design against; deferred to D6e+ as orthogonal extension to
  `allowed_values`). Closed-value-set is the floor for "real policy
  encoding" without the regex tax.

- **KD-4. Field-behavior rule semantics: well-formedness only, NOT
  presence-required-on-pattern.** Renamed from D6b brainstorm's
  `options/required-field-behavior` to `options/field-behavior-consistent`
  for naming clarity (the rule does not require the annotation; it only
  validates well-formedness when the annotation is declared).
  Pattern-based "required on field-name-pattern X" semantics deferred —
  if real demand emerges, a separate rule
  `options/required-field-behavior` can be added in D6e+ with explicit
  configuration.

- **KD-5. [SUPERSEDED — REVERSED 2026-05-20]** *Original:
  `FIELD_NOT_REQUIRED` bundled as trivial close-out.* **Revised:** the
  "trivial" framing was wrong on closer inspection. The rule body is
  ≤10 LOC but its full delivery requires Phase 0 empirical verification
  + 8-9 fixture corpus + parity-helper extension + divergence-fixture
  test wiring + CLI dedup regression test + ratchet substring
  coordination + an accepted parity-gate divergence (EV-2 engine
  walker gap) — collectively NOT a trivial close-out. Additionally,
  shipping the rule at ERROR in `recommended`+`default` creates
  double-jeopardy with the existing `file/syntax-specified` rule
  (proto2 file: 1 file-level error + N field-level errors). The
  decision to defer to D6e+ (bundled with engine
  `ElementKind.EXTENSION_FIELD` walker work for clean unhedged
  parity) is recorded here for future readers. The D6d differentiator
  narrative is also better-served by NOT bundling the parity rule —
  the option-aware headline stands alone in 0.5.0.

- **KD-6. Five-item deferral chain (D6b R6 promotion, R9b, strict
  profile, LintLocation contract, PACKAGE_NO_IMPORT_CYCLE) STILL
  deferred to D6e+.** Per D6c's in-CHANGELOG pattern, the D6d `### D6d` section
  acknowledges these five items explicitly, with the project-owner
  signal that the D6e tripwire criteria continue to apply. This is the
  same forcing-function-visibility discipline D6c established.

- **KD-7. Default custom-annotation rules are NOT shipped in D6d.**
  Rejected option (B) from the brainstorm dialogue ("Default
  custom/<suffix> instance"): protokit could ship a built-in pre-
  configured `custom/field-behavior-required` instance demonstrating the
  mechanism on real googleapis options. Rejected because:
  (a) the conventional field-name patterns are codebase-specific
  (`id`, `parent`, `name`) — shipping defaults forces users to
  `[severities] = "off"` to opt out, which violates the "always-on
  once configured" semantics of R5;
  (b) the worked example in R12's README update demonstrates the
  mechanism without forcing it on users. Configuration ergonomics
  beats opinionated defaults at pre-1.0.

- **KD-8. The `options/` pack continues to house built-in option-aware
  rules; the `custom/` namespace is reserved for user synthetic rules.**
  R3 (`options/field-behavior-consistent`) lives under `options/`. R1
  (synthetic rule_ids) lives under `custom/`. The two namespaces are
  intentionally separated to prevent collision as protokit's built-in
  option-aware pack grows in D6e+. This is the most important
  consequence of KD-2's namespace decision. Enforced structurally via
  the `test_no_builtin_rule_uses_custom_prefix` regression test in R9.

- **KD-9. Pyproject `_ALLOWED_KEYS` extension + snake_case key naming.**
  `custom_annotation_rules` (snake_case, matching sibling keys
  `max_warnings`, `no_builtin_rules`, `min_severity`) is added to
  `_config.py:_ALLOWED_KEYS` frozenset. A new
  `_coerce_custom_annotation_rules` validator follows the existing
  per-coercer pattern at `_config.py:1097-1112`; rejects malformed
  entries with the established `error[lint-pyproject-config-invalid]:`
  prefix. The array-of-tables shape is the first such shape on the
  pyproject surface (existing keys are scalars or flat tables) —
  validation logic must handle list-of-dicts; per-entry validation
  delegates to a sub-coercer. Precedence rule for severity overrides:
  the existing `[tool.protokit.lint.severities]` table is the LAST
  authority (overrides per-instance `severity` field). This is the
  current pyproject precedence model — synthetic rules inherit it
  without exception.

- **KD-10. Synthetic-rule loading mechanism: synthetic ModuleType.**
  At config-load time, the validator constructs a synthetic
  `ModuleType` object whose `RULES` attribute is a tuple of closures.
  Each closure has a `_lint_spec: LintRuleSpec` attached at construction
  (mimicking the `@lint_rule` decoration model); the engine calls
  `LintEngine.load_rule_pack(synthetic_module)` exactly as it does for
  built-in modules. Rejected: (a) new `engine.load_synthetic_rule(spec,
  fn)` API — would create a second loading-path code branch that
  duplicates `_loaded_specs` registration logic; (b) generating Python
  source + importing — security-hostile + violates the "no eval"
  invariant. The synthetic-module approach preserves "one loading
  mechanism" + reuses `DuplicateRuleError` for collision detection
  between synthetic rules and any future built-in additions (defense in
  depth alongside KD-8's regression test). Closure body is rule_id-
  uniform; per-instance state (option name, element_kinds, allowed_values,
  severity) is bound via closure capture.

## Dependencies / Assumptions

- **Buf v1.69.0 BASIC enumeration unchanged.** D6c's Phase 0
  verification (`buf config ls-lint-rules --configured-only
  --format=json` against `use: [BASIC]`) established the 26-rule
  baseline + the FIELD_NOT_REQUIRED proto2-only carve-out. D6d assumes
  no BASIC additions since 2026-05-18. /ce:plan re-verifies if
  evidence-suggesting otherwise surfaces.

- **Existing option-aware infrastructure is reusable.** D6b R6's
  `src/protokit/schema/lint/rules/options/_comments.py` (`leading_comment`
  helper) is not directly reused by D6d (R1 doesn't need comments, only
  option presence/value); however, R6's pattern of an `options/` module
  with rule_id-namespaced files is the precedent for organizing
  `options/field-behavior_consistent.py` + the synthetic-rule loader. R6
  is not modified by D6d.

- **Custom option value parsing path through the existing protoxy
  compile result is unverified for arbitrary user extensions.** R6's
  `deprecated_replacement.py` consumer accesses `*Options.deprecated`
  (a registered built-in attribute). D6d's R1 accesses arbitrary
  extension-typed option values via `protokit.options.get_option_value`
  (existing helper at `src/protokit/options.py:43-124`), which has a
  two-tier resolution path: tier 1 reads `Extensions[ext_desc]`
  (requires extension registered in pool), tier 2 reads
  `uninterpreted_option` linearly. **Empirical verification moved to
  Resolve Before Planning** (see Outstanding Questions). The
  unresolved-extension behavior is committed in R2 (emit
  `LintRuntimeWarning(category="custom_annotation_extension_unresolved")`
  + skip).

- **Proto-extension declaration is the user's responsibility.** Users who
  configure `custom/<suffix>` rules with `option = "(mycorp.foo)"` must
  ensure their compile invocation includes the extension's defining
  proto. Protokit does not stub or auto-load custom extensions; this is
  consistent with how `(google.api.field_behavior)` is handled in R3
  (the rule requires the googleapis extension proto in the compile
  set).

## Outstanding Questions

### Resolve Before Planning

- **[Affects R1, R2, KD-10] [Needs verification]** Empirically verify
  `protokit.options.get_option_value` surfaces arbitrary
  user-extension values usefully on protoxy's compile result. Construct
  a minimal proto with a custom extension (`(example.audit_level)`
  registered + applied to a field), compile via protoxy, and inspect
  the returned value through tier-1 (`Extensions[]`) AND tier-2
  (`uninterpreted_option`) resolution paths. **Outcome required:** for
  EACH scalar TOML type in R2's contract table (string, identifier/enum,
  bool, integer), confirm which wire field the parser emits (so R2's
  comparison logic is grounded in reality, not docs). 30-minute
  verification; do BEFORE writing U1. If tier-2 returns raw bytes
  instead of decoded values for the integer/bool cases, R2's contract
  needs revision before /ce:plan finalizes.

- **[Affects KD-4, R3] [Pre-emptive user impact]** Backwards-compat
  handling for the `options/required-field-behavior` →
  `options/field-behavior-consistent` rename. A user who read the D6b
  brainstorm and pre-emptively configured
  `[tool.protokit.lint.severities] "options/required-field-behavior" =
  "off"` gets silent no-op on 0.5.0 today (rule_id never matches a
  loaded rule). Pick one of: (a) emit
  `LintRuntimeWarning(category="unloaded_rule")` for the old name —
  consistent with existing `severities_unloaded_rule` mechanism, fires
  at runtime; (b) hard-error at config-load — louder but breaks
  pre-emptive users; (c) silent alias — accept the old name as a
  permanent shim mapping to the new rule_id. Recommend (a) — the
  existing runtime-warning mechanism already covers this case, and the
  old name was never actually shipped as a rule (only mentioned in
  brainstorm/planning docs), so the precedent is low-impact.

### Deferred to Planning

- **[Affects R3] [Needs research]** Exact set of "contradictory pairs"
  for `options/field-behavior-consistent`. AIP-203 enumerates the
  FieldBehavior enum (REQUIRED, OPTIONAL, IMMUTABLE, OUTPUT_ONLY,
  INPUT_ONLY, UNORDERED_LIST, IDENTIFIER, NON_EMPTY_DEFAULT) but does
  not formally enumerate which pairs are contradictory. /ce:plan
  researches the curated set + documents inclusion criteria. Initial
  candidates from the brainstorm dialogue:
  - REQUIRED + OPTIONAL (semantically opposite)
  - REQUIRED + OUTPUT_ONLY (can't require a server-only field)
  - OUTPUT_ONLY + INPUT_ONLY (mutually exclusive directionality)
  - IDENTIFIER + OUTPUT_ONLY (identifiers are inputs)
  - IMMUTABLE + OUTPUT_ONLY (redundant or contradictory)
  Plan validates against AIP-203 prose + grpc/googleapis usage.

- **[Affects R1, R8] [Technical]** ElementKinds support for
  `custom/<suffix>`. R8 allows `element_kinds` to be a subset of the
  8-value `ElementKind` enum. Per feasibility review, every kind has a
  corresponding `*Options` class (`FileOptions`, `ServiceOptions`,
  `MethodOptions`, `EnumOptions`, `EnumValueOptions`, `MessageOptions`,
  `FieldOptions`, `OneofOptions`) — so option-introspection is uniformly
  available. The narrow question deferred: which of the 8 LintContext
  classes need a helper accessor for the option value, and whether the
  closure shape (per KD-10) can be uniform across all 8 kinds. /ce:plan
  resolves at U1 design time; expects "yes, uniform closure" but
  verifies.

- **[Affects R4, R7] [Needs research]** FIELD_NOT_REQUIRED edge cases:
  (a) proto2 `extend` blocks adding `required` extensions — fires in
  extending file, extended file, both, or neither? (b) edition-2024+
  files using `features.field_presence = LEGACY_REQUIRED` — fire (treat
  as equivalent) or skip (no `LABEL_REQUIRED` keyword)? (c) proto3 file
  importing proto2 — rule fires per-file in the proto2 file's lint pass
  only, not in the proto3 importer's pass. /ce:plan adds fixture
  coverage for each + verifies against buf v1.69.0 parity snapshot.
  Per KD-5's "no new infrastructure" claim, these must resolve via the
  existing `ElementKind.FIELD` walker.

- **[Affects R11] [Technical]** Post-D6d buf BASIC numerator framing.
  Pre-D6d (D6c): "25 of 26 buf BASIC rules" with the 26-rule baseline
  excluding FIELD_NOT_REQUIRED. Post-D6d framings:
  (a) "26 of 27 buf BASIC rules" — drop the proto2-only carve-out;
      denominator is buf's true total.
  (b) "25 of 26 buf BASIC rules + FIELD_NOT_REQUIRED close-out" — keep
      the existing denominator gimmick + report FIELD_NOT_REQUIRED
      separately.
  (c) "All buf BASIC rules except PACKAGE_NO_IMPORT_CYCLE" — drop the
      ratio framing entirely.
  Plan **picks at U1 design time, not U4** — the choice gates the U4
  presence-ratchet test substring per
  [[presence-ratchet-test-pattern-for-prose-substrings-2026-05-14]]
  (a U4 test written against framing (a) would fail under framing (b)).
  Recommend (a) as the cleanest audit-trail-true option.

- **[Affects R11] [Technical]** Migration recipe structure for D6d.
  D6d's blast radius for a `recommended`-profile proto3 user with no
  configured synthetic rules is ZERO (per S6); for proto2 users it's
  FIELD_NOT_REQUIRED only; for `default`-profile users with
  `(google.api.field_behavior)` it's field-behavior-consistent warnings;
  for configured-synthetic-rule users it's whatever they configured.
  The U7 4-path migration recipe template (per
  [[builtin-packs-expansion-changelog-migration-recipe-structure-2026-05-18]])
  is over-scoped for this blast radius. Plan produces a 2-3 path
  recipe (configure-and-adopt / ignore / demote-to-info), NOT 4-path
  with "pin to 0.4.x" theater. Per-rule sub-sections for
  field-behavior-consistent + FIELD_NOT_REQUIRED + custom/<suffix>.

- **[Affects R3, R8] [Technical]** Single-specimen abstraction trap
  prevention for R8's synthetic-rule schema. Future templates beyond
  presence + closed-value-set (value-regex, message-typed options,
  pattern-based presence-required) may not cleanly extend the current
  flat-fields schema. Add a `template = "presence-and-values"`
  discriminator field to R8 NOW with one supported value, so future
  templates can specify `template = "value-regex"` etc. without a
  schema-migration breaking change. Plan decides whether to ship the
  field with one value (forward-compat) OR defer until the second
  template lands (YAGNI). Recommend forward-compat — the field is
  cheap, the future-template question is concrete.

- **[Technical]** Unit count + delivery shape. Probable shape:
  - **U1.** Synthetic-rule-id infrastructure (per KD-9 + KD-10):
    pyproject `_ALLOWED_KEYS` extension + `_coerce_custom_annotation_rules`
    validator + `rule_suffix` regex validation (R9) + synthetic
    ModuleType construction with closures + R9's collision detection
    + composed-profile augmentation (R5) + new
    `LintRuntimeWarning.category` value (`"custom_annotation_extension_unresolved"`).
    Phase 0 prerequisite: empirical extension-parsing verification.
    May split if the U1 surface grows past ~600 LOC.
  - **U2.** `options/field-behavior-consistent` rule + curated
    contradictory-pair set + AIP-203 anchored unit tests + pack
    placement decision.
  - **U3.** `FIELD_NOT_REQUIRED` rule + buf v1.69.0 parity gate
    snapshots + fixture coverage for `extend`-block + edition-2024
    edge cases.
  - **U4.** Integration-test fixture for R12's worked example
    (`tests/integration/d6d_custom_annotation_example/`) +
    README + CHANGELOG draft.
  - **U5.** Delivery boundary: pyproject 0.4.0 → 0.5.0, CHANGELOG
    fold, README refresh, stale-text sweep, presence-ratchet test for
    `### D6d` CHANGELOG section per
    [[presence-ratchet-test-pattern-for-prose-substrings-2026-05-14]].
  Plan finalizes.

- **[Technical]** Where does `options/field-behavior-consistent` live in
  the rules tree? Sibling of `options/deprecated_replacement.py`. Sub-
  question: does it belong in the existing `options` rule pack, or is a
  new `options_consistency` (or `options_validation`) sub-pack
  warranted? Plan decides at U2 design time per pack-cohesion
  heuristics.

- **[Technical]** Reserved-prefix policy for the `custom/` namespace.
  Should protokit reserve specific `rule_suffix` prefixes (e.g., a
  future protokit-curated set of synthetic-rule defaults)? D6d ships
  without any reserved prefixes — every regex-passing suffix is fair
  game for users. Plan documents this stance + the forward path if
  reserved prefixes become necessary (config-load validation against a
  `_RESERVED_SUFFIXES` frozenset). The KD-8 invariant
  (`no built-in rule_id starts with "custom/"`) is the cheap
  structural enforcement; user-facing reservation is a separate D6e+
  question.

- **[Technical]** Build-vs-use audit for the synthetic-rule approach.
  buf custom plugins (`buf.plugin.yaml`), protovalidate
  (`buf.validate.field` + CEL expressions), and Google's `api-linter`
  rule-pack mechanism all overlap with R1's design space. /ce:plan
  adds a 1-page comparison documenting (a) what each ecosystem-existing
  mechanism covers, (b) why protokit's TOML synthetic rule is
  preferable to surfacing protovalidate annotations as lint findings
  (different runtime vs lint-time semantic) and to wrapping buf's
  plugin interface. Prevents future "protokit reinvented X" critique.

## Next Steps

`-> /ce:plan` for structured implementation planning.
