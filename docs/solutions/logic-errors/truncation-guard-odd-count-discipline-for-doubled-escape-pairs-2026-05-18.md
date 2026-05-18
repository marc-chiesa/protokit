---
title: Truncation guard for doubled-escape patterns requires odd-trailing-count discipline
date: 2026-05-18
category: docs/solutions/logic-errors
module: protokit.schema.lint.rules.package_same
problem_type: logic_error
component: tooling
symptoms:
  - "_truncate_values_payload returns a string ending in a lone backslash after truncating a value containing literal `\\` (a doubled escape pair) at the 500-char cap"
  - The existing `endswith("\\")` guard strips one char from a run of trailing backslashes, leaving an odd count — itself a dangling-backslash, the exact condition the guard was designed to prevent
  - Bug is fix-induced — triggered only after `_escape_message_value` (formerly `_escape_inner_quote`) was corrected to emit `\\` for literal backslashes in PHP namespace values
  - Unit test added with the original fix passes because the test does not exercise values long enough to cross the 500-char truncation boundary
root_cause: logic_error
resolution_type: code_fix
severity: medium
related_components:
  - testing_framework
tags:
  - escape-sequences
  - truncation
  - doubled-backslash
  - dangling-backslash
  - odd-count-discipline
  - wire-format
  - fix-induced-regression
  - package-same
---

# Truncation guard for doubled-escape patterns requires odd-trailing-count discipline

## Problem

`_truncate_values_payload`'s 500-char boundary guard was correct for its original design (split `\"` escape pairs) but became incorrect when a new escape class (`\` → `\\` doubling) was added to `_escape_message_value` in D6b U6. The guard read:

```python
safe = _safe_for_stderr(payload)[:500]
if safe.endswith("\\"):
    safe = safe[:-1]
```

With U6's backslash-doubling step, a literal trailing backslash in a value expands to `\\` (a complete 2-backslash pair in the Python string representation). When `[:500]` lands at the end of a complete `\\` pair, both backslashes are inside the window, `endswith("\\")` is `True`, the guard strips one, and the result is a single orphan backslash — the exact condition the guard was designed to prevent.

## Symptoms

- `_truncate_values_payload` returns a string ending with a single `\` (odd trailing-backslash count) when a PHP namespace or similar option value contains a literal trailing backslash AND the composed payload is between 501 and ~514 chars.
- The regression test `test_truncation_preserves_complete_doubled_backslash_pair` fails with: `payload ends with odd-count trailing backslashes (1), indicating a split escape pair: ...AA\\`.
- The issue only manifests at a specific value length: 485 `A` chars plus one trailing backslash produces a 487-char escaped value; composed with the `both values "..." and no value` prefix (13 chars) and suffix (14 chars), the total is 514 chars, placing `[:500]` precisely at the end of the `\\` pair.

## What Didn't Work

**The U4b-era single-char trailing guard:**
```python
if safe.endswith("\\"):
    safe = safe[:-1]
```

This was designed for the `\"` escape pair (2 distinct characters where `\` is the opener). When `[:500]` lands between `\` and `"`, the trailing string ends with exactly 1 backslash (odd count = genuine orphan). Stripping one is correct.

When `\\` is the doubled-escape form (same character repeated as the escape mechanism), the failure mode inverts. The cap falls at the END of the pair, the trailing string ends with 2 backslashes (even count = complete pair), and stripping one is incorrect — it produces an orphan from a complete pair.

**An `endswith("\\\\")` check also fails**: it would trigger on 2, 4, or any even count, stripping one from every even-count tail rather than leaving them intact.

**Adding more buf-smoke fixtures with PHP namespace values would not have caught this** specifically because the bug requires a value length that lands the cap precisely at the end of the `\\` pair. The 21 U4a-committed fixtures all use short values (well under 500 chars in the composed payload); none exercise the truncation boundary.

## Solution

Count trailing backslashes and strip only when the count is odd:

```python
def _truncate_values_payload(payload: str) -> str:
    """``_safe_for_stderr`` + 500-char cap with backslash-escape-safe boundary.

    Handles two boundary-unsafe positions:
      1. Split `\\"` escape pair (D6b U4b origin case): odd trailing-
         backslash count (1) → strip the orphan.
      2. Split `\\\\` doubled-backslash pair (D6b U6 ce:review case):
         even trailing-backslash count (2) → leave intact.

    Odd-count discipline subsumes both: strip one only when the
    trailing-backslash count is odd (true orphan); leave even counts
    intact (complete doubled pairs).
    """
    safe = _safe_for_stderr(payload)[:500]
    trailing_backslashes = len(safe) - len(safe.rstrip("\\"))
    if trailing_backslashes % 2 == 1:
        safe = safe[:-1]
    return safe
