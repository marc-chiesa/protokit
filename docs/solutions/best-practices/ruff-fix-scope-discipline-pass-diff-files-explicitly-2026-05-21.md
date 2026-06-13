---
title: "ruff --fix scope discipline: pass the diff's files explicitly, never a broad path that sweeps unrelated tests"
date: 2026-05-21
category: docs/solutions/best-practices
module: tooling
problem_type: best_practice
component: tooling
severity: medium
applies_when:
  - "A unit's diff has triggered ruff complaints (e.g., I001 import-order, UP037 type-annotation quotes) and the agent reaches for `ruff check --fix` to auto-correct"
  - "The current working tree has uncommitted changes scoped to one delivery unit but the broader tree carries pre-existing ruff-fixable issues in unrelated files"
  - "ruff is configured with autofix-eligible rules (I, F, UP, SIM, RET, etc.) that will rewrite imports / quotes / comprehensions across whatever paths it is given"
  - "ce:review or /ce:work discipline requires a diff scoped to the unit, and unrelated-file autofixes would contaminate that scope"
related_components:
  - development_workflow
  - testing_framework
tags:
  - ruff
  - autofix
  - tool-invocation-scope
  - scope-creep
  - diff-hygiene
  - per-unit-discipline
  - tooling-guard
  - git-checkout-revert
---

# ruff --fix scope discipline: pass the diff's files explicitly, never a broad path that sweeps unrelated tests

## Context

`ruff check --fix <path>` rewrites every file under `<path>` that has an auto-fixable lint finding. It has no concept of "the diff currently under review" — `<path>` is interpreted purely as a filesystem subtree. When the agent invokes it during a code-review follow-up to fix a single newly-introduced lint finding, the typical instinct is to pass a directory glob ("just fix the imports in this test folder"). That glob captures every file under the directory, including files that pre-existed the current diff with their own organic lint drift.

During the D6d new-U4 ce:review follow-ups (2026-05-21), the agent ran `ruff check --fix tests/` to fix an `I001` import-order issue in the new `tests/schema/lint/cli/test_d6d_custom_annotation_example.py` test file. ruff autocorrected **113 errors across many unrelated test files** (46 fixed automatically + 67 noted), bringing files completely outside U4's scope into the diff. Remediation required `git checkout HEAD -- <unrelated-files>` to revert the scope-creep edits while preserving the legitimate fix on the in-scope file.

The session-historian surfaced a partial precedent at D6c U3 (`299f7401`): after implementing U3's content, the agent ran `ruff check --fix tests/ src/` broadly and immediately recognized scope-creep, reverting with `git checkout -- <non-u3-files>` before committing. The D6c remediation was smaller in scale; D6d's 113-error sweep is the largest observed instance.

This is a recurring failure mode in Python ecosystems where import-order linting accumulates organic drift: every test file slightly off-spec for `I001` becomes a candidate for "fix" the moment ruff sees it.

## Guidance

Always pass `--fix` with **explicit file paths matching the diff under review**. Never pass a directory glob unless the entire directory is genuinely in scope.

Three safe invocation shapes (in order of typical use):

```bash
# Shape 1 — Single file (when the finding is on one known file)
ruff check --fix tests/schema/lint/cli/test_d6d_custom_annotation_example.py

# Shape 2 — Current diff only (when multiple files in the diff need autofix)
ruff check --fix $(git diff --name-only HEAD | grep '\.py$')

# Shape 2 variant — Include untracked new files (which `git diff` skips)
ruff check --fix $({ git diff --name-only HEAD; git ls-files --others --exclude-standard; } | grep '\.py$')
```

Pre-flight verification before running `--fix`:

```bash
# Dry-run: show what WOULD be fixed without writing
ruff check --diff <paths>           # prints proposed patches; review before applying
```

If a directory glob is unavoidable (e.g., genuinely fixing a project-wide drift on purpose), make it an explicit named operation OUTSIDE the code-review follow-up loop, with its own commit subject like `chore: project-wide ruff autofix sweep`. Do not mix scope-sweep autofixes into a code-review follow-up commit — they corrupt the review's attributable diff.

Recovery shape if a broad `--fix` already ran:

```bash
# 1. Inspect what got swept
git status                              # lists every modified file

# 2. Identify the file(s) in the current diff's scope (keep)
#    vs the rest (revert)
git diff <base>..HEAD --name-only       # files modified by the unit
# or: extract the list from the ce:review run artifact

# 3. Revert everything NOT in scope
git checkout HEAD -- <list-of-unrelated-files>

# 4. Verify the scope shrank correctly
git status                              # should show only in-scope files
```

## Why This Matters

ruff autofix on a broad path silently inflates the follow-up commit's diff with unrelated changes:

- **Reviewers can't tell scope.** A PR reviewer reading the follow-up commit sees edits to files that weren't in the ce:review run artifact's diff. They can't tell whether those edits are legitimate review-driven changes or scope creep.
- **Audit-trail corruption.** The follow-up commit's link to the ce:review run artifact implies "this commit fixes findings from that review." Unrelated autofixes break that implication; the commit is now lying about its provenance.
- **Bisect hazard.** A broad autofix sweep changes hundreds of lines across files that haven't been touched in months. If a regression bisects through that commit, the unrelated changes become noise that obscures the real cause.
- **Per-unit pipeline contamination.** When the autofix sweep happens during a multi-unit session (per multi-unit-ce-review-stash-pop-coordination-2026-05-21), the scope-creep can leak across unit boundaries — autofixing files that belong to the NEXT unit's scope. The stash-pop discipline can't catch this because the autofix targets committed files, not stashed WIP.
- **Repeat offenders amplify cost.** Import-order drift is the most common case, but the same pattern applies to `--fix`-eligible rules: `UP*` (pyupgrade), `SIM*` (simplification), `RET*` (return). Any rule with high autofix prevalence on the existing codebase amplifies the scope-creep cost. The D6d session also surfaced `UP037` rewriting type-annotation quotes — a different fix class with the same scope-creep risk.

