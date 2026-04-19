"""Built-in COMPAT_BISECT formatters: human and json.

Renders :class:`protokit.schema.BisectReport` for the ``bisect``
subcommand. The JSON renderer reuses
``protokit.schema.cli._bisect_report_to_dict`` so the legacy
JSON contract stays in one place.
"""

from __future__ import annotations

import json

from protokit.formatters._registry import (
    FormatterContext,
    FormatterKind,
    _register_builtin,
)
from protokit.schema.model import BisectReport


def bisect_human(report: BisectReport, ctx: FormatterContext) -> str:
    """Render a BisectReport as plain-text summary lines.

    Three states:

    - **Break found**: emit ``first breaking commit: <sha>`` plus
      one indented line per finding from the breaking commit.
    - **Empty walk**: emit ``# {range}: no commits touch
      {proto_file}``. ``proto_file`` comes from ``ctx`` when
      available.
    - **Clean walk**: emit ``# {range}: no break found across
      N commit(s)``.

    Args:
        report: The bisect report to render.
        ctx: Formatter context, used for the proto-file label.

    Returns:
        A multi-line string.
    """
    if report.breaking_commit is not None:
        lines = [f"first breaking commit: {report.breaking_commit}"]
        for f in report.breaking_findings:
            lines.append(f"  {f}")
        return "\n".join(lines)
    if report.commits_walked == 0:
        proto_file = ctx.proto_file or "<unknown>"
        return f"# {report.range_spec}: no commits touch {proto_file}"
    return (
        f"# {report.range_spec}: no break found across "
        f"{report.commits_walked} commit(s)"
    )


def bisect_json(report: BisectReport, ctx: FormatterContext) -> str:
    """Render a BisectReport as the legacy pretty-printed JSON.

    Delegates to ``protokit.schema.cli._bisect_report_to_dict``
    so the JSON shape stays identical to the pre-formatter-registry
    output.

    Args:
        report: The bisect report to render.
        ctx: Formatter context (unused).

    Returns:
        A JSON string with two-space indentation.
    """
    del ctx
    from protokit.schema.cli import _bisect_report_to_dict
    return json.dumps(_bisect_report_to_dict(report), indent=2)


_register_builtin("human", bisect_human, kind=FormatterKind.COMPAT_BISECT)
_register_builtin("json", bisect_json, kind=FormatterKind.COMPAT_BISECT)
