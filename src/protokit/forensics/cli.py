"""Click CLI for ``protokit forensics`` — schema-less single-message analysis.

``forensics match`` ranks candidate ``.proto`` (or ``FileDescriptorSet``) schema
versions against one serialized proto message that carries no co-located schema,
and reports which version most plausibly produced it — with an honest verdict
(``clean_winner`` / ``multiple_clean_matches`` / ``no_clean_match``), never an
assertion that a candidate *is* the schema.

Candidate supply: ``--schema LABEL=PATH`` (repeatable). ``PATH`` is a ``.proto``
source (compiled via the optional backend) or a ``.desc`` / ``FileDescriptorSet``
file. Each candidate resolves to its own isolated descriptor pool. Include dirs
(``-I``) are shared across candidates — for two versions with divergent
same-named imports, keep each version's imports under its own entry directory
(auto-included) rather than on a shared ``-I`` path.

Exit codes: 0 = analysis completed (any verdict, including ``no_clean_match``);
2 = error (bad flags, an oversized message, a candidate that will not compile, or
a message that parses under no candidate). The library never calls ``sys.exit``;
this layer owns it.
"""

from __future__ import annotations

import json
from pathlib import Path

import click
from google.protobuf import descriptor_pb2
from google.protobuf.message import DecodeError

from protokit._cli_utils import error_exit
from protokit._pools import DescriptorPoolError
from protokit.forensics._drift import DriftReport, drift
from protokit.forensics._errors import (
    CandidateSpecError,
    ForensicsError,
    MessageTooLargeError,
)
from protokit.forensics._match import (
    DEFAULT_TIE_MARGIN,
    Candidate,
    CandidateFit,
    MatchReport,
    match,
)
from protokit.storage import StorageError
from protokit.storage.schema_source import FileDescriptorSetSchema, ProtoFileSchema

_TYPED_CLI_ERRORS = (StorageError, DescriptorPoolError)

#: Suffixes read as a compiled ``FileDescriptorSet`` rather than ``.proto`` source.
_FDS_SUFFIXES = frozenset({".desc", ".binpb", ".fds", ".pb"})

_DEFAULT_MAX_MESSAGE_BYTES = 64 * 1024 * 1024  # 64 MiB, mirroring length_delimited

# Wire-format version of the ``--format json`` object.
#
# Bump triggers (dual-clause contract): bump on a new top-level key, a meaning
# change to an existing key, or a key removal. Adding a candidate-row field is a
# bump; widening an enum-like string value (a new ``verdict``) is not, since
# consumers already treat ``verdict`` as an open string. Absence semantic: a
# JSON object with no ``schema_version`` key predates this constant — treat it as
# the implicit ``"0.1"`` shape, not an error.
_MATCH_JSON_SCHEMA_VERSION = "0.1"

# Wire-format version of the ``drift --format json`` object. Same dual-clause
# contract as ``_MATCH_JSON_SCHEMA_VERSION``: bump on a new key / changed meaning
# / removed key; absence means the implicit ``"0.1"`` shape.
_DRIFT_JSON_SCHEMA_VERSION = "0.1"


@click.group()
def main() -> None:
    """Wire-format forensics: identify the schema behind schema-less proto."""


def _parse_schema_spec(spec: str) -> tuple[str, Path]:
    """Split a ``--schema`` value into ``(label, path)``.

    Splits on the first ``=`` so a path containing ``=`` survives. A bare path
    (no ``=``) defaults its label to the file's stem.
    """
    label, sep, raw_path = spec.partition("=")
    if not sep:
        path = Path(spec)
        return path.stem, path
    if not label:
        raise CandidateSpecError(f"--schema spec {spec!r} has an empty label")
    if not raw_path:
        raise CandidateSpecError(f"--schema spec {spec!r} has an empty path")
    return label, Path(raw_path)


def _bounded_read(path: Path, limit: int) -> bytes:
    """Read at most ``limit + 1`` bytes in a single open.

    A single bounded read (not ``stat().st_size`` then ``read_bytes()``) caps the
    work for *any* file — a non-regular file (FIFO, device, process substitution)
    whose ``st_size`` is meaningless, or a regular file that grows between a stat
    and a read — so the size guard is enforcing, not advisory. ``OSError``
    propagates to the caller to translate into a typed error.
    """
    with path.open("rb") as handle:
        return handle.read(limit + 1)


