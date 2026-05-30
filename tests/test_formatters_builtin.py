"""Tests for the built-in formatter extractions.

Strategy: each built-in is a verbatim extraction of rendering
logic that previously lived in ``protokit.message.cli`` or
``protokit.schema.cli``. The contract is byte-for-byte
equivalence with the legacy rendering for human output and
``json.loads(new) == json.loads(old)`` structural equivalence
for JSON.

These tests will live across the Unit 3 → Unit 5 transition:
once Unit 5 wires the CLI to use the registry, the legacy
rendering helpers are deleted; the regression coverage for the
output then comes from the existing CLI integration tests in
``tests/test_cli.py`` and ``tests/schema/test_cli.py``.
"""

from __future__ import annotations

import json

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

from protokit.formatters import (
    FormatterContext,
    FormatterKind,
    get_formatter,
)
from protokit.message import MessageDifferencer
from protokit.message.model import Diagnostic
from protokit.schema.model import (
    BisectReport,
    CommitDiagnostic,
    CompatibilityLevel,
    CompatibilityReport,
    Direction,
    Finding,
    HistoryEntry,
    HistoryReport,
    Severity,
)


# ---------------------------------------------------------------------------
# Helpers — small protobuf fixture for diff tests
# ---------------------------------------------------------------------------


def _build_msg_class(pool: descriptor_pool.DescriptorPool) -> type:
    """Build a tiny protobuf message type via descriptor_pool."""
    fdp = descriptor_pb2.FileDescriptorProto()
    fdp.name = "test_builtin.proto"
    fdp.syntax = "proto3"
    msg = fdp.message_type.add()
    msg.name = "Person"
    fld = msg.field.add()
    fld.name = "name"
    fld.number = 1
    fld.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING
    fld.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    age = msg.field.add()
    age.name = "age"
    age.number = 2
    age.type = descriptor_pb2.FieldDescriptorProto.TYPE_INT32
    age.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    pool.Add(fdp)
    return message_factory.GetMessageClass(pool.FindMessageTypeByName("Person"))


# ---------------------------------------------------------------------------
# Built-in registration
# ---------------------------------------------------------------------------


class TestBuiltinRegistration:
    def test_diff_human_registered(self) -> None:
        assert get_formatter("human", FormatterKind.DIFF) is not None

    def test_diff_json_registered(self) -> None:
        assert get_formatter("json", FormatterKind.DIFF) is not None

    def test_compat_human_registered(self) -> None:
        assert get_formatter("human", FormatterKind.COMPAT) is not None

    def test_compat_json_registered(self) -> None:
        assert get_formatter("json", FormatterKind.COMPAT) is not None

    def test_history_human_registered(self) -> None:
        assert get_formatter("human", FormatterKind.COMPAT_HISTORY) is not None

    def test_history_json_registered(self) -> None:
        assert get_formatter("json", FormatterKind.COMPAT_HISTORY) is not None

    def test_bisect_human_registered(self) -> None:
        assert get_formatter("human", FormatterKind.COMPAT_BISECT) is not None

    def test_bisect_json_registered(self) -> None:
        assert get_formatter("json", FormatterKind.COMPAT_BISECT) is not None


# ---------------------------------------------------------------------------
# DIFF — formatter output matches legacy CLI rendering
# ---------------------------------------------------------------------------


