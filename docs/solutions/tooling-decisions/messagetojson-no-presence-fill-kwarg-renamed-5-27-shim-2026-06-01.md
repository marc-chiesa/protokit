---
title: "protobuf renamed the MessageToJson fill-defaults kwarg at 5.27: detect-and-prefer the new name"
date: 2026-06-01
category: tooling-decisions
module: protokit.storage
problem_type: tooling_decision
component: tooling
severity: medium
applies_when:
  - Calling MessageToJson or MessageToDict with the fill-unset-fields kwarg
  - Supporting protobuf across the 4.x / 5.x boundary (the kwarg was renamed at 5.27)
  - Emitting dense JSON where no-presence fields must be filled at their default
tags: [protobuf, message-to-json, json-format, version-compat, deprecationwarning, kwarg-shim, cross-version]
---

# protobuf renamed the MessageToJson fill-defaults kwarg at 5.27: detect-and-prefer the new name

## Context

`protokit storage` PR2 fills no-presence fields when rendering proto to JSON
(both the `--fields` faithful view and `--explicit-defaults` dense output rely
on it). The `json_format.MessageToJson` / `MessageToDict` keyword that does this
was **renamed** within protokit's supported `protobuf>=4.21.0,<6` range, so a
single hard-coded kwarg name breaks on part of the range.

## Guidance

The cross-version facts (verified empirically):

- `including_default_value_fields=True` — the **old** name, protobuf 4.21–5.26.
- `always_print_fields_with_no_presence=True` — the **new** name, protobuf 5.27+.
- On 5.27+, passing the **old** name raises `TypeError` (it was removed from the
  signature, not merely deprecated-but-accepted). The **new** name does not exist
  before 5.27. So neither name works across the whole pinned range.

Detect the supported kwarg **once at import** by inspecting the signature, and
**prefer the new name**:

```python
import inspect
from google.protobuf import json_format

_NEW = "always_print_fields_with_no_presence"
_OLD = "including_default_value_fields"

def _detect_no_presence_kwarg() -> str:
    params = inspect.signature(json_format.MessageToDict).parameters
    if _NEW in params:
        return _NEW
    if _OLD in params:
        return _OLD
    raise RuntimeError(  # outside the supported >=4.21,<6 range
        "json_format.MessageToDict exposes neither fill-defaults kwarg"
    )

NO_PRESENCE_FILL_KWARG = _detect_no_presence_kwarg()  # resolved once at import

# callers: MessageToDict(msg, **{NO_PRESENCE_FILL_KWARG: True}, ...)
```

Two non-obvious points:

- **Prefer the new name, don't reach for the deprecated one.** On 5.27+ the old
  name is gone (TypeError), but more generally: using a deprecated identifier
  when a successor exists emits a `DeprecationWarning`, which a strict-warnings CI
  policy promotes to an error. Detect-and-prefer-new is the same
  "use the successor, don't suppress the warning" discipline documented for other
  protobuf-churn cases here.
- **The rename was a clarification, not a behavior change.** Verified on protobuf
  4.25.9 (old kwarg) vs 5.27.5 (new kwarg): both produce identical fill output
  for every presence class — no-presence fields filled at default,
  presence-bearing fields (proto3 `optional`, `oneof`, singular submessage)
  omitted when unset. So the shim is a safe name-swap, not a papered-over
  semantic difference. (A reviewer initially hypothesized the old flag printed
  *all* fields; that did not reproduce.)

## Why This Matters

A naive `MessageToJson(msg, including_default_value_fields=True)` ships green on
the CI cell that resolves the latest in-range protobuf (5.x) and then raises
`TypeError` for any user on 4.21–5.26 — a runtime break invisible to the default
test matrix, which always installs the newest in-range release. The shim makes
the supported range actually supported, and "prefer the new name" keeps the
5.27+ path clean under strict-warnings CI.

Because the floor is the untested edge, add a **lower-bound-protobuf CI cell**
that pins `protobuf==4.25.*` and runs the affected suite, so the old-kwarg path
stays verified rather than assumed. (`protokit`'s existing `has_protoxy:
{true,false}` matrix axis is the precedent for an edge-pinning cell.)

Note on the pin: protokit pins `protobuf>=4.21.0,<6`, and the new name lands at
5.27 — i.e. entirely *inside* the pinned window (5.27 ≤ x < 6). The shim's two
branches both live within the supported range; this does not assume protobuf 6+.

## When to Apply

- Any code calling `MessageToJson`/`MessageToDict` with the fill-unset-fields
  kwarg while supporting protobuf across 4.x and 5.27+.
- More broadly: any time a library renames a keyword argument across a version
  range you support — detect the supported spelling at import and prefer the
  current one, rather than hard-coding one name or catching `TypeError`.

## Examples

The empirical check that settled the semantics (all-unset message with an
implicit scalar, a proto3 `optional`, a oneof, and a submessage):

```text
protobuf 5.27.5, always_print_fields_with_no_presence=True  -> {"implicit_i": 0}
protobuf 4.25.9, including_default_value_fields=True         -> {"implicit_i": 0}
protobuf 5.27.5, including_default_value_fields=True         -> TypeError (removed)
```

Identical output: the implicit (no-presence) scalar fills; the optional, oneof,
and submessage are omitted by presence on both versions.

The CI floor cell:

```yaml
storage-protobuf-floor:
  steps:
    - run: pip install -e ".[dev]"
    - run: |
        pip install "protobuf==4.25.*"   # pin the floor; exercise the OLD kwarg path
        python -c "import google.protobuf as g; assert g.__version__.startswith('4.25.')"
    - run: pytest tests/storage -v
```

## Related

- [[protobuf-upper-bound-pin-fielddescriptor-label-removed-in-7-2026-05-27]] —
  sibling protobuf cross-version-API-churn decision. That one *pins the bound
  out* (removed `FieldDescriptor.label` in 6); this one *shims across* a rename
  within the supported window — the two responses to the same churn problem.
- [[deprecationwarning-poisons-except-exception-strict-warning-ci-2026-05-11]] —
  the governing principle behind "prefer the new kwarg": strict-CI promotes a
  `DeprecationWarning` to an error, so use the successor identifier, don't
  suppress.
- [[proto-json-field-projection-presence-class-fill-then-prune-2026-06-01]] — the
  PR2 sibling whose dense render consumes this shim.
