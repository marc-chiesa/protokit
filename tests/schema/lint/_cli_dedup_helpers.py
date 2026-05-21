"""Shared helpers for ``--rule-pack=...`` CLI dedup regression tests.

The D6b U7 (``package_same``), D6c U2 (``package``), and D6d U5
(``options.field_behavior``) BUILTIN_PACKS flips each shipped a
sibling test under ``tests/schema/lint/test_cli_rule_pack_dedup_post_<delivery>.py``
asserting that explicit ``--rule-pack=`` for a BUILTIN_PACKS-resident
module does not raise ``ValueError`` at ``cli.py``'s R25 multi-pack
provenance line. The shape of those tests converged on the same
descriptor-set compilation helper; this module exposes it as the
canonical SSOT so the third / fourth / Nth dedup-regression test
inherits the discipline without copy-paste.

The helper is intentionally minimal — wrap ``compile_protos_to_result``
+ ``FileDescriptorSet`` serialization. Callers supply their own
proto sources; this module does not own fixture-content discipline.
"""

from __future__ import annotations

from pathlib import Path

from google.protobuf import descriptor_pb2

from protokit.schema.compile import compile_protos_to_result


def compile_sources_to_descriptor_set(
    tmp_path: Path,
    sources: dict[str, str],
    *,
    out_filename: str = "dedup_regression.descriptor_set",
) -> Path:
    """Compile inline proto ``sources`` to a serialized ``.descriptor_set``.

    Args:
        tmp_path: pytest ``tmp_path`` fixture root for the per-test
            scratch directory.
        sources: ``filename -> proto source text`` mapping. Each
            filename is created under ``tmp_path`` (parent dirs are
            created as needed) and compiled together as one set.
        out_filename: Filename of the serialized descriptor set
            written under ``tmp_path``. Defaults to a generic name
            so the file's identity doesn't imply specific content
            (mis-naming caused readability noise in earlier
            iterations of this helper).

    Returns:
        Path to the serialized descriptor-set file.

    Raises:
        AssertionError: If the compile produced any error-level
            diagnostic. Fixtures should fail loudly when compilation
            breaks rather than silently producing an empty
            descriptor set.

    Notes:
        Intentionally uses ``pool_file_names`` (all files in the
        pool, including WKTs that were imported by user files) so
        the serialized set contains everything the lint CLI needs
        to resolve cross-file references. Callers that want to
        exclude transitive imports should write their own helper
        modeled on ``tests/schema/lint/cli/conftest.py``'s
        ``_serialize_descriptor_set``.
    """
    for fname, text in sources.items():
        path = tmp_path / fname
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    result = compile_protos_to_result(
        paths=[tmp_path / fname for fname in sources],
        proto_paths=(str(tmp_path),),
    )
    error_diags = [d for d in result.diagnostics if d.level == "error"]
    assert not error_diags, f"fixture compile failed: {error_diags}"
    fds = descriptor_pb2.FileDescriptorSet()
    for fname in result.pool_file_names:
        fd_proto = descriptor_pb2.FileDescriptorProto()
        result.pool.FindFileByName(fname).CopyToProto(fd_proto)
        fds.file.add().CopyFrom(fd_proto)
    out = tmp_path / out_filename
    out.write_bytes(fds.SerializeToString())
    return out
