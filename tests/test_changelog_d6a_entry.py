"""Presence ratchet for the D6a CHANGELOG section.

The KD-9 upgrade-safety policy in
``src/protokit/schema/lint/rules/__init__.py`` requires every
``BUILTIN_PACKS`` expansion to be accompanied by a CHANGELOG
entry that calls out the auto-load expansion and the demotion
paths. D6a is the first delivery to ship a multi-pack expansion
(4 new packs joining the D2 ``naming`` canary), and the CHANGELOG
entry naming the delivery is the user-facing communication
surface for that change.

This test asserts that CHANGELOG.md contains a heading naming
"D6a". It does NOT enforce the shape of the heading or the
content of the section — it is a presence ratchet against
silently omitting the delivery's documentation, NOT a stability
contract over the CHANGELOG structure.

The check is intentionally minimal so the assertion stays valid
across reasonable rewrites of the section heading and body
(``### D6a — ...``, ``### D6a (0.2.0) — ...``, etc.). The single
substring it requires is the literal token ``D6a``.
"""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"


class TestChangelogD6aEntry:
    def test_changelog_exists(self) -> None:
        assert CHANGELOG_PATH.is_file(), (
            f"CHANGELOG.md not found at {CHANGELOG_PATH!r}. The "
            "D6a presence ratchet depends on the project's "
            "top-level changelog living at this path."
        )

    def test_changelog_names_d6a(self) -> None:
        """Substring ratchet against silently omitting the D6a entry.

        If you are intentionally renaming or removing the D6a
        section (e.g., consolidating into a release-numbered
        heading post-1.0), update this test alongside the
        CHANGELOG rewrite — but be confident the new heading
        still communicates what users see on upgrade.
        """
        body = CHANGELOG_PATH.read_text(encoding="utf-8")
        assert "D6a" in body, (
            "CHANGELOG.md does not name the D6a delivery. The "
            "KD-9 policy in src/protokit/schema/lint/rules/"
            "__init__.py requires every BUILTIN_PACKS expansion "
            "to be documented in the changelog so users can "
            "predict the upgrade-time finding surface. Restore "
            "the D6a section or update this ratchet to match a "
            "deliberately renamed heading."
        )
