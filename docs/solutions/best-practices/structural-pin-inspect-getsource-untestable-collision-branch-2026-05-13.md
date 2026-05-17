---
title: "Pin merge-order invariants via inspect.getsource when no fixture can construct the collision target"
date: 2026-05-13
last_updated: 2026-05-14
category: docs/solutions/best-practices
module: tests/schema/lint/cli
problem_type: best_practice
component: testing_framework
severity: medium
applies_when:
  - "An integration test cannot construct the failure case because no upstream fixture provides the required collision target state (e.g., no profile in BUILTIN_PACKS declares the field whose precedence is being tested)"
  - "The behavioral invariant is an evaluation-order claim — Python dict-spread right-wins-on-collision, argument order, sort stability, mergedict layering, or similar"
  - "The implementation has a single canonical location for the ordering decision (a function or method body) that can be inspected at runtime"
  - "The consequence of invariant violation is silent incorrect behavior — no exception, no obvious symptom at the integration layer, no observable difference in the test output"
  - "CI runs formatters or linters that would catch unexpected source reformatting, so the test's fragility cost is bounded"
tags:
  - testing
  - inspect-getsource
  - structural-pin
  - dict-spread
  - user-wins
  - collision-semantics
  - untestable-branch
  - integration-test
  - regression-class
---

# Pin merge-order invariants via inspect.getsource when no fixture can construct the collision target

## Context

D6a Unit 9 R9a wires user severity overrides on top of the
composed profile's existing ``rule_severity_overrides``:

```python
composed_profile = dataclasses.replace(
    composed_profile,
    rule_severity_overrides={
        **composed_profile.rule_severity_overrides,
        **resolved.severities,
    },
)
```

Python's dict-spread semantics put the right-hand operand last,
so on key collision the user-supplied value wins. The plan
(KTD-2) explicitly required this ordering: user severities must
override engine-supplied defaults.

The U9 ce:review (testing reviewer, P1, 0.97 confidence)
surfaced a gap: no integration test exercises the collision
branch. BUILTIN_PACKS' profiles don't declare any
``rule_severity_overrides`` entries — every profile this can
compose against has an empty dict on the left of the spread.
Constructing a real collision case at the integration layer
requires a user-pack fixture with an overrides-bearing profile,
which doesn't exist at U9 (deferred as a D6b enhancement).

The behavioral invariant the plan claims (user wins on
collision) is therefore unverifiable by constructing inputs and
observing outputs at the integration layer. A future contributor
reversing the spread order to ``{**resolved.severities,
**composed_profile.rule_severity_overrides}`` would silently
flip the precedence — every existing test would still pass
(because no test triggers the collision), and the docs would
silently lie.

The fix used ``inspect.getsource`` + exact-substring match to
pin the structural invariant directly in source code. The
substring encodes the spread order; reversing the source flips
the substring and fails the test with a message that points the
contributor at the exact behavior being protected.

## Guidance

**When an integration test cannot construct the failure case
(no upstream fixture provides the collision target), pin the
structural invariant via ``inspect.getsource`` + exact-substring
match. The test is fragile to source reformatting — acceptable
cost; it catches the actual regression class (precedence
reversal) the docs claim to enforce. The test's failure
message must explicitly tell future contributors to update the
substring rather than delete the test.**

Sub-rules:

1. **Match the multi-line substring as a single Python string
   literal**, not as separate ``assert "a" in source and "b" in
   source`` checks. The single-substring form catches reordering
   (which preserves both substrings individually but breaks the
   adjacency); the split form does not.
2. **Include surrounding whitespace exactly** as it appears in
   the source. A reformatter (``black``, ``ruff format``)
   running on the source AFTER this test was written can shift
   indentation, but the test's failure message tells the
   contributor "update the substring" — preserving the
   invariant.
