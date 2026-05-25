"""R8 precedence resolution table for R9b per-rule disable (D6f U2).

This module pins the **17-case R8 resolution table** (12 from the
brainstorm + 1 added post-review: ``--enable-rule R + [severities]
R = "off"`` is a cross-tier disable-wins case mirroring the
``--enable-rule R + pyproject disabled_rules ⊃ R`` case; +4 added
post-ce:review: D3+E1 cross-tier disable, and three idempotent
same-polarity no-warn cases).

Per the D6f U2 plan **Execution note**, this parametrized table is the
test fixture spec for the resolution logic in
``ResolvedLintConfig.from_dict``; it must be written BEFORE the
implementation and pin the contract independently of the source.

The 5 disable / enable mechanisms exercised:

- **D1**: pyproject ``[severities] R = "off"``
  (sentinel intercepted at coercion layer per KD-1).
- **D2**: pyproject ``disabled_rules = [R]``.
- **D3**: CLI ``--disable-rule R`` (passed via
  ``cli_overrides["disabled_rules"]``).
- **E1**: pyproject ``enabled_rules = [R]``.
- **E2**: CLI ``--enable-rule R`` (passed via
  ``cli_overrides["enabled_rules"]``).

The resolution principle (per the plan's
**R8 precedence resolution** section):

1. POLARITY: any disable from any tier wins (R disabled across the
   board).
2. TIER (only when no disable fires): CLI > pyproject within the same
   polarity.

R8b (``contradictory_disable_config``) warnings emit whenever step 1
silently overrides a user-supplied directive at a lower tier. The
idempotent case (D1 ∧ D2 — both disable; no override) does NOT warn.

R8c (``unknown_rule_id``) warnings are out of scope for this file —
they fire at the CLI-orchestration layer where the full loaded-rule
registry is available, and are covered by
``tests/schema/lint/test_r9b_warnings.py``.
"""

from __future__ import annotations

from typing import Any

import pytest

from protokit.schema.lint._config import ResolvedLintConfig

#: A single rule_id used across every case in the table. Chosen because
#: ``naming/snake-case-fields`` exists in BUILTIN_PACKS' ``default``
#: profile, so end-to-end suppression tests (in
#: ``test_cli_r9b_profile_augmentation.py``) can use the SAME id without
#: needing per-case fixture variation.
_RULE_ID = "naming/snake-case-fields"

