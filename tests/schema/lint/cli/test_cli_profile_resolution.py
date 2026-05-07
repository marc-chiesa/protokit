"""U3 tests for ``--profile``, ``--min-severity``, R9, R11, R25.

Covers:
- ``--profile`` happy paths (default; user-pack-declared name)
- R11 ``unknown-profile`` loud failure with introspection
- ``--min-severity`` numeric override + relaxation breadcrumb
- R25 multi-pack provenance gating (single-pack silent;
  multi-pack emits)
- Runtime-warning emission to stderr (deferred from U2 review)
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from protokit.schema.lint.cli import main as lint_main

# ---------------------------------------------------------------------------
# --profile happy paths + R11 unknown-profile
# ---------------------------------------------------------------------------


class TestProfileResolution:
    def test_default_profile_implicit(
        self, clean_descriptor_set: Path,
    ) -> None:
        """Bare invocation defaults to --profile=default."""
        result = CliRunner().invoke(
            lint_main, [str(clean_descriptor_set)],
        )
        assert result.exit_code == 0, result.output

    def test_default_profile_explicit(
        self, clean_descriptor_set: Path,
    ) -> None:
        """--profile=default behaves identically to bare invocation."""
        result = CliRunner().invoke(
            lint_main,
            ["--profile", "default", str(clean_descriptor_set)],
        )
        assert result.exit_code == 0, result.output

    def test_strict_profile_against_strict_only_pack(
        self, clean_descriptor_set: Path,
    ) -> None:
        """--profile=strict resolves user pack's strict-only rule.

        Built-in canary doesn't declare 'strict' so it contributes
        nothing; the user pack's one rule fires under that profile.
        """
        result = CliRunner().invoke(
            lint_main,
            [
                "--rule-pack",
                "tests.schema.lint.cli.user_packs.pack_strict_only",
                "--profile", "strict",
                str(clean_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output

    def test_unknown_profile_routes_to_unknown_profile_with_introspection(
        self, clean_descriptor_set: Path,
    ) -> None:
        """--profile=typo → R11 loud failure + per-pack introspection.

        Lists declared profiles for every loaded pack so the user
        sees what names ARE available.
        """
        result = CliRunner().invoke(
            lint_main,
            [
                "--profile", "typo-not-real",
                str(clean_descriptor_set),
            ],
        )
        assert result.exit_code == 2
        assert "error[lint-unknown-profile]:" in result.stderr
        # R11 introspection: built-in canary's declared profile listed:
        assert "protokit.schema.lint.rules.naming" in result.stderr
        assert "default" in result.stderr  # the canary's profile
        # The typo'd profile name appears in the message body:
        assert "typo-not-real" in result.stderr

    def test_unknown_profile_with_user_pack_lists_pack_profiles(
        self, clean_descriptor_set: Path,
    ) -> None:
        """R11 introspection includes user-pack declared profiles."""
        result = CliRunner().invoke(
            lint_main,
            [
                "--rule-pack",
                "tests.schema.lint.cli.user_packs.pack_strict_only",
                "--profile", "nonexistent",
                str(clean_descriptor_set),
            ],
        )
        assert result.exit_code == 2
        assert "error[lint-unknown-profile]:" in result.stderr
        # Both packs' declared profiles surface:
        assert "default" in result.stderr  # from built-in canary
        assert "strict" in result.stderr  # from pack_strict_only


# ---------------------------------------------------------------------------
# --min-severity override + relaxation breadcrumb
# ---------------------------------------------------------------------------


class TestMinSeverityOverride:
    def test_min_severity_error_filters_warnings(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        """--min-severity=error filters out WARNING-severity findings.

        The canary fires WARNING-severity findings on bad_naming.
        With --min-severity=error, those are filtered.
        """
        result = CliRunner().invoke(
            lint_main,
            [
                "--min-severity", "error",
                str(bad_naming_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        # Findings filtered: stdout is empty (or has zero findings).
        assert "BadCamelCase" not in result.stdout
        assert "with__double" not in result.stdout
        # No relaxation breadcrumb (override is more strict, not lenient).
        assert "relaxes profile floor" not in result.stderr

    def test_min_severity_info_emits_relaxation_breadcrumb(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        """--min-severity=info against composed-default WARNING emits breadcrumb.

        The composed profile's min_severity is WARNING (from_pack
        always returns the dataclass default). --min-severity=info
        is more lenient → breadcrumb fires.
        """
        result = CliRunner().invoke(
            lint_main,
            [
                "--min-severity", "info",
                str(bad_naming_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "relaxes profile floor" in result.stderr
        assert "warning" in result.stderr.lower()
        assert "info" in result.stderr.lower()
        # Findings still rendered (warnings pass the info floor):
        assert "BadCamelCase" in result.stdout

    def test_min_severity_warning_no_breadcrumb_no_change(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        """--min-severity=warning matches composed default — no breadcrumb."""
        result = CliRunner().invoke(
            lint_main,
            [
                "--min-severity", "warning",
                str(bad_naming_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        # No relaxation (override equals the composed floor, not below).
        assert "relaxes profile floor" not in result.stderr
        # Findings still rendered (warning passes the warning floor):
        assert "BadCamelCase" in result.stdout

    def test_min_severity_invalid_value_is_click_choice_error(
        self, clean_descriptor_set: Path,
    ) -> None:
        """--min-severity=nope → click validation error (Usage: prefix)."""
        result = CliRunner().invoke(
            lint_main,
            [
                "--min-severity", "nope",
                str(clean_descriptor_set),
            ],
        )
        assert result.exit_code == 2
        # Click-owned prefix; NOT lint stable prefix.
        assert "error[lint-" not in result.output


# ---------------------------------------------------------------------------
# R25 multi-pack provenance gating
# ---------------------------------------------------------------------------


class TestR25Provenance:
    def test_single_pack_default_emits_no_provenance_line(
        self, clean_descriptor_set: Path,
    ) -> None:
        """R25 gated on len(loaded_packs) >= 2 — single-pack default silent."""
        result = CliRunner().invoke(
            lint_main, [str(clean_descriptor_set)],
        )
        assert result.exit_code == 0, result.output
        assert "protokit lint: profile" not in result.stderr

    def test_multi_pack_emits_provenance_line(
        self, clean_descriptor_set: Path,
    ) -> None:
        """Multi-pack (built-in + 1 user pack) triggers R25 line."""
        result = CliRunner().invoke(
            lint_main,
            [
                "--rule-pack",
                "tests.schema.lint.cli.user_packs.pack_user_a",
                str(clean_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "protokit lint: profile 'default' from" in result.stderr
        # Both packs listed with their contributing rule_ids:
        assert "protokit.schema.lint.rules.naming=" in result.stderr
        assert "naming/snake-case-fields" in result.stderr
        assert "pack_user_a" in result.stderr
        assert "user-a/no-leading-x" in result.stderr

    def test_provenance_emits_to_stderr_not_stdout(
        self, clean_descriptor_set: Path,
    ) -> None:
        """R25 provenance MUST land on stderr (parseable side-channel)."""
        result = CliRunner().invoke(
            lint_main,
            [
                "--rule-pack",
                "tests.schema.lint.cli.user_packs.pack_user_a",
                str(clean_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "protokit lint: profile" in result.stderr
        assert "protokit lint: profile" not in result.stdout
