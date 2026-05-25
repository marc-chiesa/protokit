"""Tests for ``protokit.formatters._builtin_lint`` — D3 human formatter.

Exercises ``lint_human`` against synthetic ``LintReport``
inputs. Covers happy paths (single + multi finding), edge cases
(empty report, missing spec, multi-kind template), and
defensive paths (malformed template, missing param key).

Cold-import: this test module imports ``_builtin_lint`` directly
to exercise its rendering. The CI cold-import gate (extended in
Unit 5 of the D3 plan) verifies that ``import protokit.schema``
does NOT transitively load this module — that gate runs in
``.github/workflows/ci.yml``, not here.
"""

from __future__ import annotations

import importlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import jsonschema
import pytest
import xmlschema

from protokit.formatters import (
    FormatterContext,
    FormatterKind,
    clear_user_formatters,
    get_formatter,
)
from protokit.formatters._builtin_lint import (
    lint_human,
    lint_json,
    lint_junit,
    lint_sarif,
)
from protokit.schema.lint.model import (
    ElementKind,
    FieldLocation,
    FileLocation,
    LintFinding,
    LintReport,
    LintRuleSpec,
    LintSeverity,
    MessageLocation,
)


@pytest.fixture(autouse=True)
def _clear_user_packs() -> None:
    """Wipe user formatters around every test; built-ins persist.

    The ``human`` lint formatter registered at module import
    survives because its registration goes through
    ``_register_builtin``, which adds the name to
    ``_BUILTIN_NAMES``. ``clear_user_formatters`` only removes
    entries NOT in the built-in set.
    """
    clear_user_formatters()
    yield
    clear_user_formatters()


def _make_spec(
    rule_id: str = "naming/snake-case-fields",
    template: str | dict[str, str] = "Field {name!r} is not snake_case (AIP-122)",
) -> LintRuleSpec:
    """Build a LintRuleSpec for testing.

    Mirrors the canary at ``src/protokit/schema/lint/rules/naming.py``.
    Severity is dual-shape with template — pass a dict template +
    dict severity for multi-kind tests.
    """
    if isinstance(template, dict):
        severity: LintSeverity | dict[str, LintSeverity] = {
            kind: LintSeverity.WARNING for kind in template
        }
    else:
        severity = LintSeverity.WARNING
    return LintRuleSpec(
        rule_id=rule_id,
        severity=severity,
        profiles=("default",),
        element=ElementKind.FIELD,
        message_template=template,
    )


def _make_finding(
    rule_id: str = "naming/snake-case-fields",
    name: str = "BadField",
    violation_kind: str | None = None,
) -> LintFinding:
    return LintFinding(
        rule_id=rule_id,
        severity=LintSeverity.WARNING,
        location=FieldLocation(
            file="acme/user.proto",
            message="acme.User",
            field=name,
        ),
        violation_kind=violation_kind or rule_id,
        params={"name": name},
    )


class TestRegistryRegistration:
    def test_human_registered_under_lint_report_kind(self) -> None:
        # Simply importing _builtin_lint at module top should have
        # registered the human formatter. get_formatter returns the
        # callable on success; raises KeyError on miss.
        fn = get_formatter("human", FormatterKind.LINT_REPORT)
        # Verify it's the same callable we exported
        assert fn is lint_human

    def test_re_import_is_idempotent(self) -> None:
        # _register_builtin is idempotent under reload; reloading
        # _builtin_lint should NOT raise FormatterError. After reload,
        # the registry holds the freshly-imported lint_human (not
        # the stale module-level reference from this test file).
        import sys

        import protokit.formatters._builtin_lint as bl

        importlib.reload(bl)
        # Still registered after the reload
        fn = get_formatter("human", FormatterKind.LINT_REPORT)
        # Identity check: the registered fn is the post-reload function
        # in sys.modules, NOT the stale top-level import in this test
        # module's namespace.
        post_reload_fn = sys.modules[bl.__name__].lint_human
        assert fn is post_reload_fn, (
            "After reload, registry should hold the new lint_human "
            "from sys.modules, not a stale reference"
        )


class TestRenderHumanEmpty:
    def test_empty_report_renders_empty_string(self) -> None:
        report = LintReport()
        ctx = FormatterContext(subcommand="lint")
        assert lint_human(report, ctx) == ""

    def test_real_lint_compile_diagnostic_renders(self) -> None:
        # Pin the contract against the actual LintCompileDiagnostic
        # type. lint_human accesses .category and .message directly
        # (no getattr fallbacks) — any future shape change to D2's
        # locked type surfaces as a static / runtime error rather
        # than being silently masked by defensive duck-typing.
        from protokit.schema.compile import LintCompileDiagnostic

        diag = LintCompileDiagnostic(
            category="protoc_subprocess",
            level="error",
            message="protoc exited 1",
            command=("protoc", "x.proto"),
            exit_code=1,
            stderr="syntax error",
            exception_type=None,
        )
        report = LintReport(diagnostics=(diag,))
        out = lint_human(report, FormatterContext(subcommand="lint"))
        assert "diagnostic[protoc_subprocess]" in out
        assert "protoc exited 1" in out


