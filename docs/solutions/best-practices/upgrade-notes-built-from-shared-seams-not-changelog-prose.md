---
title: "Upgrade-notes rows come from the changed shared load and exit sites and a run against the released version, not from the release's own CHANGELOG prose"
date: 2026-09-27
category: docs/solutions/best-practices
module: release/upgrade-notes
problem_type: best_practice
component: development_workflow
severity: medium
applies_when:
  - "Drafting a release's upgrade table or README upgrade notes from the release's own CHANGELOG bullets and their 'Upgrade impact' paragraphs"
  - "A validation, catch, or exit wrapper was added at a shared load or exit site reached by several CLI commands, and the bullet that introduced it names only the command that motivated it"
  - "Stating an exit-code before-state without running the previously released, pip-installed version under the same protobuf version on both backends"
  - "Writing a presence-ratchet test whose anchor (a table header, a link) could also be satisfied by an older release's section or by the other of two files"
  - "Deciding the upgrade notes are complete after one review pass, before independent falsification with different questions has run"
symptoms:
  - "A row documents a check as affecting one command, while every other command that loads through the same shared site also changed exit code"
  - "A row says a command crashed on an input that the released version already rejected with exit 2"
  - "scripts/mutation_check.py refuses a CHANGELOG anchor because the same table header appears in more than one release's section"
  - "A link-presence test stays green when one of two files loses its link, because it asserts that a link exists anywhere"
root_cause: incomplete_implementation
related_components:
  - documentation
  - testing_framework
  - tooling
tags:
  - upgrade-notes
  - changelog
  - exit-code-contract
  - seam
  - sibling-blindness
  - presence-ratchet
  - before-after-matrix
  - cross-model-falsification
---

# Build a release's upgrade table from the changed shared sites and a run against the released version, not from the CHANGELOG bullets

## Context

0.16.0 moves many CLI paths to exit 2 and ships no switch to restore the old
codes. The upgrade table at the top of the release's CHANGELOG section, and the
README's "Upgrade notes (0.15.x → 0.16.0)" checklist built from it, are what a
user reads when a pipeline that passed yesterday turns red. The table's stated
scope is every change that can alter what a pipeline sees on upgrade with no
change on the user's side: an exit code that moves, a machine-readable verdict
or wire version that changes, a Python constructor that starts raising.

The first draft of the table was compiled from the release's own CHANGELOG
prose: the per-unit "Fixed — BREAKING (U3/U5/U6/U7/U8)" sections and their
"Upgrade impact" paragraphs. That looked like the obvious source, because each
unit had already described its own user-visible change. It was not complete,
and in places it was wrong. Each bullet was written by the unit that made the
change, when it made it, and it described the command that motivated the
change.

Four passes corrected it, in this order: an executed before/after exit-code
matrix against the released 0.15.1 package, three cross-model falsification
passes, a full code review with a cross-model peer, and a last refuter pass on
the corrected rows. Every pass found more rows, and most of the table was
rewritten after the first draft. Almost every miss had the same shape: **a validation or catch added at a
shared load or exit site changes the exit code of every command that goes
through it, but the bullet that introduced it names only the command that
motivated it.** This is the documentation form of the pattern in
[[sibling-blindness-fix-survives-review-structural-siblings-stay-broken]]. There
the fix reaches one call site and misses its siblings. Here the fix reaches
every sibling correctly, and the description reaches only one.

This had happened one release step earlier as well (session history). The
unit that added the descriptor-set UTF-8 check, #87, found the raw-exception
shape one call site at a time across two cross-model passes, and its own PR
table of "how bad input fails" still described the input classes it had been
looking at. The upgrade table inherited that framing.

## Guidance

### 1. Write the scope sentence first, and include 1 → 2 moves

