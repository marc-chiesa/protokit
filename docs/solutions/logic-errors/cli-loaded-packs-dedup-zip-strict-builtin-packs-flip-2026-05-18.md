---
title: "CLI loaded_packs list grows past engine-deduplicated dict on BUILTIN_PACKS flip — zip(strict=True) length mismatch"
date: 2026-05-18
last_updated: 2026-05-21-d6d-new-u4
category: docs/solutions/logic-errors
module: src/protokit/schema/lint/cli.py
component: tooling
problem_type: logic_error
symptoms:
  - "ValueError: zip() argument 2 is shorter than argument 1 at cli.py:987 (R25 multi-pack provenance line)"
  - "--rule-pack=protokit.schema.lint.rules.package_same crashes CLI after the BUILTIN_PACKS flip adds package_same as a default-loaded pack"
  - "TestRulePackExplicitLoadIsIdempotent::test_descriptor_set_mode_recommended_profile fails on its first post-flip run with unhandled ValueError"
  - "Failure is silent at the unit-test layer — only the integration test that exercises REGISTERED+EXPLICIT state simultaneously surfaces the bug"
root_cause: logic_error
resolution_type: code_fix
severity: high
tags:
  - rule-pack
  - dedup
  - zip-strict
  - builtin-packs
  - idempotency
  - cli
  - integration-gap
  - delivery-boundary-flip
---

# CLI loaded_packs list grows past engine-deduplicated dict on BUILTIN_PACKS flip

## Problem

When a new rule pack is added to `BUILTIN_PACKS` at a delivery-boundary flip, the CLI's `loaded_packs` accumulator can hold a duplicate entry if the user also passes `--rule-pack=<pack>` for the newly-registered pack. The downstream R25 multi-pack provenance line uses `zip(strict=True)` against a dict that deduplicates naturally on `pack.__name__`; the list keeps the duplicate; lengths diverge; `ValueError` raised at runtime. The bug is invisible pre-flip (the pack wasn't in BUILTIN_PACKS so the redundant-load path was unreachable) and invisible to unit tests (which exercise either the BUILTIN-PACKS path OR the `--rule-pack` path, not both together).

## Symptoms

- `ValueError: zip() argument 2 is shorter than argument 1` raised from `src/protokit/schema/lint/cli.py:987` (the R25 provenance line). Stack trace points at the `zip(loaded_packs_tuple, _active_rule_ids_per_pack(...).values(), strict=True)` call.
- Unhandled exception — CLI exits non-zero with a raw Python traceback rather than a structured lint output. Agents parsing `--format=json` get empty stdout.
- `tests/schema/lint/test_cli_package_same_e2e.py::TestRulePackExplicitLoadIsIdempotent::test_descriptor_set_mode_recommended_profile` fails on its first post-flip run; `result.exception` is the `ValueError`.
- All 4 methods in the same test class fail with the same exception in a single test invocation — confirms the issue is in the shared invocation setup, not the per-test assertion.
- No symptom prior to the BUILTIN_PACKS flip: pre-flip, `package_same` was not in BUILTIN_PACKS, so only one of the two loaders was ever exercised in a single CLI invocation.

## What Didn't Work

Pre-implementation analysis (ADV-3 from the U7 ce:plan review) claimed that `engine.py:241-242`'s module-name idempotency guard was sufficient: when `LintEngine.load_rule_pack` is called a second time for the same module, it early-returns:

```python
# engine.py:241-242
if module.__name__ in self._loaded_module_names:
    return
```

This analysis was **technically correct at the engine layer** — the engine does no-op the second load. But the claim missed the CLI-layer accumulator that runs AFTER the engine's no-op:

```python
# cli.py:831 (pre-fix)
loaded_packs.append(_load_user_rule_pack(module_name, engine))
```

The `_load_user_rule_pack(...)` call returns the user-pack module object even when the engine's internal load is a no-op. The `loaded_packs.append(...)` then unconditionally inserts a duplicate REFERENCE into the list, regardless of whether the engine performed any registration. The frozenset-union mechanism in `LintProfile.compose` (`model.py:717-719`) absorbs duplicate rule IDs at profile-composition time, which **masked the list-length mismatch at the rule-set layer** — but the `zip(strict=True)` at the R25 provenance line sees raw list lengths, not rule IDs, so no union semantics protected it.

