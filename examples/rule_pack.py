"""Example rule pack — a plain module exposing a ``RULES`` list.

Consumers load this via ``SchemaChecker.load_rule_pack(rule_pack)`` or
via the CLI's ``--rule-pack examples.rule_pack`` flag. The module
stays a normal Python file — no registration framework, no plugin
entry points.

The rules below use the built-in ``deprecated`` option to demonstrate
the plugin API without needing any custom extensions registered in
the pool. Real-world packs often key off options like
``google.api.field_behavior`` or ``buf.validate.field``.
"""

from __future__ import annotations

from protokit.schema import FieldRuleContext, Severity


def no_newly_deprecated_fields(ctx: FieldRuleContext) -> None:
    """Flag fields that gained ``deprecated = true`` in the new schema.

    Newly-deprecated fields surprise consumers that still rely on
    them. This plugin emits a POLICY-severity finding so it only
    surfaces under the ``STRICT`` profile by default.
    """
    if ctx.old_field is None or ctx.new_field is None:
        return
    old_dep = ctx.old_field.GetOptions().deprecated
    new_dep = ctx.new_field.GetOptions().deprecated
    if not old_dep and new_dep:
        ctx.emit(
            severity=Severity.POLICY,
            message="field newly marked deprecated",
        )


def field_names_must_be_snake_case(ctx: FieldRuleContext) -> None:
    """Flag new fields whose names contain uppercase letters.

    Catches accidental ``camelCase`` field definitions on the new
    side. Matches only new fields so existing violations are
    grandfathered in.
    """
    if ctx.old_field is not None or ctx.new_field is None:
        return
    if any(c.isupper() for c in ctx.new_field.name):
        ctx.emit(
            severity=Severity.POLICY,
            message=f"new field '{ctx.new_field.name}' is not snake_case",
        )


#: Entries are ``(rule_id, plugin_fn)``. The engine registers each
#: via ``register_field_rule`` when the pack is loaded.
RULES = [
    ("no_newly_deprecated", no_newly_deprecated_fields),
    ("field_names_must_be_snake_case", field_names_must_be_snake_case),
]
