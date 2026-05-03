---
date: 2026-05-02
topic: protokit-lint-delivery-2-engine
---

# protokit-lint Delivery 2 — Engine + Canary Rule

Created: 2026-05-02
Source roadmap: `TODOS.md` lines 86-99 ("D2 — Engine implementation").
Foundation landed: D1 commits `0b82fc3`, `e85faea`, `31c0bb1` (2026-05-02).
Sequence: depends on D1; precedes D3 (`protokit lint` CLI), D4 (`_builtin_lint` formatters), D5 (pyproject config), D6 (rule packs), D7 (plugin API).

## Problem Frame

D1 shipped the locked type system, helper refactor, and CI matrix
for protokit-lint, but produced **no lint output** — every context's
`_emit_fn` is declared and never invoked end-to-end. Five downstream
deliveries (CLI, formatters, config, rule packs, plugin API) cannot
land until the engine that walks descriptors, dispatches rules, and
populates `LintReport` exists. D2 closes the `_emit_fn` loop.

D2 also resolves a coherence gap: D1 anticipated rules but did not
decide what happens when a rule callable raises an exception or how
the engine selects rules under an active profile. Leaving those
unresolved would force ad-hoc decisions in D3+ tests against an
under-specified contract.

A canary rule (`naming/snake-case-fields`) ships in D2 to validate
the engine end-to-end against realistic descriptor input rather than
synthetic test rules only.

**Slicing rationale.** D2 deliberately slices vertically thin: the
engine ships without CLI (D3), formatters (D4), pyproject config
(D5), additional rules (D6), or third-party plugin API (D7).
End-user-visible lint output therefore does not ship until D3+D4
land. Competing tools (buf lint, api-linter, protolint) ship a
working CLI + rule set in a single release; protokit-lint instead
optimizes for review surface, rollback safety, and parallel work
across the six-delivery roadmap. The cost is a 3-delivery delay
before any external user can run a single lint check; the benefit
is that each delivery is reviewable in isolation against a locked
contract from the previous one. This trade-off should be revisited
explicitly after D3+D4 merge — at that point we'll know whether
the staged approach actually paid off in review quality, or whether
fusing future deliveries (e.g., D5+D6) makes more sense given the
contract footprint already proven.

## Requirements

**Engine surface**

- R1. New module `src/protokit/schema/lint/engine.py` exporting
  `LintEngine` (instance, not module-level functions). Mirrors the
  `SchemaChecker`-instance shape used by `protokit.schema.checker`.
- R2. `LintEngine.run(compile_result: CompileResult, *, profile:
  LintProfile) -> LintReport` is the single entry point for D2. The
  engine consumes only `CompileResult`; no overload that accepts a
  raw `DescriptorPool` or path list ships in D2 (deferred until a
  library user explicitly asks).
- R3. The engine is stateful only in the sense that it owns its
  loaded-rule registry. Each `run()` call is independent — no
  cross-run caching, no shared state mutated by a run. The engine
  copies `compile_result.diagnostics` verbatim into
  `LintReport.diagnostics` (same tuple, same order); it does not
  halt the walk when diagnostics are present. Callers wanting
  halt-on-compile-error semantics inspect
  `compile_result.diagnostics` before invoking `engine.run`. (This
  preserves the `LintReport.diagnostics` semantic locked in D1:
  compile-stage diagnostics only.)

**Walk semantics**

- R4. The engine visits **only** the files named in
  `compile_result.root_files`. Imported types reachable through
  `compile_result.pool` are visible to rules via `ctx.pool` for
  cross-file lookups but are never themselves linted. (Empty
  `root_files` produces an empty report with no findings and no
  rule-execution runtime warnings. R13's unloaded-rule warnings
  still apply if the active profile names `rule_id`s that haven't
  been loaded. Compile diagnostics pass through unchanged.)
- R5. Within each root file, the engine dispatches rules in this
  order: FILE → SERVICE (and per-service METHOD) → ENUM (and per-enum
  ENUM_VALUE) → MESSAGE (and per-message FIELD, ONEOF, nested ENUM,
  nested MESSAGE depth-first). Nested enums and messages reuse the
  same per-element dispatch as their top-level counterparts.
- R6. **At every walk level, descriptors are sorted lexicographically
  by `full_name`** (or `.name` for elements without `full_name`,
  e.g., the file itself). Sorting at each level guarantees
  deterministic `LintReport.findings` order independent of protobuf
  C++ binding iteration order — so a future binding upgrade cannot
  silently re-shuffle findings, and tests can assert exact orderings.
  `LintReport.findings` therefore preserves: (1) sorted file order
  from `root_files`, (2) sorted descriptor walk order at each level,
  (3) rule registration order within each element kind. Per-level
  sort cost is negligible (≤ N log N over typically tens of
  descriptors).
