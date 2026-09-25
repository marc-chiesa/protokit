---
title: "An import-cycle gate fails open unless its edges model CPython package initialisation and its TYPE_CHECKING guard is read from the typing binding"
date: 2026-09-14
category: docs/solutions/best-practices
module: tests/meta/test_import_layers.py
problem_type: best_practice
component: testing_framework
severity: high
root_cause: incomplete_implementation
resolution_type: test_fix
applies_when:
  - "Writing a meta test that derives a property of the package from source with `ast` instead of from a list someone maintains by hand"
  - "A gate decides an import-graph question (cycles, layering, seam purity) whose ground truth is what CPython does at module load"
  - "The gate must classify `if TYPE_CHECKING:` blocks, deferred function-level imports, or relative imports as edges or non-edges"
  - "A syntactic analysis over-approximates on purpose and the over-approximation needs pinning rather than being left implicit"
  - "A meta test has no `src` anchor for a mutation-testing script, so vacuity has to be proven by self-tests over synthetic packages"
symptoms:
  - "The gate reports zero cycles while a fresh interpreter importing one of the same modules raises ImportError from a partially initialized module"
  - "An edge model counting only the module an import names misses the package `__init__` modules CPython runs on the way to it"
  - "The opposite over-correction, an edge to the package for every from-import, reports a phantom cycle in `protokit.formatters` that the interpreter never hits"
  - "`from typing import TYPE_CHECKING as X` followed by `X = True`, or a binding made only inside a function, hides an import CPython executes"
  - "Wrong implementations of the path-depth rule, bytes parsing, async scopes, `__init__` relative imports, and four guard rules each pass the entire test suite"
related_components:
  - "tooling"
  - "development_workflow"
tags:
  - "cycle-detection"
  - "fail-open"
  - "module-import-time"
  - "type-checking"
  - "package-graph"
  - "ci-gate"
  - "static-analysis"
  - "false-confidence"
---

# An import-cycle gate fails open unless its edges model CPython package initialisation and its TYPE_CHECKING guard is read from the typing binding

## Context

A static import-graph gate is supposed to fail loudly. The failure mode that
matters is the opposite one: the gate prints *no cycle*, CI is green, and a
fresh interpreter importing one of the very modules it just cleared dies with

```
ImportError: cannot import name 'Diagnostic' from partially initialized module
'protokit.message.model' (most likely due to a circular import)
```

That is a fail-open gate — the 0.16.0 correctness programme's theme, applied to
the programme's own tooling. `tests/meta/test_import_layers.py` (U21, PR #61)
is the gate: it asserts `protokit` has zero module-load import cycles, and that
the layer-0 seam modules Wave B hoists shared logic into import nothing from
`protokit` at any scope (`tests/meta/test_import_layers.py:107-123`, asserted at lines 625-636). Every
Wave B unit rests on that property, so the gate is load-bearing for work that
has not landed yet — which makes a gate that silently passes worse than no gate
at all.

Three review rounds on that PR found two distinct shapes where an obvious edge
model fails open, a boundary the syntactic walk cannot cross, and a set of tests
that could not tell a correct implementation from a wrong one. All four are in
the finished file only as consequences: the rules are there, the reasoning that
forced them is not.

**Shape one: the packages CPython initialises on the way in are dependencies.**
`import a.b.c` runs `a/__init__`, then `a/b/__init__`, then `a/b/c`. An edge
model that records only the module the statement *names* misses every cycle
that closes through one of those `__init__` modules. This is not theoretical in
this tree. Appending one ordinary top-level `import protokit.schema.lint` to
`src/protokit/message/model.py` — a plausible line for any future PR to add —
produces:

```
named-module-only rule : no cycle            <- the gate passes
packages-on-path rule  : protokit.message -> protokit.message.model
                         -> protokit.schema -> protokit.message
fresh interpreter      : import protokit.message   rc=1
                         ImportError: cannot import name 'Diagnostic' from
                         partially initialized module 'protokit.message.model'
```

`protokit.schema.lint` itself imports nothing from the package at module load
(`src/protokit/schema/lint/__init__.py` has no package-internal top-level
import), so the named-module-only edge is a dead end. The damage is done by the
parent package on the path: `src/protokit/schema/__init__.py:35` does
`from protokit.message.model import Diagnostic`, and by the time the
interpreter reaches it `protokit.message.model` is half-built. The module the
statement names is innocent; the package on its path is not.

