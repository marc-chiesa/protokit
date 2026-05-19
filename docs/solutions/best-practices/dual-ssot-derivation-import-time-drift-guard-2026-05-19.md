---
title: "Two SSOT-derived views of the same set need a module-import drift guard with diagnostic enumeration"
date: 2026-05-19
category: docs/solutions/best-practices
module: tests/parity/test_parity_package_same.py
problem_type: best_practice
component: testing_framework
severity: medium
applies_when:
  - "A parity conftest derives a frozenset from one SSOT (e.g., a RULES list walk) AND a test module derives the same logical set from a different SSOT (e.g., a RULE_ID_MAP key filter)"
  - "Both views are intentional — the co-existence is a deliberate decoupling boundary, not an oversight that should be collapsed"
  - "The two derivations live in separate modules that do not directly depend on each other"
  - "At least one derivation runs at module-import time so the drift guard can fire at collection time"
  - "No existing assertion cross-checks the two views before tests run"
tags:
  - drift-guard
  - module-import-time
  - dual-ssot
  - parity-test
  - fail-loud
  - collection-time-failure
  - rule-family
  - frozenset
---

# Two SSOT-derived views of the same set need a module-import drift guard with diagnostic enumeration

## Context

A parity test harness sometimes contains two independent derivations of the same logical set — not through carelessness, but by deliberate architectural design. In the D6c U4 case the R7 rule-id set is computed in two places:

