"""Basic schema-compatibility check.

Builds two descriptor pools representing an old and a new version of
``acme.User``, runs ``check_compatibility`` under each profile, and
prints the findings. Mirrors the worked example from the design doc.

Run from the repo root::

    python examples/schema_check.py
"""

from __future__ import annotations

import json

from google.protobuf import descriptor_pb2, descriptor_pool

from protokit.schema import CompatibilityLevel, check_compatibility

T = descriptor_pb2.FieldDescriptorProto


def _build_user_v1(pool: descriptor_pool.DescriptorPool) -> None:
    """Old schema: four fields, one of which will be removed."""
    fp = descriptor_pb2.FileDescriptorProto(
        name="user_v1.proto", package="acme", syntax="proto3",
    )
    # PhoneType enum
    enum = fp.enum_type.add()
    enum.name = "PhoneType"
    for idx, name in enumerate(["MOBILE", "HOME", "WORK"]):
        v = enum.value.add()
        v.name, v.number = name, idx
    # User message
    msg = fp.message_type.add()
    msg.name = "User"
    for name, num, ftype in [
        ("name", 1, T.TYPE_STRING),
        ("email", 2, T.TYPE_STRING),
        ("internal_notes", 4, T.TYPE_STRING),
    ]:
        f = msg.field.add()
        f.name, f.number, f.type = name, num, ftype
        f.label = T.LABEL_OPTIONAL
    phone_field = msg.field.add()
    phone_field.name = "phone_type"
    phone_field.number = 3
    phone_field.type = T.TYPE_ENUM
    phone_field.type_name = "acme.PhoneType"
    phone_field.label = T.LABEL_OPTIONAL
    pool.Add(fp)


def _build_user_v2(pool: descriptor_pool.DescriptorPool) -> None:
    """New schema: email retyped, internal_notes dropped, nickname added, FAX added."""
    fp = descriptor_pb2.FileDescriptorProto(
        name="user_v2.proto", package="acme", syntax="proto3",
    )
    enum = fp.enum_type.add()
    enum.name = "PhoneType"
    for idx, name in enumerate(["MOBILE", "HOME", "WORK", "FAX"]):
        v = enum.value.add()
        v.name, v.number = name, idx
    msg = fp.message_type.add()
    msg.name = "User"
    # name (unchanged)
    f = msg.field.add()
    f.name, f.number, f.type = "name", 1, T.TYPE_STRING
    f.label = T.LABEL_OPTIONAL
    # email: string -> bytes (same wire group, semantic change)
    f = msg.field.add()
    f.name, f.number, f.type = "email", 2, T.TYPE_BYTES
    f.label = T.LABEL_OPTIONAL
    # phone_type (unchanged)
    f = msg.field.add()
    f.name, f.number, f.type = "phone_type", 3, T.TYPE_ENUM
    f.type_name = "acme.PhoneType"
    f.label = T.LABEL_OPTIONAL
    # nickname — new, proto3 `optional` → goes into a synthetic oneof
    nick_oneof = msg.oneof_decl.add()
    nick_oneof.name = "_nickname"
    f = msg.field.add()
    f.name, f.number, f.type = "nickname", 5, T.TYPE_STRING
    f.label = T.LABEL_OPTIONAL
    f.proto3_optional = True
    f.oneof_index = 0
    pool.Add(fp)


def _print_report(label: str, report) -> None:
    print(f"\n--- {label} (level={report.level.value}) ---")
    if report.is_compatible:
        print("COMPATIBLE")
        return
    print(f"INCOMPATIBLE: {len(report)} finding(s)")
    for f in report:
        print(f"  [{f.severity.value}/{f.direction.value}] "
              f"{f.path}: {f.message} ({f.rule_id})")


def main() -> None:
    old_pool = descriptor_pool.DescriptorPool()
    new_pool = descriptor_pool.DescriptorPool()
    _build_user_v1(old_pool)
    _build_user_v2(new_pool)

    for level in (
        CompatibilityLevel.WIRE,
        CompatibilityLevel.CONSUMER_SAFE,
        CompatibilityLevel.PRODUCER_SAFE,
        CompatibilityLevel.STRICT,
    ):
        report = check_compatibility(
            old_pool, "acme.User",
            new_pool, "acme.User",
            level=level,
        )
        _print_report(level.name, report)

    # Minimal JSON view of the CONSUMER_SAFE report.
    print("\n--- JSON shape (CONSUMER_SAFE) ---")
    report = check_compatibility(
        old_pool, "acme.User",
        new_pool, "acme.User",
        level=CompatibilityLevel.CONSUMER_SAFE,
    )
    print(json.dumps({
        "compatible": report.is_compatible,
        "level": report.level.value,
        "findings": [
            {
                "path": str(f.path),
                "rule_id": f.rule_id,
                "severity": f.severity.value,
                "direction": f.direction.value,
                "message": f.message,
            }
            for f in report.findings
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
