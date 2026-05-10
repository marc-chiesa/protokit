---
date: 2026-05-09
topic: protokit-lint-delivery-5-pyproject-config
---

# protokit-lint Delivery 5 — `pyproject.toml` Config + `--exclude`

Created: 2026-05-09
Source roadmap: `TODOS.md` lines 95-113 ("D5 — pyproject `[tool.protokit.lint]` config + `--exclude`").
Foundation landed: D1 (foundation, 2026-05-02) + D2 (engine + canary, 2026-05-03) + D3 (CLI subcommand, 2026-05-09; absorbed D4 formatters).
Sequence: depends on D3; precedes D6 (rule packs beyond the canary), then D7 (`--compat-rule-pack` rename + plugin-API doc).

D5 also folds in two D3 deferrals and one D1 deferral that the D3 plan
explicitly punted to "next delivery (pyproject config)". The originating
deferrals are referred to throughout this document with explicit "D3"/"D1"
prefixes ("**D3 R12**", "**D3 R17**", "**D1 A5**") to disambiguate them
from D5's own R-numbers, which start at R1 and are unprefixed:

| Origin | Deferral | Implemented by D5 requirements |
|---|---|---|
| D3 | R12 — `LintRuntimeWarning(category="min_severity_relaxed")` structured emission | R17–R21a |
| D3 | R17 — file-level exclusion, "co-design with `[tool.protokit.lint] exclude` globs" | R7–R10 |
| D1 | A5 — `tests/schema/lint/test_perf_smoke.py` measurement | R22–R24 |

## Problem Frame

D5 ships three coordinated changes:

1. **Per-project config surface.** D3 shipped `protokit lint` end-to-end
   against the `naming/snake-case-fields` canary, but every CLI
   invocation needs explicit flags (`--profile`, `--max-warnings`,
   `--format`, `--min-severity`, etc.). Real projects ship linters
   with per-project config checked into source — flake8 / ruff / mypy
   / black all read `pyproject.toml` `[tool.<name>]` tables, and
   protokit currently has no equivalent. Without project config,
   `protokit lint` users repeat the same flag soup on every invocation.
2. **File-level exclusion.** D3 R17 deferred file-level exclusion to
   D5 to co-design with the `[tool.protokit.lint] exclude` glob key.
   Both shapes (CLI `--exclude PATTERN` + pyproject `exclude = [...]`)
   land here; together with `--no-exclude` (R13a) they cover the
   pattern-based exclusion surface for D5.
3. **Cross-formatter `LintRuntimeWarning` render contract.** D3
   shipped four formatters but only `lint_json` rendered
   `report.runtime_warnings`; the existing two warning categories
   (`rule_exception`, `unloaded_rule`) have been silent in
   `lint_human`/`lint_junit`/`lint_sarif` since D3 ship. D5 closes
   that latent regression AND establishes the cross-formatter render
   contract for **all** `LintRuntimeWarning` categories — current
   (4 categories after D5) and future. Every D6+ category author
   owes parity tests across four formatters. This is a deliberate
   observability commitment, not a bug-fix bonus.

D5 is the **ergonomic foundation** for D6, not a strict blocker.
D6's value (a real rule library so the canary stops being the only
thing that fires) lands whether config comes from CLI flags or
pyproject; pyproject just makes D6's UX viable at production scale
once N rules are firing. Without D5, D6 still ships useful rules
— users would just live with longer command lines and silent
warning categories in 3 of 4 formatters.

**Goal-work scope honesty.** D5 closes the pyproject-config gap
for four of the listed flags (`--profile`, `--max-warnings`,
`--format`, `--min-severity`) plus `--exclude`. It does **not**
close the `--rule-pack` flag-soup case: per KD-1, plugin loading
from pyproject is deferred to D6+. A user with N third-party rule
packs at D5 still types N `--rule-pack` flags per invocation; that
half of the original pain is closed by whichever D6 brainstorm
picks the plugin-loading shape (entry points, config strings, or
hybrid). D5 is honest about this gap rather than claiming to
deliver "no flag soup."

**Why D5 before D6 (prioritization defense).** F6's framing
("ergonomic foundation, not strict blocker") is honest about D5's
role but raises a sequencing question: if D6 ships useful rules
without D5, why D5 first? Three durable reasons:

1. **R18's BREAKING change is cheaper to ship now than later.**
   The `LintRuntimeWarning.rule_id: str → str | None` migration
   (plus the SARIF `properties.runtime_warnings` channel and
   `descriptor.id` retrofit per R21a) lands against ONE rule pack's
   output today. Shipping D6 first means N more rules emitting
   warnings against the old wire format, then breaking on top of
   that — every JSON/SARIF consumer pays the migration cost
   simultaneously with absorbing N new rule semantics. R18-in-D5
   defers the BREAKING-on-bigger-output worse path.
2. **Per-project config retrofit is harder than config-first.**
   Users adopting D6 without D5's pyproject surface will wire
   their CI scripts around `--rule-pack` flag soup + `--profile`
   flag soup. D5-after-D6 means migrating those CI scripts to
   pyproject post-hoc — across every consumer who adopted D6.
   D5-first lands D6 into a config-aware ecosystem; consumers
   skip the wire-then-rewire cycle.
3. **Perf smoke needs a baseline before D6 multiplies the walk.**
   The A5 perf smoke (R22–R24) calibrates against a 1-rule
   canary. D6 introduces N more rules to walk. Without D5's
   baseline pinned BEFORE D6's rule additions, regressions in D6
   can't be distinguished from baseline-walk overhead — the smoke
   becomes uncalibrated noise. Landing the baseline first makes
   D6's rule additions accountable to a stable measurement.

These reasons make D5 a deliberate predecessor to D6, not optional
polish. F6's "ergonomic foundation" framing is correct about D5's
*role*; the three reasons above are why the *order* matters.

D5 is also where one D3-deferred design decision **must** be answered
before implementation, per the D3 plan's `--rule-pack`-as-code-execution
risk-line (D3 plan line 1806):



> *"The next delivery (pyproject config) widens this surface; D7
> (plugin API) widens it again. The next-delivery brainstorm MUST
> answer the allowlist/integrity strategy before any implementation
> lands."*

The brainstorm answers it: **D5 does not widen the surface.** Pyproject
is config-only at D5 (no plugin loading from `pyproject.toml`); plugin-
loading shape is deferred to D6 or D7. See KD-1.

## Requirements

### Pyproject discovery and parsing

- **R1.** `protokit lint` reads `[tool.protokit.lint]` from `pyproject.toml`
  discovered via CWD walk-up. First match wins; aggregation across nested
  pyprojects is explicitly NOT supported. (KD-8.)
- **R1a (walk-up boundary, per pass-2 P2-A + pass-4 worktree fix).**
  Walk-up terminates at the **first path where `(parent / ".git").exists()`
  is true** — covering both `.git` directories (standard checkouts) AND
  `.git` files (git worktrees, submodules, where `.git` is a pointer
  file containing `gitdir: <path>`). The check uses `.exists()` not
  `.is_dir()`; using `.is_dir()` would silently skip past worktree
  roots and continue walk-up into attacker-writable parent territory,
  exactly the failure mode this requirement exists to prevent. If a
  user runs `protokit lint` outside any `.git` tree (e.g., a
  pip-install-from-tarball CI environment with no checkout), walk-up
  proceeds to root with the standard silent-on-no-config behavior;
  see Outstanding Questions for the no-`.git` environment caveat.
  Matches ruff's project-root detection posture. Document the
  boundary semantics explicitly in `--help` and README.
- **R2.** `[tool.protokit.lint]` accepts exactly these top-level keys:
  `profile` (string or list-of-strings), `exclude` (list-of-strings),
  `min_severity` (`"info"`/`"warning"`/`"error"`), `max_warnings` (int),
  `format` (string). No other keys recognized at D5. (KD-5.)
- **R3.** Unknown keys in `[tool.protokit.lint]` (top-level OR nested
  under any sub-table not listed in R2) produce a hard error with a
  message naming the recognized keys. Matches ruff/mypy/black precedent;
  catches typos like `excldue = [...]` that would otherwise silently
  no-op. The R3 error message is uniform across all unrecognized keys
  — D5 does not distinguish "unknown" from "reserved-for-future-
  delivery" categories (per F1 revision; the original R4 distinction
  was dropped in favor of R3's uniform handling, leaving D6 free to
  introduce its own distinction against its actual schema). (KD-6.)
