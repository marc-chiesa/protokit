---
title: When testing a list-parser that unloads N items, the fixture must trigger ALL N items' downstream behaviors
date: 2026-05-25
category: docs/solutions/best-practices
module: protokit.schema.lint
problem_type: best_practice
component: testing_framework
severity: high
applies_when:
  - "A test asserts that a `disabled_rules` / `enabled_rules` / `--disable-rule` list-form config disables a family of N rules at once"
  - "The list parser accepts N distinct identifiers and each suppresses an independent downstream behavior (e.g., one per ElementKind, ServiceKind, etc.)"
  - "The existing fixture only contains elements of one kind, meaning a silent-drop bug on the 2nd-through-Nth list entries would be invisible"
  - "The rule family has a fixed enumerable set of target kinds (e.g., FIELD/MESSAGE/ENUM/ENUM_VALUE/METHOD for the R6 deprecated_replacement family)"
related_components:
  - tooling
tags:
  - list-parser
  - disabled-rules
  - fixture-coverage
  - element-kind
  - silent-drop
  - multi-kind
  - test-design
  - baseline-pin
---

# Multi-element fixture necessity for family-list disable test coverage

## Context

D6f U1's migration recipe for R6 promotion included a fourth path: listing all 5 R6 rule_ids in `disabled_rules` as a family-list disable. The test `test_path4_disabled_rules_family_unloads_all_five` (in `tests/schema/lint/cli/test_cli_r6_migration_recipe.py`) was originally written against `sad.proto` — a fixture containing only a single deprecated FIELD element. The test verified that path #4 produced exit code 0 and zero R6 findings.

The flaw: `sad.proto` triggers only one of the five R6 rule_ids (`options/deprecated-field-must-have-replacement-comment`). A parser regression that silently dropped 4 of the 5 entries in `disabled_rules` — leaving only the FIELD rule in the effective disabled set — would have caused path4 to still pass. The single-kind fixture provided no more regression protection than a test that disabled only one rule.

ce:review run `20260524-232840-29bb63be` surfaced this as a P2 finding with 3-reviewer agreement (correctness, testing, and maintainability reviewers all flagged the same gap independently). The fix (commit `55868cc`) replaced the fixture with `sad_multi_element.proto` carrying deprecated elements of all 5 ElementKinds and added a module-level baseline test pinning the pre-suppression signal.

**Pattern precedent (not codified before):** the same gap was caught in D6b U6's ce:review for `test_parity_package_same.py` (May 18 session — `78c5dd64`). The fix there was the same shape — extend the parametrized fixture to cover all rules in the family. This learning codifies the discipline so the third occurrence doesn't have to wait for cross-reviewer convergence to surface it.

## Guidance

**When testing a list-based suppression mechanism over N items, the fixture must trigger all N items' downstream behaviors before suppression. A fixture exercising only 1 of N items is no stronger than a single-item test.**

**Rule:** If the thing under test is a list parser that suppresses N distinct rule_ids, rule types, or categories simultaneously, the test fixture must contain elements that exercise all N items.

### Companion baseline test (mandatory)

Add a separate module-level test that invokes the same fixture WITHOUT any suppression and asserts that all N expected signals fire. This baseline test serves two purposes:

1. **Pins the fixture's pre-suppression behavior.** A fixture regression (syntax error, accidental `deprecated=false` flip, missing `option deprecated = true`) surfaces as an explicit test failure rather than silently weakening the suppression test.
2. **Makes the suppression test's assertion meaningful.** If the baseline passes, the suppression test's zero-findings result is doing real work — proving the suppression mechanism, not just the absence of triggers.

### Worked example (the D6f U1 fix)

```python
# tests/schema/lint/cli/test_cli_r6_migration_recipe.py

class TestD6fR6MigrationRecipe:
    def test_path4_disabled_rules_family_unloads_all_five(self) -> None:
        """Suppress: verify zero R6 findings when all 5 rule_ids
        are in disabled_rules."""
        result = _invoke_lint(
            _FIXTURE_DIR / "sad_multi_element.proto",   # multi-element fixture
            pyproject=_FIXTURE_DIR / "path4_disabled_rules_family.toml",
        )
        assert result.exit_code == 0
        assert _r6_findings(result.stdout) == []


# Module-level baseline (NOT nested in the class):
def test_sad_multi_element_proto_fires_five_r6_findings_without_suppression() -> None:
    """Baseline pin: fixture must trigger all 5 R6 rule_ids
    pre-suppression."""
    result = _invoke_lint(
        _FIXTURE_DIR / "sad_multi_element.proto",
        "--profile", "default",
    )
    assert result.exit_code == 1
    rule_ids = {f["rule_id"] for f in _r6_findings(result.stdout)}
    assert rule_ids == {
        "options/deprecated-field-must-have-replacement-comment",
        "options/deprecated-enum-value-must-have-replacement-comment",
        "options/deprecated-method-must-have-replacement-comment",
        "options/deprecated-message-must-have-replacement-comment",
        "options/deprecated-enum-must-have-replacement-comment",
    }
```

