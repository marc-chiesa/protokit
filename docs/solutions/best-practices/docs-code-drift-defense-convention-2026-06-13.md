---
title: "Drift-defense conventions for docs/solutions/: per-occurrence claim-currency markers and reference-triage"
date: 2026-06-13
category: best-practices
module: docs/solutions drift defense
problem_type: best_practice
component: documentation
related_components:
  - tooling
  - testing_framework
  - development_workflow
severity: medium
applies_when:
  - "Writing or editing a docs/solutions/ learning that makes a behavioral claim about a moving target (a pinned upstream version, an external tool's behavior, a download URL)"
  - "The reference-drift CI job (scripts/check_docs_test_refs.py / the docs-refs job) surfaces a docs/solutions/ line that names a renamed or removed test path"
  - "Auditing the docs/solutions/ corpus for claim currency, or deciding how to mark a single new claim"
  - "A version string in a learning is also asserted verbatim by a named presence-ratchet or membership test (a drift anchor)"
tags:
  - drift-defense
  - claim-currency
  - current-state-vs-provenance
  - per-occurrence
  - reference-triage
  - presence-ratchet
  - ratchet-anchored-provenance
  - docs-solutions-discipline
  - moving-target
---

# Drift-defense conventions for docs/solutions/: per-occurrence claim-currency markers and reference-triage

## Context

`docs/solutions/` learnings are read and acted on — by agents via grep
retrieval, by humans skimming the rendered prose — as if their framing is
correct *now*. Two failure modes let that trust go bad silently:

- **Reference drift** — a learning names a test path (`tests/foo.py`) that has
  since been renamed or removed. Cheap, and mechanically detectable: the
  `docs-refs` CI job (`scripts/check_docs_test_refs.py`) surfaces every
  `docs/solutions/` line that names a moved test's old path, for human triage
  (see [[behavior-preserving-test-move-breaks-path-coupling-2026-06-13]] for the
  path-coupling failure that floor targets).

- **Claim drift** — a learning states a *behavior* tied to a moving target
  ("buf v1.69.0 does NOT cross-fire across module boundaries"); the target moves
  and the prose still scans cleanly while the claim is wrong now. No path check
  sees this; the durable cost is trust.

This learning is the convention both defenses share: how to **mark** a claim so
its currency is legible at the point of retrieval, and how to **triage** a
surfaced reference hit. It is the per-occurrence discipline of
[[pinned-version-bump-reference-classification-2026-06-13]] (`#34`), generalized
from "bumping one pin" to "every behavioral claim in the corpus."

## Guidance

Two rules, each load-bearing. Both are *per occurrence* — classify by what a
sentence asserts, not by which doc it lives in or which version it names.

### Rule 1 — the claim-currency marker

**Mark every non-executable behavioral claim about a moving target current-state or provenance, per occurrence, co-located inline with the claim.**

A claim is *executable* — and needs **no marker** — when a live test or CI job
re-asserts that exact proposition on every run (a fixture the parity suite
recomputes, an assertion a test makes). The marker exists for the prose claims
*nothing re-runs*: the sentences a reader simply trusts.

Two marker kinds, plus one sub-case that is the dominant trap:

| Kind | When | Inline form (the lead label is the greppable handle) |
|------|------|------------------------------------------------------|
| **current-state** | The claim is true *now* and a *named live mechanism* re-verifies it against the *current* target. No past version is baked in as load-bearing. | `(current-state — re-verified by the CI parity job against the current pin)` |
| **provenance** | The version records *when* a behavior was observed. The string is load-bearing as a dated record; current behavior is re-asserted elsewhere or simply not claimed-current. | `(provenance — verified against buf v1.69.0; current behavior re-asserted by the CI parity job)` |
| **ratchet-anchored provenance** *(sub-case of provenance — never current-state)* | The version-bearing string is *also* asserted verbatim by a named test as a deliberate drift anchor (kept stale so an upstream change forces a conscious update). | `(provenance — buf v1.69.0; ratchet anchor pinned by tests/schema/lint/test_builtin_packs.py — do not bump)` |

