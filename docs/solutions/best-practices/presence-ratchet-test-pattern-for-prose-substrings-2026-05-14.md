---
title: "Presence-ratchet test pattern: pin prose substrings in docs/source against silent reversion when static analysis can't read them"
date: 2026-05-14
category: docs/solutions/best-practices
module: testing_framework
problem_type: best_practice
component: testing_framework
severity: medium
applies_when:
  - "A prose-bearing artifact (CHANGELOG section, KD-style policy docstring, README disclaimer, ADR conclusion) encodes a load-bearing commitment that no static analyzer or type checker can validate"
  - "Silent reversion or rewording of the prose would weaken the commitment without breaking any code path — the regression class is 'somebody edited the policy text and nobody noticed'"
  - "The artifact is already pinned by membership-list tests (e.g., `BUILTIN_PACKS` tuple equality) or structural pins (e.g., inspect.getsource collision branches), but the prose around the pin is itself the contract"
  - "The test is intentionally trivial — one substring check against one file — and the cost-of-carrying is negligible compared to the regression class it prevents"
related_components:
  - testing_framework
  - documentation
tags:
  - presence-ratchet
  - substring-pin
  - anti-revert
  - documentation-discipline
  - policy-stability
  - test-pattern
  - changelog-test
  - docstring-test
---

# Presence-ratchet test pattern: pin prose substrings in docs/source against silent reversion when static analysis can't read them

## Context

The protokit-lint codebase already has three ratchet patterns
that pin stability-bearing surfaces against silent regression:

1. **Membership-pin** —
   `tests/schema/lint/test_builtin_packs.py:test_builtin_packs_membership_pin`
   asserts `tuple(p.__name__ for p in BUILTIN_PACKS) == ("protokit.schema.lint.rules.naming", "protokit.schema.lint.rules.enum", ...)`. Any change to the
   auto-load tuple fails CI; the contributor must update the
   expected tuple (signaling intent). See
   [[pytest-static-analysis-gate-ratchet]] for the
   file-set-membership variant.
2. **Structural pin** —
   `tests/schema/lint/cli/test_severities_user_wins_structural.py`
   uses `inspect.getsource()` to assert the user-wins
   dict-spread order in `cli.py` evaluates user-severities AFTER
   profile-defaults. See
   [[structural-pin-inspect-getsource-untestable-collision-branch]]
   for the technique.
3. **Cross-file regex pin** —
   `tests/test_buf_parity_pin_drift.py` greps a regex anchored to
   the constant's structural shape (`_BUF_PARITY_PIN: str = "..."`)
   against `.github/workflows/ci.yml` to catch
   buf-version-string drift between two source-of-truth files.
   See [[cross-file-pin-regex-anchor-structure-not-annotation-token]].

