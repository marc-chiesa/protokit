---
title: "Intercept disable-sentinel at the coercion layer, not via enum widening, to keep the severity enum closed"
date: 2026-05-24
category: docs/solutions/best-practices
module: protokit.schema.lint._config
problem_type: best_practice
component: tooling
severity: high
applies_when:
  - "A config surface (pyproject, CLI flag) needs to accept a special 'disable' or 'off' sentinel alongside a closed enum of normal values (e.g., severity levels)"
  - "The enum is load-bearing across multiple downstream consumers: a rank table, a SARIF formatter with assert_never, a JSON wire format, and/or a Literal discriminator"
  - "Widening the enum to include a sentinel value would require auditing and updating every downstream consumer that pattern-matches or ranks the enum members"
  - "The sentinel's semantic category is fundamentally different from the enum's domain (e.g., 'no value' vs 'which value') — conflating them in the enum creates a semantic lie"
tags:
  - sentinel-value
  - enum-closed
  - coercion-layer
  - config-resolution
  - severity-override
  - named-tuple-return
  - wire-format
  - assert-never
---

# Intercept disable-sentinel at the coercion layer, not via enum widening, to keep the severity enum closed

## Context

D6f U2 (commit `fea31b5`) implemented R9b per-rule disable for protokit-lint. One of the five disable mechanisms is `[tool.protokit.lint.severities] <rule_id> = "off"` — users who already have a `severities` table in their pyproject can suppress a rule by setting its severity to the sentinel string `"off"`.

The naive implementation adds `LintSeverity.OFF` to the existing 3-member enum:

```python
class LintSeverity(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    OFF = "off"  # naively added

SEVERITY_RANK = {
    LintSeverity.INFO: 0,
    LintSeverity.WARNING: 1,
    LintSeverity.ERROR: 2,
    LintSeverity.OFF: -1,  # what rank?
}
```

This triggers a cascade: `SEVERITY_RANK` needs an arbitrary rank for `OFF` that breaks comparison-based minimum-severity filtering; the `_emit()` hot path uses `SEVERITY_RANK` to gate findings; the SARIF formatter has an `assert_never` exhaustiveness guard on the three-member enum that becomes reachable; the JSON wire-format `severity` field would carry a new string consumers don't expect; the human formatter's severity-coloring lookup has no entry for `OFF`. Each consumer has to independently decide what "OFF means" — and each answer is architecturally wrong because `OFF` is not a severity level at all. It is a "do not load" instruction, which belongs at the rule-activation layer, not the severity-ordering layer.

The D6f U2 design intercepted `"off"` at the config-coercion layer, before `LintSeverity(normalized)` is ever called. `_coerce_severities` was refactored to return a two-part `_CoercedSeverities` NamedTuple:

```python
class _CoercedSeverities(NamedTuple):
    severities: Mapping[str, LintSeverity]
    off_rule_ids: frozenset[str]

def _coerce_severities(value: Any) -> _CoercedSeverities:
    result: dict[str, LintSeverity] = {}
    off_rule_ids: set[str] = set()
    for rule_id, sev_value in value.items():
        normalized_rule_id = rule_id.strip().lower()
        normalized = sev_value.strip().lower()
        if normalized == "off":
            off_rule_ids.add(normalized_rule_id)
            continue                     # never reaches LintSeverity()
        result[normalized_rule_id] = LintSeverity(normalized)
    return _CoercedSeverities(
        severities=result,
        off_rule_ids=frozenset(off_rule_ids),
    )
```

The `off_rule_ids` frozenset propagates to `ResolvedLintConfig.disabled_rules` — a unified frozenset that merges all three disable sources (severities-off sentinel, pyproject `disabled_rules` list, CLI `--disable-rule` flags) — and the CLI orchestration layer subtracts it from `composed_profile.rule_ids` before handing the profile to the engine:

```python
if resolved.disabled_rules:
    composed_profile = dataclasses.replace(
        composed_profile,
        rule_ids=composed_profile.rule_ids - resolved.disabled_rules,
    )
```

`LintSeverity` stayed a closed 3-member enum. `SEVERITY_RANK` stayed at 3 keys. The SARIF `assert_never` guard remained structurally unreachable. All downstream severity consumers were untouched.

## Guidance

**When a new "value" for an enum would not be semantically part of the enum's existing ordering or category, intercept it at the config-coercion (input-boundary) layer rather than widening the enum. Return the intercepted value via a separate field on the same return type. Keep the enum closed to its original semantic.**

