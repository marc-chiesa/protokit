---
title: Pluggable output formatters + JUnit (Phase 1.5b CI release)
type: feat
status: active
date: 2026-04-18
deepened: 2026-04-19
origin: ~/.gstack/projects/python_message_differencer/marc-main-brainstorm-phase-1.5b-ci-release-20260418-115400.md
---

# Pluggable output formatters + JUnit (Phase 1.5b CI release)

## Overview

Make `protokit compat` first-class in CI pipelines. Ship JUnit XML output for compat checks plus a pluggable formatter API so plugin authors can add internal-dashboard, Slack-summary, SARIF, or any other downstream-specific format without forking the CLI. Unifies output formatters across both protokit CLIs (`protokit diff` and all `protokit compat` subcommands).

## Problem Frame

`protokit compat ci` is the canonical CI gate, but it emits only `human` or `json`. The CI surfaces users actually care about — Jenkins/GitLab Tests tabs, GitHub Actions Test results, CircleCI/TeamCity dashboards — all consume JUnit XML natively. Today, every team integrating protokit into their CI must post-process JSON or wrap the CLI in their own JUnit-emitting shell. That friction caps adoption at "we considered it" for teams without time to write integration glue.

A second gap: plugin authors who want to ship custom output formats (org-specific dashboards, Slack summaries, SARIF for GitHub Code Scanning) have to fork the CLI. The compat plugin system already lets users add custom rules; there's no equivalent extension point for output.

This plan closes both gaps. Two of the four "accepted but never shipped" items from the 2026-04-12 CEO plan provide the scope:
- Item #3: pluggable `register_formatter()` API — the extension point.
- Item #4: built-in JUnit formatter — the reference output that proves the API and unblocks CI integration.

The brainstorm pressure-tested the other two CEO-plan items and deferred them: #1 (schema diff report) merges into Phase 3 docgen (same descriptor-traversal engine produces changelogs); #2 (linting) earns its own brainstorm before any commitment.

**Tracking note.** This plan also closes the documentation drift where `TODOS.md` and the 2026-04-12 CEO plan list items #3 and #4 as committed Phase 1 scope. Step 6 updates those docs to reflect what shipped vs. deferred.

(see origin: `~/.gstack/projects/python_message_differencer/marc-main-brainstorm-phase-1.5b-ci-release-20260418-115400.md`)

## Requirements Trace

- R1. One unified `register_formatter()` API covers both CLIs and all four report types: `DiffResult`, `CompatibilityReport`, `HistoryReport`, `BisectReport`.
- R2. Ship `human` and `json` built-ins (extracted from current CLI code) for all four kinds. Ship `junit` built-ins for all four kinds: three compat kinds use per-finding testcase rendering; DIFF uses binary-result rendering (single testcase, pass if equal / fail if differs, with per-difference detail in the failure body). Ship `sarif` built-ins for the three compat kinds (not DIFF — SARIF's "result/finding" model doesn't fit message diffs).
- R3a. `protokit compat ci --format junit` emits a single parseable JUnit XML document that validates against the GitHub Actions `publish-test-results` JUnit consumer schema. Other CI consumers (Jenkins, GitLab, CircleCI, TeamCity) are best-effort: rendering choices are optimized for the GH Actions schema; users on stricter consumers may need a custom formatter via `--formatter-module`.
- R3b. `protokit compat ci --format sarif` emits a SARIF 2.1.0 JSON document that validates against the OASIS SARIF 2.1.0 JSON schema and is consumable by GitHub Code Scanning. Rules referenced in `results[]` are declared in `runs[0].tool.driver.rules` with human-readable descriptions.
- R4. Users load custom formatters via `--formatter-module MODULE` (repeatable, mirrors `--rule-pack`).
- R5. Zero regression on existing `human` / `json` outputs. JSON output is **structurally equivalent** (`json.loads(new) == json.loads(old)`) under regression tests; human output visually identical (text snapshot). Existing per-key assertions in `tests/schema/test_cli.py` are the authoritative JSON contract.
- R6. Unknown `--format` exits 2 with an actionable message listing available formatters for that kind.
- R7. Formatter exceptions fail the CLI fast (exit 2 with `Error: formatter '{name}' raised {ExceptionType}: {message}`); they do not silently swallow output.
- R8. README, CHANGELOG, and TODOS.md updated; CEO plan items #3 and #4 marked done with date; items #1 and #2 marked explicitly deferred with rationale.

## Scope Boundaries

- No GitHub Actions inline-annotations formatter (`::error file=...::`) as a built-in. Users can write one via the pluggable API; SARIF covers the inline-annotation path for GitHub Code Scanning users.
- No SARIF for `DIFF` kind. SARIF's `Result`/`Finding` model represents code quality issues with `ruleId` + `level`; a message-value diff has no natural rule and no natural severity. Users who need a diff-as-SARIF flow can write one via the pluggable API.
- No async/streaming formatters. Synchronous `str`-returning is sufficient.
- No formatter composition (`--format junit,json` to emit multiple). Pick one via `--format`.
- No auto-discovery via Python entry points. Explicit `--formatter-module` import only.
- No promotion of `Verdict` enum or `filter_for_level` API surface — those are pre-existing additions, untouched.

### Deferred to Separate Tasks

