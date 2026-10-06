---
title: "A typed-exception boundary leaks wherever a catch list names one runtime backend's exception shapes"
date: 2026-09-27
category: docs/solutions/best-practices
module: protokit._pools
problem_type: best_practice
component: tooling
severity: high
applies_when:
  - "A docstring, CLI exit contract or exception taxonomy promises one typed error for input that goes through protobuf's parser or DescriptorPool.Add"
  - "A catch list around a protobuf parse or pool call names specific exception types"
  - "A string field from untrusted protobuf input is read after the call that parsed it, which upb allows to fail lazily"
  - "A new CLI or engine entry point parses descriptor sets or message payloads itself instead of going through protokit._pools"
symptoms:
  - "protokit lint, forensics or storage crashed with a traceback and exit 1 on a malformed descriptor set under the pure-Python runtime, instead of a typed error and exit 2"
  - "On upb a descriptor set with a non-UTF-8 file name loaded, then failed wherever a lint rule read the file's name"
root_cause: incomplete_implementation
resolution_type: code_fix
related_components:
  - testing_framework
  - development_workflow
tags: [cross-backend-testing, pure-python-backend, upb, descriptor-pool, typed-exceptions, sibling-blindness, mutation-testing]
---

# A typed-exception boundary leaks wherever a catch list names one runtime backend's exception shapes

## Context

protokit promises callers one typed error family at its descriptor boundary.
In 0.16.0 U16 the `load_pool_from_path` docstring was corrected to say "A file
that does not parse or build raises `DescriptorPoolError`"
(`src/protokit/_pools.py:229-230`). Making that sentence true under both
protobuf runtime backends (upb, the compiled default, and pure-Python) took
five rounds. A different verifier found each one.

The problem was the same every time. A catch list named the exceptions one
backend raises, and the other backend raised something else. This happens at
every site that parses a descriptor set or message payload, and at every site
that builds a descriptor into a pool. On upb it can also happen lazily, well
after both calls have returned.

