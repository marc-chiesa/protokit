"""Built-in compatibility rules.

Each rule is a plain function that accepts the old and new descriptor
objects for its scope (field / enum / message) and a ``FieldPath`` and
returns a list of ``Finding`` objects. Zero findings means the rule
didn't trigger. The checker engine (``schema.checker``) invokes these
in the right scope; rules themselves contain no traversal logic.

The rule set is organized by scope and exposed via three registries:

    FIELD_RULES     # one pair of FieldDescriptors per call
    ENUM_RULES      # one pair of EnumDescriptors per call
    MESSAGE_RULES   # one pair of message Descriptors per call

See ``protokit.schema.model`` for the Finding/Severity/Direction
data types and the project's design doc for the 16-rule table and
wire-compatibility groups.
"""

from __future__ import annotations

import contextvars
from typing import Callable, Iterable

from google.protobuf import descriptor as proto_descriptor
from google.protobuf import descriptor_pb2

from protokit._descriptors import (
    has_presence,
    is_map_field,
    is_repeated,
    is_required,
    type_name,
)
from protokit.message.model import FieldPath
from protokit.schema.model import Direction, Finding, Severity

FD = proto_descriptor.FieldDescriptor


# ---------------------------------------------------------------------------
# Wire-format compatibility groups
# ---------------------------------------------------------------------------

# Wire group -> set of field type constants. Two types are
# wire-compatible if they fall in the same group.
_WIRE_VARINT = frozenset({
    FD.TYPE_INT32, FD.TYPE_INT64,
    FD.TYPE_UINT32, FD.TYPE_UINT64,
    FD.TYPE_BOOL, FD.TYPE_ENUM,
})
_WIRE_ZIGZAG = frozenset({FD.TYPE_SINT32, FD.TYPE_SINT64})
_WIRE_FIXED32 = frozenset({FD.TYPE_FIXED32, FD.TYPE_SFIXED32, FD.TYPE_FLOAT})
_WIRE_FIXED64 = frozenset({FD.TYPE_FIXED64, FD.TYPE_SFIXED64, FD.TYPE_DOUBLE})
# string and bytes share wire-type 2 and a byte-level payload — string
# adds UTF-8 validation on top, which is a semantic (not wire) concern.
_WIRE_LENGTH_BYTES = frozenset({FD.TYPE_STRING, FD.TYPE_BYTES})
# Messages also use wire-type 2 but their payload is a tag-value
# structure, not a byte buffer — a new consumer expecting a message
# will fail to parse arbitrary bytes or UTF-8 text, so the change is
# wire-incompatible even though the envelope is the same.
_WIRE_MESSAGE = frozenset({FD.TYPE_MESSAGE})
_WIRE_GROUP_LEGACY = frozenset({FD.TYPE_GROUP})

_WIRE_GROUPS: tuple[frozenset[int], ...] = (
    _WIRE_VARINT,
    _WIRE_ZIGZAG,
    _WIRE_FIXED32,
    _WIRE_FIXED64,
    _WIRE_LENGTH_BYTES,
    _WIRE_MESSAGE,
    _WIRE_GROUP_LEGACY,
)


def _wire_group(field_type: int) -> int:
    """Return an integer index identifying the wire-format group.

    Returns ``-1`` for unknown types. Used only for equality comparison
    so the specific integer doesn't matter.
    """
    for idx, group in enumerate(_WIRE_GROUPS):
        if field_type in group:
            return idx
    return -1


def _wire_compatible(old_type: int, new_type: int) -> bool:
    """Check whether two field types share the same wire encoding group.

    Two types are wire-compatible iff the bytes on the wire for one type
    can be parsed as the other without truncation or corruption. This is
    strictly stricter than ``_types_compatible()`` in differ.py, which
    treats all integers as one value-comparison group.
    """
    if old_type == new_type:
        return True
    old_group = _wire_group(old_type)
    new_group = _wire_group(new_type)
    return old_group != -1 and old_group == new_group


# ---------------------------------------------------------------------------
# Oneof detection helpers
# ---------------------------------------------------------------------------


#: Per-``check()`` cache of proto3-optional field names, scoped via
#: ``ContextVar`` so the engine's reentrant/concurrent guarantees
#: hold and unit tests that call rules directly don't accidentally
#: share state across invocations.
#:
#: The value (when set) is a dict keyed by ``id(descriptor)``. Valid
#: for the lifetime of the surrounding ``check()`` — descriptors are
#: held alive by the caller's pool, so ids stay stable.
_PROTO3_OPTIONAL_CACHE: contextvars.ContextVar[
    dict[int, frozenset[str]] | None
] = contextvars.ContextVar("_proto3_optional_cache", default=None)


