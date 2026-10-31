---
title: "Under upb, reading a repeated extension a message does not hold gives it one, so compare() changed the caller's message"
date: 2026-10-26
category: docs/solutions/logic-errors
module: protokit._fieldview
problem_type: logic_error
component: tooling
symptoms:
  - "After `MessageDifferencer.compare(left, right)` with a repeated extension set on one side only, the other side's `ListFields()` lists `(ext, [])` and it no longer equals an untouched copy (`==` is False), although its serialized bytes are unchanged"
  - "Later comparisons of the same message disagree with the first: the differ asks `ListFields()` whether a message is empty, so an element that was empty counted as populated and its ADDED difference was dropped"
  - "upb only (protobuf 4.25.9, 5.27.5 and 5.29.6); pure-Python creates nothing on read, so a suite run only under pure-Python stays green"
  - "The two obvious presence checks fail: `fd in msg.Extensions` kills the process with SIGSEGV (exit 139) under upb, and `msg.HasExtension(fd)` raises KeyError for a repeated extension on both backends"
root_cause: wrong_api
resolution_type: code_fix
severity: high
framework_version: "protobuf 4.25.9, 5.27.5, 5.29.6 (upb backend)"
retire_when: "A protobuf release where, under upb, reading `msg.Extensions[fd]` for an unheld repeated extension leaves `msg.ListFields()` empty and `fd in msg.Extensions` returns False instead of crashing; check by running the read and the `in` test in a fresh subprocess against the new release"
related_components: [testing_framework]
tags:
  - proto2-extensions
  - upb
  - read-side-effect
  - caller-mutation
  - segfault
  - cross-backend-testing
  - message-equality
---

# Under upb, reading a repeated extension a message does not hold gives it one, so compare() changed the caller's message

## Problem

