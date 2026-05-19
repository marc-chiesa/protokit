---
title: Family-aware union constants for parity-test partition logic — one inclusion set + one builder per rule family, module-level union for partition
date: 2026-05-19
category: docs/solutions/best-practices
module: tests/parity/conftest.py
problem_type: best_practice
component: testing_framework
severity: medium
applies_when:
  - "A parity test harness (conftest or shared fixture module) supports two or more named rule families with distinct rule_id → buf_rule_id mappings"
  - "A three-way partition (in-scope / over-firing / unknown) routes findings to the correct family's expected set during `assert_parity_multi_file` or analogous comparison"
  - "Adding a new rule family currently requires changes to the partition logic itself rather than additions to data constants"
  - "Per-call rebuild of the proto-to-buf mapping incurs O(N · M) walk overhead across M parametrized test invocations"
  - "Two families share a rule_id prefix (e.g., R7's ``package/same-*`` and R8's ``package/same-directory``), forcing carve-out logic"
related_components:
  - tooling
tags:
  - parity-test
  - partition-logic
  - rule-family
  - conftest
  - module-level-constants
  - assert-parity-multi-file
  - over-firing
  - frozenset
  - ktd-12
  - r7
  - r8
  - r8b
---

# Family-aware union constants for parity-test partition logic — one inclusion set + one builder per rule family, module-level union for partition

## Context

D6b U6 built protokit's first parity test framework for R7 (PACKAGE_SAME_*): `tests/parity/conftest.py` exposed `_PACKAGE_SAME_PROTO_TO_BUF` (mapping protokit rule_id → buf rule_id for the R7 family) and `_PACKAGE_SAME_RULE_IDS` (frozenset of mapping keys). The `assert_parity_multi_file` helper used these constants for a three-way partition:

