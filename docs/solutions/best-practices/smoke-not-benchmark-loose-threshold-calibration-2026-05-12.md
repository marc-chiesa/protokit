---
title: Smoke-not-benchmark performance test — loose threshold with investigate-don't-widen posture
date: 2026-05-12
category: best-practices
module: protokit-lint
problem_type: best_practice
component: testing_framework
severity: medium
applies_when:
  - A performance regression canary is needed but a full benchmark suite is out of scope
  - The test must be stable on noisy CI runners
  - The failure mode to detect is catastrophic (algorithmic regression, O(n²) walker) not micro-drift
  - The walker/iterator under test scales with the project's corpus size (schema size, AST size, etc.)
tags:
  - performance
  - smoke-test
  - threshold
  - canary
  - regression
  - ci-stability
  - calibration
  - perf-smoke
---

# Smoke-not-benchmark performance test — loose threshold with investigate-don't-widen posture

## Context

Performance regression tests live on a spectrum. At one end: a tight benchmark suite tracking per-rule median latency with statistical significance testing and historical baseline comparison. At the other end: no performance testing at all, relying on code review to catch algorithmic regressions.

Both extremes have failure modes. Tight benchmark suites on noisy CI runners become flaky. Flaky tests teach contributors to ignore failures. Ignored failures accumulate regression debt. Over time, the threshold is widened to stop the flakiness, the baseline drifts upward, and the canary becomes a no-op that passes while the engine gets slower with every delivery.

No performance testing means an O(n²) walker introduced by an innocent-looking refactor runs for 15 seconds on the typical schema corpus and nobody notices until a user reports it.

The D5 U6 delivery introduced `tests/schema/lint/test_perf_smoke.py` as a **smoke-not-benchmark**: a single test with a generous threshold, calibrated to detect catastrophic regressions while remaining stable on noisy CI runners. The design is explicit that the test is a canary, not a benchmark.

The lineage of this specific smoke goes back to D1. The D1 brainstorm flagged `_LintContextEmitMixin` allocating a per-descriptor `_emit_fn` closure on every walk step — a potential O(n) allocation amplifier. D1 couldn't measure it with canary-only workload, so the concern was punted as A5 ("perf smoke") to Delivery 5 step 11. The smoke is specifically guarding against that closure-allocation concern (and any similar walker-level regression), not general throughput. (session history)

## Guidance

### Threshold calibration

1. **Measure the local baseline.** Run the test on a representative developer machine under steady-state conditions. Note the median elapsed time (`t_baseline`).

2. **Apply generous headroom.** Set `threshold = t_baseline × N` where `N` is roughly 25–40. The headroom accounts for CI runner variance, cold-start JIT effects, and slower reference hardware. The D5 calibration used N ≈ 35: local baseline ~14ms on Apple Silicon → 500ms threshold.

3. **Validate the failure envelope.** At the target corpus size (e.g., 10,000 fields), an O(n²) walker would take `(n²/n) × t_O_n_local` time. Verify this is solidly inside the failure envelope. For D5: an O(n²) regression at 10k fields would land in the multi-second range, well above 500ms.

4. **Document the calibration.** Put the baseline, the headroom multiplier, and the O(n²) failure-envelope validation in the module docstring or the threshold constant's inline comment. Future maintainers need to understand why the threshold is what it is to make informed decisions about updating it.

```python
# Loose smoke-not-benchmark threshold. Local dev baseline ~14ms on
# Apple Silicon → ~35× headroom at 500ms. CI cells may run slower
# but should never approach this on healthy code. A catastrophic
# regression at 10k fields would land in the multi-second range,
# solidly inside the failure envelope.
_PERF_SMOKE_THRESHOLD_SECONDS = 0.5
```

### Failure posture: investigate, don't widen

The assertion failure message must explicitly tell future investigators NOT to widen the threshold by reflex. This sounds like an obvious instruction, but without it the reflex is nearly universal: the test is flaky, the threshold is widened, the test passes, nobody asks why the engine got slower.

```python
assert elapsed < _PERF_SMOKE_THRESHOLD_SECONDS, (
    f"lint engine took {elapsed:.3f}s for {n_total_fields} fields, "
    f"exceeding the smoke threshold of {_PERF_SMOKE_THRESHOLD_SECONDS}s. "
    f"This is a catastrophic-regression canary — investigate the root "
    f"cause; do not widen the threshold by reflex."
)
```

