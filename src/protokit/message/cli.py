"""Click CLI for ``protokit diff``.

Supports three mutually exclusive flag groups:
  A) Same-schema:  --desc + --message-type
  B) Cross-schema: --left-desc + --right-desc + --left-type + --right-type
  C) .proto:       --proto + --message-type [+ --proto-path]

Input formats: binary (default), --text-format, --json
Output formats: human-readable colored (default), --format json, --quiet
Exit codes: 0 = equal, 1 = different, 2 = error
"""

from __future__ import annotations

import base64
import json
import math
import sys
from pathlib import Path
from typing import Any

import click
from google.protobuf import (
    descriptor_pool,
    json_format,
    message_factory,
    text_format,
)
from google.protobuf.message import DecodeError, Message

from protokit._cli_utils import (
    compile_proto as _compile_proto,
    error_exit as _error,
    load_descriptor_pool as _load_descriptor_pool,
)
from protokit.message.differ import MessageDifferencer
from protokit.message.formatting import format_value as _format_value
from protokit.message.model import ChangeType, Difference, DiffResult, EnumValue, FieldPath


def _get_message_class(pool: descriptor_pool.DescriptorPool, type_name: str) -> type:
    """Look up a message class by fully-qualified name.

    Args:
        pool: The DescriptorPool to search.
        type_name: Fully-qualified message type (e.g. ``"mypackage.MyMessage"``).

    Returns:
        The generated message class for the given type.
    """
    try:
        desc = pool.FindMessageTypeByName(type_name)
    except KeyError:
        _error(f"Message type '{type_name}' not found in descriptor pool.")
    return message_factory.GetMessageClass(desc)


def _parse_message(
    cls: type,
    data: bytes,
    filename: str,
    *,
    use_text_format: bool = False,
    use_json: bool = False,
) -> Message:
    """Parse message data into a Message instance.

    Args:
        cls: The generated message class to instantiate.
        data: Raw bytes to parse (binary, text-format, or JSON).
        filename: Source filename for error messages.
        use_text_format: If True, parse as protobuf text format.
        use_json: If True, parse as JSON-encoded protobuf.

    Returns:
        A populated Message instance.
    """
    msg = cls()
    try:
        if use_text_format:
            text_format.Parse(data.decode("utf-8"), msg)
        elif use_json:
            json_format.Parse(data.decode("utf-8"), msg)
        else:
            msg.ParseFromString(data)
    except (DecodeError, UnicodeDecodeError) as e:
        _error(f"Failed to parse {filename}: {e}")
    except (json_format.ParseError, text_format.ParseError) as e:
        _error(f"Failed to parse {filename}: {e}")
    return msg


# ---------------------------------------------------------------------------
# Flag group validation
# ---------------------------------------------------------------------------


def _validate_flag_groups(
    desc: str | None,
    message_type: str | None,
    left_desc: str | None,
    right_desc: str | None,
    left_type: str | None,
    right_type: str | None,
    proto: str | None,
    proto_path: tuple[str, ...],
) -> str:
    """Validate mutually exclusive flag groups and return the active group.

    Args:
        desc: Path for same-schema descriptor set (group A).
        message_type: Fully-qualified message type name (groups A/C).
        left_desc: Left descriptor set path (group B).
        right_desc: Right descriptor set path (group B).
        left_type: Left message type (group B).
        right_type: Right message type (group B).
        proto: Path to a ``.proto`` file (group C).
        proto_path: Import paths for protoc (group C).

    Returns:
        ``"A"``, ``"B"``, or ``"C"`` indicating which flag group is active.
    """
    group_b = any(x is not None for x in (left_desc, right_desc, left_type, right_type))
    group_c = proto is not None

    # Detect which groups have flags
    active = []
    if desc is not None:
        active.append("A (--desc)")
    if group_b:
        active.append("B (--left-desc/--right-desc)")
    if group_c:
        active.append("C (--proto)")

    if len(active) > 1:
        _error(
            f"Conflicting flag groups: {', '.join(active)}. "
            "Use only one of: (--desc + --message-type), "
            "(--left-desc + --right-desc + --left-type + --right-type), "
            "or (--proto + --message-type)."
        )

    if desc is not None:
        if message_type is None:
            _error("--desc requires --message-type.")
        return "A"

    if group_b:
        missing = []
        if left_desc is None:
            missing.append("--left-desc")
        if right_desc is None:
            missing.append("--right-desc")
        if left_type is None:
            missing.append("--left-type")
        if right_type is None:
            missing.append("--right-type")
        if missing:
            _error(
                f"Cross-schema mode requires all four flags. Missing: {', '.join(missing)}"
            )
        return "B"

    if group_c:
        if message_type is None:
            _error("--proto requires --message-type.")
        return "C"

    _error(
        "No descriptor source specified. Use --desc, --left-desc/--right-desc, or --proto."
    )


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


