---
title: "A caught rule exception kept the run alive but never reached the exit verdict, so a crashed gate exited 0"
date: 2026-08-30
last_updated: 2026-09-20
category: docs/solutions/security-issues
module: protokit.schema.lint
problem_type: security_issue
component: tooling
severity: high
symptoms:
  - "`protokit lint --rule-pack <pack whose rule raises>` exits 0 and reports a clean schema"
  - "`--max-warnings 0` — the strictest gate available — also exits 0 on the same run"
  - "`report.runtime_warnings` correctly contains `rule_exception`, and the human/JSON/SARIF output correctly shows it, but the exit code does not reflect it"
  - "A CI job gating on `protokit lint` passes on a run where no rule actually executed"
root_cause: incomplete_implementation
resolution_type: code_fix
related_components: [development_workflow, testing_framework]
tags:
  - fail-open
  - exit-code
  - ci-gate
  - error-handling
  - tolerant-iteration
  - protokit-lint
---

# A caught rule exception kept the run alive but never reached the exit verdict

## Problem

The lint engine deliberately **tolerates** a rule that raises. It catches the
exception, records a
`LintRuntimeWarning(category="rule_exception")` on `report.runtime_warnings`,
and continues walking. That resilience is correct: one broken rule in a
user-supplied pack should not take down the whole run.

The CLI then computed its exit code **only from `report.findings`**:

```python
has_error = any(f.severity is LintSeverity.ERROR for f in report.findings)
if has_error:
    sys.exit(1)
if resolved.max_warnings is not None:
    warning_count = sum(1 for f in report.findings
                        if f.severity is LintSeverity.WARNING)
    if warning_count > resolved.max_warnings:
        sys.exit(1)
```

A rule pack that crashes on *every* element produces **zero findings**. So
both gates saw an empty report and the process exited 0. `--max-warnings 0`
did not help — there were no warnings to count. The one signal that said the
analysis had not completed lived on `runtime_warnings`, and nothing consulted
it.

The failure is the gap between **tolerating** an error and **reporting** it.
The engine did its half. The verdict never learned.

## Symptoms

```console
$ protokit lint --rule-pack pack_whose_rule_raises clean.descriptor_set
protokit lint: warning [rule_exception]: synthetic-failure
$ echo $?
0

$ protokit lint --max-warnings 0 --rule-pack pack_whose_rule_raises clean.descriptor_set
$ echo $?
0
```

The warning is right there on stderr. The exit code says the schema is clean.
CI reads the exit code.

## What Didn't Work

**Assuming the resilience layer was the whole fix.** The engine's catch site
had been reviewed and was correct in isolation, and the machine formatters
faithfully emitted `runtime_warnings`. Every component behaved. The defect
lived in the space between them, which is exactly the shape that survives
component-level review.

**Trusting the test suite.** Four existing tests asserted `exit_code == 0` for
a crashed-rule run. They were not oversights — they had *codified* the bug as
expected behavior, so the suite actively defended it. A green suite was
evidence that nothing had changed, not that the behavior was right.

## Solution

Add a completeness gate that runs **before** the findings gates and **after**
the report is rendered:

```python
# src/protokit/_trust.py:137-141 — the predicate, owned in one place.
#: ``LintRuntimeWarning`` categories that mean a selected rule did not run,
#: so the findings are a lower bound on an unknown total (V33).
INCOMPLETE_ANALYSIS_CATEGORIES: frozenset[str] = frozenset({
    "rule_exception",
    "unloaded_rule",
    "all_files_excluded",
})

# src/protokit/schema/lint/cli.py:174-176 — an alias to it, kept for the
# gate's message and for the exhaustiveness test below.
_INCOMPLETE_ANALYSIS_CATEGORIES: frozenset[str] = (
    _trust.INCOMPLETE_ANALYSIS_CATEGORIES
)

# src/protokit/schema/lint/cli.py:1533 — after the report, the human-warning
# hook, and the statistics footer:
incomplete = _trust.signals(report)
if incomplete:
    error_exit_with_code(
        "analysis-incomplete",
        f"{_analysis_incomplete_detail(report, incomplete)}; the findings "
        "this run produced are a lower bound, so a clean result would "
        "not mean the schema is clean",
    )
```

