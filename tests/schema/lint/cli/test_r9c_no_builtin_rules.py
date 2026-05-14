"""D6a U9 R9c — ``--no-builtin-rules`` CLI flag tests.

The flag skips the ``BUILTIN_PACKS`` auto-load loop in
``protokit lint``. Pyproject equivalent
``[tool.protokit.lint] no_builtin_rules = true`` was wired into
``ResolvedLintConfig`` in U2; this unit wires the CLI side and the
parameter-source precedence.

Tests cover:
- CLI flag set → BUILTIN_PACKS not loaded → ``no-rules`` exit 2.
- Pyproject ``no_builtin_rules = true`` → equivalent behavior.
- CLI > pyproject precedence (CLI flag wins regardless).
- Default (neither set) → BUILTIN_PACKS load normally.
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from protokit.schema.lint.cli import main as lint_main


def _write_pyproject_no_builtin(
    tmp_path: Path, value: bool,
) -> Path:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "[tool.protokit.lint]\n"
        f"no_builtin_rules = {str(value).lower()}\n",
        encoding="utf-8",
    )
    return pyproject


class TestR9cNoBuiltinRulesFlag:
    """CLI ``--no-builtin-rules`` flag (D6a R9c)."""

    def test_flag_set_triggers_no_rules_exit_two(
        self,
        clean_descriptor_set: Path,
    ) -> None:
        """With BUILTIN_PACKS skipped and no --rule-pack, the lint
        engine has zero rules → exit 2 with error[lint-no-rules]:."""
        result = CliRunner().invoke(
            lint_main,
            ["--no-builtin-rules", str(clean_descriptor_set)],
        )
        assert result.exit_code == 2, result.output
        assert "error[lint-no-rules]:" in result.stderr, result.stderr

    def test_flag_unset_loads_builtin_packs(
        self,
        bad_naming_descriptor_set: Path,
    ) -> None:
        """Without --no-builtin-rules, BUILTIN_PACKS loads and the
        canary fires."""
        result = CliRunner().invoke(
            lint_main,
            [str(bad_naming_descriptor_set)],
        )
        # Exit 1 (findings present) or 0 — both indicate that rules
        # loaded; the relevant signal is "no-rules error did NOT fire".
        assert result.exit_code in (0, 1), result.output
        assert "error[lint-no-rules]:" not in result.stderr, result.stderr


class TestR9cPyprojectEquivalent:
    """Pyproject ``no_builtin_rules = true`` (D6a R9c)."""

    def test_pyproject_true_skips_builtin_packs(
        self,
        tmp_path: Path,
        clean_descriptor_set: Path,
    ) -> None:
        pyproject = _write_pyproject_no_builtin(tmp_path, value=True)
        result = CliRunner().invoke(
            lint_main,
            [
                "--config", str(pyproject),
                str(clean_descriptor_set),
            ],
        )
        assert result.exit_code == 2, result.output
        assert "error[lint-no-rules]:" in result.stderr

    def test_pyproject_false_loads_builtin_packs(
        self,
        tmp_path: Path,
        bad_naming_descriptor_set: Path,
    ) -> None:
        pyproject = _write_pyproject_no_builtin(tmp_path, value=False)
        result = CliRunner().invoke(
            lint_main,
            [
                "--config", str(pyproject),
                str(bad_naming_descriptor_set),
            ],
        )
        assert result.exit_code in (0, 1), result.output
        assert "error[lint-no-rules]:" not in result.stderr


class TestR9cPrecedence:
    """CLI > pyproject precedence (D6a R9c)."""

    def test_cli_flag_overrides_pyproject_false(
        self,
        tmp_path: Path,
        clean_descriptor_set: Path,
    ) -> None:
        """User typed --no-builtin-rules; pyproject says
        no_builtin_rules = false. CLI wins → no-rules error."""
        pyproject = _write_pyproject_no_builtin(tmp_path, value=False)
        result = CliRunner().invoke(
            lint_main,
            [
                "--config", str(pyproject),
                "--no-builtin-rules",
                str(clean_descriptor_set),
            ],
        )
        assert result.exit_code == 2, result.output
        assert "error[lint-no-rules]:" in result.stderr

    def test_cli_default_defers_to_pyproject_true(
        self,
        tmp_path: Path,
        clean_descriptor_set: Path,
    ) -> None:
        """User did NOT type --no-builtin-rules; pyproject says
        no_builtin_rules = true. Pyproject wins → no-rules error.
        Verifies the parameter-source detection correctly treats
        the CLI default as "not explicitly set"."""
        pyproject = _write_pyproject_no_builtin(tmp_path, value=True)
        result = CliRunner().invoke(
            lint_main,
            [
                "--config", str(pyproject),
                str(clean_descriptor_set),
            ],
        )
        assert result.exit_code == 2, result.output
        assert "error[lint-no-rules]:" in result.stderr
