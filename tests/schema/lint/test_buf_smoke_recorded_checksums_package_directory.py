"""SHA-256 integrity check for D6c U3 R8/R8b recorded snapshots.

Parallel to :mod:`tests.schema.lint.test_buf_smoke_recorded_checksums`
(which covers R7's 21 snapshots) — catches accidental snapshot edits
and tamper by comparing each ``recorded/*.json`` file's actual
SHA-256 against the value pinned in ``CHECKSUMS.sha256``.

Runs by default — no ``BUF_BINARY`` dependency. Sister test
:mod:`tests.schema.lint.test_buf_smoke_assumptions_package_directory`
(live mode, gated on BUF_BINARY) catches buf-version drift on the
parity job.

When buf-version bumps require regenerating snapshots (a deliberate
``_BUF_PARITY_PIN`` bump), regenerate the checksum file via:

    cd tests/schema/lint/rules/fixtures/package_directory/_buf_smoke/recorded
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
    / "package_directory"
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
        parts = line.split()
        if len(parts) < 2:
            pytest.fail(
                f"malformed CHECKSUMS.sha256 line: {line!r} (expected "
                f"`<hex>  <basename>`)"
            )
        digest = parts[0]
        basename = parts[-1]
        pinned[basename] = digest
    return pinned


def _compute_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


_CHECKSUMS_PINNED = _parse_checksums()


@pytest.mark.parametrize("basename", sorted(_CHECKSUMS_PINNED.keys()))
def test_recorded_snapshot_sha256_matches_pinned(basename: str) -> None:
    """Each recorded JSON file's SHA-256 matches the pinned value."""
    snapshot_path = _RECORDED_ROOT / basename
    assert snapshot_path.is_file(), (
        f"recorded snapshot missing: {snapshot_path}"
    )
    actual = _compute_sha256(snapshot_path)
    expected = _CHECKSUMS_PINNED[basename]
    assert actual == expected, (
        f"SHA-256 mismatch for {basename}:\n"
        f"  Pinned:   {expected}\n"
        f"  Actual:   {actual}\n"
        f"Either the snapshot was edited (regenerate CHECKSUMS.sha256 "
        f"in the same commit) or the file is corrupted."
    )


def test_every_recorded_file_is_pinned() -> None:
    """``CHECKSUMS.sha256`` covers every ``*.json`` in ``recorded/``.

    Catches the failure mode where a new snapshot is added but
    CHECKSUMS.sha256 is not regenerated.
    """
    on_disk = {p.name for p in _RECORDED_ROOT.glob("*.json")}
    pinned = set(_CHECKSUMS_PINNED.keys())
    unpinned = on_disk - pinned
    assert not unpinned, (
        f"Recorded snapshots without a CHECKSUMS.sha256 entry: "
        f"{sorted(unpinned)!r}. Regenerate via "
        f"`shasum -a 256 *.json | sort > CHECKSUMS.sha256`."
    )
    extraneous = pinned - on_disk
    assert not extraneous, (
        f"CHECKSUMS.sha256 entries without a corresponding recorded "
        f"snapshot: {sorted(extraneous)!r}. Remove the orphan entries."
    )