class TestDiagnosticOrdering:
    def test_diagnostics_render_before_findings(self) -> None:
        # The formatter docstring documents that compile diagnostics
        # render BEFORE findings — D4 machine formatters reuse this
        # ordering as a stable contract. A swapped for-loop refactor
        # would not be caught by isolated diagnostic-only or
        # findings-only tests.
        from protokit.schema.compile import LintCompileDiagnostic

        diag = LintCompileDiagnostic(
            category="protoc_subprocess",
            level="warning",
            message="protoc warning",
        )
        spec = _make_spec()
        finding = _make_finding(name="BadField")
        report = LintReport(
            diagnostics=(diag,),
            findings=(finding,),
            specs={"naming/snake-case-fields": spec},
        )
        out = lint_human(report, FormatterContext(subcommand="lint"))
        diag_pos = out.index("diagnostic[")
        finding_pos = out.index("WARNING ")
        assert diag_pos < finding_pos, (
            f"Diagnostics must render before findings; got diag at "
            f"{diag_pos}, finding at {finding_pos}"
        )


class TestRenderHumanFindings:
    def test_single_finding_with_spec(self) -> None:
        spec = _make_spec()
        finding = _make_finding(name="BadField")
        report = LintReport(
            findings=(finding,),
            specs={"naming/snake-case-fields": spec},
        )
        out = lint_human(report, FormatterContext(subcommand="lint"))

        assert "WARNING" in out
        assert "acme/user.proto" in out
        assert "[naming/snake-case-fields]" in out
        assert "BadField" in out
        # message_template is interpolated with params
        assert "is not snake_case" in out

    def test_multiple_findings_one_per_line(self) -> None:
        spec = _make_spec()
        f1 = _make_finding(name="BadField")
        f2 = _make_finding(name="AnotherBad")
        report = LintReport(
            findings=(f1, f2),
            specs={"naming/snake-case-fields": spec},
        )
        out = lint_human(report, FormatterContext(subcommand="lint"))
        lines = out.splitlines()
        assert len(lines) == 2
        assert "BadField" in lines[0]
        assert "AnotherBad" in lines[1]

    def test_severity_label_is_uppercase_name(self) -> None:
        spec = _make_spec()
        finding = LintFinding(
            rule_id="naming/snake-case-fields",
            severity=LintSeverity.ERROR,
            location=FileLocation(file="acme/user.proto"),
            violation_kind="naming/snake-case-fields",
            params={"name": "BadField"},
        )
        report = LintReport(
            findings=(finding,),
            specs={"naming/snake-case-fields": spec},
        )
        out = lint_human(report, FormatterContext(subcommand="lint"))
        assert out.startswith("ERROR ")

    def test_finding_without_spec_falls_back_to_rule_id(self) -> None:
        # Spec missing from report.specs (e.g., engine populated
        # specs incompletely or the finding came from a rule
        # unloaded between run() and render). Formatter should
        # NOT crash; it should render the rule_id as the message.
        finding = _make_finding(name="BadField")
        report = LintReport(findings=(finding,), specs={})
        out = lint_human(report, FormatterContext(subcommand="lint"))
        # No template available, so message falls back to rule_id
        assert "naming/snake-case-fields" in out
        # Severity + location still render
        assert "WARNING" in out
        assert "acme/user.proto" in out


