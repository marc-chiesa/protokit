---
title: D6b U3 — R6 deprecated-replacement family + lint CLI source-info wire-up
type: feat
status: active
date: 2026-05-15
origin: docs/brainstorms/2026-05-15-d6b-u3-r6-deprecated-replacement-family-requirements.md
---

# D6b U3 — R6 deprecated-replacement family + lint CLI source-info wire-up

## Overview

U3 lands the **first 5 lint rules that read proto source comments**, closing the U1+U2 plumbing chain with consumer code that demonstrates the option-aware capability end-to-end. The unit splits into **U3a** (5 R6 rules + proto-mode CLI source-info wire-up + `BUILTIN_PACKS` extension) and **U3b** (descriptor-set-mode CLI extension in `_load_descriptor_sets_to_result`). The split — resolved at planning time per scope-guardian + adversarial cross-persona findings — separates the lower-risk rule deliverable + 26-site test-assertion ratchet from the more invasive descriptor-set loader extension, while still landing the entire R6 family within the D6b delivery boundary at U7.

## Problem Frame

After U1 (commit threading `include_source_info` through `compile_protos_to_result`) and U2 (commit `2b487d1` threading `source_info_descriptors` through 5 R6 ElementKind contexts + `descriptor_path` + `leading_comment` helpers) shipped, the R6 plumbing chain is complete but unused. Two visible consequences:

- **The option-aware capability is unproved end-to-end.** No rule in `BUILTIN_PACKS` calls `leading_comment` on a real proto. The parent brainstorm's "differentiator claim" is unbacked.
- **The lint CLI never sets `include_source_info=True`.** The call site at `src/protokit/schema/lint/cli.py:731` uses the parameter's default (False), so every lint invocation gets `source_info_descriptors=None`. R6 rules would over-report if they shipped without the CLI flip.

U3 closes both gaps. The 5 R6 rules (one per `*Options.deprecated` ElementKind) demonstrate that protokit reads custom-option-aware schema policy via source comments; the CLI wire-up makes the capability functional in both proto mode and descriptor-set mode.

(See origin: `docs/brainstorms/2026-05-15-d6b-u3-r6-deprecated-replacement-family-requirements.md`)

## Requirements Trace

- **R6.** Ship 5 `@lint_rule`-decorated callables under `src/protokit/schema/lint/rules/options/deprecated_replacement.py`, one per `*Options.deprecated` ElementKind (FIELD, ENUM_VALUE, METHOD, MESSAGE, ENUM). All share a `_check_replacement_comment(text: str | None) -> bool` helper and a module-level `_REPLACEMENT_PATTERNS` tuple of compiled regexes. Severity `warning`, profile `default` only. Per-rule `source_spec=""` (empty) excludes them from the parity harness per [[KTD-10-source-spec-empty-string-excludes-from-parity]].
- **R6-CLI.** Wire `include_source_info=True` at the lint CLI's `compile_protos_to_result(...)` call (`cli.py:731`, proto mode) AND extend `_load_descriptor_sets_to_result` (`_cli_utils.py:259-403`, descriptor-set mode) to capture `FileDescriptorProto` references into a `source_info_descriptors` accumulator and pass to the `CompileResult(...)` constructor.
- **R6c.** Sanitize comment-derived `params["comment"]` inline via the existing `_safe_for_stderr(...)` helper at finding-construction. Truncate to 500-char prefix before sanitization. Pre-escape `{`/`}` after sanitization to keep `message_template` interpolation safe.
- **R6-pack.** Extend `BUILTIN_PACKS` at `src/protokit/schema/lint/rules/__init__.py:84` to include the new module; ratchet the membership-pin test at `tests/schema/lint/test_builtin_packs.py:79`.
- **R6-tests.** Per-ElementKind happy-path + sad-path coverage; adversarial fixture for multi-KB / control-char / U+2028 / U+2029 / `{`/`}` cases; integration test for CLI proto-mode + descriptor-set-mode end-to-end fires; per-rule severities demotion test.

## Scope Boundaries

- **U3 does NOT ship a runtime warning** for descriptor-set inputs that lack `source_code_info`. R6 rules silently over-report in that case (documented limitation in rule docstrings + U7 CHANGELOG). The brainstorm's Non-Goals decision is preserved at planning time — adding a `LintCompileDiagnostic` from `_load_descriptor_sets_to_result` would create loader-engine coupling worse than the documentation-only mitigation.
- **U3 does NOT ship user-configurable replacement-phrasing patterns.** The 4-pattern starting set (potentially expanded after corpus tuning at implementation time) ships fixed in U3a. User-configurable patterns deferred to D6c if user demand emerges.
- **U3 does NOT add a precision/recall ship-gate.** Severity `warning` bounds the false-positive blast radius. The implementer measures precision/recall on the canonical corpus (googleapis + grpc-proto + envoy + opentelemetry-proto) and records the result in U3a's commit message body — soft signal for future deliveries, not a hard ship-gate.
- **U3 does NOT promote R6 rules to `error` severity.** D6c decision after real-world miss/hit-rate measurement.
- **U3 does NOT ship R7 (PACKAGE_SAME_* family).** U4 (separate unit) covers cross-language parity.
- **U3 does NOT ship R9 (`severities_unloaded_rule` category split + wire-format `schema_version` bump).** U5 (separate unit).
- **U3 does NOT add the new R6 rule_ids to `README.md`'s Public Surface DRAFT section.** That lands at U7 (delivery boundary unit) per [[delivery-boundary-unit-commit-composition]].

### Deferred to Separate Tasks

- **Cross-protobuf-runtime byte-equivalence verification** (proto 4 vs proto 5 `source_code_info.location[]`). Already promised at parent plan lines 145, 308; deferred to U6 (parity test infra) where the test-matrix infrastructure exists.
- **`README.md` Worked Example for R6** (a sample `.proto` with `[deprecated = true]` + commentary + resulting `warning` finding). Lands at U7.
- **`CHANGELOG.md` D6b section** with R6 rule enumeration. Lands at U7.

## Context & Research

### Relevant Code and Patterns

- **Pattern modules to mirror:**
  - `src/protokit/schema/lint/rules/imports.py:1-260` — 3-rule + shared-module pattern; closest R6 shape for the 5-rule cluster. Use the `@lint_rule(..., message_template=...)` shape from `:64-93` as the canonical example.
  - `src/protokit/schema/lint/rules/naming.py:1-310` — 8-rule pattern with cross-ElementKind dispatch; useful for the per-ElementKind rule structure.
  - `src/protokit/schema/lint/rules/enum.py` — TYPE_CHECKING-guarded context imports (mirror for cold-import contract).
- **API surfaces to consume:**
  - `src/protokit/schema/lint/decorator.py:52-130` — `@lint_rule(rule_id, severity, profiles, element, message_template, source_spec)`. `message_template` is **required** (no default).
  - `src/protokit/schema/lint/model.py:918-923` — `ctx.emit(*, violation_kind: str, params: dict | None = None)`. No `message=` kwarg; the human-rendered message comes from `message_template.format(**params)`.
  - `src/protokit/schema/lint/rules/options/_comments.py` (shipped U2) — `descriptor_path(descriptor)` and `leading_comment(source_info_descriptors, file_name, path)` helpers.
  - `src/protokit/schema/lint/_cli_utils.py:198-256` — `_safe_for_stderr(value) -> str` + `_CONTROL_CHAR_TABLE`.