- R6a. A user who wants to lint a file currently treated as an
  import (e.g., a vendored `third_party/foo.proto`) rebuilds
  `CompileResult` with that file passed as a root to
  `compile_protos_to_result(paths=(..., third_party_foo), ...)`.
  D2 does not add an `extra_root_files` engine arg; the existing
  `paths` parameter on `compile_protos_to_result` is the supported
  way to control the lint scope.

**Rule registration**

> **Revision note (2026-05-02, during `/ce:plan`):** R8/R9/R9a/R10/R11a
> below specify a sidecar `_RULE_PACK_REGISTRY` global keyed by
> `fn.__module__`. During planning, an audit of compat's actual
> pattern (`schema/checker.py:136-143, 217-235`) showed that compat
> uses a per-instance registry only — there is no process-global.
> The plan revises to match: `@lint_rule` attaches `LintRuleSpec` to
> the decorated fn as `fn._lint_spec`; rule pack modules expose
> `RULES: tuple[Callable, ...]` (echoing compat); engine reads
> per-instance only. This dissolves the test-isolation,
> `importlib.reload`, mypy-strict typing, and `fn.__module__` lookup
> concerns surfaced in document review. The original sidecar text
> is preserved below as design-history; the implementation contract
> is in `docs/plans/2026-05-02-001-feat-protokit-lint-d2-engine-plan.md`
> Key Technical Decisions.

- R7. `@lint_rule(*, rule_id, severity, profiles, element,
  message_template, source_spec="")` is the single decorator. The
  `element` kind is passed **explicitly** as a kwarg
  (`element=ElementKind.FIELD`). No first-param-annotation inference,
  no kind-specific sub-decorators (`@lint_rule.field`).
- R8. The decorator appends the resulting `LintRuleSpec` to a
  **sidecar registry** owned by the lint package — a typed module
  attribute `_RULE_PACK_REGISTRY: dict[str, list[LintRuleSpec]]`
  in a new `src/protokit/schema/lint/_registry.py` (loaded only
  when the user opts into lint), keyed by the decorated function's
  `__module__`. No `__lint_rules__` attributes on user modules; no
  module-attribute introspection; mypy-strict-clean by construction.
  Within a single pack module, the decorator raises
  `DuplicateRuleError` immediately if the same `rule_id` is
  registered twice (caught at module-import time, before any
  `load_rule_pack` call).
- R9. `LintEngine.load_rule_pack(module: ModuleType)` (matching
  compat's `SchemaChecker.load_rule_pack(module)` signature at
  `src/protokit/schema/checker.py:217`) reads `module.__name__`,
  looks up `_RULE_PACK_REGISTRY[module.__name__]`, and copies the
  entries into the engine's per-instance loaded-rule dict. Callers
  (CLI, D7 plugin path, library users) are responsible for
  `importlib.import_module(dotted_str)` before calling — the
  decorator side-effect happens during import, so the registry is
  populated by the time `load_rule_pack` runs.
- R9a. Multiple packs compose additively. `load_rule_pack` tracks
  loaded module names per engine instance; calling it twice with the
  same module short-circuits (idempotent). `LintEngine.reset()`
  clears the engine's loaded-rule dict and the loaded-module-names
  set, returning the engine to its constructed state — important
  for test isolation where the sidecar registry persists across
  tests but a test wants a fresh engine.
- R10. The engine raises `DuplicateRuleError` (locked in D1's
  `lint/model.py`) when **two distinct module names** register
  specs under the same `rule_id` across separate `load_rule_pack`
  calls. The error fires at `load_rule_pack` time, not at `run()`
  time. `load_rule_pack` is **atomic** — on `DuplicateRuleError`,
  no specs from the failing pack are loaded into the engine; the
  engine's loaded-rule dict and loaded-module-names set remain in
  their pre-call state. The caller can retry after fixing the
  conflict. (Intra-pack duplicates already fail at decoration time
  per R8.)

**Rule selection**

- R11. The engine runs **only** rules whose `rule_id` is present in
  `profile.rule_ids`. `profile.rule_ids` is authoritative.
  `LintRuleSpec.profiles` is metadata that rule pack authors use to
  declare default profile membership; the engine itself does not
  consult it during selection.
