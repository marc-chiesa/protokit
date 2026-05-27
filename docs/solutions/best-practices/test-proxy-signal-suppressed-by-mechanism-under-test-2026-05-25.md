---
title: "Test proxy signal must be independent of the suppression mechanism under test"
date: 2026-05-25
category: docs/solutions/best-practices
module: tests/schema/lint
problem_type: best_practice
component: testing_framework
severity: high
applies_when:
  - "Writing a test that verifies a suppression, disable, filter, or exclusion mechanism"
  - "The test fixture depends on the same subsystem the mechanism interacts with"
  - "The primary assertion is an absence assertion (zero findings, no warnings, empty result)"
  - "The mechanism expands one input directive into multiple downstream effects (N-rule disable, family suppression, multi-kind expansion)"
tags:
  - test-design
  - suppression-testing
  - false-confidence
  - baseline-contrast
  - proxy-signal
  - blast-radius
  - silent-test
  - vacuous-assertion
related_components:
  - tooling
  - development_workflow
---

# Test proxy signal must be independent of the suppression mechanism under test

## Context

During D6f U3 ce:review (2026-05-25), three reviewer personas — correctness, testing, and kieran-python — independently converged on the same defect in `tests/schema/lint/test_cli_rule_pack_dedup.py::TestR9bCliInteractionRegression::test_multi_kind_custom_prefix_expansion_via_cli_no_duplication` (the "Case 5" test for R14b). Confidence scores were 0.82, 0.90, and 0.65 respectively; cross-reviewer convergence boosted effective confidence well above any single-reviewer threshold. The finding was surfaced before commit — the structural payoff of running ce:review in boost mode per [[ce-review-convergence-rescues-sub-threshold-findings-diverse-personas-2026-05-17]].

The test was designed to verify that a bare-prefix `--disable-rule custom/<X>` at the CLI suppresses BOTH materialized rule_ids that a multi-kind `custom_annotation_rule` produces via `synthetic_rule_ids` mangling:

- `custom/dual-thing` — first-kind bare form
- `custom/dual-thing__field` — subsequent-kind mangled form

The original fixture used a multi-kind rule declared with `element_kinds = ["field", "method"]`, but the extension `example.dual_thing` was intentionally left unregistered — no `extend google.protobuf.MethodOptions { ... }` proto appeared in the descriptor set. Every closure hit `pool.FindExtensionByName("example.dual_thing")` → `KeyError` → emitted `custom_annotation_extension_unresolved` and returned without firing any lint finding.

The two assertions were:

1. Zero `custom/...` findings
2. Zero `unknown_rule_id` warnings for the bare suffix

Both assertions were vacuously true regardless of whether the disable mechanism worked:

- Assertion (a): no findings could fire EVER because the extension was unresolved. A regression that left `custom/dual-thing__field` unsuppressed would still produce zero findings — the FIELD closure would also hit `KeyError` on the unresolved extension and emit a warning instead of a finding.
- Assertion (b): `unknown_rule_id` for the bare suffix could never fire — `custom/dual-thing` IS in `_loaded_specs` as the first-kind closure registered by `synthetic_rule_ids`. The engine had no structural reason to emit that warning here regardless of mechanism state.

The test docstring even claimed the absence of `unknown_rule_id` was the "load-bearing signal" for prefix expansion success. That claim was wrong. The test passed in the U3 implementation phase for exactly this reason: the green CI was a misleading signal, not evidence of mechanism correctness.

The `example.dual_thing extends MethodOptions` design choice was a setup convenience — the test author needed a multi-kind custom annotation to prove prefix expansion, and the unresolved-extension shortcut avoided the cost of compiling a real extension proto into the descriptor set (session history). No prior session contains any discussion, rejection, or acceptance of alternative designs for this test; the choice was made without deliberation.

The U2 ce:review (one delivery prior) HAD found a sibling false-confidence test (T-02: `test_enable_rule_repeatable` asserted only exit code without payload check) and fixed it as a point fix. The repair discipline was not articulated as a general principle at U2, so Case 5 was written at U3 without benefit of the articulation. The current learning fills that gap.

## Guidance

Apply two checks when designing any suppression, filter, or disable mechanism test:

**Check 1 — Independence check.** Ask: could the proxy signal be absent for a reason OTHER than the mechanism working correctly? If yes, the assertion is vacuous. The proxy must be independently capable of firing before the mechanism is applied.

> **Rule:** The "broken-state" signal your test watches for must NOT itself be in the suppression mechanism's blast radius. If the proxy you measure is also being suppressed when the mechanism works — or is structurally impossible to fire regardless of mechanism state — your assertion is vacuous.

