---
date: 2026-05-04
topic: protokit-lint-delivery-3-cli
---

# protokit-lint Delivery 3 — `protokit lint` CLI Subcommand

Created: 2026-05-04
Source roadmap: `TODOS.md` lines 103-114 ("D3 — `protokit lint` CLI subcommand").
Foundation landed: D1 (commits `0b82fc3`, `e85faea`, `31c0bb1`) + D2 engine + canary (commits `26bd312`, `3fe3b8c`, `8c4ba9c`, `329b22f`, `8927d1f`, `b26cb5d`, `3252918`, `a0b7692`).
Sequence: depends on D2; precedes pyproject config (formerly D5; D4 absorbed into D3 — see KD-5), then more rule packs (formerly D6 — KD-9 promotion-policy decision lives here), then plugin API parity (formerly D7, including `--compat-rule-pack` rename).

## Problem Frame

D2 shipped the `LintEngine` + `naming/snake-case-fields` canary, but
lint output is reachable only via library calls today. There is no
user-visible CLI surface for lint — `protokit compat` exists,
`protokit lint` does not. Three downstream deliveries (D5 config,
D6 rule packs, D7 plugin API) all need a CLI to be useful at all.
D3 closes the dogfood gap.

D3 also resolves three product decisions D1/D2 deliberately deferred:
how built-in rule packs load, how `--profile` resolves across packs,
and which CI-friendly flags ship Day-1. Leaving these unresolved
would force ad-hoc decisions in D5 (which reads pyproject config
that overrides CLI defaults) and D6 (which adds more built-in
packs that need a load story).

**Slicing rationale revisited (REVISED during D3 brainstorm
pressure-test pass).** D2's original staging put `human` in
D3 and `json`/`junit`/`sarif` in D4. The pressure-test pass
surfaced that splitting the formatter delivery damages the
identity bet: a CI-positioned linter that fails the obvious
`--format=sarif` invocation directly contradicts its own
"CI auditability" claim every time a user tries it during
the D3-only window, and the `PROTOKIT_FORMAT` cross-subcommand
collision (compat supports json/junit/sarif since Phase 1.5b)
puts that contradiction in front of every CI shell that
exports the envvar globally. **D3 absorbs D4's machine
formatters.** All four lint formatters (`human`, `json`,
`junit`, `sarif`) ship together in D3, registered via
`_register_builtin` in `src/protokit/formatters/_builtin_lint.py`
under `FormatterKind.LINT_REPORT`. The original "preserves
the staged-review property" framing is reversed: shipping
half-formatter parity is the worse-than-staged outcome.
D3's delivery shape grows to include U4's machine-formatter
registration; the original "D4 — formatters" delivery is
absorbed and removed from the roadmap.

**Net scope honesty** (added during round-2 pressure-test —
the round-1 cuts framing implied D3 shrank, but the
absorption added more scope than the cuts removed): the D3
spec is now **larger** than the original D3+D4 combined
spec. The round-1 cuts (R7 deferral, R10 single-pack skip,
R25 gating, R16 default-OFF, R20a merge, KD-9 policy
deferral, help-text rendering drop) are spec
simplifications — they trimmed roughly 1-2 implementation
units of complexity. The D4 absorption added three formatter
implementations + their tests + a new `lint-missing-imports`
error code + the D3-Present Security Risks section + the
catch-tuple widening — approximately 2-3 units of growth.
Net direction: growth, not shrinkage. The growth is justified
(identity-bet damage > scope concern), but planning should
budget for the full scope rather than treating the cuts as
a counterweight to the absorption. The next-delivery
(pyproject config) brainstorm inherits a CLI surface that's
already at compat-feature-parity for formatters — config
bugs in pyproject will surface across all four formats
simultaneously rather than being caught in a narrower D4
window. Test fixtures and review attention should weight
format-cross-config interactions accordingly.

## Requirements

**Subcommand surface**

