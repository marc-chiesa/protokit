"""Tests for ``[tool.protokit.lint.severities]`` parsing (D6a U2, R9a).

Covers:

- Happy path: a populated ``severities`` table parses to a frozen
  ``Mapping[str, LintSeverity]`` accessible via ``resolved.severities``.
- Severity-string coercion mirrors ``_coerce_min_severity``:
  case-insensitive, whitespace-tolerant at the input boundary.
- Empty table (``severities = {}``) is valid and produces an empty
  mapping (no override applied).
- Error paths: scalar / list / wrong-value-type / unknown severity
  string all exit 2 with ``error[lint-pyproject-config-invalid]:``
  and name the offending rule_id when applicable.
- The resolved field is a frozen ``MappingProxyType`` per
  ``frozen-dataclass-mutable-fields-need-post-init-snapshot``.
- Empty / whitespace-only keys are rejected (typo-signal protection
  per the source-aware-error-messages learning).

R9a's CLI side-channel (per-rule ``--severity`` flag) is deferred to
a later delivery; D6a pyproject-only behavior is what these tests pin.
"""

from __future__ import annotations

import types

import pytest

from protokit.schema.lint._config import ResolvedLintConfig
from protokit.schema.lint.model import LintSeverity

from .conftest import expect_invalid

# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestSeveritiesHappyPath:
    def test_populated_table_resolves_to_lint_severity_mapping(self) -> None:
        resolved = ResolvedLintConfig.from_dict(
            {
                "severities": {
                    "naming/snake-case-fields": "info",
                    "imports/no-public": "warning",
                    "package/defined": "error",
                },
            },
            {},
        )
        assert (
            resolved.severities["naming/snake-case-fields"]
            is LintSeverity.INFO
        )
        assert (
            resolved.severities["imports/no-public"]
            is LintSeverity.WARNING
        )
        assert resolved.severities["package/defined"] is LintSeverity.ERROR

    def test_empty_table_resolves_to_empty_mapping(self) -> None:
        """``severities = {}`` is explicit empty — valid, indistinguishable
        from omitting the key, but the coercion accepts it so users can
        stage a configuration scaffold.
        """
        resolved = ResolvedLintConfig.from_dict({"severities": {}}, {})
        assert dict(resolved.severities) == {}

    def test_omitted_key_defaults_to_empty(self) -> None:
        """When the pyproject table doesn't set ``severities`` at all,
        the default factory produces an empty mapping (R9a "no
        overrides configured" state).
        """
        resolved = ResolvedLintConfig.from_dict(None, {})
        assert dict(resolved.severities) == {}

    def test_severity_strings_normalized_at_boundary(self) -> None:
        """Per ``normalize-at-input-boundary``: case and whitespace
        in the severity VALUE are handled by the coercion helper,
        not deferred to consumers.
        """
        resolved = ResolvedLintConfig.from_dict(
            {
                "severities": {
                    "naming/foo": "  WARNING  ",
                    "naming/bar": "INFO",
                },
            },
            {},
        )
        assert resolved.severities["naming/foo"] is LintSeverity.WARNING
        assert resolved.severities["naming/bar"] is LintSeverity.INFO

    def test_severity_keys_normalized_at_boundary(self) -> None:
        """Per ``normalize-at-input-boundary`` (mapping-keys extension):
        rule_id KEYS are normalized to lowercase at the coercion
        boundary so the engine's canonical-form lookup
        (``profile.rule_severity_overrides.get(spec.rule_id)`` where
        ``spec.rule_id`` is always lowercase per ``@lint_rule``
        convention) succeeds even when the user typed mixed case in
        pyproject. Without this, a typo like
        ``"Naming/Snake-Case-Fields"`` silently no-ops because the
        stored key never matches the canonical lookup.
        """
        resolved = ResolvedLintConfig.from_dict(
            {
                "severities": {
                    "Naming/Snake-Case-Fields": "info",
                    "  IMPORTS/NO-PUBLIC  ": "error",
                },
            },
            {},
        )
        # Stored under canonical lowercase form, not the user's mixed case.
        assert (
            resolved.severities["naming/snake-case-fields"]
            is LintSeverity.INFO
        )
        assert resolved.severities["imports/no-public"] is LintSeverity.ERROR
        # And the un-normalized forms are NOT keys.
        assert "Naming/Snake-Case-Fields" not in resolved.severities
        assert "  IMPORTS/NO-PUBLIC  " not in resolved.severities


