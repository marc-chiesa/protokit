---
title: "Extending a lint rule pack: derive rule_id inventories from RULES, rename duplicate test class names across sibling files"
date: 2026-05-12
category: best-practices
module: protokit.schema.lint
problem_type: best_practice
component: testing_framework
severity: low
applies_when:
  - "Adding new rules to a module.RULES tuple consumed by LintEngine.load_rule_pack"
  - "Introducing a sibling test file that covers an extended scope of an existing pack"
  - "Writing tests or introspection helpers that need an exhaustive set of rule_ids for a pack"
tags:
  - rule-pack
  - rule-id
  - ssot
  - test-hygiene
  - sibling-test-files
  - lint-rules
  - naming
---

# Extending a lint rule pack: derive rule_id inventories from RULES, rename duplicate test class names across sibling files

## Context

When D6a Unit 3 extended the `naming` rule pack from 1 rule (the D2 canary) to 9 rules, two test-hygiene gaps surfaced during `ce:review`:

1. The new exhaustive rule_id assertion lived in a hand-listed 9-element `frozenset` literal at the top of `test_naming_extended.py`. Adding or removing a rule from `RULES` would silently drift from that constant until the profile-membership test failed at run time.
2. The new test file (`tests/schema/lint/rules/test_naming_extended.py`) and the original canary file (`tests/schema/lint/test_canary_naming.py`) both defined a class named `TestNamingPackShape`. Pytest accepts duplicate class names across files, but IDE navigation, `pytest -v` output, and ownership reasoning all suffer.

Both gaps are small, but both recur every time a pack is extended via a sibling test file — and this delivery alone will repeat the pattern across `enum.py`, `imports.py`, `package.py`, and `file.py` over D6a Units 4-6. Capturing the discipline once prevents the same notes from appearing in every future ce:review.

## Guidance

**Derive rule_id inventories from `RULES` rather than hand-listing them.** When a test needs the exhaustive set of rule_ids a pack registers, comprehend over the pack's `RULES` tuple and read each function's decorator-attached `_lint_spec`:

```python
# Before — hand-listed, drifts on rule additions/removals:
_ALL_NAMING_RULE_IDS = frozenset(
    {
        "naming/snake-case-fields",
        "naming/pascal-case-messages",
        # ... 7 more strings, one per rule ...
    }
)

# After — derived from the canonical source:
from protokit.schema.lint.rules.naming import RULES

_ALL_NAMING_RULE_IDS = frozenset(
    fn._lint_spec.rule_id  # type: ignore[attr-defined]
    for fn in RULES
)
```

The `_lint_spec` attribute is attached by the `@lint_rule` decorator at module-import time. The decorator's declared signature returns `Callable[[Callable[..., None]], Callable[..., None]]` — a bare callable with no typed protocol exposing `_lint_spec`, so the type checker correctly does not see the runtime-attached attribute. The `# type: ignore[attr-defined]` documents the gap between the declared return type and the runtime contract. The same comment pattern appears in the per-rule spec-metadata tests in `test_naming_extended.py` (e.g., `spec = check_pascal_case_messages._lint_spec  # type: ignore[attr-defined]`), so the comprehension here is consistent with the established access convention.

**Rename duplicate test class names across sibling files.** When the existing test file tests a narrower scope of a pack and a new sibling tests the extended scope, rename the older file's class to reflect its narrower scope. In D6a Unit 3, `TestNamingPackShape` in `test_canary_naming.py` was renamed to `TestCanaryPackShape`, with a docstring noting the relationship:

```python
class TestCanaryPackShape:
    """The naming pack exposes RULES with the canary rule properly registered.

    Named ``TestCanaryPackShape`` (not ``TestNamingPackShape``) to
    avoid colliding with the same-named class in
    ``tests/schema/lint/rules/test_naming_extended.py``, which covers
    the wider 9-rule pack shape introduced in D6a Unit 3.
    """
```

The rename happens once, in the same commit as the new sibling file. The new file owns the canonical "PackShape" class name (`TestNamingPackShape`) because it tests the full surface; the older file owns a scoped variant.

