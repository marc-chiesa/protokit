---
title: "feat: protokit-lint Delivery 5 — pyproject `[tool.protokit.lint]` config + `--exclude`"
type: feat
status: active
date: 2026-05-10
origin: docs/brainstorms/2026-05-09-protokit-lint-delivery-5-pyproject-config-requirements.md
---

# feat: protokit-lint Delivery 5 — pyproject `[tool.protokit.lint]` config + `--exclude`

## Overview

D5 brings per-project lint configuration to `protokit lint`. `[tool.protokit.lint]` in `pyproject.toml` lets projects pin profile selection, exclude globs, severity floor, max-warnings ceiling, and output format without flag soup on every invocation. D5 also folds in three deferrals: D3 R12 (`LintRuntimeWarning(category="min_severity_relaxed")` structured emission), D3 R17 (file-level exclusion co-designed with the pyproject `exclude` key), and D1 A5 (`tests/schema/lint/test_perf_smoke.py`).

D5 ships one **BREAKING** change: `LintRuntimeWarning.rule_id` widens from `str` to `str | None`. The accompanying JSON wire format for `runtime_warnings[].rule_id` becomes `string | null` for the two new `LintRuntimeWarning` categories (`min_severity_relaxed`, `all_files_excluded`). A pre-1.0 stability disclaimer in the README and CHANGELOG reframes the adopter contract honestly.

D5 also closes a latent silent-warning regression that pre-dates D5 (only `lint_json` rendered `report.runtime_warnings` since D3 ship; `lint_human`, `lint_junit`, and `lint_sarif` were silent on all warning categories). D5 establishes the cross-formatter render contract for all current and future `LintRuntimeWarning` categories.

## Problem Frame

D3 shipped `protokit lint` end-to-end against the `naming/snake-case-fields` canary, but every CLI invocation needs explicit flags. Real projects ship linters with per-project config checked into source — flake8/ruff/mypy/black all read `pyproject.toml` `[tool.<name>]` tables. Without project config, `protokit lint` users repeat the same flag soup on every invocation, which blocks D6's UX at production scale (more rules → more flag noise).

D5 is the **ergonomic foundation** for D6, not a strict blocker. D6's rule library lands whether config comes from CLI flags or pyproject; pyproject just makes D6's UX viable once N rules are firing. The prioritization reasons are documented in the origin brainstorm (see origin: `docs/brainstorms/2026-05-09-protokit-lint-delivery-5-pyproject-config-requirements.md`, "Why D5 before D6" subsection).

D5 also resolves a D3-flagged "MUST answer before implementation" question: per the D3 plan's risk-line 1806, the brainstorm answered that **pyproject is config-only at D5** — no plugin loading from pyproject; the `--rule-pack` code-execution surface is not widened by D5 (see origin: KD-1).

## Requirements Trace

The brainstorm enumerates R1–R26 plus letter-suffix sub-requirements introduced during the 4-pass review (R1a, R3a, R5a, R13a, R13a-precedence, R13b, R18a, R18b, R19a, R21a, R23a, R23b). All carry forward unchanged; the plan references them by number.

Briefly:

- **R1–R6**: pyproject discovery and parsing (CWD walk-up; `.git` boundary; `--config`/`--no-config`).
- **R3, R3a**: schema validation (unknown keys + type mismatches → hard error; list-valued keys reject non-string elements).
- **R7–R10, R13a, R13b**: file-level exclusion (`--exclude PATTERN`, pyproject `exclude`, pathspec gitignore-style globs, `--no-exclude` proportional override, `all_files_excluded` UX warning).
- **R11–R14**: precedence stack (CLI > pyproject > profile defaults; replace except `exclude` which appends).
- **R15–R16**: `profile` shape (string-or-list).
- **R17–R21a**: D3 R12 fold-in (Literal extension to 4 categories; `rule_id: str | None` BREAKING + R18a migration note + R18b pre-1.0 disclaimer; R19/R19a CLI-side emission; R20 source attribution; R21 breadcrumb removal at `cli.py:425-439` and `cli.py:498-503`; R21a cross-formatter render expansion).
- **R22–R24, R23a, R23b**: A5 perf smoke (synthetic 50×20×10 fixture; single CI cell linux+py3.12; `slow` marker registration; meta-test asserting at-least-one-cell-ran).
- **R25–R26**: deps (`tomli` for py3.10; `pathspec`).

Full text and rationale: see origin document.

## Scope Boundaries

### In scope (D5)

- `[tool.protokit.lint]` pyproject table, Tier I keys: `profile`, `exclude`, `min_severity`, `max_warnings`, `format`.
- CLI flags: `--config PATH`, `--no-config`, `--exclude PATTERN` (repeatable), `--no-exclude`.
- New `LintRuntimeWarning` categories: `min_severity_relaxed`, `all_files_excluded`.
- BREAKING: `LintRuntimeWarning.rule_id: str | None` (+ JSON wire format `string | null` for new categories).
- Pre-1.0 stability disclaimer (R18b) in README + CHANGELOG.
- Cross-formatter render expansion (R21a): `lint_human` (CLI-side stderr), `lint_junit` (`<system-out>`), `lint_sarif` (`runs[].properties.runtime_warnings`); all 4 categories rendered consistently across all 4 formatters.
- A5 perf smoke (`tests/schema/lint/test_perf_smoke.py`) on linux+py3.12 cell + meta-test.
- New deps: `tomli` (py<3.11), `pathspec` — both with upper-bound caps + signature verification (per origin Dependencies section).
- README updates: `[tool.protokit.lint]` schema docs + Security Considerations subsection enumerating bypass channels + pre-1.0 stability disclaimer.
- CHANGELOG D5 entry with `BREAKING:` marker + migration note.
- `slow` pytest marker registration in pyproject.toml.

### Out of scope (deferred)

Carried forward from origin's "Out of scope" list:

- Plugin loading from pyproject (`rule_packs = [...]`) — KD-1; deferred to D6/D7.
- Per-rule severity overrides; per-file rule overrides; `enabled_rules`/`disabled_rules` lists — D6 designs against actual rule library.
- Inline `# protokit:ignore` comment suppression — Phase 3 separate item.
- `--no-builtin-rules` flag — D6 ships second built-in pack.
- `--extend-exclude` flag — `--exclude` (append) + `--no-exclude` (override) cover the use cases.
- `--ignore` flag name — reserved for Phase 3 finding-suppression work.
- Standalone `protokit.toml` alternative — defer.
- `PROTOKIT_CONFIG` env var — defer.
- Aggregation across nested pyprojects — first-match-wins only.
- Verbose precedence breadcrumbs (`--show-resolved-config`) — origin Outstanding Q8; defer.
- JSON schema versioning (`schema_version` field) — origin Outstanding Q10; defer to D6/D7.
- `compat` pyproject support — origin Sibling-Parity Audit; lint only.

### Deferred to Separate Tasks

None. All D5 work lands in this delivery.

## Context & Research

### Relevant Code and Patterns

