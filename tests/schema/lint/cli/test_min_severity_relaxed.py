"""End-to-end CLI tests for the `min_severity_relaxed` runtime warning (D5 U4).

Covers:

- **Happy path (3 source branches)**: CLI-source, pyproject-source,
  and "both" (CLI overrides while pyproject also set min_severity).
  Each produces the corresponding R20 message template per
  ``ResolvedLintConfig.relaxation_message``.
- **No-relaxation edge cases**: pyproject relaxes but CLI restores
  → no warning; profile floor at lowest level → no relaxation
  possible.
- **Co-emission with `all_files_excluded`**: when both CLI-emitted
  warnings fire in the same invocation, the alphabetical ordering
  contract (KTD-4: `all_files_excluded` < `min_severity_relaxed`)
  is preserved in `runtime_warnings`.
- **BREAKING contract**: the new category produces `rule_id=null`
  in JSON output (R18 widening verified end-to-end).

All assertions inspect the lint_json formatter's `runtime_warnings`
array — D5 U4 removed the previous stderr `warning[lint-runtime]:`
loop in favor of formatter-side rendering.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from protokit.schema.lint.cli import main as lint_main
from tests.schema.lint.cli._helpers import first_warning_by_category


# The session-scoped ``bad_naming_descriptor_set`` fixture from
# ``tests/schema/lint/cli/conftest.py`` aliased to ``descriptor_set``
# at module scope to keep test methods terse.
@pytest.fixture
def descriptor_set(bad_naming_descriptor_set: Path) -> Path:
    return bad_naming_descriptor_set


def _relaxation_warning(stdout: str) -> dict[str, Any] | None:
    return first_warning_by_category(stdout, "min_severity_relaxed")


# ---------------------------------------------------------------------------
# Happy path: three R20 source branches
# ---------------------------------------------------------------------------


class TestR20SourceBranches:
    def test_cli_source_only(self, descriptor_set: Path) -> None:
        """CLI `--min-severity=info` against profile floor WARNING:
        message names ``--min-severity=info`` only.
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
        w = _relaxation_warning(result.stdout)
        assert w is not None, result.stdout
        msg = w["message"]
        assert msg.startswith("--min-severity=info ")
        assert "[tool.protokit.lint]" not in msg
        assert "relaxes profile floor from warning to info" in msg
        assert w["rule_id"] is None
        assert w["exception_type"] is None
        assert w["descriptor_path"] is None

    def test_pyproject_source_only(
        self, tmp_path: Path, descriptor_set: Path,
    ) -> None:
        """pyproject `min_severity = "info"` with no CLI flag:
        message names ``[tool.protokit.lint] min_severity=info`` only.
        """
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            "[tool.protokit.lint]\nmin_severity = \"info\"\n",
        )
        result = CliRunner().invoke(
            lint_main,
            [
                "--config", str(pyproject),
                "--format", "json",
                str(descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        w = _relaxation_warning(result.stdout)
        assert w is not None, result.stdout
        msg = w["message"]
        assert msg.startswith("[tool.protokit.lint] min_severity=info ")
        assert "--min-severity=" not in msg
        assert "relaxes profile floor from warning to info" in msg

    def test_both_branch_cli_with_pyproject_retained(
        self, tmp_path: Path, descriptor_set: Path,
    ) -> None:
        """CLI `--min-severity=info` + pyproject
        `min_severity = "warning"`: CLI wins for the effective value
        but the message names BOTH sources via the
        "(overriding pyproject min_severity=...)" suffix.
        """
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            "[tool.protokit.lint]\nmin_severity = \"warning\"\n",
        )
        result = CliRunner().invoke(
            lint_main,
            [
                "--config", str(pyproject),
                "--min-severity", "info",
                "--format", "json",
                str(descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        w = _relaxation_warning(result.stdout)
        assert w is not None, result.stdout
        msg = w["message"]
        # Leading CLI attribution + trailing pyproject suffix:
        assert msg.startswith("--min-severity=info ")
        assert "(overriding pyproject min_severity=warning)" in msg


# ---------------------------------------------------------------------------
# No-relaxation edge cases
# ---------------------------------------------------------------------------


class TestNoRelaxation:
    def test_pyproject_relaxes_cli_restores_no_warning(
        self, tmp_path: Path, descriptor_set: Path,
    ) -> None:
        """pyproject relaxes to info, CLI restores to warning:
        resolved.min_severity == composed_floor, NO warning fires.
        """
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            "[tool.protokit.lint]\nmin_severity = \"info\"\n",
        )
        result = CliRunner().invoke(
            lint_main,
            [
                "--config", str(pyproject),
                "--min-severity", "warning",
                "--format", "json",
                str(descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        assert _relaxation_warning(result.stdout) is None

    def test_override_equals_floor_no_warning(
        self, descriptor_set: Path,
    ) -> None:
        """`--min-severity=warning` against profile floor WARNING:
        the override matches the floor exactly (no actual relaxation),
        so no warning fires.
        """
        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--min-severity", "warning",
                "--format", "json",
                str(descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        assert _relaxation_warning(result.stdout) is None

    def test_override_stricter_than_floor_no_warning(
        self, descriptor_set: Path,
    ) -> None:
        """`--min-severity=error` against profile floor WARNING:
        the override is STRICTER (not a relaxation), no warning fires.
        """
        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--min-severity", "error",
                "--format", "json",
                str(descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        assert _relaxation_warning(result.stdout) is None


# ---------------------------------------------------------------------------
# Co-emission with all_files_excluded (KTD-4 alphabetical ordering)
# ---------------------------------------------------------------------------


class TestCoEmissionWithAllFilesExcluded:
    def test_both_fire_alphabetical_ordering(
        self, descriptor_set: Path,
    ) -> None:
        """When both CLI-emitted warnings fire (all_files_excluded AND
        min_severity_relaxed), the alphabetical ordering contract per
        KTD-4 is preserved: all_files_excluded comes before
        min_severity_relaxed in the runtime_warnings array.
        """
        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--exclude", "**/*",
                "--min-severity", "info",
                "--format", "json",
                str(descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        parsed = json.loads(result.stdout)
        categories = [
            w["category"] for w in parsed["runtime_warnings"]
        ]
        # Both CLI-emitted categories present:
        assert "all_files_excluded" in categories
        assert "min_severity_relaxed" in categories
        # KTD-4 alphabetical ordering: all_files_excluded BEFORE
        # min_severity_relaxed (alphabetically a < m).
        idx_all = categories.index("all_files_excluded")
        idx_relax = categories.index("min_severity_relaxed")
        assert idx_all < idx_relax, categories
        # Findings are empty (engine.run was short-circuited):
        assert parsed["findings"] == []
        # Both warnings carry rule_id=null per R18 BREAKING:
        for w in parsed["runtime_warnings"]:
            if w["category"] in (
                "all_files_excluded", "min_severity_relaxed",
            ):
                assert w["rule_id"] is None