The three safe shapes above are O(1) extra typing for O(N-unrelated-files) reduction in diff noise. The cost-benefit is overwhelming.

The discipline generalizes beyond ruff to any autofix tool:

- `black .` — same hazard; pass explicit file lists
- `isort .` — same hazard
- `prettier --write .` — same hazard
- `mypy --strict <path>` (when configured with autofix-style rewriters) — same hazard
- `pre-commit run --all-files` — INTENTIONAL broad scope; only use deliberately, never inside a unit-scoped follow-up

## When to Apply

Apply **every** time an autofix tool is invoked during:

- A ce:review follow-up commit.
- Any commit whose subject implies a narrow scope (`fix:`, `feat:` for a specific unit, etc.).
- Any pre-PR cleanup pass where the diff's scope is the entire content of the PR.
- A multi-unit session with per-unit scope isolation (see multi-unit-ce-review-stash-pop-coordination-2026-05-21).

Do **not** apply (i.e., a directory glob IS appropriate) when:

- The work is an explicit project-wide lint-cleanup commit with subject like `chore: ruff autofix sweep`.
- The directory under fix is brand-new (every file in it is part of the current diff).
- Running in pre-commit hook mode where the hook itself scopes the call to staged files.
- The `tests/meta/test_static_analysis.py`-style gated paths in this project: those test runners run `ruff check` (without `--fix`) over the full gated set, which is the correct shape for a CI invariant.

## Examples

### Counter-example (D6d new-U4, 2026-05-21)

```bash
# Agent intent: fix I001 import-order in the new U4 test file
ruff check --fix tests/                  # WRONG — operates on every file under tests/
# Result: 113 errors across many unrelated test files autocorrected
#         46 fixed automatically + 67 noted (remaining errors in unrelated files)
# Remediation:
git status                               # showed dozens of modified test files
git checkout HEAD -- tests/schema/helpers.py tests/schema/test_*.py \
    tests/test_cli.py tests/test_formatters_*.py tests/test_hooks.py \
    tests/test_pytest_plugin.py tests/schema/test_rules.py
# Verify scope shrank back to just the U4 files
git status                               # only U4 files modified
```

### Correct shapes (what should have been used)

```bash
# Shape 1 — Target the single known file
ruff check --fix tests/schema/lint/cli/test_d6d_custom_annotation_example.py
# Result: 1 file modified; other test files untouched

# Shape 2 — Target the current diff
ruff check --fix $(git diff --name-only HEAD | grep '\.py$')
# Result: only files in the current diff get autofix

# Shape 2 variant — Include untracked new files
ruff check --fix $({ git diff --name-only HEAD; git ls-files --others --exclude-standard; } | grep '\.py$')
# Result: in-scope + brand-new files in the unit
```

### Pre-flight verification habit

```bash
# See proposed changes before applying — works as a sanity check
ruff check --diff tests/schema/lint/cli/test_d6d_custom_annotation_example.py
# Then run with --fix if the diff looks right
ruff check --fix tests/schema/lint/cli/test_d6d_custom_annotation_example.py
```

### Project-wide cleanup (deliberate, separate commit)

```bash
# DIFFERENT commit, DIFFERENT context — not part of any unit's follow-up
ruff check --fix .
git add -u
git commit -m "chore: project-wide ruff autofix sweep (113 errors)"
# Now the scope is the commit's stated scope — no contamination
```

## Related

- multi-unit-ce-review-stash-pop-coordination-2026-05-21 — sibling discipline from the same D6d new-U4 session. Both protect per-unit diff scope; this one against autofix-tool scope-creep, that one against multi-unit WIP. The two together cover the two operational hazards that can violate per-unit pipeline discipline in the same session.
- delivery-boundary-bundled-commit-feat-plus-review-followups-2026-05-21 — direct companion: the bundled-commit pattern at delivery boundaries depends on a clean diff; this discipline keeps the diff clean.
- Auto memory: [[Per-Delivery Workflow]] (auto memory [claude]) — per-unit scope discipline applies to tooling invocations too. The auto-memory establishes the cadence; this learning extends it to the tooling invocation layer.
- Companion concern: `git add -A` / `git add .` (similar broad-scope hazard during staging — same class of bug, different tool).
- Anchor commit: D6d new-U4 ce:review follow-ups landing at `67cd7fb` (2026-05-21). The bundled commit's diff shows the post-remediation scope — only U4 files modified.
- Prior partial precedent: D6c U3 session `299f7401` (per session-historian) ran `ruff check --fix tests/ src/` broadly and reverted with `git checkout --` before committing. D6d new-U4 is the second observed instance; the [[shared-helper-third-instance-trigger]] pattern would promote this discipline to a pre-commit hook on a third instance.
