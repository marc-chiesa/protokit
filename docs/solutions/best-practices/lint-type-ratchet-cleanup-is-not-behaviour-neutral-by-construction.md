---
title: "A lint/type ratchet cleanup is not behaviour-neutral by construction: SIM110's any(genexpr) and str()/bool() wraps added for mypy changed observable behaviour"
date: 2026-09-26
category: docs/solutions/best-practices
module: tooling/static-analysis
problem_type: best_practice
component: tooling
severity: medium
applies_when:
  - "Bringing existing modules under ruff or mypy --strict (widening _LINT_PATHS / _TYPE_CHECK_PATHS) with a promise of no behaviour change"
  - "Accepting a ruff autofix or suggested rewrite (SIM110, SIM111, UP-series) in code that calls user-supplied callables"
  - "Silencing mypy no-any-return or return-value errors by wrapping a value in str(), bool(), int() or list()"
  - "Reviewing a diff whose description says type-only or lint-only"
symptoms:
  - "A treat_as_set predicate that raised StopIteration surfaced to the caller as RuntimeError('generator raised StopIteration') after the SIM110 rewrite"
  - "A hook whose __qualname__ is a str subclass with its own __str__ was named differently in the VALIDATE diagnostic after _hook_name gained a str() wrap"
  - "Full suite green on both protobuf backends, three simplify reviewers and a full code review (five local reviewers, named in the body, plus a cross-model adversarial pass) all called the cleanup behaviour-neutral"
root_cause: logic_error
resolution_type: code_fix
related_components:
  - testing_framework
  - development_workflow
tags:
  - static-analysis
  - ratchet-pattern
  - mypy
  - ruff
  - behaviour-preservation
  - pep-479
  - typing-cast
  - cross-model-falsification
---

# A lint/type ratchet cleanup is not behaviour-neutral by construction

## Context

U17a of the 0.16.0 release brought every module 0.16.0 touched under the
static-analysis ratchet (the `_LINT_PATHS` / `_TYPE_CHECK_PATHS` tuples in
`tests/meta/test_static_analysis.py:51` and `:80`, plus the CI mypy step).
Under `src/protokit/` that meant `_descriptors.py`, `_pools.py`, the schema
checker, rules and CLI modules, and the whole formatters and message packages,
including `src/protokit/message/differ.py`. The project's ruff config selects the `SIM` family
(`pyproject.toml:152`) and mypy runs with `strict = true` and
`warn_return_any = true` (`pyproject.toml:156-157`).

The unit's contract was that the cleanup is type- and lint-only: no change to
return values, exceptions, output, exit codes or `--help`, on either protobuf
backend. Two kinds of edit made to satisfy the tools broke that contract:

1. **ruff SIM110's suggested rewrite.** `MessageDifferencer._is_treat_as_set`
   looped over the configured selectors and returned on the first match. SIM110
   (as of ruff 0.15.12, the version in use when this was written) suggests
   collapsing that into
   `return any(selector.matches(fd, field_path) for selector in self._treat_as_set_selectors)`.
   `selector.matches` calls a user-supplied predicate. Under PEP 479, a
   `StopIteration` raised inside a generator body is converted to
   `RuntimeError("generator raised StopIteration")`, so a predicate that raised
   `StopIteration` reached the caller as `StopIteration` before the rewrite and
   as `RuntimeError` after it. The rewrite also puts a generator frame into the
   traceback that the loop did not have.
2. **`str()` / `bool()` wraps added to silence mypy `no-any-return`.**
   `_hook_name` became `return str(getattr(hook, "__qualname__", None) or ...)`.
   The diagnostic renders the name with `!r` (`src/protokit/message/differ.py:444`).
   For a `__qualname__` that is a `str` subclass with its own `__str__`, `str()`
   calls that override and returns a different string, so the message changed
   from `hook 'original' raised ValueError during VALIDATE: boom` to
   `hook 'converted' ...`. The same pattern was used in
   `_descriptors.is_repeated` / `is_required` (`bool(field_desc.label == ...)`),
   `_descriptors.has_presence` (`bool(fd.has_presence)`) and differ's
   implicit-presence check (`bool(a != b)`). Each `bool(...)` forces `__bool__`
   on whatever `==` / `!=` / the attribute returns. Real protobuf descriptors
   return plain `int` / `bool` there, so per this session's conclusion only
   descriptor-shaped fakes can reach the difference, but the wrap is still a
   runtime call the original code did not make.

