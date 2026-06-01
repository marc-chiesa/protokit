---
title: "Faithful proto-to-JSON field projection: fill-dense-then-prune, split by presence class"
date: 2026-06-01
category: design-patterns
module: protokit.storage
problem_type: design_pattern
component: tooling
severity: medium
applies_when:
  - Projecting or field-selecting a protobuf message to JSON (a "jq for proto" surface)
  - Rendering proto3 messages where a default-valued field the user asked for must stay visible
  - Building partial-view or field-mask output over protobuf and reusing proto's JSON type-mapping
tags: [protobuf, proto3, presence, message-to-json, field-projection, default-values, json-rendering]
---

# Faithful proto-to-JSON field projection: fill-dense-then-prune, split by presence class

## Context

`protokit storage` added `--fields a,b.c` — a "jq for proto" that emits just the
named fields of stored records. The obvious implementation (mask the message
down to the selected fields, then render it to JSON) carries a silent footgun:
a **proto3 implicit-presence scalar at its default** (`int32 error_code` with no
`optional`, value `0`) cannot represent "excluded" vs "present and zero" *in the
message object* — both are just `0` — and the standard JSON renderer omits the
zero. So `--fields error_code` against a record where `error_code == 0` returns
`{}`. A user who isn't fluent in proto3 wire/JSON semantics reads that as "the
field is missing" or "my data is wrong." The information that the user *asked
for* the field lives in the **selection set**, which is external to the message —
so any faithful answer must be driven by the selection set, not recovered from a
round-tripped masked message.

## Guidance

Render the **full** message to a dense dict, then **prune the dict** to the
selected paths — do not mask the message first.

1. `json_format.MessageToDict(message, <no-presence-fill kwarg>=True,
   preserving_proto_field_name=True)` → a dense dict (snake_case keys; every
   no-presence field filled at its default; presence-bearing fields present only
   if actually set).
2. Walk the selection set; for each dotted path, descend the dict by segment and
   graft the terminal value into the result. If any segment is missing (a
   presence-bearing ancestor was unset, so the fill flag omitted it), the path
   contributes nothing.

The dense render **already encodes the presence-class rule**, so faithfulness
falls out for free and reuses all of proto's leaf type-mapping (enums→names,
int64→string, bytes→base64, well-known types):

- **No-presence fields** (implicit scalars, repeated, map, enums) are always
  present, at their default when defaulted — the footgun fix.
- **Presence-bearing fields** (proto3 `optional`, `oneof` members, singular
  submessages) are rendered by *actual presence* — emitted when set, omitted when
  not, **never fabricated** to a default. Forcing them to a default would
  re-create the footgun in reverse: asserting a field was set when it wasn't.

This holds **recursively** — a nested no-presence scalar fills while a nested
presence-bearing field stays absent, inside submessage / map-value /
repeated-element / `oneof` submessage terminals.

Two guards the mechanism needs:

- **Drive faithfulness from the selection set, never from the message
  representation.** Pruning a dict whose values are already materialized is
  lossless; masking the message is not (a no-presence scalar can't be made
  "absent").
- **`isinstance(dict)` guard on each descent.** A path may name a non-terminal
  whose `message_type` is a well-known type that `MessageToDict` renders as a
  *non-dict* (e.g. `Timestamp`→string, `Value`→scalar). Without the guard,
  descending (`src = src[seg]`) then `seg not in src` raises `TypeError` (a
  spurious error) or silently returns `{}`. Guard each step:
  `if not isinstance(src, dict) or seg not in src: return`.

## Why This Matters

The proto3 *message object* is the wrong place to carry "the user selected this
field." For implicit-presence scalars, "cleared" and "set to default" are
indistinguishable in the object, so any mask-then-render approach loses the
distinction at the point it masks. Sourcing the answer from the selection set
(which knows what was asked) and using the dense render only to supply
**values** keeps the faithful view honest *and* avoids reinventing proto's JSON
type-mapping. The same dense render also doubles as the engine for a dense
full-record mode (e.g. `--explicit-defaults`) — one mechanism, two consumers.

## When to Apply

- A field-selection / projection / partial-view feature over protobuf that must
  show a named field even at its proto3 default.
- Any "render a subset of a proto message as JSON" surface where dropping a
  zero/empty/false would mislead the reader.
- When you want proto-correct leaf encoding without hand-rolling enum/int64/
  bytes/WKT mapping.

## Examples

Naive mask-then-render (the footgun), record with `header.error_code == 0`:

```python
# WRONG: masked message rendered with default MessageToJson -> the zero vanishes
json_format.MessageToJson(masked_message, indent=None)   # -> "{}"
```

Fill-dense-then-prune (faithful):

```python
dense = json_format.MessageToDict(
    message,
    preserving_proto_field_name=True,
    **{no_presence_kwarg(): True},   # the cross-version fill kwarg — see related doc
)
# prune `dense` to the selected dotted paths, grafting terminals into a result dict
# --fields header.error_code,source  ->  {"header": {"error_code": 0}, "source": "edge-1"}
```

Presence-bearing fields are by-presence, never fabricated:

```python
# record with opt_scalar (proto3 optional) UNSET, choice oneof UNSET, header UNSET
# --fields opt_scalar,choice.a,header.error_code  ->  {}   (none fabricated)
# but a *set* optional at its default value (opt_scalar = 0, explicitly set) -> shown
```

Well-known-type descent is guarded (no crash):

```python
# --fields ts.seconds  where ts is a google.protobuf.Timestamp (renders as a string)
# the isinstance(dict) guard makes the path resolve to absent rather than raising
```

## Related

- [[runtime-checkable-protocol-isinstance-is-presence-only-not-correctness-2026-05-30]]
  — companion presence-vs-shape discipline: both put the real correctness check on
  a concrete `isinstance` guard (tuple there, dict here) rather than trusting a
  higher-level abstraction.
- [[messagetojson-no-presence-fill-kwarg-renamed-5-27-shim-2026-06-01]] — the
  `no_presence_kwarg()` shim this pattern's dense render depends on (PR2 sibling).
- [[proto3-optional-synthetic-oneof-false-positive-lint-rule-2026-05-12]] — the
  lint-side cousin: proto3 `optional`'s synthetic oneof surprising a naive walker,
  here on the render side instead of the lint side.
