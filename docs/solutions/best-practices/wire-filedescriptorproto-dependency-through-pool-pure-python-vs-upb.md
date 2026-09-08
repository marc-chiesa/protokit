---
title: "Wire FileDescriptorProto.dependency through the pool: pure-Python's lazy resolution needs it, upb's eager resolution hides its absence"
date: 2026-09-08
category: docs/solutions/best-practices
module: testing/protobuf-backend-parity
problem_type: best_practice
component: testing_framework
severity: high
applies_when:
  - "Measuring a protobuf-based test suite under the pure-Python runtime backend (PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python) after it has only ever run under the default upb backend"
  - "A test fixture or helper builds a FileDescriptorProto programmatically (not via protoc) and one file's fields reference a type_name or extendee declared in a sibling file added to the same pool"
  - "A helper calls pool.Add(file_desc_proto) and uses its return value as if a FileDescriptor came back the way upb's Add returns one"
  - "Triaging a batch of failures that appear only on a second backend, and deciding how many are product defects before fixing anything"
  - "A fixture-builder defect was fixed at the call site that first reported it and needs checking at every other builder"
symptoms:
  - "KeyError from protobuf's descriptor_pool module (_GetTypeFromScope) when a cross-file type_name is resolved under pure-Python, with the identical fixture passing under upb"
  - "pool.Add(fdp) returns None under pure-Python and an AttributeError follows from treating the result as a FileDescriptor, while the same call returns a FileDescriptor under upb"
  - "A cross-backend failure count cannot be split into product defects and test-helper defects without inspecting each traceback's deepest frame under src/ versus tests/"
  - "Fixing the missing dependency wiring at one fixture-builder call site leaves ten sibling call sites still broken"
root_cause: incomplete_implementation
resolution_type: test_fix
related_components:
  - tooling
tags:
  - cross-backend-testing
  - pure-python-backend
  - upb
  - descriptor-pool
  - file-descriptor-proto
  - fixture-builder
  - dependency-wiring
  - failure-attribution
---

# Wire FileDescriptorProto.dependency through the pool: pure-Python's lazy resolution needs it, upb's eager resolution hides its absence

## Context

The protobuf Python package ships two runtime backends: upb (C, the default) and
pure-Python (`PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python`). This suite had only
ever run under upb. Its first full run under pure-Python, on the tree after the
audit pins of PR #55 (measured 2026-09-07 with protobuf 5.27.5 on CPython 3.13),
gave `286 failed, 3196 passed, 8 skipped, 36 xfailed` against upb's
`3468 passed, 8 skipped, 50 xfailed` on the same 3526 tests. The question was how
many of the 286 were product defects, and the raw count could not answer it:
134 died inside test helpers before reaching the code under test.

Two fixture defects, both invisible under upb, caused the 134:

1. Every programmatic descriptor builder emitted one `FileDescriptorProto` per
   message and referenced earlier types by `type_name` alone, never filling in
   `file_proto.dependency`. upb resolves the reference against the whole pool;
   pure-Python resolves it only through the file's declared dependencies. This
   defect lived in three modules — `ProtoBuilder.message` / `map_message`,
   `build_message` / `build_enum` in `tests/schema/helpers.py`, and seven inline
   builders in `tests/schema/test_checker.py` — and the repo had already written
   the workaround instead of the fix: on `main` before PR #57,
   `tests/schema/test_cli.py` carried the comment "build_message doesn't
   auto-wire dependency edges between sibling files" beside a manual listing of
   both files.
2. Three storage helpers did `fd = pool.Add(fdp)` and used `fd`. upb's `Add`
   returns the `FileDescriptor`; pure-Python's returns `None`, so the helper died
   with `AttributeError` and masked the test's own assertion.