- **CLI flag patterns**: `src/protokit/schema/lint/cli.py:130-237` (option declarations); `--rule-pack` at line 159 is already `multiple=True` — D5 `--exclude` repeatable copies this pattern verbatim.
- **Mutually exclusive flag pattern**: `cli.py:262-265` (`--quiet` vs `--format=json/junit/sarif` mutex via `click.UsageError`); also `src/protokit/schema/cli.py:308-310` (`--since` vs `--against-base`). D5 `--config` vs `--no-config` uses this pattern.
- **Engine call site**: `engine.run(result, profile=composed_profile)` at `cli.py:489`. D5 inserts pre-engine exclude filtering + `all_files_excluded` short-circuit, and post-engine `min_severity_relaxed` CLI-side emission.
- **Existing breadcrumb to replace (R21)**: `cli.py:425-439` (conditional `if SEVERITY_RANK[override_severity] < SEVERITY_RANK[composed_floor]:` block; `click.echo(...)` body at lines 429-439). Lines 419-424 (the functional `dataclasses.replace(composed_profile, min_severity=override_severity)`) **STAY** — R19a relies on them.
- **Second stderr loop to remove (R21)**: `cli.py:498-503` (`for warning in report.runtime_warnings: click.echo(...)` loop — replaced by R21a's CLI-side render).
- **Error code registry**: `src/protokit/schema/lint/_cli_utils.py:57-68` (`_LINT_ERROR_CODES`). D5 adds: `pyproject-config-load`, `pyproject-config-invalid`. Exit code 2 (lint-internal) per D3 epilog at `cli.py:121-128`.
- **`LintRuntimeWarning` dataclass**: `src/protokit/schema/lint/model.py:344-426`. `category: Literal[...]` at line 422; `rule_id: str` at line 423. `frozen=True`; no `__post_init__` (no sequence fields). Field-population docstring table at lines 367-378.
- **`LintReport` dataclass**: `model.py:429-529`. `frozen=True`; `__post_init__` at 506-529 coerces all five sequence fields via `tuple(...)`. R19a/R13b's `dataclasses.replace(report, runtime_warnings=...)` pattern is sound.
- **`LintEngine.run` signature**: `engine.py:259-391`. Walks `compile_result.root_files` at line 358. D5 filters root_files CLI-side BEFORE `engine.run`; engine signature unchanged.
- **Formatter signatures**: all 4 lint formatters return `str` with no side effects. `lint_human` at `_builtin_lint.py:166`; `lint_json` at 227 (only one rendering `runtime_warnings` today, at lines 266-275); `lint_junit` at 374; `lint_sarif` at 487.
- **`lint_sarif` existing notifications**: `_builtin_lint.py:529-547` (entries on `runs[].invocations[].toolExecutionNotifications` for compile diagnostics; shape `{level, message, properties: {category}}`; no `descriptor.id`). `tool.driver` at lines 550-557 has `name/version/informationUri/rules` — no `notifications` array. D5 keeps these unchanged and adds runtime_warnings at `runs[].properties.runtime_warnings` (distinct channel; no descriptor.id retrofit per Outstanding Q17).
- **Test fixture pattern**: `tests/schema/lint/cli/conftest.py:69-135` (session-scoped fixtures compiling `.proto` via D1's `compile_protos_to_result`). D5 follows this for new fixtures (`vendor.proto`, multi-file fixture for `--exclude`).
- **Cold-import contract**: `tests/schema/lint/test_cold_import_extended.py` (subprocess tests; forbids `protokit.schema.lint.cli` substring + `protokit.formatters._builtin_lint` exact). D5's new `_config.py` lives under `protokit.schema.lint.` and is auto-quarantined by the substring check; no test edits required.
- **Static-analysis ratchet**: `tests/test_static_analysis.py:31-50` (`_LINT_PATHS` and `_TYPE_CHECK_PATHS` use directory entries). New files under `src/protokit/schema/lint/` and `tests/schema/lint/` auto-pickup — no ratchet edits needed. CI mirror at `.github/workflows/ci.yml:128-133`.
- **CI matrix**: `.github/workflows/ci.yml:39-45`. `runs-on: ubuntu-latest`; `python: ["3.10", "3.12"]` × `has_protoxy: [true, false]`. **py3.11 is NOT in the matrix** (correct in origin's R23b after pass-4 fix).
- **D3 plan structure**: `docs/plans/2026-05-04-001-feat-protokit-lint-d3-cli-plan.md` (6 units; R20a Reachability Matrix; per-unit Goal/Requirements/Dependencies/Files/Test scenarios/Verification structure). D5 mirrors this.

### Institutional Learnings

Eleven learnings flagged by `compound-engineering:research:learnings-researcher`. Wired into the plan as cross-references:

- `docs/solutions/best-practices/apply-institutional-learnings-postdating-plan-during-ce-review-2026-05-09.md` — wire fresh learnings into the plan now; ce:review converges faster on learning-grounded plans.
- `docs/solutions/best-practices/normalize-at-input-boundary-2026-05-07.md` — normalize Click flag values at callback boundary (`--exclude`, `--config`). pyproject string keys normalize once at `_config.py` boundary.
- `docs/solutions/best-practices/frozen-dataclass-mutable-fields-need-post-init-snapshot-2026-05-02.md` — `ResolvedLintConfig` uses tuples; pyproject `list` values coerce at boundary.
- `docs/solutions/security-issues/keyboardinterrupt-baseexception-bypass-rule-pack-load-2026-05-07.md` + `formatter-systemexit-exit-code-bypass-2026-04-19.md` — triple-arm `(SystemExit, KeyboardInterrupt, Exception)` guards around `tomllib.load`, glob compilation, path resolution.
- `docs/solutions/security-issues/module-name-newline-injection-stderr-forge-2026-05-07.md` — sanitize `\n`/`\r` on pyproject path / pattern strings before any stderr `click.echo`.
- `docs/solutions/best-practices/cross-format-enum-string-parity-2026-05-08.md` — canonical strings for category/source attribution pinned at `LintReport`/`LintRuntimeWarning` boundary, not per formatter.
- `docs/solutions/best-practices/audit-wire-format-before-claiming-sibling-parity-2026-05-03.md` — audit `--exclude` wire format against `compat`'s `--ignore-paths` and `ruff`'s `exclude` BEFORE claiming parity.
- `docs/solutions/best-practices/pytest-static-analysis-gate-ratchet-2026-05-02.md` — pay-as-you-touch; new D5 modules added to allowlist in same commit (auto-picked by directory entries).
- `docs/solutions/test-failures/pytestmark-does-not-guard-module-top-imports-2026-05-02.md` — use `pytest.importorskip` if D5 tests need conditional `tomllib`/`pathspec` imports (NOT `pytestmark = skipif`).
- `docs/solutions/test-failures/mock-patch-c-extension-method-descriptor-2026-05-06.md` — for D5 tests simulating `tomllib` parse errors or `Path.read_text` failures: use `monkeypatch.setattr` on the module-level binding, NOT `mock.patch` on stdlib internals.

### External References

Skipped. Phase 1.2 decision: well-grounded by repo + 4-pass brainstorm prior-art research (flake8, ruff, mypy, pylint, black, pre-commit, pytest, bandit, coverage.py, sphinx, isort all documented in origin).

## Key Technical Decisions

### KTD-1: SARIF mapping — drop `descriptor.id`; use `properties.subcategory`

**Decision (resolving origin Outstanding Q17)**: `runs[].properties.runtime_warnings` entries have shape `{level: "warning", message: {text: "..."}, properties: {category: "<category>", subcategory: "runtime"}}`. No `descriptor.id` field. Existing compile-stage notifications at `runs[].invocations[].toolExecutionNotifications` remain unchanged (no retrofit).

**Rationale**: Repo-research confirmed `tool.driver.notifications[]` doesn't exist today. Adding `descriptor.id` references without populating `tool.driver.notifications[]` to declare those descriptors fails strict SARIF 2.1.0 §3.58 validators. Two viable options were on the table: (a) declare `tool.driver.notifications[]` for both compile and runtime descriptors (full SARIF spec compliance; biggest D5 surface) or (b) drop `descriptor.id` and use `properties.subcategory` for filtering (smallest D5 surface; matches SARIF's open `propertyBag` semantics under `runs[].properties`). Picking (b): SARIF property bags are open and spec-compliant for non-standard data; existing `lint_sarif` already uses `runs[].properties` shape for the compat path with no schema-level conflict. D6 can promote to full descriptor refs if a real consumer requires it.

**Cross-command property-bag asymmetry (per plan-review adversarial ADV-4)**: `protokit lint` and `protokit compat` both emit SARIF but populate `runs[].properties` with different per-command keys. `lint` adds `runtime_warnings`; `compat` adds `commit`/`range_spec` per the existing `_sarif_json.py` patterns. Consumers handling both outputs should NOT assume cross-command schema parity at `runs[].properties` — each command's property-bag key set is per-command, not per-tool. U6 README documents this asymmetry explicitly to prevent consumer confusion.

### KTD-2: Schema validation API — frozen dataclass with `from_dict` classmethod

**Decision (resolving origin Outstanding Q18)**: `ResolvedLintConfig` is a frozen dataclass in `src/protokit/schema/lint/_config.py` with a `from_dict(table: dict, cli_overrides: dict) -> ResolvedLintConfig` classmethod that performs key-name validation (R3), type validation (R3a), and precedence application (R11–R14) in a single pass. Fields: `profile: tuple[str, ...]`, `exclude: tuple[str, ...]`, `min_severity: Severity | None`, `max_warnings: int | None`, `format: str | None`, plus per-key source attribution (`min_severity_source: Literal["cli", "pyproject", "profile", "default"]` + original pyproject value when applicable for R20's "both" message branch).

**Rationale**: Project has no pydantic/attrs/msgspec; existing model uses `@dataclass(frozen=True)` extensively. `from_dict` classmethod is consistent with stdlib idioms and avoids a validation-library dep. The carrier doubles as R19a's "ResolvedLintConfig-style provenance" carrier — no new abstraction needed.

### KTD-3: R23b fail-open mitigation — meta-test via static `.github/workflows/ci.yml` parse with `yaml.safe_load`

**Decision (resolving origin Outstanding Q13 + plan-review convergence: 4 personas pinned the implementation shape)**: `tests/schema/lint/test_perf_smoke_coverage.py` parses `.github/workflows/ci.yml` at test time using `yaml.safe_load` (NEVER `yaml.load()` without explicit `SafeLoader` — security: prevents arbitrary code execution via YAML object construction). Asserts that the matrix contains at least one cell matching the perf smoke's skipif predicate (linux + python `3.12`). If the file is absent, unparseable, or doesn't match: meta-test fails with a clear error (fail-closed, NOT skip).

**Rationale**: A floor predicate (`sys.version_info[:2] >= (3, 12)`) would also work but silently shifts behavior as matrix advances. Meta-test is loud-on-drift: if py3.12 leaves the matrix and no cell matches the skipif predicate, CI fails the meta-test in addition to silently skipping the smoke. Cost: ~25 LOC including YAML safe_load + matrix traversal + fail-closed error handling. Per-cell baselines (the more thorough alternative) require baseline-storage machinery and are out of D5 scope.

**Why static parse, not cross-cell aggregation**: the alternative shape (session-scoped fixture writes a marker file aggregated cross-cell via CI artifact downloads) requires NEW CI workflow plumbing (post-matrix aggregator job, artifact upload/download) NOT enumerated in this plan. The Documentation/Operational Notes section asserts "CI matrix: unchanged"; cross-cell aggregation would silently expand D5 into CI workflow design. Static parse stays within the test surface and is the only shape that fits D5 as scoped.

**`pytest -m "not slow"` interaction note**: the static parse verifies the matrix CONTAINS the predicate-matching cell, not that the cell ACTUALLY ran the smoke this CI run. A fast-iteration invocation using `pytest -m "not slow"` would skip the perf smoke even on the matching cell. This is acceptable for D5: fast-iteration runs are developer-local; CI runs use the default marker set and run the smoke. Document in the meta-test's docstring; if cross-cell-actual-run verification becomes a real need, that's a follow-up delivery.

**YAML parsing dependency note**: pyproject.toml does NOT currently include `PyYAML` as a dev dep (verified during plan-review). U6 adds `PyYAML` to `[project.optional-dependencies] dev` (or whichever group the test deps live in). Pin to a recent stable version with upper bound matching the project's semver policy.

### KTD-4: Multi-CLI-warning ordering — short-circuit + alphabetical

**Decision (resolving origin Outstanding Q12)**: When the resolved exclude set drops all files (`all_files_excluded` fires), the CLI **short-circuits `engine.run`** — no point walking zero files. `min_severity_relaxed` and `all_files_excluded` can both fire on the same invocation (relaxation is resolved pre-exclude). When multiple CLI-emitted warnings exist, they append to `report.runtime_warnings` in alphabetical order by category: `all_files_excluded` then `min_severity_relaxed`. Engine-emitted warnings (`rule_exception`, `unloaded_rule`) come first in the tuple per engine ordering; CLI-emitted warnings append after. Tests pin the order.

**Rationale**: Short-circuit is the obvious optimization (no work if no files). Alphabetical ordering is deterministic and easy to test; matches how `LintRuntimeWarning.category` Literal is ordered. Engine-first / CLI-last preserves the engine's own ordering semantics for the existing two categories.

### KTD-5: R3a element-type validation extends R3's UX contract

**Decision (resolving origin Outstanding Q11)**: R3a covers element-type errors for list-valued keys (`exclude`, `profile`). Heterogeneous arrays or wrong-element-type arrays produce the same hard-error UX as R3 (exit 2; message names key, element index, expected element type; offending value NOT echoed per R5a's content-safety constraint).

**Rationale**: TOML permits `exclude = ["a", 1, "b"]`. R3a's pass-3 examples covered scalar/list shape mismatches; pass-4 surfaced the element-type gap. Same UX surface as R3 keeps the validator's user-visible behavior coherent.

### KTD-6: Formatter stderr architecture — CLI-side post-format hook (not formatter side-effect)

**Decision (resolving origin pass-4 F1 + plan-review feasibility F3 on `--quiet` interaction)**: Formatter signatures stay pure (`(report, ctx) -> str`, no side effects). `lint_human`'s "stderr line per warning" is emitted by **CLI post-`render_with_formatter` dispatch**, after the formatter returns — CLI inspects `report.runtime_warnings` and emits stderr lines for `--format=human` invocations only. `lint_json`, `lint_junit`, `lint_sarif` embed warnings in their structured output as before.

**`--quiet` interaction**: The CLI-side stderr hook is **NOT gated by `--quiet`**. The existing breadcrumb being removed at `cli.py:498-503` had an inline comment stating it was "not gated by --quiet (which suppresses findings stdout only)" — D5 preserves that behavior. `--quiet` continues to suppress findings on stdout only; warnings on stderr remain visible regardless. This is the existing protokit posture; D5 does not change it.

**Rationale**: Existing formatter contract is pure; changing it for one formatter creates an asymmetric architecture and breaks `_run_lint_formatter_safely`. CLI-side emission centralizes warning-render policy in one place and keeps formatters portable (compat siblings reuse the same contract). Per-category summarization (`>5` threshold) lives in the CLI hook.

### KTD-7: Walk-up boundary uses `.exists()` not `.is_dir()` (worktree-safe); `.git` contents are not read

**Decision (resolving pass-4 P1)**: Walk-up termination check is `(parent / ".git").exists()` — covers both `.git` directories (standard checkouts) AND `.git` files (git worktrees, submodules, where `.git` is a `gitdir: ...` pointer file). Using `.is_dir()` would silently skip past worktree roots and continue walk-up into attacker-writable parent territory. **The `.git` path is checked for existence only; its contents (the `gitdir: ...` pointer in worktree `.git` files) are NEVER read, parsed, or followed by protokit lint.** Walk-up logic does not chase the gitdir pointer to the underlying repo root.

**Order of operations when both `.git` AND `pyproject.toml` exist at the same parent**: check `pyproject.toml` FIRST at that level (return it as the discovered config), THEN apply the walk-up termination signal. This preserves the "first-match-wins" semantics for pyproject discovery while keeping `.git` as the OUTER bound on how far walk-up may travel. U1 test scenarios pin this ordering explicitly.

**Rationale**: Modern CI systems (GitHub Actions with shallow clones, GitLab CI, Buildkite) use worktrees extensively. Verified during pass-4 security/feasibility review. The "contents never read" clarification prevents a future contributor from "helpfully" extending the check to follow gitdir pointers, which would introduce a new attack surface.

### KTD-8: Pre-1.0 stability disclaimer (R18b) softened around 1.0 surface commitment

**Decision (resolving origin Outstanding Q25 / pass-4 product-lens NEW-P5)**: R18b's disclaimer text reads: *"The 1.0 release will **define the stable public surface** and commit to semver compatibility for that surface."* (Softened from "will commit to semver compatibility for the public surface" — the original implied the surface was already defined.)

**Rationale**: The public surface is non-trivial (Python dataclass shapes, JSON schema, SARIF properties, CLI flags, exit code taxonomy). Committing to semver without first defining the surface is a documentation IOU. The softened wording acknowledges the surface-definition work as a precondition to 1.0.

### KTD-9: Triple-arm exception guards on new boundaries + newline sanitization at message-construction sites

**Decision (per `keyboardinterrupt-baseexception-bypass-rule-pack-load-2026-05-07.md` + `formatter-systemexit-exit-code-bypass-2026-04-19.md`)**: Every new D5 boundary that loads or evaluates user input — `tomllib.load`, `pathspec.PathSpec.from_lines`, `Path.resolve()`, walk-up file existence checks — uses the `(SystemExit, KeyboardInterrupt, Exception)` triple-arm catch with stable `error[lint-config-*]:` stderr prefix.

**Newline sanitization extends to message field construction (per plan-review SEC-D5-01/02)**: not only do stderr-bound strings get `\n`/`\r` collapse per `module-name-newline-injection-stderr-forge-2026-05-07.md`, but **pyproject-sourced strings interpolated into `LintRuntimeWarning.message` are also sanitized at message construction time** (in U3/U4, BEFORE the `message` field is set on the dataclass). This covers two paths:
- R20 source attribution: the `pyproject_min_severity` value in the "both" message branch is sanitized before string formatting.
- R13b `all_files_excluded`: if the message text references pattern strings (verify in U3), those are sanitized at construction time.
The U5 CLI-side stderr hook also applies a defense-in-depth sanitization pass on `{message}` slot before `click.echo` — message field should already be clean, but the stderr boundary applies the same `\n`/`\r` collapse as a backstop.

**R5a tomllib content-safety contract (per plan-review SEC-D5-03)**: if U1 verification finds that `tomli.TOMLDecodeError` includes raw file bytes in its message, the U1 implementation **replaces the message with the deterministic form `"TOML parse error at {filename}:{line}:{col}"` using only structured error attributes** (`pos.line`, `pos.column` on the exception object). Never expose `TOMLDecodeError.args[0]` directly in the error message. This converts the open-ended "wrap to sanitize" mitigation into a pre-committed contract.

**Rationale**: D3 ce:review converged on the triple-arm pattern after the rule-pack KI bypass. D5's new boundaries (pyproject loading, glob compilation) are analogous code-execution-adjacent surfaces. The newline-sanitization extension closes the message-field-construction path the pass-4 security review identified; the R5a fallback contract closes the open-ended IOU the pass-4 adversarial review identified.

### KTD-10: Click flag patterns for boolean off-switches

**Decision**: `--no-config` and `--no-exclude` use `is_flag=True` boolean options (idiomatic Click; matches how stdlib argparse handles negation flags). They are **not** `--config/--no-config` paired-flag shorthand (which exists in protokit at `--statistics/--no-statistics` per repo-research but doesn't fit D5's semantics — `--config` takes a PATH argument, not a boolean). `--config` and `--no-config` are mutually exclusive at parse time via the `click.UsageError` pattern at `cli.py:262-265`. `--no-exclude` wins over `--exclude` at resolution time (apply-time mutex, not Click-level rejection).

## Open Questions

### Resolved During Planning

- **BREAKING migration alternatives considered (per plan-review adversarial ADV-8)**: A backward-compat shim was considered (use `rule_id = ""` empty-string sentinel for the new categories instead of widening to `str | None`). Rejected because: (a) it would propagate the empty-string code-smell pattern to every future `LintRuntimeWarning` category author indefinitely, locking in the technical debt that R18's typing cleanup is specifically removing; (b) it makes the BREAKING change silent (consumers wouldn't see `null` and might assume the rule_id contract is unchanged), which is worse audit posture than an explicit BREAKING marker on the wire format. A deprecation-warning approach (emit `DeprecationWarning` for one release) was also considered; rejected because protokit is pre-1.0 (R18b reframes the contract) and the deprecation-cycle infrastructure adds carrying cost without proportionate benefit at this maturity. **D5 ships the BREAKING change directly with R18a migration recipes covering JSON/SARIF/Python consumers.**
- **SARIF descriptor.id retrofit** → KTD-1 (drop descriptor.id; use properties.subcategory).
- **Schema validation API shape** → KTD-2 (`ResolvedLintConfig.from_dict`).
- **R23b fail-open mitigation** → KTD-3 (meta-test asserting at-least-one-cell-ran).
- **Multi-CLI-warning ordering** → KTD-4 (short-circuit + alphabetical).
- **R3a element-type validation** → KTD-5 (extends R3's UX contract).
- **Formatter stderr architecture** → KTD-6 (CLI-side post-format hook).
- **Walk-up `.git` worktree compatibility** → KTD-7 (`.exists()` not `.is_dir()`).
- **R18b 1.0 surface wording** → KTD-8 (softened to "define the stable public surface").
- **Click flag patterns** → KTD-10 (`is_flag=True` for off-switches; UsageError for `--config`/`--no-config` mutex).

### Deferred to Implementation

- **Exact A5 threshold value** (origin Q1): calibrate during U6 from 5–10 local + CI runs on the linux+py3.12 cell. Method: `max_observed × 3`.
- **Synthetic `.proto` generator location** (origin Q2): reusable helper in `tests/schema/lint/_proto_generator.py` vs. inline in `test_perf_smoke.py`. U6 implementation call; lean toward inline if only `test_perf_smoke.py` uses it.
- **Exact `tomli` and `pathspec` minimum versions** (origin Q3): verify against PyPI metadata during U1; pin to recent stable. Recommendation: `tomli >= 2.0, < 3` and `pathspec >= 0.12, < 1`.
- **Help-text layout for new flags** (origin Q4): per-implementation polish in U1/U3. Group `--config`/`--no-config` adjacent in `--help`; group `--exclude`/`--no-exclude` adjacent.
- **Whether unknown keys also emit a structured warning alongside the hard error** (origin Q5): not at D5 — hard error only matches ruff/mypy/black precedent.
- **`--no-config` skips ALL pyproject reading vs only `[tool.protokit.lint]`** (origin Q6): only the `[tool.protokit.lint]` table. Other tool tables are irrelevant to protokit lint's behavior.
- **Test coverage shape for precedence stack** (origin Q7): U2 uses parametrized matrix tests (CLI × pyproject × profile) for the resolution rules; focused per-key tests for the override edge cases.
- **`--show-resolved-config` debugging flag** (origin Q8): not at D5; revisit after real user feedback emerges.
- **`runtime_warnings` ordering precise contract** (origin Q9): see KTD-4.
- **JSON schema versioning** (origin Q10): not at D5; ship at D6 or D7 when the next BREAKING change lands and the cost amortizes.
- **Walk-up trust model documentation** (origin Q14, Q15): README "Security Considerations" subsection (committed as D5 Success Criterion via KTD's three-layer-mitigation commitment); enumerates `.git`-as-terminator attacker primitive and no-`.git` CI environment caveats; recommends `--no-config` or `--config <pinned>` for untrusted-parent-CWD environments.
- **R21a stderr message content safety** (origin Q16): U4 constrains `LintRuntimeWarning.message` field construction for `rule_exception` category to `exception_type` string + sanitized message; never raw tracebacks or filesystem paths.
- **R21a SARIF descriptor declaration** (origin Q17): resolved by KTD-1 (drop descriptor.id entirely).
- **R3a schema-validation API shape** (origin Q18): resolved by KTD-2.
- **R13b cross-reference to Forward-Looking Risks** (origin Q19): U4 adds the cross-reference in R13b's message field docs.
- **D5 scope width** (origin Q20): user resolved during planning (keep current scope; 6 units; per-unit /ce:work + ce:review cadence absorbs breadth).
- **R21a per-formatter render shape vs. helper alternative** (origin Q21): per-formatter at D5 (matches current architecture); helper refactor is a D6+ option if real maintenance cost emerges.
- **F6 prioritization defense one-sidedness** (origin Q22): brainstorm-level concern; not a planning blocker. Doc carries it forward as is.
- **Identity Bet posture ambiguity** (origin Q23): brainstorm-level concern; not a planning blocker.
- **Three-layer mitigation asymmetry** (origin Q24): commit layer 1 (README Security Considerations subsection) as D5 Success Criterion in U6; layers 2-3 remain "guidance" in the brainstorm's Forward-Looking Risks section.

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

### Config resolution data flow

```
CWD ─ walk-up ─> first pyproject.toml under nearest .git boundary
                      │
                      ▼
                 tomllib.load
                      │  (triple-arm guard; newline-sanitized errors)
                      ▼
        [tool.protokit.lint] table (dict[str, Any])
                      │
                      ▼
       ResolvedLintConfig.from_dict(table, cli_overrides)
                      │  R3 + R3a validation
                      │  R11–R14 precedence
                      │  per-key source attribution
                      ▼
            ResolvedLintConfig (frozen)
                      │
                      ▼
              orchestrate CLI flow:
              ┌───────┴────────┐
              │                │
              ▼                ▼
        engine.run(...)    CLI post-engine hook:
              │              - emit min_severity_relaxed if floor relaxed
              ▼              - emit all_files_excluded if pre-engine filter dropped all
        LintReport(...)      - dataclasses.replace(report, runtime_warnings=...)
                                   │
                                   ▼
                            render_with_formatter
                                   │
                                   ▼
                     CLI post-format hook (--format=human only):
                     for warning in report.runtime_warnings:
                         click.echo(f"protokit lint: warning [{category}]: ...", err=True)
                     (apply summarization threshold)
                                   │
                                   ▼
                         stdout: formatter output
                         stderr: warning lines (human only)
```

### Precedence resolution per key (decision matrix)

| Key | CLI source | Pyproject source | Behavior when both present |
|---|---|---|---|
| `profile` | `--profile NAME` (repeatable, already `multiple=True`) | `profile = "..."` or `[...]` | CLI **replaces** pyproject entirely |
| `exclude` | `--exclude PATTERN` (repeatable) | `exclude = [...]` | CLI **appends** to pyproject; `--no-exclude` bypasses both |
| `min_severity` | `--min-severity LEVEL` | `min_severity = "..."` | CLI replaces; relaxation emits `min_severity_relaxed` warning |
| `max_warnings` | `--max-warnings N` | `max_warnings = N` | CLI replaces |
| `format` | `--format FMT` | `format = "..."` | CLI replaces |

## Success Criteria

D5 ships when **all** of the following hold (mirrors origin Success Criteria; carry-forward verified per Phase 5.1):

1. `protokit lint` discovers `[tool.protokit.lint]` via CWD walk-up (terminating at first `.git` per R1a) and applies its values per the precedence rules in R11–R14.
2. `--config PATH` and `--no-config` flags work as specified, with R5a shadow paths (missing/unreadable/table-absent/invalid-TOML) all producing exit 2 with newline-sanitized stderr.
3. `--exclude PATTERN` (CLI, repeatable), `--no-exclude` (R13a override), and `exclude = [...]` (pyproject) all behave per R7–R13b. CLI patterns append to pyproject; `--no-exclude` bypasses entirely; `all_files_excluded` runtime warning fires when zero files survive exclusion.
4. Unknown keys in `[tool.protokit.lint]` (top-level or nested) produce a hard error naming the recognized keys (R3); type mismatches including heterogeneous list elements produce the same UX (R3a/KTD-5).
5. `LintRuntimeWarning(category="min_severity_relaxed")` is emitted CLI-side per R19/R19a trigger; `rule_id: str | None` is the new dataclass shape (BREAKING — see R18/R18a); stderr conditional at `cli.py:425-439` and second stderr loop at `cli.py:498-503` are both removed.
6. `tests/schema/lint/test_perf_smoke.py` runs to completion within threshold on the designated CI matrix cell (linux+py3.12 per R23b); skips cleanly on other cells via `@pytest.mark.skipif(...)`; `tests/schema/lint/test_perf_smoke_coverage.py` meta-test asserts at-least-one-cell-ran per KTD-3.
7. README gains: `[tool.protokit.lint]` schema documentation section (R6 working-tree-anchored note), **Security Considerations subsection** committing layer 1 of the three-layer mitigation strategy per origin Q24 (enumerates configuration-data bypass channels, walk-up boundary trust assumptions including no-`.git` CI caveat per Q14/Q15, and recommends `--no-config` or `--config <pinned>` for untrusted-parent-CWD environments), and the pre-1.0 stability disclaimer per R18b/KTD-8.
8. CHANGELOG D5 entry covers: pyproject config table, `--exclude`/`--no-exclude`/`--config`/`--no-config` flags, D3 R12 structured warning, `pathspec` + `tomli` deps. CHANGELOG includes `BREAKING:` marker for R18 (`LintRuntimeWarning.rule_id` widened to `str | None`; JSON `runtime_warnings[].rule_id` may be `null` for `min_severity_relaxed`/`all_files_excluded`; SARIF gains `runs[].properties.runtime_warnings`) with migration recipes in R18a (concrete recipes for JSON, SARIF, Python API consumers).
9. `tests/test_static_analysis.py` ratchet auto-covers the new files under D5's directory globs.
10. Cross-formatter render parity: all 4 `LintRuntimeWarning` categories (2 existing + 2 new) render consistently across all 4 lint formatters (lint_human stderr, lint_json, lint_junit `<system-out>`, lint_sarif `runs[].properties.runtime_warnings`) — closes the latent D3 silent-warning regression for `rule_exception`/`unloaded_rule` in 3 of 4 formatters per R21a.
11. All 1056-baseline tests still pass; static-analysis ratchet still passes; cold-import contract test still passes.

## Implementation Units

> **Sequencing note (auto-fix per plan-review pass: 3-persona convergence on U3/U4 sequencing).** U3 emits `LintRuntimeWarning(category="all_files_excluded", rule_id=None, ...)` at completion of its unit — but that requires the `LintRuntimeWarning.category` Literal to include the new entry AND `rule_id` to be widened to `str | None`. The atomic dataclass change in `model.py:422-423` must therefore land **before** U3 can build cleanly under mypy --strict / the static-analysis ratchet. **Resolution**: U3 owns the atomic dataclass change in `model.py` as its first step (Literal extension + `rule_id` widening for ALL 4 categories — both new categories declared at the same time). U4 then ships only the CLI emission code for `min_severity_relaxed`, the R21 breadcrumb removal, and any consumer-side updates that were not made in U3.

- [ ] **U1: Dependencies + pyproject loader module + walk-up discovery + `--config` / `--no-config` flags**

**Goal:** Establish the pyproject reading substrate: new internal module loads `[tool.protokit.lint]` via CWD walk-up (terminating at `.git` boundary via `.exists()`), exposes the parsed table for U2's schema validator. Introduces `tomli` (py<3.11) and `pathspec` as required deps. Adds `--config PATH` and `--no-config` CLI flags with mutex behavior.

**Requirements:** R1, R1a, R5, R5a, R6, R25, R26.

**Dependencies:** None (foundational).

**Files:**
- Create: `src/protokit/schema/lint/_config.py`
- Modify: `src/protokit/schema/lint/cli.py` (add flags + orchestrate loader before engine flow)
- Modify: `src/protokit/schema/lint/_cli_utils.py` (add `pyproject-config-load`, `pyproject-config-invalid`, and `exclude-pattern-invalid` to `_LINT_ERROR_CODES`; the third is used by U3 for pathspec compilation failures)
- Modify: `pyproject.toml` (add `tomli >= 2.0, < 3; python_version < "3.11"`; add `pathspec >= 0.12, < 1`; register `slow` pytest marker in `[tool.pytest.ini_options]`)
- Test: `tests/schema/lint/_config/test_walkup.py`
- Test: `tests/schema/lint/_config/test_loader.py`
- Test: `tests/schema/lint/cli/test_config_flags.py`

**Approach:**
- New module `_config.py` exports: `load_pyproject_config(explicit_path: Path | None, no_config: bool) -> dict[str, Any] | None`. Returns `None` when no config found OR when `no_config=True`.
- Walk-up implementation: iterate `(Path.cwd(), *Path.cwd().parents)`; for each, check `(parent / ".git").exists()` (worktree-safe per KTD-7); if `.git` exists, terminate walk-up (check this `parent` then stop); for each candidate `parent`, check `(parent / "pyproject.toml").is_file()`; first match wins.
- Triple-arm guard around `tomllib.load` per KTD-9; emit `error[lint-config-load]: <newline-sanitized message>` to stderr; exit 2 with code `pyproject-config-load`.
- `--config PATH` shadow-path handling per R5a: missing file → exit 2; unreadable → exit 2; valid TOML lacking `[tool.protokit.lint]` table → exit 2 (explicit-path strict mode, distinct from walk-up's silent fallback); invalid TOML → exit 2 with `tomli` error location (verify in U1: `tomli.TOMLDecodeError` does not echo raw file bytes).
- `--config` and `--no-config` mutually exclusive via `click.UsageError` pattern (`cli.py:262-265` precedent).
- Tomllib import pattern (per `module pytest pytestmark` learning — use module-top import, not `pytestmark`):
  - In `_config.py`: `if sys.version_info >= (3, 11): import tomllib; else: import tomli as tomllib`
- Module location: `src/protokit/schema/lint/_config.py` (leading underscore → internal). Imported only from `cli.py`. **NOT re-exported from `src/protokit/schema/lint/__init__.py`** — preserves cold-import contract.

**Patterns to follow:**
- Click flag declaration: `cli.py:130-237` (existing options).
- Mutex pattern: `cli.py:262-265` (`--quiet` vs `--format=json/junit/sarif`).
- Error-code emission: `_cli_utils.py` `error_exit_with_code(code, message)`.
- Tuple-snapshot frozen-dataclass: `model.py:506-529` (LintReport `__post_init__`).
- Subprocess-based cold-import test: `tests/schema/lint/test_cold_import_extended.py`.

**Test scenarios:**

*Happy path:*
- Walk-up from CWD with `pyproject.toml` in CWD → returns parsed `[tool.protokit.lint]` table.
- Walk-up from `subdir/` with `pyproject.toml` in CWD's parent (no intervening `.git`) → returns table from parent.
- Walk-up reaches first `.git` directory (standard checkout) AND `pyproject.toml` at that level → returns table.
- Walk-up reaches `.git` FILE (git worktree; `.git` contains `gitdir: <path>`) AND `pyproject.toml` at that level → returns table. **KEY**: verifies KTD-7 (`.exists()` not `.is_dir()`).
- `--no-config` flag → returns `None`; loader does not call `tomllib.load`.
- `--config valid.toml` with `[tool.protokit.lint]` table → returns parsed table; walk-up bypassed.

*Edge cases:*
- Walk-up reaches filesystem root without finding `.git` (no-checkout CI scenario): returns `None`; CLI proceeds with built-in defaults silently per R5. README note documents the trust assumption.
- Walk-up finds `pyproject.toml` but the `[tool.protokit.lint]` table is absent: returns `None`; CLI proceeds with built-in defaults silently.
- Walk-up finds `pyproject.toml` outside `.git` boundary first, before reaching `.git`: returns that table (first-match-wins; walk-up termination is the OUTER bound, not the priority).

*Error paths:*
- `--config /nonexistent` → exit 2; stderr names path (newline-sanitized); error code `pyproject-config-load`.
- `--config /etc/passwd` → exit 2; TOML parse error; verify error message does NOT echo file content (defense for R5a).
- `--config valid.toml` with no `[tool.protokit.lint]` table → exit 2; explicit-path strict mode error.
- `--config invalid.toml` (malformed TOML) → exit 2; pass through `tomli` location info; verify no raw file bytes.
- `--config X --no-config` → Click `UsageError` at parse time; exit 2.
- `tomllib.load` raises `SystemExit` (malicious config): triple-arm guard catches; emit `error[lint-config-load]`; exit 2 — NOT a silent false-success.
- `tomllib.load` raises `KeyboardInterrupt`: triple-arm guard catches the bare-except surface (preventing silent bypass), then **re-raises** `KeyboardInterrupt` so the user's SIGINT propagates to Python's default handler (exit 130 with standard traceback). This matches the existing protokit posture per the `keyboardinterrupt-baseexception-bypass-rule-pack-load-2026-05-07.md` learning: catch-and-reraise prevents the bypass without absorbing the user's interrupt signal. **Decision locked at plan time** per scope-guardian F5 (no implementation-time branching surface).

*Integration scenarios:*
- Cold-import contract test (`test_cold_import_extended.py`) still passes: importing `protokit.schema` does NOT pull `protokit.schema.lint._config`.
- Static-analysis ratchet auto-picks up `_config.py` under `src/protokit/schema/lint/` glob.

**Verification:**
- `_config.py` exists and is internal (not re-exported from `__init__.py`).
- Walk-up handles both `.git` directory and `.git` file shapes (verified by tests).
- All R5a shadow paths produce exit-2 with newline-sanitized stderr (the test scenarios above enumerate the 7 distinct error conditions; the brainstorm origin's "11 shadow paths" count includes path-shape × error-type combinations — the planner-level coverage is the 7 conditions enumerated here, which collectively span all 11 brainstorm-level combinations).
- Cold-import test passes.
- `tomli` is conditionally installed for py3.10 only; py3.12 uses stdlib `tomllib`.
- `slow` marker registered in `pyproject.toml`.

---

- [x] **U2: Schema validation (R3, R3a) + `ResolvedLintConfig` + precedence engine** — SHIPPED 2026-05-11

**Goal:** Validate the loaded pyproject table (key names per R3, types per R3a including list-element types per KTD-5) and compose with CLI overrides into a `ResolvedLintConfig` carrier (frozen dataclass per KTD-2) that retains per-key source attribution for R20's three message branches.

**Requirements:** R2, R3, R3a, R11–R16.

**Dependencies:** U1 (loader returns the table).

**Files:**
- Modify: `src/protokit/schema/lint/_config.py` (add `ResolvedLintConfig` frozen dataclass + `from_dict` classmethod + validation helpers + precedence engine)
- Modify: `src/protokit/schema/lint/cli.py` (call `ResolvedLintConfig.from_dict` after U1 loader returns; pass result to engine.run prep)
- Test: `tests/schema/lint/_config/test_schema_validation.py`
- Test: `tests/schema/lint/_config/test_precedence.py`
- Test: `tests/schema/lint/_config/test_resolved_config.py`

**Approach:**
- `ResolvedLintConfig` frozen dataclass; tuple-valued list fields with `__post_init__` snapshot per `frozen-dataclass-mutable-fields-need-post-init-snapshot` learning. Fields:
  - `profile: tuple[str, ...]` (always coerced to tuple; scalar input gets wrapped)
  - `exclude: tuple[str, ...]`
  - `min_severity: Severity | None`
  - `max_warnings: int | None`
  - `format: str | None`
  - `min_severity_source: Literal["cli", "pyproject", "profile", "default"]`
  - `pyproject_min_severity: Severity | None` (retained for R20 "both" message branch)
- `from_dict(table: dict[str, Any] | None, cli_overrides: dict[str, Any]) -> ResolvedLintConfig` runs:
  1. Key-name validation (R3): hard error if any key outside R2's allowlist (`{profile, exclude, min_severity, max_warnings, format}`). **R2's allowlist contains zero sub-table-valued keys**, so the contract is effectively "top-level allowlist only": any nested table like `[tool.protokit.lint.rules.foo]` surfaces as an unknown top-level key (`rules`) and triggers R3's error. The error message names the unknown TOP-LEVEL key (e.g., `"rules"`), not the dotted path. This is consistent with KTD-2's single-pass posture; D6 may extend to dotted-path error messages when the schema gains nested tables. Error message names recognized keys; offending value NOT echoed.
  2. Type validation (R3a): coerce scalars per R15-16; reject lists with non-string elements; reject scalars where lists expected (and vice versa); reject ints/strs in mismatch.
  3. Precedence application (R11–R14): CLI > pyproject > defaults; `profile` replaces; `exclude` appends; others replace; `--no-exclude` clears exclude entirely.
  4. Source attribution computed during precedence application.
- Normalize at boundary per `normalize-at-input-boundary` learning: lowercase string keys for severity comparison; strip whitespace; canonicalize path separators in exclude patterns (already pathspec-internal).
- Three message templates pinned at the `ResolvedLintConfig` boundary per `cross-format-enum-string-parity` learning, so all formatters emit identical text.

**Patterns to follow:**
- Frozen dataclass + `__post_init__` tuple coercion: `model.py:506-529`.
- D2's `LintProfile.compose` (engine.py) for multi-profile composition (call into existing API).

**Test scenarios:**

*Happy path:*
- Table with all 5 keys at valid types → `ResolvedLintConfig` populated.
- Table with only `profile = "default"` → profile populated, others None.
- Table with `profile = ["default", "strict-naming"]` → multi-profile composed via existing D2 machinery.
- CLI provides `--max-warnings 0` alone → CLI source attributed.

*Edge cases:*
- Scalar profile coerced to single-element tuple.
- `--no-exclude` flag → exclude resolves to empty tuple regardless of pyproject `exclude = [...]`.
- pyproject `min_severity = "warning"` + CLI `--min-severity error` (CLI restores) → resolved=error; no relaxation warning fires.
- pyproject `min_severity = "warning"` + CLI absent → relaxed; `min_severity_source = "pyproject"`.
- pyproject relaxed AND CLI relaxed more → `min_severity_source = "cli"`; `pyproject_min_severity` retained for "both" message.

*Error paths (R3):*
- Unknown top-level key `excldue = [...]` → exit 2; message names recognized keys.
- Unknown nested key `[tool.protokit.lint.rules.foo]` → exit 2 (per F1 / KTD-2 uniform handling).
- Empty `[tool.protokit.lint]` table → returns config with all defaults (not an error).

*Error paths (R3a / KTD-5):*
- `min_severity = 1` (int instead of str) → exit 2; type mismatch.
- `max_warnings = "0"` (str instead of int) → exit 2.
- `exclude = "vendor/**"` (scalar instead of list) → exit 2 (note: profile string-or-list is allowed; exclude is list-only).
- `exclude = ["a", 1, "b"]` (heterogeneous list) → exit 2; message names key + element index.
- `exclude = ["a", true]` → exit 2.
- `profile = [1, 2]` (list with non-strings) → exit 2.

*Integration scenarios:*
- ResolvedLintConfig flows into U4's R19/R19a CLI emission with correct source attribution.

**Verification:**
- All R3 / R3a / KTD-5 cases produce exit-2 with consistent error format.
- ResolvedLintConfig is frozen + tuple-snapshotted (mutation attempts raise).
- Precedence resolution matches the decision matrix in High-Level Technical Design.
- Static-analysis ratchet still passes.

---

- [ ] **U3: File-level exclusion — atomic dataclass change + pathspec + `--exclude` / `--no-exclude` + filter at CLI**

**Goal:** Land the atomic dataclass prerequisite (Literal extension to 4 categories + `rule_id` widening to `str | None`) so both new D5 categories can be constructed without breaking mypy --strict. Apply gitignore-style globs (pathspec) to `FileDescriptorProto.name` between compile and `engine.run`. Short-circuit `engine.run` when zero files survive exclusion. Emit `LintRuntimeWarning(category="all_files_excluded")` CLI-side per KTD-4 + KTD-6.

**Requirements:** R7–R10, R13, R13a, R13a-precedence, R13b. Plus the dataclass-change subset of R17 + R18 (Literal + `rule_id: str | None` foundation; the CLI emission of `min_severity_relaxed` itself remains in U4).

**Dependencies:** U1, U2 (ResolvedLintConfig has exclude patterns ready).

**Files:**
- Modify: `src/protokit/schema/lint/_config.py` (add `compile_exclude_patterns(patterns: tuple[str, ...]) -> pathspec.PathSpec` helper)
- Modify: `src/protokit/schema/lint/cli.py` (add `--exclude PATTERN` and `--no-exclude` flags; apply filter between `_load_descriptor_sets_to_result` / `compile_protos_to_result` (~`cli.py:347`/`cli.py:311`) and `engine.run` (`cli.py:489`); emit `all_files_excluded` warning CLI-side when filter result is empty)
- Modify: `src/protokit/schema/lint/model.py` (extend `category: Literal` at line 422 to include all 4 categories: `Literal["rule_exception", "unloaded_rule", "min_severity_relaxed", "all_files_excluded"]`; widen `rule_id: str` → `rule_id: str | None` at line 423; update docstring field-population table at lines 367-378 to include the 2 new categories with `rule_id=None`, `exception_type=None`, `descriptor_path=None`. **This is the atomic dataclass change** required by BOTH new categories' emission code.)
- Modify: `src/protokit/formatters/_builtin_lint.py` (update `lint_json` `runtime_warnings_payload` at lines 266-275 to be type-aware of `rule_id=None`; JSON `null` serialization is automatic but type annotations must allow it)
- Modify: `src/protokit/schema/lint/engine.py` (type-annotation-only update at the existing rule_exception/unloaded_rule emit sites; runtime behavior unchanged — they still always populate `rule_id` with a non-None string)
- Test: `tests/schema/lint/_config/test_exclude_patterns.py`
- Test: `tests/schema/lint/cli/test_exclude.py`
- Test: `tests/schema/lint/cli/test_no_exclude.py`
- Test: `tests/schema/lint/test_model_dataclass_changes.py` (verifies the Literal extension covers all 4 categories and `rule_id: str | None` is the new shape)

**Approach:**
- pathspec compilation: `pathspec.PathSpec.from_lines("gitwildmatch", patterns)` once per invocation; reuse for all match calls.
- Filter `compile_result.root_files` (a `tuple[str, ...]`): rebuild `compile_result` via `dataclasses.replace(compile_result, root_files=filtered_tuple)`. Engine sees post-filter `root_files`; descriptor pool still loads all files (R9: filtering applies to findings emission, not pool loading).
- `--no-exclude` wins over `--exclude` at apply-time (KTD-10): if `--no-exclude` is set, pass empty exclude tuple to `compile_exclude_patterns`; pyproject exclude is ignored.
- `all_files_excluded` short-circuit (KTD-4): if `len(filtered_root_files) == 0`, skip `engine.run`; emit warning CLI-side; produce empty `LintReport` with the warning attached.
- Audit wire format against compat's `--ignore-paths` and ruff's `exclude` (per `audit-wire-format-before-claiming-sibling-parity` learning) — confirm `gitwildmatch` matches ruff's pattern semantics in the expected ways.

**Patterns to follow:**
- `--rule-pack` repeatable Click flag at `cli.py:159` (`multiple=True`).
- `dataclasses.replace` on frozen dataclasses: pattern documented in R19a and used throughout `model.py`.
- pathspec `from_lines` API: standard pathspec usage; no project-internal pattern yet.

**Test scenarios:**

*Happy path:*
- `--exclude "vendor/**"` excludes files where `FileDescriptorProto.name` starts with `vendor/`.
- pyproject `exclude = ["**/test/*.proto"]` + CLI absent: pyproject patterns applied.
- pyproject `exclude = ["vendor/**"]` + CLI `--exclude "third_party/**"`: both apply (append per R13).
- pyproject `exclude = ["**/*"]` + CLI `--no-exclude`: no files excluded.
- Multi-file pool: one file excluded, others lint normally; descriptor pool still loads all files.
- gitignore-style negation: `exclude = ["vendor/**", "!vendor/important.proto"]` excludes vendor/ except `vendor/important.proto`.

*Edge cases:*
- Empty pattern list → no files excluded; engine.run proceeds normally.
- Pattern matches zero files → no behavior change.
- Pattern matches all files → `all_files_excluded` warning fires; engine.run short-circuited; report.findings is empty tuple.
- File with leading `./` in `descriptor.name` (rare but possible from `protoc -I.`): patterns should still match per pathspec normalization.

*Error paths:*
- Invalid glob pattern (pathspec rejects): exit 2; error code `exclude-pattern-invalid` (NEW code, distinct from `pyproject-config-invalid` per plan-review feasibility/security convergence — exclude patterns can come from CLI flags, not just pyproject, so reusing the pyproject-specific code would be misleading); message names pattern.
- Pattern with newline injection: sanitized in error messages per `module-name-newline-injection-stderr-forge` learning AND at message-field construction time per KTD-9.

*Integration scenarios:*
- Exclude + multi-rule-pack: each rule pack walks the post-filter file set.
- Exclude + `--since` (compat-only flag, NOT lint): documented in R6 — irrelevant to lint at D5; future delivery if lint gains git-ref flags.

**Verification:**
- pathspec installed and importable on both py3.10 and py3.12 cells.
- All R7–R13b behaviors covered by tests.
- `all_files_excluded` warning emits CLI-side with correct field population (rule_id=None, exception_type=None, descriptor_path=None) per Literal extension landing in U4.

---

- [ ] **U4: D3 R12 fold-in — CLI emission of `min_severity_relaxed` + R20 source attribution + R21 breadcrumb removal**

**Goal:** Convert the existing `cli.py:425-439` stderr breadcrumb into a structured `LintRuntimeWarning(category="min_severity_relaxed")` emitted CLI-side post-`engine.run` per KTD-6/R19a using the Literal entry + `rule_id: str | None` foundation landed in U3. Remove the second stderr loop at `cli.py:498-503`. Constrain `rule_exception` message field per Outstanding Q16 (no tracebacks/paths). The R18 BREAKING migration is finalized here via R18a CHANGELOG marker (lands in U6) — the dataclass change itself shipped in U3.

**Requirements:** R19, R19a, R20, R21. Plus the consumer-side completeness of R17/R18 (the dataclass change itself shipped in U3; U4 finalizes the emission code that uses it).

**Dependencies:** U2 (ResolvedLintConfig provides source attribution); U3 (atomic dataclass change is the foundation that U4 builds on; `all_files_excluded` category usage is also already established in U3).

**Files:**
- Modify: `src/protokit/schema/lint/cli.py` (remove conditional breadcrumb block at lines 425-439 — **keep lines 419-424** (the `dataclasses.replace(composed_profile, min_severity=override_severity)` call that makes `--min-severity` work); remove `runtime_warnings` echo loop at lines 498-503; add post-`engine.run` CLI-side emission for `min_severity_relaxed` per R19a using the Literal entry already shipped in U3; integrate with U3's pre-engine `all_files_excluded` emission for deterministic ordering)
- Modify: `src/protokit/schema/lint/engine.py` (audit existing rule_exception/unloaded_rule emit sites for the Q16 content-safety constraint: message field must NOT include raw exception tracebacks or filesystem paths; limit to `exception_type` string + sanitized message)
- Test: `tests/schema/lint/cli/test_min_severity_relaxed.py`
- Test: `tests/schema/lint/cli/test_breaking_migration.py` (validates the wire-format change is consistent with R18a)
- Test: `tests/schema/lint/test_engine_warning_content_safety.py` (Q16: rule_exception message field rejects raw paths/tracebacks)

**Approach:**
- Literal extension: `category: Literal["rule_exception", "unloaded_rule", "min_severity_relaxed", "all_files_excluded"]`. Field-population table extended: both new categories have `rule_id=None`, `exception_type=None`, `descriptor_path=None`.
- `rule_id` type widening: change line 423 from `rule_id: str` to `rule_id: str | None`. The mypy-strict narrowing pattern documented in the existing docstring (assert-after-category-branch for `descriptor_path`/`exception_type`) extends to `rule_id`. Audit all consumers of `w.rule_id`:
  - `cli.py:501` (the second stderr loop being removed in this unit) — no longer relevant.
  - `_builtin_lint.py:269` (lint_json runtime_warnings_payload) — emits `rule_id` directly; the JSON value becomes `null` for the new categories. Update test expectations.
  - `engine.py:333-342, 493-501` (engine emit sites for existing categories) — always populate `rule_id` with a non-None string; type annotation is the only change.
  - Future U5 formatter render code in lint_human/junit/sarif — handle `rule_id=None` per mypy-strict narrowing.
- R19/R19a CLI emission (KTD-4 + KTD-6):
  - Pre-engine: U3 emits `all_files_excluded` if filtered. If emitted, short-circuit engine.run.
  - Post-engine: compute relaxation diff using ResolvedLintConfig from U2. If `resolved.min_severity` ranks lower than the composed profile's intrinsic floor: emit `LintRuntimeWarning(category="min_severity_relaxed", rule_id=None, message=<source-attributed text>, exception_type=None, descriptor_path=None)`.
  - Append both via `dataclasses.replace(report, runtime_warnings=report.runtime_warnings + (cli_warnings_in_alpha_order))`. Alphabetical: `all_files_excluded` then `min_severity_relaxed`.
- R20 source attribution: three message templates per origin spec. CLI-source: `"--min-severity=warning relaxes profile floor from error to warning"`. Pyproject-source: `"[tool.protokit.lint] min_severity=warning relaxes profile floor from error to warning"`. Both: `"--min-severity=warning relaxes profile floor from error to warning (overriding pyproject min_severity=info)"`. Strings pinned at the CLI emission site (the `ResolvedLintConfig` boundary) per `cross-format-enum-string-parity` learning.
- R21 removal:
  - Drop `cli.py:425-439` (the entire conditional `if SEVERITY_RANK[...] < SEVERITY_RANK[...]:` block including the `click.echo(...)` body at lines 429-439). Lines 419-424 (the `dataclasses.replace(composed_profile, min_severity=override_severity)`) STAY — R19a relies on the override being applied before `engine.run`.
  - Drop `cli.py:498-503` (the `for warning in report.runtime_warnings: click.echo(...)` loop). U5's CLI-side post-format hook replaces this for `--format=human`.
- Content safety per Outstanding Q16: `rule_exception` message field must NOT include raw exception tracebacks or filesystem paths. Limit to `exception_type` string + sanitized message. Audit existing `engine.py` emit sites; constrain message construction.
- R18a migration note text lands in CHANGELOG + README in U6.
- R18b pre-1.0 stability disclaimer lands in CHANGELOG + README in U6.
- Cross-reference per Outstanding Q19: R13b's message field (in U3) gains a docstring pointer to "Configuration-data bypass posture beyond D5" in the brainstorm.

**Patterns to follow:**
- mypy-strict narrowing: existing `model.py:396-404` pattern (`assert w.descriptor_path is not None` inside `category == "rule_exception"` branch). Extends to `rule_id` for the existing two categories.
- `dataclasses.replace` on frozen LintReport: pattern documented in R19a.

**Test scenarios:**

*Happy path:*
- Profile floor = error, CLI `--min-severity=warning`: post-engine emits `LintRuntimeWarning(category="min_severity_relaxed", rule_id=None, message="--min-severity=warning relaxes profile floor from error to warning")`.
- Profile floor = error, pyproject `min_severity = "warning"`, CLI absent: emits with pyproject source attribution.
- Profile floor = error, pyproject `min_severity = "info"`, CLI `--min-severity=warning`: emits with "both" branch attribution.

*Edge cases:*
- pyproject relaxes, CLI restores → resolved=floor; NO warning fires.
- Profile floor at lowest level (info) → no relaxation possible; no warning.
- Both `all_files_excluded` AND `min_severity_relaxed` fire on same invocation: tuple order is `all_files_excluded` then `min_severity_relaxed` (alphabetical KTD-4); engine.run short-circuited per KTD-4.

*Error paths:*
- `rule_exception` warning's message field rejects raw traceback content (per Q16); audit existing engine emit sites to verify constraint.
- BREAKING migration: external code iterating `w.rule_id.upper()` raises `AttributeError` on the new categories — CHANGELOG and README migration note documents this.

*Integration scenarios:*
- `lint_json` output for `min_severity_relaxed`: `"rule_id": null` (wire format BREAKING — verified by test).
- `lint_json` output for existing `rule_exception`: `"rule_id": "some-id"` (unchanged).
- Mypy-strict pass on the codebase passes after R18 widening (narrowing assertions added at every consumer).

**Verification:**
- Literal lists exactly 4 categories.
- `rule_id` field is typed `str | None` in `model.py`.
- `cli.py:425-439` block removed; `cli.py:498-503` loop removed; `cli.py:419-424` retained.
- All consumers of `w.rule_id` handle the `None` case (formatters, tests).
- All-files-excluded short-circuits engine.run correctly (verified by test).
- Static-analysis ratchet still passes.

---

- [ ] **U5: Cross-formatter render expansion — `lint_human` (CLI-side stderr) + `lint_junit` (`<system-out>`) + `lint_sarif` (`runs[].properties.runtime_warnings`)**

**Goal:** **Establishes the cross-formatter `LintRuntimeWarning` render contract: all current and future warning categories render in all 4 formatters, regardless of category-specific behavior.** This is a deliberate observability commitment with permanent forward-tax implications for every future category author — D6+ category authors owe parity tests across 4 formatters. As a consequence, closes the latent silent-warning regression that pre-dated D5 (only `lint_json` rendered warnings since D3 ship; `lint_human` / `lint_junit` / `lint_sarif` were silent on all categories). The bug-fix is a corollary of the contract, not vice versa.

**Requirements:** R21a.

**Dependencies:** U4 (Literal + dataclass changes; CLI-side `dataclasses.replace`-driven warning emission).

**Files:**
- Modify: `src/protokit/formatters/_builtin_lint.py`:
  - `lint_junit` (line 374): append `<system-out>` entries on testsuite for each runtime_warning. Mirrors existing pattern at lines 364-370 for compile diagnostics. Each runtime_warning becomes one `<system-out>` entry; categories distinguishable via leading `[{category}]` token.
  - `lint_sarif` (line 487): add `runs[].properties.runtime_warnings = [...]` (per KTD-1). Entry shape: `{level: "warning", message: {text: "..."}, properties: {category: "<category>", subcategory: "runtime"}}`. No `descriptor.id`. Existing `runs[].invocations[].toolExecutionNotifications` array remains unchanged.
  - `lint_human`: NO CHANGE — formatter signature stays pure. CLI-side post-format hook in `cli.py` handles human stderr emission.
- Modify: `src/protokit/schema/lint/cli.py` (add CLI-side post-format hook that, when `--format=human`, iterates `report.runtime_warnings` and emits stderr lines with per-category summarization; threshold module-level constant `_LINT_HUMAN_SUMMARIZATION_THRESHOLD = 5`)
- Test: `tests/formatters/test_builtin_lint_runtime_warnings.py` (parametrized across 4 categories × 4 formatters)
- Test: `tests/schema/lint/cli/test_human_stderr_render.py` (CLI-side human stderr emission + summarization)

**Approach:**
- `lint_junit` `<system-out>`: each runtime_warning emits one `<system-out>` element on the testsuite with text content `[{category}] {message}`. Categories distinguishable via the leading token. Mirrors existing compile-diagnostic pattern.
- `lint_sarif` runs[].properties.runtime_warnings: append a list under `runs[].properties` (SARIF allows non-standard properties under any object). Entries are independent of `runs[].invocations[].toolExecutionNotifications` (which stays compile-diagnostics-only). Per KTD-1: drop `descriptor.id`; use `properties.subcategory` for filtering.
- `lint_human` stderr (CLI-side):
  - After `render_with_formatter` returns, the CLI inspects `report.runtime_warnings`.
  - If `ctx.format == "human"`: emit stderr lines.
  - Per-category counter; once count exceeds threshold (5), emit summarization line and stop emitting individual warnings for that category.
  - Stable prefix: `"protokit lint: warning [{category}]: {message}"`.
  - Summarization: `"protokit lint: warning [{category}]: ... and {N} more — use --format=json for full details"`.
- Machine formatters (`lint_json`, `lint_junit`, `lint_sarif`) emit ALL warnings unconditionally — summarization is human-only per pass-2/3 spec.
- `lint_json` unchanged in this unit (already renders warnings; the BREAKING handling of `rule_id=None` lands in U4).

**Patterns to follow:**
- Existing `lint_junit` compile-diagnostic rendering at lines 364-370 (`<system-out>` shape).
- SARIF `propertyBag` semantics: existing `lint_sarif` uses `properties` on multiple nodes; runs[].properties is well-precedented.
- Per-category counter pattern: stdlib `collections.Counter` or a simple dict.

**Test scenarios:**

*Happy path (parametrized 4 categories × 3 formatters):*
- Each of 4 categories renders in each of `lint_human` (CLI-side), `lint_junit`, `lint_sarif`.
- `lint_json` (already rendering) unchanged.

*Edge cases:*
- Empty `report.runtime_warnings`: no stderr lines, no `<system-out>` entries, no `runs[].properties.runtime_warnings` (or empty array — pin behavior).
- **Threshold-parametrized tests**: tests use `monkeypatch.setattr(module, "_LINT_HUMAN_SUMMARIZATION_THRESHOLD", N)` with small N (e.g., N=2) to assert behavior at N/N+1 boundaries — the tests assert the BEHAVIOR (boundary crossing triggers summarization), not the literal value 5. This keeps D6 tuning friction at zero (changing the constant requires zero test updates) per plan-review adversarial ADV-5.
- Boundary at the active threshold: at exactly threshold warnings of one category, all emit individually; at threshold+1, first `threshold` emit and the next is replaced by summarization line.
- N warnings each of 2 categories: each category summarized independently using its own counter.

*Integration scenarios:*
- D3 silent-warning regression: existing `rule_exception` warnings now render in lint_human stderr, lint_junit system-out, lint_sarif properties.
- BREAKING wire format: `lint_sarif` consumers see new `runs[].properties.runtime_warnings` array; SARIF spec validator accepts the addition per `propertyBag` semantics.

*Error paths:*
- Formatter rendering an empty message field: still emits one line/element (skip-empty would mask bugs).

**Verification:**
- All 4 categories render consistently across 4 formatters (verified by parametrized matrix tests).
- Summarization threshold is module-level constant for easy D6 tuning.
- D3 regression closed: `lint_human` --format=human now shows existing `rule_exception` / `unloaded_rule` warnings on stderr.
- SARIF output validates against a strict SARIF 2.1.0 validator (manual check or via `sarif-tools` if installed).

---

- [ ] **U6: A5 perf smoke + README + CHANGELOG + ratchet additions + R18b stability disclaimer**

**Goal:** Ship `tests/schema/lint/test_perf_smoke.py` per D1 A5 fold-in (single CI cell linux+py3.12 per KTD-3 + KTD-7 + R23b; meta-test asserts at-least-one-cell-ran). Land README updates (`[tool.protokit.lint]` schema docs + Security Considerations subsection committing layer 1 of the bypass-mitigation strategy + pre-1.0 stability disclaimer per R18b/KTD-8). Land CHANGELOG D5 entry with `BREAKING:` marker + migration note. Verify static-analysis ratchet auto-picks up new D5 files; verify cold-import contract preserved.

**Requirements:** R22, R23, R23a, R23b, R24, plus the documentation portions of R18a/R18b and Outstanding Q14/Q15/Q19/Q24/Q25.

**Dependencies:** U1–U5 (all behavior in place; this unit documents and tests at scale).

**Files:**
- Create: `tests/schema/lint/test_perf_smoke.py`
- Create: `tests/schema/lint/test_perf_smoke_coverage.py` (the meta-test per KTD-3)
- Modify: `README.md` (add `[tool.protokit.lint]` section + Security Considerations subsection + pre-1.0 stability disclaimer)
- Modify: `CHANGELOG.md` (D5 entry with BREAKING marker + migration note + pre-1.0 stability header)
- Modify: `pyproject.toml` (final dep version pin sanity check; `slow` marker registration verified)
- Modify: `tests/test_static_analysis.py` (only if globs don't auto-pick up `_config/` test subdir; verify and adjust if needed)
- Modify: `tests/schema/lint/test_cold_import_extended.py` (verify the new `_config.py` is covered by the substring match; add explicit assertion if not)

**Approach:**
- `test_perf_smoke.py`:
  - Skip predicate: `@pytest.mark.skipif(sys.platform != "linux" or sys.version_info[:2] != (3, 12), reason="perf smoke runs on linux+py3.12 only (R23b)")`. Also `@pytest.mark.slow` (registered via R23a in U1).
  - Synthetic fixture: parametrized .proto generator at test time; 50 files × 20 messages × 10 fields = 10,000 fields. Compiled via D1's `compile_protos_to_result`.
  - Threshold: empirical; calibration during U6 implementation from 5–10 local + CI runs. Documented method (`max_observed × 3`); the number is empirical.
  - Module docstring: smoke-not-benchmark intent (not verbatim per R23 pass-3 revision); the behavioral constraint communicated, exact wording is U6's call.
- `test_perf_smoke_coverage.py` (the meta-test per KTD-3):
  - Asserts that the chosen cell predicate matches at least one cell in the current CI matrix. Reads `.github/workflows/ci.yml` (or relies on a CI environment variable) to detect: did at least one of the matrix's cells run the perf smoke this CI run?
  - Simplest implementation: a session-scoped pytest fixture writes a small "ran-on-this-cell" marker file; the meta-test aggregates across cells via a CI artifact OR via a single CI job that runs after the matrix completes and inspects results.
  - Acceptable alternative for D5: a static assertion in the test that the skip predicate would match at least one cell of the current `.github/workflows/ci.yml` matrix — i.e., the test parses the matrix and verifies it contains a `python: 3.12` + ubuntu cell. If matrix advances past py3.12 without updating the skipif predicate, this test fails loudly.
  - Pick the simpler shape during U6 implementation.
- README updates:
  - New `[tool.protokit.lint]` section: schema (the 5 Tier I keys), discovery (CWD walk-up to first `.git`), `--config`/`--no-config` flags, working-tree-anchored note (R6).
  - New "Security Considerations" subsection (Outstanding Q14, Q15, Q19, Q24 layer 1): enumerates the bypass channels (`exclude`, `min_severity`, `max_warnings`, `profile` switches); states that pyproject changes affecting lint policy require code-review discipline; documents the `.git`-boundary walk-up trust assumption and the no-`.git` CI environment caveat; recommends `--no-config` or `--config <pinned>` for untrusted-parent-CWD environments; cross-references the brainstorm's "Configuration-data bypass posture beyond D5" Forward-Looking Risks subsection.
  - Pre-1.0 stability disclaimer (R18b/KTD-8): *"protokit is pre-1.0. Minor-version releases may include breaking changes to public Python APIs and machine output formats (JSON, JUnit, SARIF). Breaking changes are explicitly marked `BREAKING:` in CHANGELOG entries; consumers should pin to a specific minor version (e.g., `protokit~=0.5.0`) until 1.0 ships. The 1.0 release will define the stable public surface and commit to semver compatibility for that surface."*
  - **Public Surface (DRAFT — frozen at 1.0)** appendix (per plan-review product-lens G2 — starts paying down the KTD-8 IOU): a stub section enumerating the candidate stable surface across (a) Python dataclasses (`LintReport`, `LintRuntimeWarning`, `LintFinding`, `LintProfile`, `LintRuleSpec`), (b) JSON wire format keys (`lint_json` output shape), (c) SARIF properties (`runs[].properties.runtime_warnings` shape), (d) CLI flags (the full lint flag surface), (e) exit code taxonomy. Marked DRAFT; each row marked tentatively `IN` or `INTERNAL`. Maintained each delivery so 1.0 inherits a defined surface rather than discovering it via accumulation. Even a stub appendix is a meaningful trajectory shift.
  - **Multi-profile R20 attribution note** (per plan-review adversarial ADV-2): when `profile = ["a", "b"]` composes multiple profiles, the resolved "profile floor" in `min_severity_relaxed` messages is the composed floor (a single value after D2's `LintProfile.compose`). The message does not name which contributing profile set the relaxed floor; users editing pyproject should consult the composed-profile result via D2's introspection API if attribution matters. (If real users hit confusion here, a follow-up delivery can extend the message template to include the resolved profile list; D5 stays minimal.)
  - **README adoption note** (per plan-review product-lens "fresh eyes" UX gap): include a short "Quick Start" example showing a typical `[tool.protokit.lint]` table + a typical `protokit lint` invocation, so a first-time reader sees the ergonomic-foundation value in concrete terms. This is documentation-side adoption hygiene; runtime validation remains the regression-test posture (the plan does not commit to a separate "fresh eyes" automated test suite at D5; accept this trade explicitly).
- CHANGELOG D5 entry:
  - Pre-1.0 stability disclaimer at the top of the D5 header.
  - `BREAKING:` marker: *"`LintRuntimeWarning.rule_id` is now `str | None`. JSON consumers of `report.runtime_warnings[].rule_id` must handle `null` for `category in {"min_severity_relaxed", "all_files_excluded"}`. SARIF consumers must handle the new `runs[].properties.runtime_warnings` array (existing `runs[].invocations[].toolExecutionNotifications` array unchanged)..."*
  - **Migration recipes** (per plan-review product-lens G3 — close the gap between "we warned you" posture and "we're helping you" identity):
    - *JSON consumer migration*: "If `rule_id` is `null`, treat as a non-rule-scoped warning; the `category` field tells you the source (`min_severity_relaxed` = pyproject/CLI relaxed the floor; `all_files_excluded` = no files survived exclude filtering)."
    - *SARIF consumer migration*: "Read `runs[].properties.runtime_warnings` in addition to `runs[].invocations[].toolExecutionNotifications`. The new array is for runtime warnings; the existing array remains compile-stage diagnostics. Each `lint_sarif` runtime_warnings entry has shape `{level, message: {text}, properties: {category, subcategory: 'runtime'}}` — no `descriptor.id`."
    - *Python API consumer migration*: "Add a `None` branch when narrowing `LintRuntimeWarning.rule_id`. The mypy-strict pattern: branch on `w.category`, then `assert w.rule_id is not None` for `category in {'rule_exception', 'unloaded_rule'}` (matching the existing pattern for `descriptor_path` and `exception_type`)."
  - Standard D5 feature entries: pyproject `[tool.protokit.lint]` table; `--config`/`--no-config`/`--exclude`/`--no-exclude` flags; cross-formatter `LintRuntimeWarning` render parity; `tomli`/`pathspec` deps.
- Static-analysis ratchet: verify `tests/test_static_analysis.py:_LINT_PATHS` and `_TYPE_CHECK_PATHS` auto-pick `_config/` test subdir (directory entries). The new test files under `tests/schema/lint/_config/` should be auto-covered. Verify in U6; adjust if not.
- Cold-import contract: verify `tests/schema/lint/test_cold_import_extended.py` covers the new `_config.py` (auto-covered by substring match `protokit.schema.lint`). Re-run subprocess test to confirm.

**Patterns to follow:**
- D3 conftest pattern at `tests/schema/lint/cli/conftest.py` (session-scoped fixtures compiling `.proto` via D1's `compile_protos_to_result`) — but at-test-time generation rather than checked-in fixtures.
- D3 plan's R20a Reachability Matrix style for documenting new error codes (`pyproject-config-load`, `pyproject-config-invalid`).

**Test scenarios:**

*Happy path:*
- `test_perf_smoke.py` runs on linux+py3.12 cell within threshold.
- All other CI cells skip the test cleanly with the documented `reason`.
- README section structure passes a Markdown linter / link checker.
- CHANGELOG D5 entry includes BREAKING marker text.

*Edge cases:*
- Synthetic fixture compilation completes within reasonable time on the chosen cell.
- Meta-test (`test_perf_smoke_coverage.py`) fails loudly if the CI matrix advances past py3.12 without updating the skipif predicate.

*Error paths:*
- Perf threshold exceeded: test fails with a clear message indicating regression (not flakiness); per docstring posture, the response is to investigate not to widen the threshold by reflex.

*Integration scenarios:*
- `pytest -m "not slow"` skips the perf smoke (fast iteration); default `pytest` runs it on the chosen cell.
- Cold-import test still passes after `_config.py` is introduced.

**Verification:**
- All 10 success criteria from origin met.
- README has `[tool.protokit.lint]` section + Security Considerations + pre-1.0 disclaimer.
- CHANGELOG D5 entry includes BREAKING marker + migration note.
- Perf smoke passes on linux+py3.12; skips on other cells; meta-test confirms at-least-one-cell-ran.
- All 1056-baseline tests still pass.

## System-Wide Impact

- **Interaction graph**:
  - CLI scope (`cli.py`) gains pre-engine exclude resolution + post-engine warning emission + post-format human-stderr hook.
  - `LintEngine.run` signature unchanged; engine sees post-filter `compile_result.root_files`.
  - `LintReport` / `LintRuntimeWarning` schema widens (BREAKING per R18); 4 lint formatters touched; lint_json wire format changes for new categories.
- **Error propagation**: `_LINT_ERROR_CODES` gains `pyproject-config-load`, `pyproject-config-invalid`, possibly `exclude-pattern-invalid`. All use exit code 2 (lint-internal) per D3 epilog. Triple-arm guards per KTD-9.
- **State lifecycle risks**: `tomllib.load` is one-shot; `pathspec` compilation is one-shot per invocation; both cached via `ResolvedLintConfig` immutability. No partial-write / cache / cleanup concerns.
- **API surface parity**: `compat` does NOT gain pyproject support at D5 (Sibling-Parity Audit in origin). If compat later wants pyproject support, that's its own post-D7 brainstorm.
- **Integration coverage**: cross-cutting integration tests at `tests/schema/lint/cli/` exercise the full pipeline (config load → schema validation → exclude filter → engine.run → warning emission → formatter render → CLI human-stderr hook).
- **Release pairing (per plan-review product-lens prioritization concern)**: U4 and U5 are atomic at the release boundary. U4 ships the BREAKING wire-format change and the two new warning category emission sites; U5 ships the cross-formatter render that makes those new warnings visible in `lint_human` / `lint_junit` / `lint_sarif`. Shipping U4 without U5 reinstates the silent-warning regression for the two NEW categories, which is worse than pre-D5 (since now the BREAKING change is in flight but the visibility regression continues). CI gating or the `ce:compound` boundary check must enforce U4 + U5 together as a release pairing — neither lands alone.
- **Unchanged invariants**:
  - `LintEngine.run` signature unchanged.
  - `LintReport` shape — fields added or widened, no fields removed or renamed.
  - `LintRuntimeWarning.rule_id` widened from `str` to `str | None` (BREAKING — but only the type widens, never narrows; existing two categories still always populate it).
  - Existing `lint_sarif` `runs[].invocations[].toolExecutionNotifications` array — unchanged.
  - Cold-import contract — preserved (`_config.py` is internal; not re-exported).
  - `--rule-pack` flag semantics — unchanged; pyproject does NOT support `rule_packs` key (KD-1).
  - Static-analysis ratchet auto-pickup behavior — unchanged; new files in covered directories pick up automatically.

## Risks & Dependencies

| Risk | Mitigation |
|---|---|
| `tomllib.load` echoes raw file bytes in error messages for non-TOML inputs (R5a content-safety concern) | U1 verification step: confirm `tomli.TOMLDecodeError` does not include raw file bytes. If it does, wrap error message construction to sanitize. |
| Walk-up `.git` boundary fails on git worktrees (pass-4 P1) | KTD-7: use `(parent / ".git").exists()` not `.is_dir()`; explicit test in U1 for the worktree shape. |
| Walk-up reaches `/` in no-`.git` CI environments and consumes attacker-writable parent pyprojects | U6 README "Security Considerations" subsection documents the trust assumption; recommends `--no-config` for these environments. (Hard mitigation deferred per Outstanding Q15.) |
| `.git`-as-terminator becomes attacker primitive (attacker can `mkdir /tmp/attack/.git`) | U6 README documents that walk-up trust assumes any write to a parent of CWD is already a higher-stakes compromise than pyproject injection. (Hard mitigation deferred per Outstanding Q14.) |
| `rule_id: str | None` BREAKING propagates to unaudited downstream consumers (Bazel, Buck, custom CI, SARIF/JSON ingestion pipelines) | R18a CHANGELOG `BREAKING:` marker + migration note + R18b pre-1.0 stability disclaimer reframes the contract. (Schema versioning deferred per Outstanding Q10.) |
| Per-formatter render in U5 creates permanent forward tax for D6+ category authors (pass-4 NEW-P2-B) | Accept the tax at D5 (per user decision in Phase 2). Helper-pattern refactor is a D6+ option if the cost materializes. |
| `lint_human` summarization threshold (`5`) is arbitrary and packages a value choice with a mechanism choice | Module-level constant `_LINT_HUMAN_SUMMARIZATION_THRESHOLD = 5` makes tuning a one-line change; tests use `monkeypatch.setattr` to assert behavior at parametrized N/N+1 boundaries (not the literal value 5), so test friction for D6 tuning is zero. **`5` is a placeholder pending D6 calibration** against real-world warning-count distributions. |
| KTD-3 meta-test couples to `.github/workflows/ci.yml` structure | Accepted trade for loud-on-drift behavior. The meta-test reads ci.yml at test time via `yaml.safe_load` — any future ci.yml restructure that changes matrix shape will require updating the meta-test's parser logic. The coupling cost is named in the meta-test's module docstring so future CI maintainers know why a perf-coverage test reads CI config. Documented per plan-review product-lens G5. |
| pathspec or tomli supply-chain issue (new deps) | Pin upper bounds; verify package signatures at U1 implementation; add both to dependabot/renovate config. |
| R3a element-type validation contract gap for nested-list edge cases | KTD-5 explicit + comprehensive test scenarios in U2. |
| Per-cell perf smoke fails-open silently when CI matrix advances past py3.12 | KTD-3 meta-test asserts at-least-one-cell-ran; CI fails if zero cells matched the skipif predicate. |
| Existing `cli.py:425-439` line range drift between plan and code | Use repo-relative refs; verify line numbers at U4 start. The conditional `if` block at lines 425-428 plus the click.echo body at lines 429-439 are atomic — remove together. |
| SARIF descriptor.id incomplete per spec | KTD-1: drop descriptor.id; use `properties.subcategory` for filtering. SARIF propertyBag semantics are spec-compliant for non-standard data. |
| `compile_result.root_files` filtering breaks descriptor-pool dependency loading | R9 documents the constraint: pool still loads all files; exclude filters findings emission only. U3 tests verify multi-file pool with cross-file refs. |

## Sibling-Parity Audit

D5 introduces pyproject reading **only** for `protokit lint`. `protokit compat` retains its CLI-only surface — intentional asymmetry documented in origin's Sibling-Parity Audit section. If compat ever grows pyproject support, that's a post-D7 brainstorm with stricter constraints (compat enforces wire compatibility; bypass channels are higher-stakes than for lint findings).

`--rule-pack` flag continues to work the same way in both `lint` and `compat` (D3 sibling-parity hardening preserved). pyproject does NOT widen this surface (KD-1).

## Documentation / Operational Notes

- **README**: U6 lands two new subsections (`[tool.protokit.lint]` config + "Security Considerations") and the pre-1.0 stability disclaimer. The Security Considerations subsection commits layer 1 of the three-layer mitigation strategy per origin Outstanding Q24.
- **CHANGELOG**: U6 lands the D5 entry with `BREAKING:` marker, migration note, pre-1.0 stability disclaimer header.
- **Help text**: U1 + U3 ship new flag help strings; group `--config`/`--no-config` and `--exclude`/`--no-exclude` adjacent in `protokit lint --help`. Help text drift not gated by CI (per D3 R20a).
- **CI matrix**: unchanged; `.github/workflows/ci.yml` matrix stays at `python: ["3.10", "3.12"]` × `has_protoxy: [true, false]`. Perf smoke pinned to one cell via skipif; meta-test asserts at-least-one-cell-ran.
- **Static-analysis ratchet**: auto-pickup via directory entries (verified). No ratchet edits needed unless new tests land outside `src/protokit/schema/lint/` or `tests/schema/lint/` trees.
- **TODOS.md**: after D5 ships, refresh to reflect D5 landed; D6 (rule packs beyond the canary) becomes the next entry. **TODOS.md refresh MUST include an explicit D6 line-item for JSON schema versioning** (origin Outstanding Q10 → plan-review product-lens G6 enforcement hook): this is a pre-commitment, not a discretionary call by the D6 planner, because each subsequent BREAKING change makes schema versioning harder to retrofit. The line should read: "*D6: ship `schema_version` field in `lint_json` root + corresponding SARIF property; deferred from D5 per origin Outstanding Q10; deferral cost amortizes when the next BREAKING change lands.*" The brainstorm's 25 Outstanding Questions that were "deferred to /ce:plan" are now either resolved in this plan or deferred to implementation; remaining deferrals (Q1-Q10 implementation-time) carry forward as work-during-units.
- **Operational rollout**: no special rollout. The BREAKING change is documented; consumers who pin `protokit~=0.5.0` are protected. No feature flag needed (D5 is a single release).
- **Memory updates**: after D5 ships, update `~/.claude/projects/-Users-marc-projects-python-message-differencer/memory/project_state.md` and `next_delivery_d5.md` to reflect D5 landed; next delivery becomes D6.

## Sources & References

- **Origin document**: [docs/brainstorms/2026-05-09-protokit-lint-delivery-5-pyproject-config-requirements.md](../brainstorms/2026-05-09-protokit-lint-delivery-5-pyproject-config-requirements.md) — 4-pass document review across coherence/feasibility/product-lens/security-lens/scope-guardian/adversarial personas; 25 Outstanding Questions absorbed.
- **D1 plan** (foundation): `docs/plans/2026-05-01-001-feat-protokit-lint-d1-foundation-plan.md`.
- **D2 plan** (engine + canary): `docs/plans/2026-05-02-001-feat-protokit-lint-d2-engine-plan.md`.
- **D3 plan** (CLI subcommand): `docs/plans/2026-05-04-001-feat-protokit-lint-d3-cli-plan.md` — structural template; R20a Reachability Matrix style adopted.
- **D3 brainstorm** (parent ecosystem context): `docs/brainstorms/2026-05-04-protokit-lint-delivery-3-cli-requirements.md`.
- **Institutional learnings (`docs/solutions/`)**:
  - `best-practices/apply-institutional-learnings-postdating-plan-during-ce-review-2026-05-09.md`
  - `best-practices/normalize-at-input-boundary-2026-05-07.md`
  - `best-practices/frozen-dataclass-mutable-fields-need-post-init-snapshot-2026-05-02.md`
  - `security-issues/keyboardinterrupt-baseexception-bypass-rule-pack-load-2026-05-07.md`
  - `security-issues/module-name-newline-injection-stderr-forge-2026-05-07.md`
  - `security-issues/formatter-systemexit-exit-code-bypass-2026-04-19.md`
  - `best-practices/cross-format-enum-string-parity-2026-05-08.md`
  - `best-practices/audit-wire-format-before-claiming-sibling-parity-2026-05-03.md`
  - `best-practices/pytest-static-analysis-gate-ratchet-2026-05-02.md`
  - `test-failures/pytestmark-does-not-guard-module-top-imports-2026-05-02.md`
  - `test-failures/mock-patch-c-extension-method-descriptor-2026-05-06.md`
- **Per-delivery workflow** (memory): `~/.claude/projects/-Users-marc-projects-python-message-differencer/memory/protokit_lint_delivery_workflow.md`.
- **Project state** (memory): `~/.claude/projects/-Users-marc-projects-python-message-differencer/memory/project_state.md`.
- **TODOS.md** D5 entry: lines 95-113 of `TODOS.md`.
- **CI matrix verification**: `.github/workflows/ci.yml:39-45` (linux+py3.10/3.12 × has_protoxy true/false).
