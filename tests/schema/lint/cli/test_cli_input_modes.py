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
from click.testing import CliRunner, Result
from google.protobuf import descriptor_pb2, descriptor_pool

from protokit.cli import main as protokit_main
from protokit.schema.compile import CompileResult, LintCompileDiagnostic
from protokit.schema.lint import _cli_utils as lint_cli_utils
from protokit.schema.lint.cli import main as lint_main
from tests._pure_python_inventory import skip_under_pure_python

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

    @skip_under_pure_python(
        'pins upb\'s "duplicate symbol" wording; the pure-Python pool reports '
        'a duplicate as TypeError("Conflict register for file ...") instead'
    )
    def test_cross_set_symbol_collision_pins_upb_wording(
        self,
        pool_conflict_a_descriptor_set: Path,
        pool_conflict_b_descriptor_set: Path,
    ) -> None:
        """The wording half of the split (U3, V10).

        Kept as a upb-only pin so a future protobuf release that changes
        "duplicate symbol" still surfaces as a CI failure rather than a silent
        misroute. It cannot be backend-neutral: the two runtimes word this
        condition differently, which is exactly why routing no longer depends
        on the text.
        """
        result = CliRunner().invoke(
            lint_main,
            [
                str(pool_conflict_a_descriptor_set),
                str(pool_conflict_b_descriptor_set),
            ],
        )
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
        # User-actionable hint appears in the message body. Backend-neutral:
        # protokit writes this sentence, not the protobuf runtime.
        assert "include_imports" in result.stderr

    @skip_under_pure_python(
        'pins upb\'s "has not been loaded" wording; the pure-Python pool '
        "surfaces a missing import as KeyError(<dependency name>) instead"
    )
    def test_missing_imports_loaded_marker_pins_upb_wording(
        self, missing_imports_descriptor_set: Path,
    ) -> None:
        """The wording half of the split (U3, V10)."""
        result = CliRunner().invoke(
            lint_main, [str(missing_imports_descriptor_set)],
        )
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

    @skip_under_pure_python(
        'pins upb\'s "couldn\'t resolve name" wording; the pure-Python pool '
        "surfaces a dangling symbol as KeyError(<symbol>) from the resolution "
        "probe instead"
    )
    def test_dangling_symbol_resolve_name_marker_pins_upb_wording(
        self, tmp_path: Path,
    ) -> None:
        """The wording half of the split (U3, V10).

        Rebuilds the same hand-made dangling descriptor set as the
        backend-neutral test above; duplicated rather than shared via a
        fixture so the upb-only pin can be deleted wholesale when the wording
        stops being worth pinning.
        """
        fd = descriptor_pb2.FileDescriptorProto()
        fd.name = "dangling/dangling.proto"
        fd.package = "dangling"
        fd.syntax = "proto3"
        msg = fd.message_type.add()
        msg.name = "Holder"
        field = msg.field.add()
        field.name = "ref"
        field.number = 1
        field.type = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
        field.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
        field.type_name = ".unknown.MissingType"
        fds = descriptor_pb2.FileDescriptorSet()
        fds.file.add().CopyFrom(fd)
        bad = tmp_path / "dangling_upb.descriptor_set"
        bad.write_bytes(fds.SerializeToString())

        result = CliRunner().invoke(lint_main, [str(bad)])
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

    def test_descriptor_the_runtime_rejects_routes_to_pool_conflict(
        self, tmp_path: Path,
    ) -> None:
        """A set that parses but names an out-of-range public dependency.

        upb rejects it with ``TypeError``. The pure-Python runtime raises
        ``IndexError`` from its own descriptor checks, which the loader's
        catch used to miss, so lint crashed with a traceback and exit 1
        instead of routing to a stable ``error[lint-...]`` code.
        """
        fds = descriptor_pb2.FileDescriptorSet()
        fdp = fds.file.add(name="r.proto", package="r", syntax="proto3")
        fdp.message_type.add(name="M")
        fdp.public_dependency.append(0)
        bad = tmp_path / "rejected.descriptor_set"
        bad.write_bytes(fds.SerializeToString())
        result = CliRunner().invoke(lint_main, [str(bad)])
        assert result.exit_code == 2, result.output
        assert "error[lint-pool-conflict]:" in result.stderr

    @pytest.mark.parametrize(
        "raw",
        [
            pytest.param(bytes.fromhex("0a030a01ff"), id="name-only"),
            pytest.param(bytes.fromhex("0a060a01ff1a01ff"), id="name-that-imports-itself"),
        ],
    )
    def test_file_name_that_is_not_utf8_routes_to_bad_input(
        self, tmp_path: Path, raw: bytes,
    ) -> None:
        """A set whose file name is not UTF-8.

        The pure-Python runtime rejects the name with ``UnicodeDecodeError``
        while parsing, which the loader's ``DecodeError`` catch used to miss.
        upb parses it and returns the name as bytes; the name-only set then
        crashed a lint rule reading the file name. Both used to end in a
        traceback and exit 1.
        """
        bad = tmp_path / "not_utf8.descriptor_set"
        bad.write_bytes(raw)
        result = CliRunner().invoke(lint_main, [str(bad)])
        assert result.exit_code == 2, result.output
        assert "error[lint-bad-input]:" in result.stderr

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


