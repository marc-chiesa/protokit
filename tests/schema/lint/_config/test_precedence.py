"""Tests for ``ResolvedLintConfig.from_dict`` precedence engine (D5 U2).

Covers the precedence rules R11–R14 per the plan's decision matrix:

- ``profile``:      CLI replaces pyproject entirely.
- ``exclude``:      CLI appends to pyproject; ``--no-exclude`` (signalled
                    by an empty CLI override tuple) clears both.
- ``min_severity``: CLI replaces pyproject; per-key source attribution
                    is recorded for R20's three message branches.
- ``max_warnings``: CLI replaces pyproject.
- ``format``:       CLI replaces pyproject.

Plus the multi-profile pyproject case where ``profile = [...]`` lands
multiple profile names that ``LintProfile.compose`` later merges.
"""

from __future__ import annotations

import pytest

from protokit.schema.lint._config import ResolvedLintConfig
from protokit.schema.lint.model import LintSeverity

# ---------------------------------------------------------------------------
# profile precedence (R11-style: CLI replaces pyproject)
# ---------------------------------------------------------------------------


class TestProfilePrecedence:
    def test_only_pyproject_wins_when_cli_absent(self) -> None:
        resolved = ResolvedLintConfig.from_dict(
            {"profile": "strict-naming"}, {},
        )
        assert resolved.profile == ("strict-naming",)

    def test_cli_replaces_pyproject(self) -> None:
        resolved = ResolvedLintConfig.from_dict(
            {"profile": "strict-naming"},
            {"profile": ("default",)},
        )
        # CLI replaces — pyproject's strict-naming is dropped, not merged.
        assert resolved.profile == ("default",)

    def test_multi_profile_pyproject(self) -> None:
        # Multi-profile composition via list-typed pyproject value.
        resolved = ResolvedLintConfig.from_dict(
            {"profile": ["default", "strict-naming"]}, {},
        )
        assert resolved.profile == ("default", "strict-naming")

    def test_scalar_profile_coerced_to_one_tuple(self) -> None:
        resolved = ResolvedLintConfig.from_dict(
            {"profile": "strict"}, {},
        )
        assert resolved.profile == ("strict",)

    def test_default_when_neither_source_sets_profile(self) -> None:
        resolved = ResolvedLintConfig.from_dict(None, {})
        assert resolved.profile == ("default",)

    def test_cli_default_sentinel_passes_through_to_pyproject(self) -> None:
        # cli_overrides["profile"] == None means "CLI did not
        # explicitly set --profile" (the click default applied).
        # In that case pyproject wins.
        resolved = ResolvedLintConfig.from_dict(
            {"profile": "strict"},
            {"profile": None},
        )
        assert resolved.profile == ("strict",)


# ---------------------------------------------------------------------------
# exclude precedence (R13: CLI appends to pyproject; --no-exclude clears)
# ---------------------------------------------------------------------------


class TestExcludePrecedence:
    def test_only_pyproject_wins_when_cli_absent(self) -> None:
        resolved = ResolvedLintConfig.from_dict(
            {"exclude": ["vendor/**"]}, {},
        )
        assert resolved.exclude == ("vendor/**",)

    def test_cli_appends_to_pyproject(self) -> None:
        # R13: CLI exclude patterns append onto pyproject's set.
        resolved = ResolvedLintConfig.from_dict(
            {"exclude": ["vendor/**"]},
            {"exclude": ("third_party/**",)},
        )
        assert resolved.exclude == ("vendor/**", "third_party/**")

    def test_no_exclude_clears_pyproject(self) -> None:
        # R13a-precedence: --no-exclude (signalled by the empty tuple)
        # clears BOTH pyproject and CLI patterns.
        resolved = ResolvedLintConfig.from_dict(
            {"exclude": ["**/*"]},
            {"exclude": ()},
        )
        assert resolved.exclude == ()

    def test_cli_none_means_no_exclude_flag_was_given(self) -> None:
        # `cli_overrides["exclude"] is None` means "no --exclude flag
        # was passed" (different from --no-exclude which uses ()).
        # Pyproject patterns survive.
        resolved = ResolvedLintConfig.from_dict(
            {"exclude": ["vendor/**"]},
            {"exclude": None},
        )
        assert resolved.exclude == ("vendor/**",)

    def test_default_empty_when_neither_source_sets_exclude(self) -> None:
        resolved = ResolvedLintConfig.from_dict(None, {})
        assert resolved.exclude == ()


# ---------------------------------------------------------------------------
# min_severity precedence + R20 source attribution
# ---------------------------------------------------------------------------


