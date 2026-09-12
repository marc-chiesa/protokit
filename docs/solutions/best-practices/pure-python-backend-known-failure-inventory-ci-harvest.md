---
title: "Harvest a pure-Python runtime backend's known-failure inventory from CI's own run, key entries to their exact exception, and pin the CI job against every narrowing escape hatch"
date: 2026-09-12
category: docs/solutions/best-practices
module: testing/protobuf-backend-parity
problem_type: best_practice
component: testing_framework
severity: high
applies_when:
  - "Adding CI coverage for a second protobuf runtime backend (pure-Python) after the suite has only run under the default upb backend"
  - "Triaging a batch of new-backend failures where CLI-downstream call sites raise heterogeneous exception types no single per-test marker could name precisely"
  - "A new CI job must stay advisory (continue-on-error) until the failure count reaches zero, and its own configuration needs a guard nobody can quietly narrow"
  - "Deciding whether to harvest the known-failure baseline from CI's own run or from a local reproduction that differs in Python version, OS, or dependency resolution"
  - "Writing a presence-ratchet test over a CI workflow file (yaml.safe_load) to guard job-level configuration such as env vars, step commands, and narrowing flags"
symptoms:
  - "A second-backend run reports on the order of a hundred-plus failures with no per-test marker precise enough to gate on"
  - "CLI-downstream failures surface as AssertionError, JSONDecodeError, or XMLResourceOSError depending on call path, so one exception type can't be pinned per test"
  - "A token-based check for 'the pytest step' matches a harvest step's echo text that merely mentions pytest, not an actual invocation"
  - "A presence ratchet that only checks for a `tests/` subpath still passes a job narrowed with `-k`, `--runxfail`, a step-level backend env override, or working-directory"
  - "A sanity step that prints the resolved backend passes even when nothing in the job actually asserts it"
root_cause: incomplete_implementation
resolution_type: test_fix
related_components:
  - testing_framework
  - tooling
  - development_workflow
tags:
  - cross-backend-testing
  - pure-python-backend
  - known-failure-inventory
  - ci-harvest
  - presence-ratchet
  - xfail
  - regression-pin
  - pytest
---

# Harvest a pure-Python runtime backend's known-failure inventory from CI's own run, key entries to their exact exception, and pin the CI job against every narrowing escape hatch

## Context

The protobuf Python package ships two runtime backends, upb (C, the default)
and pure-Python (`PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python`), and until
PR #59 this suite's CI had only ever expressed upb's opinion: the `test` matrix
in `.github/workflows/ci.yml` resolves protobuf's default backend on every cell
(`.github/workflows/ci.yml:173-174`). Three audit defects (V1, V10, the V9
swallow) rely on an exception only upb raises; under pure-Python each degrades
silently to a wrong value, and nothing exercised that runtime
(`.github/workflows/ci.yml:174-177`). Plan decision KTD6 — backend behaviour is
asserted, never inferred from an exception — needed a second cell that runs the
whole suite under the other backend.

Once the fixture helpers were honest (PR #57; see the sibling learning
`wire-filedescriptorproto-dependency-through-pool-pure-python-vs-upb.md`), the
full suite under pure-Python still failed about 176 tests, almost all on one
product defect the later unit U3 owns (V34: `Descriptor.CopyToProto` on a
pool-built descriptor raises `google.protobuf.descriptor.Error` on that backend;
`CHANGELOG.md:26-30`). Two obvious ways to land the cell did not work:

- **Per-test source markers.** A `@pytest.mark.xfail(..., raises=...)`
  conditional on the backend would have to be written ~176 times, and the
  44 V34 failures that surface downstream of the CLI do so with heterogeneous
  exception types — 34 `AssertionError`, 7 `json.decoder.JSONDecodeError`,
  2 `xmlschema.exceptions.XMLResourceOSError`, 1
  `xml.etree.ElementTree.ParseError` (counted from
  `tests/pure_python_expected_failures.txt` as of PR #59, 2026-09-12) — so no
  single decorator names them precisely, and every one of those markers would
  be deleted again when U3 lands. The session record calls this "mass xfails"
  and rejected it.
- **A plain red job.** `continue-on-error: true` with no expected-failure
  mechanism keeps the workflow green, but the job itself is red on every push
  for the weeks until U3, and a red job cannot say whether *this* PR added a
  failure. It is a guard that guards nothing.

The plan had originally assumed pure-Python would fail only in the
fidelity-probe and pool-building tests and could be covered by per-test
backend-conditional markers; the first live measurement found 263 failures,
most of them the V34 crash inside `protokit compat` itself, and the per-test
route was rejected as "mass xfails" once the volume was known (session
history). The count was re-baselined to 286 before the fixture fixes and the
predicted 286 -> 176 collapse after them was confirmed live (session history).

KTD10 is the third way: the known failures are **data**, a committed inventory
file the cell applies as strict, exception-specific `xfail` markers under the
pure-Python backend only, so the cell is red only on a new failure, on an XPASS
(a fix landed), on a failure whose exception changed, or on a stale entry
(`tests/_pure_python_inventory.py:6-10`). The cell stays advisory
(`continue-on-error: true`, `.github/workflows/ci.yml:211`) until U3 empties the
inventory and U23 promotes it (`.github/workflows/ci.yml:199-207`).

**Harvest run versus merge run.** The inventory's entries are not measured
locally. The cell is Python 3.12 on Linux with apt `protoc` and `.[compiler,dev]`
only (`.github/workflows/ci.yml:219-233`, restated at `CONTRIBUTING.md:44-47`),
and a developer venv differs from it on five axes at once: the Python minor,
the operating system, which optional extras are installed (a local venv may carry
the parquet and hamcrest extras the cell does not), whether a system `protoc`
is present, and — following from the extras — which protobuf the resolver picks.
On this occasion the cell resolved protobuf 5.27.5 because protoxy 0.7.2 pins
`protobuf ~=5.27.2` (its package metadata, checked 2026-09-12; the plan had
assumed 5.29.x), which happened to be the same minor as the local venv, so the
cell's list and the local estimate agreed entry for entry. That agreement is
contingent on the pin, not a rule; what the plan gives you to compare against
is the *count* (176 unlisted -> 0), not the list. (The 176 is the failure count
on the tree before the four permanent backend skips below; three of those four
were failures in that count, the perf smoke already being platform-skipped
locally, which is why the harvest lists 173.) So the workflow is: push a
draft PR with an empty inventory, let the cell's harvest step print every
failure in inventory format, commit that as the inventory, and let the cell run
again. On PR #59 the harvest run reported 173 failed / 40 xfailed against an
empty inventory and the merge run 0 failed / 213 xfailed with the harvest
reporting no unlisted failures (per the PR's run logs). Note that `ci.yml`
triggers only on `pull_request` and `push` to `main`
(`.github/workflows/ci.yml:29-33`): a bare branch push produces no run, so the
harvest needs a PR open.

## Guidance

**Register the inventory as a plugin, not as conftest body.** The hook lives in
`tests/_pure_python_inventory.py` and `tests/conftest.py:11` registers it via
`pytest_plugins = ["tests._pure_python_inventory"]`, so the hook's own tests can
load it into a child session by name (`tests/conftest.py:7-8`). Under upb the
plugin returns before reading the file (`tests/_pure_python_inventory.py:337-338`).

**Prepend the marker so the entry governs ahead of a test's own pin.**
pytest evaluates the *first* `xfail` marker it finds and stops
(`evaluate_xfail_marks` in the installed pytest 9.0.2 package, `_pytest/skipping.py:214-241`); marker
iteration starts at the item's own markers and walks up to class and module
(pytest 9.0.2, `_pytest/nodes.py:294-303` and `_pytest/nodes.py:346-357`), and `add_marker(append=False)` inserts at
index 0 of the item's own list (`_pytest/nodes.py:316-336`). So:

```python
# tests/_pure_python_inventory.py:356-361
# Prepended, so the entry's exception governs ahead of a marker the test
# already carries (a U1 pin): pytest evaluates the first xfail marker.
item.add_marker(
    pytest.mark.xfail(strict=True, raises=entry.raises, reason=_reason(entry, inventory)),
    append=False,
)
```

A U1 audit pin expects, say, `AssertionError`; under pure-Python the same test
dies earlier with `descriptor.Error` inside the fixture. The prepended entry
absorbs the earlier death; when U3 fixes V34 the pin's own exception surfaces as
a `raises=` mismatch on the entry, the entry is deleted, and the test returns to
being an ordinary xfailed pin (`tests/meta/test_pure_python_inventory.py:232-238`
is the child-session scenario).

**Entry format: node id, finding, exception, under a version header.** One
entry per line, whitespace-separated, node id first
(`tests/_pure_python_inventory.py:14-21`, `tests/pure_python_expected_failures.txt:9-20`):

```text
protobuf: 5.27.5
python: 3.12.14
tests/core/test_pools.py::TestBuildPool::test_dangling_symbol_raises_typed_error_not_raw_typeerror V10 pytest.fail.Exception
tests/schema/test_audit_u9_compat_rule_pins.py::test_proto2_default_value_change_is_reported_at_some_level[changed_int] V34,U9-1 google.protobuf.descriptor.Error
tests/schema/test_cli.py::TestJsonOutput::test_json_shape V34 json.decoder.JSONDecodeError
```

The finding column must match `V<n>` optionally followed by pin ids
(`_FINDING_RE`, `tests/_pure_python_inventory.py:79`); the exception column is a
dotted class path, comma-joined for more than one type
(`tests/_pure_python_inventory.py:220`). The parser rejects a header after the
first entry, a line without three columns, a node id without `::`, a duplicate
node id (`tests/_pure_python_inventory.py:202-227`), and entries without a
`protobuf:` header (`Inventory.__post_init__`,
`tests/_pure_python_inventory.py:114-119`). pytest's own outcome exceptions are
spelled publicly (`pytest.fail.Exception`, never a `_pytest` path;
`tests/_pure_python_inventory.py:83-87`).

**Reject catch-all exceptions at load, by identity.** The same rule the source
marker ratchet enforces (`strict-xfail-pin-without-raises-accepts-any-failure.md`)
applies to the data file:

```python
# tests/_pure_python_inventory.py:80,169-174
_CATCH_ALL = (Exception, BaseException)
...
if obj in _CATCH_ALL:
    raise InventoryError(
        f"{spelling!r} is a catch-all raises=; name the specific exception the "
        f"finding raises (the same rule tests/meta/test_xfail_raises_ratchet.py "
        f"applies to source markers)"
    )
```

Because the check is on the resolved class, not the spelling, `Exception`,
`builtins.Exception` and any alias all hit it. The source-marker ratchet compares
spellings and so needed the qualified forms added explicitly
(`_CATCH_ALL_RAISES`, `tests/meta/test_xfail_raises_ratchet.py:54-56`).

**Guard the protobuf major.minor, ignore the patch.** A non-empty inventory
whose header differs from the installed runtime on `major.minor` is one
`pytest.UsageError` naming both versions (`version_mismatch`,
`tests/_pure_python_inventory.py:248-259`, raised at `:346-348`); a patch bump
passes. `--pure-python-inventory-ignore-version` is the exploratory local
opt-out and is never the verification of record
(`tests/_pure_python_inventory.py:29-32`; `CONTRIBUTING.md:39-43`). A runtime
bump therefore forces a loud re-harvest instead of a mis-diagnosed XPASS.

**Key "full suite" on the configured `testpaths`, not on the inventory's
directory.** A listed node id that is not collected is a stale entry only if
the run collected everything. `is_full_suite_run`
(`tests/_pure_python_inventory.py:262-291`) requires no `-k` / `-m` /
`--deselect` / `--ignore` / `--ignore-glob` / `--lf` / `--sw` and that every
positional argument resolve to the tests root or one of its ancestors; the root
is `_tests_root` (`tests/_pure_python_inventory.py:389-398`), which reads
`testpaths` from `pyproject.toml:121`:

```python
# tests/_pure_python_inventory.py:389-398
def _tests_root(config: pytest.Config) -> Path:
    """... Not the inventory's own directory, so ``--pure-python-inventory=/elsewhere``
    cannot turn a stale-entry hard error into a subset warning."""
    testpaths = [str(p) for p in config.getini("testpaths")]
    if len(testpaths) == 1:
        return Path(config.rootpath) / testpaths[0]
    return Path(config.rootpath)
```

On a full run a stale entry is a `pytest.UsageError` listing `path:line` for
each (`tests/_pure_python_inventory.py:364-369`); on a subset run it is a
warning naming only entries whose *module* was collected — the one case a
subset run can distinguish from "not in this subset"
(`tests/_pure_python_inventory.py:370-386`).

**Harvest in every phase, with the exact exception type.** The
`pytest_runtest_makereport` hookwrapper (`tests/_pure_python_inventory.py:407-436`)
writes a line for every failed report the inventory did not absorb — setup and
teardown included, each with a phase comment — plus a distinct `# XPASS(strict)`
line for a listed test that passed and another for an XPASS on a test's own
marker (which the inventory cannot absorb). `spell_exception`
(`tests/_pure_python_inventory.py:138-143`) records the type because the short
test summary strips it from rewritten `assert` failures
(`tests/_pure_python_inventory.py:34-38`). `pytest_sessionfinish`
(`tests/_pure_python_inventory.py:444-470`) writes the file in inventory format,
says explicitly when the session ended with a usage error so an empty harvest
never reads as a clean run (`:455-461`), and writes nothing at all under upb
(`pytest_configure`, `:439-441`). The cell passes
`--pure-python-inventory-harvest=pure-python-harvest.txt`
(`.github/workflows/ci.yml:252`) and an `if: always()` step prints the file and
appends it to the step summary (`.github/workflows/ci.yml:254-273`).

**One spelling for the backend-skip predicate.** A test whose premise is a upb
runtime fact rather than a protokit defect is not an inventory entry; it gets
`skip_under_pure_python(reason)` (`tests/_pure_python_inventory.py:127-132`),
and the reason must name the premise. Four sites as of PR #59:
`tests/core/test_pools.py:68-74` and `tests/storage/test_schema_source.py:62-68`
(a raw `DescriptorPool().Add()` of a file whose dependency is absent raises
eagerly on upb and is accepted lazily by pure-Python — a upb-only premise),
`tests/storage/test_columnar.py:656-662` (pure-Python's pool resolves
dependencies recursively, one frame per import level, so a 1200-deep chain
raises `RecursionError` against the default limit of 1000 before protokit's
iterative walker runs), and `tests/schema/lint/test_perf_smoke.py:138-146` (a
0.5 s threshold calibrated on upb's ~14 ms; pure-Python measured 0.23-0.44 s
locally with no runner headroom; pre-emptive).

**Assert the cell's shape with a presence ratchet, and model every way the step
can run something other than the full suite.**
`tests/meta/test_pure_python_cell_presence_ratchet.py` loads `ci.yml` with
`yaml.safe_load` and `cell_violations` (`:104-181`) returns a checklist. A
ratchet over a CI job must reject all of:

- [ ] more or fewer than exactly one job whose **job-level** `env` sets the
      backend variable (`:113-122`);
- [ ] a renamed job id — the required-checks list names the context (`:124-125`);
- [ ] a different `setup-python` version (`:128-136`);
- [ ] no run step whose command **starts with** `pytest` or `python -m pytest`
      (`_pytest_commands`, `:58-73`; `:138-140`) — a message mentioning pytest
      is not an invocation;
- [ ] a pytest command without `tests/`, or with any `tests/<subpath>` (`:142-148`);
- [ ] any narrowing or escape flag: `-k`, `-m`, `--deselect`, `--ignore`,
      `--ignore-glob`, `--lf`, `--sw`, `--runxfail`, `-p`, `--co`, `-x`,
      `--maxfail`, `--pure-python-inventory=`,
      `--pure-python-inventory-ignore-version`, including attached short forms
      such as `-pno:plugin` (`_NARROWING_PREFIXES`, `:79-91`; `:149-154`);
- [ ] an `if:` or `working-directory:` on the pytest step (`:155-159`);
- [ ] a step-level `env` that re-sets the backend variable (`:160-163`);
- [ ] a sanity step that reads `api_implementation.Type()` but does not
      `assert` it `== 'python'` on some line (`_asserts_pure_python`, `:94-101`;
      `:165-168`);
- [ ] during the advisory phase, a missing `continue-on-error: true` or a
      missing advisory banner (`:170-180`; both flip in U23).

Each property has an injected-violation self-test that mutates a synthetic
workflow and asserts the message names it (`:228-345`; 18 self-test methods,
one parametrised over eleven flags, 28 collected cases as of PR #59), so the
ratchet is proven to fire, not assumed to.

## Why This Matters

Each rule closes a hole an independent falsification pass (a different model,
read-only, briefed to break seven explicit claims) reproduced before merge; a
narrower falsification brief listing explicit claims completed where a
generalist brief had stalled. Stated as "guard X passes while Y is true":

- **The harvest reports "no unlisted failures" while a teardown finalizer is
  red.** pytest's `raises=` filter runs in every phase: the `call.excinfo`
  branch of `pytest_runtest_makereport` has no `call.when` check (pytest 9.0.2,
  `_pytest/skipping.py:289-304`); only the XPASS branch is gated on
  `call.when == "call"` (`:305`). A harvest that inspected only the call phase
  therefore missed setup and teardown failures — and an inventory entry
  silently absorbs a fixture error of the named type. The hookwrapper now
  handles every phase and labels non-call phases
  (`tests/_pure_python_inventory.py:427-430`); the child-session test asserts a
  finalizer's `OSError` is harvested with its phase comment
  (`tests/meta/test_pure_python_inventory.py:281-283` and `tests/meta/test_pure_python_inventory.py:452-455`).
- **The presence ratchet passes while the cell runs `pytest tests/ -k x`, or
  `--runxfail`, or `-p no:tests._pure_python_inventory`.** A check that only
  looked for a `tests/` token with no subpath accepted every flag that narrows
  collection or disables the xfail machinery. `_narrows`
  (`tests/meta/test_pure_python_cell_presence_ratchet.py:86-91`) now rejects
  the list above; the parametrised self-test covers eleven of them (`:297-306`).
- **The ratchet passes while the step has `if: 'false'` or
  `working-directory: tests/core`.** Both leave the command text
  `pytest tests/` intact while the step runs nothing, or runs a subtree
  relative to another directory. Rejected at `:155-159`; self-test `:315-321`.
- **The ratchet passes while a step-level `env` sets the backend back to upb.**
  The job-level env check at `:113-122` is satisfied; the step's own env wins
  at run time. Rejected at `:160-163`; self-test `:323-329`.
- **The ratchet passes while the sanity step merely prints the backend.**
  `print(api_implementation.Type())` contains the fragment the ratchet looks
  for. A runtime that silently fell back to upb would pass the whole suite with
  the inventory unapplied (`.github/workflows/ci.yml:236-240`).
  `_asserts_pure_python` requires an `assert` and `'python'` on one line
  (`:94-101`); self-test `:331-336`; the real step asserts at
  `.github/workflows/ci.yml:247`.
- **The ratchet reads the harvest step's `echo` as a pytest invocation.** A
  token-anywhere detection matched the message at
  `.github/workflows/ci.yml:264` ("pytest did not reach session finish") and
  then flagged it for lacking `tests/`. `_pytest_commands` keys on commands
  that start with `pytest` or `python -m pytest` (`:67-72`); self-test `:280-288`.
- **The source-marker ratchet passes while a pin says
  `raises=builtins.Exception`.** The bare-spelling comparison missed the
  qualified name; `_CATCH_ALL_RAISES` now lists both forms
  (`tests/meta/test_xfail_raises_ratchet.py:51-56`, self-test `:286-292`). The
  inventory loader never had this hole because it checks the resolved class
  (`tests/_pure_python_inventory.py:169`).
- **A stale entry is only a warning while the inventory is passed from
  another directory.** Keying "full suite" on the inventory file's parent let
  `--pure-python-inventory=/elsewhere/x.txt` demote the hard error. `_tests_root`
  keys on `testpaths` (`tests/_pure_python_inventory.py:389-398`); test
  `tests/meta/test_pure_python_inventory.py:504-516`.

Rules the pass could not break, for the record: marker precedence over
function, class and module pins; that the four skips are runtime facts and not
defects; the version-guard semantics.

This was the second time in the same release that a guard mechanism, not the
product code it guards, fell to a falsification pass: the source-marker ratchet
this inventory borrows its discipline from shipped in PR #57 only after an
independent pass had reproduced six bypasses of its first cut (`raises=None`,
`raises=Exception`, two alias spellings, two in-body marker applications)
(session history). A guard is code that can pass while guarding nothing, and
it earns the same adversarial review as a fix.

Residual risks recorded on PR #59, accepted by design: `--runxfail` and
`-p no:skipping` are pytest escape hatches the cell never passes (and the
ratchet rejects them on the command); a *new* failure of the same exception
type on a listed test is absorbed — inherent to `raises=`-typed xfail and the
reason entries name `descriptor.Error` rather than `AssertionError` where the
failure allows; a listed test that is skipped under pure-Python sits
unverified; one stale entry aborts the whole cell until edited; the cell's
protobuf line is pinned indirectly through protoxy; and
`tests/storage/test_columnar.py` is `importorskip`ped in the cell (no parquet
extra, `tests/storage/test_columnar.py:16`), so its backend skip matters only
locally.

## When to Apply

- Adding a second runtime, backend, platform or interpreter cell over a suite
  that has only ever run on one, and the new cell fails in the tens or
  hundreds on defects a later unit owns.
- Any expected-failure list applied by a hook rather than by source markers:
  the list needs a version header and guard, exception-specific entries with
  catch-alls rejected at load, prepend-over-own-marker precedence, and a
  stale-entry error keyed on a full-suite predicate.
- Any presence ratchet over a CI workflow job: the checklist above is the
  minimum set of ways a step can look present while running something else.
- Any harvest of expected failures from a run: harvest from the cell's own
  log, in the file's own format, with the exact exception type, across setup,
  call and teardown, and with an explicit note when the session did not
  complete.
- Deciding between an inventory entry and a permanent backend skip: an entry
  is a protokit defect a fix will flip to XPASS; a skip is a runtime fact
  (eager versus lazy resolution, a recursion limit, a timing budget) whose
  reason names the premise.

## Examples

**An inventory line and the marker it becomes.** The line

```text
tests/schema/test_audit_u9_compat_rule_pins.py::test_proto2_default_value_change_is_reported_at_some_level[changed_int] V34,U9-1 google.protobuf.descriptor.Error
```

is parsed into an `Entry` whose `raises` is `(google.protobuf.descriptor.Error,)`
(`tests/_pure_python_inventory.py:220` and `tests/_pure_python_inventory.py:228`) and, under pure-Python only, the
item gets

```python
pytest.mark.xfail(
    strict=True,
    raises=(google.protobuf.descriptor.Error,),
    reason="pure-Python known failure V34,U9-1: listed in "
           "tests/pure_python_expected_failures.txt; delete the entry once it XPASSes",
)
```

inserted *before* the test's own `@pytest.mark.xfail(strict=True,
raises=AssertionError, reason="U9-1 ...")` pin (`:327-331,356-361`). Under upb
the file is never opened and the pin stands alone.

**Presence-ratchet check, before and after.** Detecting the pytest step by a
token anywhere in the script, versus by the command's first tokens:

```python
# before (falsified: matched the harvest step's echo at ci.yml:264)
pytest_steps = [s for s in steps if "pytest" in (s.get("run") or "")]

# after: tests/meta/test_pure_python_cell_presence_ratchet.py:67-72
for line in run.replace("\\\n", " ").splitlines():
    tokens = line.split()
    if tokens[:1] == ["pytest"]:
        commands.append(tokens)
    elif tokens[:3] == ["python", "-m", "pytest"]:
        commands.append(tokens[2:])
```

Checking only that the path is `tests/` with no subpath, versus also rejecting
narrowing flags, conditions, relocation and a step-level env:

```python
# before (falsified: passed `pytest tests/ -k x`, `--runxfail`, `if: 'false'`,
# `working-directory: tests/core`, and a step-level env: {BACKEND: upb})
if not any(t in ("tests", "tests/") for t in tokens) or any(
    t.startswith("tests/") and t != "tests/" for t in tokens
):
    violations.append(...)

# after: the same check, plus tests/meta/test_pure_python_cell_presence_ratchet.py:149-163
narrowing = [t for t in tokens if _narrows(t)]
if narrowing: violations.append(f"... must not narrow or escape the run; it passes {narrowing!r}")
if "if" in step or "working-directory" in step: violations.append("... unconditionally from the checkout root")
if BACKEND_ENV in (step.get("env") or {}): violations.append("... must not override ... at step level")
```

**A harvest excerpt.** The child-session scenario in
`tests/meta/test_pure_python_inventory.py:433-459` produces, in the shape
`pytest_sessionfinish` writes (`tests/_pure_python_inventory.py:450-469`):

```text
# pure-Python known-failure harvest (tests/_pure_python_inventory.py).
# Name each UNTRIAGED finding (V<n>, plus the U<n>-<m> pin id where the test
# carries one) and add the line to tests/pure_python_expected_failures.txt.
protobuf: 5.27.5
python: 3.12.14
# XPASS(strict): test_scenario.py::test_listed_passes -- delete its inventory entry
# raises= mismatch: the entry names KeyError
test_scenario.py::test_listed_wrong_type V34 ValueError
test_scenario.py::test_unlisted_fails UNTRIAGED RuntimeError
# raised during setup, not the test body:
test_scenario.py::test_unlisted_setup_error UNTRIAGED LookupError
# XPASS(strict) on a marker of its own: test_scenario.py::test_own_pin_xpasses -- the inventory cannot absorb an XPASS; gate that pin on the backend or land its fix
# raised during teardown, not the test body:
test_scenario.py::test_unlisted_teardown_error UNTRIAGED OSError
```

Replacing `UNTRIAGED` with a finding id makes each line a valid entry; the test
round-trips the triaged text through `parse_inventory` (`:461-465`). When the
session aborted instead, the file carries
`# session ended with USAGE_ERROR: the run did not complete, so nothing was harvested; see the job log`
and no version header (`tests/_pure_python_inventory.py:455-461`).

## Related

- `docs/solutions/best-practices/strict-xfail-pin-without-raises-accepts-any-failure.md`
  — the `raises=` discipline for source markers (PR #57); this learning applies
  the same rule to a data file and shows why a catch-all check on the resolved
  class beats one on spellings.
- `docs/solutions/best-practices/wire-filedescriptorproto-dependency-through-pool-pure-python-vs-upb.md`
  — the fixture fixes that had to land first so the inventory counts product
  defects rather than helper deaths; also where the 176 figure comes from.
- `docs/solutions/best-practices/sibling-blindness-fix-survives-review-structural-siblings-stay-broken.md`
  — the ratchet checklist above is the same defence applied to a CI step: derive
  the set of ways it can misbehave from the mechanism, not from the case that
  was reported.
- `docs/solutions/best-practices/presence-ratchet-test-pattern-for-prose-substrings-2026-05-14.md`
  — the presence-ratchet pattern and its banner-pin rule that
  `ADVISORY_BANNER` follows.
- `docs/solutions/best-practices/presence-ratchet-pin-canonical-not-local-form-2026-05-23.md`
  — pin the canonical form; here the canonical form of "runs the full suite" is
  a command that starts with `pytest` over `tests/` with nothing narrowing it.
- `docs/solutions/best-practices/pytest-static-analysis-gate-ratchet-2026-05-02.md`
  — the `yaml.safe_load` workflow-inspection shape this ratchet reuses.
- `docs/solutions/best-practices/docs-code-drift-defense-convention-2026-06-13.md`
  — why the moving targets in this document (the protobuf line, pytest's phase
  semantics, the entry counts) each carry an inline provenance or current-state
  marker.
- `CONCEPTS.md` defines **Known-failure inventory** alongside Regression pin,
  Presence ratchet, Sibling blindness, Runtime backend and Compile backend: a
  committed, versioned list of expected failures a hook applies as strict
  exception-specific xfails under one backend, distinct from a regression pin
  (per-test, in source, permanent until the fix) and from a presence ratchet
  (guards that the mechanism exists).