# ---------------------------------------------------------------------------
# File order inside and across descriptor sets (U8, R9)
#
# A descriptor set lists files in whatever order its producer wrote them.
# ``protoc --include_imports`` happens to write dependencies first, but other
# tools, a set merged by hand, or several sets passed in any order need not.
# ---------------------------------------------------------------------------


def _ordered_file(
    name: str, message: str, *deps: tuple[str, str],
) -> descriptor_pb2.FileDescriptorProto:
    """``u8/<name>.proto`` in package ``u8``: one message, one field per
    ``(file, message)`` dependency, typed with that dependency's message."""
    fd = descriptor_pb2.FileDescriptorProto(
        name=f"u8/{name}.proto", package="u8", syntax="proto3",
    )
    msg = fd.message_type.add(name=message)
    for number, (dep_file, dep_message) in enumerate(deps, start=1):
        fd.dependency.append(f"u8/{dep_file}.proto")
        msg.field.add(
            name=f"{dep_file}_ref", number=number,
            label=descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL,
            type=descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE,
            type_name=f".u8.{dep_message}",
        )
    return fd


def _write_set(path: Path, *files: descriptor_pb2.FileDescriptorProto) -> Path:
    path.write_bytes(descriptor_pb2.FileDescriptorSet(file=files).SerializeToString())
    return path


_DEP = _ordered_file("dep", "Dep")
_MAIN = _ordered_file("main", "Main", ("dep", "Dep"))


