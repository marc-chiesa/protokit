"""Built-in LINT_REPORT formatters.

D3 ships all four lint formatters: ``human``, ``json``,
``junit``, ``sarif`` (the original D3+D4 split was reversed
during D3 brainstorm pressure-test pass per KD-5 — half-formatter
parity damaged the CI-auditability identity bet, so D3 absorbs
the original D4 scope). All four are registered under the same
``FormatterKind.LINT_REPORT`` discriminator. Unit 1 shipped
``human`` first (commit ``c610dae``); the three machine
formatters land in U4.

Cold-import contract: this module is **NOT** in the eager-load
tuple at ``src/protokit/formatters/__init__.py`` — preserves
D1's cold-import gate (``import protokit.schema`` does not
transitively load ``protokit.schema.lint`` or this module).
``protokit.schema.lint.cli`` imports this module at its module
top, which triggers the formatter registration as a side
effect at ``protokit.cli`` load time (i.e., on every
``protokit ...`` CLI invocation, regardless of which
subcommand fires).

Registration uses the internal ``_register_builtin`` helper
(idempotent under module reload + reserves the ``human`` name in
``_BUILTIN_NAMES``) rather than the public ``register_formatter``
which would raise ``FormatterError`` on the second import.
"""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Mapping
from typing import Any, Literal

if sys.version_info >= (3, 11):
    from typing import assert_never
else:
    from typing_extensions import assert_never

from protokit.formatters import _junit_xml as junit
from protokit.formatters import _sarif_json as sarif
from protokit.formatters._registry import (
    FormatterContext,
    FormatterKind,
    _register_builtin,
)
from protokit.schema.compile import LintCompileDiagnostic
from protokit.schema.lint.model import (
    LintFinding,
    LintReport,
    LintRuleSpec,
    LintSeverity,
)


def _render_message(finding: LintFinding, spec: LintRuleSpec | None) -> str:
    """Interpolate a finding's params into its rule's message template.

    Falls back to a generic ``{rule_id}`` rendering when the
    spec is unavailable (e.g., a finding produced by a rule that
    was unloaded between ``run()`` and rendering, or if the
    engine produced findings without populating ``LintReport.specs``).
    Multi-kind rules (templates as ``dict[str, str]``) are
    looked up by ``finding.violation_kind``.

    Returns the rendered human-readable message string.
    """
    if spec is None:
        return f"{finding.rule_id}"

    template = spec.message_template
    if isinstance(template, dict):
        # Multi-kind rule: look up by violation_kind. Fall back to
        # a generic rendering if the kind is missing from the dict
        # (defensive — rule authors should declare every kind they
        # emit, but a typo shouldn't crash the formatter).
        template_str = template.get(finding.violation_kind, finding.rule_id)
    else:
        template_str = template

    if not template_str:
        return f"{finding.rule_id}"

    # ``str.format(**params)`` is a D3-present trust-boundary: R8
    # lets users load `--rule-pack` modules whose `LintRuleSpec`
    # objects control these templates AND ``LintFinding.params``
    # is typed ``dict[str, Any]`` so a user pack can store
    # objects with custom ``__format__`` methods that can raise
    # arbitrary ``Exception`` subclasses (``OverflowError``,
    # ``ZeroDivisionError``, ``StopIteration``, etc.). The catch
    # is a bare ``except Exception`` rather than a named tuple
    # so that buggy or malicious user-pack templates produce a
    # graceful rule_id fallback rather than crashing the
    # formatter mid-render and dropping every subsequent
    # finding.
    #
    # Threats acknowledged but NOT fully mitigated by this catch:
    #   - Width-specifier OS OOM-kill: ``"{x:>10000000000}"`` may
    #     allocate a large string before any Python exception
    #     fires; the OS OOM-killer terminates the process before
    #     the catch runs. Defense requires a width-cap pre-check
    #     (deferred to D6 holistic plugin-security model).
    #   - Attribute-traversal information disclosure:
    #     ``"{name.__class__.__mro__}"`` returns successfully
    #     and renders into output. No exception fires; the
    #     catch is irrelevant. Defense requires template
    #     validation/sanitization (deferred to D6).
    #
    # TODO(D6): the holistic plugin-security model — whitelist
    # of safe format specs / pre-flight regex rejection of
    # unsafe traversal patterns / safe-eval substitute — lands
    # alongside the `--rule-pack` user-contract design. The
    # broad ``except Exception`` here is defense-in-depth
    # against crash-recovery, not a complete solution.
    try:
        return template_str.format(**finding.params)
    except Exception:
        # Defensive: any Exception from str.format or a user
        # pack's custom __format__ method routes through a
        # graceful rule_id + raw params fallback. Common cases:
        #   - ``KeyError``: missing param key (``"{missing}"``).
        #   - ``IndexError``: positional placeholder out of range.
        #   - ``ValueError``: malformed format spec or excess
        #     nesting (``"{x:{y:{z}}}"``).
        #   - ``AttributeError``: dotted access on a value
        #     lacking the attribute.
        #   - ``TypeError``: format-protocol mismatch or
        #     ``__format__`` returning non-str.
        #   - ``MemoryError``: rare; user-pack ``__format__``
        #     allocates internally and exhausts memory before
        #     OS OOM-kill.
        #   - ``RecursionError``: deeply-recursive user-pack
        #     ``__format__``.
        #   - Any other ``Exception`` subclass from a custom
        #     ``__format__`` implementation in user-pack params.
        # ``BaseException`` (KeyboardInterrupt, SystemExit) is
        # NOT caught — those propagate normally so users can
        # cancel with Ctrl-C and the run_formatter_safely outer
        # SystemExit guard catches sys.exit() bypass attempts.
        # Surface the rule_id + raw params rather than crashing the
        # whole render. Rule-author bugs become visible findings,
        # not lint-tool crashes.
        return f"{finding.rule_id} {finding.params!r}"