class TestDiffFormatters:
    def test_diff_human_equal_messages(self) -> None:
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        result = MessageDifferencer().compare(cls(name="A"), cls(name="A"))
        fn = get_formatter("human", FormatterKind.DIFF)
        out = fn(result, FormatterContext(subcommand="diff"))
        # Equal -> single colored "Messages are equal." line.
        assert "Messages are equal." in out

    def test_diff_human_with_changes(self) -> None:
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        result = MessageDifferencer().compare(
            cls(name="A", age=10), cls(name="B", age=20),
        )
        fn = get_formatter("human", FormatterKind.DIFF)
        out = fn(result, FormatterContext(subcommand="diff"))
        # Both modifications appear; header announces count.
        assert "Found 2 differences" in out
        assert "name" in out
        assert "age" in out

    def test_diff_json_structural_shape(self) -> None:
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        result = MessageDifferencer().compare(
            cls(name="A"), cls(name="B"),
        )
        fn = get_formatter("json", FormatterKind.DIFF)
        out = fn(result, FormatterContext(subcommand="diff"))
        payload = json.loads(out)
        assert payload["equal"] is False
        assert isinstance(payload["differences"], list)
        assert len(payload["differences"]) == 1
        diff = payload["differences"][0]
        assert diff["path"] == "name"
        assert diff["change_type"] == "MODIFIED"
        assert diff["left_value"] == "A"
        assert diff["right_value"] == "B"
        # deprecated alias keys still emitted (removed in protokit 1.0)
        assert diff["old_value"] == "A"
        assert diff["new_value"] == "B"
        assert diff["field_type"] == "TYPE_STRING"
        assert payload["diagnostics"] == []

    def test_diff_json_equal(self) -> None:
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        result = MessageDifferencer().compare(cls(), cls())
        fn = get_formatter("json", FormatterKind.DIFF)
        payload = json.loads(fn(result, FormatterContext(subcommand="diff")))
        assert payload == {
            "schema_version": "0.1",
            "equal": True,
            "differences": [],
            "diagnostics": [],
        }


# ---------------------------------------------------------------------------
# COMPAT — formatter output matches legacy CLI rendering
# ---------------------------------------------------------------------------


def _make_finding(rule_id: str = "field_removed") -> Finding:
    from protokit.message.model import FieldPath
    return Finding(
        path=FieldPath.parse("user.email"),
        rule_id=rule_id,
        severity=Severity.SEMANTIC,
        direction=Direction.BACKWARD,
        message="field present in old schema, absent in new",
    )


class TestCompatFormatters:
    def test_compat_human_compatible(self) -> None:
        report = CompatibilityReport(level=CompatibilityLevel.STRICT)
        fn = get_formatter("human", FormatterKind.COMPAT)
        out = fn(report, FormatterContext(subcommand="compat-check"))
        assert "COMPATIBLE" in out
        assert "0 finding" in out

    def test_compat_human_incompatible(self) -> None:
        report = CompatibilityReport(
            level=CompatibilityLevel.STRICT,
            findings=(_make_finding(),),
        )
        fn = get_formatter("human", FormatterKind.COMPAT)
        out = fn(report, FormatterContext(subcommand="compat-check"))
        assert "INCOMPATIBLE" in out
        assert "1 finding" in out
        assert "user.email" in out
        assert "field_removed" in out

    def test_compat_json_shape(self) -> None:
        report = CompatibilityReport(
            level=CompatibilityLevel.STRICT,
            findings=(_make_finding(),),
            diagnostics=(Diagnostic(level="warning", path=None, message="m"),),
        )
        fn = get_formatter("json", FormatterKind.COMPAT)
        payload = json.loads(fn(report, FormatterContext(subcommand="compat-check")))
        assert payload["compatible"] is False
        assert payload["level"] == "STRICT"
        assert payload["findings"][0]["rule_id"] == "field_removed"
        assert payload["diagnostics"][0]["message"] == "m"
        assert payload["summary"]["semantic_breaks"] == 1
        assert payload["summary"]["total"] == 1


# ---------------------------------------------------------------------------
# HISTORY — formatter output matches legacy CLI rendering
# ---------------------------------------------------------------------------


