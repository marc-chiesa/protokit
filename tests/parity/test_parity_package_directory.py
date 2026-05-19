"""D6c U3 — R8 + R8b end-to-end parity verification.

Asserts protokit's R8 (``package/same-directory``) + R8b
(``package/directory-same-package``) findings byte-match buf v1.69.0's
recorded NDJSON snapshots (committed at D6c U3, SHA-pinned by
:mod:`tests.schema.lint.test_buf_smoke_recorded_checksums_package_directory`)
per-fixture, on identical multi-file inputs.

This module deliberately does NOT apply ``pytestmark = pytest.mark.parity``
(KD-2 in the D6b U6 plan, inherited via D6c plan). The recorded-snapshot
mode has no BUF_BINARY dependency, so the tests run in the required
``test`` CI job on every PR rather than the advisory ``parity`` job. The
marker would gate them behind the advisory job, which is exactly the
visibility gap the snapshot harness is built to close.

Since D6c U2 added R8 + R8b to the ``package`` pack (already in
``BUILTIN_PACKS``), ``test_parity_byte_matches_recorded_snapshot``
invokes ``run_protokit_lint_multi_file`` with no explicit ``rule_pack``
kwarg — the rules load via ``BUILTIN_PACKS`` and the parity contract
holds through the same engine-idempotency + ``LintProfile.compose``
frozenset semantics that ``TestPackagePackExplicitLoadIsIdempotent``
(at ``tests/schema/lint/test_cli_rule_pack_dedup_post_d6c.py``)
verifies for the explicit-flag callers.

Per-fixture rule scoping (KD-7 / KTD-10): each fixture's
``buf.yaml use:[]`` declaration names one or two of the D6c rules.
The cofire fixture (``cofire-r8-r8b``) uses both ``PACKAGE_SAME_DIRECTORY``
and ``DIRECTORY_SAME_PACKAGE``; all other fixtures pin a single rule.
The parametrize source derives ``(fixture_name → frozenset[protokit_rule_id])``
at module-import time via ``yaml.safe_load`` of the top-level
``lint.use`` key. Comparison is scoped to the per-fixture rule_id set
(NOT the full D6c family) so latent symmetry violations surface as
over-firing complement failures rather than silent passes.

KTD-12 conftest extension: this module consumes
``_PACKAGE_DIRECTORY_PROTO_TO_BUF`` indirectly via
``assert_parity_multi_file``'s family-aware partition. The R8/R8b family
mapping is built at conftest module-import time from
``protokit.schema.lint.rules.package.RULES`` filtered to the
``_D6C_PACKAGE_DIRECTORY_RULE_IDS`` inclusion set.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest
import yaml

from protokit.schema.lint.decorator import get_lint_spec
from protokit.schema.lint.rules import package as _package_mod

# Cross-module SSOT: PACKAGE_DIRECTORY_SMOKE_FIXTURES +
# package_directory_smoke_root live in tests/_buf_helpers.py. R25(b)/R25(c)
# invariants below pin drift.
from tests._buf_helpers import (
    PACKAGE_DIRECTORY_SMOKE_FIXTURES,
    package_directory_smoke_root,
)

# Helpers from the multi-file extension live next to their single-file
# siblings in tests/parity/conftest.py.
from tests.parity.conftest import (
    assert_parity_multi_file,
    parse_buf_recorded_snapshot,
    run_protokit_lint_multi_file,
    skip_if_buf_deprecated,
)

_SMOKE_FIXTURES = PACKAGE_DIRECTORY_SMOKE_FIXTURES
_smoke_root = package_directory_smoke_root


# ---- Local rule-id maps (parallel to test_parity_package_same.py) ---------


def _extract_buf_rule_id(source_spec: str) -> str | None:
    """Return the buf rule id from a ``buf:RULE_ID`` source_spec.

    Reimplemented locally (rather than imported from
    ``tests/parity/conftest.py:_extract_buf_rule_id``) to avoid a
    cross-module private-symbol dependency.
    """
    prefix = "buf:"
    if source_spec.startswith(prefix):
        return source_spec[len(prefix):]
    return None


# Inclusion set for R8 + R8b — the D6a ``package/defined`` +
# ``package/directory-match`` rules also live in ``package.RULES`` but
# have their own parity coverage at ``tests/parity/test_parity_package.py``
# (single-file harness).
_D6C_RULE_IDS: frozenset[str] = frozenset({
    "package/same-directory",
    "package/directory-same-package",
})


def _build_package_directory_rule_id_map() -> Mapping[str, str]:
    """Walk ``package.RULES`` filtered to R8 + R8b and return
    ``{buf_rule_id: protokit_rule_id}``.

    Local helper for parity-test-module isolation, parallel to R7's
    ``_build_package_same_rule_id_map``. The walk filters by inclusion
    set so D6a's single-file rules don't leak into the multi-file
    harness.
    """
    mapping: dict[str, str] = {}
    for fn in _package_mod.RULES:
        spec = get_lint_spec(fn)
        if spec.rule_id not in _D6C_RULE_IDS:
            continue
        buf_id = _extract_buf_rule_id(spec.source_spec)
        if buf_id is None:
            pytest.fail(
                f"_build_package_directory_rule_id_map: rule "
                f"{spec.rule_id!r} has non-buf source_spec "
                f"{spec.source_spec!r}; D6c family invariant violated."
            )
        if buf_id in mapping:
            pytest.fail(
                f"_build_package_directory_rule_id_map: duplicate "
                f"buf_id {buf_id!r} maps to both {mapping[buf_id]!r} "
                f"and {spec.rule_id!r}; check for accidental copy."
            )
        mapping[buf_id] = spec.rule_id
    return mapping


#: Forward map: ``buf_rule_id -> protokit_rule_id``. Built once at import.
_RULE_ID_MAP: Mapping[str, str] = _build_package_directory_rule_id_map()

#: Inverse map: ``protokit_rule_id -> buf_rule_id``. Derived once at import.
_BUF_RULE_ID_MAP: Mapping[str, str] = {
    v: k for k, v in _RULE_ID_MAP.items()
}


# ---- Per-fixture rule scoping via buf.yaml use:[] -------------------------


def _parse_fixture_buf_yaml(fixture_name: str) -> frozenset[str]:
    """Parse ``_buf_smoke/<fixture_name>/buf.yaml`` and return the
    frozenset of protokit rule_ids corresponding to its ``lint.use``
    entries.

    **Parsing contract**: read TOP-level ``lint.use`` only;
    module-scoped ``modules[].lint.use`` (legal in buf v2 schema) is
    NOT consulted. Returns a frozenset (not a single string) because
    the ``cofire-r8-r8b`` fixture uses TWO rules — per KTD-10. All
    other fixtures use exactly one. Missing/malformed YAML, missing
    keys, wrong types, or unknown buf rule_ids fail loudly with the
    fixture name in the diagnostic.
    """
    buf_yaml_path = _smoke_root() / fixture_name / "buf.yaml"
    if not buf_yaml_path.is_file():
        pytest.fail(
            f"_parse_fixture_buf_yaml({fixture_name}): {buf_yaml_path} "
            f"does not exist. Every PACKAGE_DIRECTORY_SMOKE_FIXTURES "
            f"entry must have a buf.yaml with a non-empty top-level "
            f"lint.use[]."
        )
    try:
        config = yaml.safe_load(buf_yaml_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        pytest.fail(
            f"_parse_fixture_buf_yaml({fixture_name}): malformed YAML at "
            f"{buf_yaml_path}: {exc}"
        )
    if not isinstance(config, dict):
        pytest.fail(
            f"_parse_fixture_buf_yaml({fixture_name}): {buf_yaml_path} "
            f"top-level is not a mapping (got {type(config).__name__})."
        )
    lint_section = config.get("lint")
    if not isinstance(lint_section, dict):
        pytest.fail(
            f"_parse_fixture_buf_yaml({fixture_name}): {buf_yaml_path} "
            f"missing TOP-level `lint:` block (got "
            f"{type(lint_section).__name__})."
        )
    use_list = lint_section.get("use")
    if not isinstance(use_list, list):
        pytest.fail(
            f"_parse_fixture_buf_yaml({fixture_name}): {buf_yaml_path} "
            f"`lint.use` is not a list (got {type(use_list).__name__})."
        )
    if len(use_list) < 1 or len(use_list) > 2:
        pytest.fail(
            f"_parse_fixture_buf_yaml({fixture_name}): {buf_yaml_path} "
            f"`lint.use` has {len(use_list)} entries; D6c per-fixture "
            f"rule scoping allows 1 or 2 rules per fixture (cofire "
            f"fixture uses 2 per KTD-10). Got: {use_list!r}"
        )
    protokit_rule_ids: set[str] = set()
    for buf_rule_id in use_list:
        if not isinstance(buf_rule_id, str):
            pytest.fail(
                f"_parse_fixture_buf_yaml({fixture_name}): `lint.use` "
                f"entry is not a string (got "
                f"{type(buf_rule_id).__name__}: {buf_rule_id!r})."
            )
        if buf_rule_id not in _RULE_ID_MAP:
            pytest.fail(
                f"_parse_fixture_buf_yaml({fixture_name}): `lint.use` "
                f"entry {buf_rule_id!r} has no protokit counterpart in "
                f"the D6c R8/R8b family. Known buf rule_ids: "
                f"{sorted(_RULE_ID_MAP.keys())!r}"
            )
        protokit_rule_ids.add(_RULE_ID_MAP[buf_rule_id])
    return frozenset(protokit_rule_ids)


#: ``fixture_name -> frozenset[protokit_rule_id]``, built at
#: module-import time. Parse errors crash collection (fail-loud
#: posture); the per-fixture failure modes are also surfaced
#: individually by R25(d).
_FIXTURE_RULE_ID_MAP: Mapping[str, frozenset[str]] = {
    fixture_name: _parse_fixture_buf_yaml(fixture_name)
    for fixture_name in _SMOKE_FIXTURES
}


# ---- Main parity test -----------------------------------------------------


def _case_id(fixture_name: str, protokit_rule_ids: frozenset[str]) -> str:
    """Render a readable parametrize id."""
    rule_short = (
        next(iter(protokit_rule_ids))
        .split("/", 1)[1]
        if len(protokit_rule_ids) == 1
        else "cofire"
    )
    return f"{fixture_name}-{rule_short}"


@pytest.mark.parametrize(
    ("fixture_name", "protokit_rule_ids"),
    list(_FIXTURE_RULE_ID_MAP.items()),
    ids=[_case_id(n, r) for n, r in _FIXTURE_RULE_ID_MAP.items()],
)
def test_parity_byte_matches_recorded_snapshot(
    fixture_name: str, protokit_rule_ids: frozenset[str],
) -> None:
    """For each fixture, assert protokit's R8/R8b-scoped findings
    byte-match buf v1.69.0's recorded snapshot for the per-fixture
    rule_id set.

    Invocation:

      1. Walk the fixture directory recursively (handles 2-3-file
         fixtures + nested directories like ``cofire-r8-r8b``).
      2. Invoke ``protokit lint --proto --format json`` with
         ``cwd=fixture_dir`` and ``-I .`` so emitted ``location`` paths
         are fixture-root-relative. R8 + R8b load via ``BUILTIN_PACKS``
         since D6c U2 — no explicit ``--rule-pack`` flag needed.
      3. Parse the recorded ``recorded/<fixture>.json`` NDJSON snapshot.
      4. Assert per-file finding-set parity scoped to the per-fixture
         rule_id set (over-firing complement included).

    Empty recorded snapshots (``matched-dir.json``, ``single-file-dir.json``
    — both SHA ``e3b0c44...`` by design) assert protokit produces zero
    R8/R8b findings on those fixtures.
    """
    # Future-proofing per [[upstream-rule-deprecation-skip-ordering-parity-harness-2026-05-13]]
    # — no D6c rule is currently in _BUF_DEPRECATED_RULES, but call
    # the helper unconditionally so a future buf deprecation surfaces
    # as a clean skip rather than a parity failure.
    for protokit_rule_id in protokit_rule_ids:
        buf_rule_id = _BUF_RULE_ID_MAP[protokit_rule_id]
        skip_if_buf_deprecated(buf_rule_id, protokit_rule_id)
    fixture_dir = _smoke_root() / fixture_name
    snapshot_path = _smoke_root() / "recorded" / f"{fixture_name}.json"
    protokit_findings = run_protokit_lint_multi_file(fixture_dir)
    buf_findings = parse_buf_recorded_snapshot(snapshot_path)
    assert_parity_multi_file(
        protokit_findings,
        buf_findings,
        protokit_rule_ids=protokit_rule_ids,
        fixture_scenario=fixture_name,
    )


# ---- Collection-time invariants (mirroring R7's R25 invariants) -----------


def test_every_d6c_rule_has_at_least_one_associated_fixture() -> None:
    """Every D6c R8 + R8b rule_id appears in at least one fixture's
    expected-fires set.
    """
    expected_rule_ids: set[str] = set(_RULE_ID_MAP.values())
    covered_rule_ids: set[str] = set()
    for rule_ids in _FIXTURE_RULE_ID_MAP.values():
        covered_rule_ids.update(rule_ids)
    missing = expected_rule_ids - covered_rule_ids
    assert not missing, (
        f"D6c R8/R8b rule_ids without any backing fixture: "
        f"{sorted(missing)!r}. Add a fixture under "
        f"tests/schema/lint/rules/fixtures/package_directory/_buf_smoke/ "
        f"that pins one of these rules via buf.yaml lint.use:[]."
    )


def test_fixture_list_matches_smoke_assumptions() -> None:
    """The parametrize fixture set matches ``PACKAGE_DIRECTORY_SMOKE_FIXTURES``
    from ``tests._buf_helpers``.
    """
    parametrize_fixtures = set(_FIXTURE_RULE_ID_MAP.keys())
    smoke_fixtures = set(_SMOKE_FIXTURES)
    assert parametrize_fixtures == smoke_fixtures, (
        f"D6c parametrize fixture set != PACKAGE_DIRECTORY_SMOKE_FIXTURES.\n"
        f"  Only in parametrize: "
        f"{sorted(parametrize_fixtures - smoke_fixtures)!r}\n"
        f"  Only in smoke: {sorted(smoke_fixtures - parametrize_fixtures)!r}"
    )


def test_every_recorded_snapshot_is_reachable() -> None:
    """Bidirectional invariant: every ``recorded/*.json`` corresponds to a
    ``PACKAGE_DIRECTORY_SMOKE_FIXTURES`` entry, and every fixture has
    both a directory + recorded snapshot.
    """
    recorded_dir = _smoke_root() / "recorded"
    snapshot_stems: set[str] = {
        p.stem for p in sorted(recorded_dir.glob("*.json"))
        if p.suffix == ".json"
    }
    smoke_fixtures = set(_SMOKE_FIXTURES)
    orphan_snapshots = snapshot_stems - smoke_fixtures
    assert not orphan_snapshots, (
        f"Recorded snapshots without a PACKAGE_DIRECTORY_SMOKE_FIXTURES "
        f"entry: {sorted(orphan_snapshots)!r}. Either add the fixture "
        f"to the tuple or delete the orphan snapshot."
    )
    for fixture_name in _SMOKE_FIXTURES:
        fixture_dir = _smoke_root() / fixture_name
        snapshot_path = recorded_dir / f"{fixture_name}.json"
        assert fixture_dir.is_dir(), (
            f"PACKAGE_DIRECTORY_SMOKE_FIXTURES entry {fixture_name!r} "
            f"has no fixture directory at {fixture_dir}."
        )
        assert snapshot_path.is_file(), (
            f"PACKAGE_DIRECTORY_SMOKE_FIXTURES entry {fixture_name!r} "
            f"has no recorded snapshot at {snapshot_path}."
        )


def test_every_fixture_buf_yaml_pins_d6c_rules() -> None:
    """Every fixture's ``buf.yaml lint.use`` resolves to known D6c
    rule_ids. Per-fixture failure visibility complements module-import
    fail-loud at ``_parse_fixture_buf_yaml``.
    """
    for fixture_name in _SMOKE_FIXTURES:
        protokit_rule_ids = _parse_fixture_buf_yaml(fixture_name)
        for rule_id in protokit_rule_ids:
            assert rule_id in _BUF_RULE_ID_MAP, (
                f"Fixture {fixture_name!r} maps to protokit rule "
                f"{rule_id!r} which is not in the D6c R8/R8b family."
            )


def test_buf_yaml_rule_matches_recorded_findings_rule() -> None:
    """Non-empty recorded snapshot's unique ``type`` values are a subset
    of the rule_ids derived from that fixture's ``buf.yaml use``.

    Catches the drift mode where a contributor edits a fixture's
    ``buf.yaml`` without re-capturing the snapshot (or vice versa).
    Empty snapshots (``matched-dir``, ``single-file-dir`` — both SHA
    ``e3b0c44...`` by design) are exempt.

    For the cofire fixture (use:[2 rules]), the snapshot's ``type``
    values must be a subset of {DIRECTORY_SAME_PACKAGE,
    PACKAGE_SAME_DIRECTORY}; equality is NOT required because a fixture
    may exercise one rule's sad path while the other is silent on the
    same input.
    """
    for fixture_name in _SMOKE_FIXTURES:
        snapshot_path = _smoke_root() / "recorded" / f"{fixture_name}.json"
        buf_findings = parse_buf_recorded_snapshot(snapshot_path)
        if not buf_findings:
            continue
        snapshot_types = {f.type for f in buf_findings}
        protokit_rule_ids = _FIXTURE_RULE_ID_MAP[fixture_name]
        expected_buf_ids: set[str] = {
            _BUF_RULE_ID_MAP[rid] for rid in protokit_rule_ids
        }
        assert snapshot_types <= expected_buf_ids, (
            f"Fixture {fixture_name!r}: buf.yaml pins "
            f"{sorted(expected_buf_ids)!r} but recorded snapshot "
            f"contains findings for "
            f"{sorted(snapshot_types - expected_buf_ids)!r}. Either the "
            f"fixture's buf.yaml was edited without re-capturing the "
            f"snapshot, or the snapshot was re-captured against a "
            f"different buf.yaml. Re-run buf against the fixture and "
            f"update the snapshot (+ CHECKSUMS.sha256), OR revert the "
            f"buf.yaml edit."
        )
