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


# Per the D6c U3 ce:review (adversarial Finding #10, P3/0.97): the two
# empty snapshots ``matched-dir.json`` and ``single-file-dir.json`` share
# the empty-bytes SHA ``e3b0c44...`` by design. A filename swap between
# them (e.g., a contributor renames the directory but forgets to rename
# the snapshot) is invisible to both the checksum gate above AND the
# parity test (both expect zero findings on these fixtures). The
# structural anchor below pins WHICH specific fixtures are SUPPOSED to
# produce empty snapshots so a swap fails loudly here rather than
# silently passing the rest of the harness.
_EXPECTED_EMPTY_FIXTURES: frozenset[str] = frozenset({
    "matched-dir",
    "single-file-dir",
})

_EMPTY_BYTES_SHA256 = (
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
)


def test_empty_snapshots_anchor_intended_fixtures() -> None:
    """Pin which fixtures are SUPPOSED to produce empty snapshots.

    Both ``matched-dir.json`` (R8 happy path — 2 files in same dir,
    same package) and ``single-file-dir.json`` (single file — both
    rules silent) are empty by design. They share the SHA-256 of zero
    bytes (``e3b0c44...``).

    Without this anchor:
      - The checksum gate above accepts both fixtures' empty SHAs
        independently (they're listed in CHECKSUMS.sha256 with the
        same hash).
      - A filename swap (e.g., contributor accidentally moves
        ``matched-dir/`` content into ``single-file-dir/`` and
        vice-versa) preserves "buf emits 0 findings" for both
        fixtures, so the parity test passes vacuously.
      - The two recorded files would still pass the SHA check (both
        empty).

    This anchor pins the **set of fixtures expected to be empty**.
    A future change that legitimately adds an empty-snapshot fixture
    requires editing this set; a swap that accidentally adds a new
    fixture to the empty set (or removes one) fails here.
    """
    actual_empty: set[str] = set()
    for basename, digest in _CHECKSUMS_PINNED.items():
        if digest == _EMPTY_BYTES_SHA256:
            actual_empty.add(basename.removesuffix(".json"))
    assert actual_empty == _EXPECTED_EMPTY_FIXTURES, (
        f"Empty-snapshot fixture set drifted from the documented anchor.\n"
        f"  Pinned to be empty: {sorted(_EXPECTED_EMPTY_FIXTURES)!r}\n"
        f"  Actually empty:     {sorted(actual_empty)!r}\n"
        f"  Newly empty (not in anchor): "
        f"{sorted(actual_empty - _EXPECTED_EMPTY_FIXTURES)!r}\n"
        f"  No longer empty (in anchor): "
        f"{sorted(_EXPECTED_EMPTY_FIXTURES - actual_empty)!r}\n"
        f"\n"
        f"If a fixture intentionally became empty (e.g., a buf-version "
        f"change made it clean), update _EXPECTED_EMPTY_FIXTURES. If a "
        f"fixture accidentally became empty, regenerate the snapshot."
    )
