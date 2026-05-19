---
title: "Value migration is not the same as value addition — forward-compatibility tolerance protects only the latter"
date: 2026-05-17
category: docs/solutions/best-practices
module: src/protokit/schema/lint/model.py
problem_type: best_practice
component: tooling
severity: medium
applies_when:
  - "A Literal-discriminator field's emit site is moving from one existing value to a new value (splitting a previously-conflated category, renaming a value at one of N emit sites, or otherwise redirecting an emit path)"
  - "The old value still appears in output from another emit site (the value did not vanish from the wire format)"
  - "Consumers may have code paths of the form ``if w.category == OLD`` specifically targeting the migrated emit site"
  - "The wire-format contract is governed by a ``schema_version`` (or equivalent) bump that signals consumer-detectable change"
  - "Forward-compatibility tolerance (``treat unknown values gracefully``) is documented as a consumer contract"
tags:
  - wire-format
  - literal-split
  - consumer-migration
  - forward-compatibility
  - schema-version
  - api-contract
  - breaking-change
  - changelog
---

# Value migration is not the same as value addition — forward-compatibility tolerance protects only the latter

## Context

D6b U5 (commit `16b494f`) split the `LintRuntimeWarning.category` Literal: the existing `"unloaded_rule"` value's CLI-synthesized emit site at `src/protokit/schema/lint/cli.py:1086-1100` migrated to a new value `"severities_unloaded_rule"`. The engine-emitted site at `engine.py:387` kept emitting the original `"unloaded_rule"` unchanged.

From a casual reading, this looks like a pure "value addition" — the new `severities_unloaded_rule` value joins the existing `unloaded_rule` in the Literal set. Consumers that "treat unknown values as forward-compatible" (per the documented wire-format contract in [[wire-format-schema-version-bump-contract-and-absence-semantic-2026-05-13]]) gracefully handle the new value via a default branch and move on. Right?

**Wrong** — for consumers that had code targeting the CLI emit site specifically. Those consumers wrote `if w.category == "unloaded_rule" and "[tool.protokit.lint.severities]" in w.message:` (the documented message-substring discrimination from D6a U9 KTD-2). After U5, the CLI emit site no longer produces `"unloaded_rule"` — it produces `"severities_unloaded_rule"`. The consumer's match condition sees ZERO matches for the CLI case after upgrade. The old value still exists (from the engine site), so the consumer doesn't see an unknown value to route through the default branch. They see a silently reduced match set: the same field shape, the same value they expect, just never appearing at the emit site they care about. The bug surfaces as missing behavior, not as a fault.

The U5 brainstorm document-review pass surfaced this as ADV-3 (adversarial reviewer, P2, conf 0.82): "Forward-compatibility claim contradicts migration breakage." The U5 plan + CHANGELOG-DRAFT had to explicitly distinguish the two failure modes — the original draft conflated them.

## Guidance

**Distinguish value MIGRATION from value ADDITION when classifying a wire-format change. Forward-compatibility tolerance protects consumers from value ADDITION (new unknown values fall through gracefully). It does NOT protect from value MIGRATION (a known value still exists, but its emit-site distribution changed). The `schema_version` bump is the ONLY programmatic signal that switch tables need re-auditing, not just extending. CHANGELOG entries that describe the change must use the correct framing — calling a migration an "addition" hides the breakage from consumer-migration audiences.**

The decision matrix:

| Change shape | Old value still appears in output? | New value appears in output? | Consumer-failure mode | Forward-compat protects? |
|---|---|---|---|---|
| **Pure addition** | No (the new value is at a new emit site) | Yes (new value at new emit site) | Default branch handles unknown gracefully | YES |
| **Migration** | Yes (still emitted from OTHER sites) | Yes (at the migrated site) | Consumer's `if value == OLD` filter sees fewer matches than before; default branch never fires (the new value goes through its own arm if the consumer added one) | NO |
| **Pure removal** | No | N/A | Consumer's `if value == OLD` filter sees ZERO matches; the field is gone | NO (consumer needs to read CHANGELOG) |

Sub-rules:

1. **Audit emit sites before classifying.** A producer-side Literal addition looks identical to a producer-side Literal migration in the diff. The discriminator is the EMIT SITES: did any emit site previously produce the old value AND now produce the new value? If yes, it's a migration. If no, it's an addition. Grep the codebase for the old value's emit sites before writing the CHANGELOG entry.

