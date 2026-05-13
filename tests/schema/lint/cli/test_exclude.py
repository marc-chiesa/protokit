"""End-to-end CLI tests for ``--exclude PATTERN`` (D5 U3, U4).

Covers:

- Happy paths: single pattern, multiple patterns, gitignore-style
  negation, pyproject-sourced exclude with no CLI flag.
- Append semantics: CLI ``--exclude`` patterns combine with pyproject
  ``[tool.protokit.lint] exclude = [...]`` per R13.
- Multi-file pool: a single file excluded; others lint normally;
  descriptor pool still loads every file (per R9).
- ``all_files_excluded`` warning fires when patterns drop every input
  file; engine.run is short-circuited; the warning surfaces in the
  ``lint_json`` formatter's ``runtime_warnings`` array (D5 U4 removed
  the previous ``warning[lint-runtime]:`` stderr loop; structured
  warnings now flow through formatter dispatch only).
- D5 U4 source-aware messages: the all_files_excluded message names
  ``--exclude`` (CLI source), ``[tool.protokit.lint] exclude``
  (pyproject source), or ``--exclude and [tool.protokit.lint] exclude``
  (both) per the R20 attribution contract.

The corresponding ``--no-exclude`` flag (clear-all sentinel + advisory
when combined with ``--exclude``) lives in ``test_no_exclude.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from protokit.schema.lint.cli import main as lint_main
from tests.schema.lint.cli._helpers import runtime_warnings_from_json

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
    # Each fixture file's package matches its directory path so the
    # D6a U6 ``package/directory-match`` rule (now in BUILTIN_PACKS)
    # does not fire on this exclude-feature test. The exclude logic
    # is what's under test here; aligning the packages avoids
    # coupling this test to the directory-match rule.
    for name, pkg in [("api/user.proto", "api"),
                      ("vendor/external.proto", "vendor")]:
        fd = fds.file.add()
        fd.name = name
        fd.syntax = "proto3"
        fd.package = pkg

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
    fd.package = "vendor"  # match directory for package/directory-match (U6)

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
        """Two ``--exclude`` flags both apply (each adds a pattern).

        Both files excluded → all_files_excluded fires in the
        ``runtime_warnings`` JSON array (D5 U4 contract: structured
        warnings via formatter dispatch).
        """
        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--format", "json",
                "--exclude", "vendor/**",
                "--exclude", "api/**",
                str(multi_file_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        warnings = runtime_warnings_from_json(result.stdout)
        categories = [w["category"] for w in warnings]
        assert "all_files_excluded" in categories

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

        D5 U4 F-03 fold-in: the message names BOTH sources
        ("--exclude and [tool.protokit.lint] exclude") so the user
        sees that patterns from both layers contributed.
        """
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            "[tool.protokit.lint]\nexclude = [\"vendor/**\"]\n",
        )
        result = CliRunner().invoke(
            lint_main,
            [
                "--config", str(pyproject),
                "--format", "json",
                "--exclude", "api/**",
                str(multi_file_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        warnings = runtime_warnings_from_json(result.stdout)
        afe = [w for w in warnings if w["category"] == "all_files_excluded"]
        assert len(afe) == 1
        # F-03: source-aware message names BOTH CLI and pyproject.
        msg = afe[0]["message"]
        assert (
            "--exclude and [tool.protokit.lint] exclude" in msg
        ), msg
        assert afe[0]["rule_id"] is None  # BREAKING R18 contract


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

        D5 U4 contract: warning surfaces via the lint_json formatter's
        ``runtime_warnings`` array. F-04 fold-in: ``rule_id`` is
        serialized as JSON ``null`` (not the string ``"None"``).
        """
        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--format", "json",
                "--exclude", "vendor/**",
                str(single_vendor_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        warnings = runtime_warnings_from_json(result.stdout)
        afe = [w for w in warnings if w["category"] == "all_files_excluded"]
        assert len(afe) == 1
        msg = afe[0]["message"]
        # The message names the input count and at least one pattern:
        assert "1 input file(s)" in msg
        assert "vendor/**" in msg
        # F-04 R18 BREAKING contract: rule_id is null for CLI-emitted
        # categories (not the literal string "None"):
        assert afe[0]["rule_id"] is None
        # F-03 source-aware message: CLI-source attribution:
        assert "--exclude patterns" in msg
        assert "[tool.protokit.lint]" not in msg

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
                "--format", "json",
                "--exclude", "**/*",
                str(multi_file_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        warnings = runtime_warnings_from_json(result.stdout)
        afe = [w for w in warnings if w["category"] == "all_files_excluded"]
        assert len(afe) == 1
        assert "2 input file(s)" in afe[0]["message"]
        assert afe[0]["rule_id"] is None

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


# ---------------------------------------------------------------------------
# R21 negative regression test (T-U4-06, 4-way reviewer convergence)
# ---------------------------------------------------------------------------


class TestR21LegacyStderrFormatAbsent:
    """D5 U4 R21 removed the ``warning[lint-runtime]:`` stderr loop;
    D5 U5 reinstated stderr emission under a NEW structured envelope:
    ``protokit lint: warning [{category}]: {message}``. The legacy
    formats (the U3-era ``warning[lint-runtime]:`` prefix and the
    U2-era bare ``protokit lint: --min-severity=...`` breadcrumb)
    must stay deleted. These tests pin that absence — an accidental
    revert that re-emits either legacy shape regresses the BREAKING
    contract carried by CHANGELOG ``BREAKING (D5 U4 — stderr wire
    format)`` and the U5 structured envelope's surface stability.
    """

    def test_human_format_emits_no_warning_lint_runtime_prefix(
        self, multi_file_descriptor_set: Path,
    ) -> None:
        # ``--exclude '**/*'`` guarantees an ``all_files_excluded``
        # runtime warning exists, so we are checking absence on a run
        # that DID produce a runtime warning (not a no-op run).
        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--exclude", "**/*",
                # Default --format=human
                str(multi_file_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "warning[lint-runtime]:" not in result.stderr, (
            "R21 regression: the legacy stderr loop was re-introduced. "
            f"stderr was:\n{result.stderr}"
        )
        # U5 positive assertion: the NEW structured envelope IS
        # present for the all_files_excluded warning, so this test
        # also pins the U5 hook against silent removal.
        assert "warning [all_files_excluded]:" in result.stderr, (
            "U5 regression: the structured human-format hook stopped "
            f"emitting all_files_excluded. stderr was:\n{result.stderr}"
        )

    def test_human_format_emits_no_bare_min_severity_breadcrumb(
        self, multi_file_descriptor_set: Path,
    ) -> None:
        # The U2 legacy breadcrumb shape was
        # ``protokit lint: --min-severity=info relaxes profile floor
        # from warning to info`` — bare prefix, no ``warning
        # [min_severity_relaxed]:`` envelope. U4 removed it; U5
        # re-introduces emission but under the NEW envelope. Pin
        # the LEGACY bare shape absent and the NEW shape present.
        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--min-severity", "info",
                str(multi_file_descriptor_set),
            ],
        )
        assert "protokit lint: --min-severity=" not in result.stderr, (
            "U2 legacy breadcrumb regression: a bare "
            "``protokit lint: --min-severity=...`` line slipped through. "
            f"stderr was:\n{result.stderr}"
        )
        assert "warning [min_severity_relaxed]:" in result.stderr, (
            "U5 regression: the structured human-format hook stopped "
            f"emitting min_severity_relaxed. stderr was:\n{result.stderr}"
        )
