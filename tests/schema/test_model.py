"""Tests for protokit.schema.model.

Pure dataclass / enum behavior. No descriptor traversal, no rules.
"""

import pytest

from protokit.message.model import Diagnostic, FieldPath
from protokit.schema import (
    BisectReport,
    CommitDiagnostic,
    CompatibilityLevel,
    CompatibilityReport,
    Direction,
    Finding,
    HistoryEntry,
    HistoryReport,
    Severity,
    Verdict,
)


def _make_finding(
    path: str = "user.email",
    *,
    rule_id: str = "field_removed",
    severity: Severity = Severity.SEMANTIC,
    direction: Direction = Direction.BACKWARD,
    message: str = "field present in old schema, absent in new",
) -> Finding:
    return Finding(
        path=FieldPath.parse(path),
        rule_id=rule_id,
        severity=severity,
        direction=direction,
        message=message,
    )


class TestEnums:
    def test_severity_values(self) -> None:
        assert {s.value for s in Severity} == {"WIRE", "SEMANTIC", "POLICY"}

    def test_direction_values(self) -> None:
        assert {d.value for d in Direction} == {"FORWARD", "BACKWARD", "BOTH"}

    def test_verdict_values(self) -> None:
        assert {v.value for v in Verdict} == {
            "COMPATIBLE",
            "INCOMPATIBLE",
            "UNKNOWN",
        }

    def test_compatibility_level_values(self) -> None:
        assert {lvl.value for lvl in CompatibilityLevel} == {
            "WIRE",
            "CONSUMER_SAFE",
            "PRODUCER_SAFE",
            "STRICT",
        }


class TestFinding:
    def test_basic_construction(self) -> None:
        f = _make_finding()
        assert f.rule_id == "field_removed"
        assert f.severity is Severity.SEMANTIC
        assert f.direction is Direction.BACKWARD
        assert f.path == FieldPath.parse("user.email")
        assert f.old_descriptor is None
        assert f.new_descriptor is None

    def test_frozen(self) -> None:
        f = _make_finding()
        with pytest.raises(Exception):  # FrozenInstanceError is a dataclasses type
            f.rule_id = "other"  # type: ignore[misc]

    def test_equal_findings_compare_equal(self) -> None:
        assert _make_finding() == _make_finding()

    def test_different_rule_id_not_equal(self) -> None:
        assert _make_finding(rule_id="a") != _make_finding(rule_id="b")

    def test_str_contains_severity_direction_path_and_rule_id(self) -> None:
        s = str(_make_finding())
        assert "SEMANTIC" in s
        assert "BACKWARD" in s
        assert "user.email" in s
        assert "field_removed" in s

    def test_str_handles_empty_path(self) -> None:
        f = Finding(
            path=FieldPath(segments=()),
            rule_id="r",
            severity=Severity.WIRE,
            direction=Direction.BOTH,
            message="m",
        )
        assert "(root)" in str(f)

    def test_old_and_new_descriptor_store_arbitrary_objects(self) -> None:
        sentinel_a = object()
        sentinel_b = object()
        f = Finding(
            path=FieldPath.parse("x"),
            rule_id="r",
            severity=Severity.WIRE,
            direction=Direction.BOTH,
            message="m",
            old_descriptor=sentinel_a,
            new_descriptor=sentinel_b,
        )
        assert f.old_descriptor is sentinel_a
        assert f.new_descriptor is sentinel_b


class TestCompatibilityReport:
    def test_empty_report_is_compatible(self) -> None:
        r = CompatibilityReport(level=CompatibilityLevel.STRICT)
        assert r.is_compatible is True
        assert r.verdict is Verdict.COMPATIBLE
        assert not bool(r)
        assert len(r) == 0

    def test_report_with_findings_is_incompatible(self) -> None:
        r = CompatibilityReport(
            level=CompatibilityLevel.CONSUMER_SAFE,
            findings=(_make_finding(),),
        )
        assert r.is_compatible is False
        assert r.verdict is Verdict.INCOMPATIBLE
        assert bool(r) is True
        assert len(r) == 1

    def test_iteration_yields_findings(self) -> None:
        f1 = _make_finding(path="a")
        f2 = _make_finding(path="b")
        r = CompatibilityReport(
            level=CompatibilityLevel.STRICT,
            findings=(f1, f2),
        )
        assert list(r) == [f1, f2]

    def test_severity_buckets(self) -> None:
        wire = _make_finding(rule_id="w", severity=Severity.WIRE, direction=Direction.BOTH)
        semantic = _make_finding(rule_id="s", severity=Severity.SEMANTIC)
        policy = _make_finding(rule_id="p", severity=Severity.POLICY, direction=Direction.BOTH)
        r = CompatibilityReport(
            level=CompatibilityLevel.STRICT,
            findings=(wire, semantic, policy),
        )
        assert r.wire_breaks == (wire,)
        assert r.semantic_breaks == (semantic,)
        assert r.policy_breaks == (policy,)

    def test_bucket_with_zero_matches(self) -> None:
        wire = _make_finding(severity=Severity.WIRE, direction=Direction.BOTH)
        r = CompatibilityReport(
            level=CompatibilityLevel.WIRE,
            findings=(wire,),
        )
        assert r.semantic_breaks == ()
        assert r.policy_breaks == ()

    def test_level_stored(self) -> None:
        r = CompatibilityReport(level=CompatibilityLevel.PRODUCER_SAFE)
        assert r.level is CompatibilityLevel.PRODUCER_SAFE

    def test_report_is_frozen(self) -> None:
        r = CompatibilityReport(level=CompatibilityLevel.STRICT)
        with pytest.raises(Exception):
            r.findings = ()  # type: ignore[misc]

    def test_default_findings_empty_tuple(self) -> None:
        r = CompatibilityReport(level=CompatibilityLevel.WIRE)
        assert r.findings == ()


