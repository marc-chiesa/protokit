---
title: "Frozen dataclass paired-field invariants belong in __post_init__, not in the constructing function"
date: 2026-05-11
category: docs/solutions/best-practices
module: python/frozen-dataclasses
problem_type: best_practice
component: tooling
severity: medium
applies_when:
  - "A frozen dataclass exposes a payload field (e.g., `value: tuple[str, ...]`) alongside a paired provenance/source discriminator field (e.g., `value_source: Literal['cli', 'pyproject', 'both', 'default']`)"
  - "The discriminator has a 'no source / default' state that is only logically valid when the payload is empty/absent"
  - "Downstream code branches on the discriminator to produce human-visible output (error messages, log lines, telemetry) and would silently misbehave if the pair drifts apart"
  - "The dataclass can be constructed programmatically OR mutated via `dataclasses.replace`, not just through a single canonical resolver / classmethod"
  - "ce:review correctness, testing, maintainability, or adversarial reviewers flag an `else` arm in an emit-site helper whose only purpose is to handle the 'no source' discriminator value"
related_components:
  - tooling
tags:
  - dataclass
  - frozen-dataclass
  - post-init
  - source-attribution
  - invariant
  - dataclasses-replace
  - unreachable-branch
  - paired-fields
---

# Frozen dataclass paired-field invariants belong in `__post_init__`, not in the constructing function

## Context

When a frozen dataclass exposes a *source-attributed* value — a payload field plus a paired discriminator field that records *which input source* produced it (CLI vs config-file vs default) — the discriminator's "no source" default state is only valid when the payload is empty. If a programmatic caller forgets to set the discriminator, or uses `dataclasses.replace(obj, payload=new)` without also updating the discriminator, the object enters a self-contradictory state: a non-empty payload paired with a "default / nothing-was-configured" source. Downstream emission code that branches on the discriminator then silently produces an unattributed (or misattributed) message, even though everything else still works.

Enforcing this invariant in the constructing function (a `from_dict` classmethod, a resolver, a builder) is insufficient: `dataclasses.replace(...)` bypasses the constructor, and so does every direct `Class(payload=...)` call. The invariant must live on the type itself.

This pattern appeared in protokit D5 U4 (`src/protokit/schema/lint/_config.py`). `ResolvedLintConfig` carries:

- `exclude: tuple[str, ...] = ()` (the payload)
- `exclude_source: ExcludeSource = "default"` (the provenance, where `ExcludeSource = Literal["cli", "pyproject", "both", "default"]`)
- `all_files_excluded_message(...)` which emits an R20-attributed warning whose template branches on `exclude_source`

`"default"` is correct only when `exclude` is empty. But:

- `cli.py` used `dataclasses.replace(resolved, exclude=new_patterns)` in four places — any one of those that forgot to update `exclude_source` would silently regress the source attribution.
- Internal callers or tests could write `ResolvedLintConfig(exclude=("vendor/**",))` without specifying `exclude_source`, get back an object that passed mypy, and only discover the regression by exact-string-comparing the rendered warning template.

The **diagnostic signal** was an unreachable `else` arm in `all_files_excluded_message` whose sole purpose was to handle `exclude_source == "default"` — a state the upstream emit site (`if resolved.exclude:`) supposedly guaranteed couldn't reach. Six independent reviewers flagged this same shape during D5 U4 ce:review (3-way finding-level convergence — correctness `COR-U4-02`, testing `T-U4-02`, maintainability `TG-U4-02` — expanded to 6-way with adversarial `ADV-P3-D`, api-contract `ACR-U4-TG-02`, kieran `TG-KP-U4-01`).

Per the D5 plan archaeology (session history), the `exclude_source` field itself was **not** in the original D5 specification — the plan named only `min_severity_source` as the source-attribution exemplar. `exclude_source` was added during implementation as a parallel to `min_severity_source`, and the carrier-shape invariant that should have come with it was missed at design time. The 6-way reviewer convergence is what surfaced the gap. (session history)

