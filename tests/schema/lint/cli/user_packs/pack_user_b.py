"""Synthetic user pack B — one rule under profile='default'.

Pairs with ``pack_user_a`` for multi-pack composition tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from protokit.schema.lint.decorator import lint_rule
from protokit.schema.lint.model import ElementKind, LintSeverity

if TYPE_CHECKING:
    from protokit.schema.lint.model import FieldLintContext


@lint_rule(
    rule_id="user-b/no-leading-z",
    severity=LintSeverity.WARNING,
    profiles=("default",),
    element=ElementKind.FIELD,
    message_template="Field {name!r} starts with 'z'",
)
def check_no_leading_z(ctx: FieldLintContext) -> None:
    if ctx.field.name.startswith("z"):
        ctx.emit(
            violation_kind="user-b/no-leading-z",
            params={"name": ctx.field.name},
        )


RULES = (check_no_leading_z,)
