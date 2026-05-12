"""End-to-end CLI tests for ``--exclude PATTERN`` (D5 U3).

Covers:

- Happy paths: single pattern, multiple patterns, gitignore-style
  negation, pyproject-sourced exclude with no CLI flag.
- Append semantics: CLI ``--exclude`` patterns combine with pyproject
  ``[tool.protokit.lint] exclude = [...]`` per R13.
- Multi-file pool: a single file excluded; others lint normally;
  descriptor pool still loads every file (per R9).
- ``all_files_excluded`` warning fires when patterns drop every input
  file; engine.run is short-circuited; the warning surfaces in
  ``warning[lint-runtime]: all_files_excluded: ...`` stderr.

The corresponding ``--no-exclude`` flag (clear-all sentinel + advisory
when combined with ``--exclude``) lives in ``test_no_exclude.py``.
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
    """Create a descriptor set with two .proto files.

    One sits under ``vendor/`` so ``--exclude 'vendor/**'`` patterns
    can drop it; the other sits under ``api/`` so it survives.
    """
    from google.protobuf import descriptor_pb2

    fds = descriptor_pb2.FileDescriptorSet()
    for name in ["api/user.proto", "vendor/external.proto"]:
        fd = fds.file.add()
        fd.name = name
        fd.syntax = "proto3"
        fd.package = "test"

    path = tmp_path / "test.descriptor_set"
    path.write_bytes(fds.SerializeToString())
    return path


@pytest.fixture
def single_vendor_descriptor_set(tmp_path: Path) -> Path:
    """Create a descriptor set with a single ``vendor/`` file.

    When ``--exclude 'vendor/**'`` is applied, this file is dropped
    and the all_files_excluded warning fires.
    """
    from google.protobuf import descriptor_pb2

    fds = descriptor_pb2.FileDescriptorSet()
    fd = fds.file.add()
    fd.name = "vendor/external.proto"
    fd.syntax = "proto3"
    fd.package = "test"

    path = tmp_path / "test.descriptor_set"
    path.write_bytes(fds.SerializeToString())
    return path


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


class TestCliExcludeHappyPath:
    def test_single_pattern_filters_matching_file(
        self, multi_file_descriptor_set: Path,
    ) -> None:
        """``--exclude 'vendor/**'`` drops ``vendor/external.proto``
        but ``api/user.proto`` survives.
        """
        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--exclude", "vendor/**",
                str(multi_file_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        # Engine ran (no all_files_excluded warning):
        assert "all_files_excluded" not in result.stderr

    def test_multiple_patterns_combine(
        self, multi_file_descriptor_set: Path,
    ) -> None:
        """Two ``--exclude`` flags both apply (each adds a pattern)."""
        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--exclude", "vendor/**",
                "--exclude", "api/**",
                str(multi_file_descriptor_set),
            ],
        )
        # Both files excluded → all_files_excluded fires:
        assert result.exit_code == 0, result.output
        assert "warning[lint-runtime]: all_files_excluded:" in result.stderr

    def test_gitignore_negation(
        self, multi_file_descriptor_set: Path,
    ) -> None:
        """``--exclude 'vendor/**' --exclude '!vendor/external.proto'``
        excludes everything under vendor/ except the named file.
        """
        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--exclude", "vendor/**",
                "--exclude", "!vendor/external.proto",
                str(multi_file_descriptor_set),
            ],
        )
        # Both files survive the filter:
        assert result.exit_code == 0, result.output
        assert "all_files_excluded" not in result.stderr


# ---------------------------------------------------------------------------
# Pyproject exclude (no CLI flag)
# ---------------------------------------------------------------------------


class TestPyprojectExclude:
    def test_pyproject_exclude_honored_without_cli_flag(
        self,
        tmp_path: Path,
        multi_file_descriptor_set: Path,
    ) -> None:
        """pyproject ``exclude = ["vendor/**"]`` + no CLI ``--exclude``:
        the pyproject patterns drive filtering. Per the U2 precedence
        contract (CLI ``None`` = "no flag" defers to pyproject).
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
        # The vendor file is dropped; api/user.proto survives → no
        # all_files_excluded warning.
        assert result.exit_code == 0, result.output
        assert "all_files_excluded" not in result.stderr


# ---------------------------------------------------------------------------
# Append semantics (CLI + pyproject)
# ---------------------------------------------------------------------------


class TestCliAppendsToPyproject:
    def test_cli_exclude_appends_to_pyproject_exclude(
        self,
        tmp_path: Path,
        multi_file_descriptor_set: Path,
    ) -> None:
        """pyproject ``exclude = ["vendor/**"]`` + CLI
        ``--exclude 'api/**'``: both apply. Both files excluded →
        all_files_excluded fires.
        """
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            "[tool.protokit.lint]\nexclude = [\"vendor/**\"]\n",
        )
        result = CliRunner().invoke(
            lint_main,
            [
                "--config", str(pyproject),
                "--exclude", "api/**",
                str(multi_file_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "warning[lint-runtime]: all_files_excluded:" in result.stderr


# ---------------------------------------------------------------------------
# all_files_excluded warning
# ---------------------------------------------------------------------------


class TestAllFilesExcludedWarning:
    def test_all_inputs_excluded_emits_warning(
        self, single_vendor_descriptor_set: Path,
    ) -> None:
        """When the pattern matches every input file, the
        ``all_files_excluded`` warning fires CLI-side and
        ``engine.run`` is short-circuited (no findings).
        """
        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--exclude", "vendor/**",
                str(single_vendor_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "warning[lint-runtime]: all_files_excluded:" in result.stderr
        # The warning message names the input count and at least one
        # pattern so users can diagnose:
        assert "1 input file(s)" in result.stderr
        assert "vendor/**" in result.stderr

    def test_glob_matching_all_files_emits_warning(
        self, multi_file_descriptor_set: Path,
    ) -> None:
        """A `**/*` pattern is a sledgehammer that drops every file
        in a multi-file pool. The all_files_excluded warning fires
        with the correct file count (2).
        """
        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--exclude", "**/*",
                str(multi_file_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "warning[lint-runtime]: all_files_excluded:" in result.stderr
        assert "2 input file(s)" in result.stderr

    def test_no_input_files_does_not_fire_warning(
        self, tmp_path: Path,
    ) -> None:
        """When the descriptor set has zero files to begin with, the
        all_files_excluded warning does NOT fire — the empty input is
        a degenerate case, not an exclude-driven empty.
        """
        from google.protobuf import descriptor_pb2

        fds = descriptor_pb2.FileDescriptorSet()
        # Empty: no files added.
        ds = tmp_path / "empty.descriptor_set"
        ds.write_bytes(fds.SerializeToString())

        result = CliRunner().invoke(
            lint_main,
            ["--no-config", "--exclude", "vendor/**", str(ds)],
        )
        # Either the engine handles it cleanly OR a different error
        # surfaces; either way, all_files_excluded should NOT fire
        # because the input was empty, not the post-filter result.
        assert "all_files_excluded" not in result.stderr


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestExcludeErrorPaths:
    def test_no_exclude_pattern_no_filter(
        self, multi_file_descriptor_set: Path,
    ) -> None:
        """Without ``--exclude`` and without pyproject exclude, no
        filter is applied. Sanity check that the default invocation
        is unchanged from D5 U2's behavior.
        """
        result = CliRunner().invoke(
            lint_main,
            ["--no-config", str(multi_file_descriptor_set)],
        )
        assert result.exit_code == 0, result.output
        assert "all_files_excluded" not in result.stderr
