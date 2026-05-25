"""R9b ``contradictory_disable_config`` (R8b) emission tests (D6f U2).

Pins the message content of the R8b warning category landed in
D6f U2 — emitted from ``ResolvedLintConfig.from_dict`` when an R9b
directive is silently overridden by R8 polarity-first / tier-second
precedence.

The :class:`tests/schema/lint/test_r9b_precedence.TestPrecedenceTable`
matrix already pins the R8 13-case truth table for the *presence* of
R8b warnings; this file focuses on the *message content*.

The R8c ``unknown_rule_id`` emission path requires the engine's
full ``_loaded_specs`` registry and is therefore tested end-to-end
in ``tests/schema/lint/cli/test_cli_r9b_unknown_rule_id.py`` where
the CLI fixtures live.
"""

from __future__ import annotations

from protokit.schema.lint._config import ResolvedLintConfig


class TestR8bWarningMessages:
    """R8b ``contradictory_disable_config`` message content."""

    def test_pyproject_disabled_plus_enabled_names_both_mechanisms(
        self,
    ) -> None:
        resolved = ResolvedLintConfig.from_dict(
            {
                "disabled_rules": ["naming/snake-case-fields"],
                "enabled_rules": ["naming/snake-case-fields"],
            },
            {},
        )
        warnings = [
            w
            for w in resolved.runtime_warnings
            if w.category == "contradictory_disable_config"
        ]
        assert len(warnings) == 1
        msg = warnings[0].message
        assert "naming/snake-case-fields" in msg
        assert "disabled_rules" in msg
        assert "enabled_rules" in msg
        assert "disable wins" in msg

    def test_cli_disable_plus_enable_names_both_flags(self) -> None:
        resolved = ResolvedLintConfig.from_dict(
            None,
            {
                "disabled_rules": ("naming/snake-case-fields",),
                "enabled_rules": ("naming/snake-case-fields",),
            },
        )
        warnings = [
            w
            for w in resolved.runtime_warnings
            if w.category == "contradictory_disable_config"
        ]
        assert len(warnings) == 1
        msg = warnings[0].message
        assert "--disable-rule" in msg
        assert "--enable-rule" in msg

    def test_cross_tier_cli_enable_surfaces_no_config_escape_hatch(
        self,
    ) -> None:
        """The cross-tier ``--enable-rule R + pyproject disabled_rules
        ⊃ R`` case is the one most likely to surprise users; the
        message surfaces ``--no-config`` as the escape hatch with the
        caveat that it drops ALL pyproject configuration."""
        resolved = ResolvedLintConfig.from_dict(
            {"disabled_rules": ["naming/snake-case-fields"]},
            {"enabled_rules": ("naming/snake-case-fields",)},
        )
        warnings = [
            w
            for w in resolved.runtime_warnings
            if w.category == "contradictory_disable_config"
        ]
        assert len(warnings) == 1
        msg = warnings[0].message
        assert "--no-config" in msg
        # The caveat must be present so users understand the
        # blast radius of --no-config:
        assert "drops ALL pyproject" in msg

    def test_severity_override_moot_message(self) -> None:
        """``disabled_rules ⊃ R AND [severities] R = "warning"`` →
        the warning explains the severity override is moot."""
        resolved = ResolvedLintConfig.from_dict(
            {
                "disabled_rules": ["naming/snake-case-fields"],
                "severities": {"naming/snake-case-fields": "warning"},
            },
            {},
        )
        warnings = [
            w
            for w in resolved.runtime_warnings
            if w.category == "contradictory_disable_config"
        ]
        assert len(warnings) == 1
        msg = warnings[0].message
        assert "non-'off'" in msg
        assert "has no effect" in msg

    def test_off_severity_plus_disabled_rules_no_warning_idempotent(
        self,
    ) -> None:
        """Both directives are disables — no override, no warning."""
        resolved = ResolvedLintConfig.from_dict(
            {
                "severities": {"naming/snake-case-fields": "off"},
                "disabled_rules": ["naming/snake-case-fields"],
            },
            {},
        )
        assert resolved.runtime_warnings == ()

    def test_warnings_sorted_deterministically_across_multiple_rules(
        self,
    ) -> None:
        """When multiple rule_ids contradict, the warnings emit in
        sorted rule_id order so test fixtures pin a stable sequence."""
        resolved = ResolvedLintConfig.from_dict(
            {
                "disabled_rules": [
                    "naming/snake-case-fields",
                    "imports/unused",
                ],
                "enabled_rules": [
                    "naming/snake-case-fields",
                    "imports/unused",
                ],
            },
            {},
        )
        warnings = [
            w
            for w in resolved.runtime_warnings
            if w.category == "contradictory_disable_config"
        ]
        rule_ids = [w.rule_id for w in warnings]
        assert rule_ids == sorted(rule_ids)




