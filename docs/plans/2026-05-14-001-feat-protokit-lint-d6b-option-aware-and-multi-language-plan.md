---
title: "feat: protokit-lint D6b — option-aware path operational + 17/18 buf BASIC parity"
type: feat
status: active
date: 2026-05-14
origin: docs/brainstorms/2026-05-14-protokit-lint-delivery-6b-option-aware-and-multi-language-requirements.md
---

# feat: protokit-lint D6b — option-aware path operational + 17/18 buf BASIC parity

## Overview

D6b ships protokit-lint's first comment-aware rule family (R6 — 5 rules covering `*Options.deprecated` across FIELD / ENUM_VALUE / METHOD / MESSAGE / ENUM ElementKinds) and unblocks multi-language rule-set parity (R7 — 7 PACKAGE_SAME_* rules). Architectural additions: `compile_protos_to_result(include_source_info: bool = False)` opt-in parameter; `CompileResult.source_info_descriptors` field; a module-level `leading_comment()` free function; `FileLintContext.source_info_descriptors` + `FileLintContext.package_options` fields; an engine pre-walk pass that builds the per-package option-value accumulator. Wire-format: `LintRuntimeWarning.category` Literal widens to 5 values (`severities_unloaded_rule` split); `_LINT_JSON_SCHEMA_VERSION` bumps `"0.2"` → `"0.3"`; package version bumps `0.2.0` → `0.3.0`. `package/same-directory` (the 18th buf BASIC rule + cross-file rule kind) is deferred to D6c per the brainstorm.

## Problem Frame

D6a (0.2.0, shipped 2026-05-13/14) made protokit-lint a credible buf BASIC competitor **for single-language teams**. Two product gaps remain:

- **Multi-language teams are blocked on the rule-set layer.** Buf's BASIC tier includes `PACKAGE_SAME_*` by default; protokit's `recommended` doesn't fire those rules, so multi-language migration silently weakens policy. (Other migration touchpoints — `buf.yaml` config import, `buf:lint:ignore` parity, `buf breaking` — remain post-D6b.)
- **The option-aware path is unproved.** No rule in `BUILTIN_PACKS` reads custom options or source comments today. R6's 5-rule family validates the plumbing (SourceCodeInfo preservation + leading_comment helper + sanitizer reuse) without overclaiming the broader differentiator until D6c grows the pack.

D6b closes both gaps in one delivery. **Headline:** option-aware path operational (R6 is the first rule using it). PACKAGE_SAME_* parity is the larger user-impact surface but secondary in framing (see origin: brainstorm TL;DR).

## Requirements Trace

