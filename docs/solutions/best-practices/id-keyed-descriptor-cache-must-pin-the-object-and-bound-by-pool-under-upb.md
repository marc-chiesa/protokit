---
title: "A cache keyed by id(descriptor) must pin the descriptor under upb, and what it pins is the pool"
date: 2026-09-15
category: best-practices
module: protokit._descriptors
problem_type: best_practice
component: tooling
severity: high
applies_when:
  - "Building a cache keyed by id(descriptor) \u2014 FileDescriptor, Descriptor, FieldDescriptor, etc. \u2014 under the upb backend (the default protobuf-python runtime)"
  - "A per-run/per-check memoization dict maps id(desc) -> result without also holding desc, inside a loop that visits many descriptors of the same kind (messages, fields) in one pass"
  - "A file-level cache entry holds a FileDescriptor (to key or validate an id()), and the traversal opens one fresh DescriptorPool per unit of work (e.g. `compat history` / `bisect`, one pool per commit)"
  - "Sizing a descriptor cache's bound by counting files/entries rather than by counting distinct pools referenced"
  - "Reviewing or writing a new lint/compat rule that memoizes a CopyToProto reconstruction (proto3_optional, reserved_range, etc.) per descriptor within a single check() run"
symptoms:
  - "A compat/lint rule that memoizes per id(desc) reports findings for the wrong message \u2014 e.g. 111 oneof_membership_changed findings on upb where exactly 100 exist, while the pure-Python backend (whose descriptors never die mid-run) reports the correct 100"
  - "A file-proto cache capped by file count either thrashes (evicts on every miss once live files exceed the cap, measured 9x slower than no cache) or, once raised, pins many more old DescriptorPools alive than intended (measured up to several hundred MB across a `compat history`/`bisect` walk)"
  - "WeakKeyDictionary raises TypeError when used to key a cache by a FileDescriptor/Descriptor \u2014 upb's wrapper is not weak-referenceable"
  - "The same id()-keyed-cache bug only reproduces on the default upb backend, not under PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python"
root_cause: logic_error
resolution_type: code_fix
tags:
  - upb
  - descriptor-identity
  - id-reuse
  - descriptor-cache
  - filedescriptor
  - descriptor-pool
  - pool-pinning
  - protobuf-descriptor
---
# A cache keyed by id(descriptor) must pin the descriptor under upb, and what it pins is the pool

## Context

On the default (upb) protobuf backend, a descriptor cache keyed by `id(descriptor)` without a strong reference to the descriptor answers for the wrong object: collected wrapper ids get handed to unrelated messages within the same run, so `protokit compat` reported spurious `oneof_membership_changed` findings. Separately, a descriptor cache that *does* pin its keys correctly can still leak unboundedly across a `compat history` / `bisect` walk, because pinning a descriptor pins its whole pool, and a per-file entry cap doesn't bound the number of pools a long walk keeps alive.

The two caches in question, with the measurements that exposed them:

- `_proto3_optional_fields` in `src/protokit/schema/rules.py` (fixed at `_proto3_optional_fields`, `rules.py:144-176`) memoized per `check()` run in a `contextvars` dict keyed by `id(desc)` with no reference held to `desc`. On a 200-message chain alternating a proto3 `optional` field (synthetic oneof, must not count as oneof membership) with a plain field moved into a real oneof (must count), upb produced 111 `oneof_membership_changed` findings where exactly 100 exist — 17 wrong cache hits, 44 ids shared across different messages' wrappers within one run. Pure-Python produced the correct 100, because its descriptors stay alive for the process lifetime and never alias.
- `message_proto`'s per-file cache in `src/protokit/_descriptors.py` (`_FILE_PROTO_CACHE`), capped purely by file count, showed two failure modes at different cap values:
  - Cap 32 thrashed on any schema with more than 32 live files, because the compat checker traverses by message reference rather than grouped by file: 60 files visited round-robin measured 3.7 ms at cap 32 versus 0.4 ms at cap 256 (9x), and 0.4 ms beat even no cache at all (~0.6 ms) — the thrashing cache was worse than not caching.
  - Cap 256 fixed the thrash but, because every cached entry holds a strong reference to its `FileDescriptor` and therefore pins that descriptor's pool, a `compat history` / `bisect` walk (one fresh pool per commit) could pin many old pools at once: 10-file schema, 40 commits — cap 32 pinned 4 pools / 63 MB peak, cap 256 pinned 26 pools / 208 MB; 100-file schema, 20 commits — 1 pool / 127 MB versus 3 pools / 426 MB. An independent validator measured 1202 MB versus 268 MB on a larger-file variant of the same walk.

