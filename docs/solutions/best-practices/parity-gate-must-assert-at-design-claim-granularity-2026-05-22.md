---
title: Parity gate must assert at the granularity the design claim names
date: 2026-05-22
last_updated: 2026-05-22
category: docs/solutions/best-practices
module: tests.parity
problem_type: best_practice
component: testing_framework
severity: high
applies_when:
  - A design choice frames the parity contract at a specific granularity ("byte-equivalent at line/column", "byte-equivalent at file granularity", "matches finding set per fixture")
  - The parity gate is a generic helper that accepts a tunable comparison key
  - The comparison key defaults to a coarser granularity than the design claim names
  - The test docstring or module commentary asserts the design claim but the implementation only invokes the coarser comparison
  - A regression at the finer granularity would not register as a parity failure
related_components:
  - testing_framework
  - tooling
tags:
  - parity-discipline
  - documentation-vs-test-coverage
  - finding-pattern
  - regression-guard
  - ce-review-pattern
---

# Parity gate must assert at the granularity the design claim names

## Context

D6e U3 shipped `package/no-import-cycle` per the user-selected Option B at ce:review session 2026-05-22: "byte-equivalent buf v1.69.0 parity at finding-set + line/column granularity." Implementation extended `FileLocation` with optional `line`/`column` fields, updated JSON + SARIF formatters to render them, and implemented `_import_source_position` to read `SourceCodeInfo.Location` for per-import line/column.

The initial parity test (commit `e66f27c`) called the shared `assert_parity_multi_file` helper. Three reviewers (testing T1 at 0.97, adversarial ADV-002 at 0.99, agent-native Warning 2) flagged the same defect: the helper compares `(rule_id, normalized_path, message)` triples — line/column values from the BufFinding snapshots are PARSED THEN DISCARDED. The "byte-equivalent at line/column" design claim was documentation-only; the parity test would silently survive any regression in `_import_source_position` (off-by-one in the 0→1 conversion, wrong field number 3, missing include_source_info plumbing, span index arithmetic errors).

The fix (commit `eff3a80`) added a Tier 2 per-finding assertion to the test:

```python
buf_position_map = {
    (bf.path, bf.message): (bf.start_line, bf.start_column)
    for bf in buf_findings if bf.type == "PACKAGE_NO_IMPORT_CYCLE"
}
for pf in protokit_findings:
    if pf["rule_id"] != "package/no-import-cycle":
        continue
    expected = buf_position_map.get((pf["location_file"], pf["message"]))
    assert expected is not None
    assert pf["location_line"] == expected[0]
    assert pf["location_column"] == expected[1]
```

All 5 fixtures PASSED — confirming protokit's line/column already matched buf v1.69.0 byte-equivalently; the previous test version just wasn't asserting it.

## The pattern

When a design choice frames the parity contract at granularity G, the parity gate MUST assert at granularity G. The shared parity helper defaults to a coarser granularity for backward compatibility with rules that don't need finer comparison — that's correct as a default, but the per-test assertion must opt into the finer granularity when the rule's design claim requires it.

Generic shape of the test:

```python
def test_parity_byte_matches_recorded_snapshot(fixture_name: str) -> None:
    """..."""
    protokit_findings = run_protokit_lint_multi_file(fixture_dir)
    buf_findings = parse_buf_recorded_snapshot(snapshot_path)
    # Tier 1: scope-checked parity at the SHARED helper's granularity.
    # (file-path level, for rules that emit at FileLocation)
    assert_parity_multi_file(
        protokit_findings, buf_findings,
        protokit_rule_ids=<inclusion_set>,
        fixture_scenario=fixture_name,
    )
    # Tier 2: per-finding assertion at the rule's specific design
    # claim granularity. Build a lookup map from buf snapshot to the
    # claimed-granularity values; iterate scoped protokit findings;
    # assert each matches.
    buf_<claim_key>_map = {
        (bf.path, bf.message): (bf.<claim_field>, ...)
        for bf in buf_findings if bf.type == <buf_rule_id>
    }
    for pf in protokit_findings:
        if pf["rule_id"] != <protokit_rule_id>:
            continue
        expected = buf_<claim_key>_map.get(
            (pf["location_file"], pf["message"]),
        )
        assert expected is not None, <diagnostic>
        # Per-field assertions with specific failure diagnostics
        # that point at the implementation function whose
        # invariant the test enforces.
```

## Why both tiers, not just Tier 2

Don't replace the shared helper call with the per-finding loop. The shared helper performs four things the per-finding loop doesn't:

1. **Scope partition**: distinguishes in-scope findings from over-firing complement findings (a rule firing outside its profile boundary).
2. **Unknown-rule diagnostics**: surfaces typo'd rule_ids that look like family-prefix matches.
3. **Cross-family bucket inspection**: ensures the fixture didn't accidentally exercise an unrelated rule.
4. **Sort-key uniqueness pre-assertion**: catches snapshot corruption where two buf findings have the same sort key.

The per-finding loop is additive — it asserts the design-claim granularity ON TOP of the shared helper's coarser comparison. Both tiers fire; either failing surfaces a different class of regression.

## When this discipline applies

Apply Tier 2 per-finding assertion whenever the design claim names a finer granularity than the shared parity helper compares:

- **Line/column byte-equivalence**: shared helper compares `(rule_id, path, message)`; design claim adds `(start_line, start_column)`. (D6e U3 case.)
- **Column-only differences**: helper compares file + line; design claim adds column. Common in formatter-aware rules.
- **Range emission**: helper compares start; design claim asserts `(start, end)` byte-equivalence.
- **Field-path navigation**: helper compares file + message; design claim adds field index, oneof index, or nested-message path.
- **Multi-arm message_template**: helper compares rendered message; design claim asserts violation_kind + params shape per arm.

Skip Tier 2 when the design claim genuinely is "finding-set parity at file granularity" — most existing protokit rules ship at this level. The discipline only applies when the design CLAIMS finer granularity than the shared helper compares.

## How to spot this gap during ce:review

Three signals during code review:

1. **A test docstring or module commentary names a finer-than-tested parity granularity.** Example from D6e U3: "byte-equivalent buf parity means matching not just the FINDING SET but also the line/column of each finding." If the test body only calls `assert_parity_multi_file` and the helper compares `(file, message)`, the doc claim outruns the test coverage.

2. **The helper's source code has a comment deferring to "caller's responsibility".** The D6e U3 conftest comment: *"per-rule line/column assertions are the caller's responsibility (e.g., U3's parity test adds a separate line/column check)."* If you grep the caller for the deferred check and find none, that's the gap.

3. **The recorded snapshot has fields that the comparison key doesn't reference.** BufFinding carries `start_line` + `start_column` + `end_line` + `end_column`. If the parity-test grep for those field names finds only `parse_buf_recorded_snapshot` (parsing) but not the test body (comparison), the data is unused.

ce:review reviewers should flag the discrepancy at P1 confidence — without the Tier 2 assertion, a regression at the design-claim granularity slips through silently.

## When ce:review flagged this in U3

Three reviewers independently surfaced the gap:

- **testing T1 (confidence 0.97)**: "Line/column parity claimed but never asserted. The module and test docstrings both state 'byte-equivalent buf parity means matching not just the FINDING SET but also the line/column of each finding.' This is false. `assert_parity_multi_file` compares `(buf_rule_id, path, message)` 3-tuples."
- **adversarial ADV-002 (confidence 0.99)**: "Parity claim false: line/column byte-equivalence is asserted in docstrings but never tested — buf and protokit could diverge at any line/column value."
- **agent-native Warning 2**: "Parity test does not assert location_line/location_column against buf start_line/start_column."

Cross-reviewer convergence at this confidence on the same issue is the strong signal pattern documented at [[ce-review-convergence-rescues-sub-threshold-findings-2026-05-17]] — when 3+ reviewers independently flag the same issue, the merged confidence rescues sub-threshold individual findings AND the issue's severity should move to P1 even if no single reviewer rated it P1 individually.

## Related disciplines

- [[ce-review-convergence-rescues-sub-threshold-findings-2026-05-17]] — the meta-pattern: cross-reviewer agreement is strong signal; this U3 case is a worked example.
- [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]] — the parity-gate-as-oracle discipline; this learning extends it with the "claim-granularity-vs-helper-granularity" gap.
- [[ce-review-cross-reviewer-agreement-shared-misreading-false-positive-amplifier-2026-05-14]] — the discriminator: ensure the convergence is via independent reasoning chains, not shared misreading. For U3 T1/ADV-002/Agent-native W2: the three reviewers cited different specifics (T1 quoted the docstring; ADV-002 quoted the conftest deferral comment; Agent-native traced the BufFinding fields). Independent reasoning; not a shared-source amplifier.
- [[tarjan-scc-iterative-dfs-package-cycle-detection-2026-05-22]] (sibling captured at same boundary) — the algorithmic context where this discipline mattered.
- [[phase-0-narrowing-rule-reachable-but-narrower-than-brainstorm-assumed-2026-05-22]] (sibling captured at same boundary) — Phase 0 reveals the rule's actual ground; this discipline catches whether the test asserts at the claimed granularity within that ground.

## Worked example

D6e U3 commit sequence:

1. `e66f27c feat(lint): D6e U3 — package/no-import-cycle` — initial implementation with the documentation-only claim of byte-equivalent line/column parity (test only invoked `assert_parity_multi_file`).
2. ce:review run `20260522-230615-e23aa0e2` — 3-way convergence on the gap at high confidence (T1 0.97, ADV-002 0.99, Agent-native W2).
3. `eff3a80 fix(lint): ce:review U3 follow-ups` — added Tier 2 per-finding line/column assertion. All 5 fixtures PASS, confirming protokit's line/column actually do match buf v1.69.0 byte-equivalently. The protection is regression-forward: any future change to `_import_source_position` that breaks the byte-equivalence (off-by-one, wrong field number, broken span arithmetic) will fail the new assertion with a structured diagnostic naming the suspect function.
4. `<this commit> docs(solutions): D6e U3 ce:compound` — captures the pattern (this file) + sibling learnings for Tarjan SCC + Phase 0 narrowing.

The lesson for future per-unit work: **if your design choice promises granularity X, your test must compare at granularity X**. The shared helper's coarser default is correct for the common case but the per-test opt-in is mandatory whenever the claim is finer.
