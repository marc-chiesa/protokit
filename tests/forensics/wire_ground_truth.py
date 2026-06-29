"""Synthetic round-trip ground-truth harness for the wire walker (R13).

Encode a message under a known schema, strip the schema, observe the bytes with
the schema-less walker, and assert it recovers the structure the schema implies:
the observed top-level field numbers equal the message's set field numbers, and
every observed wire type is compatible with that field's declared type. No
``test_`` prefix, so pytest does not collect it.
"""

from __future__ import annotations

from google.protobuf import descriptor_pb2
from google.protobuf.message import Message

from protokit.forensics._drift import _wire_type_ok
from protokit.forensics._wire import walk_top_level

_I32 = descriptor_pb2.FieldDescriptorProto.TYPE_INT32


def typed_fdp(
    fields: dict[str, tuple[int, int]],
    *,
    syntax: str = "proto3",
    repeated: frozenset[str] = frozenset(),
) -> descriptor_pb2.FileDescriptorProto:
    """Build an ``a.A`` file descriptor with ``{name: (TYPE_*, number)}`` fields."""
    fdp = descriptor_pb2.FileDescriptorProto(name="a.proto", package="a", syntax=syntax)
    mt = fdp.message_type.add()
    mt.name = "A"
    for name, (field_type, number) in fields.items():
        field = mt.field.add()
        field.name, field.number, field.type = name, number, field_type
        field.label = field.LABEL_REPEATED if name in repeated else field.LABEL_OPTIONAL
    return fdp


def assert_walker_recovers(
    message_class: type[Message], values: dict[str, object]
) -> None:
    """Encode ``values`` under ``message_class`` and assert the walker recovers them."""
    message = message_class()
    for name, value in values.items():
        if isinstance(value, list):
            getattr(message, name).extend(value)
        else:
            setattr(message, name, value)
    data = message.SerializeToString()

    observed = walk_top_level(data)
    observed_numbers = {obs.field_number for obs in observed}
    set_numbers = {field.number for field, _ in message.ListFields()}
    assert observed_numbers == set_numbers

    by_number = {field.number: field for field in message_class.DESCRIPTOR.fields}
    for obs in observed:
        assert _wire_type_ok(by_number[obs.field_number], obs.wire_type)
