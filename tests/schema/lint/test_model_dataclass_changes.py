"""Tests for the D5 U3 atomic LintRuntimeWarning dataclass change.

Covers:

- **Literal extension** from 2 → 4 → 5 → 6 → 7 categories:
  ``rule_exception``, ``unloaded_rule`` (engine-emitted), plus
  ``min_severity_relaxed`` and ``all_files_excluded`` (D5 U3/U4,
  CLI-emitted), plus ``severities_unloaded_rule`` (D6b U5,
  CLI-emitted with rule_id populated — closes D6a U9 KTD-2
  accepted tradeoff), plus ``custom_annotation_extension_unresolved``
  (D6d U1, engine-emitted with rule_id populated for synthetic
  ``custom/<suffix>`` rules), plus ``extension_unresolved``
  (D6d U2, engine-emitted with rule_id populated for built-in
  option-aware rules whose depended-on extension is absent from
  the compile pool).
- ``rule_id: str`` → ``rule_id: str | None`` widening (BREAKING per
  R18/R18a). The five rule-scoped categories
  (``rule_exception``, ``unloaded_rule``,
  ``severities_unloaded_rule``,
  ``custom_annotation_extension_unresolved``,
  ``extension_unresolved``) continue to populate ``rule_id`` with a
  non-None string at every emit site; only the two non-rule-scoped
  CLI-emitted categories construct with ``rule_id=None``.
- Frozen-dataclass mutation discipline still enforced for every
  field across all seven categories.
- Field-population invariants per the docstring table (rule_id is
  None ↔ category is one of the two non-rule-scoped CLI-emitted
  categories).

These tests pin the BREAKING wire-format change so D6+ consumers
that iterate ``w.rule_id`` see a regression if the type widens
further or the Literal set drifts.
"""

from __future__ import annotations

import dataclasses
import typing

import pytest

from protokit.schema.lint.model import LintRuntimeWarning

# ---------------------------------------------------------------------------
# Literal extension
# ---------------------------------------------------------------------------


class TestCategoryLiteral:
    def test_literal_lists_all_nine_categories(self) -> None:
        """The Literal annotation must enumerate exactly 9 category
        names. A drift to 8 or 10 indicates an accidental break in the
        category contract that this test catches at import time.

        D6d U1 added the sixth category
        ``custom_annotation_extension_unresolved`` (engine-emitted
        when a synthetic ``custom/<suffix>`` rule's configured
        ``option`` is not a registered extension in the compile pool);
        bumped ``_LINT_JSON_SCHEMA_VERSION`` ``"0.3"`` → ``"0.4"``.

        D6d U2 added the seventh category ``extension_unresolved``
        (engine-emitted when a BUILT-IN option-aware rule's
        depended-on extension is absent from the compile pool, e.g.,
        ``options/field-behavior-consistent`` linting protos that
        don't include ``google/api/field_behavior.proto``); bumped
        ``_LINT_JSON_SCHEMA_VERSION`` ``"0.4"`` → ``"0.5"`` per the
        closed-Literal-discriminator bump contract at
        ``_builtin_lint.py:227-312``.

        D6f U2 added the eighth and ninth categories
        ``contradictory_disable_config`` (CLI-emitted from
        ``ResolvedLintConfig.from_dict`` when R9b directives across
        disable + enable mechanisms collide per the R8 polarity-first
        / tier-second resolution) + ``unknown_rule_id`` (CLI-emitted
        when a rule_id named in ``disabled_rules`` / ``enabled_rules``
        / ``--disable-rule`` / ``--enable-rule`` does not match any
        loaded rule); bumped ``_LINT_JSON_SCHEMA_VERSION`` ``"0.5"``
        → ``"0.6"`` (one bump covers both additions per KD-7).
        """
        type_hints = typing.get_type_hints(LintRuntimeWarning)
        category_type = type_hints["category"]
        literal_args = typing.get_args(category_type)
        assert set(literal_args) == {
            "rule_exception",
            "unloaded_rule",
            "severities_unloaded_rule",
            "min_severity_relaxed",
            "all_files_excluded",
            "custom_annotation_extension_unresolved",
            "extension_unresolved",
            "contradictory_disable_config",
            "unknown_rule_id",
        }
        # And exactly 9 — not "a superset" — so adding a tenth without
        # a corresponding test update will fail this assertion.
        assert len(literal_args) == 9

    def test_test_helper_mirror_stays_in_sync_with_model(self) -> None:
        """``LINT_RUNTIME_WARNING_CATEGORIES`` in ``tests/schema/lint/cli/_helpers.py``
        is a manually-maintained mirror of the model Literal — the
        cross-formatter parametrized matrix iterates that tuple, so a
        7th category added to the model but missed in the helper
        silently stops getting matrix coverage. Fail the test now if
        the two diverge so the discipline is mechanically enforced
        rather than relying on the helper docstring's "Keep in sync"
        comment.
        """
        from tests.schema.lint.cli._helpers import (
            LINT_RUNTIME_WARNING_CATEGORIES,
        )

        type_hints = typing.get_type_hints(LintRuntimeWarning)
        literal_args = set(typing.get_args(type_hints["category"]))
        assert set(LINT_RUNTIME_WARNING_CATEGORIES) == literal_args, (
            f"LINT_RUNTIME_WARNING_CATEGORIES drifted from the model Literal. "
            f"Helper tuple: {sorted(LINT_RUNTIME_WARNING_CATEGORIES)}; "
            f"model Literal: {sorted(literal_args)}. Update the helper "
            f"tuple in tests/schema/lint/cli/_helpers.py in lockstep with "
            f"the LintRuntimeWarning.category Literal in "
            f"src/protokit/schema/lint/model.py."
        )


