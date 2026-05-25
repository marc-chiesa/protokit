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

    def test_proto2_file_under_default_profile_exits_0_post_r4b_demotion(
        self, tmp_path: Path,
    ) -> None:
        """ce:review P2 #6 (2026-05-22): pin the R4b exit-code change.

        Post-D6e R4b, ``file/syntax-specified`` is WARNING in
        recommended + default profiles (was ERROR). For a proto2
        file invoked WITHOUT ``--max-warnings``, the rule still
        fires but no longer pushes the exit code to 1 — the new
        contract is exit 0 + WARNING finding present in the JSON
        output. This regression test pins the behavioral change as
        intentional and catches a future inadvertent re-promotion
        of ``file/syntax-specified`` back to ERROR.

        The test also doubles as the missing end-to-end CLI test
        for the proto2-strict + default profile interaction: it
        asserts no field/not-required finding fires (the rule is
        in proto2-strict opt-in only, not default).
        """
        import json
        import textwrap

        from tests.schema.lint._cli_dedup_helpers import (
            compile_sources_to_descriptor_set,
        )

        proto2_source = textwrap.dedent(
            """\
            syntax = "proto2";
            package acme.r4b;
            message P2 {
              optional int32 ok = 1;
              required int32 also_required = 2;
            }
            """
        )
        descriptor_set = compile_sources_to_descriptor_set(
            tmp_path,
            {"acme/r4b/p2.proto": proto2_source},
            out_filename="r4b_regression.descriptor_set",
        )
        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--format",
                "json",
                str(descriptor_set),
            ],
            catch_exceptions=False,
        )
        # Post-R4b: WARNING-only findings exit 0 without
        # --max-warnings (pre-R4b would have been exit 1 from the
        # file/syntax-specified ERROR path).
        assert result.exit_code == 0, (
            f"expected exit 0 post-R4b demotion; got "
            f"{result.exit_code}.\nstdout={result.stdout!r}"
        )
        payload = json.loads(result.stdout)
        syntax_findings = [
            f for f in payload["findings"]
            if f["rule_id"] == "file/syntax-specified"
        ]
        assert len(syntax_findings) == 1, (
            f"expected 1 file/syntax-specified finding; got "
            f"{len(syntax_findings)}.\nfindings={payload['findings']!r}"
        )
        assert syntax_findings[0]["severity"] == "warning", (
            f"R4b demotion: file/syntax-specified must emit at "
            f"WARNING; got {syntax_findings[0]['severity']!r}"
        )
        # field/not-required is proto2-strict opt-in only; MUST
        # NOT fire under default profile per D6e KD-5.
        field_findings = [
            f for f in payload["findings"]
            if f["rule_id"] == "field/not-required"
        ]
        assert field_findings == [], (
            f"D6e KD-5: field/not-required ships in proto2-strict "
            f"opt-in only; MUST NOT fire under default. Got "
            f"{field_findings!r}"
        )

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


_PROTO_R6_DEPRECATED_NO_REPLACEMENT = """\
syntax = "proto3";
package demo.r6;

message User {
    // This is being removed.
    string old_field = 1 [deprecated = true];
}
"""
"""Proto fixture with a deprecated field whose leading comment does
NOT match the R6 replacement-heuristic regex. Post-D6f, the
``options/deprecated-field-must-have-replacement-comment`` rule fires
at ERROR severity. Pre-D6f it fired at WARNING.

Inline-string-fixture style matches the existing test_cli_ci_gating
discipline (cf. ``test_proto2_file_under_default_profile_exits_0_post_r4b_demotion``
above). --proto mode is required because R6 needs leading-comment
source info; the dedup helper at
``tests/schema/lint/_cli_dedup_helpers.py`` compiles without
``include_source_info=True`` and therefore would over-report per the
D6b U3 K-9 caveat — using --proto mode instead exercises the
``cli.py:731`` flip's load-bearing kwarg.
"""


