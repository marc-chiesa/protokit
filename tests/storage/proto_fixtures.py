"""Shared fixtures for ``tests/storage/`` — programmatic descriptor builders and
length-delimited frame helpers.

The descriptor builders mirror the ``_file`` / ``_fds`` helpers in
``tests/test_pools.py`` but live in one importable module (no ``test_`` prefix,
so pytest does not collect it) so the storage suite's many multi-file topo-sort
and isolation fixtures are built the same way without per-file duplication. The
framing helpers (``encode_varint`` / ``delimited``) build the byte streams the
``length_delimited`` source reads.
"""

from __future__ import annotations

from google.protobuf import descriptor_pb2

_TYPE_INT32 = descriptor_pb2.FieldDescriptorProto.TYPE_INT32


def file_proto(
    name: str,
    package: str,
    *,
    deps: tuple[str, ...] = (),
    message: str | None = None,
    ref_type: str | None = None,
    field_name: str = "x",
    field_type: int = _TYPE_INT32,
) -> descriptor_pb2.FileDescriptorProto:
    """Build a minimal proto3 ``FileDescriptorProto``.

    When ``ref_type`` is given, the message gets a field of that message type so
    the declared ``deps`` are load-bearing (the pool genuinely needs the
    dependency present before this file can be added).
    """
    fdp = descriptor_pb2.FileDescriptorProto()
    fdp.name = name
    fdp.package = package
    fdp.syntax = "proto3"
    for dep in deps:
        fdp.dependency.append(dep)
    if message is not None:
        mt = fdp.message_type.add()
        mt.name = message
        f = mt.field.add()
        f.name = field_name
        f.number = 1
        f.label = f.LABEL_OPTIONAL
        if ref_type is not None:
            f.type = f.TYPE_MESSAGE
            f.type_name = ref_type
        else:
            f.type = field_type
    return fdp


def message_file(
    name: str,
    package: str,
    message: str,
    fields: dict[str, tuple[int, int]],
    *,
    syntax: str = "proto3",
) -> descriptor_pb2.FileDescriptorProto:
    """Build a proto3 ``FileDescriptorProto`` with one multi-field message.

    Args:
        name: File name (e.g. ``"a.proto"``).
        package: Package (e.g. ``"a"``).
        message: Message name (e.g. ``"A"``); fully-qualified as
            ``package.message``.
        fields: ``{field_name: (FieldDescriptorProto.TYPE_*, field_number)}``.
    """
    fdp = descriptor_pb2.FileDescriptorProto(name=name, package=package, syntax=syntax)
    mt = fdp.message_type.add()
    mt.name = message
    for field_name, (field_type, field_number) in fields.items():
        f = mt.field.add()
        f.name = field_name
        f.number = field_number
        f.type = field_type
        f.label = f.LABEL_OPTIONAL
    return fdp


def fds(
    *files: descriptor_pb2.FileDescriptorProto,
) -> descriptor_pb2.FileDescriptorSet:
    """Bundle file descriptors into a ``FileDescriptorSet``."""
    out = descriptor_pb2.FileDescriptorSet()
    out.file.extend(files)
    return out


def encode_varint(n: int) -> bytes:
    """Encode ``n`` as a base-128 varint (the length-delimited frame prefix)."""
    out = bytearray()
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def delimited(*payloads: bytes) -> bytes:
    """Build a length-delimited stream (varint length prefix + body, repeated)."""
    return b"".join(encode_varint(len(p)) + p for p in payloads)
