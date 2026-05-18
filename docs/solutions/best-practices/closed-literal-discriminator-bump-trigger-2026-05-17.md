---
title: "Closed Literal discriminator additions bump schema_version; open severity ladders don't — apply the consumer-correctness test"
date: 2026-05-17
category: docs/solutions/best-practices
module: src/protokit/formatters/_builtin_lint.py
problem_type: best_practice
component: tooling
severity: medium
applies_when:
  - "A wire-format-bearing dataclass field of type ``Literal[...]`` gains a new string value"
  - "Consumers may exhaustively switch / match on the field's value to route logic rather than just render or compare it"
  - "A documented ``schema_version`` (or equivalent versioning) contract governs when wire-format changes trigger a bump"
  - "The codebase already enforces the bump contract via a single module-level constant docstring (see [[wire-format-schema-version-bump-contract-and-absence-semantic-2026-05-13]])"
  - "Adding the new value SHIPS in the same release as the bump (no dormant-code window between Literal widening and version constant edit)"
tags:
  - wire-format
  - schema-version
  - literal-discriminator
  - bump-contract
  - exhaustive-switch
  - forward-compatibility
  - api-contract
  - lint-runtime-warning
---

# Closed Literal discriminator additions bump `schema_version`; open severity ladders don't — apply the consumer-correctness test

## Context

D6a U9 (commit `c7a426b`) introduced `_LINT_JSON_SCHEMA_VERSION = "0.2"` as protokit's first wire-format version constant with a documented bump contract: bump on (a) new top-level keys, (b) change in meaning of an existing field, (c) removal of a previously documented field. The original contract appended a single blanket sentence: "Adding new severity-level / category strings to an existing enum field does NOT bump the version (the field's meaning is unchanged; the enum just gains a value)."

