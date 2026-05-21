---
date: 2026-05-20
status: placeholder-stub
topic: protokit-ux-philosophy-revision
---

# Protokit UX Philosophy Revision — Post-D6d Delivery (Placeholder)

**Status: PLACEHOLDER STUB.** This document tracks four interlocked
pieces of work that surfaced during the D6d U3 escalation analysis
(2026-05-20). It is **not implementation-ready**; it stakes out scope
so the work doesn't get lost during D6d execution. Full brainstorm +
plan happen AFTER D6d ships (0.5.0).

## Why This Exists

The D6d U3 per-unit brainstorm + 2 doc-review passes + escalation
analysis surfaced a strategic question protokit had never explicitly
answered: **what is protokit's product stance toward proto2 schemas,
and what's the relationship between buf parity and protokit's UX
judgment when they conflict?**

The discovery: protokit's lint defaults have drifted into an
implicit anti-proto2 stance via buf-parity-mirroring, without an
explicit product decision that proto2 is second-class. The drift
emerged from three sources:

1. **`file/syntax-specified` (D6a)** — accidentally-strict because
   the descriptor layer can't distinguish explicit `syntax = "proto2";`
   from no-syntax-statement; fires on every proto2 file at ERROR in
   `recommended`+`default`. Documented as a buf-parity DIVERGENCE
   (buf fires only on the no-statement case) with the rationale "this
   is stricter than buf and intentionally nudges users toward proto3."
2. **`field/not-required` (D6d U3 proposal)** — would extend the
   implicit anti-proto2 pattern by adding a second ERROR-severity
   proto2-targeting rule in `recommended`+`default`. Compounded with
   #1 to create double-jeopardy (1+N errors per proto2 file).
3. **U3-KD-6 precedent (proposed in U3 brainstorm)** — codified the
   implicit stance into an explicit precedent: "when buf-parity
   defaults conflict with protokit-UX judgment, protokit defers to
   buf's defaults." Doc-review surfaced that this precedent cuts both
   ways and undermines protokit's differentiator narrative (the
   custom-annotation rules are exactly the case where protokit-UX
   should exceed buf's coverage).

The user's reframe (2026-05-20 conversation): *"We need to consider a
pivot from 'buf parity is the guiding light' to 'buf parity where it
makes sense but put user experience above all'. If proto2 is going
to continue to be maintained and people are going to elect to
continue using it, treating it as second-class is not a great
option."*

This stub captures the four follow-up pieces that fall out of that
pivot. None of them ship in D6d; they're a comprehensive post-D6d
effort.

## Four Interlocked Pieces

### Piece 1 — Principle Articulation ("UX above buf parity")

**Goal**: declare protokit's product stance explicitly in a durable
location so future agent sessions and contributors inherit it.

**Likely home**: `CLAUDE.md` (read by every agent session) + a
`README.md` "Philosophy" section. Possibly also a permanent
`docs/principles/protokit-ux-above-parity.md`.

**Sketch wording** (not final): "Protokit aims to be compatible with
buf at the rule-existence level (a buf BASIC user can adopt protokit
without surprises). Protokit makes independent UX decisions about
default severity, profile membership, and rule composition. When
buf-parity defaults conflict with protokit-UX judgment, protokit-UX
wins; the divergence is documented in the rule docstring and the
relevant CHANGELOG entry."

**Open questions for the eventual brainstorm**:
- Does this principle apply ONLY to lint, or to the entire protokit
  surface (differ, descriptors, formatters)?
- What's the buf-comparison-table positioning post-pivot? "Compatible
  with buf BASIC at rule-existence level; opinionated defaults"?
- How does this affect future `--rule-pack=buf` or `--profile buf-
  basic` pseudo-profiles? Is there value in a literal "buf
  compatibility" mode that uses buf's defaults exactly?

### Piece 2 — `file/syntax-specified` Retroactive Treatment

**Goal**: bring the existing `file/syntax-specified` rule into
consistency with the new principle.

**Three remediation options** (decision deferred to the full
brainstorm):
1. **Demote to WARNING in `recommended`** (keep ERROR in `default`).
   Soft change; proto2 users in CI see ERROR convert to WARNING.
2. **Remove from `recommended` entirely** (keep in `default` + opt-in
   via `[severities]`). Stronger statement of "proto2 is supported."
3. **Fix the descriptor-layer limitation** by source-parsing the
   `.proto` file to distinguish explicit-proto2 from no-statement.
   Matches buf precisely; biggest engineering surface (introduces a
   `.proto` parser dependency or a minimal in-tree parser).

**Trade-off**: option 3 has the cleanest end-state but the largest
engineering surface (and may warrant being its own delivery — D6e+
or D7). Options 1/2 are quick wins but leave the descriptor-layer
limitation in place.

