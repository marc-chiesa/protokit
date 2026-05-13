---
title: "Tests iterating a registry for setup must also iterate it for exercise (perf-smoke profile composition across BUILTIN_PACKS)"
date: 2026-05-13
category: best-practices
module: protokit.schema.lint
problem_type: best_practice
component: testing_framework
severity: medium
applies_when:
  - "Writing a pytest test that iterates a registry (BUILTIN_PACKS, a plugin list, a fixture set) to load every member, then constructs the run input from a single index or literal"
  - "Reviewing tests that pin to ``REGISTRY[0]`` for the exercise step while iterating the same REGISTRY for the setup step"
  - "Adding a new member to a registry that is already iterated by setup-side test code"
tags:
  - perf-smoke
  - builtin-packs
  - profile-composition
  - registry-iteration
  - test-coverage
  - lint-rules
  - single-source-of-truth
  - drift-canary
---

# Tests iterating a registry for setup must also iterate it for exercise

## Context

`tests/schema/lint/test_perf_smoke.py` — the catastrophic-regression canary for `LintEngine.run` — loaded every member of `BUILTIN_PACKS` into the engine via a `for pack in BUILTIN_PACKS:` loop (setup), but then built the run profile from only `BUILTIN_PACKS[0]` (exercise):

```python
# Before fix (D5 U6, written when BUILTIN_PACKS = (naming,))
engine = LintEngine()
for pack in BUILTIN_PACKS:
    engine.load_rule_pack(pack)
profile = dataclasses.replace(
    LintProfile.from_pack(BUILTIN_PACKS[0], profile_name="default"),
    min_severity=LintSeverity.INFO,
)
```

When `BUILTIN_PACKS = (naming,)` (single member), `from_pack(BUILTIN_PACKS[0], "default")` returned the complete rule set — the asymmetry was invisible. When D6a Unit 4 expanded `BUILTIN_PACKS` to `(naming, enum)`, the exercise side silently dropped enum's 2 rules from the profile. The engine had them registered, but the run never invoked them. A catastrophic regression in the enum walker would have escaped the smoke entirely.

The smoke's positive-coverage assertions all kept passing:
- `assert not report.findings` — true because the naming pack's fixture-compatible field names guarantee zero findings.
- `assert not report.runtime_warnings` — true because no rule raised.
- `assert report.rules_run` — true because the naming pack's 9 rules were selected.

None of them tripped, because they exercise the *passing* shape of the test. The regression-canary value of the test eroded silently.

