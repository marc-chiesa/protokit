"""Built-in COMPAT_HISTORY formatters: human and json.

Renders :class:`protokit.schema.HistoryReport` for the ``history``
subcommand. The JSON renderer reuses
``protokit.schema.cli._history_report_to_dict`` so the legacy
JSON contract stays in one place.
"""

from __future__ import annotations

import json

from protokit.formatters._registry import (
    FormatterContext,
    FormatterKind,
    _register_builtin,
)
from protokit.schema.model import HistoryReport


def history_human(report: HistoryReport, ctx: FormatterContext) -> str:
    """Render a HistoryReport as plain-text per-commit summary lines.

    Empty walks (no commits in range) render a single
    ``# {range_spec}: no commits touch {proto_file}`` line; the
    proto file path is taken from ``ctx.proto_file`` when
    available, ``"<unknown>"`` otherwise.

    Args:
        report: The history report to render.
        ctx: Formatter context, used for the proto-file label
            on the empty-walk message.

    Returns:
        A multi-line string. Each entry produces one summary
        line plus indented finding lines for any breaks.
    """
    if not report.entries:
        proto_file = ctx.proto_file or "<unknown>"
        return f"# {report.range_spec}: no commits touch {proto_file}"

    lines: list[str] = []
    for entry in report.entries:
        short = entry.commit_sha[:12]
        verdict = "OK" if entry.report.is_compatible else "BROKEN"
        lines.append(
            f"{short} {verdict} ({len(entry.report.findings)} finding(s))"
        )
        for f in entry.report.findings:
            lines.append(
                f"    [{f.severity.value}/{f.direction.value}] "
                f"{f.path}: {f.message} ({f.rule_id})"
            )
    return "\n".join(lines)


def history_json(report: HistoryReport, ctx: FormatterContext) -> str:
    """Render a HistoryReport as the legacy pretty-printed JSON.

    Delegates to ``protokit.schema.cli._history_report_to_dict``
    so the JSON shape stays identical to the pre-formatter-registry
    output. Existing per-key assertions in
    ``tests/schema/test_cli.py`` continue to pin the contract.

    Args:
        report: The history report to render.
        ctx: Formatter context (unused).

    Returns:
        A JSON string with two-space indentation.
    """
    del ctx
    # Local import — avoids a circular dependency at package
    # import time. ``protokit.schema.cli`` imports formatters in
    # Unit 5; this lazy import keeps the dependency one-way.
    from protokit.schema.cli import _history_report_to_dict
    return json.dumps(_history_report_to_dict(report), indent=2)


_register_builtin("human", history_human, kind=FormatterKind.COMPAT_HISTORY)
_register_builtin("json", history_json, kind=FormatterKind.COMPAT_HISTORY)
