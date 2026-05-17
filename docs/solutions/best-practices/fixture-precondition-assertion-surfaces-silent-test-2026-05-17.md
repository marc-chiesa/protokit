---
title: "Fixture-builder precondition assertion surfaces latent silent-vacuous tests: a side-effect of catching authoring foot-guns is exposing tests that were green for the wrong reason"
date: 2026-05-17
category: docs/solutions/best-practices
module: tests/schema/lint/rules/fixtures
problem_type: best_practice
component: testing_framework
severity: medium
applies_when:
  - "A programmatic fixture builder accepts caller-supplied string values that flow into an external tool (protoc, buf, a SQL parser, etc.)"
  - "The downstream tool can fail silently on certain malformed inputs (exit 0 + empty output rather than an error code)"
  - "The test's baseline assertion is 'zero findings' or 'no errors' — assertions that pass vacuously when the tool produces no output at all"
  - "The fixture builder has no validation of caller-supplied values against the downstream tool's input constraints"
related_components:
  - tooling
tags:
  - precondition-assertion
  - fixture-builder
  - silent-vacuous-test
  - proto-compile
  - escape-sequences
  - test-discovery
  - false-confidence
  - protokit-lint
---

# Fixture-builder precondition assertion surfaces latent silent-vacuous tests

## Context

When a fixture builder accepts caller-supplied values that may silently violate downstream system requirements (compiler preconditions, parser grammar constraints, wire-format assumptions), adding a precondition assertion at the builder level does double duty: it protects future fixture authors from the documented foot-gun (primary purpose), and as a side-effect, it exposes any existing tests that were passing only because the downstream system silently failed on invalid input (secondary discovery).

D6b U4b's ce:review adversarial reviewer flagged that `_option_line` in `tests/schema/lint/rules/fixtures/package_same/proto_templates.py` accepted backslash-containing string values without validation. A caller passing `"Acme\Sub"` as a PHP namespace value would produce proto source `option php_namespace = "Acme\Sub";` in which `\S` is not a valid proto3 escape sequence. protoxy/protoc rejects the file silently (compile returns 0 findings rather than a hard error in protoxy's lenient mode), and any "all-agree" or "no findings" assertion on the resulting report passes vacuously.

