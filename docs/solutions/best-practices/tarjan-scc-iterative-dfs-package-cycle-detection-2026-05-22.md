---
title: Tarjan SCC with iterative DFS for package-level cycle detection in cross-file lint rules
date: 2026-05-22
last_updated: 2026-05-22
category: docs/solutions/best-practices
module: protokit.schema.lint.engine
problem_type: best_practice
component: lint_engine
severity: high
applies_when:
  - A new cross-file lint rule needs to detect cycles in a graph derived from descriptor-level relationships (imports, references, etc.)
  - The rule emits per-file findings whose set must match an external tool's output (buf-parity case)
  - The graph has nodes that can form strongly-connected components of arbitrary size (multiple cycles, deeply nested SCCs, transitive participation)
  - The lint rule must distinguish cycle members from non-cycle members (size ≥ 2 SCC vs size 1 SCC)
  - The lint rule must render cycle paths in a buf-equivalent forward direction (following actual edges, not Tarjan's lexicographic SCC member order)
related_components:
  - engine
  - lint_rules
tags:
  - tarjan-scc
  - cycle-detection
  - cross-file-lint
  - iterative-dfs
  - recursion-limit
  - package-graph
  - new-institutional-knowledge
---

# Tarjan SCC with iterative DFS for package-level cycle detection in cross-file lint rules

## Context

D6e U3 shipped `package/no-import-cycle` — protokit's first lint rule requiring strongly-connected-component (SCC) analysis on a package-level import graph. No prior protokit work involved cycle detection of any kind. The implementation introduced two new module-level helpers in `src/protokit/schema/lint/engine.py`:

1. `_tarjan_scc(graph)` — hand-implemented iterative Tarjan SCC enumeration.
2. `_walk_cycle_forward(package_edges, scc_member_set, source_pkg)` — iterative DFS within an SCC, following actual graph edges to render the cycle path starting at `source_pkg` and closing back to it.

Both functions operate on the same package-level graph constructed by `_build_import_graph_accumulator` (a new Step 3.5c pre-walk accumulator mirroring the D6c Arch-D `_build_directory_package_accumulator` pattern).

## The decision tree this learning captures

When a new cross-file lint rule needs cycle detection, the codified design choices are:

### Why Tarjan SCC, not back-edge detection or topological sort

- **`graphlib.TopologicalSorter`**: detects DAG-ness but does NOT enumerate SCCs. If the only requirement is "is there a cycle", topological sort suffices. If the requirement is "which nodes participate in which cycle, and report findings per-node", Tarjan is the minimal algorithm.
- **DFS back-edge detection**: ~15 LOC; detects cycle existence but does not enumerate SCC membership. Insufficient when the rule must distinguish cycle members from non-members.
- **Tarjan SCC**: ~80 LOC hand-implemented; produces SCC artifacts directly. Choose this when the rule emits at the per-SCC or per-member granularity.

The trade-off: ~30-50 LOC extra over back-edge detection buys the SCC enumeration artifact. For any rule whose findings need to reference cycle membership (which packages are in the cycle, render the cycle path, suppress sibling files outside the cycle), this is non-negotiable.

### Why iterative, not recursive

Python's default recursion limit is 1000. Recursive Tarjan on a package graph with > 990 packages raises `RecursionError`, which is `RuntimeError` and is NOT in `_RULE_EXCEPTION_TUPLE`. The exception propagates uncaught through the accumulator and crashes `engine.run()` with no `LintReport` returned.

The iterative form uses an explicit work stack with `(node, iter(sorted(children)))` frames. Backtracking pops both the work-stack frame AND the path/visited bookkeeping together. Bounded memory cost is O(SCC size), same as the recursive form, but without consuming Python frames.

**This discipline applies to ALL DFS-style helpers operating on the same graph, not just Tarjan.** D6e U3's initial implementation made `_walk_cycle_forward` recursive while `_tarjan_scc` was iterative. ce:review (run 20260522-230615-e23aa0e2) flagged this asymmetry across 5 reviewers; adversarial empirically confirmed `_walk_cycle_forward` crashed at 999-node ring SCCs. The follow-up commit (`eff3a80`) converted `_walk_cycle_forward` to iterative DFS with the same explicit-work-stack pattern. **If you're going iterative on Tarjan for recursion-limit safety, every helper operating on the same graph must follow the same posture.**

### Why per-import-edge emission, not per-root-file fan-out

The brainstorm + plan PD-6 originally bound the emission shape to "per-root-file fan-out: each root file in an SCC of size ≥ 2 gets one finding." Phase 0 of U3 empirically verified buf v1.69.0's actual behavior is **per-import-edge**: one finding per cycle-closing `import` statement, pointing at the import's line/column. Sibling "leaf" files in cyclic packages that don't have cycle-closing imports themselves do NOT emit findings.

The plan was revised (commit `5643939`) to bind PD-6/PD-7/PD-8 to per-import-edge granularity. The `leaf_files_in_cyclic_pkg` fixture pins this as a regression guard.

The general lesson: **buf-parity emission shape is empirical, not derivable from the rule name.** Phase 0 fixture authoring + capture of recorded snapshots is the cheap detection surface for emission-shape divergence from brainstorm assumptions.

### Why forward cycle traversal, not Tarjan member order

Tarjan SCC returns members in reverse DFS-finish order. For a 3-package cycle `A → B → C → A`, Tarjan may return `['C', 'B', 'A']`. Buf v1.69.0 renders the cycle following actual import edges: `"Package import cycle: acme.a -> acme.b -> acme.c -> acme.a"`. Simple rotation of Tarjan's output gives `"acme.a -> acme.c -> acme.b -> acme.a"` (wrong direction).

The fix is a separate helper (`_walk_cycle_forward`) that does DFS within the SCC following the actual graph edges, starting at the source file's package and closing back to it. The helper is iterative (per the recursion-limit discipline above).

D6e U3's commit `e66f27c` initially included a dead `_rotate_cycle_for_source` function from the design-phase rotation approach. ce:review flagged it as a future-author trap (5-way reviewer convergence at 0.95+ confidence) and the follow-up commit deleted it. **Dead design-phase helpers should be deleted, not preserved as "alternative implementations".**

## Architecture: the pre-walk accumulator pattern

The cycle-detection algorithm runs at engine pre-walk time, NOT per-file:

```
engine.run():
  Step 3:   Build package_options accumulator (R7 family)
  Step 3.5: Build per-package directory accumulator (D6c Arch-D)
  Step 3.5b: (sibling — directory inverted index)
  Step 3.5c: Build import-graph accumulator (D6e U3 — NEW)
    └─ _build_import_graph_accumulator(compile_result)
       ├─ For each root_file: read fdp.dependency via CopyToProto
       ├─ Build package_edges: {src_pkg: set[dep_pkg]} (intra-package skipped)
       ├─ Run _tarjan_scc(package_edges) → list[list[str]]
       ├─ Filter to SCCs of size >= 2 (cyclic SCCs)
       ├─ For each root file in a cyclic package:
       │  └─ For each cycle-closing import edge:
       │     └─ Build CycleEdge(imported_file, target_package, cycle_path, line, column)
       └─ Return MappingProxyType({file_name: tuple[CycleEdge, ...]})
  Step 4:   Per-file walk (rule callables consume ctx.import_cycles)
  finally:  Reset self._current_import_cycles = None
```

Threaded into `FileLintContext.import_cycles` (`Mapping[str, tuple[CycleEdge, ...]] | None`) so the rule body is cheap-check-first early-return on None or empty.

**This shape extends the D6c Arch-D pre-walk pattern with three new features:**
- Reads `compile_result.source_info_descriptors` (not `fd.CopyToProto(fdp).source_code_info`) for source positions — the DescriptorPool strips source_code_info on `pool.Add()` per [[copytoproto-round-trip-for-proto-form-only-descriptor-fields-2026-05-13]]; the separate `source_info_descriptors` bag is the only persistent path.
- Caches per-`src_pkg` SCC member set + cycle path before the inner edge loop (avoids per-edge DFS re-runs with loop-invariant arguments — ce:review PERF-1 follow-up in `eff3a80`).
- Two-tier exception handling: outer `try/except KeyError` for `FindFileByName`, inner `try/except DecodeError` for `CopyToProto` (ce:review REL-1 follow-up in `eff3a80`).

## Performance characteristics

For the common case (no cycles in the codebase):
- O(root_files × deps_per_file) for graph construction
- O(packages + edges) for Tarjan
- O(0) for fan-out — returns empty `MappingProxyType` early
- Per-rule cost: O(0) (early-return on empty mapping)

For codebases with cycles:
- Above + O(packages_in_cycle × avg_edges) for the forward DFS
- Per-import-edge: one finding emitted at FileLocation(file, line, column)

## When to apply this pattern

Use Tarjan SCC + iterative DFS for any future cross-file lint rule that:

1. Operates on a graph derived from descriptor relationships (imports, references, type usages, options-aware dependency graphs)
2. Needs to enumerate cycle MEMBERSHIP (not just existence)
3. Requires per-edge or per-node emission inside the cycle

Do NOT use this pattern for:

- Single-file rules (no cross-file graph; use existing FieldLintContext/MessageLintContext)
- DAG-only validation (use `graphlib.TopologicalSorter`)
- "Does any cycle exist" boolean checks (DFS back-edge detection is simpler)

## Related disciplines

- [[dual-view-prewalk-accumulator-cross-file-rule-dispatch-2026-05-19]] — single-view variant of this pattern when only one rule consumes the accumulator.
- [[copytoproto-round-trip-for-proto-form-only-descriptor-fields-2026-05-13]] — the CopyToProto round-trip used to access `fdp.dependency`; note the source_code_info-stripping nuance for source positions.
- [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]] — Phase 0 fixture authoring discipline; this learning extends it with cycle-detection specific guidance.
- [[family-aware-partition-pattern-multi-family-parity-harness-2026-05-19]] — the per-family conftest constants pattern (`_D6E_PACKAGE_NO_IMPORT_CYCLE_*` follows this).
- [[closed-literal-discriminator-bump-trigger-2026-05-17]] — used to confirm the FileLocation.line/column extension is open extension (no schema version bump).
- [[parity-gate-must-assert-at-design-claim-granularity-2026-05-22]] (sibling learning captured at same boundary) — when the design claim is "byte-equivalent at line/column granularity", the parity gate must compare at that granularity, not just at file/message granularity.
- [[phase-0-narrowing-rule-reachable-but-narrower-than-brainstorm-assumed-2026-05-22]] (sibling learning captured at same boundary) — the file-level-cycles-caught-at-COMPILE-phase finding from U3 Phase 0.

