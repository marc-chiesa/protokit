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

    The checker carries the library default
    ``CompatibilityLevel.STRICT`` profile (surface every finding)
    and all 18 built-in rules. Tests can mutate ``level``, call
    ``register_field_rule`` / ``register_message_rule`` /
    ``load_rule_pack``, or invoke ``ignore`` before running
    ``check()``. Each test gets its own instance so registrations
    don't leak across tests.

    .. note::

        The ``schema_checker`` fixture defaults to ``STRICT`` while
        :func:`schema_policy` defaults to ``CONSUMER_SAFE``. The
        difference mirrors the underlying classes — ``SchemaChecker``
        is the engine and surfaces everything by default, while
        ``CompatibilityPolicy`` matches the CLI-facing default. If
        a test depends on which findings come back, set ``level``
        explicitly rather than relying on the fixture default.

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

    See :func:`schema_checker` for a note on the intentional
    default-level difference between the two fixtures.

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
    every surviving ``Finding``, error diagnostic, or (unless
    suppressed) warning diagnostic. Tool-level failures — any
    ``Diagnostic`` at ``level="error"`` — ALWAYS fail the
    assertion regardless of ``allow_warnings``: a crashed plugin
    means the report may be incomplete, and silently passing
    when a detector broke defeats the point of the test.

    Args:
        report: The ``CompatibilityReport`` returned by a
            ``SchemaChecker.check()`` or
            ``CompatibilityPolicy.check()`` call.
        allow_warnings: When True, ``level="warning"`` diagnostics
            (comparison caveats like ``treat_as_map`` fallbacks)
            don't cause a failure. Error diagnostics are unaffected
            — they always fail. Use sparingly.

    Raises:
        AssertionError: If ``report.findings`` is non-empty, if
            ``report.errors`` is non-empty, or (when
            ``allow_warnings=False``) ``report.warnings`` is
            non-empty.
    """
    if report.findings:
        header = (
            f"{len(report.findings)} compatibility finding(s) "
            f"under {report.level.value}:"
        )
        lines = [header] + [f"  {f}" for f in report.findings]
        raise AssertionError("\n".join(lines))
    if report.errors:
        # Tool-level failures are never suppressible: a crashed
        # plugin may have missed findings it was supposed to
        # surface.
        header = (
            f"{len(report.errors)} error diagnostic(s) during "
            f"compatibility check (a plugin / hook crashed; the "
            f"report may be incomplete):"
        )
        lines = [header] + [f"  {e}" for e in report.errors]
        raise AssertionError("\n".join(lines))
    if not allow_warnings and report.warnings:
        header = (
            f"{len(report.warnings)} warning(s) during compatibility "
            f"check (use allow_warnings=True to suppress):"
        )
        lines = [header] + [f"  {w}" for w in report.warnings]
        raise AssertionError("\n".join(lines))