2. **CHANGELOG framing matters.** "Added new value X" tells consumers to extend their switch tables with a new branch. "Migrated value X from site A to value Y at site A" tells consumers to AUDIT their existing branches AND extend them with the new value. The first framing is incomplete; the second framing is complete. Use the second when the change is a migration.

3. **Forward-compatibility tolerance is documented for value-addition, NOT value-migration.** The [[wire-format-schema-version-bump-contract-and-absence-semantic-2026-05-13]] doc says "consumers MUST treat unknown values as forward-compatible (read what they can, ignore new keys they don't understand)." This protects against value-addition. It says nothing about value-migration because, by definition, the migrated value is NOT unknown — both old and new values are present in the Literal set.

4. **The `schema_version` bump signals the audit obligation.** Bumping schema_version says: "switch tables may need re-auditing, not just extending." For pure value-addition, "re-audit" means "add a new case." For value-migration, "re-audit" means "check whether existing cases for the old value still cover what you wanted them to cover." Both fit under the bump's umbrella; the CHANGELOG must say which one applies.

5. **Negative tests catch silent migration regressions.** A test that asserts the migrated emit site no longer produces the old value (negative assertion on the old category, paired with a positive assertion on the new category for the same input) makes the migration structurally explicit. Without the negative assertion, a future refactor that accidentally restored the old emit could pass all positive assertions while silently re-introducing the conflation. See [[silent-test-confidence-...]] family of learnings.

6. **The schema_version bump is wire-format scope, NOT semver scope.** A wire-format bump (per-unit, signals "switch tables may need re-auditing") is a separate signal from a package-version bump (per-release, signals general change). The two need not coincide. Pre-1.0 protokit ships wire-format bumps in per-unit commits while the package version waits for delivery-boundary commits per [[delivery-boundary-unit-commit-composition-2026-05-14]]. The CHANGELOG-DRAFT pattern stages the wire-format message until the boundary fold.

## Why This Matters

**Silent breakage is the worst-failure mode for wire-format changes.** A pure value-addition that the consumer's default branch handles is observable: the consumer gets a `[WARN] unknown category` log line and someone investigates. A value-migration that the consumer's existing branch silently stops matching is unobservable: the consumer's "I correctly handle the CLI severities case" code path is now dead code, but no test fires, no log appears, no metric moves. The functionality is gone and nobody notices.

**The framing in the CHANGELOG IS the consumer migration guide.** If the CHANGELOG says "added value Y," consumer-side audits stop at "extend the switch with a Y branch — done." If the CHANGELOG says "migrated value X at site A to value Y," consumer-side audits ALSO check "do my existing X branches still cover what I needed them to cover?" The framing changes what consumers do; sloppy framing leaves the silent-breakage path open.

**Forward-compatibility tolerance is a real contract, just narrower than it sounds.** Consumers SHOULD treat unknown values gracefully; that's the right contract for value-addition. Misapplying the contract to value-migration ("forward-compat protects us, we don't need to audit") is the failure mode this learning prevents. Producers must distinguish the cases in CHANGELOG entries so consumers can apply the right discipline.

**Value-migration is the natural outcome of accepted-tradeoff resolutions.** [[semantic-category-conflation-accepted-tradeoff-literal-widening-2026-05-13]] documents the pattern of conflating two semantically-distinct emit sites under one Literal value when the user-visible signal via message text is sufficient. When the deferred split eventually lands (D6b U5 closed exactly this trip-wire from D6a U9 KTD-2), the result is value-migration: the conflated value still exists from one emit site; the new value takes over the other emit site. The pattern is inherent to the resolve-deferred-conflation workflow.

## When to Apply

Apply this discipline when ALL of the following are true:

1. A wire-format Literal field is gaining a new value AND an existing emit site's output is changing from the old value to the new value.
2. The old value will still appear in output from at least one other emit site.
3. The wire-format contract is governed by a `schema_version` bump.
4. Consumers may have written discrimination logic targeting the migrated emit site specifically (e.g., via message-substring matching, source attribution, or context-aware filtering).

The inverse — when this discipline does NOT apply:

- **Pure value-addition** (new value at new emit site; no existing emit site changed). Forward-compatibility tolerance applies; the bump signals "extend your switch tables." No migration framing needed.
- **Pure value-removal** (value is gone entirely from all emit sites). Consumers will see no matches for the old value; this is observable via "where did all my X warnings go?" alerting. Removal needs its own CHANGELOG treatment but the migration framing doesn't apply.
- **Rename within the same emit site** (X → Y, no semantic change). Treat as straight value-addition + value-removal; CHANGELOG should call it a rename so consumers know the X case is gone, not just less common.