The predicate moved out of the lint CLI and into `protokit._trust` in 0.16.0
so that the exit code and every renderer read one set instead of each deciding
for itself, and `all_files_excluded` — an `--exclude` pattern that dropped
every named input, so the engine never ran at all — joined the gated set in
the exit-gates unit (PR #76).

Three placement decisions carry the design:

**Exit 2, not 1.** Exit 1 asserts *"the tool ran and found a problem."* That
claim is unavailable when part of the analysis never ran. Exit 2 means *"the
tool could not run."* The distinction is what lets a CI script tell a real
finding from a broken toolchain.

**Exit 2 wins over exit 1.** A run with both real findings and a crashed rule
exits 2. The findings it did produce are a lower bound; reporting them as
*the* answer would be the same overclaim in a smaller font.

**Gate after rendering.** The report, the stderr warnings, and the statistics
footer all emit first. The findings that *were* produced stay readable — only
the verdict changes. Gating before rendering would throw away real output to
report a partial failure.

## Why This Works

The exit code becomes a function of *both* what was found and whether the
search completed, instead of only the former. That is the invariant the CLI
was missing, and it is checkable: for any report, ask whether the absence of
a finding is evidence of absence. When a selected rule did not execute, it is
not.

## Prevention

### The general shape

**Every `except` that swallows an error to keep going creates an obligation
somewhere else.** Tolerant iteration — continue-on-error, skip-and-record,
partial results — is a good pattern, and it is only half a pattern. The other
half is that the recorded error must reach the caller's verdict: an exit code,
a raised exception, a `success: false`, a non-empty `errors` array the caller
is forced to read.

The audit question for any such handler: *if this error fires for every item,
what does the caller see?* If the answer is "success", the handler is a
fail-open.

This generalises well past linting — a batch job that skips bad records, a
scanner that continues past unreadable files, a migration that logs and moves
on. In each, "0 failures reported" and "0 items processed" must not render
identically.

### Beware the tests that defend the bug

When a fix requires changing existing assertions, stop and read them. Four
tests here asserted the fail-open exit code. That is a signal worth taking
seriously in both directions: either the behavior was intended and the fix is
wrong, or the bug was baked in early and every later test inherited it. Decide
which, explicitly, and say so in the CHANGELOG — downstream forks may pin the
old code.

### Ratchet the category set, do not rely on prose

The gate keys on a hand-maintained frozenset of `Literal` members. A future
category meaning "a rule did not run" would land outside it silently — the
same drift the fix exists to stop. Force a decision instead:

```python
def test_every_category_is_classified(self):
    literal_args = set(typing.get_args(
        typing.get_type_hints(LintRuntimeWarning)["category"]))
    classified = (set(_INCOMPLETE_ANALYSIS_CATEGORIES)
                  | set(DEFERRED_INCOMPLETE) | set(ADVISORY))
    assert classified == literal_args
```

That test is
`TestIncompleteAnalysisCategoryClassification::test_every_category_is_classified`
in `tests/schema/lint/test_model_dataclass_changes.py:168`, with the two other
buckets (`DEFERRED_INCOMPLETE`, `ADVISORY`) declared on the class beside it.

Adding a category without classifying it now fails a test. Prose in a comment
does not.

### Assert on the gate's own output, not on all of stderr

The first regression test here asserted `"rule_exception" in result.stderr` —
which the *pre-existing* warning hook already satisfies. It passed with the
entire gate disabled. Scope the assertion to the line the new code emits:

```python
gate_lines = [l for l in result.stderr.splitlines()
              if l.startswith("error[lint-analysis-incomplete]:")]
assert gate_lines, result.stderr
assert "rule_exception" in gate_lines[0], gate_lines[0]
```

Then prove it non-vacuous:

```sh
python3 scripts/mutation_check.py src/protokit/schema/lint/cli.py \
  '    if incomplete:' '    if False:' \
  "tests/schema/lint/cli/test_cli_ci_gating.py::TestAnalysisIncompleteExitGate"
```

**An anchor goes stale the way an assertion does.** This recipe used to read
`'    if blocking:'`, which was the gate until the predicate moved to
`protokit._trust`. That string is still in `src/protokit/schema/lint/cli.py`,
and still *unique* — it now sits inside `_analysis_incomplete_detail`, which
builds the gate's error **message**. So the harness accepts the anchor, mutates
a sentence, watches a test that asserts on that sentence fail, and prints
NON-VACUOUS: a real verdict about the message builder, handed to a reader who
believes they proved the exit gate. That is the rule above — assert on the
gate's own output, not on everything near it — one level up. An anchor has to
be scoped to the code it means, and re-derived whenever that code moves;
uniqueness is not aim.

**The harness's own false verdicts are closed.** A wrong pytest node id used to
make pytest exit non-zero with `no tests ran`, which a naive harness read as
"the test failed under mutation" and reported NON-VACUOUS. That hole — with
stale `.pyc` bytecode and a target already red before the mutation — was closed
on 2026-09-15; see
[mutation-check-harness-stale-bytecode-and-nonverdict-exit-codes-produce-false-verdicts](../logic-errors/mutation-check-harness-stale-bytecode-and-nonverdict-exit-codes-produce-false-verdicts.md).

## Related

This defect is one instance of a pattern this codebase has now documented ten
times: a fix lands at one call site while structurally identical siblings stay
broken. See [[sibling-blindness-fix-survives-review-structural-siblings-stay-broken]]
for the detection procedure, and for why naming the pattern has repeatedly
failed to prevent it.

[[trust-boundary-enforcement-points-derived-from-code-not-the-findings-wording]]
is this doc's compat-side counterpart, carrying the opposite half of the same
defect. Here the rule's exception *was* caught and simply never reached the
verdict. There it was never caught at all — the dispatch guard read
`except Exception`, which `SystemExit` is not — so nothing was recorded that
could reach a verdict, and the rule's own exit code became the process's. Both
now resolve through the same seam: lint at
`src/protokit/schema/lint/cli.py:1533`, compat at
`src/protokit/schema/cli.py:828`.
