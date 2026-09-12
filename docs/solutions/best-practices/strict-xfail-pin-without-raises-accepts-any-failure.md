---
title: "Strict xfail only detects XPASS: a regression pin must declare raises= (and CliRunner catch_exceptions=False) or any failure before its assertion is accepted as the pinned defect"
date: 2026-09-07
last_updated: 2026-09-12
category: docs/solutions/best-practices
module: testing/pytest-conventions
problem_type: best_practice
component: testing_framework
severity: high
applies_when:
  - "Pinning a confirmed, still-unfixed defect as a regression test with @pytest.mark.xfail(strict=True), so the suite stays green until the fix lands and flips the pin to XPASS"
  - "The pin's body builds fixtures, shells out to an optional compiler, or drives a CLI through click.testing.CliRunner -- anything that can raise before the named assertion is reached"
  - "The pin runs on more than one CI cell (protobuf backend, compiler availability, OS), so an environment gap can preempt the assertion on some cells and not others"
  - "The pin asserts on a coarse channel such as an exit code, where an unrelated crash yields the same observable value the defect does (Click folds any unhandled exception into exit_code == 1)"
  - "A green 'N xfailed, 0 xpass' summary is being read as evidence that each defect is still reproduced -- for example as the pre-fix half of a 'test fails on pre-fix code' release requirement"
symptoms:
  - "pytest records a pin as xfailed although it died in fixture construction (KeyError('.test.Elem') inside ProtoBuilder under PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python) before reaching its assertion"
  - "With neither protoc nor protoxy installed, compile_proto's SystemExit(2) satisfies a strict xfail meant to pin a compile-output defect"
  - "CliRunner.invoke with the default catch_exceptions=True turns an unrelated crash into exit_code == 1, so a pin asserting exit_code == 2 fails for the wrong reason and is still recorded as xfailed"
  - "pytest --runxfail shows every pin failing, but on exception types unrelated to the finding IDs in their reason= strings"
  - "The suite summary reads the same 'N xfailed, 0 xpass' on the CI cell where the fixture cannot be built at all"
root_cause: wrong_api
resolution_type: test_fix
related_components:
  - tooling
  - development_workflow
tags:
  - false-confidence
  - pytest
  - test-design
  - xfail
  - regression-pin
  - clirunner
  - fail-loud
  - ce-review
---

# Strict xfail only detects XPASS: a regression pin must declare raises= (and CliRunner catch_exceptions=False) or any failure before its assertion is accepted as the pinned defect

## Context

PR #55 (merged) added seven files pinning 24 confirmed audit findings as
strict xfails: 38 `@pytest.mark.xfail(strict=True, ...)` markers across
`tests/message/test_audit_u8_differ_pins.py`,
`tests/schema/test_audit_u9_compat_rule_pins.py`,
`tests/schema/test_audit_u14_compile_pins.py`,
`tests/schema/test_audit_u14_git_import_pins.py`,
`tests/schema/test_audit_u14_git_ref_pins.py`,
`tests/schema/test_audit_u15_cli_exit_pins.py` and
`tests/schema/lint/test_audit_u20_buf_parity_pins.py`. (Eight of those
markers sit on parametrized tests, which is why the suite reports 50
xfailed outcomes for 38 markers.) A pin asserts the *correct* behaviour,
fails today, and is meant to XPASS loudly the day the fix lands.
`strict=True` is what makes the XPASS loud.

`strict=True` is *only* about XPASS. It says nothing about why the test
failed. In the installed pytest (9.0.2, library source `_pytest/skipping.py:288-304`)
turns any exception into an xfail when `raises is None` -- and that branch
is not gated on the test phase, so a fixture that raises during setup is
absorbed the same way (only the XPASS branch at `skipping.py:306-308`
checks `call.when == "call"`). A pin that dies in a fixture, an import, a
missing compiler, or an unrelated crash *before* its named assertion is
recorded as xfailed, and the suite is green for the wrong reason -- the
exact failure class the pins exist to eliminate.

### What Was Observed

An independent cross-model review pass (read-only, during the PR #55
review) produced three concrete instances against the pre-fix tree, all of
which the full suite reported as `xfailed`:

