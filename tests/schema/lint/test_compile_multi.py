"""Multi-path compile tests for :func:`protokit.schema.compile.compile_protos_to_result`.

REGRESSION-CRITICAL coverage of the multi-path compile contract:

- input-order preservation (independent files, cross-file imports)
- shared include path with vendored protos (transitive imports stay
  out of ``root_files`` but reach the pool)
- pre-flight same-basename collision (returns a single
  ``SameBasenameCollision`` diagnostic without invoking either backend)
- empty input (semantically "compiled nothing"; no diagnostics)

Each test that depends on a backend is parametrized so the contract
is asserted on both the protoxy and the protoc paths. The protoxy
cell is skipped when the optional ``[compiler]`` extra is not
installed (matches the CI matrix's ``has_protoxy: false`` cell).

Tests follow the ``class TestX:`` / function-scoped fixture style
established by the rewritten ``tests/test_cli_utils.py`` (Unit 1).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from protokit import _cli_utils
from protokit.schema.compile import (
    CompileResult,
    LintCompileDiagnostic,
    compile_protos_to_result,
)

# ---------------------------------------------------------------------------
# Backend parametrization — protoxy cell skips when the [compiler] extra is
# absent so the protoc cell still runs on every CI matrix axis.
# ---------------------------------------------------------------------------

_BACKEND_PARAMS = [
    pytest.param(
        "protoxy",
        marks=pytest.mark.skipif(
            not _cli_utils._has_protoxy(),
            reason="optional [compiler] extra not installed",
        ),
    ),
    pytest.param("protoc"),
]


# ---------------------------------------------------------------------------
# Proto fixtures — small inline sources keep each test self-describing.
# ---------------------------------------------------------------------------


_PROTO_A = """\
syntax = "proto3";
package demo;
message A {
    string name = 1;
}
"""

_PROTO_B = """\
syntax = "proto3";
package demo;
message B {
    int32 count = 1;
}
"""

_PROTO_B_IMPORTS_A = """\
syntax = "proto3";
package demo;
import "a.proto";
message B {
    demo.A inner = 1;
}
"""

_VENDOR_UTIL = """\
syntax = "proto3";
package vendor;
message Util {
    string token = 1;
}
"""

_USER_MAIN_IMPORTS_VENDOR = """\
syntax = "proto3";
package user;
import "util.proto";
message Main {
    vendor.Util util = 1;
}
"""


class TestCompileProtosToResultMultiPath:
    """Multi-path scenarios for :func:`compile_protos_to_result`.

    Tests 1-3 are parametrized over backends via ``_BACKEND_PARAMS``;
    tests 4 and 5 exercise pre-backend logic (same-basename pre-flight
    and empty-input early returns) so they run once unparametrized.
    """

    @pytest.mark.parametrize("backend", _BACKEND_PARAMS)
    def test_multi_path_independent(
        self,
        backend: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Two independent .proto files in the same dir compile cleanly.

        ``root_files`` preserves input order, both descriptors are
        reachable in the pool, no diagnostics are produced. Locks
        the input-order-preservation invariant for the simple case.
        """
        if backend == "protoc":
            monkeypatch.setattr(_cli_utils, "_has_protoxy", lambda: False)

        a = tmp_path / "a.proto"
        a.write_text(_PROTO_A)
        b = tmp_path / "b.proto"
        b.write_text(_PROTO_B)

        result = compile_protos_to_result([a, b])

        assert isinstance(result, CompileResult)
        assert result.root_files == ("a.proto", "b.proto")
        assert result.pool.FindMessageTypeByName("demo.A").full_name == "demo.A"
        assert result.pool.FindMessageTypeByName("demo.B").full_name == "demo.B"
        assert result.diagnostics == ()

    @pytest.mark.parametrize("backend", _BACKEND_PARAMS)
    def test_multi_path_with_cross_file_imports(
        self,
        backend: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Cross-file imports do NOT alter input-order in ``root_files``.

        ``b.proto`` imports ``a.proto``; passing ``[b, a]`` (REVERSED
        from topological order) MUST yield ``root_files == (b, a)``.
        Locks the "input order, NOT topological" invariant — a future
        refactor can't silently re-sort.

        Implementation note: ``_cli_utils._compile_with_protoxy`` /
        ``_compile_with_protoc`` populate ``root_names`` by iterating
        ``_expected_root_names_ordered(proto_paths_in, includes)``
        — the input-order list — rather than by iterating the
        backend-emitted ``fds.file`` (topological order). This test
        is the regression gate for that ordering invariant.
        """
        if backend == "protoc":
            monkeypatch.setattr(_cli_utils, "_has_protoxy", lambda: False)

        a = tmp_path / "a.proto"
        a.write_text(_PROTO_A)
        b = tmp_path / "b.proto"
        b.write_text(_PROTO_B_IMPORTS_A)

        # Pass in REVERSE input order: b before a.
        result = compile_protos_to_result([b, a])

        # Both reachable in the pool regardless of root order.
        assert result.pool.FindMessageTypeByName("demo.A").full_name == "demo.A"
        b_msg = result.pool.FindMessageTypeByName("demo.B")
        # b's "inner" field references a's message — the descriptors
        # are interlinked through the shared pool.
        assert b_msg.fields_by_name["inner"].message_type.full_name == "demo.A"
        assert result.diagnostics == ()

        # Locked invariant: input order preserved, NOT topological.
        assert result.root_files == ("b.proto", "a.proto")

    @pytest.mark.parametrize("backend", _BACKEND_PARAMS)
    def test_shared_include_path_with_vendored_proto(
        self,
        backend: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A vendored proto reached via ``proto_paths`` is NOT a root.

        The user passes ``user/main.proto`` as the only root; the
        ``vendor/`` directory provides ``util.proto`` as a transitive
        import via the include-path resolution. Expected:
        ``root_files == ("main.proto",)`` (transitive import excluded);
        ``util.proto`` is in the pool but not a root.
        """
        if backend == "protoc":
            monkeypatch.setattr(_cli_utils, "_has_protoxy", lambda: False)

        vendor_dir = tmp_path / "vendor"
        vendor_dir.mkdir()
        util = vendor_dir / "util.proto"
        util.write_text(_VENDOR_UTIL)

        user_dir = tmp_path / "user"
        user_dir.mkdir()
        main = user_dir / "main.proto"
        main.write_text(_USER_MAIN_IMPORTS_VENDOR)

        result = compile_protos_to_result(
            [main],
            proto_paths=(str(vendor_dir),),
        )

        assert result.root_files == ("main.proto",)
        # util.proto reachable via FindFileByName — it's in the pool
        # despite not being a root.
        assert result.pool.FindFileByName("util.proto").name == "util.proto"
        assert result.pool.FindMessageTypeByName("vendor.Util").full_name == "vendor.Util"
        assert result.pool.FindMessageTypeByName("user.Main").full_name == "user.Main"
        assert result.diagnostics == ()

    def test_same_basename_pre_flight_returns_collision_diagnostic(
        self,
        tmp_path: Path,
    ) -> None:
        """Pre-flight rejects same-basename + different-parent inputs.

        Returns a single ``LintCompileDiagnostic`` with
        ``exception_type == "SameBasenameCollision"`` BEFORE invoking
        either backend. The diagnostic message names both colliding
        paths so the consumer can branch on a known input-validation
        category — distinct from category #5 unexpected-exception.

        Pool is a fresh empty ``DescriptorPool`` (no WKTs) and
        ``root_files`` is empty.
        """
        dir1 = tmp_path / "dir1"
        dir1.mkdir()
        x1 = dir1 / "x.proto"
        x1.write_text(_PROTO_A)

        dir2 = tmp_path / "dir2"
        dir2.mkdir()
        x2 = dir2 / "x.proto"
        x2.write_text(_PROTO_B)

        result = compile_protos_to_result([x1, x2])

        assert result.root_files == ()
        # Fresh empty pool — FindFileByName for any name raises KeyError.
        with pytest.raises(KeyError):
            result.pool.FindFileByName("x.proto")
        assert len(result.diagnostics) == 1
        diag = result.diagnostics[0]
        assert isinstance(diag, LintCompileDiagnostic)
        assert diag.level == "error"
        assert diag.exception_type == "SameBasenameCollision"
        # Both source paths appear in the message for actionable output.
        assert str(x1) in diag.message
        assert str(x2) in diag.message

    def test_empty_input(self) -> None:
        """``paths=()`` returns an empty result with no diagnostics.

        Semantically "compiled nothing" — NOT an error. Pool is a
        fresh empty ``DescriptorPool``: ``FindFileByName`` for any
        name raises ``KeyError``.
        """
        result = compile_protos_to_result(())

        assert result.root_files == ()
        assert result.diagnostics == ()
        with pytest.raises(KeyError):
            result.pool.FindFileByName("anything.proto")
