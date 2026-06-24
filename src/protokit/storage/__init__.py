"""Schema-aware scan/filter engine for protobuf data at rest.

``protokit.storage`` reads stored protobuf — files of length-delimited frames, a
pybind11 library's per-message ``memoryview``, any buffer source — routes each
record to its stream's **isolated** descriptor pool, parses it, and yields the
materialized message. It is the data-at-rest counterpart to the message differ
and schema-compatibility pillars: safe concurrent multi-version scanning built
on protokit's cross-pool, name-based machinery, accepting any buffer source —
a ``memoryview`` from a C++ buffer is a first-class record, not just files.

The architecture is an **adapter boundary**: user code yields stream-tagged
record bytes through a :class:`Source`; the engine owns routing, parsing, and
filtering. Two invariants are load-bearing — parse-confinement (the raw view
never escapes the parse step; upb copies into its arena) and fail-loud by
default (``on_error='raise'``; tolerant modes are opt-in and never silently
drop results).

Public surface:

- :func:`scan` — the engine entry point; returns a :class:`ScanResult`.
- :class:`Source` — the adapter protocol (yields ``(stream_id, record_bytes)``).
- :class:`ScanRecord` / :class:`ScanResult` — the yielded record and the
  iterable result (``.errors`` carries the ``collect``-mode report).
- :class:`StreamRegistry` — register each stream's schema up front.
- :class:`SchemaSource` / :class:`ResolvedSchema` and the concrete
  :class:`FileDescriptorSetSchema` / :class:`EmbeddedSchema` / :class:`ProtoFileSchema`
  — schema resolution (the last compiles ``.proto`` source).
- :func:`compile_fields` / :class:`CompiledSelection` / :func:`project` — the
  ``--fields`` projection API: ``compile_fields(spec, descriptor)`` validates a
  comma-separated dotted-path spec into a :class:`CompiledSelection`, and
  ``project(message, selection)`` prunes a parsed message to it, yielding the
  faithful nested view. Both are exported so a library consumer can build a
  selection without reaching into the private ``_fields`` module.
- :func:`to_arrow_batches` / :func:`to_parquet` — the columnar output path
  (optional ``protokit[parquet]`` extra): convert a scan stream to Apache Arrow
  ``RecordBatch``es, or stream it to a Parquet file one row group per batch.
  :func:`to_parquet` returns a :class:`FidelityReport` carrying the rows written
  plus the fidelity signal — how many records carried wire data the descriptor
  does not model, and which declared proto2 extensions ptars dropped from the
  schema (the ``fidelity='ignore'/'warn'/'error'`` policy governs both).
  :func:`to_arrow_batches` carries the same signal: it returns an iterable whose
  ``.report`` exposes a :class:`FidelityReport` once the stream is consumed.
- :class:`StorageError` / :class:`FrameError` / :class:`DuplicateStreamError` /
  :class:`SchemaCompileError` / :class:`WhereError` / :class:`FieldSelectionError` /
  :class:`ParquetExtraNotInstalledError` / :class:`SchemaMismatchError` /
  :class:`UnknownStreamError` / :class:`HandlerBuildError` /
  :class:`IncompleteScanError` / :class:`FidelityError` /
  :class:`RecursiveSchemaError` / :class:`UnsupportedWktError`
  — the typed exception hierarchy.
- ``OnError`` — the ``Literal['raise', 'skip', 'collect', 'route']`` policy type.
- ``Fidelity`` — the ``Literal['ignore', 'warn', 'error']`` columnar fidelity
  policy type (the ``fidelity=`` keyword on :func:`to_parquet`).

The reference frame adapters live in :mod:`protokit.storage.sources`
(``length_delimited``, ``per_message_view``) — they are *examples* of the
boundary, not protokit's framing taxonomy, so they are imported from there
rather than re-exported here.
"""

from __future__ import annotations

from protokit.storage._columnar import (
    Fidelity,
    FidelityError,
    FidelityReport,
    HandlerBuildError,
    IncompleteScanError,
    ParquetExtraNotInstalledError,
    RecursiveSchemaError,
    SchemaMismatchError,
    UnknownStreamError,
    UnsupportedWktError,
    to_arrow_batches,
    to_parquet,
)
from protokit.storage._fields import (
    CompiledSelection,
    FieldSelectionError,
    compile_fields,
    project,
)
from protokit.storage._where import WhereError
from protokit.storage.engine import OnError, ScanRecord, ScanResult, scan
from protokit.storage.registry import DuplicateStreamError, StreamRegistry
from protokit.storage.schema_source import (
    EmbeddedSchema,
    FileDescriptorSetSchema,
    ProtoFileSchema,
    ResolvedSchema,
    SchemaCompileError,
    SchemaSource,
)
from protokit.storage.source import FrameError, Source, StorageError

__all__ = [
    "CompiledSelection",
    "DuplicateStreamError",
    "EmbeddedSchema",
    "Fidelity",
    "FidelityError",
    "FidelityReport",
    "FieldSelectionError",
    "FileDescriptorSetSchema",
    "FrameError",
    "HandlerBuildError",
    "IncompleteScanError",
    "OnError",
    "ParquetExtraNotInstalledError",
    "ProtoFileSchema",
    "RecursiveSchemaError",
    "ResolvedSchema",
    "ScanRecord",
    "ScanResult",
    "SchemaCompileError",
    "SchemaMismatchError",
    "SchemaSource",
    "Source",
    "StorageError",
    "StreamRegistry",
    "UnknownStreamError",
    "UnsupportedWktError",
    "WhereError",
    "compile_fields",
    "project",
    "scan",
    "to_arrow_batches",
    "to_parquet",
]
