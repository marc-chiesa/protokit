---
title: "replace_all substring collision when renaming an identifier whose new name contains the old as a substring"
date: 2026-05-19
category: docs/solutions/best-practices
module: development_workflow
problem_type: workflow_issue
component: development_workflow
severity: medium
applies_when:
  - "Renaming an identifier using replace_all (Edit tool, sed -i, perl -pi -e, vim :%s//g)"
  - "The new name contains the old name as a contiguous substring (e.g., directional-prefix renames like _FOO -> _BAR_FOO, or scoping qualifications)"
  - "Any occurrence of the new name has already been written to the file before the replace_all call (e.g., the definition line for the new identifier)"
  - "The rename affects multiple call sites scattered across one or more files"
tags:
  - replace-all
  - rename
  - substring-collision
  - edit-tool
  - identifier-rename
  - agent-workflow
  - tooling-pitfall
---

# replace_all substring collision when renaming an identifier whose new name contains the old as a substring

## Context

`replace_all` (whether via the Edit tool's `replace_all=true` mode, `sed -i 's/old/new/g'`, `perl -pi -e`, or vim `:%s//g`) is a pure string-substring operation. It has no concept of identifier boundaries, word boundaries, or AST nodes.

When renaming an identifier where the new name **contains the old name as a literal substring**, a `replace_all` call will corrupt every occurrence of the new name that was already written to the file — including the definition site introduced in the immediately preceding edit.

This trap is structurally common in one specific class of renames: **directional-prefix additions** (e.g., `_FOO` → `_BAR_FOO`, `Map` → `RuleIdMap`, `_BUF_X` → `_PROTOKIT_TO_BUF_X`). These renames feel mechanical — the old name is obviously a suffix of the new name — which makes the substring-collision risk easy to overlook.

In the D6c U4 ce:review follow-ups session: the rename was `_BUF_RULE_ID_MAP` → `_PROTOKIT_TO_BUF_RULE_ID_MAP`. Step 1 introduced the new identifier at the definition site. Step 2 issued `Edit replace_all=true, old_string="_BUF_RULE_ID_MAP", new_string="_PROTOKIT_TO_BUF_RULE_ID_MAP"` to update three call sites. Because `_BUF_RULE_ID_MAP` is a suffix of `_PROTOKIT_TO_BUF_RULE_ID_MAP`, the replace_all also matched inside the newly-written definition, producing `_PROTOKIT_TO_PROTOKIT_TO_BUF_RULE_ID_MAP`. The next test run raised `NameError: name '_PROTOKIT_TO_BUF_RULE_ID_MAP' is not defined` — the call sites now referenced a name that no longer existed anywhere in the file.

## Guidance

Before issuing any `replace_all` on an identifier rename, perform the substring containment check:

```
old_name in new_name  →  if True, substring collision is guaranteed
```

For the D6c case: `"_BUF_RULE_ID_MAP" in "_PROTOKIT_TO_BUF_RULE_ID_MAP"` → True. Collision is certain. Do not use `replace_all`.

**Three safe alternatives when the check returns True:**

**(a) Call-sites first, then introduce the new name.** Replace all call sites individually (using per-occurrence Edit calls with disambiguating surrounding context, or `replace_all` on the old-name BEFORE the new name exists in the file). Then introduce the new identifier name in a final edit. There is no old-name text left in the file when the new name appears for the first time, so a final cleanup `replace_all` (if needed) is collision-free.

**(b) Per-occurrence Edit calls with disambiguating context.** Edit each usage site with a surrounding-context window large enough to be unique. This avoids `replace_all` entirely and gives explicit control over each replacement.

**(c) Choose a new name that does not contain the old name as a substring.** If the naming is not yet constrained by external contracts (API surface, test expectations), pick a name where the substring check returns False. Example: `_PROTOKIT_BUF_RULE_MAP` instead of `_PROTOKIT_TO_BUF_RULE_ID_MAP` when the old is `_BUF_RULE_ID_MAP`.

**Quick diagnostic after a suspected collision:**

```bash
grep -n "_PROTOKIT_TO_PROTOKIT_TO_BUF" file.py        # doubled-prefix symptom
# or
python -c "import the.module" 2>&1 | grep NameError
```

The doubled-prefix symptom is usually unambiguous — the corrupted name contains the new prefix twice.

## Why This Matters

The failure mode is silent at edit time. The Edit tool applies the replacement without error because the replacement itself is syntactically valid text. The corruption is only visible at import or test time, when Python raises `NameError`. In a session where tests are not run immediately after each edit, a corrupted rename can persist across several subsequent edits and become harder to untangle.

The asymmetric cost is stark: the substring check is a one-second mental operation (or a one-line `python -c "print('old' in 'new')"`). The recovery from a collision — identifying corrupted sites, reverting, and re-doing the rename safely — costs 5–15 minutes and introduces risk of a second error during recovery.

`replace_all` is the right tool for global symbol renames when the old and new names are **non-overlapping** strings. It is the wrong tool when they overlap. The Edit tool's `replace_all` does not honor identifier-boundary semantics — it's a pure string-substring operation. The only reliable protection is the pre-rename containment check.

## When to Apply

- ANY identifier rename executed via `replace_all` (Edit tool with `replace_all=true`, `sed -i 's/old/new/g'`, `perl -pi -e`, vim `:%s//g`).
- The check is mandatory when the new name is formed by adding a prefix or suffix to the old name (directional-prefix renames, scoping-qualification renames, module-qualification renames).
- Also applies to non-identifier renames: file path segments, string literals used as dict keys, SQL column names renamed via migration scripts.

The check is cheap enough to be habitual — apply it for every `replace_all` rename, not only when the rename "feels risky."

## Examples

**D6c U4 concrete failure.**

```python
# Step 1: define new identifier (via Edit)
_PROTOKIT_TO_BUF_RULE_ID_MAP = { ... }

# Step 2: replace_all old_string="_BUF_RULE_ID_MAP"
#                    new_string="_PROTOKIT_TO_BUF_RULE_ID_MAP"
# Collision: "_BUF_RULE_ID_MAP" is a suffix of "_PROTOKIT_TO_BUF_RULE_ID_MAP"
# Result at definition site:
_PROTOKIT_TO_PROTOKIT_TO_BUF_RULE_ID_MAP = { ... }   # CORRUPTED
# Call sites now reference a name that doesn't exist → NameError at next test run
```

**Safe alternative (a) — call sites first, then definition.**

```python
# Step 1: update each call site individually with surrounding context
#   Edit: old_string = "x = _BUF_RULE_ID_MAP[key]"
#         new_string = "x = _PROTOKIT_TO_BUF_RULE_ID_MAP[key]"

# Step 2: rename the definition (now no old-name text remains elsewhere)
#   Edit: old_string = "_BUF_RULE_ID_MAP = {"
#         new_string = "_PROTOKIT_TO_BUF_RULE_ID_MAP = {"
```

**Generalized pre-rename containment check.**

```python
old_name = "_BUF_RULE_ID_MAP"
new_name = "_PROTOKIT_TO_BUF_RULE_ID_MAP"
assert old_name not in new_name, (
    f"Substring collision: {old_name!r} is a substring of {new_name!r}. "
    "Use per-occurrence edits or call-sites-first ordering instead of replace_all."
)
```

## Related

- The Edit tool's `replace_all` flag — pure string-substring operation; does not honor word boundaries or Python identifier boundaries. Same caveat applies to `sed -i 's/old/new/g'`, `perl -pi -e 's/old/new/g'`, and vim `:%s/old/new/g` when `old` is a substring of `new`.
- plan-review-verify-prior-art-citations-2026-05-15 — adjacent verify-before-act discipline at the planning/review layer. This doc covers the tool-mechanics analog: even when a rename feels mechanical, the containment check is the verify-before-act step.