Under the upb backend, `msg.Extensions[fd]` for a repeated extension that `msg`
does not hold is not a read: it creates an empty container on `msg`. protokit's
differ reads an extension that is set on one side from both sides, so
`MessageDifferencer.compare()` (and everything built on it: `diff_messages`,
`proto_match` / `expect_proto`, the matchers) changed the caller's message. The
read came in with extension comparison itself (#69, the `_fieldview` seam). It
was not caught until the third re-audit cycle, where it was a P1 (finding E06-C1)
and the one code finding that gated the 0.16.0 release. It was fixed in #130 before
0.16.0 shipped.

## Symptoms

Verified 2026-10-26 on protobuf 4.25.9, 5.27.5 and 5.29.6, each in a fresh
process, with a proto2 `Host` message and a `repeated int32` extension of it
(the `KeyError` texts are 5.27.5's):

| Operation on a `Host()` that holds nothing | upb | pure-Python |
|---|---|---|
| `m.Extensions[ext]`, then `m.ListFields()` | `[(ext, [])]` | `[]` |
| then `m == Host()` | `False` | `True` |
| then `m.SerializeToString() == Host().SerializeToString()` | `True` | `True` |
| `ext in m.Extensions` | process dies, SIGSEGV (exit 139) | `False` |
| `m.HasExtension(ext)` | `KeyError: 'Field is repeated. A singular method is required.'` | `KeyError: '"x.vals" is repeated.'` |
| `list(m.Extensions)` | `[]`, creates nothing | `[]`, creates nothing |

The damage is invisible on the wire, so anything that round-trips through bytes
looks fine. It shows up through equality and `ListFields()`. That second one
matters inside protokit: the differ uses `ListFields()` to decide whether a
message is empty, so after one comparison a message that was empty counted as
populated, and a later comparison dropped its `ADDED`. The module docstring of
`tests/message/test_compare_leaves_inputs_unchanged.py` records this chain.

## What Didn't Work

- **`fd in msg.Extensions`.** The natural presence test. Under upb it
  dereferences a null array for an unset repeated extension and crashes the
  interpreter, on every protobuf line tested (see the table). It is not an
  exception you can catch, so a `try` around it does not help.
- **`msg.HasExtension(fd)`.** Refuses repeated extensions with `KeyError` on
  both backends, by design: presence is defined for singular fields only.
- **Reading and then clearing.** Reading `Extensions[fd]` and calling
  `ClearExtension` afterwards is O(1), but it still writes to the caller's
  message, which is the bug. It was rejected for that reason, and the walk over
  held extensions kept despite its cost: measured at about 3% on typical
  messages and about 37% on messages holding dozens of extensions, under upb
  (session history).
- **The first test set.** 88 tests that failed before the fix and passed after
  it still let two mutations through (session history). Deleting the
  `fd.label != LABEL_REPEATED` guard passed every test, because nothing pinned
  that an unheld *singular* extension still reads its default. The probe's
  "raises, so assume yes" fallback was untested too. Both now have tests
  (`:365`, `:383`).

## Solution

Ask whether the message holds the extension by iterating `msg.Extensions`,
which creates nothing, and only read when it does. Otherwise hand back a
read-only empty value of the right shape. `src/protokit/_fieldview.py`:

```python
# field_value (src/protokit/_fieldview.py:70-71)
if fd.is_extension:
    return _extensions_of(msg)[fd] if (empty := _unheld(msg, fd)) is None else empty

# _unheld (src/protokit/_fieldview.py:719, body from :738)
if (
    fd.label != _FD.LABEL_REPEATED
    or fd.containing_type is not type(msg).DESCRIPTOR
    or not _read_creates_extension()
):
    return None                       # singular, foreign, or a runtime whose read creates nothing
extensions = _extensions_of(msg)
if len(extensions):                   # O(1) under upb
    number = fd.number
    for held in extensions:           # iterating creates nothing
        if held.number == number:
            return None               # held: read it as usual
return _NO_ENTRIES if is_map_field(fd) else _NO_ELEMENTS   # MappingProxyType({}) or ()
```

`_read_creates_extension()` (`src/protokit/_fieldview.py:754`, cached) asks the
runtime once, on a throwaway message in a pool of its own: read a repeated
extension, then check `ListFields()`. Pure-Python answers no, so it pays nothing
for the check. A probe that raises answers yes, so the check runs: slower, never
wrong (`tests/message/test_compare_leaves_inputs_unchanged.py:383`).

Options messages have the same trap, with a wider blast radius. `desc.GetOptions()`
returns one cached object per descriptor, on both backends, so under upb a
direct `desc.GetOptions().Extensions[repeated_ext]` adds `(repeated_ext, [])` to
the options every later reader of that descriptor sees, process-wide (verified
2026-10-26 on 5.27.5; pure-Python leaves it empty). `rebind_options` may hand
back the options message it was given, so `_extensions._checked` reads a
repeated extension through `_repeated_value` (`src/protokit/_extensions.py:557`),
which uses the same iterate-then-read rule.

Two direct repeated reads remain: `src/protokit/options.py:173` and
`src/protokit/schema/lint/rules/options/field_behavior.py:303`. Both read what
`options_of` / `rebind_options` returned, and they are safe only when that is a
copy protokit made. For real descriptors it was in every case measured on
2026-10-26 (5.27.5, both backends): a field, oneof or method in the default pool
with an unset repeated custom option, and a field in an isolated pool, all left
`GetOptions()` empty after `get_option_value`. A default-pool extension makes
`options_of` read the options from the descriptor's file, and an isolated-pool
extension makes `rebind_options` build a fresh message.

That is a property of what those two functions return, not of the reads.
`options_of` returns `GetOptions()` itself in several cases (its docstring and
code, `src/protokit/_extensions.py:274`), and `rebind_options` returns its
input when that input's class already knows the extension. When both do,
`options.py:173` reads the caller's own options. One known case does this: a
hand-built object passed to `get_option_value` whose `GetOptions()` already
returns the extension's options type, with no matching extension in the
default pool. Under upb, that object's options gain `(ext, [])`. This was left
out of 0.16.0's scope as outside the CHANGELOG's claim about descriptors. The
test `test_a_custom_option_read_leaves_the_callers_options_unchanged` (`:452`)
pins `rebind_options` / `_checked` on that path, not the read at `:173`. A change
to either function can make those two reads mutate shared options for real
descriptors too.

## Why This Works

The side effect lives in upb's `Extensions[fd]` accessor for repeated fields: to
hand back a mutable container, it materialises one in the message. Iteration
only walks the extensions the message already holds, so it observes without
creating. Matching on `held.number` is enough because `_unheld` has already
required `fd.containing_type is type(msg).DESCRIPTOR`. An extension of another
type is left to the ordinary read, which refuses it as before
(`test_a_repeated_extension_of_another_pool_is_refused_not_read_as_empty`, `:329`).
Returning an immutable empty (`()` or `MappingProxyType({})`) keeps the value
read-only, so no later caller can append to a container the message never had.

Singular extensions are not affected: an unheld singular extension reads its
default without creating presence (`:365`), so `_unheld` returns `None` for
them and they are read as before.

## Prevention

- **Never read `msg.Extensions[fd]` for a repeated extension on a message
  protokit does not own.** Go through `protokit._fieldview.field_value` for
  message data, or `_extensions._repeated_value` for options. A descriptor's
  `GetOptions()` counts as not owned: it is shared by every reader of that
  descriptor. A direct read is safe only on a copy protokit made itself, and
  the code that relies on that (the two reads above) should say so where it
  reads.
- **Never use `fd in msg.Extensions` for a repeated extension.** It crashes the
  process under upb, and no test harness reports a segfault as a normal
  failure: the whole pytest run dies.
- **Test "inputs unchanged", not just "result right".** The regression suite
  compares every input with a pristine copy after the call, on both backends
  (`test_inputs_are_unchanged_after_comparison`, `:158`), and checks that an
  earlier comparison does not change a later one (`:219`). A test that checks
  only the returned differences passed throughout.
- **Run the suite under upb.** pure-Python never shows this, so a fix or new
  read site verified only with `PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python`
  proves nothing here. This is the reverse of the usual direction, where upb is
  the lenient backend.
- **Pin every guard in the seam, not just the failing case.** A guard that
  narrows where the workaround applies (here the repeated-label check, the
  same-type check, and the probe's fallback) needs its own test, or a mutation
  that deletes it survives (session history).
- **Probe a dangerous primitive in a subprocess.** When checking whether a
  protobuf operation crashes, run it in its own process and read the exit code
  (139 is SIGSEGV), as the table above was produced.

## Related Issues

- #130, the fix (`fix: comparing two messages changes neither of them under upb`).
- [Swallowed KeyError read custom options as absent on isolated pools](swallowed-keyerror-read-present-custom-options-as-absent-on-isolated-pools.md):
  where `rebind_options` / `_checked` come from, and its "emptiness for repeated
  ones" guard, which reads to test emptiness and so is safe only on a copy.
- [Sibling-blindness: a fix survives review while its structural siblings stay broken](../best-practices/sibling-blindness-fix-survives-review-structural-siblings-stay-broken.md):
  this defect was fixed at two sibling sites (`_fieldview`, `_extensions`), and
  the remaining direct reads are siblings by shape.
- [A typed-exception boundary leaks where a catch list names one backend's shapes](../best-practices/typed-exception-boundary-leaks-where-a-catch-list-names-one-backends-shapes.md):
  another upb/pure-Python split in the same seam, and a note on what
  `ListFields()` includes.
- [Released memoryview + MergeFromString segfault bypasses on-error](../security-issues/released-memoryview-mergefromstring-segfault-bypasses-on-error-2026-05-30.md):
  another upb crash no Python handler can catch.