| Round | Site kind | What escaped | Found by |
|---|---|---|---|
| 1 | Build (`add_and_resolve`, lint's inline Add-then-probe) | pure-Python `ValueError` / `IndexError` / `AttributeError` past a `(TypeError, KeyError, ...)` catch | cross-model adversarial code review |
| 2 | Parse (`load_pool_from_bytes`, lint's parse site) | pure-Python `UnicodeDecodeError` / `RecursionError` past `except DecodeError`; upb `bytes` names broke the cycle message with `TypeError` | cross-model falsification pass |
| 3 | Parse (forensics and storage CLIs' own descriptor-set parsing) | the same pure-Python shapes | refuter pass |
| 4 | Lazy (upb) plus payload parse sites | a non-UTF-8 file name survived `Add` on upb and raised `UnicodeDecodeError` at first `.name` read; payload parses let pure-Python shapes through | refuter pass |
| 5 | The round-4 fix itself | the new UTF-8 walk crashed on valid map-valued options and skipped group-typed options | second refuter pass |

In the reproduction, a lint run on pure-Python crashed with a
traceback and exit 1 where it should have printed `error[lint-pool-conflict]`
and exited 2. `protokit forensics` crashed the same way because it catches only
`(StorageError, DescriptorPoolError)` (`src/protokit/forensics/cli.py:57`).

## Guidance

### 1. List every site before fixing any of them

Fixing the site in the bug report and waiting for review to find the rest is
what made this take five rounds. Grep for all of them first:

```sh
grep -rnE 'ParseFromString|MergeFromString|FromString\(' src
grep -rnE '\.Add\(' src
```

Mark each hit as user input or not. At the end of U16 the parse sites marked as
user input were the seven below, and all seven are still where the grep finds
them after 0.16.0's re-audit fix wave:

- descriptor sets: `src/protokit/_pools.py:218`,
  `src/protokit/schema/lint/_cli_utils.py:353`,
  `src/protokit/forensics/cli.py:135`, `src/protokit/storage/cli.py:315`
- message payloads: `src/protokit/forensics/_match.py:133`,
  `src/protokit/storage/engine.py:319`, `src/protokit/message/cli.py:125`

The two parse sites that were left alone at U16 were taken to read bytes
protokit produced itself: protoc's output at `src/protokit/_cli_utils.py:558`,
and a re-serialized options message at `src/protokit/_extensions.py:103`. The
second one does read user input. On an isolated pool a custom option's bytes
stay unparsed in the options message until that re-read gives them a type, so a
malformed option first fails there. Since the fix wave the site catches
`DecodeError` and `UnicodeDecodeError` and falls back to a second parse of only
the requested option's records (`_only_extension`,
`src/protokit/_extensions.py:156`), which raises both as `DecodeError`. Neither
catch names `RecursionError`. The grep now also finds
`FileDescriptorProto.FromString(file.serialized_pb)` twice in
`src/protokit/_fieldview.py` (in `may_hold_unvalidated_string` and
`StringWalk._is_proto3`). Both re-read a file the pool has already built.

The build sites are `add_and_resolve`
(`src/protokit/_pools.py:182-183`) and lint's inline copy
(`src/protokit/schema/lint/_cli_utils.py:400` and `src/protokit/schema/lint/_cli_utils.py:412`). Every other product caller
goes through `add_and_resolve` or `build_pool`.

### 2. Know which shapes each backend raises

(provenance — observed on protobuf 5.27.5 under both backends; the exception
types can change between releases, and what stays re-asserted on both backends
is the outcome, a typed error or a clean load, by the regression tests named below.
No test re-asserts the two payload rows marked "open": there the backends reach
different outcomes, and section 4 says why they are left that way.)

| Site kind | Input | upb | pure-Python |
|---|---|---|---|
| Build (`Add` + `FindFileByName`) | int default `"abc"` | `TypeError` | `ValueError` |
| Build | `oneof_index` / `public_dependency` out of range | `TypeError` | `IndexError` |
| Build | field with no type | accepted | `AttributeError` |
| Build | dangling `type_name` | `TypeError` from `Add` | `KeyError`, but only when resolution is forced (`Add` returns cleanly) |
| Build | same file name, different content | `TypeError` | `DescriptorDatabaseConflictingDefinitionError` (`src/protokit/_pools.py:157-159`) |
| Build | duplicate field number, field number 0, empty message name, bad `syntax` | `TypeError` | accepted |
| Descriptor-set parse | non-UTF-8 string (e.g. file name `0xff`) | parses; the field comes back as `bytes` | `UnicodeDecodeError` |
| Descriptor-set parse | 2000 nested messages / 500 nested groups | `DecodeError` | `RecursionError` |
| Payload parse | non-UTF-8 proto3 string | `DecodeError` | `UnicodeDecodeError` |
| Payload parse | non-UTF-8 proto2 string, or editions string with `utf8_validation = NONE` | parses; the field comes back as `bytes` | `UnicodeDecodeError` |
| Payload parse | nesting past both parsers' limits (2000 messages deep) | `DecodeError` | `RecursionError` |
| Payload parse (open) | nesting between the two limits (101 to a few hundred messages deep) | `DecodeError` | parses |
| Payload parse (open) | a set extension of a `message_set_wire_format` message | parses | `NameError` from protobuf's own decoder |
| Lazy (after `Add`) | non-UTF-8 file name | `UnicodeDecodeError` wherever `.name` is read | (already rejected at parse) |

The two parsers stop at different depths (provenance — protobuf 5.27.5 on
Python 3.13 under both backends; nothing re-asserts these numbers). upb counts
nested messages and refuses the 101st with `DecodeError`, whatever the
interpreter's recursion limit. Pure-Python has no limit of its own: it recurses
until the interpreter's limit runs out, so its depth depends on that limit and
on how deep the call stack already is. In a bare script it parsed 496 nested
messages and raised `RecursionError` on the 497th at the default limit of 1000,
and parsed 1496 at a limit of 3000.

The last build row matters for wording. Pure-Python accepts several sets that
upb rejects, so the docstring cannot promise that "a malformed file raises". It
can only promise that a file which "does not parse or build" raises.

### 3. Build sites: `except Exception` around only the protobuf calls

```python
# src/protokit/_pools.py:178-188
# Broad on purpose: the try holds only the two protobuf calls, and their
# rejection shapes vary by backend and version (see above). BaseException
# (KeyboardInterrupt, SystemExit) is not caught and still propagates.
try:
    pool.Add(fd)
    pool.FindFileByName(fd.name)
except Exception as exc:
    raise DescriptorPoolError(
        f"could not build file {fd.name!r} into the descriptor pool: {exc}"
    ) from exc
```

Before U16 this caught `(TypeError, KeyError, DescriptorDatabaseConflictingDefinitionError)`,
and lint's copy caught `(TypeError, ValueError, KeyError)`. Pure-Python's
descriptor constructor raises whatever its internal code happens to trip over.
`AttributeError: 'NoneType' object has no attribute 'values'` for a typeless
field is one example. A list of those shapes can't be complete and could change
in any protobuf release. The try contains nothing except the two protobuf calls,
so a broad catch can't hide a protokit bug. The original exception stays on
`__cause__`. Lint's copy uses the same form
(`src/protokit/schema/lint/_cli_utils.py:413-422`), and its routing is
unchanged. A `KeyError` or a missing-import marker goes to
`error[lint-missing-imports]`, and everything else goes to
`error[lint-pool-conflict]`.

Caveat: a broad catch also converts a warning that strict-warning mode turns
into an error (see the related DeprecationWarning learning below). Pure-Python
`Add` emits a `RuntimeWarning` on a conflict. Keep the protobuf calls alone in
the `try` and keep `from exc`.

### 4. Parse sites: an explicit tuple

```python
except (DecodeError, UnicodeDecodeError, RecursionError) as exc:
```

This tuple appears at `src/protokit/_pools.py:219`,
`src/protokit/forensics/cli.py:136`, `src/protokit/forensics/_match.py:134`,
`src/protokit/storage/engine.py:320` and `src/protokit/message/cli.py:126`.
Storage and lint add `OSError` because their `try` also reads the file
(`src/protokit/storage/cli.py:316`,
`src/protokit/schema/lint/_cli_utils.py:354-356`). Parse sites don't use a broad
catch for two reasons:

- These `try` blocks hold more than the protobuf call. The storage engine's
  block holds `bytes(raw)`, which is deliberately allowed to raise `ValueError`
  for a released memoryview and fail loud (`src/protokit/storage/engine.py:312-316`).
  A broad catch would turn that into a per-record `FrameError`.
- The decoder's failure set is small and tied to what it checks: wire format
  (`DecodeError`), UTF-8 (`UnicodeDecodeError` on pure-Python) and depth
  (`RecursionError` on pure-Python). Tolerant-iteration sites need a narrow,
  typed catch so a programming error does not become a data fault.

Every parse site gives all three shapes the same handling it gives
`DecodeError`. That makes a parse *failure* typed on both backends. An earlier
version of this section went further and said the result doesn't depend on the
backend. A re-audit disproved that: a catch tuple can only convert an exception,
and for three kinds of payload one backend raises nothing, or raises a shape the
tuple leaves out. (provenance — each case below was measured on protobuf 5.27.5,
Python 3.13, under both backends; the exit codes are those of `storage count`,
`forensics match` and binary `diff`.)

**A proto2 string that is not UTF-8: fixed, by a walk after the parse.** upb
does not validate a proto2 string, or an editions string with
`utf8_validation = NONE`. It parses the payload and hands the field back as
`bytes`, at any depth. Pure-Python raises `UnicodeDecodeError` while parsing.
So until 0.16.0's re-audit fix wave, upb counted such a record (`storage count`
exit 0), ranked it `clean` (`forensics match` exit 0) and compared its raw bytes
(`diff` exit 0 or 1), where pure-Python exited 2 from all three. Each payload
seam now walks the parsed message and reports a string that came back as
`bytes` as its own decode fault, so both backends exit 2:

- the storage engine keeps one `StringWalk` for the whole scan
  (`ScanResult._iterate` in `src/protokit/storage/engine.py`) and dispatches a hit
  as a `FrameError` through `on_error`;
- `fit_candidate` (`src/protokit/forensics/_match.py:139`) records it as a
  `decode_error` fit;
- `_parse_message` (`src/protokit/message/cli.py:134`) exits 2 for binary input.
  Text and JSON input skip the walk, because both of those parsers reject such
  a string on both backends.

The walk is `first_undecodable_string`, the one section 5 describes. It runs
after each seam's `try`, not inside it, so a bug in the walk is not recorded as
a data fault. Only the verdict matches across backends. The message differs:
the walk's `string field <name> is not valid UTF-8` on upb, the decoder's own
text on pure-Python. The outcome is re-asserted on both backends by
`TestProto2StringsThatAreNotUtf8` in `tests/storage/test_engine.py` and in
`tests/message/test_cli.py`, and by
`test_a_proto2_string_that_is_not_utf8_is_a_decode_error` in
`tests/forensics/test_match_core.py`.

Two limits of the walk, each measured on upb:

- It reads only fields that can hold an unvalidated string, and skips a type
  that has none, such as one built only from proto3 files. That rule
  (`may_hold_unvalidated_string`) assumes protobuf's standard feature defaults.
  A caller-built pool given custom `FeatureSetDefaults` that turn proto3
  validation off gets `bytes` back from upb, and the walk skips the type.
  protokit's own loaders never set custom defaults.
- It reads the parsed message, not the wire. A singular proto2 string written
  twice, with a first copy that is not UTF-8 and a valid last copy, parses on
  upb to the last value, and the walk finds nothing. Pure-Python faults on the
  first copy. The descriptor-set walk has the same limit.

**Nesting between the two parsers' limits: not fixed.** Section 2 has the two
limits. A payload nested deeper than upb's 100 messages but short of
pure-Python's recursion limit faults on upb and parses on pure-Python. A
payload nested 480 deep exited 2 from all three commands on upb and 0 on
pure-Python. Each backend's failure is typed. The two just disagree about
which payloads fail.

**`NameError` from protobuf's own decoder: left out of the tuple on purpose.**
A set extension of a message with `message_set_wire_format = true` parses on
upb. Pure-Python's decoder raises
`NameError: name 'message_factory' is not defined` from inside protobuf, and
all three commands exit 1 with a traceback. `NameError` is the shape of a
programming error, and a tuple wide enough to catch it would also turn
protokit's own bugs into data faults, which the narrow tuple exists to prevent.
So the narrow tuple does not make every payload failure typed.

### 5. upb needs a UTF-8 walk at the boundary

On a proto2 descriptor set, upb doesn't check UTF-8 while parsing. It returns the
string field as `bytes` (provenance — protobuf 5.27.5 upb; the outcome is
re-asserted by the upb-only test named under Examples). A bad package or type name then fails at `Add`, which is
already converted. A bad **file name** gets through `Add` and only raises
`UnicodeDecodeError` later, when something reads `.name`. In lint that read
happened inside a rule, and again inside the engine's `rule_exception` handler.
Separately, the cycle error message's `', '.join(remaining)` raised `TypeError`
on a `bytes` name, so it now joins `map(repr, remaining)`
(`src/protokit/_pools.py:135`).

The fix is `require_decodable_strings(fds)` (`src/protokit/_pools.py:255-278`).
It walks every string field and raises `DescriptorPoolError` on any `bytes`
value. The walk itself is `first_undecodable_string`
(`src/protokit/_fieldview.py:247-271`), which runs a `StringWalk`
(`src/protokit/_fieldview.py:410-547`), in the layer-0 seam so the payload
decode seams can share it. It runs in `build_pool` (`src/protokit/_pools.py:200`) and at lint's parse
site (`src/protokit/schema/lint/_cli_utils.py:353`), and after each payload parse in storage
scans, `forensics match` and binary `diff` input, each of which reports a hit as its own
decode fault. This isn't new validation.
It makes upb reject, at the same point pure-Python already does, any string the
parsed message still holds as `bytes`. Section 4 lists the two cases the walk
does not reach.

The first version of the walk had two bugs, and a later audit found a third.

- **A protobuf map iterates its keys.** The first version pushed each key
  string onto the stack as if it were a message. On a valid set with a
  map-valued custom option (a `google.protobuf.Struct` extension on
  `FileOptions`), it crashed on both backends with
  `AttributeError: 'str' object has no attribute 'ListFields'`. The fix reads the
  map-entry descriptor and walks keys and values as pairs (the extension path
  at `src/protokit/_fieldview.py:278-284`; the planned walk's map branch at
  `:477-489` keeps the same order):
  ```python
  entry = map_entry(field)
  if entry is not None:
      yield from ((entry.key, k) for k in value)
      yield from ((entry.value, v) for v in value.values())
  ```
- **Groups are messages too.** The walk descended only into `TYPE_MESSAGE`, so a
  non-UTF-8 string inside a group-typed option still loaded on upb. It now
  descends into `(TYPE_MESSAGE, TYPE_GROUP)` (`src/protokit/_fieldview.py:221`).
- **Reading a map's values re-reads its keys.** On upb, iterating a proto2 map
  whose key is not UTF-8 yields that key as `bytes`, but `values()` looks each
  key up again and raises `UnicodeDecodeError` (provenance — protobuf 5.27.5
  upb; the outcome is re-asserted by the test named below). The walk read values before it
  checked keys, so a map-valued custom option with a bad key escaped
  `load_pool_from_bytes` raw on upb. It now yields every key, and returns on a
  bad one, before it reads any value
  (`tests/core/test_pools.py::test_a_non_utf8_map_key_in_an_option_raises_the_typed_error`).

Custom options are covered only because `ListFields()` includes registered
extensions (`src/protokit/_fieldview.py:491-492`). An unregistered extension stays
as unparsed unknown bytes that nothing decodes, so nothing needs to walk it.

After the fix, all 150 compilable `.proto` fixtures under
`tests/` (compiled with source info) loaded through the walk on both backends
with 0 rejections.

## Why This Matters

- **A suite green on both backends still says nothing about inputs it never
  sends.** Every round passed the full suite under both backends. The leaks
  were in malformed inputs no test sent, and each one reached a branch that
  only one backend takes.
- **Every fix to a boundary adds new code the boundary depends on.** Round 5 was
  a regression the round-4 fix introduced on valid input. Check the new
  boundary code as hard as the old sites.
- **The failure is a crash, not a wrong answer.** A raw exception reaching click
  becomes exit 1 plus a traceback, with no `error[...]` code. Scripts that branch
  on protokit's exit-2 contract then treat bad input as an internal error.

## When to Apply

- A docstring, CLI contract or exception taxonomy says "X raises
  `SomeTypedError`" and X calls protobuf's parser or `DescriptorPool.Add`.
- A catch list around a protobuf call names specific exception types.
- A string field from untrusted protobuf input is read after the call that
  parsed it (upb's lazy `bytes`).
- You add a new CLI or engine entry point that parses descriptor sets or
  payloads itself instead of calling `_pools`.

## Examples

### Regression tests, one per shape

- Build shapes: `TestAddAndResolveBackendValidation` in
  `tests/core/test_pools.py:237`. It parametrizes the pure-Python-rejected shapes
  and asserts `DescriptorPoolError` with a `__cause__`. For the typeless-field
  shape, which upb accepts, it asserts only that nothing escapes raw.
- Parse shapes: `TestLoadPoolFromBytesParseFailures`
  (`tests/core/test_pools.py:281`). It covers a non-UTF-8 name, the same name in a
  cycle, a non-UTF-8 message name, and a 2000-deep nesting built from raw
  varints.
- The upb-only premise is pinned with `skip_under_pure_python(...)` and a stated
  reason (`tests/core/test_pools.py:309-317`). On pure-Python the parser rejects
  the input before the walk runs.
- CLI exit codes: `test_descriptor_the_runtime_rejects_routes_to_pool_conflict`
  and `test_file_name_that_is_not_utf8_routes_to_bad_input`
  (`tests/schema/lint/cli/test_cli_input_modes.py:378` and
  `tests/schema/lint/cli/test_cli_input_modes.py:405`),
  `test_desc_the_runtime_cannot_parse_exits_2`
  (`tests/forensics/cli/test_match.py:195`),
  `test_descriptor_set_the_runtime_cannot_parse_is_exit_2`
  (`tests/storage/cli/test_schema_flags.py:131`),
  `test_a_message_nested_too_deep_exits_2` (`tests/message/test_cli.py:814`).

### Three test-writing traps

1. **Pure-Python decodes a registered extension only after it has been looked
   up.** Until `FindExtensionByName` runs, the option stays as unknown bytes. The
   first group-option test registered the extension but never looked it up. On
   pure-Python it passed for the wrong reason: the set loaded because nothing
   decoded the bad string. The scenario now calls
   `dp.Default().FindExtensionByName("opt.group_opt")` first
   (`tests/core/test_pools.py:348-349`). The assertion also checks that the error
   names `opt.Opt.s` (`tests/core/test_pools.py:397-398`), which proves the
   string caused the failure and not some other part of the set.
2. **A registration in the global default pool leaks into later tests.** The
   custom-option scenarios run in a fresh interpreter
   (`tests/core/test_pools.py:369-382`). `env={**os.environ, ...}` passes the
   `PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION` choice through to the child.
3. **Mutation-prove every new test under the backend its fix is for.** Run
   `python3 scripts/mutation_check.py <file> <old> <new> <pytest-target>` with the
   env var set to that backend. A proof run under the other backend can come back
   VACUOUS for a correct test, because that backend never reaches the predicate.
   In this unit, a VACUOUS verdict on the group-traversal test exposed a **wrong
   test**. The scenario appended the hand-built option file to a set that already
   had a file of that name, so `DuplicateFileError` fired before the walk ran and
   the test passed with the walk broken. The fix was right and the test was
   wrong, and only the mutation proof showed it.

## Secondary: edits that don't move cited line numbers

Published learnings cite `src/protokit/_pools.py:251`,
`src/protokit/schema/lint/_cli_utils.py:259-422` and `:534-552`, many ranges in
`tests/meta/test_import_layers.py`, and `tests/core/test_pools.py:68-74`. Every
U16 edit kept each cited range pointing at the same text:

- Rewrap a comment to free a line.
- Fold a new call into an existing line
  (`require_decodable_strings(...FromString(data))` at
  `src/protokit/schema/lint/_cli_utils.py:353`).
- Put new code below the last cited line.
- Use a function-level import instead of a new top-level one
  (`tests/core/test_pools.py:371-374`, `src/protokit/_pools.py:271`).

To verify, compare `git show <base>:<path>` slices with the working file for
every `path:NNN(-MMM)` citation. One review fix shifted about 15 citations in
`tests/meta/test_import_layers.py` by 6 lines, and this check caught it.

## Related

- `docs/solutions/best-practices/sibling-blindness-fix-survives-review-structural-siblings-stay-broken.md`:
  the general pattern behind rounds 1 to 3
- `docs/solutions/best-practices/wire-filedescriptorproto-dependency-through-pool-pure-python-vs-upb.md`:
  pure-Python's lazy resolution, the reason `FindFileByName` follows `Add`
- `docs/solutions/best-practices/pure-python-backend-known-failure-inventory-ci-harvest.md`
- `docs/solutions/best-practices/deprecationwarning-poisons-except-exception-strict-warning-ci-2026-05-11.md`:
  the cost of a broad catch
- `docs/solutions/design-patterns/tolerant-iteration-error-taxonomy-narrow-catch-loud-completion-guard-2026-05-30.md`:
  why payload parse sites stay narrow
- `docs/solutions/logic-errors/mutation-check-harness-stale-bytecode-and-nonverdict-exit-codes-produce-false-verdicts.md`
