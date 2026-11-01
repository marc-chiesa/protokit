"""Shared descriptor traversal helpers.

Small, backend-agnostic utilities for walking protobuf descriptors. These
are intentionally leaf-level primitives — no comparison logic — so both the
differ engine and the schema compatibility checker can import them without
coupling to either. The one piece of state is the bounded, module-level
cache behind :func:`message_proto`, documented at its definition; it holds
immutable serialized file protos and never affects what any helper returns.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, cast

from google.protobuf import descriptor as proto_descriptor
from google.protobuf import descriptor_pb2, descriptor_pool

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
    return cast(bool, field_desc.label == proto_descriptor.FieldDescriptor.LABEL_REPEATED)


def is_required(field_desc: proto_descriptor.FieldDescriptor) -> bool:
    """Return True when ``field_desc.label`` is ``LABEL_REQUIRED``.

    Mirror of :func:`is_repeated` for the proto2 ``required`` case.
    Protobuf 5.x dropped ``fd.is_required`` from the upb binding so
    the label comparison is the portable form.
    """
    return cast(bool, field_desc.label == proto_descriptor.FieldDescriptor.LABEL_REQUIRED)


def label_name(field_desc: proto_descriptor.FieldDescriptor) -> str:
    """Return the canonical ``LABEL_*`` string for a field's label.

    Maps the integer ``field_desc.label`` to the string form used
    in descriptor diagnostics — ``"LABEL_REPEATED"``,
    ``"LABEL_REQUIRED"``, or ``"LABEL_OPTIONAL"``. Used when a
    ``Difference`` reports a cardinality change so the output
    carries the actual label, not a hard-coded guess.
    """
    fd_class = proto_descriptor.FieldDescriptor
    if field_desc.label == fd_class.LABEL_REPEATED:
        return "LABEL_REPEATED"
    if field_desc.label == fd_class.LABEL_REQUIRED:
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
# Bounded by POOLS, not files. A FileDescriptor pins its pool, so what a
# `protokit compat history` / `bisect` walk (one fresh pool per commit) keeps
# alive is the number of distinct pools the cache references. A file cap
# cannot express that: 32 files thrashed on any schema larger than 32 files
# (measured 9x slower than uncached), and 256 files let a walk over ten-file
# schemas pin 26 old pools (3x the memory of the cap it replaced). So the
# live pool is always fully cached whatever its size — no thrash — and only
# the newest ``_FILE_PROTO_CACHE_MAX_POOLS`` pools (four schema pairs) stay alive; a whole pool's
# entries go when it ages out. The file backstop guards the cache's own size
# against one pathological pool and is never the operative bound in practice.
#
# One lock: entries are evicted while another caller may be between its
# ``get`` and ``move_to_end`` (two ``SchemaChecker`` runs on different threads
# raised ``KeyError`` there under contention).
_FILE_PROTO_CACHE_MAX_POOLS = 8
_FILE_PROTO_CACHE_MAX_FILES = 2048
_FILE_PROTO_CACHE: OrderedDict[
    int,
    tuple[
        proto_descriptor.FileDescriptor,
        descriptor_pb2.FileDescriptorProto,
        dict[str, descriptor_pb2.DescriptorProto],
        int,  # id() of the owning pool: the key into _FILE_PROTO_POOLS
    ],
] = OrderedDict()
# Pools with cached files, least recently used first: ``{id(pool): (pool, {file keys})}``.
_FILE_PROTO_POOLS: OrderedDict[
    int, tuple[descriptor_pool.DescriptorPool, set[int]],
] = OrderedDict()
_FILE_PROTO_LOCK = threading.Lock()


def _clear_file_proto_cache() -> None:
    """Drop every cached file and pool (tests; nothing in the product needs it)."""
    with _FILE_PROTO_LOCK:
        _FILE_PROTO_CACHE.clear()
        _FILE_PROTO_POOLS.clear()


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
    with _FILE_PROTO_LOCK:
        hit = _FILE_PROTO_CACHE.get(key)
        if hit is not None and hit[0] is file_descriptor:
            _FILE_PROTO_CACHE.move_to_end(key)
            _FILE_PROTO_POOLS.move_to_end(hit[3])
            return hit[2]
        proto = descriptor_pb2.FileDescriptorProto()
        file_descriptor.CopyToProto(proto)
        index = _index_messages(proto)
        pool = file_descriptor.pool
        pool_key = id(pool)
        pool_entry = _FILE_PROTO_POOLS.get(pool_key)
        if pool_entry is None or pool_entry[0] is not pool:
            pool_entry = (pool, set())
            _FILE_PROTO_POOLS[pool_key] = pool_entry
        _FILE_PROTO_POOLS.move_to_end(pool_key)
        pool_entry[1].add(key)
        _FILE_PROTO_CACHE[key] = (file_descriptor, proto, index, pool_key)
        _FILE_PROTO_CACHE.move_to_end(key)
        while len(_FILE_PROTO_POOLS) > _FILE_PROTO_CACHE_MAX_POOLS:
            _, (_, evicted_keys) = _FILE_PROTO_POOLS.popitem(last=False)
            for evicted in evicted_keys:
                _FILE_PROTO_CACHE.pop(evicted, None)
        while len(_FILE_PROTO_CACHE) > _FILE_PROTO_CACHE_MAX_FILES:
            evicted, (_, _, _, evicted_pool) = _FILE_PROTO_CACHE.popitem(last=False)
            owner = _FILE_PROTO_POOLS.get(evicted_pool)
            if owner is not None:
                owner[1].discard(evicted)
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
    return cast(bool, fd.has_presence)


def format_key(key: Any) -> str:
    r"""Format a key value as path bracket text the ``FieldPath`` grammar reads back.

    Each value has one spelling, so a path the differ writes parses back to
    itself and ``--filter`` can target it. Map keys are integers, booleans
    and strings; a ``treat_as_map`` key can also be a float, bytes or an enum
    number.

    Args:
        key: The key value.

    Returns:
        ``true`` / ``false`` for a bool; the decimal digits for an int (an
        enum number included); ``repr`` for a float (``1.5``, ``1e+300``,
        ``nan``, ``inf``, ``-inf``); a double-quoted string, with ``\\``,
        ``\"``, ``\n``, ``\r``, ``\t`` and ``\xHH`` / ``\uHHHH`` /
        ``\UHHHHHHHH`` for every other character ``str.isprintable`` rejects,
        so the key stays on one line and carries no terminal escape; and
        ``b"…"`` for bytes, with printable ASCII as it is and ``\\``,
        ``\"`` or ``\xHH`` for the rest. Any other value is quoted as its
        ``str``.
    """
    if isinstance(key, bool):
        return "true" if key else "false"
    if isinstance(key, int):
        return str(int(key))
    if isinstance(key, float):
        return repr(float(key))
    if isinstance(key, (bytes, bytearray)):
        return "b" + _quote_bytes(bytes(key))
    return _quote_text(key if isinstance(key, str) else str(key))


_TEXT_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _quote_text(text: str) -> str:
    """``text`` double-quoted with the path grammar's string escapes."""
    if text.isprintable() and '"' not in text and "\\" not in text:
        return f'"{text}"'
    parts: list[str] = []
    for char in text:
        escaped = _TEXT_ESCAPES.get(char)
        if escaped is not None:
            parts.append(escaped)
        elif char.isprintable():
            parts.append(char)
        elif (code := ord(char)) <= 0xFF:
            parts.append(f"\\x{code:02x}")
        elif code <= 0xFFFF:
            parts.append(f"\\u{code:04x}")
        else:
            parts.append(f"\\U{code:08x}")
    return '"' + "".join(parts) + '"'


def _quote_bytes(data: bytes) -> str:
    r"""``data`` double-quoted: printable ASCII as it is, ``\\``, ``\"`` and ``\xHH``."""
    parts: list[str] = []
    for byte in data:
        if byte == 0x5C:
            parts.append("\\\\")
        elif byte == 0x22:
            parts.append('\\"')
        elif 0x20 <= byte <= 0x7E:
            parts.append(chr(byte))
        else:
            parts.append(f"\\x{byte:02x}")
    return '"' + "".join(parts) + '"'
