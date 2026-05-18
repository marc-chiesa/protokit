---
title: Empirical parity gate surfaces latent emission-layer bugs that unit tests cannot catch
date: 2026-05-18
category: docs/solutions/best-practices
module: protokit.schema.lint.rules.package_same
problem_type: best_practice
component: testing_framework
severity: high
applies_when:
  - A lint-rule family has internal unit/e2e tests written against ASCII-only or hand-crafted fixtures
  - The rule emits a composed string by calling an escape helper (`_escape_message_value`, `_truncate_values_payload`, etc.)
  - An empirical parity gate compares protokit NDJSON output against committed reference snapshots for the same proto inputs
  - The reference snapshots were generated from real proto files that exercise non-ASCII or escape-bearing values (e.g., PHP namespace with backslash)
related_components:
  - tooling
tags:
  - empirical-parity
  - snapshot-testing
  - coverage-complementarity
  - emission-layer
  - buf-parity
  - escape-sequences
  - latent-bug
  - package-same
---

# Empirical parity gate surfaces latent emission-layer bugs that unit tests cannot catch

## Context

D6b U6 built an end-to-end parity gate for the R7 PACKAGE_SAME_* rule family: `tests/parity/test_parity_package_same.py` runs protokit's lint output against 21 SHA-pinned buf v1.69.0 NDJSON snapshots (committed at U4a, integrity-locked by `tests/schema/lint/test_buf_smoke_recorded_checksums.py`).

The gate's first run immediately caught a real helper bug: `_escape_inner_quote` (the U4b-era value-escape helper, renamed to `_escape_message_value` in U6 ce:review follow-ups) only escaped `"` → `\"` but did not escape `\` → `\\`. For PHP namespace values containing backslashes (e.g., `option php_namespace = "Foo\\X"`), protokit emitted `Foo\X` in the finding message where buf v1.69.0 emits `Foo\\X`. Two of the 21 parametrized parity cases — `mixed-value-php-namespace` and `mixed-presence-php-namespace` — failed on the first invocation, each displaying a structured diagnostic with the actual-vs-expected message text.

U4b's ~80 internal unit and e2e tests did NOT catch this because those tests assert against protokit's own expected output. They encode whatever the helper produces and verify internal self-consistency. The fixtures were generated programmatically via `tests/schema/lint/rules/fixtures/package_same/proto_templates.py` with ASCII-only values; backslash-bearing PHP namespace values were never exercised through the helper.

The parity gate asserts against buf's independently-recorded output, providing a distinct coverage class: it answers "does protokit's emission match the reference tool's emission?" rather than "does protokit's emission match what protokit's tests say it should emit?"

## Guidance

1. **Commit recorded snapshots from the reference implementation before writing protocol logic, not after.** The snapshots become the external oracle; internal tests become the consistency check. (D6b U4a captured 21 buf v1.69.0 NDJSON snapshots BEFORE U4b shipped the R7 helper — exactly this discipline.)
2. **Run the parity gate on the first implementation commit.** If the gate catches a regression immediately, the system is working correctly — not premature.
3. **Keep internal unit tests and parity snapshots as complementary, non-overlapping test layers:**
   - Unit tests verify *structural invariants* — escape-pair completeness, sort order, profile membership, message template format.
   - Parity tests verify *byte-level equivalence with the reference tool* — the same proto input produces byte-identical wire-format output.
4. **When extending a helper that affects message formatting, run the parity suite first.** Before touching internal tests, run the parity suite. Touching internal tests first creates circular reasoning: the test fixture is updated to match the helper's new output, the test passes, and any divergence from the reference is silently hidden.
5. **Snapshot the helper's actual escape contract empirically.** The U6 fix was:
   ```python
   def _escape_message_value(value: str) -> str:
       """Escape \\ then " for buf-v1.69.0 message-text byte-parity."""
       return value.replace("\\", "\\\\").replace('"', '\\"')
   ```
   Step ordering matters: backslash first so newly-inserted backslashes from the quote-escape step are not re-doubled. The empirical gate validated this ordering on the FIRST RUN by failing 2 of 21 fixtures with PHP namespace values.

## Why This Matters

Internal tests are inherently circular with respect to message format: they test "does our output match our expectation" rather than "does our output match the reference". A helper that consistently produces the wrong encoding passes all internal tests because both the assertion fixture and the production path share the same bug.

The parity gate eliminates this circularity by making the reference tool's NDJSON output the authoritative oracle. This is exactly the scenario U6 was designed to detect: a helper-edit regression that would have survived indefinitely in an internal-only test regime.

The gate's value proposition is asymmetric:
- **If the gate finds 0 divergences on day 1**: it provides regression-insurance for future helper edits + a reusable harness for adjacent multi-file rules (D6c R8 candidate).
- **If the gate finds divergences on day 1**: it pays for itself unambiguously — the fix lands BEFORE the rule reaches users, and the snapshot anchors the contract going forward.