Every in-house check missed both. The full suite was green on upb and on
`PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python`. Three simplify reviewers
(reuse, quality, efficiency) and a full code review (correctness, testing,
maintainability, project-standards and learnings reviewers, plus a cross-model
adversarial pass on the default model) all called the cleanup behaviour-neutral. What found both was a `gpt-6-astra` falsification pass whose
claims named the vectors explicitly: "for every input the edited code produces
identical results and side effects ... including exceptions from user callables,
`__bool__` / `__eq__` / `__str__` overrides, short-circuit order, `python -O`".
It returned two COUNTEREXAMPLES, and both reproduced against a worktree checked
out at the base revision. A refuter pass on the first fix then flagged the
`bool(...)` wraps in `_descriptors`.

## Guidance

**Treat each lint or type fix as a code change that needs its own equivalence
argument.** "The linter suggested it" and "it only exists to satisfy mypy" are
not arguments. Before accepting an edit, ask what runtime calls it adds, removes
or reorders.

**Narrow types with `typing.cast`, never with a converting call.** `cast` is a
no-op at runtime; `str()`, `bool()`, `int()` and `list()` call dunders on the
value and can change it. The fixes on the U17a branch:

```python
# src/protokit/message/differ.py:70-75
def _hook_name(hook: object) -> str:
    """Best-effort display name for a hook in warning messages."""
    # cast, not str(): a __qualname__ that is a str subclass renders as given.
    return cast(str, getattr(hook, "__qualname__", None) or getattr(
        hook, "__name__", repr(hook),
    ))
```

```python
# src/protokit/_descriptors.py:59, :69, :278
return cast(bool, field_desc.label == proto_descriptor.FieldDescriptor.LABEL_REPEATED)
return cast(bool, field_desc.label == proto_descriptor.FieldDescriptor.LABEL_REQUIRED)
return cast(bool, fd.has_presence)

# src/protokit/message/differ.py:867
return cast(bool, _field_value(msg, left_fd) != _field_value(default_msg, left_fd))
```

One `str()` wrap was kept on purpose: `schema/rules._real_containing_oneof`
returns `str(oneof.name)` (`src/protokit/schema/rules.py:206`). Protobuf returns
a plain `str` there, so the call cannot change the value, and adding a `typing`
import would shift the line numbers that published docs cite in that file. If
you keep a converting call, write down why it cannot differ.

**Decline SIM110 / SIM111 where the loop body calls code you do not own.** Keep
the loop, suppress the rule on that line, and leave a comment so the next
cleanup does not "fix" it again:

```python
# src/protokit/message/differ.py:2631-2636
# A plain loop, not any(genexpr): inside a generator a selector's own
# StopIteration would surface as RuntimeError (PEP 479).
for selector in self._treat_as_set_selectors:  # noqa: SIM110
    if selector.matches(fd, field_path):
        return True
return False
```

**Pin each counterexample with a regression test and prove the test is not
vacuous.** Both tests below were mutation-checked with
`scripts/mutation_check.py` against the reintroduced rewrite:

```python
# tests/message/test_set_comparison.py:361
class TestSelectorExceptionsPropagate:
    def test_stop_iteration_from_a_predicate_is_not_rewrapped(self) -> None:
        ...
        def exhausted(fd: object, path: object) -> bool:
            raise StopIteration("selector exhausted")

        d = MessageDifferencer()
        d.treat_as_set(FieldSelector.from_predicate(exhausted))
        with pytest.raises(StopIteration, match="selector exhausted"):
            d.compare(msg1, msg2)
```

```python
# tests/message/test_hooks.py:1023
class TestHookNameInDiagnostics:
    def test_qualname_is_rendered_as_given_not_through_str(self) -> None:
        class Name(str):
            def __str__(self) -> str:
                return "converted"

        class Hook:
            def __init__(self) -> None:
                self.__qualname__ = Name("original")

            def __call__(self, ctx: FieldHookContext) -> None:
                raise ValueError("boom")
        ...
        assert [e.message for e in result.errors] == [
            "hook 'original' raised ValueError during VALIDATE: boom"
        ]
```

**Verify neutrality with a falsification pass that names the vectors.** Asking
a reviewer "is this behaviour-neutral?" got "yes" from every reviewer here. The
pass that worked listed the ways equivalence breaks and asked for a
counterexample for each:

- exceptions raised by user callables, including `StopIteration`
  (generator and comprehension rewrites);
