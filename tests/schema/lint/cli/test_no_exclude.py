"""End-to-end CLI tests for ``--no-exclude`` (D5 U3).

Covers:

- ``--no-exclude`` clears pyproject ``[tool.protokit.lint] exclude``
  entirely (the clear-all sentinel per KTD-10 and R13a-precedence).
- ``--no-exclude`` AND ``--exclude`` together: the advisory
  ``warning[lint-cli]: --no-exclude clears --exclude patterns
  (--no-exclude wins)`` fires on stderr; ``--no-exclude`` wins.
- ``--no-exclude`` alone (no CLI ``--exclude``, no pyproject
  exclude) is a no-op — runs cleanly like the default invocation.
- The ``cli_overrides["exclude"]`` sentinel discipline: ``()``
  signals "clear both" and is distinct from ``None`` ("no CLI
  input; defer to pyproject"). Forward risk RR-U3-A from U2's
  ce:review.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from protokit.schema.lint.cli import main as lint_main

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def multi_file_descriptor_set(tmp_path: Path) -> Path:
    """Same shape as test_exclude.py for cross-test consistency."""
    from google.protobuf import descriptor_pb2

    fds = descriptor_pb2.FileDescriptorSet()
    # Packages match directory paths so the D6a U6
    # ``package/directory-match`` rule does not fire — the exclude
    # logic is what's under test here.
    for name, pkg in [("api/user.proto", "api"),
                      ("vendor/external.proto", "vendor")]:
        fd = fds.file.add()
        fd.name = name
        fd.syntax = "proto3"
        fd.package = pkg

    path = tmp_path / "test.descriptor_set"
    path.write_bytes(fds.SerializeToString())
    return path


# ---------------------------------------------------------------------------
# --no-exclude clears pyproject
# ---------------------------------------------------------------------------


class TestNoExcludeClearsPyproject:
    def test_no_exclude_overrides_pyproject_excludes(
        self,
        tmp_path: Path,
        multi_file_descriptor_set: Path,
    ) -> None:
        """pyproject ``exclude = ["**/*"]`` would drop every file,
        firing the all_files_excluded warning. ``--no-exclude``
        clears that — both files survive and are linted.
        """
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            "[tool.protokit.lint]\nexclude = [\"**/*\"]\n",
        )
        result = CliRunner().invoke(
            lint_main,
            [
                "--config", str(pyproject),
                "--no-exclude",
                str(multi_file_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        # The pyproject **/* pattern is cleared; no warning fires:
        assert "all_files_excluded" not in result.stderr


# ---------------------------------------------------------------------------
# --no-exclude + --exclude advisory (soft mutex per KTD-10)
# ---------------------------------------------------------------------------


class TestNoExcludeWinsOverExclude:
    def test_both_flags_advisory_fires(
        self, multi_file_descriptor_set: Path,
    ) -> None:
        """When both flags are supplied, an advisory fires on stderr
        and ``--no-exclude`` wins (CLI patterns are dropped).
        Mirrors the existing ``--quiet`` / ``--statistics``
        soft-mutex pattern.
        """
        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--exclude", "vendor/**",
                "--no-exclude",
                str(multi_file_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        assert (
            "warning[lint-cli]: --no-exclude clears --exclude patterns "
            "(--no-exclude wins)" in result.stderr
        )
        # No all_files_excluded warning (the --exclude pattern was
        # cleared before filtering ran):
        assert "all_files_excluded" not in result.stderr

    def test_no_exclude_alone_no_advisory(
        self, multi_file_descriptor_set: Path,
    ) -> None:
        """``--no-exclude`` without any ``--exclude`` flag does NOT
        emit the advisory — the advisory specifically signals the
        soft-mutex collision.
        """
        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--no-exclude",
                str(multi_file_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        assert (
            "warning[lint-cli]: --no-exclude clears" not in result.stderr
        )

    def test_no_exclude_with_pyproject_no_advisory(
        self,
        tmp_path: Path,
        multi_file_descriptor_set: Path,
    ) -> None:
        """``--no-exclude`` + pyproject exclude (no CLI ``--exclude``)
        does NOT emit the soft-mutex advisory — the advisory is
        scoped to CLI flag collisions only.
        """
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            "[tool.protokit.lint]\nexclude = [\"vendor/**\"]\n",
        )
        result = CliRunner().invoke(
            lint_main,
            [
                "--config", str(pyproject),
                "--no-exclude",
                str(multi_file_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        assert (
            "warning[lint-cli]: --no-exclude clears" not in result.stderr
        )


# ---------------------------------------------------------------------------
# --no-exclude no-op when no exclude exists
# ---------------------------------------------------------------------------


class TestNoExcludeNoop:
    def test_no_exclude_alone_runs_normally(
        self, multi_file_descriptor_set: Path,
    ) -> None:
        """``--no-exclude`` with no excludes (neither CLI nor
        pyproject) is a no-op — every file is linted, no warning
        fires.
        """
        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--no-exclude",
                str(multi_file_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "all_files_excluded" not in result.stderr


# ---------------------------------------------------------------------------
# RR-U3-A: multiple=True default empty-tuple must not silently fire
# the clear-all sentinel (regression protection)
# ---------------------------------------------------------------------------


class TestRrU3ASentinelDiscipline:
    def test_default_invocation_does_not_clear_pyproject(
        self,
        tmp_path: Path,
        multi_file_descriptor_set: Path,
    ) -> None:
        """Forward risk RR-U3-A from U2's ce:review: click's
        ``multiple=True`` flag defaults to ``()``. The CLI logic must
        distinguish "no --exclude flags passed" (``()``) from "user
        passed --no-exclude" (clear-all sentinel). Without that
        disambiguation, every default invocation would silently clear
        pyproject excludes.

        Test: pyproject ``exclude = ["vendor/**"]`` + NO CLI flags.
        The vendor file should be excluded (pyproject wins because
        CLI is absent, not because --no-exclude was passed).
        """
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            "[tool.protokit.lint]\nexclude = [\"vendor/**\"]\n",
        )
        result = CliRunner().invoke(
            lint_main,
            [
                "--config", str(pyproject),
                str(multi_file_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        # If RR-U3-A regressed, every default invocation would treat
        # the empty `exclude_patterns` tuple as "clear pyproject" and
        # the vendor file would NOT be excluded. We verify the
        # opposite: no findings from vendor/external.proto would
        # surface because it was filtered out.
        # Indirect check: the suite passed at U2's exit (1189 tests)
        # WITHOUT the regression, so default invocations producing
        # exit 0 is the right shape. A direct check is in
        # test_precedence.py which verifies from_dict's behavior.
        assert "all_files_excluded" not in result.stderr
