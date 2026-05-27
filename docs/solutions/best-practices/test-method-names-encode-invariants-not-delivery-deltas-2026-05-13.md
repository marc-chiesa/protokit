---
title: "Test method names should encode invariants, not delivery deltas"
date: 2026-05-13
category: best-practices
module: protokit
problem_type: best_practice
component: testing_framework
severity: low
applies_when:
  - "Renaming a test whose behavior was inverted by a state change introduced in a specific delivery unit"
  - "Reviewing PRs that introduce test method names containing delivery identifiers (post_X, after_Y, now_that_Z)"
  - "Naming a new test whose assertion only holds under conditions that just landed"
tags:
  - test-naming
  - invariants
  - delivery-units
  - maintainability
  - test-method-names
  - ce-review
---

# Test method names should encode invariants, not delivery deltas

## Context

During D6a Unit 4 of protokit-lint, the `test_single_pack_default_emits_no_provenance_line` test had to be inverted because the single-pack-silent branch of the R25 provenance gate became unreachable once `BUILTIN_PACKS` went multi-pack. The first rename proposed in the feature commit was:

```python
def test_builtin_default_emits_provenance_line_post_d6a_u4(self, ...):
    ...
```

ce:review's maintainability reviewer flagged the `_post_d6a_u4` suffix as a P2: the method name encoded the *moment of the U4 crossing* rather than the *steady-state behavioral invariant* the test now pins. The suffix becomes archaeology the moment Unit 5 ships, and the cost of leaving it in place compounds: every future delivery unit creates a stale historical reference in test output, CI logs, IDE navigators, and grep histories. The agent-native reviewer flagged the same observation independently.

The final rename was:

```python
def test_builtin_default_emits_provenance_line_two_packs(self, ...):
    """R25 fires on the built-in default once BUILTIN_PACKS >= 2.

    ``BUILTIN_PACKS`` shipped with one member at D2 (``naming``);
    D6a Unit 4 added a second (``enum``), tripping the R25
    ``len(loaded_packs) >= 2`` gate. The default invocation now
    emits the provenance line listing both packs and their
    contributing rule_ids.
    ...
    """
```

The delivery history is fully captured in the docstring; the method name pins the steady-state invariant.

