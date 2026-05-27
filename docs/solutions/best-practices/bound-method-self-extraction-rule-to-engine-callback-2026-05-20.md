---
title: "Bound-method __self__ extraction for rule-to-engine callbacks is brittle private-surface coupling — inject a second callable on the context instead"
date: 2026-05-20
category: docs/solutions/best-practices
module: src/protokit/schema/lint/rules/options/field_behavior.py
problem_type: best_practice
component: tooling
severity: medium
applies_when:
  - "A lint rule needs to enqueue an out-of-band signal (e.g. a runtime warning) to the parent LintEngine"
  - "The rule's only injected handle is a LintContext dataclass with a private _emit_fn callable"
  - "Walking ctx._emit_fn.__self__ reaches the engine but couples through two private surfaces (the underscore-prefixed dataclass field AND CPython's bound-method __self__)"
  - "A future engine refactor replacing _emit_fn with a closure/lambda would silently break the extraction"
  - "More than one built-in rule needs this out-of-band channel — the second recurrence is the structural-fix trigger"
tags:
  - bound-method
  - private-coupling
  - lint-context
  - engine-callback
  - architectural-debt
  - injectable-callable
  - dataclass-design
  - rule-engine
  - callback-inversion
---

# Bound-method `__self__` extraction is brittle private-surface coupling; use a second engine-injected callable instead

## Context

protokit-lint's rule callables receive a `LintContext` subclass (e.g., `FieldLintContext`) with an engine-injected `_emit_fn: Callable[[LintFinding], None]` that the rule calls to record findings. The engine-to-rule direction (engine injects a callable into the context; rule calls it) is well-defined and works through any callable shape — bound method, lambda, closure, stub.

The reverse direction is NOT represented in the public LintContext surface. D6d U2's `options/field-behavior-consistent` rule needed to enqueue a `LintRuntimeWarning(category="extension_unresolved")` back to the engine when a depended-on extension was absent from the compile pool. `FieldLintContext` has no public `engine` attribute. The rule reached the engine via:

```python
engine = ctx._emit_fn.__self__  # bound-method __self__ IS the engine instance
```

This works on CPython today because the engine's context-construction code sets `_emit_fn=self._emit` (a bound method, where `__self__` is `self`). ce:review (D6d U2, 2026-05-20) caught this as architectural debt via 3-way reviewer convergence — MAINT-1 + KP-1 + AN-OBS-03 all flagged the same coupling site from different angles. The fix was accepted as interim (one rule, pre-1.0, deferred to D6e+) but the pattern is brittle and will compound the second time it's used.

## Guidance

**Recognize the antipattern by its signals. Plan the structural fix the second time a rule needs this channel.**

Recognition signals — any of the following in a rule callable's body is a red flag:

- `engine = getattr(ctx._emit_fn, '__self__', None)` — recovering a parent via bound-method introspection.
- A defensive `if engine is None: raise RuntimeError(...)` (or `LintRuleError`) immediately after — acknowledging the introspection is fragile.
- Accessing an underscore-prefixed attribute on the recovered object (`engine._add_runtime_warning`, `engine._runtime_warnings.append(...)`).
- A comment saying "the cleanest path without a public surface change" — usually evidence that the public surface change IS the right call.
- A test that constructs the context with a lambda `_emit_fn` and is forced to either (a) wrap the lambda in a bound-method-shaped stub or (b) skip the warning-emission path.

**The structural fix: add `_emit_warning_fn` as a second engine-injected callable on `_LintContextEmitMixin`** mirroring the established `_emit_fn` pattern:

```python
# In _LintContextEmitMixin:
_emit_fn: Callable[[LintFinding], None]
_emit_warning_fn: Callable[[LintRuntimeWarning], None]  # NEW (D6e+)
```

The engine populates both at context construction time:

```python
# In LintEngine._build_field_ctx (and the other 7 context builders):
ctx = FieldLintContext(
    ...,
    _emit_fn=self._emit,
    _emit_warning_fn=self._add_runtime_warning,  # NEW (D6e+)
)
```

The rule calls it directly:

```python
ctx._emit_warning_fn(LintRuntimeWarning(category="extension_unresolved", ...))
```

No `__self__` extraction. No defensive raise. Fully typed (mypy sees `Callable[[LintRuntimeWarning], None]`). Works for bound methods, closures, lambdas, and stubs equally — including test stubs that pass a `list.append` directly.

