---
title: Module-import-time fixture mapping is a deliberate fail-loud design with module-wide blast radius
date: 2026-05-18
category: docs/solutions/best-practices
module: tests.parity
problem_type: best_practice
component: testing_framework
severity: medium
applies_when:
  - Building a parametrize source via module-import-time dict/list comprehension over N fixtures
  - Each fixture has a validity precondition (parseable config, well-formed YAML, mappable rule_id) that applies to ALL tests in the module
  - The cost of one fixture being invalid is "all tests in this module are meaningless" — not "this one test cannot run"
  - The alternative (per-test lazy validation) would produce confusing partial results (N-1 passing, 1 failing) when the contract is global
related_components:
  - tooling
tags:
  - pytest
  - module-import-time
  - fixture-mapping
  - fail-loud
  - blast-radius
  - collection-time-failure
  - parametrize-source
  - intentional-coupling
---

# Module-import-time fixture mapping is a deliberate fail-loud design with module-wide blast radius

## Context

D6b U6's `tests/parity/test_parity_package_same.py` builds `_FIXTURE_RULE_ID_MAP` at module-import time via a dict comprehension that calls `_parse_fixture_buf_yaml` for each of the 21 fixtures in `SMOKE_FIXTURES`:

```python
_FIXTURE_RULE_ID_MAP: Mapping[str, str] = {
    fixture_name: _parse_fixture_buf_yaml(fixture_name)
    for fixture_name in SMOKE_FIXTURES
}
```

`_parse_fixture_buf_yaml` reads and validates each fixture's `buf.yaml`: it checks file existence, YAML parsability, top-level `lint:` block presence, `use:` list length (must be exactly 1), entry type (must be `str`), and membership in the protokit R7 rule_id map. Any failure calls `pytest.fail(...)`.

Because `pytest.fail` inside a module-scope expression raises `Failed` during pytest collection, **a single malformed `buf.yaml` crashes the entire module's collection** — all 27 tests in `test_parity_package_same.py` show as errors, none run.

This is a deliberate design choice, not an oversight. Fixture validity is a PRECONDITION for all 27 tests, not an independent per-test concern. The alternative — lazy per-test `buf.yaml` parsing — would allow 26 tests to collect and run while 1 silently blocks on an invalid fixture, making it harder to diagnose whether the fixture was in WIP state or the `_parse_fixture_buf_yaml` logic itself was broken.

The U6 ce:review (REL-001 + RR-1) explicitly validated the tradeoff and confirmed the fail-loud-at-collection posture as correct for this module's design.

## Guidance

1. **Use module-import-time validation when the validated resource is a PRECONDITION for ALL tests in the module.** If any fixture's `buf.yaml` is malformed, no parity assertion in the module is meaningful — so surfacing the failure at collection rather than per-test is correct.

2. **Use per-test-time validation when fixtures are INDEPENDENT** and one being invalid should not block others. A module with 5 independent test scenarios where each loads its own data should validate per-test so the other 4 can still run and provide signal.

3. **Document the blast radius explicitly when adding import-time validation across N fixtures.** A developer editing `buf.yaml` for one fixture during WIP development will be blocked from running any parity test until the file is valid — this is intentional friction that enforces the fixture contract, but it must be understood as such (and ideally noted in a module-level docstring).

4. **The fail-loud mechanism at collection time is preferable to a `pytest.skip` or a silent `None` in the map:**
   - `pytest.skip` would hide a broken fixture from CI.
   - A `None` in the map would produce a confusing `KeyError` at test time with no fixture-name context.
   - `pytest.fail` at module import surfaces the failing fixture name + specific validation that failed + expected format in one place.

5. **Pair the import-time map with collection-time invariant tests** that verify the fixture set is coherent (U6 R25(a-e)):
   - R25(b) — fixture list matches `SMOKE_FIXTURES`.
   - R25(c) — bidirectional snapshot ↔ fixture reachability.
   - R25(d) — every fixture's `buf.yaml lint.use` pins exactly one rule.
   - R25(e) — non-empty snapshot's unique `type` field matches `buf.yaml use[0]`.

   These invariants run as ordinary tests (not import-time expressions) and can be diagnosed individually even if the import-time map itself is valid.

## Why This Matters

The import-time validation provides an earlier, richer diagnostic than per-test failure. A malformed `buf.yaml` error at collection time includes:

- The offending fixture name.
- The specific validation that failed (missing file, malformed YAML, missing `lint:` block, `use:` list wrong length, unknown rule_id).
- The expected format.