The three-mechanism analysis (engine idempotency + CLI accumulator + frozenset union) had a gap in the middle: the CLI accumulator was assumed to inherit the engine's dedup semantics, but it doesn't.

## Solution

CLI-level dedup check at `src/protokit/schema/lint/cli.py:841-846`, added in the D6b U7 commit (`b64b05b`):

```python
user_pack = _load_user_rule_pack(module_name, engine)
# CLI-level dedup parallels LintEngine.load_rule_pack's idempotency at
# engine.py:241-242: when a user passes --rule-pack=<pack> for a pack
# already in BUILTIN_PACKS, the engine no-ops the second load, but
# loaded_packs would still get a duplicate appended. That breaks the R25
# provenance line's zip(loaded_packs_tuple, _active_rule_ids_per_pack(...).values(), strict=True)
# below — the helper dict is keyed by pack.__name__ (so it dedups), but
# the tuple would not, yielding mismatched zip arguments. The dedup here
# keeps both data structures consistent. Bug surfaced at D6b U7's
# BUILTIN_PACKS flip of package_same per
# [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]].
if user_pack.__name__ not in {p.__name__ for p in loaded_packs}:
    loaded_packs.append(user_pack)
```

The guard MUST use `pack.__name__` (the fully-qualified module name string), not object identity (`is`). `_load_user_rule_pack` may return a different module object reference than what BUILTIN_PACKS pre-loaded (e.g., if `importlib.reload` is involved), even if both refer to the same Python module. The dict that the zip targets keys by `pack.__name__`, so the dedup criterion must match.

## Why This Works

Two parallel dedup mechanisms must be kept in sync:

1. **Engine-level idempotency** (`engine.py:241-242`): prevents the rule registry from accumulating duplicate rule registrations. Works by checking `self._loaded_module_names`. Guard against `DuplicateRuleError`.
2. **CLI-level list guard** (`cli.py:841-846`): prevents `loaded_packs` from having more entries than `_active_rule_ids_per_pack`'s dict. The dict deduplicates by `pack.__name__` as a natural consequence of dict keying; the list must be made consistent explicitly. Guard against the `zip(strict=True)` `ValueError`.

The `zip(strict=True)` at the R25 provenance line is the load-bearing invariant: it asserts that every entry in `loaded_packs_tuple` has a corresponding entry in the per-pack rule-ID dict. Strict mode was chosen precisely to make length mismatches observable rather than silently truncating — and the choice paid off. The bug surfaced immediately on the first test run after the flip because `TestRulePackExplicitLoadIsIdempotent` (formerly `TestRulePackOptIn`, renamed per KD-9 of the U7 plan) was the first test to exercise the REGISTERED+EXPLICIT state simultaneously: pack is registered via BUILTIN_PACKS AND loaded via `--rule-pack` in a single CLI invocation.

Per [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]], this is the same detection pattern as U6's `_escape_inner_quote` backslash-omission bug: an integration test caught a latent bug at the moment its enabling state existed for the first time.

## Prevention

1. **Assert the loaded_packs invariant inline** as a unit test:

   ```python
   def test_loaded_packs_no_duplicates_under_rule_pack_for_builtin():
       """loaded_packs MUST be deduplicated by pack.__name__ to keep
       R25's provenance zip(strict=True) length-aligned."""
       from click.testing import CliRunner
       from protokit.schema.lint.cli import main as lint_main
       # Invoke with --rule-pack=<pack> for a pack already in BUILTIN_PACKS:
       result = CliRunner().invoke(lint_main, [
           "--no-config",
           "--rule-pack=protokit.schema.lint.rules.package_same",
           "--profile", "recommended",
           "--format", "json",
           "<some-fixture>",
       ])
       # Pre-fix: result.exception is ValueError; post-fix: clean run.
       assert result.exception is None, (
           f"Unhandled exception: {result.exception!r}. The loaded_packs "
           f"list likely has duplicate entries — see [[cli-loaded-packs-dedup-zip-strict-builtin-packs-flip-2026-05-18]]."
       )
   ```

2. **Maintain integration tests that exercise REGISTERED+EXPLICIT state** for every member of `BUILTIN_PACKS`. The `TestRulePackExplicitLoadIsIdempotent` class is exactly that pattern post-rename. Do NOT delete or weaken it; if it becomes "tautological" in your judgment, name another test that catches the same class of bug before removing it.

