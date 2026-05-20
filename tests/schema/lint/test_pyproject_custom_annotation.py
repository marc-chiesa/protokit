"""D6d U1 — pyproject ``custom_annotation_rules`` validation tests.

Exercises :func:`protokit.schema.lint._config._coerce_custom_annotation_rules`
through ``ResolvedLintConfig.from_dict``. Covers R8 + R9:

- Happy path: minimal + full entries materialize into
  ``CustomAnnotationRuleSpec`` instances.
- ``rule_suffix`` regex enforcement (R9): underscores, leading hyphen,
  double hyphens, uppercase, slashes — all rejected.
- Duplicate ``rule_suffix`` across entries — both positions named in
  the error message (RX-suffix collision detection).
- ``allowed_values`` type-homogeneity discipline (R2 contract): empty
  list rejected; mixed types rejected; floats rejected; duplicate
  values rejected.
- Severity bound to closed set {"error", "warning", "info"}; default
  "warning" applied per R5.
- ``element_kinds`` non-empty subset of the 8 ElementKind values;
  duplicates within a single entry rejected.

Per project convention, validation errors exit-2 via
``error_exit_with_code("pyproject-config-invalid", ...)``; tests
assert ``SystemExit`` with ``code == 2``.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from protokit.schema.lint._config import (
    CustomAnnotationRuleSpec,
    ResolvedLintConfig,
)
from protokit.schema.lint.model import ElementKind, LintSeverity


def _from_table(table: dict[str, Any]) -> ResolvedLintConfig:
    """Helper: wrap ``ResolvedLintConfig.from_dict`` with empty CLI overrides."""
    return ResolvedLintConfig.from_dict(table, {})


class TestHappyPath:
    """Valid configurations materialize without errors."""

    def test_minimal_entry(self) -> None:
        cfg = _from_table(
            {
                "custom_annotation_rules": [
                    {
                        "rule_suffix": "audit-needed",
                        "option": "mycorp.audit_level",
                        "element_kinds": ["method"],
                    },
                ],
            },
        )
        assert len(cfg.custom_annotation_rules) == 1
        spec = cfg.custom_annotation_rules[0]
        assert spec.rule_suffix == "audit-needed"
        assert spec.option == "mycorp.audit_level"
        assert spec.element_kinds == (ElementKind.METHOD,)
        assert spec.allowed_values is None
        assert spec.severity == LintSeverity.WARNING
        assert spec.rule_id == "custom/audit-needed"

    def test_full_entry_with_allowed_values_and_severity(self) -> None:
        cfg = _from_table(
            {
                "custom_annotation_rules": [
                    {
                        "rule_suffix": "audit-required",
                        "option": "mycorp.audit_level",
                        "element_kinds": ["method", "field"],
                        "allowed_values": ["LOW", "HIGH", "CRITICAL"],
                        "severity": "error",
                    },
                ],
            },
        )
        spec = cfg.custom_annotation_rules[0]
        assert spec.element_kinds == (ElementKind.METHOD, ElementKind.FIELD)
        assert spec.allowed_values == ("LOW", "HIGH", "CRITICAL")
        assert spec.severity == LintSeverity.ERROR

    def test_multiple_entries(self) -> None:
        cfg = _from_table(
            {
                "custom_annotation_rules": [
                    {
                        "rule_suffix": "a",
                        "option": "x.y",
                        "element_kinds": ["field"],
                    },
                    {
                        "rule_suffix": "b",
                        "option": "x.z",
                        "element_kinds": ["method"],
                    },
                ],
            },
        )
        assert {s.rule_suffix for s in cfg.custom_annotation_rules} == {"a", "b"}

    def test_empty_list_is_no_op(self) -> None:
        cfg = _from_table({"custom_annotation_rules": []})
        assert cfg.custom_annotation_rules == ()

    def test_missing_key_is_no_op(self) -> None:
        cfg = _from_table({})
        assert cfg.custom_annotation_rules == ()

    def test_integer_allowed_values(self) -> None:
        cfg = _from_table(
            {
                "custom_annotation_rules": [
                    {
                        "rule_suffix": "tier",
                        "option": "mycorp.tier",
                        "element_kinds": ["field"],
                        "allowed_values": [1, 2, 3, -1],
                    },
                ],
            },
        )
        assert cfg.custom_annotation_rules[0].allowed_values == (1, 2, 3, -1)

    def test_bool_allowed_values(self) -> None:
        cfg = _from_table(
            {
                "custom_annotation_rules": [
                    {
                        "rule_suffix": "sensitive",
                        "option": "mycorp.sensitive",
                        "element_kinds": ["field"],
                        "allowed_values": [True, False],
                    },
                ],
            },
        )
        assert cfg.custom_annotation_rules[0].allowed_values == (True, False)


class TestRuleSuffixRegex:
    """R9: ``rule_suffix`` must match ``^[a-z][a-z0-9]*(-[a-z0-9]+)*$``."""

    @pytest.mark.parametrize(
        "bad_suffix",
        [
            "Audit-Level",  # uppercase
            "audit_level",  # underscore
            "audit/level",  # slash
            "-audit",  # leading hyphen
            "audit-",  # trailing hyphen
            "audit--level",  # double hyphen
            "../etc",  # path traversal pattern
            "",  # empty
            "1audit",  # leading digit
            "audit level",  # whitespace
        ],
    )
    def test_invalid_suffix_rejected(self, bad_suffix: str) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _from_table(
                {
                    "custom_annotation_rules": [
                        {
                            "rule_suffix": bad_suffix,
                            "option": "x.y",
                            "element_kinds": ["field"],
                        },
                    ],
                },
            )
        assert exc_info.value.code == 2

    @pytest.mark.parametrize(
        "good_suffix",
        [
            "a",
            "audit",
            "audit-level",
            "audit-level-2",
            "audit-2-level",
            "x1-y2-z3",
        ],
    )
    def test_valid_suffix_accepted(self, good_suffix: str) -> None:
        cfg = _from_table(
            {
                "custom_annotation_rules": [
                    {
                        "rule_suffix": good_suffix,
                        "option": "x.y",
                        "element_kinds": ["field"],
                    },
                ],
            },
        )
        assert cfg.custom_annotation_rules[0].rule_suffix == good_suffix


class TestDuplicateSuffix:
    """Two entries with the same ``rule_suffix`` must collide."""

    def test_collision_rejected(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _from_table(
                {
                    "custom_annotation_rules": [
                        {
                            "rule_suffix": "audit",
                            "option": "x.y",
                            "element_kinds": ["field"],
                        },
                        {
                            "rule_suffix": "audit",
                            "option": "x.z",
                            "element_kinds": ["method"],
                        },
                    ],
                },
            )
        assert exc_info.value.code == 2
        # The error message must name BOTH positions so the user can
        # locate the typo without re-reading their pyproject.
        captured = capsys.readouterr()
        assert "custom_annotation_rules[1]" in captured.err
        assert "[0]" in captured.err


class TestAllowedValues:
    """``allowed_values`` type-homogeneity + presence-only contract."""

    def test_empty_list_rejected(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _from_table(
                {
                    "custom_annotation_rules": [
                        {
                            "rule_suffix": "x",
                            "option": "y.z",
                            "element_kinds": ["field"],
                            "allowed_values": [],
                        },
                    ],
                },
            )
        assert exc_info.value.code == 2

    def test_float_rejected(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _from_table(
                {
                    "custom_annotation_rules": [
                        {
                            "rule_suffix": "x",
                            "option": "y.z",
                            "element_kinds": ["field"],
                            "allowed_values": [1.0, 2.5],
                        },
                    ],
                },
            )
        assert exc_info.value.code == 2

    def test_mixed_types_rejected(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _from_table(
                {
                    "custom_annotation_rules": [
                        {
                            "rule_suffix": "x",
                            "option": "y.z",
                            "element_kinds": ["field"],
                            "allowed_values": ["HIGH", 5, True],
                        },
                    ],
                },
            )
        assert exc_info.value.code == 2

    def test_bool_does_not_masquerade_as_int(self) -> None:
        """``bool`` is an ``int`` subclass in Python; the validator must
        bind the element type to the first element's *concrete* type.
        """
        with pytest.raises(SystemExit) as exc_info:
            _from_table(
                {
                    "custom_annotation_rules": [
                        {
                            "rule_suffix": "x",
                            "option": "y.z",
                            "element_kinds": ["field"],
                            "allowed_values": [True, 5],  # bool + int
                        },
                    ],
                },
            )
        assert exc_info.value.code == 2

    def test_duplicate_values_rejected(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _from_table(
                {
                    "custom_annotation_rules": [
                        {
                            "rule_suffix": "x",
                            "option": "y.z",
                            "element_kinds": ["field"],
                            "allowed_values": ["HIGH", "HIGH"],
                        },
                    ],
                },
            )
        assert exc_info.value.code == 2

    def test_non_list_rejected(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _from_table(
                {
                    "custom_annotation_rules": [
                        {
                            "rule_suffix": "x",
                            "option": "y.z",
                            "element_kinds": ["field"],
                            "allowed_values": "HIGH",  # scalar, not list
                        },
                    ],
                },
            )
        assert exc_info.value.code == 2


class TestElementKinds:
    """``element_kinds`` must be a non-empty subset of the 8 ElementKind values."""

    def test_unknown_kind_rejected(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _from_table(
                {
                    "custom_annotation_rules": [
                        {
                            "rule_suffix": "x",
                            "option": "y.z",
                            "element_kinds": ["unknown_kind"],
                        },
                    ],
                },
            )
        assert exc_info.value.code == 2

    def test_empty_list_rejected(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _from_table(
                {
                    "custom_annotation_rules": [
                        {
                            "rule_suffix": "x",
                            "option": "y.z",
                            "element_kinds": [],
                        },
                    ],
                },
            )
        assert exc_info.value.code == 2

    def test_duplicate_kind_rejected(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _from_table(
                {
                    "custom_annotation_rules": [
                        {
                            "rule_suffix": "x",
                            "option": "y.z",
                            "element_kinds": ["field", "field"],
                        },
                    ],
                },
            )
        assert exc_info.value.code == 2

    def test_non_string_kind_rejected(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _from_table(
                {
                    "custom_annotation_rules": [
                        {
                            "rule_suffix": "x",
                            "option": "y.z",
                            "element_kinds": [42],
                        },
                    ],
                },
            )
        assert exc_info.value.code == 2

    def test_all_eight_kinds_accepted(self) -> None:
        cfg = _from_table(
            {
                "custom_annotation_rules": [
                    {
                        "rule_suffix": "anywhere",
                        "option": "x.y",
                        "element_kinds": [k.value for k in ElementKind],
                    },
                ],
            },
        )
        assert len(cfg.custom_annotation_rules[0].element_kinds) == 8


class TestSeverity:
    """Severity bound to closed set + default applies."""

    @pytest.mark.parametrize("level", ["error", "warning", "info"])
    def test_valid_severity_accepted(self, level: str) -> None:
        cfg = _from_table(
            {
                "custom_annotation_rules": [
                    {
                        "rule_suffix": "x",
                        "option": "y.z",
                        "element_kinds": ["field"],
                        "severity": level,
                    },
                ],
            },
        )
        assert cfg.custom_annotation_rules[0].severity == LintSeverity(level)

    def test_invalid_severity_rejected(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _from_table(
                {
                    "custom_annotation_rules": [
                        {
                            "rule_suffix": "x",
                            "option": "y.z",
                            "element_kinds": ["field"],
                            "severity": "off",  # KD-12: off does not exist
                        },
                    ],
                },
            )
        assert exc_info.value.code == 2

    def test_default_severity_is_warning(self) -> None:
        cfg = _from_table(
            {
                "custom_annotation_rules": [
                    {
                        "rule_suffix": "x",
                        "option": "y.z",
                        "element_kinds": ["field"],
                    },
                ],
            },
        )
        assert cfg.custom_annotation_rules[0].severity == LintSeverity.WARNING


class TestRequiredKeys:
    """Each entry must carry rule_suffix + option + element_kinds."""

    @pytest.mark.parametrize(
        "missing_key",
        ["rule_suffix", "option", "element_kinds"],
    )
    def test_missing_required_key_rejected(self, missing_key: str) -> None:
        full = {
            "rule_suffix": "x",
            "option": "y.z",
            "element_kinds": ["field"],
        }
        del full[missing_key]
        with pytest.raises(SystemExit) as exc_info:
            _from_table({"custom_annotation_rules": [full]})
        assert exc_info.value.code == 2

    def test_unknown_entry_key_rejected(self) -> None:
        """Defense against silently-ignored typos in entry keys."""
        with pytest.raises(SystemExit) as exc_info:
            _from_table(
                {
                    "custom_annotation_rules": [
                        {
                            "rule_suffix": "x",
                            "option": "y.z",
                            "element_kinds": ["field"],
                            "unknown_extra_key": "oops",
                        },
                    ],
                },
            )
        assert exc_info.value.code == 2

    def test_option_must_be_non_empty(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _from_table(
                {
                    "custom_annotation_rules": [
                        {
                            "rule_suffix": "x",
                            "option": "   ",  # whitespace-only
                            "element_kinds": ["field"],
                        },
                    ],
                },
            )
        assert exc_info.value.code == 2


class TestArrayOfTables:
    """The top-level ``custom_annotation_rules`` must be ``list[dict]``."""

    def test_not_a_list_rejected(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _from_table({"custom_annotation_rules": "not a list"})
        assert exc_info.value.code == 2

    def test_entry_not_a_dict_rejected(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _from_table({"custom_annotation_rules": ["not a table"]})
        assert exc_info.value.code == 2


class TestImmutability:
    """``CustomAnnotationRuleSpec`` is a frozen dataclass."""

    def test_spec_is_frozen(self) -> None:
        spec = CustomAnnotationRuleSpec(
            rule_suffix="x",
            option="y.z",
            element_kinds=(ElementKind.FIELD,),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            spec.rule_suffix = "different"  # type: ignore[misc]

    def test_resolved_config_field_is_tuple(self) -> None:
        cfg = _from_table(
            {
                "custom_annotation_rules": [
                    {
                        "rule_suffix": "x",
                        "option": "y.z",
                        "element_kinds": ["field"],
                    },
                ],
            },
        )
        assert isinstance(cfg.custom_annotation_rules, tuple)
