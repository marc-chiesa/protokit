---
title: "Multi-source field resolvers must apply equal coercion strictness across all input sources"
date: 2026-05-12
category: docs/solutions/best-practices
module: protokit.schema.lint._config
problem_type: best_practice
component: tooling
severity: medium
applies_when:
  - "A resolver merges the same config field from two or more sources (pyproject TOML, CLI overrides, env var, defaults)"
  - "Each source flows through its own coercer function with independently chosen strictness levels"
  - "The pyproject path uses strict `isinstance(value, bool)` (or equivalent narrow-type check) and rejects truthy non-bools"
  - "The CLI path could plausibly receive a non-canonical value type from a programmatic caller (test fixture, library importer)"
  - "Bool fields are especially at risk because `isinstance(True, int)` is True in Python — coercion via `bool(value)` silently accepts `[]`, `0`, `\"\"`, and other falsy non-bools"
related_components:
  - tooling
tags:
  - coercion
  - strictness
  - multi-source
  - config-resolver
  - cli-overrides
  - isinstance
  - bool
  - asymmetric
  - type-strictness
---

# Multi-source field resolvers must apply equal coercion strictness across all input sources

## Context

`ResolvedLintConfig.from_dict` resolves boolean config fields from
two surfaces: pyproject TOML (via the `table` argument) and
programmatic CLI overrides (via the `cli_overrides` dict). The
pyproject path uses `_coerce_no_builtin_rules`, which calls
`isinstance(value, bool)` and hard-errors on non-bool values —
`"true"`, `1`, `0`, and the empty string are all rejected. The
intent is that TOML's distinct `true`/`false` literals are the
only valid form.

The original CLI path used `bool(cli_no_builtin)` to coerce the
value. This created an asymmetric contract: pyproject
`no_builtin_rules = "true"` failed loudly with a typed error
message, but a CLI override of `[]`, `0`, or `""` silently
became `False`. Programmatic callers (test fixtures, library
importers) passing a non-bool got no feedback that they
violated the type contract — and Python's bool-as-int conflation
(`isinstance(True, int)` is True; `bool(0)` is False) makes the
loose `bool(value)` coercion especially dangerous because every
falsy value silently passes the gate.

The fix tightens the CLI path to match pyproject's strictness:
`isinstance(cli_no_builtin, bool)` is the gate, and anything else
raises `TypeError` with a message that names Click's `is_flag`
(the expected source of properly-typed bools) so the developer
knows where to look.

## Guidance

For any config field whose pyproject path uses **strict
`isinstance(value, T)` coercion**, the CLI override path must use
the **same isinstance check**, not a permissive coercion like
`bool(value)` or `str(value)`:

```python
# src/protokit/schema/lint/_config.py
from collections.abc import Mapping
from typing import Any

@classmethod
def from_dict(
    cls,
    table: Mapping[str, Any] | None,
    cli_overrides: Mapping[str, Any],
) -> "ResolvedLintConfig":
    # ... pyproject path: validated["no_builtin_rules"] has already
    # passed strict isinstance(value, bool) via _coerce_no_builtin_rules ...

    # CLI override path — must match pyproject's strictness.
    cli_no_builtin = cli_overrides.get("no_builtin_rules")
    if cli_no_builtin is None:
        # No CLI override — use pyproject value or default:
        resolved_no_builtin = validated.get("no_builtin_rules", False)
    elif isinstance(cli_no_builtin, bool):
        # Correct type — CLI wins:
        resolved_no_builtin = cli_no_builtin
    else:
        raise TypeError(
            "cli_overrides['no_builtin_rules'] must be bool or None; "
            f"got {type(cli_no_builtin).__name__}. Click's is_flag "
            "delivers Python bools by default — check the CLI wiring "
            "in cli.py if this fires.",
        )
```

**Three structural rules** for symmetric coercion strictness:

1. **The CLI path raises `TypeError`, not `ValueError`**. Pyproject
   coercion uses the project's standard `error_exit_with_code(...)`
   path because TOML parse errors are user-facing. CLI overrides
   come from programmatic callers, so a Python-typed `TypeError`
   is the right signal — it surfaces during the caller's test run,
   not in a user-visible exit-code stream.
2. **The error message names the upstream source**. "Click's
   is_flag delivers Python bools by default — check the CLI wiring
   in cli.py if this fires" tells the developer where to look. A
   generic "expected bool" wastes investigation time.
3. **`None` is the sentinel for "CLI did not supply"**. The
   `cli_no_builtin is None` branch is the documented protocol per
   [[click-parameter-source-detection-cli-config-precedence-2026-05-11]].
   `isinstance(None, bool)` is False, so a naive
   `if isinstance(value, bool)` ordering would mis-classify None as
   "missing the type contract" rather than "intentionally absent".
   Check `is None` first.

**Anti-pattern to avoid**:

```python
# DO NOT: silently coerces [], 0, "" to False — asymmetric with pyproject
resolved_no_builtin = bool(cli_overrides.get("no_builtin_rules") or False)
```

The `or False` makes this even worse — it doubles the silent-
acceptance window because both `None` (missing) and falsy non-bools
collapse to the same `False`.

## Why This Matters

**Asymmetric surfaces create invisible footguns**. A developer who
reads the pyproject docs ("must be `true` or `false`") and then
calls `from_dict` programmatically with
`cli_overrides={"no_builtin_rules": []}` has no reason to expect
that `[]` will silently become `False`. The contract said bool; the
method accepted a list without complaint.

