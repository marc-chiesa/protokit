"""pytest fixtures and assertion helpers for schema compatibility tests.

Parallels ``protokit.message.pytest_plugin`` but targets the
schema checker instead of the runtime differ. Provides:

- A ``schema_checker`` fixture that returns a fresh
  :class:`protokit.schema.checker.SchemaChecker` instance — use
  in tests that want to register rules or tweak the level
  per-call.
- A ``schema_policy`` fixture that returns a fresh
  :class:`protokit.schema.profiles.CompatibilityPolicy` — use
  when a bundled policy is the unit under test.
- An :func:`assert_compatible` helper that fails the test with a
  rich message listing every surviving finding (and, optionally,
  every warning) when a ``CompatibilityReport`` is not clean.

Usage — add to your project's ``conftest.py``:

    from protokit.schema.pytest_plugin import (
        schema_checker,
        schema_policy,
        assert_compatible,
    )

Or register via ``pyproject.toml`` plugin list::

    [tool.pytest.ini_options]
    plugins = ["protokit.schema.pytest_plugin"]

Example test::

    def test_user_schema_is_consumer_safe(schema_checker, old_pool, new_pool):
        report = schema_checker.check(old_pool, "acme.User", new_pool, "acme.User")
        assert_compatible(report)

    def test_cross_type_rename(schema_policy, old_pool, new_pool):
        report = schema_policy.check(
            old_pool, "acme.UserV1", new_pool, "acme.UserV2",
        )
        assert_compatible(report)
"""

from __future__ import annotations

import pytest

from protokit.schema.checker import SchemaChecker
from protokit.schema.model import CompatibilityReport
from protokit.schema.profiles import CompatibilityPolicy


@pytest.fixture
def schema_checker() -> SchemaChecker:
    """Fresh :class:`SchemaChecker` for a single test.

    The checker carries the default ``CompatibilityLevel.STRICT``
    profile and all 17 built-in rules. Tests can mutate ``level``,
    call ``register_field_rule`` / ``register_message_rule`` /
    ``load_rule_pack``, or invoke ``ignore`` before running
    ``check()``. Each test gets its own instance so registrations
    don't leak across tests.

    Returns:
        A new ``SchemaChecker`` with default configuration.
    """
    return SchemaChecker()


@pytest.fixture
def schema_policy() -> CompatibilityPolicy:
    """Fresh :class:`CompatibilityPolicy` with library defaults.

    Matches the CLI defaults: ``CONSUMER_SAFE`` profile, no
    custom rules, no ignore paths. Tests that want to exercise a
    specific bundled policy should construct their own
    ``CompatibilityPolicy`` rather than relying on this fixture,
    which is primarily a convenience for the default-path case.

    Returns:
        A new ``CompatibilityPolicy`` with default configuration.
    """
    return CompatibilityPolicy()


def assert_compatible(
    report: CompatibilityReport,
    *,
    allow_warnings: bool = False,
) -> None:
    """Assert a :class:`CompatibilityReport` is free of findings.

    Raises ``AssertionError`` with a multi-line message listing
    every surviving ``Finding`` when the report is not clean. When
    ``allow_warnings`` is False (default), any ``Warning`` in the
    report also triggers a failure — matching the CLI's
    fail-closed behavior where plugin exceptions or other
    unresolved findings force a non-zero exit.

    Args:
        report: The ``CompatibilityReport`` returned by a
            ``SchemaChecker.check()`` or
            ``CompatibilityPolicy.check()`` call.
        allow_warnings: When True, warnings don't cause a
            failure. Use sparingly — a warning typically means
            the report is incomplete (a rule plugin raised
            mid-check).

    Raises:
        AssertionError: If ``report.findings`` is non-empty, or
            (when ``allow_warnings=False``) ``report.warnings`` is
            non-empty. The message lists every finding/warning.
    """
    if report.findings:
        header = (
            f"{len(report.findings)} compatibility finding(s) "
            f"under {report.level.value}:"
        )
        lines = [header] + [f"  {f}" for f in report.findings]
        raise AssertionError("\n".join(lines))
    if not allow_warnings and report.warnings:
        header = (
            f"{len(report.warnings)} warning(s) during compatibility "
            f"check (use allow_warnings=True to suppress):"
        )
        lines = [header] + [f"  {w}" for w in report.warnings]
        raise AssertionError("\n".join(lines))
