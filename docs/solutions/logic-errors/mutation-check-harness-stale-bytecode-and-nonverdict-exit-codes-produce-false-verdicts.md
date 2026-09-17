---
title: "The vacuity harness could report a verdict it had not earned: stale .pyc bytecode, non-verdict pytest exit codes, no baseline run, text-mode restore"
date: 2026-09-15
category: logic-errors
module: scripts/mutation_check
problem_type: logic_error
component: testing_framework
severity: high
symptoms:
  - "A same-length mutation applied and restored within one whole-second mtime window leaves a stale .pyc valid for the wrong text: the mutated pytest run can execute the ORIGINAL bytecode (false VACUOUS), and every run after restore can execute the MUTATED bytecode until the file is next touched -- measured 2026-09-14 when a restored differ.py kept raising for an accessor its source no longer called"
  - "Any nonzero pytest exit code was printed as NON-VACUOUS: a missing target file (exit 4), a -k selecting nothing (exit 5), and a mutation that breaks collection (exit 2) all counted as proof"
  - "A pytest target already red on the unmutated source was reported NON-VACUOUS under any mutation, because the harness never ran a baseline pass on the original file"
  - "A CRLF source was restored with LF line endings while the harness's own restore assertion still passed, because the file was handled as text instead of bytes"
  - "A substring-based write check ('new text present, old text absent') rejected any replacement that extends its own anchor -- for example appending an element to _UNMIGRATED -- as a setup failure, so the mutation could not even be verified as landed"
root_cause: logic_error
resolution_type: code_fix
tags:
  - mutation-testing
  - vacuity-harness
  - stale-bytecode
  - pyc-cache-invalidation
  - exit-code-semantics
  - false-non-vacuous
  - baseline-check
  - subprocess-verification
---

# The vacuity harness could report a verdict it had not earned

## Problem

`scripts/mutation_check.py` is the sole evidence behind every "non-vacuous" claim in the verification contract of the unreleased correctness release: it mutates one anchor string, runs a pytest target, restores the file, and prints VACUOUS or NON-VACUOUS (`scripts/mutation_check.py:2-44`). For most of 2026-09-14 the harness itself could report NON-VACUOUS for a test that had never actually been shown failing — from stale `.pyc` bytecode, from a nonzero-but-not-1 pytest exit, from a target that was already red before the mutation ever ran, or from a restore that silently rewrote line endings. On a release whose own stated thesis is "a green suite is not evidence" (`docs/solutions/best-practices/sibling-blindness-fix-survives-review-structural-siblings-stay-broken.md`), a harness that can manufacture a false verdict does not just miss one bug — it invalidates every coverage claim made through it until the run is redone, because there is no way after the fact to tell which prior NON-VACUOUS results were earned and which were an artifact of the tool.

## Symptoms

- After proving `left_map = _field_value(left_msg, left_fd)` (`src/protokit/message/differ.py:2157`) against the same-length replacement `left_map = getattr(left_msg, left_fd.name)`, `tests/message/test_extensions.py` stayed **red on the restored, unmutated source**; the traceback pointed at the `_field_value(...)` call with no frame inside the function — the bytecode being executed was still the `getattr` version.
- A mutation applied and restored within the same wall-clock second, with a replacement the same length as its anchor, could make the *mutated* run silently execute the *original* bytecode — a false VACUOUS — while every run after restore kept executing the *mutated* bytecode until something else touched the file.
- A misspelled `-k` selector (pytest exit 5, zero tests collected), a missing target file (exit 4), or a mutation that broke collection (exit 2) all printed `NON-VACUOUS — the target failed under mutation, as it must.`
- A comment-only mutation that no test could ever observe was "proven" NON-VACUOUS whenever the target was already failing for an unrelated reason before the mutation was applied — there was no check that the baseline passed.
- Restoring a CRLF source file passed the restore assertion while the bytes on disk came back as LF.
- The legitimate replacement `return 1` → `return 1 + 1` (a mutation whose text contains its own anchor) was rejected as `SETUP FAILED: mutation not present on disk after write`, blocking the proof from running at all — hit for real proving the seam guard's second drift direction, where appending a module to `_UNMIGRATED` contains the anchor line it appends to.

## What Didn't Work

