---
title: "Test capture infrastructure without dispatch is false confidence — monkeypatch + capture list that never fires hides the impl under test"
date: 2026-05-17
category: docs/solutions/best-practices
module: protokit-lint
problem_type: best_practice
component: testing_framework
severity: medium
applies_when:
  - "A test sets up a monkeypatch or capture list to observe a callback, hook, or method invoked by a dispatch walk"
  - "The dispatch walk is triggered only when at least one rule of a specific ElementKind / handler kind is registered"
  - "The test loads zero rules of the triggering kind, so the dispatch walk never runs and the capture list stays empty"
  - "The test's assertions fall through to fields on the result object that are already covered by other test modules"
  - "Deleting the implementation under test would not cause the test to fail (the deletion test)"
related_components:
  - development_workflow
tags:
  - testing
  - false-confidence
  - capture-mechanism
  - dispatch
  - visitor-pattern
  - monkeypatch
  - test-author-trap
  - protokit-lint
  - deletion-test
---

# Test capture infrastructure without dispatch is false confidence

## Context

When a test sets up capture infrastructure — a monkeypatch replacing an internal method with a recording callable, plus an empty list the callable appends to — but loads no rules that trigger the dispatch walk invoking that method, the capture list is always empty. The test has no assertion on the capture, so it falls back to asserting on adjacent fields of the result object (e.g., `result.pool_file_names`). The implementation under test is never observed. Deleting the implementation leaves all tests passing.

D6b U4a's ce:review surfaced this exact pattern (5-way convergence: Testing T-1, T-2, Maintainability M1, kieran-python F5, Adversarial ADV-U4a-003). The original `TestAccumulatorConstruction` class in `tests/schema/lint/test_engine_pre_walk.py` set up `engine._build_file_ctx = _capture` monkeypatches for two tests, but both tests loaded zero FILE-element rules. The engine's Step 4 dispatch walk for FILE elements is only entered when at least one FILE-element rule is registered; with no such rules, `_build_file_ctx` was never called, `captured` was always `[]`, and both tests silently fell back to asserting on `result.pool_file_names` — a `CompileResult` field already covered by `tests/schema/lint/test_compile_pool_file_names.py`. The accumulator code (`_build_package_options_accumulator`, ~90 lines) was entirely unobserved.

## Guidance

**The deletion test.** Before committing a test that uses capture infrastructure, ask yourself: *"If I deleted the implementation under test, would this test fail?"* If the answer is no, the test has false confidence. This 10-second mental check catches the entire pattern at authoring time.

**Load a rule of the triggering kind via a synthetic capture pack.** For the lint engine, the dispatch walk that invokes `_build_file_ctx` only runs when a FILE-element rule is registered. Use a helper that builds a synthetic module exposing exactly one `@lint_rule`-decorated callable:

```python
import types
from typing import Any
from protokit.schema.lint.decorator import lint_rule
from protokit.schema.lint.model import ElementKind, FileLintContext, LintSeverity


def _make_capture_pack(
    profile_name: str, rule_id: str, captured: list[Any],
) -> Any:
    """Build a synthetic FILE-element rule pack module.

    Engine ``load_rule_pack(module)`` consumes ``module.RULES`` (tuple of
    @lint_rule-decorated callables) and ``module.__name__`` for idempotency.
    SimpleNamespace gives us both without polluting the global module registry.
    """
    @lint_rule(
        rule_id=rule_id,
        severity=LintSeverity.INFO,
        profiles=(profile_name,),
        element=ElementKind.FILE,
        message_template="captured",
        source_spec="",
    )
    def _capture(ctx: FileLintContext) -> None:
        captured.append(ctx.package_options)

    module = types.SimpleNamespace()
    module.__name__ = f"_test_capture_{rule_id.replace('/', '_')}"
    module.RULES = (_capture,)
    return module
```

`engine.load_rule_pack(pack)` registers the rule; the dispatch walk now enters the FILE-element branch, calls `_build_file_ctx`, and the capture fires.

