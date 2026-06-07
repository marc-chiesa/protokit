---
title: "A test for an ordered preflight guard must control every probe the guard reads, not just the one under test"
date: 2026-06-07
category: docs/solutions/best-practices
module: testing/pytest-conventions
problem_type: best_practice
component: testing_framework
severity: medium
applies_when:
  - "Testing a guard that probes capabilities in a fixed order and raises/returns on the FIRST failure (find_spec, shutil.which, hasattr-style checks, feature flags)"
  - "The assertion targets a NON-FIRST branch (e.g. the error names the second dependency)"
  - "The probe stub fakes only the targeted name and delegates the rest with an `else: return real(...)` fall-through"
  - "The feature is gated behind an optional extra, so an earlier-probed dependency may be present locally (dev/spike leftover) but absent in base CI"
  - "The test passes locally and fails only on the CI matrix axis that lacks the extra"
related_components:
  - development_workflow
  - tooling
tags:
  - test-design
  - false-confidence
  - ordered-guard
  - optional-extra
  - monkeypatch
  - find-spec
  - environment-coupling
  - ci-matrix
---

# A test for an ordered preflight guard must control every probe the guard reads, not just the one under test

## Context

protokit's columnar/Parquet sink lives behind an optional extra, `protokit[parquet]`
(= `ptars==0.0.17` + `pyarrow`), so neither package is a base dependency. The sink
preflights with an **ordered** guard, `_require_parquet()` in
`src/protokit/storage/_columnar.py`, that probes each dependency with
`importlib.util.find_spec` and raises on the **first** one it finds absent:

```python
def _require_parquet() -> None:
    for name in ("ptars", "pyarrow"):
        if importlib.util.find_spec(name) is None:
            raise ParquetExtraNotInstalledError(name)   # .missing == first-absent name
```

A test wanted to assert the *second-position* behavior — "when `pyarrow` is the
missing one, the error names pyarrow." Because the guard short-circuits, that
assertion is only reachable if the first probe (`ptars`) reports present. The
original test faked only the targeted probe and **delegated the un-targeted
`ptars` probe to the real environment**:

```python
real = importlib.util.find_spec
def fake(name, *a, **k):
    if name == "pyarrow":
        return None
    return real(name, *a, **k)   # ptars reads real install state
```

This coupled the test's outcome to whatever happened to be installed in the
runner. It passed locally — the dev `.venv` had `ptars` ad-hoc pip-installed from
the PR3 spike (before it was formalized into the extra) — and failed in **every**
base-matrix CI job, where the `[parquet]` extra is not installed and `ptars` is
genuinely absent. The full local suite ("2705 passing") gave false confidence: it
ran in the one configuration that masks the bug.

## Guidance

A test that exercises an ordered preflight guard must fully control **every** probe
the guard reads — fake **all** dependency states explicitly, and never delegate an
un-targeted probe to the real environment. The guard short-circuits on the first
failure, so to reach and assert branch *N* you must pin every branch `0..N-1` to a
known "pass" state.

Concretely:

- Replace the whole probe function with a deterministic stub that returns a definite
  value for **each** name the guard can ask about. Fake "present" with a non-`None`
  sentinel (`object()`); fake "absent" with `None`.
- Do not fall through to `real(name, ...)` (or any live lookup) for the dependencies
  you are not directly targeting. An `else: return real(...)` fall-through in a
  probe stub is a code-review smell — treat it as one.
- Treat ordered short-circuiting guards (`for name in (...): if absent: raise`) as
  state machines: to test a given branch, deterministically force every earlier
  branch into "pass."

**"Fake every probe" is the rule regardless of probe order.** A sibling test in the
same file, `test_ae6_missing_extra_raises_actionable_error`, fakes `ptars=None`,
asserts `missing == "ptars"`, and *does* delegate the other probe to the real env —
yet it is safe. It is safe only by luck of position: its target (`ptars`) is the
**first** probe, so the guard never reaches the delegated one. That safety
evaporates the instant the probe tuple is reordered or a third entry is inserted
ahead of it. Don't rely on probe order for hermeticity; fake all of it.