**And the over-correction is just as wrong.** Add an edge to `<pkg>` for every
`from <pkg> import <name>` *on top of* the submodule edge, and the graph grows a
five-module strongly connected component that no interpreter ever trips over:

```
protokit.formatters, protokit.formatters._builtin_bisect,
protokit.formatters._builtin_compat, protokit.formatters._builtin_diff,
protokit.formatters._builtin_history
```

That is ordinary package initialisation.
`src/protokit/formatters/__init__.py:67-74` imports its `_builtin_*` submodules,
and each of those does `from protokit.formatters import _junit_xml as junit`
(`src/protokit/formatters/_builtin_bisect.py:14-15`, and the same pair in
`_builtin_compat.py:18-19`, `_builtin_diff.py:25`,
`_builtin_history.py:15-16`). The from-import resolves through `sys.modules` to
the sibling module, never to the half-constructed package namespace — the
package's own comment says so at
`src/protokit/formatters/__init__.py:59-66`. An earlier audit reported this
shape as a real cycle, and the plan review that specified this unit caught the
naive rule before any code existed: a reviewer ran it against the tree and
returned the five-module `formatters` cycle as an actionable finding, which is
why the submodule rule is in the unit's specification rather than a later fix
(session history). A gate that cries wolf about `formatters` on every PR
gets its assertion deleted, which is the same fail-open outcome by a slower
route.

**Shape two: `TYPE_CHECKING` recognised by spelling is not recognised at all.**
An import under `if TYPE_CHECKING:` never executes, so excluding it is correct
and necessary — the codebase uses exactly that break
(`src/protokit/schema/profiles.py:17` imports `TYPE_CHECKING`, and lines 30-31
gate the plugin import behind it). But "the test is a `Name` whose `id` is `TYPE_CHECKING`" is a
guess about a string, not a fact about the module. Each of these hides an
import CPython really executes: `from typing import TYPE_CHECKING as X`
followed by `X = True`; a `TYPE_CHECKING` rebound after the import; a
`TYPE_CHECKING` bound only inside a function, where the module-level `if` reads
a name that is not there at all.

**Shape three: a syntactic walk has boundaries, and they are invisible.**
`ast` cannot see an import executed through a module-level call, an
`importlib.import_module` string, or a module `__getattr__`. None of those runs
at module load in this tree today — the three `importlib.import_module` call
sites are deferred plugin loading inside function bodies, and there are no star
imports — but "today" is a property of the tree, not of the gate.

**Shape four: nothing tests the test.** Across the review rounds, wrong
implementations passed the entire suite. `scripts/mutation_check.py` proves a
test non-vacuous by mutating the source the test guards and requiring the test
to fail; a meta test has no `src` anchor to mutate, because the code it guards
*is* the test file. Vacuity has to be proven another way.

## Guidance

### 1. Model the edges CPython actually walks, then say which way you rounded

Two rules together, neither sufficient alone.

**A `from <pkg> import <name>` is an edge to the submodule `<pkg>.<name>` when
that is a module in the tree, and to `<pkg>` otherwise**
(`tests/meta/test_import_layers.py:391-395`). This is what kills the phantom
`formatters` cycle: the submodule edge is the one the interpreter follows. A
`from <pkg> import <attr>` where `<attr>` is a name the package's `__init__`
binds *is* a dependency on `<pkg>` having finished running, so it stays an edge
to the package.

**An import of `a.b.c` is additionally an edge to every package on that path
the importer does not itself live under**
(`tests/meta/test_import_layers.py:398-411`, applied at line 437):

```python
def _packages_on_path(target, importer_package, modules):
    own_packages = set(_prefixes(importer_package))
    return {
        prefix
        for prefix in _prefixes(target)[:-1]
        if prefix in modules and prefix not in own_packages
    }
```

The ancestor exclusion is what makes the two rules coexist. A module's own
package is already initialising by the time the module body runs, so an edge to
it would reintroduce the package-initialisation artefact the first rule just
excluded. Depth matters: stop at the target's immediate parent and you miss the
grandparent. This tree imports three deep — `src/protokit/cli.py:23` does
`from protokit.schema.lint.cli import main as _lint_command`, which the gate
records as edges to `protokit.schema`, `protokit.schema.lint`, and
`protokit.schema.lint.cli`.