- R11a. D2 ships a `LintProfile.from_pack(module: ModuleType,
  profile_name: str) -> LintProfile` classmethod that reads
  `_RULE_PACK_REGISTRY[module.__name__]`, filters specs whose
  `profile_name in spec.profiles`, and returns
  `LintProfile(name=profile_name, rule_ids=frozenset({spec.rule_id
  for spec in matching}))`. Makes `spec.profiles` load-bearing
  again: rule pack authors annotate membership at the rule, callers
  derive a profile from the pack. D5's
  `[tool.protokit.lint] profile = "default"` resolves trivially via
  this classmethod. Falls back to an empty profile (zero
  `rule_ids`) when no rule in the pack declares the profile name —
  same explicit-empty-runs-zero-rules contract as R12.
- R12. Empty `profile.rule_ids` runs zero rules and produces an
  empty-`findings` report (no implicit "default" fallback).
- R13. A `rule_id` named in `profile.rule_ids` that has not been
  loaded into the engine is reported via `LintReport.runtime_warnings`
  as a `LintRuntimeWarning` with `category="unloaded_rule"` (per
  R17's discriminator). The walk continues; the missing rule
  contributes no findings. The unloaded-rule warning is computed
  **once before the walk begins** (set difference of
  `profile.rule_ids` against the engine's loaded `rule_id`s) and
  produces exactly one warning per missing `rule_id`, regardless of
  how many elements the walk visits. For an unloaded-rule warning,
  `exception_type`, `descriptor_path` are `None`; `message` carries
  a human-readable string like
  `"rule 'naming/snake-case-fields' is named in profile 'x' but not loaded into the engine"`.

**Severity resolution**

- R14. For each emitted finding, the engine constructs the
  `_effective_severity` callable injected into the lint context as:
  start with `LintRuleSpec.severity_for(violation_kind)` (locked
  D1 logic for single-vs-multi-kind), then apply
  `profile.rule_severity_overrides[rule_id]` if set (overrides every
  `violation_kind` of that rule under that profile), then drop the
  finding entirely if the resulting severity ranks below
  `profile.min_severity` (per `_SEVERITY_RANK` table in D1).
- R15. Min-severity filtering happens **at emit time**, not in a
  post-walk pass — a filtered-out finding never reaches
  `LintReport.findings`. The engine increments a counter for each
  filtered finding and surfaces the total as
  `LintReport.filtered_count: int = 0` (new field, defaulted, see
  R18a). D3+'s `--statistics` / `--max-warnings` flows can render
  the suppressed count without re-walking at a lower
  `min_severity`.

**Rule failure containment**

- R16. The engine wraps each rule callable invocation
  (`spec.fn(ctx)`) in a **narrow** `try/except` whose tuple is
  `(ValueError, TypeError, KeyError, AttributeError, LookupError,
  LintRuleError)` — covering the common rule-author bug shapes
  plus a new `LintRuleError` exception class (in `lint/model.py`)
  that rule authors raise to signal handled rule-level failures.
  `MemoryError`, `RecursionError`, `AssertionError`, `ImportError`,
  and any other `Exception` subclass NOT in the tuple propagate
  uncaught and tear down the walk — fail-loud semantics for truly
  broken state. `BaseException`-but-not-`Exception`
  (`KeyboardInterrupt`, `SystemExit`, `GeneratorExit`) also
  propagates per D1's A2-1 posture.
- R17. A caught exception produces a `LintRuntimeWarning` appended
  to `LintReport.runtime_warnings`. The type carries a discriminator
  field `category: Literal["rule_exception", "unloaded_rule"]`
  (mirrors `LintCompileDiagnostic`'s `category` Literal in
  `schema/compile.py`) plus the union of fields needed by either
  category. Field-population rules:

  | Field | `rule_exception` | `unloaded_rule` |
  |---|---|---|
  | `category` | `"rule_exception"` | `"unloaded_rule"` |
  | `rule_id` | populated | populated |
  | `message` | `str(exc)` | human-readable explanation |
  | `exception_type` | exception class name | `None` |
  | `descriptor_path` | stable string per below | `None` |

  For `category="rule_exception"`, `descriptor_path` mirrors D1's
  `LintLocation.__str__` shapes per `ElementKind`: FILE →
  `"file.proto"`; SERVICE → `"file.proto:full.Service"`; METHOD →
  `"file.proto:full.Service.method"`; ENUM →
  `"file.proto:full.Enum"`; ENUM_VALUE →
  `"file.proto:full.Enum.VALUE"`; MESSAGE →
  `"file.proto:full.Message"`; FIELD →
  `"file.proto:full.Message.field"`; ONEOF →
  `"file.proto:full.Message.oneof"`. The walk continues; subsequent
  rules and contexts are unaffected.
- R18. `LintReport` gains TWO new defaulted fields appended **after**
  the existing `rules_run` field, preserving positional construction
  for any D1 tests that pass the existing four args:
  `runtime_warnings: tuple[LintRuntimeWarning, ...] = ()` and
  `filtered_count: int = 0`. `LintRuntimeWarning` and `LintRuleError`
  are new frozen-dataclass / Exception types in `lint/model.py`.

**Canary rule**

- R19. D2 ships exactly one built-in rule: `naming/snake-case-fields`
  at `ElementKind.FIELD` and severity `LintSeverity.WARNING`,
  belonging to profile `"default"` (metadata only — see R11). The
  rule lives in a dedicated module (e.g.,
  `src/protokit/schema/lint/rules/naming.py`) so future built-in
  rules in D6 can grow alongside it under
  `src/protokit/schema/lint/rules/`.
- R20. The rule fires when a `FieldDescriptor.name` does not match
  `^[a-z][a-z0-9]*(_[a-z0-9]+)*$` — i.e., must start lowercase, no
  consecutive underscores, no leading or trailing underscore, no
  uppercase characters. (Maps verbatim to AIP-122 field naming.)
- R21. Fields whose containing message has
  `GetOptions().map_entry == True` are skipped — protobuf generates
  these synthetic entry messages from `map<K, V>` fields; their
  `key` and `value` fields are not user-authored. The detection
  reuses the existing helper at
  `src/protokit/_descriptors.py::is_map_field` (containing-type
  side, NOT field-name side — the entry-message name is derived
  from the parent field, e.g., `attributes` → `AttributesEntry`,
  not literally `MapEntry`).
- R22. The canary's existence is **not** opt-in via
  `LintEngine.load_rule_pack` from end-user code. D2 does not
  modify any eager-load hook to auto-load the canary; tests load it
  explicitly by importing the module first
  (`import protokit.schema.lint.rules.naming as naming_pack`) and
  passing it to `engine.load_rule_pack(naming_pack)` per R9's
  `ModuleType` signature. The auto-loading question (whether
  built-in rules eager-load on `protokit.schema.lint.engine` import)
  is deferred to D3 with the rest of the CLI wiring.

**Scope hygiene / cold-import contract**

- R23. D2 does **not** modify `src/protokit/schema/__init__.py`,
  `src/protokit/__init__.py`, or
  `src/protokit/formatters/__init__.py`. The cold-import contract
  validated by D1's CI smoke step (`import protokit.schema` must NOT
  pull in `protokit.schema.lint` or `protokit.schema.compile`)
  remains intact.
- R24. D2 does **not** add `tomli`, `proto-schema-parser`, or any
  other new runtime dependency. The engine works against descriptor
  pools only.

## Success Criteria

- **Canary cross-file boundary test.** A test that constructs a
  multi-file `CompileResult` where `root_files = (A, B)` and `A`
  imports vendored file `C` (which is in `pool` but not in
  `root_files`). Registers the canary via
  `engine.load_rule_pack(naming_pack)`, runs against
  `LintProfile(name="x", rule_ids=frozenset({"naming/snake-case-fields"}))`,
  and asserts (a) findings are produced for badly-named fields in
  `A` and `B`, (b) zero findings target `C`'s fields even though
  `C`'s types are reachable via `ctx.pool` from rules running on
  `A`/`B`. — passes.
- **Per-ElementKind walk coverage.** Eight trivial synthetic
  "always-fires" rules — one per `ElementKind` (FILE, SERVICE,
  METHOD, ENUM, ENUM_VALUE, MESSAGE, FIELD, ONEOF) — registered into
  the engine, run against a fixture proto containing at least one
  instance of each kind. Asserts: each kind produced exactly the
  expected number of findings matching the input element count, and
  the findings tuple matches the documented per-level full_name
  sort order (R6). — passes.
- **Rule-exception containment.** A test that registers a synthetic
  rule that raises `ValueError` (in the catch tuple per R16) and
  another that raises `MemoryError` (NOT in the catch tuple). Runs
  the engine on a fixture with multiple descriptors and asserts
  (a) the `ValueError` rule produces a `LintRuntimeWarning` with
  `category="rule_exception"`, `exception_type="ValueError"`, and
  a non-empty `descriptor_path`; (b) other rules' findings are
  still present; (c) the `MemoryError` rule, when re-run in
  isolation, propagates uncaught and aborts `engine.run()`. —
  passes.
- **Idempotency + DuplicateRuleError + reset.** Three tests:
  (a) loading the canary pack twice via two `load_rule_pack(naming_pack)`
  calls is idempotent (loaded-module-names set already contains
  `naming_pack.__name__` on the second call; engine's loaded-rule
  dict unchanged); (b) loading two packs registering the same
  `rule_id` raises `DuplicateRuleError` and the engine's loaded-rule
  dict + loaded-module-names set are in their pre-call state
  (atomic rollback); (c) `engine.reset()` after a successful load
  empties both, returning the engine to its constructed state. —
  all pass.
- **Unloaded-rule warning.** A test that constructs
  `LintProfile(name="x", rule_ids=frozenset({"missing/rule"}))`,
  runs against the canary-loaded engine, and asserts an empty
  `findings` tuple plus exactly one `LintRuntimeWarning` with
  `category="unloaded_rule"`, `rule_id="missing/rule"`,
  `exception_type=None`, `descriptor_path=None`. — passes.
- **Severity-override + filtered_count.** A test that registers a
  rule whose default severity is `INFO`, configures
  `LintProfile(min_severity=LintSeverity.WARNING)`, runs against a
  fixture where the rule fires N times. Asserts
  `LintReport.findings == ()` and `LintReport.filtered_count == N`.
  — passes.
- **`LintProfile.from_pack` derivation.** A test that calls
  `LintProfile.from_pack(naming_pack, profile_name="default")`
  against the canary pack and asserts the resulting profile's
  `rule_ids == frozenset({"naming/snake-case-fields"})`. — passes.
- The full CI matrix (`python: ["3.10", "3.12"] × has_protoxy:
  [true, false]`, 4 jobs) stays green. Cold-import smoke step
  continues to pass. `tests/test_static_analysis.py` (ruff + mypy
  ratchet from D1) passes with the new files added to the strict
  path-list.
- `protokit compat` exit codes and stderr ladders are unchanged.
  No user-visible behavior change for compat callers.

## Scope Boundaries

- **No CLI** — `protokit lint` ships in D3, not D2. The engine is
  exercised exclusively through library calls in tests.
- **No formatters** — `LintReport` rendering (human / json / junit /
  sarif) ships in D4. D2 tests inspect the report dataclass directly.
- **No pyproject config** — D5 reads `[tool.protokit.lint]`. D2 has
  no awareness of `pyproject.toml`.
- **No additional built-in rules** — only `naming/snake-case-fields`.
  D6 adds the rest of the rule pack (upper-camel-messages,
  zero-default-required, etc.).
- **No plugin API for third-party packs** — D7 ships the
  `--lint-rule-pack`-equivalent surface and its parity with compat's
  `--rule-pack`. D2's `load_rule_pack(dotted)` is internal-use-only;
  it is the same primitive D7 will expose, but D2 does not document
  it as public API.
- **No async support** — sync `run()` only. Async lint is in the
  separate "async plugin support" TODO and is not on the lint
  delivery roadmap.
- **No profile-name registry** — engine takes a `LintProfile`
  instance; name resolution is the caller's responsibility (D5+).
- **No auto-load of built-in rules at import time** — D3 decides
  whether `protokit.schema.lint.engine` eager-loads the built-in
  rule pack or whether the CLI loads it explicitly.

## Key Decisions

- **D2 + canary, not D2 alone, not D2-D4 fused.** Synthetic test
  rules alone leave the engine validated against mock input only;
  fusing D3+D4 with D2 inflates the PR and centralizes integration
  risk. The canary is the smallest realistic-input check that
  exercises the workhorse FIELD path. **Why:** preserves the
  six-delivery sequencing while still proving the engine wires
  end-to-end. **Acknowledged trade-off:** end-user-visible lint
  output doesn't ship until D3+D4 land. Competing tools (buf lint,
  api-linter, protolint) ship working CLI + rules in one release;
  protokit-lint optimizes for review surface and rollback safety
  over time-to-first-finding. Document re-evaluation point after
  D3+D4 merge.