_CHANGE_SYMBOLS = {
    ChangeType.ADDED: ("+", "green"),
    ChangeType.REMOVED: ("-", "red"),
    ChangeType.MODIFIED: ("~", "yellow"),
    ChangeType.TYPE_CHANGED: ("T", "magenta"),
    ChangeType.FIELD_NUMBER_CHANGED: ("#", "cyan"),
    ChangeType.CARDINALITY_CHANGED: ("C", "blue"),
}


def _format_diff_human(diff: Difference) -> str:
    """Format a single difference for human-readable colored output.

    Args:
        diff: The Difference to format.

    Returns:
        A string with ANSI color codes suitable for terminal display.
    """
    symbol, color = _CHANGE_SYMBOLS[diff.change_type]
    path_str = str(diff.path) if diff.path else "(root)"
    prefix = click.style(f"  {symbol} ", fg=color, bold=True)

    match diff.change_type:
        case ChangeType.ADDED:
            val = _format_value(diff.new_value)
            return f"{prefix}{click.style(path_str, bold=True)}: {click.style(val, fg='green')}"
        case ChangeType.REMOVED:
            val = _format_value(diff.old_value)
            return f"{prefix}{click.style(path_str, bold=True)}: {click.style(val, fg='red')}"
        case ChangeType.MODIFIED:
            old = _format_value(diff.old_value)
            new = _format_value(diff.new_value)
            return (
                f"{prefix}{click.style(path_str, bold=True)}: "
                f"{click.style(old, fg='red')} → {click.style(new, fg='green')}"
            )
        case ChangeType.TYPE_CHANGED:
            return (
                f"{prefix}{click.style(path_str, bold=True)}: "
                f"type {click.style(str(diff.left_type), fg='red')} → "
                f"{click.style(str(diff.right_type), fg='green')}"
            )
        case ChangeType.FIELD_NUMBER_CHANGED:
            return (
                f"{prefix}{click.style(path_str, bold=True)}: "
                f"field# {click.style(str(diff.left_field_number), fg='red')} → "
                f"{click.style(str(diff.right_field_number), fg='green')}"
            )
        case ChangeType.CARDINALITY_CHANGED:
            return (
                f"{prefix}{click.style(path_str, bold=True)}: "
                f"{click.style(str(diff.left_label), fg='red')} → "
                f"{click.style(str(diff.right_label), fg='green')}"
            )
    raise AssertionError(f"Unhandled change type: {diff.change_type}")  # unreachable


def _output_human(result: DiffResult, verbose: bool) -> None:
    """Print human-readable colored diff output to stdout.

    Args:
        result: The DiffResult to display.
        verbose: If True, show warnings even when messages are equal.
    """
    if not result.has_changes():
        click.echo(click.style("Messages are equal.", fg="green"))
        if verbose and result.warnings:
            for w in result.warnings:
                click.echo(click.style(f"  ⚠ {w}", fg="yellow"))
        return

    click.echo(click.style(
        f"Found {len(result)} difference{'s' if len(result) != 1 else ''}:",
        bold=True,
    ))
    click.echo()

    for diff in result:
        click.echo(_format_diff_human(diff))

    if result.warnings:
        click.echo()
        click.echo(click.style("Warnings:", fg="yellow", bold=True))
        for w in result.warnings:
            click.echo(click.style(f"  ⚠ {w}", fg="yellow"))

    if not result.is_complete:
        click.echo()
        click.echo(click.style(
            f"  ⚠ Comparison truncated at max depth. "
            f"{len(result.truncated_paths)} subtree(s) not fully compared.",
            fg="yellow",
        ))


