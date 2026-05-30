---
title: "Neutral field rename behind a read-only deprecation window"
date: 2026-05-30
category: design-patterns
module: protokit.message
problem_type: design_pattern
component: service_object
severity: low
applies_when:
  - "Renaming a paired field on a public frozen dataclass to a more neutral or consistent name"
  - "A pre-1.0 library needs read back-compat without freezing the old constructor kwargs"
  - "A serialized output format (JSON) must carry both old and new keys for one release"
  - "A future hard-removal must be mechanical and grep-able rather than archaeological"
tags:
  - deprecation
  - api-evolution
  - dataclass
  - backward-compatibility
  - naming-convention
  - schema-versioning
  - protokit-message
  - differ
---

# Neutral field rename behind a read-only deprecation window

## Context

protokit's message differ exposes its results as a frozen `Difference` dataclass. Every paired field used neutral `left_*`/`right_*` naming (`left_type`/`right_type`, `left_field_number`/`right_field_number`, `left_label`/`right_label`) — except the value pair, which was named `old_value`/`new_value`. That was semantically wrong: the differ compares two *arbitrary* messages, neither privileged as a "before" or "after" (unlike protokit's separate `compat` pillar, where `old`/`new` is a legitimate **directional** version diff — that split is intentional and stays). The fix renames the pair to `left_value`/`right_value`, but external code reads `old_value`/`new_value` today, so the rename needs a back-compat window. Because protokit is pre-1.0, the window can be **asymmetric**: *reads* of the old names keep working (the public surface external code depends on), while *construction* with the old kwargs hard-breaks (an internal concern).

## Guidance

The reusable recipe for neutrally renaming a public dataclass field pair behind a clean, read-only deprecation window:

1. **Rename the canonical fields** on the frozen dataclass (`old_value`/`new_value` → `left_value`/`right_value`). The dataclass `__init__` now only accepts the new kwarg names — old-kwarg construction raises `TypeError` for free.

2. **Add read-only `@property` aliases** under the old names that warn and proxy to the canonical field. On a `frozen=True` dataclass a `@property` is inherently read-only: assignment raises `AttributeError` with no extra machinery, so reads are preserved while writes break loudly.