- **CLI call sites:**
  - `src/protokit/schema/lint/cli.py:731` — proto-mode `compile_protos_to_result(...)` call. U3a flips `include_source_info=True` here.
  - `src/protokit/schema/lint/_cli_utils.py:259-403` — `_load_descriptor_sets_to_result(...)`. U3b extends.
- **U1 prior art for capture-around-Add pattern:**
  - `src/protokit/_cli_utils.py:221-270` — `_populate_pool_with_capture(...)`. Critically, line 266 (`captured[fd.name] = fd`) precedes line 267 (`pool.Add(fd)`) — the PRE-ADD capture ordering. The docstring at lines 230-238 makes this load-bearing: `pool.Add()` consumes `source_code_info`, so capture must happen BEFORE Add. U3b applies the same ordering.
- **Pack curation:**
  - `src/protokit/schema/lint/rules/__init__.py:70-92` — `BUILTIN_PACKS: tuple[ModuleType, ...]` definition + import block.
  - `tests/schema/lint/test_builtin_packs.py:79` — membership-pin test; extend `expected` tuple.
- **Ratchet tests:**
  - `tests/schema/lint/test_cold_import_extended.py` — verify `import protokit.schema` doesn't transitively load `protokit.schema.lint.rules.options.deprecated_replacement`.
  - `tests/test_static_analysis.py:_LINT_PATHS` — append new source + test paths.
- **Affected proto-mode CLI tests** (re-counted post-review): **4 test files, 28 line-level `source_info_descriptors is None` / `is not None` references**. The brainstorm's "26 across 5 files" figure was slightly off — `tests/schema/lint/test_model.py` has zero matching sites (its 5 `'source_info_descriptors': None` entries are factory-function dict defaults, NOT `is None` assertions, and don't need any change). Per-file breakdown by actual grep:
  - `tests/test_cli_utils.py` (4 sites) — these are bucket (b), the only sites that actually flip under U3a's `cli.py:731` change because they exercise the proto-mode CLI call path.
  - `tests/schema/lint/test_compile_include_source_info.py` (20 sites) — these are bucket (a), intentional default-False contract tests calling `compile_protos_to_result(...)` DIRECTLY (not via the CLI). They MUST NOT change; they pin the U1-shipped contract that `include_source_info=False` (the parameter default) yields `source_info_descriptors is None`.
  - `tests/schema/lint/test_engine_source_info_descriptors_injection.py` (3 sites) — bucket (a), assert on `engine._current_source_info_descriptors is None` (engine-internal reentrancy state), unaffected by the CLI flip.
  - `tests/schema/lint/rules/options/test_comments.py` (1 site) — bucket (a), unit test of the U2 helper, unaffected.
  
  **Net U3a ratchet workload: ~4 sites flip in `test_cli_utils.py`**. The other 24 sites are intentional pinning of pre-U3 contracts and must NOT be touched. This recount weakens (but does not eliminate) one rationale for the U3a/U3b split; the bisectability + independent-failure-mode rationales still stand.

### Institutional Learnings

- **[[buf-parity-divergence-documentation-discipline]]** — R6 has no buf analogue. Each of the 5 rule docstrings documents this with a "Protokit-original — no buf analogue" closing line.
- **[[pytest-static-analysis-gate-ratchet]]** — new source + test paths added to `_LINT_PATHS` in the same commit they're created; `BUILTIN_PACKS` membership extends in the same commit as the new pack module.
- **[[delivery-boundary-unit-commit-composition]]** — U3a and U3b each follow per-unit commit shape (excluding the delivery-boundary cluster at U7).
- **[[no-raise-contract-extends-to-post-init-failures]]** — U3b passes a plain dict to `CompileResult(...)`; `__post_init__` wraps in `MappingProxyType` per the U1-established pattern at `src/protokit/schema/compile.py:225-229`.
- **[[ce-review-cross-reviewer-agreement-shared-misreading-false-positive-amplifier]]** — references to "U7 will add" / "U7 ships" in U3a/U3b docstrings use future tense, not present tense. The U3 commit messages note U7 as the delivery boundary unit.
- **[[apply-institutional-learnings-postdating-plan-during-ce-review]]** — `/ce:work` and `/ce:review` apply post-plan institutional learnings at each unit boundary.
- **[[frozen-dataclass-mutable-fields-need-post-init-snapshot]]** — `source_info_descriptors` is already snapshot at the `CompileResult` layer in U1; U3b passes a plain dict (re-wrap is automatic).

### External References

- Existing protobuf-python descriptor API (`google.protobuf.descriptor` + `descriptor_pb2`) is well-understood from U1/U2; no new external research needed.

## Key Technical Decisions

- **K-1 — Commit shape: SPLIT into U3a + U3b.** Scope-guardian + adversarial cross-persona finding. U3a (5 rules + proto-mode CLI wire-up + BUILTIN_PACKS extension + 26-site test ratchet) ships independently from U3b (descriptor-set loader extension + symmetric-mode tests). Bisectability gain at zero functional cost — U3b can land within hours of U3a if no issues.
- **K-2 — Single-file module shape for R6 family.** All 5 rules + `_check_replacement_comment` helper + `_REPLACEMENT_PATTERNS` tuple + `RULES` tuple co-located in `src/protokit/schema/lint/rules/options/deprecated_replacement.py`. Matches `imports.py` (3 rules) / `naming.py` (8 rules) / `enum.py` (multi-rule) precedent. The shared helper + patterns dominate the ergonomic case for co-location.
- **K-3 — Comment truncation length: 500 chars.** Resolves parent-brainstorm (200) vs parent-plan (500) discrepancy in favor of 500. Canonical deprecation comments often carry inline replacement-code snippets that 200 would truncate mid-context.
- **K-4 — Truncate-then-sanitize-then-escape order:** `_safe_for_stderr(comment_text[:500]).replace("{", "{{").replace("}", "}}")`. Truncation first (bounds per-call work), sanitization second (per-codepoint translation is order-independent), `{`/`}` escape last (protects `message_template.format(**params)` from KeyError on raw braces in comment text).
- **K-5 — `message_template` includes `{comment}` interpolation.** Better UX (rendered message shows the offending comment text). Resolves brainstorm Open Question. The pre-escape at the emit site (K-4) keeps `str.format()` safe.
- **K-6 — Pattern set ships fixed at U3a; user-configurable patterns deferred to D6c.** The 4-pattern starting set is the protokit identity statement; configurability if user demand emerges.
- **K-7 — Pool.Add invariant settled by U1 prior art (CAPTURE BEFORE ADD).** `_populate_pool_with_capture` at `src/protokit/_cli_utils.py:221-270` (specifically lines 264-267: `captured[fd.name] = fd` PRECEDES `pool.Add(fd)`) is the load-bearing precedent. The U1 docstring at lines 230-238 is explicit: *"`pool.Add()` consumes `source_code_info` regardless of the FileDescriptorProto's serialized state, so the capture must happen on the in-memory proto BEFORE Add is called."* U3b mirrors this ordering exactly — capture BEFORE the Add call.
- **K-8 — `source_info_descriptors` capture in `_load_descriptor_sets_to_result`: PRE-ADD insertion (corrected from initial post-review draft).** The `source_info_descriptors[fd.name] = fd` assignment happens BEFORE `pool.Add(fd)` is called — same ordering as U1's `_populate_pool_with_capture`. Sequence within the per-fd loop:
  ```
  for fd in fds.file:
      if fd.name in seen_names:               # dedup-skip
          duplicates.append(...)
          continue                            # never reaches capture or Add
      seen_names.add(fd.name)
      source_info_descriptors[fd.name] = fd   # ← capture FIRST
      try:
          pool.Add(fd)                        # ← consume after capture
      except (TypeError, ValueError):
          error_exit_with_code(...)           # SystemExit; partial state discarded
      root_files.append(fd.name)
  ```
  Dedup-skipped fds (line 352-364) skip both the capture and the Add — symmetric with `seen_names` invariant. On `pool.Add` failure, SystemExit discards the partial accumulator (the dict entry for the failed fd is unreachable to the caller). The dict's correctness invariant is therefore: every entry in `source_info_descriptors` corresponds to an fd that was successfully Add'd to the pool OR an fd whose Add raised SystemExit (in which case the whole CompileResult is never returned anyway).