## Worked example

The full D6e U3 implementation is the canonical worked example:

- `src/protokit/schema/lint/engine.py:_tarjan_scc` — iterative Tarjan SCC
- `src/protokit/schema/lint/engine.py:_walk_cycle_forward` — iterative DFS forward cycle traversal (post-ce:review revision)
- `src/protokit/schema/lint/engine.py:_import_source_position` — SourceCodeInfo.Location reader keyed on `path=[3, dep_index]`
- `src/protokit/schema/lint/engine.py:_build_import_graph_accumulator` — Step 3.5c pre-walk
- `src/protokit/schema/lint/rules/package.py:check_package_no_import_cycle` — rule body consuming `ctx.import_cycles`
- `tests/schema/lint/rules/fixtures/package_no_import_cycle/_buf_smoke/*` — 5 multi-file fixtures + recorded NDJSON snapshots
- `tests/parity/test_parity_package_no_import_cycle.py` — parity gate with both finding-set and line/column assertions

Commit sequence on branch `feat/d6e-buf-basic-closure-and-philosophy-revision`:

1. `5643939 docs(plans): D6e U3 Phase 0 OQ-1/2/3 binding + PD-6/7/8 revision` — Phase 0 findings
2. `e66f27c feat(lint): D6e U3 — package/no-import-cycle (26th buf BASIC rule) via Tarjan SCC pre-walk` — initial implementation
3. `eff3a80 fix(lint): ce:review U3 follow-ups — 5 P1 + 6 safe_auto` — recursion-limit safety + dead-code removal + line/column assertion + perf cache + DecodeError handling + migration recipe
4. `<this commit> docs(solutions): D6e U3 ce:compound` — three institutional learnings (this file + two siblings)
