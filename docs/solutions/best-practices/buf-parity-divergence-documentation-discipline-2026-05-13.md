---
title: "Document buf-parity divergences at four sites when descriptor limits prevent exact match"
date: 2026-05-13
category: best-practices
module: protokit.schema.lint.rules
problem_type: best_practice
component: tooling
severity: medium
applies_when:
  - "Implementing a rule whose source_spec claims buf parity but the protobuf descriptor layer collapses two distinct source states into one value"
  - "Any rule where fdp.syntax, fdp.options, or other descriptor fields are ambiguous between two valid proto source constructs"
  - "Deciding whether to add a structured parity_note field to LintRuleSpec when a single divergence is documented"
tags:
  - buf-parity
  - source-spec
  - file-descriptor-proto
  - syntax-specified
  - documentation-discipline
  - lint-rules
  - parity-note
  - sibling-parity
---

# Document buf-parity divergences at four sites when descriptor limits prevent exact match

## Context

A rule's `source_spec="buf:<RULE_ID>"` field is the project's
machine-readable parity claim — it tells agents, contributors, and
users which buf rule this rule targets. Most protokit-lint rules can
match buf exactly. Some can't — typically because the descriptor
API strips information that buf reads from .proto source directly.

D6a Unit 6's `file/syntax-specified` is the first protokit rule with
such a divergence. Buf's `SYNTAX_SPECIFIED` rule is source-aware: it
parses the .proto file directly to detect the literal
`syntax = "...";` declaration. Protokit operates on descriptor
output, where the protobuf compiler emits `fdp.syntax == ""` for
BOTH "no syntax statement at all" AND explicit
`syntax = "proto2";` files — the descriptor field is only set for
non-default syntax (`"proto3"`, `"editions"`). The two source cases
are indistinguishable at the descriptor level. Protokit therefore
fires on both: stricter than buf, intentionally nudging users
toward proto3.

(Session history: the divergence was a U6 implementation discovery,
not anticipated in the D6a brainstorm or plan. A descriptor probe
ran at the start of U6 implementation confirmed `fdp.syntax == ""`
for both cases; the divergence was documented inline at
implementation time across four sites. The "should we add a
structured `LintRuleSpec.parity_note` field" question was raised
during U6 ce:review by the api-contract reviewer and answered
"defer until 2nd divergence" — also a U6 first.)

This learning codifies the four-site documentation discipline so
future rules with unavoidable divergences follow the same pattern.

## Guidance

**Four-site documentation protocol** — when a rule's
`source_spec="buf:<ID>"` cannot perfectly match buf due to a
descriptor-level limitation (or other unavoidable constraint),
document the divergence at every one of these sites:

**1. Module docstring** (`src/protokit/schema/lint/rules/<pack>.py`,
top of file). Name the divergence, explain *why* it is unavoidable
(descriptor limitation, compiler behavior, missing source info),
state the protokit posture (stricter, looser, or lateral). This is
the first thing a contributor opening the file sees:

```python
"""``file`` rule pack — file-level structural rules.

- ``file/syntax-specified`` (buf:SYNTAX_SPECIFIED) — fires when
  the file's resolved syntax is not ``"proto3"``. **Known buf-
  parity divergence**: buf's own SYNTAX_SPECIFIED rule fires only
  when the literal ``syntax = "...";`` declaration is missing
  from the .proto source. Protokit's rule operates on descriptor
  output, where the protobuf compiler emits ``fdp.syntax == ""``
  for BOTH "no syntax statement at all" AND ``syntax = "proto2";``
  files — the descriptor cannot distinguish the two cases.
  Protokit therefore fires on every proto2 file regardless of
  whether the syntax statement was explicit.
"""
```

**2. Rule function docstring** (the `@lint_rule`-decorated function).
Same content, more concise. Explicit about which branch protokit
covers vs. buf:

```python
def check_syntax_specified(ctx: FileLintContext) -> None:
    """Fire when the file's resolved syntax is not proto3 or editions.

    The descriptor pool does not preserve enough source-level
    information to distinguish "no syntax statement at all" from
    explicit ``syntax = "proto2";`` — the protobuf compiler emits
    ``fdp.syntax == ""`` for both cases.

    Buf's SYNTAX_SPECIFIED rule fires only on the no-statement
    case (it parses .proto source directly). Protokit can only
    work from descriptor output, so the rule fires on both
    no-syntax and explicit-proto2 cases. This is stricter than
    buf and intentionally nudges users toward proto3; users with
    intentional proto2 codebases can demote the rule via
    ``[tool.protokit.lint.severities]``.
    """
```

**3. `message_template` on `@lint_rule`** (user-facing in every
finding). A user who hits a finding that differs from `buf lint` on
the same file needs to understand why. Include a remediation path
for users with intentional non-proto3 codebases:

```python
message_template=(
    "File {file!r} does not declare ``syntax = \"proto3\";`` "
    "(or ``edition = \"...\";``); protokit treats proto2 "
    "(whether explicit or implicit) as a parity violation — "
    "declare proto3 explicitly or demote this rule via "
    "[tool.protokit.lint.severities] if proto2 is intentional"
),
```

**4. Test method docstrings** in `tests/schema/lint/rules/test_<pack>.py`.
Write *separate* tests for each branch of the divergence — the
under-buf branch (what buf would catch) and the over-buf branch
(what protokit catches additionally). Each test's docstring
explains the branch and why the divergence is unavoidable:

```python
def test_sad_path_explicit_proto2_fires(self, tmp_path: Path) -> None:
    """Explicit ``syntax = "proto2";`` fires.

    This diverges from buf's SYNTAX_SPECIFIED behavior (which
    would not fire because the syntax IS specified). The
    divergence is unavoidable: the protobuf compiler emits
    ``fdp.syntax == ""`` for explicit proto2 files (the field
    is only set for non-default syntax), so the descriptor
    cannot distinguish "explicit proto2" from "no syntax
    statement". Protokit chooses the stricter posture —
    nudging toward proto3 — and accepts the divergence as
    documented in the rule docstring.
    """
    ...

def test_sad_path_no_syntax_statement_fires(self, tmp_path: Path) -> None:
    """No syntax statement (implicit proto2) fires.

    This is the case buf's SYNTAX_SPECIFIED was designed to
    catch. Protokit's rule matches buf on this branch.
    """
    ...
```

**Structured-field deferral** — do NOT add a
`LintRuleSpec.parity_note: str` field, a
`LintRuleSpec.divergence_kind: Literal[...]` enum, or any other
structured field to formalize the divergence pattern until a
*second* rule has a documented divergence. One instance is a
specimen; two instances are a pattern. Adding schema infrastructure
for one specimen locks in a field shape before the broader pattern
is understood, and the four-site prose discipline is sufficient
for one instance.

When a second divergence lands (D6b is the likely candidate via
option-aware rules), revisit the structured-field decision. At
that point: enumerate the two divergences, identify the common
fields they share (e.g., "buf-rule-id," "divergence-type,"
"protokit-stricter-or-looser"), and design the field shape from
the pattern rather than from a single instance.

## Why This Matters

The `source_spec` field is the project's machine-readable parity
claim. An agent comparing protokit vs buf output on the same
fixture reads `source_spec` and assumes equivalence. Without
documentation discipline, the divergence is invisible — the
agent's comparison will be wrong and there's no signal in the
code pointing to why.

With four-site discipline:

- The divergence is **prose-discoverable** by anyone reading the
  module or rule docstring.
- The divergence is **user-visible** via the finding message —
  users don't have to cross-reference docs to understand the
  difference between `protokit lint` and `buf lint` output.
- The divergence is **CI-enforced** via the two-branch test
  structure — a future contributor who accidentally "fixes" the
  divergence (making the rule source-aware in a way that drops
  one of the branches) will break the corresponding test, and the
  test's docstring explains the intent.

The alternative — a single comment in the rule body — is fragile.
Comments don't surface in test failures, don't appear in
user-facing messages, and don't communicate to the module-level
reader. Four sites means the divergence is documented at every
plausible discovery point a contributor or user could reach it
from.

## When to Apply

**At rule-author time**, when the implementation realizes it cannot
match buf exactly:

1. Probe the descriptor API for the field buf would inspect.
2. If the field is missing, limited, or collapsed by the compiler,
   the divergence is unavoidable.
3. Apply four-site documentation *immediately* — not as a
   follow-up, not as a comment in a future ce:compound. The
   discipline is cheapest at implementation time when the
   constraint is fresh.
4. Defer the structured-field decision until a second rule has a
   divergence.

If the implementation IS source-aware (a future protokit rule
that reads .proto source directly via `SourceCodeInfo` or a
separate parse path), no divergence exists — no four-site
discipline needed.

**At ce:review time**, when reviewing a new rule:

- Check `source_spec` claims against the actual rule logic. If the
  rule's check function uses descriptor fields buf doesn't (e.g.,
  fires on `fdp.syntax`), audit for the parity gap.
- If the rule diverges from buf and the documentation is missing
  one or more of the four sites, flag as P2 and require the
  documentation before merge.

## Examples

`file/syntax-specified` (D6a U6, commits `5836802` + `3469523`) is
the canonical worked example. The rule:

- Diverges from buf because `fdp.syntax == ""` is ambiguous
  between no-syntax-statement and explicit proto2.