- **U8, pure-Python protobuf.** Under
  `PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python`,
  `test_repeated_submessage_elements_must_pair_order_independently` raised
  `KeyError('.test.Elem')` inside `ProtoBuilder.build`, before
  `MessageDifferencer.compare` ever ran. `tests/proto_builder.py` emits one
  `FileDescriptorProto` per message and never sets `dependency`, which the
  pure-Python `DescriptorPool` cannot resolve. The paired control
  `test_pairs_cleanly_in_one_element_order_control` builds a single flat
  message, so it stayed green and could not expose the gap.
- **U14-6 / U14-7, no compiler backend.** `extract_pool_from_ref`
  (`src/protokit/schema/git.py`) calls `compile_proto`, whose
  both-backends-absent handler (`src/protokit/_cli_utils.py`) calls
  `error_exit`, which is `sys.exit(2)`. On a machine with neither protoxy
  nor protoc, those pins would accept `SystemExit(2)` as their expected
  failure.
- **U15-4, Click folding.** In click 8.3.2 (library source `click/testing.py:519-523`):
  with the default `catch_exceptions=True`, `CliRunner.invoke` swallows any
  `Exception` and reports `exit_code = 1`; `SystemExit` is caught
  unconditionally at `:502`. An injected `NameError` in the `check`
  callback therefore satisfied the pin's `assert result.exit_code == 2`
  failure just as well as the real defect did.

The in-house correctness reviewer independently flagged "no `raises=` on
any pin", and the in-house learnings pass found that all nine
`CliRunner.invoke` calls in the U15 file violated the existing
[[clirunner-catch-exceptions-false-explicit-discipline-2026-05-21]].

### What Didn't Catch It

- **Flip-validation.** The ten U14 pins had been flipped (simulate the fix
  at `pytest_configure`, run the full suite under `--runxfail`, watch them
  XPASS with no green test broken). Flipping proves the assertion can pass;
  it proves nothing about the failure path. (session history: the flip
  check was called out at authoring time as "a materially stronger claim
  than 'these tests currently fail'" -- and it is, but for a different
  property.)
- **`--runxfail` on the authoring machine.** Every pin had been seen
  failing on its named line -- in one environment, with protoxy installed
  and upb protobuf. Nothing *encoded* that observation, so it evaporated
  the moment the environment changed.
- **Controls that build a different construction.** The U8-2 control built
  a flat `Msg{repeated enum}` while the pin built `Container{repeated
  Elem}`. A control only certifies preconditions it actually shares with
  its pin.
- **Authoring-time validation asked the wrong question.** (session history)
  Every check at authoring time was about *whether* a pin failed or
  flipped -- control tests, the flip check, canonical-checkout suite runs,
  a citation-resolution pass over 149 symbols -- and none about *which
  exception* the marker would accept. The hole was orthogonal to all of it.

Measured on the current tree under pure-Python protobuf: the pre-fix U8
file reported `3 failed, 5 passed, 10 xfailed`; the fixed file reports
`8 failed, 5 passed, 6 xfailed`. Four pins that had been silently
absorbing `KeyError` are now red, plus the new control. (The ProtoBuilder
fix itself landed as unit U22, PR #57 -- see
[[wire-filedescriptorproto-dependency-through-pool-pure-python-vs-upb]];
until then the pins are *honest* there, not green.)

## Guidance

**Every strict xfail pin names the exception it fails with.** Add
`raises=` to the marker, keyed to the exception observed today, not to what
seems plausible. `skipping.py:291-304` then does the work: a matching
exception is xfailed; anything else is reported as a plain FAILED.

Discover the value empirically, per file, before writing the marker:

```
.venv/bin/python -m pytest <file> --runxfail --tb=line
```

Each pin prints `file:line: ExceptionType: message`. Confirm the line is
the pin's named assertion, then transcribe the type. (`-rf` gives the
short summary; `--tb=line` is what shows the type and line in one row.)

