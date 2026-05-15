"""Tests for D6b U3b descriptor-set-mode source-info capture.

U3b extends ``_load_descriptor_sets_to_result`` (at
``src/protokit/schema/lint/_cli_utils.py:259-422``) to capture
``FileDescriptorProto`` references into ``source_info_descriptors``
BEFORE ``pool.Add(fd)`` consumes the source-code-info. The Python-level
reference retains ``.source_code_info`` so downstream R6 comment-aware
rules can resolve descriptor paths to leading comments — symmetric with
proto-mode behavior after U3a's CLI flip.

The U1 capture-around-Add precedent (``_populate_pool_with_capture`` at
``src/protokit/_cli_utils.py:221-270``) establishes that the fd reference
captured BEFORE ``pool.Add`` retains ``.source_code_info``. U3b mirrors
this load-bearing PRE-ADD ordering per K-7/K-8 of the D6b U3 plan.

Tests verify:

- Happy path: descriptor set with source_code_info → ``source_info_descriptors``
  populated; ``.source_code_info.location[]`` non-empty.
- Without-source-info path: descriptor set built without source-code-info
  → ``source_info_descriptors`` populated (dict not None) but each fd's
  location array is empty; R6 rules over-report (documented per K-9).
- Dedup-skipped fds absent from accumulator (symmetric with pool.Add absence).
- pool.Add error_exit path: SystemExit discards partial state harmlessly.
- End-to-end: R6 rules fire on descriptor-set inputs with source info.
"""

from __future__ import annotations

from pathlib import Path

from google.protobuf import descriptor_pb2

from protokit.schema.compile import compile_protos_to_result
from protokit.schema.lint._cli_utils import _load_descriptor_sets_to_result
from protokit.schema.lint.engine import LintEngine
from protokit.schema.lint.model import LintProfile, LintSeverity
from protokit.schema.lint.rules.options import deprecated_replacement

# ---------------------------------------------------------------------------
# Helpers — build descriptor sets with/without source_code_info
# ---------------------------------------------------------------------------


def _build_descriptor_set_with_source_info(
    proto_paths: list[Path],
    proto_root: Path,
) -> bytes:
    """Build a serialized FileDescriptorSet preserving source_code_info.

    Uses ``include_source_info=True`` on the compile, then serializes the
    raw FileDescriptorProto objects from ``source_info_descriptors``
    (which carry ``source_code_info``) rather than ``fd.CopyToProto`` from
    the pool (which loses source_code_info).
    """
    result = compile_protos_to_result(
        paths=proto_paths,
        proto_paths=(str(proto_root),),
        include_source_info=True,
    )
    assert result.source_info_descriptors is not None
    fds = descriptor_pb2.FileDescriptorSet()
    for fd_proto in result.source_info_descriptors.values():
        fds.file.add().CopyFrom(fd_proto)
    return fds.SerializeToString()


def _build_descriptor_set_without_source_info(
    proto_paths: list[Path],
    proto_root: Path,
) -> bytes:
    """Build a serialized FileDescriptorSet WITHOUT source_code_info.

    Emulates ``protoc`` invoked without ``--include_source_info``: compile
    and serialize via ``fd.CopyToProto`` from the pool (the standard path
    that strips source_code_info).
    """
    result = compile_protos_to_result(
        paths=proto_paths,
        proto_paths=(str(proto_root),),
    )
    fds = descriptor_pb2.FileDescriptorSet()
    for root_name in result.root_files:
        fd = result.pool.FindFileByName(root_name)
        fp = fds.file.add()
        fd.CopyToProto(fp)
    return fds.SerializeToString()


_PROTO_WITH_DEPRECATED = """\
syntax = "proto3";
package demo;

message User {
    // Use new_field instead.
    string old_field = 1 [deprecated = true];
    string current_field = 2;
}
"""


