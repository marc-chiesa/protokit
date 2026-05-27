---
title: SARIF rule catalog entries must emit defaultConfiguration.level so severity contracts are discoverable without running a lint
date: 2026-05-25
category: docs/solutions/best-practices
module: protokit.formatters._builtin_lint
problem_type: best_practice
component: tooling
severity: medium
applies_when:
  - "A rule's severity is being promoted or demoted and the change needs to be discoverable by IDE integrations and agent callers pre-flight"
  - "The SARIF formatter emits `tool.driver.rules[]` catalog entries but omits `defaultConfiguration.level`"
  - "A rule carries severity as `dict[str, LintSeverity]` keyed by ElementKind rather than a single scalar `LintSeverity`"
  - "SARIF consumers (IDE plugins, CI dashboards, GitHub Advanced Security) render rule-level severity without running a scan (catalog-only path)"
related_components:
  - development_workflow
  - documentation
tags:
  - sarif
  - rule-catalog
  - default-configuration-level
  - severity-promotion
  - agent-discoverability
  - dict-severity
  - ide-integration
  - wire-format
---

# SARIF rule catalog must publish defaultConfiguration.level for severity-change agent discoverability

## Context

D6f's R6 promotion flipped all 5 `options/deprecated_replacement` rules from WARNING to ERROR. After the promotion, a SARIF consumer (IDE integration, GitHub Advanced Security, CI agent) that wanted to distinguish R6 from lower-severity rules without inspecting individual findings had no way to do so — the `tool.driver.rules[]` catalog entries emitted by `_lint_rules_catalog` in `src/protokit/formatters/_builtin_lint.py` contained `id`, `name`, and `shortDescription` only. They omitted `defaultConfiguration.level`, the SARIF 2.1.0 field (§3.49.3) that declares a rule's default severity at the catalog level.

This gap was not locally visible in the protokit test suite. Two SARIF tests that would have caught it (`test_d6d_custom_annotation_example.py::TestSarifFormatExposesCustomRule` and `test_builtin_lint_formatter.py::TestLintSarif`) had been broken by an earlier unrelated issue — multi-kind dict-severity rules were never handled at the catalog emit site at all, so the tests were already failing. The ce:review agent-native reviewer surfaced the discoverability gap as a P2 finding in run `20260524-232840-29bb63be`. The fix (commit `4fb57a5`) added the field and incidentally repaired the two pre-existing test failures.

This gap was known earlier: a D3 U4b ce:review (May 8) flagged a related `_lint_rules_catalog` else-branch conflation as P3 across three reviewers but assessed it as advisory at the time. The `defaultConfiguration.level` consequence sat unfixed until the D6f severity promotion made it user-visible.

## Guidance

**Emit `defaultConfiguration.level` on every `tool.driver.rules[]` entry in SARIF output. This is the field IDE integrations and GitHub Advanced Security use to display rule severities in the rule panel, independent of any individual finding.**

Per SARIF 2.1.0 §3.49.3, `reportingDescriptor.defaultConfiguration` is the mechanism for declaring a rule's baseline severity at the schema level. IDE integrations (VS Code SARIF viewer, GitHub Advanced Security, etc.) render rule severities in the rule panel from `defaultConfiguration.level` — NOT from `results[].level`. A tool that omits this field leaves the rule panel showing unclassified severity, regardless of how correctly the individual findings are emitted.

### Single-kind rules (scalar severity)

```python
# Before (pre-fix): no defaultConfiguration field
out.append({
    "id": rule_id,
    "name": rule_id,
    "shortDescription": {"text": description},
})
```

```python
# After (post-fix, commit 55868cc):
entry: dict[str, Any] = {
    "id": rule_id,
    "name": rule_id,
    "shortDescription": {"text": description},
}
if spec is not None:
    if isinstance(spec.severity, dict):
        catalog_severity = max(
            spec.severity.values(),
            key=lambda s: SEVERITY_RANK[s],
        )
    else:
        catalog_severity = spec.severity
    entry["defaultConfiguration"] = {
        "level": _lint_severity_to_sarif_level(catalog_severity),
    }
out.append(entry)
```

### Multi-kind rules (dict-typed severity)

SARIF emits **one catalog entry per `rule_id`**, not per kind. When a rule carries `severity: dict[str, LintSeverity]` keyed by `violation_kind`, reduce to a single severity for the catalog using the strictest value across kinds:

```python
catalog_severity = max(
    spec.severity.values(),
    key=lambda s: SEVERITY_RANK[s],
)
```

In practice, multi-kind rules ship with uniform severities across kinds (mixed severity is architecturally discouraged), so this reduction is usually a no-op — but it must be handled explicitly to avoid a `TypeError` at the emit site when the helper expects `LintSeverity` and gets `dict[str, LintSeverity]`.