## Why This Matters

A hand-listed frozenset is an invisible update obligation: a future engineer adding a rule to `RULES` must remember to update the separate inventory constant. The compiler does not enforce it; the linter does not flag it; only a profile-membership assertion catches the drift, and only after CI runs. The derived form eliminates the update site entirely — `RULES` is the single source of truth for "what rule_ids does this pack expose," and every consumer reads from it.

Duplicate class names across test files produce three concrete problems: (1) `pytest -v` output renders both as `TestNamingPackShape` with only the file path distinguishing them, making grep noisier; (2) IDE "go to test class" navigation becomes ambiguous; (3) future readers must inspect both files to understand which is the canonical surface. The rename costs five minutes and resolves all three.

Both patterns are micro-decisions individually but compound across a delivery. D6a Unit 3 alone shipped both; Units 4-6 will repeat the same shape four more times if not pre-empted by the discipline.

## When to Apply

- **Any pack-extension PR** that adds rules to an existing `module.RULES` tuple consumed by `LintEngine.load_rule_pack`.
- **Any sibling test file** that tests an extended scope of a pack already covered by an existing test file in the same directory tree.
- **Any test or introspection helper** that needs the exhaustive set of rule_ids exposed by a pack — the derived form scales automatically as the pack grows.

The discipline does not apply when:
- The hand-listed inventory is deliberately *partial* (e.g., a subset of rule_ids being tested for a specific behavior). In that case, name the constant to reflect the partiality (e.g., `_NAMING_RULE_IDS_FIRING_ON_OPTIONAL`).
- The test class names in sibling files cover orthogonal aspects already named differently (e.g., `TestPackShape` vs `TestHappyPath`).

## Examples

Both patterns landed in commit `79428b2` (D6a U3 ce:review follow-ups) as `safe_auto` fixes:

**Derivation** — `/Users/marc/projects/python_message_differencer/tests/schema/lint/rules/test_naming_extended.py`:
```python
# Rule_ids the naming pack registers — derived from RULES so a future
# rule addition (or removal) auto-updates this constant rather than
# requiring a hand-edit at every consumer. The ``_lint_spec`` attribute
# is attached by the ``@lint_rule`` decorator at module-import time;
# the ``type: ignore`` mirrors the established access pattern used in
# the per-rule spec-metadata tests above.
_ALL_NAMING_RULE_IDS = frozenset(
    fn._lint_spec.rule_id  # type: ignore[attr-defined]
    for fn in RULES
)
```

**Class rename** — `/Users/marc/projects/python_message_differencer/tests/schema/lint/test_canary_naming.py`:
```python
class TestCanaryPackShape:
    """The naming pack exposes RULES with the canary rule properly registered.

    Named ``TestCanaryPackShape`` (not ``TestNamingPackShape``) to
    avoid colliding with the same-named class in
    ``tests/schema/lint/rules/test_naming_extended.py``, which covers
    the wider 9-rule pack shape introduced in D6a Unit 3.
    """
```

## Related

- [[parametrized-matrix-tests-inherit-schema-validators-2026-05-12]] — the parallel principle for parametrized matrix tests: inherit fixtures from the canonical source rather than re-declaring per file. Sibling test files extending the same surface share the same single-source-of-truth discipline.
- [[audit-wire-format-before-claiming-sibling-parity-2026-05-03]] — `module.RULES` is the canonical pack entry-point; this learning is the test-side reading of the same contract that document is the planning-side reading of.
- [[conftest-plain-function-relative-import-2026-05-12]] — the adjacent learning for *helper* deduplication across sibling test files (plain functions in `conftest.py` with relative imports). When test classes diverge in name but share helper code, conftest extraction is the next-tier solution. D6a U2's ce:compound surfaced this pattern from prior session history; U3's class-rename is the simpler resolution path when only the class name (not the helper code) collides.
- [[public-surface-draft-discipline-source-audit-2026-05-12]] — the `_lint_spec` attribute is part of the DRAFT public surface; tests reading `fn._lint_spec.rule_id` reinforce the contract.