#: 17-case parametrized R8 resolution table. The tuples are:
#: ``(case_id, pyproject_table, cli_overrides, expected_disabled,
#: expected_enabled, expected_warning_rule_ids)``.
#:
#: - ``expected_disabled``: the UNIFIED ``resolved.disabled_rules``
#:   frozenset (merges ``[severities] X = "off"`` + ``disabled_rules``
#:   per KD-1 sentinel propagation contract).
#: - ``expected_enabled``: the ``resolved.enabled_rules`` frozenset
#:   (kept distinct from ``disabled_rules`` so cross-tier
#:   ``--enable-rule`` directives stay attributable for R8b warnings).
#: - ``expected_warning_rule_ids``: the rule_ids named by R8b
#:   ``contradictory_disable_config`` warnings on
#:   ``resolved.runtime_warnings``. Empty for idempotent /
#:   no-contradiction cases.
_R8_TABLE: tuple[
    tuple[
        str,
        dict[str, Any],
        dict[str, Any],
        frozenset[str],
        frozenset[str],
        frozenset[str],
    ],
    ...,
] = (
    # ── Single-mechanism cases ───────────────────────────────────────
    (
        "01_baseline_no_r9b_config",
        {},
        {},
        frozenset(),
        frozenset(),
        frozenset(),
    ),
    (
        "02_d1_only_off_severity",
        {"severities": {_RULE_ID: "off"}},
        {},
        frozenset({_RULE_ID}),
        frozenset(),
        frozenset(),
    ),
    (
        "03_d2_only_pyproject_disabled_rules",
        {"disabled_rules": [_RULE_ID]},
        {},
        frozenset({_RULE_ID}),
        frozenset(),
        frozenset(),
    ),
    (
        "04_d3_only_cli_disable_rule",
        {},
        {"disabled_rules": (_RULE_ID,)},
        frozenset({_RULE_ID}),
        frozenset(),
        frozenset(),
    ),
    (
        "05_e1_only_pyproject_enabled_rules",
        {"enabled_rules": [_RULE_ID]},
        {},
        frozenset(),
        frozenset({_RULE_ID}),
        frozenset(),
    ),
    (
        "06_e2_only_cli_enable_rule",
        {},
        {"enabled_rules": (_RULE_ID,)},
        frozenset(),
        frozenset({_RULE_ID}),
        frozenset(),
    ),
    # ── Idempotent (both disable; NO warning) ────────────────────────
    (
        "07_d1_plus_d2_idempotent_no_warning",
        {
            "severities": {_RULE_ID: "off"},
            "disabled_rules": [_RULE_ID],
        },
        {},
        frozenset({_RULE_ID}),
        frozenset(),
        frozenset(),
    ),
    # ── Contradictory (one tier disables, another enables: warn) ─────
    (
        "08_d2_plus_e1_pyproject_contradiction",
        {
            "disabled_rules": [_RULE_ID],
            "enabled_rules": [_RULE_ID],
        },
        {},
        frozenset({_RULE_ID}),
        frozenset({_RULE_ID}),
        frozenset({_RULE_ID}),
    ),
    (
        "09_d3_plus_e2_cli_contradiction",
        {},
        {
            "disabled_rules": (_RULE_ID,),
            "enabled_rules": (_RULE_ID,),
        },
        frozenset({_RULE_ID}),
        frozenset({_RULE_ID}),
        frozenset({_RULE_ID}),
    ),
    (
        "10_d2_plus_e2_cross_tier_disable_wins",
        {"disabled_rules": [_RULE_ID]},
        {"enabled_rules": (_RULE_ID,)},
        frozenset({_RULE_ID}),
        frozenset({_RULE_ID}),
        frozenset({_RULE_ID}),
    ),
    (
        "11_d1_plus_e1_off_severity_vs_enabled_rules",
        {
            "severities": {_RULE_ID: "off"},
            "enabled_rules": [_RULE_ID],
        },
        {},
        frozenset({_RULE_ID}),
        frozenset({_RULE_ID}),
        frozenset({_RULE_ID}),
    ),
    (
        "12_d2_plus_severity_override_disabled_wins",
        {
            "disabled_rules": [_RULE_ID],
            "severities": {_RULE_ID: "warning"},
        },
        {},
        frozenset({_RULE_ID}),
        frozenset(),
        frozenset({_RULE_ID}),
    ),
    (
        "13_e2_plus_d1_cross_tier_off_severity_wins",
        {"severities": {_RULE_ID: "off"}},
        {"enabled_rules": (_RULE_ID,)},
        frozenset({_RULE_ID}),
        frozenset({_RULE_ID}),
        frozenset({_RULE_ID}),
    ),
    # ── Cross-tier: CLI --disable-rule + pyproject enabled_rules (D3+E1) ─
    (
        "14_d3_plus_e1_cli_disable_pyproject_enable",
        {"enabled_rules": [_RULE_ID]},
        {"disabled_rules": (_RULE_ID,)},
        frozenset({_RULE_ID}),
        frozenset({_RULE_ID}),
        frozenset({_RULE_ID}),
    ),
    # ── Idempotent same-polarity: both disable, no warning ────────────
    (
        "15_d1_plus_d3_idempotent_off_severity_and_cli_disable",
        {"severities": {_RULE_ID: "off"}},
        {"disabled_rules": (_RULE_ID,)},
        frozenset({_RULE_ID}),
        frozenset(),
        frozenset(),
    ),
    (
        "16_d2_plus_d3_idempotent_pyproject_and_cli_disable",
        {"disabled_rules": [_RULE_ID]},
        {"disabled_rules": (_RULE_ID,)},
        frozenset({_RULE_ID}),
        frozenset(),
        frozenset(),
    ),
    # ── Idempotent same-polarity: both enable, no warning ─────────────
    (
        "17_e1_plus_e2_idempotent_pyproject_and_cli_enable",
        {"enabled_rules": [_RULE_ID]},
        {"enabled_rules": (_RULE_ID,)},
        frozenset(),
        frozenset({_RULE_ID}),
        frozenset(),
    ),
)


@pytest.mark.parametrize(
    (
        "case_id",
        "pyproject_table",
        "cli_overrides",
        "expected_disabled",
        "expected_enabled",
        "expected_warning_rule_ids",
    ),
    _R8_TABLE,
    ids=[case[0] for case in _R8_TABLE],
)
def test_r8_precedence_resolution_table(
    case_id: str,
    pyproject_table: dict[str, Any],
    cli_overrides: dict[str, Any],
    expected_disabled: frozenset[str],
    expected_enabled: frozenset[str],
    expected_warning_rule_ids: frozenset[str],
) -> None:
    """Verify R8 polarity-first / tier-second resolution + R8b warnings.

    The unified ``resolved.disabled_rules`` field merges
    ``[severities] R = "off"`` sentinel ids with the explicit
    ``disabled_rules`` list per KD-1; ``cli.py`` subtracts this set
    from ``composed_profile.rule_ids`` to actuate the suppression.
    ``resolved.enabled_rules`` stays separate so R8b warnings can name
    the directive that was overridden.
    """
    del case_id  # used only for the parametrize id label
    resolved = ResolvedLintConfig.from_dict(pyproject_table, cli_overrides)
    assert resolved.disabled_rules == expected_disabled
    assert resolved.enabled_rules == expected_enabled
    warning_rule_ids = frozenset(
        w.rule_id
        for w in resolved.runtime_warnings
        if w.category == "contradictory_disable_config" and w.rule_id is not None
    )
    assert warning_rule_ids == expected_warning_rule_ids
