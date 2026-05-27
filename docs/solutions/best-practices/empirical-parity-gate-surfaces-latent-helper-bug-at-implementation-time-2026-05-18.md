---
title: Empirical parity gate surfaces latent emission-layer bugs that unit tests cannot catch
date: 2026-05-18
last_updated: 2026-05-19-u3
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
  - A plan claim about engine ordering, grouping, or dispatch semantics is unpinned by any test — an inline invariant-pin test can surface latent bugs at the unit-test layer before the parity gate would have caught the same bug via byte-divergence
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
  - cofire-ordering
  - insertion-order
  - invariant-pin
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
- **Plan claims of the form "X happens automatically without special-case logic" (added at D6c U2 — see Case 3 below)**: when a plan elides the specific code path responsible for a behavior, an inline invariant-pin test added during /ce:review safe_auto is the cheapest way to validate the claim before the parity gate's downstream feedback loop. Authoring a unit test that asserts co-fire ordering or dispatch sequence exercises the engine's per-file dispatch path by its structural shape — the test is a load-bearing detection surface for engine-ordering / dispatch-semantic bugs, even if its stated purpose is "verify buf-parity ordering."

**Generalized boundary-flip clause (added at D6b U7 — see Case 2 below):**

The pattern extends beyond "parity gate" (the specific U6 form) to **any integration test that exercises a new boundary state for the first time at a delivery flip**. At any BUILTIN_PACKS flip (or analogous default-state transition), identify every accumulator (list, tuple, dict, set) that tracks pack/rule metadata, and verify its dedup semantics against every downstream consumer — especially `zip(strict=True)` and length-based assertions. The engine-level idempotency guard protects the rule registry, but any parallel accumulator that tracks pack metadata independently of the registry must be audited for its own dedup logic.

The integration test that catches this class of bug has a specific structural shape: **it exercises the new feature in BOTH the BUILTIN/DEFAULT path AND the EXPLICIT user-supplied path in a single invocation**. This is the REGISTERED+EXPLICIT pattern. The test's stated purpose may be different (idempotency regression, rename verification, coverage completeness) — but the structural shape is what catches the latent bug.

## Examples

### Case 1 — `_escape_inner_quote` backslash omission (D6b U6, 2026-05-18)

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

### Case 2 — `zip(strict=True)` length mismatch at BUILTIN_PACKS flip (D6b U7, 2026-05-18)

**Setup**: D6b U7's BUILTIN_PACKS flip registered `package_same` as a built-in default-loaded pack. `TestRulePackExplicitLoadIsIdempotent` (formerly `TestRulePackOptIn`, renamed at U7 per KD-9 to document the post-flip purpose) exercises `--rule-pack=protokit.schema.lint.rules.package_same` on a CLI invocation where `package_same` is ALREADY pre-loaded by BUILTIN_PACKS — the REGISTERED+EXPLICIT state for the first time.

**Bug surfaced**: `cli.py:831` unconditionally appended `user_pack` to `loaded_packs` without checking whether BUILTIN_PACKS had already inserted it. The downstream `zip(strict=True)` at `cli.py:987` received a `loaded_packs_tuple` of length N+1 but a `_active_rule_ids_per_pack` dict of length N (dict keys deduplicate naturally by `pack.__name__`), raising `ValueError: zip() argument 2 is shorter than argument 1`.

**Detection pattern**: The test was authored for a different stated purpose (idempotency regression after the U7 KD-9 rename) but happened to be the right STRUCTURAL SHAPE to exercise the REGISTERED+EXPLICIT state simultaneously — the exact boundary condition the pre-flip code had never encountered.

**Fix** (`src/protokit/schema/lint/cli.py:841-846`):

```python
user_pack = _load_user_rule_pack(module_name, engine)
if user_pack.__name__ not in {p.__name__ for p in loaded_packs}:
    loaded_packs.append(user_pack)
```

**Three-mechanism contract documented post-fix** (per [[multi-mechanism-fix-docstring-enumerate-each-layer-failure-mode-2026-05-18]]):

1. **CLI-level dedup at cli.py:841-846** — load-bearing guard against the `zip(strict=True)` ValueError.
2. **Engine-level idempotent load at engine.py:241-242** — `if module.__name__ in self._loaded_module_names: return` — guard against `DuplicateRuleError`.
3. **Profile-level frozenset union at model.py:717-719** — defense-in-depth backstop that absorbs duplicate rule_ids at composition time.

### Case 3 — Cofire-ordering unit invariant pin surfaces engine pack-load-order bug at U2 (D6c U2, 2026-05-19)