def _render_finding_line(finding: LintFinding, spec: LintRuleSpec | None) -> str:
    """Format a single finding as one grep-friendly line.

    Format:
        ``{SEVERITY} {location} [{rule_id}] {message}``

    Example::

        WARNING acme/user.proto:acme.User.bad_field
            [naming/snake-case-fields] Field 'bad_field' is not
            snake_case (AIP-122)
    """
    severity = finding.severity.name  # "INFO" / "WARNING" / "ERROR"
    location = str(finding.location)
    message = _render_message(finding, spec)
    return f"{severity} {location} [{finding.rule_id}] {message}"


def lint_human(report: LintReport, _ctx: FormatterContext) -> str:
    """Render a LintReport as human-readable plaintext.

    Output shape: one finding per line in walk-emission order.
    For clean runs (no findings, no diagnostics), returns an empty
    string — the CLI is responsible for any "no findings" sentinel
    or the ``--statistics`` footer (see Unit 4 in the D3 plan).

    Findings render as::

        SEVERITY location [rule_id] interpolated message
        SEVERITY location [rule_id] interpolated message
        ...

    Compile diagnostics (when present) render before findings::

        diagnostic[CATEGORY]: message
        ...
        SEVERITY location [rule_id] message

    The ``--statistics`` footer is rendered by the CLI callback
    (Unit 4), NOT by this formatter — keeps the formatter pure
    so that machine formats (``lint_json`` / ``lint_junit`` /
    ``lint_sarif``, also shipped in D3 per KD-5 revised) which
    embed counts in their structured payloads can reuse the same
    ``LintReport`` input without footer-stripping logic.

    The function is named ``lint_human`` (not ``_render_human``)
    to match the sibling-pattern parity convention established by
    ``_builtin_diff.diff_human`` / ``_builtin_compat.compat_human`` /
    ``_builtin_history.history_human`` /
    ``_builtin_bisect.bisect_human`` — see
    ``docs/solutions/best-practices/audit-wire-format-before-claiming-sibling-parity-2026-05-03.md``.

    Args:
        report: The lint pass result to render.
        _ctx: Reserved for future per-CLI-flag rendering. Currently
            unused; underscore prefix marks the parameter as
            intentionally ignored without forcing a ``del``.
    """
    lines: list[str] = []

    # Compile diagnostics first (when source-mode compile produced
    # info / warning / error notes). Findings come after so they're
    # the focus when both are present. The loop variable's static
    # type is ``LintCompileDiagnostic`` (not ``Any``-via-getattr) so
    # mypy narrows correctly and any future shape change to the type
    # surfaces as a static error rather than silently masking via
    # defensive fallbacks.
    diag: LintCompileDiagnostic
    for diag in report.diagnostics:
        lines.append(f"diagnostic[{diag.category}]: {diag.message}")

    for finding in report.findings:
        spec = report.specs.get(finding.rule_id)
        lines.append(_render_finding_line(finding, spec))

    return "\n".join(lines)



