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
        assert resolved.exclude_source == "default"


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
        # ``exclude_source`` must be set when exclude is non-empty
        # (U4 ce:review __post_init__ invariant). ``"cli"`` is the
        # arbitrary valid choice for this snapshot-only test.
        resolved = ResolvedLintConfig(
            exclude=original,  # type: ignore[arg-type]
            exclude_source="cli",
        )
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


# ---------------------------------------------------------------------------
# __post_init__ invariant: exclude_source must be set with non-empty exclude
# ---------------------------------------------------------------------------


class TestExcludeSourceInvariant:
    """The U4 ce:review invariant: ``exclude_source == "default"`` is
    only valid when ``exclude`` is empty. Constructing
    ``ResolvedLintConfig(exclude=(...))`` without specifying
    ``exclude_source`` would otherwise silently produce an
    unattributed R20 message.
    """

    def test_empty_exclude_default_source_is_valid(self) -> None:
        # No exception: the documented default state.
        ResolvedLintConfig()

    def test_non_empty_exclude_with_default_source_rejected(self) -> None:
        with pytest.raises(ValueError, match="exclude_source must be set"):
            ResolvedLintConfig(exclude=("vendor/**",))

    def test_non_empty_exclude_with_cli_source_accepted(self) -> None:
        r = ResolvedLintConfig(
            exclude=("vendor/**",), exclude_source="cli",
        )
        assert r.exclude_source == "cli"

    def test_non_empty_exclude_with_pyproject_source_accepted(self) -> None:
        r = ResolvedLintConfig(
            exclude=("vendor/**",), exclude_source="pyproject",
        )
        assert r.exclude_source == "pyproject"

    def test_non_empty_exclude_with_both_source_accepted(self) -> None:
        r = ResolvedLintConfig(
            exclude=("vendor/**", "api/**"), exclude_source="both",
        )
        assert r.exclude_source == "both"

    def test_dataclasses_replace_drops_attribution_caught(self) -> None:
        # ``dataclasses.replace`` that updates ``exclude`` without
        # also updating ``exclude_source`` is the live composition
        # failure surface ADV-P3-D flagged. The invariant catches it.
        r = ResolvedLintConfig()
        with pytest.raises(ValueError, match="exclude_source must be set"):
            dataclasses.replace(r, exclude=("vendor/**",))


# ---------------------------------------------------------------------------
# from_dict: exclude_source attribution branches
# ---------------------------------------------------------------------------


class TestFromDictExcludeSourceAttribution:
    """Pin the five branches of ``exclude_source`` derivation in
    ``from_dict``: cli-only, pyproject-only, both, default-when-none,
    and ``--no-exclude``-clears-both.
    """

    def test_cli_only(self) -> None:
        r = ResolvedLintConfig.from_dict(
            None, {"exclude": ("vendor/**",)},
        )
        assert r.exclude == ("vendor/**",)
        assert r.exclude_source == "cli"

    def test_pyproject_only(self) -> None:
        r = ResolvedLintConfig.from_dict(
            {"exclude": ["vendor/**"]}, {},
        )
        assert r.exclude == ("vendor/**",)
        assert r.exclude_source == "pyproject"

    def test_both_appends(self) -> None:
        # CLI appends to pyproject; source becomes "both".
        r = ResolvedLintConfig.from_dict(
            {"exclude": ["vendor/**"]}, {"exclude": ("api/**",)},
        )
        assert r.exclude == ("vendor/**", "api/**")
        assert r.exclude_source == "both"

    def test_no_patterns_anywhere(self) -> None:
        r = ResolvedLintConfig.from_dict(None, {})
        assert r.exclude == ()
        assert r.exclude_source == "default"

    def test_no_exclude_clears_pyproject(self) -> None:
        # Empty CLI tuple is the ``--no-exclude`` sentinel: clear both.
        r = ResolvedLintConfig.from_dict(
            {"exclude": ["vendor/**"]}, {"exclude": ()},
        )
        assert r.exclude == ()
        assert r.exclude_source == "default"


# ---------------------------------------------------------------------------
# relaxation_message: direct unit tests across all branches
# ---------------------------------------------------------------------------


