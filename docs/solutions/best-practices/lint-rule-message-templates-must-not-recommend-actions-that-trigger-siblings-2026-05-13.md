---
title: "Lint rule message_template remediation advice must not trigger sibling rules active in the same profile"
date: 2026-05-13
category: best-practices
module: protokit.schema.lint.rules
problem_type: best_practice
component: tooling
severity: high
applies_when:
  - "Writing or reviewing a lint rule's user-facing message_template"
  - "Adding a new rule to a profile that already contains rules with overlapping proto-semantic territory"
  - "Designing remediation advice for any rule-based check system (lint, eslint, validation, schema-guard) with shared profile/scope membership"
tags:
  - lint-rules
  - message-template
  - rule-design
  - profile-membership
  - cross-rule
  - user-experience
  - remediation-advice
  - buf-parity
  - protokit-lint
---

# Lint rule message_template remediation advice must not trigger sibling rules active in the same profile

## Context

In a multi-rule lint system where rules ship together in profiles
(`recommended`, `default`, `strict`, ...), each rule's
`message_template` typically tells the user how to remediate the
violation it just reported. If that remediation advice would itself
trigger another rule active in the same profile, the user is trapped:
following the advice produces a *new* finding instead of a clean run.
The user has no proto-semantic escape.

D6a U5 shipped `imports/unused` with exactly this trap. The original
message_template (feature commit `16a39c3`):

> "File imports `'foo.proto'` but does not reference any of its
> types — drop the import or mark it `public`/`weak` if the
> re-export is intentional"

But `imports/no-public` and `imports/no-weak` are co-resident in the
same `recommended` and `default` profiles, and they fire on every
`import public "...";` / `import weak "...";`. The user's options
after following the advice:

```
$ protokit lint  # imports/unused fires
warning[imports/unused]: File imports 'foo.proto' but does not
reference any of its types — drop the import or mark it `public`/`weak`
if the re-export is intentional

$ # user marks it public per the advice
$ protokit lint  # imports/no-public NOW fires
error[imports/no-public]: File imports 'foo.proto' as `public`;
public imports create transitive re-export coupling and are
discouraged
```

The user reads the original message and concludes the tool is
giving them a real choice. They are not. The remediation creates a
new finding from a sibling rule with no further escape.

The finding was caught during D6a U5 ce:review as ADV-U5-04
(adversarial reviewer, confidence 0.95), classified P1, and
resolved in fix commit `3bd23d7` by rewriting the message_template
to name only safe remediations + flagging the known D6a
out-of-scope false-positive cases (custom options, proto2
extensions tracked for D6b).

(Session history confirmed this is a net-new design concern in the
protokit-lint codebase — no prior session, brainstorm, or plan
review surfaced cross-rule message contradictions for any rule
family. The D6a brainstorm defined the three imports rules as peers
in the same profile without anticipating the trap. The convention
is being established prospectively at U5; future rule additions
should apply it from the start.)

## Guidance

**Audit every suggested remediation in a new rule's message_template
against the set of rules active in the same shipping profile.** The
test: "if a user follows this advice and re-runs the lint, will any
sibling rule fire on the result?"

The audit is mechanical:

1. List every action the message recommends (e.g., for
   `imports/unused`: "drop the import", "mark public", "mark weak").
2. For each action, ask: "what does this proto file look like
   *after* the user does this?" (e.g., "the import goes from
   `import "foo.proto";` to `import public "foo.proto";`")
3. For each post-action state, grep the active profile's rule
   check functions to see whether any of them would fire on the
   new state. The `_lint_spec.profiles` tuple on each rule
   declares the profile membership; rules sharing the user's
   profile are the contradiction surface.
4. If any sibling rule would fire, narrow the message to
   remediations that don't trigger sibling rules. If no safe
   remediation exists for some proto-semantic reason, the rule
   has a documented false-positive boundary that belongs in the
   docstring AND should be flagged briefly in the message_template
   itself so users understand why they can't easily fix it.

