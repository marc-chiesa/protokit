"""Human and machine output agree about whether a run succeeded (U7, R4).

Closes V23 (four human renderers printed a success verdict while the JUnit /
SARIF renderers of the same report reported an error), V24 (a depth-truncated
diff rendered as ``Messages are equal.`` / ``"equal": true``), and V25 (REPORT
hook annotations were dropped by every diff format).

Every renderer asks ``protokit._trust`` before printing a success verdict.
The structural guard that keeps a *new* renderer honest lives in
``tests/meta/test_formatter_trust.py``; this file pins the wording and the
wire shape of the five built-in kinds.
"""

from __future__ import annotations

import dataclasses
import json
import xml.etree.ElementTree as ET

import click
import pytest

# LINT_REPORT formatters register when their module loads, and nothing in
# ``protokit.formatters`` loads it (the lint CLI does).
import protokit.formatters._builtin_lint  # noqa: F401
from protokit.formatters import FormatterContext, FormatterKind, get_formatter
from protokit.message.model import (
    ChangeType,
    Difference,
    DiffResult,
    FieldPath,
)
from protokit.schema.lint.model import LintReport, LintRuntimeWarning
from protokit.schema.model import (
    CommitDiagnostic,
    Direction,
    Finding,
    Severity,
)
from tests._trust_reports import (
    bisect_report,
    compat_report,
    error_diagnostic,
    history_report,
    truncated_diff_result,
    warning_diagnostic,
)


def _render(name: str, kind: FormatterKind, report: object, **ctx: str) -> str:
    fn = get_formatter(name, kind)
    out = fn(report, FormatterContext(subcommand="test", **ctx))  # type: ignore[arg-type]
    return click.unstyle(out)


def _finding() -> Finding:
    return Finding(
        path=FieldPath.parse("user.email"), rule_id="field_removed",
        severity=Severity.SEMANTIC, direction=Direction.BACKWARD,
        message="field present in old schema, absent in new",
    )


# ---------------------------------------------------------------------------
# DIFF — V24
# ---------------------------------------------------------------------------


class TestDiffTruncation:
    def test_human_prints_incomplete_not_equal(self) -> None:
        out = _render("human", FormatterKind.DIFF, truncated_diff_result())
        assert "Messages are equal." not in out
        assert "INCOMPLETE" in out
        assert "inner" in out  # names where the comparison stopped

    def test_json_reports_not_equal_and_says_why(self) -> None:
        payload = json.loads(_render("json", FormatterKind.DIFF, truncated_diff_result()))
        assert payload["equal"] is False
        assert payload["complete"] is False
        assert payload["truncated_paths"] == ["inner"]

    def test_json_complete_equal_result(self) -> None:
        """Adjacent behavior: a genuinely equal, complete result is unchanged."""
        payload = json.loads(_render("json", FormatterKind.DIFF, DiffResult(differences=())))
        assert payload["equal"] is True
        assert payload["complete"] is True
        assert payload["truncated_paths"] == []

    def test_json_schema_version_bumped_for_the_new_keys(self) -> None:
        payload = json.loads(_render("json", FormatterKind.DIFF, DiffResult(differences=())))
        assert payload["schema_version"] == "0.2"

    def test_json_error_without_differences_is_not_equal(self) -> None:
        """R4: the human line says "not trustworthy"; ``equal`` must not say true."""
        result = DiffResult(differences=(), diagnostics=(error_diagnostic(),))
        payload = json.loads(_render("json", FormatterKind.DIFF, result))
        assert payload["equal"] is False
        assert payload["complete"] is True

    def test_human_truncated_with_differences_still_lists_them(self) -> None:
        """Adjacent behavior: a found difference is definitive even when truncated."""
        diff = Difference(
            path=FieldPath.parse("name"), change_type=ChangeType.MODIFIED,
            left_value="A", right_value="B",
        )
        result = dataclasses.replace(truncated_diff_result(), differences=(diff,))
        out = _render("human", FormatterKind.DIFF, result)
        assert "Found 1 difference" in out
        assert "truncated" in out


# ---------------------------------------------------------------------------
# DIFF — V25
# ---------------------------------------------------------------------------


class TestDiffAnnotations:
    @staticmethod
    def _annotated() -> DiffResult:
        return DiffResult(differences=(Difference(
            path=FieldPath.parse("price"), change_type=ChangeType.MODIFIED,
            left_value=1.0, right_value=1.5,
            annotations=("rounded by policy", "see RFC-7"),
        ),))

    def test_human_shows_annotations(self) -> None:
        out = _render("human", FormatterKind.DIFF, self._annotated())
        assert "rounded by policy" in out
        assert "see RFC-7" in out

    def test_json_carries_annotations(self) -> None:
        payload = json.loads(_render("json", FormatterKind.DIFF, self._annotated()))
        assert payload["differences"][0]["annotations"] == [
            "rounded by policy", "see RFC-7",
        ]

    def test_json_unannotated_entry_carries_an_empty_list(self) -> None:
        """Uniform entry shape, like the four value keys."""
        result = DiffResult(differences=(Difference(
            path=FieldPath.parse("price"), change_type=ChangeType.MODIFIED,
            left_value=1, right_value=2,
        ),))
        payload = json.loads(_render("json", FormatterKind.DIFF, result))
        assert payload["differences"][0]["annotations"] == []

    def test_junit_failure_body_shows_annotations(self) -> None:
        root = ET.fromstring(_render("junit", FormatterKind.DIFF, self._annotated()))
        failure = root.find("./testcase/failure")
        assert failure is not None and failure.text is not None
        assert "rounded by policy" in failure.text


