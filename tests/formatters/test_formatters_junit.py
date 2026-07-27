"""Tests for the built-in JUnit formatters.

Covers all four kinds (DIFF binary-result + per-finding for the
three compat kinds), edge cases (empty results, warning-only,
escaping, control-char scrubbing), and end-to-end xsd
validation against the vendored Apache Ant JUnit schema.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import xmlschema

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

from protokit.formatters import (
    FormatterContext,
    FormatterKind,
    _junit_xml as junit_xml,
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


def _build_map_msg_class(pool: descriptor_pool.DescriptorPool) -> type:
    """Build a ``map<string, string> labels`` message.

    Map keys are the one slot where arbitrary user string data
    lands *raw* in a rendered FieldPath (``labels["…"]``), so this
    is the vector that carries hostile code points into JUnit
    output. Scalar field *values* are rendered with ``{!r}`` by
    ``_difference_line`` and are therefore already escaped.
    """
    fdp = descriptor_pb2.FileDescriptorProto()
    fdp.name = "junit_map_test.proto"
    fdp.syntax = "proto3"
    msg = fdp.message_type.add()
    msg.name = "Labelled"
    entry = msg.nested_type.add()
    entry.name = "LabelsEntry"
    entry.options.map_entry = True
    for name, number in (("key", 1), ("value", 2)):
        fld = entry.field.add()
        fld.name = name
        fld.number = number
        fld.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING
        fld.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    fld = msg.field.add()
    fld.name = "labels"
    fld.number = 1
    fld.type = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
    fld.label = descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED
    fld.type_name = ".Labelled.LabelsEntry"
    pool.Add(fdp)
    return message_factory.GetMessageClass(
        pool.FindMessageTypeByName("Labelled"),
    )


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

    @pytest.mark.parametrize(
        ("label", "bad_char"),
        [("noncharacter-fffe", "￾"), ("noncharacter-ffff", "￿")],
    )
    def test_map_key_noncharacter_stays_well_formed(
        self,
        junit_validator: xmlschema.XMLSchema,
        label: str,
        bad_char: str,
    ) -> None:
        # A map key lands RAW inside the rendered FieldPath
        # (``labels["k￿"]``), which becomes the <failure>
        # body. U+FFFE / U+FFFF are valid UTF-8 and legal protobuf
        # string content but are NOT XML 1.0 Chars, so before the
        # sanitizer covered them ``protokit diff --format junit``
        # emitted a document every XML consumer rejects.
        del label
        pool = descriptor_pool.DescriptorPool()
        cls = _build_map_msg_class(pool)
        key = f"k{bad_char}"
        left, right = cls(), cls()
        left.labels[key] = "a"
        right.labels[key] = "b"
        result = MessageDifferencer().compare(left, right)
        fn = get_formatter("junit", FormatterKind.DIFF)
        out = fn(result, FormatterContext(subcommand="diff"))
        _validate(junit_validator, out)
        body = ET.fromstring(out).find(".//failure").text or ""
        assert bad_char not in body
        # The surrounding path detail survives — only the
        # ill-formed code point is dropped.
        assert 'labels["k"]' in body


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
# XML 1.0 ill-formed code points (beyond the ASCII control range)
# ---------------------------------------------------------------------------


#: Code points outside XML 1.0's ``Char`` production. The spec's
#: ``Char`` is ``#x9 | #xA | #xD | [#x20-#xD7FF] | [#xE000-#xFFFD] |
#: [#x10000-#x10FFFF]``; everything below is excluded and makes a
#: document non-well-formed, not merely "discouraged".
_ILL_FORMED = [
    pytest.param("\x01", id="ascii-control"),
    pytest.param("\ud800", id="lone-high-surrogate"),
    pytest.param("\udfff", id="lone-low-surrogate"),
    pytest.param("￾", id="noncharacter-fffe"),
    pytest.param("￿", id="noncharacter-ffff"),
]


class TestIllFormedCodePoints:
    """Every caller-supplied slot must survive non-``Char`` input.

    ASCII controls were already covered; surrogates and the BMP
    noncharacters were not, and both reach output through real
    data (map keys, undecodable filenames on Linux).
    """

    @pytest.mark.parametrize("bad", _ILL_FORMED)
    def test_xml_safe_text_strips(self, bad: str) -> None:
        assert junit_xml.xml_safe_text(f"a{bad}b") == "ab"

    @pytest.mark.parametrize("bad", _ILL_FORMED)
    def test_attribute_and_text_slots_stay_parseable(
        self, junit_validator: xmlschema.XMLSchema, bad: str,
    ) -> None:
        suite = junit_xml.make_testsuite(
            name=f"suite{bad}", tests=1, failures=1, errors=0,
        )
        case = junit_xml.make_testcase(
            classname=f"cls{bad}", name=f"case{bad}",
        )
        junit_xml.append_failure(
            case, message=f"msg{bad}", type_=f"type{bad}", body=f"body{bad}",
        )
        junit_xml.add_testcase(suite, case)
        junit_xml.append_system_out(suite, f"out{bad}")
        junit_xml.append_properties(suite, {f"k{bad}": f"v{bad}"})
        out = junit_xml.serialize(suite)
        _validate(junit_validator, out)
        assert bad not in out

    @pytest.mark.parametrize("bad", _ILL_FORMED)
    def test_timing_and_host_slots_stay_parseable(
        self, bad: str,
    ) -> None:
        # timestamp / hostname / time have deterministic defaults but
        # are caller-settable, so they are caller-supplied slots like
        # any other and must route through the sanitizer too. (Not
        # xsd-validated here: the xsd constrains timestamp's lexical
        # form, and this asserts only well-formedness.)
        suite = junit_xml.make_testsuite(
            name="s", tests=1, failures=0, errors=0,
            timestamp=f"1970-01-01T00:00:00{bad}",
            hostname=f"host{bad}",
            time=f"0{bad}",
        )
        junit_xml.add_testcase(
            suite, junit_xml.make_testcase(
                classname="c", name="n", time=f"0{bad}",
            ),
        )
        out = junit_xml.serialize(suite)
        ET.fromstring(out)
        assert bad not in out

    @pytest.mark.parametrize("bad", _ILL_FORMED)
    def test_history_suite_name_stays_parseable(
        self, bad: str,
    ) -> None:
        # history_junit overwrites the suite ``name`` attribute
        # AFTER make_testsuite sanitized it, embedding the
        # user-supplied ``--type`` verbatim — a bypass of the
        # single choke point.
        report = HistoryReport(
            range_spec="r", old_sha="a", new_sha="b", commits_walked=1,
            entries=[HistoryEntry(
                commit_sha="abc", parent_sha="x", commit_subject="s",
                report=CompatibilityReport(level=CompatibilityLevel.STRICT),
            )],
        )
        fn = get_formatter("junit", FormatterKind.COMPAT_HISTORY)
        out = fn(report, FormatterContext(
            subcommand="compat-history", target_type=f"acme.User{bad}",
        ))
        ET.fromstring(out)
        assert bad not in out

    def test_plane_noncharacters_are_preserved(self) -> None:
        # U+1FFFE and friends are "discouraged" by the spec but ARE
        # inside ``Char`` ([#x10000-#x10FFFF]), so they are
        # well-formed. Dropping them would lose real user data for
        # no correctness gain — the sanitizer's contract is
        # well-formedness, not the discouraged-set.
        text = "a\U0001fffeb"
        assert junit_xml.xml_safe_text(text) == text
        case = junit_xml.make_testcase(classname="c", name=text)
        ET.fromstring(junit_xml.serialize(case))


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
