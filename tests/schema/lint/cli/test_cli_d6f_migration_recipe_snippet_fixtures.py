"""D6f U3 — Byte-equivalence between migration recipe TOML snippets and fixtures.

Per [[changelog-readme-snippet-fixture-byte-equivalence-2026-05-21]],
every executable TOML snippet shipped in user-facing documentation
(CHANGELOG.md, README.md) MUST map to a committed fixture that parses
cleanly through the same coercion path the user's invocation will use.
The fixture is the source of truth; the documentation is a projection.

The 5 fixtures under
``tests/schema/lint/cli/cli_fixtures/d6f_migration_recipe/`` cover:

- ``path2_demote_one_rule_to_warning.toml`` — CHANGELOG ``### D6f``
  → ``#### Pre-upgrade migration recipe`` path 2.
- ``path3_off_severity_single_rule.toml`` — CHANGELOG ``### D6f``
  → ``#### Pre-upgrade migration recipe`` path 3.
- ``disabled_rules_single_rule.toml`` — README ``### Disabling and
  re-enabling rules`` → Disable mechanisms table.
- ``enabled_rules_single_rule.toml`` — README ``### Disabling and
  re-enabling rules`` → Enable mechanisms table.
- ``path4_disabled_rules_r6_family.toml`` — CHANGELOG ``### D6f``
  → ``#### Pre-upgrade migration recipe`` path 4 (KD-4 5-rule
  family-list form).

Each fixture is asserted against TWO contracts:

1. **Parse contract**: the TOML loads + flows through
   ``ResolvedLintConfig.from_dict`` without raising, and produces the
   expected ``disabled_rules`` / ``rule_severity_overrides`` /
   ``enabled_rules`` fields per the fixture's documented intent.
2. **Doc-presence contract**: the load-bearing fixture line (the rule_id
   string, in the exact form a user would copy-paste) appears verbatim
   in the source doc named above. Drift between the fixture and the
   doc snippet would silently break user copy-paste workflows; this
   ratchet catches that drift at CI time.

End-to-end CLI behavior verification for the migration paths lives in
``test_cli_r6_migration_recipe.py`` (U1, against the
``d6f_r6_migration/`` fixture set). This file is the byte-equivalence
ratchet, NOT a behavior test — the documented snippets MUST stay
load-bearing as a user-facing surface.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - lower bound
    import tomli as tomllib

from protokit.schema.lint._config import ResolvedLintConfig
from protokit.schema.lint.model import LintSeverity

REPO_ROOT = Path(__file__).resolve().parents[4]
CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"
README_PATH = REPO_ROOT / "README.md"
FIXTURE_DIR = Path(__file__).parent / "cli_fixtures" / "d6f_migration_recipe"


def _load_table(fixture_name: str) -> dict[str, Any]:
    """Read a fixture TOML and return its ``[tool.protokit.lint]`` table."""
    path = FIXTURE_DIR / fixture_name
    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    return parsed["tool"]["protokit"]["lint"]


class TestPath2DemoteOneRuleToWarning:
    """CHANGELOG migration recipe path 2 — demote one R6 rule to WARNING."""

    FIXTURE = "path2_demote_one_rule_to_warning.toml"
    RULE_ID = "options/deprecated-field-must-have-replacement-comment"

    def test_fixture_parses_to_expected_severity_override(self) -> None:
        resolved = ResolvedLintConfig.from_dict(_load_table(self.FIXTURE), {})
        assert resolved.severities[self.RULE_ID] == (
            LintSeverity.WARNING
        )
        # Path 2 does NOT disable; the rule stays loaded with the
        # overridden severity.
        assert self.RULE_ID not in resolved.disabled_rules

    def test_fixture_line_appears_in_changelog(self) -> None:
        snippet = f'"{self.RULE_ID}" = "warning"'
        body = CHANGELOG_PATH.read_text(encoding="utf-8")
        assert snippet in body, (
            f"CHANGELOG.md missing the published migration recipe snippet "
            f"{snippet!r}. The d6f_migration_recipe fixture has drifted "
            f"from the doc OR the doc has dropped the load-bearing line. "
            f"Restore the snippet in `### D6f — 0.7.0` → `#### Pre-upgrade "
            f"migration recipe` path 2, OR update the fixture + this test "
            f"after confirming the new form is still copy-paste-safe."
        )


class TestPath3OffSeveritySingleRule:
    """CHANGELOG migration recipe path 3 — disable one R6 rule via "off"."""

    FIXTURE = "path3_off_severity_single_rule.toml"
    RULE_ID = "options/deprecated-field-must-have-replacement-comment"

    def test_fixture_parses_to_unified_disabled_set(self) -> None:
        resolved = ResolvedLintConfig.from_dict(_load_table(self.FIXTURE), {})
        # KD-1 sentinel propagation: "off" rule_ids merge into the
        # unified disabled_rules frozenset.
        assert self.RULE_ID in resolved.disabled_rules
        # The "off" sentinel is intercepted BEFORE LintSeverity()
        # construction — rule does NOT appear in severity overrides.
        assert self.RULE_ID not in resolved.severities

    def test_fixture_line_appears_in_changelog(self) -> None:
        snippet = f'"{self.RULE_ID}" = "off"'
        body = CHANGELOG_PATH.read_text(encoding="utf-8")
        assert snippet in body, (
            f"CHANGELOG.md missing the published migration recipe snippet "
            f"{snippet!r}. Fixture has drifted from `### D6f — 0.7.0` → "
            f"`#### Pre-upgrade migration recipe` path 3."
        )


class TestDisabledRulesSingleRule:
    """README ``### Disabling and re-enabling rules`` → ``disabled_rules`` row."""

    FIXTURE = "disabled_rules_single_rule.toml"
    RULE_ID = "naming/snake-case-fields"

    def test_fixture_parses_to_unified_disabled_set(self) -> None:
        resolved = ResolvedLintConfig.from_dict(_load_table(self.FIXTURE), {})
        assert self.RULE_ID in resolved.disabled_rules

    def test_fixture_line_appears_in_readme(self) -> None:
        # The README's table row uses backticks around the example:
        # `disabled_rules = ["naming/snake-case-fields"]`. The
        # fixture's TOML line is the same payload.
        snippet = f'disabled_rules = ["{self.RULE_ID}"]'
        body = README_PATH.read_text(encoding="utf-8")
        assert snippet in body, (
            f"README.md missing the published `Disabling and re-enabling "
            f"rules` snippet {snippet!r}. Fixture has drifted from the "
            f"section's Disable-mechanisms table."
        )


