"""Unit tests for ``assert_parity`` branches that are dead code today.

The per-family parity tests exercise the strict-equality and the
``protokit_stricter`` exception branches. The ``protokit_looser``
posture and the unknown-posture fallthrough are unreachable until a
future delivery documents the first ``protokit_looser`` divergence
(D6b is the likely candidate via option-aware rules). Pinning the
branches with synthetic findings now means a regression in either
branch surfaces as a test failure rather than waiting for the first
real divergence to expose it.

These tests do not require buf — they call ``assert_parity`` directly
with mocked finding lists. They run under the default ``pytest tests/``
invocation alongside the inventory drift guards.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.parity.conftest import (
    ParityExceptionsMap,
    ParityPosture,
    assert_parity,
)


def _finding(rule_id: str, path: str = "bad.proto", line: int = 5) -> dict[str, Any]:
    """Build a synthetic protokit-shape finding for a rule_id."""
    return {
        "rule_id": rule_id,
        "severity": "error",
        "location_file": path,
        "location_kind": "message",
    }


def _buf_finding(buf_id: str, path: str = "bad.proto", line: int = 5) -> dict[str, Any]:
    """Build a synthetic buf-NDJSON-shape finding."""
    return {
        "type": buf_id,
        "path": path,
        "start_line": line,
    }


class TestProtokitLooserPosture:
    """Pin the protokit_looser branch (lines ~480-491 of conftest)."""

    def test_assertion_passes_when_buf_fires_alone(self) -> None:
        """protokit_looser: buf fires, protokit doesn't → exception accepted."""
        exceptions: ParityExceptionsMap = {
            ("dummy/looser-rule", "bad"): (
                "protokit_looser",  # type: ignore[arg-type] -- Literal narrowing
                "test fixture documenting protokit_looser branch",
            ),
        }
        assert_parity(
            protokit_findings=[],
            buf_findings=[_buf_finding("DUMMY_LOOSER_RULE")],
            protokit_rule_id="dummy/looser-rule",
            buf_rule_id="DUMMY_LOOSER_RULE",
            proto_relpath="bad.proto",
            expected_fires=True,
            parity_exceptions=exceptions,
        )

    def test_assertion_fails_when_protokit_fires_under_looser(self) -> None:
        """protokit_looser: protokit fires unexpectedly → loud failure."""
        exceptions: ParityExceptionsMap = {
            ("dummy/looser-rule", "bad"): (
                "protokit_looser",  # type: ignore[arg-type]
                "test fixture",
            ),
        }
        with pytest.raises(AssertionError, match="protokit_looser"):
            assert_parity(
                protokit_findings=[_finding("dummy/looser-rule")],
                buf_findings=[_buf_finding("DUMMY_LOOSER_RULE")],
                protokit_rule_id="dummy/looser-rule",
                buf_rule_id="DUMMY_LOOSER_RULE",
                proto_relpath="bad.proto",
                expected_fires=True,
                parity_exceptions=exceptions,
            )

    def test_assertion_fails_when_buf_does_not_fire_under_looser(self) -> None:
        """protokit_looser: buf must fire on the divergent fixture."""
        exceptions: ParityExceptionsMap = {
            ("dummy/looser-rule", "bad"): (
                "protokit_looser",  # type: ignore[arg-type]
                "test fixture",
            ),
        }
        with pytest.raises(AssertionError, match="protokit_looser"):
            assert_parity(
                protokit_findings=[],
                buf_findings=[],
                protokit_rule_id="dummy/looser-rule",
                buf_rule_id="DUMMY_LOOSER_RULE",
                proto_relpath="bad.proto",
                expected_fires=True,
                parity_exceptions=exceptions,
            )