# ---------------------------------------------------------------------------
# Frozen semantics — MappingProxyType + dataclass freeze
# ---------------------------------------------------------------------------


class TestSeveritiesFrozen:
    def test_severities_field_is_mapping_proxy(self) -> None:
        """``__post_init__`` wraps in ``MappingProxyType`` per the
        ``frozen-dataclass-mutable-fields-need-post-init-snapshot`` learning.
        """
        resolved = ResolvedLintConfig.from_dict(
            {"severities": {"naming/foo": "warning"}}, {},
        )
        assert isinstance(resolved.severities, types.MappingProxyType)

    def test_input_mutation_does_not_leak(self) -> None:
        """Per the snapshot learning: mutations on the input dict
        cannot leak through the frozen wrapper. Constructor (not
        from_dict) passes a list-like to demonstrate the defensive
        ``dict()`` copy in ``__post_init__``.
        """
        original = {"naming/foo": LintSeverity.WARNING}
        resolved = ResolvedLintConfig(severities=original)
        original["naming/bar"] = LintSeverity.INFO
        # Resolved should not see the post-construction insertion.
        assert "naming/bar" not in resolved.severities

    def test_mapping_proxy_blocks_direct_mutation(self) -> None:
        resolved = ResolvedLintConfig.from_dict(
            {"severities": {"naming/foo": "warning"}}, {},
        )
        with pytest.raises(TypeError):
            resolved.severities["naming/bar"] = LintSeverity.INFO  # type: ignore[index]


# ---------------------------------------------------------------------------
# Error paths — wrong shape, wrong types
# ---------------------------------------------------------------------------