Applying the assertion `assert "\\" not in value` in `_option_line` (the primary fix per adversarial reviewer's recommendation) caused `test_php_namespace_happy_path` to fail loudly — the test had been written with `"Acme\\Sub"` (Python source = `Acme\Sub`) as the PHP namespace value. The compile silently failed every time the test ran; the 3-file all-agree assertion `assert len(report.findings) == 0` was satisfied vacuously because zero files were ever evaluated. The precondition assertion surfaced this latent bug as an explicit failure rather than as confusing future-refactor symptoms.

## Guidance

**Add precondition assertions to fixture builders that accept caller-controlled values flowing into a compiler or parser.** The primary purpose is documentation and protection for future fixture authors; the secondary purpose (exposing silent tests) is a free side-effect.

For the proto source builder case (`proto_templates.py:_option_line`, lines 89-97):

```python
def _option_line(attr: str, value: str | bool) -> str:
    if attr == BOOL_ATTR:
        assert isinstance(value, bool), (
            f"java_multiple_files requires bool, got {type(value).__name__}"
        )
        literal = "true" if value else "false"
    else:
        assert isinstance(value, str), (
            f"{attr} requires str, got {type(value).__name__}"
        )
        assert "\\" not in value, (
            f"{attr}: ``make_proto`` does not escape backslashes inside "
            f"option-literal bodies; got {value!r}. Use ASCII-only values "
            f"here OR construct the proto source manually with explicit "
            f"proto3 escapes (e.g. ``\\\\\\\\`` for a literal backslash)."
        )
        literal = f'"{value}"'
    return f"option {attr} = {literal};"
```

**When an existing test fails on a newly-added assertion, investigate why it was passing before.** Do NOT simply update the test value to satisfy the assertion — first understand whether the test was producing meaningful coverage. The correct remediation path:

1. Identify the value that triggered the assertion (`"Acme\Sub"` in the PHP namespace case).
2. Trace what happened when that value reached the downstream tool: did the compile fail silently? Did it return 0 findings?
3. **If compile failed silently** → the test was never exercising the rule. Diagnose what valid value achieves the same test semantics and update.
4. **If compile succeeded** but the assertion caught a legitimate bug in a value that was intended to be valid → the assertion is too strict; narrow it.

In D6b U4b, step 3 applied: `test_php_namespace_happy_path` was updated to use `"AcmeX"` (ASCII-only, matching the `_SAMPLE_STRING_VALUES["php_namespace"]` table that the mixed-value tests had already converged on for the same reason). The all-agree code path is now actually exercised; the test would catch a future regression in the PHP namespace rule.

**Document the precondition prominently in the builder's docstring.** The assertion error message is the first-line explanation for future authors who hit it. The module-level docstring should also name the precondition in the "cross-fixture invariants" section so it appears in IDE tooltips on every call site.

**This pattern is a PASSIVE search beam for silent-test bugs.** Unlike proactive deletion tests or dispatch-trigger checks (see [[capture-setup-without-dispatch-false-test-confidence-2026-05-17]]), the precondition assertion is installed for a PRIMARY reason (catch fixture-authoring foot-guns) and discovers silent tests as a SIDE EFFECT. The discovery is passive — it fires only when a test already happens to pass an invalid value — but it scales across all existing and future tests without requiring per-test audit.

## Why This Matters

The silent-test family is large and grows organically: each silent-test pattern has a different surface (matcher path resolution, subprocess exit code, dispatch trigger, compile failure). Fixture-precondition assertions add a NEW prevention strategy that operates at the fixture/test-infrastructure layer rather than at the assertion or harness layer. A fixture builder with comprehensive precondition checks forces every test author to confront the validity of their inputs at build time, not at assertion time — when the assertion failure is maximally informative ("this value is invalid for X reason, use Y instead") rather than at assertion time ("expected 3 findings, got 0" with no hint why).

The D6b U4b case illustrates the compounding effect: `test_php_namespace_happy_path` was part of the 7-rule × 3-shape coverage grid in `TestPerRuleHappyAndSadPaths`. Its silent passing meant the PHP namespace happy-path coverage was missing for the entire lifetime of the test class. A future refactor that broke the PHP namespace rule would not have been caught by this test — making it an ENABLER of latent regressions, not a guard against them. The precondition assertion surfaced the gap 2 delivery units before U7 (when the rule auto-loads for all users), providing maximum lead time to repair the test before any user-visible impact.

Fixture-precondition assertions are the FIFTH known prevention strategy in the silent-test-confidence family:

1. **Path resolution validation** — assert fixture filesystem state matches what the matcher expects ([[matcher-backend-path-resolution-skew-silently-empties-output-2026-05-02]]).
2. **Subprocess exit-code validation** — assert the subprocess actually succeeded before treating empty stdout as "no output" ([[subprocess-exit-code-validation-test-harness-2026-05-13]]).
3. **C-extension method-descriptor mock verification** — assert `unittest.mock.patch` actually replaced the target rather than silently no-op'd on a method-descriptor ([[mock-patch-c-extension-method-descriptor-2026-05-06]]).
4. **Capture-setup-with-dispatch verification** — assert the engine walk actually FIRED on the captured rule, not just registered it ([[capture-setup-without-dispatch-false-test-confidence-2026-05-17]]).
5. **Fixture-builder precondition assertion** (this learning) — assert caller-supplied values are valid for the downstream tool before the fixture is materialized.

## When to Apply

Apply fixture precondition assertions when:

1. The fixture builder accepts caller-controlled values that will be embedded in inputs to a compiler, parser, or external tool.
2. The compiler/parser can fail silently on invalid inputs (exit 0 + empty output rather than an error code).
3. The test's assertion is of the form "N findings expected" or "0 findings expected" — assertions that would pass vacuously if the tool never evaluated the input.
4. The fixture builder is used by 3+ test functions (single-use fixtures rarely justify the precondition; the assertion's value compounds across reuse).

The precondition assertion is NOT a substitute for checking that the compiler succeeded. Both are needed: the precondition catches foot-guns at builder invocation time; the compile-error check catches failures that the precondition doesn't cover (e.g., structurally invalid proto syntax that isn't a value-encoding issue). The R7 fixtures in `proto_templates.py` rely on the test harness's `_compile` helper to surface compile errors via `assert not error_diags` — the precondition assertion in `_option_line` is the LAYERED defense.

## Examples

**Silent test before precondition (D6b U4b, PHP namespace happy-path):**

```python
# Original test (passed for the wrong reason):
def test_php_namespace_happy_path(self, tmp_path: Path) -> None:
    self._check_happy_path(tmp_path, "php_namespace", "Acme\\Sub")
    # Python source ``"Acme\\Sub"`` = literal ``Acme\Sub``
    # make_proto generated: option php_namespace = "Acme\Sub";
    # protoxy: ``\S`` is invalid proto3 escape → silent compile failure
    # → 0 findings produced
    # → "all-agree" assertion (assert len == 0) PASSES VACUOUSLY
    # The test was GREEN. It covered NOTHING.
```

**After precondition assertion fires and test is fixed:**

```python
# _option_line now has:
assert "\\" not in value, (
    f"{attr}: ``make_proto`` does not escape backslashes inside "
    f"option-literal bodies; got {value!r}. ..."
)

# test_php_namespace_happy_path with "Acme\\Sub" → AssertionError loudly
# Investigation: compile fails silently on invalid \S escape
# Fix: use ASCII-only value matching the _SAMPLE_STRING_VALUES convention

def test_php_namespace_happy_path(self, tmp_path: Path) -> None:
    # ASCII-only value (no backslash separator) per the
    # _SAMPLE_STRING_VALUES comment — the fixture builder does NOT
    # escape backslashes inside option-literal bodies.
    self._check_happy_path(tmp_path, "php_namespace", "AcmeX")
    # Now ACTUALLY exercises the all-agree code path on a
    # correctly-compiled 3-file fixture.
```

**The precondition's error message is the documentation:**

When a future author hits the assertion, they get:

```
AssertionError: php_namespace: ``make_proto`` does not escape backslashes
inside option-literal bodies; got 'Acme\\Sub'. Use ASCII-only values here
OR construct the proto source manually with explicit proto3 escapes
(e.g. ``\\\\`` for a literal backslash).
```

This is more informative than a downstream "expected 3 findings, got 0" failure that doesn't reveal the root cause.

**Generalized template for fixture-builder precondition assertions:**

```python
def fixture_builder_helper(attr: str, value: <type>) -> <returnt>:
    # Type/shape preconditions (catch obvious mistakes early)
    assert isinstance(value, <expected_type>), (
        f"{attr} requires <expected_type>, got {type(value).__name__}"
    )
    # Semantic preconditions (catch values the downstream tool can't handle)
    # Each precondition's error message must direct the caller to the
    # correct alternative and cite the downstream constraint.
    assert <semantic_check>(value), (
        f"{attr}: <builder> does not handle <pattern>; got {value!r}. "
        f"Use <alternative_pattern> OR <escape_hatch>."
    )
    # ... proceed to use value ...
```

## Related

- [[capture-setup-without-dispatch-false-test-confidence-2026-05-17]] — fourth member of the silent-test-confidence family. Different surface: engine-dispatch trigger rather than compiler input validation. Both share the symptom class (test is green, implementation is unobserved). This learning's discovery mechanism is PASSIVE (precondition assertion installed for other reasons); that learning's discovery mechanism is ACTIVE (deletion test or dispatch-trigger check done deliberately).
- [[subprocess-exit-code-validation-test-harness-2026-05-13]] — third member of the family. Subprocess exit code not checked → empty stdout treated as success. Same symptom class, different detection strategy.
- [[matcher-backend-path-resolution-skew-silently-empties-output-2026-05-02]] — first member of the family. Path resolution skew empties `root_files`, test passes vacuously.
- [[mock-patch-c-extension-method-descriptor-2026-05-06]] — sibling family member. `unittest.mock.patch` silently no-ops on C-extension method-descriptors, same false-confidence symptom class.
- [[programmatic-proto-fixture-builder-multi-file-rule-family-2026-05-17]] — the fixture builder this learning emerged from. The "three sub-pitfalls" enumerated in that learning's Guidance section is the broader context for the precondition assertion described here.
- `tests/schema/lint/rules/fixtures/package_same/proto_templates.py:62-99` — the `_option_line` precondition assertion in its canonical form.
- D6b U4b ce:review run artifact: `.context/compound-engineering/ce-review/20260517-142846-d5fdc684/` — adversarial reviewer's ADV-2 finding (0.82 confidence) that prompted the precondition addition.
- Commit landing the precondition: `dd606e7`.
