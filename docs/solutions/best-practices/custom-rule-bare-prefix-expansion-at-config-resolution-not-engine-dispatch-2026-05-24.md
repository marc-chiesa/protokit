---
title: "Expand multi-kind custom-rule bare prefixes at config-resolution time, not at engine-dispatch time, to protect the engine hot path"
date: 2026-05-24
category: docs/solutions/best-practices
module: protokit.schema.lint._config
problem_type: best_practice
component: tooling
severity: medium
applies_when:
  - "A custom rule is registered under multiple mangled IDs (one per element kind, e.g., custom/foo__method, custom/foo__service) and users can reference it by bare prefix (custom/foo)"
  - "Config-resolution produces a frozenset of rule IDs that the engine consults at runtime; any expansion of user input must happen before that frozenset is finalized"
  - "The engine's dispatch loop is a hot path that runs once per element per file; adding prefix-matching there would multiply latency by the number of custom rules"
  - "Per-kind disable via explicit mangled form (custom/foo__method) must bypass the expansion — the expansion is only for bare-prefix entries"
tags:
  - custom-rules
  - prefix-expansion
  - config-resolution
  - engine-hot-path
  - suffix-equality
  - mangled-rule-id
  - multi-kind-rule
---

# Expand multi-kind custom-rule bare prefixes at config-resolution time, not at engine-dispatch time, to protect the engine hot path

## Context

D6d (commit history) introduced `[[tool.protokit.lint.custom_annotation_rules]]` entries that each carry an `element_kinds` list. A spec with `element_kinds=["method", "service"]` and `rule_suffix="audit-required"` registers two synthetic rule_ids at engine load time:

- `custom/audit-required` — the first (or only) kind, stored under the bare form
- `custom/audit-required__service` — subsequent kinds, stored under the mangled `<suffix>__<kind>` form

D6f U2's R9b disable feature needed to accept rule_ids in `disabled_rules` / `enabled_rules` lists that name custom rules. Two user expectations are both valid:

- `disabled_rules = ["custom/audit-required"]` — "disable ALL kinds of this rule"
- `disabled_rules = ["custom/audit-required__service"]` — "disable only the service-kind variant"

The naive implementation handles the first case at engine dispatch: for each loaded rule_id, check whether any `disabled_rules` entry is a prefix of it. This means every call through `_emit()` — which fires once per descriptor that matches the rule's selector, across every `.proto` file in the descriptor set — performs an O(N) prefix-scan where N is the size of the `disabled_rules` set. Even with N small today, this is an architectural commitment: the engine now carries R9b semantics in its hot path.

The D6f U2 design (KD-2) expands bare `custom/<suffix>` entries at config-resolution time inside `ResolvedLintConfig.from_dict`, before the resolved config is handed to the engine. The expansion uses suffix **equality** matching (NOT substring), looks up the `CustomAnnotationRuleSpec` by `spec.rule_suffix == suffix`, and materializes the full set of mangled rule_ids via `synthetic_rule_ids((spec,))`:

```python
def _expand_custom_prefix(
    rule_ids: frozenset[str],
    specs: tuple[CustomAnnotationRuleSpec, ...],
) -> frozenset[str]:
    spec_by_suffix = {spec.rule_suffix: spec for spec in specs}
    result: set[str] = set()
    for rid in rule_ids:
        if rid.startswith("custom/") and "__" not in rid:
            suffix = rid[len("custom/"):]
            matching_spec = spec_by_suffix.get(suffix)
            if matching_spec is not None:
                result.update(synthetic_rule_ids((matching_spec,)))
                continue
        result.add(rid)
    return frozenset(result)
```

After expansion, `disabled_rules = ["custom/audit-required"]` becomes `frozenset({"custom/audit-required", "custom/audit-required__service"})`. The CLI orchestration subtracts this frozenset from `composed_profile.rule_ids` with a single set-difference operation. The engine's dispatch logic is an O(1) hash lookup on every emit — unchanged from before R9b.

Per-kind disable via explicit mangled form bypasses expansion automatically: the `"__" not in rid` guard means `"custom/audit-required__service"` is passed through as-is.

## Guidance