3. **Centralize the warning in a helper** with `stacklevel=3` so the warning's blame points at the *caller's* access site, not inside the property:

   ```python
   def _warn_value_alias(deprecated: str, canonical: str) -> None:  # PROTO_1_0_REMOVE
       """stacklevel call chain is caller -> property getter -> here, so
       stacklevel=3 attributes the warning to the consumer's call site."""
       warnings.warn(  # PROTO_1_0_REMOVE (with the old_value/new_value properties)
           f"Difference.{deprecated} is deprecated and will be removed in "
           f"protokit 1.0; use Difference.{canonical} instead.",
           UserWarning,
           stacklevel=3,
       )

   @property
   def old_value(self) -> object | None:  # PROTO_1_0_REMOVE
       """Deprecated read-only alias for :attr:`left_value`."""
       _warn_value_alias("old_value", "left_value")
       return self.left_value
   ```

   Use `UserWarning`, **not** `DeprecationWarning`. `DeprecationWarning` promoted to an exception under a strict-warnings CI poisons broad `except Exception` handlers elsewhere in the stack (see [Related](#related)); `UserWarning` sidesteps that trap while still surfacing under `simplefilter("error")` for consumers who want to fail on it.

4. **Dual-emit on the serialized (JSON) surface** for one release, gated by a `schema_version`. Write both key pairs from one helper, and document that a *missing* `schema_version` means "known pre-this-release format," not "malformed":

   ```python
   #: Bump on any output-shape change (new/removed top-level key, changed key
   #: meaning); the next bump is at protokit 1.0 when old_value/new_value drop.
   #: A missing key means a known-older format, not malformed.
   _DIFF_JSON_SCHEMA_VERSION = "0.1"  # PROTO_1_0_REMOVE: bump when old/new keys drop

   def _set_value_keys(entry: dict[str, Any], left: Any, right: Any) -> None:
       """Canonical keys are left_value/right_value. old_value/new_value are
       deprecated duplicate keys, removed in protokit 1.0. Every entry carries
       all four (None for schema-evolution change types) so the shape is uniform."""
       entry["left_value"] = left
       entry["right_value"] = right
       entry["old_value"] = left   # PROTO_1_0_REMOVE
       entry["new_value"] = right  # PROTO_1_0_REMOVE
   ```

   …and emit `"schema_version": _DIFF_JSON_SCHEMA_VERSION` as a top-level output key. Every entry calls `_set_value_keys` (passing `None, None` for schema-evolution change types) so all four value keys are present with a uniform shape across change types.

5. **Make your own internal readers use the canonical fields**, never the deprecated property. Every formatter (`diff_human`, `diff_json`, `diff_junit`) and the pytest plugin read `d.left_value`/`d.right_value` directly, so internal rendering never trips its own deprecation warning.

6. **Tag every removal site with a grep-able marker.** Both alias properties, the `_warn_value_alias` def and its inner `warnings.warn`, the two dual-emit lines, and the schema-version constant all carry `# PROTO_1_0_REMOVE`, so the 1.0 cleanup is a mechanical `grep -rn PROTO_1_0_REMOVE`.

7. **Pin the deprecation contract with tests** (see [Examples](#examples)): aliases read-and-warn; aliases proxy through `ADDED` (`left=None`) / `REMOVED` (`right=None`); canonical fields are silent under `simplefilter("error")`; aliases are read-only; old-kwarg construction raises `TypeError` (asserted with `match=`); JSON dual-emits both pairs; schema-evolution change types carry all four value keys as `null`; `schema_version` is present; formatters and the pytest plugin don't self-warn.

## Why This Matters

Each choice prevents a specific failure mode:

- **Read-only `@property` aliases (warn, don't raise)** keep the public read surface working with zero *silent* breakage. External code that reads `old_value` keeps getting the right value plus a migration nudge — it doesn't crash, and it doesn't silently read a now-missing attribute. *Prevents: breaking downstream consumers on upgrade.*
- **`stacklevel=3`** makes the warning *actionable* — it points at the consumer's `d.old_value` access, not at an opaque line inside the library's property getter. *Prevents: a warning the user can't locate or fix.*
- **`UserWarning` over `DeprecationWarning`** keeps the deprecation signal from being promoted to an exception that an unrelated broad `except Exception` swallows or misroutes under strict-warnings CI. *Prevents: a deprecation warning that poisons unrelated error handling.*
- **Frozen dataclass + property = read-only for free.** Reads work; writes and old-kwarg construction fail loudly. *Prevents: someone "migrating" by assigning `d.old_value = ...`, and construction code quietly depending on a name slated for removal.*
- **Dual-emit + `schema_version`** lets JSON consumers migrate on *their own clock*: they read either key pair today, switch to `left_value`/`right_value` when ready, and gate on `schema_version` to detect when the old keys vanish at 1.0. The documented "missing means pre-this-release" absence semantic stops consumers from treating older output as malformed. *Prevents: a flag-day break for out-of-band JSON readers.*
- **`PROTO_1_0_REMOVE` markers** turn a future cleanup that's easy to do *incompletely* into a single mechanical grep. *Prevents: a half-finished removal that leaves an orphaned alias or a stale dual-emit key.*
- **Formatters reading canonical fields** avoids the classic trap where your own rendering code spams the very deprecation warning you just shipped — caught explicitly by a test that turns `UserWarning` into an error while running every formatter. *Prevents: self-inflicted warning noise (or, under strict-warnings CI, your own formatters raising).*

## When to Apply

- Renaming a **public field pair** for neutrality/consistency — when the existing names imply a semantic (directionality, ownership, before/after) the type doesn't actually have.
- A **frozen dataclass** where you want read back-compat but are willing to drop construction back-compat (the `@property` gives read-only aliasing with no extra machinery).
- A **serialized surface** (JSON, on-disk, wire) that external consumers parse out-of-band and need a self-paced migration window for — pair the dual-emit with a `schema_version` and a documented absence semantic.
- **Pre-1.0 libraries** that can justify a hard break on construction (an internal concern) while keeping the read surface (the public contract) intact.
- Any deprecation where the eventual removal must be **mechanically complete** — drop a single grep-able marker comment on every site that must die together.

## Examples

**Dataclass: before → after**

```python
# BEFORE
old_value: object | None = None
new_value: object | None = None

# AFTER — canonical fields renamed, old names survive as read-only aliases
left_value: object | None = None
right_value: object | None = None

@property
def old_value(self) -> object | None:   # PROTO_1_0_REMOVE
    _warn_value_alias("old_value", "left_value")
    return self.left_value

@property
def new_value(self) -> object | None:   # PROTO_1_0_REMOVE
    _warn_value_alias("new_value", "right_value")
    return self.right_value
```

Reads still work (with a warning); writes and old-kwarg construction fail. The contract tests pin both ends:

```python
def test_aliases_are_read_only(self) -> None:
    _, d = _modified_diff()
    with pytest.raises(AttributeError):
        d.old_value = "x"   # frozen dataclass + property == read-only

def test_old_kwargs_no_longer_accepted(self) -> None:
    # Construction via the old kwarg names is intentionally a hard break.
    # match= pins the error to the rejected-kwarg TypeError, not some other.
    with pytest.raises(TypeError, match="old_value"):
        Difference(path=FieldPath.parse("x"), change_type=ChangeType.REMOVED, old_value="v")
```

And the test that guarantees internal code never trips its own warning:

```python
def test_builtin_formatters_read_canonical_fields(self) -> None:
    # If any formatter read .old_value/.new_value, UserWarning-as-error surfaces here.
    result, _ = _modified_diff()
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)
        for name in ("human", "json", "junit"):
            fn = get_formatter(name, FormatterKind.DIFF)
            fn(result, FormatterContext(subcommand="diff"))
```

**JSON output: before → after** (a `MODIFIED` diff of `M(a='A')` vs `M(a='B')`)

```jsonc
// BEFORE — entry carries old/new only; no top-level schema_version
{
  "equal": false,
  "differences": [
    { "path": "a", "change_type": "MODIFIED",
      "old_value": "A", "new_value": "B" }
  ],
  "diagnostics": []
}

// AFTER — added top-level schema_version; entry dual-emits both key pairs
{
  "schema_version": "0.1",
  "equal": false,
  "differences": [
    { "path": "a", "change_type": "MODIFIED",
      "left_value": "A", "right_value": "B",
      "old_value": "A",  "new_value": "B" }    // PROTO_1_0_REMOVE
  ],
  "diagnostics": []
}
```

Schema-evolution change types (`TYPE_CHANGED`, `FIELD_NUMBER_CHANGED`, `CARDINALITY_CHANGED`) still carry all four value keys, all `null`, so consumers see a uniform entry shape regardless of change type.

**Source of truth:**
- `src/protokit/message/model.py` — `_warn_value_alias`, the `left_value`/`right_value` fields, and the `old_value`/`new_value` `@property` aliases.
- `src/protokit/formatters/_builtin_diff.py` — `_DIFF_JSON_SCHEMA_VERSION`, `_set_value_keys`, and the `diff_json` dual-emit + `schema_version` output key.
- `tests/test_difference_value_aliases.py` — the full deprecation contract (13 cases).

## Related

- [`best-practices/wire-format-schema-version-bump-contract-and-absence-semantic`](../best-practices/wire-format-schema-version-bump-contract-and-absence-semantic-2026-05-13.md) — the parent `schema_version` + field-absence contract this doc reuses. The differ's `_DIFF_JSON_SCHEMA_VERSION` is the **second** instance of that pattern in the repo (the first governs the lint JSON output). The planned 1.0 removal of `old_value`/`new_value` keys is a future bump under that contract.
- [`best-practices/value-migrated-vs-value-added-consumer-migration`](../best-practices/value-migrated-vs-value-added-consumer-migration-2026-05-17.md) — the consumer-migration framing. A field rename within the same emit site (`old_value` → `left_value`) is the "straight value-addition + value-removal; call it a rename in the CHANGELOG" carve-out, applied at the field-name level.
- [`best-practices/deprecationwarning-poisons-except-exception-strict-warning-ci`](../best-practices/deprecationwarning-poisons-except-exception-strict-warning-ci-2026-05-11.md) — why the aliases emit `UserWarning`, not `DeprecationWarning`.
- [`best-practices/frozen-dataclass-paired-field-invariant-post-init`](../best-practices/frozen-dataclass-paired-field-invariant-post-init-2026-05-11.md) — the frozen-dataclass paired-field family; here the "no field named `old_value`" enforcement comes from the read-only-property mechanism rather than `__post_init__`.
