"""Engine integration tests for ``source_info_descriptors`` injection (D6b U2 / R6b).

Pins the cross-layer behavior that U1 (R6a) + U2 (R6b) compose into:

1. ``compile_protos_to_result(include_source_info=True)`` returns a
   ``CompileResult`` with a non-None ``source_info_descriptors`` mapping.
2. ``LintEngine.run`` snapshots that mapping into
   ``self._current_source_info_descriptors`` after the reentrancy guard.
3. The 5 R6 ElementKind context builders (``_build_field_ctx``,
   ``_build_enum_value_ctx``, ``_build_method_ctx``, ``_build_message_ctx``,
   ``_build_enum_ctx``) thread that snapshot into the corresponding
   ``LintContext.source_info_descriptors`` attribute.
4. The 3 untouched contexts (``FileLintContext``, ``ServiceLintContext``,
   ``OneofLintContext``) do NOT carry the attribute — the YAGNI boundary.
5. The ``finally`` block clears the engine instance state — no leakage
   across consecutive ``run()`` calls.

Stub rules per ElementKind capture ``ctx.source_info_descriptors`` (or
``getattr(ctx, ..., _MISSING)`` for the YAGNI boundary check) into
module-level lists so assertions can inspect end-to-end results.

These tests use real backends (no monkeypatching) so the integration is
exercised through the actual compile → engine wire-up path. The fixture
mirrors the inline ``_PROTO_WITH_COMMENTS`` shape from
``tests/schema/lint/test_compile_include_source_info.py`` (U1) to keep
the surface uniform.
"""

from __future__ import annotations

import types
from pathlib import Path
from typing import Any

import pytest

from protokit.schema.compile import compile_protos_to_result
from protokit.schema.lint.decorator import lint_rule
from protokit.schema.lint.engine import LintEngine
from protokit.schema.lint.model import (
    ElementKind,
    LintProfile,
    LintSeverity,
)

