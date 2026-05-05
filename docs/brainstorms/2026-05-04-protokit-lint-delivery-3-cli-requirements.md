---
date: 2026-05-04
topic: protokit-lint-delivery-3-cli
---

# protokit-lint Delivery 3 — `protokit lint` CLI Subcommand

Created: 2026-05-04
Source roadmap: `TODOS.md` lines 103-114 ("D3 — `protokit lint` CLI subcommand").
Foundation landed: D1 (commits `0b82fc3`, `e85faea`, `31c0bb1`) + D2 engine + canary (commits `26bd312`, `3fe3b8c`, `8c4ba9c`, `329b22f`, `8927d1f`, `b26cb5d`, `3252918`, `a0b7692`).
Sequence: depends on D2; precedes D4 (`_builtin_lint` json/junit/sarif formatters), D5 (pyproject config), D6 (more rule packs), D7 (plugin API).

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

**Slicing rationale revisited.** D2 noted the staged D1→D7 approach
should be revisited after D3+D4 merge. D3 chooses a deliberate
middle path: ship the CLI now, register a `human` lint formatter
through the existing `protokit.formatters` registry (no inline
throwaway renderer), and let D4 add `json`/`junit`/`sarif` by
extending the same `_builtin_lint.py` module. This preserves the
staged-review property while eliminating the awkward
"replace-the-renderer-in-D4" code churn the strict-minimal D3
shape would have created.

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
- R7. `--no-builtin-rules` (boolean flag) opts out of step R6.
  When set, no built-in pack loads; only user packs from
  `--rule-pack` load. *Forward-looking note*: with one built-in
  pack at D3 ship time, this flag's user-visible value is small
  (the same effect can be achieved by `--rule-pack mypkg` with a
  pack that doesn't redeclare `naming/snake-case-fields`). The
  flag exists Day-1 as the *only* opt-out for auto-load (KD-2),
  preserving symmetry now rather than introducing the flag at D6
  when its value materializes.
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
  pair `--no-builtin-rules` with a `--rule-pack` that
  reimplements the desired built-ins under the same or different
  ids. D3 does NOT introduce a `--disable-rule RULE_ID` or
  `--override-rule-pack` escape valve; that is a future-delivery
  concern. The constraint is documented in the audit table so
  users discover it before hitting `DuplicateRuleError`.
- R9. Loud failure when zero rules load. If after R6+R7+R8
  resolution the engine's loaded-rule registry is empty, OR the
  composed active profile (R10) has zero rule_ids, exit code 2
  with stderr text identifying which path was taken
  (`--no-builtin-rules` set without `--rule-pack`, or `--profile X`
  matched zero rules across all loaded packs). Prevents silent
  green CI from misconfiguration.

**Profile resolution**

- R10. `--profile NAME` (string, default `"default"`). Resolution:
  for each loaded pack (built-ins + `--rule-pack`s), call
  `LintProfile.from_pack(pack, name)`; compose all results via
  `LintProfile.compose(*per_pack_profiles)`; pass the composed
  profile to `engine.run`. The composed profile's `rule_ids` is
  the union of every pack's matching rule_ids; `min_severity` is
  the strictest (highest rank); severity overrides merge per
  D2's documented `compose` semantics.

  *Implementation note*: `LintProfile.from_pack` does not propagate
  per-rule severity into the profile-level `min_severity` (it
  uses the dataclass default `LintSeverity.WARNING` per
  `lint/model.py:522`), so composing N `from_pack` profiles
  always yields `min_severity = WARNING` regardless of pack
  declarations. The strictest-wins semantics is exercised only
  when callers construct `LintProfile` directly with non-default
  `min_severity` — e.g., D5's pyproject config. For D3 the
  user-facing knob is R12's `--min-severity`.
- R11. Empty composed profile (no rule_ids match `name` across
  all loaded packs) is the loud-failure case in R9 — exit 2 with
  stderr listing the profile names each loaded pack declares.

  *Introspection mechanism*: after rule loading, the CLI
  computes `declared_profiles_per_pack: dict[str, frozenset[str]]`
  by iterating each loaded pack's module-level `RULES` tuple and
  unioning each `fn._lint_spec.profiles` (via
  `protokit.schema.lint.decorator.get_lint_spec`). The R11
  stderr message renders this dict so users see, e.g.,
  `pack 'mine' declares profiles: {strict, ci}` and can fix the
  typo without re-reading source.
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
  `FormatterKind.LINT_REPORT` discriminator (per the existing
  `_registry.py:41-42` naming convention which recommends noun
  form like `LINT_REPORT` / `SCHEMA_DIFF` for new kinds) (R15).
  For D3 only `human` resolves; `--format json|junit|sarif`
  raises `KeyError` from `get_formatter` (per its documented
  contract at `_registry.py:213-218`). The CLI catches that
  `KeyError` via lint's own helper and routes to
  `error_exit_with_code("format-unavailable", ...)` (R20a) which
  emits stderr beginning `error[lint-format-unavailable]:` and
  lists the available LINT_REPORT formatter names from
  `list_formatters(FormatterKind.LINT_REPORT)`. The error
  text is delivery-agnostic — it lists what IS available, not
  internal roadmap labels. `PROTOKIT_FORMAT` env var support
  matches compat's pattern; the error message explicitly notes
  that `PROTOKIT_FORMAT` is **shared across all `protokit`
  subcommands** and recommends `env -u PROTOKIT_FORMAT protokit
  lint ...` for users whose CI shell exports it for compat
  (which supports json/junit/sarif since Phase 1.5b). This
  cross-subcommand interaction window closes when D4 lands
  matching lint formatters.
- R14. D3 adds `FormatterKind.LINT_REPORT` to the
  `protokit.formatters._registry.FormatterKind` enum. The four
  existing kinds (`DIFF`, `COMPAT`, `COMPAT_HISTORY`,
  `COMPAT_BISECT`) gain a fifth sibling. No existing formatter
  surface changes.
- R15. New module `src/protokit/formatters/_builtin_lint.py`
  registers a `human` lint formatter via the **internal**
  helper `_register_builtin(name="human", fn=_render_human,
  kind=FormatterKind.LINT_REPORT)` (per `_registry.py:183-200`). Using
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
  the eager-load tuple. D4 will extend this same module with
  `json`/`junit`/`sarif` lint formatters under the same
  `FormatterKind.LINT_REPORT` discriminator (per the existing `_registry.py:41-42` naming convention which recommends noun form like `LINT_REPORT` / `SCHEMA_DIFF` for new kinds) (also via
  `_register_builtin`).
- R16. `--statistics` (boolean flag, default ON when
  `--format=human` and not `--quiet`; ignored otherwise) emits a
  human-format footer with: per-severity finding counts
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
    produced `CompileResult.diagnostics` of category `error`.
  - `error[lint-formatter-exception]:` — formatter callable
    raised under `run_formatter_safely`.
  - `error[lint-bad-input]:` — descriptor-set bytes failed to
    parse (R24 helper).
  - `error[lint-pool-conflict]:` — R24 pool.Add raised
    TypeError on a cross-set symbol-level collision (NOT a
    duplicate filename — those are deduped pre-Add).

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

  The stable-prefix list above lives in the help text of
  `protokit lint` (rendered from a module-level
  `_LINT_ERROR_CODES: tuple[str, ...]` constant — single source
  of truth, no help-text drift) so CI authors can reference it
  without reading source.

**D2 ce:review residuals folded in**

- R21. *DEFERRED to D4*. **REL-03** —
  `LintRuntimeWarning.emit_count_before_exception: int = 0` was
  considered for D3 but deferred to D4. Rationale: the field's
  only consumer is the human formatter's runtime-warning footer
  (statistics row "rule X raised after emitting K findings"),
  and D4 owns the formatter ecosystem. Folding it into D3
  required (a) extending a frozen D2 type, (b) modifying
  `_invoke_rule` in `LintEngine` to snapshot per-rule emit
  counts, and (c) wiring the human formatter to render it.
  That's a three-file engine + model + formatter change for a
  field whose only output channel is the formatter being added
  in D4. Cleaner to land it together with the json/junit/sarif
  formatters that also benefit from the structured field.
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

  *Symbol-level collisions across different files* (e.g.,
  `a.descriptor_set` defines `acme.User`, `b.descriptor_set`
  also defines `acme.User` with different fields under a
  different `fd.name`): pool.Add raises TypeError; the helper
  exits 2 with `error[lint-pool-conflict]:` (R20a) listing the
  conflicting input file. This is undefined behavior for the
  lint walk; users must pre-merge or namespace-separate.

**Profile composition observability**

- R25. The CLI emits a one-line stderr provenance note before
  running: `protokit lint: profile 'default' from
  protokit.schema.lint.rules.naming=[naming/snake-case-fields]`.
  When the active profile is composed from ≥2 loaded packs the
  line lists each pack and its contributing rule_ids:
  `protokit lint: profile 'default' from
  protokit.schema.lint.rules.naming=[naming/snake-case-fields];
  acme.lint_rules=[acme/no-leading-underscore]`. The line uses
  full module names (R8) so users can spot dual-loading (e.g.,
  the user's `naming` module being a different pack than the
  built-in `protokit.schema.lint.rules.naming`). Rule_ids are
  rendered verbatim (no prefix stripping). Suppressed under
  `--quiet`. The line fires unconditionally — even on the D3
  one-pack case — to make the composition mechanism visible
  from day one rather than appearing as a "regression" the
  first time a second pack loads.

## Success Criteria

- `protokit lint a.descriptor_set` runs the auto-loaded `naming`
  pack against `a.descriptor_set`'s root files, prints
  human-readable findings (one per line) and a `--statistics`
  footer, exits 0/1/2 per R20.
- `protokit lint --proto foo.proto -I src/` compiles `foo.proto`
  through the D1 `compile_protos_to_result` entry, runs auto-loaded
  rules, behaves identically to descriptor-set mode otherwise.
- `PROTOKIT_FORMAT=json protokit lint a.descriptor_set` exits 2
  with stderr beginning `error[lint-format-unavailable]:` and
  lists the available LINT formatter names from
  `list_formatters(FormatterKind.LINT_REPORT)` (just `human` in D3).
  Verifies the discriminator-error path; D4 will flip this to a
  passing render once `_builtin_lint` adds the additional
  formatters.
- `protokit lint --no-builtin-rules a.descriptor_set` exits 2 with
  a clear "no rules loaded" message and lists `--rule-pack`
  syntax.
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
  each stable error-prefix code (`error[lint-no-rules]:`,
  `error[lint-unknown-profile]:`, `error[lint-format-unavailable]:`,
  `error[lint-compile-failed]:`, `error[lint-formatter-exception]:`,
  `error[lint-bad-input]:`, `error[lint-pool-conflict]:`), each
  loud-failure path, the cold-import quarantine, R25
  composition-stderr provenance (single + multi pack), R24
  descriptor-set ingestion (single + multi-path + duplicate
  filename + cross-set symbol collision).

## Scope Boundaries

**Out of scope for D3:**

- Git input modes (`--since`, `--against-base`) — deferred. Reuse
  `_load_pools_git` + `_validate_git_mode_flags` from compat when
  they land in a future delivery; no D3 work to prepare for them.
- `json`, `junit`, `sarif` lint formatters — D4. D3 ships only
  `human`. The `_builtin_lint.py` module is the shared landing
  zone D4 extends.
- pyproject `[tool.protokit.lint]` config — D5. D3's flags are
  the only configuration channel; CLI defaults cannot be
  overridden by pyproject yet.
- `--ignore PATH` suppression flag — deferred to D5 (R17).
  Co-design with pyproject `[tool.protokit.lint] exclude` globs;
  per-variant `LintLocation` match-target is a design question
  the pyproject config will need to resolve anyway.
- `LintRuntimeWarning.emit_count_before_exception` (REL-03,
  R21) — deferred to D4 where the formatter consumes it.
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

**KD-5. CI gating flags ship Day-1; machine-format outputs land in D4.**
`--max-warnings`, `--statistics`, `--min-severity` all ship in
D3 (`--ignore` deferred to D5 — see Scope Boundaries). Engine-
side substrate exists (`filtered_count`, `runtime_warnings`); 
per-severity counts are computed CLI-side at render time by
iterating `report.findings` (there is no precomputed
`severity_counts` field on `LintReport`, contrary to an earlier
draft of this decision). The incremental review surface is
small and front-loads CI-gating-via-exit-codes (`--max-warnings 0
--quiet` is fully usable for binary CI gating in D3 without
machine output). Tradeoff acknowledged: CI engineers who need
SARIF for code-scanning or JUnit for test-result panels must
wait for D4 — D3+D4 are intentionally staged separately for
review tractability, but the gap is real and should be
explicitly messaged in release notes ("D3 = exit-code gating;
D4 = machine output formats").

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

**KD-9. Auto-load upgrade-safety policy: D6+ packs default to opt-in registered.**
Today (D3) the auto-load list contains exactly one pack:
`naming`. As D6+ adds packs, the default policy is **NOT** to
append them to the auto-load list automatically. Each new pack
ships *registered-but-not-active* by default. Promotion of a
pack into the auto-load tuple is an explicit decision tied to
a major-version release with changelog notes. Users who upgrade
protokit get new packs available via `--rule-pack` opt-in, but
auto-load behavior on previously-green CI does not silently
expand. This decouples "protokit ships a new pack" from "every
user's CI surfaces new findings" — addresses the upgrade-trust
concern surfaced by reviewers comparing protokit-lint to
buf/api-linter (which solved this with explicit version pinning
and opt-in lists). A small, conservative auto-load set (today
just `naming`) compounds well.

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

## Sibling-Parity Audit (per `audit-wire-format-before-claiming-sibling-parity-2026-05-03`)

The 3-layer check (signature, wire format, operational semantics)
across every "mirrors compat" claim in TODOS.md:103-114:

| Aspect | compat | lint (D3) | Divergence kind |
|---|---|---|---|
| Subcommand shape | `protokit compat check` (sub-group) | `protokit lint` (single command) | **Signature** — lint is flat, compat is nested. |
| Positional inputs | OLD + NEW (two paths) | one or more paths | **Signature** — lint is single-input. |
| `--proto` flag | switches to source mode | switches to source mode | Same. |
| `-I` / `--proto-path` | repeatable | repeatable | Same. |
| `--rule-pack MODULE` | `RULES = ((rule_id, fn), ...)` | `RULES = (decorated_fn, ...)` | **Wire format** — same flag name, incompatible payloads. Already documented in D2's plan + learning. |
| Profile selector | `--level wire/consumer-safe/producer-safe/strict` | `--profile NAME` (default `"default"`) | **Operational semantics** — compat's level is a closed enum baked in; lint's profile is per-rule-pack and composes. |
| Auto-load built-ins | not applicable (built-ins compiled in) | yes; `--no-builtin-rules` opts out | **Operational semantics** — lint introduces auto-load, compat has nothing analogous. |
| `--max-warnings N` | n/a (binary "any incompatibility = exit 1") | new in lint | **New** — lint-only flag. |
| `--min-severity LEVEL` | n/a (`--level` controls *which findings exist*, not severity floor) | new in lint | **New** — lint-only flag. |
| `--statistics` | n/a (compat output is compact) | new in lint | **New** — lint-only flag. |
| `--ignore PATH` | dotted message-path prefix filter | n/a in D3 — deferred to D5 alongside pyproject `exclude` | **Absence (temporary)** — co-design with config rather than ship a CLI-only path-filter today. |
| Rule shadowing | silent shadowing — second pack's same `rule_id` registers, both fire | `DuplicateRuleError` raised at `engine.load_rule_pack` time | **Operational semantics + behavior** — same wire (loading two packs with overlapping ids); compat tolerates, lint refuses. Escape valve: `--no-builtin-rules + --rule-pack` to reimplement. |
| `--max-warnings N` upgrade safety | n/a | new built-in packs default opt-in registered, NOT auto-loaded (KD-9) | **New** — lint introduces an upgrade-safety policy compat does not need (compat has no rule-pack auto-load). |
| `--dedupe-by-type` | exists (path-completeness opt-out) | n/a (lint emits at defining sites only) | **Absence** — flag deliberately not present in lint. |
| `--type NAME` | narrows to one message type | n/a | **Absence** — lint walks the whole root-files set. |
| `--quiet` | exists | exists, mutex with non-human formats | Same shape. |
| `--format NAME` | `human` / `json` / `junit` / `sarif` | `human` only in D3; D4 adds the others | **Operational semantics** — same registry, different per-kind population. |
| `PROTOKIT_FORMAT` envvar | yes | yes | Same. |
| Exit codes | 0/1/2 ladder | 0/1/2 ladder, with internal `--max-warnings` axis | Same external ladder. |
| `FormatterKind` | `DIFF` / `COMPAT` / `COMPAT_HISTORY` / `COMPAT_BISECT` | + `LINT` (new fifth value) | **Additive** — extends the enum. |
| `--formatter-module` | exists | deferred until D4 | **Absence** — temporary, will land alongside D4. |
| Git modes | `--since` / `--against-base` | n/a in D3 | **Absence** — temporary, future delivery. |
| Cold-import contract | `import protokit.schema` does not load `lint` | preserved in D3 | Same. |

Net assessment: D3 introduces 4 new flags (`--no-builtin-rules`,
`--max-warnings`, `--min-severity`, `--statistics`); reuses
`--profile` with different semantics from compat's `--level`;
diverges on `--rule-pack` wire format and on rule-shadowing
behavior (compat silently shadows; lint raises
`DuplicateRuleError`); omits 5 compat flags by design or
deferral (`--type`, `--dedupe-by-type`, git modes,
`--formatter-module`, `--ignore`); preserves 4 mirrors verbatim
(`--proto`, `-I`, `--quiet`, `PROTOKIT_FORMAT`). Every divergence
is intentional and explained in Key Decisions or Scope Boundaries
above; none of them silently differ in a way that would surprise
a user who already knows compat. The shared `PROTOKIT_FORMAT`
envvar gap (compat supports json/junit/sarif; lint D3 supports
only human) is documented loud-and-clear at first run via the
`error[lint-format-unavailable]:` stderr code.

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
  D5's, not D3's.

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
  D3 adds `LINT` as the fifth value.
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

Hand off to `/ce:plan` with this requirements doc. Suggested
unit decomposition (5 units, matching D2's granularity for an
effort=M delivery):

1. **Formatter substrate + auto-load list anchor** —
   `FormatterKind.LINT_REPORT` enum value added to `_registry.py`;
   `src/protokit/formatters/_builtin_lint.py` created with
   `_register_builtin` of the `human` lint formatter (R14, R15);
   `BUILTIN_PACKS = (naming,)` constant added to
   `src/protokit/schema/lint/rules/__init__.py` (Q1 resolution +
   KD-9 anchor). NOT in eager-load tuple. Tests parametrize
   `FormatterKind` including `LINT_REPORT`; updates
   `test_all_four_kinds_present` to the five-kind set.
2. **CLI scaffold + input modes** — `src/protokit/schema/lint/cli.py`
   click subcommand registered on `protokit/cli.py`'s top-level
   group; positional inputs + `--proto` source mode wired via
   `compile_protos_to_result` (D1) and the new
   `_load_descriptor_sets_to_result` helper (R24, with
   dedupe-before-Add ordering and cross-set symbol-collision
   handling). Cold-import smoke step extended (R3). Covers R1,
   R2, R4, R24.
3. **Rule loading + profile resolution** — auto-load via
   `BUILTIN_PACKS` (R6), `--no-builtin-rules` (R7), `--rule-pack`
   with full-module-name semantics + shadow contract (R8),
   `--profile` resolution + `LintProfile.compose` + R11
   introspection, R25 composition stderr provenance,
   `--min-severity` as a pure numeric override (no
   LintRuntimeWarning emission — that's deferred to D5), R9
   loud failure.
4. **CI gating + exit codes + statistics footer + stable error prefixes** —
   `--max-warnings`, `--statistics`, `--quiet`, exit-code ladder
   (R20), `error_exit_with_code` helper in
   `lint/_cli_utils.py` + `_LINT_ERROR_CODES` constant + stable
   prefix codes (R20a), per-severity counts computed CLI-side
   at render time, R16 footer.
5. **D2 residual docstring fold-ins (AC-05/AC-06) + integration tests + CI cold-import gate extension** — R22, R23,
   end-to-end coverage of every flag combination, every
   loud-failure path, every stable error-prefix code, the
   cold-import quarantine.

After D3 lands, the slicing-rationale revisit point from D2's
brainstorm is reached. At that moment evaluate: did the staged
review approach pay off, or should D5 + D6 fuse to compress
remaining deliveries? D4 (machine-format formatters) is
expected to land in close sequence with D3 to close the
exit-code-only-gating gap; this is the most important
sequencing decision to confirm during planning.
