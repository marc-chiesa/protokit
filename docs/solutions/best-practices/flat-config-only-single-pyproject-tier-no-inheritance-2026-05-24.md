---
title: "Per-rule disable/enable operates within a single pyproject tier — multi-tier inheritance is an explicit out-of-scope decision, not an oversight"
date: 2026-05-24
category: docs/solutions/best-practices
module: protokit.schema.lint._config
problem_type: best_practice
component: tooling
severity: medium
applies_when:
  - "A new lint config field (e.g., disabled_rules, enabled_rules) could plausibly be merged across multiple discovered pyproject.toml files during walk-up discovery"
  - "The plan or brainstorm explicitly defers multi-tier inheritance to a future delivery (D6g+) and the current implementation must not accidentally implement it"
  - "A contributor reads load_pyproject_config and sees the walk-up-then-stop pattern and wants to extend it to merge parent configs"
  - "The feature's R8 polarity-first / tier-second precedence semantics are defined within a single resolved config object, not across multiple config objects"
tags:
  - flat-config
  - single-tier
  - pyproject-discovery
  - config-inheritance
  - architectural-decision
  - walk-up-termination
  - polarity-precedence
  - deferred-design
---

# Per-rule disable/enable operates within a single pyproject tier — multi-tier inheritance is an explicit out-of-scope decision, not an oversight

## Context

D6f U2 added `disabled_rules` and `enabled_rules` directives to `[tool.protokit.lint]`. A natural extension question arose during brainstorm (adversarial-F6): what happens in a monorepo where both a project-root `pyproject.toml` and a subpackage `pyproject.toml` declare `disabled_rules`? Which wins? Does the child `enabled_rules` override the parent `disabled_rules`?

A multi-tier config inheritance design would walk the directory tree upward from the `.proto` file being linted, merge `[tool.protokit.lint]` tables across all discovered `pyproject.toml` files, and apply a precedence policy (child wins / parent wins / explicit polarity).

The D6f U2 design (KD-3) explicitly rejected this. Protokit is **flat-config-only**: there is no `find_pyproject_files()` that walks parent directories. The single `pyproject.toml` discovered at the project root (via the existing `_find_pyproject` search) is the complete configuration. The R8 polarity-first / tier-second precedence that D6f U2 implements applies WITHIN one pyproject AND across the CLI-vs-pyproject boundary — not across multiple pyproject files.

