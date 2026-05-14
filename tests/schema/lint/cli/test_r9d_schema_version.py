"""D6a U9 R9d — wire-format schema_version tests.

``lint_json`` gains a top-level ``"schema_version": "0.2"`` key.
``lint_sarif`` gains ``runs[].properties.lint_schema_version`` with the
same string value (cross-format-enum-string-parity discipline).
``lint_human`` and ``lint_junit`` deliberately do NOT carry the field —
human is terminal text, junit is the JUnit standard schema without
protokit-specific extensions.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from click.testing import CliRunner

from protokit.schema.lint.cli import main as lint_main

_SCHEMA_VERSION = "0.2"


class TestR9dLintJsonSchemaVersion:
    """``lint_json`` ``schema_version`` top-level key."""

    def test_clean_report_has_schema_version(
        self, clean_descriptor_set: Path,
    ) -> None:
        result = CliRunner().invoke(
            lint_main,
            ["--format", "json", str(clean_descriptor_set)],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["schema_version"] == _SCHEMA_VERSION

    def test_findings_report_has_schema_version(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        result = CliRunner().invoke(
            lint_main,
            ["--format", "json", str(bad_naming_descriptor_set)],
        )
        assert result.exit_code in (0, 1), result.output
        payload = json.loads(result.stdout)
        assert payload["schema_version"] == _SCHEMA_VERSION


class TestR9dLintSarifSchemaVersion:
    """``lint_sarif`` ``runs[].properties.lint_schema_version``."""

    def test_clean_report_has_schema_version_in_properties(
        self, clean_descriptor_set: Path,
    ) -> None:
        result = CliRunner().invoke(
            lint_main,
            ["--format", "sarif", str(clean_descriptor_set)],
        )
        assert result.exit_code == 0, result.output
        doc = json.loads(result.stdout)
        run = doc["runs"][0]
        assert run["properties"]["lint_schema_version"] == _SCHEMA_VERSION

    def test_findings_report_has_schema_version_in_properties(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        result = CliRunner().invoke(
            lint_main,
            ["--format", "sarif", str(bad_naming_descriptor_set)],
        )
        assert result.exit_code in (0, 1), result.output
        doc = json.loads(result.stdout)
        run = doc["runs"][0]
        assert run["properties"]["lint_schema_version"] == _SCHEMA_VERSION

    def test_json_and_sarif_schema_versions_agree(
        self, clean_descriptor_set: Path,
    ) -> None:
        """Cross-format-enum-string-parity: both formatters MUST emit
        the same string value (so downstream consumers don't have to
        per-format-normalize)."""
        json_result = CliRunner().invoke(
            lint_main,
            ["--format", "json", str(clean_descriptor_set)],
        )
        sarif_result = CliRunner().invoke(
            lint_main,
            ["--format", "sarif", str(clean_descriptor_set)],
        )
        assert json_result.exit_code == 0
        assert sarif_result.exit_code == 0
        json_version = json.loads(json_result.stdout)["schema_version"]
        sarif_version = json.loads(sarif_result.stdout)["runs"][0][
            "properties"
        ]["lint_schema_version"]
        assert json_version == sarif_version


class TestR9dPerFormatterScope:
    """``schema_version`` is NOT emitted by ``lint_human`` or ``lint_junit``."""

    def test_lint_human_does_not_emit_schema_version(
        self, clean_descriptor_set: Path,
    ) -> None:
        """Human format is terminal-rendered text not consumed by
        machine parsers; carrying ``schema_version`` there adds no
        value and risks confusing the human reader."""
        result = CliRunner().invoke(
            lint_main,
            ["--format", "human", str(clean_descriptor_set)],
        )
        assert result.exit_code == 0, result.output
        assert "schema_version" not in result.stdout
        assert "schema_version" not in result.stderr

    def test_lint_junit_does_not_emit_schema_version(
        self, clean_descriptor_set: Path,
    ) -> None:
        """JUnit is XML; downstream CI runners consume the JUnit
        standard schema without protokit-specific extensions.
        Adding a vendor namespace is deferred until a concrete
        consumer asks for it (D6b+)."""
        result = CliRunner().invoke(
            lint_main,
            ["--format", "junit", str(clean_descriptor_set)],
        )
        assert result.exit_code == 0, result.output
        # The literal substring is the safest check: any XML element
        # or attribute named ``schema_version`` (or any vendor
        # namespace using ``lint_schema_version``) would match. The
        # current JUnit output emits neither; this test pins that.
        assert "schema_version" not in result.stdout
        # XML parse still succeeds — defense against a regression
        # that silently emits malformed output.
        tree = ET.fromstring(result.stdout)
        assert tree.tag == "testsuite", tree.tag