- **Sidecar registry, not per-module attributes.**
  `_RULE_PACK_REGISTRY: dict[str, list[LintRuleSpec]]` in
  `protokit.schema.lint._registry`, keyed by decorated fn's
  `__module__`. Engine's per-instance loaded-rule dict is built up
  from this on `load_rule_pack(module: ModuleType)`; test isolation
  comes from `engine.reset()` rather than reload. **Why:** stamping
  attributes onto user modules creates importlib-caching test
  isolation problems, mypy-strict pain (`getattr(module, ...)`
  returns `Any`), and a footgun for package-level `__init__.py`
  loads. Owning the registry in the lint package eliminates all
  three. Naming convention question (`__lint_rules__` vs `RULES`)
  becomes irrelevant because users never see the storage.
- **`load_rule_pack(module: ModuleType)` matches compat's
  `SchemaChecker.load_rule_pack(module)` signature.** Caller (CLI,
  D7 plugin, library user) imports first. **Why:** D7's
  `--lint-rule-pack` and `--compat-rule-pack` flags become
  symmetrical with compat's existing `--rule-pack`; library users
  with already-imported modules don't pay a string round-trip; one
  load_rule_pack signature across protokit's two engines.
- **Narrow catch, not catch-all `Exception`.** Engine catches
  `(ValueError, TypeError, KeyError, AttributeError, LookupError,
  LintRuleError)` only; lets `MemoryError`, `RecursionError`,
  `AssertionError`, `ImportError` propagate uncaught. **Why:**
  `assert` statements in rule code remain useful for invariant
  checks; OOM and stack overflow shouldn't get swallowed into a
  warning that hides broken state; rule authors who want fail-soft
  semantics raise the documented `LintRuleError`.
