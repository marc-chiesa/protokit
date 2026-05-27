---
title: Perf smoke should filter expected runtime-warning categories by name, not couple to a curated rule list
date: 2026-05-27
category: docs/solutions/best-practices
module: protokit.schema.lint
problem_type: best_practice
component: testing_framework
severity: low
applies_when:
  - Writing perf tests against the full default rule engine
  - Engine includes rules that emit runtime warnings depending on extensions the fixture doesn't import (e.g., `options/field-behavior-consistent` emitting `extension_unresolved`)
  - Distinguishing walker-throughput assertions from rule-extension-wiring assertions
  - "A `should-be-empty` test assertion needs to admit known-OK entries, and the alternative would be hand-curating a rule list"
tags:
  - perf-smoke
  - warning-allowlist
  - extension-unresolved
  - rule-decoupling
  - walker-throughput
  - test-isolation
  - category-keyed-filter
  - runtime-warnings
related_components:
  - testing_framework
---

# Perf smoke should filter expected runtime-warning categories by name, not couple to a curated rule list

## Context

protokit's lint engine emits typed `runtime_warnings` for non-fatal conditions that the user should know about: a rule raised an exception (`rule_exception`), the profile selected a rule that's not loaded (`unloaded_rule`), severity overrides reference unloaded rules (`severities_unloaded_rule`), and — most relevant here — a rule depends on a protobuf extension that isn't registered in the compile pool (`extension_unresolved`).

`extension_unresolved` is documented surface, not a bug. Rules like `options/field-behavior-consistent` (added in 0.5.0 as part of the AIP-203 well-formedness checks) expect the input proto to import `google/api/field_behavior.proto` so the rule can inspect the field's annotations. Inputs that don't import that file get the rule skipped with a warning ("rule X cannot evaluate file Y because extension Z is not in the pool"). This is correct behavior.

The perf smoke's synthetic fixture deliberately uses no external extensions — it's testing walker cost, not extension-resolution behavior. So `options/field-behavior-consistent` correctly emits one `extension_unresolved` warning per file. The original `assert not report.runtime_warnings` blanket-rejected those, masking the smoke's actual signal: a perf-regression in the walker.

## Guidance

Filter the `extension_unresolved` category from the unexpected-warnings assertion **by category name**, not by curated rule list. From `tests/schema/lint/test_perf_smoke.py:187-212`:

```python
# Closes the silent-pass gap on runtime warnings: if any rule
# raises a rule_exception, or if the profile selects an unloaded
# rule_id (unloaded_rule), those warnings would otherwise sail
# through while the canary passes.
#
# Filter out `extension_unresolved` warnings: those are the
# documented "rule X requires extension Y which isn't registered
# in the compile pool, so the rule skips this file" surface,
# emitted by option-aware rules added in 0.5.0+
# (notably `options/field-behavior-consistent`, which expects
# `google.api.field_behavior` to be imported by the input proto).
# The synthetic smoke fixture deliberately uses no external
# extensions, so this warning category fires once per file and
# is unrelated to walker performance — which is what the smoke
# canary actually tests. Counting these as "unexpected" would
# tie the smoke to a curated list of which BUILTIN_PACKS
# rules happen to use extensions, defeating the "future-proof
# the smoke against BUILTIN_PACKS growth" intent above.
unexpected_warnings = tuple(
    w for w in report.runtime_warnings
    if w.category != "extension_unresolved"
)
assert not unexpected_warnings, (
    f"smoke fixture produced unexpected runtime warnings: "
    f"{unexpected_warnings}"
)
```

The **name-allowlist pattern** is the load-bearing choice. The alternative — maintaining a curated list of `rules-known-to-need-extensions` in the smoke — would couple the smoke to specific rule names, requiring the smoke to be updated every time a new extension-aware rule lands. The category-based filter is invariant to rule additions: every new rule that depends on an external extension will emit the same `extension_unresolved` category and be filtered automatically.

## Why This Matters