**Setup**: The D6c plan's KTD-9 stated R8 + R8b co-fire ordering on a shared file would be rule_id-alphabetic "without special-case logic" because the engine uses `sorted(profile.rule_ids - loaded_ids)`. No test pinned the invariant. ce:review's testing reviewer added `TestCofireScenario::test_cofire_per_file_rule_id_alphabetic_ordering` during the safe_auto pass to encode the plan-time claim.

**Bug surfaced**: KTD-9's cited `sorted(...)` was at `engine.py:445` — the **unloaded-rule warning loop**, not the per-file dispatch loop. The actual per-file dispatch iterates `group_by_kind[ElementKind.FILE]` in `_loaded_specs` insertion order (i.e., pack-RULES-tuple order). The initial U2 drop listed R8 before R8b in `RULES`, so co-fire output had R8 first — opposite of buf v1.69.0's alphabetic ordering. The new test failed on its **first run**, before any U3 parity gate existed:

```
AssertionError: per-file co-fire order must be rule_id-alphabetic;
got ['package/same-directory', 'package/directory-same-package']
```

**Detection pattern**: A ce:review-added test pinning a plan-time invariant. The test's structural shape was simply "assert the order of findings on the shared file." That trivial shape was sufficient to exercise the engine's per-file dispatch order — the one property KTD-9's claim was wrong about. The test was authored as a presence-ratchet (its **stated purpose**), but its structural shape made it the right surface to catch the latent bug.

**Fix** (`src/protokit/schema/lint/rules/package.py`):

```python
# **R8b before R8 ordering is LOAD-BEARING for buf v1.69.0 parity.**
# Engine dispatches in pack-registration order (insertion-ordered dict);
# buf emits DIRECTORY_SAME_PACKAGE before PACKAGE_SAME_DIRECTORY.
RULES: tuple[Callable[..., None], ...] = (
    check_package_defined,
    check_package_directory_match,
    check_directory_same_package,    # R8b BEFORE R8 — load-bearing
    check_package_same_directory,
)
```

Plus an inline comment on the `RULES` tuple documenting that the ordering is load-bearing for buf-parity, and a docstring on the ratchet test explaining what it pins.

**Why this is a distinct case from Cases 1 + 2**: the detection surface is a **unit-level invariant-pin test** added by ce:review, not an integration test or snapshot parity gate. The bug was latent from the initial RULES-tuple definition; the test made the ordering contract explicit AT U2 time, before U3's parity gate would have surfaced the same bug via byte-divergence with buf. The cofire-ordering test is the earliest of the three detection surfaces in D6c — it fires at the unit-test layer in the same CI job as the feature code, with no snapshot or BUF_BINARY dependencies.

### Case 4 — Phase-0 fixture under-coverage causes multi-declared+packageless template gap at U3 (D6c U3, 2026-05-19)

**Setup**: D6c U2 shipped R8b (``package/directory-same-package``) with 2 ``violation_kind`` arms: ``standard`` and ``empty-mixed``. The plan's KTD-4 (b) claim — "buf produces exactly one declared-package value in the empty-mixed template even if multiple declared packages exist" — was based on Phase 0's verification fixture at ``/tmp/d6c_phase0/empty_pkg/``, which contained 1 declared-package file + 2 packageless files. That fixture's 1-declared case produces ``Package "acme.foo" and file with no package detected within directory "."`` — the template U2 implemented.

**Bug latency**: U2's ``check_directory_same_package`` picked the alphabetically-first declared package name and composed the single-template message. For the multi-declared+packageless case (2 declared packages + 1 packageless file in the same directory), protokit emitted ``Package "acme.bar" and file with no package detected within directory "pkg"`` — but buf v1.69.0 actually emits a DISTINCT template: ``Multiple packages "acme.bar,acme.foo" and file with no package detected within directory "pkg"``.

**Detection**: U3 committed the ``no-package-mixed`` fixture (2 declared + 1 packageless). The parity gate failed on the first run:

```
assert_parity_multi_file(no-package-mixed): protokit ↔ buf
finding-set divergence within scoped rule_ids ['package/directory-same-package'].
  Only-in-protokit (2): [...'Package "acme.bar" and file with no package...'...]
  Only-in-buf       (2): [...'Multiple packages "acme.bar,acme.foo" and file with no package...'...]
```

**Fix**: Split R8b's 2-arm classifier into 3 arms:

- ``standard`` — 2+ declared, no packageless.
- ``empty-mixed-single`` (renamed from ``empty-mixed``) — exactly 1 declared + ≥1 packageless. Phase 0's verified template.
- ``empty-mixed-multi`` (NEW) — 2+ declared + ≥1 packageless. Uses ``Multiple packages "X,Y" and file with no package detected within directory "Z".``

