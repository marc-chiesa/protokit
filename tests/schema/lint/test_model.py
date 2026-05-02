"""Structural tests for :mod:`protokit.schema.lint.model`.

Locks the lint-side type contracts that downstream deliveries (engine,
registry, CLI formatters) load-bear on:

* :meth:`LintProfile.compose` zero-arg / single-arg / multi-arg merge
  semantics including most-strict-wins on conflicting overrides.
* :meth:`LintRuleSpec.severity_for` single-kind passthrough,
  multi-kind dict lookup, unregistered-kind ``KeyError``.
* All eight ``LintLocation`` variants' ``__str__`` outputs.
* All eight lint-context dataclasses construct with engine-injected
  fields, dispatch :meth:`emit` to ``_emit_fn``, and stay frozen.
* :class:`DuplicateRuleError` carries both source locations.
* :class:`LintFinding` / :class:`LintReport` shape, defaults, and the
  list-to-tuple snapshot in ``LintReport.__post_init__``.
* Enum value sets for :class:`LintSeverity` and :class:`ElementKind`.

Domain descriptor fields use ``unittest.mock.MagicMock`` because these
tests verify dataclass shape only — no descriptor walk is exercised.
The production engine wires real :mod:`google.protobuf.descriptor`
handles into the same fields.
"""

from __future__ import annotations

import dataclasses
from typing import Any
from unittest.mock import MagicMock

import pytest

from protokit.schema.lint.model import (
    DuplicateRuleError,
    ElementKind,
    EnumLintContext,
    EnumLocation,
    EnumValueLintContext,
    EnumValueLocation,
    FieldLintContext,
    FieldLocation,
    FileLintContext,
    FileLocation,
    LintFinding,
    LintProfile,
    LintReport,
    LintRuleSpec,
    LintSeverity,
    MessageLintContext,
    MessageLocation,
    MethodLintContext,
    MethodLocation,
    OneofLintContext,
    OneofLocation,
    ServiceLintContext,
    ServiceLocation,
)

# ---------------------------------------------------------------------------
# Module-level helpers — engine-injected field stubs and per-context factories.
#
# The eight context dataclasses declare ``_emit_fn`` / ``_rule_id`` /
# ``_effective_severity`` as required fields with no defaults (production
# engine always supplies them). These factories default them to no-op
# stubs so individual tests only have to specify the domain fields they
# care about.
# ---------------------------------------------------------------------------


def _stub_emit_fn(_finding: LintFinding) -> None:
    """No-op ``EmitFn`` stub for tests that don't inspect emitted findings."""


def _stub_severity_resolver(_kind: str) -> LintSeverity:
    """Default severity resolver — always returns WARNING."""
    return LintSeverity.WARNING


_DEFAULT_INJECTED: dict[str, Any] = {
    "_emit_fn": _stub_emit_fn,
    "_rule_id": "TEST",
    "_effective_severity": _stub_severity_resolver,
}


def _mock_descriptor(name: str = "demo") -> MagicMock:
    """Build a ``MagicMock`` with a usable ``name`` / ``full_name``.

    ``name=`` on the constructor is consumed by ``Mock`` itself, so we
    set the attributes after construction.
    """
    mock = MagicMock()
    mock.name = name
    mock.full_name = name
    return mock


def _make_file_ctx(**user_kwargs: Any) -> FileLintContext:
    defaults: dict[str, Any] = {
        "file": _mock_descriptor("demo.proto"),
        "pool": MagicMock(),
        "profile": "default",
        **_DEFAULT_INJECTED,
    }
    return FileLintContext(**{**defaults, **user_kwargs})


def _make_service_ctx(**user_kwargs: Any) -> ServiceLintContext:
    defaults: dict[str, Any] = {
        "service": _mock_descriptor("acme.UserService"),
        "file": _mock_descriptor("demo.proto"),
        "pool": MagicMock(),
        "profile": "default",
        **_DEFAULT_INJECTED,
    }
    return ServiceLintContext(**{**defaults, **user_kwargs})


