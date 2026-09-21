---
title: "A trust boundary with three enforcement points was fixed at two, because the finding named a symptom"
date: 2026-09-20
category: docs/solutions/security-issues
module: protokit.schema
problem_type: security_issue
component: tooling
severity: critical
symptoms:
  - "`compat check` on a removed-field pair exits 1 INCOMPATIBLE, but exits 0 with empty stdout AND empty stderr once a `--compat-rule-pack` whose rule function calls `sys.exit(0)` is loaded"
  - "The same silent exit 0 on all four checker-running subcommands: `check`, `ci`, `history`, `bisect`"
  - "`_load_rule_packs` guards pack import and `RULES` iteration and its docstring says 'both boundaries', but the per-rule dispatch in `SchemaChecker` still caught bare `except Exception`"
  - "`issubclass(SystemExit, Exception)` is False, so the dispatch guard was blind to it by construction"
  - "The corrective pattern already existed unread in three sibling surfaces, decided between 2026-04-19 and 2026-05-07"
root_cause: incomplete_implementation
resolution_type: code_fix
related_components: [development_workflow, testing_framework]
tags:
  - systemexit
  - baseexception
  - trust-boundary
  - plugin-system
  - exit-code
  - sibling-blindness
  - rule-pack
  - ci-gate
---

# A trust boundary with three enforcement points was fixed at two, because the finding named a symptom

> **Citation note.** Line numbers are current-state as of PR #76 (2026-09-20)
> and will drift; each is paired with a greppable anchor so the citation
> self-heals. Every behavioural claim below was re-run against the tree at that
> merge — the pre-fix transcripts are from a `git archive` export of the commit
> before #76 landed, run with `PYTHONPATH` pointed at that copy, not from
> memory.

## Problem

`protokit compat` executes user-supplied rule packs — arbitrary third-party
Python, named by dotted module path on `--compat-rule-pack` — in-process while
it builds a compatibility report. That trust boundary has **three** enforcement
points, not one: the pack's **import**, the iteration of its **`RULES`**, and
the per-rule **dispatch** call made while the descriptor tree is walked. The
audit finding was recorded as *"a rule pack calling `sys.exit(0)`"* — a symptom
at one site — so the fix went to the two points inside `_load_rule_packs` and
left the third catching a bare `except Exception`, which `SystemExit` (a
`BaseException`, not an `Exception`) walks straight through and into the
process exit code.

## Symptoms

A rule *function* that calls `sys.exit(0)` turned a breaking schema into a
silent pass on every `compat` subcommand. Reproduced against the tree one
commit before #76, with a pair whose only change is a removed field and a pack
whose single rule is `def suicidal(ctx): sys.exit(0)`:

```console
$ protokit compat check --proto old.proto new.proto --type acme.Thing
protokit compat — level: CONSUMER_SAFE, 1 finding(s)
  [SEMANTIC/BACKWARD] count: field present in old schema, absent in new (field_removed)

INCOMPATIBLE
$ echo $?
1

$ protokit compat check --proto old.proto new.proto --type acme.Thing \
    --compat-rule-pack suicidal_pack
$ echo $?
0
```

The second invocation printed **nothing at all** — empty stdout *and* empty
stderr. Not a traceback, not a warning, not the finding it had already
computed. The same shape on the other three subcommands, each against its own
control:

| invocation | control (no pack) | with the exiting rule |
| --- | --- | --- |
| `compat check --proto OLD NEW` | 1, `INCOMPATIBLE` | **0**, empty stdout + stderr |
| `compat history --range HEAD~1..HEAD` | 1, `… BROKEN (1 finding(s))` | **0**, empty stdout + stderr |
| `compat bisect --old HEAD~1 --new HEAD` | 1 | **0**, empty stdout + stderr |
| `compat ci --base HEAD~1` | 1 | **0**, empty stdout + stderr |

