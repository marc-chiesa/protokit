"""Session-scoped fixtures for U2 CLI tests.

Compiles each ``.proto`` source file in ``cli_fixtures/`` to a
tmp-path ``.descriptor_set`` via D1's ``compile_protos_to_result``.
At-test-time compilation (rather than checked-in ``.descriptor_set``
binaries) avoids cross-version protobuf-library drift and keeps the
fixture authoring loop in human-readable ``.proto`` source.

The compile path works on both ``has_protoxy=true`` and ``=false``
CI cells via D1's protoxy → protoc fallback.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from google.protobuf import descriptor_pb2, descriptor_pool

from protokit.schema.compile import compile_protos_to_result

# Module containing the .proto source fixtures.
_FIXTURES_DIR = Path(__file__).parent / "cli_fixtures"


def _serialize_descriptor_set(
    pool: descriptor_pool.DescriptorPool,
    root_files: tuple[str, ...],
    *,
    include_imports: bool,
) -> bytes:
    """Bundle root files (and optionally their transitive deps) into a FileDescriptorSet.

    Args:
        pool: The compiled DescriptorPool.
        root_files: ``fd.name`` strings for each root file the user
            passed to the compile step.
        include_imports: When True, recurse into each root file's
            ``dependencies`` and include them in the bundle (mirrors
            ``protoc --include_imports``). When False, only the
            root files are serialized — used by the missing-imports
            fixture to reproduce the protoc footgun.

    Returns:
        Serialized FileDescriptorSet bytes ready to write to a
        ``.descriptor_set`` file.
    """
    seen: set[str] = set()
    files: list[descriptor_pb2.FileDescriptorProto] = []
    pending: list[str] = list(root_files)
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        fd = pool.FindFileByName(name)
        fp = descriptor_pb2.FileDescriptorProto()
        fd.CopyToProto(fp)
        files.append(fp)
        if include_imports:
            for dep in fd.dependencies:
                pending.append(dep.name)
    fds = descriptor_pb2.FileDescriptorSet()
    for fp in files:
        fds.file.add().CopyFrom(fp)
    return fds.SerializeToString()


def _compile_to_descriptor_set(
    proto_relpath: str,
    out_path: Path,
    *,
    include_imports: bool = True,
) -> None:
    """Compile ``cli_fixtures/<proto_relpath>`` and write a .descriptor_set.

    Args:
        proto_relpath: File name within ``cli_fixtures/`` (e.g.,
            ``"clean.proto"``).
        out_path: Where to write the serialized FileDescriptorSet.
        include_imports: Pass-through to
            :func:`_serialize_descriptor_set`. Default True; set
            False for the missing-imports fixture.

    Raises:
        AssertionError: If the compile produced any error-level
            diagnostic. Tests should fail loudly when fixture
            preparation breaks rather than silently producing an
            empty descriptor set.
    """
    src = _FIXTURES_DIR / proto_relpath
    result = compile_protos_to_result(
        paths=[src],
        proto_paths=[str(_FIXTURES_DIR)],
    )
    error_diags = [d for d in result.diagnostics if d.level == "error"]
    assert not error_diags, (
        f"fixture compile failed for {proto_relpath}: {error_diags}"
    )
    out_path.write_bytes(
        _serialize_descriptor_set(
            result.pool, result.root_files, include_imports=include_imports,
        )
    )


@pytest.fixture(scope="session")
def cli_fixtures_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Compile every ``.proto`` fixture once per session into a tmp dir.

    Returns the tmp directory path. Individual fixtures expose
    specific ``.descriptor_set`` paths through dedicated fixtures
    below.
    """
    out_dir = tmp_path_factory.mktemp("cli_fixtures")
    _compile_to_descriptor_set("clean.proto", out_dir / "clean.descriptor_set")
    _compile_to_descriptor_set(
        "bad_naming.proto", out_dir / "bad_naming.descriptor_set",
    )
    _compile_to_descriptor_set(
        "pool_conflict_a.proto", out_dir / "pool_conflict_a.descriptor_set",
    )
    _compile_to_descriptor_set(
        "pool_conflict_b.proto", out_dir / "pool_conflict_b.descriptor_set",
    )
    # missing_imports: compile WITHOUT bundling the WKT dep so the
    # resulting descriptor_set reproduces the protoc-without-include_imports
    # footgun. The compile itself succeeds (protoxy/protoc resolves
    # google/protobuf/timestamp.proto from its own bundled WKT dir);
    # the serialization step is what omits the dep.
    _compile_to_descriptor_set(
        "missing_imports.proto",
        out_dir / "missing_imports.descriptor_set",
        include_imports=False,
    )
    return out_dir


@pytest.fixture(scope="session")
def clean_descriptor_set(cli_fixtures_dir: Path) -> Path:
    """Path to a clean ``.descriptor_set`` (zero canary findings)."""
    return cli_fixtures_dir / "clean.descriptor_set"


@pytest.fixture(scope="session")
def bad_naming_descriptor_set(cli_fixtures_dir: Path) -> Path:
    """Path to a ``.descriptor_set`` that triggers ``naming/snake-case-fields``."""
    return cli_fixtures_dir / "bad_naming.descriptor_set"


@pytest.fixture(scope="session")
def pool_conflict_a_descriptor_set(cli_fixtures_dir: Path) -> Path:
    """Path to fixture A of the cross-set symbol-collision pair."""
    return cli_fixtures_dir / "pool_conflict_a.descriptor_set"


@pytest.fixture(scope="session")
def pool_conflict_b_descriptor_set(cli_fixtures_dir: Path) -> Path:
    """Path to fixture B of the cross-set symbol-collision pair."""
    return cli_fixtures_dir / "pool_conflict_b.descriptor_set"


@pytest.fixture(scope="session")
def missing_imports_descriptor_set(cli_fixtures_dir: Path) -> Path:
    """Path to a ``.descriptor_set`` referencing WKTs without bundling them."""
    return cli_fixtures_dir / "missing_imports.descriptor_set"


@pytest.fixture(scope="session")
def fixtures_proto_dir() -> Path:
    """Path to the ``cli_fixtures/`` directory holding ``.proto`` sources.

    Used by ``--proto`` mode tests that compile source files at
    test time via the lint CLI itself.
    """
    return _FIXTURES_DIR
