---
title: "A worktree run with the shared editable .venv tests the main checkout's code, and its strict type check fails on a module the ratchet does not list"
date: 2026-10-26
category: docs/solutions/test-failures
module: testing/worktree-runs
problem_type: test_failure
component: testing_framework
symptoms:
  - "From a git worktree or an exported copy, `.venv/bin/pytest` passes or fails according to the main checkout's `src/`, not the copy's: `import protokit` resolves to the main checkout"
  - "From such a copy, `tests/meta/test_static_analysis.py::test_mypy_strict_clean_on_gated_paths` fails at `src/protokit/schema/git.py:153` with `Returning Any from function declared to return \"bytes | str\"  [no-any-return]`, while the same commit passes in the main checkout and in CI"
  - "`.venv/bin/protokit --version` and `importlib.metadata.version(\"protokit\")` report the version the editable install was made at (0.15.1), not the version in pyproject.toml (0.16.0)"
  - "Against an installed, non-editable wheel, the ratchet's mypy check and `tests/core/test_extensions_default_pool.py::TestNoReaderBypassesTheFile` fail; the second dies parsing another installed package's file (`SyntaxError: invalid non-printable character U+FEFF`)"
root_cause: incomplete_setup
resolution_type: environment_setup
severity: medium
related_components: [tooling]
tags:
  - worktree
  - editable-install
  - pythonpath
  - mypy
  - static-analysis
  - src-layout
  - false-failure
---

# A worktree run with the shared editable .venv tests the main checkout's code, and its strict type check fails on a module the ratchet does not list

## Problem

The project venv, `.venv`, has protokit installed editable from the main
checkout (`pip install -e ".[dev,compiler]"`, `CONTRIBUTING.md:8`). An editable
install is a `.pth` file holding one absolute path, the main checkout's `src/`.
Any other copy of the repository run with that venv, such as a `git worktree`
for a release branch or a `git archive` export of an older commit, imports the
main checkout's `protokit`. Its tests then report on code that is not the code
under review, and the static-analysis ratchet's mypy check fails on an error it is not meant to
see.

## Symptoms

Reproduced 2026-10-26 with an export of `main` (`git archive HEAD`) and the
main checkout's `.venv` (Python 3.13, mypy 1.20.2):

| Run | `import protokit` resolves to | `test_mypy_strict_clean_on_gated_paths` |
|---|---|---|
| main checkout | main `src/` | passes |
| copy, no `PYTHONPATH` | **main** `src/` | fails: `src/protokit/schema/git.py:153: error: Returning Any from function declared to return "bytes \| str"  [no-any-return]` |
| copy, `PYTHONPATH=<copy>/src` | the copy's `src/` | passes |

`.venv/lib/python3.13/site-packages/_editable_impl_protokit.pth` contains the
main checkout's absolute `src` path, and the install's `direct_url.json` marks
it `"editable": true`. pytest does not repair the import. `tests/` is a package,
so pytest puts the copy's root on `sys.path`, not its `src/`, and `protokit` is
found through the `.pth` entry.

The first effect is silent. A worktree run is green or red according to the
main checkout, which is usually `main`, so a branch's change can pass without
ever being imported. Only the second effect, the mypy failure, makes the
mismatch visible, and it points at a file the branch did not touch.

The editable install also froze its metadata: `.venv/bin/protokit --version`
printed `protokit, version 0.15.1` after the 0.16.0 bump, because
`click.version_option(package_name="protokit")` (`src/protokit/cli.py:28`)
reads the dist-info written at install time. Reinstalling (`pip install -e .`)
refreshes it.

## What Didn't Work

The false mypy failure first appeared in the final release checks on the
rebased release branch's worktree (`release/0.16.0`, since deleted), as the one failure on each backend. The
release diff did not touch `src/`. Finding the cause took about 10 to 15
minutes and one more full-suite run on the critical path. In an earlier fix wave
the `PYTHONPATH` step had been worked out once already, and it had to be looked
up again from that session's transcript, because nothing in the repo recorded it
(session history).

- **Treating the mypy failure as a regression in the branch.** `git.py` is not
  in `_TYPE_CHECK_PATHS`, and the error at `:153` is old: the function returns
  `result.stdout` from a `subprocess.run(..., text=text)` whose `text` is a
  `bool` parameter rather than a literal, so strict mypy types the result as
  `Any`. Checking the file explicitly in the main checkout reports the same
  error (`python -m mypy src/protokit/schema/git.py`: `Found 1 error`).