Against the ladder this CLI documents in its own module docstring — `0` ran and
found nothing, `1` ran and found a problem, `2` could not run
(`src/protokit/schema/cli.py:15-19`, anchor `Exit codes (uniform across
subcommands)`) — that is the worst cell in the table: a gate that stopped
gating and reported the code reserved for "clean". Nothing distinguishes it
from a healthy pass; a CI job greps stderr and finds silence.

The vector is not only adversarial. A pack that imports a shared org helper
whose module body early-outs with `sys.exit(0)` when a feature flag is off
produces exactly this — an environment-conditional silent gate — which is the
form the load-time half of this finding was originally written up with
(`tests/schema/test_audit_u15_cli_exit_pins.py:323-349`).

## What Didn't Work

The first fix hardened `_load_rule_packs` (`src/protokit/schema/cli.py:147`)
and stopped there. It named `SystemExit` at the import
(`src/protokit/schema/cli.py:200`) and at `checker.load_rule_pack`
(`src/protokit/schema/cli.py:212`), added the `KeyboardInterrupt` arm at both
(`:195`, `:207`), and shipped a docstring that reads, accurately:

> A rule pack is arbitrary third-party Python, so both boundaries catch
> broadly and translate to exit 2 -- "the tool could not run"
> — `src/protokit/schema/cli.py:150-151`

Three things made that read as complete.

**The finding's wording scoped the search.** "A rule pack calling
`sys.exit(0)`" names a *pack*; a pack is a module; a module is imported — so
the reading walks to the import site and stops there. The boundary's real
description is "every point at which code we did not write runs inside our
process while this report is being built", and only that phrasing makes the
per-rule call a member of the set. Nothing was skipped: the third site was
never enumerated, because the enumeration was taken from the report instead of
from the code.

**"Both boundaries" is true of the function and false of the boundary.** The
docstring is still in the tree and still correct — `_load_rule_packs` has
exactly two — and an exhaustive enumeration *inside* one function reads like an
exhaustive enumeration of the surface. Written down where facts go, it also
blocked the next reader from re-deriving the set. Prose that counts sites is
load-bearing in a way prose that describes behaviour is not: it should name the
scope it counts over ("this function's two", not "both boundaries").

**The load surface had just been audited hard.** The same change also fixed
`KeyboardInterrupt` at both load points and widened the `RULES` guard from
`(AttributeError, TypeError)`, so three defects had been found and closed at
that surface in one pass. A surface that has just yielded three findings feels
finished, and that feeling was the confidence that skipped the third site. This
is the corpus's **sibling blindness** in its purest form — and it survived
inside the very unit whose stated goal is that no command exits 0 on a run that
did not complete.

What caught it was an independent pre-merge review pass, which recorded it as a
P0 and reproduced it — not the author, and not the suite, which stayed green
because no test then reached the dispatch site at all. That record is in #76's
own body.

## Solution

Name `SystemExit` at the dispatch guard too, from a module-level tuple that
explains itself.

**Before** — both dispatch guards, `src/protokit/schema/checker.py`:

```python
try:
    result = plugin_fn(ctx)
except Exception as exc:
    self._record_plugin_failure(rule_id, exc, path, warnings_sink)
    return
```

**After** — `src/protokit/schema/checker.py:112-115` (anchor
`_PLUGIN_DISPATCH_EXCEPTIONS`), used at `:787` in `_dispatch_field_plugin` and
`:830` in `_dispatch_message_plugin`:

```python
_PLUGIN_DISPATCH_EXCEPTIONS: tuple[type[BaseException], ...] = (
    SystemExit,
    Exception,
)
```

```python
try:
    result = plugin_fn(ctx)
except _PLUGIN_DISPATCH_EXCEPTIONS as exc:
    self._record_plugin_failure(rule_id, exc, path, warnings_sink)
    return
```

`_record_plugin_failure` (`src/protokit/schema/checker.py:875`) widened its
parameter from `exc: Exception` to `exc: BaseException` (`:877`) — the type
that made the old guard's ceiling explicit in the signature, and the one line
of the fix a type checker would otherwise have argued about.

