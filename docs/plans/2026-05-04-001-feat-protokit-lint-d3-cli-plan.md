---
title: "feat: protokit-lint Delivery 3 — `protokit lint` CLI subcommand with full-formatter parity"
type: feat
status: active
date: 2026-05-04
deepened: 2026-05-06
origin: docs/brainstorms/2026-05-04-protokit-lint-delivery-3-cli-requirements.md
---

# feat: protokit-lint Delivery 3 — `protokit lint` CLI Subcommand

## Overview

D3 ships the first user-visible lint surface: `protokit lint` as
a top-level click subcommand on `src/protokit/cli.py`, alongside
the existing `diff` and `compat` subcommands. The implementation
mirrors `protokit compat`'s structural template (positional
inputs + `--proto` source mode + `--profile` + `--rule-pack` +
`--format` + `--quiet` + 0/1/2 exit codes) while diverging
deliberately on several axes documented in the origin's
Sibling-Parity Audit.

**D3 absorbs the originally-planned D4 machine-formatter
delivery** (per origin KD-5 revised). All four lint formatters
ship together: `human`, `json`, `junit`, `sarif` — registered via
`_register_builtin` in `src/protokit/formatters/_builtin_lint.py`
under `FormatterKind.LINT_REPORT`. Rationale: shipping
half-formatter parity damaged the CI-auditability identity bet
(see origin "Slicing rationale revisited"); a CI-positioned
linter that fails the obvious `--format=sarif` invocation
contradicts its own identity claim every time a user tries it.

The delivery comprises 6 implementation units. Unit 1 is already
shipped on `main` (commits `c610dae` + `50acd02` + `75b2430`).

1. **[SHIPPED]** Formatter substrate + auto-load list anchor.
2. CLI scaffold + minimal end-to-end pipeline + descriptor-set
   ingestion helper + lint CLI helpers.
3. Rule-loading configurability + profile resolution + R25
   composition stderr provenance (multi-pack-gated) +
   D3-present format-injection hardening (catch-tuple
   widening — co-shipped with `--rule-pack` surface that
   creates the threat).
4a. CI gating + statistics (default-OFF) + lint-side
    formatter wrapper + `run_formatter_safely` refactor +
    `--format=human` path with format-unavailable error
    code.
4b. Machine formatters (`lint_json` / `lint_junit` /
    `lint_sarif`) + format-unavailable test updates + SARIF
    schema validation.
5. D2 residual docstring fold-ins (AC-05/AC-06) + compat
   parallel SystemExit hardening + integration tests + CI
   cold-import gate extension.

**Cold-import contract preserved**: `import protokit.schema` does
NOT transitively load `protokit.schema.lint.cli` or
`protokit.formatters._builtin_lint`. The lint subcommand module
loads only via `protokit.cli` (i.e., on every `protokit ...` CLI
invocation); the import in `protokit/cli.py` triggers the
formatter registration as a side effect at CLI load time. The
contract is preserved by NOT adding `_builtin_lint` to
`formatters/__init__.py`'s eager-load tuple.

## Identity & Positioning

protokit-lint is the linter for proto schemas where (a) compat
checks, lint, and the differ share descriptor-set ingestion +
formatter registry + cold-import discipline (one toolchain that
integrates lint findings, breaking-change reports, and runtime
diffs against the same artifact pipeline); and (b) rule-pack
composition is **explicit and auditable** rather than inherited
from an opaque bundled-default.

What protokit-lint is **not**: a competitor to buf-lint as a
general-purpose proto linter. We do not aim to ship the deepest
catalog of rules, the most pluggable ecosystem, or the broadest
language-server integration. The bet is *integration depth with
the protokit toolkit + CI auditability*, not breadth-of-rules.

This positioning anchors design tradeoffs throughout the
delivery. KD-9's deferred-but-anchored auto-load policy (one
pack today; D6 brainstorm decides promotion policy when concrete
evidence is available), R8's `DuplicateRuleError` (lint refuses
silent shadowing where compat allows it), and R25's multi-pack
provenance line are all expressions of "auditable composition."

## Problem Frame

D2 (commits `26bd312`...`a0b7692` on 2026-05-03) shipped the
`LintEngine` walker, the `@lint_rule` decorator, the canary rule
pack `naming/snake-case-fields`, and `LintProfile.from_pack` +
`compose`. Lint output is reachable today only via library calls;
there is no CLI surface for end users.

Three downstream deliveries (pyproject config, additional rule
packs, plugin API parity) are all gated on D3 — they either need
to read CLI flags, fire from a CLI invocation, or extend a CLI
surface that does not yet exist. D3 closes the dogfood gap and
unblocks the rest of the protokit-lint roadmap.

The origin brainstorm
(`docs/brainstorms/2026-05-04-protokit-lint-delivery-3-cli-requirements.md`)
went through 2 document-review pressure-test passes. All product
decisions needed for planning are resolved: subcommand shape,
input modes, rule-loading semantics, profile resolution, output
formatting, CI gating mechanics, exit-code ladder, stable
error-prefix codes, the D2 residuals folded in or deferred, the
absorbed-D4 scope, and the security framing for D3-present
trust-boundary concerns.

## Requirements Trace

Requirement IDs match the origin document. Items marked
**DEFERRED** were considered for D3 but moved to a later delivery
during brainstorm refinement; they appear in Scope Boundaries as
out-of-scope.

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
  `BUILTIN_PACKS` constant on
  `src/protokit/schema/lint/rules/__init__.py`.
- R7. **DEFERRED to D6** — `--no-builtin-rules` ships with the
  second built-in pack; D3 admitted-zero user value (workaround:
  `--rule-pack mypkg` with a pack that doesn't redeclare built-in
  rule_ids).
- R8. `--rule-pack MODULE` (repeatable, fully-qualified dotted
  module name) additive on top of built-ins. Catch is `except
  SystemExit` (route to `rule-pack-load`) THEN `except Exception`
  (route to `rule-pack-load`). `BaseException`/`KeyboardInterrupt`
  still propagates.
- R9. Loud failure when zero rules load (exit 2,
  `error[lint-no-rules]:`). Fires CLI-side after profile
  resolution, before `engine.run`. No-rules check wins over
  unknown-profile check when both would fire.

**Profile resolution**
- R10. `--profile NAME` (default `"default"`); single-pack case
  (D3 default) calls `LintProfile.from_pack` directly without
  `compose`; multi-pack case (`--rule-pack` adds 1+ packs) lifts
  `compose` back. Skipping compose in single-pack removes
  dead-path test surface.
- R11. Empty resolved profile → exit 2
  (`error[lint-unknown-profile]:`) with stderr listing each
  pack's declared profiles, grouped by pack module name.
  Behavioral spec — implementation chooses access path.
- R12. `--min-severity LEVEL` (info|warning|error) — pure numeric
  override in D3; `LintRuntimeWarning(category="min_severity_relaxed")`
  emission **DEFERRED to next delivery** (pyproject config).
  Stderr breadcrumb fires when override lowers the floor.

**Output and formatting**
- R13. `--format NAME` (default `human`, envvar `PROTOKIT_FORMAT`).
  D3 ships all four formatters: `human`/`json`/`junit`/`sarif`.
  Unsupported values → `KeyError` from registry → exit 2
  (`error[lint-format-unavailable]:`) with available-list message.
- R14. `FormatterKind.LINT_REPORT` enum value added (already
  shipped in U1).
- R15. `_builtin_lint.py` registers all four formatters via
  `_register_builtin` (idempotent + reserves names); NOT in
  eager-load tuple. (U1 shipped `lint_human`; U4b ships
  `lint_json`/`lint_junit`/`lint_sarif`.)
- R16. `--statistics` footer **default OFF** (aligns with
  ruff/eslint/buf-lint convention — opt-in via explicit
  `--statistics` when `--format=human` and not `--quiet`).
  Per-severity counts + filtered + runtime warnings; empty rows
  suppressed when emitted.
- R17. `--ignore PATH` **DEFERRED to next delivery** (pyproject
  config) — co-design with `[tool.protokit.lint] exclude` globs.
- R18. `--quiet` boolean; mutex with non-`human` formats; wins
  unconditionally over `--statistics`.

**CI gating**
- R19. `--max-warnings N` cap on WARNING-severity findings;
  ERROR always exit 1; INFO never gates.
- R20. Exit codes: 0 clean / 1 findings exceed gate / 2
  diagnostics.
- R20a. Stable stderr error-prefix codes via
  `error_exit_with_code(code, message)` helper. **D3 codes (10
  total):** `lint-no-rules`, `lint-unknown-profile`,
  `lint-format-unavailable`, `lint-compile-failed`,
  `lint-formatter-exception`, `lint-bad-input`,
  `lint-pool-conflict`, `lint-missing-imports`,
  `lint-rule-collision`, `lint-rule-pack-load`. The constant
  remains internal-test-aid only; NOT rendered into `--help`
  text.

**D2 ce:review residuals folded in**
- R21. `LintRuntimeWarning.emit_count_before_exception` field
  **DEFERRED to future delivery** (originally D4-target; D4
  absorbed but no concrete consumer is asking for the field).
- R22. `ctx.pool` mutation contract docstring (AC-05).
- R23. `LintRuleError` catch-tuple docstring tightening (AC-06).

**New requirements added during brainstorm refinement**
- R24. `_load_descriptor_sets_to_result` helper with
  dedupe-before-Add ordering, cross-set symbol-collision
  handling, and missing-imports discrimination (TypeError
  message-text routing to `lint-missing-imports` vs
  `lint-pool-conflict`).
- R25. Composition stderr provenance line **gated on
  `len(loaded_packs) >= 2`** (single-pack default emits no
  provenance line — single-pack is not composing anything).
  **Format stability**: provisional in D3 (one canary pack;
  R25 fires only with `--rule-pack` user packs). Stable
  contract from D6 onward when multi-pack composition
  becomes the common case. CI scripts depending on the line
  format before D6 do so at their own risk; release notes
  should mark the format provisional explicitly.

## Scope Boundaries

- Git input modes (`--since`, `--against-base`) — future delivery.
- pyproject `[tool.protokit.lint]` config — next delivery
  (formerly D5; D4 absorbed into D3 per KD-5 revised).
- `--ignore PATH` suppression flag — next delivery (pyproject;
  R17 deferred).
- `--no-builtin-rules` flag (R7) — D6, when second built-in pack
  lands.
- `LintRuntimeWarning(category="min_severity_relaxed")` emission
  (R12 observability) — next delivery.
- `LintRuntimeWarning.emit_count_before_exception` (REL-03,
  R21) — future delivery (no concrete consumer yet).
- `--disable-rule RULE_ID` / `--override-rule-pack` shadowing
  escape valves — future delivery; D6 brainstorm MUST address
  explicitly.
- Additional built-in rule packs beyond `naming` — D6.
- Plugin API parity / `--lint-rule-pack` aliases / compat-flag
  rename — D7 (D7's brainstorm evaluates rename vs. wire-format
  convergence vs. permanent divergence).
- Inline `protokit:ignore` source comments — Phase 3.
- Auto-fix via proto-schema-parser — Phase 3.
- Sub-grouping `protokit lint check`-style nesting (R1).
- "Old vs new" two-input lint mode (R2).
- `--type` / `--dedupe-by-type` (compat-only concepts).
- `--formatter-module` for user formatter packs — D7 (plugin API
  parity).
- `--max-findings-of SEVERITY=N` — when D6+ ships INFO-severity
  rules where the asymmetry matters.
- Help-text rendering of `_LINT_ERROR_CODES` constant — D6, when
  code count grows past ~10 and discoverability pressure
  materializes.
- Holistic plugin-security model (template whitelist/sandbox for
  format-injection) — D6 (carries the TODO(D6) marker forward).
- Auto-load promotion policy commitment (KD-9 revised) — D6
  brainstorm.

## Context & Research

### Relevant Code and Patterns

- **CLI shape template**: `src/protokit/schema/cli.py:583-737`
  (`@main.command("check")`) — argument decorators, click
  options, `PROTOKIT_FORMAT` envvar pattern, `_LEVEL_CHOICES`-style
  use of `click.Choice`. Used as a structural template; D3 does
  NOT subclass or import from this module.