**`SimpleNamespace` vs `ModuleType`:** `load_rule_pack` duck-types on `module.__name__` + `module.RULES`, so either works at runtime. `types.SimpleNamespace` is shorter (one positional arg, two attribute assignments) and reads cleanly in test code where tests aren't in the mypy-strict gate. Production code where the helper sits in a strict-typed path should prefer `types.ModuleType(name)` — it's typed as `ModuleType` (matching `load_rule_pack`'s parameter type) and sets `__name__` via the constructor. The teaching pattern uses `SimpleNamespace` because that's what `tests/schema/lint/test_engine_pre_walk.py` ships with.

**Assert on the captured value, not on result fields.** After `engine.run(...)`, the assertion must be on `captured`, not on `result.pool_file_names` or any other `CompileResult` field covered elsewhere:

```python
assert len(captured) >= 1, "FILE-element capture rule should have fired at least once"
pkg_options = captured[0]
assert pkg_options is not None  # else accumulator returned None
per_attr = pkg_options["u4a.transitive"]["go_package"]
assert set(per_attr.keys()) >= {"a.proto", "b.proto", "c.proto"}
```

This assertion fails if `_build_package_options_accumulator` is deleted, because `pkg_options` would be `None` (the engine sets `ctx.package_options = None` when the accumulator early-returns or is absent).

**One capture list per test.** Each test should create an independent `captured: list[...] = []` and a fresh pack with a unique `rule_id` via `_make_capture_pack`. This prevents cross-test contamination through shared engine-instance registration state and ensures `load_rule_pack`'s idempotency check (keyed on `module.__name__`) doesn't accidentally reject a second registration.

**Construct a fixture where the captured value would discriminate the regression you care about.** It's not enough that the capture fires — the assertion must distinguish "implementation correct" from "implementation buggy in the way I'm testing for." If you're testing the "pre-walk iterates `pool_file_names`, not `root_files`" invariant, the fixture must have `pool_file_names ⊋ root_files` (e.g., via a transitive import). Otherwise even a correctly-firing capture sees identical content under both implementations.

## Why This Matters

A test with capture infrastructure that never fires provides exactly zero marginal coverage of the implementation it purports to test. Worse, it actively masks the gap: the test name claims accumulator coverage; the test status is green; the coverage tool reports lines executed (the test body ran top-to-bottom). Only the deletion test reveals the truth.

The cost of the silent gap is realized when a regression is introduced. In D6b U4a's case, a broken `_build_package_options_accumulator` would produce `None` or an incomplete mapping; every R7 rule (landing in U4b) would receive `ctx.package_options = None` and either silently skip (if it guards the `None` case) or raise `TypeError` on the first production use. The unit test suite would not catch this until a rule-consumer integration test was written — which is exactly the behavior the unit test was supposed to provide.

The structural risk compounds when the implementation under test has no other test consumers. `_build_package_options_accumulator` is a 90-line method with 7 option attributes, 3-level mapping construction, `MappingProxyType` wrapping, `posixpath` sort key, lazy import, and a widened exception guard. All of that logic was unobserved by the original two tests. A regression in any of the attribute paths, the 3-level wrap, or the dedup logic would have been invisible until the U4b R7 rule consumers landed.

The pattern is especially seductive because the test "looks like" it's testing the right thing: the monkeypatch is correctly installed, the capture list is the correct shape, the rule pack architecture is understood. The author had every component except the one that matters — actually triggering the dispatch.

## When to Apply

Apply this check whenever a test:

1. Creates a capture list (`captured = []`) and a recording callable.
2. Installs the callable via monkeypatch, hook registration, or constructor injection.
3. Runs the engine, dispatcher, or visitor.
4. Asserts on `captured` OR falls through to assertions on other result fields.

Step 4 is the tell:
- If the test has **no** assertion on `captured`, the capture was vestigial from the start. Either delete it or wire it into the assertion path.
- If the test has an assertion on `captured` but `captured` is always empty AND the test still passes, dispatch is not being triggered. Either load a rule of the triggering kind via `_make_capture_pack`, or rewrite the test to assert on a different observable.

Apply `_make_capture_pack` (or the equivalent helper for the relevant ElementKind / handler kind) whenever:
- The implementation under test is called from within a dispatch walk.
- The dispatch walk is conditional on at least one registered rule/hook/handler of the relevant kind.
- The test does not already load such a rule through `BUILTIN_PACKS` or another fixture.

## Examples

### Before — capture infrastructure that never fires

```python
class TestAccumulatorConstruction:
    def test_accumulator_built_from_pool_file_names_not_root_files(
        self, tmp_path, monkeypatch,
    ):
        proto_dir = _write_three_files(tmp_path)
        a_only = compile_protos_to_result([proto_dir / "a.proto"], ...)

        # Capture set up correctly...
        captured = []
        def _capture(compile_result, file_descriptor, *, package_options):
            captured.append(package_options)
        monkeypatch.setattr(engine, "_build_file_ctx", _capture)

        # ...but no FILE-element rules loaded. Dispatch walk for FILE
        # elements never runs. _build_file_ctx is never called.
        result = engine.run(a_only, profile=LintProfile(..., rule_ids=frozenset()))

        # Falls back to asserting on CompileResult fields,
        # already covered by test_compile_pool_file_names.py.
        assert "a.proto" in result.pool_file_names
        assert "b.proto" in result.pool_file_names
        # DELETION TEST: delete _build_package_options_accumulator
        # → result.pool_file_names unaffected → test STILL PASSES.
        # → False confidence.
        # (no other tests in this class — class body ends here)
```

### After — capture infrastructure wired to dispatch via `_make_capture_pack`

```python
class TestAccumulatorConstruction:
    def test_accumulator_built_from_pool_file_names_not_root_files(
        self, tmp_path,
    ):
        # Fixture: a.proto imports b.proto + c.proto (cross-package types).
        # Critical for this test: pool_file_names ⊋ root_files, so the
        # invariant "pre-walk iterates pool, not roots" is discriminating.
        proto_dir = _write_transitive_fixture(tmp_path)
        a_only = compile_protos_to_result(
            [proto_dir / "a.proto"],
            proto_paths=(str(proto_dir),),
        )
        assert a_only.root_files == ("a.proto",)
        assert set(a_only.pool_file_names) >= {"a.proto", "b.proto", "c.proto"}

        # Register a real FILE-element rule so dispatch enters the FILE
        # branch → _build_file_ctx → _build_package_options_accumulator.
        captured: list[Any] = []
        rule_id = "u4a-followup/capture-superset"
        pack = _make_capture_pack(
            "u4a-followup-capture-superset", rule_id, captured,
        )

        engine = LintEngine()
        engine.load_rule_pack(pack)
        engine.run(
            a_only,
            profile=LintProfile(
                name="default",
                rule_ids=frozenset({rule_id}),
                min_severity=LintSeverity.INFO,
            ),
        )

        # Capture actually fired — assert on the accumulator's content.
        assert len(captured) >= 1, (
            "FILE-element capture rule should have fired at least once"
        )
        pkg_options = captured[0]
        assert pkg_options is not None
        per_attr = pkg_options["u4a.transitive"]["go_package"]
        keys = set(per_attr.keys())
        assert keys >= {"a.proto", "b.proto", "c.proto"}, (
            f"pre-walk must iterate pool_file_names (roots + transitive); "
            f"got {keys}. Regression: pre-walk iterating root_files only → "
            f"only 'a.proto' appears."
        )
        # DELETION TEST: delete _build_package_options_accumulator
        # → pkg_options is None → assertion at line above fails. ✓
```

### Closest prior instance (session history)

A milder cousin of this pattern was caught in D6b U3's ce:review (commit `8496b88`): the `test_control_chars_sanitized` test had a vacuous conditional assertion — the assertion only executed if a certain condition held, so the test passed vacuously when the condition was false. Caught by 2-way convergence (testing + kieran-python), fixed by making the assertion unconditional and adding U+2028 / U+2029 / U+0085 inputs. The D6b U4a `TestAccumulatorConstruction` case is the same family but more severe: the assertion path runs unconditionally, just on the wrong observable.

## Related

- ce-review-convergence-rescues-sub-threshold-findings-2026-05-17 — companion learning from the same D6b U4a review pass. The 5-way convergence on this false-confidence pattern (Testing T-1 + T-2 + Maintainability M1 + kieran-python F5 + Adversarial ADV-003) was itself an instance of the convergence rescue mechanism: kieran-python F5's 0.65 standalone confidence wouldn't have triggered triage independently, but combined with 0.92, 0.90, 0.88, and 0.95 from other reviewers, it landed as a manual P1 fix.
- [[matcher-backend-path-resolution-skew-silently-empties-output-2026-05-02]] — third member of the "silent-green" family. Different mechanism (path resolution skew empties `root_files`), same symptom class (test passes when the pipeline never produced real output).
- [[subprocess-exit-code-validation-test-harness-2026-05-13]] — fourth member of the "silent-green" family. Different mechanism (exit code not checked; empty stdout treated as success), same symptom class. Prevention rule 7 in that doc ("add a sanity test that invokes the tool with known-bad input and asserts the wrapper raises") is the structural analog to this learning's deletion test.
- [[mock-patch-c-extension-method-descriptor-2026-05-06]] — same file surface (`lint/_cli_utils.py`), same meta-pattern: setup completes silently (the C-extension `pool.Add` rejects the patch silently; in this learning, the dispatch walk skips silently). Prevention Rule 4 there ("assert that the patch actually replaced the target") is the conceptual sibling to this learning's "assert capture fired" rule.
- [[structural-pin-inspect-getsource-untestable-collision-branch-2026-05-13]] — third member of the "untestable branch" family. When no fixture can construct the trigger condition, pin the invariant via `inspect.getsource`; when a fixture CAN trigger dispatch, load a real rule and assert on the captured value (this learning's path).
- [[fixture-precondition-assertion-surfaces-silent-test-2026-05-17]] — fifth member of the silent-test-confidence family. Different mechanism: a fixture-builder precondition assertion (installed primarily to catch authoring foot-guns) PASSIVELY surfaced a pre-existing silent-vacuous test as a side-effect. This learning's discovery mechanism is ACTIVE (deliberate deletion test or dispatch-trigger check); that learning's is PASSIVE (precondition assertion that fires when an existing test happens to pass an invalid value).
