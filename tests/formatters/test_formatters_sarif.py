"""Tests for the built-in SARIF formatters.

Covers the three compat kinds (COMPAT, COMPAT_HISTORY,
COMPAT_BISECT) — DIFF intentionally has no SARIF built-in.

Validates output against the vendored OASIS SARIF 2.1.0 JSON
schema using the ``jsonschema`` library.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from protokit.formatters import (
    FormatterContext,
    FormatterKind,
    get_formatter,
)
from protokit.formatters._sarif_json import (
    BUILTIN_RULE_DESCRIPTIONS,
    SARIF_VERSION,
    severity_to_sarif_level,
)
from protokit.message.model import Diagnostic
from protokit.schema.model import (
    BisectReport,
    CommitDiagnostic,
    CompatibilityLevel,
    CompatibilityReport,
    Direction,
    Finding,
    HistoryEntry,
    HistoryReport,
    Severity,
)


_SARIF_SCHEMA = Path(__file__).parent.parent / "fixtures" / "sarif" / "sarif-2.1.0.json"


@pytest.fixture(scope="module")
def sarif_validator() -> jsonschema.Draft7Validator:
    """Load the vendored OASIS SARIF 2.1.0 JSON schema once."""
    with open(_SARIF_SCHEMA) as f:
        schema = json.load(f)
    return jsonschema.Draft7Validator(schema)


def _validate(validator: jsonschema.Draft7Validator, payload_str: str) -> dict:
    payload = json.loads(payload_str)
    errors = sorted(validator.iter_errors(payload), key=lambda e: e.path)
    assert not errors, "\n".join(
        f"{list(e.path)}: {e.message}" for e in errors
    )
    return payload


def _make_finding(
    *,
    rule_id: str = "field_removed",
    severity: Severity = Severity.SEMANTIC,
    direction: Direction = Direction.BACKWARD,
    path: str = "user.email",
    message: str = "field present in old, absent in new",
) -> Finding:
    from protokit.message.model import FieldPath
    return Finding(
        path=FieldPath.parse(path),
        rule_id=rule_id,
        severity=severity,
        direction=direction,
        message=message,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestSeverityMapping:
    def test_wire_maps_to_error(self) -> None:
        assert severity_to_sarif_level(Severity.WIRE, Direction.BOTH) == "error"

    def test_semantic_maps_to_error(self) -> None:
        assert severity_to_sarif_level(
            Severity.SEMANTIC, Direction.BACKWARD,
        ) == "error"

    def test_policy_maps_to_warning(self) -> None:
        assert severity_to_sarif_level(
            Severity.POLICY, Direction.BOTH,
        ) == "warning"


class TestRuleCatalog:
    def test_all_17_builtin_rules_have_descriptions(self) -> None:
        # Sanity check that the catalog covers every rule_id the
        # built-in checker can emit. If a new rule lands without
        # an entry it falls back to a generic "Custom rule" stub —
        # this test catches that drift.
        expected = {
            "field_removed", "field_added", "field_number_changed",
            "field_type_wire_incompatible", "field_type_semantic_change",
            "field_type_name_changed", "repeated_to_singular",
            "map_to_repeated", "oneof_membership_changed",
            "oneof_field_added", "required_field_added", "options_changed",
            "presence_changed", "enum_value_removed", "enum_value_added",
            "enum_number_reused", "reserved_field_reused",
        }
        assert expected.issubset(BUILTIN_RULE_DESCRIPTIONS.keys())


# ---------------------------------------------------------------------------
# COMPAT
# ---------------------------------------------------------------------------


class TestCompatSarif:
    def test_empty_report_validates(
        self, sarif_validator: jsonschema.Draft7Validator,
    ) -> None:
        report = CompatibilityReport(level=CompatibilityLevel.STRICT)
        fn = get_formatter("sarif", FormatterKind.COMPAT)
        out = fn(report, FormatterContext(subcommand="compat-check"))
        payload = _validate(sarif_validator, out)
        assert payload["version"] == SARIF_VERSION
        assert len(payload["runs"]) == 1
        run = payload["runs"][0]
        assert run["tool"]["driver"]["name"] == "protokit"
        assert run["results"] == []
        assert run["invocations"][0]["executionSuccessful"] is True

    def test_findings_become_results(
        self, sarif_validator: jsonschema.Draft7Validator,
    ) -> None:
        report = CompatibilityReport(
            level=CompatibilityLevel.STRICT,
            findings=(
                _make_finding(rule_id="field_removed", path="user.email"),
                _make_finding(
                    rule_id="field_added", path="user.nickname",
                    message="new field added",
                ),
            ),
        )
        fn = get_formatter("sarif", FormatterKind.COMPAT)
        out = fn(report, FormatterContext(
            subcommand="compat-check",
            target_type="acme.User",
            proto_file="acme/user.proto",
        ))
        payload = _validate(sarif_validator, out)
        run = payload["runs"][0]
        assert len(run["results"]) == 2
        rule_ids = [r["ruleId"] for r in run["results"]]
        assert set(rule_ids) == {"field_removed", "field_added"}
        # Severity → level mapping (SEMANTIC → error).
        for r in run["results"]:
            assert r["level"] == "error"
            assert r["message"]["text"]
            loc = r["locations"][0]
            assert loc["logicalLocations"][0]["fullyQualifiedName"]
            assert loc["physicalLocation"]["artifactLocation"]["uri"] == "acme/user.proto"
        # Catalog declares both rules.
        catalog_ids = {r["id"] for r in run["tool"]["driver"]["rules"]}
        assert catalog_ids == {"field_removed", "field_added"}

    def test_error_diagnostic_flips_execution_successful(
        self, sarif_validator: jsonschema.Draft7Validator,
    ) -> None:
        report = CompatibilityReport(
            level=CompatibilityLevel.STRICT,
            diagnostics=(Diagnostic(
                level="error", path=None, message="plugin crashed",
            ),),
        )
        fn = get_formatter("sarif", FormatterKind.COMPAT)
        out = fn(report, FormatterContext(subcommand="compat-check"))
        payload = _validate(sarif_validator, out)
        run = payload["runs"][0]
        assert run["invocations"][0]["executionSuccessful"] is False
        notes = run["invocations"][0]["toolExecutionNotifications"]
        assert len(notes) == 1
        assert notes[0]["level"] == "error"
        assert notes[0]["message"]["text"] == "plugin crashed"

    def test_warning_diagnostic_in_execution_notifications(
        self, sarif_validator: jsonschema.Draft7Validator,
    ) -> None:
        # R-FF fix: warnings land in toolExecutionNotifications
        # alongside errors (disambiguated by per-entry level).
        # Previously warnings went into
        # toolConfigurationNotifications, which GitHub Code
        # Scanning may suppress as "not a run event".
        report = CompatibilityReport(
            level=CompatibilityLevel.STRICT,
            diagnostics=(Diagnostic(
                level="warning", path=None, message="advisory",
            ),),
        )
        fn = get_formatter("sarif", FormatterKind.COMPAT)
        out = fn(report, FormatterContext(subcommand="compat-check"))
        payload = _validate(sarif_validator, out)
        run = payload["runs"][0]
        # Warnings don't flip success.
        assert run["invocations"][0]["executionSuccessful"] is True
        notes = run["invocations"][0]["toolExecutionNotifications"]
        assert notes[0]["level"] == "warning"
        assert notes[0]["message"]["text"] == "advisory"
        # And toolConfigurationNotifications is no longer present.
        assert "toolConfigurationNotifications" not in run["invocations"][0]

    def test_errors_and_warnings_coexist_in_execution_notifications(
        self, sarif_validator: jsonschema.Draft7Validator,
    ) -> None:
        # Mixed case — both an error and a warning land in the
        # same toolExecutionNotifications array.
        report = CompatibilityReport(
            level=CompatibilityLevel.STRICT,
            diagnostics=(
                Diagnostic(level="error", path=None, message="plugin crashed"),
                Diagnostic(level="warning", path=None, message="advisory"),
            ),
        )
        fn = get_formatter("sarif", FormatterKind.COMPAT)
        out = fn(report, FormatterContext(subcommand="compat-check"))
        payload = _validate(sarif_validator, out)
        invocation = payload["runs"][0]["invocations"][0]
        assert invocation["executionSuccessful"] is False
        notes = invocation["toolExecutionNotifications"]
        levels = [n["level"] for n in notes]
        assert set(levels) == {"error", "warning"}


# ---------------------------------------------------------------------------
# COMPAT_HISTORY
# ---------------------------------------------------------------------------


class TestHistorySarif:
    def test_empty_walk(
        self, sarif_validator: jsonschema.Draft7Validator,
    ) -> None:
        report = HistoryReport(
            range_spec="HEAD~3..HEAD",
            old_sha="aaa", new_sha="bbb", commits_walked=0,
        )
        fn = get_formatter("sarif", FormatterKind.COMPAT_HISTORY)
        out = fn(report, FormatterContext(subcommand="compat-history"))
        payload = _validate(sarif_validator, out)
        run = payload["runs"][0]
        assert run["results"] == []
        # Range metadata in run.properties.
        assert run["properties"]["range_spec"] == "HEAD~3..HEAD"
        assert run["properties"]["commits_walked"] == 0

    def test_per_commit_partial_fingerprints(
        self, sarif_validator: jsonschema.Draft7Validator,
    ) -> None:
        broken = CompatibilityReport(
            level=CompatibilityLevel.STRICT,
            findings=(_make_finding(),),
        )
        report = HistoryReport(
            range_spec="r", old_sha="a", new_sha="b", commits_walked=2,
            entries=[
                HistoryEntry(
                    commit_sha="aaaaaaaaaaaaaaa", parent_sha="x",
                    commit_subject="ok",
                    report=CompatibilityReport(level=CompatibilityLevel.STRICT),
                ),
                HistoryEntry(
                    commit_sha="bbbbbbbbbbbbbbb", parent_sha="aaaaaaaaaaaaaaa",
                    commit_subject="break", report=broken,
                ),
            ],
        )
        fn = get_formatter("sarif", FormatterKind.COMPAT_HISTORY)
        out = fn(report, FormatterContext(
            subcommand="compat-history", target_type="acme.User",
        ))
        payload = _validate(sarif_validator, out)
        run = payload["runs"][0]
        assert len(run["results"]) == 1
        assert run["results"][0]["partialFingerprints"]["commit"] == "bbbbbbbbbbbbbbb"

    def test_aggregated_diagnostics_carry_commit(
        self, sarif_validator: jsonschema.Draft7Validator,
    ) -> None:
        report = HistoryReport(
            range_spec="r", old_sha="a", new_sha="b", commits_walked=1,
            diagnostics=[
                CommitDiagnostic(
                    commit="abc", level="error",
                    path=None, message="boom",
                ),
            ],
        )
        fn = get_formatter("sarif", FormatterKind.COMPAT_HISTORY)
        out = fn(report, FormatterContext(subcommand="compat-history"))
        payload = _validate(sarif_validator, out)
        invocation = payload["runs"][0]["invocations"][0]
        assert invocation["executionSuccessful"] is False
        notif = invocation["toolExecutionNotifications"][0]
        assert notif["properties"]["commit"] == "abc"

    def test_cli_shaped_diagnostics_notify_once(
        self, sarif_validator: jsonschema.Draft7Validator,
    ) -> None:
        # `compat history` builds HistoryReport.diagnostics by copying
        # each entry's own report.diagnostics, so the per-entry and
        # aggregate passes carry the same message for the same commit.
        entry_report = CompatibilityReport(
            level=CompatibilityLevel.STRICT,
            diagnostics=(Diagnostic(
                path=None, message="plugin crashed", level="error",
            ),),
        )
        report = HistoryReport(
            range_spec="r", old_sha="a", new_sha="b", commits_walked=1,
            entries=[HistoryEntry(
                commit_sha="abc", parent_sha="zzz",
                commit_subject="s", report=entry_report,
            )],
            diagnostics=[CommitDiagnostic(
                commit="abc", level="error",
                path=None, message="plugin crashed",
            )],
        )
        fn = get_formatter("sarif", FormatterKind.COMPAT_HISTORY)
        out = fn(report, FormatterContext(subcommand="compat-history"))
        payload = _validate(sarif_validator, out)
        notes = payload["runs"][0]["invocations"][0][
            "toolExecutionNotifications"
        ]
        assert len(notes) == 1, notes
        assert notes[0]["properties"]["commit"] == "abc"

    def test_disjoint_aggregate_diagnostics_are_kept(
        self, sarif_validator: jsonschema.Draft7Validator,
    ) -> None:
        # A hand-built report whose aggregate diagnostics do NOT
        # restate the per-entry ones must keep both — the dedupe drops
        # only exact (level, commit, message) restatements.
        entry_report = CompatibilityReport(
            level=CompatibilityLevel.STRICT,
            diagnostics=(Diagnostic(
                path=None, message="per-entry", level="error",
            ),),
        )
        report = HistoryReport(
            range_spec="r", old_sha="a", new_sha="b", commits_walked=1,
            entries=[HistoryEntry(
                commit_sha="abc", parent_sha="zzz",
                commit_subject="s", report=entry_report,
            )],
            diagnostics=[
                CommitDiagnostic(
                    commit="abc", level="error",
                    path=None, message="aggregate only",
                ),
                # Same text as the per-entry one but a different
                # commit: not a restatement, so it survives.
                CommitDiagnostic(
                    commit="def", level="error",
                    path=None, message="per-entry",
                ),
            ],
        )
        fn = get_formatter("sarif", FormatterKind.COMPAT_HISTORY)
        out = fn(report, FormatterContext(subcommand="compat-history"))
        payload = _validate(sarif_validator, out)
        notes = payload["runs"][0]["invocations"][0][
            "toolExecutionNotifications"
        ]
        assert len(notes) == 3, notes
        assert [n["properties"]["commit"] for n in notes] == [
            "abc", "abc", "def",
        ]


# ---------------------------------------------------------------------------
# COMPAT_BISECT
# ---------------------------------------------------------------------------


class TestBisectSarif:
    def test_no_break(
        self, sarif_validator: jsonschema.Draft7Validator,
    ) -> None:
        report = BisectReport(
            range_spec="A..B", old_sha="a", new_sha="b",
            breaking_commit=None, commits_walked=4,
        )
        fn = get_formatter("sarif", FormatterKind.COMPAT_BISECT)
        out = fn(report, FormatterContext(subcommand="compat-bisect"))
        payload = _validate(sarif_validator, out)
        run = payload["runs"][0]
        assert run["results"] == []
        assert run["properties"]["breaking_commit"] is None

    def test_break_with_findings(
        self, sarif_validator: jsonschema.Draft7Validator,
    ) -> None:
        finding = _make_finding(rule_id="field_removed")
        report = BisectReport(
            range_spec="A..B", old_sha="aaa", new_sha="bbb",
            breaking_commit="bad999", commits_walked=3,
            breaking_findings=(finding,),
        )
        fn = get_formatter("sarif", FormatterKind.COMPAT_BISECT)
        out = fn(report, FormatterContext(subcommand="compat-bisect"))
        payload = _validate(sarif_validator, out)
        run = payload["runs"][0]
        assert len(run["results"]) == 1
        assert run["results"][0]["partialFingerprints"]["commit"] == "bad999"
        assert run["properties"]["breaking_commit"] == "bad999"
        assert run["properties"]["range_spec"] == "A..B"