The pre-1.0 carve-out at [[closed-literal-discriminator-bump-trigger-2026-05-17]] permits the rename without bumping ``_LINT_JSON_SCHEMA_VERSION``.

**Detection pattern**: parity gate's first run against a **newly committed fixture** that covers a sub-case absent from Phase 0's verification scope. Distinct from Case 3 (which a unit-level invariant-pin test caught at U2 time, before any parity gate ran). The bug was invisible at the unit-test layer because both ``empty-mixed`` and the correct ``empty-mixed-multi`` produced non-zero findings — only byte-divergence against buf's recorded snapshot made the misclassification observable. The structural shape that mattered: a fixture exercising a specific input-space corner (multi-declared + packageless) that buf treats as semantically distinct.

### Shared pattern across Cases 1, 2, 3, and 4

All four cases share these structural properties (the table covers Cases 1–4):

| Property | Case 1 (U6 — emission layer) | Case 2 (U7 — accumulator layer) | Case 3 (U2 — dispatch layer) | Case 4 (U3 — template discrimination) |
|----------|------------------------------|----------------------------------|------------------------------|---------------------------------------|
| Test type | Integration / parity gate (REGISTERED+SNAPSHOT) | Integration / idempotency test (REGISTERED+EXPLICIT) | Unit / invariant-pin test (rule_id-ordering) | Integration / parity gate (first run against new fixture) |
| First exercises | Parity-verified state for non-ASCII proto values | Registered+explicit state (BUILTIN + --rule-pack) | Engine dispatch order across two co-firing rules | Multi-declared+packageless message template |
| Bug latency | Present since U4b; latent until parity gate ran | Present since R25 provenance line; latent until BUILTIN_PACKS flip | Present since initial RULES tuple definition; latent until cofire test asserted the ordering | Present since U2's 2-arm definition; latent until the U3 ``no-package-mixed`` fixture was committed |
| Detection occasion | First parity-gate invocation after the gate was built | First test invocation after the BUILTIN_PACKS flip | First run of the ce:review-added cofire test | First parity-gate run against the newly committed fixture |
| Phase-0 root | Non-ASCII values absent from programmatic fixtures | Pre-flip API shape never covered by integration tests | "Automatic via sorted(...)" claim left as text, not test | Phase-0 verification fixture had 1-declared + 2-packageless only — missing the 2+-declared sub-case |
| Detected by | A test renamed/created at the flip to document the post-flip purpose | Same pattern — `TestRulePackOptIn` → `TestRulePackExplicitLoadIsIdempotent` rename at U7 | A new ce:review-added presence-ratchet test in the safe_auto pass | The U3-committed parity fixture itself; no parallel invariant pin existed |
| Fix shape | Helper-layer correction + presence-ratchet against the contract | CLI-layer dedup guard + three-mechanism docstring against contract drift | Tuple reorder + load-bearing-ordering inline comment | 3-arm classifier split + new violation_kind + new fixture |

The generalization extends from Cases 1+2: **the test that surfaces these bugs has a STRUCTURAL SHAPE (exercises the new boundary state for the first time, or pins a previously-untested invariant) that is independent of its STATED PURPOSE (parity verification, idempotency regression, ordering pin).** When authoring delivery-boundary commits OR reviewing a plan claim of the form "X happens automatically without special-case logic," identify which tests will exercise the boundary or claim for the first time — they are the load-bearing detection mechanism even if they were written for other reasons.

**Phase-0 fixture under-coverage sub-pattern (Cases 1 and 4)**: Both cases share a further refinement of the structural shape — the bug surfaced because the Phase 0 verification fixture, while locally valid, did NOT cover the boundary sub-case that triggered the divergence. Case 1's PHP namespace value was absent from programmatic ASCII-only fixtures. Case 4's 2+ declared + packageless combination was absent from Phase 0's 1-declared + N-packageless fixture. **Phase 0 verification proved the claim true on the tested input, but a different input class triggered a different code path in the reference tool.** When a plan KTD asserts "buf produces X in situation Y," enumerate Y's sub-cases and verify each has a fixture in the parity gate's committed corpus before relying on the claim — missing sub-cases are the most likely site of template / encoding bugs that survive all unit tests.

**Three complementary detection surfaces** in this family:

1. **Parity gate (external oracle)** — Cases 1 + 4. Snapshot comparison against the reference tool's recorded output. Catches byte-level emission divergences including Phase-0-incomplete sub-cases.
2. **Integration idempotency test (REGISTERED+EXPLICIT boundary state)** — Case 2. Exercises the new boundary condition that didn't exist before a default flip. Catches accumulator dedup gaps.
3. **Unit invariant-pin test (inline-asserted claim)** — Case 3. Encodes a plan-time claim as a runtime assertion. Catches engine-ordering / dispatch-semantic bugs at the earliest layer.

