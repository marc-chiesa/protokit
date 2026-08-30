---
title: "An empty selector parses to the root path and prefix-matches every finding, opening the whole gate"
date: 2026-08-30
last_updated: 2026-08-30
category: docs/solutions/security-issues
module: protokit.schema
problem_type: security_issue
component: tooling
severity: high
symptoms:
  - "`protokit compat check … --ignore=` (empty value) exits 0 and prints COMPATIBLE on a schema with breaking changes"
  - "`SchemaChecker().ignore('')` followed by `.check(...)` returns zero findings where the same pair reports one without it"
  - "`CompatibilityPolicy(ignore_paths=('',)).check(...)` returns zero findings"
  - "A CI job whose `--ignore` argument came from an unset shell variable runs a compatibility gate that cannot fail, and reports success"
root_cause: missing_validation
resolution_type: code_fix
related_components: [development_workflow, testing_framework]
tags:
  - fail-open
  - empty-string
  - prefix-matching
  - ci-gate
  - single-owner
  - protokit-compat
---

# An empty selector parses to the root path and prefix-matches every finding

## Problem

`SchemaChecker.ignore(path)` suppresses findings whose path begins with a
dotted prefix. It stores `FieldPath.parse(path)` and filters by
**segment-name prefix matching**, so `ignore("debug")` suppresses `debug`
and every descendant.

`FieldPath.parse("")` returns `FieldPath(segments=())` — the **root** path.
It does not raise: the grammar loop performs zero iterations on an empty
string and falls out with an empty segment tuple. The root is a prefix of
*every* path, so `ignore("")` suppresses the entire report.

The gate then reports success. `protokit compat` prints `COMPATIBLE` and
exits 0 on a schema with breaking changes, because from its point of view
there were no findings.

The realistic path to this input is not adversarial. It is:

```sh
protokit compat check old.desc new.desc --type acme.User --ignore="$IGNORE_PATH"
```

with `IGNORE_PATH` unset.

## Symptoms

```console
$ protokit compat check old.descriptor_set new.descriptor_set --type t.M
protokit compat — level: CONSUMER_SAFE, 1 finding(s)
INCOMPATIBLE
$ echo $?
1

$ protokit compat check old.descriptor_set new.descriptor_set --type t.M --ignore=
protokit compat — level: CONSUMER_SAFE, 0 finding(s)

COMPATIBLE
$ echo $?
0
```

Same inputs. The second run checked nothing and said so in the language of
success.

## What Didn't Work

**Validating at the CLI flag boundary.** The first fix rejected an empty
value inside `_build_configured_checker` in `schema/cli.py`, which every
compat subcommand routes through. It made all four subcommands exit 2 and
the regression tests passed.

It did not close the finding. Two other entry paths reach the same
suppression without touching the CLI:

```python
checker = SchemaChecker()
checker.ignore("")                      # still accepted
checker.check(old, "t.M", new, "t.M")   # 1 finding -> 0

CompatibilityPolicy(ignore_paths=("",)).check(...)   # same
```

A cross-model adversarial review found both by asking, specifically,
whether the guard was complete rather than whether the tests passed. The
tests could not have found it: they only exercised the CLI.

**Two further holes appeared in the narrowed guard:**

1. `if not path:` is a *falsiness* test, and falsiness is overridable:

   ```python
   class TruthyEmpty(str):
       def __bool__(self): return True

   checker.ignore(TruthyEmpty(""))   # passes the guard, root path stored
   ```

   `len(path) == 0` is the honest predicate.

2. Validation inside the checker builder still runs **too late** for
   `history` and `bisect`, which construct the checker *inside* the
   per-commit loop. An empty commit range never enters that loop:

   ```console
   $ protokit compat history --range HEAD..HEAD --proto-file acme/user.proto \
       --type acme.User --ignore=
   # HEAD..HEAD: no commits touch acme/user.proto
   $ echo $?
   0
   ```

   The invalid flag was accepted and the run reported success — the same
   fail-open, one level below its own fix.

## Solution

**Reject at the single owner, then validate early at the boundary for
timing.** These are two separate concerns and both are needed.

The correctness fix belongs in `SchemaChecker.ignore`, because every
supported entry path reaches it — the CLI flag, `CompatibilityPolicy`, and
direct API callers:

```python
def ignore(self, path: str) -> None:
    # ``len(...) == 0``, not falsiness: a ``str`` subclass overriding
    # ``__bool__`` passes ``if not path`` while still being the empty
    # string, and ``FieldPath.parse`` then returns the root path.
    if len(path) == 0:
        raise ValueError(
            "empty path suppresses every finding; omit the call instead"
        )
    self._ignore_paths.append(FieldPath.parse(path))
```

