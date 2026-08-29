---
title: "A protocol-maximum range expanded into a set OOMs the process: keep half-open pairs and test membership"
date: 2026-07-27
category: docs/solutions/logic-errors
module: protokit.schema.rules
problem_type: logic_error
component: engine
severity: high
applies_when:
  - "Code expands a declared RANGE into a materialized collection (set/list/dict) when the only operation performed on it is membership"
  - "The range's upper bound is a PROTOCOL maximum rather than a data-derived one (proto reserved `to max` = 536_870_912; field numbers, varint widths, port ranges, unicode planes)"
  - "The expansion sits inside a default-on rule, hook, or validator that runs per-item, so one hostile-or-merely-idiomatic declaration multiplies across the whole traversal"
  - "A sibling module in the same repo already solved the identical hazard and the older instance was never swept for"
  - "Every covering test uses a minimum-viable fixture that satisfies the assertion without approaching the boundary"
tags:
  - reserved-ranges
  - oom
  - memory-exhaustion
  - protocol-maximum
  - half-open-ranges
  - membership-test
  - minimum-viable-fixture
  - backport-sweep
  - compat-checker
---

# A protocol-maximum range expanded into a set OOMs the process

## Context

`protokit compat check | ci | history | bisect` runs a catalogue of
backward-compatibility rules over every visited message pair. One of them,
`reserved_field_reused`, answers a single question per field: *is this field
number inside a range the old schema reserved?*

It answered that question by materializing the ranges:

```python
def _reserved_numbers(desc) -> set[int]:
    dp = descriptor_pb2.DescriptorProto()
    desc.CopyToProto(dp)
    numbers: set[int] = set()
    for rng in dp.reserved_range:
        numbers.update(range(rng.start, rng.end))   # <-- materialization
    return numbers
```

## The problem

`reserved 1000 to max;` is a **standard, recommended proto idiom** — it is what
you write when you retire a block of field numbers permanently. It round-trips
through `CopyToProto` as `end = 536_870_912` (the protobuf field-number
ceiling).

So one ordinary line of schema asked Python for a set of **536,869,912
integers**. Measured growth on the real code path:

| reserved width | peak allocation | time |
|---|---|---|
| 10K | 0.8 MB | 0.002 s |
| 1M | 70.5 MB | 0.195 s |
| 10M | 588.4 MB | 1.994 s |
| **`to max` (536.8M)** | **~32 GB (extrapolated)** | **~107 s** |

`reserved_field_reused` is a **default** rule dispatched on every visited
message pair, so the cost is not paid once — it is paid per pair, and the first
one never finishes. The process is OOM-killed. There is no error, no exit code,
no partial report: the compat gate simply dies.

Three properties made this worse than a normal performance bug:

1. **The trigger is idiomatic, not adversarial.** No attacker is required. A
   maintainer following protobuf's own guidance for retiring field numbers
   triggers it.
2. **It is a default rule.** Users cannot avoid it without knowing to disable it.
3. **The failure mode is process death**, which in CI reads as an infrastructure
   flake rather than a protokit bug.

## The fix

The only operation ever performed on the expanded set was `fd.number in
old_res_numbers`. Membership over a handful of intervals does not need the
intervals expanded:

```python
def _reserved(desc) -> tuple[tuple[tuple[int, int], ...], set[str]]:
    """...Ranges are deliberately not materialized: a valid `reserved N to max;`
    emits end = 536_870_912, so set(range(...)) would allocate ~5e8 ints..."""
    dp = descriptor_pb2.DescriptorProto()
    desc.CopyToProto(dp)
    ranges = tuple((rng.start, rng.end) for rng in dp.reserved_range)
    return ranges, set(dp.reserved_name)


def _is_reserved(number: int, ranges: tuple[tuple[int, int], ...]) -> bool:
    """Whether ``number`` falls in any half-open reserved range."""
    return any(start <= number < end for start, end in ranges)
```

Post-fix, measured on the same path:

| reserved width | peak allocation | time |
|---|---|---|
| 10K / 1M / 10M / **`to max`** | **~1.9 KB (flat)** | **~0.02 ms** |
| 1000 separate ranges | 126 KB | 0.79 ms |

Memory is now **O(number of ranges)** instead of O(total range width) — flat
across every width, because the width never enters the representation.

Two details worth keeping:

- **Half-open semantics are load-bearing.** `range(start, end)` was exclusive at
  the top; `start <= n < end` must stay exclusive. Drifting to `<=` silently
  reserves one extra number per range. This is pinned by its own test rather
  than left to reviewer attention.
