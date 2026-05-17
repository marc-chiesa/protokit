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
    LintRuleError,
    LintRuleSpec,
    LintRuntimeWarning,
    LintSeverity,
    MessageLintContext,
    MessageLocation,
    MethodLintContext,
    MethodLocation,
    OneofLintContext,
    OneofLocation,
    ServiceLintContext,
    ServiceLocation,
    _LintContextEmitMixin,
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
        # ce:review follow-up (Finding #4): package_options moved to
        # default `= None` on the dataclass, so test helpers no longer
        # need to thread it through. Pass via user_kwargs to exercise the
        # populated path.
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
        "source_info_descriptors": None,
        **_DEFAULT_INJECTED,
    }
    return MethodLintContext(**{**defaults, **user_kwargs})


def _make_enum_ctx(**user_kwargs: Any) -> EnumLintContext:
    defaults: dict[str, Any] = {
        "enum": _mock_descriptor("acme.Status"),
        "file": _mock_descriptor("demo.proto"),
        "pool": MagicMock(),
        "profile": "default",
        "source_info_descriptors": None,
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
        "source_info_descriptors": None,
        **_DEFAULT_INJECTED,
    }
    return EnumValueLintContext(**{**defaults, **user_kwargs})


def _make_message_ctx(**user_kwargs: Any) -> MessageLintContext:
    defaults: dict[str, Any] = {
        "message": _mock_descriptor("acme.User"),
        "file": _mock_descriptor("demo.proto"),
        "pool": MagicMock(),
        "profile": "default",
        "source_info_descriptors": None,
        **_DEFAULT_INJECTED,
    }
    return MessageLintContext(**{**defaults, **user_kwargs})