## Examples

### Producer-side: the U5 split

Before (D6a U9):

```python
# CLI emit site at cli.py:1086-1100
LintRuntimeWarning(
    category="unloaded_rule",  # SHARED with engine emit site
    rule_id=_safe_for_stderr(rid),
    message=f"rule {_safe_for_stderr(rid)!r} is named in "
            f"[tool.protokit.lint.severities] but is not "
            f"in the composed profile — ...",
)
```

After (D6b U5):

```python
# CLI emit site at cli.py:1086-1100
LintRuntimeWarning(
    category="severities_unloaded_rule",  # NEW; engine site keeps "unloaded_rule"
    rule_id=_safe_for_stderr(rid),
    message=f"rule {_safe_for_stderr(rid)!r} is named in "
            f"[tool.protokit.lint.severities] but is not "
            f"in the composed profile — ...",
)
```

The engine emit site at `engine.py:387` is unchanged — still emits `"unloaded_rule"`. So `"unloaded_rule"` still appears in protokit output; only the CLI emit site moved.

### Consumer-side: the silent-breakage scenario

A CI parser that wanted to alert on user typos in `[tool.protokit.lint.severities]` keys:

```python
# Consumer code written against D6a U9 wire format
def find_severities_typos(lint_output: dict) -> list[str]:
    return [
        w["rule_id"] for w in lint_output["runtime_warnings"]
        if w["category"] == "unloaded_rule"
        and "[tool.protokit.lint.severities]" in w["message"]
    ]
```

After D6b U5, this consumer code silently returns an empty list. The CLI emit site now produces `category="severities_unloaded_rule"`, so the `category == "unloaded_rule"` filter excludes it. The substring filter is now redundant — but the substring filter is what previously discriminated the CLI site from the engine site, and the consumer has no signal that the category filter is now wrong.

Forward-compatibility tolerance does NOT save this consumer:
- They DID see the schema_version bump (0.2 → 0.3) in their JSON parsing.
- Their default branch (if any) is for unknown values — `"severities_unloaded_rule"` is now a KNOWN value (the consumer can read it from the Literal docstring).
- Their consumer logic just silently misses CLI-emit-site warnings.

The fix the consumer needs:

```python
# Consumer code after auditing for D6b U5 migration
def find_severities_typos(lint_output: dict) -> list[str]:
    return [
        w["rule_id"] for w in lint_output["runtime_warnings"]
        if w["category"] == "severities_unloaded_rule"  # NEW: the dedicated category
        # OR keep the old filter as a defense for the engine site (rare/never):
        # or (w["category"] == "unloaded_rule"
        #     and "[tool.protokit.lint.severities]" in w["message"])
    ]
```

### CHANGELOG framing — the load-bearing artifact

The U5 CHANGELOG-DRAFT entry (`CHANGELOG-DRAFT.md`) explicitly distinguishes the migration from addition:

```markdown
**Consumer migration (the value migrated, it did not vanish).**
Code currently switching on `category == "unloaded_rule"` and
expecting the CLI-side severities-overlay case will see ZERO matches
after upgrade — the value MIGRATED to `severities_unloaded_rule`,
it did not become unknown. Forward-compatibility tolerance for new
values does NOT save such consumers; the schema_version bump IS
the documented signal that switch tables need re-checking. Audit
existing `category == "unloaded_rule"` paths and split them: keep
the original branch for the engine-emit case (rule named in profile
but not loaded into engine) and add a new
`category == "severities_unloaded_rule"` branch for the
severities-overlay case.
```

Compare to the incomplete framing this learning prevents:

> "Added a new `severities_unloaded_rule` category for the severities-overlay case."

The incomplete framing tells consumers to extend their switch tables but doesn't tell them to AUDIT their existing `unloaded_rule` branches. A consumer reading the incomplete framing leaves the silent-breakage path open.

### Test infrastructure: paired positive + negative assertions

The U5 source-discrimination test module at `tests/schema/lint/cli/test_severities_unloaded_rule_category.py` makes the migration structurally explicit via paired assertions:

```python
def test_unknown_severities_key_emits_severities_unloaded_rule(self, ...):
    # POSITIVE: the migrated emit site now produces the new value
    matching = [w for w in runtime_warnings
                if w["category"] == "severities_unloaded_rule"
                and w["rule_id"] == "naming/does-not-exist"]
    assert matching

def test_unknown_severities_key_does_not_emit_unloaded_rule(self, ...):
    # NEGATIVE: the migrated emit site no longer produces the old value
    # (the source-discrimination contract is broken if both fire)
    leaked = [w for w in runtime_warnings
              if w["category"] == "unloaded_rule"
              and w["rule_id"] == "naming/does-not-exist"]
    assert not leaked
```

Without the negative assertion, a future refactor that accidentally restored the old emit could pass the positive assertion (both `severities_unloaded_rule` AND `unloaded_rule` warnings present) while silently re-introducing the conflation. The negative assertion catches the silent-confidence failure mode per ce:review ADV-6 from the U5 brainstorm pass.

### Producer-side audit checklist before writing the CHANGELOG

Before writing a CHANGELOG entry for a Literal-value addition, run these checks:

```bash
# 1. Find all emit sites for the value being added
git grep -n 'category="new_value"' src/

# 2. Find all emit sites for any value that LOOKS LIKE it might be migrating
git grep -n 'category="old_value"' src/

# 3. Did any of the old-value emit sites change in this diff?
git diff <base> -- src/ | grep -B 2 -A 2 'category='

# 4. If yes, the change is a MIGRATION — write the CHANGELOG accordingly.
#    If no, the change is a pure ADDITION — forward-compat framing is sufficient.
```

The U5 audit found exactly one migrated emit site (`cli.py:1086-1100`) and one preserved emit site (`engine.py:387`). The CHANGELOG-DRAFT framing reflects that split.

## Related

- [[wire-format-schema-version-bump-contract-and-absence-semantic-2026-05-13]] — the parent contract for `schema_version` bumps. The contract's "forward-compatibility tolerance for unknown values" clause is documented narrowly — it protects against value-addition, not value-migration. This learning extends the contract by spelling out the limit case.
- [[closed-literal-discriminator-bump-trigger-2026-05-17]] — sibling learning on the PRODUCER side. That doc covers when a Literal addition triggers a schema_version bump; this doc covers what the bump signals to CONSUMERS. The two learnings together cover the producer-side (when to bump) and consumer-side (what the bump means) of the same wire-format change.
- [[semantic-category-conflation-accepted-tradeoff-literal-widening-2026-05-13]] — value-migration is the natural outcome of resolving a previously-accepted conflation. That doc captures the deferral pattern; this doc captures the migration semantics that surface when the deferred split eventually lands. D6b U5 closed exactly that trip-wire from D6a U9 KTD-2.
- [[pre-1.0-version-bump-as-communication-contract-2026-05-14]] — the package version bump is a separate signal from the wire-format schema_version bump. A migration can ship in a per-unit commit that bumps wire-format only; the package version waits for the delivery boundary. Consumers reading package version as a stability proxy may briefly see decoupled signals.
- [[ce-review-cross-reviewer-agreement-shared-misreading-false-positive-amplifier-2026-05-14]] — the U5 brainstorm document-review pass surfaced the value-migration risk via ADV-3 (adversarial reviewer, P2, conf 0.82). Without the document-review pass, the original CHANGELOG-DRAFT draft would have shipped with the incomplete "added value" framing. The cross-reviewer convergence between adversarial (constructed the silent-breakage scenario) and coherence (caught the contradiction with forward-compat) escalated the finding from advisory to auto-applied fix.
- Anchor commits: `16b494f` (D6b U5 feat — the migration itself), `7cd4095` (D6b U5 ce:review follow-ups — Documentation contract refinements for the value-migration framing), and the U5 brainstorm + plan documents.
- Run artifact: `.context/compound-engineering/ce-review/20260517-180704-b16077be/` — the 9-reviewer pass that surfaced the value-migration vs value-addition distinction.
- [[builtin-packs-expansion-changelog-migration-recipe-structure-2026-05-18]] — the 5th demotion path (Python API via `LintProfile.rule_severity_overrides`, added 2026-05-19 at D6c U5) is the consumer-migration analog for libraries with first-class Python API surfaces alongside CLI. Document both at the delivery boundary so Python API consumers receive the same migration recipe as pyproject `[severities]` consumers.
- [[documented-api-recipe-verify-runnable-2026-05-19]] — companion verification discipline. When a consumer-migration recipe includes Python API code snippets, the snippets must be verified runnable against the actual library import surface before ship. D6c U5's path-5 first draft shipped two broken invocations until ce:review F#3 caught them.