class TestRenderMessageEdgeCases:
    def test_multi_kind_template_dict_lookup(self) -> None:
        spec = _make_spec(
            rule_id="multi/kind-rule",
            template={
                "kind-a": "Found kind-a violation: {name}",
                "kind-b": "Found kind-b violation: {name}",
            },
        )
        f_a = _make_finding(
            rule_id="multi/kind-rule",
            name="X",
            violation_kind="kind-a",
        )
        f_b = _make_finding(
            rule_id="multi/kind-rule",
            name="Y",
            violation_kind="kind-b",
        )
        report = LintReport(
            findings=(f_a, f_b),
            specs={"multi/kind-rule": spec},
        )
        out = lint_human(report, FormatterContext(subcommand="lint"))
        assert "Found kind-a violation: X" in out
        assert "Found kind-b violation: Y" in out

    def test_multi_kind_with_unknown_violation_kind(self) -> None:
        # Defensive fall-through: rule author emits a violation_kind
        # not declared in the template dict. Formatter falls back to
        # rule_id rather than crashing.
        spec = _make_spec(
            rule_id="multi/kind-rule",
            template={"declared-kind": "Found {name}"},
        )
        finding = _make_finding(
            rule_id="multi/kind-rule",
            name="X",
            violation_kind="undeclared-kind",
        )
        report = LintReport(
            findings=(finding,),
            specs={"multi/kind-rule": spec},
        )
        out = lint_human(report, FormatterContext(subcommand="lint"))
        # The rule_id always appears in the [rule_id] segment, so
        # the meaningful assertion is on the message body: the
        # declared-kind template's interpolated string ("Found X")
        # MUST NOT appear, since the violation_kind didn't match
        # and the fallback path was taken instead.
        assert "Found X" not in out, (
            "Multi-kind fallback failed: declared-kind template was "
            "interpolated even though violation_kind='undeclared-kind' "
            "doesn't match"
        )
        # The line should still terminate with the rule_id (as the
        # message body, since the dict.get fallback returns rule_id).
        line = out.strip()
        assert line.endswith("multi/kind-rule"), (
            f"Expected line to end with rule_id (fallback rendering), "
            f"got: {line!r}"
        )

    def test_template_missing_param_key_does_not_crash(self) -> None:
        # Defensive: rule author's template references {missing}
        # but the finding's params don't include "missing".
        # Formatter recovers by surfacing rule_id + raw params.
        # Exception kind: KeyError.
        spec = _make_spec(
            rule_id="bad/template",
            template="References {missing} which is not in params",
        )
        finding = LintFinding(
            rule_id="bad/template",
            severity=LintSeverity.WARNING,
            location=FieldLocation(
                file="x.proto", message="X", field="f",
            ),
            violation_kind="bad/template",
            params={"name": "value"},  # no "missing" key
        )
        report = LintReport(
            findings=(finding,),
            specs={"bad/template": spec},
        )
        # Should not raise; falls back gracefully
        out = lint_human(report, FormatterContext(subcommand="lint"))
        assert "bad/template" in out

    def test_template_positional_placeholder_does_not_crash(self) -> None:
        # str.format with {0} positional + kwargs raises IndexError.
        # The defensive catch tuple includes IndexError.
        spec = _make_spec(
            rule_id="bad/positional",
            template="Positional {0} placeholder",
        )
        finding = LintFinding(
            rule_id="bad/positional",
            severity=LintSeverity.WARNING,
            location=FieldLocation(
                file="x.proto", message="X", field="f",
            ),
            violation_kind="bad/positional",
            params={"name": "value"},  # no positional values
        )
        report = LintReport(
            findings=(finding,),
            specs={"bad/positional": spec},
        )
        out = lint_human(report, FormatterContext(subcommand="lint"))
        assert "bad/positional" in out
        # Template was NOT interpolated (would have raised IndexError)
        assert "Positional value placeholder" not in out

    def test_template_invalid_format_spec_does_not_crash(self) -> None:
        # str.format with invalid format spec raises ValueError.
        # E.g., "{x:invalid}" or unmatched braces "{{{name}".
        spec = _make_spec(
            rule_id="bad/spec",
            template="Bad spec {name:Z}",  # Z is not a valid type
        )
        finding = LintFinding(
            rule_id="bad/spec",
            severity=LintSeverity.WARNING,
            location=FieldLocation(
                file="x.proto", message="X", field="f",
            ),
            violation_kind="bad/spec",
            params={"name": "value"},
        )
        report = LintReport(
            findings=(finding,),
            specs={"bad/spec": spec},
        )
        out = lint_human(report, FormatterContext(subcommand="lint"))
        assert "bad/spec" in out

    def test_template_attribute_traversal_does_not_crash(self) -> None:
        # str.format with dotted access on a value lacking the
        # attribute raises AttributeError. E.g., "{name.bad}"
        # against a string value.
        spec = _make_spec(
            rule_id="bad/attribute",
            template="Bad attr {name.nonexistent}",
        )
        finding = LintFinding(
            rule_id="bad/attribute",
            severity=LintSeverity.WARNING,
            location=FieldLocation(
                file="x.proto", message="X", field="f",
            ),
            violation_kind="bad/attribute",
            params={"name": "value"},  # str has no .nonexistent
        )
        report = LintReport(
            findings=(finding,),
            specs={"bad/attribute": spec},
        )
        # Should not raise; the AttributeError is in the catch tuple
        out = lint_human(report, FormatterContext(subcommand="lint"))
        assert "bad/attribute" in out

    def test_template_subscript_type_mismatch_does_not_crash(self) -> None:
        # str.format with subscript on an unsubscriptable value
        # raises TypeError. E.g., "{n[0]}" against an int.
        spec = _make_spec(
            rule_id="bad/subscript",
            template="Bad sub {n[0]}",
        )
        finding = LintFinding(
            rule_id="bad/subscript",
            severity=LintSeverity.WARNING,
            location=FieldLocation(
                file="x.proto", message="X", field="f",
            ),
            violation_kind="bad/subscript",
            params={"n": 42},  # int is not subscriptable
        )
        report = LintReport(
            findings=(finding,),
            specs={"bad/subscript": spec},
        )
        # Should not raise; the TypeError is in the catch tuple
        out = lint_human(report, FormatterContext(subcommand="lint"))
        assert "bad/subscript" in out

    def test_empty_template_falls_back_to_rule_id(self) -> None:
        spec = _make_spec(rule_id="empty/template", template="")
        finding = _make_finding(rule_id="empty/template", name="X")
        report = LintReport(
            findings=(finding,),
            specs={"empty/template": spec},
        )
        out = lint_human(report, FormatterContext(subcommand="lint"))
        assert "empty/template" in out


class TestRenderHumanLocationVariants:
    def test_message_location(self) -> None:
        spec = _make_spec(
            rule_id="msg/rule",
            template="Bad message {name!r}",
        )
        finding = LintFinding(
            rule_id="msg/rule",
            severity=LintSeverity.WARNING,
            location=MessageLocation(file="x.proto", message="X.Y"),
            violation_kind="msg/rule",
            params={"name": "X.Y"},
        )
        report = LintReport(
            findings=(finding,),
            specs={"msg/rule": spec},
        )
        out = lint_human(report, FormatterContext(subcommand="lint"))
        # Location stringification per LintLocation.__str__
        assert "x.proto:X.Y" in out

    def test_file_location(self) -> None:
        spec = _make_spec(
            rule_id="file/rule",
            template="File-level violation",
        )
        finding = LintFinding(
            rule_id="file/rule",
            severity=LintSeverity.INFO,
            location=FileLocation(file="x.proto"),
            violation_kind="file/rule",
            params={},
        )
        report = LintReport(
            findings=(finding,),
            specs={"file/rule": spec},
        )
        out = lint_human(report, FormatterContext(subcommand="lint"))
        assert out.startswith("INFO ")
        assert "x.proto" in out
        assert "File-level violation" in out