## Guidance

When a frozen dataclass carries a `(payload, payload_source)` pair where the discriminator has a "no source" default state, do two things together:

1. **Add a `__post_init__` invariant** that rejects the contradictory `(non-empty payload, "default" source)` state at construction time.
2. **At every emit site**, replace if/elif/else dispatch with a dict-constant lookup whose keys deliberately omit the "no source" value — the invariant guarantees that key can never reach the lookup, so a `KeyError` becomes a loud assertion that the invariant held.

Together, these convert a silent runtime degradation (an unattributed message) into a loud `ValueError` (at construction) plus a defensive `KeyError` (at emit) if the invariant is ever circumvented.

**Before — silent attribution failure was reachable:**

```python
@dataclass(frozen=True)
class ResolvedLintConfig:
    exclude: tuple[str, ...] = ()
    exclude_source: ExcludeSource = "default"

    def __post_init__(self) -> None:
        object.__setattr__(self, "exclude", tuple(self.exclude))

    def all_files_excluded_message(self, file_count: int) -> str:
        if self.exclude_source == "cli":
            desc = "--exclude"
        elif self.exclude_source == "pyproject":
            desc = "[tool.protokit.lint] exclude"
        elif self.exclude_source == "both":
            desc = "--exclude and [tool.protokit.lint] exclude"
        else:
            # "default" — "should never happen" but isn't enforced
            desc = "exclude"   # silent unattributed fallback
        return f"all {file_count} input file(s) excluded by {desc} patterns: ..."
```

**After — invariant + table-driven emit:**

```python
ExcludeSource = Literal["cli", "pyproject", "both", "default"]

# Source-attribution descriptors. ``"default"`` is intentionally
# absent: the ``__post_init__`` invariant on ``ResolvedLintConfig``
# rejects ``exclude_source == "default"`` when ``exclude`` is
# non-empty, so the lookup is exhaustive at the emit site.
_EXCLUDE_SOURCE_DESC: dict[ExcludeSource, str] = {
    "cli": "--exclude",
    "pyproject": "[tool.protokit.lint] exclude",
    "both": "--exclude and [tool.protokit.lint] exclude",
}

@dataclass(frozen=True)
class ResolvedLintConfig:
    exclude: tuple[str, ...] = ()
    exclude_source: ExcludeSource = "default"

    def __post_init__(self) -> None:
        # Tuple-snapshot first (sibling discipline — see Related).
        object.__setattr__(self, "exclude", tuple(self.exclude))
        # Paired-field invariant: "default" source is only valid for
        # the empty-payload case. Catches programmatic construction
        # AND ``dataclasses.replace(resolved, exclude=new)`` callers
        # that forget to update the discriminator.
        if self.exclude and self.exclude_source == "default":
            raise ValueError(
                "ResolvedLintConfig.exclude_source must be set to "
                "'cli', 'pyproject', or 'both' when exclude is "
                "non-empty (got 'default').",
            )

    def all_files_excluded_message(self, file_count: int) -> str:
        source_desc = _EXCLUDE_SOURCE_DESC[self.exclude_source]
        return (
            f"all {file_count} input file(s) excluded by "
            f"{source_desc} patterns: ..."
        )
```

Three properties of the fix are intentional:

1. **The invariant fires at construction time**, so misuse surfaces at the offending `replace()` or constructor site rather than at the emit site (which may be far from the cause).
2. **The lookup table deliberately omits the "no source" key.** A future code path that smuggles the forbidden value through despite the invariant gets a `KeyError` at emit time — loud and traceable — rather than a silent fallback string. The omission is documented in a comment alongside the constant.
3. **Existing tests that constructed the dataclass directly with a non-empty payload must now pass the discriminator explicitly.** This is a feature, not friction: a test that was passing without setting the discriminator was itself encoding the bug.

## Why This Matters

