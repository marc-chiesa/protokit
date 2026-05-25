"""D6f U1 — R6 promotion regression pin (WARNING → ERROR in default).

Companion to ``test_deprecated_replacement.py``. Pins the post-D6f
severity of all 5 R6 rules at ``LintSeverity.ERROR`` so a future
inadvertent re-demotion back to WARNING is caught at the rule-spec
layer (the lowest-level surface — fires whether or not a finding is
emitted, whether or not the engine is run).

The pin mirrors the D6e R4b inverse-direction regression pattern at
``tests/schema/lint/cli/test_cli_ci_gating.py::TestMaxWarningsExitLadder
::test_proto2_file_under_default_profile_exits_0_post_r4b_demotion``,
which serves the same purpose for the ``file/syntax-specified``
ERROR → WARNING demotion. R6 is the inverse direction: promotion.

**Why a dedicated file** (not folded into ``test_deprecated_replacement.py``):
the existing ``TestRuleSpecs`` class asserts per-rule metadata
(``rule_id``, ``severity``, ``profiles``, ``element``, ``source_spec``)
and its severity assertions are updated in-place to ``ERROR`` as part
of the D6f U1 flip. This new file is a SECOND, intentionally-redundant
parametrized assertion across all 5 rule_ids — the redundancy is the
point. Per [[migration-recipe-severity-aware-template-reuse-2026-05-21]]
the severity change is load-bearing for the user-facing exit-code
contract; pinning it in two distinct sites doubles the chance a
re-demotion regression fires a test failure during review.

Reference: ``docs/plans/2026-05-24-001-feat-d6f-r6-promotion-and-r9b-per-rule-disable-plan.md``
U1 verification list.
"""

from __future__ import annotations

import pytest

from protokit.schema.lint.engine import LintEngine
from protokit.schema.lint.model import LintSeverity
from protokit.schema.lint.rules.options import deprecated_replacement

# The 5 R6 rule_ids in their canonical long-form (verified at
# ``src/protokit/schema/lint/rules/options/deprecated_replacement.py``
# per the D6f plan Context & Research table).
R6_RULE_IDS: tuple[str, ...] = (
    "options/deprecated-field-must-have-replacement-comment",
    "options/deprecated-enum-value-must-have-replacement-comment",
    "options/deprecated-method-must-have-replacement-comment",
    "options/deprecated-message-must-have-replacement-comment",
    "options/deprecated-enum-must-have-replacement-comment",
)


@pytest.mark.parametrize("rule_id", R6_RULE_IDS)
def test_r6_rule_spec_severity_is_error_post_d6f_promotion(
    rule_id: str,
) -> None:
    """Each R6 rule's declared spec severity is ERROR post-D6f.

    Reads the ``_lint_spec`` attribute attached by the ``@lint_rule``
    decorator on each rule callable in
    :data:`deprecated_replacement.RULES`. This is the canonical
    pre-engine surface — the assertion succeeds without any
    descriptor compilation or engine run.
    """
    spec_by_id = {
        fn._lint_spec.rule_id: fn._lint_spec  # type: ignore[attr-defined]
        for fn in deprecated_replacement.RULES
    }
    spec = spec_by_id[rule_id]
    assert spec.severity is LintSeverity.ERROR, (
        f"R6 rule {rule_id!r}: spec.severity is "
        f"{spec.severity!r}; expected LintSeverity.ERROR post-D6f "
        f"promotion. Per the D6f plan KD-8 Phase 0 empirical "
        f"validation (0/19 noisy on googleapis seed=42 n=200), the "
        f"promotion is intentional. If a regression demotes this "
        f"rule back to WARNING, update the plan AND CHANGELOG "
        f"first; do NOT silently relax this assertion."
    )


@pytest.mark.parametrize("rule_id", R6_RULE_IDS)
def test_r6_rule_severity_in_loaded_engine_is_error_post_d6f_promotion(
    rule_id: str,
) -> None:
    """Each R6 rule loaded into the engine carries ERROR severity.

    Second-surface assertion: confirms that after loading the
    ``deprecated_replacement`` pack into a fresh ``LintEngine``, the
    public :meth:`LintEngine.get_spec` accessor reports the post-D6f
    severity. Catches a hypothetical regression where the rule-pack
    decorator carries ERROR but a load-time transformation lowers
    severity (none exists today; this is a forward-safety pin).

    Uses ``get_spec`` per the D6b U4b discipline (no ``_loaded_specs``
    direct access; aligns with D6d new-U3 ce:review KP-3).
    """
    engine = LintEngine()
    engine.load_rule_pack(deprecated_replacement)
    spec = engine.get_spec(rule_id)
    assert spec.severity is LintSeverity.ERROR, (
        f"R6 rule {rule_id!r}: engine-loaded spec.severity is "
        f"{spec.severity!r}; expected LintSeverity.ERROR post-D6f "
        f"promotion."
    )


def test_r6_family_count_pinned_at_five() -> None:
    """The R6 family stays at exactly 5 rules.

    A defensive pin so that a future expansion of the
    ``deprecated_replacement`` pack (e.g., adding a SERVICE-level
    rule) re-prompts a CHANGELOG entry and Phase 0 re-validation
    instead of silently shipping an additional ERROR-severity rule
    in the ``default`` profile.
    """
    assert len(deprecated_replacement.RULES) == 5, (
        f"R6 family must stay at 5 rules pinned in the D6f plan; "
        f"got {len(deprecated_replacement.RULES)}. If you are "
        f"intentionally extending the family, update the plan, "
        f"CHANGELOG, AND R6_RULE_IDS in this file."
    )


def test_r6_family_all_default_profile_only() -> None:
    """R6 ships in ``default`` only — ``recommended`` parity preserved.

    Mirrors the existing ``TestRuleSpecs::test_all_rules_share_default_only_profile``
    assertion in ``test_deprecated_replacement.py``; duplicated here
    so a regression that adds R6 to ``recommended`` (which would
    silently break the buf-BASIC parity claim AND extend the
    ERROR-blast-radius to recommended-profile users) fails this
    severity-focused test file too.
    """
    for fn in deprecated_replacement.RULES:
        spec = fn._lint_spec  # type: ignore[attr-defined]
        assert spec.profiles == ("default",), (
            f"R6 rule {spec.rule_id!r}: profiles={spec.profiles!r}; "
            f"expected ('default',) only. R6 promotion to ERROR is "
            f"scoped to the default profile per the D6f plan Scope "
            f"Boundaries; do NOT extend to recommended without "
            f"replanning."
        )