- **Assuming the ratchet covers what it imports.** In the main checkout the check
  checks 78 source files and reports `Success`. `src/protokit/schema/git.py` is not one of
  them; mypy reaches it through `src/protokit/schema/cli.py`'s import. `mypy
  src/protokit/schema/cli.py` alone reports `no issues found in 1 source file`,
  and adding `src/protokit/schema/git.py` to the command reports the error. The
  cleanest evidence is the copy run: there `git.py:153` is the only error. The
  ratchet's paths run with `--no-site-packages` report it too, among about 160
  others caused by the third-party packages disappearing. So the editable `.pth`
  entry is what keeps that error out of the main checkout's check. mypy reports errors in the files
  it is given and in followed modules it treats as source, and stays silent on
  modules it finds through a site-packages path. In a copy, `src/` is not on a
  site-packages path, so `protokit.schema.git` is followed as source and its
  error counts.

## Solution

Point the copy's interpreter at the copy's own source:

```console
$ cd <worktree>
$ PYTHONPATH="$PWD/src" /path/to/main/.venv/bin/python -m pytest -q
$ PYTHONPATH="$PWD/src" /path/to/main/.venv/bin/python -c "import protokit; print(protokit.__file__)"
```

`PYTHONPATH` entries come before site-packages and its `.pth` entries on
`sys.path`, so the copy's `protokit` wins. The mypy check then passes too: with
the copy's `src/` on the interpreter's path, mypy finds `protokit.schema.git`
there and treats it as it does in the main checkout. Check the import line
first in any copy, before reading a test result.

One gap remains in the suite itself. Four tests start a child interpreter with
`PYTHONPATH` set to the repository root, which replaces the caller's value:
`tests/meta/test_proto_builder.py:344`,
`tests/meta/test_pure_python_inventory.py:306`,
`tests/storage/test_columnar_structural.py:216` and
`tests/storage/test_columnar_fidelity.py:238`. In a copy run with the fix, those
children still import the main checkout. That was checked with the same `env`
shape (`PYTHONPATH=<copy root>`): the child's `protokit.__file__` was the main
checkout's. Tests that build the child's `PYTHONPATH` from the imported package
(`Path(protokit.__file__).parents[1]` at `tests/core/test_options.py:902`,
`Path(_pools.__file__).parents[1]` at `tests/core/test_pools.py:380`, or `_SRC`
from `tests/core/test_extensions_default_pool.py:42`) follow whatever tree the
parent imported. So does `<repo root>/src` computed from the test file's own
location (`tests/core/test_extensions.py:862`).
So in a worktree, a pass from one of those four tests says nothing about the
copy.

Tools that hard-code the venv need the same treatment. `scripts/mutation_check.py`
runs `VENV_PY = ".venv/bin/python"` (`scripts/mutation_check.py:54`) relative to
the working directory, so in a worktree it needs a `.venv` there: either a
per-worktree `pip install -e .`, or a symlink to the main venv plus
`PYTHONPATH=<worktree>/src` (session history).

## Why This Works

An editable install is only a path on `sys.path`, fixed at install time. It
binds every interpreter that uses the venv to one checkout, whichever directory
the command runs in. `PYTHONPATH` is the one input that outranks it without
reinstalling. A per-worktree venv with its own `pip install -e .` also fixes it,
at the cost of a second environment.

The mypy difference follows from the same path. The main checkout's check
passes partly because its `src/` is also a site-packages path, so the result
depends on the install layout as well as the code. CI installs editable
(`pip install -e`, `.github/workflows/ci.yml:81`), so CI sees what the main
checkout sees.

## Prevention

- **In any worktree or export, set `PYTHONPATH=<copy>/src` and print
  `protokit.__file__` before trusting a result.** A green run that imported
  another checkout proves nothing about this one.
- **A test that runs a child interpreter should derive the child's
  `PYTHONPATH` from the imported package** (`Path(protokit.__file__).parents[1]`)
  or from the copy's own `src/`, not from the repository root. The repository root holds no importable
  `protokit` in a src layout, so the child falls back to whatever the venv's
  `.pth` names.
- **Read a mypy failure in a file outside `_TYPE_CHECK_PATHS` as a layout
  question first.** If the main checkout passes on the same commit, compare
  `protokit.__file__` in both before changing code.
- **The ratchet does not cover modules it only imports.** `src/protokit/schema/git.py` carries
  a real strict-mode error (`:153`) that the check never reports in its normal
  layout. Adding a module to `_TYPE_CHECK_PATHS` is what puts it under the
  ratchet.
- **Reinstall the editable package after a version bump** if anything reads
  `importlib.metadata.version("protokit")` or `protokit --version`.
- **A test that finds the source tree from a module's `__file__` assumes the
  src layout.** `tests/core/test_extensions_default_pool.py:42`
  (`_SRC = Path(_extensions.__file__).parents[1]`) becomes `site-packages`
  under an installed wheel, and the test then parses every installed package.
  CI never runs the suite against an installed package: the non-editable job
  installs with `pip install .` (`.github/workflows/ci.yml:335`) and then only
  runs each command's `--help` (`:337`). So a
  pre-release run of the suite against the built wheel shows these two
  failures (this test and the mypy check) as layout effects, not as defects in
  the wheel. Run with `PYTHONPATH` pointing at a copy of only the wheel's
  `protokit` package directory, and the extensions test passes against the wheel's own
  files.

## Related Issues

- [pytest static-analysis gate ratchet](../best-practices/pytest-static-analysis-gate-ratchet-2026-05-02.md):
  defines `_TYPE_CHECK_PATHS` and the check whose verdict on imported, unlisted
  modules depends on the install layout.
- [Lint and type ratchet cleanup is not behaviour-neutral by construction](../best-practices/lint-type-ratchet-cleanup-is-not-behaviour-neutral-by-construction.md):
  reproduces counterexamples "against a worktree checked out at the base
  revision", which needs the `PYTHONPATH` step above to test that revision.
- [Trust-boundary enforcement points derived from code, not the finding's wording](../security-issues/trust-boundary-enforcement-points-derived-from-code-not-the-findings-wording.md):
  ran its pre-fix transcripts from a `git archive` export "with `PYTHONPATH`
  pointed at that copy", the pattern this doc explains.
- [The mutation-check harness: stale bytecode and non-verdict exit codes produce false verdicts](../logic-errors/mutation-check-harness-stale-bytecode-and-nonverdict-exit-codes-produce-false-verdicts.md):
  the same family, a harness verdict earned on the wrong code; the harness's
  hard-coded `.venv/bin/python` puts it in scope here.