Secondary discipline: do not treat a green local suite as authority for
optional-extra **absence** behavior when you have ad-hoc-installed that extra's
dependency into your dev venv. A spike that `pip install`s `ptars` outside the
formal `[parquet]` extra creates a local↔CI(bare) divergence. The CI matrix's
*extra-absent* jobs are the source of truth for how the code behaves when the extra
is missing — not the local "all green," which runs in the configuration that hides
the defect. Either formalize the dependency into the extra and lean on the
extra-absent job, or uninstall it before trusting the local suite.

## Why This Matters

A delegating probe produces a test that false-greens exactly when you most want it
to fail, and the failure is asymmetric:

- It passes on the developer's machine (whatever they have installed), giving false
  confidence.
- It only goes red in a clean/CI environment that doesn't satisfy the un-faked
  checks — across every base-matrix job at once, after the work is pushed, far from
  the keyboard.

Worse, a delegating-probe test isn't merely flaky — in the masking environment it
is silently testing the **wrong path**. The assertion `missing == "pyarrow"` is
sharp and *does* fire; it just fires against the wrong branch. In a bare
environment the guard raises on `ptars` first, so the intended branch is never
exercised. Explicitly faking every probe makes the test exercise the path it claims
to (`ptars` present, `pyarrow` absent) regardless of what's installed — which is the
entire point of monkeypatching the probe in the first place.

## When to Apply

Apply whenever a test monkeypatches a dependency-detection or capability-probe
function (`importlib.util.find_spec`, `shutil.which`, `find_executable`, feature-flag
lookups, `hasattr`-style capability checks) **and** the code under test consults that
probe more than once in a fixed order with short-circuit semantics. Signals:

- The guard iterates a tuple/list of names and raises (or returns) on the first hit.
- You want to assert a non-first branch (second dependency, third capability, …).
- The probe stub contains an `else: return real(...)` fall-through.
- The feature is gated behind an optional extra, so the dependency may be present
  locally (dev convenience or spike leftover) but absent in base CI.

Also apply the "CI extra-absent job is the source of truth" rule any time you
ad-hoc-install an optional dependency into the dev venv during exploration.

## Examples

Before — delegates the un-targeted `ptars` probe to the real env; passes only when
`ptars` happens to be installed:

```python
real = importlib.util.find_spec
def fake(name, *a, **k):
    if name == "pyarrow":
        return None
    return real(name, *a, **k)   # reads real install state for ptars
```

After (commit `e612364`, one line) — fakes *every* probe explicitly; `ptars` is
forced present, so the guard deterministically reaches the `pyarrow` branch in any
environment:

```python
def fake(name, *a, **k):
    return None if name == "pyarrow" else object()   # ptars faked PRESENT; never touch real env
```

The robust sibling that asserts `_has_parquet()` is `False` follows the same
principle from the other direction — it stubs *everything* absent
(`lambda name, *a, **k: None`), again leaving nothing to the real environment.

## Related

- [pytestmark does NOT guard module-top imports](../test-failures/pytestmark-does-not-guard-module-top-imports-2026-05-02.md) — the complementary half of optional-extra test discipline. That doc gates *collection* with `pytest.importorskip` for tests that need the dep; this doc keeps an extra-**absent** error-path test un-skipped and instead makes its `find_spec` double hermetic. Same "passes locally, fails on the no-extra CI axis" surface, different mechanism and fix.
- [Test proxy signal must be independent of the suppression mechanism under test](test-proxy-signal-suppressed-by-mechanism-under-test-2026-05-25.md) — contrasting cousin: that is a *vacuous-assertion* false-green (the observable could never fire); here the assertion was sharp and fired, against the wrong branch, because the double was environment-coupled.
- [Test capture infrastructure without dispatch is false confidence](capture-setup-without-dispatch-false-test-confidence-2026-05-17.md) — same family of "green for the wrong reason" test traps.
- [protobuf upper-bound pin (FieldDescriptor.label removed in 7)](../tooling-decisions/protobuf-upper-bound-pin-fielddescriptor-label-removed-in-7-2026-05-27.md) — the optional-extra-must-be-tested-on-both-install-paths concern at the dependency-pin layer rather than the test layer.
- Origin: PR #17 (`feat/storage-pr3-columnar`); guard in `src/protokit/storage/_columnar.py`, fixed test in `tests/storage/test_columnar_extra.py`.
