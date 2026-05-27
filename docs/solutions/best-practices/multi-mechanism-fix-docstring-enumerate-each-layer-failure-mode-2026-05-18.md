---
title: "Multi-mechanism fix docstring must enumerate each layer + its specific failure mode"
date: 2026-05-18
category: docs/solutions/best-practices
module: docs/conventions/test-documentation
component: testing_framework
problem_type: best_practice
applies_when:
  - "A fix spans multiple defensive layers (e.g., CLI-level dedup + engine-level short-circuit + profile-level frozenset union) where each layer independently prevents a distinct failure mode"
  - "Removing any single layer restores the original bug"
  - "The test class or module docstring describing the fix was authored when only some layers existed"
  - "Future maintainers might read the docstring and conclude one layer is redundant, simplifying it away"
  - "Cross-reviewer convergence (3+ reviewers in a ce:review pass) flags the docstring as describing the fix imprecisely or describing pre-fix behavior"
severity: medium
tags:
  - docstring-discipline
  - multi-layer-defense
  - test-documentation
  - future-engineer-trap
  - defense-in-depth
  - ce-review-convergence
  - fix-induced-documentation-drift
---

# Multi-mechanism fix docstring must enumerate each layer + its specific failure mode

## Context

When a single bug fix involves coupled mechanisms across distinct code layers, the test docstring or module comment that documents the fix can become misleading even when each statement in it is individually correct. The danger is not that any single mechanism is wrong — each may be individually documented accurately. The danger is that a future maintainer sees one mechanism (often the most visible, high-level one) and infers that other mechanisms are therefore redundant simplification candidates.

D6b U7 demonstrated this concretely. The CLI rule-pack dedup bug (see [[cli-loaded-packs-dedup-zip-strict-builtin-packs-flip-2026-05-18]]) was fixed by adding a CLI-level dedup guard. The `TestRulePackExplicitLoadIsIdempotent` test class docstring originally described only TWO mechanisms: engine-level idempotent load (`engine.py:241-242`) and profile-level frozenset union (`model.py:717-719`). The docstring stated:

> "The CLI does NOT de-dup loaded_packs (cli.py:831 unconditionally appends): an explicit --rule-pack for a pack already in BUILTIN_PACKS produces a doubled list entry; the downstream compose frozenset-union eats the duplicate."

This was directly contradicted by the U7 commit's own fix at `cli.py:841-846`, which added exactly that CLI-level dedup. Five independent ce:review reviewers (correctness COR-1 at 0.95, testing T-03 at 0.80, maintainability MAINT-1 at 0.92, adversarial ADV-1 at 0.92, kieran-python KP-1 at 0.92) flagged the docstring. Cross-reviewer convergence boosted effective confidence to 1.00. Each reviewer independently identified the same future-engineer trap: read docstring → conclude CLI dedup is redundant → remove the cli.py:841-846 guard → re-introduce the `zip(strict=True)` ValueError bug.

## Guidance

When a fix involves multiple coupled mechanisms across distinct code layers, the test class docstring (or the module comment that describes the mechanism) MUST enumerate EACH layer by name + file:line + the specific exception or symptom that surfaces if that specific layer is removed.

**Required structure** for the docstring:

```python
class TestRulePackExplicitLoadIsIdempotent:
    """<one-line property the test asserts>.

    <N> coupled mechanisms keep this invariant; removing any one
    restores a distinct failure mode, so a future engineer simplifying
    one without re-checking the others can silently break the contract:

    1. **<Mechanism name> at <file:line> (the load-bearing guard)**:
       `<exact code snippet of the guard>`.
       Without this guard, `<specific call site>` at `<file:line>` fails
       with `<exact exception type + message>` — the original bug.

    2. **<Mechanism name> at <file:line>**:
       `<exact code snippet>`.
       Prevents `<specific failure mode>` (which would `<symptom>`).
       Independent of <#1> — applies to <broader scope>.

    3. **<Mechanism name> at <file:line>** (defense-in-depth):
       `<exact code snippet>`.
       Backstop that absorbs `<failure mode>` even if the upper-layer
       <#1 or #2> were removed. NOT the primary mechanism.
    """
```

**The three discipline rules:**

1. **Name each mechanism by file:line + the SPECIFIC failure mode.** "Layer" alone is insufficient — name the exact function/guard and the exact exception or broken behavior that surfaces when that specific mechanism is absent. A maintainer should be able to read the docstring and PREDICT EXACTLY what breaks if they simplify any one layer, without running the test suite.

2. **State the dependency structure explicitly.** If mechanism 3 does NOT prevent mechanism 1's failure, say so in the docstring. "Defense-in-depth" vs "primary load-bearing guard" is a distinction that must appear in plain text.

3. **Identify the load-bearing mechanism.** When multiple mechanisms exist, ONE of them is usually the primary guard against the original bug; the others are independent guards against different failure modes OR are backstops. Label them explicitly. This prevents a future reader from concluding that a backstop makes the primary guard redundant.

## Why This Matters

When multiple coupled mechanisms implement a single correctness property across code layers:

- The danger is not that any single mechanism is wrong — each may be individually correct.
- The danger is that a future maintainer sees mechanism 3 (the most visible, high-level one) and infers that mechanisms 1 and 2 are therefore redundant simplification candidates.
- Five reviewers independently flagging the same docstring at high confidence is a DIAGNOSTIC SIGNAL: the existing description was producing a false mental model. A docstring that accurately describes a fix but still misleads a reader about the fix's necessity is functionally the same as a wrong docstring.
- The three-mechanism enumeration pattern converts the docstring from a NARRATIVE ("here is what happened") into a SPECIFICATION ("here is what breaks if each piece is removed"). Specifications are more durable than narratives under refactoring pressure.

