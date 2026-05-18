# Changelog

All notable changes to `protokit` are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/).

> **Pre-1.0 stability disclaimer.** `protokit` is pre-1.0. Minor-version
> releases may include breaking changes to public Python APIs and
> machine output formats (JSON, JUnit, SARIF). Breaking changes are
> flagged in `BREAKING`-prefixed section headings below (formats vary
> across the changelog: `### Changed — BREAKING`, `### BREAKING (D5 U3 ...)`,
> etc.). Consumers should pin to a specific minor version (e.g.,
> `protokit~=0.5.0`) until 1.0 ships. The 1.0 release will **define
> the stable public surface** and commit to semver compatibility for
> that surface.

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

#### Schema linting (D1–D5)

- **`protokit lint` subcommand** — descriptor-level lint runner over
  `.proto` sources or pre-built `FileDescriptorSet` binaries. D1
  landed the engine + cold-import contract; D2 shipped the canonical
  `naming` rule pack (AIP-122 snake_case canary); D3 ratcheted the
  rule-emission contract with the structured `LintRuntimeWarning`
  carrier (`rule_exception`, `unloaded_rule` categories); D5 lands
  the pyproject configuration substrate, file-level exclusion,
  cross-formatter render parity, and the perf-smoke canary.
- **`[tool.protokit.lint]` pyproject table** — auto-discovered by
  walking up from the CWD to the first `.git` directory or file
  (worktree-safe per KTD-7). Recognized keys: `profile` (string or
  list), `exclude` (list of gitignore-style globs), `min_severity`
  (`"info"` / `"warning"` / `"error"`), `max_warnings` (int),
  `format` (formatter name). Unknown keys and type mismatches
  produce a hard exit-2 error naming the recognized keys; list-
  valued keys reject heterogeneous arrays per KTD-5.
- **`--config PATH` / `--no-config`** — pin a specific config file
  or skip pyproject reading entirely. Mutually exclusive at parse
  time. `--config` is strict (missing/unreadable/table-absent/
  invalid-TOML all exit 2 with newline-sanitized stderr); the
  default walk-up is silent-fallback when no `[tool.protokit.lint]`
  table is found.
- **`--exclude PATTERN` (repeatable) / `--no-exclude`** — gitignore-
  style glob exclusion of input files matched against
  `FileDescriptorProto.name`. CLI `--exclude` patterns append to
  the pyproject `exclude` list per R13; `--no-exclude` clears the
  resolved exclude list (CLI + pyproject) at apply-time. When the
  resolved exclude drops every file, a structured
  `LintRuntimeWarning(category="all_files_excluded")` fires and
  `engine.run` short-circuits (no point walking zero files per
  KTD-4).
- **Source-attributed `min_severity_relaxed` warning** — when the
  resolved `min_severity` relaxes the composed profile floor, a
  structured `LintRuntimeWarning(category="min_severity_relaxed")`
  fires post-`engine.run`. The message attributes the source: CLI
  flag, pyproject key, or "both" with the pyproject value carried
  in the message for triage. Replaces the previous unstructured
  stderr breadcrumb.
- **Cross-formatter `LintRuntimeWarning` render parity** — all
  four current categories (`rule_exception`, `unloaded_rule`,
  `min_severity_relaxed`, `all_files_excluded`) render in all four
  built-in formatters: `lint_human` stderr envelope, `lint_json`
  `runtime_warnings` array, `lint_junit` `<system-out>` lines,
  `lint_sarif` `runs[].properties.runtime_warnings` array. Closes
  the D3-era silent-warning regression in three of four formatters.
- **`tests/schema/lint/test_perf_smoke.py`** — catastrophic-regression
  canary on `linux + py3.12` cells. Synthetic 50 files × 20 messages
  × 10 fields = 10,000 fields; threshold loose by design (smoke,
  not benchmark). Skipped via `@pytest.mark.skipif` on other cells;
  the companion `test_perf_smoke_coverage.py` parses
  `.github/workflows/ci.yml` to verify the matrix contains at least
  one predicate-matching cell (fail-closed per KTD-3).
- **`slow` pytest marker** — registered in `pyproject.toml`. The
  D5 perf smoke is the only current consumer; future slow tests
  can join via the same marker. `pytest -m "not slow"` excludes
  them from fast-iteration loops.
