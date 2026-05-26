---
title: "Pre-release cleanup + public-repo setup for protokit 0.7.0"
date: 2026-05-25
status: draft
scope: standard
---

# Pre-release cleanup + public-repo setup for protokit 0.7.0

## Background

protokit is locally at the 0.7.0 boundary commit (`828a6c3` on `main`), ready to push to a public remote and publish to PyPI. The development workflow has produced substantial in-repo artifacts (137 markdown files across `docs/brainstorms/`, `docs/plans/`, `docs/solutions/`; 22 of 52 `src/` files reference internal milestone codes like `D6f U2 KD-1` and `[[learning-with-date]]` notation) that are valuable for contributors using the same workflow but constitute noise — sometimes a comprehension wall — for the broader audience that arrives via PyPI or a GitHub search.

This brainstorm scopes the pre-release cleanup so the first-impression repo is what we want public, the remote setup is right the first time, and post-1.0 we're not paying carrying cost for retrofits.

## Goals

- **First-impression quality**: the GitHub repo a stranger lands on from PyPI should look like a professional library, not a workflow journal.
- **No misrepresentation, no over-disclosure**: AI involvement is disclosed where it's load-bearing (commit trailers) without performative gestures that trigger the discount-the-project reaction.
- **No security gaps in the first public push**: zero secrets in git history; no avoidable PII leakage.
- **Reversible decisions stay reversible**: prefer light choices that can be undone (configure noreply email, defer docs site) over heavy choices that aren't (rewrite 232 commits, ship a Sphinx site).
- **Right-sized cleanup for a pre-1.0 release**: don't gold-plate; ship 0.7.0 with the polish that materially affects the public experience, defer the rest.

## Non-goals

- Sphinx / MkDocs / Read the Docs site for the 0.7.0 release — README is comprehensive enough to ship as docs.
- Rewriting all 232 commits with personal-email history (invasive; marginal benefit).
- Scrubbing milestone refs from `tests/` (contributor-facing; lower-priority audience).
- A "Made with AI" badge or apologetic README disclosure paragraph (performative; triggers anti-AI discount reaction).
- Multi-repo split (separate `protokit-docs` repo, sub-projects under an org) — premature for 0.7.0.
- GitHub organization creation — `protokit` org name is taken; deferred until there's a concrete reason (see Q3).
- CI publish via trusted publishing on first release (acceptable to publish manually with API token; CI workflow can land later).

## Audience model

The user landing on the public repo has one of three paths, in expected frequency order:

1. **Read the README + use `pip install`** (most users). Never opens `src/`.
2. **Look at examples or CHANGELOG, then install** (next most). Maybe skims README sections.
3. **Hit an issue, dive into `src/` to verify they're using it correctly** (the failure mode that motivates this cleanup). This user encounters comments. If they hit a wall of `[[xxx-with-date-2026-xx-xx]]` and `D6f U2 KD-1` references that require internal context, they either give up or file a confused issue.

Contributors who want to use the same compound-engineering workflow are a separate, smaller audience served by `docs/solutions/` (kept in-repo) + CONTRIBUTING.md.

## Decisions

### Q1 — Repo content boundary: keep `docs/solutions/`, move the rest out

Tiered visibility, not all-or-nothing:

| Path | Current | Action | Rationale |
|---|---|---|---|
| `docs/solutions/` (99 files, 1.7 MB) | In-repo | **Keep in-repo** | Institutional knowledge, agent-discoverable via frontmatter, signals engineering rigor. Also serves as natural AI-workflow disclosure (see Q6). |
| `docs/brainstorms/` (19 files, 888 KB) | In-repo | **Move out** | Internal product reasoning; references milestone codes external readers won't grok; pure noise in a public repo. |
| `docs/plans/` (19 files, 1.4 MB) | In-repo | **Move out** | Internal implementation plans; same calculus as brainstorms. |
| `TODOS.md` (608 lines) | In-repo | **Move out** | Internal roadmap, `D6g+` backlog references, post-ship monitoring placeholders — all contributor-internal. |
| `CLAUDE.md` (72 lines) | In-repo | **Move out** | Skill routing for the personal `gstack`/`compound-engineering` workflow; not applicable to external contributors. |
| `CHANGELOG-DRAFT.md` (11 lines, staging) | In-repo | **Move out** | Workflow staging file; public users don't need to see "D7+ staging". |
| `CONTRIBUTING.md` (75 lines) | In-repo | **Keep**, lightly update | Already clean and contributor-focused; add a brief paragraph for AI workflow norms (see Q6). |
| `CHANGELOG.md` | In-repo | **Keep** | Public release history; load-bearing for users tracking changes. |
| `README.md` | In-repo | **Keep** | Effective single-page docs site. |