This pattern complements ce-review-convergence-rescues-sub-threshold-findings-2026-05-17 (the convergence boost mechanism): when 3+ reviewers agree on a documentation gap, BOOST mode applies even though the individual confidences may have been moderate. The 5-way convergence on the U7 docstring is the canonical worked example of BOOST applied to documentation rather than to code findings.

## When to Apply

- A code fix introduces a guard at layer N, but an existing mechanism at layer N+1 appears to subsume it (e.g., frozenset-union appears to absorb duplicates, so why deduplicate at a higher layer?).
- A test class docstring describes the behavior of a flow involving two or more coupled mechanisms — any of which, if removed, would break the property the test is asserting.
- A ce:review surfaces multi-reviewer convergence (3 or more reviewers) on documentation that describes a fix, especially when reviewers independently identify the same "future-engineer trap" — the scenario where a maintainer reads the doc and is misled into removing a load-bearing guard.
- The fix was motivated by a boundary-flip (e.g., BUILTIN_PACKS expansion, schema_version bump, dormant-code activation): boundary-flips are the primary occasions when assumptions baked into earlier code get violated by new state.

**Skip when:** the fix is single-mechanism (only one guard, no backstop) — there is nothing to enumerate.

## Examples

**Before (describes pre-fix behavior, misleads maintainer):**

```python
class TestRulePackExplicitLoadIsIdempotent:
    """Verify --rule-pack=<pack> for a registered pack is idempotent.

    The CLI does NOT de-dup loaded_packs (cli.py:831 unconditionally
    appends): an explicit --rule-pack for a pack already in BUILTIN_PACKS
    produces a doubled list entry; the downstream LintProfile.compose
    frozenset-union at model.py:717-719 absorbs the duplicate rule_ids.
    """
```

Failure mode: a maintainer reads this docstring, concludes the guard at `cli.py:841-846` is redundant (the frozenset union handles it), removes the guard. The `zip(strict=True)` at `cli.py:987` then raises `ValueError` at runtime because the dict key-count and the list length diverge. The test that was supposed to catch this passes during development (because the frozenset union DOES absorb duplicates at composition time), but the `ValueError` only surfaces when the CLI is actually invoked.

**After (enumerates three mechanisms with failure modes):**

```python
class TestRulePackExplicitLoadIsIdempotent:
    """Explicit --rule-pack=...package_same is idempotent post-0.3.0.

    Since D6b U7 added package_same to BUILTIN_PACKS, the explicit
    --rule-pack flag for a built-in pack becomes a redundant explicit
    load — exercised here as an idempotency regression. THREE coupled
    mechanisms preserve the no-op contract; removing any one
    re-introduces a different failure mode, so a future engineer
    simplifying one without re-checking the others can silently break
    the contract:

    1. **CLI-level dedup at cli.py:841-846 (the load-bearing guard
       added at D6b U7)**:
       `if user_pack.__name__ not in {p.__name__ for p in loaded_packs}:
        loaded_packs.append(user_pack)`.
       This is what keeps the loaded_packs_tuple length aligned with
       _active_rule_ids_per_pack(...)'s dict size (the dict is keyed by
       pack.__name__ and would silently de-dup). Without this guard, the
       R25 multi-pack provenance line at cli.py:987 fails
       `zip(loaded_packs_tuple, active_per_pack.values(), strict=True)`
       with `ValueError('zip() argument 2 is shorter than argument 1')`
       — the original D6b U7-flip-surfaced bug.

    2. **Engine-level idempotent load at engine.py:241-242**:
       `if module.__name__ in self._loaded_module_names: return`.
       Prevents the engine from registering the same pack's rules twice
       (which would raise DuplicateRuleError). Independent of the CLI
       guard above — applies to any caller, not just CLI.

    3. **Profile-level frozenset union at model.py:717-719**
       (defense-in-depth):
       LintProfile.compose uses
       `frozenset().union(*(p.rule_ids for p in profiles))`.
       Backstop that absorbs duplicate per-pack profiles even if the
       upper-layer dedup were removed. Defense-in-depth, not the
       primary mechanism.
    """
```

Failure mode of the post-fix docstring: a maintainer reads mechanism 1's note "this is the load-bearing guard" and the explicit ValueError citation, recognizes the guard is essential, leaves it alone.

## Related

- [[cli-loaded-packs-dedup-zip-strict-builtin-packs-flip-2026-05-18]] — the bug fix whose docstring this discipline applies to.
- ce-review-convergence-rescues-sub-threshold-findings-2026-05-17 — the BOOST mode convergence mechanism that elevated the docstring finding from individual-reviewer P2/P3 to a P2/1.00 finding. The 5-way convergence on documentation is the canonical worked example of BOOST applied beyond code findings.
- ce-review-cross-reviewer-agreement-shared-misreading-false-positive-amplifier-2026-05-14 — INVERSE pattern: when 5-reviewer convergence indicates AMPLIFIED FALSE POSITIVE (reviewers misread the same forward-looking text), the same convergence signal needs the independence check to distinguish from REAL convergence (this doc's case).
- [[presence-ratchet-test-pattern-for-prose-substrings-2026-05-14]] — companion documentation-stability pattern: presence-ratchet pins prose substrings; the three-mechanism docstring pins multi-layer fix semantics.
