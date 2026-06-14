---
title: Engine dispatches per-file lint rules in pack-registration order — not by rule_id sort
date: 2026-05-19
category: docs/solutions/logic-errors
module: protokit.schema.lint.engine + protokit.schema.lint.rules.package
problem_type: logic_error
component: tooling
severity: medium
symptoms:
  - "Co-fire ordering test asserted R8b (DIRECTORY_SAME_PACKAGE) emits before R8 (PACKAGE_SAME_DIRECTORY) on a shared file (matching buf v1.69.0 + KTD-9 alphabetic claim) but the test failed with the rules in reverse order"
  - "Plan KTD-9 cited `sorted(profile.rule_ids - loaded_ids)` at engine.py:445 as the mechanism producing alphabetic co-fire ordering, but that path is the UNLOADED-rule warning loop — it has no effect on per-file emit order"
  - "Without the fix, U3's parity gate against buf v1.69.0 would have failed with byte-divergence on any co-fire fixture (R8 + R8b firing on the same file)"
root_cause: logic_error
resolution_type: code_fix
related_components:
  - testing_framework
tags:
  - engine-dispatch
  - rules-tuple
  - insertion-order
  - cofire-ordering
  - buf-parity
  - plan-claimed-automatic
  - load-bearing
  - package-rules
  - ktd-9
---

# Engine dispatches per-file lint rules in pack-registration order — not by rule_id sort

## Problem

The D6c plan's KTD-9 stated that R8 + R8b co-fire ordering on a shared file would be rule_id-alphabetic "without special-case logic" because the engine uses `sorted(profile.rule_ids - loaded_ids)` at `engine.py:445`. The plan-author assumed this sort governed per-file dispatch order. It does not — that `sorted(...)` call is the **unloaded-rule warning loop**, which has no effect on the emit order of loaded specs.

The actual per-file dispatch order is determined by `_loaded_specs` insertion order. `LintEngine._loaded_specs` is a plain Python dict, populated in pack-registration order by `load_rule_pack(pack)` walking `pack.RULES` in tuple order. At `engine.py:466-476` the engine filters loaded specs by `profile.rule_ids` and buckets them into `group_by_kind[ElementKind.FILE]` **without sorting**; `_dispatch_file` at `engine.py:810` iterates that list in bucket-insertion order.

Result: the position of a `@lint_rule`-decorated function within its pack's `RULES` tuple directly determines emit sequence among rules sharing the same `ElementKind`.

## Symptoms

- `TestCofireScenario::test_cofire_per_file_rule_id_alphabetic_ordering` fails on first run with:

  ```
  AssertionError: per-file co-fire order must be rule_id-alphabetic;
  got ['package/same-directory', 'package/directory-same-package']
  ```

- U3's empirical parity gate against buf v1.69.0 would have failed byte-comparison on any co-fire fixture (R8 + R8b firing on a shared file), since buf emits `DIRECTORY_SAME_PACKAGE` before `PACKAGE_SAME_DIRECTORY` per its own alphabetic-on-rule-id convention (provenance — buf v1.69.0; ratchet anchor pinned by the recorded NDJSON snapshots in tests/schema/lint/test_buf_smoke_recorded_checksums_package_directory.py — do not bump).
- No runtime failure prior to the test addition — the bug was latent until an invariant-pin test exercised the cofire boundary.

## What Didn't Work

- **Relying on KTD-9's plan-text claim about engine behavior.** KTD-9 cited `sorted(profile.rule_ids - loaded_ids)` as the alphabetic-ordering mechanism, but tracing the call site shows that line drives the **unloaded-rule warning loop** at `engine.py:445`, not per-file dispatch. The two paths share the `sorted(...)` token but are structurally unrelated.
- **Assuming "no special-case logic needed" meant the desired ordering was free.** The desired ordering required a specific `RULES`-tuple ordering — not the absence of code, but the presence of intentional code-by-positioning. The plan elided this.

## Solution

Reorder the `RULES` tuple in `src/protokit/schema/lint/rules/package.py` so R8b precedes R8, then document the ordering as load-bearing inline:

**Before** (initial U2 drop, commit `d28641f`):

```python
RULES: tuple[Callable[..., None], ...] = (
    check_package_defined,
    check_package_directory_match,
    check_package_same_directory,    # R8 first — wrong order
    check_directory_same_package,    # R8b second — wrong order
)
```

**After** (commit `6b9a609`):

```python
# Module-level RULES tuple read by ``LintEngine.load_rule_pack``.
#
# **R8b before R8 ordering is LOAD-BEARING for buf v1.69.0 parity.** The
# engine dispatches rules in pack-registration order within each
# ``ElementKind`` bucket (``LintEngine._loaded_specs`` is an
# insertion-ordered dict consumed by ``_dispatch_file`` without an
# intermediate sort). Buf v1.69.0 emits ``DIRECTORY_SAME_PACKAGE`` (R8b)
# BEFORE ``PACKAGE_SAME_DIRECTORY`` (R8) when both fire on the same file
# — alphabetical by buf's rule_id. To match buf byte-for-byte on co-fire
# scenarios, R8b must appear before R8 in this tuple.
RULES: tuple[Callable[..., None], ...] = (
    check_package_defined,
    check_package_directory_match,
    check_directory_same_package,    # R8b BEFORE R8 — load-bearing
    check_package_same_directory,
)
```

