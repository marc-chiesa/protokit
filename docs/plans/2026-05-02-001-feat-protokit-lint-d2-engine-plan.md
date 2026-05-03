---
title: "feat: protokit-lint Delivery 2 (engine + canary)"
type: feat
status: active
date: 2026-05-02
origin: docs/brainstorms/2026-05-02-protokit-lint-delivery-2-engine-requirements.md
---

# feat: protokit-lint Delivery 2 — Engine + Canary

## Overview

D2 closes the `_emit_fn` loop that D1's eight lint contexts declare
but never invoke end-to-end. Ships:

1. The descriptor-tree-walking `LintEngine` (per-instance loaded-rule
   dict, walk-level `full_name` sort, narrow-catch failure
   containment, atomic rule-pack loading).
2. A pure-metadata `@lint_rule` decorator that attaches a
   `LintRuleSpec` to the decorated function as `fn._lint_spec`.
   **No process-global registry, no module-attribute side effects.**
3. Three new types in `lint/model.py`: `LintRuntimeWarning` (with a
   `category` discriminator that mirrors `LintCompileDiagnostic`'s
   pattern), `LintRuleError` (Exception subclass for rule authors),
   and two new defaulted fields on `LintReport`
   (`runtime_warnings`, `filtered_count`).
4. `LintProfile.from_pack(module, profile_name)` classmethod that
   walks `module.RULES` directly to derive a profile from a rule
   pack's declared profile membership.
5. The canary rule `naming/snake-case-fields` shipped as the
   inaugural built-in pack at `lint/rules/naming.py`, exposing a
   module-level `RULES` tuple (echoing compat's `module.RULES`
   attribute pattern at `schema/checker.py:217-220`).
6. Eight synthetic per-`ElementKind` walk tests + a cross-file
   boundary test + severity-override / `filtered_count` test +
   canary integration tests, plus a verification pass confirming
   D1's static-analysis ratchet's directory globs auto-cover the
   new files.

No CLI ships in D2 (D3); no formatters (D4); no additional rules
(D6); no plugin API (D7). The engine is exercised exclusively via
library calls in tests.

## Problem Frame

D1 (commits `0b82fc3`, `e85faea`, `31c0bb1` on 2026-05-02) locked
the lint-side type system, the public compile entry point
(`compile_protos_to_result`), the helper-refactor for
`_compile_with_protoxy` / `_compile_with_protoc`, the 4-job CI
matrix (`python: ["3.10", "3.12"] × has_protoxy: [true, false]`),
and the pytest-driven static-analysis gate. Every subsequent
delivery (CLI, formatters, config, rule packs, plugin API) imports
against locked types from D1 — but D1 produced **no lint output**.
Each lint context's `_emit_fn` is declared and never invoked.

D2 closes that loop. The engine is the bridge between
`compile_result.root_files` and `LintReport.findings`. Five
downstream deliveries cannot land without it.

The plan resolves two structural concerns surfaced by review.

**(1) Registry shape.** The brainstorm chose a process-global
sidecar `_RULE_PACK_REGISTRY` dict, keyed by `fn.__module__`. The
plan revises this to mirror compat's actual pattern (verified at
`schema/checker.py:136-143, 217-220`): per-instance state only, no
process-global, with `@lint_rule` attaching `LintRuleSpec` to the
decorated function and rule pack modules exposing a `RULES` tuple.
This dissolves the test-isolation, `importlib.reload`, mypy-strict
attribute-typing, and `fn.__module__`-key concerns by construction.
The protobuf-pool analogy (Default + local pools) supports an
optional global default later, but D2 doesn't need it; the simplest
expression is per-instance only, matching compat.

**(2) SystemExit at rule-callable boundary.** D1's `R16` posture
said "BaseException-but-not-Exception propagates uncaught", but a
library-API engine that returns a `LintReport` cannot let a rule
silently call `sys.exit(0)` without making `engine.run` never return
results — the caller sees a clean exit and concludes no findings
exist. The plan **explicitly catches `SystemExit`** at the
rule-callable boundary and converts it to a
`LintRuntimeWarning(category="rule_exception")`. The formatter
SystemExit P0 learning (2026-04-19) is informative but not load-
bearing: it deliberately limited its fix to formatters. The
D2-specific reason — library functions should not silently terminate
their caller's process — stands on its own. See Key Technical
Decisions for the full rationale and trade-off.

(see origin: `docs/brainstorms/2026-05-02-protokit-lint-delivery-2-engine-requirements.md`)

## Requirements Trace

Every requirement from the origin doc is addressed below; IDs match
the origin.

**Engine surface**
- R1, R2, R3 — Unit 3 (engine.py) + Unit 1 (model.py runtime_warnings/filtered_count fields)

**Walk semantics**
- R4 — Unit 3 (`_walk_root_files` iterates only `compile_result.root_files`)
- R5 — Unit 3 (top-down dispatch order: FILE → SERVICE/METHOD → ENUM/ENUM_VALUE → MESSAGE/FIELD/ONEOF/nested)
- R6 — Unit 3 (`_sorted_by_full_name` helper; per-level sort)
- R6a — Documented under Scope Boundaries; vendored-proto linting handled via rebuild-`CompileResult`

