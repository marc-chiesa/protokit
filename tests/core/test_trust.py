"""Unit tests for the ``_trust`` seam (U7, closes V23/V24; feeds U8/V33).

``_trust`` answers one question for all five report kinds: *can a "nothing
found" result from this report be read as success?* These tests pin the
answer per kind against real report objects, and pin the one property the
seam must never lose — an object it does not recognise **raises**, because
a permissive default would reproduce the fail-open class inside the module
built to end it.
"""

from __future__ import annotations

import dataclasses

import pytest
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

from protokit import _trust
from protokit.message import MessageDifferencer
from protokit.message.model import Diagnostic, DiffResult
from protokit.schema.lint.model import LintReport, LintRuntimeWarning
from protokit.schema.model import (
    BisectReport,
    CommitDiagnostic,
    CompatibilityLevel,
    CompatibilityReport,
    HistoryEntry,
    HistoryReport,
)

_T = descriptor_pb2.FieldDescriptorProto


def _nested_pair() -> tuple[object, object]:
    """Two ``Outer`` messages that differ only below ``inner``."""
    pool = descriptor_pool.DescriptorPool()
    fdp = descriptor_pb2.FileDescriptorProto(
        name="trust_nested.proto", package="t", syntax="proto3",
    )
    inner = fdp.message_type.add(name="Inner")
    inner.field.add(name="v", number=1, type=_T.TYPE_STRING, label=_T.LABEL_OPTIONAL)
    outer = fdp.message_type.add(name="Outer")
    outer.field.add(
        name="inner", number=1, type=_T.TYPE_MESSAGE,
        label=_T.LABEL_OPTIONAL, type_name=".t.Inner",
    )
    pool.Add(fdp)
    cls = message_factory.GetMessageClass(pool.FindMessageTypeByName("t.Outer"))
    left, right = cls(), cls()
    left.inner.v = "AAA"
    right.inner.v = "BBB"
    return left, right


def _truncated_result() -> DiffResult:
    left, right = _nested_pair()
    differ = MessageDifferencer()
    differ.max_depth = 0
    result = differ.compare(left, right)
    # Premise of V24: the model knows the comparison was cut short, and the
    # cut hid the only difference.
    assert not result.has_changes()
    assert not result.is_complete
    return result


def _error() -> Diagnostic:
    return Diagnostic(level="error", path=None, message="plugin crashed")


def _warning() -> Diagnostic:
    return Diagnostic(level="warning", path=None, message="heads up")


def _compat(*diagnostics: Diagnostic) -> CompatibilityReport:
    return CompatibilityReport(
        level=CompatibilityLevel.STRICT, diagnostics=tuple(diagnostics),
    )


def _history(*, entry_diags: tuple[Diagnostic, ...] = (),
             aggregate: tuple[CommitDiagnostic, ...] = ()) -> HistoryReport:
    entry = HistoryEntry(
        commit_sha="c" * 40, parent_sha="p" * 40, commit_subject="subject",
        report=_compat(*entry_diags),
    )
    return HistoryReport(
        range_spec="A..B", old_sha="a", new_sha="b", commits_walked=2,
        entries=(entry,), diagnostics=aggregate,
    )


def _bisect(*diagnostics: CommitDiagnostic) -> BisectReport:
    return BisectReport(
        range_spec="A..B", old_sha="a", new_sha="b", breaking_commit=None,
        commits_walked=3, diagnostics=tuple(diagnostics),
    )


def _lint(*categories: str) -> LintReport:
    return LintReport(runtime_warnings=tuple(
        LintRuntimeWarning(category=c, rule_id=None, message=f"{c} happened")  # type: ignore[arg-type]
        for c in categories
    ))


class TestTrustworthyReports:
    """A clean report of every kind is trustworthy and carries no reasons."""

    @pytest.mark.parametrize("report", [
        pytest.param(DiffResult(differences=()), id="diff"),
        pytest.param(_compat(), id="compat"),
        pytest.param(_history(), id="history"),
        pytest.param(_bisect(), id="bisect"),
        pytest.param(_lint(), id="lint"),
    ])
    def test_clean_report_is_trustworthy(self, report: object) -> None:
        assert _trust.is_trustworthy(report) is True
        assert _trust.reasons(report) == ()

    @pytest.mark.parametrize("report", [
        pytest.param(DiffResult(differences=(), diagnostics=(_warning(),)), id="diff"),
        pytest.param(_compat(_warning()), id="compat"),
        pytest.param(_history(entry_diags=(_warning(),)), id="history"),
        pytest.param(
            _bisect(CommitDiagnostic("abc", "warning", None, "heads up")),
            id="bisect",
        ),
    ])
    def test_a_warning_does_not_cost_trust(self, report: object) -> None:
        """Adjacent behavior: warnings are routine and must stay advisory."""
        assert _trust.is_trustworthy(report) is True