def _write_pbset(
    tmp_path: Path,
    proto_text: str,
    *,
    with_source_info: bool,
) -> Path:
    """Write the proto to disk, build a .pbset, return the .pbset path."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    proto_path = tmp_path / "demo.proto"
    proto_path.write_text(proto_text)
    if with_source_info:
        data = _build_descriptor_set_with_source_info(
            [proto_path], tmp_path,
        )
    else:
        data = _build_descriptor_set_without_source_info(
            [proto_path], tmp_path,
        )
    pbset = tmp_path / "demo.pbset"
    pbset.write_bytes(data)
    return pbset


# ---------------------------------------------------------------------------
# Loader-level tests — _load_descriptor_sets_to_result behavior
# ---------------------------------------------------------------------------


class TestLoaderSourceInfoCapture:
    """``_load_descriptor_sets_to_result`` captures source_info_descriptors."""

    def test_with_source_info_returns_populated_mapping(
        self, tmp_path: Path,
    ) -> None:
        pbset = _write_pbset(
            tmp_path, _PROTO_WITH_DEPRECATED, with_source_info=True,
        )
        result = _load_descriptor_sets_to_result((pbset,))

        # Mapping is populated and non-empty.
        assert result.source_info_descriptors is not None
        assert "demo.proto" in result.source_info_descriptors
        fd_proto = result.source_info_descriptors["demo.proto"]
        # source_code_info is present and carries Locations.
        assert len(fd_proto.source_code_info.location) > 0

    def test_without_source_info_returns_populated_but_empty_locations(
        self, tmp_path: Path,
    ) -> None:
        pbset = _write_pbset(
            tmp_path, _PROTO_WITH_DEPRECATED, with_source_info=False,
        )
        result = _load_descriptor_sets_to_result((pbset,))

        # Mapping itself is populated (the fd reference is captured),
        # but the captured fd has no source_code_info.location entries.
        assert result.source_info_descriptors is not None
        assert "demo.proto" in result.source_info_descriptors
        fd_proto = result.source_info_descriptors["demo.proto"]
        assert len(fd_proto.source_code_info.location) == 0

    def test_keys_match_root_files_set(
        self, tmp_path: Path,
    ) -> None:
        """source_info_descriptors keys exactly match the pool's file set."""
        pbset = _write_pbset(
            tmp_path, _PROTO_WITH_DEPRECATED, with_source_info=True,
        )
        result = _load_descriptor_sets_to_result((pbset,))

        assert result.source_info_descriptors is not None
        keys = set(result.source_info_descriptors.keys())
        roots = set(result.root_files)
        # Single-file fixture: every key is also a root.
        assert keys == roots


class TestLoaderDedupSkipsAccumulator:
    """Dedup-skipped fds are absent from both pool AND source_info_descriptors."""

    def test_dedup_skipped_fd_not_in_accumulator(
        self, tmp_path: Path,
    ) -> None:
        # Build two pbsets containing the SAME fd.name. The loader
        # processes them in argv order; the second occurrence is
        # dedup-skipped per the same_basename_collision path.
        pbset_a = _write_pbset(
            tmp_path / "a", _PROTO_WITH_DEPRECATED, with_source_info=True,
        )
        # Identical second pbset, different directory so write_text
        # doesn't collide on the .proto.
        pbset_b = _write_pbset(
            tmp_path / "b", _PROTO_WITH_DEPRECATED, with_source_info=True,
        )

        result = _load_descriptor_sets_to_result((pbset_a, pbset_b))

        # The dedup-skipped fd contributed a diagnostic.
        dedup_diags = [
            d for d in result.diagnostics
            if d.category == "same_basename_collision"
        ]
        assert len(dedup_diags) == 1

        # The mapping still has the one fd entry (from the first pbset),
        # NOT two entries — the second was skipped.
        assert result.source_info_descriptors is not None
        assert len(result.source_info_descriptors) == 1


