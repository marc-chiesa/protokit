---
title: "Forward-looking CLI help text becomes a P1 agent-discoverability defect the moment the referenced feature ships"
date: 2026-05-12
last_updated: 2026-05-14
category: docs/solutions/best-practices
module: protokit.schema.lint
problem_type: best_practice
component: development_workflow
severity: high
applies_when:
  - "A CLI option's help text, a docstring, or a CHANGELOG entry uses temporal phrasing ('arrives in', 'until X ships', 'currently exits 2', 'forthcoming')"
  - "A sibling delivery ships the feature the help text described as future-state"
  - "Agents or CI scripts use --help output to decide whether to invoke a flag or fall back to a degraded path"
tags:
  - cli-help-text
  - agent-discoverability
  - stale-docs
  - delivery-cadence
  - ce-review
  - protokit-lint
  - forward-reference
  - present-tense-prose
---

# Forward-looking CLI help text becomes a P1 agent-discoverability defect the moment the referenced feature ships

## Context

Incremental delivery workflows split a feature across named units (U1, U2, U3, …) within a single delivery. During U(n), the unit's docstrings, help text, and CHANGELOG entries naturally describe what U(n+1) will do — using phrases like "arrives in U4b" or "until D5 U5 adds the human-format hook" or "currently exits 2 via error[lint-format-unavailable]:". The forward-pointing language is correct *at the moment it ships*, but becomes incorrect the moment the referenced unit lands. Nothing in the local test suite or the static-analysis gate detects help-text accuracy regressions, so the stale prose persists silently.

In this codebase, the U5 ce:review surfaced exactly this failure. The `--format` option help text in `src/protokit/schema/lint/cli.py` still read:

> `'json', 'junit', and 'sarif' arrive in U4b and currently exit 2 via error[lint-format-unavailable]:`

U4b had shipped all three machine formatters before U5 even began. The stale text had survived through **three** delivery cycles — U4a → U4b → U4 ce:review → U5 implementation → U5's own pre-review commit. The `agent-native-reviewer` flagged it FAIL at 0.97 confidence (`cli-readiness-reviewer` also flagged it at 0.90, a two-reviewer convergence): an agent reading `--help` to decide whether `--format=json` was operational would conclude the structured channel was broken and fall back to `--format=human`, silently losing the `runtime_warnings` array.