class TestR6PromotionExitCodeRegression:
    """D6f U1 — R6 promotion (WARNING → ERROR) exit-code regression pin.

    The mirror counterpart to
    ``TestMaxWarningsExitLadder.test_proto2_file_under_default_profile_exits_0_post_r4b_demotion``
    above. D6e R4b was an inverse-direction demotion
    (``file/syntax-specified``: ERROR → WARNING); D6f R6 is the
    promotion. Pins post-D6f exit codes across the three
    user-visible CI postures named in the D6f plan U1 *Error paths*
    test scenarios:

    1. ``--max-warnings`` unset: pre-promotion exit 0; post-promotion
       exit 1. **SILENT CI-PASS REGRESSION RISK** — documented in the
       CHANGELOG migration table.
    2. ``--max-warnings 0``: pre-promotion exit 1 (warnings>0 gate);
       post-promotion exit 1 (``has_error=True`` short-circuits before
       the gate is consulted).
    3. ``--min-severity error``: pre-promotion exit 0 (WARNING filtered
       below floor); post-promotion exit 1 (ERROR passes floor).

    Together these three pin the user-facing severity change as
    intentional. A regression that demotes any R6 rule back to WARNING
    will fire across (1) and (3); a regression that breaks the
    ``has_error`` short-circuit ordering will fire on (2).
    """

    def _write_proto(self, tmp_path: Path) -> Path:
        proto = tmp_path / "r6_sad.proto"
        proto.write_text(_PROTO_R6_DEPRECATED_NO_REPLACEMENT)
        return proto

    def test_max_warnings_unset_post_promotion_exits_1(
        self, tmp_path: Path,
    ) -> None:
        """Posture 1: silent-CI-pass regression risk pinned.

        Pre-D6f: WARNING-only findings without --max-warnings exit 0
        (R20 contract). A user with no CI gating saw a silent passing
        build. Post-D6f: R6 fires at ERROR, the has_error short-circuit
        forces exit 1, CI fails. The CHANGELOG migration recipe MUST
        call this out — users who relied on bare ``protokit lint`` to
        pass their CI will see a new failure on upgrade.
        """
        import json

        proto = self._write_proto(tmp_path)
        result = CliRunner().invoke(
            lint_main,
            [
                "--proto", str(proto),
                "-I", str(tmp_path),
                "--profile", "default",
                "--format", "json",
            ],
            catch_exceptions=False,
        )
        assert result.exit_code == 1, (
            f"D6f R6 promotion: post-promotion --max-warnings-unset "
            f"with an R6 finding must exit 1 (was 0 pre-D6f). Got "
            f"exit={result.exit_code}; output={result.output!r}"
        )
        payload = json.loads(result.stdout)
        r6 = [
            f for f in payload["findings"]
            if f["rule_id"].startswith("options/deprecated-")
        ]
        assert len(r6) == 1, r6
        assert r6[0]["severity"] == "error", (
            f"D6f R6 promotion: finding severity must be 'error'; "
            f"got {r6[0]['severity']!r}"
        )

    def test_max_warnings_zero_post_promotion_exits_1(
        self, tmp_path: Path,
    ) -> None:
        """Posture 2: has_error short-circuit verified.

        Pre-D6f: ``--max-warnings 0`` with a WARNING finding exits 1
        via the warnings>0 gate. Post-D6f: same fixture fires at ERROR,
        ``has_error=True`` short-circuits the exit-code logic at
        ``cli.py:1210-1222`` BEFORE the max_warnings gate is consulted.
        Both paths exit 1; the assertion pins the post-D6f code path.
        """
        proto = self._write_proto(tmp_path)
        result = CliRunner().invoke(
            lint_main,
            [
                "--proto", str(proto),
                "-I", str(tmp_path),
                "--profile", "default",
                "--max-warnings", "0",
            ],
            catch_exceptions=False,
        )
        assert result.exit_code == 1, (
            f"D6f R6 promotion: --max-warnings 0 with an R6 finding "
            f"must exit 1. Got exit={result.exit_code}; "
            f"output={result.output!r}"
        )

    def test_min_severity_error_post_promotion_exits_1(
        self, tmp_path: Path,
    ) -> None:
        """Posture 3: severity floor admits R6 post-D6f.

        Pre-D6f: ``--min-severity error`` filtered the WARNING R6
        finding out of the report, leaving zero findings and exit 0.
        Post-D6f: R6 fires at ERROR, passes the severity floor, exit 1.
        This posture is the ONE where the upgrade impact is most visible
        — a user explicitly opting into errors-only sees the new error
        immediately.
        """
        proto = self._write_proto(tmp_path)
        result = CliRunner().invoke(
            lint_main,
            [
                "--proto", str(proto),
                "-I", str(tmp_path),
                "--profile", "default",
                "--min-severity", "error",
            ],
            catch_exceptions=False,
        )
        assert result.exit_code == 1, (
            f"D6f R6 promotion: --min-severity error with an R6 "
            f"finding must exit 1 (was 0 pre-D6f, when WARNING was "
            f"filtered below the floor). Got exit={result.exit_code}; "
            f"output={result.output!r}"
        )

    def test_r9b_disable_via_off_severity_restores_exit_0(
        self, tmp_path: Path,
    ) -> None:
        """Migration recipe path #3 (R9b ``"off"``) end-to-end.

        Post-D6f R6 promotion + U2 R9b infrastructure: a user can
        suppress the new ERROR via ``--disable-rule`` (CLI) without
        editing the proto. This pins the integration between U2's
        R9b dispatch and U1's R6 severity. If the dispatch silently
        no-ops (the U2 KD-1 propagation gap), this test catches it
        with the migration-recipe lens.

        Uses ``--disable-rule`` rather than a pyproject fixture so the
        test is self-contained (no I/O beyond the inline proto).
        """
        proto = self._write_proto(tmp_path)
        result = CliRunner().invoke(
            lint_main,
            [
                "--proto", str(proto),
                "-I", str(tmp_path),
                "--profile", "default",
                "--disable-rule",
                "options/deprecated-field-must-have-replacement-comment",
            ],
            catch_exceptions=False,
        )
        assert result.exit_code == 0, (
            f"D6f migration recipe #3: --disable-rule for the R6 rule "
            f"must restore exit 0. If this fails, U2's R9b dispatch "
            f"is not actually subtracting from the composed profile "
            f"(KD-1 propagation gap). Got exit={result.exit_code}; "
            f"output={result.output!r}"
        )

    def test_demote_to_warning_severities_restores_exit_0_default(
        self, tmp_path: Path,
    ) -> None:
        """Migration recipe path #2 (demote to ``warning``) end-to-end.

        Post-D6f: the user demotes a single R6 rule back to ``warning``
        via a ``[severities]`` pyproject entry. The R6 finding still
        fires (still useful for human review) but no longer fails CI
        without ``--max-warnings``.

        Uses ``--severity`` via a tmp pyproject fixture would require
        more setup; instead we use ``--no-config`` + the proto-only
        invocation to establish the baseline, then verify the
        ``[severities]`` override path via a tmp pyproject.
        """
        proto = self._write_proto(tmp_path)
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            "[tool.protokit.lint]\n"
            "profile = \"default\"\n"
            "[tool.protokit.lint.severities]\n"
            "\"options/deprecated-field-must-have-replacement-comment\""
            " = \"warning\"\n"
        )
        result = CliRunner().invoke(
            lint_main,
            [
                "--proto", str(proto),
                "-I", str(tmp_path),
                "--config", str(pyproject),
            ],
            catch_exceptions=False,
        )
        assert result.exit_code == 0, (
            f"D6f migration recipe #2: demoting the R6 rule to "
            f"'warning' via [severities] must restore exit 0 in the "
            f"absence of --max-warnings. Got exit={result.exit_code}; "
            f"output={result.output!r}"
        )


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
        """All-zero severity counts → no severity rows, but the footer
        marker should still indicate statistics ran.

        Note (D6d U5): the D6d delivery promoted
        ``options/field-behavior-consistent`` into ``BUILTIN_PACKS``
        under the ``default`` profile. The rule emits a deduplicated
        ``extension_unresolved`` runtime warning per file when the
        compile pool lacks ``google/api/field_behavior.proto`` — so
        the footer's ``runtime-warnings: N`` row now appears on this
        fixture. That row is structural (not a severity count) and
        the assertion below explicitly excludes it from the
        severity-row check.
        """
        result = CliRunner().invoke(
            lint_main,
            ["--statistics", str(clean_descriptor_set)],
        )
        assert result.exit_code == 0, result.output
        assert "statistics:" in result.stdout
        # No severity rows because zero severity-bearing findings.
        # Use splitlines + startswith on the 2-space-indented row
        # prefix so the structural ``runtime-warnings:`` row (also
        # 2-space indented) does NOT satisfy a substring containment
        # check, and so a future indent-width change in the cli's
        # statistics-footer rendering fails loudly (a containment
        # check could pass silently when the indent changes).
        rows = [
            line for line in result.stdout.splitlines()
            if line.startswith("  ")
        ]
        severity_rows = [
            row for row in rows
            if row.startswith(("  warnings:", "  errors:", "  info:"))
        ]
        assert severity_rows == [], (
            f"unexpected severity rows in clean-input statistics: "
            f"{severity_rows!r}"
        )
        # Positive assertion: the D6d-introduced runtime-warnings row
        # IS present (catches a silent regression where the row stops
        # emitting — see ce:review T-03 / TG-1).
        runtime_rows = [
            row for row in rows
            if row.startswith("  runtime-warnings:")
        ]
        assert len(runtime_rows) == 1, (
            f"expected exactly one runtime-warnings row from the "
            f"D6d field-behavior rule's extension_unresolved warning; "
            f"got {runtime_rows!r}"
        )

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
