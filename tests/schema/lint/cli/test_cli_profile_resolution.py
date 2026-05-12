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
        nothing; the user pack's one rule is selected under that profile.
        ``clean.proto`` field names (``user_id``, ``workspace_id``,
        ``display_name``, ``members``) contain no digit characters, so
        ``strict-only/no-numbers`` fires zero findings — stdout is empty.
        The R25 provenance line confirms ``strict-only/no-numbers`` was
        the active rule, pinning that the profile was resolved correctly.
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
        # No findings — clean.proto field names have no digit characters:
        assert result.stdout == ""
        # R25 provenance confirms the strict-only/no-numbers rule was active:
        assert "strict-only/no-numbers" in result.stderr

    def test_unknown_profile_routes_to_unknown_profile_with_introspection(
        self, clean_descriptor_set: Path,
    ) -> None:
        """--profile=typo → R11 loud failure + per-pack introspection.

        Per-pack info lines appear before the single-line error.
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
        # R11 introspection: built-in canary's declared profile listed
        # as a parseable info[lint-pack-profiles]: line:
        assert (
            "info[lint-pack-profiles]: pack=protokit.schema.lint.rules.naming "
            "profiles=[default]"
            in result.stderr
        )
        # Single-line error body:
        assert (
            "error[lint-unknown-profile]: profile 'typo-not-real' is not "
            "declared by any loaded pack"
            in result.stderr
        )

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
        # Both packs appear as parseable info[lint-pack-profiles]: lines:
        assert (
            "info[lint-pack-profiles]: pack=protokit.schema.lint.rules.naming "
            "profiles=[default]"
            in result.stderr
        )
        assert (
            "info[lint-pack-profiles]: "
            "pack=tests.schema.lint.cli.user_packs.pack_strict_only "
            "profiles=[strict]"
            in result.stderr
        )
        # Single-line error body:
        assert (
            "error[lint-unknown-profile]: profile 'nonexistent' is not "
            "declared by any loaded pack"
            in result.stderr
        )


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

    def test_min_severity_info_emits_relaxation_warning(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        """--min-severity=info against composed-default WARNING emits
        a structured min_severity_relaxed warning.

        The composed profile's min_severity is WARNING (from_pack
        always returns the dataclass default). --min-severity=info
        is more lenient → relaxation message fires.

        D5 U4 contract: the previous U2 stderr breadcrumb was
        replaced with a `LintRuntimeWarning(category=
        "min_severity_relaxed", rule_id=None)` appended to
        `report.runtime_warnings` post-engine. Visible via
        `--format=json`.
        """
        import json

        result = CliRunner().invoke(
            lint_main,
            [
                "--min-severity", "info",
                "--format", "json",
                str(bad_naming_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        parsed = json.loads(result.stdout)
        warnings = parsed["runtime_warnings"]
        relax = [
            w for w in warnings
            if w["category"] == "min_severity_relaxed"
        ]
        assert len(relax) == 1, warnings
        msg = relax[0]["message"]
        assert "relaxes profile floor" in msg
        assert "warning" in msg.lower()
        assert "info" in msg.lower()
        # CLI source attribution:
        assert "--min-severity=info" in msg
        # R18 BREAKING contract: rule_id is null for CLI-emitted
        # categories:
        assert relax[0]["rule_id"] is None
        # Findings still rendered (warnings pass the info floor):
        assert len(parsed["findings"]) > 0

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


# ---------------------------------------------------------------------------
# Runtime-warning emission (Fix W)
# ---------------------------------------------------------------------------


class TestRuntimeWarningEmission:
    def test_rule_exception_surfaces_in_runtime_warnings(
        self, clean_descriptor_set: Path,
    ) -> None:
        """A rule that raises an exception produces a
        ``LintRuntimeWarning(category="rule_exception")`` in the
        report's ``runtime_warnings`` tuple.

        ``pack_rule_raises`` declares a rule that unconditionally raises
        ``ValueError("synthetic-failure")``. The engine catches the
        exception (its narrow-catch tuple includes ``Exception``)
        and records a ``LintRuntimeWarning(category="rule_exception")``.

        D5 U4 contract: the previous stderr ``warning[lint-runtime]:``
        loop was removed; structured warnings now flow through
        formatter dispatch only. Visible via ``--format=json``. (D5 U5
        adds a CLI-side post-format hook re-emitting to stderr for
        ``--format=human``.)
        """
        import json

        result = CliRunner().invoke(
            lint_main,
            [
                "--rule-pack",
                "tests.schema.lint.cli.user_packs.pack_rule_raises",
                "--format", "json",
                str(clean_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        parsed = json.loads(result.stdout)
        warnings = parsed["runtime_warnings"]
        rule_exc = [
            w for w in warnings if w["category"] == "rule_exception"
        ]
        assert len(rule_exc) >= 1, warnings
        assert "synthetic-failure" in rule_exc[0]["message"]
        # Engine-emitted categories retain a non-null rule_id per
        # the R18 widening contract (only CLI-emitted categories
        # populate rule_id=None):
        assert rule_exc[0]["rule_id"] is not None


class TestProfileCaseNormalization:
    """Case normalization for ``--profile``.

    Mirrors ``TestFormatCaseNormalization`` from
    ``test_cli_ci_gating.py``. Pack authors declare lowercase
    profile names by convention (``@lint_rule(profiles=("default",))``);
    users typing ``--profile Default`` should resolve identically
    rather than firing R11 unknown-profile. See
    ``docs/solutions/best-practices/normalize-at-input-boundary-2026-05-07.md``.
    """

    def test_profile_default_mixed_case_resolves(
        self, clean_descriptor_set: Path,
    ) -> None:
        """--profile=Default resolves identically to --profile=default."""
        result = CliRunner().invoke(
            lint_main,
            ["--profile", "Default", str(clean_descriptor_set)],
        )
        assert result.exit_code == 0, result.output
        assert "error[lint-unknown-profile]:" not in result.stderr

    def test_profile_uppercase_resolves(
        self, clean_descriptor_set: Path,
    ) -> None:
        """--profile=DEFAULT (all caps) also resolves to default."""
        result = CliRunner().invoke(
            lint_main,
            ["--profile", "DEFAULT", str(clean_descriptor_set)],
        )
        assert result.exit_code == 0, result.output
        assert "error[lint-unknown-profile]:" not in result.stderr

    def test_profile_mixed_case_strict_resolves_against_strict_only_pack(
        self, clean_descriptor_set: Path,
    ) -> None:
        """--profile=Strict resolves identically to --profile=strict
        when a pack declares profiles=('strict',)."""
        result = CliRunner().invoke(
            lint_main,
            [
                "--rule-pack",
                "tests.schema.lint.cli.user_packs.pack_strict_only",
                "--profile", "Strict",
                str(clean_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "error[lint-unknown-profile]:" not in result.stderr
