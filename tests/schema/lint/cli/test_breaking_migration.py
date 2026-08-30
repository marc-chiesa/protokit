"""End-to-end CLI tests for the D5 U3+U4 BREAKING wire-format migration.

D5 U3 widened ``LintRuntimeWarning.rule_id`` from ``str`` to
``str | None`` (R18 BREAKING). U4 introduces the first emission site
that actually populates ``rule_id=None`` end-to-end:
``min_severity_relaxed``.

This file pins the wire-format consequences:

- **JSON output**: ``runtime_warnings[*].rule_id`` is ``null`` (not the
  literal string ``"None"``) for the two CLI-emitted categories.
- **Engine-emitted categories**: ``rule_exception`` and
  ``unloaded_rule`` continue to populate a non-``None`` string at
  every emit site (the type widening was additive — the engine code
  paths did not change).
- **Migration recipe (R18a)**: external code iterating ``w.rule_id``
  as a string (e.g., ``w.rule_id.upper()``) crashes with
  ``AttributeError`` on the new categories. The CHANGELOG
  ``[Unreleased]`` entry from U3 ce:review F-02 documents this; this
  file pins the wire-format contract programmatically so future
  changes don't silently regress the BREAKING surface.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from protokit.schema.lint.cli import main as lint_main


@pytest.fixture
def descriptor_set(bad_naming_descriptor_set: Path) -> Path:
    """Alias the session-scoped conftest fixture for terser test signatures."""
    return bad_naming_descriptor_set


# ---------------------------------------------------------------------------
# CLI-emitted categories: rule_id serializes as JSON null
# ---------------------------------------------------------------------------


class TestCliEmittedCategoriesProduceJsonNull:
    def test_min_severity_relaxed_rule_id_is_null(
        self, descriptor_set: Path,
    ) -> None:
        """`min_severity_relaxed` runtime warning: JSON `rule_id`
        is `null` — not the string `"None"`, not the literal Python
        `None` repr, not omitted from the dict.
        """
        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--min-severity", "info",
                "--format", "json",
                str(descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        parsed = json.loads(result.stdout)
        relax = [
            w for w in parsed["runtime_warnings"]
            if w["category"] == "min_severity_relaxed"
        ]
        assert len(relax) == 1
        # The KEY is present in the dict (not omitted):
        assert "rule_id" in relax[0]
        # The VALUE is JSON null (Python None after parse) — not the
        # string "None", not the string "null":
        assert relax[0]["rule_id"] is None
        # Belt-and-suspenders: re-read the raw JSON text to verify
        # the serializer emitted the bare token `null` (not `"None"`
        # or `"null"` as a string).
        assert "\"rule_id\": null" in result.stdout

    def test_all_files_excluded_rule_id_is_null(
        self, descriptor_set: Path,
    ) -> None:
        """`all_files_excluded` runtime warning: same contract."""
        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--exclude", "**/*",
                "--format", "json",
                str(descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        parsed = json.loads(result.stdout)
        afe = [
            w for w in parsed["runtime_warnings"]
            if w["category"] == "all_files_excluded"
        ]
        assert len(afe) == 1
        assert "rule_id" in afe[0]
        assert afe[0]["rule_id"] is None
        assert "\"rule_id\": null" in result.stdout


# ---------------------------------------------------------------------------
# Engine-emitted categories: rule_id retains a string (no regression)
# ---------------------------------------------------------------------------


class TestEngineEmittedCategoriesRetainStringRuleId:
    def test_rule_exception_rule_id_is_non_null_string(
        self, descriptor_set: Path,
    ) -> None:
        """`rule_exception` warning: the engine populates rule_id with
        the offending rule's id (non-`None` string). The R18 widening
        was additive — engine-emitted categories did NOT change emit
        behavior, only the type annotation.

        The `pack_rule_raises` fixture's rule fires on FIELD elements;
        ``bad_naming_descriptor_set`` carries three fields, so the
        rule fires multiple times. The assertion only requires one.
        """
        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--rule-pack",
                "tests.schema.lint.cli.user_packs.pack_rule_raises",
                "--format", "json",
                str(descriptor_set),
            ],
        )
        # V33 (0.15.1): a crashed rule now exits 2; the JSON payload
        # is rendered before the gate fires.
        assert result.exit_code == 2, result.output
        parsed = json.loads(result.stdout)
        rule_exc = [
            w for w in parsed["runtime_warnings"]
            if w["category"] == "rule_exception"
        ]
        assert len(rule_exc) >= 1, parsed["runtime_warnings"]
        for w in rule_exc:
            assert isinstance(w["rule_id"], str)
            assert w["rule_id"] != ""
            assert w["rule_id"] is not None


# ---------------------------------------------------------------------------
# Migration recipe: AttributeError on .upper() for new categories
# ---------------------------------------------------------------------------


class TestMigrationRecipe:
    def test_external_code_iterating_rule_id_as_string_breaks(
        self, descriptor_set: Path,
    ) -> None:
        """Document the R18a migration recipe contractually:
        external code that previously assumed `rule_id: str` will
        crash with `AttributeError` on the new categories.

        This is the WHOLE POINT of the BREAKING marker in CHANGELOG.
        The test pins the failure mode so future "fix" attempts to
        silently re-narrow `rule_id` would also break this test —
        forcing a conscious revisit of the migration plan.
        """
        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--min-severity", "info",
                "--format", "json",
                str(descriptor_set),
            ],
        )
        parsed = json.loads(result.stdout)
        relax = next(
            w for w in parsed["runtime_warnings"]
            if w["category"] == "min_severity_relaxed"
        )
        # Pre-U3 consumer code: `w.rule_id.upper()`:
        with pytest.raises(AttributeError) as exc_info:
            relax["rule_id"].upper()  # type: ignore[union-attr]
        # The specific AttributeError shape ("'NoneType' object has
        # no attribute 'upper'") is part of the migration contract —
        # documented in the CHANGELOG migration recipe.
        assert "NoneType" in str(exc_info.value)
        assert "upper" in str(exc_info.value)
