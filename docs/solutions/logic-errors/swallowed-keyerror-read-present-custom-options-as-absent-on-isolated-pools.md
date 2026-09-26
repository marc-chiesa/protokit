---
title: "get_option_value read every custom option on an isolated pool as absent, because a swallowed KeyError is indistinguishable from absence"
date: 2026-09-24
category: docs/solutions/logic-errors
module: protokit.options
problem_type: logic_error
component: tooling
severity: high
symptoms:
  - "`get_option_value(desc, option_path)` returned None for every custom option on an isolated DescriptorPool (a `build_pool` FileDescriptorSet pool or a protoxy compile pool): singular, repeated, message-typed and dotted sub-field paths alike, byte-identical to an absent option"
  - "Reproduced on BOTH backends, each refusing the extension by class identity with a KeyError even though full names match (upb 'Extension doesn't match (google.protobuf.FieldOptions vs iso.limit)'; pure-Python 'extends message type google.protobuf.FieldOptions, but this message is of type google.protobuf.FieldOptions'), which the helper's `except (KeyError, ValueError): continue` turned into absence"
  - "The option bytes were intact as unknown fields; only the class was wrong: `desc.GetOptions()` always returns the bootstrap descriptor_pb2 options class, whose extension registry knows default-pool extensions only"
  - "The protoxy option-value regression contract stayed green because it hand-rolled the pool-bound re-read inline in 5 tests and never called the public helper, and tests/core/test_options.py documented custom-pool tier-1 testing as blocked by bootstrap-pool coupling"
  - "Sibling, upb only: `options._owning_pool` raised AttributeError for MethodDescriptor and OneofDescriptor, which upb gives no `file` or `pool` attribute"
root_cause: wrong_api
resolution_type: code_fix
related_components: [testing_framework, documentation]
tags:
  - custom-options
  - proto2-extensions
  - descriptor-pool
  - broad-catch
  - silent-failure
  - sibling-blindness
  - cross-backend-testing
  - seam
---

# get_option_value read every custom option on an isolated pool as absent, because a swallowed KeyError is indistinguishable from absence

> **Citation note.** Line numbers are current-state as of the U5 change
> (unmerged as of this writing) and will drift; each is paired with a greppable
> anchor so the citation self-heals. "Before U5" citations are to the file as it
> stands on `main`. Every behavioural claim below was re-run on protobuf 5.27.5,
> Python 3.13.5, under both backends (upb, the default, and
> `PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python`). The pre-fix results come from
> executing `main`'s `options.py` against the same fixture, not from memory.

## Problem

`protokit.options.get_option_value(desc, option_path, pool=None)` is the public
helper that differ hooks and checker plugins use to read a custom option. The
differ hands hooks `left_pool` / `right_pool` for exactly this purpose
(`src/protokit/message/model.py:908-910`, anchor `left_pool: Descriptor pool`). The helper returned `None` for
**every** custom option on an isolated `DescriptorPool`: any pool built by
`protokit._pools.build_pool` from a `FileDescriptorSet`, and any protoxy compile
pool. In practice that is every schema protokit builds itself. An annotated field
and an unannotated one got the same answer, so a hook gating on
`get_option_value(...) is not None` never fired. This was audit finding V9, the
audit's headline finding.

The mechanism has two parts, and the lesson is in how they combine.

**protobuf refuses the lookup by identity, on both backends.** `desc.GetOptions()`
always returns an instance of the bootstrap `descriptor_pb2` options class
(`FieldOptions`, `MethodOptions`, and so on), whatever pool `desc` came from.
That class's extension registry knows only default-pool extensions. For an
extension declared in any other pool, `HasExtension` and `Extensions[]` raise
`KeyError` even though the full names match:

```text
upb:    KeyError "Extension doesn't match (google.protobuf.FieldOptions vs iso.limit)"
python: KeyError 'Extension "iso.limit" extends message type "google.protobuf.FieldOptions",
                  but this message is of type "google.protobuf.FieldOptions".'
```

The pure-Python message names the same type on both sides of "but", which is
what an identity check looks like when it is reported by name. The value is not
lost: the options message still carries the extension's bytes (4 serialized
bytes for `limit = 42` in the probe), and only the class reading them is wrong.
`type(desc.GetOptions()).DESCRIPTOR is ext_desc.containing_type` is `False` for
an isolated pool. For the default pool,
`message_factory.GetMessageClass(descriptor_pb2.FieldOptions.DESCRIPTOR) is
descriptor_pb2.FieldOptions` is `True`, which is why generated `_pb2` modules
never showed the problem.

