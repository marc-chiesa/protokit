"""Tests for the built-in JUnit formatters.

Covers all four kinds (DIFF binary-result + per-finding for the
three compat kinds), edge cases (empty results, warning-only,
escaping, control-char scrubbing), and end-to-end xsd
validation against the vendored Apache Ant JUnit schema.
"""

from __future__ import annotations

import time
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
from protokit.formatters import _junit_xml as junit
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
# Fixtures and helpers
# ---------------------------------------------------------------------------


_JUNIT_XSD = Path(__file__).parent.parent / "fixtures" / "junit-xml" / "JUnit.xsd"


@pytest.fixture(scope="module")
def junit_validator() -> xmlschema.XMLSchema:
    """Vendored Apache Ant JUnit xsd loaded once per module."""
    return xmlschema.XMLSchema(str(_JUNIT_XSD))


def _validate(validator: xmlschema.XMLSchema, xml: str) -> None:
    """Validate an XML string against the vendored xsd.

    The Ant xsd defines two roots: ``<testsuite>`` (singleton) and
    ``<testsuites>`` (aggregating). protokit always emits the
    aggregating root so the validator is asked to validate against
    the inner suite when the doc is a single suite, and against
    ``<testsuites>`` when the doc has multiple suites.
    """
    # Parse first to verify well-formedness independent of schema.
    ET.fromstring(xml)
    # Then schema-validate. xmlschema raises on invalid documents.
    validator.validate(xml)


def _build_msg_class(pool: descriptor_pool.DescriptorPool) -> type:
    fdp = descriptor_pb2.FileDescriptorProto()
    fdp.name = "junit_test.proto"
    fdp.syntax = "proto3"
    msg = fdp.message_type.add()
    msg.name = "Person"
    fld = msg.field.add()
    fld.name = "name"
    fld.number = 1
    fld.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING
    fld.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    pool.Add(fdp)
    return message_factory.GetMessageClass(pool.FindMessageTypeByName("Person"))


def _make_finding(
    *,
    rule_id: str = "field_removed",
    severity: Severity = Severity.SEMANTIC,
    direction: Direction = Direction.BACKWARD,
    path: str = "user.email",
    message: str = "field present in old, absent in new",
) -> Finding:
    from protokit.message.model import FieldPath
    return Finding(
        path=FieldPath.parse(path),
        rule_id=rule_id,
        severity=severity,
        direction=direction,
        message=message,
    )


# ---------------------------------------------------------------------------
# DIFF — binary-result rendering
# ---------------------------------------------------------------------------


class TestDiffJunit:
    def test_equal_messages_pass(
        self, junit_validator: xmlschema.XMLSchema,
    ) -> None:
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        result = MessageDifferencer().compare(cls(name="A"), cls(name="A"))
        fn = get_formatter("junit", FormatterKind.DIFF)
        out = fn(result, FormatterContext(subcommand="diff"))
        _validate(junit_validator, out)
        root = ET.fromstring(out)
        assert root.tag == "testsuite"
        suite = root
        assert suite.get("name") == "protokit-diff"
        assert suite.get("tests") == "1"
        assert suite.get("failures") == "0"
        case = suite.find("testcase")
        assert case.get("name") == "messages-equal"
        assert case.find("failure") is None

    def test_unequal_messages_fail_with_body(
        self, junit_validator: xmlschema.XMLSchema,
    ) -> None:
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        result = MessageDifferencer().compare(cls(name="A"), cls(name="B"))
        fn = get_formatter("junit", FormatterKind.DIFF)
        out = fn(result, FormatterContext(subcommand="diff"))
        _validate(junit_validator, out)
        root = ET.fromstring(out)
        assert root.tag == "testsuite"
        suite = root
        assert suite.get("tests") == "1"
        assert suite.get("failures") == "1"
        case = suite.find("testcase")
        failure = case.find("failure")
        assert failure is not None
        assert "1 difference" in failure.get("message")
        # Body contains the diff line.
        assert "name" in (failure.text or "")

    def test_multiple_differences_in_failure_body(
        self, junit_validator: xmlschema.XMLSchema,
    ) -> None:
        pool = descriptor_pool.DescriptorPool()
        # Build a message with two fields so we get two diffs.
        fdp = descriptor_pb2.FileDescriptorProto()
        fdp.name = "junit_two.proto"
        fdp.syntax = "proto3"
        msg = fdp.message_type.add()
        msg.name = "Two"
        for i, name in enumerate(("a", "b"), start=1):
            fld = msg.field.add()
            fld.name = name
            fld.number = i
            fld.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING
            fld.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
        pool.Add(fdp)
        cls = message_factory.GetMessageClass(pool.FindMessageTypeByName("Two"))
        result = MessageDifferencer().compare(
            cls(a="x", b="y"), cls(a="X", b="Y"),
        )
        fn = get_formatter("junit", FormatterKind.DIFF)
        out = fn(result, FormatterContext(subcommand="diff"))
        _validate(junit_validator, out)
        root = ET.fromstring(out)
        failure = root.find(".//failure")
        assert "2 differences" in failure.get("message")
        body = failure.text or ""
        assert "~ a:" in body
        assert "~ b:" in body