D6b U5 (commit `16b494f`) widened `LintRuntimeWarning.category: Literal[...]` from 4 to 5 values by adding `"severities_unloaded_rule"` (resolving D6a U9 KTD-2's accepted conflation). The U5 plan and KTD-5 surfaced a contradiction: the blanket "enum-value additions don't bump" sentence would make the U5 bump look like an over-bump. But the contract was wrong — not all enum-value additions are equivalent. Two regimes coexist:

- **`severity` field** (`"error"` / `"warning"` / `"info"`) — consumers render the string or compare by ordering. An unknown value can still be rendered, still ordered (with a sensible fallback), still tolerated. Adding a hypothetical `"trace"` level doesn't break correctness.
- **`category` field** (`"rule_exception"` / `"unloaded_rule"` / ...) — consumers exhaustively switch on the value to route logic (each branch handles a different shape: `rule_exception` populates `exception_type` and `descriptor_path`, while `unloaded_rule` leaves both `None`). An unknown value falls through to a `default:` / `else:` branch the consumer didn't write for the new case.

The U5 bump-contract docstring refinement formalizes the distinction with a discriminating question: **"Can a consumer that doesn't know about the new value still produce a correct result?"** Open ladders: yes. Closed discriminators: no. The U5 commit landed the refined docstring + the constant bump (0.2 → 0.3) as one atomic change.

## Guidance

**When adding a new string value to a wire-format-bearing `Literal[...]` field, classify it as a closed discriminator OR an open ladder using the consumer-correctness test. Closed discriminators DO bump `schema_version`; open ladders DO NOT. Document the classification at the field site, not just at the version constant.**

The discriminating question, applied at the point of every Literal addition:

> Can a consumer that doesn't know about the new value still produce a correct result?

- **YES** → open ladder. Examples: `severity` ordering, `level` rendering, free-text descriptive enums. Don't bump.
- **NO** → closed discriminator. Examples: routing tags (`category`, `type`, `kind`) where each value triggers different code paths in the consumer. Bump.

Sub-rules:

1. **Bump in the same commit as the Literal addition.** A dormant-code window where the value exists in source but the version constant is stale produces inconsistent wire-format states: tests would emit the new value under the old version. Co-locate the Literal edit and the constant edit in one commit. (Per [[delivery-boundary-unit-commit-composition-2026-05-14]], this is a per-unit bump, NOT a delivery-boundary release-version bump — see [[pre-1.0-version-bump-as-communication-contract-2026-05-14]] for the decoupled signals.)

2. **Document the classification at the field.** The Literal docstring on the frozen dataclass should enumerate per-value contracts that make the closed-discriminator nature obvious (e.g., "each category has distinct field-population semantics; consumers exhaustively switch"). A future contributor adding a 6th value sees the contract and applies the test correctly.

3. **The refined bump-contract is the load-bearing document.** Without the closed-vs-open distinction in the `_LINT_JSON_SCHEMA_VERSION` docstring (the SSOT per [[wire-format-schema-version-bump-contract-and-absence-semantic-2026-05-13]]), the bump action looks like an over-bump and a future contributor will silently re-introduce the conflation. The refined wording is REQUIRED, not optional.

4. **Test the value vacancy at the type-system level.** A presence-ratchet test (`assert len(typing.get_args(SomeClass.field.type)) == N`) makes silent additions impossible — adding a 6th value without bumping fails the test loudly. The U5 commit landed this for `LintRuntimeWarning.category` at `tests/schema/lint/test_model_dataclass_changes.py:54`.

5. **Forward-compatibility tolerance is NOT a substitute for the bump.** Consumers that "treat unknown values as forward-compatible" via a `default:` branch still need the bump as the signal to AUDIT their switch statements. The bump tells them: "your `default:` branch will now fire for a known case — re-check whether you need a specific handler."

6. **The classification can flip during a field's lifetime.** A field that started as an open ladder may become a closed discriminator if consumers add routing logic. Once classified closed, additions bump. The reverse migration (closed → open) is impossible without a major version change.

## Why This Matters

**Wrong classification = silent consumer breakage.** Treating a closed discriminator as an open ladder means the consumer's `default:` branch fires for a known case the producer thinks is "just a new enum value." The consumer's routing logic is incomplete; the bug surfaces as missing behavior, not as an exception. Detection requires noticing absence, which is much harder than noticing presence.

**Wrong classification = false-alarm bump.** Treating an open ladder as a closed discriminator means consumers re-check their switch statements every time a new severity / level / descriptive string lands. Over time the version field becomes noise; consumers stop reading the bumps; the next legitimate bump goes unnoticed.

**The consumer-correctness test is decidable at the producer side.** The producer doesn't need to enumerate consumer code; the producer needs to ask "could the consumer's code work without knowing about this value?" If the field's value drives field-population shape (different categories populate different fields), the answer is no. If the field is purely descriptive, the answer is yes.

**The refined contract is the worked example for future additions.** D6b U5 is the first closed-Literal-discriminator addition in protokit. The bump-contract docstring's new wording becomes the rubric for every future closed-Literal addition. Without the discriminating question, contributors will re-derive the rule from scratch (or skip it).

## When to Apply

Apply this discipline when ALL of the following are true:

1. A `Literal[...]` field on a wire-format-bearing dataclass is gaining a new string value.
2. The field flows through serialization to JSON / SARIF / YAML / similar machine-consumed format.
3. A documented `schema_version` (or equivalent) contract exists per [[wire-format-schema-version-bump-contract-and-absence-semantic-2026-05-13]].
4. The field's role is decidable as discriminator (drives downstream branching) or ladder (renders / orders).

The inverse — when this discipline does NOT apply:

- **Adding a new top-level KEY to a wire-format payload** — that's trigger (a) in the bump contract; always bump regardless of discriminator classification.
- **Changing the MEANING of an existing field's value** — trigger (b); always bump.
- **Removing a documented field** — trigger (c); always bump.
- **Internal-only Literal fields** that never leave the process — no consumer, no contract.
- **Free-text fields typed as `str`** rather than `Literal[...]` — outside this discipline (those are by definition unbounded; consumers can never assume exhaustiveness).

## Examples

### The discriminating question applied to two protokit fields

`LintFinding.severity: Literal["error", "warning", "info"]`:

> Can a consumer that doesn't know about a hypothetical `"trace"` value still produce a correct result? **YES** — they render the string (no special handling) or order it (with `"trace"` falling outside the known ordering, the consumer treats it as "lowest by default" or similar fallback). Adding `"trace"` does NOT bump.

`LintRuntimeWarning.category: Literal["rule_exception", "unloaded_rule", "severities_unloaded_rule", "min_severity_relaxed", "all_files_excluded"]`:

> Can a consumer that doesn't know about `"severities_unloaded_rule"` still produce a correct result? **NO** — the consumer's `match w.category` block has no arm for the new value; the warning falls through to `case _:` (default) which is either an error log or a silent skip. The consumer treats the warning as malformed, NOT as a known signal it needs to route. Adding `"severities_unloaded_rule"` DOES bump (0.2 → 0.3 in U5).

### Refined bump-contract docstring (the load-bearing artifact)

`src/protokit/formatters/_builtin_lint.py:243-269` (after U5):

```python
#:   - Protokit bumps this version on:
#:       (a) addition of new top-level keys
#:       (b) change in meaning of an existing field
#:       (c) removal of a previously documented field
#:   - **Bump-trigger refinement (closed Literals vs open ladders):**
#:     Adding new string values to an existing enum field has two
#:     consumer-impact regimes that determine whether a bump is
#:     needed:
#:       * **Open severity-string ladders** — for fields like
#:         ``severity`` (``"error"`` / ``"warning"`` / ``"info"``)
#:         where consumers tolerate unknown values gracefully (the
#:         field's role is to be rendered or compared, not switched
#:         on; an unknown value can still be rendered as a string or
#:         compared by ordering), additions DO NOT bump the version.
#:       * **Closed Literal discriminators** — for fields like
#:         ``LintRuntimeWarning.category`` (``"rule_exception"`` /
#:         ``"unloaded_rule"`` / ...) where consumers exhaustively
#:         switch on the value (each case handled with different
#:         logic; an unknown value would fall through to a default
#:         branch the consumer didn't expect), additions DO bump the
#:         version. Every consumer must extend their switch / match
#:         construct to handle the new case.
#:     The discriminating question: can a consumer that doesn't know
#:     about the new value still produce a correct result? Open
#:     ladders: yes. Closed discriminators: no. D6b U5's addition of
#:     ``"severities_unloaded_rule"`` to the ``category`` Literal is
#:     the first closed-Literal addition under this contract; it
#:     bumps schema_version from ``"0.2"`` to ``"0.3"``.
_LINT_JSON_SCHEMA_VERSION: str = "0.3"
```

### Co-located bump + Literal edit (one atomic commit)

The U5 feat commit (`16b494f`) bundled six edits as ONE commit:

1. `src/protokit/schema/lint/model.py` — Literal widening (4 → 5 values) + dataclass docstring rewrite
2. `src/protokit/formatters/_builtin_lint.py` — `_LINT_JSON_SCHEMA_VERSION = "0.2"` → `"0.3"` + refined bump-contract docstring + `runtime_warnings` docstring rewrite (per-category contract pointer)
3. `src/protokit/schema/lint/cli.py` — CLI emit-site `category=` switch + inline comment rewrite
4. Lockstep test updates (count-pin 4 → 5, parametrize list extension, helper tuple + factory branch)
5. NEW source-discrimination test module with paired positive + negative assertions
6. Documentation surfaces (README, CHANGELOG-DRAFT, TODOS)

No intermediate state has the Literal at 5 with the constant at 0.2 (or vice versa).

### Type-system presence-ratchet (catches silent additions)

`tests/schema/lint/test_model_dataclass_changes.py:38-54`:

```python
def test_literal_lists_all_five_categories(self) -> None:
    """The Literal annotation must enumerate exactly 5 category
    names. A drift to 4 or 6 indicates an accidental break in the
    category contract that this test catches at import time.
    """
    type_hints = typing.get_type_hints(LintRuntimeWarning)
    category_type = type_hints["category"]
    literal_args = typing.get_args(category_type)
    assert set(literal_args) == {
        "rule_exception",
        "unloaded_rule",
        "severities_unloaded_rule",
        "min_severity_relaxed",
        "all_files_excluded",
    }
    # And exactly 5 — not "a superset" — so adding a sixth without
    # a corresponding test update will fail this assertion.
    assert len(literal_args) == 5
```

Adding a 6th value without the lockstep test update fails this test loudly. The test makes it structurally impossible to widen the Literal without remembering to apply the consumer-correctness test (and bump if it fails).

### The same lesson at the field site

`LintRuntimeWarning` docstring (after U5, at `src/protokit/schema/lint/model.py:354-510`) enumerates per-category contracts that make the closed-discriminator nature obvious:

```
1. ``"rule_exception"`` — populates exception_type + descriptor_path
2. ``"unloaded_rule"`` — populates rule_id; exception_type/descriptor_path None
3. ``"severities_unloaded_rule"`` — populates rule_id; exception_type/descriptor_path None
4. ``"min_severity_relaxed"`` — rule_id None (not rule-scoped)
5. ``"all_files_excluded"`` — rule_id None (not rule-scoped)
```

A future contributor adding a 6th value reads this docstring and sees that each value has distinct field-population semantics. They can correctly classify the field as a closed discriminator without re-deriving the rule.

## Related

- [[wire-format-schema-version-bump-contract-and-absence-semantic-2026-05-13]] — this doc EXTENDS that one. The original bump contract had the three triggers (a/b/c) + a single blanket "enum-value additions don't bump" sentence; this doc replaces that sentence with the closed-vs-open distinction grounded in the consumer-correctness test. D6b U5 is the first worked example.
- [[semantic-category-conflation-accepted-tradeoff-literal-widening-2026-05-13]] — RESOLVED by D6b U5. That doc captured the deferred decision to split `"unloaded_rule"` into engine-emit + CLI-emit categories; U5 executed the split and bumped schema_version 0.2 → 0.3 as the consumer-facing signal. The three-site documentation discipline was applied in reverse: Literal docstring + CLI emit-site comment + TODOS.md backlog entry all retired as the split landed.
- [[value-migrated-vs-value-added-consumer-migration-2026-05-17]] — sibling learning for the CONSUMER side of this story. D6b U5 didn't just ADD `"severities_unloaded_rule"` — it MIGRATED the CLI-emit site from `"unloaded_rule"` to the new value. Forward-compatibility tolerance protects against value-added; the schema_version bump is the only signal for value-migrated. The two learnings together cover producer-side (this doc: when to bump) and consumer-side (the sibling: what the bump signals).
- [[pre-1.0-version-bump-as-communication-contract-2026-05-14]] — distinguishes the wire-format schema_version (this doc's scope, bumps per-unit) from the package semver (bumps at delivery boundary). Both are signals; they bump on different cadences. The U5 commit bumped wire-format 0.2 → 0.3 while the package stays at 0.2.x until U7's delivery boundary.
- [[delivery-boundary-unit-commit-composition-2026-05-14]] — explains why the wire-format bump can land in a per-unit commit (U5) rather than waiting for the delivery-boundary commit (U7). The per-unit bump is the wire-format signal; the boundary commit is the package-version + CHANGELOG fold + README refresh.
- [[cross-format-enum-string-parity-2026-05-08]] — when the bump fires, BOTH sibling formats (lint_json top-level + lint_sarif `runs[].properties.lint_schema_version`) must agree on the new value. Single-constant cascade enforces this structurally.
- [[parametrized-matrix-tests-inherit-schema-validators-2026-05-12]] — closed-Literal additions automatically gain cross-formatter coverage when the `LINT_RUNTIME_WARNING_CATEGORIES` tuple in `tests/schema/lint/cli/_helpers.py` is updated in lockstep with the model Literal. The cross-check test at `test_model_dataclass_changes.py:56-79` enforces the tuple stays in sync.
- [[stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12]] — the closed-Literal classification at the field site (the per-category contract docstring) is itself a "narrative enumeration" that needs lockstep updates when the Literal widens. The U5 ce:review surfaced 7 stale narrative sites that the planning-time grep missed because they enumerated the count narratively ("four categories") not literally.
- Anchor commits: `16b494f` (D6b U5 feat — Literal widening + bump + bump-contract docstring refinement), `7cd4095` (D6b U5 ce:review follow-ups — 6 safe_auto stale-narrative fixes).
- Plan: `docs/plans/2026-05-17-003-feat-d6b-u5-r9-severities-category-split-plan.md` (Key Technical Decisions section — "Coupling acknowledgement: R9-bump and R9-docstring are inseparable", "Bump-scope clarification (closed Literal value ONLY)").
- Brainstorm: `docs/brainstorms/2026-05-17-d6b-u5-r9-severities-category-split-requirements.md` (R9-docstring section — refined wording template).
- 9-reviewer ce:review at `.context/compound-engineering/ce-review/20260517-180704-b16077be/` — the api-contract + adversarial + maintainability reviewers converged on the importance of the refined contract.