- **Working around the harness instead of fixing it (session history).** The session that implemented the seam unit on this same branch hit the harness refusing to confirm that a multi-line mutation of `pyproject.toml` had landed, and abandoned it for that case in favour of a hand-written mutate/run/restore script with its own restore path. That kept the proof honest for one case and left the harness's verification logic exactly as it was for every later proof. Across the units that used it before this fix, the harness was invoked dozens of times as settled tooling and no session doubted its verdicts, which is why these defects stayed latent through several shipped units.
- **The substring write check.** The original "did the mutation land" check tested that the new text was present and the old text was absent. That rejects any replacement that extends its own anchor — `return 1` → `return 1 + 1`, or "add one element to this set" — as a setup failure, because the old string is still present as a substring of the new one. It did catch failed writes, but it also refused legitimate mutations outright, which is a different failure mode than a false verdict: it made real proofs impossible to run rather than making them lie.
- **Trusting the exit code.** Treating "pytest exited nonzero" as synonymous with "the target failed" conflates five different pytest exit codes into one meaning. Exit 1 (tests failed) is the only one that says the target ran and observed a failure; exit 2 (interrupted / collection error), 3 (internal error), 4 (usage error — e.g. a missing target file), and 5 (no tests collected — e.g. a `-k` that matches nothing) are all "the run didn't produce a verdict," and each printed NON-VACUOUS anyway.
- **The belief that `-B` alone closes the bytecode hazard.** `-B` (`sys.dont_write_bytecode`) stops the interpreter *running the harness's own pytest invocation* from writing a `.pyc` for the mutated source. It does nothing about a `.pyc` a prior ordinary (non-`-B`) run already cached before the mutation started, and it does not propagate to a grandchild process: a test that shells out to a fresh interpreter (`subprocess.run([sys.executable, ...])`) does not inherit `-B` unless the harness sets `PYTHONDONTWRITEBYTECODE` in the environment, so that grandchild can cache the *mutated* source and that cache survives the restore. `-B` closes the in-process write path; it does not close the pre-existing-cache or grandchild-write paths.

## Solution

Four independent checks now compose, current as of the tip of branch `fix/u3-fieldview-seam` (three commits on that branch; the PR was pending as of this writing).

**Drop bytecode before *and* after, for every cache location, run pytest with `-B`:**

```python
# scripts/mutation_check.py:58-72
def _drop_bytecode(source: pathlib.Path) -> None:
    cache = pathlib.Path(importlib.util.cache_from_source(str(source)))
    candidates = {cache}
    candidates.update(cache.parent.glob(f"{source.stem}.*.pyc"))
    candidates.update(source.parent.glob(f"__pycache__/{source.stem}.*.pyc"))
    for pyc in candidates:
        pyc.unlink(missing_ok=True)
```

`_drop_bytecode` is called before the baseline run, again after the mutated write (`scripts/mutation_check.py:117`, `:137`), and again in the `finally` block after restore (`:157`). `_run_pytest` invokes `.venv/bin/python -B -m pytest ...` (`scripts/mutation_check.py:75-85`). `cache_from_source` names this interpreter's cache file and honors `PYTHONPYCACHEPREFIX`; the two globs beside it catch every other interpreter tag and pytest's own assertion-rewrite caches, and the default `__pycache__` location even when this interpreter caches under a prefix.

**Baseline run before trusting any mutated result:**

```python
# scripts/mutation_check.py:115-126
_drop_bytecode(p)
baseline = _run_pytest(targets)
if baseline is None:
    print(f"SETUP FAILED: baseline run timed out after {TIMEOUT_SECONDS:.0f}s")
    return 1
if baseline.returncode != 0:
    print(_tail(baseline))
    print(f"\nSETUP FAILED: target is not green on the unmutated source "
          f"(pytest exit {baseline.returncode}); a proof needs a passing baseline")
    return 1
```

**Only exit 1 is a verdict:**

```python
# scripts/mutation_check.py:144-151
if result.returncode == 0:
    print("\nVACUOUS — the target passed with the code broken.")
    return 1
if result.returncode != 1:
    print(f"\nSETUP FAILED: pytest exited {result.returncode} under mutation "
          "(1 = tests failed; 2 = interrupted, 3 = internal error, "
          "4 = usage error, 5 = no tests collected): not a verdict")
    return 1
```

**Bytes in, bytes out, with the write and the restore both verified against disk, not against an in-memory string:**

```python
# scripts/mutation_check.py:98-99, 128-135, 154-158
original = p.read_bytes()
...
p.write_bytes(mutated)
if p.read_bytes() != mutated:
    print("SETUP FAILED: mutation not present on disk after write")
    return 1
...
finally:
    p.write_bytes(original)
    assert p.read_bytes() == original, f"FAILED TO RESTORE {path}"
    _drop_bytecode(p)
```

The write-landed check compares the re-read bytes to the intended mutated bytes by equality (`scripts/mutation_check.py:133`), not by "new text present, old text absent," so a replacement that contains its own anchor — the substring check's hole — is accepted.

## Why This Works

CPython's timestamp-based `.pyc` validation is coarser than it looks. Verified against CPython's standard library as installed in the project venv (3.13.5), in the interpreter's own module `importlib._bootstrap_external` (not a file in this repository): `SourceFileLoader.path_stats` reports `{'mtime': st.st_mtime, 'size': st.st_size}` (`:1233-1236`), and the timestamp-loader path truncates that to `source_mtime = int(st['mtime'])` before comparing (`:1116`) — sub-second precision is discarded. `_validate_timestamp_pyc` then accepts a cached `.pyc` whenever its stored 32-bit mtime and size fields match (`:730-756`); there is no content hash in this path. So a same-length replacement, applied and restored inside one wall-clock second, is invisible to the cache-validity check in both directions — which is exactly the mechanism behind the `_field_value` / `getattr` false-negative.

Each new check closes one hole created by that fact, and together they don't depend on it not recurring:

- **Dropping the cache before and after, with `-B` in between**, removes the only artifact the mtime/size check can accept in place of the real source — regardless of clock resolution. `-B` stops this process from writing a fresh one during the mutated run; the post-restore drop is what catches a `.pyc` a grandchild interpreter wrote, since a subprocess spawned by a test doesn't inherit `-B` (pinned by `test_grandchild_bytecode_does_not_survive_restore`, below).
- **The baseline run** establishes the counterfactual: a target must be shown green *before* mutation for its later failure to be attributable *to* the mutation, rather than to something already broken.
- **Exit-code classification** matches pytest's own contract — 1 means "tests ran and failed," nothing else does — so a setup problem (missing file, empty selection, broken collection) can no longer be mistaken for a test catching the mutation.
- **Bytes throughout, with a disk re-read after both the write and the restore**, removes text-mode newline translation as a place where the file that's actually on disk can silently diverge from the string the harness believes it wrote.

## Prevention

- Run every non-vacuity proof **through this harness**, never as a hand-rolled mutate/run/restore script. The four checks compose; a one-off script is highly likely to be missing at least one, and mutation-check bugs are invisible at the call site — the proof just prints a verdict.
- Prefer an anchor/replacement pair of **different lengths** when the mutation allows it — the size field alone then invalidates any stale cache regardless of mtime resolution — but never rely on length alone: the equality-based write check (item above) and the grandchild-bytecode path are orthogonal to length, and plenty of real mutations (e.g. flipping a boolean, changing an operator) are same-length by necessity.
- The regression pins for all of this live in `tests/meta/test_mutation_check_harness.py` and are structural, not timing-based, so they hold regardless of how fast the test machine is: `test_same_length_mutation_leaves_no_bytecode_and_is_still_detected` (`:80-96`, pre-warms a cache of the *original* source before mutating, the exact hazard shape), `test_grandchild_bytecode_does_not_survive_restore` (`:108-127`), `test_replacement_containing_its_anchor_is_a_valid_mutation` (`:99-105`), `test_target_red_on_the_baseline_is_refused` (`:151-159`), `test_nonexistent_target_is_a_setup_failure_not_a_verdict` (`:130-138`), `test_selecting_no_tests_is_a_setup_failure_not_a_verdict` (`:141-148`), `test_a_mutation_that_breaks_collection_is_not_a_verdict` (`:190-203`), `test_restore_preserves_crlf_bytes` (`:162-166`), and `test_timeout_is_a_setup_failure` (`:169-182`).
- **Recognize the stale-bytecode signature if you hit it outside the harness**: a traceback whose failing line names a call that should be inside a function body, but the innermost frame is the *caller*, not the callee — i.e., the line printed doesn't match a frame that actually entered it. That mismatch between "the line pytest says failed" and "the frames that actually ran" is the tell that the source on disk and the bytecode being executed have diverged.
- If a suite goes red (or unexpectedly green) immediately after running a proof — inside or outside this harness — clear `__pycache__` (and any `PYTHONPYCACHEPREFIX` directory) for the touched files before trusting the result.
- A VACUOUS verdict is not automatically a harness defect (session history): a mutation of a predicate that only one Runtime backend exercises is legitimately VACUOUS under the other backend — the resolution probe added for the pure-Python pool is provably vacuous under upb, whose `Add` already raises. Run the proof under the backend the predicate is for (`PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python python3 scripts/mutation_check.py ...`) before concluding anything from VACUOUS.

## Related Issues

- `docs/solutions/logic-errors/subprocess-exit-code-validation-test-harness-2026-05-13.md` is the same mechanism in a different harness: a subprocess wrapper that treated a coarse exit-code/output signal as a verdict instead of enumerating the wrapped tool's actual exit-code contract. Its prevention rules (enumerate the success codes, check the exit code before parsing output, keep a known-bad-input sanity test) are the discipline applied here to pytest's own codes.
- `docs/solutions/best-practices/sibling-blindness-fix-survives-review-structural-siblings-stay-broken.md` names the release's governing finding ("green suites are not evidence") and already carried this exact caveat as unresolved: *"Mutation proof has its own failure mode. `scripts/mutation_check.py` reports `NON-VACUOUS` from a non-zero exit code, so a wrong pytest node id — which collects zero tests — yields a false proof. Verify the collected count in the printed tail before trusting the verdict."* The exit-code classification fix above (on branch `fix/u3-fieldview-seam`, PR pending as of this writing) closes exactly that hole — exit 5 (no tests collected) is now refused as "not a verdict" rather than accepted as NON-VACUOUS — so that caveat no longer applies to the harness as it stands on this branch.
- `docs/solutions/best-practices/strict-xfail-pin-without-raises-accepts-any-failure.md` is the same family from the other direction: a strict `xfail` without `raises=` records a pin as passing (xfailed) when it died for an unrelated reason before reaching its assertion, exactly as this harness could record NON-VACUOUS for a run that never reached a real test verdict. Both are "a green (or green-shaped) signal earned for the wrong reason," and both fixes are the same shape: stop trusting a coarse binary signal (exit code / caught-or-not) and instead require the *specific* expected condition (exit 1 with a passing baseline / a named exception type) before accepting the result as proof.