The phrase "do not widen the threshold by reflex" in the assertion message serves as a speed bump. It introduces just enough friction to make a contributor pause before the reflex widening.

### Frame the test as smoke-not-benchmark in its docstring

The module docstring (or function docstring) should:

- State "smoke, not benchmark" in the opening line.
- Explain that the intent is catastrophic-regression detection, not micro-perf drift.
- Explicitly acknowledge that CI runners are noisy and the threshold is loose by design.
- State the response to a failure: investigate, not widen.

```python
"""Perf smoke for ``protokit lint`` — catastrophic-regression canary.

The threshold is loose by design: the intent is to fail loudly when
a future change introduces an algorithmic regression (e.g. a quadratic
walker or per-field pool lookup), NOT to track micro-performance drift.
CI runners are noisy; a tight threshold would teach contributors to
ignore the test, which is worse than no test at all.

Response to a failure: investigate the root cause; do NOT widen the
threshold by reflex.
"""
```

### Corpus size and fixture design

Choose a corpus size where O(n) and O(n²) diverge visibly. For lint walkers:

- 10,000 fields (50 files × 20 messages × 10 fields) is a good anchor: O(n) at 14ms local, O(n²) projected at ~14s.
- The fixture should produce **zero findings** under the current rules — this validates the walker path, not the findings-accumulation path, and prevents `assert not report.findings` from masking a short-circuit.
- The fixture is generated at test time (parametrized .proto source generator), not checked in as binary descriptor sets. At-test-time generation avoids cross-version protobuf-library drift and keeps the fixture authoring loop in human-readable source.

### Three positive-behavior assertions before the threshold check

A single elapsed-time assertion is insufficient. Add three positive assertions that the walker actually ran before checking the threshold:

```python
# 1. Walker didn't short-circuit via findings (snake_case names produce none).
assert not report.findings, f"smoke fixture should produce zero findings; got {len(report.findings)}"

# 2. Walker didn't short-circuit via runtime warnings (catches rule_exception/unloaded_rule).
assert not report.runtime_warnings, f"unexpected runtime warnings: {report.runtime_warnings}"

# 3. Profile actually selected rules (catches accidental empty-walker degeneration).
assert report.rules_run, "profile selected zero rules; smoke is timing an empty walk"

# Only then check the threshold.
assert elapsed < _PERF_SMOKE_THRESHOLD_SECONDS, "..."
```

The `assert report.rules_run` is the underappreciated one. Without it, a refactor that accidentally empties `profile.rule_ids` satisfies `assert not report.findings` trivially while timing an empty walk. The canary would silently degrade to a no-op.

### Profile reconstruction: use `dataclasses.replace`, not parts-reconstruction

When deriving a test profile from a built-in pack, use `dataclasses.replace` to preserve fields not explicitly overridden. Parts-reconstruction silently drops fields:

```python
import dataclasses

# WRONG — silently drops rule_severity_overrides from the pack-derived profile
profile = LintProfile.from_pack(BUILTIN_PACKS[0], profile_name="default")
profile = LintProfile(
    name="default",
    rule_ids=profile.rule_ids,
    min_severity=LintSeverity.INFO,
)

# RIGHT — preserves rule_severity_overrides automatically
profile = dataclasses.replace(
    LintProfile.from_pack(BUILTIN_PACKS[0], profile_name="default"),
    min_severity=LintSeverity.INFO,
)
```

If the built-in pack ever declares severity overrides, the wrong form silently runs the smoke with subtly different policy than production lint — a silent correctness gap on top of a perf smoke.

### Pair with a fail-closed CI matrix coverage meta-test

A smoke gated by `@pytest.mark.skipif` to a specific cell can silently degrade to "skipped on every cell" if the matrix evolves. See [[fail-closed-ci-matrix-coverage-meta-test]] for the companion test that prevents this. The smoke and its coverage meta-test ship together; neither is fully useful without the other.

## Why This Matters

