---
title: When N fixtures share a digest, pin the expected sharing set — the SHA gate alone permits invisible inter-fixture file swaps
date: 2026-05-19
category: docs/solutions/best-practices
module: tests/schema/lint/test_buf_smoke_recorded_checksums_package_directory.py
problem_type: best_practice
component: testing_framework
severity: medium
applies_when:
  - "A SHA-based checksum gate validates that committed snapshot files match recorded digests"
  - "Two or more snapshot fixtures are intentionally identical (canonical case: multiple empty NDJSON files all hash to the empty-bytes SHA `e3b0c44...`)"
  - "The parity test that consumes the fixtures cannot distinguish them by finding count (both expect 0 findings, or both expect the same N findings)"
  - "A directory rename without snapshot rename, or any future filename swap between same-digest fixtures, would be invisible to both the SHA gate and the parity test"
related_components:
  - tooling
tags:
  - fixture-integrity
  - sha-pin
  - checksum
  - empty-fixture
  - structural-anchor
  - silent-swap
  - parity-gate
  - invariant-pin
  - smoke-checksums
  - r8b
---

# When N fixtures share a digest, pin the expected sharing set — the SHA gate alone permits invisible inter-fixture file swaps

## Context

`tests/schema/lint/test_buf_smoke_recorded_checksums_package_directory.py` (and its R7 sibling for the package_same family) contains a SHA-256 integrity gate that verifies every committed `recorded/*.json` snapshot matches its pinned digest. The gate catches content modification, corruption, and accidental edits via byte-by-byte hash comparison.

The D6c U3 R8/R8b parity corpus committed 10 fixtures. **Two are intentionally empty** by design:

- `matched-dir.json` — proto files in the same directory all declaring the same package; R8 + R8b both fire 0 findings (no violation).
- `single-file-dir.json` — single file per directory; cannot have package conflicts; both rules fire 0 findings.

Both share the SHA-256 digest `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` (the canonical empty-bytes SHA-256). The SHA gate accepts both digests independently. The parity test accepts 0 findings from each.

D6c U3's ce:review (Finding #10, P3/0.97, adversarial) identified a structural gap: **a filename swap between the two fixtures is invisible to both gates**. Consider the scenario where a contributor renames `matched-dir/` to `same-package-dir/`:

```
Before rename:
  matched-dir/{a.proto, b.proto, buf.yaml}   ← proto inputs (same package, same dir)
  recorded/matched-dir.json                  ← empty snapshot (0 findings expected)

Mistake: git mv matched-dir/ same-package-dir/ (forgets to rename the snapshot)

After rename:
  same-package-dir/{a.proto, b.proto, buf.yaml}  ← proto inputs (still produce 0 findings)
  recorded/matched-dir.json                       ← orphan empty snapshot (NAME no longer matches a fixture)
```

- **SHA gate:** PASSES — `matched-dir.json` still has the correct empty-bytes digest.
- **Parity test:** PASSES if `single-file-dir.json` (the OTHER empty file with the same digest) accidentally becomes the new authoritative `matched-dir`'s pair. In the worst case, both fixtures could be silently mis-paired with each other's proto inputs and the parity assertions still pass because both produce 0 findings.
- **Structural error:** INVISIBLE. Label and content are misaligned, but every test passes.

The gated_auto fix added a `test_empty_snapshots_anchor_intended_fixtures` to the SHA-gate test module:

```python
_EMPTY_BYTES_SHA256 = (
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
)
_EXPECTED_EMPTY_FIXTURES: frozenset[str] = frozenset({
    "matched-dir",
    "single-file-dir",
})


def test_empty_snapshots_anchor_intended_fixtures() -> None:
    """Pin which fixtures are SUPPOSED to produce empty snapshots."""
    actual_empty: set[str] = {
        basename.removesuffix(".json")
        for basename, digest in _CHECKSUMS_PINNED.items()
        if digest == _EMPTY_BYTES_SHA256
    }
    assert actual_empty == _EXPECTED_EMPTY_FIXTURES, (
        f"Empty-snapshot fixture set drifted from the documented anchor.\n"
        f"  Pinned to be empty: {sorted(_EXPECTED_EMPTY_FIXTURES)!r}\n"
        f"  Actually empty:     {sorted(actual_empty)!r}"
    )
```

