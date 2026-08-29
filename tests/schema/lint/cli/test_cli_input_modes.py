"""U2 tests for ``protokit lint`` input modes + helper edge cases.

Covers descriptor-set mode, ``--proto`` source mode,
multi-path dedup, and the four input-side error codes
(``bad-input``, ``pool-conflict``, ``missing-imports``,
``compile-failed``). U3 adds rule-loading flag tests; U4a adds
gating + format flag tests; U4b adds machine-formatter tests.

Per the plan's U2 test obligation, the error-code dispatch tests
exercise actual ``descriptor_pool.Add`` output for all three
observed message shapes:

- ``has not been loaded`` (missing transitive dependency file —
  the protoc-without-include_imports footgun) — covered by the
  ``missing_imports.descriptor_set`` fixture.
- ``couldn't resolve name`` (dangling-symbol reference: a field
  type_name references a FQN whose defining file is not present
  in any descriptor in the set) — covered by the inline
  FileDescriptorProto test below.
- ``duplicate symbol`` (two descriptor sets define the same FQN
  under different file names) — covered by the
  ``pool_conflict_a/b`` fixtures.

If a future protobuf version changes any of these substrings,
the corresponding test fails CI rather than silently misroutes.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from google.protobuf import descriptor_pb2, descriptor_pool

from protokit.cli import main as protokit_main
from protokit.schema.compile import CompileResult, LintCompileDiagnostic
from protokit.schema.lint import _cli_utils as lint_cli_utils
from protokit.schema.lint.cli import main as lint_main

# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


class TestHappyPaths:
    def test_clean_descriptor_set_exits_0(
        self, clean_descriptor_set: Path,
    ) -> None:
        """Demonstrates KD-10 invariant 1 (canary-clean → 0 or 1, never 2).

        The lint_human formatter returns an empty string for the
        no-findings + no-diagnostics path, and ``click.echo`` of an
        empty string is suppressed by the CLI wiring — so ``stdout``
        is empty even though the rules ran. The R25 multi-pack
        provenance line lands on ``stderr`` after D6a Unit 4 grew
        ``BUILTIN_PACKS`` to two members (naming + enum); that
        line is informational metadata, not finding output, and is
        verified separately by tests in
        ``test_cli_profile_resolution.py::TestR25Provenance``.
        """
        result = CliRunner().invoke(lint_main, [str(clean_descriptor_set)])
        assert result.exit_code == 0, result.output
        assert result.stdout == ""

    def test_bad_naming_descriptor_set_renders_findings(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        result = CliRunner().invoke(
            lint_main, [str(bad_naming_descriptor_set)],
        )
        # Exit 0 in U2 (R20 ladder is U4a's job; U2 just runs).
        # Per KD-10 invariant 1, exit 0 is acceptable here.
        assert result.exit_code == 0, result.output
        # Both bad fields fire:
        assert "BadCamelCase" in result.output
        assert "with__double" in result.output
        # The good field does NOT fire:
        assert "good_field_name" not in result.output
        # Rule_id appears in the rendered line.
        assert "naming/snake-case-fields" in result.output

    def test_proto_source_mode_clean(
        self, fixtures_proto_dir: Path,
    ) -> None:
        clean_proto = fixtures_proto_dir / "clean.proto"
        result = CliRunner().invoke(
            lint_main,
            [
                "--proto",
                str(clean_proto),
                "-I", str(fixtures_proto_dir),
            ],
        )
        assert result.exit_code == 0, result.output
        assert result.stdout == ""

    def test_proto_source_mode_with_findings(
        self, fixtures_proto_dir: Path,
    ) -> None:
        """--proto pipeline produces non-empty findings (full chain)."""
        bad_proto = fixtures_proto_dir / "bad_naming.proto"
        result = CliRunner().invoke(
            lint_main,
            [
                "--proto",
                str(bad_proto),
                "-I", str(fixtures_proto_dir),
            ],
        )
        # Exit 0 in U2 (R20 ladder is U4a's job).
        assert result.exit_code == 0, result.output
        # Both bad fields fire via the --proto pipeline:
        assert "BadCamelCase" in result.stdout
        assert "with__double" in result.stdout
        assert "naming/snake-case-fields" in result.stdout

    def test_multi_path_descriptor_set_dedupes_first_wins(
        self, clean_descriptor_set: Path,
    ) -> None:
        # Pass the same descriptor_set twice → second occurrence's
        # fd.name matches seen_names → emit duplicate diagnostic.
        # The diagnostic appears in lint_human output as a
        # `diagnostic[same_basename_collision]: ...` line.
        result = CliRunner().invoke(
            lint_main,
            [str(clean_descriptor_set), str(clean_descriptor_set)],
        )
        assert result.exit_code == 0, result.output
        assert "diagnostic[same_basename_collision]" in result.output
        assert "deduplicated duplicate file path" in result.output


# ---------------------------------------------------------------------------
# Click usage errors (click-owned `Usage:` / `Error:` prefix; exit 2)
# ---------------------------------------------------------------------------


class TestClickUsageErrors:
    def test_zero_positional_args_is_click_usage_error(self) -> None:
        result = CliRunner().invoke(lint_main, [])
        assert result.exit_code == 2
        # Click-owned prefix; NOT lint stable prefix.
        assert "Usage:" in result.output
        assert "error[lint-" not in result.output

    def test_nonexistent_path_is_click_usage_error(self) -> None:
        result = CliRunner().invoke(lint_main, ["/no/such/file.descriptor_set"])
        assert result.exit_code == 2
        assert "Usage:" in result.output

    def test_proto_flag_without_positional_args_is_click_usage_error(
        self,
    ) -> None:
        result = CliRunner().invoke(lint_main, ["--proto"])
        assert result.exit_code == 2
        assert "Usage:" in result.output


# ---------------------------------------------------------------------------
# Stable error-prefix codes (R20a)
# ---------------------------------------------------------------------------


class TestErrorCodes:
    """Stable `error[lint-CODE]:` prefix codes route to stderr.

    Each test asserts the prefix lands on stderr (the contract:
    CI scripts grep stderr for `error[lint-` prefixes) and that
    the message body contains the protobuf-runtime substring
    that drove the dispatch decision (per plan U2 test
    obligation: pin against actual descriptor_pool output).
    """

    def test_malformed_bytes_routes_to_bad_input(
        self, tmp_path: Path,
    ) -> None:
        bad = tmp_path / "not_a_descriptor_set.descriptor_set"
        bad.write_bytes(b"this is not a FileDescriptorSet")
        result = CliRunner().invoke(lint_main, [str(bad)])
        assert result.exit_code == 2
        # Code lands on stderr (NOT merged stdout):
        assert "error[lint-bad-input]:" in result.stderr
        # Path is part of the message body.
        assert str(bad) in result.stderr

    def test_cross_set_symbol_collision_routes_to_pool_conflict(
        self,
        pool_conflict_a_descriptor_set: Path,
        pool_conflict_b_descriptor_set: Path,
    ) -> None:
        result = CliRunner().invoke(
            lint_main,
            [
                str(pool_conflict_a_descriptor_set),
                str(pool_conflict_b_descriptor_set),
            ],
        )
        assert result.exit_code == 2
        assert "error[lint-pool-conflict]:" in result.stderr
        # Pin against actual descriptor_pool wording so a future
        # protobuf release that changes "duplicate symbol" surfaces
        # as a CI failure (not a silent misroute).
        assert "duplicate symbol" in result.stderr.lower()

    def test_missing_imports_routes_to_missing_imports_loaded_marker(
        self, missing_imports_descriptor_set: Path,
    ) -> None:
        """`has not been loaded` shape — descriptor_set built without
        ``protoc --include_imports``, leaving WKT deps unbundled.
        """
        result = CliRunner().invoke(
            lint_main, [str(missing_imports_descriptor_set)],
        )
        assert result.exit_code == 2
        assert "error[lint-missing-imports]:" in result.stderr
        # User-actionable hint appears in the message body.
        assert "include_imports" in result.stderr
        # Pin the protobuf-runtime substring that drove dispatch:
        assert "has not been loaded" in result.stderr.lower()

    def test_missing_imports_routes_to_missing_imports_resolve_name_marker(
        self, tmp_path: Path,
    ) -> None:
        """`couldn't resolve name` shape — a FieldDescriptorProto
        references a type FQN whose defining file is not in any
        descriptor in the set.

        Constructed inline (no .proto fixture) because the failure
        mode requires a hand-built FileDescriptorProto: a field
        with type=TYPE_MESSAGE and type_name pointing at an FQN
        that no other descriptor in the set defines.
        """
        # Build a FileDescriptorProto with a field referencing
        # `.unknown.MissingType` — no other file declares it.
        # fd.name's directory ("dangling/") aligns with fd.package
        # ("dangling") per package/directory-match. The descriptor-pool
        # build crashes before lint rules walk this file today, but
        # alignment is defensive — see Learning 1 (CLI fixture proto
        # hygiene must satisfy BUILTIN_PACKS).
        fd = descriptor_pb2.FileDescriptorProto()
        fd.name = "dangling/dangling.proto"
        fd.package = "dangling"
        fd.syntax = "proto3"
        msg = fd.message_type.add()
        msg.name = "Holder"
        field = msg.field.add()
        field.name = "missing_type_field"
        field.number = 1
        field.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
        field.type = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
        field.type_name = ".unknown.MissingType"

        fds = descriptor_pb2.FileDescriptorSet()
        fds.file.add().CopyFrom(fd)

        bad = tmp_path / "dangling.descriptor_set"
        bad.write_bytes(fds.SerializeToString())

        result = CliRunner().invoke(lint_main, [str(bad)])
        assert result.exit_code == 2
        assert "error[lint-missing-imports]:" in result.stderr
        # Pin the protobuf-runtime substring that drove dispatch:
        assert "couldn't resolve name" in result.stderr.lower()

    def test_unmatched_typeerror_falls_through_to_pool_conflict(
        self,
        clean_descriptor_set: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Unmatched TypeError text routes to pool-conflict (legacy
        fallthrough).

        Future protobuf versions that change either the
        missing-imports wording or the duplicate-symbol wording
        without matching either marker should surface as
        ``lint-pool-conflict`` with the raw exception text
        rather than escape as an unhandled exception.

        ``descriptor_pool.DescriptorPool.Add`` is a C-extension
        method that resists ``unittest.mock.patch`` at the method
        level. Patch the class accessor in the helper's import
        namespace and call the helper directly (bypassing the
        click runner, which would otherwise see SystemExit and
        swallow the exit code rendering).
        """
        fake_pool = MagicMock()
        fake_pool.Add.side_effect = TypeError("synthetic novel TypeError text")

        with patch.object(
            lint_cli_utils.descriptor_pool,
            "DescriptorPool",
            return_value=fake_pool,
        ), pytest.raises(SystemExit) as exc_info:
            lint_cli_utils._load_descriptor_sets_to_result(
                (clean_descriptor_set,),
            )
        assert exc_info.value.code == 2

        captured = capsys.readouterr()
        assert "error[lint-pool-conflict]:" in captured.err
        # Raw text passes through (not pinned to a specific phrase
        # since the whole point of this test is that unmatched text
        # still routes correctly).
        assert "synthetic novel TypeError text" in captured.err

    def test_proto_mode_syntax_error_routes_to_compile_failed(
        self, tmp_path: Path,
    ) -> None:
        bad_proto = tmp_path / "syntax_error.proto"
        bad_proto.write_text(
            "syntax = \"proto3\";\n"
            "package broken;\n"
            "this is not valid proto syntax {{{\n"
        )
        result = CliRunner().invoke(
            lint_main,
            ["--proto", str(bad_proto), "-I", str(tmp_path)],
        )
        assert result.exit_code == 2
        assert "error[lint-compile-failed]:" in result.stderr
        # The diagnostic echo loop emits per-error diagnostic lines
        # to stderr BEFORE the stable error-prefix code. Verify the
        # echo loop runs (regression-protection — a refactor that
        # drops the echo would silence the actionable detail).
        assert "diagnostic[" in result.stderr


