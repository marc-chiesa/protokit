"""``enum`` rule pack — semantic enum rules for protokit-lint.

Buf BASIC parity rules covering enum *semantics* (as opposed to enum
*naming*, which lives in :mod:`protokit.schema.lint.rules.naming`).
The pack ships two rules:

- ``enum/no-allow-alias`` (buf:ENUM_NO_ALLOW_ALIAS) — fires whenever
  an enum sets ``option allow_alias = true``, including the case
  where the option is structurally necessary (multiple values
  sharing the same number). Buf flags this unconditionally as a
  design discouragement signal; protokit mirrors so the parity
  story holds at the rule-fires level.
- ``enum/first-value-zero`` (buf:ENUM_FIRST_VALUE_ZERO) — fires
  when an enum's first declared value's number is not zero.
  Proto3 grammar requires zero as the first value (so this rule is
  unreachable on a successfully compiled proto3 enum), but proto2
  allows arbitrary first-value numbers and buf still flags those
  cases. Protokit mirrors.

References:
- buf BASIC rule catalog (parity targets named per-rule via
  ``source_spec="buf:<RULE_ID>"``).
- The enum-rule pack was introduced as part of the BASIC rule-library
  build-out; see the project's design notes for full rationale.

Module shape mirrors :mod:`protokit.schema.lint.rules.naming`:
a top-level ``RULES`` tuple of ``@lint_rule``-decorated callables,
each carrying its ``LintRuleSpec`` on ``fn._lint_spec``. The engine
reads ``module.RULES`` via :meth:`LintEngine.load_rule_pack`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from protokit.schema.lint.decorator import lint_rule
from protokit.schema.lint.model import ElementKind, LintSeverity

if TYPE_CHECKING:
    from protokit.schema.lint.model import EnumLintContext


@lint_rule(
    rule_id="enum/no-allow-alias",
    severity=LintSeverity.ERROR,
    profiles=("recommended", "default"),
    element=ElementKind.ENUM,
    message_template="Enum {name!r} sets allow_alias = true",
    source_spec="buf:ENUM_NO_ALLOW_ALIAS",
)
def check_no_allow_alias(ctx: EnumLintContext) -> None:
    """Fire on enums that set ``option allow_alias = true``.

    Buf BASIC flags this unconditionally as a design discouragement
    signal — including the case where the option is structurally
    necessary (multiple enum values declared with the same number).
    Protokit mirrors that posture to keep ``source_spec="buf:
    ENUM_NO_ALLOW_ALIAS"`` parity honest at the rule-fires level;
    if a future delivery wants to distinguish "structurally needed
    alias" from "accidentally-set alias", it would land as a
    separate, narrower rule rather than weakening this one.
    """
    if ctx.enum.GetOptions().allow_alias:
        ctx.emit(
            violation_kind="enum/no-allow-alias",
            params={"name": ctx.enum.name},
        )


@lint_rule(
    rule_id="enum/first-value-zero",
    severity=LintSeverity.ERROR,
    profiles=("recommended", "default"),
    element=ElementKind.ENUM,
    message_template=(
        "Enum {name!r} first value {first_value!r} has number "
        "{first_number} (must be 0)"
    ),
    source_spec="buf:ENUM_FIRST_VALUE_ZERO",
)
def check_first_value_zero(ctx: EnumLintContext) -> None:
    """Fire on enums whose first declared value's number is not zero.

    Proto3 grammar requires the first enum value to have number 0
    — a proto3 enum violating this fails to compile, so the rule
    is effectively unreachable on a successfully compiled proto3
    file. Proto2 permits arbitrary first-value numbers, and buf
    BASIC's ENUM_FIRST_VALUE_ZERO flags such proto2 enums
    regardless. Protokit mirrors.

    Empty enums (no declared values) are unreachable in practice
    — the protobuf grammar rejects them at parse time — but the
    rule guards against an empty ``ctx.enum.values`` sequence
    defensively to avoid an ``IndexError`` if a synthetic
    descriptor ever surfaces one.
    """
    if not ctx.enum.values:
        return
    first = ctx.enum.values[0]
    if first.number != 0:
        ctx.emit(
            violation_kind="enum/first-value-zero",
            params={
                "name": ctx.enum.name,
                "first_value": first.name,
                "first_number": first.number,
            },
        )


# Module-level RULES tuple read by ``LintEngine.load_rule_pack``.
RULES: tuple[Callable[..., None], ...] = (
    check_no_allow_alias,
    check_first_value_zero,
)