class TestCommitDiagnostic:
    def test_basic_construction(self) -> None:
        cd = CommitDiagnostic(
            commit="abc123", level="error", path="user.email", message="boom",
        )
        assert cd.commit == "abc123"
        assert cd.level == "error"
        assert cd.path == "user.email"
        assert cd.message == "boom"

    def test_path_can_be_none(self) -> None:
        cd = CommitDiagnostic(
            commit="abc123", level="warning", path=None, message="global",
        )
        assert cd.path is None

    def test_is_frozen(self) -> None:
        cd = CommitDiagnostic(
            commit="x", level="info", path=None, message="m",
        )
        with pytest.raises(Exception):
            cd.commit = "y"  # type: ignore[misc]


class TestHistoryEntry:
    def test_basic_construction(self) -> None:
        report = CompatibilityReport(level=CompatibilityLevel.STRICT)
        entry = HistoryEntry(
            commit_sha="new123", parent_sha="old456",
            commit_subject="fix: thing", report=report,
        )
        assert entry.commit_sha == "new123"
        assert entry.parent_sha == "old456"
        assert entry.commit_subject == "fix: thing"
        assert entry.report is report

    def test_is_frozen(self) -> None:
        entry = HistoryEntry(
            commit_sha="a", parent_sha="b", commit_subject="s",
            report=CompatibilityReport(level=CompatibilityLevel.STRICT),
        )
        with pytest.raises(Exception):
            entry.commit_sha = "c"  # type: ignore[misc]


class TestHistoryReport:
    def test_minimal_construction(self) -> None:
        r = HistoryReport(
            range_spec="HEAD~3..HEAD", old_sha="aaa", new_sha="bbb",
            commits_walked=0,
        )
        assert r.range_spec == "HEAD~3..HEAD"
        assert r.entries == ()
        assert r.diagnostics == ()
        assert r.commits_walked == 0

    def test_tuple_coercion_for_entries(self) -> None:
        report = CompatibilityReport(level=CompatibilityLevel.STRICT)
        entry = HistoryEntry(
            commit_sha="x", parent_sha="y", commit_subject="s", report=report,
        )
        r = HistoryReport(
            range_spec="r", old_sha="a", new_sha="b", commits_walked=1,
            entries=[entry],  # list, not tuple
        )
        assert isinstance(r.entries, tuple)
        assert r.entries == (entry,)

    def test_tuple_coercion_for_diagnostics(self) -> None:
        diag = CommitDiagnostic(commit="x", level="error", path=None, message="m")
        r = HistoryReport(
            range_spec="r", old_sha="a", new_sha="b", commits_walked=0,
            diagnostics=[diag],
        )
        assert isinstance(r.diagnostics, tuple)
        assert r.diagnostics == (diag,)

    def test_commits_walked_independent_from_entries(self) -> None:
        # Pairing consumes one commit as the anchor, so commits_walked
        # may exceed len(entries).
        r = HistoryReport(
            range_spec="r", old_sha="a", new_sha="b", commits_walked=5,
            entries=(),
        )
        assert r.commits_walked == 5
        assert len(r.entries) == 0

    def test_is_frozen(self) -> None:
        r = HistoryReport(
            range_spec="r", old_sha="a", new_sha="b", commits_walked=0,
        )
        with pytest.raises(Exception):
            r.range_spec = "x"  # type: ignore[misc]


class TestBisectReport:
    def test_minimal_construction(self) -> None:
        r = BisectReport(
            range_spec="A..B", old_sha="aaa", new_sha="bbb",
            breaking_commit=None, commits_walked=0,
        )
        assert r.breaking_commit is None
        assert r.breaking_findings == ()
        assert r.diagnostics == ()
        assert r.commits_walked == 0

    def test_breaking_commit_with_findings(self) -> None:
        finding = _make_finding()
        r = BisectReport(
            range_spec="A..B", old_sha="aaa", new_sha="bbb",
            breaking_commit="xxx", commits_walked=3,
            breaking_findings=(finding,),
        )
        assert r.breaking_commit == "xxx"
        assert r.breaking_findings == (finding,)

    def test_tuple_coercion_for_breaking_findings(self) -> None:
        finding = _make_finding()
        r = BisectReport(
            range_spec="r", old_sha="a", new_sha="b",
            breaking_commit="x", commits_walked=1,
            breaking_findings=[finding],  # list, not tuple
        )
        assert isinstance(r.breaking_findings, tuple)

    def test_tuple_coercion_for_diagnostics(self) -> None:
        diag = CommitDiagnostic(commit="x", level="error", path=None, message="m")
        r = BisectReport(
            range_spec="r", old_sha="a", new_sha="b",
            breaking_commit=None, commits_walked=0,
            diagnostics=[diag],
        )
        assert isinstance(r.diagnostics, tuple)

    def test_is_frozen(self) -> None:
        r = BisectReport(
            range_spec="r", old_sha="a", new_sha="b",
            breaking_commit=None, commits_walked=0,
        )
        with pytest.raises(Exception):
            r.breaking_commit = "x"  # type: ignore[misc]

