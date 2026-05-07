"""Synthetic user pack A — one rule under profile='default'.

Used as the multi-pack happy-path fixture: pairs with
``pack_user_b`` to exercise R25's multi-pack provenance line.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from protokit.schema.lint.decorator import lint_rule
from protokit.schema.lint.model import ElementKind, LintSeverity

if TYPE_CHECKING:
    from protokit.schema.lint.model import FieldLintContext


@lint_rule(
    rule_id="user-a/no-leading-x",
    severity=LintSeverity.WARNING,
    profiles=("default",),
    element=ElementKind.FIELD,
    message_template="Field {name!r} starts with 'x'",
)
def check_no_leading_x(ctx: FieldLintContext) -> None:
    if ctx.field.name.startswith("x"):
        ctx.emit(
            violation_kind="user-a/no-leading-x",
            params={"name": ctx.field.name},
        )


RULES = (check_no_leading_x,)