- **K-9 — Descriptor-set-without-source-info runtime signal: defer to D6c.** Documentation-only mitigation in U3a's rule docstrings + U7's CHANGELOG. Adding a `LintCompileDiagnostic` from the loader would couple the loader to which rules are loaded — leaky abstraction worse than the disease.
- **K-10 — Precision/recall measurement: SOFT signal, not ship-gate.** U3a's implementation measures precision/recall on the corpus (googleapis + grpc-proto + envoy + opentelemetry-proto) and records the numbers in the commit message body. Severity `warning` bounds blast radius; no hard floor.
- **K-11 — TYPE_CHECKING-guarded context imports.** Mirror `imports.py:48-61` (eager-imports block lines 48-56 + `if TYPE_CHECKING:` block lines 58-61) / `naming.py` / `enum.py`. The 5 `*LintContext` type aliases (`FieldLintContext`, `EnumValueLintContext`, `MethodLintContext`, `MessageLintContext`, `EnumLintContext`) live under `if TYPE_CHECKING:`. Module-top eager imports: `re`, `lint_rule`, `ElementKind`, `LintSeverity`, `descriptor_path`, `leading_comment`, `_safe_for_stderr`. `from __future__ import annotations` enables the lazy resolution.
- **K-12 — Adversarial fixture composition: single shared `.proto` file** with multiple deprecated elements, each covering one adversarial concern (multi-KB comment, control chars, U+2028, raw `\n`, `{`/`}` characters). Reduces fixture file count; one fixture, multiple findings per run.

## Open Questions

### Resolved During Planning

- **Commit shape (atomic vs split)** — K-1 resolves: split into U3a + U3b.
- **Descriptor-set runtime signal** — K-9 resolves: defer to D6c.
- **Pattern-set extensibility** — K-6 resolves: fixed in U3a.
- **Precision/recall ship-gate** — K-10 resolves: SOFT signal only.
- **`message_template` `{comment}` policy + `{`/`}` escape** — K-4 + K-5 resolve: include `{comment}` in template; pre-escape `{`/`}` at emit site.
- **Comment-length bound** — K-3 resolves: 500 chars.
- **Module shape** — K-2 resolves: single file.
- **Pool.Add survival invariant** — K-7 resolves: settled by U1 prior art.
- **Capture ordering** — K-8 resolves: post-success insertion (symmetric with `root_files.append`).
- **TYPE_CHECKING discipline** — K-11 resolves: mirror `imports.py:48-61` (eager-imports block lines 48-56 + `if TYPE_CHECKING:` block lines 58-61).
- **Adversarial fixture composition** — K-12 resolves: single shared file.
- **Per-rule docstring shape** — Each rule's docstring opens with one paragraph describing the deprecated-replacement phrasing the rule expects, closes with "Protokit-original — no buf analogue" substring. The U7 presence ratchet asserts this substring across the 5 rules.

### Deferred to Implementation

- **Final regex pattern set.** Starting set is 4 patterns from the brainstorm: `\buse\s+[\w.]+\s+instead\b`, `\breplaced?\s+(?:by|with)\s+[\w.]+`, `\bmigrate\s+to\s+[\w.]+\b`, `\bsee\s+[\w.]+\s+for\s+(?:the\s+)?replacement\b` (all `re.IGNORECASE`). U3a's implementation: (1) extract deprecation comments from the canonical corpus; (2) measure precision/recall of the 4-pattern set; (3) add patterns only if precision stays high (~95%+) on real-world comments. Final pattern set + measurement recorded in U3a's commit message body.
- **Exact wording of each rule's `message_template`.** Starting template: `"deprecated {kind} {name!r} is missing a replacement comment (expected 'Use X instead.' or similar phrasing; got: {comment!r})"`. Fine-tuned per ElementKind during implementation; the U7 presence ratchet (lands at delivery boundary) asserts the canonical substring.
- **Adversarial fixture exact content.** The single shared adversarial fixture's exact `.proto` content (which characters in which leading comment) finalized at implementation time. Constraint: at least one deprecated element per adversarial concern from K-12.
- **Concrete enumeration of the 26 `source_info_descriptors is None` test sites.** Pre-counted at brainstorm time; implementer reads each site, classifies as (a) intentional default-False guard (no change), (b) proto-mode CLI assertion that flips (U3a ratchet), or (c) needs new fixture. The classification + per-line action recorded in U3a's commit message body.

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

### Data flow: comment → finding (U3a)

```
proto source     U2 helpers              R6 rule (NEW in U3a)
─────────────    ───────────────         ────────────────────────────────
field [deprecated=true]
  "Use NewField instead."
        │
        ▼
  CompileResult.source_info_descriptors  (U1 captured;
                                          flows through engine)
        │
        ▼
  ctx.source_info_descriptors            (U2 wired onto
                                          FieldLintContext et al.)
        │                                ┌──────────────────────────┐
        │   ┌───── descriptor_path ─────┤  if not                   │
        ▼   ▼                            │     ctx.field.options    │
  leading_comment(...)  →  str | None    │     .deprecated:         │
        │                                │      return              │
        ▼                                │  path = descriptor_path( │
   _check_replacement_comment(text)      │      ctx.field)          │
        │                                │  comment = leading_      │
        ├── True  → return (silent)      │      comment(...)        │
        │                                │  if _check_replacement_  │
        └── False → ctx.emit(            │     comment(comment):    │
              violation_kind=rule_id,    │      return              │
              params={                   │  ctx.emit(...)           │
                "name":  ...,            └──────────────────────────┘
                "comment": _safe_for_stderr(
                  (comment or "")[:500]
                ).replace("{","{{").replace("}","}}"),
              },
            )
                │
                ▼
  LintFinding(rule_id, severity=warning, location, params)
                │
                ▼
  message_template.format(name=..., comment=...) (rendered at emit)
                │
                ▼
  formatters: human / json / sarif / junit
```