class TestIncompleteAnalysisCategoryClassification:
    """Every ``LintRuntimeWarning`` category must be *classified* with
    respect to the V33 ``analysis-incomplete`` exit gate.

    ``_INCOMPLETE_ANALYSIS_CATEGORIES`` in ``schema/lint/cli.py`` is a
    hand-maintained tuple. A future category that means "a rule did not
    run" would land outside it silently, and the CLI would go on
    reporting a clean exit for an analysis that never completed — the
    exact drift class the 0.16.0 release exists to close, reintroduced
    by the fix for it.

    The gate's own comment classifies the other categories in prose.
    Prose is not a guard, so the two other buckets are mirrored here as
    explicit tuples: adding a category to the model Literal without
    deciding which bucket it belongs to fails this test.

    Modelled on ``test_test_helper_mirror_stays_in_sync_with_model``
    above — same ratcheting discipline, different mirror.
    """

    #: Categories that mean a rule DID NOT RUN but are deliberately not
    #: gated yet, for blast radius. Owned by U7/U8 (the ``_trust`` seam).
    #: Moving one of these into the gate is a deliberate breaking change.
    DEFERRED_INCOMPLETE: tuple[str, ...] = (
        "extension_unresolved",
        "custom_annotation_extension_unresolved",
        "all_files_excluded",
    )

    #: Categories that are genuinely advisory: they describe an
    #: ineffective override, a severity-policy note, or a nonexistent
    #: rule id — not a selected rule that failed to execute.
    ADVISORY: tuple[str, ...] = (
        "severities_unloaded_rule",
        "min_severity_relaxed",
        "contradictory_disable_config",
        "unknown_rule_id",
    )

    def test_every_category_is_classified(self) -> None:
        from protokit.schema.lint.cli import _INCOMPLETE_ANALYSIS_CATEGORIES

        type_hints = typing.get_type_hints(LintRuntimeWarning)
        literal_args = set(typing.get_args(type_hints["category"]))
        classified = (
            set(_INCOMPLETE_ANALYSIS_CATEGORIES)
            | set(self.DEFERRED_INCOMPLETE)
            | set(self.ADVISORY)
        )
        assert classified == literal_args, (
            "A LintRuntimeWarning category is unclassified with respect to "
            "the analysis-incomplete exit gate. Unclassified: "
            f"{sorted(literal_args - classified)}; classified but not in "
            f"the model: {sorted(classified - literal_args)}. Decide "
            "whether the new category means a rule did not run (add it to "
            "_INCOMPLETE_ANALYSIS_CATEGORIES in "
            "src/protokit/schema/lint/cli.py, with a CHANGELOG BREAKING "
            "row) or is advisory (add it to ADVISORY here). Silence is "
            "the one option that reintroduces the fail-open."
        )

    def test_buckets_are_disjoint(self) -> None:
        """A category in two buckets means the classification is
        incoherent, which the union check alone would not catch."""
        from protokit.schema.lint.cli import _INCOMPLETE_ANALYSIS_CATEGORIES

        gated = set(_INCOMPLETE_ANALYSIS_CATEGORIES)
        deferred = set(self.DEFERRED_INCOMPLETE)
        advisory = set(self.ADVISORY)
        assert not (gated & deferred), gated & deferred
        assert not (gated & advisory), gated & advisory
        assert not (deferred & advisory), deferred & advisory

    def test_gated_set_is_exactly_the_two_shipped_in_0_15_1(self) -> None:
        """Pins the gate's current membership so widening it is a
        deliberate, reviewed act rather than a drive-by edit."""
        from protokit.schema.lint.cli import _INCOMPLETE_ANALYSIS_CATEGORIES

        assert set(_INCOMPLETE_ANALYSIS_CATEGORIES) == {
            "rule_exception", "unloaded_rule",
        }


