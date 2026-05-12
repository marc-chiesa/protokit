# Changelog

All notable changes to `protokit` are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/).

## Unreleased

### Added
- `protokit.schema` — descriptor-level compatibility checker with 17 built-in
  rules, four compatibility profiles (`WIRE`, `CONSUMER_SAFE`,
  `PRODUCER_SAFE`, `STRICT`), and a pluggable rule API.
- `protokit compat` CLI subcommand for schema compatibility checks.
- `protokit.schema.SchemaChecker` engine, `CompatibilityPolicy` for
  reusable configuration bundles, and `FieldRuleContext` /
  `MessageRuleContext` for emit-style plugins.
- Rule-pack loading via `SchemaChecker.load_rule_pack(module)` and the
  CLI `--rule-pack MODULE` flag. Rule packs are plain Python modules
  exposing a `RULES = [(rule_id, fn), ...]` list.
- **`protokit.formatters` — pluggable output formatter system** spanning
  both CLIs. Four `FormatterKind` values (`DIFF`, `COMPAT`,
  `COMPAT_HISTORY`, `COMPAT_BISECT`); user packs register via
  `register_formatter(name, fn, *, kind)` or the CLI's
  `--formatter-module MODULE` (repeatable, mirrors `--rule-pack`).
  Built-in names (`human`, `json`, `junit`, `sarif`) are reserved
  against override.
- **JUnit XML built-ins** for every kind. `protokit diff --format junit`
  uses a binary-result single-testcase pattern (one assertion per
  comparison); `protokit compat {check,history,bisect,ci} --format junit`
  uses per-finding testcases. Output validates against the Apache Ant
  reference JUnit xsd consumed by Jenkins, GitLab, GitHub Actions
  test-result actions, CircleCI, and TeamCity.
- **SARIF 2.1.0 built-ins** for every compat kind (`COMPAT`,
  `COMPAT_HISTORY`, `COMPAT_BISECT`) — consumable by GitHub Code
  Scanning, GitLab security dashboards, and any OASIS SARIF
  consumer. Severity mapping: WIRE+SEMANTIC → `"error"`, POLICY →
  `"warning"`. Aggregate kinds attach `partialFingerprints.commit`
  for per-commit grouping. SARIF for the DIFF kind is intentionally
  omitted — message diffs don't fit SARIF's rule/result model.
- `protokit.schema.HistoryReport`, `protokit.schema.BisectReport`,
  `protokit.schema.HistoryEntry`, and `protokit.schema.CommitDiagnostic`
  promoted to public dataclasses. `protokit.schema.Diagnostic` now
  re-exported as well.
- `protokit.schema.git.commit_subject(ref)` helper.
- `examples/custom_formatter.py` Slack-summary demo for the
  pluggable formatter API.
- pytest-based test coverage: 700+ tests including formatter
  registry semantics, built-in coverage, JUnit xsd validation, SARIF
  schema validation, CLI dispatch, two-phase pack rollback, formatter
  exception fail-fast, and the stdout-write guard.

### Changed
- `--format` on every CLI subcommand is now a free-form string instead
  of a fixed `click.Choice`. Unknown values exit 2 with the available
  formatter list for the subcommand's kind. Case-insensitivity from
  the prior `Choice(..., case_sensitive=False)` is preserved.
- `--quiet` mutual-exclusion widened: previously rejected
  `--format json` only; now rejects every non-`human` formatter
  (junit, sarif, custom packs) so structured output is never
  silently swallowed.
- **Error message wording** for two existing rejections changed.
  Exit codes are unchanged (still 2 for both), but CI scripts that
  parse stderr text need updating:
  - Unknown `--format`: was Click's auto `"Invalid value for '--format':
    'X' is not 'human' or 'json'"`, now `"unknown formatter 'X'.
    Available for {KIND}: human, json, junit, sarif"`.
  - `--quiet --format json`: was `"--quiet and --format json are
    mutually exclusive"`, now `"--quiet is incompatible with structured
    output format 'X'. Drop --quiet, or pick --format human"`.
  - Built-in formatter shadowing via `--formatter-module` now reports
    `"formatter pack 'X' conflicts with a reserved built-in name: ..."`
    (distinct prefix from the generic `"failed to load formatter pack"`).
