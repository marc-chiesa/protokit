"""Tests for the ``ResolvedLintConfig`` dataclass shape itself (D5 U2).

Covers:

- **Frozen semantics**: mutation attempts raise ``FrozenInstanceError``.
- **Tuple-snapshot ``__post_init__``**: list inputs become tuples and
  later mutations on the original list do not leak through (per the
  ``frozen-dataclass-mutable-fields-need-post-init-snapshot`` learning).
- **Defaults**: factory-fresh instance has the documented defaults.
- **Field types** match the documented contract (``profile``,
  ``exclude`` as ``tuple[str, ...]``; ``min_severity_source`` as the
  closed ``Literal`` set).
"""

from __future__ import annotations

import dataclasses

import pytest

from protokit.schema.lint._config import ResolvedLintConfig
from protokit.schema.lint.model import LintSeverity

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_factory_fresh_instance_has_documented_defaults(self) -> None:
        resolved = ResolvedLintConfig()
        assert resolved.profile == ("default",)
        assert resolved.exclude == ()
        assert resolved.min_severity is None
        assert resolved.max_warnings is None
        assert resolved.format == "human"
        assert resolved.min_severity_source == "default"
        assert resolved.pyproject_min_severity is None


# ---------------------------------------------------------------------------
# Frozen semantics
# ---------------------------------------------------------------------------


class TestFrozen:
    def test_assignment_raises_frozen_instance_error(self) -> None:
        resolved = ResolvedLintConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            resolved.profile = ("other",)  # type: ignore[misc]

    @pytest.mark.parametrize("field_name", [
        "profile",
        "exclude",
        "min_severity",
        "max_warnings",
        "format",
        "min_severity_source",
        "pyproject_min_severity",
    ])
    def test_assignment_raises(self, field_name: str) -> None:
        # Every field should refuse mutation; this protects against
        # accidental ``field(default_factory=list)`` regressions that
        # would silently re-introduce mutability. Parametrized so each
        # field gets its own test node (failures localize cleanly to
        # the specific field that regressed, instead of the test
        # stopping at the first AssertionError in a shared loop).
        resolved = ResolvedLintConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            # ``setattr`` is the same as ``resolved.<name> = ...``
            # for the frozen-dataclass check; using it lets us
            # parametrize the assertion cleanly.
            setattr(resolved, field_name, None)


# ---------------------------------------------------------------------------
# Tuple-snapshot semantics (frozen-dataclass-mutable-fields learning)
# ---------------------------------------------------------------------------


class TestTupleSnapshot:
    def test_list_profile_input_coerced_to_tuple(self) -> None:
        # Passing a list directly via the constructor (not from_dict)
        # should still tuple-snapshot in __post_init__.
        original = ["a", "b"]
        resolved = ResolvedLintConfig(profile=original)  # type: ignore[arg-type]
        assert resolved.profile == ("a", "b")
        assert isinstance(resolved.profile, tuple)

    def test_list_exclude_input_coerced_to_tuple(self) -> None:
        original = ["vendor/**", "third_party/**"]
        resolved = ResolvedLintConfig(exclude=original)  # type: ignore[arg-type]
        assert resolved.exclude == ("vendor/**", "third_party/**")
        assert isinstance(resolved.exclude, tuple)

    def test_post_mutation_of_input_list_does_not_leak(self) -> None:
        # Per the frozen-dataclass-mutable-fields learning: snapshotting
        # via tuple() means later mutations on the input list cannot
        # leak through the frozen wrapper.
        original = ["a", "b"]
        resolved = ResolvedLintConfig(profile=original)  # type: ignore[arg-type]
        original.append("c")
        assert resolved.profile == ("a", "b")


# ---------------------------------------------------------------------------
# Round-trip with from_dict
# ---------------------------------------------------------------------------


class TestFromDictRoundTrip:
    def test_all_five_keys_at_valid_types(self) -> None:
        # Happy path: every key set + all valid types.
        resolved = ResolvedLintConfig.from_dict(
            {
                "profile": ["default", "strict"],
                "exclude": ["vendor/**"],
                "min_severity": "warning",
                "max_warnings": 5,
                "format": "json",
            },
            {},
        )
        assert resolved.profile == ("default", "strict")
        assert resolved.exclude == ("vendor/**",)
        assert resolved.min_severity is LintSeverity.WARNING
        assert resolved.max_warnings == 5
        assert resolved.format == "json"
        assert resolved.min_severity_source == "pyproject"
        assert resolved.pyproject_min_severity is LintSeverity.WARNING

    def test_only_one_pyproject_key(self) -> None:
        # Sparse table — only one key set; others fall through to
        # documented defaults.
        resolved = ResolvedLintConfig.from_dict({"profile": "strict"}, {})
        assert resolved.profile == ("strict",)
        assert resolved.exclude == ()
        assert resolved.min_severity is None
        assert resolved.max_warnings is None
        assert resolved.format == "human"

    def test_strings_normalized_at_boundary(self) -> None:
        # normalize-at-input-boundary: case + whitespace handled in
        # the coerce helpers, not deferred to consumers.
        resolved = ResolvedLintConfig.from_dict(
            {
                "profile": "  StrictNaming  ",
                "min_severity": " WARNING ",
                "format": " JSON ",
            },
            {},
        )
        assert resolved.profile == ("strictnaming",)
        assert resolved.min_severity is LintSeverity.WARNING
        assert resolved.format == "json"
