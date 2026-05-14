---
title: "Frozen dataclasses with mutable fields need a __post_init__ snapshot"
date: 2026-05-02
category: docs/solutions/best-practices
module: python/frozen-dataclasses
problem_type: best_practice
component: tooling
severity: medium
applies_when:
  - "Defining a `@dataclass(frozen=True)` with a `dict[...]`, `list[...]`, or `set[...]` field"
  - "The dataclass is constructed with caller-supplied container values (literal dicts, list comprehensions, registry lookups)"
  - "Instances cross plugin / delivery / thread boundaries where shared state would corrupt other consumers"
  - "Equality and hashability are part of the dataclass contract"
related_components:
  - tooling
tags:
  - dataclass
  - frozen
  - immutability
  - post-init
  - mutable-default
  - defensive-copying
  - snapshot
  - python
---

# Frozen dataclasses with mutable fields need a `__post_init__` snapshot

## Context

`@dataclass(frozen=True)` is a common Python pattern for immutable record types. It customizes `__setattr__` and `__delattr__` to raise `FrozenInstanceError`, so `obj.field = new_value` and `del obj.field` both fail loudly. Authors regularly assume this means the object is immutable.

It doesn't. `frozen=True` only blocks **attribute rebinding** on the instance itself. It does not (and cannot) prevent **nested mutation** through a mutable field. If a frozen dataclass has a `dict[...]` field, calling `obj.field["k"] = v` succeeds and mutates the "frozen" instance.

The Python docs phrase this honestly — "emulate read-only frozen instances" — but the qualifier "emulate" is doing a lot of work, and ruff/mypy/pyright will not flag the leak. The bug class shows up most often in event-record / finding-record systems where rules emit instances at high rates and reuse a single dict reference for performance.

This pattern was introduced after a `ce:review` adversarial pass on `protokit.schema.lint.model` flagged that `LintFinding.params: dict[str, Any]`, `LintProfile.rule_severity_overrides: dict[str, LintSeverity]`, and `LintRuleSpec.severity` (dict variant) all carried the leak.

## Guidance

### The pattern