class TestHistoryFormatters:
    def test_history_human_empty_walk(self) -> None:
        report = HistoryReport(
            range_spec="HEAD~3..HEAD",
            old_sha="aaa", new_sha="bbb", commits_walked=0,
        )
        fn = get_formatter("human", FormatterKind.COMPAT_HISTORY)
        out = fn(report, FormatterContext(
            subcommand="compat-history", proto_file="acme/user.proto",
        ))
        assert out == "# HEAD~3..HEAD: no commits touch acme/user.proto"

    def test_history_human_with_entries(self) -> None:
        clean = CompatibilityReport(level=CompatibilityLevel.STRICT)
        broken = CompatibilityReport(
            level=CompatibilityLevel.STRICT,
            findings=(_make_finding(),),
        )
        report = HistoryReport(
            range_spec="r", old_sha="a", new_sha="b", commits_walked=2,
            entries=[
                HistoryEntry(
                    commit_sha="abc123def456ghi", parent_sha="x",
                    commit_subject="ok commit", report=clean,
                ),
                HistoryEntry(
                    commit_sha="bad999bad999ghi", parent_sha="abc123def456ghi",
                    commit_subject="break it", report=broken,
                ),
            ],
        )
        fn = get_formatter("human", FormatterKind.COMPAT_HISTORY)
        out = fn(report, FormatterContext(subcommand="compat-history"))
        assert "abc123def456 OK" in out
        assert "bad999bad999 BROKEN" in out
        assert "user.email" in out

    def test_history_json_empty_walk(self) -> None:
        report = HistoryReport(
            range_spec="HEAD~3..HEAD",
            old_sha="aaa", new_sha="bbb", commits_walked=0,
        )
        fn = get_formatter("json", FormatterKind.COMPAT_HISTORY)
        payload = json.loads(fn(report, FormatterContext(subcommand="compat-history")))
        assert payload == {
            "range": "HEAD~3..HEAD",
            "old": "aaa",
            "new": "bbb",
            "commits_walked": 0,
            "entries": [],
            "diagnostics": [],
        }

    def test_history_json_with_aggregated_diagnostics(self) -> None:
        report = HistoryReport(
            range_spec="r", old_sha="a", new_sha="b", commits_walked=1,
            diagnostics=[
                CommitDiagnostic(
                    commit="abc", level="error", path=None, message="boom",
                ),
            ],
        )
        fn = get_formatter("json", FormatterKind.COMPAT_HISTORY)
        payload = json.loads(fn(report, FormatterContext(subcommand="compat-history")))
        assert payload["diagnostics"] == [
            {"commit": "abc", "level": "error", "path": None, "message": "boom"},
        ]


# ---------------------------------------------------------------------------
# BISECT — formatter output matches legacy CLI rendering
# ---------------------------------------------------------------------------


class TestBisectFormatters:
    def test_bisect_human_no_break(self) -> None:
        report = BisectReport(
            range_spec="A..B", old_sha="a", new_sha="b",
            breaking_commit=None, commits_walked=4,
        )
        fn = get_formatter("human", FormatterKind.COMPAT_BISECT)
        out = fn(report, FormatterContext(subcommand="compat-bisect"))
        assert out == "# A..B: no break found across 4 commit(s)"

    def test_bisect_human_empty_walk(self) -> None:
        report = BisectReport(
            range_spec="A..B", old_sha="a", new_sha="b",
            breaking_commit=None, commits_walked=0,
        )
        fn = get_formatter("human", FormatterKind.COMPAT_BISECT)
        out = fn(report, FormatterContext(
            subcommand="compat-bisect", proto_file="user.proto",
        ))
        assert out == "# A..B: no commits touch user.proto"

    def test_bisect_human_break_found(self) -> None:
        finding = _make_finding()
        report = BisectReport(
            range_spec="A..B", old_sha="a", new_sha="b",
            breaking_commit="badcommit", commits_walked=3,
            breaking_findings=(finding,),
        )
        fn = get_formatter("human", FormatterKind.COMPAT_BISECT)
        out = fn(report, FormatterContext(subcommand="compat-bisect"))
        assert "first breaking commit: badcommit" in out
        assert "user.email" in out

    def test_bisect_json_shape(self) -> None:
        finding = _make_finding()
        report = BisectReport(
            range_spec="A..B", old_sha="a", new_sha="b",
            breaking_commit="bad", commits_walked=3,
            breaking_findings=(finding,),
            diagnostics=[
                CommitDiagnostic(
                    commit="d", level="error", path=None, message="m",
                ),
            ],
        )
        fn = get_formatter("json", FormatterKind.COMPAT_BISECT)
        payload = json.loads(fn(report, FormatterContext(subcommand="compat-bisect")))
        assert payload["range"] == "A..B"
        assert payload["breaking_commit"] == "bad"
        assert payload["commits_walked"] == 3
        assert payload["findings"][0]["rule_id"] == "field_removed"
        assert payload["diagnostics"][0]["commit"] == "d"
