"""Shared helpers for SARIF 2.1.0 JSON emission.

SARIF (Static Analysis Results Interchange Format) is the
OASIS standard format consumed by GitHub Code Scanning,
GitLab security dashboards, and many static analysis tools.
protokit's compat formatters emit SARIF for the COMPAT,
COMPAT_HISTORY, and COMPAT_BISECT kinds; DIFF is excluded
because a message-value diff doesn't fit SARIF's
``Result``/``ruleId``/``level`` model.

This module provides:

- :data:`SARIF_VERSION` and :data:`SARIF_SCHEMA_URL` constants.
- :func:`severity_to_sarif_level` — maps protokit's
  ``Severity`` to SARIF's ``"error" | "warning" | "note"``.
- :data:`BUILTIN_RULE_DESCRIPTIONS` — static catalog of the
  17 built-in rule_ids with short descriptions, so the
  ``run.tool.driver.rules`` array is populated for every
  finding rule that fires.
- :func:`build_run` — assemble a ``run`` object from a
  CompatibilityReport (or list of them, for aggregates).
- :func:`build_document` — wrap one or more runs into the
  top-level SARIF document.
"""

from __future__ import annotations

from typing import Any

from protokit.schema.model import (
    CompatibilityReport,
    Direction,
    Finding,
    Severity,
)

SARIF_VERSION = "2.1.0"
SARIF_SCHEMA_URL = "https://json.schemastore.org/sarif-2.1.0.json"
TOOL_NAME = "protokit"
TOOL_INFORMATION_URI = "https://github.com/marc/protokit"


# Static catalog of built-in rule descriptions. Sourced from
# README.adoc's "Built-in Rules" table. Plugin rules that fire
# without an entry here get a generic fallback description in
# :func:`build_run` — SARIF requires a rule entry for every
# ``ruleId`` referenced in results, but the description text
# can be a stub.
BUILTIN_RULE_DESCRIPTIONS: dict[str, str] = {
    "field_removed": "Field present in old, absent in new.",
    "field_added": "New field added; old consumer sees unknown data.",
    "field_number_changed": "Same name, different field number.",
    "field_type_wire_incompatible": (
        "Scalar type change across wire encoding groups."
    ),
    "field_type_semantic_change": (
        "Type change within a wire group (e.g. string ↔ bytes)."
    ),
    "field_type_name_changed": (
        "Message/enum field points at a renamed type."
    ),
    "repeated_to_singular": "Cardinality flip between singular and repeated.",
    "map_to_repeated": "Map ↔ repeated field conversion.",
    "oneof_membership_changed": (
        "Field moved in/out of a real oneof."
    ),
    "oneof_field_added": (
        "New alternative in a real oneof; "
        "old exhaustive switches break."
    ),
    "required_field_added": (
        "New proto2 required field; old producers cannot satisfy."
    ),
    "options_changed": "Any serialized-options change on a field.",
    "presence_changed": "has_presence semantics differ across schemas.",
    "enum_value_removed": (
        "Enum value deleted; new consumer sees unknown number."
    ),
    "enum_value_added": (
        "Enum value added; old consumer sees unknown number."
    ),
    "enum_number_reused": "Enum number now binds a different name.",
    "reserved_field_reused": "Reserved number/name reused.",
}


def severity_to_sarif_level(severity: Severity, direction: Direction) -> str:
    """Map a protokit Severity/Direction to SARIF's level enum.

    Mapping (per Phase 1.5b plan):
    - WIRE → "error"   (deserialization will break)
    - SEMANTIC → "error" (breaking compat in some direction)
    - POLICY → "warning" (org-rule violation, advisory)
    """
    del direction  # currently mapping is severity-only
    if severity is Severity.WIRE:
        return "error"
    if severity is Severity.SEMANTIC:
        return "error"
    return "warning"


def _result_for_finding(
    finding: Finding,
    *,
    proto_file: str | None,
    partial_fingerprints: dict[str, str] | None,
) -> dict[str, Any]:
    """Build one SARIF ``result`` object from a Finding."""
    result: dict[str, Any] = {
        "ruleId": finding.rule_id,
        "level": severity_to_sarif_level(finding.severity, finding.direction),
        "message": {"text": finding.message},
        "locations": [{
            "logicalLocations": [{
                "fullyQualifiedName": str(finding.path) if finding.path else "(root)",
            }],
        }],
    }
    if proto_file is not None:
        result["locations"][0]["physicalLocation"] = {
            "artifactLocation": {"uri": proto_file},
        }
    if partial_fingerprints:
        result["partialFingerprints"] = dict(partial_fingerprints)
    return result