The comment above the tuple (`src/protokit/schema/checker.py:90-111`) carries
the whole reason, including the half that is a *divergence*: `KeyboardInterrupt`
is deliberately not in it, because dispatch runs mid-walk while the operator is
watching, so a Ctrl-C there is the operator's and must keep propagating —
whereas at *load* time an interrupt comes from the pack's own module body,
which is why `_load_rule_packs` catches it. Same class, opposite decisions,
both written down at their own site.

**This decision already existed three times in this repo**, which is the part
worth keeping. Lint's engine has had it since 2026-05-02:

```python
# Engine-stage exception tuple. Catching ``SystemExit`` is a deliberate
# divergence: ``LintEngine.run`` is a library call that returns a
# ``LintReport``; a rule calling ``sys.exit(0)`` must NOT silently
# terminate the caller's process and produce zero findings. Rule authors
# who legitimately want to abort the run raise an Exception subclass NOT
# in this tuple — ``RuntimeError`` is the canonical choice […]
_RULE_EXCEPTION_TUPLE: tuple[type[BaseException], ...] = (
    SystemExit,
    ValueError,
    …
)
```
— `src/protokit/schema/lint/engine.py:321-352`, `SystemExit` first at `:345`,
applied at the single dispatch owner `LintEngine._invoke_rule`
(`:1394`, guard at `:1406-1408`).

The formatter dispatch decided the same way earlier still, in the module the
compat CLI imports from: `except SystemExit` before `except Exception` around
`output = fn(report, ctx)` (`src/protokit/_cli_utils.py:964-971`), the fix from
[formatter-systemexit-exit-code-bypass-2026-04-19](formatter-systemexit-exit-code-bypass-2026-04-19.md).
Lint's *pack loader* decided the third time in
[keyboardinterrupt-baseexception-bypass-rule-pack-load-2026-05-07](keyboardinterrupt-baseexception-bypass-rule-pack-load-2026-05-07.md).
Compat's dispatch was the one holdout, four and a half months later.

**After the fix**, the same invocation:

```console
$ protokit compat check --proto old.proto new.proto --type acme.Thing \
    --compat-rule-pack suicidal_pack
protokit compat — level: CONSUMER_SAFE, 1 finding(s)
  [SEMANTIC/BACKWARD] count: field present in old schema, absent in new (field_removed)
  ! count: schema plugin 'suicidal' raised SystemExit: 0
  ! name: schema plugin 'suicidal' raised SystemExit: 0

INCOMPATIBLE
$ echo $?
2
```

with the same two lines on stderr as `Error:` diagnostics. `history` renders
the same facts as `INCOMPLETE: the walk cannot be trusted:` and exits 2. The
schema's real verdict is still printed; what changed is that the run no longer
claims to have finished.

Pinned by `test_rule_function_calling_sys_exit_does_not_forge_exit_0`
(`tests/schema/test_audit_u15_cli_exit_pins.py:870`) for `check`, and by
`test_rule_function_sys_exit_is_exit_2_on_the_walking_subcommands` (`:917`),
parametrized over `history` and `bisect` — all four route through
`_build_configured_checker` and `checker.check`, so the hole was never a
`check`-only defect.

## Why This Works

**`SystemExit` is a `BaseException`.** `issubclass(SystemExit, Exception)` is
`False`, so `except Exception` is blind to it by construction, not by accident.
Uncaught at dispatch it unwound past the guard, past `src/protokit/schema/cli.py`'s
`except ValueError`, past Click's `standalone_mode` (which traps only
`ClickException` and `Abort`), and *became* the process exit code with the
pack's own value. Nothing printed because nothing failed: the interpreter was
doing exactly what `sys.exit(0)` asks for.