def _serialize_value(val: object) -> Any:
    """Serialize a value for JSON output.

    Args:
        val: The value to serialize (may be None, EnumValue, bytes, or
            any JSON-compatible type).

    Returns:
        A JSON-serializable representation: ``None`` for None, a dict
        for EnumValue, base64 string for bytes, or the value as-is.
    """
    if val is None:
        return None
    if isinstance(val, EnumValue):
        return {"name": val.name, "number": val.number}
    if isinstance(val, bytes):
        return base64.b64encode(val).decode("ascii")
    if isinstance(val, bool):
        return val  # must check before int since bool is a subclass of int
    if isinstance(val, float):
        if math.isnan(val):
            return {"special_float": "NaN"}
        if math.isinf(val):
            return {"special_float": "Infinity" if val > 0 else "-Infinity"}
        return val
    return val


def _output_json(result: DiffResult) -> None:
    """Print JSON-formatted diff output to stdout.

    Args:
        result: The DiffResult to serialize and print.
    """
    diffs = []
    for d in result:
        entry: dict[str, Any] = {
            "path": str(d.path) if d.path else "",
            "change_type": d.change_type.value,
        }

        match d.change_type:
            case ChangeType.ADDED | ChangeType.REMOVED | ChangeType.MODIFIED:
                entry["old_value"] = _serialize_value(d.old_value)
                entry["new_value"] = _serialize_value(d.new_value)
                entry["field_type"] = d.field_type
            case ChangeType.TYPE_CHANGED:
                entry["old_value"] = None
                entry["new_value"] = None
                entry["field_type"] = None
                entry["left_type"] = d.left_type
                entry["right_type"] = d.right_type
            case ChangeType.FIELD_NUMBER_CHANGED:
                entry["old_value"] = None
                entry["new_value"] = None
                entry["field_type"] = d.field_type
                entry["left_field_number"] = d.left_field_number
                entry["right_field_number"] = d.right_field_number
            case ChangeType.CARDINALITY_CHANGED:
                entry["old_value"] = None
                entry["new_value"] = None
                entry["field_type"] = d.field_type
                entry["left_label"] = d.left_label
                entry["right_label"] = d.right_label

        diffs.append(entry)

    warnings = [{"path": w.path, "message": w.message} for w in result.warnings]

    output = {
        "equal": not result.has_changes(),
        "differences": diffs,
        "warnings": warnings,
    }
    click.echo(json.dumps(output, indent=2, default=str))


# ---------------------------------------------------------------------------
# Main CLI command
# ---------------------------------------------------------------------------