- **R3a (type validation).** Type mismatches on R2's listed keys
  produce hard errors with the same UX contract as R3
  (exit code 2, message naming the offending key and expected type;
  the offending value is NOT echoed in the error message — matches
  R5a's `tomli` content-safety concern). Examples:
  `min_severity = 1` (int instead of str), `max_warnings = "0"`
  (str instead of int), `exclude = "vendor/**"` (scalar instead of
  list-of-strings — note this is distinct from R15's profile-as-
  scalar accepted via coercion, which is explicitly opted into in
  the type definition). U2 implements key-name validation (R3) AND
  type validation (R3a) in a single schema-validation pass. (Per
  pass-2 adversarial F1 revision.)
- **R5.** CLI: `--config PATH` flag overrides walk-up discovery with an
  explicit path; `--no-config` flag bypasses pyproject loading entirely
  (run with built-in defaults). On no-config-found via walk-up OR on
  `[tool.protokit.lint]` table missing from a discovered pyproject:
  silent — run with built-in defaults. (KD-8.)
- **R5a.** Shadow paths for `--config PATH` (explicit-path case is
  stricter than walk-up because the user signaled explicit intent):
  - Path does not exist → hard error, exit 2, message names the path.
  - Path is unreadable (permissions, EISDIR) → hard error, exit 2.
  - Path parses as TOML but lacks `[tool.protokit.lint]` table → hard
    error, exit 2. Distinct from the silent walk-up case.
  - Path is invalid TOML → hard error, exit 2; pass through `tomli`'s
    location info in the message. **Verify during U1 that `tomli`'s
    `TOMLDecodeError` does not echo raw file bytes** before relying
    on this for the `--config /etc/passwd`-style misuse posture.
  All four use exit code 2 (config-load), distinct from exit 1
  (findings present). Cross-references D3's exit-code taxonomy.
- **R6.** Pyproject is always read from the working tree (CWD-anchored
  walk-up), never from the descriptor set's source. The descriptor set
  may have been compiled from any tree state — a checked-in `.binpb`
  artifact, a git-extracted snapshot from another tool, a regenerated
  output — but the lint config that filters its findings is always
  anchored to the CWD where `protokit lint` runs. Document this
  explicitly in README and `--help`. **Note:** `protokit lint` does
  not currently ship `--since`/`--against-base` flags (those are
  `protokit compat` only); if a future delivery adds git-ref
  integration to `protokit lint`, R6's anchoring rule applies
  unchanged. (KD-8.)

### File-level exclusion

- **R7.** CLI: `--exclude PATTERN` flag (repeatable: `--exclude a --exclude b`).
  Pyproject mirror: `exclude = ["pat1", "pat2"]`. (KD-2, KD-3.)
- **R8.** Glob semantics: gitignore-style via the `pathspec` package
  (pure-Python, mature). Supports `**` recursion and `!negation`. Replaces
  fnmatch/regex. (KD-4.)
- **R9.** Patterns match against `FileDescriptorProto.name` (the protoc-
  internal relative path), not against the filesystem. The descriptor
  pool still loads excluded files (their types may be referenced from
  non-excluded files); exclusion filters which files emit findings.
  Document this clearly: "`--exclude` is *don't report on this file*,
  not *don't load this file*." (KD-2.)
- **R10.** `--ignore` is **not** a D5 flag. D3 R17's "PATH" hint already
  signaled file-level intent; using the same `--exclude` name removes
  the flake8/pylint name-clash. The `--ignore` name is reserved for
  Phase 3's inline finding-suppression work, where the pylint-vs-flake8
  semantic distinction becomes a separate decision. (KD-3.)

### Precedence stack

- **R11.** Precedence (least to most authoritative):
  (1) built-in defaults; (2) profile composition result; (3) pyproject
  explicit overrides; (4) CLI flag overrides. Each level overrides the
  previous. (KD-7.)
- **R12.** For all keys EXCEPT `exclude`: CLI replaces pyproject. If
  `--profile strict` is given, pyproject `profile = "default"` is fully
  ignored; the CLI value (or list) wins entirely. (KD-7.)
- **R13.** For `exclude`: CLI **appends** to pyproject. `--exclude pat`
  on the command line extends, not replaces, `exclude = [...]` in
  pyproject. Matches gitignore mental model ("more rules = more
  excluded"). (KD-7.)
- **R13a.** CLI `--no-exclude` flag bypasses the entire `exclude`
  resolution (both pyproject and CLI patterns ignored; all input
  files lint). Proportional escape for debugging cases like "lint
  one specific vendored file to verify behavior" — without the
  blunt-force of `--no-config`, which discards ALL pyproject config
  (profile, min_severity, max_warnings, format) when the user only
  wanted to bypass excludes. Per-key override pattern; doesn't
  generalize to `--no-profile` / etc. at D5 (those have no
  demonstrated use case yet). (Per F3 revision.)
- **R13a-precedence (flag conflicts).** When both `--no-exclude`
  and `--exclude PATTERN` are given on the same invocation,
  `--no-exclude` wins (matches the bypass-everything framing).
  When both `--config PATH` and `--no-config` are given, **they are
  mutually exclusive** — Click rejects the invocation with a hard
  error at flag-parse time (exit 2, message naming the conflict).
  Document in `--help`. (Per pass-2 adversarial F3 revision.)
- **R13b.** **CLI emits** one
  `LintRuntimeWarning(category="all_files_excluded")` after
  applying exclude resolution and **before** invoking
  `engine.run`, when the resolved exclude set drops every file in
  the descriptor pool (i.e., zero findings possible because zero
  files survive exclusion). Mirrors R19a's CLI-scope pattern:
  `engine.run`'s signature does not change; CLI rebuilds the
  report via `dataclasses.replace(report,
  runtime_warnings=report.runtime_warnings + (new_warning,))`
  before formatter dispatch. **Framing**: R13b is a **no-work-to-do
  UX nicety**, not a security control. It catches the trivial
  full-bypass shape (e.g., `exclude = ["**/*.proto"]`) which is
  user-visible noise (zero findings on a real proto repo); it does
  **not** catch partial-exclusion bypass and is not framed as a
  bypass deterrent. The durable security framing for configuration-
  data bypass lives in the Forward-Looking Risks section ("Config-
  data bypass posture beyond D5"), not in R13b's behavior. (Per
  pass-2 P1-A revision: original "most extreme bypass-shaped
  configurations loudly" framing was overreach — R13b's actual
  coverage is the 100%-excluded UX case only.) Message: *"all input
  files matched exclude patterns; no findings possible. Check
  `[tool.protokit.lint] exclude` and `--exclude` flags. Run with
  `--no-exclude` to disable exclusion."* Field population mirrors
  `min_severity_relaxed` (`rule_id = None`, `exception_type = None`,
  `descriptor_path = None`).
- **R14.** No stderr breadcrumb when CLI overrides pyproject. The
  D3 R12 relaxation warning (the `min_severity_relaxed` warning
  specified by R17–R21a below) covers the most surprising case.
  (KD-7.)

### `profile` shape

- **R15.** `profile` accepts string OR list-of-strings:
  - Scalar: `profile = "default"` — common case, single profile.
  - List: `profile = ["default", "strict-naming"]` — composes profiles
    via D2's existing multi-pack composition machinery, mirroring
    `--profile a --profile b` on the CLI.
  - On read: scalar is coerced to a 1-element list internally before
    composition. Mirrors ruff's `select` (string-or-list).
- **R16.** When CLI `--profile` is given, the entire pyproject `profile`
  list is replaced. Multi-flag CLI usage (`--profile a --profile b`)
  produces a list that replaces pyproject. (KD-7.)

### D3 R12 fold-in (D5 R17–R21a): `LintRuntimeWarning(category="min_severity_relaxed")`

- **R17.** Extend `LintRuntimeWarning.category` Literal at
  `src/protokit/schema/lint/model.py:422` from
  `Literal["rule_exception", "unloaded_rule"]` to
  `Literal["rule_exception", "unloaded_rule", "min_severity_relaxed", "all_files_excluded"]`
  (the latter added per F3 revision; field population for both new
  categories mirrors the same shape — `rule_id = None`,
  `exception_type = None`, `descriptor_path = None`). (KD-9.)
- **R18.** Change `LintRuntimeWarning.rule_id` from `str` to `str | None`.
  Aligns with the existing `Optional` pattern used by category-conditional
  fields (`exception_type: str | None`, `descriptor_path: str | None`).
  For `min_severity_relaxed`: `rule_id = None`. The mypy-strict narrowing
  pattern documented in the existing docstring (assert-after-category-
  branch) extends to `rule_id` for the existing categories. **This is
  a deliberate public API break** affecting both the Python dataclass
  (consumers iterating `report.runtime_warnings` who call methods on
  `w.rule_id` without first branching on `w.category` will raise
  `AttributeError` for the new category) AND the JSON wire format (the
  `lint_json` formatter at `src/protokit/formatters/_builtin_lint.py:269`
  emits `"rule_id": w.rule_id`, which becomes `null` for the new
  category — schema goes from `string` to `string | null`). Both
  consequences are explicitly accepted; see R18a below for the
  CHANGELOG/migration treatment. (KD-9.)
- **R18a (CHANGELOG / migration / stability framing).** R18 ships
  with an explicit `BREAKING:` marker in CHANGELOG (per Success
  Criteria item 8) plus a migration note: *"`LintRuntimeWarning.rule_id`
  is now `str | None`. JSON consumers of
  `report.runtime_warnings[].rule_id` must handle `null` for
  `category in {'min_severity_relaxed', 'all_files_excluded'}`.
  SARIF consumers must handle the new
  `runs[].properties.runtime_warnings` array (and the now-set
  `descriptor.id` on existing notifications entries — see R21a).
  Python consumers branching on `w.category` and asserting/casting
  per the existing mypy-strict narrowing pattern (see
  `LintRuntimeWarning` docstring) require no change for the existing
  two categories; consumers using duck-typed access (e.g.,
  `w.rule_id.startswith(...)`) without category checks must add
  category branching."* The migration note also lands in the README
  `protokit lint` programmatic-API section (per Success Criteria
  item 7).
- **R18b (pre-1.0 stability disclaimer per P1-B revision).** Add an
  explicit **STABILITY: pre-1.0** statement to the README's
  `protokit lint` section and to the CHANGELOG header for D5:
  *"protokit is pre-1.0. Minor-version releases may include
  breaking changes to public Python APIs and machine output
  formats (JSON, JUnit, SARIF). Breaking changes are explicitly
  marked `BREAKING:` in CHANGELOG entries; consumers should pin
  to a specific minor version (e.g., `protokit~=0.5.0`) until 1.0
  ships. The 1.0 release will commit to semver compatibility for
  the public surface."* Reframes the adopter contract honestly —
  D5 is the first delivery after D3's CLI debut and lands in the
  adoption-critical window, but the pre-1.0 framing makes the
  expected churn explicit rather than implicit. (Per pass-2 P1-B
  revision; resolves the adoption-window concern by reframing
  the contract, not by deferring the break.)
- **R19.** Trigger condition: emit one
  `LintRuntimeWarning(category="min_severity_relaxed")` when the
  **resolved** `min_severity` (after applying full precedence stack) ranks
  lower than the **composed profile's intrinsic floor**. Fires regardless
  of whether CLI, pyproject, or both produced the relaxation. Edge cases:
  - pyproject relaxes, CLI restores → no warning (resolved == profile floor).
  - pyproject relaxes, CLI relaxes more → one warning, attributed to CLI.
  - pyproject relaxes, CLI absent → one warning, attributed to pyproject.
  - CLI relaxes, pyproject absent → one warning, attributed to CLI.
  - Profile floor at lowest level → no warning possible.
- **R19a (emission site).** `LintReport` is `@dataclass(frozen=True)`
  with `__post_init__` snapshotting tuples (see `model.py:430+`), and
  `engine.run` receives the *post-override* composed profile from CLI
  scope (`cli.py:419-439` calls `dataclasses.replace(composed_profile,
  min_severity=override_severity)` before passing to the engine). The
  engine therefore cannot see the original profile floor or the
  precedence provenance needed by R19/R20. **D5 emits the warning
  in CLI scope after `engine.run` returns**, then rebuilds the
  report via `dataclasses.replace(report,
  runtime_warnings=report.runtime_warnings + (new_warning,))` before
  formatter dispatch. This keeps `engine.run`'s signature unchanged
  and confines the precedence-provenance plumbing (Decision 4 +
  R19/R20) to CLI scope where it belongs. U2's precedence engine
  produces a `ResolvedLintConfig`-style carrier that retains
  per-key source attribution (e.g.,
  `min_severity_source: Literal["cli","pyproject","profile","default"]`
  plus the original pre-CLI pyproject value when both CLI and
  pyproject participated); U4's R20 message construction reads from
  this carrier.
- **R20.** Source attribution in `message` string (human-readable):
  - CLI source: `"--min-severity=warning relaxes profile floor from error to warning"`.
  - Pyproject source: `"[tool.protokit.lint] min_severity=warning relaxes profile floor from error to warning"`.
  - Both: `"--min-severity=warning relaxes profile floor from error to warning (overriding pyproject min_severity=info)"`.
- **R21.** Remove the conditional emission block at
  `src/protokit/schema/lint/cli.py:425-439` (the entire
  `if SEVERITY_RANK[override_severity] < SEVERITY_RANK[composed_floor]:`
  guard plus the `click.echo(...)` body inside it; per pass-4
  feasibility correction the functional `dataclasses.replace`
  call ends at line 424, NOT line 432). **Lines 419-424 STAY** —
  they contain the `dataclasses.replace(composed_profile,
  min_severity=override_severity)` call that makes `--min-severity`
  work; R19a explicitly relies on this override application
  happening pre-`engine.run`. Removing only lines 433-439 (the
  click.echo body) without the surrounding `if` guard would leave
  a syntactically invalid empty block. Additionally remove the
  **second** stderr emission of `report.runtime_warnings` at
  `src/protokit/schema/lint/cli.py:498-503` (the
  `for warning in report.runtime_warnings: click.echo(...)` loop)
  — this is a pre-existing post-`engine.run` stderr blast that
  R21a's formatter render code replaces. After R21 + R21a, all
  warning visibility flows through `LintReport.runtime_warnings`
  rendered by formatters; no direct `click.echo` of warnings
  anywhere in `cli.py`. Single source of truth — same posture as
  the 2026-04-13 plugin-failures decision (no `warnings.warn()`,
  single channel via `report.warnings`). (Per pass-2 feasibility
  correction + pass-4 line-range fix.)
- **R21a (formatter render expansion, per F4 revision).** Direct
  code verification confirmed only `lint_json`
  (`src/protokit/formatters/_builtin_lint.py:266-274`) iterates
  `report.runtime_warnings` today. `lint_human` (line 166),
  `lint_junit` (line 374), and `lint_sarif` (line 487) do **not**
  render warnings — meaning D3's existing `rule_exception` /
  `unloaded_rule` warnings are already silent in 3 of 4 formatters.
  D5 fixes this by adding render code to all three:
  - **`lint_human`**: this is the FIRST formatter to need stderr
    emission; existing formatters return `(report, ctx) → str`
    with no side-effect channel (verified across all 4 formatters
    in `_builtin_lint.py`). **Architectural decision (per pass-4
    feasibility F1)**: the formatter signature does NOT change.
    Instead, **CLI inspects `report.runtime_warnings` post-format
    dispatch and emits stderr lines for the human format only**
    (`src/protokit/schema/lint/cli.py` post-`engine.run` and
    post-`render_with_formatter` hook). This keeps formatters pure
    (no side effects), preserves the existing
    `formatter(report, ctx) → str` contract for compat siblings,
    and centralizes warning-render policy in one place. Stderr
    line shape: `"protokit lint: warning [{category}]: {message}"`
    — stable prefix, machine-grep-friendly, consistent with D3's
    removed breadcrumb shape; reaches the default-format user.
    **Per-category summarization (per pass-2 P2-B)**: when more
    than 5 warnings of a single category fire, emit the first 5
    followed by a single summarization line
    (`"protokit lint: warning [{category}]: ... and N more — use --format=json for full details"`).
    Prevents stderr flood when D6+ multi-rule packs trigger N
    `unloaded_rule` warnings on a single failed pack import.
    Threshold 5 is a placeholder; parameterize as a module-level
    constant (`_LINT_HUMAN_SUMMARIZATION_THRESHOLD = 5`) so D6
    tuning is a one-line change. Machine formatters (`lint_json`,
    `lint_junit`, `lint_sarif`) emit ALL warnings unconditionally
    via their existing structured render paths — summarization is
    CLI-side and human-only.
  - **`lint_junit`**: append `<system-out>` entries on the
    testsuite, mirroring the existing pattern at lines 364-370 for
    compile-stage warning diagnostics. Each runtime_warning becomes
    one system-out entry; categories are distinguishable via the
    leading `[{category}]` token.
  - **`lint_sarif`**: `lint_sarif` ALREADY uses
    `runs[].invocations[].toolExecutionNotifications` for compile-
    stage diagnostics (`_builtin_lint.py:529-547`) — emitting
    runtime_warnings into the same array would mix two semantically
    distinct streams with no clean discriminator. **D5 keeps the
    notifications array dedicated to compile diagnostics** and emits
    runtime_warnings into a separate non-standard property at
    `runs[].properties.runtime_warnings = [...]`. Each entry shape:
    `{level: "warning", descriptor: {id: "protokit-runtime-{category}"}, message: {text: "..."}}`.
    Distinct from results[] (findings) and invocations[].notifications
    (compile diagnostics). U4 also retroactively sets
    `descriptor.id = "protokit-compile-{category}"` on the existing
    notifications entries so consumers can filter both streams
    cleanly. **This is part of the BREAKING surface** — document in
    R18a's migration note alongside the rule_id null change. (Per
    pass-2 adversarial F4-collision correction.)
  All three render paths cover the existing two categories
  (`rule_exception`, `unloaded_rule`) AND the two new ones
  (`min_severity_relaxed`, `all_files_excluded`). Tests in
  `test_builtin_lint_formatter.py` / `test_formatters_junit.py` /
  `test_formatters_sarif.py` parametrize across all four
  categories. **Net effect**: D5 removes the stderr breadcrumb AND
  closes a latent silent-warning regression that pre-dated D5 in
  three formatters. (Per F4 revision.)

### A5 fold-in: perf smoke test

- **R22.** Land `tests/schema/lint/test_perf_smoke.py` (per D1 A5's
  deferral note). Engine-walk throughput smoke: synthetic descriptor
  set of 50 files × 20 messages × 10 fields (= 10,000 fields), run
  `LintEngine.run` with the canary, assert wall time under
  threshold. (KD-10.)
- **R23.** Threshold calibrated as `max_observed × 3` from 5–10 runs
  on the single CI cell that the test runs on (per F5 revision —
  see R23b below; the test runs on one matrix cell only, eliminating
  cell-spread dilution). The test docstring must communicate the
  smoke-not-benchmark intent — that this is a smoke test for order-
  of-magnitude regressions, not a micro-benchmark, and that flakiness
  is resolved by widening the threshold rather than removing the
  test. Exact wording is an implementation decision. Marked
  `@pytest.mark.slow` so fast-iteration `pytest -m "not slow"` skips
  it. (KD-10.)
- **R23b (single-cell scope per F5 revision).** `test_perf_smoke.py`
  runs on **one** CI matrix cell only. The actual CI matrix is
  `python = ["3.10", "3.12"]` × `has_protoxy = [true, false]`
  (verified against `.github/workflows/ci.yml`); the recommended
  pin is `linux + python=3.12` (`has_protoxy`-axis-agnostic;
  **note the matrix does NOT include py3.11**). The `has_protoxy`
  axis is **irrelevant to the engine-walk closure-allocation
  concern** that A5 raised — lint operates on `FileDescriptorProto`
  and never imports protoxy. The cell pin is therefore for
  stability/predictability of CI scheduling, not problem-domain
  coverage. **Skip predicate (per pass-2 P3-D revision):**
  ```python
  @pytest.mark.skipif(
      sys.platform != "linux" or sys.version_info[:2] != (3, 12),
      reason="perf smoke runs on linux+py3.12 only (R23b)",
  )
  ```
  No env var; the predicate uses standard library introspection
  only. Other matrix cells skip the test; the threshold reflects
  one cell's observed range, not the cross-cell max. Trade-off
  accepted: the test loses cross-OS regression coverage in exchange
  for catching real per-cell regressions that a global threshold
  would hide. Document this trade-off in the test's module
  docstring alongside the smoke-not-benchmark framing. (Per pass-2
  feasibility / adversarial / security cell-name + has_protoxy +
  env-var corrections.)
- **R23a.** Register the `slow` marker in `pyproject.toml` under
  `[tool.pytest.ini_options] markers = ["slow: tests excluded by `pytest -m \"not slow\"`"]`
  so future `--strict-markers` adoption doesn't regress. Lands in
  the same U6 polish unit as the dep additions.
- **R24.** Synthetic fixture: parametrized `.proto` generator at
  test time, compiled via D1's `compile_protos_to_result` (matches
  `tests/schema/lint/cli/conftest.py` pattern). No checked-in
  `.descriptor_set` binaries. Whether the generator becomes a
  reusable helper or stays inline is a planning-level call.

### Dependencies

- **R25.** Add `tomli` to required dependencies for Python 3.10 only
  (3.11+ ships `tomllib`). Standard pattern:
  ```python
  import sys
  if sys.version_info >= (3, 11):
      import tomllib
  else:
      import tomli as tomllib
  ```
  Specified in `pyproject.toml` `[project] dependencies` with the
  appropriate version marker.
- **R26.** Add `pathspec` to required dependencies (gitignore-style
  globs). Pure-Python, no compilation; verify maintenance status
  during planning before locking the version pin.

## Success Criteria

D5 ships when **all** of the following hold:

1. `protokit lint` discovers `[tool.protokit.lint]` via CWD walk-up
   and applies its values per the precedence rules in R11–R14.
2. `--config PATH` and `--no-config` flags work as specified.
3. `--exclude PATTERN` (CLI, repeatable), `--no-exclude` (R13a
   override), and `exclude = [...]` (pyproject) all behave per
   R7–R13b. CLI patterns append to pyproject; `--no-exclude`
   bypasses the entire exclude resolution; `all_files_excluded`
   runtime warning (R13b) fires when zero files survive
   exclusion.
4. Unknown keys in `[tool.protokit.lint]` (top-level or nested)
   produce a hard error naming the recognized keys.
5. `LintRuntimeWarning(category="min_severity_relaxed")` is emitted
   per R19 trigger; `rule_id: str | None` is the new dataclass shape
   (BREAKING; see R18/R18a); stderr breadcrumb at `cli.py:419-439`
   is removed.
6. `tests/schema/lint/test_perf_smoke.py` runs to completion within
   threshold on the designated CI matrix cell (per R23b — linux,
   py3.12, has_protoxy-axis-agnostic); skips cleanly on other
   cells via `@pytest.mark.skipif(...)`.
7. README `protokit lint` section gains a `[tool.protokit.lint]`
   subsection documenting the schema, discovery, and the
   working-tree-vs-git-ref note (R6).
8. CHANGELOG entry covers: pyproject config table, `--exclude` /
   `--no-exclude` / `--config` / `--no-config` flags, D3 R12
   structured warning, `pathspec` + `tomli` deps. CHANGELOG
   includes a `BREAKING:` marker for R18 (`LintRuntimeWarning.rule_id`
   widened to `str | None`; JSON `runtime_warnings[].rule_id` may
   be `null` for `min_severity_relaxed` / `all_files_excluded`;
   SARIF gains `runs[].properties.runtime_warnings` and sets
   `descriptor.id` on existing notifications entries) with the
   migration note in R18a. CHANGELOG header for D5 also carries
   the pre-1.0 stability disclaimer per R18b.
9. `tests/test_static_analysis.py` ratchet auto-covers the new files
   under D5's path globs.
10. All 1056-baseline tests still pass.

## Scope Boundaries

### In scope (D5)

- `[tool.protokit.lint]` pyproject table, Tier I keys (R2).
- `--exclude`, `--no-exclude`, `--config`, `--no-config` CLI flags.
- D3 R12 + D3 R17 + D1 A5 fold-ins per the table in the preamble above.
- Two new `LintRuntimeWarning` categories (`min_severity_relaxed`,
  `all_files_excluded`) + R18 BREAKING (`rule_id: str | None`) +
  pre-1.0 stability disclaimer (R18b).
- Formatter render expansion (R21a) across `lint_human` / `lint_junit`
  / `lint_sarif` covering all 4 categories (the 2 new + 2 pre-existing
  that were silent in 3 of 4 formatters since D3).
- `tomli` + `pathspec` dependency additions.
- README + CHANGELOG updates.
- D5-touched paths added to the static-analysis ratchet.

**Why bundled** (per pass-2 P1-C decision): a D5/D5b split was
considered (D5 = config core; D5b = formatter render parity).
Rejected in favor of single-delivery shape. Rationale: splitting
would ship D5 with a known regression in 3 formatters for the two
new warning categories; the formatter render work is small enough
(~80–120 LOC + tests) to absorb in U4. The per-unit `/ce:work` +
`/ce:review` cadence handles the breadth.

### Out of scope (deferred)

- **Plugin loading from pyproject** (`rule_packs = [...]` key) — KD-1.
  Deferred to D6 (entry-point discovery story) or D7 (plugin-API doc),
  whichever picks the loading shape against ≥2 rule packs.
- **Per-rule severity overrides.** D5 surfaces them as unknown keys
  via R3's uniform error; the eventual schema (e.g., a
  `[tool.protokit.lint.rules.*]` table or a flatter form) is D6's
  call.
- **Per-file rule overrides.** Same posture as per-rule: D5 errors
  via R3, D6 designs the schema.
- **Top-level `enabled_rules` / `disabled_rules` lists.** Same: D5
  errors via R3, D6 designs.
- **Inline `# protokit:ignore` comment suppression.** Phase 3 separate
  item, unrelated to file-level exclusion.