def lint_json(report: LintReport, _ctx: FormatterContext) -> str:
    """Render a LintReport as pretty-printed JSON.

    Top-level keys (stable schema):

    - ``findings``: list of finding dicts (rule_id, severity,
      location, violation_kind, message).
    - ``filtered_count``: int (count of findings dropped by
      ``--min-severity`` filtering).
    - ``runtime_warnings``: list of warning dicts (category,
      rule_id, message, exception_type, descriptor_path). The
      ``rule_id`` field is ``null`` for the CLI-emitted categories
      (``min_severity_relaxed``, ``all_files_excluded``) and a
      string for engine-emitted categories (``rule_exception``,
      ``unloaded_rule``) — see :class:`LintRuntimeWarning` for the
      contract.
    - ``diagnostics``: list of compile-time diagnostic dicts
      (level, category, message); empty unless ``--proto`` mode
      surfaced backend notices.
    - ``summary``: per-severity counts (errors, warnings, info,
      total) plus filtered_count and runtime_warning_count. Embeds
      what the human-format ``--statistics`` footer would have
      shown, so machine-format consumers don't need ``--statistics``
      and the flag is silently ignored when ``--format=json``.
    """
    del _ctx
    findings_payload: list[dict[str, Any]] = [
        {
            "rule_id": finding.rule_id,
            "severity": finding.severity.value,
            "location": str(finding.location),
            "location_file": finding.location.file,
            "location_kind": (
                type(finding.location).__name__
                .removesuffix("Location")
                .lower()
            ),
            "violation_kind": finding.violation_kind,
            "message": _render_message(
                finding, report.specs.get(finding.rule_id),
            ),
        }
        for finding in report.findings
    ]
    runtime_warnings_payload: list[dict[str, Any]] = [
        {
            "category": w.category,
            "rule_id": w.rule_id,
            "message": w.message,
            "exception_type": w.exception_type,
            "descriptor_path": w.descriptor_path,
        }
        for w in report.runtime_warnings
    ]
    diagnostics_payload: list[dict[str, Any]] = [
        {"level": d.level, "category": d.category, "message": d.message}
        for d in report.diagnostics
    ]
    counts: Counter[LintSeverity] = Counter(
        finding.severity for finding in report.findings
    )
    summary: dict[str, int] = {
        "errors": counts[LintSeverity.ERROR],
        "warnings": counts[LintSeverity.WARNING],
        "info": counts[LintSeverity.INFO],
        "total": len(report.findings),
        "filtered_count": report.filtered_count,
        "runtime_warning_count": len(report.runtime_warnings),
    }
    payload: dict[str, Any] = {
        "findings": findings_payload,
        "filtered_count": report.filtered_count,
        "runtime_warnings": runtime_warnings_payload,
        "diagnostics": diagnostics_payload,
        "summary": summary,
    }
    # default=str preserves findings output when a user-pack rule
    # emits non-JSON-serializable params (e.g., Path, datetime). One
    # bad param renders as repr() rather than suppressing all findings
    # via TypeError → error[lint-formatter-exception]: exit 2.
    return json.dumps(payload, indent=2, default=str)


