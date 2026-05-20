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
from pathlib import Path

import jsonschema
import pytest
import xmlschema

from protokit.formatters import FormatterContext
from protokit.formatters._builtin_lint import (
    lint_json,
    lint_junit,
    lint_sarif,
)
from protokit.schema.lint.model import LintReport, LintRuntimeWarning
from tests.schema.lint.cli._helpers import (
    LINT_RUNTIME_WARNING_CATEGORIES as _CATEGORIES,
)
from tests.schema.lint.cli._helpers import (
    warning_for_category as _warning_for_category,
)

_JUNIT_XSD = Path(__file__).parent / "fixtures" / "junit-xml" / "JUnit.xsd"
_SARIF_SCHEMA = Path(__file__).parent / "fixtures" / "sarif" / "sarif-2.1.0.json"


@pytest.fixture(scope="module")
def junit_validator() -> xmlschema.XMLSchema:
    """Vendored Apache Ant JUnit xsd loaded once per module."""
    return xmlschema.XMLSchema(str(_JUNIT_XSD))


@pytest.fixture(scope="module")
def sarif_validator() -> jsonschema.Draft7Validator:
    """Vendored SARIF 2.1.0 schema loaded once per module."""
    with open(_SARIF_SCHEMA) as f:
        return jsonschema.Draft7Validator(json.load(f))


def _validate_junit(validator: xmlschema.XMLSchema, xml: str) -> None:
    """Validate an XML string against the vendored xsd."""
    ET.fromstring(xml)  # well-formedness first
    validator.validate(xml)


def _ctx() -> FormatterContext:
    return FormatterContext(subcommand="lint")


# ``_CATEGORIES`` (the canonical five ``LintRuntimeWarning`` category
# strings as of D6b U5) and ``_warning_for_category`` (the
# per-category factory) live in ``tests/schema/lint/cli/_helpers.py``
# so this file and ``tests/schema/lint/cli/test_human_stderr_render.py``
# share a single definition. Adding a 6th category requires editing
# only the shared helper; the parametrized matrix tests in this file
# then fail until every formatter render site is covered.


# ---------------------------------------------------------------------------
# lint_json — already rendered warnings since D3; regression matrix
# ---------------------------------------------------------------------------