- **Catch → record → continue with single `LintRuntimeWarning`
  type carrying a `category` discriminator.** One frozen dataclass
  for both rule-exception failures and unloaded-rule notices,
  matching `LintCompileDiagnostic`'s `category` Literal pattern in
  `schema/compile.py`. **Why:** parity with compat's failure model;
  one type for D4 formatters to render; structurally honest about
  the field-population differences (exception_type and
  descriptor_path are Optional, populated only for
  `category="rule_exception"`).
- **`LintProfile.rule_ids` authoritative for engine selection.**
  `LintRuleSpec.profiles` carries default profile membership
  metadata; `LintProfile.from_pack(module, profile_name)`
  classmethod (R11a) derives a profile from a pack. **Why:** keeps
  the engine boundary single-source-of-truth (engine reads only
  `profile.rule_ids`) while making `spec.profiles` load-bearing for
  pack-author ergonomics; D5's pyproject `profile = "default"`
  resolves trivially via `from_pack`.
- **Walk-level full_name sort for determinism.** Engine sorts
  descriptors lexicographically by `full_name` (or `.name` where
  `full_name` doesn't apply) at every walk level. **Why:**
  guarantees `LintReport.findings` order independent of protobuf
  C++ binding iteration semantics; tests can assert exact
  orderings; future binding upgrades cannot silently re-shuffle
  findings.
- **`filtered_count` on `LintReport`.** New `int = 0` field counts
  findings dropped at emit time by min_severity filtering. **Why:**
  industry-standard `--statistics` / `--max-warnings` flows in D3+
  need this; deferring forces re-walk at lower min_severity (2x
  cost).
- **Profile-name registry still deferred to D5.** Engine takes a
  `LintProfile` instance only; `LintProfile.from_pack(module, name)`
  is the D2-side derivation primitive. **Why:** YAGNI on the
  string-to-profile lookup table; D5 is the right place for
  pyproject-driven name resolution.
- **Walk only `root_files`, never imported files.** Standard
  practice for lint tools (ruff, eslint, golangci-lint). **Why:**
  linting imports would surface findings on
  `google/protobuf/timestamp.proto` and vendored deps, which is
  universally wrong-default. Vendored linting is supported by
  rebuilding `CompileResult` with the vendored path in
  `paths` (R6a).
- **Explicit `element=` kwarg on `@lint_rule`, not type-hint
  inference.** Robust under `from __future__ import annotations`
  (annotations are strings, would require eval), readable at the
  decorator call site, no introspection of `inspect.signature` at
  import time. **Why:** lower carrying cost; fewer subtle failures
  for plugin authors.

## Dependencies / Assumptions

- D1's locked `lint/model.py` types — `LintFinding`, `LintReport`,
  `LintProfile`, `LintRuleSpec`, `_LintContextEmitMixin`, the eight
  context dataclasses, `LintSeverity`, `ElementKind`, `EmitFn`,
  `DuplicateRuleError` — are consumed without breaking changes.
  Three additive type changes:
  1. `LintReport` gains two defaulted fields appended after
     `rules_run`: `runtime_warnings: tuple[LintRuntimeWarning, ...] = ()`
     and `filtered_count: int = 0`. Defaulted-and-appended preserves
     positional construction for any D1 tests that pass the existing
     four args.
  2. `LintProfile` gains a `from_pack(module: ModuleType,
     profile_name: str) -> LintProfile` classmethod (no fields
     change).
  3. `LintRuntimeWarning` (new frozen dataclass) and `LintRuleError`
     (new Exception subclass) are added to `lint/model.py`.
  4. **Verification gate:** before merging, run a sweep
     (`grep -rn "LintReport(" src/ tests/`) confirming no D1 site
     constructs `LintReport` with more than four positional args; if
     any exist, convert them to kwarg construction in the same PR
     so the additive change is safe.
- D1's `compile_protos_to_result()` and `CompileResult` (in
  `schema/compile.py`) are consumed without modification.
  `LintReport.diagnostics` continues to mean compile-stage
  diagnostics only; D2 routes rule-runtime issues through
  `runtime_warnings` (R17/R18) instead.