# ---------------------------------------------------------------------------
# COMPAT / HISTORY / BISECT — V23
# ---------------------------------------------------------------------------


class TestCompatTrust:
    def test_zero_findings_plus_an_error_is_not_compatible(self) -> None:
        out = _render(
            "human", FormatterKind.COMPAT, compat_report(error_diagnostic()),
        )
        assert "COMPATIBLE" not in out  # also excludes INCOMPATIBLE
        assert "INCOMPLETE" in out
        assert "plugin crashed" in out

    def test_findings_plus_an_error_stays_incompatible_and_shows_the_reason(
        self,
    ) -> None:
        """Reasons render unconditionally, not only on the success path."""
        out = _render("human", FormatterKind.COMPAT, compat_report(
            error_diagnostic(), findings=(_finding(),),
        ))
        assert "INCOMPATIBLE" in out
        assert "plugin crashed" in out

    def test_a_warning_still_prints_compatible(self) -> None:
        """Adjacent behavior: warnings do not cost the verdict."""
        report = compat_report(warning_diagnostic())
        out = _render("human", FormatterKind.COMPAT, report)
        assert out.rstrip().endswith("COMPATIBLE")
        assert "INCOMPATIBLE" not in out


class TestHistoryTrust:
    def test_an_entry_carrying_an_error_is_not_ok(self) -> None:
        out = _render(
            "human", FormatterKind.COMPAT_HISTORY,
            history_report(entry_diags=(error_diagnostic(),)),
        )
        assert "cccccccccccc OK" not in out
        assert "cccccccccccc INCOMPLETE" in out
        assert "plugin crashed" in out

    def test_a_clean_entry_is_still_ok(self) -> None:
        out = _render("human", FormatterKind.COMPAT_HISTORY, history_report())
        assert out == "cccccccccccc OK (0 finding(s))"

    def test_an_aggregate_only_error_is_rendered(self) -> None:
        out = _render("human", FormatterKind.COMPAT_HISTORY, history_report(
            aggregate=(CommitDiagnostic("abc123", "error", None, "walk broke"),),
        ))
        assert "walk broke" in out
        assert "INCOMPLETE" in out

    def test_an_empty_walk_with_an_error_says_so(self) -> None:
        out = _render("human", FormatterKind.COMPAT_HISTORY, history_report(
            entries=False,
            aggregate=(CommitDiagnostic("abc123", "error", None, "walk broke"),),
        ), proto_file="a.proto")
        assert "walk broke" in out
        assert "INCOMPLETE" in out

    def test_junit_counts_an_aggregate_only_error(self) -> None:
        """V23's fourth site: the history JUnit ignored aggregate errors."""
        out = _render("junit", FormatterKind.COMPAT_HISTORY, history_report(
            aggregate=(CommitDiagnostic("abc123", "error", None, "walk broke"),),
        ))
        root = ET.fromstring(out)
        errors = sum(int(s.get("errors") or 0) for s in root.iter("testsuite"))
        assert errors == 1
        assert "walk broke" in out

    def test_junit_does_not_double_count_a_restated_entry_error(self) -> None:
        """Adjacent behavior: the CLI copies entry diagnostics into the aggregate."""
        out = _render("junit", FormatterKind.COMPAT_HISTORY, history_report(
            entry_diags=(error_diagnostic(),),
            aggregate=(CommitDiagnostic("c" * 40, "error", None, "plugin crashed"),),
        ))
        root = ET.fromstring(out)
        errors = sum(int(s.get("errors") or 0) for s in root.iter("testsuite"))
        assert errors == 1


class TestBisectTrust:
    def test_an_error_withholds_no_break_found(self) -> None:
        out = _render("human", FormatterKind.COMPAT_BISECT, bisect_report(
            CommitDiagnostic("abc123", "error", None, "plugin crashed"),
        ))
        assert "no break found" not in out
        assert "INCOMPLETE" in out
        assert "plugin crashed" in out

    def test_a_break_plus_an_error_shows_both(self) -> None:
        out = _render("human", FormatterKind.COMPAT_BISECT, bisect_report(
            CommitDiagnostic("abc123", "error", None, "plugin crashed"),
            breaking="f" * 40, findings=(_finding(),),
        ))
        assert "first breaking commit" in out
        assert "plugin crashed" in out


# ---------------------------------------------------------------------------
# LINT — the kind the plan's first draft omitted
# ---------------------------------------------------------------------------


class TestLintTrust:
    @pytest.mark.parametrize("category", ["rule_exception", "unloaded_rule"])
    def test_a_rule_that_did_not_run_is_rendered(self, category: str) -> None:
        report = LintReport(runtime_warnings=(LintRuntimeWarning(
            category=category, rule_id="x/y", message="rule blew up",  # type: ignore[arg-type]
        ),))
        out = _render("human", FormatterKind.LINT_REPORT, report)
        assert "INCOMPLETE" in out
        assert "rule blew up" in out

    def test_an_advisory_warning_leaves_a_clean_run_silent(self) -> None:
        """Adjacent behavior: the clean-run empty string is a CLI contract."""
        report = LintReport(runtime_warnings=(LintRuntimeWarning(
            category="min_severity_relaxed", rule_id=None, message="fyi",
        ),))
        assert _render("human", FormatterKind.LINT_REPORT, report) == ""
