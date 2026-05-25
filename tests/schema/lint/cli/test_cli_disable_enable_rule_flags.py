"""Click integration tests for ``--disable-rule`` / ``--enable-rule`` (D6f U2).

Verifies the CLI surface mechanics — repeatability, env-var
integration via ``PROTOKIT_DISABLE_RULE`` / ``PROTOKIT_ENABLE_RULE``,
and that the flags survive intact into ``cli_overrides`` for
``ResolvedLintConfig.from_dict`` to consume.

End-to-end suppression behavior is covered separately by
``test_cli_r9b_profile_augmentation.py``; this file focuses on the
Click parsing + plumbing layer.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from protokit.schema.lint.cli import main as lint_main


def _run(args: list[str], env: dict[str, str] | None = None) -> tuple[int, str]:
    """Invoke lint_main and return (exit_code, stdout-only string).

    Click 8.2+ splits stdout / stderr by default on ``CliRunner``;
    reading ``result.stdout`` keeps the R25 multi-pack provenance
    line and post-format ``_emit_human_runtime_warnings`` output
    (both stderr-bound) out of the JSON parser's input.
    """
    runner = CliRunner()
    result = runner.invoke(lint_main, args, env=env)
    return result.exit_code, result.stdout


class TestRepeatableFlag:
    """``multiple=True`` allows the flag to appear repeatedly."""

    def test_disable_rule_repeatable_collects_multiple_ids(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        exit_code, stdout = _run(
            [
                "--format", "json",
                "--no-config",
                "--disable-rule", "naming/snake-case-fields",
                "--disable-rule", "imports/unused",
                str(bad_naming_descriptor_set),
            ],
        )
        assert exit_code in (0, 1), stdout
        payload = json.loads(stdout)
        # Both rules suppressed — no naming/snake-case-fields finding;
        # imports/unused either was unknown (R8c warning) or also
        # absent. Verify by checking findings don't contain either:
        rule_ids = {f["rule_id"] for f in payload["findings"]}
        assert "naming/snake-case-fields" not in rule_ids
        assert "imports/unused" not in rule_ids

    def test_enable_rule_repeatable(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        """``--enable-rule R1 --enable-rule R2`` is accepted; the two
        rules are processed and no ``unknown_rule_id`` fires for loaded rules."""
        exit_code, stdout = _run(
            [
                "--format", "json",
                "--no-config",
                "--enable-rule", "naming/snake-case-fields",
                "--enable-rule", "imports/unused",
                str(bad_naming_descriptor_set),
            ],
        )
        assert exit_code in (0, 1), stdout
        payload = json.loads(stdout)
        # Both rule_ids were processed by the CLI → no unknown_rule_id
        # warning should fire for the known rule (naming/snake-case-fields
        # is in BUILTIN_PACKS default profile; if it were not processed,
        # the R8c emission would fire).
        unknown_for_known_rule = [
            w
            for w in payload["runtime_warnings"]
            if w["category"] == "unknown_rule_id"
            and w["rule_id"] == "naming/snake-case-fields"
        ]
        assert unknown_for_known_rule == [], (
            "known rule 'naming/snake-case-fields' should not trigger "
            f"unknown_rule_id warning: {unknown_for_known_rule!r}"
        )
        # The 'findings' key is present in the structured payload —
        # confirms the full pipeline ran (not just a flag-parse check).
        assert "findings" in payload

    def test_mixed_disable_and_enable_same_invocation_warns(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        """``--disable-rule R --enable-rule R`` in the same invocation
        emits an R8b contradictory_disable_config warning."""
        exit_code, stdout = _run(
            [
                "--format", "json",
                "--no-config",
                "--disable-rule", "naming/snake-case-fields",
                "--enable-rule", "naming/snake-case-fields",
                str(bad_naming_descriptor_set),
            ],
        )
        assert exit_code in (0, 1), stdout
        payload = json.loads(stdout)
        warnings = [
            w
            for w in payload["runtime_warnings"]
            if w["category"] == "contradictory_disable_config"
        ]
        assert len(warnings) == 1
        assert warnings[0]["rule_id"] == "naming/snake-case-fields"
        assert "--disable-rule" in warnings[0]["message"]
        assert "--enable-rule" in warnings[0]["message"]


class TestNormalizationAtCliBoundary:
    """KD-6 — CLI inputs flow through ``.strip().lower()`` so an
    uppercase typo cited at the command line still matches the
    canonical lowercase rule_id."""

    def test_uppercase_cli_disable_rule_normalized(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        exit_code, stdout = _run(
            [
                "--format", "json",
                "--no-config",
                "--disable-rule", "Naming/Snake-Case-Fields",
                str(bad_naming_descriptor_set),
            ],
        )
        assert exit_code in (0, 1), stdout
        payload = json.loads(stdout)
        rule_ids = {f["rule_id"] for f in payload["findings"]}
        # Normalization applied → the uppercase form matches the
        # canonical lowercase rule_id and disables it.
        assert "naming/snake-case-fields" not in rule_ids


class TestEnvVarIntegration:
    """``PROTOKIT_DISABLE_RULE`` / ``PROTOKIT_ENABLE_RULE`` env vars."""

    def test_disable_rule_env_var_recognized(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        """Click's ``envvar=...`` plumbing turns the env var into the
        flag's value at parse time."""
        exit_code, stdout = _run(
            [
                "--format", "json",
                "--no-config",
                str(bad_naming_descriptor_set),
            ],
            env={"PROTOKIT_DISABLE_RULE": "naming/snake-case-fields"},
        )
        assert exit_code in (0, 1), stdout
        payload = json.loads(stdout)
        rule_ids = {f["rule_id"] for f in payload["findings"]}
        assert "naming/snake-case-fields" not in rule_ids


class TestFormatValidation:
    """CLI format validation parity with pyproject (per
    [[symmetric-coercion-strictness-multi-source-field-resolver-2026-05-12]])."""

    def test_invalid_format_cli_disable_rule_exits_2(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        exit_code, stdout = _run(
            [
                "--format", "json",
                "--no-config",
                "--disable-rule", "invalid-no-slash",
                str(bad_naming_descriptor_set),
            ],
        )
        assert exit_code == 2, stdout


class TestEmptyTupleSentinel:
    """KD-5 — when the user does not pass the flag, the cli.py wiring
    converts the natural Click empty-tuple to ``None`` for from_dict.

    No regression observable at the CLI layer (--no-config with no
    --disable-rule produces no R9b directives), but the test pins
    the no-flag-default-no-warning contract."""

    def test_no_flag_no_warnings(
        self, clean_descriptor_set: Path,
    ) -> None:
        exit_code, stdout = _run(
            [
                "--format", "json",
                "--no-config",
                str(clean_descriptor_set),
            ],
        )
        assert exit_code == 0, stdout
        payload = json.loads(stdout)
        warnings = payload["runtime_warnings"]
        r9b_categories = {
            "contradictory_disable_config", "unknown_rule_id",
        }
        for w in warnings:
            assert w["category"] not in r9b_categories, (
                f"unexpected R9b warning on a no-flag invocation: {w}"
            )