- The cold-import contract is preserved: nothing under
  `src/protokit/schema/lint/engine.py`,
  `src/protokit/schema/lint/_registry.py`,
  `src/protokit/schema/lint/rules/naming.py`, or
  `src/protokit/schema/lint/rules/__init__.py` is loaded by
  `import protokit.schema`. The CI smoke step from D1 covers this
  without modification. `lint/__init__.py` itself stays free of
  eager imports of any of the above (must remain a marker module
  only).
- `naming/snake-case-fields` does not require source-code-info or
  the `proto-schema-parser` dependency — it operates purely on
  `FieldDescriptor.name` from the descriptor pool.

## Verified Codebase Context

| Claim | Verified at | Notes |
|---|---|---|
| `LintReport` has 4 fields in D1 (`findings`, `diagnostics`, `profiles_run`, `rules_run`), all defaulted | `src/protokit/schema/lint/model.py:371-374` | D2 appends two defaulted fields after `rules_run`: `runtime_warnings = ()` and `filtered_count = 0` (6 fields total). All defaulted, so D1 tests that pass the existing four positional args remain valid. Verification sweep mandated in Dependencies / Assumptions. |
| Compat's existing rule-pack signature is `SchemaChecker.load_rule_pack(self, module: ModuleType)` | `src/protokit/schema/checker.py:217` | D2's `LintEngine.load_rule_pack(module: ModuleType)` mirrors this exactly so D7's `--lint-rule-pack` and `--compat-rule-pack` flags share the same shape. |
| Eight lint contexts each declare `_emit_fn`, `_rule_id`, `_effective_severity` as their LAST fields | `src/protokit/schema/lint/model.py:691-693, 718-720, 750-752, 781-783, 813-815, 844-846, 876-878, 909-911` | Engine must provide all three at context construction. |
| `LintRuleSpec.severity_for(violation_kind)` returns `LintSeverity` (single-kind) or looks up dict (multi-kind, raises `KeyError` on miss) | `src/protokit/schema/lint/model.py:574-598` | The `_effective_severity` callable in each context wraps this with profile-override logic. |
| `LintProfile.rule_severity_overrides: dict[str, LintSeverity]` (not per-`violation_kind`) | `src/protokit/schema/lint/model.py:415` | Override applies to all violation_kinds of a multi-kind rule (R14). |
| `_LintContextEmitMixin.emit(*, violation_kind, params=None)` requires `violation_kind` | `src/protokit/schema/lint/model.py:622-627` | Single-kind rules pass their `rule_id` (or any constant) as `violation_kind` per D1 docstring convention. |
| `DuplicateRuleError(rule_id, first_fn, second_fn)` already exists | `src/protokit/schema/lint/model.py:922-958` | Engine reuses; no new exception type for duplicates. |
| `compile_protos_to_result()` returns `CompileResult(pool, root_files, diagnostics)` with `root_files: tuple[str, ...]` preserving input order | D1 brainstorm § "Types/functions in `src/protokit/schema/compile.py`" | Engine iterates `compile_result.root_files`, never `pool.GetMessages()` or similar pool-wide enumeration. |
| Cold-import contract: `import protokit.schema` must NOT load `protokit.schema.lint` or `protokit.schema.compile` | D1 brainstorm § "Acceptance Criteria > CI workflow"; `tests/test_static_analysis.py` ratchet | D2's new `engine.py` and `rules/naming.py` must respect this. |
| 4-job CI matrix (`python × has_protoxy`) is in place | `.github/workflows/ci.yml` (per D1 brainstorm) | D2 tests run on every cell unchanged. Canary tests do not require `has_protoxy=true`. |
| `tests/test_static_analysis.py` is a path-list ratchet (ruff + mypy strict on listed paths) | D1 § "CI" / project_state.md | New D2 paths must be added to the strict path list. |
| `protokit compat` CLI behavior, exit codes, stderr ladders are bit-stable from D1 | D1 brainstorm § "Goal" | D2 does not touch `protokit/schema/cli.py`. |

