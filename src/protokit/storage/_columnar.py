"""Columnar output path: convert a ``scan()`` stream to Apache Arrow / Parquet.

The PR3 sink. It consumes the existing :func:`protokit.storage.scan` stream of
materialized messages and converts them to Arrow ``RecordBatch``es in bounded
batches via the optional `ptars <https://github.com/0x26res/ptars>`_ backend
(Rust/PyO3, descriptor-driven). A ``to_parquet`` convenience streams one row
group per batch.

Three load-bearing properties (each pinned in code, not left implicit):

- **Optional extra (R8/R9).** ptars + pyarrow live behind the ``protokit[parquet]``
  extra; using this module without it raises :class:`ParquetExtraNotInstalledError`
  naming the install, never a raw ``ImportError``. Imports are deferred to first
  use (``importlib.util.find_spec`` probe + lazy ``import`` inside functions) so
  the core install never pays for them.
- **Entry points own scan construction (R1/R4/R14).** ``to_parquet`` /
  ``to_arrow_batches`` build the :class:`~protokit.storage.engine.ScanResult`
  themselves with ``on_error='collect'`` hard-wired — a caller cannot supply a
  ``ScanResult`` whose mode would silently break the completion guarantee
  (``skip`` drops faults; ``route``/``raise`` make ``.errors`` unreadable).
- **Completion honesty (R14).** After the stream is exhausted the sink reads
  ``ScanResult.errors``; any collected fault fails loud rather than closing a
  complete-looking Parquet. On any mid-stream exception the partially-written
  Parquet is discarded, never left as a truncated complete-looking file.

Single message type per conversion (R11): the adapter binds to one expected
message ``DESCRIPTOR`` and raises :class:`SchemaMismatchError` on a record of a
different type (a same-fully-qualified-name message from a different isolated
pool is a different descriptor object, hence a different type).
"""

from __future__ import annotations

import contextlib
import importlib.util
import os
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Literal

from google.protobuf.descriptor import Descriptor, FileDescriptor
from google.protobuf.message import Message

from protokit.storage.engine import scan
from protokit.storage.registry import StreamRegistry
from protokit.storage.source import Source, StorageError

if TYPE_CHECKING:  # pragma: no cover - typing only; runtime imports are lazy
    import pyarrow as pa
    import pyarrow.parquet as pq


# Default rows per batch / Parquet row group. Within the 64k-1M guidance; small
# batches inflate Parquet metadata, huge ones break the O(batch) memory bound.
DEFAULT_BATCH_SIZE = 65_536

# Arrow timestamp/temporal resolution for well-known-type conversion. ``us``
# (microsecond) is the default — it round-trips cleanly to Python ``datetime``;
# ``ns`` is fuller proto fidelity but exceeds ``datetime`` resolution.
TimestampUnit = Literal["s", "ms", "us", "ns"]


class ParquetExtraNotInstalledError(StorageError):
    """The columnar API was used without the ``protokit[parquet]`` extra.

    Raised in place of a raw ``ImportError`` so the remedy is actionable.
    """

    def __init__(self, missing: str) -> None:
        self.missing = missing
        super().__init__(
            f"the columnar/Parquet API requires the optional {missing!r} package; "
            f"install it with `pip install protokit[parquet]`"
        )


class HandlerBuildError(StorageError):
    """ptars could not build a converter for a message descriptor.

    Raised before any output is produced (R12), so a build failure never leaves
    a partially-written Parquet file.
    """

    def __init__(self, type_name: str, reason: str) -> None:
        self.type_name = type_name
        self.reason = reason
        super().__init__(
            f"could not build a columnar converter for message type "
            f"{type_name!r}: {reason}"
        )


class SchemaMismatchError(StorageError):
    """A record's type did not match the conversion's bound message type.

    v1 converts a single message type per pass (R11). Two streams sharing a
    fully-qualified name but resolved through different isolated pools are
    distinct descriptor objects, hence distinct types.
    """

    def __init__(self, expected: str, got: str) -> None:
        self.expected = expected
        self.got = got
        super().__init__(
            f"columnar conversion is bound to message type {expected!r} but "
            f"encountered a record of type {got!r}; v1 converts a single type "
            f"per pass"
        )