Be explicit that this rounds toward false positives. `import P.sub` requires
`P` only to have *started* initialising, so a sibling-package shape the
interpreter tolerates is still reported as a cycle. That is a deliberate
fail-closed trade, taken because dropping the rule to silence it reopens the
real load-order failure above — and it is pinned as such, not left to be
rediscovered (`tests/meta/test_import_layers.py:840-855`).

### 2. Read the `TYPE_CHECKING` guard off the module's own bindings

The general rule here is not new to this repo, and
[`strict-xfail-pin-without-raises-accepts-any-failure.md`](strict-xfail-pin-without-raises-accepts-any-failure.md)
already owns it: a gate that recognises its subject by spelling accepts what it
was built to reject, and the fix is to key on the resolved binding. What
follows is that rule's import-graph instance.

Recognise the guard by what the module bound, not by how the token is spelled
(`tests/meta/test_import_layers.py:268-321`). Collect names bound by
`from typing import TYPE_CHECKING [as X]` and module aliases bound by
`import typing [as T]` (`typing_extensions` counts for both), then subtract
every name the module rebinds or deletes:

```python
rebound = _rebound_at_module_scope(tree)
return cls(
    names=frozenset(names - rebound),
    typing_modules=frozenset(typing_modules - rebound),
)
```

Two details carry the correctness.

**Module scope only.** `_module_scope_nodes`
(`tests/meta/test_import_layers.py:203-216`) enters compound statements,
because their bodies run as the module loads, but yields without entering a
`def`, `async def`, `class` or `lambda` — those are namespaces of their own, so
a `TYPE_CHECKING` imported inside a function is invisible to a module-level
`if`.

**Over-collect the rebound set on purpose.** `_rebound_at_module_scope`
(`tests/meta/test_import_layers.py:219-265`) counts comprehension targets and
`global` declarations it arguably should not, and the docstring says why: a
dropped guard name costs a false positive, a stale one costs a missed import
CPython executes. Round the same direction everywhere, and write the direction
down.

Everything the gate does not recognise as the guard is a plain `if` and both
arms are entered — `Flags.TYPE_CHECKING` on some other receiver, a compound
`TYPE_CHECKING or X`, a `TYPE_CHECKING` never imported at all. The negated form
`if not TYPE_CHECKING:` counts its body and skips its `else`
(`tests/meta/test_import_layers.py:348-351`).

The rest of the execution model falls out of the same question — *does this run
at import?* A `def`, `async def` or nested `def` body does not
(`tests/meta/test_import_layers.py:156`, and `async def` is easy to omit); a
`try` body, an `except` arm, a `try`/`else`, a `finally`, an `if`/`elif`/`else`,
a `with`, a `for`, a `while`, a `match` arm and a class body all do. Resolve
relative imports against the importer's `__package__`, which is the module
itself for a package `__init__` and its parent otherwise
(`tests/meta/test_import_layers.py:430`). And parse from bytes, not text
(`tests/meta/test_import_layers.py:428`): a BOM or a PEP 263 coding cookie the
interpreter accepts would otherwise error the whole gate on a file whose
imports are not the problem.

### 3. Pair the syntactic gate with a runtime sweep, and pin the seam between them

Neither analysis subsumes the other, and each covers the other's blind spot.

The interpreter is not a complete oracle: a plain mutual `import a` / `import b`
cycle does not raise at all — the half-initialised module is simply bound — so
a runtime sweep alone would miss the cycles the gate exists to find.

The gate is not complete either. `test_every_module_imports_in_a_fresh_interpreter`
(`tests/meta/test_import_layers.py:646-669`) imports every module of the tree in
its own subprocess and is the runtime complement — it catches the module-level
call, the `importlib` string, and the module `__getattr__` the `ast` walk cannot
see. It is cheap enough not to be an excuse: 78 modules across eight threads,
and the whole file (80 tests) runs in about two seconds locally. Bound each
subprocess on wall clock (`tests/meta/test_import_layers.py:485`) and turn the
timeout into an ordinary named failure row
(`tests/meta/test_import_layers.py:508-522`), or a module that blocks on load
stalls the suite until the CI job cap and names nothing.

