"""Tests for ``compile_protos_to_result(include_source_info=)`` opt-in.

D6b Unit 1 (R6a) adds an ``include_source_info: bool = False`` parameter
to :func:`protokit.schema.compile.compile_protos_to_result`. The parameter
threads through to both compile backends (``_compile_with_protoxy`` and
``_compile_with_protoc``); when ``True``, the backends preserve
``source_code_info`` on every emitted ``FileDescriptorProto`` and return a
``source_info_descriptors: Mapping[str, FileDescriptorProto]`` capturing the raw
descriptors BEFORE ``pool.Add()`` discards their source-location data.

The parameter defaults to ``False`` so D1-D5 non-lint consumers
(``protokit compat``, codegen, direct Python API users) continue paying
zero descriptor-size cost. The lint CLI will pass ``True`` in D6b U3
once the comment-aware R6 rules land; until then the default keeps the
pre-D6b zero-cost contract.

This test file pins:

1. Default-False path preserves pre-D6b semantics (``source_info_descriptors is
   None``; ``source_code_info`` absent from pool-loaded descriptors).
2. Opt-in True path produces a non-empty ``source_info_descriptors`` mapping
   with populated ``source_code_info.location[]`` arrays.
3. Cross-backend byte-equivalence of ``source_code_info`` when both
   backends are installed (skipped otherwise).
4. Early-return paths (empty input, same-basename collision) pass
   ``source_info_descriptors=None`` regardless of the opt-in flag.
5. Failure paths with ``include_source_info=True`` still produce
   ``source_info_descriptors=None`` (the irrecoverable-failure clear at
   ``compile.py``'s ``if pool is None`` branch).
6. The parameter value threads through to the backend — a fake that
   captures its received kwargs sees ``True`` when the caller passes
   ``True``.

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
    """The ``CompileResult.source_info_descriptors`` field exists and defaults to None."""

    def test_field_defaults_to_none(self, tmp_path: Path) -> None:
        """CompileResult instances default ``source_info_descriptors`` to ``None``."""
        proto = _write_proto(tmp_path, "demo.proto", _PROTO_WITH_COMMENTS)
        result = compile_protos_to_result([proto])
        # Pre-flight: opt-in default is False, so source_info_descriptors is None.
        assert result.source_info_descriptors is None

    def test_field_accessible_after_opt_in(self, tmp_path: Path) -> None:
        """With ``include_source_info=True`` the field is a non-empty mapping."""
        proto = _write_proto(tmp_path, "demo.proto", _PROTO_WITH_COMMENTS)
        result = compile_protos_to_result([proto], include_source_info=True)
        assert result.source_info_descriptors is not None
        # At minimum the input file is present in the mapping.
        assert "demo.proto" in result.source_info_descriptors


class TestOptInParameterThreading:
    """``include_source_info`` threads correctly through the active backend."""

    def test_default_false_produces_no_source_info_descriptors(
        self, tmp_path: Path
    ) -> None:
        """Default False on the parameter → ``source_info_descriptors is None``."""
        proto = _write_proto(tmp_path, "demo.proto", _PROTO_WITH_COMMENTS)
        # Default-keyword call (no include_source_info argument).
        result = compile_protos_to_result([proto])
        assert result.source_info_descriptors is None
        assert result.root_files == ("demo.proto",)
        assert result.diagnostics == ()

    def test_explicit_false_produces_no_source_info_descriptors(
        self, tmp_path: Path
    ) -> None:
        """Explicit ``include_source_info=False`` matches default behavior."""
        proto = _write_proto(tmp_path, "demo.proto", _PROTO_WITH_COMMENTS)
        result = compile_protos_to_result([proto], include_source_info=False)
        assert result.source_info_descriptors is None

    def test_opt_in_true_populates_source_info_descriptors(
        self, tmp_path: Path
    ) -> None:
        """``include_source_info=True`` → ``source_info_descriptors`` non-empty + has SCI."""
        proto = _write_proto(tmp_path, "demo.proto", _PROTO_WITH_COMMENTS)
        result = compile_protos_to_result([proto], include_source_info=True)
        assert result.source_info_descriptors is not None
        assert "demo.proto" in result.source_info_descriptors
        fd_proto = result.source_info_descriptors["demo.proto"]
        # Source code info must have been preserved — the backend's
        # contract under True is that ``location[]`` is populated AND
        # carries the structural fields R6 rules will consume:
        # ``path`` (the descriptor-graph coordinates) and at least one
        # entry with a leading comment matching the fixture. A
        # populated-but-empty location list would satisfy ``len > 0``
        # while still failing every comment-aware rule, so assert on
        # the fields that actually matter.
        locations = fd_proto.source_code_info.location
        assert len(locations) > 0
        assert any(len(loc.path) > 0 for loc in locations), (
            "expected at least one Location with a non-empty path[]"
        )
        assert any(
            "Leading comment on the User message" in loc.leading_comments
            for loc in locations
        ), "expected the fixture's User-message comment to be captured"


class TestSourceInfoDescriptorsCrossBackendSemanticEquivalence:
    """``source_code_info.location`` comment payloads match across backends.

    Skipped when protoxy isn't installed (the [compiler] extra) — the
    cross-backend test needs both. When this guard skips, the
    single-backend tests above still pin the opt-in parameter contract
    against whichever backend the environment has.

    Note: this used to assert full byte-equivalence on
    ``source_code_info.SerializeToString()``, but protoc 25+ encodes
    location spans slightly differently than the protoc embedded in
    protoxy (older), producing different serialized bytes for the
    same input even though the path→comments mapping the production
    code consumes is unchanged. The test now asserts the semantic
    contract the production code actually depends on — see the test
    docstring below — rather than the strict-bytes contract that
    only held when both backends shipped the same protoc version.
    """

    def test_protoxy_and_protoc_produce_equivalent_path_comment_mapping(
        self, tmp_path: Path
    ) -> None:
        """Same .proto + same ``include_source_info=True`` → same comment payloads on both backends.

        Pins the cross-backend invariant that the lint engine's
        ``leading_comment(path)`` lookups return the same string on
        any installation, regardless of which backend compiled the
        descriptor. ``leading_comment`` consumes only the
        ``(path → leading_comments)`` mapping; backends may differ on
        ``span``, on internal location-tuple ordering, or on whether
        they emit a Location for a path with no comments at all (the
        protoc-version-specific encoding details). Those differences
        are invisible to production code as long as the
        comments-keyed-by-path mapping agrees.
        """
        if not _cli_utils._has_protoxy():
            pytest.skip(
                "optional [compiler] extra not installed; "
                "cross-backend test requires both"
            )

        # Capture protoxy-emitted source_code_info by calling the
        # backend directly (sidesteps the dispatcher's _has_protoxy
        # check which can't be reliably patched at compile.py's bound
        # reference).
        proto = _write_proto(tmp_path, "demo.proto", _PROTO_WITH_COMMENTS)
        _, _, protoxy_sl, _ = _cli_utils._compile_with_protoxy(
            [proto], (), include_source_info=True
        )
        try:
            _, _, protoc_sl, _ = _cli_utils._compile_with_protoc(
                [proto], (), include_source_info=True
            )
        except FileNotFoundError:
            pytest.skip("protoc not on PATH; cross-backend test requires both")

        assert protoxy_sl is not None
        assert protoc_sl is not None
        # Same set of files.
        assert set(protoxy_sl.keys()) == set(protoc_sl.keys())

        protoxy_fd = protoxy_sl["demo.proto"]
        protoc_fd = protoc_sl["demo.proto"]

        def _path_comment_map(
            fd: object,
        ) -> dict[tuple[int, ...], tuple[str, str, tuple[str, ...]]]:
            # Reduce source_code_info to the (path → comments) mapping
            # that leading_comment / trailing_comment / detached_comment
            # helpers actually consume. Both helpers strip whitespace at
            # the call site; do the same normalization here so the
            # comparison is invariant to backend-specific trailing-newline
            # encoding decisions.
            out: dict[tuple[int, ...], tuple[str, str, tuple[str, ...]]] = {}
            for loc in fd.source_code_info.location:
                key = tuple(loc.path)
                value = (
                    loc.leading_comments.strip(),
                    loc.trailing_comments.strip(),
                    tuple(s.strip() for s in loc.leading_detached_comments),
                )
                # Only record paths that carry any comment content; backends
                # may differ on whether they emit empty Locations for
                # comment-less spans.
                if value != ("", "", ()):
                    out[key] = value
            return out

        protoxy_map = _path_comment_map(protoxy_fd)
        protoc_map = _path_comment_map(protoc_fd)
        assert protoxy_map == protoc_map


class TestEarlyReturnPaths:
    """Empty input + same-basename collision both pass ``source_info_descriptors=None``."""

    def test_empty_paths_returns_none_regardless_of_opt_in(self) -> None:
        """Empty input is the trivial early-return; opt-in flag is moot."""
        result_off = compile_protos_to_result([])
        result_on = compile_protos_to_result([], include_source_info=True)
        assert result_off.source_info_descriptors is None
        assert result_on.source_info_descriptors is None
        assert result_off.root_files == ()
        assert result_on.root_files == ()

    def test_same_basename_collision_returns_none(self, tmp_path: Path) -> None:
        """Pre-flight collision path also passes ``source_info_descriptors=None``."""
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
        # The collision pre-flight should fire; source_info_descriptors stays None.
        assert result.source_info_descriptors is None
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
        # Both produce CompileResult with source_info_descriptors None.
        assert isinstance(result1, CompileResult)
        assert isinstance(result2, CompileResult)
        assert result1.source_info_descriptors is None
        assert result2.source_info_descriptors is None
        # And the pool is populated as before.
        assert result1.pool.FindMessageTypeByName("demo.User") is not None


class TestSourceInfoDescriptorsFrozenDataclassInvariant:
    """``source_info_descriptors`` is wrapped in MappingProxyType (post-init snapshot)."""

    def test_mapping_proxy_blocks_setitem(self, tmp_path: Path) -> None:
        """Caller-supplied mutable dict is wrapped immutably post-init."""
        proto = _write_proto(tmp_path, "demo.proto", _PROTO_WITH_COMMENTS)
        result = compile_protos_to_result([proto], include_source_info=True)
        assert result.source_info_descriptors is not None
        # MappingProxyType raises TypeError on mutation attempts.
        with pytest.raises(TypeError):
            result.source_info_descriptors["new.proto"] = result.source_info_descriptors[
                "demo.proto"
            ]  # type: ignore[index]

    def test_mapping_proxy_blocks_delitem(self, tmp_path: Path) -> None:
        """``del source_info_descriptors[key]`` raises TypeError."""
        proto = _write_proto(tmp_path, "demo.proto", _PROTO_WITH_COMMENTS)
        result = compile_protos_to_result([proto], include_source_info=True)
        assert result.source_info_descriptors is not None
        with pytest.raises(TypeError):
            del result.source_info_descriptors["demo.proto"]  # type: ignore[attr-defined]

    def test_mapping_proxy_has_no_update_method(self, tmp_path: Path) -> None:
        """MappingProxyType does not expose mutating helpers like update()."""
        proto = _write_proto(tmp_path, "demo.proto", _PROTO_WITH_COMMENTS)
        result = compile_protos_to_result([proto], include_source_info=True)
        assert result.source_info_descriptors is not None
        # ``Mapping`` doesn't define ``update`` / ``clear`` / ``pop``;
        # MappingProxyType inherits Mapping not MutableMapping. Reading
        # the attribute should raise AttributeError.
        with pytest.raises(AttributeError):
            result.source_info_descriptors.update({})  # type: ignore[attr-defined]
        with pytest.raises(AttributeError):
            result.source_info_descriptors.clear()  # type: ignore[attr-defined]


class TestFailurePathClearsSourceLocations:
    """``include_source_info=True`` + compile failure → ``source_info_descriptors is None``.

    Pins plan scenario line 322 — the ``if pool is None`` clearing block at
    ``compile.py`` must drop ``source_info_descriptors`` on irrecoverable failure
    even when the caller opted in. Without this guard, downstream R6 rules
    could read stale source data from a partially-populated backend.
    """

    def test_syntax_error_with_opt_in_returns_none(
        self, tmp_path: Path
    ) -> None:
        """A syntactically invalid .proto + ``True`` → ``source_info_descriptors is None``."""
        bad = tmp_path / "broken.proto"
        bad.write_text(
            'syntax = "proto3";\n'
            'package demo;\n'
            # Deliberately invalid: missing semicolons, dangling field type.
            'message User { string username 1 }\n'
        )
        result = compile_protos_to_result([bad], include_source_info=True)
        # Failure populates diagnostics; both backends may report this
        # differently (protoxy ProtoxyError, protoc CalledProcessError).
        assert len(result.diagnostics) >= 1
        # The clearing contract: irrecoverable failure forces None
        # regardless of the opt-in flag.
        assert result.source_info_descriptors is None
        assert result.root_files == ()


class TestParameterValueThreadsToBackend:
    """The ``include_source_info`` VALUE reaches the backend, not just the keyword.

    The integration tests above pin end-to-end outcomes via real backends.
    These tests use fake backends to assert specifically that the kwarg
    value (True vs False) is forwarded — guarding against a future
    refactor that accidentally hard-codes a literal.
    """

    @pytest.mark.parametrize("opt_in", [True, False])
    def test_protoc_backend_receives_flag_value(
        self,
        opt_in: bool,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Forces the protoc path and asserts the fake captures the kwarg."""
        from google.protobuf import descriptor_pool

        from protokit.schema import compile as compile_module

        captured: dict[str, object] = {}

        def fake_protoc(
            paths,  # type: ignore[no-untyped-def]
            ip,
            *,
            include_source_info: bool = False,
        ):
            captured["include_source_info"] = include_source_info
            return descriptor_pool.DescriptorPool(), (), None

        monkeypatch.setattr(compile_module, "_has_protoxy", lambda: False)
        monkeypatch.setattr(
            compile_module, "_compile_with_protoc", fake_protoc,
        )

        proto = _write_proto(tmp_path, "demo.proto", _PROTO_WITH_COMMENTS)
        compile_protos_to_result([proto], include_source_info=opt_in)

        assert captured["include_source_info"] is opt_in

    @pytest.mark.skipif(
        not _cli_utils._has_protoxy(),
        reason=(
            "monkeypatches _has_protoxy=True to force the protoxy arm of the "
            "dispatcher, but the dispatcher then does `import protoxy` inside "
            "its try block — on the has_protoxy=false CI cell that ImportError "
            "short-circuits to the backend-missing diagnostic before the fake "
            "_compile_with_protoxy is reached"
        ),
    )
    @pytest.mark.parametrize("opt_in", [True, False])
    def test_protoxy_backend_receives_flag_value(
        self,
        opt_in: bool,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Forces the protoxy path and asserts the fake captures the kwarg."""
        from google.protobuf import descriptor_pool

        from protokit.schema import compile as compile_module

        captured: dict[str, object] = {}

        def fake_protoxy(
            paths,  # type: ignore[no-untyped-def]
            ip,
            *,
            include_source_info: bool = False,
        ):
            captured["include_source_info"] = include_source_info
            return descriptor_pool.DescriptorPool(), (), None

        monkeypatch.setattr(compile_module, "_has_protoxy", lambda: True)
        monkeypatch.setattr(
            compile_module, "_compile_with_protoxy", fake_protoxy,
        )

        proto = _write_proto(tmp_path, "demo.proto", _PROTO_WITH_COMMENTS)
        compile_protos_to_result([proto], include_source_info=opt_in)

        assert captured["include_source_info"] is opt_in


class TestDefaultFalseDescriptorBytesUnchanged:
    """Default-False path keeps ``source_code_info`` out of the pool entirely.

    The strongest proxy for the plan's "byte-identical to pre-D6b output"
    verification (line 328) without checking in a serialized golden:
    ``pool.CopyToProto(fd)`` on the False path must produce a
    ``FileDescriptorProto`` whose ``source_code_info.location`` array is
    empty. A regression that defaulted ``include_source_info`` to True
    would leave non-empty locations on the round-tripped descriptor.
    """

    def test_default_false_pool_has_no_source_code_info(
        self, tmp_path: Path
    ) -> None:
        """Round-tripping a descriptor through the False-path pool drops SCI."""
        from google.protobuf import descriptor_pb2

        proto = _write_proto(tmp_path, "demo.proto", _PROTO_WITH_COMMENTS)
        result = compile_protos_to_result([proto])  # default False

        file_descriptor = result.pool.FindFileByName("demo.proto")
        round_tripped = descriptor_pb2.FileDescriptorProto()
        file_descriptor.CopyToProto(round_tripped)

        # ``source_code_info`` should be absent (empty Location list) —
        # both backends pass ``include_source_info=False`` to their
        # underlying compiler in this configuration, and ``pool.Add()``
        # would have stripped any incidental locations.
        assert len(round_tripped.source_code_info.location) == 0


class TestRootTransitiveShadow:
    """Pre-flight detects when a root proto's basename is shadowed on ``-I``.

    Without this guard, the backend's ``-I`` walk could pick a same-named
    file from one of the user-supplied include paths over the user's
    root input, and ``source_info_descriptors[fd.name]`` would silently
    carry the shadow's ``source_code_info`` — breaking R6 rules that
    read leading_comment from the wrong file.
    """

    def test_shadow_detected_emits_diagnostic(
        self, tmp_path: Path
    ) -> None:
        """Root + shadow on -I → ``root_transitive_shadow`` diagnostic."""
        # Root proto under /a; shadow with the same basename under /b
        # passed as an include path.
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        root = _write_proto(dir_a, "shared.proto", _PROTO_WITH_COMMENTS)
        # Different content under /b — must be a distinct physical file.
        (dir_b / "shared.proto").write_text(
            'syntax = "proto3"; package shadow; message Other {}'
        )

        result = compile_protos_to_result(
            [root], proto_paths=(str(dir_b),), include_source_info=True,
        )

        assert result.source_info_descriptors is None
        assert result.root_files == ()
        assert len(result.diagnostics) == 1
        diag = result.diagnostics[0]
        assert diag.category == "root_transitive_shadow"
        assert diag.exception_type == "RootTransitiveShadow"
        # The message names the basename (not the absolute path of the root).
        assert "shared.proto" in diag.message

    def test_no_shadow_when_only_root_parent_in_path(
        self, tmp_path: Path
    ) -> None:
        """Root's own parent on -I is not a shadow — same physical file."""
        dir_a = tmp_path / "a"
        dir_a.mkdir()
        root = _write_proto(dir_a, "demo.proto", _PROTO_WITH_COMMENTS)

        # Caller passes the same dir on -I that contains the root.
        # samefile() returns True so no shadow is reported.
        result = compile_protos_to_result(
            [root], proto_paths=(str(dir_a),),
        )

        assert result.diagnostics == ()

    def test_shadow_check_skipped_when_no_proto_paths(
        self, tmp_path: Path
    ) -> None:
        """Empty proto_paths means no shadow can exist — clean path."""
        root = _write_proto(tmp_path, "demo.proto", _PROTO_WITH_COMMENTS)

        result = compile_protos_to_result([root])

        assert result.diagnostics == ()


class TestPostInitExceptionContainment:
    """A buggy backend Mapping is contained as a category-#5 diagnostic.

    Pins finding #13 of the U1 ce:review: the final
    ``CompileResult(...)`` construction is wrapped in the dispatch's
    Exception catch so a backend that returns a non-standard Mapping
    (one whose ``dict()`` conversion raises inside ``__post_init__``)
    surfaces as a category-#5 diagnostic instead of escaping the A2-1
    "never raises on backend failure" contract.
    """

    @pytest.mark.skipif(
        not _cli_utils._has_protoxy(),
        reason=(
            "monkeypatches _has_protoxy=True to plant a fake protoxy backend "
            "that returns a buggy Mapping, but the dispatcher's `import "
            "protoxy` raises ImportError on the has_protoxy=false CI cell "
            "and short-circuits to the backend-missing diagnostic before the "
            "fake is reached — making the post_init containment unobservable"
        ),
    )
    def test_iteration_failure_in_post_init_becomes_diagnostic(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Backend returns a Mapping that raises on iteration → diagnostic."""
        from google.protobuf import descriptor_pool

        from protokit.schema import compile as compile_module

        class _BuggyMapping:
            """Mapping-shaped object whose ``__iter__`` raises.

            ``dict()`` conversion calls ``__iter__`` first; raising there
            triggers __post_init__ to propagate the exception out of the
            final CompileResult construction.
            """

            def __iter__(self):  # type: ignore[no-untyped-def]
                raise RuntimeError("synthetic iteration failure")

            def keys(self):  # type: ignore[no-untyped-def]
                return iter(self)

            def __getitem__(self, key):  # type: ignore[no-untyped-def]
                raise KeyError(key)

            def __len__(self) -> int:
                return 0

        def fake_protoxy(
            paths,  # type: ignore[no-untyped-def]
            ip,
            *,
            include_source_info: bool = False,
        ):
            return descriptor_pool.DescriptorPool(), (), _BuggyMapping(), ()

        monkeypatch.setattr(compile_module, "_has_protoxy", lambda: True)
        monkeypatch.setattr(
            compile_module, "_compile_with_protoxy", fake_protoxy,
        )

        proto = _write_proto(tmp_path, "demo.proto", _PROTO_WITH_COMMENTS)
        # Must NOT raise — the contract is that __post_init__ failures
        # land as category-#5 diagnostics, not propagate.
        result = compile_protos_to_result([proto], include_source_info=True)

        # source_info_descriptors cleared on the rebuild path.
        assert result.source_info_descriptors is None
        # A category-#5 ("unexpected") diagnostic carries the RuntimeError.
        unexpected = [d for d in result.diagnostics if d.category == "unexpected"]
        assert len(unexpected) == 1
        assert unexpected[0].exception_type == "RuntimeError"