- **Silent degradation has no test signal.** A misattributed warning still mentions exclusion, still names the right file count, still passes any "does the warning fire?" assertion. Only an exact-string-comparison test against the full template would catch it — and those tests are easy to skip when adding a new construction site.
- **`dataclasses.replace` is the failure-prone path.** It does not run constructor-side validation. Every `replace(obj, payload=new)` site is a future bug waiting to be written. Moving the check onto the type closes that surface.
- **Frozen dataclasses encourage programmatic construction.** Unlike a builder, a frozen dataclass invites callers to construct one inline. The default for `payload_source` cannot be simultaneously "safe for empty payload" and "safe for non-empty payload"; a runtime invariant resolves the conflict cleanly.
- **The emission code becomes simpler.** Dropping the `else` branch tightens the dispatch type and shrinks the surface that has to be exhaustive-matched in tests.
- **Construction-time invariants compose with the cross-format-enum-string-parity discipline.** That learning establishes "pin source-attributed message templates at the carrier object boundary so every consumer emits identical text." This learning extends the principle: the carrier should *also* reject construction states that would make the template's branches non-exhaustive. Together they form a complete pattern — (a) templates live on the carrier, (b) the carrier rejects construction states that would make the templates' branches non-exhaustive.

## When to Apply

Apply this pattern whenever a frozen dataclass has the `(payload, payload_source)` shape **AND**:

- The discriminator has a "no source / default" state that is only logically valid when the payload is empty.
- The dataclass is frozen and/or used with `dataclasses.replace` — `replace()` does not run any "did you update both fields?" check.
- Downstream code branches on the discriminator for human-visible output (messages, logs, telemetry, exit-code attribution).

**Do not apply when:**

- The discriminator field has no default — the constructor signature already enforces correctness.
- The discriminator is purely informational and never branched on at emit time — no degradation risk.
- The dataclass is constructed exclusively through a single classmethod / resolver that has its own validation — but verify this is actually true by grepping for direct constructor calls and `dataclasses.replace` sites.

## Examples

### Composing with existing protokit learnings

This learning sits at the intersection of three prior protokit best-practice docs:

- **[`frozen-dataclass-mutable-fields-need-post-init-snapshot-2026-05-02.md`](frozen-dataclass-mutable-fields-need-post-init-snapshot-2026-05-02.md)** — sibling `__post_init__` discipline. That learning addresses *structural* integrity (snapshotting mutable container inputs to prevent aliasing). This learning addresses *semantic* integrity (paired-field consistency between a payload and its discriminator). Both belong in `__post_init__`. In `ResolvedLintConfig.__post_init__`, the tuple-snapshot lines run first, followed by the paired-field invariant — both disciplines stack cleanly on the same hook.
- **[`source-aware-error-messages-multi-source-resolved-value-2026-05-11.md`](source-aware-error-messages-multi-source-resolved-value-2026-05-11.md)** — the message-emission half of the pattern. That learning says "error messages must name the actual runtime source of a multi-source resolved value." This learning is the **upstream guard**: the carrier the message helper reads from never reaches the emit site in an unattributed state. The two compose into a complete pipeline.
- **[`cross-format-enum-string-parity-2026-05-08.md`](cross-format-enum-string-parity-2026-05-08.md)** — pins message templates at the carrier boundary so sibling formatters emit identical text. This learning extends that discipline by enforcing that the templates' branches stay exhaustive at the emit site via construction-time rejection of the contradictory state.

### Real protokit U4 fix shape