- R1. New click subcommand `protokit lint` registered on the
  top-level click group at `src/protokit/cli.py`. Implementation
  module at `src/protokit/schema/lint/cli.py` (parallel to
  `src/protokit/schema/cli.py`'s compat surface). The subcommand is
  a single command, NOT a sub-group — no `protokit lint check` /
  `protokit lint history`-style nesting in D3.
- R2. The subcommand accepts one or more positional path arguments
  and a `--proto` flag, mirroring `protokit compat check`'s
  argument-passing style: positional descriptor-set paths by
  default; `--proto` switches to source-file mode. Unlike compat
  (which requires one OLD path and one NEW path — two inputs from
  conceptually different schema snapshots), lint takes a single
  input set: one or more paths of the same kind, all merged
  together. There is no "old vs new" axis in lint.
- R3. Cold-import contract preserved: `import protokit.schema`
  must continue NOT to load `protokit.schema.lint` transitively.
  Validated by extending the D1 cold-import smoke step in CI to
  also cover the lint CLI module's quarantine. The lint subcommand
  module loads only when `protokit.cli` itself is imported (i.e.,
  at CLI invocation time), not on `import protokit` (which today
  stays empty per the package convention).

**Input modes**

- R4. Two input modes ship in D3:
  - **Descriptor-set mode (default)**: `protokit lint FOO.descriptor_set`
    — positional path to a serialized `FileDescriptorSet`. Multiple
    positional paths supported (each merged into the compile
    result's pool; their union forms `root_files`).
  - **Source mode (`--proto`)**: `protokit lint --proto a.proto b.proto -I dir/`
    — paths are `.proto` source files compiled via the existing
    `protokit.schema.compile.compile_protos_to_result` (D1 entry
    point). `-I` / `--proto-path` is repeatable and matches
    compat's flag name.
- R5. Git modes (`--since`, `--against-base`) are explicitly
  deferred — see Scope Boundaries. The git scaffolding in
  `src/protokit/schema/git.py` exists and is reusable; adding
  lint git modes later is purely additive on top of D3.

**Rule loading**

- R6. Built-in rule packs auto-load on subcommand startup. For D3
  this means importing `protokit.schema.lint.rules.naming` and
  calling `engine.load_rule_pack(naming)`. The auto-load list is
  the curated set of packs that fire by default — see KD-9 for
  the upgrade-safety policy that governs how new built-in packs
  get promoted into this list. Packs that ship with protokit but
  are NOT in the auto-load list remain available via
  `--rule-pack <module>`. The auto-load list is *not* "all packs
  that ship with protokit"; it is "all packs that fire without
  explicit opt-in."
- R7. **DEFERRED to D6** (during D3 brainstorm pressure-test
  pass). `--no-builtin-rules` was originally drafted to opt
  out of step R6's auto-load. With one built-in pack at D3
  ship time, the flag's user-visible value is admitted-zero
  (the same effect is reachable via `--rule-pack mypkg` with
  a pack that doesn't redeclare `naming/snake-case-fields`).
  Standard just-in-time pattern: the flag earns its keep in
  D6 when a second built-in pack lands. Adding the flag in
  D6 is purely additive — D3 has no users to break.
  R9 zero-rules loud failure remains in scope: if all loaded
  `--rule-pack`s declare zero rules under the active profile,
  exit 2 with `error[lint-no-rules]:`.
- R8. `--rule-pack MODULE` (repeatable string) loads additional
  rule packs on top of (or, with R7, instead of) the built-ins.
  **`MODULE` is a fully-qualified dotted Python module name**
  (e.g., `acme.lint_rules`) — NOT a short name. The CLI calls
  `importlib.import_module(MODULE)` and passes the resulting
  module object to `engine.load_rule_pack`. Same wire format as
  D2's `engine.load_rule_pack(module)` — the module exposes
  `RULES = (decorated_fn, ...)`. **DIVERGES from compat's
  `--rule-pack` wire format** (compat expects
  `RULES = ((rule_id, fn), ...)`); see Sibling-Parity Audit.
  Built-in packs use full module names like
  `protokit.schema.lint.rules.naming`; user packs collide with
  built-ins only on full-name match (a top-level `naming`
  module does NOT collide with the built-in
  `protokit.schema.lint.rules.naming`).

  *Shadow contract*: `engine.load_rule_pack` raises
  `DuplicateRuleError` on cross-pack `rule_id` collision (per
  D2's locked behavior; diverges from compat which silently
  shadows). A user who wants to override a built-in rule MUST
  pair (in D6+ when `--no-builtin-rules` ships) with a
  `--rule-pack` that reimplements the desired built-ins under
  the same or different ids. D3 does NOT introduce a
  `--disable-rule RULE_ID` or `--override-rule-pack` escape
  valve.

  *Concrete promotion trigger for `--disable-rule`* (REVISED
  during round-2 pressure-test — original numeric threshold
  ">5 rules" was reviewed and recognized as delayed-deferral
  disguised as a measurable expiration): ship `--disable-rule
  RULE_ID` (repeatable; filters from the loaded set after
  composition) when **a user files an issue requesting
  per-rule suppression** — the only honest decisive signal.
  Additionally, **D6's brainstorm MUST address `--disable-rule`
  explicitly**: deferring further requires a written rationale
  in the D6 brainstorm doc rather than a quiet rollover. This
  converts the deferral from "we'll add it if someone
  complains" into a procedural gate that surfaces at every
  D6+ brainstorm.
- R9. Loud failure when zero rules load. The check fires
  CLI-side AFTER profile composition completes but BEFORE
  `engine.run` is called. Two predicates, evaluated in order:
  (a) `not engine._loaded_specs` — no rules loaded across any
  pack (typically: `--no-builtin-rules` set with no
  `--rule-pack`, OR all `--rule-pack`s declared empty `RULES`).
  (b) `not composed_profile.rule_ids` — packs loaded rules but
  none match the active profile (typically: `--profile X`
  typo, or all loaded packs declare zero rules under `X`).
  When BOTH would fire, **(a) wins** — the user can't
  meaningfully fix profile selection until they have rules
  to select from. Predicate (a) routes through
  `error[lint-no-rules]:`; predicate (b) routes through
  `error[lint-unknown-profile]:`. Exit code 2 with stderr
  text identifying which path was taken. Prevents silent
  green CI from misconfiguration.

**Profile resolution**

- R10. `--profile NAME` (string, default `"default"`).
  Resolution: D3 has exactly one auto-loaded pack
  (`BUILTIN_PACKS = (naming,)`); `--rule-pack` adds
  user-supplied packs on top. Resolution path:
  - **Single-pack case (D3 default)**: call
    `LintProfile.from_pack(pack, name)` directly. No
    `compose` call.
  - **Multi-pack case (`--rule-pack` adds 1+ packs)**: build
    per-pack profiles via `from_pack` and call
    `LintProfile.compose(*per_pack_profiles)`. Composed
    profile's `rule_ids` is the union of every pack's
    matching rule_ids; `min_severity` is the strictest
    (highest rank); severity overrides merge per D2's
    documented `compose` semantics.

  *Why skip compose in the single-pack case*: `from_pack`
  always returns `min_severity = LintSeverity.WARNING` (per
  `lint/model.py:522`), so a single-pack `compose()` is a
  no-op identity reduction with carrying cost. The
  strictest-wins semantics is exercised only when callers
  construct `LintProfile` directly with non-default
  `min_severity` — e.g., the next delivery's pyproject
  config. Lifting `compose` back into the always-on path is
  a one-line change when that delivery introduces the first
  non-default-floor caller.
- R11. Empty resolved profile (no rule_ids match `name`
  across all loaded packs) is the loud-failure case in R9 —
  exit 2 with stderr listing the profile names each loaded
  pack declares.

  *Behavioral specification*: the exit-2 stderr message must
  list every profile name declared across all loaded packs,
  grouped by pack module name (e.g.,
  `protokit.schema.lint.rules.naming declares profiles:
  {default}; acme.lint_rules declares profiles: {strict,
  ci}`). Implementation chooses the access path — planning
  decides whether to walk each loaded pack's `RULES` tuple
  client-side or extend the engine's introspection API. The
  requirement is the user-visible message shape, not the
  algorithm.
- R12. `--min-severity LEVEL` (choice: `info` / `warning` /
  `error`, default unset) overrides the composed profile's
  `min_severity` before passing to `engine.run`. When unset, the
  composed profile's value (driven by `from_pack`'s defaults +
  any pack-declared severity) is used.

  *Override semantics*: `--min-severity` is a free override —
  it can both raise (more strict, fewer findings) and lower
  (more lenient, more findings) the composed floor. As of D3
  there is no first-class observability for relaxation — the
  override applies as a pure numeric floor pre-emit. **The
  silent-relaxation observability (originally drafted as a
  `LintRuntimeWarning(category="min_severity_relaxed")` emission)
  is deferred to D5**, where pyproject config introduces the
  first non-default-`min_severity` caller and a real path that
  actually fires the warning. Deferring also avoids extending
  D2's locked `LintRuntimeWarning.category` Literal type in D3
  — the same constraint that drove R21's deferral (KD-8).
  Pack-author-declared severity floors are advisory, not hard
  contracts; users are trusted to relax for development workflows.

**Output and formatting**

- R13. `--format NAME` (string, default `human`, envvar
  `PROTOKIT_FORMAT`). The flag value resolves via the existing
  `protokit.formatters.get_formatter` registry against the new
  `FormatterKind.LINT_REPORT` discriminator. **D3 ships all
  four formatters: `human`, `json`, `junit`, `sarif`** (see
  KD-5; D4's machine-formatter delivery is absorbed into D3).
  Unknown values raise `KeyError` from `get_formatter` per
  its documented contract at `_registry.py:213-218`; the CLI
  catches via lint's helper and routes to
  `error_exit_with_code("format-unavailable", ...)` (R20a)
  which emits `error[lint-format-unavailable]:` and lists the
  available formatter names from
  `list_formatters(FormatterKind.LINT_REPORT)`.
  `PROTOKIT_FORMAT` envvar support matches compat's pattern.
  Because D3 ships full-formatter parity with compat, no
  cross-subcommand collision exists for the four standard
  formats — `PROTOKIT_FORMAT=json` works uniformly across
  `protokit compat` and `protokit lint`.
- R14. D3 adds `FormatterKind.LINT_REPORT` to the
  `protokit.formatters._registry.FormatterKind` enum. The four
  existing kinds (`DIFF`, `COMPAT`, `COMPAT_HISTORY`,
  `COMPAT_BISECT`) gain a fifth sibling. No existing formatter
  surface changes.
- R15. New module `src/protokit/formatters/_builtin_lint.py`
  registers a `human` lint formatter via the **internal**
  helper `_register_builtin(name="human", fn=lint_human,
  kind=FormatterKind.LINT_REPORT)` (per `_registry.py:183-200`). The
  formatter callable is named `lint_human` (sibling-parity with
  `diff_human` / `compat_human` / `history_human` / `bisect_human`
  per the audit-wire-format learning; resolved during Unit 1
  ce:review). Using
  `_register_builtin` rather than the public
  `register_formatter` (a) makes registration idempotent under
  module reload (test suites, dev REPL, importlib.reload —
  `_register_builtin` overwrites silently; `register_formatter`
  raises `FormatterError` on duplicate keys) and (b) reserves
  the `human` name in `_BUILTIN_NAMES` so future user formatter
  packs cannot shadow the lint built-in. The module is **NOT**
  added to the eager-load tuple at
  `src/protokit/formatters/__init__.py:60-71` (preserves D1's
  cold-import P0 finding). The lint subcommand module imports
  `_builtin_lint` at its module top — registration runs at
  `protokit.cli` load time (i.e., on every `protokit ...` CLI
  invocation, regardless of which subcommand is used), NOT at
  the first `protokit lint` invocation specifically. The
  cold-import contract is preserved because `protokit.schema`
  does not import `protokit.cli` and `_builtin_lint` is not in
  the eager-load tuple. **D3 absorbs D4** (KD-5 revised) — all
  three additional lint formatters (`lint_json`, `lint_junit`,
  `lint_sarif`) are registered in this same `_builtin_lint.py`
  module alongside `lint_human`, all under
  `FormatterKind.LINT_REPORT` (also via `_register_builtin`).
- R16. `--statistics` (boolean flag, **default OFF** —
  REVISED during D3 brainstorm pressure-test; aligns with
  ruff/eslint/buf-lint convention of silent-on-clean) emits a
  human-format footer when explicitly passed and `--format=human`
  and not `--quiet` (ignored otherwise) with: per-severity
  finding counts
  (computed by iterating `report.findings` and bucketing by
  `finding.severity` — there is no precomputed `severity_counts`
  field on `LintReport`), filtered count (from
  `LintReport.filtered_count`), and runtime warning count (from
  `len(LintReport.runtime_warnings)`). When `--format` is
  non-human or `--quiet` is set, this flag has no effect (no
  footer in machine formats; no output at all under quiet).
  Empty rows (zero counts) are suppressed in the footer to keep
  clean-run output compact.
- R17. *DEFERRED — see Scope Boundaries*. `--ignore PATH` was
  considered for D3 but deferred to D5 where it can be
  co-designed with `[tool.protokit.lint] exclude` globs. The
  per-variant prefix-match target across 8 `LintLocation`
  variants is itself a design question worth resolving with the
  pyproject config rather than baking a CLI-only mechanism that
  D5 then inherits. With one built-in rule in D3, the
  suppression need is satisfied by `--no-builtin-rules` (opt-out
  the whole pack) or a custom `--profile NAME` (opt-out by
  profile membership).
- R18. `--quiet` (boolean flag). Suppresses formatter output
  entirely; only the exit code communicates result. Mutex with
  any non-`human` format (mirrors compat's "any non-human format"
  mutex from Phase 1.5b). When `--quiet` is passed alongside
  explicit `--statistics`, click emits a usage warning and
  `--quiet` wins (no footer, no output) — resolving Q3 inline.

**CI gating**

- R19. `--max-warnings N` (integer, default unset = unlimited).
  Cap on WARNING-severity findings only. ERROR-severity findings
  always trigger exit 1 regardless of N. INFO-severity findings
  never trigger non-zero exit (they're advisory; if D6+ ships
  rules where INFO gating matters, a future delivery introduces
  `--max-info` or generalizes to `--max-findings-of SEVERITY=N`).
  The cap counts findings AFTER R12 min-severity filtering. When
  unset, only ERROR-severity findings drive exit 1.
- R20. Exit codes (mirror compat's uniform 0/1/2 ladder):
  - **0** = clean: no ERROR-severity findings AND
    (`--max-warnings` unset OR WARNING count ≤ N).
  - **1** = findings exceed gate: ERROR-severity present, OR
    WARNING count > `--max-warnings`.
  - **2** = diagnostics: compile errors in `CompileResult.diagnostics`,
    malformed flags, R9 zero-rules loud failure, R11 unknown
    profile, R13 unavailable formatter, formatter raised
    exception (consistent with Phase 1.5b's
    `run_formatter_safely`).
- R20a. *Stable stderr error-prefix codes* — lint's own exit-2
  failure modes emit a stderr line with a stable
  `error[lint-CODE]:` prefix so CI scripts can parse without
  relying on freeform message text. **A new helper
  `error_exit_with_code(code: str, message: str)` lives in
  `src/protokit/schema/lint/_cli_utils.py`** (NOT in the
  top-level `protokit._cli_utils.py` — keeps lint and compat
  surfaces decoupled). The helper writes
  `error[lint-{code}]: {message}` to stderr and `sys.exit(2)`.
  Lint's own callsites use this helper exclusively.

  Codes reachable in D3:
  - `error[lint-no-rules]:` — R9 zero rules loaded (no built-ins
    + no `--rule-pack`, OR all loaded packs declare zero rules
    under the active profile).
  - `error[lint-unknown-profile]:` — R11 composed profile is
    empty due to typo / unknown name.
  - `error[lint-format-unavailable]:` — R13 `--format` value not
    registered for `FormatterKind.LINT_REPORT` in the registry.
  - `error[lint-compile-failed]:` — R4 source-mode compile
    produced `CompileResult.diagnostics` containing entries with
    `level == 'error'` (matching `LintCompileDiagnostic.level:
    Literal['info', 'error']`). Note: a successful compile via
    protoxy→protoc fallback emits an `info`-level diagnostic
    that must NOT trigger this code — the predicate is
    explicitly `any(d.level == 'error' for d in
    result.diagnostics)`.
  - `error[lint-formatter-exception]:` — formatter callable
    raised under `run_formatter_safely`.
  - `error[lint-bad-input]:` — descriptor-set bytes failed to
    parse (R24 helper).
  - `error[lint-pool-conflict]:` — R24 pool.Add raised
    TypeError on a cross-set symbol-level collision (NOT a
    duplicate filename — those are deduped pre-Add; NOT a
    missing-imports failure — that's `lint-missing-imports`).
  - `error[lint-missing-imports]:` — R24 pool.Add raised
    TypeError matching the `has not been declared` pattern,
    indicating the descriptor_set was produced without
    `protoc --include_imports` or omits well-known-type
    descriptor files. Discriminates from the
    cross-set-collision case to give first-time users a
    diagnostic that points at the protoc invocation rather
    than at "symbol collision" they may not recognize.
  - `error[lint-rule-collision]:` — `engine.load_rule_pack`
    raised `DuplicateRuleError` when a `--rule-pack` declares
    a `rule_id` colliding with a built-in or another loaded
    pack (per D2's no-shadow contract).
  - `error[lint-rule-pack-load]:` — `--rule-pack MODULE`
    failed to load. Covers the full failure surface in a
    single code: (a) `importlib.import_module` raised any
    `Exception` (module path typo, missing install, broken
    `__init__.py`, or any top-level exception raised during
    the user pack's module body — `NameError`, `RuntimeError`,
    `ZeroDivisionError`); (b) the import succeeded but the
    module's `RULES` tuple has the wrong wire format
    (`TypeError` from `LintProfile.from_pack` /
    `LintEngine.load_rule_pack` — most commonly the user
    wrote compat-style `RULES = ((rule_id, fn), ...)`
    instead of lint's `RULES = (decorated_fn, ...)`); (c)
    a user pack's module body called `sys.exit(...)` (or
    raised `SystemExit` directly) — without an explicit
    `except SystemExit` guard, the standalone-mode click
    runner re-raises with the user pack's exit code,
    silently producing a false-green CI exit (exit 0)
    when the user pack called `sys.exit(0)`. The catch
    pattern is therefore `except SystemExit as exc:` first
    (routing to `rule-pack-load` with message naming the
    user-supplied exit code), then `except Exception`
    second (routing all other Exception subclasses).
    `BaseException`/`KeyboardInterrupt` still propagates.
    Matches compat's `run_formatter_safely` SystemExit
    guard pattern (`src/protokit/_cli_utils.py:521-529`)
    extended to compat's `load_formatter_packs` import
    pattern (`src/protokit/_cli_utils.py:402-413`).

    **Discrimination via message text, not code split**: the
    stderr message body distinguishes the two failure modes
    explicitly. Import failures: `error[lint-rule-pack-load]:
    failed to import 'acme.lint_rules': ModuleNotFoundError:
    No module named 'acme.lint_rules'`. Shape failures:
    `error[lint-rule-pack-load]: 'acme.lint_rules' has wrong
    wire format: ('snake_case', <function fn>) is not
    @lint_rule-decorated. lint expects RULES =
    (decorated_fn, ...); compat's RULES = ((rule_id, fn),
    ...) is incompatible. See
    audit-wire-format-before-claiming-sibling-parity-2026-05-03.`
    The single-code design follows compat's pattern (Phase
    1.5b shipped without per-failure-mode error codes and no
    user pain has been reported); reversibility-favorable
    (additive split is non-breaking; merge-after-split would
    break CI scripts). If a real CI consumer requests the
    split later, add `lint-rule-pack-shape` as a strictly-additive
    new code.

  *Coverage gap acknowledged*: the existing top-level
  `error_exit()` in `protokit._cli_utils.py:68` writes
  `Error: {message}` (legacy compat surface). Lint never calls
  that helper — all lint exit-2 paths go through
  `error_exit_with_code`. Click's own usage errors (e.g.,
  malformed flag values, missing required args) keep their
  default `Usage:` / `Error:` prefixes — those are click-owned.
  CI scripts that need to distinguish lint-internal failures
  from click-side flag errors filter on the `error[lint-`
  prefix specifically; click-side errors carry click's own
  prefix and are reachable independently of `error_exit_with_code`.

  The stable-prefix list lives in a module-level
  `_LINT_ERROR_CODES: tuple[str, ...]` constant in
  `src/protokit/schema/lint/_cli_utils.py` as a single source
  of truth for the helper's input validation and for tests.
  **The constant is NOT rendered into `protokit lint --help`**
  (REVISED during D3 brainstorm pressure-test pass): help
  text rendering would add a dual-maintenance test obligation
  ("help must contain every code") that compat doesn't have,
  and the discoverability win is better served by
  documentation in `CLAUDE.md` or a future
  `protokit lint --list-error-codes` flag if CI authors ask
  for it. Promote help-text rendering to a hard requirement
  in D6 if the code list grows past ~10 and discoverability
  pressure materializes.

**D2 ce:review residuals folded in**

- R21. *DEFERRED to future delivery* (REVISED after D3
  brainstorm pressure-test absorbed D4 into D3). **REL-03** —
  `LintRuntimeWarning.emit_count_before_exception: int = 0`
  was considered for D3 but stays deferred. Rationale: the
  field requires (a) extending a frozen D2 type, (b)
  modifying `_invoke_rule` in `LintEngine` to snapshot
  per-rule emit counts, and (c) wiring formatters to render
  it. D3 absorbed D4 but no concrete consumer is asking for
  the field; lands when a real per-rule emit-count debugging
  need surfaces.
- R22. **AC-05** — add `ctx.pool` mutation contract to the
  `_LintContextEmitMixin` and per-kind context docstrings in
  `lint/model.py`: rules MUST NOT mutate `ctx.pool` during the
  walk. Documentation-only; no runtime check.
- R23. **AC-06** — tighten `LintRuleError` docstring from "at
  minimum includes" to "exactly is" for the catch tuple.
  Documentation-only.

**Descriptor-set ingestion**

- R24. New helper `_load_descriptor_sets_to_result(paths:
  tuple[Path, ...]) -> CompileResult` lives in
  `src/protokit/schema/lint/_cli_utils.py`. Algorithm
  (dedupe-before-Add — protobuf's `pool.Add(fd)` raises
  `TypeError` on duplicate `fd.name`, so dedup MUST happen
  before pool insertion):

  ```
  pool = DescriptorPool()
  seen_names: set[str] = set()
  duplicate_warnings: list[str] = []
  root_files: list[str] = []
  for input_path in paths:
      try:
          fds = FileDescriptorSet.FromString(input_path.read_bytes())
      except (OSError, DecodeError) as exc:
          error_exit_with_code("bad-input", f"{input_path}: {exc}")
      for fd in fds.file:
          if fd.name in seen_names:
              duplicate_warnings.append(fd.name)
              continue
          seen_names.add(fd.name)
          try:
              pool.Add(fd)
          except TypeError as exc:
              # Cross-file symbol collision (different fd.name,
              # same message FQN) — distinct from filename dedup.
              error_exit_with_code(
                  "pool-conflict", f"{input_path}: {exc}"
              )
          root_files.append(fd.name)
  return CompileResult(
      pool=pool,
      root_files=tuple(root_files),
      diagnostics=(),
  )
  ```

  *Duplicate filename observability*: duplicates are accumulated
  in `duplicate_warnings` (not `LintRuntimeWarning` — D2's
  `category` Literal stays untouched in D3, per KD-8). The CLI
  prints them as a one-line stderr note before running:
  `protokit lint: deduplicated {N} duplicate file path(s) across
  input sets: {names}`. Suppressed under `--quiet`. Audit-trail
  only; does not change exit code.

  *Disambiguating `pool.Add` TypeErrors*: `pool.Add(fd)`
  raises `TypeError` for several distinct failure modes that
  share the exception type. The helper inspects the message
  text (verified empirically against the protobuf Python
  C++ runtime — see Forward-Looking Risks for the
  fragility-against-protobuf-version-upgrade caveat) to
  route to the right error code:
  - **Missing transitive imports** (descriptor_set produced
    without `protoc --include_imports`, or referencing
    `google.protobuf.Timestamp`/`Duration`/`Any` without
    bundling the WKT files): TypeError message contains
    either `has not been loaded` (the dependency-file case:
    `Depends on file '<path>', but it has not been loaded`)
    OR `couldn't resolve name` (the dangling-symbol case:
    `couldn't resolve name '<fqn>'`). Routes to
    `error[lint-missing-imports]:` with stderr message
    naming the requirement: `descriptor_set
    '{input_path}' references types not present in the
    set; rebuild with 'protoc --include_imports' or include
    the WKT descriptor file. Underlying: {exc}`. This is
    the most common protoc footgun for first-time users
    and deserves its own discriminating diagnostic.
  - **Cross-set symbol collision** (e.g., `a.descriptor_set`
    defines `acme.User`, `b.descriptor_set` also defines
    `acme.User` with different fields under a different
    `fd.name`): TypeError message contains
    `duplicate symbol`. Routes to
    `error[lint-pool-conflict]:` listing the conflicting
    input file. Undefined behavior for the lint walk;
    users must pre-merge or namespace-separate.
  - **Unmatched TypeError** (protobuf upgrade changed the
    message text, or a new failure mode emerged): falls
    through to `error[lint-pool-conflict]:` with the raw
    exception text — preserves the legacy behavior so
    users still get a stable error code.

  *Test obligation*: U2's tests MUST exercise actual
  `descriptor_pool.Add` output for all three observed
  message shapes (loaded-dependency-missing,
  resolve-name-failure, duplicate-symbol) so a
  protobuf-version upgrade that changes wording becomes a
  CI failure rather than silent misrouting.

  *Trust model on inputs*: descriptor-set files are trusted
  build artifacts from the operator's own build system. No
  size cap is enforced before `read_bytes()` /
  `FileDescriptorSet.FromString()`. Operators using
  protokit-lint against descriptor sets from untrusted
  remote sources (extremely uncommon — descriptor_sets are
  not typically distributed) should configure shell-level
  resource limits on the lint invocation. Stderr error
  messages may include proto file paths and FQN type names
  from the analyzed schemas; operators treating these as
  sensitive should redirect stderr to a secured log sink.

**Profile composition observability**

- R25. The CLI emits a one-line stderr provenance note before
  running when **two or more rule packs are loaded** (REVISED
  during D3 brainstorm pressure-test pass — original
  unconditional emission was speculative future-proofing with
  zero D3 user benefit and three-persona consensus to gate).
  When `len(loaded_packs) >= 2`, the line lists each pack and
  its contributing rule_ids:
  `protokit lint: profile 'default' from
  protokit.schema.lint.rules.naming=[naming/snake-case-fields];
  acme.lint_rules=[acme/no-leading-underscore]`. The line uses
  full module names (R8) so users can spot dual-loading (e.g.,
  the user's `naming` module being a different pack than the
  built-in `protokit.schema.lint.rules.naming`). Rule_ids are
  rendered verbatim (no prefix stripping). Suppressed under
  `--quiet`. **Single-pack case (D3 default with no
  `--rule-pack`): no provenance line emitted** — the user is
  not composing anything; printing the "composition mechanism"
  for a non-composition is noise. Reversibility-favorable: the
  threshold is one constant in the CLI; promoting back to
  unconditional-emit is a one-line change if a real
  multi-pack-mechanism-discoverability complaint surfaces.

  *Source for per-pack rule_ids*: reuse R11's pre-computed
  introspection dict (extending it from "profiles-by-pack" to
  "rule_ids-by-pack") rather than reaching into engine
  internals. One CLI-side data structure shared by R11 and
  R25 — `pack_to_active_rules: dict[str, list[str]]` built
  by iterating each loaded pack's `RULES` and intersecting
  with the resolved `profile.rule_ids`.

## Success Criteria

- `protokit lint a.descriptor_set` runs the auto-loaded `naming`
  pack against `a.descriptor_set`'s root files, prints
  human-readable findings (one per line), exits 0/1/2 per R20.
  No `--statistics` footer by default (R16 revised — opt-in
  via explicit `--statistics`).
- `protokit lint --proto foo.proto -I src/` compiles `foo.proto`
  through the D1 `compile_protos_to_result` entry, runs auto-loaded
  rules, behaves identically to descriptor-set mode otherwise.
- `PROTOKIT_FORMAT=json protokit lint a.descriptor_set`
  produces JSON-formatted lint output and exits 0/1 per the
  R20 ladder (D3 absorbed D4's machine formatters per KD-5
  revised; `json`/`junit`/`sarif` all resolve in D3).
  `--format=does-not-exist` exits 2 with stderr beginning
  `error[lint-format-unavailable]:` listing the four
  available formatter names from
  `list_formatters(FormatterKind.LINT_REPORT)`.
- `protokit lint --rule-pack=test_pack_with_zero_rules
  a.descriptor_set` (a user pack with empty `RULES`) exits 2
  with `error[lint-no-rules]:` and lists `--rule-pack`
  troubleshooting hints. (Note: `--no-builtin-rules` is
  deferred to D6 per R7 revised — the only D3 path to
  zero rules is via `--rule-pack`s that all declare empty
  `RULES`.)
- `protokit lint --profile typo a.descriptor_set` exits 2 with
  "profile 'typo' matched 0 rules across loaded packs" and lists
  the profile names each pack declares.
- `protokit lint --max-warnings 0 a.descriptor_set` exits 1 when
  any WARNING-severity finding fires, exits 0 when none do.
  Independent of ERROR-severity behavior.
- Cold-import smoke step (D1's CI gate) extended to cover the
  lint CLI module: `python -c "import protokit.schema; ..."` must
  not transitively load `protokit.schema.lint.cli` or
  `protokit.formatters._builtin_lint`.
- All existing tests stay green; no compat / diff / hook test
  changes required.
- Existing `formatters/_registry` tests that enumerate
  `FormatterKind` values gain a `LINT_REPORT` case (e.g.,
  parametrize over `FormatterKind` including `LINT_REPORT`).
  The existing `test_all_four_kinds_present` test (asserts the
  exact set {`DIFF`, `COMPAT`, `COMPAT_HISTORY`,
  `COMPAT_BISECT`}) is updated to assert the five-kind set
  including `LINT_REPORT`. `list_formatters` / `get_formatter`
  tests continue to pass for the four pre-existing kinds.
- New tests cover: each input mode, each flag, each exit code,
  each of the 10 stable error-prefix codes
  (`error[lint-no-rules]:`,
  `error[lint-unknown-profile]:`, `error[lint-format-unavailable]:`,
  `error[lint-compile-failed]:`, `error[lint-formatter-exception]:`,
  `error[lint-bad-input]:`, `error[lint-pool-conflict]:`,
  `error[lint-missing-imports]:`, `error[lint-rule-collision]:`,
  `error[lint-rule-pack-load]:`), each loud-failure path, the
  cold-import quarantine, R25 composition-stderr provenance
  (multi-pack only — single-pack is silent per R25 revised),
  R24 descriptor-set ingestion (single + multi-path +
  duplicate filename + cross-set symbol collision +
  missing-imports discrimination).

## Scope Boundaries

**Out of scope for D3:**

- Git input modes (`--since`, `--against-base`) — deferred. Reuse
  `_load_pools_git` + `_validate_git_mode_flags` from compat when
  they land in a future delivery; no D3 work to prepare for them.
- pyproject `[tool.protokit.lint]` config — next delivery
  (formerly D5; renumbered after D4 absorption — see KD-5).
  D3's flags are the only configuration channel; CLI defaults
  cannot be overridden by pyproject yet.
- `--ignore PATH` suppression flag — deferred to next-delivery
  (pyproject config). Co-design with `[tool.protokit.lint]
  exclude` globs; per-variant `LintLocation` match-target is a
  design question the pyproject config will need to resolve
  anyway.
- `--no-builtin-rules` flag (R7) — **deferred to D6** when the
  second built-in pack lands. The flag's user-visible value at
  D3 is admitted-near-zero (the same effect is reachable via
  `--rule-pack mypkg` with a pack that doesn't redeclare
  built-in rule_ids). Standard just-in-time pattern; D3 has no
  users to break by deferring. R9 zero-rules loud failure
  remains for the case where all loaded `--rule-pack`s declare
  zero rules under the active profile.
- `LintRuntimeWarning.emit_count_before_exception` (REL-03,
  R21) — deferred to **future delivery**. Was originally
  deferred to D4 because the formatter is the only consumer;
  D4 is now absorbed but R21 still requires extending D2's
  frozen type plus engine instrumentation, and no concrete
  consumer is asking for it. Land when a real per-rule
  emit-count debugging need surfaces.
- `--disable-rule RULE_ID` / `--override-rule-pack` shadowing
  escape valves — deferred. D3 documents the
  `DuplicateRuleError` contract and the
  `--no-builtin-rules + --rule-pack` workaround in R8 +
  Sibling-Parity Audit.
- Additional built-in rule packs beyond `naming` — D6.
- Plugin API parity with compat / `--lint-rule-pack` flag aliases
  / `--compat-rule-pack` rename — D7.
- Inline `protokit:ignore` source comments — Phase 3.
- Auto-fix via proto-schema-parser — Phase 3.
- Sub-grouping `protokit lint check`-style nesting (R1).
- "Old vs new" two-input lint mode (R2: lint takes one input set).
- `--type` narrow-to-one-message-type flag (compat-only concept).
- `--dedupe-by-type` (compat-only concept; lint emits at
  defining sites, not at every reference path).
- `--formatter-module` for user formatter packs — deferred until
  D4 establishes the lint-formatter API surface.
- `--max-findings-of SEVERITY=N` generalized gating — deferred
  until D6+ ships INFO-severity rules where the asymmetry
  matters.

## Key Decisions

**KD-1. Register `human` via the formatter registry, not inline.**
Selected over the strict-minimal "inline throwaway renderer"
shape and over the fused D3+D4 "all four formatters at once"
shape. Rationale: zero throwaway code; D4 becomes purely
additive; the cold-import contract is preserved by NOT adding
`_builtin_lint` to the eager-load tuple. Cost: D3 must touch
`FormatterKind` to add `LINT` and must prove the deferred-load
pattern works. Both are small and verifiable.

**KD-2. Auto-load built-in rule packs by default.**
Selected over "explicit `--rule-pack` only" and over "auto-load
unless --rule-pack is passed". Rationale: matches user
expectations from buf lint / api-linter / protolint — running
`protokit lint` should produce lint output. Cost: introduces
`--no-builtin-rules` opt-out flag (one new flag) and a small
divergence from compat (compat has no auto-load concept because
its built-in checks are compiled into `SchemaChecker`, not packs).
The divergence is intentional and documented in the audit.

**KD-3. Profile resolution composes across loaded packs.**
Selected over per-pack `--profile naming/default` syntax and over
"defer profiles to D5 entirely". Rationale: D2 already shipped
`LintProfile.compose` and `from_pack` precisely for this fan-out.
A single `--profile NAME` that unions across packs is the
simplest user-facing surface that uses both primitives. D5's
pyproject config will override the CLI default; the CLI shape
stays stable.

**KD-4. Loud failure on zero-rule and unknown-profile cases.**
Both routes through R9/R11 produce exit 2 with stderr text. The
alternative (silent empty-findings report) is a footgun for CI
users — a typo in `--profile` would yield green CI on any input.
Loud failure is the user-correcting path; cost is a few extra
test cases and stderr-message wording.

**KD-5. D3 ships full CLI surface: gating flags + all four
formatters together (REVISED).** `--max-warnings`,
`--statistics`, `--min-severity` all ship in D3
(`--ignore` deferred to D5 — see Scope Boundaries). All
four lint formatters (`human`, `json`, `junit`, `sarif`)
ship together in D3 via `_register_builtin`; the original
"D4 — machine formatters" delivery is absorbed (see Slicing
Rationale Revisited above). Engine-side substrate exists
(`filtered_count`, `runtime_warnings`); per-severity counts
are computed CLI-side at render time by iterating
`report.findings` (there is no precomputed `severity_counts`
field on `LintReport`). Rationale for absorbing D4: shipping
half-formatter parity damaged the identity bet — the
"D3 = exit-code gating; D4 = machine output" staging put
the contradiction in front of every CI user during the
D3-only window. Full-formatter parity at D3 closes the gap.
Cost: D3's delivery scope grows by three formatter
implementations (`json`, `junit`, `sarif`) plus their tests;
D4's slot in the roadmap is absorbed and the next delivery
becomes pyproject config (formerly D5).

**KD-6. Mirror compat's exit-code ladder, extend with --max-warnings.**
0/1/2 stays uniform. `--max-warnings` adds an internal axis
(WARNING count vs N) but the externally-visible ladder is
unchanged. INFO-severity findings never gate exit code (they're
advisory by D2's contract).

**KD-7. Defer git input modes.**
Selected over "all four modes Day-1" and over "skip --since but
keep --against-base". Rationale: descriptor-set + `--proto` cover
the dogfood path. The "git diff | xargs protokit lint --proto"
workaround has known sharp edges (deleted files, missing
transitive imports in `-I`, descriptor-set users get nothing) —
it's a stopgap, not a clean solution. The git scaffolding from
compat (`_load_pools_git`, `_validate_git_mode_flags`) is
reusable, so a later delivery picks the modes up cheaply.
Release notes should explicitly call git modes out as
"coming next" so CI users with incremental-lint needs know to
either wait or accept the workaround's limitations.

**KD-8. Fold AC-05 + AC-06 from D2 ce:review residuals; defer REL-03 + PERF-01.**
**AC-05** (`ctx.pool` mutation contract docstring) and **AC-06**
(tighten `LintRuleError` catch-tuple docstring) are
documentation-only — both fold cleanly into D3 since CLI users
are the first non-test consumers who benefit. **REL-03**
(`emit_count_before_exception` field) is deferred to D4 —
originally drafted as fold-in but second-pass review surfaced
that it requires three coupled changes (frozen D2 type
extension, `_invoke_rule` engine work, formatter rendering
wiring) and the only consumer is the formatter system D4
delivers. Lands cleaner alongside json/junit/sarif than as a
D3 carry-along. **PERF-01** (engine closure hoist) is engine-
only and unrelated to D3's surface; deferred to D5's perf gate
per the D2 plan. The same "don't extend D2's frozen
`LintRuntimeWarning.category` Literal in D3" principle drove
two further deferrals during the second-pass review: R12's
`min_severity_relaxed` warning emission moved to D5 (its first
real caller arrives with pyproject), and R24's
`duplicate_root_file` audit signal was rerouted to a CLI
stderr line (no `LintRuntimeWarning` emission). The Literal
type stays at its D2-locked two values through the entire D3
delivery.

**KD-9. D3 establishes `BUILTIN_PACKS` anchor; auto-load
promotion policy decision deferred to D6 (REVISED).**
Today (D3) the auto-load list contains exactly one pack:
`naming`. The structural anchor (`BUILTIN_PACKS` constant +
membership-pin test in `tests/schema/lint/test_builtin_packs.py`)
ships in D3 to make the surface discoverable and to force
explicit intent for any future change. **The promotion
policy itself — whether D6+ packs default to opt-in
registered (auto-load is conservative) or default to
auto-loaded (auto-load is opinionated) — is a D6 brainstorm
decision when concrete evidence about user expectations is
available**. Original D3 framing committed to "default
opt-in" by analogy to buf/api-linter, but those tools earned
that posture from production upgrade-pain incidents that
protokit-lint has no evidence base for yet. The opposite
policy (opt-out: auto-load by default, users disable noisy
ones) is plausibly what early dogfood users want for
maximum coverage on a new tool. D6's brainstorm decides
based on real signal, not analogy.

*Q1 resolved inline*: the auto-load list lives on
`src/protokit/schema/lint/rules/__init__.py` as a typed
module-level constant
`BUILTIN_PACKS: tuple[ModuleType, ...] = (naming,)` (option (b)
from the original Q1 framing). This makes KD-9 an anchor on a
public, discoverable surface — users and contributors can
introspect `protokit.schema.lint.rules.BUILTIN_PACKS` at runtime
to answer "is pack X auto-loaded?" without reading source. A
docstring on the constant binds membership changes to a
major-version event with CHANGELOG entry. Cold-import
preserved: `protokit.schema.lint.rules.__init__.py` is loaded
only when something inside the lint subpackage imports it (no
external code touches it during `import protokit.schema`).

*KD-9 enforcement honesty*: the membership-pin test in
`tests/schema/lint/test_builtin_packs.py` enforces the
*test-must-be-updated-when-`BUILTIN_PACKS`-changes* invariant
— a structural CI gate that forces explicit intent for any
change to the auto-load tuple. The test does NOT enforce
"CHANGELOG entry in the same commit"; that remains a soft
norm enforced via PR review. Promotion to a hard CHANGELOG
gate (a pre-commit/CI hook diffing `BUILTIN_PACKS` ↔
`CHANGELOG.md`) is correctly deferred until the second pack
is added (D6) — the carrying cost of the hook substrate
exceeds present value at one pack.

**KD-10. Unit staging: every D3 unit lands a runnable
`protokit lint`.** Selected over the original "Unit 2 ships
scaffold-only" framing. After D2, the project's pattern is
"land units incrementally to `main` for review tractability".
That worked for D2 because every D2 unit was library-only —
no user-facing surface appeared mid-delivery. D3 Unit 2 is
the inflection point because it registers the `protokit lint`
click subcommand on the top-level CLI group, making the
command appear in `protokit --help` and shell tab-completion
the moment it merges. To keep `main` healthy throughout the
remaining delivery, each unit must end in a state where
`protokit lint <input>` produces defensible output — even
if successive units add user-visible knobs around it.

Concretely:

- **U2 lands a minimal end-to-end pipeline** with hard-coded
  defaults: iterate `BUILTIN_PACKS` to auto-load the canary
  pack, derive the active profile via
  `LintProfile.from_pack(naming, "default")`, run
  `engine.run`, and render via the `lint_human` formatter.
  After U2 merges: `protokit lint a.descriptor_set` actually
  produces a findings list. U2's surface is "the default case
  works"; the only user-visible flags are `--proto` and
  `-I`/`--proto-path` from R4.
- **U3 introduces configurability** by refactoring U2's
  hard-coded auto-load + profile derivation into the
  flag-driven version: adds `--rule-pack`, `--profile`,
  `--min-severity`, plus the R9/R11 loud-failure paths and
  R25 provenance line (gated on `len(loaded_packs) >= 2`).
  R7 `--no-builtin-rules` deferred to D6. After U3 merges:
  zero-flag invocation behavior is unchanged from U2; users
  gain the configuration knobs.
- **U4 adds CI gating + output-shape control**:
  `--max-warnings`, `--statistics`/`--no-statistics`,
  `--quiet`, `--format`, the exit-code ladder (R20), and the
  format-unavailable error path. After U4 merges: `protokit
  lint` with no flags continues to behave exactly as it did
  after U3 (R16 `--statistics` is default-OFF, so no
  footer noise on bare invocation);
  CI users gain the gating surface.
- **U5 stays as written**: D2 docstring fold-ins (R22, R23),
  end-to-end integration tests, CI cold-import gate
  extension.

The forcing function (REVISED with checkable invariants
during round-2 pressure-test pass — replaces the original
"defensible output" framing which was too vague to enforce):

Three checkable invariants every unit must preserve:

1. **Exit-code stability for canary inputs**: `protokit
   lint <descriptor_set>` exits 0 or 1 (never 2 from
   internal CLI errors) for inputs the auto-loaded
   `naming` canary handles cleanly. From U2 onward.
2. **Cold-import smoke remains green**: `import
   protokit.schema` does NOT load
   `protokit.schema.lint.cli` or
   `protokit.formatters._builtin_lint`. From U1 onward
   (U1 already shipped with this preserved).
3. **Subcommand discoverability**: `protokit --help`
   lists `lint` with a non-empty short-help string. From
   U2 onward.

Successive units may legitimately add advertised behaviors
(R25 provenance line, statistics footer, exit-code gating,
new flags) — those are not regressions and do not violate
the invariants above. This is *not* a byte-stability
contract on zero-flag stdout — that would over-constrain
U3/U4's legitimate additions.

Tradeoff: U2's plan-text grows by ~6 lines of code (engine
instantiation + load_rule_pack + from_pack + run +
formatter call + echo). U3 reframes from "add rule loading"
to "lift hard-coded defaults into flags". The total work is
the same; the unit boundaries shift to match what `main`
can defensibly carry between landings.

## Sibling-Parity Audit (per `audit-wire-format-before-claiming-sibling-parity-2026-05-03`)

The 3-layer check (signature, wire format, operational semantics)
across every "mirrors compat" claim in TODOS.md:103-114:

| Aspect | compat | lint (D3) | Divergence kind |
|---|---|---|---|
| Subcommand shape | `protokit compat check` (sub-group) | `protokit lint` (single command) | **Signature** — lint is flat, compat is nested. |
| Positional inputs | OLD + NEW (two paths) | one or more paths | **Signature** — lint is single-input. |
| `--proto` flag | switches to source mode | switches to source mode | Same. |
| `-I` / `--proto-path` | repeatable | repeatable | Same. |
| `--rule-pack MODULE` | `RULES = ((rule_id, fn), ...)` | `RULES = (decorated_fn, ...)` | **Wire format** — same flag name, incompatible payloads. **D7's brainstorm MUST evaluate three options** (REVISED during round-2 pressure-test — the original "permanent divergence + rename in D7" framing was unfalsifiable directional commitment foreclosing the convergence design path before evaluation): (a) rename compat's flag to `--compat-rule-pack` (preserves divergence syntactically; current direction); (b) converge wire formats via a unified `@rule(kind='lint'\|'compat')` decorator with compat's tuple form deprecated-but-supported; (c) accept permanent divergence and document as such. Until D7 lands, `lint-rule-pack-load` error message text discriminates the two formats explicitly so users hitting the divergence get a diagnostic that points at the wire-format issue. The directional commitment is reframed as "D7 evaluates options"; the choice itself waits for D7's brainstorm with concrete user-pack-ecosystem evidence. |
| Profile selector | `--level wire/consumer-safe/producer-safe/strict` | `--profile NAME` (default `"default"`) | **Operational semantics** — compat's level is a closed enum baked in; lint's profile is per-rule-pack and composes. |
| Auto-load built-ins | not applicable (built-ins compiled in) | yes; `--no-builtin-rules` opt-out deferred to D6 (R7 revised) | **Operational semantics** — lint introduces auto-load; opt-out flag earns its keep when second pack lands. |
| `--max-warnings N` | n/a (binary "any incompatibility = exit 1") | new in lint | **New** — lint-only flag. |
| `--min-severity LEVEL` | n/a (`--level` controls *which findings exist*, not severity floor) | new in lint | **New** — lint-only flag. |
| `--statistics` | n/a (compat output is compact) | new in lint | **New** — lint-only flag. |
| `--ignore PATH` | dotted message-path prefix filter | n/a in D3 — deferred to D5 alongside pyproject `exclude` | **Absence (temporary)** — co-design with config rather than ship a CLI-only path-filter today. |
| Rule shadowing | silent shadowing — second pack's same `rule_id` registers, both fire | `DuplicateRuleError` raised at `engine.load_rule_pack` time | **Operational semantics + behavior** — same wire (loading two packs with overlapping ids); compat tolerates, lint refuses. Escape valve: `--no-builtin-rules + --rule-pack` to reimplement. |
| Auto-load upgrade safety | n/a | `BUILTIN_PACKS` constant + membership-pin test ship in D3 as the structural anchor; promotion policy decision deferred to D6 (KD-9 revised) | **New** — lint introduces an upgrade-safety substrate compat does not need (compat has no rule-pack auto-load). The policy itself (opt-in vs opt-out by default) is deferred until D6 has concrete user-expectation evidence. |
| `--dedupe-by-type` | exists (path-completeness opt-out) | n/a (lint emits at defining sites only) | **Absence** — flag deliberately not present in lint. |
| `--type NAME` | narrows to one message type | n/a | **Absence** — lint walks the whole root-files set. |
| `--quiet` | exists | exists, mutex with non-human formats | Same shape. |
| `--format NAME` | `human` / `json` / `junit` / `sarif` | `human` / `json` / `junit` / `sarif` (D3 absorbs D4 — see KD-5) | **Same** — full-formatter parity at D3. |
| `PROTOKIT_FORMAT` envvar | yes | yes | Same. |
| Exit codes | 0/1/2 ladder | 0/1/2 ladder, with internal `--max-warnings` axis | Same external ladder. |
| `FormatterKind` | `DIFF` / `COMPAT` / `COMPAT_HISTORY` / `COMPAT_BISECT` | + `LINT_REPORT` (new fifth value) | **Additive** — extends the enum. |
| `--formatter-module` | exists | deferred to future delivery | **Absence** — D3 absorbed the formatter delivery (KD-5 revised); user-formatter-pack support deferred until plugin API parity (formerly D7). |
| Git modes | `--since` / `--against-base` | n/a in D3 | **Absence** — temporary, future delivery. |
| Cold-import contract | `import protokit.schema` does not load `lint` | preserved in D3 | Same. |

Net assessment (REVISED after D3 brainstorm pressure-test):
D3 introduces 3 new flags (`--max-warnings`, `--min-severity`,
`--statistics` default-OFF); reuses `--profile` with different
semantics from compat's `--level`; diverges on `--rule-pack`
wire format and on rule-shadowing behavior (compat silently
shadows; lint raises `DuplicateRuleError`); omits 6 compat
flags by design or deferral (`--type`, `--dedupe-by-type`,
git modes, `--formatter-module`, `--ignore`,
`--no-builtin-rules` deferred to D6); preserves 4 mirrors
verbatim (`--proto`, `-I`, `--quiet`, `PROTOKIT_FORMAT`).
Every divergence is intentional and explained in Key
Decisions or Scope Boundaries above; none of them silently
differ in a way that would surprise a user who already knows
compat. **D3 ships full-formatter parity with compat
(`human`/`json`/`junit`/`sarif`), so no `PROTOKIT_FORMAT`
cross-subcommand gap exists** — the original D3-only-human
window is closed by absorbing D4 into D3 (KD-5).

## Dependencies / Assumptions

- D2 engine + canary landed and on `main` (verified per memory:
  commits `26bd312`...`a0b7692`, all on main as of 2026-05-03).
- `protokit.schema.compile.compile_protos_to_result` from D1 is
  the source-mode compile entry point — D3 reuses it for `--proto`.
- `protokit.formatters._registry` exposes `FormatterKind`,
  `register_formatter`, `get_formatter`, `FormatterError` — all
  public per Phase 1.5b's promotion.
- The cold-import smoke test pattern in CI is extensible (D1
  established it).
- Click is the CLI framework (compat uses it; the top-level CLI
  group at `src/protokit/cli.py` is click).
- No new dependencies beyond what D2 already has. `tomli` is
  the next delivery's (pyproject config), not D3's.

**Why the cold-import contract matters** (added during
D3 brainstorm pressure-test pass — the contract was invoked
5x as a load-bearing constraint without an articulated cost
of violation):

`import protokit.schema` is the entry point downstream
library consumers use when they want lint's
`CompileResult` / `LintReport` types without paying for the
CLI subcommand machinery. D1's brainstorm identified
`protokit-coverage` (a downstream tool that imports
`protokit.schema` to consume `CompileResult` for
schema-coverage analysis) as the concrete consumer; the
imported subpackage stays small (model + decorator + engine,
no click, no formatter registry) so library users don't pay
~30ms of click + formatter eager-load every time they
`import protokit.schema`. That cost is small in absolute
terms but compounds in test suites that import the package
hundreds of times. The contract also keeps the CLI surface
isolated from the library surface — a refactor that
accidentally pulls click into `protokit.schema` would be
a measurable regression for the downstream consumer. The
membership-pin smoke test in CI catches such regressions
structurally.

**Lint-side formatter wrapper design** (REVISED during
round-2 pressure-test pass — the original "share OR
duplicate" framing was a punt that left security substrate
consistency to planner judgment):

`protokit._cli_utils.run_formatter_safely` provides four
distinct security-relevant guards (SystemExit, generic
Exception, stdout-leak, non-str return) that all lint
formatters need. The lint-side wrapper that produces
`error[lint-formatter-exception]:` prefix MUST share
`run_formatter_safely`'s body via an `error_exit_fn`
parameter — the refactor is small (signature change + all
callers updated, single PR) and the security-substrate
consistency benefit is durable. **Duplication is rejected**
unless the planning-stage refactor demonstrably introduces
>50 lines of churn in compat OR breaks a Phase-1.5b-locked
public signature; the planner must justify duplication
against this criterion, not choose freely between
equivalent options. Sharing is the default; duplication
requires written justification.

## D3-Present Security Risks

Risks that are present in D3 (not deferred to a future
delivery) and that the implementation must address:

- **`--rule-pack MODULE` is a D3-present code-execution
  channel.** R8's `importlib.import_module(MODULE)` evaluates
  arbitrary user Python at import time. D3 trusts the local
  operator (the user typing the flag = the user running the
  CLI). **In CI pipelines where `--rule-pack` is interpolated
  from YAML/Makefile config that is not root-operator-controlled,
  the trust assumption silently degrades to whoever can write
  that config.** Operators using `--rule-pack` in CI must
  ensure MODULE values come from a vetted, pinned source —
  not interpolated from user-supplied or PR-author-controlled
  inputs. D3 keeps the channel a single, well-named importlib
  edge so the trust boundary is greppable; the brainstorm
  doc names the operator responsibility explicitly so
  implementors know to mention it in user-facing
  documentation.
- **Format-injection in `template_str.format(**finding.params)`
  is D3-present**, not D6-future. R8 lets users load `--rule-pack`
  modules in D3, and those modules control `LintRuleSpec.message_template`
  strings. The `lint_human` formatter calls
  `template_str.format(**finding.params)` with the
  user-controlled template. Width specifiers
  (`{name:>1000000000}` → multi-GB string memory DoS) and
  attribute traversal (`{name.__class__.__mro__}` walks
  Python type hierarchy → information disclosure about
  internal types) are reachable today. **D3 mitigations**:
  (a) widen the Unit 1 try/except catch tuple in
  `_builtin_lint.py:_render_message` to include `MemoryError`
  and `RecursionError` so a width-specifier DoS attempt
  doesn't crash the formatter mid-render and drop subsequent
  findings (cheap defensive fix, lands in this delivery's
  source edits); (b) document the D3-present trust assumption
  ("`--rule-pack`-supplied templates run with the operator's
  privileges; only load packs from trusted sources"). The
  TODO(D6) marker on the format call carries the holistic
  plugin-security design (whitelist of safe format specs
  vs. safe-eval substitute) forward to D6 when user
  ecosystems form, but the present-D3 hardening lands now.

## Forward-Looking Risks (Future Deliveries)

These do not change D3 mechanics. Recorded so future-delivery
brainstorms inherit the context.

- **Pyproject trust surface (next delivery).** When
  `[tool.protokit.lint] rule_packs = [...]` lands in the
  pyproject config delivery (formerly D5), rule_pack values
  become "trust-the-pyproject-checked-into-the-repo" data —
  anyone with push access controls a code-execution config.
  **The next-delivery brainstorm MUST answer "what is the
  allowlist/integrity strategy for `rule_packs` entries"
  before any implementation lands**. Candidate mechanisms to
  evaluate: (a) explicit `trusted_rule_packs = [...]` allowlist
  separate from the auto-load list, (b) hash-pin the module
  distribution to a known-good version, (c) require a
  first-use confirmation prompt with human-actionable
  messaging. At minimum, do not ship pyproject `rule_packs`
  without choosing one of these.
- **Plugin API trust surface (D7).** A formalized third-party
  rule_pack distribution channel widens trust further. D7's
  brainstorm must include a holistic plugin security review
  starting from a clean threat model rather than inheriting
  D3's "local operator trust" assumption transitively.

## Verified Codebase Context

- `src/protokit/cli.py:20-27` — top-level click group with `diff`
  and `compat` subcommands. D3 adds a third `lint` subcommand to
  this group.
- `src/protokit/schema/cli.py:583-737` — compat's `check`
  subcommand. Used as the structural template for lint's
  argument shape; D3 does NOT subclass or import from this
  module.
- `src/protokit/formatters/__init__.py:60-71` — eager-load tuple
  for built-in formatter modules. D3 adds neither
  `_builtin_lint` nor any other lint module to this tuple
  (cold-import preservation).
- `src/protokit/formatters/_registry.py` — `FormatterKind` enum.
  D3 adds `LINT_REPORT` as the fifth value (per the
  `_registry.py:41-42` noun-form convention).
- `src/protokit/schema/lint/model.py:75-115` — `LintSeverity`
  enum (INFO/WARNING/ERROR) and `_SEVERITY_RANK` map. D3 maps
  `--min-severity LEVEL` choice values to these.
- `src/protokit/schema/lint/model.py:499-665` — `LintProfile`
  + `compose` + `from_pack`. D3 is the first CLI consumer.
- `src/protokit/schema/lint/rules/naming.py:79` — `RULES =
  (check_snake_case_fields,)`. The single auto-loaded built-in
  pack at D3 ship time.
- `src/protokit/schema/lint/engine.py` — `LintEngine` D2 ship.
  D3 instantiates it once per CLI invocation (no caching).
- D2 ce:review residual artifact:
  `.context/compound-engineering/ce-review/20260503-001657-4c4467d1/`
  — AC-05/AC-06 are folded in (R22/R23); REL-03 (R21) is
  deferred to D4 (formatter delivery is the only consumer);
  PERF-01 remains deferred per KD-8.
- **Unit 1 inline addition** (already on `main` per
  `c610dae` + ce:review follow-ups `50acd02`, `75b2430`):
  `LintReport` gained an additive `specs: Mapping[str,
  LintRuleSpec]` field, frozen post-construction via
  `MappingProxyType`. Engine populates it from
  `self._loaded_specs` at return time. The `lint_human`
  formatter consumes `report.specs[finding.rule_id].message_template`
  for message rendering; the additional machine formatters
  (`lint_json`/`lint_junit`/`lint_sarif`, shipped in D3 per
  KD-5 revised) use the same channel. U4's `--statistics`
  footer does NOT read `specs` (per-severity counts come
  from iterating `report.findings`).
- **Unit 1 format-injection TODO** (in
  `_builtin_lint.py:_render_message`): the
  `template_str.format(**finding.params)` call ships
  user-controlled-template support in D3 once R8's
  `--rule-pack` flag lands in U3. The trust boundary is
  D3-present (not D6-deferred) — see "D3-Present Security
  Risks" section. The Unit 1 module docstring (currently
  saying "D3 ships human only. D4 will extend...") is stale
  after the D4-absorption decision and is updated as part
  of U4's scope (alongside the three new formatter
  registrations). The TODO(D6) on the format() call carries
  forward the holistic plugin-security model design (template
  whitelist/sandbox), which remains future-delivery work.

## Outstanding Questions

### Resolve Before Planning

- **Q1. Where does the auto-load list of built-in rule packs
  live?** — RESOLVED inline at KD-9: option (b) —
  `BUILTIN_PACKS: tuple[ModuleType, ...] = (naming,)` on
  `src/protokit/schema/lint/rules/__init__.py`. Public,
  discoverable, anchors the upgrade-safety contract.
- **Q2. Default value of `--max-warnings`** — RESOLVED:
  `Optional[int] = None`. Click idiom is
  `click.option("--max-warnings", type=int, default=None)`;
  the callback branches on `max_warnings is None` to short-
  circuit the WARNING-count gate. No sentinel value needed.
  Compat has no analogous flag, so this sets a fresh convention
  rather than mirroring one.
- **Q3. `--statistics` interaction with `--quiet`** — RESOLVED
  inline at R18: `--quiet` always wins, with a click-level
  warning if both are passed simultaneously. No remaining
  ambiguity.

### Deferred to Planning

- Concrete click decorator wiring and option ordering — planning
  decides flag order, help text wording, and whether to use
  `click.Choice` vs `click.STRING` for `--profile` (the latter
  defers the validation to runtime, allowing user-defined
  profile names from packs).
- Test fixture layout for the new CLI tests.
- Whether the lint subcommand has its own `_cli_utils.py`-style
  helper module or shares compat's. (Lean: separate file —
  `src/protokit/schema/lint/_cli_utils.py` — since lint's input
  shape is single-input vs compat's two-input.)
- Specific stderr message wording for R9/R11/R13 loud-failure
  paths.
- Test coverage of every flag combination under `--quiet`.

## Next Steps

Hand off to `/ce:plan` with this requirements doc. Unit
decomposition (5 units, matching D2's granularity for an
effort=M delivery; Unit 1 already shipped on `main` per
commits `c610dae` + `50acd02` + `75b2430`). Per KD-10, every
unit lands in a state where `protokit lint <input>` produces
defensible output:

1. **[SHIPPED] Formatter substrate + auto-load list anchor** —
   `FormatterKind.LINT_REPORT` enum value added to `_registry.py`;
   `src/protokit/formatters/_builtin_lint.py` created with
   `_register_builtin` of the `human` lint formatter named
   `lint_human` (R14, R15); `BUILTIN_PACKS = (naming,)`
   constant added to `src/protokit/schema/lint/rules/__init__.py`
   (Q1 resolution + KD-9 anchor). `LintReport.specs:
   Mapping[str, LintRuleSpec]` added inline as a frozen
   `MappingProxyType` field. NOT in eager-load tuple. Tests
   parametrize `FormatterKind` including `LINT_REPORT`;
   `test_all_four_kinds_present` renamed to
   `test_all_kinds_present` and asserts the 5-kind set.
2. **CLI scaffold + minimal end-to-end pipeline** —
   `src/protokit/schema/lint/cli.py` click subcommand
   registered on `protokit/cli.py`'s top-level group;
   positional inputs + `--proto` source mode wired via
   `compile_protos_to_result` (D1) and the new
   `_load_descriptor_sets_to_result` helper (R24, with
   dedupe-before-Add ordering and cross-set symbol-collision
   handling); `_cli_utils.py` with `error_exit_with_code`,
   `_LINT_ERROR_CODES`, and the input-side error codes
   (`bad-input`, `pool-conflict`, `compile-failed`).
   **Hard-coded happy path wired**: iterate `BUILTIN_PACKS`,
   `LintProfile.from_pack(naming, "default")`, `engine.run`,
   render via `lint_human`, `click.echo`. After this unit:
   `protokit lint a.descriptor_set` produces a real findings
   list. Cold-import smoke step extended (R3). Covers R1,
   R2, R4, R24, R20a (helper + initial codes), and the
   default case of R6.
3. **Rule loading configurability + profile resolution** —
   refactors U2's hard-coded auto-load + default profile
   into the flag-driven version: `--rule-pack` with
   full-module-name semantics + shadow contract (R8),
   `--profile` resolution (single-pack from_pack only;
   `LintProfile.compose` lifts back when `--rule-pack`
   actually adds a second pack — see R10 revised),
   R11 behavioral introspection on unknown-profile,
   `--min-severity` as a pure numeric override (no
   `LintRuntimeWarning` emission — deferred to next
   delivery), R9 loud failure. **R7 `--no-builtin-rules`
   deferred to D6**. **R25 provenance gated on
   `len(loaded_packs) >= 2`**. Extends `_LINT_ERROR_CODES`
   with `no-rules`, `unknown-profile`, `rule-collision`,
   `rule-pack-load`, `missing-imports`. After this unit:
   zero-flag invocation behavior is unchanged from U2;
   users gain the configuration knobs.
4. **CI gating + statistics + all four formatters + stable error prefixes** —
   `--max-warnings`, `--statistics` (default-OFF, opt-in),
   `--quiet`, `--format` (resolves all four:
   `human`/`json`/`junit`/`sarif`), exit-code ladder (R20),
   per-severity counts computed CLI-side at render time
   only when `--statistics` passed, lint-side formatter
   wrapper that produces `error[lint-formatter-exception]:`
   (sharing `run_formatter_safely`'s body via an
   `error_exit_fn` parameter, OR duplicating with mirrored
   guards — plan decides). **D3 absorbs D4's machine-format
   formatters**: register `lint_json` / `lint_junit` /
   `lint_sarif` via `_register_builtin` in
   `_builtin_lint.py` alongside `lint_human`. Extends
   `_LINT_ERROR_CODES` with `format-unavailable`,
   `formatter-exception`. After this unit: zero-flag
   invocation behavior is preserved (default-OFF statistics
   means no footer noise); CI users gain the gating + full
   formatter surface.
5. **D2 residual docstring fold-ins (AC-05/AC-06) + integration tests + CI cold-import gate extension** — R22, R23,
   end-to-end coverage of every flag combination, every
   loud-failure path, every stable error-prefix code, the
   cold-import quarantine. **Source-side D3-present
   security hardening**: widen the `_render_message` catch
   tuple in `_builtin_lint.py` to include `MemoryError` +
   `RecursionError` (per Forward-Looking Risks D3-present
   security entry).

D3's delivery shape (after the brainstorm pressure-test
pass): U1 shipped, U2-U5 remain. The "what comes after D3"
roadmap renumbers because D3 absorbed D4's machine
formatters: the next delivery is pyproject config
(`[tool.protokit.lint]`, formerly D5), then more rule packs
(formerly D6 — promotion policy decision lives here per
KD-9 revised), then plugin API parity (formerly D7,
including `--compat-rule-pack` rename per the audit table's
directional commitment). TODOS.md should be updated to
reflect this renumbering before planning begins.