def _make_method_ctx(**user_kwargs: Any) -> MethodLintContext:
    defaults: dict[str, Any] = {
        "method": _mock_descriptor("GetUser"),
        "service": _mock_descriptor("acme.UserService"),
        "file": _mock_descriptor("demo.proto"),
        "pool": MagicMock(),
        "profile": "default",
        **_DEFAULT_INJECTED,
    }
    return MethodLintContext(**{**defaults, **user_kwargs})


def _make_enum_ctx(**user_kwargs: Any) -> EnumLintContext:
    defaults: dict[str, Any] = {
        "enum": _mock_descriptor("acme.Status"),
        "file": _mock_descriptor("demo.proto"),
        "pool": MagicMock(),
        "profile": "default",
        **_DEFAULT_INJECTED,
    }
    return EnumLintContext(**{**defaults, **user_kwargs})


def _make_enum_value_ctx(**user_kwargs: Any) -> EnumValueLintContext:
    defaults: dict[str, Any] = {
        "value": _mock_descriptor("ACTIVE"),
        "enum": _mock_descriptor("acme.Status"),
        "file": _mock_descriptor("demo.proto"),
        "pool": MagicMock(),
        "profile": "default",
        **_DEFAULT_INJECTED,
    }
    return EnumValueLintContext(**{**defaults, **user_kwargs})


def _make_message_ctx(**user_kwargs: Any) -> MessageLintContext:
    defaults: dict[str, Any] = {
        "message": _mock_descriptor("acme.User"),
        "file": _mock_descriptor("demo.proto"),
        "pool": MagicMock(),
        "profile": "default",
        **_DEFAULT_INJECTED,
    }
    return MessageLintContext(**{**defaults, **user_kwargs})


def _make_field_ctx(**user_kwargs: Any) -> FieldLintContext:
    """Mint a FieldLintContext with engine-injected fields stubbed.

    Domain fields (field, message, file, pool, profile) all have
    sensible mock defaults; callers override only what they need.
    """
    defaults: dict[str, Any] = {
        "field": _mock_descriptor("email"),
        "message": _mock_descriptor("acme.User"),
        "file": _mock_descriptor("demo.proto"),
        "pool": MagicMock(),
        "profile": "default",
        **_DEFAULT_INJECTED,
    }
    return FieldLintContext(**{**defaults, **user_kwargs})


def _make_oneof_ctx(**user_kwargs: Any) -> OneofLintContext:
    defaults: dict[str, Any] = {
        "oneof": _mock_descriptor("kind"),
        "message": _mock_descriptor("acme.User"),
        "file": _mock_descriptor("demo.proto"),
        "pool": MagicMock(),
        "profile": "default",
        **_DEFAULT_INJECTED,
    }
    return OneofLintContext(**{**defaults, **user_kwargs})


# Map ElementKind -> factory for parametrized context tests.
_CONTEXT_FACTORIES = [
    pytest.param(_make_file_ctx, id="file"),
    pytest.param(_make_service_ctx, id="service"),
    pytest.param(_make_method_ctx, id="method"),
    pytest.param(_make_enum_ctx, id="enum"),
    pytest.param(_make_enum_value_ctx, id="enum_value"),
    pytest.param(_make_message_ctx, id="message"),
    pytest.param(_make_field_ctx, id="field"),
    pytest.param(_make_oneof_ctx, id="oneof"),
]


# ---------------------------------------------------------------------------
# LintProfile.compose
# ---------------------------------------------------------------------------


