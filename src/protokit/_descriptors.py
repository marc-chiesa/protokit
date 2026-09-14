"""Shared descriptor traversal helpers.

Small, backend-agnostic utilities for walking protobuf descriptors. These
are intentionally leaf-level primitives — no comparison logic — so both the
differ engine and the schema compatibility checker can import them without
coupling to either. The one piece of state is the bounded, module-level
cache behind :func:`message_proto`, documented at its definition; it holds
immutable serialized file protos and never affects what any helper returns.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

from google.protobuf import descriptor as proto_descriptor
from google.protobuf import descriptor_pb2

from protokit import _fieldview

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


def is_repeated(field_desc: proto_descriptor.FieldDescriptor) -> bool:
    """Return True when ``field_desc.label`` is ``LABEL_REPEATED``.

    Protobuf 5.x removed the convenience ``is_repeated`` attribute
    from the upb ``FieldDescriptor`` binding; the label comparison
    is the only form that works uniformly across protobuf 4 and 5.
    This helper keeps the call sites readable and gives a single
    place to revisit if the API shifts again.
    """
    return field_desc.label == proto_descriptor.FieldDescriptor.LABEL_REPEATED


def is_required(field_desc: proto_descriptor.FieldDescriptor) -> bool:
    """Return True when ``field_desc.label`` is ``LABEL_REQUIRED``.

    Mirror of :func:`is_repeated` for the proto2 ``required`` case.
    Protobuf 5.x dropped ``fd.is_required`` from the upb binding so
    the label comparison is the portable form.
    """
    return field_desc.label == proto_descriptor.FieldDescriptor.LABEL_REQUIRED


def label_name(field_desc: proto_descriptor.FieldDescriptor) -> str:
    """Return the canonical ``LABEL_*`` string for a field's label.

    Maps the integer ``field_desc.label`` to the string form used
    in descriptor diagnostics — ``"LABEL_REPEATED"``,
    ``"LABEL_REQUIRED"``, or ``"LABEL_OPTIONAL"``. Used when a
    ``Difference`` reports a cardinality change so the output
    carries the actual label, not a hard-coded guess.
    """
    FD = proto_descriptor.FieldDescriptor
    if field_desc.label == FD.LABEL_REPEATED:
        return "LABEL_REPEATED"
    if field_desc.label == FD.LABEL_REQUIRED:
        return "LABEL_REQUIRED"
    return "LABEL_OPTIONAL"


def is_map_field(field_desc: proto_descriptor.FieldDescriptor) -> bool:
    """Check if a field is a protobuf map field.

    Delegates to :func:`protokit._fieldview.is_map_field`, which owns the
    map-entry question alongside the enumeration question (U3). Kept here
    as a re-export so existing call sites keep resolving it from this
    module; the two cannot drift apart because there is only one body.

    Args:
        field_desc: A protobuf FieldDescriptor.

    Returns:
        True if the field is a repeated message whose message type has
        the ``map_entry`` option set.
    """
    return _fieldview.is_map_field(field_desc)


# Serialized FileDescriptorProtos, keyed by ``id(FileDescriptor)``.
#
# ``message_proto`` below reads the whole FILE to get one message, because that
# is the only route that works on both backends. Without a cache that turns a
# per-message read into a per-message whole-file serialization: the compat
# checker calls it once per message pair, so a file with N messages costs
# O(N * filesize) where the old per-message ``CopyToProto`` cost O(filesize)
# in total. Measured before caching: a 400-message schema took 10x longer
# through ``SchemaChecker.check()``.
#
# Keyed by ``id()`` because upb's FileDescriptor is NOT weak-referenceable
# (``weakref.WeakKeyDictionary`` raises TypeError on it), so the obvious
# identity-safe container is unavailable. The entry therefore holds a STRONG
# reference to the FileDescriptor alongside its proto: while an entry lives its
# key object cannot be collected, so that id cannot be reused by a different
# object — the failure mode a bare ``id()`` cache would have. A file already in
# a pool is immutable, so a cached proto cannot go stale.
#
# Bounded, because `protokit compat history` / `bisect` build a fresh pool per
# commit; an unbounded cache would pin one pool per commit walked. Bounded is
# not small: the checker traverses by message reference, not grouped by file,
# so a schema with more live files than the cap evicts on every miss. Measured
# at 60 files visited round-robin, a cap of 32 took 3.7 ms against 0.4 ms at
# 256 — 9x slower, and slower than not caching at all. The cap therefore sits
# well above any single descriptor set's file count; what it bounds is the
# number of POOLS a long history walk can keep alive, and 256 files is a
# handful of commits' worth, not one pool per commit.
_FILE_PROTO_CACHE_MAX = 256
_FILE_PROTO_CACHE: OrderedDict[
    int,
    tuple[
        proto_descriptor.FileDescriptor,
        descriptor_pb2.FileDescriptorProto,
        dict[str, descriptor_pb2.DescriptorProto],
    ],
] = OrderedDict()


def _index_messages(
    file_proto: descriptor_pb2.FileDescriptorProto,
) -> dict[str, descriptor_pb2.DescriptorProto]:
    """Map every message in ``file_proto`` to its package-relative dotted name.

    Built once per file so :func:`message_proto` is a dict hit rather than a
    scan. Without it the whole-file read is still O(N) *per lookup* — a linear
    walk over N message_type entries — which leaves the compat checker
    quadratic in message count even with the file proto itself cached.
    """
    index: dict[str, descriptor_pb2.DescriptorProto] = {}

    def _walk(nodes: object, prefix: str) -> None:
        for node in nodes:  # type: ignore[attr-defined]
            name = f"{prefix}.{node.name}" if prefix else node.name
            index[name] = node
            _walk(node.nested_type, name)

    _walk(file_proto.message_type, "")
    return index


def _file_message_index(
    file_descriptor: proto_descriptor.FileDescriptor,
) -> dict[str, descriptor_pb2.DescriptorProto]:
    """``{package-relative dotted name: DescriptorProto}`` for a file, memoized."""
    key = id(file_descriptor)
    hit = _FILE_PROTO_CACHE.get(key)
    if hit is not None and hit[0] is file_descriptor:
        _FILE_PROTO_CACHE.move_to_end(key)
        return hit[2]
    proto = descriptor_pb2.FileDescriptorProto()
    file_descriptor.CopyToProto(proto)
    index = _index_messages(proto)
    _FILE_PROTO_CACHE[key] = (file_descriptor, proto, index)
    _FILE_PROTO_CACHE.move_to_end(key)
    while len(_FILE_PROTO_CACHE) > _FILE_PROTO_CACHE_MAX:
        _FILE_PROTO_CACHE.popitem(last=False)
    return index


def message_proto(
    descriptor: proto_descriptor.Descriptor,
) -> descriptor_pb2.DescriptorProto:
    """Return the ``DescriptorProto`` for ``descriptor``, on either backend.

    The obvious call, ``descriptor.CopyToProto(DescriptorProto())``, is upb-only
    (V34). Measured on protobuf 5.27.5, for a descriptor built by adding a
    ``FileDescriptorProto`` to a pool — which is every descriptor protokit
    handles — the pure-Python runtime raises
    ``descriptor.Error("Descriptor does not contain serialization.")``, because
    it only retains a serialized form for descriptors it generated. upb returns
    the proto. That asymmetry crashed ``protokit compat`` and the drift walker
    outright under the pure-Python backend.

    The owning FILE always retains its serialization on both runtimes, so this
    reads ``descriptor.file`` and locates the message inside it by name,
    walking ``nested_type`` for a nested message. One owner for the three
    readers that need this (KTD1): the two in ``schema.rules`` and the one in
    ``forensics._drift``.

    Args:
        descriptor: A protobuf message ``Descriptor``.

    Returns:
        The ``DescriptorProto`` declaring this message.

    Raises:
        KeyError: If the message cannot be located in its own file's proto,
            which would mean the descriptor and its file disagree.
    """
    package = descriptor.file.package
    relative = descriptor.full_name
    if package and relative.startswith(f"{package}."):
        relative = relative[len(package) + 1 :]

    node = _file_message_index(descriptor.file).get(relative)
    if node is None:
        raise KeyError(
            f"{descriptor.full_name!r} not found in its own file "
            f"{descriptor.file.name!r}"
        )
    return node


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