# ---------------------------------------------------------------------------
# COMPAT — per-finding rendering
# ---------------------------------------------------------------------------


class TestCompatJunit:
    def test_compatible_uses_synthetic_passing_testcase(
        self, junit_validator: xmlschema.XMLSchema,
    ) -> None:
        report = CompatibilityReport(level=CompatibilityLevel.STRICT)
        fn = get_formatter("junit", FormatterKind.COMPAT)
        out = fn(report, FormatterContext(
            subcommand="compat-check", target_type="acme.User",
        ))
        _validate(junit_validator, out)
        root = ET.fromstring(out)
        # Compat/bisect: <testsuite> is root. History: <testsuites> wraps.
        suite = root if root.tag == "testsuite" else root.find("testsuite")
        assert suite.get("name") == "protokit-compat-acme.User"
        assert suite.get("tests") == "1"
        assert suite.get("failures") == "0"
        assert suite.get("errors") == "0"
        case = suite.find("testcase")
        assert case.get("name") == "compatible"
        assert case.find("failure") is None

    def test_findings_become_failure_testcases(
        self, junit_validator: xmlschema.XMLSchema,
    ) -> None:
        findings = (
            _make_finding(rule_id="field_removed", path="user.email"),
            _make_finding(
                rule_id="field_added", path="user.nickname",
                severity=Severity.SEMANTIC, direction=Direction.BACKWARD,
                message="new field; old consumers ignore",
            ),
        )
        report = CompatibilityReport(
            level=CompatibilityLevel.STRICT, findings=findings,
        )
        fn = get_formatter("junit", FormatterKind.COMPAT)
        out = fn(report, FormatterContext(
            subcommand="compat-check", target_type="acme.User",
        ))
        _validate(junit_validator, out)
        root = ET.fromstring(out)
        # Compat/bisect: <testsuite> is root. History: <testsuites> wraps.
        suite = root if root.tag == "testsuite" else root.find("testsuite")
        assert suite.get("tests") == "2"
        assert suite.get("failures") == "2"
        cases = suite.findall("testcase")
        assert {c.get("classname") for c in cases} == {
            "field_removed", "field_added",
        }
        for case in cases:
            assert case.find("failure") is not None

    def test_warning_only_uses_synthetic_passing_testcase(
        self, junit_validator: xmlschema.XMLSchema,
    ) -> None:
        # Warning-only counts as empty for the empty-suite rule —
        # warnings don't make testcases.
        report = CompatibilityReport(
            level=CompatibilityLevel.STRICT,
            diagnostics=(Diagnostic(
                level="warning", path=None, message="caveat",
            ),),
        )
        fn = get_formatter("junit", FormatterKind.COMPAT)
        out = fn(report, FormatterContext(subcommand="compat-check"))
        _validate(junit_validator, out)
        root = ET.fromstring(out)
        # Compat/bisect: <testsuite> is root. History: <testsuites> wraps.
        suite = root if root.tag == "testsuite" else root.find("testsuite")
        assert suite.get("tests") == "1"
        assert suite.get("failures") == "0"
        case = suite.find("testcase")
        assert case.get("name") == "compatible"
        # And the warning surfaces as system-out.
        sys_out = suite.find("system-out")
        assert sys_out is not None
        assert "caveat" in (sys_out.text or "")

    def test_error_diagnostic_becomes_error_testcase(
        self, junit_validator: xmlschema.XMLSchema,
    ) -> None:
        report = CompatibilityReport(
            level=CompatibilityLevel.STRICT,
            diagnostics=(Diagnostic(
                level="error", path=None, message="plugin crashed",
            ),),
        )
        fn = get_formatter("junit", FormatterKind.COMPAT)
        out = fn(report, FormatterContext(subcommand="compat-check"))
        _validate(junit_validator, out)
        root = ET.fromstring(out)
        # Compat/bisect: <testsuite> is root. History: <testsuites> wraps.
        suite = root if root.tag == "testsuite" else root.find("testsuite")
        assert suite.get("errors") == "1"
        # Error testcase, NOT the synthetic passing one.
        cases = suite.findall("testcase")
        assert len(cases) == 1
        assert cases[0].get("classname") == "diagnostic"
        assert cases[0].find("error") is not None

    def test_cross_type_suite_name(
        self, junit_validator: xmlschema.XMLSchema,
    ) -> None:
        report = CompatibilityReport(level=CompatibilityLevel.STRICT)
        fn = get_formatter("junit", FormatterKind.COMPAT)
        out = fn(report, FormatterContext(
            subcommand="compat-check",
            old_target_type="acme.UserV1",
            new_target_type="acme.UserV2",
        ))
        _validate(junit_validator, out)
        root = ET.fromstring(out)
        # Compat/bisect: <testsuite> is root. History: <testsuites> wraps.
        suite = root if root.tag == "testsuite" else root.find("testsuite")
        assert suite.get("name") == "protokit-compat-acme.UserV1->acme.UserV2"

    def test_unknown_type_falls_back(
        self, junit_validator: xmlschema.XMLSchema,
    ) -> None:
        report = CompatibilityReport(level=CompatibilityLevel.STRICT)
        fn = get_formatter("junit", FormatterKind.COMPAT)
        out = fn(report, FormatterContext(subcommand="compat-check"))
        _validate(junit_validator, out)
        root = ET.fromstring(out)
        suite = root if root.tag == "testsuite" else root.find("testsuite")
        assert suite.get("name") == "protokit-compat-unknown"

    def test_xml_special_chars_escaped(
        self, junit_validator: xmlschema.XMLSchema,
    ) -> None:
        report = CompatibilityReport(
            level=CompatibilityLevel.STRICT,
            findings=(_make_finding(
                rule_id="custom",
                message='broken "thing" & <stuff>',
            ),),
        )
        fn = get_formatter("junit", FormatterKind.COMPAT)
        out = fn(report, FormatterContext(
            subcommand="compat-check", target_type="acme.User",
        ))
        # Schema-valid AND parseable means escaping was correct.
        _validate(junit_validator, out)
        root = ET.fromstring(out)
        failure = root.find(".//failure")
        # Round-trip preserves the original text content.
        assert "broken" in (failure.text or "")
        assert '"thing"' in (failure.text or "")

    def test_control_chars_scrubbed(
        self, junit_validator: xmlschema.XMLSchema,
    ) -> None:
        # \x01 is forbidden in XML 1.0 and must be stripped.
        report = CompatibilityReport(
            level=CompatibilityLevel.STRICT,
            findings=(_make_finding(message="bad\x01char"),),
        )
        fn = get_formatter("junit", FormatterKind.COMPAT)
        out = fn(report, FormatterContext(
            subcommand="compat-check", target_type="acme.User",
        ))
        _validate(junit_validator, out)
        root = ET.fromstring(out)
        failure = root.find(".//failure")
        assert "\x01" not in (failure.text or "")
        assert "bad" in (failure.text or "")
        assert "char" in (failure.text or "")