The invariant pin (Case 3) is the **earliest** of the three — it fires at U2 time with no snapshot dependencies, no BUF_BINARY, no integration setup. The parity gate (Cases 1 + 4) is the **only surface with organic expansion into unexplored input regions** — as new fixtures are committed, the gate automatically validates new corners without requiring a priori knowledge of where bugs hide. Authoring invariant pins during ce:review safe_auto passes is the lowest-friction way to convert plan-text claims into executable contracts; committing parity fixtures for each enumerated sub-case is the lowest-friction way to expand the gate's coverage into Phase-0 blind spots.

## Related

- audit-wire-format-before-claiming-sibling-parity-2026-05-03 — planning-time complement: this doc catches at implementation time what that doc catches at plan time.
- [[buf-parity-divergence-documentation-discipline-2026-05-13]] — what to do once the snapshot gate fires and divergence is confirmed (four-site documentation discipline + `_PARITY_EXCEPTIONS` entry).
- [[programmatic-proto-fixture-builder-multi-file-rule-family-2026-05-17]] — contrast: programmatic fixtures (unit-test) vs committed NDJSON snapshots (parity gate). Different fixture strategies for different verification goals.
- [[fixture-precondition-assertion-surfaces-silent-test-2026-05-17]] — sibling pattern at a different abstraction layer (fixture precondition vs emission-layer parity).
- ce-review-convergence-rescues-sub-threshold-findings-2026-05-17 — Case 4 documents the FIX-INDUCED SECOND-ORDER bug pattern (the U6 escape-fix introduced an orphan-backslash bug caught by cross-reviewer convergence in ce:review). The 5-reviewer convergence on the U7 docstring drift is a documentation-layer analog.
- [[truncation-guard-odd-count-discipline-for-doubled-escape-pairs-2026-05-18]] — the second-order bug the U6 escape-fix introduced (orphan backslash from the truncation guard).
- [[cli-loaded-packs-dedup-zip-strict-builtin-packs-flip-2026-05-18]] — Case 2's bug fix. The REGISTERED+EXPLICIT state exercises both the engine-level idempotency guard AND the CLI-layer accumulator independently; both must have consistent dedup semantics. A `zip(strict=True)` between two data structures built by different code paths is the load-bearing invariant that makes the mismatch observable rather than silently truncating.
- [[multi-mechanism-fix-docstring-enumerate-each-layer-failure-mode-2026-05-18]] — the documentation discipline that prevents future-engineer removal of the load-bearing Case 2 CLI dedup guard.
- [[rules-tuple-insertion-order-load-bearing-engine-dispatch-2026-05-19]] — Case 3's bug from the implementation-error angle. Documents the engine pack-load-order dispatch contract + the RULES-tuple reorder fix.
- plan-review-verify-prior-art-citations-2026-05-15 — planning-time discipline that complements Case 3. The "inherited assumption" sub-pattern is the planning-phase analog: claims inherited from a parent brainstorm should be empirically re-verified. KTD-9's "automatic via sorted(...)" claim was an inherited assumption that survived planning unchecked.
- [[dict-shaped-message-template-multi-arm-rule-violation-kind-2026-05-19]] — the rule-design pattern Case 4's fix landed on. R8b's 3-arm split (`standard` + `empty-mixed-single` + `empty-mixed-multi`) is the canonical multi-kind-rule structure; the doc's "Per-arm params contract" and "Hard-pinning the expected kind set" subsections both grew out of Case 4's parity-gate discovery.
- [[closed-literal-discriminator-bump-trigger-2026-05-17]] — Case 4's `/empty-mixed` → `/empty-mixed-single` rename did not bump `_LINT_JSON_SCHEMA_VERSION` per the pre-release carve-out clause added to that doc as part of the U3 ce:review follow-ups.
- [[family-aware-partition-pattern-multi-family-parity-harness-2026-05-19]] — the partition-logic discipline that the parity gate (Cases 1 + 4) requires once the framework supports multiple rule families. The R8/R8b parity gate at U3 needed family-aware union constants to keep R7 + R8/R8b in the same `assert_parity_multi_file` helper without prefix-based carve-out drift.
- [[structural-anchor-test-sha-collision-prone-empty-fixtures-2026-05-19]] — the structural integrity discipline that protects the parity gate from invisible fixture swaps. Case 4 added two empty-snapshot fixtures (matched-dir, single-file-dir); without the anchor, a rename-without-snapshot-rename would silently pass the gate.