```python
# _config.py (D5 U4)

ExcludeSource = Literal["cli", "pyproject", "both", "default"]

_EXCLUDE_SOURCE_DESC: dict[ExcludeSource, str] = {
    "cli": "--exclude",
    "pyproject": "[tool.protokit.lint] exclude",
    "both": "--exclude and [tool.protokit.lint] exclude",
    # "default" intentionally absent — see __post_init__ invariant
}

@dataclass(frozen=True)
class ResolvedLintConfig:
    profile: tuple[str, ...] = ("default",)
    exclude: tuple[str, ...] = ()
    min_severity: LintSeverity | None = None
    # ...
    exclude_source: ExcludeSource = "default"
    min_severity_source: ConfigSource = "default"
    pyproject_min_severity: LintSeverity | None = None

    def __post_init__(self) -> None:
        # Sibling discipline: tuple-snapshot mutable container inputs.
        object.__setattr__(self, "profile", tuple(self.profile))
        object.__setattr__(self, "exclude", tuple(self.exclude))
        # Paired-field invariant for (exclude, exclude_source).
        if self.exclude and self.exclude_source == "default":
            raise ValueError(
                "ResolvedLintConfig.exclude_source must be set to "
                "'cli', 'pyproject', or 'both' when exclude is "
                "non-empty (got 'default').",
            )
```

### Test discipline that catches the pre-existing-bug-as-test case

When adding the invariant, expect to break existing tests that constructed the dataclass with a non-empty payload but the default discriminator. Update those tests to pass the discriminator explicitly — and add a dedicated test that the invariant fires:

```python
def test_non_empty_exclude_with_default_source_rejected(self) -> None:
    with pytest.raises(ValueError, match="exclude_source must be set"):
        ResolvedLintConfig(exclude=("vendor/**",))

def test_dataclasses_replace_drops_attribution_caught(self) -> None:
    r = ResolvedLintConfig()
    with pytest.raises(ValueError, match="exclude_source must be set"):
        dataclasses.replace(r, exclude=("vendor/**",))
```

The second test is the load-bearing one — it pins the failure mode adversarial review flagged as the live composition surface (D5 U4 finding `ADV-P3-D`).

### Why not use a `from_dict`-side check instead?

A `from_dict` classmethod (or any resolver-side validation) misses two paths the `__post_init__` invariant catches:

1. **`dataclasses.replace(obj, payload=new)`** — bypasses the classmethod entirely.
2. **Direct constructor calls** — `ResolvedLintConfig(payload=..., other_field=...)` doesn't route through `from_dict`.

`__post_init__` is invoked on every `__init__`, including the synthetic `__init__` `@dataclass` generates and including the path `dataclasses.replace` uses. It is the only hook that protects all construction paths uniformly.

## Related

- [`frozen-dataclass-mutable-fields-need-post-init-snapshot-2026-05-02.md`](frozen-dataclass-mutable-fields-need-post-init-snapshot-2026-05-02.md) — sibling `__post_init__` discipline for *structural* integrity. Combine in the same `__post_init__`: snapshot first, then invariant-check.
- [`source-aware-error-messages-multi-source-resolved-value-2026-05-11.md`](source-aware-error-messages-multi-source-resolved-value-2026-05-11.md) — message-emission half of the pattern. This learning is its upstream guard.
- [`cross-format-enum-string-parity-2026-05-08.md`](cross-format-enum-string-parity-2026-05-08.md) — carrier-boundary message templates. This learning enforces that the templates' branches stay exhaustive.
- [`cli-overrides-deferred-key-notimplemented-trip-wire-2026-05-12.md`](cli-overrides-deferred-key-notimplemented-trip-wire-2026-05-12.md) — complementary defensive layer at a different construction-path stage. `__post_init__` (this learning) is the right place for *field-relationship invariants* (e.g., "exclude_source must be set when exclude is non-empty"); `from_dict` (that learning) is the right place for *integration-boundary key guards* (e.g., "no deferred-feature keys may arrive yet"). Together they cover all construction-path defensive layers without overlapping.
- D5 U4 ce:review run id `20260511-224330-79e6510b`. Convergence: `COR-U4-02` + `T-U4-02` + `TG-U4-02` + `ACR-U4-TG-02` + `TG-KP-U4-01` + `ADV-P3-D` (6-way).