| Shape of the pin body | `raises=` | Notes |
| --- | --- | --- |
| `assert <correct behaviour>` | `AssertionError` | The common case (28 of 38 markers). |
| `with pytest.raises(...)` that does not raise, or explicit `pytest.fail(...)` | `pytest.fail.Exception` | `Failed` is an `OutcomeException(BaseException)` (pytest 9.0.2 source, `_pytest/outcomes.py`), so it matches neither `AssertionError` nor `Exception`. "DID NOT RAISE" is raised via `fail()`. |
| The defect *is* an escaping exception | that exception, e.g. `RuntimeError`, `ValueError` | When it crosses `CliRunner.invoke`, pass `catch_exceptions=False` or Click folds it into `exit_code == 1` and you are back to `AssertionError` for the wrong reason. |
| The defect *is* a `sys.exit` / `error_exit` | `SystemExit` | `CliRunner` catches `SystemExit` regardless of `catch_exceptions`; outside the runner it propagates. |

Three further rules that fell out of the review:

1. **Pair every pin with a control that shares its construction.** If the
   pin builds `Container{repeated Elem}` across two pools, the control must
   too: a red control says "precondition broken", a red pin says "defect
   changed shape", and only a shared construction lets you tell them apart.
2. **Do not widen the accepted failure to make an environment pass.** A
   `contextlib.suppress(SystemExit)` around a call whose expected failure
   is an assertion (the U14-3 fallback pin in
   `tests/schema/test_audit_u14_git_ref_pins.py`) is fine because the
   pin's *assertion* is still the only accepted failure; widening it to
   `Exception` was considered and rejected because it would have masked a
   git failure today. Likewise no module-level backend skip was added to
   the git-import pins: with `raises=`, a no-compiler environment is
   honestly red, which is the correct signal.
3. **Say it in the module docstring.** The U15 file now carries a
   paragraph ("Every pin names the exception it fails with") so the next
   author sees the discipline before the first marker.

