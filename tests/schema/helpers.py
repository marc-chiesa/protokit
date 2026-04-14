"""Descriptor-construction helpers for schema checker tests.

Extends ProtoBuilder for features not covered by the shared helper:
proto2 ``required`` fields, proto3 ``optional`` (synthetic oneofs),
message-level ``reserved`` ranges and names, custom field options,
and ``allow_alias`` enums.
"""

from __future__ import annotations

from typing import Iterable

from google.protobuf import descriptor_pb2, descriptor_pool

T = descriptor_pb2.FieldDescriptorProto
M = descriptor_pb2.DescriptorProto


def build_message(
    pool: descriptor_pool.DescriptorPool,
    full_name: str,
    *,
    fields: Iterable[dict] = (),
    enums: Iterable[dict] = (),
    oneofs: Iterable[str] = (),
    reserved_ranges: Iterable[tuple[int, int]] = (),
    reserved_names: Iterable[str] = (),
    syntax: str = "proto3",
    file_name: str | None = None,
) -> None:
    """Build a message into ``pool``.

    Each ``fields`` entry is a dict with keys: name (required), number
    (required), type (required: ``TYPE_*`` constant), type_name (for
    MESSAGE/ENUM), label (default OPTIONAL), oneof_index, proto3_optional,
    json_name.

    Each ``enums`` entry is a dict with keys: name, values (dict name->number),
    allow_alias (bool).

    ``oneofs`` is a list of oneof names in order. Fields reference oneofs
    by index via the ``oneof_index`` key.

    Synthetic oneofs (proto3 optional) must appear last in the oneof list,
    per protobuf's internal ordering requirement.
    """
    parts = full_name.rsplit(".", 1)
    package = parts[0] if len(parts) > 1 else ""
    msg_name = parts[-1]

    fp = descriptor_pb2.FileDescriptorProto(
        name=file_name or f"{msg_name.lower()}_{id(pool):x}.proto",
        package=package,
        syntax=syntax,
    )
    mp = fp.message_type.add()
    mp.name = msg_name

    for oneof_name in oneofs:
        op = mp.oneof_decl.add()
        op.name = oneof_name

    for rng in reserved_ranges:
        rr = mp.reserved_range.add()
        rr.start = rng[0]
        rr.end = rng[1]
    for name in reserved_names:
        mp.reserved_name.append(name)

    for enum_spec in enums:
        ep = mp.enum_type.add()
        ep.name = enum_spec["name"]
        if enum_spec.get("allow_alias"):
            ep.options.allow_alias = True
        for val_name, val_number in enum_spec["values"].items():
            vp = ep.value.add()
            vp.name = val_name
            vp.number = val_number

    for spec in fields:
        f = mp.field.add()
        f.name = spec["name"]
        f.number = spec["number"]
        f.type = spec["type"]
        if "type_name" in spec:
            f.type_name = spec["type_name"]
        f.label = spec.get("label", T.LABEL_OPTIONAL)
        if "oneof_index" in spec:
            f.oneof_index = spec["oneof_index"]
        if spec.get("proto3_optional"):
            f.proto3_optional = True
        if "json_name" in spec:
            f.json_name = spec["json_name"]

    pool.Add(fp)


def build_enum(
    pool: descriptor_pool.DescriptorPool,
    full_name: str,
    values: dict[str, int],
    *,
    allow_alias: bool = False,
    syntax: str = "proto3",
    file_name: str | None = None,
) -> None:
    """Build a package-level enum into ``pool``."""
    parts = full_name.rsplit(".", 1)
    package = parts[0] if len(parts) > 1 else ""
    enum_name = parts[-1]

    fp = descriptor_pb2.FileDescriptorProto(
        name=file_name or f"enum_{enum_name.lower()}_{id(pool):x}.proto",
        package=package,
        syntax=syntax,
    )
    ep = fp.enum_type.add()
    ep.name = enum_name
    if allow_alias:
        ep.options.allow_alias = True
    for val_name, val_number in values.items():
        vp = ep.value.add()
        vp.name = val_name
        vp.number = val_number
    pool.Add(fp)