class TestEnabledRulesSingleRule:
    """README ``### Disabling and re-enabling rules`` → ``enabled_rules`` row."""

    FIXTURE = "enabled_rules_single_rule.toml"
    RULE_ID = "package/no-import-cycle"

    def test_fixture_parses_to_enabled_set(self) -> None:
        resolved = ResolvedLintConfig.from_dict(_load_table(self.FIXTURE), {})
        assert self.RULE_ID in resolved.enabled_rules
        # No disable mechanism in this fixture → rule_id stays out of
        # the unified disabled_rules set.
        assert self.RULE_ID not in resolved.disabled_rules

    def test_fixture_line_appears_in_readme(self) -> None:
        snippet = f'enabled_rules = ["{self.RULE_ID}"]'
        body = README_PATH.read_text(encoding="utf-8")
        assert snippet in body, (
            f"README.md missing the published `Disabling and re-enabling "
            f"rules` snippet {snippet!r}. Fixture has drifted from the "
            f"section's Enable-mechanisms table."
        )


class TestPath4DisabledRulesR6Family:
    """CHANGELOG migration recipe path 4 — KD-4 5-rule family-list form.

    Per KD-4: writing every R6 ElementKind in a single ``disabled_rules``
    list is the canonical "suppress R6 wholesale" form. The 5-rule
    enumeration is load-bearing and MUST appear verbatim in CHANGELOG.
    """

    FIXTURE = "path4_disabled_rules_r6_family.toml"
    FAMILY_RULE_IDS: tuple[str, ...] = (
        "options/deprecated-field-must-have-replacement-comment",
        "options/deprecated-enum-value-must-have-replacement-comment",
        "options/deprecated-method-must-have-replacement-comment",
        "options/deprecated-message-must-have-replacement-comment",
        "options/deprecated-enum-must-have-replacement-comment",
    )

    def test_fixture_parses_to_all_five_family_rule_ids_disabled(self) -> None:
        resolved = ResolvedLintConfig.from_dict(_load_table(self.FIXTURE), {})
        for rule_id in self.FAMILY_RULE_IDS:
            assert rule_id in resolved.disabled_rules, (
                f"R6 family rule_id {rule_id!r} missing from the fixture's "
                f"resolved disabled_rules. Fixture has drifted from the "
                f"5-rule KD-4 family-list form."
            )
        # Pin the exact count too — a regression that adds a 6th id
        # (e.g., a `service` ElementKind that doesn't actually exist
        # in the deprecated_replacement family) would be silently
        # accepted otherwise.
        family_disabled = resolved.disabled_rules & frozenset(self.FAMILY_RULE_IDS)
        assert len(family_disabled) == 5

    @pytest.mark.parametrize("rule_id", FAMILY_RULE_IDS)
    def test_family_rule_id_appears_in_changelog_path4_snippet(
        self, rule_id: str,
    ) -> None:
        """Each R6 family rule_id appears verbatim in CHANGELOG path 4.

        The KD-4 5-rule family-list form is load-bearing for users who
        want to copy-paste the wholesale-suppression recipe. Per the
        snippet-fixture byte-equivalence discipline, every rule_id in
        the fixture MUST appear in the published doc.

        Anchored on the indented-list form (5-space indent + trailing
        comma, matching CHANGELOG path 4's TOML block) so a regression
        that deletes the entire `disabled_rules = [...]` block does
        not pass silently for rule_ids that also appear in path 2 or
        path 3's single-rule `[severities]` snippets (the FIELD rule_id
        in particular appears in both path 2 and path 3 examples).
        """
        body = CHANGELOG_PATH.read_text(encoding="utf-8")
        # Match the indented-list form as it appears in the TOML list:
        # 5-space indent (matches the published path 4 block, which is
        # itself indented 3 spaces inside the markdown code fence with
        # an additional 2 spaces for TOML list-element indent) + trailing
        # comma. This anchors on the block structure, not on any
        # incidental quoted occurrence elsewhere in the section.
        snippet = f'     "{rule_id}",'
        assert snippet in body, (
            f"CHANGELOG.md `### D6f — 0.7.0` path 4 snippet missing "
            f"the indented-list entry {snippet!r}. The KD-4 5-rule "
            f"family-list form is load-bearing; restore the missing "
            f"rule_id in the `disabled_rules = [...]` block. (If the "
            f"block was reformatted to a different indent or quoting, "
            f"update this assertion's anchor pattern to match.)"
        )