- **Both halves come back from one `CopyToProto`.** Reading reserved data
  requires a descriptor roundtrip on the upb backend, and that roundtrip — not
  the set — was the rule's *other* cost. Returning ranges and names together
  halves it.

## The obvious fix has its own trap: O(width) traded for O(fields x ranges)

The first version of this fix replaced the set with a linear scan:

```python
def _is_reserved(number, ranges):
    return any(start <= number < end for start, end in ranges)   # O(R) per field
```

That is correct, and it fixes the memory blow-up completely. It also
**replaces a memory denial of service with a CPU one**. The rule runs the
membership test once per new field, so the cost is O(fields x ranges) — and a
schema that retires field blocks piecemeal accumulates many small reserved
ranges legitimately.

Measured on real descriptors:

| ranges x fields | set (original) | linear scan | binary search |
|---|---|---|---|
| 1,000 | — | 0.0249 s | 0.0007 s |
| 5,000 | — | 0.6001 s | 0.0042 s |
| 10,000 | 0.003 s | **2.3994 s** | **0.0080 s** |

The linear scan was **~800x slower than the set it replaced** at 10k x 10k. The
set form was O(1) per lookup; giving that up for O(R) is a real regression that
the "obvious" fix hides behind its correctness.

The fix for the fix: normalize once per message pair — sort, drop vacuous
ranges, merge overlapping and adjacent ones — then binary-search:

```python
idx = bisect.bisect_right(ranges, number, key=lambda r: r[0]) - 1
return idx >= 0 and number < ranges[idx][1]
```

O(R log R) once plus O(log R) per field, and the merge step collapses the
overlaps real schemas accumulate. Back to 0.008 s at 10k x 10k.

**Generalize: when you remove a materialized index, you are removing an index.**
Materialization is usually buying O(1) lookup. Deleting it because it costs too
much memory silently sells the lookup complexity too. Check what the structure
was *for* before replacing it with a scan — and measure the replacement at
adversarial scale, not just at the scale that broke.

Behavior-preservation was verified by differential testing against the original
implementation: 311 range configurations (inverted, empty, adjacent,
overlapping, nested, duplicate, reverse-order, plus 300 random) x 72 probe
values = 22,392 comparisons, zero divergence. When you replace a data structure
whose semantics came free (`range()` handles inverted and empty ranges by
producing nothing), differential-test the replacement rather than reasoning
about the edge cases — the free semantics are exactly the ones nobody
remembers to re-implement.

## A regression test for resource exhaustion must fail safely

The first regression guard fed the real ceiling through the public rule:

```python
build_message(..., reserved_ranges=[(1000, 536_870_912)])   # the true `to max`
...
assert peak < 1_000_000
```

That looks maximally rigorous — test the actual protocol maximum — and it is
**broken as a regression test**. If someone reintroduces `set(range(...))`, this
test attempts the ~32 GB allocation *before* reaching its assertion. The pytest
worker is OOM-killed. Instead of a readable assertion failure naming the
defect, CI reports a dead worker, or the developer's machine starts swapping.

A regression test is a *detector*, and a detector that reproduces the
catastrophe it detects is not one. Measured allocations:

| expansion width | tracemalloc peak | exceeds a 1 MB ceiling? | safe to run? |
|---|---|---|---|
| 10,000 | 0.8 MB | no | yes |
| **100,000** | **8.8 MB** | **yes, by ~9x** | **yes** |
| 536,869,912 (`to max`) | ~32 GB | yes | **no — OOM** |

100k separates fixed-from-broken by ~9x while allocating single-digit
megabytes if the defect returns. The protocol maximum still gets pinned, but
at the *helper* level (`_normalize_ranges` / `_is_reserved`), where no code path
can expand anything regardless of what the rule does.

**The rule: pick the smallest input that separates fixed from broken by a
comfortable margin, and pin the true extreme somewhere it cannot detonate.**
This is in direct tension with the minimum-viable-fixture lesson below, and the
resolution is to be deliberate about which property each test carries —
*functional* coverage wants the real protocol maximum, *resource* guards want
the smallest input with a decisive signal.

## Why it survived a 3148-test suite

This is the part worth generalizing.

`reserved_field_reused` was **well tested**. Four tests covered it: fires on
number reuse, fires on name reuse, silent when reservations are unused, and
fires twice when a field reuses both. Severity split asserted. Message contents
asserted.