# Fixture proto — covers every ElementKind so a single compile populates
# all 8 dispatch paths in the engine.
_PROTO = """\
syntax = "proto3";
package demo;

// Leading comment on Msg.
message Msg {
    // Leading comment on f.
    string f = 1;
    oneof one {
        int32 a = 2;
        int32 b = 3;
    }
}

// Leading comment on E.
enum E {
    E_DEFAULT = 0;
    E_ONE = 1;
}

// Leading comment on S.
service S {
    rpc R (Msg) returns (Msg);
}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MISSING = object()
"""Sentinel for ``getattr(ctx, "source_info_descriptors", _MISSING)``
checks on the 3 untouched contexts."""


def _make_pack(name: str, fns: tuple[Any, ...]) -> types.ModuleType:
    """Construct a throwaway module with __name__=name and RULES=fns."""
    mod = types.ModuleType(name)
    mod.RULES = fns
    return mod


def _compile_with_opt_in(tmp_path: Path) -> Any:
    """Compile the fixture with ``include_source_info=True``."""
    p = tmp_path / "demo.proto"
    p.write_text(_PROTO)
    return compile_protos_to_result([p], include_source_info=True)


def _compile_without_opt_in(tmp_path: Path) -> Any:
    """Compile the fixture without opt-in (default ``include_source_info=False``)."""
    p = tmp_path / "demo.proto"
    p.write_text(_PROTO)
    return compile_protos_to_result([p])


def _make_capture_rule(rule_id: str, element: ElementKind, captured: list[Any]) -> Any:
    """Build a stub rule that captures ``ctx.source_info_descriptors`` per invocation.

    Returns a rule callable decorated under ``profiles=("default",)`` so
    a stock ``LintProfile`` registers it. ``captured`` is the module-level
    list each invocation appends to.
    """

    @lint_rule(
        rule_id=rule_id,
        severity=LintSeverity.INFO,
        profiles=("default",),
        element=element,
        message_template="captured " + rule_id,
    )
    def rule(ctx: Any) -> None:
        captured.append(
            getattr(ctx, "source_info_descriptors", _MISSING)
        )

    rule.__name__ = f"rule_{rule_id.replace('/', '_').replace('-', '_')}"
    return rule


def _default_profile_for(rule_ids: tuple[str, ...]) -> LintProfile:
    """A minimal ``LintProfile`` selecting the given rule_ids at INFO threshold."""
    return LintProfile(
        name="default",
        rule_ids=frozenset(rule_ids),
        min_severity=LintSeverity.INFO,
        rule_severity_overrides={},
    )


# ---------------------------------------------------------------------------
# Per-ElementKind injection — 5 R6 contexts receive the mapping
# ---------------------------------------------------------------------------


class TestFiveR6ContextsReceiveSourceInfoDescriptorsWhenOptIn:
    """Each of the 5 R6 contexts sees the non-None mapping when caller opts in."""

    @pytest.mark.parametrize(
        ("element", "rule_id"),
        [
            (ElementKind.FIELD, "stub/field"),
            (ElementKind.ENUM_VALUE, "stub/enum-value"),
            (ElementKind.METHOD, "stub/method"),
            (ElementKind.MESSAGE, "stub/message"),
            (ElementKind.ENUM, "stub/enum"),
        ],
    )
    def test_context_carries_mapping_when_opt_in(
        self, element: ElementKind, rule_id: str, tmp_path: Path,
    ) -> None:
        captured: list[Any] = []
        rule = _make_capture_rule(rule_id, element, captured)
        engine = LintEngine()
        engine.load_rule_pack(_make_pack(f"pack_{element.value}", (rule,)))

        result = _compile_with_opt_in(tmp_path)
        engine.run(result, profile=_default_profile_for((rule_id,)))

        assert captured, f"stub rule for {element.value} was never invoked"
        # Every captured value must be the SAME mapping the caller opted into —
        # not None, not a sentinel, not a different object.
        for value in captured:
            assert value is not _MISSING, (
                f"{element.value} context is missing source_info_descriptors"
            )
            assert value is not None, (
                f"{element.value} context received None despite opt-in"
            )
            # Identity check — the engine forwarded the exact mapping
            # produced by ``compile_protos_to_result``.
            assert value is result.source_info_descriptors


class TestFiveR6ContextsReceiveNoneWhenNoOptIn:
    """Each of the 5 R6 contexts sees ``None`` when caller does NOT opt in."""

    @pytest.mark.parametrize(
        ("element", "rule_id"),
        [
            (ElementKind.FIELD, "stub/field"),
            (ElementKind.ENUM_VALUE, "stub/enum-value"),
            (ElementKind.METHOD, "stub/method"),
            (ElementKind.MESSAGE, "stub/message"),
            (ElementKind.ENUM, "stub/enum"),
        ],
    )
    def test_context_carries_none_without_opt_in(
        self, element: ElementKind, rule_id: str, tmp_path: Path,
    ) -> None:
        captured: list[Any] = []
        rule = _make_capture_rule(rule_id, element, captured)
        engine = LintEngine()
        engine.load_rule_pack(_make_pack(f"pack_{element.value}", (rule,)))

        result = _compile_without_opt_in(tmp_path)
        engine.run(result, profile=_default_profile_for((rule_id,)))

        assert captured, f"stub rule for {element.value} was never invoked"
        for value in captured:
            assert value is not _MISSING, (
                f"{element.value} context is missing source_info_descriptors"
            )
            assert value is None, (
                f"{element.value} context received non-None without opt-in"
            )


# ---------------------------------------------------------------------------
# YAGNI boundary — the 3 untouched contexts MUST NOT carry the attribute
# ---------------------------------------------------------------------------


class TestThreeUntouchedContextsLackSourceInfoDescriptors:
    """``FileLintContext``, ``ServiceLintContext``, ``OneofLintContext`` lack the field.

    Pins the K-2 / Scope Boundaries decision: comment-aware rules dispatch
    only through the 5 R6 ElementKinds. Adding the field to the other 3
    would be premature surface widening. A regression that quietly added
    it would surface here.
    """

    @pytest.mark.parametrize(
        ("element", "rule_id"),
        [
            (ElementKind.FILE, "stub/file"),
            (ElementKind.SERVICE, "stub/service"),
            (ElementKind.ONEOF, "stub/oneof"),
        ],
    )
    def test_untouched_context_has_no_attribute(
        self, element: ElementKind, rule_id: str, tmp_path: Path,
    ) -> None:
        captured: list[Any] = []
        rule = _make_capture_rule(rule_id, element, captured)
        engine = LintEngine()
        engine.load_rule_pack(_make_pack(f"pack_{element.value}", (rule,)))

        result = _compile_with_opt_in(tmp_path)
        engine.run(result, profile=_default_profile_for((rule_id,)))

        assert captured, f"stub rule for {element.value} was never invoked"
        for value in captured:
            assert value is _MISSING, (
                f"YAGNI boundary leaked: {element.value} context now carries "
                f"source_info_descriptors (got {value!r})"
            )


# ---------------------------------------------------------------------------
# Engine instance-state lifecycle
# ---------------------------------------------------------------------------


class TestEngineInstanceStateClearsAfterRun:
    """``self._current_source_info_descriptors`` is ``None`` after ``run()`` returns."""

    def test_state_clears_on_normal_completion(self, tmp_path: Path) -> None:
        captured: list[Any] = []
        rule = _make_capture_rule("stub/field", ElementKind.FIELD, captured)
        engine = LintEngine()
        engine.load_rule_pack(_make_pack("pack_clear_normal", (rule,)))

        result = _compile_with_opt_in(tmp_path)
        engine.run(result, profile=_default_profile_for(("stub/field",)))

        # State must be cleared after normal completion.
        assert engine._current_source_info_descriptors is None
        # Sanity: also confirm the run actually populated it during execution.
        assert captured, "stub rule was never invoked"
        assert captured[0] is not None


class TestEngineInstanceStateClearsOnException:
    """The ``finally`` block clears state when a rule body raises."""

    def test_state_clears_on_unrecoverable_exception(self, tmp_path: Path) -> None:
        @lint_rule(
            rule_id="stub/raises",
            severity=LintSeverity.ERROR,
            profiles=("default",),
            element=ElementKind.FIELD,
            message_template="never seen",
        )
        def raising_rule(ctx: Any) -> None:
            # KeyboardInterrupt is outside the engine's narrow catch tuple
            # (``_RULE_EXCEPTION_TUPLE``), so it propagates out of ``run()``.
            raise KeyboardInterrupt("synthetic abort")

        engine = LintEngine()
        engine.load_rule_pack(_make_pack("pack_clear_exc", (raising_rule,)))
        result = _compile_with_opt_in(tmp_path)

        with pytest.raises(KeyboardInterrupt, match="synthetic abort"):
            engine.run(result, profile=_default_profile_for(("stub/raises",)))

        # finally-block must still have cleared the state.
        assert engine._current_source_info_descriptors is None
        # Profile cleanup also still holds — pinning the existing invariant
        # alongside the new one.
        assert engine._current_profile is None


class TestStateDoesNotLeakAcrossConsecutiveRuns:
    """A second ``run()`` with no opt-in must NOT see the prior run's mapping."""

    def test_second_run_starts_clean(self, tmp_path: Path) -> None:
        captured: list[Any] = []
        rule = _make_capture_rule("stub/field", ElementKind.FIELD, captured)
        engine = LintEngine()
        engine.load_rule_pack(_make_pack("pack_no_leak", (rule,)))

        # First run: opt in.
        with_opt_in = _compile_with_opt_in(tmp_path)
        engine.run(with_opt_in, profile=_default_profile_for(("stub/field",)))
        first_run_captured = list(captured)
        captured.clear()

        # Second run: no opt-in.
        without_opt_in = _compile_without_opt_in(tmp_path)
        engine.run(without_opt_in, profile=_default_profile_for(("stub/field",)))

        # First run saw the mapping.
        assert all(v is not None for v in first_run_captured)
        # Second run saw None — no leakage from the first run.
        assert captured, "stub rule was never invoked on second run"
        assert all(v is None for v in captured)


