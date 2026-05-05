---
title: "feat: protokit-lint Delivery 3 — `protokit lint` CLI subcommand"
type: feat
status: active
date: 2026-05-04
origin: docs/brainstorms/2026-05-04-protokit-lint-delivery-3-cli-requirements.md
---

# feat: protokit-lint Delivery 3 — `protokit lint` CLI Subcommand

## Overview

D3 ships the first user-visible lint surface: `protokit lint` as a
top-level click subcommand on `protokit/cli.py`. The implementation
mirrors `protokit compat`'s structural template (positional inputs +
`--proto` source mode + `--profile` + `--rule-pack` + `--format` +
`--quiet` + 0/1/2 exit codes) while diverging deliberately on
several axes documented in the brainstorm's Sibling-Parity Audit.

The delivery comprises 5 implementation units totaling roughly:

1. Formatter substrate (`FormatterKind.LINT_REPORT`,
   `_builtin_lint.py` with the `human` formatter,
   `BUILTIN_PACKS` constant on `lint/rules/__init__.py` as KD-9's
   anchor).
2. CLI scaffold + input modes (descriptor-set + `--proto` source).
3. Rule loading + profile resolution (auto-load via
   `BUILTIN_PACKS`, `--rule-pack`, `--no-builtin-rules`,
   `--profile` resolution + composition + `--min-severity` numeric
   override).
4. CI gating + statistics + stable error-prefix codes
   (`--max-warnings`, `--statistics`, `--quiet`,
   `error_exit_with_code` helper, exit-code ladder).
5. D2 residual docstring fold-ins (AC-05/AC-06) + integration tests
   + CI cold-import gate extension.

**No machine output formats (`json`/`junit`/`sarif`) ship in D3** —
those land in D4 by extending the same `_builtin_lint.py` module
under the same `FormatterKind.LINT_REPORT` discriminator. D3 is
fully usable for binary CI gating via exit codes + `--quiet`; teams
needing SARIF/JUnit for code-scanning UIs wait for D4. KD-5 in the
origin document explicitly acknowledges this trade-off.

**Cold-import contract preserved**: `import protokit.schema` does
not transitively load `protokit.schema.lint` or
`protokit.formatters._builtin_lint`. The lint subcommand module
`src/protokit/schema/lint/cli.py` loads only via
`protokit.cli` (i.e., on every `protokit ...` CLI invocation) and
its top-level import of `_builtin_lint` triggers the formatter
registration as a side effect — preserved by NOT adding
`_builtin_lint` to `formatters/__init__.py`'s eager-load tuple.

## Identity & Positioning

protokit-lint is the linter for proto schemas where (a) compat
checks, lint, and the differ share descriptor-set ingestion +
formatter registry + cold-import discipline (i.e., one toolchain
that integrates lint findings, breaking-change reports, and
runtime diffs against the same artifact pipeline); and (b)
rule-pack composition is **explicit and auditable** rather than
inherited from an opaque bundled-default.

What protokit-lint is **not**: a competitor to buf-lint as a
general-purpose proto linter. We do not aim to ship the deepest
catalog of rules, the most pluggable ecosystem, or the broadest
language-server integration. The bet is *integration depth with
the protokit toolkit + CI auditability*, not breadth-of-rules.

This positioning anchors design tradeoffs: KD-9's conservative
auto-load policy (one pack today; D6+ packs default opt-in) is a
direct expression of "auditable composition" — users see what
runs and grant explicit permission for new rules. R8's
`DuplicateRuleError` (lint refuses silent shadowing where compat
allows it) is another expression of the same bet. R25's
unconditional stderr provenance line surfaces composition the
moment it occurs. Future scoping calls (D5/D6/D7) should be
weighed against this anchor: changes that increase auditability
or integration depth pull toward the bet; changes that compete
on rule breadth, ecosystem plugins, or "just-works" magic pull
away from it.

## Problem Frame

D2 (commits `26bd312`...`a0b7692` on 2026-05-03) shipped the
`LintEngine` walker, the `@lint_rule` decorator, the canary
rule pack `naming/snake-case-fields`, and `LintProfile.from_pack`
+ `compose`. Lint output is reachable today only via library
calls; there is no CLI surface for end users.

Three downstream deliveries (D5 pyproject config, D6 additional
rule packs, D7 plugin API parity) are all gated on D3 — they
either need to read CLI flags, fire from a CLI invocation, or
extend a CLI surface that does not yet exist. D3 closes the
dogfood gap and unblocks the rest of the protokit-lint roadmap.

The brainstorm (see origin: `docs/brainstorms/2026-05-04-protokit-lint-delivery-3-cli-requirements.md`)
resolved every product decision needed for planning: shape of the
subcommand, input modes, rule-loading semantics, profile
resolution, output formatting, CI gating mechanics, exit-code
ladder, stable error-prefix codes, and the D2 residuals folded
in / deferred. Two passes of `document-review` surfaced and
addressed coherence + feasibility issues including the
`LintRuntimeWarning.category` Literal-extension concern that drove
deferral of R12's `min_severity_relaxed` warning to D5 (where
its first real caller arrives with pyproject config).

## Requirements Trace

Requirement IDs match the origin document. Items marked **DEFERRED**
were considered for D3 but moved to a later delivery during
brainstorm refinement; they are listed here for traceability and
appear in Scope Boundaries as out-of-scope.

**Subcommand surface**
- R1. `protokit lint` click subcommand on top-level CLI group;
  single command, not a sub-group.
- R2. One-or-more positional path arguments + `--proto` flag;
  single input set (no old/new axis).
- R3. Cold-import contract preserved.