**Check 2 — Baseline contrast.** The test must compare a WITH-mechanism state against a WITHOUT-mechanism baseline. If only the post-mechanism state is observed, you cannot distinguish "mechanism worked" from "signal was never going to fire anyway." The baseline assertions must be independent: each observable signal must be confirmed present before suppression is applied.

These two checks together produce a valid suppression test:

1. Construct a fixture where the signal CAN fire (independently of the mechanism).
2. Assert it DOES fire in the baseline (no mechanism applied).
3. Apply the mechanism.
4. Assert the signal is now absent.

For multi-signal mechanisms (bare-prefix expansion suppresses N materialized rule_ids; family-list disable suppresses N rule_ids in one declaration), assert ALL N signals in both the baseline and the suppressed state. If only M < N signals appear in the baseline, the test cannot prove the mechanism suppressed the remaining N − M.

**Two-layer pattern that works (codified in the Case 5 fix):**

For mechanisms with a unit-layer contract AND a CLI-layer integration boundary, split the test into two parts:

- **Part 1 — Unit-level direct assertion of the mechanism's contract.** Assert the mechanism's resolved state directly (e.g., `ResolvedLintConfig.from_dict` produces both materialized rule_ids in `disabled_rules`). This is independent of any downstream subsystem and proves the mechanism's contract at its narrowest point.
- **Part 2 — Integration-level baseline-vs-mechanism comparison.** Use real, resolvable fixtures so all N signals fire in the baseline. Assert the baseline signals are all present, then apply the mechanism, then assert all N signals are absent. The baseline assertions are the load-bearing independence check.

When Part 1 is structurally cheap (the unit layer is a pure function over typed inputs), it is mandatory — it gives Part 2 a fallback signal even if the integration fixture has unrelated drift.

## Why This Matters

The failure mode this prevents is a silent test regression: a real bug in the suppression mechanism slips through CI because the test's observable was never going to fire anyway. The regression can persist for weeks or months until the mechanism is exercised by a path the test is structurally incapable of detecting.

Cost asymmetry is severe. Adding a baseline contrast takes approximately five minutes at test-writing time. Discovering a latent suppression regression post-ship — after the broken mechanism has quietly passed hundreds of CI runs — can require days of triage, because the test suite provides no signal that anything changed. The pattern is structurally identical to the post-ship monitoring problem documented in post-ship-adoption-monitoring-pre-1.0-breaking-default-change-2026-05-19: "null proxy is no proxy."

The Case 5 defect also illustrates the structural payoff of ce:review boost mode. Three personas independently converged on the same finding before any commit landed. Without that convergence, the vacuous test would have merged, the R14b multi-kind disable contract would have had no working regression guard, and any future refactor that broke bare-prefix expansion for mangled rule_ids would have passed CI silently. The ce:review workflow surfaced the defect at the cheapest possible point in the delivery cycle, in the same way the prior false-confidence-family learnings ([[capture-setup-without-dispatch-false-test-confidence-2026-05-17]], [[fixture-precondition-assertion-surfaces-silent-test-2026-05-17]], [[multi-element-fixture-list-disable-coverage-all-kinds-2026-05-25]]) were each surfaced by review rather than by test-failure signal.

Critically, the U2 ce:review found and point-fixed a sibling false-confidence test (T-02) one delivery earlier (session history). The point-fix did not generalize the underlying principle, so the same mistake was made again at U3. This learning is the generalization that the point-fix didn't capture — it converts a repeated reactive fix into a proactive named discipline.

## When to Apply

Apply this discipline whenever all of the following are true:

- The test exercises a suppression, filter, or disable mechanism (the mechanism's purpose is to prevent something from happening).
- The test fixture depends on a subsystem that the mechanism also interacts with (the mechanism and the fixture share a code path).
- The test's primary assertion is an absence assertion ("zero findings", "no warnings", "no errors", "empty result list").

This is most critical for:

- Lint rule disable / suppress infrastructure (per-rule, per-profile, per-prefix, multi-kind expansion).
- Feature flag or capability gating (the gate and the fixture share the same resolution path).
- Access control or permission filters tested against fixtures that happen to be denied for an unrelated reason.
- Config-driven exclusion lists tested against fixtures where the exclusion and the fixture use the same lookup.
- Cache invalidation tests where the cached signal could be absent for cache-miss reasons rather than invalidation success.

It is less critical for additive mechanisms, where the broken state IS the absence of the added behavior and is naturally observable without a baseline. If you are testing "rule X fires when condition Y is present," absence of the finding when Y is absent is independently meaningful. The risk is asymmetric: additive tests naturally have a baseline (no condition → no finding). Suppression tests naturally lack one (mechanism off → signal fires; mechanism on → signal absent) — you must add the baseline explicitly.

The discipline is NOT a substitute for the related fixture-coverage discipline in [[multi-element-fixture-list-disable-coverage-all-kinds-2026-05-25]]. They are complementary checks at different layers: that learning ensures the FIXTURE exercises all N targets a multi-rule suppression should affect; this learning ensures the OBSERVABLE chosen for the assertion is structurally capable of failing if the mechanism is broken. A test that passes fixture-coverage but fails proxy-independence is still vacuous. A test that passes proxy-independence but fails fixture-coverage is still incomplete. Apply both.

## Examples

### Before — vacuous suppression test (Case 5 original)

```python
def test_multi_kind_custom_prefix_expansion_via_cli_no_duplication(self, tmp_path):
    """
    Case 5: bare-prefix --disable-rule custom/<X> suppresses both materialized
    rule_ids for a multi-kind custom_annotation_rule.

    Load-bearing signal: absence of unknown_rule_id for the bare suffix.
    """
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(textwrap.dedent("""\
        [tool.protokit.lint]
        profile = "default"

        [[tool.protokit.lint.custom_annotation_rules]]
        rule_suffix    = "dual-thing"
        option         = "example.dual_thing"   # NOT registered in descriptor set
        element_kinds  = ["field", "method"]
        severity       = "warning"
        """))
    # Proto with field + service method, neither annotated — no extension proto
    descriptor_set = compile_sources_to_descriptor_set(
        tmp_path,
        {"r14b/dual/carrier.proto": MINIMAL_PROTO3_SOURCE},
        out_filename="r14b_case5.descriptor_set",
    )
    result = CliRunner().invoke(
        lint_main,
        [f"--config={pyproject}", "--format", "json",
         "--disable-rule", "custom/dual-thing", str(descriptor_set)],
    )
    payload = json.loads(result.stdout)

    # FLAW (assertion 1): zero findings because extension is unresolved,
    # not because disable worked. A regression that left
    # custom/dual-thing__field un-suppressed would still produce zero
    # findings (FIELD closure also hits KeyError on unresolved extension).
    custom_findings = [f for f in payload["findings"]
                       if f["rule_id"].startswith("custom/")]
    assert custom_findings == []

    # FLAW (assertion 2): unknown_rule_id can never fire — custom/dual-thing
    # IS in _loaded_specs (first-kind closure). This warning is only emitted
    # for rule_ids not found in _loaded_specs.
    unknown_for_bare = [w for w in payload["runtime_warnings"]
                        if w["category"] == "unknown_rule_id"
                        and w.get("rule_id") == "custom/dual-thing"]
    assert unknown_for_bare == []
```

Both assertions pass whether the disable mechanism is correct or completely broken.

### After — two-part fix

**Part 1: unit-level contract assertion (mechanism-layer, no extension needed)**

```python
def test_multi_kind_custom_prefix_expansion_via_cli_no_duplication(self, tmp_path):
    """
    Case 5: bare-prefix --disable-rule custom/<X> suppresses ALL materialized kinds.

    Two-part verification:

    Part 1 — unit-level prefix-expansion pin via ResolvedLintConfig.from_dict.
    Part 2 — CLI baseline-vs-disable comparison using a real registered extension.
    """
    # Part 1 — direct mechanism-contract assertion.
    from protokit.schema.lint._config import ResolvedLintConfig

    resolved = ResolvedLintConfig.from_dict(
        {
            "custom_annotation_rules": [{
                "rule_suffix": "dual-thing",
                "option": "example.dual_thing",
                "element_kinds": ["method", "field"],
                "severity": "warning",
            }],
            "disabled_rules": ["custom/dual-thing"],
        },
        {},
    )
    # Proves expansion at the config layer — no extension resolution required.
    # This assertion is structurally independent of the CLI / engine layer.
    assert "custom/dual-thing" in resolved.disabled_rules
    assert "custom/dual-thing__field" in resolved.disabled_rules  # mangled form
```

**Part 2: CLI baseline-vs-disable comparison with a real extension**

```python
    # Part 2 — Real extension declared on MethodOptions only.
    # METHOD closure: resolves and fires (annotation absent → finding).
    # FIELD closure:  HasExtension raises KeyError (wrong extendee)
    #                 → rule_exception warning with rule_id="custom/dual-thing__field".
    # BOTH observables are in the disable's blast radius — both drop to zero
    # when bare-prefix expansion correctly suppresses both rule_ids.
    ext_proto = textwrap.dedent("""\
        syntax = "proto2";
        package example;
        import "google/protobuf/descriptor.proto";
        extend google.protobuf.MethodOptions {
          optional string dual_thing = 50001;
        }
        """)
    svc_proto = textwrap.dedent("""\
        syntax = "proto3";
        package r14b.dual;
        message Carrier { string id = 1; }
        service Carriers {
          rpc Get(Carrier) returns (Carrier);
        }
        """)
    descriptor_set = compile_sources_to_descriptor_set(
        tmp_path,
        {"example/dual_thing.proto": ext_proto,
         "r14b/dual/carrier.proto": svc_proto},
        out_filename="r14b_case5.descriptor_set",
    )
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(DUAL_THING_CONFIG_TOML)

    # Baseline: NO --disable-rule. BOTH observables must fire.
    baseline = CliRunner().invoke(
        lint_main,
        [f"--config={pyproject}", "--format", "json", str(descriptor_set)],
        catch_exceptions=False,
    )
    baseline_payload = json.loads(baseline.stdout)
    baseline_method_findings = [
        f for f in baseline_payload["findings"]
        if f["rule_id"] == "custom/dual-thing"
    ]
    baseline_field_rule_exceptions = [
        w for w in baseline_payload["runtime_warnings"]
        if w["category"] == "rule_exception"
        and w["rule_id"] == "custom/dual-thing__field"
    ]
    # Independence check: confirm each signal fires before applying the
    # mechanism. Without these baseline pins, the post-disable assertions
    # below would be vacuous (Case 5's original flaw).
    assert len(baseline_method_findings) >= 1, (
        "baseline must fire at least one custom/dual-thing finding; without "
        "this signal the disable assertion below is vacuous"
    )
    assert len(baseline_field_rule_exceptions) >= 1, (
        "baseline must fire at least one rule_exception for "
        "custom/dual-thing__field; without this signal the disable "
        "assertion below is vacuous"
    )

    # Disable: --disable-rule custom/dual-thing (bare). BOTH must drop to zero.
    result = CliRunner().invoke(
        lint_main,
        [f"--config={pyproject}", "--format", "json",
         "--disable-rule", "custom/dual-thing", str(descriptor_set)],
        catch_exceptions=False,
    )
    payload = json.loads(result.stdout)
    surviving_custom_findings = [
        f for f in payload["findings"]
        if f["rule_id"].startswith("custom/")
    ]
    surviving_custom_warnings = [
        w for w in payload["runtime_warnings"]
        if w["category"] == "rule_exception"
        and (w["rule_id"] or "").startswith("custom/")
    ]
    assert surviving_custom_findings == []
    assert surviving_custom_warnings == []
```

The key invariant: the baseline assertions are structurally independent of the disable mechanism. If only one rule_id were suppressed by the disable, the baseline-vs-disable comparison would fail loudly for the unsuppressed form. The original design had no such invariant — it could not fail regardless of mechanism state.

## Related

- [[multi-element-fixture-list-disable-coverage-all-kinds-2026-05-25]] — sibling discipline at the FIXTURE-coverage layer (same day, same module). That learning ensures the fixture exercises all N targets a multi-rule suppression should affect; THIS learning ensures the OBSERVABLE chosen for the assertion is structurally capable of failing. The two checks are complementary — apply both for multi-rule suppression tests.
- [[capture-setup-without-dispatch-false-test-confidence-2026-05-17]] — closest mechanism-level sibling. In that learning, the mechanism never fires at all (dispatch never triggers, monkeypatch capture never fills). In THIS learning, the mechanism fires but absorbs the proxy signal (dispatch triggers, suppression works, but the proxy was already absent for a different reason). Both are members of the silent-test-confidence family. Introduces the "deletion test" — would the test fail if you deleted the implementation under test? — as the canonical audit.
- [[fixture-precondition-assertion-surfaces-silent-test-2026-05-17]] — fifth member of the silent-test-confidence family; its "silent-vacuous test via silent compile failure" is the same symptom class from a different layer. This new learning registers as a sixth member of the family.
- post-ship-adoption-monitoring-pre-1.0-breaking-default-change-2026-05-19 — generalized form of "null proxy is no proxy" at the post-ship monitoring layer. The "Sibling discipline: absence-of-error false-confidence" section explicitly names the essentials-alias zero-rules pattern; this learning is the test-layer specific instance.
- [[subprocess-exit-code-validation-test-harness-2026-05-13]] — third member of the silent-test-confidence family (exit code not checked → empty stdout treated as "no findings"). Same vacuous-assertion symptom, different mechanism.
- [[ce-review-convergence-rescues-sub-threshold-findings-diverse-personas-2026-05-17]] — the structural reason this learning's defect was caught before commit. Three reviewers at 0.82 / 0.90 / 0.65 individually; cross-reviewer convergence boosted the merged confidence well above the gate. Boost mode pays off for false-confidence findings specifically because no single reviewer typically has 0.95+ certainty on a vacuous-assertion claim.
