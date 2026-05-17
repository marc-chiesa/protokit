"""SHA-256 integrity check for the 21 buf smoke recorded snapshots — D6b U4a.

Replaces the dropped ``test_buf_smoke_assumptions.py`` snapshot-consistency
mode (which was tautological — asserted snapshots encode what the plan
claims, both committed together). This test catches accidental snapshot
edits AND tamper by comparing each ``recorded/*.json`` file's actual
SHA-256 against the value pinned in ``CHECKSUMS.sha256``.

Runs by default — no ``BUF_BINARY`` dependency. Sister test
``test_buf_smoke_assumptions.py`` (live mode, gated on BUF_BINARY)
catches buf-version drift on the parity job.

When buf-version bumps require regenerating snapshots (a deliberate
``_BUF_PARITY_PIN`` bump), regenerate the checksum file via:

    cd tests/schema/lint/rules/fixtures/package_same/_buf_smoke/recorded
    shasum -a 256 *.json | sort > CHECKSUMS.sha256

Then commit the new checksums alongside the regenerated snapshots in
the same commit so the integrity gate stays in sync with the pinned
buf version.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

_RECORDED_ROOT = (
    Path(__file__).resolve().parent
    / "rules"
    / "fixtures"
    / "package_same"
    / "_buf_smoke"
    / "recorded"
)
_CHECKSUMS_PATH = _RECORDED_ROOT / "CHECKSUMS.sha256"


def _parse_checksums() -> dict[str, str]:
    """Parse ``shasum -a 256``-style output: ``<hex>  <basename>`` per line."""
    pinned: dict[str, str] = {}
    for raw in _CHECKSUMS_PATH.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # shasum's two-space separator → split on whitespace, take first/last.
        parts = line.split()
        assert len(parts) == 2, f"malformed CHECKSUMS line: {line!r}"
        hex_digest, name = parts
        pinned[name] = hex_digest
    return pinned


def _compute_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestRecordedSnapshotChecksums:
    """Each ``recorded/<name>.json`` SHA-256 matches the pinned value."""

    def test_checksums_file_exists(self) -> None:
        assert _CHECKSUMS_PATH.is_file(), (
            f"CHECKSUMS.sha256 missing at {_CHECKSUMS_PATH}. Regenerate via "
            "'shasum -a 256 *.json | sort > CHECKSUMS.sha256' from the "
            "recorded/ directory."
        )

    def test_all_recorded_snapshots_are_pinned(self) -> None:
        """Every ``recorded/*.json`` has a checksum entry; no orphan snapshots."""
        pinned = _parse_checksums()
        actual_snapshots = {
            p.name for p in _RECORDED_ROOT.glob("*.json")
        }
        missing_pin = actual_snapshots - pinned.keys()
        orphan_pin = pinned.keys() - actual_snapshots
        assert not missing_pin, (
            f"recorded snapshots without CHECKSUMS entries: {sorted(missing_pin)!r}. "
            f"Add them via 'shasum -a 256 ...'."
        )
        assert not orphan_pin, (
            f"CHECKSUMS entries with no matching snapshot: {sorted(orphan_pin)!r}. "
            f"Regenerate CHECKSUMS or restore the missing snapshot files."
        )

    @pytest.mark.parametrize(
        "snapshot_name",
        sorted(p.name for p in _RECORDED_ROOT.glob("*.json")),
    )
    def test_recorded_snapshot_matches_pinned_checksum(
        self, snapshot_name: str,
    ) -> None:
        """``sha256(recorded/<name>.json)`` matches the pinned hex digest."""
        pinned = _parse_checksums()
        assert snapshot_name in pinned, (
            f"{snapshot_name} not pinned in CHECKSUMS.sha256"
        )
        actual = _compute_sha256(_RECORDED_ROOT / snapshot_name)
        assert actual == pinned[snapshot_name], (
            f"{snapshot_name} SHA-256 mismatch:\n"
            f"  pinned:   {pinned[snapshot_name]}\n"
            f"  actual:   {actual}\n"
            f"If this is an intentional buf-version bump, regenerate via "
            f"'shasum -a 256 *.json | sort > CHECKSUMS.sha256' from "
            f"{_RECORDED_ROOT}."
        )
