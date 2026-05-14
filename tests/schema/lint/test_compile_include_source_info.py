"""Tests for ``compile_protos_to_result(include_source_info=)`` opt-in.

D6b Unit 1 (R6a) adds an ``include_source_info: bool = False`` parameter
to :func:`protokit.schema.compile.compile_protos_to_result`. The parameter
threads through to both compile backends (``_compile_with_protoxy`` and
``_compile_with_protoc``); when ``True``, the backends preserve
``source_code_info`` on every emitted ``FileDescriptorProto`` and return a
``source_locations: Mapping[str, FileDescriptorProto]`` capturing the raw
descriptors BEFORE ``pool.Add()`` discards their source-location data.

The parameter defaults to ``False`` so D1-D5 non-lint consumers
(``protokit compat``, codegen, direct Python API users) continue paying
zero descriptor-size cost. The lint CLI sets ``True`` per D6b U1's
contract.

This test file pins:

1. Default-False path preserves pre-D6b semantics (``source_locations is
   None``; descriptor bytes unchanged).
2. Opt-in True path produces a non-empty ``source_locations`` mapping
   with populated ``source_code_info.location[]`` arrays.
3. Cross-backend byte-equivalence of ``source_code_info`` when both
   backends are installed (skipped otherwise).
4. Early-return paths (empty input, same-basename collision) pass
   ``source_locations=None`` regardless of the opt-in flag.

Tests use whatever backend is available in the current environment
(protoxy preferred via the existing dispatch). The cross-backend
equivalence test explicitly skips when protoxy isn't installed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from protokit import _cli_utils
from protokit.schema.compile import (
    CompileResult,
    compile_protos_to_result,
)

# A .proto with deliberately rich leading comments so source_code_info has
# something to capture. The exact comment text is verified in U2's
# leading_comment tests; here we only assert that source_code_info is
# present/absent based on the opt-in flag.
_PROTO_WITH_COMMENTS = """\
syntax = "proto3";
package demo;