class TestCompileFailureDetailReachesStderr:
    """``error[lint-compile-failed]:`` promises "see stderr for details",
    so the compiler's OWN error text has to be on stderr.

    ``diag.message`` is a fixed protokit string ("protoc compilation
    failed"); the actionable ``file:line:col: ...`` text lives only on
    the structured ``stderr`` / ``command`` / ``exit_code`` fields, and
    nothing downstream renders them — no formatter reads ``.stderr``,
    and ``error_exit_with_code`` raises ``SystemExit`` before a
    formatter could run, so even ``--format=json`` cannot recover it.

    The backend is patched rather than driven for real because the
    detail under test is protoc's, and protoc is not a test dependency
    (protoxy is the primary backend here); patching also pins the
    rendering against a known-exact string instead of whatever the
    locally-installed compiler happens to print.
    """

    @staticmethod
    def _result_with(diag: LintCompileDiagnostic) -> CompileResult:
        return CompileResult(
            pool=descriptor_pool.DescriptorPool(), diagnostics=(diag,),
        )

    def test_protoc_stderr_and_invocation_reach_the_user(
        self, tmp_path: Path,
    ) -> None:
        proto = tmp_path / "bad.proto"
        proto.write_text("syntax = \"proto3\";\n")
        diag = LintCompileDiagnostic(
            level="error",
            category="protoc_subprocess",
            message="protoc compilation failed",
            command=("protoc", "--include_imports", str(proto)),
            exit_code=1,
            stderr="bad.proto:3:1: Expected field name.",
            exception_type="CalledProcessError",
        )
        with patch(
            "protokit.schema.lint.cli.compile_protos_to_result",
            return_value=self._result_with(diag),
        ):
            result = CliRunner().invoke(
                lint_main,
                ["--proto", str(proto), "-I", str(tmp_path)],
            )
        assert result.exit_code == 2
        assert "error[lint-compile-failed]:" in result.stderr
        # The whole point: the compiler's own diagnostic text.
        assert "bad.proto:3:1: Expected field name." in result.stderr
        # The failing invocation is reproducible by hand.
        assert "exit=1" in result.stderr
        assert "protoc" in result.stderr

    def test_compiler_stderr_cannot_forge_a_stable_prefix_line(
        self, tmp_path: Path,
    ) -> None:
        """Compiler output is external input. Per
        ``docs/solutions/security-issues/module-name-newline-injection-stderr-forge-2026-05-07.md``
        it must not be able to synthesise a line that begins with a
        stable ``error[lint-...]:`` prefix that CI greps.
        """
        proto = tmp_path / "hostile.proto"
        proto.write_text("syntax = \"proto3\";\n")
        diag = LintCompileDiagnostic(
            level="error",
            category="protoc_subprocess",
            message="protoc compilation failed",
            command=("protoc", str(proto)),
            exit_code=1,
            stderr="real detail\nerror[lint-forged]: not a real error",
            exception_type="CalledProcessError",
        )
        with patch(
            "protokit.schema.lint.cli.compile_protos_to_result",
            return_value=self._result_with(diag),
        ):
            result = CliRunner().invoke(
                lint_main,
                ["--proto", str(proto), "-I", str(tmp_path)],
            )
        assert result.exit_code == 2
        # The text still surfaces (sanitised, not suppressed) ...
        assert "not a real error" in result.stderr
        # ... but never as its own prefix-leading line.
        assert not any(
            line.startswith("error[lint-forged]:")
            for line in result.stderr.splitlines()
        )