class IncompleteScanError(StorageError):
    """The scan did not complete cleanly, so the Parquet output is withheld.

    Under the columnar path's ``on_error='collect'`` mode, any per-record fault
    (a framing fault, an unknown stream, a decode failure) means the written
    file would not faithfully represent the whole scan. The sink fails loud and
    discards the partial output rather than presenting it as complete (R14).
    """

    def __init__(self, fault_count: int) -> None:
        self.fault_count = fault_count
        super().__init__(
            f"scan did not complete cleanly: {fault_count} record fault(s) were "
            f"collected; the Parquet output is withheld (use on_error='skip' on a "
            f"plain scan() if partial output is acceptable)"
        )


def _require_parquet() -> None:
    """Raise :class:`ParquetExtraNotInstalledError` if the extra is absent.

    Probes with ``importlib.util.find_spec`` (no import side effect) so the check
    is cheap and monkeypatchable, mirroring ``protokit._cli_utils._has_protoxy``.
    """
    for name in ("ptars", "pyarrow"):
        if importlib.util.find_spec(name) is None:
            raise ParquetExtraNotInstalledError(name)


def has_parquet() -> bool:
    """Return whether the ``protokit[parquet]`` extra is importable."""
    return (
        importlib.util.find_spec("ptars") is not None
        and importlib.util.find_spec("pyarrow") is not None
    )


def transitive_file_descriptors(descriptor: Descriptor) -> list[FileDescriptor]:
    """Return the descriptor's file plus its transitive dependency files.

    ptars's ``HandlerPool`` needs the full file set to resolve every referenced
    type (nested messages, well-known types). Files are returned in dependency
    order (each dependency before the file that imports it), deduplicated by
    name, walking the live descriptor graph since the source
    ``FileDescriptorProto``s are not retained by ``build_pool``.
    """
    ordered: list[FileDescriptor] = []
    seen: set[str] = set()

    def visit(fd: FileDescriptor) -> None:
        if fd.name in seen:
            return
        seen.add(fd.name)
        for dep in fd.dependencies:
            visit(dep)
        ordered.append(fd)

    visit(descriptor.file)
    return ordered


class _PtarsConversionAdapter:
    """ptars-backed proto -> Arrow converter, bound to one message type.

    Builds and validates the ptars ``HandlerPool`` once (R12) and reuses it plus
    the canonical descriptor-derived schema across every batch — so a handler
    failure surfaces before any output, and each batch is checked against one
    fixed schema (Parquet requires a single schema across row groups).
    """

    def __init__(self, descriptor: Descriptor, *, timestamp_unit: TimestampUnit = "us") -> None:
        import ptars  # lazy: only when the extra is present (R8)

        self._descriptor = descriptor
        files = transitive_file_descriptors(descriptor)
        try:
            self._pool = ptars.HandlerPool(
                files, ptars.PtarsConfig(timestamp_unit=timestamp_unit)
            )
            # Canonical schema, descriptor-derived and record-independent (R13):
            # an empty conversion yields the full schema used to open the writer.
            self._schema = self._pool.messages_to_record_batch(
                [], descriptor
            ).schema
        except Exception as exc:  # noqa: BLE001 - any ptars build failure is one fault class
            raise HandlerBuildError(descriptor.full_name, str(exc)) from exc

    @property
    def schema(self) -> pa.Schema:
        return self._schema

    def to_record_batch(self, messages: list[Message]) -> pa.RecordBatch:
        for message in messages:
            if message.DESCRIPTOR is not self._descriptor:
                raise SchemaMismatchError(
                    self._descriptor.full_name, message.DESCRIPTOR.full_name
                )
        batch = self._pool.messages_to_record_batch(messages, self._descriptor)
        if not batch.schema.equals(self._schema):
            raise SchemaMismatchError(
                f"{self._descriptor.full_name} (canonical schema)",
                f"{self._descriptor.full_name} (drifted batch schema)",
            )
        return batch


def _resolve_descriptor(registry: StreamRegistry, stream_id: str) -> Descriptor:
    resolved = registry.get(stream_id)
    if resolved is None:
        raise SchemaMismatchError(
            f"a registered stream_id (got unknown {stream_id!r})", stream_id
        )
    descriptor: Descriptor = resolved.message_class.DESCRIPTOR
    return descriptor


