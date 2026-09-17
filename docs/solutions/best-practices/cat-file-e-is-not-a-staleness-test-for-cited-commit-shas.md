---
title: "`git cat-file -e` is not a staleness test for a cited commit SHA, and a rewrite map is a hop rather than an answer"
date: 2026-09-14
category: docs/solutions/best-practices
module: docs/solutions
problem_type: best_practice
component: documentation
severity: medium
root_cause: incorrect_assumption
resolution_type: process_fix
applies_when:
  - "Auditing documentation, changelogs, or comments that cite short commit SHAs as provenance"
  - "A repository has been through `git filter-repo`, `filter-branch`, or any history rewrite"
  - "A repository squash-merges pull requests, so branch commits never appear on the default branch"
  - "Deciding whether a citation still points at the work it claims to describe"
  - "Planning a bulk rewrite of references that a wrong mapping would silently corrupt"
symptoms:
  - "A cited SHA passes `git cat-file -e` but `git log` cannot find it and `git show` works only by accident"
  - "A staleness scan reports a small number of broken citations and a later `git gc` breaks many more"
  - "`.git/filter-repo/commit-map` maps a cited SHA to a successor that is itself unreachable"
  - "Two docs cite different SHAs for what turns out to be the same commit"
  - "A commit subject matches several candidates and none of them touched the file the doc describes"
related_components:
  - "tooling"
  - "development_workflow"
tags:
  - "git"
  - "history-rewrite"
  - "squash-merge"
  - "patch-id"
  - "documentation-drift"
  - "provenance"
---

## Context

`docs/solutions/` cites short commit SHAs as provenance — anchor commits, before/after
states, "the fix landed in". A history rewrite invalidates all of them at once, silently,
because nothing in the repository links a doc to a commit.

An audit of every short SHA cited in tracked docs found 80 distinct SHAs. **Three were
healthy.** The other 77 were broken in two different ways, and the obvious check only
found 34 of them.

## Guidance

### 1. Test reachability, not existence

`git cat-file -e <sha>^{commit}` answers "is there an object here", which is not the
question. After a rewrite the *old* objects usually survive in the object database as
unreachable garbage: on no branch, not an ancestor of HEAD, alive only until the next
`git gc`. They pass `cat-file -e`. They look fine. They are already wrong, and they will
become visibly wrong at an unpredictable moment.

```sh
# Wrong — passes for dangling objects
git cat-file -e "$sha^{commit}"

# Right — is this commit actually in current history?
git merge-base --is-ancestor "$sha" HEAD
```

In this audit that distinction was the difference between 34 broken citations and 77.
A scan built on `cat-file -e` alone **under-reported by more than half**.

### 2. Treat a rewrite map as one hop, not as the answer

`git filter-repo` leaves `.git/filter-repo/commit-map` — an old→new table. It is
authoritative for *the rewrite that wrote it*. It is not authoritative for "where did this
commit go", because a repository can be rewritten more than once, and the second pass
rewrites the first pass's output.

Here the map's own targets were themselves dangling. Following it once produced a SHA that
looked resolved and was still unreachable. Always re-check the map's output with the
reachability test from §1, and keep following until the answer lands in current history.

Note also that this file lives in `.git/` — it is **machine-local and not shared**. A
clone has no copy. If it is the only record of a rewrite, that record exists on exactly
one machine.

### 3. Resolve by patch content, never by commit subject

Subjects survive rewrites, which makes subject matching tempting and unsafe: conventional
commits repeat ("ce:review follow-ups" appears dozens of times), and a squash may merge
several described changes under one message.

`git patch-id --stable` identifies a commit by its diff, which a rewrite generally
preserves:

```sh
patch_id() { git diff-tree -p --no-color "$1" | git patch-id --stable | cut -d' ' -f1; }
```

Index every commit reachable from HEAD, then look up the old object's patch-id. Across 310
commits this produced 305 distinct patch-ids with **zero collisions**, and resolved 76 of
77 citations outright. Verify the survivors by checking the successor actually touches the
files the doc talks about.

### 4. A squash-merge leaves the same footprint as a rewrite