The 0.15.0 table left out any fix "whose previous behaviour was already a
crash, a hang, or a non-zero exit", on the grounds that no passing pipeline
could break. That reasoning fails for this CLI. `lint` and `diff` document exit
1 as "the tool ran and found something", and `compat` documents it as
INCOMPATIBLE. So a crash that surfaced as a traceback plus exit 1 was read as a
finding by any gate that tells 1 from 2, and a 1 → 2 move changes what that
gate sees. State the scope in the note itself, as 0.16.0 does ("Unlike the
0.15.0 table, this one also lists exit 1 → exit 2 moves"), so reviewers can
test rows against it.

### 2. Enumerate rows from the changed shared sites, not from the bullets

Treat each CHANGELOG bullet as a lead, not as the list. For every new
validation, catch, or exit wrapper in `git diff v<prev>..HEAD -- src/`:

1. Name the function it lives in.
2. Grep that function's callers until each one reaches a CLI command or a
   public API entry point.
3. Each (command × input class × protobuf backend) reached is a candidate row.
   The bullet covered one of them.

In protokit the sites that fan out this way are the descriptor-set loader
(`protokit._pools.build_pool`, which every CLI but `lint` reaches when it
loads a descriptor set; `lint`'s own loader calls the same checks directly),
storage's `_exit_after_scan` (the exit of `scan`, `head` and `count`, apart
from `scan`'s Parquet output path),
`protokit._records.own_tuples` / `as_tuple` (the collection fields of every
public frozen record), compat's `_load_rule_packs`, and the `protokit._trust`
seam (every exit gate). A change to any of these is a change to many commands.

### 3. Settle every before-state by running the released package

Build a throwaway venv, `pip install protokit==<prev>` into it, and pin the
**same protobuf version** as the working tree, so any difference comes from
protokit and not from protobuf. Build fixtures in code: `descriptor_pb2`
FileDescriptorSets, length-delimited data files, a throwaway git repo, a `PATH`
with no `git`. Run every candidate row against the released CLI and against the
working tree, under upb and under
`PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python`, and record the observed exit
codes on both sides.

Reading `git show v<prev>:<path>` is fine for forming a hypothesis, but it does
not settle one. The wrong before-states in the 0.16.0 draft were claims about
what the old catch lists did, and they were only settled by running the old
version (Examples 4 and 6). If a cell shows no move, the row goes away or gets
an explicit "already exited 2" note. Readers look for those notes as much as
for the moves.

### 4. Falsify with a different question each pass

Give each independent pass one question: completeness ("find a command and
input whose exit code changes and that no row covers"), truth ("for each row, is
the stated before-state what `<prev>` actually does?"), or the scope of rows
that just changed. Before editing, reproduce every counterexample on both
backends against the released version. Expect each pass to find more rows until
the step-2 enumeration is actually done. The `build_pool` fan-out (Example 1)
got past the matrix and the falsification rounds, and only the cross-model
review peer found it.

### 5. Check the notes' general claims against every renderer, and fix the bullets the table contradicts

A summary sentence like "every renderer asks the same predicate" is a claim
about code, and it needs the same grep as a row does (Example 8). Where the
matrix shows that an earlier unit's CHANGELOG bullet is wrong, correct the bullet
in the same change. It is user-facing too, and the table and the bullet must not
disagree.

### 6. Pin the notes with a section-scoped, mutation-proven presence ratchet

Follow [[presence-ratchet-test-pattern-for-prose-substrings-2026-05-14]], with three
points specific to upgrade tables:

- **Scope CHANGELOG checks to this release's `## ` section.** The table header
  `> | Change | What starts happening |` appears in both the 0.16.0 and 0.15.0
  tables (and 0.15.1's table uses the same header without the quote marker), so a whole-file check would pass even if 0.16.0's table were deleted.
  `scripts/mutation_check.py` refused that anchor ("appears 2x … make the
  anchor unique"), and that refusal is how the gap came to light.
  `tests/meta/test_upgrade_notes_presence_ratchet.py` selects the section that
  contains the release's upgrade-note line, not the `## Unreleased` heading, so
  renaming that heading at the cut does not break the check, and an older
  release's section cannot satisfy it.
- **Mutation-prove each test.** The first link test asserted that some link to
  the notes existed across README.md and CHANGELOG.md. Deleting either link left
  it green, because the other file still satisfied it. It now requires a link
  from each file.
- **Check each link's destination file.** A bare `#upgrade-notes-…` fragment
  inside CHANGELOG.md resolves against CHANGELOG.md's own headings, not
  README's.

## Why This Matters

With no opt-out, the upgrade table is the only explanation a user gets for a
red pipeline. A missing row leaves a failure unexplained. A wrong before-state
is worse, because it sends the user looking for a behaviour change that did not
happen. Had the table built from the bullets shipped, it would have left out
that `diff`, `storage` and `forensics` stop accepting a class of descriptor
sets under upb. It would have described `count --quiet` as 0 → 2 when it is
1 → 2, and it would have described a compat rule-pack move that did not happen.
Release notes are read at upgrade time, after the version is on PyPI, and a
published release cannot be taken back. Correcting them then means a second
release or an erratum.

The CHANGELOG bullets are not careless. They are accurate about the case that
prompted the change. The failure is structural: whoever changes a shared site
describes the caller they were looking at. Only an enumeration of callers and
an executed matrix see the rest.

## When to Apply

- Every release whose diff touches exit codes, rendered or machine-readable
  verdicts, wire versions, or constructor validation. 0.17.0, 0.18.0 and 0.19.0
  each need upgrade notes.
- When the release diff adds a check, a catch, or an exit wrapper to a function
  with more than one caller.
- When any row, bullet or README sentence says "instead of", "used to" or
  "already". Each of those is a before-state claim and needs a matrix cell.
- When a release widens the supported protobuf range (the planned move off the
  `protobuf<6` pin): keep the protobuf version identical on both sides of each
  cell, and treat behaviour that changes with the protobuf version as a
  separate set of rows.

## Examples

The 0.16.0 misses. "Draft said" is the first table draft, which came from the
bullets. The corrections are what the matrix, the falsification rounds or the
review found, each reproduced against released 0.15.1.

1. **Descriptor-set UTF-8 check (#87).** Draft: "`lint` over a descriptor set
   with a non-UTF-8 file name, under upb: traceback and 1 → 2."
   `require_decodable_strings` is called inside `_pools.build_pool`, which
   every descriptor-set load goes through: `diff` via
   `_cli_utils.load_descriptor_pool`, and `storage` and `forensics` via
   `storage.schema_source`. Under upb, `diff`, `storage` and `forensics` used to
   accept such a set and now reject it (0 → 2). Only the cross-model review
   peer found this; the matrix and the falsification rounds had missed it. The
   review's row was still too narrow: the check walks every string in the set,
   so a non-UTF-8 *comment* moves all five commands, `lint` and `compat`
   included, from 0 to 2 under upb. And the same function's import probe now
   resolves every file under the pure-Python runtime, so an unresolvable type
   reference in a file the command never uses moves `diff`, `storage`,
   `forensics` and `lint` from 0 to 2 there (`compat` from a crash and 1). A
   final refuter pass on the corrected rows found both; the rows now describe
   the loader, not a command.
2. **Storage scan exit (#76).** Draft: "exits 2 instead of 0 when records were
   dropped." `scan`, `head` and `count` now exit through `_exit_after_scan`,
   which lets incompleteness override `count --quiet`'s grep-style 0/1. At
   0.15.1, `count --quiet` with no match exited
   `sys.exit(0 if matched > 0 else 1)`, so that path is 1 → 2.
3. **Lint rule `profiles` (#84).** Draft: rejects `profiles="name"`.
   `LintRuleSpec.__post_init__` runs `own_tuples(self, "profiles")`, and
   `as_tuple` refuses a `Mapping` as well as a `str`, so
   `profiles={"default": True}` also goes 0 → 2 via
   `error[lint-rule-pack-load]`.
4. **Compat rule-pack loading (#76).** Draft: "a pack that raises at import
   exits 2 instead of 1." At v0.15.1 `_load_rule_packs` already wrapped
   `importlib.import_module` in `except Exception`, so an import-time exception
   already exited 2. The exit-1 case was `RULES` raising while it was read:
   only `AttributeError` and `TypeError` were caught around `load_rule_pack`.
   A `RULES` iterator that raised `SystemExit(0)` went 0 → 2, and
   `KeyboardInterrupt` at import printed Click's `Aborted!` and exited 1. It was
   not a traceback.
5. **`diff --max-depth` (#76).** Draft: "where the cut hides every difference."
   `_diff_exit_code` returns 2 whenever `_trust.is_trustworthy(result)` is
   false, and any truncation makes it false. So, per the matrix run, identical
   messages nested deeper than the limit also go 0 → 2.
6. **`diff` over a non-UTF-8 proto3 string, pure-Python (#87).** The #87
   bullet said `diff` "crashed on such an input". At v0.15.1 `_parse_message`
   already caught `UnicodeDecodeError`, and it exited 2. Only deep nesting
   (`RecursionError`, which was added to that catch) crashed with exit 1. The
   bullet was corrected in the U20 upgrade-notes change.
7. **Pure-Python `Descriptor does not contain serialization` crash.** Draft:
   "`compat`, `forensics match` / `drift` over a descriptor-set schema." Per the
   matrix run, `compat` crashed on every such schema, but `forensics` crashed
   only on paths that read reserved ranges or names. The row now says so.
8. **A general claim, not a row.** The README said that every renderer asks the
   same completeness predicate. `forensics match` prints its verdict from
   `_verdict_line`, which reads `report.verdict` and never consults
   `protokit._trust`. `_exit_unless_vouched` runs after rendering. So a run can
   print `verdict: clean match` and exit 2 when another candidate could not be
   measured. The README claim now covers only the `diff` / `compat` / `lint`
   formatters and names the forensics exception. The code gap is a follow-up.
   The same overbroad wording ("the same predicate every renderer … asks") is
   still in `_exit_after_scan`'s docstring.

In every one of these, the source had the answer at a single shared function,
and the bullet described one caller of it.

## Related

- [[sibling-blindness-fix-survives-review-structural-siblings-stay-broken]] — the code-fix form of the same shape.
- [[trust-boundary-enforcement-points-derived-from-code-not-the-findings-wording]] — scope taken from a finding's wording rather than the code's enforcement points; its Prevention step 1 is what Guidance step 2 applies to release notes.
- [[presence-ratchet-test-pattern-for-prose-substrings-2026-05-14]] — the ratchet discipline Guidance step 6 builds on.
- [[mutation-check-harness-stale-bytecode-and-nonverdict-exit-codes-produce-false-verdicts]] — the harness whose anchor-uniqueness refusal exposed the repeated table header.
- [[docs-code-drift-defense-convention-2026-06-13]] — why this doc names functions rather than line numbers.