@click.command()
@click.argument("left_file", type=click.Path(exists=True))
@click.argument("right_file", type=click.Path(exists=True))
# Group A: same-schema
@click.option("--desc", type=click.Path(exists=True), help="Descriptor set file (same-schema mode).")
@click.option("--message-type", help="Fully-qualified message type name.")
# Group B: cross-schema
@click.option("--left-desc", type=click.Path(exists=True), help="Left descriptor set (cross-schema mode).")
@click.option("--right-desc", type=click.Path(exists=True), help="Right descriptor set (cross-schema mode).")
@click.option("--left-type", help="Left message type (cross-schema mode).")
@click.option("--right-type", help="Right message type (cross-schema mode).")
# Group C: .proto
@click.option("--proto", type=click.Path(exists=True), help=".proto file (requires protoc).")
@click.option("--proto-path", multiple=True, help="Import path for protoc (-I). Repeatable.")
# Input format
@click.option("--text-format", "use_text_format", is_flag=True, help="Parse input as protobuf text format.")
@click.option("--json", "use_json", is_flag=True, help="Parse input as JSON-encoded protobuf.")
# Output format
@click.option("--format", "output_format", type=click.Choice(["human", "json"]), default="human", help="Output format.")
@click.option("--quiet", is_flag=True, help="Suppress output, exit code only.")
@click.option("--verbose", is_flag=True, help="Show warnings even when messages are equal.")
# Diff options
@click.option("--filter", "filter_path", help="Filter diffs by path prefix.")
@click.option("--ignore", multiple=True, help="Ignore field (bare name or dotted path). Repeatable.")
@click.option("--treat-as-map", multiple=True, nargs=2, metavar="FIELD KEY", help="Treat repeated field as map with KEY.")
@click.option("--float-mode", type=click.Choice(["exact", "approximate"]), default="exact", help="Float comparison mode.")
@click.option("--max-depth", type=int, help="Max comparison depth.")
@click.option("--strict-schema", is_flag=True, help="Warn on message type name changes.")
def main(
    left_file: str,
    right_file: str,
    desc: str | None,
    message_type: str | None,
    left_desc: str | None,
    right_desc: str | None,
    left_type: str | None,
    right_type: str | None,
    proto: str | None,
    proto_path: tuple[str, ...],
    use_text_format: bool,
    use_json: bool,
    output_format: str,
    quiet: bool,
    verbose: bool,
    filter_path: str | None,
    ignore: tuple[str, ...],
    treat_as_map: tuple[tuple[str, str], ...],
    float_mode: str,
    max_depth: int | None,
    strict_schema: bool,
) -> None:
    """Compare two protobuf messages and show differences.

    EXIT CODES: 0 = equal, 1 = different, 2 = error.
    """
    if use_text_format and use_json:
        _error("--text-format and --json are mutually exclusive.")

    # Validate flag groups
    group = _validate_flag_groups(
        desc, message_type, left_desc, right_desc, left_type, right_type, proto, proto_path,
    )

    # Resolve descriptor pools and message classes
    if group == "A":
        pool = _load_descriptor_pool(Path(desc))  # type: ignore[arg-type]
        left_cls = _get_message_class(pool, message_type)  # type: ignore[arg-type]
        right_cls = left_cls
    elif group == "B":
        left_pool = _load_descriptor_pool(Path(left_desc))  # type: ignore[arg-type]
        right_pool = _load_descriptor_pool(Path(right_desc))  # type: ignore[arg-type]
        left_cls = _get_message_class(left_pool, left_type)  # type: ignore[arg-type]
        right_cls = _get_message_class(right_pool, right_type)  # type: ignore[arg-type]
    else:  # group C
        pool = _compile_proto(Path(proto), proto_path)  # type: ignore[arg-type]
        left_cls = _get_message_class(pool, message_type)  # type: ignore[arg-type]
        right_cls = left_cls

    # Read and parse input files
    left_data = Path(left_file).read_bytes()
    right_data = Path(right_file).read_bytes()

    left_msg = _parse_message(
        left_cls, left_data, left_file,
        use_text_format=use_text_format, use_json=use_json,
    )
    right_msg = _parse_message(
        right_cls, right_data, right_file,
        use_text_format=use_text_format, use_json=use_json,
    )

    # Configure differencer
    differ = MessageDifferencer()

    if ignore:
        differ.ignore_fields(*ignore)

    for field, key in treat_as_map:
        differ.treat_as_map(field, key=key)

    if float_mode == "approximate":
        from protokit.message.comparators import FloatComparison
        differ.set_float_comparison(FloatComparison.APPROXIMATE)

    if max_depth is not None:
        differ.max_depth = max_depth

    differ.strict_schema = strict_schema

    # Run comparison
    try:
        result = differ.compare(left_msg, right_msg)
    except ValueError as e:
        _error(str(e))

    # Apply filter
    if filter_path:
        result = result.filter(path=filter_path)

    # Output
    if quiet:
        sys.exit(1 if result.has_changes() else 0)

    if output_format == "json":
        _output_json(result)
    else:
        _output_human(result, verbose)

    sys.exit(1 if result.has_changes() else 0)
