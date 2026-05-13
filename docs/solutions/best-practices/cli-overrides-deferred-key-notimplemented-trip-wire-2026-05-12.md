---
title: "Hard-fail at deferred cli_overrides key boundaries with NotImplementedError"
date: 2026-05-12
category: docs/solutions/best-practices
module: protokit.schema.lint._config
problem_type: best_practice
component: tooling
severity: high
applies_when:
  - "A factory method (e.g., `ResolvedLintConfig.from_dict(table, cli_overrides)`) accepts a flexible `cli_overrides: Mapping[str, Any]` dict with a documented shape table"
  - "A new field is added to one input surface (pyproject TOML) in delivery unit N, but its sibling CLI flag wiring is deferred to unit N+1 or later"
  - "The override dict is loosely typed so unrecognized keys are not automatically rejected — `.get(key)` silently returns `None` for keys the method never reads"
  - "Two or more delivery units must remain in sync about which keys `cli_overrides` is expected to carry"
related_components:
  - tooling
tags:
  - cli-overrides
  - integration-boundary
  - notimplemented
  - silent-drop
  - phased-delivery
  - factory-method
  - from_dict
  - defensive-boundary
---

# Hard-fail at deferred cli_overrides key boundaries with NotImplementedError

## Context

`ResolvedLintConfig.from_dict(table, cli_overrides)` is the config
resolution boundary that merges pyproject TOML + CLI overrides into
the typed dataclass the linter engine consumes. Its docstring
declares a `cli_overrides` shape table listing every key the method
knows how to resolve.

D6a U2 added the `severities` field to pyproject parsing (R9a) but
deliberately deferred its CLI side-channel to a later delivery
(Unit 9 wires `--severity-override` flags). During the window
between those two units, `cli_overrides` legally cannot contain
`"severities"` — but nothing structural prevents a future
implementer from passing it. If `from_dict` simply never reads an
unrecognized key, the value silently disappears: the user-supplied
CLI value is dropped without any error, and the bug only surfaces
when a downstream user notices their flag does nothing.

The fix is a one-line trip-wire at the integration boundary: hard-
fail with `NotImplementedError` whenever the deferred key arrives.
The error fires at first invocation — the developer's own test run
during U9 implementation — not silently in production months later.

## Guidance

When a new config field ships to one input surface (pyproject) while
its sibling CLI surface is deferred to a later delivery, add an
explicit trip-wire in the factory method:

```python
# src/protokit/schema/lint/_config.py

@classmethod
def from_dict(
    cls,
    table: Mapping[str, Any] | None,
    cli_overrides: Mapping[str, Any],
) -> "ResolvedLintConfig":
    # ... existing validation of `table` ...

    # Hard-fail trip-wire: severities CLI wiring is deferred to U9.
    # If a future delivery passes cli_overrides["severities"] before
    # updating this method, hard-fail at first invocation rather than
    # silently dropping the user's value. The error message names the
    # delivery unit that will remove the guard so the implementer has
    # a clear action item.
    if "severities" in cli_overrides:
        raise NotImplementedError(
            "cli_overrides['severities'] is not yet wired into "
            "ResolvedLintConfig.from_dict — D6a U2 ships pyproject "
            "parsing only. Add the precedence branch here before "
            "exposing a CLI severities override.",
        )

    resolved_severities: Mapping[str, LintSeverity] = validated.get(
        "severities", {},
    )

    # ... rest of resolution ...
```

Three companion edits make the trip-wire complete:

1. **Update the `cli_overrides` shape table in the docstring** to
   explicitly note the key is intentionally absent and reference the
   unit that will add it:

   ```
   Intentionally absent: ``"severities"``. D6a U2 ships the
   pyproject-only parsing surface for R9a; no CLI side-channel
   exists yet. If a future delivery wires a CLI severities
   override, the key must be added to this shape table AND
   ``from_dict`` updated to read it — otherwise the override
   is silently dropped.
   ```

2. **When the deferred unit ships**, remove the trip-wire and replace
   with the actual precedence branch (CLI wins over pyproject for
   non-None values, etc.).

3. **Choose `NotImplementedError` over `ValueError`**: the semantic
   distinction matters. `ValueError` signals "this value is wrong";
   `NotImplementedError` signals "this code path doesn't exist yet —
   the integration is incomplete." The latter is the accurate
   diagnosis and points the implementer at the missing code, not at
   the value they passed.

## Why This Matters

The failure mode without this guard is insidious — observable only
by an end-user who notices their CLI flag does nothing:

- **Integration contract enforcement.** The `cli_overrides` shape
  table in the docstring is a contract. The trip-wire enforces it
  mechanically, not just documentarily. Documentation drift on a
  contract is silent; runtime drift fires immediately.
- **Phased delivery safety.** Multi-unit deliveries create windows
  where two halves of a feature exist independently. The trip-wire
  is the "bridge is out" sign for the missing half.
- **Grep-able marker.** A future developer searching `_config.py`
  for the right place to add CLI wiring finds the
  `NotImplementedError` immediately. Without it, they would need to
  audit every field's resolution logic to spot the missing branch.
- **Test-time failure, not production failure.** The trip-wire
  fires during the implementer's first U9 test invocation, where
  the diff is small and the fix obvious. The pre-fix silent drop
  would only surface when a downstream user files a "my flag does
  nothing" bug — long after the original context is gone.

This pattern is symmetric to (but distinct from)
[[click-parameter-source-detection-cli-config-precedence-2026-05-11]]:
that learning defines what the `cli_overrides` dict carries for
*known* keys (the `None` sentinel protocol for "CLI did not supply").
This learning adds a second invariant on the same structure: hard-
fail on *unrecognized* keys. The two learnings together cover the
full integrity contract for `cli_overrides`.

It is also complementary to
[[frozen-dataclass-paired-field-invariant-post-init-2026-05-11]]:
`__post_init__` is the right place for field-relationship invariants
(e.g., "exclude_source must be set when exclude is non-empty");
`from_dict` is the right place for integration-boundary key guards
(e.g., "no deferred-feature keys may arrive yet"). They cover
different construction-path defensive layers without overlapping.

## When to Apply

Apply this pattern whenever ALL of the following are true:

1. A config-resolution method accepts a flexible dict of overrides
   (not a typed dataclass with declared fields). The looseness is
   what makes silent-drop possible.
2. A new key is being added to that dict's documented shape.
3. The full wiring for that key is **NOT** complete in the current
   delivery unit. A future unit will add the precedence branch.

Do NOT apply to keys that are fully wired in the same commit — the
guard is only meaningful during the delivery window between partial
and complete wiring. Once both surfaces are wired, the guard
becomes dead code and should be removed in the same commit that
adds the real precedence branch.

## Examples

### Pre-fix (silent drop)

`from_dict` resolves `severities` from pyproject but never reads
`cli_overrides["severities"]`. A caller passing
`cli_overrides={"severities": {"naming/snake-case-fields": "info"}}`
sees no error; the override vanishes:

```python
def from_dict(cls, table, cli_overrides):
    # ... validate table ...
    resolved_severities = validated.get("severities", {})
    # cli_overrides["severities"] is never read — silent drop
    return cls(severities=resolved_severities, ...)
```

### Post-fix (hard-fail at boundary)

```python
def from_dict(cls, table, cli_overrides):
    # ... validate table ...
    if "severities" in cli_overrides:
        raise NotImplementedError(
            "cli_overrides['severities'] is not yet wired into "
            "ResolvedLintConfig.from_dict — D6a U2 ships pyproject "
            "parsing only. Add the precedence branch here before "
            "exposing a CLI severities override.",
        )
    resolved_severities = validated.get("severities", {})
    return cls(severities=resolved_severities, ...)
```

### When the deferred unit ships (remove guard, add precedence)

```python
def from_dict(cls, table, cli_overrides):
    # ... validate table ...
    cli_severities = cli_overrides.get("severities")
    if cli_severities is not None:
        resolved_severities = cli_severities  # CLI wins
    else:
        resolved_severities = validated.get("severities", {})
    return cls(severities=resolved_severities, ...)
```

## Related Learnings

- [[click-parameter-source-detection-cli-config-precedence-2026-05-11]] — the parent learning for `cli_overrides` shape; defines the `None`-sentinel protocol for *known* keys (this learning adds the guard for *unknown* keys)
- [[frozen-dataclass-paired-field-invariant-post-init-2026-05-11]] — complementary defensive layer: `__post_init__` for field-relationship invariants, `from_dict` for integration-boundary key guards
- [[shared-error-helper-source-label-caller-attribution-2026-05-11]] — same `_config.py` module; covers error message attribution when helpers are reachable from multiple sources
- [[normalize-at-input-boundary-2026-05-07]] — meta-principle: apply the same defensive rule at every entry point that touches user input

## Discovered During

D6a U2 ce:review follow-ups (commit `1dea189`). The adversarial
reviewer surfaced the silent-drop trap as finding A3 during the
9-reviewer parallel pass on commit `a039a51` (D6a U2 — pyproject
config substrate for R7/R9a/R9c).