(Session history: the `BUILTIN_PACKS[0]` form was adopted in D5 U6 without explicit discussion because `BUILTIN_PACKS` had one member; the D5 brainstorm did not enumerate "what happens to existing tests when BUILTIN_PACKS gains a second pack." The D6a brainstorm's F3 finding anticipated user-facing impact of pack growth (`+ N new categories of findings on previously-green CI`) but did not flag test-infrastructure impact.)

## Guidance

**Use the same iteration form on both the setup side and the exercise side.** When a test loops over a registry for loading, it must also loop over the same registry for whatever drives the exercise:

```python
# imports elided — see tests/schema/lint/test_perf_smoke.py
# (LintEngine, LintProfile, LintSeverity from protokit.schema.lint;
# BUILTIN_PACKS from protokit.schema.lint.rules)

# After fix — symmetric: setup and exercise both iterate all packs
engine = LintEngine()
for pack in BUILTIN_PACKS:
    engine.load_rule_pack(pack)
# Compose the profile across every pack so the test exercises the
# full walker, not just the first pack's rules. LintProfile.compose
# is declared ``def compose(*profiles: LintProfile) -> LintProfile``,
# so the star-unpack of the generator is required, not stylistic.
# compose is identity-safe for single arguments, so the symmetric
# form is equally correct at registry size 1.
composed = LintProfile.compose(
    *(LintProfile.from_pack(pack, profile_name="default")
      for pack in BUILTIN_PACKS),
)
profile = dataclasses.replace(composed, min_severity=LintSeverity.INFO)
```

If a test must pin to a single registry member intentionally (isolate one pack's behavior), make the intent explicit and prevent the form from accidentally becoming the template for other tests:

```python
# Explicit isolation — intentional, not accidental
single_pack = BUILTIN_PACKS[0]  # isolating naming pack walker timing
profile = LintProfile.from_pack(single_pack, profile_name="default")
```

Naming the variable + a docstring or comment + a deliberate single-pack invocation (not an iteration that happens to use index 0) all signal "this is intentional pinning, not a leftover of single-member days."

## Why This Matters

The pre-2-member state of any registry hides the setup/exercise asymmetry. The smoke, the fixture, or whatever the test loop builds *looks* correct when there's one item — `[0]` and "all" are observationally identical. As soon as the registry grows:

- New members load into the engine (or whatever the setup loop targets) but are silently excluded from the exercise input.
- Positive-coverage assertions keep passing because new members are *dormant* under the exercise input rather than *producing findings*. The test reports green on the original behavior, not on the new total.
- The regression-canary value erodes proportionally to registry growth, without any CI signal. Each new member is one more place where a real bug could hide.

The general principle: **a test claiming to verify behavior across a collection should iterate that collection for both setup and exercise, or document why the asymmetry is intentional.** The single-source-of-truth principle in the [[rule-pack-extension-ssot-rule-ids-and-test-class-naming-2026-05-12]] learning applies at the test-input level too: derive the run input from the same iteration that built the setup state, not from a frozen pin to one index.

The failure mode is the same shape as [[fail-closed-ci-matrix-coverage-meta-test-2026-05-12]] — a test silently stops covering what it claims to cover — but at a different layer. That doc covers `@pytest.mark.skipif` predicates that no longer match any CI cell; this doc covers in-test registry pinning that no longer enumerates the full set. Both are "silent degeneration" defects discoverable only when you compare *what the test claims* against *what it actually exercised*.

## When to Apply

- **At write time** — when writing a new test that includes `for X in REGISTRY:` for setup, the exercise side should follow the same iteration form by default. The discipline is easier to add **before** the registry has a second member; once `[0]` works fine for years, it becomes the entrenched template that future contributors copy.
- **At review time** — when reviewing a PR that adds a new member to a registry already iterated by test code, search for tests pinning to `REGISTRY[0]` or `REGISTRY[index]` and verify whether each pin is intentional or accidental. The grep target is `BUILTIN_PACKS\[` (or `<your-registry>\[`); the question is "does this test still measure what it claims after this PR lands?"
- **In coverage audits** — when a test passes for years on the same fixture as the codebase grows around it, ask "does the test still exercise everything the codebase now defines?" Compare the test's effective input set against the canonical registry.
- **Extends beyond lint rules** — applies to any registry-style pattern: pytest parameterize values lists, plugin loader tuples, test case enum members, fixture composition. The discipline is "iterate the canonical collection for exercise, not a pinned subset."

## Examples

**Before** — `tests/schema/lint/test_perf_smoke.py` lines 145-151 at commit `313c8d8` (the D6a U4 feature commit, before this fix):

```python
engine = LintEngine()
for pack in BUILTIN_PACKS:
    engine.load_rule_pack(pack)
profile = dataclasses.replace(
    LintProfile.from_pack(BUILTIN_PACKS[0], profile_name="default"),
    min_severity=LintSeverity.INFO,
)
```

**After** — same file lines 145-162 at commit `1146e99` (the D6a U4 ce:review follow-up):

```python
engine = LintEngine()
for pack in BUILTIN_PACKS:
    engine.load_rule_pack(pack)
# Compose the profile across every pack in BUILTIN_PACKS so the
# smoke exercises the full walker, not just the first pack's rules.
# Before D6a Unit 4, BUILTIN_PACKS contained only the ``naming``
# pack and ``LintProfile.from_pack(BUILTIN_PACKS[0], ...)`` produced
# the complete rule set. After U4 added the ``enum`` pack, the
# single-pack form silently dropped enum's rules from the profile —
# the engine still loaded them, but the run never invoked them, so
# any catastrophic regression in the enum walker would have escaped
# the smoke entirely. Composing across every pack future-proofs the
# smoke against further BUILTIN_PACKS growth.
composed = LintProfile.compose(
    *(LintProfile.from_pack(pack, profile_name="default")
      for pack in BUILTIN_PACKS),
)
profile = dataclasses.replace(composed, min_severity=LintSeverity.INFO)
```

**Verification** (manual, since `test_perf_smoke.py` is skipif-gated on macOS):

```
elapsed: 14.8ms (threshold 500ms)
findings: 0 (must be 0)
rules_run count: 11 (was 9, now 11 — enum walker now exercised)
runtime_warnings: ()
```

The 11-rule walk finishes well within the 500ms threshold (~34× headroom), confirming the fix does not regress perf characteristics while restoring the smoke's intended coverage.

## Related

- [[smoke-not-benchmark-loose-threshold-calibration-2026-05-12]] — sibling on the same file, covering threshold calibration and corpus-design discipline. Its `## Profile reconstruction` section's "RIGHT" example showed the `BUILTIN_PACKS[0]` form during the single-pack era; that section was refreshed in the same compound pass that wrote this doc, to show the compose-across-all-packs form as the canonical example.
- [[rule-pack-extension-ssot-rule-ids-and-test-class-naming-2026-05-12]] — parallel single-source-of-truth discipline applied at the test-data level. That doc says derive the rule_id frozenset from `RULES`; this doc says derive the profile from the iteration over `BUILTIN_PACKS`. Both eliminate an "invisible update obligation" when the canonical collection grows.
- [[fail-closed-ci-matrix-coverage-meta-test-2026-05-12]] — same "silent degeneration" failure-mode shape at a different layer: that doc catches CI-matrix-yaml predicates that no longer match any cell; this doc catches in-test registry pinning that no longer enumerates the full set. Together they cover two of the common ways a coverage test silently stops covering what it claims to cover.
- [[audit-wire-format-before-claiming-sibling-parity-2026-05-03]] — adjacent: the audit discipline asks "is the claim still true?" Applied here as "is the test still measuring what it claims to measure after the canonical collection grew?"
