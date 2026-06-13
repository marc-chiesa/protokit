"""Compile-failure dispatch tree tests for :func:`protokit.schema.compile.compile_protos_to_result`.

REGRESSION-CRITICAL coverage of categories #2-#5 of the locked
5-category compile-failure dispatch tree, plus the BaseException
propagation contract.

Each test synthesizes a failure mode via ``monkeypatch`` and asserts
the ``LintCompileDiagnostic`` shape per the field-presence table
locked in Unit 3 of the protokit-lint Delivery 1 plan:

| Category | level     | exception_type           | command/exit_code/stderr |
| -------- | --------- | ------------------------ | ------------------------ |
| #2       | "error"   | "CalledProcessError"     | populated                |
| #3       | "error"   | "FileNotFoundError"      | None                     |
| #4       | "error"   | OSError-subclass name    | None                     |
| #5       | "error"   | unexpected-class name    | None                     |

Unlike :mod:`test_compile_protoxy_fallback`, this module is NOT
gated on ``_has_protoxy()`` — every test forces ``_has_protoxy()``
to ``False`` so the dispatch tree's protoc-only branches run on
every CI matrix axis.

Tests follow the ``class TestX:`` / function-scoped fixture style
established by the rewritten ``tests/core/test_cli_utils.py`` (Unit 1)
and ``tests/schema/lint/test_compile_multi.py`` (Unit 4).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from protokit.schema import compile as compile_module
from protokit.schema.compile import (
    LintCompileDiagnostic,
    compile_protos_to_result,
)

# ---------------------------------------------------------------------------
# Demo proto fixture — mirrors tests/core/test_cli_utils.py:17-32. Most failure
# tests synthesize subprocess.run failures BEFORE the protoc backend reads
# the file, so the file content rarely matters; the fixture exists so the
# input ``Path`` is real (avoids accidental pre-flight oddities).
# ---------------------------------------------------------------------------


_DEMO_PROTO = """\
syntax = "proto3";
package demo;
message User {
    string name = 1;
}
"""


@pytest.fixture
def demo_proto_file(tmp_path: Path) -> Path:
    proto_path = tmp_path / "demo.proto"
    proto_path.write_text(_DEMO_PROTO)
    return proto_path


class TestCompileFailureCategories:
    """Locks the 5-category compile-failure dispatch tree contract.

    Each test synthesizes a failure mode via monkeypatch and asserts
    the ``LintCompileDiagnostic`` shape per the locked field-presence
    table from the plan's Unit 3 specification. The `_has_protoxy()`
    binding inside :mod:`protokit.schema.compile` is patched (NOT
    the one in :mod:`protokit._cli_utils`) — ``compile.py`` uses
    ``from protokit._cli_utils import _has_protoxy``, which rebinds
    the symbol into its own module namespace, so the
    ``compile_module._has_protoxy`` attribute is the call site.
    """

    def test_protoc_subprocess_error_emits_category_2_diagnostic(
        self,
        demo_proto_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Category #2: ``protoc`` subprocess returns non-zero.

        ``CalledProcessError`` from ``subprocess.run`` becomes a
        single ``level="error"`` diagnostic with ``command``,
        ``exit_code``, ``stderr``, ``exception_type`` populated per
        the ``_diagnostic_protoc_subprocess`` factory contract.
        """
        monkeypatch.setattr(compile_module, "_has_protoxy", lambda: False)

        def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise subprocess.CalledProcessError(
                returncode=1,
                cmd=["protoc", "--descriptor_set_out", "..."],
                stderr="some protoc error\n",
            )

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = compile_protos_to_result([demo_proto_file])

        assert result.root_files == ()
        with pytest.raises(KeyError):
            result.pool.FindFileByName("demo.proto")
        assert len(result.diagnostics) == 1
        diag = result.diagnostics[0]
        assert isinstance(diag, LintCompileDiagnostic)
        assert diag.level == "error"
        assert diag.command == ("protoc", "--descriptor_set_out", "...")
        assert diag.exit_code == 1
        # Stripped per the _diagnostic_protoc_subprocess contract.
        assert diag.stderr == "some protoc error"
        assert diag.exception_type == "CalledProcessError"

    def test_both_backends_absent_emits_category_3_diagnostic(
        self,
        demo_proto_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Category #3: ``protoxy`` not importable AND ``protoc`` not on PATH.

        ``FileNotFoundError`` from ``subprocess.run`` becomes a
        single ``level="error"`` diagnostic. The fixed message names
        the install hint substring ``"protokit[compiler]"`` and
        ``"protoc on PATH"`` per the ``_diagnostic_backend_missing``
        factory contract.
        """
        monkeypatch.setattr(compile_module, "_has_protoxy", lambda: False)

        def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise FileNotFoundError("protoc not found")

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = compile_protos_to_result([demo_proto_file])

        assert result.root_files == ()
        with pytest.raises(KeyError):
            result.pool.FindFileByName("demo.proto")
        assert len(result.diagnostics) == 1
        diag = result.diagnostics[0]
        assert diag.level == "error"
        assert diag.exception_type == "FileNotFoundError"
        # Install-hint contract: message must mention both install
        # routes so the user knows how to fix the failure.
        assert "protokit[compiler]" in diag.message
        assert "protoc on PATH" in diag.message

    @pytest.mark.parametrize(
        "exc_cls",
        [PermissionError, BrokenPipeError, OSError],
    )
    def test_oserror_subclasses_emit_category_4_diagnostic(
        self,
        exc_cls: type[OSError],
        demo_proto_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Category #4: ``OSError`` subclasses (PermissionError, etc.).

        Each becomes a ``level="error"`` diagnostic with a synthetic
        message starting ``"compile infrastructure error: "`` per the
        ``_diagnostic_infrastructure`` factory contract.
        """
        monkeypatch.setattr(compile_module, "_has_protoxy", lambda: False)

        def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise exc_cls("synthetic infra failure")

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = compile_protos_to_result([demo_proto_file])

        assert result.root_files == ()
        with pytest.raises(KeyError):
            result.pool.FindFileByName("demo.proto")
        assert len(result.diagnostics) == 1
        diag = result.diagnostics[0]
        assert diag.level == "error"
        assert diag.exception_type == exc_cls.__name__
        assert "compile infrastructure error" in diag.message

    def test_timeout_expired_emits_category_4_diagnostic(
        self,
        demo_proto_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Category #4 (TimeoutExpired branch).

        ``subprocess.TimeoutExpired`` is a sibling of CalledProcessError
        under SubprocessError (NOT an OSError subclass). The dispatch
        tree has a dedicated except clause BEFORE OSError; this test
        locks that the clause routes to ``_diagnostic_infrastructure``
        with ``exception_type='TimeoutExpired'``.
        """
        monkeypatch.setattr(compile_module, "_has_protoxy", lambda: False)

        def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise subprocess.TimeoutExpired(cmd=["protoc"], timeout=1)

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = compile_protos_to_result([demo_proto_file])

        assert result.root_files == ()
        assert len(result.diagnostics) == 1
        diag = result.diagnostics[0]
        assert diag.level == "error"
        assert diag.exception_type == "TimeoutExpired"
        assert "compile infrastructure error" in diag.message

    @pytest.mark.parametrize(
        "exc_cls",
        [RuntimeError, ImportError, MemoryError, TypeError],
    )
    def test_unexpected_exceptions_emit_category_5_diagnostic(
        self,
        exc_cls: type[Exception],
        demo_proto_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Category #5: catch-all for any other ``Exception`` subclass.

        Patches ``compile_module._compile_with_protoc`` directly to
        raise the parametrized class — these failure modes are NOT
        producible by ``subprocess.run`` alone (e.g., ``MemoryError``
        from descriptor pool population, ``TypeError`` from a
        malformed FileDescriptor). Each becomes a ``level="error"``
        diagnostic with ``message`` starting ``"unexpected backend
        exception:"`` per the ``_diagnostic_unexpected`` contract.

        Patches the binding on :mod:`protokit.schema.compile` rather
        than on :mod:`protokit._cli_utils` — ``compile.py`` uses
        ``from ... import _compile_with_protoc``, which copies the
        symbol into its own namespace; patching the source module
        wouldn't intercept the call.
        """
        monkeypatch.setattr(compile_module, "_has_protoxy", lambda: False)

        def fake_protoc(paths, ip, *, include_source_info=False):  # type: ignore[no-untyped-def]
            raise exc_cls("synthetic unexpected failure")

        monkeypatch.setattr(
            compile_module, "_compile_with_protoc", fake_protoc,
        )

        result = compile_protos_to_result([demo_proto_file])

        assert result.root_files == ()
        with pytest.raises(KeyError):
            result.pool.FindFileByName("demo.proto")
        assert len(result.diagnostics) == 1
        diag = result.diagnostics[0]
        assert diag.level == "error"
        assert diag.exception_type == exc_cls.__name__
        assert diag.message.startswith("unexpected backend exception:")

    def test_lint_compile_diagnostic_str_renders_each_combination(
        self,
    ) -> None:
        """Lock the documented format of ``LintCompileDiagnostic.__str__``.

        Four combinations exercise the conditional fragments:
        (1) level + message only, (2) + exception_type, (3) +
        command/exit_code, (4) all populated. A future refactor of the
        format string would surface here.
        """
        # 1: bare info — no optional fragments
        d1 = LintCompileDiagnostic(level="info", message="hello")
        assert str(d1) == "[info] hello"

        # 2: with exception_type only
        d2 = LintCompileDiagnostic(
            level="error", message="boom", exception_type="RuntimeError",
        )
        assert str(d2) == "[error] boom (RuntimeError)"

        # 3: with command + exit_code only
        d3 = LintCompileDiagnostic(
            level="error", message="boom",
            command=("protoc", "--bad"), exit_code=1,
        )
        assert str(d3) == "[error] boom cmd='protoc --bad' exit=1"

        # 4: all populated
        d4 = LintCompileDiagnostic(
            level="error", message="boom",
            command=("protoc",), exit_code=2,
            exception_type="CalledProcessError",
        )
        assert str(d4) == "[error] boom (CalledProcessError) cmd='protoc' exit=2"

    @pytest.mark.parametrize(
        "exc_cls",
        [KeyboardInterrupt, SystemExit, GeneratorExit],
    )
    def test_baseexception_propagates_uncaught(
        self,
        exc_cls: type[BaseException],
        demo_proto_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``BaseException``-but-not-``Exception`` propagates by design.

        Locks the A2-1 contract: the dispatch tree catches
        ``Exception`` only, NOT ``BaseException``. ``KeyboardInterrupt``,
        ``SystemExit``, and ``GeneratorExit`` propagate so users can
        ``Ctrl-C`` a long-running compile and tools that rely on
        ``SystemExit`` for control flow still work.
        """
        monkeypatch.setattr(compile_module, "_has_protoxy", lambda: False)

        def fake_protoc(paths, ip, *, include_source_info=False):  # type: ignore[no-untyped-def]
            raise exc_cls()

        monkeypatch.setattr(
            compile_module, "_compile_with_protoc", fake_protoc,
        )

        with pytest.raises(exc_cls):
            compile_protos_to_result([demo_proto_file])
