---
title: "No-raise dispatch contracts must extend to dataclass __post_init__ failures"
date: 2026-05-14
category: docs/solutions/best-practices
module: python/frozen-dataclasses
problem_type: best_practice
component: tooling
severity: medium
applies_when:
  - "A function carries a documented 'never raises on failure' contract (returns a structured result type and converts failures into entries on that result)"
  - "The function returns a `@dataclass(frozen=True)` whose `__post_init__` does work beyond plain attribute storage — snapshotting a Mapping/list/set, normalizing a field, validating a paired-field invariant, etc."
  - "The dispatch try-tree wraps only the work-producing calls; the final `return DataClass(...)` line sits OUTSIDE that try-tree"
  - "At least one `__post_init__` field is typed broadly (e.g., `Mapping[str, X] | None`) rather than narrowly (e.g., `dict[str, X] | None`), so callers can legally pass non-standard implementations"
  - "ce:review reliability, correctness, or adversarial reviewers flag a `__post_init__` failure path as escaping the documented contract"
related_components:
  - testing_framework
tags:
  - no-raise-contract
  - dispatch-tree
  - post-init
  - frozen-dataclass
  - exception-boundary
  - mappingproxytype
  - ce-review-finding
  - contract-integrity
---

# No-raise dispatch contracts must extend to dataclass `__post_init__` failures

## Context

A "no-raise dispatch" function is one that promises its caller: *I never throw on failure. Instead, I return a result type carrying structured diagnostics, and you branch on that.* Examples are common in compiler frontends, validation pipelines, plugin loaders, and any seam where the caller is too far from the failure to handle exceptions meaningfully.

The standard implementation pattern is:

1. Wrap every fallible call in a try-tree with a catch ladder (`FileNotFoundError` → `CalledProcessError` → `OSError` → `Exception`).
2. On exception, append a categorized diagnostic to a list.
3. After the try-tree, build the result type from the accumulated state and return it.

The latent gap: step 3 itself can raise. If the result type is a `@dataclass(frozen=True)` whose `__post_init__` does any non-trivial work — snapshotting a mutable Mapping into a `MappingProxyType`, normalizing a list into a tuple, validating a paired-field invariant — then the final `return DataClass(...)` line is doing work that the surrounding try-tree does NOT cover. A caller (or a future backend) who passes a value that trips `__post_init__` gets an exception that escapes the documented no-raise contract, untyped and unsurfaced as a diagnostic.

The gap is hard to spot because:

- `__post_init__` runs inside `__init__`, so the construction *looks* like ordinary data assembly.
- Happy-path tests never trip it — they pass plain `dict` / `list` values that `MappingProxyType(dict(...))` and `tuple(...)` handle cleanly.
- Type annotations broader than the safe set (`Mapping` rather than `dict`) advertise the gap to callers but no static analyser flags it.

This learning was introduced when a `ce:review` of `protokit.schema.compile.compile_protos_to_result` (D6b U1) noted that the function's A2-1 "never raises on backend failure" contract had a hole: `CompileResult` is a frozen dataclass whose `__post_init__` wraps `source_info_descriptors` via `MappingProxyType(dict(self.source_info_descriptors))`. A caller passing a custom `Mapping` whose `__iter__` raises would escape the contract.

## Guidance

**Rule.** A no-raise contract is only as strong as its weakest point. The final dataclass construction is "work" if `__post_init__` does anything beyond plain `object.__setattr__` assignments — and must be wrapped in the same catch-all as the dispatch tree.

**Pattern.** After the dispatch try-tree, wrap the return construction in a separate `try/except Exception`. On exception, append a category-#5 (or equivalent "unexpected") diagnostic and rebuild with `None` (or a primitive sentinel) for any field that could have triggered `__post_init__`. The rebuild path must be **mechanically simpler** than the primary path so it cannot loop on the same failure.

Before:

```python
return CompileResult(
    pool=pool,
    root_files=root_files,
    diagnostics=tuple(diagnostics),
    source_info_descriptors=source_info_descriptors,
)
```

After:

