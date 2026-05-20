---
title: "WeakKeyDictionary + id-of-resettable-engine-attribute for per-engine, per-run state isolation in rule callables"
date: 2026-05-20
category: docs/solutions/best-practices
module: src/protokit/schema/lint/rules/options/field_behavior.py
problem_type: best_practice
component: tooling
severity: high
applies_when:
  - "A rule callable needs per-engine isolation of mutable state (e.g., dedup sets, counters, caches) without modifying the engine's public surface"
  - "The same LintEngine instance may have engine.run() called more than once in the same process (MCP/IDE session runtimes, test suites that reuse engines)"
  - "The state must reset with each engine.run() call, not just with each engine instantiation"
  - "The rule callable is a module-level function (not a closure constructed per run), so per-factory initialization is not available"
  - "The engine already resets some known mutable attribute (list, dict) per run-entry that the rule can observe"
tags:
  - weak-reference
  - engine-state
  - per-run-reset
  - dedup
  - id-sentinel
  - mcp-runtime
  - runtime-warning
  - isolation
  - silent-failure
---

# WeakKeyDictionary + id-of-resettable-engine-attribute for per-engine, per-run state isolation

## Context

protokit-lint's rule callables are module-level functions that receive a `LintContext` subclass on each invocation. A rule may need to emit a runtime warning at most ONCE per (rule_id, file_name) per `engine.run()` — for example, D6d U2's `options/field-behavior-consistent` emits `extension_unresolved` on the first file that triggers it and suppresses duplicates thereafter for the rest of the walk. The dedup state must satisfy two simultaneous constraints:

1. **Isolated per engine** — two `LintEngine` instances running concurrently (or sequentially in the same process) must not share dedup state. A module-level `set` shared across all engines violates this.
2. **Reset per `engine.run()` call** — the same engine may be reused across multiple calls in MCP/IDE D6e+ runtimes, in library callers using a single engine across multiple compile results, or in `engine.reset()`-based flows. `engine.run()` already resets `engine._runtime_warnings = []` at run-entry (`engine.py:418`), but a module-level dict entry keyed on the engine persists after the reset. The second `run()` would silently emit zero warnings even when it should emit one.

Neither a module-level `set` nor a closure-captured `set` (initialized once per closure factory call) satisfies both requirements simultaneously. The `WeakKeyDictionary` + id-of-resettable-attribute pattern closes both.

ce:review caught the failure mode via two-way reviewer convergence (D6d U2, 2026-05-20): correctness COR-1 reasoning from the engine.py:418 reset site + adversarial ADV-1 reasoning from a concrete two-call breakage construction. Both reached the same conclusion independently — the second `engine.run()` emits zero warnings on the same engine. See [[ce-review-convergence-rescues-sub-threshold-findings-2026-05-17]] Case 8.

## Guidance

**Use `weakref.WeakKeyDictionary[LintEngine, tuple[int, set[...]]]` as the module-level state store. Key each entry on the engine; store `(id(engine._runtime_warnings), dedup_set)` as the value. On each rule invocation, check whether the stored id matches the CURRENT `id(engine._runtime_warnings)` to detect a new run.**

Step-by-step:

1. **Declare the module-level WeakKeyDictionary** with the engine type as key and a `(int, set)` tuple as value. Use a `TYPE_CHECKING` forward-ref for `LintEngine` to avoid the circular import:

   ```python
   from typing import TYPE_CHECKING
   import weakref

   if TYPE_CHECKING:
       from protokit.schema.lint.engine import LintEngine

   _UNRESOLVED_SEEN: "weakref.WeakKeyDictionary[LintEngine, tuple[int, set[tuple[str, str]]]]" = (
       weakref.WeakKeyDictionary()
   )
   ```

2. **Recover the engine reference** at the rule callable's call site. This is the interim path documented at [[bound-method-self-extraction-rule-to-engine-callback-2026-05-20]] (also captured in the D6d U2 review). The structural fix is a second engine-injected callable on the LintContext mixin; the WeakKeyDictionary pattern is independently correct regardless of which path supplies the engine reference.

3. **Perform the lookup-with-reset** before accessing the dedup set:

   ```python
   engine = _engine_for_ctx(ctx)  # extracts via ctx._emit_fn.__self__ today
   current_run_id = id(engine._runtime_warnings)
   state = _UNRESOLVED_SEEN.get(engine)
   if state is None or state[0] != current_run_id:
       # New engine (no prior state) OR same engine but fresh
       # _runtime_warnings list (= new run() call).
       seen: set[tuple[str, str]] = set()
       _UNRESOLVED_SEEN[engine] = (current_run_id, seen)
   else:
       _, seen = state
   ```