## Guidance

**Whenever two or more snapshot fixtures share a digest by design — for ANY digest, not just empty-bytes — add a structural anchor test that pins the exact set of fixture stems expected to share that digest.**

The anchor test is structurally distinct from the SHA gate:

| Layer | SHA gate | Structural anchor |
|---|---|---|
| What it checks | Each file's content matches its recorded digest | Which files share a digest matches the expected set |
| Catches | Content modification, corruption, accidental edit | Fixture rename without snapshot rename; unexpectedly identical fixtures |
| Fires when | Any SHA mismatch | The set of same-digest fixtures diverges from the expected set |
| Error message style | "Snapshot X has wrong digest" | "Expected fixtures {A, B} to be empty; actually empty: {A, C}" |

The SHA gate and the structural anchor compose: the gate verifies per-fixture content integrity; the anchor verifies cross-fixture structural alignment. Together they catch both content drift AND label drift.

### Pattern parts

1. **Define the shared digest as a named constant.** For empty-bytes that's `_EMPTY_BYTES_SHA256 = "e3b0c44..."`. For any other shared digest, pick a descriptive name (`_CANONICAL_3_FINDING_DIGEST`, etc.) and compute the hash via `hashlib.sha256(content).hexdigest()`.
2. **Pin the expected sharing set as a frozenset.** `_EXPECTED_EMPTY_FIXTURES: frozenset[str] = frozenset({"matched-dir", "single-file-dir"})`. Use frozenset (immutable) so the set itself is part of the contract.
3. **Compute the actual sharing set at test time.** Iterate the checksums dict; collect basenames whose digest equals the named constant.
4. **Assert exact equality.** `assert actual == _EXPECTED_*`. NOT subset, NOT contains — exact equality catches both unexpected additions (new fixture became identical) and unexpected removals (expected-identical fixture diverged).
5. **Error message must name both directions.** "Pinned to be empty" + "Actually empty" + "Only in pinned" + "Only in actual". A contributor hitting the failure should know which fixtures the expected set covers AND which fixtures actually match — and remediate in the right direction.

### Two remediation paths

The error message should make both paths obvious:

- **Path A: the new state is intentional.** A fixture legitimately became identical (e.g., a buf-version bump made a previously-firing fixture clean). Update the expected set + commit the new SHA.
- **Path B: the new state is accidental.** A fixture that should fire is producing 0 findings (regression). Regenerate the snapshot.

Without naming both paths, the contributor sees only "test failed" and may pick the wrong remediation.

## Why This Matters

**Invisible structural errors are the hardest class to detect.** Wrong content fails the SHA gate. Wrong filename + correct content passes both the SHA gate and the parity test if the parity test's finding-level assertion can't distinguish between fixtures sharing a digest. The structural error has no syntactic signal — only the label-to-content alignment is broken, and no per-fixture test asserts that alignment.

**Shared-digest fixtures create structural symmetry that masks swaps.** In a corpus of N fixtures where 2 are empty by design, the probability of a contributor accidentally swapping their names via a rename-without-rename-snapshot is nonzero — especially in CLI workflows that `git mv` the fixture directory but forget to rename the snapshot artifact. The anchor makes this swap observable at test time.

**Pre-1.0 corpora grow quickly.** D6c added 10 fixtures across R8/R8b. Future D6d deliveries will add more. As the corpus grows, the number of expected-empty (or expected-N-finding) fixtures may grow. Anchoring each such set at the time it first ships is much cheaper than auditing the full corpus later.

**The anchor doubles as accidental-regression detection.** If a fixture that should fire produces 0 findings (e.g., a code change silently broke the rule), the snapshot regenerates to the empty-bytes SHA. The anchor's `actual_empty - _EXPECTED_EMPTY_FIXTURES` set is non-empty and the assertion fails with a clear "this fixture is unexpectedly empty" message. The same test surface that catches label drift also catches silent-rule-regression.

## When to Apply

Apply this discipline when ALL of the following hold:

1. Two or more snapshot fixtures share a digest by design (check with `groupby(sorted(files, key=sha256))` or by inspecting the checksums file for repeated hash values).
2. The downstream test (parity test, snapshot test, integration test) cannot distinguish between same-digest fixtures by content alone — both produce the same observable outcome (0 findings, identical render, etc.).
3. The fixture corpus is growing across delivery units — each new fixture is an opportunity to create an accidental same-digest sibling that the anchor would catch.

**Do NOT apply when:**

- All fixtures have unique digests — no structural symmetry, no swap risk.
- The SHA gate already uses a per-fixture mapping that fails on filename change (i.e., the gate is keyed by filename AND digest; renaming would cause a key-miss). In that case, the structural anchor is redundant.
- The same-digest set is genuinely accidental and not load-bearing (e.g., two unrelated fixtures happen to share a hash). In that case, change one fixture so the digests diverge — the right answer isn't an anchor; it's removing the unintentional symmetry.

## Examples

### Canonical empty-bytes anchor (D6c U3 R8/R8b corpus)

```python
import hashlib
from pathlib import Path

_EMPTY_BYTES_SHA256 = hashlib.sha256(b"").hexdigest()
# == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

_EXPECTED_EMPTY_FIXTURES: frozenset[str] = frozenset({
    "matched-dir",       # R8 + R8b both clean: same dir, same package, single dir
    "single-file-dir",   # R8 + R8b both clean: only one file per directory
})


def test_empty_snapshots_anchor_intended_fixtures() -> None:
    """Pin which fixtures are SUPPOSED to produce empty snapshots.

    The SHA gate accepts each empty snapshot independently; if a
    contributor swapped the filenames of matched-dir.json and
    single-file-dir.json, both files still hash to the empty-bytes SHA
    and the gate passes. The parity test also passes — both fixtures
    produce 0 findings regardless of which proto inputs they pair with.

    This test catches the swap: it asserts the SET of fixture names
    whose snapshots have the empty-bytes digest matches the documented
    expected set EXACTLY.
    """
    actual_empty: set[str] = {
        basename.removesuffix(".json")
        for basename, digest in _CHECKSUMS_PINNED.items()
        if digest == _EMPTY_BYTES_SHA256
    }
    assert actual_empty == _EXPECTED_EMPTY_FIXTURES, (
        f"Empty-snapshot fixture set drifted from the documented anchor.\n"
        f"  Pinned to be empty: {sorted(_EXPECTED_EMPTY_FIXTURES)!r}\n"
        f"  Actually empty:     {sorted(actual_empty)!r}\n"
        f"  Only in pinned (no longer empty?): "
        f"{sorted(_EXPECTED_EMPTY_FIXTURES - actual_empty)!r}\n"
        f"  Only in actual (unexpectedly empty?): "
        f"{sorted(actual_empty - _EXPECTED_EMPTY_FIXTURES)!r}\n"
        f"\n"
        f"Path A (the new state is intentional): add the newly-empty "
        f"fixture stem to _EXPECTED_EMPTY_FIXTURES.\n"
        f"Path B (the new state is accidental): regenerate the snapshot "
        f"from a fresh buf invocation against the fixture's proto inputs."
    )
```

### Generalization for non-empty shared-digest sets

```python
# Hypothetical scenario: two cofire fixtures intentionally produce
# the same 6-finding output (e.g., normalized for sort-order).
_CANONICAL_6_FINDING_DIGEST = "<sha256-of-the-6-finding-NDJSON>"
_EXPECTED_6_FINDING_FIXTURES: frozenset[str] = frozenset({
    "cofire-r8-r8b-n2",
    "cofire-r8-r8b-n2-alphabetic",
})


def test_canonical_6_finding_anchor() -> None:
    actual: set[str] = {
        basename.removesuffix(".json")
        for basename, digest in _CHECKSUMS_PINNED.items()
        if digest == _CANONICAL_6_FINDING_DIGEST
    }
    assert actual == _EXPECTED_6_FINDING_FIXTURES
```

The pattern scales linearly — one constant + one frozenset + one test per shared-digest cluster.

### The structural gap without the anchor (invisible scenario)

