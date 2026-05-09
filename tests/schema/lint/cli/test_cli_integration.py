"""End-to-end integration tests spanning U2-U4b implementation surfaces.

Covers the matrix of meaningful flag combinations across rule
loading, profile resolution, CI gating, output formatting, and
exit codes — exercising the full ``protokit lint`` pipeline as a
single composed unit. Each test asserts a specific cross-cutting
contract that no single per-unit test file can cover in isolation:

- **Single-pack happy path**: ``--proto`` source mode + canary
  rules + ``--statistics`` footer + ``--max-warnings 0`` gating
  end-to-end (R4, R6, R16, R19, R20).
- **Multi-pack provenance under quiet**: ``--rule-pack`` × 2 +
  ``--max-warnings`` + ``--quiet`` produces no stdout but R25
  provenance still emits to stderr (R8, R18, R19, R20, R25).
- **Error-chain ordering**: a config that would trip three
  distinct exit-2 paths simultaneously (zero rules + unknown
  profile + bad format) reports the FIRST error per the
  documented short-circuit order: ``no-rules`` →
  ``unknown-profile`` → ``format-unavailable`` (R9, R11, R13,
  R20a).
- **Format-cross-config gating**: ``--format=sarif`` +
  ``--max-warnings 0`` against a finding-bearing input produces
  valid SARIF output AND exits 1 — the R20 ladder applies
  regardless of formatter (R13, R15, R19, R20).

These are the tests the per-unit suites cannot write in
isolation: they pin behavior at the seams between U2's input
ingestion, U3's rule-loading + profile resolution, U4a's CI
gating + format dispatch, and U4b's machine formatters. A
regression in any single unit that breaks the composition
surfaces here even when the unit's own tests stay green.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

import protokit.schema.lint.cli as lint_cli_module
from protokit.schema.lint.cli import main as lint_main

# ---------------------------------------------------------------------------
# Single-pack full pipeline
# ---------------------------------------------------------------------------


class TestSinglePackFullPipeline:
    """``--proto`` source + canary + ``--statistics`` + gating."""

    def test_proto_source_with_statistics_and_max_warnings_zero_exits_1(
        self, fixtures_proto_dir: Path,
    ) -> None:
        """End-to-end: D1 compile + canary fires + footer + gate trips.

        The ``bad_naming.proto`` fixture has two snake-case-violating
        fields (``BadCamelCase`` and ``with__double``) that the always-on
        canary flags as WARNING. ``--max-warnings 0`` then trips the
        R19 gate (warning count > cap), driving exit code 1 per R20.
        ``--statistics`` opts into the per-severity footer (R16).

        Asserts the full chain: stdout carries findings + footer,
        stderr carries no error-prefix lines, exit code is 1 (gate
        tripped, not internal error).
        """
        result = CliRunner().invoke(
            lint_main,
            [
                "--proto", str(fixtures_proto_dir / "bad_naming.proto"),
                "-I", str(fixtures_proto_dir),
                "--statistics",
                "--max-warnings", "0",
            ],
        )
        assert result.exit_code == 1, (
            f"expected gate-tripped exit 1, got {result.exit_code!r}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        # Findings rendered to stdout (canary warnings).
        assert "BadCamelCase" in result.stdout
        assert "with__double" in result.stdout
        assert "naming/snake-case-fields" in result.stdout
        # Statistics footer rendered (R16 opt-in).
        assert "statistics:" in result.stdout.lower()
        # No internal-error prefix on stderr.
        assert "error[lint-" not in result.stderr


# ---------------------------------------------------------------------------
# Multi-pack provenance under --quiet
# ---------------------------------------------------------------------------


class TestMultiPackProvenanceUnderQuiet:
    """``--rule-pack`` × 2 + ``--max-warnings`` + ``--quiet``."""

    def test_multi_pack_quiet_emits_r25_to_stderr_with_no_stdout(
        self, clean_descriptor_set: Path,
    ) -> None:
        """R25 provenance fires on stderr even when ``--quiet`` empties stdout.

        The R18/R20 contract: ``--quiet`` suppresses the formatter's
        stdout output but preserves the exit-code ladder. R25's
        provenance line is a STDERR breadcrumb that survives quiet
        because it's diagnostic context, not formatter output. With
        canary + ``pack_user_a`` + ``pack_user_b`` loaded (3 packs >=
        2), R25 fires; both user packs appear in the line.

        ``--max-warnings 5`` is non-tripping (clean fixture has zero
        findings) so exit code 0. The test pins the contract:
        operators running quiet + multi-pack still get the
        provenance trail in CI logs without polluting stdout.
        """
        result = CliRunner().invoke(
            lint_main,
            [
                "--rule-pack", "tests.schema.lint.cli.user_packs.pack_user_a",
                "--rule-pack", "tests.schema.lint.cli.user_packs.pack_user_b",
                "--max-warnings", "5",
                "--quiet",
                str(clean_descriptor_set),
            ],
        )
        assert result.exit_code == 0, (
            f"expected exit 0 on clean fixture, got {result.exit_code!r}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        # --quiet suppresses formatter stdout entirely.
        assert result.stdout == "", (
            f"--quiet must empty stdout; got: {result.stdout!r}"
        )
        # R25 provenance fires (3 loaded packs >= 2).
        assert "protokit lint: profile 'default' from" in result.stderr
        # Both user packs appear in the provenance line.
        assert "pack_user_a" in result.stderr
        assert "pack_user_b" in result.stderr
        # Built-in canary appears too (provenance is exhaustive).
        assert "protokit.schema.lint.rules.naming" in result.stderr


# ---------------------------------------------------------------------------
# Error-chain short-circuit ordering
# ---------------------------------------------------------------------------


class TestErrorChainOrdering:
    """First-error-wins short-circuit across the U3+U4a check chain.

    A configuration that would trip three independent exit-2 paths
    simultaneously must surface the FIRST error per the documented
    order:

    1. ``no-rules`` (engine carries zero loaded specs)
    2. ``unknown-profile`` (composed profile has zero rule_ids)
    3. ``format-unavailable`` (registry lookup misses)

    The order is structural — each check short-circuits the next —
    and locking it in a test prevents a future delivery from
    accidentally swapping the order (e.g., moving format
    validation earlier as an "early-fail" optimization, which
    would surface format errors over the more actionable rules
    error).
    """

    def test_no_rules_wins_over_unknown_profile_and_format(
        self,
        clean_descriptor_set: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """All three exit-2 conditions present → ``no-rules`` reported.

        With empty BUILTIN_PACKS, no ``--rule-pack``, an unknown
        ``--profile``, and an unknown ``--format``, the engine
        carries zero specs. The CLI's check chain (per
        ``schema/lint/cli.py``) tests no-rules BEFORE unknown-profile
        BEFORE format-unavailable, so ``no-rules`` is the surfaced
        prefix. The other two error codes MUST NOT appear — both
        because rendering them would imply they ran, and because
        an operator getting all three at once would have to guess
        which one to fix first.
        """
        monkeypatch.setattr(lint_cli_module, "BUILTIN_PACKS", ())
        result = CliRunner().invoke(
            lint_main,
            [
                "--profile", "this-profile-does-not-exist",
                "--format", "this-format-also-does-not-exist",
                str(clean_descriptor_set),
            ],
        )
        assert result.exit_code == 2, (
            f"expected exit 2, got {result.exit_code!r}\n"
            f"stderr={result.stderr!r}"
        )
        # First error wins.
        assert "error[lint-no-rules]:" in result.stderr
        # Subsequent checks must NOT have run.
        assert "error[lint-unknown-profile]:" not in result.stderr
        assert "error[lint-format-unavailable]:" not in result.stderr


# ---------------------------------------------------------------------------
# Format-cross-config gating (SARIF + --max-warnings 0)
# ---------------------------------------------------------------------------


class TestFormatCrossConfigGating:
    """R20 ladder applies regardless of ``--format``."""

    def test_sarif_with_max_warnings_zero_emits_valid_sarif_and_exits_1(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        """SARIF output stays well-formed under a tripped gate.

        A formatter's output is independent of the gate — the gate
        decides exit code, the formatter decides what's on stdout.
        With ``--format=sarif`` + ``--max-warnings 0`` against a
        warning-bearing fixture, stdout MUST be parseable SARIF
        2.1.0 with the canary findings populated AND exit code MUST
        be 1.

        Acknowledges the next-delivery brainstorm responsibility:
        config bugs surface across all four formats simultaneously
        because the gate is upstream of formatter selection. A
        regression that drops SARIF when gating trips would silently
        break CI integrations consuming the JSON.
        """
        result = CliRunner().invoke(
            lint_main,
            [
                "--format", "sarif",
                "--max-warnings", "0",
                str(bad_naming_descriptor_set),
            ],
        )
        assert result.exit_code == 1, (
            f"expected exit 1 (gate tripped), got {result.exit_code!r}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        # Output is well-formed SARIF 2.1.0.
        payload = json.loads(result.stdout)
        assert payload["version"] == "2.1.0", (
            f"expected SARIF 2.1.0, got version={payload.get('version')!r}"
        )
        assert "runs" in payload
        # Canary findings ARE present in the SARIF payload despite
        # the trip — gating does not silence the formatter.
        runs = payload["runs"]
        assert len(runs) >= 1, "SARIF payload missing runs[]"
        results = runs[0].get("results", [])
        # Two canary findings: BadCamelCase, with__double.
        assert len(results) >= 2, (
            f"expected at least 2 SARIF results, got {len(results)}"
        )
        # No stderr error-prefix (gate trip is exit 1, not exit 2).
        assert "error[lint-" not in result.stderr
