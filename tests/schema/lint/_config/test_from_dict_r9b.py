"""``ResolvedLintConfig.from_dict`` R9b dispatch tests (D6f U2).

Pins the intra-``from_dict`` ordering (KD-2), custom-prefix
expansion semantics (KD-2 suffix-equality matching), CLI overrides
(KD-5 natural empty-tuple sentinel), and the unified
``disabled_rules`` merge per the KD-1 sentinel propagation contract.

The R8 precedence table (13 cases) lives in
``tests/schema/lint/test_r9b_precedence.py`` — this file focuses on
the dispatch mechanics that don't belong in the precedence matrix.
"""

from __future__ import annotations

import pytest

from protokit.schema.lint._config import LintSeverity, ResolvedLintConfig

from .conftest import expect_invalid


class TestCustomPrefixExpansion:
    """KD-2 bare ``custom/<suffix>`` → all kind-mangled forms."""

    def test_single_kind_custom_rule_no_mangling(self) -> None:
        """A single-kind spec produces only the bare rule_id; the
        expansion is effectively a no-op."""
        resolved = ResolvedLintConfig.from_dict(
            {
                "custom_annotation_rules": [
                    {
                        "rule_suffix": "audit-required",
                        "option": "example.audit_level",
                        "element_kinds": ["method"],
                    },
                ],
                "disabled_rules": ["custom/audit-required"],
            },
            {},
        )
        assert resolved.disabled_rules == frozenset({"custom/audit-required"})

    def test_multi_kind_custom_rule_expands_to_all_mangled_forms(
        self,
    ) -> None:
        """A multi-kind spec expands the bare entry to bare + every
        ``__<kind>`` mangled form per ``synthetic_rule_ids()``."""
        resolved = ResolvedLintConfig.from_dict(
            {
                "custom_annotation_rules": [
                    {
                        "rule_suffix": "audit-required",
                        "option": "example.audit_level",
                        "element_kinds": ["method", "service", "field"],
                    },
                ],
                "disabled_rules": ["custom/audit-required"],
            },
            {},
        )
        assert resolved.disabled_rules == frozenset(
            {
                "custom/audit-required",
                "custom/audit-required__service",
                "custom/audit-required__field",
            },
        )

    def test_per_kind_explicit_form_bypasses_expansion(self) -> None:
        """``disabled_rules = ["custom/X__method"]`` disables only the
        method kind; bare prefix expansion does not apply."""
        resolved = ResolvedLintConfig.from_dict(
            {
                "custom_annotation_rules": [
                    {
                        "rule_suffix": "audit-required",
                        "option": "example.audit_level",
                        "element_kinds": ["method", "service"],
                    },
                ],
                "disabled_rules": ["custom/audit-required__service"],
            },
            {},
        )
        assert resolved.disabled_rules == frozenset(
            {"custom/audit-required__service"},
        )

    def test_bare_plus_explicit_form_idempotent(self) -> None:
        """``["custom/X", "custom/X__method"]`` → idempotent (the
        bare expansion already includes the mangled form)."""
        resolved = ResolvedLintConfig.from_dict(
            {
                "custom_annotation_rules": [
                    {
                        "rule_suffix": "audit-required",
                        "option": "example.audit_level",
                        "element_kinds": ["method", "service"],
                    },
                ],
                "disabled_rules": [
                    "custom/audit-required",
                    "custom/audit-required__service",
                ],
            },
            {},
        )
        assert resolved.disabled_rules == frozenset(
            {
                "custom/audit-required",
                "custom/audit-required__service",
            },
        )

    def test_suffix_equality_does_not_substring_match(self) -> None:
        """``"custom/foo"`` must NOT expand against a spec with
        ``rule_suffix="foobar"`` — suffix equality, not substring."""
        resolved = ResolvedLintConfig.from_dict(
            {
                "custom_annotation_rules": [
                    {
                        "rule_suffix": "foobar",
                        "option": "example.foo",
                        "element_kinds": ["method", "service"],
                    },
                ],
                "disabled_rules": ["custom/foo"],
            },
            {},
        )
        # "custom/foo" preserved as-is (no matching spec); R8c warning
        # would fire from CLI orchestration when no loaded rule
        # matches. ``foobar`` mangled forms NOT included.
        assert resolved.disabled_rules == frozenset({"custom/foo"})
        assert (
            "custom/foobar__service" not in resolved.disabled_rules
        )

    def test_unmatched_bare_custom_preserved_for_r8c_diagnosis(
        self,
    ) -> None:
        """No matching ``custom_annotation_rules`` spec → bare entry
        preserved so the CLI's R8c emission can name it."""
        resolved = ResolvedLintConfig.from_dict(
            {"disabled_rules": ["custom/unknown-suffix"]},
            {},
        )
        assert resolved.disabled_rules == frozenset(
            {"custom/unknown-suffix"},
        )

    def test_expansion_applies_to_enabled_rules_symmetrically(
        self,
    ) -> None:
        resolved = ResolvedLintConfig.from_dict(
            {
                "custom_annotation_rules": [
                    {
                        "rule_suffix": "audit-required",
                        "option": "example.audit_level",
                        "element_kinds": ["method", "service"],
                    },
                ],
                "enabled_rules": ["custom/audit-required"],
            },
            {},
        )
        assert resolved.enabled_rules == frozenset(
            {
                "custom/audit-required",
                "custom/audit-required__service",
            },
        )

    def test_expansion_applies_to_off_severity_sentinel(self) -> None:
        """``[severities] "custom/X" = "off"`` where X is multi-kind →
        expanded into the unified disabled_rules per KD-1+KD-2."""
        resolved = ResolvedLintConfig.from_dict(
            {
                "custom_annotation_rules": [
                    {
                        "rule_suffix": "audit-required",
                        "option": "example.audit_level",
                        "element_kinds": ["method", "service"],
                    },
                ],
                "severities": {"custom/audit-required": "off"},
            },
            {},
        )
        assert resolved.disabled_rules == frozenset(
            {
                "custom/audit-required",
                "custom/audit-required__service",
            },
        )

    def test_expansion_applies_to_non_off_severity_override(self) -> None:
        """``[severities] "custom/X" = "warning"`` must reach every kind
        of a multi-kind X, exactly as the ``"off"`` sentinel does.

        Without expansion the engine's ``rule_severity_overrides.get(
        spec.rule_id)`` lookup misses the ``__<kind>`` forms, so the
        same bare key would silently retune only the first kind."""
        resolved = ResolvedLintConfig.from_dict(
            {
                "custom_annotation_rules": [
                    {
                        "rule_suffix": "audit-required",
                        "option": "example.audit_level",
                        "element_kinds": ["method", "service"],
                    },
                ],
                "severities": {"custom/audit-required": "warning"},
            },
            {},
        )
        assert dict(resolved.severities) == {
            "custom/audit-required": LintSeverity.WARNING,
            "custom/audit-required__service": LintSeverity.WARNING,
        }

    def test_explicit_mangled_severity_key_wins_over_expansion(self) -> None:
        """A per-kind key stated alongside the bare family key keeps its
        own severity — expansion must not clobber the more specific
        entry regardless of table order."""
        resolved = ResolvedLintConfig.from_dict(
            {
                "custom_annotation_rules": [
                    {
                        "rule_suffix": "audit-required",
                        "option": "example.audit_level",
                        "element_kinds": ["method", "service"],
                    },
                ],
                "severities": {
                    "custom/audit-required": "warning",
                    "custom/audit-required__service": "info",
                },
            },
            {},
        )
        assert dict(resolved.severities) == {
            "custom/audit-required": LintSeverity.WARNING,
            "custom/audit-required__service": LintSeverity.INFO,
        }


