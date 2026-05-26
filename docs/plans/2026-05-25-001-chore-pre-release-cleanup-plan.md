---
title: "Pre-release cleanup + first public push for protokit 0.7.0"
type: chore
status: active
date: 2026-05-25
origin: docs/brainstorms/2026-05-25-pre-release-cleanup-requirements.md
---

# Pre-release cleanup + first public push for protokit 0.7.0

## Summary

Execute the pre-release cleanup sequence to take protokit from its current local-only state (`main` at commit `828a6c3`, D6f U3 delivery boundary, 0.7.0 ready) to a published PyPI release with a clean public GitHub repo at `github.com/marc-chiesa/protokit`. The work is sequenced across **13 Implementation Units in 8 phases**: full PII history rewrite via `git filter-repo` (the never-pushed assumption is load-bearing and verified), post-rewrite content reconciliation, public-facing file polish (including a selective README scrub and a 3-cluster `src/` comment scrub atomic with presence-ratchet test updates), internal-docs move to a private repo, security + CI verification, first public push + tag, TestPyPI dry-run + real PyPI publish, and post-publish monitoring setup.

The brainstorm's 7 decision threads (Q1-Q7) are all settled. Research surfaced scope extensions (`pyproject.toml` polish beyond URL fix, README has one Obsidian link + selective milestone-code scrub, `.github/workflows/ci.yml` has an embarrassing "no remote at time of writing" header note, SHA cleanup is 50 docs/solutions files not 10-15) and identified two presence-ratchet tests that pin milestone-code substrings — the `src/` scrub and these test updates MUST land atomically.

This is genuinely new territory for the project — no prior `docs/solutions/` learnings cover PyPI publish mechanics, `git filter-repo` PII rewrite at the pre-push boundary, or first-public-push setup. Expect 2-4 post-execution `/ce-compound` learnings worth capturing.

---

## Problem Frame

protokit has been developed entirely locally across 6 D-series deliveries (D2-D6f). The 0.7.0 release boundary (D6f U3) shipped on 2026-05-25 to local `main` at commit `828a6c3`. Pre-publish, several classes of cleanup are required:

1. **PII in git history** — 232 commits attributed to `mchiesa@gmail.com` (personal email) + 1 commit attributed to `marc@Marcs-MacBook-Pro.local` (local hostname leak). Standard "don't rewrite history" objections evaporate because the repo has never been pushed (verified: `git remote -v` empty, no push events in reflog). One-time rewrite via `git filter-repo --email-callback` cleans everything before any external reference exists.

