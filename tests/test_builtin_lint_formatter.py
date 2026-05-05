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

import pytest

from protokit.formatters import (
    FormatterContext,
    FormatterKind,
    clear_user_formatters,
    get_formatter,
)
from protokit.formatters._builtin_lint import lint_human
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