Runtime-warning assertions in perf smokes serve a specific purpose: catch silent failures where the canary timing assertion passes (walker is fast) but something is wrong (rules are failing, missing, or misconfigured). A blanket `assert not runtime_warnings` is the strictest form of that assertion but assumes the fixture exercises every rule cleanly.

`extension_unresolved` breaks the assumption because it's not a failure — it's a deterministic property of the fixture (no extensions imported) combined with rule design (some rules need extensions). The only ways to eliminate it would be: import every possible extension in the fixture (heavy, brittle), or exclude extension-dependent rules from the smoke's profile (also brittle, requires manual maintenance as rules are added).

The category-allowlist filter is the right shape because it expresses the actual contract: "tell me about runtime warnings that indicate something broken, but don't tell me about warnings that are documented deterministic surface for this fixture shape." The smoke continues to catch the warnings that matter (`rule_exception`, `unloaded_rule`, `severities_unloaded_rule`) and ignores the one that doesn't.

The broader pattern: **when a "should be zero" assertion needs to allow specific known cases, allowlist by category/tag rather than by rule name.** Categories are stable across rule additions; rule names are not. The same shape applies to allowlisting deprecation warnings by category, filtering CI logs by job name vs. specific commit, etc.

## When to Apply

- When a perf smoke or canary uses a "no runtime warnings" assertion AND any loaded rule depends on external extensions/options that the fixture doesn't import.
- Generally, when a "should-be-empty" assertion needs to admit known-OK entries, filter by stable category rather than by exhaustive rule-name list.
- Does NOT apply to standalone-rule unit tests where the fixture is built to exercise exactly one rule and runtime warnings genuinely indicate failure.
- Does NOT apply when the assertion's purpose is "no warnings of ANY kind" (a stricter contract worth preserving on its own merits).

## Examples

**Before (couples to rule-name list, brittle to BUILTIN_PACKS growth):**

```python
# Excludes specific rules from the perf-smoke profile to suppress
# their extension_unresolved warnings:
_RULES_NEEDING_EXTENSIONS = frozenset({
    "options/field-behavior-consistent",
    # ... future rule names go here ...
})
profile = LintProfile.compose(
    *(LintProfile.from_pack(pack, profile_name="default")
      for pack in BUILTIN_PACKS),
)
profile = dataclasses.replace(
    profile,
    rule_ids=tuple(r for r in profile.rule_ids if r not in _RULES_NEEDING_EXTENSIONS),
)
# ... then the original strict assertion:
assert not report.runtime_warnings
```

Every new extension-aware rule requires updating `_RULES_NEEDING_EXTENSIONS`. The smoke breaks until someone notices.

**After (category-allowlist, future-proof against new extension-aware rules):**

```python
# Profile is composed across all of BUILTIN_PACKS unchanged;
# every rule runs as-is and gets to emit warnings naturally.
unexpected_warnings = tuple(
    w for w in report.runtime_warnings
    if w.category != "extension_unresolved"
)
assert not unexpected_warnings
```

Adding a new extension-aware rule next release: no change to the smoke. The new rule will emit `extension_unresolved` on the fixture, the filter ignores it, the assertion stays meaningful.

## Related

- [[perf-smoke-profile-compose-across-builtin-packs-2026-05-13]] — same file (`test_perf_smoke.py`), same "decouple the smoke from per-delivery rule lists" instinct. Consider consolidating into a perf-smoke discipline cluster.
- [[test-method-names-encode-invariants-not-delivery-deltas-2026-05-13]] — same "decouple tests from per-delivery details" mental shape, applied at the test-name granularity.
- [[dual-ssot-derivation-import-time-drift-guard-2026-05-19]] — same "don't hand-curate a list when you can derive it" pattern, applied to schema-version drift.
- changelog-readme-snippet-fixture-byte-equivalence-2026-05-21 — references `custom_annotation_extension_unresolved` runtime warning category as a silent-failure signal.
- [[perf-smoke-fixture-layout-must-track-cross-file-lint-rule-additions-2026-05-27]] — the companion 0.7.1 fix on the same test module.
- Canonical commit: `5886fdb` ("test: perf smoke filters extension_unresolved warnings (documented surface)").
