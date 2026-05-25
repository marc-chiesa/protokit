---
title: "Accept semantic category conflation when reuse avoids a wire-format Literal widening — document at three sites"
date: 2026-05-13
last_updated: 2026-05-17
category: docs/solutions/best-practices
module: src/protokit/schema/lint/model.py
problem_type: best_practice
component: tooling
severity: medium
applies_when:
  - "A new CLI surface or call site needs to emit a warning whose semantics overlap an existing ``Literal[...]`` category value used in a frozen dataclass that flows to wire-format outputs (JSON, SARIF)"
  - "The user-visible signal is sufficient via message-text attribution (no programmatic origin discrimination is needed at this delivery)"
  - "Adding a new ``Literal`` value would constitute a wire-format change before the feature is stable — JSON ``category`` / SARIF property fields gain a new string"
  - "The two origins can be distinguished via stable message substrings that can be documented as agent-grep anchors"
  - "A future delivery is the appropriate slot for the dedicated category split if real consumer feedback warrants it"
tags:
  - lint-runtime-warning
  - literal-widening
  - category-conflation
  - api-contract
  - wire-format
  - agent-grep
  - deferred-design
  - unloaded-rule
  - three-site-documentation
---

# Accept semantic category conflation when reuse avoids a wire-format Literal widening — document at three sites

## Resolution (D6b U5 — 2026-05-17)

**The specific D6a U9 KTD-2 deferred split has shipped.** D6b U5 (commit `16b494f`) added `"severities_unloaded_rule"` to the `LintRuntimeWarning.category` Literal and switched the CLI-synthesized emit site at `src/protokit/schema/lint/cli.py:1086-1100` to the new value. Wire-format `_LINT_JSON_SCHEMA_VERSION` bumped 0.2 → 0.3 as the consumer-facing signal. The three-site documentation discipline was applied in reverse: the Literal docstring at `model.py:351-510` enumerates per-category contracts for all 5 values, the CLI emit-site comment was updated to acknowledge the resolution (`cli.py:877-882` post-ce:review-follow-up), and the TODOS.md backlog entry was retired in place.

**The general pattern guidance in this doc is still applicable.** The conflation-vs-widening decision tree (when to reuse, when to widen, the three-site discipline) remains valid for FUTURE Literal-widening decisions on different fields. This Resolution annotation closes only the specific D6a U9 KTD-2 instance; the discipline framework lives on.

**The value-migration semantics surfaced during U5** are captured in [[value-migrated-vs-value-added-consumer-migration-2026-05-17]] — when a reuse-then-split decision eventually resolves, the result is value-MIGRATION (not pure value-addition), which has narrower consumer-side protection from forward-compatibility tolerance.

**The bump-contract refinement triggered by U5** is captured in [[closed-literal-discriminator-bump-trigger-2026-05-17]] — the closed-Literal-discriminator vs open-severity-ladder distinction extends the bump contract documented in [[wire-format-schema-version-bump-contract-and-absence-semantic-2026-05-13]].

## Context

D6a Unit 9 R9a wires per-rule severity overrides from the
pyproject ``[tool.protokit.lint.severities]`` table into the CLI's
composed profile. Keys in that table that don't match any
``rule_id`` in the composed profile must surface as a
``LintRuntimeWarning`` so users know the override has no effect.
The natural emit point is the CLI itself — synthesize a warning
at the point the severities overlay is applied.

The new CLI-synthesized warning shares a category with an existing
engine-emitted warning: the engine already emits
``LintRuntimeWarning(category="unloaded_rule", ...)`` for
``profile.rule_ids - loaded_ids`` (a rule named in the profile
but not loaded into the engine). The new CLI site says the same
thing in a different context — "you named a rule_id that won't
take effect" — but the user named it in
``[tool.protokit.lint.severities]``, not in the profile.

Two viable shapes for the new warning:

1. **Widen the Literal** — add ``"severities_unloaded_rule"`` to
   ``LintRuntimeWarning.category: Literal[...]``. Semantically
   cleaner. Programmatic consumers can switch on ``category``.
   But: adding a new string value to a frozen dataclass field
   that serializes to JSON ``category`` and SARIF properties is
   a wire-format change. Consumers pattern-matching on a known
   set of category values see an unknown value and must update.
2. **Reuse the existing value** — emit ``unloaded_rule`` from
   the new site too. Both signals reach the user via
   ``runtime_warnings``. Distinguishing them programmatically
   requires matching message substrings. But: no wire-format
   change; the future split to ``severities_unloaded_rule`` is
   strictly additive when consumer feedback warrants it.

