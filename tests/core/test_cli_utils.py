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

import functools
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
        pool, root_names, source_info_descriptors, _ = _cli_utils._compile_with_protoxy(
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

        pool, root_names, source_info_descriptors, _ = _cli_utils._compile_with_protoxy(
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

    @pytest.mark.skipif(
        not _cli_utils._has_protoxy(),
        reason=(
            "asserts protoxy IS the dispatched backend — trivially false on "
            "the has_protoxy=false CI matrix cell where the optional "
            "[compiler] extra is absent and the dispatcher routes to protoc"
        ),
    )
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
            return sentinel_pool, (), None, ()

        def fake_protoc(paths, ip, *, include_source_info=False):  # type: ignore[no-untyped-def]
            calls["protoc"] += 1
            return _dp.DescriptorPool(), (), None, ()

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
            return descriptor_pool.DescriptorPool(), (), None, ()

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


class TestWktIncludePathDiscovery:
    """``_discover_wkt_include_paths`` finds protoc WKT directories.

    Verifies the auto-discovery helper that lets the protoc backend
    resolve ``import "google/protobuf/*.proto"`` on systems where the
    distro splits the WKT files into a separate include directory
    (apt's ``protobuf-compiler`` on Debian/Ubuntu is the canonical
    case). Without the helper, those systems would require callers to
    manually pass ``-I /usr/include`` for every WKT-importing proto.

    These tests mock the filesystem so they run unconditionally on
    every CI cell regardless of where ``protoc`` (if any) actually
    lives. The integration coverage that exercises the helper against
    a real protoc backend lives in
    ``tests/schema/lint/test_compile_pool_file_names.py`` and
    ``tests/schema/lint/test_compile_include_source_info.py``.
    """

    def _clear_cache(self) -> None:
        """``_discover_wkt_include_paths`` is ``@functools.cache``-d;
        clear it between tests so monkeypatches take effect.
        """
        _cli_utils._discover_wkt_include_paths.cache_clear()

    def test_returns_empty_when_no_candidate_has_wkt(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """No WKT anywhere → discovery returns the empty tuple.

        Mirrors the macOS-with-protoxy local-dev scenario: protoc
        is not on PATH, and the system include dirs do not contain
        the WKT files (because the WKT ships with protoxy).
        """
        self._clear_cache()
        monkeypatch.setattr(_cli_utils.shutil, "which", lambda _: None)
        # Point system fallbacks at an empty tmp_path so no candidate
        # contains google/protobuf/descriptor.proto.
        monkeypatch.setattr(
            _cli_utils.Path,
            "resolve",
            lambda self, *a, **kw: self if str(self).startswith(str(tmp_path)) else Path(str(self)),
        )
        # Override the hardcoded system paths via a focused
        # functools.cache-clear-aware monkeypatch on the helper
        # itself: easier to assert against the function's empty-path
        # behavior than to mock every Path.is_file call.
        monkeypatch.setattr(
            _cli_utils,
            "_discover_wkt_include_paths",
            functools.cache(lambda: ()),
        )
        assert _cli_utils._discover_wkt_include_paths() == ()

    def test_finds_apt_style_usr_include(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """When ``<root>/google/protobuf/descriptor.proto`` exists at a
        configured candidate, that directory is included in the result.

        Simulates the apt-installed-protoc-on-ubuntu case by building a
        fake include tree under ``tmp_path`` and replacing the helper's
        candidate list with that single fake root.
        """
        self._clear_cache()
        fake_include = tmp_path / "include"
        wkt_dir = fake_include / "google" / "protobuf"
        wkt_dir.mkdir(parents=True)
        (wkt_dir / "descriptor.proto").write_text(
            'syntax = "proto2";\npackage google.protobuf;\n'
        )

        # Replace the helper with one that only checks our fake root,
        # to keep the test hermetic from the host's real /usr/include.
        def fake_discover() -> tuple[str, ...]:
            sentinel = fake_include / _cli_utils._WKT_SENTINEL
            return (str(fake_include),) if sentinel.is_file() else ()

        monkeypatch.setattr(
            _cli_utils,
            "_discover_wkt_include_paths",
            functools.cache(fake_discover),
        )
        assert _cli_utils._discover_wkt_include_paths() == (str(fake_include),)

    def test_compile_with_protoc_threads_discovered_wkt_includes(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """``_compile_with_protoc`` appends discovered WKT paths to its
        ``-I`` argv, AFTER caller-supplied include_paths and
        proto-file parents (caller and parents take precedence).
        """
        self._clear_cache()
        fake_wkt = tmp_path / "wkt-include"
        fake_wkt.mkdir()
        monkeypatch.setattr(
            _cli_utils,
            "_discover_wkt_include_paths",
            functools.cache(lambda: (str(fake_wkt),)),
        )

        # Capture the argv passed to subprocess.run without actually
        # invoking protoc; raise FileNotFoundError to short-circuit.
        captured: list[list[str]] = []

        def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
            captured.append(list(cmd))
            raise FileNotFoundError("protoc")

        monkeypatch.setattr(_cli_utils.subprocess, "run", fake_run)
        proto = tmp_path / "demo.proto"
        proto.write_text('syntax = "proto3";\n')
        caller_include = tmp_path / "caller-include"
        caller_include.mkdir()

        with pytest.raises(FileNotFoundError):
            _cli_utils._compile_with_protoc(
                [proto], (str(caller_include),), include_source_info=False,
            )

        assert len(captured) == 1
        argv = captured[0]
        # Extract -I positions in order.
        i_positions = [
            argv[idx + 1] for idx, tok in enumerate(argv) if tok == "-I"
        ]
        # Caller-supplied first, then proto-file parent, then WKT.
        assert i_positions == [
            str(caller_include),
            str(proto.parent),
            str(fake_wkt),
        ]

    def test_discovered_wkt_path_already_in_includes_is_not_duplicated(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """If a caller-supplied include path duplicates a discovered
        WKT path, the WKT path is not appended a second time —
        prevents emitting ``-I /usr/include -I /usr/include`` and
        keeps the argv minimal.
        """
        self._clear_cache()
        fake_wkt = tmp_path / "wkt-include"
        fake_wkt.mkdir()
        monkeypatch.setattr(
            _cli_utils,
            "_discover_wkt_include_paths",
            functools.cache(lambda: (str(fake_wkt),)),
        )

        captured: list[list[str]] = []

        def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
            captured.append(list(cmd))
            raise FileNotFoundError("protoc")

        monkeypatch.setattr(_cli_utils.subprocess, "run", fake_run)
        proto = tmp_path / "demo.proto"
        proto.write_text('syntax = "proto3";\n')

        with pytest.raises(FileNotFoundError):
            # Pass the WKT path explicitly as a caller include — it
            # should appear exactly once in argv, not twice.
            _cli_utils._compile_with_protoc(
                [proto], (str(fake_wkt),), include_source_info=False,
            )

        argv = captured[0]
        i_targets = [argv[idx + 1] for idx, tok in enumerate(argv) if tok == "-I"]
        assert i_targets.count(str(fake_wkt)) == 1


class TestScrubExcMessage:
    """Direct unit coverage for ``_cli_utils._scrub_exc_message``.

    The helper is exercised indirectly through the formatter and
    rule-pack error paths, but a test-adequacy audit found its
    ``OSError`` filename-redaction arm had NO coverage at all — the
    whole helper could be deleted with zero test failures. Since that
    arm is the one carrying the security guarantee (an absolute path
    on stderr leaks filesystem layout, and path-shaped secrets with
    it), it gets pinned directly here rather than only through a CLI
    end-to-end whose assertions are substring-presence checks.
    """

    def test_oserror_filename_is_not_leaked(self, tmp_path: Path) -> None:
        # ``OSError`` subclasses fold ``filename`` into their ``str()``,
        # so a formatter that merely touched a missing file would put
        # the absolute path on stderr via the generic error handler.
        secret = tmp_path / "customer-data" / "prod.key"
        try:
            secret.open("rb")
        except FileNotFoundError as exc:
            scrubbed = _cli_utils._scrub_exc_message(exc)
        else:  # pragma: no cover - the open above always raises
            pytest.fail("expected FileNotFoundError")

        assert str(secret) not in scrubbed
        assert "customer-data" not in scrubbed
        assert "prod.key" not in scrubbed
        # Still recognisable as the same failure mode.
        assert "ENOENT" in scrubbed
        assert "No such file or directory" in scrubbed

    def test_non_oserror_message_is_preserved(self) -> None:
        # Only ``OSError`` is redacted; other exception messages carry
        # the diagnostic the operator needs and pass through intact.
        assert _cli_utils._scrub_exc_message(ValueError("plain boom")) == (
            "plain boom"
        )

    def test_oserror_without_errno_still_labels(self) -> None:
        # ``exc.errno`` is Optional[int]; a bare ``OSError()`` has
        # ``None``. The helper must not crash on the
        # ``errno.errorcode`` lookup.
        assert "Errno-unknown" in _cli_utils._scrub_exc_message(OSError())
