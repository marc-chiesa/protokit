---
title: D6b U6 — R7 PACKAGE_SAME_* end-to-end parity verification
type: feat
status: active
date: 2026-05-18
origin: docs/brainstorms/2026-05-18-d6b-u6-r7-package-same-parity-tests-requirements.md
---

# D6b U6 — R7 PACKAGE_SAME_* end-to-end parity verification

## Overview

Add `tests/parity/test_parity_package_same.py` — a new parity test module that asserts protokit's PACKAGE_SAME_*-rule_id-scoped findings byte-match buf v1.69.0's recorded NDJSON snapshots across 21 multi-file fixtures. Extend `tests/parity/conftest.py` with three new helpers for multi-file linter invocation (R8 in D6c is the next known multi-file rule and a *candidate* reuse target — whether its cross-file semantics actually reuse this shape is validated when R8 lands). Land 5 collection-time invariants that prevent silent drift between the parity tests, U4a's empirical snapshots, U4b's R7 rule implementations, and the per-fixture `buf.yaml use:[]` declarations.

This is the **empirical regression-gate** between U4b's dormant-code ship and U7's BUILTIN_PACKS default-on flip. Recorded-snapshot mode — no BUF_BINARY dependency, runs in the required `test` job on every PR.

## Problem Frame

U4b shipped 7 PACKAGE_SAME_* rules as dormant code (importable via `--rule-pack=protokit.schema.lint.rules.package_same`, NOT in `BUILTIN_PACKS`). Unit + e2e tests at `tests/schema/lint/rules/test_package_same.py` (1200 lines) + `tests/schema/lint/test_cli_package_same_e2e.py` (326 lines) assert protokit's expected behavior against protokit-internal fixtures. The helper was authored against U4a's empirically-captured buf v1.69.0 observations (21 SHA-pinned NDJSON snapshots at `tests/schema/lint/rules/fixtures/package_same/_buf_smoke/recorded/`), so the implementation-conforms-to-helper-author-intent claim is real, not circular.

What's missing: end-to-end regression detection. If a future helper edit drifts (e.g., a refactor changes the inner-quote-escape sequence, or a contributor "improves" the value-payload sort), the existing tests would either also be updated (covering up the drift) or fail loudly without telling the maintainer which side is wrong. U6's parity tests are the second line of defense — they assert protokit's PACKAGE_SAME_* output matches buf's recorded snapshots byte-for-byte on identical inputs, with the SHA-pin guaranteeing the recorded snapshot still represents buf v1.69.0 faithfully (see origin: `docs/brainstorms/2026-05-18-d6b-u6-r7-package-same-parity-tests-requirements.md` Problem Frame).

The parity-test infrastructure also needs a one-time extension: today's `tests/parity/conftest.py` invokes both protokit and buf one file at a time. R7 is the project's first multi-file rule family; R8 in D6c (`package/same-directory`) is the next known multi-file rule, but its cross-file disagreement semantics may need a different `assert_parity_*` shape than U6's all-disagreers-fire model. The harness extension lands sized for U6's actual need (the all-disagreers-fire model R7 uses); whether R8 reuses it or extends it is validated when R8 lands. Framing R8 as a "candidate" rather than "target" honors that uncertainty.

## Requirements Trace

Requirements carried from origin doc R20-R26:

- **R20**. Parity test module `tests/parity/test_parity_package_same.py` — drops `pytestmark = pytest.mark.parity` per KD-2; module-import-time fixture→rule_id mapping derived from each `buf.yaml use:[]`.
- **R21**. Single-source-of-truth fixture list via cross-module import from `tests.schema.lint.test_buf_smoke_assumptions._SMOKE_FIXTURES`.
- **R22**. `--rule-pack=protokit.schema.lint.rules.package_same` opt-in; KD-4 documents the post-U7 no-op behavior.
- **R23**. Recorded-snapshot mode runs in the required `test` job (not the advisory `parity` job).
- **R24**. Three new conftest helpers: `run_protokit_lint_multi_file`, `parse_buf_recorded_snapshot`, `assert_parity_multi_file` + typed `BufFinding`.
- **R25**. Five collection-time invariants (R25(a) coverage, R25(b) fixture-list sync, R25(c) bidirectional snapshot reachability, R25(d) buf.yaml single-rule precondition, R25(e) snapshot/buf.yaml rule-id consistency).
- **R26**. Zero new `_PARITY_EXCEPTIONS` entries expected within the 21-fixture domain; surface-and-resolve framing if divergence appears.

Success criteria carried from origin doc S1-S6 (see origin for full text). Key acceptance: 21 parametrized cases + 5 collection-time invariants = **+26 new passing tests**; `pytest tests/` suite grows by +26 from the HEAD baseline at U6 land time (HEAD at plan-writing time `5a3f86f` reports 1882 collected → 1908 post-U6; the brainstorm baseline of 1875 was the U5-ce:compound checkpoint and has since advanced); zero new `_PARITY_EXCEPTIONS` entries; R7 stays dormant; U7 inherits a verified PACKAGE_SAME_*-scoped parity contract.

## Scope Boundaries

- **BUILTIN_PACKS registration is U7's job.** R7 stays dormant; `--rule-pack=...` opt-in only.
- **No live-mode buf re-invocation in U6.** `test_buf_smoke_assumptions.py` already covers buf-drift detection.
- **No new `tests/parity/fixtures/package_same/` tree.** Read committed `_buf_smoke/<scenario>/` fixtures + `recorded/<scenario>.json` snapshots in place.
- **No adversarial fixtures.** Adversarial-domain coverage (long values, unicode, comment-shifted lines) requires BUF_BINARY at fixture-creation time — a U4-style empirical-capture deliverable, not a U6 parity-gate deliverable.
- **R8 parity is D6c.** Multi-file harness extension lands in U6 as a candidate for R8's reuse; R8 itself + its fixtures stay deferred, and the reuse decision happens when R8 lands and its cross-file semantics are pinned.
- **No `--descriptor-set` mode parity testing.** U4b's e2e tests already cover that equivalence.
- **No CHANGELOG / README user-facing prose updates.** U6 lands the empirical lock; U7 lands the delivery-boundary work.
- **No `proto_templates.py` reuse.** Per [[programmatic-proto-fixture-builder-multi-file-rule-family-2026-05-17]], the builder is for tmp-dir unit-test fixtures; U6 reads committed byte-pinned static .proto files (different invariant class).

### Deferred to Separate Tasks

