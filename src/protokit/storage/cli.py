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

import sys
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import click
from google.protobuf import descriptor_pb2, json_format, text_format
from google.protobuf.message import DecodeError, Message

from protokit._cli_utils import error_exit
from protokit._pools import DescriptorPoolError
from protokit.storage import (
    FrameError,
    ScanRecord,
    ScanResult,
    Source,
    StorageError,
    StreamRegistry,
    scan,
)
from protokit.storage._where import WhereError, compile_where
from protokit.storage.schema_source import FileDescriptorSetSchema, ProtoFileSchema
from protokit.storage.sources.length_delimited import length_delimited

_TYPED_CLI_ERRORS = (StorageError, DescriptorPoolError)


class _Setup(NamedTuple):
    """The resolved scan setup shared by every subcommand."""

    registry: StreamRegistry
    stream_id: str
    predicate: Callable[[Message], bool] | None


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
) -> _Setup:
    """Validate flags, resolve the schema, and compile the predicate (exit 2 on fault)."""
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
    return _Setup(registry, stream_id, predicate)


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
        on_error=on_error,  # type: ignore[arg-type]  # validated Choice (raise/skip)
    )
    return _Run(result, None)


def _render(record: ScanRecord, output_format: str) -> str:
    """Render one record; convert ANY render failure to a typed exit-2 (KD-6)."""
    message = record.message
    if output_format == "json":
        try:
            rendered: str = json_format.MessageToJson(message, indent=None)
        except Exception as exc:  # defensive: render errors are outside the taxonomy
            error_exit(
                f"failed to render record {record.record_index} as JSON: {exc}"
            )
        return rendered
    try:
        body: str = text_format.MessageToString(message)
    except Exception as exc:
        error_exit(f"failed to render record {record.record_index}: {exc}")
    return f"# stream={record.stream_id} record={record.record_index}\n{body.rstrip()}"


def _emit_warn_summary(on_error: str, scanned: int, run: _Run) -> None:
    if on_error == "warn" and run.faults is not None:
        click.echo(f"scanned {scanned} records, {run.faults[0]} faults", err=True)


@main.command(name="scan")
@_common_options
@_format_option
def scan_cmd(
    data_file: Path,
    desc: Path | None,
    proto: Path | None,
    proto_paths: tuple[str, ...],
    type_name: str | None,
    where_expr: str | None,
    on_error: str,
    output_format: str,
) -> None:
    """Dump every (matching) record readably — the protoc --decode replacement."""
    setup = _prepare(data_file, desc, proto, proto_paths, type_name, where_expr)
    yielded = 0
    with open(data_file, "rb") as handle:
        source = length_delimited(handle, stream_id=setup.stream_id)
        run = _make_result(setup, source, on_error)
        try:
            for record in run.result:
                click.echo(_render(record, output_format))
                yielded += 1
        except _TYPED_CLI_ERRORS as exc:
            error_exit(str(exc))
    _emit_warn_summary(on_error, yielded, run)
    sys.exit(0)


@main.command(name="head")
@_common_options
@_format_option
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
    limit: int,
) -> None:
    """Show the first N (matching) records (default N=10)."""
    setup = _prepare(data_file, desc, proto, proto_paths, type_name, where_expr)
    yielded = 0
    with open(data_file, "rb") as handle:
        source = length_delimited(handle, stream_id=setup.stream_id)
        run = _make_result(setup, source, on_error)
        # limit == 0 pulls nothing (and shows nothing); the `with` closes the file.
        if limit > 0:
            try:
                for record in run.result:
                    click.echo(_render(record, output_format))
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
    with open(data_file, "rb") as handle:
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
