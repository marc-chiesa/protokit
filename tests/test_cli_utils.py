"""Tests for the compiler-backend selection in ``protokit._cli_utils``.

Covers the ``protoxy`` preference, the ``protoc`` fallback path,
and the error message when neither is available.
"""

from __future__ import annotations

import importlib.util
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
    def test_has_protoxy_returns_true_when_installed(self) -> None:
        """Sanity check — our dev venv has the compiler extra installed."""
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


class TestProtoxyBackend:
    def test_compile_demo_proto(self, demo_proto_file: Path) -> None:
        """The protoxy path should produce a fully-populated pool."""
        pool = _cli_utils._compile_with_protoxy(demo_proto_file, ())
        user = pool.FindMessageTypeByName("demo.User")
        assert user.full_name == "demo.User"
        fields = {f.name: f for f in user.fields}
        assert fields["name"].type == fields["name"].TYPE_STRING
        assert fields["age"].type == fields["age"].TYPE_INT32

    def test_compile_with_explicit_include_path(
        self, tmp_path: Path,
    ) -> None:
        """A .proto that imports a sibling .proto from another dir
        works when the caller passes the sibling's dir as an
        include path.
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

        pool = _cli_utils._compile_with_protoxy(
            main_proto, (str(common_dir),),
        )
        assert pool.FindMessageTypeByName("demo.User")
        # include_imports=True means the imported type is also in the pool.
        assert pool.FindMessageTypeByName("common.Address")

    def test_compile_failure_exits_with_code_2(
        self, tmp_path: Path,
    ) -> None:
        """A .proto with a syntax error should ``error_exit`` (code 2)."""
        bad_proto = tmp_path / "bad.proto"
        bad_proto.write_text('syntax = "proto3";\nmessage {')  # broken
        with pytest.raises(SystemExit) as exc:
            _cli_utils._compile_with_protoxy(bad_proto, ())
        assert exc.value.code == 2


class TestBackendDispatch:
    def test_dispatches_to_protoxy_when_available(
        self, demo_proto_file: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``compile_proto`` picks protoxy when importable."""
        calls = {"protoxy": 0, "protoc": 0}

        def fake_protoxy(path, paths):  # type: ignore[no-untyped-def]
            calls["protoxy"] += 1
            from google.protobuf import descriptor_pool
            return descriptor_pool.DescriptorPool()

        def fake_protoc(path, paths):  # type: ignore[no-untyped-def]
            calls["protoc"] += 1
            from google.protobuf import descriptor_pool
            return descriptor_pool.DescriptorPool()

        monkeypatch.setattr(_cli_utils, "_compile_with_protoxy", fake_protoxy)
        monkeypatch.setattr(_cli_utils, "_compile_with_protoc", fake_protoc)
        _cli_utils.compile_proto(demo_proto_file, ())
        assert calls == {"protoxy": 1, "protoc": 0}

    def test_falls_back_to_protoc_when_protoxy_unavailable(
        self, demo_proto_file: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Without protoxy, ``compile_proto`` routes to the protoc path."""
        calls = {"protoxy": 0, "protoc": 0}

        def fake_protoxy(path, paths):  # type: ignore[no-untyped-def]
            calls["protoxy"] += 1
            raise AssertionError("protoxy should not be called")

        def fake_protoc(path, paths):  # type: ignore[no-untyped-def]
            calls["protoc"] += 1
            from google.protobuf import descriptor_pool
            return descriptor_pool.DescriptorPool()

        monkeypatch.setattr(_cli_utils, "_has_protoxy", lambda: False)
        monkeypatch.setattr(_cli_utils, "_compile_with_protoxy", fake_protoxy)
        monkeypatch.setattr(_cli_utils, "_compile_with_protoc", fake_protoc)
        _cli_utils.compile_proto(demo_proto_file, ())
        assert calls == {"protoxy": 0, "protoc": 1}

    def test_protoc_fallback_error_mentions_both_options(
        self, demo_proto_file: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When protoxy isn't installed AND protoc isn't on PATH, the
        error message tells the user how to get either.
        """
        # Force the protoxy-absent branch.
        monkeypatch.setattr(_cli_utils, "_has_protoxy", lambda: False)
        # Simulate protoc missing: pretend subprocess.run raises
        # FileNotFoundError (same as a truly absent binary).
        import subprocess
        real_run = subprocess.run

        def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise FileNotFoundError("protoc not found")

        monkeypatch.setattr(subprocess, "run", fake_run)

        with pytest.raises(SystemExit) as exc:
            _cli_utils.compile_proto(demo_proto_file, ())
        assert exc.value.code == 2
        # Restore to not interfere with other tests.
        monkeypatch.setattr(subprocess, "run", real_run)