In every `@dataclass(frozen=True)` that has a mutable container field, add a `__post_init__` that snapshots the field:

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LintFinding:
    rule_id: str
    severity: LintSeverity
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Snapshot the caller-supplied ``params`` dict.

        ``frozen=True`` only prevents attribute REBINDING; nested
        mutation of a passed-in dict would still mutate the finding's
        params after construction. A rule plugin that reuses one
        params dict across multiple emits would otherwise produce
        findings whose params alias to the LAST set of values.
        """
        object.__setattr__(self, "params", dict(self.params))
```

The key elements:

- **`object.__setattr__(self, "params", dict(self.params))`** — bypasses the frozen guard (which routes through the dataclass's overridden `__setattr__`) and rebinds the field to a fresh dict that the caller doesn't hold a reference to.
- **`dict(self.params)`** — shallow copy. For nested-dict shapes use `copy.deepcopy(self.params)` or build the right immutable structure.
- **The docstring documents the WHY.** Frozen + post-init looks like ceremony to a reader who doesn't know the trap; the docstring earns its keep by naming the exact failure mode.

### Per-field shape choices

| Field type | Snapshot call | Notes |
|---|---|---|
| `dict[K, V]` | `dict(self.field)` | Shallow copy. Sufficient when V is immutable (str, int, enum, tuple). |
| `list[T]` | `tuple(self.field)` | Convert to tuple — eliminates the mutability AND makes equality stable. Update the type annotation to `tuple[T, ...]`. |
| `set[T]` | `frozenset(self.field)` | Same pattern: convert to immutable. Update annotation to `frozenset[T]`. |
| `dict[K, dict[K2, V]]` | `copy.deepcopy(self.field)` | Shallow copy isn't enough; nested dict still aliases. Or restructure the type to avoid the nesting. |

Prefer converting to immutable types (`tuple`, `frozenset`) over snapshotting mutables. The immutable type is self-enforcing — no future contributor can accidentally drop the `__post_init__` and reintroduce the bug.

### When the field is `Union | dict`

Some dataclasses carry a discriminated field like `severity: LintSeverity | dict[str, LintSeverity]` (single-kind vs multi-kind). Only snapshot when the runtime value is a dict:

```python
@dataclass(frozen=True)
class LintRuleSpec:
    rule_id: str
    severity: LintSeverity | dict[str, LintSeverity]
    message_template: str | dict[str, str] = ""
    # ... other fields ...

    def __post_init__(self) -> None:
        # Bind the union value to a local first; mypy can then narrow
        # via isinstance() checks. Object.__setattr__ on a frozen
        # dataclass doesn't narrow the type from the function's
        # perspective, so reading self.severity again would lose the
        # narrowing.
        severity = self.severity
        template = self.message_template
        if isinstance(severity, dict):
            object.__setattr__(self, "severity", dict(severity))
        if isinstance(template, dict):
            object.__setattr__(self, "message_template", dict(template))
```

Two notes on this shape:

- **Bind to a local before isinstance.** Mypy's narrowing applies to the local, not to subsequent reads of `self.severity`. Without the local, mypy strict mode flags `dict(self.severity)` because it can't prove the value is a dict.
- **Snapshot only when needed.** The single-kind case (`LintSeverity` enum value) is already immutable; no copy required.

## Why This Matters

**The bug is silent and survives equality checks until the moment something mutates.** Two findings constructed at different times with the same dict reference will be `==` until one of them mutates the dict; after the mutation, both have the new state. Tests that assert equality at construction time pass; tests that assert equality after a batch of emits fail mysteriously. Static analysis catches none of this — the mutation is structurally valid Python.

The cross-boundary risk is the more important one. A rule plugin that yields findings to an engine, or a profile that's looked up from a registry and passed across deliveries, can be mutated by any holder of a reference. Without snapshotting, the dataclass's "frozen" claim is a lie outside its own attribute table.

The fix is cheap (~3 lines per dataclass plus a docstring) and the cost of NOT applying it scales with the number of consumers. Apply it eagerly when defining the type, not after the bug surfaces.

## When to Apply

Apply when:

1. You define `@dataclass(frozen=True)` and any field type is mutable (`dict`, `list`, `set`, or any user-defined mutable class).
2. The dataclass is constructed with caller-supplied values (literal dicts, dict comprehensions, values returned from a registry that the registry might still hold a reference to).
3. Equality / hashability is part of the contract — `__eq__` on a frozen dataclass uses field values; nested mutation breaks equality silently.
4. Instances cross thread, plugin, delivery, or process boundaries where state corruption matters.

Don't bother when:

- The field type is immutable (`int`, `str`, `tuple[immutable, ...]`, `frozenset[immutable]`, `LintSeverity` enum, etc.).
- The dataclass is a private record only constructed and consumed within a single function — the leak is theoretically possible but not exploitable.
- You can use an immutable container type instead (`tuple` instead of `list`, `frozenset` instead of `set`). Prefer this — no `__post_init__` needed.

## Examples

### Before (the trap)

```python
@dataclass(frozen=True)
class LintFinding:
    rule_id: str
    severity: LintSeverity
    params: dict[str, Any] = field(default_factory=dict)


# A rule plugin emits multiple findings, reusing one dict for params:
shared = {"key": "first"}
findings = []
findings.append(LintFinding(rule_id="r1", severity=LintSeverity.ERROR, params=shared))
shared["key"] = "second"  # mutate the shared dict
findings.append(LintFinding(rule_id="r2", severity=LintSeverity.ERROR, params=shared))

# Both findings now have params={"key": "second"} — the first finding
# was retroactively mutated. The "frozen" guarantee did not protect it.
assert findings[0].params == {"key": "second"}  # passes (incorrectly)
assert findings[0].params == {"key": "first"}   # fails — silent corruption
```

### After (the snapshot)

```python
@dataclass(frozen=True)
class LintFinding:
    rule_id: str
    severity: LintSeverity
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", dict(self.params))


shared = {"key": "first"}
findings = []
findings.append(LintFinding(rule_id="r1", severity=LintSeverity.ERROR, params=shared))
shared["key"] = "second"
findings.append(LintFinding(rule_id="r2", severity=LintSeverity.ERROR, params=shared))

# Each finding owns its own params dict. The first finding holds the
# snapshot taken at construction time.
assert findings[0].params == {"key": "first"}   # passes
assert findings[1].params == {"key": "second"}  # passes
```

### Stronger: prefer immutable types where possible

```python
# Instead of:
@dataclass(frozen=True)
class LintReport:
    findings: list[LintFinding] = field(default_factory=list)
    diagnostics: list[LintCompileDiagnostic] = field(default_factory=list)

# Use:
@dataclass(frozen=True)
class LintReport:
    findings: tuple[LintFinding, ...] = ()
    diagnostics: tuple[LintCompileDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        # Still need the snapshot to coerce list-shaped inputs to
        # tuples (callers may pass list literals for ergonomics).
        object.__setattr__(self, "findings", tuple(self.findings))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
```

Tuples are immutable end-to-end. Even if a future contributor drops the `__post_init__`, the type annotation forces callers to pass tuples (or fail mypy strict mode), and tuples can't be mutated. Belt-and-suspenders.

## Related

- [`frozen-dataclass-paired-field-invariant-post-init-2026-05-11.md`](frozen-dataclass-paired-field-invariant-post-init-2026-05-11.md) — sibling `__post_init__` discipline for *semantic* integrity (paired-field invariants between a payload and its source discriminator). This learning covers *structural* integrity (snapshotting mutable container inputs). Both belong on the same hook and stack cleanly: snapshot first, then invariant-check. Together they cover the menu of `__post_init__` duties on a frozen dataclass with source-attributed fields.
- [`no-raise-contract-extends-to-post-init-failures-2026-05-14.md`](no-raise-contract-extends-to-post-init-failures-2026-05-14.md) — when this snapshot pattern is used on a frozen dataclass returned from a function with a "never raises" dispatch contract, the snapshot itself can raise (e.g., `dict(self.field)` on a Mapping whose `__iter__` raises). The dispatch tree must wrap the final `DataClass(...)` construction too, or the no-raise contract has a silent hole. Surfaced by the D6b U1 `ce:review` of `CompileResult`.
- `docs/solutions/best-practices/pytest-static-analysis-gate-ratchet-2026-05-02.md` — the static-analysis gate that catches mypy strict-mode regressions; relevant because `__post_init__` uses `object.__setattr__` which mypy strict has its own opinions about (use a local for narrowing, as shown above).
- `docs/solutions/test-failures/pytestmark-does-not-guard-module-top-imports-2026-05-02.md` — companion learning from the same review pass; both are "looks-like-it-works-but-actually-doesn't" Python gotchas that static analysis won't catch.
