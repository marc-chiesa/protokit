"""``CompileResult.pool_file_names`` field + ``__post_init__`` invariant — D6b U4a.

R7's engine pre-walk accumulator (in :mod:`protokit.schema.lint.engine`)
iterates the FULL pool — including transitively-imported protos — to
detect per-package option-value disagreements that protokit emits only
on root_files. The full pool's file list lives on a new
:attr:`CompileResult.pool_file_names` field added in U4a; this module
pins that field's contract.

Three contract pillars verified here:

1. **Compile-mode population**: both compile backends (``_compile_with_protoxy``
   and ``_compile_with_protoc``) grow to a 4-tuple return shape
   ``(pool, root_names, source_info_descriptors, pool_file_names)``;
   ``compile_protos_to_result`` tuple-unpacks the 4th element into
   ``CompileResult.pool_file_names``. Default ``()`` for callers that
   don't populate it (test helpers, direct construction without backend).
2. **Descriptor-set-mode population**: ``_load_descriptor_sets_to_result``
   populates ``pool_file_names`` symmetric with ``root_files`` — every
   fd added to the pool also appears in ``pool_file_names``.
3. **__post_init__ invariant** via diagnostic emission (NOT ``assert``
   which strips under ``-O`` nor ``raise ValueError`` which violates the
   no-raise contract): when ``pool_file_names`` is non-empty but does
   not include every entry in ``root_files``, ``__post_init__`` appends
   a ``LintCompileDiagnostic(level="error", ...)`` to ``diagnostics``
   and resets ``pool_file_names`` to ``()`` so the engine pre-walk
   early-returns instead of mis-firing on partial state.

Mirrors the cross-backend pattern in
:class:`tests.schema.lint.test_compile_include_source_info.TestSourceInfoDescriptorsCrossBackendSemanticEquivalence`.
``pool_file_names`` is a tuple of file-name strings (no
version-sensitive encoding), so byte-equivalence still holds across
protoc versions; ``source_code_info`` requires semantic-rather-than-
byte comparison because protoc 25+ encodes location spans slightly
differently than older versions.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from google.protobuf import descriptor_pb2, descriptor_pool

from protokit import _cli_utils
from protokit.schema.compile import CompileResult, compile_protos_to_result

# ---- Fixture helpers --------------------------------------------------------


_PROTO_USER = """\
syntax = "proto3";

package u4a.compile_pool_file_names;

import "google/protobuf/any.proto";

message User {
  google.protobuf.Any payload = 1;
}
"""

_PROTO_PEER = """\
syntax = "proto3";

package u4a.compile_pool_file_names;