```

**The regression test fixture** (`tests/schema/lint/rules/test_package_same.py::TestAdversarialSanitization::test_truncation_preserves_complete_doubled_backslash_pair`):

```python
# 485 'A' chars + literal trailing backslash.
# Proto-source `\\` embeds a single literal backslash in the option string.
# PHP namespace is the natural backslash-bearing rule_id.
proto_with_trailing_backslash = (
    'syntax = "proto3";\n'
    "package smoke.boundary_php;\n"
    'option php_namespace = "' + ("A" * 485) + '\\\\' + '";\n'
)
proto_without_option = (
    'syntax = "proto3";\n'
    "package smoke.boundary_php;\n"
    "// no php_namespace option declared\n"
)
# Mixed-presence fires both files (one declares, one omits).
# _escape_message_value doubles the trailing `\` to `\\` (487 chars).
# Composed payload is 514 chars; [:500] = prefix(13) + escaped(487).
# Tail ends with the complete `\\` pair.
# Odd-count guard: trailing_backslashes == 2 (even) → do NOT strip.
```

## Why This Works

The odd-count invariant generalizes across escape shapes:

- **`\"` split case**: `[:500]` lands between `\` and `"`. `"` is cut off. Tail ends with 1 `\` (odd) → strip. ✓
- **`\\` complete case**: `[:500]` lands after both `\` chars. Tail ends with 2 `\` (even) → do not strip. ✓
- **`\\"` combined case** (escaped backslash followed by inner quote): `[:500]` lands between `\\` and `"`. `"` is cut off. Tail ends with 3 `\` (odd) → strip one, leaving `\\`. ✓ The `\\` pair is intact.
- **`\\\\` four-backslash case** (e.g., a doubled-already-escaped backslash): tail ends with 4 `\` (even) → do not strip. ✓

The odd-count rule is equivalent to asking *"is the final backslash's escape partner inside or outside the window?"* An even count means all backslashes are paired within the window; an odd count means one is stranded.

## Prevention

1. **When adding a NEW escape class that doubles a character** (e.g., `\` → `\\`), immediately audit every guard that inspects trailing runs of that character. A guard designed for a split-pair (single stranded char) must be upgraded to an odd-count check before the new escape class ships.

2. **Add a regression test with a value length engineered to land `[:500]` precisely at the END of the doubled pair** — not in the middle and not one character past. This boundary is the only position the single-char guard mis-handles. The general formula: pick a value length such that `len(prefix) + len(escaped_value) == 500` exactly, where `escaped_value` ends in the doubled character.

3. **Generalize the pattern**: any "doubled-escape pattern" creates this trap. A guard of the form `if endswith(X): strip one` is correct only when the only way X appears at the boundary is as an orphan. Once X can appear as part of a complete doubled pair, the guard needs an odd-count (or equivalent parity) check.

4. **ce:review convergence is the corrective signal** when a fix introduces a second-order bug. The original `_escape_message_value` fix passed all internal tests; the U6 parity gate caught the FIRST bug (missing backslash escape); cross-reviewer convergence in ce:review (correctness + adversarial both providing concrete `value='A'*485+chr(92)` repros at confidence 0.88 + 0.97 → boosted to 1.00) caught the SECOND-ORDER bug introduced by the fix. See [[cross-reviewer-convergence-catches-fix-induced-second-order-bug-2026-05-18]].

## Related

- [[escape-pair-aware-truncation-dangling-backslash-wire-format-divergence-2026-05-17]] — original split-`\"`-pair case. This doc generalizes that pattern to doubled escapes; the original Prevention section's `endswith("\\")` guidance is superseded by the odd-count discipline here.
- [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]] — the parity gate that caught the FIRST bug whose fix introduced this SECOND-ORDER bug.
- [[cross-reviewer-convergence-catches-fix-induced-second-order-bug-2026-05-18]] — the ce:review mechanism that caught this second-order bug post-fix.
- [[module-name-newline-injection-stderr-forge-2026-05-07]] — `_safe_for_stderr` pipeline base layer that precedes the truncation guard.
