---
title: Dual-view pre-walk accumulator — build by_package + by_directory in one pass for cross-file rule dispatch
date: 2026-05-19
category: docs/solutions/best-practices
module: protokit.schema.lint.engine
problem_type: best_practice
component: tooling
severity: high
applies_when:
  - Shipping cross-file rule infrastructure (a pre-walk accumulator) for a rule family where two rules require different primary access patterns over the same source data
  - One rule needs lookup by logical key (package → files), the other needs lookup by structural key (directory → packages)
  - The per-invocation pass over `compile_result` is fixed-cost and small relative to the size of both derived views
  - An adversarial ce:review reviewer flags an O(N²) access-pattern risk against an explicit SC benchmark (e.g., 50ms at 10k files)
related_components:
  - testing_framework
  - development_workflow
tags:
  - accumulator
  - inverted-index
  - cross-file-rules
  - performance
  - ce-review-adversarial
  - pre-walk
  - mappingproxytype
  - frozenset
  - access-pattern
  - sibling-pattern-divergence
  - root-files-scope
---

# Dual-view pre-walk accumulator — build by_package + by_directory in one pass

## Context

D6c U1 shipped the cross-file dispatch infrastructure (an Arch-D pre-walk accumulator) needed by the upcoming R8 (`package/same-directory`) and R8b (`package/directory-same-package`) rules. The initial design shaped the accumulator as a single `Mapping[pkg, Mapping[fname, dirname]]` — R8's natural view: given a package, what directories do its files span?

During ce:review (run `20260519-074830`, 8 reviewers in parallel), the adversarial reviewer surfaced ADV-1 at P2/0.82:

> "Accumulator shape `pkg→fname→dirname` locks R8b into O(N²) per-file scan before U2 ships."

R8b's planned access pattern (from the plan: "iterate `ctx.directory_packages` to collect `{pkg: dirs}` where `current_dir` in `dirs.values()`") required scanning ALL packages × ALL files to find which files belong to the current directory — O(N) per file × N files = O(N²) total. At 10,000 files this is 100M iterations, breaching the plan's 50ms SC E7 benchmark.

A single-view accumulator optimized for R8 is the wrong shape for R8b, and fixing the access pattern after R8b ships is more expensive than fixing it before U2 begins. The adversarial reviewer caught this BEFORE the bug shipped, at lower fix cost than the parity-gate catches described in [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]].

The user chose option (a): add an inverted index alongside the existing structure in the same single pass, threading both views into `FileLintContext`. Commit `94eb76d` on branch `feat/d6c-u1-arch-d-accumulator`.

## Guidance

**Build both views in a single pass over `root_files`; populate them together; wrap them together.**

The core pattern:

```python
def _build_directory_package_accumulator(
    compile_result: CompileResult,
) -> tuple[
    Mapping[str, Mapping[str, str]] | None,                       # by_package
    Mapping[str, Mapping[str, frozenset[str]]] | None,            # by_directory
]:
    """Build two complementary views over root_files in one pass.

    by_package  : pkg → fname → dirname             (R8's primary view)
    by_directory: dirname → pkg → frozenset[fname]  (R8b's primary view)

    Both are fully immutable (2-level MappingProxyType; sets wrapped in
    frozenset). Both are reset together in run()'s finally block.
    """
    if not compile_result.root_files:
        return (None, None)

    _by_package: dict[str, dict[str, str]] = {}
    _by_directory: dict[str, dict[str, set[str]]] = {}

    for fname in sorted(compile_result.root_files, key=...):
        try:
            fd = compile_result.pool.FindFileByName(fname)
        except KeyError:
            continue
        pkg = fd.package
        dirname = posixpath.dirname(fname) or "."

        # Populate the by_package view (R8's primary access).
        _by_package.setdefault(pkg, {})[fname] = dirname

        # Populate the by_directory inverted view (R8b's primary access).
        _by_directory.setdefault(dirname, {}).setdefault(pkg, set()).add(fname)

    by_package = MappingProxyType(
        {pkg: MappingProxyType(fmap) for pkg, fmap in _by_package.items()}
    )
    by_directory = MappingProxyType(
        {
            d: MappingProxyType(
                {pkg: frozenset(fnames) for pkg, fnames in pmap.items()}
            )
            for d, pmap in _by_directory.items()
        }
    )
    return (by_package, by_directory)
```

