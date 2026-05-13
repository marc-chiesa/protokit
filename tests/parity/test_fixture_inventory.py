"""Reverse-inventory guard: every fixture directory maps to a known rule.

The per-family ``test_every_<family>_rule_has_a_parity_map_entry`` tests
enforce the forward direction (every parity-eligible rule in
``BUILTIN_PACKS`` has fixtures). This module enforces the reverse:
every fixture directory under ``tests/parity/fixtures/<family>/<rule>/``
corresponds to an actual rule in ``RULE_ID_MAP``.

Without this guard, a deleted-or-renamed rule's orphaned fixture
directory silently becomes a happy-path case (protokit emits no
findings because the rule no longer exists; buf may or may not fire
depending on whether its rule still exists; the test passes trivially).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.parity.conftest import RULE_ID_MAP

pytestmark = pytest.mark.parity

_FIXTURES_ROOT = Path(__file__).resolve().parent / "fixtures"


def _enumerate_fixture_rule_dirs() -> list[str]:
    """Walk ``fixtures/<family>/<rule_slug>/`` and return ``family/rule_slug``."""
    if not _FIXTURES_ROOT.is_dir():
        return []
    rule_dirs: list[str] = []
    for family_dir in sorted(_FIXTURES_ROOT.iterdir()):
        if not family_dir.is_dir():
            continue
        for rule_dir in sorted(family_dir.iterdir()):
            if not rule_dir.is_dir():
                continue
            rule_dirs.append(f"{family_dir.name}/{rule_dir.name}")
    return rule_dirs


class TestFixtureInventory:
    """Drift guards on the fixture tree itself."""

    def test_every_fixture_directory_maps_to_a_known_rule(self) -> None:
        """No orphan fixture directories.

        Each ``tests/parity/fixtures/<family>/<rule_slug>/`` must
        correspond to an entry in ``RULE_ID_MAP`` (i.e., a live
        ``buf:``-parity rule in BUILTIN_PACKS or a curated canary
        override). A leftover directory from a deleted/renamed rule
        would silently turn into a happy-path case that always passes.
        """
        fixture_rule_ids = set(_enumerate_fixture_rule_dirs())
        known_rule_ids = set(RULE_ID_MAP.keys())
        orphans = fixture_rule_ids - known_rule_ids
        assert not orphans, (
            f"fixture directories without a corresponding rule in "
            f"RULE_ID_MAP: {sorted(orphans)!r}. Either delete the "
            f"orphan directory, or restore the rule and verify its "
            f"source_spec is 'buf:<RULE_ID>' (or that the canary "
            f"override entry in tests/parity/conftest.py is still "
            f"correct)."
        )

    def test_every_fixture_directory_has_a_buf_yaml(self) -> None:
        """Every per-rule fixture directory must declare its buf.yaml.

        Without ``buf.yaml``, buf v2 cannot run lint against the
        fixture and the parity test would silently fail with an
        unhelpful diagnostic. The forward guard (rule has fixtures)
        and the per-fixture proto files don't catch a missing
        ``buf.yaml`` since the test only reads .proto files.
        """
        missing: list[str] = []
        for rule_dir_str in _enumerate_fixture_rule_dirs():
            rule_dir = _FIXTURES_ROOT / rule_dir_str
            if not (rule_dir / "buf.yaml").is_file():
                missing.append(rule_dir_str)
        assert not missing, (
            f"fixture directories without a buf.yaml: {missing!r}. "
            f"Every per-rule fixture needs ``version: v2`` + "
            f"``lint: use: [<RULE_ID>]`` so buf knows what to check."
        )