- **`--no-builtin-rules` flag.** D6 ships the second built-in rule pack;
  the flag becomes meaningful then (per D3 R7's deferral rationale).
- **`--extend-exclude` flag.** Single `--exclude` (append-to-pyproject)
  semantics + `--no-exclude` (R13a) cover the override cases; if
  "extend pyproject excludes via a different flag name" becomes a
  real demand, add later.
- **`--ignore` flag.** Reserved name for Phase 3 finding-suppression
  work; D5 retires D3 R17's name.
- **Standalone `protokit.toml` alternative file.** ruff supports it;
  D5 doesn't. Add later if asked.
- **`PROTOKIT_CONFIG` env var.** Not at D5.
- **Aggregation across nested pyprojects.** First-match-wins only.
- **Verbose precedence breadcrumbs** when CLI overrides pyproject.
  Silent precedence; the D3 R12 relaxation warning covers the surprising case.

## Key Decisions

### KD-1: Pyproject is config-only at D5; no plugin loading

`[tool.protokit.lint]` does not accept `rule_packs = [...]` or any
key that triggers `import_module()`. Plugin-loading shape (entry
points vs. config strings vs. hybrid) is deferred to D6+ where ≥2
rule packs exist to pressure-test against.

**Rationale:** The D3 plan flagged that pyproject widens the
`--rule-pack` code-execution surface and required this brainstorm to
answer the trust strategy. The answer is *not to widen the surface*.
Industry precedent for plugin loading is mixed (flake8/pytest =
entry points; mypy/pylint = config strings); both rely on the
package-install boundary as the trust gate. flake8 and pytest
deferred their plugin-loading shape until they had real demand
to design against — protokit at D5 has one rule pack, so it's
the wrong time to commit. D6 (with ≥2 packs) is the natural
moment to pick the pattern.

**Forward-compat:** R3's unknown-key hard error covers any future
plugin-loading keys (or any other unrecognized key) uniformly. D5
does not pre-reserve specific table names for D6 — that decision
is deferred to D6's brainstorm against its actual schema. (Per
F1 revision.)

