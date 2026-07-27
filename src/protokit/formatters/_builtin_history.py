"""Built-in COMPAT_HISTORY formatters: human and json.

Renders :class:`protokit.schema.HistoryReport` for the ``history``
subcommand. The JSON renderer reuses
``protokit.schema.cli._history_report_to_dict`` so the legacy
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
from protokit.schema.model import (
    Finding,
    HistoryReport,
    history_report_to_dict,
)


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
            path_str = str(f.path) if f.path else "(root)"
            lines.append(
                f"    [{f.severity.value}/{f.direction.value}] "
                f"{path_str}: {f.message} ({f.rule_id})"
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
    return json.dumps(history_report_to_dict(report), indent=2)


def history_junit(report: HistoryReport, ctx: FormatterContext) -> str:
    """Render a HistoryReport as a ``<testsuites>`` aggregating per-commit suites.

    Each ``HistoryEntry`` becomes one ``<testsuite>`` rendered
    by the COMPAT JUnit formatter; suite-level ``package`` is
    the commit subject and ``id`` is the entry index. The
    aggregated xsd requires both attributes.

    Empty walks emit an empty ``<testsuites/>`` document — the
    Apache Ant xsd allows zero ``<testsuite>`` children under
    ``<testsuites>``.
    """
    # Local import — _builtin_compat owns _build_compat_testsuite,
    # and going through the package-level import would create a
    # cycle at module load time.
    from protokit.formatters._builtin_compat import (
        _build_compat_testsuite,
        _suite_name_for,
    )

    # Type-qualified prefix shared with the standalone COMPAT
    # suite name. Combined with the commit short-SHA below it
    # produces a fully disambiguated suite name like
    # ``protokit-compat-acme.User-commit-abcdef123456`` so two
    # concurrent ``history`` runs over the same commit range
    # but different ``--type`` values don't overwrite each
    # other in CI aggregators that dedupe by suite name.
    type_prefix = _suite_name_for(ctx)

    root = ET.Element("testsuites")
    for index, entry in enumerate(report.entries):
        # Build the inner suite via the COMPAT helper for
        # per-finding semantics, then upgrade it to an
        # aggregated testsuite by adding the xsd-required
        # ``package`` and ``id`` attributes.
        entry_ctx = FormatterContext(
            subcommand=ctx.subcommand,
            target_type=ctx.target_type,
            old_target_type=ctx.old_target_type,
            new_target_type=ctx.new_target_type,
            level=ctx.level,
            range_spec=ctx.range_spec,
            old_ref=entry.parent_sha,
            new_ref=entry.commit_sha,
            proto_file=ctx.proto_file,
        )
        suite = _build_compat_testsuite(entry.report, entry_ctx)
        # Overwrites the name make_testsuite already scrubbed, so it
        # has to re-scrub: type_prefix embeds the user-supplied
        # ``--type`` verbatim.
        suite.set("name", junit.xml_safe_text(
            f"{type_prefix}-commit-{entry.commit_sha[:12]}",
        ))
        suite.set("package", junit.xml_safe_text(entry.commit_subject or ""))
        suite.set("id", str(index))
        root.append(suite)
    return junit.serialize(root)


def history_sarif(report: HistoryReport, ctx: FormatterContext) -> str:
    """Render a HistoryReport as SARIF 2.1.0 JSON.

    Single ``run`` aggregating findings across every commit;
    each result carries ``partialFingerprints = {"commit": sha}``
    so consumers can group by commit. Per-commit error and
    warning diagnostics flow into invocation notifications with
    the same commit fingerprint. The aggregated
    ``HistoryReport.diagnostics`` are also surfaced under their
    commit key.
    """
    from protokit.formatters._builtin_compat import _protokit_version

    findings_with_context: list[
        tuple[Finding, str | None, dict[str, str] | None]
    ] = []
    error_messages: list[tuple[str | None, str]] = []
    warning_messages: list[tuple[str | None, str]] = []

    for entry in report.entries:
        commit = entry.commit_sha
        for f in entry.report.findings:
            findings_with_context.append(
                (f, ctx.proto_file, {"commit": commit}),
            )
        per_errs, per_warns = sarif.collect_diagnostics_from_report(
            entry.report, commit=commit,
        )
        error_messages.extend(per_errs)
        warning_messages.extend(per_warns)

    # Aggregate-level diagnostics keep their own commit
    # attribution from the CommitDiagnostic itself.
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
            "commits_walked": report.commits_walked,
        },
        protokit_version=_protokit_version(),
    )
    return json.dumps(sarif.build_document(runs=[run]), indent=2)


_register_builtin("human", history_human, kind=FormatterKind.COMPAT_HISTORY)
_register_builtin("json", history_json, kind=FormatterKind.COMPAT_HISTORY)
_register_builtin("junit", history_junit, kind=FormatterKind.COMPAT_HISTORY)
_register_builtin("sarif", history_sarif, kind=FormatterKind.COMPAT_HISTORY)