class TestIntraFromDictOrdering:
    """KD-2 — ``custom_annotation_rules`` resolves FIRST, then R9b
    list coercion, then prefix expansion, then R8 precedence."""

    def test_custom_annotation_rules_resolved_before_expansion(
        self,
    ) -> None:
        """If expansion happened before custom_annotation_rules
        resolution, the bare ``custom/audit-required`` would never
        expand. Verify the expanded form IS in the resolved set."""
        resolved = ResolvedLintConfig.from_dict(
            {
                "custom_annotation_rules": [
                    {
                        "rule_suffix": "audit-required",
                        "option": "example.audit_level",
                        "element_kinds": ["method", "field"],
                    },
                ],
                "disabled_rules": ["custom/audit-required"],
            },
            {},
        )
        # If ordering were wrong, this would only contain the bare
        # form and miss "custom/audit-required__field".
        assert (
            "custom/audit-required__field" in resolved.disabled_rules
        )


class TestUnifiedDisabledRulesMerge:
    """KD-1 — the unified ``disabled_rules`` field merges three
    sources (off-severity + pyproject disabled_rules + CLI
    --disable-rule)."""

    def test_three_sources_union_into_one_frozenset(self) -> None:
        resolved = ResolvedLintConfig.from_dict(
            {
                "severities": {"naming/snake-case-fields": "off"},
                "disabled_rules": ["imports/unused"],
            },
            {"disabled_rules": ("naming/no-leading-underscore",)},
        )
        assert resolved.disabled_rules == frozenset(
            {
                "naming/snake-case-fields",
                "imports/unused",
                "naming/no-leading-underscore",
            },
        )

    def test_resolved_severities_excludes_off_entries(self) -> None:
        """The ``off`` sentinel is intercepted at the coercion layer
        per KD-1; resolved.severities only contains non-off entries.
        """
        resolved = ResolvedLintConfig.from_dict(
            {
                "severities": {
                    "naming/snake-case-fields": "off",
                    "imports/unused": "warning",
                },
            },
            {},
        )
        # severities preserves non-off entries with LintSeverity vals
        assert "naming/snake-case-fields" not in resolved.severities
        assert "imports/unused" in resolved.severities
        # off entry surfaces in the unified disabled_rules instead
        assert "naming/snake-case-fields" in resolved.disabled_rules


