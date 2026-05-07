"""Unit tests for ``protokit.schema.lint._cli_utils`` helper internals.

Covers the membership guard in :func:`error_exit_with_code` that uses
an explicit ``if … raise AssertionError`` (survives ``python -O``).
"""

from __future__ import annotations

import pytest

from protokit.schema.lint import _cli_utils as lint_cli_utils


class TestErrorExitWithCode:
    def test_undeclared_code_raises_assertion_error(self) -> None:
        """Passing an unregistered code to error_exit_with_code raises
        AssertionError immediately, before any click.echo or sys.exit.

        This validates the ``if code not in _LINT_ERROR_CODES: raise
        AssertionError`` guard — the guard is intentionally NOT an
        ``assert`` statement so it survives ``python -O``
        (PYTHONOPTIMIZE). See :data:`_cli_utils._LINT_ERROR_CODES`.
        """
        with pytest.raises(AssertionError, match="undeclared lint error code"):
            lint_cli_utils.error_exit_with_code("not-a-real-code", "msg")
