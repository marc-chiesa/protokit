# protokit-lint D6b U3 — R6 deprecated-replacement family (5 rules) + lint CLI source-info wire-up

**Status:** brainstorm (requirements). Next step: `/ce:plan`.
**Date:** 2026-05-15.
**Scope:** per-unit. Refines parent D6b U3 section.
**Parent brainstorm:** `docs/brainstorms/2026-05-14-protokit-lint-delivery-6b-option-aware-and-multi-language-requirements.md` (R6, R6c sections + Open Questions).
**Parent plan:** `docs/plans/2026-05-14-001-feat-protokit-lint-d6b-option-aware-and-multi-language-plan.md:391-440` (Unit 3 section).
**Predecessors shipped:** U1 (commit `9bfb2da`-ish) wired `include_source_info=...` through `compile_protos_to_result` + both backends; U2 (commit `2b487d1`) wired `descriptor_path` + `leading_comment` helpers and threaded `source_info_descriptors` through 5 R6 ElementKind contexts. 1600 tests + 39 skips passing.

## TL;DR

U3 lands the **first 5 lint rules that read proto source comments** — closing the U1+U2 plumbing chain with consumer code that demonstrates the option-aware capability end-to-end. The headline shifts from "plumbing exists" (U2) to "rules fire on real protos" (U3).

Three deliverables:

1. **5 R6 rules** under `src/protokit/schema/lint/rules/options/deprecated_replacement.py` — one rule per `*Options.deprecated` ElementKind (FIELD, ENUM_VALUE, METHOD, MESSAGE, ENUM). All share a `_check_replacement_comment(text) -> bool` helper and a module-level `_REPLACEMENT_PATTERNS` tuple of compiled regexes. Severity `warning`, profile `default` only. Each rule emits `params={"comment": _safe_for_stderr(comment_text[:500])}` for adversarial-safe wire format.
2. **Lint CLI source-info wire-up** at BOTH input paths — proto mode (`compile_protos_to_result(..., include_source_info=True)` at `cli.py:731`) AND descriptor-set mode (extend `_load_descriptor_sets_to_result` at `_cli_utils.py:259` to capture `FileDescriptorProto` references BEFORE `pool.Add(fd)` consumes the source info, pass to `CompileResult(...)`). Symmetric behavior between modes prevents R6 over-reporting on descriptor-set inputs.
3. **BUILTIN_PACKS membership extension** at `rules/__init__.py:84` (append the new `deprecated_replacement` module; ratchet `tests/schema/lint/test_builtin_packs.py:79`'s `expected` tuple).

Explicit non-goals: R7 PACKAGE_SAME_* family (U4), R9 `severities_unloaded_rule` category split + schema_version bump (U5), runtime warning when `source_info_descriptors=None` (deferred — coordinates with U5's wire-format bump).

## Problem Frame

After U2 shipped, the R6 plumbing chain is complete:

```
compile_protos_to_result(include_source_info=True)  ← U1
  └─→ CompileResult.source_info_descriptors          ← U1
       └─→ ctx.source_info_descriptors (5 contexts)  ← U2
            └─→ descriptor_path(ctx.field)            ← U2 helper
                 └─→ leading_comment(descs, name, path)  ← U2 helper
                      └─→ str | None  ← consumed by ... nothing yet
```

The "consumed by ... nothing yet" gap is U3's scope. Two visible consequences of leaving the gap open:

- **The option-aware capability is unproved end-to-end.** U1 and U2 added 1600th-test-baseline-worth of code; no rule ever calls `leading_comment` on a real proto. The differentiator claim ("protokit reads comments to enforce schema policy") needs a worked example in `BUILTIN_PACKS`.
- **The lint CLI never sets `include_source_info=True`.** Today the call site at `cli.py:731` uses the parameter's default (False), so even after the U1+U2 plumbing, every lint invocation gets `source_info_descriptors=None`. U2 K-6 ("legitimate None state") explicitly noted this is pre-U3 behavior; U3 flips it.

D6b U3 closes both gaps in one unit — the 5 rules consume the helper, the CLI wire-up flips `include_source_info=True`, and the BUILTIN_PACKS extension makes the rules visible to users running `protokit lint --profile default`.

## Requirements

### R6 — 5-rule deprecated-replacement family

Ship 5 `@lint_rule`-decorated callables under a single module `src/protokit/schema/lint/rules/options/deprecated_replacement.py`. Each rule:

| rule_id | ElementKind | Reads | Context type |
|---------|-------------|-------|--------------|
| `options/deprecated-field-must-have-replacement-comment` | FIELD | `FieldOptions.deprecated` | `FieldLintContext` |
| `options/deprecated-enum-value-must-have-replacement-comment` | ENUM_VALUE | `EnumValueOptions.deprecated` | `EnumValueLintContext` |
| `options/deprecated-method-must-have-replacement-comment` | METHOD | `MethodOptions.deprecated` | `MethodLintContext` |
| `options/deprecated-message-must-have-replacement-comment` | MESSAGE | `MessageOptions.deprecated` | `MessageLintContext` |
| `options/deprecated-enum-must-have-replacement-comment` | ENUM | `EnumOptions.deprecated` | `EnumLintContext` |

Body shape (pattern for each rule — mirrors `imports.py:64-93` / `naming.py` / `enum.py`):

```python
@lint_rule(
    rule_id="options/deprecated-field-must-have-replacement-comment",
    severity=LintSeverity.WARNING,
    profiles=("default",),
    element=ElementKind.FIELD,
    message_template=(
        "deprecated field {name!r} is missing a replacement comment "
        "(expected 'Use X instead.' or similar phrasing)"
    ),
    source_spec="",  # protokit-original, excluded from parity per KTD-10
)
def check_deprecated_field_must_have_replacement_comment(
    ctx: FieldLintContext,
) -> None:
    if not ctx.field.GetOptions().deprecated:
        return
    path = descriptor_path(ctx.field)
    comment = leading_comment(
        ctx.source_info_descriptors, ctx.file.name, path,
    )
    if _check_replacement_comment(comment):
        return
    ctx.emit(
        violation_kind="options/deprecated-field-must-have-replacement-comment",
        params={
            "name": ctx.field.full_name,
            "comment": _safe_for_stderr((comment or "")[:500]),
        },
    )
```

**API alignment** (corrects pre-review draft per `ce:review` feedback):

- `@lint_rule` requires `message_template` (no default per `src/protokit/schema/lint/decorator.py:58`). Each of the 5 rules carries its own template; `/ce:plan` finalizes the exact wording per rule so U7's presence ratchet has a known substring to assert.
- `ctx.emit` signature is `emit(*, violation_kind: str, params: dict | None)` (per `src/protokit/schema/lint/model.py:918-923`); there is no `message=` kwarg. The human-readable message is rendered from `message_template` via `.format(**params)` at engine emit time.
- `params["name"]` carries the descriptor's `full_name` for `{name!r}` interpolation; `params["comment"]` carries the sanitized truncated comment text. Whether the template references `{comment}` (surfacing the comment in human-rendered messages) or omits it (carrying only via structured `params`) is a `/ce:plan` decision — see Open Questions.

**Shared helper:**

```python
_REPLACEMENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\buse\s+[\w.]+\s+instead\b", re.IGNORECASE),
    re.compile(r"\breplaced?\s+(?:by|with)\s+[\w.]+", re.IGNORECASE),
    re.compile(r"\bmigrate\s+to\s+[\w.]+\b", re.IGNORECASE),
    re.compile(r"\bsee\s+[\w.]+\s+for\s+(?:the\s+)?replacement\b", re.IGNORECASE),
)


def _check_replacement_comment(text: str | None) -> bool:
    """Return True if ``text`` matches any replacement-phrasing pattern."""
    if text is None:
        return False
    return any(pattern.search(text) for pattern in _REPLACEMENT_PATTERNS)
```

Starting regex set is intentionally narrow (high precision per parent brainstorm's "minimize false positives at the cost of some false negatives" bias). `/ce:plan` finalizes the set against a fixture corpus drawn from googleapis, grpc-proto, envoy, and opentelemetry-proto — adding patterns only if precision stays high on real-world deprecation comments.

**`RULES` tuple** at module bottom — convention from `imports.py`/`naming.py`. Module-level `RULES` is the engine's entry point.

### R6-CLI — Lint CLI wires `include_source_info=True` at BOTH input paths

**Proto mode** (`src/protokit/schema/lint/cli.py:731`): set `include_source_info=True` on the `compile_protos_to_result(...)` call. No other parameters change. The descriptor-set size delta documented at U1 (~10-30% under the cross-version verification suite) is paid for every `--proto`-mode lint invocation; non-lint consumers (compat, codegen, direct Python API) keep the pre-D6b zero-cost contract via the parameter's `False` default.

**Descriptor-set mode** (`src/protokit/schema/lint/_cli_utils.py:259-403`, `_load_descriptor_sets_to_result`): extend the loader to capture `fd` references into a `source_info_descriptors: dict[str, FileDescriptorProto]` accumulator alongside `root_files` on the success path of each per-fd iteration. Pass the accumulator (as a plain dict; `CompileResult.__post_init__` wraps it in `MappingProxyType` per U1's pattern at `src/protokit/schema/compile.py:225-229`) to the `CompileResult(...)` constructor at line 399.

**Capture ordering** (post-review clarification): within the per-fd loop, the `source_info_descriptors[fd.name] = fd` assignment happens AFTER `pool.Add(fd)` succeeds — at the same point as `root_files.append(fd.name)` today (line 397). The Python-level `fd` reference is captured *before* `pool.Add(fd)` only in the sense that the local binding persists for the post-success dict insertion; partial state is never visible on the `error_exit_with_code` paths (bad-input / missing-imports / pool-conflict). Dedup-collision-skipped fds (line 352-364) also skip the accumulator insertion — those file names are absent from the pool and absent from `source_info_descriptors`, preserving the invariant that `source_info_descriptors` keys match the set of `fd.name`s actually added to the pool.

The descriptor-set extension matters because without it, R6 rules silently no-op on descriptor-set inputs even when the user generated the set with `protoc --include_source_info` — that's a footgun. The extension's cost is ~10 lines of accumulation + one constructor argument, and it gives lint symmetric behavior across input modes.

**Behavior when descriptor-set was built WITHOUT `--include_source_info`:** `source_info_descriptors` will be a mapping of `FileDescriptorProto`s whose `.source_code_info.location` is empty. `leading_comment` returns None for every path lookup. `_check_replacement_comment(None)` returns False. R6 rules emit findings for every deprecated element. Documented in U3 CHANGELOG content (lands at U7) and each rule's docstring as a known limitation: "to suppress R6 findings, either (a) add a replacement comment in proto source, (b) rebuild your descriptor set with `--include_source_info`, or (c) demote R6 rules via `[tool.protokit.lint.severities]`."

### R6c — Inline `_safe_for_stderr` reuse at finding-construction

The comment-derived `params["comment"]` value passes through the existing `_safe_for_stderr(...)` helper at `src/protokit/schema/lint/_cli_utils.py:216` inline at each rule's `ctx.emit(...)` call site. No new module, no `_safe_for_findings` abstraction.

**Truncate-then-sanitize order**: `_safe_for_stderr(comment_text[:500])`. Truncation runs first because:

1. The `_CONTROL_CHAR_TABLE` is a per-codepoint translation map (each char is independently rewritten). Truncating at char 500 cannot split a "sanitizer-relevant sequence" because none exist — the table operates on single codepoints, not multi-char patterns.
2. Sanitize-first would do more work on bytes that will be discarded anyway (multi-KB adversarial comments).

The 500-char cap bounds the size of the comment value that reaches any downstream emit path (human stderr message + JSON `params` field + SARIF property bag) against adversarial protos carrying multi-KB deprecation comments.

**Per-emit-path threat model decomposition** (added post-review to address sanitizer-scope question):

| Emit path | Consumes `params["comment"]`? | Sanitization that applies |
|-----------|-------------------------------|---------------------------|
| Human formatter (stderr / `click.echo`) | Yes IF `message_template` references `{comment}` | `_safe_for_stderr` collapses control chars + U+0085/U+2028/U+2029 to spaces — keeps the rendered line a single-line literal. Load-bearing. |
| JSON formatter (`_builtin_lint.py:lint_json`) | The current schema emits the rendered `message` string, not raw `params`. Whether `params["comment"]` surfaces depends on whether `{comment}` is in the template. `/ce:plan` decides; if surfaced, the sanitized value is what `json.dumps` then escapes. | `json.dumps` independently escapes control chars + U+2028/U+2029 as `\uXXXX`. Defense-in-depth. |
| SARIF formatter (`_builtin_lint.py:lint_sarif`) | Same as JSON — message is rendered from template. | Same as JSON. |
| JUnit formatter | Same — message is rendered from template; XML escape applies on the rendered string. | XML-escaping of `<`, `>`, `&` etc. handled by the XML emitter. |

**Net consequence:** `_safe_for_stderr` is load-bearing for the human emit path (and only that path, in U3's scope). For the structured paths, the formatter's own escape contract is the primary defense; the sanitizer's contribution is collapsing newlines so the rendered template — which contains the comment via `{comment}` if present — doesn't span multiple lines. If `/ce:plan` decides to omit `{comment}` from the rendered template entirely and surface the comment only as a structured `params` field in JSON/SARIF, the sanitizer becomes pure defense-in-depth and the 500-char truncation remains the load-bearing DoS bound.

### R6-pack — `BUILTIN_PACKS` membership

Append `deprecated_replacement` to the `BUILTIN_PACKS: tuple[ModuleType, ...]` at `src/protokit/schema/lint/rules/__init__.py:84` as a Python module reference (matching the existing `naming`, `enum`, `imports`, `package`, `file` entries — the tuple holds imported module objects, not strings). New import line at the module top: `from protokit.schema.lint.rules.options import deprecated_replacement`. The new entry's qualified `__name__` is `protokit.schema.lint.rules.options.deprecated_replacement` (the first entry under the `options/` sub-package). Extend the membership-pin test's `expected` tuple at `tests/schema/lint/test_builtin_packs.py:79` to include the new module per the [[pytest-static-analysis-gate-ratchet]] ratchet pattern.

The pack imports cleanly into the cold-import chain: `protokit.schema.lint.rules.options.deprecated_replacement` sits under the existing `protokit.schema.lint.rules.options.*` lazy subtree (`_comments.py` shipped in U2 under the same path). **Import discipline mirrors `imports.py:42-58` / `naming.py` / `enum.py`:**

- Eager at module top: `import re`, `from protokit.schema.lint.decorator import lint_rule`, `from protokit.schema.lint.model import ElementKind, LintSeverity`, `from protokit.schema.lint.rules.options._comments import descriptor_path, leading_comment`, `from protokit.schema.lint._cli_utils import _safe_for_stderr`.
- TYPE_CHECKING-guarded: the 5 `*LintContext` type aliases (`FieldLintContext`, `EnumValueLintContext`, `MethodLintContext`, `MessageLintContext`, `EnumLintContext`) under `if TYPE_CHECKING:` per the cold-import contract verified by `tests/schema/lint/test_cold_import_extended.py`.
- `from __future__ import annotations` at module top so the parameter annotations resolve as strings at runtime.

## Non-Goals (deferred)

- **R7 PACKAGE_SAME_* family.** U4 ships these 7 cross-language rules. U3 stays focused on the option-aware path.
- **R9 `severities_unloaded_rule` category split + schema_version bump.** U5. R9 is independent of R6/R7.
- **Runtime warning when `source_info_descriptors=None`.** Adding a new `LintRuntimeWarning.category` Literal value (e.g., `"comment_source_info_missing"`) for the descriptor-set-without-source-info case is plausible but would coordinate with U5's wire-format `schema_version` bump. U3 ships without it; R6 rules over-report on descriptor-set inputs without source info, documented per R6-CLI. Re-evaluate in D6c if user reports show real-world confusion.
- **Regex set tuning against full corpus.** `/ce:plan` extracts deprecation comments from googleapis + grpc-proto + envoy + opentelemetry-proto and validates the starting 4-pattern set against measured precision/recall. The 4 patterns shipped here are a starting point — `/ce:plan` may add patterns if precision stays high on the corpus.
- **Promotion to `error` severity.** D6c decision after real-world miss/hit rate measurement per the parent brainstorm's heuristic-rule blast-radius asymmetry rationale.
- **Expanded option-aware pack** (`options/required-field-behavior`, etc.). D6c+.
- **README worked example.** Lands at U7 (delivery boundary unit) per the parent plan; U3 lands the rules + tests, U7 lands the documentation surface.

## Open Questions

### Deferred to Planning

- **Regex set finalization.** Starting set is 4 patterns (`use X instead`, `replaced by X`, `migrate to X`, `see X for the replacement`). `/ce:plan` measures precision against the fixture corpus and adds patterns if signal is high. Severity stays `warning` regardless of corpus outcome.
- **Per-rule docstring shape.** Each of the 5 rules' docstring mentions protokit-original status (no buf analogue per [[buf-parity-divergence-documentation-discipline]]). `/ce:plan` finalizes the exact docstring wording so the U7 presence ratchet has a known substring to assert.
- **Adversarial fixture composition.** `/ce:plan` decides whether adversarial cases (multi-KB comment, control-char comment, U+2028/U+2029 comment, raw `\n` injection) share one `.proto` file or are split across separate fixtures. Lean toward shared file for test density.

- **`message_template` `{comment}` interpolation policy.** Each of the 5 R6 rules' `message_template` may or may not reference `{comment}`. Including it surfaces the (sanitized, truncated) comment text in the human-rendered message line — useful for "this comment doesn't match the heuristic; here's what it says" UX. Omitting it keeps the rendered message uniform across findings (better for grep-based CI tooling) and the comment is still carried in structured `params` for JSON/SARIF consumers. `/ce:plan` picks a single policy across the 5 rules and finalizes the exact `message_template` wording per ElementKind.

- **`{`/`}` escape in sanitized comment.** `_safe_for_stderr` does not escape `{` or `}` characters. If `message_template` references `{comment}` and the sanitized comment itself contains `{` or `}`, `str.format()` may raise `KeyError` on attempted spec parsing. `/ce:plan` decides: (a) extend `_safe_for_stderr` to also map `{` `}` to safe equivalents (scope creep — changes the shared helper's contract), (b) use `str.format_map` with a defaultdict-style mapping that swallows unknown keys, (c) skip `{comment}` in `message_template` and surface the comment only via structured `params`, or (d) pre-escape `{` `}` at the R6 emit site (`comment.replace("{","{{").replace("}","}}")` after sanitization).

- **Commit shape — atomic U3 vs split U3a/U3b** (scope-guardian + adversarial cross-persona, post-review). U3 currently bundles 5 R6 rules + 2 CLI plumbing changes + 5-26 test ratchet updates in one cohesive commit. Independent failure modes; bisectability suffers if `/ce:review` finds a regex defect after the CLI plumbing has landed. `/ce:plan` decides: (a) keep U3 atomic per the brainstorm's Output Structure; (b) split into **U3a** (5 rules + proto-mode `cli.py:731` wire-up + BUILTIN_PACKS + test ratchet) and **U3b** (descriptor-set-mode `_load_descriptor_sets_to_result` extension + symmetric-behavior tests); (c) prep-commit the test-assertion ratchet ahead of U3's main commit (de-couples the noisy `is None` → `is not None` flip from rule semantics). Lean toward (b) if the diff size or test-update count exceeds the per-commit budget at implementation time.

- **Descriptor-set-without-source-info runtime signal** (product-lens + adversarial cross-persona, post-review). Currently documented as a known limitation (Non-Goals). The cheaper mitigation than a new `LintRuntimeWarning.category` Literal value: emit a one-shot `LintCompileDiagnostic(level="warning", category="source_info_missing"-or-similar, message="descriptor set lacks source_code_info — R6 rules over-report; rebuild with --include_source_info")` from `_load_descriptor_sets_to_result` IF any captured fd has empty `source_code_info.location` AND any R6 rule is loaded into the engine. `/ce:plan` decides: (a) ship the diagnostic in U3 (load-bearing for footgun mitigation; small code change); (b) defer the runtime signal to D6c per current Non-Goals (lower scope cost but ships the footgun); (c) ship the diagnostic decoupled from R6-rule-presence (warn whenever a descriptor set lacks source info regardless of profile — most general but creates noise for non-R6 users).

- **Pattern-set extensibility — fixed vs user-configurable** (product-lens, post-review). The 4-pattern starting set becomes a de facto API after ship: users write deprecation comments to match it; future narrowing breaks comments that previously satisfied. `/ce:plan` decides: (a) ship the 4-pattern set as fixed protokit-canonical (locked-in identity bet); (b) ship the 4-pattern set as the default for a new `[tool.protokit.lint.options.deprecated_replacement.patterns]` config knob (additional patterns appended; existing 4 always present) — preserves identity while accommodating teams with house-style deprecation phrasings; (c) ship a regex-replacement-marker prefix knob (`replacement_marker_prefix = "@replaced-by:"` etc. — fully prescriptive but configurable). Lean toward (b) if D6b is already shipping `[tool.protokit.lint.severities]` precedent (it is, per D5 U2).

- **Precision/recall floor as ship-gate** (product-lens, post-review). Current success criteria are plumbing assertions; no measurable user-outcome target gates U3 ship. `/ce:plan` decides: (a) add Success Criterion 11 — "On the curated corpus (googleapis + grpc-proto + envoy + opentelemetry-proto deprecation comments), the 4-pattern set matches ≥X% of canonical replacement-tagged deprecations (recall) AND ≤Y% of non-replacement-tagged comments (false-positive rate). X and Y finalized at /ce:plan corpus measurement time, gating U3 ship if not met"; (b) accept that severity=warning bounds blast-radius without a measured floor and ship regardless of corpus outcome (current brainstorm posture). Lean toward (a) if the corpus is small enough for /ce:plan to measure tractably.

### Resolved Here

- **Module shape: SINGLE FILE.** `src/protokit/schema/lint/rules/options/deprecated_replacement.py` contains all 5 rules + `_check_replacement_comment` helper + `_REPLACEMENT_PATTERNS` tuple + `RULES` tuple. Matches `imports.py` (8 rules) and `naming.py` (8 rules) precedent; sharing the helper + patterns across rules is the dominant ergonomic factor. Resolves brainstorm Open Question on R6 sub-rule module structure.
- **Comment truncation length: 500 chars.** Resolves the parent brainstorm (200) vs parent plan (500) discrepancy in favor of 500 per the parent plan's working bias. Justification: canonical deprecation comments in real-world corpora (googleapis, grpc-proto) frequently include inline replacement code (e.g., `Use foo.bar.Baz with the new request shape: { ... }`) that 200 chars would truncate mid-context; 500 chars preserves enough context for the rendered message to be actionable while still bounding DoS amplification by a factor of ~10× against multi-KB adversarial comments. `/ce:plan` may revisit if the corpus measurement shows P95 comment-length distributions that warrant a different number.
- **Truncate-then-sanitize order:** truncate first, sanitize second. `_CONTROL_CHAR_TABLE` is per-codepoint; truncation cannot split a sanitizer-relevant sequence.
- **Lint CLI source-info wire-up scope: BOTH proto mode AND descriptor-set mode.** Extends `_load_descriptor_sets_to_result` to capture `FileDescriptorProto` references before `pool.Add(fd)`. Cost is ~10 lines; correctness gain is symmetric behavior across input modes. R6 rules work the same in `--proto` mode and `--descriptor-set` mode (assuming the descriptor set was built with `--include_source_info`).
- **`source_info_descriptors=None` behavior:** R6 rules emit findings for every deprecated element when `leading_comment` returns None. Documented per R6-CLI as a known limitation; no new `LintRuntimeWarning.category` value in U3 (deferred — see Non-Goals).
- **Severity: `warning`.** Locked at parent brainstorm + parent plan; promotion to `error` is a D6c decision.
- **Profile: `default` only.** Locked at parent brainstorm. `recommended` stays buf BASIC parity (R6 has no buf analogue).
- **`source_spec=""` (empty)** on all 5 rules excludes them from the parity harness per [[KTD-10-source-spec-empty-string-excludes-from-parity]].
- **`FileDescriptorProto` references survive `pool.Add(fd)`** — settled by U1 prior art at `src/protokit/_cli_utils.py:221-269` (`_populate_pool_with_capture` ships exactly this pattern: `captured[fd.name] = fd` is recorded around `pool.Add(fd)`, and U1's test suite verifies the captured reference retains `.source_code_info` after pool consumption). U3 mirrors the pattern in `_load_descriptor_sets_to_result`. No deep-copy fallback needed; removed from Risks.

## Success Criteria

1. **5 R6 rules registered and visible** under `protokit lint --profile default --format=json <fixture>`. All 5 fire when the fixture has `deprecated = true` elements without a satisfying replacement comment.
2. **5 R6 rules silent** under `protokit lint --profile recommended <fixture>` (R6 not in recommended).
3. **Comment-aware happy path** verified end-to-end: a fixture with `field x = 1 [deprecated = true]` AND leading comment "Use NewField instead." produces zero findings for that field. Each ElementKind has its own happy-path fixture.
4. **`include_source_info=True` flows through the lint CLI:**
   - Proto mode: `compile_protos_to_result(...)` at `cli.py:731` passes `include_source_info=True`.
   - Descriptor-set mode: `_load_descriptor_sets_to_result` returns a `CompileResult` with non-None `source_info_descriptors` when the input descriptor set has source info.
   - End-to-end: `protokit lint --descriptor-set <set built with --include_source_info> --profile default` fires R6 rules the same way `protokit lint --proto <source>` does. (Implementation path — direct `fd` reference per U1 prior art at `_cli_utils.py:221-269` — is established; no fallback path needed.)
5. **Adversarial safety:**
   - Multi-KB leading comment (5KB+) — finding's `params["comment"]` is at most 500 chars.
   - Comment with raw `\n`, `\r`, U+2028, U+2029, U+0085, ASCII control chars — sanitized in `params["comment"]` (no stderr forge possible).
6. **BUILTIN_PACKS membership-pin test passes** with the extended `expected` tuple. The membership-pin test is the single source of truth for "what packs ship by default."
7. **Cold-import contract holds.** `import protokit.schema` does NOT transitively load `protokit.schema.lint.rules.options.deprecated_replacement`. The existing `tests/schema/lint/test_cold_import_extended.py` catches violations. The `import re` at the new module's top is stdlib; no transitive descriptor-pb2 loads.
8. **Static-analysis ratchet holds.** New paths (`src/protokit/schema/lint/rules/options/deprecated_replacement.py`, `tests/schema/lint/rules/options/test_deprecated_replacement.py`, `tests/schema/lint/rules/options/fixtures/`) added to `tests/test_static_analysis.py:_LINT_PATHS` in the same commit per [[pytest-static-analysis-gate-ratchet]].
9. **D6b U1+U2 regressions: zero.** The 1600-test baseline continues to pass. Tests asserting `source_info_descriptors=None` in pre-U3 CLI invocations are updated to expect the populated mapping. Pre-counted impact at brainstorm time (grep `source_info_descriptors` in `tests/`): **5 affected test files** with **26 line-level `is None` assertions**:
   - `tests/test_cli_utils.py` — proto-mode CLI helpers; some assertions flip to non-None when U3 wires `include_source_info=True`.
   - `tests/schema/lint/test_model.py` — likely default-False guards on `CompileResult`; remain valid (no change).
   - `tests/schema/lint/test_compile_include_source_info.py` — U1's explicit include/exclude matrix; assertions stay correct (each branch tests its own flag value).
   - `tests/schema/lint/test_engine_source_info_descriptors_injection.py` — U2's engine-injection coverage; existing assertions stay correct.
   - `tests/schema/lint/rules/options/test_comments.py` — U2's helper unit tests; pure-input tests, no CLI dependence.
   `/ce:plan` enumerates per-line and classifies each into (a) intentional default-False guard that stays None (no change), (b) proto-mode CLI assertion that flips to non-None (U3 ratchet), or (c) needs new fixture. If the count of (b) exceeds ~10 sites, consider splitting the test-assertion ratchet into a prep commit ahead of U3's main commit.
10. **Per-rule demotion via `[tool.protokit.lint.severities]` works** for any of the 5 R6 rule_ids — verified by a fixture pyproject + a runtime test.

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Starting 4-pattern regex set has too-low recall on real-world deprecation comments — R6 over-reports legitimate replacement-tagged deprecations | Severity `warning` at launch limits CI blast radius. `/ce:plan` corpus tuning extends the pattern set if signal is high. Promotion to `error` deferred to D6c after measurement. |
| `_load_descriptor_sets_to_result` modification breaks existing descriptor-set tests | Audit existing tests at `tests/schema/lint/test_cli_descriptor_set_mode.py` (or wherever) in U3. The change is additive (new `source_info_descriptors` field in the returned `CompileResult`); existing assertions on `pool`, `root_files`, `diagnostics` are unaffected. |
| Proto-mode CLI tests asserting `source_info_descriptors is None` (pre-U3 baseline) break when U3 flips `include_source_info=True` | Audit needed. The brainstorm assumes such tests exist and is conservative; U3's CLI-mode regression suite ratchets up the expectation. `/ce:plan` enumerates the affected test sites. |
| `_load_descriptor_sets_to_result` capture of `FileDescriptorProto` references doesn't survive `pool.Add(fd)` | **Resolved** by U1 prior art at `src/protokit/_cli_utils.py:221-269`. `_populate_pool_with_capture` ships the identical capture-around-Add pattern; U1's test suite verifies `.source_code_info` retention. U3 mirrors the pattern. No deep-copy fallback needed. |
| Adversarial multi-KB comment fixture inflates the test repo size | 5KB fixture is small; co-locate under `tests/schema/lint/rules/options/fixtures/` and reuse across the 5 ElementKind tests via parameterization. |
| BUILTIN_PACKS membership test brittle to module-add order | The existing test pins exact membership tuple. Test update is mechanical; the brittleness is intentional per the pack-curation discipline. |
| R6 rules silently over-report on descriptor-set inputs built without `--include_source_info` (no runtime warning until D6c) | Documented in each rule's docstring + U7 CHANGELOG. Workaround paths (proto mode, `--include_source_info` rebuild, severities demotion) all available. |
| R6 false-positive epidemic in production (heuristic mismatches real-world phrasings) | Severity `warning` doesn't break CI. Per-rule demotion via `[severities]` available. The 4-pattern starting set is intentionally narrow per high-precision bias. |

## Assumptions

- **U1's `include_source_info=True` cost** (10-30% descriptor-set size, per U1's cross-version verification) is acceptable for every lint invocation. Non-lint consumers (compat, codegen, direct API) keep the zero-cost default. Verified at U1; carried forward.
- **`leading_comment(...)`'s O(N) scan over `source_code_info.location[]`** is acceptable for the rule-dispatch frequency. Each R6 rule does one scan per deprecated element; large protos with many deprecated elements pay O(N × M) total, where N = locations in file and M = deprecated elements. Mitigation deferred to D6c if measurement shows hot-path issues.
- **`FileDescriptorProto` references survive `pool.Add(fd)`** when captured Python-side before the call — **settled by U1 prior art at `src/protokit/_cli_utils.py:221-269` and U1's test suite**. No further verification needed in U3.
- **`source_info_descriptors` keys equal `ctx.file.name`** for every file the engine walks. The keys are the `fd.name` strings recorded into `pool.Add(fd)`, and `ctx.file.name` is the same string registered in the `DescriptorPool`. U3 verifies this end-to-end via a descriptor-set-mode regression test that asserts `leading_comment(ctx.source_info_descriptors, ctx.file.name, path)` resolves non-None for at least one ctx in the dispatch walk on a fixture descriptor set built with `--include_source_info`.
- **The 4-pattern starting set has high precision** on canonical deprecation comments. Verified at `/ce:plan` time against fixture corpus.
- **Existing `_safe_for_stderr` table** (U+0085, U+2028, U+2029, ASCII control chars per D5 U5) covers the comment-content threat model for the human-rendered (stderr) emit path. JSON/SARIF output paths use `json.dumps`'s independent escape behavior. See R6c for the per-path threat-model decomposition.

## Output Structure (this unit's commit shape)

U3 is one cohesive commit per [[delivery-boundary-unit-commit-composition]]'s per-unit-equivalent shape (excluding the delivery boundary cluster at U7). Commit composition:

- **Source:**
  - `src/protokit/schema/lint/rules/options/deprecated_replacement.py` (NEW — 5 rules + helper + patterns + RULES tuple)
  - `src/protokit/schema/lint/rules/__init__.py:84` (BUILTIN_PACKS — append `deprecated_replacement`)
  - `src/protokit/schema/lint/cli.py:731` (`compile_protos_to_result(..., include_source_info=True)`)
  - `src/protokit/schema/lint/_cli_utils.py:259-403` (`_load_descriptor_sets_to_result` — capture `source_info_descriptors` before `pool.Add`)
- **Tests:**
  - `tests/schema/lint/rules/options/test_deprecated_replacement.py` (NEW — 5-rule family unit tests, happy + sad paths)
  - `tests/schema/lint/rules/options/fixtures/` (NEW — small `.proto` corpus, one fixture per ElementKind + 1-2 adversarial fixtures)
  - `tests/schema/lint/test_builtin_packs.py:79` (extend `expected` tuple)
  - `tests/schema/lint/test_cli_proto_mode_source_info.py` (NEW or extend — assert source_info flows through proto-mode CLI)
  - `tests/schema/lint/test_cli_descriptor_set_source_info.py` (NEW — assert source_info flows through descriptor-set-mode CLI when present, None when absent)
  - `tests/test_static_analysis.py:_LINT_PATHS` (extend per ratchet)

Estimated test count: +25-40 new tests (5 rule × ~5 scenarios = 25; +5-10 CLI-wire-up tests; +adversarial). Brings the suite to ~1625-1640 passing.

## Sources & References

- **Parent brainstorm:** `docs/brainstorms/2026-05-14-protokit-lint-delivery-6b-option-aware-and-multi-language-requirements.md` (R6 section: lines 32-47; R6c section: lines 75-79; Open Questions: lines 146-162).
- **Parent plan:** `docs/plans/2026-05-14-001-feat-protokit-lint-d6b-option-aware-and-multi-language-plan.md` (Unit 3 section: lines 391-440).
- **U2 per-unit plan:** `docs/plans/2026-05-14-002-feat-d6b-u2-leading-comment-helper-plan.md` (K-6 `source_info_descriptors=None` semantic resolution).
- **Helper module shipped at U2:** `src/protokit/schema/lint/rules/options/_comments.py` (`descriptor_path` + `leading_comment`).
- **Sanitizer:** `src/protokit/schema/lint/_cli_utils.py:198-245` (`_CONTROL_CHAR_TABLE` + `_safe_for_stderr`).
- **Lint CLI call site:** `src/protokit/schema/lint/cli.py:731` (`compile_protos_to_result(...)`).
- **Descriptor-set loader:** `src/protokit/schema/lint/_cli_utils.py:259-403` (`_load_descriptor_sets_to_result`).
- **Pattern modules to mirror:** `src/protokit/schema/lint/rules/imports.py` (8-rule + shared-helper shape), `src/protokit/schema/lint/rules/naming.py` (8-rule shape).

### Institutional learnings applied

- [[buf-parity-divergence-documentation-discipline]] — each R6 rule docstring documents protokit-original status (no buf analogue).
- [[pytest-static-analysis-gate-ratchet]] — new paths added to `_LINT_PATHS` + `BUILTIN_PACKS` membership-pin extension in the same commit they're created.
- [[delivery-boundary-unit-commit-composition]] — U3 commit shape (excluding the delivery-boundary cluster at U7).
- [[no-raise-contract-extends-to-post-init-failures]] — the descriptor-set loader's `MappingProxyType` wrap of `source_info_descriptors` happens at the `CompileResult` construction site (via `__post_init__`, not by manual wrap in `_load_descriptor_sets_to_result`); the loader passes a plain dict.

### Review history

- **2026-05-15 document-review pass:** 6 personas (coherence + feasibility + product-lens + security-lens + scope-guardian + adversarial). 10 auto-fixes applied in-doc: (1) R6 rule body shape corrected to actual `@lint_rule(..., message_template=...)` + `ctx.emit(violation_kind=..., params=...)` API per `imports.py:64-93` and `model.py:918-923` (P1, critical — original draft would have crashed at first emit); (2) capture-ordering of `source_info_descriptors[fd.name] = fd` clarified to AFTER `pool.Add(fd)` succeeds, with dedup-collision-skip path explicit; (3) BUILTIN_PACKS entry typed correctly (`tuple[ModuleType, ...]` — module ref, not string); (4) import discipline mirroring `imports.py:42-58` (TYPE_CHECKING-guarded context aliases) specified; (5) pool.Add survival invariant resolved by citing U1 prior art `_populate_pool_with_capture` at `src/protokit/_cli_utils.py:221-269` — deep-copy fallback removed; (6) `fd.name == ctx.file.name` symmetry assumption added; (7) 500-char truncation rationale strengthened (real-world canonical comments include inline code samples); (8) R6c sanitization scope decomposed per emit path (human/JSON/SARIF/JUnit) — `_safe_for_stderr` load-bearing for human, defense-in-depth for structured; (9) Success Criterion 9 test-impact pre-enumerated (5 affected test files, 26 line-level `is None` assertions, classifier triage deferred to /ce:plan); (10) Success Criterion 4 implementation path settled per U1 prior art (no fallback path needed). 5 strategic findings added to Open Questions for `/ce:plan` resolution: commit shape (atomic U3 vs split U3a/U3b), descriptor-set-without-source-info runtime signal, pattern-set extensibility (fixed vs user-configurable), precision/recall ship-gate, `message_template` `{comment}` interpolation policy.

### Next step

`/ce:plan` against this brainstorm + the parent D6b plan's U3 section + U2's per-unit plan (as the reference shape for per-unit plans in this delivery). `/ce:plan` resolves the 7 deferred questions in Open Questions (regex set finalization, docstring shape, adversarial fixture composition, `message_template` `{comment}` policy, `{`/`}` escape, commit shape split, descriptor-set runtime signal, pattern-set extensibility, precision/recall ship-gate) and produces the per-unit plan at `docs/plans/2026-05-15-001-feat-d6b-u3-r6-deprecated-replacement-plan.md`.