**The tight-threshold failure mode** degrades the canary via accumulated widening. Each widening is locally rational ("the test is flaky on CI, widening is safe because the regression I'm introducing is only 10% slower"). Cumulatively, the threshold drifts from a meaningful signal to a no-op. Nobody makes a single decision to break the canary; it degrades across many small decisions, each defensible in isolation.

**The loose threshold + investigate-don't-widen posture** preserves the canary's signal value by making widening a deliberate, documented decision rather than a reflex. If a contributor genuinely needs to widen the threshold because the system is legitimately slower (e.g., a new feature adds O(n) work to each field walk), they must document the calibration update in the same commit. The threshold constant's inline comment — which appears in the PR diff — serves as the accounting.

**The smoke-not-benchmark framing** manages contributor expectations. If a contributor expects the test to catch micro-drift and it doesn't, they may mistakenly conclude the test is "not working." If they understand it is a catastrophic-regression canary, they apply the correct mental model: this test failing means something is seriously wrong.

## When to Apply

- Any project with a walker, iterator, or traversal over a corpus that could become O(n²) via a future change (e.g., an inner loop that acquires a resource per element, a rule that re-traverses the corpus for each finding).
- Lint engines, schema validators, code generators, static analysis tools — anywhere the corpus size scales with project artifact size.
- Projects where a full benchmark suite is out of scope for the current delivery but a "don't introduce catastrophic regressions" constraint exists.
- Any test that would otherwise require tight thresholds to be meaningful — prefer the smoke-not-benchmark framing over tightening.

Do NOT apply as a substitute for a benchmark suite when:

- The project has SLA commitments on throughput requiring per-release validation.
- The performance characteristic being guarded is not catastrophic-regression but micro-drift (e.g., a user-visible interactive latency budget).

## Examples

**The protokit U6 instance** (canonical, `tests/schema/lint/test_perf_smoke.py`):

- Corpus: 50 files × 20 messages × 10 fields = 10,000 fields
- Local baseline: ~14ms on Apple Silicon (~37× headroom at 500ms)
- Threshold: 500ms (`_PERF_SMOKE_THRESHOLD_SECONDS = 0.5`)
- Gating: `@pytest.mark.slow` + `@pytest.mark.skipif(sys.platform != "linux" or sys.version_info[:2] != (3, 12))`
- Companion: `test_perf_smoke_coverage.py` (fail-closed matrix coverage meta-test)

**Adapting the calibration to a different corpus.** If the walker is O(n) in fields but the typical production corpus is 100 files × 50 messages × 30 fields = 150,000 fields, scale the fixture proportionally and re-measure:

- 150k fields at O(n), ~15× corpus → ~210ms local baseline
- Threshold at 30× headroom: ~6,300ms
- Verify: O(n²) at 150k fields = `(150k/10k)² × 14ms` ≈ 3,150ms. This is below the threshold — scale the corpus up further or accept the reduced failure envelope, documenting the tradeoff.

**The reflex-widening anti-pattern** (what the message text prevents):

```diff
- _PERF_SMOKE_THRESHOLD_SECONDS = 0.5
+ _PERF_SMOKE_THRESHOLD_SECONDS = 2.0   # widened because test was flaky
```

The correct response when the smoke fires unexpectedly: profile the code path under the smoke corpus, identify whether the regression is real or a measurement artifact, and either fix the regression OR — if the system is genuinely doing more work and that work is intentional — document the calibration update with a new baseline measurement in the same commit.

## Related

- `tests/schema/lint/test_perf_smoke.py` — canonical smoke implementation
- `tests/schema/lint/test_perf_smoke_coverage.py` — companion fail-closed meta-test
- D5 plan / R22 — calibration rationale (max_observed × ~30 method)
- D5 plan / R23a / R23b — `@pytest.mark.slow` + cell-predicate design decisions
- D1 brainstorm — original A5 perf-smoke deferral (closure-allocation concern in `_LintContextEmitMixin`)
- [[fail-closed-ci-matrix-coverage-meta-test]] — companion meta-test pattern; the smoke and the meta-test ship together
- [[pytest-static-analysis-gate-ratchet]] — parallel gate-as-pytest-test philosophy applied to static-analysis paths; this doc applies the pattern to performance assertions
- [[parametrized-matrix-tests-inherit-schema-validators]] — tangential: if the smoke is parametrized across formatters/backends, fixture-inheritance discipline applies