def _build_lint_testsuite(
    report: LintReport, _ctx: FormatterContext,
) -> ET.Element:
    """Construct the LINT testsuite element.

    Per-finding ``<testcase>`` with ``<failure>`` body. Compile
    error diagnostics become ``<error>`` testcases; non-error
    diagnostics surface in ``<system-out>`` so they don't inflate
    the failure count. Empty-suite fallback emits a single passing
    ``<testcase classname="lint" name="clean"/>`` so CI consumers
    don't read "no tests ran."
    """
    del _ctx
    error_diags = [d for d in report.diagnostics if d.level == "error"]
    warning_diags = [d for d in report.diagnostics if d.level != "error"]
    findings_count = len(report.findings)
    errors_count = len(error_diags)

    has_real_cases = findings_count > 0 or errors_count > 0
    tests_count = findings_count + errors_count if has_real_cases else 1
    failures_count = findings_count

    suite = junit.make_testsuite(
        name="protokit-lint",
        tests=tests_count,
        failures=failures_count,
        errors=errors_count,
    )

    for finding in report.findings:
        spec = report.specs.get(finding.rule_id)
        message = _render_message(finding, spec)
        case = junit.make_testcase(
            classname=finding.rule_id,
            name=str(finding.location),
        )
        junit.append_failure(
            case,
            message=message,
            type_=finding.severity.name.lower(),
            body=message,
        )
        junit.add_testcase(suite, case)

    for diag in error_diags:
        case = junit.make_testcase(
            classname="diagnostic",
            name=diag.category or "(global)",
        )
        junit.append_error(
            case, message=diag.message, type_="error", body=diag.message,
        )
        junit.add_testcase(suite, case)

    if not has_real_cases:
        junit.add_testcase(
            suite, junit.make_testcase(classname="lint", name="clean"),
        )

    if warning_diags:
        junit.append_system_out(
            suite,
            "\n".join(
                f"{d.level} [{d.category}]: {d.message}" for d in warning_diags
            ),
        )
    return suite


def lint_junit(report: LintReport, ctx: FormatterContext) -> str:
    """Render a LintReport as JUnit XML.

    Returns a standalone ``<testsuite>`` root suitable for CI
    test-result panels. Each finding becomes a ``<failure>``
    element under a ``<testcase>`` whose classname is the rule_id
    and whose name is the finding's location.

    Mirrors compat's ``compat_junit`` structurally; intentional
    divergences:

    1. **Testsuite name** is hardcoded ``"protokit-lint"`` instead
       of compat's context-derived ``"protokit-compat-{type}"``.
       Lint has no per-invocation type discriminator.
    2. **`<failure type=>`** uses ``finding.severity.name.lower()``
       (e.g. ``"warning"``) instead of compat's
       ``f"{severity.value}/{direction.value}"`` (e.g.
       ``"WIRE/BACKWARD"``). Lint findings have no direction
       concept; severity alone is the right axis.
    3. **Empty-suite fallback** emits
       ``<testcase classname="lint" name="clean"/>`` instead of
       compat's ``classname="compat" name="compatible"``. Naming
       reflects the subsystem.

    See ``_build_lint_testsuite`` for per-element semantics.
    """
    return junit.serialize(_build_lint_testsuite(report, ctx))


def _lint_severity_to_sarif_level(
    severity: LintSeverity,
) -> Literal["none", "note", "warning", "error"]:
    """Map a LintSeverity to SARIF's level enum.

    SARIF defines four levels: ``"none" | "note" | "warning" | "error"``.
    LintSeverity has three; INFO maps to ``"note"`` (SARIF's
    informational level), WARNING and ERROR map directly.
    """
    if severity is LintSeverity.ERROR:
        return "error"
    if severity is LintSeverity.WARNING:
        return "warning"
    if severity is LintSeverity.INFO:
        return "note"
    assert_never(severity)


def _lint_result_for_finding(
    finding: LintFinding, message: str,
) -> dict[str, Any]:
    """Build one SARIF ``result`` object from a LintFinding.

    Lint findings have no proto-file / partial-fingerprints
    context (the location string is the canonical address), so
    this is a narrower shape than compat's ``_result_for_finding``.
    """
    return {
        "ruleId": finding.rule_id,
        "level": _lint_severity_to_sarif_level(finding.severity),
        "message": {"text": message},
        "locations": [{
            "logicalLocations": [{
                "fullyQualifiedName": str(finding.location),
            }],
        }],
    }


def _lint_rules_catalog(
    rule_ids: set[str], specs: Mapping[str, LintRuleSpec],
) -> list[dict[str, Any]]:
    """Build the ``run.tool.driver.rules`` array for fired rules.

    SARIF requires every ``result.ruleId`` to have a corresponding
    rule entry in ``tool.driver.rules`` (or a ``$ref``-style
    ``rule.index`` form). Use rule_id as both id and name; pull
    the short description from the spec when available, fall back
    to a generic stub when the spec wasn't passed through (e.g.
    a future report shape that omits ``specs``).
    """
    out: list[dict[str, Any]] = []
    for rule_id in sorted(rule_ids):
        spec = specs.get(rule_id)
        if spec is None:
            description = f"Lint rule: {rule_id}"
        elif isinstance(spec.message_template, str):
            description = spec.message_template
        else:
            # Multi-kind rule: dict template. Join all values to
            # surface every kind's prose in the SARIF rule panel.
            description = "; ".join(spec.message_template.values())
        out.append({
            "id": rule_id,
            "name": rule_id,
            "shortDescription": {"text": description},
        })
    return out


