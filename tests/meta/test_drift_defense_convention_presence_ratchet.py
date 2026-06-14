"""Presence ratchet for the drift-defense convention's two load-bearing rules.

``docs/solutions/best-practices/docs-code-drift-defense-convention-2026-06-13.md``
is itself prose that no static analyzer reads, yet it carries two load-bearing
commitments: the claim-currency marker rule (mark behavioral claims about a
moving target current-state or provenance, per occurrence, co-located inline)
and the reference-triage rule (navigational pointer to a moved test path ->
update it; historical / illustrative mention -> leave it). A future contributor
doing a docs cleanup could silently delete or gut either rule, weakening the
discipline with no test failure and no reviewer noticing — the exact regression
class the convention exists to defend against. The anti-drift convention should
itself be drift-protected.

This test is a **presence ratchet, NOT a stability contract over the wording**.
Each pinned substring is the shortest uniquely-identifying ASCII run of its
rule, contiguous on one source line of the markdown file (per the
presence-ratchet pattern, rule 5). Re-flow the surrounding prose freely; only
deleting or rewording a load-bearing rule itself trips an assertion. Its scope
is honest: it guards the rules' *existence* against silent reversion. It does
NOT enforce that authors apply the convention, nor catch drift in the
convention's content — those depend on the PR-checklist gate and reviewer
attention.

See [[presence-ratchet-test-pattern-for-prose-substrings-2026-05-14]] for the
pattern and its five discipline rules.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONVENTION_PATH = (
    _REPO_ROOT
    / "docs"
    / "solutions"
    / "best-practices"
    / "docs-code-drift-defense-convention-2026-06-13.md"
)

# The shortest uniquely-identifying ASCII substring of each load-bearing rule,
# each contiguous on a single source line of the convention doc (rule 5 — no
# Unicode arrow inside the pinned run, so a `->`/`→` reflow cannot silently
# unfind it). One substring per test method (rule 4).
_MARKER_RULE_SUBSTRING = (
    "current-state or provenance, per occurrence, co-located inline with the claim"
)
_TRIAGE_RULE_SUBSTRING = "update it; a historical or illustrative mention"


class TestDriftDefenseConventionRatchet:
    def test_convention_doc_exists(self) -> None:
        """The convention doc itself is present.

        Distinguishes "deleted the whole convention" from "reworded a rule" as
        separate failure modes.
        """
        assert _CONVENTION_PATH.is_file(), (
            f"The drift-defense convention doc is missing at "
            f"{_CONVENTION_PATH.relative_to(_REPO_ROOT)}. The claim-currency "
            "marker convention and the reference-triage rule live there; "
            "restore the file or update this ratchet to the doc's new path."
        )

    def test_marker_rule_substring_is_present(self) -> None:
        """Ratchet against silent reversion of the claim-currency marker rule.

        If you are intentionally rewording the marker rule, update
        ``_MARKER_RULE_SUBSTRING`` above to match — but only after confirming
        the new wording still requires per-occurrence, co-located,
        current-state-or-provenance marking of behavioral claims about a moving
        target.
        """
        body = _CONVENTION_PATH.read_text(encoding="utf-8")
        assert _MARKER_RULE_SUBSTRING in body, (
            f"The drift-defense convention no longer states the claim-currency "
            f"marker rule ({_MARKER_RULE_SUBSTRING!r}). The per-occurrence, "
            "co-located, current-state-or-provenance marking discipline was "
            "deleted or reworded. Either restore the substring or update "
            "_MARKER_RULE_SUBSTRING in this test after confirming the new "
            "wording carries the same meaning."
        )

    def test_reference_triage_rule_substring_is_present(self) -> None:
        """Ratchet against silent reversion of the reference-triage rule.

        If you are intentionally rewording the triage rule, update
        ``_TRIAGE_RULE_SUBSTRING`` above to match — but only after confirming
        the new wording still says navigational pointers are updated and
        historical / illustrative mentions are left.
        """
        body = _CONVENTION_PATH.read_text(encoding="utf-8")
        assert _TRIAGE_RULE_SUBSTRING in body, (
            f"The drift-defense convention no longer states the reference-triage "
            f"rule ({_TRIAGE_RULE_SUBSTRING!r}). The navigational-update /"
            " historical-leave triage discipline was deleted or reworded. "
            "Either restore the substring or update _TRIAGE_RULE_SUBSTRING in "
            "this test after confirming the new wording carries the same "
            "meaning."
        )