def _open_caches() -> contextvars.Token:
    """Enter a per-check cache scope; returns a token for :func:`_close_caches`.

    Caller must pair this with ``_close_caches(token)`` in a
    ``try/finally`` so the cache is reset even if traversal raises.
    """
    return _PROTO3_OPTIONAL_CACHE.set({})


def _close_caches(token: contextvars.Token) -> None:
    """Exit the per-check cache scope opened by :func:`_open_caches`."""
    _PROTO3_OPTIONAL_CACHE.reset(token)


def _proto3_optional_fields(
    desc: proto_descriptor.Descriptor,
) -> frozenset[str]:
    """Return the set of field names in ``desc`` declared ``proto3 optional``.

    The upb backend doesn't expose ``proto3_optional`` on
    ``FieldDescriptor`` directly, so we reconstruct the flag via
    ``CopyToProto``. When called inside a ``SchemaChecker.check()``
    scope the result is cached on the current ContextVar so repeated
    lookups within a single check don't re-serialize the parent
    message. Outside a check (e.g. when rule tests call rules
    directly), the serialization runs on every call — which is fine
    since those code paths don't iterate.

    Args:
        desc: The message descriptor to inspect.

    Returns:
        A frozenset of field names that were declared ``optional`` in
        proto3 (i.e., that live in a synthetic oneof).
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


def _is_synthetic_oneof(oneof_desc: proto_descriptor.OneofDescriptor) -> bool:
    """Return True if this oneof was synthesized for a proto3 ``optional`` field.

    Fast path: synthetic oneofs always have exactly one field. Slow
    path: reconstruct ``proto3_optional`` via ``CopyToProto`` on the
    parent message (cached by ``_proto3_optional_fields``).
    """
    if len(oneof_desc.fields) != 1:
        return False
    fd = oneof_desc.fields[0]
    parent = fd.containing_type
    if parent is None:
        return False
    return fd.name in _proto3_optional_fields(parent)


def _real_containing_oneof(fd: proto_descriptor.FieldDescriptor) -> str | None:
    """Return the name of the field's real (non-synthetic) containing oneof.

    Returns ``None`` if the field is not in any oneof, or if the oneof is
    a synthetic one created by proto3's ``optional`` keyword.
    """
    oneof = fd.containing_oneof
    if oneof is None:
        return None
    if _is_synthetic_oneof(oneof):
        return None
    return oneof.name


# ---------------------------------------------------------------------------
# Field-level rules
# ---------------------------------------------------------------------------


def field_removed(
    old_fd: proto_descriptor.FieldDescriptor | None,
    new_fd: proto_descriptor.FieldDescriptor | None,
    path: FieldPath,
) -> list[Finding]:
    """Detect a field present in the old schema but absent in the new.

    Severity SEMANTIC, direction BACKWARD: old consumers expecting
    the field will see ``unset``/default in messages produced under
    the new schema.

    Args:
        old_fd: Old-side ``FieldDescriptor`` (the candidate removed
            field), or ``None`` if the field is absent on the old side.
        new_fd: New-side ``FieldDescriptor``, or ``None`` if the field
            is absent on the new side. The rule fires only when this
            is ``None`` and ``old_fd`` is not.
        path: Dotted ``FieldPath`` to the field.

    Returns:
        A single-element list with the finding when the rule fires;
        an empty list otherwise.
    """
    if old_fd is None or new_fd is not None:
        return []
    return [Finding(
        path=path,
        rule_id="field_removed",
        severity=Severity.SEMANTIC,
        direction=Direction.BACKWARD,
        message="field present in old schema, absent in new",
        old_descriptor=old_fd,
    )]


def field_added(
    old_fd: proto_descriptor.FieldDescriptor | None,
    new_fd: proto_descriptor.FieldDescriptor | None,
    path: FieldPath,
) -> list[Finding]:
    """Detect a field present in the new schema but absent in the old.

    Severity SEMANTIC, direction BACKWARD. An old consumer reading
    new data sees a field it doesn't know — protobuf ignores unknown
    fields at the wire level, but code that depends on an exhaustive
    view of the message's fields can still be surprised. Surfaces
    under CONSUMER_SAFE.

    Excludes:

    - proto2 ``required`` adds — handled by ``required_field_added``
      at WIRE severity (more serious) with direction FORWARD.
    - adds into a real (non-synthetic) oneof — handled by
      ``oneof_field_added`` to surface the oneof context.

    Args:
        old_fd: Old-side ``FieldDescriptor``, or ``None`` if absent.
            The rule fires only when this is ``None``.
        new_fd: New-side ``FieldDescriptor``, or ``None`` if absent.
        path: Dotted ``FieldPath`` to the field.

    Returns:
        A single-element list with the finding when the rule fires;
        an empty list otherwise.
    """
    if old_fd is not None or new_fd is None:
        return []
    if is_required(new_fd):
        return []
    if _real_containing_oneof(new_fd) is not None:
        return []
    return [Finding(
        path=path,
        rule_id="field_added",
        severity=Severity.SEMANTIC,
        direction=Direction.BACKWARD,
        message="field present in new schema, absent in old",
        new_descriptor=new_fd,
    )]


def field_number_changed(
    old_fd: proto_descriptor.FieldDescriptor | None,
    new_fd: proto_descriptor.FieldDescriptor | None,
    path: FieldPath,
) -> list[Finding]:
    """Detect a field-number change for the same field name.

    Severity WIRE, direction BOTH. Wire format keys are field
    numbers, so renumbering breaks decoding in both directions.

    Args:
        old_fd: Old-side ``FieldDescriptor`` (must be present).
        new_fd: New-side ``FieldDescriptor`` (must be present).
        path: Dotted ``FieldPath`` to the field.

    Returns:
        A single-element list with the finding when numbers differ;
        an empty list otherwise (or when either side is missing).
    """
    if old_fd is None or new_fd is None:
        return []
    if old_fd.number == new_fd.number:
        return []
    return [Finding(
        path=path,
        rule_id="field_number_changed",
        severity=Severity.WIRE,
        direction=Direction.BOTH,
        message=f"field number changed from {old_fd.number} to {new_fd.number}",
        old_descriptor=old_fd,
        new_descriptor=new_fd,
    )]


def field_type_wire_incompatible(
    old_fd: proto_descriptor.FieldDescriptor | None,
    new_fd: proto_descriptor.FieldDescriptor | None,
    path: FieldPath,
) -> list[Finding]:
    """Detect a scalar type change that crosses wire-encoding groups.

    Severity WIRE, direction BOTH. Only fires when types differ AND
    the new type's wire group differs from the old's (e.g.,
    ``int32`` -> ``sint32`` crosses varint -> zigzag).

    Args:
        old_fd: Old-side ``FieldDescriptor`` (must be present).
        new_fd: New-side ``FieldDescriptor`` (must be present).
        path: Dotted ``FieldPath`` to the field.

    Returns:
        A single-element list when the wire groups differ; otherwise
        an empty list. Same-wire-group changes are reported by
        ``field_type_semantic_change`` instead.
    """
    if old_fd is None or new_fd is None:
        return []
    if old_fd.type == new_fd.type:
        return []
    if _wire_compatible(old_fd.type, new_fd.type):
        return []
    return [Finding(
        path=path,
        rule_id="field_type_wire_incompatible",
        severity=Severity.WIRE,
        direction=Direction.BOTH,
        message=(
            f"field type changed from {type_name(old_fd.type)} to "
            f"{type_name(new_fd.type)} (incompatible wire encoding)"
        ),
        old_descriptor=old_fd,
        new_descriptor=new_fd,
    )]


def field_type_semantic_change(
    old_fd: proto_descriptor.FieldDescriptor | None,
    new_fd: proto_descriptor.FieldDescriptor | None,
    path: FieldPath,
) -> list[Finding]:
    """Detect a type change that keeps wire encoding but shifts semantics.

    Severity SEMANTIC, direction BOTH. Only fires when types differ
    AND the new type shares the old's wire group (e.g., ``string`` ->
    ``bytes``: both length-delimited but UTF-8 validation differs).

    Args:
        old_fd: Old-side ``FieldDescriptor`` (must be present).
        new_fd: New-side ``FieldDescriptor`` (must be present).
        path: Dotted ``FieldPath`` to the field.

    Returns:
        A single-element list when wire groups match but types
        differ; otherwise an empty list. Cross-wire-group changes are
        reported by ``field_type_wire_incompatible`` instead.
    """
    if old_fd is None or new_fd is None:
        return []
    if old_fd.type == new_fd.type:
        return []
    if not _wire_compatible(old_fd.type, new_fd.type):
        return []
    return [Finding(
        path=path,
        rule_id="field_type_semantic_change",
        severity=Severity.SEMANTIC,
        direction=Direction.BOTH,
        message=(
            f"field type changed from {type_name(old_fd.type)} to "
            f"{type_name(new_fd.type)} (same wire encoding, different "
            f"value semantics)"
        ),
        old_descriptor=old_fd,
        new_descriptor=new_fd,
    )]


def _cardinality_label(fd: proto_descriptor.FieldDescriptor) -> str:
    if is_map_field(fd):
        return "map"
    if is_repeated(fd):
        return "repeated"
    return "singular"


def repeated_to_singular(
    old_fd: proto_descriptor.FieldDescriptor | None,
    new_fd: proto_descriptor.FieldDescriptor | None,
    path: FieldPath,
) -> list[Finding]:
    """Detect a cardinality flip between repeated and singular (non-map).

    Severity WIRE, direction BOTH. Skipped when either side is a map
    (covered by ``map_to_repeated`` instead).

    Args:
        old_fd: Old-side ``FieldDescriptor`` (must be present).
        new_fd: New-side ``FieldDescriptor`` (must be present).
        path: Dotted ``FieldPath`` to the field.

    Returns:
        A single-element list when cardinality flipped; an empty list
        when unchanged or when a map is involved.
    """
    if old_fd is None or new_fd is None:
        return []
    if is_map_field(old_fd) or is_map_field(new_fd):
        return []
    if is_repeated(old_fd) == is_repeated(new_fd):
        return []
    return [Finding(
        path=path,
        rule_id="repeated_to_singular",
        severity=Severity.WIRE,
        direction=Direction.BOTH,
        message=(
            f"cardinality changed: {_cardinality_label(old_fd)} -> "
            f"{_cardinality_label(new_fd)}"
        ),
        old_descriptor=old_fd,
        new_descriptor=new_fd,
    )]


def map_to_repeated(
    old_fd: proto_descriptor.FieldDescriptor | None,
    new_fd: proto_descriptor.FieldDescriptor | None,
    path: FieldPath,
) -> list[Finding]:
    """Detect a map field changing into a repeated field (or vice versa).

    Severity WIRE, direction BOTH. Maps and repeated fields share the
    LABEL_REPEATED label but the synthetic ``map_entry`` message
    makes wire decoding differ.

    Args:
        old_fd: Old-side ``FieldDescriptor`` (must be present).
        new_fd: New-side ``FieldDescriptor`` (must be present).
        path: Dotted ``FieldPath`` to the field.

    Returns:
        A single-element list when map-ness flipped; an empty list
        when unchanged.
    """
    if old_fd is None or new_fd is None:
        return []
    if is_map_field(old_fd) == is_map_field(new_fd):
        return []
    return [Finding(
        path=path,
        rule_id="map_to_repeated",
        severity=Severity.WIRE,
        direction=Direction.BOTH,
        message=(
            f"cardinality changed: {_cardinality_label(old_fd)} -> "
            f"{_cardinality_label(new_fd)}"
        ),
        old_descriptor=old_fd,
        new_descriptor=new_fd,
    )]


def oneof_membership_changed(
    old_fd: proto_descriptor.FieldDescriptor | None,
    new_fd: proto_descriptor.FieldDescriptor | None,
    path: FieldPath,
) -> list[Finding]:
    """Detect a field moving in/out of a real oneof or between two oneofs.

    Severity SEMANTIC, direction BOTH. Synthetic oneofs (created by
    proto3 ``optional``) are treated as "no oneof" and do not trigger
    this rule — see ``presence_changed`` for that case.

    Args:
        old_fd: Old-side ``FieldDescriptor`` (must be present).
        new_fd: New-side ``FieldDescriptor`` (must be present).
        path: Dotted ``FieldPath`` to the field.

    Returns:
        A single-element list when the real-oneof membership differs;
        an empty list otherwise.
    """
    if old_fd is None or new_fd is None:
        return []
    old_oneof = _real_containing_oneof(old_fd)
    new_oneof = _real_containing_oneof(new_fd)
    if old_oneof == new_oneof:
        return []
    return [Finding(
        path=path,
        rule_id="oneof_membership_changed",
        severity=Severity.SEMANTIC,
        direction=Direction.BOTH,
        message=(
            f"oneof membership changed: "
            f"{old_oneof or '<none>'} -> {new_oneof or '<none>'}"
        ),
        old_descriptor=old_fd,
        new_descriptor=new_fd,
    )]


def oneof_field_added(
    old_fd: proto_descriptor.FieldDescriptor | None,
    new_fd: proto_descriptor.FieldDescriptor | None,
    path: FieldPath,
) -> list[Finding]:
    """Detect a new field added as an alternative inside a real oneof.

    Severity SEMANTIC, direction BACKWARD. Old consumers doing
    exhaustive switches on the oneof variants will not recognize the
    new alternative in new data. Surfaces under CONSUMER_SAFE.

    Args:
        old_fd: Old-side ``FieldDescriptor``, or ``None`` if absent.
            The rule fires only when this is ``None``.
        new_fd: New-side ``FieldDescriptor``, or ``None`` if absent.
            Must be in a real (non-synthetic) oneof for the rule to
            fire.
        path: Dotted ``FieldPath`` to the field.

    Returns:
        A single-element list when ``new_fd`` is in a real oneof and
        ``old_fd`` is absent; an empty list otherwise.
    """
    if old_fd is not None or new_fd is None:
        return []
    oneof_name = _real_containing_oneof(new_fd)
    if oneof_name is None:
        return []
    return [Finding(
        path=path,
        rule_id="oneof_field_added",
        severity=Severity.SEMANTIC,
        direction=Direction.BACKWARD,
        message=f"new alternative added to oneof '{oneof_name}'",
        new_descriptor=new_fd,
    )]


def required_field_added(
    old_fd: proto_descriptor.FieldDescriptor | None,
    new_fd: proto_descriptor.FieldDescriptor | None,
    path: FieldPath,
) -> list[Finding]:
    """Detect a proto2 ``required`` field added in the new schema.

    Severity WIRE, direction FORWARD. Old producers still emit
    messages without the new required field; a new consumer that
    parses that old data fails to deserialize. That's a
    "new-consumer reading old-data" break — i.e., backward
    compatibility is broken — so the finding surfaces under the
    PRODUCER_SAFE profile (which protects against old producers).

    Args:
        old_fd: Old-side ``FieldDescriptor``, or ``None`` if absent.
            The rule fires only when this is ``None``.
        new_fd: New-side ``FieldDescriptor``, or ``None`` if absent.
            Must have ``label == LABEL_REQUIRED`` for the rule to
            fire.
        path: Dotted ``FieldPath`` to the field.

    Returns:
        A single-element list when a required field is newly added;
        an empty list otherwise.
    """
    if old_fd is not None or new_fd is None:
        return []
    if not is_required(new_fd):
        return []
    return [Finding(
        path=path,
        rule_id="required_field_added",
        severity=Severity.WIRE,
        direction=Direction.FORWARD,
        message="new proto2 `required` field; old producers cannot satisfy it",
        new_descriptor=new_fd,
    )]


def options_changed(
    old_fd: proto_descriptor.FieldDescriptor | None,
    new_fd: proto_descriptor.FieldDescriptor | None,
    path: FieldPath,
) -> list[Finding]:
    """Detect any change to a field's serialized options.

    Severity POLICY, direction BOTH. Backend-agnostic:
    ``GetOptions().SerializeToString()`` is compared byte-for-byte. A
    plugin rule can provide finer-grained interpretation; this
    built-in only flags that *something* changed.

    Args:
        old_fd: Old-side ``FieldDescriptor`` (must be present).
        new_fd: New-side ``FieldDescriptor`` (must be present).
        path: Dotted ``FieldPath`` to the field.

    Returns:
        A single-element list when the serialized options differ; an
        empty list otherwise.
    """
    if old_fd is None or new_fd is None:
        return []
    old_bytes = old_fd.GetOptions().SerializeToString()
    new_bytes = new_fd.GetOptions().SerializeToString()
    if old_bytes == new_bytes:
        return []
    return [Finding(
        path=path,
        rule_id="options_changed",
        severity=Severity.POLICY,
        direction=Direction.BOTH,
        message="field options changed (serialized bytes differ)",
        old_descriptor=old_fd,
        new_descriptor=new_fd,
    )]


def field_type_name_changed(
    old_fd: proto_descriptor.FieldDescriptor | None,
    new_fd: proto_descriptor.FieldDescriptor | None,
    path: FieldPath,
) -> list[Finding]:
    """Detect a field whose message/enum type pointer now names a different type.

    Severity POLICY, direction BOTH. Fires only when both sides are
    ``TYPE_MESSAGE`` or both sides are ``TYPE_ENUM`` and the
    referenced type's fully-qualified name differs. Shape-level
    differences between the two types are reported separately by
    recursion (for messages) or ``enum_value_*`` rules (for enums);
    this rule captures the source-level identity rotation itself.

    Does not fire when the field type changes *category* (e.g.
    message → string) — that's handled by
    ``field_type_wire_incompatible`` / ``field_type_semantic_change``.

    Rationale: wire format is unaffected if the replacement type has
    the same shape, but generated client code depends on the concrete
    type name (``isinstance``, imports, ``switch`` exhaustiveness).
    Users that don't care about type identity can stay below STRICT.

    Args:
        old_fd: Old-side ``FieldDescriptor`` (must be present).
        new_fd: New-side ``FieldDescriptor`` (must be present).
        path: Dotted ``FieldPath`` to the field.

    Returns:
        A single-element list when the type name differs; an empty
        list when identity is unchanged or the field type isn't
        MESSAGE/ENUM on both sides.
    """
    if old_fd is None or new_fd is None:
        return []
    if old_fd.type != new_fd.type:
        return []

    # Map fields point at a synthetic ``XxxEntry`` message whose
    # full_name is tied to the containing message's name — renaming
    # ``UserV1`` → ``UserV2`` rotates every ``UserV1.ItemsEntry`` →
    # ``UserV2.ItemsEntry`` synthetically, not because the user
    # changed the map's value type. We skip the map field itself
    # here; the checker dispatches field rules on the map's
    # ``value`` sub-field so any real value-type rotation fires
    # against the user-authored type directly.
    if is_map_field(old_fd) or is_map_field(new_fd):
        return []

    if old_fd.type == FD.TYPE_MESSAGE:
        old_name = old_fd.message_type.full_name
        new_name = new_fd.message_type.full_name
    elif old_fd.type == FD.TYPE_ENUM:
        old_name = old_fd.enum_type.full_name
        new_name = new_fd.enum_type.full_name
    else:
        return []
    if old_name == new_name:
        return []
    kind = "message" if old_fd.type == FD.TYPE_MESSAGE else "enum"
    return [Finding(
        path=path,
        rule_id="field_type_name_changed",
        severity=Severity.POLICY,
        direction=Direction.BOTH,
        message=(
            f"{kind} type changed: '{old_name}' -> '{new_name}' "
            f"(shape-level differences are reported separately)"
        ),
        old_descriptor=old_fd,
        new_descriptor=new_fd,
    )]


def presence_changed(
    old_fd: proto_descriptor.FieldDescriptor | None,
    new_fd: proto_descriptor.FieldDescriptor | None,
    path: FieldPath,
) -> list[Finding]:
    """Detect a change in field presence semantics.

    Severity SEMANTIC, direction BOTH. Compares
    ``FieldDescriptor.has_presence`` across the two sides. Examples:
    proto3 implicit (no presence) -> proto3 ``optional`` (has
    presence), or proto2 ``optional`` -> proto3 implicit. Only fires
    when both sides exist — added/removed fields are covered by
    ``field_added`` / ``field_removed``.

    Args:
        old_fd: Old-side ``FieldDescriptor`` (must be present).
        new_fd: New-side ``FieldDescriptor`` (must be present).
        path: Dotted ``FieldPath`` to the field.

    Returns:
        A single-element list when presence semantics differ; an
        empty list otherwise.
    """
    if old_fd is None or new_fd is None:
        return []
    old_has = has_presence(old_fd)
    new_has = has_presence(new_fd)
    if old_has == new_has:
        return []
    return [Finding(
        path=path,
        rule_id="presence_changed",
        severity=Severity.SEMANTIC,
        direction=Direction.BOTH,
        message=f"field presence changed: has_presence {old_has} -> {new_has}",
        old_descriptor=old_fd,
        new_descriptor=new_fd,
    )]


# ---------------------------------------------------------------------------
# Enum-level rules
# ---------------------------------------------------------------------------


def enum_value_removed(
    old_enum: proto_descriptor.EnumDescriptor | None,
    new_enum: proto_descriptor.EnumDescriptor | None,
    path: FieldPath,
) -> list[Finding]:
    """Detect enum values present in the old schema but absent in the new.

    Severity SEMANTIC, direction FORWARD. Old producers can still
    emit the removed value on the wire; a new consumer parsing that
    old data will see an enum number with no matching name. Surfaces
    under PRODUCER_SAFE. Matched by name.

    Args:
        old_enum: Old-side ``EnumDescriptor`` (must be present).
        new_enum: New-side ``EnumDescriptor`` (must be present).
        path: Dotted ``FieldPath`` to the field that uses this enum.
            Each finding inherits this path.

    Returns:
        One finding per removed value (by name). Empty list when the
        enum membership is unchanged or when either side is missing.
    """
    if old_enum is None or new_enum is None:
        return []
    new_names = {v.name for v in new_enum.values}
    return [
        Finding(
            path=path,
            rule_id="enum_value_removed",
            severity=Severity.SEMANTIC,
            direction=Direction.FORWARD,
            message=f"enum value '{v.name}' (number {v.number}) removed",
            old_descriptor=v,
        )
        for v in old_enum.values
        if v.name not in new_names
    ]


def enum_value_added(
    old_enum: proto_descriptor.EnumDescriptor | None,
    new_enum: proto_descriptor.EnumDescriptor | None,
    path: FieldPath,
) -> list[Finding]:
    """Detect enum values added in the new schema, absent from the old.

    Severity SEMANTIC, direction BACKWARD. New producers can emit
    the added value; an old consumer parsing new data will see an
    enum number it doesn't know, breaking exhaustive switches.
    Surfaces under CONSUMER_SAFE. Matched by name.

    Args:
        old_enum: Old-side ``EnumDescriptor`` (must be present).
        new_enum: New-side ``EnumDescriptor`` (must be present).
        path: Dotted ``FieldPath`` to the field that uses this enum.

    Returns:
        One finding per added value (by name). Empty list when the
        enum membership is unchanged or when either side is missing.
    """
    if old_enum is None or new_enum is None:
        return []
    old_names = {v.name for v in old_enum.values}
    return [
        Finding(
            path=path,
            rule_id="enum_value_added",
            severity=Severity.SEMANTIC,
            direction=Direction.BACKWARD,
            message=f"enum value '{v.name}' (number {v.number}) added",
            new_descriptor=v,
        )
        for v in new_enum.values
        if v.name not in old_names
    ]


def enum_number_reused(
    old_enum: proto_descriptor.EnumDescriptor | None,
    new_enum: proto_descriptor.EnumDescriptor | None,
    path: FieldPath,
) -> list[Finding]:
    """Detect enum numbers that now carry a different name than before.

    Severity WIRE, direction BOTH. Protobuf permits aliasing
    (``allow_alias``), so a number may have multiple names on either
    side. The rule fires when the new schema introduces a name at a
    number that existed under different names in the old schema —
    name additions that don't reuse an existing number are reported
    by ``enum_value_added`` instead.

    Args:
        old_enum: Old-side ``EnumDescriptor`` (must be present).
        new_enum: New-side ``EnumDescriptor`` (must be present).
        path: Dotted ``FieldPath`` to the field that uses this enum.

    Returns:
        One finding per reused number, listing the old and new sets
        of names. Empty list when no reuse occurred.
    """
    if old_enum is None or new_enum is None:
        return []
    old_names_by_number: dict[int, set[str]] = {}
    for v in old_enum.values:
        old_names_by_number.setdefault(v.number, set()).add(v.name)
    new_names_by_number: dict[int, set[str]] = {}
    for v in new_enum.values:
        new_names_by_number.setdefault(v.number, set()).add(v.name)

    findings: list[Finding] = []
    for number in sorted(old_names_by_number.keys() & new_names_by_number.keys()):
        added_names = new_names_by_number[number] - old_names_by_number[number]
        if not added_names:
            continue
        old_list = sorted(old_names_by_number[number])
        new_list = sorted(new_names_by_number[number])
        findings.append(Finding(
            path=path,
            rule_id="enum_number_reused",
            severity=Severity.WIRE,
            direction=Direction.BOTH,
            message=(
                f"enum number {number} now refers to different names: "
                f"old={old_list} new={new_list}"
            ),
            old_descriptor=old_enum,
            new_descriptor=new_enum,
        ))
    return findings


# ---------------------------------------------------------------------------
# Message-level rules
# ---------------------------------------------------------------------------


def _reserved(
    desc: proto_descriptor.Descriptor,
) -> tuple[tuple[tuple[int, int], ...], set[str]]:
    """The message's reserved field-number ranges and reserved names.

    Ranges are returned as half-open ``(start, end)`` pairs and are
    **deliberately not materialized** into a set of integers: a valid
    ``reserved N to max;`` emits ``end = 536_870_912``, so
    ``set(range(...))`` would allocate ~5e8 ints (~32 GB measured by
    extrapolation) and OOM the process. Membership is the only use --
    see :func:`_is_reserved`. The sibling walker in
    ``protokit.forensics._drift`` keeps the same shape for the same
    reason.

    Both halves come back together because reading either one requires
    a ``CopyToProto`` roundtrip on the upb backend (the live
    ``Descriptor`` doesn't expose reserved data), and that roundtrip is
    the expensive part -- doing it once per message pair instead of
    twice halves the serialization cost of this rule.
    """
    dp = descriptor_pb2.DescriptorProto()
    desc.CopyToProto(dp)
    ranges = tuple((rng.start, rng.end) for rng in dp.reserved_range)
    return ranges, set(dp.reserved_name)


def _is_reserved(number: int, ranges: tuple[tuple[int, int], ...]) -> bool:
    """Whether ``number`` falls in any half-open reserved range."""
    return any(start <= number < end for start, end in ranges)


def reserved_field_reused(
    old_desc: proto_descriptor.Descriptor | None,
    new_desc: proto_descriptor.Descriptor | None,
    path: FieldPath,
) -> list[Finding]:
    """Detect reuse of a number or name that was reserved in the old schema.

    Direction BOTH. Severity is split by reuse kind:

    - Reusing a reserved **number** emits a WIRE finding (wire-format
      tags key off the number; a consumer still holding old bytes for
      that number would misparse them).
    - Reusing a reserved **name** emits a SEMANTIC finding. Names are
      not on the wire; reuse is a source-level/API concern but does
      not corrupt decoding.

    Reading ``reserved_range`` and ``reserved_name`` requires a
    ``CopyToProto`` roundtrip on the upb backend (the live
    ``Descriptor`` doesn't expose them). Each violating new field
    produces its own finding under ``path.child(field_name)``.

    Args:
        old_desc: Old-side message ``Descriptor`` (must be present).
        new_desc: New-side message ``Descriptor`` (must be present).
        path: Dotted ``FieldPath`` to the message itself; per-field
            findings extend this path with the offending field's name.

    Returns:
        One finding per reused number or name. A field that reuses
        both a reserved number and a reserved name produces two
        findings.
    """
    if old_desc is None or new_desc is None:
        return []
    old_res_ranges, old_res_names = _reserved(old_desc)
    findings: list[Finding] = []
    for fd in new_desc.fields:
        if fd.is_extension:
            continue
        if _is_reserved(fd.number, old_res_ranges):
            findings.append(Finding(
                path=path.child(fd.name),
                rule_id="reserved_field_reused",
                severity=Severity.WIRE,
                direction=Direction.BOTH,
                message=(
                    f"field number {fd.number} was reserved in the old "
                    f"schema; '{fd.name}' reuses it"
                ),
                new_descriptor=fd,
            ))
        if fd.name in old_res_names:
            findings.append(Finding(
                path=path.child(fd.name),
                rule_id="reserved_field_reused",
                severity=Severity.SEMANTIC,
                direction=Direction.BOTH,
                message=(
                    f"field name '{fd.name}' was reserved in the old "
                    f"schema; it is reused in the new schema"
                ),
                new_descriptor=fd,
            ))
    return findings


# ---------------------------------------------------------------------------
# Rule registries
# ---------------------------------------------------------------------------

FieldRuleFn = Callable[
    [
        proto_descriptor.FieldDescriptor | None,
        proto_descriptor.FieldDescriptor | None,
        FieldPath,
    ],
    Iterable[Finding],
]

EnumRuleFn = Callable[
    [
        proto_descriptor.EnumDescriptor | None,
        proto_descriptor.EnumDescriptor | None,
        FieldPath,
    ],
    Iterable[Finding],
]

MessageRuleFn = Callable[
    [
        proto_descriptor.Descriptor | None,
        proto_descriptor.Descriptor | None,
        FieldPath,
    ],
    Iterable[Finding],
]


FIELD_RULES: tuple[tuple[str, FieldRuleFn], ...] = (
    ("field_removed", field_removed),
    ("field_added", field_added),
    ("field_number_changed", field_number_changed),
    ("field_type_wire_incompatible", field_type_wire_incompatible),
    ("field_type_semantic_change", field_type_semantic_change),
    ("field_type_name_changed", field_type_name_changed),
    ("repeated_to_singular", repeated_to_singular),
    ("map_to_repeated", map_to_repeated),
    ("oneof_membership_changed", oneof_membership_changed),
    ("oneof_field_added", oneof_field_added),
    ("required_field_added", required_field_added),
    ("options_changed", options_changed),
    ("presence_changed", presence_changed),
)

ENUM_RULES: tuple[tuple[str, EnumRuleFn], ...] = (
    ("enum_value_removed", enum_value_removed),
    ("enum_value_added", enum_value_added),
    ("enum_number_reused", enum_number_reused),
)

MESSAGE_RULES: tuple[tuple[str, MessageRuleFn], ...] = (
    ("reserved_field_reused", reserved_field_reused),
)