**Rule registration**
- R7 — Unit 2 (`@lint_rule(*, rule_id, severity, profiles, element, message_template, source_spec="")`)
- R8 — **Revised:** Unit 2 (decorator attaches `LintRuleSpec` to the decorated fn as `fn._lint_spec`; no global registry; rule pack modules expose `RULES: tuple[Callable, ...]`)
- R9 — **Revised:** Unit 3 (`load_rule_pack(module: ModuleType)` reads `module.RULES`, extracts `_lint_spec` from each fn, registers per-instance — mirrors compat's `SchemaChecker.load_rule_pack` exactly)
- R9a — Unit 3 (`reset()` clears engine state; loaded-module-names tracking via `set[str]` keyed on `module.__name__`)
- R10 — Unit 3 (atomic `load_rule_pack`: stage-then-commit. Cross-pack `rule_id` collision raises `DuplicateRuleError` BEFORE engine state is mutated)

**Rule selection**
- R11 — Unit 3 (engine reads only `profile.rule_ids`)
- R11a — Unit 1 (`LintProfile.from_pack(module, profile_name)` classmethod walks `module.RULES` directly — no deferred imports needed since there's no global registry to break a circular)
- R12 — Unit 3 (empty `rule_ids` short-circuits to empty findings)
- R13 — Unit 3 (unloaded-rule diff computed once at `run()` entry)

**Severity resolution**
- R14 — Unit 3 (`_effective_severity` closure constructed per-context)
- R15 — Unit 3 (filter-at-emit; `filtered_count` increment)

**Rule failure containment**
- R16 — Unit 3 (narrow catch tuple: `(SystemExit, ValueError, TypeError, KeyError, AttributeError, LookupError, LintRuleError)`); plan-side amendment to brainstorm R16 documented in Key Technical Decisions
- R17, R18 — Unit 1 (`LintRuntimeWarning` with `category` discriminator + `runtime_warnings`/`filtered_count` fields)

**Canary rule**
- R19, R20, R21, R22 — Unit 4 (`lint/rules/naming.py` with `RULES = (check_snake_case_fields,)`)

**Scope hygiene**
- R23 — All units (no modifications to `protokit/__init__.py`, `schema/__init__.py`, `formatters/__init__.py`); cold-import smoke step continues to pass
- R24 — All units (no new runtime deps)

## Scope Boundaries

- **No CLI** — `protokit lint` ships in D3. D2's engine is exercised only via library calls in tests.
- **No formatters** — `LintReport` rendering (human / json / junit / sarif) ships in D4. D2 tests inspect the report dataclass directly.
- **No pyproject config** — D5 reads `[tool.protokit.lint]`. D2 has no awareness of `pyproject.toml`.
- **No additional built-in rules** — only `naming/snake-case-fields`. D6 adds the rest.
- **No plugin API** — D7 ships `--lint-rule-pack` and parity with compat's `--rule-pack`.
- **No async rule support** — Unit 2's decorator rejects `async def` rules at registration with a clear `TypeError`. Async lint as a whole is in the separate "async plugin support" TODO.
- **No profile-name registry** — engine takes a `LintProfile` instance only. `LintProfile.from_pack` is the D2-side derivation primitive; string-name resolution is D5's job.
- **No process-global rule registry** — registration is per-`LintEngine` instance only. A global default registry (à la `descriptor_pool.Default()`) is a deliberate non-goal for D2; if real users need one in D6/D7, it lands as an additive convenience layer (a module-level `default_engine = LintEngine()`) without touching D2's contracts.
- **No auto-load of built-in rules at import time** — Unit 4's `lint/rules/naming.py` is loaded only when callers explicitly do `import protokit.schema.lint.rules.naming as naming_pack` and pass it to `engine.load_rule_pack(naming_pack)`. Whether D3's CLI eager-loads the built-in pack is a D3 decision.

### Deferred to Separate Tasks

- **D3 CLI subcommand** — separate brainstorm/plan; consumes D2's engine + Unit 4's canary
- **D4 `_builtin_lint` formatters** — separate brainstorm/plan; consumes Unit 1's `LintReport` shape
- **D5 pyproject config** — separate brainstorm/plan
- **D6 additional rule packs** — separate brainstorm/plan; uses Unit 2's `@lint_rule` + Unit 3's engine
- **D7 plugin API** — separate brainstorm/plan; symmetrizes the compat rule-pack flag
- **Optional global default registry** — only if D6/D7 surfaces real demand from rule pack authors

## Context & Research

### Relevant Code and Patterns

- **Compat sibling architecture** — `src/protokit/schema/checker.py`. `SchemaChecker.__init__` initializes `self._field_rules`, `self._enum_rules`, `self._message_rules` per-instance (lines 136-143); built-in rules are imported as module-level constants (`FIELD_RULES`, `ENUM_RULES`, `MESSAGE_RULES`) and copied into the instance via `list(FIELD_RULES) if include_builtin else []`; `load_rule_pack(module: ModuleType)` reads `module.RULES` (a sequence of `(rule_id, plugin_fn)` tuples) and registers each via `register_field_rule` (line 217-235). **There is no process-global registry in compat.** D2's engine mirrors this exactly.
- **Compat rule-pack `RULES` convention** — verified at `src/protokit/schema/checker.py:218-220`. D2 uses the same attribute name (`RULES`) but its tuple entries are decorated functions (carrying `_lint_spec`) rather than `(rule_id, plugin_fn)` tuples.
- **D1 lint type system** — `src/protokit/schema/lint/model.py` (958 LOC). Locked types consumed without modification except for the additions in Unit 1.
- **D1 compile module** — `src/protokit/schema/compile.py` (454 LOC). `LintCompileDiagnostic`'s `category: DiagnosticCategory` Literal is the exact pattern Unit 1's `LintRuntimeWarning.category` mirrors. Both types use `Optional[str]` fields populated per-category.
- **`is_map_field` helper** — `src/protokit/_descriptors.py` (referenced by R21). Unit 4's canary reuses this helper to skip map-entry synthetic fields.
- **D1 multi-path test pattern** — `tests/schema/lint/test_compile_multi.py` uses `tmp_path` + inline proto strings. D2 reuses this pattern; Unit 5 adds a single `tests/schema/lint/fixtures/all_kinds.proto` checked-in fixture for the 8-per-ElementKind walk test.
- **Static-analysis ratchet** — `tests/test_static_analysis.py` with `_LINT_PATHS` and `_TYPE_CHECK_PATHS` dual lists; CI workflow `.github/workflows/ci.yml` mypy step mirrors `_TYPE_CHECK_PATHS`. **D1 already uses directory globs (`src/protokit/schema/lint`, `tests/schema/lint`)**, so D2's new files are auto-covered.

### Institutional Learnings

All five `docs/solutions/` entries from the D1 review pass apply directly:

- **`docs/solutions/best-practices/frozen-dataclass-mutable-fields-need-post-init-snapshot-2026-05-02.md`** — `LintRuntimeWarning` is `frozen=True`; if it ever carries a list/dict context field (currently it doesn't, all fields are str / Optional[str] / Literal), `__post_init__` must `object.__setattr__` to snapshot. `LintReport.runtime_warnings` field uses `tuple[LintRuntimeWarning, ...]` and is snapshotted in the existing `LintReport.__post_init__`. Bind union-typed locals before `isinstance()` checks for mypy-strict narrowing.
- **`docs/solutions/best-practices/pytest-static-analysis-gate-ratchet-2026-05-02.md`** — D1's `_LINT_PATHS` and `_TYPE_CHECK_PATHS` use directory globs. D2's new files inside `src/protokit/schema/lint/` and `tests/schema/lint/` are auto-covered with no ratchet edits required (Unit 6 verifies this).
- **`docs/solutions/test-failures/pytestmark-does-not-guard-module-top-imports-2026-05-02.md`** — `pytestmark = pytest.mark.skipif(...)` is evaluated AFTER module import. Test files that need protoxy at module top use `protoxy = pytest.importorskip("protoxy")` BEFORE any other protoxy import. D2's tests don't currently need module-top protoxy (descriptor pools come from `compile_protos_to_result`).
- **`docs/solutions/security-issues/formatter-systemexit-exit-code-bypass-2026-04-19.md`** — `except Exception` does NOT catch `SystemExit`. The learning's own scope is formatters; it explicitly called the rule-plugin disposition (let SystemExit propagate) "defensible" and did not extend the fix to rule callables. **Unit 3 still catches `SystemExit` at the rule-callable boundary** — but on D2-specific reasoning, not as an extension of this learning: `LintEngine.run` is a library call returning `LintReport`, and a rule calling `sys.exit(0)` would make the call never return with results (caller sees clean exit and concludes no findings exist). See Key Technical Decisions for the full standalone rationale and the trade-off (rule authors lose `sys.exit()` / `pytest.exit()`; the escape hatch for "abort the run" is to raise an Exception subclass outside the catch tuple).
- **`docs/solutions/logic-errors/matcher-backend-path-resolution-skew-silently-empties-output-2026-05-02.md`** — Generalized lesson applied: when `compile_result.root_files` is non-empty but `LintEngine.run` returns zero findings AND zero runtime warnings, the test must non-defensively prove the walk visited descriptors. **Unit 5's tests include explicit walk-trace assertions** (assert specific element-kind counts AND `findings + filtered_count >= expected_emit_count` to distinguish walk-skip from filter-everything failure modes).

### External References

None used — local patterns dense and recent (D1 just landed; compat's `SchemaChecker` is the established sibling). External research deliberately skipped per Phase 1.2.

## Key Technical Decisions

- **Per-instance registry only, no process-global.** Mirrors compat's `SchemaChecker` pattern at `schema/checker.py:136-143`. Each `LintEngine` instance owns `self._loaded_specs: dict[str, LintRuleSpec]` and `self._loaded_module_names: set[str]`. The `@lint_rule` decorator attaches `LintRuleSpec` to the decorated function via `fn._lint_spec` and returns `fn` unchanged. Rule pack modules expose `RULES: tuple[Callable, ...]` listing the decorated functions to export. **Why:** the brainstorm's sidecar global created an importlib-caching test-isolation problem, an `importlib.reload`-collision problem, an `fn.__module__`-key-mismatch problem in dynamic-module tests, and a mypy-strict typing problem for module-attribute introspection. All four dissolve when the registry is per-instance. The brainstorm's "matches compat" claim was incorrect; compat is per-instance only.
- **Rule pack `RULES` convention echoes compat exactly.** Rule pack modules expose `RULES: tuple[Callable, ...]` containing the decorated functions. `LintEngine.load_rule_pack(module)` walks the tuple, extracts `fn._lint_spec` from each, and registers per-instance. **Why:** compat already uses `RULES`; reusing the name minimizes plugin-author cognitive overhead across the two engines (compat's tuples are `(rule_id, plugin_fn)`; lint's are decorated functions, but the iteration site is identical).
- **`load_rule_pack(module: ModuleType)` matches compat exactly.** Caller imports first; engine reads `module.RULES`, extracts each fn's `_lint_spec`, validates cross-pack `rule_id` uniqueness, commits per-instance. **Why:** D7's `--lint-rule-pack` and `--compat-rule-pack` flags share one wiring; library users with already-imported modules don't pay a string round-trip.
- **Atomic `load_rule_pack` via stage-then-commit.** Engine builds a temporary mapping of `rule_id → LintRuleSpec` from the pack's `RULES`, validates against the engine's existing loaded-rule dict for cross-pack `DuplicateRuleError`, then either commits (extends the engine's dict + adds module name to `_loaded_module_names`) OR discards the staging dict and raises. **Why:** brainstorm R10 atomicity; Unit 3 success criterion test (c). Intra-pack duplicates (same `rule_id` declared twice in `module.RULES`) are also caught at staging time — staging dict construction with per-`rule_id` collision check.
- **`@lint_rule` rejects `async def` and async-generator callables at decoration time.** Decorator runs `inspect.iscoroutinefunction(fn)` AND `inspect.isasyncgenfunction(fn)` before constructing the spec; either match raises `TypeError` with a clear message. **Why:** brainstorm "Deferred to Planning" item resolved; surfaces silent-no-op bug at module import time, not at engine.run() time.
- **Catch SystemExit at rule-callable boundary.** Diverges from brainstorm R16's literal "BaseException propagates" wording. Catch tuple becomes `(SystemExit, ValueError, TypeError, KeyError, AttributeError, LookupError, LintRuleError)`. `KeyboardInterrupt` and `GeneratorExit` still propagate (they have no rule-bug-bypass meaning). `MemoryError` / `RecursionError` / `AssertionError` / `ImportError` propagate as the brainstorm intended. **Why (D2-specific rationale, NOT extension of formatter learning):** `LintEngine.run` is a library call that returns a `LintReport`. A rule calling `sys.exit(0)` makes the library call never return with results — the user's process exits with code 0, and the caller (D3 CLI in the future, library users today) sees "clean exit" and concludes no lint findings exist. This is the same shape of bypass the formatter learning solved at the CLI surface, but the argument here stands on its own: a library function should not silently terminate its caller's process. The formatter learning explicitly limited its fix to formatters and called the rule-plugin disposition "defensible"; this divergence is justified by D2's library-API context, not by an extension of that fix. **Trade-off acknowledged:** rule authors lose the ability to use `sys.exit()` (or `pytest.exit()`, which subclasses `SystemExit`) to abort the run. The escape hatch for "stop the run" is to raise an `Exception` subclass NOT in the catch tuple (e.g., `RuntimeError`), which propagates uncaught and tears down `engine.run`. Document the escape hatch in `LintRuleError`'s docstring.
- **Per-level `_sorted_by_full_name` helper.** Sort cost is `O(N log N)` per level, negligible at typical N. One helper used by all level-walks. Helper signature is `_sorted(items, key=lambda x: getattr(x, "full_name", x.name))` so files (which have `.name`) and descriptors (which have `.full_name`) sort consistently. For ambiguous cases (two files declaring the same `package empty;` so two top-level messages share `full_name="empty.Foo"`), tie-break by file `.name` to keep ordering deterministic across runs. **Why:** guarantees deterministic findings independent of protobuf C++ binding iteration; tests can assert exact orderings; future binding upgrade can't silently re-shuffle. Tie-break covers the ambiguous-package edge case adversarial review surfaced.
- **`LintRuntimeWarning` field-population per category, mypy-narrowing pattern documented.** `category="rule_exception"` populates `rule_id`, `message`, `exception_type`, `descriptor_path`. `category="unloaded_rule"` populates only `rule_id` + `message`; `exception_type` and `descriptor_path` are `None`. Documented in dataclass docstring + enforced by tests. mypy `--strict` will not narrow Optional fields by Literal discriminator; downstream consumers (D4 formatters) match `LintCompileDiagnostic`'s already-established read pattern: branch on `category`, then `assert w.descriptor_path is not None` (or `cast(...)`) inside the relevant branch. The plan documents this pattern in `LintRuntimeWarning`'s docstring so D4 plan/implementation has a clear reference. **Why:** consistent with D1's `LintCompileDiagnostic`, which has the exact same `Optional`-by-category shape (`command`, `exit_code`, `stderr`, `exception_type` are all `Optional[...]` in `compile.py`); not introducing a new pattern, just restating the existing one.
- **`LintReport` adds two defaulted fields, both at the end.** `runtime_warnings: tuple[LintRuntimeWarning, ...] = ()` and `filtered_count: int = 0`. Both defaulted-and-appended preserves any existing positional construction; verification sweep in Unit 1 confirms no existing site uses more than 4 positional args. **Why:** brainstorm R18 + Dependencies / Assumptions verification gate.
- **`LintProfile.from_pack` lives in `lint/model.py`, no deferred imports needed.** Method body walks `module.RULES` and reads `fn._lint_spec` directly — no global registry to break a circular. **Why:** simpler than the brainstorm's deferred-import pattern; no circular to break since the registry doesn't exist.
- **Cross-file boundary test pinned in Unit 5.** Multi-file fixture where root A imports vendored C, and assertion that no findings target C even when rules do `ctx.pool.FindFileByName("C.proto")` cross-file lookups. **Why:** brainstorm Success Criterion #1 ambiguity resolved; vendored-proto rebuild-CompileResult workflow (R6a) gets a positive-control test.
- **Walk-trace assertion in Unit 5 walk-coverage tests.** Each per-`ElementKind` synthetic test asserts (a) its element kind produced N findings matching the input element count AND (b) `len(findings) + filtered_count >= expected_emit_count` (distinguishes walk-skip from filter-everything failure modes). **Why:** institutional learning #5 applied; closes the silent-zero-output failure-mode the matcher-backend learning surfaced.

## Open Questions

### Resolved During Planning

- **Registry shape** — Resolved: per-instance only, mirrors compat. Drops the brainstorm's sidecar `_RULE_PACK_REGISTRY`. Brainstorm review-pass concerns about test isolation, importlib.reload, mypy-strict typing, and `fn.__module__` lookups all dissolve by construction.
- **SystemExit handling at rule boundary** — Resolved per D2-specific library-API rationale: catch explicitly. Diverges from brainstorm R16; rationale documented in Problem Frame and Key Technical Decisions. Trade-off (rule authors lose `sys.exit()`) documented; escape hatch (raise non-caught Exception subclass) documented in `LintRuleError` docstring.
- **Async rule rejection** — Resolved: `inspect.iscoroutinefunction(fn) or inspect.isasyncgenfunction(fn)` check in decorator; raises `TypeError` at decoration time. Brainstorm deferred-question resolved.
- **Test fixture layout** — Resolved: hybrid. Canary, registry, engine-walk, severity, idempotency tests use `tmp_path` + inline proto strings (matches D1 `test_compile_multi.py` pattern). Per-`ElementKind` walk-coverage test (Unit 5) uses one checked-in `tests/schema/lint/fixtures/all_kinds.proto` because authoring all 8 kinds inline becomes unreadable. Cross-file boundary test uses `tmp_path` with two inline strings (root + vendored).
- **AIP-122 regex spec citation** — Resolved: cite https://google.aip.dev/122 § "Field names" in the canary's docstring. Brainstorm deferred-question resolved.
- **Atomic `load_rule_pack` rollback semantics** — Resolved: stage-then-commit pattern (build staging dict; validate; commit-or-raise). Brainstorm R10 promoted from deferred.
- **Walk-order determinism for ambiguous package names** — Resolved: tie-break by file `.name` when `full_name` collides. Adversarial review concern resolved.
- **mypy-strict narrowing pattern for `LintRuntimeWarning` Optional fields** — Resolved: matches D1's `LintCompileDiagnostic` precedent (branch on `category`, then assert/cast inside the branch). No architectural change; documented in dataclass docstring.

### Deferred to Implementation

- **Final exact field names on `LintRuntimeWarning`** — `descriptor_path`, `exception_type`, `message`, `rule_id`, `category` are pinned. If implementation reveals a need for additional context (e.g., `traceback_summary` for rule-exception debugging), add as a deferred decision at first PR review.
- **Whether `engine.reset()` should also unload the canary's `_lint_spec` attributes** — `_lint_spec` lives on the function object, which is module-level and outlives `engine.reset()`. If reset is meant to "start completely over", that's still fine: the next `load_rule_pack(module)` re-reads `module.RULES` and re-registers from scratch. No cleanup of `_lint_spec` attributes is needed. Confirm during Unit 3 implementation that this is intuitive for test authors.
- **`@lint_rule` decoration-site enforcement** — Plan documents supported sites as module-level functions only; decorator does NOT actively reject methods, lambdas, partials, nested functions. If implementation reveals a common foot-gun, add a runtime check (e.g., `if fn.__qualname__ != fn.__name__: raise TypeError`).
- **`LintRuleError` semantic** — Documented as the explicit "rule-author wants fail-soft" signal. Concrete usage pattern (when to raise `LintRuleError` vs returning silently) clarifies during Unit 4 canary writing and the synthetic-rule-error tests in Unit 3/Unit 5.
- **Reload semantics for rule pack modules** — `importlib.reload(naming_pack)` produces a fresh module with fresh `_lint_spec` attributes on fresh fn objects. Subsequent `engine.load_rule_pack(naming_pack)` reads the fresh `RULES` and registers fresh specs. No special handling needed because there's no global registry to invalidate. Worth a single test in Unit 3 to lock the contract.
- **AST-based verification sweep for `LintReport(...)` positional construction** — Plan currently specifies `grep -rn "LintReport(" src/ tests/` which has false positives (docstrings) and false negatives (multi-line constructions, star-args). Implementation may upgrade to a small AST-walk Python script if grep produces noise.
- **`compile_result.diagnostics` snapshot timing** — Plan reads `compile_result.diagnostics` at `LintReport` construction. If a rule mutates diagnostics mid-walk via `object.__setattr__` (CompileResult's frozenness not verified yet), observed diagnostics differ from those at `engine.run` entry. Snapshot at `run()` entry — copy `compile_result.diagnostics` into a local at the start of `run()` and use the local for the report. Trivial defensive change; lock during Unit 3 implementation.
- **`sorted(compile_result.root_files)` cross-platform stability** — Python's lex-codepoint sort over absolute paths varies between Linux (`/tmp/pytest-of-runner/...`) and macOS (`/var/folders/.../...`). Tests asserting exact ordering may pass on Linux CI cells and fail on macOS. Implementation should sort by basename (`os.path.basename(file_name)`) instead of full path to be cross-platform stable, OR ensure tests use only relative `.proto` names that sort consistently. Lock during Unit 3 implementation.
- **Performance budget** — `O(rules × elements)` per-context construction. Defer measurement to D5's perf smoke test (deferred there per D1's A5 disposition). If D5 finds the cost prohibitive, hoisting `_effective_severity` out of the per-element loop or building one context per element are mitigations.

## Output Structure

```
src/protokit/schema/lint/
├── __init__.py            # existing — stays a marker, no eager imports
├── decorator.py           # NEW: @lint_rule decorator (attaches _lint_spec to fn)
├── engine.py              # NEW: LintEngine class
├── model.py               # MODIFIED: + LintRuntimeWarning, LintRuleError,
│                          #            LintReport.runtime_warnings,
│                          #            LintReport.filtered_count,
│                          #            LintProfile.from_pack
└── rules/                 # NEW PACKAGE
    ├── __init__.py        # marker; no eager imports
    └── naming.py          # NEW: naming/snake-case-fields canary
                           #      with module-level RULES = (...)

tests/schema/lint/
├── __init__.py            # existing
├── fixtures/              # NEW directory
│   └── all_kinds.proto    # NEW: fixture with all 8 ElementKinds
├── test_canary_naming.py  # NEW: canary integration tests
├── test_compile_failure.py             # existing
├── test_compile_multi.py               # existing
├── test_compile_protoxy_fallback.py    # existing
├── test_decorator.py      # NEW: @lint_rule attachment + async rejection tests
├── test_engine.py         # NEW: walk + severity + failure containment + atomicity
├── test_model.py          # MODIFIED: + tests for new types/fields/from_pack
└── test_walk_coverage.py  # NEW: 8 synthetic per-ElementKind tests
                           #      + cross-file boundary
                           #      + filtered_count
                           #      + LintProfile.from_pack with canary
```

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

`LintEngine.run(compile_result, *, profile)` orchestrates this flow:

```
engine.run(compile_result, *, profile)
│
├── 1. Snapshot compile-stage diagnostics
│      compile_diagnostics = tuple(compile_result.diagnostics)
│
├── 2. Compute unloaded-rule diff
│      missing = profile.rule_ids - {rid for rid in self._loaded_specs}
│      runtime_warnings.extend(
│          LintRuntimeWarning(category="unloaded_rule", rule_id=rid, message=...)
│          for rid in missing
│      )
│
├── 3. Filter loaded specs by profile.rule_ids
│      active_specs = [spec for rid, spec in self._loaded_specs.items()
│                      if rid in profile.rule_ids]
│      group_by_kind = bucket(active_specs, key=lambda spec: spec.element)
│
├── 4. Walk root_files in sorted-by-basename order
│      # basename, not full path, for cross-platform test stability
│      for file in sorted(compile_result.root_files, key=os.path.basename):
│          fd = compile_result.pool.FindFileByName(file)
│          dispatch(fd, group_by_kind[FILE])
│          for service in _sorted_by_full_name(fd.services_by_name.values()):
│              dispatch(service, group_by_kind[SERVICE])
│              for method in _sorted_by_name(service.methods):
│                  dispatch(method, group_by_kind[METHOD])
│          for enum in _sorted_by_full_name(fd.enum_types_by_name.values()):
│              walk_enum(enum, group_by_kind)   # ENUM + ENUM_VALUE
│          for message in _sorted_by_full_name(fd.message_types_by_name.values()):
│              walk_message(message, group_by_kind)
│
├── 5. dispatch(element, specs) — per-rule loop
│      for spec in specs:
│          ctx = build_context(element, spec, profile, emit_fn=self._emit)
│          try:
│              spec.fn(ctx)
│          except (SystemExit, ValueError, TypeError, KeyError,
│                  AttributeError, LookupError, LintRuleError) as exc:
│              self._record_runtime_warning(spec.rule_id, exc, descriptor_path_for(element))
│
├── 6. self._emit(finding) callback
│      # finding.severity is already the effective severity — set inside
│      # _LintContextEmitMixin.emit() via the engine-injected
│      # _effective_severity closure (see model.py:643-646). The engine's
│      # callback only filters on profile.min_severity.
│      if rank(finding.severity) < rank(profile.min_severity):
│          self._filtered_count += 1
│          return
│      self._findings.append(finding)
│
└── 7. Return LintReport(
            findings=tuple(self._findings),
            diagnostics=compile_diagnostics,    # snapshot from step 1
            runtime_warnings=tuple(self._runtime_warnings),
            filtered_count=self._filtered_count,
            profiles_run=(profile.name,),
            rules_run=tuple(spec.rule_id for spec in active_specs),
        )
```

**Walk dispatch order (R5)** for nested elements within a message:

```
walk_message(message):
    dispatch(message, MESSAGE rules)
    for field in _sorted_by_name(message.fields):
        dispatch(field, FIELD rules)
    for oneof in _sorted_by_name(message.oneofs):
        dispatch(oneof, ONEOF rules)
    for nested_enum in _sorted_by_full_name(message.enum_types):
        walk_enum(nested_enum)        # ENUM + ENUM_VALUE
    for nested_message in _sorted_by_full_name(message.nested_types):
        walk_message(nested_message)  # depth-first recursion
```

**Decorator (R7, R8) — pure metadata, no global state:**

```
# in lint/decorator.py — directional sketch
def lint_rule(*, rule_id, severity, profiles, element, message_template, source_spec=""):
    def wrap(fn):
        if inspect.iscoroutinefunction(fn) or inspect.isasyncgenfunction(fn):
            raise TypeError(f"@lint_rule does not support async fns; got {fn!r}")
        # Construct via kwargs only — never positional. Decorator kwarg order
        # and LintRuleSpec field order differ; kwargs avoid positional drift.
        spec = LintRuleSpec(
            rule_id=rule_id, severity=severity, profiles=profiles,
            source_spec=source_spec, element=element,
            message_template=message_template, fn=fn,
        )
        fn._lint_spec = spec  # mypy: see comment in module about Protocol typing
        return fn
    return wrap
```

**Rule pack module shape (R8, R19):**

```
# in lint/rules/naming.py
from protokit.schema.lint.decorator import lint_rule
from protokit.schema.lint.model import ElementKind, LintSeverity

_FIELD_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")

@lint_rule(
    rule_id="naming/snake-case-fields",
    severity=LintSeverity.WARNING,
    profiles=("default",),
    element=ElementKind.FIELD,
    message_template="Field {name!r} is not snake_case (AIP-122)",
    source_spec="https://google.aip.dev/122",
)
def check_snake_case_fields(ctx):
    if is_map_field(ctx.field):
        return
    if not _FIELD_NAME_RE.match(ctx.field.name):
        ctx.emit(
            violation_kind="naming/snake-case-fields",
            params={"name": ctx.field.name},
        )

# Module-level RULES tuple — exact echo of compat's pattern
RULES = (check_snake_case_fields,)
```

**Engine load_rule_pack (R9, R10) — atomic stage-then-commit:**

```
# in lint/engine.py — directional sketch
def load_rule_pack(self, module):
    if module.__name__ in self._loaded_module_names:
        return  # idempotent

    rules = getattr(module, "RULES", None)
    if rules is None:
        raise AttributeError(f"rule pack {module.__name__!r} has no RULES attribute")

    # Stage: build a per-rule_id mapping from the pack's RULES, also detecting
    # intra-pack duplicates (same rule_id appearing twice in module.RULES).
    staging: dict[str, LintRuleSpec] = {}
    for fn in rules:
        spec = getattr(fn, "_lint_spec", None)
        if spec is None:
            raise TypeError(f"{fn!r} in {module.__name__}.RULES is not @lint_rule-decorated")
        if spec.rule_id in staging:
            raise DuplicateRuleError(spec.rule_id, staging[spec.rule_id].fn, fn)
        staging[spec.rule_id] = spec

    # Validate cross-pack: any rule_id already in self._loaded_specs?
    for rid, new_spec in staging.items():
        if rid in self._loaded_specs:
            raise DuplicateRuleError(rid, self._loaded_specs[rid].fn, new_spec.fn)

    # Commit: only after all validation passes.
    self._loaded_specs.update(staging)
    self._loaded_module_names.add(module.__name__)
```

**LintProfile.from_pack (R11a) — direct module.RULES walk:**

```
# in lint/model.py
@classmethod
def from_pack(cls, module: ModuleType, profile_name: str) -> LintProfile:
    matching = frozenset(
        fn._lint_spec.rule_id
        for fn in getattr(module, "RULES", ())
        if profile_name in fn._lint_spec.profiles
    )
    return cls(name=profile_name, rule_ids=matching)
```

## Implementation Units

- [ ] **Unit 1: Type-system additions to `lint/model.py`**

**Goal:** Land the new types (`LintRuntimeWarning`, `LintRuleError`), field additions (`runtime_warnings`, `filtered_count`), and `LintProfile.from_pack` classmethod.

**Requirements:** R17, R18, R11a; Dependencies / Assumptions verification gate

**Dependencies:** None (D1 foundation already landed)

**Files:**
- Modify: `src/protokit/schema/lint/model.py`
- Test: `tests/schema/lint/test_model.py` (modify; D1 already wrote the structural tests)

**Approach:**
- Add `LintRuntimeWarning` as a `@dataclass(frozen=True)` with fields: `category: Literal["rule_exception", "unloaded_rule"]`, `rule_id: str`, `message: str`, `exception_type: str | None = None`, `descriptor_path: str | None = None`. Document field-population rules per category in the dataclass docstring (including the format table mirroring `LintLocation.__str__` for `descriptor_path` when `category="rule_exception"`). Document the mypy-narrowing read pattern — branch on `category`, then `assert ... is not None` inside the branch — citing D1's `LintCompileDiagnostic` precedent.
- Add `LintRuleError(Exception)` — single class, no fields beyond `Exception`'s. Docstring explains it as the explicit "rule-author wants fail-soft" signal AND documents the escape hatch for "abort the run" (raise an Exception subclass NOT in the engine's catch tuple, e.g., `RuntimeError`).
- Append two fields to `LintReport`: `runtime_warnings: tuple[LintRuntimeWarning, ...] = ()` and `filtered_count: int = 0`. Extend `LintReport.__post_init__` to snapshot `runtime_warnings` to a `tuple` (mirrors existing `findings`/`diagnostics`/`profiles_run`/`rules_run` snapshots).
- Add `LintProfile.from_pack(module: ModuleType, profile_name: str) -> LintProfile` classmethod. Walks `getattr(module, "RULES", ())`, reads each fn's `_lint_spec`, filters by profile membership, returns `LintProfile(name=profile_name, rule_ids=frozenset(...))`. No deferred imports needed — the only dependency is the decorator's contract that `RULES` entries carry `_lint_spec`. mypy `--strict`: use `cast(LintRuleFn, fn)` or a Protocol class with `_lint_spec: LintRuleSpec` attribute.
- **Verification sweep before commit:** `grep -rn "LintReport(" src/ tests/` and confirm no existing site constructs `LintReport` with more than four positional args. If any found, convert to kwargs in the same commit. (Implementation may use a small AST-walk script if grep noise is excessive.)

**Patterns to follow:**
- `LintCompileDiagnostic` in `src/protokit/schema/compile.py` — exact same `category: Literal[...]` discriminator pattern + Optional fields + per-category field-population rules documented in docstring. Same mypy-narrowing read pattern.
- Existing `LintFinding`, `LintReport`, `LintProfile`, `LintRuleSpec` `__post_init__` snapshots in `lint/model.py`.
- `docs/solutions/best-practices/frozen-dataclass-mutable-fields-need-post-init-snapshot-2026-05-02.md`.

**Test scenarios:**
- Happy path: `LintRuntimeWarning(category="rule_exception", rule_id="x", message="m", exception_type="ValueError", descriptor_path="f.proto:Foo.bar")` constructs and is hashable / equality-comparable.
- Happy path: `LintRuntimeWarning(category="unloaded_rule", rule_id="missing", message="…")` constructs with `exception_type=None` and `descriptor_path=None`.
- Edge case: `LintReport(findings=(), diagnostics=(), profiles_run=(), rules_run=())` — existing four-arg positional construction still works.
- Edge case: `LintReport()` with all defaults yields `runtime_warnings=()` and `filtered_count=0`.
- Edge case: `LintReport.__post_init__` snapshots a list passed for `runtime_warnings` into a tuple; mutation of the input list does not affect the report.
- Happy path: `LintRuleError` constructs and is a subclass of `Exception` (not `BaseException`-but-not-`Exception`).
- Happy path: `LintProfile.from_pack` against a stub module with `RULES = (decorated_fn,)` returns a profile whose `rule_ids` matches the decorated fn's spec membership (single-rule, single-profile case). Test uses a synthetic decorated fn (constructed inline; no module-level state) to avoid coupling Unit 1's tests to Unit 4's canary.
- Edge case: `LintProfile.from_pack(module, "nonexistent_profile")` returns a profile with `rule_ids=frozenset()`.
- Edge case: `LintProfile.from_pack(module_without_RULES, "default")` returns a profile with `rule_ids=frozenset()` (the `getattr(..., (), )` default).

**Verification:**
- All `tests/schema/lint/test_model.py` tests pass under `pytest tests/schema/lint/test_model.py`.
- `mypy --strict src/protokit/schema/lint/model.py` clean.
- Verification sweep returns no positional-construction violations.

---

- [ ] **Unit 2: `@lint_rule` decorator**

**Goal:** Provide the decoration surface that rule packs use — a pure metadata-attach function with async rejection and async-generator rejection.

**Requirements:** R7, R8

**Dependencies:** Unit 1 (`LintRuntimeWarning`, `LintRuleError`, `LintRuleSpec` already in D1)

**Files:**
- Create: `src/protokit/schema/lint/decorator.py`
- Test: `tests/schema/lint/test_decorator.py` (new)

**Approach:**
- `@lint_rule(*, rule_id, severity, profiles, element, message_template, source_spec="")` is a decorator factory. The wrapped fn validates `inspect.iscoroutinefunction(fn) is False AND inspect.isasyncgenfunction(fn) is False` (else `TypeError` with a message naming the offending callable).
- Constructs `LintRuleSpec` via kwargs only.
- Attaches the spec to the function: `fn._lint_spec = spec` then returns `fn`.
- Document supported decoration sites in the decorator docstring: module-level functions only; methods, lambdas, and `functools.partial` wrappers are unsupported (foot-gun patterns surface during D6 if they appear).
- Document the contract that callers / engines / tooling rely on `fn._lint_spec` being readable on every fn in any rule pack's `RULES` tuple.
- mypy `--strict` typing: the attached attribute `_lint_spec` requires either a Protocol class declaration in `decorator.py` (or `model.py`) or `# type: ignore[attr-defined]` at the assignment site. Pick the Protocol option since it's the more durable surface.

**Patterns to follow:**
- `LintRuleSpec.__post_init__` dual-shape validation in `lint/model.py:540-572` — decorator just calls the constructor; no need to re-validate.
- compat's `register_field_rule` shape: a function that takes `(rule_id, plugin_fn)` — D2's decorator is the same idea, factored into a decorator that captures `rule_id` and other metadata at the decoration site.

**Test scenarios:**
- Happy path: a sync `def check(ctx): ...` decorated with `@lint_rule(...)` returns the same fn unchanged AND has `fn._lint_spec` set to a `LintRuleSpec` matching the decorator args.
- Happy path: decorating multiple sync fns with different `rule_id`s in the same module produces distinct `_lint_spec` attributes.
- Error path: decorating an `async def` callable raises `TypeError` immediately with a message that names the offending callable.
- Error path: decorating an `async def gen(): yield` async generator raises `TypeError` immediately.
- Error path: passing severity dict + message_template str (mismatched dual-shape) raises `TypeError` from `LintRuleSpec.__post_init__` (already locked in D1; verify decorator forwards correctly).
- Edge case: decorator-as-callable with no args raises a clear error (e.g., calling `@lint_rule` without parentheses).

**Verification:**
- All `tests/schema/lint/test_decorator.py` tests pass.
- `mypy --strict src/protokit/schema/lint/decorator.py` clean.
- Cold-import smoke: `python -c "import sys; import protokit.schema; assert 'protokit.schema.lint' not in sys.modules"` returns clean.

---

- [ ] **Unit 3: `LintEngine` implementation**

**Goal:** Land the engine that walks descriptors, dispatches rules, contains failures, resolves severity, and assembles `LintReport`.

**Requirements:** R1-R6, R9, R9a, R10, R11-R15, R16 (with SystemExit amendment); consumes R17/R18 types from Unit 1.

**Dependencies:** Unit 1, Unit 2

**Files:**
- Create: `src/protokit/schema/lint/engine.py`
- Test: `tests/schema/lint/test_engine.py` (new)

**Approach:**
- `LintEngine.__init__()` — initializes `self._loaded_specs: dict[str, LintRuleSpec] = {}` (keyed by `rule_id`) and `self._loaded_module_names: set[str] = set()`.
- `LintEngine.load_rule_pack(module: ModuleType)` — atomic stage-then-commit per the High-Level Technical Design. Reads `module.RULES`, extracts `_lint_spec` from each fn (raises `TypeError` if any entry isn't `@lint_rule`-decorated), detects intra-pack and cross-pack `rule_id` duplicates, commits or rolls back.
- `LintEngine.reset()` — clears `self._loaded_specs` and `self._loaded_module_names`. Returns the engine to its constructed state. Note: does NOT touch `_lint_spec` attributes on functions (those live on the function objects, are module-scoped, and survive engine reset by design).
- `LintEngine.run(compile_result, *, profile)` — orchestrates per the High-Level Technical Design.
- `_sorted_by_full_name(items)` helper — uses `key=lambda x: getattr(x, "full_name", x.name)` with tie-break by file `.name` for ambiguous-package cases.
- `_walk_message(msg, group_by_kind, accumulator)` — recursive helper; handles MESSAGE → FIELD → ONEOF → nested ENUM → nested MESSAGE.
- Rule-callable invocation wrapped in `try/except (SystemExit, ValueError, TypeError, KeyError, AttributeError, LookupError, LintRuleError)`. Other `Exception` subclasses propagate uncaught.
- Per-rule context construction: `_build_context(element, spec, profile, emit_fn)` returns the appropriate `*LintContext` dataclass with `_emit_fn`, `_rule_id`, `_effective_severity` injected. (Performance concern about per-rule construction at large N is deferred to D5's perf gate per Open Questions.)
- `_effective_severity_for(spec, profile)(violation_kind) -> LintSeverity`:
  1. base = `spec.severity_for(violation_kind)`
  2. if `spec.rule_id in profile.rule_severity_overrides`: base = `profile.rule_severity_overrides[spec.rule_id]`
  3. return base
- `_emit(finding)` callback — checks `rank(finding.severity) < rank(profile.min_severity)`; if filtered, increments `self._filtered_count`; else appends to `self._findings`.
- Unloaded-rule diff at start of `run()`: `missing = profile.rule_ids - {rid for rid in self._loaded_specs}`; one warning per missing.
- Snapshot `compile_result.diagnostics` into a local at `run()` entry; use the local in the final `LintReport` to defend against mid-walk mutation (Open Questions).
- Sort `compile_result.root_files` by `os.path.basename` for cross-platform test stability (Open Questions).
- Empty `compile_result.root_files` short-circuits past the walk but still computes the unloaded-rule diff (per R4 amendment).

**Patterns to follow:**
- `SchemaChecker` in `src/protokit/schema/checker.py:136-235` — overall instance shape (init, load_rule_pack reading `module.RULES`, run-equivalent `check()`).
- Existing `_LintContextEmitMixin` and 8 context dataclasses in `lint/model.py:601-919`.

**Test scenarios:**
- **load_rule_pack atomicity (R10):** Pre-load engine with pack A registering rule_ids `{a1, a2}`. Attempt to load pack B registering `{b1, a1}`. Assert (a) `DuplicateRuleError` raised; (b) `self._loaded_specs` keys still `{a1, a2}` only; (c) `self._loaded_module_names` contains only `A.__name__`; (d) re-running `engine.run()` produces findings only from A's rules.
- **load_rule_pack idempotency (R9a):** Load pack A twice; assert (a) no error; (b) `self._loaded_specs` has 2 entries (not 4); (c) `self._loaded_module_names` has 1 entry.
- **engine.reset() (R9a):** After loading two packs, `engine.reset()` empties both `_loaded_specs` and `_loaded_module_names`. A subsequent `engine.run()` produces an empty findings tuple. Re-loading the same pack after reset succeeds (idempotency reset).
- **load_rule_pack TypeError on undecorated fn:** Pack module exposes `RULES = (lambda ctx: None,)` with no `_lint_spec`. `load_rule_pack` raises `TypeError` with message naming the offending fn. Engine state unchanged.
- **load_rule_pack AttributeError on missing RULES:** Pack module has no `RULES` attribute. `load_rule_pack` raises `AttributeError` with a clear message. Engine state unchanged.
- **load_rule_pack intra-pack DuplicateRuleError:** Pack module exposes `RULES = (fn1, fn2)` where both fns have the same `_lint_spec.rule_id`. `load_rule_pack` raises `DuplicateRuleError` at staging time. Engine state unchanged.
- **importlib.reload contract:** Load pack A; mutate the pack's source (via test helper or fresh module); reload via `importlib.reload(pack_A)`; reset engine; reload pack into engine; assert the new specs are in effect. Locks the reload contract per Open Questions.
- **Walk order (R5, R6):** Fixture proto with three messages whose `full_name` is `Z`, `M`, `A`. Register a synthetic FIELD rule that emits one finding per field. Assert findings order in the tuple matches `A.<field>` < `M.<field>` < `Z.<field>` lexicographically. Verifies per-level full_name sort.
- **Walk-order tie-break:** Two-file fixture where both files declare `package empty;` with a top-level message `Foo` (so both have `full_name="empty.Foo"`). Register a synthetic MESSAGE rule. Assert the two findings appear in order of their parent file's basename (deterministic tie-break).
- **Walk only root_files (R4):** Multi-file fixture where root A imports vendored C. Registered FIELD rule emits one finding per field visited. Assert findings target only A's fields, never C's.
- **Empty root_files (R4 amendment):** `compile_result.root_files == ()`, profile names a loaded rule. Assert empty findings, empty runtime_warnings.
- **Empty root_files + unloaded rule (R4 + R13):** `compile_result.root_files == ()`, profile names an unloaded rule. Assert one `LintRuntimeWarning(category="unloaded_rule")`.
- **Unloaded-rule fire-frequency (R13):** Profile with two unloaded rule_ids and one loaded rule_id. Fixture with N descriptors. Assert exactly two unloaded-rule warnings (not 2*N), and the loaded rule's findings are present.
- **Severity override (R14):** Rule defaults to INFO; profile overrides it to ERROR. Fixture where rule fires once. Assert the emitted finding's severity is ERROR (not INFO).
- **Min-severity filter + filtered_count (R15):** Rule defaults to WARNING; profile sets `min_severity=ERROR`. Fixture where rule fires three times. Assert `findings == ()` and `filtered_count == 3`.
- **Rule-exception containment, narrow catch (R16):** Synthetic rule raises `ValueError`. Run returns; assert one `LintRuntimeWarning(category="rule_exception", exception_type="ValueError")`. Other rules' findings are still present.
- **Rule-exception containment, SystemExit (R16 amendment):** Synthetic rule calls `sys.exit(1)`. Use `subprocess.run` (or pytest's `pytest.raises(SystemExit)` discipline) to verify the test process does NOT exit — engine.run returns normally with one `LintRuntimeWarning(category="rule_exception", exception_type="SystemExit")`. Avoids the vacuous-pass failure mode where pytest itself catches SystemExit.
- **Rule-exception propagation, MemoryError:** Synthetic rule raises `MemoryError`. Run does NOT catch; the exception propagates out of `engine.run`. Verifies the catch tuple is narrow.
- **Rule-exception propagation, AssertionError:** Same as MemoryError — propagates uncaught.
- **Rule-exception propagation, GeneratorExit:** Synthetic rule raises `GeneratorExit`. Run does NOT catch; propagates uncaught (positive test confirming `BaseException`-but-not-`Exception` propagation per brainstorm intent).
- **CompileResult diagnostics passthrough (R3):** `compile_result.diagnostics = (LintCompileDiagnostic(level="info", ...),)`. After `engine.run`, `report.diagnostics` is the same tuple (verbatim, same order).
- **CompileResult diagnostics snapshot stability:** A rule that mutates `compile_result.diagnostics` mid-walk (via `object.__setattr__`) does NOT affect the resulting `report.diagnostics` (engine snapshots at run() entry).

**Verification:**
- All `tests/schema/lint/test_engine.py` tests pass.
- `mypy --strict src/protokit/schema/lint/engine.py` clean.
- Cold-import smoke step continues to pass.

---

- [ ] **Unit 4: Canary rule pack — `naming/snake-case-fields`**

**Goal:** Ship the inaugural built-in rule pack so the engine has realistic-input validation and D6 has a place to grow.

**Requirements:** R19, R20, R21, R22

**Dependencies:** Unit 1 (types), Unit 2 (decorator). Unit 3 not strictly required for the canary's own existence, but the canary's tests exercise the engine.

**Files:**
- Create: `src/protokit/schema/lint/rules/__init__.py` (marker; no eager imports)
- Create: `src/protokit/schema/lint/rules/naming.py`
- Test: `tests/schema/lint/test_canary_naming.py` (new)

**Approach:**
- `lint/rules/__init__.py` is a marker only. No eager imports of any submodule (preserves cold-import contract).
- `lint/rules/naming.py` imports `lint_rule` from `protokit.schema.lint.decorator` and decorates a single rule using `@lint_rule(rule_id="naming/snake-case-fields", severity=LintSeverity.WARNING, profiles=("default",), element=ElementKind.FIELD, message_template="Field {name!r} is not snake_case (AIP-122)", source_spec="https://google.aip.dev/122")`.
- Rule body:
  - Skip map-entry synthetic fields via `protokit._descriptors.is_map_field(ctx.field)` (per R21).
  - Match `FieldDescriptor.name` against `^[a-z][a-z0-9]*(_[a-z0-9]+)*$`. Compile the regex once at module scope.
  - On mismatch: `ctx.emit(violation_kind="naming/snake-case-fields", params={"name": ctx.field.name})`.
- Module exposes `RULES = (check_snake_case_fields,)` at module bottom (echoing compat's `module.RULES` convention).
- Module docstring cites AIP-122 § "Field names" with the URL.

**Patterns to follow:**
- `protokit._descriptors.is_map_field` — reuse exactly this helper, do NOT re-implement detection.
- compat's rule pack module shape with `RULES = (...)` at module scope.

**Test scenarios:**
- Happy path: fixture with fields `good_name`, `also_fine`, `field_2_name` (digit segment) — no findings.
- Error path: fixture with fields `BadCamelCase`, `with__double`, `trailing_`, `with-dash`, `UPPER` — four findings (assuming protobuf grammar rejects leading-underscore at parse time so that path is dead — verify and document during implementation).
- Edge case: fixture with a `map<string, string>` field; the synthetic `MapEntry.key` and `.value` fields are in the descriptor but the rule does NOT fire on them (verifies R21 skip).
- Integration: import the canary module, call `LintProfile.from_pack(naming_pack, "default")`, get a profile that includes `naming/snake-case-fields`. Run against a mixed-name fixture; produce findings only for the bad-name fields.
- Module-shape sanity: `naming.RULES` is a tuple; every entry has `_lint_spec`; the spec's `rule_id` matches `naming/snake-case-fields`.

**Verification:**
- All `tests/schema/lint/test_canary_naming.py` tests pass.
- `mypy --strict src/protokit/schema/lint/rules/naming.py` clean.
- Cold-import smoke step continues to pass (rules subpackage stays unloaded).

---

- [ ] **Unit 5: Per-`ElementKind` walk coverage + cross-file boundary + filtered_count + from_pack tests**

**Goal:** Validate the engine's walk paths against ALL eight `ElementKind` values, lock the cross-file boundary contract, and exercise integration scenarios that earlier unit-level tests can't reach.

**Requirements:** Success Criteria: per-`ElementKind` walk coverage; cross-file boundary; severity-override + filtered_count; `LintProfile.from_pack` derivation. Plus residual concerns: silent-zero-output guard.

**Dependencies:** Unit 1, Unit 2, Unit 3, Unit 4

**Files:**
- Create: `tests/schema/lint/fixtures/all_kinds.proto` — fixture proto containing at least one of each: file (file itself), service + 1 method, top-level enum + 2 enum_values (one being the required zero-valued UNSPECIFIED), top-level message with 2 fields + 1 oneof + 1 nested enum + 1 nested message
- Create: `tests/schema/lint/test_walk_coverage.py`

**Approach:**
- 8 synthetic always-fires rules registered via `@lint_rule` in a throwaway test module. The throwaway module is a `types.ModuleType('test_walk_coverage_pack')` with `__name__` set explicitly, the decorated functions def'd into its namespace, and `RULES = (...)` set on it. Engine reads `module.RULES` per the standard contract — no `sys.modules` injection needed because the engine doesn't look up `__module__` anywhere.
- Single test runs all 8 rules together against `all_kinds.proto`; asserts:
  - Each rule fired N times where N equals the number of that ElementKind in the fixture.
  - The findings tuple's order matches the documented sort order (file order; then per-level `full_name` sort within each file).
  - Total findings == sum of per-kind counts.
- Cross-file boundary test: two-file `tmp_path` fixture (`a.proto` imports `c.proto`); register the canary; assert findings target `a.proto` only, NOT `c.proto`, even though `ctx.pool.FindFileByName("c.proto")` succeeds inside a rule.
- Severity-override + filtered_count test (**integration-layer, real canary**): use the canary `naming/snake-case-fields` against an `all_kinds.proto` field with a bad name. Profile overrides the canary's severity to `LintSeverity.INFO` then sets `min_severity=WARNING`; assert `report.findings == ()` and `report.filtered_count == 1`. Then construct a second profile that overrides the canary to `ERROR`; assert one finding with `severity=ERROR`. Distinguishes from Unit 3's synthetic-rule test by exercising the real registered canary path; ensures override + filter behaviors hold for actual rule packs, not just engine-internal mocks.
- `LintProfile.from_pack` test: import `protokit.schema.lint.rules.naming` and call `LintProfile.from_pack(naming_pack, "default")`; assert `rule_ids == frozenset({"naming/snake-case-fields"})`.
- **Silent-zero-output guard:** in the per-kind walk-coverage test, after running the engine, assert (a) `len(report.findings) > 0`, (b) `len(report.findings) + report.filtered_count >= expected_emit_count` (distinguishes walk-skipped-elements from filtered-everything failure modes), AND (c) one specific element-kind's count by looking up its synthetic `descriptor_path` in the findings.

**Patterns to follow:**
- `tests/schema/lint/test_compile_multi.py` — `tmp_path` + inline proto string pattern for the cross-file test.
- compat's rule pack module shape (`RULES = (...)`) — synthetic test rules use the same convention even when the test module is constructed inline.

**Test scenarios:**
- Per-`ElementKind` walk coverage: 8 always-fires rules registered, fixture proto contains 1+ of each kind. Assertions per Approach.
- Cross-file boundary: root A imports vendored C. Canary registered. Assert no findings target C even when rules call `ctx.pool.FindFileByName("c.proto")`.
- filtered_count integration: canary forced to INFO via profile override, `min_severity=WARNING`, fires N times on bad-name fields. Assert `findings == ()` and `filtered_count == N`.
- Severity override visible in findings: canary forced to ERROR via profile override; bad-name fields produce findings with severity=ERROR (not the canary's default WARNING).
- `LintProfile.from_pack` derivation: returns the expected `rule_ids` for the canary pack.
- Silent-zero-output guard: assert `len(findings) + filtered_count >= expected_emit_count` AND specific kind counts match expectation. Fails clearly if a walk path silently skips OR if filtering accidentally drops everything.

**Verification:**
- All `tests/schema/lint/test_walk_coverage.py` tests pass.
- The fixture proto compiles successfully via both `has_protoxy=true` and `has_protoxy=false` matrix cells (needs `apt-get install -y protobuf-compiler` already in CI).
- `mypy --strict tests/schema/lint/test_walk_coverage.py` clean.

---

- [ ] **Unit 6: Final ratchet + cold-import smoke verification**

**Goal:** Confirm D1's existing static-analysis ratchet (which uses directory globs `src/protokit/schema/lint` + `tests/schema/lint`) automatically covers all D2 additions, and the cold-import smoke step still holds. Catch any drift before merge.

**Requirements:** R23, R24; institutional learning #2 (`pytest-static-analysis-gate-ratchet`)

**Dependencies:** Units 1-5

**Files:**
- Read-only: `tests/test_static_analysis.py` (verify no path additions needed)
- Read-only: `.github/workflows/ci.yml` (verify mypy step still covers new files via directory glob)
- Possibly modify: `tests/test_static_analysis.py` and `.github/workflows/ci.yml` ONLY if a new file lands outside `src/protokit/schema/lint/` or `tests/schema/lint/` — none are expected per Output Structure.

**Approach:**
- D1's `_LINT_PATHS` already contains `"src/protokit/schema/lint"` and `"tests/schema/lint"`; `_TYPE_CHECK_PATHS` already contains `"src/protokit/schema/lint"`; CI mypy step already passes `src/protokit/schema/lint/`. Both ruff and mypy treat directory args as recursive, so D2's new files (`decorator.py`, `engine.py`, `rules/__init__.py`, `rules/naming.py`, the new test files) are auto-covered with zero ratchet edits required.
- The only files needing list additions would be ones landing OUTSIDE these directories — verify none of D2's units do that.
- Run `pytest tests/test_static_analysis.py` locally and confirm it still passes against the directory globs after Units 1-5 land.
- Confirm cold-import smoke step (`python -c "import sys; import protokit.schema; assert 'protokit.schema.lint' not in sys.modules and 'protokit.schema.compile' not in sys.modules"`) returns clean.

**Patterns to follow:**
- `docs/solutions/best-practices/pytest-static-analysis-gate-ratchet-2026-05-02.md` — directory-glob pattern is the established approach.

**Test scenarios:**
- Test expectation: none — verification pass only; coverage already in place via D1's directory entries.

**Verification:**
- `pytest tests/test_static_analysis.py` passes (directory globs auto-cover the new files).
- Locally: `python -m mypy --strict src/protokit/schema/lint` returns clean (covers all new sources via the recursive directory arg).
- CI matrix all 4 cells green.
- Cold-import smoke step: `python -c "import sys; import protokit.schema; assert 'protokit.schema.lint' not in sys.modules and 'protokit.schema.compile' not in sys.modules, sys.modules.keys()"` returns clean.

## System-Wide Impact

- **Interaction graph:** D2's new surface is `LintEngine.run` (called by D3's CLI, D7's plugin path, library users). The engine touches `compile_result.pool` and `compile_result.root_files` only — never mutates them. Rule callables receive `*LintContext` instances and call `ctx.emit(...)`, which routes through `_emit_fn` to the engine's per-instance accumulator.
- **Error propagation:** Three error categories. (1) **Compile-stage** — passes through via snapshot of `compile_result.diagnostics → LintReport.diagnostics`. (2) **Engine-stage rule failures** — caught by the narrow tuple, recorded as `LintRuntimeWarning(category="rule_exception")`. SystemExit specifically caught (per D2-specific library-API rationale). (3) **Engine-stage configuration mistakes** — `DuplicateRuleError` from `load_rule_pack` propagates uncaught (caller's job to handle); unloaded-rule warnings recorded as `LintRuntimeWarning(category="unloaded_rule")`.
- **State lifecycle:** Engine instance state (`_loaded_specs`, `_loaded_module_names`, `_findings`, `_runtime_warnings`, `_filtered_count`) is per-instance; the latter four reset at every `run()` entry. `engine.reset()` clears the former two. **No process-global state.** `_lint_spec` attributes live on function objects and survive `engine.reset()` by design — the next `load_rule_pack(module)` re-reads `module.RULES` and re-registers from scratch.
- **API surface parity:** `LintEngine.load_rule_pack(module: ModuleType)` matches `SchemaChecker.load_rule_pack(module: ModuleType)` exactly (`schema/checker.py:217`). Rule pack modules expose `RULES` in both engines (compat's are `(rule_id, plugin_fn)` tuples; lint's are `@lint_rule`-decorated functions). D7's `--lint-rule-pack` and `--compat-rule-pack` flags will share identical wiring.
- **Integration coverage:** Unit 5 covers what unit-level tests can't — cross-file boundary, full per-`ElementKind` walk, severity-override-flowing-to-findings, filtered_count tracking, `from_pack` derivation.
- **Unchanged invariants:**
  - `protokit compat` CLI behavior — exit codes, stderr ladders, formatter pipeline — unchanged. D2 doesn't touch `protokit/schema/cli.py`.
  - D1's locked types (`LintFinding`, `LintProfile`, `LintRuleSpec`, `_LintContextEmitMixin`, the 8 context dataclasses, `LintSeverity`, `ElementKind`, `EmitFn`, `DuplicateRuleError`) remain as-is. `LintReport` and `LintProfile` get additive changes only.
  - Cold-import contract: `import protokit.schema` still does not pull in `protokit.schema.lint` or `protokit.schema.compile`.
  - 4-job CI matrix shape (`python: ["3.10", "3.12"] × has_protoxy: [true, false]`) unchanged. Static-analysis gate is unchanged (D1's directory globs cover D2's new files automatically).
  - `protokit.message` differ subsystem and `protokit.schema.checker` compat checker are not touched.

## Risks & Dependencies

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `LintReport` positional-construction breaks at unknown call site | Low | High (D1 tests fail) | Verification sweep in Unit 1 (`grep -rn "LintReport(" src/ tests/`); convert to kwargs in same commit if any > 4-arg site found |
| SystemExit from rule callable bypasses containment | Medium | High (CI false-pass) | Unit 3 explicit catch + Unit 3 test scenario using subprocess to verify the test process does NOT exit; Key Technical Decisions documents the divergence from R16 with D2-specific rationale |
| Walk order drift between protobuf C++ binding versions | Low | Medium (test fragility) | Unit 3 sorts at every level by `full_name` with file-`.name` tie-break; not dependent on binding iteration order |
| Cold-import contract regresses via accidental eager import | Low | High (compat startup time + D1 contract break) | Lint package's `__init__.py` stays a marker; rules subpackage's `__init__.py` stays a marker; Unit 6 verifies; CI smoke step continues to assert |
| AIP-122 regex semantics drift (false positives or negatives) | Low | Low (canary findings noisy) | Unit 4 test fixtures cover documented edge cases; AIP-122 spec URL cited in canary docstring; future user reports become the regression source |
| `LintProfile.from_pack` over-permissive on undecorated `RULES` entries | Low | Low (silent zero rule_ids) | `from_pack` reads `fn._lint_spec` via attribute access; if missing, AttributeError surfaces. Unit 1 tests an undecorated entry case (raise vs silently skip — pin during implementation) |
| `inspect.iscoroutinefunction` false-negative on `functools.wraps`-wrapped callables | Low | Low (silently no-op rule) | Decorator docstring limits supported sites to module-level functions; methods/lambdas/partials/wraps documented as unsupported. Plus `inspect.isasyncgenfunction` adds defense-in-depth |
| Rule pack `RULES` tuple drift (author forgets to add a new rule to `RULES` after decorating it) | Medium | Low (rule silently absent) | Unit 4's "module-shape sanity" test asserts the canary's `RULES` matches its `@lint_rule`-decorated functions. D6 will add similar pack-shape tests for additional rules |
| Cross-platform `sorted(root_files)` instability | Low | Medium (tests fail on different OSs) | Sort by `os.path.basename` instead of full path; resolved during Unit 3 implementation per Open Questions |

## Documentation / Operational Notes

- **No CHANGELOG entry yet** — D2 is library-internal. CHANGELOG entry lands when the first user-visible delivery (D3 CLI) ships.
- **No README update yet** — same reason.
- **Update `MEMORY.md` project_state** after merge: add D2 to the "protokit-lint" section with the shipped surface enumerated, and note the registry-shape revision (compat-mirror, no global) as a key architectural decision.
- **Cold-import smoke step** (in CI) continues unchanged. No rollout / migration / monitoring concerns — D2 is internal scaffolding.

## Sources & References

- **Origin document:** [`docs/brainstorms/2026-05-02-protokit-lint-delivery-2-engine-requirements.md`](../brainstorms/2026-05-02-protokit-lint-delivery-2-engine-requirements.md)
- **D1 foundation requirements:** `docs/brainstorms/2026-04-30-protokit-lint-delivery-1-foundation-requirements.md`
- **D1 implementation plan:** `docs/plans/2026-05-01-001-feat-protokit-lint-d1-foundation-plan.md`
- **D1 commits:** `0b82fc3` (P1/P2/P3 ce:review fixes), `e85faea` (pytest static-analysis gate), `31c0bb1` (4 docs/solutions learnings)
- **Compat sibling (verified per-instance pattern):** `src/protokit/schema/checker.py:136-143, 217-235`
- **Locked D1 types:** `src/protokit/schema/lint/model.py`
- **D1 compile module:** `src/protokit/schema/compile.py`
- **Map-entry helper:** `src/protokit/_descriptors.py::is_map_field`
- **Static-analysis ratchet:** `tests/test_static_analysis.py`, `.github/workflows/ci.yml`
- **Institutional learnings (all directly applicable):**
  - `docs/solutions/best-practices/frozen-dataclass-mutable-fields-need-post-init-snapshot-2026-05-02.md`
  - `docs/solutions/best-practices/pytest-static-analysis-gate-ratchet-2026-05-02.md`
  - `docs/solutions/test-failures/pytestmark-does-not-guard-module-top-imports-2026-05-02.md`
  - `docs/solutions/security-issues/formatter-systemexit-exit-code-bypass-2026-04-19.md` *(informs but does not extend; see Key Technical Decisions for D2-specific R16 amendment rationale)*
  - `docs/solutions/logic-errors/matcher-backend-path-resolution-skew-silently-empties-output-2026-05-02.md`
- **AIP-122 (canary spec source):** https://google.aip.dev/122
- **Protobuf descriptor pool analogy** — protobuf's `descriptor_pool.Default()` global + `descriptor_pool.DescriptorPool()` local pattern was raised as a precedent during planning. D2 matches the per-instance half of that pattern (compat does the same); a global default registry is a deliberate non-goal for D2 and an additive D6/D7 option if real demand surfaces.