**The helper turned the refusal into "absent".** Before U5 (options.py on main),
tier 1 wrapped both presence reads in a `try` whose handler was
`except (KeyError, ValueError): continue` (lines 133-153). That handler has been
there since the module's first commit (2026-04-14), and no reason was ever
recorded for `ValueError`. On an isolated pool the `KeyError` was always the
identity refusal, so the loop moved on, tier 2's `uninterpreted_option` scan
found nothing (a compiled set has interpreted options), and the function
returned `None`.

## Symptoms

Measured before the fix, on a pool built with `build_pool` from a self-contained
set, singular `int32`, singular `string`, repeated, message-typed and dotted
sub-field paths all returned `None`. That is byte-identical to the result on an
unannotated field, on both backends:

```text
upb     old annotated: None   old bare: None   new: 42
python  old annotated: None   old bare: None   new: 42
```

No exception, warning or log line appeared. Nothing inside protokit noticed,
because nothing inside protokit called the helper: `src/` has zero call sites
(only docstring references in `src/protokit/message/differ.py` and `src/protokit/message/model.py`).
Before U5, the only tests that exercised it were the 24 in
`tests/core/test_options.py`, and none of them used an isolated pool.

A sibling defect in the same helper appeared on one backend only. Before U5,
`_owning_pool` (options.py on main, lines 47-71) tried `desc.file`, then
`desc.pool`, then `desc.type.file.pool`. Under upb a `MethodDescriptor` has no
`file` and no `pool`, so it fell through to `type`:

```text
upb     old method AttributeError: 'google._upb._message.MethodDescriptor' object has no attribute 'type'
python  old method: None
```

The upb attribute layout, probed per descriptor kind: `FileDescriptor` has
`pool` but not `file`. `Descriptor`, `FieldDescriptor`, `EnumDescriptor` and
`ServiceDescriptor` have `file`. `OneofDescriptor` has only `containing_type`,
`MethodDescriptor` only `containing_service`, and `EnumValueDescriptor` only
`type`. Pure-Python gives the method and oneof descriptors a `file`.

## What Didn't Work

**The workaround already existed at two sibling sites and never reached the
helper.** Since D6d U1 and U2 (2026-05-19 and 2026-05-20) the lint package had re-read options through
a pool-bound class, written out by hand in two places: inside the synthetic-rule
closure in `src/protokit/schema/lint/_custom_rules.py`, and in
`src/protokit/schema/lint/rules/options/field_behavior.py`. Both used
`_extension_access.get_pool_bound_options_class`. The lint loader's own module
docstring stated the defect outright. Before U5, `_custom_rules.py` lines 18-24
read:

> The naive ``protokit.options.get_option_value`` helper does NOT surface
> custom-extension values when the extension is registered through a
> ``protoxy``-built ``DescriptorPool`` […]

So the diagnosis was written down, and the public helper stayed broken for four
months. The plan names this *bypass drift* (KTD1): a correct implementation
exists and the shared owner never adopts it. Two sibling call sites that decided
one way while the public entry point decided the other was the signal.
Documented as a design note, it read as settled. (auto memory [claude]: a
rationale for *not* doing something is itself a claim, and two siblings deciding
the other way is the tell.)

**The regression contract pinned the workaround, not the helper.**
`tests/schema/lint/test_protoxy_option_value_encoding_contract.py` is the
suite's "regression contract" for this exact encoding question. Before U5 it
hand-rolled the reparse inline in five tests (`parsed.MergeFromString(...)` at
its lines 136, 149, 159, 175, 192) and never called `get_option_value`. It
proved that protobuf's bytes survive a reparse. It could not prove that protokit
did the reparse, so it stayed green while the public helper returned `None`. A
contract test that reimplements the fix pins the library underneath, not the
code under test.

**A test docstring declared the case untestable.** Before U5, the module
docstring of `tests/core/test_options.py` (lines 3-12) said:

> Unit-level Tier 1 testing over a *custom* pool is blocked by protobuf's
> bootstrap-pool coupling […] — so ``TestExtensionPresence`` registers its
> extensions in the DEFAULT pool instead

That "limitation" was the defect. The coupling it describes is exactly what makes
the helper return `None`, and the lint package next door had already worked
around it. Moving the fixture to the default pool made tier 1 engage and the
tests pass, and it guaranteed that no test ever built the one pool shape the
helper failed on. A note of the form "cannot test X because of Y" is a claim, and
it can be checked: is Y a property of the library, or of our code's response to
it? Here a sibling had already answered that.