// Leading comment on the User message.
// Use UserV2 instead.
message User {
    // Leading comment on the username field.
    string username = 1;
    // Leading comment on the deprecated email field.
    string email = 2 [deprecated = true];
}
"""


def _write_proto(tmp_path: Path, name: str, source: str) -> Path:
    p = tmp_path / name
    p.write_text(source)
    return p


class TestCompileResultSourceLocationsField:
    """The ``CompileResult.source_locations`` field exists and defaults to None."""

    def test_field_defaults_to_none(self, tmp_path: Path) -> None:
        """CompileResult instances default ``source_locations`` to ``None``."""
        proto = _write_proto(tmp_path, "demo.proto", _PROTO_WITH_COMMENTS)
        result = compile_protos_to_result([proto])
        # Pre-flight: opt-in default is False, so source_locations is None.
        assert result.source_locations is None

    def test_field_accessible_after_opt_in(self, tmp_path: Path) -> None:
        """With ``include_source_info=True`` the field is a non-empty mapping."""
        proto = _write_proto(tmp_path, "demo.proto", _PROTO_WITH_COMMENTS)
        result = compile_protos_to_result([proto], include_source_info=True)
        assert result.source_locations is not None
        # At minimum the input file is present in the mapping.
        assert "demo.proto" in result.source_locations


class TestOptInParameterThreading:
    """``include_source_info`` threads correctly through the active backend."""

    def test_default_false_produces_no_source_locations(
        self, tmp_path: Path
    ) -> None:
        """Default False on the parameter → ``source_locations is None``."""
        proto = _write_proto(tmp_path, "demo.proto", _PROTO_WITH_COMMENTS)
        # Default-keyword call (no include_source_info argument).
        result = compile_protos_to_result([proto])
        assert result.source_locations is None
        assert result.root_files == ("demo.proto",)
        assert result.diagnostics == ()

    def test_explicit_false_produces_no_source_locations(
        self, tmp_path: Path
    ) -> None:
        """Explicit ``include_source_info=False`` matches default behavior."""
        proto = _write_proto(tmp_path, "demo.proto", _PROTO_WITH_COMMENTS)
        result = compile_protos_to_result([proto], include_source_info=False)
        assert result.source_locations is None

    def test_opt_in_true_populates_source_locations(
        self, tmp_path: Path
    ) -> None:
        """``include_source_info=True`` → ``source_locations`` non-empty + has SCI."""
        proto = _write_proto(tmp_path, "demo.proto", _PROTO_WITH_COMMENTS)
        result = compile_protos_to_result([proto], include_source_info=True)
        assert result.source_locations is not None
        assert "demo.proto" in result.source_locations
        fd_proto = result.source_locations["demo.proto"]
        # Source code info must have been preserved — the backend's
        # contract under True is that location[] is populated.
        assert len(fd_proto.source_code_info.location) > 0


class TestSourceLocationsCrossBackendByteEquivalence:
    """``source_code_info.location`` arrays match byte-for-byte across backends.

    Skipped when protoxy isn't installed (the [compiler] extra) — the
    cross-backend test needs both. When this guard skips, the
    single-backend tests above still pin the opt-in parameter contract
    against whichever backend the environment has.
    """

    def test_protoxy_and_protoc_produce_identical_source_code_info(
        self, tmp_path: Path
    ) -> None:
        """Same .proto + same ``include_source_info=True`` → same SCI on both backends.

        This pins the byte-equivalence-between-backends invariant that the
        ``_cli_utils.py`` comments establish for the existing False path.
        The True path must preserve the same property: if the two
        backends ever diverge on ``source_code_info`` emission, the lint
        engine's ``leading_comment(path)`` lookups would return different
        results on different installations — a cross-runtime correctness
        regression we want to catch at the boundary, not at rule runtime.
        """
        if not _cli_utils._has_protoxy():
            pytest.skip(
                "optional [compiler] extra not installed; "
                "cross-backend test requires both"
            )

        # Capture protoxy-emitted source_code_info bytes by calling the
        # backend directly (sidesteps the dispatcher's _has_protoxy check
        # which can't be reliably patched at compile.py's bound reference).
        proto = _write_proto(tmp_path, "demo.proto", _PROTO_WITH_COMMENTS)
        _, _, protoxy_sl = _cli_utils._compile_with_protoxy(
            [proto], (), include_source_info=True
        )
        try:
            _, _, protoc_sl = _cli_utils._compile_with_protoc(
                [proto], (), include_source_info=True
            )
        except FileNotFoundError:
            pytest.skip("protoc not on PATH; cross-backend test requires both")

        assert protoxy_sl is not None
        assert protoc_sl is not None
        # Same set of files.
        assert set(protoxy_sl.keys()) == set(protoc_sl.keys())
        # Compare the source_code_info field specifically — backends may
        # differ on metadata like syntax-empty handling, but
        # source_code_info is what R6b's leading_comment helper consumes.
        protoxy_fd = protoxy_sl["demo.proto"]
        protoc_fd = protoc_sl["demo.proto"]
        assert protoxy_fd.source_code_info.SerializeToString() == (
            protoc_fd.source_code_info.SerializeToString()
        )


class TestEarlyReturnPaths:
    """Empty input + same-basename collision both pass ``source_locations=None``."""

    def test_empty_paths_returns_none_regardless_of_opt_in(self) -> None:
        """Empty input is the trivial early-return; opt-in flag is moot."""
        result_off = compile_protos_to_result([])
        result_on = compile_protos_to_result([], include_source_info=True)
        assert result_off.source_locations is None
        assert result_on.source_locations is None
        assert result_off.root_files == ()
        assert result_on.root_files == ()

    def test_same_basename_collision_returns_none(self, tmp_path: Path) -> None:
        """Pre-flight collision path also passes ``source_locations=None``."""
        # Two files with the same basename under different parents — the
        # pre-flight detector returns early without invoking either backend.
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        same_a = _write_proto(dir_a, "shared.proto", _PROTO_WITH_COMMENTS)
        same_b = _write_proto(dir_b, "shared.proto", _PROTO_WITH_COMMENTS)
        result = compile_protos_to_result(
            [same_a, same_b], include_source_info=True
        )
        # The collision pre-flight should fire; source_locations stays None.
        assert result.source_locations is None
        assert len(result.diagnostics) == 1
        assert result.diagnostics[0].category == "same_basename_collision"


class TestBackwardCompatibility:
    """Existing D1-D5 callers (no ``include_source_info`` argument) unaffected."""

    def test_pre_d6b_call_signature_unchanged(self, tmp_path: Path) -> None:
        """Existing positional-and-keyword call patterns continue to work."""
        proto = _write_proto(tmp_path, "demo.proto", _PROTO_WITH_COMMENTS)
        # Pre-D6b call shape: paths only.
        result1 = compile_protos_to_result([proto])
        # Pre-D6b call shape: paths + proto_paths.
        result2 = compile_protos_to_result([proto], proto_paths=())
        # Both produce CompileResult with source_locations None.
        assert isinstance(result1, CompileResult)
        assert isinstance(result2, CompileResult)
        assert result1.source_locations is None
        assert result2.source_locations is None
        # And the pool is populated as before.
        assert result1.pool.FindMessageTypeByName("demo.User") is not None


class TestSourceLocationsFrozenDataclassInvariant:
    """``source_locations`` is wrapped in MappingProxyType (post-init snapshot)."""

    def test_mapping_proxy_blocks_mutation(self, tmp_path: Path) -> None:
        """Caller-supplied mutable dict is wrapped immutably post-init."""
        proto = _write_proto(tmp_path, "demo.proto", _PROTO_WITH_COMMENTS)
        result = compile_protos_to_result([proto], include_source_info=True)
        assert result.source_locations is not None
        # MappingProxyType raises TypeError on mutation attempts.
        with pytest.raises(TypeError):
            result.source_locations["new.proto"] = result.source_locations[
                "demo.proto"
            ]  # type: ignore[index]