2. **Internal workflow artifacts in repo** — `docs/brainstorms/`, `docs/plans/`, `TODOS.md`, `CLAUDE.md`, `CHANGELOG-DRAFT.md` are workflow internals that confuse external readers. Move to a private repo (`marc-chiesa/protokit-internal`) while keeping `docs/solutions/` in-repo (it's institutional knowledge that signals engineering rigor).

3. **Milestone-reference noise in user-facing code** — 21 `src/` files contain ~632 references to internal milestone designators (`D6X UY KZ`, `[[learning-with-date]]`, `R[N]b` rule IDs, `KD-N` decision IDs). A debug-from-source user dives into a `.py` file to verify behavior and hits a wall of internal jargon. Hand-edit pass rewrites these as descriptive prose (preserving the technical content) while leaving tests/ alone.

4. **Public-repo metadata gaps** — `pyproject.toml` `[project.urls]` Repository is a placeholder pointing at a non-existent user; `authors` field is incomplete; missing `LICENSE` file at repo root; missing `Changelog`/`Documentation` project URLs.

5. **First-impression risks on first public push** — README has an Obsidian-style link the brainstorm didn't catch; `.github/workflows/ci.yml` has a "this workflow lands as dormant config — the repo has no configured GitHub remote at the time of writing" header note that's embarrassing in a public context; the `protokit` GitHub org is taken (use personal account `marc-chiesa/protokit`); no LICENSE file makes `twine check` warn.

6. **One-way-door publish actions** — first public push, `git tag v0.7.0`, `uv publish` to PyPI. Each is hard to undo and demands verification before execution.

(see origin: `docs/brainstorms/2026-05-25-pre-release-cleanup-requirements.md`)

---

## Requirements Trace

Carried from brainstorm:

- **Q1** — Keep `docs/solutions/` in-repo; move `docs/brainstorms/`, `docs/plans/`, `TODOS.md`, `CLAUDE.md`, `CHANGELOG-DRAFT.md` to a private `marc-chiesa/protokit-internal` repo.
- **Q2** — Hand-edit `src/` comment scrub: strip `[[xxx-with-date]]` Obsidian-link notation everywhere; rewrite `D6X UY KZ`, `KD-N`, `R[N]b` references as descriptive prose; leave `tests/` alone; docstrings get priority over inline comments.
- **Q3** — Personal-account `github.com/marc-chiesa/protokit` (the `protokit` GitHub org is taken; defer org creation until concrete reason).
- **Q4** — Defer docs-generation site for 0.7.0; ship README-as-docs.
- **Q5** — PyPI publish via personal account; manual `uv publish` for 0.7.0; trusted publishing via GitHub Actions OIDC for 0.7.1+.
- **Q6** — Three-layer AI disclosure: `Co-Authored-By:` commit trailers (already present), CONTRIBUTING.md paragraph, NO README badge.
- **Q7** — Full PII history rewrite via `git filter-repo --email-callback` (load-bearing assumption: repo has never been pushed; verified). Fixes 232 gmail commits + 1 hostname-email commit. Followed by SHA-reference cleanup in docs/solutions/.

Scope extensions surfaced by Phase 1 research:

- **R-ext-1** — `pyproject.toml` polish beyond URL fix: complete `authors` (full name + noreply email), add `Changelog` + `Documentation` `[project.urls]`, scrub inline milestone-code comments in `[tool.pytest.ini_options]` + `[dev]` extra, optionally add `Typing :: Typed` classifier if `py.typed` marker present.
- **R-ext-2** — README selective scrub per user's call-out: strip the Obsidian-style link at line 1046; strip pure-breadcrumb milestone codes; KEEP version-anchored milestone codes in upgrade-notes / migration-recipe sections where they serve as version identifiers (`0.6.0 D6e R4b`-style refs help readers orient versions to changes).
- **R-ext-3** — `.github/workflows/ci.yml` cleanup: remove the "this workflow lands as dormant config — the repo has no configured GitHub remote at the time of writing" header note (lines 1-27); selective scrub of inline milestone codes; keep load-bearing comments (the parity-job branch-protection advisory). Run GHA expression-injection audit per `[[github-actions-expression-injection-env-block-mitigation-2026-05-13]]`.
- **R-ext-4** — `CONTRIBUTING.md` polish: scrub the one `D6b U4` milestone reference at line 24; add the Q6 AI workflow paragraph.
- **R-ext-5** — Two presence-ratchet tests pin milestone-code substrings that the src/ scrub may touch: `test_uxd_philosophy_principle_presence_ratchet.py` pins `"D6e KD-1: protokit-UX overrides buf-parity..."`; `test_builtin_packs.py` pins `"R9b per-rule disable surface"`. The src/ scrub and the test substring updates MUST land in the same commit per atomic-pair discipline.
- **R-ext-6** — `docs/solutions/` SHA cleanup scope is **50 files with 104 SHA references** (revised from brainstorm's "10-15 files"). CHANGELOG.md has **zero** SHA references (revised from brainstorm assumption). Additionally fix **4 `/Users/marc/...` absolute path leaks in 2 files** under `docs/solutions/best-practices/`.
- **R-ext-7** — README Public Surface DRAFT source audit before first public push per `[[public-surface-draft-discipline-source-audit-2026-05-12]]`. D6f added new surface (R6 promoted to ERROR, R9b per-rule disable mechanisms) that the DRAFT table needs to reflect accurately.
- **R-ext-8** — Verify `CHANGELOG-DRAFT.md` is stub-only (no staged D7+ content) before moving to private repo per `[[dormant-code-changelog-draft-staging-delivery-boundary-2026-05-17]]`. If real staged content exists, fold to `CHANGELOG.md` first.
- **R-ext-9** — Add an Acknowledgments section to README that accurately characterizes the buf relationship. The current ~100 references to buf across README + CHANGELOG + src/ are descriptive nominative-fair-use, but with no explicit relationship clarifier a first-time reader could reasonably wonder whether protokit is a buf project / fork / sponsored. Empirically verified: zero Buf-authored runtime dependencies (`pyproject.toml`); zero imports of Buf packages in `src/`; tests requiring buf skip cleanly (1 pass + 18 skip with buf absent — verified). Plus a one-line note in CONTRIBUTING.md clarifying buf is parity-test-only, not a build/run dependency.

---

## Scope Boundaries

Explicit non-goals for this plan:

- **Sphinx / MkDocs docs site** — deferred per Q4; ship README-as-docs for 0.7.0. Revisit post-0.7.0.
- **Rewriting all 232 gmail-attributed commits to fix anything beyond the email field** — the rewrite is email-only; commit messages, trailers, dates, content stay intact.
- **Scrubbing milestone references from `tests/`** — contributor surface; lower priority; brainstorm explicitly out-of-scope.
- **Scrubbing milestone references from `CHANGELOG.md`** — historical describer; "D6f", "D6e" are version identifiers tied to specific releases; users benefit from seeing which release introduced each change.
- **Scrubbing milestone references from `docs/solutions/`** — these ARE the institutional learnings; the `[[xxx-with-date]]` notation is the canonical cross-reference format and signals AI workflow honestly (per Q6 disclosure logic).
- **Branch protection rules, issue templates, PR templates, Code of Conduct, SECURITY.md** — minimum-viable GitHub repo settings for 0.7.0 per brainstorm's "Open scope question" default. Add post-0.7.0 if needed.
- **CI publish via trusted publishing on GitHub Actions OIDC** — defer to 0.7.1; 0.7.0 publishes via manual `uv publish` with project-scoped API token.
- **GitHub Organization creation** — `protokit` org is taken; deferred until concrete reason per Q3.
- **PyPI Organization** — PyPI orgs exist but are overkill for a solo project; publish under personal PyPI account.
- **Rewriting the 232 historical commits' `Co-Authored-By:` trailers** — these are anonymous (`<noreply@anthropic.com>`); no PII risk.
- **History rewrite of any branch other than `main`** — feature branches (`feat/d6d-u1-synthetic-custom-annotation-rules`, etc.) are local-only and already fully-merged into `main` (0 commits ahead). **ADV-6 clarification**: `git filter-repo` rewrites ALL refs by default (the U1 invocation does NOT use `--refs refs/heads/main`). Since the feature branches have no unique commits (they're just historical pointers into main's history), filter-repo will update their tip SHAs as a side effect of the main rewrite. This is safe and expected; the scope-boundary statement above means "we don't preserve them as named branches with rewritten content for any active use" — they're stale-by-design and should be deleted as part of U10 or U11 cleanup. To delete: `git branch -d feat/d6d-u1-synthetic-custom-annotation-rules feat/d6e-buf-basic-closure-and-philosophy-revision feat/d6f-r9b-and-r6-promotion` (lowercase `-d` refuses unmerged-branch deletion; the merged-to-main state means these will delete cleanly).

### Deferred to Follow-Up Work

- Trusted publishing via GitHub Actions OIDC (0.7.1)
- MkDocs Material site with mkdocstrings (0.8.x or 1.0)
- Branch protection on main (post-0.7.0; required when external contributors arrive)
- Code of Conduct + SECURITY.md (post-0.7.0)
- Move to GitHub organization (when concrete reason exists)
- Full history rewrite of 232 commits' `Co-Authored-By:` trailers if AI-disclosure norms shift

---

## Key Technical Decisions

### KD-1 — `git filter-repo` over `git filter-branch` or squash

`git filter-repo` is the modern replacement (Python-based, official Git recommendation since 2019). `git filter-branch` is deprecated and slower. Full-repo squash (`git checkout --orphan`) would lose the per-commit `Co-Authored-By:` trailers that are the Q6 disclosure mechanism AND erase git blame value for future contributors. `filter-repo` with `--email-callback` cleanly touches only the Author/Committer fields, leaves commit message bodies (including trailers) intact, and runs in <1 minute on 233 commits.

### KD-2 — Backup-clone-first discipline before applying rewrite

Per the never-been-pushed assumption (verified via `git remote -v` empty + no push events in reflog), the rewrite has no external-reference downside. But local catastrophe is still possible: a typo in the email-callback could rewrite to an unintended email, or filter-repo could fail mid-run leaving the repo in an inconsistent state. Mitigation: backup-clone to `/tmp/protokit-rewrite-test`, run the rewrite there first, verify `git log --format="%ae %ce" --all | sort -u` shows only the noreply email, then apply to the working repo.

### KD-3 — Split src/ scrub into 3 file-cluster commits, atomic with presence-ratchet test updates

Per user call-out + `[[delivery-boundary-unit-commit-composition-2026-05-14]]`: each Implementation Unit is one atomic commit. The 22 src/ files split naturally:
- **Cluster A**: `schema/lint/_config.py` + `schema/lint/cli.py` (118 + 88 lines = 206 milestone-ref lines; the heavy hitters)
- **Cluster B**: `schema/lint/model.py` + `schema/lint/engine.py` + `schema/lint/rules/__init__.py` (63 + 66 + 31 = 160 lines; the public surface — also where the 2 presence-ratchet tests pin substrings)
- **Cluster C**: `schema/lint/rules/options/*` + `schema/lint/rules/package.py` + `schema/lint/rules/package_same.py` + `schema/lint/_cli_utils.py` + the 3 files surfaced by Phase 1 research (`schema/lint/rules/naming.py`, `imports.py`, `enum.py` — each with `docs/plans/` path refs that become dangling after U9 moves docs/plans/) + remaining smaller files (~150 lines total) + `.github/workflows/ci.yml` inline comments. **Note**: `pyproject.toml` comment scrub is owned entirely by U3 (which already touches the file) — not split across U3 and U8 per scope-guardian F4. This keeps the pyproject.toml diff in a single unit.

Cluster B carries the test-substring updates atomically (rewriting `D6e KD-1: ...` in `rules/__init__.py` AND updating `tests/test_uxd_philosophy_principle_presence_ratchet.py` in the same commit). This avoids the bisect hazard of "commit N broke the ratchet test; commit N+1 fixed the test" — a single atomic commit preserves bisectability.

### KD-4 — `R9b` is canonical feature name, not milestone-code-to-strip

The phrase `"R9b per-rule disable surface"` is pinned by `tests/schema/lint/test_builtin_packs.py` as a load-bearing presence-ratchet substring. The `R9b` token started as an internal requirement designator but the feature has shipped under that name in CHANGELOG migration recipes and README sections. Treat `R9b` as the canonical feature identifier (like `proto2-strict` is a profile name); do NOT strip from the docstring or from the test substring. By contrast, `D6e KD-1` in the `protokit-UX overrides buf-parity` ratchet IS a pure milestone reference and SHOULD be rewritten (the underlying principle is the canonical content, not the `D6e KD-1` prefix).

### KD-5 — Selective README scrub: testable keep-vs-strip rule per PL-001

Strip the one Obsidian-style link at line 1046 (`per [[closed-literal-discriminator-bump-trigger-2026-05-17]]`) — rewrite as descriptive prose.

**Testable rule for milestone-code scrub** (PL-001 fix; replaces the previous undefined "version-anchored" vs "pure-breadcrumb" distinction):

**KEEP** a milestone code (e.g., `D6f`, `D6e R4b`, `R9b`, `KD-1`) ONLY when ALL of these conditions hold:

1. **Co-occurs with a semantic version string** (e.g., `0.7.0`, `0.6.x → 0.7.0`, `as of 0.6.0`) in the SAME sentence or table cell, AND
2. **Appears in an "Upgrade notes" section, "Migration recipe" section, or "Profile description" table cell** (the README locations where version anchors aid the reader), AND
3. **Removing the milestone code would make the version-to-change mapping ambiguous** (e.g., "0.7.0 added R6 promotion" — the `R6` is load-bearing because users may search migration docs for "R6"; vs "the per-rule disable surface added in 0.7.0" — milestone code adds no information beyond the version).

**STRIP** in all other positions:

- Schema-linting intro paragraphs (replace with descriptive prose)
- Code/text without a semantic version nearby
- Cross-references to plans/brainstorms by milestone code (e.g., "per D6f plan KD-8" → "per the [post-ship adoption monitoring discipline](#post-ship-adoption-monitoring)")
- Public Surface DRAFT cell contents (already comprehensive; milestone codes there are redundant)

**Verification gate** (mirrors U6-U8's grep discipline): after the U4 scrub, `grep -E "D6[a-f]" README.md` returns ONLY matches that satisfy all 3 KEEP conditions above. Run a spot-check on 5 random remaining matches to verify.

Rationale: the previous version of KD-5 said "keep version-anchored, strip pure-breadcrumb" without defining either category, which would produce inconsistent results across reviewers and future edits. The 3-condition rule is mechanical and survives the post-execution grep check.

### KD-6 — Final delivery-boundary commit shape

Per `[[delivery-boundary-unit-commit-composition-2026-05-14]]`: the final commit before push is NOT "whatever's left." It should be a focused commit. In this plan's case, the public push happens after a long sequence of cleanup commits — the push itself (`git push --set-upstream origin main`) does not require a new commit. The tag (`git tag v0.7.0`) is a lightweight ref, not a commit. So there's no "delivery-boundary commit" to compose in this plan — the boundary commit `828a6c3` (D6f U3) already happened. This plan's commits are pre-release cleanup, not delivery-boundary.

### KD-7 — Post-rewrite SHA cleanup limited to `docs/solutions/`

Verified by repo research: CHANGELOG.md has **zero** SHA references (the brainstorm's assumption was wrong). `docs/plans/` has SHA refs but moves out to private repo per Q1 — accept staleness there (internal artifacts; SHA history is meaningful at the private-repo level). `docs/solutions/` has 104 SHA references across 50 files. Source-of-truth for SHA cleanup is `grep -rE "commit \`[0-9a-f]{7,40}\`" docs/solutions/` — every match needs the old SHA mapped to its post-rewrite equivalent.

### KD-8 — Public Surface DRAFT audit + GHA expression-injection audit are mandatory pre-push gates

Per `[[public-surface-draft-discipline-source-audit-2026-05-12]]` and `[[github-actions-expression-injection-env-block-mitigation-2026-05-13]]`: both audits must complete before the first public push. The Public Surface DRAFT audit catches drift between the README table and the actual public API surface (D6f added R6 promotion + R9b mechanisms that may not be fully reflected). The GHA expression-injection audit catches a security vector that becomes externally exploitable the moment the repo is public.

### KD-9 — buf relationship framing: parity-tracking at the lint subcommand only; zero runtime overlap; explicit non-affiliation

The 100+ references to buf across README + CHANGELOG + `src/` are descriptive nominative-fair-use under US trademark law (we identify buf to describe parity), and buf is Apache 2.0 (no attribution requirement for non-redistribution use). Risk surface is low but the relationship is currently implicit. Add an Acknowledgments section to README that:

1. Names buf as a comprehensive protobuf toolkit (lint, format, breaking-change detection, codegen, BSR, Connect, protovalidate) — NOT just a "Go ecosystem tool" (the casual framing is wrong; buf is language-agnostic in use)
2. Specifies the narrow overlap honestly: `protokit lint` ↔ `buf lint` (heavy parity); `protokit compat` ↔ `buf breaking` (different framing — protokit ships 4 named profiles + pluggable rule-pack API); `protokit diff` and `protokit.formatters` plugin API have no buf equivalent
3. Explicitly enumerates what protokit does NOT replicate: `buf format`, `buf generate`, `buf push`, BSR, Connect, protovalidate
4. Closes the "do we secretly depend on Buf-authored runtimes?" question explicitly: zero runtime-library overlap (verified empirically — protokit uses Google's official `protobuf` Python library; no `connect-python`, no `protovalidate-python`, no BSR client)
5. Trademark hygiene: explicit "not affiliated with or endorsed by Buf Technologies, Inc."
6. Notes the optional buf install (`brew install buf`) for cross-verifying parity-test output, and that the parity test suite skips cleanly without buf installed (verified: 1 pass + 18 skip when buf absent)
7. Notes buf is open source under Apache 2.0

**Canonical draft text** (lives in U4's implementation; landed at the README's natural location near the bottom):

```markdown
## Acknowledgments

`protokit lint` tracks rule-set parity with [`buf lint`](https://buf.build/product/cli),
the lint subcommand of the [buf](https://buf.build/) CLI by
[Buf Technologies, Inc.](https://buf.build/) — a comprehensive protobuf
tooling suite covering lint, formatting, breaking-change detection,
code generation, the Buf Schema Registry, and the Connect RPC
framework. protokit is an independent project, not affiliated with
or endorsed by Buf Technologies.

The functional overlap is intentionally narrow:

- **`protokit lint` ↔ `buf lint`**: closely tracked. `protokit lint`
  matches 26 of 26 buf v1.69.0 BASIC rules, with deliberate
  divergences where Python-protobuf-developer ergonomics differ
  (see the [Schema Linting](#schema-linting) section's positioning
  statement).
- **`protokit compat` ↔ `buf breaking`**: both detect schema
  compatibility breaks, with different framing — protokit ships four
  named profiles (`WIRE`, `CONSUMER_SAFE`, `PRODUCER_SAFE`, `STRICT`)
  and a pluggable Python rule-pack API.
- **`protokit diff`**: binary protobuf message diffing — no equivalent
  in buf.
- **Everything else buf provides** (`buf format`, `buf generate`,
  `buf push`, the Buf Schema Registry, Connect, protovalidate, etc.):
  protokit does not replicate.

protokit uses Google's official `protobuf` Python library at runtime
and does not depend on any Buf-authored Python package. The `buf` CLI
itself is optional — install via `brew install buf` to cross-verify
protokit's lint output against buf's reference implementation. The
parity test suite (`tests/parity/`) uses an installed `buf` binary
when available and skips cleanly when not.

`buf` is open source under Apache 2.0.
```

This framing is the working text; the implementing agent may make minor wording adjustments but must preserve: the comprehensive-toolkit characterization (not Go-ecosystem framing), the narrow-overlap claims with correctly-named buf subcommands, the runtime-library independence note, the trademark non-affiliation clarifier, and the Apache 2.0 mention.

---

## Output Structure

The plan adds these new artifacts to the repo:

```
protokit/                                       # public repo (renamed from local-only)
├── LICENSE                                     # NEW: MIT license file
├── .gitignore                                  # UPDATED: add internal-doc exclusions
├── pyproject.toml                              # UPDATED: authors, urls, classifiers, scrub
├── README.md                                   # UPDATED: selective scrub, Obsidian link removed
├── CONTRIBUTING.md                             # UPDATED: AI workflow paragraph, D6b U4 scrub
├── CHANGELOG.md                                # (unchanged - no SHA refs, already clean)
├── docs/
│   └── solutions/                              # UPDATED: 104 SHA refs + 4 absolute paths fixed
├── src/protokit/                               # UPDATED: 22 files, ~632 milestone refs scrubbed
├── tests/                                      # UPDATED: 2 presence-ratchet test substrings
└── .github/workflows/
    ├── ci.yml                                  # UPDATED: header note removed, inline scrub, GHA audit
    └── buf-release-watch.yml                   # (unchanged)
```

And these are removed from the public repo (moved to `marc-chiesa/protokit-internal` private repo):

```
docs/brainstorms/                               # 19 files, 888KB
docs/plans/                                     # 19 files, 1.4MB
TODOS.md                                        # 608 lines (post-ship monitoring lives here)
CLAUDE.md                                       # 72 lines (skill routing for personal workflow)
CHANGELOG-DRAFT.md                              # 11 lines (workflow staging file)
```

---

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification.*

```
Pre-push state:                          Post-publish state:
~~~~~~~~~~~~~~~                          ~~~~~~~~~~~~~~~~~~~~

local main @ 828a6c3                    github.com/marc-chiesa/protokit
├── 233 commits                          ├── 233 commits (rewritten)
│   ├── Author: mchiesa@gmail.com (232)  │   └── Author: <user-id>+marc-chiesa@users.noreply.github.com
│   └── Author: marc@Marcs-MBP (1)       │
├── docs/                                ├── docs/
│   ├── brainstorms/ (888K, in-repo)    │   └── solutions/ (only; in-repo)
│   ├── plans/ (1.4M, in-repo)          │
│   ├── solutions/ (1.7M, in-repo)      │
│   └── (internal milestone refs)        │   (cleaned references)
├── src/ (21 files, ~632 milestone refs) ├── src/ (cleaned, descriptive prose)
├── pyproject.toml (placeholder URL)    ├── pyproject.toml (real URL, full metadata)
├── (no LICENSE)                         ├── LICENSE (MIT)
└── (no public URL)                      └── Public + tag v0.7.0

                                         pypi.org/project/protokit/0.7.0/
                                         └── pip install protokit (works)

                                         marc-chiesa/protokit-internal (PRIVATE)
                                         ├── docs/brainstorms/
                                         ├── docs/plans/
                                         ├── TODOS.md
                                         ├── CLAUDE.md
                                         └── CHANGELOG-DRAFT.md
```

**Critical sequencing constraint**: history rewrite (Phase A) must precede SHA cleanup (Phase B) — otherwise SHA references would point at SHAs about to change. Docs move (Phase D) should precede final src/ scrub commits (Phase C) ONLY IF the src/ scrub rewrites path references to docs/brainstorms/ paths; alternatively, the src/ scrub can drop path refs proactively and the docs move happens whenever. Recommended order keeps src/ scrub agnostic to docs move timing.

---

## Implementation Units

### Phase A — Git history PII rewrite

### U1. `git filter-repo` PII rewrite

**Goal:** Rewrite all 233 commits to use the GitHub noreply email for the Author/Committer fields. Fixes 232 commits attributed to `mchiesa@gmail.com` and 1 commit attributed to `marc@Marcs-MacBook-Pro.local` (the initial 2026-04-12 commit). `Co-Authored-By:` trailers in commit message bodies remain intact (filter-repo's `--email-callback` only touches Author/Committer fields, not trailers).

**Requirements:** Q7, KD-1, KD-2

**Dependencies:** None (load-bearing assumption: verify `git remote -v` empty + `git reflog --all | grep -i "push\|origin"` empty BEFORE running)

**Files:**
- Modify: every commit's Author + Committer fields (no source-file modifications)

**Approach:**

1. **Find GitHub user ID** for the noreply email format: `curl -s https://api.github.com/users/<username> | grep '"id"'`. Format: `<id>+<username>@users.noreply.github.com`.
2. **Configure git going forward** so future commits anonymized: `git config --global user.email "<id>+marc-chiesa@users.noreply.github.com"`.
3. **Install `git-filter-repo`** if absent: `pip install git-filter-repo` (or `brew install git-filter-repo`).
4. **Backup-clone-first per KD-2**: `git clone /Users/marc/projects/python_message_differencer /tmp/protokit-rewrite-test`. The clone inherits an `origin` remote pointing at the source repo, which `git filter-repo` refuses to rewrite without `--force`. Either run `cd /tmp/protokit-rewrite-test && git remote remove origin` immediately after the clone, OR pass `--force` to the filter-repo invocation in the backup clone. (The working-repo apply at step 6 has no remote yet — `git remote -v` is empty — so `--force` is not needed there.)
5. **Apply rewrite in the backup clone** with `--email-callback`:
   ```python
   if email in (b"mchiesa@gmail.com", b"marc@Marcs-MacBook-Pro.local"):
       return b"<id>+marc-chiesa@users.noreply.github.com"
   return email
   ```
6. **Verify** in backup clone: `git log --format="%ae %ce" --all | sort -u` returns ONLY the noreply email; `git log --format="%(trailers:key=Co-Authored-By,valueonly)" | grep -oE "<[^>]+>" | sort -u` returns ONLY `<noreply@anthropic.com>`.
7. **Apply to working repo** once backup clone verified clean.

**Patterns to follow:** Brainstorm Q7 section has the exact callback Python and command sequence.

**Test scenarios:**

*Verification (after rewrite, before any subsequent unit):*
- `git log --format="%ae %ce" --all | sort -u` shows only the noreply email (no gmail, no hostname).
- `git log --format="%(trailers:key=Co-Authored-By,valueonly)" | grep -oE "<[^>]+>" | sort -u` shows only `<noreply@anthropic.com>` (trailers intact).
- **`git log --format="%B" --all | grep -iE "mchiesa@gmail\.com|marc@Marcs-MacBook-Pro\.local"` returns zero matches** (commit message bodies are clean — `--email-callback` only touches Author/Committer fields, so any gmail or hostname appearance in a message body would survive the rewrite). Pre-rewrite check confirmed clean; verify post-rewrite to close the assumption gap.
- `git log --oneline | wc -l` shows 233 commits (count preserved — no commits dropped).
- `git status` shows clean working tree.
- `pytest -x` passes (2345 tests + 7 skipped) — no test depends on commit SHAs.

**Verification:** All 4 verification commands above return expected results. If any verification fails, restore from backup (`/tmp/protokit-rewrite-test` is read-only reference) and diagnose before applying again.

---

### Phase B — Post-rewrite content reconciliation

### U2. SHA reference cleanup in `docs/solutions/` + absolute-path leak fix

**Goal:** Update all 104 SHA references across 50 docs/solutions/ files to point to post-rewrite SHAs using `git filter-repo`'s auto-generated `commit-map` artifact. Additionally fix all `/Users/marc/...` absolute-path leaks (enumeration step gates the file list — verified-known of 4 leaks in 2 files; pre-enumerate to confirm scope). CHANGELOG.md has zero SHA refs (verified) — no action there.

**Requirements:** Q7 follow-on, KD-7, R-ext-6, R-ext-10 (commit-map approach)

**Dependencies:** U1 (history rewrite must complete first; `.git/filter-repo/commit-map` file is the input to U2)

**Files:**
- Modify: 50 files in `docs/solutions/` with SHA references (enumerated via `grep -rl "commit \`[0-9a-f]\{7,40\}\`" docs/solutions/`)
- Modify: every file surfaced by the pre-enumeration step 1 below (verified-known: 2 files under `docs/solutions/best-practices/` — `pureposixpath-for-proto-descriptor-file-stem-2026-05-12.md` + `rule-pack-extension-ssot-rule-ids-and-test-class-naming-2026-05-12.md`)

**Approach:**

1. **Pre-enumeration step (PL-006 — both classes of leaks before editing begins)**: run `grep -rE "/Users/marc" . --exclude-dir=.git --exclude-dir=dist --exclude-dir=.venv --exclude-dir=.context --exclude-dir=node_modules` to enumerate ALL absolute-path leaks across the repo. Categorize hits by destination:
   - `docs/solutions/*` — fix in this unit (verified-known: 2 files, 4 lines)
   - `docs/brainstorms/*` / `docs/plans/*` / `TODOS.md` / `CLAUDE.md` / `CHANGELOG-DRAFT.md` — moves to private repo in U9; accept staleness there (internal artifacts)
   - `src/*` / `tests/*` — should not exist; flag and fix in U6-U8 if surfaced
   - `.github/workflows/*` — flag and fix in U10 if surfaced
   - Any other public-repo file — flag now, fix here or surface as a separate fix
2. **Build the SHA mapping from `.git/filter-repo/commit-map`** (FEAS-2/ADV-1 — convergent 2-reviewer correction): U1's `git filter-repo` invocation auto-writes `.git/filter-repo/commit-map` to BOTH the backup clone (`/tmp/protokit-rewrite-test/.git/filter-repo/commit-map`) and the working repo. The file format is one line per commit: `<old_sha> <new_sha>`. Read the file from the working repo; build a Python dict keyed on the first 7 chars of `old_sha` (since most references use short SHAs); also build dicts for 8-char and 10-char abbreviations for any references that used longer abbreviations. (Use `git rev-parse --short <old_sha>` to derive the canonical short form per repo `core.abbrev` setting if needed.)
3. **Mechanical find-and-replace** across the 50 files: for each SHA reference matching `\`[0-9a-f]{7,40}\`` in a docs/solutions/ file, look up the old SHA in the mapping dict, replace with the new SHA. Per `[[ruff-fix-scope-discipline-pass-diff-files-explicitly-2026-05-21]]`, scope replacements explicitly to the 50 enumerated files; do NOT use broad path patterns like `find docs/ -name '*.md'`.
4. **Absolute-path fix**: replace `/Users/marc/projects/python_message_differencer/...` with relative paths (or rephrase to drop the path entirely when it's not load-bearing) in each file the pre-enumeration surfaced under `docs/solutions/`.
5. **Verification (independent of editing process — passes the proxy-independence test from `[[test-proxy-signal-suppressed-by-mechanism-under-test-2026-05-25]]`)**:
   - `grep -rE "commit \`[0-9a-f]{7,40}\`" docs/solutions/` should match the SAME lines as before cleanup (count preserved); each match's SHA must now exist in the rewritten history (`git rev-parse <sha>` succeeds for each — would fail loudly on a stale ref).
   - `grep -rE "/Users/marc" docs/solutions/` returns zero matches.
   - If the pre-enumeration step surfaced absolute-path leaks in other locations, verify those were either fixed (public-repo files) or accepted-as-staleness (private-repo-bound files).

**Patterns to follow:**
- `[[ruff-fix-scope-discipline-pass-diff-files-explicitly-2026-05-21]]` — scope replacements to enumerated file list, not broad path patterns
- `[[test-proxy-signal-suppressed-by-mechanism-under-test-2026-05-25]]` — verification must be independent of the editing process; the grep gate catches the case where the mechanism (find-and-replace) silently misses some SHAs
- `git filter-repo` documentation for `commit-map` format and location

**Test scenarios:**

*Happy path:*
- After cleanup, sample 5 random docs/solutions/ files containing SHA refs. For each cited SHA, `git rev-parse <sha>` succeeds (returns the full SHA).
- `grep -rE "/Users/marc" docs/solutions/` returns zero matches.
- The pre-enumeration step (1) was executed and its output was categorized before any editing began.

*Edge cases:*
- A SHA referenced in docs/solutions/ that doesn't appear in `commit-map` (the commit existed before U1's rewrite but was somehow dropped — extremely unlikely with email-callback-only rewrite, but possible if filter-repo expansion ever broadens) — flag and investigate before proceeding. The mapping dict's `KeyError` is the load-bearing signal.
- A SHA reference that uses a length not in the mapping dicts (e.g., 12-char abbreviation) — extend the dicts to cover that length and re-run.
- Pre-enumeration surfaces absolute-path leaks in unexpected locations (e.g., a fixture file in tests/) — fix before proceeding.

**Verification:** All happy-path checks pass. `pytest -x` still passes (no test reads docs/solutions/ for SHA content). The `commit-map` file is preserved in the working repo (not deleted) for any post-publish re-mapping if needed.

---

### U3. `pyproject.toml` polish + `LICENSE` file

**Goal:** Bring `pyproject.toml` to PyPI-publish quality (complete authors, additional `[project.urls]`, scrub milestone comments). Create `LICENSE` file at repo root.

**Requirements:** Q5, R-ext-1

**Dependencies:** U1 (must use new noreply email for `authors`)

**Files:**
- Modify: `pyproject.toml`
- Create: `LICENSE` (repo root)

**Approach:**

1. **Update `[project]` `authors`**: `{ name = "Marc Chiesa", email = "<id>+marc-chiesa@users.noreply.github.com" }` (use the noreply email from U1's git config).
2. **Update `[project.urls]` Repository**: `https://github.com/marc-chiesa/protokit` (real personal-account URL).
3. **Add `[project.urls]` Changelog**: `https://github.com/marc-chiesa/protokit/blob/main/CHANGELOG.md`.
4. **Add `[project.urls]` Documentation**: `https://github.com/marc-chiesa/protokit#readme` (until a docs site exists).
5. **Ship as PEP 561 typed package**: create `src/protokit/py.typed` (empty marker file) AND add `"Typing :: Typed"` to `classifiers`. Decision rationale: protokit already has strict mypy gating (`tests/test_static_analysis.py::test_mypy_strict_clean_on_gated_paths`) and comprehensive type annotations on the public surface. Shipping as typed gives downstream Python users `mypy` / IDE type-checking on the protokit API at near-zero ongoing cost. **Per scope-guardian F3: removed from U10's "optional" list — this is a definite decision made in U3, not deferred.**
6. **Scrub milestone comments** in `[tool.pytest.ini_options]` markers block and `[dev]` extra. Rewrite as descriptive prose (e.g., `# 'slow' marker — perf-smoke gate` instead of `# D5 R23a: register the 'slow' marker...`).
7. **Create `LICENSE` file** at repo root with MIT license text and copyright line `Copyright (c) 2026 Marc Chiesa`. Use the canonical MIT template; do not invent variants.

**Patterns to follow:**
- PyPI metadata conventions: see any well-published Python project's pyproject.toml (e.g., `pydantic`, `httpx`).
- MIT license template: SPDX `MIT` text exactly.

**Test scenarios:**

*Happy path:*
- `python -c "import tomllib; t = tomllib.load(open('pyproject.toml', 'rb')); assert t['project']['authors'][0]['email'].endswith('@users.noreply.github.com')"` succeeds.
- `LICENSE` file exists at repo root and contains "MIT License" + copyright line.
- `grep -E "D[0-9][a-z]+|KD-[0-9]|R[0-9]+[a-z]?" pyproject.toml` returns zero matches in the scrubbed sections (`[tool.pytest.ini_options]` markers, `[dev]` extra). [Outside-scope refs in other comments may stay if they're version-anchored.]

*Verification:*
- `uv build` runs without errors (sanity check that pyproject.toml is still valid).
- `twine check dist/*` shows no warnings about missing license file.

**Verification:** All three test scenarios pass. `pyproject.toml` validates with `python -m tomllib`.

---

### Phase C — Public-facing file polish (in-repo)

### U4. README scrub + Public Surface DRAFT source audit + buf Acknowledgments section

**Goal:** Strip the Obsidian-style link at README:1046. Selectively scrub pure-breadcrumb milestone references; keep version-anchored milestone refs in upgrade-notes / migration-recipe sections. Run Public Surface DRAFT source audit per `[[public-surface-draft-discipline-source-audit-2026-05-12]]` to verify the table reflects D6f-added surface (R6 promotion + R9b mechanisms). Add an Acknowledgments section that accurately characterizes the relationship with buf (parity-tracking at the lint subcommand only; zero runtime-library overlap; explicit non-affiliation per nominative-fair-use trademark hygiene).

**Requirements:** Q1 (README in-repo), R-ext-2, R-ext-7, R-ext-9 (buf attribution), KD-5, KD-8, KD-9 (buf relationship framing)

**Dependencies:** None (independent of U1-U3)

**Files:**
- Modify: `README.md`

**Approach:**

1. **Strip the Obsidian link at line 1046**: rewrite `per [[closed-literal-discriminator-bump-trigger-2026-05-17]]` as descriptive prose (e.g., `per the closed-Literal-discriminator bump policy`).
2. **Selective scrub of milestone codes**: walk through the ~40 occurrences. For each:
   - In upgrade-notes / migration-recipe / version-history sections: KEEP if the `D6X`/`R[N]` token serves as a version anchor or migration-recipe identifier
   - In other sections (e.g., schema linting intro, profile descriptions): REWRITE as descriptive prose
3. **Public Surface DRAFT source audit**:
   - `dataclasses.fields(LintFinding)` → cross-check fields enumerated in README's DRAFT table
   - Grep `@click.option` in `src/protokit/schema/lint/cli.py` → verify all CLI flags in the table (especially R9b additions: `--disable-rule`, `--enable-rule`)
   - Grep `_LINT_ERROR_CODES` in `src/protokit/schema/lint/_cli_utils.py` → verify all error codes in the table (especially R9b additions: `no-rules-after-disable`, `cli-option-invalid`)
   - Any drift gets fixed in the DRAFT table.
4. **Add an Acknowledgments section** to the README (near the bottom, after the Output Formatters section or in a natural location). The section accurately characterizes the relationship with buf:
   - Names buf as a comprehensive protobuf toolkit (lint, format, breaking-change detection, codegen, BSR, Connect, protovalidate) — not just a "Go ecosystem tool"
   - Specifies the narrow overlap: `protokit lint` ↔ `buf lint` (heavy parity), `protokit compat` ↔ `buf breaking` (different framing), `protokit diff` and `protokit.formatters` plugin API have no buf equivalent
   - Explicitly enumerates what protokit does NOT replicate (format, generate, push, BSR, Connect, protovalidate)
   - Notes zero runtime-library overlap: protokit uses Google's official `protobuf` Python library; no Buf-authored Python packages
   - Trademark hygiene: explicit "not affiliated with or endorsed by Buf Technologies, Inc."
   - Optional buf install note: `brew install buf` to cross-verify; parity tests skip cleanly when buf is absent
   - Notes buf is Apache 2.0
   - Approximate length: 25-30 lines. See the brainstorm's KD-9 for the canonical draft text the planner produced and the user revised.

**Patterns to follow:**
- `[[stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12]]` triage rubric applies to the README selective scrub
- The Public Surface DRAFT learning has the exact source audit checklist
- KD-9 (this plan) carries the canonical Acknowledgments draft text

**Test scenarios:**

*Happy path:*
- `grep -E "\[\[.*-202[0-9]" README.md` returns zero matches (no Obsidian-style links).
- Sample 5 upgrade-notes sections after scrub; version anchors (`0.6.0 D6e R4b`) remain readable as version references.
- Public Surface DRAFT table includes `--disable-rule`, `--enable-rule` flags and `no-rules-after-disable`, `cli-option-invalid` error codes (R9b additions).
- `grep -E "^## Acknowledgments" README.md` returns one match (section exists).
- Acknowledgments section contains the substrings: `"buf lint"`, `"Buf Technologies"`, `"not affiliated"`, `"Apache 2.0"`, `"brew install buf"`.

*Verification:*
- A user reading README L1046's surrounding context can understand what "closed-Literal-discriminator bump policy" means from prose alone (no Obsidian-link cross-reference needed).
- README still renders cleanly in GitHub's markdown preview.
- The Acknowledgments section frames buf as a comprehensive toolkit (not just "Go ecosystem"), names the narrow overlap explicitly, and clarifies protokit's runtime-library independence.

**Verification:** Above checks pass.

---

### U5. CONTRIBUTING.md update (AI workflow paragraph + `D6b U4` scrub + buf-is-optional clarifier)

**Goal:** Add the Q6 AI-workflow paragraph (revised per ce-doc-review PL-002 to lead with the operational fact rather than the workflow characterization). Rewrite the one `D6b U4` milestone reference at line 24. Add a one-line clarifier that buf is parity-test-only (not a build/run dependency) per KD-9. Optionally generalize the hardcoded `v1.69.0` reference.

**Requirements:** Q6, R-ext-4, R-ext-9 (the CONTRIBUTING.md one-liner portion)

**Dependencies:** None

**Files:**
- Modify: `CONTRIBUTING.md`

**Approach:**

1. **Add AI-workflow paragraph** at a natural location (e.g., before or after "Setup" section). Per ce-doc-review PL-002, lead with the operational fact rather than the workflow characterization:

   > "Contributions may credit AI tools via `Co-Authored-By:` trailers in commit messages. You are responsible for correctness and license compliance of everything you submit, regardless of tooling used."

   (Replaces the brainstorm Q6's original wording — "Development uses AI-assisted workflows; substantive AI contributions are credited via `Co-Authored-By:` git trailers. Contributors are welcome to use any tooling but should review and own their submissions." — which the product-lens review flagged as the disclosure-for-disclosure's-sake framing the brainstorm Q6 was trying to avoid.)
2. **Scrub `D6b U4`** at line 24: rewrite `the D6b U4 buf smoke regression gate` to `the buf smoke regression gate` (the milestone designator adds no value to an external contributor).
3. **Add a one-line clarifier** to the "Tests that require `buf`" section confirming buf is parity-test-only (not a build/run dependency). Example wording near the section opener: "**Note**: `buf` is a parity-test-only optional dependency; `protokit` itself has no buf runtime requirement and `pip install protokit` does not require buf. Parity tests skip cleanly when buf is absent." This complements the README Acknowledgments section (KD-9 / U4) for contributors who land on CONTRIBUTING.md directly.
4. **Optional**: rewrite hardcoded `v1.69.0` references to point at `_BUF_PARITY_PIN` in `src/protokit/schema/lint/cli.py` (the canonical source of the pin). This decouples CONTRIBUTING.md from version drift.

**Patterns to follow:**
- Q6 brainstorm decision wording for the AI paragraph (operational, not philosophical; no apologetic tone), revised per ce-doc-review PL-002 finding.
- KD-9 framing for the buf-is-optional clarifier.

**Test scenarios:**

*Happy path:*
- `grep -E "D[0-9][a-z]+ U[0-9]" CONTRIBUTING.md` returns zero matches.
- The AI workflow paragraph leads with "Contributions may credit..." (operational fact), not "Development uses..." (workflow characterization).
- The "Tests that require `buf`" section has the buf-is-optional clarifier (parity-test-only; no runtime dependency).

*Verification:*
- An external contributor reading CONTRIBUTING.md cold can complete the setup + run tests without needing to look up `D6b U4`.
- A reader landing on CONTRIBUTING.md without first reading README understands buf is optional.

**Verification:** Above checks pass.

---

### U6. src/ comment scrub — Cluster A (heavy hitters: `_config.py` + `cli.py`)

**Goal:** Hand-edit the two largest milestone-ref-bearing src/ files. Strip `[[xxx-with-date]]` Obsidian-link notation; rewrite `D6X UY KZ`, `KD-N`, `R[N]b` references as descriptive prose; preserve actual technical content the comments were conveying.

**Requirements:** Q2, KD-3

**Dependencies:** None (independent of U1-U5)

**Files:**
- Modify: `src/protokit/schema/lint/_config.py` (~118 milestone-ref lines)
- Modify: `src/protokit/schema/lint/cli.py` (~88 milestone-ref lines)

**Approach:**

Per `[[stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12]]` two-pass discipline:

1. **Pass 1 (verb-pattern)**: grep `src/protokit/schema/lint/_config.py` and `src/protokit/schema/lint/cli.py` for verb patterns indicating present-tense / forward-looking references: `until D[0-9]`, `will land`, `arrives in U`, `per \[\[`, etc.
2. **Pass 2 (bare delivery-label)**: grep for `D[0-9][a-z]+` (e.g., `D6f`, `D6e`).
3. **For each hit, apply triage**:
   - Past-tense historical references (`shipped in D6a`) — leave (they're audit trail)
   - Present-tense forward references — REWRITE
   - `[[xxx-with-date]]` Obsidian links — REWRITE or DELETE (replace with descriptive prose or with a `docs/solutions/` filename reference if cross-link is genuinely useful)
   - `D6X UY KZ` milestone codes that are NOT version-anchored — REWRITE
   - `R[N]` requirement designators that are NOT canonical feature names (per KD-4) — REWRITE
4. **Preserve technical content**: the comment's underlying meaning stays; only the milestone-jargon prefix changes.
5. **Verify completion**: re-run both passes; expected zero hits in `src/protokit/schema/lint/_config.py` and `src/protokit/schema/lint/cli.py` for the rewrite-eligible patterns.

**Patterns to follow:** `[[stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12]]` is the governing learning.

**Test scenarios:**

*Happy path:*
- `grep -E "\[\[.*-202[0-9]" src/protokit/schema/lint/_config.py src/protokit/schema/lint/cli.py` returns zero matches.
- `grep -E "D6[a-f] U[0-9]" src/protokit/schema/lint/_config.py src/protokit/schema/lint/cli.py` returns zero matches (or only matches where `D6X` is a version anchor in a docstring — judgment call per file).
- The rewritten comments still convey the underlying technical content. Sample 5 rewritten lines; for each, the WHY is preserved.

*Verification:*
- `pytest tests/schema/lint/_config/ tests/schema/lint/cli/ -x` passes (no test depends on these comment substrings).
- `ruff check src/protokit/schema/lint/_config.py src/protokit/schema/lint/cli.py` clean.
- `mypy --strict src/protokit/schema/lint/_config.py src/protokit/schema/lint/cli.py` clean.

**Verification:** Above checks pass. Per `[[test-proxy-signal-suppressed-by-mechanism-under-test-2026-05-25]]`: the grep verification is structurally independent of the editing process (grep would fire if any Obsidian link survived; visual spot-check is NOT acceptable as sole completion signal).

---

### U7. src/ comment scrub — Cluster B (public surface: `model.py` + `engine.py` + `rules/__init__.py`) + atomic presence-ratchet test updates

**Goal:** Hand-edit the public-surface src/ files. CRITICAL: this cluster contains the substrings pinned by two presence-ratchet tests (`test_uxd_philosophy_principle_presence_ratchet.py` pins `"D6e KD-1: protokit-UX overrides buf-parity..."` in `rules/__init__.py`; `test_builtin_packs.py` pins `"R9b per-rule disable surface"` in `rules/__init__.py`). Per KD-3 + KD-4, the src/ scrub and the test substring updates land atomically in this same commit.

**Requirements:** Q2, R-ext-5, KD-3, KD-4

**Dependencies:** None (parallel-safe with U6, U8)

**Files:**
- Modify: `src/protokit/schema/lint/model.py` (~63 milestone-ref lines)
- Modify: `src/protokit/schema/lint/engine.py` (~66 milestone-ref lines)
- Modify: `src/protokit/schema/lint/rules/__init__.py` (~31 milestone-ref lines)
- Modify: `tests/test_uxd_philosophy_principle_presence_ratchet.py` (update pinned substring atomic with src/ scrub)
- Modify: `tests/schema/lint/test_builtin_packs.py` (verify pinned substring; per KD-4, `R9b per-rule disable surface` is canonical and stays)

**Approach:**

1. **Same two-pass discipline as U6** for the 3 src/ files.
2. **Special handling for ratchet-pinned substrings**:
   - `"D6e KD-1: protokit-UX overrides buf-parity..."` in `rules/__init__.py` docstring: rewrite as e.g., `"UX philosophy: protokit-UX overrides buf-parity; proto2-specific strict rules ship in proto2-strict."` Update `tests/test_uxd_philosophy_principle_presence_ratchet.py` substring to match (drop `"D6e KD-1: "` prefix).
   - `"R9b per-rule disable surface"` in `rules/__init__.py` docstring: KEEP — per KD-4, `R9b` is the canonical feature name (not a milestone designator to strip). The test ratchet stays as-is.
3. **Verify** the 2 presence-ratchet tests still pass after the src/ + test substring updates land together.

**Patterns to follow:**
- `[[presence-ratchet-pin-canonical-not-local-form-2026-05-23]]` — substring pins should be canonical user-facing phrases, not internal-marker phrases
- `[[stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12]]` — the governing rule
- KD-4 — `R9b` as canonical feature name decision

**Test scenarios:**

*Happy path:*
- `grep -E "\[\[.*-202[0-9]" src/protokit/schema/lint/{model.py,engine.py,rules/__init__.py}` returns zero matches.
- `pytest tests/test_uxd_philosophy_principle_presence_ratchet.py tests/schema/lint/test_builtin_packs.py -x` passes.
- `R9b per-rule disable surface` substring still present verbatim in `src/protokit/schema/lint/rules/__init__.py` (per KD-4).

*Edge cases:*
- Any other test that has substring-pin dependencies on these 3 files surfaces during `pytest -x` — investigate before completing.

*Verification:*
- `pytest tests/ -x` passes end-to-end (2345 tests + 7 skipped).
- `ruff check` + `mypy --strict` clean on the 3 src/ files.
- **Atomicity check (COH-4 fix — KD-3 made testable, not just asserted)**: `git show --name-only HEAD` after the U7 commit returns a file list containing BOTH `src/protokit/schema/lint/rules/__init__.py` AND `tests/test_uxd_philosophy_principle_presence_ratchet.py` (and the other 2 src/ files in this cluster). If these are split across two commits, the bisect-safety claim is violated; redo as a single squash before merging to main.

**Verification:** Above checks pass. The atomicity check is now testable rather than asserted-only — `git show --name-only HEAD` is the load-bearing gate.

---

### U8. src/ comment scrub — Cluster C (remaining src/ files + `pyproject.toml` markers + `.github/workflows/ci.yml` inline comments)

**Goal:** Hand-edit the remaining 17 src/ files (smaller milestone-ref counts each, including 3 files surfaced by Phase 1 research — `rules/naming.py`, `rules/imports.py`, `rules/enum.py` — which carry `docs/plans/` path references that become dangling after U9 moves docs/plans/ out). Also scrub inline milestone comments in `.github/workflows/ci.yml` (but PRESERVE the parity-job branch-protection advisory, which is load-bearing public documentation). pyproject.toml's milestone comments are handled entirely in U3 (see F4).

**Requirements:** Q2, R-ext-1 (pyproject part), R-ext-3 (ci.yml part), KD-3

**Dependencies:** None (parallel-safe with U6, U7)

**Files:**
- Modify: `src/protokit/schema/lint/rules/package.py` (~34 lines)
- Modify: `src/protokit/formatters/_builtin_lint.py` (~27 lines)
- Modify: `src/protokit/schema/lint/_cli_utils.py` (~25 lines)
- Modify: `src/protokit/schema/lint/_custom_rules.py` (~17 lines)
- Modify: `src/protokit/schema/lint/rules/options/deprecated_replacement.py` (~16 lines)
- Modify: `src/protokit/schema/lint/rules/options/field_behavior.py` (~14 lines)
- Modify: `src/protokit/schema/lint/rules/package_same.py` (~11 lines)
- Modify: `src/protokit/schema/compile.py` (~9 lines)
- Modify: `src/protokit/schema/lint/rules/options/_comments.py` (~6 lines)
- Modify: `src/protokit/schema/lint/rules/field.py` (~6 lines)
- Modify: `src/protokit/schema/lint/rules/file.py` (~5 lines)
- Modify: `src/protokit/schema/lint/_extension_access.py` (~5 lines)
- Modify: `src/protokit/_cli_utils.py` (~4 lines)
- Modify: `src/protokit/formatters/_builtin_compat.py` (~1 line)
- Modify: `src/protokit/schema/lint/rules/naming.py` (~3 lines including `docs/plans/` refs) — added per Phase 1 research finding (FEAS-3)
- Modify: `src/protokit/schema/lint/rules/imports.py` (~1 line including `docs/plans/` ref) — added per Phase 1 research finding (FEAS-3)
- Modify: `src/protokit/schema/lint/rules/enum.py` (~1 line including `docs/plans/` ref) — added per Phase 1 research finding (FEAS-3)
- Modify: `.github/workflows/ci.yml` (inline milestone comments only; preserve parity-job advisory at lines 155-167)

**Approach:** Same two-pass discipline as U6/U7. Cluster C is smaller per-file, mostly mechanical.

**Patterns to follow:** Same as U6.

**Test scenarios:**

*Happy path:*
- `grep -rE "\[\[.*-202[0-9]" src/` returns zero matches (across ALL src/ files now).
- `grep -E "D[0-9][a-z]+ U[0-9]|KD-[0-9]+|R[0-9]+[a-z]?" src/protokit/formatters/_builtin_lint.py | head` shows zero rewrite-eligible patterns.
- The ci.yml parity-job advisory at lines 155-167 is preserved verbatim.

*Verification:*
- `pytest tests/ -x` passes.
- `ruff check src/ tests/` + `mypy --strict <gated paths>` clean.
- `python -c "import tomllib; tomllib.load(open('pyproject.toml', 'rb'))"` succeeds (toml is valid).
- `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"` succeeds (yaml is valid).

**Verification:** Above checks pass.

---

### Phase D — Internal docs move

### U9. Move internal docs to private repo + `.gitignore` updates

**Goal:** Move `docs/brainstorms/`, `docs/plans/`, `TODOS.md`, `CLAUDE.md`, `CHANGELOG-DRAFT.md` to a new private repo `marc-chiesa/protokit-internal`. Update `.gitignore` in the public repo to prevent accidental re-add.

**Requirements:** Q1, R-ext-8

**Dependencies:** U6-U8 (src/ scrub should complete first so any docstring path references to `docs/brainstorms/` or `docs/plans/` get rewritten in U6-U8, leaving U9 to just move the files cleanly)

**Files:**
- Delete from public repo (move to private): `docs/brainstorms/` (entire directory), `docs/plans/` (entire directory), `TODOS.md`, `CLAUDE.md`, `CHANGELOG-DRAFT.md`
- Modify: `.gitignore` (add `TODOS.md`, `CLAUDE.md`, `CHANGELOG-DRAFT.md`, `docs/brainstorms/`, `docs/plans/`)
- Create: `marc-chiesa/protokit-internal` private repo (external — GitHub action, not file)

**Approach:**

1. **Verify `CHANGELOG-DRAFT.md` is stub-only** per `[[dormant-code-changelog-draft-staging-delivery-boundary-2026-05-17]]`. The brainstorm noted it's 11 lines; confirm those 11 lines are the "D7+ staging" header only, no staged D6f+ content. If real content exists, fold to `CHANGELOG.md` first (this would be a sub-step before move).
2. **Create the private repo**: `gh repo create marc-chiesa/protokit-internal --private --description "Internal workflow artifacts for protokit: brainstorms, plans, TODOs, agent skills routing, CHANGELOG staging."`.
3. **Initialize the private repo locally** and add the moved files. Push to the new repo.
4. **In the public repo**, delete the 5 paths via `git rm -r docs/brainstorms/ docs/plans/ TODOS.md CLAUDE.md CHANGELOG-DRAFT.md`.
5. **Update `.gitignore`** in the public repo to add the 5 path patterns. This prevents accidental re-add via `git add .`.
6. **Verify** the public repo no longer contains these paths.

**Patterns to follow:**
- `[[dormant-code-changelog-draft-staging-delivery-boundary-2026-05-17]]` for the CHANGELOG-DRAFT.md verification
- `.gitignore` already excludes `.context/`; follow that pattern for the new entries

**Test scenarios:**

*Happy path:*
- `ls docs/brainstorms/ docs/plans/ TODOS.md CLAUDE.md CHANGELOG-DRAFT.md 2>&1` returns "No such file or directory" for all in the public repo.
- `cat .gitignore | grep -E "TODOS.md|CLAUDE.md|CHANGELOG-DRAFT.md|docs/brainstorms|docs/plans"` returns 5 matches.
- `cd /tmp/test-private-repo && gh repo clone marc-chiesa/protokit-internal && ls protokit-internal/docs/brainstorms/` shows the 19 brainstorm files (verifies private repo has the content).

*Edge cases:*
- Any src/ docstring still referencing `docs/brainstorms/foo.md` or `docs/plans/bar.md` paths → those references should have been rewritten in U6-U8; verify by `grep -rE "docs/(brainstorms|plans)" src/` returns zero matches.

*Verification:*
- `pytest -x` passes (no test reads any of the moved files).
- `git log --diff-filter=D --name-only HEAD~1..HEAD` (after this unit's commit) shows the 5 deletions.

**Verification:** Above checks pass.

---

### Phase E — Pre-push verification

### U10. Security audit + CI verification + ci.yml header note removal

**Goal:** Pre-push verification gate. Remove the embarrassing "this workflow lands as dormant config — the repo has no configured GitHub remote at the time of writing" header note in `.github/workflows/ci.yml`. Run `gitleaks` to verify no secrets entered history. Confirm GHA expression-injection audit returns zero findings (run during planning by scope-guardian F2 + security-lens — verified zero `${{ }}` interpolations in any `run:` block across both workflows; demoted from "structured concern" to "verification grep step" per F2). Verify CI workflow runs cleanly end-to-end against the full test suite.

**Requirements:** R-ext-3, Q7 ongoing defense, KD-8

**Dependencies:** U1-U9 (all in-repo cleanup must complete first)

**Files:**
- Modify: `.github/workflows/ci.yml` (remove the dormant-config note at lines 23-27; preserve matrix-axes rationale at lines 1-22; the inline milestone comments throughout the workflow were already scrubbed in U8, this unit handles the header note + the GHA expression-injection audit)

**Approach:**

1. **Install gitleaks**: `brew install gitleaks` (or platform equivalent).
2. **Run gitleaks**: `gitleaks detect --source . --log-opts="--all" --redact`. Expected: zero findings (already verified by prior scan in brainstorm, but re-verify after the rewrite + cleanup).
3. **Remove ci.yml dormant-config header note** at lines 23-27 (the "this workflow lands as dormant config — the repo has no configured GitHub remote at the time of writing" paragraph specifically). PRESERVE lines 1-22 — they contain useful matrix-axes rationale (why 3.10+3.12, the has_protoxy axis explanation, the apt-protoc version note) that's worth keeping for contributors. Update any forward-looking language in the preserved header to past-tense / present-tense as needed.
4. **GHA expression-injection audit (verification grep — zero findings expected per F2 pre-verify)**: `grep -E '\$\{\{ github\.|steps\.[a-z_]+\.outputs' .github/workflows/*.yml` filtered to `run:` blocks. Already verified zero findings during planning (scope-guardian F2): all `${{ }}` expressions in protokit's workflows are in `with:`, `if:`, and step `name:` fields — none in `run:` blocks. Re-run as a sanity check; if any new interpolations have appeared since planning (very unlikely — `.github/workflows/*.yml` are not touched between planning and U10 in this plan), refactor per the learning. Expected result: zero matches, audit passes in <30 seconds.
5. **CI workflow dry-run**: optionally run `act` locally (if installed) to simulate CI; otherwise rely on the first public-push CI run to validate (U11).
6. ~~Optionally add `py.typed` marker~~ — REMOVED per scope-guardian F3. The decision (ship as typed) is made in U3 (creates the marker + adds the classifier). U10 does NOT touch `py.typed`. This resolves the prior logical contradiction where U3 conditionally classifier-tagged on existing-py.typed while U10 optionally created py.typed.

**Patterns to follow:**
- `[[github-actions-expression-injection-env-block-mitigation-2026-05-13]]` — full audit checklist
- gitleaks default rule set

**Test scenarios:**

*Happy path:*
- `gitleaks detect --source . --log-opts="--all" --redact` returns zero findings.
- `head -30 .github/workflows/ci.yml` shows no "dormant config" or "no remote at time of writing" phrasing.
- GHA expression-injection audit: every `${{ }}` in `run:` blocks goes through `env:` (no inline interpolation).

*Verification:*
- `pytest -x` still passes.
- `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"` succeeds.

**Verification:** Above checks pass. This is the last unit before the one-way-door public push.

---

### Phase F — Public push

### U11. Create public repo + push + tag + enable secret scanning

**Goal:** Create `github.com/marc-chiesa/protokit` (personal-account, public). Push local `main` to the new remote. Tag `v0.7.0` and push the tag. Enable GitHub secret scanning on the now-public repo.

**Requirements:** Q3, Q7 ongoing defense

**Dependencies:** U10 (all pre-push verification must complete)

**Files:**
- Modify: none (this unit is GitHub state changes + git push, no local file edits)

**Approach:**

1. **Pre-flight: verify the target GitHub repo does NOT already exist** to avoid a `gh repo create` failure at the most stressful moment: `gh repo view marc-chiesa/protokit 2>/dev/null && { echo "ERROR: repo already exists; investigate before proceeding"; exit 1; } || echo "OK: name available"`.
2. **Create public repo**: `gh repo create marc-chiesa/protokit --public --description "Python toolkit for Protocol Buffers: structural message diffing and schema compatibility checking." --homepage "https://pypi.org/project/protokit/"`. (The homepage URL won't resolve until U12 publishes; that's fine — it'll work once published.)
3. **Push main**: `git push --set-upstream origin main`. First public push moment.
4. **Tag**: `git tag -a v0.7.0 -m "0.7.0 — R6 promotion to ERROR + R9b per-rule disable"`.
5. **Push tags**: `git push origin v0.7.0`.
6. **Enable GitHub secret scanning** via the repo Settings → Code security & analysis → Secret scanning → Enable. (CLI alternative: `gh api -X PATCH /repos/marc-chiesa/protokit -f "security_and_analysis[secret_scanning][status]=enabled"`. Note: `gh api -X PUT /repos/.../automated-security-fixes` is a DIFFERENT feature — Dependabot automated security fixes — not secret scanning. Use the PATCH endpoint above for secret scanning specifically, or the web UI for safety.)
7. **Verify**: `gh repo view marc-chiesa/protokit` shows the repo with 233 commits, `v0.7.0` tag, MIT license detected from the LICENSE file.
8. **Verify CI workflow runs** on the first public push: `gh run list --repo marc-chiesa/protokit --limit 1` shows a run in progress or completed cleanly. If failures, debug before proceeding to U12.

**Patterns to follow:** Standard `gh repo create` + `git push` flow. Modern noreply email pattern already configured per U1.

**Test scenarios:**

*Happy path:*
- `curl -s -o /dev/null -w "%{http_code}" https://github.com/marc-chiesa/protokit` returns `200`.
- `git ls-remote --tags origin` shows `refs/tags/v0.7.0` pointing at the same SHA as local `main`.
- `gh run list --repo marc-chiesa/protokit --limit 1` shows a successful CI run.
- GitHub repo view shows MIT license detected.

*Edge cases:*
- CI first run fails on something repo-context-dependent (e.g., a hardcoded path that worked locally). Debug, fix in a hotfix commit, re-push.
- GitHub secret scanning catches anything (very unlikely given U10's gitleaks pass, but possible if gitleaks missed something) — investigate and fix before U12.

*Verification:*
- Public repo is browsable, README renders, LICENSE detected, v0.7.0 tag visible.
- CI workflow run is green.

**Verification:** Above checks pass. **This is the most significant one-way-door action in the plan** — the public repo and its first commits become permanently visible.

---

### Phase G — PyPI publish

### U12. TestPyPI dry-run + real PyPI publish

**Goal:** Build the distribution, validate metadata, publish to TestPyPI for dry-run verification, then publish to real PyPI. Verify `pip install protokit` from a clean venv works.

**Requirements:** Q5

**Dependencies:** U3 (LICENSE + pyproject.toml polish), U11 (public repo exists for `[project.urls]` to resolve)

**Files:**
- Generate: `dist/protokit-0.7.0-py3-none-any.whl`
- Generate: `dist/protokit-0.7.0.tar.gz`
- Create: PyPI account + project-scoped API token (external — PyPI web UI, not file)

**Approach:**

1. **PyPI account setup** (if not already done): create account at `pypi.org`, enable 2FA, create a **project-scoped API token** for `protokit` (scope = upload-only to the `protokit` project, NOT user-scoped). Create a SEPARATE TestPyPI account + 2FA + project-scoped token (TestPyPI is a fully separate database; tokens are not shared).
2. **Token delivery mechanism (Security F4)**: pass the token via `UV_PUBLISH_TOKEN` environment variable in-session — do NOT write to `~/.pypirc` (plaintext credential file is a leakage vector; ends up in home-directory backups, gets synced via dotfile-management tools, can be accidentally committed if `$HOME` is a git repo). Recommended invocation:
   ```bash
   # Paste token at the prompt — bash 'read -rs' does NOT save to shell history
   read -rs UV_PUBLISH_TOKEN && export UV_PUBLISH_TOKEN
   # Then run uv publish — the env var auto-applies; unset after.
   ```
   After publish completes, `unset UV_PUBLISH_TOKEN`. Do NOT pass tokens on the command line (visible in `ps`, `~/.bash_history`, `.zsh_history`). Apply the same discipline for TestPyPI's separate token.
3. **Build**: `uv build` (or `python -m build`). Produces `dist/protokit-0.7.0-py3-none-any.whl` and `dist/protokit-0.7.0.tar.gz`.
4. **Validate metadata**: `twine check dist/*`. Expected: no warnings (LICENSE present, README is valid markdown, all required metadata fields populated).
5. **Publish to TestPyPI** (with the TestPyPI token via `UV_PUBLISH_TOKEN`): `uv publish --publish-url https://test.pypi.org/legacy/` (or `twine upload --repository testpypi dist/*` if preferred).
6. **Clean-venv install from TestPyPI**: create a fresh venv, `pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ protokit==0.7.0`. The `--extra-index-url` fallback is required because `tomli` (a Python <3.11 runtime dep) is not on TestPyPI — without it, install fails on Python 3.10. Verify `python -c "import protokit; print(protokit.__version__)"` works.
7. **Smoke-test the CLI**: run `protokit --version` and `protokit --help` from the test venv; verify they execute correctly.
8. **Publish to real PyPI** (swap `UV_PUBLISH_TOKEN` to the real-PyPI token first — they are SEPARATE tokens for SEPARATE accounts): `unset UV_PUBLISH_TOKEN && read -rs UV_PUBLISH_TOKEN && export UV_PUBLISH_TOKEN && uv publish`.
9. **Unset the token immediately after publish**: `unset UV_PUBLISH_TOKEN`. Verify with `env | grep UV_PUBLISH_TOKEN` (should return empty).
10. **Verify**: visit `https://pypi.org/project/protokit/0.7.0/`. Verify the page renders, README displays, LICENSE shows as MIT, classifiers correct, project URLs all clickable.
11. **Final clean-venv install from real PyPI**: `pip install protokit==0.7.0`. Smoke-test CLI again.
12. **Token cleanup**: do NOT write the real-PyPI token anywhere persistent. If you must store it for future publishes (e.g., for 0.7.1 patch release), store in your OS keychain (macOS Keychain Access, 1Password, etc.) — never in `~/.pypirc`. Future releases (0.7.1+) will use GitHub Actions trusted publishing per Q5 deferred scope; no persistent token storage needed long-term.

**Patterns to follow:** Standard PyPI publish flow per `twine`/`uv` documentation.

**Test scenarios:**

*Happy path:*
- `twine check dist/*` returns "PASSED" for both wheel and sdist.
- TestPyPI install + smoke-test succeeds.
- Real PyPI publish succeeds; `pypi.org/project/protokit/0.7.0/` resolves with rendered README.
- `pip install protokit==0.7.0` from clean venv succeeds; `protokit --version` shows `protokit 0.7.0`.

*Edge cases:*
- `twine check` warns about README rendering — fix README markdown before publishing to real PyPI.
- TestPyPI install fails (typically a metadata issue) — fix locally, rebuild, retry TestPyPI before real PyPI.
- PyPI rejects the upload (name conflict, etc.) — investigate; the user already confirmed `protokit` is available, but verify at upload time.

*Verification:*
- All happy-path checks pass.
- The PyPI project page shows the right information for the right consumer.

**Verification:** Above checks pass. **Second one-way-door action**: once published to real PyPI, the version is permanent (PyPI does not allow re-uploads of the same version). If a critical issue is discovered post-publish, the remediation is a new patch release, not a republish.

---

### Phase H — Post-publish

**~~U13~~ — REMOVED as an Implementation Unit per scope-guardian F1 + product-lens PL-003.** Post-ship monitoring is operational work, not an implementation unit (modifies zero files in the public repo). Its content is now covered in the **Operational / Rollout Notes** section's "Post-publish operational schedule" subsection (see below), with the PL-003 framing fix incorporated: distinguish AUDIENCE IDENTIFICATION (potential-audience communities to monitor, appropriate at publish time even with zero existing users) from ADOPTION MONITORING (week 4/6 checks of PyPI velocity + GitHub issue/star activity). The negative trigger for the 0.7.1 demotion patch is tightened: requires at minimum **one confirmed user report** of R6 breakage, not just a download-ratio inversion (which would false-positive on a normal-no-adoption pattern for a brand-new release).

**Net plan shape:** 12 Implementation Units across 7 phases (U1-U12). The "Phase H — Post-publish" header is preserved to mark the operational boundary, but its work is documented as operational schedule, not as an IU.

---

## System-Wide Impact

- **Interaction graph**: history rewrite (U1) is the load-bearing dependency for U2 (SHA cleanup, which maps old→new SHAs) and U3 (which uses the new noreply email in `authors`). Public-facing file polish (U4-U8) is independent of U1 and can proceed in parallel with U1-U3. U9 (internal docs move) depends on U6-U8 completing the src/ scrub so that docstring path references to `docs/brainstorms/` and `docs/plans/` are rewritten before the files actually move. U10 (security + CI verify) depends on all prior in-repo cleanup. U11 (public push) is the one-way door — everything before must complete. U12 (PyPI publish) depends on U3 (metadata + LICENSE) + U11 (public repo exists for project URLs). U13 (post-publish monitoring) follows U12.

- **Error propagation**: `git filter-repo` failure mid-run can leave the working repo in an inconsistent state — KD-2 backup-clone-first mitigates. PyPI publish failure on real PyPI requires a new patch version (PyPI does not allow re-upload of the same version) — TestPyPI dry-run (U12) is the mitigation.

- **State lifecycle risks**: the rewritten git history is permanent once pushed (U11). If a PII leak survives rewrite, the only remediation is force-push + history rewrite again BEFORE anyone clones — once cloned by external parties (even one star/fork), the old history persists in their clones. U10's gitleaks verification is the last gate before this risk becomes irreversible.

- **API surface parity**: Public Surface DRAFT in README must reflect the post-D6f surface (R6 promoted, R9b mechanisms added). U4's source audit catches any drift.

- **Integration coverage**: U6-U8's src/ scrub must not break tests. The two presence-ratchet tests (`test_uxd_philosophy_principle_presence_ratchet.py`, `test_builtin_packs.py`) are the highest-risk integration points — U7's atomic scrub + test update is the discipline.

- **Unchanged invariants**:
  - All 2345 tests + 7 skipped continue to pass at each unit's completion.
  - `ruff check` + `mypy --strict` clean on gated paths at each unit's completion.
  - `docs/solutions/` learnings remain in-repo (Q1 decision).
  - `Co-Authored-By:` commit trailers remain intact through the filter-repo rewrite.
  - CHANGELOG.md content stays unchanged (no SHA refs to clean, no milestone-code scrub planned per Scope Boundaries).
  - The `protokit` Python import name stays the same (only PyPI distribution and GitHub URL are public-facing-new).

---

## Risk Analysis & Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `git filter-repo` rewrites to wrong email due to callback typo | Low | High (PII leak persists; remediation = rewrite again before push) | KD-2: backup-clone-first; verify in backup before applying to working repo. Verification command: `git log --format="%ae %ce" --all \| sort -u` must show ONLY the noreply email. |
| Repository was actually pushed at some point (assumption falsified) | Very low | High (every "no external references" argument collapses; rewrite is invasive) | Pre-flight check: `git remote -v` must return empty AND `git reflog --all \| grep -i "push\|origin"` must return empty AND no GitHub repo with this name exists. ALL THREE must be empty. If any one isn't, fall back to partial remediation per Q7 fallback (accept gmail in history). |
| SHA cleanup pass misses references and stale SHAs remain in `docs/solutions/` | Medium | Low-Medium (broken cross-references in published docs) | U2 verification: re-grep `commit \`[0-9a-f]{7,40}\`` after cleanup; for each match, `git rev-parse` must succeed. |
| Presence-ratchet tests break atomic with U7 due to substring mismatch | Medium | Low (CI fails immediately; obvious) | U7 verification: `pytest tests/test_uxd_philosophy_principle_presence_ratchet.py tests/schema/lint/test_builtin_packs.py -x` must pass before U7 is complete. Atomic commit ensures bisectability. |
| Public push happens before all PII / metadata cleanup is done | Low | Very High (PII leak goes live; first-impression damaged) | Unit dependencies: U11 depends on U10; U10 depends on U1-U9. Sequencing prevents accidental early push. |
| `pip install protokit` from clean venv fails post-publish | Low | High (immediate user-visible failure on day-zero) | U12 verification: TestPyPI dry-run + clean-venv install BEFORE real PyPI publish. |
| GitHub Actions expression injection vulnerability in `ci.yml` | Low | High (security incident on a public repo) | U10: `[[github-actions-expression-injection-env-block-mitigation-2026-05-13]]` audit. |
| `CHANGELOG-DRAFT.md` has real staged content that gets moved to private repo without folding | Medium | Low (public CHANGELOG.md missing some D6f content) | U9 pre-step: verify `CHANGELOG-DRAFT.md` is stub-only; if real content exists, fold to `CHANGELOG.md` first. |
| R9b ratchet substring decision (KD-4) turns out wrong — `R9b` becomes embarrassing | Low | Low (cosmetic; user-visible feature name) | KD-4 documents the decision rationale. Reversible in any future release. |
| Post-publish: silent-pinning is the dominant response to R6 promotion (no GitHub issues, low PyPI download rate) | Medium | Medium (R6 promotion is unfalsifiable without active monitoring; D6f plan KD-8 + `[[post-ship-adoption-monitoring-pre-1.0-breaking-default-change-2026-05-19]]` flagged this) | U13 multi-signal monitoring per the same learning. If negative trigger fires, cut 0.7.1 demotion patch within 1 week. |
| First-public-push CI run fails on something repo-context-dependent | Medium | Low (debug + fix + re-push; visible but not catastrophic) | U10 local CI verification (or `act` dry-run); accept the small risk that first push reveals environmental gaps. |

---

## Phased Delivery

The 13 Implementation Units split into 8 phases by dependency cluster:

| Phase | Units | Concern | Risk Level |
|-------|-------|---------|------------|
| **A** — History rewrite | U1 | PII fix (one-way locally; reversible via backup until applied) | High (must succeed cleanly) |
| **B** — Post-rewrite cleanup | U2, U3 | SHA refs + repo metadata + LICENSE | Low (mechanical) |
| **C** — Public-facing polish | U4, U5, U6, U7, U8 | README + CONTRIBUTING + src/ scrub (3 clusters) | Medium (large surface; atomic ratchet-test update in U7 is critical) |
| **D** — Internal docs move | U9 | Move to private repo + .gitignore | Low (mechanical) |
| **E** — Pre-push verification | U10 | gitleaks + GHA audit + ci.yml header | Medium (final gate before one-way door) |
| **F** — Public push | U11 | Create repo + push + tag + enable secret scanning | **Very High (one-way door)** |
| **G** — PyPI publish | U12 | TestPyPI dry-run + real PyPI publish | **Very High (one-way door — PyPI doesn't allow re-uploads)** |
| **H** — Post-publish | U13 | Monitoring setup (in private repo) | Medium (operational; window 4-6 weeks) |

**Phase commit boundaries**: each unit is one atomic commit (or one atomic commit + ratchet-test update for U7). Phases A-E land as separate commits on local `main`. Phase F (U11) pushes the cumulative state to the public remote. Phases G + H are out-of-tree operations (PyPI; private repo).

**Phase pause/resume points**: between any two phases, the working repo is in a consistent state and the user can pause for review/break. The critical "no pause" boundary is **U1 backup → U1 apply** (do not pause between backup verification and apply; the working repo is unchanged but uncommitted-feeling state shouldn't linger).

---

## Operational / Rollout Notes

**Pre-push readiness checklist** (must all be ✓ before U11 fires):

- [ ] U1: `git log --format="%ae %ce" --all | sort -u` shows only noreply email
- [ ] U2: `grep -rE "commit \`[0-9a-f]{7,40}\`" docs/solutions/` matches all map to extant SHAs; `grep -rE "/Users/marc" docs/solutions/` returns zero
- [ ] U3: `LICENSE` file exists; `twine check dist/*` (run after `uv build`) shows no warnings
- [ ] U4: README has zero `[[xxx-with-date]]` Obsidian links; Public Surface DRAFT reflects R6 + R9b additions
- [ ] U5: CONTRIBUTING.md has AI workflow paragraph; zero `D6X UY` references
- [ ] U6-U8: `grep -rE "\[\[.*-202[0-9]" src/` returns zero matches; presence-ratchet tests pass
- [ ] U9: 5 internal-doc paths gone from public repo; .gitignore updated
- [ ] U10: `gitleaks detect --source . --log-opts="--all" --redact` returns zero findings; GHA expression-injection audit clean
- [ ] All units: `pytest -x` passes (2345 + 7 skipped); `ruff check` + `mypy --strict` clean on gated paths
- [ ] `git remote -v` is STILL empty (no remote has been added yet; U11 adds it)

**Post-publish operational schedule** (post-U12; replaces the removed U13 IU per F1 + PL-003):

Two distinct activities at different times:

- **AUDIENCE IDENTIFICATION (within 24 hours of `uv publish`)** — appropriate at publish time even with zero existing users. Fill in the `Post-ship monitoring (0.7.0)` section in the now-private `marc-chiesa/protokit-internal` repo's `TODOS.md`:
  - Release date (the actual date `uv publish` completed)
  - Week-4 date (release_date + 28 days) and week-6 date (release_date + 42 days)
  - **2-3 potential-audience communities** to monitor for organic reactions (NOT existing users — protokit has none yet). Realistic candidates: r/protobuf, protobuf community Discord, Python packaging Discourse, relevant `protokit-lint` GitHub topic page. Cold-outreach is NOT appropriate at publish time for a project with no prior users.
  - Bookmark PyPI download stats: `https://pypistats.org/packages/protokit`
  - Save GitHub issue search query: `is:issue R6 OR deprecated-replacement OR "deprecated-field-must-have"`
  - Set calendar reminders for week-4 and week-6 check dates
- **ADOPTION MONITORING (week 4 and week 6 checks)** — the actual signal-watching:
  - Review GitHub issues for R6-related reports (no issues + low download velocity = expected for a brand-new release with no audience yet; not a negative trigger by itself)
  - Check PyPI download velocity: is it growing? if yes, even slowly, that's positive adoption signal
  - Scan the 2-3 potential-audience communities for any mentions of protokit
  - Update the TODOS section with findings
- **Negative trigger for 0.7.1 demotion patch** (PL-003 framing fix — tighter than the original): **≥1 confirmed user report** of R6 breakage AND no usable demote-path in the published 5-path migration recipe. Download-ratio inversion alone is NOT a sufficient trigger for a brand-new release because no audience exists at week 6 to invert the ratio against. (For pre-1.0 libraries with existing audiences, download-ratio inversion IS a sufficient trigger per the learning; protokit's zero-prior-audience state changes the calculus.)
- **Post-monitoring-window** (after week 6, assuming no negative triggers): record the post-ship outcome as an institutional learning via `/ce-compound` — protokit's first public release + first PyPI publish + first post-ship-monitoring-window completion are all NEW territory worth documenting.

**Rollback / failure modes**:

- **U1 failure** (filter-repo produces wrong results, or — rarely — crashes mid-run): do NOT rely on `ORIG_HEAD`. `git filter-repo` (unlike `git filter-branch`) does not set `ORIG_HEAD` and is mostly atomic — the failure mode is "rewrite completed with wrong output" rather than "rewrite half-applied." Recovery procedure: `rm -rf .git && git clone /tmp/protokit-rewrite-test .` (or equivalent restore from the backup clone at `/tmp/protokit-rewrite-test`). Belt-and-suspenders: record `git rev-parse HEAD > /tmp/pre-rewrite-head.txt` BEFORE running U1 step 6 so the pre-rewrite SHA is recoverable from a file even if all other state is lost.
- **U10 secret-scan finding**: STOP. Investigate. If a real secret is in history, the rewrite must be redone with the secret redacted via filter-repo `--blob-callback` BEFORE the public push.
- **U11 push failure**: typically due to GitHub repo not yet created or auth issues. Easy to fix; not a true rollback.
- **U12 TestPyPI failure**: don't publish to real PyPI; fix locally, rebuild, retry TestPyPI first.
- **U12 real PyPI failure post-upload**: PyPI doesn't allow re-uploads. The recovery is a 0.7.1 patch release with the fix. Pre-stage by knowing the next available version number.
- **Post-publish monitoring trigger fires** (negative signal per the Operational schedule above): the pre-staged 0.7.1 demotion patch (documented in the private `marc-chiesa/protokit-internal` repo's `TODOS.md`) lays out the rule-id flip; execute as a standalone D6g delivery.

**New territory documentation candidates** (post-execution `/ce-compound` opportunities):

- `pypi-publish-first-release-discipline-2026-XX-XX` — TestPyPI dry-run + clean-venv smoke-test + twine check + metadata-completeness checklist
- `git-filter-repo-pii-rewrite-pre-push-boundary-2026-XX-XX` — never-pushed assumption verification + backup-clone-first + email-callback discipline + SHA-reference cleanup pass
- `first-public-push-cleanup-sequence-2026-XX-XX` — the 8-phase pre-release cleanup as a reusable pattern (this plan itself becomes the source learning)
- `ai-disclosure-contributing-md-norm-2026-XX-XX` — operational AI workflow paragraph wording; commit-trailer-as-primary vs README-badge rationale

---

## Dependencies / Prerequisites

**Tools required (must be installed locally before plan execution begins):**

- `git` (any modern version)
- `git-filter-repo` — `pip install git-filter-repo` or `brew install git-filter-repo`
- `gh` (GitHub CLI) — for `gh repo create`, `gh repo clone`, etc.
- `uv` — for `uv build`, `uv publish`
- `twine` — for `twine check`; usually installed alongside `uv` or via `pip install twine`
- `gitleaks` — `brew install gitleaks`
- `curl` (system default) — for GitHub user-id lookup

**External accounts / setup required:**

- **GitHub account** (`marc-chiesa`) with permission to create public + private repos
- **GitHub user ID** known (lookup via `curl -s https://api.github.com/users/marc-chiesa | grep '"id"'`)
- **PyPI account** with 2FA enabled
- **PyPI project-scoped API token** for `protokit`
- **TestPyPI account** with 2FA + token (separate from real PyPI)

**Pre-flight verification (run before U1):**

```bash
# Confirm never-been-pushed assumption (load-bearing for Q7)
git remote -v          # MUST be empty
git reflog --all | grep -i "push\|origin"  # MUST be empty

# Verify tool availability
command -v git-filter-repo gh uv twine gitleaks curl  # MUST all resolve

# Verify GitHub access
gh auth status  # MUST show authenticated

# Verify PyPI name availability one more time (in case anything changed)
# (Note: `pip` may not be on PATH on Homebrew Python; use `python3 -m pip` or a curl alternative.)
python3 -m pip index versions protokit  # MUST return "No matching distribution" (i.e., not taken)
# Or, portable alternative without pip dependency:
# curl -sf https://pypi.org/pypi/protokit/json >/dev/null && echo "TAKEN" || echo "AVAILABLE"
```

If any of the above fails, fix before starting U1.

---

## References

- **Origin document**: `docs/brainstorms/2026-05-25-pre-release-cleanup-requirements.md`
- **D6f boundary commit** (current `main` HEAD): `828a6c3 feat(lint): D6f U3 — delivery boundary (0.7.0 release; KD-1 demonstration)`
- **Governing learnings** (cited inline in the plan):
  - `docs/solutions/best-practices/stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12.md` — governs U6, U7, U8 src/ scrub
  - `docs/solutions/best-practices/delivery-boundary-unit-commit-composition-2026-05-14.md` — governs commit shape
  - `docs/solutions/best-practices/dormant-code-changelog-draft-staging-delivery-boundary-2026-05-17.md` — governs U9 CHANGELOG-DRAFT verification
  - `docs/solutions/best-practices/pre-1.0-version-bump-as-communication-contract-2026-05-14.md` — governs version-bump communication
  - `docs/solutions/best-practices/public-surface-draft-discipline-source-audit-2026-05-12.md` — governs U4 source audit
  - `docs/solutions/best-practices/post-ship-adoption-monitoring-pre-1.0-breaking-default-change-2026-05-19.md` — governs U13 monitoring
  - `docs/solutions/best-practices/test-proxy-signal-suppressed-by-mechanism-under-test-2026-05-25.md` — applies to U6-U8 verification (grep, not visual spot-check)
  - `docs/solutions/security-issues/github-actions-expression-injection-env-block-mitigation-2026-05-13.md` — governs U10 GHA audit
  - `docs/solutions/best-practices/ruff-fix-scope-discipline-pass-diff-files-explicitly-2026-05-21.md` — governs U2 tooling scope
  - `docs/solutions/best-practices/presence-ratchet-pin-canonical-not-local-form-2026-05-23.md` — informs KD-4 R9b decision
- **D6f plan** (recently completed parent delivery): `docs/plans/2026-05-24-001-feat-d6f-r6-promotion-and-r9b-per-rule-disable-plan.md`
- **Plugin syntax note**: this plan uses post-2026-05-25 plugin syntax (`/ce-work`, `/ce-compound`, `/ce-code-review`) — colon-to-hyphen swap; `/ce:review` specifically renamed to `/ce-code-review`.
