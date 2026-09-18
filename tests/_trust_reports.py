"""Report builders shared by the ``_trust`` seam's test modules.

Three modules exercise the seam from three sides — the owner
(``tests/core/test_trust.py``), its renderers
(``tests/formatters/test_formatters_trust.py``) and its guards
(``tests/meta/test_formatter_trust.py``) — and all three need the same five
report kinds in a trustworthy and an untrustworthy state. They are built here
once so "an untrustworthy history report" means the same object in each.

Every builder returns the real report dataclass. A lookalike would defeat the
point: the seam recognises kinds by the attributes the real types carry.
"""

from __future__ import annotations

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

from protokit.message import MessageDifferencer
from protokit.message.model import Diagnostic, DiffResult
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


def error_diagnostic(message: str = "plugin crashed") -> Diagnostic:
    return Diagnostic(level="error", path=None, message=message)


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
    entries: bool = True,
) -> HistoryReport:
    """One-entry walk; ``entries=False`` makes it an empty walk."""
    entry = HistoryEntry(
        commit_sha=ENTRY_SHA, parent_sha="p" * 40, commit_subject="subject",
        report=compat_report(*entry_diags),
    )
    return HistoryReport(
        range_spec="A..B", old_sha="a", new_sha="b", commits_walked=2,
        entries=(entry,) if entries else (), diagnostics=aggregate,
    )


def bisect_report(
    *diagnostics: CommitDiagnostic,
    breaking: str | None = None,
    findings: tuple[Finding, ...] = (),
) -> BisectReport:
    return BisectReport(
        range_spec="A..B", old_sha="a", new_sha="b", breaking_commit=breaking,
        commits_walked=3, breaking_findings=findings,
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