class TestDescriptorSetFileOrder:
    @pytest.mark.parametrize(
        "files",
        [
            (_MAIN, _DEP),
            # Two files import Dep; the second finds it already placed.
            (_MAIN, _ordered_file("side", "Side", ("dep", "Dep")), _DEP),
        ],
        ids=["one-importer", "two-importers"],
    )
    def test_a_set_listing_a_file_before_its_dependency_lints(
        self, tmp_path: Path, files: tuple[descriptor_pb2.FileDescriptorProto, ...],
    ) -> None:
        reversed_set = _write_set(tmp_path / "reversed.pb", *files)
        result = CliRunner().invoke(lint_main, [str(reversed_set)])
        assert result.exit_code == 0, result.output

    def test_sets_passed_before_their_dependencies_lint(self, tmp_path: Path) -> None:
        main_only = _write_set(tmp_path / "main_only.pb", _MAIN)
        dep = _write_set(tmp_path / "dep.pb", _DEP)
        result = CliRunner().invoke(lint_main, [str(main_only), str(dep)])
        assert result.exit_code == 0, result.output

    def test_a_dependency_absent_from_every_set_still_names_its_input(
        self, tmp_path: Path,
    ) -> None:
        """The orphan sits in the second input, so the error must carry that
        input's path even though sorting moved the files around."""
        orphan = _ordered_file("orphan", "Orphan", ("gone", "Gone"))
        main_only = _write_set(tmp_path / "main_only.pb", _MAIN)
        dep = _write_set(tmp_path / "dep.pb", _DEP, orphan)
        result = CliRunner().invoke(lint_main, [str(main_only), str(dep)])
        assert result.exit_code == 2
        assert f"error[lint-missing-imports]: {dep}:" in result.stderr

    @pytest.mark.parametrize(
        "files",
        [
            (
                _ordered_file("left", "Left", ("right", "Right")),
                _ordered_file("right", "Right", ("left", "Left")),
            ),
            (_ordered_file("loop", "Loop", ("loop", "Loop")),),
        ],
        ids=["two-files", "self-import"],
    )
    def test_an_import_cycle_is_a_pool_conflict(
        self, tmp_path: Path, files: tuple[descriptor_pb2.FileDescriptorProto, ...],
    ) -> None:
        cycle = _write_set(tmp_path / "cycle.pb", *files)
        result = CliRunner().invoke(lint_main, [str(cycle)])
        assert result.exit_code == 2
        assert f"error[lint-pool-conflict]: {cycle}:" in result.stderr
        assert "import cycle" in result.stderr

    def test_a_duplicate_file_keeps_its_first_occurrence(self, tmp_path: Path) -> None:
        """The second ``u8/dep.proto`` declares another message; only the
        first is loaded, so ``Main``'s field still resolves to ``Dep``."""
        first = _write_set(tmp_path / "first.pb", _MAIN, _DEP)
        second = _write_set(tmp_path / "second.pb", _ordered_file("dep", "Other"))
        result = CliRunner().invoke(lint_main, [str(first), str(second)])
        assert result.exit_code == 0, result.output
        assert "deduplicated duplicate file path 'u8/dep.proto'" in result.output

    def test_files_report_in_input_order(self, tmp_path: Path) -> None:
        reversed_set = _write_set(tmp_path / "reversed.pb", _MAIN, _DEP)
        result = lint_cli_utils._load_descriptor_sets_to_result((reversed_set,))
        assert result.root_files == ("u8/main.proto", "u8/dep.proto")
        assert result.pool_file_names == ("u8/main.proto", "u8/dep.proto")

    @pytest.mark.parametrize(
        ("inputs", "cycle", "closing_input"),
        [
            # The loop B -> C -> B is reached through A, which is not part of it.
            (
                [[
                    _ordered_file("a", "A", ("b", "B")),
                    _ordered_file("b", "B", ("c", "C")),
                    _ordered_file("c", "C", ("b", "B")),
                ]],
                "u8/b.proto -> u8/c.proto -> u8/b.proto",
                0,
            ),
            # The import that closes the loop sits in the second input.
            (
                [
                    [_ordered_file("left", "Left", ("right", "Right"))],
                    [_ordered_file("right", "Right", ("left", "Left"))],
                ],
                "u8/left.proto -> u8/right.proto -> u8/left.proto",
                1,
            ),
        ],
        ids=["loop-below-the-root", "across-inputs"],
    )
    def test_an_import_cycle_names_the_loop_and_its_input(
        self,
        tmp_path: Path,
        inputs: list[list[descriptor_pb2.FileDescriptorProto]],
        cycle: str,
        closing_input: int,
    ) -> None:
        paths = [
            _write_set(tmp_path / f"set{index}.pb", *files)
            for index, files in enumerate(inputs)
        ]
        result = CliRunner().invoke(lint_main, [str(path) for path in paths])
        assert result.exit_code == 2
        assert (
            f"error[lint-pool-conflict]: {paths[closing_input]}: import cycle: {cycle}"
            in result.stderr
        )

    def test_an_unreadable_input_is_reported_before_a_missing_import(
        self, tmp_path: Path,
    ) -> None:
        """Every input is read before any file is loaded, so the second
        input's parse failure wins over the first input's missing import."""
        orphan = _write_set(
            tmp_path / "orphan.pb", _ordered_file("orphan", "Orphan", ("gone", "Gone")),
        )
        corrupt = tmp_path / "corrupt.pb"
        corrupt.write_bytes(b"\xff")
        result = CliRunner().invoke(lint_main, [str(orphan), str(corrupt)])
        assert result.exit_code == 2
        assert f"error[lint-bad-input]: {corrupt}:" in result.stderr
        assert "lint-missing-imports" not in result.stderr


