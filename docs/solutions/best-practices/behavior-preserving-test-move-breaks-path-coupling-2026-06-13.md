---
title: "A behavior-preserving test-file move still breaks four classes of path coupling that git mv cannot fix"
date: 2026-06-13
category: docs/solutions/best-practices
module: tests
problem_type: best_practice
component: testing_framework
severity: medium
applies_when:
  - "Relocating loose tests/test_*.py files into source-mirroring subpackages (one or more directory levels deeper)"
  - "A static-analysis gate test holds a hardcoded tuple/list of test-file path strings that must be refreshed when files move"
  - "Test files compute the repo root via Path(__file__).resolve().parent.parent or .parents[N] and are therefore depth-coupled"
  - "Shared fixtures, builders, or helpers stay at the tests/ root while the files reading them move deeper"
  - "A CI workflow hardcodes a pytest path like 'pytest tests/test_X.py' that goes stale on relocation"
symptoms:
  - "git mv leaves the suite green locally but a CI matrix job fails on a stale hardcoded pytest path"
  - "A moved file resolves repo root one level too shallow; absolute-path reads point outside the tree"
  - "FileNotFoundError reading a shared fixtures dir after the reading file moved deeper"
  - "A path-string gate test passes its existence pre-check yet no longer covers the moved files"
  - "pytest rootdir/import errors or basename collisions when a new test subdir lacks __init__.py"
related_components:
  - tooling
  - development_workflow
tags:
  - test-reorganization
  - git-mv
  - path-coupling
  - pytest-rootdir
  - fixture-path-resolution
  - repo-root-anchor
  - fail-closed
  - ci-hardcoded-path
---

# A behavior-preserving test-file move still breaks four classes of path coupling that git mv cannot fix

## Context

You have a `tests/` tree that is half-organized: some tests already live in
source-mirroring subpackages (`tests/schema/`, `tests/storage/`,
`tests/parity/`), but dozens of older `test_*.py` files are still loose at the
root. The obvious cleanup — relocate the loose files into matching subpackages
so the test tree mirrors `src/` — *feels* content-free. `git mv` preserves
history, the files don't change, and "it's just moving files."