### Data flow: descriptor-set capture (U3b)

```
operator runs: protokit lint --descriptor-set foo.pbset
        │
        ▼
  _load_descriptor_sets_to_result(paths)
        │
        ▼
  pool = DescriptorPool()
  source_info_descriptors: dict[str, FileDescriptorProto] = {}
  seen_names: set[str] = set()
  duplicates: list[LintCompileDiagnostic] = []
  root_files: list[str] = []
        │
        ▼  for input_path in paths:
        │      data = input_path.read_bytes()
        │      fds = FileDescriptorSet.FromString(data)
        │      for fd in fds.file:
        │          if fd.name in seen_names:
        │              duplicates.append(...)     ┐
        │              continue                   │  no accumulator
        │          seen_names.add(fd.name)        │  insertion (symmetric
        │          source_info_descriptors[      │  with pool.Add absence)
        │              fd.name                    │
        │          ] = fd     ◀── K-7/K-8: PRE-ADD capture per U1 precedent
        │                       (pool.Add consumes source_code_info; capture
        │                        must precede Add to retain it)
        │          try:
        │              pool.Add(fd)
        │          except (TypeError, ValueError):
        │              error_exit_with_code(...)  ┐  SystemExit;
        │                                          ┘  partial accumulator
        │                                             discarded harmlessly
        │          root_files.append(fd.name)
        ▼
  CompileResult(
      pool=pool,
      root_files=tuple(root_files),
      source_info_descriptors=source_info_descriptors,  # plain dict;
      diagnostics=tuple(duplicates),                     # __post_init__
  )                                                      # wraps in
                                                          # MappingProxyType
```

## Implementation Units

- [ ] **Unit 3a: R6 family (5 rules) + proto-mode CLI source-info wire-up + BUILTIN_PACKS extension + ~4-site test ratchet**

**Goal:** Land 5 `@lint_rule` callables under `src/protokit/schema/lint/rules/options/deprecated_replacement.py` sharing `_check_replacement_comment` + `_REPLACEMENT_PATTERNS`. Flip lint CLI proto mode to `include_source_info=True` at `cli.py:731`. Extend `BUILTIN_PACKS` with the new pack. Ratchet the ~4 `source_info_descriptors is None` assertion sites in `tests/test_cli_utils.py` (the only file with sites affected by the CLI flip — see Context & Research for the post-review breakdown).

**Requirements:** R6, R6c, R6-pack, R6-tests (proto-mode subset).

**Dependencies:** U1 (shipped), U2 (shipped, commit `2b487d1`).

**Files:**
- Create: `src/protokit/schema/lint/rules/options/deprecated_replacement.py` (5 rules + helper + patterns + RULES tuple)
- Modify: `src/protokit/schema/lint/rules/__init__.py:84` (BUILTIN_PACKS — append the new module; add import line)
- Modify: `src/protokit/schema/lint/cli.py:731` (`compile_protos_to_result(..., include_source_info=True)`)
- Test: `tests/schema/lint/rules/options/test_deprecated_replacement.py` (NEW — 5-rule family unit tests, happy + sad + edge + adversarial)
- Test: `tests/schema/lint/rules/options/fixtures/` (NEW directory — 5 per-ElementKind fixtures + 1 shared adversarial fixture)
- Modify: `tests/schema/lint/test_builtin_packs.py:79` (extend `expected` tuple with the new module)
- Modify: `tests/schema/lint/test_cold_import_extended.py` (verify the new module is NOT transitively loaded by `import protokit.schema`)
- Modify: `tests/test_static_analysis.py:_LINT_PATHS` (append the new source + test paths)
- Modify: ~4 `source_info_descriptors is None` assertion sites in `tests/test_cli_utils.py` only (the proto-mode CLI call path affected by `cli.py:731` flip). The 20 sites in `tests/schema/lint/test_compile_include_source_info.py` + 3 in `tests/schema/lint/test_engine_source_info_descriptors_injection.py` + 1 in `tests/schema/lint/rules/options/test_comments.py` are intentional pre-U3 contract pinning and MUST NOT change. `tests/schema/lint/test_model.py` has zero matching sites. (See Context & Research for the post-review re-count.)
- Modify: Mock-patch sites that wrap `compile_protos_to_result` at the lint CLI import boundary (e.g., `tests/schema/lint/cli/test_cli_input_modes.py:440-444`). Grep `patch.object.*compile_protos_to_result` to enumerate; for each, verify the mock signature tolerates the new `include_source_info=True` kwarg. `return_value=...` mocks are tolerant; `side_effect=fn` or `wraps=real_compile` mocks may need signature updates.

**Approach:**
- **Step 0 (pre-coding, pre-commit prep — produces NO checked-in artifact except the final pattern set used in Step 1) — corpus tuning** (K-10):
  - **Acquisition path:** sparse-checkout deprecation-comment-bearing subdirectories from each corpus (network-online environments only):
    - `git clone --depth 1 --filter=blob:none --sparse https://github.com/googleapis/googleapis.git` then `git sparse-checkout set google/`
    - `git clone --depth 1 https://github.com/grpc/grpc-proto.git`
    - `git clone --depth 1 --filter=blob:none --sparse https://github.com/envoyproxy/envoy.git` then `git sparse-checkout set api/`
    - `git clone --depth 1 https://github.com/open-telemetry/opentelemetry-proto.git`
    - Subset target: ~50-100 real-world deprecation comments across all 4 corpora.
  - **Offline fallback (network-restricted environments):** ship the 4 starting patterns AS-IS without corpus measurement; record `"corpus tuning deferred to D6c — environment without network egress"` in the commit message body. The patterns ship at warning severity which bounds blast radius regardless.
  - **Decision rule** (resolves the K-6/Step-0 circularity surfaced in review): if Step 0 measurement falls below 95% precision target, ship the 4 starting patterns AS-IS, record the measurement, and queue precision-tuning as a D6c follow-up. **Pattern ADDITION is allowed at Step 0 (if a missed canonical phrasing emerges); pattern REMOVAL or REPLACEMENT is NOT** — preserves the identity statement and the fixed-set commitment from K-6.
  - **Persistence:** record (a) precision/recall numbers + sample size + corpus subset details in U3a's commit message body; (b) optionally add a one-line summary comment in `_REPLACEMENT_PATTERNS` (e.g., `# Validated 2026-05-15 against googleapis+grpc-proto+envoy+opentelemetry-proto; precision ~97% on N=84`). The commit-body record is the durable signal for future deliveries.