- Schema diff report (item #1 from CEO plan): merge into Phase 3 docgen when changelogs are built.
- Linting engine (item #2 from CEO plan): earns its own brainstorm. Out of scope here.

## Context & Research

### Relevant Code and Patterns

- `src/protokit/schema/cli.py:130-152` — `_load_rule_packs(checker, module_names)` helper. Uses `importlib.import_module` + attribute access, fails via `error_exit`. **Mirror this pattern** for `_load_formatter_packs`.
- `src/protokit/schema/cli.py:776-780` — current `--format` declared as `click.Choice(["human", "json"])` on `compat check`. Replicated on `history` (line ~966), `bisect` (~1243), `ci` (~1551). All four sites need the same refactor.
- `src/protokit/message/cli.py:398` — current `--format` for `protokit diff`, same `click.Choice` pattern.
- `src/protokit/schema/cli.py:219` — `_format_finding_human(finding)` and surrounding rendering helpers. These are the bodies to extract into the new `_builtin_compat.py`.
- `src/protokit/message/cli.py:196` — `_format_diff_human(diff)` and surrounding rendering helpers; extraction targets for `_builtin_diff.py`.
- `src/protokit/schema/model.py` — exports `CompatibilityReport`, `Finding`, `Severity`, `Direction`, `Verdict`. **Note: `Diagnostic` is NOT currently in `protokit.schema.__all__`** (verified at `src/protokit/schema/__init__.py:41-56`); it is imported into `schema/model.py` only as a field type. Unit 1 must add `Diagnostic` and the new `CommitDiagnostic` / `HistoryEntry` / `HistoryReport` / `BisectReport` to the public exports.
- `src/protokit/message/model.py:79-125` — `Diagnostic` dataclass with `level: str` field (`"info"|"warning"|"error"`). Reuse for aggregate diagnostics on the new aggregate dataclasses.
- `src/protokit/schema/cli.py` (history JSON construction ~lines 1156-1163 and bisect JSON ~lines 1371-1388, per audit) — these inline dict builders are the points to refactor into dataclass construction.
- `tests/proto_builder.py` and `tests/schema/helpers.py` — shared test helpers; reuse them in new formatter tests rather than re-inventing fixtures.
- Test layout convention: top-level `tests/test_<topic>.py` for message-side and shared concerns; `tests/schema/test_<topic>.py` for schema-side. Formatters are top-level (`protokit.formatters`), so tests go in `tests/`.

### Institutional Learnings

- The repo has no `docs/solutions/` directory and no recorded solutions to consult.
- `Diagnostic` (renamed from `Warning` in Phase 2) keeps `Warning = Diagnostic` as a backward-compat alias. New code should use `Diagnostic` directly. (See TODOS.md decision log.)
- Plugin failures are fail-closed via `report.diagnostics` (level=`"error"`); CLI exits 2 when any error diagnostic is present. Formatters use the **opposite** policy by design — they cannot corrupt the report verdict, only rendering, so a formatter exception should hard-fail rather than degrade silently.

### External References

- GitHub Actions `publish-test-results` JUnit schema: https://github.com/EnricoMi/publish-unit-test-result-action/blob/main/test/files/junit-xml/JUnit.xsd — concrete validation target for R3a.
- SARIF 2.1.0 JSON schema (OASIS standard, hosted by SchemaStore): https://json.schemastore.org/sarif-2.1.0.json — concrete validation target for R3b.
- SARIF 2.1.0 specification: https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html — reference for field semantics.
- `xmlschema` Python library (pip-installable, pure Python) — used in tests to validate JUnit output against the published xsd.
- `jsonschema` Python library (pip-installable, pure Python) — used in tests to validate SARIF output against the published JSON schema.

## Key Technical Decisions

- **One unified `register_formatter()` API with a `FormatterKind` discriminator** rather than per-CLI registries or polymorphic single registry. Reason: explicit kind keeps each formatter aware of which report shape it consumes; CLI can validate `--format junit` is available for the requesting subcommand's kind; users see one API across both CLIs. (see origin)
- **Four formatter kinds**: `DIFF`, `COMPAT`, `COMPAT_HISTORY`, `COMPAT_BISECT`. Aggregate kinds get full pluggability (Option B in the brainstorm) so users can override aggregate rendering. New `HistoryReport` / `BisectReport` dataclasses become public API.
- **`--format` declared as `click.STRING` not `click.Choice`**. Reason: `click.Choice` evaluates at CLI definition time, before `--formatter-module` flags load user-supplied formatters. Manual validation runs after flag processing. (see origin: P1 patch)
- **Formatter signature**: `Callable[[Report, FormatterContext], str]`. `FormatterContext` is a frozen dataclass carrying: `subcommand: str`; `target_type: str | None` (single-type compat); `old_target_type: str | None` and `new_target_type: str | None` (cross-type compat — both populated when `--old-type X --new-type Y` is used; `target_type` is set to whichever is non-None when they match, else `None`); `level: str | None` (CLI flag string like `"consumer-safe"`, NOT enum name `"CONSUMER_SAFE"`); `range_spec: str | None`; `old_ref: str | None`, `new_ref: str | None`, `proto_file: str | None` (git-mode context for history/bisect/check-since/ci formatters that want to emit their own header). Stateless, str-returning, no streaming in v1.
- **Formatter names are case-insensitive.** `register_formatter` and `get_formatter` lowercase-normalize the name. Preserves today's `case_sensitive=False` Click behavior; existing `output_format.lower()` checks keep working.
- **Formatter MUST be a pure str-returning function.** Side-effect writes to stdout/stderr are unsupported. CLI guards by redirecting `sys.stdout` to an in-memory buffer for the duration of the formatter call; non-empty buffer triggers a contract-violation error (exit 2). This prevents partial-output corruption when a formatter writes some bytes and then raises.
- **JUnit empty-testsuite handling**: zero `<testcase>` children would cause some CI systems to interpret as "no tests ran." Emit a single passing `<testcase classname="compat" name="compatible"/>` when there are no findings AND no error-level diagnostics. Warning-only diagnostics still produce the passing testcase (warnings don't make testcases). (see origin: P1 patch)
- **DIFF JUnit uses binary-result pattern, not per-difference testcases.** For COMPAT, each finding is an independent rule violation — natural per-testcase granularity. For DIFF, the whole comparison is a single assertion ("these two messages are equal") with per-field differences as evidence of one failure. Per-difference testcase rendering would produce "100 tests / 100 failures" noise in CI aggregators with no more actionable information than "1 test / 1 failure with a 100-line body." A single testcase that passes when messages match and fails with a detailed body when they don't is the cleaner semantic. This is a principled divergence from the COMPAT pattern driven by the difference in underlying semantics.
- **SARIF as a co-equal v1 built-in for compat kinds.** Originally deferred; re-evaluated during document review (2026-04-19) because in 2026 SARIF is GitHub's native code-scanning format (PR inline annotations, Security tab, dismissal workflow) — higher-leverage than the JUnit Tests tab for compat findings. Incremental cost is bounded (~1 additional file per compat kind + shared JSON builder + schema validation). Shipping both JUnit and SARIF gives symmetric CI-output coverage and a stronger release narrative than JUnit-only + "users can write SARIF."
- **SARIF for DIFF is out of scope.** SARIF's `Result`/`Finding` model represents code-quality issues with `ruleId` + `level`; a message-value diff has no natural rule and no natural severity. Users who need diff-as-SARIF can write one via the pluggable API.
- **JUnit timestamp**: deterministic placeholder (`"1970-01-01T00:00:00Z"`) so snapshot tests don't flake on wall-clock. Future flag/env var can opt in to real timestamps.
- **Formatter exception policy**: hard-fail at the CLI top level (exit 2). Built-in formatters are exception-safe via tests; third-party authors own their error handling. (see origin: P1 patch)
- **JSON contract is structural equivalence, not byte-identity.** The refactor must produce JSON that satisfies `json.loads(new) == json.loads(old)` for every existing `--format json` invocation: same keys, same value types, same nested structure. Byte-identity (key order, whitespace, exact float repr) is NOT required because (a) `json.dumps` does not sort keys today and Python dict insertion order across versions is the only thing pinning byte order — that's a brittle contract; (b) downstream consumers (jq, json.loads, dashboards) all canonicalize; (c) pinning byte order ossifies incidental formatting and blocks future improvements like `sort_keys=True`. Existing per-key assertions in `tests/schema/test_cli.py` (TestBisectJson, TestHistory*) remain the authoritative contract; new structural-equivalence tests supplement them. Human output remains visually identical (snapshot at text level).
- **Re-registration policy: reject by default.** `register_formatter(name, fn, *, kind, replace=False)` raises `ValueError` if `(kind, name)` is already registered, unless `replace=True`. Built-in names (kinds × `{human, json, junit}`) are RESERVED — third-party packs cannot shadow them even with `replace=True`. Reason: protokit is a CI gate; silently allowing a third-party pack to override the built-in `junit` formatter would let downstream CI consumers consume drift with no error signal. For dev-time re-import ergonomics, expose `protokit.formatters.clear_user_formatters()` to wipe non-built-in entries. Override of a third-party name (with `replace=True`) is the only sanctioned path.
- **Two-phase formatter pack loading.** `_load_formatter_packs(module_names)` first imports each module and stages its `FORMATTERS` list, then on full success registers each into the live registry. On any error, abort with no live-registry mutation. This prevents partial-load state corruption when the third entry in a pack is malformed.
- **Trust model.** `--formatter-module MODULE` runs `importlib.import_module` on user-supplied dotted names — same trust pattern as `--rule-pack`. Treat formatter packs as you would `pip install`: only load packs from sources you trust. Three guarantees protokit makes:
  1. The CLI exit code is determined by the report itself (compat verdict + diagnostic levels), NOT by formatter output. A malicious or buggy formatter can mislead human readers but cannot flip CI gating.
  2. Built-in formatter names are reserved (cannot be silently shadowed by `--formatter-module` packs; see re-registration policy above).
  3. Formatters cannot inject arbitrary stdout output mid-render (stdout-write guard catches direct writes; only the returned `str` reaches stdout).
  Document this in README under "Output Formatters" so security-conscious users have a clear answer.

## Open Questions

### Resolved During Planning

- **Where does the formatters module live?** Top-level `src/protokit/formatters/` (a sibling of `src/protokit/message/` and `src/protokit/schema/`). Reason: the API is unified across both CLIs; co-locating with one would imply ownership.
- **How does CLI bootstrapping order work with `--formatter-module`?** Built-ins register at `protokit.formatters` import; `--formatter-module` flags process in declaration order; `--format` validates against the final registry state. (see origin: P1 patch)
- **What's the JUnit schema validation target?** GitHub Actions `publish-test-results` xsd (concrete published schema).

### Deferred to Implementation

- **Exact regression-test fixtures** — capture current CLI output on a representative descriptor pair as JSON files, refactor's regression tests assert `json.loads(new) == json.loads(old)` (structural equivalence). Fixtures chosen at implementation time. Recommended axes: scalar-only schema, schema with one nested message, schema with map field, schema with one finding, schema with multiple findings + diagnostics.
- **xmlschema library version pin** — pick at implementation time after checking PyPI.
- **Naming of future `FormatterKind` values** — when `LINT` and `SCHEMA_DIFF` kinds eventually land, follow noun form (`SCHEMA_DIFF`, `LINT_REPORT`) for consistency with `COMPAT_HISTORY` / `COMPAT_BISECT`. Document in `protokit.formatters` docstring as the convention going forward.

## Output Structure

```
src/protokit/
  formatters/                         (new)
    __init__.py                       (public API: register_formatter, FormatterKind, etc.)
    _registry.py                      (module-level singleton dict)
    _builtin_diff.py                  (human, json, junit for DIFF)
    _builtin_compat.py                (human, json, junit, sarif for COMPAT)
    _builtin_history.py               (human, json, junit, sarif for COMPAT_HISTORY)
    _builtin_bisect.py                (human, json, junit, sarif for COMPAT_BISECT)
    _junit_xml.py                     (xml.etree.ElementTree helpers)
    _sarif_json.py                    (SARIF 2.1.0 JSON builder)
docs/
  plans/
    2026-04-18-001-feat-pluggable-formatters-junit-plan.md
tests/
  test_formatters_registry.py         (Unit 2)
  test_formatters_builtin.py          (Unit 3)
  test_formatters_junit.py            (Unit 4)
  test_formatters_sarif.py            (Unit 4)
  test_formatters_cli.py              (Unit 5)
  test_formatters_integration.py      (Unit 6)
```

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

### Registry shape (sketch)

```
FormatterKind = enum(DIFF, COMPAT, COMPAT_HISTORY, COMPAT_BISECT)
# Future kinds (LINT, SCHEMA_DIFF) added as new members; non-breaking.

FormatterContext = frozen dataclass(
    subcommand: str,
    target_type: str | None,         # populated when single-type or both sides match
    old_target_type: str | None,     # populated when --old-type used
    new_target_type: str | None,     # populated when --new-type used
    level: str | None,               # CLI flag string (e.g., "consumer-safe")
    range_spec: str | None,
    old_ref: str | None,             # git-mode context
    new_ref: str | None,
    proto_file: str | None,
)

# Module-level singleton, keyed by (kind, lower(name))
_REGISTRY: dict[tuple[FormatterKind, str], Formatter]
_BUILTIN_NAMES: frozenset[tuple[FormatterKind, str]]   # reserved

register_formatter(name, fn, *, kind, replace=False):
    key = (kind, name.lower())
    if key in _BUILTIN_NAMES:
        raise ValueError(f"cannot override built-in formatter {key}")
    if key in _REGISTRY and not replace:
        raise ValueError(f"formatter {key} already registered; pass replace=True to override")
    _REGISTRY[key] = fn

get_formatter(name, kind) -> Formatter   # lowercases name
list_formatters(kind) -> list[str]       # sorted, lowercase
clear_user_formatters()                  # wipes non-built-in entries (test/dev helper)

load_formatter_pack(module):
    # Two-phase: stage all entries, then commit. No partial registrations.
    staged = [(name, fn, kind) for name, fn, kind in module.FORMATTERS]
    for name, fn, kind in staged:
        register_formatter(name, fn, kind=kind)
```

### CLI flag flow

```
1. CLI starts.
2. protokit.formatters import → built-ins register.
3. Click parses flags. --format captured as STRING (not Choice).
4. --formatter-module flags processed in declaration order:
     for module_name in formatter_modules:
         module = importlib.import_module(module_name)
         load_formatter_pack(module)
5. --format value validated:
     try:
         fn = get_formatter(value, kind=KIND_FOR_THIS_SUBCOMMAND)
     except KeyError:
         error_exit(f"unknown formatter '{value}'. Available for {kind}: {list}")
6. Subcommand runs, produces report.
7. fn(report, ctx) → str → printed to stdout.
8. If fn raises, top-level handler:
     error_exit(f"formatter '{name}' raised {type}: {message}")
```

### JUnit COMPAT structure (sketch)

```
<testsuites>
  <testsuite name="protokit-compat-{target_type}"
             tests="{n}" failures="{n_findings}" errors="{n_error_diag}"
             timestamp="1970-01-01T00:00:00Z">
    [for each finding:]
    <testcase classname="{rule_id}" name="{finding.path}">
      <failure type="{severity}/{direction}" message="...">
        {finding.message}
      </failure>
    </testcase>
    [for each error-level diagnostic:]
    <testcase classname="diagnostic" name="{short-summary}">
      <error message="...">{diagnostic.message}</error>
    </testcase>
    [if zero testcases otherwise:]
    <testcase classname="compat" name="compatible"/>
    [warning-level diagnostics:]
    <system-out>{warnings joined}</system-out>
  </testsuite>
</testsuites>
```

`COMPAT_HISTORY` wraps N COMPAT testsuites under a `<testsuites>` root, `testsuite.name="commit-{short-sha}-{subject}"`. `COMPAT_BISECT` is a single `<testsuite>` with `<testcase>` per walked commit + `<properties>` block carrying `range_spec`, `old_sha`, `new_sha`, `breaking_commit`.

## Implementation Units

- [ ] **Unit 1: Promote history/bisect outputs to public dataclasses**

**Goal:** Replace inline-dict construction in `history` / `bisect` subcommands with frozen public dataclasses (`HistoryEntry`, `HistoryReport`, `BisectReport`). No formatter machinery yet — just extract the data model so formatters can type-hint against it.

**Requirements:** R1 (foundation for COMPAT_HISTORY / COMPAT_BISECT formatters), R5 (zero JSON regression).

**Dependencies:** None.

**Files:**
- Modify: `src/protokit/schema/model.py` (add four frozen dataclasses: `CommitDiagnostic`, `HistoryEntry`, `HistoryReport`, `BisectReport`)
- Modify: `src/protokit/schema/__init__.py` (add `Diagnostic`, `CommitDiagnostic`, `HistoryEntry`, `HistoryReport`, `BisectReport` to `__all__`)
- Modify: `src/protokit/schema/cli.py` (refactor `history` and `bisect` body to construct dataclasses; add `_history_report_to_dict` and `_bisect_report_to_dict` helpers that emit the existing JSON shape)
- Test: `tests/schema/test_model.py` (new test cases for the four dataclasses — frozen, tuple coercion, attribute correctness)
- Test: `tests/schema/test_cli.py` (snapshot tests using `json.loads(new) == json.loads(old)` structural equivalence; existing per-key assertions remain the primary contract)

**Approach:**

Field shapes pinned by the existing JSON contract (verified at `src/protokit/schema/cli.py:1115-1163` for history aggregation, `:1370-1403` for bisect):

- `CommitDiagnostic` carries `commit: str`, `level: str`, `path: str | None`, `message: str`. Frozen. Mirrors today's per-commit diagnostic dict shape — needed because the existing `Diagnostic` has no `commit` field, and aggregated diagnostics emit `{"commit": sha, "level": ..., "path": ..., "message": ...}`.
- `HistoryEntry` carries `commit_sha: str`, `commit_subject: str` (full commit message verbatim if no newline; first line otherwise), `report: CompatibilityReport`. Frozen. The entry's own commit identity carries the SHA, so `report.diagnostics` stays as `tuple[Diagnostic, ...]` — no commit field needed at this level.
- `HistoryReport` carries `range_spec: str`, `old_sha: str`, `new_sha: str`, `commits_walked: int` (count of dep-affecting commits enumerated; NOT `len(entries)` — entries pair commits with predecessor), `entries: tuple[HistoryEntry, ...]`, `diagnostics: tuple[CommitDiagnostic, ...]` (aggregated per-commit; matches today's top-level `diagnostics` key). Frozen.
- `BisectReport` carries `range_spec: str`, `old_sha: str`, `new_sha: str`, `breaking_commit: str | None`, `commits_walked: int` (matches today's `commits_walked` key), `diagnostics: tuple[CommitDiagnostic, ...]` (single aggregated list — today's bisect JSON has one diagnostics key, not a per-commit/aggregate split). Frozen.
- Refactor `schema/cli.py` so each subcommand builds the dataclass internally; then JSON output goes through `_history_report_to_dict` / `_bisect_report_to_dict` helpers that produce structurally-equivalent dicts. JSON contract is structural equivalence (`json.loads(new) == json.loads(old)`), not byte-identity — see Key Technical Decisions.

**Tuple coercion pattern.** Frozen dataclasses do NOT coerce list inputs to tuples automatically. The prior precedent (`CompatibilityReport` at `src/protokit/schema/model.py:172-203`) does NOT use `__post_init__` because its callers already pass tuples. The new aggregate types receive lists from CLI processing, so they need explicit coercion. Use this pattern:

```python
def __post_init__(self) -> None:
    if not isinstance(self.entries, tuple):
        object.__setattr__(self, "entries", tuple(self.entries))
    if not isinstance(self.diagnostics, tuple):
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
```

This is a new pattern in the project; document the choice in the dataclass docstrings.

**Execution note:** Test-first. The existing `tests/schema/test_cli.py` (TestBisectJson, TestHistory*) is the primary JSON contract — run those green pre-refactor as the baseline. Add structural-equivalence snapshot tests (`json.loads(new) == json.loads(old)`) as belt-and-suspenders, NOT byte-level snapshots.

**Patterns to follow:**
- `src/protokit/schema/model.py:172-203` `CompatibilityReport` for `@dataclass(frozen=True)` declaration style. (Tuple coercion via `__post_init__` is new — see code skeleton above.)
- `src/protokit/message/model.py:79-125` `Diagnostic` for the per-finding diagnostic shape.

**Test scenarios:**
- Happy path: `HistoryReport(range_spec=..., old_sha=..., new_sha=..., commits_walked=3, entries=[entry1, entry2], diagnostics=[diag1])` instantiates; `HistoryReport.entries` is a `tuple` even when constructed from a list.
- Happy path: `BisectReport.breaking_commit = None` valid (no break in range); `BisectReport.commits_walked` is `int`.
- Happy path: `CommitDiagnostic(commit="abc123", level="error", path=None, message="…")` — `path` defaults to `None`.
- Edge case: empty `entries` and `commits_walked=0` is valid (today's "no commits in range" case at `schema/cli.py:1063-1070`).
- Edge case: `commits_walked != len(entries)` is the normal case (entries pair commits with predecessor).
- Integration: `protokit compat history --range HEAD~3..HEAD --format json` produces JSON structurally equivalent to pre-refactor output (`json.loads` parsed dicts compare equal). Same for `bisect --format json`.
- Regression: existing per-key assertions in `tests/schema/test_cli.py:TestBisectJson` and `TestHistory*` pass without modification.

**Verification:**
- `Diagnostic`, `CommitDiagnostic`, `HistoryEntry`, `HistoryReport`, `BisectReport` are importable from `protokit.schema`.
- Existing `tests/schema/test_cli.py` tests for `history` and `bisect` pass without modification.
- New structural-equivalence tests pass.

---

- [ ] **Unit 2: Build `protokit.formatters` registry**

**Goal:** New top-level package `protokit.formatters` with the public API: `FormatterKind`, `FormatterContext`, `register_formatter`, `get_formatter`, `list_formatters`, `load_formatter_pack`. No built-ins yet, no CLI integration.

**Requirements:** R1, R6 (infrastructure for unknown-format detection), R7 (no exception handling in registry — happens at CLI level).

**Dependencies:** None (independent of Unit 1).

**Files:**
- Create: `src/protokit/formatters/__init__.py`
- Create: `src/protokit/formatters/_registry.py`
- Test: `tests/test_formatters_registry.py`

**Approach:**
- `FormatterKind = Enum("DIFF", "COMPAT", "COMPAT_HISTORY", "COMPAT_BISECT")`. Plain `Enum`, not `IntEnum`, so future kinds can be added without breaking. Module docstring documents the noun-form naming convention (`SCHEMA_DIFF`, `LINT_REPORT`) for future kinds.
- `FormatterContext = @dataclass(frozen=True)` with: `subcommand: str`; `target_type: str | None`; `old_target_type: str | None`; `new_target_type: str | None`; `level: str | None` (CLI flag string like `"consumer-safe"`); `range_spec: str | None`; `old_ref: str | None`; `new_ref: str | None`; `proto_file: str | None`. All optional except `subcommand`.
- `Formatter` type alias: `Callable[[Any, FormatterContext], str]` (use `Any` for the report — formatters validate internally; static type narrowing via `kind` parameter at registration is not enforceable in Python).
- Registry is a module-level dict in `_registry.py` keyed by `(kind, name.lower())` — name is case-insensitive.
- `_BUILTIN_NAMES: frozenset[tuple[FormatterKind, str]]` populated at built-in registration time (Unit 3); reserved against override.
- `register_formatter(name, fn, *, kind, replace=False)`:
  - Raises `ValueError` if `(kind, name.lower())` is in `_BUILTIN_NAMES` (built-ins reserved).
  - Raises `ValueError` if key already in registry and `replace=False`.
  - Otherwise stores (or overwrites if `replace=True`).
- `get_formatter(name, kind)` lowercases name; raises `KeyError` if missing (caller wraps).
- `list_formatters(kind)` returns sorted list of registered names (lowercase).
- `clear_user_formatters()` removes all entries not in `_BUILTIN_NAMES`. For test/dev use; not part of the formal user API but importable.
- `load_formatter_pack(module)` — **two-phase**: stage all entries from `module.FORMATTERS` first, then register each. On any error during staging or registration, abort with no live-registry mutation. `AttributeError` (no FORMATTERS) and `TypeError` (bad tuple shape) propagate during staging.

**Patterns to follow:**
- `src/protokit/schema/cli.py:130` `_load_rule_packs` for the import-and-register flow.
- `src/protokit/schema/plugins.py` for the iter-pack pattern (`iter_rule_pack`).

**Test scenarios:**
- Happy path: register a formatter; `get_formatter` returns it; `list_formatters(kind)` includes its name (lowercase).
- Happy path: `register_formatter("FOO", fn, kind=COMPAT)` then `get_formatter("foo", COMPAT)` returns the fn (case-insensitive).
- Happy path: `load_formatter_pack` with a module exposing `FORMATTERS = [("foo", fn, FormatterKind.COMPAT)]` registers correctly.
- Edge case: `list_formatters` on a kind with no user formatters returns the built-ins (lowercase, sorted).
- Edge case: `clear_user_formatters()` removes user-registered entries but preserves built-ins.
- Error path: re-registration of an existing name without `replace=True` raises `ValueError`.
- Error path: `register_formatter("junit", fn, kind=COMPAT)` (built-in name) raises `ValueError` even with `replace=True` — built-ins reserved.
- Error path: `register_formatter("foo", fn, kind=COMPAT, replace=True)` after a prior registration succeeds; subsequent `get_formatter` returns the new fn.
- Error path: `get_formatter` on missing `(kind, name)` raises `KeyError`.
- Error path: `load_formatter_pack` on a module with no `FORMATTERS` attribute raises `AttributeError`; registry unchanged.
- Error path: `load_formatter_pack` on a module with malformed `FORMATTERS` (e.g., 2-tuples not 3-tuples) raises `TypeError`; registry unchanged (two-phase load aborts).
- Error path: `load_formatter_pack` on a module whose 3rd entry is malformed leaves the first two NOT in the registry (verifiable via `list_formatters`).

**Verification:**
- All registry unit tests pass.
- `from protokit.formatters import FormatterKind, FormatterContext, register_formatter, get_formatter, list_formatters, load_formatter_pack` works.

---

- [ ] **Unit 3: Extract existing `human` / `json` rendering into built-in formatters**

**Goal:** Move existing rendering logic from `src/protokit/schema/cli.py` and `src/protokit/message/cli.py` into the new `_builtin_*.py` modules. Register at `protokit.formatters` import. Snapshot tests verify byte-identical output.

**Requirements:** R2 (built-ins for both CLIs), R5 (zero regression).

**Dependencies:** Unit 1 (HistoryReport/BisectReport dataclasses), Unit 2 (registry).

**Files:**
- Create: `src/protokit/formatters/_builtin_diff.py` (human + json for DIFF)
- Create: `src/protokit/formatters/_builtin_compat.py` (human + json for COMPAT)
- Create: `src/protokit/formatters/_builtin_history.py` (human + json for COMPAT_HISTORY)
- Create: `src/protokit/formatters/_builtin_bisect.py` (human + json for COMPAT_BISECT)
- Modify: `src/protokit/formatters/__init__.py` (import the four `_builtin_*.py` modules so registration happens at package import)
- Modify: `src/protokit/schema/cli.py` (delete extracted rendering; keep callsite that resolves formatter and prints — full CLI integration in Unit 5, here just stubbed-via-call to the new fns directly)
- Modify: `src/protokit/message/cli.py` (same)
- Test: `tests/test_formatters_builtin.py` (snapshot tests for each built-in)

**Approach:**
- Move `_format_finding_human` and surrounding helpers from `src/protokit/schema/cli.py` into `_builtin_compat.py` as `_compat_human(report, ctx)`. JSON renderer becomes `_compat_json(report, ctx)`.
- Same for diff (`src/protokit/message/cli.py:196`).
- For history and bisect, the existing inline JSON-builders (post Unit 1, building from dataclasses) become the formatter bodies. Human formatters compose multiple per-commit COMPAT formatters or render directly — whichever is simpler.
- All eight built-ins (4 kinds × {human, json}) registered at the bottom of `__init__.py` via `register_formatter` calls. Done at package import → zero CLI logic for built-in availability.
- CLI temporarily calls `get_formatter("human", kind=...)` directly to keep behavior. Full `--format` flag wiring lands in Unit 5.

**Execution note:** Snapshot-driven extraction. Capture pre-refactor outputs first; the move is correct iff snapshots match.

**Patterns to follow:**
- Existing `_format_finding_human` etc. in `src/protokit/schema/cli.py` and `src/protokit/message/cli.py`.

**Test scenarios:**
- Happy path: each built-in formatter is registered after `import protokit.formatters`.
- Happy path: `_compat_json(real_report, ctx)` produces output byte-identical to `json.dumps(...existing dict...)` — snapshot test.
- Happy path: `_compat_human(real_report, ctx)` produces output visually identical (line-by-line) to current human CLI output — snapshot test.
- Same for `_diff_human` / `_diff_json`, `_history_human` / `_history_json`, `_bisect_human` / `_bisect_json`.
- Edge case: empty report (no findings) produces stable empty output for each kind.
- Integration: the existing `tests/schema/test_cli.py` and `tests/test_cli.py` continue to pass with no changes — output is byte-identical from the user's perspective.

**Verification:**
- All eight built-ins registered.
- Snapshot tests pass.
- Existing CLI tests pass with no modifications.

---

- [ ] **Unit 4: Add JUnit and SARIF built-in formatters**

**Goal:** Four JUnit formatters (one per kind) plus three SARIF formatters (compat kinds). JUnit for DIFF uses a binary-result single-testcase pattern (pass if equal / fail with per-difference detail in body); JUnit for compat kinds uses per-finding testcase rendering. SARIF 2.1.0 for compat kinds targets GitHub Code Scanning consumption. Validates against GH Actions JUnit xsd and OASIS SARIF JSON schema respectively.

**Requirements:** R2, R3a, R3b.

**Dependencies:** Units 1-3 (dataclasses + registry + extracted built-ins for shared rendering helpers).

**Files:**
- Create: `src/protokit/formatters/_junit_xml.py` (xml.etree helpers; control-char scrubber)
- Create: `src/protokit/formatters/_sarif_json.py` (SARIF 2.1.0 builder; severity/level mapping; rule catalog)
- Modify: `src/protokit/formatters/_builtin_diff.py` (add `_diff_junit`; register)
- Modify: `src/protokit/formatters/_builtin_compat.py` (add `_compat_junit`, `_compat_sarif`; register)
- Modify: `src/protokit/formatters/_builtin_history.py` (add `_history_junit`, `_history_sarif`; register)
- Modify: `src/protokit/formatters/_builtin_bisect.py` (add `_bisect_junit`, `_bisect_sarif`; register)
- Modify: `pyproject.toml` (introduce `[project.optional-dependencies] dev` group with `xmlschema>=2.0` and `jsonschema>=4.0`)
- Test: `tests/test_formatters_junit.py` (escaping, binary-result DIFF, empty-testsuite compat, error/warning diagnostic handling, XML parseability, xsd validation)
- Test: `tests/test_formatters_sarif.py` (rule catalog, severity/level mapping, JSON parseability, schema validation)
- Vendor: `tests/fixtures/junit-xml/JUnit.xsd` (pinned GH Actions xsd, documented commit SHA)
- Vendor: `tests/fixtures/sarif/sarif-2.1.0.json` (pinned OASIS SARIF schema; note source + date)

**Approach:**

**JUnit for DIFF (`_diff_junit(result, ctx)`)** — binary-result pattern:
- Single `<testsuites>` → single `<testsuite name="protokit-diff" tests="1" failures="{0 or 1}">`.
- Single `<testcase classname="diff" name="messages-equal">`:
  - If `result.has_changes()` is False: empty body (pass).
  - If True: `<failure type="diff" message="{N} difference(s) found">` with body listing each `Difference` on its own line (`- {path}: {old_value!r} -> {new_value!r}` or a type-specific line for ADDED/REMOVED/TYPE_CHANGED/etc.). Warnings appended to `<system-out>`.
- Rationale: a diff is a single assertion ("these two messages are equal"); differences are evidence of the single failure, not independent tests. Prevents "100 tests failed" noise in CI aggregators while preserving detail for humans. Documented in the Key Technical Decisions section of this plan.

**JUnit for COMPAT (`_compat_junit(report, ctx)`)** — per-finding pattern:
- Wrap in `<testsuites>` (single child for COMPAT).
- Suite name: `protokit-compat-{type_segment}` where `type_segment = ctx.target_type if old_target_type == new_target_type else f"{old_target_type}->{new_target_type}"`. Falls back to `"unknown"` only if both are `None`. Prevents silently collapsing cross-type comparisons in CI dashboards.
- `<testsuite name="..." tests=... failures=... errors=... timestamp="1970-01-01T00:00:00Z">`.
- Per finding → `<testcase classname="{rule_id}" name="{finding.path}"><failure type="{severity}/{direction}" message="...">{finding.message}</failure></testcase>`. `finding.path` uses new-side dotted paths; deletion findings carry the old-side path.
- Per error-level diagnostic → `<testcase classname="diagnostic" name="{short-summary}"><error message="...">{diagnostic.message}</error></testcase>`.
- Per warning-level diagnostic → single `<system-out>` block on the testsuite.
- **Empty-testsuite handling**: zero findings AND zero error diagnostics → single `<testcase classname="compat" name="compatible"/>` with `tests="1" failures="0" errors="0"`. Warning-only counts as empty.

**JUnit for COMPAT_HISTORY (`_history_junit(report, ctx)`):** Root `<testsuites>`, one child `<testsuite>` per `HistoryEntry`, generated by reusing `_compat_junit` internals. `testsuite.name = "commit-{short-sha}-{commit_subject}"` (subject sanitized).

**JUnit for COMPAT_BISECT (`_bisect_junit(report, ctx)`):** Single `<testsuite name="protokit-bisect">`; `<properties>` block with `range_spec`, `old_sha`, `new_sha`, `breaking_commit`; per walked commit → `<testcase classname="{short-sha}" name="{commit_subject}"/>` (passing) or with `<failure type="break" ...>` for the breaking commit.

**SARIF for COMPAT (`_compat_sarif(report, ctx)`):**
- Top-level `{"version": "2.1.0", "$schema": "https://json.schemastore.org/sarif-2.1.0.json", "runs": [...]}`.
- Single `run`:
  - `run.tool.driver = {"name": "protokit", "version": "<from protokit.__version__>", "informationUri": "...", "rules": [...]}`.
  - `run.tool.driver.rules`: declare each rule_id that fired, with `{"id": rule_id, "name": rule_id, "shortDescription": {"text": "..."}, "fullDescription": {"text": "..."}, "defaultConfiguration": {"level": <mapped>}}`. Rule text comes from a static dictionary keyed by rule_id (the 17 built-in rule_ids; user-plugin rule_ids get a generic description).
  - `run.results`: one per finding. Each result: `{"ruleId": finding.rule_id, "level": <mapped from severity/direction>, "message": {"text": finding.message}, "locations": [{"logicalLocations": [{"fullyQualifiedName": str(finding.path)}]}]}`. If `ctx.proto_file` is set, add `physicalLocation.artifactLocation.uri`.
  - `run.invocations = [{"executionSuccessful": <no error diagnostics>}]`. Error diagnostics → `run.invocations[0].toolExecutionNotifications = [...]`. Warning diagnostics → `run.invocations[0].toolConfigurationNotifications = [...]`.
- **Severity/level mapping:**
  - WIRE severity → SARIF `"error"`.
  - SEMANTIC + direction in {BACKWARD, FORWARD, BOTH} → SARIF `"error"` (breaking).
  - POLICY → SARIF `"warning"`.
- Output via `json.dumps(payload, indent=2)` — structurally stable, human-readable.

**SARIF for COMPAT_HISTORY (`_history_sarif(report, ctx)`):**
- Single `run` with aggregated results across all entries.
- Each result carries `partialFingerprints = {"commit": commit_sha}` so consumers can group by commit.
- Rules catalog merged across entries.
- `run.invocations`: one per entry, in order.

**SARIF for COMPAT_BISECT (`_bisect_sarif(report, ctx)`):**
- Single `run`.
- Results aggregated across walked commits with `partialFingerprints = {"commit": sha}`.
- Breaking commit flagged in `run.properties = {"breaking_commit": ..., "range_spec": ..., "old_sha": ..., "new_sha": ...}`.

**Patterns to follow:**
- **JUnit**: `xml.etree.ElementTree` for construction + serialization. Python 3.8+ preserves attribute insertion order. Output via `ET.tostring(root, xml_declaration=True, encoding='unicode')`. Strip XML 1.0-forbidden control characters (`\x00`-`\x08`, `\x0b`, `\x0c`, `\x0e`-`\x1f`) via a `_xml_safe_text(s)` helper.
- **SARIF**: plain `dict` + `json.dumps`. No schema library at build time; validation is test-only via `jsonschema.Draft7Validator` against the vendored schema.
- Both: deterministic output (no wall-clock timestamps; stable ordering).

**Test scenarios:**
- Happy path: DIFF JUnit on equal messages → pass (single testcase, no `<failure>`).
- Happy path: DIFF JUnit on unequal messages → single testcase + `<failure>` with body listing each Difference.
- Happy path: COMPAT JUnit with 3 findings produces 1 `<testsuite>` + 3 `<testcase>` + 3 `<failure>`.
- Happy path: HISTORY JUnit with 5 entries produces `<testsuites>` root + 5 `<testsuite>` children.
- Happy path: BISECT JUnit with breaking commit identifies it via `<failure>` testcase.
- Happy path: COMPAT SARIF with 3 findings produces one `run` with 3 `results` and 3 entries in `rules`.
- Happy path: HISTORY SARIF with 5 entries produces one `run` with aggregated results; each `result.partialFingerprints.commit` is set.
- Happy path: BISECT SARIF with breaking commit identifies it in `run.properties.breaking_commit`.
- Edge case: COMPAT JUnit with zero findings AND zero error diagnostics emits single passing `<testcase classname="compat" name="compatible"/>` with `tests="1"`.
- Edge case: COMPAT JUnit with only warning-level diagnostics also emits the passing testcase + `<system-out>` block.
- Edge case: COMPAT JUnit with only error-level diagnostics emits diagnostic testcase, no synthetic compatible testcase.
- Edge case: COMPAT SARIF with zero findings produces an empty `results: []` array with `invocations[0].executionSuccessful: true`.
- Edge case: finding message with XML-special chars (`<`, `>`, `&`, `"`) is escaped correctly in JUnit; encoded correctly in SARIF JSON.
- Edge case: finding message with `\x01` (XML-forbidden control char) is scrubbed from JUnit (producing parseable XML); preserved in SARIF (JSON permits it).
- Edge case: commit subject with newlines / special chars in HISTORY testsuite name is sanitized.
- Edge case: `target_type=None` and both `old_target_type`/`new_target_type` None → JUnit testsuite name uses `"unknown"`; SARIF rule catalog empty.
- Edge case: DIFF JUnit with 1 difference → failure body has 1 line; with 100 differences → 100 lines (no truncation in v1; truncation deferred).
- Integration: all JUnit outputs parse cleanly via `xml.etree.ElementTree.fromstring`.
- Integration: all JUnit outputs validate against the GitHub Actions `publish-test-results` JUnit xsd via `xmlschema.XMLSchema(xsd_path).validate(xml_string)`.
- Integration: all SARIF outputs validate against OASIS SARIF 2.1.0 schema via `jsonschema.Draft7Validator(sarif_schema).validate(json.loads(output))`.

**Verification:**
- 15 total built-in formatters registered (DIFF: human/json/junit; COMPAT/HISTORY/BISECT: human/json/junit/sarif each).
- All JUnit outputs xsd-validate; all SARIF outputs schema-validate.
- All snapshot tests pass.

---

- [ ] **Unit 5: CLI wire-up — dynamic `--format` + `--formatter-module` + exception handling**

**Goal:** Replace `click.Choice` on every subcommand's `--format` with `click.STRING` + manual validation. Add `--formatter-module` (repeatable). Wire formatter exceptions to the CLI top-level error handler. Pass `FormatterContext` into the selected formatter.

**Requirements:** R1, R4, R6, R7.

**Dependencies:** Units 2-4 (need registry + built-ins + JUnit before flag wiring is meaningful).

**Files:**
- Modify: `src/protokit/schema/cli.py` (every `--format` declaration in `check`, `history`, `bisect`, `ci`; add `--formatter-module`; replace direct rendering calls with `get_formatter`+invocation; wrap formatter call in try/except)
- Modify: `src/protokit/message/cli.py` (same for `protokit diff`)
- Modify: `src/protokit/cli.py` (top-level dispatcher) — only if `--formatter-module` lands as a global option vs per-subcommand. Recommendation: per-subcommand (consistent with `--rule-pack`).
- Create: shared helper in `src/protokit/_cli_utils.py` for `_load_formatter_packs(module_names)` and `_resolve_and_validate_formatter(name, kind)` — mirrors the `_load_rule_packs` shape.
- Test: `tests/test_formatters_cli.py` (CLI-level tests for unknown format, formatter-module loading, exception fail-fast)

**Approach:**
- Replace each `click.Choice(("human", "json"), case_sensitive=False)` with `click.STRING`. **Keep `default="human"`** on Click — only the Choice constraint was the bootstrapping problem; the default is fine to leave on the option. This avoids a `None`/`output_format.lower()` `TypeError` in the existing `_reject_quiet_plus_json` call site.
- Preserve case-insensitivity by lowercase-normalizing the formatter name in `register_formatter` and `get_formatter`. The existing `output_format.lower()` checks (`_reject_quiet_plus_json`, header gating) continue to work because the resolved canonical name is already lowercase.
- Add `@click.option("--formatter-module", "formatter_modules", multiple=True, help="...")` to every subcommand that has `--format`. Mirror exactly the placement of `--rule-pack`.

- Call order in subcommand body:
  1. `_load_formatter_packs(formatter_modules)` — **two-phase load**: import each module and stage its `FORMATTERS` list; on full success, register into the live registry. On any error, abort with no live-registry mutation. Surface the original exception verbatim, mirroring `_load_rule_packs`.
  2. `_reject_quiet_plus_json_or_structured(quiet, output_format, kind=KIND_FOR_THIS_SUBCOMMAND)` — widened mutual-exclusion: `--quiet` rejects any non-`human` formatter, not just `json`. Otherwise `--quiet --format junit` would silently swallow the JUnit output.
  3. Resolve format: `fn = _resolve_and_validate_formatter(output_format, kind=KIND_FOR_THIS_SUBCOMMAND)` — `error_exit` with the available list on `KeyError`.
  4. Build the report (existing logic, post Unit 1).
  5. Construct `FormatterContext` from CLI flags. For check/ci, populate `target_type`, `level`, `old_target_type`/`new_target_type` (cross-type compat). For history/bisect, populate `range_spec`, `old_ref`, `new_ref`, `proto_file` so a custom formatter can render the git-mode header itself if it wants.
  6. **Stdout-write guard**: redirect `sys.stdout` to an in-memory buffer for the duration of `fn(report, ctx)`. Formatters MUST be pure functions returning `str`; any side-effect writes to stdout are unsupported. If the buffer is non-empty after the call, treat as error (formatter contract violation; exit 2 with "formatter '{name}' wrote to stdout directly; formatters must return str only").
  7. Wrap `output = fn(report, ctx)` in `try/except Exception as exc: error_exit(f"formatter '{name}' raised {type(exc).__name__}: {exc}")`. NO `--verbose` claim — the project has no `--verbose` flag today (verified at `src/protokit/_cli_utils.py:20-32` and grep for `verbose`); a one-line `error_exit` message is the consistent behavior. If introducing `--verbose` is wanted later, scope it as a separate change.
  8. `click.echo(output)`.

- **Re-registration policy**: reject by default (raise `ValueError`). Add an explicit `replace: bool = False` kwarg on `register_formatter` for opt-in override. Built-in names (the kinds × `{human, json, junit}`) are reserved — third-party formatter packs cannot shadow them via `--formatter-module` even with `replace=True`. For dev-time re-import ergonomics, expose `protokit.formatters.clear_user_formatters()` (clears non-built-in entries). Update Unit 2's API description accordingly. This is a stricter policy than the original brainstorm's "warn + last-write-wins" — the change is justified by CI-tool semantics: silent override of a built-in `junit` formatter could cause downstream CI consumers to silently consume drift.

- `_resolve_and_validate_formatter` lists available formatters in error: `f"unknown formatter '{name}'. Available for {kind.value}: {', '.join(list_formatters(kind))}"`.

**Patterns to follow:**
- `src/protokit/schema/cli.py:130-152` `_load_rule_packs` — exact mirror for the import-and-load helper, but with the two-phase load enhancement.
- `src/protokit/schema/cli.py` per-subcommand `--rule-pack` declaration sites (line ~783, ~966, ~1243, ~1551) for `--formatter-module` placement.
- `src/protokit/_cli_utils.py:20-32` `error_exit` for all CLI errors.

**Test scenarios:**
- Happy path: `protokit compat check ... --format human` produces existing output (regression — verified against existing `tests/schema/test_cli.py`).
- Happy path: `protokit compat check ... --format JSON` (uppercase) works — case-insensitivity preserved.
- Happy path: `protokit compat check ... --format junit` produces JUnit XML.
- Happy path: `protokit compat check ... --format sarif` produces SARIF 2.1.0 JSON.
- Happy path: `protokit diff left.pb right.pb --format junit` on equal messages produces passing-testcase JUnit; on unequal messages produces single-testcase-with-failure JUnit.
- Happy path: `protokit diff left.pb right.pb --format sarif` exits 2 with `Error: unknown formatter 'sarif'. Available for DIFF: human, json, junit` (SARIF for DIFF intentionally not shipped).
- Happy path: `--formatter-module mypkg.formatters` loads pack; subsequent `--format my-name` works.
- Edge case: `--format` not provided → defaults to `human` (Click default).
- Edge case: `--formatter-module` repeated multiple times → all packs loaded in declaration order; partial-load failure leaves registry unchanged.
- Error path: `--format unknown` exits 2 with message `Error: unknown formatter 'unknown'. Available for COMPAT: human, json, junit`.
- Error path: `--quiet --format junit` exits 2 with `Error: --quiet is incompatible with structured output format 'junit'` (widened mutex check).
- Error path: `--formatter-module nonexistent.module` exits 2 with `Error: failed to import formatter pack 'nonexistent.module': ...`.
- Error path: `--formatter-module pkg.no_formatters` (module exists, no `FORMATTERS` attr) exits 2 with `Error: failed to load formatter pack ...`.
- Error path: `--formatter-module pkg.has_two_good_one_bad` (third entry malformed) exits 2 AND none of the three formatters land in the live registry (verifiable via `list_formatters`).
- Error path: `--formatter-module pkg.tries_to_shadow_junit` (registers `(COMPAT, "junit")`) exits 2 with `Error: cannot override built-in formatter (COMPAT, 'junit')` — built-in names are reserved.
- Error path: registered formatter that raises → CLI exits 2 with `Error: formatter '{name}' raised {ExceptionType}: {message}`. (No traceback; `--verbose` is not in scope.)
- Error path: registered formatter that writes to stdout directly → CLI exits 2 with `Error: formatter '{name}' wrote to stdout directly; formatters must return str only`.
- Edge case: `--quiet --format json` still exits 2 (existing mutual exclusion preserved).
- Integration: `protokit compat ci --format junit --base origin/main` on a real repo outputs JUnit XML to stdout, exits 0/1 based on findings, never 2 unless an actual error.

**Verification:**
- All four `protokit compat` subcommands accept `--format <any registered name>` and `--formatter-module`.
- `protokit diff` accepts the same.
- Unknown format and formatter-module errors are actionable.
- Existing `tests/schema/test_cli.py` and `tests/test_cli.py` continue to pass.

---

- [ ] **Unit 6: Integration tests, docs, changelog, TODOS update**

**Goal:** End-to-end validation; user-facing documentation; close the loop on the CEO plan tracking.

**Requirements:** R3 (xsd validation), R8 (docs).

**Dependencies:** Units 1-5.

**Files:**
- Test: `tests/test_formatters_integration.py` (full CLI invocations; xsd validation; multi-kind coverage)
- Modify: `README.adoc` (new "Output Formatters" section under Schema Compatibility; update CLI reference tables for `--format` and `--formatter-module`; example JUnit output snippet)
- Modify: `CHANGELOG.md` (Unreleased section: "Added: pluggable output formatter system; built-in JUnit formatters for compat / history / bisect; new public dataclasses HistoryReport and BisectReport. Changed: --format is now extensible via --formatter-module.")
- Modify: `TODOS.md` (mark CEO-plan items #3 and #4 complete with date 2026-04-18; add explicit "items #1 and #2 deferred" entries with rationale: #1 → Phase 3 docgen; #2 → standalone brainstorm)
- Modify: `examples/` (add `examples/custom_formatter.py` showing `register_formatter` + a small custom formatter; runnable)

**Approach:**
- Integration tests run real CLI invocations via Click's `CliRunner` against fixture descriptor pairs from `tests/schema/helpers.py`.
- Vendor the GH Actions JUnit xsd into `tests/fixtures/junit-xml/JUnit.xsd` (pin source URL + commit SHA in a comment). Vendor the OASIS SARIF 2.1.0 JSON schema into `tests/fixtures/sarif/sarif-2.1.0.json` (same treatment).
- Each JUnit kind's output validated via `xmlschema.XMLSchema(path).validate(...)`. Each SARIF kind's output validated via `jsonschema.Draft7Validator(schema).validate(...)`.
- README "Output Formatters" section: built-ins table (all 15), pluggable API code example, JUnit + SARIF output samples, `--formatter-module` usage, Trust-model notes (built-ins reserved, formatters cannot flip exit code, stdout-write guard).
- TODOS.md: open the existing "Phase 1 completeness" subsection, add entries marking #3 and #4 done; add new subsection or entries explicitly marking #1 deferred to Phase 3 and #2 deferred to its own brainstorm.
- `examples/custom_formatter.py`: 30-line example showing a Slack-summary-style formatter that converts findings into a single text block. Demonstrates the API for users. (Slack-style was chosen over SARIF because SARIF now ships as a built-in.)

**Patterns to follow:**
- Existing `examples/schema_check.py` and `examples/schema_plugin.py` for example file conventions.
- README.adoc existing section structure.
- CHANGELOG `Unreleased` block (extends existing entry, doesn't create new release).

**Test scenarios:**
- Integration: `protokit compat check --format junit ...` output xsd-validates against GH Actions JUnit schema.
- Integration: `protokit compat history --range HEAD~3..HEAD --format junit ...` output xsd-validates.
- Integration: `protokit compat bisect --old <sha> --new <sha> --format junit ...` output xsd-validates.
- Integration: `protokit compat ci --base origin/main --format junit ...` output xsd-validates and mirrors `check` semantics.
- Integration: `protokit compat check --format sarif ...` output schema-validates against OASIS SARIF 2.1.0 schema.
- Integration: `protokit compat history --range HEAD~3..HEAD --format sarif ...` output schema-validates.
- Integration: `protokit compat bisect --old <sha> --new <sha> --format sarif ...` output schema-validates.
- Integration: `protokit compat ci --base origin/main --format sarif ...` output schema-validates.
- Integration: `protokit diff left.pb right.pb --format junit ...` on equal messages produces pass-only XML; on unequal messages produces single-testcase-with-failure XML containing each Difference in the body.
- Integration: `--formatter-module examples.custom_formatter --format slack` runs the example pack and produces the expected output.
- Documentation: `examples/custom_formatter.py` runs cleanly under `python -m examples.custom_formatter`.

**Verification:**
- All integration tests pass.
- README, CHANGELOG, TODOS updated.
- `examples/custom_formatter.py` runs and demonstrates the API.

## System-Wide Impact

- **Interaction graph:** `protokit.formatters` is a new top-level peer to `protokit.message` and `protokit.schema`. CLI subcommands import from it; rule-plugin code does not. No circular dependencies.
- **Error propagation:** Formatter exceptions are caught at the CLI subcommand boundary (one site per subcommand) and converted to `error_exit(2)`. Plugin errors continue to flow through `report.diagnostics` as today (separate channel).
- **State lifecycle risks:** Registry is a module-level singleton mutated at import time (built-ins) and at CLI startup (user packs). Re-registration policy is **reject by default**; built-ins are reserved (cannot be shadowed). Test isolation: `tests/conftest.py` (new file) provides an autouse fixture that calls `clear_user_formatters()` after each test (built-ins are idempotent at import, so they don't need re-loading). For subprocess-based integration tests, formatters loaded via `register_formatter()` in the parent process are NOT visible — those tests must use `--formatter-module` pointing at a real importable module on disk (e.g., `examples/custom_formatter.py` registered as a test fixture pack). For pytest-xdist, each worker has its own registry — fine since they're separate processes; verify by running `pytest -p xdist -n auto` in CI. Strict `filterwarnings = error` projects are unaffected since re-registration now raises rather than warns.
- **API surface parity:** Both `protokit diff` and every `protokit compat` subcommand now accept `--format <any-name>` and `--formatter-module`. `--quiet` mutual-exclusion is widened to reject any non-`human` format (preserves existing `--quiet --format json` behavior; extends to `junit` and any user-registered structured format).
- **Integration coverage:** `tests/test_formatters_integration.py` covers full CLI runs end-to-end; xsd validation against the GH Actions schema proves the JUnit contract for that consumer (other CI consumers like Jenkins are best-effort; see Risks).
- **Unchanged invariants:** Existing `--format human` and `--format json` outputs remain **structurally equivalent** (json: same keys/values via `json.loads(new) == json.loads(old)`; human: visually identical). Existing CLI tests pass without modification. `--quiet`, `--rule-pack`, `--ignore`, `--dedupe-by-type`, `--level`, `--type` / `--old-type` / `--new-type`: all unchanged. `Diagnostic` model unchanged. `CompatibilityReport` shape unchanged. `DiffResult` shape unchanged.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| JSON output drift during refactor (Unit 1, Unit 3) | Existing per-key assertions in `tests/schema/test_cli.py` (TestBisectJson, TestHistory*) are the authoritative contract. Add structural-equivalence tests (`json.loads(new) == json.loads(old)`) as belt-and-suspenders. Run these green pre-refactor as the baseline. |
| GitHub Actions xsd validates output but Jenkins/GitLab/CircleCI may have stricter requirements (e.g., `time` attr on `<testsuite>`, specific `<system-out>` placement) | R3 narrowed: validates against GH Actions xsd; other consumers are best-effort. Document in README "Output Formatters" section that users on stricter consumers may need a custom formatter via `--formatter-module`. Future work could add multi-consumer xsd validation. |
| GitHub Actions xsd schema drifts upstream | Vendor the xsd into `tests/fixtures/junit-xml/JUnit.xsd` so the test target is pinned. Document the xsd version + commit SHA in a comment. |
| `xmlschema` and `jsonschema` libraries are heavy or slow | Used in tests only, not runtime. Both behind a new `[project.optional-dependencies] dev` group in `pyproject.toml` so `pip install protokit` doesn't pull them. |
| OASIS SARIF 2.1.0 schema drifts upstream or has permissive optional fields protokit doesn't populate | Vendor the schema into `tests/fixtures/sarif/sarif-2.1.0.json` (same pattern as xsd). Populate only the fields protokit actually needs; SARIF schema is permissive about optional fields. Document the vendored schema version + source URL. |
| SARIF severity mapping may not match what GitHub Code Scanning displays (e.g., WIRE → `"error"` but GH displays as `"warning"`) | Map SEMANTIC + WIRE findings to SARIF `"error"` (breaking); map POLICY to `"warning"` (advisory). Document the mapping in README's Output Formatters section so users know why a STRICT-profile WIRE finding shows up as a Code Scanning error. Future work could expose a mapping override via `FormatterContext`. |
| `click.STRING` vs `click.Choice` change loses Click's auto-generated help text listing valid choices | Provide explicit help text listing built-ins per kind: `"Output format. Built-in for compat: human, json, junit, sarif. Built-in for diff: human, json, junit. Use --formatter-module to add more."` |
| Registry singleton state leaks between tests; subprocess CLI tests can't reuse in-process formatters | `tests/conftest.py` autouse fixture clears user formatters after each test. Subprocess tests use `--formatter-module examples.custom_formatter` against a real on-disk module. Verify with `pytest -p xdist -n auto` in CI. |
| `--formatter-module` partial-load failure leaves registry inconsistent | Two-phase load (stage all entries; commit on full success). Test scenario explicitly covers this. |
| Stdout corruption when a formatter writes mid-render and then raises | Stdout-write guard: redirect `sys.stdout` to in-memory buffer for the duration of `fn(report, ctx)`; non-empty buffer triggers contract-violation error with non-zero exit. Document in README that formatters must be pure str-returning functions. |
| Built-in formatter shadowing by third-party packs | Built-in names reserved at registration time; `register_formatter` raises on attempted override. Documented as part of the trust model. |
| `FormatterKind` enum extension when LINT / SCHEMA_DIFF land later | `FormatterKind` is `Enum`, not `IntEnum` — adding new members is non-breaking. Document the noun-form naming convention (`SCHEMA_DIFF`, `LINT_REPORT`) in the module docstring. |
| `--formatter-module` import failure mode is opaque (e.g., user typo'd a class name inside the module) | Catch broad `Exception` in `_load_formatter_packs` and surface the original exception message verbatim, mirroring `_load_rule_packs`. |
| Performance regression from `get_formatter` lookup on every invocation | Negligible — single dict lookup per CLI run. Not in any hot loop. |

## Documentation / Operational Notes

- README.adoc gains an "Output Formatters" section (~70 lines) covering built-in inventory (all 15 built-ins), pluggable API example, `--formatter-module` usage, JUnit and SARIF output samples, SARIF severity mapping table, and a Trust-model subsection.
- CHANGELOG entry under "Unreleased" — Added: pluggable output formatter system; built-in JUnit formatters for all kinds; built-in SARIF 2.1.0 formatters for compat kinds; new public dataclasses `CommitDiagnostic`, `HistoryEntry`, `HistoryReport`, `BisectReport`; `Diagnostic` now exported from `protokit.schema`. Changed: `--format` is extensible via `--formatter-module`.
- TODOS.md updated to close items #3 and #4 from the 2026-04-12 CEO plan (with note that item #4 expanded in scope from JUnit-only to JUnit + SARIF during the 2026-04-19 document-review deepening) and explicitly mark #1 (deferred to Phase 3 docgen) and #2 (deferred to standalone brainstorm) with rationale.
- No migration required for users on the current `--format human|json` (no breaking changes).
- No new runtime dependencies. `xmlschema` and `jsonschema` are dev-only (new `[project.optional-dependencies] dev` group).

## Sources & References

- **Origin document:** `~/.gstack/projects/python_message_differencer/marc-main-brainstorm-phase-1.5b-ci-release-20260418-115400.md` (personal-workflow location, not checked into repo)
- **CEO plan:** `~/.gstack/projects/python_message_differencer/ceo-plans/2026-04-12-schema-compat-engine.md` (origin of accepted scope items #3 + #4)
- **Phase 1 design:** `~/.gstack/projects/python_message_differencer/marc-main-design-20260412-123909.md` (formatter system mentioned, not specified in detail)
- **JUnit schema:** https://github.com/EnricoMi/publish-unit-test-result-action/blob/main/test/files/junit-xml/JUnit.xsd
- **SARIF schema:** https://json.schemastore.org/sarif-2.1.0.json (OASIS 2.1.0)
- **SARIF spec:** https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html
- **Related code:**
  - `src/protokit/schema/cli.py:130-152` (`_load_rule_packs` pattern)
  - `src/protokit/schema/cli.py:776-780, 966, 1243, 1551` (current `--format` declarations)
  - `src/protokit/message/cli.py:398` (current `--format` declaration)
  - `src/protokit/schema/model.py` (existing dataclass conventions)
  - `src/protokit/message/model.py:79-125` (`Diagnostic`)
- **Audit findings:** in-session 2026-04-18 audit identified the dropped scope.
