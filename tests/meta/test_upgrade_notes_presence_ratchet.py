"""Presence ratchet for the 0.15.x → 0.16.0 upgrade notes.

0.16.0 moves many CLI paths to exit 2 and deliberately ships no switch to
restore the old codes. The notes that say so are what stand between a user and
a pipeline that turns red with no explanation, so this pins that they exist:
the README section, the CHANGELOG upgrade table, the CHANGELOG ``### Security``
entry for the release, and the explicit no-opt-out statement in both files.

This is a presence check, not a shape contract. Each test pins one short phrase
or one heading line; the prose around it may be rewritten freely. The CHANGELOG
checks are scoped to the ``## `` section that carries the 0.16.0 upgrade note,
so the 0.15.1 ``### Security`` heading or its "no opt-out flag" wording cannot
satisfy them. They key on the upgrade note, not on the ``## Unreleased``
heading, so renaming that heading at the release cut does not break them.

The last test checks that every in-repo link to an ``#upgrade-notes-…`` anchor
resolves to a README heading, since a heading with an arrow and dots in it has
a slug that is easy to get wrong by hand.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
README_PATH = REPO_ROOT / "README.md"
CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"

_README_HEADING = re.compile(
    r"^### Upgrade notes \(0\.15\.x → 0\.16\.0\)$", flags=re.MULTILINE,
)
_CHANGELOG_NOTE = re.compile(
    r"^> \*\*Upgrade note \(0\.15\.x → 0\.16\.0\)\.\*\*", flags=re.MULTILINE,
)
_NO_OPT_OUT = "There is no opt-out."

_UPDATE_PATH = (
    "Restore it if the change was accidental. If the notes were deliberately "
    "reworded, update the pattern in tests/meta/"
    "test_upgrade_notes_presence_ratchet.py to the new wording, keeping the "
    "explicit no-opt-out declaration: leaving the absence of an escape hatch "
    "unexplained is the thing this ratchet exists to prevent."
)


def _readme_section() -> str:
    """The README text from the 0.16.0 heading to the next ``#``-heading."""
    body = README_PATH.read_text(encoding="utf-8")
    match = _README_HEADING.search(body)
    assert match, f"README.md has no `### Upgrade notes (0.15.x → 0.16.0)` heading. {_UPDATE_PATH}"
    rest = body[match.end():]
    end = re.search(r"^#{1,3} ", rest, flags=re.MULTILINE)
    return rest[: end.start()] if end else rest


def _changelog_release_section() -> str:
    """The CHANGELOG ``## `` section that carries the 0.16.0 upgrade note."""
    body = CHANGELOG_PATH.read_text(encoding="utf-8")
    for section in re.split(r"^(?=## )", body, flags=re.MULTILINE):
        if _CHANGELOG_NOTE.search(section):
            return section
    raise AssertionError(
        "CHANGELOG.md has no `> **Upgrade note (0.15.x → 0.16.0).**` block. "
        + _UPDATE_PATH,
    )


def test_readme_has_the_upgrade_notes_heading() -> None:
    assert _README_HEADING.search(README_PATH.read_text(encoding="utf-8")), (
        f"README.md has no `### Upgrade notes (0.15.x → 0.16.0)` heading. {_UPDATE_PATH}"
    )


def test_readme_notes_declare_no_opt_out() -> None:
    assert _NO_OPT_OUT in _readme_section(), (
        f"README's 0.16.0 upgrade notes no longer say {_NO_OPT_OUT!r}. {_UPDATE_PATH}"
    )


def test_changelog_release_has_a_security_heading() -> None:
    assert re.search(r"^### Security$", _changelog_release_section(), flags=re.MULTILINE), (
        "The CHANGELOG section carrying the 0.16.0 upgrade note has no "
        f"`### Security` heading for the V31/V33 follow-through. {_UPDATE_PATH}"
    )


def test_changelog_note_declares_no_opt_out() -> None:
    assert _NO_OPT_OUT in _changelog_release_section(), (
        f"The 0.16.0 CHANGELOG section no longer says {_NO_OPT_OUT!r}. {_UPDATE_PATH}"
    )


def _github_slug(heading: str) -> str:
    """GitHub's heading anchor: lowercase, drop punctuation, spaces to hyphens."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def test_upgrade_note_links_resolve_to_a_readme_heading() -> None:
    readme = README_PATH.read_text(encoding="utf-8")
    slugs = {
        _github_slug(m.group(1))
        for m in re.finditer(r"^#{1,6} (.+)$", readme, flags=re.MULTILINE)
    }
    links = [
        (path.name, target)
        for path in (README_PATH, CHANGELOG_PATH)
        for target in re.findall(
            r"\]\((?:README\.md)?#(upgrade-notes-[^)]*)\)",
            path.read_text(encoding="utf-8"),
        )
    ]
    assert links, "no link to an `#upgrade-notes-…` anchor found; the premise of this test is gone"
    broken = [(name, target) for name, target in links if target not in slugs]
    assert not broken, f"links to a README heading that does not exist: {broken}"