**Decision procedure, per occurrence:**

1. Does a live test/job re-assert this exact proposition every run? → **no marker** (it is executable, not prose).
2. Else, does a *named* live mechanism re-verify the claim against the *current* target, with no past version baked in as load-bearing? → **current-state**; name the mechanism.
3. Else, the version records *when* a behavior was observed → **provenance**; name the version.
4. Is that provenance string *also* asserted verbatim by a named test as a drift anchor? → **ratchet-anchored provenance**; name the test, say "do not bump." **Never mark it current-state** — a live re-verifier would silently track the target while the ratchet demands the string stay frozen; marking it current-state and then bumping breaks the ratchet test and disarms the drift detector (`#34` category 6).

**Per-occurrence keying (the heart of it).** The *same proposition* can be
current-state at one site and provenance at another. "protokit covers 26 of 26
buf BASIC rules" is **current-state** in a present-tense README parity claim (a
live job re-verifies it against the current pin, no test pins the README string)
and **ratchet-anchored provenance** in the `BUILTIN_PACKS` docstring numerator (a
named test pins that exact string stale). Same words, opposite marker, because
their *sentences assert different things*. This mirrors `#34`'s per-occurrence
rule exactly — never classify a claim by its substring alone.

**Co-location (why inline, not frontmatter or an HTML comment).** The marker
rides on, or immediately adjacent to, the claim's own line. A frontmatter-only
marker is invisible to an agent that greps and pulls a single mid-doc line into
context; an HTML comment is invisible to a human reading the rendered page. Both
audiences act on stale framing, so the marker must be visible to both — plain
inline prose, led by the `current-state` / `provenance` label.

### Rule 2 — reference-triage

**A navigational pointer to a moved test path → update it; a historical or illustrative mention → leave it.**

When the `docs-refs` job surfaces a `docs/solutions/` line naming a renamed or
removed test's old path, triage that hit per occurrence:

- **Navigational pointer** — the line points a *current* reader at that test
  ("the gate lives at `tests/foo.py`", "see `tests/foo.py` for the pattern").
  The old path is now wrong → **update** it to the new path.
- **Historical / illustrative mention** — the line records a point in time
  ("when #29 shipped, the file was `tests/foo.py`") or uses the path as an
  example of the failure shape. The old path is load-bearing as a dated record
  → **leave** it.

No standing exemption list: triage *every* hit per change (the check is
non-blocking and never auto-edits — it surfaces, the human decides). This is the
prose-reference analogue of `#34`'s current-state-vs-historical split, and of
the "class 5 — refresh, don't gate" tracked-prose rule in
[[behavior-preserving-test-move-breaks-path-coupling-2026-06-13]].

## Why This Matters

**The marker makes currency legible at the point of retrieval.** An agent rarely
reads a learning top-to-bottom; it greps a phrase and pulls the matching line.
If that line says "buf v1.69.0 does NOT cross-fire" with no marker, the agent
cannot tell whether that is true now or was true once. The co-located marker
answers that question in the same glance — `provenance` says "dated record,
verify against current"; `current-state` says "a live job keeps this honest."

**The ratchet-anchor sub-case is where good intentions turn CI red.** The
instinct, marking a claim "current-state" so it reads as fresh, is exactly wrong
for a version-bearing numerator that a presence-ratchet pins stale on purpose
(see [[presence-ratchet-test-pattern-for-prose-substrings-2026-05-14]]). The
ratchet *wants* the string frozen so a new upstream rule forces a deliberate
update; a "current-state" marker invites a bump that breaks the ratchet test and
silently disarms the drift detector it exists to be. Classify the numerator as
provenance, name its pinning test, and say "do not bump."

