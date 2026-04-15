"""Tests for ``protokit.schema.pytest_plugin``.

Uses pytest's ``pytester`` fixture to spawn an isolated test
session that imports the plugin — same pattern as
``tests/test_pytest_plugin.py`` for the differ's plugin.
"""

from __future__ import annotations

import pytest

from google.protobuf import descriptor_pool

from protokit.schema.checker import SchemaChecker
from protokit.schema.model import (
    CompatibilityLevel,
    CompatibilityReport,
    Direction,
    Finding,
    Severity,
)
from protokit.schema.profiles import CompatibilityPolicy
from protokit.schema.pytest_plugin import (
    assert_compatible,
    schema_checker,
    schema_policy,
)
from protokit.message.model import FieldPath, Warning
from tests.schema.helpers import T, build_message


def _compatible_pair() -> tuple[descriptor_pool.DescriptorPool, descriptor_pool.DescriptorPool]:
    old = descriptor_pool.DescriptorPool()
    new = descriptor_pool.DescriptorPool()
    for p in (old, new):
        build_message(p, "t.M", fields=[
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
        ])
    return old, new


def _incompatible_pair() -> tuple[descriptor_pool.DescriptorPool, descriptor_pool.DescriptorPool]:
    old = descriptor_pool.DescriptorPool()
    new = descriptor_pool.DescriptorPool()
    build_message(old, "t.M", fields=[
        {"name": "x", "number": 1, "type": T.TYPE_INT32},
    ])
    build_message(new, "t.M", fields=[])  # field removed
    return old, new


class TestFixtures:
    def test_schema_checker_returns_fresh_instance(self) -> None:
        """Calling the fixture as a plain function returns a new checker."""
        checker_a = schema_checker.__wrapped__()  # unwrap @pytest.fixture
        checker_b = schema_checker.__wrapped__()
        assert isinstance(checker_a, SchemaChecker)
        assert isinstance(checker_b, SchemaChecker)
        assert checker_a is not checker_b

    def test_schema_policy_returns_fresh_instance(self) -> None:
        policy_a = schema_policy.__wrapped__()
        policy_b = schema_policy.__wrapped__()
        assert isinstance(policy_a, CompatibilityPolicy)
        assert isinstance(policy_b, CompatibilityPolicy)
        assert policy_a is not policy_b
        # Library default: CONSUMER_SAFE.
        assert policy_a.base is CompatibilityLevel.CONSUMER_SAFE

    def test_schema_checker_customizable(self) -> None:
        """The fixture-returned checker can be configured per-test."""
        checker = schema_checker.__wrapped__()
        checker.level = CompatibilityLevel.STRICT
        old, new = _incompatible_pair()
        report = checker.check(old, "t.M", new, "t.M")
        assert any(f.rule_id == "field_removed" for f in report.findings)


class TestAssertCompatible:
    def test_compatible_report_does_not_raise(self) -> None:
        old, new = _compatible_pair()
        checker = SchemaChecker()
        report = checker.check(old, "t.M", new, "t.M")
        # Compatible: no findings, no warnings.
        assert_compatible(report)

    def test_incompatible_report_raises_with_findings(self) -> None:
        old, new = _incompatible_pair()
        checker = SchemaChecker()
        report = checker.check(old, "t.M", new, "t.M")
        with pytest.raises(AssertionError) as exc:
            assert_compatible(report)
        msg = str(exc.value)
        assert "compatibility finding" in msg
        assert "field_removed" in msg

    def test_warnings_cause_failure_by_default(self) -> None:
        """Warnings without findings still fail closed."""
        # Hand-craft a report with a warning but no findings.
        report = CompatibilityReport(
            level=CompatibilityLevel.STRICT,
            findings=(),
            warnings=(Warning(path=None, message="plugin crashed"),),
        )
        with pytest.raises(AssertionError) as exc:
            assert_compatible(report)
        assert "warning(s)" in str(exc.value)
        assert "plugin crashed" in str(exc.value)

    def test_allow_warnings_suppresses_warning_failure(self) -> None:
        report = CompatibilityReport(
            level=CompatibilityLevel.STRICT,
            findings=(),
            warnings=(Warning(path=None, message="plugin crashed"),),
        )
        # With allow_warnings=True we accept the report despite warnings.
        assert_compatible(report, allow_warnings=True)

    def test_findings_always_fail_even_with_allow_warnings(self) -> None:
        """``allow_warnings`` only gates warnings — findings still fail."""
        report = CompatibilityReport(
            level=CompatibilityLevel.STRICT,
            findings=(
                Finding(
                    path=FieldPath.parse("x"),
                    rule_id="field_removed",
                    severity=Severity.SEMANTIC,
                    direction=Direction.BACKWARD,
                    message="field x removed",
                ),
            ),
            warnings=(),
        )
        with pytest.raises(AssertionError) as exc:
            assert_compatible(report, allow_warnings=True)
        assert "field_removed" in str(exc.value)

    def test_failure_message_lists_every_finding(self) -> None:
        """All surviving findings are listed in the failure message."""
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        build_message(old, "t.M", fields=[
            {"name": "a", "number": 1, "type": T.TYPE_INT32},
            {"name": "b", "number": 2, "type": T.TYPE_STRING},
        ])
        build_message(new, "t.M", fields=[])  # both removed
        checker = SchemaChecker()
        report = checker.check(old, "t.M", new, "t.M")
        with pytest.raises(AssertionError) as exc:
            assert_compatible(report)
        msg = str(exc.value)
        # Both field_removed findings should be listed.
        assert msg.count("field_removed") == 2
        # Paths appear in the output.
        assert "a" in msg and "b" in msg