def to_arrow_batches(
    source: Source,
    registry: StreamRegistry,
    *,
    stream_id: str,
    predicate: Callable[[Message], bool] | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    timestamp_unit: TimestampUnit = "us",
) -> Iterator[pa.RecordBatch]:
    """Yield bounded Arrow ``RecordBatch``es for one message type from a scan.

    Owns scan construction (``on_error='collect'`` hard-wired). Binds to the
    ``stream_id``'s message type; a record of a different type raises
    :class:`SchemaMismatchError` (R11). After the stream is exhausted, any
    collected fault raises :class:`IncompleteScanError` (R14). Peak memory is
    O(``batch_size``).
    """
    _require_parquet()
    descriptor = _resolve_descriptor(registry, stream_id)
    adapter = _PtarsConversionAdapter(descriptor, timestamp_unit=timestamp_unit)
    result = scan(source, registry, predicate=predicate, on_error="collect")
    batch: list[Message] = []
    for record in result:
        batch.append(record.message)
        if len(batch) >= batch_size:
            yield adapter.to_record_batch(batch)
            batch = []
    if batch:
        yield adapter.to_record_batch(batch)
    faults = result.errors
    if faults:
        raise IncompleteScanError(len(faults))


def to_parquet(
    source: Source,
    registry: StreamRegistry,
    destination: str | os.PathLike[str],
    *,
    stream_id: str,
    predicate: Callable[[Message], bool] | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    timestamp_unit: TimestampUnit = "us",
) -> int:
    """Convert one message type from a scan and write it to a Parquet file.

    Streams one row group per batch (peak memory O(``batch_size``)). An empty
    result still writes a valid zero-row Parquet with the full descriptor-derived
    schema (R13). On any fault collected during the scan, or any mid-stream
    exception, the partially-written file is discarded and the error propagates —
    never a truncated file that reads as complete (R14/R12).

    Returns the number of rows written.

    ``destination`` is a filesystem path (a path is required so the sink can own
    creation and discard a partial file on failure).
    """
    _require_parquet()
    import pyarrow.parquet as pq  # lazy

    descriptor = _resolve_descriptor(registry, stream_id)
    adapter = _PtarsConversionAdapter(descriptor, timestamp_unit=timestamp_unit)
    result = scan(source, registry, predicate=predicate, on_error="collect")

    path = os.fspath(destination)
    writer: pq.ParquetWriter | None = None
    rows = 0
    try:
        batch: list[Message] = []
        for record in result:
            batch.append(record.message)
            if len(batch) >= batch_size:
                writer = _write_batch(writer, path, adapter, batch)
                rows += len(batch)
                batch = []
        if batch:
            writer = _write_batch(writer, path, adapter, batch)
            rows += len(batch)
        # Zero-record result still gets a valid, descriptor-schema'd file (R13).
        if writer is None:
            writer = pq.ParquetWriter(path, adapter.schema)
        # Completion honesty (R14): withhold a complete-looking file on any fault.
        faults = result.errors
        if faults:
            raise IncompleteScanError(len(faults))
        writer.close()
        writer = None
        return rows
    except BaseException:
        # Partial-file disposition: close the writer and discard the file so a
        # truncated Parquet is never left looking complete (R14 / R12 extended to
        # the write phase). Covers a fail-loud IncompleteScanError and any
        # mid-stream propagating exception (e.g. a non-FrameError source abort).
        if writer is not None:
            # Teardown is best-effort; the original error wins. Close the writer
            # (so the file handle is released) and unlink the partial file.
            with contextlib.suppress(Exception):
                writer.close()
            with contextlib.suppress(OSError):
                os.unlink(path)
        raise


def _write_batch(
    writer: pq.ParquetWriter | None,
    path: str,
    adapter: _PtarsConversionAdapter,
    messages: list[Message],
) -> pq.ParquetWriter:
    import pyarrow.parquet as pq  # lazy

    batch = adapter.to_record_batch(messages)
    if writer is None:
        writer = pq.ParquetWriter(path, adapter.schema)
    writer.write_batch(batch)
    return writer
