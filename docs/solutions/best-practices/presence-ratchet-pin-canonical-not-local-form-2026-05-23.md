---
title: "Pin the canonical cross-document phrase in presence ratchets, not the docstring's local form"
date: 2026-05-23
category: docs/solutions/best-practices
module: protokit.schema.lint
problem_type: best_practice
component: testing_framework
severity: medium
applies_when:
  - "A policy phrase appears in multiple documents (docstring + README + CHANGELOG + plan) and a presence-ratchet test guards it against silent drift"
  - "An internal surface (module docstring, config comment, generated --help text) carries a truncated or paraphrased form of a phrase whose canonical authoritative form lives in a user-facing surface (README, CHANGELOG)"
  - "The presence-ratchet substring was drafted from whichever copy of the phrase the author had open at the time, not deliberately extracted from the canonical source"
  - "The phrase carries load-bearing rationale clauses (the 'why' of a contract, not just the 'what') that could be silently dropped without changing whether the test passes"
symptoms:
  - "ce:review flags the ratchet pin as too narrow — the canonical README/CHANGELOG form could be silently shortened to match the docstring's truncated form with no CI signal"
  - "Two surfaces describe the same policy with divergent phrasing; the divergence persists across multiple deliveries because nothing catches it"
  - "A load-bearing clause (e.g., 'not buf's defaults', 'see X for the escape hatch') is present in README but absent from the docstring — the ratchet asserts on the docstring's truncated form and never demands the clause be carried into the docstring"
root_cause: inadequate_documentation
resolution_type: test_fix
related_components:
  - documentation
  - development_workflow
tags:
  - presence-ratchet
  - substring-pin
  - canonical-form
  - cross-document-drift
  - documentation-discipline
  - docstring-divergence
  - anti-revert
  - policy-stability
---

# Pin the canonical cross-document phrase in presence ratchets, not the docstring's local form

## Context

Discovered during the D6e U4 ce:review cycle (M2 finding, 2026-05-23) in protokit. The `BUILTIN_PACKS` module docstring at `src/protokit/schema/lint/rules/__init__.py` carried a truncated form of the D6e KD-1 UX-philosophy POSITIONING_STATEMENT:

> "protokit targets buf BASIC coverage; defaults reflect Python-protobuf-dev ergonomics."

The canonical authoritative form — present byte-identical in `README.md` (line 482) and `CHANGELOG.md` (line 458) — was longer and carried two load-bearing clauses absent from the docstring:

> "protokit targets buf BASIC coverage; defaults reflect Python-protobuf-developer ergonomics, not buf's defaults (see proto2-strict for opt-in proto2 strictness)."

The presence-ratchet test in `tests/test_uxd_philosophy_principle_presence_ratchet.py` was written against the docstring's truncated form (`"Python-protobuf-dev ergonomics."`), not the canonical form. A future editor reformatting README to match the docstring would have passed CI while silently dropping:
- **"not buf's defaults"** — the rationale clause that *defines* the KD-1 ergonomics-over-buf-parity stance against a foil. Without it, KD-1's "why" disappears and future maintainers cannot tell that tightening defaults toward buf's opinion is contrary to the established policy.
- **"see proto2-strict for opt-in proto2 strictness"** — the only forward pointer to the escape hatch for users who DO want buf-style strictness. Without it, the doc loses its only cross-reference to the opt-in profile.

The asymmetry was invisible by construction: the test still passed against the docstring after the canonical clause was dropped, because the test was already checking a truncated string.

This learning is the cross-document-sourcing companion to [[presence-ratchet-test-pattern-for-prose-substrings-2026-05-14]]. That parent learning covers the technical mechanics of ratchet construction (rule 5: single-source-line; rule 1: shortest uniquely-identifying substring; rule 6: line-anchored per-section regex). This learning covers the upstream question its discipline rules don't address: **which form of the phrase to pin against, when the phrase exists in more than one document with potential micro-divergence between them.**

A prior session warning signal (session history): at the D6d new-U4 boundary (2026-05-21), the learnings reviewer flagged a "POTENTIAL MISSING RATCHET" for the positioning-statement surface, noting that the bump-contract ratchet pinned Literal values correctly but that prose policy claims in the docstring were relying on a single substring that could degrade silently if the docstring was shortened. The full failure mode (canonical-vs-local divergence) only surfaced one delivery later, at D6e U4, when the canonical form landed in README/CHANGELOG and the docstring did not catch up.

## Guidance

When designing a presence ratchet over a contract phrase that appears in multiple documents (docstring + README + CHANGELOG + plan):

1. **Identify the canonical authoritative source first.** The canonical source is the most user-facing surface — typically README/CHANGELOG over an internal module docstring. A docstring is a derivative artifact; the README is the contract a user reads. When the docstring and README diverge, the canonical source wins by default.

