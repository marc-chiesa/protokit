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
3. Coordinate a minor version bump pre-1.0 (or major bump post-1.0)
   — adding to BUILTIN_PACKS is a user-visible behavior change to
   ``protokit lint`` defaults that the version-bump communication
   contract requires per
   [[pre-1.0-version-bump-as-communication-contract-2026-05-14]].

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
        expected = (
            "protokit.schema.lint.rules.naming",
            "protokit.schema.lint.rules.enum",
            "protokit.schema.lint.rules.imports",
            "protokit.schema.lint.rules.package",
            "protokit.schema.lint.rules.file",
            "protokit.schema.lint.rules.field",
            "protokit.schema.lint.rules.options.deprecated_replacement",
            "protokit.schema.lint.rules.options.field_behavior",
            "protokit.schema.lint.rules.package_same",
        )
        assert actual == expected, (
            f"BUILTIN_PACKS changed: {actual!r} != {expected!r}.\n"
            "If this change is intentional, you MUST:\n"
            "  1. Update the expected tuple in this test\n"
            "  2. Add a CHANGELOG entry per KD-9 (see "
            "src/protokit/schema/lint/rules/__init__.py module "
            "docstring)\n"
            "  3. Coordinate a minor version bump pre-1.0 (or "
            "major bump post-1.0) — adding to BUILTIN_PACKS is a "
            "user-visible behavior\n"
            "     change to `protokit lint` defaults that the "
            "version-bump communication contract requires per "
            "[[pre-1.0-version-bump-as-communication-contract]]."
        )


class TestCanaryPack:
    """Sanity-check the naming pack — origin of the D2 canary rule."""

    def test_naming_pack_exposes_snake_case_rule(self) -> None:
        rule_ids = [get_lint_spec(fn).rule_id for fn in naming.RULES]
        assert "naming/snake-case-fields" in rule_ids

    def test_naming_pack_is_first_member_of_builtin_packs(self) -> None:
        # Order matters for stable rendering of R25's stderr
        # provenance line (Unit 3): the first pack listed in
        # composition output should be the canary at D3.
        assert BUILTIN_PACKS[0] is naming


class TestBuiltinPacksDocstringRatchet:
    """Presence ratchet for the buf BASIC parity numerator + the
    two D6e rules newly cited in the ``BUILTIN_PACKS`` docstring.

    The module docstring uses ``#:`` Sphinx-style continuation
    prefixes (NOT a Python ``__doc__`` attribute), so the test
    reads source via ``inspect.getsource`` (Pattern B per
    [[presence-ratchet-test-pattern-for-prose-substrings-2026-05-14]]).

    Live pins (D6f U3, 2026-05-25 — KD-1 demonstration shipped
    at 0.7.0):

    1. ``"26 of 26 buf v1.69.0 BASIC rules"`` — load-bearing
       audit-trail numerator. Replaces the historical D6c-era
       ``"25 of 26 buf BASIC rules"`` claim (still present in the
       docstring as an audit-trail reference but no longer the
       live pin). The ``v1.69.0`` qualifier is load-bearing for
       future drift detection if buf ships a new BASIC rule.
    2. ``"``buf:PACKAGE_NO_IMPORT_CYCLE``"`` — the 26th buf BASIC
       rule landed at D6e U3 (canonical ``buf:``-prefixed form).
    3. ``"``buf:FIELD_NOT_REQUIRED``"`` — the proto2-only rule
       landed at D6e U1+U2 in opt-in ``proto2-strict``.
    4. ``"R9b per-rule disable surface"`` — D6f U2 shipped the
       full per-rule disable surface (``"off"`` severity sentinel,
       ``disabled_rules`` / ``enabled_rules`` pyproject lists,
       ``--disable-rule`` / ``--enable-rule`` CLI flags). The
       canonical phrase mirrors CHANGELOG ``#### Added — R9b
       per-rule disable (full surface)`` per
       [[presence-ratchet-pin-canonical-not-local-form-2026-05-23]]
       — pinned to the CHANGELOG/docstring canonical form, NOT
       the README's user-facing ``Disabling and re-enabling
       rules`` section heading (the section heading is verified
       separately by the README-anchored stale-text discipline).

    Without this ratchet a future stale-text edit could silently
    revert the numerator or drop the audit-trail references to
    the two D6e additions or the D6f R9b addition. Per the 5th
    discipline rule of the presence-ratchet pattern, each
    substring fits on a single source line — no Sphinx ``#:``
    continuation interrupts the assertion.
    """

    def test_builtin_packs_docstring_pins_buf_basic_numerator(
        self,
    ) -> None:
        import inspect

        from protokit.schema.lint import rules

        source = inspect.getsource(rules)
        # D6e U4 ratchet update (2026-05-22): closing-arc complete
        # at 26 of 26. The historical "25 of 26" framing is
        # preserved in the docstring as an audit-trail reference
        # to D6c (line 157 area) but the LIVE numerator pinned
        # here is the post-U4 26-of-26 with the v1.69.0 qualifier.
        # Per [[presence-ratchet-test-pattern-for-prose-substrings-
        # 2026-05-14]] rule 5: each substring fits on a single
        # source line. The ``PACKAGE_NO_IMPORT_CYCLE`` and
        # ``FIELD_NOT_REQUIRED`` substrings remain pinned as
        # audit-trail references (now landed, no longer deferred).
        ratchet_substrings = (
            "26 of 26 buf v1.69.0 BASIC rules",
            # Post-D6e U3 the rule's name appears with the ``buf:``
            # prefix in the docstring (canonical source_spec form);
            # match that form to preserve the audit-trail pin.
            "``buf:PACKAGE_NO_IMPORT_CYCLE``",
            # Post-D6e U1+U2 the rule's name appears with the
            # ``buf:`` prefix too; same rationale.
            "``buf:FIELD_NOT_REQUIRED``",
            # D6f U2 (0.7.0) R9b per-rule disable surface. Pinned
            # canonical phrase from CHANGELOG ``#### Added — R9b
            # per-rule disable (full surface)`` per
            # [[presence-ratchet-pin-canonical-not-local-form-2026-05-23]].
            # NOT pinned to the README's user-facing section heading
            # ``Disabling and re-enabling rules`` since that lives
            # outside the docstring; per the canonical-pin rule the
            # substring must appear in BOTH source surfaces (here,
            # the BUILTIN_PACKS docstring AND the CHANGELOG entry).
            "R9b per-rule disable surface",
        )
        for substring in ratchet_substrings:
            assert substring in source, (
                f"BUILTIN_PACKS docstring substring {substring!r} "
                f"missing from src/protokit/schema/lint/rules/"
                f"__init__.py. Either restore the substring OR "
                f"update `ratchet_substrings` in this test after "
                f"confirming the buf BASIC parity numerator is "
                f"still preserved semantically. See the D6c "
                f"CHANGELOG `#### Corrected` subsection + the D6e "
                f"U4 boundary commit + [[stale-forward-looking-"
                f"text-cli-help-agent-discoverability-2026-05-12]] "
                f"for the discipline this ratchet protects."
            )