# ---------------------------------------------------------------------------
# Every root named with --proto is linted, or the run fails (U9, R8)
#
# The compile helpers keep a root only when the backend emitted the name they
# predicted for it. A path stepping through ``..`` was predicted wrongly, so
# the root dropped out and lint exited 0 without linting it. Any root that
# still fails to come back (protoc's ``-I VIRTUAL=DIR`` mapping renames it)
# now exits 2 naming the path.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parents[4]

_GOOD = 'syntax = "proto3";\npackage a;\nmessage Good { string name = 1; }\n'
# A root-level file, so ``package/directory-match`` has nothing to compare.
_BAD = 'syntax = "proto3";\nmessage bad_message { string name = 1; }\n'


def _use_backend(backend: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the compile arm ``lint --proto`` takes."""
    from protokit import _cli_utils
    from protokit.schema import compile as compile_module

    if backend == "protoxy":
        if not _cli_utils._has_protoxy():
            pytest.skip("optional [compiler] extra not installed")
        return
    import shutil

    if shutil.which("protoc") is None:
        pytest.skip("protoc not on PATH (CI installs it on every cell)")
    monkeypatch.setattr(compile_module, "_has_protoxy", lambda: False)


def _proto_tree(root: Path) -> None:
    (root / "proto" / "a").mkdir(parents=True)
    (root / "proto" / "b").mkdir()
    (root / "proto" / "a" / "good.proto").write_text(_GOOD)
    (root / "proto" / "b" / "bad.proto").write_text(_BAD)


@pytest.mark.parametrize("backend", ["protoxy", "protoc"])
class TestProtoRootsAreLinted:
    def test_a_root_named_through_dotdot_is_linted(
        self, backend: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _use_backend(backend, monkeypatch)
        monkeypatch.chdir(_REPO_ROOT)
        result = CliRunner().invoke(
            lint_main,
            [
                "--proto",
                "tests/schema/lint/cli/../cli/cli_fixtures/bad_naming.proto",
                "-I", ".",
            ],
        )
        assert result.exit_code == 0, result.output
        assert result.stdout.count("naming/snake-case-fields") == 2
        assert "BadCamelCase" in result.stdout
        assert "with__double" in result.stdout

    def test_two_roots_one_through_dotdot_are_both_linted(
        self, backend: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _use_backend(backend, monkeypatch)
        _proto_tree(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(
            lint_main,
            ["--proto", "proto/a/good.proto", "proto/a/../b/bad.proto", "-I", "proto"],
        )
        assert result.exit_code == 1, result.output
        assert "naming/pascal-case-messages" in result.stdout
        assert "bad_message" in result.stdout


class TestDroppedProtoRoot:
    def test_a_root_protoc_names_differently_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``-I v=proto`` is protoc's VIRTUAL=DIR mapping: protoc names the
        file ``v/b/bad.proto``, which no prediction matches. Lint's ``-I``
        must name an existing directory, so ``v=proto`` exists as one too."""
        _use_backend("protoc", monkeypatch)
        _proto_tree(tmp_path)
        (tmp_path / "v=proto").mkdir()
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(
            lint_main, ["--proto", "proto/b/bad.proto", "-I", "v=proto"],
        )
        assert result.exit_code == 2, result.output
        assert "not linted: proto/b/bad.proto" in result.stderr
        assert "error[lint-compile-failed]: 1 of 1 " in result.stderr
        assert "bad_message" not in result.stdout

    @staticmethod
    def _invoke_dropping(
        tmp_path: Path, names: list[str], keep: tuple[str, ...],
    ) -> Result:
        """Run ``lint --proto`` over ``names`` with a clean compile that
        returns only ``keep`` as ``root_files``.

        The result is built by hand: a real compile of these files would
        either keep every root or fail with its own diagnostics, and either
        way never reach the check under test.
        """
        from protokit.schema.lint import cli as lint_cli_module

        paths = []
        for name in names:
            path = tmp_path / name
            path.write_text(_BAD)
            paths.append(path)
        dropped = CompileResult(
            pool=descriptor_pool.DescriptorPool(),
            root_files=keep,
            pool_file_names=keep,
        )
        with patch.object(
            lint_cli_module, "compile_protos_to_result", return_value=dropped,
        ):
            return CliRunner().invoke(
                lint_main, ["--proto", *(str(p) for p in paths)],
            )

    def test_a_dropped_root_exits_2_naming_only_that_path(
        self, tmp_path: Path,
    ) -> None:
        result = self._invoke_dropping(
            tmp_path, ["first.proto", "second.proto"], keep=("first.proto",),
        )
        assert result.exit_code == 2, result.output
        assert f"not linted: {tmp_path / 'second.proto'}" in result.stderr
        assert str(tmp_path / "first.proto") not in result.stderr
        assert "error[lint-compile-failed]: 1 of 2 " in result.stderr

    def test_a_dropped_path_cannot_forge_a_stable_prefix_line(
        self, tmp_path: Path,
    ) -> None:
        result = self._invoke_dropping(
            tmp_path, ["x\nerror[lint-forged]: y.proto"], keep=(),
        )
        assert result.exit_code == 2, result.output
        assert "not linted: " in result.stderr
        assert not any(
            line.startswith("error[lint-forged]")
            for line in result.stderr.splitlines()
        )


# ---------------------------------------------------------------------------
# Compile diagnostics cannot forge a stable-prefix stderr line
#
# A diagnostic message can carry an input path (the same-basename collision
# names the basename), so a path holding a newline could print a line of its
# own beginning ``error[lint-``, which CI greps. Both echo sites in --proto
# mode now go through ``_safe_for_stderr``, like the detail lines below them.
# ---------------------------------------------------------------------------

_FORGED_NAME = "x\nerror[lint-forged]: y.proto"


def _forged_lines(stderr: str) -> list[str]:
    return [line for line in stderr.splitlines() if line.startswith("error[lint-forged]")]


class TestCompileDiagnosticsCannotForgeLines:
    def test_an_error_diagnostic_naming_the_input(self, tmp_path: Path) -> None:
        paths = []
        for parent in ("a", "b"):
            (tmp_path / parent).mkdir()
            path = tmp_path / parent / _FORGED_NAME
            path.write_text('syntax = "proto3";\n')
            paths.append(str(path))
        result = CliRunner().invoke(lint_main, ["--proto", *paths])
        assert result.exit_code == 2, result.output
        assert "diagnostic[same_basename_collision]: " in result.stderr
        assert _forged_lines(result.stderr) == []

    def test_an_info_diagnostic_naming_the_input(self, tmp_path: Path) -> None:
        from protokit.schema.lint import cli as lint_cli_module

        proto = tmp_path / "clean.proto"
        proto.write_text('syntax = "proto3";\npackage clean;\n')
        info = LintCompileDiagnostic(
            level="info", category="protoxy_fallback", message=_FORGED_NAME,
        )
        compiled = CompileResult(
            pool=descriptor_pool.DescriptorPool(),
            root_files=("clean.proto",),
            pool_file_names=("clean.proto",),
            diagnostics=(info,),
        )
        with patch.object(
            lint_cli_module, "compile_protos_to_result", return_value=compiled,
        ):
            result = CliRunner().invoke(lint_main, ["--proto", str(proto)])
        assert "info[lint-compile]: protoxy_fallback: " in result.stderr
        assert _forged_lines(result.stderr) == []