**When a feature introduces "name with optional suffix expansion" semantics (a bare identifier that expands to a family of fully-qualified identifiers), expand at config-resolution time, not at engine dispatch time. Use the already-known mapping (specs, registry) to materialize the full identifier set before the hot path sees any of them.**

The core principle: the engine's dispatch path should do exactly one thing per event — look up the identifier and decide pass/fail. It should not carry knowledge of expansion semantics, multi-kind families, or alias resolution. Those are config-layer concerns.

Concretely:

1. **Identify the expansion mapping.** In D6f U2 the mapping is `CustomAnnotationRuleSpec.rule_suffix → synthetic_rule_ids(spec)`. The mapping is computable at config-resolution time because `custom_annotation_rules` is resolved before `disabled_rules` / `enabled_rules` in the same `from_dict` call. Any feature where the "what does this name expand to?" answer is knowable before the first event fires belongs in the config-resolution layer.

2. **Use suffix equality, not substring matching.** `"custom/foo"` must NOT match `rule_suffix="foobar"`. The guard `spec_by_suffix.get(suffix)` where `suffix = rid[len("custom/"):]` is an exact-equality dictionary lookup. Substring or prefix matching would incorrectly expand `"custom/audit-required"` against a `rule_suffix="audit-required-strict"` spec, silently over-disabling rules the user did not name.

3. **Let the per-kind (mangled) form bypass expansion.** The mangled form already encodes exactly one rule_id. No expansion is needed. The `"__" not in rid` guard in `_expand_custom_prefix` achieves this with zero additional logic.

4. **Apply expansion to every R9b source set symmetrically.** In D6f U2, `_expand_custom_prefix` is called on `off_severity_rule_ids`, `pyproject_disabled_rules`, `cli_disabled_rules`, `pyproject_enabled_rules`, and `cli_enabled_rules` before R8b contradiction warning computation and before the final merge. Expanding some sources but not others would cause R8b to see asymmetric sets, producing incorrect contradiction detection.

5. **Document the expansion guarantee at the field site.** The `ResolvedLintConfig.disabled_rules` docstring in D6f U2 notes that custom-prefix expansion has already been applied, so callers do not need to expand again. Without this note, a future caller at the CLI layer might redundantly attempt expansion and double-count.

## Why This Matters

**Engine hot-path operations should be O(1).** The `_emit()` method runs on every descriptor element that matches a rule's selector — for a large descriptor set this is tens of thousands of calls per run. An O(N) prefix-scan per call where N is the directive count is technically small today (N typically ≤ 10) but is an architectural commitment: adding the expansion logic to `_emit()` means future R9b complexity (negation semantics, glob patterns, etc.) would also naturally land in `_emit()`, compounding the cost and the coupling.

**Engine code unchanged = engine semantics unchanged.** The engine's pre-R9b contract is: "given a rule_id set, emit findings for matching descriptors." Post-R9b, the contract is identical — the engine just receives a smaller rule_id set. The engine has no knowledge that any rules were disabled. This makes the engine testable independently of R9b semantics, and makes R9b semantics testable without running the engine.

**Suffix equality vs. substring is a silent correctness boundary.** A prefix-match implementation `"custom/foo" in disabled_rules` would correctly expand `"custom/foo"` against `rule_suffix="foo"` but ALSO incorrectly expand it against `rule_suffix="foobar"`. The suffix-equality lookup `spec_by_suffix.get(suffix)` makes the boundary explicit in both the code and the documentation.

**Config-resolution time is the right layer for "what does this mean" questions.** The config layer has access to the full declared spec list. The engine dispatch layer does not (by design — specs are resolved once, not re-queried per event). Asking "what rule_ids does this bare custom prefix expand to?" in the engine would require passing the spec list into the engine hot path, coupling the engine to config-layer data structures.

## When to Apply

Apply this pattern when ALL of the following are true:

- A feature introduces identifier aliases or families where one user-facing name maps to multiple internal identifiers (rule_ids, event types, route names, etc.).
- The full expansion mapping is knowable at config-resolution time (i.e., the mapping is derived from already-resolved config, not from per-event runtime state).
- The hot path that consumes identifiers uses exact-match lookups (dict `get`, set membership, hash lookup).
- The alias / expansion semantics are user-facing (in config, not internal to the engine).