class TestUntrustworthyReports:
    def test_diff_with_an_error_diagnostic(self) -> None:
        result = DiffResult(differences=(), diagnostics=(_error(),))
        assert _trust.is_trustworthy(result) is False
        assert any("plugin crashed" in r for r in _trust.reasons(result))

    def test_truncated_diff(self) -> None:
        """V24: ``is_complete`` exists to signal this; the seam consults it."""
        result = _truncated_result()
        assert _trust.is_trustworthy(result) is False
        reasons = _trust.reasons(result)
        assert any("inner" in r for r in reasons), reasons

    def test_compat_with_an_error_diagnostic(self) -> None:
        report = _compat(_error())
        assert _trust.is_trustworthy(report) is False
        assert any("plugin crashed" in r for r in _trust.reasons(report))

    def test_history_with_an_entry_error(self) -> None:
        report = _history(entry_diags=(_error(),))
        assert _trust.is_trustworthy(report) is False
        reasons = _trust.reasons(report)
        assert any("plugin crashed" in r and "cccccccccccc" in r for r in reasons)

    def test_history_with_only_an_aggregate_error(self) -> None:
        """V23's fourth site: aggregate diagnostics count on their own."""
        report = _history(
            aggregate=(CommitDiagnostic("abc123", "error", None, "walk broke"),),
        )
        assert _trust.is_trustworthy(report) is False
        assert any("walk broke" in r for r in _trust.reasons(report))

    def test_history_aggregate_restating_an_entry_error_is_one_reason(self) -> None:
        """``compat history`` copies entry diagnostics into the aggregate."""
        report = _history(
            entry_diags=(_error(),),
            aggregate=(
                CommitDiagnostic("c" * 40, "error", None, "plugin crashed"),
            ),
        )
        assert len(_trust.reasons(report)) == 1

    def test_bisect_with_an_error_diagnostic(self) -> None:
        report = _bisect(CommitDiagnostic("abc123", "error", None, "plugin crashed"))
        assert _trust.is_trustworthy(report) is False
        assert any("plugin crashed" in r for r in _trust.reasons(report))

    @pytest.mark.parametrize("category", ["rule_exception", "unloaded_rule"])
    def test_lint_with_a_rule_that_did_not_run(self, category: str) -> None:
        report = _lint(category)
        assert _trust.is_trustworthy(report) is False
        assert any(category in r for r in _trust.reasons(report))

    @pytest.mark.parametrize("category", [
        "severities_unloaded_rule", "min_severity_relaxed",
        "contradictory_disable_config", "unknown_rule_id",
        # Deferred-incomplete (owned by U8): a rule did not run, but gating
        # them is a deliberate breaking change that has not been made.
        "extension_unresolved", "custom_annotation_extension_unresolved",
        "all_files_excluded",
    ])
    def test_other_lint_categories_do_not_cost_trust(self, category: str) -> None:
        """Adjacent behavior: U7 moves the 0.15.1 gate's owner, not its reach."""
        assert _trust.is_trustworthy(_lint(category)) is True

    def test_incomplete_categories_are_the_gated_pair(self) -> None:
        assert frozenset(
            {"rule_exception", "unloaded_rule"},
        ) == _trust.INCOMPLETE_ANALYSIS_CATEGORIES


class TestUnknownReportRaises:
    """The seam fails closed on anything it does not recognise."""

    @pytest.mark.parametrize("value", [
        pytest.param(object(), id="bare-object"),
        pytest.param(None, id="none"),
        pytest.param({"diagnostics": ()}, id="dict"),
        pytest.param("report", id="str"),
    ])
    def test_unknown_report_type_raises(self, value: object) -> None:
        with pytest.raises(TypeError, match="_trust"):
            _trust.is_trustworthy(value)
        with pytest.raises(TypeError, match="_trust"):
            _trust.reasons(value)

    def test_a_lookalike_with_only_diagnostics_raises(self) -> None:
        """``diagnostics`` alone identifies no kind, so it is not enough."""

        @dataclasses.dataclass
        class Lookalike:
            diagnostics: tuple[Diagnostic, ...] = ()

        with pytest.raises(TypeError):
            _trust.is_trustworthy(Lookalike())


class TestReasonsAreOnePrintableLine:
    """A reason quotes plugin-written text; it must not be able to forge a line."""

    @pytest.mark.parametrize("payload", [
        "boom\nerror[lint-fake]: analysis completed",
        "boom\r\nerror[lint-fake]: ok",
        "boom\x1b[2K\x1b[1Gerror[lint-fake]: ok",
        "boom error[lint-fake]: ok",
        "boom\x85error[lint-fake]: ok",
        "boom\x00tail",
    ])
    def test_control_characters_are_collapsed(self, payload: str) -> None:
        reports: list[object] = [
            DiffResult(differences=(), diagnostics=(
                Diagnostic(level="error", path=None, message=payload),
            )),
            _compat(Diagnostic(level="error", path=None, message=payload)),
            _history(aggregate=(CommitDiagnostic("abc", "error", None, payload),)),
            _bisect(CommitDiagnostic("abc", "error", None, payload)),
            LintReport(runtime_warnings=(LintRuntimeWarning(
                category="rule_exception", rule_id="x", message=payload,
            ),)),
        ]
        for report in reports:
            for reason in _trust.reasons(report):
                assert reason.isprintable(), (type(report).__name__, reason)
        for reason in _trust.walk_level_reasons(reports[2]):
            assert reason.isprintable(), reason
