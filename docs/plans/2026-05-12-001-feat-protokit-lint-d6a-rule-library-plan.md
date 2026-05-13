---
title: "feat: protokit-lint Delivery 6a — buf BASIC parity rule library"
type: feat
status: active
date: 2026-05-12
origin: docs/brainstorms/2026-05-12-protokit-lint-delivery-6a-rule-library-requirements.md
---

# feat: protokit-lint Delivery 6a — buf BASIC parity rule library

## Overview

Ship the first concrete rule library for `protokit lint` — buf BASIC parity (17 rules total: 16 net new + the existing canary `naming/snake-case-fields`) shipping in the `recommended` profile, with `default` initially equivalent to `recommended` (placeholder for D6b differentiators). For single-language Python proto teams. This delivery turns the D1–D5 substrate from a polished demo into a credible buf BASIC competitor for single-language teams. (Note: buf BASIC nominally contains 18 rules; PACKAGE_SAME_DIRECTORY is a cross-file rule deferred to D6b alongside the rest of the cross-language `PACKAGE_SAME_*` family — see Scope Boundaries.)

D6a is the first of two sibling deliveries:
- **D6a (this plan)** — buf BASIC parity for single-language teams + 3 D5-deferred config knobs (R9a per-rule severity overrides, R9c `--no-builtin-rules`, R9d `schema_version` wire field) + parity-test infrastructure (advisory) + version bump 0.1.0 → 0.2.0 (protokit is pre-1.0; no stability promise is made or owed).
- **D6b (separate follow-on)** — full buf DEFAULT parity, cross-language `PACKAGE_SAME_*` family (multi-language migration gate), **option-aware differentiator seed (R6) + structural prerequisites (R6a SourceCodeInfo enablement + R6b `CompileResult.source_locations` index + `leading_comment(path)` helper + `_safe_for_findings()` sanitizer — deferred here from D6a so D6a stays a pure-parity story**, R9b per-rule disable/enable, `strict` profile, expanded option-aware pack.

The split was decided in the origin brainstorm after 2 ce:review passes (see origin: `docs/brainstorms/2026-05-12-protokit-lint-delivery-6a-rule-library-requirements.md`). The further deferral of R6/R6a/R6b from D6a → D6b was decided at plan-review time (J1): R6a+R6b are structural work that exist only to enable R6 in this delivery; deferring them removes the largest architectural change (Unit 1) and shrinks D6a from 10 units to 8, making the parity story the headline rather than competing with structural prerequisites.

## Problem Frame

After D5 (commit `9d6d7f5` on 2026-05-12), `protokit lint` has a polished ergonomic substrate but only **one rule** fires — the D2 canary `naming/snake-case-fields`. The lint thesis is "engine without rules isn't useful"; D6 is where that thesis becomes a product. The brainstorm reframes the adoption story honestly as a **forward bet**: no team today runs both `buf lint` and `protokit-lint` for overlapping jobs (compat is breaking-change checking, not lint), but BASIC parity is the precondition for that future migration to be possible. D6a invests in (a) making the migration possible and (b) closing 3 D5-deferred config knobs that only become meaningful at 20-rule scale. The option-aware differentiator path (R6 + prerequisites) is deferred to D6b — D6a focuses on getting parity right first.

## Requirements Trace

All requirements are carried forward from the origin brainstorm. Stable IDs preserved.

### Auto-load surface expansion (KD-9 reconcile)
- **R0** — Amend KD-9 docstring to reflect protokit's pre-1.0 status (no stability guarantee; packs may be added freely with a CHANGELOG entry); bump version 0.1.0 → 0.2.0; CHANGELOG entry enumerating new auto-loaded packs + the opt-out path (no ceremonial `BREAKING:` marker — pre-1.0, the version bump itself communicates change).

### Rule library — buf BASIC parity
- **R1** — Ship 5 buf-BASIC rule families (naming, enum semantics, imports, package conventions, file conventions) into the `recommended` profile. RPC naming conventions fold into the `naming` family. Cross-language `PACKAGE_SAME_*` family deferred to D6b.
- **R2** — Each shipped rule documents its `buf:<RULE_ID>` equivalent in its `LintRuleSpec.source_spec` field.
- **R3** — Profile rule counts after D6a: `recommended` contains 17 rules (16 net new buf-BASIC parity rules + the existing canary `naming/snake-case-fields`); `default` is structurally equivalent to `recommended` in D6a — the R6 differentiator that distinguishes `default` from `recommended` is **deferred to D6b** (J1). `default` exists as a distinct profile name in D6a so consumers can target it knowing future differentiators will land there. The 18th buf BASIC rule (PACKAGE_SAME_DIRECTORY) is deferred to D6b per R1. Inventory pinned to the buf version selected for R10.
- **R4** — Existing `naming/snake-case-fields` canary continues firing under its current rule_id; profile membership widens from `("default",)` to `("recommended", "default")`. No rename.

### Option-aware differentiator seed — DEFERRED TO D6b (J1)
- ~~**R6**~~ — `options/deprecated-must-have-replacement-comment` — **deferred to D6b**. D6a focuses on pure parity.
- ~~**R6a**~~ — `SourceCodeInfo` preservation in compile backends — **deferred to D6b** (only consumer is R6).
- ~~**R6b**~~ — `CompileResult.source_locations` + `leading_comment(path)` helper — **deferred to D6b** (only consumer is R6).

### Profile vocabulary
- **R7** — Primary protokit-native profile names: `essentials` / `recommended` / `default`. Buf aliases `minimal` → `essentials`, `basic` → `recommended` resolved at config-load time in `_config.py`. `default` is included for forward-compatibility with D6b differentiators even though it's structurally equal to `recommended` in D6a.

### Config knobs (D5 deferred)
- **R9a** — Per-rule severity overrides (`[tool.protokit.lint.severities]`). User overrides always win via post-compose `dataclasses.replace` patch.
- **R9c** — `--no-builtin-rules` CLI flag + pyproject equivalent. Load-bearing as the opt-out for R0's auto-load expansion.
- **R9d** — `schema_version` field in `lint_json` root and SARIF `runs[].properties.lint_schema_version`. Initial value `"0.2"`.

### Parity test infrastructure
- **R10** — `tests/parity/` directory + `@pytest.mark.parity` marker.
- **R11** — Dedicated CI parity job installing pinned buf binary; runs `pytest tests/parity/`. **Job is advisory (non-blocking), NOT a required PR check (J2).** Parity divergence surfaces as a failed-but-non-blocking job; maintainers decide whether to address it in the current PR or in a follow-up.
- **R13** — Buf version pin policy: pin to a specific buf version + `--version` surfacing + a separate scheduled "buf release watcher" CI job that opens an issue when a newer buf release exists upstream. Pin bumps become discrete tasks (a "buf version upgrade" PR), not pressure on the current PR's reviewers. Intentional-divergence documentation lives in each rule's docstring.

### Carry-over hardening
- **R14** — Recalibrate `_LINT_HUMAN_SUMMARIZATION_THRESHOLD` against the new 17-rule corpus (the `recommended` profile after D6a).

## Scope Boundaries

**In scope (D6a):**
- 5 rule families (naming including RPC, enum, imports, package, file) in `recommended` / `default`.
- 3 protokit-native profile names + buf-alias mapping (`default` is forward-placeholder; structurally equals `recommended` in D6a).
- 3 config knobs (R9a, R9c, R9d).
- Parity test infrastructure (R10–R11, advisory) + version-pin watcher + drift policy (R13).
- Version bump 0.1.0 → 0.2.0 + CHANGELOG entry describing the auto-load expansion and demotion paths (pre-1.0; no formal BREAKING ceremony).
- Cross-rule emit ordering pinned (sort `findings` by `(file, location, rule_id)` in `LintEngine.run` final pass).
- `_LINT_HUMAN_SUMMARIZATION_THRESHOLD` recalibration.

### Deferred to Separate Tasks
- **D6b** — **Option-aware differentiator path: R6 (`options/deprecated-must-have-replacement-comment`) + R6a (SourceCodeInfo enablement on both compile backends) + R6b (`CompileResult.source_locations` index + `leading_comment(path)` helper on `_LintContextEmitMixin` + `source_locations` field on all 8 LintContext dataclasses) + `_safe_for_findings()` sanitizer helper** (deferred from D6a — J1); full buf DEFAULT parity; cross-language `PACKAGE_SAME_*` family; `package/same-directory` (same engine extension as the cross-language family — implements a cross-file FILE-level rule kind); R9b per-rule disable/enable; `strict` profile; expanded option-aware pack.
- **D7** — Plugin loading from pyproject (`rule_packs = [...]`), `--compat-rule-pack` rename, plugin-API doc.
- **Phase 3** — Inline `# protokit:ignore` comment suppression.

## Context & Research

### Relevant Code and Patterns

- **Rule pack template**: `src/protokit/schema/lint/rules/naming.py` (D2 canary) — the canonical `@lint_rule` decoration + module-level `RULES: tuple[Callable[..., None], ...]`.
- **`@lint_rule` decorator**: `src/protokit/schema/lint/decorator.py` (signature with kwargs only; attaches `LintRuleSpec` to `fn._lint_spec`).
- **`BUILTIN_PACKS` registration**: `src/protokit/schema/lint/rules/__init__.py:66` — currently `(naming,)`. KD-9 docstring at lines 17–54.
- **`test_builtin_packs.py:79`** — pins exact BUILTIN_PACKS tuple. Must update with every pack addition.
- **`LintRuleSpec`**: `src/protokit/schema/lint/model.py:757–856` — frozen dataclass; `severity_for(violation_kind)` resolves multi-kind rules at lines 832–856.
- **`LintProfile.compose()`**: `model.py:628–693` — most-strict-wins on `rule_severity_overrides`. R9a's user-wins semantics overlay this AFTER compose returns (NOT through compose itself).
- **`LintFinding`**: `model.py:298–341` — frozen, `params: dict[str, Any]` with `__post_init__` snapshot. No `message` field (rendered at output time from `LintRuleSpec.message_template`).
- **Compile backends**: `src/protokit/_cli_utils.py:197–250` (`_compile_with_protoxy`) and `:253–326` (`_compile_with_protoc`). Line 235 currently passes `include_source_info=False`; line 283 protoc command omits `--include_source_info`.
- **`CompileResult`**: `src/protokit/schema/compile.py:145–188` — frozen dataclass; `pool`, `root_files`, `diagnostics`. (R6b's `source_locations` extension deferred to D6b per J1; D6a uses the existing shape unchanged.)
- **`_ALLOWED_KEYS`**: `src/protokit/schema/lint/_config.py:440–442` — frozenset of 5 keys. R9 expansion adds 2 more (`severities`, `no_builtin_rules` — `schema_version` is wire-format output only).
- **`ResolvedLintConfig.from_dict`**: `_config.py:821–975` — precedence engine (CLI replaces pyproject for scalars; appends for `exclude`). Pattern to follow for R9a/R9c.
- **`_coerce_*` helpers**: `_config.py:471–820` — pattern for new `_coerce_severities` and `_coerce_no_builtin_rules`.
- **CLI compose+inject**: `src/protokit/schema/lint/cli.py:755–764` — `dataclasses.replace(composed_profile, min_severity=resolved.min_severity)` after `LintProfile.compose`. R9a's `rule_severity_overrides` injection slots in here.
- **Click `ParameterSource` detection**: `cli.py:529–538` — `ctx.get_parameter_source(name) in explicit_sources` where `explicit_sources = (COMMANDLINE, ENVIRONMENT, DEFAULT_MAP)`. R9c flag uses this pattern.
- **`_emit_human_runtime_warnings`**: `cli.py` D5 U5 — post-format hook. R9c may emit a one-time "you opted out of builtins" advisory through analogous machinery.
- **Formatters**: `src/protokit/formatters/_builtin_lint.py:227` (`lint_json` top-level keys) and `:310+` (`lint_junit`). R9d adds `schema_version` to `lint_json` root and `lint_sarif` `runs[].properties`.
- **Static-analysis ratchet**: `tests/test_static_analysis.py:31–52` — `_LINT_PATHS` and `_TYPE_CHECK_PATHS`. Existing entry `"src/protokit/schema/lint"` auto-covers new rule modules; existing entry `"tests/schema/lint"` auto-covers new rule tests. **NEW directory `tests/parity/` requires an explicit entry.**
- **Cold-import contract**: `tests/schema/lint/test_cold_import_extended.py` — substring match `'protokit.schema.lint' in k` auto-covers new rule modules.
- **CI workflow**: `.github/workflows/ci.yml:43–45` — current matrix is `python: ["3.10", "3.12"] × has_protoxy: [true, false]` on `ubuntu-latest`. R11 parity job is a SEPARATE top-level job (not a new matrix axis) installing buf via `curl` from GitHub releases (mirroring the protoc apt install at lines 57–59).
- **Canonical rule test pattern**: `tests/schema/lint/test_canary_naming.py` — module-level `.proto` source string fixtures + `_compile(tmp_path, sources)` helper + class-based test organization (`TestPackShape`, `TestHappyPath`, `TestSadPath`, `TestFromPack`). New rule tests follow this exact shape.
- **`ProtoBuilder` caveat**: `tests/proto_builder.py` discards `source_code_info` (uses `pool.Add(FileDescriptorProto)`). (Carries forward to D6b when R6 tests require `compile_protos_to_result` via real `.proto` source files on disk. D6a's rule tests do not depend on `source_code_info`.)

### Institutional Learnings

Applied throughout the plan; concrete unit references in the implementation units themselves:

- `module-name-newline-injection-stderr-forge-2026-05-07` — Extended principle: every `{...}` slot in every f-string routing to stderr or wire format must pass through a sanitizer. (Carries forward to D6b when R6's `_safe_for_findings()` helper lands; D6a adds no new user-controlled wire-format params.)
- `keyboardinterrupt-baseexception-bypass-rule-pack-load-2026-05-07` — Triple-arm guard (`SystemExit` + `KeyboardInterrupt` + `Exception`) at any new `importlib` or subprocess call site.
- `formatter-systemexit-exit-code-bypass-2026-04-19` — Sandbox every rule invocation in the existing engine guard. New rules inherit this architecturally.
- `frozen-dataclass-mutable-fields-need-post-init-snapshot-2026-05-02` — (Carries forward to D6b when `CompileResult.source_locations` Mapping field lands; D6a adds no new mutable frozen-dataclass fields.)
- `frozen-dataclass-paired-field-invariant-post-init-2026-05-11` — (Carries forward to D6b alongside `source_locations`.)
- `public-surface-draft-discipline-source-audit-2026-05-12` — Add Public Surface DRAFT rows for new profile names, buf-alias mapping, `schema_version` wire field. Grep-verify each row against source before shipping. (`source_locations` and `_safe_for_findings()` rows deferred to D6b along with R6/R6a/R6b.)
- `stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12` — Sweep stale forward-looking text in the final unit. Canonical grep (expanded for D6a): `grep -rn "until D[0-9]\|will land\|arrives in U\|forthcoming\|once U[0-9] ships\|in D6a\|D6a will\|TODO(D6a)\|D6b will\|once D6a ships\|after D6a\|deferred to D6a" src/ tests/ docs/ README.md CHANGELOG.md`. The `tests/` and `README.md` additions catch stale references in test docstrings and the linting README section that the original grep missed; the `D6a`-specific patterns catch deferral-shaped text written before this delivery existed.
- `fail-closed-ci-matrix-coverage-meta-test-2026-05-12` — Parity job IS a new CI job. If the parity test uses `@pytest.mark.skipif` with OS/Python predicate, ship a companion coverage meta-test.
- `click-parameter-source-detection-cli-config-precedence-2026-05-11` — R9c `--no-builtin-rules` flag needs `DEFAULT_MAP` in `explicit_sources` if it has a meaningful non-None default.
- `source-aware-error-messages-multi-source-resolved-value-2026-05-11` — R9a/R9c emit error messages naming the source (CLI / pyproject) per the established D5 pattern.
- `pytest-static-analysis-gate-ratchet-2026-05-02` — `tests/parity/` (new root-level test dir) needs explicit `_LINT_PATHS` entry in the same commit.
- `cross-format-enum-string-parity-2026-05-08` — New `rule_id` strings emit consistently across all 4 formatters; no `.value`/`.name` divergence since rule_ids are strings, not enums.
- `parametrized-matrix-tests-inherit-schema-validators-2026-05-12` — New parametrized test classes (if any) list `junit_validator` / `sarif_validator` fixtures in every method signature.
- `deprecationwarning-poisons-except-exception-strict-warning-ci-2026-05-11` — (Carries forward to D6b when R6's comment-text regex lands; D6a adds no new `re.compile(...)` call sites in user-facing rules.)
- `circular-import-type-checking-cycle-break-2026-05-11` — New rule modules importing `LintEngine` / `ResolvedLintConfig` only for annotations gate under `TYPE_CHECKING`. Never lazy-import inside `except` arms.
- `shared-error-helper-source-label-caller-attribution-2026-05-11` — Shared error helpers reachable from multiple source paths accept `source_label` parameter.
- `normalize-at-input-boundary-2026-05-07` — Profile alias resolution applies `.strip().lower()` then alias-lookup at the `_coerce_profile` input boundary.
- `audit-wire-format-before-claiming-sibling-parity-2026-05-03` — Audit buf parity claims at wire-format level: element types, severity mappings, profile name conventions.
- `smoke-not-benchmark-loose-threshold-calibration-2026-05-12` — Reference only; D6a parity tests are pass/fail, not threshold-based.
- `apply-institutional-learnings-postdating-plan-during-ce-review-2026-05-09` — ce:review at each unit's boundary will surface any new learnings; 3-way convergence is the must-fix threshold.

### External References

External research skipped — local patterns are strong (D1-D5 substrate); buf-specific knowledge captured in origin brainstorm; the 14 deferred-to-planning items provide explicit decision agenda. /ce:plan resolves them inline rather than re-researching.

## Key Technical Decisions

### KTD-1: Profile alias resolution at `_coerce_profile` boundary

`_PROFILE_ALIASES: dict[str, str] = {"minimal": "essentials", "basic": "recommended"}` declared in `_config.py`. `_coerce_profile()` applies `.strip().lower()` then `_PROFILE_ALIASES.get(name, name)` — alias resolution happens at the boundary that handles both pyproject AND CLI input paths (since both flow through `from_dict`'s coercion step). No alias resolution elsewhere; downstream code sees only primary names. Per `normalize-at-input-boundary` learning.

### KTD-2: R9a user-wins via post-compose dict overlay (NOT through compose)

`LintProfile.compose()` implements most-strict-wins on `rule_severity_overrides`. R9a needs the opposite: user pyproject `severities` should always win, even when contributing profiles declare a higher severity. The user-wins semantics layer on top of compose via:

```
composed = LintProfile.compose(*profiles_from_packs)
final = dataclasses.replace(
    composed,
    rule_severity_overrides={
        **composed.rule_severity_overrides,
        **user_severities,  # user keys win
    },
)
```

This applies AFTER compose, in `cli.py` around line 755 (where the existing `min_severity` injection happens). Per F9 resolution in the origin brainstorm.

### KTD-3: `CompileResult.source_locations` — DEFERRED TO D6b (J1)

`CompileResult.source_locations` field + `_LintContextEmitMixin.leading_comment(path)` helper + `source_locations` field on all 8 LintContext dataclasses are **deferred to D6b** along with R6/R6a/R6b. The original analysis (Mapping built before `pool.Add()` to preserve `source_code_info`; `MappingProxyType` read-only with `__post_init__` snapshot; None when `include_source_info=False`; helper walks `source_code_info.location[]` for the current descriptor's path) carries forward verbatim to D6b's plan when R6 is the active driver. No `CompileResult` shape changes in D6a.

### KTD-4: R0 lands as the final commit; version bump 0.1.0 → 0.2.0

R0 ships as the FINAL unit of D6a, after all rule packs are written and `BUILTIN_PACKS` is being expanded — the CHANGELOG entry's "BUILTIN_PACKS gains 4 new pack modules" claim must be true when it lands. Earlier units update `test_builtin_packs.py` to match each incremental pack addition; the version bump itself happens once at the end. Per pre-1.0 stability disclaimer (D5 U6).

### KTD-5: `_safe_for_findings()` sanitizer — DEFERRED TO D6b (J1)

The `_safe_for_findings()` helper is **deferred to D6b** because its immediate consumer was R6 comment-derived params. No new wire-format sanitization surface lands in D6a; existing `LintFinding.params` consumers continue using established patterns. The threat-model analysis (json.dumps escapes U+2028 and U+2029; xml.etree does not; defense-in-depth across JUnit + human + future formatters; alias-to-`_safe_for_stderr` to share `_CONTROL_CHAR_TABLE`) carries forward verbatim to D6b plan when R6 is the active driver.

### KTD-6: Cross-rule emit ordering pinned

D6a sorts `LintReport.findings` by the key `(finding.location.file, str(finding.location), finding.rule_id)` AFTER `engine.run` completes. The sort uses `str(location)` (every `LintLocation` variant implements `__str__`) — NOT a `proto_path_str()` method (no such method exists, and the 8 frozen `LintLocation` dataclasses don't declare `order=True`, so `__lt__` isn't generated; sorting raw location objects would raise `TypeError`). The sort lives as a final pass at the end of `LintEngine.run` (right before returning the `LintReport`), NOT in `LintReport.__post_init__` — keeping `__post_init__` to its existing tuple-snapshot responsibility and allowing test code that constructs `LintReport` with deliberately-ordered findings (e.g., for formatter ordering tests) to bypass the engine-level sort. Per origin brainstorm cross-rule-ordering resolution. Note: this changes the find-order of `tests/test_builtin_lint_formatter.py:219-227` (the two-finding ordering test); that test's expected order needs to be updated to match the new sort key in the same commit as the sort implementation.

### KTD-7: Buf binary pin in `.github/workflows/ci.yml` via curl from GitHub releases (advisory job + release watcher)

Direct binary download (matches existing protoc apt install pattern at line 57–59). New top-level job named `parity` (not a new matrix axis) — runs only on `ubuntu-latest` + `python: "3.12"`. Downloads `buf-Linux-x86_64` from `https://github.com/bufbuild/buf/releases/download/v{PIN}/`, chmod +x, then `pytest tests/parity/ -m parity`. **The job is advisory (J2)**: it runs on every PR and surfaces parity divergence as a job failure, but does NOT block merges. No branch-protection configuration is required. The pin version is selected at unit-implementation time from a recent stable buf release; pin policy per R13. `bufbuild/setup-buf` GitHub Action also feasible but adds a third-party action dependency — direct curl preferred for transparency.

**Release-watcher companion job:** a separate scheduled GitHub Actions workflow (e.g., `.github/workflows/buf-release-watch.yml`) runs weekly via `cron:` schedule, queries `bufbuild/buf` releases via `gh release list -R bufbuild/buf --limit 5`, compares the latest stable release tag against the pinned `_BUF_PARITY_PIN` constant in `src/protokit/schema/lint/cli.py`, and opens a tracking issue when behind (deduped by issue title to avoid spam). This decouples buf release cadence from PR throughput: pin bumps become discrete tasks ("buf parity pin upgrade") owned by a maintainer, not pressure on the current PR's reviewers. The watcher itself is implementation-light (~30 lines of YAML + bash) and ships in Unit 8 alongside the parity job.

### KTD-8: Per-family pack modules in `src/protokit/schema/lint/rules/`

Pack organization mirrors buf's family conceptual groupings: extend `naming.py` (all case-style rules including PackageLowerSnakeCase per buf's classification + RPC naming + service naming), create `enum.py` (semantic enum rules: no-allow-alias, first-value-zero), `imports.py` (no-public, no-weak, unused), `package.py` (structural: defined, directory-match), `file.py` (structural: syntax-specified). Each is a `BUILTIN_PACKS` entry. KD-9 amendment in R0 unlocks expansion. (The `options.py` pack for R6 is **deferred to D6b** along with R6 itself per J1.)

### KTD-9: Severity posture — match buf BASIC (ERROR by default)

New D6a rules default to `LintSeverity.ERROR` to match buf's BASIC posture — the parity story is the headline, and shipping at WARNING would be parity in rule-name only, not in semantics. Protokit is pre-1.0; there is no stability guarantee, so no soft-rollout ceremony is owed to existing users. Users who want softer behavior have two paths already wired in by D5/D6a: `--min-severity=warning` (global demotion, surfaces as a `min_severity_relaxed` runtime warning per D5 U3) and `[tool.protokit.lint.severities]` (per-rule demotion, R9a). The existing canary `naming/snake-case-fields` retains its existing severity (no change).

## Open Questions

### Resolved During Planning

- **Rule inventory** → Pin buf v1.50.x (or latest stable at unit implementation time). BASIC rules in D6a scope: SYNTAX_SPECIFIED, PACKAGE_DEFINED, PACKAGE_DIRECTORY_MATCH, FIELD_LOWER_SNAKE_CASE (existing canary), FILE_LOWER_SNAKE_CASE, PACKAGE_LOWER_SNAKE_CASE, MESSAGE_PASCAL_CASE, ENUM_PASCAL_CASE, ENUM_VALUE_UPPER_SNAKE_CASE, ENUM_FIRST_VALUE_ZERO, ENUM_NO_ALLOW_ALIAS, ONEOF_LOWER_SNAKE_CASE, SERVICE_PASCAL_CASE, RPC_PASCAL_CASE, IMPORT_NO_PUBLIC, IMPORT_NO_WEAK, IMPORT_USED. **17 rules total; 16 net new + 1 existing canary (FIELD_LOWER_SNAKE_CASE).** Note: `package/same-directory` (buf:PACKAGE_SAME_DIRECTORY) is the 18th buf BASIC rule but is a cross-file rule requiring engine support not yet present; it is **deferred to D6b** alongside the rest of the cross-language `PACKAGE_SAME_*` family. Final inventory verified against the pinned buf version at the start of Unit 3 (the first new-rules unit): before extending `naming.py`, the implementer runs `buf lint --config '{version: v2, lint: {use: [BASIC]}}' <fixture>` against a synthetic .proto file to enumerate exactly which rules buf fires; that enumeration is the contract for D6a's rule_id list. If the pin's enumeration differs from the list above, the discrepancy is resolved before Unit 3 proceeds. **Scope cap:** if the pinned buf version's BASIC category contains rules NOT in this list, they are deferred to D6b — D6a does not grow scope mid-implementation.
- **Pack organization** → 5 modules per KTD-8 (`naming`/`enum`/`imports`/`package`/`file`; `options` deferred to D6b per J1).
- **Alias-resolution mechanism** → `_PROFILE_ALIASES` constant + `_coerce_profile` resolution per KTD-1.
- **R0 commit ordering** → Final unit per KTD-4.
- **Cross-rule emit ordering** → Sort `findings` by `(file, str(location), rule_id)` in `LintEngine.run` final pass (NOT in `__post_init__`) per KTD-6.
- **R6 sanitization helper location** → Deferred to D6b along with R6 (J1); KTD-5 carries forward.
- **R9a most-strict-wins conflict** → User-wins via post-compose patch per KTD-2.
- **Buf binary pin strategy** → Direct curl from GitHub releases per KTD-7.
- **Severity posture** → New rules default to `error` (buf BASIC parity) per KTD-9. No soft-rollout — pre-1.0, no stability guarantees.
- **Primary signal framing** → Parity story is the headline. R6 differentiator deferred to D6b (J1) so D6a is pure parity. Reflected in README + CHANGELOG drafting (Unit 10).
- **`schema_version` initial value** → `"0.2"` matches protokit semver after R0 bump.
- **Parity CI failure-blocking posture** → **Advisory (non-blocking) per J2.** Companion release-watcher job decouples buf release cadence from PR throughput; pin bumps become discrete maintainer tasks.
- **R6 / R6a / R6b deferral** → Deferred to D6b per J1. D6a ships pure buf BASIC parity without the option-aware path; structural prerequisites land in D6b alongside the rule they enable.

### Deferred to Implementation

- **`_LINT_HUMAN_SUMMARIZATION_THRESHOLD` recalibration** — During Unit 10, run protokit lint against a representative corpus (googleapis snippets + protokit's own protos) with the new 17-rule set. If per-category warning counts cluster < 5 routinely, keep at 5; if they cluster 8-10, bump.
- **Exact buf version pin** — Selected at Unit 8 implementation time. Bias toward latest stable buf as of that day. (Release-watcher job will surface newer releases as discrete bump tasks after D6a ships.)
- **R9c pyproject key name** — `no_builtin_rules = true` vs `builtin_rules = false` decided in Unit 2. Lean toward `no_builtin_rules` (matches CLI flag name).
- **Lint subcommand `--version` override mechanism** — Click's group-level `@version_option` doesn't naturally compose with subcommand-level overrides; Unit 9 picks between adding a lint-specific `--version` flag with custom callback OR augmenting the top-level callback with lint-aware metadata.

## Output Structure

```
src/protokit/schema/lint/rules/
├── __init__.py            # MODIFY: BUILTIN_PACKS expansion + KD-9 docstring amend
├── naming.py              # MODIFY: extend with PascalCase + UPPER_SNAKE + file/package case + RPC/service naming
├── enum.py                # NEW: ENUM_NO_ALLOW_ALIAS, ENUM_FIRST_VALUE_ZERO
├── imports.py             # NEW: IMPORT_NO_PUBLIC, IMPORT_NO_WEAK, IMPORT_USED
├── package.py             # NEW: PACKAGE_DEFINED, PACKAGE_DIRECTORY_MATCH (PACKAGE_SAME_DIRECTORY deferred to D6b)
└── file.py                # NEW: SYNTAX_SPECIFIED
# options.py — DEFERRED TO D6b (J1)

src/protokit/schema/lint/
├── _config.py             # MODIFY: _ALLOWED_KEYS expansion + _PROFILE_ALIASES + _coerce_severities + _coerce_no_builtin_rules
├── cli.py                 # MODIFY: R9a post-compose patch + R9c flag + --version hook + _BUF_PARITY_PIN constant
├── engine.py              # MODIFY: final-pass sort of findings (KTD-6)
└── model.py               # (unchanged for D6a; CompileResult source_locations deferred to D6b)
# _cli_utils.py _safe_for_findings() — DEFERRED TO D6b (J1)

# src/protokit/_cli_utils.py — UNCHANGED in D6a (include_source_info enablement deferred to D6b)
# src/protokit/schema/compile.py — UNCHANGED in D6a (CompileResult.source_locations deferred to D6b)
src/protokit/formatters/_builtin_lint.py # MODIFY: lint_json + lint_sarif emit schema_version

tests/schema/lint/rules/      # NEW directory
├── test_naming_extended.py   # NEW: tests for D6a naming family additions (incl. RPC/service)
├── test_enum.py              # NEW
├── test_imports.py           # NEW
├── test_package.py           # NEW
└── test_file.py              # NEW
# test_options.py — DEFERRED TO D6b (J1)

tests/parity/                 # NEW directory + new _LINT_PATHS entry
├── conftest.py               # NEW: buf binary discovery + invocation helper
├── test_parity_naming.py     # NEW
├── test_parity_enum.py       # NEW
├── test_parity_imports.py    # NEW
├── test_parity_package.py    # NEW
├── test_parity_file.py       # NEW
└── fixtures/                 # NEW: per-rule .proto fixtures
    ├── naming/
    ├── enum/
    ├── imports/
    ├── package/
    └── file/

tests/schema/lint/
├── test_builtin_packs.py     # MODIFY: pinned BUILTIN_PACKS tuple grows with each unit
└── (existing tests)
# test_compile.py source_locations assertion — DEFERRED TO D6b

.github/workflows/ci.yml      # MODIFY: new advisory "parity" job + buf binary install step (SHA-256 verified)
.github/workflows/buf-release-watch.yml # NEW: weekly scheduled release-watcher (J2)
pyproject.toml                # MODIFY: version 0.1.0 → 0.2.0 + parity marker
CHANGELOG.md                  # MODIFY: ### D6a section under Unreleased
README.md                     # MODIFY: Schema Linting section additions + Public Surface DRAFT rows
tests/test_static_analysis.py # MODIFY: add "tests/parity" directory entry to _LINT_PATHS
```

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

### Unit dependency graph

```
Unit 2 (R9 config schema + KTD-1 aliases)
                  │
                  ▼
            Unit 3 (naming extension)
                  │
                  ▼
            Unit 4 (enum pack)
                  │
                  ▼
            Unit 5 (imports pack)
                  │
                  ▼
            Unit 6 (package + file packs)
                  │
                  ▼
            Unit 8 (parity infra — advisory job + release watcher — needs all rule packs registered)
                  │
                  ▼
            Unit 9 (CLI wiring: R9a post-compose + R9c flag + R9d schema_version + --version hook)
                  │
                  ▼
            Unit 10 (R0 version bump + KD-9 amend + CHANGELOG + README + Public Surface + sweep)

(Unit 1 — R6a + R6b structural prerequisites — DEFERRED TO D6b per J1.)
(Unit 7 — R6 options pack — DEFERRED TO D6b per J1.)
```

D6a runs as a single sequential chain: **Unit 2 → 3 → 4 → 5 → 6 → 8 → 9 → 10** (8 units total). Units 3-6 must run sequentially because each modifies `BUILTIN_PACKS` in `rules/__init__.py` AND the pinned tuple in `test_builtin_packs.py:79`; two parallel branches both modifying the same line produce a merge conflict. Unit 8 depends on all rule packs being registered. Units 9 and 10 close the delivery. (With Unit 1 deferred, Unit 2 no longer has a parallel sibling at the start — the chain is fully sequential.)

### Upgrade trajectory (pre-1.0 — no stability guarantee)

```
0.1.x users with `protokit~=0.1.0` pin   ──>   stay on D5
                                                  (no auto-load expansion)

0.1.x users with `protokit>=0.1.0`       ──>   pip install -U bumps to 0.2.0
unpinned / generous-bound                       ──> see ~16 new ERROR findings (buf parity)
                                                ──> CHANGELOG describes what changed
                                                ──> option: --no-builtin-rules
                                                ──> option: pin to ~=0.1.0
                                                ──> option: triage findings + demote per rule via [tool.protokit.lint.severities]
                                                ──> option: --min-severity=warning (global demotion)

0.2.0 new users                          ──>   See 17-rule library at buf-parity severity
                                                ──> All errors by default (KTD-9; matches buf BASIC)
                                                ──> --min-severity / per-rule overrides available
```

### `CompileResult.source_locations` integration — DEFERRED TO D6b (J1)

The full integration diagram (compile-backend SourceCodeInfo enablement → FDS preservation → pre-Add snapshot → CompileResult field → LintEngine handoff → `leading_comment(path)` helper → R6 rule consumption → `_safe_for_findings()` sanitization on params) is **deferred to D6b's plan** along with R6/R6a/R6b. D6a does not modify the compile pipeline or `CompileResult` shape; the engine runs on the existing D5 compile output unchanged.

## Implementation Units

- [~] **Unit 1: R6a + R6b — DEFERRED TO D6b (J1)**

**Status:** This unit is **deferred to D6b** along with R6, R6a, and R6b. D6a no longer modifies compile backends, `CompileResult` shape, or `LintContext` dataclasses. The full unit description below is preserved as a record of the analysis that carries forward to D6b's plan; do not implement it as part of D6a.

**Original goal (for D6b reference):** Land the structural prerequisite for any comment-aware rule. Both compile backends preserve `source_code_info`; `CompileResult` carries a source-location index built before `pool.Add()` consumes it; lint context exposes `leading_comment(path)`. Measure and document descriptor-size impact.

**Requirements:** R6a, R6b.

**Dependencies:** None (foundational).

**Files:**
- Modify: `src/protokit/_cli_utils.py` (lines 229–250 for protoxy; lines 253–326 for protoc — flip `include_source_info` flag in both; build source_locations index before pool.Add)
- Modify: `src/protokit/schema/compile.py` (add `CompileResult.source_locations` field + `__post_init__` snapshot)
- Modify: `src/protokit/schema/lint/model.py` (add `source_locations: Mapping[str, FileDescriptorProto] | None = None` field to ALL 8 frozen `LintContext` dataclasses — `FileLintContext`, `ServiceLintContext`, `MethodLintContext`, `EnumLintContext`, `EnumValueLintContext`, `MessageLintContext`, `FieldLintContext`, `OneofLintContext`. Add `leading_comment(path: tuple[int, ...]) -> str | None` as a method on `_LintContextEmitMixin` — the mixin can define the method but cannot declare fields, so the data field lives on each concrete dataclass and the method reads `self.source_locations`. Frozen-dataclass invariants apply: `source_locations` is snapshotted via the existing `__post_init__` pattern in each dataclass.)
- Modify: `src/protokit/schema/lint/engine.py` (8 `_build_*_ctx` methods at lines 609-680+ pass `source_locations=compile_result.source_locations` through to each context construction)
- Test: `tests/schema/lint/test_compile.py` (or new `tests/schema/lint/test_source_code_info.py`) — round-trip preservation; source_locations carries comments; None when include_source_info=False
- Test: `tests/schema/lint/test_canary_naming.py` — verify existing canary tests still pass with source_code_info enabled (no regression)
- Test: existing fixture-byte-asserting tests — UPDATE to absorb the descriptor-size delta (grep for tests asserting exact serialized bytes; budget ~1 day for refresh)

**Approach:**
- Protoxy path (`_cli_utils.py:235`): `protoxy.compile(..., include_source_info=True)`. Update inline comment ("neither carries source-location info into the pool") to reflect new behavior.
- Protoc path (`_cli_utils.py:283`): add `"--include_source_info"` to the command args list before `--`.
- Build source_locations: after `protoxy.compile` returns and BEFORE the `for fd in fds.file: pool.Add(fd)` loop, snapshot `{fd.name: fd for fd in fds.file}`. Pass to `CompileResult` constructor.
- Same pattern for protoc path: load the descriptor set from `tmp_path`, snapshot the FDS, then pool.Add the files.
- `CompileResult.source_locations` is `Mapping[str, FileDescriptorProto] | None = None`. `__post_init__` wraps in `MappingProxyType(dict(self.source_locations))` if non-None.
- `leading_comment(path: tuple[int, ...]) -> str | None`: defined as an instance method on `_LintContextEmitMixin` that reads `self.source_locations` (a field on each concrete LintContext dataclass, set by the engine's `_build_*_ctx` methods) and walks `source_code_info.location[]` looking for an entry whose `path` field matches the tuple. Returns `leading_comments` or None. Context callers (rule functions in `options.py`) construct the path-tuple from the descriptor object passed in — the protobuf wire-format convention defines the path encoding (e.g., field=2 for `message_type[]`, then index of message; field=2 for `field[]` within message, then index of field). For D6a, the path-construction helper lives alongside the rule that uses it (Unit 7 `options.py`); future comment-aware rules can extract it into a shared helper if needed. Cross-backend determinism: the path encoding is defined by the protobuf descriptor format itself (not by protoc vs protoxy implementation choices), so a `.proto` source file produces equivalent paths across backends.
- Descriptor-size measurement: in the same commit, run a one-time benchmark comparing serialized FDS bytes pre/post the flag flip on a representative corpus. Document in CHANGELOG.

**Patterns to follow:**
- Frozen-dataclass snapshot: existing `LintReport.__post_init__` pattern.
- Mapping wrapping: `LintReport.specs = MappingProxyType(dict(...))` pattern.

**Test scenarios:**
- *Happy path:* Compile a `.proto` file with comments; `CompileResult.source_locations` carries one FileDescriptorProto with `source_code_info.location[]` non-empty.
- *Happy path:* `field_ctx.leading_comment(path)` returns the comment text for a documented field.
- *Edge case:* `.proto` file with no comments compiles cleanly; `source_locations` still populated; `leading_comment` returns `None` for paths without comments.
- *Edge case:* `CompileResult` constructed with `source_locations=None` (legacy path) — `leading_comment` returns `None` gracefully, never raises.
- *Edge case:* Multi-file compile (5 protos, comments on some) — source_locations carries all 5 entries.
- *Integration:* Round-trip via the existing test_canary_naming.py fixtures — D2 canary continues firing exactly as before; no regression in rule walk semantics.
- *Backend parity:* protoxy and protoc backends both produce equivalent `source_locations` shapes (same keys, same `leading_comments` content) on identical inputs.

**Verification:**
- `pytest tests/schema/lint/test_compile.py` (or new test file) passes; source_locations field exists; leading_comment helper returns expected values.
- `pytest tests/schema/lint/test_canary_naming.py` passes unchanged (no behavior regression).
- Static-analysis ratchet (`tests/test_static_analysis.py`) passes — file paths already covered by directory entries.
- CHANGELOG entry documents the empirical descriptor-size delta.

---

- [ ] **Unit 2: R9 config schema + profile-alias mechanism**

**Goal:** Expand the pyproject configuration substrate to accept the new D6a knobs (`severities`, `no_builtin_rules`) plus the alias-resolution mechanism (`minimal`→`essentials`, `basic`→`recommended`). (The KD-9 docstring amendment moved to Unit 10, where it lands in the same commit as the BUILTIN_PACKS expansion it authorizes.)

**Requirements:** R7 (alias mechanism), R9a (severities), R9c (`--no-builtin-rules` pyproject equivalent).

**Dependencies:** None — foundational config substrate; first unit in the D6a sequential chain.

**Files:**
- Modify: `src/protokit/schema/lint/_config.py` (`_ALLOWED_KEYS` expansion at line 440; add `_PROFILE_ALIASES` constant; add `_coerce_severities`, `_coerce_no_builtin_rules` helpers; extend `ResolvedLintConfig` with `severities: Mapping[str, LintSeverity]` and `no_builtin_rules: bool` fields; update `from_dict` precedence logic)
- Test: `tests/schema/lint/test_config.py` (or wherever ResolvedLintConfig tests live) — new tests for severities/no_builtin_rules parsing + alias resolution
- Test: `tests/schema/lint/_config/test_profile_aliases.py` (NEW) — alias resolution covering pyproject and CLI input paths

**Approach:**
- `_ALLOWED_KEYS` grows from 5 to 7 keys: add `"severities"`, `"no_builtin_rules"`.
- `_PROFILE_ALIASES: dict[str, str] = {"minimal": "essentials", "basic": "recommended"}`. Apply in `_coerce_profile` after `.strip().lower()`: `name = _PROFILE_ALIASES.get(name, name)`.
- `_coerce_severities(value, source)` — validates value is a dict (TOML table); each key is non-empty string (rule_id); each value coerces to `LintSeverity` via existing severity-string coercion. Empty dict `{}` is valid (no overrides). Per `source-aware-error-messages` learning, error messages name the offending rule_id + value + source label.
- `_coerce_no_builtin_rules(value, source)` — validates value is a bool. TOML `true`/`false` only.
- `ResolvedLintConfig` gains:
  - `severities: Mapping[str, LintSeverity] = field(default_factory=dict)`
  - `no_builtin_rules: bool = False`
  - Per `frozen-dataclass-mutable-fields-need-post-init-snapshot`: `__post_init__` wraps `severities` in `MappingProxyType(dict(...))`.
- `from_dict` precedence: CLI overrides pyproject for both new fields (`severities`: CLI `--severity-override` repeatable flag deferred to D7-or-later; D6a is pyproject-only). `no_builtin_rules`: CLI `--no-builtin-rules` flag implemented in Unit 9.
(KD-9 docstring amendment moved to Unit 10's final commit.)

**Patterns to follow:**
- Existing `_coerce_min_severity` for severity-string parsing.
- Existing `_coerce_*` helpers' error-message shape (per `source-aware-error-messages` learning).
- `ResolvedLintConfig` field declaration + `__post_init__` snapshot pattern at lines 631+.

**Test scenarios:**
- *Happy path:* `[tool.protokit.lint] profile = "basic"` resolves to `("recommended",)` via alias.
- *Happy path:* `[tool.protokit.lint.severities]` table with `{"naming/snake-case-fields" = "info"}` populates `resolved.severities` correctly.
- *Happy path:* `no_builtin_rules = true` populates `resolved.no_builtin_rules`.
(KD-9 docstring assertion test moved to Unit 10 alongside the docstring amendment itself.)
- *Edge case:* `profile = "BASIC"` (uppercase) normalizes via `.lower()` then resolves via alias.
- *Edge case:* `profile = "essentials"` (already primary) passes through unchanged.
- *Edge case:* Empty `severities = {}` resolves to empty dict (not error).
- *Edge case:* `--profile basic` (CLI alias) resolves the same as pyproject `profile = "basic"` (alias resolution at coercion-boundary covers both paths).
- *Error path:* `severities = "warning"` (scalar, not table) → exit 2 with `pyproject-config-invalid` naming the key.
- *Error path:* `severities = {"naming/foo" = "WARN"}` (non-canonical severity) → exit 2 naming the offending key + value.
- *Error path:* `no_builtin_rules = "true"` (string, not bool) → exit 2 with type-mismatch error.
- *Error path:* Unknown key `[tool.protokit.lint] disabled_rules = [...]` → exit 2 (R9b deferred to D6b; unknown-key error).

**Verification:**
- All new config tests pass.
- Existing config tests pass unchanged (no regression in D5 substrate).
- Static-analysis ratchet passes — files already covered.

---

- [ ] **Unit 3: Naming family extension — extend `rules/naming.py`**

**Goal:** Add the naming-case rules that match buf's BASIC: PascalCase for messages/enums/services/RPCs; UPPER_SNAKE for enum values; lower_snake for oneofs/files/packages. Existing `snake-case-fields` canary widens its profile to `("recommended", "default")`.

**Requirements:** R1 (naming family), R2 (buf-id docs), R4 (canary profile widening).

**Dependencies:** Unit 2 (profile aliases must exist before rules declare `profiles=("recommended", "default")`). First of the sequential rule-pack chain (Units 3 → 4 → 5 → 6); see dependency-graph note about why parallel rule-pack work produces merge conflicts on `test_builtin_packs.py:79`.

**Files:**
- Modify: `src/protokit/schema/lint/rules/naming.py` (add 8 new rule functions + extend RULES tuple)
- Modify: `src/protokit/schema/lint/rules/__init__.py` (BUILTIN_PACKS unchanged — naming already a member)
- Modify: `tests/schema/lint/test_builtin_packs.py:79` (no tuple change — naming.py already in BUILTIN_PACKS; verify membership assertion still passes)
- Test: `tests/schema/lint/rules/test_naming_extended.py` (NEW directory + file) — per-rule unit tests for each new rule

**Approach:**
- 8 new rules in `naming.py`:
  - `naming/pascal-case-messages` (buf:MESSAGE_PASCAL_CASE) — ElementKind.MESSAGE
  - `naming/pascal-case-enums` (buf:ENUM_PASCAL_CASE) — ElementKind.ENUM
  - `naming/upper-snake-case-enum-values` (buf:ENUM_VALUE_UPPER_SNAKE_CASE) — ElementKind.ENUM_VALUE
  - `naming/snake-case-oneofs` (buf:ONEOF_LOWER_SNAKE_CASE) — ElementKind.ONEOF
  - `naming/pascal-case-services` (buf:SERVICE_PASCAL_CASE) — ElementKind.SERVICE
  - `naming/pascal-case-rpcs` (buf:RPC_PASCAL_CASE) — ElementKind.METHOD
  - `naming/snake-case-files` (buf:FILE_LOWER_SNAKE_CASE) — ElementKind.FILE (filename check)
  - `naming/snake-case-packages` (buf:PACKAGE_LOWER_SNAKE_CASE) — ElementKind.FILE (file.package check; dots split into segments, each checked)
- Each new rule:
  - `profiles=("recommended", "default")` — fires in both profiles
  - `severity=LintSeverity.ERROR` (per KTD-9 buf-parity posture)
  - `source_spec="buf:<RULE_ID>"` (per R2 — naming the buf equivalent at the rule level for auto-discovery)
  - `message_template` follows existing canary's style
- Existing canary `snake-case-fields`: amend `profiles=("default",)` to `profiles=("recommended", "default")`. Severity unchanged (already warning).
- RULES tuple grows to 9 entries: existing canary + 8 new.

**Patterns to follow:**
- `naming.py:46–70` for `@lint_rule` decoration + check function shape.
- `tests/schema/lint/test_canary_naming.py` for test class organization (TestPackShape, TestHappyPath, TestSadPath, TestFromPack).

**Test scenarios:**
- *Happy path:* For each rule, a `.proto` file with the correct shape produces zero findings under `profile = "recommended"`.
- *Happy path:* For each rule, a `.proto` file with the incorrect shape produces exactly the expected findings.
- *Edge case:* `naming/snake-case-files` — file basename only, ignore directory path; `Foo_Bar.proto` fires, `foo_bar.proto` is clean.
- *Edge case:* `naming/snake-case-packages` — multi-segment package like `acme.api.v1.users` — each segment checked; `acme.API.v1.users` fires on `API`.
- *Edge case:* `naming/pascal-case-rpcs` — RPC named `getUser` fires (not PascalCase); `GetUser` is clean.
- *Edge case:* `naming/upper-snake-case-enum-values` — `STATUS_ACTIVE` is clean; `StatusActive` fires; `STATUS_active` fires.
- *Edge case:* Empty / single-character names — `naming/pascal-case-messages` on `message A` is clean (A is PascalCase by convention); empty name path is unreachable in protobuf grammar.
- *Integration:* Profile composition test — `profile = "recommended"` fires all 9 naming rules; `profile = "default"` fires the same 9 (since `default` is structurally equivalent to `recommended` in D6a per R3); `profile = "essentials"` fires zero naming rules.

**Verification:**
- `tests/schema/lint/rules/test_naming_extended.py` passes; each rule has happy + sad path tests.
- Existing `tests/schema/lint/test_canary_naming.py` passes unchanged (canary's wider profile membership doesn't break existing assertions).
- Static-analysis ratchet passes — `src/protokit/schema/lint/rules` and `tests/schema/lint` both directory-covered.

---

- [ ] **Unit 4: Enum semantics pack — new `rules/enum.py`**

**Goal:** Ship the non-naming enum rules (`enum-no-allow-alias`, `enum-first-value-zero`). New pack module registered in BUILTIN_PACKS.

**Requirements:** R1 (enum family), R2.

**Dependencies:** Unit 2 (config schema). Sequential after Unit 3 — merges into the BUILTIN_PACKS pin in `test_builtin_packs.py:79`.

**Files:**
- Create: `src/protokit/schema/lint/rules/enum.py`
- Modify: `src/protokit/schema/lint/rules/__init__.py` (add `from . import enum`; extend BUILTIN_PACKS to `(naming, enum)`)
- Modify: `tests/schema/lint/test_builtin_packs.py:79` (update pinned tuple)
- Test: `tests/schema/lint/rules/test_enum.py` (NEW)

**Approach:**
- 2 rules in `enum.py`:
  - `enum/no-allow-alias` (buf:ENUM_NO_ALLOW_ALIAS) — fires when an enum declares `option allow_alias = true` (and the option is unnecessary because there are no aliased values).
  - `enum/first-value-zero` (buf:ENUM_FIRST_VALUE_ZERO) — fires when an enum's first value is not `= 0`.
- Each: `profiles=("recommended", "default")`, severity ERROR (per KTD-9), source_spec naming the buf equivalent.

**Patterns to follow:**
- `naming.py` for the module shape + `@lint_rule` registration.
- `tests/schema/lint/test_canary_naming.py` for test organization.

**Test scenarios:**
- *Happy path:* `enum Status { STATUS_UNSPECIFIED = 0; STATUS_ACTIVE = 1; }` is clean under both rules.
- *Happy path (no-allow-alias):* enum without `allow_alias` is clean.
- *Sad path (first-value-zero):* `enum Status { STATUS_ACTIVE = 1; }` (first value is 1, not 0) → fires.
- *Sad path (no-allow-alias):* `enum Status { option allow_alias = true; FOO = 0; BAR = 0; }` → fires (no-allow-alias).
- *Edge case (no-allow-alias):* If `allow_alias = true` IS structurally needed (multiple values with same number), what's the right behavior? buf flags it always — protokit mirrors. Document the diverge-or-mirror decision in the rule docstring.
- *Edge case (first-value-zero):* proto2 enums (which don't require zero as first value) — buf still flags. Protokit mirrors.
- *Integration:* Profile composition — recommended fires both rules; essentials fires neither (enum semantics aren't in essentials).

**Verification:**
- `tests/schema/lint/rules/test_enum.py` passes.
- `test_builtin_packs.py` passes with updated pinned tuple.
- Static-analysis ratchet passes.

---

- [ ] **Unit 5: Imports pack — new `rules/imports.py`**

**Goal:** Ship `imports/no-public`, `imports/no-weak`, `imports/unused`. New pack module registered in BUILTIN_PACKS.

**Requirements:** R1 (imports family), R2.

**Dependencies:** Unit 2 (config schema). Sequential after Unit 4 — merges into the BUILTIN_PACKS pin in `test_builtin_packs.py:79`.

**Files:**
- Create: `src/protokit/schema/lint/rules/imports.py`
- Modify: `src/protokit/schema/lint/rules/__init__.py` (extend BUILTIN_PACKS to `(naming, enum, imports)`)
- Modify: `tests/schema/lint/test_builtin_packs.py:79`
- Test: `tests/schema/lint/rules/test_imports.py` (NEW)

**Approach:**
- 3 rules in `imports.py`:
  - `imports/no-public` (buf:IMPORT_NO_PUBLIC) — fires when `import public` is used.
  - `imports/no-weak` (buf:IMPORT_NO_WEAK) — fires when `import weak` is used.
  - `imports/unused` (buf:IMPORT_USED) — fires when an imported file's types are never referenced in the current file. Requires walking dependencies + usage graph.
- All: `profiles=("recommended", "default")`, severity ERROR (per KTD-9).
- **`FileDescriptor` API note**: protobuf-python's runtime `FileDescriptor` (the type `FileLintContext.file` carries) does NOT expose `public_dependency` / `weak_dependency` attributes — those index lists exist only on the proto-message form `FileDescriptorProto`. **D6a uses `ctx.file.CopyToProto(fdp)`** to serialize the runtime descriptor back to `FileDescriptorProto`, then read `fdp.public_dependency` / `fdp.weak_dependency`. This is a standard protobuf API with no version-skew risk, and the imports rules need `public_dependency` / `weak_dependency` index arrays which are populated regardless of whether `include_source_info` was set. `imports/unused` similarly uses `CopyToProto` to read the `dependency` array, then walks the current file's message/service type references checking which dependencies appear. (A separate `source_locations` lookup path was considered during planning but is unnecessary for D6a — that path depends on R6a/R6b, both deferred to D6b per J1; CopyToProto stands alone.)

**Patterns to follow:**
- `naming.py` for the module shape.
- `CopyToProto` round-trip for dependency-array access (no existing protokit precedent — D6a establishes this pattern; future imports/cross-file rules can reuse).

**Test scenarios:**
- *Happy path:* File with `import "google/protobuf/timestamp.proto"` and a `Timestamp` field is clean (used).
- *Sad path (no-public):* `import public "foo.proto"` → fires.
- *Sad path (no-weak):* `import weak "foo.proto"` → fires.
- *Sad path (unused):* `import "google/protobuf/timestamp.proto"` but no message uses Timestamp → fires.
- *Edge case:* Transitive imports — `imports/unused` only checks DIRECT imports, not transitive (matches buf behavior).
- *Edge case:* Well-known imports (`google/protobuf/descriptor.proto`) — buf treats these the same as user imports; protokit mirrors.
- *Integration:* Profile composition.

**Verification:**
- `tests/schema/lint/rules/test_imports.py` passes.
- `test_builtin_packs.py` passes.
- Static-analysis ratchet passes.

---

- [ ] **Unit 6: Package + File structural packs — new `rules/package.py` and `rules/file.py`**

**Goal:** Ship the structural rules outside naming-case (`package-defined`, `package-directory-match`, `file-syntax-specified`). Two new pack modules. `package-same-directory` (buf:PACKAGE_SAME_DIRECTORY) is **deferred to D6b** — see Out-of-Scope. It is a cross-file rule that requires comparing multiple files' `package` declarations; the current engine dispatches FILE-level rules one file at a time with no cross-call state, so a stateless FILE rule cannot implement it. Deferring to D6b alongside the other `PACKAGE_SAME_*` cross-language rules keeps multi-file engine extension as one coherent piece of work.

**Requirements:** R1 (package + file families), R2.

**Dependencies:** Unit 2 (config schema). Sequential after Unit 5 — merges into the BUILTIN_PACKS pin in `test_builtin_packs.py:79`.

**Files:**
- Create: `src/protokit/schema/lint/rules/package.py`
- Create: `src/protokit/schema/lint/rules/file.py`
- Modify: `src/protokit/schema/lint/rules/__init__.py` (extend BUILTIN_PACKS to `(naming, enum, imports, package, file)`)
- Modify: `tests/schema/lint/test_builtin_packs.py:79`
- Test: `tests/schema/lint/rules/test_package.py` (NEW)
- Test: `tests/schema/lint/rules/test_file.py` (NEW)

**Approach:**
- `package.py` (2 rules — `package/same-directory` deferred to D6b):
  - `package/defined` (buf:PACKAGE_DEFINED) — fires when file has no `package` declaration.
  - `package/directory-match` (buf:PACKAGE_DIRECTORY_MATCH) — fires when the file's package doesn't match its directory path. E.g., file at `acme/api/v1/users.proto` should have `package acme.api.v1;`.
- `file.py` (1 rule):
  - `file/syntax-specified` (buf:SYNTAX_SPECIFIED) — fires when a file's `syntax = "proto3";` (or proto2) declaration is missing. Proto's default-without-syntax is proto2; buf treats absence as a violation.
- All `profiles=("recommended", "default")`, severity ERROR (per KTD-9 buf-parity posture).
- Both `package/defined` and `package/directory-match` use `CopyToProto` to read `FileDescriptorProto.package` since the runtime `FileDescriptor.package` attribute IS available (unlike `public_dependency`); but for consistency with Unit 5's imports rules, document the choice inline. Path matching for `package/directory-match` uses `Path(file.name).parent.parts` (the .proto file's directory relative to its include root) and compares to `file.package.split('.')`.

**Patterns to follow:**
- `naming.py` for the module shape.
- `engine.py` walker order for file-level rule dispatch.

**Test scenarios:**
- *Happy path:* File `acme/v1/users.proto` with `package acme.v1;` and `syntax = "proto3";` is clean under all 4 rules.
- *Sad path (package-defined):* File with no `package` → fires.
- *Sad path (package-directory-match):* File `acme/v1/users.proto` with `package acme.v2;` → fires.
(package-same-directory test scenarios moved to D6b alongside the rule itself.)
- *Sad path (syntax-specified):* File with no syntax declaration → fires.
- *Edge case (package-directory-match):* What's the directory anchor? buf uses the directory containing the file. /ce:plan default: directory of `.proto` file relative to working directory.
- *Integration:* Profile composition.

**Verification:**
- Both new test modules pass.
- `test_builtin_packs.py` passes with updated tuple `(naming, enum, imports, package, file)`.
- Static-analysis ratchet passes.

---

- [~] **Unit 7: R6 option-aware differentiator — DEFERRED TO D6b (J1)**

**Status:** This unit is **deferred to D6b** along with R6 and the `_safe_for_findings()` sanitizer. D6a's BUILTIN_PACKS ends at `(naming, enum, imports, package, file)` — the `options` pack does NOT register in D6a. The full unit description below is preserved as a record of the rule design, heuristic-deferral decision, and test scenarios that carry forward to D6b's plan; do not implement it as part of D6a.

**Original goal (for D6b reference):** Ship the protokit-only differentiator: `options/deprecated-must-have-replacement-comment`. Uses `CompileResult.source_locations` (from deferred Unit 1) + the new `leading_comment(path)` lint-context helper. Adds `_safe_for_findings()` sanitizer for wire-format escape of comment-derived params.

**Requirements:** R6 (differentiator).

**Dependencies:** Unit 1 (source_locations + leading_comment helper); Unit 2 (profile alias mechanism + config schema). Sequential after Unit 6 — merges into the BUILTIN_PACKS pin in `test_builtin_packs.py:79`. Last unit in the sequential rule-pack chain.

**Files:**
- Create: `src/protokit/schema/lint/rules/options.py`
- Modify: `src/protokit/schema/lint/rules/__init__.py` (extend BUILTIN_PACKS to `(naming, enum, imports, package, file, options)`)
- Modify: `src/protokit/schema/lint/_cli_utils.py` (add `_safe_for_findings()` helper alongside `_safe_for_stderr`)
- Modify: `tests/schema/lint/test_builtin_packs.py:79`
- Test: `tests/schema/lint/rules/test_options.py` (NEW)
- Test: `tests/schema/lint/test_safe_for_findings.py` (NEW) — sanitizer unit tests; placed at the same tree level as `test_canary_naming.py` to match the colocation convention (test file mirrors the source module's tree position; `_cli_utils.py` is at `src/protokit/schema/lint/`, so its test goes at `tests/schema/lint/`, NOT `tests/schema/lint/_config/`)

**Approach:**
- 1 rule in `options.py`:
  - `options/deprecated-must-have-replacement-comment` — fires when `FieldOptions.deprecated = true`, `EnumValueOptions.deprecated = true`, `MethodOptions.deprecated = true`, `MessageOptions.deprecated = true`, or `EnumOptions.deprecated = true` is set AND the leading comment doesn't match the replacement-pointer heuristic.
- Heuristic: a regex- or keyword-based comment-text matcher detecting "this thing was deprecated AND its replacement is named in the comment." The exact pattern is **not pre-committed in this plan** and is finalized during Unit 7 implementation after surveying real-world deprecated-comment conventions (see Deferred-to-Implementation: "Comment-introspection heuristic for R6"). The implementer documents the chosen pattern in the rule's docstring + a short comment block describing what conventions are recognized and what is intentionally not matched. Avoid pre-committing to a specific regex shape here — it creates anchoring bias in the implementer and conflicts with the plan's "decisions not code" principle.
- `profiles=("default",)` — NOT in `recommended` (default = recommended + differentiator).
- Multi-kind rule: severity mapping per element type (field/enum-value/method/message/enum) — all `LintSeverity.ERROR` per KTD-9.
- The rule's `params` include the offending element name + (sanitized) comment text. `_safe_for_findings()` applied to comment_text before adding to `params`. The sanitizer collapses control chars + U+0085 + U+2028 + U+2029 to spaces.
- DeprecationWarning hygiene: run `pytest -W error::DeprecationWarning tests/schema/lint/rules/test_options.py` before shipping; add `recwarn`-based test asserting no DeprecationWarning emitted by the regex compile path.
- Per `keyboardinterrupt-baseexception-bypass-rule-pack-load`: the rule's check function is invoked through the existing engine guard (triple-arm catch). No new I/O surface in the rule itself.

**Patterns to follow:**
- `naming.py` for module shape.
- `_safe_for_stderr` in `_cli_utils.py` for the sanitizer's `str.translate` table-based approach.

**Test scenarios:**
- *Happy path:* Field `deprecated_field = 1 [deprecated = true];` with leading comment `// Use new_field instead.` is clean.
- *Happy path:* Non-deprecated field with no leading comment is clean (rule doesn't fire on non-deprecated elements).
- *Happy path:* Method, enum value, message, enum — each with `deprecated = true` + matching replacement comment is clean.
- *Sad path:* `deprecated_field = 1 [deprecated = true];` with NO leading comment → fires.
- *Sad path:* `deprecated_field = 1 [deprecated = true];` with leading comment `// Old field.` (no replacement pointer) → fires.
- *Edge case:* Comment with replacement at the END of a multi-line block: `// This is the old field.\n// Use new_field instead.` — should match (regex searches anywhere in the comment).
- *Edge case:* Comment with embedded `// Use X instead` inside an example block — current heuristic matches (false positive accepted as documented heuristic limitation).
- *Edge case:* Comment text contains control characters (newline, ANSI ESC, U+2028) — `_safe_for_findings()` sanitizes; finding's `params["comment"]` value contains no control chars; JSON/SARIF output has no aggregator-splittable bytes.
- *Edge case:* Empty comment string vs missing comment — both treated equivalently (rule fires).
- *Edge case:* Element marked `deprecated = true` but comment-text retrieval returns `None` (source_locations not preserved on some compile path) — rule emits a runtime warning rather than a finding, so absence-of-data doesn't masquerade as compliance.
- *Integration:* Rule fires via end-to-end CliRunner invocation with `--proto` mode (real source_code_info path).
- *Integration:* JSON output's `findings[*].params.comment` field is sanitized.
- *Integration:* `recwarn` test asserts no DeprecationWarning from `re.compile(...)` call.

**Verification:**
- `tests/schema/lint/rules/test_options.py` passes.
- `pytest -W error::DeprecationWarning tests/schema/lint/rules/test_options.py` passes (no strict-warning escape).
- `_safe_for_findings()` sanitizer tests cover the 7 control char categories from D5.
- `test_builtin_packs.py` passes with updated tuple `(naming, enum, imports, package, file, options)`. (Unit 7 is deferred to D6b; this Verification line moves with it.)

---

- [ ] **Unit 8: Parity test infrastructure — `tests/parity/` + advisory CI parity job + release watcher**

**Goal:** Land the buf-parity test harness: `tests/parity/` directory + `@pytest.mark.parity` marker + per-rule parity fixtures + dedicated CI job (advisory, non-blocking — J2) installing pinned buf binary + companion scheduled release-watcher workflow that opens an issue when a newer buf release exists.

**Requirements:** R10, R11 (advisory framing), R13 (pin policy + release-watcher + `--version` surfacing).

**Dependencies:** Units 3–6 (all rule packs registered; `BUILTIN_PACKS` complete except for R0 version bump).

**Files:**
- Create: `tests/parity/__init__.py` (empty)
- Create: `tests/parity/conftest.py` (buf binary discovery + invocation helper; parametrized fixture loading per rule)
- Create: `tests/parity/test_parity_naming.py`
- Create: `tests/parity/test_parity_enum.py`
- Create: `tests/parity/test_parity_imports.py`
- Create: `tests/parity/test_parity_package.py`
- Create: `tests/parity/test_parity_file.py`
- Create: `tests/parity/fixtures/{naming,enum,imports,package,file}/*.proto` (per-rule fixtures: 1 happy-path + 1 sad-path per rule)
- Modify: `pyproject.toml` (register `parity` pytest marker alongside `slow`)
- Modify: `tests/test_static_analysis.py` (add `"tests/parity"` directory entry to `_LINT_PATHS`)
- Modify: `.github/workflows/ci.yml` (NEW top-level `parity` job; buf binary install step with SHA-256 verification; pytest invocation step; advisory — `continue-on-error: true` or omit from required-checks list to keep non-blocking)
- Create: `.github/workflows/buf-release-watch.yml` (NEW scheduled workflow — weekly `cron`; queries `bufbuild/buf` releases via `gh release list -R bufbuild/buf --limit 5`; compares latest stable tag against the `_BUF_PARITY_PIN` constant grep'd from `src/protokit/schema/lint/cli.py`; opens or updates a single tracking issue titled "buf parity pin behind upstream" when behind, dedup'd by exact title — J2)

**Approach:**
- `@pytest.mark.parity` registered as a custom marker; default `pytest tests/` skips parity (gated by marker). Pytest configured via `pyproject.toml [tool.pytest.ini_options] markers = ["slow: ...", "parity: ..."]`.
- `conftest.py` provides:
  - `_BUF_BINARY: Path` — discovered from `$BUF_BINARY` env var, falls back to `shutil.which("buf")`.
  - `run_buf_lint(proto_path: Path, config: dict) -> list[dict]` — invokes buf as subprocess **with `subprocess.run(..., timeout=30, check=False)`** (30-second wall-clock cap; subprocess hangs do not deadlock CI), parses JSON output into structured findings. If buf exits non-zero with no parseable JSON, surface stderr as the test failure message rather than swallowing it. If the timeout fires, `subprocess.TimeoutExpired` propagates as a test failure with a clear "buf invocation exceeded 30s" message.
  - `run_protokit_lint(proto_path: Path, profile: str) -> list[dict]` — invokes protokit lint with `--format json`.
  - `assert_parity(buf_findings, protokit_findings, rule_id_map)` — compares rule-id and finding-location equivalence using the explicit `buf_id <-> protokit_id` map from `source_spec`.
- Per-rule test pattern: each test parametrizes over (rule_id, fixture_path) pairs. The fixture is a `.proto` file deliberately violating the rule. Both tools run on it; outputs compared.
- CI parity job (new top-level job in `.github/workflows/ci.yml`):
  - Runs on `ubuntu-latest` only (no matrix).
  - Step 1: Install pinned buf binary via curl (pin selected during Unit 8 implementation — bias toward latest stable buf as of that day; document in CI YAML comment). **Supply-chain hardening (required, not optional):** download the SHA-256 checksum file alongside the binary (`buf-Linux-x86_64.sha256` from the same release URL), verify the downloaded binary's checksum against it (`sha256sum -c buf-Linux-x86_64.sha256`), and fail the job if the verification fails. The checksum file URL and expected behavior are recorded in a YAML comment alongside the version pin so a future bump updates both. This prevents a compromised GitHub release artifact from silently shipping malicious code into our parity test harness. **Buf release asset name verification:** the asset name format (`buf-Linux-x86_64`) is verified against the pinned buf release page during Unit 8 implementation — buf has historically used both `buf-Linux-x86_64` and `buf-linux-x86_64` formats across releases; do not assume — fetch `https://api.github.com/repos/bufbuild/buf/releases/tags/v<PIN>` and confirm the actual asset name before wiring the curl URL.
  - Step 2: Install protokit + dev deps (existing pattern from `test` job).
  - Step 3: `pytest tests/parity/ -m parity`.
  - **Job is advisory (J2 — non-blocking).** Configured either via `continue-on-error: true` on the job's `runs-on` step OR simply by leaving the `parity` job out of any required-status-check branch-protection list. Parity divergence surfaces as a job failure in the PR's checks panel but does not gate merge. The original brainstorm's F-Deferred-CI-degradation resolution was "required PR check"; J2 supersedes that decision in favor of decoupling buf-release cadence from PR throughput, with the release-watcher workflow filling the surveillance gap.
- Per `fail-closed-ci-matrix-coverage-meta-test` learning: if parity tests use `@pytest.mark.skipif` with OS/Python predicate, add a companion coverage meta-test. D6a's parity tests are unconditionally on (no skipif), so the meta-test is NOT needed.
- Per `audit-wire-format-before-claiming-sibling-parity` learning: each fixture explicitly documents the buf rule_id ↔ protokit rule_id mapping in a header comment. Module docstring lists the mapping.

**Patterns to follow:**
- `tests/schema/lint/test_perf_smoke.py` for fixture generation (synthetic proto strings) and `@pytest.mark.slow` marker registration.
- Existing protoc install step at `.github/workflows/ci.yml:57–59` for the buf curl pattern.

**Test scenarios:**
- *Happy path:* Each `tests/parity/test_parity_*.py` parametrized test runs all fixtures; protokit's findings match buf's on rule-id + finding-location for each fixture.
- *Edge case:* Buf binary not installed (developer runs `pytest -m parity` locally without buf) — fixture discovery raises a clear "BUF_BINARY not found; install buf to run parity tests" error.
- *Edge case:* `pytest tests/` (no `-m parity`) skips all parity tests cleanly without invoking buf.
- *CI scenarios:*
  - Parity job runs on every PR; surfaces parity divergence as a failed-but-non-blocking job (advisory per J2).
  - Documentation in CI YAML comment explains the pin + drift policy + release-watcher mechanism per R13.
  - Release-watcher workflow runs weekly; opens a dedup'd tracking issue when the pin is behind upstream. Verification: dry-run the workflow against a known-stale pin and assert an issue is created (or the existing one is updated); dry-run against a current pin and assert no issue is created.

**Verification:**
- `pytest tests/parity/ -m parity` passes locally (with buf installed).
- `pytest tests/` (default) skips parity tests cleanly.
- CI parity job passes on a sample PR.
- `tests/parity` directory entry added to `_LINT_PATHS`; ratchet auto-covers all new parity test files.

---

- [ ] **Unit 9: CLI wiring — R9a user-wins + R9c flag + R9d schema_version + `--version` hook**

**Goal:** Wire the new config knobs into the CLI runtime. Apply R9a's user-wins severities overlay post-compose. Add R9c `--no-builtin-rules` CLI flag with `DEFAULT_MAP` source detection. Emit `schema_version` in lint_json + lint_sarif outputs. Add lint-subcommand `--version` override surfacing the buf parity pin.

**Requirements:** R9a (CLI side), R9c (CLI flag + pyproject equivalent already wired in Unit 2), R9d (`schema_version` wire output), R13 (`--version` surfacing).

**Dependencies:** Unit 2 (config schema), Unit 8 (buf binary pin known).

**Files:**
- Modify: `src/protokit/schema/lint/cli.py` (post-compose severities overlay around line 755; new `--no-builtin-rules` flag with `is_flag=True`; lint-subcommand `--version` flag override)
- Modify: `src/protokit/formatters/_builtin_lint.py` (`lint_json` root: add `"schema_version": "0.2"`; `lint_sarif`: add `runs[].properties.lint_schema_version = "0.2"`)
- Test: `tests/schema/lint/cli/test_r9a_severities_overlay.py` (NEW) — user-wins behavior
- Test: `tests/schema/lint/cli/test_r9c_no_builtin_rules.py` (NEW) — flag + pyproject equivalent + DEFAULT_MAP source detection
- Test: `tests/schema/lint/cli/test_r9d_schema_version.py` (NEW) — wire-format additions
- Test: `tests/schema/lint/cli/test_version_output.py` (NEW) — `--version` includes buf pin

**Approach:**
- R9a wiring at `cli.py` around line 755 (where `min_severity` injection currently happens). New code:
  ```
  if resolved.severities:
      composed_profile = dataclasses.replace(
          composed_profile,
          rule_severity_overrides={
              **composed_profile.rule_severity_overrides,
              **resolved.severities,
          },
      )
  ```
  User keys win on collision per KTD-2. When a user `severities` key references an unknown rule_id (not in any loaded pack), the engine emits a `LintRuntimeWarning(category="unloaded_rule", rule_id=<the unknown id>, message=<source-attributed text>)` — reusing the existing `unloaded_rule` category to avoid extending the `LintRuntimeWarning.category` Literal (which would be a separate wire-format change in D6a; pre-1.0 we could ship it, but reuse is simpler and the semantic fit is reasonable). The semantic conflation (profile-named-unloaded vs severities-named-unloaded) is accepted; both signals reach the user. A dedicated category for this case can be added in D6b if real user feedback shows the conflation is confusing.
- R9c flag (`--no-builtin-rules` is_flag, no default-None ambiguity): when set, the existing `BUILTIN_PACKS` auto-load loop in `cli.py` skips. Empty profile is fine — engine emits zero findings (or an `unloaded_rule` warning if a profile is selected). Per Click `ParameterSource` detection: only honor the flag when `ctx.get_parameter_source("no_builtin_rules") in explicit_sources`. Pyproject equivalent (already in Unit 2's `ResolvedLintConfig`) merges via standard CLI > pyproject precedence.
- R9d `schema_version`: top-level `lint_json` root gains `"schema_version": "0.2"`. `lint_sarif` adds `runs[].properties.lint_schema_version = "0.2"`. Per `cross-format-enum-string-parity` learning: same string value in both formatters. `lint_human` and `lint_junit` do NOT add the version: `lint_human` is terminal-rendered text not consumed by parsers; `lint_junit` is XML and CI-runner consumers historically rely on the JUnit standard schema without protokit-specific extensions — adding a vendor namespace there is deferred until a concrete consumer asks for it (tracked as a D6b+ follow-up, not a gap).
- **`schema_version` consumer contract** (documented in CHANGELOG + README): Consumers MUST treat unknown `schema_version` values as forward-compatible (read what they can, ignore new fields they don't understand) rather than hard-rejecting. Protokit bumps `schema_version` on (a) addition of new top-level keys, (b) **change in meaning of an existing field**, or (c) removal of a previously documented field. Adding new severity-level or category strings to an existing enum field does NOT bump the schema_version (the field's meaning is unchanged; the enum just gains a value). This contract gives downstream consumers a stable parsing model and prevents accidental break-the-world version bumps for additive enum growth.
- `--version` hook: Click's `@click.version_option(package_name="protokit")` at the top level outputs only the package version. Lint subcommand's `--version` (added as a flag override): callback prints `protokit X.Y.Z (parity: buf vM.N.P)` where the buf pin comes from a `_BUF_PARITY_PIN` constant in `cli.py` (kept in sync with `.github/workflows/ci.yml` via comment cross-reference). Drift between constant and CI YAML can be caught by a small static-analysis test that parses both.

**Patterns to follow:**
- Existing `min_severity` injection at `cli.py:755–764`.
- `ParameterSource` detection at `cli.py:529–538`.
- `lint_json` top-level key shape at `_builtin_lint.py:227`.
- `_emit_human_runtime_warnings` post-format hook from D5 U5 for any new advisory emissions.

**Test scenarios:**
- *Happy path (R9a):* Pyproject `severities = {"naming/snake-case-fields" = "info"}` AND profile = "default" → composed profile's `rule_severity_overrides["naming/snake-case-fields"] == LintSeverity.INFO`.
- *Happy path (R9a, user-wins):* Pyproject `severities = {"naming/enum-pascal-case" = "warning"}` AND the user's composed profile already has `rule_severity_overrides["naming/enum-pascal-case"] = LintSeverity.ERROR` (somehow); after the post-compose patch, value is `warning`.
- *Happy path (R9c flag):* `protokit lint --no-builtin-rules schema.descriptor_set` → BUILTIN_PACKS not loaded; if no `--rule-pack` provided, lint completes with zero findings (or `no-rules` error per existing D3 R20 behavior).
- *Happy path (R9c pyproject):* `[tool.protokit.lint] no_builtin_rules = true` → equivalent behavior.
- *Happy path (R9d):* `protokit lint --format json schema.descriptor_set` → JSON output's root has `"schema_version": "0.2"`.
- *Happy path (R9d):* `protokit lint --format sarif schema.descriptor_set` → SARIF output's `runs[0].properties.lint_schema_version == "0.2"`.
- *Happy path (--version):* `protokit lint --version` → output contains both `protokit 0.2.0` and `parity: buf v<PIN>`.
- *Edge case (R9a):* User severities references an unknown rule_id → emits an `unloaded_rule` runtime warning naming the unknown id (per KTD-2 + `unloaded_rule` reuse).
- *Edge case (R9c):* `--no-builtin-rules` + `--rule-pack my_pack` → only user pack rules load; lint runs against them.
- *Edge case (R9d):* `lint_human` output (default) does NOT include schema_version (it's a JSON-formatter-only addition).
- *Edge case (R9d):* `lint_junit` output does NOT include schema_version (XML-formatter; not in scope for this delivery).
- *Edge case (--version):* `protokit lint --help` does NOT include the buf pin string (it's a `--version` specific surface).
- *Integration:* End-to-end CliRunner invocation exercises all 4 new flag/config combinations.

**Verification:**
- All new CLI tests pass.
- `_LINT_HUMAN_SUMMARIZATION_THRESHOLD` recalibration is performed in Unit 10 per R14 (after all rules are registered); Unit 9 does not perform this work.

---

- [ ] **Unit 10: R0 version bump + CHANGELOG + README + Public Surface + sweep stale text**

**Goal:** Finalize the D6a delivery. Bump pyproject version 0.1.0 → 0.2.0. Amend the KD-9 docstring in `rules/__init__.py` to reflect the pre-1.0 "no stability guarantee" stance (moved here from earlier units — the policy clarification should ship in the same commit as the BUILTIN_PACKS expansion it authorizes). Add a CHANGELOG entry for D6a enumerating all auto-load expansions, the wire-format `schema_version` addition, the new pyproject keys, the 3 new protokit-native profile names + buf-alias mapping, and the available demotion paths (no ceremonial `BREAKING:` marker — pre-1.0, the version bump and CHANGELOG entry are communication enough). Update README's Schema Linting section with the 3 new profile names + alias mapping + demotion-path guidance + R9c opt-out path. Update Public Surface DRAFT table with rows for new profile names, buf-alias mapping, and `schema_version` wire field (the `source_locations` and `_safe_for_findings()` rows move to D6b along with R6/R6a/R6b — J1). Sweep stale forward-looking text from the codebase per `stale-forward-looking-text-cli-help-agent-discoverability` learning.

**Requirements:** R0 (final commit).

**Dependencies:** All non-deferred D6a units (2, 3, 4, 5, 6, 8, 9 — all behavior in place; Units 1 and 7 are deferred to D6b).

**Files:**
- Modify: `pyproject.toml` (`version = "0.2.0"`)
- Modify: `src/protokit/schema/lint/rules/__init__.py` (KD-9 docstring at lines 17–54: amend point 2 to reflect that protokit is pre-1.0 — "While protokit is pre-1.0 there is no stability guarantee; new packs may be added to BUILTIN_PACKS freely, with a CHANGELOG entry describing what users will see. Post-1.0, additions are gated on a major-version bump per the original intent." Drop point 3's specific BREAKING-marker requirement since the marker is decorative pre-1.0; keep the CHANGELOG-entry expectation as plain communication.)
- Modify: `CHANGELOG.md` (new `### D6a — ...` section under Unreleased; upgrade notes + demotion paths)
- Modify: `README.md` (Schema Linting section additions; Public Surface DRAFT table rows; upgrade recipe)
- (Sweep across `src/protokit/`, `tests/`, `docs/`, `README.md`, `CHANGELOG.md` for any stale forward-looking text — small edits scattered across multiple files)
- Modify: `~/.claude/projects/.../memory/project_state.md` and `MEMORY.md` (per-delivery workflow: trigger `/ce:compound` at delivery boundary which drives these updates)
- Test: `tests/test_changelog_d6a_entry.py` (NEW) — asserts a CHANGELOG.md section titled with "D6a" exists (a presence ratchet; doesn't enforce a specific heading shape, just that the delivery is documented for users)
- Test: `tests/schema/lint/rules/test_kd9_docstring.py` (NEW, or inline in existing test_builtin_packs.py) — asserts KD-9 docstring contains "pre-1.0 there is no stability guarantee" (the substring is the ratchet against silent reversion to the old "major-version bump" wording while protokit is still pre-1.0).

**Approach:**
- Version bump in `pyproject.toml` line 7: `version = "0.2.0"`. (No version bumping mechanism — direct edit.)
- CHANGELOG entry: a plain `### D6a — ...` section under Unreleased (no `BREAKING:` prefix — pre-1.0, the version bump itself signals change). Enumerate:
  - **BUILTIN_PACKS expansion** — 4 new packs auto-loaded: enum, imports, package, file. Existing users see ~16 new categories of ERROR-severity findings on previously-green CI (per KTD-9 buf-parity posture). (The `options` pack — R6 differentiator — is deferred to D6b per J1.)
  - **Wire format** — `lint_json` root gains `"schema_version": "0.2"`; SARIF gains `runs[].properties.lint_schema_version`.
  - (`CompileResult.source_locations` and `_safe_for_findings()` helper moved to D6b — J1.)
  - **Pyproject schema** — `[tool.protokit.lint] severities` and `[tool.protokit.lint] no_builtin_rules` keys added.
  - **Profile names** — `essentials`, `recommended`, `default` are now the primary protokit-native profile names; `minimal`/`basic` are aliases.
  - **Opt-out / demotion paths** — `--no-builtin-rules` (CLI) or `no_builtin_rules = true` (pyproject) for full opt-out; `--min-severity=warning` for global demotion; `[tool.protokit.lint.severities]` for per-rule demotion; or pin to `protokit~=0.1.0`.
  - **Upgrade notes** — section walks users through (a) upgrade, (b) see new findings, (c) triage via `--format json | jq` or in-place, (d) demote or fix.
- README Schema Linting section additions:
  - New "Profiles" subsection enumerating `essentials`/`recommended`/`default` with rule counts + buf-alias mapping.
  - Upgrade notes (mirrored from CHANGELOG).
  - `--no-builtin-rules` flag documentation.
  - Demotion-path note: "D6a rules ship at ERROR (buf BASIC parity); use `--min-severity=warning` globally or `[tool.protokit.lint.severities]` per-rule to demote."
- Public Surface DRAFT table — new rows (per `public-surface-draft-discipline-source-audit` learning; rows are DRAFT documentation while protokit is pre-1.0, not a stability contract):
  - `Profile names: essentials / recommended / default` (IN)
  - `Buf aliases: minimal → essentials, basic → recommended` (IN)
  - `lint_json["schema_version"]: "0.2"` (IN)
  - `lint_sarif runs[].properties.lint_schema_version: "0.2"` (IN)
  - (`CompileResult.source_locations` and `_safe_for_findings()` rows deferred to D6b along with R6/R6a/R6b — J1.)
  - (Output ordering deliberately NOT listed as a Public Surface row — `LintEngine.run` sorts by `(file, location, rule_id)` per KTD-6 for deterministic test output, but that tuple shape is an implementation detail subject to change. Re-listing it later if a downstream consumer asks for the contract.)
- Stale-text sweep: run the **expanded** canonical grep across `src/`, `tests/`, `docs/`, `README.md`, `CHANGELOG.md`: `grep -rn "until D[0-9]\|will land\|arrives in U\|forthcoming\|once U[0-9] ships\|in D6a\|D6a will\|TODO(D6a)\|D6b will\|once D6a ships\|after D6a\|deferred to D6a" src/ tests/ docs/ README.md CHANGELOG.md`. The `tests/` + `README.md` expansion catches stale references in test docstrings and the linting README section. The `D6a`-specific patterns catch deferral-shaped text written before this delivery existed. For each match, decide: rewrite to present tense (if the referenced feature now exists), update to point at D6b/D7 (if deferred), or leave (if still forward-looking with respect to a later delivery).

**Patterns to follow:**
- D5 U6's CHANGELOG entries (`### BREAKING (D5 U3/U4/U5 — ...)` headings — historical pattern; D6a drops the `BREAKING:` prefix per "pre-1.0, no stability ceremony" but keeps the H3 + parenthetical-description shape).
- Existing Public Surface DRAFT appendix in README.

**Test scenarios:**
- *Verification:* `protokit lint --version` reflects new version (0.2.0).
- *Verification:* `test_builtin_packs.py` final pinned tuple is `(naming, enum, imports, package, file)` (5 entries — `options` pack deferred to D6b per J1).
- *Verification:* Grep for stale text returns zero hits (or only intentional-forward-looking ones).
- *Verification:* `pytest tests/` passes (full regression — 1329 → ~1500+ tests).
- *Verification (required, not optional):* `tests/test_changelog_d6a_entry.py` asserts a CHANGELOG.md section titled with "D6a" exists (one assertion on one file read; trivial to write, high value as a ratchet against accidentally omitting the delivery documentation — communication discipline, not a stability promise).

**Post-Unit workflow trigger (explicit, not implicit):**
- After Unit 10 lands and is committed, invoke `/ce:compound` (compound-engineering compound mode) at the delivery boundary to: (a) extract new institutional learnings from D6a into `docs/solutions/`, (b) reciprocate cross-references with existing learnings, (c) update `~/.claude/projects/.../memory/project_state.md` and `MEMORY.md` reflecting D6a complete. The plan calls this out as a workflow obligation rather than a code-touching task — it is not gated by a test but is a required ritual in the established per-delivery workflow (validated across D2, D3, and D5). Skipping it forfeits the compounding-knowledge benefit of D6a.

**Verification:**
- `pyproject.toml` version is `"0.2.0"`.
- `CHANGELOG.md` has a `### D6a — ...` section.
- README Schema Linting section documents profiles + aliases + demotion paths.
- Public Surface DRAFT table has 4 new rows (profile names, buf aliases, `lint_json` schema_version, `lint_sarif` schema_version). No output-ordering row (pre-1.0 not a contract). `source_locations` / `_safe_for_findings()` rows move to D6b along with R6/R6a/R6b — J1.
- Full test suite passes.
- Static-analysis ratchet passes.
- Cold-import contract passes.

## System-Wide Impact

- **Interaction graph:** R9a's post-compose patch hooks into the existing `cli.py:755–764` composed-profile injection point. R7's alias resolution lives in `_coerce_profile` at the input boundary, covering both pyproject + CLI paths. New rules invoke through the existing `_LintContextEmitMixin` emit pathway. (R6/R6a/R6b's compile-output → engine-input boundary work is deferred to D6b per J1.)
- **Error propagation:** New `_ALLOWED_KEYS` entries fall through the existing `_validate_table_keys` machinery — unknown-key behavior unchanged. New `_coerce_*` helpers raise the same `error_exit_with_code("pyproject-config-invalid", ...)` path as existing helpers. R9c flag uses Click's `ParameterSource` detection per the established D5 pattern.
- **State lifecycle risks:** None obvious — D6a doesn't add persistent state. (`CompileResult.source_locations` deferred to D6b per J1; no new compile-result state in D6a.)
- **API surface parity:** New `LintRuleSpec.source_spec="buf:<RULE_ID>"` annotations on all D6a rules give parity tests a discoverable rule-id map. The Public Surface DRAFT table additions document the new surface.
- **Integration coverage:** Each rule unit's *Integration* test scenarios cover profile composition (rules fire under both `recommended` and `default`, which are structurally equivalent in D6a). (R6's end-to-end integration test — source_code_info preservation → source_locations → leading_comment lookup → sanitized params → JSON output — moves to D6b along with R6 itself.)
- **Unchanged invariants:**
  - D1 cold-import contract: `import protokit.schema` does not load `lint.*`. New rule modules under `protokit.schema.lint.rules.*` are auto-quarantined by the existing substring match.
  - D2 engine walker order: rules emit in lex-by-full_name order within each element kind (cross-rule sort lands at the engine-output boundary per KTD-6, NOT in the walker itself).
  - D3 CLI exit-code ladder: existing exit codes unchanged. R9c's `--no-builtin-rules` + no rule packs scenario routes through the existing `no-rules` exit-2 path.
  - D4 formatter contract: `lint_human` / `lint_json` / `lint_junit` / `lint_sarif` continue rendering at the same dispatch points. R9d adds a top-level key to JSON/SARIF (additive); does not change existing keys.
  - D5 cross-formatter render parity: all 4 categories (`rule_exception`, `unloaded_rule`, `min_severity_relaxed`, `all_files_excluded`) continue rendering across all 4 formatters. No new `LintRuntimeWarning.category` values added in D6a (R9a's unknown-rule-id warning reuses `unloaded_rule`).

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| `--no-builtin-rules` users have no rule source until D7 plugin loading | Acknowledge in README + flag help text: "Use --rule-pack MODULE to provide your own rules until D7 ships pyproject-based plugin loading." |
| Buf binary download unavailable in CI (rate limit, outage) | Parity job is advisory (J2) so a failed download doesn't block PRs. Release-watcher job tolerates rate limits via the same dedup'd-issue pattern. |
| New rule fires falsely on edge cases not covered by D6a's fixture corpus | Document each rule's heuristic limitations in the rule's docstring. |
| Existing protokit 0.1.x users get findings on upgrade | Pre-1.0, no stability guarantee — but CHANGELOG documents what changed and the available demotion paths (`--min-severity=warning`, `[severities]` per-rule, `--no-builtin-rules`). |
| Cross-rule emit ordering change breaks downstream consumers parsing findings by position | Document the new ordering in CHANGELOG. Pre-1.0, we do not promise the specific `(file, location, rule_id)` tuple shape as a stable contract — consumers should not parse by positional invariants. |
| Profile alias resolution introduces ambiguity if user packs declare the alias name | Aliases resolve at config-load time BEFORE rule pack profile-name matching. A user pack declaring `profiles=("basic",)` would never match because `basic` is resolved to `recommended` before lookup. Document this in `_PROFILE_ALIASES` inline comment. |
| R0 version bump confuses users with pinned `protokit~=0.1.0` | `~=0.1.0` means `>=0.1.0, <0.2.0`, so pinned users are NOT auto-bumped. Document this in CHANGELOG upgrade notes. |
| Buf parity job download latency slows CI | Job is advisory so latency doesn't block merges. Optional: add a GitHub Actions cache step for the pinned buf binary if developers complain about job duration. |
| Release-watcher fires false-positives (e.g., pre-releases interpreted as newer) | Restrict the version comparison to releases without a pre-release suffix (no `-rc`, `-beta`, etc.). Tested via dry-run before shipping the workflow. |
| Default profile is structurally equivalent to recommended in D6a (no differentiator) | Documented in R3 + R7 + README profiles subsection. The `default` name is retained for forward-compatibility with D6b differentiators; consumers targeting `default` today get the same rule set as `recommended` until D6b lands. |

## Documentation / Operational Notes

- **CHANGELOG.md** — primary delivery doc; `### D6a — ...` section enumerates the wire-format + auto-load changes + demotion paths (no `BREAKING:` prefix; pre-1.0, the version bump itself signals change).
- **README.md** — Schema Linting section grows: Profiles subsection, upgrade notes, `--no-builtin-rules` doc, demotion-path note, Public Surface DRAFT table additions.
- **Public Surface DRAFT table** — 4 new rows per `public-surface-draft-discipline-source-audit` learning (profile names, buf aliases, `lint_json` + `lint_sarif` schema_version). Each row grep-verified against source before shipping. Output ordering is intentionally NOT listed (implementation detail, not a stability promise). `source_locations` and `_safe_for_findings()` rows move to D6b along with R6/R6a/R6b — J1.
- **Inline rule docstrings** — each new rule documents its buf equivalent (`buf:<RULE_ID>`) and any deliberate divergence from buf semantics per `audit-wire-format-before-claiming-sibling-parity`.
- **Memory updates** — after D6a ships, update `~/.claude/projects/.../memory/project_state.md` and `MEMORY.md` to reflect D6a SHIPPED + D6b becomes the next delivery.
- **No new docs/solutions/ entries during D6a** — those are captured at delivery boundary via `/ce:compound`.
- **TODOS.md refresh** — after D6a ships, update the D6 section to reflect D6a landed + D6b agenda.

## Sources & References

- **Origin document:** `docs/brainstorms/2026-05-12-protokit-lint-delivery-6a-rule-library-requirements.md`
- Related code references throughout the plan use repo-relative paths and (file:line_number) format where useful.
- Related external references: `https://github.com/bufbuild/buf` (buf source for rule semantics); `https://buf.build/docs/lint/rules` (buf published rule docs — exact rule names and severities).
- Related institutional learnings: 17 entries from `docs/solutions/` cited inline (see Institutional Learnings section).
