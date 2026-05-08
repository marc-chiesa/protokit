# Static-Analysis Cleanup — Scope and Approach

**Created:** 2026-05-08
**Status:** scoped, not yet planned
**Priority:** low (incremental discipline applies; not blocking any delivery)

## Context

protokit's static-analysis gate uses a ratchet pattern (see
`docs/solutions/best-practices/pytest-static-analysis-gate-ratchet-2026-05-02.md`):
the ratchet only grows; clean files get added to
`tests/test_static_analysis.py:_LINT_PATHS` and
`_TYPE_CHECK_PATHS` as feature work touches them. The
intentional discipline is **pay-as-you-touch**, not big-bang
remediation.

After D3 U4b ships, the ratchet covers:

```
_LINT_PATHS:
  src/protokit/_cli_utils.py
  src/protokit/formatters/_builtin_lint.py
  src/protokit/schema/compile.py
  src/protokit/schema/lint/
  tests/schema/lint/
  tests/test_cli_utils.py
  tests/test_formatters_cli.py
  tests/test_static_analysis.py

_TYPE_CHECK_PATHS:
  src/protokit/_cli_utils.py
  src/protokit/formatters/_builtin_lint.py
  src/protokit/schema/compile.py
  src/protokit/schema/lint/
```

That's the D3-touched surface. Pre-D3 modules
(`src/protokit/message/`, `src/protokit/schema/{checker,cli,git,model,plugins,profiles,rules}.py`,
older `src/protokit/formatters/_builtin_*.py`, plus their test
files) sit outside the ratchet and carry pre-existing static-
analysis debt.

## Pre-existing debt as of 2026-05-08

Running `ruff check src tests` against the full repo:

- **160 ruff errors** across ~25 files
- **Top categories:**
  - 46 N806 — variable name should be lowercase (Phase 1
    pre-existing convention drift; mostly in
    `src/protokit/message/` and `src/protokit/schema/checker.py`)
  - 21 I001 — import organization
  - 21 E501 — line too long
  - 20 W291 — trailing whitespace
  - 8 F401 — unused imports
  - 8 B017 — `pytest.raises(Exception)` too broad
  - 4 B905 — `zip()` without `strict=`
  - 3 B023 — unbound loop variable in closure
  - 2 E702 — multiple statements on one line
  - 2 B904 — raise without `from`
- **71 of 160 are auto-fixable** via `ruff check --fix`.

Running `mypy --strict src tests`:

- **212 mypy --strict errors** across 38 files
- Categories include: missing annotations, `Any` returns,
  generator return types, missing library stubs (e.g.,
  `types-jsonschema` is in `dev` deps but not consistently
  applied), attribute-defined gaps.
- Test files are NOT in `_TYPE_CHECK_PATHS` by convention; the
  ratchet's mypy gate is source-only. The ungated 212 includes
  test files.

## Scoped follow-up work

Three paths, in increasing scope:

### Path 1 (narrow) — File-by-file as touched

The default discipline. When future delivery work touches a
pre-D3 file, the implementer:

1. Fixes the file's static-analysis issues.
2. Adds the path to `_LINT_PATHS` (and `_TYPE_CHECK_PATHS` if
   it's a source file).
3. Updates `.github/workflows/ci.yml` mypy step in lockstep.

This is what U4b's follow-up commit did for `_builtin_lint.py`
and `tests/test_formatters_cli.py`. No work captured here;
implicit in delivery discipline.

### Path 2 (medium) — `src/protokit/formatters/_builtin_*.py`

The four sibling formatter modules (`_builtin_diff.py`,
`_builtin_compat.py`, `_builtin_history.py`,
`_builtin_bisect.py`) share the same pattern as the ratcheted
`_builtin_lint.py` and were touched by D3's ruff auto-fix.
Bringing them into the ratchet would be ~2 hours:

- Run `ruff check --fix` on the four files.
- Resolve any remaining issues (line-too-long, unused imports).
- Run `mypy --strict` and fix annotations.
- Add all four to `_LINT_PATHS` and `_TYPE_CHECK_PATHS`.
- Update CI YAML.

Recommended trigger: any delivery that adds a fifth machine
formatter (e.g., a future SARIF v2.2.0, GitHub-Code-Scanning-
specific format, or a user-formatter-pack discovery mechanism).

### Path 3 (large) — Repo-wide cleanup

Tackle all 160 ruff + 212 mypy errors in one structured pass.
Estimated 1-2 days.

Suggested sequencing (a future ce:brainstorm + ce:plan would
expand each):

1. **Auto-fixable first** — `ruff check --fix` resolves 71
   issues mechanically. Single commit.
2. **Naming convention sweep** — N806 (46) requires careful
   review per file: some "uppercase" names are intentional
   (e.g., generated proto class fields). Per-file inspection.
3. **Import organization** — I001 (21), F401 (8) — mostly
   mechanical with `--fix` but some imports are deliberate
   (e.g., side-effect-only `_builtin_*` imports). Verify.
4. **Whitespace + formatting** — E501 (21), W291 (20), E702
   (2). Some E501s are docstrings with literal examples that
   should stay long; others can be wrapped.
5. **Bug-flavored** — B017 (8) and B904 (2) flag actual
   defensive-coding problems. Fix per-finding.
6. **Test-file mypy** — extending `_TYPE_CHECK_PATHS` to
   include test files would change the discipline. Optional;
   discuss in the planning brainstorm.

Recommended trigger: a calm period between deliveries OR a
hire/contributor onboarding moment where the pre-existing
patterns confuse newcomers. Not urgent.

## Decision

**Default to Path 1.** The D3 deliveries (U2-U4b) demonstrate
the model works: each unit's ce:review surfaced static-analysis
issues in its own touched files, fixes landed in the unit, and
the ratchet grew incrementally. Path 1 honors the existing
learning's discipline.

**Path 2 is the next natural step** if D6+ touches the
`_builtin_*` formatter family or a sibling-pattern parity audit
surfaces drift between them. Track as a candidate for D6
brainstorm.

**Path 3 is on the table** but should be planned via
ce:brainstorm + ce:plan when scheduled. Not before D3 ships.

## Related

- `docs/solutions/best-practices/pytest-static-analysis-gate-ratchet-2026-05-02.md`
  — the discipline this doc inherits.
- `docs/solutions/best-practices/normalize-at-input-boundary-2026-05-07.md`
  — example of incremental cleanup driven by ce:review +
  ce:compound (the `--profile` case-normalization fix).
- `docs/plans/2026-05-04-001-feat-protokit-lint-d3-cli-plan.md`
  Unit 5 — the in-flight delivery; widens the ratchet for
  `tests/test_formatters_cli.py` per U4a ce:review advisory A1.
- D3 U4a ce:review — flagged the ratchet-widening for
  `tests/test_formatters_cli.py`, which Path 1 addressed in
  the U4b follow-up commit.