class TestLintJson:
    """``lint_json`` machine formatter — stable JSON schema."""

    def _ctx(self) -> FormatterContext:
        return FormatterContext(subcommand="lint")

    def test_empty_report_produces_well_formed_json(self) -> None:
        report = LintReport()
        out = lint_json(report, self._ctx())
        payload = json.loads(out)
        assert payload["findings"] == []
        assert payload["filtered_count"] == 0
        assert payload["runtime_warnings"] == []
        assert payload["diagnostics"] == []
        assert payload["summary"]["total"] == 0
        assert payload["summary"]["errors"] == 0
        assert payload["summary"]["warnings"] == 0
        assert payload["summary"]["info"] == 0

    def test_single_finding_renders_to_findings_list(self) -> None:
        spec = _make_spec()
        finding = _make_finding()
        report = LintReport(
            findings=(finding,),
            specs={"naming/snake-case-fields": spec},
        )
        payload = json.loads(lint_json(report, self._ctx()))
        assert len(payload["findings"]) == 1
        entry = payload["findings"][0]
        assert entry["rule_id"] == "naming/snake-case-fields"
        assert entry["severity"] == "warning"
        assert "acme/user.proto" in entry["location"]
        assert "BadField" in entry["message"]
        # Structured location fields (added in U4b ce:review follow-up
        # to give agents file/kind without parsing the location string).
        assert entry["location_file"] == "acme/user.proto"
        assert entry["location_kind"] == "field"

    def test_location_kind_per_location_variant(self) -> None:
        """Each LintLocation variant maps to a stable lowercase kind."""
        spec = _make_spec(rule_id="x/y", template="msg")
        cases = [
            (FieldLocation(file="a.proto", message="M", field="f"), "field"),
            (MessageLocation(file="a.proto", message="M"), "message"),
            (FileLocation(file="a.proto"), "file"),
        ]
        for loc, expected_kind in cases:
            finding = LintFinding(
                rule_id="x/y", severity=LintSeverity.WARNING,
                location=loc, violation_kind="x/y", params={},
            )
            report = LintReport(findings=(finding,), specs={"x/y": spec})
            payload = json.loads(lint_json(report, self._ctx()))
            assert payload["findings"][0]["location_kind"] == expected_kind
            assert payload["findings"][0]["location_file"] == "a.proto"

    def test_per_finding_params_serialized(self) -> None:
        """``params`` dict surfaces verbatim in each finding payload.

        D6c U2 ce:review #8 + agent-native: structured-output consumers
        (agents, IDEs, CI tools) read ``params`` directly to discriminate
        rule arms or extract semantic fields without parsing rendered
        message prose. Verifies the key is emitted, contains the source
        values (post-format), and tolerates heterogeneous value types
        like bool (for R8b's ``packageless_present`` discriminator).
        """
        spec = _make_spec(rule_id="x/multi", template="msg")
        finding = LintFinding(
            rule_id="x/multi",
            severity=LintSeverity.ERROR,
            location=FileLocation(file="a.proto"),
            violation_kind="x/multi",
            params={
                "directory": "pkg",
                "packages": "acme.bar,acme.foo",
                "packageless_present": False,
            },
        )
        report = LintReport(findings=(finding,), specs={"x/multi": spec})
        payload = json.loads(lint_json(report, self._ctx()))
        entry = payload["findings"][0]
        assert entry["params"] == {
            "directory": "pkg",
            "packages": "acme.bar,acme.foo",
            "packageless_present": False,
        }

    def test_non_json_serializable_param_does_not_suppress_output(
        self,
    ) -> None:
        """A finding whose params contains a non-JSON-serializable
        value (here: a Path) renders via default=str rather than
        raising TypeError and suppressing all findings."""
        from pathlib import Path as _Path
        spec = _make_spec(template="Got {bad}")
        finding = LintFinding(
            rule_id="naming/snake-case-fields",
            severity=LintSeverity.WARNING,
            location=FieldLocation(
                file="x.proto", message="X", field="Bad",
            ),
            violation_kind="naming/snake-case-fields",
            params={"bad": _Path("/tmp/example")},
        )
        report = LintReport(
            findings=(finding,),
            specs={"naming/snake-case-fields": spec},
        )
        # Should not raise — default=str handles the Path.
        payload = json.loads(lint_json(report, self._ctx()))
        assert len(payload["findings"]) == 1
        # Path renders via str() in the message interpolation; payload
        # is well-formed JSON.
        assert "/tmp/example" in payload["findings"][0]["message"]

    def test_summary_counts_per_severity(self) -> None:
        spec = _make_spec()
        f_warn = _make_finding(name="WarnField")
        f_err = LintFinding(
            rule_id="naming/snake-case-fields",
            severity=LintSeverity.ERROR,
            location=FieldLocation(
                file="x.proto", message="X", field="ErrField",
            ),
            violation_kind="naming/snake-case-fields",
            params={"name": "ErrField"},
        )
        f_info = LintFinding(
            rule_id="naming/snake-case-fields",
            severity=LintSeverity.INFO,
            location=FieldLocation(
                file="x.proto", message="X", field="InfoField",
            ),
            violation_kind="naming/snake-case-fields",
            params={"name": "InfoField"},
        )
        report = LintReport(
            findings=(f_warn, f_err, f_info),
            specs={"naming/snake-case-fields": spec},
        )
        payload = json.loads(lint_json(report, self._ctx()))
        assert payload["summary"]["errors"] == 1
        assert payload["summary"]["warnings"] == 1
        assert payload["summary"]["info"] == 1
        assert payload["summary"]["total"] == 3

    def test_filtered_count_surfaces_in_payload_and_summary(self) -> None:
        report = LintReport(filtered_count=5)
        payload = json.loads(lint_json(report, self._ctx()))
        assert payload["filtered_count"] == 5
        assert payload["summary"]["filtered_count"] == 5

    def test_diagnostics_in_payload(self) -> None:
        from protokit.schema.compile import LintCompileDiagnostic
        diag = LintCompileDiagnostic(
            level="warning", message="protoxy fallback", category="protoxy_fallback",
        )
        report = LintReport(diagnostics=(diag,))
        payload = json.loads(lint_json(report, self._ctx()))
        assert len(payload["diagnostics"]) == 1
        assert payload["diagnostics"][0]["level"] == "warning"
        assert payload["diagnostics"][0]["category"] == "protoxy_fallback"

    def test_output_is_pretty_printed_with_2_space_indent(self) -> None:
        """Stable contract: lint_json uses indent=2."""
        out = lint_json(LintReport(), self._ctx())
        # First-level field starts with 2 spaces in pretty-printed JSON.
        assert "\n  " in out

    def test_runtime_warnings_serialized_with_per_warning_fields(self) -> None:
        """A non-empty LintRuntimeWarning round-trips through lint_json
        with all five fields (category, rule_id, message, exception_type,
        descriptor_path)."""
        from protokit.schema.lint.model import LintRuntimeWarning
        warning = LintRuntimeWarning(
            category="rule_exception",
            rule_id="naming/snake-case-fields",
            message="ValueError: synthetic",
            exception_type="ValueError",
            descriptor_path="acme.User.bad_field",
        )
        report = LintReport(runtime_warnings=(warning,))
        payload = json.loads(lint_json(report, self._ctx()))
        assert len(payload["runtime_warnings"]) == 1
        entry = payload["runtime_warnings"][0]
        assert entry["category"] == "rule_exception"
        assert entry["rule_id"] == "naming/snake-case-fields"
        assert entry["message"] == "ValueError: synthetic"
        assert entry["exception_type"] == "ValueError"
        assert entry["descriptor_path"] == "acme.User.bad_field"
        # Summary block surfaces the count.
        assert payload["summary"]["runtime_warning_count"] == 1

    def test_lint_json_registered_under_lint_report_kind(self) -> None:
        # Use sys.modules to dodge the stale-reference trap from
        # test_re_import_is_idempotent (which reloads _builtin_lint
        # and rebinds the registry to fresh function objects).
        import sys

        importlib.import_module("protokit.formatters._builtin_lint")
        bl = sys.modules["protokit.formatters._builtin_lint"]
        fn = get_formatter("json", FormatterKind.LINT_REPORT)
        assert fn is bl.lint_json