Then pin the seam. Every deliberate over-approximation gets a test that asserts
**both** verdicts — the gate's and the interpreter's — on the same synthetic
package (`tests/meta/test_import_layers.py:857-889`, and the individually
pinned boundaries at lines 840-855 and 891-907). A trade-off asserted in two
places is a decision; the same trade-off asserted in one place is a bug waiting
to be "fixed" by someone who only saw the other half.

### 4. Prove a meta test non-vacuous with injected-violation self-tests

With no `src` anchor for `scripts/mutation_check.py`, the substitute is a
self-test class that runs the real walk over synthetic `pkg` / `pkg.sub`
packages with one violation injected each, and asserts the failure names it
(`tests/meta/test_import_layers.py:761-1257`). Add a coverage guard so the
cycle assertion cannot pass on a graph that is not the package's: every module
is a node, the node count equals the `.py` count, known modules are present, and
no edge points outside the tree
(`tests/meta/test_import_layers.py:560-574`).

The self-tests only work if someone actively tries to write a passing wrong
implementation. That is the practice, not the file: for each rule, write the
plausible wrong version, run the suite, and if it passes, you have found the
missing test rather than a reason to relax.

## Why This Matters

- **A gate that fails open is worse than no gate.** No gate leaves the team
  knowing the property is unchecked. A fail-open gate spends the team's
  attention budget and then reports success on an analysis that never
  completed — and the seam work that lands on top of it inherits the false
  confidence. This is the 0.16.0 programme's whole subject, and the gate built
  to enforce it had two instances of it.
- **The interpreter and the `ast` walk have complementary blind spots, so
  "just import everything" is not an answer, and neither is "just parse
  everything."** A mutual plain-import cycle raises nothing at runtime; a
  call-executed import is invisible to the parser. The pairing is the design,
  not a belt-and-braces afterthought.
- **A phantom cycle destroys a gate as surely as a missed one.** `formatters`
  is a legitimate package-initialisation shape. A rule that flags it trains
  everyone to read the gate's failures as noise, and the first real cycle
  arrives in that same voice.
- **Rounding direction is a design decision that has to survive the reviewer
  who did not make it.** Both rules here round toward false positives, for
  opposite-looking reasons — one adds edges the interpreter might not need, one
  drops guard names the module might still honour — and both are written down
  in the code that implements them plus a test that pins the cost. Without
  that, the next reader deletes the "obviously over-eager" rule and reopens the
  failure it was closing.
- **Meta tests are the least-tested code in a repo and the most trusted.**
  Nothing downstream fails when a meta test silently stops checking, which is
  exactly why wrong implementations survived three rounds here.

## When to Apply

Apply when **any** of these hold:

1. A test derives a property of the package by walking source with `ast`
   instead of reading a hand-maintained list — and the property's ground truth
   is what CPython does at module load.
2. A gate answers an import-graph question: cycles, layering, seam purity,
   cold-import contracts, "package X must not transitively load Y".
3. The analysis must classify `if TYPE_CHECKING:` blocks, function-level
   deferred imports, or relative imports as edges or non-edges.
4. A syntactic analysis over-approximates or under-approximates on purpose and
   the trade is currently implicit.
5. The test you are writing has no product source to mutate, so
   `scripts/mutation_check.py` cannot certify it.

**Do not apply when:**

- The question is genuinely lexical — "does this string appear in this file" —
  and has no runtime semantics to be wrong about. A presence ratchet over prose
  needs no interpreter.
- The graph is already materialised by something authoritative. The lint
  engine's own `_tarjan_scc` enumerates strongly connected components over
  proto imports; the gate deliberately does not reuse it, because a meta gate
  must not depend on a module the 0.17.0 decomposition moves, and enumerating
  components is more than "is there a cycle" needs. Reuse is right when neither
  objection applies.
- The property is cheap to check at runtime and has no static component at all.
  Then write only the sweep, and say so.

## Examples

### The injected edge that leaves the gate green

One line added to `src/protokit/message/model.py`, immediately after
`from __future__ import annotations`:

```python
import protokit.schema.lint
```

Running the gate's own graph builder over the modified tree, alongside a
variant whose `_import_targets` result is used without `_packages_on_path`:

```
real rule (packages-on-path) : ['protokit.message', 'protokit.message.model',
                                'protokit.schema', 'protokit.message']
named-module-only variant    : None          <- fails open
import protokit.message      : rc=1  ImportError: cannot import name
                               'Diagnostic' from partially initialized module
                               'protokit.message.model'
import protokit.message.model: rc=1  (same)
import protokit              : rc=0          <- and this is why it is easy to miss
```