**Test fixtures are the most common victim**. Test files frequently
construct `cli_overrides` dicts by hand. A typo
(`cli_overrides={"no_builtin_rules": None}` when the test author
meant `False`) is the exact scenario this guard catches — `None` is
intentionally the sentinel for "no CLI override", so it must not be
conflated with `False`. With the strict `isinstance` check, the
test fails with a clear type error pointing at the typo. With the
loose `bool(value)`, the test silently produces wrong behavior.

**The `bool(x)` coercion footgun is broader than it looks**.
`bool([])` is `False`, `bool(0)` is `False`, `bool("")` is `False`,
`bool({})` is `False`. All are confusable with a deliberate `False`
override, and none would surface as an error with the pre-fix code.
The post-fix `TypeError` with a message naming Click's `is_flag`
redirects the developer to the actual fix (typed bool at the
upstream callsite) immediately.

**Generalization beyond bool**. The same asymmetric-strictness trap
applies to any field whose pyproject coercion uses
`isinstance(value, str)` (rejects ints, lists), `isinstance(value,
int)` (rejects bools because of bool-as-int — use
`isinstance(value, int) and not isinstance(value, bool)`), or
narrow string-enum coercion. The CLI side must mirror.

## When to Apply

Apply this pattern whenever ALL of the following are true:

1. A config field has a typed-strict pyproject coercion (e.g.,
   `isinstance(value, bool)` rejecting truthy non-bools).
2. The same field is also settable via a `cli_overrides` dict in
   the resolver method.
3. The CLI surface comes from Click `is_flag` (or another framework
   that delivers typed Python bools). This means the correct type
   is always the narrow Python type, never a truthy value.

Do NOT apply when the field is intentionally lenient (e.g., accepts
`"true"` / `"yes"` / `"1"` strings from environment variables) — in
that case, both paths should share a single permissive coercion
function rather than splitting strict-on-one / lenient-on-the-other.
The principle is "same rule everywhere", not "always strict".

## Examples

### Asymmetric (pre-fix) — pyproject strict, CLI lenient

```python
# Pyproject path (strict — rejects "true", 1, 0):
def _coerce_no_builtin_rules(value):
    if not isinstance(value, bool):
        error_exit_with_code(
            "pyproject-config-invalid",
            f"no_builtin_rules must be a boolean; got {type(value).__name__}.",
        )
    return value

# CLI path (lenient — silently accepts [], 0, "" as False):
cli_no_builtin = cli_overrides.get("no_builtin_rules")
if cli_no_builtin is not None:
    resolved_no_builtin = bool(cli_no_builtin)  # FOOTGUN
else:
    resolved_no_builtin = validated.get("no_builtin_rules", False)
```

A programmatic caller passing
`cli_overrides={"no_builtin_rules": []}` gets `resolved.no_builtin_rules
== False`. Same caller passing
`{"no_builtin_rules": [], "_table": "...", ...}` to the pyproject
path equivalent would hit `_coerce_no_builtin_rules` and exit with
a typed error. Asymmetric.

### Symmetric (post-fix) — both surfaces enforce isinstance(bool)

```python
# Pyproject path unchanged.
# CLI path — now matches pyproject's strictness:
cli_no_builtin = cli_overrides.get("no_builtin_rules")
if cli_no_builtin is None:
    resolved_no_builtin = validated.get("no_builtin_rules", False)
elif isinstance(cli_no_builtin, bool):
    resolved_no_builtin = cli_no_builtin
else:
    raise TypeError(
        "cli_overrides['no_builtin_rules'] must be bool or None; "
        f"got {type(cli_no_builtin).__name__}. Click's is_flag "
        "delivers Python bools by default — check the CLI wiring "
        "in cli.py if this fires.",
    )
```

The post-fix path produces the same outcome regardless of which
surface the caller came through: typed bool or `None` is accepted,
everything else raises with a pointer to the upstream wiring.

### Generalization: same pattern for non-bool fields

```python
# Pyproject path (strict — rejects bools, lists, None):
def _coerce_max_warnings(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        error_exit_with_code(...)
    return value

# CLI path — mirror exactly:
cli_max = cli_overrides.get("max_warnings")
if cli_max is None:
    resolved_max = validated.get("max_warnings")
elif isinstance(cli_max, int) and not isinstance(cli_max, bool):
    resolved_max = cli_max
else:
    raise TypeError(
        "cli_overrides['max_warnings'] must be int or None; "
        f"got {type(cli_max).__name__}.",
    )
```

## Related Learnings

- [[click-parameter-source-detection-cli-config-precedence-2026-05-11]] — defines the `cli_overrides` dict shape and the `None`-sentinel protocol that this learning's branch ordering depends on
- [[normalize-at-input-boundary-2026-05-07]] — meta-principle: apply the same defensive rule at every entry point that touches user input (this learning extends the principle from string-case normalization to type-coercion strictness)
- [[cli-overrides-deferred-key-notimplemented-trip-wire-2026-05-12]] — companion learning on `cli_overrides` integrity: this learning enforces type discipline on *known* keys; the trip-wire learning hard-fails on *unknown* keys
- [[source-aware-error-messages-multi-source-resolved-value-2026-05-11]] — when a multi-source field fails coercion, the error message should name which source it came from
- [[shared-error-helper-source-label-caller-attribution-2026-05-11]] — pattern family for shared validation helpers reachable from multiple sources

## Discovered During

D6a U2 ce:review follow-ups (commit `739a0f2`). The maintainability
reviewer (M5), kieran-python reviewer (KP-3), and adversarial
reviewer (A2) independently surfaced the asymmetric strictness
during the 9-reviewer parallel pass on commit `5a464e2`. Three-way
convergence is the must-fix threshold per
[[apply-institutional-learnings-postdating-plan-during-ce-review-2026-05-09]].
