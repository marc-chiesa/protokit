---
title: "Enforce load-bearing ordering invariants on pair-tuples / frozensets via module-level assert at import time, not by comment alone"
date: 2026-05-20
category: docs/solutions/best-practices
module: src/protokit/schema/lint/rules/options/field_behavior.py
problem_type: best_practice
component: tooling
severity: medium
applies_when:
  - "A module defines a curated frozenset, tuple, or sequence of structured values (pairs, triples) where element ordering inside each value is load-bearing for downstream output stability"
  - "The intended ordering invariant (e.g., alphabetic a < b) is documented in a comment but not enforced mechanically"
  - "Future contributors adding new entries may flip the order, causing downstream output keys (e.g., value_a/value_b in lint params) to swap depending on source order"
  - "The consumption site unpacks the structured value directly (e.g., `a, b = pair`) and relies on the ordering for stable rendered output"
  - "Existing parametrized tests cover ONLY current entries and would silently accept a malformed new entry"
tags:
  - module-level-assert
  - canonicalization
  - ordered-pairs
  - import-time
  - invariant-enforcement
  - lint-rule
  - fail-loud
  - stable-output
  - structural-enforcement
---

# Module-level `assert` enforces ordering invariants on frozensets at import time

## Context

protokit-lint's D6d U2 `options/field-behavior-consistent` rule stores contradictory FieldBehavior pairs as `_CONTRADICTORY_PAIRS: frozenset[tuple[str, str]]`. Each pair is stored alphabetically — `("OPTIONAL", "REQUIRED")` rather than `("REQUIRED", "OPTIONAL")` — so the consumption site can do `a, b = pair` with a guaranteed ordering for the lint message's `value_a` / `value_b` params:

```python
_CONTRADICTORY_PAIRS: frozenset[tuple[str, str]] = frozenset({
    ("IMMUTABLE", "OUTPUT_ONLY"),
    ("INPUT_ONLY", "OUTPUT_ONLY"),
    ("OPTIONAL", "REQUIRED"),
    ("OUTPUT_ONLY", "REQUIRED"),
    ("IMMUTABLE", "INPUT_ONLY"),
})
```

The alphabetic-storage convention was documented in a comment + the consumption-site relied on it (`a, b = pair # already alphabetic-sorted`). A future contributor adding `("REQUIRED", "OPTIONAL")` (the wrong order) would have caused two findings to fire on the same field with value_a/value_b flipped — exactly what the alphabetic-storage was designed to prevent.

ce:review caught the missing mechanical gate via 3-way reviewer convergence (D6d U2, 2026-05-20): MAINT-4 + ADV-3 + KP-4 all flagged the comment-only enforcement. The fix is a one-line module-level `assert` that fires at import time. Any malformed pair fails CI immediately + the assertion message explains the WHY.

## Guidance

**When a curated frozenset/tuple/sequence has a load-bearing internal ordering invariant, enforce it with a module-level `assert` at import time. Make the assertion message explain the consumption-site contract.**

The assertion for `_CONTRADICTORY_PAIRS`:

```python
_CONTRADICTORY_PAIRS: frozenset[tuple[str, str]] = frozenset({
    ("IMMUTABLE", "OUTPUT_ONLY"),
    ("INPUT_ONLY", "OUTPUT_ONLY"),
    ("OPTIONAL", "REQUIRED"),
    ("OUTPUT_ONLY", "REQUIRED"),
    ("IMMUTABLE", "INPUT_ONLY"),
})
# Structural enforcement of the alphabetic-storage convention — a
# non-alphabetic tuple (e.g., ("REQUIRED", "OPTIONAL")) would cause
# value_a/value_b to flip in emitted params depending on proto source
# order, breaking the order-invariance contract. Fires at module
# import time so a malformed addition fails CI immediately.
assert all(a < b for a, b in _CONTRADICTORY_PAIRS), (
    "_CONTRADICTORY_PAIRS tuples must be alphabetically sorted "
    "(a < b). Mis-ordered pairs flip value_a/value_b in emitted params."
)
```

The assertion fires at import time. Any CI run that imports the module catches a malformed pair immediately + the assertion message explains the WHY.

**Three structural alternatives and their tradeoffs:**

(a) **Module-level `assert` (recommended for pre-1.0 curated sets):** cheapest, fires at import, clear error message, zero overhead in production (`-O` strips assertions). Does NOT prevent the wrong pair from being written — it catches it at import. Best for curated sets with ≤20 hand-maintained entries.

(b) **`frozenset[frozenset[str]]` instead of `frozenset[tuple[str, str]]`:** eliminates the ordering by making the inner container itself unordered. Consumption site `a, b = sorted(pair)` must call `sorted()` explicitly — the inner set must be materialized. Loses tuple-unpacking readability at declaration. Use when the set is large + the structural guarantee is more important than declaration readability.