**The plan classified the failure as backend-specific, and three tracked files
repeated it.** The remediation plan (`docs/plans/2026-08-30-001-fix-0160-stability-release-plan.md`,
maintainer-local and not in this repo) grouped V9 under KTD6: "Three defects
(V1, V10, and the V9 swallow) rely on an exception only the upb backend raises;
under the pure-Python runtime each degrades silently to a wrong value". The measurements above
show otherwise. Both backends raise `KeyError`, and both return `None`. V9 is a
backend-neutral defect, and the pure-Python CI cell was never going to be its
guard. The claim had been copied into three tracked places, and U5 corrected all
three:

- the `test-pure-python` job comment in `.github/workflows/ci.yml` (now
  `:179`, anchor `Two audit defects (V1, V10)`);
- the module docstring of `tests/meta/test_pure_python_cell_presence_ratchet.py`
  (`:3`);
- `docs/solutions/best-practices/pure-python-backend-known-failure-inventory-ci-harvest.md`
  (`:46-47`).

The same plan also named the wrong source. It said to hoist "the reparse" out of
`src/protokit/schema/lint/_extension_access.py` and described that file as already fixing the
problem correctly. That file held only the class builder. The reparse itself
(`options_cls()` then `MergeFromString(...SerializeToString())`) lived at the
two lint sites, and the plan's Files list omitted both. The site set was taken
from the code, not from the plan's wording, the same correction
[trust-boundary-enforcement-points-derived-from-code-not-the-findings-wording](../security-issues/trust-boundary-enforcement-points-derived-from-code-not-the-findings-wording.md)
records for #77.

**Keeping the swallow and adding the reparse inside it would not have been a
fix.** One `KeyError` handler around a reparsed read still cannot tell the case
it exists for (an extension of another options type, such as a method option
asked of a field, which is truly absent) from any future identity refusal the
reparse fails to cover. Both would still read as `None`, and the next
regression would be as silent as this one.

## Solution

A new layer-0 module, `src/protokit/_extensions.py`, owns the re-read. It
imports nothing from `protokit`, so `protokit.options` (core) and
`protokit.schema.lint` can both depend on it. It exports two functions.

**Before U5 (options.py on main)**, tier 1, lines 133-153:

```python
        try:
            if ext_desc.label == descriptor.FieldDescriptor.LABEL_REPEATED:
                ext_value = options.Extensions[ext_desc]
                if len(ext_value) == 0:
                    continue
            else:
                if not options.HasExtension(ext_desc):
                    continue
                ext_value = options.Extensions[ext_desc]
        except (KeyError, ValueError):
            continue
```

**After**, `src/protokit/options.py:159-180` (anchor `if not extends(options,
ext_desc)`):

```python
        if not extends(options, ext_desc):
            continue
        readable = rebind_options(options, ext_desc)
        ext_value: object
        if is_repeated(ext_desc):
            values = readable.Extensions[ext_desc]
            if len(values) == 0:
                continue
            ext_value = values
        else:
            if not readable.HasExtension(ext_desc):
                continue
            ext_value = readable.Extensions[ext_desc]
```

The presence guard is unchanged: `HasExtension` for singular extensions,
emptiness for repeated ones. The `except` is gone.

**The re-read**, `src/protokit/_extensions.py:65-108` (anchor `def
rebind_options`):

```python
    target = ext_desc.containing_type
    if options.DESCRIPTOR is target:
        return options
    if not extends(options, ext_desc):
        raise KeyError(
            f"extension {ext_desc.full_name!r} extends {target.full_name!r}, "
            f"not {options.DESCRIPTOR.full_name!r}"
        )
    rebound = _options_class(target)()
    try:
        rebound.MergeFromString(options.SerializeToString())
    except UnicodeDecodeError as exc:
        # Pure-python validates proto3 string UTF-8 while parsing and raises
        # this where upb raises DecodeError; callers get one type on both.
        raise message.DecodeError(f"{ext_desc.full_name}: {exc}") from exc
    return rebound
```

**The absent-case predicate**, `src/protokit/_extensions.py:47-62` (anchor `def
extends`), compares `options.DESCRIPTOR.full_name` with
`ext_desc.containing_type.full_name`. It compares by name because the two sides
usually come from different pools.

`_options_class` (`src/protokit/_extensions.py:111-123`) calls
`message_factory.GetMessageClass` and falls back to
`MessageFactory(pool).GetPrototype`. `GetMessageClass` is absent from protobuf
4.21, the declared floor, and present by 4.25, the floor CI runs.