def _rules_catalog(rule_ids: set[str]) -> list[dict[str, Any]]:
    """Build the ``run.tool.driver.rules`` array.

    Includes every rule_id referenced by results in the run,
    with the description from :data:`BUILTIN_RULE_DESCRIPTIONS`
    when known and a generic stub otherwise. SARIF requires
    every ``result.ruleId`` to have a corresponding rule entry,
    or the ``$ref``-style ``rule.index`` form (we use names).
    """
    out: list[dict[str, Any]] = []
    # Sorted for deterministic output (helps snapshot tests if any).
    for rule_id in sorted(rule_ids):
        description = BUILTIN_RULE_DESCRIPTIONS.get(
            rule_id, f"Custom rule: {rule_id}",
        )
        out.append({
            "id": rule_id,
            "name": rule_id,
            "shortDescription": {"text": description},
        })
    return out


def build_run(
    *,
    findings_with_context: list[
        tuple[Finding, str | None, dict[str, str] | None]
    ],
    error_messages: list[tuple[str | None, str]] | None = None,
    warning_messages: list[tuple[str | None, str]] | None = None,
    properties: dict[str, Any] | None = None,
    protokit_version: str,
) -> dict[str, Any]:
    """Build one SARIF ``run`` object.

    Args:
        findings_with_context: List of
            ``(Finding, proto_file_or_None,
              partial_fingerprints_or_None)`` triples. The
            proto_file becomes ``locations[0].physicalLocation``
            when present; partial_fingerprints (e.g.
            ``{"commit": sha}`` for aggregate kinds) attach to
            the result for downstream grouping.
        error_messages: ``(commit_or_None, message)`` pairs
            recorded as
            ``run.invocations[0].toolExecutionNotifications``.
        warning_messages: similar, recorded as
            ``run.invocations[0].toolConfigurationNotifications``.
        properties: arbitrary key/value bag attached to
            ``run.properties`` (e.g. for bisect's range_spec /
            breaking_commit metadata).
        protokit_version: Version string for ``tool.driver.version``.

    Returns:
        A SARIF run dict suitable for inclusion in
        ``document.runs``.
    """
    rule_ids = {f.rule_id for f, _proto, _fp in findings_with_context}
    rules = _rules_catalog(rule_ids)

    results = [
        _result_for_finding(
            f, proto_file=proto_file, partial_fingerprints=fingerprints,
        )
        for f, proto_file, fingerprints in findings_with_context
    ]

    invocation: dict[str, Any] = {
        "executionSuccessful": not bool(error_messages),
    }
    # All notifications — error AND warning — go into
    # toolExecutionNotifications. GitHub Code Scanning and most
    # other SARIF consumers surface that channel as part of the
    # run; toolConfigurationNotifications (reserved for problems
    # with the tool's configuration rather than events during
    # execution) is often suppressed or de-prioritized. Errors
    # and warnings share the same array, disambiguated by their
    # per-entry ``level`` field.
    notifications: list[dict[str, Any]] = []
    for commit, message in error_messages or []:
        notifications.append({
            "level": "error",
            "message": {"text": message},
            # SARIF notifications don't permit
            # partialFingerprints, but properties is an open
            # bag — attach commit attribution there so consumers
            # can group/filter.
            **({"properties": {"commit": commit}} if commit else {}),
        })
    for commit, message in warning_messages or []:
        notifications.append({
            "level": "warning",
            "message": {"text": message},
            **({"properties": {"commit": commit}} if commit else {}),
        })
    if notifications:
        invocation["toolExecutionNotifications"] = notifications

    run: dict[str, Any] = {
        "tool": {
            "driver": {
                "name": TOOL_NAME,
                "version": protokit_version,
                "informationUri": TOOL_INFORMATION_URI,
                "rules": rules,
            },
        },
        "results": results,
        "invocations": [invocation],
    }
    if properties is not None:
        run["properties"] = dict(properties)
    return run


def build_document(*, runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Wrap one or more runs into the top-level SARIF document."""
    return {
        "version": SARIF_VERSION,
        "$schema": SARIF_SCHEMA_URL,
        "runs": runs,
    }


def collect_diagnostics_from_report(
    report: CompatibilityReport,
    *,
    commit: str | None = None,
) -> tuple[list[tuple[str | None, str]], list[tuple[str | None, str]]]:
    """Split a CompatibilityReport's diagnostics into (errors, warnings).

    Each entry is ``(commit_or_None, message_text)`` so the
    aggregate formatters can preserve commit attribution when
    flattening many reports into one SARIF run.
    """
    errors: list[tuple[str | None, str]] = []
    warnings: list[tuple[str | None, str]] = []
    for d in report.diagnostics:
        target = errors if d.level == "error" else warnings
        target.append((commit, d.message))
    return errors, warnings