(c) **Factory function `_make_pair(a, b) -> tuple[str, str]` that canonicalizes via `tuple(sorted([a, b]))` at construction:** moves the invariant to the constructor. The frozenset literal can still contain `_make_pair("REQUIRED", "OPTIONAL")` and the output is always canonical. Slightly more verbose at declaration; useful when pairs are programmatically constructed rather than hand-curated.

For pre-1.0 protokit with hand-curated sets of < 10 pairs, option (a) is the clear choice. The assertion is one line; the error message explains the convention; CI catches violations immediately.

**Placement discipline.** Put the assertion immediately after the constant definition, not at module bottom. A reader scanning the constant sees the invariant enforcement directly below and does not need to search for it.

**Error-message discipline.** Write the assertion message as if explaining to a future contributor who will see ONLY the `AssertionError` traceback, NOT the comment above the constant. Include:

1. **What the invariant IS** ("a < b alphabetic").
2. **WHY it matters** (the consumption-site contract — what breaks downstream).
3. **HOW to fix** (the construction-site rule the contributor must follow).

The D6d U2 message: `"_CONTRADICTORY_PAIRS tuples must be alphabetically sorted (a < b). Mis-ordered pairs flip value_a/value_b in emitted params."` All three facets in one sentence.

## Why This Matters

**Existing parametrized tests don't catch new-entry malformations.** Unit tests that parametrize over `_CONTRADICTORY_PAIRS` as-is exercise ONLY current entries. A new malformed pair added to the frozenset will produce a new test case that passes (the wrong-order pair still triggers a finding — it's just a doubled, flipped finding), or the new test exercises the wrong message and is accepted as correct. The assertion is the only mechanical gate that fails CI on malformed additions.

**The silent-flip failure mode is user-visible AND ambiguous.** If `("REQUIRED", "OPTIONAL")` is added alongside the existing `("OPTIONAL", "REQUIRED")`, users see TWO lint findings on the same field with `value_a` and `value_b` swapped between them. The duplication is confusing; the flip is invisible from the finding text alone. No exception is raised by the rule itself. Debugging requires walking the frozenset construction site to spot the wrong-order tuple — exactly the work the contributor should NOT need to do if the invariant were enforced structurally.

**Comment-only conventions erode.** A comment saying "alphabetical order" is ignored by linters, mypy, and tests. It is advisory, not structural. The assertion converts the advisory comment into a mechanical invariant that survives contributor turnover and code reviews that miss the comment.

**Import-time failure has zero production cost.** The `assert` fires once at module import. In optimized deployments (`python -O`), assertions are skipped entirely — but pre-1.0 protokit does not ship with `-O`, and CI always runs without it. The assertion is free in production AND mechanical in CI.

**Cross-reviewer convergence is the surfacing mechanism.** Three independent D6d U2 reviewers (maintainability MAINT-4, adversarial ADV-3, kieran-python KP-4) flagged the comment-only enforcement from three angles: maintainability ("convention erodes"), adversarial ("construct the malformed addition"), kieran-python ("type-system invisibility"). The convergence signals the risk is structurally obvious once read side-by-side, but invisible without juxtaposition — exactly the convergence-boost discipline from [[ce-review-convergence-rescues-sub-threshold-findings-2026-05-17]].

## When to Apply

Apply a module-level `assert` for ordering invariants when ALL of the following hold:

1. A `frozenset[tuple[...]]`, `list[tuple[...]]`, or similar structured constant has an ordering or canonicalization convention (alphabetic, monotonic, balanced).
2. The consumption site relies on that ordering for CORRECTNESS (not just readability) — e.g., tuple-unpacking into named output keys, hash lookups against an ordered key, alphabetic-by-default test assertions.
3. A future contributor adding a new entry could violate the invariant without any existing test failing.
4. The constant is hand-curated (not programmatically generated — programmatic generation should include the canonicalization in the generator).

**Do NOT apply** when:

- The consumption site does NOT rely on ordering (membership tests only — `key in _SET`). The overhead of the assertion is non-zero and the invariant does not exist.
- The set is programmatically generated by a constructor that already canonicalizes (option (c) above already covers this; the assertion would be redundant).
- The set is used purely for display and the "wrong" order is visually equivalent to the "right" order.
- The set is small (≤3 entries) and contributor frequency is low enough that the comment + code-review backstop is sufficient. This calls for judgment; D6d U2 had 5 entries with deferred-promotion intent (D6e+ will add more), which crossed the threshold.

**Protokit instances where this applies today:** `_CONTRADICTORY_PAIRS` in `field_behavior.py` (this case). Future option-aware curated sets whose consumption relies on ordered unpacking should be audited for the same pattern.

## Examples

### Before: comment-only convention (silent-flip bug possible)

```python
# Pairs are stored alphabetically (a < b) — consumption site unpacks
# `a, b = pair` and relies on this ordering.
_CONTRADICTORY_PAIRS: frozenset[tuple[str, str]] = frozenset({
    ("IMMUTABLE", "OUTPUT_ONLY"),
    ("INPUT_ONLY", "OUTPUT_ONLY"),
    ("OPTIONAL", "REQUIRED"),
})

# Consumption site (relies on alphabetic ordering):
for pair in _CONTRADICTORY_PAIRS:
    a, b = pair  # assumed alphabetic; silently wrong if invariant violated
```