**An error diagnostic is the right shape, not a hard stop.** `check()` is a
library call that returns a `CompatibilityReport`; its contract is to report,
not to terminate. So the crash is recorded on the report as a `Diagnostic` at
`level="error"` (`src/protokit/schema/checker.py:875-904`), and the exit code
is derived from the report afterwards. `protokit._trust` is the single-owner
seam for "can this report be read as success?" — `_compat_signals`
(`src/protokit/_trust.py:197-198`) makes every error diagnostic a reason, and
`is_trustworthy` (`:457-469`) is false while any reason exists — and the CLI's
gate reads it: `if not _trust.is_trustworthy(report) or report.diagnostics:`
(`src/protokit/schema/cli.py:828`; the same shape at `:1445` and `:1692` for
`history` and `bisect`). One crashed rule therefore produces exit 2 *through
the report*, with no second predicate growing beside the seam, and library
callers see the same fact on `report.diagnostics` without a CLI in the picture.

The alternative — re-raising, or calling `error_exit` from inside the checker —
would have thrown away the verdict the walk had already computed and handed the
third-party rule a different kind of control over the process. Recording it
keeps both: the finding is still rendered, and the run still refuses to be read
as success.

**What it does not cover, and the code says so.** The guards catch
*exceptions*. A pack calling `os._exit` takes the process down with its own
code and no Python-level guard can see it; `os.write(1, …)` still reaches the
real stdout because `redirect_stdout` only rebinds `sys.stdout`. Both limits
are stated at their sites (`src/protokit/schema/cli.py:152-154` and
`:347-357`), having been found by a cross-model falsification pass against
docstrings that had implied otherwise. Closing that class means running packs
out of process.

One consequence worth expecting: dispatch is per descriptor, so a single
exiting rule yields one diagnostic per field it was dispatched on (two, in the
transcript above). That is the honest count of failed dispatches, not a bug,
but it means the diagnostic list is not a list of distinct causes.

## Prevention

### 1. Derive the site set from the code, never from the report's wording

A defect description names a symptom. The fix has to be scoped to the
**boundary**, and the boundary is a question you can grep: *where does code we
did not write run inside our process?* Two greps answer it here, and both are
structural — they anchor on the ingredient every site must contain, not on the
symptom you just fixed:

```console
$ grep -rn "importlib.import_module" src/protokit/ | grep -v '``'
src/protokit/_cli_utils.py:726:            module = importlib.import_module(name)
src/protokit/schema/cli.py:194:            module = importlib.import_module(name)
src/protokit/schema/lint/_cli_utils.py:534:        module = importlib.import_module(module_name)

$ grep -rn "plugin_fn(ctx)\|rule_fn(\|_invoke_rule\|fn(report" src/protokit/ | grep -v "def \|#"
src/protokit/_cli_utils.py:964:            output = fn(report, ctx)
src/protokit/_trust.py:388:                    s._replace(text=one_line(s.text)) for s in fn(report)
src/protokit/schema/checker.py:598:                findings.extend(rule_fn(old_m, new_m, path))
src/protokit/schema/checker.py:662:                findings.extend(rule_fn(old_fd, new_fd, field_path))
src/protokit/schema/checker.py:675:                    findings.extend(rule_fn(
src/protokit/schema/checker.py:736:            findings.extend(rule_fn(old_value, new_value, value_path))
src/protokit/schema/checker.py:747:                findings.extend(rule_fn(
src/protokit/schema/checker.py:786:            result = plugin_fn(ctx)
src/protokit/schema/checker.py:829:            result = plugin_fn(ctx)
src/protokit/schema/lint/engine.py:1322:            self._invoke_rule(spec, ctx)
src/protokit/schema/lint/engine.py:1327:                self._invoke_rule(spec, ctx_svc)
src/protokit/schema/lint/engine.py:1333:                    self._invoke_rule(spec, ctx_m)
src/protokit/schema/lint/engine.py:1351:            self._invoke_rule(spec, ctx)
src/protokit/schema/lint/engine.py:1360:                self._invoke_rule(spec, ctx_val)
src/protokit/schema/lint/engine.py:1372:            self._invoke_rule(spec, ctx)
src/protokit/schema/lint/engine.py:1377:                self._invoke_rule(spec, ctx_f)
src/protokit/schema/lint/engine.py:1382:                self._invoke_rule(spec, ctx_o)
```

