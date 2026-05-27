---
title: Perf-smoke fixtures must be audited against cross-file lint rules added after the fixture was written
date: 2026-05-27
category: docs/solutions/best-practices
module: protokit.schema.lint
problem_type: best_practice
component: testing_framework
severity: medium
applies_when:
  - Adding a cross-file lint rule (e.g., `package/directory-same-package`, `package/directory-match`, `package/no-import-cycle`) to BUILTIN_PACKS
  - Maintaining synthetic perf-smoke or stress-test fixtures gated behind platform-specific skipif markers
  - Auditing fixture layouts whenever a new cross-file rule lands
  - "A test runs on a single CI cell (matrix-axis-skipif pattern) and may not exercise locally for months"
tags:
  - perf-smoke
  - fixture-layout
  - cross-file-lint-rules
  - package-directory-alignment
  - skipif-marker
  - ci-only-failure
  - fixture-audit
  - builtin-packs-growth
  - synthetic-fixture
related_components:
  - testing_framework
---

# Perf-smoke fixtures must be audited against cross-file lint rules added after the fixture was written

## Context

protokit's perf smoke (`tests/schema/lint/test_perf_smoke.py`) is a catastrophic-regression canary: time the lint engine on 50 files × 20 messages × 10 fields = 10,000 fields, assert under 0.5s. It runs on `linux+py3.12` only (matrix-axis-skipif), so it executes on exactly one CI cell.

The original synthetic fixture wrote 50 files with distinct `perfsmoke.file<N>` packages into a single tmp_path directory. That layout was fine when the only cross-file rule was `naming/snake-case-fields`, but `package/directory-same-package` landed in 0.4.0 (and the broader `package/directory-match` family with it). The rule correctly fired 50 findings on the new fixture: 50 distinct packages in one directory violates the contract.

The fixture had become invalid for its own perf smoke — but the bug stayed hidden for months because the smoke only runs on one CI cell, and that cell had never executed before the first public CI run (the repo was private; no Linux CI). On macOS local dev the test always skipped via the skipif marker.

## Guidance

Restructure perf-smoke fixtures so each file's directory layout matches its dotted package, eliminating cross-file lint findings on the otherwise-clean walker fixture. From `tests/schema/lint/test_perf_smoke.py:100-121`:

```python
def _generate_synthetic_fixture(tmp_path: Path) -> list[Path]:
    """Write the 50-file synthetic fixture to ``tmp_path`` and return paths.

    Each file lives at ``perfsmoke/file<idx>/file_<idx>.proto`` so
    its directory layout matches its dotted package
    (``perfsmoke.file<idx>``) and no cross-file package-vs-directory
    lint rule fires on the otherwise-clean walker fixture.
    """
    paths: list[Path] = []
    for i in range(_PERF_SMOKE_FILES):
        subdir = tmp_path / "perfsmoke" / f"file{i}"
        subdir.mkdir(parents=True, exist_ok=True)
        p = subdir / f"file_{i:03d}.proto"
        p.write_text(
            _generate_proto_source(
                file_idx=i,
                n_messages=_PERF_SMOKE_MESSAGES_PER_FILE,
                n_fields=_PERF_SMOKE_FIELDS_PER_MESSAGE,
            ),
        )
        paths.append(p)
    return paths
```

And in the proto-source generator at `tests/schema/lint/test_perf_smoke.py:71-97`, each file declares `package perfsmoke.file<idx>;` to match its directory.

The structural rule: **when adding a new cross-file lint rule to `BUILTIN_PACKS`, audit every existing synthetic fixture used in tests.** Fixtures that were valid against the previous rule set may become invalid when the rule lands.

Add a checklist item to the new-cross-file-rule template (the planning doc or PR template for `BUILTIN_PACKS` additions):

- [ ] Audit perf-smoke fixture (`tests/schema/lint/test_perf_smoke.py::_generate_synthetic_fixture`) for compliance with the new rule
- [ ] Audit any other multi-file fixture in `tests/schema/lint/` that exercises the full `BUILTIN_PACKS` profile
- [ ] If the perf smoke runs on a single CI cell (matrix-axis-skipif), verify the cell exists in the CI matrix BEFORE merging (so any fixture-regression surfaces on first CI run rather than months later)