- **New deps**: `tomli >= 2.0, < 3` (py<3.11 only; py3.11+ uses
  stdlib `tomllib`) for `[tool.protokit.lint]` parsing; `pathspec
  >= 0.12, < 2` for gitignore-style glob matching. Dev-dep
  additions: `PyYAML >= 6.0, < 7` and `types-PyYAML` for the perf-
  smoke coverage meta-test (uses `yaml.safe_load` exclusively per
  KTD-3 security posture).

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

**Migration recipes (D5 U6 fold-in).** Concrete before/after for
each consumer type:

*JSON consumer migration.* The shape of
`report.runtime_warnings[*]` changed only in the `rule_id` field:
it is now `string | null`. When `rule_id` is `null`, the `category`
field tells you the source — `"min_severity_relaxed"` means
pyproject or CLI relaxed the profile floor; `"all_files_excluded"`
means no files survived `--exclude` / `[tool.protokit.lint] exclude`
filtering. Code that previously did:

```python
for w in parsed["runtime_warnings"]:
    print(w["rule_id"].upper())  # AttributeError on None
```

becomes:

```python
for w in parsed["runtime_warnings"]:
    if w["rule_id"] is not None:
        print(w["rule_id"].upper())
    else:
        # rule_id-less category — branch on w["category"] for triage
        print(f"[{w['category']}] {w['message']}")
```

*SARIF consumer migration.* Read
`runs[].properties.runtime_warnings` in addition to the existing
`runs[].invocations[].toolExecutionNotifications` array. The two
arrays carry disjoint event sets — `toolExecutionNotifications`
remains compile-stage diagnostics only (per KTD-1); the new
`runs[].properties.runtime_warnings` array carries
`LintRuntimeWarning` events. Each entry has shape:

```json
{
  "level": "warning",
  "message": {"text": "<warning message>"},
  "properties": {
    "category": "<one of the four categories>",
    "subcategory": "runtime"
  }
}
```

No `descriptor.id` is emitted (per KTD-1) — categorization travels
via `properties.category`. SARIF consumers wanting a unified
warning stream should union the two channels on the client side.
The `runs[].properties` block is **omitted entirely** on clean
runs (zero runtime warnings); existing pre-U5 SARIF documents are
byte-for-byte unchanged when no warnings fire.

*Python API consumer migration.* Add a `None` branch when
narrowing `LintRuntimeWarning.rule_id`. The mypy-strict pattern
mirrors the existing `descriptor_path` / `exception_type`
narrowing in `LintRuntimeWarning`'s docstring:

```python
def handle(w: LintRuntimeWarning) -> None:
    if w.category in ("rule_exception", "unloaded_rule"):
        assert w.rule_id is not None  # mypy-strict narrowing
        process_rule_scoped_warning(w.rule_id, w.message)
    else:
        # category in ("min_severity_relaxed", "all_files_excluded")
        # rule_id is None; warning is global, not rule-scoped
        process_global_warning(w.category, w.message)
```

Exhaustive `match`/`if-elif` arms with `assert_never()` also
require an additional branch — the `category` Literal widened
from 2 values to 4 (`"rule_exception"`, `"unloaded_rule"`,
`"min_severity_relaxed"`, `"all_files_excluded"`).

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

### D6b — option-aware path + cross-language buf BASIC parity (0.3.0)

D6b adds the first option-aware rules (R6 deprecated-replacement
family) + cross-language buf-BASIC parity (R7 PACKAGE_SAME_* family),
bringing `protokit lint` to **17 of 18 buf BASIC rules**. The 18th
(`package/same-directory`) defers to D6c — its cross-file rule kind
requires new ElementKind + LintLocation discriminant work scoped for
its own architectural delivery. Multi-language teams whose protos
have cross-file option disagreement will see NEW error-severity
findings on the upgrade; the pre-upgrade migration recipe below
covers the 4 demotion paths.

#### Added

- **R6 deprecated-replacement family** — 5 warning-severity rules in
  the `default` profile only: `options/deprecated-{enum,enum-value,
  field,message,method}-must-have-replacement-comment`. First
  option-aware rules + first leading-comment-introspection consumer.
  Rules fire when `*Options.deprecated = true` is set without a
  `[replaced-by: <X>]` leading-comment pointer. The `recommended`
  profile is untouched (R6 has no buf BASIC analogue); severity
  bounded to `warning` to contain the heuristic-regex blast radius.

