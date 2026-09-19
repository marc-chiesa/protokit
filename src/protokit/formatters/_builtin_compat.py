"""Built-in COMPAT formatters: human and json.

Renders :class:`protokit.schema.CompatibilityReport` for the
``check`` and ``ci`` subcommands. The rendering logic was
previously inlined in ``protokit.schema.cli`` as
``_render_human`` / ``_render_json``; it now lives here so the
formatter registry owns it.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Any

import click

from protokit import _trust
from protokit.formatters import _junit_xml as junit
from protokit.formatters import _sarif_json as sarif
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
        each finding, then every reason ``protokit._trust`` gives for
        not trusting the report; trailer shows the verdict in color.
        ``COMPATIBLE`` is printed only when the seam vouches for the
        report: zero findings from a check that broke part-way is
        ``INCOMPLETE``, not a pass (V23). ``INCOMPATIBLE`` needs no
        such consent -- a finding is definitive however the rest of
        the check went.
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

    untrusted = _trust.reasons(report)
    for reason in untrusted:
        lines.append(click.style(f"  ! {reason}", fg="red"))

    if not report.is_compatible:
        verdict = click.style("INCOMPATIBLE", fg="red", bold=True)
    elif untrusted:
        verdict = click.style(
            "INCOMPLETE: no findings, but the check did not finish",
            fg="red", bold=True,
        )
    else:
        verdict = click.style("COMPATIBLE", fg="green", bold=True)
    lines.append("")
    lines.append(verdict)
    return "\n".join(lines)


def compat_json(report: CompatibilityReport, ctx: FormatterContext) -> str:
    """Render a CompatibilityReport as pretty-printed JSON.

    Returns the shape the schema CLI has emitted since Phase 1:
    ``compatible`` (bool), ``level`` (string), ``findings`` (list of
    dicts), ``diagnostics`` (list of dicts), ``summary``
    (severity-bucket counts) — plus, since 0.16.0, ``complete``
    (bool): whether ``protokit._trust`` vouches for the report.
    ``compatible`` is a verdict and needs that consent: zero findings
    from a check that broke is ``"compatible": false, "complete":
    false``, matching the human renderer's ``INCOMPLETE`` (R4).

    Args:
        report: The report to render.
        ctx: Formatter context (unused).

    Returns:
        A JSON string with two-space indentation.
    """
    del ctx
    complete = _trust.is_trustworthy(report)
    payload: dict[str, Any] = {
        "compatible": report.is_compatible and complete,
        "complete": complete,
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


def _reasons_not_shown(report: object, **kwargs: bool) -> tuple[str, ...]:
    """The seam's reasons this format does not already render structurally.

    The JUnit and SARIF renderers turn each error diagnostic into a case of
    its own, carrying the path and commit a flat sentence would lose — so
    they tell the seam that much (``ERROR_DIAGNOSTIC``) and render whatever
    else it knows. Today that is nothing; the point is the day it is not.

    Asking by kind rather than "did I render anything?" is what makes it
    exact: a report that already carries an error diagnostic AND a reason of
    some other kind would, under the older guess, have had the second one
    silently dropped.

    Args:
        report: The report being rendered.
        **kwargs: Passed to ``protokit._trust.signals_other_than``; history's
            renderers set ``only_from_entries=True`` because each entry's
            suite shows that entry's own diagnostics.
    """
    return tuple(
        s.text for s in _trust.signals_other_than(
            report, _trust.ERROR_DIAGNOSTIC, **kwargs,
        )
    )


def _suite_name_for(ctx: FormatterContext) -> str:
    """Build the testsuite name from FormatterContext type fields.

    ``protokit-compat-{type}`` for the same-type case;
    ``protokit-compat-{old}->{new}`` when the user passed
    ``--old-type`` / ``--new-type`` and they differ; falls back
    to ``protokit-compat-unknown`` when no type is available.
    Prevents cross-type comparisons from silently aggregating
    under one suite identifier in CI dashboards.
    """
    if ctx.target_type is not None:
        return f"protokit-compat-{ctx.target_type}"
    old, new = ctx.old_target_type, ctx.new_target_type
    if old is None and new is None:
        return "protokit-compat-unknown"
    if old == new:
        return f"protokit-compat-{old or 'unknown'}"
    return f"protokit-compat-{old or 'unknown'}->{new or 'unknown'}"


def _build_compat_testsuite(
    report: CompatibilityReport, ctx: FormatterContext,
) -> ET.Element:
    """Construct the COMPAT testsuite (used standalone and inside HISTORY).

    Per-finding testcase rendering. Empty-suite fallback emits a
    single passing ``<testcase classname="compat" name="compatible"/>``
    when there are no findings AND no error-level diagnostics —
    avoids CI systems interpreting an empty suite as "no tests
    ran." Warning-only counts as empty for this purpose.
    """
    error_diags = [d for d in report.diagnostics if d.level == "error"]
    warning_diags = [d for d in report.diagnostics if d.level != "error"]
    not_shown = _reasons_not_shown(report)
    findings_count = len(report.findings)
    errors_count = len(error_diags) + len(not_shown)

    has_real_cases = findings_count > 0 or errors_count > 0
    tests_count = findings_count + errors_count if has_real_cases else 1
    failures_count = findings_count

    suite = junit.make_testsuite(
        name=_suite_name_for(ctx),
        tests=tests_count,
        failures=failures_count,
        errors=errors_count,
    )

    for f in report.findings:
        case = junit.make_testcase(
            classname=f.rule_id,
            name=str(f.path) if f.path else "(root)",
        )
        junit.append_failure(
            case,
            message=f.message,
            type_=f"{f.severity.value}/{f.direction.value}",
            body=f.message,
        )
        junit.add_testcase(suite, case)

    for d in error_diags:
        case = junit.make_testcase(
            classname="diagnostic",
            name=d.path or "(global)",
        )
        junit.append_error(case, message=d.message, type_="error", body=d.message)
        junit.add_testcase(suite, case)

    for reason in not_shown:
        case = junit.make_testcase(classname="diagnostic", name="(untrusted)")
        junit.append_error(case, message=reason, type_="error", body=reason)
        junit.add_testcase(suite, case)

    if not has_real_cases:
        # Empty-suite fallback so CI consumers get a clean
        # "compatible" signal instead of a "no tests ran" warning.
        junit.add_testcase(
            suite, junit.make_testcase(classname="compat", name="compatible"),
        )

    if warning_diags:
        junit.append_system_out(
            suite, "\n".join(str(d) for d in warning_diags),
        )
    return suite


def compat_junit(report: CompatibilityReport, ctx: FormatterContext) -> str:
    """Render a CompatibilityReport as JUnit XML.

    Returns a standalone ``<testsuite>`` root (the xsd's
    non-aggregating form) — the aggregating ``<testsuites>``
    wrapper requires ``package``/``id`` attributes on each
    child suite, which only HISTORY can populate. See
    :func:`_build_compat_testsuite` for per-finding semantics
    and the empty-suite fallback.
    """
    return junit.serialize(_build_compat_testsuite(report, ctx))


def _protokit_version() -> str:
    """Best-effort lookup of the installed protokit version for SARIF.

    Thin wrapper around ``protokit._cli_utils._get_protokit_version``;
    kept as a function (not a direct import alias) so the
    ``tool.driver.version`` call site stays readable. Three independent
    copies of the same try/except-PackageNotFoundError block were
    collapsed during a code-review pass.
    """
    from protokit._cli_utils import _get_protokit_version
    return _get_protokit_version()


def compat_sarif(report: CompatibilityReport, ctx: FormatterContext) -> str:
    """Render a CompatibilityReport as SARIF 2.1.0 JSON.

    Single ``run`` containing one ``result`` per finding,
    declaring every fired rule_id in
    ``run.tool.driver.rules``. Diagnostic-level errors land in
    ``invocations[0].toolExecutionNotifications`` and flip
    ``executionSuccessful`` to false; warnings join them in that
    same array, tagged ``level: "warning"``. Optionally pins the
    proto file as ``physicalLocation.artifactLocation.uri``
    when ``ctx.proto_file`` is set.
    """
    errors, warnings = sarif.collect_diagnostics_from_report(report)
    errors.extend((None, reason) for reason in _reasons_not_shown(report))
    findings_with_context = [
        (f, ctx.proto_file, None) for f in report.findings
    ]
    run = sarif.build_run(
        findings_with_context=findings_with_context,
        error_messages=errors,
        warning_messages=warnings,
        protokit_version=_protokit_version(),
    )
    return json.dumps(sarif.build_document(runs=[run]), indent=2)


_register_builtin("human", compat_human, kind=FormatterKind.COMPAT)
_register_builtin("json", compat_json, kind=FormatterKind.COMPAT)
_register_builtin("junit", compat_junit, kind=FormatterKind.COMPAT)
_register_builtin("sarif", compat_sarif, kind=FormatterKind.COMPAT)