U6 hit the second outcome. Both outcomes justify the gate; the latter is the failure mode the architecture is built to make catchable.

## When to Apply

- Any rule family whose finding messages contain structured text derived from user-supplied proto option values (especially escape-sensitive strings: backslashes, quotes, control characters).
- When extending a shared helper that affects message formatting across a rule family (all 7 PACKAGE_SAME_* rules share `_escape_message_value` and `_truncate_values_payload`).
- When adding a new escape class to an existing helper: the parity gate must be run before and after, treating the before-run as baseline validation and the after-run as regression confirmation.
- When committing recorded snapshots: verify they cover the escape classes present in real-world proto files. PHP namespace values routinely contain backslash namespace separators (`Vendor\Package\X`); SQL-like values may contain quotes; Java enum values may contain unicode escapes.

## Examples

**The failure pattern the gate caught (D6b U6 first parity run, 2026-05-18):**

```
# Bug: backslash in php_namespace value not doubled
# option php_namespace = "Foo\\X" (literal value: Foo\X)
# protokit emitted in message text: Foo\X
# buf v1.69.0 recorded in NDJSON:   Foo\\X
```

The ce:review diagnostic shape (structured per-fixture):
```
assert_parity_multi_file(mixed-presence-php-namespace): protokit ↔ buf
finding-set divergence within scoped rule_ids ['package/same-php-namespace']
(buf-equivalent ['PACKAGE_SAME_PHP_NAMESPACE']).
  Only-in-protokit (3): [('PACKAGE_SAME_PHP_NAMESPACE', 'a.proto', '...Foo\\X...')]
  Only-in-buf       (3): [('PACKAGE_SAME_PHP_NAMESPACE', 'a.proto', '...Foo\\\\X...')]
```

**After the fix in `src/protokit/schema/lint/rules/package_same.py`:**

```python
def _escape_message_value(value: str) -> str:
    """Escape `\\` then `"` for buf-v1.69.0 message-text byte-parity.

    Two-step escape applied per declared value BEFORE composition:
      1. Each literal `\\` becomes `\\\\` (existing backslashes are doubled).
      2. Each literal `"` becomes `\\"` (quotes gain a leading backslash).

    Step ordering matters: backslash-first means the new backslashes
    inserted by step 2's quote-escape are NOT re-doubled by step 1.
    """
    return value.replace("\\", "\\\\").replace('"', '\\"')
```

**Gate parametrization (21 cases, import-time construction at `tests/parity/test_parity_package_same.py`):**

```python
_FIXTURE_RULE_ID_MAP: Mapping[str, str] = {
    fixture_name: _parse_fixture_buf_yaml(fixture_name)
    for fixture_name in _SMOKE_FIXTURES  # 21 fixtures from tests/_buf_helpers.py
}


@pytest.mark.parametrize(
    ("fixture_name", "protokit_rule_id"),
    list(_FIXTURE_RULE_ID_MAP.items()),
    ids=[_case_id(n, r) for n, r in _FIXTURE_RULE_ID_MAP.items()],
)
def test_parity_byte_matches_recorded_snapshot(
    fixture_name: str, protokit_rule_id: str
) -> None:
    """Assert protokit's PACKAGE_SAME_*-scoped findings byte-match buf's
    recorded snapshot for the single rule_id pinned by that fixture's
    `buf.yaml use:[0]`."""
    # ... invoke protokit lint, parse buf snapshot, assert_parity_multi_file ...
```

## Related

- [[audit-wire-format-before-claiming-sibling-parity-2026-05-03]] — planning-time complement: this doc catches at implementation time what that doc catches at plan time.
- [[buf-parity-divergence-documentation-discipline-2026-05-13]] — what to do once the snapshot gate fires and divergence is confirmed (four-site documentation discipline + `_PARITY_EXCEPTIONS` entry).
- [[programmatic-proto-fixture-builder-multi-file-rule-family-2026-05-17]] — contrast: programmatic fixtures (unit-test) vs committed NDJSON snapshots (parity gate). Different fixture strategies for different verification goals.
- [[fixture-precondition-assertion-surfaces-silent-test-2026-05-17]] — sibling pattern at a different abstraction layer (fixture precondition vs emission-layer parity).
- [[cross-reviewer-convergence-catches-fix-induced-second-order-bug-2026-05-18]] — when the FIX for a parity-gate-surfaced bug introduces a second-order bug, cross-reviewer convergence in ce:review catches it.
- [[truncation-guard-odd-count-discipline-for-doubled-escape-pairs-2026-05-18]] — the second-order bug the U6 escape-fix introduced (orphan backslash from the truncation guard).
