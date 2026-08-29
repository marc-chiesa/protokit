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
``tests/message/test_cli.py`` and ``tests/schema/test_cli.py``.
"""

from __future__ import annotations

import dataclasses
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import xmlschema
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

from protokit.formatters import (
    FormatterContext,
    FormatterKind,
    get_formatter,
)
from protokit.message import MessageDifferencer
from protokit.message.model import Diagnostic, DiffResult
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


class TestDiffJunitErrorDiagnostics:
    """An error-level diagnostic must not render as a clean pass.

    ``Diagnostic``'s own contract says an ``"error"`` means the tool
    itself broke and "CI callers should treat any ``error`` as a
    fail-closed condition **even if the filtered findings list is
    empty**". ``diff_junit`` hard-coded ``errors=0`` and piped only
    ``result.warnings`` into ``<system-out>``, so ``result.errors``
    reached no output at all: a plugin crash or hook exception during a
    comparison that found no differences produced
    ``tests=1 failures=0 errors=0`` and a green CI job.
    """

    @staticmethod
    def _equal_result_with_error() -> DiffResult:
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        result = MessageDifferencer().compare(cls(name="A"), cls(name="A"))
        assert not result.has_changes()
        return dataclasses.replace(
            result,
            diagnostics=(
                Diagnostic(level="error", path=None, message="plugin exploded"),
            ),
        )

    def test_error_diagnostic_is_counted_and_rendered(self) -> None:
        fn = get_formatter("junit", FormatterKind.DIFF)
        out = fn(self._equal_result_with_error(), FormatterContext(subcommand="diff"))
        root = ET.fromstring(out)
        assert root.get("errors") == "1", "error diagnostic not counted in the suite"
        assert "plugin exploded" in out, "error diagnostic text absent from the output"

    def test_warning_only_result_still_reports_zero_errors(self) -> None:
        """The existing warning path must keep its current shape."""
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        base = MessageDifferencer().compare(cls(name="A"), cls(name="A"))
        result = dataclasses.replace(
            base,
            diagnostics=(Diagnostic(level="warning", path=None, message="heads up"),),
        )
        fn = get_formatter("junit", FormatterKind.DIFF)
        out = fn(result, FormatterContext(subcommand="diff"))
        root = ET.fromstring(out)
        assert root.get("errors") == "0"
        assert "heads up" in out


class TestDiffJunitSchemaValidity:
    """The JUnit document must satisfy the vendored Apache Ant xsd.

    ``<testcase>``'s content model is ``<xs:choice minOccurs="0">`` over
    ``skipped | error | failure`` — at most ONE of them. Putting the error
    diagnostic on the same testcase as the failure emitted two children, so
    the differing-messages-plus-error case produced a document strict JUnit
    consumers reject. Several CI systems report an unparseable report as "no
    test results found" — the same blank/green outcome the error-diagnostic
    fix set out to eliminate, reintroduced through a different door.

    Every sibling formatter already avoids this by giving each error
    diagnostic its own testcase (``_builtin_compat``, ``_builtin_bisect``,
    ``_builtin_lint``).
    """

    @staticmethod
    def _validator() -> xmlschema.XMLSchema:
        return xmlschema.XMLSchema(
            str(Path(__file__).parent.parent / "fixtures" / "junit-xml" / "JUnit.xsd")
        )

    @staticmethod
    def _result(*, differing: bool, error: bool) -> DiffResult:
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        right = cls(name="B") if differing else cls(name="A")
        base = MessageDifferencer().compare(cls(name="A"), right)
        assert base.has_changes() is differing
        if not error:
            return base
        return dataclasses.replace(
            base,
            diagnostics=(
                Diagnostic(level="error", path=None, message="plugin exploded"),
            ),
        )

    @pytest.mark.parametrize(
        ("differing", "error"),
        [(False, False), (True, False), (False, True), (True, True)],
    )
    def test_every_failure_error_combination_is_schema_valid(
        self, differing: bool, error: bool
    ) -> None:
        fn = get_formatter("junit", FormatterKind.DIFF)
        out = fn(
            self._result(differing=differing, error=error),
            FormatterContext(subcommand="diff"),
        )
        ET.fromstring(out)  # well-formed
        self._validator().validate(out)  # ...and schema-valid

    def test_failure_and_error_land_on_separate_testcases(self) -> None:
        fn = get_formatter("junit", FormatterKind.DIFF)
        out = fn(
            self._result(differing=True, error=True),
            FormatterContext(subcommand="diff"),
        )
        root = ET.fromstring(out)
        cases = root.findall("testcase")
        assert len(cases) == 2, "failure and error must not share one testcase"
        assert sum(len(c.findall("failure")) for c in cases) == 1
        assert sum(len(c.findall("error")) for c in cases) == 1
        assert all(
            len(c.findall("failure")) + len(c.findall("error")) <= 1 for c in cases
        )

    def test_suite_counts_do_not_double_count_one_testcase(self) -> None:
        """``tests`` must cover every case, so ``tests - failures - errors >= 0``.

        Aggregators that derive a pass count that way (GitLab, some Jenkins
        renderers) got -1 when one testcase carried both.
        """
        fn = get_formatter("junit", FormatterKind.DIFF)
        out = fn(
            self._result(differing=True, error=True),
            FormatterContext(subcommand="diff"),
        )
        root = ET.fromstring(out)
        tests = int(root.get("tests") or 0)
        failures = int(root.get("failures") or 0)
        errors = int(root.get("errors") or 0)
        assert failures == 1 and errors == 1
        assert tests - failures - errors >= 0, f"{tests=} {failures=} {errors=}"


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