Both lint sites now call the seam and nothing else:
`src/protokit/schema/lint/_custom_rules.py:244` and
`src/protokit/schema/lint/rules/options/field_behavior.py:302`, each
`parsed = rebind_options(<descriptor>.GetOptions(), ext_desc)`.
`_extension_access.get_pool_bound_options_class` was deleted, not re-exported
as the plan's seam table had it. A re-export would have left a second public
way to get the class.

**The sibling fix**, `src/protokit/options.py:77-84` (anchor `Under upb a
MethodDescriptor reaches its file only through`): after `file` and `pool`,
`_owning_pool` tries `containing_service.file.pool` and then
`containing_type.file.pool`, and only then falls back to `desc.type.file.pool`
for enum values.

## Why This Works

**It binds on the extension, not on a pool.** The class that can read an
extension is the class of the message that extension extends, and
`ext_desc.containing_type` is that message's descriptor *in the extension's own
pool*. Deriving the class from there means there is only one source of truth.
The old lint helper took `(pool, options_full_name)` and looked the options type
up in the pool. That is a second input which can disagree with the extension
whenever a caller finds the extension in one pool and holds a descriptor from
another, which `get_option_value`'s `pool=` argument explicitly allows.
`test_explicit_pool_holding_the_extension_resolves`
(`tests/core/test_options.py:416`) reads a descriptor from one isolated pool
through an extension from a second one.

Binding on the extension also removes a second silent skip. The old helper
returned `None` when the pool lacked `descriptor.proto`, and both lint sites
"skipped silently" on that. An extension cannot be built into a pool without the
message it extends, so `containing_type` always exists and that branch no longer
has a case to handle.

**The fast path makes the common case free.** For a default-pool extension
(every generated `_pb2`), `containing_type` *is*
`descriptor_pb2.FieldOptions.DESCRIPTOR`, so `rebind_options` returns the input
without reserializing. The same holds for options the seam has already rebound.

**An explicit predicate replaces a catch that meant two things.** The
`KeyError` from `HasExtension` meant either "this extension extends another
options type" (a legitimate absence) or "you are reading with the wrong class"
(the defect). No handler can separate them after the fact. `extends` answers the
first question before any read happens, so the helper returns `None` only for
that case, and the second case no longer arises because the read goes through
the right class. If a future protobuf changes the refusal, the error propagates
instead of becoming `None`.

**Mismatch still raises inside the seam, on purpose.** `rebind_options` raises
`KeyError` rather than reparsing field bytes as method options, because the
field numbers would decode as unrelated data. The public helper tests `extends`
first and never reaches that branch. The lint closure does reach it: a synthetic
rule configured for the wrong element kind (a `FieldOptions` extension on
`METHOD`) surfaced as a `rule_exception` runtime warning before U5 and still
does. That behaviour was pinned *before* the move by
`TestOptionOfAnotherElementKind`
(`tests/schema/lint/test_custom_rules_loader.py:447`), so the move could be shown
not to turn it into a finding or a silent pass. Only the warning's wording changed:
each backend used to word protobuf's own refusal differently, and the seam's
message is the same on both.

**The guard is by construction, and it says what it cannot catch.** "Builds a
pool-bound options class" cannot be detected statically:
`protokit._pools.get_message_class` makes the same
`message_factory.GetMessageClass` call for ordinary message classes
(`src/protokit/_pools.py:251`), so a name-match ratchet would fire on day one.
Instead the builder is private, and the only exported entry points are
`rebind_options` and `extends`. `TestConstructionGuard`
(`tests/core/test_extensions.py:230`) pins both modules' exported surfaces, and
counts a builder re-exported from protobuf or wrapped in a `typing` alias as
exported: the first version checked only locally defined functions, and a
cross-model refuter bypassed it both ways. Its docstring says a from-scratch
hand-roll is outside what it can rule out.

## Prevention

**1. Test option readers on the pool shape that fails, with positive
assertions.** Build a self-contained `FileDescriptorSet`, with
`descriptor.proto` inside it as `protoc --include_imports` emits it, into a fresh
pool through `build_pool`, and assert a value:

```python
assert get_option_value(_ISO_FIELDS["annotated"], f"{_ISO_PKG}.limit") == 42
assert get_option_value(_ISO_FIELDS["zeroed"], f"{_ISO_PKG}.limit") == 0
```

`TestIsolatedPool` (`tests/core/test_options.py:342`) has eleven such tests. Nine
were red before the fix. The two that were green are
`test_absent_extensions_return_none` and
`test_option_of_another_options_type_is_absent`. **An `is None` assertion alone
passes against this defect by construction**, so every absence test needs a
positive twin on the same fixture. `tests/core/test_extensions.py` repeats the
positive check for all eight options types.