Fixed in PR #57 (open, unmerged as of 2026-09-08; plan unit U22). Once the
helpers were honest, the product-defect count went *up*: 110 helper-caused
failures stopped failing (106 pass; 4 return to the strict xfails PR #55 pinned),
and 24 helper-caused failures unmasked a product defect underneath (23 V34,
1 V1), so the honest product count rose from 152 to 176. The named V1 scenario,
`test_missing_required_field_cannot_measure` in
`tests/storage/test_columnar_fidelity.py`, now fails on its own
`assert 0 is None` instead of inside the helper.

What was tried first, and did not work:

- **Counting failures as product defects.** The first pure-Python run (263
  failures on 2026-08-30, before the audit pins landed) was "materially more than
  the plan anticipated" — the plan had expected a handful of fidelity-probe and
  pool-building failures. Two clusters were traced to one product root cause
  (V34, `Descriptor.CopyToProto` on a pool-built descriptor) and explicitly not
  double-counted; the helper cluster was recognised only when eight audit pins
  died with `KeyError` inside the builder (session history). An interim
  inventory figure in the plan was later caught as wrong by document review, so
  a single-pass count is unverified until cross-checked (session history).
- **Marking each backend-dependent failure as an individual xfail.** Rejected
  as "mass xfails" once the scale was clear; the count had to be attributed by
  root cause first (session history).
- **Wiring dependencies from a builder-local file list.** `ProtoBuilder` knows
  the files it emitted, but `build_message` and the inline builders take a
  caller-supplied pool that several tests pre-populate by hand; a local list
  misses those referents.
- **Trying the bare name before the package-scoped name.** With root-level `X`
  and `a.X` both in a shared pool, a file in package `a` referencing `X` must
  depend on `a.proto`; bare-name-first records `r.proto` and resolves to the wrong
  type under pure-Python.
- **Fixing only what the upb suite could see.** The code review of PR #57
  reverted the storage fix and the entire upb suite still passed. A fix with no
  pure-Python pin has no regression control.

## Guidance

**Attribute before you count.** Attribute each cross-backend failure to the
deepest traceback frame under `src/` or `tests/`; for CliRunner cases read the
`Result` under `--showlocals`. A failure that dies in a helper is not a product
finding. Remove the helper-caused failures first, then count — here removal
*raised* the product count by unmasking failures the helper had been swallowing.

**Wire `dependency` through the pool, at every builder.** One shared helper,
`wire_dependencies(file_proto, pool)` in `tests/proto_builder.py`, is called
immediately before `pool.Add` at all eleven builder sites:

```python
# before                               # after (PR #57)
self.pool.Add(file_proto)              wire_dependencies(file_proto, self.pool)
                                       self.pool.Add(file_proto)
```

The helper walks every referenced name — each field's `type_name`, plus an
extension's `extendee` and `type_name` at both file and message scope — tries
each in protobuf scope order (a leading dot is absolute; otherwise innermost
package first, bare name last), skips names the file itself declares, looks the
rest up through `pool.FindMessageTypeByName` / `FindEnumTypeByName`, tolerates a
miss, and appends each referent's `file.name` to `file_proto.dependency` once.
Resolution goes through the pool because the pool is the only complete source of
truth: a referent may have been `pool.Add`ed by hand with no builder involved.
Scope order mirrors the runtime's own `_GetTypeFromScope`, so the first
candidate that is declared in-file or present in the pool is the one protobuf
would pick, and a same-named type at an outer scope of a shared pool cannot
shadow the inner one. A miss is not the helper's error to raise; `pool.Add` or
the first lookup reports it with protobuf's own message.

**Never use `pool.Add()`'s return value.** Read the file back instead:

```python
# before                               # after (PR #57)
fd = pool.Add(fdp)                     pool.Add(fdp)
                                       fd = pool.FindFileByName(fdp.name)
```

**Pin every backend-specific fix with a subprocess-forced pure-Python test.**
The backend is chosen at import time and cannot be switched inside the upb
process, so the pin runs a child interpreter and asserts the backend it got
(`tests/meta/test_proto_builder.py`, `TestDependencyWiring`; storage guards in
`tests/storage/test_columnar_fidelity.py` and `tests/storage/test_columnar_structural.py`):

```python
script = (
    "from google.protobuf.internal import api_implementation\n"
    "assert api_implementation.Type() == 'python', api_implementation.Type()\n"
    "from tests.proto_builder import ProtoBuilder\n"
    "b = ProtoBuilder()\n"
    "b.message('test.Address', {'street': (T.TYPE_STRING, 1)})\n"
    "b.message('test.Person', {'address': (T.TYPE_MESSAGE, 1, '.test.Address')})\n"
    "print(b.build('test.Person').address.street)\n"   # KeyError before the fix
)
env = dict(os.environ, PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION="python", PYTHONPATH=str(_REPO_ROOT))
result = subprocess.run([sys.executable, "-c", script], cwd=_REPO_ROOT, env=env,
                        capture_output=True, text=True, timeout=60, check=False)
assert result.returncode == 0, result.stderr
```

The child's `api_implementation.Type()` assertion makes a runtime that cannot be
forced fail loudly instead of silently testing upb again.

**Prove the pins are real, and diff outcomes rather than counts.**
`scripts/mutation_check.py` on the `file_proto.dependency.append(...)` line
reported NON-VACUOUS: every wiring test in `TestDependencyWiring` fails under
the mutation (the exact counts grow as tests are added; the first U22 commit
reported 9 collected, 6 failed). Compare `pytest -rA` per-test
outcomes between `main` and the branch under upb: PR #57 changed zero existing
outcomes and added 42 tests. A pass/fail count would have hidden a swapped
outcome.

**Expect siblings.** When a helper defect is found, grep for every `pool.Add(`
under `tests/` before declaring it fixed. The pattern here — the same defect in
three modules, one of them already annotated with the workaround — is
[[sibling-blindness-fix-survives-review-structural-siblings-stay-broken]].

## Why This Matters

All runtime claims below are current-state as of protobuf 5.27.5, verified
against the installed package's `descriptor_pool` module (part of protobuf, not
this repository). The subprocess pins
re-assert on every CI run that the fixed constructions work under pure-Python;
nothing re-asserts the divergences themselves, so re-check them when the pin
moves to a new protobuf release.

