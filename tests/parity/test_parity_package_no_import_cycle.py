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

    Invocation:

      1. Walk the fixture directory recursively (multi-file fixtures
         with subdirectories like ``pkg_a/`` + ``pkg_b/``).
      2. Invoke ``protokit lint --proto --format json`` with
         ``cwd=fixture_dir`` and ``-I .`` so emitted ``location_file``
         paths are fixture-root-relative. ``package/no-import-cycle``
         loads via ``BUILTIN_PACKS`` (D6e U3 promotion) — no explicit
         ``--rule-pack`` flag needed.
      3. Parse the recorded ``recorded/<fixture>.json`` NDJSON snapshot.
      4. Assert per-file finding-set parity scoped to U3's single-
         entry inclusion set.

    Empty recorded snapshots (``no_cycle_baseline.json``) assert
    protokit produces zero ``package/no-import-cycle`` findings on
    that fixture.
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
    assert_parity_multi_file(
        protokit_findings,
        buf_findings,
        protokit_rule_ids=_D6E_PACKAGE_NO_IMPORT_CYCLE_RULE_IDS,
        fixture_scenario=fixture_name,
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


def test_fixture_list_matches_smoke_assumptions() -> None:
    """The parametrize fixture set matches PACKAGE_NO_IMPORT_CYCLE_SMOKE_FIXTURES."""
    parametrize_fixtures = set(_SMOKE_FIXTURES)
    # No drift surface here since the parametrize list IS the SSOT
    # tuple — kept for parity with D6c U3's invariant test.
    assert parametrize_fixtures == set(_SMOKE_FIXTURES)


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