# ---------------------------------------------------------------------------
# COMPAT_HISTORY — testsuites root with per-commit suites
# ---------------------------------------------------------------------------


class TestHistoryJunit:
    def test_empty_walk_emits_empty_testsuites(
        self, junit_validator: xmlschema.XMLSchema,
    ) -> None:
        report = HistoryReport(
            range_spec="HEAD~3..HEAD", old_sha="a", new_sha="b",
            commits_walked=0,
        )
        fn = get_formatter("junit", FormatterKind.COMPAT_HISTORY)
        out = fn(report, FormatterContext(subcommand="compat-history"))
        # Empty <testsuites/> is xsd-legal.
        _validate(junit_validator, out)
        root = ET.fromstring(out)
        assert root.tag == "testsuites"
        assert root.find("testsuite") is None

    def test_per_entry_suite_with_package_and_id(
        self, junit_validator: xmlschema.XMLSchema,
    ) -> None:
        clean = CompatibilityReport(level=CompatibilityLevel.STRICT)
        broken = CompatibilityReport(
            level=CompatibilityLevel.STRICT,
            findings=(_make_finding(),),
        )
        report = HistoryReport(
            range_spec="r", old_sha="a", new_sha="b", commits_walked=2,
            entries=[
                HistoryEntry(
                    commit_sha="aaaaaaaaaaaaaaa", parent_sha="x",
                    commit_subject="ok", report=clean,
                ),
                HistoryEntry(
                    commit_sha="bbbbbbbbbbbbbbb", parent_sha="aaaaaaaaaaaaaaa",
                    commit_subject="break", report=broken,
                ),
            ],
        )
        fn = get_formatter("junit", FormatterKind.COMPAT_HISTORY)
        out = fn(report, FormatterContext(
            subcommand="compat-history", target_type="acme.User",
        ))
        _validate(junit_validator, out)
        root = ET.fromstring(out)
        suites = root.findall("testsuite")
        assert len(suites) == 2
        assert suites[0].get("package") == "ok"
        assert suites[0].get("id") == "0"
        assert suites[1].get("package") == "break"
        assert suites[1].get("id") == "1"
        # Suite name carries the type-qualified prefix + short SHA
        # so concurrent multi-type history runs don't collide in
        # CI aggregators that dedupe by suite name (R-CC fix).
        assert suites[0].get("name") == "protokit-compat-acme.User-commit-aaaaaaaaaaaa"

    def test_suite_names_disambiguate_across_types(
        self, junit_validator: xmlschema.XMLSchema,
    ) -> None:
        # Regression for the 2026-04-19 review (ADV-007): two
        # history runs over the same commit range but different
        # --type values used to produce identical "commit-{sha}"
        # suite names. CI aggregators that dedupe by name would
        # silently overwrite one type's findings with the other's.
        # The fix prefixes each suite name with the type-qualified
        # form so they live side-by-side.
        report_user = HistoryReport(
            range_spec="r", old_sha="a", new_sha="b", commits_walked=1,
            entries=[HistoryEntry(
                commit_sha="abc", parent_sha="x", commit_subject="s",
                report=CompatibilityReport(level=CompatibilityLevel.STRICT),
            )],
        )
        fn = get_formatter("junit", FormatterKind.COMPAT_HISTORY)
        out_user = fn(report_user, FormatterContext(
            subcommand="compat-history", target_type="acme.User",
        ))
        out_order = fn(report_user, FormatterContext(
            subcommand="compat-history", target_type="acme.Order",
        ))
        name_user = ET.fromstring(out_user).find("testsuite").get("name")
        name_order = ET.fromstring(out_order).find("testsuite").get("name")
        assert name_user != name_order
        assert "acme.User" in name_user
        assert "acme.Order" in name_order