Forbidden recommendations for `imports/unused` in `recommended` /
`default`:

- "mark it `public`" — triggers `imports/no-public`
- "mark it `weak`" — triggers `imports/no-weak`

Safe recommendations:

- "drop the import" — no sibling rule fires on a missing import
- "this is a known false-positive case (link to docstring)" — the
  message acknowledges the boundary instead of suggesting a
  cascade-triggering remediation

The corrected D6a U5 message_template (fix commit `3bd23d7`):

```python
message_template=(
    "File imports {imported!r} but does not reference any of "
    "its message or enum types — drop the import if it is "
    "truly unused; known false positives for imports used "
    "only via custom options or proto2 extensions are tracked "
    "for D6b"
),
```

The new message names only "drop the import" as the safe
remediation and explicitly tells users about the two known
false-positive cases (custom options, proto2 extensions) so users
hitting them know the lint result is a documented gap rather than
their actual code being wrong.

**Apply the audit at rule-implementation time, not at post-ship
review time.** The U5 catch was lucky — adversarial review surfaced
it before users would have. The discipline is cheap when you have
the rule's message_template open in your editor and the sibling
rules' check functions in the same module. It is expensive when
you've shipped, users have hit it, and the fix requires a
behavioral CHANGELOG note.

## Why This Matters

**User trust in a lint tool depends on remediation paths being
actionable.** A contradiction — "the tool tells me to do X, then
complains when I do X" — destroys confidence in both the tool's
correctness and its operator's judgment. The user concludes either
(a) the tool's rules are not coherent as a set, or (b) the user
doesn't understand the tool well enough to trust its advice. Both
conclusions are worse than the original finding the rule was trying
to surface.

**The failure is silent under normal review.** The rule's unit
tests pass: `_run_single(..., "imports/unused", imports_pack)` only
loads the one rule and the assertion checks the finding's params,
not what would happen if the user followed the advice. The rule's
integration test asserts the rule fires, not whether the advice it
gives is internally consistent with the rest of the pack. Catching
the trap requires reading the message_template against the *other*
rules' check functions — which is exactly what an adversarial
reviewer does and what unit tests by design do not.

**Automated fixers amplify the breakage.** A fixer that reads
`message_template` to produce a patch would apply the bad advice,
re-lint, produce a new finding from the sibling rule, and either
loop forever or report a "fix failed" without identifying why. The
fix-and-lint cycle becomes irrecoverable without human
intervention.

**The constraint shapes rule API surface.** Rules that cover
overlapping proto-semantic territory need explicit coordination at
the message level. `imports/no-public` and `imports/no-weak` own
"public and weak imports are discouraged"; `imports/unused` must
respect that ownership when framing its own remediation. Without
this discipline, every rule's author writes remediation advice in
isolation, and the cross-rule contract drifts whenever a new rule
is added.

## When to Apply

- **At write time** for every new rule's `message_template`. Run
  the audit before the PR is even opened.
- **At review time** during ce:review (adversarial reviewer is
  well-positioned to surface this — D6a U5 caught it via
  adversarial confidence 0.95 / P1). Project-standards reviewer
  is the second-line catch.
- **When adding a new rule to an existing profile** — also audit
  the messages of already-shipped rules to check whether their
  recommended remediations would trigger the new rule. The new
  rule might invalidate the safety of existing messages.
- **When designing future option-aware rules** scheduled for D6b
  (e.g., `deprecated-must-have-replacement-comment`,
  `recursive-options-discouraged`) — verify the remediation
  patterns don't collide with sibling option-checking rules in
  the same profile.

Skip the discipline when:

- The rule ships in a profile with no sibling rules (e.g., a
  user-supplied `--rule-pack` that is the only loaded pack).
  Adding more sibling rules later requires re-running the audit.
- The rule has no message_template (purely structural rules
  that emit zero-param findings). Edge case; most rules have
  some advice.