The CLI's pre-existing `except ValueError` turns that into exit 2, so the
CLI-local guard could be **deleted** rather than duplicated.

Timing is a separate fix. Each subcommand validates up front, reusing the
owner rather than restating its rule:

```python
def _validate_ignore_paths(ignore_paths: tuple[str, ...]) -> None:
    probe = SchemaChecker()
    for path in ignore_paths:
        try:
            probe.ignore(path)
        except ValueError as exc:
            error_exit(
                f"invalid --ignore path {path!r}: {_safe_for_stderr(exc)}"
            )
```

called as the first statement of `check` / `ci` / `history` / `bisect`.
This closes the empty-range hole and stops a usage error from first costing
a git traversal and a `--compat-rule-pack` module import — which executes
arbitrary user Python.

## Why This Works

The empty string is the *only* input for which `FieldPath.parse` returns
the root path; every other string requires a `_NAME_RE` segment and raises
on failure. So a single length check at the one place that appends to
`_ignore_paths` is complete for the supported surface, and every other
malformed value keeps its existing grammar error.

Splitting correctness from timing is what makes it stay fixed. If the check
only lived at the boundary, a new entry path silently reopens it. If it only
lived at the owner, a code path that never reaches the owner — an empty
commit range — silently reopens it.

## Prevention

### The general shape

**An empty value that parses to a "match everything" sentinel is a
fail-open, not an edge case.** The pattern generalises past protokit:
an empty prefix, an empty glob, an empty filter, an empty allowlist, an
empty regex. Wherever a suppression, filter, or scope value is parsed, ask
what the empty value means, and whether the answer is "everything".

The tell is that the code path has **no error branch**: parsing succeeds,
filtering succeeds, and the result is silently maximal.

### Fix at the owner, not the call site

Before writing a validation guard, find every path that reaches the
behavior — not just the one in the bug report. Grep for the mutation site
(here, the single `_ignore_paths.append`) and check each caller. If the CLI,
a config object, and a public method all reach it, the guard belongs at the
convergence point and the callers only report it.

A guard at one call site with structurally identical siblings left open is
the most common way a "fixed" fail-open stays open.

### Falsiness is not emptiness

`if not x:` on a value whose type is user-controllable is a weaker check
than it looks. Use `len(x) == 0` or `x == ""` when the property you mean is
emptiness. `str` subclasses can override `__bool__`; `__len__` for a real
empty string cannot lie about being zero.

### Regression test

Pin every entry path, not just the reported one, and assert the *specific*
diagnostic rather than the exit code alone — a neighbouring grammar error
also produces exit 2, so a bare `assert exit_code == 2` passes with the new
branch deleted:

```python
def test_empty_ignore_value_exits_2(self, tmp_path):
    # Baseline first: without --ignore the dropped field IS a finding.
    baseline = CliRunner().invoke(main, ["check", old, new, "--type", "t.M"])
    assert baseline.exit_code == 1

    result = CliRunner().invoke(main, ["check", old, new, "--type", "t.M",
                                       "--ignore", ""])
    assert result.exit_code == 2
    assert "empty path suppresses every finding" in result.output   # specific
    assert "COMPATIBLE" not in result.output


def test_truthy_empty_str_subclass_is_rejected(self):
    class TruthyEmpty(str):
        def __bool__(self) -> bool: return True
    checker = SchemaChecker()
    with pytest.raises(ValueError, match="empty path suppresses"):
        checker.ignore(TruthyEmpty(""))
    assert checker._ignore_paths == []
```

The **baseline assertion is load-bearing**: without it, a test that asserts
"no findings after the fix" cannot distinguish a working suppression from a
schema that never had a finding.

Prove non-vacuity with the repo's harness — the guard must make tests fail
when broken:

```sh
python3 scripts/mutation_check.py src/protokit/schema/checker.py \
  '        if len(path) == 0:' '        if False:' \
  tests/schema/test_checker.py tests/schema/test_cli.py
```

### Cover the empty-collection path

When validation lives inside a loop over discovered work (commits, files,
records), write one test where **the collection is empty**. Loop-body
validation does not run zero times "harmlessly" — it does not run at all,
and whatever it was guarding is unguarded.

## Related

This defect is one instance of a pattern this codebase has now documented nine
times: a fix lands at one call site while structurally identical siblings stay
broken. See [[sibling-blindness-fix-survives-review-structural-siblings-stay-broken]]
for the detection procedure, and for why naming the pattern has repeatedly
failed to prevent it.