All in one place, before any test attempts to run. A per-test `yaml.YAMLError` at test time would show the error embedded in a test failure traceback, requiring the developer to find the fixture manually.

The pattern also prevents a subtle class of silent tests: if `_parse_fixture_buf_yaml` returned `None` on parse failure and the map silently dropped the fixture, the parametrize decorator would produce 20 tests instead of 21, and the "missing fixture" would never appear as a failure — it would simply not run. R25(b) provides a complementary guard, but import-time fail-loud is the primary defense.

**The cost** is full-module blast radius during WIP fixture editing. A developer who introduces a typo in one of the 21 `buf.yaml` files blocks all 27 parity tests in that module until the file is corrected. This is intentional friction: the fixture contract is global; broken contracts should manifest globally.

## When to Apply

**DO apply when:**
- Parametrized test modules where the parametrize source is derived from a file-system scan (fixture directories, snapshot files, config files) AND every parameter must be parseable for any test to be meaningful.
- Test modules where fixture validity is a global precondition enforced by the module's design contract (e.g., per-fixture rule scoping via `buf.yaml use:[0]` — the scope is baked into the test structure, not optional).
- When adding module-import-time validation across N fixtures where N is large enough that a per-test failure would produce confusing partial results (e.g., 26/27 tests passing with 1 collection error).

**DO NOT apply when:**
- Fixtures are independent (one bad fixture should not block the others).
- The fixture resource is expensive to load (network, large file) — use lazy loading with per-test caching instead.
- The module is shared across multiple test suites and import-time failure would cascade beyond the intended blast radius.

## Examples

**Import-time map with fail-loud parsing** (from `tests/parity/test_parity_package_same.py`):

```python
_FIXTURE_RULE_ID_MAP: Mapping[str, str] = {
    fixture_name: _parse_fixture_buf_yaml(fixture_name)
    for fixture_name in SMOKE_FIXTURES
}
```

**Fail-loud validator** (excerpt — actual U6 implementation):

```python
def _parse_fixture_buf_yaml(fixture_name: str) -> str:
    buf_yaml_path = smoke_root() / fixture_name / "buf.yaml"
    if not buf_yaml_path.is_file():
        pytest.fail(
            f"_parse_fixture_buf_yaml({fixture_name}): {buf_yaml_path} "
            f"does not exist. Every SMOKE_FIXTURES entry must have a "
            f"buf.yaml with a single-element top-level lint.use[]."
        )
    try:
        config = yaml.safe_load(buf_yaml_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        pytest.fail(
            f"_parse_fixture_buf_yaml({fixture_name}): malformed YAML at "
            f"{buf_yaml_path}: {exc}"
        )
    # ... further validation of lint.use[0] structure ...
    return _PACKAGE_SAME_RULE_ID_MAP[buf_rule_id]
```

**Collection-time invariant that complements the import-time map** (R25(b) from `test_parity_package_same.py`):

```python
def test_fixture_list_matches_smoke_assumptions() -> None:
    """R25(b): U6's local fixture-set matches SMOKE_FIXTURES."""
    u6_fixtures = set(_FIXTURE_RULE_ID_MAP.keys())
    smoke_fixtures = set(SMOKE_FIXTURES)
    assert u6_fixtures == smoke_fixtures, (
        f"U6 fixture set != SMOKE_FIXTURES.\n"
        f"  Only in U6: {sorted(u6_fixtures - smoke_fixtures)!r}\n"
        f"  Only in smoke: {sorted(smoke_fixtures - u6_fixtures)!r}"
    )
```

## Related

- [[fixture-precondition-assertion-surfaces-silent-test-2026-05-17]] — related but different scope: precondition assertion is local (one test fails when its specific value is invalid). This doc is the GLOBAL counterpart — import-time mapping that fails ALL tests in the module when any fixture is invalid. Both are members of the silent-test-confidence prevention family but operate at different abstraction layers.
- [[pytestmark-does-not-guard-module-top-imports-2026-05-02]] — same collection-time blast-radius mechanism, opposite framing: that doc treats the mechanism as a BUG (`pytestmark` cannot guard against collection-time errors). This doc treats the SAME mechanism as a deliberate design tool. Document both perspectives so future contributors know when each applies.
- [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]] — companion U6 learning: U6's parametrize source IS the import-time map described here, and the parity gate's first run caught the helper bug.
- [[programmatic-proto-fixture-builder-multi-file-rule-family-2026-05-17]] — contrast: programmatic fixtures (per-test construction) vs committed snapshots (import-time mapping). Different fixture strategies trigger different validation timing.
