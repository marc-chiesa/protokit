---
title: "Length cap on composed string with `\\\"` escapes splits the escape pair, stranding a lone backslash and diverging from buf's wire format"
date: 2026-05-17
category: docs/solutions/logic-errors
module: protokit.schema.lint.rules.package_same
problem_type: logic_error
component: tooling
symptoms:
  - "Lint finding's params[\"values_payload\"] ends with a lone backslash"
  - "Rendered human-format message terminates with malformed `...AAAA\\` fragment instead of a closed quoted value list"
  - "Wire-format byte-divergence from buf v1.69.0 on adversarial inputs with inner-quote-bearing values near the 500-char composed-string boundary"
  - "Triggered only on adversarial inputs; happy-path and typical-length values are unaffected"
  - "Test-suite is green; bug latent until value length crosses the cap boundary after `_escape_inner_quote` expansion"
root_cause: logic_error
resolution_type: code_fix
severity: medium
related_components:
  - testing_framework
tags:
  - escape-sequences
  - truncation
  - wire-format
  - buf-parity
  - dangling-backslash
  - values-payload
  - package-same
  - protokit-lint
---

# Length cap on composed string with `\"` escapes splits the escape pair, stranding a lone backslash and diverging from buf's wire format

## Problem

A 500-character length cap applied AFTER `_escape_inner_quote` has expanded each inner `"` to `\"` (two characters) can land precisely between a `\` and its `"` partner, leaving a stranded backslash at the cap boundary with no semantic meaning. The resulting `params["values_payload"]` ends with a lone `\` that is byte-divergent from buf v1.69.0 (which never produces an unbalanced escape pair) and renders incorrectly in human-format lint messages.

## Symptoms

- `params["values_payload"]` ends with `\` for the affected finding.
- Wire-format byte-divergence from buf v1.69.0 on adversarial inputs (any `go_package`/string-attr value of length ~482 chars containing an inner quote, combined with a second value of ~483 chars, crosses the 500-char composed-string boundary at the `\"` escape pair).
- Rendered message ends with malformed `... \` fragment instead of a properly closed value list.
- Happy-path values and typical multi-KB inputs are unaffected (the boundary case is narrow).
- All R7 PACKAGE_SAME_* rules can be affected — the helper is shared.

## What Didn't Work

**Plan-time conclusion that "cap runs after composition" was sufficient.** The original D6b U4 plan correctly required composition before length-cap (so the `"X,Y"` payload structure was preserved), but this was incorrectly read as the COMPLETE truncation correctness story. Composition-before-cap is necessary but not sufficient when the composed string contains structural multi-character escape sequences.

**Per-value sub-cap (rejected alternative).** Capping each value individually before composition (e.g., `[:480]` per value) would prevent the cap boundary from ever landing on a `\"` pair, but it breaks byte-parity with buf for under-cap values whose full string buf preserves. Rejected per the plan's "no per-value sub-cap" decision; the escape-pair-safe post-truncation guard (Solution below) is byte-compatible.

**Catching it in pre-merge review without a regression test.** All three reviewers who saw it (correctness `RR-1 @ 0.62`, testing `T-03 @ 0.82`, adversarial `ADV-1 @ 0.92`) flagged the issue from different angles. The merged confidence after 3-way convergence was capped 1.0 — but without a concrete regression test, a future refactor could re-introduce the bug. See ce-review-convergence-rescues-sub-threshold-findings-2026-05-17 for the BOOST mechanism that escalated this to P2 gated_auto.

## Solution

Extracted helper `_truncate_values_payload` in `src/protokit/schema/lint/rules/package_same.py:213-239`:

```python
def _truncate_values_payload(payload: str) -> str:
    """``_safe_for_stderr`` + 500-char cap with backslash-escape-safe boundary."""
    safe = _safe_for_stderr(payload)[:500]
    if safe.endswith("\\"):
        # Strip the orphaned backslash from a split ``\"`` escape pair.
        safe = safe[:-1]
    return safe
```

Applied at the single composition site in `_check_package_option`:

```python
ctx.emit(
    violation_kind=rule_id,
    params={
        "package": _safe_for_stderr(ctx.file.package)[:500],
        "option_attr": _safe_for_stderr(option_attr)[:500],
        "values_payload": _truncate_values_payload(values_payload),
    },
)
```

Regression test `test_truncation_never_strands_backslash_from_split_escape_pair` in `tests/schema/lint/rules/test_package_same.py:848-895` engineers the exact boundary case:

```python
proto_a = (
    'syntax = "proto3";\n'
    "package smoke.boundary;\n"
    'option go_package = "' + ("A" * 482) + '\\"' + '";\n'
)
proto_b = (
    'syntax = "proto3";\n'
    "package smoke.boundary;\n"
    'option go_package = "' + ("B" * 483) + '";\n'
)
# ... run lint ...
assert not payload.endswith("\\"), (
    f"payload ends with stranded backslash from split escape pair: "
    f"...{payload[-20:]!r}"
)
```

## Why This Works

