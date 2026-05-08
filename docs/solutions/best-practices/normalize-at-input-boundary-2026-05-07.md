---
title: "Normalize user-supplied names at the input boundary when any downstream consumer normalizes at lookup"
date: 2026-05-07
last_updated: 2026-05-08
category: docs/solutions/best-practices
module: tooling/cli
problem_type: best_practice
component: tooling
severity: medium
applies_when:
  - "A registry, dispatcher, or lookup table normalizes keys (lowercase, casefold, trim) at lookup time rather than rejecting non-canonical input"
  - "A function branches on the same user-supplied value that a downstream registry will normalize (e.g., `if flag == 'human'` followed by `registry.get(flag.lower())`)"
  - "A Click option uses `STRING` type backed by a case-insensitive registry — the registry normalizes at lookup but Click hands the raw value to local comparisons"
  - "A Click `Choice(case_sensitive=False)` value is later passed to another function that branches on it case-sensitively (Click's own normalization stops at the callback boundary)"
  - "An environment variable or config file feeds both a Python equality check and a case-insensitive lookup"
tags:
  - normalization
  - input-boundary
  - registry-lookup
  - case-insensitive
  - cli
  - click
  - string-comparison
  - discipline
---

# Normalize user-supplied names at the input boundary when any downstream consumer normalizes at lookup

## Context

This guidance emerged from the U4a delivery of the `protokit lint`
CLI (D3). The trigger was a high-impact bug in
`src/protokit/schema/lint/cli.py` where the `--format` flag value
flowed into two local equality comparisons without first applying
the same case normalization that the formatter registry applies
internally. (session history) Three independent reviewers
(correctness, adversarial, kieran-python) converged on the same
finding from three different angles — convergence that indicates a
recurring bug class, not a one-off.

The trust boundary looks like this:

```
User supplies:  --format=Human
                       │
Click receives as:  format_name = "Human"   (STRING type, no case coercion)
                       │
  ┌────────────────────┴───────────────────────────────────────────────┐
  │  CLI branches on format_name (pre-fix BUG zone):                   │
  │    if quiet and format_name != "human":  ← "Human" != "human" → fires│
  │    if statistics and format_name == "human":  ← "Human" == "human" miss│
  └────────────────────┬───────────────────────────────────────────────┘
                       │
get_formatter(format_name, kind)  →  _REGISTRY[(kind, "Human".lower())]
                                  → finds "human" entry just fine
```

The formatter registry at
`src/protokit/formatters/_registry.py` (lines 172, 201, 222)
normalizes every key to lowercase at registration AND lookup time.
The CLI did not. A user passing `--format=Human` (or
`PROTOKIT_FORMAT=Human` envvar) saw two distinct silent failure
modes:

1. `--quiet --format=Human` raised a misleading
   `Error: --quiet is incompatible with --format='Human';
   use --quiet only with the human format (the default).`
   The user IS asking for the human format — the comparison was the
   bug.
2. `--statistics --format=Human` rendered findings normally and
   exited 0 but silently suppressed the statistics footer. The flag
   appeared honored (no error, no warning) but produced no footer.

(session history) The bug was genuinely unknown until ce:review — it
was not flagged in the D3 brainstorm document-review pass, not
flagged in the plan-review pass, not surfaced during the U2 or U3
ce:review rounds. The U4a delivery introduced the failure surface
(the `format_name == "human"` comparisons), and the U4a ce:review
caught it via three converging reviewers in the same pass.

## Guidance

When a registry, dictionary, or lookup function normalizes its key
at lookup time (lowercase, casefold, trim, etc.), every caller that
branches on the same user-supplied value MUST apply the same
normalization at the input boundary — typically as the first
statement after argument parsing. This ensures all downstream
comparisons, log messages, and error messages see the same
canonical value the registry will see.

The rule is NOT "normalize before every registry call" — the
registry handles that. The rule IS: **normalize before any local
comparison on a value that the registry will normalize.** Local
comparisons are the blind spot.

A short checklist for a function that takes a user-supplied string:

1. Find every downstream consumer within the function's call chain
   (registry, DB, hashmap, comparison) — not a full codebase audit;
   just trace the value's path through the current function and its
   immediate callees.
2. Identify which consumers normalize and which don't.
3. If ANY consumer normalizes, apply the same normalization once at
   the function's input boundary.
4. Downstream code reads the already-normalized value without
   thinking about it.

Concrete instantiations:

- **Click `Choice(case_sensitive=False)`** produces a value Click
  has already lowercased. Local code can branch safely on the
  result. But: if you pass that value to another function that
  branches AGAIN, that other function should still apply
  belt-and-suspenders `.lower()`. See the in-codebase example below.