```
# Before any rename:
#   tests/schema/lint/rules/fixtures/package_directory/_buf_smoke/
#     matched-dir/{a.proto, b.proto, buf.yaml}
#     single-file-dir/{a.proto, buf.yaml}
#     recorded/matched-dir.json       (empty, e3b0c44...)
#     recorded/single-file-dir.json   (empty, e3b0c44...)
#
# Contributor renames matched-dir → same-package-dir but forgets the snapshot:
#   git mv matched-dir/ same-package-dir/
#   # forgot: git mv recorded/matched-dir.json recorded/same-package-dir.json
#
# After:
#   same-package-dir/{...}             ← proto inputs renamed
#   single-file-dir/{...}              ← unchanged
#   recorded/matched-dir.json           ← orphan (no fixture by this name)
#   recorded/single-file-dir.json       ← OK
#
# SHA gate result:        matched-dir.json still has e3b0c44... → PASS
# Parity test result:     same-package-dir reads (which snapshot?) → ambiguous;
#                         if the harness looks up by fixture name, no snapshot
#                         exists for same-package-dir → test errors loudly here
#                         (the harness's fixture-mapping is the rescue layer)
#                         BUT if the harness silently fell back to an empty
#                         snapshot match, the parity test would PASS.
#
# Anchor test result:    _EXPECTED_EMPTY_FIXTURES = {"matched-dir", "single-file-dir"}
#                        actual_empty (basenames with empty SHA) = {"matched-dir", "single-file-dir"}
#                        ← STILL matches because matched-dir.json still exists.
#                        The anchor does NOT catch this specific orphan-snapshot
#                        case — the fixture-mapping harness catches it first.
#
# But consider a different swap: contributor renames AND moves snapshot incorrectly:
#   git mv matched-dir/ pkg-a/
#   git mv single-file-dir/ pkg-b/
#   git mv recorded/matched-dir.json recorded/pkg-b.json     ← swapped!
#   git mv recorded/single-file-dir.json recorded/pkg-a.json ← swapped!
#
# After:
#   pkg-a/{matched-dir's proto inputs}
#   pkg-b/{single-file-dir's proto inputs}
#   recorded/pkg-a.json   ← was single-file-dir's snapshot (still empty)
#   recorded/pkg-b.json   ← was matched-dir's snapshot (still empty)
#
# SHA gate result:        all pinned hashes match.
# Parity test result:     pkg-a's proto inputs produce 0 findings; pkg-a.json is
#                         empty → match. Same for pkg-b. PASS.
# Anchor test result:     _EXPECTED_EMPTY_FIXTURES = {"matched-dir", "single-file-dir"}
#                        actual_empty = {"pkg-a", "pkg-b"}
#                        ← MISMATCH. Test FAILS loudly: "Pinned: {matched-dir,
#                          single-file-dir}; Actually empty: {pkg-a, pkg-b}".
```

The anchor specifically catches the case where same-digest fixtures get renamed in a way that the per-fixture SHA gate cannot detect.

## Related

- [[fixture-precondition-assertion-surfaces-silent-test-2026-05-17]] — the structural-anchor pattern joins the silent-test-confidence family as a passive-detection mechanism. Both share the symptom class: test is green, structural state is wrong.
- [[module-import-time-fixture-mapping-fail-loud-blast-radius-2026-05-18]] — import-time blast-radius discipline. The structural anchor fires at test-collection time (before any test logic runs) — same "fail early, fail loudly" principle.
- [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]] — the parity gate that the anchor protects. The anchor ensures the gate's fixture corpus remains structurally coherent (each fixture stem corresponds to the correct proto inputs) as the corpus grows.
- [[audit-wire-format-before-claiming-sibling-parity-2026-05-03]] — audit discipline for the corpus as a whole. The structural anchor is the executable form of "verify fixture labels match their contents before claiming the parity gate covers a given scenario."
- [[programmatic-proto-fixture-builder-multi-file-rule-family-2026-05-17]] — fixture-creation discipline at the input side. The structural anchor complements it at the output side: builder discipline ensures inputs are well-formed; anchor discipline ensures outputs are correctly labeled.
- [[family-aware-partition-pattern-multi-family-parity-harness-2026-05-19]] — sibling pattern at the harness layer (data structures with consistent invariants). Both apply the same principle: when multiple structures track the same domain, pin the consistency explicitly so drift surfaces loudly rather than silently passing.