**Identity Bet (per pass-2 P2-G).** KD-1's "config-only at D5"
posture is in tension with protokit-lint's broader thesis that
rules are Python-native (rules are Python modules, profiles are
Python data). A pyproject schema for rule SELECTION (vs. rule
*configuration*, which lives in profiles) drifts toward the
ruff/flake8 model — config-driven rule lists — rather than the
Python-native model where profiles compose in code. KD-1 doesn't
foreclose the Python-native path (D6 can still pick entry-point
discovery + profile-driven selection), but D5 ships pyproject
keys (`profile`, `min_severity`, `max_warnings`, `format`,
`exclude`) that establish "pyproject as the user-facing surface"
as the dominant convention. **The bet**: ≥2 rule packs in D6 will
produce a better plugin-loading shape than premature commitment
in D5; user packs are CLI-loaded at D5 and centralized at D6+ via
whichever mechanism D6 picks. The risk: users perceive user packs
as second-class at D5; the mitigation is documenting this
explicitly so the contract is honest. If the bet fails (D6's
brainstorm picks a config-string-driven plugin shape that
contradicts the Python-native thesis), that's a deliberate D6
decision, not a D5 lock-in.

### KD-2: Exclusion is one concept, two shapes

D3 R17 (`--ignore PATH`) and pyproject `exclude` were both deferred
together to D5 with the note "co-design...so they share semantics."
The brainstorm pressure-test concluded they're **the same concept**
(file-level exclusion) in two shapes (CLI flag + config table),
not two distinct concepts. The other natural concept — finding-
level suppression — is already a separate Phase 3 item ("Inline
rule suppression via `protokit:ignore` comments").

### KD-3: `--exclude` only; retire `--ignore` from R17

CLI flag is `--exclude PATTERN` (repeatable). Matches flake8/black/
ruff/mypy precedent (clear file-level intent). `--ignore` is the
most ambiguous flag in Python lint tooling (flake8 = rule codes;
pylint = paths); D3 R17's "PATH" hint already pointed at file-level,
so the rename to `--exclude` removes the name-clash. `--ignore`
is reserved for Phase 3's finding-suppression work, where the
flake8-vs-pylint semantic distinction becomes a real decision.

### KD-4: Glob semantics via `pathspec` (gitignore-style)

ruff uses gitignore-style globs (`**/*.proto`, `!exception.proto`).
Most modern Python pattern. `pathspec` is pure-Python, mature, no
compilation cost. Alternative (stdlib `fnmatch`) loses negation
and `**` recursion — strictly weaker UX for one fewer dep.
Trade-off accepted: `pathspec` ships.

### KD-5: Tier I config schema (top-level keys only)

`[tool.protokit.lint]` accepts: `profile`, `exclude`, `min_severity`,
`max_warnings`, `format`. No per-rule controls, no per-file controls.
Per-rule tuning still requires writing a Python profile (D2 supports
this); D6+ adds richer schema once the rule library justifies it.

**Why Tier I, not Tier II/III:** protokit has one rule pack at D5.
Designing per-rule severity overrides against one rule is designing
against zero real use cases. Per-rule and per-file controls land
in D6+ when the rule library justifies them; D5 does not pre-
reserve specific table names (per F1 revision) — D6 designs the
schema freely against its actual rule set.

**Tier I narrowness vs. ruff/mypy positioning (per pass-2 P2-F).**
A user evaluating protokit-lint at D5 will see 5 keys vs ruff's
~50+. KD-5's defense (don't design against zero rules) is correct
on the merits; the F6 reframe makes the positioning honest:
**Tier I is the *ergonomic-foundation* schema, not the
*destination* schema.** D6 grows per-rule controls when the rule
library justifies them. D7+ may add per-file controls if real
usage signals the demand. Users comparing against ruff at D5
should expect schema parity to grow with the rule library,
matching ruff's own historical pattern (ruff started small and
expanded as its rule library grew). This is a deliberate identity
choice: protokit-lint optimizes for "config grows with the tool,"
not "config is rich on day one."

