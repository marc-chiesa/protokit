"""D6e U3 — PACKAGE_NO_IMPORT_CYCLE end-to-end parity verification.

Asserts protokit's ``package/no-import-cycle`` findings byte-match buf
v1.69.0's recorded NDJSON snapshots (committed at U3 implementation
time, 2026-05-22) per-fixture, on identical multi-file inputs.

Per the U3 Phase 0 + ce:review session 2026-05-22 user decision
(Option B over Option A FileLocation-without-line): byte-equivalent
buf parity means matching not just the FINDING SET but also the
line/column of each finding (buf points at the offending ``import``
statement; protokit emits at ``FileLocation(file, line, column)``
populated from ``SourceCodeInfo.Location`` keyed on the dependency
field's path ``[3, dep_index]``).

This module follows the per-family pattern established by D6c U3's
``test_parity_package_directory.py``: per-family fixture list at
``tests/_buf_helpers.PACKAGE_NO_IMPORT_CYCLE_SMOKE_FIXTURES``,
per-family conftest constants
(``_D6E_PACKAGE_NO_IMPORT_CYCLE_RULE_IDS`` +
``_D6E_PACKAGE_NO_IMPORT_CYCLE_PROTO_TO_BUF``), and per-family
recorded snapshots at ``_buf_smoke/recorded/<fixture>.json``.

Unlike D6c U3's harness, this module does NOT need cofire
discrimination — U3 is the only rule in its family (single-entry
inclusion set). The per-fixture ``buf.yaml lint.use[]`` is therefore
always ``["PACKAGE_NO_IMPORT_CYCLE"]``; parsing is simplified to a
single-rule expectation.

Like D6c U3, this module deliberately does NOT apply
``pytestmark = pytest.mark.parity``. The recorded-snapshot mode has
no BUF_BINARY dependency, so the tests run in the required ``test``
CI job on every PR rather than the advisory ``parity`` job.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Cross-module SSOT: PACKAGE_NO_IMPORT_CYCLE_SMOKE_FIXTURES +
# package_no_import_cycle_smoke_root live in tests/_buf_helpers.py.
from tests._buf_helpers import (
    PACKAGE_NO_IMPORT_CYCLE_SMOKE_FIXTURES,
    package_no_import_cycle_smoke_root,
)

# Conftest SSOTs for the family-aware partition.
from tests.parity.conftest import (
    _D6E_PACKAGE_NO_IMPORT_CYCLE_PROTO_TO_BUF,
    _D6E_PACKAGE_NO_IMPORT_CYCLE_RULE_IDS,
    assert_parity_multi_file,
    parse_buf_recorded_snapshot,
    run_protokit_lint_multi_file,
    skip_if_buf_deprecated,
)

_SMOKE_FIXTURES = PACKAGE_NO_IMPORT_CYCLE_SMOKE_FIXTURES
_smoke_root = package_no_import_cycle_smoke_root


@pytest.mark.parametrize(
    "fixture_name",
    list(_SMOKE_FIXTURES),
    ids=list(_SMOKE_FIXTURES),
)
def test_parity_byte_matches_recorded_snapshot(
    fixture_name: str,
) -> None:
    """Per-fixture parity gate against buf v1.69.0 recorded snapshots.

    Two-tier assertion (ce:review U3 T1/ADV-002/Agent-native W2 fix,
    2026-05-22):

      1. **Finding-set parity** (via :func:`assert_parity_multi_file`):
         scope-checked ``(rule_id, file, message)`` triples match
         between protokit and buf. This is the file-granularity gate.
      2. **Line/column byte-equivalence** (per-finding loop below):
         protokit's ``location_line`` / ``location_column`` match
         buf's ``start_line`` / ``start_column`` for every scoped
         finding. This is what makes the Option B
         "byte-equivalent buf parity" claim actually testable.
         Without this loop, a regression in
         :func:`_import_source_position` (e.g., off-by-one in the
         0→1 conversion, wrong field number, missing
         ``include_source_info`` plumbing) would slip through the
         finding-set gate silently because location strings would
         still match at the file-path level.

    Invocation:

      1. Walk the fixture directory recursively (multi-file fixtures
         with subdirectories like ``pkg_a/`` + ``pkg_b/``).
      2. Invoke ``protokit lint --proto --format json`` with
         ``cwd=fixture_dir`` and ``-I .`` so emitted ``location_file``
         paths are fixture-root-relative. ``package/no-import-cycle``
         loads via ``BUILTIN_PACKS`` (D6e U3 promotion) — no explicit
         ``--rule-pack`` flag needed.
      3. Parse the recorded ``recorded/<fixture>.json`` NDJSON snapshot.
      4. Assert finding-set parity scoped to U3's single-entry
         inclusion set.
      5. Build a ``(path, message) → (start_line, start_column)``
         map from buf snapshot entries scoped to
         PACKAGE_NO_IMPORT_CYCLE; for each protokit finding with
         the same rule_id, assert location_line / location_column
         match.

    Empty recorded snapshots (``no_cycle_baseline.json``) assert
    protokit produces zero ``package/no-import-cycle`` findings on
    that fixture; the line/column loop is a no-op in that case.
    """
    # Future-proofing per
    # [[upstream-rule-deprecation-skip-ordering-parity-harness-2026-05-13]]
    # — PACKAGE_NO_IMPORT_CYCLE is not currently in
    # ``_BUF_DEPRECATED_RULES``, but call the helper unconditionally so
    # a future buf deprecation surfaces as a clean skip rather than a
    # parity failure.
    skip_if_buf_deprecated(
        "PACKAGE_NO_IMPORT_CYCLE", "package/no-import-cycle",
    )
    fixture_dir = _smoke_root() / fixture_name
    snapshot_path = _smoke_root() / "recorded" / f"{fixture_name}.json"
    protokit_findings = run_protokit_lint_multi_file(fixture_dir)
    buf_findings = parse_buf_recorded_snapshot(snapshot_path)
    # Tier 1: finding-set parity (file-granularity).
    assert_parity_multi_file(
        protokit_findings,
        buf_findings,
        protokit_rule_ids=_D6E_PACKAGE_NO_IMPORT_CYCLE_RULE_IDS,
        fixture_scenario=fixture_name,
    )
    # Tier 2: line/column byte-equivalence per finding.
    buf_position_map: dict[tuple[str, str], tuple[int, int]] = {
        (bf.path, bf.message): (bf.start_line, bf.start_column)
        for bf in buf_findings
        if bf.type == "PACKAGE_NO_IMPORT_CYCLE"
    }
    for pf in protokit_findings:
        if pf.get("rule_id") != "package/no-import-cycle":
            continue
        pf_file = str(pf.get("location_file", ""))
        pf_message = str(pf.get("message", ""))
        pf_line = pf.get("location_line")
        pf_column = pf.get("location_column")
        expected = buf_position_map.get((pf_file, pf_message))
        assert expected is not None, (
            f"line/column parity ({fixture_name}): protokit finding "
            f"({pf_file!r}, message={pf_message!r}) has no matching "
            f"buf snapshot entry. The finding-set gate above should "
            f"have caught this; reaching here means a path or "
            f"message divergence slipped past Tier 1."
        )
        expected_line, expected_column = expected
        assert pf_line == expected_line, (
            f"line/column parity ({fixture_name}): {pf_file!r} "
            f"expected line={expected_line}, got {pf_line!r}. "
            f"Check _import_source_position 0→1 conversion + "
            f"SourceCodeInfo.Location path=[3, dep_index] lookup."
        )
        assert pf_column == expected_column, (
            f"line/column parity ({fixture_name}): {pf_file!r}:"
            f"{pf_line} expected column={expected_column}, got "
            f"{pf_column!r}. Check _import_source_position span "
            f"index arithmetic."
        )


# ---- Collection-time invariants ------------------------------------------


def test_every_d6e_u3_rule_has_at_least_one_associated_fixture() -> None:
    """``package/no-import-cycle`` has at least one fixture that fires it.

    Mirrors the R8/R8b family invariant at
    ``test_parity_package_directory.py``. With U3's inclusion set being
    a single rule_id, this check is degenerate but kept for symmetry +
    future-proofing if the family grows.
    """
    assert _D6E_PACKAGE_NO_IMPORT_CYCLE_PROTO_TO_BUF, (
        "package/no-import-cycle is missing from the U3 family map. "
        "Check that the rule's source_spec is buf:PACKAGE_NO_IMPORT_CYCLE."
    )


def test_fixture_list_matches_on_disk_directories() -> None:
    """PACKAGE_NO_IMPORT_CYCLE_SMOKE_FIXTURES matches the on-disk dirs.

    ce:review U3 KP-6/T9 (2026-05-22): the prior form
    (``set(_SMOKE_FIXTURES) == set(_SMOKE_FIXTURES)``) was a
    tautology that always passed by reflexivity — could not
    catch any drift. Replaced with a meaningful invariant:
    the SSOT tuple matches the actual fixture directories on
    disk, modulo the ``recorded/`` snapshot directory.

    Catches the case where someone adds a new fixture directory
    but forgets to add it to PACKAGE_NO_IMPORT_CYCLE_SMOKE_FIXTURES,
    OR removes a fixture from the tuple without deleting the
    directory.
    """
    smoke_dirs = {
        p.name
        for p in _smoke_root().iterdir()
        if p.is_dir() and p.name != "recorded"
    }
    declared_fixtures = set(_SMOKE_FIXTURES)
    only_on_disk = smoke_dirs - declared_fixtures
    only_in_tuple = declared_fixtures - smoke_dirs
    assert not only_on_disk, (
        f"Fixture directories on disk but absent from "
        f"PACKAGE_NO_IMPORT_CYCLE_SMOKE_FIXTURES: "
        f"{sorted(only_on_disk)!r}. Add to the tuple in "
        f"tests/_buf_helpers.py."
    )
    assert not only_in_tuple, (
        f"PACKAGE_NO_IMPORT_CYCLE_SMOKE_FIXTURES entries with no "
        f"on-disk directory: {sorted(only_in_tuple)!r}. Either "
        f"create the fixture directory or remove the entry."
    )


def test_every_recorded_snapshot_is_reachable() -> None:
    """Every recorded snapshot has a fixture + every fixture has a snapshot.

    Mirrors D6c U3's bidirectional invariant. Prevents orphan
    snapshots (renamed-but-not-deleted) and missing snapshots
    (fixture added without recording).
    """
    recorded_dir = _smoke_root() / "recorded"
    snapshot_stems: set[str] = {
        p.stem for p in sorted(recorded_dir.glob("*.json"))
        if p.suffix == ".json"
    }
    smoke_fixtures = set(_SMOKE_FIXTURES)
    orphan_snapshots = snapshot_stems - smoke_fixtures
    assert not orphan_snapshots, (
        f"Recorded snapshots without a PACKAGE_NO_IMPORT_CYCLE_SMOKE_"
        f"FIXTURES entry: {sorted(orphan_snapshots)!r}. Either add the "
        f"fixture to the tuple or delete the orphan snapshot."
    )
    for fixture_name in _SMOKE_FIXTURES:
        fixture_dir: Path = _smoke_root() / fixture_name
        snapshot_path = recorded_dir / f"{fixture_name}.json"
        assert fixture_dir.is_dir(), (
            f"PACKAGE_NO_IMPORT_CYCLE_SMOKE_FIXTURES entry "
            f"{fixture_name!r} has no fixture directory at "
            f"{fixture_dir}."
        )
        assert snapshot_path.is_file(), (
            f"PACKAGE_NO_IMPORT_CYCLE_SMOKE_FIXTURES entry "
            f"{fixture_name!r} has no recorded snapshot at "
            f"{snapshot_path}."
        )
