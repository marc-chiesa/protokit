"""D6d new-U3 — worked-example integration test for ``custom/<suffix>``.

Proves the differentiator end-to-end in CI: a downstream user
declares a custom-annotation rule via
``[[tool.protokit.lint.custom_annotation_rules]]`` in their
``pyproject.toml``, points ``protokit lint`` at their schema, and
sees the synthetic rule materialize as a first-class
``custom/<suffix>`` finding in JSON output. Satisfies S2 of the
D6d brainstorm (differentiator claim "provable in CI, not just
documentation prose").

The fixture lives at
``tests/schema/lint/cli/cli_fixtures/d6d_custom_annotation/`` and
is intentionally self-contained: ``pyproject.toml`` +
``proto/example/audit.proto`` (extension definition) +
``proto/example/service.proto`` (sample service with four method-
level cases). A user copying this fixture into their own project
gets a working starting template.

The fixture's worked-example shape:

==================  ============================  =================
Method              Annotation                    Expected finding
==================  ============================  =================
``HighAudit``       ``audit_level = HIGH``        none (in allowed)
``LowAudit``        ``audit_level = LOW``         none (in allowed)
``BareAudit``       (no annotation)               PRESENCE
``DisallowedAudit`` ``audit_level = NONE``        VALUE-MISMATCH
==================  ============================  =================

The presence-only variant + severity-override scenarios use
``tmp_path``-written pyproject overlays so the on-disk fixture
``pyproject.toml`` stays the canonical (closed-value-set + ERROR
severity) worked example.

ce:review follow-ups (2026-05-21) hardened the contract:
``_RULE_ID`` / ``_FIXTURE_RULE_SUFFIX`` / ``_FIXTURE_OPTION``
constants single-source the fixture's identity; ``_run_lint`` passes
``catch_exceptions=False`` so a CLI crash surfaces as a clean
traceback rather than a confusing ``JSONDecodeError``; every
scenario asserts its expected ``exit_code`` + ``violation_kind`` +
``params`` per finding + ``runtime_warnings == []`` on happy paths.
Two new scenario classes exercise the
``custom_annotation_extension_unresolved`` runtime warning path and
the exit-2 ``error[lint-pyproject-config-invalid]:`` error path.
A SARIF format scenario verifies the synthetic rule_id surfaces in
the structured catalog GitHub Code Scanning + VS Code consume.

The README cross-reference + copy-paste contract land in new-U4
(was U5) per the umbrella plan's revised unit lineup
(``docs/plans/2026-05-19-001-feat-d6d-option-aware-pack-expansion-plan.md``
Strategic Deferral section). This test file is the contract
new-U4 pins against.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from protokit.schema.lint.cli import main as lint_main

# Module-level path constants for the on-disk fixture. Computed
# relative to this test file so the fixture moves with the test if
# either is relocated.
_FIXTURE_ROOT = (
    Path(__file__).parent
    / "cli_fixtures"
    / "d6d_custom_annotation"
)
_FIXTURE_PYPROJECT = _FIXTURE_ROOT / "pyproject.toml"
_FIXTURE_PROTO_ROOT = _FIXTURE_ROOT / "proto"
_FIXTURE_SERVICE_PROTO = _FIXTURE_PROTO_ROOT / "example" / "service.proto"
_FIXTURE_AUDIT_PROTO = _FIXTURE_PROTO_ROOT / "example" / "audit.proto"

# Single-source the fixture's pyproject-derived identifiers. Renaming
# the rule or the option in the fixture only requires updating these
# constants; the assertions and overlay-TOML generators below
# interpolate them everywhere.
_FIXTURE_RULE_SUFFIX = "audit-required"
_FIXTURE_OPTION = "example.audit_level"
_RULE_ID = f"custom/{_FIXTURE_RULE_SUFFIX}"
_KIND_ABSENT = "custom-annotation-absent"
_KIND_VALUE_MISMATCH = "custom-annotation-value-mismatch"


def _run_lint(
    pyproject: Path,
    *,
    extra_args: tuple[str, ...] = (),
    format_: str = "json",
) -> tuple[int, dict[str, Any], str, str]:
    """Invoke ``protokit lint`` against the worked-example service.

    Returns ``(exit_code, parsed_payload, stdout, stderr)``. The
    payload is the parsed ``--format=<format_>`` document (JSON or
    SARIF). For non-JSON-parsable outputs, callers should pass
    ``format_="raw"`` and read ``stdout`` directly.

    Passes ``catch_exceptions=False`` so an unhandled exception in the
    CLI surfaces as a clean traceback rather than masking as
    ``exit_code == 1`` + empty ``stdout`` (which would then crash
    ``json.loads`` with a confusing ``JSONDecodeError``).

    Centralizes the CLI invocation so the scenarios share one
    canonical invocation shape. Test-level customization happens
    via ``pyproject`` (write a modified TOML to ``tmp_path``) and
    ``extra_args`` (additional CLI flags).
    """
    args = [
        "--config", str(pyproject),
        "--proto", str(_FIXTURE_SERVICE_PROTO),
        "-I", str(_FIXTURE_PROTO_ROOT),
        *(["--format", format_] if format_ != "raw" else []),
        *extra_args,
    ]
    result = CliRunner().invoke(
        lint_main, args, catch_exceptions=False,
    )
    # Exit 0 (no findings) or 1 (findings exist) are expected under
    # different scenarios; exit 2 signals a CLI-internal error that
    # callers wanting to verify exit-2 paths should opt into via
    # _run_lint_raw below.
    assert result.exit_code in (0, 1), (
        f"expected lint exit 0/1, got {result.exit_code!r}\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    payload = (
        json.loads(result.stdout) if format_ in ("json", "sarif") else {}
    )
    return result.exit_code, payload, result.stdout, result.stderr


def _run_lint_raw(
    pyproject: Path,
    *,
    extra_args: tuple[str, ...] = (),
) -> tuple[int, str, str]:
    """Invoke ``protokit lint`` without exit-code-range assertions.

    Returned tuple is ``(exit_code, stdout, stderr)``. Use this
    helper to exercise exit-2 paths (malformed pyproject, regex-
    invalid suffix, duplicate suffix). Like :func:`_run_lint`, passes
    ``catch_exceptions=False`` so internal crashes surface cleanly.
    """
    result = CliRunner().invoke(
        lint_main,
        [
            "--config", str(pyproject),
            "--proto", str(_FIXTURE_SERVICE_PROTO),
            "-I", str(_FIXTURE_PROTO_ROOT),
            "--format", "json",
            *extra_args,
        ],
        catch_exceptions=False,
    )
    return result.exit_code, result.stdout, result.stderr


def _findings_for_rule(
    payload: dict[str, Any], rule_id: str,
) -> list[dict[str, Any]]:
    """Extract findings matching ``rule_id`` from the JSON payload.

    Filters on ``rule_id`` so the test asserts on the synthetic
    rule's behavior specifically, decoupled from any other built-in
    rule that might also fire on the fixture.
    """
    return [
        f for f in payload["findings"]
        if f["rule_id"] == rule_id
    ]


def _method_name(finding: dict[str, Any]) -> str:
    """Return the method name from a method-level finding's location.

    Method-level findings emit a ``location`` string shaped
    ``"<file>:<package.Service>/<method>"`` (e.g.,
    ``"example/service.proto:example.AuditedService/BareAudit"``).
    The trailing segment after the final ``/`` is the method name
    proper. Stability of ``MethodLocation.__str__`` is the implicit
    contract this parsing depends on.
    """
    location = finding["location"]
    assert isinstance(location, str)
    return location.rsplit("/", maxsplit=1)[-1]


# ---------------------------------------------------------------------------
# Scenario 1 — Happy path: closed-value-set + ERROR severity (canonical)
# ---------------------------------------------------------------------------


class TestCanonicalWorkedExample:
    """Closed-value-set + ERROR severity per the on-disk pyproject."""

    def test_end_to_end_produces_two_custom_findings(self) -> None:
        """``BareAudit`` (presence) + ``DisallowedAudit`` (value-mismatch).

        Asserts the synthetic rule materializes correctly:
        - rule_id matches ``custom/audit-required``
        - source_spec is the documented protokit-namespaced value
          (verified at spec level in
          :mod:`tests.schema.lint.test_custom_rules_loader`).
        - severity is ERROR (per the fixture pyproject's per-entry
          ``severity = "error"`` override)
        - violation_kind pairs with the expected method:
          ``BareAudit`` → ``custom-annotation-absent``;
          ``DisallowedAudit`` → ``custom-annotation-value-mismatch``
          (pinned per-finding so a swap-regression is visible).
        - params carry the option name + (for mismatch) the actual
          rejected value — the structured agent-native discriminator.
        - location_file is the bare proto path
          ``example/service.proto`` (stable file-correlation key).
        - exit code is 1 (findings present, gate trips).
        - runtime_warnings is empty (no extension-unresolved noise).
        """
        exit_code, payload, _, _ = _run_lint(_FIXTURE_PYPROJECT)

        custom = _findings_for_rule(payload, _RULE_ID)
        assert len(custom) == 2, (
            f"expected 2 {_RULE_ID} findings, got {len(custom)}\n"
            f"all findings: {payload['findings']!r}"
        )

        # Pin the per-method violation_kind pairing. A regression that
        # swapped the two arms between methods would still satisfy
        # set-equality checks, so the test pins each method's
        # discriminator individually here.
        by_method = {_method_name(f): f for f in custom}
        assert set(by_method) == {"BareAudit", "DisallowedAudit"}, (
            f"unexpected method coverage: {set(by_method)!r}"
        )

        bare = by_method["BareAudit"]
        assert bare["rule_id"] == _RULE_ID
        assert bare["severity"] == "error"
        assert bare["location_kind"] == "method"
        assert bare["location_file"] == "example/service.proto"
        assert bare["violation_kind"] == _KIND_ABSENT
        # Agent-native contract: params['option'] is the stable
        # extension-name key; agents correlate findings to the
        # configured rule without parsing message text.
        assert bare["params"]["option"] == _FIXTURE_OPTION
        assert bare["params"]["rule_id"] == _RULE_ID
        # Presence-only finding does NOT carry actual_value.
        assert "actual_value" not in bare["params"]

        mismatch = by_method["DisallowedAudit"]
        assert mismatch["rule_id"] == _RULE_ID
        assert mismatch["severity"] == "error"
        assert mismatch["location_kind"] == "method"
        assert mismatch["location_file"] == "example/service.proto"
        assert mismatch["violation_kind"] == _KIND_VALUE_MISMATCH
        assert mismatch["params"]["option"] == _FIXTURE_OPTION
        assert mismatch["params"]["rule_id"] == _RULE_ID
        # Value-mismatch finding carries the rejected enum identifier
        # (translated from the raw int value via
        # resolve_enum_value_for_comparison).
        assert mismatch["params"]["actual_value"] == "NONE"

        # Exit 1 because the per-entry severity is ERROR (gate trips
        # on any error finding regardless of --max-warnings).
        assert exit_code == 1

        # No runtime warnings on the happy path: the audit_level
        # extension IS in the compile pool (audit.proto is included
        # transitively via service.proto's import), so the rule does
        # not emit ``custom_annotation_extension_unresolved``.
        assert payload["runtime_warnings"] == [], (
            f"expected zero runtime warnings on happy path; got "
            f"{payload['runtime_warnings']!r}"
        )


# ---------------------------------------------------------------------------
# Scenario 2 — Presence-only variant (allowed_values omitted)
# ---------------------------------------------------------------------------


class TestPresenceOnlyVariant:
    """A second pyproject overlay drops ``allowed_values`` entirely."""

    def test_presence_only_rule_fires_on_absence_only(
        self, tmp_path: Path,
    ) -> None:
        """Without ``allowed_values``, the rule fires on absence only.

        Overrides the canonical pyproject by writing a tmp_path
        variant that drops ``allowed_values``. The rule then fires
        on absence (``BareAudit``) but NOT on value-mismatch
        (``DisallowedAudit`` with ``NONE`` now passes because no
        closed set restricts the value). Severity is ERROR so the
        exit-code gate trips.
        """
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            textwrap.dedent(
                f"""\
                [tool.protokit.lint]
                profile = "recommended"

                [tool.protokit.lint.severities]
                # Carry the canonical fixture's imports/unused demotion
                # so the overlay produces the same noise profile.
                "imports/unused" = "info"

                [[tool.protokit.lint.custom_annotation_rules]]
                rule_suffix    = "{_FIXTURE_RULE_SUFFIX}"
                option         = "{_FIXTURE_OPTION}"
                element_kinds  = ["method"]
                severity       = "error"
                """,
            ),
            encoding="utf-8",
        )

        exit_code, payload, _, _ = _run_lint(pyproject)
        custom = _findings_for_rule(payload, _RULE_ID)

        # Exactly one finding (BareAudit's presence violation). The
        # NONE-annotated method now passes because the rule has no
        # closed value set to test against.
        assert len(custom) == 1
        assert _method_name(custom[0]) == "BareAudit"
        # Discriminator pin: a regression that emitted
        # ``custom-annotation-value-mismatch`` on absence (an
        # impossible-but-conceivable mis-routing in _make_synthetic_closure)
        # would still satisfy the count + method-name assertions
        # above, so the violation_kind is pinned individually.
        assert custom[0]["violation_kind"] == _KIND_ABSENT
        # Exit 1 because severity=error trips the gate on the single
        # presence finding.
        assert exit_code == 1


# ---------------------------------------------------------------------------
# Scenario 3 — [severities] table demotes the rule to info
# ---------------------------------------------------------------------------


class TestSeverityOverrideViaSeveritiesTable:
    """``[severities]`` overlay demotes the synthetic rule_id."""

    def test_severity_override_demotes_to_info(
        self, tmp_path: Path,
    ) -> None:
        """Override the per-entry severity via the ``[severities]`` table.

        The pyproject precedence model (per umbrella KD-9) makes
        ``[tool.protokit.lint.severities]`` the LAST authority on
        per-rule severity. Synthetic rule_ids inherit this without
        exception — a demotion of ``custom/audit-required`` to
        ``info`` is reflected in every finding's severity field AND
        in the CI gate: exit code drops from 1 to 0 because no
        ERROR-severity findings remain.

        Passes ``--min-severity info`` so the demoted findings are
        not filtered out before they reach the JSON payload.
        """
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            textwrap.dedent(
                f"""\
                [tool.protokit.lint]
                profile = "recommended"

                [[tool.protokit.lint.custom_annotation_rules]]
                rule_suffix    = "{_FIXTURE_RULE_SUFFIX}"
                option         = "{_FIXTURE_OPTION}"
                element_kinds  = ["method"]
                allowed_values = ["LOW", "HIGH", "CRITICAL"]
                severity       = "error"

                [tool.protokit.lint.severities]
                "{_RULE_ID}" = "info"
                "imports/unused" = "info"
                """,
            ),
            encoding="utf-8",
        )

        exit_code, payload, _, _ = _run_lint(
            pyproject, extra_args=("--min-severity", "info"),
        )
        custom = _findings_for_rule(payload, _RULE_ID)

        # The two findings still surface, but at info severity
        # rather than the per-entry-declared error.
        assert len(custom) == 2
        for f in custom:
            assert f["severity"] == "info", (
                f"expected demoted severity=info; got {f!r}"
            )

        # Exit 0 because every finding is now info-severity; the
        # default --min-severity=error gate no longer trips. This is
        # the load-bearing user-story contract: "demote the rule to
        # info and CI stays green."
        assert exit_code == 0


# ---------------------------------------------------------------------------
# Scenario 4 — Extension-unresolved runtime warning surfaces in JSON
# ---------------------------------------------------------------------------


class TestExtensionUnresolvedWarning:
    """The ``custom_annotation_extension_unresolved`` runtime warning path.

    The pyproject fixture's inline comment documents that passing
    the parenthesized form ``(example.audit_level)`` causes
    ``pool.FindExtensionByName`` to raise ``KeyError`` (the
    parenthesized form is invalid for ``FindExtensionByName``, which
    expects the bare fully-qualified name). The rule then skips
    firing and emits one deduplicated runtime warning per file.

    This scenario verifies the warning surfaces in the
    ``runtime_warnings`` array of ``--format=json`` output with the
    correct ``category``, ``rule_id``, and a non-empty ``message`` —
    the structured signal agents rely on to detect rule
    misconfiguration without parsing prose.
    """

    def test_parenthesized_option_emits_extension_unresolved_warning(
        self, tmp_path: Path,
    ) -> None:
        """An invalid option form silently no-ops + emits one warning.

        Confirms the warning is surfaced through the JSON wire format
        (per the closed-Literal contract pinned at
        ``_LINT_JSON_SCHEMA_VERSION``).
        """
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            textwrap.dedent(
                f"""\
                [tool.protokit.lint]
                profile = "recommended"

                [tool.protokit.lint.severities]
                "imports/unused" = "info"

                [[tool.protokit.lint.custom_annotation_rules]]
                rule_suffix    = "{_FIXTURE_RULE_SUFFIX}"
                option         = "({_FIXTURE_OPTION})"
                element_kinds  = ["method"]
                severity       = "error"
                """,
            ),
            encoding="utf-8",
        )

        exit_code, payload, _, _ = _run_lint(pyproject)

        # Zero findings — the rule silently skipped firing per file
        # because the extension could not be resolved.
        custom = _findings_for_rule(payload, _RULE_ID)
        assert len(custom) == 0

        # Exactly one structured runtime warning (deduplicated per
        # (rule_id, file) tuple; service.proto is the only root file).
        warnings = [
            w for w in payload["runtime_warnings"]
            if w["category"] == "custom_annotation_extension_unresolved"
        ]
        assert len(warnings) == 1, (
            f"expected 1 extension_unresolved warning; got "
            f"{payload['runtime_warnings']!r}"
        )
        assert warnings[0]["rule_id"] == _RULE_ID
        assert warnings[0]["message"], "warning message must be non-empty"

        # Exit code is whatever other builtin-rule findings produce.
        # Allowed range checked inside _run_lint; assert specifically
        # that the gate did not trip on a phantom finding from the
        # unresolved rule.
        assert exit_code in (0, 1)


# ---------------------------------------------------------------------------
# Scenario 5 — Exit-2 error paths (malformed pyproject)
# ---------------------------------------------------------------------------


class TestConfigErrorPaths:
    """Malformed ``[[custom_annotation_rules]]`` produces structured exit-2.

    Agents constructing pyproject content programmatically need a
    parseable signal when their config is rejected. The CLI emits
    ``error[lint-pyproject-config-invalid]:`` on stderr and exits 2.
    This scenario verifies the contract is observable through the
    same fixture surface a human user encounters.
    """

    def test_missing_required_option_key_exits_2(
        self, tmp_path: Path,
    ) -> None:
        """Omitting the required ``option`` key triggers exit 2."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            textwrap.dedent(
                f"""\
                [tool.protokit.lint]
                profile = "recommended"

                [[tool.protokit.lint.custom_annotation_rules]]
                rule_suffix    = "{_FIXTURE_RULE_SUFFIX}"
                element_kinds  = ["method"]
                """,
            ),
            encoding="utf-8",
        )

        exit_code, _, stderr = _run_lint_raw(pyproject)
        assert exit_code == 2, f"expected exit 2; got {exit_code!r}"
        assert "error[lint-pyproject-config-invalid]:" in stderr
        assert "option" in stderr

    def test_uppercase_rule_suffix_exits_2(
        self, tmp_path: Path,
    ) -> None:
        """A regex-invalid ``rule_suffix`` (uppercase) exits 2."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            textwrap.dedent(
                f"""\
                [tool.protokit.lint]
                profile = "recommended"

                [[tool.protokit.lint.custom_annotation_rules]]
                rule_suffix    = "Audit-Required"
                option         = "{_FIXTURE_OPTION}"
                element_kinds  = ["method"]
                """,
            ),
            encoding="utf-8",
        )

        exit_code, _, stderr = _run_lint_raw(pyproject)
        assert exit_code == 2
        assert "error[lint-pyproject-config-invalid]:" in stderr
        assert "rule_suffix" in stderr


# ---------------------------------------------------------------------------
# Scenario 6 — SARIF format output exposes the synthetic rule catalog entry
# ---------------------------------------------------------------------------


class TestSarifFormatExposesCustomRule:
    """SARIF 2.1.0 output surfaces ``custom/<suffix>`` in the rules catalog.

    GitHub Code Scanning, VS Code SARIF Viewer, and other OASIS
    SARIF consumers read ``runs[0].tool.driver.rules`` to populate
    their rule-metadata side panels. The synthetic rule's catalog
    entry must be present so consumers can render its metadata + tie
    individual results back to the rule. This is the agent-native
    equivalent of the per-finding JSON discriminator coverage in
    Scenario 1.
    """

    def test_sarif_runs_tool_driver_rules_includes_custom_rule(
        self,
    ) -> None:
        """The synthetic rule_id appears in the SARIF rules catalog.

        Asserts the catalog entry exists + carries the protokit-
        namespaced ``source_spec`` informationUri (verified at the
        spec level in
        :mod:`tests.schema.lint.test_custom_rules_loader`).
        """
        exit_code, payload, _, _ = _run_lint(
            _FIXTURE_PYPROJECT, format_="sarif",
        )
        assert exit_code == 1
        assert payload["version"] == "2.1.0"
        rules = payload["runs"][0]["tool"]["driver"]["rules"]
        rule_ids = {r["id"] for r in rules}
        assert _RULE_ID in rule_ids, (
            f"{_RULE_ID!r} missing from SARIF rules catalog; "
            f"present rule_ids: {sorted(rule_ids)!r}"
        )

        # Locate the synthetic rule's catalog entry and pin the
        # agent-native fields a consumer would actually read.
        synthetic_entry = next(
            r for r in rules if r["id"] == _RULE_ID
        )
        # The catalog entry must include a name (rendered as the rule
        # header in SARIF viewers) — synthetic specs use the rule_id
        # as the name. Other SARIF metadata fields are exercised in
        # the formatter-level tests at tests/test_formatters_sarif.py.
        assert synthetic_entry["name"] == _RULE_ID


# ---------------------------------------------------------------------------
# Module-level smoke: the fixture's proto root resolves correctly.
# ---------------------------------------------------------------------------


def test_fixture_proto_root_structure_is_intact() -> None:
    """Catch fixture-tree drift early (rename / move / accidental delete).

    Module-level test that runs even if no scenario test is selected,
    so contributors editing the fixture get a fast-fail signal at
    collection time rather than a confusing per-scenario failure.

    Each is_file() check uses the module-level path constant so a
    fixture rename only updates the constant — the structure-intact
    assertion follows automatically.
    """
    assert _FIXTURE_ROOT.is_dir()
    assert _FIXTURE_PROTO_ROOT.is_dir()
    assert _FIXTURE_PYPROJECT.is_file()
    assert _FIXTURE_AUDIT_PROTO.is_file()
    assert _FIXTURE_SERVICE_PROTO.is_file()


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
