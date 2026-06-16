---
title: "Recursive proto schemas segfault ptars during Arrow schema build"
date: 2026-06-15
category: security-issues
module: protokit.storage
problem_type: security_issue
component: tooling
symptoms:
  - "Converting a proto with a recursive message type to Parquet crashes the whole process with SIGSEGV (exit 139 / -11), not a Python exception"
  - "The crash bypasses every guard (the except->HandlerBuildError net AND the BaseException partial-file unlink) and orphans the .partial temp file"
  - "Triggers on self-reference (Node with a repeated Node field), mutual recursion, and the well-known types google.protobuf.Struct / Value / ListValue"
root_cause: missing_validation
resolution_type: code_fix
severity: high
tags: [recursive-schema, segfault, ptars, arrow-schema, descriptor-preflight, raise-before-c, well-known-types, subprocess-survival-test]
---

# Recursive proto schemas segfault ptars during Arrow schema build

## Problem

The columnar/Parquet path (`src/protokit/storage/_columnar.py`) hands a message
descriptor to the `ptars` backend to build an Arrow schema. When the descriptor
is **recursive** — a type reachable from itself — ptars 0.0.17's Rust schema
builder recurses with no cycle guard until the native stack overflows, killing
the whole process with a SIGSEGV (`exit 139`) *before any record is read*.
Because a signal is not a Python exception, it bypasses every error guard the
sink relies on and leaves an orphaned `.partial` temp file, breaking the
documented exit-0/2, no-partial-file contract.

## Symptoms

- Process dies with `SIGSEGV` / `exit 139` (`subprocess` reports `-11`) the moment
  conversion of a recursive type begins.
- Neither the adapter's `except Exception -> HandlerBuildError` wrapper nor the
  CLI's blanket `except Exception` ever runs; the `finally` that unlinks the
  `.partial` temp never fires, so the temp is orphaned.
- Triggers on direct self-reference (`Node { repeated Node children }`), mutual
  recursion (`A -> B -> A`), recursion through map / group / oneof message
  fields, and — non-obviously — any message embedding `google.protobuf.Struct`,
  `Value`, or `ListValue` (these are themselves recursive: `Struct -> Value ->
  Struct`).

## What Didn't Work

- **A `try/except` around the ptars call.** A SIGSEGV is a process signal, not a
  Python `Exception`. No in-process handler — not `except Exception`, not the
  CLI's blanket arm — can intercept it. The crash is *uncatchable* in-process.
- **Assuming `google.protobuf.Struct` mapped losslessly.** The prior proto->Arrow
  learning claimed `Any`/`Struct`/`FieldMask` "map losslessly, never blocked", so
  the first design *terminalized* the `google.protobuf.*` prefix (skipped
  descending into it). Measuring ptars 0.0.17 directly inverted the assumption:
  `Struct`/`Value`/`ListValue` are exactly the WKTs that segfault, while
  `Timestamp`/`Any`/`Duration`/`FieldMask`/`Empty`/wrappers convert. Terminalizing
  the struct family would have let the common `Struct`-embed sail straight into
  the crash the guard exists to prevent.
- **Hoping empty data avoids it.** The Arrow schema is derived from the
  *descriptor*, not the records (an empty conversion still builds the full
  schema), so even a recursive field that is never populated crashes. Rejection
  must be at the type level.

## Solution

Detect the cycle in Python and raise a catchable error **before** ptars is
invoked — there is no other lever, since ptars is exact-pinned and its schema
builder is a closed binary. A pure descriptor pre-flight runs inside
`_PtarsConversionAdapter.__init__` ahead of `ptars.HandlerPool`:

```python
def _find_recursive_cycle(descriptor):
    """Return (cycle, is_wkt_family) or None. Iterative DFS — never recursive."""
    on_path, in_progress, acyclic = [], set(), set()
    stack = [("enter", descriptor)]
    while stack:
        action, node = stack.pop()
        if action == "leave":
            in_progress.discard(node.full_name)
            on_path.pop()
            acyclic.add(node.full_name)   # memo: popped without a cycle => safe
            continue
        if node.full_name in acyclic:      # skip a proven-safe shared sub-message
            continue
        if node.full_name in in_progress:  # back-edge to a node on the path => cycle
            start = next(i for i, d in enumerate(on_path)
                         if d.full_name == node.full_name)
            cycle_descs = on_path[start:] + [node]
            cycle = [d.full_name for d in cycle_descs]
            is_wkt = all(d.file.name == _STRUCT_PROTO_FILE for d in cycle_descs)
            return cycle, is_wkt
        in_progress.add(node.full_name)
        on_path.append(node)
        stack.append(("leave", node))
        for field in node.fields:
            if not field.is_extension and field.type in _MESSAGE_FIELD_TYPES:
                stack.append(("enter", field.message_type))
    return None


def _reject_recursive(descriptor):
    found = _find_recursive_cycle(descriptor)
    if found is None:
        return
    cycle, is_wkt = found
    if is_wkt:
        raise UnsupportedWktError(descriptor.full_name, tuple(cycle))
    raise RecursiveSchemaError(descriptor.full_name, tuple(cycle))
```

