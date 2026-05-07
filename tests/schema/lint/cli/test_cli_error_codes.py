"""Parametrized tests over ``_LINT_ERROR_CODES``.

Single source of truth: the constant tuple lists the closed set of
``error[lint-CODE]:`` exit-2 codes. This file pins the tuple's
contents, its R20a-mandated order, and the helper's per-code
emission shape. Tests for each code's ACTUAL emission paths (e.g.
``bad-input`` from a malformed descriptor set) live in the
per-feature test files (``test_cli_input_modes.py``,
``test_cli_rule_loading.py``, etc.). U4a adds ``format-unavailable``
and ``formatter-exception`` to the tuple; the corresponding
emission tests land alongside the flag work in U4a-3 and U4a-4.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from protokit.schema.lint._cli_utils import _LINT_ERROR_CODES, error_exit_with_code
from protokit.schema.lint.cli import main as lint_main

_EXPECTED_D3_CODES: tuple[str, ...] = (
    "no-rules",
    "unknown-profile",
    "format-unavailable",
    "compile-failed",
    "formatter-exception",
    "bad-input",
    "pool-conflict",
    "missing-imports",
    "rule-collision",
    "rule-pack-load",
)


class TestLintErrorCodesConstant:
    def test_constant_has_exactly_the_d3_set(self) -> None:
        """Closed set check: no rogue codes, no missing codes."""
        assert set(_LINT_ERROR_CODES) == set(_EXPECTED_D3_CODES)

    def test_constant_size_is_ten(self) -> None:
        """R20a says D3 ships 10 codes total."""
        assert len(_LINT_ERROR_CODES) == 10

    def test_constant_order_matches_r20a(self) -> None:
        """Plan locks the tuple order so docs and CI greps stay stable."""
        assert _LINT_ERROR_CODES == _EXPECTED_D3_CODES

    def test_format_unavailable_present(self) -> None:
        assert "format-unavailable" in _LINT_ERROR_CODES

    def test_formatter_exception_present(self) -> None:
        assert "formatter-exception" in _LINT_ERROR_CODES


class TestEachCodeProducesStablePrefix:
    """For every code in the tuple, ``error_exit_with_code`` emits
    ``error[lint-<code>]:`` on stderr and exits with code 2.

    This is the helper-side reachability check. Per-code emission
    via real CLI flows lives in the per-feature test files.
    """

    @pytest.mark.parametrize("code", _LINT_ERROR_CODES)
    def test_helper_emits_stable_prefix_for_code(
        self, code: str, capsys: pytest.CaptureFixture[str],
    ) -> None:
        with pytest.raises(SystemExit) as exc_info:
            error_exit_with_code(code, "synthetic-message")
        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert f"error[lint-{code}]:" in captured.err
        assert "synthetic-message" in captured.err


class TestErrorCodesNotInHelp:
    """R20a says the constant is internal-only; ``--help`` MUST NOT
    enumerate the codes (they live in stderr error messages and the
    epilog, not as a printed list of strings)."""

    def test_help_does_not_dump_constant(self) -> None:
        result = CliRunner().invoke(lint_main, ["--help"])
        assert result.exit_code == 0
        for code in _LINT_ERROR_CODES:
            literal = f"({code!r}, "
            assert literal not in result.output, (
                f"Help text appears to dump the {code!r} entry "
                f"of _LINT_ERROR_CODES verbatim — keep the constant internal."
            )