That intuition is the trap. Moving 47 loose `tests/test_*.py` files one level
deeper into `tests/{message,formatters,core,meta}/` (protokit, issue #29 / PR
\#30) broke **four distinct classes of path coupling that `git mv` cannot fix**,
plus a fifth (non-breaking) class of stale prose references. None of these live
in the moved file's *test logic* — they hide in path strings, filesystem
anchors, fixture reads, and CI invocations that silently encode "how deep am I
in the tree." A test-file relocation is a refactor with a real blast radius, and
the couplings live *outside* the assertions, where a casual reading won't find
them.

Every one of the four breaking classes resolves a path *relative to the file's
own location*, so making the file one directory deeper changes what that path
points at. The good news — and the thing that makes the reorg safe to attempt —
is that all four **fail closed**: they raise loudly rather than passing wrong.
The danger is the gap: a path that *coincidentally still resolves to something
that exists* passes silently, so the green suite alone does not prove
correctness.

## Guidance

Treat a test-tree relocation as a coupling-repair task, not a move. Before you
`git mv`, enumerate each coupling class with grep; then repair them in the same
commit as the move.

### The four breaking classes (must repair — `git mv` won't)

1. **Path-string gate lists.** A test that feeds *hardcoded test-file path
   strings* to an external tool — here a `_LINT_PATHS` tuple fed to `ruff check`
   in `tests/meta/test_static_analysis.py`, with an `_assert_paths_exist`
   pre-check resolving each against `_REPO_ROOT`. Every moved-file string goes
   stale. **Subtlety:** if the same file *also* has a repo-root anchor (class 2)
   and its pre-check resolves the strings against that anchor, you must fix
   **both** — repointing the strings but leaving the anchor shallow (or vice
   versa) leaves the gate red.
   - Grep: `grep -rn '"tests/' tests/ src/ .github/ pyproject.toml`

2. **Repo-root anchors.** Any `Path(__file__).resolve().parent.parent` or
   `.parents[1]` that assumed the file sat at `tests/`. After moving deeper it
   resolves to `tests/` instead of the repo root. Deepen the index by one
   (`parent.parent` → `parents[2]`), mirroring the codebase's pre-existing
   depth-3 anchor at `tests/storage/test_public_surface.py`.
   - Grep: `grep -rn 'Path(__file__).resolve().parent' tests/` and
     `grep -rn 'parents\[' tests/`
   - **Trade-off to log:** `parents[2]` is still depth-coupled — a future move
     re-tunes the index. An upward `pyproject.toml`-marker search removes the
     coupling entirely but is scope creep for a relocation; defer it explicitly
     rather than silently.

3. **Shared-fixture relative reads.** Tests reading a sibling data dir via
   `Path(__file__).parent / "fixtures"`. If the fixtures dir stays at `tests/`
   root (because it is *shared* across buckets) while the test moves deeper,
   repoint `parent` → `parent.parent`.
   - Grep: `grep -rn 'Path(__file__).parent' tests/ | grep -iE 'fixtures|data|golden|schema'`
   - **Decision rule:** a fixture dir read by more than one bucket (here
     `tests/fixtures/` is read by the formatters bucket *and* by
     `tests/schema/test_cli.py`) **stays at root**; only the readers' relative
     depth changes. Grep all readers before deciding whether to move the data.

4. **CI invocations.** Hardcoded test paths inside `.github/workflows/*.yml`
   (here `pytest tests/test_hamcrest_adapter.py` in the `message-hamcrest` job).
   These fail the *CI job*, not the local suite — so a green local run hides
   them.
   - Grep: `grep -rnE 'tests/test_|pytest tests/' .github/` (and any `Makefile`,
     `tox.ini`, `noxfile.py`, pre-commit config, or scripts dir)

### The fifth (non-breaking) class — refresh, don't gate on it

5. **Tracked comment/docstring path refs.** Prose like
   `# see tests/test_cli_utils.py header` in source and CI comments. These don't
   break anything but rot. Refresh them in a *separate, final, non-breaking
   commit*. Leave genuinely historical records (e.g. point-in-time entries in
   `CHANGELOG.md` or other `docs/solutions/` learnings) alone.
   - Grep: `grep -rn 'tests/test_' src/ .github/`

### Controls that are depth-INDEPENDENT — confirm they need NO edit (do not "fix" them)

- `inspect.getsource(module)` presence ratchets — operate on an imported module
  object, not a path. The assertion survives untouched; only a `parent.parent`
  *file-locator* sitting above it (if any) is a class-2 site.
- `tmp_path`-based paths — pytest-provided, location-agnostic.
- Package-qualified absolute imports (`from tests.proto_builder import ...`) —
  resolve identically from any depth, because shared helpers stayed at root with
  `__init__.py`.

### Structural prerequisite — `__init__.py` in every new dir

Under pytest's default `prepend`-mode rootpath, modules are imported by
fully-qualified name; without `__init__.py` you get import errors or basename
collisions across buckets (two `test_cli.py`, two `test_pytest_plugin.py` in
different dirs). Scaffold the empty packages *first*.

### Commit discipline (three commits)

- **U1 — scaffold empty `__init__.py` packages.** Clean intermediate green.
- **U2 — `git mv` + repair ALL four coupling classes as ONE squashed commit.**
  The tree is *transiently red* between the `mv` and the repairs (paths are
  stale by construction), so green must hold at the **unit boundary**, never
  mid-move. Splitting the move from its repairs commits a known-red state and
  breaks `git bisect`.
- **U3 — refresh doc/comment refs (class 5).** Non-breaking, isolated, easy to
  review.

## Why This Matters

**The fail-closed property is what makes this refactor tractable.** All four
breaking classes raise loudly — an assertion (the `_assert_paths_exist`
pre-check on stale `_LINT_PATHS`), a `FileNotFoundError` (a fixture read
pointing at a now-nonexistent path), or a hard CI error (a `pytest <bad-path>`
step). None pass wrong. So you can move aggressively: miss one, and the suite
goes red and tells you where.

**The one gap in fail-closed: a path that coincidentally still resolves.** The
gate only protects paths whose target *moved*. If a repo-root anchor is wrong by
one level but the directory it now points at happens to exist (e.g. resolving to
`tests/` when `tests/` is a real dir), the assertion passes and the test
silently checks the wrong thing. The green suite cannot catch this, because it
only exercises paths the tests happen to touch. That is why static verification
*beyond* the suite is mandatory.

**Why one squashed commit for the move+repair.** The window between `git mv` and
finishing the repairs is *definitionally red*. Squashing makes green hold at the
unit boundary while keeping the scaffold and the doc refresh as their own clean,
reviewable commits.

**Why full-matrix verification, not just a local run.** Regrouping test files
can change *collection-time optional-dependency skips per CI cell*. The proof of
correctness was an identical `pytest --collect-only -q` count (2976) and
identical pass/fail (2969 passed, 7 skipped) before and after — run on the full
CI matrix including the optional-dep cells (`parquet`, `hamcrest`). A single
local cell with all extras installed would not surface a bucket that changed
which tests skip in a minimal cell. (See
[[pytestmark-does-not-guard-module-top-imports-2026-05-02]] for the collection-
time skip failure mode.)

**Why the adversarial static sweep beyond the green suite.** Because of the
coincidental-resolve gap, a passing suite is necessary but not sufficient. Run
multiple *independent* search angles to find latent couplings the suite never
exercises: (1) depth anchors, (2) relative data reads, (3) residual path-strings
across all tooling/config, (4) imports + collection + basename collisions, (5)
requirement coverage, (6) CI-matrix skip behavior. Multi-modal because no single
grep catches all classes — a string-literal search misses a `parents[1]` anchor,
and an anchor search misses a CI invocation.

## When to Apply

- Relocating test files **deeper** in the tree (loose → subpackage, or one
  nesting level → another) — the depth change is what breaks relative
  resolution.
- Reorganizing a half-organized test tree to mirror `src/` structure.
- Moving or renaming a *shared* fixture/data directory that multiple test
  buckets read.
- Any "behavior-preserving" file move where files contain `Path(__file__)`-
  relative logic, hardcoded path-string lists fed to external tools, or are
  named in CI/Makefile/tox invocations.

It applies most sharply when the tree is **partially** migrated — the safe-depth
pattern already exists somewhere (here `tests/storage/` at depth 3), so you
mirror it instead of inventing a new convention.

It is **less relevant** when moving files *up* (toward the root, which usually
over-resolves harmlessly) or moving a fully self-contained file with no relative
path logic, no gate-list entry, and no CI mention — but you only know that
*after* running the five greps, so run them regardless.

## Examples

**Class 1 — path-string gate list** (`tests/meta/test_static_analysis.py`). The
`_LINT_PATHS` tuple holds literal test-file paths fed to `ruff check`; repoint
each moved-file string to its new bucket, including the self-reference:

```python
_LINT_PATHS: tuple[str, ...] = (
    ...
    "tests/meta/test_buf_parity_pin_drift.py",       # was tests/test_buf_parity_pin_drift.py
    "tests/formatters/test_builtin_lint_formatter.py",
    "tests/core/test_cli_utils.py",
    "tests/message/test_field_selector.py",
    "tests/message/test_hamcrest_adapter.py",
    "tests/meta/test_static_analysis.py",            # self-reference
)
```

This same file *also* needed the class-2 anchor fix — `_assert_paths_exist`
resolves these repointed strings against `_REPO_ROOT`, so fixing only the
strings leaves the gate red:

```python
-_REPO_ROOT = Path(__file__).resolve().parent.parent   # resolved to tests/
+_REPO_ROOT = Path(__file__).resolve().parents[2]       # resolves to repo root
```

**Class 2 — repo-root anchors.** Four files; all `parent.parent` / `parents[1]`
→ `parents[2]`:

```python
# tests/message/test_message_public_surface.py
-_REPO_ROOT = Path(__file__).resolve().parents[1]
+_REPO_ROOT = Path(__file__).resolve().parents[2]

# tests/meta/test_changelog_delivery_presence_ratchet.py
-REPO_ROOT = Path(__file__).resolve().parent.parent
+REPO_ROOT = Path(__file__).resolve().parents[2]
```

The target depth was not guessed — it mirrors the pre-existing depth-3 anchor
already correct in the half-migrated tree:

```python
# tests/storage/test_public_surface.py  (unchanged — the reference pattern)
_REPO_ROOT = Path(__file__).resolve().parents[2]
```

**Class 3 — shared-fixture relative reads.** Five formatter tests read
`tests/fixtures/`, which stayed at root; `parent` → `parent.parent` (8 sites):

```python
# tests/formatters/test_formatters_junit.py (and sarif / builtin_lint / integration / runtime_warnings)
-_JUNIT_XSD   = Path(__file__).parent / "fixtures" / "junit-xml" / "JUnit.xsd"
+_JUNIT_XSD   = Path(__file__).parent.parent / "fixtures" / "junit-xml" / "JUnit.xsd"
```

`tests/schema/test_cli.py` already lived at depth 2 and already used
`parent.parent` for the same fixtures — so it correctly needed **no change**,
confirming the fixture dir is shared and belongs at root.

**Class 4 — CI invocation** (`.github/workflows/ci.yml`, `message-hamcrest`
job). Fails the CI job, not the local suite:

```yaml
-        run: pytest tests/test_hamcrest_adapter.py -v
+        run: pytest tests/message/test_hamcrest_adapter.py -v
```

**Class 5 — tracked prose refs** (non-breaking, final commit). Comments in
source and CI yaml:

```yaml
-#     (see tests/test_cli_utils.py header for the convention).
+#     (see tests/core/test_cli_utils.py header for the convention).
```

**The enumeration greps (run all five before moving):**

```sh
# Class 1 — quoted test-path string literals in code/config/CI
grep -rn '"tests/' tests/ src/ .github/ pyproject.toml
# Class 2 — repo-root anchors that assume a fixed depth
grep -rn 'Path(__file__).resolve().parent' tests/ ; grep -rn 'parents\[' tests/
# Class 3 — relative sibling-data reads
grep -rn 'Path(__file__).parent' tests/ | grep -iE 'fixtures|data|golden|schema'
# Class 4 — hardcoded test paths in CI / build tooling
grep -rnE 'tests/test_|pytest tests/' .github/
# Class 5 — prose path references (refresh in final non-breaking commit)
grep -rn 'tests/test_' src/ .github/
```

**Correctness proof (run on the full CI matrix, before and after):**

```sh
pytest --collect-only -q | tail -1   # identical count both sides
pytest -q                            # identical pass/skip both sides
```

## Related

- [[pytest-static-analysis-gate-ratchet-2026-05-02]] — the gate whose
  `_LINT_PATHS` strings (class 1) and `_REPO_ROOT` anchor (class 2) this reorg
  repoints. Its own prevention notes already flag that
  `_REPO_ROOT = parent.parent` assumes a fixed depth — this learning is the
  event where that caveat came due.
- [[conftest-plain-function-relative-import-2026-05-12]] — the
  `__init__.py`-per-dir prerequisite and the package-qualified-import survival
  the move relies on.
- [[pytestmark-does-not-guard-module-top-imports-2026-05-02]] — why the proof
  must run the full CI matrix (optional-dep collection-time skips).
- [[cross-file-pin-regex-anchor-structure-not-annotation-token-2026-05-13]] —
  `test_buf_parity_pin_drift`, a concrete class-2 meta test that moved into
  `tests/meta/`.
- [[presence-ratchet-test-pattern-for-prose-substrings-2026-05-14]] — the
  `inspect.getsource` depth-independent control: the substring assertion
  survives the move; only a `parent.parent` file-locator above it would not.
- Originating issue: protokit#29 (reorganize `tests/` into subpackage-mirroring
  directories); shipped in PR #30.