def _make_field_ctx(**user_kwargs: Any) -> FieldLintContext:
    """Mint a FieldLintContext with engine-injected fields stubbed.

    Domain fields (field, message, file, pool, profile) all have
    sensible mock defaults; callers override only what they need.
    ``source_info_descriptors`` defaults to ``None`` — the legitimate
    "caller did not opt into ``include_source_info=True``" state.
    """
    defaults: dict[str, Any] = {
        "field": _mock_descriptor("email"),
        "message": _mock_descriptor("acme.User"),
        "file": _mock_descriptor("demo.proto"),
        "pool": MagicMock(),
        "profile": "default",
        "source_info_descriptors": None,
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

# Map context-factory -> expected LintLocation variant emitted by
# the matching context's location() override. Used by the all-8
# emit-dispatch parametrize so a copy-paste error in any single
# context's location() body surfaces immediately.
_CONTEXT_LOCATION_EXPECTATIONS = [
    pytest.param(_make_file_ctx, FileLocation, id="file"),
    pytest.param(_make_service_ctx, ServiceLocation, id="service"),
    pytest.param(_make_method_ctx, MethodLocation, id="method"),
    pytest.param(_make_enum_ctx, EnumLocation, id="enum"),
    pytest.param(_make_enum_value_ctx, EnumValueLocation, id="enum_value"),
    pytest.param(_make_message_ctx, MessageLocation, id="message"),
    pytest.param(_make_field_ctx, FieldLocation, id="field"),
    pytest.param(_make_oneof_ctx, OneofLocation, id="oneof"),
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

    def test_compose_single_string_arg_raises_type_error(self) -> None:
        """Strings are rejected — caller must resolve names to instances.

        Type signature accepts ``LintProfile`` only; a ``str`` argument
        triggers the runtime guard with ``TypeError``.
        """
        with pytest.raises(TypeError) as excinfo:
            LintProfile.compose("default")  # type: ignore[arg-type]
        # The error message advertises the caller's responsibility.
        assert "caller" in str(excinfo.value).lower() or "responsibility" in str(
            excinfo.value
        ).lower()

    def test_compose_none_arg_raises_type_error(self) -> None:
        """``None`` is also rejected (guard against registry misses)."""
        with pytest.raises(TypeError):
            LintProfile.compose(None)  # type: ignore[arg-type]

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

    def test_compose_multi_arg_with_embedded_string_raises(self) -> None:
        """Multi-arg compose with one string argument fails fast."""
        p = LintProfile(name="x")
        with pytest.raises(TypeError):
            LintProfile.compose(p, "name")  # type: ignore[arg-type]

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

    @pytest.mark.parametrize(
        ("severity", "message_template"),
        [
            pytest.param(
                {"k1": LintSeverity.ERROR}, "single",
                id="multi_kind_severity_with_single_template",
            ),
            pytest.param(
                LintSeverity.ERROR, {"k1": "t1"},
                id="single_severity_with_multi_kind_template",
            ),
        ],
    )
    def test_dual_shape_invariant_rejects_mismatch(
        self,
        severity: object,
        message_template: object,
    ) -> None:
        """severity and message_template must share the same shape.

        Plugin authors will write `LintRuleSpec(severity=dict, ...,
        message_template="single string")` — without this guard, the
        spec registers cleanly and only fails at first finding render.
        """
        with pytest.raises(TypeError, match="same shape"):
            LintRuleSpec(
                rule_id="R",
                severity=severity,  # type: ignore[arg-type]
                profiles=("default",),
                element=ElementKind.FIELD,
                message_template=message_template,  # type: ignore[arg-type]
            )


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

    @pytest.mark.parametrize(
        ("factory", "expected_location_cls"),
        _CONTEXT_LOCATION_EXPECTATIONS,
    )
    def test_each_context_location_returns_matching_variant(
        self,
        factory: Any,
        expected_location_cls: type,
    ) -> None:
        """Every context's ``location()`` returns the matching ``LintLocation`` variant.

        Without this parametrize a copy-paste error in any context's
        ``location()`` body — e.g., ``self.field.name`` referenced from
        a class without ``field`` — would only surface at runtime when
        the engine first invokes that context's emit pipeline.
        """
        ctx = factory()
        loc = ctx.location()
        assert isinstance(loc, expected_location_cls)
        # Smoke-test the file attribute carries through (every variant
        # has a ``file`` field except FileLocation, which carries the
        # file name as its only attribute under the same name).
        assert loc.file == "demo.proto"

    def test_mixin_location_raises_notimplemented_when_not_overridden(self) -> None:
        """The defensive raise in ``_LintContextEmitMixin.location`` fires.

        Locks the contract that the engine's ``emit()`` dispatch
        rejects a subclass that forgot to override ``location()``.
        Future deliveries that add a 9th context dataclass and skip the
        override hit this raise instead of a confusing AttributeError.
        """
        from protokit.schema.lint.model import _LintContextEmitMixin

        class _Bare(_LintContextEmitMixin):
            pass

        bare = _Bare()
        with pytest.raises(NotImplementedError, match="must override location"):
            bare.location()


# ---------------------------------------------------------------------------
# AC-05: ctx.pool mutation prohibition is documented on every context
# ---------------------------------------------------------------------------


_POOL_BEARING_CONTEXTS: list[type[_LintContextEmitMixin]] = [
    FileLintContext,
    ServiceLintContext,
    MethodLintContext,
    EnumLintContext,
    EnumValueLintContext,
    MessageLintContext,
    FieldLintContext,
    OneofLintContext,
]


def _normalize_docstring(doc: str) -> str:
    """Collapse docstring whitespace so line-wrapping doesn't hide phrases.

    Python preserves the verbatim docstring text including leading
    indentation and line breaks. ``"MUST NOT"`` legitimately wraps
    across a line boundary in the wrapped 80-col attribute
    descriptions, so substring checks would miss it. Collapsing
    whitespace makes the assertions resilient to harmless
    re-flowing while still catching meaning-changing edits. Used
    by both the AC-05 and AC-06 docstring-contract tests.
    """
    return " ".join(doc.split())


class TestPoolMutationDocstringContract:
    """AC-05: lock the ``ctx.pool`` mutation prohibition into every docstring.

    The engine relies on rules treating ``ctx.pool`` as read-only;
    in-walk mutation surfaces as cross-rule action-at-a-distance.
    The contract is enforced by convention only (the descriptor pool
    is not Python-level immutable), so the docstrings ARE the
    contract — these assertions catch any future docstring edit
    that would silently weaken the contract.
    """

    def test_mixin_class_docstring_documents_pool_mutation_prohibition(
        self,
    ) -> None:
        raw = _LintContextEmitMixin.__doc__
        assert raw is not None
        doc = _normalize_docstring(raw)
        assert "AC-05" in doc
        # The mixin has no ``pool`` attribute itself; the prohibition
        # must point readers to the per-kind contexts.
        assert "MUST NOT mutate" in doc
        assert "ctx.pool" in doc

    @pytest.mark.parametrize(
        "context_cls",
        _POOL_BEARING_CONTEXTS,
        ids=lambda c: c.__name__,
    )
    def test_each_context_pool_attribute_documents_prohibition(
        self,
        context_cls: type[_LintContextEmitMixin],
    ) -> None:
        """All eight per-kind contexts repeat the prohibition on ``pool``."""
        raw = context_cls.__doc__
        assert raw is not None, f"{context_cls.__name__} missing docstring"
        doc = _normalize_docstring(raw)
        assert "MUST NOT mutate" in doc, (
            f"{context_cls.__name__}.pool docstring missing the AC-05 "
            f"mutation prohibition"
        )
        # Pool-specificity guard: the prohibition must mention ``pool``
        # specifically. A future weakening reword to "MUST NOT mutate
        # any attribute" would otherwise pass the substring check
        # while silently broadening the contract beyond the engine's
        # actual invariant.
        assert "pool" in doc, (
            f"{context_cls.__name__}.pool docstring weakens AC-05: the "
            f"prohibition must reference 'pool' specifically, not a "
            f"generic 'any attribute'"
        )
        assert "AC-05" in doc, (
            f"{context_cls.__name__}.pool docstring missing the AC-05 anchor"
        )


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
        assert report.runtime_warnings == ()
        assert report.filtered_count == 0
        assert isinstance(report.findings, tuple)
        assert isinstance(report.diagnostics, tuple)
        assert isinstance(report.profiles_run, tuple)
        assert isinstance(report.rules_run, tuple)
        assert isinstance(report.runtime_warnings, tuple)
        assert isinstance(report.filtered_count, int)

    def test_lint_report_d1_positional_construction_still_works(self) -> None:
        """The four pre-D2 positional args still construct a valid report.

        D2 appends ``runtime_warnings`` and ``filtered_count`` after
        ``rules_run``, both defaulted, so existing four-arg positional
        construction in D1 callers continues to type-check and run.
        """
        report = LintReport((), (), (), ())
        assert report.findings == ()
        assert report.diagnostics == ()
        assert report.profiles_run == ()
        assert report.rules_run == ()
        # New fields take their defaults.
        assert report.runtime_warnings == ()
        assert report.filtered_count == 0

    def test_lint_report_runtime_warnings_snapshots_list_to_tuple(self) -> None:
        """Caller-supplied list for ``runtime_warnings`` is coerced to a tuple."""
        warning = LintRuntimeWarning(
            category="rule_exception",
            rule_id="naming/snake-case-fields",
            message="oops",
            exception_type="ValueError",
            descriptor_path="a.proto:Foo.bar",
        )
        warnings_list = [warning]
        report = LintReport(runtime_warnings=warnings_list)
        assert isinstance(report.runtime_warnings, tuple)
        assert report.runtime_warnings == (warning,)
        # Mutation of the input list does not affect the report — proves
        # snapshot at __post_init__ is a tuple, not an aliased list.
        warnings_list.clear()
        assert report.runtime_warnings == (warning,)

    def test_get_type_hints_lint_report_resolves_with_localns(self) -> None:
        """``typing.get_type_hints(LintReport, localns=...)`` resolves.

        ``LintReport.diagnostics`` references ``LintCompileDiagnostic``
        from another module (preserving the cold-import contract — a
        runtime import here would drag ``compile.py`` (and its full
        dependency chain) into every consumer of ``lint.model``).
        Tooling that needs to introspect annotations supplies
        ``localns`` with the resolved type. This test documents the
        canonical pattern; the TYPE_CHECKING import in ``model.py``
        gives static type-checkers the same resolution.
        """
        import typing

        from protokit.schema.compile import LintCompileDiagnostic

        hints = typing.get_type_hints(
            LintReport,
            localns={"LintCompileDiagnostic": LintCompileDiagnostic},
        )
        # The diagnostics annotation resolves to a generic alias whose
        # args include LintCompileDiagnostic.
        assert "diagnostics" in hints
        assert LintCompileDiagnostic in typing.get_args(hints["diagnostics"])

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
# LintRuntimeWarning — discriminator-based engine-stage warnings.
# ---------------------------------------------------------------------------


class TestLintRuntimeWarning:
    """Cover both ``category`` cases and field-population per category."""

    def test_rule_exception_category_constructs_with_full_field_set(self) -> None:
        """``category="rule_exception"`` populates every field."""
        warning = LintRuntimeWarning(
            category="rule_exception",
            rule_id="naming/snake-case-fields",
            message="ValueError: bad input",
            exception_type="ValueError",
            descriptor_path="a.proto:Foo.bar",
        )
        assert warning.category == "rule_exception"
        assert warning.rule_id == "naming/snake-case-fields"
        assert warning.message == "ValueError: bad input"
        assert warning.exception_type == "ValueError"
        assert warning.descriptor_path == "a.proto:Foo.bar"

    def test_unloaded_rule_category_constructs_with_optional_fields_none(self) -> None:
        """``category="unloaded_rule"`` leaves exception_type / descriptor_path None."""
        warning = LintRuntimeWarning(
            category="unloaded_rule",
            rule_id="missing/rule",
            message="rule 'missing/rule' is named in profile 'x' but not loaded",
        )
        assert warning.category == "unloaded_rule"
        assert warning.rule_id == "missing/rule"
        assert "not loaded" in warning.message
        assert warning.exception_type is None
        assert warning.descriptor_path is None

    def test_runtime_warning_supports_value_equality(self) -> None:
        """Two warnings with the same fields compare equal (frozen dataclass)."""
        a = LintRuntimeWarning(
            category="rule_exception",
            rule_id="x",
            message="m",
            exception_type="ValueError",
            descriptor_path="a.proto:F.b",
        )
        b = LintRuntimeWarning(
            category="rule_exception",
            rule_id="x",
            message="m",
            exception_type="ValueError",
            descriptor_path="a.proto:F.b",
        )
        assert a == b

    def test_runtime_warning_is_frozen(self) -> None:
        """The dataclass is frozen — attribute reassignment raises."""
        warning = LintRuntimeWarning(
            category="unloaded_rule",
            rule_id="x",
            message="m",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            warning.rule_id = "y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# LintRuleError — explicit fail-soft signal for rule authors.
# ---------------------------------------------------------------------------


class TestLintRuleError:
    """LintRuleError is a plain Exception subclass for use by rule authors."""

    def test_lint_rule_error_subclasses_exception_not_baseexception(self) -> None:
        """LintRuleError IS an Exception subclass (caught by the engine)."""
        assert issubclass(LintRuleError, Exception)
        # Sanity check the engine's catch tuple covers it indirectly:
        # the engine catches Exception subclasses by enumeration; this
        # test pins the inheritance chain so downstream changes can't
        # accidentally promote it to BaseException-but-not-Exception.
        assert LintRuleError.__mro__[1] is Exception

    def test_lint_rule_error_constructs_with_message(self) -> None:
        """LintRuleError(msg) carries the message via str()."""
        err = LintRuleError("rule bailed because ...")
        assert str(err) == "rule bailed because ..."

    def test_lint_rule_error_docstring_locks_exact_catch_tuple(self) -> None:
        """AC-06: the docstring states the catch tuple "is exactly".

        The previous wording ("at minimum includes") implied the engine
        could widen the tuple silently, leaving rule authors to discover
        new caught exceptions empirically. The corrected wording locks
        the contract at the documented set, and the listed tuple
        matches ``engine.py:_RULE_EXCEPTION_TUPLE`` byte-for-byte
        (six items: ``KeyError`` is omitted because ``LookupError``
        already covers it). The structural tuple-value pin lives in
        ``test_engine.py`` adjacent to ``_RULE_EXCEPTION_TUPLE`` so
        engine renames trip the test next door rather than across
        modules.
        """
        raw = LintRuleError.__doc__
        assert raw is not None
        doc = _normalize_docstring(raw)
        assert "is exactly" in doc, (
            "LintRuleError docstring must say the catch tuple 'is exactly' "
            "(the previous 'at minimum includes' wording let the engine "
            "drift unnoticed)"
        )
        assert "at minimum includes" not in doc, (
            "stale wording 'at minimum includes' must be removed"
        )
        for member in (
            "SystemExit", "ValueError", "TypeError",
            "AttributeError", "LookupError", "LintRuleError",
        ):
            assert member in doc, (
                f"docstring missing tuple member {member!r}"
            )
        # The LISTED tuple must NOT contain KeyError — its omission is
        # the load-bearing R23 correction; a future re-insertion would
        # silently weaken the catch-tuple pin to dead coverage. The
        # *explanatory* prose may mention KeyError (it explains WHY
        # KeyError is omitted), so we check the verbatim tuple
        # listing rather than the whole docstring.
        assert (
            "(SystemExit, ValueError, TypeError, "
            "AttributeError, LookupError, LintRuleError)"
        ) in doc, (
            "LintRuleError docstring must list the catch tuple verbatim "
            "(6 items, no KeyError). A re-insertion of KeyError or any "
            "wording drift trips this pin."
        )
        assert "AC-06" in doc


# ---------------------------------------------------------------------------
# LintProfile.from_pack — derive a profile from a rule pack module.
# ---------------------------------------------------------------------------


class _FakeSpec:
    """Minimal stand-in for LintRuleSpec — only the fields from_pack reads."""

    def __init__(self, rule_id: str, profiles: tuple[str, ...]) -> None:
        self.rule_id = rule_id
        self.profiles = profiles


class _FakeFn:
    """Stand-in for an @lint_rule-decorated fn — exposes _lint_spec."""

    def __init__(self, rule_id: str, profiles: tuple[str, ...]) -> None:
        self._lint_spec = _FakeSpec(rule_id, profiles)


class _FakePack:
    """Stand-in for a rule pack module — exposes RULES."""

    def __init__(self, *fns: _FakeFn) -> None:
        self.RULES: tuple[Any, ...] = fns


class TestLintProfileFromPack:
    """Exercise the module.RULES walking + profile-membership filter."""

    def test_from_pack_returns_matching_rule_ids(self) -> None:
        """Rules whose ``profiles`` includes the name are selected."""
        pack = _FakePack(
            _FakeFn("naming/snake-case-fields", ("default",)),
            _FakeFn("naming/upper-camel-messages", ("default", "strict")),
            _FakeFn("enum/zero-default-required", ("strict",)),
        )
        profile = LintProfile.from_pack(pack, "default")  # type: ignore[arg-type]
        assert profile.name == "default"
        assert profile.rule_ids == frozenset(
            {"naming/snake-case-fields", "naming/upper-camel-messages"}
        )

    def test_from_pack_strict_profile_picks_different_rules(self) -> None:
        """Filtering on a different profile_name yields a different set."""
        pack = _FakePack(
            _FakeFn("naming/snake-case-fields", ("default",)),
            _FakeFn("enum/zero-default-required", ("strict",)),
        )
        profile = LintProfile.from_pack(pack, "strict")  # type: ignore[arg-type]
        assert profile.rule_ids == frozenset({"enum/zero-default-required"})

    def test_from_pack_unknown_profile_returns_empty_rule_ids(self) -> None:
        """No matching profile → empty rule_ids (matches R12 explicit-empty)."""
        pack = _FakePack(_FakeFn("x/y", ("default",)))
        profile = LintProfile.from_pack(pack, "nonexistent")  # type: ignore[arg-type]
        assert profile.name == "nonexistent"
        assert profile.rule_ids == frozenset()

    def test_from_pack_module_without_rules_attr_returns_empty(self) -> None:
        """``getattr(..., "RULES", ())`` fallback yields an empty profile."""

        class _NoRules:
            pass

        profile = LintProfile.from_pack(_NoRules(), "default")  # type: ignore[arg-type]
        assert profile.rule_ids == frozenset()

    def test_from_pack_empty_rules_tuple_returns_empty(self) -> None:
        """An empty ``RULES`` tuple produces an empty profile."""
        pack = _FakePack()
        profile = LintProfile.from_pack(pack, "default")  # type: ignore[arg-type]
        assert profile.rule_ids == frozenset()

    def test_from_pack_undecorated_fn_raises_typeerror(self) -> None:
        """A RULES entry without _lint_spec raises TypeError, not AttributeError.

        Mirrors LintEngine.load_rule_pack's contract exactly so callers
        can catch one TypeError for either entry point. Updated as part
        of the ce:review #5 convergence on getattr-with-guard.
        """

        def undecorated_fn(_ctx: Any) -> None:
            pass

        class _BadPack:
            __name__ = "_bad_pack"
            RULES = (undecorated_fn,)

        with pytest.raises(TypeError, match="not @lint_rule-decorated"):
            LintProfile.from_pack(_BadPack(), "default")  # type: ignore[arg-type]


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