class TestLintJsonRuntimeWarningParity:
    """Every category renders in ``lint_json.runtime_warnings`` with
    every field populated according to category semantics. The
    BREAKING-rule_id contract is pinned per category: rule-scoped
    categories (``rule_exception``, ``unloaded_rule``,
    ``severities_unloaded_rule``) carry a populated ``rule_id``,
    while non-rule-scoped CLI-emitted categories
    (``min_severity_relaxed``, ``all_files_excluded``) carry
    ``None``. A silent rule_id widening regression surfaces here.
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

    def test_empty_message_field_still_emits_one_entry(self) -> None:
        """Plan U5 line 645: 'skip-empty would mask bugs'. A warning
        with an empty message field must still produce one
        ``runtime_warnings`` entry; the formatter must not silently
        drop it. Catches a future defensive ``if w.message:`` guard.
        """
        warning = LintRuntimeWarning(
            category="rule_exception",
            rule_id="naming/snake-case-fields",
            message="",
            exception_type="ValueError",
            descriptor_path="acme.User.x",
        )
        report = LintReport(runtime_warnings=(warning,))
        payload = json.loads(lint_json(report, _ctx()))
        assert len(payload["runtime_warnings"]) == 1
        assert payload["runtime_warnings"][0]["message"] == ""


# ---------------------------------------------------------------------------
# lint_junit — D5 U5 new system-out emission
# ---------------------------------------------------------------------------


class TestLintJunitRuntimeWarningSystemOut:
    """Each runtime_warning becomes one line in the testsuite's
    ``<system-out>`` body with shape ``[{category}] {message}``.
    Compile-diagnostic warnings share the same ``<system-out>``
    element (JUnit XSD permits only one).

    Every test in this class validates the rendered XML against the
    vendored Apache Ant JUnit XSD per plan U5 line 651 — well-formedness
    alone (``ET.fromstring``) is not sufficient; schema drift in the
    runtime-warnings body must trip the validator.
    """

    @pytest.mark.parametrize("category", _CATEGORIES)
    def test_category_renders_in_system_out(
        self, category: str, junit_validator: xmlschema.XMLSchema,
    ) -> None:
        warning = _warning_for_category(category)
        report = LintReport(runtime_warnings=(warning,))
        out = lint_junit(report, _ctx())
        _validate_junit(junit_validator, out)
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
        self, junit_validator: xmlschema.XMLSchema,
    ) -> None:
        report = LintReport()
        out = lint_junit(report, _ctx())
        _validate_junit(junit_validator, out)
        root = ET.fromstring(out)
        # The ``<system-out>`` element is seeded by ``make_testsuite``
        # to satisfy the JUnit XSD even on empty suites, but its text
        # body stays empty when there are no warnings / diagnostics
        # to render. ``ET.Element.text`` is ``None`` for self-closed
        # / empty-content elements after parse.
        system_out = root.find("system-out")
        assert system_out is not None
        assert not (system_out.text or ""), out

    def test_multiple_categories_emit_independent_lines(
        self, junit_validator: xmlschema.XMLSchema,
    ) -> None:
        warnings = tuple(_warning_for_category(c) for c in _CATEGORIES)
        report = LintReport(runtime_warnings=warnings)
        out = lint_junit(report, _ctx())
        _validate_junit(junit_validator, out)
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

    def test_empty_message_field_still_emits_one_line(
        self, junit_validator: xmlschema.XMLSchema,
    ) -> None:
        """Plan U5 line 645: 'skip-empty would mask bugs'. A warning
        with an empty message field must still produce one
        ``<system-out>`` line, not be silently dropped. The leading
        ``[{category}]`` token is what callers grep on; an empty
        body is acceptable but the entry must survive.
        """
        warning = LintRuntimeWarning(
            category="rule_exception",
            rule_id="naming/snake-case-fields",
            message="",
            exception_type="ValueError",
            descriptor_path="acme.User.x",
        )
        report = LintReport(runtime_warnings=(warning,))
        out = lint_junit(report, _ctx())
        _validate_junit(junit_validator, out)
        root = ET.fromstring(out)
        system_out = root.find("system-out")
        assert system_out is not None
        text = system_out.text or ""
        assert "[rule_exception]" in text, text

    def test_compile_warning_and_runtime_warning_coexist_in_system_out(
        self, junit_validator: xmlschema.XMLSchema,
    ) -> None:
        """Compile-diagnostic warning lines and runtime-warning lines
        share the single ``<system-out>`` body per JUnit XSD. The
        documented ordering is compile diagnostics first, then runtime
        warnings — pin both presence and ordering so a future refactor
        cannot reverse them silently.
        """
        from protokit.schema.compile import LintCompileDiagnostic
        diag = LintCompileDiagnostic(
            level="warning",
            message="protoxy unavailable, falling back to protoc",
            category="protoxy_fallback",
        )
        rt_warning = _warning_for_category("rule_exception")
        report = LintReport(
            diagnostics=(diag,),
            runtime_warnings=(rt_warning,),
        )
        out = lint_junit(report, _ctx())
        _validate_junit(junit_validator, out)
        root = ET.fromstring(out)
        system_out = root.find("system-out")
        assert system_out is not None
        text = system_out.text or ""
        # Compile diagnostic uses ``{level} [{category}]:`` shape.
        assert "warning [protoxy_fallback]:" in text, text
        # Runtime warning uses ``[{category}] {message}`` shape.
        assert "[rule_exception]" in text, text
        # Compile diagnostic precedes runtime warning.
        compile_idx = text.index("[protoxy_fallback]")
        runtime_idx = text.index("[rule_exception]")
        assert compile_idx < runtime_idx, (compile_idx, runtime_idx, text)


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

    Every test in this class validates the rendered JSON against the
    vendored SARIF 2.1.0 schema per plan U5 line 651. SARIF
    ``propertyBag`` semantics permit non-standard keys, so the
    validator is what catches a shape change that would otherwise
    be silently rejected by GitHub code scanning.
    """

    @pytest.mark.parametrize("category", _CATEGORIES)
    def test_category_renders_in_runs_properties(
        self, category: str,
        sarif_validator: jsonschema.Draft7Validator,
    ) -> None:
        warning = _warning_for_category(category)
        report = LintReport(runtime_warnings=(warning,))
        doc = json.loads(lint_sarif(report, _ctx()))
        sarif_validator.validate(doc)
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

    def test_empty_runtime_warnings_omits_runtime_warnings_key(
        self, sarif_validator: jsonschema.Draft7Validator,
    ) -> None:
        """When the report carries no runtime warnings, the SARIF
        ``runs[].properties.runtime_warnings`` key MUST NOT appear —
        otherwise a clean-report SARIF document would contain an
        empty list that downstream consumers might iterate.

        D6a U9 R9d adds ``lint_schema_version`` to the same
        ``properties`` propertyBag, so the bag itself is now always
        present; the assertion narrows from "no properties block" to
        "no runtime_warnings key inside properties, but lint_schema_version
        is present" so the two SARIF property contracts stay
        independently testable.
        """
        report = LintReport()
        doc = json.loads(lint_sarif(report, _ctx()))
        sarif_validator.validate(doc)
        run = doc["runs"][0]
        assert "properties" in run, doc
        properties = run["properties"]
        assert "runtime_warnings" not in properties, properties
        # Schema version is unconditional (R9d cross-format-enum-string-parity
        # with lint_json).
        assert properties["lint_schema_version"] == "0.4"

    def test_runtime_warnings_and_schema_version_coexist(
        self, sarif_validator: jsonschema.Draft7Validator,
    ) -> None:
        """When the report carries runtime warnings AND R9d's
        ``lint_schema_version`` is emitted, BOTH keys must appear in
        the same ``runs[].properties`` propertyBag.

        Without this assertion, a future conditional that only sets
        ``lint_schema_version`` on empty-warning reports — or a
        wholesale ``run["properties"] = {...}`` reassignment between
        the two writes — would silently clobber one key. Per ce:review
        F9 on commit c7a426b.
        """
        warning = LintRuntimeWarning(
            category="rule_exception",
            rule_id="naming/snake-case-fields",
            message="cosmetic test warning",
            exception_type="ValueError",
            descriptor_path="acme.User.x",
        )
        report = LintReport(runtime_warnings=(warning,))
        doc = json.loads(lint_sarif(report, _ctx()))
        sarif_validator.validate(doc)
        run = doc["runs"][0]
        properties = run["properties"]
        assert "runtime_warnings" in properties, properties
        assert "lint_schema_version" in properties, properties
        assert len(properties["runtime_warnings"]) == 1
        assert properties["lint_schema_version"] == "0.4"

    def test_empty_message_field_still_emits_one_entry(
        self, sarif_validator: jsonschema.Draft7Validator,
    ) -> None:
        """Plan U5 line 645: 'skip-empty would mask bugs'. A warning
        with an empty message must still produce one
        ``runtime_warnings`` entry; ``message.text`` may be empty
        but the entry must survive — and SARIF schema validation
        must still pass on the empty-string text node.
        """
        warning = LintRuntimeWarning(
            category="rule_exception",
            rule_id="naming/snake-case-fields",
            message="",
            exception_type="ValueError",
            descriptor_path="acme.User.x",
        )
        report = LintReport(runtime_warnings=(warning,))
        doc = json.loads(lint_sarif(report, _ctx()))
        sarif_validator.validate(doc)
        rw = doc["runs"][0]["properties"]["runtime_warnings"]
        assert len(rw) == 1
        assert rw[0]["message"]["text"] == ""

    def test_runtime_warnings_distinct_from_tool_execution_notifications(
        self,
        sarif_validator: jsonschema.Draft7Validator,
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
        sarif_validator.validate(doc)
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