```python
# Wrap the final construction in the same Exception catch-all so
# ``__post_init__`` failures (e.g., a caller-supplied custom
# Mapping for ``source_info_descriptors`` whose iteration raises)
# surface as a category-#5 diagnostic rather than escaping the
# A2-1 "never raises on backend failure" contract. The bundled
# backends always return ``dict | None``, so this only kicks in
# for direct external construction with non-standard Mappings.
try:
    return CompileResult(
        pool=pool,
        root_files=root_files,
        diagnostics=tuple(diagnostics),
        source_info_descriptors=source_info_descriptors,
    )
except Exception as exc:  # noqa: BLE001 — see comment above
    diagnostics.append(_diagnostic_unexpected(exc))
    # Re-build with cleared source_info_descriptors so the second
    # attempt cannot trip the same __post_init__ failure.
    return CompileResult(
        pool=pool,
        root_files=root_files,
        diagnostics=tuple(diagnostics),
        source_info_descriptors=None,
    )
```

**Rebuild safety rule.** Pass `None` (or another primitive sentinel) for the field whose `__post_init__` processing could raise. The rebuild must be strictly simpler than the primary construction — *not* a re-attempt of the same code path. If the rebuild itself can fail in the same way, you have not closed the gap; you have moved it.

**Where the catch belongs.** Place the `try/except` around the construction, not inside `__post_init__`. Catching there would hide errors from callers who DO want strict construction (tests, programmatic builders). The dispatch function is the layer that owes the no-raise contract; the dataclass itself is just a value carrier.

## Why This Matters

A documented no-raise contract creates a strong caller expectation: the function absorbs every failure and reports it as a structured diagnostic. If any code path after the try-tree raises, the contract is violated silently — no test catches it unless someone explicitly exercises the escaping path with a synthetic problematic value.

The violation is especially insidious with frozen dataclasses: `__post_init__` runs during `__init__`, so it looks like ordinary construction, not "work." But any `__post_init__` that calls `dict()`, iterates, validates, or normalizes is *work* in the same sense as a subprocess call. The catch tree must account for it or the no-raise guarantee has a hole that only adversarial review or a fuzz backend will surface.

A secondary benefit: callers who pass unusual types for an optional parameter get a diagnostic (observable, debuggable, attributable) rather than a traceback (surprising, attributed to the wrong frame). This matters most when the dataclass field is typed broadly (`Mapping`, `Iterable`, `Callable`) and the documented contract is the only thing telling callers "this absorbs failures."

## When to Apply

Apply this pattern whenever ALL three conditions hold:

1. **A function has a documented no-raise contract** — it promises to absorb failures and report them as structured return values rather than exceptions.
2. **The function returns a frozen dataclass (or any class with `__post_init__` work)** — `MappingProxyType(dict(...))`, `tuple(self.field)`, `frozenset(self.field)`, custom validation, or any call that could itself raise.
3. **The catch tree does not physically wrap the return construction** — i.e., the `DataClass(...)` call sits after the final `except` block.

The pattern is most important when:

- The dataclass has caller-supplied fields whose types are broader than the safe set (`Mapping` instead of `dict`, `Sequence` instead of `tuple`).
- The function is part of a public API where callers can legally construct results directly (not only through the dispatch function).
- The dataclass is the documented "single source of truth" for failure reporting — if construction fails, there is no other surface to carry the diagnostic.

This pattern is **less important** when:

- The dataclass is internal and only ever built by one well-typed caller.
- The `__post_init__` is purely `object.__setattr__` for derived fields (no iteration, no validation, no conversion).

## Examples

**protokit `compile_protos_to_result` + `CompileResult`.**

`CompileResult.__post_init__` wraps `source_info_descriptors` in `MappingProxyType(dict(self.source_info_descriptors))`. The `dict()` call iterates the input via `__iter__`; a `Mapping` whose `__iter__` raises causes `__post_init__` to raise. The fix wraps the return construction in `try/except Exception`, catches the failure, appends a category-#5 unexpected diagnostic, and rebuilds with `source_info_descriptors=None` — which skips the `MappingProxyType(dict(...))` path entirely (the guard is `if self.source_info_descriptors is not None`).