This pattern does NOT apply when:
- The expansion mapping is only knowable at event time (e.g., the expansion depends on per-event data like the descriptor's package or file name — in that case the engine must carry the logic, but it should still be modeled as a pre-filter, not interleaved with finding emission).
- The aliasing is purely cosmetic (display names that never affect lookup).

## Examples

### The expansion function

`src/protokit/schema/lint/_config.py` (D6f U2, commit `b8f0168`):

```python
def _expand_custom_prefix(
    rule_ids: frozenset[str],
    specs: tuple[CustomAnnotationRuleSpec, ...],
) -> frozenset[str]:
    spec_by_suffix = {spec.rule_suffix: spec for spec in specs}
    result: set[str] = set()
    for rid in rule_ids:
        if rid.startswith("custom/") and "__" not in rid:
            suffix = rid[len("custom/"):]
            matching_spec = spec_by_suffix.get(suffix)
            if matching_spec is not None:
                # Materialize every kind-mangled rule_id for this spec.
                result.update(synthetic_rule_ids((matching_spec,)))
                continue
        result.add(rid)
    return frozenset(result)
```

### Symmetric expansion before contradiction detection

Inside `ResolvedLintConfig.from_dict`, expansion is applied to ALL five R9b input sets before R8b warning computation:

```python
# KD-2 ordering: expand ALL R9b sets before R8b contradiction warnings.
# Partial expansion produces incorrect contradiction detection.
off_severity_rule_ids = _expand_custom_prefix(
    off_severity_rule_ids, custom_annotation_rules
)
pyproject_disabled_rules = _expand_custom_prefix(
    pyproject_disabled_rules, custom_annotation_rules
)
cli_disabled_rules = _expand_custom_prefix(
    cli_disabled_rules, custom_annotation_rules
)
pyproject_enabled_rules = _expand_custom_prefix(
    pyproject_enabled_rules, custom_annotation_rules
)
cli_enabled_rules = _expand_custom_prefix(
    cli_enabled_rules, custom_annotation_rules
)
```

Then R8b warnings are computed from the post-expansion sets. Then the unified `disabled_rules` frozenset is constructed. The engine sees the final set.

### Expansion contract documented at the field site

`ResolvedLintConfig.disabled_rules` field docstring (D6f U2):

```
UNIFIED disabled-rule set merging three sources:
[severities] X = "off" sentinel ids (intercepted at the coercion layer
per KD-1), pyproject disabled_rules list, and CLI --disable-rule
overrides. Custom-prefix expansion (KD-2) materializes any custom/<suffix>
bare entry into the full set of mangled rule_ids for the matching spec
before merge. cli.py subtracts this set from composed_profile.rule_ids.
```

### What the engine sees (unchanged)

Before R9b, the engine's profile had `rule_ids = {"naming/snake-case-fields", "custom/audit-required", "custom/audit-required__service", ...}`.

After R9b with `disabled_rules = ["custom/audit-required"]`, the engine's profile has `rule_ids = {"naming/snake-case-fields", ...}` — with both `custom/audit-required` and `custom/audit-required__service` removed by the set-difference in cli.py. The engine's `_emit()` logic is word-for-word identical to its pre-R9b form.

## Related

- [[rules-tuple-insertion-order-load-bearing-engine-dispatch-2026-05-19]] — establishes that engine dispatch is order-dependent. KD-2's config-resolution-time expansion preserves this invariant by materializing the full rule_id set before it reaches the engine. The dispatch order is unchanged.
- [[capture-setup-without-dispatch-false-test-confidence-2026-05-17]] — applies to test design for KD-2: tests must ensure at least one `custom/<kind>/<suffix>` rule of each kind is registered so the dispatch fires.
- [[normalize-at-input-boundary-2026-05-07]] — KD-2's expansion is a form of input-boundary normalization: the user-facing bare `custom/<suffix>` form is expanded into the canonical mangled form at the config-resolution boundary, before the engine sees it.
- [[sentinel-at-coercion-layer-not-enum-widening-2026-05-24]] — sibling KD pattern in D6f U2. Both push complexity to the config-resolution layer to keep the engine and the enum unchanged.
