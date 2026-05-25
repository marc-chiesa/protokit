"""R8c ``unknown_rule_id`` CLI-emitted warning tests (D6f U2).

The R8c emission path requires the engine's full ``_loaded_specs``
registry (it diffs ``resolved.disabled_rules | resolved.enabled_rules``
against the loaded rule_ids AFTER all rule-pack loading), so the
contract is exercised end-to-end through the CLI rather than at the
``from_dict`` boundary.

Mirrors the existing ``severities_unloaded_rule`` CLI-synthesis
pattern (cli.py around the post-engine.run warnings block); the
emission site is the orchestration layer, not the engine.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from protokit.schema.lint.cli import main as lint_main


def _make_pyproject(tmp_path: Path, contents: str) -> Path:
    path = tmp_path / "pyproject.toml"
    path.write_text(contents, encoding="utf-8")
    return path


def _invoke_json(args: list[str]) -> tuple[int, str, str]:
    """Run lint_main and return (exit_code, stdout, stderr).

    Click 8.2+ splits stdout / stderr by default on ``CliRunner``;
    reading ``result.stdout`` keeps the R25 multi-pack provenance
    line and post-format ``_emit_human_runtime_warnings`` output
    (both stderr-bound) out of the JSON parser's input.
    """
    runner = CliRunner()
    result = runner.invoke(lint_main, args)
    return result.exit_code, result.stdout, result.stderr


class TestR8cUnknownRuleIdEmission:
    def test_unknown_pyproject_disabled_rule_emits_warning(
        self, tmp_path: Path, bad_naming_descriptor_set: Path,
    ) -> None:
        pyproject = _make_pyproject(
            tmp_path,
            """
            [tool.protokit.lint]
            profile = "default"
            disabled_rules = ["naming/nonexistent-rule-xyz"]
            """,
        )
        exit_code, stdout, _ = _invoke_json(
            [
                "--format", "json",
                "--config", str(pyproject),
                str(bad_naming_descriptor_set),
            ],
        )
        assert exit_code in (0, 1), stdout
        payload = json.loads(stdout)
        unknowns = [
            w
            for w in payload["runtime_warnings"]
            if w["category"] == "unknown_rule_id"
        ]
        assert len(unknowns) >= 1
        assert any(
            w["rule_id"] == "naming/nonexistent-rule-xyz" for w in unknowns
        )
        # Lenient-with-warning: the rule pass still completes; the
        # unknown directive has no effect.
        assert "findings" in payload

    def test_unknown_pyproject_enabled_rule_emits_warning(
        self, tmp_path: Path, bad_naming_descriptor_set: Path,
    ) -> None:
        pyproject = _make_pyproject(
            tmp_path,
            """
            [tool.protokit.lint]
            profile = "default"
            enabled_rules = ["fictional/nonexistent-rule"]
            """,
        )
        exit_code, stdout, _ = _invoke_json(
            [
                "--format", "json",
                "--config", str(pyproject),
                str(bad_naming_descriptor_set),
            ],
        )
        assert exit_code in (0, 1), stdout
        payload = json.loads(stdout)
        unknowns = [
            w
            for w in payload["runtime_warnings"]
            if w["category"] == "unknown_rule_id"
        ]
        assert any(
            w["rule_id"] == "fictional/nonexistent-rule" for w in unknowns
        )

    def test_unknown_cli_disable_rule_emits_warning(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        exit_code, stdout, _ = _invoke_json(
            [
                "--format", "json",
                "--no-config",
                "--disable-rule", "fictional/cli-only-rule",
                str(bad_naming_descriptor_set),
            ],
        )
        assert exit_code in (0, 1), stdout
        payload = json.loads(stdout)
        unknowns = [
            w
            for w in payload["runtime_warnings"]
            if w["category"] == "unknown_rule_id"
        ]
        assert any(
            w["rule_id"] == "fictional/cli-only-rule" for w in unknowns
        )

    def test_known_rule_does_not_emit_unknown_warning(
        self, tmp_path: Path, bad_naming_descriptor_set: Path,
    ) -> None:
        """Regression guard: a legitimately disabled rule must NOT
        produce a spurious ``unknown_rule_id`` warning."""
        pyproject = _make_pyproject(
            tmp_path,
            """
            [tool.protokit.lint]
            profile = "default"
            disabled_rules = ["naming/snake-case-fields"]
            """,
        )
        exit_code, stdout, _ = _invoke_json(
            [
                "--format", "json",
                "--config", str(pyproject),
                str(bad_naming_descriptor_set),
            ],
        )
        assert exit_code in (0, 1), stdout
        payload = json.loads(stdout)
        for w in payload["runtime_warnings"]:
            assert w["category"] != "unknown_rule_id", (
                f"spurious unknown_rule_id fired for a known rule: {w}"
            )

    def test_unknown_cli_enable_rule_emits_warning(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        """``--enable-rule <nonexistent>`` emits ``unknown_rule_id`` warning.

        Mirrors ``test_unknown_cli_disable_rule_emits_warning`` for the
        ``--enable-rule`` flag — the R8c emission path covers both
        ``disabled_rules | enabled_rules`` per cli.py's diff against
        the loaded registry.
        """
        exit_code, stdout, _ = _invoke_json(
            [
                "--format", "json",
                "--no-config",
                "--enable-rule", "fictional/cli-only-rule",
                str(bad_naming_descriptor_set),
            ],
        )
        assert exit_code in (0, 1), stdout
        payload = json.loads(stdout)
        unknowns = [
            w
            for w in payload["runtime_warnings"]
            if w["category"] == "unknown_rule_id"
        ]
        assert any(
            w["rule_id"] == "fictional/cli-only-rule" for w in unknowns
        )

    def test_unknown_warning_normalizes_rule_id_in_payload(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        """The warning's ``rule_id`` field carries the post-normalization
        form (``.strip().lower()``) so users see the canonical form
        that was actually compared against the registry — KD-6 +
        ``source-aware-error-messages``."""
        exit_code, stdout, _ = _invoke_json(
            [
                "--format", "json",
                "--no-config",
                "--disable-rule", "  Fictional/Mixed-Case-Rule  ",
                str(bad_naming_descriptor_set),
            ],
        )
        assert exit_code in (0, 1), stdout
        payload = json.loads(stdout)
        unknowns = [
            w
            for w in payload["runtime_warnings"]
            if w["category"] == "unknown_rule_id"
        ]
        assert any(
            w["rule_id"] == "fictional/mixed-case-rule" for w in unknowns
        )