class TestBumpContractDocstring:
    """Presence ratchet for the bump-contract block above `_LINT_JSON_SCHEMA_VERSION`.

    The block at ``src/protokit/formatters/_builtin_lint.py:227-270``
    is a ``#:`` Sphinx-style comment, NOT a Python ``__doc__``
    attribute — so the test reads source via ``inspect.getsource``
    (Pattern B per [[presence-ratchet-test-pattern-for-prose-substrings-2026-05-14]]).

    This is NOT a stability contract over wording; this asserts
    that the load-bearing substrings remain present. If a future
    docstring rewrite changes the wording while preserving the
    contract, update ``ratchet_substrings`` after confirming
    semantic equivalence. If the contract itself is dropped
    (e.g., the closed-vs-open distinction is removed), restore
    the substring or capture the new contract in a fresh learning
    + cross-ref per
    [[closed-literal-discriminator-bump-trigger-2026-05-17]].

    Substring 2 (``"additions DO bump the"``) is deliberately the
    5-word fragment rather than the full ``"additions DO bump the
    version"`` clause: the latter spans lines 262-263 via ``#:``
    continuation prefix in the source comment block, so
    ``inspect.getsource`` returns it interrupted by
    ``\\n#:         ``; the 5-word fragment is the longest
    contiguous on-line substring that preserves the positive
    directional contract for closed Literals.
    """

    def test_bump_contract_docstring_preserves_closed_literal_distinction(
        self,
    ) -> None:
        import inspect

        from protokit.formatters import _builtin_lint

        source = inspect.getsource(_builtin_lint)
        ratchet_substrings = (
            "Closed Literal discriminators",
            "additions DO bump the",
            "Open severity-string ladders",
            '"severities_unloaded_rule"',
            '"custom_annotation_extension_unresolved"',
            '"extension_unresolved"',
            '"contradictory_disable_config"',
            '"unknown_rule_id"',
        )
        for substring in ratchet_substrings:
            assert substring in source, (
                f"Bump-contract substring {substring!r} missing from "
                f"src/protokit/formatters/_builtin_lint.py (bump-"
                f"contract block above `_LINT_JSON_SCHEMA_VERSION`). "
                f"Either restore the substring OR update "
                f"`ratchet_substrings` in this test after confirming "
                f"the closed-Literal-discriminator-vs-open-severity-"
                f"ladder contract is still preserved semantically. "
                f"See [[closed-literal-discriminator-bump-trigger-"
                f"2026-05-17]] for the load-bearing contract."
            )