## Examples

**Before (D6a U5 feature commit `16a39c3`, `imports.py:121-125`)
— the trapped message:**

```python
@lint_rule(
    rule_id="imports/unused",
    ...
    message_template=(
        "File imports {imported!r} but does not reference any of its "
        "types — drop the import or mark it ``public``/``weak`` if "
        "the re-export is intentional"
    ),
    ...
)
```

This message recommends `import public` / `import weak` as valid
remediations. Both fire `imports/no-public` / `imports/no-weak` in
the same `recommended`+`default` profile.

**After (D6a U5 ce:review fix commit `3bd23d7`,
`imports.py:121-128`) — safe remediations only:**

```python
@lint_rule(
    rule_id="imports/unused",
    ...
    message_template=(
        "File imports {imported!r} but does not reference any of "
        "its message or enum types — drop the import if it is "
        "truly unused; known false positives for imports used "
        "only via custom options or proto2 extensions are tracked "
        "for D6b"
    ),
    ...
)
```

The fix drops the `public`/`weak` remediation entirely, names only
"drop the import" as the safe action, and tells users about the
D6a out-of-scope false-positive boundary so users with genuinely
needed imports understand why the rule fires and where the fix
lives.

**The cascade that the before-template would have caused
(adversarial reviewer's failure scenario):**

```
$ cat bar.proto
syntax = "proto3";
import "google/api/annotations.proto";  // used only via option (google.api.http)
message Bar { string x = 1; }

$ protokit lint
# imports/unused fires (rule doesn't walk options yet — D6b):
"File imports 'google/api/annotations.proto' but does not reference
 any of its types — drop the import or mark it `public`/`weak` if
 the re-export is intentional"

$ # user follows advice, marks it public
$ cat bar.proto
syntax = "proto3";
import public "google/api/annotations.proto";
message Bar { string x = 1; }

$ protokit lint
# imports/no-public NOW fires:
"File imports 'google/api/annotations.proto' as `public`; public
 imports create transitive re-export coupling and are discouraged"

# User has no proto-semantic escape. The actual fix is to wait for
# D6b's option-aware walker; the rule's original advice was
# misleading the user toward a sibling-rule trap.
```

The corrected message_template eliminates the cascade by not
recommending `public`/`weak` at all and instead documenting the
D6b deferral.

## Related

- [[copytoproto-round-trip-for-proto-form-only-descriptor-fields-2026-05-13]] — sibling D6a U5 learning covering the data-access pattern (`ctx.file.CopyToProto(fdp)`) the imports rules use to read `public_dependency` / `weak_dependency`. Together with this doc, they capture both the data-access pattern and the user-facing contract for the imports pack.
- [[proto3-optional-synthetic-oneof-false-positive-lint-rule-2026-05-12]] — different lint-rule UX failure mode: that doc covers a rule that fires on synthetic descriptors (descriptor-scope confusion); this doc covers remediation advice that triggers sibling rules (profile-scope contradiction). The two failure modes are distinct but share the domain — they belong on a future "lint rule design pitfalls" index page.
- [[rule-pack-extension-ssot-rule-ids-and-test-class-naming-2026-05-12]] — rule-pack extension checklist. Adding "audit message_template remediation advice against sibling rules in the same profile" to that checklist would surface this discipline at PR-author time rather than at ce:review time.
- [[cross-format-enum-string-parity-2026-05-08]] — adjacent cross-X consistency discipline (consistent enum strings across sibling output formats). Same logical shape (X and Y must be mutually consistent, discovered through an audit) at a different layer (serialization vs. remediation advice).
- [[audit-wire-format-before-claiming-sibling-parity-2026-05-03]] — buf-parity audit discipline. A cross-rule message audit is a special case of the broader "verify the claim against the actual behavior" discipline that doc establishes. The cross-rule audit verifies "the remediation advice claim against the sibling rules' check functions."