2. **Pin the load-bearing substring from the canonical form, not the substring as it appears in any one local copy.** "Load-bearing" means: the clause whose removal would change the contract's *meaning*, not just its wording. In the POSITIONING_STATEMENT example, `"not buf's defaults"` is load-bearing because it defines the ergonomics choice against a foil; `"see proto2-strict for opt-in proto2 strictness"` is load-bearing because it is the only forward pointer to the escape hatch. By contrast, `"defaults reflect"` is wording (replaceable by `"defaults carry"` or `"defaults match"` without changing meaning) and is not worth pinning.

3. **If the canonical form exceeds one line, split into multiple single-line substrings — one per content line.** Per [[presence-ratchet-test-pattern-for-prose-substrings-2026-05-14]] rule 5, each substring must fit on a single source line as it appears in the file under test. Iterate over a tuple of substrings and assert each independently so a CI failure message identifies exactly which load-bearing clause was dropped.

4. **If a local copy carries a truncated form, treat that as a docstring bug and fix it.** Do not accommodate the truncation by pinning the shorter phrase. The docstring must be updated to match the canonical form; otherwise the ratchet and the canonical surface will diverge again at the next rewrite, recreating the vulnerability.

5. **Record the canonical source in the test comment.** The test should state which document is authoritative and why, so the next editor knows not to "simplify" the pinned substring to match whatever the docstring happens to say at the time. A comment like `# Canonical authoritative form: README.md / CHANGELOG.md KD-1 block. Do NOT shorten these substrings to match the docstring; fix the docstring instead.` makes the discipline explicit at the point of edit.

## Why This Matters

A presence ratchet's purpose is to catch silent drift. Pinning the local (truncated) form converts the ratchet into a self-fulfilling guard: it catches drift away from the local form, but it does not catch drift FROM the canonical form INTO the local form. This asymmetry creates a **unidirectional vulnerability** — the canonical clause can be shortened or deleted, and CI still passes because the test was already checking a truncated string.

The failure mode is invisible by construction. Nothing in the test output signals that the canonical clause was dropped; the test passes and the reviewer has no prompt to look further. The KD-1 "not buf's defaults" rationale exists precisely to prevent future maintainers from silently tightening defaults toward buf's opinion. A ratchet that cannot detect the removal of that rationale is not guarding the contract — it is guarding the wording of a local copy.

The broader principle: when a phrase exists in both an internal surface (docstring, config comment, generated `--help` text) and an external surface (README, CHANGELOG, public-facing spec), the internal surface is the one at risk of quiet truncation (developers shorten docstrings for line-length, "readability", or fashion), and the external surface is the one a user actually depends on. The ratchet must be anchored to the external surface, even if the test is reading the source of the internal surface to verify it.

This is also why the related family of "byte-equivalence" learnings — [[changelog-readme-snippet-fixture-byte-equivalence-2026-05-21]] for TOML snippets, [[verify-reviewer-sort-ordering-claims-against-canonical-regen-2026-05-19]] for sort ordering — all converge on the same discipline: **find the canonical source first, then verify the secondary artifacts against it.** The presence-ratchet pattern is the prose-substring instance of that family.

## When to Apply

Apply this guidance whenever a presence-ratchet test is being written (or reviewed) and the protected phrase appears in more than one document:

- Source code docstring AND user-facing README or CHANGELOG (the POSITIONING_STATEMENT case)
- Plan document AND multiple downstream artifacts (CHANGELOG entry, release notes, README upgrade section, `--help` text)
- Module docstring AND auto-generated CLI `--help` output that surfaces the same policy
- Any internal comment AND an external specification or contract document

Apply also during **ratchet review** (ce:review maintainability phase): if a ratchet test contains a string that is obviously shorter than the phrase in README or CHANGELOG, flag it as a canonical-source mismatch rather than accepting it as intentional brevity. The reviewer prompt is: "Could the canonical README/CHANGELOG form be silently shortened to match this ratchet substring? If yes, the ratchet is anchored to the wrong source."

Skip this discipline when the phrase exists in only one document — there is nothing to diverge from. The risk surfaces specifically at cross-document boundaries.

## Examples

### Before — pinned to truncated local (docstring) form; vulnerable to canonical-form drift

```python
def test_positioning_statement_pinned_in_builtin_packs_docstring():
    """D6e POSITIONING_STATEMENT pinned in the BUILTIN_PACKS docstring."""
    from protokit.schema.lint import rules

    source = inspect.getsource(rules)
    substring = (
        "protokit targets buf BASIC coverage; defaults reflect "
        "Python-protobuf-dev ergonomics."  # ← truncated to match local docstring
    )
    assert substring in source
```

This passes even if README/CHANGELOG are edited to remove `"not buf's defaults"` and `"see proto2-strict for opt-in proto2 strictness"`, because the test never checks those clauses. The canonical surface can silently collapse to the docstring's truncated form with no CI signal.

