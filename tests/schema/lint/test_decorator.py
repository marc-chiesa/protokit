"""Tests for :mod:`protokit.schema.lint.decorator`.

Cover the @lint_rule decorator's metadata-attach contract, async
rejection, dual-shape passthrough to LintRuleSpec, and the
get_lint_spec accessor.
"""

from __future__ import annotations

from typing import Any

import pytest

from protokit.schema.lint.decorator import get_lint_spec, lint_rule
from protokit.schema.lint.model import (
    ElementKind,
    LintRuleSpec,
    LintSeverity,
)


class TestLintRuleHappyPath:
    """Decorator attaches a LintRuleSpec to the fn and returns the fn."""

    def test_decorator_attaches_lint_spec_attribute(self) -> None:
        """A decorated sync fn carries a _lint_spec matching the kwargs."""

        @lint_rule(
            rule_id="naming/snake-case-fields",
            severity=LintSeverity.WARNING,
            profiles=("default",),
            element=ElementKind.FIELD,
            message_template="Field {name!r} is not snake_case",
            source_spec="https://google.aip.dev/122",
        )
        def check_snake_case(_ctx: Any) -> None:
            return None

        spec: LintRuleSpec = check_snake_case._lint_spec  # type: ignore[attr-defined]
        assert isinstance(spec, LintRuleSpec)
        assert spec.rule_id == "naming/snake-case-fields"
        assert spec.severity is LintSeverity.WARNING
        assert spec.profiles == ("default",)
        assert spec.element is ElementKind.FIELD
        assert spec.message_template == "Field {name!r} is not snake_case"
        assert spec.source_spec == "https://google.aip.dev/122"
        assert spec.fn is check_snake_case

    def test_decorator_returns_fn_unchanged_aside_from_attribute(self) -> None:
        """The decorated fn is the same object as the input fn."""

        def original(ctx: Any) -> None:
            ctx.touch()

        wrapped = lint_rule(
            rule_id="x/y",
            severity=LintSeverity.INFO,
            profiles=(),
            element=ElementKind.MESSAGE,
            message_template="m",
        )(original)
        assert wrapped is original

    def test_two_distinct_rules_have_distinct_specs(self) -> None:
        """Decorating two functions does not share the spec."""

        @lint_rule(
            rule_id="rule/one",
            severity=LintSeverity.ERROR,
            profiles=("strict",),
            element=ElementKind.FIELD,
            message_template="one",
        )
        def rule_one(_ctx: Any) -> None:
            return None

        @lint_rule(
            rule_id="rule/two",
            severity=LintSeverity.WARNING,
            profiles=("default",),
            element=ElementKind.MESSAGE,
            message_template="two",
        )
        def rule_two(_ctx: Any) -> None:
            return None

        assert rule_one._lint_spec.rule_id == "rule/one"  # type: ignore[attr-defined]
        assert rule_two._lint_spec.rule_id == "rule/two"  # type: ignore[attr-defined]
        assert (
            rule_one._lint_spec is not rule_two._lint_spec  # type: ignore[attr-defined]
        )


class TestLintRuleAsyncRejection:
    """Async and async-generator callables are rejected at decoration time."""

    def test_async_def_rule_raises_typeerror(self) -> None:
        """An ``async def`` rule callable raises TypeError immediately."""
        with pytest.raises(TypeError, match="async or async-generator"):

            @lint_rule(
                rule_id="x/y",
                severity=LintSeverity.WARNING,
                profiles=(),
                element=ElementKind.FIELD,
                message_template="m",
            )
            async def async_rule(_ctx: Any) -> None:  # type: ignore[unused-ignore]
                return None

    def test_async_generator_rule_raises_typeerror(self) -> None:
        """An ``async def`` rule that yields raises TypeError immediately."""
        with pytest.raises(TypeError, match="async or async-generator"):

            @lint_rule(
                rule_id="x/y",
                severity=LintSeverity.WARNING,
                profiles=(),
                element=ElementKind.FIELD,
                message_template="m",
            )
            async def async_gen_rule(_ctx: Any) -> Any:  # type: ignore[misc]
                yield None


class TestLintRuleSpecDualShapeForwarding:
    """Decorator forwards severity / message_template to LintRuleSpec.

    The dual-shape invariant (single-kind vs multi-kind) is enforced
    by ``LintRuleSpec.__post_init__`` (locked in D1). The decorator
    must not mask that error — these tests confirm the validation
    path runs through the decorator unchanged.
    """

    def test_single_kind_severity_with_str_message_template_succeeds(
        self,
    ) -> None:
        """LintSeverity + str template is the single-kind shape."""

        @lint_rule(
            rule_id="x/y",
            severity=LintSeverity.WARNING,
            profiles=(),
            element=ElementKind.FIELD,
            message_template="m",
        )
        def rule(_ctx: Any) -> None:
            return None

        assert rule._lint_spec.severity is LintSeverity.WARNING  # type: ignore[attr-defined]
        assert rule._lint_spec.message_template == "m"  # type: ignore[attr-defined]

    def test_multi_kind_severity_with_dict_message_template_succeeds(
        self,
    ) -> None:
        """dict severity + dict template is the multi-kind shape."""

        @lint_rule(
            rule_id="x/y",
            severity={"k1": LintSeverity.WARNING, "k2": LintSeverity.ERROR},
            profiles=(),
            element=ElementKind.FIELD,
            message_template={"k1": "m1", "k2": "m2"},
        )
        def rule(_ctx: Any) -> None:
            return None

        spec = rule._lint_spec  # type: ignore[attr-defined]
        assert spec.severity == {
            "k1": LintSeverity.WARNING,
            "k2": LintSeverity.ERROR,
        }
        assert spec.message_template == {"k1": "m1", "k2": "m2"}

    def test_mixed_shape_raises_typeerror_through_decorator(self) -> None:
        """LintSeverity + dict template (mismatch) → TypeError from spec."""
        with pytest.raises(TypeError, match="must share the same shape"):

            @lint_rule(
                rule_id="x/y",
                severity=LintSeverity.WARNING,
                profiles=(),
                element=ElementKind.FIELD,
                message_template={"k1": "m1"},
            )
            def rule(_ctx: Any) -> None:
                return None


class TestGetLintSpec:
    """Convenience accessor surfaces clear errors on undecorated fns."""

    def test_get_lint_spec_returns_attached_spec(self) -> None:
        """A decorated fn yields its spec via the accessor."""

        @lint_rule(
            rule_id="x/y",
            severity=LintSeverity.INFO,
            profiles=(),
            element=ElementKind.FIELD,
            message_template="m",
        )
        def rule(_ctx: Any) -> None:
            return None

        spec = get_lint_spec(rule)
        assert spec.rule_id == "x/y"

    def test_get_lint_spec_undecorated_raises_typeerror(self) -> None:
        """An undecorated fn raises TypeError, not AttributeError."""

        def undecorated(_ctx: Any) -> None:
            return None

        with pytest.raises(TypeError, match="not @lint_rule-decorated"):
            get_lint_spec(undecorated)
