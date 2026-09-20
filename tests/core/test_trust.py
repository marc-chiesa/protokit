"""Unit tests for the ``_trust`` seam (U7, closes V23/V24; feeds U8/V33).

``_trust`` answers one question for every report kind: *can a "nothing
found" result from this report be read as success?* These tests pin the
answer per kind against real report objects, and pin the one property the
seam must never lose — an object it does not recognise **raises**, because
a permissive default would reproduce the fail-open class inside the module
built to end it.
"""

from __future__ import annotations

import dataclasses

import pytest

from protokit import _trust
from protokit.message.model import Diagnostic, DiffResult
from protokit.schema.compile import LintCompileDiagnostic
from protokit.schema.lint.model import LintReport, LintRuntimeWarning
from protokit.schema.model import CommitDiagnostic
from tests._trust_reports import (
    ENTRY_SHA,
    bisect_report,
    candidate_fit,
    compat_report,
    drift_report,
    error_diagnostic,
    field_divergence,
    history_report,
    lint_report,
    match_report,
    truncated_diff_result,
    warning_diagnostic,
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
        pytest.param(compat_report(), id="compat"),
        pytest.param(history_report(), id="history"),
        pytest.param(bisect_report(), id="bisect"),
        pytest.param(_lint(), id="lint"),
        pytest.param(match_report(), id="match"),
        pytest.param(drift_report(), id="drift"),
    ])
    def test_clean_report_is_trustworthy(self, report: object) -> None:
        assert _trust.is_trustworthy(report) is True
        assert _trust.reasons(report) == ()

    @pytest.mark.parametrize("report", [
        pytest.param(DiffResult(differences=(), diagnostics=(warning_diagnostic(),)), id="diff"),
        pytest.param(compat_report(warning_diagnostic()), id="compat"),
        pytest.param(history_report(entry_diags=(warning_diagnostic(),)), id="history"),
        pytest.param(
            bisect_report(CommitDiagnostic("abc", "warning", None, "heads up")),
            id="bisect",
        ),
        pytest.param(match_report(warning_diagnostic()), id="match"),
        pytest.param(drift_report(warning_diagnostic()), id="drift"),
    ])
    def test_a_warning_does_not_cost_trust(self, report: object) -> None:
        """Adjacent behavior: warnings are routine and must stay advisory."""
        assert _trust.is_trustworthy(report) is True


class TestUntrustworthyReports:
    def test_diff_with_an_error_diagnostic(self) -> None:
        result = DiffResult(differences=(), diagnostics=(error_diagnostic(),))
        assert _trust.is_trustworthy(result) is False
        assert any("plugin crashed" in r for r in _trust.reasons(result))

    def test_truncated_diff(self) -> None:
        """V24: ``is_complete`` exists to signal this; the seam consults it."""
        result = truncated_diff_result()
        assert _trust.is_trustworthy(result) is False
        reasons = _trust.reasons(result)
        assert any("inner" in r for r in reasons), reasons

    def test_compat_with_an_error_diagnostic(self) -> None:
        report = compat_report(error_diagnostic())
        assert _trust.is_trustworthy(report) is False
        assert any("plugin crashed" in r for r in _trust.reasons(report))

    def test_history_with_an_entry_error(self) -> None:
        report = history_report(entry_diags=(error_diagnostic(),))
        assert _trust.is_trustworthy(report) is False
        reasons = _trust.reasons(report)
        assert any("plugin crashed" in r and "cccccccccccc" in r for r in reasons)

    def test_history_with_only_an_aggregate_error(self) -> None:
        """V23's fourth site: aggregate diagnostics count on their own."""
        report = history_report(
            aggregate=(CommitDiagnostic("abc123", "error", None, "walk broke"),),
        )
        assert _trust.is_trustworthy(report) is False
        assert any("walk broke" in r for r in _trust.reasons(report))

    def test_history_aggregate_restating_an_entry_error_is_one_reason(self) -> None:
        """``compat history`` copies entry diagnostics into the aggregate."""
        report = history_report(
            entry_diags=(error_diagnostic(),),
            aggregate=(
                CommitDiagnostic("c" * 40, "error", None, "plugin crashed"),
            ),
        )
        assert len(_trust.reasons(report)) == 1

    def test_bisect_with_an_error_diagnostic(self) -> None:
        report = bisect_report(CommitDiagnostic("abc123", "error", None, "plugin crashed"))
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


