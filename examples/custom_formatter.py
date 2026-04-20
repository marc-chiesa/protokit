"""Example formatter pack — a Slack-summary renderer.

Consumers load this via the CLI's
``--formatter-module examples.custom_formatter`` flag. The
module stays a normal Python file — same trust model as
``--rule-pack``: protokit imports the module and reads its
``FORMATTERS`` attribute, so only load packs from sources you
trust.

Demonstrates three things pack authors need:

1. The ``FORMATTERS = [(name, fn, kind), ...]`` pack
   convention.
2. The formatter function signature
   ``(report, ctx) -> str`` — pure, no side effects.
3. ``logging`` as the canonical way to emit diagnostic output
   from a pack. The ``logging`` module defaults to stderr,
   which stays off the stdout stream the CLI uses for the
   returned formatted string. Using ``logging`` also avoids
   tripping the CLI's stdout-write guard, which catches
   accidental ``print()`` / ``sys.stdout.write`` calls.
"""

from __future__ import annotations

import logging

from protokit.formatters import (
    FORMATTER_LOG_NAMESPACE,
    FormatterContext,
    FormatterKind,
)
from protokit.schema import CompatibilityReport


# Name sub-loggers under the ``protokit.formatters`` root so
# downstream log-level configuration can address all formatter
# packs uniformly.
logger = logging.getLogger(f"{FORMATTER_LOG_NAMESPACE}.slack_summary")


def slack_summary(report: CompatibilityReport, ctx: FormatterContext) -> str:
    """Render a CompatibilityReport as a Slack-friendly text block.

    Format:

        *protokit compat — TYPE*
        Profile: LEVEL · 5 finding(s) · INCOMPATIBLE
        • [SEVERITY/DIRECTION] path: message (rule_id)
        • ...

    A real Slack pack would wrap this in a Block Kit JSON
    payload; this example stays in plain text so the output is
    obvious in the terminal and copy/paste-friendly.
    """
    logger.info(
        "rendering slack summary for %s (%d findings)",
        ctx.target_type or "cross-type", len(report),
    )
    # ctx.target_type is None on cross-type runs (--old-type X
    # --new-type Y); fall back to old->new so a Slack message
    # still identifies which comparison broke.
    if ctx.target_type is not None:
        target = ctx.target_type
    elif ctx.old_target_type or ctx.new_target_type:
        target = f"{ctx.old_target_type}->{ctx.new_target_type}"
    else:
        target = "(unknown type)"
    verdict = "COMPATIBLE" if report.is_compatible else "INCOMPATIBLE"
    lines = [
        f"*protokit compat — {target}*",
        (
            f"Profile: {report.level.value} · "
            f"{len(report)} finding(s) · {verdict}"
        ),
    ]
    for finding in report:
        path = str(finding.path) if finding.path else "(root)"
        lines.append(
            f"• [{finding.severity.value}/{finding.direction.value}] "
            f"{path}: {finding.message} ({finding.rule_id})"
        )
    if not report.findings:
        lines.append("• (no findings under this profile)")
    return "\n".join(lines)


#: Entries are ``(name, fn, kind)``. The engine registers each
#: via ``register_formatter`` when the pack is loaded. ``kind``
#: tells the registry which report shape ``fn`` consumes; only
#: matching subcommands will accept this name on ``--format``.
FORMATTERS = [
    ("slack", slack_summary, FormatterKind.COMPAT),
]


if __name__ == "__main__":
    # Tiny smoke test — useful to run as
    # ``python -m examples.custom_formatter`` so the pack works
    # standalone before wiring into the CLI.
    from protokit.message.model import FieldPath
    from protokit.schema.model import (
        CompatibilityLevel,
        Direction,
        Finding,
        Severity,
    )

    fake_report = CompatibilityReport(
        level=CompatibilityLevel.STRICT,
        findings=(Finding(
            path=FieldPath.parse("user.email"),
            rule_id="field_removed",
            severity=Severity.SEMANTIC,
            direction=Direction.BACKWARD,
            message="field present in old, absent in new",
        ),),
    )
    print(slack_summary(
        fake_report,
        FormatterContext(subcommand="compat-check", target_type="acme.User"),
    ))