class TestLintProfileCompose:
    """Cover the three argument-count modes plus most-strict-wins merge."""

    def test_compose_zero_args_returns_identity(self) -> None:
        """Zero-arg compose returns ``LintProfile(name="composed")``."""
        composed = LintProfile.compose()
        assert composed.name == "composed"
        assert composed.rule_ids == frozenset()
        assert composed.min_severity is LintSeverity.WARNING
        assert composed.rule_severity_overrides == {}

    def test_compose_single_string_arg_raises_value_error(self) -> None:
        """Strings are rejected — caller must resolve names to instances."""
        with pytest.raises(ValueError) as excinfo:
            LintProfile.compose("default")
        # The error message advertises the caller's responsibility.
        assert "caller" in str(excinfo.value).lower() or "responsibility" in str(
            excinfo.value
        ).lower()

    def test_compose_single_lintprofile_returns_input_unchanged(self) -> None:
        """Single LintProfile arg is returned as-is (preserves name)."""
        original = LintProfile(
            name="strict",
            rule_ids=frozenset({"R1", "R2"}),
            min_severity=LintSeverity.ERROR,
        )
        result = LintProfile.compose(original)
        # Preserves identity AND name (not renamed to "composed").
        assert result is original
        assert result.name == "strict"

    def test_compose_multi_unions_rule_ids_and_picks_strictest_overrides(
        self,
    ) -> None:
        """Multi-arg compose unions rule_ids and picks strictest severities."""
        p1 = LintProfile(
            name="a",
            rule_ids=frozenset({"R1", "R2"}),
            min_severity=LintSeverity.WARNING,
            rule_severity_overrides={"R1": LintSeverity.INFO},
        )
        p2 = LintProfile(
            name="b",
            rule_ids=frozenset({"R2", "R3"}),
            min_severity=LintSeverity.ERROR,
            rule_severity_overrides={
                "R1": LintSeverity.ERROR,
                "R3": LintSeverity.WARNING,
            },
        )
        composed = LintProfile.compose(p1, p2)

        assert composed.name == "composed"
        assert composed.rule_ids == frozenset({"R1", "R2", "R3"})
        # Strictest of WARNING/ERROR is ERROR.
        assert composed.min_severity is LintSeverity.ERROR
        # R1: INFO (p1) vs ERROR (p2) -> ERROR wins.
        # R3: only in p2 -> WARNING.
        assert composed.rule_severity_overrides == {
            "R1": LintSeverity.ERROR,
            "R3": LintSeverity.WARNING,
        }


# ---------------------------------------------------------------------------
# LintRuleSpec.severity_for
# ---------------------------------------------------------------------------


class TestLintRuleSpecSeverityFor:
    """Cover single-kind passthrough, multi-kind dict lookup, missing key."""

    def test_severity_for_single_kind_returns_spec_severity(self) -> None:
        """Single-kind rule ignores the violation_kind argument."""
        spec = LintRuleSpec(
            rule_id="R",
            severity=LintSeverity.ERROR,
            profiles=("default",),
            source_spec="x",
            element=ElementKind.FIELD,
            message_template="t",
        )
        # Any string maps to the same severity.
        assert spec.severity_for("any_kind") is LintSeverity.ERROR
        assert spec.severity_for("") is LintSeverity.ERROR

    def test_severity_for_multi_kind_dict_lookup(self) -> None:
        """Multi-kind rule resolves severity per registered violation_kind."""
        spec = LintRuleSpec(
            rule_id="R",
            severity={
                "k1": LintSeverity.ERROR,
                "k2": LintSeverity.WARNING,
            },
            profiles=("default",),
            element=ElementKind.FIELD,
            message_template={"k1": "t1", "k2": "t2"},
        )
        assert spec.severity_for("k1") is LintSeverity.ERROR
        assert spec.severity_for("k2") is LintSeverity.WARNING

    def test_severity_for_unregistered_kind_raises_keyerror(self) -> None:
        """Multi-kind rule raises KeyError for unregistered kinds."""
        spec = LintRuleSpec(
            rule_id="R",
            severity={"k1": LintSeverity.ERROR},
            profiles=("default",),
            element=ElementKind.FIELD,
            message_template={"k1": "t1"},
        )
        with pytest.raises(KeyError):
            spec.severity_for("unregistered")


# ---------------------------------------------------------------------------
# LintLocation.__str__
# ---------------------------------------------------------------------------