4. **Check-and-record** before emitting:

   ```python
   key = (rule_id, file_name)
   if key in seen:
       return
   seen.add(key)
   # emit the runtime warning via the engine's runtime_warnings accumulator
   ```

**Why this works:** `engine.run()` assigns a FRESH `list` object to `engine._runtime_warnings` at every run-entry. A fresh list has a new `id()`. The id-mismatch detection is a cheap, non-invasive per-run reset signal that requires no engine API change and no public reset hook. The pattern is generic: any attribute the engine deterministically replaces per run can serve as the run-epoch sentinel.

**GC safety:** `WeakKeyDictionary` holds only a weak reference to the engine. When the engine is garbage-collected (e.g., at test teardown or session end), the entry is removed automatically. No memory leak across engine lifecycles.

**Thread safety:** a single engine should not be run concurrently per the existing `LintEngine` contract (`engine.py:134-149`). If concurrent per-engine use ever becomes a requirement, guard `_UNRESOLVED_SEEN` with a `threading.Lock`. For D6d U2's pre-1.0 surface, single-threaded execution is assumed.

## Why This Matters

**The silent-failure mode is severe.** A second `engine.run()` call on the same engine with identical input emits ZERO `extension_unresolved` warnings, because the dedup set from the first run was retained. No exception is raised. No test fails unless the test explicitly calls `run()` twice and asserts on the second result. The bug is invisible on the CLI (one `run()` per process) but would silently break long-lived MCP/IDE D6e+ runtimes that maintain an engine across user sessions or that use `engine.reset()` to restart a walk.

**Detection requires testing the second-run contract explicitly.** A regression test for this pattern MUST call `engine.run()` twice and assert both results contain the expected warnings — not just the first. A test that only exercises one `run()` call gives false confidence. The D6d U2 regression test `TestCrossRunDedupReset::test_second_run_reemits_warning_on_same_engine` is the canonical shape.

**The anti-pattern (module-level `set`) was the natural first draft.** Module-level `set[(rule_id, file_name)]` is simple, but it leaks across engines AND across runs. A closure-captured `set()` (initialized once per closure factory invocation, as used in D6d U1's synthetic-rule path at `_custom_rules.py`'s `_make_synthetic_closure`) is per-closure-factory-invocation but NOT per `engine.run()` — the U1 synthetic rules have the same second-run bug latent in them; the CLI mitigates by constructing a fresh engine per invocation, but the Python library API does not. **Backport flagged for D6d U3+.**

**The `WeakKeyDictionary + id()` pattern is the only approach that satisfies both isolation dimensions without engine API changes.** Other paths considered + rejected:

- A new `engine.register_per_run_reset(callback)` hook — requires engine API change; the callback list itself becomes new shared state.
- Resetting `_UNRESOLVED_SEEN[engine]` from a `finally` block in `engine.run()` — requires the engine to know about the rule's per-engine state, which inverts the dependency direction.
- Using `weakref.WeakValueDictionary` keyed on `id(engine._runtime_warnings)` — leaks `id` values across runs as old keys persist; not GC-friendly.

The chosen pattern's cost is one tuple-wrap + one id-comparison per rule invocation. Both are O(1) and negligible.

## When to Apply

Apply this pattern when ALL of the following hold:

1. A rule callable needs mutable state that outlives a single `__call__` invocation (e.g., a dedup set built incrementally across all files in one `run()`).
2. The state must be **isolated per engine** — sharing state across engines would cause cross-contamination.
3. The state must **reset per `engine.run()` call** — persistent state across runs on the same engine produces incorrect results.
4. The engine already resets some known attribute per run (e.g., `_runtime_warnings`, `_findings`). The id-of-that-attribute is the cheapest reset signal available without a new public hook.

**Do NOT apply** when:

