"""Synthetic user pack — declares a rule under profile='strict' ONLY.

Used by R11 unknown-profile tests: when --profile=default is
selected against this pack alone, the composed profile resolves
to zero rule_ids (this pack has no 'default' rules), triggering
``error[lint-unknown-profile]:``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from protokit.schema.lint.decorator import lint_rule
from protokit.schema.lint.model import ElementKind, LintSeverity

if TYPE_CHECKING:
    from protokit.schema.lint.model import FieldLintContext


@lint_rule(
    rule_id="strict-only/no-numbers",
    severity=LintSeverity.WARNING,
    profiles=("strict",),
    element=ElementKind.FIELD,
    message_template="Field {name!r} contains a digit",
)
def check_no_numbers(ctx: FieldLintContext) -> None:
    if any(c.isdigit() for c in ctx.field.name):
        ctx.emit(
            violation_kind="strict-only/no-numbers",
            params={"name": ctx.field.name},
        )


RULES = (check_no_numbers,)