- dunder dispatch: `__bool__`, `__eq__` / `__ne__`, `__str__` / `__repr__`,
  `__len__`, `__iter__`;
- short-circuit and evaluation order (`any` / `all` against the loop,
  `or` / `and` chains);
- `python -O` (a removed or added `assert`);
- traceback shape, if anything inspects frames.

Reproduce every counterexample against a worktree at the base revision before
you accept it, then add a test that fails on the rewrite.

## Why This Matters

A ratchet widening touches many modules at once, and every edit is small and
comes with a tool's approval. That combination makes review assume the diff is
mechanical. The test suite doesn't cover the gap: it exercises the inputs the
library expects, and these regressions only show up on inputs nobody writes a
test for until someone asks: a predicate that raises `StopIteration`, a
`__qualname__` that overrides `__str__`. A user who hit the first would see a
`RuntimeError` from the library with no obvious cause, in a release whose
changelog called the change internal-only.

`typing.cast` gives mypy exactly what it needs and nothing else. A converting
call is a runtime function call that happens to type-check. Having the fix be
"cast, and say why in a comment" also keeps the next ratchet widening from
bringing the conversion back.

## When to Apply

- Adding modules to `_LINT_PATHS` / `_TYPE_CHECK_PATHS`, or any "make it pass
  ruff/mypy" sweep described as no behaviour change.
- Any ruff rewrite that turns a loop into `any()`, `all()`, a comprehension or a
  generator (SIM110, SIM111, and similar), when the loop body calls a
  user-supplied callable or a protocol method.
- Any `no-any-return` / `return-value` fix. Use `cast` by default; use a
  converting call only when the value is provably of the exact builtin type,
  and say so in a comment.
- Any review where the only verification of "behaviour-neutral" is a green
  suite and reviewers agreeing. Add a falsification pass that names the
  vectors, run before the PR merges.

Out of scope here, noted once: `scripts/mutation_check.py` clears `.pyc` caches
but not `.mypy_cache`, so a same-length mutation restored within the same second
can leave mypy reporting a phantom error until the cache is deleted (CI starts
cold). That belongs with
[[mutation-check-harness-stale-bytecode-and-nonverdict-exit-codes-produce-false-verdicts]].

## Examples

**SIM110: loop to `any(genexpr)`**

Before (ruff's suggestion, applied during the cleanup):

```python
return any(
    selector.matches(fd, field_path)
    for selector in self._treat_as_set_selectors
)
# predicate raises StopIteration("selector exhausted")
# -> caller sees RuntimeError("generator raised StopIteration")
```

After (on the U17a branch):

```python
# A plain loop, not any(genexpr): inside a generator a selector's own
# StopIteration would surface as RuntimeError (PEP 479).
for selector in self._treat_as_set_selectors:  # noqa: SIM110
    if selector.matches(fd, field_path):
        return True
return False
# -> caller sees StopIteration("selector exhausted"), as before the cleanup
```

**`no-any-return`: `str()` to `cast`**

Before:

```python
return str(getattr(hook, "__qualname__", None) or getattr(hook, "__name__", repr(hook)))
# __qualname__ = Name("original") where Name.__str__ returns "converted"
# -> "hook 'converted' raised ValueError during VALIDATE: boom"
```

After:

```python
# cast, not str(): a __qualname__ that is a str subclass renders as given.
return cast(str, getattr(hook, "__qualname__", None) or getattr(
    hook, "__name__", repr(hook),
))
# -> "hook 'original' raised ValueError during VALIDATE: boom"
```

**`no-any-return`: `bool()` to `cast`**

Before:

```python
return bool(field_desc.label == proto_descriptor.FieldDescriptor.LABEL_REPEATED)
# calls __bool__ on whatever == returned
```

After:

```python
return cast(bool, field_desc.label == proto_descriptor.FieldDescriptor.LABEL_REPEATED)
# returns what == returned, unchanged, as the pre-cleanup code did
```

## Related

- [[pytest-static-analysis-gate-ratchet-2026-05-02]]: the ratchet this
  cleanup widened. This doc covers the cost of widening it.
- [[mutation-check-harness-stale-bytecode-and-nonverdict-exit-codes-produce-false-verdicts]]:
  the harness used to prove both regression tests are not vacuous.
- [[sibling-blindness-fix-survives-review-structural-siblings-stay-broken]] and
  [[frozen-record-reflection-guard-only-as-good-as-classifier-and-probes]]:
  earlier cases where a named-target falsification pass found what in-house
  review did not.