`_reject_recursive(descriptor)` is called at the top of the adapter constructor,
before `ptars.HandlerPool(...)`. Both errors subclass `StorageError`, carry the
structured cycle path, and are exported from `protokit.storage`; they
auto-route to CLI `exit 2` through the base-keyed `_TYPED_CLI_ERRORS` tuple, so
no CLI change is needed. The struct family (`Struct`/`Value`/`ListValue`) is
*not* special-cased in the walk — being genuinely recursive, the plain cycle
check rejects it; the only WKT-awareness is at the cycle, where an all-`struct.proto`
cycle becomes `UnsupportedWktError` (a clearer message than "your schema is
recursive" for a user who merely embedded a `Struct`).

## Why This Works

Arrow/Parquet schemas are finite, acyclic type trees — a recursive type has no
columnar representation, which is precisely why ptars cannot build one and why
rejecting is correct (Spark's `from_protobuf`, parquet-java, and others reject
or depth-cap by default too). Moving detection into Python *before* the
descriptor reaches the C extension converts an uncatchable process death into a
catchable `StorageError`, keeping the failure inside the error model the sink
already honors. This is the same move as the released-memoryview fix —
materialize/validate in Python before the value reaches C — generalized from
**buffer lifetime** to **schema topology**.

Two details keep the guard itself safe. It is an **iterative** DFS, so a deep
self-referential type cannot raise `RecursionError` (which would re-introduce a
failure escaping the taxonomy). And it carries an **acyclic memo**: a path-scoped
`in_progress` set alone correctly distinguishes a true cycle from a DAG diamond,
but re-walks a shared sub-message once per path — exponential on a wide, deep,
but perfectly *valid* acyclic schema. Graduating each node to `acyclic` on
backtrack (a node popped with no cycle is acyclic on every path) makes the walk
O(V+E) while preserving identical detection. Without the memo, the guard meant
to prevent a crash would instead hang on valid input — a regression caught by
`ce-code-review` (correctness + adversarial + performance agreed, with measured
timings) before merge.

## Prevention

- **Raise before C.** At any boundary where input crosses into a closed C
  extension that can crash on a malformed or unsupported shape, validate in
  Python and raise a catchable error *before* the call. Never hand the raw value
  to C and hope to catch the failure — a SIGSEGV bypasses the entire `except`
  model (and even `BaseException` cleanup).
- **Regression-test process *survival* in a subprocess.** Assert the child exits
  with the clean error code (`== 2`), not the crash (`!= 139`). An in-process
  test cannot assert a segfault is gone — the in-process variant of the bug *is*
  the crash. One assertion per crashing shape (here: self-reference and each of
  `Struct`/`Value`/`ListValue`); a single fixture only proves that one shape.

  ```python
  proc = subprocess.run([sys.executable, "-c", "from protokit.cli import main; main()",
                         *argv], capture_output=True, text=True)
  assert proc.returncode == 2, f"expected clean exit 2, got {proc.returncode}"
  ```

- **Measure a pinned closed dependency; don't trust documentation about it.** The
  proto->Arrow doc's "`Struct` maps losslessly" was wrong at the schema-build
  boundary. A five-minute per-type subprocess probe (`exit 0` vs `139`) gave
  ground truth and *inverted* the design — promote that probe to a
  pre-implementation gate when it can falsify the plan.
- **Path-scoped set + acyclic memo for any cycle-vs-diamond walk.** The
  `in_progress` set prevents false-positives on shared sub-nodes; the `acyclic`
  memo prevents exponential re-visits. Keep the walk iterative to avoid
  `RecursionError`.

## Related Issues

- [Released memoryview MergeFromString segfault bypasses on_error](released-memoryview-mergefromstring-segfault-bypasses-on-error-2026-05-30.md)
  — the structural precedent this generalizes (C-extension crash bypasses the
  error model; raise in Python before C; subprocess survival test).
- [Faithful proto-to-Arrow mapping](../design-patterns/proto-to-arrow-faithful-mapping-presence-structure-arrow-native-values.md)
  — the mapping doc this fix corrected (the `Struct`-maps-losslessly claim) and
  whose disposal guarantee became three-layered (pre-flight is the new layer 0).
- [Atomic CLI file publish](../design-patterns/atomic-cli-file-publish-sibling-temp-os-replace.md)
  — the CLI publish layer above the sink; the `.partial` no-orphan guarantee
  this restores.
- [Tarjan SCC + iterative DFS for cycle detection](../best-practices/tarjan-scc-iterative-dfs-package-cycle-detection-2026-05-22.md)
  — the iterative-not-recursive discipline the walker reuses, on the type graph
  rather than the import graph.
- [ptars over protarrow](../tooling-decisions/ptars-over-protarrow-proto-to-arrow-isolated-descriptor-pools.md)
  — the exact-pinned, closed-binary backend whose maturity risk this
  materializes.
- [Multi-mechanism fix docstring enumerates each layer + failure mode](../best-practices/multi-mechanism-fix-docstring-enumerate-each-layer-failure-mode-2026-05-18.md)
  — why the pre-flight is documented as a named layer the `BaseException` unlink
  does not cover.
- Issue #25 (columnar real-data go/no-go — this resolves the blocker found
  during it), issue #24 (the `--format parquet` feature), PR #39 (this fix).