- `protokit.schema.Diagnostic` is now exported from
  `protokit.schema.__all__` (was importable only via the
  `protokit.message` path).

### Changed — BREAKING
- **Distribution name renamed** from `proto-differ` to `protokit`.
- **Import root renamed** from `proto_differ` to `protokit`. The
  top-level package is now intentionally empty — import from the two
  subpackages directly:
  - `proto_differ.*` → `protokit.message.*`
  - (no `protokit` top-level re-exports; explicit namespacing only)
- **CLI entry point renamed** from `pbdiff` to `protokit`, now with
  subcommands:
  - `pbdiff [args]` → `protokit diff [args]`
  - `protokit compat [args]` — new schema compatibility command.
- **pytest plugin import path** changed:
  - `from proto_differ.pytest_plugin import pytest_assertrepr_compare`
    → `from protokit.message.pytest_plugin import pytest_assertrepr_compare`

### Changed — BREAKING
- **Distribution name renamed** from `proto-differ` to `protokit`.
- **Import root renamed** from `proto_differ` to `protokit`. The
  top-level package is now intentionally empty — import from the two
  subpackages directly:
  - `proto_differ.*` → `protokit.message.*`
  - (no `protokit` top-level re-exports; explicit namespacing only)
- **CLI entry point renamed** from `pbdiff` to `protokit`, now with
  subcommands:
  - `pbdiff [args]` → `protokit diff [args]`
  - `protokit compat [args]` — new schema compatibility command.
- **pytest plugin import path** changed:
  - `from proto_differ.pytest_plugin import pytest_assertrepr_compare`
    → `from protokit.message.pytest_plugin import pytest_assertrepr_compare`

There is no compatibility shim — existing imports must be updated.
The rename lands as a single breaking change on the path to 0.2.

### BREAKING (D5 U3 — `protokit lint` runtime warnings)

- `LintRuntimeWarning.rule_id` widened from `str` to `str | None`
  (D5 U3). Engine-emitted categories (`rule_exception`,
  `unloaded_rule`) continue to populate a non-`None` string at every
  emit site. CLI-emitted categories — `all_files_excluded` (D5 U3,
  fires when `--exclude` / `[tool.protokit.lint] exclude` drops every
  input file) and `min_severity_relaxed` (D5 U4, fires when the
  resolved `min_severity` relaxes the composed profile floor) —
  populate `rule_id=None` because they are not scoped to a single
  rule.
- **JSON wire format**: `report.runtime_warnings[*].rule_id` is now
  `null`-capable. Consumers strictly typing this field as `string`
  must accept `null` or `Optional<string>`.
- **Python API**: code iterating `w.rule_id.upper()` or
  `w.rule_id.startswith(...)` on the new categories raises
  `AttributeError`. Branch on `w.category` first, then narrow:
  ```python
  if w.category in ("rule_exception", "unloaded_rule"):
      assert w.rule_id is not None  # mypy-strict narrowing
      ...use w.rule_id as str...
  ```
  Mirrors the existing `descriptor_path` / `exception_type` narrowing
  pattern in `LintRuntimeWarning`'s docstring.
- **`LintRuntimeWarning.category` Literal** widened from 2 values
  (`"rule_exception"`, `"unloaded_rule"`) to 4 (adds
  `"min_severity_relaxed"`, `"all_files_excluded"`). Exhaustive
  `match`/`if-elif` with `assert_never()` arms require an additional
  branch.
- Full migration recipes (JSON / SARIF / Python with concrete
  before/after code) land with D5 U6's CHANGELOG fold-in alongside
  the formatter-side wire-format updates (lint_junit / lint_sarif).
  This entry pre-empts the U3→U6 gap for consumers landing the
  BREAKING change in `main` today.

### BREAKING (D5 U4 — `protokit lint` stderr wire format)

