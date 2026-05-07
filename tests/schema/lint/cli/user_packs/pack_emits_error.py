"""Synthetic pack — emits ERROR-severity findings.

Exercises the R20 exit-code ladder branch where ERROR-severity
findings force exit 1 regardless of ``--max-warnings``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from protokit.schema.lint.decorator import lint_rule
from protokit.schema.lint.model import ElementKind, LintSeverity

if TYPE_CHECKING:
    from protokit.schema.lint.model import FieldLintContext


@lint_rule(
    rule_id="error-pack/always-error",
    severity=LintSeverity.ERROR,
    profiles=("default",),
    element=ElementKind.FIELD,
    message_template="Synthetic ERROR finding on field {name!r}",
)
def emit_error_for_every_field(ctx: FieldLintContext) -> None:
    ctx.emit(
        violation_kind="error-pack/always-error",
        params={"name": ctx.field.name},
    )


RULES = (emit_error_for_every_field,)
