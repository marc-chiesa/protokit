"""Cross-formatter parity tests for ``LintRuntimeWarning`` rendering.

D5 U5 R21a contract: every ``LintRuntimeWarning`` category renders
in every machine formatter, regardless of category-specific
behavior. The matrix below pins each (category, formatter)
combination so a future category addition that forgets to update
one formatter trips immediately.

Coverage:

- ``lint_json`` — already rendered runtime_warnings since D3;
  the test pins the pre-U5 contract so a regression there is
  caught by the same matrix.
- ``lint_junit`` — D5 U5 added ``<system-out>`` emission. Each
  runtime_warning becomes one line with ``[{category}]`` prefix.
- ``lint_sarif`` — D5 U5 added ``runs[].properties.runtime_warnings``
  per KTD-1. Each entry carries ``level``, ``message.text``, and
  ``properties.{category, subcategory: "runtime"}``.

``lint_human`` is intentionally NOT in this matrix — its runtime
warnings emit via the CLI-side post-format hook (KTD-6), tested
in ``tests/schema/lint/cli/test_human_stderr_render.py``.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest

from protokit.formatters import FormatterContext
from protokit.formatters._builtin_lint import (
    lint_json,
    lint_junit,
    lint_sarif,
)
from protokit.schema.lint.model import LintReport, LintRuntimeWarning


def _ctx() -> FormatterContext:
    return FormatterContext(subcommand="lint")


def _warning_for_category(category: str) -> LintRuntimeWarning:
    """Construct a representative ``LintRuntimeWarning`` per category.

    Mirrors the engine/CLI emission contract:

    - Engine-emitted (``rule_exception`` / ``unloaded_rule``):
      ``rule_id`` is a non-``None`` string + ``descriptor_path`` is
      populated for ``rule_exception``.
    - CLI-emitted (``min_severity_relaxed`` / ``all_files_excluded``):
      ``rule_id`` is ``None``.
    """
    if category == "rule_exception":
        return LintRuntimeWarning(
            category="rule_exception",
            rule_id="naming/snake-case-fields",
            message="ValueError: synthetic rule failure",
            exception_type="ValueError",
            descriptor_path="acme.User.bad_field",
        )
    if category == "unloaded_rule":
        return LintRuntimeWarning(
            category="unloaded_rule",
            rule_id="missing/never-registered",
            message="rule pack 'missing.pack' could not be loaded",
        )
    if category == "min_severity_relaxed":
        return LintRuntimeWarning(
            category="min_severity_relaxed",
            rule_id=None,
            message=(
                "--min-severity=info relaxes profile floor from "
                "warning to info"
            ),
        )
    if category == "all_files_excluded":
        return LintRuntimeWarning(
            category="all_files_excluded",
            rule_id=None,
            message=(
                "all 3 input file(s) excluded by --exclude patterns: "
                "**/*"
            ),
        )
    raise AssertionError(f"unrecognized category for test: {category}")


_CATEGORIES: tuple[str, ...] = (
    "rule_exception",
    "unloaded_rule",
    "min_severity_relaxed",
    "all_files_excluded",
)


# ---------------------------------------------------------------------------
# lint_json — already rendered warnings since D3; regression matrix
# ---------------------------------------------------------------------------


class TestLintJsonRuntimeWarningParity:
    """Every category renders in ``lint_json.runtime_warnings`` with
    every field populated according to category semantics. The
    BREAKING-rule_id contract (CLI categories produce ``None``) is
    pinned per category so a silent rule_id widening regression
    surfaces here.
    """

    @pytest.mark.parametrize("category", _CATEGORIES)
    def test_category_renders_with_correct_fields(
        self, category: str,
    ) -> None:
        warning = _warning_for_category(category)
        report = LintReport(runtime_warnings=(warning,))
        payload = json.loads(lint_json(report, _ctx()))
        assert len(payload["runtime_warnings"]) == 1
        entry = payload["runtime_warnings"][0]
        assert entry["category"] == category
        assert entry["message"] == warning.message
        if category in ("min_severity_relaxed", "all_files_excluded"):
            assert entry["rule_id"] is None
        else:
            assert isinstance(entry["rule_id"], str)
            assert entry["rule_id"] == warning.rule_id

    def test_empty_runtime_warnings_emits_empty_array(self) -> None:
        report = LintReport()
        payload = json.loads(lint_json(report, _ctx()))
        assert payload["runtime_warnings"] == []
        assert payload["summary"]["runtime_warning_count"] == 0


# ---------------------------------------------------------------------------
# lint_junit — D5 U5 new system-out emission
# ---------------------------------------------------------------------------


class TestLintJunitRuntimeWarningSystemOut:
    """Each runtime_warning becomes one line in the testsuite's
    ``<system-out>`` body with shape ``[{category}] {message}``.
    Compile-diagnostic warnings share the same ``<system-out>``
    element (JUnit XSD permits only one).
    """

    @pytest.mark.parametrize("category", _CATEGORIES)
    def test_category_renders_in_system_out(self, category: str) -> None:
        warning = _warning_for_category(category)
        report = LintReport(runtime_warnings=(warning,))
        out = lint_junit(report, _ctx())
        root = ET.fromstring(out)
        system_out = root.find("system-out")
        assert system_out is not None, out
        assert system_out.text is not None
        # ``[{category}]`` leading token distinguishes runtime
        # warnings from compile diagnostics (which lead with
        # ``{level} [{category}]:``).
        assert f"[{category}]" in system_out.text
        assert warning.message in system_out.text

    def test_empty_runtime_warnings_emits_empty_system_out_body(
        self,
    ) -> None:
        report = LintReport()
        out = lint_junit(report, _ctx())
        root = ET.fromstring(out)
        # The ``<system-out>`` element is seeded by ``make_testsuite``
        # to satisfy the JUnit XSD even on empty suites, but its text
        # body stays empty when there are no warnings / diagnostics
        # to render. ``ET.Element.text`` is ``None`` for self-closed
        # / empty-content elements after parse.
        system_out = root.find("system-out")
        assert system_out is not None
        assert not (system_out.text or ""), out

    def test_multiple_categories_emit_independent_lines(self) -> None:
        warnings = tuple(_warning_for_category(c) for c in _CATEGORIES)
        report = LintReport(runtime_warnings=warnings)
        out = lint_junit(report, _ctx())
        root = ET.fromstring(out)
        system_out = root.find("system-out")
        assert system_out is not None
        text = system_out.text or ""
        # One line per category, all distinguishable by leading token.
        for c in _CATEGORIES:
            assert f"[{c}]" in text, (c, text)
        # And every message body survives.
        for w in warnings:
            assert w.message in text


# ---------------------------------------------------------------------------
# lint_sarif — D5 U5 new runs[].properties.runtime_warnings (KTD-1)
# ---------------------------------------------------------------------------


class TestLintSarifRuntimeWarningProperties:
    """Per KTD-1, runtime warnings ride in
    ``runs[].properties.runtime_warnings``. Each entry shape::

        {
            "level": "warning",
            "message": {"text": "..."},
            "properties": {
                "category": "<category>",
                "subcategory": "runtime",
            },
        }

    ``descriptor.id`` is intentionally absent (KTD-1);
    categorization travels via ``properties.category``.
    """

    @pytest.mark.parametrize("category", _CATEGORIES)
    def test_category_renders_in_runs_properties(
        self, category: str,
    ) -> None:
        warning = _warning_for_category(category)
        report = LintReport(runtime_warnings=(warning,))
        doc = json.loads(lint_sarif(report, _ctx()))
        run = doc["runs"][0]
        assert "properties" in run, doc
        rw = run["properties"]["runtime_warnings"]
        assert len(rw) == 1
        entry = rw[0]
        assert entry["level"] == "warning"
        assert entry["message"]["text"] == warning.message
        assert entry["properties"]["category"] == category
        assert entry["properties"]["subcategory"] == "runtime"
        # KTD-1: no descriptor.id, even at the top of the entry.
        assert "ruleId" not in entry
        assert "descriptor" not in entry

    def test_empty_runtime_warnings_omits_properties_block(self) -> None:
        report = LintReport()
        doc = json.loads(lint_sarif(report, _ctx()))
        run = doc["runs"][0]
        assert "properties" not in run, run

    def test_runtime_warnings_distinct_from_tool_execution_notifications(
        self,
    ) -> None:
        """``invocations[0].toolExecutionNotifications`` stays
        compile-stage only; runtime warnings DO NOT bleed into it.
        The two channels are intentionally separate (KTD-1) so SARIF
        consumers can filter ``properties.subcategory == "runtime"``
        without scanning notifications.
        """
        from protokit.schema.compile import LintCompileDiagnostic
        diag = LintCompileDiagnostic(
            level="warning",
            message="protoxy unavailable, falling back to protoc",
            category="protoxy_fallback",
        )
        warning = _warning_for_category("rule_exception")
        report = LintReport(
            diagnostics=(diag,),
            runtime_warnings=(warning,),
        )
        doc = json.loads(lint_sarif(report, _ctx()))
        run = doc["runs"][0]
        # Compile diagnostic lives in toolExecutionNotifications.
        notifications = run["invocations"][0]["toolExecutionNotifications"]
        assert len(notifications) == 1
        assert notifications[0]["message"]["text"] == diag.message
        # Runtime warning lives in runs[].properties.runtime_warnings.
        rw = run["properties"]["runtime_warnings"]
        assert len(rw) == 1
        assert rw[0]["properties"]["category"] == "rule_exception"
        # And the runtime warning's message has NOT leaked into the
        # notifications channel.
        notification_texts = [n["message"]["text"] for n in notifications]
        assert warning.message not in notification_texts