The original single-element fixture is **not discarded** — preserve it for tests that legitimately test only one element kind (paths 2/3 and the negative control in D6f use `sad.proto` appropriately; the FIELD-only signal is sufficient for those tests). The multi-element fixture is additive.

## Why This Matters

A list-based suppression parser that correctly handles 1 entry but silently drops entries 2-N (due to a slice-off-by-one, a set-deduplication bug, or a regex that only matches the first kind) is an undetectable regression if the test fixture exercises only 1 entry. The suppression test passes; the bug ships.

This is a specific instance of the general principle that **a suppression test is only as strong as its triggering fixture**. For family-list parsers the gap is particularly easy to miss because the "all 5 disabled" assertion feels comprehensive — it IS comprehensive for the list semantics, but it implicitly depends on the fixture having all 5 live signals.

The 3-reviewer convergence on this single finding (ce:review run `20260524-232840-29bb63be`) reflects that the gap is non-obvious to any one reviewer but obvious in hindsight: correctness reviewers catch it as a logic gap in the suppression proof, testing reviewers catch it as fixture under-coverage, and maintainability reviewers catch it as a hidden coupling between fixture content and test validity.

## When to Apply

- Testing any `disabled_rules = [R1, R2, ..., RN]` family-list form where N > 1.
- Testing any suppress/exclude/ignore list parser that processes multiple distinct items simultaneously.
- Testing `--disable-rule R1 --disable-rule R2` repeatable CLI flag interactions where the N-item signal must all be suppressed.
- Extending a test from a single-element fixture to prove a "suppress all N" claim.

Not required for:
- Tests of a single-item disable (the fixture covering that one item is sufficient).
- Tests that verify parser error handling (fixture content is irrelevant to error path tests).

## Examples

### Before (single-element fixture, insufficient for family-list)

`sad.proto` contains only a deprecated FIELD element. `test_path4_disabled_rules_family_unloads_all_five` used it and passed — but a parser bug dropping 4 of 5 entries in `disabled_rules` would also pass, because only 1 rule needed to be disabled to suppress the only finding.

### After (multi-element fixture + baseline, commit `55868cc`)

`sad_multi_element.proto` carries:
- `LegacyUser.legacy_id` — deprecated FIELD
- `LegacyStatus.LEGACY_STATUS_INACTIVE` — deprecated ENUM_VALUE
- `LegacyService.LegacyLookup` — deprecated METHOD
- `LegacyUser` message — deprecated MESSAGE
- `LegacyStatus` enum — deprecated ENUM

The path4 test now consumes `sad_multi_element.proto`. The baseline test asserts all 5 rule_ids fire without suppression. A regression that drops 4 of 5 entries from `disabled_rules` now leaves 4 residual findings — the path4 test fails.

### Source references

- `tests/schema/lint/cli/test_cli_r6_migration_recipe.py:164-265` (post-fix line range)
- `tests/schema/lint/cli/cli_fixtures/d6f_r6_migration/sad_multi_element.proto` (introduced in commit `55868cc`)
- D6b U6 precedent (session history): `test_parity_package_same.py` parametrized fixture extended for the package_same family at May 18 ce:review

## Related

- [[fixture-precondition-assertion-surfaces-silent-test-2026-05-17]] — sibling fixture-silence class: that doc covers vacuous-pass from empty output; this doc covers incomplete N-of-N path coverage. Both are "fixture inadequacy causes false test confidence."
- [[parametrized-matrix-tests-inherit-schema-validators-2026-05-12]] — sibling test-coverage completeness discipline.
- [[family-aware-partition-pattern-multi-family-parity-harness-2026-05-19]] — runtime context where family-list disable coverage matters; a fixture that only triggers one family kind can't validate the partition.
- [[capture-setup-without-dispatch-false-test-confidence-2026-05-17]] — sibling false-confidence class.
