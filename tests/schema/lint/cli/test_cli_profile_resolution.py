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
        # as a parseable info[lint-pack-profiles]: line. D6a Unit 3
        # widened the naming pack to declare both ``default`` and
        # ``recommended`` (sorted alphabetically in the output).
        assert (
            "info[lint-pack-profiles]: pack=protokit.schema.lint.rules.naming "
            "profiles=[default, recommended]"
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
        # Both packs appear as parseable info[lint-pack-profiles]: lines.
        # D6a Unit 3 widened the naming pack's declared profiles.
        assert (
            "info[lint-pack-profiles]: pack=protokit.schema.lint.rules.naming "
            "profiles=[default, recommended]"
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
        import json

        result = CliRunner().invoke(
            lint_main,
            [
                "--min-severity", "error",
                "--format", "json",
                str(bad_naming_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        parsed = json.loads(result.stdout)
        # Findings filtered: zero findings render.
        assert parsed["findings"] == []
        # Override is stricter than the WARNING floor, so the
        # structured relaxation warning must NOT fire.
        relax = [
            w for w in parsed["runtime_warnings"]
            if w["category"] == "min_severity_relaxed"
        ]
        assert relax == [], parsed["runtime_warnings"]

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

    def test_min_severity_warning_no_relaxation_when_matching_floor(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        """--min-severity=warning matches composed default — no relaxation.

        T-U4-03 edge case: override equals the floor exactly (not
        below). ``relaxation_message`` returns ``None`` for this case,
        so no structured warning is appended.
        """
        import json

        result = CliRunner().invoke(
            lint_main,
            [
                "--min-severity", "warning",
                "--format", "json",
                str(bad_naming_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        parsed = json.loads(result.stdout)
        # Override == floor, no relaxation: structured warning absent.
        relax = [
            w for w in parsed["runtime_warnings"]
            if w["category"] == "min_severity_relaxed"
        ]
        assert relax == [], parsed["runtime_warnings"]
        # Findings still rendered (warning passes the warning floor):
        finding_messages = [f["message"] for f in parsed["findings"]]
        assert any("BadCamelCase" in m for m in finding_messages)

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
    def test_builtin_default_emits_provenance_line_multi_pack(
        self, clean_descriptor_set: Path,
    ) -> None:
        """R25 fires on the built-in default once BUILTIN_PACKS >= 2.

        ``BUILTIN_PACKS`` shipped with one member at D2 (``naming``);
        D6a Unit 4 added ``enum`` (tripping the R25
        ``len(loaded_packs) >= 2`` gate), Unit 5 added ``imports``,
        Unit 6 added ``package`` and ``file``. The default
        invocation now emits the provenance line listing all five
        packs and their contributing rule_ids.

        The single-pack-silent branch of the gate is no longer
        reachable through built-in defaults. It will be re-verifiable
        when D6a Unit 9 lands ``--no-builtin-rules`` (which, combined
        with a single ``--rule-pack <module>``, yields a true
        single-pack composition). A coverage test for that branch
        ships alongside Unit 9.
        """
        result = CliRunner().invoke(
            lint_main, [str(clean_descriptor_set)],
        )
        assert result.exit_code == 0, result.output
        assert "protokit lint: profile 'default' from" in result.stderr
        # Pin specific D6a-era contributing rules across the 5 packs
        # that were in BUILTIN_PACKS at this test's introduction
        # (naming, enum, imports, package, file). BUILTIN_PACKS has
        # grown since (D6b U7 added package_same, D6b U3a + D6d U5
        # added the options namespace, D6e U1+U2 added field). The
        # assertions below pin specific rule names — not pack count
        # — so they remain valid as the BUILTIN_PACKS tuple grows.
        # ce:review P2 #9 (agent-native Obs 1, 2026-05-22) updated
        # this comment to reflect current BUILTIN_PACKS size.
        assert "protokit.schema.lint.rules.naming=" in result.stderr
        assert "naming/snake-case-fields" in result.stderr
        assert "protokit.schema.lint.rules.enum=" in result.stderr
        assert "enum/no-allow-alias" in result.stderr
        assert "enum/first-value-zero" in result.stderr
        assert "protokit.schema.lint.rules.imports=" in result.stderr
        assert "imports/no-public" in result.stderr
        assert "imports/no-weak" in result.stderr
        assert "imports/unused" in result.stderr
        assert "protokit.schema.lint.rules.package=" in result.stderr
        assert "package/defined" in result.stderr
        assert "package/directory-match" in result.stderr
        assert "protokit.schema.lint.rules.file=" in result.stderr
        assert "file/syntax-specified" in result.stderr

    def test_multi_pack_emits_provenance_line(
        self, clean_descriptor_set: Path,
    ) -> None:
        """Multi-pack (built-in + 1 user pack) triggers R25 line.

        BUILTIN_PACKS has grown since this test was introduced
        (D6a U6: 5 packs; D6b U7: +1 = 6; D6b U3a: +1 = 7; D6d U5:
        +1 = 8; D6e U1+U2: +1 = 9). The companion test above pins
        specific built-in rule names; this test additionally pins
        that user packs append cleanly to the provenance line in
        the same wire format. The R25 line fires whenever
        ``len(loaded_packs_tuple) >= 2``, which has been true
        since D6a U6. ce:review P2 #9 (agent-native Obs 1,
        2026-05-22) updated this docstring to reflect current
        BUILTIN_PACKS size.
        """
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
        # All six packs listed with at least one contributing rule_id each.
        assert "protokit.schema.lint.rules.naming=" in result.stderr
        assert "naming/snake-case-fields" in result.stderr
        assert "protokit.schema.lint.rules.enum=" in result.stderr
        assert "enum/no-allow-alias" in result.stderr
        assert "enum/first-value-zero" in result.stderr
        assert "protokit.schema.lint.rules.imports=" in result.stderr
        assert "imports/no-public" in result.stderr
        assert "imports/no-weak" in result.stderr
        assert "imports/unused" in result.stderr
        assert "protokit.schema.lint.rules.package=" in result.stderr
        assert "package/defined" in result.stderr
        assert "package/directory-match" in result.stderr
        assert "protokit.schema.lint.rules.file=" in result.stderr
        assert "file/syntax-specified" in result.stderr
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


class TestProfileAliasOnCliSurface:
    """Buf-compatibility aliases must resolve through the ``--profile``
    FLAG, not only through ``[tool.protokit.lint] profile``.

    ``_PROFILE_ALIASES`` claims (comment at its declaration, and
    ``_coerce_profile``'s docstring) that "both pyproject and CLI input
    paths flow through ``_coerce_profile``", and README's profiles table
    advertises ``basic``/``minimal`` with no CLI-vs-pyproject caveat.
    The unit tests in ``tests/schema/lint/_config/test_profile_aliases.py``
    cannot pin the CLI half of that claim — they never run the
    flag-parsing layer — so it lives here, end to end through
    ``CliRunner``.

    Only ``basic`` is exercised: ``minimal -> essentials`` is a forward
    placeholder that no shipped pack declares, so it fires R11
    unknown-profile on BOTH surfaces and is not a divergence.
    """

    def test_basic_alias_resolves_like_recommended(
        self, clean_descriptor_set: Path,
    ) -> None:
        """``--profile basic`` must behave exactly like the primary
        name it aliases. Equivalence (rather than "exit code is not 2")
        is the assertion because the alias contract is "same profile",
        not merely "does not error".
        """
        alias = CliRunner().invoke(
            lint_main,
            ["--profile", "basic", str(clean_descriptor_set)],
        )
        primary = CliRunner().invoke(
            lint_main,
            ["--profile", "recommended", str(clean_descriptor_set)],
        )
        assert "error[lint-unknown-profile]:" not in alias.stderr
        assert alias.exit_code == primary.exit_code, alias.output
        assert alias.stdout == primary.stdout

    def test_basic_alias_normalized_before_resolution(
        self, clean_descriptor_set: Path,
    ) -> None:
        """Case/whitespace normalization runs BEFORE the alias lookup on
        the CLI surface too, so ``--profile '  BASIC  '`` resolves.
        """
        result = CliRunner().invoke(
            lint_main,
            ["--profile", "  BASIC  ", str(clean_descriptor_set)],
        )
        assert "error[lint-unknown-profile]:" not in result.stderr
        assert result.exit_code != 2, result.output