Why the obvious designs were not available (session history: the file cache's author checked weak-referenceability on both backends before choosing the strong-reference design, and sized the first cap for boundedness rather than for a measured workload — the review round that followed measured the thrash):

- **`weakref.WeakKeyDictionary` keyed on the descriptor.** Under upb, `Descriptor` / `FileDescriptor` are C-extension wrapper objects and are not weak-referenceable — `weakref.ref()` (and `WeakKeyDictionary.__setitem__`) raises `TypeError: cannot create weak reference to 'google._upb._message.Descriptor' object` (confirmed directly against the current tree's protobuf 5.27.5 install). The one container that would auto-expire entries exactly when the underlying wrapper is collected — solving both the identity and the leak problem at once — is unavailable on the backend that matters.
- **An `id()`-keyed dict with no reference held to the object.** This is the shape `_PROTO3_OPTIONAL_CACHE` had before the fix on this branch. It looks identity-safe because `id()` is unique *while the object is alive*, but under upb the wrapper is created on demand and released as soon as nothing references it, and CPython reissues freed ids to the next allocation. Confirmed directly: looking up 3 distinct messages from the same pool by name, with no reference held between lookups, produced only 1 distinct `id()` across the 3 calls (the wrapper was collected and its id reused twice). A cache with no pin doesn't just risk staleness — it silently answers for a different message's proto3-optional set, and the compat rules read it as ground truth.
- **A bigger file cap (256) alone as the leak fix.** Raising the cap from 32 to 256 fixed the thrash (see Symptoms), but a file-count cap has no way to express "how many pools are alive," since one 100-file pool costs the same 100 slots as 100 one-file pools drawn from 100 different commits. The fix that actually bounds walk memory had to count pools, not files.

## Guidance

For any future cache keyed on a protobuf descriptor, or on any upb wrapper type:

For any future cache keyed on a protobuf descriptor (or any upb wrapper type):

- Key by `id()` only if the value also holds a strong reference to the exact object, and check identity (`is`) on every hit before trusting a lookup — an id match alone is not proof of object identity once the object can be collected.
- `weakref` containers are not an option for upb wrapper types (`WeakKeyDictionary`, `weakref.ref`, `weakref.finalize` all raise `TypeError`); don't reach for them as the "obvious" fix.
- When sizing the cache's bound, count what actually gets pinned in memory — here, pools, not files/entries — not what's convenient to count. If pinning one entry drags in a larger owning structure, the eviction unit should be the owning structure.
- Test upb specifically with a reference-order or high-churn access pattern long enough to exercise id reuse (e.g. a chain of ~200 short-lived messages with two answer shapes, asserting exact counts, not just "no crash") — pure-Python's suite passing proves nothing about upb's aliasing behavior, since pure-Python descriptors never get collected.
- Test the pool-count bound separately from the entry-count bound: a walk of many small pools (few files each) must show only the newest N pools pinned, and touching an evicted pool's descriptor again must still read correctly.
- Clear caches between tests (`_clear_file_proto_cache`, or the equivalent `contextvars` reset) so one test's pinned pools can't leak into another's memory/identity assertions.

The two fixes on this branch are the reference shape:

The proto3-optional cache now stores the descriptor alongside the result and checks identity on hit, so a reused id can never be mistaken for the object that owned it (`src/protokit/schema/rules.py:165-176`):

```python
cache = _PROTO3_OPTIONAL_CACHE.get()
if cache is not None:
    cached = cache.get(id(desc))
    if cached is not None and cached[0] is desc:
        return cached[1]
...
if cache is not None:
    cache[id(desc)] = (desc, result)
```

The file-proto cache pins the same way, and bounds eviction by distinct pools rather than by file count, with a file-count backstop against one pathological pool (`src/protokit/_descriptors.py:139-219`):

```python
_FILE_PROTO_CACHE_MAX_POOLS = 4
_FILE_PROTO_CACHE_MAX_FILES = 2048
...
while len(_FILE_PROTO_POOLS) > _FILE_PROTO_CACHE_MAX_POOLS:
    _, (_, evicted_keys) = _FILE_PROTO_POOLS.popitem(last=False)
    for evicted in evicted_keys:
        _FILE_PROTO_CACHE.pop(evicted, None)
while len(_FILE_PROTO_CACHE) > _FILE_PROTO_CACHE_MAX_FILES:
    evicted, (_, _, _, evicted_pool) = _FILE_PROTO_CACHE.popitem(last=False)
    owner = _FILE_PROTO_POOLS.get(evicted_pool)
    if owner is not None:
        owner[1].discard(evicted)
```

Both caches are entered under one `threading.Lock()` (`_FILE_PROTO_LOCK`, `_descriptors.py:154`) because eviction can otherwise race a second caller between its `get` and `move_to_end` and raise `KeyError` — reported under two concurrent `SchemaChecker` runs. Both fixes are on branch `fix/u3-fieldview-seam` (PR pending as of this writing), not yet merged.

## Why This Matters

The two backends give `Descriptor`/`FileDescriptor` genuinely different lifetimes. Under pure-Python, descriptors are ordinary long-lived Python objects; once built they persist for the life of the pool, so `id()` is a stable key for as long as anyone cares to use it. Under upb (the default backend), the Python-visible `Descriptor` is a wrapper created on demand over the C++ object and released the moment nothing references it — so `id()` is only a stable key *while something holds the wrapper*. A strong reference in the cache's own value is what makes the id unreusable: as long as the entry lives, CPython cannot free that wrapper and reissue its id to something else, which is exactly the pin both fixes rely on (the identity check on the hit path in `rules.py` is then redundant-but-cheap insurance: the pin is the fix, and the proof that removed both together is what showed it).

That same strong reference has a cost: holding a descriptor holds the pool that owns it (a pool cannot release a file while any of its descriptors are referenced), so the memory a descriptor cache pins is counted in pools, not in cache entries. A cap on entries bounds the cache's own size but says nothing about how many distinct pools — and therefore how much of a multi-commit history walk — stay resident. Bounding by pool count (LRU, evicting a whole pool's entries together) makes the eviction unit match the actual unit of memory.

## When to Apply

- Building or reviewing any cache whose key is `id()` of a `FileDescriptor`, `Descriptor`, `FieldDescriptor` or another upb wrapper.
- A per-run memoization that visits many descriptors of one kind in a single pass (compat rules, lint rules, drift walkers) — the churn that recycles wrapper ids.
- A cache entry that retains a `FileDescriptor`, in a traversal that opens one fresh pool per unit of work (`compat history`, `bisect`).
- Sizing such a cache: count what is pinned (pools), not entries.
- A defect that reproduces on the default backend but not under `PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python` — pure-Python descriptors are long-lived and never alias, so that asymmetry is itself the signature.

## Examples

A minimal reproduction of the aliasing, on upb only: build one proto3 file with a chain of messages `M0 -> M1 -> ... -> M199` linked through a `next` field, alternate a proto3 `optional` field (a synthetic oneof, which must not count as oneof membership) with a plain field moved into a real oneof between the old and new schemas (which must count), and run `check_compatibility` from `M0`. Exactly half the messages should report `oneof_membership_changed`; an `id()`-keyed cache with no pin reports more. `tests/schema/test_proto3_optional_cache.py` is that test, parametrised at 40 and 200 messages, and it passes on both backends only with the pin.

A minimal reproduction of pool pinning: build one small pool per "commit" in a loop (ten files each), read every message through `message_proto`, and count `{id(fd.pool) for fd, *_ in _FILE_PROTO_CACHE.values()}` after each commit. A file-count cap leaves as many pools alive as the cap divided by the files per pool; the pool bound leaves exactly the bound. the `TestFileProtoCache` class in `tests/core/test_descriptors.py` pins both the no-thrash property (64 files serialized once across two passes) and the pool bound (a walk of ten pools pins only the newest four).

## Related

- `docs/solutions/best-practices/wire-filedescriptorproto-dependency-through-pool-pure-python-vs-upb.md` — the same pure-Python-vs-upb backend split, from the pool-resolution side (lazy vs. eager `FileDescriptorProto.dependency` resolution).
- `docs/solutions/tooling-decisions/ptars-over-protarrow-proto-to-arrow-isolated-descriptor-pools.md` — why descriptor pools are isolated from each other in the first place, the structural fact this cache's pool-bounding leans on.
- `docs/solutions/test-failures/mock-patch-c-extension-method-descriptor-2026-05-06.md` — another surprise from upb's C-extension wrapper objects (`unittest.mock.patch` silently no-ops on them), same underlying theme of upb wrappers not behaving like ordinary Python objects.