- **Click `STRING` type backed by a registry that lowercases.** The
  flag accepts any string; the registry normalizes on lookup. The
  caller MUST `value.lower()` before any local comparison. This is
  exactly the U4a shape.
- **Database collations like `utf8mb4_general_ci`.** SQL `WHERE name
  = ?` matches case-insensitively at the database level, but
  Python-side `==` does not. Same normalize-at-boundary discipline
  applies in the application layer.
- **Environment variables feeding a registry.** `PROTOKIT_FORMAT=Human`
  flows through Click into `format_name` unchanged. The envvar path
  and the flag path share the same normalization gap; fixing one at
  the input boundary fixes both.

## Why This Matters

**Silent inconsistency with high CI impact.** The fix is one line
(`format_name = format_name.lower()`). The bug is three distinct
failure modes: misleading mutex errors confusing operators about
which flags are compatible; silent feature suppression where the
flag appears honored (exit 0, no error) but the output is missing;
and CI scripts using `PROTOKIT_FORMAT=HUMAN` in their config seeing
non-interactive misbehavior with no diagnostic.

**Reviewer convergence as signal.** Three separate reviewers
examining the U4a diff from three independent angles all surfaced
the same bug. When reviewers with different threat models converge
on a single finding, it reliably indicates a class problem rather
than a one-off. (session history) The convergence was the trigger
for capturing this learning rather than treating it as a bugfix.

**Latent in any registry pattern in this codebase.** protokit has
multiple registries: formatter registry (`_registry.py`), lint rule
registry (inside `LintEngine`), profile resolution
(`LintProfile.from_pack`). Each is a potential repeat site. (session
history) The `--profile NAME` flag is the next domino: `profile_name`
is used raw (no `.lower()`) and passed to `LintProfile.from_pack(pack,
profile_name)` which matches against `@lint_rule(profiles=(...))`
tuple values. If `from_pack` matches case-sensitively (it does
today) and profile names are conventionally lowercase
(`@lint_rule(profiles=("default",))`), then `--profile Default`
silently produces an empty rule set — same class of bug, same fix
pattern, currently unfixed. Audit per-flag at delivery time.

## When to Apply

This discipline kicks in when ALL of the following hold:

1. A user-controlled string (CLI flag, envvar, config field, HTTP
   header, form field) flows through your code.
2. That string is used in at least one local equality / inequality
   comparison (Python `==`, `!=`, `in`, dict key lookup with a
   string literal, `match`/`case`, `startswith`).
3. The same string is also consumed by a downstream component that
   normalizes it at lookup time (a registry, a case-insensitive DB
   column, an API that canonicalizes).

The normalization gap exists when conditions 2 and 3 are both true
AND the normalization in condition 3 is invisible at the call site
(hidden inside a method body, a framework, a DB driver). The fix is
always condition 2: normalize at the input boundary so conditions 2
and 3 see the same value.

The inverse also matters: when the downstream consumer does NOT
normalize (case-sensitive lookup is the explicit contract — Python
import names, hashmap keys with no documented normalization), do
NOT pre-normalize in the caller. Pre-normalization there would
silently break valid case-sensitive lookups.

## Examples

### The U4a bug (anchor)

The registry's normalization (the hidden side) —
`src/protokit/formatters/_registry.py`:

```python
# Line 172 (register_formatter):
key = (kind, name.lower())   # stored lowercase

# Line 201 (_register_builtin):
key = (kind, name.lower())   # built-ins stored lowercase

# Line 222 (get_formatter):
return _REGISTRY[(kind, name.lower())]  # normalized at lookup
```

The docstring at line 138 states the contract explicitly: "Names
are case-insensitive. Stored as lowercase so the CLI's resolved
value (whatever case the user typed) hits the same entry."

The CLI before the fix —
`src/protokit/schema/lint/cli.py` (pre-`530010e` state):

```python
def main(..., format_name: str, ...):
    # No normalization. format_name is whatever Click received.
    if quiet and format_name != "human":        # BUG: "Human" != "human" fires
        raise click.UsageError(
            f"--quiet is incompatible with --format={format_name!r}; ..."
        )
    ...
    _main_impl(..., format_name=format_name, ...)


def _main_impl(..., format_name: str, ...):
    ...
    if statistics and format_name == "human":   # BUG: "Human" == "human" misses
        _emit_statistics_footer(report)
    ...
    formatter = get_formatter(format_name, FormatterKind.LINT_REPORT)
```

The fix at `cli.py:259`:

```python
def main(..., format_name: str, ...):
    format_name = format_name.lower()           # Normalize at input boundary
    if quiet and format_name != "human":        # Now "human" == "human" — correct
        raise click.UsageError(...)
    ...
    _main_impl(..., format_name=format_name, ...)
```