- **U7 — BUILTIN_PACKS registration + 0.2.0 → 0.3.0 bump + CHANGELOG-DRAFT fold + README refresh + presence-ratchet test + stale-text sweep** (next D6b unit).
- **D6c R8 — `package/same-directory` parity** (next known multi-file rule; CANDIDATE for reusing the harness extension from U6 depending on R8's cross-file semantics).
- **Multi-file `_PARITY_EXCEPTIONS` key shape design** — deferred until ≥2 divergence specimens exist per [[buf-parity-divergence-documentation-discipline-2026-05-13]] (one-specimen ≠ pattern rule).

## Context & Research

### Relevant Code and Patterns

- **Proven single-file parity pattern** — `tests/parity/test_parity_package.py:26-102`: `pytestmark = pytest.mark.parity` (L26), `_CASES` tuple shape `(rule_id, fixture_subdir, proto_relpath, expected_fires)` (L28-57), collection-time invariant `test_every_<family>_rule_has_a_parity_map_entry` (L61-71), `case_id(...)` helper for parametrize ids (L73-77), test body using `skip_if_buf_deprecated → run_protokit_lint → run_buf_lint → assert_parity` (L78-102). U6 mirrors this shape but extends to multi-file invocation.

- **Existing parity conftest helpers** — `tests/parity/conftest.py`:
  - `_extract_buf_rule_id` (L133-138): strips `buf:` prefix from `source_spec`.
  - `_build_rule_id_map` (L141-185): walks `BUILTIN_PACKS`, uses `get_lint_spec(fn)`, raises on dup-rule-id collisions. **R7 is NOT in BUILTIN_PACKS during U6** — U6 cannot use `RULE_ID_MAP` (see KD-1 below).
  - `_validate_parity_exceptions` (L193-227) + module-bottom invocation (L230): collection-time invariant pattern U6's invariants mirror.
  - `skip_if_buf_deprecated` (L254-269): must call at top of `test_parity` body even when no R7 rule is buf-deprecated today (future-proofing per [[upstream-rule-deprecation-skip-ordering-parity-harness-2026-05-13]]).
  - `_BUF_OK_EXIT_CODES = frozenset({0, 100})` (L308): guards against silent-green from buf.
  - `run_protokit_lint` (L354-421): invokes via `python -c "from protokit.cli import main; main()"`, exit-code allowlist `(0, 1)`, reads `payload["findings"]`, **`cwd=fixture_dir` (L388)** — multi-file helper must mirror this for path-relative emission.
  - `_normalize_buf_path` (L427-440): `PurePosixPath(buf_path).as_posix()` — buf may emit paths without leading `./`.
  - `assert_parity` (L485-579): single-file shape. U6's `assert_parity_multi_file` is genuinely new.

- **Shared subprocess helpers** — `tests/_buf_helpers.py:90-133` (`run_buf_subprocess`): 30s wall-clock cap + triple-arm guard (`KeyboardInterrupt`/`SystemExit`/`Exception`) at L112; signature `(argv, cwd, label)` → `subprocess.CompletedProcess[str]`. U6's `run_protokit_lint_multi_file` reuses this; for buf-side input U6 reads recorded snapshots, no buf subprocess needed.

- **Buf smoke fixtures + snapshots** — `tests/schema/lint/test_buf_smoke_assumptions.py:47-72` (`_SMOKE_FIXTURES` tuple of 21 names in canonical 7+7+7 order); `_smoke_root()` (L75-82) returns `tests/schema/lint/rules/fixtures/package_same/_buf_smoke/`. 21 committed fixtures at `_buf_smoke/<scenario>/` (each with 2-4 `.proto` files + `buf.yaml`); 21 committed recorded snapshots at `_buf_smoke/recorded/<scenario>.json` (SHA-pinned by `tests/schema/lint/test_buf_smoke_recorded_checksums.py`).

- **R7 rule registry** — `src/protokit/schema/lint/rules/package_same.py` exposes `RULES = (...)` tuple of 7 `LintRuleSpec` objects via `get_lint_spec`. Per-rule `source_spec="buf:PACKAGE_SAME_<NAME>"` is the mapping back to buf rule_ids.

- **`get_lint_spec` accessor** — `src/protokit/schema/lint/decorator.py:144-174`. Typed accessor U4b adopted per ce:review KP-3 to eliminate `# type: ignore[attr-defined]` suppressions.

- **Engine idempotent load** — `src/protokit/schema/lint/engine.py:241-242`: `if module.__name__ in self._loaded_module_names: return  # idempotent`. Verified at HEAD; KD-4 (post-U7 `--rule-pack` becomes no-op) relies on this.

- **CI workflow** — `.github/workflows/ci.yml:136` (`test` job: `pytest tests/ -v`, no marker filter, default 6h timeout) vs `:261` (`parity` job: `pytest tests/parity/ -m parity -v` with `BUF_BINARY`, intentionally advisory per L237-249, 15-min timeout at L255). U6's tests run in the `test` job only (KD-2).

- **PyYAML** — already in dependencies (`pyproject.toml`: `PyYAML>=6.0,<7` + `types-PyYAML`). Comment instructs `yaml.safe_load` only (security: never bare `yaml.load()`).

- **pyproject.toml:86-87** — `# The marker is documentary — default pytest tests/ still collects parity tests`. Authoritative on marker behavior; `tests/parity/conftest.py:6-9` docstring is stale and contradicts pyproject.toml.

### Institutional Learnings

- **[[buf-parity-divergence-documentation-discipline-2026-05-13]]** — `_PARITY_EXCEPTIONS` keyed by `(rule_id, fixture_stem)` requires four-site documentation. **U6 expects zero entries** (S4); if divergences surface, multi-file key shape design is deferred until ≥2 specimens (one-specimen-not-a-pattern rule).
- **[[upstream-rule-deprecation-skip-ordering-parity-harness-2026-05-13]]** — `skip_if_buf_deprecated()` MUST be called at the top of every `test_parity` method even when no R7 rule is buf-deprecated today; future-proofing discipline.
- **[[subprocess-exit-code-validation-test-harness-2026-05-13]]** — U6's `run_protokit_lint_multi_file` must use the `(0, 1)` exit-code allowlist + JSON-shape guard, not bypass them.
- **[[pytestmark-does-not-guard-module-top-imports-2026-05-02]]** — Dropping `pytestmark = pytest.mark.parity` (KD-2) is the right knob to move U6 into the required `test` job; do NOT use module-top `pytest.importorskip` since U6 is buf-binary-free.
- **[[structural-pin-inspect-getsource-untestable-collision-branch-2026-05-13]]** — For the `sorted()` determinism OQ: try to construct a tie-producing fixture FIRST; fall back to `inspect.getsource` structural pin only if behavior tests are unreachable.
- **[[conftest-plain-function-relative-import-2026-05-12]]** — The 3 new conftest helpers are plain functions; consumers use `from tests.parity.conftest import <helper>` (not bare `from conftest import`).
- **[[fixture-precondition-assertion-surfaces-silent-test-2026-05-17]]** + **[[capture-setup-without-dispatch-false-test-confidence-2026-05-17]]** — Collection-time invariants are active-discovery counterparts to passive-discovery patterns; each invariant must fail with a message naming what drifted.
- **[[audit-wire-format-before-claiming-sibling-parity-2026-05-03]]** — KD-7's per-fixture rule scoping reads each `buf.yaml use:[]` as SSOT; this IS the wire-format audit applied correctly.
- **[[programmatic-proto-fixture-builder-multi-file-rule-family-2026-05-17]]** — U4b's `proto_templates.py` is for tmp-dir unit-test fixtures; U6's committed byte-pinned static .proto files fall in the builder's exclusion bucket. Do NOT reuse the builder for U6.
- **[[dormant-code-changelog-draft-staging-delivery-boundary-2026-05-17]]** — U7-cleanup TODOs belong in `CHANGELOG-DRAFT.md`, not test-source docstrings; the dormancy-window note for U6 goes in CHANGELOG-DRAFT.
- **[[stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12]]** — Same discipline: forward-looking text in source code creates sweep debt; staged entries in CHANGELOG-DRAFT survive the sweep cleanly.
- **[[test-method-names-encode-invariants-not-delivery-deltas-2026-05-13]]** — Test method names encode the invariant (e.g., `test_parity_byte_matches_recorded_snapshot`), not "u6" / "snapshot-mode" / delivery deltas.

## Key Technical Decisions

- **KD-1 (NEW): U6 walks `protokit.schema.lint.rules.package_same.RULES` directly, bypassing `RULE_ID_MAP`.** R7 is NOT in `BUILTIN_PACKS` until U7 (per origin: KD-4); `tests/parity/conftest.py:141-185` `_build_rule_id_map()` walks `BUILTIN_PACKS` only. U6 adds a local helper `_build_package_same_rule_id_map()` in `test_parity_package_same.py` that iterates `package_same.RULES`, calls `get_lint_spec(fn)`, extracts `buf:` prefix via the existing `_extract_buf_rule_id`, and returns the canonical map `_PACKAGE_SAME_RULE_ID_MAP: Mapping[str, str]` keyed by `buf_rule_id` with `protokit_rule_id` values. The inverse direction (`protokit_rule_id → buf_rule_id`) is derived at module-import time via dict comprehension: `_BUF_RULE_ID_MAP = {v: k for k, v in _PACKAGE_SAME_RULE_ID_MAP.items()}`. Both directions are needed: KD-8's `_FIXTURE_RULE_ID_MAP` building uses the forward direction (`buf_rule_id → protokit_rule_id`); the test body's `skip_if_buf_deprecated(buf_rule_id, protokit_rule_id)` call uses the inverse to look up `buf_rule_id` from the parametrize's `protokit_rule_id`. **Rationale:** preserves the dormancy contract from U4b without forcing U6 to take a dependency on U7's BUILTIN_PACKS edit; rule-id derivation stays internal to U6's test module. Documenting both maps explicitly (rather than inverting at use sites) prevents the silent failure mode of an implementer choosing one direction inconsistently across the test body and the collection-time invariants.

- **KD-2 (carried from origin): Drop `pytestmark = pytest.mark.parity`.** Tests run in the required `test` job (`pytest tests/ -v`), not the advisory parity job. Empirically verified by `pyproject.toml:86-87` authoritative comment + collection check. (See origin: KD-2.)

- **KD-3 (carried from origin's KD-2, second half): Recorded-snapshot mode default.** No BUF_BINARY dependency; SHA-pin gates snapshot fidelity. The origin's KD-2 covers BOTH "drop the marker" AND "use recorded snapshots" as one decision; the plan splits them into KD-2 (marker) + KD-3 (mode) for clarity. (See origin: KD-2, recorded-snapshot half.)

- **KD-4 (carried from origin): `--rule-pack` opt-in for dormancy window, deliberate no-op post-U7.** `engine.py:241-242` is idempotent by module name; verified. No U7 migration work required. (See origin: KD-4.)

- **KD-5 (carried from origin): Per-fixture rule scoping from `buf.yaml use:[]`.** Module-import-time parse via `yaml.safe_load` of top-level `lint.use` only; R25(d) invariant pins the precondition. (See origin: KD-7.)

- **KD-6 (NEW): `_PARITY_EXCEPTIONS` extension for multi-file scope is deferred.** Per [[buf-parity-divergence-documentation-discipline-2026-05-13]] (one-specimen ≠ pattern), U6 expects zero entries (S4). If R20 surfaces a real divergence at `/ce:work`, the U6 deliverable expands minimally — a single inline divergence with `xfail` + a tracked issue, not a generalized multi-file key shape extension to `_PARITY_EXCEPTIONS`. Multi-file key shape design deferred until ≥2 divergence specimens exist.

- **KD-7 (NEW): Conftest docstring drift fix folded into U6.** `tests/parity/conftest.py:6-9` claims `default pytest tests/ skips the entire tree because the marker is not selected by default` — this is stale (contradicts `pyproject.toml:86-87`). U6 is the unit that surfaced the drift; folding the one-line fix into U6 is cheaper than adding it to U7's stale-text sweep backlog.

- **KD-8 (NEW): Module-import-time fixture mapping via top-level dict comprehension.** R20's parametrize source is `_FIXTURE_RULE_ID_MAP: Mapping[str, str]` built at module-import time by parsing each `_SMOKE_FIXTURES` entry's `buf.yaml` once. `pytest.mark.parametrize("fixture,rule_id", _FIXTURE_RULE_ID_MAP.items())` consumes the mapping. Parse errors crash collection with the offending fixture name (fail-loud posture matching R25(d)). **Rationale:** single-source-of-truth for the (fixture → rule_id) relationship; collection-time failure beats test-time failure for fixture/config drift.

- **KD-9 (NEW): `BufFinding` as `NamedTuple` in conftest.py.** Matches existing parity-tree conventions; supports tuple sorting + immutability. Located near the top of `tests/parity/conftest.py` next to existing type aliases (around L69-70) for discoverability per [[conftest-plain-function-relative-import-2026-05-12]] and per the project's existing pattern of type-alias colocation.

## Open Questions

### Resolved During Planning

- **buf.yaml parsing library + key path** — `yaml.safe_load` (PyYAML already in deps); read top-level `lint.use` only (NOT `modules[].lint.use`).
- **BUILTIN_PACKS sequencing constraint** — KD-1 resolves: U6 walks `package_same.RULES` directly via local helper.
- **Subprocess reuse** — `run_buf_subprocess` from `tests/_buf_helpers.py:90-133` is the discipline; `run_protokit_lint_multi_file` is a new helper but calls the same underlying machinery.
- **`cwd` contract** — `cwd=fixture_dir` matching `conftest.py:388`; aligns with buf's recorded NDJSON `path` field after `_normalize_buf_path`.
- **PyYAML availability** — verified in `pyproject.toml`; no dependency-management work needed.
- **Latency feasibility** — empirically measured 0.07s per invocation × 21 = <2s wall-time (origin doc Dependencies).
- **Test method naming** — invariant-style: `test_parity_byte_matches_recorded_snapshot` (per [[test-method-names-encode-invariants-not-delivery-deltas-2026-05-13]]).
- **Skip-if-buf-deprecated** — call at top of `test_parity_byte_matches_recorded_snapshot` body even though no PACKAGE_SAME_* is currently in `_BUF_DEPRECATED_RULES` (future-proofing per learning).
- **conftest helper import convention** — `from tests.parity.conftest import <helper>` (not bare `from conftest import`).
- **`BufFinding` type + location** — `NamedTuple` in `tests/parity/conftest.py` next to the parser.
- **Parametrize approach** — single parametrized function with descriptive ids derived from `(fixture_name, rule_id_short)`.
- **Multi-file `_PARITY_EXCEPTIONS` key shape** — deferred until ≥2 divergence specimens per [[buf-parity-divergence-documentation-discipline-2026-05-13]].

### Deferred to Implementation

- **Exact diagnostic message text for `assert_parity_multi_file` divergence** — lean documented in origin (structured failure with `fixture_scenario`, `protokit_rule_id`, `proto_relpath`, `protokit_finding`, `buf_finding`, + decision-tree hint). Concrete wording at implementation time.
- **`sorted()` determinism (per [[structural-pin-inspect-getsource-untestable-collision-branch-2026-05-13]])** — at implementation time, attempt to construct a 3-file fixture where two findings tie on the natural sort key `(path, line, col, rule_id)`. If a tie-producing fixture works, behavior-test the sort; if no fixture produces a tie (likely given path differs per file in multi-file emit shape), fall back to `inspect.getsource` structural pin on the sort-key expression.
- **Sort-key uniqueness pre-assertion implementation** — R24 specifies "Sort-key uniqueness within each side is asserted before pairing." **Decision rule (pin at implementation time)**: parse ALL 21 recorded snapshots in <100ms and assert that `(path, start_line, start_column, type)` is unique per snapshot. If every snapshot's findings pass uniqueness, use the simple `len(set(...)) == len(...)` pre-assertion. If ANY snapshot has a duplicate sort key, switch the assertion to multiset equality on `(path, message)` tuples scoped by rule_id. The 21-snapshot scan removes per-implementer judgment and provides empirical grounding for the chosen shape. (Plan-writing time spot-check of `recorded/mixed-presence-java-multiple-files.json` confirms 3 findings with distinct `path` values at identical `(line=1, col=1)` — `path` IS the discriminator, so uniqueness likely holds trivially; the 21-snapshot scan is the verification.)

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

**Module-import-time fixture mapping (KD-8) + KD-1's two derived maps:**

```text
# KD-1: forward + inverse rule-id maps derived from package_same.RULES once at import
_PACKAGE_SAME_RULE_ID_MAP: Mapping[str, str] = _build_package_same_rule_id_map()
    # returns {buf_rule_id: protokit_rule_id}
_BUF_RULE_ID_MAP: Mapping[str, str] = {v: k for k, v in _PACKAGE_SAME_RULE_ID_MAP.items()}
    # inverse: {protokit_rule_id: buf_rule_id}

# KD-8: parse each fixture's buf.yaml once at import; build _FIXTURE_RULE_ID_MAP
_SMOKE_FIXTURES = import from tests.schema.lint.test_buf_smoke_assumptions

for fixture_name in _SMOKE_FIXTURES:
    buf_yaml_path = _smoke_root() / fixture_name / "buf.yaml"
    config = yaml.safe_load(buf_yaml_path.read_text())
    use_list = config["lint"]["use"]  # TOP-LEVEL only; not modules[].lint.use
    assert len(use_list) == 1, fail(fixture_name + ": expected single rule")
    buf_rule_id = use_list[0]
    protokit_rule_id = _PACKAGE_SAME_RULE_ID_MAP[buf_rule_id]  # forward lookup
    _FIXTURE_RULE_ID_MAP[fixture_name] = protokit_rule_id

# Parametrize body:
@pytest.mark.parametrize(
    "fixture_name,protokit_rule_id",
    _FIXTURE_RULE_ID_MAP.items(),
    ids=[f"{name}-{rid.replace('/', '-')}" for name, rid in _FIXTURE_RULE_ID_MAP.items()],
)
def test_parity_byte_matches_recorded_snapshot(fixture_name, protokit_rule_id, ...):
    buf_rule_id = _BUF_RULE_ID_MAP[protokit_rule_id]  # inverse lookup
    skip_if_buf_deprecated(buf_rule_id, protokit_rule_id)
    fixture_dir = _smoke_root() / fixture_name
    snapshot_path = _smoke_root() / "recorded" / f"{fixture_name}.json"
    protokit_findings = run_protokit_lint_multi_file(fixture_dir, rule_pack="protokit.schema.lint.rules.package_same")
    buf_findings = parse_buf_recorded_snapshot(snapshot_path)
    assert_parity_multi_file(
        protokit_findings,
        buf_findings,
        protokit_rule_ids={protokit_rule_id},
        fixture_scenario=fixture_name,
    )
```

**Five collection-time invariants (R25 a-e):**

```text
# Each invariant invoked at module-bottom (mirroring _validate_parity_exceptions at conftest.py:230)

def test_every_package_same_rule_has_at_least_one_firing_fixture():
    """R25(a) — every R7 rule_id appears in at least one snapshot's firing set"""

def test_fixture_list_matches_smoke_assumptions():
    """R25(b) — _FIXTURE_RULE_ID_MAP.keys() == _SMOKE_FIXTURES (sync check)"""

def test_every_recorded_snapshot_is_reachable():
    """R25(c) — bidirectional: every recorded/*.json ↔ every _SMOKE_FIXTURES entry"""

def test_every_fixture_buf_yaml_pins_one_r7_rule():
    """R25(d) — fixtures uniformly pin one PACKAGE_SAME_* rule (precondition for KD-5)"""

def test_buf_yaml_rule_matches_recorded_findings_rule():
    """R25(e) — non-empty recorded snapshot's unique `type` field == buf.yaml use[0]"""
```

**Three multi-file conftest helpers (R24):**

```text
class BufFinding(NamedTuple):
    path: str
    start_line: int
    start_column: int
    end_line: int
    end_column: int
    type: str
    message: str

def run_protokit_lint_multi_file(
    fixture_dir: Path,
    *,
    rule_pack: str | None = None,
    proto_paths: tuple[Path, ...] | None = None,
) -> tuple[ProtokitFinding, ...]:
    """Subprocess invocation with cwd=fixture_dir (matching single-file at L388);
    recursive rglob; -I per proto_path; exit-code allowlist (0,1); JSON-shape guard;
    sort findings by (path, line, col, rule_id) for deterministic assertion;
    NIL+ERROR shadow paths fail loud with fixture name."""

def parse_buf_recorded_snapshot(snapshot_path: Path) -> tuple[BufFinding, ...]:
    """Read NDJSON line-by-line; empty file → empty tuple; sort by
    (path, start_line, start_column, type) for deterministic comparison."""

def assert_parity_multi_file(
    protokit_findings: Sequence[ProtokitFinding],
    buf_findings: Sequence[BufFinding],
    *,
    protokit_rule_ids: AbstractSet[str],
    fixture_scenario: str,
) -> None:
    """Two-sided rule-id check: (i) every protokit finding inside protokit_rule_ids
    must pair with a buf finding; (ii) every protokit finding OUTSIDE protokit_rule_ids
    BUT inside the R7 family must NOT exist (over-firing complement).
    Sort-key uniqueness asserted before pairing.
    Diagnostic message names fixture_scenario + decision-tree hint on failure."""
```

## Implementation Units

- [ ] **Unit 1: Multi-file conftest helpers + typed `BufFinding`**

**Goal:** Extend `tests/parity/conftest.py` with three new helpers + the `BufFinding` named tuple so U6's test module can invoke them. Helpers are sized for U6's all-disagreers-fire model (R7's emit shape); D6c R8 is a candidate downstream consumer but its reuse depends on R8's cross-file semantics being compatible.

**Requirements:** R24, KD-9.

**Dependencies:** None (extends existing conftest in place).

**Files:**
- Modify: `tests/parity/conftest.py` (add helpers next to single-file siblings)

**Approach:**
- Add `BufFinding(NamedTuple)` near the top of conftest (next to existing type aliases at L69-70).
- Add `parse_buf_recorded_snapshot(snapshot_path)` next to existing buf-related helpers (after `_normalize_buf_path` at L427-440 region). Implementation: read NDJSON line-by-line, skip empty lines (per `_normalize_buf_output` pattern at `test_buf_smoke_assumptions.py:85-90`), `json.loads` each, construct `BufFinding`, return sorted tuple.
- Add `run_protokit_lint_multi_file(fixture_dir, *, rule_pack=None, proto_paths=None)` next to single-file `run_protokit_lint` at L354-421. Reuse `tests._buf_helpers.run_buf_subprocess` for subprocess discipline. Mirror single-file's exit-code allowlist `(0, 1)`, JSON-shape guard, `cwd=fixture_dir`. `sorted(fixture_dir.rglob("*.proto"))` for file enumeration; default `proto_paths=(fixture_dir,)` for `-I` flag. **Critical: pass `-I` as `.` (relative to `cwd=fixture_dir`) rather than `str(fixture_dir)` (absolute)** — empirically verified at plan-writing time that `-I .` with `cwd=fixture_dir` produces fixture-root-relative finding `location` paths (e.g., `"path":"a.proto"`) matching buf's recorded NDJSON `path` field; absolute `-I str(fixture_dir)` would produce absolute paths that fail `assert_parity_multi_file`'s path comparison. Implement as `-I "."` (or equivalent: `-I` followed by `os.fspath(p.relative_to(fixture_dir))` for each path in `proto_paths`).
- Add `assert_parity_multi_file(...)` next to single-file `assert_parity` at L485-579. Implement two-sided rule-id check + sort-key uniqueness pre-assertion + structured diagnostic.
- Each helper's docstring describes its multi-file parity invocation pattern. The specific "N=1 reuse target: D6c R8 `package/same-directory`" forward-pointer is single-sourced in Unit 3's CHANGELOG-DRAFT entry; helper docstrings themselves stay factual ("multi-file analog of the single-file `<sibling>` helper at `conftest.py:<line>`") without the speculative R8 reference. Rationale: forward-pointers in source code create stale-text-sweep debt (per [[stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12]]); CHANGELOG-DRAFT is the right place for speculative-consumer references.

**Execution note:** Test-first for the helpers — write a stub test in Unit 2 that exercises each helper against the simplest fixture (e.g., `all-agree` for zero-findings happy path) BEFORE adding the parametrized 21-case body. The stub validates the helper contracts in isolation before scale.

**Patterns to follow:**
- `tests/parity/conftest.py:354-421` (`run_protokit_lint` shape)
- `tests/parity/conftest.py:485-579` (`assert_parity` shape — though U6's version is genuinely different)
- `tests/_buf_helpers.py:90-133` (`run_buf_subprocess` reuse — 30s cap + triple-arm guard)
- `tests/schema/lint/test_buf_smoke_assumptions.py:85-90` (`_normalize_buf_output` for NDJSON parse pattern)

**Test scenarios:**
- *Happy path*: `parse_buf_recorded_snapshot` on `recorded/mixed-presence-java-package.json` returns 3 `BufFinding` tuples (one per file in the 3-file fixture), each with `type="PACKAGE_SAME_JAVA_PACKAGE"`, distinct `path` values.
- *Edge case*: `parse_buf_recorded_snapshot` on `recorded/all-agree.json` (empty file, SHA `e3b0c44...`) returns `()`.
- *Edge case*: `parse_buf_recorded_snapshot` on `recorded/wkt-only.json` (also empty) returns `()`.
- *Error path*: `run_protokit_lint_multi_file` against a directory containing zero `.proto` files raises `pytest.fail` with a message naming the empty fixture path.
- *Error path*: `run_protokit_lint_multi_file` against a fixture where protokit returns exit code 2 (config error) raises `pytest.fail` matching the single-file helper's pattern.
- *Edge case*: A `.proto` file that exists but is empty (zero bytes) routes through the existing exit-code-2 surfacing (protoc rejects empty files lacking a `syntax` declaration) — verify the diagnostic names the offending file path, not just `fixture_dir`. No special-case "skip empty files" branch is needed; the `(0, 1)` allowlist + JSON-shape guard handle it cleanly.
- *Integration*: `run_protokit_lint_multi_file(fixture_dir=_buf_smoke/googleapis-import/, rule_pack="...package_same")` returns findings whose `path` values are fixture-root-relative (verifies `cwd=fixture_dir` contract).
- *Integration*: `assert_parity_multi_file` with matched protokit + buf finding sets (e.g., both empty for `all-agree`) passes silently.
- *Integration*: `assert_parity_multi_file` with mismatched sets (protokit fires `PACKAGE_SAME_JAVA_PACKAGE` on a fixture whose `buf.yaml` pins `PACKAGE_SAME_GO_PACKAGE`) fails with the over-firing diagnostic naming the unexpected rule_id.
- *Integration*: `assert_parity_multi_file` with rule-id-filter mismatch on protokit side (extra finding outside scoped rule_ids) is reported as over-firing.
- *Edge case*: Sort-key uniqueness pre-assertion catches the hypothetical case of two findings with identical `(path, line, col, rule_id)` within a side.

**Verification:**
- All three helpers callable from a smoke test that imports them via `from tests.parity.conftest import run_protokit_lint_multi_file, parse_buf_recorded_snapshot, assert_parity_multi_file, BufFinding`.
- `mypy src/protokit tests/parity` passes (typed `BufFinding` accessible to type-checked test modules).
- `ruff check tests/parity/conftest.py` passes.
- Helper docstrings describe the multi-file pattern + sibling reference; N=1 reuse forward-pointer to D6c R8 lives in the CHANGELOG-DRAFT entry (Unit 3) per single-sourcing.

---

- [ ] **Unit 2: Parity test module `test_parity_package_same.py` (21 parametrized cases + 5 collection-time invariants)**

**Goal:** Create the new parity test module that exercises U4b's R7 helper against the 21 SHA-pinned buf v1.69.0 snapshots, with 5 collection-time invariants preventing silent drift.

**Requirements:** R20, R21, R22, R23, R25, R26, S1, S2, S3, S4, S5, S6, KD-1, KD-2, KD-3, KD-5, KD-6, KD-8, KD-9 (BufFinding type imported from conftest); also depends on KD-7 (conftest docstring fix in Unit 3 is parallel cleanup, no order dependency).

**Dependencies:** Unit 1 (helpers must exist before this module imports them).

**Files:**
- Create: `tests/parity/test_parity_package_same.py`

**Approach:**
- Module docstring states the parity contract: "Asserts protokit's PACKAGE_SAME_*-rule_id-scoped findings byte-match buf v1.69.0's recorded NDJSON snapshots, per-fixture, on identical multi-file inputs. Runs in the required `test` job (no `pytestmark = pytest.mark.parity` — see KD-2 in origin)." Include the post-U7 no-op contract for `--rule-pack=...package_same` (KD-4).
- Imports: `from tests.parity.conftest import (BufFinding, parse_buf_recorded_snapshot, run_protokit_lint_multi_file, assert_parity_multi_file, skip_if_buf_deprecated, _extract_buf_rule_id)`; `from tests.schema.lint.test_buf_smoke_assumptions import _SMOKE_FIXTURES`; `from protokit.schema.lint.rules import package_same`; `from protokit.schema.lint.decorator import get_lint_spec`; `import yaml`.
- Local helper `_build_package_same_rule_id_map() -> Mapping[str, str]` (KD-1): walks `package_same.RULES`, calls `get_lint_spec(fn)`, extracts buf rule_id via `_extract_buf_rule_id(spec.source_spec)`, returns the canonical map `_PACKAGE_SAME_RULE_ID_MAP: Mapping[str, str]` keyed by `buf_rule_id → protokit_rule_id` (bypasses `BUILTIN_PACKS`-based `RULE_ID_MAP`).
- Inverse map `_BUF_RULE_ID_MAP: Mapping[str, str]` derived once at module-import time via dict comprehension: `_BUF_RULE_ID_MAP = {v: k for k, v in _PACKAGE_SAME_RULE_ID_MAP.items()}`. Forward map serves KD-8's fixture-mapping; inverse map serves the test body's `skip_if_buf_deprecated` call.
- Module-import-time `_FIXTURE_RULE_ID_MAP: Mapping[str, str]` built via dict comprehension over `_SMOKE_FIXTURES`: for each fixture, parse `_smoke_root() / fixture / "buf.yaml"` via `yaml.safe_load`, read top-level `lint.use[0]`, look up protokit rule_id via `_PACKAGE_SAME_RULE_ID_MAP[buf_rule_id]` (forward direction). Parse errors or precondition violations crash collection with the offending fixture name.
- Test body `test_parity_byte_matches_recorded_snapshot(fixture_name, protokit_rule_id, ...)`: derive `buf_rule_id = _BUF_RULE_ID_MAP[protokit_rule_id]` (inverse direction); call `skip_if_buf_deprecated(buf_rule_id, protokit_rule_id)` (future-proofing per [[upstream-rule-deprecation-skip-ordering-parity-harness-2026-05-13]]); compute `fixture_dir + snapshot_path`; invoke `run_protokit_lint_multi_file(fixture_dir, rule_pack="protokit.schema.lint.rules.package_same")`; invoke `parse_buf_recorded_snapshot(snapshot_path)`; call `assert_parity_multi_file(protokit_findings, buf_findings, protokit_rule_ids={protokit_rule_id}, fixture_scenario=fixture_name)`.
- Five collection-time invariants as test functions invoked at module-bottom mirroring `_validate_parity_exceptions()` pattern at `conftest.py:230`. R25(a) — over `package_same.RULES`. R25(b) — `set(_FIXTURE_RULE_ID_MAP.keys()) == set(_SMOKE_FIXTURES)`. R25(c) — bidirectional `recorded/*.json` ↔ `_SMOKE_FIXTURES`. R25(d) — every fixture's `buf.yaml lint.use` is single-element + maps to known R7 rule. R25(e) — non-empty recorded snapshot's unique `type` field == derived `buf_rule_id`; `all-agree.json` + `wkt-only.json` exempt.
- Test method name per [[test-method-names-encode-invariants-not-delivery-deltas-2026-05-13]]: `test_parity_byte_matches_recorded_snapshot` (NOT `test_u6_*` or `test_snapshot_mode_*`).

**Execution note:** Implementation order: (1) stub the parametrize body with `_SMOKE_FIXTURES[:1]` (just `all-agree`) to validate the helper wiring + import paths; (2) expand to full `_SMOKE_FIXTURES`; (3) add the 5 collection-time invariants one at a time, verifying each fails appropriately by temporarily breaking the invariant (e.g., remove a recorded snapshot, confirm R25(c) fails with the expected message).

**Patterns to follow:**
- `tests/parity/test_parity_package.py` shape (`_CASES` tuple, collection-time invariant, parametrize structure, `case_id` for ids)
- `tests/parity/conftest.py:193-230` (`_validate_parity_exceptions` + module-bottom invocation — the collection-time invariant pattern)
- `tests/schema/lint/test_buf_smoke_assumptions.py:47-72` (`_SMOKE_FIXTURES` import)

**Test scenarios:**
- *Happy path*: All 21 parametrized cases pass (`pytest tests/parity/test_parity_package_same.py -v` shows 21 PASSED + 5 invariant PASSED = 26 PASSED).
- *Edge case*: `all-agree` and `wkt-only` (both with empty recorded snapshots) assert protokit produces zero R7 findings.
- *Edge case*: `googleapis-import` and `wkt-conflict` (3-file fixtures with nested `google/api/*.proto` and `google/protobuf/*.proto`) succeed — verifies recursive `rglob` + `cwd=fixture_dir` + `-I` resolution.
- *Edge case*: `mixed-presence-java-multiple-files.json` (bool option, mixed-presence) succeeds — verifies bool rendering matches buf's `false,true` lowercase.
- *Edge case*: `mixed-value-with-inner-quote.json` succeeds — verifies inner-quote escape `\"` matches.
- *Error path*: R25(d) fails at collection time with a clear message if a fixture's `buf.yaml` is missing or names multiple rules.
- *Error path*: R25(e) fails at collection time if a contributor edits a `buf.yaml` rule without re-capturing the snapshot (or vice versa).
- *Error path*: R25(b) fails at collection time if `_SMOKE_FIXTURES` and U6's local fixture set drift.
- *Integration*: Test discovery confirmed — `pytest tests/parity/test_parity_package_same.py --collect-only` lists 26 tests (no marker selector required).
- *Integration*: `pytest tests/` (default, no marker filter) suite count grows by +26 from HEAD baseline (1882 at plan-writing time → 1908 post-U6, modulo other intervening landings); `pytest tests/ -m parity` count does NOT increase (U6 is excluded by `-m parity` per KD-2 + Scope Boundaries).
- *Integration*: `_FIXTURE_RULE_ID_MAP` is correctly populated at module import — verifiable via a print or via R25(b) invariant passing.
- *Integration*: All 21 cases scoped per-fixture to single rule_id; over-firing complement in `assert_parity_multi_file` does NOT fire spuriously on any fixture (latent symmetry holds).

**Verification:**
- `pytest tests/parity/test_parity_package_same.py -v` shows 26 PASSED.
- `pytest tests/` suite count: HEAD baseline at U6 implementation start time + 26 (HEAD at plan-writing time `5a3f86f` = 1882 → expected 1908). Capture the actual baseline via `pytest tests/ --collect-only -q | tail -1` before starting Unit 1; the +26 delta is the load-bearing assertion.
- `pytest tests/parity/ -m parity` count UNCHANGED (U6 excluded by marker).
- `pytest tests/parity/test_parity_package_same.py --collect-only` shows 26 tests, no skips, no errors.
- `mypy src/protokit tests/parity` passes.
- `ruff check tests/parity/test_parity_package_same.py` passes.
- `pytest tests/schema/lint/rules/test_package_same.py` (U4b's dormancy contract test) continues to pass — R7 stays out of BUILTIN_PACKS.

---

- [ ] **Unit 3: Conftest docstring drift fix + CHANGELOG-DRAFT staging entry**

**Goal:** Reconcile the stale `tests/parity/conftest.py:6-9` docstring with the authoritative `pyproject.toml:86-87` comment + stage U6's contribution in `CHANGELOG-DRAFT.md` per the dormancy-window pattern.

**Requirements:** KD-7, [[dormant-code-changelog-draft-staging-delivery-boundary-2026-05-17]], [[stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12]].

**Dependencies:** None (cleanup + documentation only).

**Files:**
- Modify: `tests/parity/conftest.py` (one-line docstring fix at L6-9)
- Modify: `CHANGELOG-DRAFT.md` (add U6 staging entry under D6b section)

**Approach:**
- Docstring fix: replace `default pytest tests/ skips the entire tree because the marker is not selected by default` with `the marker is documentary; default pytest tests/ collects parity tests (verified at pyproject.toml:86-87) — the marker is only honored by jobs that explicitly select via -m parity (e.g., the advisory parity CI job)`.
- CHANGELOG-DRAFT entry under the existing D6b section: "**U6 (R7 PACKAGE_SAME_* parity verification)**: New `tests/parity/test_parity_package_same.py` asserts protokit's PACKAGE_SAME_*-rule_id-scoped findings byte-match buf v1.69.0 recorded NDJSON snapshots across 21 multi-file fixtures (recorded-snapshot mode; no BUF_BINARY dependency). Three multi-file conftest helpers (`run_protokit_lint_multi_file`, `parse_buf_recorded_snapshot`, `assert_parity_multi_file` + `BufFinding`) added as candidates for D6c R8 reuse (reuse depends on R8's cross-file semantics, validated when R8 lands). R7 remains dormant in BUILTIN_PACKS until U7. Five collection-time invariants prevent silent drift."

**Patterns to follow:**
- Existing D6b U4b CHANGELOG-DRAFT entry shape (per project memory: "CHANGELOG-DRAFT.md stages dormancy-window note + U7 content scope").

**Test scenarios:**
- Test expectation: none — pure documentation + cleanup (no behavioral change). The docstring fix is verified by reading; the CHANGELOG-DRAFT entry's correctness is verified at U7's stale-text sweep when the entry is folded into the actual CHANGELOG.

**Verification:**
- Docstring at `tests/parity/conftest.py:6-9` no longer contradicts `pyproject.toml:86-87`.
- CHANGELOG-DRAFT.md has a new U6 entry under D6b section in chronological order with U4b + U5.
- `grep -n 'pytest.mark.parity' tests/parity/conftest.py` returns lines consistent with the corrected docstring.

## System-Wide Impact

- **Interaction graph:** U6 adds reads on the LintEngine via `--rule-pack` opt-in (already exercised by U4b e2e tests); no new writes to engine state. Module-import-time `yaml.safe_load` reads add a startup cost at the 21-fixture level (negligible). Collection-time invariants extend the existing `_validate_parity_exceptions` pattern with 5 new functions invoked at module-bottom.
- **Error propagation:** Subprocess errors propagate via `run_buf_subprocess`'s 30s cap + triple-arm guard → `pytest.fail`. YAML parse errors propagate as collection-time exceptions naming the fixture. Per-fixture rule scoping mismatches surface as `assert_parity_multi_file` failures with structured diagnostic.
- **State lifecycle risks:** None — U6 is read-only test infrastructure. No persistent state, no caches, no migration concerns.
- **API surface parity:** `tests/parity/conftest.py` gains 3 helpers + 1 NamedTuple. The single-file helpers (`run_protokit_lint`, `assert_parity`, etc.) are unchanged. Existing `tests/parity/test_parity_*.py` modules are unaffected.
- **Integration coverage:** U6 itself IS the integration coverage — it validates the end-to-end protokit→buf-recorded parity for R7. Unit tests within Unit 1 cover the helpers in isolation; Unit 2's 21 parametrized cases cover the integration.
- **Unchanged invariants:** R7 remains absent from `BUILTIN_PACKS` (S5 dormancy contract). `RULE_ID_MAP` (built from `BUILTIN_PACKS`) does NOT contain R7 rules during U6. `_PARITY_EXCEPTIONS` is NOT extended. The advisory parity CI job behavior is unchanged (U6's tests excluded by `-m parity` selector). Production code in `src/` is unchanged.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| `tests/parity/conftest.py` module-import-time `_validate_parity_exceptions()` runs `_build_rule_id_map()` which walks `BUILTIN_PACKS`. If U6's Unit 1 helpers somehow trigger this validation at the wrong time, U6 collection could fail. | Verified the validation is idempotent at module import (already runs every parity test session). U6 Unit 1 adds helpers WITHOUT touching `BUILTIN_PACKS` or `_validate_parity_exceptions` — the new helpers are independent functions. KD-1's local `_build_package_same_rule_id_map()` in U6's test module sidesteps `RULE_ID_MAP` entirely. |
| Cross-module test-package import (`from tests.schema.lint.test_buf_smoke_assumptions import _SMOKE_FIXTURES`) breaks if pytest's `rootdir` resolution differs from package import. | `tests/schema/__init__.py` + `tests/schema/lint/__init__.py` verified present at HEAD. R25(b) collection-time invariant pins the relationship even if import succeeds but content drifts. Fallback: move `_SMOKE_FIXTURES` to `tests/_buf_helpers.py` (already a shared module). |
| Per-fixture `buf.yaml` parsing assumes top-level `lint.use` — a contributor migrating to module-scoped `modules[].lint.use` would silently break R25(d). | R25(d) explicitly reads top-level `lint.use` only and fails at collection time with a clear message pointing to the fixture-authoring convention. The fail-loud posture is the mitigation. |
| `--rule-pack=protokit.schema.lint.rules.package_same` invocation at test time loads ALL 7 R7 rules. If a future smoke fixture sets multiple options that conflict, protokit would fire multiple R7 rules on a fixture whose `buf.yaml` pins only one. | Per-fixture rule scoping via `assert_parity_multi_file(protokit_rule_ids={derived_rule_id})` + over-firing complement check catches this at test time. R25(d) collection-time invariant pins the single-rule precondition. |
| Sort-key uniqueness assumption `(path, line, col, rule_id)` may not hold for all fixtures — specifically `mixed-presence-java-package` (3 findings, same line per file). | Sort-key uniqueness is asserted before pairing (R24 contract). Implementation spot-checks `recorded/mixed-presence-java-package.json` to confirm `path` is the discriminator. Fallback: multiset equality on `(path, message)` tuples scoped by rule_id. |
| If R20 surfaces an actual parity divergence at `/ce:work`, the U6 deliverable expands. The brainstorm's S4 framing allows either "zero new entries" or "all surfaced divergences resolved." | KD-6 (NEW): single-divergence response uses inline `xfail` + tracked issue, NOT generalized `_PARITY_EXCEPTIONS` multi-file key shape (per [[buf-parity-divergence-documentation-discipline-2026-05-13]] one-specimen-not-pattern rule). Multi-file key shape design deferred until ≥2 specimens exist. |
| `_PARITY_EXCEPTIONS` map keyed by `(rule_id, fixture_stem)` uses single-file fixture stems; U6's fixture paths are multi-file directories. If U6 needs an exception entry, the validator at `conftest.py:193-227` would reject it (looks for `fixtures/<rule_id>/<stem>.proto`). | U6 stays exception-free per S4 expected outcome. If a divergence forces an entry, the validator extension is part of the divergence-response work (one specimen drives the design, not preemptive). |
| Helper subprocess invocations consume cold-Python import overhead × 21 cases. Empirically measured 0.07s per case = ~1.5s total — well under any reasonable timeout. | No mitigation needed; verified at brainstorm time. |

## Documentation / Operational Notes

- **`CHANGELOG-DRAFT.md` U6 staging entry** (Unit 3) — folded into the actual CHANGELOG at U7 per the dormancy-window pattern.
- **No README updates** in U6; U7 owns README refresh for Schema Linting section + BUILTIN_PACKS flip.
- **No `protokit lint --help` epilog changes** in U6; U7 owns the rule-pack discovery line cleanup.
- **No CI workflow edits** — U6's tests run in the existing `test` job (`.github/workflows/ci.yml:136`) by default; the advisory parity job excludes them via `-m parity` selector at `ci.yml:261`.

## Sources & References

- **Origin document:** [docs/brainstorms/2026-05-18-d6b-u6-r7-package-same-parity-tests-requirements.md](../brainstorms/2026-05-18-d6b-u6-r7-package-same-parity-tests-requirements.md)
- **Predecessor brainstorm:** [docs/brainstorms/2026-05-17-d6b-u4-r7-package-same-revised-requirements.md](../brainstorms/2026-05-17-d6b-u4-r7-package-same-revised-requirements.md)
- **Parent D6b brainstorm:** [docs/brainstorms/2026-05-14-protokit-lint-delivery-6b-option-aware-and-multi-language-requirements.md](../brainstorms/2026-05-14-protokit-lint-delivery-6b-option-aware-and-multi-language-requirements.md)
- **Parent D6b plan:** [docs/plans/2026-05-14-001-feat-protokit-lint-d6b-option-aware-and-multi-language-plan.md](2026-05-14-001-feat-protokit-lint-d6b-option-aware-and-multi-language-plan.md)
- **Related code:**
  - `tests/parity/conftest.py:354-579` (single-file helpers U6 extends)
  - `tests/parity/test_parity_package.py` (proven parity module shape)
  - `tests/schema/lint/test_buf_smoke_assumptions.py:47-72` (`_SMOKE_FIXTURES`)
  - `tests/schema/lint/rules/fixtures/package_same/_buf_smoke/recorded/` (21 SHA-pinned snapshots)
  - `tests/schema/lint/rules/fixtures/package_same/_buf_smoke/<scenario>/buf.yaml` × 21 (per-fixture single-rule declarations)
  - `src/protokit/schema/lint/rules/package_same.py` (`RULES` tuple)
  - `src/protokit/schema/lint/engine.py:241-242` (idempotent `load_rule_pack`)
  - `src/protokit/schema/lint/decorator.py:144-174` (`get_lint_spec`)
  - `tests/_buf_helpers.py:90-133` (`run_buf_subprocess`)
- **Related institutional learnings (from learnings-researcher):** `buf-parity-divergence-documentation-discipline-2026-05-13`, `upstream-rule-deprecation-skip-ordering-parity-harness-2026-05-13`, `programmatic-proto-fixture-builder-multi-file-rule-family-2026-05-17`, `subprocess-exit-code-validation-test-harness-2026-05-13`, `pytestmark-does-not-guard-module-top-imports-2026-05-02`, `structural-pin-inspect-getsource-untestable-collision-branch-2026-05-13`, `conftest-plain-function-relative-import-2026-05-12`, `fixture-precondition-assertion-surfaces-silent-test-2026-05-17`, `capture-setup-without-dispatch-false-test-confidence-2026-05-17`, `audit-wire-format-before-claiming-sibling-parity-2026-05-03`, `dormant-code-changelog-draft-staging-delivery-boundary-2026-05-17`, `stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12`, `test-method-names-encode-invariants-not-delivery-deltas-2026-05-13`.