- Documents the divergence at four sites:
  1. **Module docstring** (`src/protokit/schema/lint/rules/file.py`
     lines 1-31).
  2. **Rule docstring** (`check_syntax_specified` body, ~30 lines
     including the editions carve-out).
  3. **`message_template`** (refined in U6 ce:review commit
     `3469523` to mention `edition = "...";` as also-clean).
  4. **Test method docstrings** (`test_sad_path_explicit_proto2_fires`
     pins the over-buf branch; `test_sad_path_no_syntax_statement_fires`
     pins the buf-parity branch; both docstrings explain the
     branch they cover).

The structured-field deferral is logged in commit `5a97b9e`'s
"Plan-deferred residual" section as advisory `AC2`: *"Adding a
machine-readable `LintRuleSpec.parity_note` field is a D6b
candidate when a 2nd divergence forces the question."* When D6b
adds option-aware rules (R6 + R6a + R6b deferred from D6a per J1
of the plan), the second divergence is likely — at that point,
the structured-field question becomes load-bearing and gets
designed from two instances rather than guessed from one.

## Related

- [[audit-wire-format-before-claiming-sibling-parity-2026-05-03]] — direct planning-time sibling. That doc establishes the discipline of auditing parity claims at plan-review time ("if divergences are found, document at every claim site; selective parity is more honest"). This doc is the implementation-time complement: once the divergence is discovered during implementation, the four-site protocol operationalizes the planning-time guidance. The two docs together cover the full arc — pre-implementation audit + post-implementation documentation.
- [[copytoproto-round-trip-for-proto-form-only-descriptor-fields-2026-05-13]] — covers the most common root cause that triggers this doc's protocol (descriptor API limitation forcing a workaround). When a CopyToProto workaround results in behavior diverging from buf, the four-site documentation protocol applies. The two docs together cover the full arc: detect the descriptor limitation → implement the CopyToProto workaround → document any resulting divergence.
- [[lint-rule-message-templates-must-not-recommend-actions-that-trigger-siblings-2026-05-13]] — both docs impose content obligations on `message_template`. That doc covers cross-rule remediation contradictions (one rule's suggested fix triggers another rule); this doc covers descriptor-limited divergences (the message must explain why protokit differs from buf). Both failure modes land in message_template content; the two disciplines compose.
- [[proto3-optional-synthetic-oneof-false-positive-lint-rule-2026-05-12]] — concrete D6a U3 specimen of a buf-parity divergence (rule fires on synthetic oneofs that buf skips natively via descriptor inspection). That doc establishes the buf-parity rationale; this doc generalizes the documentation protocol.
- [[parametrized-matrix-tests-inherit-schema-validators-2026-05-12]] — adjacent: this doc's "pin both branches with tests" requirement aligns with the matrix-test discipline of running validators on every parametrized cell. Both impose explicit-branch coverage as a CI-enforced invariant.
- [[upstream-rule-deprecation-skip-ordering-parity-harness-2026-05-13]] — sibling discipline for a different class of divergence. This doc covers **behavioral divergences** (both tools have the rule, they disagree on when it fires) — the four-site protocol + `_PARITY_EXCEPTIONS` map are the test-layer artifact. That doc covers **lifecycle divergences** (only one tool has the rule — buf deprecated upstream) — the `_BUF_DEPRECATED_RULES` registry + per-test skip is the test-layer artifact. Classification rule: does the rule still exist upstream? Yes → behavioral; no → lifecycle.
- [[cross-file-pin-regex-anchor-structure-not-annotation-token-2026-05-13]] — the drift-check test enforcing pin agreement across cli.py, ci.yml's tarball URL, and ci.yml's sha256.txt URL is the test-layer enforcement of the broader multi-site discipline this doc establishes. Both documents share the principle "multiple sites must stay in sync with a single underlying contract" — this doc covers rule-author documentation sites; the cross-ref doc covers regex anchors in test infrastructure.
- [[semantic-category-conflation-accepted-tradeoff-literal-widening-2026-05-13]] — structurally parallel deferral decision applied to a different schema surface. This doc defers a structured `parity_note` field on `LintRuleSpec` until a second divergence specimen justifies the schema infrastructure; that doc defers a Literal-widening on `LintRuntimeWarning.category` until a second emit site needs separate wire representation. Same "one specimen is not a design signal" principle applied to two independent schema-extension surfaces. The four-site protocol here and the three-site protocol there differ only in what counts as a site — both encode the discipline that schema design needs ≥2 instances before structure is locked in.
- [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]] — upstream complement: this doc covers what to do AFTER a divergence is discovered (four-site documentation + `_PARITY_EXCEPTIONS` entry). The D6b U6 doc covers the implementation-time GATE MECHANISM that surfaces the bug in the first place (committed buf NDJSON snapshots as the empirical oracle). The two docs together cover the full divergence-handling arc: parity gate fires → reviewer + author triage → if real divergence, apply four-site protocol; if fix-the-helper, no exception entry needed (the empirical gate's first hit at D6b U6 was the second case — helper bug, fixed, no `_PARITY_EXCEPTIONS` entry added).
