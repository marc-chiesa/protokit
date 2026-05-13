---
title: "Use descriptor.CopyToProto(target) to read proto-form-only fields the runtime descriptor doesn't expose"
date: 2026-05-13
category: best-practices
module: protokit.schema
problem_type: best_practice
component: tooling
severity: medium
applies_when:
  - "A descriptor-introspecting helper or lint rule needs a field present on the proto-message form (FileDescriptorProto, DescriptorProto, FieldDescriptorProto, etc.) but absent from the runtime descriptor object (FileDescriptor, Descriptor, FieldDescriptor)"
  - "Specifically: public_dependency / weak_dependency on FileDescriptor; reserved_name / reserved_range on Descriptor; proto3_optional on FieldDescriptor"
  - "Writing or reviewing a buf-parity rule that inspects descriptor surfaces the runtime API truncates"
  - "Choosing between CopyToProto vs. an inferred-from-name discriminator (e.g., leading underscore on synthetic oneof names) for a new descriptor-introspection helper"
tags:
  - protobuf-descriptor
  - copytoproto
  - filedescriptor
  - descriptor-introspection
  - lint-rules
  - schema-checker
  - upb
  - protokit-lint
---

# Use `descriptor.CopyToProto(target)` to read proto-form-only fields the runtime descriptor doesn't expose

## Context

The protobuf-python runtime descriptor objects (`FileDescriptor`,
`Descriptor`, `FieldDescriptor`, `EnumDescriptor`, etc.) do not expose
every field that lives on the proto-message form (`FileDescriptorProto`,
`DescriptorProto`, `FieldDescriptorProto`, `EnumDescriptorProto`, etc.).
The gap is consistent across protobuf-python's two backends — the C
extension and the pure-Python upb runtime — though each backend chooses
slightly different subsets to expose directly. Three concrete cases hit
in this codebase so far:

| Proto-form field | Runtime descriptor exposes it? | First use site |
|---|---|---|
| `FileDescriptorProto.public_dependency` | No on `FileDescriptor` | `imports/no-public` (D6a Unit 5, commit `16a39c3`) |
| `FileDescriptorProto.weak_dependency` | No on `FileDescriptor` | `imports/no-weak` (D6a Unit 5) |
| `DescriptorProto.reserved_range` / `reserved_name` | No on `Descriptor` (upb) | `_reserved_names()` in `schema/rules.py` (Phase 1) |
| `FieldDescriptorProto.proto3_optional` | No on `FieldDescriptor` (upb) | `_proto3_optional_fields()` in `schema/rules.py` (Phase 1) |
| `FileDescriptorProto.syntax` | No on `FileDescriptor` (upb) | (probed in D1; not currently consumed) |

The pattern itself — `descriptor.CopyToProto(target_pb_msg)` to serialize
back into a proto-message buffer that exposes the full API — was first
established in Phase 1 (the schema checker) for the `reserved_name` and
`proto3_optional` cases. The D6a Unit 5 imports rules extend it to
`FileDescriptor.public_dependency` / `weak_dependency`. The D6a plan
ce:review (session history) was the first time the pattern's
generalizability was named as an institutional rule, after F-03 flagged
the runtime-API gap during plan review.

This learning consolidates the pattern as the canonical recipe across
all current and future use sites and documents the decision boundary
between CopyToProto and lighter-weight alternatives (notably the
proto3-optional synthetic-oneof learning, which deliberately
*rejected* CopyToProto in favor of a leading-underscore name
discriminator).

## Guidance

**Use `descriptor.CopyToProto(target_pb_msg)` to access any
proto-form-only field.** Each runtime descriptor type has a
corresponding proto-message type in `descriptor_pb2`:

| Runtime descriptor | CopyToProto target |
|---|---|
| `FileDescriptor` | `descriptor_pb2.FileDescriptorProto()` |
| `Descriptor` (message) | `descriptor_pb2.DescriptorProto()` |
| `FieldDescriptor` | `descriptor_pb2.FieldDescriptorProto()` |
| `EnumDescriptor` | `descriptor_pb2.EnumDescriptorProto()` |
| `EnumValueDescriptor` | `descriptor_pb2.EnumValueDescriptorProto()` |
| `ServiceDescriptor` | `descriptor_pb2.ServiceDescriptorProto()` |
| `MethodDescriptor` | `descriptor_pb2.MethodDescriptorProto()` |
| `OneofDescriptor` | `descriptor_pb2.OneofDescriptorProto()` |

The canonical 2-line idiom:

```python
from google.protobuf import descriptor_pb2

fdp = descriptor_pb2.FileDescriptorProto()
ctx.file.CopyToProto(fdp)
# Read fdp.public_dependency, fdp.weak_dependency, fdp.dependency, ...
```

**Allocate a fresh target per invocation.** Do not share the buffer
across rule invocations — the round-trip is cheap (bounded by the
descriptor's own serialized size), and a shared buffer carries stale
state from the prior caller.

**Cache the result when the round-trip is invoked per child element.**
The `_proto3_optional_fields()` helper in `schema/rules.py` calls
`parent.CopyToProto(dp)` to check `proto3_optional` on each field of
the parent message. Without caching, every field-level rule that
consults `_is_proto3_optional()` would re-serialize the parent — a
quadratic hot path on field-heavy schemas. The fix is a
`contextvars.ContextVar`-keyed cache by `id(descriptor)`, set up
once per `SchemaChecker.check()` invocation and torn down at the
end. Two details matter for correctness: the ContextVar is declared
with `default=None` so callers outside a `check()` scope get a
`None` sentinel (not a `LookupError`), and the cached values are
`frozenset` (immutable) so callers cannot accidentally mutate the
cache. The helper handles the `cache is None` branch by serializing
without storing the result:

```python
_PROTO3_OPTIONAL_CACHE: contextvars.ContextVar[
    dict[int, frozenset[str]] | None
] = contextvars.ContextVar("_proto3_optional_cache", default=None)


def _open_caches() -> contextvars.Token:
    return _PROTO3_OPTIONAL_CACHE.set({})


def _close_caches(token: contextvars.Token) -> None:
    _PROTO3_OPTIONAL_CACHE.reset(token)


def _proto3_optional_fields(desc):
    cache = _PROTO3_OPTIONAL_CACHE.get()
    if cache is not None:
        cached = cache.get(id(desc))
        if cached is not None:
            return cached
    dp = descriptor_pb2.DescriptorProto()
    desc.CopyToProto(dp)
    result = frozenset(
        f.name for f in dp.field if f.proto3_optional
    )
    if cache is not None:
        cache[id(desc)] = result
    return result
```

The caller pairs `_open_caches()` with `_close_caches(token)` in
a `try/finally` at the top of `SchemaChecker.check()` so the cache
is torn down even if traversal raises. Without the pairing, stale
descriptor ids leak across check invocations on long-running
processes.

The D6a U5 imports rules do NOT need caching because each rule calls
`CopyToProto` **once per file** (FILE-element rules fire once per
file), not once per child element. When designing a new rule, the
test for whether caching is needed is "does the per-rule invocation
walk N elements, and would each element re-serialize the same
parent?" If yes, cache. If no, the unadorned round-trip is fine.

**Use the runtime descriptor directly when the field IS exposed.** Do
not reach for CopyToProto when the runtime API has what you need.
Examples of fields available on the runtime descriptor (no round-trip
needed): `file.dependencies` (iterable of imported `FileDescriptor`),
`file.message_types_by_name` / `services_by_name` / `enum_types_by_name`,
`field.message_type` / `field.enum_type`, `method.input_type` /
`method.output_type`, `enum.values`.

**Choose the lighter discriminator when one exists.** The D6a U3
`naming/snake-case-oneofs` rule needed to detect proto3 synthetic
oneofs (created for `optional <type> <name>` fields). The naive path
was `parent.CopyToProto(dp)` → walk `dp.field` → check
`proto3_optional`. The rule instead uses `ctx.oneof.name.startswith("_")`
because protobuf grammar prohibits user-authored underscore-prefixed
oneof names — the underscore is a structurally reliable discriminator
that requires no serialization. See [[proto3-optional-synthetic-oneof-false-positive-lint-rule-2026-05-12]]
for the affirmative case where CopyToProto is NOT the right tool.

## Why This Matters

**Without this pattern, rule authors reach for two strictly worse
alternatives:**

1. **Parsing `descriptor.serialized_pb` directly via
   `ParseFromString`** — works, but re-parses the full serialization
   from scratch each call. CopyToProto uses an optimized native
   serialization path that is faster and more memory-efficient. The
   serialized_pb approach is also harder to audit because the
   parsing step is more opaque than a single `CopyToProto` call.

2. **Reaching into pool internals** (`file._pool`, `file._options`,
   underscore members on the runtime objects) — these differ across
   backends (C extension vs. upb), have broken between major
   protobuf versions, and are not documented as part of the API
   surface. The CopyToProto API is documented, stable, and
   backend-agnostic.

**Backend parity:** the round-trip works identically across protoxy
and protoc backends. Phase 1 of protokit ran both backends during D1
and confirmed CopyToProto produces equivalent `DescriptorProto` /
`FileDescriptorProto` content on both paths. D6a U5 verified the
same for `public_dependency` and `weak_dependency` — the index arrays
are populated regardless of whether `include_source_info` was set at
compile time.

**Performance:** for FILE-element rules invoked once per file, the
per-call serialization cost is negligible. For field-element or
enum-value-element rules invoked many times per file, cache the
result keyed by `id(parent_descriptor)` to avoid quadratic
re-serialization (see the `_proto3_optional_fields()` precedent).

## When to Apply

Use CopyToProto when:

- The needed field is on the proto-message form but not exposed by
  the runtime descriptor — `public_dependency`, `weak_dependency`,
  `reserved_range`, `reserved_name`, `proto3_optional`, raw
  `FieldDescriptorProto.options` for custom-option work (deferred
  to D6b).
- The runtime descriptor's accessor is documented as unstable or
  backend-specific.
- The needed proto-form data spans multiple fields and reading
  them all from one `CopyToProto` call is simpler than mixing
  runtime-API reads with serialized_pb parsing.

Skip CopyToProto when:

- The field IS exposed on the runtime descriptor — use it directly.
  The full list of exposed fields per descriptor type is documented
  in protobuf-python's reference.
- A lighter discriminator exists that doesn't require serialization
  (the proto3-optional synthetic-oneof case is the canonical
  rejection — see [[proto3-optional-synthetic-oneof-false-positive-lint-rule-2026-05-12]]).
- You are inside a tight loop that runs per-field or per-value AND
  you have not yet added a cache — either add the cache first or
  redesign to invoke once per parent.

## Examples

**D1 — synthetic-oneof field detection in the schema checker
(`schema/rules.py:135-169`):**

```python
def _proto3_optional_fields(
    desc: proto_descriptor.Descriptor,
) -> frozenset[str]:
    """Return the set of field names in ``desc`` declared ``proto3 optional``.

    The upb backend doesn't expose ``proto3_optional`` on
    ``FieldDescriptor`` directly, so we reconstruct the flag via
    ``CopyToProto``. Cached on a ContextVar during a check() scope;
    outside that scope the serialization runs on every call (fine
    because those code paths don't iterate).
    """
    cache = _PROTO3_OPTIONAL_CACHE.get()
    if cache is not None:
        key = id(desc)
        cached = cache.get(key)
        if cached is not None:
            return cached
    dp = descriptor_pb2.DescriptorProto()
    desc.CopyToProto(dp)
    result = frozenset(
        f.name for f in dp.field if f.proto3_optional
    )
    if cache is not None:
        cache[id(desc)] = result
    return result
```

**D1 — reserved-name detection in the schema checker
(`schema/rules.py:911-918`):**

```python
def _reserved_names(desc: proto_descriptor.Descriptor) -> set[str]:
    """Names reserved on ``desc`` via the ``reserved`` keyword."""
    dp = descriptor_pb2.DescriptorProto()
    desc.CopyToProto(dp)
    return set(dp.reserved_name)
```

**D6a U5 — `imports/no-public` (`schema/lint/rules/imports.py`):**

```python
def check_no_public_imports(ctx: FileLintContext) -> None:
    fdp = descriptor_pb2.FileDescriptorProto()
    ctx.file.CopyToProto(fdp)
    for idx in fdp.public_dependency:
        ctx.emit(
            violation_kind="imports/no-public",
            params={"imported": fdp.dependency[idx]},
        )
```

**D6a U5 — `imports/unused` reading all three arrays in one round-trip:**

```python
def check_unused_imports(ctx: FileLintContext) -> None:
    fdp = descriptor_pb2.FileDescriptorProto()
    ctx.file.CopyToProto(fdp)
    if not fdp.dependency:
        return
    # ... walk used files ...
    public_idx = set(fdp.public_dependency)
    weak_idx = set(fdp.weak_dependency)
    for idx, imported_name in enumerate(fdp.dependency):
        if idx in public_idx or idx in weak_idx:
            continue
        if imported_name not in used_files:
            ctx.emit(violation_kind="imports/unused",
                     params={"imported": imported_name})
```

(Session history: the D6a plan ce:review at session `030fb66c`
explicitly chose CopyToProto over the alternative SourceCodeInfo path
because SourceCodeInfo is suppressed by both compile backends and
`pool.Add()` destroys it even when enabled at compile time — making
CopyToProto the only viable path for D6a. The R6/R6a/R6b option-aware
rules deferred to D6b will need this same pattern for
`fdp.options` access.)

## Related

- [[proto3-optional-synthetic-oneof-false-positive-lint-rule-2026-05-12]] — the canonical *rejection* of CopyToProto in favor of a lighter discriminator. The two docs together establish the decision boundary: use CopyToProto when there is no alternative; prefer a name-based or structurally-derived discriminator when one exists.
- [[pureposixpath-for-proto-descriptor-file-stem-2026-05-13]] — descriptor-introspection sibling for FILE-element rules; covers the `fd.name` POSIX-separator convention. The two docs together cover the descriptor-introspection landscape for FILE-element work.
- [[matcher-backend-path-resolution-skew-silently-empties-output-2026-05-02]] — established the `fd.name` POSIX-separator convention empirically across protoc and protoxy. The CopyToProto round-trip preserves the `dependency` array values verbatim (POSIX-separator strings the user wrote in their .proto file), so the comparison `used_files.discard(ctx.file.name)` in `imports/unused` is safe.
- [[audit-wire-format-before-claiming-sibling-parity-2026-05-03]] — buf-parity audit discipline. The D6a U5 imports rules' parity claims rest on documentation + behavioral reasoning, not empirical buf-binary cross-checks (parity test infrastructure is planned for D6a Unit 9). The next ce:review pass that touches buf-parity should validate the public/weak skip semantics against buf's actual IMPORT_USED output.
- [[lint-rule-message-templates-must-not-recommend-actions-that-trigger-siblings-2026-05-13]] — sibling D6a U5 learning on the rule-design side, covering message_template audit discipline. Together with this CopyToProto doc, they capture both the data-access pattern and the user-facing contract for the imports pack.
- [[buf-parity-divergence-documentation-discipline-2026-05-13]] — documentation companion. When the CopyToProto workaround produces behavior that diverges from buf's source-aware behavior (e.g., file/syntax-specified firing on explicit proto2 because `fdp.syntax == ""` is ambiguous), the four-site documentation protocol applies. The two docs together cover the full arc: detect the descriptor limitation → implement the CopyToProto workaround → document any resulting divergence.
