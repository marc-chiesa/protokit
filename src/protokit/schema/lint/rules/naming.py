"""``naming`` rule pack — AIP-122 field-naming canary for protokit-lint.

D2 ships exactly one rule (``naming/snake-case-fields``); D6 grows
this module with the rest of the AIP-122 naming family
(upper-camel-messages, etc.).

References:
- AIP-122 § "Field names":
  https://google.aip.dev/122
- protokit-lint D2 plan:
  ``docs/plans/2026-05-02-001-feat-protokit-lint-d2-engine-plan.md``

Module shape echoes compat's ``RULES`` convention
(``schema/checker.py:217-220``): a module-level ``RULES`` tuple
listing the ``@lint_rule``-decorated functions this pack exports.
``LintEngine.load_rule_pack(module)`` reads ``module.RULES`` and
extracts each function's ``_lint_spec``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TYPE_CHECKING

from protokit.schema.lint.decorator import lint_rule
from protokit.schema.lint.model import ElementKind, LintSeverity

if TYPE_CHECKING:
    from protokit.schema.lint.model import FieldLintContext


# AIP-122 snake_case: lowercase start, alphanumeric segments separated
# by single underscores. Rejects: BadCamelCase (uppercase),
# with__double (consecutive underscores), trailing_ (trailing
# underscore), with-dash (non-word character), UPPER (uppercase).
# Note: protobuf grammar already rejects leading-underscore field
# names at the source level; the regex would also reject them, but
# in practice that branch is dead.
_SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")


@lint_rule(
    rule_id="naming/snake-case-fields",
    severity=LintSeverity.WARNING,
    profiles=("default",),
    element=ElementKind.FIELD,
    message_template="Field {name!r} is not snake_case (AIP-122)",
    source_spec="https://google.aip.dev/122",
)
def check_snake_case_fields(ctx: FieldLintContext) -> None:
    """Fire on field names that don't match AIP-122 snake_case.

    Skips the synthetic ``key`` / ``value`` fields generated inside
    protobuf map-entry messages: their names are pre-defined by the
    protobuf compiler from ``map<K, V>`` declarations and are not
    user-authored, so a snake_case warning would be noise. The
    detection is on the field's containing type (the entry message
    has ``map_entry = true`` set in its options); the user-facing
    map field itself (e.g., ``attributes`` in
    ``map<string, string> attributes = 1;``) IS user-authored and
    IS linted normally.
    """
    if ctx.field.containing_type.GetOptions().map_entry:
        return
    if not _SNAKE_CASE_RE.match(ctx.field.name):
        ctx.emit(
            violation_kind="naming/snake-case-fields",
            params={"name": ctx.field.name},
        )


# Module-level RULES tuple — exact echo of compat's
# `schema/checker.py:217-220` convention. ``LintEngine.load_rule_pack``
# reads this attribute.
RULES: tuple[Callable[..., None], ...] = (check_snake_case_fields,)
