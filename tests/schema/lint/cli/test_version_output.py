"""D6a U9 / U8 R13 — ``protokit lint --version`` surfaces the buf pin.

The top-level ``protokit --version`` (via ``@click.version_option``
at ``src/protokit/cli.py:24``) outputs only the package version.
The lint subcommand adds its own ``--version`` flag that prints
``protokit X.Y.Z (parity: buf v<PIN>)`` so users can verify the
parity reference without reading CI YAML.

Tests cover:
- Flag prints the expected format and exits 0.
- Output contains both the package version and the buf pin.
- ``protokit lint --help`` does NOT include the buf pin (it's a
  ``--version``-specific surface, not help text).
- The pin matches ``_BUF_PARITY_PIN`` in cli.py (single source of
  truth — drift would be caught by the drift-check test but
  pinned here as well for fast-path local feedback).
"""

from __future__ import annotations

from click.testing import CliRunner

from protokit.schema.lint.cli import _BUF_PARITY_PIN
from protokit.schema.lint.cli import main as lint_main


class TestLintVersionFlag:
    """``protokit lint --version`` (D6a U9 / U8 R13)."""

    def test_version_flag_exits_zero(self) -> None:
        result = CliRunner().invoke(lint_main, ["--version"])
        assert result.exit_code == 0, result.output

    def test_version_output_contains_package_version(self) -> None:
        result = CliRunner().invoke(lint_main, ["--version"])
        # The package version is best-effort (falls back to "0.0.0"
        # for an uninstalled checkout). The invariant is that some
        # version string + the parity line both appear.
        assert "protokit " in result.stdout, result.stdout

    def test_version_output_contains_buf_pin(self) -> None:
        result = CliRunner().invoke(lint_main, ["--version"])
        assert f"parity: buf {_BUF_PARITY_PIN}" in result.stdout, (
            f"expected 'parity: buf {_BUF_PARITY_PIN}' in output; "
            f"got {result.stdout!r}"
        )

    def test_version_output_format_matches_contract(self) -> None:
        """The output format is part of the public surface — agents
        and users grep this line. Pin the exact shape so a regex
        like ``protokit (\\S+) \\(parity: buf (v\\S+)\\)`` continues
        to match."""
        result = CliRunner().invoke(lint_main, ["--version"])
        line = result.stdout.strip()
        # One line, ``protokit <version> (parity: buf <pin>)``.
        assert "\n" not in line, f"expected single line; got {line!r}"
        assert line.startswith("protokit ")
        assert line.endswith(f"(parity: buf {_BUF_PARITY_PIN})")

    def test_help_does_not_include_buf_pin_in_output(self) -> None:
        """The buf pin is a ``--version`` specific surface. The
        help text mentions ``--version`` and its purpose (because
        Click renders the flag's help text), but should NOT include
        the resolved pin value v<X> itself (which would require
        running the resolver and exits early)."""
        result = CliRunner().invoke(lint_main, ["--help"])
        assert result.exit_code == 0, result.output
        # The literal pin value (v<X.Y.Z>) MUST NOT appear in --help
        # output. The help text mentions "buf-parity pin" and
        # "v<PIN>" as a placeholder, but no concrete v<X.Y.Z>.
        assert _BUF_PARITY_PIN not in result.output, (
            f"--help should not surface the resolved pin "
            f"{_BUF_PARITY_PIN!r}; got {result.output!r}"
        )

    def test_version_flag_does_not_require_inputs(self) -> None:
        """``--version`` is eager and exits BEFORE Click parses the
        required INPUTS argument. Without this, the flag would fail
        with ``Usage: ... Missing argument 'INPUTS...'``."""
        # No INPUTS provided — the eager callback should fire and
        # exit 0 before Click validates required positional args.
        result = CliRunner().invoke(lint_main, ["--version"])
        assert result.exit_code == 0, (
            f"--version should exit 0 without requiring INPUTS; "
            f"got exit_code={result.exit_code} output={result.output!r}"
        )
