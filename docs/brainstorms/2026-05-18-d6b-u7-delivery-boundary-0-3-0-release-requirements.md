# protokit-lint D6b U7 — delivery-boundary 0.2.0 → 0.3.0 release

**Status:** brainstorm (requirements). Next step: `/ce:plan`.
**Date:** 2026-05-18.
**Scope:** delivery boundary. Closes D6b by flipping the dormancy contracts shipped at U4b/U5/U6 into user-visible defaults + bumping the version + folding CHANGELOG-DRAFT staging into the released CHANGELOG + refreshing README + sweeping stale forward-looking text.
**Parent brainstorm:** `docs/brainstorms/2026-05-14-protokit-lint-delivery-6b-option-aware-and-multi-language-requirements.md` (R11-R12 + 0.2.0 → 0.3.0 bump).
**Predecessors shipped:** U1 (`include_source_info` parameter), U2 (`source_info_descriptors` + `leading_comment` helper), U3 (R6 5-rule deprecated-replacement family + CLI source-info wire-up), U4a (R7 engine pre-walk + 21 SHA-pinned `_buf_smoke/recorded/*.json` snapshots), U4b (R7 PACKAGE_SAME_* 7-rule family as DORMANT code), U5 (R9 `severities_unloaded_rule` category split + `_LINT_JSON_SCHEMA_VERSION` 0.2 → 0.3 + bump-contract docstring refinement), U6 (R7 end-to-end parity verification + multi-file harness extension + 3 ce:compound learnings). main HEAD = `0f09101`. Suite: 1905 passing + 7 skipped. 60 docs/solutions/ total.

## TL;DR

U7 ships the **0.3.0 delivery** — the user-visible release that closes D6b. The work is mechanically bounded (no new rule logic, no new test scenarios) but coordinates across multiple surfaces. Seven coupled edits ship as one atomic feat commit per established D6b pattern.

**Seven deliverables:**

1. **BUILTIN_PACKS registration of `package_same`** — flips R7 from dormant to default-on under `recommended` + `default` profiles. Single import + tuple-append edit in `src/protokit/schema/lint/rules/__init__.py`. Engine's idempotent `load_rule_pack` (verified at `engine.py:241-242` during U6) ensures U6's `--rule-pack=...package_same` flag in `test_parity_package_same.py` becomes a deliberate no-op — but per the dormancy-cleanup decision below, the flag is REMOVED rather than retained as documentation.

2. **Version bump 0.2.0 → 0.3.0** — `pyproject.toml` constant edit; `src/protokit/__init__.py` `__version__` constant if present. `_LINT_JSON_SCHEMA_VERSION` already bumped to `"0.3"` at U5 (no double-bump).

3. **CHANGELOG-DRAFT.md fold into CHANGELOG.md** — move the 3 staged entries (D6b U4b dormancy note + D6b U5 wire-format additive + D6b U6 parity gate + harness extension) into a single `### D6b — 0.3.0 (2026-05-18)` section under the existing pre-1.0-framed structure. Pre-1.0 plain framing per [[pre-1.0-version-bump-as-communication-contract]] — no `BREAKING:` prefix; the 0.2.0 → 0.3.0 bump IS the breaking-change signal. Enumerate additions + behavior changes + demotion paths per the existing D6a U10 precedent.

