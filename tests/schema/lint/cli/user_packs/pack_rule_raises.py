"""Synthetic user pack — rule raises ValueError at check time.

Used by runtime_warnings emission tests: the engine catches the
exception (per its narrow-catch tuple), appends a
``LintRuntimeWarning(category="rule_exception")`` to the report,
and the CLI surfaces it as ``warning[lint-runtime]: rule_exception:
...`` on stderr.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from protokit.schema.lint.decorator import lint_rule
from protokit.schema.lint.model import ElementKind, LintSeverity

if TYPE_CHECKING:
    from protokit.schema.lint.model import FieldLintContext


@lint_rule(
    rule_id="pack-rule-raises/always-fails",
    severity=LintSeverity.WARNING,
    profiles=("default",),
    element=ElementKind.FIELD,
    message_template="(never rendered — rule raises before emit)",
)
def check_always_raises(ctx: FieldLintContext) -> None:
    raise ValueError("synthetic-failure")


RULES = (check_always_raises,)
