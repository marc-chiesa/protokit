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



#: D6a U9 R9d: wire-format schema version for ``lint_json`` (top-level
#: ``schema_version``) and ``lint_sarif`` (``runs[].properties.lint_schema_version``).
#: Both formatters MUST emit the same string value per the
#: cross-format-enum-string-parity discipline. ``lint_human`` (terminal-
#: rendered text) and ``lint_junit`` (XML; downstream JUnit consumers
#: rely on the standard schema without protokit-specific extensions)
#: deliberately do NOT carry this field.
#:
#: Consumer contract:
#:   - Consumers MUST treat unknown values as forward-compatible
#:     (read what they can, ignore new keys they don't understand).
#:   - Field-absent semantic: protokit output that predates this
#:     constant (no ``schema_version`` key at all) is the implicit
#:     version ``"0.1"`` — i.e., one bump below the first
#:     documented value. Consumers comparing versions should treat
#:     absence as a known-older release, NOT as an error.
#:   - Protokit bumps this version on:
#:       (a) addition of new top-level keys
#:       (b) change in meaning of an existing field
#:       (c) removal of a previously documented field
#:   - **Bump-trigger refinement (closed Literals vs open ladders):**
#:     Adding new string values to an existing enum field has two
#:     consumer-impact regimes that determine whether a bump is
#:     needed:
#:       * **Open severity-string ladders** — for fields like
#:         ``severity`` (``"error"`` / ``"warning"`` / ``"info"``)
#:         where consumers tolerate unknown values gracefully (the
#:         field's role is to be rendered or compared, not switched
#:         on; an unknown value can still be rendered as a string or
#:         compared by ordering), additions DO NOT bump the version.
#:       * **Closed Literal discriminators** — for fields like
#:         ``LintRuntimeWarning.category`` (``"rule_exception"`` /
#:         ``"unloaded_rule"`` / ...) where consumers exhaustively
#:         switch on the value (each case handled with different
#:         logic; an unknown value would fall through to a default
#:         branch the consumer didn't expect), additions DO bump the
#:         version. Every consumer must extend their switch / match
#:         construct to handle the new case.
#:     The discriminating question: can a consumer that doesn't know
#:     about the new value still produce a correct result? Open
#:     ladders: yes. Closed discriminators: no. D6b U5's addition of
#:     ``"severities_unloaded_rule"`` to the ``category`` Literal is
#:     the first closed-Literal addition under this contract; it
#:     bumps schema_version from ``"0.2"`` to ``"0.3"``.
#:   - **Pre-release carve-out**: closed-discriminator value renames
#:     within the SAME unreleased version cycle (i.e., between two
#:     internal units U_N and U_N+1 of the same delivery, both of
#:     which precede the version bump to a user-visible release) do
#:     NOT bump ``_LINT_JSON_SCHEMA_VERSION``. Rationale: the
#:     pre-release surface is internal-only by the version-bump
#:     communication contract (see [[pre-1.0-version-bump-as-
#:     communication-contract-2026-05-14]]); no consumer has stored
#:     state against the intermediate U_N value. The next public
#:     release's CHANGELOG documents the final user-visible
#:     ``violation_kind`` (and any other closed-discriminator) set.
#:     First case under this clause: D6c U2 shipped R8b with
#:     ``violation_kind="package/directory-same-package/empty-mixed"``;
#:     D6c U3 corrected the helper-bug fix to split that arm into
#:     ``/empty-mixed-single`` + ``/empty-mixed-multi`` empirically
#:     against buf v1.69.0. Both U2 and U3 land before the 0.4.0
#:     release (U5 boundary); ``schema_version`` stays ``"0.3"``.
#:     Post-1.0, the same rename WOULD bump per the
#:     value-migrated-vs-value-added distinction in
#:     [[closed-literal-discriminator-bump-trigger-2026-05-17]].
#:   - **D6d 0.5.0 bump**: ``_LINT_JSON_SCHEMA_VERSION`` advances
#:     ``"0.3"`` → ``"0.4"`` because D6d adds a sixth value to the
#:     ``LintRuntimeWarning.category`` closed Literal:
#:     ``"custom_annotation_extension_unresolved"`` (synthetic
#:     ``custom/<suffix>`` rule skipped because its configured
#:     ``option`` is not registered in the compile pool). Consumers
#:     that exhaustively switch on ``category`` (per the mypy-strict
#:     narrowing pattern documented on :class:`LintRuntimeWarning`)
#:     must extend their match construct to handle the new case.
_LINT_JSON_SCHEMA_VERSION: str = "0.4"


