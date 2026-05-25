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
        # D6a U2 — new fields documented in the dataclass field
        # declarations. ``severities`` is empty (no overrides
        # configured) and ``no_builtin_rules`` is False (BUILTIN_PACKS
        # auto-load proceeds). The empty severities mapping is wrapped
        # by ``__post_init__`` in MappingProxyType.
        assert dict(resolved.severities) == {}
        assert resolved.no_builtin_rules is False


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
        "severities",  # D6a U2 R9a
        "no_builtin_rules",  # D6a U2 R9c
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

    def test_all_seven_keys_at_valid_types(self) -> None:
        # D6a U2 cross-key integration: all 7 _ALLOWED_KEYS set together
        # in one pyproject table. Pins the interaction between the
        # __post_init__ snapshot chain (profile tuple → exclude tuple →
        # severities MappingProxyType) and the exclude_source invariant
        # (non-empty exclude forces exclude_source != "default").
        # A regression in any one coercion helper or in the from_dict
        # precedence wiring surfaces here as a single-test failure.
        resolved = ResolvedLintConfig.from_dict(
            {
                "profile": "basic",
                "exclude": ["vendor/**"],
                "min_severity": "warning",
                "max_warnings": 5,
                "format": "json",
                "severities": {
                    "naming/snake-case-fields": "info",
                    "imports/no-public": "error",
                },
                "no_builtin_rules": True,
            },
            {},
        )
        # Profile aliased: "basic" → "recommended"
        assert resolved.profile == ("recommended",)
        assert resolved.exclude == ("vendor/**",)
        assert resolved.exclude_source == "pyproject"
        assert resolved.min_severity is LintSeverity.WARNING
        assert resolved.max_warnings == 5
        assert resolved.format == "json"
        # Severities normalized at the boundary (D6a U2 ce:review F1):
        # rule_id keys stored lowercase to match @lint_rule convention.
        assert (
            resolved.severities["naming/snake-case-fields"]
            is LintSeverity.INFO
        )
        assert resolved.severities["imports/no-public"] is LintSeverity.ERROR
        assert resolved.no_builtin_rules is True

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


# ---------------------------------------------------------------------------
# D6f GAP 4: __post_init__ paired-field invariant for R8b warnings
# ---------------------------------------------------------------------------


class TestR8bPairedFieldInvariant:
    """D6f GAP 4: every R8b contradictory_disable_config warning's
    rule_id must be present in ``disabled_rules`` or ``enabled_rules``.
    Catches ``dataclasses.replace()`` callers who mutate the disable/
    enable sets without refreshing ``runtime_warnings``.
    """

    def test_valid_r8b_warning_with_matching_disabled_rule_passes(
        self,
    ) -> None:
        """A contradictory_disable_config warning whose rule_id is in
        ``disabled_rules`` is valid — no ValueError raised."""
        from protokit.schema.lint.model import LintRuntimeWarning
        resolved = ResolvedLintConfig(
            disabled_rules=frozenset({"naming/snake-case-fields"}),
            enabled_rules=frozenset(),
            runtime_warnings=(
                LintRuntimeWarning(
                    category="contradictory_disable_config",
                    rule_id="naming/snake-case-fields",
                    message="disabled by X; enabled by Y; disable wins.",
                ),
            ),
        )
        # Should not raise
        assert resolved.disabled_rules == frozenset({"naming/snake-case-fields"})

    def test_stale_r8b_warning_after_replace_raises_value_error(
        self,
    ) -> None:
        """Using ``dataclasses.replace(resolved, disabled_rules=frozenset())``
        to clear disabled_rules while keeping a stale R8b warning raises
        ValueError per the GAP 4 invariant guard."""
        from protokit.schema.lint.model import LintRuntimeWarning
        # Construct a valid resolved config (R8b warning + matching disabled).
        resolved = ResolvedLintConfig(
            disabled_rules=frozenset({"naming/snake-case-fields"}),
            enabled_rules=frozenset(),
            runtime_warnings=(
                LintRuntimeWarning(
                    category="contradictory_disable_config",
                    rule_id="naming/snake-case-fields",
                    message="disabled by X; enabled by Y; disable wins.",
                ),
            ),
        )
        # Now clear disabled_rules via dataclasses.replace WITHOUT
        # refreshing runtime_warnings — this leaves a stale R8b warning.
        with pytest.raises(ValueError, match="contradictory_disable_config"):
            dataclasses.replace(resolved, disabled_rules=frozenset())

    def test_r8b_warning_with_matching_enabled_rule_passes(
        self,
    ) -> None:
        """A contradictory_disable_config warning whose rule_id appears
        in ``enabled_rules`` (not disabled_rules) is also valid."""
        from protokit.schema.lint.model import LintRuntimeWarning
        # R8b fires when enabled_rules and disabled_rules overlap;
        # the rule_id is in BOTH sets. After resolution disabled_rules
        # wins (polarity-first), but enabled_rules still records the
        # intent — the warning's rule_id must be in at least one.
        resolved = ResolvedLintConfig(
            disabled_rules=frozenset({"naming/snake-case-fields"}),
            enabled_rules=frozenset({"naming/snake-case-fields"}),
            runtime_warnings=(
                LintRuntimeWarning(
                    category="contradictory_disable_config",
                    rule_id="naming/snake-case-fields",
                    message="disabled by X; enabled by Y; disable wins.",
                ),
            ),
        )
        # Should not raise — rule_id is in both sets
        assert "naming/snake-case-fields" in resolved.disabled_rules

    def test_non_r8b_warning_with_any_rule_id_passes(
        self,
    ) -> None:
        """Non-contradictory_disable_config categories are not subject
        to the paired-field invariant check."""
        from protokit.schema.lint.model import LintRuntimeWarning
        # An unloaded_rule warning with no disabled/enabled rules — valid.
        resolved = ResolvedLintConfig(
            runtime_warnings=(
                LintRuntimeWarning(
                    category="unloaded_rule",
                    rule_id="naming/never-registered",
                    message="rule not loaded",
                ),
            ),
        )
        # Should not raise
        assert len(resolved.runtime_warnings) == 1