def _build_candidate(
    label: str, path: Path, type_name: str, proto_paths: tuple[str, ...]
) -> Candidate:
    """Build a :class:`Candidate` from one resolved ``(label, path)`` spec."""
    if not path.exists():
        raise CandidateSpecError(f"--schema {label}={path}: file does not exist")
    if path.suffix in _FDS_SUFFIXES:
        try:
            raw = _bounded_read(path, _DEFAULT_MAX_MESSAGE_BYTES)
        except OSError as exc:
            raise CandidateSpecError(
                f"--schema {label}={path}: cannot read ({exc})"
            ) from exc
        if len(raw) > _DEFAULT_MAX_MESSAGE_BYTES:
            raise CandidateSpecError(
                f"--schema {label}={path}: descriptor set exceeds "
                f"{_DEFAULT_MAX_MESSAGE_BYTES} bytes"
            )
        fds = descriptor_pb2.FileDescriptorSet()
        try:
            fds.ParseFromString(raw)
        except DecodeError as exc:
            raise CandidateSpecError(
                f"--schema {label}={path}: not a valid FileDescriptorSet ({exc})"
            ) from exc
        return Candidate(label, FileDescriptorSetSchema(fds, type_name))
    return Candidate(label, ProtoFileSchema(path, type_name, proto_paths=proto_paths))


def _read_message(path: Path, max_message_bytes: int) -> bytes:
    """Read the message, capping the read (KTD10) so untrusted input cannot OOM.

    A single bounded read enforces the cap for non-regular and growing files
    alike; an I/O error becomes a typed :class:`ForensicsError` (exit 2), never a
    bare traceback.
    """
    try:
        data = _bounded_read(path, max_message_bytes)
    except OSError as exc:
        raise ForensicsError(f"cannot read message {path}: {exc}") from exc
    if len(data) > max_message_bytes:
        raise MessageTooLargeError(path, path.stat().st_size, max_message_bytes)
    return data


def _fmt_opt(value: float | None, spec: str, dash: str) -> str:
    """Format an optional numeric cell, or a right-sized dash when it is ``None``."""
    return dash if value is None else format(value, spec)


def _render_human(report: MatchReport) -> str:
    """Build the stdout ranking table for ``--format human``."""
    lines = [
        f"{'rank':<4}  {'label':<20}  {'outcome':<11}  "
        f"{'fraction':>8}  {'cover':>5}  {'resid':>5}"
    ]
    for rank, fit in enumerate(report.ranked, start=1):
        fraction = _fmt_opt(fit.modeled_fraction, "8.3f", "    -   ")
        coverage = _fmt_opt(fit.declared_field_coverage, "5.2f", "   - ")
        residual = _fmt_opt(fit.unmodeled_bytes, "5d", "    -")
        lines.append(
            f"{rank:<4}  {fit.label:<20.20}  {fit.parse_outcome:<11}  "
            f"{fraction}  {coverage}  {residual}"
        )
    return "\n".join(lines)


def _fit_to_json(rank: int, fit: CandidateFit) -> dict[str, object]:
    """One candidate row for ``--format json`` — every fit field is printable."""
    return {
        "rank": rank,
        "label": fit.label,
        "parse_outcome": fit.parse_outcome,
        "modeled_fraction": fit.modeled_fraction,
        "declared_field_coverage": fit.declared_field_coverage,
        "unmodeled_bytes": fit.unmodeled_bytes,
        "present_fields": fit.present_field_count,
        "declared_fields": fit.declared_field_count,
        "detail": fit.detail,
    }


def _render_json(report: MatchReport, message_bytes: int) -> str:
    """Build the stdout JSON object for ``--format json`` (carries schema_version)."""
    payload: dict[str, object] = {
        "schema_version": _MATCH_JSON_SCHEMA_VERSION,
        "message_bytes": message_bytes,
        "verdict": report.verdict,
        "ambiguous_top": report.ambiguous_top,
        "candidates": [
            _fit_to_json(rank, fit) for rank, fit in enumerate(report.ranked, start=1)
        ],
    }
    return json.dumps(payload)


def _verdict_line(report: MatchReport) -> str:
    """A one-line human verdict for stderr."""
    if report.verdict == "no_clean_match":
        return "verdict: no clean match — no candidate fully models the message"
    top = report.ranked[0].label if report.ranked else "?"
    if report.verdict == "multiple_clean_matches":
        return f"verdict: multiple clean matches — {top} and others fit equally well"
    return f"verdict: clean match — {top}"