class TestProtokitStricterPosture:
    """Smoke-test the protokit_stricter branch with synthetic findings.

    The real `file/syntax-specified` test already exercises this
    branch with a real buf binary; these tests pin the branch's logic
    independently so a refactor that breaks it surfaces in default
    ``pytest tests/`` runs without buf.
    """

    def test_assertion_passes_when_protokit_fires_alone(self) -> None:
        """protokit_stricter: protokit fires, buf doesn't → exception accepted."""
        exceptions: ParityExceptionsMap = {
            ("dummy/stricter-rule", "bad"): (
                "protokit_stricter",  # type: ignore[arg-type]
                "test fixture",
            ),
        }
        assert_parity(
            protokit_findings=[_finding("dummy/stricter-rule")],
            buf_findings=[],
            protokit_rule_id="dummy/stricter-rule",
            buf_rule_id="DUMMY_STRICTER_RULE",
            proto_relpath="bad.proto",
            expected_fires=True,
            parity_exceptions=exceptions,
        )

    def test_assertion_fails_when_buf_fires_under_stricter(self) -> None:
        """protokit_stricter: buf firing means divergence may have resolved."""
        exceptions: ParityExceptionsMap = {
            ("dummy/stricter-rule", "bad"): (
                "protokit_stricter",  # type: ignore[arg-type]
                "test fixture",
            ),
        }
        with pytest.raises(AssertionError, match="protokit_stricter"):
            assert_parity(
                protokit_findings=[_finding("dummy/stricter-rule")],
                buf_findings=[_buf_finding("DUMMY_STRICTER_RULE")],
                protokit_rule_id="dummy/stricter-rule",
                buf_rule_id="DUMMY_STRICTER_RULE",
                proto_relpath="bad.proto",
                expected_fires=True,
                parity_exceptions=exceptions,
            )


class TestStrictEqualityBranches:
    """Pin the happy-path and sad-path strict-equality branches."""

    def test_happy_path_passes_when_neither_fires(self) -> None:
        """No exception entry; expected_fires=False; both empty → pass."""
        assert_parity(
            protokit_findings=[],
            buf_findings=[],
            protokit_rule_id="dummy/rule",
            buf_rule_id="DUMMY_RULE",
            proto_relpath="good.proto",
            expected_fires=False,
            parity_exceptions={},
        )

    def test_sad_path_passes_when_both_fire(self) -> None:
        """No exception entry; expected_fires=True; both fire → pass."""
        assert_parity(
            protokit_findings=[_finding("dummy/rule")],
            buf_findings=[_buf_finding("DUMMY_RULE")],
            protokit_rule_id="dummy/rule",
            buf_rule_id="DUMMY_RULE",
            proto_relpath="bad.proto",
            expected_fires=True,
            parity_exceptions={},
        )

    def test_sad_path_fails_when_only_one_fires(self) -> None:
        """Strict-equality branch: drift between tools → loud failure."""
        with pytest.raises(AssertionError, match="parity sad-path"):
            assert_parity(
                protokit_findings=[_finding("dummy/rule")],
                buf_findings=[],
                protokit_rule_id="dummy/rule",
                buf_rule_id="DUMMY_RULE",
                proto_relpath="bad.proto",
                expected_fires=True,
                parity_exceptions={},
            )

    def test_happy_path_fails_when_either_fires(self) -> None:
        """Strict-equality branch: spurious finding on a clean fixture."""
        with pytest.raises(AssertionError, match="parity happy-path"):
            assert_parity(
                protokit_findings=[_finding("dummy/rule")],
                buf_findings=[],
                protokit_rule_id="dummy/rule",
                buf_rule_id="DUMMY_RULE",
                proto_relpath="good.proto",
                expected_fires=False,
                parity_exceptions={},
            )


class TestUnknownPostureFallthrough:
    """Pin the defensive 'unknown posture' fallthrough at the bottom of
    assert_parity's exception handling. ``_validate_parity_exceptions``
    rejects unknown postures at import time, so the only way to reach
    this branch in practice is by passing a malformed exceptions
    dict directly to ``assert_parity`` — which these tests do
    deliberately."""

    def test_fail_on_unknown_posture_value(self) -> None:
        bad_posture: Any = "protokit_strict"  # typo: missing "er"
        exceptions: ParityExceptionsMap = {
            ("dummy/rule", "bad"): (bad_posture, "test fixture"),
        }
        with pytest.raises(pytest.fail.Exception, match="unknown.*posture"):
            assert_parity(
                protokit_findings=[],
                buf_findings=[],
                protokit_rule_id="dummy/rule",
                buf_rule_id="DUMMY_RULE",
                proto_relpath="bad.proto",
                expected_fires=True,
                parity_exceptions=exceptions,
            )


# Silence "imported but unused" — ParityPosture is exported for type
# narrowing in callers; the import here exercises that it remains
# importable from conftest.
_ = ParityPosture