class TestForensicsReports:
    """U8: the seam learned ``MatchReport`` and ``DriftReport``.

    Forensics' two commands exited 0 on every run that did not hard-error,
    including a ranking in which a candidate never parsed. The seam now
    recognises both kinds, so their exit paths can ask it the same question
    every other command asks.
    """

    def test_a_candidate_that_was_not_measured_costs_trust(self) -> None:
        report = match_report(ranked=(
            candidate_fit("v1"),
            candidate_fit(
                "v2", parse_outcome="incomplete", detail="could not measure",
            ),
        ))
        assert _trust.is_trustworthy(report) is False
        assert _trust.reasons(report) == ("v2: could not measure",)

    def test_the_reason_falls_back_to_the_outcome_without_a_detail(self) -> None:
        report = match_report(ranked=(
            candidate_fit("v2", parse_outcome="incomplete"),
        ))
        assert _trust.reasons(report) == ("v2: incomplete",)

    def test_every_unmeasured_candidate_gets_its_own_reason(self) -> None:
        """Two blind spots must not collapse into one line."""
        report = match_report(ranked=(
            candidate_fit("v1", parse_outcome="incomplete", detail="no x"),
            candidate_fit("v2", parse_outcome="incomplete", detail="no y"),
        ))
        assert _trust.reasons(report) == ("v1: no x", "v2: no y")

    @pytest.mark.parametrize("outcome", ["clean", "unmodeled", "decode_error"])
    def test_a_measured_candidate_costs_nothing(self, outcome: str) -> None:
        """``unmodeled`` and ``decode_error`` are ranking results, not faults.

        A candidate the message does not decode under has been *evaluated*
        and ruled out -- the ordinary outcome of ranking one message against
        several schema versions, most of which did not produce it. Gating on
        it would make a healthy ranking exit non-zero nearly every time. Only
        a candidate whose modeled-byte fraction could not be computed at all
        (``incomplete``) never entered the contest.
        """
        report = match_report(ranked=(candidate_fit("v1", parse_outcome=outcome),))
        assert _trust.is_trustworthy(report) is True

    def test_match_signals_are_their_own_kind(self) -> None:
        """A renderer that shows error diagnostics itself still sees these."""
        report = match_report(ranked=(
            candidate_fit("v2", parse_outcome="incomplete"),
        ))
        signal, = _trust.signals(report)
        assert signal.kind == _trust.CANDIDATE_NOT_MEASURED
        assert _trust.signals_other_than(report, _trust.ERROR_DIAGNOSTIC) == (signal,)

    def test_a_match_error_diagnostic_costs_trust(self) -> None:
        report = match_report(error_diagnostic("ranker blew up"))
        assert _trust.is_trustworthy(report) is False
        assert _trust.reasons(report) == ("ranker blew up",)

    def test_a_divergence_is_a_finding_not_an_incompleteness(self) -> None:
        """``drift``'s whole output is divergences; they are what it found."""
        report = drift_report(divergences=(
            field_divergence(7), field_divergence(9),
        ))
        assert _trust.is_trustworthy(report) is True
        assert _trust.reasons(report) == ()

    def test_a_drift_error_diagnostic_costs_trust(self) -> None:
        report = drift_report(error_diagnostic("walk blew up"))
        assert _trust.is_trustworthy(report) is False
        assert _trust.reasons(report) == ("walk blew up",)


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
            compat_report(Diagnostic(level="error", path=None, message=payload)),
            history_report(aggregate=(CommitDiagnostic("abc", "error", None, payload),)),
            bisect_report(CommitDiagnostic("abc", "error", None, payload)),
            LintReport(runtime_warnings=(LintRuntimeWarning(
                category="rule_exception", rule_id="x", message=payload,
            ),)),
        ]
        for report in reports:
            for reason in _trust.reasons(report):
                assert reason.isprintable(), (type(report).__name__, reason)
        for reason in _trust.walk_level_reasons(reports[2]):
            assert reason.isprintable(), reason