## Outstanding Questions

### Resolve Before Planning

(none — all P0/P1 design decisions resolved in document-review pass)

### Deferred to Planning

- [Affects R8][Technical] Decorator implementation detail — does
  `@lint_rule` look up the importing module via `fn.__module__`
  (preferred, robust under decorators-of-decorators), or via
  `sys._getframe(1)` at decoration time? `fn.__module__` is the
  obvious pick. Planning should confirm there are no edge cases
  (functions defined inside `if TYPE_CHECKING` blocks; `__main__`
  REPL invocations; methods on classes; lambdas / `functools.partial`
  wrappers — supported decoration sites should be limited to
  module-level functions and explicitly documented).
- [Affects R19][Technical] Test fixture proto layout — D1's
  multi-path tests (`tests/schema/lint/test_compile_multi.py`) use
  `tmp_path` with inline proto strings rather than a checked-in
  fixtures subtree (no `tests/schema/lint/fixtures/` directory
  currently exists). Planning should decide whether canary tests
  follow the same `tmp_path`-with-inline-strings pattern or
  introduce the first checked-in `tests/schema/lint/fixtures/naming/`
  subtree with intentional snake-case violations.
- [Affects R20][Needs research] Cross-check the canary regex
  `^[a-z][a-z0-9]*(_[a-z0-9]+)*$` against AIP-122 spec text
  (https://google.aip.dev/122). The "verbatim AIP-122 mapping"
  claim should cite the relevant section and document any cases
  where the regex accepts what AIP rejects (or vice versa). Pin a
  test fixture covering each edge case (single-letter fields,
  digit-segments like `field_1`, leading underscore which protobuf
  grammar already rejects).
- [Affects R22][Needs research] Whether `protokit.schema.lint.engine`
  should eager-load the built-in rule pack at import time once D3
  ships. Out of scope for D2 itself but worth flagging so the D3
  brainstorm picks it up.
- [Affects R14][Technical] Multi-kind rule severity-override
  semantics — `LintProfile.rule_severity_overrides` keys by
  `rule_id`, not by `(rule_id, violation_kind)`. The override
  collapses all violation_kinds of a multi-kind rule to one
  severity. D2 ships single-kind canary so this isn't exercised;
  D6's first multi-kind rule must include a test that confirms the
  uniform-collapse behavior is what users expect (alternative: add
  per-kind override granularity later, with a migration story).
- [Affects R8][Technical] Async rule callable detection — should
  the engine reject `async def` rule fns at registration time
  (raise `TypeError`) or silently no-op? They run, return a
  never-awaited coroutine, and the rule contributes nothing.
  Planning should pick rejection-with-clear-error.
- [Affects R10][Technical] `engine.load_rule_pack` propagation of
  `ModuleNotFoundError` / `ImportError` — Engine doesn't internalize
  importlib (R9), so import errors arise at the caller. But if a
  module imports successfully and then a `LintRuleError` fires from
  inside the decorator's own `_RULE_PACK_REGISTRY` insertion path
  (e.g., D8's intra-pack DuplicateRuleError), the error surfaces
  during `import_module()` from the caller's perspective — D3's
  CLI must wrap this in clear error reporting.

## Next Steps

`-> /ce:plan` for structured implementation planning against this
requirements doc. The plan should produce:

1. File-level diff order. Suggested sequence:
   (a) `lint/model.py` additions — `LintRuntimeWarning` (with
   `category` discriminator), `LintRuleError`, `LintReport`'s two
   new defaulted fields, `LintProfile.from_pack` classmethod;
   (b) `lint/_registry.py` — sidecar `_RULE_PACK_REGISTRY` dict +
   `@lint_rule` decorator;
   (c) `lint/engine.py` — `LintEngine` with sorted walk, narrow
   catch, severity resolution, `reset()`, `load_rule_pack(module)`;
   (d) `lint/rules/__init__.py` + `lint/rules/naming.py` — canary
   pack;
   (e) test files in dependency order (model tests, registry tests,
   engine walk tests, canary integration tests).
2. Test ordering and shared fixture design — whether the canary
   tests follow D1's inline-`tmp_path` pattern from
   `test_compile_multi.py` or grow the first checked-in
   `tests/schema/lint/fixtures/` subtree. Eight per-ElementKind
   synthetic rules need a fixture proto containing all kinds.
3. Verification sweep step before merge: `grep -rn "LintReport(" src/ tests/`
   confirms no positional construction with >4 args (per Dependencies / Assumptions).
4. Concrete acceptance gates for the PR (every Success Criterion
   above passes; cold-import smoke step continues to pass; ruff +
   mypy ratchet covers all new paths including `_registry.py`,
   `engine.py`, `rules/__init__.py`, `rules/naming.py`).