# ---------------------------------------------------------------------------
# Cold-import contract (KD-10 invariant 2)
# ---------------------------------------------------------------------------


class TestColdImportContract:
    """KD-10 invariant 2: ``import protokit.schema`` does NOT load lint CLI."""

    def test_protokit_schema_does_not_load_lint_cli(self) -> None:
        # Run in a subprocess so this test isn't polluted by other
        # tests that have already imported the lint CLI.
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import protokit.schema; "
                "import sys; "
                "forbidden = sorted("
                "k for k in sys.modules "
                "if 'protokit.schema.lint.cli' in k "
                "or k == 'protokit.formatters._builtin_lint'); "
                "assert not forbidden, "
                "f'cold-import broken: {forbidden}'; "
                "print('OK')",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"stderr: {result.stderr}\nstdout: {result.stdout}"
        )
        assert "OK" in result.stdout


# ---------------------------------------------------------------------------
# Subcommand discoverability (KD-10 invariant 3)
# ---------------------------------------------------------------------------


class TestDiscoverability:
    def test_lint_appears_in_top_level_help(self) -> None:
        result = CliRunner().invoke(protokit_main, ["--help"])
        assert result.exit_code == 0
        assert "lint" in result.output

    def test_lint_help_renders(self) -> None:
        result = CliRunner().invoke(lint_main, ["--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output
        # Short help phrase from the @click.command decorator.
        assert "schema" in result.output.lower()


# ---------------------------------------------------------------------------
# Regression: existing subcommands still work
# ---------------------------------------------------------------------------


class TestRegressionExistingSubcommands:
    def test_diff_help_unchanged(self) -> None:
        result = CliRunner().invoke(protokit_main, ["diff", "--help"])
        assert result.exit_code == 0

    def test_compat_help_unchanged(self) -> None:
        result = CliRunner().invoke(protokit_main, ["compat", "--help"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Non-error compile diagnostics in --proto mode (Fix X)
# ---------------------------------------------------------------------------


class TestProtoModeNonErrorDiagnostics:
    def test_info_compile_diagnostic_surfaces_to_stderr(
        self, fixtures_proto_dir: Path,
    ) -> None:
        """info/warning-level compile diagnostics from the backend appear on
        stderr as ``info[lint-compile]:`` / ``warning[lint-compile]:`` lines.

        Mocks ``compile_protos_to_result`` in the cli module's namespace to
        return a ``CompileResult`` with a synthetic info-level diagnostic.
        The actual compile pipeline is not exercised — this test pins the
        CLI's diagnostic-emission loop, not the backend's diagnostic
        production.
        """
        from protokit.schema.compile import CompileResult, LintCompileDiagnostic
        from protokit.schema.lint import cli as lint_cli_module

        clean_proto = fixtures_proto_dir / "clean.proto"

        # Build a real CompileResult first so we have a valid pool/root_files:
        from protokit.schema.compile import compile_protos_to_result as real_compile

        real_result = real_compile(
            paths=[clean_proto],
            proto_paths=[str(fixtures_proto_dir)],
        )
        synthetic_info = LintCompileDiagnostic(
            level="info",
            category="protoxy_fallback",
            message="synthetic-info-diagnostic-for-cli-test",
        )
        mocked_result = CompileResult(
            pool=real_result.pool,
            root_files=real_result.root_files,
            diagnostics=(synthetic_info,),
        )

        with patch.object(
            lint_cli_module,
            "compile_protos_to_result",
            return_value=mocked_result,
        ):
            result = CliRunner().invoke(
                lint_main,
                ["--proto", str(clean_proto), "-I", str(fixtures_proto_dir)],
            )

        assert result.exit_code == 0, result.output
        assert "info[lint-compile]:" in result.stderr
        assert "protoxy_fallback" in result.stderr
        assert "synthetic-info-diagnostic-for-cli-test" in result.stderr


# ---------------------------------------------------------------------------
# Fix D: --proto-path advisory in descriptor-set mode
# ---------------------------------------------------------------------------


class TestProtoPathAdvisory:
    def test_proto_path_in_descriptor_set_mode_emits_advisory(
        self, clean_descriptor_set: Path,
    ) -> None:
        """-I in descriptor-set mode emits warning[lint-cli]: advisory on stderr."""
        result = CliRunner().invoke(
            lint_main,
            ["-I", "/tmp", str(clean_descriptor_set)],
        )
        assert result.exit_code == 0, result.output
        assert "warning[lint-cli]:" in result.stderr
        assert "--proto-path ignored" in result.stderr
        assert "descriptor-set mode" in result.stderr

    def test_proto_path_in_proto_mode_does_not_emit_advisory(
        self, fixtures_proto_dir: Path,
    ) -> None:
        """-I in --proto mode is expected and must NOT emit the advisory."""
        clean_proto = fixtures_proto_dir / "clean.proto"
        result = CliRunner().invoke(
            lint_main,
            [
                "--proto",
                str(clean_proto),
                "-I", str(fixtures_proto_dir),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "warning[lint-cli]:" not in result.stderr
        assert "--proto-path ignored" not in result.stderr
