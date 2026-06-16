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
        for name in (
            "scan",
            "Source",
            "StreamRegistry",
            "FrameError",
            "SchemaSource",
            "ScanRecord",
            "ScanResult",
        ):
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
        # U2 adds the projection helper + its resolver error type; the PR2
        # review widened the contract to also export the compiler + its
        # compiled-selection dataclass (so a consumer can build a selection
        # without reaching into the private _fields module).
        for name in (
            "project",
            "FieldSelectionError",
            "compile_fields",
            "CompiledSelection",
        ):
            assert hasattr(storage, name), name
            assert name in storage.__all__, name

    def test_all_stays_sorted(self) -> None:
        assert storage.__all__ == sorted(storage.__all__)

    def test_field_selection_error_is_storage_error(self) -> None:
        from protokit.storage import FieldSelectionError, StorageError

        assert issubclass(FieldSelectionError, StorageError)

    def test_full_projection_path_via_public_surface_only(self) -> None:
        # The public contract is compile_fields(spec, descriptor) -> selection;
        # project(message, selection) -> dict. Exercise the FULL path using ONLY
        # the package-top imports (no private _fields module).
        from protokit.storage import compile_fields, project

        fdp = file_proto("a.proto", "a", message="A")
        schema = FileDescriptorSetSchema(fds(fdp), "a.A")
        message_cls = schema.resolve().message_class
        selection = compile_fields("x", message_cls.DESCRIPTOR)
        view = project(message_cls(x=7), selection)
        assert view == {"x": 7}


class TestPr3SurfaceAdditions:
    def test_new_public_symbols_resolve(self) -> None:
        # PR3 adds the columnar entry points + their typed exception family.
        for name in (
            "to_arrow_batches",
            "to_parquet",
            "ParquetExtraNotInstalledError",
            "SchemaMismatchError",
            "UnknownStreamError",
            "HandlerBuildError",
            "IncompleteScanError",
        ):
            assert hasattr(storage, name), name
            assert name in storage.__all__, name

    def test_all_stays_sorted(self) -> None:
        assert storage.__all__ == sorted(storage.__all__)

    def test_new_exceptions_are_storage_errors(self) -> None:
        from protokit.storage import (
            HandlerBuildError,
            IncompleteScanError,
            ParquetExtraNotInstalledError,
            SchemaMismatchError,
            StorageError,
            UnknownStreamError,
        )

        for exc in (
            ParquetExtraNotInstalledError,
            SchemaMismatchError,
            UnknownStreamError,
            HandlerBuildError,
            IncompleteScanError,
        ):
            assert issubclass(exc, StorageError), exc

    def test_columnar_internals_not_exported(self) -> None:
        # The conversion backend + helpers + tuning constants are internal; only
        # the two entry points and the typed exceptions are public surface.
        for name in (
            "_has_parquet",
            "_transitive_file_descriptors",
            "_PtarsConversionAdapter",
            "DEFAULT_BATCH_SIZE",
            "TimestampUnit",
        ):
            assert name not in storage.__all__, name

    def test_new_symbols_not_leaked_to_top_level(self) -> None:
        import protokit

        for name in ("to_arrow_batches", "to_parquet", "ParquetExtraNotInstalledError"):
            assert not hasattr(protokit, name), f"protokit.{name} leaked to top level"


class TestRecursiveRejectionSurfaceAdditions:
    def test_new_public_symbols_resolve(self) -> None:
        # The recursive-schema rejection delivery adds two typed exceptions.
        for name in ("RecursiveSchemaError", "UnsupportedWktError"):
            assert hasattr(storage, name), name
            assert name in storage.__all__, name

    def test_all_stays_sorted(self) -> None:
        assert storage.__all__ == sorted(storage.__all__)

    def test_new_exceptions_are_storage_errors(self) -> None:
        from protokit.storage import (
            RecursiveSchemaError,
            StorageError,
            UnsupportedWktError,
        )

        for exc in (RecursiveSchemaError, UnsupportedWktError):
            assert issubclass(exc, StorageError), exc

    def test_recursion_internals_not_exported(self) -> None:
        # The walker, the reject helper, and the WKT-file constant are internal.
        for name in ("_find_recursive_cycle", "_reject_recursive", "_STRUCT_PROTO_FILE"):
            assert name not in storage.__all__, name


class TestFidelitySignalSurfaceAdditions:
    def test_new_public_symbols_resolve(self) -> None:
        # The columnar fidelity-signal delivery adds a policy alias, a typed
        # exception, and a report.
        for name in ("Fidelity", "FidelityError", "FidelityReport"):
            assert hasattr(storage, name), name
            assert name in storage.__all__, name

    def test_all_stays_sorted(self) -> None:
        assert storage.__all__ == sorted(storage.__all__)

    def test_fidelity_error_is_a_storage_error(self) -> None:
        from protokit.storage import FidelityError, StorageError

        assert issubclass(FidelityError, StorageError)

    def test_fidelity_report_is_a_frozen_dataclass(self) -> None:
        import dataclasses

        from protokit.storage import FidelityReport

        assert dataclasses.is_dataclass(FidelityReport)
        assert FidelityReport.__dataclass_params__.frozen is True
        report = FidelityReport(rows=3, measured=True, unmodeled_records=1, unmodeled_bytes=2)
        assert (report.rows, report.measured, report.unmodeled_records) == (3, True, 1)

    def test_fidelity_internals_not_exported(self) -> None:
        # The per-record probe is internal.
        assert "_unmodeled_byte_delta" not in storage.__all__


class TestReadmeDocsPresence:
    def test_readme_mentions_storage_surface(self) -> None:
        readme = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
        assert "protokit.storage" in readme

    def test_readme_documents_storage_cli(self) -> None:
        readme = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
        assert "protokit storage scan" in readme