The key question to ask before widening an enum: *Is the new value a member of the same conceptual category as the existing values, or is it a different kind of instruction entirely?* Severity ordering has three members because `"error"`, `"warning"`, and `"info"` are all answers to "how serious is this finding?" The string `"off"` is NOT an answer to that question — it is an answer to "should this rule run at all?" Those are structurally different questions, and conflating them in one enum forces every severity consumer to carry "do not load" logic that is none of its business.

Concretely, when you recognize that the new value is a sentinel:

1. **Add the interception in the coercion function, not in the enum.** Check for the sentinel string before constructing the enum value. Use `continue` / `pass` to skip the enum construction path entirely.

2. **Return a NamedTuple (or dataclass) that carries BOTH the surviving enum-typed map AND the intercepted sentinel set as separate fields.** Do not return a single mixed-type collection where `None` or a special enum value signals "intercepted" — explicit separate fields preserve type safety and make `from_dict` callers explicit about what they received.

3. **Propagate the intercepted set to the layer that owns the semantic.** "Off" means "do not load this rule" — that semantic belongs at the rule-activation layer (the CLI orchestration step that constructs the effective rule set), NOT at the severity-ordering layer. The propagation path (`_coerce_severities` → `_CoercedSeverities.off_rule_ids` → `ResolvedLintConfig.disabled_rules` → `composed_profile.rule_ids - resolved.disabled_rules`) makes the separation explicit and auditable.

4. **Verify that the enum's downstream consumers are unchanged.** After the refactor, run a grep for every consumer of the enum (comparison sites, lookup sites, exhaustiveness guards, formatters). None should have changed. If any did, the interception was not complete.

5. **Update the error message at the coercion site to advertise the sentinel.** Users who type an unrecognized severity value will hit the `ValueError` branch. The error message must name both the valid enum values AND the sentinel, AND must preserve source attribution (which pyproject key + which rule_id). The shipped form at `_config.py:867-873`:

   ```python
   valid = ", ".join(repr(s.value) for s in LintSeverity)
   error_exit_with_code(
       "pyproject-config-invalid",
       (
           f"[tool.protokit.lint] severities[{rule_id!r}] must "
           f"be one of {valid} or 'off' to disable the rule; "
           f"got a severity name outside the closed set."
       ),
   )
   ```

   The four load-bearing pieces: the source-attribution prefix (`[tool.protokit.lint] severities[{rule_id!r}]`), the interpolated valid-values list (`{valid}` — built from the enum so it stays in sync), the `or 'off' to disable the rule` clause, and the closed-set acknowledgement. Without source attribution, users cannot discover the disable mechanism from an error without reading the changelog AND cannot locate which pyproject entry is bad. Per [[source-aware-error-messages-multi-source-resolved-value-2026-05-11]] the attribution must lead, not trail.

## Why This Matters

**Enum widening for a sentinel value cascades silently.** There is no clean answer to "what rank does `OFF` get in `SEVERITY_RANK`?" Any numeric value is arbitrary. Pick `-1` and the minimum-severity filter logic breaks for edge cases. Pick `3` (above `ERROR`) and the filter passes `OFF` findings through even when the user wants `--min-severity=error`. Add a special-case branch to every comparison site and you have replicated the disable logic four separate times, each with its own potential for drift.

**The "do not load" semantic is structurally different from severity ordering.** Severity ordering determines how seriously the engine rates a finding that it did produce. Rule loading determines whether the engine runs the rule at all. These are different phases of the pipeline. Conflating them in a single enum forces the severity layer to carry rule-loading semantics and forces every consumer of `LintSeverity` to understand the rule-loading protocol.

**`assert_never` guards are the visible tip of an invisible iceberg.** The SARIF formatter's `assert_never(finding.severity)` is easy to spot. But the same exhaustiveness assumption is implicit in `SEVERITY_RANK`, the human formatter's severity-to-color map, and any external consumer that `match`es on the JSON `severity` string field. Widening the enum breaks all of them; the `assert_never` is the only one that fails loudly.

**Interception at the coercion layer is zero-cost to all existing consumers.** Every existing test, formatter, and downstream system that consumes `LintSeverity` is correct before and after the change. The sentinel is fully resolved before any of them see it.

## When to Apply

Apply this pattern when ALL of the following are true:

- A new string value is being added to an `Enum` (or `Literal[...]`) where the new value is not semantically part of the existing ordering or category (a "disable" / "skip" / "ignore" / "none" / "off" signal rather than a new tier in an existing hierarchy).
- The enum is consumed by exhaustive-switch / `assert_never` / `match` constructs downstream.
- Multiple downstream consumers depend on the enum's closedness (lookup tables, formatters, wire-format serializers).
- The new value's semantic belongs at a different layer of the pipeline than the enum's existing values (e.g., activation vs. severity ordering, routing vs. classification).
- A config-coercion function already owns the input boundary for this value.

This pattern does NOT apply when:
- The new value is genuinely a new tier in the same category (e.g., adding `"trace"` to a severity ladder — that is an open-ladder widening per [[closed-literal-discriminator-bump-trigger-2026-05-17]], not a sentinel).
- The enum is purely internal and has no downstream exhaustiveness consumers.
- There is no config-coercion layer to intercept at (in which case, add one).

## Examples

### The `_CoercedSeverities` NamedTuple and interception

`src/protokit/schema/lint/_config.py` (D6f U2, commit `fea31b5`):

```python
class _CoercedSeverities(NamedTuple):
    """Two-part return shape for _coerce_severities (D6f U2 KD-1).

    The "off" value is intercepted at the coercion layer BEFORE
    LintSeverity(normalized) construction. LintSeverity stays a
    closed 3-member enum; the sentinel propagates to the disable
    layer via the second tuple member.
    """
    severities: Mapping[str, LintSeverity]
    off_rule_ids: frozenset[str]
```

The interception loop — note the `continue` that ensures `LintSeverity()` is never called with `"off"`:

```python
if normalized == "off":
    off_rule_ids.add(normalized_rule_id)
    continue
result[normalized_rule_id] = LintSeverity(normalized)
```

### Downstream consumers are unchanged

Before and after D6f U2, `SEVERITY_RANK` is:

```python
SEVERITY_RANK: dict[LintSeverity, int] = {
    LintSeverity.INFO: 0,
    LintSeverity.WARNING: 1,
    LintSeverity.ERROR: 2,
}
```

Three keys. No `OFF` entry. No special-case branch in the `_emit()` min-severity filter. The SARIF `assert_never` guard in `_builtin_lint.py` remains unreachable.

### Actuation at the rule-activation layer

`src/protokit/schema/lint/cli.py` (D6f U2):

```python
# Three disable sources merged in resolved.disabled_rules; subtract once.
if resolved.disabled_rules:
    composed_profile = dataclasses.replace(
        composed_profile,
        rule_ids=composed_profile.rule_ids - resolved.disabled_rules,
    )
```

The engine receives `composed_profile` with the disabled rule_ids already removed. It never encounters the concept of `"off"` severity.

### Contrast: what widening would have required

If `LintSeverity.OFF` had been added to the enum, the following sites would each have required independent changes:

- `SEVERITY_RANK` — arbitrary rank choice, breaks filter comparisons
- `_emit()` min-severity gate — needs an `is OFF` early-return guard
- SARIF formatter `assert_never` — becomes a reachable branch or needs removal
- JSON formatter severity serialization — needs to handle the new string
- Human formatter severity-to-color map — needs an `OFF` entry or a default fallback
- Wire-format `_LINT_JSON_SCHEMA_VERSION` — needs a bump for the new severity string
- Every external consumer that `match`es on severity values

The sentinel-at-coercion-layer pattern touches none of these. Every one of them is a potential drift site; eliminating all of them at once is the payoff.

## Related

- [[semantic-category-conflation-accepted-tradeoff-literal-widening-2026-05-13]] — prior pattern. This is the 4th exercise of that pattern with a NEW twist: sentinel at coercion layer instead of in-enum conflation. That doc's decision tree should be extended to acknowledge interception as a third option alongside widen-vs-reuse.
- [[normalize-at-input-boundary-2026-05-07]] — the canonical reference for `_coerce_severities` as the input-boundary normalization point. The interception described here is one more responsibility loaded onto the same coercion function.
- [[symmetric-coercion-strictness-multi-source-field-resolver-2026-05-12]] — the multi-source coercion strictness contract that this pattern extends with in-band sentinel interception.
- [[closed-literal-discriminator-bump-trigger-2026-05-17]] — provides the discriminating question ("can a consumer that doesn't know about the new value still produce a correct result?") that justifies interception over widening for closed Literal / exhaustive-switch consumers.
- [[migration-recipe-severity-aware-template-reuse-2026-05-21]] — flagged `LintSeverity("off") → ValueError → exit-2 pyproject-config-invalid` as deferred-to-D6e+. D6f KD-1 is the resolution.
