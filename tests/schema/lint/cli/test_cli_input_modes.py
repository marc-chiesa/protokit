"""U2 tests for ``protokit lint`` input modes + helper edge cases.

Covers descriptor-set mode, ``--proto`` source mode,
multi-path dedup, and the four input-side error codes
(``bad-input``, ``pool-conflict``, ``missing-imports``,
``compile-failed``). U3 adds rule-loading flag tests; U4a adds
gating + format flag tests; U4b adds machine-formatter tests.
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from protokit.cli import main as protokit_main
from protokit.schema.lint.cli import main as lint_main

# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


class TestHappyPaths:
    def test_clean_descriptor_set_exits_0(
        self, clean_descriptor_set: Path,
    ) -> None:
        """Demonstrates KD-10 invariant 1 (canary-clean → 0 or 1, never 2)."""
        result = CliRunner().invoke(lint_main, [str(clean_descriptor_set)])
        assert result.exit_code == 0, result.output
        # lint_human returns empty string for no-findings, no-diagnostics —
        # click.echo of empty string is suppressed in the CLI wiring.
        assert result.output == ""

    def test_bad_naming_descriptor_set_renders_findings(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        result = CliRunner().invoke(
            lint_main, [str(bad_naming_descriptor_set)],
        )
        # Exit 0 in U2 (R20 ladder is U4a's job; U2 just runs).
        # Per KD-10 invariant 1, exit 0 is acceptable here.
        assert result.exit_code == 0, result.output
        # Both bad fields fire:
        assert "BadCamelCase" in result.output
        assert "with__double" in result.output
        # The good field does NOT fire:
        assert "good_field_name" not in result.output
        # Rule_id appears in the rendered line.
        assert "naming/snake-case-fields" in result.output

    def test_proto_source_mode(
        self, fixtures_proto_dir: Path,
    ) -> None:
        clean_proto = fixtures_proto_dir / "clean.proto"
        result = CliRunner().invoke(
            lint_main,
            [
                "--proto",
                str(clean_proto),
                "-I", str(fixtures_proto_dir),
            ],
        )
        assert result.exit_code == 0, result.output
        assert result.output == ""

    def test_multi_path_descriptor_set_dedupes_first_wins(
        self, clean_descriptor_set: Path,
    ) -> None:
        # Pass the same descriptor_set twice → second occurrence's
        # fd.name matches seen_names → emit duplicate diagnostic.
        # The diagnostic appears in lint_human output as a
        # `diagnostic[same_basename_collision]: ...` line.
        result = CliRunner().invoke(
            lint_main,
            [str(clean_descriptor_set), str(clean_descriptor_set)],
        )
        assert result.exit_code == 0, result.output
        assert "diagnostic[same_basename_collision]" in result.output
        assert "deduplicated duplicate file path" in result.output


# ---------------------------------------------------------------------------
# Click usage errors (click-owned `Usage:` / `Error:` prefix; exit 2)
# ---------------------------------------------------------------------------


class TestClickUsageErrors:
    def test_zero_positional_args_is_click_usage_error(self) -> None:
        result = CliRunner().invoke(lint_main, [])
        assert result.exit_code == 2
        # Click-owned prefix; NOT lint stable prefix.
        assert "Usage:" in result.output
        assert "error[lint-" not in result.output

    def test_nonexistent_path_is_click_usage_error(self) -> None:
        result = CliRunner().invoke(lint_main, ["/no/such/file.descriptor_set"])
        assert result.exit_code == 2
        assert "Usage:" in result.output

    def test_proto_flag_without_positional_args_is_click_usage_error(
        self,
    ) -> None:
        result = CliRunner().invoke(lint_main, ["--proto"])
        assert result.exit_code == 2
        assert "Usage:" in result.output


# ---------------------------------------------------------------------------
# Stable error-prefix codes (R20a)
# ---------------------------------------------------------------------------


class TestErrorCodes:
    def test_malformed_bytes_routes_to_bad_input(
        self, tmp_path: Path,
    ) -> None:
        bad = tmp_path / "not_a_descriptor_set.descriptor_set"
        bad.write_bytes(b"this is not a FileDescriptorSet")
        result = CliRunner().invoke(lint_main, [str(bad)])
        assert result.exit_code == 2
        assert "error[lint-bad-input]:" in result.output
        # Path is part of the message body.
        assert str(bad) in result.output

    def test_cross_set_symbol_collision_routes_to_pool_conflict(
        self,
        pool_conflict_a_descriptor_set: Path,
        pool_conflict_b_descriptor_set: Path,
    ) -> None:
        result = CliRunner().invoke(
            lint_main,
            [
                str(pool_conflict_a_descriptor_set),
                str(pool_conflict_b_descriptor_set),
            ],
        )
        assert result.exit_code == 2
        assert "error[lint-pool-conflict]:" in result.output
        # The duplicate-symbol marker should appear in the message body.
        assert "duplicate symbol" in result.output.lower() or (
            "Item" in result.output
        )

    def test_missing_imports_routes_to_missing_imports(
        self, missing_imports_descriptor_set: Path,
    ) -> None:
        result = CliRunner().invoke(
            lint_main, [str(missing_imports_descriptor_set)],
        )
        assert result.exit_code == 2
        assert "error[lint-missing-imports]:" in result.output
        # User-actionable hint appears in the message body.
        assert "include_imports" in result.output

    def test_proto_mode_syntax_error_routes_to_compile_failed(
        self, tmp_path: Path,
    ) -> None:
        bad_proto = tmp_path / "syntax_error.proto"
        bad_proto.write_text(
            "syntax = \"proto3\";\n"
            "package broken;\n"
            "this is not valid proto syntax {{{\n"
        )
        result = CliRunner().invoke(
            lint_main,
            ["--proto", str(bad_proto), "-I", str(tmp_path)],
        )
        assert result.exit_code == 2
        assert "error[lint-compile-failed]:" in result.output


# ---------------------------------------------------------------------------
# Cold-import contract (KD-10 invariant 2)
# ---------------------------------------------------------------------------


class TestColdImportContract:
    """KD-10 invariant 2: ``import protokit.schema`` does NOT load lint CLI."""

    def test_protokit_schema_does_not_load_lint_cli(self) -> None:
        # Run in a subprocess so this test isn't polluted by other
        # tests that have already imported the lint CLI.
        import subprocess
        import sys
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import protokit.schema; "
                "import sys; "
                "forbidden = sorted("
                "k for k in sys.modules "
                "if 'protokit.schema.lint.cli' in k "
                "or k == 'protokit.formatters._builtin_lint'); "
                "assert not forbidden, "
                "f'cold-import broken: {forbidden}'; "
                "print('OK')",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"stderr: {result.stderr}\nstdout: {result.stdout}"
        )
        assert "OK" in result.stdout


# ---------------------------------------------------------------------------
# Subcommand discoverability (KD-10 invariant 3)
# ---------------------------------------------------------------------------


class TestDiscoverability:
    def test_lint_appears_in_top_level_help(self) -> None:
        result = CliRunner().invoke(protokit_main, ["--help"])
        assert result.exit_code == 0
        assert "lint" in result.output

    def test_lint_help_renders(self) -> None:
        result = CliRunner().invoke(lint_main, ["--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output
        # Short help phrase from the @click.command decorator.
        assert "schema" in result.output.lower()


# ---------------------------------------------------------------------------
# Regression: existing subcommands still work
# ---------------------------------------------------------------------------


class TestRegressionExistingSubcommands:
    def test_diff_help_unchanged(self) -> None:
        result = CliRunner().invoke(protokit_main, ["diff", "--help"])
        assert result.exit_code == 0

    def test_compat_help_unchanged(self) -> None:
        result = CliRunner().invoke(protokit_main, ["compat", "--help"])
        assert result.exit_code == 0
