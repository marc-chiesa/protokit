"""Built-in DIFF formatters: human and json.

Renders :class:`protokit.message.DiffResult` for the
``protokit diff`` CLI. The rendering logic was previously
inlined in ``protokit.message.cli`` as ``_format_diff_human`` /
``_serialize_value`` / ``_output_human`` / ``_output_json``;
it now lives here so the formatter registry owns it.

Note on ``--verbose`` semantics: the existing CLI suppresses
diagnostics on the equal-result path unless ``--verbose`` is
set. This formatter always renders diagnostics when present —
the CLI handles the equal-and-not-verbose case by short-
circuiting before invoking the formatter (Unit 5).
"""

from __future__ import annotations

import base64
import json
import math
from typing import Any

import click

from protokit.formatters._registry import (
    FormatterContext,
    FormatterKind,
    _register_builtin,
)
from protokit.message.model import (
    ChangeType,
    Diagnostic,
    Difference,
    DiffResult,
    EnumValue,
)


_CHANGE_SYMBOLS = {
    ChangeType.ADDED: ("+", "green"),
    ChangeType.REMOVED: ("-", "red"),
    ChangeType.MODIFIED: ("~", "yellow"),
    ChangeType.TYPE_CHANGED: ("T", "magenta"),
    ChangeType.FIELD_NUMBER_CHANGED: ("#", "cyan"),
    ChangeType.CARDINALITY_CHANGED: ("C", "blue"),
}


def _format_diff_human(diff: Difference) -> str:
    """Format a single Difference as a colored single-line string.

    Imported lazily to avoid a circular import — the value
    formatter lives in ``protokit.message.formatting`` which
    is itself imported from ``protokit.message`` at package
    load time.
    """
    from protokit.message.formatting import format_value as _format_value

    symbol, color = _CHANGE_SYMBOLS[diff.change_type]
    path_str = str(diff.path) if diff.path else "(root)"
    prefix = click.style(f"  {symbol} ", fg=color, bold=True)

    match diff.change_type:
        case ChangeType.ADDED:
            val = _format_value(diff.new_value)
            return (
                f"{prefix}{click.style(path_str, bold=True)}: "
                f"{click.style(val, fg='green')}"
            )
        case ChangeType.REMOVED:
            val = _format_value(diff.old_value)
            return (
                f"{prefix}{click.style(path_str, bold=True)}: "
                f"{click.style(val, fg='red')}"
            )
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


def _format_diagnostic_line(d: Diagnostic) -> str:
    """Render a Diagnostic as a single colored line."""
    if d.level == "error":
        return click.style(f"  ✗ {d}", fg="red")
    return click.style(f"  ⚠ {d}", fg="yellow")


def diff_human(result: DiffResult, ctx: FormatterContext) -> str:
    """Render a DiffResult as colored human-readable text.

    Always renders diagnostics and truncation notices when
    present. The CLI is responsible for short-circuiting the
    equal-and-not-verbose case before calling this — see
    module docstring.

    Args:
        result: The DiffResult to render.
        ctx: Formatter context (unused).

    Returns:
        A multi-line string. Empty equal results return the
        single line ``"Messages are equal."``; otherwise a
        header, body of diff lines, and trailing diagnostic /
        truncation blocks.
    """
    del ctx
    lines: list[str] = []

    if not result.has_changes():
        lines.append(click.style("Messages are equal.", fg="green"))
        if result.diagnostics:
            for d in result.diagnostics:
                lines.append(_format_diagnostic_line(d))
        return "\n".join(lines)

    plural = "s" if len(result) != 1 else ""
    lines.append(click.style(
        f"Found {len(result)} difference{plural}:", bold=True,
    ))
    lines.append("")
    for diff in result:
        lines.append(_format_diff_human(diff))

    if result.diagnostics:
        lines.append("")
        if result.errors:
            lines.append(click.style("Errors:", fg="red", bold=True))
            for d in result.errors:
                lines.append(click.style(f"  ✗ {d}", fg="red"))
        if result.warnings:
            lines.append(click.style("Warnings:", fg="yellow", bold=True))
            for d in result.warnings:
                lines.append(click.style(f"  ⚠ {d}", fg="yellow"))

    if not result.is_complete:
        lines.append("")
        lines.append(click.style(
            f"  ⚠ Comparison truncated at max depth. "
            f"{len(result.truncated_paths)} subtree(s) not fully compared.",
            fg="yellow",
        ))

    return "\n".join(lines)


def _serialize_value(val: object) -> Any:
    """Serialize a Difference value for JSON output.

    Handles ``None``, ``EnumValue``, ``bytes`` (base64), ``bool``,
    finite floats, and special floats (NaN/Infinity rendered as
    ``{"special_float": "..."}``).
    """
    if val is None:
        return None
    if isinstance(val, EnumValue):
        return {"name": val.name, "number": val.number}
    if isinstance(val, bytes):
        return base64.b64encode(val).decode("ascii")
    if isinstance(val, bool):
        return val  # check before int — bool is a subclass of int
    if isinstance(val, float):
        if math.isnan(val):
            return {"special_float": "NaN"}
        if math.isinf(val):
            return {"special_float": "Infinity" if val > 0 else "-Infinity"}
        return val
    return val


def diff_json(result: DiffResult, ctx: FormatterContext) -> str:
    """Render a DiffResult as pretty-printed JSON.

    Returns the same shape the message CLI has emitted since v1:
    ``equal`` (bool), ``differences`` (list of dicts whose shape
    depends on ``change_type``), ``diagnostics`` (list of dicts).

    Args:
        result: The DiffResult to render.
        ctx: Formatter context (unused).

    Returns:
        A JSON string with two-space indentation. Falls back to
        ``str()`` for objects that aren't directly JSON-serializable
        (matches the legacy ``default=str`` behavior).
    """
    del ctx
    diffs: list[dict[str, Any]] = []
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

    diagnostics = [
        {"level": d.level, "path": d.path, "message": d.message}
        for d in result.diagnostics
    ]
    output = {
        "equal": not result.has_changes(),
        "differences": diffs,
        "diagnostics": diagnostics,
    }
    return json.dumps(output, indent=2, default=str)


_register_builtin("human", diff_human, kind=FormatterKind.DIFF)
_register_builtin("json", diff_json, kind=FormatterKind.DIFF)
