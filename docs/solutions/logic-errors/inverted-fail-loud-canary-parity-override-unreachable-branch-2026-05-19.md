---
title: Inverted fail-loud — the `elif` branch that "catches a source_spec revert" was structurally unreachable on the failure scenario it documented
date: 2026-05-19
category: docs/solutions/logic-errors
module: tests/parity/conftest.py + protokit.schema.lint.rules.naming
problem_type: logic_error
component: testing_framework
severity: high
symptoms:
  - "`_CANARY_PARITY_OVERRIDE` dict retained post-KTD-11 with docstring claiming it serves as a fail-loud safety assertion site against a source_spec revert"
  - "The asserting `elif` branch was inside `_build_rule_id_map`'s `elif buf_id is None` arm — unreachable for the canary when its source_spec carries the `buf:` prefix"
  - "On the failure scenario the docstring described (source_spec reverted to AIP-122 URL), `buf_id` would become None, the canary would fall through the override path, the nested `if protokit_id in mapping` would be False (canary not yet in mapping), and the AssertionError would not fire — silent fallback through the override path"
  - "4-way ce:review convergence at D6c U2: correctness (P2/0.95), testing (P2/0.91), maintainability (P2/0.97), adversarial (P3/0.85) — all caught the unreachability"
root_cause: logic_error
resolution_type: code_fix
related_components:
  - development_workflow
tags:
  - unreachable-code
  - fail-loud
  - canary
  - parity-override
  - reachability-trace
  - ce-review-convergence
  - source-spec
  - ktd-11
  - docstring-claim-vs-code-behavior
---

# Inverted fail-loud — the `elif` branch that "catches a source_spec revert" was structurally unreachable on the failure scenario it documented

## Problem

`_build_rule_id_map` in `tests/parity/conftest.py` used an `if/elif` pair to handle the `naming/snake-case-fields` canary after D6c U2 KTD-11 corrected its `source_spec` from `"https://google.aip.dev/122"` to `"buf:FIELD_LOWER_SNAKE_CASE"`. The intent: keep the `_CANARY_PARITY_OVERRIDE` dict as a fail-loud safety check that would catch any future revert of the canary's source_spec back to the AIP-122 URL.