**Destination for the moved files**: a separate **private** GitHub repo (`marc-chiesa/protokit-internal` or similar) on the same personal account as the public repo. This keeps them recoverable, syncable across machines, version-controlled, and team-shareable when future collaborators arrive — without burdening the public repo. Local-only (`.git/info/exclude`) is rejected because it doesn't survive a fresh clone. If the project later moves to a GitHub org, the private repo can transfer alongside the public one.

**`.gitignore` updates** required after the move so accidental `git add docs/brainstorms/` doesn't silently re-add them.

### Q2 — Comment scrub: full hand-edit pass on `src/`, defer `tests/`

The scrub targets the debug-from-source path. Three sub-patterns and per-pattern policy:

| Pattern | Example | Policy in `src/` | Policy in `tests/` |
|---|---|---|---|
| `[[xxx-with-date-2026-xx-xx]]` Obsidian links | `per [[wire-format-schema-version-bump-contract-and-absence-semantic-2026-05-13]]` | **Delete or rewrite as descriptive prose** | Lower priority; can stay |
| `D6X UY KZ` milestone codes | `D6f U2 KD-1 sentinel pattern` | **Rewrite as descriptive prose** (e.g., "sentinel pattern for `"off"` interception at the coercion layer") | Leave; tests are contributor surface |
| `RN` / `RNb` requirement designators | `R9b precedence resolution` | **Rewrite** ("per-rule disable precedence") | Leave; planning artifact useful to contributors |

**Scope**: 22 `src/` files; `_config.py` alone has 174 such references. Estimated effort: 2-3 hours of careful editing.

**Discipline**: docstrings get priority over inline comments. Docstrings surface via IDE hover, `help()`, and any future autodoc tool — they're the cleanest reader path. Inline comments are lower priority (only seen by someone actually reading the file).

**What we preserve**: technical content the comment was conveying. The goal is "translate to language a stranger can read", not "strip information".

### Q3 — Remote: personal account `github.com/marc-chiesa/protokit`, defer org