- **Step 1 — write the helper module skeleton** with `_REPLACEMENT_PATTERNS` (finalized at Step 0), `_check_replacement_comment(text: str | None) -> bool`. Helper returns False when `text is None` (no comment) and `any(pattern.search(text) for pattern in _REPLACEMENT_PATTERNS)` otherwise.
- **Step 2 — write the 5 `@lint_rule` callables** following the body shape from the brainstorm. Each carries its own `message_template`, `rule_id`, `element=ElementKind.<KIND>`, `severity=LintSeverity.WARNING`, `profiles=("default",)`, `source_spec=""`. Body shape (uses `.name` for `params["name"]` per existing precedent at `naming.py:104, 131, 148, 165, 197, 214, 231` and `enum.py:68` — `.full_name` was decision drift in the brainstorm body shape; the LintLocation already carries scoping context like containing service/message):
  ```python
  if not ctx.<element>.GetOptions().deprecated:
      return
  path = descriptor_path(ctx.<element>)
  comment = leading_comment(ctx.source_info_descriptors, ctx.file.name, path)
  if _check_replacement_comment(comment):
      return
  ctx.emit(
      violation_kind="<rule_id>",
      params={
          "name": ctx.<element>.name,
          "comment": _safe_for_stderr((comment or "")[:500])
                      .replace("{", "{{").replace("}", "}}"),
      },
  )
  ```
- **Step 3 — `RULES` tuple at module bottom** (alphabetical or canonical order): `(check_deprecated_enum_..., check_deprecated_enum_value_..., check_deprecated_field_..., check_deprecated_message_..., check_deprecated_method_...)`.
- **Step 4 — BUILTIN_PACKS extension**: add `from protokit.schema.lint.rules.options import deprecated_replacement` import; append `deprecated_replacement` to the `BUILTIN_PACKS` tuple.
- **Step 5 — Lint CLI proto-mode flip**: change `compile_protos_to_result(paths=..., proto_paths=...)` at `cli.py:731` to `compile_protos_to_result(paths=..., proto_paths=..., include_source_info=True)`.
- **Step 6 — Test ratchet** (the ~4-site flip in `tests/test_cli_utils.py` only, per the post-review re-count): grep `source_info_descriptors is None` in that file; flip each assertion from `is None` to `is not None` (or assert on the populated mapping shape). Do NOT touch the 20 sites in `test_compile_include_source_info.py` or the 3 sites in `test_engine_source_info_descriptors_injection.py` — those test pre-U3 default-False contracts that must stay pinned. Also: enumerate mock-patch sites via `grep -rn "patch.object.*compile_protos_to_result" tests/`, verify each tolerates the new `include_source_info=True` kwarg (`return_value=...` patches are tolerant; `side_effect=fn` may need signature updates). Record per-file action notes in the commit message body.

**Execution note:** Build the regex corpus + finalize `_REPLACEMENT_PATTERNS` FIRST (Step 0); the corpus tuning is empirical and may add patterns. Then test-first for the helper (`_check_replacement_comment`), then write rules using the finalized regex set + helper.

**Technical design:** *(directional only)* Body shape and helper shape above. Production module under 300 lines including docstrings (5 rules × ~30 lines each + helper + patterns + imports). Test module similarly compact; parametrized fixtures keep the 5 ElementKinds DRY.

