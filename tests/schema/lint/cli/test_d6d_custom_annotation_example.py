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

The README cross-reference + copy-paste contract land in new-U4
(was U5) per the umbrella plan's revised unit lineup
(``docs/plans/2026-05-19-001-feat-d6d-option-aware-pack-expansion-plan.md``
Strategic Deferral section). This test file is the contract
new-U4 pins against.
"""

from __future__ import annotations

import json
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


def _run_lint(
    pyproject: Path,
    *,
    extra_args: tuple[str, ...] = (),
) -> tuple[int, dict[str, Any]]:
    """Invoke ``protokit lint`` against the worked-example service.

    Returns ``(exit_code, parsed_json_payload)``. The payload is the
    full ``--format=json`` document including ``findings`` and
    ``runtime_warnings``.

    Centralizes the CLI invocation so the four test scenarios share
    one canonical invocation shape. Test-level customization happens
    via ``pyproject`` (write a modified TOML to ``tmp_path``) and
    ``extra_args`` (additional CLI flags).
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
    )
    # Exit 0 (no findings) or 1 (findings exist) are both expected
    # under different scenarios; exit 2 signals a CLI-internal error
    # that means the fixture is broken — fail loudly with stderr.
    assert result.exit_code in (0, 1), (
        f"expected lint exit 0/1, got {result.exit_code!r}\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    payload = json.loads(result.stdout)
    return result.exit_code, payload


def _findings_for_rule(
    payload: dict[str, Any], rule_id: str,
) -> list[dict[str, Any]]:
    """Extract findings matching ``rule_id`` from the JSON payload.

    Filters on ``rule_id`` so the test asserts on the synthetic
    rule's behavior specifically, decoupled from any other built-in
    rule that might also fire on the fixture (today: none under
    ``recommended`` profile, but the filter future-proofs the test
    against built-in pack expansion).
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
    proper.
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
        - severity is ERROR (per the fixture pyproject's per-entry
          ``severity = "error"`` override)
        - exactly the two method names BareAudit + DisallowedAudit
          appear in findings; HighAudit + LowAudit do NOT
        - exit code is 1 (findings present, gate trips)
        """
        exit_code, payload = _run_lint(_FIXTURE_PYPROJECT)

        custom = _findings_for_rule(payload, "custom/audit-required")
        assert len(custom) == 2, (
            f"expected 2 custom/audit-required findings, got {len(custom)}\n"
            f"all findings: {payload['findings']!r}"
        )

        method_names = {_method_name(f) for f in custom}
        assert method_names == {"BareAudit", "DisallowedAudit"}, (
            f"unexpected method coverage: {method_names!r}"
        )

        # Per-finding contract: rule_id + severity + violation_kind
        # discriminator all match the synthetic-rule emission shape
        # U1 established. (``source_spec`` is rule-metadata held by
        # ``LintEngine._loaded_specs[rule_id].source_spec``, not a
        # per-finding field in the ``--format=json`` payload — the
        # umbrella brainstorm R10 framing of "source_spec ==
        # protokit:custom-annotation" is verified at the rule-spec
        # level, not the finding level. See the
        # TestSyntheticRuleSpecRegistryContract test below for the
        # rule-spec-level verification.)
        for f in custom:
            assert f["rule_id"] == "custom/audit-required"
            assert f["severity"] == "error"
            assert f["location_kind"] == "method"
        by_kind = {f["violation_kind"] for f in custom}
        assert by_kind == {
            "custom-annotation-absent",
            "custom-annotation-value-mismatch",
        }, f"unexpected violation_kind set: {by_kind!r}"

        # Exit 1 because the per-entry severity is ERROR (gate trips
        # on any error finding regardless of --max-warnings).
        assert exit_code == 1


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
        closed set restricts the value).
        """
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            "[tool.protokit.lint]\n"
            'profile = "recommended"\n'
            "\n"
            "[tool.protokit.lint.severities]\n"
            # Carry the canonical fixture's imports/unused demotion
            # so the overlay produces the same noise profile.
            '"imports/unused" = "info"\n'
            "\n"
            "[[tool.protokit.lint.custom_annotation_rules]]\n"
            'rule_suffix    = "audit-required"\n'
            'option         = "example.audit_level"\n'
            'element_kinds  = ["method"]\n'
            'severity       = "error"\n',
            encoding="utf-8",
        )

        _, payload = _run_lint(pyproject)
        custom = _findings_for_rule(payload, "custom/audit-required")

        # Exactly one finding (BareAudit's presence violation). The
        # NONE-annotated method now passes because the rule has no
        # closed value set to test against.
        assert len(custom) == 1
        assert _method_name(custom[0]) == "BareAudit"


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
        ``info`` is reflected in every finding's severity field.

        Passes ``--min-severity info`` so the demoted findings are
        not filtered out before they reach the JSON payload.
        """
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            "[tool.protokit.lint]\n"
            'profile = "recommended"\n'
            "\n"
            "[[tool.protokit.lint.custom_annotation_rules]]\n"
            'rule_suffix    = "audit-required"\n'
            'option         = "example.audit_level"\n'
            'element_kinds  = ["method"]\n'
            'allowed_values = ["LOW", "HIGH", "CRITICAL"]\n'
            'severity       = "error"\n'
            "\n"
            "[tool.protokit.lint.severities]\n"
            '"custom/audit-required" = "info"\n'
            '"imports/unused" = "info"\n',
            encoding="utf-8",
        )

        _, payload = _run_lint(
            pyproject, extra_args=("--min-severity", "info"),
        )
        custom = _findings_for_rule(payload, "custom/audit-required")

        # The two findings still surface, but at info severity
        # rather than the per-entry-declared error.
        assert len(custom) == 2
        for f in custom:
            assert f["severity"] == "info", (
                f"expected demoted severity=info; got {f!r}"
            )