**Alternative: a public `ctx.queue_runtime_warning(category, rule_id, message)` method** on the mixin. This hides the `LintRuntimeWarning` constructor from the rule callable entirely and is cleaner if the warning shape is stable across all callers. Slightly more surface; the engine still injects a callable internally, but the rule never sees it.

**When is the interim `__self__` debt acceptable?** D6d U2 accepted the shortcut under three conditions, all of which must hold simultaneously:

1. **Exactly ONE built-in rule currently uses the out-of-band channel** (no recurrence yet).
2. **The project is pre-1.0** (no external consumer holds a stable reference to `_LintContextEmitMixin`).
3. **The structural fix is explicitly deferred** in a TODOS.md entry, the rule's docstring, OR a cross-reference back to this learning.

When the SECOND built-in rule needs the same channel, the structural fix MUST land THEN — not the third time. The coupling tax accumulates linearly with site count; the structural fix's cost stays constant.

## Why This Matters

**Brittle across engine refactors.** The `__self__` trick works ONLY when `_emit_fn` is a genuine bound method. A future engine refactor that inlines `_emit_fn` as `lambda finding: self._findings.append(finding)` (e.g., for performance or testing isolation) silently breaks: `lambda.__self__` raises `AttributeError`, so the `getattr(..., None)` returns `None`, and the defensive raise fires. The rule stops working with no hint in its own code about why. The defensive raise's message says "the context shape changed" — which is accurate but does not point at the actual cause (the engine refactor).

**Type-system invisible.** `ctx._emit_fn.__self__` returns `Any` from mypy's perspective. The subsequent `engine._add_runtime_warning(warning)` call is untyped — typos in the method name, wrong argument shape, wrong warning category all pass mypy silently. The structural fix's `_emit_warning_fn: Callable[[LintRuntimeWarning], None]` makes all these checkable.

**Private-surface drift accumulation.** Each additional built-in rule that uses `__self__` extraction adds another coupling site to `_emit_fn`'s internal implementation detail. The more coupling sites, the harder any future `_emit_fn` change becomes. The structural fix at the second recurrence costs roughly the same as at the first; the coupling tax grows linearly with site count.

**Test stub construction breaks.** A unit test constructing a `FieldLintContext` with `_emit_fn=lambda f: None` (a natural testing pattern) trips the defensive raise. Tests that want to stub out finding-emission cannot do so cleanly without also constructing a bound-method-shaped stub — which is not natural in Python and requires either a class with an `_emit` method or a `MethodType` wrapper.

**Plan-time prior-art verification missed it.** Per plan-review-verify-prior-art-citations-2026-05-15, the D6d U2 plan classified `ctx._emit_fn.__self__` as "the cleanest path without a public surface change." That phrasing should have triggered a review — when the chosen path needs a defensive raise to guard CPython implementation details, the "cleanest path" claim deserves scrutiny. The structural fix is the cleanest path; the `__self__` extraction is the cheap-but-coupled path.

## When to Apply

Apply the **structural fix** (`_emit_warning_fn` as a second injected callable) when:

- The SECOND built-in rule needs to emit a `LintRuntimeWarning` from inside a rule callable. The pattern has recurred — the structural debt compounds.
- A D6e+ rule family has more than one option-aware rule requiring out-of-band warning emission. The pattern scales poorly across a family.
- Stub-based testing of the option-aware rules is blocked by the `__self__` extraction defensive raise.
- The engine internals refactor (replacing `_emit_fn` with a non-bound-method form) is on the near-term roadmap.

Apply the **interim `__self__` approach** (accepted debt) only when ALL three conditions above hold simultaneously.

## Examples

### Before: `__self__` extraction (brittle private coupling — D6d U2 as shipped)

```python
def _engine_for_ctx(ctx: FieldLintContext) -> "LintEngine":
    emit_fn = ctx._emit_fn
    engine = getattr(emit_fn, "__self__", None)
    if engine is None:
        raise LintRuleError(
            "options/field-behavior-consistent could not resolve the "
            "active LintEngine through ctx._emit_fn. The context shape "
            "changed; update _engine_for_ctx accordingly."
        )
    return engine


@lint_rule(...)
def check_field_behavior_consistent(ctx: FieldLintContext) -> None:
    engine = _engine_for_ctx(ctx)
    engine._runtime_warnings.append(LintRuntimeWarning(
        category="extension_unresolved",
        rule_id=RULE_ID,
        message="...",
    ))
```

