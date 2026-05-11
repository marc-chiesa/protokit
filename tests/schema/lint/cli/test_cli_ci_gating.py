"""U4a tests for CI-gating flags and --format resolution.

Covers:
- ``--format`` resolution via formatter registry (R20a
  ``format-unavailable`` exit-2 path).
- ``_run_lint_formatter_safely`` wrapper:
  ``error[lint-formatter-exception]:`` exit-2 path for the four
  formatter contract violations.
- ``--max-warnings`` exit-code ladder (R20).
- ``--statistics`` / ``--no-statistics`` footer rendering.
- ``--quiet`` mutex behavior.
- The R20 exit-code contract: 0 (clean), 1 (ERROR or WARNING > N),
  2 (lint-internal error or formatter exception).

Each section's tests land alongside the matching task in U4a.
``--format=json`` / ``--format=junit`` / ``--format=sarif`` happy
paths land in U4b when the machine formatters register; until then
those values exit 2 via ``lint-format-unavailable``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from protokit.formatters import (
    FormatterKind,
    clear_user_formatters,
    register_formatter,
)
from protokit.schema.lint.cli import main as lint_main


@pytest.fixture(autouse=True)
def _isolate_formatter_registry() -> None:
    """Clear user-registered formatters around every test.

    Built-in lint formatters survive (they're in the reservation
    set); test-only registrations from the cases below are wiped
    so one test's broken formatter doesn't leak into another's
    lookup.
    """
    clear_user_formatters()
    yield
    clear_user_formatters()


class TestFormatFlagResolution:
    """``--format`` resolution and the U4a-introduced
    ``error[lint-format-unavailable]:`` exit-2 path."""

    def test_format_human_explicit(
        self, clean_descriptor_set: Path,
    ) -> None:
        result = CliRunner().invoke(
            lint_main, ["--format", "human", str(clean_descriptor_set)],
        )
        assert result.exit_code == 0, result.output

    def test_format_human_via_envvar(
        self, clean_descriptor_set: Path,
    ) -> None:
        result = CliRunner().invoke(
            lint_main, [str(clean_descriptor_set)],
            env={"PROTOKIT_FORMAT": "human"},
        )
        assert result.exit_code == 0, result.output

    def test_format_json_produces_json_output(
        self, clean_descriptor_set: Path,
    ) -> None:
        """U4b: --format=json now resolves; output is parseable JSON
        with the documented top-level keys."""
        import json

        result = CliRunner().invoke(
            lint_main, ["--format", "json", str(clean_descriptor_set)],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert "findings" in payload
        assert "filtered_count" in payload
        assert "summary" in payload

    def test_format_junit_produces_junit_xml_output(
        self, clean_descriptor_set: Path,
    ) -> None:
        """U4b: --format=junit produces JUnit XML."""
        result = CliRunner().invoke(
            lint_main, ["--format", "junit", str(clean_descriptor_set)],
        )
        assert result.exit_code == 0, result.output
        assert "<testsuite" in result.stdout
        assert 'name="protokit-lint"' in result.stdout

    def test_format_sarif_produces_sarif_2_1_0_output(
        self, clean_descriptor_set: Path,
    ) -> None:
        """U4b: --format=sarif produces SARIF 2.1.0."""
        import json

        result = CliRunner().invoke(
            lint_main, ["--format", "sarif", str(clean_descriptor_set)],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["version"] == "2.1.0"
        assert "runs" in payload

    def test_format_unknown_value(
        self, clean_descriptor_set: Path,
    ) -> None:
        result = CliRunner().invoke(
            lint_main,
            ["--format", "does-not-exist", str(clean_descriptor_set)],
        )
        assert result.exit_code == 2
        assert "error[lint-format-unavailable]:" in result.stderr
        assert "does-not-exist" in result.stderr

    def test_format_unavailable_lists_all_four_available_formats(
        self, clean_descriptor_set: Path,
    ) -> None:
        """Error message must enumerate what IS available. At U4b's
        ship, all four formats (human, json, junit, sarif) are
        registered and must appear in the available list."""
        result = CliRunner().invoke(
            lint_main,
            ["--format", "does-not-exist", str(clean_descriptor_set)],
        )
        assert result.exit_code == 2
        assert "human" in result.stderr
        assert "json" in result.stderr
        assert "junit" in result.stderr
        assert "sarif" in result.stderr

    def test_format_envvar_resolves_json(
        self, clean_descriptor_set: Path,
    ) -> None:
        """PROTOKIT_FORMAT=json (no --format flag) resolves identically."""
        import json

        result = CliRunner().invoke(
            lint_main, [str(clean_descriptor_set)],
            env={"PROTOKIT_FORMAT": "json"},
        )
        assert result.exit_code == 0, result.output
        json.loads(result.stdout)


class TestMachineFormatStatistics:
    """``--statistics`` interaction with machine formats.

    Closes U4a ce:review Cluster B: machine formats embed
    per-severity counts in their structured payload natively, so
    ``--statistics`` is silently redundant rather than emitting an
    advisory. The agent reading JSON gets the counts in
    ``summary.errors`` / ``summary.warnings`` / ``summary.info``;
    no information loss.
    """

    def test_format_json_with_max_warnings_exceeded_exits_1_with_valid_json(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        """R20 ladder applies regardless of format. --format=json
        --max-warnings 0 with WARNINGs produces valid JSON output AND
        exit 1."""
        import json as _json

        result = CliRunner().invoke(
            lint_main,
            [
                "--format", "json",
                "--max-warnings", "0",
                str(bad_naming_descriptor_set),
            ],
        )
        assert result.exit_code == 1
        payload = _json.loads(result.stdout)
        assert payload["summary"]["warnings"] >= 1

    def test_statistics_with_format_json_silently_ignored(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        """--statistics + --format=json: no advisory; counts in JSON."""
        import json

        result = CliRunner().invoke(
            lint_main,
            [
                "--statistics",
                "--format", "json",
                str(bad_naming_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        # No human-format footer leaked into stdout.
        assert "statistics:" not in result.stdout
        # No advisory on stderr — machine formats embed counts natively.
        assert "warning[lint-cli]:" not in result.stderr
        # Counts surface in the JSON payload's summary block.
        payload = json.loads(result.stdout)
        assert "summary" in payload
        assert payload["summary"]["warnings"] >= 1

    def test_statistics_with_format_junit_silently_ignored(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        """--statistics + --format=junit: no advisory; counts in
        the testsuite element's tests/failures attributes."""
        result = CliRunner().invoke(
            lint_main,
            [
                "--statistics",
                "--format", "junit",
                str(bad_naming_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "statistics:" not in result.stdout
        assert "warning[lint-cli]:" not in result.stderr
        # JUnit XML embeds the count in <testsuite ... failures="N">.
        assert "<testsuite" in result.stdout
        assert "failures=" in result.stdout

    def test_statistics_with_format_sarif_silently_ignored(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        """--statistics + --format=sarif: no advisory; counts inferred
        from results[] length in the SARIF payload."""
        import json

        result = CliRunner().invoke(
            lint_main,
            [
                "--statistics",
                "--format", "sarif",
                str(bad_naming_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "statistics:" not in result.stdout
        assert "warning[lint-cli]:" not in result.stderr
        payload = json.loads(result.stdout)
        # SARIF results array carries one entry per finding.
        assert len(payload["runs"][0]["results"]) >= 1


class TestFormatterExceptionWrapper:
    """``_run_lint_formatter_safely`` integration. The four formatter
    contract violations (SystemExit, generic Exception, stdout-leak,
    non-str return) all route through ``error_exit_with_code(
    "formatter-exception", ...)``."""

    def _register(self, name: str, fn: Any) -> None:
        register_formatter(name, fn, kind=FormatterKind.LINT_REPORT)

    def test_formatter_raises_runtime_error(
        self, clean_descriptor_set: Path,
    ) -> None:
        def boom(report: object, ctx: object) -> str:
            raise RuntimeError("synthetic-boom")

        self._register("boom", boom)
        result = CliRunner().invoke(
            lint_main, ["--format", "boom", str(clean_descriptor_set)],
        )
        assert result.exit_code == 2
        assert "error[lint-formatter-exception]:" in result.stderr
        assert "RuntimeError" in result.stderr

    def test_formatter_calls_sys_exit(
        self, clean_descriptor_set: Path,
    ) -> None:
        def evil(report: object, ctx: object) -> str:
            sys.exit(0)

        self._register("evil", evil)
        result = CliRunner().invoke(
            lint_main, ["--format", "evil", str(clean_descriptor_set)],
        )
        assert result.exit_code == 2
        assert "error[lint-formatter-exception]:" in result.stderr
        assert "called sys.exit" in result.stderr

    def test_formatter_writes_to_stdout(
        self, clean_descriptor_set: Path,
    ) -> None:
        def leaky(report: object, ctx: object) -> str:
            sys.stdout.write("leaked")
            return "ok"

        self._register("leaky", leaky)
        result = CliRunner().invoke(
            lint_main, ["--format", "leaky", str(clean_descriptor_set)],
        )
        assert result.exit_code == 2
        assert "error[lint-formatter-exception]:" in result.stderr
        assert "wrote to sys.stdout directly" in result.stderr

    def test_formatter_returns_non_str(
        self, clean_descriptor_set: Path,
    ) -> None:
        def bad(report: object, ctx: object) -> Any:  # noqa: ANN401
            return 42

        self._register("bad", bad)
        result = CliRunner().invoke(
            lint_main, ["--format", "bad", str(clean_descriptor_set)],
        )
        assert result.exit_code == 2
        assert "error[lint-formatter-exception]:" in result.stderr
        assert "returned int" in result.stderr


class TestMaxWarningsExitLadder:
    """R20 exit-code ladder: 0 (clean), 1 (ERROR present OR
    WARNING count > --max-warnings), 2 (lint-internal error).
    ERROR severity always exits 1 regardless of --max-warnings.
    """

    def test_clean_input_exits_0(
        self, clean_descriptor_set: Path,
    ) -> None:
        result = CliRunner().invoke(
            lint_main, [str(clean_descriptor_set)],
        )
        assert result.exit_code == 0, result.output

    def test_warnings_without_max_warnings_flag_still_exits_0(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        """Per R20: exit 1 only fires for WARNINGs when --max-warnings
        is explicitly set. Bare invocation with WARNINGs is exit 0.
        """
        result = CliRunner().invoke(
            lint_main, [str(bad_naming_descriptor_set)],
        )
        assert result.exit_code == 0, result.output
        assert "BadCamelCase" in result.stdout

    def test_warnings_above_max_warnings_threshold_exits_1(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        """bad_naming fires multiple WARNINGs; --max-warnings=0 fails."""
        result = CliRunner().invoke(
            lint_main,
            ["--max-warnings", "0", str(bad_naming_descriptor_set)],
        )
        assert result.exit_code == 1, result.output

    def test_warnings_at_or_below_max_warnings_threshold_exits_0(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        """High threshold passes — fewer WARNINGs than the gate."""
        result = CliRunner().invoke(
            lint_main,
            ["--max-warnings", "100", str(bad_naming_descriptor_set)],
        )
        assert result.exit_code == 0, result.output

    def test_error_severity_finding_exits_1_even_without_max_warnings(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        """ERROR-severity findings always exit 1 — no flag required."""
        result = CliRunner().invoke(
            lint_main,
            [
                "--rule-pack",
                "tests.schema.lint.cli.user_packs.pack_emits_error",
                str(bad_naming_descriptor_set),
            ],
        )
        assert result.exit_code == 1, result.output
        assert "error-pack/always-error" in result.stdout

    def test_max_warnings_negative_is_click_validation_error(
        self, clean_descriptor_set: Path,
    ) -> None:
        result = CliRunner().invoke(
            lint_main,
            ["--max-warnings", "-1", str(clean_descriptor_set)],
        )
        assert result.exit_code == 2
        # Click-owned prefix; NOT lint stable prefix.
        assert "error[lint-" not in result.output

    def test_max_warnings_filters_post_min_severity(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        """--min-severity=error filters WARNINGs from report.findings;
        --max-warnings then sees zero WARNINGs and exits 0 even at 0.
        """
        result = CliRunner().invoke(
            lint_main,
            [
                "--min-severity", "error",
                "--max-warnings", "0",
                str(bad_naming_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output


class TestStatisticsFooter:
    """``--statistics`` opt-in human-format footer with per-severity
    counts, filtered count, and runtime-warning count. Empty rows
    (zero counts) are suppressed."""

    def test_bare_invocation_emits_no_footer(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        """Default-OFF per R16 revised — no statistics line in stdout."""
        result = CliRunner().invoke(
            lint_main, [str(bad_naming_descriptor_set)],
        )
        assert result.exit_code == 0, result.output
        assert "statistics:" not in result.stdout.lower()
        assert "warnings:" not in result.stdout.lower()
        # Findings still rendered.
        assert "BadCamelCase" in result.stdout

    def test_statistics_emits_footer_with_warning_count(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        result = CliRunner().invoke(
            lint_main,
            ["--statistics", str(bad_naming_descriptor_set)],
        )
        assert result.exit_code == 0, result.output
        # Footer contains a recognisable statistics block in stdout.
        assert "statistics:" in result.stdout.lower()
        # WARNING count appears in the footer.
        assert "warning" in result.stdout.lower()

    def test_no_statistics_explicit_opts_out(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        """--no-statistics confirms the default-OFF behavior for
        scripts that want to be explicit about not opting in."""
        result = CliRunner().invoke(
            lint_main,
            ["--no-statistics", str(bad_naming_descriptor_set)],
        )
        assert result.exit_code == 0, result.output
        assert "statistics:" not in result.stdout.lower()

    def test_statistics_on_clean_input_emits_minimal_footer(
        self, clean_descriptor_set: Path,
    ) -> None:
        """All-zero counts → no severity rows, but the footer
        marker should still indicate statistics ran."""
        result = CliRunner().invoke(
            lint_main,
            ["--statistics", str(clean_descriptor_set)],
        )
        assert result.exit_code == 0, result.output
        assert "statistics:" in result.stdout
        # No severity rows because zero findings.
        assert "warning" not in result.stdout.lower()
        assert "error" not in result.stdout.lower()

    def test_statistics_footer_emits_to_stdout_not_stderr(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        """Statistics footer is part of the human format — stdout,
        not stderr."""
        result = CliRunner().invoke(
            lint_main,
            ["--statistics", str(bad_naming_descriptor_set)],
        )
        assert result.exit_code == 0, result.output
        assert "statistics:" in result.stdout.lower()
        assert "statistics:" not in result.stderr.lower()


class TestQuietFlag:
    """``--quiet`` suppresses stdout. Hard mutex with non-human
    format (click validation error). Soft mutex with --statistics
    (stderr advisory; --quiet wins)."""

    def test_quiet_suppresses_findings_stdout(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        result = CliRunner().invoke(
            lint_main, ["--quiet", str(bad_naming_descriptor_set)],
        )
        assert result.exit_code == 0, result.output
        assert result.stdout == ""

    def test_quiet_preserves_findings_exit_code(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        """--quiet still surfaces exit code via R20 ladder."""
        result = CliRunner().invoke(
            lint_main,
            ["--quiet", "--max-warnings", "0",
             str(bad_naming_descriptor_set)],
        )
        assert result.exit_code == 1
        assert result.stdout == ""

    def test_quiet_with_non_human_format_is_click_validation_error(
        self, clean_descriptor_set: Path,
    ) -> None:
        """Hard mutex: --quiet + --format=json is a usage error
        (click-owned 'Usage:' prefix; NOT lint stable prefix).

        D5 U2 F-04: the error message is source-aware. When the
        non-human format comes from the CLI (or PROTOKIT_FORMAT
        envvar), the message names the ``--format=`` flag explicitly
        so users see the offending input. See
        ``test_quiet_with_pyproject_format_names_pyproject_source``
        for the pyproject-source branch.
        """
        result = CliRunner().invoke(
            lint_main,
            ["--quiet", "--format", "json", str(clean_descriptor_set)],
        )
        assert result.exit_code == 2
        # Click usage-error prefix; NOT lint stable prefix.
        assert "error[lint-" not in result.output
        # Source-aware: CLI-source mentions --format= explicitly.
        assert "--format='json'" in result.stderr
        assert "[tool.protokit.lint]" not in result.stderr

    def test_quiet_with_pyproject_format_names_pyproject_source(
        self,
        tmp_path: Path,
        clean_descriptor_set: Path,
    ) -> None:
        """D5 U2 F-04: when --quiet collides with a pyproject-sourced
        non-human format, the mutex error names ``[tool.protokit.lint]
        format=...`` (not ``--format=...``) so users see the actual
        source of the offending value.

        The check moved AFTER ResolvedLintConfig.from_dict in U2
        specifically to catch this pyproject-driven path; the
        source-aware wording closes the agent-grep regression flagged
        by the ce:review.
        """
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            "[tool.protokit.lint]\nformat = \"json\"\n",
        )

        result = CliRunner().invoke(
            lint_main,
            [
                "--config", str(pyproject),
                "--quiet",
                str(clean_descriptor_set),
            ],
        )

        assert result.exit_code == 2
        # Click usage-error prefix; NOT lint stable prefix.
        assert "error[lint-" not in result.output
        # Source-aware: pyproject-source mentions [tool.protokit.lint]
        # format=, NOT --format= (which would be misleading).
        assert "[tool.protokit.lint] format='json'" in result.stderr
        assert "--format=" not in result.stderr

    def test_quiet_with_statistics_emits_advisory_and_quiet_wins(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        """Soft mutex: --quiet --statistics emits a stderr advisory
        and suppresses the footer (quiet wins)."""
        result = CliRunner().invoke(
            lint_main,
            ["--quiet", "--statistics",
             str(bad_naming_descriptor_set)],
        )
        assert result.exit_code == 0, result.output
        assert result.stdout == ""
        # Advisory hits stderr.
        assert "warning[lint-cli]:" in result.stderr
        assert "--quiet" in result.stderr
        assert "--statistics" in result.stderr

    def test_statistics_footer_emits_before_exit_1_on_max_warnings_violation(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        """The footer emits to stdout BEFORE sys.exit(1) fires when
        --max-warnings is exceeded. An agent reading exit 1 + the
        footer can both gate AND see counts in the same invocation."""
        result = CliRunner().invoke(
            lint_main,
            [
                "--statistics",
                "--max-warnings", "0",
                str(bad_naming_descriptor_set),
            ],
        )
        assert result.exit_code == 1
        assert "statistics:" in result.stdout
        assert "warning" in result.stdout.lower()


class TestFormatCaseNormalization:
    """Case normalization for --format / PROTOKIT_FORMAT."""

    def test_format_human_mixed_case_normalizes(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        """--format=Human resolves identically to --format=human:
        statistics gate fires and quiet mutex does NOT fire."""
        result = CliRunner().invoke(
            lint_main,
            ["--format", "Human", "--statistics",
             str(bad_naming_descriptor_set)],
        )
        assert result.exit_code == 0, result.output
        assert "statistics:" in result.stdout

    def test_format_envvar_mixed_case_with_quiet_does_not_misfire(
        self, clean_descriptor_set: Path,
    ) -> None:
        """PROTOKIT_FORMAT=Human + --quiet should NOT raise the
        quiet/non-human mutex — both resolve to human."""
        result = CliRunner().invoke(
            lint_main, ["--quiet", str(clean_descriptor_set)],
            env={"PROTOKIT_FORMAT": "HUMAN"},
        )
        assert result.exit_code == 0, result.output
        assert "--quiet is incompatible" not in result.output

    def test_format_envvar_unknown_value_routes_to_format_unavailable(
        self, clean_descriptor_set: Path,
    ) -> None:
        """PROTOKIT_FORMAT=<unknown> exits 2 via lint-format-unavailable."""
        result = CliRunner().invoke(
            lint_main, [str(clean_descriptor_set)],
            env={"PROTOKIT_FORMAT": "junk-format"},
        )
        assert result.exit_code == 2
        assert "error[lint-format-unavailable]:" in result.stderr
        assert "junk-format" in result.stderr


class TestStatisticsRows:
    """Coverage for filtered: and runtime-warnings: rows in the footer."""

    def test_statistics_emits_filtered_row_when_min_severity_filters_findings(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        """--min-severity=error filters WARNINGs out; the filtered count
        appears in the statistics footer's filtered: row."""
        result = CliRunner().invoke(
            lint_main,
            [
                "--statistics",
                "--min-severity", "error",
                str(bad_naming_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "statistics:" in result.stdout
        assert "filtered:" in result.stdout

    def test_statistics_emits_runtime_warnings_row(
        self, clean_descriptor_set: Path,
    ) -> None:
        """A rule that raises produces a runtime warning; --statistics
        surfaces it in the runtime-warnings: row."""
        result = CliRunner().invoke(
            lint_main,
            [
                "--statistics",
                "--rule-pack",
                "tests.schema.lint.cli.user_packs.pack_rule_raises",
                str(clean_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "statistics:" in result.stdout
        assert "runtime-warnings:" in result.stdout