**`github.com/protokit/protokit` is unavailable** — the `protokit` GitHub org is already taken (PyPI `protokit` IS available; the two namespaces are independent and don't have to match — `pip install Pillow` ↔ `github.com/python-pillow/Pillow` is the common precedent).

**Decision: ship 0.7.0 from personal account** (`github.com/marc-chiesa/protokit`), defer the org question until there's a concrete reason for one.

Reasoning:
- Adding "create a new GitHub org with a name I haven't decided yet" to the pre-0.7.0 cleanup list is scope creep against shipping
- Modern precedent: FastAPI was `tiangolo/fastapi` from 2018 until 2024 (years of community success) before transferring to `fastapi/fastapi`. Personal-account hosting is not a signal of "side project" in 2026 — many established libraries live there
- Reversible: `gh repo transfer marc-chiesa/protokit <new-org-name>` moves the repo to an org later. GitHub auto-redirects the old URL for ~1 year after transfer, so the migration is invisible to users
- Real triggers for moving to an org (any one suffices, none apply yet): a second related project lands and an umbrella makes sense; a collaborator needs org-level admin; an org name candidate becomes clearly the right choice

**If a future org move happens, naming options to revisit** (don't commit now):
- Author-umbrella pattern (`chiesa-labs`, `chiesa-dev`) — mirrors `encode`/`pallets`/`Textualize`; future-proofs for related projects
- Project-variant pattern (`protokit-py`, `protokit-labs`) — pairs with the project name; signals "this org hosts THE protokit"

**Companion fix**: `pyproject.toml` `[project.urls]` currently has `Repository = "https://github.com/marc/protokit"` — placeholder pointing at a non-existent user. Update to `https://github.com/marc-chiesa/protokit` alongside the version bump.

### Q4 — Documentation generation: defer the site, ship README-as-docs

For 0.7.0: **no docs site**. README is 1100+ lines, comprehensive, and self-contained. Adding a docs site to 0.7.0 scope is scope creep.

For the future (when we decide to add a site, likely 0.8.x or 1.0):

- **Recommend**: MkDocs Material + mkdocstrings, hosted on GitHub Pages
  - Markdown-first matches existing README/CHANGELOG/CONTRIBUTING style — no RST conversion needed
  - mkdocstrings extracts existing Google-style docstrings without rewrite
  - Material theme is the modern "looks professional out of the box" choice
  - GitHub Pages is free, tied to the repo, no third-party hosting decision
  - Setup ~30 minutes
- **Defer**: Sphinx + Read the Docs (heavier setup, RST format, third-party hosting) until versioned docs become important — typically post-1.0 when the API surface needs side-by-side comparison.

**Structural decision to make NOW**: keep docstrings clean (Google-style, no milestone refs — folded into Q2's scrub) so the future tool can extract them as-is.

### Q5 — PyPI registration: yes, with modern publish path

Pre-publish steps (in order):

1. **Check `protokit` name availability** on PyPI (`pip index versions protokit` or visit `pypi.org/project/protokit/`). If taken, decide on alternative distribution name (e.g., `protokit-toolkit`) while keeping `protokit` as the import name.
2. **Create PyPI account**, enable 2FA (now required for publishing accounts).
3. **Skip PyPI Organizations** — feature exists but overkill for a solo project. Publish under personal PyPI account.
4. **First release**: publish manually via `uv publish` (or `twine upload`) with a project-scoped API token. Acceptable for 0.7.0.
5. **Optional follow-up release**: set up trusted publishing via GitHub Actions OIDC for subsequent releases — no API tokens, better security, standard 2024+ practice. Can land in 0.7.1 or 0.8.0.

Pre-publish dry run (always worth it):

- `uv build` → produces `dist/protokit-0.7.0-py3-none-any.whl` + `protokit-0.7.0.tar.gz`
- `twine check dist/*` → validates metadata (catches missing LICENSE, malformed README, etc.)
- Publish to **TestPyPI** first (`uv publish --publish-url https://test.pypi.org/legacy/`), install from a clean venv via `pip install --index-url https://test.pypi.org/simple/ protokit==0.7.0` to verify install actually works
- Then publish to real PyPI

### Q6 — AI disclosure: three light layers, no performative gestures

Stay in the pragmatic middle: disclose where it's load-bearing, don't ceremonialize it.

| Layer | Action |
|---|---|
| **Commit trailers** | Keep existing `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` trailers on every commit. Auditable, permanent, machine-readable. This IS the primary disclosure. |
| **CONTRIBUTING.md** | Add ~2 sentences: "Development uses AI-assisted workflows; substantive AI contributions are credited via `Co-Authored-By:` git trailers. Contributors are welcome to use any tooling but should review and own their submissions." Sets norms for external PRs; operational, not philosophical. |
| **README** | **No disclosure paragraph, no badge.** The README's job is to tell users what the library does. Adding "Made with AI" doesn't help users evaluate code quality (they do that via code, tests, CHANGELOG) and WILL trigger the discount-the-project reaction from skeptics. |

**Q1↔Q6 connection**: keeping `docs/solutions/` in-repo (per Q1) provides the most honest disclosure of all — the artifacts themselves reference `ce:review`, `ce:compound`, and the institutional-learning naming convention. Anyone curious enough to look gets full transparency without a banner.

**Defensible truth**: 2345 tests, ce:review pre-landing on every commit, comprehensive CHANGELOG, full README, explicit commit attribution — those signals are the rigor headline. AI provenance is a footnote, not the lead.

### Q7 — Secret + PII scan: clean for secrets; full PII rewrite (no external references exist yet)

**Scan results**:

| Signal | Scope | Action |
|---|---|---|
| API keys / tokens / private keys / hardcoded paths | 0 matches across 233 commits | ✅ No action needed |
| Hostname-leaking author email (`marc@Marcs-MacBook-Pro.local`) | 1 commit (`9513542`, initial 2026-04-12 commit) | **Rewrite via `git filter-repo`** (same pass as gmail rewrite below) |
| Personal gmail (`mchiesa@gmail.com`) in author field | 232 commits | **Rewrite all 232 commits to noreply email via `git filter-repo`** — see rationale below |
| Co-author email (`noreply@anthropic.com`) | 222+ commits | ✅ Anonymous, fine. Untouched by the rewrite. |

**Why a full rewrite is the right call here (calculus depends on repo state):**

The standard "don't rewrite history" advice assumes external references exist — open PRs, issues, deploy artifacts, blog post links, collaborators' clones, CI runs against specific SHAs. **None of those apply here** — the repo has never been pushed to any remote. The standard downsides evaporate:

| Standard objection | Applies here? |
|---|---|
| Force-push needed to overwrite remote | ❌ no remote exists yet |
| Other people's clones become stale | ❌ no other clones exist |
| External SHA references break (PRs, issues, blog links, deploys) | ❌ no external references exist |
| CI re-runs against new SHAs | ❌ first public CI run hasn't happened |
| Open PRs need rebasing | ❌ no PRs |

**What still applies (the real cost): SHA references inside in-repo content become stale.** Specifically:
- `CHANGELOG.md` cites commits like `b8f0168`, `b74762c`, `cc15653` (D6f U2 / U1 anchors)
- `docs/solutions/*.md` learnings reference commits like `16b494f` (D6b U5), `b8f0168` (D6f U2), etc.
- Auto-memory files reference current SHAs for orientation

After the rewrite, those SHA references become stale. Remediation is a mechanical find-and-replace pass across ~10-15 files. Estimated effort: 1-2 hours.

**Net trade**: 1-2 hours of mechanical SHA cleanup buys complete PII remediation — no `mchiesa@gmail.com`, no `Marcs-MacBook-Pro.local`, anywhere in public history. The audit trail and per-commit `Co-Authored-By:` attribution (the Q6 disclosure mechanism) survive intact because `git filter-repo --email-callback` only touches Author/Committer fields, not commit message bodies.

**Concrete command**:

```bash
# Install if not already present
pip install git-filter-repo

# Find your GitHub user ID (so the noreply format is robust against username changes):
# curl -s https://api.github.com/users/<username> | grep '"id"'

# SAFETY: clone to a backup first and run the rewrite there to verify the result
git clone /Users/marc/projects/python_message_differencer /tmp/protokit-rewrite-test
cd /tmp/protokit-rewrite-test

# Rewrite all author/committer emails in one pass.
# Fixes BOTH the gmail (232 commits) AND the hostname-email commit (1 commit) at once.
git filter-repo --email-callback '
  if email in (b"mchiesa@gmail.com", b"marc@Marcs-MacBook-Pro.local"):
    return b"<user-id>+marc-chiesa@users.noreply.github.com"
  return email
'

# Verify: should show ONLY the noreply email (Anthropic noreply still appears
# as co-author in trailers, but author/committer fields are clean)
git log --format="%ae %ce" --all | sort -u

# If clean, apply to working repo
cd /Users/marc/projects/python_message_differencer
git filter-repo --email-callback '
  if email in (b"mchiesa@gmail.com", b"marc@Marcs-MacBook-Pro.local"):
    return b"<user-id>+marc-chiesa@users.noreply.github.com"
  return email
'
```

**SHA cleanup pass** (post-rewrite, before any push):

After the rewrite, walk through and update SHA references:
- `git log --format="%h %s" | head -20` — get the new SHAs for the recent commits
- Find references with `grep -rE "\b[0-9a-f]{7,40}\b" CHANGELOG.md docs/solutions/ docs/plans/ 2>/dev/null` (note: docs/plans/ moves out per Q1 — fix references there before the move, OR accept the staleness in the private repo)
- Replace each old SHA with the new SHA via Edit
- Auto-memory (`MEMORY.md`, `project_state.md`) is local and easy to refresh post-rewrite

**Ongoing defense (unchanged)**:

- Install `gitleaks` (`brew install gitleaks`); run `gitleaks detect --source . --redact` as a pre-push check. Optional pre-commit hook (~5 min setup) catches secrets before they enter history.
- Enable **GitHub secret scanning** on the public repo after first push (free for public repos; ~30 seconds to enable; warns automatically if anyone ever pushes a real secret).
- Configure git to use the noreply email globally going forward so the rewrite doesn't need to happen again: `git config --global user.email "<user-id>+marc-chiesa@users.noreply.github.com"`

## Related cleanup items (low-effort, fold into the same boundary)

- **`LICENSE` file at repo root** — `pyproject.toml` says `license = "MIT"` but no `LICENSE` file exists. Required by PyPI + good open-source practice. ~1 minute (copy the MIT template, add copyright line).
- **`.gitignore` updates** — after Q1 moves files out, add `TODOS.md`, `CLAUDE.md`, `CHANGELOG-DRAFT.md`, `docs/brainstorms/`, `docs/plans/` to `.gitignore` so accidental `git add` doesn't re-include them.
- **CI verification** — `.github/workflows/ci.yml` exists. Verify it runs cleanly end-to-end on push (this is the first time it'll run on a public repo against the full 2345-test suite).
- **GitHub repo settings on the new org** — branch protection on `main` (require PR review post-1.0; for solo pre-1.0, optional), issue templates, PR template, optional Code of Conduct + SECURITY.md. Light polish; ~30 minutes if you want the full setup.

## Sequencing

Roughly cheapest-first, with dependencies respected. **The history rewrite (steps 3-5) must happen BEFORE any in-repo SHA references are written or moved**, otherwise they'd reference SHAs that are about to change.

1. **PyPI name availability check** — if `protokit` is taken, decisions downstream change (e.g., the org name might not need to match anymore). Do this first; ~30 seconds.
2. **Find your GitHub user ID** for the noreply format (`curl -s https://api.github.com/users/<username> | grep '"id"'`). ~30 seconds.
3. **Configure git noreply email** going forward (`git config --global user.email "<user-id>+marc-chiesa@users.noreply.github.com"`). ~30 seconds. Future commits anonymized.
4. **Backup clone + dry-run the rewrite** in `/tmp/protokit-rewrite-test`. Verify `git log --format="%ae %ce" --all | sort -u` shows only the noreply email. ~5 minutes.
5. **Apply `git filter-repo --email-callback`** to the working repo. Rewrites all 233 commits (232 gmail + 1 hostname) to noreply in one pass. ~30 seconds.
6. **SHA reference cleanup pass** — mechanical find-and-replace across `CHANGELOG.md`, `docs/solutions/*.md`, auto-memory files. Old SHAs (pre-rewrite) → new SHAs (post-rewrite). The SHAs to map: walk `git log` to get the new SHAs, then `grep -rE "\b[0-9a-f]{7,40}\b" CHANGELOG.md docs/solutions/` to find references. ~1-2 hours.
7. **Create the public repo** at `github.com/marc-chiesa/protokit` (personal account; no new org needed). ~3 minutes via `gh repo create marc-chiesa/protokit --public --description "..."` or the GitHub web UI.
8. **Update `pyproject.toml`** `[project.urls]` Repository field to `https://github.com/marc-chiesa/protokit`. ~1 minute.
9. **Add `LICENSE` file** to repo root. ~1 minute.
10. **Move internal docs out** to a separate private repo (`marc-chiesa/protokit-internal` or similar). Update `.gitignore`. ~30 minutes total. NOTE: `docs/plans/` has SHA references too — either update them in place before the move, or accept staleness in the private repo (recommended: accept; they're internal artifacts).
11. **`src/` comment scrub** — hand-edit the 22 files. **The largest chunk: ~2-3 hours.** Tracked as its own /ce-work unit; can split per-file or per-pattern.
12. **CONTRIBUTING.md update** — add the AI workflow paragraph. ~2 minutes.
13. **Install `gitleaks` + pre-push secret check**. ~5 minutes.
14. **CI verify** — confirm `.github/workflows/ci.yml` runs cleanly. Variable.
15. **`uv build` + `twine check dist/*` + TestPyPI dry-run** + clean-venv install. ~15 minutes.
16. **`git push` to public org + `git tag v0.7.0` + `git push --tags`** — first public push moment.
17. **Enable GitHub secret scanning** on the now-public repo. ~30 seconds.
18. **`uv publish` to real PyPI**. ~5 minutes.
19. **Post-publish operational task** — fill in `TODOS.md` `Post-ship monitoring (0.7.0)` section with the actual release date + week-4/week-6 dates + outreach targets (per the existing D6f plan's KD-8 backstop discipline). NOTE: since `TODOS.md` moves out of the public repo per Q1, this fill-in happens in the private `marc-chiesa/protokit-internal` repo.

Total wall-clock: probably 5-8 hours focused work, spread over a session or two. The rewrite + SHA cleanup adds ~1-2 hours over the original estimate.

## Success criteria

The 0.7.0 release ships when ALL of the following hold:

- `pypi.org/project/protokit/0.7.0/` resolves and `pip install protokit` from a clean venv works
- `github.com/marc-chiesa/protokit` is public, has a clean README, a LICENSE file, and the version tag `v0.7.0`
- `git log --format="%ae %ce" --all | sort -u` shows ONLY the noreply email (no `mchiesa@gmail.com`, no `marc@Marcs-MacBook-Pro.local`) — full PII rewrite verified
- `git log --format="%(trailers:key=Co-Authored-By,valueonly)" | grep -oE "<[^>]+>" | sort -u` shows ONLY `<noreply@anthropic.com>` — Co-Authored-By trailers intact (rewrite touched only Author/Committer fields)
- `gitleaks detect --source .` returns zero findings (already true; verify again after the rewrite + scrub)
- A user opening any `src/` file does not encounter `[[xxx-with-date]]` Obsidian-link notation
- SHA references in `CHANGELOG.md` and `docs/solutions/*.md` point to the post-rewrite SHAs (no stale references)
- The `docs/brainstorms/`, `docs/plans/`, `TODOS.md`, `CLAUDE.md`, `CHANGELOG-DRAFT.md` artifacts are not visible in the public repo
- `docs/solutions/`, `CONTRIBUTING.md`, `CHANGELOG.md`, `README.md`, `LICENSE` ARE visible in the public repo
- CONTRIBUTING.md has the AI-workflow paragraph
- The post-ship monitoring section in the (now-private) `TODOS.md` has been filled in with actual release date + week-4/week-6 dates

## Dependencies / assumptions

- **Assumption**: `protokit` is available on PyPI. If not, distribution name changes, but the import name stays `protokit` (these are separable).
- **Assumption**: the user wants a separate private repo for internal docs (vs. moving to Notion / Obsidian / local-only). The private-repo path is most consistent with the developer-tools nature of the project and keeps a future contributor onboarding path open. If a knowledge-management tool is preferred, swap step 10's destination.
- **Assumption**: the repo has never been pushed to any remote — this is the load-bearing assumption for choosing full PII rewrite over partial remediation. **Verify before applying step 5**: `git remote -v` should show nothing (no `origin`), and no public clone, fork, or mirror exists anywhere. If this assumption turns out false (e.g., the repo was briefly pushed during an earlier experiment), fall back to the partial remediation path: configure noreply going forward, leave the 232 existing commits as-is, and accept the gmail exposure.
- **Assumption**: the SHA-cleanup pass (step 6) is acceptable as ~1-2 hours of mechanical work. If not, the alternative is to revert Q7 to partial remediation (accept gmail in history). The full-rewrite path is preferred because the alternative leaks personal email permanently into the very first public history.

## Open scope questions for planning

These don't need to be answered now, but planning should resolve them:

1. **Internal-docs destination**: private GitHub repo (default), Notion / Obsidian (workflow-incompatible), or local-only via `.git/info/exclude` (no cross-machine sync). Private repo is the recommended default.
2. **Comment-scrub commit shape**: single bulk-scrub commit, or per-file commits for git-blame archaeology? Single commit is faster; per-file preserves blame for the underlying code changes. Recommended: single commit with a thorough message summarizing the scrub policy applied.
3. **CI publish via trusted publishing**: ship in 0.7.0 or defer to 0.7.1? Recommended: defer; manual `uv publish` for 0.7.0 is fine, trusted-publishing setup is its own ~30-min unit.
4. **GitHub repo settings depth**: branch protection, issue templates, Code of Conduct, SECURITY.md — full pre-1.0 polish or minimum-viable? Recommended: minimum-viable for 0.7.0, add the rest pre-1.0.

## References

- D6f plan (parent delivery): `docs/plans/2026-05-24-001-feat-d6f-r6-promotion-and-r9b-per-rule-disable-plan.md`
- D6f boundary commit (current `main` HEAD): `828a6c3 feat(lint): D6f U3 — delivery boundary (0.7.0 release; KD-1 demonstration)`
- Post-ship monitoring discipline: `docs/solutions/best-practices/post-ship-adoption-monitoring-pre-1.0-breaking-default-change-2026-05-19.md`
- AI-disclosure landscape (community references, not in-repo): Apache Software Foundation generative-AI guidelines, Linux kernel mailing list discussions on AI-generated patches, FastAPI / Pydantic / Typer as examples of no-disclosure-by-default modern Python libraries
