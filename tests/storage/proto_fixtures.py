"""Shared descriptor fixtures for ``tests/storage/`` — programmatic
``FileDescriptorProto`` / ``FileDescriptorSet`` builders.

Mirrors the ``_file`` / ``_fds`` helpers in ``tests/test_pools.py`` but lives in
one importable module (no ``test_`` prefix, so pytest does not collect it) so
the storage suite's many multi-file topo-sort and isolation fixtures are built
the same way without per-file duplication.
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


def fds(
    *files: descriptor_pb2.FileDescriptorProto,
) -> descriptor_pb2.FileDescriptorSet:
    """Bundle file descriptors into a ``FileDescriptorSet``."""
    out = descriptor_pb2.FileDescriptorSet()
    out.file.extend(files)
    return out