# ---------------------------------------------------------------------------
# COMPAT_BISECT — single testsuite with properties
# ---------------------------------------------------------------------------


class TestBisectJunit:
    def test_no_break_emits_passing_testcase(
        self, junit_validator: xmlschema.XMLSchema,
    ) -> None:
        report = BisectReport(
            range_spec="A..B", old_sha="a", new_sha="b",
            breaking_commit=None, commits_walked=4,
        )
        fn = get_formatter("junit", FormatterKind.COMPAT_BISECT)
        out = fn(report, FormatterContext(subcommand="compat-bisect"))
        _validate(junit_validator, out)
        root = ET.fromstring(out)
        # Compat/bisect: <testsuite> is root. History: <testsuites> wraps.
        suite = root if root.tag == "testsuite" else root.find("testsuite")
        assert suite.get("tests") == "1"
        assert suite.get("failures") == "0"
        case = suite.find("testcase")
        assert case.get("name") == "no-break"

    def test_empty_walk_emits_no_commits_testcase(
        self, junit_validator: xmlschema.XMLSchema,
    ) -> None:
        report = BisectReport(
            range_spec="A..B", old_sha="a", new_sha="b",
            breaking_commit=None, commits_walked=0,
        )
        fn = get_formatter("junit", FormatterKind.COMPAT_BISECT)
        out = fn(report, FormatterContext(subcommand="compat-bisect"))
        _validate(junit_validator, out)
        root = ET.fromstring(out)
        case = root.find(".//testcase")
        assert case.get("name") == "no-commits"

    def test_breaking_commit_emits_failure_with_properties(
        self, junit_validator: xmlschema.XMLSchema,
    ) -> None:
        finding = _make_finding(rule_id="field_removed")
        report = BisectReport(
            range_spec="A..B", old_sha="aaa", new_sha="bbb",
            breaking_commit="bad999bad", commits_walked=3,
            breaking_findings=(finding,),
        )
        fn = get_formatter("junit", FormatterKind.COMPAT_BISECT)
        out = fn(report, FormatterContext(subcommand="compat-bisect"))
        _validate(junit_validator, out)
        root = ET.fromstring(out)
        # Compat/bisect: <testsuite> is root. History: <testsuites> wraps.
        suite = root if root.tag == "testsuite" else root.find("testsuite")
        assert suite.get("failures") == "1"
        # Properties block carries metadata.
        props = {
            p.get("name"): p.get("value")
            for p in suite.findall("properties/property")
        }
        assert props["range_spec"] == "A..B"
        assert props["old_sha"] == "aaa"
        assert props["new_sha"] == "bbb"
        assert props["breaking_commit"] == "bad999bad"
        assert props["commits_walked"] == "3"
        # Failure body lists the breaking finding.
        failure = root.find(".//failure")
        assert failure.get("type") == "break"
        assert "user.email" in (failure.text or "")

    def test_error_diagnostic_emits_error_testcase(
        self, junit_validator: xmlschema.XMLSchema,
    ) -> None:
        report = BisectReport(
            range_spec="A..B", old_sha="a", new_sha="b",
            breaking_commit=None, commits_walked=2,
            diagnostics=(CommitDiagnostic(
                commit="badcommit", level="error",
                path=None, message="plugin crashed",
            ),),
        )
        fn = get_formatter("junit", FormatterKind.COMPAT_BISECT)
        out = fn(report, FormatterContext(subcommand="compat-bisect"))
        _validate(junit_validator, out)
        root = ET.fromstring(out)
        # Compat/bisect: <testsuite> is root. History: <testsuites> wraps.
        suite = root if root.tag == "testsuite" else root.find("testsuite")
        assert suite.get("errors") == "1"
        # Should not have the synthetic no-break case since we have an error.
        cases = suite.findall("testcase")
        assert len(cases) == 1
        assert cases[0].find("error") is not None