class TestSeveritiesErrors:
    def test_scalar_value_rejected(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        expect_invalid(
            {"severities": "warning"},
            {},
            capsys,
            substring="severities must be a table",
        )

    def test_list_value_rejected(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        expect_invalid(
            {"severities": ["naming/foo", "warning"]},
            {},
            capsys,
            substring="severities must be a table",
        )

    def test_non_string_severity_value_rejected(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        expect_invalid(
            {"severities": {"naming/foo": 1}},
            {},
            capsys,
            substring="must be a string severity name",
        )

    def test_unknown_severity_value_rejected(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Plan scenario 9: "WARN" is the natural abbreviation a user
        # types expecting "warning" to be accepted — the more useful
        # regression boundary than an implausible string like "fatal".
        expect_invalid(
            {"severities": {"naming/foo": "WARN"}},
            {},
            capsys,
            substring="severity name outside the closed set",
        )

    def test_unknown_severity_names_the_rule_id(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Per the ``source-aware-error-messages`` learning, the error
        message names the rule_id whose value is invalid so the user
        can locate the typo without scanning their whole table.
        """
        expect_invalid(
            {"severities": {"naming/snake-case-fields": "WARN"}},
            {},
            capsys,
            substring="'naming/snake-case-fields'",
        )

    def test_empty_key_rejected(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        expect_invalid(
            {"severities": {"": "warning"}},
            {},
            capsys,
            substring="must be a non-empty rule_id",
        )

    def test_whitespace_only_key_rejected(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        expect_invalid(
            {"severities": {"   ": "warning"}},
            {},
            capsys,
            substring="must be a non-empty rule_id",
        )

    def test_non_string_key_rejected_via_programmatic_dict(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """TOML keys are always strings, but programmatic from_dict
        callers (tests, future internal APIs) may pass non-string
        keys. The defensive isinstance check covers this.
        """
        expect_invalid(
            {"severities": {123: "warning"}},
            {},
            capsys,
            substring="severities key must be a string rule_id",
        )


# ---------------------------------------------------------------------------
# D6f R4 — "off" sentinel interception (KD-1)
# ---------------------------------------------------------------------------


class TestOffSentinelInterception:
    """``"off"`` is accepted as a severity value and intercepted at
    the coercion layer per KD-1.

    The matching rule_id is NOT written into the severities dict
    (so ``LintSeverity`` stays a closed 3-member enum and the SARIF
    formatter ``assert_never`` wire-safety invariant holds); instead
    it is propagated to ``ResolvedLintConfig.disabled_rules`` per
    the KD-1 sentinel propagation contract.
    """

    def test_off_value_does_not_appear_in_severities_dict(self) -> None:
        """The intercepted ``off`` entry is removed from severities
        — ``LintSeverity`` enum stays closed at 3 members."""
        resolved = ResolvedLintConfig.from_dict(
            {"severities": {"naming/snake-case-fields": "off"}}, {},
        )
        assert resolved.severities == {}

    def test_off_value_surfaces_in_unified_disabled_rules(self) -> None:
        """KD-1 propagation contract: off-severity rule_ids land in
        the unified ``ResolvedLintConfig.disabled_rules`` frozenset."""
        resolved = ResolvedLintConfig.from_dict(
            {"severities": {"naming/snake-case-fields": "off"}}, {},
        )
        assert resolved.disabled_rules == frozenset(
            {"naming/snake-case-fields"},
        )

    def test_off_value_case_insensitive(self) -> None:
        """``"OFF"`` / ``"Off"`` are normalized to the sentinel just
        like other severity strings."""
        resolved = ResolvedLintConfig.from_dict(
            {
                "severities": {
                    "naming/a": "OFF",
                    "naming/b": "Off",
                },
            },
            {},
        )
        assert resolved.severities == {}
        assert resolved.disabled_rules == frozenset(
            {"naming/a", "naming/b"},
        )

    def test_off_value_whitespace_tolerated(self) -> None:
        resolved = ResolvedLintConfig.from_dict(
            {"severities": {"naming/foo": "  off  "}}, {},
        )
        assert resolved.disabled_rules == frozenset({"naming/foo"})

    def test_off_mixed_with_non_off_severities(self) -> None:
        """Off-severity rules go to disabled_rules; non-off entries
        stay in severities."""
        resolved = ResolvedLintConfig.from_dict(
            {
                "severities": {
                    "naming/snake-case-fields": "off",
                    "imports/unused": "warning",
                    "package/no-import-cycle": "off",
                },
            },
            {},
        )
        assert resolved.disabled_rules == frozenset(
            {"naming/snake-case-fields", "package/no-import-cycle"},
        )
        assert dict(resolved.severities) == {
            "imports/unused": LintSeverity.WARNING,
        }

    def test_off_rule_id_normalized_at_boundary(self) -> None:
        """Per KD-6, off-rule_id keys are normalized to lowercase
        before being added to the disabled set."""
        resolved = ResolvedLintConfig.from_dict(
            {"severities": {"Naming/Snake-Case-Fields": "off"}}, {},
        )
        assert resolved.disabled_rules == frozenset(
            {"naming/snake-case-fields"},
        )

    def test_off_value_omitted_resolves_to_empty(self) -> None:
        """No ``[severities]`` table → empty disabled_rules from this
        source. Other R9b mechanisms unaffected."""
        resolved = ResolvedLintConfig.from_dict({}, {})
        assert resolved.disabled_rules == frozenset()


class TestCoercedSeveritiesNamedTuple:
    """The new ``_CoercedSeverities`` return shape exposes off ids
    distinctly from non-off severities."""

    def test_coerce_severities_returns_named_tuple(self) -> None:
        """Direct unit test of ``_coerce_severities`` — verifies the
        return shape regardless of from_dict's downstream merging."""
        from protokit.schema.lint._config import _coerce_severities

        result = _coerce_severities(
            {
                "naming/a": "off",
                "naming/b": "warning",
            },
        )
        assert result.severities == {"naming/b": LintSeverity.WARNING}
        assert result.off_rule_ids == frozenset({"naming/a"})

    def test_coerce_severities_unpacking(self) -> None:
        """``_CoercedSeverities`` is a NamedTuple — supports both
        attribute access and tuple unpacking."""
        from protokit.schema.lint._config import _coerce_severities

        severities, off_ids = _coerce_severities(
            {"naming/a": "off", "naming/b": "info"},
        )
        assert severities == {"naming/b": LintSeverity.INFO}
        assert off_ids == frozenset({"naming/a"})