# ---------------------------------------------------------------------------
# rule_id type widening (BREAKING)
# ---------------------------------------------------------------------------


class TestRuleIdWidened:
    def test_rule_id_is_optional_str(self) -> None:
        """``rule_id`` is typed ``str | None`` after D5 U3 R18."""
        type_hints = typing.get_type_hints(LintRuntimeWarning)
        rule_id_type = type_hints["rule_id"]
        # str | None is equivalent to Optional[str] / Union[str, None]
        args = set(typing.get_args(rule_id_type))
        assert args == {str, type(None)}

    def test_engine_categories_accept_populated_rule_id(self) -> None:
        """The two engine-emitted categories continue to take a
        non-None ``rule_id`` (existing behavior preserved). The third
        rule-scoped category, ``severities_unloaded_rule`` (D6b U5,
        CLI-synthesized), is covered separately in
        ``tests/schema/lint/test_model.py``.
        """
        w_exc = LintRuntimeWarning(
            category="rule_exception",
            rule_id="naming/snake-case-fields",
            message="ValueError(...)",
            exception_type="ValueError",
            descriptor_path="foo.proto:bar",
        )
        assert w_exc.rule_id == "naming/snake-case-fields"

        w_unloaded = LintRuntimeWarning(
            category="unloaded_rule",
            rule_id="acme/missing-rule",
            message=(
                "rule 'acme/missing-rule' is named in profile "
                "'default' but not loaded into the engine"
            ),
        )
        assert w_unloaded.rule_id == "acme/missing-rule"

    def test_cli_categories_accept_none_rule_id(self) -> None:
        """The two non-rule-scoped CLI-emitted categories construct
        with ``rule_id=None`` (NEW behavior in D5 U3). Note: the
        third CLI-emitted category ``severities_unloaded_rule``
        (D6b U5) is rule-scoped and carries a populated ``rule_id``
        — covered in ``tests/schema/lint/test_model.py``.
        """
        w_relaxed = LintRuntimeWarning(
            category="min_severity_relaxed",
            rule_id=None,
            message="--min-severity=warning relaxes ...",
        )
        assert w_relaxed.rule_id is None

        w_excluded = LintRuntimeWarning(
            category="all_files_excluded",
            rule_id=None,
            message="all 3 input file(s) excluded by patterns: vendor/**",
        )
        assert w_excluded.rule_id is None


# ---------------------------------------------------------------------------
# Frozen-dataclass discipline preserved across all five categories
# ---------------------------------------------------------------------------


class TestFrozen:
    @pytest.mark.parametrize(
        "category,rule_id",
        [
            ("rule_exception", "rule/id"),
            ("unloaded_rule", "rule/id"),
            ("severities_unloaded_rule", "rule/id"),
            ("min_severity_relaxed", None),
            ("all_files_excluded", None),
            ("custom_annotation_extension_unresolved", "custom/x"),
            ("extension_unresolved", "options/x"),
            ("contradictory_disable_config", "naming/x"),
            ("unknown_rule_id", "naming/x"),
        ],
    )
    def test_assignment_raises_for_every_category(
        self, category: str, rule_id: str | None,
    ) -> None:
        w = LintRuntimeWarning(
            category=category,  # type: ignore[arg-type]
            rule_id=rule_id,
            message="m",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            w.rule_id = "different"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Field-population invariants per docstring table
# ---------------------------------------------------------------------------


class TestFieldPopulationInvariants:
    def test_cli_emitted_categories_have_none_descriptor_path(self) -> None:
        """``min_severity_relaxed`` and ``all_files_excluded`` are
        CLI-emitted (not engine-emitted); ``descriptor_path`` is
        ``None`` for both. The dataclass default is ``None`` so
        omitting it is the canonical construction.
        """
        for category in ("min_severity_relaxed", "all_files_excluded"):
            w = LintRuntimeWarning(
                category=category,  # type: ignore[arg-type]
                rule_id=None,
                message="m",
            )
            assert w.descriptor_path is None
            assert w.exception_type is None

    def test_rule_exception_takes_descriptor_path(self) -> None:
        """``rule_exception`` is the only category that populates
        ``descriptor_path``; this test pins the contract.
        """
        w = LintRuntimeWarning(
            category="rule_exception",
            rule_id="r/id",
            message="m",
            exception_type="ValueError",
            descriptor_path="foo.proto:bar.Msg",
        )
        assert w.descriptor_path == "foo.proto:bar.Msg"
        assert w.exception_type == "ValueError"