D5 U4 routes all runtime warnings through structured emission. The
following stderr patterns are no longer produced; consumers that
grep stderr must switch to the structured channel until D5 U5
restores a human-format hook.

- **`warning[lint-runtime]:` stderr prefix removed.** The stderr
  loop that mirrored every `LintRuntimeWarning` as
  `warning[lint-runtime]: <category>: <message>` was deleted.
  Runtime warnings now travel exclusively in
  `LintReport.runtime_warnings` and surface only through the machine
  formatters (`--format=json` / `--format=junit` / `--format=sarif`).
  Five patterns disappeared from stderr in one cut:
  `warning[lint-runtime]: rule_exception: ...`,
  `warning[lint-runtime]: unloaded_rule: ...`,
  `warning[lint-runtime]: all_files_excluded: ...`,
  `protokit lint: --min-severity=... relaxes profile floor ...`, and
  `protokit lint: [tool.protokit.lint] min_severity=... relaxes
  profile floor ...`. CI scripts pinned to any of these prefixes
  will silently stop matching.
- **`min_severity_relaxed` message format changed.** The U2
  breadcrumb was prefixed with `protokit lint: `. The U4 structured
  message drops that prefix and starts directly with the source
  attribution: `--min-severity=warning relaxes profile floor from
  error to warning` (CLI-source),
  `[tool.protokit.lint] min_severity=warning relaxes profile floor
  from error to warning` (pyproject-source), or the CLI form with
  `(overriding pyproject min_severity=info)` appended (both-source).
  Read via `parsed["runtime_warnings"][i]["message"]` in
  `--format=json`.
- **`all_files_excluded` message format changed.** The U3 message
  read `all N input file(s) excluded by patterns: PATTERN_LIST`.
  U4 attributes the source: `all N input file(s) excluded by
  --exclude patterns: ...` (CLI-only),
  `all N input file(s) excluded by [tool.protokit.lint] exclude
  patterns: ...` (pyproject-only), or
  `all N input file(s) excluded by --exclude and
  [tool.protokit.lint] exclude patterns: ...` (both). Consumers
  matching the substring `excluded by patterns:` no longer match.
- **`--format=human` regression window (U4 → U5).** The U4 → U5
  window in which `--format=human` (the default) surfaced zero
  runtime warnings is now CLOSED — see the "BREAKING (D5 U5)"
  entry below for the restored envelope shape. Until U5 shipped,
  `--format=human` consumers had to fall back to `--format=json`
  to observe runtime warnings; that fallback is no longer required
  for visibility, though it remains the right choice for full-fidelity
  machine consumption (the human hook truncates per-category above
  an internal threshold; see U5 entry).

  **Migration recipe (human-format CI, transitional):** during the
  U4-only window CI scripts replaced `protokit lint <args>` with
  `protokit lint --format=json <args> | jq '.runtime_warnings'`,
  or set `format = "json"` in `[tool.protokit.lint]` and parsed
  the emitted JSON. Reverting to `--format=human` once U5 shipped
  restores stderr emission under the NEW envelope shape — see U5
  entry for the new prefix.

### BREAKING (D5 U5 — `protokit lint` cross-formatter runtime-warning surfaces)

D5 U5 materializes three consumer-visible wire-format surfaces. The
agent-native `--format=json` channel is unchanged. Each new surface
is additive at the document level but introduces a new shape
consumers may need to parse:

- **`--format=human` stderr envelope restored.** The U4→U5 silent
  window for `--format=human` is closed. Runtime warnings now
  emit to stderr as:

      protokit lint: warning [<category>]: <message>

  This is a NEW shape — distinct from both the U3-era
  `warning[lint-runtime]: <category>: <message>` (REMOVED in U4)
  and the U2-era `protokit lint: <bare-message>` breadcrumb
  (REMOVED in U4). CI scripts grepping `protokit lint: warning [`
  match. The four current categories — `rule_exception`,
  `unloaded_rule`, `min_severity_relaxed`, `all_files_excluded` —
  all render under this envelope. The hook is NOT gated by
  `--quiet` (KTD-6); only stdout findings are. To suppress
  stderr warnings, route them through `--format=json` instead.

  **Summarization above per-category threshold.** When a single
  category produces more than an internal threshold of warnings
  (currently 5; module-level constant `_LINT_HUMAN_SUMMARIZATION_THRESHOLD`),
  the human hook emits the first `<threshold>` individual lines
  then a single collapse line:

      protokit lint: warning [<category>]: ... and <N> more — use --format=json for full details

  Machine formatters (`json` / `junit` / `sarif`) emit ALL warnings
  unconditionally; summarization is human-only. Agents needing
  full fidelity must use `--format=json`.