The guard landed as `tests/meta/test_xfail_raises_ratchet.py` (U22 of the
0.16.0 plan, PR #57): an `ast` walk over `tests/**/*.py` that fails with
the file:line of any `pytest.mark.xfail` *construction* -- decorator or
not, strict or not -- that lacks a `raises=` keyword, and it forbids the
shapes that evade a decorator-only check: a module-level `pytestmark`
xfail, `pytest.param(..., marks=xfail)`, imperative `pytest.xfail()`, and
any alias of the marker (`import pytest as pt`, `from pytest import
mark`, `xfail = pytest.mark.xfail`). It started at zero violations (all
38 markers carried `raises=`; none of the other shapes existed under
`tests/`), so it is strict from its first commit with no allowlist.

Two review findings on that ratchet are the durable part, because each is
a way a guard can pass while the thing it guards is absent:

1. **Check every construction, not one position.** The first cut inspected
   only `decorator_list`. A test body that calls
   `request.applymarker(pytest.mark.xfail(strict=True))` or
   `item.add_marker(...)` produces an XFAIL the decorator walk never sees,
   and a review probe showed pytest reporting it green. The fix scans every
   `pytest.mark.xfail` call and bare-attribute use anywhere in the module,
   so a `conftest.py` hook that builds a marker is checked by the same rule
   (it passes when it names `raises=`, which the pure-Python inventory hook
   must).
2. **Validate the value, not the keyword's presence.** `raises=None`,
   `raises=Exception`, `raises=BaseException`, or a tuple holding one of
   them satisfied a presence check while leaving pytest's exception filter
   effectively off -- precisely the false green this document is about.
   Those are now offenders in their own right. The qualified spellings
   `builtins.Exception` and `builtins.BaseException` are offenders too
   (refreshed 2026-09-12, per PR #59): the ratchet compares spellings, so
   a bare-name list missed them until an independent falsification pass of
   the pure-Python inventory unit reproduced the bypass; a check on the
   resolved class, as the inventory's own loader does, never had the hole.

The general rule: a ratchet over a discipline must enumerate the ways the
discipline can be spelled, not the one way the author first wrote it, and
its self-checks must include each evasion shape as an injected violation.

## Why This Matters

- **The suite is not evidence; the failure reason is.** PR #48 shipped
  four self-inflicted defects past a green suite, which is why
  `scripts/mutation_check.py` now demands a test be shown failing under a
  mutation (auto memory [claude]). `raises=` is the same discipline
  applied to pins: a pin must be shown failing *for the named reason*, and
  the marker must carry that proof so it re-executes on every machine.
- **Pins are portability-sensitive by construction.** They sit on the
  edges of the system -- compiler backends, git on PATH, protobuf
  implementation -- which is exactly where environment drift lands. An
  unrestricted xfail turns each of those edges into a silent absorber.
- **Click makes exit-code pins especially fragile.** Any unhandled
  exception becomes `exit_code == 1`, the very code these pins assert
  *against*; only `catch_exceptions=False` separates "the CLI chose 1" from
  "the CLI crashed".
- **`raises=` also covers setup.** Because the exception branch in
  `skipping.py` is not phase-gated, a fixture error would previously be
  xfailed; with `raises=AssertionError` it is now an ERROR.

## When to Apply

- Writing any `xfail(strict=True)` pin for a live defect, in this repo or
  elsewhere: `raises=` is part of the marker, not an optional refinement.
- Reviewing a PR that adds xfail markers: ask for the `--runxfail
  --tb=line` output and check each `raises=` against it. Ask whether the
  control shares the pin's construction.
- Any test that goes through `CliRunner.invoke`: `catch_exceptions=False`,
  per [[clirunner-catch-exceptions-false-explicit-discipline-2026-05-21]];
  the U15 file is the reference.
- A pin starts xfailing in CI on a different cell (pure-Python protobuf,
  no protoc, no git): that is the signal working. Fix the precondition or
  the control; do not widen `raises=`.
- NOT for plain `skip`/`skipif` guards, and NOT a reason to add
  `contextlib.suppress` around pin bodies -- the accepted failure should
  narrow, never widen.

## Examples

**U15-4 before (PR #55, pre-review).** Marker with `strict=True` only, and
the helper called `runner.invoke(compat_main, args)` with Click's default.
An escaping `RuntimeError("git not found on PATH; ...")` became
`exit_code == 1`, the `assert result.exit_code == 2` failed, and the xfail
accepted it -- as it would have accepted a `NameError` in the callback.

**U15-4 after** (`tests/schema/test_audit_u15_cli_exit_pins.py`):

```python
@pytest.mark.xfail(
    strict=True,
    raises=RuntimeError,
    reason=("U15-4: _run_git translates a missing binary into "
            "RuntimeError('git not found on PATH; ...'), but only "
            "_resolve_range_endpoints (history-only) catches RuntimeError. ..."),
)
def test_u15_4_missing_git_is_a_tooling_error_not_a_break(...):
    ...
    result = _invoke_in_repo(breaking_repo, args)   # invoke(..., catch_exceptions=False)
    assert result.exit_code == 2, (...)
```

The defect *is* the escaping `RuntimeError` (raised in
`src/protokit/schema/git.py`), so the pin is narrowed to it; the assertion
is reached only after the fix, at which point it passes and strict mode
reports XPASS. Sibling pins in the same file whose defect is a wrong exit
code stay on `raises=AssertionError`; the JSON parse pin uses
`pytest.fail.Exception`; the differ-validation pin uses `ValueError`.

**U8 nested control** (`tests/message/test_audit_u8_differ_pins.py`),
added so a pool that cannot resolve `Elem` from `Container` is a RED
control:

```python
def test_repeated_submessage_elements_pair_cleanly_in_one_order_control(self) -> None:
    left_b = _enum_elem_builder(_LEFT_ENUM)      # Container{repeated Elem}, two pools
    right_b = _enum_elem_builder(_RIGHT_ENUM)
    left_elem = left_b.get_message_class("test.Elem")
    right_elem = right_b.get_message_class("test.Elem")
    left = left_b.build("test.Container", elems=[left_elem(status=1), left_elem(status=5)])
    right = right_b.build("test.Container", elems=[right_elem(status=1), right_elem(status=5)])
    d = MessageDifferencer(); d.treat_as_set("elems")
    assert not d.compare(left, right).has_changes()
```

The pin is the same construction in the other element order, marked
`raises=AssertionError`. Under pure-Python protobuf both now fail on
`KeyError('.test.Elem')` -- the control as FAILED, the pin as FAILED
because `KeyError` is not `AssertionError` -- instead of one green control
and one quietly xfailed pin.

**Other representative markers as they now read:**
`tests/schema/test_audit_u14_git_ref_pins.py` (`raises=SystemExit` for the
only-protoc-can-compile pin, whose defect is `error_exit` firing);
`tests/schema/test_audit_u14_git_import_pins.py`
(`raises=pytest.fail.Exception` for a `with pytest.raises(ProtoImportError)`
body that does not raise); `tests/message/test_audit_u8_differ_pins.py`
(`raises=ValueError`, the differ's own validation error).

**The sketch that became the ratchet** (kept for the shape; the landed test
also catches non-strict markers, class-level decorators, and the three
forbidden forms, and self-checks each with a synthetic source):

```python
def test_every_strict_xfail_pin_names_its_exception() -> None:
    offenders = []
    for path in (_REPO_ROOT / "tests").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            for dec in getattr(node, "decorator_list", []):
                if not (isinstance(dec, ast.Call) and ast.unparse(dec.func) == "pytest.mark.xfail"):
                    continue
                kws = {kw.arg for kw in dec.keywords}
                if "strict" in kws and "raises" not in kws:
                    offenders.append(f"{path.relative_to(_REPO_ROOT)}:{dec.lineno}")
    assert not offenders, "strict xfail pins without raises= (green for the wrong reason): " + ", ".join(offenders)
```

Verification of the fix as merged: the seven files report
`34 passed, 50 xfailed, 0 xpassed`; `--runxfail --tb=line` shows every pin
failing on its declared exception; the full suite is
`3468 passed, 8 skipped, 50 xfailed`.

## Related

- [[clirunner-catch-exceptions-false-explicit-discipline-2026-05-21]] -- the CliRunner half of this discipline. That doc explains why the click default absorbs a crash into `exit_code == 1`; this doc explains why that absorption is fatal specifically for a strict xfail pin, and why `catch_exceptions=False` still cannot expose a `SystemExit`, which click folds unconditionally.
- [[sibling-blindness-fix-survives-review-structural-siblings-stay-broken]] -- the same release's "green suites are not evidence" finding. Its rule 4(c) (an exit-code-only assertion passes for the wrong reason) is the assertion-level form of this learning; its `mutation_check.py` caveat (a harness that infers failure from a non-zero exit reports NON-VACUOUS on zero collected tests) is the same shape as a strict xfail that accepts any exception as the expected one.
- [[test-proxy-signal-suppressed-by-mechanism-under-test-2026-05-25]] -- the independence check applied to a regression pin: the pin's failure is the proxy signal, and `raises=` is what makes it unable to fire for a reason other than the pinned defect. The passing control beside each pin is that doc's baseline contrast.
- [[fixture-precondition-assertion-surfaces-silent-test-2026-05-17]] -- the silent-test-confidence family this learning joins; here the vacuous surface is not the fixture or the assertion but the xfail marker itself.
- [[capture-setup-without-dispatch-false-test-confidence-2026-05-17]] -- the deletion test, inverted for pins: `strict=True` proves the pin notices the fix; `raises=` proves it notices everything else.
- [[ordered-preflight-guard-test-must-control-every-probe]] -- same "green in the one configuration that hides the defect" surface; a `raises=`-less pin generalises it to green in every configuration.
- [[pytestmark-does-not-guard-module-top-imports-2026-05-02]] -- companion marker-semantics gotcha: that doc is about what `pytestmark` does not gate at collection; this one is about what `strict=True` does not gate at report time.
- [[mock-patch-c-extension-method-descriptor-2026-05-06]] -- Rule 2 there (direct invocation plus `pytest.raises(SystemExit)` instead of CliRunner) is how a pin can name `SystemExit` in `raises=` at all; through CliRunner the exit is always folded and the pin must assert the code instead.
- [[presence-ratchet-test-pattern-for-prose-substrings-2026-05-14]] and [[pytest-static-analysis-gate-ratchet-2026-05-02]] -- the `tests/meta` ratchet family the proposed guard belongs to, including the "inject a violation and watch it fail" self-check.
- [[pure-python-backend-known-failure-inventory-ci-harvest]] -- the same `raises=` discipline applied to a data file: a committed known-failure inventory a conftest-registered hook turns into strict, exception-specific xfails under the pure-Python backend, with catch-alls rejected at load by resolved class rather than by spelling.
- [[formatter-systemexit-exit-code-bypass-2026-04-19]] -- why `SystemExit` must be named explicitly in `raises=`: it is outside the `Exception` subtree.
- PR #55 -- where the pins and this fix landed.