- **Top-level CLI group**: `src/protokit/cli.py:20-27` — adds
  the third subcommand `lint` adjacent to existing `diff` and
  `compat`. The `from protokit.schema.lint.cli import main as
  _lint_command` import is the load-bearing edge for R15's
  cold-import claim (registration happens at `protokit.cli` load
  time).
- **Formatter registry primitives**:
  `src/protokit/formatters/_registry.py` —
  - `FormatterKind` enum at line 21 (U1 added `LINT_REPORT` per
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
    profile at lines 612-613
  - `LintProfile.from_pack(module, profile_name)` walks `RULES`,
    yields `min_severity = WARNING` per the dataclass default at
    line 555
- **Severity types (D2)**:
  `src/protokit/schema/lint/model.py:75-115` —
  `LintSeverity{INFO,WARNING,ERROR}` and `_SEVERITY_RANK`.
- **Rule pack template**:
  `src/protokit/schema/lint/rules/naming.py` — `@lint_rule`
  decorated function + `RULES = (decorated_fn,)` module
  attribute. U1 shipped `BUILTIN_PACKS = (naming,)` in
  `src/protokit/schema/lint/rules/__init__.py`.
- **`LintReport.specs` (U1 inline addition)**:
  `src/protokit/schema/lint/model.py:472-485` —
  `Mapping[str, LintRuleSpec]`, frozen via `MappingProxyType`.
  Engine populates from `self._loaded_specs` at return time.
  Formatters consume `report.specs[finding.rule_id].message_template`
  for message rendering.
- **`LintRuntimeWarning` (frozen Literal type)**:
  `src/protokit/schema/lint/model.py:421` —
  `category: Literal["rule_exception", "unloaded_rule"]`. D3
  preserves the two-value Literal (R12's
  `min_severity_relaxed` deferred to next delivery).
- **Existing `error_exit` helper**:
  `src/protokit/_cli_utils.py:68` writes `Error: {message}` —
  used by compat. D3 introduces `error_exit_with_code` in
  `src/protokit/schema/lint/_cli_utils.py` for lint's stable
  prefix codes (the legacy helper stays untouched).
- **`run_formatter_safely` pattern**:
  `src/protokit/_cli_utils.py:487-549` — wraps formatter calls
  in try/except with four guards (`SystemExit`, generic
  `Exception`, stdout-leak, non-str return) and routes to
  `error_exit`. **D3 refactors this** to accept an
  `error_exit_fn` parameter so lint and compat share the body
  with different prefix semantics (per origin's "Lint-side
  formatter wrapper design" — sharing required, duplication
  needs justification against a 50-line-churn criterion).
- **Compat's broad-catch `Exception` import pattern**:
  `src/protokit/_cli_utils.py:402-413` (`load_formatter_packs`).
  R8 mirrors this for `--rule-pack` imports, with an additional
  `except SystemExit` guard before `except Exception` to catch
  user-pack `sys.exit()` bypass attempts.
- **CI smoke pattern (D1)**: `tests/test_static_analysis.py`
  enforces a path-list ratchet for ruff + mypy. D1's
  `_LINT_PATHS` + `_TYPE_CHECK_PATHS` already use directory
  globs covering `src/protokit/schema/lint` and
  `tests/schema/lint`; D3's new files auto-cover.
- **`.github/workflows/ci.yml` cold-import smoke step**: lines
  83-107 (inline `python -c "..."` block). U5 extends this with
  two new not-in-sys.modules assertions for the new lint
  modules.

### Institutional Learnings

- `docs/solutions/best-practices/audit-wire-format-before-claiming-sibling-parity-2026-05-03.md`
  — applied throughout the brainstorm's Sibling-Parity Audit and
  the U1 ce:review follow-up rename of `_render_human` →
  `lint_human`. R8's wire-format divergence and the rule-shadow
  contract divergence are documented audit-table rows; the audit
  was used during pass-2 review to catch the
  `LintRuntimeWarning.category` Literal-extension issue (R12,
  R24) and the round-2 `lint-rule-pack-load` merge from the
  speculative split.
- `docs/solutions/security-issues/formatter-systemexit-exit-code-bypass-2026-04-19.md`
  — the formatter-side `except SystemExit` fix that
  `run_formatter_safely` already provides. R20a's
  `lint-formatter-exception` code path piggybacks on this
  existing safety net via the refactored shared body. R8's
  `--rule-pack` import path adds a parallel `except SystemExit`
  guard for the same reason: a user pack calling `sys.exit(0)`
  at module load would otherwise produce a false-green CI exit.
- D1 cold-import learning (referenced in
  `docs/brainstorms/2026-04-30-protokit-lint-delivery-1-foundation-requirements.md`):
  the quarantine pattern that R15 preserves. `_builtin_lint`
  NOT in eager-load tuple; lint subcommand module imports it at
  module top, registration runs at `protokit.cli` load time.
- D2 ce:review residuals (R21, R22, R23) folded in per origin
  KD-8: AC-05 (`ctx.pool` mutation contract docstring) and
  AC-06 (`LintRuleError` catch-tuple tightening) ship in U5;
  REL-03 (`emit_count_before_exception`) deferred to future
  delivery.

### External References

None used. The brainstorm grounded all decisions in internal
codebase patterns and D2's locked engine surface; external
research (buf-lint / api-linter / protolint comparisons)
informed the *identity-bet* discussion but did not change
implementation mechanics.

## Key Technical Decisions

- **Use `_register_builtin`, not `register_formatter`, for all
  four lint formatters (R15)**. The internal helper at
  `_registry.py:183-200` is idempotent under module reload (test
  suites, `importlib.reload`, dev REPL) and reserves the format
  names in `_BUILTIN_NAMES` against future user-pack shadow
  attempts. The public `register_formatter` raises
  `FormatterError` on duplicate keys, which would break test
  parametrization that imports the lint CLI module across cases.
- **D3 absorbs D4** (KD-5 revised). All four formatters
  (`lint_human` / `lint_json` / `lint_junit` / `lint_sarif`)
  ship in D3. Originally `lint_human` was D3 and the three
  machine formatters were D4. The brainstorm pressure-test
  pass surfaced that half-formatter parity damaged the
  CI-auditability identity bet. U4's scope grows; the next
  delivery becomes pyproject config.
- **Auto-load via the `BUILTIN_PACKS` tuple constant on
  `rules/__init__.py`** (Q1 resolution + KD-9 anchor). Public,
  discoverable surface that users can introspect at runtime;
  docstring on the constant binds membership changes to a
  major-version event with CHANGELOG entry. Cold-import
  preserved because nothing outside the lint subpackage imports
  `protokit.schema.lint.rules`.
- **Promotion policy decision deferred to D6** (KD-9 revised).
  D3 ships only the structural anchor (`BUILTIN_PACKS` tuple +
  membership-pin test). The policy itself — opt-in vs opt-out
  by default for D6+ packs — waits for concrete user-expectation
  evidence rather than analogy to buf/api-linter.
- **Profile composition uses `LintProfile.compose` only when
  >=1 user pack loaded** (R10 revised). Single-pack case skips
  `compose` entirely and calls `from_pack` directly — `from_pack`
  always returns `min_severity = WARNING` so single-pack
  `compose()` is a no-op identity reduction. The next delivery
  introduces non-default-floor profiles via pyproject config;
  lifting `compose` back to always-on is a one-line change at
  that point.
- **`--min-severity` is a pure numeric override in D3 (R12)**.
  The `LintRuntimeWarning(category="min_severity_relaxed")`
  emission is deferred to the next delivery — extends D2's
  locked `LintRuntimeWarning.category` Literal type. A stderr
  breadcrumb fires in D3 when the user lowers the floor;
  pyproject config delivery introduces the first non-default-floor
  caller.
- **R24's duplicate-filename detection emits a CLI stderr line,
  NOT a `LintRuntimeWarning(category="duplicate_root_file")`**.
  Same Literal-preservation rationale as R12.
- **R24 disambiguates `pool.Add` TypeErrors via message-text
  matching**. Three patterns route to distinct stable codes:
  `has not been loaded` / `couldn't resolve name` →
  `lint-missing-imports`; `duplicate symbol` →
  `lint-pool-conflict`; unmatched → `lint-pool-conflict`
  (preserves legacy behavior). Test obligation: U2 MUST exercise
  actual `descriptor_pool.Add` output for all three observed
  message shapes so a protobuf-version upgrade that changes
  wording becomes a CI failure rather than silent misrouting.
- **`error_exit_with_code` helper lives in
  `src/protokit/schema/lint/_cli_utils.py`, NOT in
  `src/protokit/_cli_utils.py` (R20a)**. Lint and compat helper
  surfaces stay decoupled. The legacy `error_exit` keeps its
  `Error: ` prefix; lint's exit-2 paths route through the new
  helper with `error[lint-{code}]: ` prefixes. CI scripts that
  filter on `error[lint-` get a clean lint-internal failure
  signal.
- **`--rule-pack MODULE` uses fully-qualified dotted Python
  module name (R8)** with `except SystemExit` THEN
  `except Exception` catch ordering. The `SystemExit` guard
  prevents a user pack's `sys.exit(0)` at module load from
  bypassing the helper and producing a false-green CI exit. The
  broad `Exception` catch matches compat's
  `load_formatter_packs` pattern at `_cli_utils.py:402-413`.
  `BaseException`/`KeyboardInterrupt` still propagates.
- **Single `lint-rule-pack-load` error code, not split** (round
  2 of brainstorm pressure-test reversed an earlier split into
  `lint-rule-pack-import` + `lint-rule-pack-shape`).
  Reversibility-favorable: an additive split later is
  non-breaking; a merge-after-split would break CI scripts.
  Sibling-parity with compat's broad-catch + freeform-message
  pattern. Discriminating message body covers diagnostic value.
- **Lint-side formatter wrapper SHARES `run_formatter_safely`'s
  body via an `error_exit_fn` parameter**. The four guards
  (SystemExit, generic Exception, stdout-leak, non-str return)
  are security-relevant; sharing is required so future guard
  additions in compat propagate to lint automatically.
  Duplication is rejected unless the planning-stage refactor
  demonstrably introduces >50 lines of churn in compat OR
  breaks a Phase-1.5b-locked public signature.
- **Integration test cold-import smoke step extension**. D1's
  CI smoke step asserts `import protokit.schema; ...` does not
  load the lint subpackage. U5 extends with two more
  assertions: `import protokit.schema; ...` does not load
  `protokit.schema.lint.cli` OR
  `protokit.formatters._builtin_lint`.
- **D3-present format-injection mitigation: bare `except
  Exception` in `_render_message`**. `LintFinding.params` is
  typed `dict[str, Any]`, so once R8 ships in U3, user packs
  can store objects with custom `__format__` methods that raise
  arbitrary `Exception` subclasses. The Unit 1 7-tuple catch
  is widened to bare `except Exception` in U5. This catches
  crash-recovery vectors only; it does NOT mitigate attribute-
  traversal info disclosure (`{name.__class__.__mro__}`) or OS
  OOM-kill from extreme width specifiers — those are deferred
  to D6's holistic plugin-security model.

## Open Questions

### Resolved During Planning

- **Should `engine.load_rule_pack`'s `DuplicateRuleError` route
  to a stable error-prefix code?** Yes — `lint-rule-collision`
  (Unit 3). Reachable when a `--rule-pack` declares a `rule_id`
  colliding with a built-in or another user pack.
- **Should bad `--rule-pack` module names route to a stable
  code?** Yes — `lint-rule-pack-load` covers all load-time
  failures (ImportError, ModuleNotFoundError, top-level
  Exception, TypeError from `from_pack`/`load_rule_pack`,
  SystemExit). Single code with discriminating message text.
- **Should `--profile` use `click.Choice`?** No — profile names
  are pack-defined and may grow with `--rule-pack`. Use
  `click.STRING` and validate at runtime via R11's behavioral
  introspection.
- **Should `--max-warnings` use `click.IntRange(min=0)`?** Yes —
  negative values are nonsensical; click handles validation
  uniformly with its `Usage: Error:` prefix (acceptable per
  R20a's click-owned-prefix carve-out).
- **Should `_builtin_lint` import live at the top of
  `lint/cli.py` or inside the click callback?** At module top.
  Module-top mirrors compat's pattern at `protokit/cli.py`.
  Inside-callback would force one extra registration check per
  invocation. The cold-import contract is preserved either way.
- **Where do test fixtures for the new CLI tests live?** Under
  `tests/schema/lint/cli/cli_fixtures/` — small `.proto` files.
  A session-scoped pytest fixture in
  `tests/schema/lint/cli/conftest.py` compiles each `.proto` to
  a tmp-path `.descriptor_set` via D1's `compile_protos_to_result`
  (matches D2's at-test-time compile pattern). NO checked-in
  `.descriptor_set` binaries.

### Deferred to Implementation

- Exact stderr message wording for each `error[lint-...]:` code
  — choose during implementation; tests assert the prefix and
  the presence of context strings (e.g., the unknown profile
  name, the conflicting rule_id), not exact phrasing.
- Help-text wording for `protokit lint --help` — generated by
  click decorators; copy-edit during implementation.
- Whether `_load_descriptor_sets_to_result` accepts `Path` or
  `os.PathLike` for input — match the existing
  `load_descriptor_pool` signature in
  `src/protokit/_cli_utils.py`.
- Click parameter ordering — match compat's order where flags
  align (`--profile`, `--format`, `--quiet`, etc.).
- Test parametrization style — match D2's
  `tests/schema/lint/test_engine.py` parametrization style.
- Whether `run_formatter_safely`'s refactor to accept
  `error_exit_fn` keeps the existing keyword-only `name`
  parameter or introduces a new signature shape — implementer
  decides; keep backward-compat for compat callsites.

## Output Structure

D3 creates several new files; the layout mirrors compat's
existing structure under `src/protokit/schema/`:

```text
src/protokit/
├── _cli_utils.py
├── cli.py
├── formatters/
│   ├── _registry.py
│   ├── __init__.py
│   └── _builtin_lint.py
└── schema/
    └── lint/
        ├── cli.py
        ├── _cli_utils.py
        ├── model.py
        └── rules/
            └── __init__.py

tests/
├── test_formatters_registry.py
├── test_builtin_lint_formatter.py
└── schema/lint/
    ├── cli/
    │   ├── conftest.py
    │   ├── test_cli_input_modes.py
    │   ├── test_cli_rule_loading.py
    │   ├── test_cli_profile_resolution.py
    │   ├── test_cli_ci_gating.py
    │   ├── test_cli_error_codes.py
    │   ├── test_cli_integration.py
    │   └── cli_fixtures/
    │       ├── all_kinds.proto
    │       ├── duplicate_root_a.proto
    │       ├── duplicate_root_b.proto
    │       ├── pool_conflict_a.proto
    │       ├── pool_conflict_b.proto
    │       └── missing_imports.proto
    └── test_cold_import_extended.py

.github/workflows/
└── ci.yml
```

Scope declaration showing the expected output shape; per-unit
`**Files:**` sections below are authoritative for what each
unit creates, modifies, or leaves unchanged.

## High-Level Technical Design

> *This illustrates the intended approach and is directional
> guidance for review, not implementation specification. The
> implementing agent should treat it as context, not code to
> reproduce.*

**KD-10 forcing function — three checkable invariants every unit
must preserve:**

1. **Exit-code stability for canary inputs**: `protokit lint
   <descriptor_set>` exits 0 or 1 (never 2 from internal CLI
   errors) for inputs the auto-loaded `naming` canary handles
   cleanly. From U2 onward.
2. **Cold-import smoke remains green**: `import protokit.schema`
   does NOT load `protokit.schema.lint.cli` or
   `protokit.formatters._builtin_lint`. From U1 onward (U1
   already shipped with this preserved).
3. **Subcommand discoverability**: `protokit --help` lists
   `lint` with a non-empty short-help string. From U2 onward.

**Decision matrix for `--format` × `--quiet` × `--statistics`:**

| `--format` | `--quiet` | `--statistics` | Output behavior |
|------------|-----------|----------------|-----------------|
| `human` | absent | absent (default) | Findings only, no footer (R16 default-OFF) |
| `human` | absent | explicit `--statistics` | Findings + statistics footer (empty rows suppressed) |
| `human` | absent | explicit `--no-statistics` | Findings only, no footer (no-op confirmation flag) |
| `human` | `--quiet` | (any) | No output; click warning if `--statistics` also passed; `--quiet` wins |
| `json`/`junit`/`sarif` | absent | (any) | Machine-format output rendered (D3 ships all four formatters per KD-5 revised); statistics footer is human-only |
| `json`/`junit`/`sarif` | `--quiet` | (any) | Click validation error — `--quiet` mutex with non-`human` formats; exit 2 with `Usage:` prefix |

**Module-load + side-effect registration**: `_builtin_lint`
registers all four formatters at MODULE LOAD time of
`schema/lint/cli.py`, which itself is loaded at module load
time of `protokit/cli.py` (the entry point). The cold-import
contract holds because `import protokit.schema` does NOT load
`protokit.cli` and `_builtin_lint` is NOT in the eager-load
tuple at `src/protokit/formatters/__init__.py:60-71`.

**Stable error-prefix code reachability matrix:**

| Code | Unit | Reachable from |
|------|------|----------------|
| `bad-input` | U2 | descriptor-set bytes parse failure (`OSError` / `DecodeError`) |
| `pool-conflict` | U2 | `pool.Add` TypeError matching `duplicate symbol` or unmatched |
| `missing-imports` | U2 | `pool.Add` TypeError matching `has not been loaded` or `couldn't resolve name` |
| `compile-failed` | U2 | `--proto` mode: `result.diagnostics` contains `level == 'error'` entry |
| `no-rules` | U3 | After load: `not engine._loaded_specs` |
| `unknown-profile` | U3 | After load: `not composed_profile.rule_ids` (no-rules wins when both) |
| `rule-collision` | U3 | `engine.load_rule_pack` raises `DuplicateRuleError` |
| `rule-pack-load` | U3 | `--rule-pack` import: `SystemExit` OR `Exception` from importlib OR TypeError from `from_pack`/`load_rule_pack` |
| `format-unavailable` | U4a | `get_formatter` raises `KeyError` (machine-format values exit 2 here until U4b registers them) |
| `formatter-exception` | U4a | Lint-side wrapper catches `SystemExit`/`Exception`/stdout-leak/non-str return from formatter |

## Implementation Units

- [x] **Unit 1: Formatter substrate + auto-load list anchor** *(SHIPPED on `main` per `c610dae`, ce:review follow-ups in `50acd02` + `75b2430`)*

**Goal:** Land the locked-but-static substrate D3 needs before
the CLI scaffold itself: the `FormatterKind.LINT_REPORT` enum
value, an empty-but-importable `_builtin_lint.py` skeleton with
the `lint_human` formatter registered via `_register_builtin`,
and the `BUILTIN_PACKS` constant on `lint/rules/__init__.py`.
No CLI surface yet; this unit was exercised exclusively via
library imports + tests.

**Requirements:** R14, R15 (partial — `lint_human` only;
machine formatters in U4), R6 (anchor only), KD-9 anchor.

**Status:** Shipped. The actual files that landed (including
the inline-discovered `LintReport.specs` addition that was not
in the original plan):

- Modified: `src/protokit/formatters/_registry.py` — added
  `FormatterKind.LINT_REPORT`.
- Created: `src/protokit/formatters/_builtin_lint.py` — public
  `lint_human` callable (sibling-parity rename from the original
  `_render_human` plan via ce:review follow-up `75b2430`);
  registers via `_register_builtin`.
- Modified: `src/protokit/schema/lint/rules/__init__.py` —
  added `BUILTIN_PACKS: tuple[ModuleType, ...] = (naming,)` plus
  KD-9 upgrade-safety docstring.
- Modified: `src/protokit/schema/lint/model.py` — **inline
  addition not in original plan**: added `LintReport.specs:
  Mapping[str, LintRuleSpec]` field, frozen post-construction
  via `MappingProxyType`. Formatters consume this field to
  render `message_template`s without reaching back into engine
  internals.
- Modified: `src/protokit/schema/lint/engine.py` — **inline
  addition not in original plan**: `LintEngine.run` now
  populates `LintReport.specs` from `self._loaded_specs` at
  return time.
- Modified: `src/protokit/formatters/__init__.py` — package
  docstring updated "four report shapes" → "five" (ce:review
  `50acd02`).
- VERIFY-ONLY (preserved): `_builtin_lint` is NOT in the
  eager-load tuple at lines 60-71.
- Created: `tests/schema/lint/test_builtin_packs.py` (6 tests)
- Created: `tests/test_builtin_lint_formatter.py` (14 tests +
  12 added during ce:review follow-ups)
- Modified: `tests/test_formatters_registry.py` — renamed
  `test_all_four_kinds_present` → `test_all_kinds_present`,
  asserts 5-kind set.

The `_builtin_lint.py` module docstring was updated in the
brainstorm round-2 pressure-test pass to reflect D3's
absorption of D4 (no longer says "D4 will extend"). The
catch tuple in `_render_message` is widened in U5 (security
hardening) per the D3-present format-injection threat surface.

---

- [ ] **Unit 2: CLI scaffold + minimal end-to-end pipeline + descriptor-set ingestion helper + lint CLI helpers**

**Goal:** Wire `protokit lint` as a click subcommand on the
top-level CLI group with a **minimal end-to-end happy path**:
both input modes (descriptor-set default + `--proto` source),
the new `_load_descriptor_sets_to_result` helper, the
`error_exit_with_code` + `_LINT_ERROR_CODES` lint CLI helper
module, **and** the runtime call chain that auto-loads
`BUILTIN_PACKS`, derives the default profile via
`LintProfile.from_pack`, runs `engine.run`, and renders via
`lint_human` + `click.echo`. After this unit merges to `main`,
`protokit lint a.descriptor_set` (no flags) produces a real
findings list — per **KD-10 invariants**, `main` carries
defensible output from this unit forward. U3 lifts the
hard-coded defaults into flag-driven configurability; U4a wraps
the call chain in CI gating + format flag handling + adds
machine formatters.

**Requirements:** R1, R2, R3, R4, R20a (helper + initial codes
land here), R24, R6 (default-case auto-load only —
configurability flags arrive in U3).

**Dependencies:** U1 (`FormatterKind.LINT_REPORT` must exist
because `lint/cli.py` imports `_builtin_lint` at module top).

**Files:**
- Modify: `src/protokit/cli.py` (add `from
  protokit.schema.lint.cli import main as _lint_command` +
  `main.add_command(_lint_command, name="lint")`)
- Create: `src/protokit/schema/lint/cli.py` (click subcommand
  scaffold; positional inputs; `--proto`; `--proto-path`/`-I`
  repeatable)
- Create: `src/protokit/schema/lint/_cli_utils.py` containing:
  - `_LINT_ERROR_CODES: tuple[str, ...]` constant (initial set:
    `bad-input`, `pool-conflict`, `missing-imports`,
    `compile-failed`)
  - `error_exit_with_code(code: str, message: str) -> NoReturn`
    helper. Validates `code in _LINT_ERROR_CODES` via
    `assert code in _LINT_ERROR_CODES, f"undeclared lint error code: {code!r}"`
    — `AssertionError` on miss is a hard test failure that
    surfaces implementation drift between the constant and
    call sites. Then writes `error[lint-{code}]: {message}`
    to stderr and calls `sys.exit(2)`. Per round-1 P3
    finding: validation MUST raise rather than silently
    fall through to write an undeclared prefix.
  - `_load_descriptor_sets_to_result(paths: tuple[Path, ...]) ->
    CompileResult` — threads duplicate-filename detection
    into `CompileResult.diagnostics` as `level='info'` entries
    so SARIF/JUnit/JSON consumers in descriptor-set mode see
    them uniformly (per round-1 P2 finding: original design
    routed duplicates to stderr-only side-channel, which
    machine-format CI consumers couldn't see — contradicting
    the CI-auditability identity bet). The helper builds a
    `tuple[LintCompileDiagnostic, ...]` for any duplicates
    encountered and passes it to the returned `CompileResult`.
    No `quiet` parameter on the helper; the CLI callback
    decides whether to render diagnostics based on `--quiet`
    in the formatter call (handled by U4a's pipeline).
  - All `error_exit_with_code` paths in this helper that
    interpolate `str(exc)` (`bad-input`, `pool-conflict`,
    `missing-imports`) wrap the exception via
    `_scrub_exc_message(exc)` from
    `src/protokit/_cli_utils.py:463-484` to suppress OSError
    filename leakage onto stderr (per round-1 P2 finding).
- Test: `tests/schema/lint/cli/test_cli_input_modes.py` (new)
- Test: `tests/schema/lint/test_cold_import_extended.py` (new
  — pytest-runnable parallel to the CI-YAML smoke step; gives
  local feedback before push)
- Test fixtures (using D2's at-test-time compile pattern, NOT
  checked-in `.descriptor_set` binaries — matches
  `tests/schema/lint/test_engine.py` /
  `test_canary_naming.py`):
  - `tests/schema/lint/cli/cli_fixtures/all_kinds.proto`
  - `tests/schema/lint/cli/cli_fixtures/duplicate_root_a.proto`
    + `duplicate_root_b.proto` (same `package` + `message`
    names, identical content for the duplicate-filename test)
  - `tests/schema/lint/cli/cli_fixtures/pool_conflict_a.proto`
    + `pool_conflict_b.proto` (different `package`-qualified
    file names but a colliding message FQN, for the cross-set
    symbol-collision test)
  - `tests/schema/lint/cli/cli_fixtures/missing_imports.proto`
    (references `google.protobuf.Timestamp` without
    `--include_imports`, for the missing-imports test)
  - A session-scoped pytest fixture in
    `tests/schema/lint/cli/conftest.py` compiles each `.proto`
    to a tmp-path `.descriptor_set` via D1's
    `compile_protos_to_result` (works on both
    `has_protoxy=true` and `=false` CI cells)

**Approach:**
- `lint/cli.py` defines a click `@click.command()` (NOT
  `@click.group()` — single command per R1) wrapped by a shim
  function exported as `main` to mirror compat's `from
  protokit.schema.cli import main as _compat_command` pattern.
- `_load_descriptor_sets_to_result(paths)` algorithm:
  - Initialize fresh `DescriptorPool`, `seen_names: set[str]`,
    `duplicates: list[LintCompileDiagnostic]`,
    `root_files: list[str]`.
  - Iterate `paths` in command-line argv order; within each
    path, iterate `fds.file` in protobuf parse order.
  - For each `fd`: if `fd.name in seen_names`, append a
    `LintCompileDiagnostic(level='info',
    category='same_basename_collision', message=...)` to
    `duplicates` and skip; else add to `seen_names`, call
    `pool.Add(fd)`. On `TypeError`: inspect message text for
    `has not been loaded` / `couldn't resolve name` (route to
    `error_exit_with_code("missing-imports",
    f"{path}: {_scrub_exc_message(exc)}")`) vs
    `duplicate symbol` (route to
    `error_exit_with_code("pool-conflict",
    f"{path}: {_scrub_exc_message(exc)}")`); unmatched falls
    through to `pool-conflict` to preserve legacy behavior.
    Append `fd.name` to `root_files`.
  - On per-path read or parse failure: route directly to
    `error_exit_with_code("bad-input",
    f"{path}: {_scrub_exc_message(exc)}")`.
  - Return `CompileResult(pool=pool, root_files=tuple(root_files),
    diagnostics=tuple(duplicates))` — duplicate signals flow
    through `CompileResult.diagnostics` so all formatters see
    them uniformly. Click validation (`Path(exists=True,
    dir_okay=False)`) covers path-level failures BEFORE the
    callback fires; `bad-input` is reserved for bytes-level
    parse failures (per round-1 P3 finding narrowing
    `bad-input` scope).
- `--proto` mode delegates to D1's
  `compile_protos_to_result(paths, proto_paths)` directly. Its
  diagnostics drive the `lint-compile-failed` exit-2 path —
  predicate: `any(d.level == 'error' for d in
  result.diagnostics)`. Successful compile via protoxy→protoc
  fallback emits an `info`-level diagnostic that must NOT
  trigger this code.
- **Minimal end-to-end pipeline (KD-10 anchor)**: after
  computing the `CompileResult` from inputs, the click callback
  runs:

  ```text
  engine = LintEngine()
  for pack in BUILTIN_PACKS:
      engine.load_rule_pack(pack)
  profile = LintProfile.from_pack(BUILTIN_PACKS[0], "default")
  report = engine.run(compile_result, profile=profile)
  ctx = FormatterContext(subcommand="lint")
  output = lint_human(report, ctx)
  click.echo(output)
  ```

  Hard-coded `"default"` profile + hard-coded `BUILTIN_PACKS[0]`
  iteration is the U2 shape. U3 introduces `--rule-pack`,
  `--profile NAME`, and `--min-severity` by lifting these
  hard-coded values into click-flag-driven equivalents while
  preserving the zero-flag behavior. Exit code is 0 here
  unconditionally; U4a wires the R20 ladder.
- Cold-import test: parametrize over a list of "must NOT be in
  sys.modules after `import protokit.schema`" — extends D1's
  baseline with `protokit.schema.lint.cli` and
  `protokit.formatters._builtin_lint`.

**Patterns to follow:**
- `src/protokit/schema/cli.py:583-680` — `@click.argument` /
  `@click.option` decorator stack and signature shape.
- `src/protokit/_cli_utils.py:load_descriptor_pool` — single-path
  descriptor-set loader; D3's helper extends to multi-path.
- D1's CI cold-import smoke test (referenced in
  `docs/brainstorms/2026-04-30-protokit-lint-delivery-1-foundation-requirements.md`).

**Test scenarios:**
- Happy path: `protokit lint <fixture>.descriptor_set` (built
  from a fixture with no naming violations) invokes the click
  callback end-to-end (auto-load + `engine.run` + `lint_human`
  + `click.echo`), prints the formatter's "no findings" output,
  and returns exit 0. **Demonstrates KD-10's minimal-runnable
  contract.**
- Happy path: `protokit lint <fixture>.descriptor_set` (built
  from a fixture with two `camelCase` field name violations)
  prints two findings via `lint_human`, exit 0 (R20 gating is
  U4's job; U2's exit code is just "did the pipeline run?").
- Happy path: `protokit lint --proto <fixture>.proto -I <dir>`
  compiles the source via `compile_protos_to_result`, runs the
  pipeline end-to-end.
- Happy path: multi-path descriptor-set `protokit lint
  a.descriptor_set b.descriptor_set` merges pools and
  accumulates `root_files` from both inputs in argv-order,
  deduplicating by `fd.name` (first occurrence wins).
- Edge case: zero positional arguments → click usage error
  (exit 2, click-owned prefix `Usage:` / `Error:`).
- Edge case: `protokit lint --proto` with no positional
  arguments → click usage error.
- Edge case: descriptor-set with overlapping `fd.name` across
  inputs → first-occurrence-wins; helper emits stderr line
  `protokit lint: deduplicated 1 duplicate file path(s) across
  input sets` (suppressed under `--quiet` in U4).
- Edge case: `--proto` mode with a `.proto` that has only a
  successful protoxy→protoc fallback (info-level diagnostic
  only, no error-level) → pipeline runs to completion, exit 0.
  Diagnostic appears in `lint_human` output.
- Error path: malformed bytes (non-FileDescriptorSet) → exit 2
  via `error[lint-bad-input]:`.
- Error path: cross-set symbol collision (different `fd.name`,
  same message FQN — exercised by `pool_conflict_a.proto` +
  `pool_conflict_b.proto` fixtures) → `pool.Add` raises
  `TypeError` with `duplicate symbol` text → helper exits 2
  via `error[lint-pool-conflict]:`.
- Error path: missing transitive imports (descriptor_set built
  WITHOUT `--include_imports` referencing
  `google.protobuf.Timestamp` — exercised by
  `missing_imports.proto` fixture) → `pool.Add` raises
  `TypeError` with `has not been loaded` text → helper exits 2
  via `error[lint-missing-imports]:` with stderr message
  naming the `protoc --include_imports` requirement.
- Error path: dangling symbol reference (descriptor_set
  references `acme.UnknownType` not present in any included
  file) → `pool.Add` raises `TypeError` with `couldn't resolve
  name` text → helper exits 2 via `error[lint-missing-imports]:`.
- Error path: `--proto` mode with a `.proto` that has a syntax
  error → `compile_protos_to_result` populates `diagnostics`
  with at least one `level == 'error'` entry; helper exits 2
  via `error[lint-compile-failed]:`.
- Integration: cold-import smoke — `import protokit.schema; ...`
  does NOT load `protokit.schema.lint.cli` or
  `protokit.formatters._builtin_lint`; `import protokit.cli;
  ...` DOES load both.
- Integration: `protokit diff <args>` and `protokit compat
  <args>` continue to work unchanged (regression check that
  the third subcommand registration does not break the other
  two).
- Integration: `protokit --help` lists `lint` with a non-empty
  short-help string. **KD-10 invariant 3.**
- Test obligation per Key Technical Decisions: U2's tests MUST
  exercise actual `descriptor_pool.Add` output for all three
  observed message shapes (loaded-dependency-missing,
  resolve-name-failure, duplicate-symbol) so a
  protobuf-version upgrade that changes wording becomes a CI
  failure rather than silent misrouting.

**Verification:**
- `protokit lint --help` renders without errors and lists
  positional inputs + `--proto` + `--proto-path`.
- All U2 tests pass; existing diff/compat CLI tests still
  pass.
- KD-10 invariants 1, 2, 3 all hold after this unit lands.
- **Static analysis ratchet covers new files**: confirm
  `tests/test_static_analysis.py`'s `_LINT_PATHS` and
  `_TYPE_CHECK_PATHS` use recursive directory globs that
  cover the new `tests/schema/lint/cli/` subdirectory and
  the new top-level `tests/test_cold_import_extended.py`. If
  patterns are single-level, extend them so new CLI tests
  do not bypass mypy strict-mode coverage.

---

- [ ] **Unit 3: Rule-loading configurability + profile resolution + R25 provenance + D3-present format-injection hardening**

**Goal:** Lift U2's hard-coded auto-load + default-profile
machinery into the flag-driven version. Adds `--rule-pack`
(repeatable), `--profile NAME`, `--min-severity LEVEL`. Adds
the loud-failure paths: R9 zero-rules, R11 unknown-profile
(with behavioral introspection of each pack's declared
profiles, grouped by pack module name). Adds R25 composition
stderr provenance line **gated on `len(loaded_packs) >= 2`**
(single-pack default emits no provenance line). **Co-ships
the D3-present format-injection hardening** (catch-tuple
widening in `_render_message`) alongside the `--rule-pack`
surface that creates the threat — per round-1 plan-review
P1 finding, hardening must land with the surface, not in a
later unit. **Co-ships the stderr load-banner** for
`--rule-pack` invocations so the trust delegation is observable
(per round-1 P1 finding on `--rule-pack` security mitigation).
Preserves U2's zero-flag-invocation behavior per KD-10.
**R7 `--no-builtin-rules` DEFERRED to D6**.

**Requirements:** R6 (full configurability — U2 covered the
default case only), R8, R9, R10, R11, R12, R25.

**Dependencies:** U2 (CLI scaffold must exist).

**Files:**
- Modify: `src/protokit/schema/lint/cli.py` (add `--rule-pack`,
  `--profile`, `--min-severity` click options; add rule-loading
  + profile-resolution logic; emit R25 provenance line gated on
  `len(loaded_packs) >= 2`; emit `--rule-pack` stderr
  load-banner advisory line on every invocation; add an
  in-source `# TODO(next-delivery)` comment at the
  single-pack/multi-pack profile branch noting the
  compose-lift trigger when pyproject introduces
  non-default-floor profiles)
- Modify: `src/protokit/schema/lint/_cli_utils.py` (extend
  `_LINT_ERROR_CODES` with `no-rules`, `unknown-profile`,
  `rule-collision`, `rule-pack-load`; add helpers for
  pack-loading and profile composition that share data
  structures between R11 and R25; apply `_scrub_exc_message`
  to all `error_exit_with_code` paths that interpolate
  `str(exc)` from filesystem-bearing exceptions)
- Modify: `src/protokit/formatters/_builtin_lint.py` —
  **D3-present security hardening (moved from U5 per P1
  finding)**: the catch tuple in `_render_message` was
  widened from the original 5-tuple to bare `except
  Exception` during the brainstorm round-2 pressure-test
  pass (already on working tree; lands with this unit's
  commit because `--rule-pack` is the surface that creates
  the user-pack-template threat). `LintFinding.params` is
  typed `dict[str, Any]`, so once `--rule-pack` ships in
  this unit, user packs can store objects with custom
  `__format__` methods that raise arbitrary `Exception`
  subclasses (`OverflowError`, `ZeroDivisionError`, etc.).
  The bare catch ensures buggy or malicious user-pack
  templates produce a graceful rule_id fallback rather than
  crashing the formatter mid-render and dropping every
  subsequent finding. `BaseException` /
  `KeyboardInterrupt` / `SystemExit` are NOT caught — those
  propagate normally so users can cancel with Ctrl-C and the
  `run_formatter_safely` outer SystemExit guard catches
  `sys.exit()` bypass attempts. The widening is
  defense-in-depth against crash-recovery only; it does NOT
  mitigate attribute-traversal info disclosure
  (`{name.__class__.__mro__}`) or OS OOM-kill from extreme
  width specifiers — those defer to D6's holistic
  plugin-security model. Comment block updated to honestly
  acknowledge what the catch covers and doesn't cover, and
  to document `os._exit()` as a known-unmitigatable C-level
  termination path that bypasses Python exception handling
  entirely.
- Test: `tests/schema/lint/cli/test_cli_rule_loading.py` (new)
- Test: `tests/schema/lint/cli/test_cli_profile_resolution.py`
  (new)
- Modify: `tests/test_builtin_lint_formatter.py` — add tests
  for the new catch behavior covering exception types beyond
  the previous 5-tuple (synthetic templates with custom
  `__format__` raising `OverflowError`, `ZeroDivisionError`,
  `StopIteration`); verify `KeyboardInterrupt` and `SystemExit`
  still propagate (NOT caught by bare `except Exception`).

**Approach:**
- Auto-load: iterate `protokit.schema.lint.rules.BUILTIN_PACKS`
  unconditionally (no `--no-builtin-rules` opt-out in D3); for
  each module call `engine.load_rule_pack(module)`.
- **Stderr load-banner for `--rule-pack`**: on every
  `--rule-pack` value processed (before the import call),
  emit a stderr advisory line via
  `click.echo(..., err=True)`:
  `protokit lint: loading user-supplied rule pack '{value}'
  (executes arbitrary Python from the named module)`.
  Suppressed under `--quiet`. Converts the trust delegation
  into observable surface; defensible posture for the
  identity-bet "audit" claim.
- `--rule-pack`: for each value, call
  `importlib.import_module(value)` inside a guard. The
  message body uses a stable `kind={import,shape}:` token
  at a fixed position so CI scripts can branch on the
  failure mode without parsing freeform text:

  ```text
  try:
      module = importlib.import_module(value)
  except SystemExit as exc:
      error_exit_with_code("rule-pack-load",
          f"kind=import: pack {value!r} called sys.exit({exc.code!r}) at import time")
  except Exception as exc:
      error_exit_with_code("rule-pack-load",
          f"kind=import: failed to import pack {value!r}: "
          f"{type(exc).__name__}: {_scrub_exc_message(exc)}")
  ```

  The `SystemExit` guard is FIRST (catches `BaseException`
  subclass before the broad `Exception` catch can miss it).
  `BaseException`/`KeyboardInterrupt` still propagates.
  **`os._exit()` is NOT caught** — it terminates the process
  at the C level before any Python exception fires; document
  this as a known-unmitigatable vector in the plugin contract.
  `_scrub_exc_message` (from `src/protokit/_cli_utils.py:463-484`)
  scrubs OSError filename leakage from message bodies.
- `engine.load_rule_pack(module)`: catches `DuplicateRuleError`
  → `error_exit_with_code("rule-collision", ...)`. Catches
  `TypeError` (raised by `from_pack`/`load_rule_pack` when
  `RULES` has wrong wire format — most commonly user wrote
  compat's `RULES = ((rule_id, fn), ...)`) → routes to the
  same `rule-pack-load` code as import failures, with the
  message body using the `kind=shape:` token at a fixed
  position: `kind=shape: pack 'acme.lint_rules' has wrong
  wire format: ('snake_case', <function fn>) is not
  @lint_rule-decorated. lint expects RULES = (decorated_fn,
  ...); compat's RULES = ((rule_id, fn), ...) is incompatible.
  See audit-wire-format-before-claiming-sibling-parity-2026-05-03.`
  Stable `kind={import,shape}:` token discrimination lets CI
  scripts branch on failure mode without parsing freeform
  message text.
- Profile resolution per R10 revised:
  - **Single-pack case** (D3 default — only `BUILTIN_PACKS[0]`
    loaded): `profile = LintProfile.from_pack(pack, name)`.
    No `compose` call.
  - **Multi-pack case** (`--rule-pack` adds 1+ packs): build
    per-pack profiles via `from_pack`, call
    `LintProfile.compose(*per_pack_profiles)`.
- R11 introspection (behavioral spec — implementation chooses
  access path): build a CLI-side data structure
  `pack_to_active_rules: dict[str, list[str]]` by iterating
  each loaded pack's `RULES` and intersecting with the resolved
  `profile.rule_ids`. Reuse this dict for both R11
  (unknown-profile message lists declared profiles per pack)
  and R25 (provenance line lists active rule_ids per pack).
- R9 zero-rules check: after rule loading + profile resolution
  succeed, check predicates in order:
  - `not engine._loaded_specs` → `error_exit_with_code("no-rules",
    "no rule packs loaded; use --rule-pack to load a pack")`.
  - `not composed_profile.rule_ids` →
    `error_exit_with_code("unknown-profile", f"profile {name!r}
    matched 0 rules across loaded packs. Declared profiles per
    pack:\n{pack_profiles_summary}")`.
  - When BOTH would fire, no-rules wins (the user can't
    meaningfully fix profile selection without rules).
- `--min-severity LEVEL`: `click.Choice(["info", "warning",
  "error"], case_sensitive=False)`. If unset, use composed
  profile's `min_severity`. If set, override via
  `dataclasses.replace(composed_profile, min_severity=...)`.

  *Relaxation breadcrumb*: when `--min-severity` is passed AND
  the resulting floor is more lenient than the composed floor
  (i.e., user passed `info` or `warning` against a composed
  floor of `warning` or `error`), emit a stderr line analogous
  to R25:
  `protokit lint: --min-severity={user-level} relaxes profile
  floor from {composed-level} to {effective-level}`.
  Suppressed under `--quiet` (wired in U4). Per origin R12,
  the `LintRuntimeWarning(category="min_severity_relaxed")`
  emission is deferred to the next delivery.
- R25 provenance: after rule loading + profile resolution
  succeed (i.e., R9 and R11 short-circuits did NOT fire),
  before `engine.run`, **only when `len(loaded_packs) >= 2`**,
  format the line as
  `protokit lint: profile '{name}' from
  {pack1}=[{rule_ids1}]; {pack2}=[{rule_ids2}]`
  using full `module.__name__`s and verbatim rule_ids.
  Suppressed under `--quiet`; never written to `stdout`.
  R25 does NOT fire in the D3-default single-pack case.

**Patterns to follow:**
- `LintProfile.compose` short-circuit behavior at
  `src/protokit/schema/lint/model.py:612-613` (returns
  `profiles[0]` unchanged for single-arg case).
- Compat's runtime rule-pack loading at
  `src/protokit/schema/cli.py:_load_rule_packs` — mirror the
  importlib pattern but adapted for lint's wire format
  (decorated callables, NOT `(rule_id, fn)` tuples).
- Compat's broad-catch + freeform-message pattern at
  `src/protokit/_cli_utils.py:402-413`
  (`load_formatter_packs`).
- `run_formatter_safely`'s `except SystemExit as exc` guard at
  `src/protokit/_cli_utils.py:521-529` — the same pattern
  applied to the `--rule-pack` import.

**Test scenarios:**
- Happy path: bare `protokit lint <fixture>.descriptor_set`
  auto-loads `BUILTIN_PACKS` and runs `naming/snake-case-fields`.
  Zero-flag behavior unchanged from U2.
- Happy path: `--profile default` is the default value; same
  behavior as no flag.
- Happy path: `--rule-pack=test_pack_a` loads on top of
  built-ins; R25 line fires with both packs (multi-pack case).
- Happy path: `--rule-pack=pack_a --rule-pack=pack_b` loads
  both on top of built-ins; R25 line shows all 3 packs.
- Happy path: R25 provenance line fires only when
  `len(loaded_packs) >= 2`; single-pack default produces no
  provenance line. Suppressed under `--quiet` (U4) regardless
  of pack count.
- Happy path: `--min-severity error` raises composed
  WARNING-default to ERROR; only ERROR-severity findings
  surface in `report.findings`. No relaxation breadcrumb
  emitted (override is more strict).
- Happy path: `--min-severity info` against the WARNING
  composed default emits the relaxation breadcrumb on stderr;
  suppressed under `--quiet` (U4).
- Edge case: `--profile default` resolves to non-empty
  `rule_ids` because canary declares `profiles=("default",)`.
- Edge case: empty `RULES` tuple in a user pack with no
  built-ins loaded → R9 loud failure
  (`error[lint-no-rules]:`). Note: the path requires `--rule-pack`
  with a pack that has empty RULES; the always-on built-ins
  prevent the simpler "no flags" zero-rules path until D6 ships
  `--no-builtin-rules`.
- Edge case: `--rule-pack=test_pack_strict_only --profile default`
  where `test_pack_strict_only` declares only
  `profiles=("strict",)` AND built-in canary declares
  `("default",)` → composed profile DOES match (canary fires,
  user pack contributes nothing). Confirms compose semantics.
- Edge case: `--rule-pack=test_pack_strict_only --profile strict`
  → composed profile matches user pack only; canary contributes
  nothing.
- Edge case: `--rule-pack=test_pack_strict_only --profile typo`
  → R11 loud failure with stderr listing the declared profiles
  for both built-in and user pack.
- Edge case: `--min-severity warning` (default) doesn't change
  behavior (composed default is already WARNING).
- Edge case: same `module.__name__` passed twice via
  `--rule-pack` → engine idempotency-guard short-circuits;
  R25 line lists the pack once.
- Error path: `--rule-pack=does.not.exist` →
  `ModuleNotFoundError` → exit 2 via `lint-rule-pack-load`
  prefix; message names the missing module.
- Error path: `--rule-pack=test_pack_compat_format` exposing
  `RULES = (("snake_case_fields", fn),)` → `TypeError` from
  `LintProfile.from_pack` / `LintEngine.load_rule_pack` →
  exit 2 via the same `lint-rule-pack-load` prefix; message
  body explicitly names the wire-format mismatch and
  references the audit-wire-format learning.
- Error path: `--rule-pack=test_pack_module_body_raises` whose
  top-level body executes `1/0` → `ZeroDivisionError` caught
  by the broad `except Exception` → exit 2 via
  `lint-rule-pack-load` prefix; message names the import-time
  exception type and the offending module path.
- Error path: `--rule-pack=test_pack_module_body_sys_exits`
  whose top-level body executes `sys.exit(0)` → `SystemExit(0)`
  caught by the FIRST `except SystemExit` guard → exit 2 via
  `lint-rule-pack-load` prefix; message names the user-supplied
  exit code. **Critical: prevents false-green CI exit when a
  user pack accidentally calls sys.exit(0).**
- Error path: `--rule-pack=test_pack_collision` declaring
  `naming/snake-case-fields` (colliding with built-in) →
  `DuplicateRuleError` from `engine.load_rule_pack` → exit 2
  via `lint-rule-collision` prefix.
- Error path: `--profile typo` → R11 loud failure; stderr
  message includes the typo'd name + every loaded pack's
  declared profiles, grouped by pack module name.
- Error path: `--min-severity nope` → click validation error
  (`Usage:` prefix, click-owned, exit 2).
- Integration: R25 line emits to stderr (not stdout); under
  `--quiet` (U4) no R25 line emits; the mutually-exclusive
  interaction with `--format json` (U4a/U4b territory) does not
  break R25 emission ordering — provenance fires before
  format dispatch.
- Integration: KD-10 invariant 1 holds — `protokit lint
  <descriptor_set>` exits 0/1 only (never 2 from internal CLI
  errors) for canary-clean inputs.

**Verification:**
- All scenarios above pass.
- `protokit lint --help` renders updated help text including
  the new flags.
- Existing diff/compat CLI tests still pass.
- KD-10 invariants 1, 2, 3 all hold.

---

- [ ] **Unit 4a: CI gating + lint-side formatter wrapper + `run_formatter_safely` refactor**

**Goal:** Land the CI gating mechanics (`--max-warnings`,
`--statistics` default-OFF, `--quiet`), the exit-code ladder
(R20), the `--format` flag with the format-unavailable error
path (resolving `human` only at this unit's ship; machine
formatters land in U4b), and the lint-side formatter wrapper
that produces `error[lint-formatter-exception]:` stable
prefix. Refactors `protokit._cli_utils.run_formatter_safely`
to accept an `error_exit_fn` parameter so lint and compat
share the body. **Split rationale (per round-1 plan-review
pressure-test pass)**: U4 originally bundled CI gating +
machine formatters + wrapper refactor into one unit. The
refactor touches a Phase-1.5b-locked compat helper; the
machine formatters are purely additive registrations. Splitting
isolates compat-regression risk in U4a and lets U4b ship as
near-mechanical formatter additions. Both intermediate states
honor KD-10 invariants. Release boundary stays D3 = U4b
complete; identity-bet rationale (KD-5) preserved.

**Requirements:** R13 (format-unavailable error path; machine
formats resolve KeyError → exit 2 until U4b adds them),
R16 (default-OFF), R18, R19, R20, R20a (extends
`_LINT_ERROR_CODES` with `format-unavailable`,
`formatter-exception`).

**Dependencies:** U3 (rule loading + profile resolution +
`error_exit_with_code` helper all already exist; this unit
extends them).

**Files:**
- Modify: `src/protokit/_cli_utils.py` —
  **`run_formatter_safely` refactor**: add `error_exit_fn`
  parameter (kw-only, default `error_exit` for compat
  back-compat) so the body can be shared between compat
  (legacy `error_exit` prefix) and lint (new
  `error_exit_with_code("formatter-exception", ...)` prefix).
  All four guards (SystemExit, generic Exception, stdout-leak,
  non-str return) stay in the shared body. Compat's existing
  callsites are unchanged at the source-code level (default
  parameter value preserves behavior). Existing
  `_scrub_exc_message` invocation on the `except Exception`
  branch is preserved by the refactor — verified by compat's
  test suite staying green.
- Modify: `src/protokit/schema/lint/_cli_utils.py` (extend
  `_LINT_ERROR_CODES` with `format-unavailable` and
  `formatter-exception`; constant remains internal-only, NOT
  rendered into `--help`; add a thin
  `_run_lint_formatter_safely` wrapper that calls the
  refactored `run_formatter_safely` with
  `error_exit_fn=lambda msg: error_exit_with_code(
  "formatter-exception", msg)`)
- Modify: `src/protokit/schema/lint/cli.py` (add `--format`,
  `--max-warnings`, `--statistics`/`--no-statistics`,
  `--quiet` click options; wire `_run_lint_formatter_safely`
  for the formatter call; compute exit code per R20)
- Test: `tests/schema/lint/cli/test_cli_ci_gating.py` (new)
- Test: `tests/schema/lint/cli/test_cli_error_codes.py` (new
  — covers 9 of the 10 codes; SARIF/JUnit/JSON-specific
  format-unavailable scenarios verify they're NOT in the
  available list at this unit's ship; U4b updates that
  expectation when machine formatters register)

**Execution note:** Test-first for the `error_exit_with_code`
helper extension and the exit-code ladder — both are
pure-function-shaped surfaces that benefit from red-green
discipline. The `--statistics` footer rendering can be
implemented test-with rather than test-first. The
`run_formatter_safely` refactor should be verified test-first
against compat's existing test suite to ensure backward
compatibility. The Phase-1.5b lock on `run_formatter_safely`
permits additive kw-only parameters with default values
(non-breaking signature evolution); see compat's
Phase-1.5b lock document under
`docs/solutions/best-practices/` (or equivalent) before
making the change. If a Phase-1.5b lock document does not
exist with explicit additive-parameter language, the
refactor's compat-impact analysis should be discharged via
explicit note in the PR description.

**Approach:**
- By this unit's end, `_LINT_ERROR_CODES` contains the full
  D3 set (10 codes): `("no-rules", "unknown-profile",
  "format-unavailable", "compile-failed",
  "formatter-exception", "bad-input", "pool-conflict",
  "missing-imports", "rule-collision", "rule-pack-load")`.
  Order is stable and matches the R20a list. (U4b adds
  registration for the machine formatters but does not
  extend the constant.)
- `--format`: `click.option('--format', envvar='PROTOKIT_FORMAT',
  default='human', type=click.STRING)` — uses click's built-in
  envvar mechanism for parity with compat. Resolution:
  `get_formatter(value, FormatterKind.LINT_REPORT)`. `KeyError`
  → `error_exit_with_code("format-unavailable", ...)` with the
  available list rendered via `list_formatters(FormatterKind.LINT_REPORT)`.
  At U4a's ship: only `lint_human` resolves; `--format=json`,
  `--format=junit`, `--format=sarif` exit 2 via
  `lint-format-unavailable`. U4b extends the registry with
  the three machine formatters; the format-unavailable test
  expectation updates accordingly when U4b lands.
- `--max-warnings`: `click.IntRange(min=0)`, default `None`.
  When set, count WARNING-severity findings in
  `report.findings` post-min-severity-filter; exit 1 if
  count > N.
- `--statistics`: `click.option("--statistics/--no-statistics",
  default=None)`. Click's slash-syntax produces a true
  three-state boolean (None=default-OFF, True=explicit
  `--statistics`, False=explicit `--no-statistics`). Default
  OFF in human format unless `--statistics`. Footer rendering:
  - Per-severity counts (computed by iterating
    `report.findings`)
  - Filtered count (from `LintReport.filtered_count`)
  - Runtime warning count (from
    `len(LintReport.runtime_warnings)`)
  - Empty rows (zero counts) suppressed.
  Footer is human-only; non-`human` formats embed counts in
  their structured payloads natively (in U4b).
- `--quiet`: `click.option(is_flag=True, default=False)`.
  Mutex with non-`human` format → click validation error
  (`Usage:` prefix; emitted via `click.echo(..., err=True)` —
  click has no native "warning" primitive). Mutex-soft with
  `--statistics` → stderr advisory line via
  `click.echo(..., err=True)`; `--quiet` wins.
- Exit code logic per R20: 0 (clean), 1 (ERROR present OR
  WARNING > max-warnings), 2 (any of the
  `error_exit_with_code` paths or formatter exception).
- `_run_lint_formatter_safely` wraps the refactored
  `run_formatter_safely`:

  ```text
  def _run_lint_formatter_safely(fn, report, ctx, *, name):
      def lint_error_exit(msg: str):
          error_exit_with_code("formatter-exception", msg)
      return run_formatter_safely(
          fn, report, ctx, name=name,
          error_exit_fn=lint_error_exit,
      )
  ```

**Patterns to follow:**
- `protokit._cli_utils.run_formatter_safely` pre-refactor —
  the four guards become the shared body.
- `protokit.schema.cli._resolve_common_flags` — example of
  bundling `--quiet` + `--format` validation interaction.
- Compat's `Phase-1.5b` lock semantics for additive kw-only
  parameter changes — verify before signature change lands.

**Test scenarios:**
- Happy path: `protokit lint --max-warnings 0
  <clean>.descriptor_set` exits 0 (no findings).
- Happy path: `protokit lint --max-warnings 0
  <bad>.descriptor_set` with one WARNING finding exits 1.
- Happy path: `protokit lint --max-warnings 5
  <bad>.descriptor_set` with 3 WARNING findings exits 0;
  with 6 WARNING findings exits 1.
- Happy path: `protokit lint --statistics
  <bad>.descriptor_set` emits a footer with non-zero rows
  only.
- Happy path: bare `protokit lint <fixture>.descriptor_set`
  (no flags) emits findings only, no statistics footer
  (default-OFF per R16 revised).
- Happy path: `protokit lint --quiet <bad>.descriptor_set`
  produces no stdout output; exit code reflects findings.
- Happy path: `protokit lint --format human` works (default).
- Happy path: `PROTOKIT_FORMAT=human protokit lint
  <fixture>.descriptor_set` (no `--format` flag) resolves
  human format via click's envvar mechanism.
- Note: `--format=json|junit|sarif` happy paths land in U4b
  alongside the formatter registrations. At U4a's ship, those
  values exit 2 with `lint-format-unavailable` (covered by
  the error-path scenarios below).
- Edge case: `--max-warnings 0` with one ERROR-severity
  finding exits 1 (ERROR always exits 1 regardless of N).
- Edge case: `--max-warnings 0` with one INFO-severity finding
  exits 0 (INFO never gates).
- Edge case: `--statistics` with all-zero counts produces an
  empty footer (no rows rendered).
- Edge case: `--statistics` opts in to the footer;
  `--no-statistics` is a no-op confirmation flag for
  explicit-default scripts.
- Edge case: `--quiet --statistics` triggers click warning;
  `--quiet` wins (no footer).
- Edge case: `--quiet --format=json` → click validation error
  (mutex; `Usage:` prefix; exit 2 with click-owned prefix —
  NOT lint stable prefix).
- Edge case: `_LINT_ERROR_CODES` is sorted/stable order;
  parametrized tests over the constant tuple verify each code
  is reachable from at least one test case.
- Edge case: `--format=json` with `--statistics` flag passed —
  `--statistics` is human-only, so the flag is silently
  ignored (no warning needed; machine formats embed counts
  natively).
- Error path: `--format=does-not-exist` → exit 2 via
  `lint-format-unavailable` prefix; at U4a's ship lists only
  `human` as available. Same path for `--format=json|junit|sarif`
  until U4b registers the machine formatters.
- Error path: `--max-warnings=-1` → click `IntRange` error
  (`Usage:` prefix, click-owned).
- Error path: formatter callable raises `RuntimeError` →
  `_run_lint_formatter_safely` catches → exit 2 via
  `error[lint-formatter-exception]:`.
- Error path: formatter callable calls `sys.exit(0)` →
  `_run_lint_formatter_safely`'s `except SystemExit` (via
  shared body) catches per the formatter-systemexit-bypass
  learning → exit 2 via `error[lint-formatter-exception]:`
  (security regression prevention).
- Error path: formatter callable writes to `sys.stdout`
  directly → stdout-leak guard fires → exit 2 via
  `error[lint-formatter-exception]:`.
- Error path: formatter callable returns non-str →
  non-str-return guard fires → exit 2 via
  `error[lint-formatter-exception]:`.
- Error path: source compile (`--proto` mode) produces
  `CompileResult.diagnostics` with `level == 'error'` → exit
  2 via `error[lint-compile-failed]:`.
- Integration: every code in `_LINT_ERROR_CODES` has a
  corresponding test that verifies the exact stderr prefix
  (parametrized over the constant tuple — single source of
  truth for both implementation and tests).
- Integration: compat's existing `run_formatter_safely`-based
  test suite still passes after the `error_exit_fn` parameter
  refactor (backward-compat).
- Integration: KD-10 invariants 1, 2, 3 all hold.

**Verification:**
- All scenarios above pass.
- Error-prefix tests parametrize over `_LINT_ERROR_CODES` —
  count matches; no drift.
- `_LINT_ERROR_CODES` is NOT in `--help` output (verifies the
  R20a "internal-only" constraint).
- Compat test suite green (refactor backward-compat).
- KD-10 invariants 1, 2, 3 all hold.

---

- [ ] **Unit 4b: Machine formatters (lint_json/lint_junit/lint_sarif) + format-unavailable test updates**

**Goal:** Add the three machine formatter implementations to
`_builtin_lint.py` alongside the existing `lint_human`. After
this unit merges, `--format=json`, `--format=junit`, and
`--format=sarif` all produce structured output. Update the
`format-unavailable` test expectation to assert all four
formatter names appear in the available list. Add SARIF
2.1.0 schema validation and JUnit XSD validation tests so
schema drift fails CI rather than producing user-visible
broken output.

**Requirements:** R13 (machine-format wiring complete),
R15 (machine-formatter registrations).

**Dependencies:** U4a (lint-side wrapper + format flag +
format-unavailable error path all already exist; this unit
only registers the formatters and updates the available-list
expectation).

**Files:**
- Modify: `src/protokit/formatters/_builtin_lint.py` —
  **D4 absorption**: add three new formatter callables
  (`lint_json`, `lint_junit`, `lint_sarif`) registered via
  `_register_builtin` alongside the existing `lint_human`,
  all under `FormatterKind.LINT_REPORT`. Sibling-parity with
  compat's `_builtin_compat.py` which exposes the matching
  set.
- Modify: `tests/schema/lint/cli/test_cli_error_codes.py`
  — update the `format-unavailable` available-list
  expectation: now lists all four formatter names.
- Modify: `tests/test_builtin_lint_formatter.py` — extend
  with per-formatter scenarios for `lint_json`, `lint_junit`,
  `lint_sarif` (happy path + edge cases + diagnostic-rendering
  per format + schema validation per below).

**Approach:**
- Three new formatters follow compat's pattern at
  `_builtin_compat.py`. Each takes
  `(report: LintReport, ctx: FormatterContext) -> str`.
  - `lint_json`: serialize findings + filtered_count +
    runtime_warnings as a single JSON object. Schema mirrors
    compat's json output where the analogous concepts exist.
  - `lint_junit`: JUnit XML format suitable for CI test-result
    panels. Each finding becomes a `<failure>` element under a
    `<testcase>` whose name is the rule_id.
  - `lint_sarif`: SARIF 2.1.0 format suitable for code-scanning
    UIs (GitHub code scanning, Azure DevOps, etc.). Findings
    map to `results[]` with `ruleId` and `message`.

**Patterns to follow:**
- Compat's `_builtin_compat.py` for the three machine
  formatter implementations — the structural template
  applies.
- `_register_builtin` callsites in `_builtin_lint.py` for
  `lint_human` (U1-shipped) — three new calls follow the
  same shape.

**Test scenarios:**
- Happy path: `protokit lint --format json
  <fixture>.descriptor_set` produces JSON-formatted output;
  exits per R20 ladder.
- Happy path: `protokit lint --format junit
  <fixture>.descriptor_set` produces JUnit XML output.
- Happy path: `protokit lint --format sarif
  <fixture>.descriptor_set` produces SARIF 2.1.0 output.
- Happy path: `PROTOKIT_FORMAT=json protokit lint
  <fixture>.descriptor_set` (no `--format` flag) produces JSON
  output via click's envvar mechanism.
- Schema validation: `lint_json` output parses as valid JSON
  via `json.loads()`; structural shape matches a documented
  schema (top-level keys: findings, filtered_count,
  runtime_warnings).
- Schema validation: `lint_junit` output validates against a
  reference JUnit XSD (e.g.,
  https://github.com/jenkinsci/xunit-plugin/blob/master/src/main/resources/org/jenkinsci/plugins/xunit/types/model/xsd/junit-10.xsd).
  Use `lxml` or `xmlschema` library.
- Schema validation: `lint_sarif` output validates against
  the official SARIF 2.1.0 JSON schema
  (https://json.schemastore.org/sarif-2.1.0.json) via the
  `jsonschema` library. Critical for the CI-auditability
  identity bet — schema-drift bugs in SARIF output cause
  silent rejection by GitHub code scanning.
- Edge case: each formatter on a `LintReport` with zero
  findings produces well-formed empty output (empty `results`
  array in SARIF, empty `<testsuite>` in JUnit, empty
  `findings` list in JSON).
- Edge case: each formatter on a `LintReport` with diagnostics
  but no findings includes the diagnostics in its output (the
  format-specific representation).
- Edge case: `--format=json` with `--statistics` flag passed —
  `--statistics` is human-only, so the flag is silently
  ignored (no warning needed; machine formats embed counts
  natively).
- Integration: `format-unavailable` available-list test
  updated: now asserts the message lists all four
  formatter names (`human`, `json`, `junit`, `sarif`).
- Integration: KD-10 invariants 1, 2, 3 all hold.

**Verification:**
- All scenarios above pass.
- All four `--format` values resolve at U4b's ship.
- SARIF and JUnit schema validation tests pass against the
  reference schemas; this gate is what protects the
  CI-auditability identity bet from silent schema drift.

---

- [ ] **Unit 5: D2 residual docstring fold-ins (AC-05/AC-06) + compat parallel SystemExit hardening + integration tests + CI cold-import gate extension**

**Goal:** Land the two D2 ce:review residuals that are
docstring-only, harden compat's `load_formatter_packs` with
the parallel `except SystemExit` guard (sibling-parity with
U3's `--rule-pack` import; per round-1 P2 finding), complete
the integration test suite spanning all flag combinations,
and extend the CI cold-import smoke step to cover
`_builtin_lint`. Note: D3-present format-injection hardening
(catch-tuple widening) was moved out of U5 into U3 per
round-1 P1 finding — hardening must land alongside the
threat surface (`--rule-pack`), not 1-2 PRs later.

**Requirements:** R22, R23 (docstring fold-ins); compat
parallel hardening (sibling-parity); end-to-end test
coverage of every flag combination, loud-failure path,
error-prefix code, and the cold-import quarantine.

**Dependencies:** U1-U4b (the implementation surfaces all
exist).

**Files:**
- Modify: `src/protokit/schema/lint/model.py` (R22 — add
  `ctx.pool` mutation contract paragraph to
  `_LintContextEmitMixin` docstring AND each per-kind context
  dataclass docstring; R23 — tighten `LintRuleError`
  docstring from "at minimum includes" to "exactly is" for
  the catch-tuple list. **Critical**: the current docstring
  lists a 7-item tuple including `KeyError`, but
  `engine.py:_RULE_EXCEPTION_TUPLE` is a 6-item tuple that
  intentionally omits `KeyError` (because `LookupError`
  covers it — see engine.py source comment). The R23 edit
  MUST also drop `KeyError` from the listed tuple to match
  the engine; otherwise "is exactly" introduces a new
  falsehood. The corrected list: `(SystemExit, ValueError,
  TypeError, AttributeError, LookupError, LintRuleError)`.)
- Modify: `src/protokit/_cli_utils.py` — add `except SystemExit
  as exc:` guard to `load_formatter_packs` BEFORE the existing
  broad `except Exception` (sibling-parity with U3's
  `--rule-pack` import; closes the same false-green CI exit
  vulnerability). Routes to `error_exit` (compat's legacy
  helper) with a message naming the user-supplied exit code.
- Create: `tests/schema/lint/cli/test_cli_integration.py`
  (new — end-to-end coverage spanning U2-U4b).
- Modify: `tests/test_formatter_pack_loading.py` (or wherever
  compat's formatter-pack loading is tested) — add a test
  for the new SystemExit guard: a formatter pack module that
  calls `sys.exit(0)` at top-level → exit 2 via legacy
  `Error:` prefix (compat's existing error format), NOT
  false-green exit 0.
- Modify: `.github/workflows/ci.yml` — extend the inline
  `Cold-import smoke test` step at lines 83-107 to also
  reject `protokit.formatters._builtin_lint` from
  `sys.modules` after `import protokit.schema`. **Note**:
  the existing CI smoke step already substring-matches
  `'protokit.schema.lint' in k`, which transitively covers
  `protokit.schema.lint.cli`; the only NEW assertion this
  unit adds is the `_builtin_lint` exact-match check (lives
  under `protokit.formatters`, not `protokit.schema.lint`).
  (D1's smoke step lives in CI YAML as an inline
  `python -c ...` block, NOT in
  `tests/test_static_analysis.py` which is the ruff/mypy
  ratchet only.)

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
  description AND drop `KeyError` from the listed tuple to
  match `engine.py:_RULE_EXCEPTION_TUPLE` (6 items, not 7).
- Integration tests: cover the matrix of meaningful flag
  combinations spanning rule loading, profile resolution,
  CI gating, output formatting, and exit codes. Reuse
  fixtures from U2-U4b.
- CI cold-import gate: extend `.github/workflows/ci.yml`'s
  `Cold-import smoke test` step at lines 83-107 with one
  new not-in-sys.modules assertion for
  `protokit.formatters._builtin_lint`. (`lint.cli` is
  already covered by the existing substring-match on
  `protokit.schema.lint`.)

**Patterns to follow:**
- D2's `tests/schema/lint/test_engine.py` end-to-end shape
  for the integration tests.
- D1's existing cold-import smoke step pattern (verified
  during implementation).
- U1's existing `_render_message` catch pattern at
  `src/protokit/formatters/_builtin_lint.py:71-110` (widen
  in place).

**Test scenarios:**
- Integration: full pipeline single-pack —
  `protokit lint --proto valid.proto -I dir/ --statistics`
  produces findings + footer + exit 1, end-to-end.
- Integration: full pipeline multi-pack —
  `protokit lint --rule-pack=mypack a.descriptor_set
  b.descriptor_set --max-warnings 5 --quiet` exit code
  reflects findings; no stdout; R25 provenance line lists
  both packs on stderr (multi-pack triggers R25).
- Integration: full pipeline error chain — `protokit lint
  --rule-pack=test_pack_with_zero_rules --profile typo
  --format=json a.descriptor_set` exits 2 with the FIRST
  detected error: in this case
  `error[lint-no-rules]:` (the absence of any rules
  short-circuits before profile validation, which would
  short-circuit before format validation).
- Integration: format-cross-config scenario —
  `protokit lint --format=sarif --max-warnings 0
  <bad>.descriptor_set` produces SARIF with findings AND
  exits 1 (gating still applies regardless of format).
  **Acknowledges the next-delivery brainstorm responsibility**
  noted in origin's "Net Scope Honesty" — config bugs surface
  across all four formats simultaneously.
- Integration: cold-import smoke step extended; CI matrix
  passes on all 4 cells (`python: ["3.10", "3.12"] ×
  has_protoxy: [true, false]`).
- Happy path (AC-05): `_LintContextEmitMixin` docstring
  contains the `ctx.pool` mutation prohibition; each per-kind
  context's `pool` attribute docstring contains it.
- Happy path (AC-06): `LintRuleError.__doc__` says "is
  exactly" (NOT "at minimum includes") for the catch tuple.
- Edge case: existing D2 tests that referenced the older
  `LintRuleError` docstring text (if any) updated.
- Regression: all existing tests stay green; static analysis
  ratchet does not regress.

**Verification:**
- Full test suite green (target: ~900+ tests after D3
  lands).
- CI matrix green on all 4 cells.
- Cold-import smoke step passes locally and in CI.
- Manual smoke: `protokit lint <fixture>.descriptor_set`,
  `protokit lint --proto <fixture>.proto -I <dir>`,
  `protokit lint --rule-pack <user_pack>
  <fixture>.descriptor_set`, `protokit lint --format=sarif
  <fixture>.descriptor_set` — all behave per Success
  Criteria in the origin doc.
- KD-10 invariants 1, 2, 3 all hold throughout the delivery.

## System-Wide Impact

- **Interaction graph:** D3 adds a third subcommand on
  `src/protokit/cli.py`'s click group adjacent to `diff` and
  `compat`. No interaction between subcommands at runtime;
  click dispatches by name. The shared formatter registry
  (`src/protokit/formatters/_registry.py`) gains four new
  `LINT_REPORT` entries that compat / diff are unaware of —
  `clear_user_formatters` and `list_formatters` calls with
  the existing four kinds remain unchanged.
- **Error propagation:** Lint's exit-2 paths route exclusively
  through `error_exit_with_code` (lint-side helper). Click
  usage errors propagate via click's own machinery with
  `Usage:` prefix. Compat's `error_exit` and its callsites are
  untouched. CI scripts that filter on `error[lint-` get a
  clean lint-internal failure signal independent of compat's
  stderr. The `run_formatter_safely` refactor (U4) preserves
  compat's existing behavior via the `error_exit_fn=error_exit`
  default parameter.
- **State lifecycle risks:** The `_register_builtin` calls in
  `_builtin_lint.py` (four of them after U4) run at
  module-import time and are idempotent under reload. Test
  isolation is preserved via the existing
  `clear_user_formatters` test fixture pattern (built-ins
  survive `clear_user_formatters` by design —
  `_BUILTIN_NAMES` reservation protects them).
- **API surface parity:** D3 introduces `FormatterKind.LINT_REPORT`
  as a public enum value (already shipped in U1); consumers
  of `FormatterKind` may need to handle the fifth case. The
  codebase audit confirms no exhaustive `match` statements
  over the enum exist that would silently miss the new case.
  The `run_formatter_safely` refactor in U4a adds a new
  parameter; compat's existing callers default to the legacy
  prefix.
- **Integration coverage:** Multi-flag interactions (`--quiet`
  + `--statistics`, `--format=json` + R25 provenance ordering,
  R9 short-circuit before R11 short-circuit before R13, etc.)
  are covered in U5 integration tests. The format-cross-config
  scenario (e.g., SARIF + max-warnings) is explicitly tested
  per origin's "Net Scope Honesty" — config bugs surface
  across all four formats simultaneously.
- **Unchanged invariants:** `protokit diff` and `protokit
  compat` CLI behaviors are bit-for-bit unchanged. The
  formatter registry's built-in entries for the four
  pre-existing `FormatterKind` values remain registered with
  the same names. D2's engine API (`LintEngine.run` signature,
  `LintProfile.compose` semantics, `LintRuntimeWarning.category`
  Literal type) is unchanged. The cold-import contract from
  D1 is preserved (KD-10 invariant 2).

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| `_register_builtin` not actually idempotent under all reload scenarios (e.g., `importlib.reload` of the formatter registry itself) | U1 test exercises `importlib.reload(_builtin_lint)`; if registry-level reload is later needed, surface as a follow-up. |
| `_LINT_ERROR_CODES` drift — implementation adds a code without updating tests | Tests parametrize over `_LINT_ERROR_CODES` (single source of truth) verifying each code is reachable from at least one test case. The constant is NOT rendered into `--help`, so help-text drift is not a concern at D3. |
| Cold-import contract regression — a future refactor adds an import to `protokit.schema.cli` that pulls in lint | U5 extends D1's existing CI cold-import smoke step; CI fails on regression. |
| Test fixture descriptor-sets vary across protobuf-library versions | Generate descriptor sets at test time via session-scoped pytest fixture (`tests/schema/lint/cli/conftest.py`) that compiles checked-in `.proto` files via D1's `compile_protos_to_result`. Works on both `has_protoxy=true` and `=false` CI cells. No checked-in `.descriptor_set` binaries to drift. |
| KD-9 upgrade-safety policy needs an enforcement substrate, not just a docstring | U1's tests pin `BUILTIN_PACKS` membership: `tuple(p.__name__ for p in BUILTIN_PACKS) == ("protokit.schema.lint.rules.naming",)`. Hard CI gate on **test consistency** forces explicit intent for any change. CHANGELOG-update-in-same-commit remains a soft norm enforced via PR review. Promotion to a hard CHANGELOG gate is correctly deferred until the second pack is added (D6) — carrying cost of the hook substrate exceeds present value at one pack. |
| Format-injection vectors (`{name:>10**9}`, `{name.__class__.__mro__}`) reachable via `--rule-pack`-supplied `message_template`s | U5's source-side hardening widens `_render_message`'s catch to bare `except Exception` so width-specifier DoS attempts and recursive-`__format__` malice produce a graceful rule_id fallback instead of crashing the formatter mid-render. The holistic plugin-security model (whitelist of safe specs vs. safe-eval substitute) is deferred to D6 alongside the user-pack plugin contract. **Catch widening is defense-in-depth against crash-recovery, NOT mitigation for attribute-traversal info disclosure or OS OOM-kill** — those are explicitly D6 work. |
| Descriptor-set inputs reference WKTs or transitive imports without `protoc --include_imports` | R24's helper inspects `pool.Add` TypeError messages for `has not been loaded` / `couldn't resolve name` markers and routes those to `lint-missing-imports` with a diagnostic message naming the protoc invocation requirement. Discriminates from cross-set symbol-collision (which keeps `lint-pool-conflict`). U2 test obligation: exercise actual `descriptor_pool.Add` output for all three observed message shapes so a protobuf-version upgrade that changes wording becomes a CI failure rather than silent misrouting. |
| `--rule-pack MODULE` is a code-execution channel | R8's `importlib.import_module(MODULE)` evaluates arbitrary user Python at import time. D3 trusts the local operator (the user typing the flag = the user running the CLI), which is fine for a CLI flag. **In CI pipelines where `--rule-pack` is interpolated from YAML/Makefile config that is not root-operator-controlled, the trust assumption silently degrades to whoever can write that config — including PR authors.** Operators using `--rule-pack` in CI must ensure MODULE values come from a vetted, pinned source. The next delivery (pyproject config) widens this surface; D7 (plugin API) widens it again. The next-delivery brainstorm MUST answer the allowlist/integrity strategy before any implementation lands. |
| `--rule-pack` user pack calls `sys.exit(0)` at module load time, producing false-green CI exit | U3's `--rule-pack` import path adds an explicit `except SystemExit as exc` guard FIRST, before the broad `except Exception`, routing to `error_exit_with_code("rule-pack-load", ...)` with a message naming the user-supplied exit code. Prevents the false-green CI exit scenario. |
| `run_formatter_safely` refactor breaks compat's existing callers | U4a's refactor adds an `error_exit_fn` keyword parameter with a default of `error_exit` (the legacy helper). Compat's existing callsites are unchanged at the source-code level. U4a verifies compat's test suite stays green. |
| protobuf-python error message text changes across library versions, silently misrouting `pool.Add` TypeErrors | U2 test obligation pins discrimination predicates against actual `descriptor_pool.Add` output for all three observed message shapes (`has not been loaded`, `couldn't resolve name`, `duplicate symbol`). A protobuf upgrade that changes wording fails the test rather than producing silent misrouting. |
| KD-10 invariants violated mid-delivery (e.g., a unit lands on `main` with `protokit lint` exiting 2 from internal CLI errors) | Each unit's verification step explicitly asserts the three KD-10 invariants. Test parametrization includes "canary-clean inputs exit 0/1 only, never 2" coverage from U2 onward. |
| `BUILTIN_PACKS` becomes a public introspection surface that test fixtures or third-party tools monkey-patch | U1's docstring binds membership to major-version events; the membership-pin test fails on any change. External mutation of the tuple is undefined behavior; document this in a follow-up if a test-fixture monkey-patch pattern emerges. |

## Documentation / Operational Notes

- **README**: D3 should fold `protokit lint` into the README
  — D3 absorbed D4's machine formatters (KD-5 revised), so
  the formatter story is complete at D3 ship time.
  First-impression discoverability matters; release the
  user-visible documentation alongside the surface.
- **CHANGELOG**: D3 entry should explicitly note:
  - New `protokit lint` subcommand with full-formatter
    parity (`human`/`json`/`junit`/`sarif`).
  - Usable for binary CI gating via `--max-warnings 0
    --quiet` exit codes AND for code-scanning UIs via
    `--format=sarif` / `--format=junit`.
  - `BUILTIN_PACKS` is the auto-load surface; membership
    changes are major-version events (KD-9 anchor;
    promotion policy decision deferred to D6).
  - `--rule-pack MODULE` ships as a fully-qualified Python
    module path channel; security-conscious users must
    ensure MODULE values come from vetted sources.
- **Help text**: `protokit lint --help` should be
  copy-edited during impl; verify it renders all flags +
  a brief description of the exit-code ladder. The
  `_LINT_ERROR_CODES` list is NOT rendered into help text
  (R20a revised) — discoverability is via documentation,
  not the help surface.
- **CI**: D1's 4-cell CI matrix is unchanged; the cold-import
  smoke step gains two assertions in U5. The
  `tests/test_static_analysis.py` ratchet auto-covers new
  files via D1's directory globs.
- **Rollout (REVISED — D3 absorbs D4)**: the original
  D3+D4 sequencing commitment is no longer needed because
  D3 ships full-formatter parity. D3 lands as a single
  user-visible release with CHANGELOG entry + version bump
  + README update. No "preview / not-yet-CI-complete"
  framing required.
- **TODOS.md renumbering**: before planning the next
  delivery, update `TODOS.md` to reflect the absorbed-D4
  sequence: pyproject config (formerly D5), more rule packs
  (formerly D6), plugin API (formerly D7).

## Sources & References

- **Origin document:** [docs/brainstorms/2026-05-04-protokit-lint-delivery-3-cli-requirements.md](../brainstorms/2026-05-04-protokit-lint-delivery-3-cli-requirements.md)
- **D1 brainstorm (cold-import contract origin):** `docs/brainstorms/2026-04-30-protokit-lint-delivery-1-foundation-requirements.md`
- **D2 brainstorm (engine + canary):** `docs/brainstorms/2026-05-02-protokit-lint-delivery-2-engine-requirements.md`
- **D2 plan (structural template):** `docs/plans/2026-05-02-001-feat-protokit-lint-d2-engine-plan.md`
- **Sibling-parity learning:** `docs/solutions/best-practices/audit-wire-format-before-claiming-sibling-parity-2026-05-03.md`
- **Formatter SystemExit security learning:** `docs/solutions/security-issues/formatter-systemexit-exit-code-bypass-2026-04-19.md`
- **TODOS.md D3 entry:** lines 103-114 (renumber after D3 lands)
- **Top-level CLI group:** `src/protokit/cli.py:20-27`
- **Compat CLI structural template:** `src/protokit/schema/cli.py:583-737`
- **Formatter registry:** `src/protokit/formatters/_registry.py:21,128,183,203,222`
- **Eager-load tuple to preserve:** `src/protokit/formatters/__init__.py:60-71`
- **D1 compile entry:** `src/protokit/schema/compile.py`
- **D2 engine API:** `src/protokit/schema/lint/engine.py`
- **D2 profile primitives:** `src/protokit/schema/lint/model.py:499-665`
- **D2 LintRuntimeWarning Literal type:** `src/protokit/schema/lint/model.py:421`
- **U1 LintReport.specs field:** `src/protokit/schema/lint/model.py:472-485`
- **D2 canary rule pack:** `src/protokit/schema/lint/rules/naming.py`
- **U1 BUILTIN_PACKS anchor:** `src/protokit/schema/lint/rules/__init__.py`
- **U1 lint_human formatter:** `src/protokit/formatters/_builtin_lint.py`
- **`run_formatter_safely` (U4a refactor target):** `src/protokit/_cli_utils.py:487-549`
- **Compat's broad-catch import pattern:** `src/protokit/_cli_utils.py:402-413`