def _protokit_version() -> str:
    """Best-effort lookup of the installed protokit version.

    Falls back to ``"0.0.0"`` if the package isn't installed
    (uninstalled checkout). Used in SARIF ``tool.driver.version``.
    Mirrors compat's ``_builtin_compat._protokit_version``.
    """
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version("protokit")
    except PackageNotFoundError:
        return "0.0.0"


def lint_sarif(report: LintReport, _ctx: FormatterContext) -> str:
    """Render a LintReport as SARIF 2.1.0 JSON.

    Single ``run`` containing one ``result`` per finding, with
    every fired rule_id declared in ``run.tool.driver.rules``.
    Compile-time error diagnostics surface in
    ``invocations[0].toolExecutionNotifications`` with level
    ``"error"`` and flip ``executionSuccessful`` to false; non-error
    diagnostics surface in the same array with level ``"warning"``.

    Adopts ``_sarif_json`` constants (``TOOL_NAME``, schema URL,
    ``build_document``) for structural parity with ``compat_sarif``.
    Intentional divergences from compat:

    1. **Severity mapping** uses ``_lint_severity_to_sarif_level``
       (LintSeverity → ``note|warning|error``) instead of compat's
       ``severity_to_sarif_level`` (Severity/Direction → ``error|warning``).
       Different domain enums; lint adds a ``"note"`` mapping for
       INFO that compat doesn't need.
    2. **Rules catalog** draws from ``LintReport.specs`` (live spec
       dict) instead of compat's static ``BUILTIN_RULE_DESCRIPTIONS``
       map. Lint's catalog grows dynamically as new rule packs load.
    3. **No physicalLocation** on ``result.locations`` — lint findings
       carry only logical locations (``str(finding.location)``),
       since the descriptor-set input doesn't carry per-finding
       source-file URIs the way compat's git-mode runs do.
    """
    del _ctx
    error_diags = [d for d in report.diagnostics if d.level == "error"]
    warning_diags = [d for d in report.diagnostics if d.level != "error"]

    results = [
        _lint_result_for_finding(
            finding,
            _render_message(finding, report.specs.get(finding.rule_id)),
        )
        for finding in report.findings
    ]

    rule_ids = {f.rule_id for f in report.findings}
    rules = _lint_rules_catalog(rule_ids, report.specs)

    notifications: list[dict[str, Any]] = []
    for diag in error_diags:
        notifications.append({
            "level": "error",
            "message": {"text": diag.message},
            "properties": {"category": diag.category},
        })
    for diag in warning_diags:
        notifications.append({
            "level": "warning",
            "message": {"text": diag.message},
            "properties": {"category": diag.category},
        })

    invocation: dict[str, Any] = {
        "executionSuccessful": not error_diags,
    }
    if notifications:
        invocation["toolExecutionNotifications"] = notifications

    run: dict[str, Any] = {
        "tool": {
            "driver": {
                "name": sarif.TOOL_NAME,
                "version": _protokit_version(),
                "informationUri": sarif.TOOL_INFORMATION_URI,
                "rules": rules,
            },
        },
        "results": results,
        "invocations": [invocation],
    }

    # default=str: same rationale as lint_json — preserve output when
    # a user-pack finding's params or message contains a
    # non-JSON-serializable object.
    return json.dumps(
        sarif.build_document(runs=[run]), indent=2, default=str,
    )


# Idempotent registration at module import. The lint subcommand
# module imports this module at its top — see module docstring.
_register_builtin(name="human", fn=lint_human, kind=FormatterKind.LINT_REPORT)
_register_builtin(name="json", fn=lint_json, kind=FormatterKind.LINT_REPORT)
_register_builtin(name="junit", fn=lint_junit, kind=FormatterKind.LINT_REPORT)
_register_builtin(name="sarif", fn=lint_sarif, kind=FormatterKind.LINT_REPORT)