**Use `frozenset` for innermost collections that are sets, `MappingProxyType` for dicts.** `MappingProxyType` only wraps dicts; there is no direct immutable analog for sets. `frozenset` fills that role for the innermost `set[fname]` collections in `by_directory`. Applying immutability at every level (2-level `MappingProxyType` + innermost `frozenset`) prevents rules from accidentally mutating accumulator state during a lint run.

**Thread BOTH views as separate fields on `FileLintContext`.**

```python
@dataclass(frozen=True)
class FileLintContext(_LintContextEmitMixin):
    ...
    # R8's primary view: lookup by package name → set of (fname, dirname).
    directory_packages: Mapping[str, Mapping[str, str]] | None = None
    # R8b's primary view: lookup by directory → set of (pkg, fnames-in-dir).
    directory_packages_by_dir: (
        Mapping[str, Mapping[str, frozenset[str]]] | None
    ) = None
```

Both fields default to `None` so test helpers can construct `FileLintContext` without threading the kwargs; engine threads explicitly via `_build_file_ctx`. Both fields classified INTERNAL per the Public Surface DRAFT — downstream rule authors access them through the named ctx fields, not through any public API.

**Reset both views together in `run()`'s `finally` block.** The two views are logically coupled; a partially-reset state (one view cleared, the other stale) would produce silent mis-attributions if an exception escapes between the two resets. Co-locate the reset calls:

```python
finally:
    ...
    # Clear the per-run directory_packages accumulators — both views together.
    self._current_directory_packages = None
    self._current_directory_packages_by_dir = None
```

**Scope the accumulator to `root_files`, NOT `pool_file_names`.** This is a deliberate divergence from the sibling `_build_package_options_accumulator` (R7), which iterates `pool_file_names` for cross-import language-namespace conflicts. buf v1.69.0 does NOT cross-fire `PACKAGE_SAME_DIRECTORY` / `DIRECTORY_SAME_PACKAGE` across module boundaries; restricting to `root_files` matches the reference tool's empirical behavior. The KTD-4 (d) empirical correction is itself an instance of audit-wire-format-before-claiming-sibling-parity-2026-05-03 — the brainstorm originally assumed R8 would mirror R7's pool-scope; empirical verification at brainstorm time inverted the decision.

The counterfactual is documented in the engine.py method docstring: "Correcting this back to `pool_file_names` would cause R8/R8b to fire on transitively-imported files outside the user's control — spurious findings on every `vendor/`-style import."

**Document the "DO NOT unify" constraint explicitly in the engine module docstring.** Both sibling pre-walk accumulators (`_build_package_options_accumulator` for R7 and `_build_directory_package_accumulator` for R8/R8b) look similar at a glance but have intentionally different iteration scopes (`pool_file_names` vs `root_files`). A future maintainer unifying them into a single loop would reintroduce the spurious-vendor-import bug. The module docstring must enumerate both by name and explicitly label the intentional asymmetry. See [[multi-mechanism-fix-docstring-enumerate-each-layer-failure-mode-2026-05-18]] for the three-mechanism enumeration discipline that applies here.

## Why This Matters

**Catches O(N²) before the parity gate, not after.** The adversarial reviewer surfacing ADV-1 at 0.82 confidence (above the 0.60 gate; no cross-reviewer convergence needed) prevented the access-pattern lock-in from reaching U2's parity gate. Earlier detection = lower fix cost: fixing accumulator shape before U2 ships is a 1-commit refactor; fixing it after U2 ships would require rewriting R8b's rule logic AND the accumulator simultaneously while keeping the parity gate green. (auto memory [claude]: the empirical-parity-gate learning documents 3 prior instances where latent bugs were caught later — at parity-gate time rather than at review time; this is the 4th instance in the series but detected earliest.)

**Eliminates per-rule-family redundancy.** Without the inverted index, R8b's rule implementation would have needed to build its own `dirname → packages` index on every invocation (once per file, inside the rule's `check()` method). Moving that construction to the pre-walk accumulator means it is built once per `engine.run()` call regardless of how many files the run covers.

**Locks the downstream-rule access pattern to O(1) per file.** With `by_directory`, R8b's per-file check reduces to a single dict lookup (`ctx.directory_packages_by_dir[current_dir]`) followed by iteration over the packages in that directory — O(D_avg) per file where D_avg is the average number of distinct packages per directory, typically 1–2. Total cost O(N × D_avg) ≪ O(N²).

**Immutability-at-every-level prevents accumulator mutation bugs.** A rule that accidentally modifies a `set` inside `by_directory` would corrupt all subsequent rules' views of that directory within the same `engine.run()` call. `frozenset` at the innermost level makes such a mutation a `TypeError` rather than a silent data corruption.