3. **Write the failure message to name the invariant and the
   remediation path.** The message must:
   (a) Identify what the substring is encoding (e.g., "user-
   wins dict-spread order: composed first, user second").
   (b) Tell the contributor the action when source has been
   reformatted ("update this test to track the new shape").
   (c) Explicitly forbid the easy escape ("DO NOT just remove
   the test").
4. **Co-locate the test with the behavioral tests for the same
   feature.** A future contributor adding a real fixture
   exercising the collision case should find both the structural-
   pin test and the (eventually-written) behavioral test
   together. The structural-pin can then be retired.
5. **Add a D6b-style backlog entry naming the path forward** —
   when a user-pack fixture with an overrides-bearing profile
   becomes available, the structural-pin test should be
   replaced by a real behavioral test. The pin is interim
   coverage, not a permanent shape.

## Why This Matters / Why This Works

**Behavioral tests are the gold standard; structural pins are
the fallback when behavior can't be observed.** The collision
branch ``{**a, **b}`` vs ``{**b, **a}`` produces identical output
for every input where ``a.keys() ∩ b.keys() == ∅``. No
integration test that doesn't construct a collision can
distinguish the two orderings. Without a fixture that creates
the collision, the only place the invariant is observable is in
the source code itself.

**The substring approach is direct, not magical.** It reads the
source file at test time, finds the canonical ordering
expression, and asserts its presence. A future contributor
flipping the spread order to ``{**resolved.severities,
**composed_profile.rule_severity_overrides}`` literally cannot
preserve the substring without preserving the order. The test
fails loudly with the message that points at the docs-claimed
behavior.

**The fragility is bounded.** ``black`` and ``ruff format``
shifts (whitespace, line breaks) are caught at CI; a
contributor running formatter changes sees the structural-pin
test fail and updates the substring to track the new shape.
The cost is ~2 minutes per format change; the benefit is
catching every reordering bug forever.

**The pattern is not a substitute for behavior tests when
behavior is testable.** If a user-pack fixture with an overrides-
bearing profile WERE available, the right test would be:

```python
def test_user_severities_win_over_composed_overrides(
    self, ..., overrides_bearing_pack_fixture: Path,
) -> None:
    # Real fixture provides composed = {"x/y": LintSeverity.ERROR}
    # User provides severities = {"x/y": "info"}
    # Run protokit; assert the composed report's effective
    # severity for x/y is INFO.
```

Behavior tests survive refactoring. The structural pin is
interim coverage when no such fixture exists.

**The "untestable collision branch" pattern recurs.** Any time
a feature's plan claims an evaluation-order invariant
(dict-spread, argument resolution, sort stability, function-
default-vs-explicit-arg, mergedict layering, attribute
override) and no available fixture can construct the
collision input, this technique applies.

## When to Apply

Apply when ALL of the following are true:

1. The invariant is a structural / ordering property in source
   — not a value property observable via output.
2. An integration test cannot currently construct the failure
   case (e.g., the upstream fixture data that would trigger the
   collision path is not available in the current test suite).
3. The invariant is explicitly required by the plan or spec
   — i.e., it is not just an implementation detail but a
   documented contract.
4. A future contributor reversing the ordering would get no
   other signal — no exception, no other test failure, no
   visible behavioral change.

The inverse — when NOT to apply:

- **A fixture can be added cheaply** that exercises the
  collision case. Write the behavior test instead; that
  survives refactoring.
- **The ordering is not a documented contract** — e.g., it
  happens to work because of a current implementation choice
  but the spec is silent. Don't pin internal details that
  aren't part of the contract.
- **The source location is volatile** — if the canonical
  ordering decision moves between modules every few releases,
  the pin will need updating in every move. Prefer a
  behavior test or accept the gap.

## Examples

### The test (anchor — U9 R9a F1 follow-up)

``tests/schema/lint/cli/test_r9a_severities_overlay.py:160–213``:

```python
def test_user_severities_win_over_composed_overrides(
    self,
    tmp_path: Path,
    bad_naming_descriptor_set: Path,
) -> None:
    """User severities table wins on collision with a composed
    profile's existing ``rule_severity_overrides`` entry.

    The user-wins semantics are enforced by Python's right-wins-
    on-collision dict-spread behavior in the cli.py overlay.
    BUILTIN_PACKS profiles don't declare rule_severity_overrides,
    so we cannot construct a real collision at the integration
    layer in U9. Per ce:review F1 finding on commit c7a426b. (The
    ideal test would construct a multi-pack composition where
    pack A declares rule_severity_overrides; that requires a
    user-pack fixture with an overrides-bearing profile,
    deferred as a D6b enhancement.)
    """
    import inspect
    from protokit.schema.lint import cli as lint_cli_module

    source = inspect.getsource(lint_cli_module)
    assert (
        "**composed_profile.rule_severity_overrides,\n"
        "                **resolved.severities,"
    ) in source, (
        "expected user-wins dict spread order (composed first, "
        "user second) in cli.py severities overlay; collision "
        "semantics rely on Python's right-wins-on-collision behavior. "
        "If the source has been reformatted, update this test to "
        "track the new shape — DO NOT just remove the test."
    )
```

### The source under test (the invariant being pinned)

``src/protokit/schema/lint/cli.py:869–875``:

```python
if resolved.severities:
    composed_profile = dataclasses.replace(
        composed_profile,
        rule_severity_overrides={
            **composed_profile.rule_severity_overrides,
            **resolved.severities,
        },
    )
```

### What a regression looks like (what the test catches)

A future contributor reorders the spread thinking the order
doesn't matter:

```python
# REGRESSION — user values are now overwritten by composed defaults
rule_severity_overrides={
    **resolved.severities,
    **composed_profile.rule_severity_overrides,
},
```

The substring
``"**composed_profile.rule_severity_overrides,\n                **resolved.severities,"``
no longer appears in source. The test fails with:

```
AssertionError: expected user-wins dict spread order (composed first,
user second) in cli.py severities overlay; collision semantics rely
on Python's right-wins-on-collision behavior. If the source has
been reformatted, update this test to track the new shape —
DO NOT just remove the test.
```

The contributor reads the message, sees that the docs claim
"user wins", and either reverts the reorder or (if they
actually intended to change the contract) updates the docs,
the substring, AND the plan.

### Replacement path (when a user-pack fixture becomes available)

A D6b user-pack fixture might look like:

```python
@pytest.fixture
def pack_with_severity_override(tmp_path: Path) -> Path:
    """A user pack whose profile pre-declares a rule_severity_override
    for a specific rule_id, enabling collision tests at the
    integration layer."""
    pack_dir = tmp_path / "user_pack_overrides"
    ...
    # Profile YAML:
    #   rules: [naming/snake-case-fields]
    #   rule_severity_overrides:
    #     naming/snake-case-fields: error
    return pack_dir
```

With that fixture, the structural-pin test can be retired in
favor of:

```python
def test_user_severities_win_over_pack_overrides(
    self, pack_with_severity_override: Path,
) -> None:
    # Pack declares: naming/snake-case-fields → ERROR
    # User overrides:  naming/snake-case-fields → INFO
    # Composed result should be INFO (user wins).
    pyproject = """
    [tool.protokit.lint]
    rule_packs = ["./user_pack_overrides"]

    [tool.protokit.lint.severities]
    "naming/snake-case-fields" = "info"
    """
    result = run_lint_with_pyproject(pyproject)
    # Find a finding for the rule; assert severity is "info" not "error"
    finding = next(
        f for f in result["findings"]
        if f["rule_id"] == "naming/snake-case-fields"
    )
    assert finding["severity"] == "info"
```

Behavior survives refactoring; the structural pin can be removed.

## Related

- [[cross-file-pin-regex-anchor-structure-not-annotation-token-2026-05-13]] —
  sibling pattern at a different layer. That learning uses a
  regex anchor structured around the load-bearing tokens (not
  the annotation noise around them) to pin a multi-site agreement
  across ``cli.py`` and ``ci.yml``. This learning uses
  ``inspect.getsource`` to pin a structural ordering invariant
  within a single source file. Both patterns share the
  underlying philosophy: **when the property you need to
  protect is structural rather than behavioral, pin the
  structure directly; don't simulate behavior you cannot
  produce.**
- [[mock-patch-c-extension-method-descriptor-2026-05-06]] —
  adjacent "when a fixture can't construct the collision
  target" testing problem. That learning uses class-accessor
  patching to bypass a C-extension limitation that prevents
  normal mocking. This learning uses ``inspect.getsource`` to
  pin merge-order when no runtime fixture can construct two
  source-distinct-but-value-equal dicts. Both are workarounds
  for the same structural test gap: the observable behavior is
  identical across branches, so the test must verify
  implementation structure directly.
- [[parametrized-matrix-tests-inherit-schema-validators-2026-05-12]] —
  complementary test-discipline pattern. That learning ensures
  test coverage scales across format combinations; this
  learning ensures test coverage survives evaluation-order
  invariants that fixtures can't exercise.
- [[shared-error-helper-source-label-caller-attribution-2026-05-11]] —
  a different "test must verify source structure" pattern,
  applied to shared error helpers. Source-structure tests are
  a small family in this codebase; this learning adds the
  inspect.getsource variant.
- [[capture-setup-without-dispatch-false-test-confidence-2026-05-17]] —
  third member of the "untestable branch" family. This learning
  uses inspect.getsource when no fixture can trigger the branch;
  the capture-setup learning uses _make_capture_pack to LOAD a
  rule that triggers the dispatch path so a previously-untestable
  branch becomes observable. Both address the same gap (test
  silently passes while the relevant code path is never exercised)
  from opposite ends: structural pinning when behavior is
  unreachable, vs. wiring infrastructure so behavior fires.
- [[presence-ratchet-test-pattern-for-prose-substrings]] —
  sibling ratchet pattern at the prose layer: this learning
  pins evaluation-order shape that fixtures can't exercise;
  the presence-ratchet pins prose substrings that static
  analysis can't read. Both are ratchets against silent
  regression; choose the structural pin when the source shape
  IS the contract, choose the presence ratchet when a
  substring's meaning IS the contract and surrounding shape
  is free to evolve.
- Anchor commit: ``3c828a4`` (Unit 9 ce:review follow-up F1
  — testing reviewer surfaced the collision-branch gap;
  ``inspect.getsource`` test added as the structural pin).
- Plan: ``docs/plans/2026-05-12-001-feat-protokit-lint-d6a-rule-library-plan.md``
  Unit 9 R9a / KTD-2.
- 11-reviewer ce:review at ``.context/compound-engineering/
  ce-review/20260513-113000-u9/`` — testing reviewer surfaced
  the F1 P1 finding (0.97 confidence).