Every one of them used the same fixture:

```python
reserved_ranges=[(5, 10)]
```

A **five-integer** range. `set(range(5, 10))` is instant. The tests pinned the
rule's **logic** completely and its **cost** not at all — and a green test
suite is not a place anyone goes looking for a gap.

The fixture was not lazy. It was chosen as *the smallest value that makes the
assertion meaningful*, which is normally good practice: small fixtures are
readable and fast. The failure is that for this subject, the risk did not live
in the logic. It lived at a boundary the fixture had no reason to approach.

**The generalizable rule:** when a function accepts a range, size, count, depth,
or any other quantity whose ceiling is set by a *protocol* rather than by your
data, at least one test must use the protocol's actual maximum. Not a large
number — *the* number. `(5, 10)` and `(1000, 536_870_912)` exercise identical
logic and completely different machines.

The regression guard added here asserts **peak allocation**, not wall time:

```python
tracemalloc.start()
findings = reserved_field_reused(old_d, new_d, ROOT)
_, peak = tracemalloc.get_traced_memory()
tracemalloc.stop()
assert len(findings) == 1                      # still detected
assert peak < 1_000_000                        # ~2 KB actual
```

The defect was an allocation, so allocation is what the test pins. A timing
assertion would be flaky on a loaded CI box and would not fail at all if someone
reintroduced the expansion on a fast machine. The 1 MB ceiling is ~500x the real
figure and still fails by four orders of magnitude if the set returns.

## The sweep that did not happen

The fix already existed **in this repository**. `protokit.forensics._drift`
was written weeks later and carries:

```python
def _reserved_ranges(descriptor) -> tuple[tuple[int, int], ...]:
    """Deliberately not materialized into a set: a valid ``reserved N to max``
    emits ``end = 536_870_912``, so ``set(range(...))`` would allocate ~5e8 ints
    and OOM. Membership is the only use -- see :func:`_is_reserved`."""
```

That docstring was written during a code review of the forensics work. The
author recognised the hazard, avoided it, and documented *why* — and the
identical construct sat untouched in `schema/rules.py`, older and reachable
from four CLI subcommands.

**When a review turns up a hazard and you fix it locally, grep for the
construct across the repo before closing.** The lesson is cheap at that moment
and expensive later: the reviewer already has the pattern loaded, already knows
what a violation looks like, and is the last person who will think about it for
months. A one-line `rg 'set\(range\(' src/` would have found this.

This applies to any hazard class with a recognisable syntactic signature —
materialized ranges, bare `except Exception`, unguarded path joins,
`sys.exit` inside a callback. See
[released-memoryview-mergefromstring-segfault-bypasses-on-error](../security-issues/released-memoryview-mergefromstring-segfault-bypasses-on-error-2026-05-30.md)
for a hazard that was correctly swept, and
[recursive-proto-schema-segfaults-ptars-arrow-build](../security-issues/recursive-proto-schema-segfaults-ptars-arrow-build.md)
for the same "reject before the expensive layer" shape applied to schema
topology.

## Checklist

- [ ] Does this code expand a range into a collection when membership is the only use? Keep pairs.
- [ ] Is the range's ceiling a protocol constant rather than a data-derived one? Assume the maximum will appear in real input.
- [ ] Does the expansion sit inside a default-on, per-item rule? Multiply the cost by the traversal before judging it acceptable.
- [ ] **What was the materialized structure buying?** If it was O(1) lookup, does the replacement keep it, or did you silently sell it for O(R) scanning?
- [ ] Did you measure the replacement at ADVERSARIAL scale (many ranges x many fields), not just at the scale that broke?
- [ ] Did you differential-test the replacement against the original across inverted, empty, adjacent, overlapping, nested and duplicate inputs? The old structure handled those for free.
- [ ] Do the covering tests use the protocol maximum, or the smallest value that makes the assertion pass?
- [ ] Does the regression test pin the resource that actually failed (allocation), not a proxy (wall time)?
- [ ] **Does the regression test FAIL SAFELY?** If the defect returns, does it produce a readable assertion failure — or does it reproduce the exhaustion and kill the runner before asserting?
- [ ] Did you `rg` for the construct elsewhere in the repo before closing the fix?
- [ ] Did an INDEPENDENT reviewer see the fix? Both the quadratic and the unsafe regression test in this document were found by a second-opinion review after the author had verified the fix and believed it correct.