class TestSignalsAreTyped:
    """A reason carries its kind, so a format can tell what it already shows."""

    def test_every_signal_text_matches_reasons(self) -> None:
        report = history_report(entry_diags=(error_diagnostic(),))
        assert tuple(s.text for s in _trust.signals(report)) == _trust.reasons(report)

    def test_a_format_can_exclude_what_it_renders_itself(self) -> None:
        report = compat_report(error_diagnostic())
        assert _trust.reasons(report)
        assert _trust.signals_other_than(report, _trust.ERROR_DIAGNOSTIC) == ()

    def test_history_entry_errors_are_excluded_only_when_asked(self) -> None:
        """The per-entry renderers show entry errors; walk-level ones they do not."""
        report = history_report(
            entry_diags=(error_diagnostic(),),
            aggregate=(CommitDiagnostic("abc123", "error", None, "walk broke"),),
        )
        kept = _trust.signals_other_than(
            report, _trust.ERROR_DIAGNOSTIC, only_from_entries=True,
        )
        assert [s.text for s in kept] == ["abc123: walk broke"]
        assert _trust.signals_other_than(report, _trust.ERROR_DIAGNOSTIC) == ()

    def test_an_unknown_kind_survives_every_exclusion(self) -> None:
        """Fail closed: a format may only exclude the kind it actually renders."""
        report = lint_report(categories=("rule_exception",))
        assert _trust.signals_other_than(report, _trust.ERROR_DIAGNOSTIC)
        assert _trust.signals_other_than(report, _trust.COMPILE_DIAGNOSTIC)


class TestLintReasonsCountRules:
    def test_one_rule_raising_on_many_elements_is_one_reason(self) -> None:
        """The engine emits one warning per element; a rule is still one rule."""
        report = lint_report(categories=("rule_exception",), elements=9)
        reasons = _trust.reasons(report)
        assert len(reasons) == 1
        assert "pack/rule" in reasons[0]
        assert "(on 9 elements)" in reasons[0]

    def test_two_rules_are_two_reasons(self) -> None:
        report = LintReport(runtime_warnings=(
            LintRuntimeWarning(category="rule_exception", rule_id="a/one", message="x"),
            LintRuntimeWarning(category="rule_exception", rule_id="b/two", message="y"),
        ))
        assert len(_trust.reasons(report)) == 2

    def test_a_warning_without_a_rule_id_still_reports(self) -> None:
        report = LintReport(runtime_warnings=(
            LintRuntimeWarning(category="unloaded_rule", rule_id=None, message="gone"),
        ))
        assert _trust.reasons(report) == ("[unloaded_rule] gone",)

    def test_a_compile_error_is_a_reason_of_its_own_kind(self) -> None:
        """A schema that did not compile produced no findings for that reason."""
        report = lint_report(compile_error="protoc failed")
        assert _trust.is_trustworthy(report) is False
        assert [s.kind for s in _trust.signals(report)] == [_trust.COMPILE_DIAGNOSTIC]

    def test_an_info_compile_diagnostic_costs_nothing(self) -> None:
        """Adjacent behavior: the protoxy-fallback notice is not a failure."""
        report = LintReport(diagnostics=(LintCompileDiagnostic(
            level="info", message="protoxy unavailable", category="protoxy_fallback",
        ),))
        assert _trust.is_trustworthy(report) is True


class TestHistoryAggregateIdentity:
    def test_same_message_different_paths_both_survive(self) -> None:
        """Two plugin failures on one commit are two reasons, not one."""
        report = history_report(
            entry_diags=(Diagnostic(level="error", path="a", message="boom"),),
            aggregate=(CommitDiagnostic(ENTRY_SHA, "error", "b", "boom"),),
        )
        reasons = _trust.reasons(report)
        assert len(reasons) == 2
        assert any("a: boom" in r for r in reasons)
        assert any("b: boom" in r for r in reasons)

    def test_an_exact_restatement_still_collapses(self) -> None:
        report = history_report(
            entry_diags=(Diagnostic(level="error", path="a", message="boom"),),
            aggregate=(CommitDiagnostic(ENTRY_SHA, "error", "a", "boom"),),
        )
        assert len(_trust.reasons(report)) == 1

    def test_multiplicity_beyond_one_is_matched(self) -> None:
        """Two identical entry errors and three identical aggregate ones: one survives."""
        error = Diagnostic(level="error", path=None, message="boom")
        restated = CommitDiagnostic(ENTRY_SHA, "error", None, "boom")
        report = history_report(
            entry_diags=(error, error), aggregate=(restated, restated, restated),
        )
        assert len(_trust.reasons(report)) == 3  # 2 entry + 1 surviving aggregate
        assert len(_trust.walk_level_reasons(report)) == 1

    def test_the_aggregate_path_is_rendered(self) -> None:
        report = bisect_report(CommitDiagnostic("abc123", "error", "user.email", "boom"))
        assert _trust.reasons(report) == ("abc123: user.email: boom",)