4. **README Schema Linting section refresh (targeted)** — update the rule table (add rows for R6's 5 deprecated-replacement rules + R7's 7 PACKAGE_SAME_* rules; bump rule counts; update buf BASIC parity claim from D6a's "5 packs / 17 rules" to "17 of 18 buf BASIC rules" with the `package/same-directory` deferred-to-D6c honest caveat); update profile descriptions to reflect default-on R7; document the `category="severities_unloaded_rule"` value in the `lint_json` shape reference; refresh BUILTIN_PACKS rule count. **No restructuring** — preserves the targeted-refresh scope per the U7 brainstorm decision.

5. **Presence-ratchet test for refined bump-contract docstring wording** — new test in `tests/test_builtin_lint_formatter.py` (or co-located with U5's bump-contract source) that asserts the closed-Literal-discriminator vs open-severity-ladder distinction in `_builtin_lint.py:243-249` docstring is preserved verbatim. Per the U5 plan's R11-related deferred item ("presence-ratchet test pinning the refined bump-contract docstring wording"). Modeled on D6a U10's prose-presence-ratchet pattern documented at [[presence-ratchet-test-pattern-for-prose-substrings]].

6. **Stale forward-looking text full sweep** — remove dormancy-window artifacts now that R7 is realized:
   - `src/protokit/schema/lint/cli.py` `--help` epilog: remove the R7 opt-in discovery line landed at U4b.
   - `tests/schema/lint/test_cli_package_same_e2e.py`: delete the `TestDormancyContract` class (R7 IS now registered; the contract is structurally re-validated by the rule-pack discovery + BUILTIN_PACKS membership tests).
   - `tests/parity/test_parity_package_same.py`: remove the `--rule-pack=protokit.schema.lint.rules.package_same` flag from the parity-test invocation (now a no-op; KD-4's retain-as-documentation framing is superseded by the full-sweep decision).
   - `src/protokit/schema/lint/rules/package_same.py`: module docstring + `RULES` tuple comment — replace "dormant code" / "not yet in BUILTIN_PACKS" prose with active framing.
   - `CHANGELOG-DRAFT.md`: empty to a header-only stub preserving the file's role for future units (D6c onward). Don't delete — the pattern + file path are referenced from [[dormant-code-changelog-draft-staging-delivery-boundary-2026-05-17]].
   - General grep sweep across `docs/`, `tests/`, `src/`: any remaining "deferred to U7" / "until U7" / "candidate for D6c" prose that's now realized gets updated to active framing.

7. **Public Surface DRAFT additions** — new rows in the README's Public Surface DRAFT table per the parent D6b brainstorm's R12: `CompileResult.source_locations` (IN — landed at U2), `_LintContextEmitMixin.leading_comment(path)` (IN — landed at U2), `_safe_for_findings` (INTERNAL — implementation detail), the new R6/R7 rule_ids enumerated as part of the existing rule-set row, `LintRuntimeWarning.category` Literal updated to include `severities_unloaded_rule` (5 values), `_LINT_JSON_SCHEMA_VERSION: "0.3"` row replaces the existing `"0.2"` row.

**Out of scope:**

- **`package/same-directory` (R8)** — the 18th buf BASIC rule. D6c per the parent brainstorm's explicit deferral. Honest caveat in CHANGELOG + README: "17 of 18 buf BASIC rules; package/same-directory deferred to D6c for its own architectural delivery (cross-file rule kind requires new ElementKind + LintLocation discriminant)."
- **`strict` profile** — D6c+ decision; D6a U8 deferral still stands.
- **R9b (per-rule disable/enable)** — D6c+ decision; needs real-demand evidence per U5 brainstorm.
- **New `docs/solutions/` entries** — U6's ce:compound captured 3 new learnings; U7 doesn't add more. The delivery-boundary unit is mechanical coordination, not novel-problem-solving.
- **New tests for R7 / R6 / R9 logic** — coverage is complete from prior units. U7 only adds the presence-ratchet test for the bump-contract docstring.
- **Migration guide for 0.3.0** — pre-1.0 stance per [[pre-1.0-version-bump-as-communication-contract]]: the version bump IS the communication. CHANGELOG enumerates the changes; users who want to opt out of the new R7 defaults can use `[severities]` overrides to demote per-rule.

## Problem Frame

After D6b U6 shipped (2026-05-18), all 7 implementation units of D6b (U1+U2+U3+U4a+U4b+U5+U6) are on `main`. R7 is operational as DORMANT code: importable, exercised via `--rule-pack` opt-in, NOT in `BUILTIN_PACKS`. The U6 parity gate empirically verified byte-parity with buf v1.69.0 across 21 snapshots; U4b's ~80 internal tests + the U6 ce:review-induced fix for `_truncate_values_payload`'s odd-count discipline complete the helper-correctness contract. R9 already shipped at U5 (category split + `_LINT_JSON_SCHEMA_VERSION` 0.2 → 0.3 + bump-contract docstring refinement).

The remaining gap is the **delivery-boundary work**: flip R7's default-on switch, bump the user-visible version, fold CHANGELOG-DRAFT staging into the released CHANGELOG, refresh README to reflect the new shipping state, and sweep the dormancy-window forward-looking text artifacts so the codebase reads as "this is what shipped" rather than "this is in flight."

**The cost of leaving the gap is asymmetric.** Each unit shipped under the dormancy contract carries forward-looking text (--help epilog lines, CHANGELOG-DRAFT staging entries, dormant-code module docstrings, the U6 parity test's `--rule-pack` flag) that becomes stale immediately when the BUILTIN_PACKS flip happens. Leaving the artifacts in place after the flip creates [[stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12]] debt: agents grepping for "is R7 enabled by default" see contradictory signals (`--help` says opt-in, BUILTIN_PACKS membership says default-on); contributors editing `package_same.py` see "dormant code" framing in the docstring even though it's the live production R7 family. The sweep is small (~6-8 sites) but high-leverage: it eliminates the source of future-contributor confusion.

**No alternative approach scored better.** This is the standard delivery-boundary pattern per [[delivery-boundary-unit-commit-composition]], validated across D2, D3, D5, D6a U10. The unit is mechanical-coordination-heavy by design; the brainstorm scope is product-level confirmation (CHANGELOG framing + README scope + sweep aggressiveness) rather than technical-design exploration.

## Requirements

### R31 — BUILTIN_PACKS registration (with required test updates)

Add `package_same` to the `BUILTIN_PACKS` tuple in `src/protokit/schema/lint/rules/__init__.py`. Add `from . import package_same` import (replacing any U4b-era `# noqa: F401` discard, if still present). After this edit:

- `protokit lint --profile recommended` fires R7 rules without `--rule-pack` flag.
- `protokit lint --profile default` likewise.
- `RULE_ID_MAP` at `tests/parity/conftest.py:190` (built from `BUILTIN_PACKS`) gains the 7 R7 entries.
- `LintEngine.load_rule_pack` (engine.py:241-242) remains idempotent — duplicate loads via U6's `--rule-pack` flag would be silent no-ops if the flag were retained, but per R36 the flag is removed.

**Required atomically-coupled test updates** (must land in the SAME commit as the BUILTIN_PACKS edit — verified at `/ce:plan` time these fail without them):

1. **`tests/schema/lint/test_builtin_packs.py:78-87`** — update the expected-tuple assertion to include `"protokit.schema.lint.rules.package_same"` as the 7th member. The test's diagnostic message ("Update the expected tuple in this test, Add a CHANGELOG entry per KD-9, Coordinate a major version bump") IS the KD-9 contract being satisfied at U7. This is non-optional: the test fails CI without it.

2. **NEW `tests/test_changelog_d6b_entry.py`** — mirror `tests/test_changelog_d6a_entry.py` exactly (substring ratchet for `"### D6b"` in `CHANGELOG.md`). Per the D6a U10 precedent's per-delivery KD-9 ratchet pattern. ~25 lines. Pinning the per-delivery presence-ratchet forward extends the discipline to D6c+ deliveries without re-litigating each time.

**Cold-import contract: NOT regressed.** Verified at `/ce:plan` time: `tests/schema/lint/test_cold_import_extended.py:57` lists `protokit.schema.lint.rules.package_same` as forbidden in the cold-import path. R31 does not regress this — the cold-import gate forbids loading `protokit.schema` from transitively loading `lint.rules`; the rules/__init__.py is only loaded when `lint.cli` is loaded, which the gate already excludes. R31 is cold-import-safe.

### R32 — Version bump 0.2.0 → 0.3.0

Single-line edit to `pyproject.toml:7` (`version = "0.2.0"` → `"0.3.0"`). **Verified at U7 brainstorm time (2026-05-18):** `pyproject.toml:7` is the SOLE `version` declaration; `src/protokit/__init__.py` has no `__version__` constant (`grep -rn "__version__" src/` returns zero matches). Do NOT introduce a derived `__version__` constant; if a future unit needs runtime version access, use `importlib.metadata.version("protokit")` (the existing pattern at `src/protokit/_cli_utils.py:42-61`).

**Runtime-version impact note**: `_get_protokit_version()` at `src/protokit/_cli_utils.py:42-61` uses `importlib.metadata.version("protokit")` — reads the INSTALLED package metadata, NOT pyproject.toml directly. Surfaces in (a) `protokit lint --version`, (b) SARIF `runs[0].tool.driver.version`. In dev checkouts (`pip install -e .[dev]`), the installed metadata is captured at install time and only re-reads from pyproject.toml on re-install. CI re-runs `pip install -e ...` fresh per build (no issue); local dev S6 verification requires re-running `pip install -e .[dev]` after the bump for the runtime version to reflect 0.3.0. Add this to U7's verification checklist.

Note: `_LINT_JSON_SCHEMA_VERSION` was already bumped 0.2 → 0.3 at U5. No double-bump.

### R33 — CHANGELOG-DRAFT.md fold into CHANGELOG.md (with pre-upgrade migration section per U4-plan commitment)

Move the 3 staged entries (D6b U4b + D6b U5 + D6b U6) from `CHANGELOG-DRAFT.md` into a single `### D6b — 0.3.0 (2026-05-18)` section in `CHANGELOG.md`. Use pre-1.0 plain framing per [[pre-1.0-version-bump-as-communication-contract]]: no `BREAKING:` prefix; the version bump IS the breaking-change signal.

**Strategic lede (matches D6a U10 precedent at `CHANGELOG.md:437-444`)** — open the 0.3.0 section with 2 sentences positioning the strategic completion BEFORE the enumerated Added bullets:

> D6b adds the first option-aware rules (R6 deprecated-replacement family) + cross-language buf-BASIC parity (R7 PACKAGE_SAME_* family), bringing `protokit lint` to **17 of 18 buf BASIC rules**. The 18th (`package/same-directory`) defers to D6c — its cross-file rule kind requires new ElementKind + LintLocation discriminant work scoped for its own architectural delivery.

Section content (high-level — `/ce:plan` resolves exact wording):

- **Added**:
  - R6 5-rule deprecated-replacement family (`options/deprecated-{enum,enum-value,field,message,method}-must-have-replacement-comment`) — `warning` severity, `default` profile only. First option-aware rules + first leading-comment-introspection consumer.
  - R7 7-rule PACKAGE_SAME_* family (`package/same-{go-package,java-package,csharp-namespace,php-namespace,ruby-package,swift-prefix,java-multiple-files}`) — `error` severity, `recommended` + `default` profiles. Cross-language buf-BASIC parity (17 of 18 rules; `package/same-directory` deferred to D6c).
  - R9 `severities_unloaded_rule` category value on `LintRuntimeWarning.category` Literal (5th value). Programmatic consumers can switch on category instead of message substring.
  - Multi-file parity harness extension at `tests/parity/conftest.py` — `BufFinding` NamedTuple + 3 helpers reusable by future multi-file rule families.
  - Empirical parity gate at `tests/parity/test_parity_package_same.py` — byte-parity verification against 21 SHA-pinned buf v1.69.0 NDJSON snapshots; runs in required `test` CI job.

- **Wire-format**:
  - `lint_json.schema_version` + `lint_sarif.runs[0].properties.lint_schema_version` bumped `"0.2"` → `"0.3"` (per the closed-Literal-discriminator bump-contract in `_builtin_lint.py:243-249`).

- **Behavior changes** (defaults; demotable):
  - R6 family fires as `warning` on `default` profile (NOT `recommended`). Multi-language teams using `--profile recommended` (the buf-parity profile) see ZERO new R6 findings. Teams using `--profile default` see warnings on `option deprecated = true` fields/methods/enums without a corresponding `[replaced-by: <new_thing>]` leading comment.
  - R7 family fires as `error` on `recommended` + `default` profiles. **Multi-language teams will see NEW error-severity findings when option values disagree across files in a package** (e.g., `go_package`, `java_package`, `csharp_namespace` differing across files in the same proto package). This is the buf BASIC parity behavior; it surfaces real cross-language config inconsistency.

- **Pre-upgrade migration recipe (per U4-plan commitment, matches D6a U10 precedent at `CHANGELOG.md:504-536`)**:

  Cross-language teams whose CI currently passes on protokit 0.2.0 with `--profile recommended` and whose protos have cross-file option disagreement will see RED CI on first 0.3.0 invocation. Four numbered demotion paths, ranked by preference:

  **1. Fix the disagreement (recommended).** R7 fires because option values differ across files in the same package — the buf v1.69.0 parity behavior treats this as a correctness signal. Decide a canonical value per `option_attr` per package; update outlier files to match.

  **2. Demote a specific R7 rule to `warning` (per-rule escape hatch).** Add to `pyproject.toml`:

  ```toml
  [tool.protokit.lint.severities]
  "package/same-go-package" = "warning"
  ```

  Multiple keys compose. Demoted rules still report findings but do not fail CI (under default `--min-severity error`). Demote to `info` for fully advisory output.

  **3. Disable a specific R7 rule** (sharper escape hatch, available when the rule is genuinely not applicable to the team's setup):

  ```toml
  [tool.protokit.lint.severities]
  "package/same-go-package" = "off"
  ```

  Use sparingly — disabled rules are invisible to downstream consumers of `lint_json`/`lint_sarif` output. Prefer demotion to `warning` so findings stay visible.

  **4. Pin to the prior minor version (deferral fallback)**:

  ```toml
  # pyproject.toml or requirements.txt
  "protokit~=0.2.0"
  ```

  Reserves time to address R7 findings on the team's schedule. Re-evaluate at each 0.3.x patch release. Not recommended long-term: protokit 0.2.x stops receiving D6c+ rule additions.

  **Upgrade-notes triage recipe** (per the D6a U10 precedent shape):

  ```
  1. Run `protokit lint --profile recommended <inputs>` against your protos.
  2. If exit code 0: no migration needed; the bump is clean.
  3. If R7 findings appear: choose one of the 4 demotion paths above per rule.
  4. If R6 findings appear (default profile only): add `[replaced-by: <X>]` comments to deprecated fields/methods/enums, OR demote `options/deprecated-*` rules via `[severities]` (warning → info).
  5. Re-run after applying demotion/fix; commit the updated pyproject.toml or proto fix.
  ```

- **Consumer migration (Python API)**:
  - Consumers switching on `LintRuntimeWarning.category` should re-check switch statements for exhaustiveness — the 5th value `"severities_unloaded_rule"` is the new closed-Literal addition. Per the bump-contract docstring at `_builtin_lint.py:243-270`, this is exactly the consumer-action signal the `schema_version` 0.2 → 0.3 bump communicates.
  - `LintRuntimeWarning.category` IS a closed Literal discriminator: additions trigger `schema_version` minor bumps; consumer switch statements should be exhaustive. Contrast with `LintSeverity` ordering, which is an open ladder (additions do NOT trigger bumps).

- **Deferred to D6c**: `package/same-directory` (R8 — 18th buf BASIC rule; requires new ElementKind for cross-file rules); R6 promotion to `error`; `strict` profile rule enumeration; per-rule disable/enable (R9b).

### R34 — README Schema Linting section refresh (targeted)

**Strategic positioning note (matches D6a U10 lede)**: the README's Schema Linting section intro paragraph should be updated to surface the 17-of-18 buf BASIC parity claim at the top — not buried in the rule table. Recommend a 1-2 sentence update to the existing intro (don't add a new section): "**As of 0.3.0, protokit lint covers 17 of 18 buf BASIC rules** (the 18th, `package/same-directory`, defers to D6c)."

Update sites:

- **Rule table** — README.md:535-538 currently reads `recommended | 17 | Buf BASIC parity. The full D6a rule library — naming (9), enum (2), imports (3), package (2), file (1)` with **zero R6 entries** (R6 was shipped at U3 with deferral-to-U7 README updates). U7's R34 is the FIRST-TIME README inclusion for R6 + R7 rule_ids, not a refresh. **Rule count math (corrected)**: `recommended` = 17 (D6a) + 7 (R7 PACKAGE_SAME_*) = **24 rules**; `default` = 24 (recommended) + 5 (R6 deprecated-replacement, default-only) = **29 rules**. No overlaps between R6/R7 rule_ids and prior D6a namespaces (R6 = `options/deprecated-*`, R7 = `package/same-*`; D6a uses `naming/*`, `enum/*`, `imports/*`, `package/*`, `file/*`). Source R6 rule_ids + short descriptions from `src/protokit/schema/lint/rules/options/deprecated_replacement.py` at `/ce:plan` time.

- **Default-profile row REWRITE** — README.md:536 currently reads `default | 17 | Forward-placeholder for the D6b option-aware differentiator. Structurally equal to recommended in 0.2.0`. This is FALSE post-U7 (R6 splits default from recommended). REPLACE with active framing: `default | 29 | Buf BASIC parity (recommended's 24 rules) + R6 deprecated-replacement family (5 warning-severity option-aware rules).` Do not preserve the forward-placeholder framing.

- **Profile descriptions** — reflect default-on R7 (`recommended` + `default` now include the 7 PACKAGE_SAME_*); R6 in `default` only (not `recommended`). Buf BASIC parity claim in the `recommended` row: "17 of 18 buf BASIC rules; the 18th (`package/same-directory`) defers to D6c."

- **lint_json shape reference** — update the `runtime_warnings[].category` enumeration to list 5 values (add `"severities_unloaded_rule"`). Mark as CLOSED DISCRIMINATOR per the contract at `_builtin_lint.py:243-270`.

- **Schema linting Quick Start** — add a one-line note about multi-language teams (PACKAGE_SAME_* family fires under `recommended`; per-rule demotion via `[severities]` for known-no-package-option teams). Optionally mention the migration recipe location ("See CHANGELOG.md `### D6b — 0.3.0` 'Pre-upgrade migration recipe' for the demotion syntax").

No restructuring. No new sections. No worked-example rewrites (the R6 worked-example in the README from U3 stands; no new examples needed).

**Pre-edit verification at `/ce:plan` time**: enumerate buf BASIC rule_ids at `_BUF_PARITY_PIN` v1.69.0 (`buf config ls-lint-rules --config '{version: v1, lint: {use: [BASIC]}}'` or equivalent) and confirm the 17/18 split. If buf BASIC actually has 17 or 19 rules at v1.69.0, update the README claim accordingly.

### R35 — Presence-ratchet test for refined bump-contract docstring

Add a test that asserts the closed-Literal-discriminator-vs-open-severity-ladder distinction in `src/protokit/formatters/_builtin_lint.py:243-249` docstring is preserved verbatim. Locate in `tests/test_builtin_lint_formatter.py` next to existing prose-presence-ratchet tests (per D6a U10 precedent at [[presence-ratchet-test-pattern-for-prose-substrings]]).

The test should:

- Read `_builtin_lint.py` source via `Path(...).read_text()` (NOT runtime introspection — the docstring may be `__doc__`-attribute-mutated by future tooling).
- Assert presence of specific substrings characterizing the closed-Literal contract (e.g., "closed Literal discriminator" + "additive enum-value additions DO bump" + "open severity ladder" — `/ce:plan` resolves exact substrings).
- Fail with a clear message naming the docstring file + line range + the missing substring.

**Substring selection criterion (pinned at brainstorm level, not deferred to `/ce:plan`)**: each chosen substring MUST be (a) **load-bearing for the closed-Literal-vs-open-severity-ladder distinction** — paraphrasing that preserves the contract must keep all substrings; rewording that drops the contract must drop at least one; AND (b) **at least one substring pins the DIRECTIONAL CONTRACT** (e.g., "DO bump" or "requires bump" — NOT just framing nouns like "closed Literal" or "open ladder"). Test the criterion at `/ce:plan` time by drafting two adversarial paraphrases of the docstring: one preserving the contract semantically while changing wording (should PASS the ratchet) + one dropping the bump-required clause while preserving framing nouns (should FAIL the ratchet). If both paraphrases produce the same test result, the substring set is mis-calibrated.

**Note on line range**: U7 brainstorm cites `_builtin_lint.py:243-249`; verified at HEAD the docstring actually spans `_builtin_lint.py:243-270`. `/ce:plan` reads the source at HEAD to anchor the exact byte range; the `243-249` figure in this brainstorm is approximate.

Catches accidental docstring rewrites that drop the bump-contract distinction (the U5 refinement is load-bearing for all future closed-Literal additions, including D6c's category extensions).

### R36 — Stale forward-looking text full sweep (10 concrete sites + explicit binary scope rule)

**Binary scope rule** (load-bearing — `/ce:plan` verifies via `git diff --stat`): edit ONLY files matching:

- `src/**/*.py` (production code + docstrings)
- `tests/**/*.py` (test code + docstrings explaining current runtime behavior)
- `README.md`, `CHANGELOG.md`, `CHANGELOG-DRAFT.md`

**DO NOT EDIT** any file under `docs/brainstorms/`, `docs/plans/`, or `docs/solutions/` — these are historical artifacts; their forward-looking phrasing is the audit trail of past deliberation. Cross-doc references that become factually stale post-U7 are acceptable in historical artifacts; rewriting them erases the unit's deliberation history. Verification: run `git diff --stat -- docs/brainstorms/ docs/plans/ docs/solutions/` after the sweep; if non-empty, revert those changes before commit. (Future doc-polish work that updates cross-references is a separate D6c+ unit, not U7's scope.)

**10 concrete sites** (verified at U7 brainstorm time via `git grep -n 'dormant\|until U7\|deferred to U7\|post-U7\|U7 flip\|not yet in BUILTIN_PACKS' src/ tests/`):

1. **`src/protokit/schema/lint/cli.py` `--help` epilog** — remove the R7 opt-in discovery line landed at U4b. Verify by grepping for "rule-pack" / "package_same" / "opt-in" in the `--help` output text.

2. **`tests/schema/lint/test_cli_package_same_e2e.py` `TestDormancyContract` class** — delete (`test_recommended_profile_no_r7_findings_when_dormant` + `test_default_profile_no_r7_findings_when_dormant`). R7's BUILTIN_PACKS membership is the structural assertion now; the dormancy contract is no longer a meaningful invariant.

3. **`tests/schema/lint/test_cli_package_same_e2e.py` `TestRulePackOptIn` class** (NEW site per adversarial review). Currently the class tests `--rule-pack=protokit.schema.lint.rules.package_same` as an OPT-IN to otherwise-dormant rules. Post-flip, the flag is a redundant explicit load that exercises `LintEngine.load_rule_pack`'s idempotency contract. **Disposition**: rename to `TestRulePackExplicitLoadIsIdempotent` + update class docstring + each test docstring to reflect that the flag now exercises idempotency, NOT opt-in. Preserves regression value for the idempotent-load contract. Alternative considered: delete (lose idempotency regression coverage); rejected because the idempotency claim in KD-4/post-U7 framing IS load-bearing for the flag-removal in site 4 below.

4. **`tests/parity/test_parity_package_same.py` `--rule-pack` flag removal + module docstring rewrite** — remove `rule_pack=_RULE_PACK` argument from the `run_protokit_lint_multi_file(...)` call in `test_parity_byte_matches_recorded_snapshot`; remove the module-level `_RULE_PACK` constant. Additionally REWRITE module docstring at lines 16-22 ("Post-U7 contract (KD-4): when U7 flips BUILTIN_PACKS ... The flag is retained for documentation value...") — delete the entire Post-U7 contract paragraph (the flag is gone per KD-3 supersedure); replace with a one-liner noting R7 loads via BUILTIN_PACKS as of 0.3.0. Also rewrite `_build_package_same_rule_id_map` docstring at lines 83-90 to past-tense framing.

5. **`tests/parity/conftest.py:171-199` `_build_package_same_proto_to_buf` docstring** — currently reads "R7 is dormant (not in BUILTIN_PACKS) until U7 ... After U7's BUILTIN_PACKS flip, `_PACKAGE_SAME_PROTO_TO_BUF` becomes a subset of `RULE_ID_MAP` and could be derived from it; until then, the dedicated walk keeps U6's invocation path independent of the BUILTIN_PACKS sequencing." Rewrite to historical-fact framing: "Until U7, R7 was dormant; this dedicated walk kept U6's invocation path independent of BUILTIN_PACKS sequencing. Post-U7, `_PACKAGE_SAME_PROTO_TO_BUF` is a subset of `RULE_ID_MAP` but retained as a dedicated map for diagnostic locality in `assert_parity_multi_file`." (Or, per the R38 decision below, REPLACE the function entirely with `RULE_ID_MAP`-derived filter.)

6. **`src/protokit/schema/lint/rules/package_same.py` module docstring + `RULES` tuple comment** — replace "dormant code" / "not yet in BUILTIN_PACKS" / "deferred to U7" prose with active framing ("R7 PACKAGE_SAME_* family — cross-language namespace consistency rules, default-on under `recommended` + `default` profiles as of 0.3.0").

7. **`src/protokit/schema/lint/rules/__init__.py:80-94` multi-paragraph dormancy commentary** — the "It is DELIBERATELY NOT in BUILTIN_PACKS below — registration is deferred to U7 ... dormant-by-default: dormant code is the explicit opt-in pattern this delivery uses to ship R7 without auto-failing every pull-from-main between U4b and U7" block. Replace with past-tense framing acknowledging the U4b→U7 dormancy window was the intentional shipping pattern AND noting R31 closed it: "R7 was shipped dormant at U4b (importable via `--rule-pack` opt-in, NOT in `BUILTIN_PACKS`) to decouple rule-development cadence from CI-breakage timing. U7 registered package_same in `BUILTIN_PACKS` after U6's empirical parity gate validated byte-parity with buf v1.69.0."

8. **`src/protokit/schema/lint/engine.py:519-526` deferred-import docstring** — the "Once U7 registers package_same in BUILTIN_PACKS, the package_same module loads at engine-init time anyway, so this deferred import becomes a no-op" framing. Rewrite to past-tense: "Until U7, the package_same module was loaded only on `--rule-pack` opt-in; since U7 added it to BUILTIN_PACKS, the deferred import is a realized no-op. The lazy-import pattern is retained for cold-import contract compliance (see `tests/schema/lint/test_cold_import_extended.py`)."

9. **`CHANGELOG-DRAFT.md` empty-to-stub** — preserve the file with just the framing prose explaining the staging mechanism for future D6c+ units; delete the D6b U4b + U5 + U6 staged sections (folded into CHANGELOG.md via R33). KD-4 captures this decision. The stub MUST NOT add new forward-looking text about D6c (it's a passive staging container, not a forecasting doc).

10. **Verification grep** — after sites 1-9, run `git grep -n 'dormant\|until U7\|deferred to U7\|post-U7\|U7 flip\|not yet in BUILTIN_PACKS' src/ tests/ -- ':!**/test_changelog*'` (excludes the changelog-presence-ratchet tests which legitimately mention these terms in test names). Any residual hits get reviewed individually; if they're active code or docstring contracts, update; if they're regression-test names or commit-message references, leave.

### R37 — Public Surface DRAFT additions in README

Add or update rows in the existing Public Surface DRAFT table per the parent D6b brainstorm's R12. **Note**: the parent D6b brainstorm has an internal contradiction on `CompileResult.source_locations` classification — R6b says INTERNAL (per security-lens rationale); R12 says IN. Promoted to a Resolve-Before-Planning item in Outstanding Questions below; `/ce:plan` resolves via parent brainstorm intent audit + codebase verification.

Row updates:

- `CompileResult.source_locations` (**classification TBD per Resolve-Before-Planning question**; landed at U2)
- `_LintContextEmitMixin.leading_comment(path)` (IN — landed at U2)
- `_safe_for_findings` (**INTERNAL — pending verification of no external callers per Outstanding Questions**; landed at U2)
- R6 rule_ids enumerated within the existing rule-set row (5 new rule_ids)
- R7 rule_ids enumerated within the existing rule-set row (7 new rule_ids)
- **`LintRuntimeWarning.category`**: update row format from `category Literal` to **`category: Literal[<5 values enumerated>]` — CLOSED DISCRIMINATOR**. Additions to this Literal trigger `_LINT_JSON_SCHEMA_VERSION` minor bump per the bump-contract at `_builtin_lint.py:243-270`. Distinguish from `LintSeverity` ordering which is an open ladder (additions do NOT trigger bumps). Pinning the TYPE-contract (closed-discriminator) — not just the value count (4→5) — makes the bump-trigger structurally visible in the user-facing Public Surface DRAFT, complementing R35's docstring-presence-ratchet at the source layer.
- `_LINT_JSON_SCHEMA_VERSION` row: update from `"0.2"` to `"0.3"`

## Success Criteria

- **S1. 0.3.0 ships clean.** After the U7 feat commit lands on `main`, `pyproject.toml` reads `version = "0.3.0"`; `CHANGELOG.md` has a `### D6b — 0.3.0` section enumerating R6 + R7 + R9 + parity-gate additions; `CHANGELOG-DRAFT.md` is an empty stub.
- **S2. R7 fires default-on.** `pytest tests/schema/lint/test_cli_package_same_e2e.py` (the U4b/U6 e2e tests, with `TestDormancyContract` removed per R36) passes all R7 assertions without `--rule-pack=...` arguments. `protokit lint --profile recommended <fixture-with-disagreement>` produces R7 findings.
- **S3. Suite stays green.** `pytest tests/` count grows by ~5 (R35 presence-ratchet test + any minor invariant additions for the active-contract framing). All 1905 prior tests + new R35 test pass. Ruff + mypy gated paths clean.
- **S4. Parity gate continues passing.** `pytest tests/parity/test_parity_package_same.py` 27 tests still pass after R36's `--rule-pack` flag removal (the no-op behavior is structurally verified by the engine's idempotent `load_rule_pack`; the empirically-validated parity contract is unchanged).
- **S5. README reads as 0.3.0-shipped.** No "dormant" / "deferred to U7" / "opt-in via `--rule-pack`" prose anywhere in the README's Schema Linting section. Rule table reflects 17-of-18 buf BASIC parity claim with the `package/same-directory` honest caveat.
- **S6. Presence-ratchet catches docstring drift.** A deliberate `sed` edit to remove "closed Literal discriminator" from `_builtin_lint.py:243-270` causes `pytest tests/test_builtin_lint_formatter.py::test_bump_contract_docstring_preserves_closed_literal_distinction` (R35) to fail with a clear diagnostic.
- **S7. User-journey: multi-language team can adopt 0.3.0 without leaving CHANGELOG.md.** A multi-language team upgrading 0.2.0 → 0.3.0 with cross-file `go_package` / `java_package` disagreement can either (a) fix the disagreement guided by the CHANGELOG `Behavior changes` content + rule docstrings, OR (b) demote one or more R7 rules via a TOML snippet copy-pasted DIRECTLY from the CHANGELOG `Pre-upgrade migration recipe` section — without grepping documentation outside CHANGELOG.md. Testable by a dry-run review of the CHANGELOG diff before U7's feat commit lands: the demotion recipe must be self-contained.

## Post-Merge Steps

These items are explicitly OUTSIDE U7's feat-commit scope per KD-6 (memory artifacts live outside the repo; commit covers in-repo changes only). They are downstream maintenance to perform after U7 fast-forward-merges to main, NOT gates on U7 landing.

- **MEMORY.md + project_state.md update**: refresh the auto-loaded hook to reflect "D6b complete; 0.3.0 shipped; next delivery D6c". Carries forward the U6-shipped state with the new HEAD SHA + suite count + docs/solutions count + the dormancy-window-closed state for D6c-relevant carry-forward facts.
- **D6c brainstorm kickoff**: the next planned brainstorm is D6b's successor delivery (R8 `package/same-directory` + `strict` profile rule enumeration + R9b disable/enable). Not blocking on U7 but worth tracking as the next compound-engineering cycle entry-point.

## Scope Boundaries

- **No new rule logic.** U7 is delivery-boundary coordination only. Any new rule decisions (R8 `package/same-directory`, `strict` profile rules, R9b disable/enable) are explicitly D6c+ scope.
- **No new test scenarios for R6 / R7 / R9 behavior.** Coverage is complete from prior units. The only new test U7 adds is R35's docstring presence-ratchet.
- **No `docs/solutions/` additions.** U6's ce:compound captured the substantive learnings; U7 doesn't surface novel patterns (delivery-boundary mechanics are well-trodden via D2/D3/D5/D6a U10 precedent).
- **No migration guide.** Pre-1.0 stance per [[pre-1.0-version-bump-as-communication-contract]] — the version bump + CHANGELOG IS the migration communication. Per-rule severity demotion via `[severities]` is the user's escape hatch.
- **No README restructuring.** Targeted refresh only (R34 scope). Worked-example rewrites + multi-language migration tutorial defer to a future "documentation polish" pass after user feedback.
- **No revisiting of prior brainstorm decisions.** U1-U6's brainstorms + plans are historical artifacts. R36's stale-text sweep does NOT rewrite their content; it only updates active code + active prose where the dormancy framing is now misleading.

### Deferred to Separate Tasks

- **D6c — `package/same-directory` (R8) + cross-file rule kind** — separate brainstorm + plan when D6c begins.
- **D6c — `strict` profile rule enumeration** — separate brainstorm scoped to which strict-only rules ship.
- **D6c — R9b per-rule disable/enable** — separate brainstorm; needs real-demand evidence per U5's brainstorm scope discussion.
- **MEMORY.md project_state.md update for D6b-complete state** — post-merge maintenance; tracked at S7 but not in-scope for U7's feat commit.

## Key Decisions

### KD-1. Pre-1.0 plain CHANGELOG framing (matches D6a U10 0.2.0 precedent)

**Decision:** `### D6b — 0.3.0 (2026-05-18)` section in CHANGELOG.md uses plain pre-1.0 framing. No `BREAKING:` prefix. Enumerate additions + behavior changes + demotion paths. Honest "multi-language teams: parity layer of buf-BASIC migration is unblocked" framing in the prose; the strategic claim ("17 of 18 buf BASIC rules") is documented in the Added section's first bullet, not as a headline statement.

**Why?** Pre-1.0 communication contract per [[pre-1.0-version-bump-as-communication-contract]]: the version bump IS the breaking-change signal; explicit `BREAKING:` prefixes are reserved for post-1.0 SemVer compliance. Matches the D6a U10 0.2.0 precedent (the immediate predecessor 0.X.0 release). Lower carrying-cost framing than the "major-release" alternative (no marketing prose to maintain) without losing the strategic communication.

### KD-2. Targeted README refresh (Schema Linting section + rule table + profile descriptions only)

**Decision:** R34's scope is the existing Schema Linting section + rule table + profile descriptions + lint_json shape reference + BUILTIN_PACKS rule count. No restructuring. No multi-language migration tutorial. No worked-example rewrites (R6 example from U3 stands).

**Why?** Targeted refresh has lower carry-cost vs full Schema Linting rewrite. The strategic completion (17-of-18 parity, first option-aware rules) is communicated via CHANGELOG-section content + rule-table entries; users tracking the project get the signal. A full restructure expands the section's word count + creates more sweep maintenance for D6c+ — out-of-proportion for a delivery-boundary unit. Reserve restructure-level changes for a dedicated "documentation polish" pass after 0.3.0 user feedback.

### KD-3. Full dormancy-window artifact sweep (no retain-as-documentation framing)

**Decision:** R36 removes ALL dormancy artifacts: `--rule-pack` flag in U6's parity test, `--help` epilog R7 opt-in line, `TestDormancyContract` class in `test_cli_package_same_e2e.py`, "dormant code" / "not yet in BUILTIN_PACKS" prose in `package_same.py`, CHANGELOG-DRAFT staged sections (empty to stub).

**Why?** Per [[stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12]] discipline: forward-looking text in active code + active CLI prose creates sweep debt + agent-confusion signal. The U6 KD-4's "retain as documentation value" framing for the `--rule-pack` flag was load-bearing during the dormancy window (it explicitly named the scope when scope was non-default); post-flip, the scope IS default and the flag is redundant noise. Full sweep eliminates the source of future-contributor confusion (the `--help` epilog said "opt-in"; BUILTIN_PACKS membership says "default-on"; one of those is now wrong).

### KD-4. CHANGELOG-DRAFT.md kept as empty stub (not deleted)

**Decision:** R36 empties `CHANGELOG-DRAFT.md` to a header-only stub explaining the staging mechanism. Don't delete the file.

**Why?** The dormant-code staging pattern per [[dormant-code-changelog-draft-staging-delivery-boundary-2026-05-17]] references this file by path. D6c onward will need it again for its own dormancy-window content; deleting + recreating loses the file-path-stability signal. Empty stub preserves the pattern's discoverability without carrying obsolete content.

### KD-5. Presence-ratchet test reads source via `Path.read_text`, not runtime introspection

**Decision:** R35 implements via filesystem read of `_builtin_lint.py` + substring assertion, matching D6a U10's prose-presence-ratchet pattern at [[presence-ratchet-test-pattern-for-prose-substrings]].

**Why?** Runtime `__doc__` introspection can be subverted by `inspect.cleandoc` normalization OR by future tooling that mutates `__doc__` attributes (e.g., `functools.wraps`, `typing.get_type_hints` indirection). The source-read pattern pins the literal bytes in the source file, which is the authoritative artifact for code-review + git-blame + IDE-jump-to-definition flows. Higher confidence + lower flakiness than runtime introspection.

### KD-6. No memory update inside U7's feat commit

**Decision:** `MEMORY.md` + `project_state.md` updates documenting "D6b complete; 0.3.0 shipped" are POST-MERGE maintenance, not part of U7's feat commit.

**Why?** Memory artifacts live outside the repo (in `~/.claude/projects/.../memory/`). U7's feat commit covers in-repo changes only. The memory update can happen as a separate explicit step after fast-forward merge (matching the U6 precedent where memory was updated post-merge per user direction).

## Dependencies / Assumptions

- **`LintEngine.load_rule_pack` is idempotent by module name.** Verified at HEAD (`engine.py:241-242`: `if module.__name__ in self._loaded_module_names: return`). R36's `--rule-pack` flag removal from U6's parity test relies on this — the no-flag invocation will load `package_same` via BUILTIN_PACKS; redundant loads (which won't happen post-flag-removal) would be silent no-ops.

- **`pyproject.toml` is the canonical version source-of-truth.** Verify during `/ce:plan` whether `src/protokit/__init__.py` has a `__version__` constant that's derived from pyproject or independent. If independent, both edits go in U7; if derived, only pyproject changes.

- **CHANGELOG-DRAFT.md has 3 staged sections.** Verified at HEAD: D6b U4b dormancy note + D6b U5 wire-format additive + D6b U6 parity gate + harness extension entries. All three fold into the 0.3.0 section.

- **U6 ce:compound's 3 new learnings are correctly cross-referenced.** Verified at HEAD: `empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18`, `truncation-guard-odd-count-discipline-for-doubled-escape-pairs-2026-05-18`, `module-import-time-fixture-mapping-fail-loud-blast-radius-2026-05-18`. U7 doesn't modify these; they were captured at U6's ce:compound.

- **The R6 family from U3 + R7 family from U4b + R9 category split from U5 are all functionally complete.** No new behavior changes in U7. Verify at `/ce:plan` time that R6 + R7 + R9 internal tests + e2e tests all pass at HEAD; if any are skipped or xfail, U7's scope expands to address them before the BUILTIN_PACKS flip.

- **The 21 `_buf_smoke/recorded/*.json` snapshots remain SHA-pinned.** Verified by `tests/schema/lint/test_buf_smoke_recorded_checksums.py` at HEAD. R36's `--rule-pack` removal does NOT affect snapshot validity; the parity contract is unchanged.

- **`tests/parity/conftest.py:6-9` docstring was corrected at U6 ce:review.** Verified at HEAD: the stale "default `pytest tests/` skips the entire tree" claim was replaced with "the marker is documentary". No further docstring sweep needed in `tests/parity/conftest.py`.

## Outstanding Questions

### Resolve Before Planning

- **[Affects R37 + parent D6b brainstorm][Coherence] CompileResult.source_locations classification: IN vs INTERNAL.** Parent D6b brainstorm (`docs/brainstorms/2026-05-14-protokit-lint-delivery-6b-option-aware-and-multi-language-requirements.md`) contains an INTERNAL CONTRADICTION:
  - **R6b (line 73)**: "Public Surface DRAFT classification: `CompileResult.source_locations` enters as **INTERNAL** (not IN), per security-lens concern..."
  - **Non-Goals (line 182)**: "**`CompileResult.source_locations` enters Public Surface DRAFT as INTERNAL**, not IN."
  - **R12 (line 128)**: "New rows: `CompileResult.source_locations` (IN)..."
  
  U7's R37 originally propagated R12's IN framing. `/ce:plan` MUST audit the parent brainstorm to determine final intent (lean: **INTERNAL** per the R6b + Non-Goals consensus; R12 appears to be a stale enumeration line not updated when R6b decided INTERNAL). After resolution, optionally retroactively-fix the parent brainstorm's R12 line to reflect the actual decision — but per R36's binary scope rule, do NOT rewrite the parent brainstorm's content under U7's feat commit. The fix-the-parent step is a separate documentation-polish unit OR leave the contradiction as a historical artifact and just note the resolution in U7's plan-of-record.

- **[Affects R37][Stability decision] `_safe_for_findings` INTERNAL classification verification.** R37 lists `_safe_for_findings` as INTERNAL, signaling consumers it is an implementation detail. Verify at `/ce:plan` time that no external callers exist in `tests/` or downstream usage (`grep -rn "_safe_for_findings" tests/ src/ docs/`); if any test imports it directly, document the intended stability posture (INTERNAL-but-test-visible vs INTERNAL-and-test-duplicated). Once in the Public Surface DRAFT table, reverting from INTERNAL requires a separate update pass — pin this at brainstorm/plan time, not at first-consumer time.

### Deferred to Planning

- **[Affects R34][Technical]** Exact wording for the "17 of 18 buf BASIC rules" claim — needs to honestly caveat `package/same-directory` as D6c without overpromising D6c's timeline. Lean (folded into R33's strategic lede + R34's intro paragraph already): "17 of 18 buf BASIC rules; the 18th (`package/same-directory`) defers to D6c due to its cross-file rule-kind architectural requirements" — concrete + honest about why it's not in 0.3.0 yet. **Pre-edit verification**: enumerate buf BASIC rule_ids at `_BUF_PARITY_PIN` v1.69.0 (`buf config ls-lint-rules --config '{version: v1, lint: {use: [BASIC]}}'` or equivalent) and confirm the 17/18 split before the README claim lands.

- **[Affects R37][Technical]** Exact placement + format of new Public Surface DRAFT rows in README. Existing table structure pinned at D6a U10; new rows extend the same table. `/ce:plan` resolves column widths + ordering.

- **[Affects R33][Optional]** Whether to also link from the CHANGELOG 0.3.0 section to the 3 new docs/solutions/ learnings from U6's ce:compound. Lean: NO — CHANGELOG is user-facing release notes; docs/solutions/ is internal institutional knowledge. Mixing surfaces would dilute both.

- **[Affects KD-3 + future D6c units][Forward pattern]** Should U7 explicitly invalidate U6 KD-4's "retain-as-documentation" framing AS A FORWARD PATTERN for D6c+ dormant-code units, or defer the meta-decision? KD-3 makes the right tactical call for U7 but leaves the precedent ambiguous. **Lean: defer to D6c's first dormant-code unit** — adding a forward-pattern decision in U7 over-scopes the brainstorm (the decision needs ≥2 specimens to design against). When D6c's first dormant unit lands, it can either re-litigate or explicitly invalidate KD-4 with a fresh decision based on the realized U6+U7 cycle's lessons.

- **[Affects R31 follow-up][Code-health debt]** After R31's flip, the local rule-id derivation in `tests/parity/conftest.py:171-199` (`_build_package_same_proto_to_buf`) + `tests/parity/test_parity_package_same.py:83-120` (`_build_package_same_rule_id_map`) becomes redundant with `RULE_ID_MAP` (which now includes R7 via BUILTIN_PACKS). Two options: **(a) consolidate at U7** — replace the dedicated walks with `RULE_ID_MAP`-filter derivations; **(b) defer to D6c** — preserve U6's deliberate-isolation discipline; add a comment update marking the duplication as historical-rationale. **Lean: (b) defer to D6c** — preserves U6's invocation-path independence semantic + keeps U7 mechanical-coordination-only per stated scope boundaries. The R36 docstring-rewrite already addresses the prose-staleness aspect; the structural consolidation can wait. If `/ce:plan` reveals an unexpected coupling, escalate to KD-7.

## Next Steps

`-> /ce:plan` for structured implementation planning.