**Divergence 1: dependency-scoped resolution.** Under upb, `DescriptorPool.__new__`
returns the C pool and the pure-Python class body never runs. Under pure-Python,
`Add` only stores the proto in an internal database; `FindFileByName` converts
lazily via `_ConvertFileProtoToFileDescriptor`, which builds its name scope from
the files named in `file_proto.dependency` plus the file's own types. Each
field's `type_name` is then resolved by `_SetFieldType` → `_GetTypeFromScope`,
which walks the package outward and ends in `return scope[type_name]` — a plain
`KeyError` for anything not declared in the file or its dependencies. That is
why the error surfaces at the first lookup, never at `Add`, and why upb (which
resolves against the whole pool at `Add`) never saw it. The same laziness applies
to duplicate symbols: a `RuntimeWarning` at `Add`, and a
`TypeError("Conflict register for file ...")` only at conversion.

**Divergence 2: the `Add` return value.** The pure-Python `Add` has no `return`;
upb's returns the `FileDescriptor`, which the storage helpers had relied on for
the suite's entire life. `FindFileByName` returns the `FileDescriptor` on both
backends (upb's implementation is compiled, so this is observed through the
subprocess pins rather than read from source).

**Why the fixture layer matters more than it looks.** A suite that is green under
one backend has expressed one backend's opinion. Until the helpers were honest,
the pure-Python failure set was a mixture that could neither be inventoried nor
gated on, and the product findings it hid (23 V34, 1 V1) were invisible. The
planned consumer is a pure-Python CI cell with a known-failure inventory (plan
unit U2); the 176 product defects themselves (V34/V10/V1) belong to plan unit U3,
not to this learning.

## When to Apply

- Before counting or gating on a failure set that exists only under a second
  backend, runtime, or platform: attribute by deepest frame first and remove
  helper-caused failures.
- Whenever a test builds `FileDescriptorProto` objects directly and any field or
  extension references a type from another file in the same pool.
- Whenever a helper reads `pool.Add()`'s return value.
- Whenever a fix is only observable under a configuration the required CI does
  not run: add a subprocess-forced pin under that configuration, and prove it
  with a mutation or revert.
- Whenever a fixture-builder defect is found at one site: grep the ingredient
  (`pool.Add(`, `type_name =`) across `tests/` before declaring it fixed.

## Examples

A two-file `ProtoBuilder` pool now records the edge under both backends:

```python
builder = ProtoBuilder()
builder.message("test.Address", {"street": (T.TYPE_STRING, 1)})
builder.message("test.Person", {"address": (T.TYPE_MESSAGE, 1, ".test.Address")})
person_file = builder.pool.FindFileByName("generated_2.proto")
assert [d.name for d in person_file.dependencies] == ["generated_1.proto"]
```

Scope order over a shared pool: with root-level `X` (file `r.proto`, no package)
and `a.X` (file `a.proto`) both present, a file in package `a` whose field
references bare `X` records `a.proto`, and the runtime's own resolution lands on
`a.X` as well (`tests/meta/test_proto_builder.py`,
`test_bare_name_prefers_package_scope_over_pool_root`).

The revert experiment that justified the storage pins: restoring
`fd = pool.Add(fdp)` at any one of the three sites passes the whole upb suite
and fails exactly that module's subprocess test with
`AttributeError: 'NoneType' object has no attribute 'message_types_by_name'`.

## Related

- [[sibling-blindness-fix-survives-review-structural-siblings-stay-broken]] — the
  three-location shape this defect took, and the grep-the-ingredient rule.
- [[strict-xfail-pin-without-raises-accepts-any-failure]] — first sighting of
  the `KeyError` inside `ProtoBuilder` (four audit pins absorbed it until
  `raises=` was narrowed); those four pins return to honest xfails once the
  helpers are wired (PR #55, PR #57).
- [[programmatic-proto-fixture-builder-multi-file-rule-family-2026-05-17]] —
  cross-file fixtures built as `.proto` source and compiled; a compiler rejects
  an unresolvable import outright, which is why that layer never showed this
  defect.
- [[source-code-info-semantic-not-byte-equivalence-across-protoc-backends-2026-05-27]] —
  a different backend axis: protoc compile backends, not the protobuf-python
  runtime backends this learning is about.
- [[copytoproto-round-trip-for-proto-form-only-descriptor-fields-2026-05-13]] —
  background for the V34 `CopyToProto` product defect the helper fix unmasked.
- [[fixture-precondition-assertion-surfaces-silent-test-2026-05-17]] — the
  child-process `api_implementation.Type()` assertion is this discipline.
- [[mock-patch-c-extension-method-descriptor-2026-05-06]] — the other
  `DescriptorPool.Add` backend gotcha (C-extension methods resist `mock.patch`).
- PR #55 (audit pins), PR #57 (this fix; unit U22 of the 0.16.0 plan).