class TestLoaderPoolAddFailure:
    """``pool.Add`` failure raises SystemExit; partial accumulator discarded."""

    def test_missing_imports_raises_system_exit(
        self, tmp_path: Path,
    ) -> None:
        """A descriptor set whose fds reference unresolved imports
        triggers ``pool.Add`` to raise TypeError, which the loader
        routes to ``error_exit_with_code('missing-imports', ...)``.
        The partial ``source_info_descriptors`` accumulator carrying
        the failing fd's entry is discarded by SystemExit propagation
        — no caller observes the partial state because
        ``CompileResult`` is never constructed on this path.
        """
        # Build a descriptor set whose fd declares a dependency on a
        # file that is NOT included in the set. pool.Add(fd) raises
        # TypeError on the missing-imports marker.
        proto_path = tmp_path / "demo.proto"
        proto_path.write_text(
            'syntax = "proto3";\n'
            'package demo;\n'
            'import "missing.proto";\n'
            'message X { string name = 1; }\n',
        )
        # We can't compile this directly (the compile step would fail
        # at the proto-resolution layer). Instead, hand-construct a
        # minimal FileDescriptorProto that declares a missing import.
        fds = descriptor_pb2.FileDescriptorSet()
        fp = fds.file.add()
        fp.name = "demo.proto"
        fp.package = "demo"
        fp.syntax = "proto3"
        fp.dependency.append("missing.proto")  # Never resolved.
        msg = fp.message_type.add()
        msg.name = "X"
        field = msg.field.add()
        field.name = "name"
        field.number = 1
        field.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING
        pbset = tmp_path / "bad.pbset"
        pbset.write_bytes(fds.SerializeToString())

        # The loader must raise SystemExit (via error_exit_with_code)
        # — the partial accumulator state is never returned.
        import pytest
        with pytest.raises(SystemExit):
            _load_descriptor_sets_to_result((pbset,))


# ---------------------------------------------------------------------------
# End-to-end: R6 rules fire correctly through the descriptor-set mode
# ---------------------------------------------------------------------------


_PROTO_HAPPY_DEPRECATED = """\
syntax = "proto3";
package demo;

message User {
    // Use new_field instead.
    string old_field = 1 [deprecated = true];
}
"""

_PROTO_SAD_DEPRECATED = """\
syntax = "proto3";
package demo;

message User {
    // No replacement available.
    string old_field = 1 [deprecated = true];
}
"""


def _run_r6_through_pbset(pbset: Path) -> int:
    """Load pbset, run R6 field rule, return finding count."""
    result = _load_descriptor_sets_to_result((pbset,))
    engine = LintEngine()
    engine.load_rule_pack(deprecated_replacement)
    profile = LintProfile(
        name="_test_isolation",
        rule_ids=frozenset(
            {"options/deprecated-field-must-have-replacement-comment"},
        ),
        min_severity=LintSeverity.INFO,
    )
    report = engine.run(result, profile=profile)
    return len(report.findings)


class TestDescriptorSetModeR6EndToEnd:
    """R6 rules behave symmetrically across proto/descriptor-set modes."""

    def test_happy_path_with_source_info(self, tmp_path: Path) -> None:
        pbset = _write_pbset(
            tmp_path, _PROTO_HAPPY_DEPRECATED, with_source_info=True,
        )
        # Replacement comment matches; zero findings.
        assert _run_r6_through_pbset(pbset) == 0

    def test_sad_path_with_source_info(self, tmp_path: Path) -> None:
        pbset = _write_pbset(
            tmp_path, _PROTO_SAD_DEPRECATED, with_source_info=True,
        )
        # Comment does NOT match any pattern; one finding.
        assert _run_r6_through_pbset(pbset) == 1

    def test_without_source_info_over_reports_documented_caveat(
        self, tmp_path: Path,
    ) -> None:
        """Descriptor set without source_code_info → R6 over-reports.

        Per K-9 of the D6b U3 plan: when a descriptor set is built
        without ``protoc --include_source_info``, leading_comment()
        returns None and R6 emits a finding for every deprecated
        element regardless of its actual comment content. This test
        pins that documented behavior.
        """
        # Use the HAPPY proto (carries a matching replacement comment),
        # but strip source_code_info from the descriptor set. The R6
        # rule cannot see the comment and fires anyway.
        pbset = _write_pbset(
            tmp_path, _PROTO_HAPPY_DEPRECATED, with_source_info=False,
        )
        # Despite the proto carrying "Use new_field instead.", the
        # descriptor set has no source info → over-report.
        assert _run_r6_through_pbset(pbset) == 1