### The in-codebase safe pattern: `_MIN_SEVERITY_CHOICES`

(session history) The same `cli.py` already had a value-resolving
flag that survives the case-normalization gap by design. The
`--min-severity` option uses `click.Choice([...], case_sensitive=False)`,
and the consumption site adds an explicit `.lower()` at the dict
lookup:

```python
# At consumption (cli.py:419):
override_severity = _MIN_SEVERITY_CHOICES[min_severity.lower()]
```

Click's `case_sensitive=False` already lowercases the value before
the callback receives it, so the `.lower()` here is
belt-and-suspenders. Two things it defends against:

1. **A refactor that swaps `Choice` for `STRING`** (the most likely
   evolution — exactly what `--format` does in U4a, removing
   Click's normalization).
2. **A future change in Click's `case_sensitive=False` semantics** —
   long-standing and documented today, but the explicit boundary
   call costs nothing.

The pattern is durable. The `--format` flag chose `STRING` (not
`Choice`) because its valid values are registry-dependent, removing
Click's automatic normalization — so the boundary normalization
MUST come from the caller.

The `--format` flag chose `STRING` (not `Choice`) because its valid
values are registry-dependent. That choice is correct for D3 — but
it removes Click's automatic normalization, so the boundary
normalization MUST come from the caller.

### Regression tests pinning the discipline

`tests/schema/lint/cli/test_cli_ci_gating.py` `TestFormatCaseNormalization`:

```python
class TestFormatCaseNormalization:
    """Case normalization for --format / PROTOKIT_FORMAT."""

    def test_format_human_mixed_case_normalizes(
        self, bad_naming_descriptor_set,
    ):
        """--format=Human resolves identically to --format=human:
        statistics gate fires and quiet mutex does NOT fire."""
        result = CliRunner().invoke(
            lint_main,
            ["--format", "Human", "--statistics",
             str(bad_naming_descriptor_set)],
        )
        assert result.exit_code == 0, result.output
        assert "statistics:" in result.stdout

    def test_format_envvar_mixed_case_with_quiet_does_not_misfire(
        self, clean_descriptor_set,
    ):
        """PROTOKIT_FORMAT=HUMAN + --quiet should NOT raise the mutex."""
        result = CliRunner().invoke(
            lint_main, ["--quiet", str(clean_descriptor_set)],
            env={"PROTOKIT_FORMAT": "HUMAN"},
        )
        assert result.exit_code == 0, result.output
        # Negative assertion pins the bug: pre-fix, this exact
        # invocation produced "--quiet is incompatible with
        # --format='HUMAN'" on stderr. Post-fix, the mutex sees
        # "human" and stays silent.
        assert "--quiet is incompatible" not in result.output
```

These pin the two specific failure modes (silent footer suppression
+ spurious mutex misfiring via envvar). Future regressions surface
immediately.

## Related

- `docs/solutions/logic-errors/matcher-backend-path-resolution-skew-silently-empties-output-2026-05-02.md`.
  Structural parent of this learning. The matcher-backend bug is
  the same class of "transformation skew between two components
  operating on the same string key" — there it was
  `Path.resolve()` applied on one side but not the other; here it
  is `.lower()` applied on the registry side but not the CLI
  side. (session history) Discovered independently weeks earlier;
  the connection wasn't drawn until this learning. The matcher-
  backend doc's Prevention #5 already generalizes the rule
  ("matcher and source-of-truth must use identical resolution
  policies") and lists hostname case + URL canonicalization as
  examples — but didn't catch the formatter-registry instance.
- `docs/solutions/security-issues/module-name-newline-injection-stderr-forge-2026-05-07.md`.
  Companion contrast: that learning prescribes "sanitize at the
  OUTPUT boundary, not at import time"; this one prescribes
  "normalize at the INPUT boundary, not at comparison sites."
  Together they define the two boundary-discipline rules:
  normalize early (inputs), sanitize late (outputs).
- `docs/solutions/best-practices/cross-format-enum-string-parity-2026-05-08.md`.
  Output-side sibling discipline: where this doc covers
  input-boundary normalization for string values, that doc
  covers output-boundary serialization consistency for enum
  values across sibling formatters (JSON, SARIF, JUnit). Same
  family — boundary discipline — different direction.
  Together: normalize early at inputs (this doc); serialize
  consistently across sibling outputs (the new doc).
- Anchor commits: `530010e` (the one-line `format_name.lower()`
  fix + `TestFormatCaseNormalization`); `e86ee0d` (the U4a feat
  delivery where the bug was latent).
- Plan: `docs/plans/2026-05-04-001-feat-protokit-lint-d3-cli-plan.md`,
  Unit 4a — defined the `--format` / `--quiet` / `--statistics`
  trust boundary that introduced the comparison sites.
