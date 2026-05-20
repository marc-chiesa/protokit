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
    def test_literal_lists_all_seven_categories(self) -> None:
        """The Literal annotation must enumerate exactly 7 category
        names. A drift to 6 or 8 indicates an accidental break in the
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
        don't include ``google/api/field_behavior.proto``).
        Bump-permissive additive Literal value per the wire-format
        schema-version bump contract — no schema_version bump.
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
        }
        # And exactly 7 — not "a superset" — so adding an eighth without
        # a corresponding test update will fail this assertion.
        assert len(literal_args) == 7

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