class TestMinSeverityPrecedence:
    def test_cli_only_source_attributed_cli(self) -> None:
        resolved = ResolvedLintConfig.from_dict(
            None,
            {"min_severity": LintSeverity.WARNING},
        )
        assert resolved.min_severity is LintSeverity.WARNING
        assert resolved.min_severity_source == "cli"
        assert resolved.pyproject_min_severity is None

    def test_pyproject_only_source_attributed_pyproject(self) -> None:
        resolved = ResolvedLintConfig.from_dict(
            {"min_severity": "warning"}, {},
        )
        assert resolved.min_severity is LintSeverity.WARNING
        assert resolved.min_severity_source == "pyproject"
        # Retained for R20's "both" message branch (U4 consumes this).
        assert resolved.pyproject_min_severity is LintSeverity.WARNING

    def test_both_set_cli_wins_pyproject_retained(self) -> None:
        # R20 "both" branch: CLI is the effective source, but pyproject
        # is retained so U4 can emit the
        # "...(overriding pyproject min_severity=info)" suffix.
        resolved = ResolvedLintConfig.from_dict(
            {"min_severity": "info"},
            {"min_severity": LintSeverity.WARNING},
        )
        assert resolved.min_severity is LintSeverity.WARNING
        assert resolved.min_severity_source == "cli"
        assert resolved.pyproject_min_severity is LintSeverity.INFO

    def test_pyproject_relaxed_cli_restores(self) -> None:
        # pyproject relaxes, CLI restores: resolved=ERROR; the
        # relaxation message should NOT fire (U4 emit logic). Here we
        # just verify the source attribution carries CLI.
        resolved = ResolvedLintConfig.from_dict(
            {"min_severity": "warning"},
            {"min_severity": LintSeverity.ERROR},
        )
        assert resolved.min_severity is LintSeverity.ERROR
        assert resolved.min_severity_source == "cli"
        assert resolved.pyproject_min_severity is LintSeverity.WARNING

    def test_neither_source_default(self) -> None:
        resolved = ResolvedLintConfig.from_dict(None, {})
        assert resolved.min_severity is None
        assert resolved.min_severity_source == "default"
        assert resolved.pyproject_min_severity is None


# ---------------------------------------------------------------------------
# max_warnings precedence (CLI replaces pyproject)
# ---------------------------------------------------------------------------


class TestMaxWarningsPrecedence:
    def test_pyproject_only(self) -> None:
        resolved = ResolvedLintConfig.from_dict(
            {"max_warnings": 5}, {},
        )
        assert resolved.max_warnings == 5

    def test_cli_replaces_pyproject(self) -> None:
        resolved = ResolvedLintConfig.from_dict(
            {"max_warnings": 10},
            {"max_warnings": 0},
        )
        assert resolved.max_warnings == 0

    def test_cli_zero_is_a_real_override(self) -> None:
        # Zero is "fail on any WARNING"; must distinguish from None
        # (the "no gate" sentinel).
        resolved = ResolvedLintConfig.from_dict(None, {"max_warnings": 0})
        assert resolved.max_warnings == 0

    def test_neither_source_none(self) -> None:
        resolved = ResolvedLintConfig.from_dict(None, {})
        assert resolved.max_warnings is None


# ---------------------------------------------------------------------------
# format precedence (CLI replaces pyproject; default "human")
# ---------------------------------------------------------------------------


class TestFormatPrecedence:
    def test_pyproject_only(self) -> None:
        resolved = ResolvedLintConfig.from_dict(
            {"format": "json"}, {},
        )
        assert resolved.format == "json"

    def test_cli_replaces_pyproject(self) -> None:
        resolved = ResolvedLintConfig.from_dict(
            {"format": "json"},
            {"format": "sarif"},
        )
        assert resolved.format == "sarif"

    def test_default_human_when_neither_set(self) -> None:
        resolved = ResolvedLintConfig.from_dict(None, {})
        assert resolved.format == "human"


# ---------------------------------------------------------------------------
# Parametrized matrix: CLI × pyproject for each key
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key,pyproject_value,cli_value,expected_resolved",
    [
        # profile: CLI replaces
        ("profile", "strict", ("default",), ("default",)),
        ("profile", "strict", None, ("strict",)),
        ("profile", None, ("default",), ("default",)),
        ("profile", None, None, ("default",)),
        # max_warnings: CLI replaces
        ("max_warnings", 5, 0, 0),
        ("max_warnings", 5, None, 5),
        ("max_warnings", None, 0, 0),
        ("max_warnings", None, None, None),
        # format: CLI replaces
        ("format", "json", "sarif", "sarif"),
        ("format", "json", None, "json"),
        ("format", None, "sarif", "sarif"),
        ("format", None, None, "human"),
    ],
)
def test_precedence_matrix(
    key: str,
    pyproject_value: object,
    cli_value: object,
    expected_resolved: object,
) -> None:
    """Cross-source precedence matrix for replace-semantics keys."""
    table: dict[str, object] | None = (
        {key: pyproject_value} if pyproject_value is not None else None
    )
    cli_overrides: dict[str, object] = (
        {key: cli_value} if cli_value is not None else {}
    )
    resolved = ResolvedLintConfig.from_dict(table, cli_overrides)
    assert getattr(resolved, key) == expected_resolved