A future contributor adds `("REQUIRED", "OPTIONAL")`. No test fails. CI passes. Users see doubled findings with flipped `value_a` / `value_b` params.

### After: module-level `assert` (invariant enforced at import)

```python
_CONTRADICTORY_PAIRS: frozenset[tuple[str, str]] = frozenset({
    ("IMMUTABLE", "OUTPUT_ONLY"),
    ("INPUT_ONLY", "OUTPUT_ONLY"),
    ("OPTIONAL", "REQUIRED"),
    # Add future pairs in alphabetical order: ("SMALLER", "LARGER").
})
# Structural enforcement of the alphabetic-storage convention.
assert all(a < b for a, b in _CONTRADICTORY_PAIRS), (
    "_CONTRADICTORY_PAIRS tuples must be alphabetically sorted "
    "(a < b). Mis-ordered pairs flip value_a/value_b in emitted params."
)

# Consumption site — ordering is now mechanically guaranteed:
for pair in _CONTRADICTORY_PAIRS:
    a, b = pair  # safe: assert at module top ensures a < b
```

If `("REQUIRED", "OPTIONAL")` is added, the import raises:

```
AssertionError: _CONTRADICTORY_PAIRS tuples must be alphabetically sorted
(a < b). Mis-ordered pairs flip value_a/value_b in emitted params.
```

CI fails immediately. The contributor sees the fix instruction in the error message.

### Test that pins the assertion's presence

```python
def test_contradictory_pairs_alphabetic_invariant():
    """Public regression test that the alphabetic-storage invariant
    is upheld — fires if a future refactor removes the module-level
    assert + a future entry violates the convention."""
    for pair in _CONTRADICTORY_PAIRS:
        a, b = pair
        assert a < b, (
            f"_CONTRADICTORY_PAIRS contains {pair!r} which violates "
            f"the alphabetic-storage convention; fix the construction "
            f"site using tuple(sorted([x, y]))."
        )
```

The test backs up the module-level assertion: if a contributor removes the import-time assert (e.g., during a refactor), the test still pins the invariant.

### Alternative: factory function (option c — for programmatic construction)

```python
def _pair(x: str, y: str) -> tuple[str, str]:
    """Return (x, y) in alphabetical order. Canonicalizes at construction."""
    return tuple(sorted([x, y]))  # type: ignore[return-value]

_CONTRADICTORY_PAIRS: frozenset[tuple[str, str]] = frozenset({
    _pair("IMMUTABLE", "OUTPUT_ONLY"),
    _pair("OUTPUT_ONLY", "IMMUTABLE"),  # wrong source order, auto-corrected
    _pair("OPTIONAL", "REQUIRED"),
})
```

The factory silently corrects any wrong-order addition. Preferred when pairs are generated programmatically OR when contributors should not be required to know the alphabetic convention.

## Related

- [[dual-ssot-derivation-import-time-drift-guard-2026-05-19]] — sibling: the same module-level-assert-at-import discipline applied to a DIFFERENT invariant class. Where that doc covers TWO independently-derived SSOT views drifting against each other (MEMBERSHIP-EQUALITY invariant), this doc covers ONE frozenset's internal ordering convention (ORDERING invariant). Both fire at `pytest --collect-only` time + both produce diagnostic enumeration on failure. The two patterns share placement discipline and error-message discipline.
- [[module-import-time-fixture-mapping-fail-loud-blast-radius-2026-05-18]] — sibling: deliberate fail-loud design of module-import-time validation. The "blast radius" and "collection-time failure" guidance applies directly to module-level `assert`s for canonicalization invariants. Different invariant class (FIXTURE-PRECONDITION) but same enforcement discipline.
- [[programmatic-proto-fixture-builder-multi-file-rule-family-2026-05-17]] — sibling: structural enforcement of conventions. Where that doc covers programmatic fixture builders that prevent class-of-errors via construction, this doc covers module-level assertions that enforce load-bearing ordering conventions on curated constants. Both are instances of the broader "enforce structurally, not by convention" discipline.
- [[weakkeydict-plus-id-resettable-attr-per-engine-per-run-state-2026-05-20]] — sibling: another structural-enforcement pattern from the same D6d U2 ce:review pass.
- [[bound-method-self-extraction-rule-to-engine-callback-2026-05-20]] — sibling: another structural-debt pattern from the same D6d U2 ce:review pass.
- [[ce-review-convergence-rescues-sub-threshold-findings-2026-05-17]] — sibling: the 3-way reviewer convergence (MAINT-4 + ADV-3 + KP-4) that surfaced the comment-only enforcement gap.
- Anchor commit: D6d U2 ce:review follow-up commit (2026-05-20). See `src/protokit/schema/lint/rules/options/field_behavior.py:179-198` for the assertion.