This was not an implicit assumption or an oversight. The D6f plan documented KD-3 explicitly with the rationale, cited the flat-config-only architectural reality (confirmed via [[source-aware-error-messages-multi-source-resolved-value-2026-05-11]]'s codebase inspection), and identified the D6f U2 ce:compound learning deliverable as the durable capture site. The brainstorm adversarial-F6 scenario is labeled `HYPOTHETICAL — D6f does not implement it`.

The choice to defer is further reinforced by the absence of empirical demand: no user had requested multi-pyproject inheritance before D6f shipped. Adding it without a demonstrated use case would increase the config complexity surface (precedence rules, debugging which file set a value, test matrix for all tier combinations) for zero concrete benefit.

## Guidance

**When a new config feature could conceptually support multi-tier resolution, default to flat-config-only and defer multi-tier semantics until there is empirical demand. Document the choice as a deliberate architectural decision — not an oversight — at three sites: the plan, the implementation comment, and a ce:compound learning.**

The three documentation sites ensure the decision survives:

1. **The plan (or brainstorm requirements doc).** Name the multi-tier scenario explicitly and mark it as out-of-scope with a rationale. In D6f U2 this was `KD-3 — Flat-config-only (no multi-tier pyproject inheritance)` in the Implementation Units plan. Future contributors reading the plan before implementing a feature that might introduce multi-tier semantics see the prior decision and its context.

2. **The implementation comment at the config-resolution layer.** The `ResolvedLintConfig.from_dict` docstring (or the `_find_pyproject` / `_load_pyproject` functions) should note that only a single pyproject is resolved per invocation. A contributor adding a second pyproject-loading call in the future will read this note and know to reconsider the flat-config invariant before proceeding.

3. **A ce:compound learning** (this document). The plan-level note tells the team what the decision is; the compound learning tells the team WHY and what the complexity tax of reversing it would look like.

Sub-rules:

1. **Flat-config is the correct default for new config features.** Multi-tier resolution is an additive enhancement: a flat-config-only feature can be extended to multi-tier later without breaking the flat-config contract (adding multi-tier resolution is additive; removing it is a breaking change). The ratchet goes one direction.

2. **Document what "flat-config-only" means precisely.** In protokit-lint, it means: one `pyproject.toml` per invocation, discovered by `_find_pyproject()` searching upward from the CWD to the git root. The R8 precedence (polarity-first, tier-second) operates on: (a) `[severities] X = "off"`, (b) `disabled_rules` list, and (c) `--disable-rule` flags. There is no tier-D (parent pyproject) or tier-E (workspace config). The comment at `ResolvedLintConfig.from_dict` notes this explicitly.

3. **Name the concrete multi-tier scenario that was deferred.** "Multi-tier pyproject inheritance" is not abstract. The scenario is: monorepo root `pyproject.toml` disables a rule; subpackage `pyproject.toml` enables it; the question is which pyproject governs linting in `services/billing/`. Naming the scenario makes the deferral testable — if this exact user request appears in a future GitHub issue, it confirms empirical demand and triggers reconsideration.

4. **Do NOT add multi-tier scaffolding under the guise of "future-proofing."** Partial implementations (a `parent_pyproject_path` field that always resolves to `None`, a `_merge_pyproject_tables` function that only handles a single table) create the illusion of readiness while actually adding confusion. Either implement multi-tier fully or implement flat-config cleanly. Flat-config is the cleaner baseline.

## Why This Matters

**Multi-tier config inheritance is a known source of silent misconfigurations.** Once precedence rules exist across multiple config files, users must understand the full merge semantics to predict which value wins. Debugging a rule that is unexpectedly disabled requires walking the directory tree and reasoning about the precedence policy. A single `pyproject.toml` as the source of truth is debuggable: the user can open one file and see the complete configuration.

**Postponing complexity until demand is demonstrated reduces the test matrix.** The D6f U2 R9b test suite covers: pyproject-only disable, CLI-only disable, both sources with consistent polarity (idempotent), both sources with contradictory polarity (R8b warning), cross-list contradiction (`disabled_rules ∩ enabled_rules`), and the `[severities] = "off"` sentinel vs. enable lists. Adding a second pyproject tier would multiply each of these scenarios by the number of tier combinations (parent-only, child-only, parent+child agree, parent+child conflict, parent pyproject overridden by child, etc.). The complexity growth is super-linear; the concrete user benefit before any user has requested the feature is zero.

**An explicit deferral is contractually different from an oversight.** A codebase that silently lacks multi-tier support could be extended by a contributor without considering the flat-config invariant — resulting in a partial implementation that half-works. A codebase that explicitly documents "flat-config-only, multi-tier deferred to D6g+ pending empirical demand" tells the contributor exactly what they need to check before adding the second file discovery path. The documentation changes the implementation hazard from invisible to visible.

**The flat-config constraint is also an API contract.** Users who build automation on top of protokit-lint's config layer (CI scripts, editor plugins, agents) can rely on the invariant that one pyproject = one config = one behavior. If multi-tier semantics were added without adequate notice, their automation could break silently when a parent pyproject is discovered that they did not expect. Flat-config-only is a promise to those consumers.

## When to Apply

Apply this pattern when ALL of the following are true:

- A new config feature introduces directives that could conceptually apply at multiple levels (project, workspace, monorepo root, user home).
- No user has empirically requested multi-tier semantics for this specific feature.
- The multi-tier design would require precedence rules beyond "CLI wins over file config."

Revisit multi-tier deferral when:

- A concrete user request for multi-tier semantics appears (GitHub issue, support request, user survey).
- A new related feature (e.g., workspace-level config) independently requires multi-tier infrastructure; at that point, R9b can be extended to participate in the same infrastructure.
- The flat-config constraint creates a documented workaround so painful that users are forced to duplicate config across multiple pyproject files.

This pattern does NOT mean "never implement multi-tier config." It means: start flat, document the choice, extend when justified.

## Examples

### KD-3 in the D6f plan (the deferral decision, recorded)

`docs/plans/2026-05-24-001-feat-d6f-r6-promotion-and-r9b-per-rule-disable-plan.md`, KD-3 section:

> Protokit currently uses **flat-config-only**. There is no `find_pyproject_files()` that walks parent directories and merges multiple `[tool.protokit.lint]` tables. The brainstorm adversarial-F6 layered-config scenario (parent `disabled_rules` + child `enabled_rules`) is therefore HYPOTHETICAL — D6f does not implement it.
>
> The R8 polarity-first-disable-wins-across-tiers resolution applies WITHIN a single pyproject's `disabled_rules` + `enabled_rules` lists, AND across the CLI-vs-pyproject tier boundary. Multi-pyproject inheritance is explicit D6g+ (or later) scope.

### What the precedence table covers and what it does not

The R8 precedence table implemented in D6f U2 covers three tiers:

| Tier | Source | Mechanisms |
|------|--------|------------|
| T1 (highest) | CLI | `--disable-rule`, `--enable-rule` |
| T2 | pyproject | `disabled_rules`, `enabled_rules`, `[severities] X = "off"` |
| T3 (implicit) | profile | rule_ids inherited from the active profile pack |

There is no T0 (workspace/parent pyproject). There is no T4 (system-wide config). Adding either would require extending `from_dict` to accept a new source, adding expansion and contradiction detection for the new source, and shipping documentation of the new precedence tier. D6f U2 delivers a three-tier model with a clean contract; extending to four or five tiers is additive.

### The R8 polarity contract (flat-config boundary explicit in the docstring)

`ResolvedLintConfig.disabled_rules` field docstring (D6f U2):

```
UNIFIED disabled-rule set merging three sources: [severities] X = "off"
sentinel ids (intercepted at the coercion layer per KD-1), pyproject
disabled_rules list, and CLI --disable-rule overrides. [...]
cli.py subtracts this set from composed_profile.rule_ids.
```

No mention of a parent-pyproject source, workspace config, or directory-walk merge. The three-source enumeration is the flat-config contract in machine-readable form: if a fourth source is added without updating this docstring, the field contract is stale and a future contributor has a signal that the architecture changed.

### The complexity tax of multi-tier (concrete, not abstract)

The D6f U2 R8b contradiction warning computation (`_compute_r8b_contradiction_warnings`) detects five contradiction patterns across two tiers (pyproject vs. CLI). Multi-tier semantics would require detecting:

- Parent-disabled + child-enabled
- Child-disabled + parent-enabled
- Parent-disabled + child-disabled + CLI-enabled (three-way)
- Parent-off-severity + child-enabled + CLI-disable (four-way)

The message for each contradiction must name all involved mechanisms AND tiers. The number of combinations grows combinatorially. Postponing this until a user demonstrates the need is not timidity — it is the correct response to combinatorial complexity with no confirmed use case.

## Related

- [[source-aware-error-messages-multi-source-resolved-value-2026-05-11]] — the foundational doc that confirms protokit's flat-config-only architecture. Its `applies_when` mentions "walk-up-discovered pyproject" as a hypothetical scenario; flat-config-only makes that scenario explicitly out-of-scope.
- [[symmetric-coercion-strictness-multi-source-field-resolver-2026-05-12]] — the two-source coercion strictness contract that flat-config-only preserves. Multi-tier would force the resolver to handle a third source (parent pyproject) and either extend symmetry or accept asymmetric coercion paths.
- [[click-parameter-source-detection-cli-config-precedence-2026-05-11]] — establishes the current two-source precedence hierarchy (CLI > pyproject > default). Multi-tier would insert a third tier and break the current `ParameterSource` detection model.
- [[sentinel-at-coercion-layer-not-enum-widening-2026-05-24]] — sibling D6f U2 KD pattern. Both keep complexity contained: KD-1 keeps the enum closed; KD-3 keeps the config-tier count closed.
- [[custom-rule-bare-prefix-expansion-at-config-resolution-not-engine-dispatch-2026-05-24]] — sibling D6f U2 KD pattern. KD-2's expansion guarantee holds within the flat-config tier; multi-tier would require re-expansion at each tier boundary.
