"""Tests for the ``protokit.storage`` public surface (U6).

Pins the PR1 contract: the public names import from the package top level, a
third-party ``Source`` built from only those names works end-to-end, ``__all__``
is sorted and leaks no private name, and the storage symbols are NOT re-exported
onto the top-level ``protokit`` namespace (the no-top-level-re-export rule).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import protokit.storage as storage
from protokit.storage import (
    FileDescriptorSetSchema,
    ScanRecord,
    Source,
    StreamRegistry,
    scan,
)
from tests.storage.proto_fixtures import fds, file_proto

_REPO_ROOT = Path(__file__).resolve().parents[2]


class _ThirdPartySource:
    """A ``Source`` built with only the public surface — no internal imports."""

    def __init__(self, records: list[tuple[str, bytes]]) -> None:
        self._records = records

    def __iter__(self) -> Iterator[tuple[str, bytes]]:
        yield from self._records


class TestPublicImports:
    def test_core_names_resolve_from_top_level(self) -> None:
        # The import block at module top already exercises resolution; assert a
        # representative slice is present on the package object too.
        for name in ("scan", "Source", "StreamRegistry", "FrameError",
                     "SchemaSource", "ScanRecord", "ScanResult"):
            assert hasattr(storage, name), name

    def test_all_is_sorted_and_fully_importable(self) -> None:
        assert storage.__all__ == sorted(storage.__all__)
        for name in storage.__all__:
            assert hasattr(storage, name), name
            assert not name.startswith("_"), name


class TestThirdPartySourceStability:
    def test_third_party_source_works_end_to_end(self) -> None:
        fdp = file_proto("a.proto", "a", message="A")
        schema = FileDescriptorSetSchema(fds(fdp), "a.A")
        registry = StreamRegistry()
        registry.register_stream("s", schema)
        # Build payloads via the public SchemaSource, not registry internals.
        message_cls = schema.resolve().message_class
        records = [("s", message_cls(x=i).SerializeToString()) for i in (1, 2, 3)]

        source = _ThirdPartySource(records)
        assert isinstance(source, Source)  # satisfies the public protocol
        scanned = list(scan(source, registry))
        assert [r.message.x for r in scanned] == [1, 2, 3]
        assert all(isinstance(r, ScanRecord) for r in scanned)


class TestNoTopLevelReExport:
    def test_storage_symbols_not_leaked_to_top_level_protokit(self) -> None:
        import protokit

        for name in ("scan", "Source", "StreamRegistry", "ScanRecord", "FrameError"):
            assert not hasattr(protokit, name), f"protokit.{name} leaked to top level"


class TestPr15SurfaceAdditions:
    def test_new_public_symbols_resolve(self) -> None:
        for name in ("ProtoFileSchema", "SchemaCompileError", "WhereError"):
            assert hasattr(storage, name), name
            assert name in storage.__all__, name

    def test_compile_where_is_internal_not_exported(self) -> None:
        # The --where compiler is CLI sugar; only its error type is public.
        assert "compile_where" not in storage.__all__
        assert not hasattr(storage, "compile_where")

    def test_onerror_includes_route(self) -> None:
        import typing

        from protokit.storage import OnError

        assert "route" in typing.get_args(OnError)


class TestPr2SurfaceAdditions:
    def test_new_public_symbols_resolve(self) -> None:
        # U2 adds the projection helper + its resolver error type.
        for name in ("project", "FieldSelectionError"):
            assert hasattr(storage, name), name
            assert name in storage.__all__, name

    def test_all_stays_sorted(self) -> None:
        assert storage.__all__ == sorted(storage.__all__)

    def test_compile_fields_and_selection_stay_internal(self) -> None:
        # Mirror compile_where: only the error type + projection helper are
        # public; the compiler and its compiled-selection dataclass are not.
        for name in ("compile_fields", "CompiledSelection"):
            assert name not in storage.__all__
            assert not hasattr(storage, name)

    def test_field_selection_error_is_storage_error(self) -> None:
        from protokit.storage import FieldSelectionError, StorageError

        assert issubclass(FieldSelectionError, StorageError)


class TestReadmeDocsPresence:
    def test_readme_mentions_storage_surface(self) -> None:
        readme = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
        assert "protokit.storage" in readme

    def test_readme_documents_storage_cli(self) -> None:
        readme = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
        assert "protokit storage scan" in readme
