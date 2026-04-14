"""Custom plugin + rule-pack loading demo.

Builds two versions of ``acme.Account`` where the new version:

  1. Newly deprecates the ``legacy_id`` field (POLICY finding from
     the rule pack's ``no_newly_deprecated`` plugin).
  2. Introduces a non-snake-case ``fullName`` field (POLICY finding
     from the rule pack's ``field_names_must_be_snake_case`` plugin).

Shows two registration flows:

  - Direct: ``SchemaChecker.register_field_rule(id, fn)``.
  - Rule pack: ``SchemaChecker.load_rule_pack(module)``.

Run from the repo root::

    python examples/schema_plugin.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the examples dir importable as a package so ``rule_pack`` resolves.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from google.protobuf import descriptor_pb2, descriptor_pool  # noqa: E402

import rule_pack  # noqa: E402  — ./rule_pack.py

from protokit.schema import (  # noqa: E402
    CompatibilityLevel,
    FieldRuleContext,
    SchemaChecker,
    Severity,
)

T = descriptor_pb2.FieldDescriptorProto


def _build_account(
    pool: descriptor_pool.DescriptorPool,
    *,
    deprecate_legacy_id: bool,
    add_camel_case_field: bool,
    file_label: str,
) -> None:
    fp = descriptor_pb2.FileDescriptorProto(
        name=f"account_{file_label}.proto", package="acme", syntax="proto3",
    )
    msg = fp.message_type.add()
    msg.name = "Account"

    id_f = msg.field.add()
    id_f.name, id_f.number, id_f.type = "id", 1, T.TYPE_STRING
    id_f.label = T.LABEL_OPTIONAL

    legacy_f = msg.field.add()
    legacy_f.name, legacy_f.number, legacy_f.type = "legacy_id", 2, T.TYPE_STRING
    legacy_f.label = T.LABEL_OPTIONAL
    if deprecate_legacy_id:
        legacy_f.options.deprecated = True

    if add_camel_case_field:
        cc_f = msg.field.add()
        cc_f.name, cc_f.number, cc_f.type = "fullName", 3, T.TYPE_STRING
        cc_f.label = T.LABEL_OPTIONAL

    pool.Add(fp)


def _min_age_for_new_messages(ctx) -> None:
    """Message-level plugin: toy rule that fires on every visited message.

    Demonstrates register_message_rule. In a real codebase this
    might enforce documentation presence or cross-field invariants.
    """
    ctx.emit(
        severity=Severity.POLICY,
        message=f"visited message '{ctx.path}'",
    )


def main() -> None:
    old_pool = descriptor_pool.DescriptorPool()
    new_pool = descriptor_pool.DescriptorPool()
    _build_account(
        old_pool, deprecate_legacy_id=False,
        add_camel_case_field=False, file_label="old",
    )
    _build_account(
        new_pool, deprecate_legacy_id=True,
        add_camel_case_field=True, file_label="new",
    )

    # Register a one-off field plugin directly.
    def flag_short_ids(ctx: FieldRuleContext) -> None:
        if ctx.new_field is None:
            return
        if ctx.new_field.name == "id" and ctx.new_field.type == T.TYPE_STRING:
            ctx.emit(
                severity=Severity.POLICY,
                message="id field uses TYPE_STRING — consider a strongly-typed ID",
            )

    checker = SchemaChecker(level=CompatibilityLevel.STRICT)
    checker.register_field_rule("flag_short_ids", flag_short_ids)
    checker.register_message_rule("visit_log", _min_age_for_new_messages)
    # Load the whole example rule pack.
    checker.load_rule_pack(rule_pack)

    report = checker.check(old_pool, "acme.Account", new_pool, "acme.Account")

    print(f"protokit compat demo — {len(report)} finding(s) under STRICT\n")
    for f in report:
        print(f"  [{f.severity.value}/{f.direction.value}] "
              f"{f.path if f.path else '(root)'}: {f.message} "
              f"({f.rule_id})")

    print()
    print("COMPATIBLE" if report.is_compatible else "INCOMPATIBLE")


if __name__ == "__main__":
    main()