**Pre-shipping detection economics** (cross-references ce-review-convergence-rescues-sub-threshold-findings-2026-05-17): ADV-1 at single-reviewer P2/0.82 cleared the 0.60 confidence gate WITHOUT cross-reviewer convergence. The high single-reviewer confidence + concrete arithmetic in the finding body (specific 10k-file → 100M-iteration derivation against the 50ms benchmark) was sufficient. Not every adversarial finding requires consensus; this is the BOOST mode (not RESCUE) for the convergence-rescue pattern. (auto memory [claude])

## When to Apply

Apply this pattern when ALL of the following hold:

1. **Two rules in the same family require complementary primary access patterns** over the same source data (e.g., "lookup by package" and "lookup by directory" over the same `root_files`).
2. **The per-invocation construction pass is fixed-cost** — the accumulator is built once per `engine.run()` regardless of the number of rules that consume it.
3. **The access pattern of a downstream rule would be O(N) or worse per file** if it operated directly on the primary-view accumulator shape.
4. **A ce:review adversarial reviewer (or an explicit SC performance benchmark)** has flagged the access-pattern mismatch before the downstream rule ships.

Do NOT apply this pattern when:

- Only one rule consumes the accumulator (single-view is simpler; add the inverted index only when the second rule's access pattern is known).
- The two access patterns can share a single traversal inside the rule's `check()` method without O(N²) complexity (e.g., single-pass linear scan with early exit).
- The accumulator scope differs between the two rules (e.g., one rule needs `root_files`, the other needs `pool_file_names`): separate accumulators with separate scopes are cleaner than a single dual-view accumulator with mixed-scope semantics.

## Examples

### Before — single-view accumulator (R8's shape, locks R8b into O(N²))

```python
# Accumulator shape: pkg → fname → dirname
FileLintContext:
    directory_packages: Mapping[str, Mapping[str, str]]

# R8's access (O(1)):
dirs = {d for d in ctx.directory_packages[pkg].values()}

# R8b's intended access (O(N²) — scans ALL packages × ALL files):
packages_in_dir = {
    pkg: dirs
    for pkg, fmap in ctx.directory_packages.items()
    for d in fmap.values()
    if d == current_dir
}
# At 10k files, 100M iterations → breaches 50ms SC E7 benchmark.
```

### After — dual-view accumulator (both shapes built in one pass)

```python
# Two views, one pass.
FileLintContext:
    directory_packages:         Mapping[str, Mapping[str, str]]
    directory_packages_by_dir:  Mapping[str, Mapping[str, frozenset[str]]]

# R8's access (unchanged, O(1)):
dirs = {d for d in ctx.directory_packages[pkg].values()}

# R8b's access (now O(1) lookup + O(D_avg) iteration):
packages_in_dir = ctx.directory_packages_by_dir.get(current_dir, {})
# packages_in_dir: {pkg: frozenset[fname]} — pre-built.
```

### Test coverage: `TestInvertedIndexView` (4 of 15 tests in test module)

```python
class TestInvertedIndexView:
    """Per-directory inverted index ``directory_packages_by_dir`` (R8b view).

    Resolves ce:review ADV-1: the per-package view alone would force R8b
    into O(N) per-file scan over all packages to find files in the
    current dir = O(N^2) total across N root files. The inverted index
    gives R8b O(1) directory-keyed lookup.
    """

    def test_inverted_index_keyed_by_directory(self, ...) -> None: ...
    def test_inverted_index_empty_package_under_empty_string_key(self, ...) -> None: ...
    def test_inverted_index_consistent_with_per_package_view(self, ...) -> None:
        """Both views reflect the same triples — cross-validation.

        Reconstruct the (pkg, fname, dirname) triple set from each view;
        assert set-equality. Catches drift between by_pkg and by_dir if
        a future refactor only updates one side.
        """
    def test_inverted_index_inner_value_is_frozenset(self, ...) -> None:
        """Inner fname collection is frozenset (immutable by construction)."""
```

The cross-validation test (`test_inverted_index_consistent_with_per_package_view`) is the load-bearing test — it catches any drift between the two views by reconstructing triples from each and asserting set-equality. This is the closest analog of the discriminating-fixture invariant from [[capture-setup-without-dispatch-false-test-confidence-2026-05-17]] for dual-view accumulators: the test would fail if a future refactor updated only one view.

### Anti-patterns

**Anti-pattern 1 — deferred single-view (locks R8b before U2 ships):**

```python
# Bad: ship R8 with single-view, plan to "add inverted index in U2 alongside R8b".
# Cost: U2 must refactor the accumulator, change FileLintContext, migrate R8's
# field reference, and ship all three changes atomically without breaking the
# parity gate. One-pass dual-view at U1 costs ~30 LOC additional; deferred
# refactor costs 3× as many touchpoints.
```

**Anti-pattern 2 — per-file index rebuild inside rule check():**

```python
# Bad: each R8b invocation rebuilds its own dirname→packages index.
def check(self, ctx: FileLintContext, fd: FileDescriptorProto) -> ...:
    current_dir = posixpath.dirname(ctx.fname) or "."
    packages_in_dir = {}
    for pkg, fmap in ctx.directory_packages.items():   # O(N) scan
        for fname, d in fmap.items():                   # O(N) inner scan
            if d == current_dir:
                packages_in_dir.setdefault(pkg, set()).add(fname)
    # O(N²) total across all files.
```

**Anti-pattern 3 — unifying both accumulator scopes:**

```python
# Bad: use pool_file_names for both (R7's scope) to "simplify to one loop".
# Consequence: R8/R8b fire on transitively-imported vendor files outside the
# user's control — spurious findings on every proto dependency import.
# The two sibling accumulators have intentionally different scopes.
# See engine.py module docstring "DO NOT unify" clause.
```

## Related

- ce-review-convergence-rescues-sub-threshold-findings-2026-05-17 — ADV-1 at P2/0.82 cleared the 0.60 gate without cross-reviewer convergence. Single-reviewer BOOST mode (high confidence + concrete arithmetic in the finding body) is sufficient when the adversarial reviewer provides the O(N²) derivation. (auto memory [claude])
- [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]] — contrast in detection timing: this learning documents pre-shipping detection (adversarial ce:review at U1 ce:review pass, before U2 ships); that learning documents post-shipping detection (parity gate on first run). Earlier detection has lower fix cost; both mechanisms are needed in the overall pipeline.
- [[multi-mechanism-fix-docstring-enumerate-each-layer-failure-mode-2026-05-18]] — applies to the engine.py module docstring update enumerating both sibling pre-walk accumulators with explicit "DO NOT unify" guard. Each accumulator has a distinct scope and failure mode if unified; the docstring must enumerate both. (auto memory [claude])
- audit-wire-format-before-claiming-sibling-parity-2026-05-03 — KTD-4 (d) `pool_file_names` → `root_files` inversion is a direct instance of this discipline. The brainstorm originally inherited R7's pool-scope by analogy; empirical verification against buf v1.69.0's module-boundary behavior corrected it before U1 implementation began. This learning's "audit before claiming sibling parity" rule is the meta-pattern; KTD-4 (d) is a concrete application.
- [[capture-setup-without-dispatch-false-test-confidence-2026-05-17]] — the test-discipline complement to this design discipline. That doc covers HOW to write tests that actually discriminate accumulator-iteration-scope regressions; this doc covers HOW to design the accumulator's shape to avoid downstream O(N²). The cross-validation test (`test_inverted_index_consistent_with_per_package_view`) applies that doc's discriminating-fixture principle to dual-view accumulators.
- dormant-code-changelog-draft-staging-delivery-boundary-2026-05-17 — the dormancy-window staging pattern for R8/R8b. The dual-view accumulator is part of the Arch-D pre-walk infrastructure that ships dormant (engine plumbing in U1) until R8's U2 delivery activates rule consumers.
- [[programmatic-proto-fixture-builder-multi-file-rule-family-2026-05-17]] — the programmatic fixture builder for the R8/R8b rule family's tests. The `TestInvertedIndexView` test class consumes programmatically-built multi-file packages to assert inverse relational consistency.
- [[pureposixpath-for-proto-descriptor-file-stem-2026-05-12]] — directory grouping via `posixpath.dirname(fd.name) or "."` is the mechanical dependency for the by-directory view's dirname key. Cross-platform determinism (POSIX semantics for descriptor paths regardless of host OS).
- `src/protokit/schema/lint/engine.py::_build_directory_package_accumulator` — reference implementation (commit `83b95d3`). Method docstring enumerates: (a) `root_files` scope rationale + "DO NOT unify" counterfactual, (b) frozenset-vs-MappingProxyType immutability contract, (c) co-reset discipline.
- `tests/schema/lint/test_engine_directory_package_accumulator.py` — 15 tests (11 original + 4 new `TestInvertedIndexView` from ce:review follow-up). Suite: 1921 passed + 7 skipped (was 1906 + 7 baseline).