- **R6.** 5 `@lint_rule` functions under `protokit.schema.lint.rules.options.deprecated_replacement` (one per `*Options.deprecated` ElementKind) sharing a `_check_replacement_comment` helper. Severity `warning` at launch. Profile `default` only. Each rule's `source_spec=""` (excluded from parity harness).
- **R6a.** `compile_protos_to_result(include_source_info: bool = False)` opt-in parameter; threads through both backend functions which gain a third return element `Mapping[str, FileDescriptorProto] | None`. Lint CLI sets `True`; non-lint consumers (compat, codegen) stay on the pre-D6b default.
- **R6b.** `CompileResult.source_info_descriptors: Mapping[str, FileDescriptorProto] | None` field; module-level `leading_comment(source_info_descriptors, file_name, path)` free function; `FileLintContext.source_info_descriptors` engine-injected field (single dataclass addition; the brainstorm's "contexts already reference compile_result" claim was incorrect — verified by Phase 1 research).
- **R6c.** Inline reuse of existing `_safe_for_stderr` for comment-derived params (truncated to 500-char prefix to bound wire-format size against adversarial protos). No new sanitizer module.
- **R7.** 7 `@lint_rule` functions in one module `protokit.schema.lint.rules.package_same` reading FileOptions string values. Engine pre-walk pass builds per-package option-value accumulator (`package_options: dict[str, dict[str, str | None]]`); rules read via new `FileLintContext.package_options` field. Emit-shape: one finding per file whose value disagrees with the canonical value (canonical = lexicographically-smallest filename in the package). Profile `recommended` + `default`. Severity `error`. `source_spec="buf:PACKAGE_SAME_*"` for parity harness auto-discovery.
- **R9.** `LintRuntimeWarning.category` Literal widens from 4 → 5 values (`severities_unloaded_rule` added). CLI emit site at `src/protokit/schema/lint/cli.py:1062-1090` switches from `"unloaded_rule"` to `"severities_unloaded_rule"`. The 3-site discipline applies per [[semantic-category-conflation-accepted-tradeoff-literal-widening]]: Literal docstring + emit-site comment + TODOS.md entry retired.
- **R9-bump.** `_LINT_JSON_SCHEMA_VERSION` bumps `"0.2"` → `"0.3"`; bump-contract docstring at `src/protokit/formatters/_builtin_lint.py:243-249` updates to refine the rule (closed-discriminator Literal additions DO bump; open severity-string additions don't). Both consumption sites (`lint_json:329` + `lint_sarif:673`) update via the single constant edit.
- **R10.** Parity fixtures under `tests/parity/fixtures/package/same-{lang}/` — `good.proto` (all files agree), `bad-value.proto` (mixed values), `bad-presence.proto` (some declare, others omit). 7 rules × 3 fixtures = 21 fixture protos. Adversarial fixtures: `_evil_option_value.proto` (newline injection in FileOptions strings).
- **R11.** Version bump `0.2.0` → `0.3.0` in pyproject.toml. CHANGELOG `### D6b — ...` plain section (no BREAKING prefix per [[pre-1.0-version-bump-as-communication-contract]]).
- **R12.** Public Surface DRAFT additions per [[public-surface-draft-discipline-source-audit]]: `CompileResult.source_info_descriptors` (INTERNAL), `FileLintContext.source_info_descriptors` (INTERNAL), `FileLintContext.package_options` (INTERNAL), `compile_protos_to_result(include_source_info=)` parameter (IN), 5 R6 rule_ids (IN), 7 R7 rule_ids (IN), expanded `LintRuntimeWarning.category` Literal (IN — updated), bumped `schema_version: "0.3"` (IN — rows at README.md:760, 763 update).

## Scope Boundaries

- D6b ships 17 of 18 buf BASIC rules; the 18th (`package/same-directory`) is deferred (see below).
- R6 ships at `warning` severity, not `error` (heuristic-rule blast-radius asymmetry per brainstorm document review).
- `_LintContextEmitMixin` does NOT gain a `leading_comment` method (per scope-guardian + adversarial brainstorm review). Free function preferred.
- No new `_safe_for_findings` module — inline `_safe_for_stderr` reuse.
- `strict` profile not shipped (continues D6a deferral with acknowledged `essentials`-inconsistency note).
- R9b per-rule disable/enable lists not shipped (continues D6a deferral; no real-demand evidence yet).
- Expanded option-aware pack beyond R6's deprecated-replacement family deferred to D6c.

### Deferred to Separate Tasks

- **`package/same-directory` (18th buf BASIC rule + cross-file rule kind)** — deferred to D6c. Requires new ElementKind + new LintLocation discriminant variant + engine walker phase + audit of every `match/case` over LintLocation in formatters per [[cross-format-enum-string-parity]]. Multi-module wire-format change worth its own focused delivery. CHANGELOG documents the gap honestly.
- **`strict` profile rule enumeration** — D6c. Acknowledged inconsistency with `essentials` (0-rule placeholder shipping in 0.2.0); D6c picks one stance (remove `essentials` OR ship `strict` empty).
- **R9b per-rule disable/enable lists** — D6c (awaiting real-demand evidence). The 4-precedence-shape design space defers more defensibly than R9's additive Literal widening.
- **Expanded option-aware pack** (`options/required-field-behavior`, `options/required-custom-annotation`, `options/json-name-respects-snake-case`) — D6c+.
- **Per-file rule overrides** (path-glob → rule-id) — sibling of R9b; D6c.
- **Per-buf-version parity matrix** — post-D6c infrastructure.

## Context & Research

### Relevant Code and Patterns

- **Compile backends:** `src/protokit/_cli_utils.py:219` (`_compile_with_protoxy`, `include_source_info=False` hard-coded at line 257) and `:275` (`_compile_with_protoc`, argv built at line 305 without `--include_source_info`). Both return `tuple[DescriptorPool, tuple[str, ...]]` today; R6a widens to `tuple[..., ..., Mapping[str, FileDescriptorProto] | None]`.
- **CompileResult instantiation:** `src/protokit/schema/compile.py` — 5 sites (lines 374, 380, 396, 450) all need `source_info_descriptors` parameter; early-return paths pass `None`.
- **CompileResult dataclass:** `src/protokit/schema/compile.py:145-187`. Already de-facto unhashable (DescriptorPool isn't hashable) — adding `Mapping[str, FileDescriptorProto] | None` doesn't introduce new hash regressions. `__post_init__` snapshot pattern at lines 177-187 mirrors for the new field per [[frozen-dataclass-mutable-fields-need-post-init-snapshot]].
- **8 LintContext dataclasses:** `src/protokit/schema/lint/model.py:957-1209` — only `FileLintContext` (line 957) gains new fields per R6b/R7 plan. The other 7 contexts are untouched.
- **`_LintContextEmitMixin`:** `src/protokit/schema/lint/model.py:878-954` — exposes only `emit()` and `location()` today. Intentionally minimal; staying minimal per scope-guardian review.
- **`LintEngine.run`:** `src/protokit/schema/lint/engine.py:261-401`. Pre-walk hook point between Step 3 (line 377, after `group_by_kind` bucketing) and Step 4 (line 379, walking `root_files`). Context builders at 609 (`_build_file_ctx` — gets new `source_info_descriptors` + `package_options` params).
- **`LintRuntimeWarning.category` Literal:** `src/protokit/schema/lint/model.py:344, 492-497`. Currently 4 values; widens to 5.
- **`_LINT_JSON_SCHEMA_VERSION`:** `src/protokit/formatters/_builtin_lint.py:250`. Consumption: `lint_json:329`, `lint_sarif:673`. Bump-contract docstring lines 243-249 — needs refinement.
- **`_safe_for_stderr` + `_CONTROL_CHAR_TABLE`:** `src/protokit/schema/lint/_cli_utils.py:198, 216`. Import path: `from protokit.schema.lint._cli_utils import _safe_for_stderr`.
- **`@lint_rule` decorator:** `src/protokit/schema/lint/decorator.py:52-141`. `element: ElementKind` is singular — confirms the 5-separate-rules decision for R6.
- **Rule pack template (closest analogue):**
  - R6: `src/protokit/schema/lint/rules/naming.py` (9-rule + 3-helper pattern; closest shape for 5 rules sharing a helper).
  - R7: `src/protokit/schema/lint/rules/imports.py` (3 FILE-element rules — closest R7 shape).
- **CLI emit site for `severities_unloaded_rule` split:** `src/protokit/schema/lint/cli.py:1062-1090`.
- **Parity harness:** `tests/parity/conftest.py:188` (`RULE_ID_MAP` auto-walks `BUILTIN_PACKS` via `source_spec="buf:..."` prefix; R7 picked up automatically, R6 excluded automatically via empty `source_spec`).
- **Public Surface DRAFT:** `README.md:740-779` (heading line 740, table lines 750-773, schema_version rows at 760 + 763).
- **CHANGELOG insertion point:** `CHANGELOG.md:555` (between D6a section ending at 554 and `### Rationale` at 556).

### Institutional Learnings

19 learnings bind to D6b (full mapping in research output):

- [[frozen-dataclass-mutable-fields-need-post-init-snapshot]] — U2 must add `__post_init__` snapshot for `CompileResult.source_info_descriptors` AND for the new `FileLintContext` mapping fields.
- [[frozen-dataclass-paired-field-invariant-post-init]] — Source-info-paired invariants on both CompileResult AND FileLintContext.
- [[copytoproto-round-trip-for-proto-form-only-descriptor-fields]] — R6b's "preserve FileDescriptorProto before pool.Add()" pattern. Add `source_code_info` to the proto-form-only table in this learning.
- [[circular-import-type-checking-cycle-break]] — `FileDescriptorProto` annotation on `CompileResult.source_info_descriptors` and `FileLintContext.source_info_descriptors`. TYPE_CHECKING-guard if cycles emerge.
- [[normalize-at-input-boundary]] — R7's NULL-vs-default-value FileOptions semantics resolved at the pre-walk pass boundary.
- [[cross-format-enum-string-parity]] — Schema version bump surfaces identically in `lint_json` + `lint_sarif`; new `severities_unloaded_rule` value emits identical strings across all 4 formatters.
- [[wire-format-schema-version-bump-contract-and-absence-semantic]] — Bump-contract docstring at `_builtin_lint.py:243-249` REQUIRES refinement in U5; current docstring's "enum-value additions don't bump" stance contradicts the brainstorm decision. Refinement: closed-discriminator Literal additions DO bump; open severity-string ladder additions DON'T.
- [[semantic-category-conflation-accepted-tradeoff-literal-widening]] — U5 resolves U9 KTD-2 explicitly. 3-site discipline applies in reverse: Literal docstring + CLI emit-site comment + TODOS.md entry retired.
- [[audit-wire-format-before-claiming-sibling-parity]] — R7 PACKAGE_SAME_* parity claims audited against buf actual emit (NULL semantics, emit-shape, severity, message template).
- [[buf-parity-divergence-documentation-discipline]] — R6 has no buf analogue; 5 rule docstrings document the protokit-original status; `source_spec=""` excludes from parity harness.
- [[module-name-newline-injection-stderr-forge]] — R6 comment text AND R7 FileOptions string values MUST pass through `_safe_for_stderr` before any wire-format interpolation. Adversarial test fixtures mandatory (P0 plan requirement, not ce:review surprise).
- [[presence-ratchet-test-pattern-for-prose-substrings]] — U7 adds ratchets for the R6 worked-example section in README, the D6b CHANGELOG section, the bump-contract docstring refinement.
- [[delivery-boundary-unit-commit-composition]] — U7 follows D6a U10 shape (version bump + CHANGELOG + README + Public Surface DRAFT + sweep + presence ratchets in one commit).
- [[pre-1.0-version-bump-as-communication-contract]] — Plain `### D6b — ...` CHANGELOG section, no BREAKING prefix.
- [[stale-forward-looking-text-cli-help-agent-discoverability]] — U7 invokes canonical sweep with triage rubric (refreshed at D6a U10).
- [[public-surface-draft-discipline-source-audit]] — Every Public Surface DRAFT row added in U7 grep-verified against source.
- [[pytest-static-analysis-gate-ratchet]] — New D6b paths (`protokit.schema.lint.rules.options.*`, `protokit.schema.lint.rules.package_same.*`) added to `tests/test_static_analysis.py:_LINT_PATHS` in the same commit they're created.
- [[cross-file-pin-regex-anchor-structure-not-annotation-token]] — Audit any cross-file regex pins on `_LINT_JSON_SCHEMA_VERSION`; bump value safely.
- [[structural-pin-inspect-getsource-untestable-collision-branch]] — Pre-walk iteration order pinned (sorted by file path); structural pin via `inspect.getsource` if no fixture can construct the collision.

### External References

None — local patterns from D2-D6a are strong; no external research needed per Phase 1.2 assessment.

## Key Technical Decisions

- **KTD-1: `include_source_info` opt-in at `compile_protos_to_result` API, not always-on at backend.** Per brainstorm document review (3-persona convergence). Non-lint consumers (`protokit compat`, codegen, direct Python API) keep the pre-D6b zero-cost contract. Lint CLI's compile invocation sets `True`. Atomic flip of BOTH backends preserves the byte-equivalence-between-backends invariant.

- **KTD-2: `source_info_descriptors` is a direct field on `FileLintContext`, NOT via `compile_result` reference.** Phase 1 research surfaced that the brainstorm's claim "contexts already reference compile_result" was incorrect — contexts have `file`, `pool`, `profile`, and engine-injected fields, but no `compile_result`. Single-field addition (paralleling R7's `package_options`) is the leanest path and avoids any 8-context plumbing. Free function `leading_comment(ctx.source_info_descriptors, ctx.file.name, path)` reads from the single field.

- **KTD-3: `leading_comment` is a module-level free function**, NOT a method on `_LintContextEmitMixin`. Eliminates 8-dataclass plumbing for capabilities with one current consumer family. If a future delivery has 5+ comment-aware rules and a mixin method earns its keep on ergonomics, extract then.

- **KTD-4: Inline `_safe_for_stderr` reuse, no new sanitizer module.** Threat model identical to D5 U5's stderr concerns (`_CONTROL_CHAR_TABLE` already covers U+0085 / U+2028 / U+2029 / ASCII control chars). With one current consumer family (R6), inline reuse + 500-char truncation prefix is sufficient. Optional follow-up: rename `_safe_for_stderr` → `_strip_control_chars` if a second consumer materializes in D6c.

- **KTD-5: Bump-contract docstring refinement is REQUIRED in U5.** Existing `_builtin_lint.py:243-249` docstring says "enum-value additions don't bump"; that's correct for OPEN severity-string ladders (the `severity` field's `"error"|"warning"|"info"` ladder where consumers tolerate new values) but WRONG for CLOSED discriminator Literals (`LintRuntimeWarning.category` which consumers exhaustively switch on). Refinement: distinguish closed-discriminator additions (bump) from open-ladder additions (don't bump).

- **KTD-6: R7 emit-shape canonical = lexicographically-smallest filename.** Deterministic across OS / CI / iteration order. Audited against buf's actual emit at U4 per [[audit-wire-format-before-claiming-sibling-parity]] — if buf emits differently, document divergence per [[buf-parity-divergence-documentation-discipline]] AND mirror buf's emit (parity-first when buf has a clear answer).

- **KTD-7: R7 module shape — single module `package_same.py`.** All 7 rules in one file mirrors `imports.py` (3 rules sharing a module). Easier to audit + maintain than 7 per-language modules. Parity fixtures co-locate at `tests/parity/fixtures/package/same-{lang}/`.

- **KTD-8: R6 5-rule family in one module.** `src/protokit/schema/lint/rules/options/deprecated_replacement.py` exposes all 5 RULES + the shared `_check_replacement_comment` helper. Each rule_id discriminates per ElementKind. Users demote per-kind via `[tool.protokit.lint.severities]`.

- **KTD-9: R6 severity `warning` at launch.** Heuristic-rule asymmetry: false positives on legitimate deprecation comments would block CI as `error`. Promotion to `error` is a D6c decision after corpus tuning. (Per brainstorm document review.)

- **KTD-10: R6 `source_spec=""` (empty) excludes from parity harness automatically.** `tests/parity/conftest.py:RULE_ID_MAP` auto-walks `BUILTIN_PACKS` and only includes rules whose `source_spec` starts with `"buf:"`. R6 has no buf analogue; empty `source_spec` is the clean opt-out signal.

## Open Questions

### Resolved During Planning

- **R6 sub-rule module structure** → Single `deprecated_replacement.py` with all 5 RULES + shared helper (KTD-8).
- **R7 module shape** → Single `package_same.py` (KTD-7).
- **R7 sanitization scope** → Apply `_safe_for_stderr` to all string-typed params in R7 findings (defense-in-depth; [[module-name-newline-injection-stderr-forge]]).
- **Bump-contract reconciliation** → Refine the docstring (KTD-5).
- **FileLintContext field vs compile_result reference** → Direct field (KTD-2).
- **R6 worked-example placement** → Inline in README's "Schema Linting" section under a new "Worked example: comment-aware lint" subsection (U7).

### Deferred to Implementation

- **R6 regex set finalization** — `/use\s+[\w.]+\s+instead/i` family is the starting point. U3 builds a fixture corpus of real-world deprecation comments (googleapis, protobuf style guides) and finalizes the regex set with measured precision. Severity stays `warning` regardless.
- **R6 comment-length truncation bound** — 500-char prefix is the working bias. U3 measures comment-length distribution against the real corpus and picks a concrete threshold.
- **R7 NULL semantics** — Does `option go_package` absent on file A count as "agrees with file B's declared value" (silent) or "disagrees" (fires)? U4 audits buf's actual emit on mixed-presence fixtures and documents the chosen semantics per [[buf-parity-divergence-documentation-discipline]].
- **CompileResult consumer audit** — U2 audits all `CompileResult` callers (internal + tests) for positional unpacking, equality, repr usage. Mapping field's hash-exclusion only required if hash usage surfaces.
- **Cross-protobuf-runtime verification** — U1 verifies byte-identical `source_code_info` emission across protobuf 4 + 5 (both backends).

## Output Structure

```
src/protokit/schema/lint/rules/
├── options/                              # NEW directory
│   ├── __init__.py                       # NEW (empty or re-exports)
│   ├── _comments.py                      # NEW (leading_comment free function)
│   └── deprecated_replacement.py         # NEW (5 rules + _check_replacement_comment helper)
└── package_same.py                       # NEW (7 PACKAGE_SAME_* rules)

tests/schema/lint/rules/
├── options/                              # NEW directory
│   ├── __init__.py                       # NEW
│   ├── test_comments.py                  # NEW (leading_comment unit tests)
│   └── test_deprecated_replacement.py    # NEW (R6 family rule tests + adversarial newline)
└── test_package_same.py                  # NEW (R7 family rule tests + adversarial newline)

tests/parity/fixtures/package/
├── same-go-package/
│   ├── good.proto                        # NEW
│   ├── bad-value.proto                   # NEW
│   ├── bad-presence.proto                # NEW
│   └── buf.yaml                          # NEW
├── same-java-package/                    # ... (same shape as same-go-package)
├── same-csharp-namespace/                # ...
├── same-php-namespace/                   # ...
├── same-ruby-package/                    # ...
├── same-swift-prefix/                    # ...
└── same-java-multiple-files/             # ...

tests/parity/test_parity_package_same.py  # NEW
```

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

### Data flow: source_info_descriptors from compile to rule

```
User invokes `protokit lint` (CLI)
    │
    ▼
src/protokit/schema/lint/cli.py
    calls compile_protos_to_result(paths, ..., include_source_info=True)
    │
    ▼
src/protokit/schema/compile.py:compile_protos_to_result(include_source_info=True)
    │
    ├─→ _compile_with_protoxy(..., include_source_info=True)
    │   protoxy.compile(include_source_info=True) → fds
    │   For each fd in fds.file:
    │     pool.Add(fd)              # ← pool.Add() DISCARDS source_code_info
    │   Build source_info_descriptors[fd.name] = fd   # ← BEFORE pool.Add discards it
    │   return (pool, root_names, source_info_descriptors)
    │
    └─→ _compile_with_protoc(..., include_source_info=True)
        cmd = ["protoc", ..., "--include_source_info"]
        Parse FileDescriptorSet from subprocess output
        Build source_info_descriptors dict (same pattern)
        return (pool, root_names, source_info_descriptors)
    │
    ▼
CompileResult(pool=..., root_files=..., diagnostics=..., source_info_descriptors=source_info_descriptors)
    │
    ▼
src/protokit/schema/lint/engine.py:LintEngine.run(compile_result)
    │
    ├─ Step 3.5 (NEW pre-walk pass)
    │   package_options = {}
    │   for fname in sorted(compile_result.root_files):
    │     fd_proto = compile_result.source_info_descriptors.get(fname)
    │     pkg = fd_proto.package
    │     for opt in ("go_package", "java_package", ...):
    │       package_options.setdefault(pkg, {})[opt] = getattr(fd_proto.options, opt) or None
    │
    ├─ Step 4 (walk root_files; build FileLintContext per file)
    │   ctx = _build_file_ctx(
    │     ...,
    │     source_info_descriptors=compile_result.source_info_descriptors,    # ← injected
    │     package_options=package_options,                      # ← injected
    │   )
    │
    └─ R6 / R7 rules consume:
        R6: leading_comment(ctx.source_info_descriptors, ctx.file.name, ctx.location.path)
        R7: ctx.package_options[ctx.file.package][option_name]
```

### Bump-contract docstring refinement (KTD-5)

```text
BEFORE (src/protokit/formatters/_builtin_lint.py:243-249):
    Adding new severity-level / category strings to an existing
    enum field does NOT bump the version (the field's meaning is
    unchanged; the enum just gains a value).

AFTER:
    Bump-trigger refinement:
    - Open severity-string ladders (e.g., "error" / "warning" / "info"
      where consumers tolerate new values gracefully) — additions DO
      NOT bump the version.
    - Closed Literal discriminators (e.g., LintRuntimeWarning.category
      where consumers exhaustively switch on the value) — additions
      DO bump the version, because every consumer must extend their
      switch / match to handle the new case.
```

### R6 rule structure (per-ElementKind, shared helper)

```text
src/protokit/schema/lint/rules/options/deprecated_replacement.py

Module structure:
    _REPLACEMENT_PATTERNS: tuple[re.Pattern, ...] = (
        re.compile(r"use\s+[\w.]+\s+instead", re.IGNORECASE),
        re.compile(r"replaced\s+by\s+[\w.]+", re.IGNORECASE),
        re.compile(r"see\s+[\w.]+", re.IGNORECASE),
    )

    def _check_replacement_comment(text: str | None) -> bool:
        if text is None:
            return False
        return any(p.search(text) for p in _REPLACEMENT_PATTERNS)

    @lint_rule(rule_id="options/deprecated-field-must-have-replacement-comment",
               element=ElementKind.FIELD,
               profiles=("default",),
               severity=LintSeverity.WARNING,
               source_spec="")  # protokit-only; excluded from parity harness
    def check_deprecated_field_replacement_comment(ctx: FieldLintContext) -> None:
        if not ctx.field.options.deprecated:
            return
        comment = leading_comment(ctx.source_info_descriptors, ctx.file.name, ctx.location.path)
        if not _check_replacement_comment(comment):
            ctx.emit(violation_kind="missing_replacement_comment",
                     params={"comment": _safe_for_stderr((comment or "")[:500])})

    # ... same shape for enum-value, method, message, enum

    RULES = (check_deprecated_field_..., check_deprecated_enum_value_..., ..., ...)
```

## Implementation Units

- [ ] **Unit 1: R6a — SourceCodeInfo opt-in parameter + 3-tuple backend signatures**

**Goal:** Add `include_source_info: bool = False` parameter to `compile_protos_to_result` and both backend functions. Backend return signatures widen to 3-tuple. Cross-protobuf-runtime verification step.

**Requirements:** R6a.

**Dependencies:** None (foundation unit).

**Files:**
- Modify: `src/protokit/schema/compile.py` (compile_protos_to_result signature + threading; CompileResult dataclass gets `source_info_descriptors` field — see also U2 which extends this)
- Modify: `src/protokit/_cli_utils.py` (`_compile_with_protoxy` line 219 — flip `include_source_info=False` to `include_source_info=include_source_info` parameter; `_compile_with_protoc` line 275 — append `--include_source_info` to cmd at line 305 when flag is True; both return 3-tuple including raw FDS-derived `source_info_descriptors` dict)
- Modify: `src/protokit/_cli_utils.py:251-258` byte-equivalence comment — update to reflect "both backends carry source-location info when requested; bytes still byte-equivalent across backends when `include_source_info=True`"
- Test: `tests/test_compile_include_source_info.py` (NEW) — verifies opt-in parameter threading, source_info_descriptors populated on True, None on False, cross-backend byte-identical contents

**Approach:**
- Both backends thread the new parameter atomically (preserves byte-equivalence-between-backends invariant).
- Default False on all signatures preserves D1-D5 backward compatibility for non-lint consumers (compat, codegen, direct API).
- Cross-runtime verification: build descriptor set with `include_source_info=True` against protobuf 4 + protobuf 5 (current dev environment); assert identical `source_code_info.location[]` for the same fixture.

**Execution note:** Test-first for the cross-runtime verification — write the protobuf-version-pinned tests before flipping the parameter so the regression bar is set.

**Patterns to follow:**
- Existing parameter threading in `compile_protos_to_result` (proto_paths handling at compile.py:327-330).
- Backend dispatch pattern at compile.py:402, 420, 422 (5 instantiation sites of CompileResult — early-return paths at lines 374, 380, 396 will pass `source_info_descriptors=None`).

**Test scenarios:**
- *Happy path:* `compile_protos_to_result(paths, include_source_info=True)` returns a CompileResult where `source_info_descriptors` is a non-empty Mapping for each input file.
- *Happy path:* `compile_protos_to_result(paths, include_source_info=False)` (default) returns CompileResult where `source_info_descriptors is None`.
- *Edge case:* protoxy backend with `include_source_info=True` against a .proto containing leading comments — the source_info_descriptors entries have populated `source_code_info.location` arrays.
- *Edge case:* protoc backend with `include_source_info=True` against the same .proto — byte-identical `source_code_info.location` arrays vs protoxy.
- *Edge case:* Mixed protobuf 4 + 5 runtimes — byte-identical `source_code_info` emission (cross-version pin per [[copytoproto-round-trip-for-proto-form-only-descriptor-fields]]).
- *Error path:* `include_source_info=True` against a .proto with syntax errors — CompileResult diagnostics non-empty; `source_info_descriptors is None` (early-return path preserved).
- *Edge case:* Empty input paths — CompileResult is empty; `source_info_descriptors is None`.
- *Integration:* Existing D1-D5 tests that call `compile_protos_to_result` without the new parameter continue passing (default False preserves zero-cost contract).

**Verification:**
- `compile_protos_to_result(paths, include_source_info=True)` returns CompileResult.source_info_descriptors as a non-empty Mapping.
- Default-False path produces byte-identical CompileResult output to pre-D6b.
- Cross-runtime + cross-backend byte equivalence verified.
- No D1-D5 test regressions.

---

- [ ] **Unit 2: R6b — CompileResult.source_info_descriptors field + FileLintContext.source_info_descriptors field + leading_comment free function + CompileResult consumer audit**

**Goal:** Add `CompileResult.source_info_descriptors: Mapping[str, FileDescriptorProto] | None` field with `__post_init__` snapshot. Add `FileLintContext.source_info_descriptors` engine-injected field (single-context addition; no other 7 contexts touched). Module-level `leading_comment(source_info_descriptors, file_name, path)` free function. Audit all CompileResult callers.

**Requirements:** R6b.

**Dependencies:** Unit 1.

**Files:**
- Modify: `src/protokit/schema/compile.py:145-187` (`CompileResult` dataclass — new field + `__post_init__` MappingProxyType snapshot following the existing root_files/diagnostics pattern)
- Modify: `src/protokit/schema/compile.py:327-454` (`compile_protos_to_result` — populate source_info_descriptors at all 5 CompileResult instantiation sites; early-return paths pass `None`)
- Modify: `src/protokit/schema/lint/model.py:957` (`FileLintContext` — single new field `source_info_descriptors: Mapping[str, FileDescriptorProto] | None`; engine-injected; placed BEFORE the three existing engine-injected fields `_emit_fn` / `_rule_id` / `_effective_severity` to preserve "engine-injected last" convention)
- Modify: `src/protokit/schema/lint/engine.py:609` (`_build_file_ctx` — passes `source_info_descriptors=compile_result.source_info_descriptors`)
- Create: `src/protokit/schema/lint/rules/options/__init__.py` (empty package marker)
- Create: `src/protokit/schema/lint/rules/options/_comments.py` (module-level `leading_comment(source_info_descriptors, file_name, path)` function)
- Modify: `tests/test_static_analysis.py:_LINT_PATHS` — add `src/protokit/schema/lint/rules/options/` per [[pytest-static-analysis-gate-ratchet]]
- Test: `tests/schema/lint/rules/options/__init__.py` (NEW, empty)
- Test: `tests/schema/lint/rules/options/test_comments.py` (NEW — leading_comment unit tests + adversarial newline)
- Test: `tests/schema/test_compile_result_source_info_descriptors.py` (NEW — CompileResult field tests + frozen-dataclass invariants)

**Approach:**
- `CompileResult.source_info_descriptors` defaults to `None` for backward compatibility. `__post_init__` wraps a non-None mapping in `MappingProxyType` per [[frozen-dataclass-mutable-fields-need-post-init-snapshot]].
- `FileLintContext.source_info_descriptors` field is engine-injected; same `None` semantic when `include_source_info=False`.
- `leading_comment(source_info_descriptors, file_name, path)`: walks `source_info_descriptors[file_name].source_code_info.location[]` looking for a Location whose `path` field matches the input. Returns `Location.leading_comments` or `None` (when source_info_descriptors is None, or file not in mapping, or no Location matches path).
- CompileResult consumer audit: grep callers for positional unpacking (`pool, root_files, diagnostics = result`), equality comparisons against goldens, repr-based assertions. Document findings in U2's commit message.

**Patterns to follow:**
- `CompileResult.__post_init__` at compile.py:177-187 for the MappingProxyType snapshot.
- `FileLintContext` field ordering at model.py:957-988 (engine-injected fields LAST convention).

**Test scenarios:**
- *Happy path:* `leading_comment(source_info_descriptors, "test.proto", (4, 0, 2, 0))` returns the leading comment text when source_info_descriptors is populated and Location matches.
- *Happy path:* `leading_comment(None, "test.proto", path)` returns `None` (defensive None handling).
- *Edge case:* file_name not in source_info_descriptors mapping → returns `None`.
- *Edge case:* path matches no Location in source_code_info → returns `None`.
- *Edge case:* CompileResult constructed with `source_info_descriptors=None` — frozen-dataclass invariants hold; `__post_init__` doesn't crash on None.
- *Edge case:* CompileResult constructed with `source_info_descriptors={"a.proto": fd_proto}` — `__post_init__` wraps in MappingProxyType; subsequent mutation attempt raises TypeError.
- *Adversarial path:* `leading_comment` returns a string containing `\n` characters or U+2028 — caller must sanitize before wire-format emission (verified in U3's test).
- *Integration:* Engine builds FileLintContext with `source_info_descriptors` injected; rule body calls `leading_comment(ctx.source_info_descriptors, ctx.file.name, ctx.location.path)` end-to-end without errors.

**Verification:**
- `CompileResult.source_info_descriptors` field accessible via `result.source_info_descriptors`.
- `FileLintContext.source_info_descriptors` field accessible via `ctx.source_info_descriptors`.
- `leading_comment` returns expected values for all 8 test scenarios above.
- CompileResult consumer audit finds no breakages; documented in commit message.

---

- [ ] **Unit 3: R6 — 5-rule deprecated-replacement family + inline _safe_for_stderr reuse**

**Goal:** Ship 5 `@lint_rule` functions sharing `_check_replacement_comment` helper. Severity `warning`. Profile `default` only. Each rule emits `params={"comment": _safe_for_stderr(comment_text[:500])}` for adversarial-safe wire format.

**Requirements:** R6, R6c.

**Dependencies:** Unit 2.

**Files:**
- Create: `src/protokit/schema/lint/rules/options/deprecated_replacement.py` (5 rules + helper + `RULES` tuple)
- Modify: `src/protokit/schema/lint/rules/__init__.py:84` (`BUILTIN_PACKS` — append `deprecated_replacement` module)
- Modify: `tests/schema/lint/test_builtin_packs.py:79` (membership-pin test — extend `expected` tuple per [[pytest-static-analysis-gate-ratchet]]'s ratchet pattern)
- Test: `tests/schema/lint/rules/options/test_deprecated_replacement.py` (NEW — 5-rule family tests + adversarial fixture)
- Test: `tests/schema/lint/rules/options/fixtures/` (NEW — small .proto corpus for tests)

**Approach:**
- 5 rules, one per `*Options.deprecated` ElementKind (FIELD, ENUM_VALUE, METHOD, MESSAGE, ENUM). Each rule_id: `options/deprecated-{kind}-must-have-replacement-comment`.
- Shared module-level `_REPLACEMENT_PATTERNS` tuple of compiled regexes (regex set finalized at U3 against the fixture corpus — implementation-time discovery per Open Questions).
- Shared `_check_replacement_comment(text: str | None) -> bool` helper.
- Each rule reads `*Options.deprecated` flag; if True, calls `leading_comment(ctx.source_info_descriptors, ctx.file.name, ctx.location.path)`; passes result to helper; on False return, emits a finding.
- Sanitization: comment text truncated to 500-char prefix, passed through `_safe_for_stderr`, included in `params` for human-readable rendering. The 500-char cap prevents adversarial protos with multi-KB comments from bloating wire-format output.
- `source_spec=""` (empty) on all 5 rules excludes them from parity harness per KTD-10.
- Each rule's docstring documents the protokit-original status (no buf analogue) per [[buf-parity-divergence-documentation-discipline]].

**Execution note:** Build the regex corpus + finalize `_REPLACEMENT_PATTERNS` first against a real-world corpus (googleapis, protobuf style guides); then write rules using the finalized regex set.

**Patterns to follow:**
- `src/protokit/schema/lint/rules/naming.py` (9-rule + shared-helper module pattern; closest analogue).
- `src/protokit/schema/lint/rules/imports.py` (FILE-element rule shape).
- Existing rule test pattern: `tests/schema/lint/rules/test_imports.py`.

**Test scenarios:**
- *Happy path:* `.proto` with `deprecated = true` field + leading comment "Use NewField instead." produces zero findings (helper recognizes the phrasing).
- *Happy path:* `.proto` with `deprecated = true` field + no leading comment produces exactly one `options/deprecated-field-must-have-replacement-comment` finding at `warning` severity.
- *Edge case:* `.proto` with `deprecated = true` field + leading comment "deprecated" (no replacement phrasing) — fires finding.
- *Edge case:* `.proto` with `deprecated = false` field + no comment — zero findings (rule only checks deprecated fields).
- *Edge case:* `.proto` without `include_source_info=True` (i.e., `source_info_descriptors is None`) — rule emits findings for every deprecated element without a comment (leading_comment returns None, helper returns False).
- *Per-ElementKind coverage:* 5 separate proto fixtures, one per ElementKind (field, enum-value, method, message, enum), each demonstrating happy-path + sad-path for that kind's rule.
- *Adversarial path:* `.proto` with `deprecated = true` field + leading comment containing `\n error[lint-evil]: forged` — finding emits sanitized comment in `params` (no newline injection into stderr).
- *Adversarial path:* `.proto` with multi-KB comment — finding emits 500-char truncated + sanitized comment.
- *Integration:* `protokit lint --profile default <fixture>` produces expected findings end-to-end across all 5 rules; `protokit lint --profile recommended <fixture>` produces zero R6 findings (R6 not in recommended).
- *Integration:* `[tool.protokit.lint.severities]` per-rule demotion to `info` works for any of the 5 rule_ids.

**Verification:**
- 5 new rule_ids registered; visible via `protokit lint --no-color --profile default --format=json <fixture>` output.
- BUILTIN_PACKS membership-pin test passes with extended tuple.
- All test scenarios above pass.
- Adversarial fixtures produce sanitized output (no control chars or newline escapes in stderr).

---

- [ ] **Unit 4: R7 — PACKAGE_SAME_* family + engine pre-walk accumulator + FileLintContext.package_options field**

**Goal:** Ship 7 PACKAGE_SAME_* rules under `protokit.schema.lint.rules.package_same`. Engine adds a pre-walk pass building `package_options: dict[str, dict[str, str | None]]` accumulator. `FileLintContext.package_options` field injected by engine. Each rule reads its specific FileOptions field. Canonical = lexicographically-smallest filename.

**Requirements:** R7.

**Dependencies:** Unit 2 (FileLintContext shape; same dataclass touched in U2 and U4 to add both `source_info_descriptors` and `package_options` fields).

**Files:**
- Create: `src/protokit/schema/lint/rules/package_same.py` (7 rules + shared helper structure)
- Modify: `src/protokit/schema/lint/rules/__init__.py:84` (`BUILTIN_PACKS` — append `package_same` module; updates the membership-pin test tuple)
- Modify: `src/protokit/schema/lint/model.py:957` (`FileLintContext` — add `package_options: Mapping[str, Mapping[str, str | None]] | None` field; engine-injected; positioned BEFORE engine-injected last three)
- Modify: `src/protokit/schema/lint/engine.py:261-401` (`LintEngine.run` — insert Step 3.5 pre-walk pass between line 377 and line 379; populate `package_options` dict from `compile_result.source_info_descriptors`)
- Modify: `src/protokit/schema/lint/engine.py:609` (`_build_file_ctx` — passes `package_options=...` to FileLintContext constructor)
- Modify: `tests/schema/lint/test_builtin_packs.py:79` (membership-pin test — extend `expected` tuple again)
- Test: `tests/schema/lint/rules/test_package_same.py` (NEW — 7-rule family tests + adversarial fixture)
- Test: `tests/schema/lint/test_engine_pre_walk.py` (NEW — engine pre-walk accumulator unit tests, including iteration-order determinism)

**Approach:**
- Pre-walk pass: iterates `sorted(compile_result.root_files)` (lexicographic sort for determinism per [[structural-pin-inspect-getsource-untestable-collision-branch]]). For each file, reads `source_info_descriptors[fname].options` and records `(go_package, java_package, csharp_namespace, php_namespace, ruby_package, swift_prefix, java_multiple_files)` into the accumulator keyed by `(package_name, option_name)`.
- Each rule reads `ctx.package_options[ctx.file.package][option_name]`. The accumulator was built once at engine.run startup; rules don't re-iterate files.
- Emit-shape: for each file whose value disagrees with the canonical value, emit one finding. Canonical = the value declared by the lexicographically-smallest filename in the package. Files that don't declare the option contribute `None` to the accumulator; whether `None` "agrees" or "disagrees" is finalized at U4 implementation time via buf-actual audit per [[audit-wire-format-before-claiming-sibling-parity]].
- All 7 rules: `source_spec="buf:PACKAGE_SAME_<NAME>"`, `severity=LintSeverity.ERROR`, `profiles=("recommended", "default")`.
- Sanitization: each finding's `params` (file_name, option_value, canonical_value) passes through `_safe_for_stderr` (defense-in-depth per [[module-name-newline-injection-stderr-forge]] — adversarial option values could contain newlines).

**Execution note:** Build the pre-walk accumulator as test-first. The accumulator's iteration order + canonical-value computation are correctness-critical and benefit from explicit unit tests before rules consume them.

**Patterns to follow:**
- `src/protokit/schema/lint/rules/imports.py` (3 FILE-element rules sharing module — closest R7 shape).
- Pre-walk pass placement: between `engine.py:377` (group_by_kind bucketing) and `engine.py:379` (root_files walk).

**Test scenarios:**
- *Happy path:* 3-file proto package, all files declare `go_package = "github.com/x/y"` — zero `package/same-go-package` findings.
- *Happy path:* 3-file package, all 3 omit `go_package` — zero findings (all agree on None).
- *Sad path:* 3-file package: `a.proto` declares `go_package = "github.com/x/y"`, `b.proto` declares `go_package = "github.com/x/z"`, `c.proto` agrees with `a.proto` — `b.proto` emits one finding (canonical = a.proto's value).
- *Edge case (NULL semantic — finalized at U4):* `a.proto` declares `go_package = "github.com/x/y"`, `b.proto` omits the option — does `b.proto` emit? Decided by U4 buf audit; test reflects the decision.
- *Per-rule coverage:* 7 separate fixture sets, one per PACKAGE_SAME_* rule.
- *Edge case:* Different packages — `a.proto` in pkg `foo.bar` declares one value, `c.proto` in pkg `foo.baz` declares different value — zero findings (rule scope is per-package).
- *Edge case:* Single-file package — zero findings (no disagreement possible).
- *Adversarial path:* `option go_package = "foo.bar\n error[lint-evil]: forged"` — finding emits sanitized option_value in `params`.
- *Integration:* `protokit lint --profile recommended <multi-file fixture>` produces expected R7 findings end-to-end; `protokit lint --no-builtin-rules` produces zero R7 findings.
- *Engine pre-walk iteration-order pin (structural):* `inspect.getsource(LintEngine.run)` contains `sorted(compile_result.root_files)` pattern at the pre-walk pass per [[structural-pin-inspect-getsource-untestable-collision-branch]].

**Verification:**
- 7 new rule_ids registered.
- BUILTIN_PACKS membership-pin test passes with extended tuple.
- Pre-walk accumulator correctly populated; iteration order deterministic.
- All 7 rules fire on `bad-value.proto` fixtures; zero findings on `good.proto`.
- NULL semantic test cases reflect U4's audit decision.
- Adversarial sanitization verified.

---

- [ ] **Unit 5: R9 — severities_unloaded_rule Literal widening + schema_version bump 0.2 → 0.3 + bump-contract docstring refinement**

**Goal:** Widen `LintRuntimeWarning.category` Literal to 5 values. Switch CLI emit site from `"unloaded_rule"` to `"severities_unloaded_rule"` per U9 KTD-2 resolution. Bump `_LINT_JSON_SCHEMA_VERSION` 0.2 → 0.3. Refine the bump-contract docstring to distinguish closed-discriminator additions (bump) from open-ladder additions (don't bump).

**Requirements:** R9, R9-bump.

**Dependencies:** None (independent of R6/R7).

**Files:**
- Modify: `src/protokit/schema/lint/model.py:344, 492-497` (`LintRuntimeWarning.category` Literal — add `"severities_unloaded_rule"` as 5th value; update Literal docstring listing all 5)
- Modify: `src/protokit/schema/lint/cli.py:1062-1090` (CLI emit site — switch `category="unloaded_rule"` to `category="severities_unloaded_rule"`; update inline comment explaining the split)
- Modify: `src/protokit/formatters/_builtin_lint.py:250` (`_LINT_JSON_SCHEMA_VERSION = "0.2"` → `"0.3"`)
- Modify: `src/protokit/formatters/_builtin_lint.py:243-249` (bump-contract docstring refinement per KTD-5)
- Modify: `TODOS.md` (retire the U9 KTD-2 `severities_unloaded_rule` backlog item — replace with "Shipped in D6b 0.3.0")
- Test: `tests/schema/lint/cli/test_severities_unloaded_rule_category.py` (NEW — verify CLI emit produces new category value; verify engine emit still produces `"unloaded_rule"` for the original case)
- Test: `tests/test_builtin_lint_schema_version.py` (existing test — update expected version string from `"0.2"` to `"0.3"`)

**Approach:**
- Literal widening is additive; no existing consumer of the engine emit path breaks (`"unloaded_rule"` still emitted for the engine case). CLI consumers gain a new value to switch on.
- The 3-site discipline per [[semantic-category-conflation-accepted-tradeoff-literal-widening]]: Literal docstring (model.py) + emit-site inline comment (cli.py) + TODOS.md retirement.
- Bump-contract docstring refinement: distinguish closed-discriminator Literals (bump trigger) from open severity-string ladders (not bump trigger). This is REQUIRED — without it, the docstring contradicts the bump action.
- Schema version constant edit cascades to both consumption sites (`lint_json:329`, `lint_sarif:673`) via the single constant.

**Patterns to follow:**
- The 3-site discipline documentation pattern from D6a U9 KTD-2 commits.
- D6a U10's CHANGELOG section structure for the version-bump communication contract.

**Test scenarios:**
- *Happy path:* `[tool.protokit.lint.severities] "nonexistent-rule" = "warning"` invocation produces a `LintRuntimeWarning(category="severities_unloaded_rule", ...)` in lint_json output (not `"unloaded_rule"`).
- *Happy path:* Engine-side unloaded-rule case (rule in profile but not in BUILTIN_PACKS) still produces `category="unloaded_rule"` (no regression for that path).
- *Edge case:* `lint_json["schema_version"] == "0.3"` after the bump.
- *Edge case:* `lint_sarif`'s `runs[].properties.lint_schema_version == "0.3"` (cross-format parity per [[cross-format-enum-string-parity]]).
- *Edge case:* `lint_human` and `lint_junit` formatters unchanged by the bump (schema_version is JSON/SARIF only).
- *Integration:* Existing tests asserting `category="unloaded_rule"` for the CLI emit site (if any) update to `"severities_unloaded_rule"`.
- *Documentation:* Bump-contract docstring contains the refined wording distinguishing closed Literals from open ladders.
- *Documentation:* TODOS.md no longer lists the severities_unloaded_rule backlog item.

**Verification:**
- 5 Literal values present in model.py.
- CLI emit produces new category value.
- Engine emit still produces original category value.
- schema_version reads `"0.3"` in both formatters.
- Bump-contract docstring refined.
- TODOS.md updated.

---

- [ ] **Unit 6: Parity test infrastructure — R7 PACKAGE_SAME_* fixtures + parity-job verification**

**Goal:** Add `tests/parity/fixtures/package/same-{lang}/` fixture sets (7 rules × 3 fixtures = 21 protos) + `test_parity_package_same.py` module + adversarial fixture coverage. R6 rules are automatically excluded from parity (empty `source_spec`).

**Requirements:** R10.

**Dependencies:** Unit 4 (R7 rules must exist for parity comparison).

**Files:**
- Create: `tests/parity/fixtures/package/same-go-package/{good,bad-value,bad-presence}.proto` + `buf.yaml`
- Create: `tests/parity/fixtures/package/same-java-package/...`
- Create: `tests/parity/fixtures/package/same-csharp-namespace/...`
- Create: `tests/parity/fixtures/package/same-php-namespace/...`
- Create: `tests/parity/fixtures/package/same-ruby-package/...`
- Create: `tests/parity/fixtures/package/same-swift-prefix/...`
- Create: `tests/parity/fixtures/package/same-java-multiple-files/...`
- Create: `tests/parity/test_parity_package_same.py` (NEW — uses `assert_parity` from conftest.py:555)
- Modify: `tests/parity/conftest.py` if new exceptions or fixture-inventory updates needed (verify `RULE_ID_MAP` auto-walker picks up R7 rules without manual intervention)

**Approach:**
- Each rule's fixture set: `good.proto` (all files in package declare the same value), `bad-value.proto` (one file disagrees), `bad-presence.proto` (one file omits the option). 7 × 3 = 21 fixtures.
- `buf.yaml` per fixture set enables the specific PACKAGE_SAME_* rule.
- Parity test module follows the pattern of `test_parity_imports.py` etc. — `pytestmark = pytest.mark.parity` at module top.
- Adversarial fixtures (`_evil_option_value.proto`) co-located OR in a shared `tests/parity/fixtures/_security/` subdirectory; called out in security-test infrastructure.

**Patterns to follow:**
- `tests/parity/test_parity_imports.py` (closest module shape — 3 rules, FILE-element).
- `tests/parity/conftest.py:assert_parity` invocation pattern.
- Existing fixture conventions at `tests/parity/fixtures/imports/no-public/good.proto`.

**Test scenarios:**
- *Happy path:* All 21 `good.proto` fixtures produce zero findings in both buf and protokit.
- *Sad path:* Each `bad-value.proto` produces matching finding sets between buf and protokit (rule_id, severity, line, column-or-near-equivalent).
- *Sad path:* Each `bad-presence.proto` produces matching finding sets (assuming U4's NULL semantic decision matches buf).
- *Buf-divergence path:* If U4's audit reveals R7 emits differently than buf, the divergence is documented per [[buf-parity-divergence-documentation-discipline]] AND the fixture's parity-test asserts the divergence rather than expecting parity.
- *Adversarial path:* `_evil_option_value.proto` doesn't crash protokit; finding output is sanitized.
- *Integration:* `pytest tests/parity/ -m parity` runs the new module + buf binary in CI parity job.

**Verification:**
- 7 fixture sets created (21 protos + 7 buf.yaml).
- Parity job passes for all 7 PACKAGE_SAME_* rules.
- `RULE_ID_MAP` auto-discovery includes the 7 new rule_ids.
- Adversarial fixtures don't crash; output sanitized.

---

- [ ] **Unit 7: Delivery boundary (D6b → 0.3.0)**

**Goal:** Land the D6b delivery as one cohesive commit per [[delivery-boundary-unit-commit-composition]]: version bump 0.2.0 → 0.3.0 + CHANGELOG D6b section + README Schema Linting refresh (R6 worked example, new rule families enumerated, Public Surface DRAFT row updates) + TODOS.md D6b-shipped status + presence ratchets + stale-text sweep.

**Requirements:** R11, R12 + all institutional-discipline learnings.

**Dependencies:** Units 1-6.

**Files:**
- Modify: `pyproject.toml` (version `"0.2.0"` → `"0.3.0"`)
- Modify: `CHANGELOG.md:555` (insert `### D6b — protokit-lint option-aware path operational + 17/18 buf BASIC parity (0.3.0)` section between D6a section and Rationale; plain heading, no BREAKING prefix per [[pre-1.0-version-bump-as-communication-contract]])
- Modify: `README.md:480` (Schema Linting section — new rule counts: 17 + 5 R6 + 7 R7 + 0 R8-deferred = 29 rules total; new Worked Example subsection for R6; Profiles subsection updates with rule counts; demotion paths note R7's per-rule demotion via `[severities]`)
- Modify: `README.md:740-779` (Public Surface DRAFT — new rows for `CompileResult.source_info_descriptors` (INTERNAL), `FileLintContext.source_info_descriptors` (INTERNAL), `FileLintContext.package_options` (INTERNAL), `compile_protos_to_result(include_source_info=)` (IN), 5 R6 rule_ids (IN), 7 R7 rule_ids (IN); update `LintRuntimeWarning.category` row to enumerate all 5 values; update `lint_json["schema_version"]: "0.2"` → `"0.3"` at line 760 + line 763)
- Modify: `TODOS.md` (D6a section marked SHIPPED → D6b section added; D6b status SHIPPED at this commit; D6c agenda includes `package/same-directory`, `strict` profile, R9b, expanded option-aware pack, per-file rule overrides)
- Test: `tests/test_changelog_d6b_entry.py` (NEW — presence ratchet asserting `"D6b"` heading in CHANGELOG.md per [[presence-ratchet-test-pattern-for-prose-substrings]])
- Test: `tests/test_bump_contract_refinement.py` (NEW — presence ratchet asserting the refined bump-contract docstring substring in `_builtin_lint.py:243-249` per [[presence-ratchet-test-pattern-for-prose-substrings]])
- Test: `tests/test_r6_protokit_only_status.py` (NEW — presence ratchet asserting each of the 5 R6 rule docstrings mentions "protokit-only" or equivalent)

**Approach:**
- Mirrors D6a U10's shape (commit `1b59cae`): version bump + CHANGELOG + README + Public Surface DRAFT + presence ratchets + stale-text sweep in one commit per [[delivery-boundary-unit-commit-composition]].
- CHANGELOG D6b section enumerates: R6 family (5 rules, default profile, warning severity), R7 family (7 rules, recommended + default, error severity), R9 severities_unloaded_rule category, R9 schema_version bump 0.2 → 0.3, include_source_info opt-in parameter, demotion paths for users who don't want new findings.
- README Worked Example for R6: show a sample `.proto` with `field deprecated = true` + a comment that satisfies/doesn't satisfy the heuristic; show the resulting `warning` finding.
- Stale-text sweep per [[stale-forward-looking-text-cli-help-agent-discoverability]]: canonical grep targets (`D6b`, `forthcoming`, `arrives in`, `will add`, `deferred to D6a`) across `src/protokit/schema/lint/`, README, CHANGELOG, KD docstrings; triage rubric applied.
- Presence ratchets: D6b CHANGELOG heading substring; bump-contract docstring refinement substring; R6 "protokit-only" docstring substring per rule (5 rules) — each ratchet is a trivial substring assertion against one file per the pattern.

**Patterns to follow:**
- D6a U10 commit `1b59cae` for the boundary-unit shape.
- D6a CHANGELOG section structure at `CHANGELOG.md:435-554` as the template for the D6b section.

**Test scenarios:**
- *Happy path:* `pyproject.toml` reads `version = "0.3.0"`.
- *Happy path:* CHANGELOG.md contains `### D6b` heading (presence ratchet).
- *Happy path:* README's Schema Linting section enumerates the new R6 + R7 families and total rule count.
- *Happy path:* Public Surface DRAFT contains rows for `source_info_descriptors`, `package_options`, `include_source_info` parameter, 12 new rule_ids, schema_version "0.3".
- *Happy path:* Bump-contract docstring contains refined wording distinguishing closed Literals from open ladders.
- *Happy path:* Each of the 5 R6 rule docstrings contains "protokit-only" or equivalent marker.
- *Edge case:* `protokit lint --version` reflects "0.3.0".
- *Stale-text sweep:* Canonical grep across `src/`, `tests/`, `docs/`, README.md, CHANGELOG.md produces no actually-stale forward-looking text matches (past-tense historical references and frozen planning artifacts are filtered per triage rubric).
- *Documentation:* TODOS.md "D6b backlog items" section is retired; "D6c backlog items" section added with deferred items.
- *Integration:* Full test suite (1536 + new D6b tests; expect 1750-1850 total) passes.

**Verification:**
- All presence-ratchet tests pass.
- Static-analysis ratchet passes on new D6b paths.
- Cold-import contract passes.
- BUILTIN_PACKS membership pin passes with 5+5+7 = 17 new rule entries (12 R6+R7 rules + 5 existing D6a packs unchanged).
- Full test suite passes.
- `protokit lint --version` reports "0.3.0".

## System-Wide Impact

- **Interaction graph:** R6a's `include_source_info` parameter threads through `compile_protos_to_result` → both compile backends. Pre-walk pass in `LintEngine.run` consumes `CompileResult.source_info_descriptors` to build per-package accumulator. R6/R7 rules consume `FileLintContext.source_info_descriptors` + `FileLintContext.package_options`. CLI emit site for `severities_unloaded_rule` in `cli.py:1062-1090` is the only emit-site change for R9.

- **Error propagation:** R6a's opt-in parameter doesn't change error paths; descriptor compilation failures still surface via existing `CompileResult.diagnostics`. R6/R7 rule exceptions remain captured by the engine guard (`(SystemExit, ValueError, TypeError, AttributeError, LookupError, LintRuleError)`).

- **State lifecycle risks:** New `FileLintContext.source_info_descriptors` and `FileLintContext.package_options` are engine-injected (built once per `LintEngine.run`, shared across all rules within a run). No persistent state. `CompileResult.source_info_descriptors`'s MappingProxyType snapshot at `__post_init__` prevents post-construction mutation.

- **API surface parity:** `compile_protos_to_result` API gains optional parameter; existing positional and keyword callers unchanged. CompileResult dataclass gains optional field; positional unpacking of all 4 fields would break — Unit 2's audit step identifies any such callers. Mapping field isn't naturally hashable but CompileResult is already de-facto unhashable due to `pool: DescriptorPool`, so no new hash regression.

- **Integration coverage:** Cross-formatter render parity for the new `severities_unloaded_rule` Literal value (4 formatters × 1 value). Cross-runtime byte-equivalent `source_code_info` emission (protobuf 4 + 5 × protoxy + protoc = 4 combinations).

- **Unchanged invariants:**
  - D1 cold-import contract: `import protokit.schema` still does NOT transitively load `protokit.schema.lint`. Verified by extension of existing test in U2.
  - D2 engine walker order: rules still emit in lex-by-full_name order within each ElementKind. Pre-walk pass runs BEFORE this loop, doesn't change the loop's behavior.
  - D3 CLI exit-code ladder: unchanged. R9c `--no-builtin-rules` + empty rule set still exits 2 via `no-rules`.
  - D4 formatter contract: `lint_human` / `lint_json` / `lint_junit` / `lint_sarif` dispatch unchanged. R9 adds a new `category` Literal value (additive); `_LINT_JSON_SCHEMA_VERSION` bump is mechanical.
  - D5 cross-formatter render parity: 5-value Literal renders consistently across all 4 formatters.
  - D6a BUILTIN_PACKS membership pin: extended in U3 and U4 via the established ratchet pattern.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| `include_source_info=True` under lint breaks D1-D5 tests hardcoding descriptor-set bytes | Audit affected tests in U1; non-lint shared-backend callers stay on the pre-D6b default, scoping impact to lint paths only |
| R6b's source_info_descriptors index doesn't survive `pool.Add()` ordering | Verified by D6a brainstorm's second-pass feasibility review + Phase 1 research: index built FROM raw set BEFORE pool consumes it. U2 includes an explicit assertion test. |
| R6 false-positive epidemic on legitimate deprecation comments using non-canonical phrasings | Severity `warning` at launch limits CI blast radius. Heuristic regex set tuned in U3 against representative corpus. Per-rule demotion via `[severities]` available. Promotion to `error` deferred to D6c. |
| R7 false positives on legitimate cross-language differences (vendor isolation, etc.) | Document each rule's heuristic limitations; users demote via `[severities]`. NULL semantics finalized at U4 against buf's actual emit. |
| Adversarial protos with multi-KB comments or option strings inflate descriptor-set + finding params | R6 truncates to 500 chars; R6+R7 sanitize via `_safe_for_stderr`. Mandatory adversarial test fixtures per [[module-name-newline-injection-stderr-forge]]. |
| Bump-contract docstring contradicted the brainstorm; not reconciling would leave the codebase inconsistent | KTD-5 refines the docstring in U5. Presence ratchet in U7 pins the refined wording. |
| Cross-protobuf-runtime divergence (4 vs 5) produces different lint findings | U1's cross-version verification step compares byte-identical emission before R6 lands. Divergence resolved or documented. |
| Brainstorm's "contexts already reference compile_result" claim was incorrect | Plan corrects to direct field on FileLintContext (KTD-2); single-field addition only (paralleling R7's package_options). |
| 5 CompileResult instantiation sites (not 1) require source_info_descriptors parameter | U2 explicitly enumerates all 5 sites; early-return paths pass None. |
| R7 emit-shape order non-determinism across OS/CI | Canonical = lexicographically-smallest filename (KTD-6); pre-walk iteration uses `sorted()` per [[structural-pin-inspect-getsource-untestable-collision-branch]]. |
| `severities_unloaded_rule` Literal addition is a wire-format change consumers must extend switch statements for | Bump-contract refinement (KTD-5) makes the rationale explicit. Schema_version bump 0.2 → 0.3 is the wire-format signal. |
| `_LintContextEmitMixin` minimal-surface invariant violated if leading_comment is added as a method | Free function chosen (KTD-3); mixin surface unchanged. |
| Stale text from D6a referring to "D6b will" becomes inaccurate after D6b ships | U7 invokes canonical sweep per [[stale-forward-looking-text-cli-help-agent-discoverability]] triage rubric. |

## Documentation / Operational Notes

- **CHANGELOG.md** — primary delivery doc; `### D6b — ...` section under Unreleased; plain heading per pre-1.0 stance; enumerates auto-load expansion (12 new rules), wire-format additions (`severities_unloaded_rule` category, schema_version 0.3, `include_source_info` parameter), demotion paths.
- **README.md** — Schema Linting section gains: new Worked Example subsection for R6, expanded rule-family enumeration (29 total rules now), Public Surface DRAFT row updates.
- **Public Surface DRAFT** — 12+ new rows per [[public-surface-draft-discipline-source-audit]]. Each grep-verified against source before shipping.
- **Inline rule docstrings** — each R7 rule documents its buf equivalent (`buf:PACKAGE_SAME_*`); each R6 rule documents its protokit-only status (no buf analogue) per [[buf-parity-divergence-documentation-discipline]].
- **TODOS.md** — D6a marked SHIPPED; D6b section added with shipped status; D6c agenda enumerates deferred items.
- **Memory updates** — after D6b ships, update `~/.claude/projects/.../memory/project_state.md` and `MEMORY.md` to reflect D6b complete.
- **No new docs/solutions/ entries during D6b** — those are captured at delivery boundary via `/ce:compound` (invoked post-U7 commit).

## Sources & References

- **Origin document:** docs/brainstorms/2026-05-14-protokit-lint-delivery-6b-option-aware-and-multi-language-requirements.md
- Reference plan: docs/plans/2026-05-12-001-feat-protokit-lint-d6a-rule-library-plan.md (D6a shape D6b mirrors)
- Reference scope tracker: TODOS.md "D6b backlog items surfaced during D6a"
- External: https://buf.build/docs/lint/rules (buf BASIC rule enumeration; pin to `_BUF_PARITY_PIN` reference)
- 19 institutional learnings cited inline (full mapping in research output)

### Next step

`/ce:work` per-unit starting with U1 (R6a SourceCodeInfo opt-in parameter).