_JUNIT_XSD = Path(__file__).parent / "fixtures" / "junit-xml" / "JUnit.xsd"


@pytest.fixture(scope="module")
def junit_validator() -> xmlschema.XMLSchema:
    """Vendored Apache Ant JUnit xsd loaded once per module."""
    return xmlschema.XMLSchema(str(_JUNIT_XSD))


def _validate_junit(validator: xmlschema.XMLSchema, xml: str) -> None:
    """Validate an XML string against the vendored xsd."""
    ET.fromstring(xml)  # well-formedness first
    validator.validate(xml)


class TestLintJunit:
    """``lint_junit`` machine formatter — JUnit XSD validation."""

    def _ctx(self) -> FormatterContext:
        return FormatterContext(subcommand="lint")

    def test_empty_report_emits_clean_passing_suite(
        self, junit_validator: xmlschema.XMLSchema,
    ) -> None:
        report = LintReport()
        out = lint_junit(report, self._ctx())
        _validate_junit(junit_validator, out)
        assert "protokit-lint" in out
        assert 'classname="lint"' in out
        assert 'name="clean"' in out
        assert 'failures="0"' in out

    def test_single_finding_emits_failure_under_testcase(
        self, junit_validator: xmlschema.XMLSchema,
    ) -> None:
        spec = _make_spec()
        finding = _make_finding()
        report = LintReport(
            findings=(finding,),
            specs={"naming/snake-case-fields": spec},
        )
        out = lint_junit(report, self._ctx())
        _validate_junit(junit_validator, out)
        assert 'tests="1"' in out
        assert 'failures="1"' in out
        assert 'classname="naming/snake-case-fields"' in out
        assert "<failure" in out
        assert "BadField" in out

    def test_multiple_findings_aggregate_into_one_suite(
        self, junit_validator: xmlschema.XMLSchema,
    ) -> None:
        spec = _make_spec()
        f1 = _make_finding(name="BadOne")
        f2 = _make_finding(name="BadTwo")
        report = LintReport(
            findings=(f1, f2),
            specs={"naming/snake-case-fields": spec},
        )
        out = lint_junit(report, self._ctx())
        _validate_junit(junit_validator, out)
        assert 'tests="2"' in out
        assert 'failures="2"' in out
        assert "BadOne" in out
        assert "BadTwo" in out

    def test_compile_error_diagnostic_renders_as_error_testcase(
        self, junit_validator: xmlschema.XMLSchema,
    ) -> None:
        from protokit.schema.compile import LintCompileDiagnostic
        diag = LintCompileDiagnostic(
            level="error", message="protoc fail", category="protoc_subprocess",
        )
        report = LintReport(diagnostics=(diag,))
        out = lint_junit(report, self._ctx())
        _validate_junit(junit_validator, out)
        assert 'errors="1"' in out
        assert "<error" in out
        assert "protoc fail" in out

    def test_warning_diagnostics_in_system_out(
        self, junit_validator: xmlschema.XMLSchema,
    ) -> None:
        from protokit.schema.compile import LintCompileDiagnostic
        diag = LintCompileDiagnostic(
            level="warning",
            message="protoxy unavailable, falling back to protoc",
            category="protoxy_fallback",
        )
        report = LintReport(diagnostics=(diag,))
        out = lint_junit(report, self._ctx())
        _validate_junit(junit_validator, out)
        # Non-error diagnostics surface in <system-out>, not as failures.
        assert 'failures="0"' in out
        assert "protoxy_fallback" in out

    def test_lint_junit_registered_under_lint_report_kind(self) -> None:
        import sys

        importlib.import_module("protokit.formatters._builtin_lint")
        bl = sys.modules["protokit.formatters._builtin_lint"]
        fn = get_formatter("junit", FormatterKind.LINT_REPORT)
        assert fn is bl.lint_junit


_SARIF_SCHEMA = Path(__file__).parent / "fixtures" / "sarif" / "sarif-2.1.0.json"


@pytest.fixture(scope="module")
def sarif_validator() -> jsonschema.Draft7Validator:
    """Vendored SARIF 2.1.0 schema loaded once per module."""
    with open(_SARIF_SCHEMA) as f:
        return jsonschema.Draft7Validator(json.load(f))