3. **Audit `zip(strict=True)` callsites** when adding entries to either of the two sequences. The strict-mode `zip` is a load-bearing invariant: if the two sequences are built by different code paths (BUILTIN_PACKS loop + `--rule-pack` loop in this case), both paths must be audited for their deduplication semantics before any new entry joins either source.

4. **Same-class detection pattern**: this bug is structurally identical to U6's `_escape_inner_quote` omission (emission helper diverges from reference at parity-gate flip). Both surface at integration-test time when the test's enabling state exists for the first time. See [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]] (Case 2). The generalized pattern: **at any BUILTIN_PACKS flip, identify every accumulator (list, tuple, dict, set) that tracks pack metadata, and verify its dedup semantics against every downstream consumer (especially `zip(strict=True)` and length-based assertions).**

5. **Three-mechanism documentation discipline**: the test class docstring documenting this fix must enumerate ALL THREE coupled mechanisms (CLI dedup + engine idempotency + frozenset union), each with the SPECIFIC failure mode that surfaces if that mechanism alone is removed. See [[multi-mechanism-fix-docstring-enumerate-each-layer-failure-mode-2026-05-18]]. The 5-reviewer ce:review convergence on the stale docstring at this exact site (5 reviewers independently flagged the pre-fix docstring as misleading) is the worked example.

6. **Per-flip dedup-regression test (canonical pattern post-D6c U2)**: every BUILTIN_PACKS flip ships a sibling test file at `tests/schema/lint/test_cli_rule_pack_dedup_post_<delivery>.py` that invokes `--rule-pack=<the-newly-registered-pack>` against a minimal fixture and asserts no `ValueError` at the R25 provenance line. Three concrete instances:

   * `test_cli_rule_pack_dedup_post_d6c.py` — D6c U2 expanded the `package` pack from 2 to 4 rules (added R8 + R8b). Test asserts R8 + R8b firing counts to catch count-inflation from duplicate-pack-load.
   * `test_cli_rule_pack_dedup_post_d6d.py` — D6d U5 promoted `options/field-behavior-consistent` into BUILTIN_PACKS. The fixture omits `google/api/field_behavior.proto` so the rule short-circuits via `extension_unresolved` (no findings to count); the test asserts `result.exception is None` to catch a future broad-except absorbing the ValueError, plus `result.exit_code == 0` for the clean-fixture invariant.

   The `_cli_dedup_helpers.compile_sources_to_descriptor_set` helper is the shared SSOT for descriptor-set compilation; introduced at D6d new-U4 per MAINT-2 to prevent the third copy-paste at the next BUILTIN_PACKS flip (the [[shared-helper-third-instance-trigger]] discipline). When a third dedup-regression test ships, both existing tests should already be migrated to use the helper.

7. **`catch_exceptions=False` + `assert result.exception is None`** — pair the explicit-CliRunner-flag discipline (per [[clirunner-catch-exceptions-false-explicit-discipline-2026-05-21]]) with a positive exception-None assertion. The flag propagates exceptions cleanly; the assertion guards against a future `except Exception:` broadening in CLI code that could absorb the ValueError and silently set `exit_code=0`. Either one alone is necessary but not sufficient.

## Related

- [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]] — Case 2 (D6b U7) of the integration-test-surfaces-latent-bug pattern; this bug fix is the canonical worked example.
- [[multi-mechanism-fix-docstring-enumerate-each-layer-failure-mode-2026-05-18]] — the docstring discipline that prevents future-engineer removal of the load-bearing CLI dedup guard.
- [[dormant-code-changelog-draft-staging-delivery-boundary-2026-05-17]] — the BUILTIN_PACKS flip pattern that U7 executes; U7's delivery-boundary commit was the trigger event for this bug to surface.
- [[ce-review-convergence-rescues-sub-threshold-findings-2026-05-17]] — Case 4 (BOOST mode); the 5-reviewer convergence on the U7 docstring is the documentation analog of this code-finding convergence.
- [[clirunner-catch-exceptions-false-explicit-discipline-2026-05-21]] — companion: the `catch_exceptions=False` discipline that the per-flip dedup-regression test relies on. The ValueError propagation only works if the test harness doesn't silently absorb it.
- [[changelog-readme-snippet-fixture-byte-equivalence-2026-05-21]] — sibling delivery-boundary discipline from the same D6d new-U4 ce:review pass.
- [[migration-recipe-severity-aware-template-reuse-2026-05-21]] — sibling delivery-boundary discipline; both surfaced at the D6d new-U4 ce:review.
