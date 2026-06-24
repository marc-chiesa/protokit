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
- **Recursive-schema rejection (pre-ptars).** A self-referential message type
  has no finite Arrow representation and segfaults the ptars backend during
  schema construction — an uncatchable process death that bypasses the
  ``HandlerBuildError`` net and the partial-file cleanup above. A descriptor
  pre-flight (:func:`_reject_recursive`, the load-bearing third disposal layer)
  detects the cycle and raises :class:`RecursiveSchemaError` /
  :class:`UnsupportedWktError` before ptars is invoked, keeping the failure
  inside the catchable model.

Single message type per conversion (R11): the adapter binds to one expected
message ``DESCRIPTOR`` and raises :class:`SchemaMismatchError` on a record of a
different type (a same-fully-qualified-name message from a different isolated
pool is a different descriptor object, hence a different type).
"""

from __future__ import annotations

import contextlib
import importlib.util
import os
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from google.protobuf.descriptor import Descriptor, FieldDescriptor, FileDescriptor
from google.protobuf.message import EncodeError, Message

from protokit.storage.engine import ScanRecord, scan
from protokit.storage.registry import StreamRegistry
from protokit.storage.source import FrameError, Source, StorageError

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

# Fidelity-signal policy over records carrying wire data the descriptor does not
# model: ``ignore`` skips the per-record probe entirely; ``warn`` (the default)
# measures and surfaces the count; ``error`` fails the conversion loud. Distinct
# from the ``on_error`` decode-fault axis (hard-wired ``collect`` here).
Fidelity = Literal["ignore", "warn", "error"]


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
            f"could not build a columnar converter for message type {type_name!r}: {reason}"
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


class UnknownStreamError(StorageError):
    """The requested ``stream_id`` is not registered in the ``StreamRegistry``.

    A caller-side configuration error (the stream was never registered) — distinct
    from :class:`SchemaMismatchError`, which is a *record* whose type differs from
    the bound type mid-scan.
    """

    def __init__(self, stream_id: str) -> None:
        self.stream_id = stream_id
        super().__init__(
            f"stream_id {stream_id!r} is not registered; register it on the "
            f"StreamRegistry before converting"
        )


class IncompleteScanError(StorageError):
    """The scan did not complete cleanly, so the Parquet output is withheld.

    Under the columnar path's ``on_error='collect'`` mode, any per-record fault
    (a framing fault, an unknown stream, a decode failure) means the written
    file would not faithfully represent the whole scan. The sink fails loud and
    discards the partial output rather than presenting it as complete (R14).

    Attributes:
        faults: The collected :class:`~protokit.storage.FrameError`s, verbatim,
            so callers can report fault locations (stream / record index /
            offset / reason) without scraping the message string. ``offset`` is
            ``None`` for non-positional faults (see :class:`FrameError`).
        fault_count: ``len(faults)`` — the stable count attribute.
    """

    def __init__(self, faults: tuple[FrameError, ...]) -> None:
        self.faults = faults
        self.fault_count = len(faults)
        super().__init__(
            f"scan did not complete cleanly: {self.fault_count} record fault(s) "
            f"were collected (a framing fault can also truncate the scan, so "
            f"further records may be missing beyond the count); the Parquet "
            f"output is withheld (use on_error='skip' on a plain scan() if "
            f"partial output is acceptable)"
        )


class RecursiveSchemaError(StorageError):
    """A bound message type is recursive, so the columnar path rejects it.

    Arrow/Parquet schemas are finite, acyclic type trees: a self-referential
    message — directly, mutually, or through map / group / oneof message fields
    — has no columnar representation, and ptars segfaults building one. The
    pre-flight detects the cycle on the descriptor graph before ptars is invoked
    (R12), so this raises before any output exists.

    Attributes:
        type_name: The bound message type's fully-qualified name.
        cycle: The fully-qualified names forming the cycle, with the repeated
            type at both ends (e.g. ``("t.Node", "t.Node")``).
    """

    def __init__(self, type_name: str, cycle: tuple[str, ...]) -> None:
        self.type_name = type_name
        self.cycle = tuple(cycle)
        super().__init__(
            f"message type {type_name!r} is recursive and cannot be represented "
            f"in Arrow/Parquet (cycle: {' -> '.join(cycle)}); recursive message "
            f"types are not supported by the columnar path"
        )


class UnsupportedWktError(StorageError):
    """A bound message embeds a recursive well-known type with no columnar form.

    ``google.protobuf.Struct`` / ``Value`` / ``ListValue`` are mutually
    recursive (``Struct -> Value -> Struct``) and segfault ptars 0.0.17's schema
    build, exactly like a user-authored recursive type. They are split from
    :class:`RecursiveSchemaError` so the failure reads as an unsupported
    well-known type — the user did not write a recursive schema — rather than as
    their own recursion, keeping the columnar go/no-go signal honest about what
    actually blocks real data.

    Attributes:
        type_name: The bound message type's fully-qualified name.
        cycle: The recursive well-known-type cycle reached from it.
    """

    def __init__(self, type_name: str, cycle: tuple[str, ...]) -> None:
        self.type_name = type_name
        self.cycle = tuple(cycle)
        super().__init__(
            f"message type {type_name!r} embeds the recursive well-known type "
            f"google.protobuf.Struct/Value/ListValue (cycle: {' -> '.join(cycle)}"
            f"), which has no Arrow/Parquet representation; the columnar path "
            f"does not support it"
        )


class FidelityError(StorageError):
    """The scan carried unmodeled wire data and ``fidelity='error'`` was set.

    Under ``fidelity='error'`` a record that carried wire data the descriptor
    does not model — a proto2 out-of-range closed-enum value, or an *undeclared*
    unknown/extension field — fails the conversion loud rather than writing a
    Parquet that silently diverges from what a protobuf consumer would see. The
    partial output is discarded, like :class:`IncompleteScanError` (R14
    all-or-nothing publish). It is a *distinct* error channel from
    ``IncompleteScanError``: that signals records that failed to **decode**,
    whereas a fidelity fault is a cleanly-decoded record that carried unmodeled
    bytes.

    It carries two signals, either of which can trigger it: the per-record probe
    (``unmodeled_records`` / ``unmodeled_bytes``) and the *structural oracle*
    (``dropped_extensions`` — declared proto2 extensions ptars drops from the
    Arrow schema). The structural signal is known at bind time, so a structural
    ``error`` fails fast before any record is read or written; in that case the
    per-record counts are ``0``.

    Attributes:
        unmodeled_records: how many records carried unmodeled wire data.
        unmodeled_bytes: total unmodeled bytes across those records.
        dropped_extensions: declared proto2 extensions ptars dropped from the
            schema (empty when the trigger was the per-record signal).
    """

    def __init__(
        self,
        unmodeled_records: int = 0,
        unmodeled_bytes: int = 0,
        dropped_extensions: tuple[str, ...] = (),
    ) -> None:
        self.unmodeled_records = unmodeled_records
        self.unmodeled_bytes = unmodeled_bytes
        self.dropped_extensions = dropped_extensions
        parts: list[str] = []
        if dropped_extensions:
            parts.append(
                f"the descriptor declares {len(dropped_extensions)} extension(s) "
                f"ptars drops from the Arrow schema ({', '.join(dropped_extensions)})"
            )
        if unmodeled_records:
            parts.append(
                f"{unmodeled_records} record(s) carried {unmodeled_bytes} byte(s) "
                f"the descriptor does not model"
            )
        detail = "; ".join(parts) if parts else "unmodeled wire data was detected"
        super().__init__(
            f"scan carried unmodeled wire data and fidelity='error': {detail}; the "
            f"Parquet output is withheld (use fidelity='warn' to write it and "
            f"surface the signal instead)"
        )


@dataclass(frozen=True)
class FidelityReport:
    """Result of a columnar conversion: rows written plus the fidelity signal.

    Returned by :func:`to_parquet` (replacing its former bare ``int`` row count).
    ``rows`` is the number of records written. The fidelity signal counts records
    that carried wire data the descriptor does not model (a non-empty recursive
    unknown-field set) and the total such bytes.

    ``measured`` distinguishes a *measured zero* from *not measured*: under
    ``fidelity='ignore'`` neither signal runs, so ``measured`` is ``False``, the
    counts are ``0``, and ``dropped_extensions`` is empty by convention (not a
    real observation). Under ``fidelity='warn'`` / ``'error'`` ``measured`` is
    ``True`` and both signals are real — check ``measured`` before reading them.

    ``dropped_extensions`` is the *structural* signal: the fully-qualified names
    of declared proto2 extensions ptars dropped from the Arrow schema. This is a
    loss class the per-record probe is blind to — a declared extension reads into
    ``Extensions[...]`` with an empty unknown-field set, so its byte delta is
    ``0`` — and it is computed once per conversion, independent of record count.

    Attributes:
        rows: records written to the output.
        measured: whether fidelity detection ran (``False`` under ``'ignore'``).
        unmodeled_records: records carrying unmodeled wire data (``0`` if not measured).
        unmodeled_bytes: total unmodeled bytes across those records (``0`` if not measured).
        dropped_extensions: declared proto2 extensions ptars dropped from the
            schema (empty if none, or if not measured).
    """

    rows: int
    measured: bool
    unmodeled_records: int
    unmodeled_bytes: int
    dropped_extensions: tuple[str, ...] = ()


def _require_parquet() -> None:
    """Raise :class:`ParquetExtraNotInstalledError` if the extra is absent.

    Probes with ``importlib.util.find_spec`` (no import side effect) so the check
    is cheap and monkeypatchable, mirroring ``protokit._cli_utils._has_protoxy``.
    """
    for name in ("ptars", "pyarrow"):
        if importlib.util.find_spec(name) is None:
            raise ParquetExtraNotInstalledError(name)


def _has_parquet() -> bool:
    """Return whether the ``protokit[parquet]`` extra is importable (internal)."""
    try:
        _require_parquet()
        return True
    except ParquetExtraNotInstalledError:
        return False


def _transitive_file_descriptors(descriptor: Descriptor) -> list[FileDescriptor]:
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


# The recursive well-known types live in this one file. ptars 0.0.17 segfaults
# building an Arrow schema for any of them (Struct -> Value -> Struct has no
# finite columnar shape), so a cycle whose every node is declared here is the
# unsupported-WKT case, distinct from a user-authored recursive schema.
_STRUCT_PROTO_FILE = "google/protobuf/struct.proto"

_MESSAGE_FIELD_TYPES = frozenset((FieldDescriptor.TYPE_MESSAGE, FieldDescriptor.TYPE_GROUP))


def _find_recursive_cycle(
    descriptor: Descriptor,
) -> tuple[list[str], bool] | None:
    """Find a message-type cycle reachable from ``descriptor``.

    Returns ``(cycle, is_wkt_family)`` where ``cycle`` is the list of
    fully-qualified type names forming the cycle — the repeated type appears at
    both ends, e.g. ``["t.Node", "t.Node"]`` or ``["p.A", "p.B", "p.A"]`` — and
    ``is_wkt_family`` is true when every node on the cycle is declared in
    ``struct.proto`` (the recursive ``google.protobuf.Struct`` / ``Value`` /
    ``ListValue`` family). Returns ``None`` when the reachable type graph is
    acyclic.

    The walk is an iterative DFS (no Python recursion — a recursive walk would
    reintroduce a ``RecursionError`` on a self-referential type, the very class
    of uncatchable failure this guard exists to remove). A path-scoped
    ``in_progress`` set, popped on backtrack via a ``leave`` sentinel, means a
    DAG diamond — a type reached by two non-cyclic paths — is not a cycle; only
    a type reached while still on the current path is. An ``acyclic`` memo
    records nodes fully explored without a cycle, so a shared sub-message in a
    DAG is walked once, not once per path (O(V+E)); when a type has multiple
    distinct cycles, the first reached in DFS order is returned. Map fields need no
    special handling: the synthetic map-entry message is an ordinary node whose
    ``value`` field is walked like any other. Every message- or group-typed
    field is descended into exactly once per node, so a map entry is not also
    walked a second time.
    """
    on_path: list[Descriptor] = []  # descriptors on the current DFS path
    in_progress: set[str] = set()  # their full_names, for O(1) membership
    acyclic: set[str] = set()  # full_names fully explored with no cycle (memo)
    # Stack entries: ("enter", Descriptor) or ("leave", Descriptor).
    stack: list[tuple[str, Descriptor]] = [("enter", descriptor)]
    while stack:
        action, node = stack.pop()
        if action == "leave":
            in_progress.discard(node.full_name)
            on_path.pop()
            # A node popped with no cycle is acyclic on every path that reaches
            # it — any cycle through it is found while it is still in_progress —
            # so later paths skip it. Without this memo a shared sub-message in a
            # DAG diamond is re-walked once per path: exponential on a wide, deep
            # (but valid, acyclic) schema, which would hang the pre-flight.
            acyclic.add(node.full_name)
            continue
        if node.full_name in acyclic:
            continue
        if node.full_name in in_progress:
            start = next(i for i, d in enumerate(on_path) if d.full_name == node.full_name)
            cycle_descs = on_path[start:] + [node]
            cycle = [d.full_name for d in cycle_descs]
            is_wkt = all(d.file.name == _STRUCT_PROTO_FILE for d in cycle_descs)
            return cycle, is_wkt
        in_progress.add(node.full_name)
        on_path.append(node)
        stack.append(("leave", node))
        for field in node.fields:
            if field.is_extension:
                continue
            if field.type in _MESSAGE_FIELD_TYPES:
                stack.append(("enter", field.message_type))
    return None


def _reject_recursive(descriptor: Descriptor) -> None:
    """Raise if ``descriptor``'s reachable type graph contains a cycle.

    Runs before ptars sees the descriptor (KTD2): a recursive type segfaults
    ptars 0.0.17's schema build — an uncatchable process death — so the only fix
    is to detect and reject it in Python first. The recursive ``google.protobuf``
    struct family raises :class:`UnsupportedWktError`; every other cycle raises
    :class:`RecursiveSchemaError`.
    """
    found = _find_recursive_cycle(descriptor)
    if found is None:
        return
    cycle, is_wkt = found
    if is_wkt:
        raise UnsupportedWktError(descriptor.full_name, tuple(cycle))
    raise RecursiveSchemaError(descriptor.full_name, tuple(cycle))


def _unmodeled_byte_delta(message: Message) -> int | None:
    """Wire bytes ``message`` carried that its descriptor does not model.

    The serialized-size difference between ``message`` and a copy with its
    unknown-field set discarded — recursively, into submessages, repeated
    elements, and map entries (``DiscardUnknownFields`` clears the whole tree). A
    non-zero delta means the message carried wire data outside the descriptor: a
    proto2 out-of-range closed-enum value (which the runtime relegates to the
    unknown-field set) or an *undeclared* unknown/extension field. ``0`` means
    the descriptor modeled every byte — including proto3 open-enum out-of-range
    values, which are preserved as the field value, not relegated.

    Returns ``None`` ("cannot measure") when the message is not fully
    initialized: ``ByteSize`` raises ``EncodeError`` on a proto2 message missing
    a required field. ptars itself rejects such a record during conversion, so
    the probe defers rather than letting the error escape its own pre-pass.

    The signal is a causally-linked proxy computed on the parsed message, not on
    ptars's column output: the same out-of-range value the descriptor cannot
    model is what both lands in the unknown-field set here and is surfaced by
    ptars in the column, so a non-empty set is exactly the divergence condition.
    A field the descriptor *does* model but ptars drops — a *declared* proto2
    extension (read into ``Extensions[...]`` with an empty unknown set) or a
    group field — is invisible to this probe; that is a documented non-goal.
    """
    try:
        # Typed locals: protobuf ships no stubs, so ByteSize() is Any; annotate so
        # mypy --strict (warn_return_any) sees an int subtraction, not Any.
        before: int = message.ByteSize()
        clone = type(message)()
        clone.CopyFrom(message)
        clone.DiscardUnknownFields()
        after: int = clone.ByteSize()
        return before - after
    except EncodeError:
        return None


def _dropped_declared_extensions(
    descriptor: Descriptor, schema_names: Iterable[str]
) -> tuple[str, ...]:
    """Declared proto2 extensions ptars drops from the produced Arrow schema.

    ptars columnizes ``descriptor.fields`` only; declared extensions live in the
    descriptor's pool, not in ``descriptor.fields``, so ptars emits no column for
    them and they vanish from the Parquet even though a protobuf consumer that
    compiled the extension's ``.proto`` reads them back via ``Extensions[...]``.
    This is the structural blind spot the per-record :func:`_unmodeled_byte_delta`
    probe cannot see: a *declared* extension lands in ``Extensions[...]`` with an
    empty unknown-field set, so its byte delta is ``0``.

    The check is keyed on extension identity, never on a union of field and
    extension names — a regular field sharing a name with an extension must not
    mask the dropped extension. ``schema_names`` is forward-defensive: an
    extension is reported as dropped unless ptars produced a *non-field* column
    attributable to it (its short name appears in the schema but is not one of the
    descriptor's regular fields). For ptars 0.0.17 ptars columnizes no extension,
    so every declared extension is reported; the end-to-end pin guards that
    assumption against a future ptars that columnizes one.

    Returns the fully-qualified name of each dropped extension, or an empty tuple
    when the pool declares none for ``descriptor`` (the common case).
    """
    extensions = descriptor.file.pool.FindAllExtensions(descriptor)
    if not extensions:
        return ()
    field_names = {field.name for field in descriptor.fields}
    # Columns ptars produced that are NOT regular fields are the only place a
    # (future) extension column could appear. Subtracting field names first means
    # a regular field sharing a name with an extension cannot mask the extension.
    extension_columns = set(schema_names) - field_names
    return tuple(ext.full_name for ext in extensions if ext.name not in extension_columns)


class _PerRecordFidelity:
    """Accumulates the per-record byte-delta signal across batches.

    Shared by :func:`to_parquet` and the :func:`to_arrow_batches` wrapper so the
    two delta-accounting paths cannot drift (a parity test guards it). Under
    ``fidelity='ignore'`` ``measure`` is ``False`` and :meth:`observe` is a no-op,
    so the probe never runs.
    """

    def __init__(self, measure: bool) -> None:
        self.measure = measure
        self.records = 0
        self.bytes = 0

    def observe(self, messages: Iterable[Message]) -> None:
        if not self.measure:
            return
        for message in messages:
            delta = _unmodeled_byte_delta(message)
            if delta:  # not None ("cannot measure") and > 0
                self.records += 1
                self.bytes += delta


class _PtarsConversionAdapter:
    """ptars-backed proto -> Arrow converter, bound to one message type.

    Builds and validates the ptars ``HandlerPool`` once (R12) and reuses it plus
    the canonical descriptor-derived schema across every batch — so a handler
    failure surfaces before any output, and each batch is checked against one
    fixed schema (Parquet requires a single schema across row groups).

    A recursive descriptor is rejected by :func:`_reject_recursive` before the
    pool is built: ptars 0.0.17 segfaults constructing an Arrow schema for a
    self-referential type, so the cycle must be caught in Python first.
    """

    def __init__(self, descriptor: Descriptor, *, timestamp_unit: TimestampUnit = "us") -> None:
        import ptars  # lazy: only when the extra is present (R8)

        self._descriptor = descriptor
        # Reject a recursive descriptor before ptars sees it: ptars 0.0.17
        # segfaults building an Arrow schema for a self-referential type, an
        # uncatchable process death that bypasses the HandlerBuildError net
        # below and the writer's partial-file cleanup. This is the load-bearing
        # third disposal layer (KTD2).
        _reject_recursive(descriptor)
        files = _transitive_file_descriptors(descriptor)
        try:
            self._pool = ptars.HandlerPool(files, ptars.PtarsConfig(timestamp_unit=timestamp_unit))
            # Canonical schema, descriptor-derived and record-independent (R13):
            # an empty conversion yields the full schema used to open the writer.
            self.schema: pa.Schema = self._pool.messages_to_record_batch([], descriptor).schema
        except Exception as exc:  # noqa: BLE001 - any ptars build failure is one fault class
            raise HandlerBuildError(descriptor.full_name, str(exc)) from exc

    def to_record_batch(self, messages: list[Message]) -> pa.RecordBatch:
        for message in messages:
            if message.DESCRIPTOR is not self._descriptor:
                raise SchemaMismatchError(self._descriptor.full_name, message.DESCRIPTOR.full_name)
        batch = self._pool.messages_to_record_batch(messages, self._descriptor)
        if not batch.schema.equals(self.schema):
            # A drift between the canonical (empty-conversion) schema and a
            # populated batch's schema can only be a ptars/pyarrow regression,
            # not a data fault — surface it as an internal invariant breach, not
            # a SchemaMismatchError (whose expected/got hold real type names).
            raise RuntimeError(
                f"ptars produced a schema that drifted from the canonical "
                f"descriptor schema for {self._descriptor.full_name!r}; this "
                f"indicates a ptars/pyarrow regression"
            )
        return batch


def _resolve_descriptor(registry: StreamRegistry, stream_id: str) -> Descriptor:
    resolved = registry.get(stream_id)
    if resolved is None:
        raise UnknownStreamError(stream_id)
    return resolved.message_class.DESCRIPTOR


def _batched(records: Iterable[ScanRecord], batch_size: int) -> Iterator[list[Message]]:
    """Group a ``ScanRecord`` stream into message batches of at most ``batch_size``.

    Shared by both entry points so the slicing arithmetic lives in one place.
    Peak memory is O(``batch_size``) — a flushed batch is dropped before the next
    accumulates.
    """
    batch: list[Message] = []
    for record in records:
        batch.append(record.message)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


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

    The fault check runs only after the stream is fully consumed, so a caller
    that breaks early will not observe :class:`IncompleteScanError` — exhaust the
    iterator, or use :func:`to_parquet` (all-or-nothing), when completeness
    matters.

    Because this is a generator, the descriptor pre-flight fires on the first
    iteration, not at call time: a recursive bound type raises
    :class:`RecursiveSchemaError` / :class:`UnsupportedWktError` when iteration
    begins (:func:`to_parquet` is eager and raises at call time).
    """
    _require_parquet()
    descriptor = _resolve_descriptor(registry, stream_id)
    adapter = _PtarsConversionAdapter(descriptor, timestamp_unit=timestamp_unit)
    result = scan(source, registry, predicate=predicate, on_error="collect")
    for chunk in _batched(result, batch_size):
        yield adapter.to_record_batch(chunk)
    faults = result.errors
    if faults:
        raise IncompleteScanError(faults)


def to_parquet(
    source: Source,
    registry: StreamRegistry,
    destination: str | os.PathLike[str],
    *,
    stream_id: str,
    predicate: Callable[[Message], bool] | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    timestamp_unit: TimestampUnit = "us",
    fidelity: Fidelity = "warn",
) -> FidelityReport:
    """Convert one message type from a scan and write it to a Parquet file.

    Streams one row group per batch (peak memory O(``batch_size``)). An empty
    result still writes a valid zero-row Parquet with the full descriptor-derived
    schema (R13). On any fault collected during the scan, or any mid-stream
    exception, the partially-written file is discarded and the error propagates —
    never a truncated file that reads as complete (R14/R12).

    Returns a :class:`FidelityReport` — the rows written plus the fidelity signal:
    how many records carried wire data the descriptor does not model (the
    per-record probe), and which declared proto2 extensions ptars dropped from the
    Arrow schema (the structural oracle, computed once at bind). ``fidelity``
    governs both: ``ignore`` skips them (no cost, ``measured=False``); ``warn``
    (default) measures and surfaces them, writing the file regardless; ``error``
    raises :class:`FidelityError` and discards the partial file. The fidelity axis
    is orthogonal to ``on_error`` (hard-wired ``collect``). Precedence under
    ``error``: a structural drop fails fast at bind (before any record or file),
    then a *decode* fault (:class:`IncompleteScanError`) takes precedence over the
    per-record fidelity signal.

    ``destination`` is a filesystem path (a path is required so the sink can own
    creation and discard a partial file on failure).
    """
    _require_parquet()
    import pyarrow.parquet as pq  # lazy

    descriptor = _resolve_descriptor(registry, stream_id)
    adapter = _PtarsConversionAdapter(descriptor, timestamp_unit=timestamp_unit)

    # Structural oracle: which declared proto2 extensions ptars drops from the
    # Arrow schema, computed once from the descriptor + the cached schema (no
    # record needed). Under `error` it fails fast HERE — before the scan runs and
    # before the writer opens — so no partial file is created and the structural
    # drop pre-empts both decode faults and the per-record signal (the precedence
    # ladder: recursion -> structural -> decode -> per-record). Skipped under
    # `ignore` (no FindAllExtensions call), matching the per-record probe gate.
    measure = fidelity != "ignore"
    dropped_extensions = (
        _dropped_declared_extensions(descriptor, adapter.schema.names) if measure else ()
    )
    if fidelity == "error" and dropped_extensions:
        raise FidelityError(dropped_extensions=dropped_extensions)

    result = scan(source, registry, predicate=predicate, on_error="collect")
    path = os.fspath(destination)

    # The per-record probe runs in this sink loop, on the same Message objects the
    # adapter hands to ptars — not inside the adapter (its return is a RecordBatch
    # and it is shared by to_arrow_batches). The accumulator is shared with the
    # to_arrow_batches wrapper so the two delta-accounting paths cannot drift.
    per_record = _PerRecordFidelity(measure)

    writer: pq.ParquetWriter | None = None
    rows = 0
    try:
        # Open up front from the descriptor-derived schema: an empty result then
        # still yields a valid zero-row Parquet (R13), with no first-batch case.
        writer = pq.ParquetWriter(path, adapter.schema)
        for chunk in _batched(result, batch_size):
            writer.write_batch(adapter.to_record_batch(chunk))
            rows += len(chunk)
            per_record.observe(chunk)
        # Completion honesty (R14): withhold a complete-looking file on any fault.
        # Decode faults take precedence over the per-record fidelity signal — a
        # corrupt record is a stronger signal than a cleanly-decoded one carrying
        # unmodeled bytes. (A structural drop already fail-fasted at bind above.)
        faults = result.errors
        if faults:
            raise IncompleteScanError(faults)
        # Strict fidelity: fail loud and discard the partial, like a decode fault.
        # Raised inside the try (before writer.close) so the disposal below fires.
        if fidelity == "error" and per_record.records:
            raise FidelityError(per_record.records, per_record.bytes)
        writer.close()
        writer = None
        return FidelityReport(
            rows=rows,
            measured=measure,
            unmodeled_records=per_record.records,
            unmodeled_bytes=per_record.bytes,
            dropped_extensions=dropped_extensions,
        )
    except BaseException:
        # Partial-file disposition (R14 / R12 extended to the write phase): close
        # the writer, then discard ANY file the writer may have created so a
        # truncated Parquet is never left looking complete. Covers a fail-loud
        # IncompleteScanError, any mid-stream propagating exception (e.g. a
        # non-FrameError source abort), AND a ParquetWriter() constructor failure
        # that created the file before raising (writer stays None there). The
        # unlink is unconditional; a missing file raises OSError, suppressed.
        if writer is not None:
            with contextlib.suppress(Exception):
                writer.close()
        with contextlib.suppress(OSError):
            os.unlink(path)
        raise