# ---------------------------------------------------------------------------
# add_testcase scaling guard
# ---------------------------------------------------------------------------


class TestAddTestcaseScaling:
    """Suite construction must stay linear in the number of testcases.

    ``add_testcase`` locates the seeded ``<system-out>`` placeholder so
    each case lands before it. A FORWARD scan rescans every previously
    inserted testcase, making a suite of n cases O(n^2) — 20k cases took
    ~4.5s. Nothing is ever appended after ``<system-err>``, so the
    placeholder is always at the tail and a backward scan finds it in
    O(1).
    """

    @staticmethod
    def _median_of_3_s(n: int) -> float:
        """Build an n-case suite 3 times (plus warmup); return median secs."""
        def build() -> None:
            suite = junit.make_testsuite(
                name="scale", tests=n, failures=0, errors=0,
            )
            for i in range(n):
                junit.add_testcase(
                    suite, junit.make_testcase(classname="c", name=f"t{i}"),
                )

        build()  # warmup
        timings = []
        for _ in range(3):
            start = time.perf_counter()
            build()
            timings.append(time.perf_counter() - start)
        timings.sort()
        return timings[1]

    @pytest.mark.slow
    def test_suite_construction_scales_linearly(self) -> None:
        small = self._median_of_3_s(2_000)
        large = self._median_of_3_s(8_000)
        # 4x the cases: linear ~4x, quadratic ~16x. 8x leaves generous
        # headroom for timer noise while still failing a forward scan.
        ratio = large / small if small else float("inf")
        assert ratio < 8.0, (
            f"add_testcase looks superlinear: 2000 cases {small * 1000:.1f}ms, "
            f"8000 cases {large * 1000:.1f}ms (ratio {ratio:.1f}x)"
        )

    def test_cases_precede_system_out(self) -> None:
        # Guards the ordering invariant the fast path relies on.
        suite = junit.make_testsuite(name="s", tests=3, failures=0, errors=0)
        for i in range(3):
            junit.add_testcase(
                suite, junit.make_testcase(classname="c", name=f"t{i}"),
            )
        assert [c.tag for c in suite] == [
            "properties", "testcase", "testcase", "testcase",
            "system-out", "system-err",
        ]
