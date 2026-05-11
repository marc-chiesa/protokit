"""End-to-end CLI tests for ``--config`` / ``--no-config`` flags (D5 U1).

Covers the click-level wire-up:

- ``--config PATH`` accepts a path and routes to
  ``load_pyproject_config``.
- ``--no-config`` bypass.
- ``--config`` and ``--no-config`` mutual exclusion (click UsageError,
  exit 2 — distinct from the loader-side ``pyproject-config-load``
  error code which carries the ``error[lint-...]:`` stable prefix).
- R5a shadow paths propagate via the CLI invocation as exit 2 with
  the ``error[lint-pyproject-config-load]:`` prefix.
- ``--help`` text mentions the new flags.

These tests exercise the full Click flow via ``CliRunner``. Unit-level
behavior of ``load_pyproject_config`` itself is covered by
``tests/schema/lint/_config/test_loader.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from protokit.schema.lint.cli import main as lint_main


def _write_minimal_pyproject(directory: Path) -> Path:
    """Write a pyproject with an empty [tool.protokit.lint] table."""
    path = directory / "pyproject.toml"
    path.write_text("[tool.protokit.lint]\n")
    return path


@pytest.fixture
def descriptor_set(tmp_path: Path) -> Path:
    """Create a minimal valid descriptor set for the lint command's INPUT.

    U1 doesn't yet consume the pyproject_config result, so we just need
    an INPUT that lints cleanly (or fails the lint pipeline AFTER the
    config-loading step). A trivially valid empty descriptor set is
    enough.
    """
    from google.protobuf import descriptor_pb2

    # Minimal valid FileDescriptorSet: one file with no messages.
    fds = descriptor_pb2.FileDescriptorSet()
    fd = fds.file.add()
    fd.name = "test.proto"
    fd.syntax = "proto3"
    fd.package = "test"

    path = tmp_path / "test.descriptor_set"
    path.write_bytes(fds.SerializeToString())
    return path


# ---------------------------------------------------------------------------
# Mutex behavior (R13a-precedence)
# ---------------------------------------------------------------------------


class TestConfigNoConfigMutex:
    def test_config_and_no_config_both_set_is_usage_error(
        self, tmp_path: Path, descriptor_set: Path,
    ) -> None:
        """--config and --no-config together → click UsageError, exit 2.

        Fix #4: assert on ``result.stderr`` (where Click writes
        UsageError output) so the test is symmetric with the
        R5a shadow-path tests in :class:`TestConfigShadowPaths`
        (which assert on ``result.stderr``). On Click 8.3+, the
        ``CliRunner`` constructor no longer accepts ``mix_stderr=False``
        because stderr is captured separately by default; ``result.stderr``
        is already populated for UsageError.
        """
        config = _write_minimal_pyproject(tmp_path)

        result = CliRunner().invoke(
            lint_main,
            ["--config", str(config), "--no-config", str(descriptor_set)],
        )

        assert result.exit_code == 2
        # Click usage errors carry the 'Usage:' prefix on stderr,
        # distinct from the lint-internal 'error[lint-...]:' prefix.
        assert "mutually exclusive" in result.stderr
        assert "Usage:" in result.stderr


# ---------------------------------------------------------------------------
# --no-config bypass
# ---------------------------------------------------------------------------


class TestNoConfigBypass:
    def test_no_config_alone_does_not_load_pyproject(
        self,
        tmp_path: Path,
        descriptor_set: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--no-config bypasses walk-up; even a syntactically-invalid
        nearby pyproject must NOT cause an exit-2 error."""
        # Write a syntactically-broken pyproject in CWD; --no-config should
        # cause the loader to skip it entirely.
        bad_pyproject = tmp_path / "pyproject.toml"
        bad_pyproject.write_text("this = is = totally = broken = toml\n")
        monkeypatch.chdir(tmp_path)

        result = CliRunner().invoke(
            lint_main,
            ["--no-config", str(descriptor_set)],
        )

        # Should NOT be exit 2 from a config-load error. (Exit code may
        # be 0 or 1 depending on lint findings, but never 2.)
        assert result.exit_code != 2, (
            f"--no-config should bypass pyproject loading entirely, but "
            f"got exit_code={result.exit_code} with stderr:\n{result.output}"
        )


