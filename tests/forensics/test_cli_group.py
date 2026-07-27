"""U1 — the ``forensics`` group is registered and exposes ``match``."""

from __future__ import annotations

from click.testing import CliRunner

from protokit.cli import main


def test_forensics_group_registered() -> None:
    assert "forensics" in main.commands


def test_forensics_help_lists_match() -> None:
    result = CliRunner().invoke(main, ["forensics", "--help"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "match" in result.output


def test_match_help_lists_schema_option() -> None:
    result = CliRunner().invoke(
        main, ["forensics", "match", "--help"], catch_exceptions=False
    )
    assert result.exit_code == 0
    assert "--schema" in result.output
    assert "--type" in result.output