class TestLintSarif:
    """``lint_sarif`` machine formatter — SARIF 2.1.0 schema validation.

    Critical for the CI-auditability identity bet (KD-5):
    schema-drift bugs in SARIF output cause silent rejection by
    GitHub code scanning, so every shape is gated by the official
    OASIS schema.
    """

    def _ctx(self) -> FormatterContext:
        return FormatterContext(subcommand="lint")

    def test_empty_report_validates_against_sarif_2_1_0(
        self, sarif_validator: jsonschema.Draft7Validator,
    ) -> None:
        out = lint_sarif(LintReport(), self._ctx())
        doc = json.loads(out)
        sarif_validator.validate(doc)
        assert doc["version"] == "2.1.0"
        assert doc["runs"][0]["results"] == []
        assert doc["runs"][0]["tool"]["driver"]["name"] == "protokit"
        assert doc["runs"][0]["invocations"][0]["executionSuccessful"] is True

    def test_single_finding_renders_to_results_array(
        self, sarif_validator: jsonschema.Draft7Validator,
    ) -> None:
        spec = _make_spec()
        finding = _make_finding()
        report = LintReport(
            findings=(finding,),
            specs={"naming/snake-case-fields": spec},
        )
        out = lint_sarif(report, self._ctx())
        doc = json.loads(out)
        sarif_validator.validate(doc)
        results = doc["runs"][0]["results"]
        assert len(results) == 1
        assert results[0]["ruleId"] == "naming/snake-case-fields"
        assert results[0]["level"] == "warning"
        assert "BadField" in results[0]["message"]["text"]

    def test_result_properties_carries_params(
        self, sarif_validator: jsonschema.Draft7Validator,
    ) -> None:
        """SARIF ``result.properties.params`` exposes semantic fields.

        D6c U2 ce:review #8 + agent-native: SARIF consumers reading the
        vendor-extension ``properties`` bag can discriminate rule arms
        (e.g., R8b's ``packageless_present``) without scraping the
        rendered ``message.text``.
        """
        spec = _make_spec(rule_id="x/multi", template="msg")
        finding = LintFinding(
            rule_id="x/multi",
            severity=LintSeverity.ERROR,
            location=FileLocation(file="a.proto"),
            violation_kind="x/multi",
            params={
                "directory": "pkg",
                "packages": "acme.bar,acme.foo",
                "packageless_present": False,
            },
        )
        report = LintReport(findings=(finding,), specs={"x/multi": spec})
        out = lint_sarif(report, self._ctx())
        doc = json.loads(out)
        sarif_validator.validate(doc)
        result = doc["runs"][0]["results"][0]
        assert result["properties"]["params"] == {
            "directory": "pkg",
            "packages": "acme.bar,acme.foo",
            "packageless_present": False,
        }

    def test_severity_levels_map_correctly(
        self, sarif_validator: jsonschema.Draft7Validator,
    ) -> None:
        spec = _make_spec()
        f_err = LintFinding(
            rule_id="naming/snake-case-fields",
            severity=LintSeverity.ERROR,
            location=FieldLocation(
                file="x.proto", message="X", field="ErrField",
            ),
            violation_kind="naming/snake-case-fields",
            params={"name": "ErrField"},
        )
        f_warn = _make_finding(name="WarnField")
        f_info = LintFinding(
            rule_id="naming/snake-case-fields",
            severity=LintSeverity.INFO,
            location=FieldLocation(
                file="x.proto", message="X", field="InfoField",
            ),
            violation_kind="naming/snake-case-fields",
            params={"name": "InfoField"},
        )
        report = LintReport(
            findings=(f_err, f_warn, f_info),
            specs={"naming/snake-case-fields": spec},
        )
        out = lint_sarif(report, self._ctx())
        doc = json.loads(out)
        sarif_validator.validate(doc)
        levels = [r["level"] for r in doc["runs"][0]["results"]]
        # SARIF: ERROR -> "error", WARNING -> "warning", INFO -> "note"
        assert levels == ["error", "warning", "note"]

    def test_rules_catalog_includes_every_fired_rule_id(
        self, sarif_validator: jsonschema.Draft7Validator,
    ) -> None:
        spec = _make_spec()
        finding = _make_finding()
        report = LintReport(
            findings=(finding,),
            specs={"naming/snake-case-fields": spec},
        )
        out = lint_sarif(report, self._ctx())
        doc = json.loads(out)
        sarif_validator.validate(doc)
        rules = doc["runs"][0]["tool"]["driver"]["rules"]
        rule_ids = {r["id"] for r in rules}
        assert "naming/snake-case-fields" in rule_ids

    def test_compile_error_diagnostic_flips_execution_successful(
        self, sarif_validator: jsonschema.Draft7Validator,
    ) -> None:
        from protokit.schema.compile import LintCompileDiagnostic
        diag = LintCompileDiagnostic(
            level="error", message="protoc fail", category="protoc_subprocess",
        )
        report = LintReport(diagnostics=(diag,))
        out = lint_sarif(report, self._ctx())
        doc = json.loads(out)
        sarif_validator.validate(doc)
        invocation = doc["runs"][0]["invocations"][0]
        assert invocation["executionSuccessful"] is False
        notifications = invocation["toolExecutionNotifications"]
        assert len(notifications) == 1
        assert notifications[0]["level"] == "error"

    def test_warning_diagnostic_does_not_flip_execution_successful(
        self, sarif_validator: jsonschema.Draft7Validator,
    ) -> None:
        from protokit.schema.compile import LintCompileDiagnostic
        diag = LintCompileDiagnostic(
            level="warning",
            message="protoxy fallback",
            category="protoxy_fallback",
        )
        report = LintReport(diagnostics=(diag,))
        out = lint_sarif(report, self._ctx())
        doc = json.loads(out)
        sarif_validator.validate(doc)
        invocation = doc["runs"][0]["invocations"][0]
        assert invocation["executionSuccessful"] is True

    def test_multi_kind_dict_template_rule_renders_joined_descriptions(
        self, sarif_validator: jsonschema.Draft7Validator,
    ) -> None:
        """A multi-kind LintRuleSpec (dict template) joins kinds in
        SARIF shortDescription instead of falling through to the
        generic stub."""
        spec = LintRuleSpec(
            rule_id="multi/kind-rule",
            severity={"k1": LintSeverity.WARNING, "k2": LintSeverity.WARNING},
            profiles=("default",),
            element=ElementKind.FIELD,
            message_template={"k1": "First kind text", "k2": "Second kind text"},
        )
        finding = LintFinding(
            rule_id="multi/kind-rule",
            severity=LintSeverity.WARNING,
            location=FieldLocation(file="x.proto", message="X", field="f"),
            violation_kind="k1",
            params={},
        )
        report = LintReport(findings=(finding,), specs={"multi/kind-rule": spec})
        out = lint_sarif(report, self._ctx())
        doc = json.loads(out)
        sarif_validator.validate(doc)
        rules = doc["runs"][0]["tool"]["driver"]["rules"]
        description = rules[0]["shortDescription"]["text"]
        assert "First kind text" in description
        assert "Second kind text" in description

    def test_finding_with_unknown_rule_id_renders_with_generic_stub(
        self, sarif_validator: jsonschema.Draft7Validator,
    ) -> None:
        """A finding whose rule_id is not in report.specs falls back
        to the 'Lint rule: {rule_id}' stub in shortDescription."""
        finding = LintFinding(
            rule_id="orphan/no-spec",
            severity=LintSeverity.WARNING,
            location=FieldLocation(file="x.proto", message="X", field="f"),
            violation_kind="orphan/no-spec",
            params={},
        )
        report = LintReport(findings=(finding,), specs={})
        out = lint_sarif(report, self._ctx())
        doc = json.loads(out)
        sarif_validator.validate(doc)
        rules = doc["runs"][0]["tool"]["driver"]["rules"]
        assert rules[0]["shortDescription"]["text"] == "Lint rule: orphan/no-spec"

    def test_tool_driver_version_field_populated(
        self, sarif_validator: jsonschema.Draft7Validator,
    ) -> None:
        """tool.driver.version is non-empty (real version or 0.0.0
        fallback for uninstalled checkouts)."""
        out = lint_sarif(LintReport(), self._ctx())
        doc = json.loads(out)
        sarif_validator.validate(doc)
        version = doc["runs"][0]["tool"]["driver"]["version"]
        assert isinstance(version, str)
        assert len(version) > 0

    def test_multi_rule_catalog_is_sorted_deterministic(
        self, sarif_validator: jsonschema.Draft7Validator,
    ) -> None:
        """When multiple rules fire, tool.driver.rules entries are
        sorted by rule_id for deterministic SARIF output."""
        spec_a = _make_spec(rule_id="aaa/rule", template="A")
        spec_z = _make_spec(rule_id="zzz/rule", template="Z")
        f_z = LintFinding(
            rule_id="zzz/rule", severity=LintSeverity.WARNING,
            location=FieldLocation(file="x.proto", message="X", field="f"),
            violation_kind="zzz/rule", params={},
        )
        f_a = LintFinding(
            rule_id="aaa/rule", severity=LintSeverity.WARNING,
            location=FieldLocation(file="x.proto", message="X", field="g"),
            violation_kind="aaa/rule", params={},
        )
        report = LintReport(
            findings=(f_z, f_a),  # Reversed insertion order.
            specs={"aaa/rule": spec_a, "zzz/rule": spec_z},
        )
        out = lint_sarif(report, self._ctx())
        doc = json.loads(out)
        sarif_validator.validate(doc)
        rules = doc["runs"][0]["tool"]["driver"]["rules"]
        rule_ids = [r["id"] for r in rules]
        assert rule_ids == sorted(rule_ids)
        assert rule_ids == ["aaa/rule", "zzz/rule"]

    def test_info_level_diagnostic_emits_warning_notification_known_quirk(
        self, sarif_validator: jsonschema.Draft7Validator,
    ) -> None:
        """Documents the current behavior: info-level compile diagnostics
        (e.g. protoxy_fallback) emit SARIF notifications with level
        'warning'. SARIF spec recommends 'note' for informational, but
        the binary error/non-error split here mirrors compat's pattern.
        Pin the current behavior so any future correction is visible.
        """
        from protokit.schema.compile import LintCompileDiagnostic
        diag = LintCompileDiagnostic(
            level="info", message="protoxy fallback", category="protoxy_fallback",
        )
        report = LintReport(diagnostics=(diag,))
        out = lint_sarif(report, self._ctx())
        doc = json.loads(out)
        sarif_validator.validate(doc)
        notifications = doc["runs"][0]["invocations"][0][
            "toolExecutionNotifications"
        ]
        assert len(notifications) == 1
        # Documented quirk: info level → SARIF "warning" not "note".
        # Mirrors compat's _sarif_json.build_run binary error-vs-other
        # split. If/when this is corrected, this assertion flips.
        assert notifications[0]["level"] == "warning"

    def test_lint_sarif_registered_under_lint_report_kind(self) -> None:
        import sys

        importlib.import_module("protokit.formatters._builtin_lint")
        bl = sys.modules["protokit.formatters._builtin_lint"]
        fn = get_formatter("sarif", FormatterKind.LINT_REPORT)
        assert fn is bl.lint_sarif
