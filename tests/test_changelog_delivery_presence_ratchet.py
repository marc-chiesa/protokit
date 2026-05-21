"""Parametrized presence ratchet for per-delivery CHANGELOG sections.

Consolidates the three near-verbatim per-delivery ratchets
(``tests/test_changelog_d6{a,b,c}_entry.py``) into a single
parametrized check. Per
[[presence-ratchet-test-pattern-for-prose-substrings-2026-05-14]]
discipline rule 1 (lightweight ratchets), each delivery just
needs to be NAMED in the CHANGELOG as a section heading; the
test does NOT enforce the shape of the heading or the content
of the section.

The KD-9 upgrade-safety policy in
``src/protokit/schema/lint/rules/__init__.py`` requires every
``BUILTIN_PACKS`` expansion to be accompanied by a CHANGELOG
entry that calls out the auto-load expansion and the demotion
paths. This test ratchets the section-heading presence for
every shipped delivery; new deliveries just add their
``DeliveryRatchetSpec`` entry to ``DELIVERY_RATCHETS`` below.

Heading match is line-anchored on ``### <delivery>`` (the
standard CHANGELOG markdown heading prefix) so incidental
references to ``D6a`` / ``D6b`` / ``D6c`` in prose elsewhere in
the file (cross-references, "as of D6c", historical audit-trail
notes) cannot satisfy the ratchet — only a real section heading
does. This closes the substring-leak hole that surfaced at the
D6c U5 ce:review (Finding T-01).

To rename a delivery section (e.g., consolidating into a
release-numbered heading post-1.0), update the matching
``DeliveryRatchetSpec`` alongside the CHANGELOG rewrite — but be
confident the new heading still communicates what users see on
upgrade.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"


@dataclass(frozen=True)
class DeliveryRatchetSpec:
    """A single per-delivery CHANGELOG section ratchet.

    Attributes:
        delivery: The delivery name as it appears in the
            ``### <delivery>`` CHANGELOG section heading
            (e.g., ``D6a``, ``D6b``, ``D6c``).
        version: The release version the delivery shipped as
            (e.g., ``"0.2.0"``). Informational; not asserted by
            the ratchet (the version-bump pin lives in
            ``pyproject.toml`` and is structurally verified by
            other tests).
    """

    delivery: str
    version: str


#: Per-delivery ratchet specs. Add a new entry here when shipping
#: each delivery boundary. The entries are intentionally append-
#: only — never remove a shipped delivery's ratchet, since the
#: corresponding CHANGELOG section is part of the public audit
#: trail.
DELIVERY_RATCHETS: tuple[DeliveryRatchetSpec, ...] = (
    DeliveryRatchetSpec(delivery="D6a", version="0.2.0"),
    DeliveryRatchetSpec(delivery="D6b", version="0.3.0"),
    DeliveryRatchetSpec(delivery="D6c", version="0.4.0"),
    DeliveryRatchetSpec(delivery="D6d", version="0.5.0"),
)


class TestChangelogPathExists:
    def test_changelog_file_exists(self) -> None:
        assert CHANGELOG_PATH.is_file(), (
            f"CHANGELOG.md not found at {CHANGELOG_PATH!r}. The "
            "per-delivery presence ratchets depend on the "
            "project's top-level changelog living at this path."
        )


class TestPerDeliveryHeadingPresent:
    """Line-anchored heading ratchet per shipped delivery."""

    @pytest.mark.parametrize(
        "spec",
        DELIVERY_RATCHETS,
        ids=lambda spec: spec.delivery,
    )
    def test_changelog_has_delivery_heading(
        self, spec: DeliveryRatchetSpec,
    ) -> None:
        """The CHANGELOG must have a ``### <delivery>`` heading line.

        If you are intentionally renaming or removing a
        delivery's section (e.g., consolidating into a release-
        numbered heading post-1.0), update the matching entry in
        ``DELIVERY_RATCHETS`` alongside the CHANGELOG rewrite —
        but be confident the new heading still communicates what
        users see on upgrade.
        """
        body = CHANGELOG_PATH.read_text(encoding="utf-8")
        pattern = re.compile(
            rf"^### {re.escape(spec.delivery)}\b", flags=re.MULTILINE,
        )
        assert pattern.search(body), (
            f"CHANGELOG.md has no `### {spec.delivery}` heading "
            f"line. The KD-9 policy in src/protokit/schema/lint/"
            f"rules/__init__.py requires every BUILTIN_PACKS "
            f"expansion to be documented in the changelog so "
            f"users can predict the upgrade-time finding surface. "
            f"Restore the `### {spec.delivery}` section heading "
            f"(or, if the delivery has been deliberately renamed, "
            f"update the DeliveryRatchetSpec entry in "
            f"DELIVERY_RATCHETS at this test's module head)."
        )
