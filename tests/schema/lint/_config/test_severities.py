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

# ---------------------------------------------------------------------------
# Helpers (mirrors test_schema_validation.py shape)
# ---------------------------------------------------------------------------


_PREFIX: str = "error[lint-pyproject-config-invalid]:"


def _expect_invalid(
    table: dict[str, object],
    cli_overrides: dict[str, object],
    capsys: pytest.CaptureFixture[str],
    *,
    substring: str,
) -> None:
    """Call ``from_dict`` expecting exit 2 with the invalid-prefix message."""
    with pytest.raises(SystemExit) as excinfo:
        ResolvedLintConfig.from_dict(table, cli_overrides)
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert err.startswith(_PREFIX), err
    assert substring in err, err


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
        _expect_invalid(
            {"severities": "warning"},
            {},
            capsys,
            substring="severities must be a table",
        )

    def test_list_value_rejected(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        _expect_invalid(
            {"severities": ["naming/foo", "warning"]},
            {},
            capsys,
            substring="severities must be a table",
        )

    def test_non_string_severity_value_rejected(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        _expect_invalid(
            {"severities": {"naming/foo": 1}},
            {},
            capsys,
            substring="must be a string severity name",
        )

    def test_unknown_severity_value_rejected(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        _expect_invalid(
            {"severities": {"naming/foo": "fatal"}},
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
        _expect_invalid(
            {"severities": {"naming/snake-case-fields": "fatal"}},
            {},
            capsys,
            substring="'naming/snake-case-fields'",
        )

    def test_empty_key_rejected(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        _expect_invalid(
            {"severities": {"": "warning"}},
            {},
            capsys,
            substring="must be a non-empty rule_id",
        )

    def test_whitespace_only_key_rejected(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        _expect_invalid(
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
        _expect_invalid(
            {"severities": {123: "warning"}},
            {},
            capsys,
            substring="severities key must be a string rule_id",
        )