The top-level entry point still imports cleanly. Twelve of the tree's 78
modules break — every module under `protokit.message` — but `import protokit`
still succeeds, so a developer who checks the top-level entry point sees
nothing wrong.
The synthetic form of the same shape is pinned at
`tests/meta/test_import_layers.py:720-724` and asserted at lines 823-827, with
the two-package-deep version — the one a parent-only rule misses — at lines
746-751 and 829-838:

```python
_GRANDPARENT_PACKAGE_CYCLE = {
    "_a.py": "import pkg.x.y._z\nX = 1\n",
    "x/__init__.py": "from pkg._a import X\n",
    "x/y/__init__.py": "",
    "x/y/_z.py": "",
}
# graph["pkg._a"] == {"pkg.x", "pkg.x.y", "pkg.x.y._z"}
```

### The phantom cycle the over-correction reports

Add an edge to `<pkg>` for every `from <pkg> import <name>`, keep everything
else the same, and the tree grows one non-trivial strongly connected
component — `protokit.formatters` plus the four `_builtin_*` modules its
`__init__` imports. `_builtin_lint` stays out of it only because
`src/protokit/formatters/__init__.py:67-74` does not import it at module load;
that is how narrow the accident is. The real rule records
`protokit.formatters -> {_builtin_bisect, _builtin_compat, _builtin_diff,
_builtin_history, _junit_xml, _registry, _sarif_json}` and no back-edges, and
`test_formatters_package_init_shape_is_present_and_not_a_cycle`
(`tests/meta/test_import_layers.py:605-623`) asserts both halves — that the
shape is still there, and that no `_builtin_*` module imports the package
itself, which would be the genuine back-edge the submodule rule does not
excuse.

The minimal form, as the self-tests write it
(`tests/meta/test_import_layers.py:731-735`):

```python
_PACKAGE_INIT_SHAPE = {
    "__init__.py": "from pkg import _a\nfrom pkg import _b\n",
    "_a.py": "from pkg import _b as sibling\n",
    "_b.py": "",
}
# gate: no cycle.  interpreter: imports cleanly.
```

### Guard spellings that are not the guard

Ten parametrised cases at `tests/meta/test_import_layers.py:993-1056` each
assert the *cycle is reported* — the fail-closed direction. The four that are
easy to get wrong:

```python
# rebound alias: typing's flag at the import, True at the `if`
"from typing import TYPE_CHECKING as X\nX = True\nif X:\n    from pkg._a import A\n"

# rebound name, after the import
"from typing import TYPE_CHECKING\nTYPE_CHECKING = True\nif TYPE_CHECKING:\n    from pkg._a import A\n"

# bound only inside a function: the module-level `if` reads a name that is not there
"def f():\n    from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import pkg._a\n"

# re-exported by another module: same spelling, different provenance
"from pkg import TYPE_CHECKING\nif TYPE_CHECKING:\n    import pkg._a\n"
```

The rebound-name case is not merely a modelling nicety: it is carried into
`test_gate_verdict_agrees_with_the_interpreter`
(`tests/meta/test_import_layers.py:739-743, 857-889`), where the interpreter is
asserted to fail with `partially initialized module` on the same source. A
spelling-based walker calls all four `TYPE_CHECKING` and skips an import
CPython runs.

### The over-approximation, pinned in both directions

```python
_SIBLING_PACKAGE_SHAPE = {
    "_a.py": "from pkg.sub import _c\n",
    "sub/__init__.py": "from pkg import _a\n",
    "sub/_c.py": "",
}
```

`test_cycle_through_a_sibling_package_init_is_a_deliberate_over_approximation`
(`tests/meta/test_import_layers.py:840-855`) asserts the gate reports
`{pkg._a, pkg.sub}` **and** that a fresh interpreter imports `pkg._a`,
`pkg.sub` and `pkg.sub._c` with return code 0. Both facts are true, the test
says so, and the comment says which one the project chose to live with. The
boundary on the other side gets the same treatment
(`tests/meta/test_import_layers.py:891-907`): the gate reports no cycle for an
import executed by a module-level `register()` call while the interpreter
fails, and the test asserts *both*, so extending the walker to follow
module-level calls is a visible, deliberate update to this pin rather than a
silent behaviour change.

### The wrong implementations that passed everything