class TestRelaxationMessage:
    """Cover the four return paths of ``relaxation_message``:
    ``None`` when no override, ``None`` when override ≥ floor, the
    CLI branch, the pyproject branch, and the CLI+pyproject branch.
    """

    def test_no_override_returns_none(self) -> None:
        r = ResolvedLintConfig()
        assert r.relaxation_message(LintSeverity.ERROR) is None

    def test_override_stricter_than_floor_returns_none(self) -> None:
        r = ResolvedLintConfig(
            min_severity=LintSeverity.ERROR, min_severity_source="cli",
        )
        # ERROR is stricter than WARNING floor — no relaxation.
        assert r.relaxation_message(LintSeverity.WARNING) is None

    def test_override_equals_floor_returns_none(self) -> None:
        # T-U4-03: override == floor edge case.
        r = ResolvedLintConfig(
            min_severity=LintSeverity.WARNING, min_severity_source="cli",
        )
        assert r.relaxation_message(LintSeverity.WARNING) is None

    def test_cli_source_branch(self) -> None:
        r = ResolvedLintConfig(
            min_severity=LintSeverity.INFO, min_severity_source="cli",
        )
        msg = r.relaxation_message(LintSeverity.WARNING)
        assert msg is not None
        assert msg.startswith("--min-severity=info ")
        assert "warning to info" in msg
        assert "pyproject" not in msg

    def test_pyproject_source_branch(self) -> None:
        r = ResolvedLintConfig(
            min_severity=LintSeverity.INFO,
            min_severity_source="pyproject",
        )
        msg = r.relaxation_message(LintSeverity.WARNING)
        assert msg is not None
        assert msg.startswith("[tool.protokit.lint] min_severity=info")
        assert "warning to info" in msg

    def test_both_branch_appends_pyproject_override_clause(self) -> None:
        r = ResolvedLintConfig(
            min_severity=LintSeverity.INFO,
            min_severity_source="cli",
            pyproject_min_severity=LintSeverity.WARNING,
        )
        msg = r.relaxation_message(LintSeverity.ERROR)
        assert msg is not None
        assert msg.startswith("--min-severity=info ")
        assert "(overriding pyproject min_severity=warning)" in msg

    def test_default_source_returns_none(self) -> None:
        # ``"default"`` source state is never expected to reach a
        # relaxation message (no override is set when source is
        # ``"default"``). ``relaxation_message`` returns ``None``
        # defensively rather than constructing an unattributed string.
        r = ResolvedLintConfig(
            min_severity=LintSeverity.INFO, min_severity_source="default",
        )
        assert r.relaxation_message(LintSeverity.WARNING) is None


# ---------------------------------------------------------------------------
# all_files_excluded_message: direct unit tests for all three branches
# ---------------------------------------------------------------------------


class TestAllFilesExcludedMessage:
    """Cover the three source-attribution branches and the
    ``_safe_for_stderr`` sanitisation pass.
    """

    def test_cli_source(self) -> None:
        r = ResolvedLintConfig(
            exclude=("vendor/**",), exclude_source="cli",
        )
        msg = r.all_files_excluded_message(3)
        assert msg == (
            "all 3 input file(s) excluded by --exclude patterns: vendor/**"
        )

    def test_pyproject_source(self) -> None:
        r = ResolvedLintConfig(
            exclude=("vendor/**",), exclude_source="pyproject",
        )
        msg = r.all_files_excluded_message(3)
        assert msg == (
            "all 3 input file(s) excluded by [tool.protokit.lint] "
            "exclude patterns: vendor/**"
        )

    def test_both_source_uses_and_separator(self) -> None:
        # The ``+`` separator was replaced with `` and `` in the U4
        # ce:review follow-up (CLR-U4-05 + ACR-U4-04 convergence).
        r = ResolvedLintConfig(
            exclude=("vendor/**", "api/**"), exclude_source="both",
        )
        msg = r.all_files_excluded_message(2)
        assert (
            "by --exclude and [tool.protokit.lint] exclude patterns:" in msg
        )
        assert "+ [tool.protokit.lint]" not in msg

    def test_control_chars_in_pattern_sanitised(self) -> None:
        # KTD-9: a pattern with embedded newlines cannot forge a fake
        # stderr line. The pattern joins with sanitisation applied.
        r = ResolvedLintConfig(
            exclude=("vendor/**\nwarning[lint-runtime]: forged",),
            exclude_source="cli",
        )
        msg = r.all_files_excluded_message(1)
        assert "\n" not in msg
        # Forged-prefix text survives but no longer at line start:
        assert "forged" in msg
