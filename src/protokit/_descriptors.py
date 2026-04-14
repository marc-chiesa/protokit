"""Shared descriptor traversal helpers.

Small, backend-agnostic utilities for walking protobuf descriptors. These
are intentionally leaf-level primitives — no comparison logic, no state —
so both the differ engine and the schema compatibility checker can import
them without coupling to either.
"""

from __future__ import annotations

from typing import Any

from google.protobuf import descriptor as proto_descriptor

_FD = proto_descriptor.FieldDescriptor

_TYPE_NAMES: dict[int, str] = {
    _FD.TYPE_DOUBLE: "TYPE_DOUBLE", _FD.TYPE_FLOAT: "TYPE_FLOAT",
    _FD.TYPE_INT64: "TYPE_INT64", _FD.TYPE_UINT64: "TYPE_UINT64",
    _FD.TYPE_INT32: "TYPE_INT32", _FD.TYPE_FIXED64: "TYPE_FIXED64",
    _FD.TYPE_FIXED32: "TYPE_FIXED32", _FD.TYPE_BOOL: "TYPE_BOOL",
    _FD.TYPE_STRING: "TYPE_STRING", _FD.TYPE_MESSAGE: "TYPE_MESSAGE",
    _FD.TYPE_BYTES: "TYPE_BYTES", _FD.TYPE_UINT32: "TYPE_UINT32",
    _FD.TYPE_ENUM: "TYPE_ENUM", _FD.TYPE_SFIXED32: "TYPE_SFIXED32",
    _FD.TYPE_SFIXED64: "TYPE_SFIXED64", _FD.TYPE_SINT32: "TYPE_SINT32",
    _FD.TYPE_SINT64: "TYPE_SINT64", _FD.TYPE_GROUP: "TYPE_GROUP",
}


def type_name(field_type: int) -> str:
    """Return the human-readable name for a protobuf field type constant.

    Args:
        field_type: An integer field type constant from FieldDescriptor.

    Returns:
        A string such as ``"TYPE_STRING"`` or ``"TYPE_UNKNOWN_<n>"`` for
        unrecognised values.
    """
    return _TYPE_NAMES.get(field_type, f"TYPE_UNKNOWN_{field_type}")


def is_map_field(field_desc: proto_descriptor.FieldDescriptor) -> bool:
    """Check if a field is a protobuf map field.

    Args:
        field_desc: A protobuf FieldDescriptor.

    Returns:
        True if the field is a repeated message whose message type has
        the ``map_entry`` option set.
    """
    return (
        field_desc.is_repeated
        and field_desc.type == proto_descriptor.FieldDescriptor.TYPE_MESSAGE
        and field_desc.message_type.GetOptions().map_entry
    )


def get_field_map(
    descriptor: proto_descriptor.Descriptor,
) -> dict[str, proto_descriptor.FieldDescriptor]:
    """Get a name -> field descriptor map, excluding extensions.

    Args:
        descriptor: A protobuf message Descriptor.

    Returns:
        A dict mapping field name to FieldDescriptor for all non-extension
        fields.
    """
    return {f.name: f for f in descriptor.fields if not f.is_extension}


def has_presence(fd: proto_descriptor.FieldDescriptor) -> bool:
    """Check if a field has presence semantics (HasField support).

    Uses the has_presence property available in protobuf v4+ (upb backend).

    Args:
        fd: A protobuf FieldDescriptor.

    Returns:
        True if the field supports ``HasField`` (proto2 fields, proto3
        ``optional`` fields, oneof members, and message fields).
    """
    return fd.has_presence


def format_key(key: Any) -> str:
    """Format a map key value for path bracket display.

    Args:
        key: The key value (bool, int, or str).

    Returns:
        A string suitable for bracket notation in a FieldPath, e.g.
        ``'"foo"'`` for strings, ``"42"`` for ints, ``"true"``/``"false"``
        for bools.
    """
    if isinstance(key, bool):
        return "true" if key else "false"
    if isinstance(key, int):
        return str(key)
    if isinstance(key, str):
        escaped = key.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return str(key)