The grep returns candidates to triage, not a site list: `_trust.py:388` calls
this repo's own signal function, and the eight `engine.py` lines all funnel into
one owner. What is left after triage is the boundary. Run against the tree
before the fix, the same grep returns the two `plugin_fn(ctx)` lines that the
finding's wording never pointed at. **If the count surprises you, your model of
the surface is wrong, and that is the finding.**

It also shows the structural difference between the two subsystems. Lint funnels
eight dispatch call sites through **one** owner, `_invoke_rule`
(`src/protokit/schema/lint/engine.py:1394`), so its guard is a place. Compat
dispatches from seven sites in one file and guards two of them. Where a boundary
is a set rather than a single owner, every future guard has to be applied N times
and the N is not written down anywhere — which is the standing argument for
giving compat's third-party dispatch **one owner** as well.

Note the deliberate wording: one owner, not a *seam*. This project reserves
"seam" for an owner that also sits at layer 0, importing nothing from the rest
of the package — which is what makes it safe for every layer above to import.
Compat's dispatch owner would live inside the checker and could not satisfy
that. Single-ownership and layer-0-ness are separable, and only the first is
what this argument needs.

**A live instance of exactly this, as of 2026-09-20 (current-state — verified
by the reproduction below against the tree at #76).** Five of compat's seven
rule-invocation sites — the *raw return-style* rules at
`src/protokit/schema/checker.py:598`, `:662`, `:675`, `:736`, `:747` — are
wrapped in no `try` at all, so any exception from such a rule leaves `check()`:

```python
>>> c = SchemaChecker()
>>> c.register_raw_field_rule("raw-suicidal", lambda o, n, p: sys.exit(0))
>>> c.check(old_pool, "acme.Thing", new_pool, "acme.Thing")
# SystemExit(0) escapes check(); the calling process exits 0.
```

This is **not** reachable through `--compat-rule-pack`: `load_rule_pack`
registers pack entries as emit-style field *plugins* only
(`src/protokit/schema/checker.py:287-288`), so the shipped claim that a rule
pack can no longer decide the exit code holds as written. It is reachable
through documented public API — `register_raw_field_rule` and its enum/message
siblings (`src/protokit/schema/checker.py:294`, `:315`, `:326`), described in
the module docstring as "advanced users can register here too"
(`:15-18`) — by any consumer embedding protokit. Recorded here as an open
observation with its reproduction, not as a claim about #76's scope; the
blast radius of a boundary follows the API surface, never the reporter's entry
point.

### 2. Ask whether a sibling subsystem already decided

Before writing a guard on a third-party boundary, check whether the repo has
already answered the same question elsewhere:

```console
$ grep -rn "except SystemExit\|SystemExit," src/protokit/
```

Here it returns the formatter dispatch (`src/protokit/_cli_utils.py:965`),
lint's engine tuple (`src/protokit/schema/lint/engine.py:345`) and lint's pack
loader — three prior decisions, one of them in the very module
`src/protokit/schema/cli.py` imports its `error_exit` from. When a sibling has decided,
either copy the decision **together with its comment**, or write down why this
surface differs. Compat's tuple does the second for `KeyboardInterrupt`, and
that paragraph (`src/protokit/schema/checker.py:103-111`) is what stops the
next reader from "fixing" the omission.

The signal generalises: two subsystems that both run third-party rules are the
same problem twice. Whenever a project has a plugin surface in more than one
place, a fix to one is a question to ask of the others *in the same change*.

### 3. Re-run the mutation proof for neighbouring tests, not just the new one

A fix that stops an exception escaping changes the control flow every
neighbouring test depends on. In this change, a separate defect — captured
rule-pack stdout being dropped when the wrapped call raised, because the drain
loop sat after the `with` block instead of in a `finally` — had a regression
test whose rule printed and then called `sys.exit(0)`. Once dispatch caught
`SystemExit`, that exception no longer escaped, the `with` block exited
normally, the old drain ran, and **the test could no longer fail even with the
stdout bug reintroduced.**

Demonstrated by re-introducing the drain bug (drop the `try`/`finally` at
`src/protokit/schema/cli.py:367-373`) and running each lever:

| lever a rule uses | drain bug present | verdict |
| --- | --- | --- |
| `print(...)` then `sys.exit(0)` | line still re-emitted on stderr, exit 2 | test passes — **vacuous** |
| `print(...)` then `raise KeyboardInterrupt` | line dropped entirely, exit 1 `Aborted!` | test fails — non-vacuous |

The fix was to move the lever to the one exception dispatch still lets escape
**by design**, and to say so in the test:

```python
def _noisy_then_interrupted_rule(ctx):
    """A rule that prints and then takes the process down.

    ``KeyboardInterrupt`` is the one thing a rule can raise at dispatch
    time that still escapes ``checker.check`` after the ``SystemExit``
    fix below — deliberately, since at dispatch time (unlike load time)
    an interrupt is the operator's. That makes it the only lever left
    for proving the stdout drain survives an exception.
    """
    print("PACK-LINE: about to be interrupted")
    raise KeyboardInterrupt
```
— `tests/schema/test_audit_u15_cli_exit_pins.py:857-867`, used by
`test_rule_pack_stdout_survives_a_failing_check` (`:1000`), whose own docstring
records the interaction (`:1011-1017`).

Three rules come out of this:

- **After landing a fix, re-run the mutation proof for every test that shares
  the fixed code path**, not only for the test the fix was written with. A
  proof run *before* the fix is evidence about a tree that no longer exists.
  Use the shared harness so the verdict is a real pytest exit 1 on a target
  that passed unmutated, per
  [mutation-check-harness-stale-bytecode-and-nonverdict-exit-codes-produce-false-verdicts](../logic-errors/mutation-check-harness-stale-bytecode-and-nonverdict-exit-codes-produce-false-verdicts.md).
- **A test that needs an exception to escape must use one the code escapes on
  purpose**, and must say in its docstring which one and why. An exception that
  escapes only because of a bug is a lever that the bug's fix removes.
- **Two fixes in one change can interact.** The interaction here was silent and
  in the safe-looking direction: nothing turned red, a test simply stopped
  being able to.

A note on vocabulary: these are regression tests, not **pins** in this
project's sense — the fixes landed with them, so none is a strict
expected-failure carrying a finding id. That is exactly why the mutation proof
is load-bearing here. A pin proves itself by flipping when the defect is fixed;
a regression test that lands green proves nothing until something shows it can
fail, and "it can fail" is a property of the tree it runs against, not of the
test.

## Limits

One more instance, from writing this document. The first draft of Prevention §1
said lint funnels *nine* dispatch call sites through one owner. It is eight —
caught by the grounding pass that checks a doc's countable claims against the
tree before it is committed, not by the author, who wrote the miscount two
paragraphs below the sentence "if the count surprises you, your model of the
surface is wrong". Counting by eye is the failure this document is about, and
knowing that did not prevent it; the check that ran afterwards did. Treat a
count in prose as a claim needing evidence, including in a document arguing
exactly that.

This is a review-detectable class, not a test-detectable one. The tests added
here convert three found instances into permanently closed ones; none of them
would have located the dispatch site, because the defect *is* the failure to
enumerate it. The greps in Prevention are the part that scales — they return
the raw-rule sites today, which no test in the tree asks about — and the
control that actually found the instance was an independent reviewer reading
the diff and asking where else third-party code runs.