The one citation patch-id could not resolve was not a rewrite casualty at all: it was an
ordinary branch commit that was squash-merged into a PR and therefore never existed on
`main`. Its diff is a subset of the squash, so its patch-id matches nothing.

Any repository that squash-merges produces dangling, citable, `cat-file -e`-passing
commits as a matter of routine. This is not a one-time migration problem — it is the
steady state. Cite the squash commit or the PR number, not a SHA you read off your own
branch before it merged.

### 5. Derive a bulk mapping twice, by different means

A wrong mapping in a bulk rewrite is worse than the staleness it replaces: it produces
confident, resolvable, *incorrect* provenance that nothing will ever flag again.

Before rewriting, derive the mapping a second time by an unrelated method — here, per-SHA
archaeology over subjects, touched files, and pickaxe searches, each conclusion then
attacked by independent reviewers looking for a rival candidate, a diff mismatch, or an
ordering contradiction. The two methods agreed on all 34 SHAs they both covered, which is
what justified rewriting 157 citations mechanically.

Apply the substitution in **one simultaneous pass**, and assert first that no successor
SHA is also a key — otherwise a sequential pass rewrites its own output.

## Why This Matters

Provenance citations are load-bearing for exactly the reader who most needs them: someone
auditing a claim they do not already believe. A citation that resolves to the wrong commit
is worse than one that fails loudly, because it invites the reader to conclude the doc is
wrong about the code rather than about its own footnote.

The failure is also silent and delayed. Nothing in CI reads a doc's SHA. The citations
here broke in May 2026 and the breakage surfaced four months later, during unrelated work.

## When to Apply

Reach for §1 whenever a check answers "does this SHA exist". Reach for §3 and §5 before
any bulk rewrite of references. Reach for §4 when writing a new citation at all: prefer a
PR number or the squash commit on the default branch over a SHA from your working branch,
because the latter is dangling the moment the PR merges.

## Examples

### The scan that under-reported by half

```
distinct short SHAs cited in tracked docs : 80
  GONE      (cat-file -e fails)           : 34
  DANGLING  (passes, unreachable)         : 43   <- invisible to the naive check
  LIVE      (ancestor of HEAD)            :  3
```

### The map hop that resolved to another dangling object

```
cited      1249b10   GONE
commit-map 1249b10 -> 94708dd
           94708dd   DANGLING   <- passes cat-file -e, on no branch
patch-id   94708dd -> 6c28e63   LIVE
```

Two docs citing `1249b10` and `94708dd` respectively turned out to be citing the same
commit. Converging them fixed a latent inconsistency nobody had noticed.

### The false positives a hex regex finds

A `[0-9a-f]{7}` scan matches things that are not commits. Two had to be excluded by hand:
`e3b0c44`, the leading bytes of the empty-file SHA-256 quoted in a fixture-collision
learning, and `1000001`, the tail of the float literal `0.1000001`. Both would have been
"resolved" into nonsense by an unattended rewrite. Read every match's surrounding line
before substituting; a commit citation is almost always adjacent to a cue word
(`commit`, `anchor`, backticks, `pre-`/`post-`).

## A note for the next sweep

The SHAs in the examples above are **deliberately broken and must stay that way**.
`1249b10` and `94708dd` are cited precisely because they are gone and dangling
respectively, and `e3b0c44` / `1000001` are cited as regex false positives that are not
commits at all. Only `6c28e63` is a live citation. A future audit that "repairs" this file
destroys the examples it is built from — exclude this document, or check that a match is
not inside an example block, before rewriting anything here.

## Related

- `docs-code-drift-defense-convention-2026-06-13.md` — marking claims about a moving
  target as current-state, the general case of which this is one instance.
- `pinned-version-bump-reference-classification-2026-06-13.md` — classifying a reference
  as navigational or historical before deciding whether drift matters.
- `scripts/check_docs_test_refs.py` — the reporter that catches the sibling problem, a doc
  naming a test path that a rename moved. It is diff-scoped and does not look at SHAs;
  this class of drift has no gate, by deliberate choice, because a rewrite is rare and
  post-rewrite citations are stable.