def lint_json(report: LintReport, _ctx: FormatterContext) -> str:
    """Render a LintReport as pretty-printed JSON.

    Top-level keys (stable schema):

    - ``schema_version``: wire-format version string (D6a U9 R9d).
      Consumers MUST treat unknown values as forward-compatible.
      See :data:`_LINT_JSON_SCHEMA_VERSION` for the bump contract.
    - ``findings``: list of finding dicts (rule_id, severity,
      location, violation_kind, message, params).
    - ``filtered_count``: int (count of findings dropped by
      ``--min-severity`` filtering).
    - ``runtime_warnings``: list of warning dicts (category,
      rule_id, message, exception_type, descriptor_path). The
      ``rule_id`` field is populated for rule-scoped categories
      (``rule_exception``, ``unloaded_rule``,
      ``severities_unloaded_rule``) and ``null`` for non-rule-scoped
      categories (``min_severity_relaxed``, ``all_files_excluded``).
      See :class:`LintRuntimeWarning` for the full per-category
      field-population contract.
    - ``diagnostics``: list of compile-time diagnostic dicts
      (level, category, message); empty unless ``--proto`` mode
      surfaced backend notices.
    - ``summary``: per-severity counts (errors, warnings, info,
      total) plus filtered_count and runtime_warning_count. Embeds
      what the human-format ``--statistics`` footer would have
      shown, so machine-format consumers don't need ``--statistics``
      and the flag is silently ignored when ``--format=json``.

    Per-finding ``params`` dict contract:

      The ``params`` field carries the rule-specific semantic fields
      used to interpolate the rendered ``message`` text. For
      single-arm rules (the vast majority), ``params`` carries one
      stable key set per rule_id. For **multi-arm rules** (rules with
      dict-shaped ``message_template`` keyed by ``violation_kind``),
      ``params`` carries a per-arm key set discriminated by
      ``violation_kind``. Agent consumers that branch on rule
      behavior should switch on ``violation_kind`` to determine which
      keys are present.

      Current multi-arm rule (one as of D6c U3):

      - ``package/directory-same-package`` (R8b, three arms):

        - ``violation_kind="package/directory-same-package"`` (standard arm,
          2+ declared packages, no packageless files):
          params = ``{file, directory, packages, packageless_present}``.
          ``packages`` is a comma-no-space alphabetic-sorted string
          (e.g., ``"acme.bar,acme.foo"``).
        - ``violation_kind="package/directory-same-package/empty-mixed-single"``
          (1 declared + ≥1 packageless): params = ``{file, directory,
          package, packageless_present}``. ``package`` (singular) is
          the single declared-package value.
        - ``violation_kind="package/directory-same-package/empty-mixed-multi"``
          (2+ declared + ≥1 packageless): params = ``{file, directory,
          packages, packageless_present}``. ``packages`` (plural CSV)
          matches the standard arm's shape.

      Note the ``package`` (singular) vs ``packages`` (plural)
      asymmetry between R8b's empty-mixed-single arm and its other
      two arms — branching on ``violation_kind`` is the
      discriminator. ``packageless_present`` is a symmetric
      ``bool`` field present in all three arms for callers that
      prefer a direct boolean over string-prefix-matching the
      ``violation_kind``.

      ``params`` values are sanitized via ``_safe_for_stderr`` and
      capped at 500 chars per value before serialization. Non-JSON-
      serializable param values (rare; ``str`` and ``bool`` cover
      the current rule set) degrade to ``repr`` via
      ``json.dumps(default=str)`` rather than failing the document.
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
            # Per-finding ``params`` dict (D6c U2 ce:review #8 +
            # agent-native finding). Exposes the rule's semantic
            # introspection fields so agent callers don't have to
            # string-parse the rendered ``message``. For multi-kind
            # rules like R8b, the ``packageless_present``
            # discriminator (a bool) lives here; for any rule whose
            # template renders ``{name}`` style placeholders, the raw
            # source values flow through unchanged so consumers can
            # correlate findings across runs by stable IDs rather
            # than rendered prose. Forward-compatible: consumers may
            # ignore unknown keys; this is a per-finding extension,
            # NOT a top-level schema-version-bumping change per
            # ``_LINT_JSON_SCHEMA_VERSION``'s open-vs-closed contract.
            "params": dict(finding.params),
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
        # D6a U9 R9d wire-format version; see the
        # ``_LINT_JSON_SCHEMA_VERSION`` constant's docstring for the
        # full consumer contract (bump rules + absence semantic).
        "schema_version": _LINT_JSON_SCHEMA_VERSION,
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

    # Compile-time warning diagnostics + engine/CLI runtime warnings
    # share the suite's single ``<system-out>`` body. JUnit XSD permits
    # only one ``<system-out>`` per testsuite, so the two sources are
    # joined into one text block. Runtime warnings use a leading
    # ``[{category}]`` token so consumers can distinguish them from
    # compile diagnostics (which lead with ``{level} [{category}]:``).
    #
    # Per D5 U5 R21a, the cross-formatter render contract: every
    # ``LintRuntimeWarning`` category (``rule_exception``,
    # ``unloaded_rule``, ``severities_unloaded_rule``,
    # ``min_severity_relaxed``, ``all_files_excluded``, plus any
    # future category) renders here regardless of source — closes the
    # D3-era silent-warning regression for ``lint_junit``.
    system_out_lines: list[str] = [
        f"{d.level} [{d.category}]: {d.message}" for d in warning_diags
    ]
    system_out_lines.extend(
        f"[{w.category}] {w.message}" for w in report.runtime_warnings
    )
    if system_out_lines:
        junit.append_system_out(suite, "\n".join(system_out_lines))
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

    Per-result ``properties.params`` (D6c U2 ce:review #8) carries the
    rule's semantic introspection fields (e.g., R8b's
    ``packageless_present`` discriminator + ``directory`` / ``packages``
    / ``package``) so SARIF consumers can programmatically distinguish
    rule-arm sub-types without parsing the rendered ``message.text``.
    The SARIF spec reserves ``properties`` for vendor-extension fields
    of this kind. Renders ``finding.params`` as-is; for any rule that
    stores non-JSON-serializable values, the outer ``json.dumps`` call
    in :func:`lint_sarif` uses ``default=str`` so they degrade to
    repr rather than failing the whole document.
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
        "properties": {
            "params": dict(finding.params),
        },
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
    """Best-effort lookup of the installed protokit version for SARIF.

    Thin wrapper around ``protokit._cli_utils._get_protokit_version``;
    kept as a function (not a direct import alias) so the
    ``tool.driver.version`` call site stays readable. Three independent
    copies of the same try/except-PackageNotFoundError block collapsed
    in D6a U9 ce:review (F11).
    """
    from protokit._cli_utils import _get_protokit_version
    return _get_protokit_version()


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

    Stable schema (within ``runs[0]``):

    - ``properties.lint_schema_version`` (D6a U9 R9d): wire-format
      version string. Prefixed with ``lint_`` to namespace under
      SARIF's reserved ``schema`` property; same value as
      ``lint_json``'s top-level ``schema_version`` per cross-format
      parity. Bag is unconditionally present after U9 — see
      ``_LINT_JSON_SCHEMA_VERSION`` constant for the bump contract.
    - ``properties.runtime_warnings`` (D5 U5 R21a): present only
      when ``report.runtime_warnings`` is non-empty.
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

    # D5 U5 R21a / KTD-1: runtime warnings ride in
    # ``runs[].properties.runtime_warnings`` (SARIF ``propertyBag``
    # is permitted on any object). Each entry has shape::
    #
    #     {
    #         "level": "warning",
    #         "message": {"text": "..."},
    #         "properties": {
    #             "category": "<one of the five categories>",
    #             "subcategory": "runtime",
    #         },
    #     }
    #
    # The ``invocations[0].toolExecutionNotifications`` array
    # (above) remains compile-stage diagnostics only — runtime
    # warnings are intentionally a separate channel so SARIF
    # consumers can filter ``properties.subcategory == "runtime"``
    # without scanning the notifications stream. Per KTD-1, no
    # ``descriptor.id`` is emitted — categorization travels via
    # ``properties.category`` instead. The block is omitted when
    # the report carries no runtime warnings (matches the
    # ``toolExecutionNotifications`` pattern above and keeps the
    # common clean-report SARIF document minimal).
    #
    # ``run.setdefault("properties", {})`` rather than wholesale
    # assignment so a future delivery that adds other run-level
    # properties (e.g., ``tool_version`` / ``policy_hash``) before
    # this block executes does not get silently overwritten. The
    # shared ``run_props`` reference below avoids a second
    # throwaway-dict allocation when the runtime_warnings block
    # already initialized the bag — both keys assign into the same
    # dict.
    run_props: dict[str, Any] = run.setdefault("properties", {})
    if report.runtime_warnings:
        run_props["runtime_warnings"] = [
            {
                "level": "warning",
                "message": {"text": w.message},
                "properties": {
                    "category": w.category,
                    "subcategory": "runtime",
                },
            }
            for w in report.runtime_warnings
        ]

    # D6a U9 R9d: wire-format schema version (key name
    # ``lint_schema_version`` to namespace under SARIF's reserved
    # ``schema`` property). Cross-format parity: same string value
    # as ``lint_json``'s top-level ``schema_version``.
    run_props["lint_schema_version"] = _LINT_JSON_SCHEMA_VERSION

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
