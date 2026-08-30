---
title: "Sibling blindness: a fix at one call site survives the review built to catch it while structural siblings stay broken"
date: 2026-08-30
last_updated: 2026-08-30
category: docs/solutions/best-practices
module: protokit.schema
problem_type: best_practice
component: tooling
severity: high
applies_when:
  - "A fix is applied at the call site where a bug was first reported, while other call sites independently construct or invoke the same broken logic (per-subcommand CLI wiring, per-branch dispatch, per-loop-iteration renderer calls)"
  - "The fix is later relocated to a shared single-owner function, but some callers reach that owner only through a code path the triggering bug report never exercised (e.g. an empty commit range that skips a per-commit loop body entirely)"
  - "Parity or coverage tests assert that multiple entry points share one boundary, but every test case happens to exercise the same value class, so the shared-boundary claim is never proven for the class that actually broke"
  - "A review pass is explicitly scoped to catch 'fix in one place, structurally identical case stays broken' and still misses an instance of exactly that pattern"
  - "Several structurally identical handler or renderer functions exist because each subcommand formats its own diagnostics or invokes its own instance of otherwise-shared logic"
root_cause: incomplete_implementation
related_components:
  - development_workflow
  - testing_framework
tags:
  - sibling-blindness
  - call-site-completeness
  - single-owner
  - fix-completeness
  - review-blind-spot
  - ci-gate
  - protokit-schema-cli
  - parity-test-coverage
---

# Sibling blindness: a fix lands at one call site while structurally identical siblings stay broken

## Context

**This is the ninth documented recurrence of a pattern this codebase named,
and wrote three prevention rules for, four months ago. That is the finding.**

The shape: a fix is applied at the call site the bug report happened to name,
and the structurally identical siblings — the other subcommand, the other
renderer, the public API path behind the CLI — are left open.