# ---------------------------------------------------------------------------
# Reentrancy guard
# ---------------------------------------------------------------------------


class TestReentrancyGuardStillFiresWithBothFields:
    """A rule calling ``engine.run()`` recursively triggers the existing guard.

    The guard checks ``self._current_profile is not None``; the new
    ``_current_source_info_descriptors`` field is set AFTER the guard (per
    K-1), so the guard catches reentrancy before either field can be
    corrupted. This test pins both fields being non-None mid-walk.
    """

    def test_recursive_run_raises_runtimeerror(self, tmp_path: Path) -> None:
        engine = LintEngine()
        # Capture the engine state observed inside the rule, to prove both
        # fields are non-None when the guard would fire.
        observed: dict[str, Any] = {}

        @lint_rule(
            rule_id="stub/reentrant",
            severity=LintSeverity.INFO,
            profiles=("default",),
            element=ElementKind.FIELD,
            message_template="reentrant",
        )
        def reentrant_rule(ctx: Any) -> None:
            observed["profile"] = engine._current_profile
            observed["sld"] = engine._current_source_info_descriptors
            # Recurse — should hit the reentrancy guard.
            engine.run(ctx_compile_result, profile=ctx_profile)

        engine.load_rule_pack(_make_pack("pack_reentrant", (reentrant_rule,)))
        ctx_compile_result = _compile_with_opt_in(tmp_path)
        ctx_profile = _default_profile_for(("stub/reentrant",))

        with pytest.raises(RuntimeError, match="not reentrant"):
            engine.run(ctx_compile_result, profile=ctx_profile)

        # Both fields were non-None at guard-trigger time.
        assert observed["profile"] is not None
        assert observed["sld"] is not None
        # And both are cleared after the outer run's finally block runs.
        assert engine._current_profile is None
        assert engine._current_source_info_descriptors is None
