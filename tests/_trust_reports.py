"""Report builders shared by the ``_trust`` seam's test modules.

Three modules exercise the seam from three sides — the owner
(``tests/core/test_trust.py``), its renderers
(``tests/formatters/test_formatters_trust.py``) and its guards
(``tests/meta/test_formatter_trust.py``) — and all three need the same
report kinds in a trustworthy and an untrustworthy state. They are built here
once so "an untrustworthy history report" means the same object in each.

Every builder returns the real report dataclass. A lookalike would defeat the
point: the seam recognises kinds by the attributes the real types carry.
"""

from __future__ import annotations

import dataclasses

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

from protokit.forensics import DriftReport, FieldDivergence, MatchReport
from protokit.forensics._match import CandidateFit, ParseTier
from protokit.message import MessageDifferencer
from protokit.message.model import Diagnostic, DiffResult
from protokit.schema.compile import LintCompileDiagnostic
from protokit.schema.lint.model import LintFinding, LintReport, LintRuntimeWarning
from protokit.schema.model import (
    BisectReport,
    CommitDiagnostic,
    CompatibilityLevel,
    CompatibilityReport,
    Finding,
    HistoryEntry,
    HistoryReport,
)

_T = descriptor_pb2.FieldDescriptorProto

#: The SHA every built ``HistoryEntry`` carries; renderers show its first 12.
ENTRY_SHA = "c" * 40


def error_diagnostic(
    message: str = "plugin crashed", *, path: str | None = None,
) -> Diagnostic:
    """``path`` matters: a renderer can treat a path-scoped error differently."""
    return Diagnostic(level="error", path=path, message=message)


def warning_diagnostic(message: str = "heads up") -> Diagnostic:
    return Diagnostic(level="warning", path=None, message=message)


def compat_report(
    *diagnostics: Diagnostic, findings: tuple[Finding, ...] = (),
) -> CompatibilityReport:
    return CompatibilityReport(
        level=CompatibilityLevel.STRICT,
        findings=findings,
        diagnostics=tuple(diagnostics),
    )


def history_report(
    *,
    entry_diags: tuple[Diagnostic, ...] = (),
    aggregate: tuple[CommitDiagnostic, ...] = (),
    entries: int | bool = True,
    findings: tuple[Finding, ...] = (),
    broken_entry: int = 0,
) -> HistoryReport:
    """One-entry walk; ``entries=False`` makes it an empty walk.

    ``findings`` puts a rule pack's own text on the entry, which is the only
    way the per-finding lines of this kind's renderers are ever exercised.
    """
    count = int(entries)
    built = tuple(
        HistoryEntry(
            commit_sha=chr(ord("a") + i) * 40, parent_sha="p" * 40,
            commit_subject="subject",
            report=compat_report(
                *(entry_diags if i == broken_entry else ()), findings=findings,
            ),
        )
        for i in range(count)
    )
    # One entry keeps ENTRY_SHA so existing expectations hold.
    if count == 1:
        built = (dataclasses.replace(built[0], commit_sha=ENTRY_SHA),)
    return HistoryReport(
        range_spec="A..B", old_sha="a", new_sha="b", commits_walked=2,
        entries=built, diagnostics=aggregate,
    )


def bisect_report(
    *diagnostics: CommitDiagnostic,
    breaking: str | None = None,
    findings: tuple[Finding, ...] = (),
    walked: int = 3,
) -> BisectReport:
    """``walked=0`` is the empty walk, which renders its own way."""
    return BisectReport(
        range_spec="A..B", old_sha="a", new_sha="b", breaking_commit=breaking,
        commits_walked=walked, breaking_findings=findings,
        diagnostics=tuple(diagnostics),
    )


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


def truncated_diff_result() -> DiffResult:
    """A real ``max_depth=0`` comparison whose cut hid the only difference (V24)."""
    left, right = _nested_pair()
    differ = MessageDifferencer()
    differ.max_depth = 0
    result = differ.compare(left, right)
    # Premise of V24: the model knows the comparison was cut short, and the
    # cut hid the only difference.
    assert not result.has_changes()
    assert not result.is_complete
    return result


def lint_finding(rule_id: str = "naming/snake-case-fields") -> LintFinding:
    """A lint finding whose rule id and rendered message are a pack's words."""
    from protokit.schema.lint.model import FieldLocation, LintSeverity
    return LintFinding(
        rule_id=rule_id,
        severity=LintSeverity.WARNING,
        location=FieldLocation(
            file="acme/user.proto", message="acme.User", field="BadField",
        ),
        violation_kind=rule_id,
        params={"name": "BadField"},
    )


def lint_report(
    *,
    categories: tuple[str, ...] = (),
    rule_id: str | None = "pack/rule",
    message: str = "rule blew up",
    compile_error: str | None = None,
    findings: tuple[LintFinding, ...] = (),
    elements: int = 1,
) -> LintReport:
    """A ``LintReport`` untrustworthy in each way the seam recognises.

    ``categories`` names the runtime-warning categories to emit (the engine
    emits one warning per dispatched element, which ``elements`` mimics);
    ``compile_error`` adds an error-level compile diagnostic, the other way a
    lint run can produce no findings for the wrong reason.
    """
    warnings = tuple(
        LintRuntimeWarning(category=c, rule_id=rule_id, message=message)  # type: ignore[arg-type]
        for c in categories for _ in range(elements)
    )
    diagnostics = (
        (LintCompileDiagnostic(level="error", message=compile_error),)
        if compile_error else ()
    )
    return LintReport(
        findings=findings, runtime_warnings=warnings, diagnostics=diagnostics,
    )


def candidate_fit(
    label: str = "v1",
    *,
    parse_outcome: str = "clean",
    detail: str | None = None,
) -> CandidateFit:
    """One ranked candidate. ``parse_outcome`` decides whether it was measured."""
    measured = parse_outcome not in {"decode_error", "incomplete"}
    return CandidateFit(
        label=label,
        tier=ParseTier.CLEAN if measured else ParseTier.FAULT,
        parse_outcome=parse_outcome,  # type: ignore[arg-type]
        total_bytes=12,
        unmodeled_bytes=0 if measured else None,
        modeled_fraction=1.0 if measured else None,
        declared_field_coverage=1.0 if measured else None,
        present_field_count=2 if measured else 0,
        declared_field_count=2,
        detail=detail,
    )


def match_report(
    *diagnostics: Diagnostic, ranked: tuple[CandidateFit, ...] = (),
) -> MatchReport:
    """A ``MatchReport``. Default is a clean two-candidate sweep."""
    return MatchReport(
        ranked=ranked or (candidate_fit("v1"), candidate_fit("v2")),
        verdict="clean_winner",
        ambiguous_top=False,
        diagnostics=tuple(diagnostics),
    )


def drift_report(
    *diagnostics: Diagnostic, divergences: tuple[FieldDivergence, ...] = (),
) -> DriftReport:
    """A ``DriftReport``. Divergences are findings, so they cost no trust."""
    return DriftReport(
        divergences=divergences,
        observed_field_count=2,
        diagnostics=tuple(diagnostics),
    )


def field_divergence(field_number: int = 7) -> FieldDivergence:
    return FieldDivergence(
        field_number=field_number, kind="undeclared", detail="tag not declared",
    )