### Skip the field when `spec is None`

The stub case (synthetic rule_id with no registered spec) — the rule's declared severity is unrecoverable. Emitting a placeholder severity would be misleading; omit `defaultConfiguration` entirely for these entries.

## Why This Matters

`defaultConfiguration.level` serves two distinct consumer classes:

1. **IDE integrations at design time.** VS Code SARIF viewer and GitHub Advanced Security display rule severity in the rule panel before any file is linted. Without this field, all rules appear with unclassified (or uniform placeholder) severity — a user cannot tell which rules are ERROR-severity candidates that will break CI.

2. **Programmatic agents and CI pipelines.** An agent consuming SARIF output to decide which rules to disable, defer, or escalate operates on the rule catalog. After D6f's R6 promotion, an agent that used the catalog to identify ERROR-severity rules would have found none — the promotion would be invisible to the catalog consumer even though individual findings correctly carried `level: "error"`.

The side effect of adding this field in commit `4fb57a5` was that 2 pre-existing SARIF tests that had been silently broken (by multi-kind dict-severity not being handled at the catalog emit site) became passing. This illustrates a secondary risk: when the field is absent, test coverage for the catalog shape is easy to miss or break without immediate feedback.

Severity changes are catalog-level events. Emitting `defaultConfiguration.level` makes them immediately visible to any SARIF consumer — making severity changes and the catalog consistent is a discipline that becomes mandatory once IDE or agent consumers are in the picture.

## When to Apply

- Any new SARIF-emitting linter or formatter that supports multi-severity rules.
- Any severity promotion or demotion in an existing SARIF-emitting tool.
- When adding IDE integration (VS Code, GitHub Advanced Security) to a lint tool — `defaultConfiguration.level` is the first field the IDE panel looks up.
- When a lint tool has multi-kind rules with dict-typed severity: the reduction via `max(..., key=SEVERITY_RANK.__getitem__)` (or equivalent) must be explicit at the catalog emit site.

Not critical for tools that:
- Emit SARIF only for archival/display in a custom UI that does not use `tool.driver.rules[]`.
- Have all rules at a single severity level (the field still should be emitted, but omitting it has lower visible impact).

## Examples

### Before (pre-fix): catalog entries carry no severity information

```json
{
  "tool": {
    "driver": {
      "rules": [
        {
          "id": "options/deprecated-field-must-have-replacement-comment",
          "name": "options/deprecated-field-must-have-replacement-comment",
          "shortDescription": {
            "text": "Field marked deprecated= must document its replacement ..."
          }
        }
      ]
    }
  }
}
```

An IDE rule panel would show this rule without a severity badge. Post-D6f, it is ERROR-severity — but the catalog does not say so.

### After (post-fix, commit `4fb57a5`)

```json
{
  "tool": {
    "driver": {
      "rules": [
        {
          "id": "options/deprecated-field-must-have-replacement-comment",
          "name": "options/deprecated-field-must-have-replacement-comment",
          "shortDescription": {
            "text": "Field marked deprecated= must document its replacement ..."
          },
          "defaultConfiguration": {
            "level": "error"
          }
        }
      ]
    }
  }
}
```

The IDE rule panel now renders this rule with the ERROR severity badge. An agent scanning the SARIF catalog for ERROR-severity rules to selectively disable will find it.

### Code reference

- `src/protokit/formatters/_builtin_lint.py:_lint_rules_catalog` (post-fix lines ~698-741), introduced in commit `4fb57a5` (D6f U1 ce:review follow-ups)
- SARIF spec: SARIF 2.1.0 §3.49.3 `reportingDescriptor.defaultConfiguration`

## Related

- [[dict-shaped-message-template-multi-arm-rule-violation-kind-2026-05-19]] — closest sibling: both concern `_lint_rules_catalog` in `_builtin_lint.py`; that doc covers `shortDescription` corruption from identity templates; this doc covers `defaultConfiguration.level` absence. Both are formatter-layer gaps in the same function.
- [[expose-finding-params-lint-json-sarif-agent-native-2026-05-19]] — sibling agent-native discipline: that doc surfaces `params` in `result.properties`; this doc surfaces severity in `rules[].defaultConfiguration.level`. Both address SARIF output completeness for agent consumers.
- [[wire-format-schema-version-bump-contract-and-absence-semantic-2026-05-13]] — when `defaultConfiguration.level` is added to existing catalog entries, the absence-semantic discipline applies: consumers that haven't seen this field before should treat its absence as "level: warning" per SARIF 2.1.0 §3.49.3 defaults.
- [[stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12]] — sibling agent-discoverability concern at a different surface (CLI `--help` vs SARIF catalog).