**Reference-triage keeps the floor trustworthy.** A check that auto-rewrote
every surfaced path, or that blocked the build, would false-positive on the
historical mentions that are *supposed* to name an old path — and a check that
cries wolf gets ignored. Non-blocking surfacing plus per-occurrence human triage
is the design that keeps the signal worth reading (the reason a continuous
"all paths must resolve" gate was rejected upstream).

## When to Apply

- **Writing a new learning** that asserts a behavior tied to a moving target:
  add the marker in the same edit, on the claim's line.
- **Editing an existing learning** near such a claim: if it is unmarked, mark it
  while you are there.
- **The `docs-refs` job flags your branch:** apply Rule 2 to each hit before
  merging — update navigational pointers, leave historical mentions.
- **Bumping a pin** (`#34`'s scenario): the marker you wrote tells the bumper
  which occurrences are current-state (bump) and which are provenance / ratchet
  anchors (leave) — the convention and the bump-time decision reinforce.

**Skip the marker** when the claim is executable (a live test re-asserts it) or
when it names no moving target at all (a structural invariant, a code shape a
type checker or test already pins). The marker is for *prose nothing re-runs*.

## Examples

**1. current-state (no baked-in version).**
A learning states: "protokit's lint findings are byte-equivalent to buf's for the
BASIC rules `(current-state — re-verified by the CI parity job against the
current pin)`." There is no version string to go stale; the live parity job
re-asserts the claim against whatever the pin currently is. This is the
*corrected* current-state example: it marks a claim a live job keeps honest, not
a version-bearing numerator (contrast example 3).

**2. provenance (dated empirical observation).**
A learning states: "buf v1.69.0 does NOT cross-fire across module boundaries
`(provenance — verified against buf v1.69.0; current behavior re-asserted by the
CI parity job)`." The `v1.69.0` is load-bearing — it records the version the
behavior was *observed against*. Bumping it would be revisionist; the live job,
not the prose, is the current-behavior authority (`#34` category 5).

**3. ratchet-anchored provenance (the trap — never current-state).**
The `BUILTIN_PACKS` docstring numerator, "26 of 26 buf v1.69.0 BASIC rules," is
asserted verbatim by `tests/schema/lint/test_builtin_packs.py`, which keeps it
stale on purpose so a *new* buf BASIC rule forces a conscious update. Mark it
`(provenance — buf v1.69.0; ratchet anchor pinned by
tests/schema/lint/test_builtin_packs.py — do not bump)`. The *same numerator* in
the present-tense README parity claim is **current-state** (a live job
re-verifies it; no test pins the README string) — same proposition, opposite
marker, per occurrence (`#34` categories 3 vs 6).

**4. reference-triage (Rule 2 in action).**
A branch renames `tests/foo.py` to `tests/meta/foo.py`; the `docs-refs` job
surfaces three `docs/solutions/` lines naming `tests/foo.py`. Two are
navigational ("the gate lives at `tests/foo.py`") → update both to the new path.
One is historical ("when #29 shipped the file was `tests/foo.py`") → leave it.
The build is not blocked; the job reported, the author decided.

## Related

- [[pinned-version-bump-reference-classification-2026-06-13]] — `#34`, the
  per-occurrence currency model this convention generalizes: bumping a pin,
  current-state claims bump while historical / provenance / ratchet-anchor
  statements stay. The marker is the durable, retrieval-time form of that
  classification.
- [[behavior-preserving-test-move-breaks-path-coupling-2026-06-13]] — the
  path-coupling failure the reference floor targets; its "class 5 — refresh,
  don't gate" tracked-prose rule is Rule 2's source.
- [[presence-ratchet-test-pattern-for-prose-substrings-2026-05-14]] — why the
  ratchet-anchored-provenance sub-case exists and must never be marked
  current-state; also the mechanism a presence-ratchet uses to pin *this
  convention's* load-bearing clauses against silent reversion.
- [[stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12]] — the
  temporal-staleness sibling (present/future tense → rewrite; past tense →
  leave); the marker convention is the currency-identifier analogue of that same
  default-to-leave-to-avoid-revisionism shape.