The corpus already tracks it under two coined names. `Symmetric surface`
([[formatter-systemexit-exit-code-bypass-2026-04-19]], which keeps a running
log of recurrences dated April 19 → May 7 → May 9 → May 11) and the
`spatial-scope-audit rule`
([[keyboardinterrupt-baseexception-bypass-rule-pack-load-2026-05-07]]:
"audit ALL I/O surfaces in the same function/module — not just the headline
parse call"). A third,
[[module-name-newline-injection-stderr-forge-2026-05-07]], states as its
architectural posture that every output boundary with a per-line contract must
sanitize every interpolated slot.

Then, in one release:

- The 0.15.1 change committed the pattern **three times** — including one
  instance that was a violation of that third doc's own rule, on a sibling CLI,
  3.5 months after it was written.
- **Instance 2 was introduced by the fix for instance 1.**
- Earlier, during PR #48's remediation, an adversarial review caught a map
  **value**-axis false-equality; that was fixed, verified, committed — and a
  *second* re-review caught the **key** axis, broken by the identical root
  cause.
- The 0.16.0 plan, whose Problem Frame names this pattern as protokit's
  "characteristic failure", committed it in its own unit definitions: one unit
  enumerated four CLI modules and omitted a registered fifth; another migrated
  four formatters and omitted a fifth; a third aimed its guard at call sites
  that do not contain the defect it claimed to close.

Every instance was caught by an **independent reviewer**. None by the author.
None by the test suite, which was green throughout (3392 → 3434 passing). One
was missed by a test class written *specifically* to catch this class of
defect, whose docstring quotes the pattern by name.

**So the gap is not awareness, and it is not documentation.** The project had
the name, three prevention rules, an audit finding, a plan that opened by
naming the pattern, and a test class titled after it. None of that located the
instances. A fourth prose writeup would not either.

What follows is therefore split deliberately: an **executable procedure**
(greps you run, a reachability question you ask, a mutation you apply at the
site), and an honest account of **what actually caught these** — iterative
independent falsification review — versus what did not. If you take one thing:
the control is a process you run, not a rule you know.

Two sibling learnings from the same release cover the specific defects used
below as illustrations; this one is about the meta-pattern and deliberately
does not re-explain their mechanics:

- [[empty-selector-parses-to-root-prefix-suppresses-every-finding-2026-08-30]]
  (V31 — the empty `--ignore` fail-open; instances 1 and 2)
- [[caught-rule-exception-must-participate-in-the-exit-verdict-2026-08-30]]
  (V33 — a swallowed rule exception that never reached the exit verdict)

Instance 3 (the stderr sanitizer applied to `check`/`ci` but not `history`/
`bisect`) is captured here and nowhere else — at release time it existed only
in the #52 commit message and the CHANGELOG.

The work landed in **#51** (the fix) and **#52** (the release cut, which
carried instance 3's fix), released as **0.15.1**.

> **Citation note.** Line numbers below are current-state as of 0.15.1 and will
> drift. Each is paired with a greppable anchor so the citation self-heals; if a
> line number no longer matches, run the anchor.

## Guidance

### 1. Distinguish "the owner is wrong" from "the owner is never reached"

These look identical in a bug report and need different fixes. Getting the
first one right is what makes the second one invisible.

**Shape A — the owner is wrong, or there is no owner.** The rule is restated at
each call site (or lives at one of them), so fixing one leaves the rest. The
fix is to establish a *single owner* and delete the per-caller restatements.

In instance 1, the first revision of the V31 guard sat at the CLI flag
boundary, in `_build_configured_checker`
(`src/protokit/schema/cli.py:594`, anchor `def _build_configured_checker`).
Every CLI route was covered. `SchemaChecker.ignore("")` and
`CompatibilityPolicy(ignore_paths=("",))` — both public API, neither routed
through the CLI — stayed broken. The reviewer reproduced it: a pair that
reports 1 finding reported 0.

The fix moved the rule to the single owner,
`SchemaChecker.ignore` (`src/protokit/schema/checker.py:313`, guard at
`:357`, anchor `if len(path) == 0:`), and deleted the CLI guard. The comment
left at the old site records why, so the next person does not re-add it there.

**Shape B — the owner is correct and simply never reached.** Nothing about the
owner is wrong. There is a code path on which it is not invoked at all.

Instance 2 is this shape. After the relocation, `history` and `bisect` still
accepted `--ignore=` and exited 0. Both build the checker **inside the
per-commit loop** — `_build_configured_checker` is called at
`src/protokit/schema/cli.py:1241` (inside `for old_ref, new_ref in pairs:`) and
`:1618` (inside `for sha in commits:`). An empty commit range
(`--range HEAD..HEAD`) yields zero iterations, so the loop body never runs,
the checker is never built, and the owner is never consulted. The command
printed `no commits touch …` and exited 0 with an invalid flag silently
accepted.

The fix for Shape B is an **additional eager check at every entry point** —
and, critically, one that *invokes* the owner rather than restating its rule:

```python
# src/protokit/schema/cli.py:562
def _validate_ignore_paths(ignore_paths: tuple[str, ...]) -> None:
    probe = SchemaChecker()
    for path in ignore_paths:
        try:
            probe.ignore(path)
        except ValueError as exc:
            error_exit(
                f"invalid --ignore path {path!r}: {_safe_for_stderr(exc)}"
            )
```

The throwaway `SchemaChecker` exists solely to reach the owner. The rule is
still written down in exactly one place; only *when* it is consulted changed.
Every subcommand that accepts `--ignore` now calls this at entry:
`check` (`:929`), `history` (`:1161`), `bisect` (`:1502`), `ci` (`:1826`).

The reflex "I fixed the owner, therefore every caller is fixed" is only sound
for Shape A. Shape B needs a second, separate question, which is step 3 below.

### 2. The detection procedure

Four steps. Run them on the diff, not on the bug report.

**Step 1 — grep the ingredient, not the symptom.**

The symptom is the thing you just fixed, so a symptom-shaped grep finds your
own fix and stops. Anchor instead on something every sibling *must* contain
semantically — a field access, an enum comparison, a constructor call — and
never on incidental formatting.

Instance 3 (the stderr-forgery fix, which sanitized the `check`/`ci` renderer
and left two others) illustrates both halves. The bad anchor:

```console
$ grep -n 'click.echo(.*err=True)' src/protokit/schema/cli.py
692:        click.echo(f"{prefix} {_safe_for_stderr(d)}", err=True)
```

One hit — the fixed site. The two siblings are line-wrapped calls, so a grep
matching a whole call expression cannot see them. The good anchor is the thing
every diagnostic renderer must compute:

```console
$ grep -rn 'd.level == "error"' src/protokit/schema/cli.py
688:        prefix = "Error:" if d.level == "error" else "Warning:"
1257:                prefix = "Error" if d.level == "error" else "Warning"
1634:                prefix = "Error" if d.level == "error" else "Warning"
```

Three hits: the shared `_run_check_pipeline` helper used by `check` and `ci`
(`:688`), plus `history` (`:1257`) and `bisect` (`:1634`), each rendering
diagnostics per-commit from its own call site. Even better as a structural
anchor, because it survives a rewrite of the prefix expression:

```console
$ grep -n 'report.diagnostics' src/protokit/schema/cli.py
687:    for d in report.diagnostics:
711:    if report.diagnostics:
1254:        if report.diagnostics:
1256:            for d in report.diagnostics:
1631:        if report.diagnostics:
1633:            for d in report.diagnostics:
```

**Step 2 — enumerate every call site of the owner and classify each.**

```console
$ grep -rn '\.ignore(' src/protokit/
src/protokit/schema/profiles.py:201:            checker.ignore(path)
src/protokit/schema/cli.py:587:            probe.ignore(path)
src/protokit/schema/cli.py:621:            checker.ignore(path)
```

Three: the policy path, the eager validator, the checker builder. That is the
complete supported-entry inventory, and the point of running it is that **if
the count surprises you, your mental model of the surface is wrong, and that
is the finding.** The first V31 revision would have shown a `profiles.py` hit
sitting outside the guard.

For a library, the inventory must include the **public API**, not only the CLI.
`SchemaChecker` and `CompatibilityPolicy` are documented surface; `protokit
compat` is one caller of them. Instance 1 is precisely the error of treating
the CLI as the boundary.

**Step 3 — ask reachability, not correctness.**

For every call site, two distinct questions:

- (a) *Is the owner correct?*
- (b) *Does this path reach the owner on **every** input — including the inputs
  on which no work happens?*

Question (b) is the one that gets skipped, and it is where Shape B hides.
Reachability killers, roughly in order of how often they conceal a sibling:

1. **The owner is constructed inside a loop body** — an empty collection skips
   it entirely. This is instance 2.
2. **An early return or short-circuit above the owner** — `if not files:
   return`, `if cached: return cached`.
3. **A branch added later for performance** — a "fast path" that reimplements
   part of the flow and forgets the guard.
4. **Lazy or memoized construction** — the owner runs once, on a path a given
   input may not take.

The operational test: *for each call site, try to name an input for which the
owner is never invoked.* If you can name one, you have found a sibling. For
`history`, that input is `--range HEAD..HEAD`. Empty ranges, empty file lists,
empty rule sets, and zero-match globs are the standing candidates.

**Step 4 — mutation-prove each site independently.**

Breaking the owner and watching tests fail proves *the owner* is covered. It
proves nothing about the sibling call sites: a test exercising only `check`
fails under a mutation to `checker.py` and tells you nothing about `history`.

Mutate **at the site**. To prove the `history` renderer is covered, revert only
its sanitizer:

```sh
python3 scripts/mutation_check.py src/protokit/schema/cli.py \
  '{_safe_for_stderr(d)}' '{d}' \
  tests/schema/test_cli.py::TestRulePack::test_plugin_diagnostic_cannot_forge_stderr_on_any_subcommand
```

`scripts/mutation_check.py` requires the anchor string be **unique in the
file** (it refuses with `SETUP FAILED` otherwise), which forces per-site
anchors — exactly the constraint this defect class needs. It also re-reads the
file from disk to prove the mutation landed, and always restores it.

One harness caveat, recorded in both sibling learnings and worth repeating
here because it produces a *false proof from the tool whose job is preventing
false proofs*: `mutation_check.py` infers failure from a non-zero exit code,
with no collected-test-count check. A wrong pytest node id therefore prints
`NON-VACUOUS` on a run that collected **zero** tests. Read the printed pytest
tail, not just the verdict line.

### 3. A guard at a chokepoint is not sufficient on its own

"All four subcommands share `_build_configured_checker`" was **true**, and it
was not enough. A shared boundary is only shared *when it is reached*.

The rule that follows: **whenever a guard lives at a construction site inside a
loop, or behind any branch, pair it with an eager check at each entry point.**
Express the eager check by invoking the owner, so the rule still has exactly
one home. That is what `_validate_ignore_paths` does.

The eager check bought a second property worth naming separately, because it is
an independent reason to adopt the same shape: **a usage error should not first
cost expensive or dangerous work.** Before the change, an invalid `--ignore`
was rejected only after rule-pack import, git ref resolution, and proto
compilation — meaning `--ignore= --compat-rule-pack evil.mod` executed the
pack's module-level code before reporting the usage error. Ordering validation
ahead of side-effecting work is good practice on its own, and it happens to
close the reachability hole. Pinned by
`test_empty_ignore_rejected_before_rule_pack_import`
(`tests/schema/test_cli.py:1502`), which passes a nonexistent module and
asserts the error names `--ignore`, not the rule pack.

### 4. How to write a parity test that cannot have the blind spot

The test that failed to catch instance 2 was written for exactly that purpose.
`TestEmptyIgnoreRejectedEverySubcommand` (`tests/schema/test_cli.py:1414`)
opens:

> The audit's characteristic finding is a fix applied at one call site while
> structurally identical siblings stay broken. All four subcommands share
> `_build_configured_checker`, so this class is the assertion that the shared
> boundary is genuinely shared.

It passed while `history --range HEAD..HEAD --ignore=` exited 0, because every
original case used a **non-empty** commit range. Each case reached the shared
boundary; none exercised the branch that skips it. The class asserted the
shared thing was *correct*, and believed it had asserted the thing was
*shared*.

Three properties make a parity test carry the weight its docstring claims:

**(a) Derive the surface from the code, not from a hand-written list.** Walk
every subcommand / registered handler / implementation, so a sibling added
later is covered by construction rather than by someone remembering. The
regression test for instance 3 does this deliberately — #52's rationale was
that this was the third occurrence, so the test walks every subcommand rather
than pinning the two that were broken
(`test_plugin_diagnostic_cannot_forge_stderr_on_any_subcommand`,
`tests/schema/test_cli.py:396`). It iterates an `invocations` list and asserts
per-invocation:

```python
for args in invocations:
    result = _invoke_in_repo(git_repo, args)
    for line in result.output.splitlines():
        assert not line.startswith("error[lint-"), (
            f"{args[0]} forged a stderr line: {line!r}"
        )
```

A literal list is still a hand-written enumeration and is the weaker form;
deriving the list from the click group's registered commands would close the
remaining gap, and is the shape to reach for when the surface is enumerable at
runtime.

**(b) Include the zero/empty case for every collection the code iterates.**
This is the property whose absence caused the miss, and it generalizes cleanly:
*if a code path loops over commits, files, rules, fields, or messages, the
parity test needs a case where that collection is empty.* The empty case is the
one that tests whether the shared boundary is **reached**, and it is exactly
the case a realistic fixture never produces — realistic fixtures have data in
them. `test_history_rejects_empty_ignore_on_empty_range` and
`test_bisect_rejects_empty_ignore_on_empty_range`
(`tests/schema/test_cli.py:1466` and `:1488`) are that case; both were added
only after review found the hole.

**(c) Assert the negative, not just the exit code.** An exit-code-only
assertion can pass for the wrong reason — a different error on a different
line. Assert that the fail-open's characteristic **success text is absent**:

```python
assert result.exit_code == 2, result.output
assert "no commits touch" not in result.output   # history / bisect
assert "COMPATIBLE" not in result.output         # check / ci
```

**Checklist before you believe a parity test.** For each dimension the class
claims parity over, is there a case at the **zero boundary** of that dimension?
If not, the class proves the shared thing is correct, not that it is shared.

### 5. Re-review after the fix — a single pass is not enough

This is the control that empirically worked, and it is the one most easily
skipped, because a review that just found something feels finished.

During PR #48, the first cross-model adversarial pass found a map **value**-axis
false-equality. It was fixed, verified, committed. A **second** pass on the same
branch then found the **key** axis, left broken by the identical root cause. A
third pass was run to confirm nothing remained. The same shape repeated in
0.15.1: instance 2 was introduced by the fix for instance 1, and instance 3 was
found only by a pass run *after* the earlier round's fixes had landed.

The rule: **after fixing an instance of this pattern, re-run the review. The
fix itself is the highest-risk place for the next sibling.** Iterate until a
pass returns clean — one clean pass at the end, not one pass total.

This is why "I already thought about siblings" is worth less than nothing as
evidence: in every instance here, the author had just reasoned explicitly about
sibling blindness, and the reasoning is what produced the confidence that
skipped the check.

### 6. Derive the guarded set from the code, never from a list

A hand-maintained enumeration fails in both directions, and this was falsified
concretely rather than argued. Reviewing the 0.16.0 plan, a reviewer showed that
its proposed migration list would (a) flag modules that did not need migrating
and (b) omit the module that actually held the defect — discovered by grepping
for every *idiom* that enumerates descriptor fields, not by reading the list.

The standard that came out of it: **a structural guard must independently
discover its call sites** — by idiom, by AST shape, by walking a registry — and
must be red on day one against every unmigrated site. A guard that consumes a
list someone maintains is a reminder, not a guard. The same applies to parity
tests: the literal `invocations` list in this release's instance-3 regression
test is the weaker form, and deriving it from the click group's registered
commands is the shape to reach for.

## Why This Matters

**A partial fix is worse than no fix, not proportionally better.** Fixing one
of N call sites does not reduce the defect to (N-1)/N. It converts a
*known-open* defect into a *believed-closed* one. The CHANGELOG says fixed, the
suite is green, and the remaining siblings are now shielded from scrutiny by
the fix's own reputation. #52 caught exactly this before it shipped: a
`### Security` entry claiming coverage of "diagnostic emission sites" while two
advertised subcommands still forged `error[lint-…]:` lines would have been a
**false claim inside a security note** — the highest-trust text the project
publishes.

**Green suites are not evidence.** All three instances existed alongside a
fully green suite (3392 → 3433 → 3434 passing across the release). One of them
survived a test class purpose-built to catch its class of defect. A passing
suite tells you the assertions someone wrote still hold; it says nothing about
the surface nobody enumerated.

**Naming the pattern does not find its instances.** This is the finding that
justifies writing the procedure down. The project had the audit finding, the
plan language ("the characteristic failure"), and the pattern's name inside a
test docstring — and committed it three times in the same change. Vigilance
does not scale into a control. Greps and the reachability question do.

**The class concentrates in guards.** Validations, sanitizers, and exit-code
decisions are the code most likely to be added at whichever call site a bug
report named, because that is where the reporter's reproduction pointed. That
is also the code whose failure mode is silent: a missing guard does not crash,
it lets a bad input through somewhere else and reports success. Every one of
the three instances was a guard or a sanitizer.

**The blast radius follows the API surface, not the reporter's entry point.**
Instance 1's reproduction came in through a CLI flag; the unfixed siblings were
two documented Python entry points that any consumer embedding protokit would
hit without ever touching the CLI.

## When to Apply

Run the four-step procedure whenever **any** of these holds:

- **You are fixing at a call site rather than at a definition.** If the diff
  touches a caller, ask why the rule does not live in the callee.
- **The fix is a guard, validation, sanitizer, or exit-code decision.** Highest
  yield category, for the reasons above.
- **The fixed function is public API of a library.** The CLI is one caller.
  Enumerate the Python entry points explicitly; they will not appear in a CLI
  test sweep.
- **The symptom was reported through one entry point** — one subcommand, one
  endpoint, one output format, one file type. The reporter's entry point is a
  sampling artifact and is never the boundary.
- **A construction, validation, or emission happens inside a loop, a branch, or
  a lazily-initialized path.** Then step 3's reachability question is mandatory,
  not optional.
- **You are about to write a release note claiming a *class* is covered** — "all
  diagnostic emission sites", "every subcommand", "all entry paths". The scope
  of that sentence is now the required scope of the test. Write the sentence
  first if it helps; then go make it true.
- **You just fixed an instance of this pattern.** Empirically the highest-risk
  moment: all three instances here landed inside a change whose author had just
  reasoned explicitly about sibling blindness.

Skip it when the change is genuinely local — a fix inside a private function
with a single call site. Verify the "single" with a grep; do not assume it.

## Examples

### Instance 1 — API siblings (Shape A)

The V31 fail-open: an empty `--ignore` value parses to the root `FieldPath`,
and because ignore-filtering is segment-prefix matching, the root prefix-matches
every finding, so `compat` printed `COMPATIBLE` at exit 0 on a breaking schema.

**Before** — guard at the CLI flag boundary in `_build_configured_checker`:

```python
# CLI path: rejected.
$ protokit compat check old.desc new.desc --type acme.User --ignore=
error: invalid --ignore path ''            # exit 2

# Python API paths: still fully open.
>>> c = SchemaChecker(); c.ignore(""); len(c.check(...).findings)
0                                          # baseline without ignore: 1
>>> CompatibilityPolicy(ignore_paths=("",)).check(...).findings
[]
```

**After** — the rule lives at the single owner, `SchemaChecker.ignore`
(`src/protokit/schema/checker.py:357`), and `CompatibilityPolicy.check` reaches
it through `checker.ignore(path)` (`src/protokit/schema/profiles.py:201`). The
CLI guard was deleted; a comment at the old site records why it must not come
back.

The guard tests `len(path) == 0` rather than `if not path`, because a `str`
subclass overriding `__bool__` is empty-but-truthy. That is documented in the
code as a robustness measure, not a security boundary — `__len__` is overridable
too, and anyone able to subclass `str` in-process can append to `_ignore_paths`
directly.

### Instance 2 — the unreached owner (Shape B)

**Before** — owner correct, never reached:

```console
$ protokit compat history --range HEAD..HEAD \
    --proto-file acme/user.proto --type acme.User --ignore=
no commits touch acme/user.proto
$ echo $?
0
```

The checker is built at `src/protokit/schema/cli.py:1241`, inside
`for old_ref, new_ref in pairs:`. Zero pairs, zero iterations, zero validation.
`bisect` has the identical structure at `:1618`.

**After** — `_validate_ignore_paths(ignore_paths)` at each subcommand entry
(`:929`, `:1161`, `:1502`, `:1826`), implemented as a throwaway probe that
calls the owner. Exit 2 on every subcommand, on every range, empty or not.

Note the scope the fix actually has, which is wider than the reported bug and
was corrected in #52's upgrade table: `history` and `bisect` now reject **any**
malformed `--ignore` on a walk that finds no commits, not just the empty value
— because none of them were being validated on that path.

### Instance 3 — renderer siblings

The stderr-forgery fix: `FieldPath.parse` embeds the offending path *unquoted*
in its `ValueError`, so a newline in a flag value rendered as a second stderr
line — one that could begin with the `error[lint-…]:` prefix CI scripts grep
on, forging a gate result.

**Before** (#51) — `_run_check_pipeline` sanitized, per-commit renderers not:

```python
# cli.py:1258 (history) and cli.py:1632 (bisect)
click.echo(f"{prefix} ({new_ref[:12]}): {d}", err=True)
```

**After** (#52):

```python
click.echo(
    f"{prefix} ({new_ref[:12]}): {_safe_for_stderr(d)}",
    err=True,
)
```

All three emission sites now route through `_safe_for_stderr`
(`src/protokit/_cli_utils.py:835`), which collapses newlines, carriage returns,
NUL bytes, ANSI escapes, other ASCII control characters, and the Unicode line
terminators `U+0085` / `U+2028` / `U+2029` — the last group because
Unicode-aware log aggregators break on them even though terminals do not.

The regression test walks every subcommand rather than pinning the two that
were broken, with the reason stated in its own docstring: this was the third
occurrence of the pattern inside one change.

## Limits — what this procedure cannot do

**Writing this document is not a control, and neither were the three before
it.** The corpus named this pattern in April 2026, added a prevention rule in
May, and restated it in a third doc the same week. It recurred anyway, three
times in one release, including a direct violation of one of those documents'
stated rule on a sibling of the very surface it was written about. Treat prose
— this file included — as a way to make a *found* instance cheaper to
understand, never as a mechanism that prevents the next one. The mechanisms
that have actually caught instances here are: an independent falsification pass
told what to hunt, run iteratively; a derived-from-code guard that goes red on
day one; and a zero-boundary test case. Everything else is a reminder.

**This is a review-detectable class, not a test-detectable one.** A test can
only assert parity over a surface someone thought to enumerate, and the defect
*is* the failure to enumerate. Tests convert a **found** instance into a
permanently closed one; they do not find the next instance in a surface nobody
has looked at yet. Two things tests genuinely buy: (a) derived-from-code
enumeration covers *newly added* siblings by construction, and (b) once you know
a loop exists, the zero-boundary case pins it forever. Neither discovers the
first instance.

The practical implication is a budget one: **plan for independent review on any
change matching the "When to Apply" list, and do not treat a green suite as a
substitute.** In all three instances here, detection was a reader asking "where
else?" — never a failing test.

**Cross-model adversarial review outperformed in-house specialist review, on
this evidence.** Per the #51 and #52 records, an independent cross-model pass
(`gpt-5.6-sol`, run read-only via `codex exec --sandbox read-only`) prompted to
**falsify** the change rather than review it, and told the specific failure mode
to hunt, found what eight in-house specialist reviewers on the same diff did
not. Two mechanisms plausibly contribute and are worth keeping separate: the
reviewer had **no authorship stake** in the diff, and the prompt **named the
failure mode**. Neither is isolated as the cause — this is one release, n=1, and
the reviewers were not run as a controlled comparison. The defensible claim is
narrower and still actionable: a falsification-framed pass with a named target
is cheap, and here it paid for itself three times.

**The author cannot reliably run this on their own diff.** Every instance was in
the author's own fix, written immediately after the author had reasoned
explicitly about sibling blindness — and instance 2 was introduced by the *fix
for* instance 1. Treat "I already thought about siblings" as **no evidence at
all**, and route the check to someone (or something) that did not write the
patch.

**Mutation proof has its own failure mode.** `scripts/mutation_check.py`
reports `NON-VACUOUS` from a non-zero exit code, so a wrong pytest node id —
which collects zero tests — yields a false proof. Verify the collected count in
the printed tail before trusting the verdict.
