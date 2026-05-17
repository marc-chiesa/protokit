# CHANGELOG (DRAFT — D6b U7 staging)

This file stages CHANGELOG content for the eventual 0.3.0 release.
Content here is **NOT yet in the published `CHANGELOG.md`** — it
accumulates during D6b's per-unit work and folds into `CHANGELOG.md`
at U7's delivery-boundary commit alongside the 0.2.0 → 0.3.0 version
bump.

The DRAFT-vs-published separation per
[[pre-1.0-version-bump-as-communication-contract]] +
[[delivery-boundary-unit-commit-composition]] keeps each unit's
public-surface tradeoffs visible to reviewers during the U4 → U7
window WITHOUT prematurely advertising additions that are still
gated by the `--rule-pack` opt-in path.

## D6b U4b (unreleased, dormancy-window note)

The R7 PACKAGE_SAME_* rule family (7 rules) lands in this commit as
**dormant code**. The rules are loadable but **NOT** registered in
the default `BUILTIN_PACKS` tuple, so a bare
`protokit lint --profile recommended <inputs>` invocation produces
**zero R7 findings**. To exercise R7 today, opt in explicitly:

    protokit lint \
        --rule-pack=protokit.schema.lint.rules.package_same \
        --profile recommended \
        <inputs>

The 7 rule_ids shipped:

- `package/same-go-package` → buf:`PACKAGE_SAME_GO_PACKAGE`
- `package/same-java-package` → buf:`PACKAGE_SAME_JAVA_PACKAGE`
- `package/same-csharp-namespace` → buf:`PACKAGE_SAME_CSHARP_NAMESPACE`
- `package/same-php-namespace` → buf:`PACKAGE_SAME_PHP_NAMESPACE`
- `package/same-ruby-package` → buf:`PACKAGE_SAME_RUBY_PACKAGE`
- `package/same-swift-prefix` → buf:`PACKAGE_SAME_SWIFT_PREFIX`
- `package/same-java-multiple-files` → buf:`PACKAGE_SAME_JAVA_MULTIPLE_FILES`

All 7 ship at `LintSeverity.ERROR` in profiles
`("recommended", "default")` once `BUILTIN_PACKS` registration lands
at U7. The dormancy window prevents pull-from-main between U4b and
U7 from breaking every downstream CI on the upgrade.

**Why dormant?** U7 ships the 0.2.0 → 0.3.0 version bump, the
`BUILTIN_PACKS` extension, the README "Schema Linting" section
refresh, the Public Surface DRAFT additions, and the pre-upgrade
migration note as one cohesive boundary commit. Eliminating the
U4b → U7 CI-breakage window for captive users is the explicit goal
per the per-unit brainstorm.

**Empirical foundation.** Each rule's behavior is locked against
buf v1.69.0 via 21 NDJSON snapshots committed at
`tests/schema/lint/rules/fixtures/package_same/_buf_smoke/recorded/`.
SHA-256 checksums under `CHECKSUMS.sha256` guard against accidental
edits; a follow-up live-mode test re-invokes buf at test time when
`BUF_BINARY` is set, gating buf-version drift.

## D6b U5 (unreleased, wire-format additive)

The `LintRuntimeWarning.category` Literal gains a 5th value
(`"severities_unloaded_rule"`) and the wire-format
`_LINT_JSON_SCHEMA_VERSION` constant bumps from `"0.2"` to `"0.3"`.
Together these close the D6a U9 KTD-2 accepted-conflation
trip-wire: programmatic consumers can now switch on `category`
instead of matching the `"[tool.protokit.lint.severities]"` message
substring to distinguish the two `*_unloaded_rule` emit sites.

**Bump scope.** The 0.2 → 0.3 bump is scoped to R9's new Literal
value ONLY. New `rule_id` strings landing in `LintFinding` output
from R6 (shipped U3) and R7 (shipped dormant U4b) do NOT trigger
additional bumps — `findings` is an additive list and consumers
already tolerate unknown rule_ids. The refined bump-contract
docstring at `src/protokit/formatters/_builtin_lint.py:243-269`
formalizes the closed-Literal-discriminator vs open-severity-ladder
distinction that justifies this scope.

**New category contract.** `severities_unloaded_rule` is
CLI-synthesized (NOT engine-emitted) and carries a populated
`rule_id` — the bad key from `[tool.protokit.lint.severities]`.
The original `unloaded_rule` category retains its engine-emit
semantics (a `rule_id` named in `profile.rule_ids` but not loaded
into the engine). See the `LintRuntimeWarning.category` docstring
at `src/protokit/schema/lint/model.py` for the full per-category
field-population contract.

**Consumer migration (the value migrated, it did not vanish).**
Code currently switching on `category == "unloaded_rule"` and
expecting the CLI-side severities-overlay case will see ZERO matches
after upgrade — the value MIGRATED to `severities_unloaded_rule`,
it did not become unknown. Forward-compatibility tolerance for new
values does NOT save such consumers; the schema_version bump IS
the documented signal that switch tables need re-checking. Audit
existing `category == "unloaded_rule"` paths and split them: keep
the original branch for the engine-emit case (rule named in profile
but not loaded into engine) and add a new
`category == "severities_unloaded_rule"` branch for the
severities-overlay case.

## D6b U7 — eventual CHANGELOG content scope (suggested)

Owned by U7's plan; documented here so the substantive items from
U4b's + U5's accepted tradeoffs are not lost in handoff.

1. **+7 new ERROR-severity rules** enumerated above.
2. **N-not-N-1 per-package emit cardinality.** A 5-file package
   with disagreement produces up to 5 × 7 = 35 findings. A 20-file
   no-package legacy corpus where the `""`-namespace aggregation
   kicks in produces up to **140 findings** (20 × 7) on the upgrade.
   The combined estimate is the load-bearing number for adoption
   sizing.
3. **`""`-package monorepo aggregation explanation** + mitigation
   recipe (declare `package` on all protos OR demote per-rule via
   `[tool.protokit.lint.severities]` for known-no-package globs).
4. **Transitive-import supply-chain note** + mitigation (pin
   dependency versions OR demote PACKAGE_SAME_* when third-party
   imports introduce conflicts).
5. **WKT enforcement note** for users with non-standard
   `google/protobuf/` vendoring.
6. **Example pyproject `[tool.protokit.lint.severities]` snippets**
   showing per-rule demotion.
7. **`--rule-pack` opt-in pattern** preserved as a forward-compat
   escape hatch for users who want early-access to a future rule
   family without waiting for `BUILTIN_PACKS` registration.
8. **`schema_version` 0.2 → 0.3 bump** (driven by R9's
   `LintRuntimeWarning.category` Literal widening; rule_id
   additions from R6 / R7 do NOT contribute additional bumps).
9. **New `"severities_unloaded_rule"` `LintRuntimeWarning.category`
   value** (CLI-synthesized; closes D6a U9 KTD-2). Carries
   populated `rule_id`.
10. **Bump-contract docstring refinement** at
    `_builtin_lint.py:243-269` (closed Literal discriminator vs
    open severity-string ladder distinction). The first closed-
    Literal addition under the refined contract.
11. **Consumer-migration note** for the category-value migration:
    consumers switching on `category == "unloaded_rule"` expecting
    the CLI-side severities-overlay case must audit + split paths
    rather than rely on forward-compatibility tolerance.

U7's plan owns final wording / structure / collapsing as long as
the 3 accepted tradeoffs (`""`-package aggregation, transitive-import
contamination, WKT enforcement) and the combined-worst-case math
remain covered, AND the U5 wire-format items (8-11) remain
discoverable for the consumer-migration audience.