**Patterns to follow:**
- `src/protokit/schema/lint/rules/imports.py:64-93` — `@lint_rule(...)` shape with `message_template`.
- `src/protokit/schema/lint/rules/imports.py:42-58` — TYPE_CHECKING-guarded context aliases (K-11).
- `src/protokit/schema/lint/rules/imports.py:241-260` — module-bottom `RULES` tuple.
- `src/protokit/schema/lint/rules/naming.py` — multi-ElementKind dispatch.
- `src/protokit/_cli_utils.py:221-269` — capture-around-Add precedent (referenced for context though U3a doesn't extend this path).
- `tests/schema/lint/rules/test_imports.py` — rule-test module shape; fixture + ElementKind parameterization.
- `tests/schema/lint/test_compile_include_source_info.py` — fixture proto with leading comments (`_PROTO_WITH_COMMENTS` constant reusable for adversarial cases).

**Test scenarios:**

For EACH of the 5 ElementKinds (FIELD, ENUM_VALUE, METHOD, MESSAGE, ENUM), repeat:
- **Happy path:** `[deprecated = true]` element + leading comment matching one of the 4 patterns (e.g., `"Use NewField instead."`) → zero findings.
- **Happy path:** `[deprecated = true]` element + no leading comment → exactly one finding at `warning` severity with `violation_kind=options/deprecated-<kind>-must-have-replacement-comment`.
- **Edge case:** `[deprecated = true]` element + leading comment that doesn't match any pattern (e.g., `"This is being removed."`) → one finding; `params["comment"]` echoes the (sanitized) original text.
- **Edge case:** `[deprecated = false]` element + no comment → zero findings.
- **Edge case:** non-deprecated element + comment matching a pattern → zero findings (rule is gated by `.deprecated` first).
- **Edge case:** `ctx.source_info_descriptors is None` (legacy state) → rule emits a finding for every deprecated element (`leading_comment` returns None → helper returns False).

Adversarial scenarios (single shared `.proto` fixture with one deprecated element per concern — implementer **must parametrize** the test function over a per-concern table so a single failure shows the offending concern by name, e.g., `pytest.mark.parametrize("concern", ["multi_kb", "control_chars", "u2028_paragraph", "braces"])` with the fixture-element-name as a derived key):
- **Adversarial path (`multi_kb`):** `[deprecated = true]` element + leading comment containing 5KB of text → finding's `params["comment"]` is at most 500 chars.
- **Adversarial path (`control_chars`):** comment containing `\n`, `\r`, `\t`, ASCII control char, U+0085, U+2028, U+2029 → finding's `params["comment"]` has all collapsed to spaces (via `_safe_for_stderr`).
- **Adversarial path (`braces`):** comment containing literal `{` or `}` characters → rendered message (via `message_template.format(**params)`) does NOT crash with `KeyError`; the rendered output has `{{` / `}}` doubled per K-4.
- **Adversarial path (`braces_e2e`):** end-to-end `protokit lint --proto fixture.proto --format=json` produces a finding whose `message` field renders the brace-doubled comment without crashing — exercises the full R6c pipeline including `message_template.format(**params)` on adversarial input.
- **Fixture construction note:** `.proto` files with literal NUL / U+2028 / U+2029 in leading comments may need byte-level construction at fixture-build time (e.g., `conftest.py` writes the file at session-setup) rather than checked in as bytes — text editors and Git's autocrlf normalization may mangle them. If single-shared-fixture proves hard to debug, fall back to one fixture per concern (4 fixtures total) per the K-12 fallback note.

Integration scenarios:
- **Integration:** `protokit lint --proto fixture.proto --profile default --format=json` produces 5 R6 rule_ids in `findings` output, each at `warning` severity.
- **Integration:** `protokit lint --proto fixture.proto --profile recommended` produces zero R6 findings (R6 not in `recommended`).
- **Integration:** `[tool.protokit.lint.severities] "options/deprecated-field-must-have-replacement-comment" = "info"` demotes that specific rule_id to `info` severity — verified by the finding's `severity` field in `--format=json` output.
- **Integration:** `protokit lint --no-builtin-rules --proto fixture.proto` produces zero R6 findings (R6 is part of BUILTIN_PACKS; suppressing builtins suppresses R6 alongside the existing 17 buf-BASIC-parity rules).
- **Integration (smoke):** the full pre-U3 test suite (1600 tests at U2 baseline) continues to pass after the 26-site ratchet.

Static / structural scenarios:
- **Pack membership:** `tests/schema/lint/test_builtin_packs.py:79` membership-pin test passes with the extended `expected` tuple including the new module.
- **Cold-import:** `import protokit.schema` does NOT transitively load `protokit.schema.lint.rules.options.deprecated_replacement` (verified by `test_cold_import_extended.py`).
- **Static-analysis ratchet:** new source + test paths present in `tests/test_static_analysis.py:_LINT_PATHS`.

**Verification:**
- 5 new rule_ids visible via `protokit lint --no-color --profile default --format=json <fixture>`.
- All scenarios above pass.
- Pre-U3 test baseline holds zero regressions (1600 → 1650+ passing depending on test count).
- Commit message body records: (a) the finalized regex pattern set + corpus precision/recall numbers, (b) the per-file classification of the 26-site test ratchet.

---

- [ ] **Unit 3b: Descriptor-set-mode source-info capture in `_load_descriptor_sets_to_result`**

**Goal:** Extend the descriptor-set loader to capture `FileDescriptorProto` references into a `source_info_descriptors` accumulator (built on the per-fd success path) and pass to `CompileResult(...)`. R6 rules then fire end-to-end in descriptor-set mode when the input descriptor set was built with `protoc --include_source_info`.

**Requirements:** R6-CLI (descriptor-set-mode subset), R6-tests (descriptor-set-mode subset).

**Dependencies:** Unit 3a.

**Files:**
- Modify: `src/protokit/schema/lint/_cli_utils.py:259-403` (`_load_descriptor_sets_to_result` — capture `source_info_descriptors`; pass to `CompileResult(...)` constructor at line 399)
- Test: `tests/schema/lint/test_cli_descriptor_set_source_info.py` (NEW — descriptor-set-mode source-info coverage)
- Test fixtures: `tests/schema/lint/rules/options/fixtures/` extended with two pre-built `.pbset` files (one with `--include_source_info`, one without) — generated at fixture-build time from existing `.proto` source files

**Approach:**
- **Step 1 — Mirror the U1 PRE-ADD capture pattern** from `src/protokit/_cli_utils.py:221-270` (`_populate_pool_with_capture`, specifically lines 264-267 where `captured[fd.name] = fd` PRECEDES `pool.Add(fd)`). Within the per-fd loop at `_cli_utils.py:341-396`:
  - Initialize `source_info_descriptors: dict[str, FileDescriptorProto] = {}` at the loader's top alongside `pool`, `seen_names`, `duplicates`, `root_files`.
  - On the per-fd path, AFTER the dedup-skip `continue` (line 364) and AFTER `seen_names.add(fd.name)` (line 365) BUT BEFORE the `try: pool.Add(fd)` block (line 366), record `source_info_descriptors[fd.name] = fd`. **Order is load-bearing:** `pool.Add(fd)` consumes `source_code_info` per the U1 docstring at `src/protokit/_cli_utils.py:230-238` ("`pool.Add()` consumes `source_code_info` regardless of the FileDescriptorProto's serialized state, so the capture must happen on the in-memory proto BEFORE Add is called"). Capture-after-Add would yield empty `source_code_info` on every fd.
  - Dedup-skipped fds (line 352-364) skip BOTH the capture AND the Add — symmetric with `seen_names` invariant.
  - Error-exit paths (line 380, 393) discard partial accumulator state via SystemExit. The dict-insertion-before-Add means the accumulator carries an entry for the failing fd at SystemExit time, but the partial state is never returned to a caller — SystemExit propagates and the CompileResult is never constructed.
- **Step 2 — Pass `source_info_descriptors` to the `CompileResult(...)` constructor** at line 399. The plain dict is wrapped in `MappingProxyType` by `CompileResult.__post_init__` per the U1-established pattern at `src/protokit/schema/compile.py:225-229`.

**Execution note:** Test-first for the descriptor-set-mode source-info plumbing — the symmetric-behavior assertion (descriptor-set mode fires R6 rules the same way proto mode does) is the load-bearing correctness claim.

**Technical design:** *(directional only)* See "Data flow: descriptor-set capture (U3b)" diagram in the High-Level Technical Design section above. The change adds ~5-10 lines (one dict initialization at the function top + one insertion after the success-path `root_files.append` + one new constructor argument).

**Patterns to follow:**
- `src/protokit/_cli_utils.py:221-269` — `_populate_pool_with_capture` (U1 capture-around-Add precedent).
- `src/protokit/schema/compile.py:225-229` — `__post_init__` `MappingProxyType` wrap pattern.
- `tests/schema/lint/test_compile_include_source_info.py` — proto-mode source-info test pattern; mirror the structure for descriptor-set mode.

**Test scenarios:**
- **Happy path:** descriptor set built with `protoc --include_source_info` → `_load_descriptor_sets_to_result` returns a `CompileResult` whose `source_info_descriptors` is non-None and contains every `fd.name` from the input set. `.source_code_info.location[]` is non-empty for at least one fd.
- **Happy path:** descriptor set built WITHOUT `--include_source_info` → `source_info_descriptors` is non-None but each fd's `.source_code_info.location[]` is empty. `leading_comment(...)` returns None for every path lookup; R6 rules emit findings for every deprecated element (documented limitation per K-9).
- **Edge case:** descriptor set with one valid fd and one duplicate fd → dedup-collision-skipped fd is absent from BOTH `source_info_descriptors` AND `pool`; first-occurrence wins.
- **Edge case:** descriptor set with `pool.Add` failure (missing-imports / pool-conflict) → SystemExit; the partial `source_info_descriptors` state is harmlessly discarded.
- **Integration:** `protokit lint --descriptor-set <set built with --include_source_info> --profile default` fires the 5 R6 rules; output matches `protokit lint --proto <equivalent source> --profile default`.
- **Integration:** `protokit lint --descriptor-set <set built WITHOUT --include_source_info> --profile default` fires R6 rules for every deprecated element (over-report; documented per K-9).
- **Integration:** end-to-end descriptor-set-mode happy path on a fixture with `[deprecated = true]` field + replacement-matching comment → zero R6 findings.

**Verification:**
- `_load_descriptor_sets_to_result` returns `CompileResult` with populated `source_info_descriptors` (when input has source info).
- The per-fd `fd.name`-keyed accumulator matches the set of fds that made it into the pool (verified by an explicit symmetry test).
- All test scenarios above pass.
- Adversarial fixtures (multi-KB comment in a descriptor set) don't crash the loader or inflate memory beyond proto-mode's measured cost.

---

## System-Wide Impact

- **Interaction graph:** U3a's CLI flip at `cli.py:731` affects every proto-mode lint invocation — every `protokit lint --proto ...` call now compiles with source info. U3b's loader extension affects every descriptor-set-mode lint invocation. Both paths flow into the same `LintEngine` dispatch loop, so the engine's R6 dispatch is symmetric.
- **Error propagation:** R6 rules participate in the standard `ctx.emit → LintFinding → formatter` chain. No new error categories or runtime warning types in U3 (per K-9). Existing `LintCompileDiagnostic` paths in `_load_descriptor_sets_to_result` (bad-input, missing-imports, pool-conflict) are unchanged.
- **State lifecycle risks:** None. `source_info_descriptors` is read-only at the rule level (`Mapping[str, FileDescriptorProto]`). U3a's CLI proto-mode flip doesn't change pool lifecycle. U3b's loader extension adds a per-fd reference capture on the success path; SystemExit on failure paths discards partial state harmlessly.
- **API surface parity:** The 5 new rule_ids appear in `lint_json` / `lint_sarif` / `lint_human` / `lint_junit` output uniformly (no per-formatter divergence). All formatters surface the **rendered `message` string** (which embeds the sanitized + truncated + brace-escaped comment via `message_template.format(**params)`); none of the current formatters emit raw `params` into structured output (`_builtin_lint.py:282-299` `lint_json` and `:579-585` `lint_sarif` build their payloads from `message`, `rule_id`, `severity`, `location`, `violation_kind` only). The K-4 brace-escape is therefore load-bearing on the SINGLE consumer (`template.format(**params)`); the sanitization is load-bearing on the human-stderr path (rendered message line). Test scenarios assert on `finding.message` (rendered) for the structured paths, NOT on `finding.params["comment"]`.
- **Integration coverage:** Cross-layer scenarios verified in U3a's Integration test scenarios — CLI invocation → engine dispatch → formatter output, end-to-end.
- **Unchanged invariants:** 
  - `BUILTIN_PACKS` membership-pin test is still authoritative for the canonical pack set (U3a extends the `expected` tuple in lockstep).
  - The `recommended` profile remains buf BASIC parity (R6 not in `recommended`).
  - `severities` per-rule demotion semantics from D5 are unchanged; R6 rule_ids participate uniformly.
  - Wire-format `_LINT_JSON_SCHEMA_VERSION` stays at `"0.2"` in U3 (the bump to `"0.3"` happens at U5 with R9's `severities_unloaded_rule` category split).
  - Non-lint consumers (`protokit compat`, codegen, direct Python API) keep the pre-D6b zero-cost contract — they don't call `compile_protos_to_result(..., include_source_info=True)`.
  - Cross-protobuf-runtime (proto 4 vs proto 5) byte-equivalence verification remains deferred to U6 (not U3).

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Starting 4-pattern regex set has too-low recall on real-world deprecation comments — R6 over-reports legitimate replacement-tagged deprecations | Severity `warning` at launch bounds CI blast radius. Corpus tuning at Step 0 measures precision/recall and adjusts patterns; precision-first bias means recall gaps are acceptable. Promotion to `error` deferred to D6c. Documented in rule docstrings per [[buf-parity-divergence-documentation-discipline]]. |
| Proto-mode CLI flip breaks tests asserting `source_info_descriptors is None` | 26 sites pre-counted at brainstorm time (across 5 test files). Per-line classification in U3a Step 6; (a) intentional default-False guard stays None, (b) proto-mode CLI assertion flips to non-None, (c) needs new fixture. Recorded in commit message body. |
| R6 rules over-report on descriptor-set inputs built without `--include_source_info` (every deprecated element emits a finding) | Documented in each rule's docstring + U7 CHANGELOG. Workaround paths: (a) add a replacement comment, (b) rebuild descriptor set with `--include_source_info`, (c) demote R6 rule via `[severities]`. Runtime warning deferred to D6c per K-9. |
| `message_template.format(**params)` crashes on raw `{` or `}` in a comment | K-4 pre-escape (`.replace("{","{{").replace("}","}}")` after sanitization) at the R6 emit site prevents the crash. Adversarial test in U3a covers this. |
| `_load_descriptor_sets_to_result` modification changes the return-value shape in ways that break callers | The change is additive (new `source_info_descriptors` field on the returned `CompileResult`); pre-D6b callers that read only `.pool`, `.root_files`, `.diagnostics` are unaffected. The U1 audit (per parent plan line 61: 7 production + 6 test sites) already confirmed call-shape compatibility for the `source_info_descriptors` field. |
| Descriptor-set capture in U3b violates the `frozen`-dataclass mutation contract | `source_info_descriptors` is passed as a plain dict; `CompileResult.__post_init__` (`src/protokit/schema/compile.py:225-229`) wraps in `MappingProxyType` automatically per the U1-established pattern. Verified by U1's test suite for the proto-mode capture path; U3b mirrors the contract. |
| The 5-rule per-ElementKind dispatch fails to trigger because the engine's `default` profile composition doesn't pick up `profiles=("default",)`-only rules | **R6 will be the FIRST `default`-only rule family** — every existing rule under `src/protokit/schema/lint/rules/` declares `profiles=("recommended", "default")`. The mechanism is sound: `LintProfile.from_pack(module, profile_name)` at `src/protokit/schema/lint/model.py:771-781` filters per `profile_name in spec.profiles`, and the CLI's per-name composition at `cli.py:826-851` composes across packs. The load-bearing verification is U3a's new integration test: "R6 fires under `--profile default` AND zero R6 findings under `--profile recommended`." Not pre-existing precedent. |
| Adversarial multi-KB-comment proto inflates lint memory under proto-mode (since `include_source_info=True` now ships on every invocation) | U1's measured 10-30% descriptor-set size cost is the measured impact. The 500-char truncation at finding-construction bounds downstream amplification; raw `source_code_info` retention in `CompileResult` is the U1-baseline cost, not new in U3. |
| Cross-protobuf-runtime (proto 4 vs proto 5) `source_code_info` emission divergence produces inconsistent R6 findings | Deferred to U6 (parity test infra); U3 ships against the pinned protobuf version. If U6's verification reveals divergence, R6 rules may need a runtime-conditional path or a protobuf-version pin update in `pyproject.toml`. |
| Adversarial path test fixture is too dense (single `.proto` with many deprecated elements + many adversarial comment variants) and obscures which case is failing | If the dense single-fixture approach proves hard to debug at implementation time, K-12 may be revisited; default plan is single shared fixture per the brainstorm K-12. |

## Documentation / Operational Notes

- **Rule docstrings:** each of the 5 rules' docstring documents (a) the deprecated-replacement phrasing it expects, (b) the protokit-original status (no buf analogue), (c) the descriptor-set-without-source-info limitation. The U7 presence ratchet asserts a known substring per rule.
- **CHANGELOG D6b section** (U7 deliverable, not U3): R6 family (5 rules, default profile, warning severity); include the corpus-precision number from U3a's measurement.
- **README "Schema Linting" section refresh** (U7 deliverable): R6 worked example showing a deprecated field + replacement comment + the resulting warning finding; descriptor-set-mode caveat callout.
- **Public Surface DRAFT** (U7 deliverable): new rows for the 5 R6 rule_ids (status: IN); rows for `CompileResult.source_info_descriptors` (INTERNAL — already drafted at U2), `compile_protos_to_result(include_source_info=)` (IN, shipped U1), `_load_descriptor_sets_to_result` behavior change (INTERNAL — implementation detail).
- **Operational rollout:** D6b 0.2.0 → 0.3.0 bump lands at U7 with the version-bump-as-communication-contract per [[pre-1.0-version-bump-as-communication-contract]]. R6 rules ship at `warning`; CIs that gate on `max_warnings` may flip red on D6b adoption — documented in U7's CHANGELOG with demotion paths.
- **Rendered-message line length:** R6 messages include `{comment}` interpolation per K-5, which can produce stderr lines up to ~700 chars worst case (template prefix + brace-doubled 500-char comment + suffix). `click.echo` does not wrap. This is acceptable for D6b ship — most CI log viewers (GitHub Actions, GitLab, Jenkins console) handle long lines via horizontal scroll or soft wrap. If user feedback indicates the human-message length harms readability, the U7 CHANGELOG can document the configurable-truncation option as a D6c follow-up.
- **Universal proto-mode CLI cost:** The `cli.py:731` flip applies `include_source_info=True` unconditionally for every `protokit lint --proto` invocation, including invocations where R6 rules are demoted to off. The U1-measured 10-30% descriptor-set size cost is paid universally. Documented in U7's CHANGELOG as part of the version-bump communication; no per-invocation opt-out flag in D6b. If user demand emerges, expose a `--no-source-info` flag in D6c.

## Sources & References

- **Origin document:** [docs/brainstorms/2026-05-15-d6b-u3-r6-deprecated-replacement-family-requirements.md](docs/brainstorms/2026-05-15-d6b-u3-r6-deprecated-replacement-family-requirements.md)
- **Parent D6b brainstorm:** [docs/brainstorms/2026-05-14-protokit-lint-delivery-6b-option-aware-and-multi-language-requirements.md](docs/brainstorms/2026-05-14-protokit-lint-delivery-6b-option-aware-and-multi-language-requirements.md) (R6 / R6c / R7 / R9 sections — U3 scope per lines 32-79).
- **Parent D6b plan:** [docs/plans/2026-05-14-001-feat-protokit-lint-d6b-option-aware-and-multi-language-plan.md](docs/plans/2026-05-14-001-feat-protokit-lint-d6b-option-aware-and-multi-language-plan.md) (Unit 3 section: lines 391-440 — this plan supersedes that section in implementation specifics).
- **U2 per-unit plan (reference shape):** [docs/plans/2026-05-14-002-feat-d6b-u2-leading-comment-helper-plan.md](docs/plans/2026-05-14-002-feat-d6b-u2-leading-comment-helper-plan.md).
- **U2 shipped helpers:** `src/protokit/schema/lint/rules/options/_comments.py` (`descriptor_path`, `leading_comment`).
- **U1 prior art for pool.Add capture:** `src/protokit/_cli_utils.py:221-269` (`_populate_pool_with_capture`).
- **Pattern modules:** `src/protokit/schema/lint/rules/imports.py` (canonical 3-rule + message_template shape), `src/protokit/schema/lint/rules/naming.py` (multi-ElementKind dispatch).
- **API surfaces:** `src/protokit/schema/lint/decorator.py:52-130` (`@lint_rule`), `src/protokit/schema/lint/model.py:918-923` (`emit`), `src/protokit/schema/lint/_cli_utils.py:198-256` (sanitizer).
- **CLI entry points:** `src/protokit/schema/lint/cli.py:731` (proto mode), `src/protokit/schema/lint/_cli_utils.py:259-403` (descriptor-set mode).
- **Pack curation:** `src/protokit/schema/lint/rules/__init__.py:70-92` + `tests/schema/lint/test_builtin_packs.py:79`.

### Review history

- **2026-05-15 ce:plan document-review pass:** 4 personas (coherence + feasibility + scope-guardian + adversarial). 10 auto-fixes applied in-doc:
  1. **K-7/K-8 capture-ordering CORRECTED** (P1 critical) — original draft said "post-success insertion (AFTER pool.Add)"; verified against U1 source at `src/protokit/_cli_utils.py:264-267` which captures BEFORE Add (docstring line 230-238 explicit: "the capture must happen on the in-memory proto BEFORE Add is called"). Plan now specifies PRE-ADD capture; data-flow diagram and U3a Step 1 instructions updated.
  2. **`params["name"]` changed from `.full_name` to `.name`** — verified against existing rule precedent at `naming.py:104,131,148,165,197,214,231` + `enum.py:68` (all use `.name`); LintLocation already carries scoping context.
  3. **Test count corrected** — was "5 files / 26 sites"; actual grep yields "4 files / 28 sites" with `test_model.py` having zero matching assertions. Net U3a ratchet workload: ~4 sites in `tests/test_cli_utils.py` only (the other 24 sites are intentional pre-U3 contract pinning that must NOT change).
  4. **Wire-format claim corrected** — original draft said JSON/SARIF "carry the same value via params[comment] if formatter consumes params"; verified at `_builtin_lint.py:282-299/579-585` that formatters surface only the rendered `message` string, NOT raw params. K-4 brace-escape protects the single consumer (`template.format(**params)`).
  5. **Default-only profile risk row corrected** — was "verified by existing tests on enum.py-style rules"; verified that NO existing rule is `default`-only (all use `("recommended", "default")`). R6 will be the FIRST `default`-only family; integration test is the load-bearing verification, not existing precedent.
  6. **Step 0 acquisition path made concrete** — added sparse-checkout commands per corpus + offline fallback (network-restricted environments ship the 4 patterns AS-IS and record the fallback rationale in commit body).
  7. **Step 0 decision rule resolved** — K-6 vs Step 0 circularity (ship fixed vs corpus-tune) collapsed to one bit: pattern ADDITION allowed; pattern REMOVAL/REPLACEMENT not (preserves K-6's fixed-set commitment).
  8. **K-12 adversarial fixture parametrization** — added explicit `pytest.mark.parametrize` requirement so per-concern failures show by name; documented byte-level fixture-construction caveat for U+2028/NUL chars.
  9. **K-11 line range citation fixed** — was `imports.py:42-58` (docstring/runtime-notes block); corrected to `imports.py:48-61` (actual eager-imports + TYPE_CHECKING block).
  10. **PR boundary specified** — U3a + U3b ship as two commits in ONE PR (bisectability preserved; single review surface). Plus: rendered-message line-length and universal-CLI-flip operational notes added to Documentation/Operational Notes; `--no-builtin-rules` integration scenario clarified; mock-patch test-site enumeration added to Step 6.

Findings deferred to implementer judgment / future deliveries (residual): K-9 over-reporting flood mitigation (cheap runtime detection of empty `source_code_info.location` could suppress findings — defer to /ce:work decision); user-facing `--no-source-info` CLI flag (defer to D6c if demand emerges).

### Next step

`/ce:work` against this plan starting with Unit 3a (Step 0: corpus tuning). The implementation note from K-10 — recording precision/recall numbers (or the offline-fallback rationale) in U3a's commit message body — is the verification signal that the corpus tuning step ran.

**PR boundary** (resolves the unspecified boundary surfaced in review): U3a and U3b ship as **two commits in a single PR**. Rationale:
- Bisectability for `git bisect` is preserved across the two commits.
- Single review surface for the U3 family (lower CI overhead, atomic reviewer view).
- Sequential merge ordering risk is eliminated — U3a's CLI flip + R6 rules and U3b's descriptor-set loader extension land or roll back together.
- `/ce:review` runs once on the combined diff at PR creation; per-commit `/ce:review` runs (the per-unit workflow convention) still occur during local development.

U3b follows U3a in the same PR; the two-commit boundary is preserved for git history clarity.