- `tests/parity/conftest.py` derives `_PACKAGE_SAME_RULE_IDS` by walking `package_same.RULES` (the module's own registration list).
- `tests/parity/test_parity_package_same.py` derives `_PACKAGE_SAME_RULE_ID_MAP` by filtering `RULE_ID_MAP` (the BUILTIN_PACKS-backed global map) to the `package/same-*` prefix, then excluding the R8/R8b family via `_D6C_PACKAGE_DIRECTORY_RULE_IDS`.

Both views are intentional. The conftest view anchors R7 family isolation for the partition helper; the test-module view builds the buf-to-protokit translation map consumed by the parity assertions. Collapsing the two into one import would couple R7's parity invariants to R8/R8b's diagnostic surface — the very coupling [[family-aware-partition-pattern-multi-family-parity-harness-2026-05-19]] argues against.

When two derivations of the same logical set co-exist by design, **silent drift** is the dominant failure mode. There is no compiler or static analysis that enforces agreement between two frozenset-valued expressions derived from different sources. The drift only surfaces when a rule is added to one source-of-truth but not the other — and even then, the failure may be obscure test miscounting rather than an obvious assertion error, because each derivation is internally self-consistent.

Three independent D6c U4 ce:review reviewers (maintainability MAINT-2, kieran-python TG-1, correctness TG) surfaced this gap in the same review pass — a signal that the risk is structurally obvious once the two derivations are read side by side, but invisible without that juxtaposition.

## Guidance

When two SSOT-derived views of the same logical set co-exist in the same test harness, add a module-import-time drift-guard assertion immediately after both views have been constructed.

**Placement.** The assertion goes at module scope (not inside a test function or fixture), so it fires at `pytest --collect-only` time before any test body runs. This inherits the fail-loud-blast-radius posture from [[module-import-time-fixture-mapping-fail-loud-blast-radius-2026-05-18]].

**Content.** The assertion must be asymmetric — it must enumerate both sides when it fails, so the divergent rule is immediately visible without a debugger:

```python
# Drift guard: _PACKAGE_SAME_RULE_ID_MAP is derived from RULE_ID_MAP;
# _CONFTEST_R7_RULE_IDS is derived from package_same.RULES.
# Both must agree on the 7 R7 rule_ids. A divergence means a rule
# landed in one source-of-truth but not the other.
assert set(_PACKAGE_SAME_RULE_ID_MAP.values()) == _CONFTEST_R7_RULE_IDS, (
    f"R7 derivation drift: RULE_ID_MAP filter yielded "
    f"{sorted(_PACKAGE_SAME_RULE_ID_MAP.values())!r}, "
    f"package_same.RULES walk yielded "
    f"{sorted(_CONFTEST_R7_RULE_IDS)!r}."
)
```

**Import direction.** Import the conftest view into the test module (not the reverse). Conftest is the collection-time anchor; test modules are leaves:

```python
from tests.parity.conftest import _PACKAGE_SAME_RULE_IDS as _CONFTEST_R7_RULE_IDS
```

**Naming discipline.** Re-alias the imported symbol with a `_CONFTEST_` prefix so readers immediately see which derivation each name refers to. Both names appear in the assertion message; the prefix prevents confusion.

## Why This Matters

Decoupled-by-design and silently-divergent-when-buggy are not opposites — they are adjacent states separated only by a drift guard. Without the assertion, a future developer adding an eighth R7 rule to `package_same.RULES` would update conftest's `_PACKAGE_SAME_RULE_IDS` correctly but might miss the filter expression in `test_parity_package_same.py`, leaving the test-module view stuck at 7 rules. The parity test would then run against an incomplete translation map, produce incorrect pass/fail signals, and give no indication that a rule was silently excluded.

This gap is distinct from ordinary missing-test coverage. Both derivations are tested in isolation — neither side is broken on its own. Only their **agreement** is untested.

The pattern connects to the fail-loud-blast-radius family: module-import-time failures are maximally loud (they block all tests in the module from even collecting) and maximally cheap to diagnose (the error appears before any test runs). The asymmetric diagnostic message eliminates the follow-up step of running ad-hoc commands to identify the divergent rule.

There is also a connection to the `RULES`-walk SSOT discipline established at [[rule-pack-extension-ssot-rule-ids-and-test-class-naming-2026-05-12]]. That doc covered single-derivation: derive the rule-id frozenset from `RULES` rather than hand-listing. This doc covers the next layer up: when two derivations of that frozenset legitimately co-exist for decoupling reasons, validate their agreement at import time.

## When to Apply

- Two or more derivations of the same logical set (frozenset, set, list of identifiers) co-exist in the same test harness AND the co-existence is intentional (not an oversight to be collapsed).
- The derivations draw from different source-of-truth locations (e.g., one from a module's `RULES` registration, one from a global `RULE_ID_MAP` filter).
- At least one derivation is computed at module-import time so the drift guard can fire at collection time.
- The harness is collection-time-loadable — `pytest --collect-only` on the module does not require external processes or network.

Do NOT apply when the two derivations are trivially the same expression in different files — in that case collapse them to a single SSOT import instead of guarding the duplication.

## Examples

**D6c U4 concrete case.**

Before the fix — two views exist, no guard:

```python
# conftest.py:212
_PACKAGE_SAME_RULE_IDS: frozenset = frozenset(_PACKAGE_SAME_PROTO_TO_BUF.keys())

# test_parity_package_same.py:84-91
_PACKAGE_SAME_RULE_ID_MAP = {
    buf_id: protokit_id
    for protokit_id, buf_id in RULE_ID_MAP.items()
    if protokit_id.startswith("package/same-")
    and protokit_id not in _D6C_PACKAGE_DIRECTORY_RULE_IDS
}
# No assertion that these two views agree.
```

After the fix — drift guard added at module scope immediately after both views exist:

```python
from tests.parity.conftest import _PACKAGE_SAME_RULE_IDS as _CONFTEST_R7_RULE_IDS

_PACKAGE_SAME_RULE_ID_MAP = {
    buf_id: protokit_id
    for protokit_id, buf_id in RULE_ID_MAP.items()
    if protokit_id.startswith("package/same-")
    and protokit_id not in _D6C_PACKAGE_DIRECTORY_RULE_IDS
}

assert set(_PACKAGE_SAME_RULE_ID_MAP.values()) == _CONFTEST_R7_RULE_IDS, (
    f"R7 derivation drift: RULE_ID_MAP filter yielded "
    f"{sorted(_PACKAGE_SAME_RULE_ID_MAP.values())!r}, "
    f"package_same.RULES walk yielded "
    f"{sorted(_CONFTEST_R7_RULE_IDS)!r}."
)
```

**Generalized template for any two SSOT-derived views.**

```python
# After constructing both views A and B:
assert set_a == set_b, (
    f"<description> drift: <A source> yielded {sorted(set_a)!r}, "
    f"<B source> yielded {sorted(set_b)!r}."
)
```

The message should NAME the two sources (not just say "expected X, got Y") so the reader knows where to go to fix the divergence.

## Related

- [[module-import-time-fixture-mapping-fail-loud-blast-radius-2026-05-18]] — sibling discipline at the single-derivation layer. Both rely on module-import-time blast radius to surface silent failures before any test body runs. The drift-guard pattern is the cross-module dual-view variant.
- [[rule-pack-extension-ssot-rule-ids-and-test-class-naming-2026-05-12]] — established the "derive rule-id frozensets from `RULES`" discipline. This doc adds the assertion layer on top: when decoupling forces two such derivations to co-exist, validate their agreement at import time.
- [[family-aware-partition-pattern-multi-family-parity-harness-2026-05-19]] — provides the architectural rationale for why two views of the same rule-id set co-exist deliberately. The drift guard closes the correctness gap that the decoupling-by-design choice opens.
- [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]] — Case 3 (cofire-ordering inline invariant pin) is the structural analog at the dispatch-ordering layer. The drift-guard `assert` is the same shape applied to two-view derivation consistency.
- [[fixture-precondition-assertion-surfaces-silent-test-2026-05-17]] — adjacent family member; same "assert early to catch structural divergence" principle, applied at the fixture-precondition layer rather than the module-level SSOT layer.
