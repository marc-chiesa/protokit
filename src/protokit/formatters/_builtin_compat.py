"""Built-in COMPAT formatters: human and json.

Renders :class:`protokit.schema.CompatibilityReport` for the
``check`` and ``ci`` subcommands. The rendering logic was
previously inlined in ``protokit.schema.cli`` as
``_render_human`` / ``_render_json``; it now lives here so the
formatter registry owns it.
"""

from __future__ import annotations

import json
from typing import Any

import click

from protokit.formatters._registry import (
    FormatterContext,
    FormatterKind,
    _register_builtin,
)
from protokit.schema.model import (
    CompatibilityReport,
    Finding,
    Severity,
)


_SEVERITY_COLORS: dict[Severity, str] = {
    Severity.WIRE: "red",
    Severity.SEMANTIC: "yellow",
    Severity.POLICY: "magenta",
}


def _format_finding_human(finding: Finding) -> str:
    """Render one finding as a colored, single-line string.

    Severity is color-coded (red/yellow/magenta) and the
    ``rule_id`` appears in parentheses at the end.
    """
    color = _SEVERITY_COLORS[finding.severity]
    tag = click.style(
        f"[{finding.severity.value}/{finding.direction.value}]",
        fg=color,
        bold=True,
    )
    path_str = str(finding.path) if finding.path else "(root)"
    path_styled = click.style(path_str, bold=True)
    rule = click.style(f"({finding.rule_id})", fg="cyan")
    return f"  {tag} {path_styled}: {finding.message} {rule}"


def compat_human(report: CompatibilityReport, ctx: FormatterContext) -> str:
    """Render a CompatibilityReport as colored human-readable text.

    Args:
        report: The report to render.
        ctx: Formatter context (unused — header has its own
            level/finding-count summary).

    Returns:
        A multi-line string. Header names the profile; body lists
        each finding; trailer shows the verdict (COMPATIBLE or
        INCOMPATIBLE in color).
    """
    del ctx  # unused; level is on the report itself
    lines = []
    header = (
        f"protokit compat — level: {report.level.value}, "
        f"{len(report)} finding(s)"
    )
    lines.append(click.style(header, bold=True))

    for finding in report:
        lines.append(_format_finding_human(finding))

    if report.is_compatible:
        verdict = click.style("COMPATIBLE", fg="green", bold=True)
    else:
        verdict = click.style("INCOMPATIBLE", fg="red", bold=True)
    lines.append("")
    lines.append(verdict)
    return "\n".join(lines)


def compat_json(report: CompatibilityReport, ctx: FormatterContext) -> str:
    """Render a CompatibilityReport as pretty-printed JSON.

    Returns the same shape the schema CLI has emitted since
    Phase 1: ``compatible`` (bool), ``level`` (string),
    ``findings`` (list of dicts), ``diagnostics`` (list of dicts),
    ``summary`` (severity-bucket counts).

    Args:
        report: The report to render.
        ctx: Formatter context (unused).

    Returns:
        A JSON string with two-space indentation.
    """
    del ctx
    payload: dict[str, Any] = {
        "compatible": report.is_compatible,
        "level": report.level.value,
        "findings": [
            {
                "path": str(f.path),
                "rule_id": f.rule_id,
                "severity": f.severity.value,
                "direction": f.direction.value,
                "message": f.message,
            }
            for f in report.findings
        ],
        "diagnostics": [
            {"level": d.level, "path": d.path, "message": d.message}
            for d in report.diagnostics
        ],
        "summary": {
            "wire_breaks": len(report.wire_breaks),
            "semantic_breaks": len(report.semantic_breaks),
            "policy_breaks": len(report.policy_breaks),
            "total": len(report),
        },
    }
    return json.dumps(payload, indent=2)


_register_builtin("human", compat_human, kind=FormatterKind.COMPAT)
_register_builtin("json", compat_json, kind=FormatterKind.COMPAT)