**Input modes**
- R4. Descriptor-set mode (default, multi-path) + `--proto` source
  mode (compiles via D1's `compile_protos_to_result`).
- R5. Git modes (`--since`, `--against-base`) **DEFERRED**.

**Rule loading**
- R6. Built-in rule packs auto-load on subcommand startup via
  `BUILTIN_PACKS` constant on `lint/rules/__init__.py`.
- R7. `--no-builtin-rules` boolean opt-out.
- R8. `--rule-pack MODULE` (repeatable, fully-qualified dotted
  module name) additive on top of built-ins.
- R9. Loud failure when zero rules load (exit 2,
  `error[lint-no-rules]:`).

**Profile resolution**
- R10. `--profile NAME` (default `"default"`); compose
  `LintProfile.from_pack` across all loaded packs.
- R11. Empty composed profile → exit 2 (`error[lint-unknown-profile]:`)
  with stderr listing each pack's declared profiles.
- R12. `--min-severity LEVEL` (info|warning|error) — pure numeric
  override in D3; the `LintRuntimeWarning(category="min_severity_relaxed")`
  emission is **DEFERRED to D5** (its first non-default caller
  arrives there).

**Output and formatting**
- R13. `--format NAME` (default `human`, envvar `PROTOKIT_FORMAT`);
  unsupported values → `KeyError` from registry → exit 2
  (`error[lint-format-unavailable]:`) with available-list message
  + cross-subcommand envvar note.
- R14. `FormatterKind.LINT_REPORT` enum value added.
- R15. `_builtin_lint.py` registers `human` via `_register_builtin`
  (idempotent + reserves the name); NOT in eager-load tuple.
- R16. `--statistics` footer (default ON in human format unless
  `--quiet`; per-severity counts + filtered + runtime warnings;
  empty rows suppressed).
- R17. `--ignore PATH` **DEFERRED to D5** (co-design with pyproject
  `exclude` globs; per-variant `LintLocation` match-target is a
  design question pyproject must resolve anyway).
- R18. `--quiet` boolean; mutex with non-`human` formats; wins
  unconditionally over `--statistics`.

**CI gating**
- R19. `--max-warnings N` cap on WARNING-severity findings;
  ERROR always exit 1; INFO never gates.
- R20. Exit codes: 0 clean / 1 findings exceed gate / 2 diagnostics.
- R20a. Stable stderr error-prefix codes via
  `error_exit_with_code(code, message)` helper. **D3 codes:**
  `lint-no-rules`, `lint-unknown-profile`,
  `lint-format-unavailable`, `lint-compile-failed`,
  `lint-formatter-exception`, `lint-bad-input`,
  `lint-pool-conflict`, `lint-rule-collision`,
  `lint-rule-pack-import` (last two added during planning — see
  Open Questions).

**D2 ce:review residuals folded in**
- R21. `LintRuntimeWarning.emit_count_before_exception` field
  **DEFERRED to D4** (formatter is the only consumer).
- R22. `ctx.pool` mutation contract docstring (AC-05).
- R23. `LintRuleError` catch-tuple docstring tightening (AC-06).

**New requirements added during brainstorm refinement**
- R24. `_load_descriptor_sets_to_result` helper with
  dedupe-before-Add ordering + cross-set symbol-collision
  handling.
- R25. Composition stderr provenance line (fires on every run, full
  module names, surfaces dual-loading).

## Scope Boundaries

- Git input modes (`--since`, `--against-base`) — future delivery.
- `json` / `junit` / `sarif` lint formatters — D4. D3 ships only
  `human`; the `_builtin_lint.py` module is the shared landing
  zone D4 extends.
- pyproject `[tool.protokit.lint]` config — D5.
- `--ignore PATH` suppression flag — D5 (R17 deferred).
- `LintRuntimeWarning.emit_count_before_exception` (REL-03,
  R21) — D4.
- `LintRuntimeWarning(category="min_severity_relaxed")` emission
  (R12 observability) — D5.
- `--disable-rule RULE_ID` / `--override-rule-pack` shadowing
  escape valves — future delivery.
- Additional built-in rule packs beyond `naming` — D6.
- Plugin API parity / `--lint-rule-pack` aliases — D7.
- Inline `protokit:ignore` source comments — Phase 3.
- Auto-fix via proto-schema-parser — Phase 3.
- Sub-grouping `protokit lint check`-style nesting (R1).
- "Old vs new" two-input lint mode (R2).
- `--type` / `--dedupe-by-type` (compat-only concepts).
- `--formatter-module` for user formatter packs — until D4
  establishes the lint-formatter API surface.
- `--max-findings-of SEVERITY=N` — until D6+ ships INFO-severity
  rules where the asymmetry matters.

## Context & Research

### Relevant Code and Patterns

- **CLI shape template**: `src/protokit/schema/cli.py:583-737`
  (`@main.command("check")`) — argument decorators, click options,
  PROTOKIT_FORMAT envvar pattern, `_LEVEL_CHOICES`-style use of
  `click.Choice`. Used as a structural template; D3 does NOT
  subclass or import from this module.
- **Top-level CLI group**: `src/protokit/cli.py:20-27` — adds the
  third subcommand `lint` adjacent to existing `diff` and `compat`.
  The `from protokit.schema.lint.cli import main as _lint_command`
  import is the load-bearing edge for R15's cold-import claim
  (registration happens at `protokit.cli` load time).
- **Formatter registry primitives**:
  `src/protokit/formatters/_registry.py` —
  - `FormatterKind` enum at line 21 (D3 adds `LINT_REPORT` per
    line 41-42 docstring noun-form convention)
  - `register_formatter` at line 128 (raises `FormatterError`)
  - `_register_builtin` at line 183 (idempotent, reserves name —
    THIS is the helper R15 uses)
  - `get_formatter` at line 203 (raises `KeyError` on miss —
    docstring at 213-218 explicitly says "callers should catch
    KeyError and translate to error_exit")
  - `list_formatters` at line 222
- **Eager-load tuple to PRESERVE (don't add `_builtin_lint`)**:
  `src/protokit/formatters/__init__.py:60-71`.
- **Compile entry point (D1)**:
  `src/protokit/schema/compile.py:compile_protos_to_result(paths,
  proto_paths) -> CompileResult` — reused for `--proto` mode.
- **Engine API (D2)**:
  `src/protokit/schema/lint/engine.py` —
  - `LintEngine.__init__` initializes per-instance registry
  - `LintEngine.load_rule_pack(module)` raises
    `DuplicateRuleError` on collision (idempotent for same
    `module.__name__`)
  - `LintEngine.run(compile_result, *, profile) -> LintReport`
- **Profile primitives (D2)**:
  `src/protokit/schema/lint/model.py:499-665` —
  - `LintProfile` dataclass (frozen)
  - `LintProfile.compose(*profiles)` short-circuits with single
    profile
  - `LintProfile.from_pack(module, profile_name)` walks `RULES`,
    yields `min_severity = WARNING` regardless of pack declaration
- **Severity types (D2)**:
  `src/protokit/schema/lint/model.py:75-115` —
  `LintSeverity{INFO,WARNING,ERROR}` and `_SEVERITY_RANK`.
- **Rule pack template**:
  `src/protokit/schema/lint/rules/naming.py` — `@lint_rule`
  decorated function + `RULES = (decorated_fn,)` module
  attribute. D3's `BUILTIN_PACKS = (naming,)` lives in
  `src/protokit/schema/lint/rules/__init__.py`.
- **`LintRuntimeWarning` (frozen Literal type)**:
  `src/protokit/schema/lint/model.py:421` —
  `category: Literal["rule_exception", "unloaded_rule"]`. D3
  preserves the two-value Literal (R12's `min_severity_relaxed`
  deferred to D5; R24's `duplicate_root_file` rerouted to
  CLI stderr).
- **Existing `error_exit` helper**:
  `src/protokit/_cli_utils.py:68` writes `Error: {message}` —
  used by compat. D3 introduces `error_exit_with_code` in
  `src/protokit/schema/lint/_cli_utils.py` for lint's stable
  prefix codes (the legacy helper stays untouched).
- **`run_formatter_safely` pattern**: `src/protokit/_cli_utils.py`
  — wraps formatter calls in try/except and routes to
  exit code 2 with the security-related `except SystemExit` fix
  documented in `docs/solutions/security-issues/formatter-systemexit-exit-code-bypass-2026-04-19.md`.
  D3 uses this same wrapper for the lint formatter call.
- **CI smoke pattern (D1)**: `tests/test_static_analysis.py`
  enforces a path-list ratchet for ruff + mypy. D1's `_LINT_PATHS`
  + `_TYPE_CHECK_PATHS` already use directory globs covering
  `src/protokit/schema/lint` and `tests/schema/lint`; D3's new
  files auto-cover.

### Institutional Learnings

- `docs/solutions/best-practices/audit-wire-format-before-claiming-sibling-parity-2026-05-03.md`
  — applied throughout the brainstorm's Sibling-Parity Audit. R8's
  `--rule-pack` wire-format divergence and the rule-shadow contract
  divergence are documented audit-table rows; the audit was used
  again during pass-2 review to catch the
  `LintRuntimeWarning.category` Literal-extension issue (R12, R24).
- `docs/solutions/security-issues/formatter-systemexit-exit-code-bypass-2026-04-19.md`
  — the formatter-side `except SystemExit` fix that
  `run_formatter_safely` already provides. R13 + Unit 4's
  `lint-formatter-exception` code path piggybacks on this
  existing safety net.
- `docs/solutions/best-practices/cold-import-quarantine-pattern-2026-05-02.md`
  (if exists per D1; otherwise the codex P0 finding
  LINT-DESIGN-COLD-IMPORT-FORMATTERS in D1's brainstorm) — the
  quarantine pattern that R15 preserves: `_builtin_lint` NOT in
  eager-load tuple; lint subcommand module imports it at module
  top, registration runs at `protokit.cli` load time.

### External References

None used. The brainstorm grounded all decisions in internal
codebase patterns and D2's locked engine surface; external research
(buf-lint / api-linter / protolint comparisons) informed the
*identity-bet* discussion but did not change implementation
mechanics.

## Key Technical Decisions

- **Use `_register_builtin`, not `register_formatter`, for the
  human lint formatter (R15)**. The internal helper at
  `_registry.py:183-200` is idempotent under module reload (test
  suites, `importlib.reload`, dev REPL) and reserves the `human`
  name in `_BUILTIN_NAMES` against future user-pack shadow
  attempts. The public `register_formatter` raises
  `FormatterError` on duplicate keys, which would break test
  parametrization that imports the lint CLI module across cases.
- **Auto-load via a `BUILTIN_PACKS` tuple constant on
  `rules/__init__.py`, NOT a hard-coded import in `lint/cli.py`
  (Q1 resolution + KD-9 anchor)**. Public, discoverable surface
  that users can introspect at runtime; docstring on the constant
  binds membership changes to a major-version event with CHANGELOG
  entry. Cold-import preserved because nothing outside the lint
  subpackage imports `protokit.schema.lint.rules`.
- **Profile composition uses `LintProfile.compose` with the
  single-pack short-circuit (R10)**. For the typical D3 case
  (`naming` only), `compose` returns the single `from_pack` result
  unchanged. R25's stderr provenance line fires on every run
  regardless of pack count to make the composition mechanism
  visible from day one.
- **`--min-severity` is a pure numeric override in D3 (R12)**. The
  `LintRuntimeWarning(category="min_severity_relaxed")` emission
  was drafted into D3 during brainstorm pass 1 but deferred to
  D5 in pass 2 to avoid extending D2's locked
  `LintRuntimeWarning.category` Literal type — the same constraint
  that drove R21's deferral (KD-8). Pyproject config in D5 is the
  first real caller that produces a non-default-floor profile, so
  the warning's value materializes there.
- **R24's duplicate-filename detection emits a CLI stderr line,
  NOT a `LintRuntimeWarning(category="duplicate_root_file")`**.
  Same Literal-preservation rationale as the R12 deferral. The
  audit-trail line fires before the lint walk begins; it is
  suppressible under `--quiet`.
- **`error_exit_with_code` helper lives in
  `src/protokit/schema/lint/_cli_utils.py`, NOT in
  `protokit._cli_utils.py` (R20a)**. Lint and compat helper
  surfaces stay decoupled. The legacy `error_exit` keeps its
  `Error: ` prefix; lint's exit-2 paths route through the new
  helper with `error[lint-{code}]: ` prefixes. CI scripts that
  filter on `error[lint-` get a clean lint-internal failure
  signal; click usage errors and any compat-side error_exit calls
  carry their own prefixes (acknowledged coverage gap in R20a).
- **`--rule-pack MODULE` is a fully-qualified dotted Python module
  name (R8)**. The CLI calls `importlib.import_module(MODULE)` and
  passes the resulting module object to `engine.load_rule_pack`.
  Built-in packs use full names like
  `protokit.schema.lint.rules.naming`; user packs collide with
  built-ins only on full-name match. R25's stderr provenance line
  uses full module names so users spot dual-loading.
- **Integration test cold-import smoke step extension**. D1's CI
  smoke step asserts `import protokit.schema; ...` does not load
  the lint subpackage. D3 extends with two more assertions:
  `import protokit.schema; ...` does not load
  `protokit.schema.lint.cli` OR
  `protokit.formatters._builtin_lint`.

## Open Questions

### Resolved During Planning

- **Should `engine.load_rule_pack`'s `DuplicateRuleError` route
  to a stable error-prefix code?** Yes — added
  `error[lint-rule-collision]:` to R20a's code list (Unit 3).
  Reachable when `--no-builtin-rules` is unset and a `--rule-pack`
  declares a `rule_id` colliding with a built-in.
- **Should bad `--rule-pack` module names route to a stable
  code?** Yes — added `error[lint-rule-pack-import]:` to the list
  for `ModuleNotFoundError` / `ImportError` from
  `importlib.import_module` in Unit 3.
- **Should `--profile` use `click.Choice`?** No — profile names
  are pack-defined (the `default` for `naming` is registered via
  `@lint_rule(profiles=("default",))`) and may grow with `--rule-pack`.
  Use `click.STRING` and validate at runtime via R11's
  introspection mechanism.
- **Should `--max-warnings` use `click.IntRange(min=0)`?** Yes —
  negative values are nonsensical; click handles the validation
  uniformly with its `Usage: Error:` prefix (acceptable per R20a's
  click-owned-prefix carve-out).
- **Should `_builtin_lint` import live at the top of
  `lint/cli.py` or inside the click callback?** At module top.
  Module-top mirrors compat's pattern at
  `protokit/cli.py:16-17`. Inside-callback would force one extra
  registration check per invocation. The cold-import contract is
  preserved either way (the contract is `import protokit.schema`
  doesn't load lint, NOT `import protokit.schema.lint.cli` is
  side-effect-free).
- **Where do test fixtures for the new CLI tests live?** Under
  `tests/schema/lint/cli_fixtures/` — small `.proto` files for
  `--proto` mode tests, pre-built `.descriptor_set` files for
  descriptor-set-mode tests. Consistent with D2's fixture
  layout under `tests/schema/lint/fixtures/`.

### Deferred to Implementation

- Exact stderr message wording for each `error[lint-...]:` code
  — choose during implementation; tests assert the prefix and
  the presence of context strings (e.g., the unknown profile name,
  the conflicting rule_id), not exact phrasing.
- Help-text wording for `protokit lint --help` — generated by
  click decorators; copy-edit during implementation. The help
  text MUST render `_LINT_ERROR_CODES` so CI authors can reference
  it without reading source.
- Whether `_load_descriptor_sets_to_result` accepts `Path` or
  `os.PathLike` for input — match the existing
  `load_descriptor_pool` signature in `_cli_utils.py`.
- Click parameter ordering — match compat's order where flags
  align (`--profile`, `--format`, `--quiet`, etc.).
- Test parametrization style — match D2's
  `tests/schema/lint/test_engine.py` parametrization style.

## Output Structure

D3 creates several new files; the layout mirrors compat's existing
structure under `src/protokit/schema/`:

```text
src/protokit/
├── cli.py                                      # MODIFIED: add `lint` subcommand
├── formatters/
│   ├── _registry.py                            # MODIFIED: FormatterKind.LINT_REPORT
│   ├── __init__.py                             # UNCHANGED (eager-load tuple preserved)
│   └── _builtin_lint.py                        # NEW: registers human lint formatter
└── schema/
    └── lint/
        ├── cli.py                              # NEW: click subcommand
        ├── _cli_utils.py                       # NEW: error_exit_with_code + _LINT_ERROR_CODES + _load_descriptor_sets_to_result + _run_lint_formatter_safely
        ├── model.py                            # MODIFIED: AC-05/AC-06 docstring tightening only
        └── rules/
            └── __init__.py                     # MODIFIED: BUILTIN_PACKS = (naming,)

tests/
├── test_formatters_registry.py                 # MODIFIED: rename test_all_four_kinds_present → test_all_kinds_present; assert 5-kind set
└── schema/lint/
    ├── cli/                                    # NEW: CLI test directory
    │   ├── conftest.py                         # NEW: session-scoped fixture compiling .proto sources to tmp .descriptor_set files
    │   ├── test_cli_input_modes.py             # Unit 2 tests
    │   ├── test_cli_rule_loading.py            # Unit 3 tests
    │   ├── test_cli_profile_resolution.py      # Unit 3 tests
    │   ├── test_cli_ci_gating.py               # Unit 4 tests
    │   ├── test_cli_error_codes.py             # Unit 4 tests
    │   ├── test_cli_integration.py             # Unit 5 end-to-end
    │   └── cli_fixtures/                       # NEW: .proto source files (compiled at test time, not checked in as binaries)
    │       ├── all_kinds.proto
    │       ├── duplicate_root_a.proto
    │       ├── duplicate_root_b.proto
    │       ├── pool_conflict_a.proto
    │       └── pool_conflict_b.proto
    ├── test_builtin_packs.py                   # NEW: BUILTIN_PACKS introspection + membership-pin test
    └── test_cold_import_extended.py            # NEW: pytest-runnable parallel to CI YAML smoke step

.github/workflows/
└── ci.yml                                      # MODIFIED: extend Cold-import smoke test step (lines 83-107) to also reject lint.cli + _builtin_lint
```

This is a scope declaration showing the expected output shape;
implementers may consolidate files (e.g., merge unit 4's two test
files) if implementation reveals a better layout. The per-unit
`**Files:**` sections below remain authoritative for what each
unit creates or modifies.

## High-Level Technical Design

> *This illustrates the intended approach and is directional
> guidance for review, not implementation specification. The
> implementing agent should treat it as context, not code to
> reproduce.*

**Decision matrix for `--format` × `--quiet` × `--statistics`:**

| `--format` | `--quiet` | `--statistics` | Output behavior |
|------------|-----------|----------------|-----------------|
| `human` | absent | default ON | Findings + statistics footer (empty rows suppressed) |
| `human` | absent | explicit `--statistics` | Same as above (no-op flag) |
| `human` | absent | explicit `--no-statistics` | Findings only, no footer |
| `human` | `--quiet` | (any) | No output; click warning if `--statistics` also passed; `--quiet` wins |
| `json`/`junit`/`sarif` | absent | (any) | **D3 exits 2** with `error[lint-format-unavailable]:` (D4 makes these passing) |
| `json`/`junit`/`sarif` | `--quiet` | (any) | **Click validation error** — `--quiet` mutex with non-`human` formats; exit 2 with `Usage:` prefix |

**Subcommand load + invocation flow (mermaid):**

```
sequenceDiagram
    participant U as User
    participant CLI as protokit/cli.py
    participant LCL as schema/lint/cli.py
    participant BL as formatters/_builtin_lint.py
    participant REG as formatters/_registry.py
    participant ENG as schema/lint/engine.py

    U->>CLI: protokit lint a.descriptor_set
    Note over CLI: Module load (once per process; subsequent in-process callers reuse cached modules per sys.modules)
    CLI->>LCL: import schema.lint.cli (top-level import)
    LCL->>BL: import _builtin_lint (top-level import)
    BL->>REG: _register_builtin("human", _render_human, FormatterKind.LINT_REPORT)
    Note over CLI: Module load complete; click dispatches to subcommand callback. _register_builtin's idempotency makes module reload safe in test suites.
    CLI->>LCL: invoke lint() callback
    LCL->>LCL: load BUILTIN_PACKS (unless --no-builtin-rules)
    LCL->>LCL: load --rule-pack modules via importlib
    LCL->>ENG: engine.load_rule_pack for each loaded pack
    LCL->>LCL: compose LintProfile.from_pack across packs
    LCL->>LCL: emit R25 stderr provenance line (unless --quiet)
    LCL->>ENG: engine.run(compile_result, profile=composed)
    ENG-->>LCL: LintReport
    LCL->>REG: get_formatter("human", FormatterKind.LINT_REPORT)
    REG-->>LCL: human renderer
    LCL->>LCL: render report + statistics footer (unless --quiet)
    LCL->>U: stdout findings + footer; exit per R20 ladder
```

The crucial point: `_builtin_lint` registers at MODULE LOAD time
of `schema/lint/cli.py`, which itself is loaded at module load
time of `protokit/cli.py` (the entry point). The cold-import
contract holds because `import protokit.schema` does NOT load
`protokit.cli`.

## Implementation Units

- [ ] **Unit 1: Formatter substrate + auto-load list anchor**

**Goal:** Land all the locked-but-static substrate D3 needs
before the CLI scaffold itself: the `FormatterKind.LINT_REPORT`
enum value, an empty-but-importable `_builtin_lint.py` skeleton
with the human formatter registered via `_register_builtin`, and
the `BUILTIN_PACKS` constant on `lint/rules/__init__.py` that
KD-9's upgrade-safety policy anchors against. No CLI surface yet;
this unit is exercised exclusively via library imports + tests.

**Requirements:** R14, R15, R6 (anchor only), KD-9 anchor.

**Dependencies:** None (D2 already on main).

**Files:**
- Modify: `src/protokit/formatters/_registry.py` (add
  `FormatterKind.LINT_REPORT` per the line 41-42 noun-form
  convention)
- Create: `src/protokit/formatters/_builtin_lint.py`
- Modify: `src/protokit/schema/lint/rules/__init__.py` (add
  `BUILTIN_PACKS: tuple[ModuleType, ...] = (naming,)` constant +
  docstring tying membership changes to major-version events)
- Modify: `src/protokit/formatters/__init__.py` —
  **VERIFY-ONLY**: confirm `_builtin_lint` is NOT added to the
  eager-load tuple at lines 60-71. No actual modification.
- Test: `tests/schema/lint/test_builtin_packs.py` (new)
- Test: `tests/test_formatters_registry.py` (modify existing —
  update `test_all_four_kinds_present` to assert the 5-kind set
  including `LINT_REPORT`)

**Approach:**
- `FormatterKind.LINT_REPORT` is a single enum-value addition;
  existing callers don't enumerate exhaustively (verified during
  brainstorm).
- `_builtin_lint.py` exposes a private `_render_human(report:
  LintReport, ctx: FormatterContext) -> str` callable that
  formats findings line-by-line + a `--statistics` footer
  (per R16 behavior). Footer rendering computes per-severity
  counts inline (no precomputed `severity_counts` field). Module
  body calls `_register_builtin` exactly once at import time.
- `BUILTIN_PACKS` lives at module scope in `rules/__init__.py`.
  The constant's docstring binds membership-changes to a
  major-version + CHANGELOG event (KD-9 anchor); the constant
  itself is a typed `tuple[ModuleType, ...]`.

**Patterns to follow:**
- `_register_builtin` callsite pattern: existing `_builtin_diff.py`
  / `_builtin_compat.py` modules in `src/protokit/formatters/`.
  Follow their import-then-call shape (lint formatter is shorter
  but structurally identical).
- `FormatterContext` consumption: `_builtin_compat.py` shows
  the typical `(report, ctx) -> str` signature already in use.

**Test scenarios:**
- Happy path: `from protokit.formatters._registry import FormatterKind` → `FormatterKind.LINT_REPORT` enumerable; `FormatterKind.LINT_REPORT.value == "LINT_REPORT"` (matches the existing UPPERCASE convention at `_registry.py:48-51` — `DIFF = "DIFF"`, `COMPAT = "COMPAT"`, etc.).
- Happy path: importing `_builtin_lint` registers `(FormatterKind.LINT_REPORT, "human")` in `_REGISTRY`; `get_formatter("human", FormatterKind.LINT_REPORT)` returns the renderer.
- Happy path: `BUILTIN_PACKS` is a tuple of length 1 containing the `naming` module; `BUILTIN_PACKS[0].__name__ == "protokit.schema.lint.rules.naming"`.
- Happy path: **`BUILTIN_PACKS` membership pin** — a dedicated test asserts `tuple(p.__name__ for p in BUILTIN_PACKS) == ("protokit.schema.lint.rules.naming",)`. Failure message references KD-9's policy and instructs adding a CHANGELOG entry alongside any membership change. This converts the upgrade-safety contract from a soft norm into a hard CI gate.
- Edge case: re-importing `_builtin_lint` (via `importlib.reload`) does NOT raise `FormatterError` — verifies `_register_builtin`'s idempotency under reload.
- Edge case: human formatter's `_render_human` on an empty `LintReport` (no findings, no diagnostics, no runtime warnings) returns a minimal output string — exact wording deferred but the function does not raise.
- Error path: passing a non-`LintReport` to `_render_human` raises `AttributeError` (caller's contract violation; not handled here).
- Integration: existing `test_all_four_kinds_present` is **renamed** to `test_all_kinds_present` and updated to assert the 5-kind set including `LINT_REPORT`. Other `list_formatters(FormatterKind.DIFF | COMPAT | COMPAT_HISTORY | COMPAT_BISECT)` calls return their original lists unchanged.

**Verification:**
- `python -c "from protokit.formatters._registry import FormatterKind; print(FormatterKind.LINT_REPORT)"` succeeds.
- `python -c "import protokit.schema; assert 'protokit.schema.lint' not in sys.modules and 'protokit.formatters._builtin_lint' not in sys.modules"` succeeds (cold-import preserved).
- All new tests pass; no regressions in existing `formatters` tests.

---

- [ ] **Unit 2: CLI scaffold + input modes + descriptor-set ingestion helper + lint-CLI helpers**

**Goal:** Wire `protokit lint` as a click subcommand on the
top-level CLI group; implement both input modes (descriptor-set
default + `--proto` source) and the new
`_load_descriptor_sets_to_result` helper that handles multi-path
descriptor-set merging with dedupe-before-Add ordering and
cross-set symbol-collision detection. Land the lint CLI helper
module up-front (`error_exit_with_code` + `_LINT_ERROR_CODES`
constant) so subsequent units use real exit-code paths from the
start rather than placeholder exception types — eliminates the
partial-PR-landing hazard where Unit 2 ships placeholders that
Unit 4 has to backfill.

**Requirements:** R1, R2, R3, R4, R20a (helper + constant land
here; codes added incrementally as later units enable the
corresponding paths), R24.

**Dependencies:** Unit 1 (FormatterKind.LINT_REPORT must exist
because `lint/cli.py` imports `_builtin_lint` at module top).

**Files:**
- Modify: `src/protokit/cli.py` (add
  `from protokit.schema.lint.cli import main as _lint_command`
  + `main.add_command(_lint_command, name="lint")`)
- Create: `src/protokit/schema/lint/cli.py` (click subcommand
  scaffold; positional inputs; `--proto`; `--proto-path`/`-I`
  repeatable)
- Create: `src/protokit/schema/lint/_cli_utils.py` containing:
  - `_LINT_ERROR_CODES: tuple[str, ...]` constant (initial set
    populated for Unit 2's reachable paths: `bad-input`,
    `pool-conflict`, `compile-failed`; later units extend the
    constant as their paths land)
  - `error_exit_with_code(code: str, message: str) -> NoReturn`
    helper (validates `code in _LINT_ERROR_CODES`, writes
    `error[lint-{code}]: {message}` to stderr, calls
    `sys.exit(2)`)
  - `_load_descriptor_sets_to_result(paths: tuple[Path, ...], *,
    quiet: bool) -> CompileResult` (the helper itself emits the
    duplicate-filename stderr line directly when not `quiet`,
    avoiding the data-flow gap that would otherwise require
    threading `duplicate_warnings` back to the CLI callback)
- Test: `tests/schema/lint/cli/test_cli_input_modes.py` (new)
- Test: `tests/schema/lint/test_cold_import_extended.py` (new —
  pytest-runnable parallel to the CI-YAML smoke step; gives
  local feedback before push)
- Test fixtures (using D2's at-test-time compile pattern, NOT
  checked-in `.descriptor_set` binaries — matches
  `tests/schema/lint/test_engine.py` / `test_canary_naming.py`):
  - `tests/schema/lint/cli/cli_fixtures/all_kinds.proto`
  - `tests/schema/lint/cli/cli_fixtures/duplicate_root_a.proto`
    + `duplicate_root_b.proto` (same `package` + `message`
    names, identical content for the duplicate-filename test)
  - `tests/schema/lint/cli/cli_fixtures/pool_conflict_a.proto`
    + `pool_conflict_b.proto` (different `package`-qualified
    file names but a colliding message FQN, for the cross-set
    symbol-collision test)
  - A session-scoped pytest fixture in
    `tests/schema/lint/cli/conftest.py` compiles each `.proto`
    to a tmp-path `.descriptor_set` via D1's
    `compile_protos_to_result` (works on both `has_protoxy=true`
    and `=false` CI cells via D1's existing protoc fallback)

**Approach:**
- `lint/cli.py` defines a click `@click.command()` (NOT
  `@click.group()` — single command per R1) wrapped by a shim
  function exported as `main` to mirror compat's
  `from protokit.schema.cli import main as _compat_command`
  pattern.
- `_load_descriptor_sets_to_result(paths: tuple[Path, ...], *,
  quiet: bool) -> CompileResult` follows the algorithm from R24:
  - Initialize fresh `DescriptorPool`, `seen_names: set[str]`,
    `duplicate_count: int`, `root_files: list[str]`.
  - Iterate `paths` in command-line argv order; within each
    path, iterate `fds.file` in protobuf parse order.
  - For each `fd`: if `fd.name in seen_names`, increment
    `duplicate_count` and skip; else add to `seen_names`, call
    `pool.Add(fd)` (on `TypeError` route directly to
    `error_exit_with_code("pool-conflict", f"{path}: {exc}")`),
    append `fd.name` to `root_files`.
  - On per-path read or parse failure: route directly to
    `error_exit_with_code("bad-input", f"{path}: {exc}")` —
    helper exists from this unit.
  - When `not quiet` and `duplicate_count > 0`: write a stderr
    line like
    `protokit lint: deduplicated {duplicate_count} duplicate
    file path(s) across input sets` BEFORE returning. This keeps
    the duplicate-warning side effect inside the helper rather
    than requiring `CompileResult` to grow new fields.
  - Return `CompileResult(pool=pool,
    root_files=tuple(root_files), diagnostics=())`.
- `--proto` mode delegates to D1's
  `compile_protos_to_result(paths, proto_paths)` directly. Its
  diagnostics drive the `lint-compile-failed` exit-2 path —
  wired here via `error_exit_with_code("compile-failed", ...)`
  when `result.diagnostics` contains any `category="error"`
  entries.
- Cold-import test: parametrize over a list of "must NOT be in
  sys.modules after `import protokit.schema`" — extends D1's
  baseline with `protokit.schema.lint.cli` and
  `protokit.formatters._builtin_lint`.

**Patterns to follow:**
- `protokit/schema/cli.py:583-680` — `@click.argument` /
  `@click.option` decorator stack and signature shape.
- `_cli_utils.load_descriptor_pool` — single-path descriptor-set
  loader; D3's helper extends to multi-path.
- D1's CI cold-import smoke test (referenced in
  `docs/brainstorms/2026-04-30-protokit-lint-delivery-1-foundation-requirements.md`).

**Test scenarios:**
- Happy path: `protokit lint <fixture>.descriptor_set` (built
  from the `all_kinds.proto` fixture via the conftest fixture)
  invokes the click callback, no errors (formatter renders empty
  footer if no findings).
- Happy path: `protokit lint --proto <fixture>.proto -I <dir>`
  compiles the source via `compile_protos_to_result`, runs the
  pipeline.
- Happy path: multi-path descriptor-set
  `protokit lint a.descriptor_set b.descriptor_set` merges
  pools and accumulates `root_files` from both inputs in
  argv-order, deduplicating by `fd.name` (first occurrence wins).
- Edge case: zero positional arguments → click usage error
  (exit 2, click-owned prefix `Usage:` / `Error:`).
- Edge case: `protokit lint --proto` with no positional
  arguments → click usage error.
- Edge case: descriptor-set with overlapping `fd.name` across
  inputs → first-occurrence-wins; helper emits stderr line
  `protokit lint: deduplicated 1 duplicate file path(s) across
  input sets` (suppressed under `--quiet`).
- Edge case: descriptor-set with overlapping `fd.name` AND
  `--quiet` → no stderr line emitted; lint proceeds normally.
- Error path: malformed bytes (non-FileDescriptorSet) → exit 2
  via `error[lint-bad-input]:` (real helper, not placeholder).
- Error path: cross-set symbol collision (different `fd.name`,
  same message FQN — exercised by `pool_conflict_a.proto` +
  `pool_conflict_b.proto` fixtures) → `pool.Add` raises
  `TypeError`; helper exits 2 via `error[lint-pool-conflict]:`.
- Error path: `--proto` mode with a `.proto` that has a syntax
  error → `compile_protos_to_result` populates
  `diagnostics`; helper exits 2 via `error[lint-compile-failed]:`.
- Integration: Cold-import smoke — `import protokit.schema; ...`
  does NOT load `protokit.schema.lint.cli` or
  `protokit.formatters._builtin_lint`; `import protokit.cli;
  ...` DOES load both (verifies the deferred-load contract).
  Also covered by Unit 5's CI YAML extension.
- Integration: `protokit diff <args>` and
  `protokit compat <args>` continue to work unchanged
  (regression check that the third subcommand registration does
  not break the other two).

**Verification:**
- `protokit lint --help` renders without errors and lists
  positional inputs + `--proto` + `--proto-path`.
- All Unit 2 tests pass; existing diff/compat CLI tests still
  pass.

---

- [ ] **Unit 3: Rule loading + profile resolution + R25 provenance**

**Goal:** Land the rule-loading machinery (`BUILTIN_PACKS`
auto-load, `--no-builtin-rules`, `--rule-pack` repeatable),
profile resolution + composition, `--min-severity` numeric
override, R9 zero-rules loud failure, R11 unknown-profile loud
failure with introspection, and R25 composition stderr
provenance line.

**Requirements:** R6, R7, R8, R9, R10, R11, R12, R25.

**Dependencies:** Unit 2 (CLI scaffold must exist).

**Files:**
- Modify: `src/protokit/schema/lint/cli.py` (add `--no-builtin-rules`,
  `--rule-pack`, `--profile`, `--min-severity` click options;
  add rule-loading + profile-composition logic; emit R25
  provenance line)
- Modify: `src/protokit/schema/lint/_cli_utils.py` (add
  `_compose_active_profile`, `_introspect_declared_profiles`
  helpers; runtime importlib-based loading helper)
- Test: `tests/schema/lint/cli/test_cli_rule_loading.py` (new)
- Test: `tests/schema/lint/cli/test_cli_profile_resolution.py` (new)

**Approach:**
- Auto-load: iterate `protokit.schema.lint.rules.BUILTIN_PACKS`
  unless `--no-builtin-rules` is set; for each module call
  `engine.load_rule_pack(module)`.
- `--rule-pack`: for each value, call
  `importlib.import_module(value)` and pass to
  `engine.load_rule_pack`. `ImportError` /
  `ModuleNotFoundError` → exit 2 via
  `error_exit_with_code("rule-pack-import", ...)` (real helper
  from Unit 2; this unit extends `_LINT_ERROR_CODES` to add
  `rule-pack-import`).
- `DuplicateRuleError` from `engine.load_rule_pack` → exit 2
  via `error_exit_with_code("rule-collision", ...)` (this unit
  extends `_LINT_ERROR_CODES` to add `rule-collision`).
- `TypeError` from `engine.load_rule_pack` (raised when a user
  pack's `RULES` contains a non-`@lint_rule`-decorated callable —
  `LintProfile.from_pack`'s contract) → routed via the same
  `rule-pack-import` code (post-import structural failures
  semantically belong with import failures). Plan to clarify
  the helper's name to "rule-pack-load" if a future review
  surfaces the rename, but for D3 the existing name is
  acceptable.
- Profile resolution: build per-pack profiles via
  `LintProfile.from_pack(pack, profile_name)`; pass list to
  `LintProfile.compose(*per_pack_profiles)`.
- R11 introspection: walk each loaded pack's `RULES` tuple,
  extract `_lint_spec.profiles` via
  `protokit.schema.lint.decorator.get_lint_spec`, build
  `dict[str, frozenset[str]]` (pack-name → declared profiles).
  Empty composed profile → render this dict in stderr +
  `error_exit_with_code("unknown-profile", ...)`.
- R9 zero-rules: after loading, if the engine has no registered
  rules (implementation: `len(engine._loaded_specs) == 0` —
  acknowledged private-attribute access; lint CLI is a
  first-class consumer of the engine in protokit), exit 2 via
  `error_exit_with_code("no-rules", ...)` (this unit extends
  `_LINT_ERROR_CODES` to add `no-rules`). R9 fires BEFORE R25
  provenance and BEFORE profile resolution (R11) — short-circuit
  ordering: load → R9 → profile compose → R11 → R25 → engine.run.
- `--min-severity LEVEL`: `click.Choice(["info", "warning",
  "error"], case_sensitive=False)`. If unset, use composed
  profile's `min_severity`. If set, override via
  `dataclasses.replace(composed_profile, min_severity=...)`
  (LintProfile is frozen but `dataclasses.replace` re-runs
  `__post_init__` correctly — re-snapshots
  `rule_severity_overrides`; tested as part of this unit).

  *Relaxation observability (D3 stderr breadcrumb)*: when
  `--min-severity` is passed AND the resulting floor is more
  lenient than the composed floor (i.e., user passed `info` or
  `warning` against a composed floor of `warning` or `error`),
  emit a stderr line analogous to R25:
  `protokit lint: --min-severity={user-level} relaxes profile
  floor from {composed-level} to {effective-level}`.
  Suppressed under `--quiet`. This restores observability of
  free-relaxation without extending D2's locked
  `LintRuntimeWarning.category` Literal type — the
  Literal-extension version of this signal is deferred to D5
  (per the brainstorm's R12 deferral). Note: as documented in
  R10's implementation note, `from_pack` always returns
  WARNING, so this breadcrumb fires today only when
  `--min-severity info` is passed against any composed floor;
  it lands its first richer signal when D5 pyproject config
  introduces non-default-floor profiles.
- R25 provenance: after rule loading + profile resolution
  succeed (i.e., R9 and R11 short-circuits did NOT fire),
  before `engine.run`, format the line as
  `protokit lint: profile '{name}' from
  {pack1}=[{rule_ids1}]; {pack2}=[{rule_ids2}]`
  using full `module.__name__`s and verbatim rule_ids.
  Suppressed under `--quiet`; never written to `stdout`.
  R25 does NOT fire when R9 (zero rules) or R11 (empty
  profile) preempts execution — those exit 2 first.

**Patterns to follow:**
- `LintProfile.compose` short-circuit behavior (already
  in `lint/model.py`).
- Compat's runtime rule-pack loading at
  `src/protokit/schema/cli.py:_load_rule_packs` — mirror the
  importlib pattern but adapted for lint's wire format
  (decorated callables, NOT (rule_id, fn) tuples).

**Test scenarios:**
- Happy path: bare `protokit lint <fixture>.descriptor_set`
  auto-loads `BUILTIN_PACKS` and runs `naming/snake-case-fields`.
- Happy path: `--profile default` is the default value; same
  behavior as no flag.
- Happy path: `--no-builtin-rules --rule-pack=test_pack`
  loads only the user pack.
- Happy path: `--rule-pack=pack_a --rule-pack=pack_b` loads
  both on top of built-ins; R25 line shows all 3 packs.
- Happy path: R25 provenance line fires after rule loading +
  profile resolution succeed (single pack: `protokit lint:
  profile 'default' from
  protokit.schema.lint.rules.naming=[naming/snake-case-fields]`).
  Suppressed under `--quiet`; preempted by R9 / R11 short-circuits.
- Happy path: `--min-severity error` raises composed
  WARNING-default to ERROR; only ERROR-severity findings
  surface in `report.findings`. No relaxation breadcrumb
  emitted (override is more strict).
- Happy path: `--min-severity info` against the WARNING
  composed default emits the relaxation breadcrumb
  `protokit lint: --min-severity=info relaxes profile floor
  from warning to info` on stderr; suppressed under `--quiet`.
- Edge case: `--profile default` resolves to non-empty
  `rule_ids` because canary declares `profiles=("default",)`.
- Edge case: `--no-builtin-rules` with no `--rule-pack` → R9
  loud failure (`error[lint-no-rules]:`).
- Edge case: empty `RULES` tuple in a user pack with
  `--no-builtin-rules` → R9 loud failure.
- Edge case: `--rule-pack=test_pack_strict_only --profile default`
  where `test_pack_strict_only` declares only `profiles=("strict",)`
  → R11 loud failure with stderr listing the declared profiles.
- Edge case: `--min-severity warning` (default) doesn't change
  behavior (composed default is already WARNING).
- Edge case: same `module.__name__` passed twice via
  `--rule-pack` → engine idempotency-guard short-circuits;
  R25 line lists the pack once.
- Error path: `--rule-pack=does.not.exist` →
  `ModuleNotFoundError` → exit 2 via `lint-rule-pack-import`
  prefix (placeholder until Unit 4 lands the helper).
- Error path: `--rule-pack=test_pack_collision` declaring
  `naming/snake-case-fields` (colliding with built-in) →
  `DuplicateRuleError` from `engine.load_rule_pack` → exit 2
  via `lint-rule-collision` prefix.
- Error path: `--profile typo` → R11 loud failure;
  stderr message includes the typo'd name + every loaded
  pack's declared profiles.
- Error path: `--min-severity nope` → click validation error
  (`Usage:` prefix, click-owned, exit 2).
- Integration: R25 line emits to stderr (not stdout); under
  `--quiet` no R25 line emits; the mutually-exclusive
  interaction with `--format json` (Unit 4 territory) does
  not break R25 emission ordering — provenance fires before
  the format-validation exit.

**Verification:**
- All scenarios above pass.
- `protokit lint --help` renders updated help text including
  the new flags.
- Existing diff/compat CLI tests still pass.

---

- [ ] **Unit 4: CI gating + statistics + format-unavailable + lint-side formatter wrapper**

**Goal:** Land the CI gating mechanics (`--max-warnings`,
`--statistics`/`--no-statistics`, `--quiet`), the exit-code
ladder (R20), the `--format` flag with the
`lint-format-unavailable` error path, and a lint-side
formatter wrapper that produces the
`error[lint-formatter-exception]:` stable prefix on formatter
exceptions (the existing `protokit._cli_utils.run_formatter_safely`
hardcodes the legacy `Error:` prefix and would not produce the
stable lint prefix without modification).

**Requirements:** R13 (final wiring of format-unavailable
case), R16, R18, R19, R20, R20a (extends `_LINT_ERROR_CODES`
with `format-unavailable`, `formatter-exception`).

**Dependencies:** Unit 3 (rule loading + profile resolution +
`error_exit_with_code` helper all already exist by this point;
this unit only EXTENDS `_LINT_ERROR_CODES` with the two
remaining codes and adds the new wrapper).

**Files:**
- Modify: `src/protokit/schema/lint/_cli_utils.py` (extend
  `_LINT_ERROR_CODES` with `format-unavailable` and
  `formatter-exception`; add module docstring binding the
  constant to user-visible help text; add new
  `_run_lint_formatter_safely(fn, report, ctx, *, name)`
  wrapper that calls
  `protokit._cli_utils.run_formatter_safely`'s underlying
  guard logic but routes ALL exceptions — including
  SystemExit per the formatter-systemexit-bypass learning —
  to `error_exit_with_code("formatter-exception", ...)`. The
  legacy `run_formatter_safely` stays untouched; lint's
  wrapper is a thin lint-specific replacement that mirrors
  the same SystemExit + Exception + stdout-leak guards but
  produces the lint stable prefix)
- Modify: `src/protokit/schema/lint/cli.py` (add
  `--format`, `--max-warnings`,
  `--statistics`/`--no-statistics`, `--quiet` click options;
  wire `_run_lint_formatter_safely` for the formatter call;
  compute exit code per R20)
- Test: `tests/schema/lint/cli/test_cli_ci_gating.py` (new)
- Test: `tests/schema/lint/cli/test_cli_error_codes.py` (new)

**Execution note:** Test-first for the
`error_exit_with_code` helper and the exit-code ladder —
both are pure-function-shaped surfaces that benefit from
red-green discipline. The `--statistics` footer rendering
can be implemented test-with rather than test-first.

**Approach:**
- By this unit's end, `_LINT_ERROR_CODES` contains the full
  D3 set: `("no-rules", "unknown-profile",
  "format-unavailable", "compile-failed",
  "formatter-exception", "bad-input", "pool-conflict",
  "rule-collision", "rule-pack-import")`. Order is stable and
  matches the R20a list. Earlier units extended the constant
  incrementally as their paths landed (Unit 2: `bad-input`,
  `pool-conflict`, `compile-failed`; Unit 3: `no-rules`,
  `unknown-profile`, `rule-collision`, `rule-pack-import`).
  This unit appends `format-unavailable` and
  `formatter-exception`.
- `error_exit_with_code` already exists from Unit 2; this unit
  has no new helper-API surface to add (only the formatter
  wrapper).
- `--format`: `click.STRING` (NOT `click.Choice` — formatter
  registry is the source of truth, runtime-validated). Empty
  / unknown values: `KeyError` from `get_formatter` →
  `error_exit_with_code("format-unavailable", ...)` with the
  available list rendered via `list_formatters(FormatterKind.LINT_REPORT)`.
  PROTOKIT_FORMAT cross-subcommand note appended to the
  message (per R13).
- `--max-warnings`: `click.IntRange(min=0)`, default `None`.
  When set, count WARNING-severity findings in
  `report.findings` post-min-severity-filter; exit 1 if
  count > N.
- `--statistics`: `click.option("--statistics/--no-statistics",
  default=None)`. Click's slash-syntax produces a true
  three-state boolean (None=default, True=explicit `--statistics`,
  False=explicit `--no-statistics`). Default ON in human format
  unless `--quiet`. Footer rendering:
  - Per-severity counts (computed by iterating
    `report.findings`)
  - Filtered count (from `LintReport.filtered_count`)
  - Runtime warning count (from
    `len(LintReport.runtime_warnings)`)
  - Empty rows (zero counts) suppressed.
- `--quiet`: `click.option(is_flag=True, default=False)`.
  Mutex with non-`human` format → click validation error
  (`Usage:` prefix). Mutex-soft with `--statistics` → click
  warning + `--quiet` wins.
- Exit code logic per R20: 0 (clean), 1 (ERROR present OR
  WARNING > max-warnings), 2 (any of the
  `error_exit_with_code` paths or formatter exception).

**Patterns to follow:**
- `protokit._cli_utils.run_formatter_safely` (read-only
  reference) — its internal guard structure for
  `except SystemExit` + `except Exception` + stdout-leak
  detection is the model for `_run_lint_formatter_safely`.
  Lint's wrapper mirrors the guards but routes through
  `error_exit_with_code("formatter-exception", ...)` instead
  of the legacy `error_exit` helper, producing the
  `error[lint-formatter-exception]:` stable prefix that R20a
  promises.
- `protokit.schema.cli._resolve_common_flags` — example of
  bundling `--quiet` + `--format` validation interaction.

**Test scenarios:**
- Happy path: `protokit lint --max-warnings 0 <clean>.descriptor_set`
  exits 0 (no findings).
- Happy path: `protokit lint --max-warnings 0 <bad>.descriptor_set`
  with one WARNING finding exits 1.
- Happy path: `protokit lint --max-warnings 5 <bad>.descriptor_set`
  with 3 WARNING findings exits 0; with 6 WARNING findings exits 1.
- Happy path: `protokit lint --statistics <bad>.descriptor_set`
  emits a footer with non-zero rows only.
- Happy path: `protokit lint --quiet <bad>.descriptor_set`
  produces no stdout output; exit code reflects findings.
- Happy path: `protokit lint --format human` works (default).
- Edge case: `--max-warnings 0` with one ERROR-severity finding
  exits 1 (ERROR always exits 1 regardless of N).
- Edge case: `--max-warnings 0` with one INFO-severity finding
  exits 0 (INFO never gates).
- Edge case: `--statistics` with all-zero counts produces an
  empty footer (or single-line "Lint complete: no findings"-style
  marker — exact wording deferred but tests assert non-zero rows
  are absent).
- Edge case: `--no-statistics` overrides default-ON.
- Edge case: `--quiet --statistics` triggers click warning;
  `--quiet` wins (no footer).
- Edge case: `PROTOKIT_FORMAT` envvar set to `human` with no
  `--format` flag → human format used.
- Edge case: `_LINT_ERROR_CODES` is sorted/stable order; help
  text renders the list verbatim.
- Error path: `--format=json` →
  `error[lint-format-unavailable]:` + lists `human` as
  available + cross-subcommand envvar note.
- Error path: `--format=does-not-exist` → same
  `error[lint-format-unavailable]:` path.
- Error path: `--quiet --format=json` → click mutex error
  (`Usage:` prefix, exit 2; click-owned, NOT lint stable
  prefix).
- Error path: `--max-warnings=-1` → click `IntRange` error
  (`Usage:` prefix, click-owned).
- Error path: formatter callable raises `RuntimeError` →
  `_run_lint_formatter_safely` catches → exit 2 via
  `error[lint-formatter-exception]:`.
- Error path: formatter callable calls `sys.exit(0)` →
  `_run_lint_formatter_safely`'s `except SystemExit` catches
  per the formatter-systemexit-bypass learning → exit 2 via
  `error[lint-formatter-exception]:` (security regression
  prevention).
- Error path: source compile (`--proto` mode) produces
  `CompileResult.diagnostics` with category=error → exit 2
  via `error[lint-compile-failed]:`.
- Integration: R25 ordering test deferred to Unit 5
  end-to-end (no duplication here).
- Integration: every code in `_LINT_ERROR_CODES` has a
  corresponding test that verifies the exact stderr prefix
  (parametrized over the constant tuple — single source of
  truth for both implementation and tests).

**Verification:**
- All scenarios above pass.
- `protokit lint --help` renders the `_LINT_ERROR_CODES` list
  in the help text (single source of truth — drift test
  asserts help text contains every code).
- Error-prefix tests parametrize over `_LINT_ERROR_CODES` —
  count matches; no drift.

---

- [ ] **Unit 5: D2 residual docstring fold-ins (AC-05/AC-06) + integration tests + CI cold-import gate extension**

**Goal:** Land the two D2 ce:review residuals that are
docstring-only, complete the integration test suite spanning
all flag combinations, and extend the CI cold-import smoke
step to cover `lint.cli` and `_builtin_lint`.

**Requirements:** R22, R23 (docstring fold-ins);
end-to-end test coverage of every flag combination,
loud-failure path, error-prefix code, and the cold-import
quarantine.

**Dependencies:** Units 1-4 (the implementation surfaces all
exist).

**Files:**
- Modify: `src/protokit/schema/lint/model.py` (R22 — add
  `ctx.pool` mutation contract paragraph to
  `_LintContextEmitMixin` docstring AND each per-kind context
  dataclass docstring; R23 — tighten `LintRuleError`
  docstring from "at minimum includes" to "exactly is" for
  the catch-tuple list)
- Create: `tests/schema/lint/cli/test_cli_integration.py` (new
  — end-to-end coverage spanning units 2-4)
- Modify: `.github/workflows/ci.yml` — extend the inline
  `Cold-import smoke test` step at lines 83-107 to also
  reject `protokit.schema.lint.cli` and
  `protokit.formatters._builtin_lint` from `sys.modules` after
  `import protokit.schema`. (D1's smoke step lives in CI YAML
  as an inline `python -c ...` block, NOT in
  `tests/test_static_analysis.py` which is the ruff/mypy
  ratchet only.)
- The pytest-runnable `tests/schema/lint/test_cold_import_extended.py`
  created in Unit 2 gives local-feedback parallel coverage; the
  CI YAML extension is the authoritative gate.

**Approach:**
- AC-05 docstring: rules MUST NOT mutate `ctx.pool` during
  the walk. Add the prohibition sentence to the `pool`
  attribute docstring (Attributes section) of each of the
  eight per-kind context dataclasses (FileLintContext,
  ServiceLintContext, MethodLintContext, EnumLintContext,
  EnumValueLintContext, MessageLintContext, FieldLintContext,
  OneofLintContext). The mixin (`_LintContextEmitMixin`) has
  no `pool` attribute of its own — add the prohibition as a
  class-level note in the mixin docstring referring readers
  to the per-kind docstrings.
- AC-06 docstring: change "at minimum includes" → "is
  exactly" in the `LintRuleError` docstring's catch-tuple
  description.
- Integration tests: cover the matrix of meaningful flag
  combinations spanning rule loading, profile resolution,
  CI gating, output formatting, and exit codes. Reuse
  fixtures from Units 2-4.
- CI cold-import gate: extend `.github/workflows/ci.yml`'s
  `Cold-import smoke test` step at lines 83-107 to add two new
  not-in-sys.modules assertions for `protokit.schema.lint.cli`
  and `protokit.formatters._builtin_lint`.

**Patterns to follow:**
- D2's `tests/schema/lint/test_engine.py` end-to-end shape
  for the integration tests.
- D1's existing cold-import smoke step pattern (verified
  during impl).

**Test scenarios:**
- Integration: full pipeline single-pack —
  `protokit lint --proto valid.proto -I dir/ --statistics`
  produces findings + footer + exit 1, end-to-end.
- Integration: full pipeline multi-pack —
  `protokit lint --rule-pack=mypack a.descriptor_set b.descriptor_set
  --max-warnings 5 --quiet` exit code reflects findings; no
  stdout; R25 provenance line lists both packs on stderr.
- Integration: full pipeline error chain —
  `protokit lint --no-builtin-rules --profile typo
  --format=json a.descriptor_set` exits 2 with the FIRST
  detected error: R9 `lint-no-rules:` (the absence of any
  rules short-circuits before profile validation, which would
  short-circuit before format validation).
- Integration: cold-import smoke step extended; CI matrix
  passes on all 4 cells (`python: ["3.10", "3.12"] ×
  has_protoxy: [true, false]`).
- Happy path (AC-05): `_LintContextEmitMixin` docstring
  contains the `ctx.pool` mutation prohibition.
- Happy path (AC-06): `LintRuleError.__doc__` says "is
  exactly" (NOT "at minimum includes") for the catch tuple.
- Edge case: existing D2 tests that referenced the older
  `LintRuleError` docstring text (if any) updated.
- Regression: all 867 existing tests stay green;
  `tests/test_static_analysis.py` ratchet does not regress.

**Verification:**
- Full test suite green (target: ~900+ tests after D3 lands).
- CI matrix green on all 4 cells.
- Cold-import smoke step passes locally and in CI.
- Manual smoke: `protokit lint <fixture>.descriptor_set`,
  `protokit lint --proto <fixture>.proto -I <dir>`,
  `protokit lint --rule-pack <user_pack>
  <fixture>.descriptor_set` — all behave per Success
  Criteria in the origin doc.

## System-Wide Impact

- **Interaction graph:** D3 adds a third subcommand on
  `protokit/cli.py`'s click group adjacent to `diff` and `compat`.
  No interaction between subcommands at runtime; click dispatches
  by name. The shared formatter registry (`protokit.formatters._registry`)
  gains a new `LINT_REPORT` discriminator that compat / diff are
  unaware of — `clear_user_formatters` and `list_formatters` calls
  with the existing four kinds remain unchanged.
- **Error propagation:** Lint's exit-2 paths route exclusively
  through `error_exit_with_code` (lint-side helper). Click usage
  errors propagate via click's own machinery with `Usage:` prefix.
  Compat's `error_exit` and its callsites are untouched. CI
  scripts that filter on `error[lint-` get a clean lint-internal
  failure signal independent of compat's stderr.
- **State lifecycle risks:** The `_register_builtin` call inside
  `_builtin_lint.py` runs at module-import time and is idempotent
  under reload. Test isolation is preserved via the existing
  `clear_user_formatters` test fixture pattern (built-ins survive
  `clear_user_formatters` by design — `_BUILTIN_NAMES` reservation
  protects them).
- **API surface parity:** D3 introduces `FormatterKind.LINT_REPORT`
  as a public enum value; consumers of `FormatterKind` may need
  to handle the fifth case. The codebase audit confirms no
  exhaustive `match` statements over the enum exist that would
  silently miss the new case; tests parametrized over the enum
  are updated in Unit 1.
- **Integration coverage:** Multi-flag interactions (`--quiet` +
  `--statistics`, `--format=json` + R25 provenance ordering, R9
  short-circuit before R11 short-circuit before R13, etc.) are
  covered in Unit 5 integration tests.
- **Unchanged invariants:** `protokit diff` and `protokit compat`
  CLI behaviors are bit-for-bit unchanged. The formatter registry's
  built-in entries for the four pre-existing FormatterKinds remain
  registered with the same names. D2's engine API (`LintEngine.run`
  signature, `LintProfile.compose` semantics, `LintRuntimeWarning.category`
  Literal type) is unchanged. The cold-import contract from D1 is
  preserved.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| `_register_builtin` not actually idempotent under all reload scenarios (e.g., `importlib.reload` of the formatter registry itself, not just `_builtin_lint`) | Unit 1 test exercises `importlib.reload(_builtin_lint)`; if registry-level reload is later needed, surface as a follow-up. |
| Cross-subcommand `PROTOKIT_FORMAT` envvar collision (compat supports json/junit/sarif; lint D3 supports only human) breaks CI shells that export it globally | R13 error message explicitly notes the cross-subcommand interaction and recommends `env -u PROTOKIT_FORMAT protokit lint ...`. Window closes when D4 lands matching lint formatters. |
| R20a `_LINT_ERROR_CODES` drift — implementation adds a code without updating help text or tests | Tests parametrize over `_LINT_ERROR_CODES` (single source of truth); a help-text drift test asserts every code appears in `--help` output. |
| Cold-import contract regression — a future refactor adds an import to `protokit.schema.cli` that pulls in lint | Unit 5 extends D1's existing CI cold-import smoke step; CI fails on regression. |
| Test fixture descriptor-sets vary across protobuf-library versions | Generate descriptor sets at test time via a session-scoped pytest fixture (`tests/schema/lint/cli/conftest.py`) that compiles checked-in `.proto` files via D1's `compile_protos_to_result` (matches D2's `tests/schema/lint/test_engine.py` / `test_canary_naming.py` pattern). Works on both `has_protoxy=true` and `=false` CI cells via D1's protoc fallback. No checked-in `.descriptor_set` binaries to drift. |
| KD-9 upgrade-safety policy needs an enforcement substrate, not just a docstring | Unit 1's tests pin `BUILTIN_PACKS` membership: `tuple(p.__name__ for p in BUILTIN_PACKS) == ("protokit.schema.lint.rules.naming",)`. Failure message references KD-9 and the CHANGELOG requirement. Membership change requires test update + CHANGELOG entry in the same commit. Hard CI gate replaces the soft norm. |
| D3+D4 sequencing slips, leaving D3 in production with only `human` format for an extended window | Release-note guidance ("D3 = exit-code gating; D4 = machine output"); the cross-subcommand envvar note in R13 makes the limitation visible to CI users; identity-bet implications surfaced in brainstorm pass 2 review for product-owner awareness. |
| Documented `LintRuntimeWarning(category="duplicate_root_file")` rerouting to CLI stderr (R24) leaves no programmatic signal for library consumers who want to detect duplicates | D5 pyproject config or future delivery may revisit; D3 prioritizes Literal preservation. Documented in Scope Boundaries. |

## Deferred Debt Ledger

D3 deliberately defers several items to keep the delivery
right-sized and to preserve D2's locked
`LintRuntimeWarning.category` Literal type. The compound dependency
of multiple deferrals on the same Literal-preservation constraint
means D4 and D5 silently inherit work that needs explicit pricing
into their plans. This ledger makes that visible.

| Deferred item | Target | Revisit trigger | Risk if target slips |
|---------------|--------|-----------------|----------------------|
| R12 `LintRuntimeWarning(category="min_severity_relaxed")` emission | D5 | First non-default-floor caller arrives via pyproject `[tool.protokit.lint]` | D3+D4 ship a free-relaxation knob with only the stderr breadcrumb (added in D3 per the auto-fix); if D5 slips, the Literal-typed warning machinery for library consumers stays absent indefinitely. The breadcrumb mitigates user-visible silent-relaxation but library consumers have no programmatic signal until D5 lands. |
| R17 `--ignore PATH` flag | D5 | Pyproject `[tool.protokit.lint] exclude` globs land — co-design happens together | D6+ rules without any path suppression mechanism create CI noise; users lean on `--profile` or `--no-builtin-rules` (whole-pack opt-out) instead of finer-grained suppression. |
| R21 `LintRuntimeWarning.emit_count_before_exception` field | D4 | Formatter delivery — the only consumer is the human formatter's runtime-warning footer | If D4 slips, the runtime-warning footer renders without per-rule emit-count context. Cosmetic until rule-pack authors hit the gap during debugging. |
| R24 duplicate-filename signal as `LintRuntimeWarning(category="duplicate_root_file")` | D5 or future delivery | A library consumer asks for programmatic duplicate detection (D7 plugin API would surface this need) | D3 ships a CLI stderr line; library consumers cannot detect duplicates without parsing stderr. Acceptable for D3's CLI focus; revisit when programmatic ecosystem matures. |
| `--disable-rule RULE_ID` / `--override-rule-pack` shadowing escape valves | Future delivery (likely D5 or D6) | A user reports "I want to silence one built-in rule, not the whole pack" — concrete need, not speculative | D6+ multi-pack future grows friction: users must reimplement entire packs to override single rules. Workaround `--no-builtin-rules + --rule-pack` documented in R8. |
| `--max-findings-of SEVERITY=N` generalized gating | Future delivery | D6+ ships INFO-severity rules where the asymmetry between WARNING-only `--max-warnings` and ungated INFO matters | Currently INFO is purely advisory; the asymmetry is invisible at D3. |
| README documentation of `protokit lint` | D4 (per current plan) — but consider promoting to D3 | First user complaint about discoverability or first-impression friction | First-time users discover via `--help` only; the README rewrite happens with D4's full machine-format story. The Documentation/Operational Notes section already calls this out as a P2 finding worth revisiting before D3 ship. |

**Compound dependency**: items 1, 4 share the same root cause —
preserving D2's locked `LintRuntimeWarning.category` Literal type
(per KD-8). D5 (or whichever delivery extends the Literal first)
will need to plan for absorbing all three Literal-extension items
together rather than treating them as independent fold-ins. D5's
brainstorm should explicitly price this in.

## Documentation / Operational Notes

- **README**: out of scope for D3 (D4 release will fold lint
  CLI into README documentation alongside the machine formats).
- **CHANGELOG**: D3 entry should explicitly note (a) new
  `protokit lint` subcommand, (b) only `human` format
  available — `json`/`junit`/`sarif` coming in D4, (c) D3
  is fully usable for binary CI gating via exit codes +
  `--quiet`, (d) `BUILTIN_PACKS` is the auto-load surface and
  membership changes are major-version events.
- **Help text**: `protokit lint --help` should be
  copy-edited during impl; verify it renders all flags,
  the seven D3 stable error-prefix codes (eight including
  `formatter-exception`), and a brief description of the
  exit-code ladder.
- **CI**: D1's 4-cell CI matrix is unchanged; the cold-import
  smoke step gains two assertions in Unit 5. The
  `tests/test_static_analysis.py` ratchet auto-covers new
  files via D1's directory globs.
- **Rollout (D3+D4 sequencing commitment)**: D3 SHOULD ship as
  part of a paired user-visible release with D4. The plan
  COMMITS to: D3 lands on `main` first to unblock D4
  implementation, but **the user-visible release announcement
  (CHANGELOG entry + version bump + any social/blog
  communication) waits until D4 is also on `main`**. This
  prevents external CI engineers from forming sticky "not
  ready" first impressions during the human-only window.

  Fallback policy if D4 truly cannot land within 2 weeks of D3
  landing on main: D3 is released independently with explicit
  "preview / not-yet-CI-complete" framing in the release notes,
  and the README section documenting `protokit lint` is
  promoted INTO D3's scope (overriding the Deferred Debt
  Ledger's "README → D4" entry). Independent D3 release without
  the README addition is rejected — too thin a documentation
  surface for the first user-visible lint touchpoint.

  Decision rule: at the moment D3 is ready to merge, check D4
  status. If D4 is implementation-complete and in review →
  paired release. If D4 has substantial implementation
  remaining (>2 weeks of work) → trigger fallback. If D4 is
  abandoned or descoped → treat as a different release-shape
  decision worth its own brainstorm.

## Sources & References

- **Origin document:** `docs/brainstorms/2026-05-04-protokit-lint-delivery-3-cli-requirements.md`
- **D1 brainstorm (cold-import contract origin):** `docs/brainstorms/2026-04-30-protokit-lint-delivery-1-foundation-requirements.md`
- **D2 brainstorm (engine + canary):** `docs/brainstorms/2026-05-02-protokit-lint-delivery-2-engine-requirements.md`
- **D2 plan (structural template):** `docs/plans/2026-05-02-001-feat-protokit-lint-d2-engine-plan.md`
- **Sibling-parity learning:** `docs/solutions/best-practices/audit-wire-format-before-claiming-sibling-parity-2026-05-03.md`
- **Formatter SystemExit security learning:** `docs/solutions/security-issues/formatter-systemexit-exit-code-bypass-2026-04-19.md`
- **TODOS.md D3 entry:** lines 103-114
- **Top-level CLI group:** `src/protokit/cli.py:20-27`
- **Compat CLI structural template:** `src/protokit/schema/cli.py:583-737`
- **Formatter registry:** `src/protokit/formatters/_registry.py:21,128,183,203,222`
- **Eager-load tuple to preserve:** `src/protokit/formatters/__init__.py:60-71`
- **D1 compile entry:** `src/protokit/schema/compile.py`
- **D2 engine API:** `src/protokit/schema/lint/engine.py`
- **D2 profile primitives:** `src/protokit/schema/lint/model.py:499-665`
- **D2 LintRuntimeWarning Literal type:** `src/protokit/schema/lint/model.py:421`
- **D2 canary rule pack:** `src/protokit/schema/lint/rules/naming.py`
- **D2 ce:review residual artifact:** `.context/compound-engineering/ce-review/20260503-001657-4c4467d1/`