**Regression test.** `TestPostInitExceptionContainment::test_iteration_failure_in_post_init_becomes_diagnostic` injects a fake backend that returns a `_BuggyMapping` whose `__iter__` raises `RuntimeError`. The test pins the contract:

```python
class _BuggyMapping:
    """Mapping-shaped object whose ``__iter__`` raises."""

    def __iter__(self):
        raise RuntimeError("synthetic iteration failure")

    def keys(self):
        return iter(self)

    def __getitem__(self, key):
        raise KeyError(key)

    def __len__(self) -> int:
        return 0


def test_iteration_failure_in_post_init_becomes_diagnostic(
    self, tmp_path, monkeypatch,
):
    from google.protobuf import descriptor_pool
    from protokit.schema import compile as compile_module

    def fake_protoxy(paths, ip, *, include_source_info=False):
        return descriptor_pool.DescriptorPool(), (), _BuggyMapping()

    monkeypatch.setattr(compile_module, "_has_protoxy", lambda: True)
    monkeypatch.setattr(compile_module, "_compile_with_protoxy", fake_protoxy)

    proto = tmp_path / "demo.proto"
    proto.write_text('syntax = "proto3"; package demo; message X {}')

    # MUST NOT raise — the contract is that __post_init__ failures
    # land as category-#5 diagnostics, not propagate.
    result = compile_protos_to_result([proto], include_source_info=True)

    # source_info_descriptors cleared on the rebuild path.
    assert result.source_info_descriptors is None
    # A category-#5 ("unexpected") diagnostic carries the RuntimeError.
    unexpected = [d for d in result.diagnostics if d.category == "unexpected"]
    assert len(unexpected) == 1
    assert unexpected[0].exception_type == "RuntimeError"
```

**Generalized checklist:**

- Identify every `__post_init__` operation on every field. Flag any that iterate, coerce, validate, or call other functions.
- For each flagged field, check whether the type annotation is broader than the actual safe set (e.g., `Mapping` vs `dict`).
- If yes, the return construction must be inside a `try/except Exception`.
- The rebuild path must use `None` or a primitive sentinel for the flagged field — never re-pass the original problematic value.
- Add a regression test with a synthetic broken type that exercises the `__post_init__` failure path. The test must assert (a) the call does not raise, (b) the offending field is cleared on rebuild, and (c) a diagnostic carries the original exception type.

## Related

- [[frozen-dataclass-mutable-fields-need-post-init-snapshot]] — establishes that `__post_init__` must snapshot mutable container fields (`MappingProxyType(dict(...))`, `tuple(self.field)`) to preserve frozen semantics. This learning extends it: the snapshot work CAN raise, and any surrounding no-raise contract must catch it.
- [[frozen-dataclass-paired-field-invariant-post-init]] — sibling pattern: paired-field invariants belong in `__post_init__`. Same caveat applies — a paired-field invariant that calls `raise ValueError(...)` is `__post_init__` work that escapes a no-raise contract unless the dispatch tree wraps construction too.
- [[circular-import-type-checking-cycle-break]] — sibling concern in the same family: an `except` arm that converts exceptions into structured warnings is only as strong as the code inside it. A lazy `ImportError` from an annotation-only import inside the arm silently breaks the conversion contract. The pattern there is the same — surface every escape path before it can break a stated contract.
- [[copytoproto-round-trip-for-proto-form-only-descriptor-fields]] — the underlying constraint that made `CompileResult.source_info_descriptors` necessary in the first place. `pool.Add()` discards `source_code_info`, so descriptors must be captured pre-`Add()` and stored on the result — which is what introduced the broadly-typed `Mapping` field that exposes the no-raise gap.
- [[ce-review-cross-reviewer-agreement-shared-misreading-false-positive-amplifier]] — written from the same D6b U1 `ce:review` session. That doc captures the false-positive finding the review produced (5-reviewer convergence on a shared-source misreading of forward-looking docstrings); this doc captures one of the genuinely actionable findings. Read together they illustrate how the merge stage must distinguish independent evidence (this finding, surfaced by the reliability reviewer alone with a concrete trace) from shared-source convergence (the false CLI wire-up finding).
