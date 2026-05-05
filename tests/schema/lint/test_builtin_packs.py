"""Tests for ``protokit.schema.lint.rules.BUILTIN_PACKS``.

The auto-load list is the **single source of truth** for which
packs ``protokit lint`` runs by default (see KD-9 in the D3
plan). This test pins the exact membership of the tuple. Any
change to ``BUILTIN_PACKS`` MUST:

1. Update the assertion in ``test_builtin_packs_membership_pin``
   below to reflect the new tuple (signaling intent — the change
   is deliberate, not a typo).
2. Add a CHANGELOG entry calling out the auto-load expansion +
   the user-facing impact (new findings on previously-green CI
   for users who upgrade across the change).
3. Coordinate with a major version bump — adding to the
   auto-load set is a breaking change to the
   ``protokit lint`` default behavior.

The hard CI gate replaces the soft-norm documentation policy
documented in ``rules/__init__.py`` with a structural guarantee.

Cold-import note: this test imports from
``protokit.schema.lint.rules`` directly, so it intentionally
does NOT exercise the ``import protokit.schema; ...`` cold-import
gate (which lives in ``.github/workflows/ci.yml`` and is
extended in Unit 5 of the D3 plan).
"""

from __future__ import annotations

from types import ModuleType

from protokit.schema.lint.decorator import get_lint_spec
from protokit.schema.lint.rules import BUILTIN_PACKS, naming


class TestBuiltinPacks:
    def test_is_a_tuple(self) -> None:
        # ``tuple`` (not ``list``) so the constant is hash-stable
        # and immutable at the language level.
        assert isinstance(BUILTIN_PACKS, tuple)

    def test_every_member_is_a_module(self) -> None:
        for pack in BUILTIN_PACKS:
            assert isinstance(pack, ModuleType), (
                f"{pack!r} is not a module — BUILTIN_PACKS members "
                "must be importable rule pack modules whose RULES "
                "tuple LintEngine.load_rule_pack consumes."
            )

    def test_every_member_exposes_rules_tuple(self) -> None:
        for pack in BUILTIN_PACKS:
            rules = getattr(pack, "RULES", None)
            assert rules is not None, (
                f"{pack.__name__} has no top-level RULES attribute. "
                "All built-in packs MUST expose a RULES tuple of "
                "@lint_rule-decorated callables (see D2 plan)."
            )
            assert isinstance(rules, tuple), (
                f"{pack.__name__}.RULES must be a tuple, got "
                f"{type(rules).__name__}."
            )
            assert len(rules) > 0, (
                f"{pack.__name__}.RULES is empty — a pack with no "
                "rules has no value in the auto-load set. Either "
                "remove it from BUILTIN_PACKS or add at least one "
                "rule."
            )

    def test_builtin_packs_membership_pin(self) -> None:
        """Hard CI gate enforcing KD-9 upgrade-safety.

        See module docstring + ``rules/__init__.py`` for the
        policy this assertion enforces. If you are intentionally
        adding a pack to BUILTIN_PACKS, update the expected tuple
        below AND add a CHANGELOG entry AND coordinate a major
        version bump (the change is breaking under semver).
        """
        actual = tuple(p.__name__ for p in BUILTIN_PACKS)
        expected = ("protokit.schema.lint.rules.naming",)
        assert actual == expected, (
            f"BUILTIN_PACKS changed: {actual!r} != {expected!r}.\n"
            "If this change is intentional, you MUST:\n"
            "  1. Update the expected tuple in this test\n"
            "  2. Add a CHANGELOG entry per KD-9 (see "
            "src/protokit/schema/lint/rules/__init__.py module "
            "docstring)\n"
            "  3. Coordinate a major version bump — adding to "
            "BUILTIN_PACKS is a breaking change to the\n"
            "     `protokit lint` default behavior."
        )


class TestCanaryPack:
    """Sanity-check the single D3-era built-in pack."""

    def test_naming_pack_exposes_snake_case_rule(self) -> None:
        rule_ids = [get_lint_spec(fn).rule_id for fn in naming.RULES]
        assert "naming/snake-case-fields" in rule_ids

    def test_naming_pack_is_first_member_of_builtin_packs(self) -> None:
        # Order matters for stable rendering of R25's stderr
        # provenance line (Unit 3): the first pack listed in
        # composition output should be the canary at D3.
        assert BUILTIN_PACKS[0] is naming