**Failure modes:**

- `_emit_fn` switched to a closure → `__self__` raises `AttributeError` → `getattr(..., None)` returns `None` → `LintRuleError` fires → rule stops working → engine records the error as a `rule_exception` warning but does NOT emit the intended `extension_unresolved` warning. Downstream consumers see neither category and have no signal the rule meant to fire.
- Test stub: `ctx = FieldLintContext(..., _emit_fn=lambda f: None)` → same `LintRuleError`. Tests cannot stub the finding emission without also stubbing `__self__` recovery.

### After: second engine-injected callable (D6e+ structural fix)

```python
# In src/protokit/schema/lint/model.py — _LintContextEmitMixin:
@dataclass(frozen=True)
class _LintContextEmitMixin:
    _emit_fn: Callable[[LintFinding], None]
    _emit_warning_fn: Callable[[LintRuntimeWarning], None]  # NEW
    _rule_id: str
    # ... other engine-injected fields ...

# In src/protokit/schema/lint/engine.py — context builders:
ctx = FieldLintContext(
    ...,
    _emit_fn=self._emit,
    _emit_warning_fn=self._add_runtime_warning,  # NEW
    _rule_id=spec.rule_id,
)

# In the rule callable:
@lint_rule(...)
def check_field_behavior_consistent(ctx: FieldLintContext) -> None:
    ctx._emit_warning_fn(LintRuntimeWarning(
        category="extension_unresolved",
        rule_id=ctx._rule_id,
        message="...",
    ))
```

Works for any callable implementation of `_emit_warning_fn`. Fully typed. No `__self__`. No defensive raise.

### Test stub (shows the testing failure mode resolved)

```python
# BROKEN with __self__ approach:
ctx = FieldLintContext(..., _emit_fn=lambda f: None)  # lambda has no __self__
check_field_behavior_consistent(ctx)  # raises LintRuleError in the rule body

# WORKS with second-injected-callable approach:
findings: list[LintFinding] = []
warnings: list[LintRuntimeWarning] = []
ctx = FieldLintContext(
    ...,
    _emit_fn=findings.append,
    _emit_warning_fn=warnings.append,
    _rule_id="options/field-behavior-consistent",
)
check_field_behavior_consistent(ctx)
assert len(warnings) == 1
assert warnings[0].category == "extension_unresolved"
```

## Related

- [[weakkeydict-plus-id-resettable-attr-per-engine-per-run-state-2026-05-20]] — coupled sibling: the WeakKeyDictionary per-run reset pattern uses the `__self__` extraction identified here as debt. When the structural fix (second injected callable) lands, the WeakKeyDictionary pattern's engine-extraction step switches from `ctx._emit_fn.__self__` to a more direct path WITHOUT changing the WeakKeyDictionary pattern itself. The two patterns ship together at D6d U2.
- [[module-level-assert-canonicalization-invariant-frozenset-2026-05-20]] — sibling: another structural-enforcement pattern from the same D6d U2 ce:review pass.
- [[frozen-dataclass-paired-field-invariant-post-init-2026-05-11]] — sibling: dataclass field invariants. Where that doc covers `__post_init__` enforcement of paired-field contracts, this doc covers the pairing of a NEW engine-injected field (`_emit_warning_fn`) with the existing `_emit_fn`. The mixin pattern is the same; the field added here is a `Callable`, not a data field.
- plan-review-verify-prior-art-citations-2026-05-15 — sibling discipline: the D6d U2 plan classified `__self__` extraction as "the cleanest path" without empirically verifying the alternatives. The "cleanest path without a public surface change" framing should have surfaced the question "why do we need a public surface change to be 'no change'?" Adds another sub-pattern to the prior-art verification discipline.
- [[module-name-newline-injection-stderr-forge-2026-05-07]] — sibling: defensive boundaries. Where that doc covers sanitization of values before writing to stderr (defensive OUTPUT boundary), this doc covers the defensive raise on `__self__` extraction (defensive INPUT boundary). Both are symptoms of a missing structural abstraction.
- ce-review-convergence-rescues-sub-threshold-findings-2026-05-17 Case 8 — sibling convergence event in the same D6d U2 ce:review pass.
- Anchor commit: D6d U2 ce:review follow-up commit (2026-05-20). See `src/protokit/schema/lint/rules/options/field_behavior.py:227-256` for the `_engine_for_ctx` helper.