Two parallel instances surfaced in the same review pass: a `_cli_utils.py` docstring ending "until D5 U5 adds the human-format hook" (stale the moment U5 shipped); a U4 CHANGELOG migration recipe saying "Reverting to --format=human once U5 ships restores stderr emission" (correct as a U4-window note, but the verb tense made it permanent rather than transitional, so the moment U5 shipped the recipe read as if U5 hadn't happened).

## Guidance

### Write user-facing prose in the present tense, even during forward-looking development

Prefer:

> `Output format. One of: 'human' (default), 'json', 'junit', 'sarif'.`

Over:

> `'json', 'junit', and 'sarif' arrive in U4b and currently exit 2.`

If a feature is not yet implemented, **omit the text entirely** rather than describing the future state inline. A `# TODO(U4b): add json/junit/sarif descriptions when registered` source comment is recoverable; a `--help` claim that "json arrives in U4b" persists as a public contract.

### Sweep for stale forward references at every ce:review follow-up commit

The natural checklist step at the end of each unit's ce:review follow-up commit is a grep for the *previous* unit's forward-pointing phrasing:

```bash
# Adapt to your domain's delivery naming.
grep -rn \
  "until D[0-9]\|will land\|arrives in U\|currently exit 2\|forthcoming\|once U[0-9] ships" \
  src/ docs/ CHANGELOG.md
```

When a unit ships, the previous unit's "until X" references are the lowest-cost time to fix — the next ce:review will surface them otherwise, but as P1/P2 findings rather than as a 30-second maintenance task.

### Triage rubric for grep hits — not every match is stale (added 2026-05-14)

The canonical grep is intentionally broad, which means it catches three classes of hits with different remediation paths. The D6a Unit 10 delivery-boundary sweep (see [[delivery-boundary-unit-commit-composition]]) ran the expanded grep across `src/`, `tests/`, `docs/`, `README.md`, and `CHANGELOG.md` and produced ~40 hits, of which ZERO required rewriting once the rubric below was applied. Without the rubric, the temptation is to rewrite each hit; that erases legitimate history and inflates the boundary-unit diff.

Classify each hit into one of three categories before acting:

| Category | Shape | Remediation |
|----------|-------|-------------|
| **Forward-looking-from-now** (the original target) | Present- or future-tense prose describing a feature that does NOT exist yet at the current commit. `"--format json arrives in U4b and currently exits 2"` when U4b has shipped. | **Rewrite to present tense, or omit entirely if the feature still does not exist.** This is the original failure mode this learning was written for. |
| **Past-tense historical reference** | Verb is past-tense; the prose records what shipped in a prior unit or delivery. `"Profile membership widened in D6a Unit 3 from ('default',) to ('recommended', 'default')"`. `"Three independent copies of the same try/except block collapsed in D6a U9 ce:review (F11)"`. | **Leave as-is.** The historical record is correct; the verb tense IS the discriminator. Rewriting past-tense references destroys the narrative that lets future readers reconstruct why the code looks the way it does. |
| **Frozen planning artifact** | The hit lives in `docs/plans/`, `docs/brainstorms/`, or a learning under `docs/solutions/` that documents a past pattern. The forward-looking language was correct at authoring time and is deliberately preserved as a snapshot. `docs/plans/2026-05-04-...-d3-cli-plan.md` containing "until D6 ships". | **Leave as-is.** Plans and brainstorms are snapshots; refer to [[apply-institutional-learnings-postdating-plan-during-ce-review]] for how plan-vs-implementation drift surfaces at ce:review (the plan's forward-looking language is the planning record, not a runtime-discoverable claim). |

**The verb tense is the primary discriminator** between forward-looking-from-now and past-tense historical reference. "Arrives in U4b" (present tense, claim about future) is forward-looking; "shipped in U4b" or "added in D6a U3" (past tense, claim about history) is reference. **The file location is the secondary discriminator**: hits in `docs/plans/` or `docs/brainstorms/` are almost always frozen artifacts; hits in `src/`, `tests/`, `CHANGELOG.md`, or `README.md` need the verb-tense check.

A short post-grep triage loop:

```text
For each hit:
  1. Read the surrounding sentence.
  2. What verb tense does the claim use?
     - Present/future tense about a feature → forward-looking; check feature status, rewrite or omit.
     - Past tense about a shipped unit → historical; leave.
  3. What file is the hit in?
     - docs/plans/ or docs/brainstorms/ → frozen; leave.
     - src/, tests/, CHANGELOG.md, README.md → verb tense decides.
  4. If rewriting, prefer present-tense + remove the delivery name entirely.
```

**Why the rubric matters:** the grep is reusable across deliveries, but its precision degrades over time. By D6a (the fifth delivery), the codebase carries dozens of legitimate past-tense references that the original grep catches. Without the rubric, a contributor running the sweep at the boundary unit sees the long match list and either (a) rewrites them all, destroying history, or (b) abandons the sweep as too noisy. The rubric keeps the sweep usable indefinitely.

### Treat `agent-native-reviewer` and `cli-readiness-reviewer` as explicit gates for this defect class

The `agent-native-reviewer` reads `--help` text the way an agent would and flags any claim that contradicts the current implementation. The `cli-readiness-reviewer` does the same with a focus on CLI flag operability. Their convergence on this finding (two reviewers, 0.97 + 0.90) argues that the check is reliable when invoked. But do not rely on review alone — the U4 ce:review *missed* the `--format` help text staleness that U5 ce:review caught. The text was wrong at the U4 commit; only the U5 review caught it. Catching at commit time via the grep sweep is cheaper than relying on ce:review to surface it one (or two, or three) deliveries later.

## Why This Matters

An agent that reads `--help` to decide whether `--format=json` is safe to use concludes the flag exits 2 and falls back to `--format=human`. Under `--format=human`, the per-category summarization threshold may suppress high-volume runtime warnings; the structured `runtime_warnings` array is unavailable entirely. A CI pipeline that could have been fully automated instead requires manual human inspection of stderr output. The staleness was invisible across three delivery cycles because nothing in the local test suite, mypy, or ruff checked help-text accuracy.

The U5 ce:review surfaced the finding at 0.97 confidence with two-reviewer convergence (agent-native C1b + cli-readiness CLR-U5-03). Cost of the fix: a rewrite of the `--format` help string. Cost of *not* catching it earlier: three cycles of accumulated misleading documentation, plus any downstream automation that made decisions based on stale `--help` output. The fact that two reviewers — each scoped to a different reviewer dimension — independently arrived at the same finding is structural evidence that the failure mode is recurring, not idiosyncratic.

**Fourth consequence — ce:review confidence corruption.** Beyond
misleading agents and corrupting CI automation, present-tense
forward-looking docstrings also actively distort the multi-agent
review pipeline's confidence signal during in-flight delivery
units. When N reviewer personas all read the same forward-looking
docstring and conclude the documented behavior is missing, they
produce **apparent cross-reviewer convergence** — which the merge
stage's agreement boost treats as N independent observations
confirming a real finding. The convergence is spurious: it is one
misreading amplified N times, not N independent confirmations.
The D6b U1 anchor case (2026-05-14) saw 5 reviewers converge at
near-1.0 merged confidence on a "missing CLI wire-up" finding that
was in fact the plan's explicit U3 deferral being misread through
three present-tense docstrings. See
[[ce-review-cross-reviewer-agreement-shared-misreading-false-positive-amplifier]]
for the reviewer-side mirror of this consequence and the merge-stage
independence test that demotes the bogus boost. Combined with the
agent-discoverability and CI-pipeline-decision consequences above,
this means present-tense forward-looking text harms three distinct
audiences — automated agents reading `--help`, CI pipelines making
gating decisions, AND multi-agent review pipelines computing
confidence scores.

## When to Apply

- Any time a unit's docstring, help text, or CHANGELOG entry uses temporal language ("arrives in", "until X ships", "currently", "will be", "forthcoming") describing in-flight work
- When shipping a unit that was previously referenced by name in a previous unit's help text or CHANGELOG (the previous unit's forward references are now stale)
- Any time a ce:review `agent-native-reviewer` or `cli-readiness-reviewer` reports a FAIL on help text accuracy (treat as a checklist for sweeping the rest of the surface)
- During the ce:review follow-up commit: run the stale-reference grep as the first action before fixing any findings — it often surfaces additional misses the reviewers did not call out

## Examples

### Before — stale at U5, written during U4a, never refreshed

```python
@click.option(
    "--format",
    "format_name",
    envvar="PROTOKIT_FORMAT",
    default="human",
    ...
    help=(
        "Output format. 'human' is the default and only format "
        "registered in U4a; 'json', 'junit', and 'sarif' arrive "
        "in U4b and currently exit 2 via "
        "error[lint-format-unavailable]:. Precedence: CLI --format > "
        "PROTOKIT_FORMAT envvar > [tool.protokit.lint] format in "
        "pyproject.toml > built-in default ('human')..."
    ),
)
```

### After — present-tense, no delivery-conditional language

The minimal lesson is to drop the delivery reference and use present-tense verbs:

```python
help=(
    "Output format. One of: 'human' (default), 'json', 'junit', 'sarif'. "
    "Precedence: CLI --format > PROTOKIT_FORMAT envvar > "
    "[tool.protokit.lint] format in pyproject.toml > built-in default "
    "('human')..."
),
```

The actual protokit U5 follow-up commit went further and described what each format emits — but that is a separate documentation-richness decision, not the lesson here. The point is: the temporal phrasing is gone.

### Docstring forward-reference that became stale

```python
# Before — stale after U5 shipped:
#: Note: the legacy ``warning[lint-runtime]:`` stderr prefix was
#: removed in D5 U4 (R21). Runtime warnings ... surface only via the
#: machine formatters (``--format=json`` / ``--format=junit`` /
#: ``--format=sarif``) until D5 U5 adds the human-format hook.

# After — describes the current state:
#: Note: the legacy ``warning[lint-runtime]:`` stderr prefix was
#: removed in D5 U4 (R21) and is not restored. Runtime warnings ...
#: are carried in ``LintReport.runtime_warnings``. Under
#: ``--format=human`` (the default) they surface on stderr via the
#: D5 U5 CLI-side hook as
#: ``protokit lint: warning [<category>]: <message>`` — see
#: ``_emit_human_runtime_warnings`` in ``cli.py``.
```

### CHANGELOG entry whose future-tense verb made the recipe permanent

```markdown
<!-- Before — written during U4 development as a transitional recipe.
     The phrasing "once U5 ships restores stderr emission" describes
     U5 in the future tense, so the moment U5 ships, the recipe reads
     as if U5 hadn't happened. -->
**Migration recipe (human-format CI):** replace
`protokit lint <args>` with
`protokit lint --format=json <args> | jq '.runtime_warnings'`,
or set `format = "json"` in `[tool.protokit.lint]` and parse the
emitted JSON. Reverting to `--format=human` once U5 ships
restores stderr emission with no other code changes.
```

```markdown
<!-- After — present-tense, distinguishes "during the U4 window" from
     "after U5 shipped" explicitly. -->
**Migration recipe (human-format CI, transitional):** during the
U4-only window CI scripts replaced `protokit lint <args>` with
`protokit lint --format=json <args> | jq '.runtime_warnings'`,
or set `format = "json"` in `[tool.protokit.lint]` and parsed the
emitted JSON. Reverting to `--format=human` once U5 shipped
restores stderr emission under the NEW envelope shape — see U5
entry for the new prefix.
```

## Related

- [[apply-institutional-learnings-postdating-plan-during-ce-review-2026-05-09]] — the broader pattern of plan/implementation staleness; this learning is the runtime-discoverable-text variant (help text, docstrings, CHANGELOG forward references) of the same family. **Triage cross-ref:** the "frozen planning artifact" category in the rubric above defers to that learning for how plan docs evolve.
- [[click-parameter-source-detection-cli-config-precedence-2026-05-11]] — CLI parameter-source detection; adjacent CLI-help discipline
- [[source-aware-error-messages-multi-source-resolved-value-2026-05-11]] — keeping output prose synchronized with the current resolved configuration state
- [[public-surface-draft-discipline-source-audit]] — sibling failure mode: this learning covers stale **temporal phrasing** ("will land in U6", "currently exit 2 via ..."); the companion covers stale **factual surface enumeration** (dataclass field lists, error code names, CLI flags claimed in API tables that no longer match source). Both are documentation-drift problems with different remediation patterns: tense audit (this doc) vs source-grep audit (companion). Same broad documentation-discipline family, different granularities.
- [[delivery-boundary-unit-commit-composition]] — the boundary unit invokes this sweep as one of its required deliverables; the triage rubric above is the discriminator that keeps the sweep efficient as the project ages.
- [[ce-review-cross-reviewer-agreement-shared-misreading-false-positive-amplifier]] — **reviewer-side consequence.** This learning documents why forward-looking docstrings exist and how to triage them (author-side). The companion doc captures the reviewer-side failure mode: the same present-tense forward-looking docstrings prime multiple `ce:review` reviewer personas identically, producing apparent cross-reviewer convergence that the merge stage's agreement boost misinterprets as independent confirmation. A fourth consequence class for the "Why This Matters" enumeration (alongside agent-discoverability and CI-pipeline drift): unswept stale docstrings actively corrupt the multi-agent review pipeline's confidence signal during in-flight delivery units.