- **R7 PACKAGE_SAME_\* family** — 7 ERROR-severity rules in BOTH
  `recommended` + `default` profiles, covering cross-language
  namespace consistency:
  - `package/same-go-package` → buf `PACKAGE_SAME_GO_PACKAGE`
  - `package/same-java-package` → buf `PACKAGE_SAME_JAVA_PACKAGE`
  - `package/same-csharp-namespace` → buf `PACKAGE_SAME_CSHARP_NAMESPACE`
  - `package/same-php-namespace` → buf `PACKAGE_SAME_PHP_NAMESPACE`
  - `package/same-ruby-package` → buf `PACKAGE_SAME_RUBY_PACKAGE`
  - `package/same-swift-prefix` → buf `PACKAGE_SAME_SWIFT_PREFIX`
  - `package/same-java-multiple-files` → buf `PACKAGE_SAME_JAVA_MULTIPLE_FILES`

  All-disagreers-fire semantics: every file in a package with a
  divergent value gets one finding per affected option. **Validated
  by U6's empirical parity gate** against 21 SHA-pinned buf v1.69.0
  NDJSON snapshots committed at U4a.

- **R9 `severities_unloaded_rule` category** — 5th value on
  `LintRuntimeWarning.category` Literal. **CLI-synthesized emit
  site MIGRATED** from `"unloaded_rule"` to
  `"severities_unloaded_rule"`; engine-synthesized emit site
  unchanged. Closes the D6a U9 KTD-2 accepted-conflation trip-wire
  so programmatic consumers can switch on `category` instead of
  matching the `"[tool.protokit.lint.severities]"` message substring.

- **Multi-file parity harness extension** at
  `tests/parity/conftest.py` — `BufFinding` NamedTuple +
  `parse_buf_recorded_snapshot()` + `run_protokit_lint_multi_file()`
  + `assert_parity_multi_file()`. Reusable by future multi-file
  rule families (D6c R8 candidate).

- **Empirical parity gate** at `tests/parity/test_parity_package_same.py`
  — 21 parametrized cases + 5 collection-time invariants R25(a-e);
  recorded-snapshot mode runs in the required `test` CI job (no
  BUF_BINARY dependency).

#### Fixed

