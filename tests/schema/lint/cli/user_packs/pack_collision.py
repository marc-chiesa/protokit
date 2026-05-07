"""Synthetic user pack — rule_id collides with built-in canary.

Triggers DuplicateRuleError from engine.load_rule_pack →
``error[lint-rule-collision]:``. The colliding rule_id is
``naming/snake-case-fields``, which is already loaded from
``BUILTIN_PACKS`` via the auto-load step.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from protokit.schema.lint.decorator import lint_rule
from protokit.schema.lint.model import ElementKind, LintSeverity

if TYPE_CHECKING:
    from protokit.schema.lint.model import FieldLintContext


@lint_rule(
    rule_id="naming/snake-case-fields",  # collides with built-in canary
    severity=LintSeverity.WARNING,
    profiles=("default",),
    element=ElementKind.FIELD,
    message_template="Reimplemented snake-case check",
)
def check_snake_case_reimpl(ctx: FieldLintContext) -> None:
    pass  # behavior doesn't matter — the collision fires at load time


RULES = (check_snake_case_reimpl,)