The Unit 9 plan (KTD-2) explicitly accepted the conflation:
"the semantic conflation (profile-named-unloaded vs
severities-named-unloaded) is accepted; both signals reach the
user. A dedicated category for this case can be added in D6b if
real user feedback shows the conflation is confusing." The
ce:review (cli-readiness reviewer, F5) surfaced the need to
document the resolution path so the deferred design isn't lost.

## Guidance

**When a new emission site needs a signal that semantically fits
an existing ``Literal`` category value used in a frozen dataclass
that flows to wire-format outputs, prefer category reuse over
Literal widening IF the user-visible signal via message text is
sufficient. Reuse is reversible (a future delivery can still
widen); widening is a wire-format change at the moment of
introduction. Document the conflation at THREE sites so the
deferred design is discoverable.**

The three-site documentation discipline:

1. **The ``Literal`` type's docstring** in the frozen dataclass
   module — enumerate ALL emit sites for the reused value, with
   their distinguishing message substrings called out as
   agent-grep anchors. A future contributor adding a fourth emit
   site reads this docstring before introducing the fourth
   meaning.
2. **The CLI emit-site code comment** — at the point the
   warning is synthesized, acknowledge the conflation with a
   one-paragraph comment that names the alternative (widening)
   and links to the delivery slot where the split is planned.
   Without this comment, a contributor reading only the emit
   site has no signal that the choice was deliberate.
3. **A named ``TODOS.md`` (or equivalent) backlog entry** —
   captures the dedicated split as a planned future delivery,
   not lost feedback. The entry names the proposed category
   value, the trigger (real consumer confusion), and the
   target delivery slot.

Sub-rules:

1. **Message text must carry the distinguishing signal.** The
   engine-emitted site and the CLI-synthesized site each use a
   stable substring as their identifying anchor (e.g., ``"in
   profile"`` vs ``"[tool.protokit.lint.severities]"``). These
   substrings are load-bearing and must be documented as such in
   the Literal docstring.
2. **The two sites must both populate the same dataclass fields
   in the same shape.** Both shapes carry ``rule_id`` populated;
   both leave ``exception_type`` and ``descriptor_path`` as
   ``None``. Programmatic consumers that don't switch on
   ``category`` should still see structurally identical warnings.
3. **Don't conflate when the new site needs different fields.**
   If the new emit site would require populating additional or
   different fields, the conflation breaks; widen the Literal
   instead.
4. **Don't conflate across user-facing routing boundaries.** If
   the user-facing CLI exit-code routing or formatter behavior
   should differ between the two origins, the conflation hides
   the routing decision in message-substring parsing — widen the
   Literal so the routing logic is explicit.

## Why This Matters

**Widening a wire-format ``Literal`` is irreversible per-version.**
Once a new category value ships in a release, consumers that
pattern-match on the known set see the new value and must update.
A consumer using the JSON output to drive a dashboard would
silently break on the new value. Conflation defers that breakage
indefinitely (until a real use case justifies it).

**The conflation is reversible.** Splitting later — adding
``severities_unloaded_rule`` in D6b — is strictly additive:
existing consumers reading ``unloaded_rule`` still see warnings
they already know how to handle (the engine-emitted site keeps
emitting the original value). Only new consumers that want the
split read the new value. Reuse-now / split-later is a one-way
ratchet toward more specificity, never less.

**Three sites are the minimum for discoverability.** Without the
Literal docstring, a contributor adding a fifth emit site has
no signal the category has multiple origins. Without the emit-
site comment, a contributor refactoring the CLI synthesis can
delete the warning thinking it's incidental. Without the
TODOS.md entry, the deferred design decays into a verbal
agreement that disappears when the team rotates. All three sites
exist to survive turnover.

**The pattern is structurally parallel to
[[buf-parity-divergence-documentation-discipline-2026-05-13]].**
Both decisions defer schema evolution until a second instance
forces the design — that doc deferred a structured
``parity_note`` field until a second divergence; this doc
defers Literal widening until a second category needs separate
wire representation. The "one specimen is not a design signal"
principle applied to two independent schema-extension surfaces.
The four-site protocol over there and the three-site protocol
here differ only in what counts as a site (rule-pack docs add
two sites that don't have analogs in CLI-synthesized warnings).

## When to Apply

Apply this discipline when ALL of the following are true:

1. A new emit site introduces a warning that semantically fits
   an existing ``Literal`` value.
2. The Literal flows to a wire-format output where adding a new
   value would be a breaking change for consumers that switch
   on the known set.
3. The two emit sites can be distinguished via stable message
   substrings that survive translation, locale changes, or
   safe-string sanitization passes.
4. The user-facing CLI behavior (exit code, formatter
   routing) is the same for both origins — no logic needs to
   branch on ``category`` value.
5. A future delivery slot exists where the split can land if
   real consumer feedback warrants it.

The inverse — when to widen the Literal instead:

- **Programmatic consumers need to discriminate the origins** —
  e.g., an agent that auto-fixes only one origin's warnings
  cannot rely on message-substring matching across protokit
  versions.
- **Different formatters need different routing** — if SARIF
  should surface one origin as an error and the other as a
  note, widening makes the routing explicit instead of hiding
  it in message parsing.
- **Different fields are required at the two sites** — the
  conflation only works when the structural shape matches.

## Examples

### Site 1 — Literal docstring with both emit sites enumerated

``src/protokit/schema/lint/model.py:358–386``:

```python
class LintRuntimeWarning:
    """Non-finding warnings that should still surface to the user.

    ...

    2. ``"unloaded_rule"`` — a ``rule_id`` was named in a context
       where it cannot take effect. Two emit sites share the
       category (per D6a U9 KTD-2; semantic conflation is
       accepted — both signals reach the user). Distinguish via
       message content:

       (a) **Engine-emitted** (the original site): the active
       profile's ``rule_ids`` referenced a ``rule_id`` not loaded
       into the engine. ...
       Message: ``rule {rid} is named in
       profile {name} but not loaded into the engine``.

       (b) **CLI-synthesized** (D6a U9 R9a): a key in
       ``[tool.protokit.lint.severities]`` is not in the composed
       profile's ``rule_ids``, so the severity override has no
       effect. Message: ``rule {rid} is named in
       [tool.protokit.lint.severities] but is not in the composed
       profile — the severity override has no effect``.

       Both shapes carry ``rule_id`` populated and ``exception_type``
       / ``descriptor_path`` ``None``. Agents that need to
       programmatically distinguish the two origins should match
       the message substrings ``in profile`` (engine) vs
       ``[tool.protokit.lint.severities]`` (CLI). A dedicated
       category for the CLI-synthesized branch is a D6b candidate
       if real consumer feedback shows the conflation is confusing.
    """
    category: Literal[
        "rule_exception",
        "unloaded_rule",
        ...
    ]
    rule_id: str | None = None
    message: str = ""
    exception_type: str | None = None
    descriptor_path: str | None = None
```

### Site 2 — CLI emit-site comment acknowledging the conflation

``src/protokit/schema/lint/cli.py:1062–1071``:

```python
# R9a (D6a U9): synthesize ``unloaded_rule`` runtime warnings for
# any ``severities`` keys that don't match a rule_id in the
# composed profile. Reuses the existing ``unloaded_rule`` category
# rather than introducing a new ``severities_unloaded_rule`` value
# in the LintRuntimeWarning.category Literal — the semantic fit is
# reasonable (both communicate "you named a rule_id that won't
# take effect") and avoids a wire-format change in D6a.
```

The synthesized warning's message uses the stable
``"[tool.protokit.lint.severities]"`` substring documented in
the Literal docstring as the CLI-site distinguisher:

```python
LintRuntimeWarning(
    category="unloaded_rule",
    rule_id=_safe_for_stderr(rid),
    message=(
        f"rule {_safe_for_stderr(rid)!r} is named in "
        f"[tool.protokit.lint.severities] but is not "
        f"in the composed profile — the severity override "
        f"has no effect"
    ),
)
```

### Site 3 — TODOS.md backlog entry

``TODOS.md`` (D6b backlog section):

```
- **`severities_unloaded_rule` category split**: D6a U9 introduced a
  second emit site for the existing `LintRuntimeWarning.category =
  "unloaded_rule"` value — engine-emitted (rule in profile but not
  loaded) + CLI-synthesized (rule in `[tool.protokit.lint.severities]`
  but not in composed profile). Per Unit 9 KTD-2 the semantic
  conflation was accepted: both signals reach the user; agents
  distinguish via message substring. The U9 ce:review F5 finding
  (cli-readiness reviewer, 2026-05-13) recommends a dedicated
  category value (`severities_unloaded_rule`) in D6b so consumers
  can switch on `category` rather than message substring.
```

### Test for the new emit site (asserts no finding leakage)

A regression net for the CLI-synthesized warning makes sure the
emit shape stays distinct from a real lint finding:

``tests/schema/lint/cli/test_r9a_severities_overlay.py:80–124``:

```python
def test_unknown_rule_id_emits_unloaded_rule_warning(
    self, tmp_path: Path, ...
) -> None:
    ...
    # Synthesized warning is present
    warning = next(
        w for w in result["runtime_warnings"]
        if w["category"] == "unloaded_rule"
        and w["rule_id"] == "totally/unknown-rule"
    )
    assert "[tool.protokit.lint.severities]" in warning["message"]
    # Critically: the unknown rule_id does NOT appear in findings —
    # severity overrides for unknown rules are noisy-warnings,
    # never silent-promotions to error.
    assert all(
        f["rule_id"] != "totally/unknown-rule"
        for f in result["findings"]
    )
```

## Related

- [[buf-parity-divergence-documentation-discipline-2026-05-13]] —
  structurally parallel deferral decision applied to a different
  schema surface. That learning defers a structured
  ``parity_note`` field on ``LintRuleSpec`` until a second
  divergence specimen justifies the schema infrastructure. This
  learning defers a Literal-widening on
  ``LintRuntimeWarning.category`` until a second emit site needs
  separate wire representation. Same "one specimen is not a
  design signal" principle applied to two independent schema-
  extension surfaces. The four-site protocol there and the
  three-site protocol here differ only in what counts as a
  site (rule-pack docs vs CLI synthesis).
- [[frozen-dataclass-paired-field-invariant-post-init-2026-05-11]] —
  ``LintRuntimeWarning`` is the frozen dataclass that this
  learning's category conflation lives on. That learning
  describes the ``__post_init__`` invariant pattern for paired
  fields on the same dataclass. This learning explains why one
  of its ``Literal`` fields (``category``) was reused instead of
  widened when a new emit site arrived — same dataclass, adjacent
  design pressure.
- [[source-aware-error-messages-multi-source-resolved-value-2026-05-11]] —
  the CLI-synthesized warning's message text names the config
  source (``[tool.protokit.lint.severities]``) explicitly,
  applying the source-aware-naming pattern this doc defines.
  The stable substring is what makes message-text
  discrimination viable as a substitute for category
  discrimination.
- [[cli-overrides-deferred-key-notimplemented-trip-wire-2026-05-12]] —
  related deferral discipline at a different boundary. That
  learning hard-fails when a deferred key appears at the
  ``from_dict`` boundary; this learning accepts a deferred
  schema split at the ``Literal`` boundary. Different sites,
  same "defer until justified" mindset.
- Anchor commits: ``c7a426b`` (Unit 9 feat — initial CLI
  synthesis), ``3c828a4`` (ce:review follow-ups — Literal
  docstring updated, F8 assertion added that the unknown
  rule_id does not appear in findings).
- Plan: ``docs/plans/2026-05-12-001-feat-protokit-lint-d6a-rule-library-plan.md``
  Unit 9 R9a / KTD-2.
- 11-reviewer ce:review at ``.context/compound-engineering/
  ce-review/20260513-113000-u9/`` — cli-readiness reviewer F5
  surfaced the documentation-path obligation.
- [[closed-literal-discriminator-bump-trigger-2026-05-17]] —
  triggered by the U5 resolution. The bump-contract refinement
  needed for the U5 split (closed-Literal vs open-ladder
  distinction) extends [[wire-format-schema-version-bump-contract-and-absence-semantic-2026-05-13]].
- [[sentinel-at-coercion-layer-not-enum-widening-2026-05-24]] —
  **third option** in the widen-vs-reuse decision tree (D6f U2 KD-1).
  When the new value is a SENTINEL (semantically different from the
  enum's existing category, e.g., `"off"` as a disable signal vs.
  severity levels), intercept at the coercion layer BEFORE constructing
  the enum value and propagate via a separate field on the return
  type. The enum stays closed; downstream consumers are unchanged.
  This widen-vs-reuse framing assumes the new value belongs to the
  same conceptual category — the sentinel pattern is the correct
  answer when that assumption does not hold.
- [[value-migrated-vs-value-added-consumer-migration-2026-05-17]] —
  the consumer-side semantics of the U5 resolution. When a
  reuse-then-split decision documented here eventually lands as
  this doc anticipated, the result is value-MIGRATION (one
  emit site's output changes from old value to new) NOT value-
  addition. Forward-compatibility tolerance does NOT protect
  consumers from migration; the schema_version bump is the only
  programmatic signal.
- D6b U5 anchor commits: ``16b494f`` (D6b U5 feat — split
  shipped), ``7cd4095`` (D6b U5 ce:review follow-ups), U5
  brainstorm + plan at ``docs/brainstorms/2026-05-17-d6b-u5-r9-severities-category-split-requirements.md``
  + ``docs/plans/2026-05-17-003-feat-d6b-u5-r9-severities-category-split-plan.md``.
