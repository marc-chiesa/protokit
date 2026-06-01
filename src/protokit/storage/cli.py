"""Click CLI for ``protokit storage`` — scan / head / count over stored proto.

A command-line face for :func:`protokit.storage.scan`: point it at a file of
length-delimited protobuf frames, resolve the message type from one schema
source, optionally filter with ``--where``, and dump / head / count the records.
This is the ``protoc --decode`` replacement (many records, pipeable, filterable).

Schema sources (exactly one required, plus ``--type``):
  --desc DESC --type FQN              a FileDescriptorSet file
  --proto FILE [--proto-path DIR] --type FQN   compile .proto (needs a backend)

(``--embedded-schema`` is a library-only resolver in PR1.5 — its file form is not
yet pinned, so it is not a CLI flag.)

Output: ``scan`` / ``head`` dump each record (``--format human`` default, or
``json`` as compact JSONL). ``count`` prints the count.

Error policy (``--on-error``): ``raise`` (default, fail-loud) aborts on the first
bad record; ``skip`` drops bad records; ``warn`` reports each to stderr live and
continues. NOTE: with the length-delimited reader a *framing* fault (truncated
frame) ends the scan even under ``skip`` / ``warn`` — only *decode* and
*unknown-stream* faults are recovered past.

Exit codes: 0 = success, 2 = error (a bad flag, an unresolved schema, a malformed
``--where``, or a data fault under ``--on-error raise``). ``count --quiet`` adds
the grep-like signal: 1 = zero matches, 0 = at least one (mirroring ``diff
--quiet``). Storage library code never calls ``sys.exit``; this layer owns it.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO, NamedTuple

import click
from google.protobuf import descriptor_pb2, json_format, text_format
from google.protobuf.message import DecodeError, Message

from protokit._cli_utils import error_exit
from protokit._pools import DescriptorPoolError
from protokit.storage import (
    FrameError,
    OnError,
    ScanRecord,
    ScanResult,
    Source,
    StorageError,
    StreamRegistry,
    scan,
)
from protokit.storage._fields import (
    CompiledSelection,
    FieldSelectionError,
    compile_fields,
    no_presence_kwarg,
    project,
)
from protokit.storage._where import WhereError, compile_where
from protokit.storage.schema_source import FileDescriptorSetSchema, ProtoFileSchema
from protokit.storage.sources.length_delimited import length_delimited

_TYPED_CLI_ERRORS = (StorageError, DescriptorPoolError)

# The non-tolerant CLI --on-error values map directly to engine OnError values;
# 'warn' is handled separately (route + a stderr sink). An explicit, typed map
# keeps the translation exhaustive and avoids a cast at the scan() boundary.
_CLI_TO_ENGINE: dict[str, OnError] = {"raise": "raise", "skip": "skip"}


class _Setup(NamedTuple):
    """The resolved scan setup shared by every subcommand."""

    registry: StreamRegistry
    stream_id: str
    predicate: Callable[[Message], bool] | None
    selection: CompiledSelection | None
    explicit_defaults: bool


def _common_options(command: Callable[..., None]) -> Callable[..., None]:
    """Stack the schema-source + input + filter options shared by all subcommands."""
    options = [
        click.argument(
            "data_file",
            type=click.Path(exists=True, dir_okay=False, path_type=Path),
        ),
        click.option(
            "--desc",
            type=click.Path(exists=True, dir_okay=False, path_type=Path),
            help="FileDescriptorSet file (with --type).",
        ),
        click.option(
            "--proto",
            type=click.Path(exists=True, dir_okay=False, path_type=Path),
            help=".proto file to compile (with --type; needs a compile backend).",
        ),
        click.option(
            "--proto-path",
            "-I",
            "proto_paths",
            multiple=True,
            metavar="DIR",
            help="Import path for .proto compilation (-I). Repeatable.",
        ),
        click.option(
            "--type",
            "--message-type",
            "type_name",
            help="Fully-qualified message type name (required).",
        ),
        click.option(
            "--where",
            "where_expr",
            metavar="EXPR",
            help="Filter: 'path == value', 'path != value', or 'has:path'.",
        ),
        click.option(
            "--on-error",
            "on_error",
            type=click.Choice(["raise", "skip", "warn"]),
            default="raise",
            help="raise (default, fail-loud) | skip | warn (report to stderr, continue).",
        ),
    ]
    for option in reversed(options):
        command = option(command)
    return command


def _format_option(command: Callable[..., None]) -> Callable[..., None]:
    return click.option(
        "--format",
        "output_format",
        type=click.Choice(["human", "json"]),
        default="human",
        envvar="PROTOKIT_FORMAT",
        help="Output format: human (default) or json (compact JSONL). "
        "Also reads PROTOKIT_FORMAT.",
    )(command)


def _fields_option(command: Callable[..., None]) -> Callable[..., None]:
    """Add ``--fields`` to a command (scan/head ONLY — never ``count``).

    Deliberately *not* part of ``_common_options``: ``count_cmd`` shares that
    decorator but declares no ``fields`` parameter, so a common ``--fields``
    option would make Click raise ``TypeError`` on a plain ``protokit storage
    count``. Keeping ``--fields`` off ``count`` also gives R1's "count rejects
    --fields" for free (Click emits ``No such option: --fields``, exit 2).
    """
    return click.option(
        "--fields",
        "fields",
        metavar="PATHS",
        help="Project to these comma-separated dotted field paths "
        "(e.g. 'header.code,source'). snake_case keys; faithful nested view.",
    )(command)


def _explicit_defaults_option(command: Callable[..., None]) -> Callable[..., None]:
    """Add ``--explicit-defaults`` to a command (scan/head ONLY — never ``count``).

    A JSON-only density flag (R7/R9): with ``--format json`` it renders each
    full record with no-presence fields filled at their default (camelCase keys),
    a density variant of the shipped PR1.5 JSON. Kept off ``count`` (which has no
    output rows to densify) the same way ``--fields`` is, and mutually exclusive
    with ``--fields`` (R14, enforced in :func:`_prepare`).
    """
    return click.option(
        "--explicit-defaults",
        "explicit_defaults",
        is_flag=True,
        help="JSON only: emit a dense full record — fill no-presence fields at "
        "their default (camelCase keys). Mutually exclusive with --fields.",
    )(command)


@click.group()
def main() -> None:
    """Scan, head, and count stored protobuf (length-delimited frames)."""


def _build_schema_source(
    desc: Path | None,
    proto: Path | None,
    proto_paths: tuple[str, ...],
    type_name: str,
) -> FileDescriptorSetSchema | ProtoFileSchema:
    """Build the SchemaSource for the chosen flag (exactly-one already validated)."""
    if desc is not None:
        fds = descriptor_pb2.FileDescriptorSet()
        try:
            fds.ParseFromString(desc.read_bytes())
        except (OSError, DecodeError) as exc:
            error_exit(f"failed to read descriptor set ({desc}): {exc}")
        return FileDescriptorSetSchema(fds, type_name)
    assert proto is not None
    return ProtoFileSchema(proto, type_name, proto_paths=proto_paths)


def _prepare(
    data_file: Path,
    desc: Path | None,
    proto: Path | None,
    proto_paths: tuple[str, ...],
    type_name: str | None,
    where_expr: str | None,
    fields: str | None = None,
    explicit_defaults: bool = False,
    output_format: str = "human",  # matches the Click default; count_cmd omits it
) -> _Setup:
    """Validate flags, resolve the schema, and compile the predicate (exit 2 on fault).

    R14 (``--fields`` + ``--explicit-defaults`` mutually exclusive) and R9
    (``--explicit-defaults`` is JSON only) are enforced here up front — before any
    record is read — so they fail cleanly with exit 2 regardless of how many
    records the data file holds (an empty file must not silently no-op R9).
    ``count_cmd`` intentionally omits ``output_format`` (it has no output rows to
    densify): it passes neither flag, so the ``explicit_defaults`` + ``human``
    guard never fires for it regardless of this default.
    """
    if fields is not None and explicit_defaults:
        error_exit("--fields and --explicit-defaults are mutually exclusive")
    if explicit_defaults and output_format == "human":
        error_exit("--explicit-defaults is JSON only; use --format json")
    chosen = [name for name, val in (("--desc", desc), ("--proto", proto)) if val]
    if not chosen:
        error_exit("a schema source is required: --desc or --proto")
    if len(chosen) > 1:
        error_exit(f"--desc and --proto are mutually exclusive (got {', '.join(chosen)})")
    if not type_name:
        error_exit("--type (the fully-qualified message name) is required")

    schema = _build_schema_source(desc, proto, proto_paths, type_name)
    stream_id = data_file.name
    registry = StreamRegistry()
    try:
        registry.register_stream(stream_id, schema)
    except _TYPED_CLI_ERRORS as exc:
        error_exit(str(exc))
    resolved = registry.get(stream_id)
    assert resolved is not None

    predicate: Callable[[Message], bool] | None = None
    if where_expr:
        try:
            predicate = compile_where(where_expr, resolved.message_class.DESCRIPTOR)
        except WhereError as exc:
            error_exit(str(exc))

    selection: CompiledSelection | None = None
    if fields is not None:
        # `is not None` (not truthiness): an empty/whitespace --fields '' must
        # reach compile_fields so it raises the "empty selection" error (exit 2)
        # rather than falling through to a full-record dump.
        try:
            selection = compile_fields(fields, resolved.message_class.DESCRIPTOR)
        except FieldSelectionError as exc:
            error_exit(str(exc))
    return _Setup(registry, stream_id, predicate, selection, explicit_defaults)


class _Run(NamedTuple):
    result: ScanResult
    faults: list[int] | None  # populated only under 'warn' (route)


def _make_result(setup: _Setup, source: Source, on_error: str) -> _Run:
    """Build the ScanResult, wiring a stderr sink + fault tally for 'warn' (route)."""
    if on_error == "warn":
        faults = [0]

        def sink(err: FrameError) -> None:
            faults[0] += 1
            click.echo(
                f"Warning: stream {err.stream_id!r} record {err.record_index} "
                f"(offset {err.offset}): {err.reason}",
                err=True,
            )

        result = scan(
            source,
            setup.registry,
            predicate=setup.predicate,
            on_error="route",
            error_sink=sink,
        )
        return _Run(result, faults)
    result = scan(
        source,
        setup.registry,
        predicate=setup.predicate,
        on_error=_CLI_TO_ENGINE[on_error],
    )
    return _Run(result, None)


def _flatten_view(view: dict[str, object], prefix: str = "") -> list[str]:
    """Flatten a projected dict into ``path: value`` lines (R13, human mode).

    The line format per terminal kind:

    - A **non-empty dict** (either a descended dotted path like ``header.code``
      or a selected whole submessage/map) is flattened recursively to
      dotted-path keys, so the output mirrors the ``--fields`` paths.
    - An **empty dict** renders as ``path: {}`` — a selected-but-empty submessage
      or map stays visible instead of vanishing (it would otherwise contribute no
      lines).
    - A **non-empty list** (a selected repeated terminal) renders as compact JSON
      on one ``path: [..]`` line.
    - An **empty list** renders as ``path: []`` — a selected-but-empty repeated
      field stays visible (same vanishing-terminal fix as the empty dict).
    - A **scalar** leaf renders plainly as ``path: value``.

    Note that a flattened ``header.code`` line and a whole-submessage ``header``
    selection are unambiguous: a path is either descended through or selected
    whole, so the two cannot both occur for the same key in one selection.
    """
    lines: list[str] = []
    for key, value in view.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            if not value:
                # A selected-but-empty submessage/map: keep it visible.
                lines.append(f"{path}: {{}}")
            else:
                # A nested dict (descended dotted path or whole-submessage/map)
                # -> keep flattening to dotted-path keys.
                lines.extend(_flatten_view(value, f"{path}."))
        elif isinstance(value, list):
            # A repeated terminal -> compact JSON (empty list stays visible as []).
            lines.append(f"{path}: {json.dumps(value, separators=(',', ':'))}")
        else:
            lines.append(f"{path}: {value}")
    return lines


def _render(
    record: ScanRecord,
    output_format: str,
    selection: CompiledSelection | None,
    explicit_defaults: bool = False,
) -> str:
    """Render one record; convert ANY render failure to a typed exit-2 (KD-6).

    With ``selection`` (``--fields``): project the message to the selected paths
    (the faithful nested view, KTD1) and render that view — compact JSONL for
    ``--format json``, ``path: value`` lines for ``--format human`` (R13).

    With ``explicit_defaults`` (``--explicit-defaults``, JSON only): render the
    full record dense — no-presence fields filled at their default, presence-
    bearing fields still by presence — in camelCase, a density variant of the
    shipped PR1.5 JSON (R7/R8/R10, KTD4). The JSON-only rule (R9) and mutual
    exclusivity with ``--fields`` (R14) are enforced up front in :func:`_prepare`,
    so by the time a record reaches here ``explicit_defaults`` only ever pairs
    with ``--format json`` and never with a selection.

    Without either: the shipped PR1.5 full-record render.
    """
    message = record.message
    if output_format == "json":
        try:
            if selection is not None:
                view = project(message, selection)
                rendered: str = json.dumps(view, separators=(",", ":"))
            elif explicit_defaults:
                # Dense full record: fill no-presence fields at their default,
                # leave presence-bearing fields by presence. camelCase keys
                # (no preserving_proto_field_name) keep it a density variant of
                # the plain PR1.5 JSON below (R8/R10, KTD4). The fill kwarg is
                # the KTD2 shim, reused — not re-detected.
                rendered = json_format.MessageToJson(
                    message, indent=None, **{no_presence_kwarg(): True}
                )
            else:
                rendered = json_format.MessageToJson(message, indent=None)
        except Exception as exc:  # defensive: render errors are outside the taxonomy
            error_exit(
                f"failed to render record {record.record_index} as JSON: {exc}"
            )
        return rendered
    try:
        if selection is not None:
            view = project(message, selection)
            body = "\n".join(_flatten_view(view))
        else:
            body = text_format.MessageToString(message).rstrip()
    except Exception as exc:
        error_exit(f"failed to render record {record.record_index}: {exc}")
    header = f"# stream={record.stream_id} record={record.record_index}"
    # Preserve PR1.5's (R8) trailing-newline shape for an all-default (empty-body)
    # record: `# stream=...\n`, not a bare header with no newline.
    return f"{header}\n{body}" if body else f"{header}\n"


def _emit_warn_summary(on_error: str, matched: int, run: _Run) -> None:
    # "matched", not "scanned": this counter is the records that passed the
    # predicate and were emitted/counted, NOT the total read from the source
    # (which the engine does not expose). Under --where / head -n the two
    # differ, so calling it "scanned" would misstate the scan volume.
    if on_error == "warn" and run.faults is not None:
        click.echo(f"matched {matched} records, {run.faults[0]} faults", err=True)


def _open_data(path: Path) -> BinaryIO:
    """Open the data file, translating an OS read error to a clean exit-2.

    ``click.Path(exists=True)`` checks existence but not readability, and the
    file can vanish or become unreadable between the check and the open
    (TOCTOU). Those raise ``OSError``, which is not a ``StorageError`` — without
    this guard it would escape as an exit-1 traceback, breaking the 0/2 exit
    contract this layer owns.
    """
    try:
        return open(path, "rb")
    except OSError as exc:
        error_exit(f"cannot read {path}: {exc}")


@main.command(name="scan")
@_common_options
@_format_option
@_fields_option
@_explicit_defaults_option
def scan_cmd(
    data_file: Path,
    desc: Path | None,
    proto: Path | None,
    proto_paths: tuple[str, ...],
    type_name: str | None,
    where_expr: str | None,
    on_error: str,
    output_format: str,
    fields: str | None,
    explicit_defaults: bool,
) -> None:
    """Dump every (matching) record readably — the protoc --decode replacement."""
    setup = _prepare(
        data_file,
        desc,
        proto,
        proto_paths,
        type_name,
        where_expr,
        fields,
        explicit_defaults,
        output_format,
    )
    yielded = 0
    with _open_data(data_file) as handle:
        source = length_delimited(handle, stream_id=setup.stream_id)
        run = _make_result(setup, source, on_error)
        try:
            for record in run.result:
                click.echo(
                    _render(
                        record, output_format, setup.selection, setup.explicit_defaults
                    )
                )
                yielded += 1
        except _TYPED_CLI_ERRORS as exc:
            error_exit(str(exc))
    _emit_warn_summary(on_error, yielded, run)
    sys.exit(0)


@main.command(name="head")
@_common_options
@_format_option
@_fields_option
@_explicit_defaults_option
@click.option(
    "-n",
    "limit",
    type=click.IntRange(min=0),
    default=10,
    help="Maximum number of records to show (default 10).",
)
def head_cmd(
    data_file: Path,
    desc: Path | None,
    proto: Path | None,
    proto_paths: tuple[str, ...],
    type_name: str | None,
    where_expr: str | None,
    on_error: str,
    output_format: str,
    fields: str | None,
    explicit_defaults: bool,
    limit: int,
) -> None:
    """Show the first N (matching) records (default N=10)."""
    setup = _prepare(
        data_file,
        desc,
        proto,
        proto_paths,
        type_name,
        where_expr,
        fields,
        explicit_defaults,
        output_format,
    )
    yielded = 0
    with _open_data(data_file) as handle:
        source = length_delimited(handle, stream_id=setup.stream_id)
        run = _make_result(setup, source, on_error)
        # limit == 0 pulls nothing (and shows nothing); the `with` closes the file.
        if limit > 0:
            try:
                for record in run.result:
                    click.echo(
                        _render(
                            record,
                            output_format,
                            setup.selection,
                            setup.explicit_defaults,
                        )
                    )
                    yielded += 1
                    if yielded >= limit:
                        break
            except _TYPED_CLI_ERRORS as exc:
                error_exit(str(exc))
    _emit_warn_summary(on_error, yielded, run)
    sys.exit(0)


@main.command(name="count")
@_common_options
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    help="Suppress the count; exit 1 if zero matches, 0 otherwise (grep-like).",
)
def count_cmd(
    data_file: Path,
    desc: Path | None,
    proto: Path | None,
    proto_paths: tuple[str, ...],
    type_name: str | None,
    where_expr: str | None,
    on_error: str,
    quiet: bool,
) -> None:
    """Count the (matching) records.

    Bare: prints the count (0 included) and exits 0. With --quiet: prints nothing
    and exits 1 on zero matches, 0 otherwise (grep-like; zero matches is a valid
    result, not an error — that stays exit 2).
    """
    setup = _prepare(data_file, desc, proto, proto_paths, type_name, where_expr)
    matched = 0
    with _open_data(data_file) as handle:
        source = length_delimited(handle, stream_id=setup.stream_id)
        run = _make_result(setup, source, on_error)
        try:
            for _record in run.result:
                matched += 1
        except _TYPED_CLI_ERRORS as exc:
            error_exit(str(exc))
    _emit_warn_summary(on_error, matched, run)
    if quiet:
        sys.exit(0 if matched > 0 else 1)
    click.echo(str(matched))
    sys.exit(0)
