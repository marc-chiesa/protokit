"""Protoxy → protoc fallback tests for :func:`protokit.schema.compile.compile_protos_to_result`.

REGRESSION-CRITICAL coverage of category #1 (the protoxy-fallback
info diagnostic) and the both-fail composition contract — when
``protoxy.compile`` raises ``ProtoxyError`` AND the protoc
re-attempt then ALSO fails, the resulting ``CompileResult`` carries
TWO diagnostics IN ORDER: the info-fallback notice FIRST, the
backend failure SECOND. Locks the A2-2 ordering invariant.

Module-level skip: this module needs ``protoxy`` importable so the
tests can construct ``protoxy.ProtoxyError`` instances. It is
skipped on the CI matrix's ``has_protoxy: false`` cell via
``pytest.importorskip("protoxy")`` at module top — a bare
``import protoxy`` after ``pytestmark`` does NOT skip, because
``pytestmark`` is evaluated AFTER module import and any failed
import surfaces as a collection error.

Per pass-3 doc-review F1 (verified 2026-05-01):
``protoxy.ProtoxyError.__init__(self, message, details, json_details)``
requires THREE positional arguments. ``protoxy.ProtoxyError("msg")``
fails with ``TypeError``. The :func:`_make_protoxy_error` helper
centralizes the constructor so test bodies stay readable.

Reachable both-fail compositions (parametrized in test 2):

- ``info + #2``: protoc subprocess returned non-zero
- ``info + #3``: ``FileNotFoundError`` (protoxy installed, protoc absent)
- ``info + #4``: ``OSError`` subclass during protoc
- ``info + #5``: any other ``Exception`` during protoc
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

# Module-level skip via importorskip: when protoxy is absent, the
# module is skipped at collection time WITHOUT a collection error.
# A bare ``import protoxy`` here would raise ModuleNotFoundError on
# ``has_protoxy: false`` CI cells, turning the cell red instead of
# skipping it. Subsequent imports run only after the skip gate, so
# E402 is suppressed for them.
protoxy = pytest.importorskip("protoxy")

from protokit.schema import compile as compile_module  # noqa: E402
from protokit.schema.compile import (  # noqa: E402
    LintCompileDiagnostic,
    compile_protos_to_result,
)


def _make_protoxy_error(msg: str) -> protoxy.ProtoxyError:
    """Helper: ``protoxy.ProtoxyError`` requires (message, details, json_details).

    Per the protoxy 0.7+ constructor signature (verified pass-3
    F1). Centralizing the helper avoids ``TypeError`` surprises in
    test bodies — ``protoxy.ProtoxyError("msg")`` would fail at
    construction time, masking the real test intent.
    """
    return protoxy.ProtoxyError(msg, [], "[]")


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


class TestCompileProtoxyFallback:
    """Locks the protoxy → protoc fallback contract.

    Test 1 covers the success path (protoxy raises, protoc
    succeeds → one info diagnostic). Test 2 parametrizes over the
    three reachable both-fail compositions to lock the
    diagnostic-ordering invariant (info first, error second).
    """

    def test_protoxy_parse_error_falls_back_to_protoc_with_info_diagnostic(
        self,
        demo_proto_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Category #1 success: protoxy raises, protoc succeeds.

        Patches ``protoxy.compile`` (the actual function the helper
        calls under the hood) to raise a synthetic ``ProtoxyError``,
        AND patches ``compile_module._compile_with_protoc`` to a
        fake that returns a populated ``(pool, root_names)`` tuple.

        The protoc helper is patched (rather than relying on a real
        ``protoc`` binary on PATH) so the test is hermetic — both
        CI cells and dev machines without ``protoc`` installed
        exercise the fallback contract identically. The contract
        under test is ``compile_protos_to_result``'s dispatch, NOT
        the protoc backend itself (which is covered by
        :mod:`tests.schema.lint.test_compile_multi`).

        Expected result: one ``level="info"`` diagnostic noting the
        fallback, AND the pool / root_files returned by the patched
        protoc helper.
        """
        from google.protobuf import descriptor_pb2, descriptor_pool

        def fake_protoxy_compile(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise _make_protoxy_error("synthetic parse error")

        # Build a real, minimal FileDescriptorProto for demo.User so the
        # returned pool round-trips through pool.Add() and the
        # FindMessageTypeByName assertion exercises a real descriptor —
        # not just an empty pool fixture.
        fdp = descriptor_pb2.FileDescriptorProto()
        fdp.name = "demo.proto"
        fdp.package = "demo"
        fdp.syntax = "proto3"
        msg = fdp.message_type.add()
        msg.name = "User"
        field = msg.field.add()
        field.name = "name"
        field.number = 1
        field.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING
        field.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL

        def fake_protoc(paths, ip):  # type: ignore[no-untyped-def]
            pool = descriptor_pool.DescriptorPool()
            pool.Add(fdp)
            return pool, ("demo.proto",)

        monkeypatch.setattr(protoxy, "compile", fake_protoxy_compile)
        monkeypatch.setattr(
            compile_module, "_compile_with_protoc", fake_protoc,
        )

        result = compile_protos_to_result([demo_proto_file])

        # Pool populated by the protoc fallback.
        assert result.pool.FindMessageTypeByName("demo.User").full_name == "demo.User"
        assert result.root_files == ("demo.proto",)
        # Exactly one info diagnostic noting the fallback.
        assert len(result.diagnostics) == 1
        diag = result.diagnostics[0]
        assert isinstance(diag, LintCompileDiagnostic)
        assert diag.level == "info"
        assert diag.exception_type == "ProtoxyError"
        # Message uses the verb form "falling back" — the substring
        # "fall" matches both the verb (current) and the noun
        # ("fallback") so a future stylistic edit can pick either
        # without breaking this regression gate.
        assert "fall" in diag.message

    @pytest.mark.parametrize(
        ("label", "exc", "expected_exception_type"),
        [
            (
                "protoc_called",
                subprocess.CalledProcessError(
                    returncode=1,
                    cmd=["protoc"],
                    stderr="parse error",
                ),
                "CalledProcessError",
            ),
            (
                "file_not_found",
                FileNotFoundError("protoc not found"),
                "FileNotFoundError",
            ),
            (
                "oserror",
                PermissionError("denied"),
                "PermissionError",
            ),
            (
                "unexpected",
                RuntimeError("synthetic"),
                "RuntimeError",
            ),
        ],
    )
    def test_both_fail_composition_parametrized(
        self,
        label: str,
        exc: Exception,
        expected_exception_type: str,
        demo_proto_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Both-backend failure produces TWO diagnostics, info FIRST.

        Patches ``protoxy.compile`` to raise ``ProtoxyError`` (forcing
        the fallback) AND patches the ``_compile_with_protoc`` binding
        on :mod:`protokit.schema.compile` to raise the parametrized
        exception. Expected: ``result.diagnostics`` is a 2-tuple where
        the first entry is the ``level="info"`` fallback notice and
        the second entry is the ``level="error"`` failure diagnostic.

        Locks the A2-2 ordering invariant (info first) so consumers
        scanning ``result.diagnostics`` for the leading entry always
        find the fallback notice — distinguishes "protoxy failed,
        protoc succeeded" (1 info) from "protoxy failed, protoc also
        failed" (1 info + 1 error) by tuple length.

        The ``CalledProcessError`` / ``OSError`` cases route through
        ``subprocess.run`` indirectly via ``_compile_with_protoc``;
        we patch the helper directly here so each parametrized case
        targets a distinct catch clause without depending on the
        helper's internal subprocess plumbing.
        """
        del label  # Used only for parametrize-id readability.

        def fake_protoxy_compile(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise _make_protoxy_error("synthetic parse error")

        def fake_protoc(paths, ip):  # type: ignore[no-untyped-def]
            raise exc

        monkeypatch.setattr(protoxy, "compile", fake_protoxy_compile)
        monkeypatch.setattr(
            compile_module, "_compile_with_protoc", fake_protoc,
        )

        result = compile_protos_to_result([demo_proto_file])

        # Both-fail: empty pool, empty roots.
        assert result.root_files == ()
        with pytest.raises(KeyError):
            result.pool.FindFileByName("demo.proto")

        # 2 diagnostics, info FIRST per A2-2 ordering invariant.
        assert len(result.diagnostics) == 2
        info_diag, error_diag = result.diagnostics
        assert info_diag.level == "info"
        assert info_diag.exception_type == "ProtoxyError"
        # See test 1 above for the "fall" substring rationale.
        assert "fall" in info_diag.message

        assert error_diag.level == "error"
        assert error_diag.exception_type == expected_exception_type
