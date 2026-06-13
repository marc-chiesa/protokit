"""Integration tests for the formatter system end-to-end through the CLI.

These tests invoke the actual ``protokit diff`` and ``protokit
compat`` Click commands via ``CliRunner``, capture stdout, and
validate the output against the vendored schemas. Where the
formatter unit tests in ``test_formatters_junit.py`` and
``test_formatters_sarif.py`` cover formatter shape in
isolation, these tests cover the whole pipeline:

  CLI args → report construction → context → formatter
  → stdout → schema validation
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import jsonschema
import pytest
import xmlschema
from click.testing import CliRunner

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

from protokit.formatters import clear_user_formatters
from protokit.message.cli import main as diff_main
from protokit.schema.cli import main as compat_main


_JUNIT_XSD = Path(__file__).parent.parent / "fixtures" / "junit-xml" / "JUnit.xsd"
_SARIF_SCHEMA = Path(__file__).parent.parent / "fixtures" / "sarif" / "sarif-2.1.0.json"


@pytest.fixture(scope="module")
def junit_validator() -> xmlschema.XMLSchema:
    return xmlschema.XMLSchema(str(_JUNIT_XSD))


@pytest.fixture(scope="module")
def sarif_validator() -> jsonschema.Draft7Validator:
    with open(_SARIF_SCHEMA) as f:
        return jsonschema.Draft7Validator(json.load(f))


@pytest.fixture(autouse=True)
def _isolate_formatter_registry() -> None:
    clear_user_formatters()
    yield
    clear_user_formatters()


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _write_descriptor_set(path: Path, type_name: str, *, with_email: bool) -> None:
    """Build a small FileDescriptorSet on disk.

    ``with_email=True`` includes a ``string email`` field at
    number 2, in addition to the ``string name`` at number 1.
    Tests use the diff between the two shapes (with/without
    email) to drive a schema-level finding.
    """
    fdp = descriptor_pb2.FileDescriptorProto()
    fdp.name = f"{path.stem}.proto"
    fdp.syntax = "proto3"
    msg = fdp.message_type.add()
    msg.name = type_name
    name_fld = msg.field.add()
    name_fld.name = "name"
    name_fld.number = 1
    name_fld.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING
    name_fld.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    if with_email:
        email_fld = msg.field.add()
        email_fld.name = "email"
        email_fld.number = 2
        email_fld.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING
        email_fld.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    fds = descriptor_pb2.FileDescriptorSet()
    fds.file.append(fdp)
    path.write_bytes(fds.SerializeToString())


def _build_msg_class(pool: descriptor_pool.DescriptorPool) -> type:
    fdp = descriptor_pb2.FileDescriptorProto()
    fdp.name = "intg_diff.proto"
    fdp.syntax = "proto3"
    msg = fdp.message_type.add()
    msg.name = "M"
    fld = msg.field.add()
    fld.name = "name"
    fld.number = 1
    fld.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING
    fld.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    pool.Add(fdp)
    return message_factory.GetMessageClass(pool.FindMessageTypeByName("M"))


# ---------------------------------------------------------------------------
# protokit compat check — JUnit and SARIF round-trip
# ---------------------------------------------------------------------------


class TestCompatCheckIntegration:
    def test_junit_output_validates_via_cli(
        self, junit_validator: xmlschema.XMLSchema, tmp_path: Path,
    ) -> None:
        old = tmp_path / "old.descriptor_set"
        new = tmp_path / "new.descriptor_set"
        _write_descriptor_set(old, "User", with_email=True)
        _write_descriptor_set(new, "User", with_email=False)
        result = CliRunner().invoke(compat_main, [
            "check", str(old), str(new),
            "--type", "User",
            "--level", "consumer-safe",
            "--format", "junit",
        ])
        # Compat findings → exit 1.
        assert result.exit_code == 1
        # Round-trip: parses + xsd-validates.
        ET.fromstring(result.output)
        junit_validator.validate(result.output)
        # The removal shows up as a failure testcase.
        root = ET.fromstring(result.output)
        suite = root if root.tag == "testsuite" else root.find("testsuite")
        assert any(
            c.get("classname") == "field_removed"
            for c in suite.findall("testcase")
        )

    def test_sarif_output_validates_via_cli(
        self, sarif_validator: jsonschema.Draft7Validator, tmp_path: Path,
    ) -> None:
        old = tmp_path / "old.descriptor_set"
        new = tmp_path / "new.descriptor_set"
        _write_descriptor_set(old, "User", with_email=True)
        _write_descriptor_set(new, "User", with_email=False)
        result = CliRunner().invoke(compat_main, [
            "check", str(old), str(new),
            "--type", "User",
            "--level", "consumer-safe",
            "--format", "sarif",
        ])
        assert result.exit_code == 1
        payload = json.loads(result.output)
        errors = list(sarif_validator.iter_errors(payload))
        assert not errors, "\n".join(
            f"{list(e.path)}: {e.message}" for e in errors
        )
        # Result carries the rule id and SARIF level.
        result_obj = payload["runs"][0]["results"][0]
        assert result_obj["ruleId"] == "field_removed"
        assert result_obj["level"] == "error"

    def test_human_format_no_xml_or_json_artifacts(
        self, tmp_path: Path,
    ) -> None:
        old = tmp_path / "old.descriptor_set"
        new = tmp_path / "new.descriptor_set"
        _write_descriptor_set(old, "User", with_email=True)
        _write_descriptor_set(new, "User", with_email=False)
        result = CliRunner().invoke(compat_main, [
            "check", str(old), str(new),
            "--type", "User",
            "--level", "consumer-safe",
            "--format", "human",
        ])
        assert result.exit_code == 1
        # Human output has neither XML prolog nor JSON braces at start.
        assert not result.output.lstrip().startswith("<?xml")
        assert not result.output.lstrip().startswith("{")
        assert "INCOMPATIBLE" in result.output

    def test_quiet_suppresses_all_stdout(self, tmp_path: Path) -> None:
        old = tmp_path / "old.descriptor_set"
        new = tmp_path / "new.descriptor_set"
        _write_descriptor_set(old, "User", with_email=True)
        _write_descriptor_set(new, "User", with_email=False)
        result = CliRunner().invoke(compat_main, [
            "check", str(old), str(new),
            "--type", "User",
            "--quiet",
        ])
        assert result.exit_code == 1
        # --quiet means no stdout. (Diagnostics go to stderr;
        # CliRunner captures them via the same stream by default,
        # so we check that *the rendered report* isn't there.)
        assert "INCOMPATIBLE" not in result.output
        assert "<?xml" not in result.output


# ---------------------------------------------------------------------------
# protokit diff — JUnit binary-result round-trip
# ---------------------------------------------------------------------------


class TestDiffIntegration:
    def test_diff_junit_equal_messages(
        self, junit_validator: xmlschema.XMLSchema, tmp_path: Path,
    ) -> None:
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        left = tmp_path / "a.pb"
        right = tmp_path / "b.pb"
        left.write_bytes(cls(name="A").SerializeToString())
        right.write_bytes(cls(name="A").SerializeToString())
        desc = tmp_path / "schema.descriptor_set"
        _write_descriptor_set(desc, "M", with_email=False)
        result = CliRunner().invoke(diff_main, [
            str(left), str(right),
            "--desc", str(desc), "--message-type", "M",
            "--format", "junit",
        ])
        assert result.exit_code == 0
        junit_validator.validate(result.output)
        root = ET.fromstring(result.output)
        suite = root if root.tag == "testsuite" else root.find("testsuite")
        assert suite.get("name") == "protokit-diff"
        case = suite.find("testcase")
        assert case.get("name") == "messages-equal"
        assert case.find("failure") is None

    def test_diff_junit_unequal_messages(
        self, junit_validator: xmlschema.XMLSchema, tmp_path: Path,
    ) -> None:
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        left = tmp_path / "a.pb"
        right = tmp_path / "b.pb"
        left.write_bytes(cls(name="alice").SerializeToString())
        right.write_bytes(cls(name="bob").SerializeToString())
        desc = tmp_path / "schema.descriptor_set"
        _write_descriptor_set(desc, "M", with_email=False)
        result = CliRunner().invoke(diff_main, [
            str(left), str(right),
            "--desc", str(desc), "--message-type", "M",
            "--format", "junit",
        ])
        assert result.exit_code == 1
        junit_validator.validate(result.output)
        root = ET.fromstring(result.output)
        suite = root if root.tag == "testsuite" else root.find("testsuite")
        case = suite.find("testcase")
        failure = case.find("failure")
        assert failure is not None
        assert "1 difference" in failure.get("message")


# ---------------------------------------------------------------------------
# Smoke test: examples/custom_formatter.py loads via --formatter-module
# ---------------------------------------------------------------------------


class TestExampleFormatterPack:
    def test_examples_custom_formatter_works(self, tmp_path: Path) -> None:
        old = tmp_path / "old.descriptor_set"
        new = tmp_path / "new.descriptor_set"
        _write_descriptor_set(old, "User", with_email=True)
        _write_descriptor_set(new, "User", with_email=False)
        result = CliRunner().invoke(compat_main, [
            "check", str(old), str(new),
            "--type", "User", "--level", "consumer-safe",
            "--formatter-module", "examples.custom_formatter",
            "--format", "slack",
        ])
        assert result.exit_code == 1
        assert "*protokit compat — User*" in result.output
        assert "INCOMPATIBLE" in result.output
        assert "field_removed" in result.output