**Carry-forward constraint**: whatever option lands, the
`TestBuiltinPacksDocstringRatchet` test at
`test_builtin_packs.py:144-170` pins substrings about
`file/syntax-specified` behavior; updates must be atomic with the
behavior change.

### Piece 3 — Proto2-Aware Profile Design

**Goal**: ship a `proto2-friendly` (or similarly-named)
`BUILTIN_PROFILE` that gives intentional-proto2 users a first-class
supported configuration.

**Sketch shape**:
```python
"proto2-friendly": LintProfile(
    name="proto2-friendly",
    rule_ids=recommended.rule_ids - {
        "file/syntax-specified",
        # plus future proto2-targeting rules as they ship
    },
)
```

~50 LOC: one `BUILTIN_PROFILES` entry + 2-rule exclusion list (more
if Piece 4's audit surfaces additional proto2-hostile rules).

**Open questions**:
- Naming: `proto2-friendly`? `proto2-supported`? `intentional-
  proto2`? Naming signals user-perception of the profile.
- Profile alias: should there be a `proto3-only` alias for users who
  want the opposite (explicitly fail on any proto2)? Or is
  `recommended` already that profile post-pivot?
- Does the proto2-friendly profile inherit from `recommended` or from
  `default`?
- What gets the rule_id set: a hardcoded list or a profile-level
  predicate?

### Piece 4 — Existing Rules Audit

**Goal**: audit all currently-shipping rules under the new principle
to identify other accidentally-strict-because-buf-parity patterns.

**Initial candidates worth examining** (not exhaustive):
- `enum/first-value-zero` — currently mirrors buf (fires on proto2
  enums too). Is that the right UX call given proto2 enums don't
  require zero as first value?
- `imports/no-public`, `imports/no-weak` — proto2-only features;
  defaults match buf. Are they the right defaults under the new
  principle?
- `naming/snake-case-fields` — syntax-agnostic; probably fine.
- `package_same/*` family — syntax-agnostic; probably fine.

**Output**: per-rule audit table (rule, current default, buf
default, UX assessment, recommended action) + a remediation PR per
rule that's misaligned.

## Sequencing With D6e+

`PACKAGE_NO_IMPORT_CYCLE` and `FIELD_NOT_REQUIRED` are both deferred
to D6e+. The philosophy-revision work above ALSO sits in the D6e+
window. Possible sequencings:

- **Option A**: philosophy revision FIRST (its own delivery, e.g.,
  D6e), then `PACKAGE_NO_IMPORT_CYCLE` (D6f) + `FIELD_NOT_REQUIRED`
  bundled with engine walker (D6g) under the new principle.
- **Option B**: bundle philosophy revision INTO the
  `FIELD_NOT_REQUIRED` delivery (the rule's defaults are decided
  under the new principle as part of its first ship).
- **Option C**: defer philosophy revision indefinitely and ship
  remaining buf-parity rules under the current implicit defaults
  (status quo continues).

Recommend Option A — comprehensive principle work deserves its own
window rather than being bundled with a specific rule's delivery.
Decision deferred to the eventual brainstorm.

## Triggering Conditions

The philosophy revision SHOULD start when:
- D6d 0.5.0 has shipped + been in production for ≥2 weeks (let the
  option-aware delivery stand on its own; gather any adoption signal).
- AT LEAST ONE OF:
  - User-visible report of "buf-parity-driven defaults are wrong for
    my workflow" (Piece 1 + Piece 4 priority signal).
  - Decision to ship `PACKAGE_NO_IMPORT_CYCLE` or `FIELD_NOT_REQUIRED`
    is imminent (these need the principle decided first).
  - 4+ weeks have passed since 0.5.0 ship with no urgent priorities
    competing for the window.

## Out of Scope for This Stub

- Concrete decisions on any of the four pieces (those are the WORK
  this stub stakes out, not the OUTPUT of this stub).
- A timeline. The triggering conditions above are loose; the
  scheduling is the user's call.
- Implementation details, rule body changes, test infrastructure
  changes.

## Next Step

When triggered, invoke `/ce:brainstorm protokit-ux-philosophy-revision`
against this placeholder. The brainstorm should:
1. Pin the principle wording (Piece 1)
2. Pick a remediation option for `file/syntax-specified` (Piece 2)
3. Sketch the proto2-aware profile (Piece 3)
4. Scope the existing-rules audit (Piece 4)
5. Decide sequencing (A/B/C above)
6. Produce a per-piece plan via `/ce:plan`

This stub stays in `docs/brainstorms/` until the full brainstorm
supersedes it.