## Why This Matters

Catastrophic-regression canaries lose their signal when they emit findings or warnings on the fixture itself — the test passes the timing assertion but the "should produce zero findings" assertion fails, and the failure is interpreted as "the canary is broken" rather than "the fixture is wrong." Worse, if the failing-fixture state persists for releases, future regressions in walker performance get masked behind the fixture failure.

The single-CI-cell skip pattern (`@pytest.mark.skipif(sys.platform != "linux" or sys.version_info[:2] != (3, 12), ...)`) makes this category of bug invisible locally. The smoke author who ran tests on macOS never saw the failure. The Linux-py3.12 cell in CI didn't exist when the fixture was first written. By the time the CI matrix actually exercised the fixture, a cross-file rule family had landed and the fixture violated it.

The lesson generalizes beyond perf smoke: **any test fixture exercised by only a subset of CI cells is at risk of bit-rotting against rule changes that the broader test suite doesn't catch.** Add fixture-audit to the checklist for new cross-file rules, and consider broadening the smoke's CI matrix coverage if practical (timing variance across cells is the usual reason it's narrowed — but a fixture-correctness assertion is less timing-sensitive than the throughput assertion and could run on more cells).

## When to Apply

- Always when adding a new cross-file lint rule (package, directory, file-level naming, import structure) to `BUILTIN_PACKS`.
- Always when a test fixture exercises the full `BUILTIN_PACKS` profile rather than a single rule pack.
- When a test runs on a single CI cell (matrix-axis-skipif pattern), be especially vigilant — local dev may not exercise it for months.
- Does NOT apply to single-rule unit tests where the fixture is intentionally minimal and only the rule-under-test is loaded.

## Examples

**Before (50 files, one directory, 50 packages — fires 50 `package/directory-same-package` findings):**

```python
def _generate_synthetic_fixture(tmp_path: Path) -> list[Path]:
    paths = []
    for i in range(_PERF_SMOKE_FILES):
        p = tmp_path / f"file_{i:03d}.proto"  # ← all collocated in tmp_path
        p.write_text(_generate_proto_source(i, ...))  # package perfsmoke.file<i>;
        paths.append(p)
    return paths
```

**After (each file in its own subdir matching its package):**

```python
def _generate_synthetic_fixture(tmp_path: Path) -> list[Path]:
    paths = []
    for i in range(_PERF_SMOKE_FILES):
        subdir = tmp_path / "perfsmoke" / f"file{i}"
        subdir.mkdir(parents=True, exist_ok=True)
        p = subdir / f"file_{i:03d}.proto"  # ← directory matches package
        p.write_text(_generate_proto_source(i, ...))  # package perfsmoke.file<i>;
        paths.append(p)
    return paths
```

The rule check passes; the timing assertion is meaningful again.

## Related

- [[perf-smoke-profile-compose-across-builtin-packs-2026-05-13]] — sibling perf-smoke discipline doc (registry-iteration symmetry). The "fixture-side counterpart" of that learning's "test-side" rule: that doc fixes test-coverage of new packs; this one fixes test fixtures themselves when new cross-file rules ship. Worth consolidating into a perf-smoke discipline cluster.
- [[cli-fixture-proto-hygiene-must-satisfy-builtin-packs-2026-05-13]] — directly adjacent: "CLI fixtures must satisfy every rule in BUILTIN_PACKS when a new rule lands." Perf-smoke fixtures need the same hygiene audit.
- [[programmatic-proto-fixture-builder-multi-file-rule-family-2026-05-17]] — fixture-builder discipline for multi-file rule families (cross-file rules specifically).
- [[per-rule-fixture-symbol-isolation-buf-v2-compile-group-2026-05-13]] — fixture isolation discipline (sibling).
- [[perf-smoke-filter-expected-warning-categories-by-name-not-rule-list-2026-05-27]] — the companion 0.7.1 fix on the same test module.
- first-public-push-plan-for-ci-iteration-debugging-2026-05-27 — the meta-learning that surfaced this whole cluster. A test gated to a single CI cell is exactly the shape of bug that hides until the first public CI run.
- Canonical commit: `b22d60a` ("fix: pin protobuf<6 + restructure perf-smoke fixture per-package directory").