message Peer {}
"""


def _write_proto(dest: Path, name: str, contents: str) -> Path:
    """Materialise a ``.proto`` file under ``dest`` and return its path."""
    path = dest / name
    path.write_text(contents)
    return path


# ---- Field shape + default --------------------------------------------------


class TestPoolFileNamesFieldDefault:
    """``pool_file_names`` defaults to ``()`` for test-helper construction."""

    def test_default_empty_tuple(self) -> None:
        result = CompileResult(pool=descriptor_pool.DescriptorPool())
        assert result.pool_file_names == ()

    def test_explicit_tuple_snapshot(self) -> None:
        """``__post_init__`` snapshots caller-supplied lists into tuples."""
        names_list = ["a.proto", "b.proto"]
        result = CompileResult(
            pool=descriptor_pool.DescriptorPool(),
            root_files=("a.proto", "b.proto"),
            pool_file_names=names_list,  # type: ignore[arg-type]
        )
        assert isinstance(result.pool_file_names, tuple)
        names_list.append("c.proto")  # mutate after construction
        assert result.pool_file_names == ("a.proto", "b.proto")

    def test_field_position_kwarg_only_callers_unaffected(self) -> None:
        """All in-repo callers use kwarg construction; positional safety check."""
        result = CompileResult(
            pool=descriptor_pool.DescriptorPool(),
            root_files=(),
            diagnostics=(),
            source_info_descriptors=None,
        )
        assert result.pool_file_names == ()


# ---- Compile-mode population ------------------------------------------------


class TestPoolFileNamesCompileMode:
    """Both backends produce ``pool_file_names`` including transitive imports."""

    def test_protoxy_populates_pool_file_names(self, tmp_path: Path) -> None:
        """``_compile_with_protoxy`` returns the 4-tuple shape with pool_file_names."""
        if not _cli_utils._has_protoxy():
            pytest.skip("optional [compiler] extra not installed")
        user = _write_proto(tmp_path, "user.proto", _PROTO_USER)

        pool, root_names, _, pool_file_names = _cli_utils._compile_with_protoxy(
            [user], (), include_source_info=False,
        )

        assert isinstance(pool_file_names, tuple)
        assert "user.proto" in pool_file_names
        # google/protobuf/any.proto is transitively imported and appears
        # in pool_file_names (via include_imports=True) but NOT root_names.
        assert "google/protobuf/any.proto" in pool_file_names
        assert "google/protobuf/any.proto" not in root_names

    def test_protoc_populates_pool_file_names(self, tmp_path: Path) -> None:
        """``_compile_with_protoc`` returns the 4-tuple shape with pool_file_names."""
        user = _write_proto(tmp_path, "user.proto", _PROTO_USER)
        try:
            pool, root_names, _, pool_file_names = _cli_utils._compile_with_protoc(
                [user], (), include_source_info=False,
            )
        except FileNotFoundError:
            pytest.skip("protoc not on PATH")

        assert isinstance(pool_file_names, tuple)
        assert "user.proto" in pool_file_names
        assert "google/protobuf/any.proto" in pool_file_names
        assert "google/protobuf/any.proto" not in root_names

    def test_compile_protos_to_result_threads_pool_file_names(
        self, tmp_path: Path,
    ) -> None:
        """``compile_protos_to_result`` tuple-unpacks 4-tuple into CompileResult."""
        user = _write_proto(tmp_path, "user.proto", _PROTO_USER)
        result = compile_protos_to_result([user])

        assert result.pool_file_names != ()
        assert "user.proto" in result.pool_file_names
        # Pool-file-names is a superset of root-files (transitive imports
        # included via include_imports=True).
        assert set(result.pool_file_names) >= set(result.root_files)
        assert "google/protobuf/any.proto" in result.pool_file_names


# ---- Descriptor-set-mode population -----------------------------------------


class TestPoolFileNamesDescriptorSetMode:
    """``_load_descriptor_sets_to_result`` populates ``pool_file_names``."""

    def test_descriptor_set_loader_populates_pool_file_names(
        self, tmp_path: Path,
    ) -> None:
        """Symmetric with ``root_files`` — every loaded fd appears in both."""
        from protokit.schema.lint import _cli_utils as lint_cli_utils

        # Build a synthetic FileDescriptorSet with two files in the same package.
        fds = descriptor_pb2.FileDescriptorSet()
        fd_a = fds.file.add()
        fd_a.name = "u4a/a.proto"
        fd_a.package = "u4a.descriptor_set"
        fd_a.syntax = "proto3"
        fd_b = fds.file.add()
        fd_b.name = "u4a/b.proto"
        fd_b.package = "u4a.descriptor_set"
        fd_b.syntax = "proto3"
        set_path = tmp_path / "u4a.descriptor_set"
        set_path.write_bytes(fds.SerializeToString())

        result = lint_cli_utils._load_descriptor_sets_to_result((set_path,))

        assert isinstance(result.pool_file_names, tuple)
        assert set(result.pool_file_names) == {"u4a/a.proto", "u4a/b.proto"}
        assert set(result.root_files) == set(result.pool_file_names)

    def test_descriptor_set_loader_duplicate_skip_preserves_invariant(
        self, tmp_path: Path,
    ) -> None:
        """Dedup-skipped fds are absent from both ``pool_file_names`` AND ``root_files``."""
        from protokit.schema.lint import _cli_utils as lint_cli_utils

        fds = descriptor_pb2.FileDescriptorSet()
        fd1 = fds.file.add()
        fd1.name = "shared.proto"
        fd1.package = "u4a.dedup"
        fd1.syntax = "proto3"
        # Same fd.name in a second set → dedup-skipped on the second occurrence.
        fd2 = fds.file.add()
        fd2.name = "shared.proto"
        fd2.package = "u4a.dedup"
        fd2.syntax = "proto3"
        set_path = tmp_path / "u4a-dedup.descriptor_set"
        set_path.write_bytes(fds.SerializeToString())

        result = lint_cli_utils._load_descriptor_sets_to_result((set_path,))

        # pool_file_names contains each fd.name at most once; dedup-skipped
        # entries do NOT inflate the tuple.
        assert result.pool_file_names.count("shared.proto") == 1
        assert set(result.pool_file_names) == set(result.root_files)


# ---- __post_init__ invariant (diagnostic emission, NOT assert/raise) --------


class TestPoolFileNamesInvariant:
    """Invariant: ``pool_file_names == () OR set(pool_file_names) >= set(root_files)``.

    Violation surfaces as a ``LintCompileDiagnostic(level="error")``
    appended to ``diagnostics`` AND ``pool_file_names`` reset to ``()``.
    No exception raised — preserves the documented no-raise contract.
    """

    def test_consistent_construction_passes_invariant(self) -> None:
        """``root_files ⊆ pool_file_names`` → no diagnostic emitted."""
        result = CompileResult(
            pool=descriptor_pool.DescriptorPool(),
            root_files=("a.proto",),
            pool_file_names=("a.proto", "google/protobuf/any.proto"),
        )
        assert result.pool_file_names == (
            "a.proto", "google/protobuf/any.proto",
        )
        invariant_diags = [
            d for d in result.diagnostics
            if d.category == "pool_file_names_invariant"
        ]
        assert invariant_diags == []

    def test_empty_pool_file_names_with_nonempty_root_files_passes(self) -> None:
        """``pool_file_names == ()`` is always valid (test-helper path)."""
        result = CompileResult(
            pool=descriptor_pool.DescriptorPool(),
            root_files=("a.proto",),
            pool_file_names=(),
        )
        assert result.pool_file_names == ()
        invariant_diags = [
            d for d in result.diagnostics
            if d.category == "pool_file_names_invariant"
        ]
        assert invariant_diags == []

    def test_violated_invariant_emits_diagnostic_and_resets(self) -> None:
        """Non-empty ``pool_file_names`` missing a root_file → diagnostic + reset."""
        result = CompileResult(
            pool=descriptor_pool.DescriptorPool(),
            root_files=("a.proto", "b.proto"),
            pool_file_names=("a.proto",),  # missing b.proto — invariant violated
        )
        # pool_file_names forced to () so engine pre-walk early-returns.
        assert result.pool_file_names == ()
        # Diagnostic appended.
        invariant_diags = [
            d for d in result.diagnostics
            if d.category == "pool_file_names_invariant"
        ]
        assert len(invariant_diags) == 1
        assert invariant_diags[0].level == "error"

    def test_invariant_violation_does_not_raise(self) -> None:
        """Invariant violation routes via diagnostic, not exception."""
        # Should not raise AssertionError, ValueError, or anything else.
        result = CompileResult(
            pool=descriptor_pool.DescriptorPool(),
            root_files=("missing.proto",),
            pool_file_names=("only-this.proto",),
        )
        assert isinstance(result, CompileResult)


# ---- Cross-backend byte-equivalence (mirrors U1 pattern) --------------------


class TestPoolFileNamesCrossBackendByteEquivalence:
    """``pool_file_names`` matches tuple-for-tuple across protoxy + protoc backends.

    Skipped when protoxy or protoc isn't available — the cross-backend
    test needs both. Mirrors ``TestSourceInfoDescriptorsCrossBackendSemanticEquivalence``
    in ``tests/schema/lint/test_compile_include_source_info.py``.
    """

    def test_protoxy_and_protoc_produce_identical_pool_file_names(
        self, tmp_path: Path,
    ) -> None:
        if not _cli_utils._has_protoxy():
            pytest.skip("optional [compiler] extra not installed")
        user = _write_proto(tmp_path, "user.proto", _PROTO_USER)
        _, _, _, protoxy_names = _cli_utils._compile_with_protoxy(
            [user], (), include_source_info=False,
        )
        try:
            _, _, _, protoc_names = _cli_utils._compile_with_protoc(
                [user], (), include_source_info=False,
            )
        except FileNotFoundError:
            pytest.skip("protoc not on PATH")

        assert protoxy_names == protoc_names

    def test_protoxy_and_protoc_identical_under_include_source_info(
        self, tmp_path: Path,
    ) -> None:
        """Cross-backend equivalence still holds with include_source_info=True."""
        if not _cli_utils._has_protoxy():
            pytest.skip("optional [compiler] extra not installed")
        user = _write_proto(tmp_path, "user.proto", _PROTO_USER)
        _, _, _, protoxy_names = _cli_utils._compile_with_protoxy(
            [user], (), include_source_info=True,
        )
        try:
            _, _, _, protoc_names = _cli_utils._compile_with_protoc(
                [user], (), include_source_info=True,
            )
        except FileNotFoundError:
            pytest.skip("protoc not on PATH")

        assert protoxy_names == protoc_names
