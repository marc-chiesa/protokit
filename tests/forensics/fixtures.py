"""Shared builders for ``tests/forensics/`` — message classes, candidates, files.

No ``test_`` prefix, so pytest does not collect it. Builds candidate schemas as
in-memory ``FileDescriptorSet``s (each resolves to its own isolated pool, no
compiler backend needed) and serializes messages under a chosen schema so the
match-fit cases (clean / unmodeled / superset / missing-required) are exact.
"""

from __future__ import annotations

from pathlib import Path

from google.protobuf import descriptor_pb2
from google.protobuf.message import Message

from protokit.forensics import Candidate
from protokit.storage.schema_source import FileDescriptorSetSchema
from tests.storage.proto_fixtures import fds, message_file

TYPE = "a.A"
_I32 = descriptor_pb2.FieldDescriptorProto.TYPE_INT32


def fdp(
    fields: dict[str, int], *, syntax: str = "proto3"
) -> descriptor_pb2.FileDescriptorProto:
    """Build an ``a.A`` file descriptor with ``{name: number}`` int32 fields."""
    return message_file(
        "a.proto", "a", "A", {n: (_I32, num) for n, num in fields.items()}, syntax=syntax
    )


def proto2_required_fdp(
    required: dict[str, int], optional: dict[str, int]
) -> descriptor_pb2.FileDescriptorProto:
    """Build a proto2 ``a.A`` with the given required and optional int32 fields."""
    f = descriptor_pb2.FileDescriptorProto(name="a.proto", package="a", syntax="proto2")
    mt = f.message_type.add()
    mt.name = "A"
    for name, number in required.items():
        fl = mt.field.add()
        fl.name, fl.number, fl.type, fl.label = name, number, _I32, fl.LABEL_REQUIRED
    for name, number in optional.items():
        fl = mt.field.add()
        fl.name, fl.number, fl.type, fl.label = name, number, _I32, fl.LABEL_OPTIONAL
    return f


def cls_for(file_proto: descriptor_pb2.FileDescriptorProto) -> type[Message]:
    """Resolve ``a.A``'s message class from one file descriptor (isolated pool)."""
    return FileDescriptorSetSchema(fds(file_proto), TYPE).resolve().message_class


def candidate(
    label: str, file_proto: descriptor_pb2.FileDescriptorProto
) -> Candidate:
    """A :class:`Candidate` over an in-memory ``FileDescriptorSet`` schema."""
    return Candidate(label, FileDescriptorSetSchema(fds(file_proto), TYPE))


def msg_bytes(
    file_proto: descriptor_pb2.FileDescriptorProto, values: dict[str, int]
) -> bytes:
    """Serialize an ``a.A`` message built under ``file_proto`` with ``values`` set."""
    message = cls_for(file_proto)()
    for key, value in values.items():
        setattr(message, key, value)
    return message.SerializeToString()


def write_desc(path: Path, file_proto: descriptor_pb2.FileDescriptorProto) -> None:
    """Write ``file_proto`` as a ``.desc`` ``FileDescriptorSet`` file."""
    path.write_bytes(fds(file_proto).SerializeToString())


def write_message(
    path: Path, file_proto: descriptor_pb2.FileDescriptorProto, values: dict[str, int]
) -> None:
    """Write a serialized ``a.A`` message (built under ``file_proto``) to ``path``."""
    path.write_bytes(msg_bytes(file_proto, values))