Each of these was written, run against the then-current suite, and passed —
which is what added the test that now catches it:

| Wrong implementation | Caught by |
| --- | --- |
| Add only the target's immediate parent package | `test_import_through_a_grandparent_package_init_is_a_cycle` (`:824-833`) — the real tree imports depth-3 targets |
| Parse with `read_text(encoding="utf-8")` instead of `read_bytes()` | `test_sources_are_parsed_as_bytes_so_a_bom_or_a_coding_cookie_still_builds` (`:1174-1191`) — BOM raises `SyntaxError`, a latin-1 cookie raises `UnicodeDecodeError` |
| Treat `def` as deferred but not `async def` | `test_import_in_a_deferred_scope_is_not_an_edge[async-def]` (`:920-935`) |
| Drop the package-`__init__` branch of relative resolution | `test_relative_imports_resolve_against_the_importer_package` (`:1109-1126`) — a `from . import x` in `__init__` resolves against the package, not its parent |
| Four separate guard readings (spelling-only; ignoring rebinds; walking into function scopes; missing the `typing_extensions` and aliased-attribute forms) | the ten-case fail-closed matrix (`:988-1051`) plus the six recognised spellings (`:937-959`) |

The deferred-import pins are the same idea applied to the real tree rather than
to synthetic packages: `DEFERRED_EDGES`
(`tests/meta/test_import_layers.py:145-148`) names the two function-level
imports that exist to break a load-time cycle —
`src/protokit/schema/profiles.py:192-193` importing `SchemaChecker` inside a
method, against `src/protokit/schema/checker.py:76`'s top-level
`from protokit.schema.profiles import filter_for_level`; and
`src/protokit/message/pytest_plugin.py:585-586` importing `matchers` inside
`ProtoMatcherFactory.__call__`, against `src/protokit/message/matchers.py:38`'s
top-level `from protokit.message.pytest_plugin import render_diff_lines`. The
test (`tests/meta/test_import_layers.py:585-603`) asserts each edge is **absent**
from the load-time graph, **present** in the deferred graph, and that the
reverse top-level edge still exists — so "top-level only" is proven on the real
tree, and a future hoist of either import into module scope fails with a message
naming the pair.

## Related

- [`tarjan-scc-iterative-dfs-package-cycle-detection-2026-05-22.md`](tarjan-scc-iterative-dfs-package-cycle-detection-2026-05-22.md)
  — cycle detection over a derived graph, in the lint engine. The gate
  deliberately does not reuse that `_tarjan_scc`: a meta gate must not depend
  on a module a later decomposition moves, and `graphlib.TopologicalSorter`'s
  `CycleError` already carries the cycle path
  (`tests/meta/test_import_layers.py:443-455`).
- [`circular-import-type-checking-cycle-break-2026-05-11.md`](circular-import-type-checking-cycle-break-2026-05-11.md)
  — the other side of the same coin: how to *use* `TYPE_CHECKING` to break a
  cycle. This doc is the gate that must not be fooled by it, and by every
  spelling of it that is not actually typing's flag.
- [`pytest-static-analysis-gate-ratchet-2026-05-02.md`](pytest-static-analysis-gate-ratchet-2026-05-02.md)
  — the repo's pattern for pytest-driven static-analysis gates; this gate is
  one, with a runtime complement bolted on.
- [`strict-xfail-pin-without-raises-accepts-any-failure.md`](strict-xfail-pin-without-raises-accepts-any-failure.md)
  — the same defect one release earlier, in a different surface: a ratchet that
  listed bare exception names accepted the `builtins.`-qualified spellings past
  it. It states the general rule this doc instantiates, so read it for the rule
  and this one for the import-graph specifics.
- [`capture-setup-without-dispatch-false-test-confidence-2026-05-17.md`](capture-setup-without-dispatch-false-test-confidence-2026-05-17.md)
  — the vacuity theme. Same lesson, different surface: a test that sets up the
  condition but never dispatches proves nothing, and neither does a meta test
  nobody tried to fool.
- [`sibling-blindness-fix-survives-review-structural-siblings-stay-broken.md`](sibling-blindness-fix-survives-review-structural-siblings-stay-broken.md)
  — derive the set of sites from the code, not from a list someone wrote down.
  `discover_modules` walking the tree, rather than a maintained module list, is
  that principle applied to the gate's own inputs.
