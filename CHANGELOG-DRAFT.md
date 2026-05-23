# CHANGELOG-DRAFT — D6e+ staging

This file stages CHANGELOG content for the next 0.X.0 release. Per
[[dormant-code-changelog-draft-staging-delivery-boundary-2026-05-17]],
each in-flight unit appends its content here; the delivery-boundary
unit folds the staged sections into `CHANGELOG.md` alongside the
version bump.

D6d content folded into `CHANGELOG.md` as
`### D6d — option-aware pack expansion + AIP-203 well-formedness (0.5.0)`.
New D6e+ content begins below.

---

## D6e — staged (U1+U2 atomic; U3 + U4 still pending)

### Added

- **D6e KD-1: hard-inverted UX philosophy** — protokit-UX overrides
  buf-parity when they conflict; proto2-specific strict rules ship
  in opt-in `proto2-strict` profile per KD-2 (pragmatic-not-
  dogmatic about proto2). The principle is pinned via presence
  ratchet in `BUILTIN_PACKS` docstring +
  `tests/test_uxd_philosophy_principle_presence_ratchet.py` so
  future stale-text edits cannot silently revert the stance.
- **D6e POSITIONING_STATEMENT** — `protokit targets buf BASIC
  coverage; defaults reflect Python-protobuf-developer
  ergonomics, not buf's defaults (see proto2-strict for opt-in
  proto2 strictness).` Pinned in `BUILTIN_PACKS` docstring +
  README Schema Linting section header. Resolves the KD-1-vs-
  26/26-headline latent tension by naming the bet explicitly:
  parity at COVERAGE, ergonomics at DEFAULTS. Per ce:review P1
  #2 (2026-05-22), avoids pinning a specific rule count — the
  prior "26 BASIC rules" phrasing was factually incorrect at
  U1+U2 when only 25 rules had shipped.
- **`proto2-strict` opt-in profile** (NEW; D6e KD-3 + KD-11)
  carrying ONE rule initially: `field/not-required`. Activate via
  `--profile proto2-strict` or pyproject
  `profile = ["default", "proto2-strict"]`. Distinct from the
  deferred `strict` profile (which targets style-strictness rules
  like COMMENT_* / ENUM_ZERO_VALUE_SUFFIX); do NOT consolidate per
  KD-3.
- **`field/not-required` rule** (`buf:FIELD_NOT_REQUIRED` parity;
  proto2-only) shipping in the `field` rule pack — the deferred
  D6d-U3 rule. ERROR severity in `proto2-strict` profile only;
  ZERO findings in `recommended` + `default` (D6e KD-5: proto2-
  specific strictness is opt-in per the inverted UX philosophy at
  KD-1). Group-typed required fields fire on the implicit
  lowercased field name per buf v1.69.0 (Phase 0 EV-3 binding).
- **NEW `field` rule pack** at `protokit.schema.lint.rules.field`
  — namespace anchor for future field-level proto2-strict rules
  per KD-11 (`field/no-group-syntax`, `field/no-explicit-default`,
  `field/packed-repeated-primitive`; none ship in D6e).
- **Parametrized CLI dedup test consolidation** at
  `tests/schema/lint/test_cli_rule_pack_dedup.py` — replaces the
  two per-flip files (`*_post_d6c.py`, `*_post_d6d.py`) with one
  parametrized test iterating over every `BUILTIN_PACKS` member.
  Promoted at the third near-copy-paste instance per
  [[shared-helper-third-instance-trigger]] (codified at U4 boundary
  as `near-copy-paste-third-instance-consolidation-trigger`).
  ~60 LOC vs ~360 LOC across the two prior files.

### Changed (behavior delta)

- **`file/syntax-specified` demoted ERROR → WARNING** in
  `recommended` + `default` profiles (D6e R4b per KD-2 pragmatic-
  not-dogmatic). The rule still surfaces the signal ("declare
  syntax explicitly so future readers don't have to guess proto2
  from descriptor shape") but does NOT fail CI on proto2 files by
  default. **Worst-case math by `--max-warnings` posture:**
  - **`--max-warnings` unset (default)**: pre-R4b exit 1 (ERROR
    present); post-R4b exit 0 — silent CI-pass regression if the
    rule was the sole load-bearing failure. Most dangerous case;
    re-promote per migration path #1 below.
  - **`--max-warnings 0`**: same exit code (1), but failure
    reclassified from error-bin to warning-bin (different formatter
    output + bin distribution). Not cosmetic.
  - **`--min-severity error`**: true zero impact.

### Pre-upgrade migration recipe

- Want explicit ERROR enforcement of `file/syntax-specified`?
  ```toml
  [tool.protokit.lint.severities]
  "file/syntax-specified" = "error"
  ```
- Want proto2-strict checks?
  ```toml
  [tool.protokit.lint]
  profile = ["default", "proto2-strict"]
  ```
- Want to demote `field/not-required` after opting in?
  ```toml
  [tool.protokit.lint.severities]
  "field/not-required" = "warning"
  ```
- Pin to 0.5.0 indefinitely? `pip install protokit==0.5.0`.

### Phase 0 EV-2 falsification (audit-trail note)

The brainstorm + plan originally framed a "documented extend-block
divergence" where buf would fire `FIELD_NOT_REQUIRED` on extend-
block `required` fields while protokit (whose engine walker does
not iterate `fd.extensions_by_name` or `Message.extensions_by_name`)
would not. **Phase 0 of U2 empirically falsified this premise**:
both buf v1.69.0 AND protokit's compiler reject `required`
extension fields at parse layer (`invalid cardinality: 2`). The
protobuf spec disallows LABEL_REQUIRED for extension fields; the
construct cannot be compiled, so no rule-level divergence exists.
**`field/not-required` ships with clean buf-parity** — no
asterisk in the headline, no four-site documentation, no
`_PARITY_EXCEPTIONS` entry, no walker-extension backlog. See the
ce:compound entry at
`docs/solutions/best-practices/phase-0-empirical-verification-falsifies-brainstorm-assumption-2026-05-22.md`
for the institutional lesson.

### Deferred to U3 + U4 (within D6e)

- **`package/no-import-cycle`** (26th buf BASIC rule) — U3.
- **Delivery boundary 0.5.0 → 0.6.0** including CHANGELOG fold,
  README "26 of 26 v1.69.0" numerator refresh, presence-ratchet
  additions, stale-text sweep — U4.
