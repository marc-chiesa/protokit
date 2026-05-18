"""D6b U6 — R7 PACKAGE_SAME_* end-to-end parity verification.

Asserts protokit's PACKAGE_SAME_*-rule_id-scoped findings byte-match
buf v1.69.0's recorded NDJSON snapshots (committed at D6b U4a,
SHA-pinned by ``tests/schema/lint/test_buf_smoke_recorded_checksums.py``)
per-fixture, on identical multi-file inputs.

This module deliberately does NOT apply ``pytestmark = pytest.mark.parity``
(KD-2 in the U6 plan). U6's recorded-snapshot mode has no BUF_BINARY
dependency, so the tests run in the required ``test`` CI job on every
PR rather than the advisory ``parity`` job. The marker would gate them
behind the advisory job (per ``.github/workflows/ci.yml`` and
``pyproject.toml:86-87``), which is exactly the visibility gap U6 is
built to close.

Post-U7 contract (KD-4): when U7 flips ``BUILTIN_PACKS`` to include the
PACKAGE_SAME_* family, the ``--rule-pack=protokit.schema.lint.rules.package_same``
flag in ``test_parity_byte_matches_recorded_snapshot`` becomes a deliberate
no-op — ``LintEngine.load_rule_pack`` is idempotent by module name
(``src/protokit/schema/lint/engine.py:241-242``), so duplicate loads are
short-circuited silently. The flag is retained for documentation value
(naming the scope explicitly even when implicit via BUILTIN_PACKS).

Per-fixture rule scoping (KD-7): each fixture's ``buf.yaml use:[]``
declaration names exactly one PACKAGE_SAME_* rule. The parametrize
source derives ``(fixture_name → protokit_rule_id)`` at module-import
time via ``yaml.safe_load`` of the top-level ``lint.use`` key (NOT
module-scoped ``modules[].lint.use``). Comparison is scoped to that
single rule_id (NOT the full R7 family) so latent symmetry violations
(e.g., a future helper edit firing ``package/same-java-package`` on a
``go_package``-only fixture) surface as over-firing complement failures
rather than silent passes.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest
import yaml

from protokit.schema.lint.decorator import get_lint_spec
from protokit.schema.lint.rules import package_same as _package_same_mod

# Helpers from the multi-file extension (D6b U6) live next to their
# single-file siblings in tests/parity/conftest.py.
from tests.parity.conftest import (
    assert_parity_multi_file,
    parse_buf_recorded_snapshot,
    run_protokit_lint_multi_file,
    skip_if_buf_deprecated,
)

# Cross-module SSOT: KD-3 imports _SMOKE_FIXTURES + _smoke_root from
# the smoke-assumptions module so U6 and the smoke-drift gate stay in
# lockstep. Drift is caught by the R25(b)/R25(c) invariants below.
from tests.schema.lint.test_buf_smoke_assumptions import (
    _SMOKE_FIXTURES,
    _smoke_root,
)

# ---- KD-1: local rule-id maps (bypass BUILTIN_PACKS-based RULE_ID_MAP) -----


def _extract_buf_rule_id(source_spec: str) -> str | None:
    """Return the buf rule id from a ``buf:RULE_ID`` source_spec.

    Reimplemented locally (rather than imported from
    ``tests/parity/conftest.py:_extract_buf_rule_id``) to avoid a
    cross-module private-symbol dependency; the 5-line function is
    cheaper to duplicate than to expose.
    """
    prefix = "buf:"
    if source_spec.startswith(prefix):
        return source_spec[len(prefix):]
    return None


def _build_package_same_rule_id_map() -> dict[str, str]:
    """Walk the dormant ``package_same.RULES`` tuple and build
    ``{buf_rule_id: protokit_rule_id}``.

    R7 is NOT in ``BUILTIN_PACKS`` until U7 (per KD-4), so
    ``tests/parity/conftest.py:_build_rule_id_map`` does NOT cover R7.
    This local helper keeps U6's rule-id derivation internal without
    forcing a BUILTIN_PACKS dependency on U7 to ship first.
    """
    mapping: dict[str, str] = {}
    for fn in _package_same_mod.RULES:
        spec = get_lint_spec(fn)
        buf_id = _extract_buf_rule_id(spec.source_spec)
        if buf_id is None:
            pytest.fail(
                f"_build_package_same_rule_id_map: rule {spec.rule_id!r} "
                f"has non-buf source_spec {spec.source_spec!r}; "
                f"R7 family invariant violated."
            )
        if buf_id in mapping:
            pytest.fail(
                f"_build_package_same_rule_id_map: duplicate buf_id "
                f"{buf_id!r} maps to both {mapping[buf_id]!r} and "
                f"{spec.rule_id!r}; check for accidental copy."
            )
        mapping[buf_id] = spec.rule_id
    return mapping


#: Forward map: ``buf_rule_id -> protokit_rule_id``. Built once at import.
_PACKAGE_SAME_RULE_ID_MAP: Mapping[str, str] = _build_package_same_rule_id_map()

#: Inverse map: ``protokit_rule_id -> buf_rule_id``. Derived once at import.
#: Both directions documented in KD-1; forward feeds KD-8's fixture mapping,
#: inverse feeds the test body's ``skip_if_buf_deprecated`` call.
_BUF_RULE_ID_MAP: Mapping[str, str] = {
    v: k for k, v in _PACKAGE_SAME_RULE_ID_MAP.items()
}


# ---- KD-7/KD-8: per-fixture rule scoping via buf.yaml use:[] --------------


def _parse_fixture_buf_yaml(fixture_name: str) -> str:
    """Parse ``_buf_smoke/<fixture_name>/buf.yaml`` and return the
    single protokit rule_id corresponding to its ``lint.use[0]`` entry.

    **Parsing contract (KD-7)**: read TOP-level ``lint.use`` only;
    module-scoped ``modules[].lint.use`` (legal in buf v2 schema) is
    NOT consulted. Missing/malformed YAML, missing keys, wrong types,
    multiple ``use[]`` entries, or unknown buf rule_ids all fail
    loudly with the fixture name in the diagnostic.
    """
    buf_yaml_path = _smoke_root() / fixture_name / "buf.yaml"
    if not buf_yaml_path.is_file():
        pytest.fail(
            f"_parse_fixture_buf_yaml({fixture_name}): {buf_yaml_path} "
            f"does not exist. Every _SMOKE_FIXTURES entry must have a "
            f"buf.yaml with a single-element top-level lint.use[]."
        )
    try:
        config = yaml.safe_load(buf_yaml_path.read_text())
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
            f"{type(lint_section).__name__}). Module-scoped "
            f"modules[].lint.use is NOT consulted (KD-7 parsing contract)."
        )
    use_list = lint_section.get("use")
    if not isinstance(use_list, list):
        pytest.fail(
            f"_parse_fixture_buf_yaml({fixture_name}): {buf_yaml_path} "
            f"`lint.use` is not a list (got {type(use_list).__name__})."
        )
    if len(use_list) != 1:
        pytest.fail(
            f"_parse_fixture_buf_yaml({fixture_name}): {buf_yaml_path} "
            f"`lint.use` has {len(use_list)} entries; per-fixture rule "
            f"scoping (KD-7) requires exactly one PACKAGE_SAME_* rule "
            f"per fixture. Got: {use_list!r}"
        )
    buf_rule_id = use_list[0]
    if not isinstance(buf_rule_id, str):
        pytest.fail(
            f"_parse_fixture_buf_yaml({fixture_name}): `lint.use[0]` is "
            f"not a string (got {type(buf_rule_id).__name__}: "
            f"{buf_rule_id!r})."
        )
    if buf_rule_id not in _PACKAGE_SAME_RULE_ID_MAP:
        pytest.fail(
            f"_parse_fixture_buf_yaml({fixture_name}): `lint.use[0]` is "
            f"{buf_rule_id!r} which has no protokit counterpart in "
            f"package_same.RULES. Known buf rule_ids: "
            f"{sorted(_PACKAGE_SAME_RULE_ID_MAP.keys())!r}"
        )
    return _PACKAGE_SAME_RULE_ID_MAP[buf_rule_id]


#: ``fixture_name -> protokit_rule_id``, built at module-import time.
#: Parse errors crash collection (fail-loud posture per KD-8); the
#: per-fixture failure modes are also surfaced individually by R25(d).
_FIXTURE_RULE_ID_MAP: Mapping[str, str] = {
    fixture_name: _parse_fixture_buf_yaml(fixture_name)
    for fixture_name in _SMOKE_FIXTURES
}


# ---- Main parity test (R20-R23, R26) --------------------------------------


_RULE_PACK = "protokit.schema.lint.rules.package_same"


def _case_id(fixture_name: str, protokit_rule_id: str) -> str:
    """Render a readable parametrize id like ``mixed-value-java-package-same-java-package``."""
    rid_short = (
        protokit_rule_id.split("/", 1)[1]
        if "/" in protokit_rule_id
        else protokit_rule_id
    )
    return f"{fixture_name}-{rid_short}"


@pytest.mark.parametrize(
    ("fixture_name", "protokit_rule_id"),
    list(_FIXTURE_RULE_ID_MAP.items()),
    ids=[_case_id(n, r) for n, r in _FIXTURE_RULE_ID_MAP.items()],
)
def test_parity_byte_matches_recorded_snapshot(
    fixture_name: str, protokit_rule_id: str
) -> None:
    """For each fixture, assert protokit's PACKAGE_SAME_*-scoped findings
    byte-match buf v1.69.0's recorded snapshot for the single rule_id
    pinned by that fixture's ``buf.yaml use:[0]`` (KD-7).

    Invocation:

      1. Walk the fixture directory recursively (handles 2-3-file fixtures
         + nested ``google/api/*.proto`` and ``google/protobuf/*.proto``).
      2. Invoke ``protokit lint --proto --format json --rule-pack ...
         package_same`` with ``cwd=fixture_dir`` and ``-I .`` so emitted
         ``location`` paths are fixture-root-relative.
      3. Parse the recorded ``recorded/<fixture>.json`` NDJSON snapshot.
      4. Assert per-file finding-set parity scoped to the derived rule_id
         (over-firing complement included — any R7-family finding outside
         the scope fails the test).

    Empty recorded snapshots (``all-agree.json``, ``wkt-only.json`` —
    both SHA ``e3b0c44...`` by design) assert protokit produces zero
    R7 findings.
    """
    buf_rule_id = _BUF_RULE_ID_MAP[protokit_rule_id]
    # Future-proofing per [[upstream-rule-deprecation-skip-ordering-parity-harness-2026-05-13]]
    # — no PACKAGE_SAME_* is currently in _BUF_DEPRECATED_RULES, but
    # call the helper unconditionally so a future buf deprecation
    # surfaces as a clean skip rather than a parity failure.
    skip_if_buf_deprecated(buf_rule_id, protokit_rule_id)
    fixture_dir = _smoke_root() / fixture_name
    snapshot_path = _smoke_root() / "recorded" / f"{fixture_name}.json"
    protokit_findings = run_protokit_lint_multi_file(
        fixture_dir, rule_pack=_RULE_PACK
    )
    buf_findings = parse_buf_recorded_snapshot(snapshot_path)
    assert_parity_multi_file(
        protokit_findings,
        buf_findings,
        protokit_rule_ids=frozenset({protokit_rule_id}),
        fixture_scenario=fixture_name,
    )


# ---- R25 collection-time invariants (a-e) ---------------------------------


def test_every_package_same_rule_has_at_least_one_firing_fixture() -> None:
    """R25(a): every R7 protokit rule_id appears in at least one fixture's
    expected-fires set.

    Catches "added an R7 rule but forgot to back it with a fixture".
    This is a fixture-coverage smoke check — over-firing is caught at
    test time by ``assert_parity_multi_file``'s two-sided check.
    """
    expected_rule_ids: set[str] = {
        get_lint_spec(fn).rule_id for fn in _package_same_mod.RULES
    }
    covered_rule_ids: set[str] = set(_FIXTURE_RULE_ID_MAP.values())
    missing = expected_rule_ids - covered_rule_ids
    assert not missing, (
        f"R7 rule_ids without any backing fixture: {sorted(missing)!r}. "
        f"Add a fixture under "
        f"tests/schema/lint/rules/fixtures/package_same/_buf_smoke/ "
        f"that pins one of these rules via buf.yaml lint.use:[]."
    )


def test_fixture_list_matches_smoke_assumptions() -> None:
    """R25(b): U6's local fixture-set matches ``_SMOKE_FIXTURES`` from
    ``tests.schema.lint.test_buf_smoke_assumptions``.

    Catches "added a smoke fixture but forgot the parity test" and
    "U6 silently re-defined the fixture list".
    """
    u6_fixtures = set(_FIXTURE_RULE_ID_MAP.keys())
    smoke_fixtures = set(_SMOKE_FIXTURES)
    assert u6_fixtures == smoke_fixtures, (
        f"U6 fixture set != _SMOKE_FIXTURES.\n"
        f"  Only in U6: {sorted(u6_fixtures - smoke_fixtures)!r}\n"
        f"  Only in smoke: {sorted(smoke_fixtures - u6_fixtures)!r}"
    )


def test_every_recorded_snapshot_is_reachable() -> None:
    """R25(c): bidirectional invariant on recorded snapshots ↔ ``_SMOKE_FIXTURES``.

    (a) every ``recorded/*.json`` file (explicit ``.json`` suffix filter,
        excludes ``CHECKSUMS.sha256``) corresponds to a ``_SMOKE_FIXTURES``
        entry.
    (b) every ``_SMOKE_FIXTURES`` entry has both a fixture directory at
        ``_buf_smoke/<name>/`` AND a recorded snapshot at
        ``_buf_smoke/recorded/<name>.json``.

    Catches orphan snapshots, missing snapshots, and fixture/snapshot
    rename drift in one pass. The forward-only check would not catch
    "entry added to _SMOKE_FIXTURES but recorded file never committed";
    the bidirectional version is the value-add.
    """
    recorded_dir = _smoke_root() / "recorded"
    snapshot_stems: set[str] = {
        p.stem for p in sorted(recorded_dir.glob("*.json"))
        if p.suffix == ".json"
    }
    smoke_fixtures = set(_SMOKE_FIXTURES)
    orphan_snapshots = snapshot_stems - smoke_fixtures
    assert not orphan_snapshots, (
        f"Recorded snapshots without a _SMOKE_FIXTURES entry: "
        f"{sorted(orphan_snapshots)!r}. Either add the fixture to "
        f"_SMOKE_FIXTURES (and add a parity case) or delete the orphan "
        f"snapshot."
    )
    for fixture_name in _SMOKE_FIXTURES:
        fixture_dir = _smoke_root() / fixture_name
        snapshot_path = recorded_dir / f"{fixture_name}.json"
        assert fixture_dir.is_dir(), (
            f"_SMOKE_FIXTURES entry {fixture_name!r} has no fixture "
            f"directory at {fixture_dir}."
        )
        assert snapshot_path.is_file(), (
            f"_SMOKE_FIXTURES entry {fixture_name!r} has no recorded "
            f"snapshot at {snapshot_path}."
        )


def test_every_fixture_buf_yaml_pins_one_r7_rule() -> None:
    """R25(d): every fixture's ``buf.yaml lint.use`` is a single-element
    list whose value maps to a known protokit R7 rule_id.

    This is the load-bearing precondition for KD-7's per-fixture
    rule-scoping approach — also exercised by
    ``_parse_fixture_buf_yaml`` at module-import time. This test makes
    the contract individually visible per fixture so a regression
    surfaces as a single test failure rather than a collection crash.
    """
    for fixture_name in _SMOKE_FIXTURES:
        protokit_rule_id = _parse_fixture_buf_yaml(fixture_name)
        assert protokit_rule_id in _BUF_RULE_ID_MAP, (
            f"Fixture {fixture_name!r} maps to protokit rule "
            f"{protokit_rule_id!r} which is not in the R7 family."
        )


def test_buf_yaml_rule_matches_recorded_findings_rule() -> None:
    """R25(e): non-empty recorded snapshot's unique ``type`` field equals
    the rule_id derived from that fixture's ``buf.yaml use[0]``.

    Catches the drift mode where a contributor edits a fixture's
    ``buf.yaml`` without re-capturing the snapshot (or vice versa).
    Empty snapshots (``all-agree.json``, ``wkt-only.json`` — both SHA
    ``e3b0c44...`` by design) are exempt: no findings means no ``type``
    field to cross-check, and the empty contract is verified by the
    SHA pin.

    Without this check, per-fixture rule scoping could pass false-positive
    parity by comparing protokit's findings for the wrong rule_id against
    a snapshot's findings for a different rule_id.
    """
    for fixture_name in _SMOKE_FIXTURES:
        snapshot_path = _smoke_root() / "recorded" / f"{fixture_name}.json"
        buf_findings = parse_buf_recorded_snapshot(snapshot_path)
        if not buf_findings:
            continue
        unique_types = {f.type for f in buf_findings}
        assert len(unique_types) == 1, (
            f"Fixture {fixture_name!r} recorded snapshot contains "
            f"multiple buf rule_ids: {sorted(unique_types)!r}. R25(d) "
            f"requires single-rule fixtures; the snapshot must contain "
            f"findings for exactly one buf rule_id."
        )
        snapshot_buf_id = unique_types.pop()
        protokit_rule_id = _FIXTURE_RULE_ID_MAP[fixture_name]
        expected_buf_id = _BUF_RULE_ID_MAP[protokit_rule_id]
        assert snapshot_buf_id == expected_buf_id, (
            f"Fixture {fixture_name!r}: buf.yaml pins "
            f"{expected_buf_id!r} but recorded snapshot has findings "
            f"for {snapshot_buf_id!r}. Either the fixture's buf.yaml "
            f"was edited without re-capturing the snapshot, or the "
            f"snapshot was re-captured against a different buf.yaml "
            f"and CHECKSUMS.sha256 was updated. Re-run buf against the "
            f"fixture and update the snapshot (+ CHECKSUMS.sha256), OR "
            f"revert the buf.yaml edit."
        )