**2. Pin the premise, so its removal is visible.**
`test_bootstrap_options_are_refused_by_identity`
(`tests/core/test_extensions.py:146`), parametrized over the eight options
types, asserts `pytest.raises(KeyError)` on `GetOptions().HasExtension(ext)`. If
a protobuf release stops refusing, this is the test that says the seam can go.

**3. A contract test must call the public entry point.** Clause 5,
`TestPublicHelperContract`
(`tests/schema/lint/test_protoxy_option_value_encoding_contract.py:213`), now
calls `get_option_value` on the same protoxy pool the five reparse tests use,
and checks both the values and `None` on the unannotated method. When a contract
test contains the fix's own mechanism (`MergeFromString`, `GetMessageClass`),
ask which line of *our* code it would fail on. For the pre-U5 file, the answer
was none.

**4. Never catch `KeyError` around an extension read.** The candidates are
listed with:

```console
$ grep -rn "HasExtension(\|\.Extensions\[" src/protokit | grep -v '``'
```

At the U5 tree every hit reads through `rebind_options` or through
`_fieldview`'s declared-extension accessors (`src/protokit/_fieldview.py:71`,
`:83`), and none sits under a `KeyError` handler. A legitimate absent case gets
a predicate, like `extends` here. The exception protobuf raises for "wrong
reader" cannot be told apart from "not there".

**5. Treat "cannot test X because of Y" as a claim to check against siblings.**

```console
$ grep -rniE "is blocked by|cannot be (unit-)?tested|can't (be )?test|not testable|untestable" tests src
```

For each hit, ask whether another module in the repo already handles Y. Also
ask whether moving the fixture to avoid Y moves it away from the configuration
users run.

**6. Measure a backend claim on both backends before it enters tracked prose.**
Run the reproduction twice, once with
`PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python`, and record both outputs next to
the claim. When a backend claim is refuted, grep for its wording
(`grep -rnE "only (the )?upb (backend )?raises"`) to find every copy. Three had
to be corrected here, and one of them was in `docs/solutions/`.

**7. Exercise every accepted descriptor kind, under both backends.** The
`_owning_pool` sibling was found only because clause 5 called the helper on a
`MethodDescriptor`. `test_accepts_service_method_and_oneof_descriptors`
(`tests/core/test_options.py:580`) was red on upb and green on pure-Python before
the fix. The attribute layout differs by backend, so a helper that accepts "any
descriptor" needs one case per kind, run in both CI cells.

**Verification record for the U5 change**, as reported by its run (not re-run
for this writeup): the full suite was green on upb (4456 passed, 8 skipped, 37
xfailed) and pure-Python (4450 passed, 14 skipped, 37 xfailed). Seven mutation
proofs via `scripts/mutation_check.py` were all non-vacuous: skip the re-read in
`options.py`, drop the reparse bytes, drop the `extends` predicate, drop the
method hop, drop the fast path, and bypass the seam at each lint site.
`protokit._extensions` joined `LANDED_SEAMS`, and both it and `options.py`
joined the ruff and `mypy --strict` ratchets.

**Open, out of U5's scope:** `protokit._pools.get_message_class` calls
`message_factory.GetMessageClass` with no fallback (`src/protokit/_pools.py:251`),
and that call does not exist in protobuf 4.21.0, the declared floor of
`protobuf>=4.21.0,<6`. CI's floor cell pins 4.25.x, so nothing exercises the
gap.

## Related

- [sibling-blindness-fix-survives-review-structural-siblings-stay-broken](../best-practices/sibling-blindness-fix-survives-review-structural-siblings-stay-broken.md):
  the recurrence log for this pattern. Here the correct sibling was the older
  code, and the public owner was the one left broken.
- [trust-boundary-enforcement-points-derived-from-code-not-the-findings-wording](../security-issues/trust-boundary-enforcement-points-derived-from-code-not-the-findings-wording.md):
  deriving the site set from the code, not from the plan's or finding's wording
  (#77).
- [ptars-over-protarrow-proto-to-arrow-isolated-descriptor-pools](../tooling-decisions/ptars-over-protarrow-proto-to-arrow-isolated-descriptor-pools.md):
  the same default-pool identity assumption, met in a third-party library.
- [id-keyed-descriptor-cache-must-pin-the-object-and-bound-by-pool-under-upb](../best-practices/id-keyed-descriptor-cache-must-pin-the-object-and-bound-by-pool-under-upb.md):
  another upb-specific descriptor fact where what matters is the pool.
- [docs-code-drift-defense-convention-2026-06-13](../best-practices/docs-code-drift-defense-convention-2026-06-13.md):
  Rule 3, which governs the plan citation above.