- **CLI rule-pack idempotency at the BUILTIN_PACKS boundary.** When
  a user passes `--rule-pack=<pack>` for a pack now in BUILTIN_PACKS
  (post-U7), the engine's load_rule_pack short-circuits the second
  load (`engine.py:241-242`) but the CLI's `loaded_packs` list
  would still append a duplicate. That broke the R25 multi-pack
  provenance line's `zip(loaded_packs_tuple,
  _active_rule_ids_per_pack(...).values(), strict=True)` because
  the helper dict de-dups by `pack.__name__` while the tuple did
  not. Fix: dedup `loaded_packs` at CLI append time. Bug was
  unreachable pre-U7 (since `package_same` was not in BUILTIN_PACKS);
  surfaced by U7's idempotency regression tests at flip time.

#### Wire format

- `lint_json["schema_version"]` + `lint_sarif.runs[0].properties.lint_schema_version`
  bumped `"0.2"` → `"0.3"` (shipped at D6b U5). The bump is driven
  ONLY by R9's `LintRuntimeWarning.category` Literal widening per
  the refined bump-contract at `_builtin_lint.py:227-270` (closed
  Literal discriminators vs open severity-string ladders). New
  `rule_id` strings from R6 + R7 do NOT contribute additional
  bumps — `findings` is an additive list and consumers tolerate
  unknown rule_ids.

#### Behavior changes (defaults; demotable)

- **R6 family fires as `warning` on `default` profile only.**
  Teams using `--profile recommended` (the buf-parity default) see
  ZERO new R6 findings. Teams on `default` (or with custom profile
  composition that includes the R6 ruleset) will see deprecated-
  replacement warnings.

- **R7 family fires as `error` on both `recommended` and `default`
  profiles.** Multi-language teams running `protokit lint --profile
  recommended <inputs>` in CI will see NEW error-severity findings
  when cross-file option values disagree within a proto package
  (e.g., `go_package`, `java_package`, `csharp_namespace` differing
  across files in the same package). This is buf BASIC parity
  behavior; surfaces real cross-language config inconsistency.

#### Pre-upgrade migration recipe

Cross-language teams whose CI currently passes on protokit 0.2.0
with `--profile recommended` and whose protos have cross-file option
disagreement will see RED CI on first 0.3.0 invocation.

**Worst-case adoption math.** A 5-file package with disagreement
produces up to 5 × 7 = 35 findings. A 20-file no-package legacy
corpus where the `""`-namespace aggregation kicks in (proto files
without explicit `package` declarations get grouped into the
empty-package bucket and compared as one cross-file scope)
produces up to **140 findings** (20 × 7) on the upgrade. Plan
adoption sizing against the combined worst case for your repo.

**4 numbered demotion paths**, ranked by team situation (not by
"rightness"):

1. **Fix the disagreement** (when the disagreement is unintentional).
   R7 fires because option values differ across files in the same
   package — buf v1.69.0 parity behavior treats this as a correctness
   signal. Decide a canonical value per `option_attr` per package;
   update outlier files to match.

2. **Demote a specific R7 rule to `warning`** (per-rule severity
   escape hatch; suitable for "I want findings to remain visible
   but not fail CI"). Add to `pyproject.toml`:
   ```toml
   [tool.protokit.lint.severities]
   "package/same-go-package" = "warning"
   ```
   Multiple keys compose. Demoted rules still report findings but
   do not fail CI (under default `--min-severity error`). Demote
   to `info` for fully advisory output.

3. **Disable a specific R7 rule** (legitimate for INTENTIONAL
   disagreement that expresses team convention):
   ```toml
   [tool.protokit.lint.severities]
   "package/same-go-package" = "off"
   ```
   Legitimate when the disagreement is by design — e.g., a polyrepo
   where each `.proto` file ships in its own Go module has
   intentionally divergent `go_package` values; demoting
   `package/same-go-package` to `"off"` for this repo is the
   correct long-term answer, NOT a workaround. Disabled rules are
   invisible to downstream consumers of `lint_json`/`lint_sarif`;
   prefer demotion to `warning` when you want findings to remain
   visible.

4. **Pin to the prior minor version** (deferral fallback — last
   resort):
   ```toml
   # pyproject.toml or requirements.txt
   "protokit~=0.2.0"
   ```
   Reserves time to address R7 findings on the team's schedule.
   **Cost**: pinning forgoes future 0.3.x bug fixes for the rule
   families you already use. Prefer paths 1-3 for teams who plan to
   remain on protokit beyond one quarter; re-evaluate at each 0.3.x
   patch release.

**No `pyproject.toml`? Create a minimal one.** Paths 2-3 require a
`pyproject.toml` for the `[tool.protokit.lint.severities]` overlay.
Teams using `requirements.txt`-only Python tooling can add a 3-line
stub at the repo root:

```toml
[tool.protokit.lint.severities]
"package/same-go-package" = "warning"
```

protokit discovers `pyproject.toml` independently of pip/build
tooling — the file does not need to define a build system. Path 4
(version pin in `requirements.txt`) is the only `requirements.txt`-
only escape hatch.

**Accepted-tradeoff scenarios to plan for:**

- **`""`-package aggregation.** Proto files without an explicit
  `package` declaration get grouped into the empty-package bucket.
  On a 20-file no-package legacy corpus, all 7 R7 rules cross-
  compare every file against every other file in that bucket,
  producing the worst-case 140 findings. Mitigations: declare
  `package` on all protos (preferred — gives R7's per-package
  scope a chance to do useful work), OR demote PACKAGE_SAME_* per-
  rule via `[severities]` for known-no-package globs (combine with
  `exclude` for vendored paths).

- **Transitive-import supply chain.** R7 fires across the cross-
  package boundary when a third-party `import` brings in protos
  with divergent option values from your in-repo protos. The
  upstream change can trip your CI even though your repo didn't
  change. Mitigations: pin dependency versions in your build
  graph; OR demote PACKAGE_SAME_* when third-party imports
  introduce conflicts.

- **WKT enforcement.** Users with non-standard `google/protobuf/`
  vendoring (vendored well-known-type stubs with differing option
  values) may see surprise findings against vendored protos.
  Mitigations: `exclude` the vendored path, OR confirm vendoring
  aligns with upstream protobuf option values.

#### Upgrade notes (triage recipe)

1. Run `protokit lint --profile recommended <inputs>` against your
   protos.
2. If exit code 0: no migration needed; the bump is clean.
3. If R7 findings appear: choose one of the 4 demotion paths above
   per rule. Most teams will land on path 1 (fix) for unintentional
   disagreement and path 3 (`"off"` overlay) for intentional
   per-service divergence.
4. If R6 findings appear (default profile only): add `[replaced-by:
   <X>]` comments to deprecated fields / methods / enums, OR
   demote `options/deprecated-*` rules via `[severities]`
   (warning → info).
5. Re-run after applying demotion/fix; commit the updated
   `pyproject.toml` or proto fix.

#### Consumer migration (Python API)

- **`LintRuntimeWarning.category` is a CLOSED Literal DISCRIMINATOR.**
  The 5 enumerated values (`"rule_exception"`, `"unloaded_rule"`,
  `"rule_exit"`, `"rule_pack"`, `"severities_unloaded_rule"`) are
  the complete set; additions trigger a `schema_version` minor
  bump. Consumer switch statements should be exhaustive — contrast
  with `LintSeverity` ordering (an open ladder where additions do
  NOT trigger bumps).

- **`severities_unloaded_rule` is a value MIGRATION, not an
  ADDITION.** The 5th value is the 5th `LintRuntimeWarning.category`
  Literal entry, but the CLI-synthesized emit site MIGRATED from
  the existing `"unloaded_rule"` value; the engine-synthesized
  emit site is unchanged. Consumers switching on `category ==
  "unloaded_rule"` should AUDIT their existing branches — not just
  extend switch tables. The 0.2 → 0.3 `schema_version` bump IS the
  documented signal that consumer switch tables need re-checking.

- **`CompileResult.source_info_descriptors`** (new at D6b U2, the
  source-locations index built from `FileDescriptorSet` before
  `pool.Add()` discards `source_code_info`) is **INTERNAL** — not
  part of the public surface; consumers integrating with the
  compile-result object should treat it as implementation detail.
  R6's leading-comment introspection consumes it via the
  `leading_comment(source_info_descriptors, file_name, path)`
  free function at `protokit.schema.lint.rules.options._comments`.

#### Deferred to D6c

- `package/same-directory` (R8 — 18th buf BASIC rule; cross-file
  rule kind requires new ElementKind + LintLocation discriminant).
- R6 promotion to `error` severity (pending real-world experience
  with the leading-comment heuristic accuracy).
- `strict` profile rule enumeration.
- Per-rule disable/enable CLI flag (R9b) — `[severities] = "off"`
  in pyproject is the current de-facto disable mechanism.

### D6a — `protokit lint` rule library expansion + buf BASIC parity (0.2.0)

D6a grows `protokit lint` from the D2 `naming` canary (1 pack /
9 rules) into a 5-pack / 17-rule library covering buf BASIC parity
for single-language teams. Existing users upgrading from
`protokit 0.1.x` will see new ERROR-severity findings on
previously-green CI (matching buf's BASIC severity posture per
KD-9). Pin to `protokit~=0.1.0` (which means `>=0.1.0, <0.2.0`) if
you want to defer the upgrade; the demotion paths below cover the
common triage flows for users who choose to upgrade now.

- **`BUILTIN_PACKS` expansion (auto-loaded packs).** Four new
  packs join `naming` in the auto-load set: `enum`
  (`no-allow-alias`, `first-value-zero`), `imports`
  (`no-public`, `no-weak`, `unused`), `package` (`defined`,
  `directory-match`), and `file` (`syntax-specified`). Each rule
  is tagged with `source_spec="buf:<RULE_ID>"` for parity
  introspection; documented buf-parity divergences live in the
  rule docstrings (notably `file/syntax-specified` fires on both
  no-syntax AND explicit `syntax = "proto2";` files because the
  compiler emits `fdp.syntax == ""` for both). The auto-load
  expansion is gated on the `--no-builtin-rules` opt-out below.

- **Wire format — `schema_version` field.** `lint_json` output
  gains a top-level `"schema_version": "0.2"` key; `lint_sarif`
  gains `runs[].properties.lint_schema_version: "0.2"` (namespaced
  under SARIF's reserved property bag to coexist with the SARIF
  spec's own `version` field). The bump contract: this constant
  changes any time the JSON/SARIF wire shapes change in a way
  consumers need to detect. Absence of the key (older output) is
  the implicit "0.1" — consumers that need to support pre-0.2
  output should treat a missing `schema_version` as `"0.1"`. The
  JUnit `<system-out>` and human-stderr surfaces are unchanged.

- **Pyproject schema additions.** `[tool.protokit.lint]` accepts
  two new keys:
  - `no_builtin_rules` (bool, default `false`) — when `true`,
    skip loading `BUILTIN_PACKS` entirely. The `--rule-pack
    MODULE` flag (or future pyproject `rule_packs = [...]`)
    becomes load-bearing; without any user pack the engine has
    no rules and exits 2 via the existing `no-rules` error code.
  - `[tool.protokit.lint.severities]` (table; rule_id → severity
    string) — per-rule severity overrides applied AFTER profile
    composition. User overrides always win on collision via a
    post-compose dict-spread (`{**profile_overrides,
    **user_severities}`). Unknown rule_ids fire an `unloaded_rule`
    runtime warning naming each rule_id but do NOT exit error —
    the warning surfaces typos without blocking the lint run.

- **CLI flags.** `--no-builtin-rules` mirrors the pyproject key;
  parameter-source detection (`COMMANDLINE` / `ENVIRONMENT` /
  `DEFAULT_MAP`) drives precedence per the D5 pattern. `protokit
  lint --version` is new — prints `protokit <version> (parity:
  buf <pin>)` where the buf pin is `_BUF_PARITY_PIN` in
  `src/protokit/schema/lint/cli.py` (currently `v1.69.0`,
  cross-referenced with the parity CI job).

- **Profile names — protokit-native + buf aliases.** The primary
  protokit-native profile names are `essentials` (lightweight
  forward-placeholder), `recommended` (buf BASIC parity; the
  17-rule D6a set), and `default` (forward-placeholder for the
  D6b differentiator; structurally equal to `recommended` in
  D6a). Buf compatibility aliases resolve at the
  `_coerce_profile` input boundary in `_config.py`:
  `minimal → essentials`, `basic → recommended`. A user pack
  declaring `profiles=("basic",)` will never match — the alias
  resolves before pack profile-name lookup. Document this in
  custom rule packs.

- **Opt-out / demotion paths.** Pre-1.0 the version bump itself
  is the breaking-change signal; the four available demotion
  paths are:
  1. **Pin** — `protokit~=0.1.0` means `>=0.1.0, <0.2.0`, so
     pinned users are NOT auto-bumped.
  2. **Full opt-out** — `--no-builtin-rules` (CLI) or
     `[tool.protokit.lint] no_builtin_rules = true` (pyproject)
     skips `BUILTIN_PACKS` entirely. Pair with `--rule-pack
     MODULE` to supply a custom rule set; an empty rule set
     exits 2 via `no-rules`.
  3. **Global severity demotion** — `--min-severity=warning`
     (CLI) or `[tool.protokit.lint] min_severity = "warning"`
     (pyproject) raises the floor across all rules. This is the
     coarse hammer; finer control via the next option.
  4. **Per-rule demotion** —
     `[tool.protokit.lint.severities] "imports/unused" = "warning"`
     (or `"info"`) demotes one rule without touching the rest.
     Multiple keys compose. User overrides always win.

- **Upgrade notes.** The recommended triage path for an existing
  `protokit 0.1.x` user upgrading to `0.2.0`:
  1. Upgrade `protokit` (`pip install -U protokit` or equivalent).
  2. Run `protokit lint --format=json <inputs> | jq
     '.findings[] | {rule_id, severity, location}'` to enumerate
     the new findings.
  3. Decide per finding: fix the schema, or demote the rule. If
     a whole category is noise for your project (e.g.,
     `imports/unused` on third-party vendored protos), the
     pyproject `[severities]` table is the lowest-cost option;
     pair with `exclude` for vendored paths.
  4. For an emergency-revert, pin to `protokit~=0.1.0` and file
     an issue describing the false-positive — pre-1.0 is the
     right time to surface gaps in the rule heuristics.

- **Parity test infrastructure (advisory).** `tests/parity/`
  ships local fixtures + a pinned-buf CI job that runs against
  every PR. The job is **advisory (J2)** — failures surface as a
  yellow check, not a red block, so buf release shifts don't
  hold up unrelated PRs. A separate scheduled "buf release
  watcher" workflow opens a tracking issue weekly when upstream
  ships a newer stable release; pin bumps land as discrete
  reviewed PRs.

- **Public Surface (DRAFT) additions.** Four new rows in the
  README's Public Surface DRAFT table: protokit-native profile
  names, buf alias mapping, `lint_json` top-level
  `schema_version`, and SARIF `runs[].properties.lint_schema_version`.
  Output ordering (sorted by `(file, location, rule_id)` per
  KTD-6) is intentionally NOT listed as a Public Surface row —
  it is an implementation detail subject to change pre-1.0;
  consumers should not parse findings by positional invariants.

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