The implementation inverted the failure-mode trace. Post-KTD-11, `_extract_buf_rule_id(spec.source_spec)` returns a non-None `buf_id` for the canary (because the source_spec carries the `buf:` prefix), so the canary lands in `mapping` via the `if buf_id is not None` branch and the `elif protokit_id in _CANARY_PARITY_OVERRIDE` arm is **never reached**. On the failure scenario the docstring claimed to catch — a source_spec revert to the AIP-122 URL — `_extract_buf_rule_id` would return `None`, the `elif` would execute, the nested `if protokit_id in mapping` check would be False (the canary is not yet in `mapping` because the `if` arm didn't fire), the AssertionError would not raise, and the override would silently insert the canary into `mapping` via the override value — bypassing every safety check the docstring claimed.

ce:review caught this with 4-way convergence: correctness (P2/0.95) traced the control flow, testing (P2/0.91) noted no test could exercise the elif arm for the canary, maintainability (P2/0.97) flagged the future-engineer trap, adversarial (P3/0.85) constructed the source_spec-revert scenario showing the branch never fires.

## Symptoms

- No runtime failure — the override path worked correctly post-KTD-11 because the canary landed in `mapping` via the `if buf_id is not None` branch.
- The bug was a **silent safety hole**: if any future developer reverted the canary's `source_spec` for any reason (e.g., reverting an unrelated commit, an automated migration, a merge conflict resolution), the parity gate would continue passing because the override fallback would re-insert the canary into `mapping` without any signal that the source_spec contract had been broken.
- The docstring's claim — "retained as fail-loud safety: `_build_rule_id_map` asserts the override entry collides with the directly-picked-up rule, which catches an accidental revert of the canary's source_spec back to the AIP-122 URL" — was the opposite of what the code did.
- ce:review surfaced the issue at D6c U2 (4-way convergence). The /ce:review safe_auto pass routed it `gated_auto` → `downstream-resolver` per the merged severity P2/1.00.

## What Didn't Work

**Pre-fix code (commit `d28641f`, then retained through commit `6b9a609` with a docstring asserting fail-loud safety):**

```python
_CANARY_PARITY_OVERRIDE: Mapping[str, str] = {
    "naming/snake-case-fields": "FIELD_LOWER_SNAKE_CASE",
}

# inside _build_rule_id_map() loop:
for pack in BUILTIN_PACKS:
    for fn in pack.RULES:
        spec = get_lint_spec(fn)
        protokit_id = spec.rule_id
        buf_id = _extract_buf_rule_id(spec.source_spec)
        if buf_id is not None:
            if protokit_id in mapping and mapping[protokit_id] != buf_id:
                raise AssertionError(...)  # duplicate guard — fires correctly
            mapping[protokit_id] = buf_id
        elif protokit_id in _CANARY_PARITY_OVERRIDE:
            if protokit_id in mapping:
                raise AssertionError(
                    f"_CANARY_PARITY_OVERRIDE entry {protokit_id!r} "
                    f"collides with a buf:-sourced rule already in "
                    f"BUILTIN_PACKS. The override is dead code; "
                    f"either remove it or change the rule's "
                    f"source_spec away from a buf: prefix."
                )
            mapping[protokit_id] = _CANARY_PARITY_OVERRIDE[protokit_id]
```

**Failure-mode trace** (the exact scenario the docstring claimed to catch):

1. Developer reverts `naming.py:80` from `source_spec="buf:FIELD_LOWER_SNAKE_CASE"` back to `source_spec="https://google.aip.dev/122"`.
2. `_extract_buf_rule_id("https://google.aip.dev/122")` returns `None`.
3. `buf_id is not None` is False → skip the `if` arm.
4. `protokit_id in _CANARY_PARITY_OVERRIDE` is True → enter `elif`.
5. `protokit_id in mapping` is **False** (canary not added by the `if` arm; this is the canary's first iteration).
6. The nested AssertionError does **not** fire.
7. `mapping[protokit_id] = _CANARY_PARITY_OVERRIDE[protokit_id]` silently re-inserts the canary using the override value.
8. Parity tests continue passing because the mapping is "correct" — the only signal that the source_spec contract was broken is the direct-value assertion in `tests/schema/lint/test_canary_naming.py:73`, which is in a different test module.

The docstring claim said the `elif`'s nested `if protokit_id in mapping` was the load-bearing fail-loud check. In reality, that nested check could only fire if the canary had ALREADY landed in `mapping` via the `if buf_id is not None` branch — which is the post-KTD-11 happy path, **the opposite** of the revert scenario the docstring described.

## Solution

Remove the `_CANARY_PARITY_OVERRIDE` dict and `elif` branch entirely. Replace with a **post-walk assertion** that checks the final state of `mapping` directly:

**After (commit `d1dc094`):**

```python
def _build_rule_id_map() -> Mapping[str, str]:
    """Walk ``BUILTIN_PACKS`` and derive ``protokit_id -> buf_id``.

    **Canary inclusion** (post-D6c U2 KTD-11): the
    ``naming/snake-case-fields`` rule ships with
    ``source_spec="buf:FIELD_LOWER_SNAKE_CASE"`` and lands in the
    mapping via the standard ``buf:`` prefix path — no override
    layer needed. The post-walk assertion below guards the canary
    against an accidental revert of its source_spec back to the
    AIP-122 URL (which would silently drop it from the parity
    numerator).
    """
    mapping: dict[str, str] = {}
    for pack in BUILTIN_PACKS:
        for fn in pack.RULES:
            spec = get_lint_spec(fn)
            protokit_id = spec.rule_id
            buf_id = _extract_buf_rule_id(spec.source_spec)
            if buf_id is not None:
                if protokit_id in mapping and mapping[protokit_id] != buf_id:
                    raise AssertionError(...)
                mapping[protokit_id] = buf_id
            # else: rule is protokit-only — excluded from parity.
    # Post-walk assertion: the canary must land in the mapping via
    # the ``buf:`` source_spec path. If this fails, the canary's
    # source_spec was reverted to a non-``buf:`` value (e.g., the
    # AIP-122 URL it carried pre-D6c U2) and the rule has silently
    # dropped from the parity numerator.
    assert "naming/snake-case-fields" in mapping, (
        "canary rule 'naming/snake-case-fields' dropped from "
        "RULE_ID_MAP — source_spec may have reverted away from "
        "'buf:FIELD_LOWER_SNAKE_CASE'. See test_canary_naming.py "
        "for the direct value contract; KTD-11 in docs/plans/2026-"
        "05-18-003-feat-d6c-r8-r8b-cross-file-package-rules-plan.md "
        "for the audit-trail rationale."
    )
    return mapping
```

## Why This Works

The pre-fix guard was a **conditional** check inside a branch that the failure mode could not reach. The post-fix guard is **unconditional**: after the walk completes, the assertion checks the final state of `mapping` directly. There is no intermediate state where the canary can re-enter via a back-door — if the canary is absent from `mapping` at this point, the assertion fires unconditionally.

The control-flow shape is symmetric to the failure mode. The failure mode is "canary missing from `mapping`"; the assertion is `assert "naming/snake-case-fields" in mapping`. Symptom and guard share the same predicate.

Two-source defense remains intact:
1. **`tests/schema/lint/test_canary_naming.py:73`** — direct-value assertion `spec.source_spec == "buf:FIELD_LOWER_SNAKE_CASE"`. Primary contract; fires at unit-test layer when the source_spec changes.
2. **`tests/parity/conftest.py:_build_rule_id_map` post-walk assert** — integration-layer backstop; fires at parity-harness collection time when the canary drops from RULE_ID_MAP. Catches the broader failure mode of "canary excluded from parity numerator for any reason" — broader than just a source_spec revert.

## Prevention

1. **Before claiming a code path provides a fail-loud backstop, trace whether the path is reachable in the failure mode it's supposed to catch.** Write the failure scenario as a concrete trace: "to fire this assertion, the following conditions must hold: X, Y, Z." Then check whether the documented failure mode satisfies X+Y+Z. If not, the backstop is unreachable and the docstring is wrong.
2. **Prefer post-walk / post-loop assertions for invariants over conditional in-loop guards.** A post-walk assert checks the final state of a data structure unconditionally. An in-loop guard can be skipped by control-flow paths that don't hit the guard branch. For canary-style invariants ("X must be in mapping by end of loop"), post-walk is structurally correct; in-loop is brittle.
3. **Pair documentation defenses with executable defenses.** The pre-fix code relied on a docstring claim that was inverted from the code's behavior. Docstrings drift; assertions either fire or they don't. When documenting safety, the docstring should describe an **observed** behavior of an executable assertion, not claim a behavior the assertion does not have.
4. **ce:review's multi-persona convergence is the right surface for this class of bug.** Correctness alone might trace the control flow but miss the docstring claim. Adversarial alone might construct the failure scenario but miss the existing guard. Convergence across correctness (control flow), testing (no test exercises the elif arm for the canary), maintainability (future-engineer trap from the misleading docstring), and adversarial (revert scenario) provides 4 independent angles on the same bug — see ce-review-convergence-rescues-sub-threshold-findings-2026-05-17 Case 5.

## Related

- ce-review-convergence-rescues-sub-threshold-findings-2026-05-17 — Case 5 documents the 4-way BOOST convergence pattern that caught this bug. The discriminator: convergence on "this path is unreachable" across diverse lenses (correctness traces the flow, testing notes no test can exercise it, maintainability flags the future-engineer trap, adversarial constructs the failure scenario) is a reliable signal that the backstop does not exist.
- [[multi-mechanism-fix-docstring-enumerate-each-layer-failure-mode-2026-05-18]] — sibling discipline at a different angle. That doc covers docstrings that correctly enumerate each mechanism's role but elide one of them. This doc covers a docstring that misrepresented a mechanism's role entirely. Both are documentation-correctness bugs caught by multi-reviewer convergence; the failure modes differ.
- audit-wire-format-before-claiming-sibling-parity-2026-05-03 — Layer C (operational semantics) is the related discipline at planning time. "Do both sides guarantee the same behavior?" is the question that should have been asked when the docstring claimed fail-loud safety.
- [[structural-pin-inspect-getsource-untestable-collision-branch-2026-05-13]] — sibling pattern for **legitimately** untestable branches. The canary `elif` was untestable for a different reason — not because no fixture could exercise it, but because the documented failure mode could never reach it. The mitigations differ: structural-pin tests for legitimately-untestable branches; restructuring for unreachable-in-failure-mode branches.
- [[capture-setup-without-dispatch-false-test-confidence-2026-05-17]] — false confidence from a test that never fires. This is the production-code analog: false confidence from a guard that never fires in the failure mode it documents.