class TestCliOverrideSentinels:
    """KD-5 — Click ``multiple=True`` empty-tuple sentinel; None means
    "user did not pass this flag"."""

    def test_none_means_cli_did_not_pass_flag(self) -> None:
        """When the CLI did not pass --disable-rule, ``None`` is the
        sentinel; the unified disabled_rules reflects only pyproject."""
        resolved = ResolvedLintConfig.from_dict(
            {"disabled_rules": ["naming/snake-case-fields"]},
            {"disabled_rules": None, "enabled_rules": None},
        )
        assert resolved.disabled_rules == frozenset(
            {"naming/snake-case-fields"},
        )

    def test_empty_tuple_cli_override_treated_as_absent(self) -> None:
        """If the caller passes ``()`` (the natural Click empty
        sentinel BEFORE the cli.py wiring converts it to None), the
        helper treats it the same as None — no CLI disables added."""
        resolved = ResolvedLintConfig.from_dict(
            {"disabled_rules": ["naming/snake-case-fields"]},
            {"disabled_rules": (), "enabled_rules": ()},
        )
        # The empty tuple coerces to frozenset() and unions cleanly;
        # the result is identical to None-sentinel semantics for the
        # disabled-rules field.
        assert resolved.disabled_rules == frozenset(
            {"naming/snake-case-fields"},
        )


class TestSeveritiesOffValueRejection:
    """``"off"`` is the ONLY non-LintSeverity string accepted by
    ``_coerce_severities``."""

    def test_invalid_severity_error_advertises_off_in_message(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The 'valid values' message advertises ``"off"`` alongside
        the closed-set LintSeverity values so users discover the R9b
        disable mechanism from the error."""
        expect_invalid(
            {"severities": {"naming/snake-case-fields": "fatal"}},
            {},
            capsys,
            substring="or 'off' to disable",
        )

    def test_off_case_insensitive_with_whitespace(self) -> None:
        """``"OFF"`` / ``"  off  "`` all normalize to the sentinel."""
        resolved = ResolvedLintConfig.from_dict(
            {
                "severities": {
                    "naming/a": "OFF",
                    "naming/b": "  off  ",
                },
            },
            {},
        )
        assert resolved.severities == {}
        assert resolved.disabled_rules == frozenset(
            {"naming/a", "naming/b"},
        )
