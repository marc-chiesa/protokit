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

## D6b U7 — eventual CHANGELOG content scope (suggested)

Owned by U7's plan; documented here so the substantive items from
U4b's accepted tradeoffs are not lost in handoff.

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

U7's plan owns final wording / structure / collapsing as long as
the 3 accepted tradeoffs (`""`-package aggregation, transitive-import
contamination, WKT enforcement) and the combined-worst-case math
remain covered.