# ---------------------------------------------------------------------------
# --config explicit path R5a shadow paths
# ---------------------------------------------------------------------------


class TestConfigShadowPaths:
    def test_config_path_does_not_exist(
        self,
        tmp_path: Path,
        descriptor_set: Path,
    ) -> None:
        """--config pointing at a non-existent path → exit 2 with
        pyproject-config-load prefix."""
        missing = tmp_path / "does_not_exist.toml"

        result = CliRunner().invoke(
            lint_main,
            ["--config", str(missing), str(descriptor_set)],
        )

        assert result.exit_code == 2
        assert "error[lint-pyproject-config-load]:" in result.stderr
        assert "does not exist" in result.stderr

    def test_config_path_no_lint_table(
        self,
        tmp_path: Path,
        descriptor_set: Path,
    ) -> None:
        """--config to a valid pyproject lacking [tool.protokit.lint] is
        strict-mode error (R5a)."""
        path = tmp_path / "config.toml"
        path.write_text("[project]\nname = 'foo'\n")

        result = CliRunner().invoke(
            lint_main,
            ["--config", str(path), str(descriptor_set)],
        )

        assert result.exit_code == 2
        assert "error[lint-pyproject-config-load]:" in result.stderr
        assert "no [tool.protokit.lint] table" in result.stderr

    def test_config_path_invalid_toml(
        self,
        tmp_path: Path,
        descriptor_set: Path,
    ) -> None:
        """--config to invalid TOML → exit 2 with content-safe message."""
        path = tmp_path / "bad.toml"
        path.write_text("this is = not = valid = toml\n")

        result = CliRunner().invoke(
            lint_main,
            ["--config", str(path), str(descriptor_set)],
        )

        assert result.exit_code == 2
        assert "error[lint-pyproject-config-load]:" in result.stderr
        assert "TOML parse error" in result.stderr


# ---------------------------------------------------------------------------
# --config happy path (lint proceeds)
# ---------------------------------------------------------------------------


class TestConfigHappyPath:
    def test_config_valid_pyproject_lint_proceeds(
        self,
        tmp_path: Path,
        descriptor_set: Path,
    ) -> None:
        """--config to a valid pyproject WITH [tool.protokit.lint] table
        → the loader succeeds; lint pipeline runs.

        U1 doesn't yet consume the loaded table, so the resulting exit
        code only depends on the lint findings against the descriptor
        set fixture. It MUST NOT be exit 2 from a config-load error.
        """
        path = _write_minimal_pyproject(tmp_path)

        result = CliRunner().invoke(
            lint_main,
            ["--config", str(path), str(descriptor_set)],
        )

        # The config load must succeed (no pyproject-config-load error).
        # Lint may exit 0 (clean) or 1 (findings) but never 2 from this path.
        assert "error[lint-pyproject-config-load]:" not in result.stderr


# ---------------------------------------------------------------------------
# --help mentions new flags
# ---------------------------------------------------------------------------


class TestHelpMentionsConfigFlags:
    """Click wraps option help text at the terminal width, so phrases
    that span multiple words may break across lines in ``result.output``.
    Normalize whitespace before substring-matching the mutex assertion.
    """

    @staticmethod
    def _normalized(text: str) -> str:
        import re
        return re.sub(r"\s+", " ", text)

    def test_help_shows_config_option(self) -> None:
        result = CliRunner().invoke(lint_main, ["--help"])
        assert result.exit_code == 0
        assert "--config" in result.output
        assert "Mutually exclusive with --no-config" in self._normalized(
            result.output,
        )

    def test_help_shows_no_config_option(self) -> None:
        result = CliRunner().invoke(lint_main, ["--help"])
        assert result.exit_code == 0
        assert "--no-config" in result.output
        assert "Mutually exclusive with --config" in self._normalized(
            result.output,
        )