- **`--format=junit` `<system-out>` dual line format.** The
  testsuite's `<system-out>` body now contains TWO incompatible
  line shapes joined by newlines:

  1. Compile diagnostics (pre-U5; unchanged): `<level> [<category>]: <message>`
  2. Runtime warnings (NEW in U5): `[<category>] <message>`

  Compile diagnostics precede runtime warnings within the block.
  Consumers with a strict prefix regex anchored to the leading
  level token (`^(warning|error|info) \[`) will not match the new
  runtime-warning lines. Two distinguishing tokens:
  compile-diagnostic lines start with a word, runtime-warning
  lines start with `[`.

- **`--format=sarif` `runs[].properties.runtime_warnings` array.**
  SARIF runtime warnings ride on a `propertyBag` extension under
  the run object — INTENTIONALLY separate from the existing
  `runs[].invocations[].toolExecutionNotifications` array (which
  remains compile-stage diagnostics only per KTD-1). Entry shape:

      {
        "level": "warning",
        "message": {"text": "<warning message>"},
        "properties": {
          "category": "<one of the four categories>",
          "subcategory": "runtime"
        }
      }

  No `descriptor.id` is emitted per KTD-1 — categorization
  travels via `properties.category`. SARIF consumers filter
  `properties.subcategory == "runtime"` to get the dedicated
  channel. The `runs[].properties` block is OMITTED entirely on
  clean runs (zero runtime warnings) so existing pre-U5 SARIF
  documents are byte-for-byte unchanged when no warnings fire.

  **Migration recipe (SARIF consumer):** add a second scan of
  `runs[].properties.runtime_warnings` in addition to the existing
  `runs[].invocations[].toolExecutionNotifications` scan. The two
  arrays carry disjoint event sets. If consumers want a unified
  warning stream, union the two channels on the client side.

  **Migration recipe (JUnit consumer):** if scripts parse
  `<system-out>` for warning lines, extend the leading-token
  regex to accept BOTH `^<level> \[<category>\]:` AND
  `^\[<category>\]`. Runtime-warning lines always appear AFTER
  compile-diagnostic lines within the same `<system-out>` body.

  **Migration recipe (human-format consumer):** match the new
  envelope `protokit lint: warning [<category>]:` on stderr. The
  trailing summarization line includes the literal string
  `use --format=json` so a grep-based consumer hitting the
  threshold knows where to find full-fidelity output.

### Rationale (design decisions)

See `TODOS.md` for the full decision log. Summary:

- Package split: `message/` and `schema/` are sibling subpackages with
  no cross-dependency beyond `FieldPath` / `Warning`. Shared helpers
  live in the underscore-prefixed `_descriptors` and `_cli_utils`
  modules.
- Direction semantics: `Direction.FORWARD` / `Direction.BACKWARD`
  describe **which reader is at risk**, not which side of the schema
  changed. This keeps profile names (`CONSUMER_SAFE` etc.) aligned
  with what they filter.
- Plugin dispatch is fail-closed in the CLI: any plugin exception
  surfaces in `CompatibilityReport.warnings` and causes `protokit
  compat` to exit with code 2, so a broken custom policy never
  silently passes CI.

## 0.1.0 — 2026-04-07 (pre-rename snapshot)

Original `proto-differ` release — Python equivalent of Google's C++
`MessageDifferencer`. See git history at tag `v0.1.0` for the full
feature list; at a high level: 228 tests, structural message diffing,
cross-pool comparison, schema evolution detection, pytest hook, CLI.