### KD-6: Hard error on unknown keys

ruff/mypy/black all hard-error on unknown keys. The cost is one
helpful error message; the benefit is no silent typo bugs. flake8's
legacy lenient behavior is the worse default — `excldue = [...]`
silently no-ops with zero feedback.

### KD-7: Precedence — CLI > pyproject > defaults; replace except `exclude`

Universal industry pattern: CLI flag wins over config which wins
over defaults. For list-valued keys, the interesting choice is
replace-vs-append:

- `profile`: **replace** (CLI value(s) override entire pyproject list).
  Append-mode invites confusion ("why is the strict profile firing?
  oh, pyproject also added default").
- `exclude`: **append** (CLI patterns extend pyproject patterns).
  Matches gitignore mental model. Single `--exclude` flag, no
  `--extend-exclude`. `--no-exclude` (R13a) is the proportional
  override for debugging; `all_files_excluded` runtime warning
  (R13b) surfaces bypass-shaped configurations.

`min_severity` / `max_warnings` / `format` are scalars: replace.
Silent precedence — no breadcrumb when CLI overrides pyproject.
The D3 R12 relaxation warning (KD-9) covers the most surprising case.

### KD-8: Pyproject discovery — CWD walk-up, first match, escape hatches, project-root boundary

Universal pattern across flake8/black/ruff/mypy/pylint: walk up
from CWD, first `pyproject.toml` found wins, plus `--config`
escape hatch. D5 adds `--no-config` (mypy-style) to support
"verify CI runs with intended defaults." Silent on missing config
or missing `[tool.protokit.lint]` table.

**Walk-up boundary (per R1a, pass-2 P2-A revision + pass-4 worktree
fix)**: walk-up terminates at the first path where `(parent /
".git").exists()` is true — covering both `.git` directories
(standard checkouts) AND `.git` files (git worktrees, submodules).
The `.exists()` check (not `.is_dir()`) is critical: worktree `.git`
is a FILE pointer, and a directory-only check would silently skip
past worktree roots into attacker-writable parent territory. On
shared filesystems and CI environments (`/tmp`-based build trees,
mounted volumes), this prevents walk-up from consuming attacker-
writable parent pyprojects outside the project boundary. In
monorepos with nested `.git` directories or worktrees, the boundary
respects the immediate sub-project root.

For descriptor sets compiled from any non-CWD source (a checked-in
`.binpb` from a previous build, a git-extracted snapshot, a
regenerated output): pyproject is always read from the **working
tree**, not the descriptor's source. This is the standard
convention (lint config is anchored to the running invocation), but
worth documenting because someone will hit the "I checked out an
old branch and got different lint output" case. Note: `protokit
lint` does not currently expose git-ref flags (`--since`,
`--against-base` are `protokit compat`-only); if a future delivery
adds them, R6's anchoring rule applies unchanged.

### KD-9: `LintRuntimeWarning.rule_id: str | None`

Change from `rule_id: str` to `rule_id: str | None`. Aligns with
the existing `Optional` pattern used by category-conditional
fields (`exception_type: str | None`, `descriptor_path: str | None`).
For `min_severity_relaxed`: `rule_id = None` (not rule-specific).

**Why not the empty-string sentinel:** the empty-string approach is
a code smell — `''` is not "no rule," it's "a rule with empty ID."
Truthy checks (`if w.rule_id:`) silently treat both as the same
thing; that's exactly the latent bug class mypy `--strict` is
designed to catch. The dataclass's existing field-population
docstring already establishes the assert-after-category-branch
pattern for `descriptor_path`/`exception_type`; extending the
same pattern to `rule_id` is one-line per consumer (the four
formatters), not a refactor.

**Blast radius:** `model.py` (annotation + docstring table) +
4 formatters (`lint_human`, `lint_json`, `lint_junit`,
`lint_sarif`) + their tests. All files D5 already touches for
the Literal extension. **Plus**: a public API/wire-format break
(see R18). The Python dataclass is part of the public lint API
(reachable via `report.runtime_warnings` from any caller of
`LintEngine.run`), and `lint_json` at `_builtin_lint.py:269`
unconditionally emits `"rule_id": w.rule_id` — so the JSON
schema for `runtime_warnings[].rule_id` widens from `string` to
`string | null`. Both impacts are accepted; R18a specifies the
CHANGELOG `BREAKING:` marker and migration note. The choice
trade against an empty-string sentinel: sentinel preserves wire
format but propagates the code-smell pattern to every future
`LintRuntimeWarning` category author. We prefer the public-API
break with explicit migration over indefinite sentinel
propagation.

### KD-10: A5 perf smoke — engine-walk throughput, single CI cell

Single test, single cell: synthetic descriptor set (50 × 20 × 10 =
10,000 fields), `LintEngine.run` with canary, assert wall time
< `max_observed × 3` (from CI calibration on the chosen cell —
linux, py3.12, has_protoxy-axis-agnostic since lint never touches
protoxy; py3.11 is **not** in the actual CI matrix
`python = ["3.10", "3.12"]`). Implicitly exercises A5's closure-
allocation concern by stressing the walk; catches order-of-
magnitude regressions cheaply. **Smoke, not benchmark** — flakiness
handled by widening the threshold, never by removing the test.
`@pytest.mark.slow` + cell-skip predicates so fast-iteration runs
skip it; default `pytest` on the chosen cell includes it. Per F5
revision: running on one cell instead of the full matrix avoids
cell-spread dilution that would mask a fast-cell regression
behind a slow-cell baseline.

Why not micro-benchmark closure cost specifically: micro-benchmarks
are notoriously CI-fragile (sub-millisecond noise floor). A scale
test answers A5's actual concern ("could this matter at scale?")
more honestly.

Why not per-cell baselines: that's the right answer if cross-
platform perf coverage matters. For pure-Python closure-allocation
cost, perf is largely CPython-bytecode-bound (not OS-dependent),
so the value of per-cell coverage is low; the maintenance cost of
per-cell baseline files is real. Defer to a future delivery if a
real cross-cell perf signal emerges.

## Sibling-Parity Audit

`protokit compat` (Phase 1.5b + D3 sibling-parity hardening) does
NOT read pyproject config today. D5 introduces pyproject reading
**only** for `protokit lint`; `compat` retains its CLI-only surface.
This is intentional asymmetry: compat's primary use case is CI
gating against a baseline schema, where pyproject "always wins"
behavior is a footgun (a PR that relaxes compat policy via
pyproject would silently weaken the gate).

If compat ever grows pyproject support, that's its own future
delivery (post-D7), not part of D5. D5's scope is `lint` only.

## Dependencies / Assumptions

### New dependencies

Both new dependencies receive identical supply-chain treatment at
planning time: pin a known-good minimum, cap the upper bound consistent
with project semver policy, verify package signature / published hash
at the pinned version during U1, and add to dependabot/renovate config
so future upgrades are reviewed (not automatic).

- **`tomli`** — TOML parsing for Python 3.10 (`tomllib` ships in 3.11+).
  Pin via environment marker: `tomli >= 2.0, < 3; python_version < "3.11"`.
  Standard pattern in the ecosystem (used by black, mypy, ruff's Python
  fallback, etc.). Despite the wide adoption, treat as a security-
  sensitive dependency since it parses untrusted-ish TOML from the
  filesystem; the supply-chain steps above apply.
- **`pathspec`** — gitignore-style glob matching. Pure-Python; mature
  (used by `mypy`, `dvc`, `pre-commit`, etc.). Pin a sensible minimum
  with the same upper-bound + signature + dependabot strategy as `tomli`.

### Assumptions

- `tests/test_static_analysis.py:_LINT_PATHS` and `_TYPE_CHECK_PATHS`
  glob auto-pick up D5 file additions per the pay-as-you-touch ratchet.
  Verify during U-N implementation; if not auto-picked, add explicit
  entries.
- D2's profile composition machinery (`engine.py`) handles the
  multi-profile case for `profile = [a, b]` correctly; D5 calls into
  the existing API rather than reimplementing.
- ~~The four lint formatters in `_builtin_lint.py` already render
  `LintReport.runtime_warnings`.~~ **REVISED per F4**: only
  `lint_json` renders runtime_warnings today; `lint_human`,
  `lint_junit`, `lint_sarif` do NOT. D5 adds render code to all
  three (R21a) covering both existing categories
  (`rule_exception`, `unloaded_rule`) and the two new ones from
  this delivery (`min_severity_relaxed`, `all_files_excluded`).

## D5-Present Security Risks

### `--config PATH` accepts arbitrary paths

Same posture as `--rule-pack MODULE` in D3: trust = the operator
typing the flag. A `--config /etc/passwd` invocation produces a
TOML parse error, not data exfiltration — provided the parser
error message does not echo raw file bytes (verify in U1 that
`tomli.TOMLDecodeError` is content-safe, per R5a). The surface is
bounded.

**Symlink caveat:** `--config PATH` is opened by the OS without
canonicalization; symlinks resolve at open time. If callers
construct `--config` paths programmatically (e.g., from CI YAML
interpolation), they should canonicalize the path before passing
it. Document this caveat in the README security note alongside
the trust model. No enforcement code at D5.

### Pyproject is data, not code (but data can still weaken policy)

KD-1 explicitly excludes plugin loading from pyproject. The
config values are pure data (strings, numbers, lists of strings,
TOML tables). No `import_module()` is reachable via pyproject
content at D5. The `--rule-pack MODULE` flag retains its D3
trust posture; pyproject does not widen the **code-execution**
surface.

**Configuration-data bypass is a known, durable, accepted concern.**
A PR adding `exclude = ["src/sensitive/**", "src/api/**"]` (drop
99% of files), `min_severity = "info"`, `max_warnings = 99999`,
or switching `profile = "permissive"` to `[tool.protokit.lint]`
silently weakens CI without triggering any error path that fully
mitigates the bypass. This is the same threat shape that the
Sibling-Parity Audit invokes for compat ("a PR that relaxes compat
policy via pyproject would silently weaken the gate") — applied to
lint, the analogous risks exist for `exclude`, `min_severity`,
`max_warnings`, and `profile`.

**D5's posture (deliberate, matches industry):** Every config-
driven lint tool (flake8, ruff, mypy, black) has this exact
threat shape. None implement partial-exclude warnings, baseline
tracking, or in-tool enforcement. The universal industry answer
is **code review of config changes**. D5 adopts that posture
explicitly:

- **`all_files_excluded` runtime warning (R13b)** is a UX nicety
  for the trivial full-bypass case, not a security control.
- **`min_severity_relaxed` runtime warning (R19)** surfaces pyproject-
  driven relaxation of the profile floor (also a UX nicety; a
  malicious PR can switch `profile` instead and avoid the warning).
- **No D5 mitigation** for `max_warnings` weakening, partial-
  exclusion bypass, or `profile` switching — silent by design.
- **All config-data bypasses are accepted as PR-review-discipline
  concerns.** The README `protokit lint` security note enumerates
  the bypass channels explicitly so reviewers know what to look
  for.

The durable mitigation strategy and forward-looking work live in
the Forward-Looking Risks section (see "Configuration-data bypass
posture beyond D5"). D5 does not commit to additional in-tool
enforcement.

### `pathspec` and `tomli` (new deps)

Pure-Python, no compilation; supply-chain risk is the standard
"new direct dep" surface for both packages. Both receive the
identical pinning + signature + dependabot treatment described
in the Dependencies section. `tomli` is the more security-sensitive
of the two (it parses untrusted-ish config from the filesystem),
but the audit steps are the same.

## Forward-Looking Risks (Future Deliveries)

### D6 designs per-rule / per-file schema freely

D5 does NOT pre-reserve specific table names (per F1 revision —
the original R4 reserved-namespace requirement was dropped in
favor of R3's uniform unknown-key handling). D6's brainstorm
designs per-rule and per-file controls against its actual rule
library, with full freedom over schema shape — flat keys
(`disabled_rules = [...]`), nested tables
(`[tool.protokit.lint.rules.foo]`), or anything else. Until D6
ships, those keys land as R3 unknown-key errors; D5 imposes no
constraint on D6's schema choices.

### D6 / D7 will need to design plugin loading

KD-1 punts plugin-loading shape to D6 or D7. When that brainstorm
runs, the choices are:

- Entry-point auto-discovery (flake8/pytest-style; consuming
  pyproject doesn't reference plugins; trust = `pip install`).
- Config-string module paths (mypy/pylint-style; consuming
  pyproject lists modules; trust = config + install).
- Hybrid (pytest-style; both channels with explicit precedence).

D6's brainstorm should include a parallel "Read the prior art
landscape" pressure-test, exactly as D5 did. The decision should
not be made by default.

### Compat may eventually want pyproject support

D5 explicitly excludes compat (Sibling-Parity Audit above). If
compat grows pyproject support, the trust-model question
re-emerges with different stakes (CI gates that compat enforces
are higher-stakes than lint findings). That brainstorm should
re-pressure-test KD-1 in compat's context.

### Configuration-data bypass posture beyond D5

D5 accepts configuration-data bypass as a code-review-discipline
concern (see D5-Present Security Risks → "Pyproject is data, not
code"). This matches every other config-driven lint tool's
posture (flake8 / ruff / mypy / black all have analogous threat
shapes; none implement in-tool enforcement). The durable concern
that follows D5 forward:

A PR-write-access attacker can weaken lint gating by editing
`[tool.protokit.lint]` — partial `exclude` patterns, profile
switches, or `max_warnings` raises all evade D5's runtime
warnings. The realistic attack pattern is **two-PR**: PR-1
quietly weakens config (looks innocuous to reviewers); PR-2
lands the offending code (now passes the weakened gate). Single-
PR attacks are caught by code review of the config change in
the same PR.

**Three layers of durable mitigation, none of which require
protokit-side enforcement:**

1. **Documentation (D5 or near-term follow-up).** README
   `protokit lint` "Security Considerations" subsection enumerates
   the bypass channels explicitly so reviewers know what to look
   for during PR review. Cheap, immediate, durable.
2. **CODEOWNERS guidance (organizational policy).** Recommend
   protecting `pyproject.toml` — or specifically the
   `[tool.protokit.lint]` block via path-scoped CODEOWNERS — so
   config changes require security-team review. Out of protokit's
   enforcement scope; lives in org policy.
3. **Companion tool (Phase 3+ if demand emerges).** A
   `protokit lint config-diff --base <ref>` subcommand that
   surfaces "this PR weakens lint policy by X" as a separate CI
   check, complementing the lint run itself. Different tool from
   the lint engine; would need its own brainstorm against actual
   user demand.

**What is explicitly NOT the right answer:** threshold-based
warnings (arbitrary; attackers split into sub-threshold PRs;
noisy on legitimate per-package linting), baseline tracking
inside protokit (out of lint-tool scope; belongs in code-review
tooling like Reviewable / Sourcegraph or policy engines like
OPA / Conftest), or refusing to read pyproject for security-
relevant keys (defeats D5's purpose).

D5 does not block on this; it documents the posture and forward-
references the layered mitigation strategy so future maintainers
inherit the framing.

## Verified Codebase Context

Verified by direct read during brainstorm (line numbers as of 2026-05-09):

- **`LintRuntimeWarning` dataclass:** `src/protokit/schema/lint/model.py:344-426`.
  Current Literal at line 422:
  `Literal["rule_exception", "unloaded_rule"]`. Field-population
  docstring table at lines 367-378. mypy-strict narrowing pattern
  documented at lines 396-404. Existing `Optional` fields:
  `exception_type: str | None`, `descriptor_path: str | None`.
- **D3 R12 stderr breadcrumb:** `src/protokit/schema/lint/cli.py:419-439`
  (the entire override block; the actual `click.echo(...)` call is at
  lines 433-439). Line 417 is a comment that references the
  `LintRuntimeWarning(category="min_severity_relaxed")` deferred work.
  The surrounding code computes `composed_floor = composed_profile.min_severity`
  and applies the override via `dataclasses.replace`.
- **D3 conftest fixture pattern:** `tests/schema/lint/cli/conftest.py`
  compiles checked-in `.proto` files via D1's `compile_protos_to_result`
  in a session-scoped pytest fixture. R24's synthetic generator follows
  this pattern.
- **Cold-import contract:** `tests/schema/lint/test_cold_import_extended.py`
  enforces `import protokit.schema` does not transitively pull
  `protokit.schema.lint`, `protokit.schema.compile`, or
  `protokit.formatters._builtin_lint`. D5 must preserve this; pyproject
  reading lives in the lint subcommand path, not in `schema/__init__.py`.
  **Target module path:** new file
  `src/protokit/schema/lint/_config.py` (leading underscore to mark
  internal; imports `tomli`/`tomllib` and `pathspec` at module top).
  Imported only from `cli.py`; **never re-exported from
  `protokit.schema.lint.__init__`**. Verify during U1 that
  `test_cold_import_extended.py` still passes with the new module
  added.
- **Static-analysis ratchet:** `tests/test_static_analysis.py:_LINT_PATHS` /
  `_TYPE_CHECK_PATHS` directory globs.
- **Existing pyproject mention:** `src/protokit/schema/lint/model.py:656`
  documents `[tool.protokit.lint] profile = "default"` as a forward
  reference. D5 makes this real.

## Outstanding Questions

### Resolve before planning

None. All eight brainstorm-level decisions (Decisions 1–8 in
session) resolved into KDs 1–10 above.

### Deferred to planning

1. **Exact A5 threshold value.** Calibrate during U-N implementation
   from local + CI runs on the pinned cell (linux+py3.12).
   Brainstorm sets the *method* (`max_observed × 3`); the *number*
   is empirical.
2. **Synthetic `.proto` generator location.** Reusable helper vs.
   inline in `test_perf_smoke.py`. Planning-level call.
3. **Exact `tomli` and `pathspec` minimum versions.** Verify against
   current PyPI metadata during U1; pin to a sensibly recent
   stable.
4. **Help-text layout for the new flags.** `--config`, `--no-config`,
   `--exclude`, `--no-exclude` need help strings + ordering in the
   `protokit lint` subcommand. Implementation-level polish.
5. **Whether unknown keys produce a hard error or a `LintRuntimeWarning`
   alongside the hard error.** R3 says hard error; whether to also
   emit a structured warning that machine consumers can capture
   (vs. CLI exit + stderr) is a planning-level call. Not strictly
   needed; ruff/mypy/black just hard-error at startup.
6. **Whether `--no-config` skips ALL pyproject reading or only
   `[tool.protokit.lint]`.** R5 says the table; the answer is "skip
   the table" since other tool tables are irrelevant. Planning may
   want to document this for symmetry.
7. **Test coverage shape for the precedence stack.** Planning will
   pick whether to write parametrized matrix tests (CLI × pyproject
   × profile) or focused per-key tests.
8. **`--show-resolved-config` debugging flag (per pass-2 P2-C,
   carried from pass 1 adversarial).** R5 + R14 + Out-of-Scope
   "verbose precedence breadcrumbs" combine to make precedence
   debugging hostile: a user editing pyproject and getting
   unchanged output has no introspection tool to confirm whether
   pyproject was loaded, the table was missing, CLI overrode, or
   the value was correctly applied. flake8 has `--verbose`; ruff
   has `--show-settings`; mypy has `--verbose`. D5 ships none of
   these. Deferred to a follow-up delivery rather than added at
   D5 because the implementation requires deciding the output
   shape (printf-style vs structured JSON), the trigger surface
   (separate flag vs always-on at higher verbosity), and integration
   with the `LintRuntimeWarning` channel. Not blocking D5 ship;
   re-evaluate after a real user requests it.
9. **`runtime_warnings` ordering between engine-emitted and
   CLI-emitted warnings (per pass-2 feasibility).** R19a says
   `runtime_warnings = engine_warnings + (cli_warning,)` (CLI
   appends). For machine consumers iterating the tuple this is
   benign; for the human formatter's stderr ordering it matters.
   Planning should pin: engine warnings (`rule_exception`,
   `unloaded_rule`) first in the order the engine produces them,
   then CLI warnings (`min_severity_relaxed`, `all_files_excluded`)
   in that fixed order. Tests pin the contract.
10. **JSON schema versioning for runtime_warnings (per pass-2
    P1-B / security F-PASS2-3).** R18b's pre-1.0 stability
    disclaimer covers the BREAKING-without-deprecation posture
    semantically, but a programmatic detection point (a
    `schema_version` field in `lint_json` root) would let
    consumers detect future breaks without reading the CHANGELOG.
    Deferred from D5 because it adds schema-versioning machinery
    that pays off across multiple deliveries; ship at D6 or D7
    where the next BREAKING change lands and the cost amortizes.

### Pass-4 themes deferred to /ce:plan

Pass 4 (2026-05-10) surfaced ~30 second-order findings across
6 reviewers. The 3 concrete-bug P1s were auto-fixed in pass 4
itself (R1a `.git`-as-file, R21 line range 419-424 not 419-432,
formatter stderr architectural decision per F1 — CLI-side stderr
emission, not formatter-side). The remaining themes flow to
/ce:plan as Outstanding Questions:

11. **R3a element-type validation for list-valued keys** (adversarial
    F-PASS4-2). R3a covers scalar/list shape mismatches but is
    silent on heterogeneous arrays (e.g., `exclude = ["a", 1, "b"]`).
    Plan should extend R3a with element-type rule: list-valued
    keys reject non-string elements with the same exit-2 hard
    error.

12. **Multi-CLI-warning ordering edge cases** (adversarial F-PASS4-3
    + feasibility F7). When BOTH `min_severity_relaxed` AND
    `all_files_excluded` fire on the same invocation: (a) does
    `all_files_excluded` short-circuit `engine.run` (recommended:
    yes); (b) what's the deterministic order in
    `report.runtime_warnings` (recommended: alphabetical by
    category — `all_files_excluded` then `min_severity_relaxed`).
    Plan pins the contract; tests enforce it.

13. **R23b skip-predicate fail-open on matrix drift** (adversarial
    F-PASS4-6). When CI matrix advances past py3.12 (e.g.,
    `python = ["3.12", "3.13"]`), the hard-coded
    `sys.version_info[:2] != (3, 12)` predicate skips on every
    cell silently. Plan should add a meta-test that asserts at
    least one cell ran the perf smoke (CI fails if zero), OR
    change the predicate to a floor (`>= (3, 12)` AND
    `sys.platform == "linux"`) with documented re-baselining
    expectation when new Python versions land.

14. **R1a `.git`-as-terminator becomes a new attacker primitive**
    (security F-PASS4-1, F-PASS4-3 + adversarial F-PASS4-1). On
    shared filesystems where an attacker can `mkdir
    /tmp/attack/.git`, walk-up termination is now controllable by
    the attacker. The fix narrowed walk-to-root but the residual
    surface is unanalyzed in the doc. Plan should add to README
    "Security Considerations" subsection: walk-up trust assumes
    any write to a parent of CWD is already a higher-stakes
    compromise than pyproject injection; operators in untrusted-
    parent-CWD environments should pass `--no-config` or
    `--config <pinned-path>`.

15. **No-`.git` CI environment walk-up reaches `/`** (security
    F-PASS4-2). In pip-install-from-tarball CI environments with
    no checkout, walk-up traverses to root. Plan should document
    as residual risk in README; recommend `--no-config` for
    no-`.git` environments. Optionally emit a one-line stderr
    note when walk-up reaches `/` without finding `.git`.

16. **R21a stderr message content safety** (security F-PASS4-6).
    `rule_exception` warning message field may include exception
    tracebacks or internal filesystem paths. Plan should constrain
    message construction: only `exception_type` string + sanitized
    message; never raw tracebacks or paths. Analogous to R5a's
    `tomli` content-safety constraint.

17. **R21a SARIF `descriptor.id` retrofit needs `tool.driver.notifications`
    declaration** (feasibility F4 + security partial). Per SARIF
    2.1.0 §3.58, descriptor references must resolve against
    `tool.driver.notifications[]`. Plan picks: (a) declare the
    notification descriptors in `tool.driver.notifications`, OR
    (b) drop `descriptor.id` and use `properties.subcategory` for
    filtering.

18. **R3a schema-validation API shape unspecified** (feasibility
    F5). The codebase has no pydantic/attrs/msgspec; U2 will
    write the validator from scratch. Plan picks: TypedDict +
    isinstance checks, or `@dataclass` with `from_dict` classmethod,
    or central `validate(table) -> ResolvedConfig` function.

19. **R13b cross-reference to Forward-Looking Risks** (security
    F-PASS4-4). R13b's UX framing has no pointer to "Configuration-
    data bypass posture beyond D5" subsection. Future contributors
    reading R13b's "not a security control" framing won't know
    where the security framing actually lives. Plan adds the
    cross-reference in R13b's text.

20. **D5 scope width** (scope-guardian F4-1). Pass 3 added 7
    requirements without closing pass-2's open items (`--no-config`
    speculative, R15-R16 multi-profile premature). The D5/D5b
    split was rejected (P1-C) but pass 3's scope additions widened
    the delivery further. Plan considers two reductions: (a) cut
    R21a `>5` summarization (solves a D6 problem at D5 scale where
    one rule pack can't trigger it); (b) narrow R15 to scalar-only
    (multi-profile composition has no use case at one rule pack).
    Both are scope-reduction options the plan can adopt without
    redoing brainstorm-level decisions.

21. **R21a per-formatter render shape vs. helper alternative**
    (product-lens NEW-P2-B). Hardcoding per-category render code
    in 3 formatters means every D6+ category author touches all 4
    formatters. Plan considers a single render helper
    (`LintRuntimeWarning.render(formatter_kind) -> str`) so adding
    categories is compositional, not enumerative.

22. **F6 prioritization defense one-sidedness** (product-lens
    NEW-P1 + adversarial F-PASS4-7). The "Why D5 before D6"
    subsection argues all three reasons defend D5-first; only
    Reason 2 (config-retrofit) is load-bearing for the full D5
    bundle. The steel-man "ship R18 alone as D4.5; defer config
    + exclusion until after D6 ships rules" is not pressure-
    tested. Plan considers whether D5-first is a preference or a
    lock-in.

23. **Identity Bet posture ambiguity** (adversarial F-PASS4-9 +
    product-lens NEW-P4). KD-1's "Identity Bet" framing
    explicitly accepts that D6 may pick a config-string-driven
    plugin shape, contradicting the Python-native thesis. Pick:
    (a) thesis is load-bearing — D6 MUST justify any deviation;
    or (b) thesis is preference — D6 picks freely. Current text
    is implicitly (b) but the framing reads as (a). Plan picks
    explicitly. Also: Identity Bet language should not propagate
    to user-facing artifacts (README, --help, CHANGELOG) where
    it signals product-direction uncertainty.

24. **Three-layer mitigation asymmetry** (adversarial F-PASS4-8).
    "Configuration-data bypass posture beyond D5" lists 3
    mitigation layers; layer 1 is hedged ("D5 OR near-term
    follow-up"), layer 2 is out-of-scope (organizational policy),
    layer 3 is conditional vapor ("if demand emerges"). Plan
    commits layer 1 (README "Security Considerations" subsection)
    as a D5 Success Criterion and re-labels layers 2–3 as
    "guidance" not "mitigation."

25. **R18b 1.0 semver commitment without 1.0 surface defined**
    (product-lens NEW-P5). R18b's disclaimer text commits to
    "The 1.0 release will commit to semver compatibility for the
    public surface" without defining what the public surface is
    (Python dataclass shapes, JSON schema, SARIF properties, CLI
    flags, exit codes). Plan softens to "The 1.0 release will
    define the stable public surface and commit to semver
    compatibility for that surface."

These items are tracked here so /ce:plan's brainstorm-review
pressure-test passes inherit them as known concerns without
needing to re-derive them from raw reviewer output.

## Next Steps

1. `/ce:plan` for D5 with this document as origin. Per
   `protokit_lint_delivery_workflow.md`, the workflow is:
   brainstorm → plan (with brainstorm-review pressure-test passes) →
   per-unit `/ce:work` → per-unit `/ce:review` → ce:review follow-ups.
2. Plan should decompose into implementation units. Provisional
   shape (the planner gets to redo this):
   - **U1**: dependencies + pyproject parsing module + walk-up discovery + `--config` / `--no-config` flags.
   - **U2**: schema validation (Tier I keys, hard error on unknown,
     reserved-namespace error), precedence engine.
   - **U3**: `--exclude` CLI flag + pyproject `exclude` + `pathspec`
     integration + `FileDescriptorProto.name` matching.
   - **U4**: D3 R12 fold-in + F3/F4 expansions. Literal extension
     (4 categories total: existing 2 + `min_severity_relaxed` +
     `all_files_excluded`), `rule_id: str | None` (R18 BREAKING),
     R19 trigger logic with CLI-side emission (R19a), R13b
     all-files-excluded engine check, formatter render code
     across `lint_human` / `lint_junit` / `lint_sarif` (R21a),
     stderr breadcrumb removal (R21).
   - **U5**: A5 perf smoke test + synthetic `.proto` fixture.
   - **U6**: README + CHANGELOG + static-analysis ratchet additions.
3. Run `compound-engineering:document-review` on this brainstorm
   before planning to surface any P0/P1 gaps.

---

**Brainstorm session metadata**

- **Initial brainstorm**: Eight decisions resolved (Decisions 1–8
  in session). Reframe at Decision 6 (initially recommended
  empty-string sentinel; reversed to `str | None` after pressure-
  test). All decisions cross-referenced against industry prior
  art (flake8, ruff, mypy, pylint, black, pre-commit, pytest,
  bandit, coverage.py, sphinx, isort) at Decisions 1, 4, 5.
  `next_delivery_d5.md` memory pointer + `TODOS.md` D5 entry
  consulted at session start.
- **4-pass document review** with 6 personas (coherence,
  feasibility, product-lens, security-lens, scope-guardian,
  adversarial):
  - **Pass 1**: 11 auto-fixes + 6 P1 design decisions (F1–F6).
  - **Pass 2**: diagnostic; surfaced new findings introduced by
    pass-1 refinements (R12/R17 collision, formatter gaps, etc.).
  - **Pass 3**: 8 concrete-bug auto-fixes + 5 P1 design
    decisions (P1-A through P1-E) + 7 P2/P3 fixes. Net 20
    refinements.
  - **Pass 4** (2026-05-10): 3 concrete-bug P1 auto-fixes
    (worktree `.git`-as-file, R21 line range 419-424, formatter
    stderr architectural decision via CLI-side emission). 15
    second-order themes documented in Outstanding Questions
    11–25 for /ce:plan to absorb. Adversarial meta-observation
    confirmed diminishing returns.
- **Total refinements across 4 passes**: ~57 distinct items
  resolved or documented. Doc graduated from initial draft to
  plan-ready with explicit Outstanding Questions covering the
  documentation-vs-mechanism asymmetries pass 4 surfaced.