- **in-scope** — `rule_id in protokit_rule_ids` (this fixture's expected rules) → compare to recorded buf finding.
- **over-firing** — `rule_id in _PACKAGE_SAME_RULE_IDS` but not in `protokit_rule_ids` → an R7-family rule fired outside the per-fixture scope (KD-7 over-firing complement).
- **unknown** — `rule_id.startswith("package/same-")` but not in `_PACKAGE_SAME_RULE_IDS` → typo'd rule_id (ADV-3 ce:review finding).

D6c U2 added R8 (`package/same-directory`) and R8b (`package/directory-same-package`). Two structural problems surfaced:

1. **Prefix-based filtering accumulates carve-out debt.** R8 (`package/same-directory`) shares the `package/same-` prefix with R7 but belongs to a different architectural family (cross-file directory/package rules vs per-file package-option rules). The partition logic needed a carve-out conditional: `rule_id.startswith("package/same-") and rule_id != "package/same-directory"`. A future family adding more `package/same-X` rules would compound the conditional.

2. **Per-call rebuilds are O(N) per parametrized test invocation.** The U2 prototype rebuilt the family union dict inside `assert_parity_multi_file` (~31 parametrized invocations across R7 + R8/R8b). The walk through `RULES` plus the source_spec filter ran once per call when it could run once at module import.

D6c U3's ce:review (Finding #8, P2/0.85, 2-way maintainability + kieran-python convergence) flagged both. The safe_auto fix applied KTD-12 from the D6c plan:

1. Each rule family gets THREE module-level constants: an inclusion set, a `_PROTO_TO_BUF` dict, and a `_RULE_IDS` frozenset.
2. Two union constants (`_FAMILY_PROTO_TO_BUF`, `_FAMILY_RULE_IDS`) merge all families at module level.
3. `assert_parity_multi_file` consumes only the union constants and DOES NOT change when a new family is added.
4. The cross-family carve-out for `package/same-directory` becomes implicit in the inclusion-set definition rather than buried in the partition conditional.

## Guidance

**For each rule family in the parity test framework, define three module-level constants. Extend the two module-level union constants when a new family is added. The partition logic stays unchanged across family additions.**

### Per-family block (template)

```python
# --- Family N: <description> -----------------------------------------------
_FAMILY_N_INCLUSION: frozenset[str] = frozenset({
    "<rule_id_1>",
    "<rule_id_2>",
    # ... explicit list — cross-family rule_ids that share a prefix MUST be
    # explicitly INCLUDED or EXCLUDED here (carve-out is data, not logic).
})


def _build_family_n_proto_to_buf() -> Mapping[str, str]:
    """Walk module.RULES filtered by inclusion set; return {protokit_id: buf_id}.

    Filter by inclusion-set membership (not prefix) so cross-family
    rule_ids that share a prefix don't leak. A future family addition
    requires extending the inclusion set, not the partition logic.
    """
    mapping: dict[str, str] = {}
    for fn in _family_n_module.RULES:
        spec = get_lint_spec(fn)
        if spec.rule_id not in _FAMILY_N_INCLUSION:
            continue
        buf_id = _extract_buf_rule_id(spec.source_spec)
        if buf_id is not None:
            mapping[spec.rule_id] = buf_id
    return mapping


#: Mapping consumed by partition logic. Built once at module import; not
#: rebuilt per parametrized call.
_FAMILY_N_PROTO_TO_BUF: Mapping[str, str] = _build_family_n_proto_to_buf()

#: Frozenset for fast membership checks. Derived from the mapping's keys
#: at module import (single source of truth).
_FAMILY_N_RULE_IDS: frozenset[str] = frozenset(_FAMILY_N_PROTO_TO_BUF.keys())
```

### Module-level union constants (one per harness)

```python
#: Union of all families' protokit_id → buf_id mappings. Consumed by
#: `assert_parity_multi_file`'s family-aware partition. The dict merge
#: surfaces collisions loudly (Python dict-spread of same-key entries
#: uses the last one) — keep families' inclusion sets disjoint.
_FAMILY_PROTO_TO_BUF: Mapping[str, str] = {
    **_FAMILY_1_PROTO_TO_BUF,
    **_FAMILY_2_PROTO_TO_BUF,
    # ... extend per family
}

#: Union of all families' rule_ids. Consumed by partition logic.
_FAMILY_RULE_IDS: frozenset[str] = (
    _FAMILY_1_RULE_IDS
    | _FAMILY_2_RULE_IDS
    # | ... extend per family
)
```

### Partition logic (does not change per family addition)

```python
def assert_parity_multi_file(
    protokit_findings: Sequence[Mapping[str, Any]],
    buf_findings: Sequence[BufFinding],
    protokit_rule_ids: frozenset[str],
    fixture_scenario: str,
) -> None:
    in_scope: list[tuple[str, str, str]] = []
    over_fire: list[tuple[str, str, str]] = []
    unknown: list[tuple[str, str, str]] = []

    for f in protokit_findings:
        rule_id = str(f.get("rule_id", ""))
        path = _normalize_buf_path(str(f.get("location", "")))
        message = str(f.get("message", ""))
        if rule_id in protokit_rule_ids:
            in_scope.append((_FAMILY_PROTO_TO_BUF[rule_id], path, message))
        elif rule_id in _FAMILY_RULE_IDS:
            over_fire.append((rule_id, path, message))
        elif <family-specific prefix typo detection>:
            unknown.append((rule_id, path, message))
        # else: rule outside known families — exclude from assertion.

    # ... fail-loud on unknown / over-fire; multiset compare in_scope to buf
```

## Why This Matters

**Prefix-based partition logic accumulates carve-out debt linearly with family count.** Each new family that shares a prefix with an existing family adds another conditional. Three families with shared prefixes produce a conditional chain that requires cross-family knowledge to understand. Explicit inclusion sets move the family-membership decision to the **data** (each family owns its rule_id set), not the **logic**. The union is mechanical.

**Per-call rebuild is O(N) per parametrized invocation.** Building the union dict inside `assert_parity_multi_file` for each parametrized test multiplies the `RULES`-walk cost by the parametrize count. Module-level union pays the cost once at import; every test invocation reads the pre-built mapping in O(1).

**The inclusion set is the executable form of the delivery plan's KTD.** D6c's KTD-12 said "derive R7-family + R8/R8b frozensets from `RULE_ID_MAP`, new arm for R8/R8b in three-way partition." The inclusion set IS that derivation, executed at module load. If a rule_id drifts in source (e.g., a rename without conftest update), the inclusion set fails loudly at module import time rather than silently routing the renamed rule to the "unknown" bucket.

**The `assert_parity_multi_file` helper becomes a stable contract.** Once family-aware, the partition logic doesn't need updates when new families ship. Adding family N+1 is purely additive at the data layer. This is the test-harness analog of "extend, don't modify" — the helper code is closed for modification but open for extension via union-constant additions.

## When to Apply

- When adding a second (or Nth) rule family to an existing parity test conftest that uses `assert_parity_multi_file` or equivalent three-way partition.
- When any two rule families share a rule_id prefix (e.g., `package/same-*` and `package/directory-*` both start with `package/`).
- When the per-call mapping rebuild exceeds ~10 RULES entries (the O(N) overhead becomes noticeable in parametrized test suites with 20+ fixtures per family).
- When the delivery plan's KTD section explicitly cites a partition extension (D6c's KTD-12 was the trigger for this pattern's first instantiation).

## Examples

### D6c U3 R8/R8b family addition (the canonical case)

```python
# R7 family (D6b U6)
_PACKAGE_SAME_INCLUSION = frozenset({
    "package/same-go-package", "package/same-java-package",
    "package/same-csharp-namespace", "package/same-php-namespace",
    "package/same-ruby-package", "package/same-swift-prefix",
    "package/same-java-multiple-files",
})
_PACKAGE_SAME_PROTO_TO_BUF = _build_package_same_proto_to_buf()
_PACKAGE_SAME_RULE_IDS = frozenset(_PACKAGE_SAME_PROTO_TO_BUF)

# R8/R8b family (D6c U2 → U3 KTD-12)
_D6C_PACKAGE_DIRECTORY_RULE_IDS: frozenset[str] = frozenset({
    "package/same-directory",         # R8 — IN this family despite
                                       # "package/same-" prefix overlap with R7
    "package/directory-same-package",  # R8b
})
_PACKAGE_DIRECTORY_PROTO_TO_BUF: Mapping[str, str] = (
    _build_package_directory_proto_to_buf()
)
_PACKAGE_DIRECTORY_RULE_IDS: frozenset[str] = frozenset(
    _PACKAGE_DIRECTORY_PROTO_TO_BUF.keys()
)

# Module-level union (consumed by assert_parity_multi_file)
_FAMILY_PROTO_TO_BUF: Mapping[str, str] = {
    **_PACKAGE_SAME_PROTO_TO_BUF,
    **_PACKAGE_DIRECTORY_PROTO_TO_BUF,
}
_FAMILY_RULE_IDS: frozenset[str] = (
    _PACKAGE_SAME_RULE_IDS | _PACKAGE_DIRECTORY_RULE_IDS
)
```

The carve-out for `package/same-directory` is now data, not logic: it's an explicit member of `_D6C_PACKAGE_DIRECTORY_RULE_IDS`, not a `!= "package/same-directory"` carve-out inside a conditional. A reviewer sees the family membership at the inclusion-set definition site.

### Extending for a hypothetical third family (D6d field rules)

```python
# Field-naming family (hypothetical D6d)
_D6D_FIELD_INCLUSION = frozenset({
    "field/lower-snake-case",
    "field/no-required",
    # ...
})
_FIELD_PROTO_TO_BUF = _build_field_proto_to_buf()
_FIELD_RULE_IDS = frozenset(_FIELD_PROTO_TO_BUF)

# Extend union constants (assert_parity_multi_file unchanged):
_FAMILY_PROTO_TO_BUF = {
    **_PACKAGE_SAME_PROTO_TO_BUF,
    **_PACKAGE_DIRECTORY_PROTO_TO_BUF,
    **_FIELD_PROTO_TO_BUF,           # new line
}
_FAMILY_RULE_IDS = (
    _PACKAGE_SAME_RULE_IDS
    | _PACKAGE_DIRECTORY_RULE_IDS
    | _FIELD_RULE_IDS                # new line
)
```

Three lines of data added; zero lines of logic changed. The partition helper continues to work without modification.

### Before vs after the per-call-rebuild fix

**Before (per-call rebuild, U2 prototype):**

```python
def assert_parity_multi_file(...) -> None:
    # ... inside the helper, rebuilt every parametrized invocation:
    family_proto_to_buf = {
        **_PACKAGE_SAME_PROTO_TO_BUF,
        **_PACKAGE_DIRECTORY_PROTO_TO_BUF,
    }
    family_rule_ids = _PACKAGE_SAME_RULE_IDS | _PACKAGE_DIRECTORY_RULE_IDS
    # ... use them ...
```

**After (module-level union, U3 fix):**

```python
# Module level (one-time at import):
_FAMILY_PROTO_TO_BUF = {...}
_FAMILY_RULE_IDS = ...

def assert_parity_multi_file(...) -> None:
    # ... use _FAMILY_PROTO_TO_BUF + _FAMILY_RULE_IDS directly ...
```

The walk + filter + merge runs once at module import, not 31 times across parametrized invocations.

## Related

- [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]] — the single-family parity gate this pattern scales. Multi-family extension preserves the same Case 1/4 detection semantics while broadening the rule coverage.
- [[dual-view-prewalk-accumulator-cross-file-rule-dispatch-2026-05-19]] — the production-code analog: dual-view accumulator (by_package + by_directory) computed once, threaded into context. Same "build once at boundary, consume in O(1)" principle at the rule-engine layer.
- [[module-import-time-fixture-mapping-fail-loud-blast-radius-2026-05-18]] — import-time blast-radius discipline. The inclusion-set + builder functions follow the same posture: any drift in source rule_ids surfaces at collection time, not at assertion time.
- [[programmatic-proto-fixture-builder-multi-file-rule-family-2026-05-17]] — fixture-creation discipline. The family-aware partition complements the fixture builder: fixtures are the inputs; the inclusion-set constants are the routing logic for the outputs.
- [[buf-parity-divergence-documentation-discipline-2026-05-13]] — what to do once the family-aware partition surfaces a divergence (four-site documentation per family).
- [[cli-loaded-packs-dedup-zip-strict-builtin-packs-flip-2026-05-18]] — sibling pattern at the CLI layer (multiple structures that need consistent dedup semantics). Same architectural principle: when two data structures track the same domain, factor them into one source so consistency is mechanical, not maintained-by-hand.