class TestLintLocationStr:
    """Pin the documented string format for every location variant."""

    @pytest.mark.parametrize(
        ("location", "expected"),
        [
            pytest.param(
                FileLocation("a.proto"),
                "a.proto",
                id="file",
            ),
            pytest.param(
                ServiceLocation("a.proto", "acme.UserService"),
                "a.proto:acme.UserService",
                id="service",
            ),
            pytest.param(
                MethodLocation("a.proto", "acme.UserService", "GetUser"),
                "a.proto:acme.UserService/GetUser",
                id="method",
            ),
            pytest.param(
                EnumLocation("a.proto", "acme.Status"),
                "a.proto:acme.Status",
                id="enum",
            ),
            pytest.param(
                EnumValueLocation("a.proto", "acme.Status", "ACTIVE"),
                "a.proto:acme.Status.ACTIVE",
                id="enum_value",
            ),
            pytest.param(
                MessageLocation("a.proto", "acme.User"),
                "a.proto:acme.User",
                id="message",
            ),
            pytest.param(
                FieldLocation("a.proto", "acme.User", "email"),
                "a.proto:acme.User.email",
                id="field",
            ),
            pytest.param(
                OneofLocation("a.proto", "acme.User", "kind"),
                "a.proto:acme.User#kind",
                id="oneof",
            ),
        ],
    )
    def test_all_8_location_str_outputs_are_stable(
        self,
        location: object,
        expected: str,
    ) -> None:
        """Each variant renders to its documented canonical address shape."""
        assert str(location) == expected


# ---------------------------------------------------------------------------
# Frozen lint-context dataclasses
# ---------------------------------------------------------------------------


class TestContextInstantiation:
    """Cover construction, emit dispatch, and frozen immutability."""

    @pytest.mark.parametrize("factory", _CONTEXT_FACTORIES)
    def test_all_8_contexts_construct_with_engine_injected_fields(
        self,
        factory: Any,
    ) -> None:
        """Each context constructs with the engine-injected field stubs."""
        ctx = factory()
        assert ctx._rule_id == "TEST"
        assert callable(ctx._emit_fn)
        # The default resolver returns WARNING for any kind.
        assert ctx._effective_severity("anything") is LintSeverity.WARNING

    def test_context_emit_dispatches_to_emit_fn(self) -> None:
        """ctx.emit() builds a LintFinding and forwards it to _emit_fn.

        Verifies the locked shape: rule_id, severity (resolved via
        ``_effective_severity``), location (variant from
        ``ctx.location()``), violation_kind, params.
        """
        received: list[LintFinding] = []
        recorded_kinds: list[str] = []

        def recording_resolver(kind: str) -> LintSeverity:
            recorded_kinds.append(kind)
            return LintSeverity.ERROR

        ctx = _make_field_ctx(
            _emit_fn=received.append,
            _rule_id="rule.X",
            _effective_severity=recording_resolver,
        )
        ctx.emit(violation_kind="test_kind", params={"detail": "x"})

        assert len(received) == 1
        finding = received[0]
        assert finding.rule_id == "rule.X"
        assert finding.severity is LintSeverity.ERROR
        assert finding.violation_kind == "test_kind"
        assert finding.params == {"detail": "x"}
        # Location is the FieldLocation variant produced by FieldLintContext.
        assert isinstance(finding.location, FieldLocation)
        assert finding.location.file == "demo.proto"
        assert finding.location.message == "acme.User"
        assert finding.location.field == "email"

        # Severity resolver fired exactly once with the supplied kind.
        assert recorded_kinds == ["test_kind"]

    def test_context_frozen_immutability(self) -> None:
        """Lint contexts are frozen dataclasses — assignment raises."""
        ctx = _make_field_ctx()
        with pytest.raises(dataclasses.FrozenInstanceError):
            ctx._rule_id = "X"  # type: ignore[misc]
        with pytest.raises(dataclasses.FrozenInstanceError):
            ctx.profile = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# DuplicateRuleError