### After — pins load-bearing substrings from the canonical README/CHANGELOG form

```python
def test_positioning_statement_pinned_in_builtin_packs_docstring():
    """D6e POSITIONING_STATEMENT pinned in the BUILTIN_PACKS docstring.

    Pinning two substrings — each fits on a single source line per
    [[presence-ratchet-test-pattern-for-prose-substrings]] rule 5 —
    locks BOTH load-bearing clauses of the canonical README/CHANGELOG
    form. The two-pin strategy closes the M2 gap where a single pin
    against the truncated docstring form would have allowed silent
    drift if the canonical form was shortened to match the docstring.
    """
    from protokit.schema.lint import rules

    source = inspect.getsource(rules)
    # Canonical authoritative form: README.md / CHANGELOG.md KD-1 block.
    # Do NOT shorten these substrings to match the docstring; fix the
    # docstring to match the canonical form instead.
    substrings = (
        "Python-protobuf-developer ergonomics, not buf's defaults",  # load-bearing rationale
        "see proto2-strict for opt-in proto2 strictness",             # load-bearing cross-ref
    )
    for substring in substrings:
        assert substring in source, (
            f"Canonical POSITIONING_STATEMENT clause missing from "
            f"BUILTIN_PACKS docstring: {substring!r}"
        )
```

Simultaneously, the docstring in `src/protokit/schema/lint/rules/__init__.py` was updated to carry all three lines of the canonical form (the prior single-line truncated form was deleted), and an inline pointer comment was added directing future editors to the ratchet test before reformatting:

```
D6e POSITIONING_STATEMENT
-------------------------

protokit targets buf BASIC coverage; defaults reflect
Python-protobuf-developer ergonomics, not buf's defaults
(see proto2-strict for opt-in proto2 strictness).

Both the KD-1 line above and the 3-line POSITIONING_STATEMENT
block are protected by
``tests/test_uxd_philosophy_principle_presence_ratchet.py``.
KD-1 is pinned by a single substring; POSITIONING_STATEMENT is
pinned by TWO substrings ("not buf's defaults" + "see proto2-
strict") — reformatting either content line may break the
two-substring ratchet. Update the test substrings alongside any
canonical rewording.
```

Both ends of the canonical-vs-local axis now agree: the docstring carries the full canonical form, and the ratchet pins the load-bearing substrings from that form. Subsequent rewrites in either direction (canonical-shortening or docstring-truncation) trigger CI.

### When a one-pin form is still correct

This discipline applies only when divergence is possible. If a phrase exists in only one document, or all copies are mechanically generated from a single source, a single substring pin is sufficient. The KD-1 line itself (`"D6e KD-1: protokit-UX overrides buf-parity; proto2-specific strict rules ship in proto2-strict."`) lives only in the BUILTIN_PACKS docstring at protokit; no README or CHANGELOG carries an alternative form. The companion test in the same file pins KD-1 with a single substring, which is correct for that case.

## Related

- [[presence-ratchet-test-pattern-for-prose-substrings-2026-05-14]] — **parent learning.** Covers the technical mechanics of presence-ratchet construction (rule 5 single-source-line, rule 1 shortest-uniquely-identifying-substring, rule 6 line-anchored per-section regex). This doc is the cross-document-sourcing companion: rules 1–6 govern HOW to construct the ratchet within one artifact; this doc governs WHICH form of the phrase to pin against when the phrase exists in multiple artifacts with potential divergence.
- [[changelog-readme-snippet-fixture-byte-equivalence-2026-05-21]] — sibling discipline for executable TOML snippets. Both learnings converge on "find the canonical source first, then verify secondary artifacts against it." The byte-equivalence learning covers TOML-as-config; this learning covers prose-as-policy.
- [[verify-reviewer-sort-ordering-claims-against-canonical-regen-2026-05-19]] — sibling discipline for sort-ordering claims. Same canonical-source pattern, different artifact type.
- [[stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12]] — adjacent staleness failure mode. That learning covers stale TEMPORAL phrasing ("until X ships"); this learning covers stale CANONICAL phrasing (the wrong form of the phrase pinned). Both surface at delivery-boundary documentation passes; both need explicit verification steps to catch.
- [[delivery-boundary-unit-commit-composition-2026-05-14]] — the boundary-unit checklist that should invoke this discipline whenever a new presence ratchet is added (or an existing one updated) at the delivery boundary. The 7-component checklist's presence-ratchet item should reference this learning for cross-document phrases.
- [[delivery-boundary-bundled-commit-feat-plus-review-followups-2026-05-21]] — the bundled-commit discipline that governed how the D6e U4 follow-up fix landed (separate `fix(lint):` commit, since the U4 boundary at `6dd35ca` was already committed when ce:review ran).