Plus a cofire-ordering presence-ratchet test pinning the contract:

```python
def test_cofire_per_file_rule_id_alphabetic_ordering(
    self, tmp_path: Path,
) -> None:
    """KTD-9: per-file co-fire order is rule_id-alphabetic."""
    report = _run_full_pack(tmp_path, cofire_fixtures, rule_ids)
    on_shared_file = [
        f for f in report.findings if f.params["file"] == "pkg/a.proto"
    ]
    rule_ids_on_shared = [f.rule_id for f in on_shared_file]
    assert rule_ids_on_shared == [
        "package/directory-same-package",   # alphabetically first
        "package/same-directory",
    ], (
        f"per-file co-fire order must be rule_id-alphabetic; "
        f"got {rule_ids_on_shared}"
    )
```

## Why This Works

`LintEngine._loaded_specs` is an insertion-ordered dict. `load_rule_pack(pack)` walks `pack.RULES` in tuple order, registering each `@lint_rule`-decorated function via `_register_spec(spec)` which `dict[rule_id] = spec`s into `_loaded_specs`. The per-`run()` filter at `engine.py:467` iterates `self._loaded_specs.items()` in insertion order. The bucket at `group_by_kind[ElementKind.FILE]` is a `list` appended to in iteration order. `_dispatch_file` iterates the bucket without sorting.

End-to-end: the only place ordering is established is at pack load time. The `RULES` tuple in `package.py` is therefore the canonical ordering surface for any rule in that pack; tuple position is the contract.

The `sorted(profile.rule_ids - loaded_ids)` at `engine.py:445` only orders the **synthesized `LintRuntimeWarning(category="unloaded_rule")`** entries for rule_ids that are in `profile.rule_ids` but not in `_loaded_specs`. It has no effect on findings emitted by loaded rules.

## Prevention

1. **Treat plan claims of "X happens automatically without special-case logic" as hypotheses requiring an invariant-pin test.** A plan that elides the specific code path responsible for a behavior should be flagged at /ce:work time — if the claim is true, write the test; if the test fails, the claim was wrong. The cofire-ordering test was added during D6c U2's ce:review safe_auto pass per [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]] Case 3.
2. **When two code paths share a token (`sorted(...)`, `dict.update`, `frozenset.union`, etc.), trace the SPECIFIC path being relied on.** Similarly-shaped neighbor calls can produce opposite behaviors. The engine had two `sorted(...)` calls within 100 lines of each other — one for unloaded-rule warnings, one absent from the per-file dispatch. The plan-author conflated them.
3. **Document `RULES`-tuple position as load-bearing whenever buf-parity depends on it.** The comment block above `RULES` in `package.py` is the canonical citation: it names the exact engine mechanism (`_loaded_specs` insertion-ordered dict, `_dispatch_file` non-sorting iteration) and states the conditions under which the ordering would become incidental (a future engine refactor adding per-bucket sort).
4. **Cofire fixtures should be in the unit-test layer, not deferred to the parity-gate layer.** The cofire-ordering test does not require BUF_BINARY or recorded snapshots — it asserts against protokit's own observable emit order. Authoring it at U2 catches engine-ordering bugs before they reach the parity-gate run at U3, with a much tighter feedback loop.

## Related

- [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]] — Case 3 of that doc documents this same bug from the test-surface angle (an inline invariant pin firing on its first run, before the U3 parity gate).
- plan-review-verify-prior-art-citations-2026-05-15 — sibling planning-time discipline. The "inherited assumption" sub-pattern is the planning-phase analog: claims inherited from a parent brainstorm should be empirically re-verified. KTD-9's "automatic via sorted(...)" claim was an inherited assumption that survived planning unchecked.
- audit-wire-format-before-claiming-sibling-parity-2026-05-03 — Layer C (operational semantics) is the same discipline applied to claims about runtime behavior. "Do both sides guarantee the same ordering?" is the layer-C question the plan elided.
- [[dual-view-prewalk-accumulator-cross-file-rule-dispatch-2026-05-19]] — D6c U1's accumulator that feeds R8 + R8b. The dispatch-order bug is on the consumer side of the accumulator, not the accumulator itself.
- [[cli-loaded-packs-dedup-zip-strict-builtin-packs-flip-2026-05-18]] — sibling pattern: two data structures (`loaded_packs` list + `_active_rule_ids_per_pack` dict) with different dedup semantics produced a `zip(strict=True)` failure. Here, two `sorted(...)` calls with different scopes produced a wrong-ordering assumption.