# ---------------------------------------------------------------------------
# Scenario 4 — Copy-paste verification placeholder (contract for new-U4)
# ---------------------------------------------------------------------------


class TestCopyPasteContract:
    """The on-disk fixture is the canonical worked example.

    The actual README copy-paste verification lands in new-U4 (was
    U5) per the umbrella plan's Strategic Deferral renumbering. This
    test asserts the contract that new-U4 will pin against: the
    on-disk fixture works without modification when invoked the way
    a user copy-pasting from the README would invoke it.
    """

    def test_on_disk_fixture_runs_clean_from_a_user_perspective(
        self,
    ) -> None:
        """A user copying the fixture verbatim gets the documented behavior.

        Mirrors the first scenario but spelled out as the contract
        new-U4's README example must satisfy: invoking
        ``protokit lint`` against the on-disk fixture pyproject +
        proto source produces a deterministic 2-finding result with
        the expected rule_id.

        new-U4 will add a README snippet that names this exact
        invocation; the contract pinned here ensures the snippet
        keeps working as the fixture / synthetic-rule infrastructure
        evolves.
        """
        # All three fixture files are committed to the repo and
        # discoverable at the documented paths.
        assert _FIXTURE_PYPROJECT.is_file()
        assert _FIXTURE_SERVICE_PROTO.is_file()
        assert _FIXTURE_AUDIT_PROTO.is_file()

        exit_code, payload = _run_lint(_FIXTURE_PYPROJECT)
        custom = _findings_for_rule(payload, "custom/audit-required")

        # The user-visible outcome new-U4's README snippet promises:
        # two findings, exit code 1, both findings tagged with the
        # synthetic rule_id (``source_spec`` is rule-metadata, not a
        # per-finding field — see the canonical scenario test for
        # the discriminator-on-finding contract).
        assert len(custom) == 2
        assert exit_code == 1
        for f in custom:
            assert f["rule_id"] == "custom/audit-required"


# ---------------------------------------------------------------------------
# Module-level smoke: the fixture's proto root resolves correctly.
# ---------------------------------------------------------------------------


def test_fixture_proto_root_structure_is_intact() -> None:
    """Catch fixture-tree drift early (rename / move / accidental delete).

    Module-level test that runs even if no scenario test is selected,
    so contributors editing the fixture get a fast-fail signal at
    collection time rather than a confusing per-scenario failure.
    """
    assert _FIXTURE_PROTO_ROOT.is_dir()
    assert (_FIXTURE_PROTO_ROOT / "example" / "audit.proto").is_file()
    assert (_FIXTURE_PROTO_ROOT / "example" / "service.proto").is_file()


# ---------------------------------------------------------------------------
# Rule-spec-level contract — source_spec is rule-metadata, not per-finding
# ---------------------------------------------------------------------------


class TestSyntheticRuleSpecRegistryContract:
    """The umbrella brainstorm R10 source_spec contract lives on the spec.

    R10 (``protokit:custom-annotation`` source_spec) is a rule-spec-
    level invariant — it lives on ``LintRuleSpec.source_spec``,
    accessed via ``LintEngine._loaded_specs[rule_id]`` after
    config-resolution loads the synthetic module. It is NOT a per-
    finding JSON field. This test verifies the spec-level contract
    directly so it survives any future change to the per-finding
    JSON shape.
    """

    def test_synthetic_rule_spec_carries_protokit_namespaced_source_spec(
        self,
    ) -> None:
        """Synthetic specs register with ``source_spec='protokit:custom-annotation'``.

        Builds the synthetic module the same way ``cli.py`` does and
        inspects each materialized spec's ``source_spec`` field. The
        brainstorm pins this value as the protokit-namespaced
        identifier so consumers walking ``_loaded_specs`` can
        distinguish synthetic rules from buf-parity rules
        (``source_spec`` starts with ``buf:``) and protokit-original
        rules (other namespaces).
        """
        from protokit.schema.lint._config import CustomAnnotationRuleSpec
        from protokit.schema.lint._custom_rules import build_synthetic_module
        from protokit.schema.lint.engine import LintEngine
        from protokit.schema.lint.model import ElementKind, LintSeverity

        # Mirror the fixture's pyproject entry programmatically; the
        # CustomAnnotationRuleSpec dataclass is the same shape
        # ``_coerce_custom_annotation_rules`` produces.
        spec = CustomAnnotationRuleSpec(
            rule_suffix="audit-required",
            option="example.audit_level",
            element_kinds=(ElementKind.METHOD,),
            allowed_values=("LOW", "HIGH", "CRITICAL"),
            severity=LintSeverity.ERROR,
        )

        engine = LintEngine()
        module = build_synthetic_module((spec,), engine)
        # ``build_synthetic_module`` returns ``None`` only when the
        # specs sequence is empty; a single-spec input always returns
        # a module. Assert to narrow the type for mypy and to
        # fail-loud if the contract regresses.
        assert module is not None
        engine.load_rule_pack(module)

        loaded = engine._loaded_specs["custom/audit-required"]
        assert loaded.source_spec == "protokit:custom-annotation"
        assert loaded.rule_id == "custom/audit-required"
        assert loaded.element is ElementKind.METHOD
        # Severity is dict-shaped per violation_kind (matching U2's
        # options/field-behavior-consistent multi-arm pattern); the
        # per-entry pyproject ``severity = "error"`` applies uniformly
        # to both ``custom-annotation-absent`` and
        # ``custom-annotation-value-mismatch`` arms.
        assert loaded.severity == {
            "custom-annotation-absent": LintSeverity.ERROR,
            "custom-annotation-value-mismatch": LintSeverity.ERROR,
        }


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
