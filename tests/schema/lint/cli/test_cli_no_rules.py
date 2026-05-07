"""Tests for R9 no-rules loud failure path.

The always-on BUILTIN_PACKS means the no-rules path is structurally
unreachable in normal operation. This test pins the path against
future regressions (e.g., BUILTIN_PACKS accidentally emptied) by
monkeypatching BUILTIN_PACKS to () at CLI-module scope.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

import protokit.schema.lint.cli as lint_cli_module
from protokit.schema.lint.cli import main as lint_main


class TestNoRulesPath:
    def test_empty_builtin_packs_routes_to_no_rules(
        self,
        clean_descriptor_set: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """R9 no-rules path fires when BUILTIN_PACKS is empty and no
        --rule-pack is supplied.

        Monkeypatches ``protokit.schema.lint.cli.BUILTIN_PACKS`` to ``()``
        so the engine loads zero rules, triggering
        ``error[lint-no-rules]:``. This path is structurally unreachable
        in normal operation and exists to guard against BUILTIN_PACKS
        regressions.
        """
        monkeypatch.setattr(lint_cli_module, "BUILTIN_PACKS", ())
        result = CliRunner().invoke(lint_main, [str(clean_descriptor_set)])
        assert result.exit_code == 2
        assert "error[lint-no-rules]:" in result.stderr