- The state is purely read (no per-run mutation).
- The rule factory is a closure constructed fresh per `engine.run()` (per-run reset can then be handled via the fresh closure's local set instead).
- The state legitimately spans engine lifetimes (e.g., a process-wide cache of computed values that does not need per-engine isolation).

The id-of-resettable-attribute trick generalizes beyond protokit: any framework where a parent resets a known attribute per "job" can be instrumented with this pattern from a child callable without modifying the parent's public surface.

## Examples

### Before: module-level `set` (leaks across engines AND across runs)

```python
# BAD — shared across ALL engines and persists forever.
_UNRESOLVED_SEEN: set[tuple[str, str]] = set()

@lint_rule(...)
def check_field_behavior_consistent(ctx: FieldLintContext) -> None:
    key = (ctx._rule_id, ctx.file.name)
    if key in _UNRESOLVED_SEEN:
        return
    _UNRESOLVED_SEEN.add(key)
    # emit warning — never fires again for the same (rule, file)
    # even across different engines or different run() calls.
```

### Before: closure-captured `set` (per-factory-invocation, but NOT per-run)

```python
# PARTIAL FIX — per-engine if the closure is created per engine,
# but NOT reset when engine.run() is called a second time.
def build_rule():
    seen: set[tuple[str, str]] = set()  # captured at factory time, persists

    @lint_rule(...)
    def check_rule(ctx: FieldLintContext) -> None:
        key = (ctx._rule_id, ctx.file.name)
        if key in seen:
            return
        seen.add(key)
        # second engine.run() on the same engine still uses the old `seen`.
    return check_rule
```

This is the failure mode latent in D6d U1's `_custom_rules.py:_make_synthetic_closure` (flagged for backport).

### After: WeakKeyDictionary + id-sentinel (isolated per engine AND per run)

```python
from typing import TYPE_CHECKING
import weakref

if TYPE_CHECKING:
    from protokit.schema.lint.engine import LintEngine

_UNRESOLVED_SEEN: "weakref.WeakKeyDictionary[LintEngine, tuple[int, set[tuple[str, str]]]]" = (
    weakref.WeakKeyDictionary()
)


def _emit_unresolved_extension(ctx: FieldLintContext) -> None:
    engine = _engine_for_ctx(ctx)
    current_run_id = id(engine._runtime_warnings)
    state = _UNRESOLVED_SEEN.get(engine)
    if state is None or state[0] != current_run_id:
        # New engine OR new engine.run() — allocate a fresh dedup set.
        seen: set[tuple[str, str]] = set()
        _UNRESOLVED_SEEN[engine] = (current_run_id, seen)
    else:
        _, seen = state
    key = (RULE_ID, ctx.file.name)
    if key in seen:
        return
    seen.add(key)
    # emit runtime warning — fires exactly once per (rule, file) per run().
    engine._runtime_warnings.append(LintRuntimeWarning(...))
```

### Regression test shape (must exercise two `run()` calls)

```python
def test_second_run_reemits_warning_on_same_engine(tmp_path):
    # Build identical compile inputs in two scratch dirs.
    result_a = _make_result(tmp_path / "run_a")
    result_b = _make_result(tmp_path / "run_b")
    engine = LintEngine()
    engine.load_rule_pack(field_behavior)
    profile = LintProfile(name="_test_isolation", rule_ids=frozenset({RULE_ID}))
    r1 = engine.run(result_a, profile=profile)
    r2 = engine.run(result_b, profile=profile)
    # Both runs must emit the warning — dedup MUST reset between runs.
    assert _count_extension_unresolved(r1) == 1
    assert _count_extension_unresolved(r2) == 1
```

A test that only asserts on `r1` would pass even with the broken module-level `set` pattern, providing false confidence.

## Related

- [[bound-method-self-extraction-rule-to-engine-callback-2026-05-20]] — coupled sibling: the `ctx._emit_fn.__self__` extraction this pattern uses to recover the engine reference is itself architectural debt documented separately. The two patterns ship together at D6d U2; when the structural fix (a second engine-injected callable on the LintContext mixin) lands at D6e+, the `_engine_for_ctx` helper can drop the `__self__` extraction without changing the WeakKeyDictionary pattern.
- [[module-level-assert-canonicalization-invariant-frozenset-2026-05-20]] — sibling: another structural-enforcement pattern from the same D6d U2 ce:review pass. Module-level `assert` for ordering invariants at import; this doc covers module-level state for dedup at runtime.
- [[ce-review-convergence-rescues-sub-threshold-findings-2026-05-17]] Case 8 — concrete reviewer-convergence event that surfaced this bug.
- [[module-import-time-fixture-mapping-fail-loud-blast-radius-2026-05-18]] — sibling: module-level state initialized at import time, fail-loud blast radius. Different state class (PRECONDITION vs DEDUP) but the same "module-level mutable state with lifecycle constraints" topic.
- [[dormant-code-changelog-draft-staging-delivery-boundary-2026-05-17]] — companion: the dormant-staged dormant-code discipline applies to the closure-captured `unresolved_seen` set in D6d U1's synthetic rules; the per-run reset pattern documented here is the backport target.
- [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]] — sibling: latent-bug surface patterns. Where that doc covers parity gates surfacing single-run bugs, this pattern documents the multi-run failure class parity gates DON'T cover (because parity gates are single-run by construction).
- [[delivery-boundary-unit-commit-composition-2026-05-14]] — related: engine state hygiene. The per-unit commit boundary applies — the WeakKeyDictionary pattern and its regression test land in the SAME unit commit as the rule callable that needs it.
- Anchor commit: D6d U2 ce:review follow-up commit (2026-05-20). See `src/protokit/schema/lint/rules/options/field_behavior.py:178-228`.