(Session history: this was the first time in the project's commit history that a delivery-unit suffix in a test method name was explicitly flagged and corrected. No prior ce:review across D1-D5 surfaced a `_post_X` / `_after_Y` / `_now_that_Z` pattern, so the convention is now established for D6a U5 onwards.)

## Guidance

Test method names should describe the **invariant being asserted** — the steady-state behavioral condition that makes the test pass — not the delivery unit that first established it.

**Delivery-delta form (avoid):**

```python
def test_builtin_default_emits_provenance_line_post_d6a_u4(self, ...):
    ...
```

**Invariant form (use):**

```python
def test_builtin_default_emits_provenance_line_two_packs(self, ...):
    """R25 fires on the built-in default once BUILTIN_PACKS >= 2.

    ``BUILTIN_PACKS`` shipped with one member at D2 (``naming``);
    D6a Unit 4 added a second (``enum``), tripping the R25 gate...
    """
```

The method name describes the **shape of the world** when the test passes: `_two_packs`, `_when_multi_profile`, `_with_disabled_flag`, `_no_findings_on_compliant_input`, `_zero_pack_silent`. Not: `_post_d6a_u4`, `_after_phase_3`, `_now_that_R25_lands`, `_d5_canary_inverted`.

When the test exists specifically because of a delivery-time state change, the right place for that history is the docstring's first paragraph — where readers investigating a test failure or reading the code in context can find it. The method name is for ID-level surfaces (pytest output, CI logs, IDE jump-to-definition); the docstring is for narrative-level context.

If a test intentionally pins to a single delivery's behavior (a regression-pinning test that locks exact finding counts from a known-bad release), put the version identifier in the docstring or class name, not the method name. Method names like `_regression_2026_05_13` are acceptable when the date IS the invariant (the test exists to catch a specific historical regression); method names like `_post_2026_05_13_fix` are not (the date is the fix moment, which ages).

## Why This Matters

A test method's name appears in five places where delivery-unit suffixes cause friction:

1. **Pytest output** — failure lines show the full method ID; `FAILED .../test_cli_profile_resolution.py::TestR25Provenance::test_builtin_default_emits_provenance_line_post_d6a_u4` is opaque to anyone who didn't ship D6a Unit 4. The same failure under `_two_packs` is self-describing.
2. **CI logs and PR checks** — flaky tests are tracked by method ID; a delivery-unit rename breaks continuity in CI dashboards and history queries.
3. **IDE navigators / jump-to-test** — delivery-delta names cluster on `_post_d` prefixes rather than on the behavior they assert; alphabetical browse loses signal.
4. **Grep / search histories** — `grep test_post_d6a` finds the file when D6a is recent, then finds nothing six months later when the rename has happened.
5. **Rename churn** — if the policy is "suffix reflects delivery unit," every re-shaping of the behavior requires renaming the test, polluting git log and CI history with churn that adds no information.

An invariant-shaped name is permanent because the invariant is permanent. `_two_packs` will still be accurate after D6b, D7, and Phase 3 ship; `_no_builtin_rules_flag` will still be accurate at protokit 2.0. The cost of choosing a steady-state name once is paid back every time someone reads the test name without context.

## When to Apply

- **At write time** — whenever a test's behavior was established in a specific delivery unit. Default to the invariant form immediately. The session-history search across protokit-lint's D1-D6a found no prior occurrence of this pattern being flagged, which means the convention is being established now; new tests are the cheapest place to start applying it.
- **At review time** — whenever a ce:review or PR comment proposes a name ending in `_post_X`, `_after_Y`, `_now_that_Z`, or referencing a delivery identifier. Flag as P2 (maintainability) and propose the invariant rename in the same review pass.
- **When inverting an existing test** — when a test that *was* named for a single-member state must be *inverted* because the world changed (single-pack-silent → multi-pack-fires), the rename is mandatory. That is the right moment to establish the invariant name, not to encode the crossing.
- **When intentionally pinning to a snapshot** — a test that exists specifically to catch a historical regression (e.g., exact finding-count assertion locked to a known-bad commit) should put the version in the docstring or class name (`class TestRegressionFromCommitABC123:`), not the method name. The shape `_regression_<id>` is acceptable when the id IS the invariant; `_post_<id>_fix` is not.

Skip the discipline when:
- The test's name would be unintelligible without delivery context AND the docstring is the wrong place (no other test author would have context to follow the docstring) — this is rare and almost always indicates the wrong test surface.

## Examples

**Before** — `tests/schema/lint/cli/test_cli_profile_resolution.py` at commit `59fa1df` (the D6a U4 feature commit, where the test was first inverted with the wrong name):

```python
def test_builtin_default_emits_provenance_line_post_d6a_u4(
    self, clean_descriptor_set: Path,
) -> None:
    """R25 fires on the built-in default once BUILTIN_PACKS >= 2.

    Pre-D6a-U4, ``BUILTIN_PACKS`` contained only the ``naming``
    pack and this test asserted the *silent* branch of R25's
    ``len(loaded_packs) >= 2`` gate — single-pack default emits
    no provenance line because there's nothing to compose. D6a
    Unit 4 added the ``enum`` pack to ``BUILTIN_PACKS``, so the
    default invocation now ships two built-in packs and the R25
    line fires unconditionally. The test was inverted to pin the
    new behavior: built-in default emits the line, listing both
    packs and their contributing rule_ids.
    ...
    """
```

**After** — same file lines 276-306 at commit `045b4e5` (the D6a U4 ce:review follow-up):

```python
def test_builtin_default_emits_provenance_line_two_packs(
    self, clean_descriptor_set: Path,
) -> None:
    """R25 fires on the built-in default once BUILTIN_PACKS >= 2.

    ``BUILTIN_PACKS`` shipped with one member at D2 (``naming``);
    D6a Unit 4 added a second (``enum``), tripping the R25
    ``len(loaded_packs) >= 2`` gate. The default invocation now
    emits the provenance line listing both packs and their
    contributing rule_ids.

    The single-pack-silent branch of the gate is no longer
    reachable through built-in defaults. It will be re-verifiable
    when D6a Unit 9 lands ``--no-builtin-rules``.
    [Remaining docstring elided for brevity — see the shipped test
    for the full migration notes and the test body assertions.]
    """
```

The method name pins the invariant (`_two_packs` describes the gate-firing condition); the docstring captures the delivery history without polluting the test-ID surface. The sibling method `test_multi_pack_emits_provenance_line` followed the same timeless convention from the start and needed no rename — the U4 rename brought the inverted test into line with that existing convention.

## Related

- [[rule-pack-extension-ssot-rule-ids-and-test-class-naming-2026-05-12]] — natural sibling: that doc covers test *class* naming (deduplication across sibling files); this doc covers test *method* naming (invariant-vs-delivery-moment encoding). Together they cover both granularities of test-naming hygiene.
- [[apply-institutional-learnings-postdating-plan-during-ce-review-2026-05-09]] — adjacent: the discipline of absorbing post-plan ce:review findings into the docstring (rather than the method name) is one application of the "docstring holds the history, method name holds the invariant" split this doc generalizes.
- [[perf-smoke-profile-compose-across-builtin-packs-2026-05-13]] — sibling from the same ce:review pass; both surfaced as P2/P3 findings during D6a U4 ce:review and both are net-new institutional knowledge for the project.
