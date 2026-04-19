"""Built-in COMPAT_BISECT formatters: human and json.

Renders :class:`protokit.schema.BisectReport` for the ``bisect``
subcommand. The JSON renderer reuses
``protokit.schema.cli._bisect_report_to_dict`` so the legacy
JSON contract stays in one place.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

from protokit.formatters import _junit_xml as junit
from protokit.formatters import _sarif_json as sarif
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


def bisect_junit(report: BisectReport, ctx: FormatterContext) -> str:
    """Render a BisectReport as a single ``<testsuite>``.

    A ``<properties>`` block carries ``range_spec``, ``old_sha``,
    ``new_sha``, and ``breaking_commit`` for downstream tooling.
    The breaking commit (if any) is one ``<testcase>`` with a
    ``<failure>`` body listing the breaking findings; aggregated
    diagnostics become ``<testcase classname="diagnostic">``
    entries with ``<error>`` bodies.

    Empty walks (no commits in range) emit a single passing
    testcase named ``"no-commits"`` so the suite isn't empty.
    """
    del ctx  # range/sha info comes from the report itself
    failures = 1 if report.breaking_commit is not None else 0
    error_diags = [d for d in report.diagnostics if d.level == "error"]
    warning_diags = [d for d in report.diagnostics if d.level != "error"]
    errors = len(error_diags)

    cases: list[ET.Element] = []
    if report.breaking_commit is not None:
        case = junit.make_testcase(
            classname=report.breaking_commit[:12],
            name="break",
        )
        body = "\n".join(str(f) for f in report.breaking_findings)
        junit.append_failure(
            case,
            message=f"first break in range: {report.breaking_commit}",
            type_="break",
            body=body or report.breaking_commit,
        )
        cases.append(case)

    for d in error_diags:
        case = junit.make_testcase(
            classname=(d.commit[:12] if d.commit else "diagnostic"),
            name=d.path or "(global)",
        )
        junit.append_error(case, message=d.message, type_="error", body=d.message)
        cases.append(case)

    if not cases:
        # Either no break and no error diagnostics, or empty walk.
        cases.append(junit.make_testcase(
            classname="bisect",
            name="no-break" if report.commits_walked > 0 else "no-commits",
        ))

    suite = junit.make_testsuite(
        name="protokit-bisect",
        tests=len(cases),
        failures=failures,
        errors=errors,
    )
    junit.append_properties(suite, {
        "range_spec": report.range_spec,
        "old_sha": report.old_sha,
        "new_sha": report.new_sha,
        "breaking_commit": report.breaking_commit,
        "commits_walked": str(report.commits_walked),
    })
    for case in cases:
        junit.add_testcase(suite, case)
    if warning_diags:
        junit.append_system_out(
            suite, "\n".join(str(d) for d in warning_diags),
        )
    return junit.serialize(suite)


def bisect_sarif(report: BisectReport, ctx: FormatterContext) -> str:
    """Render a BisectReport as SARIF 2.1.0 JSON.

    Single ``run``. Breaking-commit findings become results with
    ``partialFingerprints = {"commit": breaking_commit}``.
    Aggregated diagnostics become invocation notifications,
    each carrying the commit they came from. Bisect range
    metadata (range_spec, old_sha, new_sha, breaking_commit,
    commits_walked) flows into ``run.properties`` for
    downstream consumption.
    """
    from protokit.formatters._builtin_compat import _protokit_version

    findings_with_context: list = []
    if report.breaking_commit is not None:
        for f in report.breaking_findings:
            findings_with_context.append((
                f, ctx.proto_file,
                {"commit": report.breaking_commit},
            ))

    error_messages: list[tuple[str | None, str]] = []
    warning_messages: list[tuple[str | None, str]] = []
    for d in report.diagnostics:
        target = error_messages if d.level == "error" else warning_messages
        target.append((d.commit, d.message))

    run = sarif.build_run(
        findings_with_context=findings_with_context,
        error_messages=error_messages,
        warning_messages=warning_messages,
        properties={
            "range_spec": report.range_spec,
            "old_sha": report.old_sha,
            "new_sha": report.new_sha,
            "breaking_commit": report.breaking_commit,
            "commits_walked": report.commits_walked,
        },
        protokit_version=_protokit_version(),
    )
    return json.dumps(sarif.build_document(runs=[run]), indent=2)


_register_builtin("human", bisect_human, kind=FormatterKind.COMPAT_BISECT)
_register_builtin("json", bisect_json, kind=FormatterKind.COMPAT_BISECT)
_register_builtin("junit", bisect_junit, kind=FormatterKind.COMPAT_BISECT)
_register_builtin("sarif", bisect_sarif, kind=FormatterKind.COMPAT_BISECT)
