"""Example formatter pack — a Slack-summary renderer.

Consumers load this via the CLI's
``--formatter-module examples.custom_formatter`` flag. The
module stays a normal Python file — same trust model as
``--rule-pack``: protokit imports the module and reads its
``FORMATTERS`` attribute, so only load packs from sources you
trust.

Demonstrates the ``register_formatter`` API by way of the
``FORMATTERS = [(name, fn, kind), ...]`` pack convention.
The Slack format is intentionally simple: one block of text
that summarises the compat report in a way you could paste
directly into a webhook payload.
"""

from __future__ import annotations

from protokit.formatters import FormatterContext, FormatterKind
from protokit.schema import CompatibilityReport


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
    target = ctx.target_type or "(unknown type)"
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