D6a Unit 10 surfaced a fourth case the existing patterns don't
cover: the KD-9 policy docstring at
`src/protokit/schema/lint/rules/__init__.py` was amended to the
pre-1.0 stance ("while protokit is pre-1.0 there is no stability
guarantee; new packs may be added to BUILTIN_PACKS freely,
accompanied by a CHANGELOG entry"). The amendment is **prose** —
not a constant, not a tuple, not a code shape. Membership-pin
doesn't apply (no list to assert against). Structural-pin doesn't
apply (the prose has no fixed line/word shape — paragraphs may
be re-flowed without altering meaning). Cross-file regex pin
doesn't apply (the prose lives in exactly one file). But the
prose IS load-bearing: it authorizes
[[pre-1.0-version-bump-as-communication-contract]], and a future
contributor refactoring the docstring could trivially revert the
pre-1.0 carve-out back to the original "major-version bump
required" wording without any test failure.

The same shape recurred in `CHANGELOG.md`: the `### D6a — ...`
section is the user-facing communication contract per
[[delivery-boundary-unit-commit-composition]], and a release
without that section would silently omit the delivery's
upgrade-time documentation.

**The presence-ratchet pattern fills this slot.** A trivial
pytest assertion that a specific substring (or heading) exists
in a specific file. The substring IS the contract; the test
documents which substring carries the weight and why.

## Guidance

### The shape of a presence-ratchet test

```python
"""Presence ratchet for [the prose artifact].

[Two-paragraph explanation: what the prose carries, why it's
load-bearing, what silent reversion would cost. Close with:
"This test is a presence ratchet, NOT a stability contract over
the [shape / structure / wording]."]
"""

from __future__ import annotations

from pathlib import Path

import [the_module]  # or read a file with Path(...)


RATCHET_SUBSTRING = "exact text that carries the contract"
# Or: REPO_ROOT = Path(__file__).resolve().parent.parent
#     ARTIFACT_PATH = REPO_ROOT / "CHANGELOG.md"


class TestArtifactRatchet:
    def test_artifact_exists(self) -> None:
        # Optional: assert the artifact itself is present
        # (file exists, module has a __doc__, etc.). Catches
        # "deleted the entire file/docstring" as a distinct
        # failure mode from "reworded the substring".
        ...

    def test_ratchet_substring_is_present(self) -> None:
        """Substring ratchet against silent reversion of [the contract].

        If you are intentionally rewording or moving the
        [policy / section / clause], update RATCHET_SUBSTRING
        above to match the new wording — but only after
        confirming the new wording carries the same meaning.
        """
        body = [the source — module docstring, file read, etc.]
        assert RATCHET_SUBSTRING in body, (
            "[Specific failure narrative: what the substring "
            "protects, what silent reversion would mean for "
            "consumers, what the contributor's two valid paths "
            "are — restore the substring or update the test "
            "after confirming the new wording is semantically "
            "equivalent.]"
        )
```

### The four discipline rules

1. **The substring IS the ratchet, NOT the shape.** Pick the
   shortest substring that uniquely identifies the contract.
   Long substrings (whole paragraphs) couple the test to prose
   formatting and break on benign reflows; one-word substrings
   are too brittle (common words appear elsewhere). The D6a U10
   ratchets use single-clause substrings: `"pre-1.0 there is no
   stability guarantee"` (the KD-9 stance) and `"D6a"` (the
   CHANGELOG section identifier). Neither is reformattable into
   nonexistence; both are deliberate-intent substrings.

2. **Comments / docstrings explicitly say "presence, not shape
   contract".** A future reader sees the test and asks "do I
   need to maintain the exact wording?". The test docstring's
   first paragraph must answer that explicitly. Without the
   disclaimer, the ratchet drifts toward a stability contract
   that constrains prose evolution unnecessarily.

3. **Failure messages point at the deliberate update path.**
   The assertion message must name BOTH paths the contributor
   can take: (a) restore the substring (the change was
   accidental), (b) update the ratchet constant (the change was
   deliberate and the new wording is semantically equivalent).
   Without the deliberate path, the ratchet feels like a wall;
   with it, the ratchet feels like a checklist.

4. **One test per artifact, one substring per test.** Don't
   stack multiple ratchets in one test method — when one fails,
   pytest stops on the first assertion and the contributor sees
   only that signal. Separate tests separate failure narratives.

### When to add a presence-ratchet vs other ratchet types

| Pattern | What it pins | When |
|---------|--------------|------|
| Membership pin | Tuple/list/set equality | Auto-load surfaces, error-code enumerations, registered formatters |
| Structural pin (inspect.getsource) | Source-code shape | Evaluation-order invariants, code patterns no fixture can exercise |
| Cross-file regex pin | Multi-source-of-truth string agreement | Version pins, dependency identifiers, configuration values that appear in 2+ files |
| **Presence ratchet (this pattern)** | **Prose substring** | **Load-bearing policy text in docstrings, CHANGELOG sections, README disclaimers — content no static analyzer reads** |

The presence-ratchet's blast radius is minimal: one assertion
on one file read. Cost-of-carrying is negligible (<10ms test
runtime). The regression class it prevents is concrete: a
contributor doing a docstring refactor or a CHANGELOG cleanup
accidentally weakens a policy stance.

## Why This Matters

**Prose is invisible to type checkers and linters.** mypy,
ruff, pyright, eslint — none of them read documentation. A
contributor rewording a KD-policy docstring from "pre-1.0
there is no stability guarantee" back to "the protokit major
version is being bumped" passes every gate. The reviewer
catches it only if they remember the original amendment's
motivation. The presence-ratchet replaces "reviewer
remembers" with "CI fails loudly".

**The substring is a stability-of-intent contract, not a
stability-of-prose contract.** Future contributors are free to
reformat, re-paragraph, or move the surrounding prose. They are
NOT free to silently remove the load-bearing clause. The
ratchet draws the line at exactly the right granularity: the
clause itself, not its formatting.

**The failure message is the deliberate-change checklist.**
When the ratchet fails, the contributor reads the assertion
message: "either restore the substring or update
RATCHET_SUBSTRING after confirming the new wording is
semantically equivalent". This is the same pattern as the
[[pytest-static-analysis-gate-ratchet]]'s deliberate-update
prompt: the ratchet forces an explicit decision rather than a
silent drift.

**Sibling-cluster discoverability.** Three pre-existing ratchet
patterns already exist in the codebase. The presence-ratchet
slots into the family with a clear sibling-table, so future
contributors looking for an anti-regression mechanism find
the right one via the cross-references rather than reinventing
a less-disciplined variant.

## When to Apply

Add a presence-ratchet when ALL of the following hold:

- A specific prose substring (in a docstring, CHANGELOG
  section, README, ADR) carries a load-bearing commitment.
- No code path validates the commitment — static analysis,
  type checking, and existing tests are silent on it.
- The substring is uniquely identifying (not too short to
  collide, not too long to be format-fragile).
- The regression class is "somebody edited the prose without
  realizing the policy weight" — silent and undetectable
  without the ratchet.

**Skip the ratchet when:**

- The prose is descriptive, not load-bearing (e.g., a code
  comment explaining what a function does — type signatures
  and tests are the contract).
- A stronger ratchet already covers the same surface (e.g.,
  if a tuple-membership pin asserts the auto-load set, a
  prose ratchet on the surrounding docstring is redundant —
  unless the docstring carries an additional policy clause
  beyond what the tuple encodes).
- The substring is short enough that it appears elsewhere
  in the file by coincidence (refactor the substring to be
  more specific, or use a structural-pin variant via
  inspect.getsource).

## Examples

### KD-9 docstring ratchet (D6a U10)

```python
# tests/schema/lint/rules/test_kd9_docstring.py
"""Substring-ratchet for the KD-9 upgrade-safety docstring.

The KD-9 policy in `protokit.schema.lint.rules.__init__` documents
the pre-1.0 stance that new packs may be added to `BUILTIN_PACKS`
freely when accompanied by a CHANGELOG entry, with the
major-version gate deferred until post-1.0. This test pins the
pre-1.0 sentence as a substring so that an accidental revert to
the original "major-version bump required" wording fails CI
rather than silently landing.

The test is intentionally a substring check, NOT a structural
parse: the docstring is human-facing prose, and re-flowing the
surrounding paragraphs should not break the ratchet. Only
deleting or rewording the pre-1.0 stance itself trips this
assertion.
"""
import protokit.schema.lint.rules as rules_pkg

PRE_1_0_RATCHET_SUBSTRING = "pre-1.0 there is no stability guarantee"


class TestKD9Docstring:
    def test_module_docstring_exists(self) -> None:
        assert rules_pkg.__doc__ is not None, (
            "protokit.schema.lint.rules has no module docstring — "
            "KD-9 policy lives in that docstring; restore it."
        )

    def test_pre_1_0_stance_substring_is_present(self) -> None:
        docstring = rules_pkg.__doc__ or ""
        assert PRE_1_0_RATCHET_SUBSTRING in docstring, (
            f"KD-9 docstring no longer contains "
            f"{PRE_1_0_RATCHET_SUBSTRING!r}. The pre-1.0 stance "
            "was reverted or reworded. Either restore the substring "
            "or update PRE_1_0_RATCHET_SUBSTRING in this test "
            "after confirming the new wording carries the same "
            "meaning."
        )
```

### CHANGELOG presence ratchet (D6a U10)

```python
# tests/test_changelog_d6a_entry.py
"""Presence ratchet for the D6a CHANGELOG section.

The KD-9 upgrade-safety policy in
`src/protokit/schema/lint/rules/__init__.py` requires every
`BUILTIN_PACKS` expansion to be accompanied by a CHANGELOG entry
that calls out the auto-load expansion and the demotion paths.
[...] This test asserts that CHANGELOG.md contains a heading
naming "D6a". It does NOT enforce the shape of the heading or
the content of the section.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"


class TestChangelogD6aEntry:
    def test_changelog_exists(self) -> None: ...

    def test_changelog_names_d6a(self) -> None:
        body = CHANGELOG_PATH.read_text(encoding="utf-8")
        assert "D6a" in body, (
            "CHANGELOG.md does not name the D6a delivery. The "
            "KD-9 policy [...] requires every BUILTIN_PACKS "
            "expansion to be documented in the changelog so "
            "users can predict the upgrade-time finding surface. "
            "Restore the D6a section or update this ratchet to "
            "match a deliberately renamed heading."
        )
```

Both ratchets total ~110 lines of test code. Total runtime:
under 20ms on the project's CI. Total cognitive carrying cost:
zero — the tests are self-explanatory at first read.

## Related Learnings

- [[pytest-static-analysis-gate-ratchet]] — canonical
  ratchet doc; the presence-ratchet is a sibling that pins
  prose substrings instead of file-set membership.
- [[structural-pin-inspect-getsource-untestable-collision-branch]] —
  sibling ratchet pattern that pins source-code shape. Choose
  the structural pin when the shape itself IS the contract;
  choose the presence ratchet when the substring's meaning IS
  the contract and the surrounding shape is free to evolve.
- [[cross-file-pin-regex-anchor-structure-not-annotation-token]] —
  adjacent pattern that pins multi-source-of-truth string
  agreement across files. The presence-ratchet is the
  single-file degenerate case.
- [[cli-overrides-deferred-key-notimplemented-trip-wire]] —
  runtime-layer sibling: a NotImplementedError trip-wire fires
  when the deferred code path is exercised. Both patterns
  catch silent regression of a deliberately-deferred or
  deliberately-committed decision.
- [[pre-1.0-version-bump-as-communication-contract]] — the
  KD-9 ratchet's motivating commitment. The ratchet IS the
  durability mechanism behind this learning.
- [[delivery-boundary-unit-commit-composition]] — presence
  ratchets are one of the boundary unit's signature
  deliverables. They land in the same commit as the prose
  they pin.
- [[public-surface-draft-discipline-source-audit]] — natural
  extension target: critical Public Surface DRAFT rows could
  acquire presence ratchets to pin their inclusion against
  silent removal during table rewrites.
- [[ce-review-cross-reviewer-agreement-shared-misreading-false-positive-amplifier]]
  — natural extension target: presence ratchets pinned to
  future-tense substrings ("will land in U3", "planned for U2")
  would catch a regression to present-tense forward-looking
  docstrings mechanically, before `ce:review` runs and 5
  reviewers all read them. The ratchet is the mechanical guard
  that prevents the shared-source misreading from arising in
  the first place.