`_escape_inner_quote` replaces each `"` with `\"` (backslash + quote, two characters) BEFORE composition. After `",".join(escaped_values)`, the composed string is a flat byte sequence where some `\"` pairs are structurally atomic — the backslash carries meaning ONLY as the opener of the escape sequence. A naive `[:500]` slice cuts at a byte offset, not a token boundary; it has no awareness of which positions are "safe."

The post-truncation guard `if safe.endswith("\\"): safe = safe[:-1]` treats a trailing `\` as evidence that the cap just split a `\"` pair (since a non-escape backslash would have been removed or kept by `_safe_for_stderr`, which currently passes `\` through unchanged). Removing the orphaned `\` reduces the payload by at most one character (the cap boundary moves from 500 to 499), but the byte-format is now compatible with buf's output for the same inputs.

The five-stage pipeline that makes this work:

1. Per-value structural escape: `_escape_inner_quote(v)` for each `v` in `sorted(declared_set)`
2. Composition: `",".join(escaped_values)` and outer template wrapping → full payload string
3. Control-char sanitization: `_safe_for_stderr(payload)` — neutralizes control chars; passes `\` through
4. Length cap: `[:500]` — may land at a `\"` boundary on adversarial inputs
5. Escape-pair repair: `endswith("\\")` guard — strips the orphan if step 4 split a pair

Steps 1-4 already existed before the fix; step 5 is the addition that closes the gap.

## Prevention

> **2026-05-18 update (D6b U6 ce:review):** the original `endswith("\\")` single-char trailing guard prescribed below is **necessary but not sufficient** once the helper supports doubled-escape patterns (`\` → `\\`). When the 500-char cap lands at the END of a complete `\\` pair, the single-char guard incorrectly strips one backslash and produces an orphan — the exact condition the guard exists to prevent. The general-case discipline is an **odd-count trailing-backslash check** (strip one only when count is odd). See [[truncation-guard-odd-count-discipline-for-doubled-escape-pairs-2026-05-18]] for the generalized rule + D6b U6 ce:review repro. The guidance below remains correct for single-escape-pair openers but should be read as a special case of the odd-count rule.

- When composing strings that contain structural multi-character escape sequences (any format where 2+ adjacent characters are semantically atomic), apply the length cap and then run a post-cap structural integrity check.
- For the SINGLE-escape-pair case (one-char escape opener like `\` before `"`), the post-cap check is a constant-cost predicate: `endswith("\\")` for backslash openers, `endswith("&")` for HTML entity openers, etc. No lookahead or full re-parse needed.
- For the DOUBLED-escape case (same character repeated as escape mechanism — e.g., `\` → `\\` for literal backslash), the single-char predicate is WRONG. Use the odd-count discipline:
  ```python
  trailing = len(safe) - len(safe.rstrip("\\"))
  if trailing % 2 == 1:
      safe = safe[:-1]
  ```
  Odd count = genuine orphan from a split pair; even count = complete doubled pair (leave intact).
- Alternative architecture: cap BEFORE escape composition (a per-value sub-cap that bounds escaped-value length pre-composition). Rejected here because it breaks buf byte-parity for under-cap values; preferred when wire-format parity is not a constraint.
- ALWAYS pair a wire-format truncation helper with a regression test that engineers the exact boundary case. Calculate the boundary arithmetic explicitly: in this case 482-char value + inner `"` → 484 escaped chars; 484 + 1 (comma) + first 15 chars of value B + premium = 500 exactly. The test fixture must reproduce that arithmetic; a naive multi-KB value test misses the boundary entirely.
- **When adding a NEW escape class to an existing helper, audit every guard that inspects trailing runs of the new escape character.** A guard designed for a split-pair (single stranded char) must be upgraded to an odd-count check before the new escape class ships. The D6b U6 ce:review caught this regression class via cross-reviewer convergence; see [[truncation-guard-odd-count-discipline-for-doubled-escape-pairs-2026-05-18]].
- During ce:review, treat 3-way independent reviewer convergence on a single concern as a strong signal to elevate severity, even when each reviewer's individual confidence is already above gate — see ce-review-convergence-rescues-sub-threshold-findings-2026-05-17 for the BOOST mechanism. The D6b U6 case is now Case 4 (FIX-INDUCED SECOND-ORDER) in that doc.

## Related Issues

- [[module-name-newline-injection-stderr-forge-2026-05-07]] — established `_safe_for_stderr` and the "every interpolated slot" sanitization principle. The escape-pair truncation guard layers on top of that sanitization: `_safe_for_stderr` neutralizes control chars; `_truncate_values_payload` adds length cap + escape-pair repair.
- ce-review-convergence-rescues-sub-threshold-findings-2026-05-17 — the multi-reviewer convergence mechanism that escalated this finding from individually-actionable to gated_auto with mandatory regression test.
- `src/protokit/schema/lint/rules/package_same.py:200-326` — the `_escape_inner_quote` + `_check_package_option` + `_truncate_values_payload` helpers in their canonical composition order.
- `tests/schema/lint/rules/test_package_same.py::TestAdversarialSanitization` — full adversarial test class housing the regression test alongside newline / U+2028 / U+2029 / multi-KB / control-char sanitization tests.
- D6b U4b plan: `docs/plans/2026-05-17-002-feat-d6b-u4-r7-package-same-revised-plan.md`
- Commit landing the fix: `dd606e7`