# ---------------------------------------------------------------------------


class TestDuplicateRuleError:
    """Verify the exception captures both source locations."""

    @staticmethod
    def _fn_a() -> None:
        return None

    @staticmethod
    def _fn_b() -> None:
        return None

    def test_duplicate_rule_error_constructible_with_two_fns(self) -> None:
        """DuplicateRuleError stores both fns and renders both qualnames."""
        err = DuplicateRuleError("R1", self._fn_a, self._fn_b)
        assert isinstance(err, Exception)
        assert err.rule_id == "R1"
        assert err.first_fn is self._fn_a
        assert err.second_fn is self._fn_b
        message = str(err)
        # Module-qualified names of both functions appear in the message
        # so the operator can find both registration sites.
        assert self._fn_a.__qualname__ in message
        assert self._fn_b.__qualname__ in message
        assert "R1" in message


# ---------------------------------------------------------------------------
# LintFinding + LintReport
# ---------------------------------------------------------------------------


class TestLintFindingLintReport:
    """Cover finding shape, report defaults, and tuple-snapshot post_init."""

    def test_lint_finding_instantiates_with_locked_field_shape(self) -> None:
        """LintFinding exposes all five fields and supports value equality."""
        finding = LintFinding(
            rule_id="R",
            severity=LintSeverity.ERROR,
            location=FileLocation("a.proto"),
            violation_kind="kind",
            params={"key": "val"},
        )
        assert finding.rule_id == "R"
        assert finding.severity is LintSeverity.ERROR
        assert finding.location == FileLocation("a.proto")
        assert finding.violation_kind == "kind"
        assert finding.params == {"key": "val"}

        twin = LintFinding(
            rule_id="R",
            severity=LintSeverity.ERROR,
            location=FileLocation("a.proto"),
            violation_kind="kind",
            params={"key": "val"},
        )
        assert finding == twin

    def test_lint_report_default_constructs_with_empty_tuples(self) -> None:
        """LintReport() defaults every collection to ``()`` (not None / list)."""
        report = LintReport()
        assert report.findings == ()
        assert report.diagnostics == ()
        assert report.profiles_run == ()
        assert report.rules_run == ()
        assert isinstance(report.findings, tuple)
        assert isinstance(report.diagnostics, tuple)
        assert isinstance(report.profiles_run, tuple)
        assert isinstance(report.rules_run, tuple)

    def test_lint_report_post_init_snapshots_lists_to_tuples(self) -> None:
        """Caller-supplied lists are coerced to tuples by ``__post_init__``."""
        f1 = LintFinding(
            rule_id="R",
            severity=LintSeverity.WARNING,
            location=FileLocation("a.proto"),
            violation_kind="k",
        )
        f2 = LintFinding(
            rule_id="R",
            severity=LintSeverity.WARNING,
            location=FileLocation("b.proto"),
            violation_kind="k",
        )
        report = LintReport(
            findings=[f1, f2],
            profiles_run=["default"],
            rules_run=["R"],
        )
        assert isinstance(report.findings, tuple)
        assert isinstance(report.profiles_run, tuple)
        assert isinstance(report.rules_run, tuple)
        assert report.findings == (f1, f2)
        assert report.profiles_run == ("default",)
        assert report.rules_run == ("R",)


# ---------------------------------------------------------------------------
# Enum value sets
# ---------------------------------------------------------------------------


class TestEnumValues:
    """Pin the value sets — engine, formatters, and external tools rely on them."""

    def test_lint_severity_enum_has_three_values(self) -> None:
        """LintSeverity carries error / warning / info."""
        assert {e.value for e in LintSeverity} == {"error", "warning", "info"}

    def test_element_kind_enum_has_eight_values(self) -> None:
        """ElementKind carries the eight protobuf element kinds."""
        assert {e.value for e in ElementKind} == {
            "file",
            "service",
            "method",
            "enum",
            "enum_value",
            "message",
            "field",
            "oneof",
        }
