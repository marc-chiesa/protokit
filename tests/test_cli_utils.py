"""Tests for the compiler-backend selection in ``protokit._cli_utils``.

Covers the ``protoxy`` preference, the ``protoc`` fallback path,
and the error message when neither is available.

Convention introduced 2026-05-01 in protokit-lint Delivery 1: tests that
require ``protoxy`` to be importable at collection time use the
``pytestmark = pytest.mark.skipif(not _cli_utils._has_protoxy(), ...)``
class-level skip pattern. This lets the new CI matrix's
``has_protoxy: false`` cell skip protoxy-dependent tests cleanly without
collection-time ImportError. Other backend-absence simulations use the
existing monkeypatch pattern (see TestBackendDetection,
TestBackendDispatch, TestLegacyCompileProto for examples).
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

from protokit import _cli_utils

_DEMO_PROTO = """
syntax = "proto3";
package demo;

message User {
    string name = 1;
    int32 age = 2;
}
"""


@pytest.fixture
def demo_proto_file(tmp_path: Path) -> Path:
    proto_path = tmp_path / "demo.proto"
    proto_path.write_text(_DEMO_PROTO)
    return proto_path


class TestBackendDetection:
    @pytest.mark.skipif(
        not _cli_utils._has_protoxy(),
        reason="optional [compiler] extra not installed",
    )
    def test_has_protoxy_returns_true_when_installed(self) -> None:
        """Sanity check — when the dev venv has the compiler extra installed,
        ``_has_protoxy()`` returns True. Skipped on CI cells where the
        ``[compiler]`` extra is intentionally absent (matrix axis
        ``has_protoxy: false``).
        """
        assert _cli_utils._has_protoxy() is True

    def test_has_protoxy_returns_false_when_not_importable(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Simulate protoxy not on the path."""
        real_find_spec = importlib.util.find_spec

        def fake_find_spec(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
            if name == "protoxy":
                return None
            return real_find_spec(name, *args, **kwargs)

        monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
        assert _cli_utils._has_protoxy() is False


@pytest.mark.skipif(
    not _cli_utils._has_protoxy(),
    reason="optional [compiler] extra not installed",
)
class TestProtoxyBackend:
    """Tests that exercise the protoxy backend directly. Skipped on
    CI cells without the ``[compiler]`` extra installed.
    """

    def test_compile_demo_proto_returns_pool_and_root_names(
        self, demo_proto_file: Path,
    ) -> None:
        """Multi-path raising contract: ``_compile_with_protoxy`` returns
        ``(pool, root_names)`` where ``root_names`` is a tuple of the
        ``.proto``-relative names that came from the user's input paths.
        """
        pool, root_names, source_info_descriptors = _cli_utils._compile_with_protoxy(
            [demo_proto_file], (),
        )
        # Pool is fully populated.
        user = pool.FindMessageTypeByName("demo.User")
        assert user.full_name == "demo.User"
        fields = {f.name: f for f in user.fields}
        assert fields["name"].type == fields["name"].TYPE_STRING
        assert fields["age"].type == fields["age"].TYPE_INT32
        # root_names matches the input — basename since parent is the
        # auto-included directory.
        assert root_names == ("demo.proto",)
        # D6b R6a: source_info_descriptors is None by default (no opt-in).
        assert source_info_descriptors is None

    def test_compile_with_explicit_include_path(
        self, tmp_path: Path,
    ) -> None:
        """Cross-file imports: a .proto that imports from a sibling dir
        works when the caller passes the sibling's dir as an include
        path. Only the user's input path appears in root_names; the
        transitively imported proto is in the pool but NOT a root.
        """
        common_dir = tmp_path / "common"
        common_dir.mkdir()
        common_proto = common_dir / "addr.proto"
        common_proto.write_text(
            'syntax = "proto3";\n'
            'package common;\n'
            'message Address { string street = 1; }\n'
        )

        main_dir = tmp_path / "main"
        main_dir.mkdir()
        main_proto = main_dir / "user.proto"
        main_proto.write_text(
            'syntax = "proto3";\n'
            'package demo;\n'
            'import "addr.proto";\n'
            'message User { string name = 1; common.Address addr = 2; }\n'
        )

        pool, root_names, source_info_descriptors = _cli_utils._compile_with_protoxy(
            [main_proto], (str(common_dir),),
        )
        # Both messages reachable.
        assert pool.FindMessageTypeByName("demo.User")
        assert pool.FindMessageTypeByName("common.Address")
        # Only main is a root; addr was a transitive import.
        assert root_names == ("user.proto",)
        # D6b R6a: source_info_descriptors is None by default (no opt-in).
        assert source_info_descriptors is None

    def test_compile_with_protoxy_raises_on_parse_error(
        self, tmp_path: Path,
    ) -> None:
        """Refactored helper RAISES on parse failure (does NOT call
        ``error_exit``). Replaces the prior ``test_compile_failure_exits_with_code_2``
        test, which was testing helper-level SystemExit — wrong layer
        post-refactor. The CLI-level invariant (exit 2 on syntax error)
        is now covered at the legacy adapter level (TestLegacyCompileProto)
        and at the CLI integration level (tests/schema/test_cli.py).
        """
        import protoxy

        bad_proto = tmp_path / "bad.proto"
        bad_proto.write_text('syntax = "proto3";\nmessage {')  # broken
        with pytest.raises(protoxy.ProtoxyError):
            _cli_utils._compile_with_protoxy([bad_proto], ())


class TestBackendDispatch:
    """Tests that ``compile_proto`` (legacy single-path adapter) routes
    to the correct backend and translates raised exceptions into
    ``error_exit`` with the right per-category stderr prefix.

    The per-category stderr prefix contract introduced in the helper
    refactor (locked 2026-05-01 in protokit-lint Delivery 1):

    | Caught class            | error_exit prefix             |
    | ----------------------- | ----------------------------- |
    | protoxy.ProtoxyError    | "protoxy compile failed: "    |
    | ValueError              | "protoxy compile failed: "    |
    | CalledProcessError      | "protoc compile failed: "     |
    | FileNotFoundError       | "compile backend missing: "   |
    | OSError / TimeoutExpired| "compile infrastructure error: " |
    """

    def test_dispatches_to_protoxy_when_available(
        self, demo_proto_file: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``compile_proto`` picks protoxy when importable. Refactored
        fakes return ``(pool, root_names)`` tuples to match the new
        helper signature.
        """
        from google.protobuf import descriptor_pool as _dp
        calls = {"protoxy": 0, "protoc": 0}
        # Capture the exact pool the fake returns so we can verify
        # compile_proto returns identity rather than dropping it.
        sentinel_pool = _dp.DescriptorPool()

        def fake_protoxy(paths, ip, *, include_source_info=False):  # type: ignore[no-untyped-def]
            calls["protoxy"] += 1
            return sentinel_pool, (), None

        def fake_protoc(paths, ip, *, include_source_info=False):  # type: ignore[no-untyped-def]
            calls["protoc"] += 1
            return _dp.DescriptorPool(), (), None

        monkeypatch.setattr(_cli_utils, "_compile_with_protoxy", fake_protoxy)
        monkeypatch.setattr(_cli_utils, "_compile_with_protoc", fake_protoc)
        # Identity-check the return: a future refactor that drops the
        # helper's return value (silently breaking compile_proto's
        # contract) wouldn't pass this assertion.
        result = _cli_utils.compile_proto(demo_proto_file, ())
        assert result is sentinel_pool
        assert calls == {"protoxy": 1, "protoc": 0}

    def test_falls_back_to_protoc_when_protoxy_unavailable(
        self, demo_proto_file: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Without protoxy, ``compile_proto`` routes to the protoc path."""
        calls = {"protoxy": 0, "protoc": 0}

        def fake_protoxy(paths, ip, *, include_source_info=False):  # type: ignore[no-untyped-def]
            calls["protoxy"] += 1
            raise AssertionError("protoxy should not be called")

        def fake_protoc(paths, ip, *, include_source_info=False):  # type: ignore[no-untyped-def]
            calls["protoc"] += 1
            from google.protobuf import descriptor_pool
            return descriptor_pool.DescriptorPool(), (), None

        monkeypatch.setattr(_cli_utils, "_has_protoxy", lambda: False)
        monkeypatch.setattr(_cli_utils, "_compile_with_protoxy", fake_protoxy)
        monkeypatch.setattr(_cli_utils, "_compile_with_protoc", fake_protoc)
        _cli_utils.compile_proto(demo_proto_file, ())
        assert calls == {"protoxy": 0, "protoc": 1}

    def test_protoc_fallback_error_mentions_both_options(
        self,
        demo_proto_file: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """When neither backend is on PATH, the legacy adapter emits the
        ``"compile backend missing: "`` prefix per the stderr contract,
        and the install-hint message names both install routes so users
        know how to fix the failure.
        """
        # Force the protoxy-absent branch.
        monkeypatch.setattr(_cli_utils, "_has_protoxy", lambda: False)
        # Simulate protoc missing: pretend subprocess.run raises
        # FileNotFoundError (same as a truly absent binary).

        def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise FileNotFoundError("protoc not found")

        monkeypatch.setattr(subprocess, "run", fake_run)

        with pytest.raises(SystemExit) as exc:
            _cli_utils.compile_proto(demo_proto_file, ())
        assert exc.value.code == 2
        captured = capsys.readouterr()
        msg = captured.err
        # Stderr-string contract: locked prefix.
        assert "compile backend missing: " in msg
        # Both install routes named in the hint.
        assert "protoxy" in msg
        assert "protokit[compiler]" in msg
        assert "protoc" in msg


class TestResolveExpectedName:
    """Direct tests for ``_resolve_expected_name``.

    The fallback paths (no include matches; literal-prefix mismatch
    after the .resolve() strip) were previously exercised only
    indirectly through the backends. A direct unit-level lock makes
    matcher regressions visible without a full compile run.
    """

    def test_first_include_prefix_match_wins(self) -> None:
        """Walks includes in declared order; first prefix match returns."""
        result = _cli_utils._resolve_expected_name(
            Path("/x/a/b/file.proto"), ["/x/a", "/x/a/b"],
        )
        # Declared-order winner is /x/a -> 'b/file.proto', NOT the more
        # specific /x/a/b. Mirrors backend resolution semantics.
        assert result == "b/file.proto"

    def test_no_include_matches_returns_basename(self) -> None:
        """Falls back to ``p.name`` when no include is a prefix."""
        result = _cli_utils._resolve_expected_name(
            Path("/x/a/file.proto"), ["/y", "/z"],
        )
        assert result == "file.proto"

    def test_empty_includes_returns_basename(self) -> None:
        """Empty include list short-circuits to basename fallback."""
        result = _cli_utils._resolve_expected_name(
            Path("/x/a/file.proto"), [],
        )
        assert result == "file.proto"

    def test_literal_prefix_no_resolve(self, tmp_path: Path) -> None:
        """Symlinked include should NOT be resolved through to realpath.

        Locks the F2 fix: the matcher must use literal string-prefix
        semantics so it agrees with the backends, which pass include
        directories to protoxy/protoc verbatim. A regression that
        re-introduces ``.resolve()`` would break this test.
        """
        real = tmp_path / "real"
        real.mkdir()
        (real / "file.proto").write_text("syntax = \"proto3\";")
        link = tmp_path / "link"
        link.symlink_to(real)

        # Pass the symlinked include path; expect fd.name to be relative
        # to the LITERAL include (not the resolved realpath).
        result = _cli_utils._resolve_expected_name(
            link / "file.proto", [str(link)],
        )
        assert result == "file.proto"


class TestLegacyCompileProto:
    """Tests that exercise ``compile_proto`` (legacy adapter) at the
    error-translation layer. Each test asserts (a) ``SystemExit(2)`` and
    (b) the locked stderr prefix per category. This locks the per-class
    stderr-string contract introduced 2026-05-01 in protokit-lint
    Delivery 1.
    """

    @pytest.mark.skipif(
        not _cli_utils._has_protoxy(),
        reason="optional [compiler] extra not installed",
    )
    def test_protoxy_parse_error_emits_protoxy_compile_failed_prefix(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Replaces the old helper-level ``test_compile_failure_exits_with_code_2``.
        At the legacy adapter level: a syntax error on the protoxy
        backend exits 2 and the locked ``"protoxy compile failed: "``
        prefix appears on stderr.
        """
        bad_proto = tmp_path / "bad.proto"
        bad_proto.write_text('syntax = "proto3";\nmessage {')  # broken
        with pytest.raises(SystemExit) as exc:
            _cli_utils.compile_proto(bad_proto, ())
        assert exc.value.code == 2
        captured = capsys.readouterr()
        assert "protoxy compile failed: " in captured.err

    def test_protoc_subprocess_error_emits_protoc_compile_failed_prefix(
        self,
        demo_proto_file: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The locked ``"protoc compile failed: "`` prefix fires on
        ``CalledProcessError`` from the protoc subprocess.
        """
        monkeypatch.setattr(_cli_utils, "_has_protoxy", lambda: False)

        def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise subprocess.CalledProcessError(
                returncode=1, cmd=["protoc", "..."],
                stderr="syntax error in foo.proto",
            )

        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(SystemExit) as exc:
            _cli_utils.compile_proto(demo_proto_file, ())
        assert exc.value.code == 2
        captured = capsys.readouterr()
        assert "protoc compile failed: " in captured.err
        # Stderr from the subprocess flows into the error message.
        assert "syntax error in foo.proto" in captured.err

    def test_oserror_emits_compile_infrastructure_error_prefix(
        self,
        demo_proto_file: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The locked ``"compile infrastructure error: "`` prefix fires
        on OSError subclasses (e.g., PermissionError).
        """
        monkeypatch.setattr(_cli_utils, "_has_protoxy", lambda: False)

        def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise PermissionError("denied")

        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(SystemExit) as exc:
            _cli_utils.compile_proto(demo_proto_file, ())
        assert exc.value.code == 2
        captured = capsys.readouterr()
        assert "compile infrastructure error: " in captured.err