@main.command(name="match")
@click.argument(
    "message_file", type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
@click.option(
    "--schema",
    "schema_specs",
    multiple=True,
    metavar="LABEL=PATH",
    help="Candidate schema version (repeatable). PATH is a .proto or .desc file.",
)
@click.option(
    "--type",
    "--message-type",
    "type_name",
    help="Fully-qualified message type name (required).",
)
@click.option(
    "--proto-path",
    "-I",
    "proto_paths",
    multiple=True,
    metavar="DIR",
    help="Import path for .proto compilation (-I), shared across candidates. Repeatable.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["human", "json"]),
    default="human",
    help="human (default, ranked table) | json (machine-readable, carries schema_version).",
)
@click.option(
    "--max-residual-bytes",
    type=click.IntRange(min=0),
    default=0,
    help="A candidate is a clean match if it leaves at most this many unmodeled bytes.",
)
@click.option(
    "--max-message-bytes",
    type=click.IntRange(min=1),
    default=_DEFAULT_MAX_MESSAGE_BYTES,
    help="Reject an input message larger than this (default 64 MiB), before reading.",
)
@click.option(
    "--tie-margin",
    type=click.FloatRange(min=0.0),
    default=DEFAULT_TIE_MARGIN,
    help="Top-2 modeled fractions within this epsilon flag an ambiguous pair.",
)
def match_cmd(
    message_file: Path,
    schema_specs: tuple[str, ...],
    type_name: str | None,
    proto_paths: tuple[str, ...],
    output_format: str,
    max_residual_bytes: int,
    max_message_bytes: int,
    tie_margin: float,
) -> None:
    """Rank candidate schema versions against one schema-less MESSAGE_FILE."""
    if not schema_specs:
        error_exit("at least one --schema LABEL=PATH is required")
    if not type_name:
        error_exit("--type is required")

    try:
        message_bytes = _read_message(message_file, max_message_bytes)
        candidates = [
            _build_candidate(*_parse_schema_spec(spec), type_name, proto_paths)
            for spec in schema_specs
        ]
        labels = [candidate.label for candidate in candidates]
        duplicates = sorted({lbl for lbl in labels if labels.count(lbl) > 1})
        if duplicates:
            error_exit(
                f"duplicate --schema label(s): {', '.join(duplicates)}; "
                "use a unique LABEL per candidate"
            )
        report = match(
            message_bytes,
            candidates,
            max_residual_bytes=max_residual_bytes,
            tie_margin=tie_margin,
        )
    except _TYPED_CLI_ERRORS as exc:
        error_exit(str(exc))

    if report.ranked and all(f.parse_outcome == "decode_error" for f in report.ranked):
        error_exit("the message does not parse under any candidate schema")

    if output_format == "json":
        click.echo(_render_json(report, len(message_bytes)))
    else:
        click.echo(_render_human(report))
        click.echo(_verdict_line(report), err=True)


def _render_drift_human(report: DriftReport) -> str:
    """Build the stdout per-field divergence report for ``--format human``."""
    if not report.divergences:
        return (
            f"{report.observed_field_count} fields observed — "
            "no divergences from the schema"
        )
    header = (
        f"{report.observed_field_count} fields observed, "
        f"{len(report.divergences)} divergence(s):"
    )
    lines = [header]
    lines.extend(
        f"  field {d.field_number}: {d.kind} — {d.detail}" for d in report.divergences
    )
    return "\n".join(lines)


def _render_drift_json(report: DriftReport) -> str:
    """Build the stdout JSON object for ``drift --format json``."""
    payload: dict[str, object] = {
        "schema_version": _DRIFT_JSON_SCHEMA_VERSION,
        "observed_fields": report.observed_field_count,
        "divergences": [
            {"field_number": d.field_number, "kind": d.kind, "detail": d.detail}
            for d in report.divergences
        ],
    }
    return json.dumps(payload)


@main.command(name="drift")
@click.argument(
    "message_file", type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
@click.option(
    "--schema",
    "schema_spec",
    metavar="[LABEL=]PATH",
    help="Candidate schema to reconcile against (.proto or .desc).",
)
@click.option(
    "--type",
    "--message-type",
    "type_name",
    help="Fully-qualified message type name (required).",
)
@click.option(
    "--proto-path",
    "-I",
    "proto_paths",
    multiple=True,
    metavar="DIR",
    help="Import path for .proto compilation (-I). Repeatable.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["human", "json"]),
    default="human",
    help="human (default) | json (machine-readable, carries schema_version).",
)
@click.option(
    "--max-message-bytes",
    type=click.IntRange(min=1),
    default=_DEFAULT_MAX_MESSAGE_BYTES,
    help="Reject an input message larger than this (default 64 MiB), before reading.",
)
def drift_cmd(
    message_file: Path,
    schema_spec: str | None,
    type_name: str | None,
    proto_paths: tuple[str, ...],
    output_format: str,
    max_message_bytes: int,
) -> None:
    """Report how one schema-less MESSAGE_FILE diverges from one candidate schema."""
    if not schema_spec:
        error_exit("--schema [LABEL=]PATH is required")
    if not type_name:
        error_exit("--type is required")

    try:
        message_bytes = _read_message(message_file, max_message_bytes)
        label, path = _parse_schema_spec(schema_spec)
        candidate = _build_candidate(label, path, type_name, proto_paths)
        report = drift(message_bytes, candidate.source)
    except _TYPED_CLI_ERRORS as exc:
        error_exit(str(exc))

    if output_format == "json":
        click.echo(_render_drift_json(report))
    else:
        click.echo(_render_drift_human(report))
        summary = (
            "drift: consistent with the schema"
            if not report.divergences
            else f"drift: {len(report.divergences)} divergence(s)"
        )
        click.echo(summary, err=True)
