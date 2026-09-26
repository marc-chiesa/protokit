---
title: "A reflection guard over every public frozen record is only as good as its annotation classifier and its probes"
date: 2026-09-25
category: docs/solutions/best-practices
module: tests/meta/test_frozen_records.py
problem_type: best_practice
component: tooling
severity: high
root_cause: incomplete_implementation
applies_when:
  - "Writing a reflection/meta test that asserts a structural property over every dataclass, record, or type in a package (e.g. 'every public frozen dataclass owns its collection fields') by walking type annotations rather than a hand-maintained list"
  - "The annotation classifier must see through Optional/Union/Annotated wrappers, module-aliased imports, and string-quoted annotations (both a whole quoted annotation and a quoted element type inside a container) under `from __future__ import annotations`"
  - "Records are nested inside other classes, or fields are themselves fixed-length inner tuples/pairs (tuple[tuple[str, X], ...], Sequence[tuple[str, Plugin]]) rather than a flat collection"
  - "A field's declared type is a union that includes a non-collection arm (e.g. `LintSeverity | dict`), so a naive shape check on only one arm lets a value shaped like the other arm through unguarded"
  - "Reviewing or falsifying a freshly landed completeness guard: probing with values the guard's own coercion helpers (tuple(), dict(), frozenset()) will silently accept in the wrong shape — str, bytes, a plain dict, or a list of (key, value) pairs — is what surfaces the remaining gaps"
symptoms:
  - "The guard's annotation classifier missed Optional/Union/Annotated/module-alias arms, quoted whole-annotation and quoted element-annotation forms under `from __future__ import annotations`, records nested in classes, and fixed-length inner-pair fields (tuple[tuple[str, X], ...], Sequence[tuple[str, Plugin]]) — each found by review or cross-model falsification after the guard first landed"
  - "dict(['ab']) == {'a': 'b'} — a dict-typed field accepted a two-character string as if it were a single key-value pair, silently misconstructing caller input instead of raising"
  - "LintRuleSpec.severity: LintSeverity | dict — a list value passed neither shape check in the union and was stored as-is, unguarded and unnormalized"
  - "MatchPolicy.approx_overlays and CompatibilityPolicy.custom_rules (inner pair-typed fields) were absent from both the original six-record plan and the first guard, so they stayed alias-prone after the seam otherwise shipped"
related_components:
  - development_workflow
  - testing_framework
tags:
  - reflection-guard
  - frozen-dataclass
  - structural-siblings
  - annotation-classifier
  - sibling-blindness
  - records-seam
  - cross-model-falsification
  - guard-completeness
---
# A reflection guard over "every public frozen record" is only as good as its annotation classifier and its probes

## Context

`@dataclass(frozen=True)` blocks attribute rebinding and nothing else. A record
annotated `tuple[...]` keeps whatever it is handed. When a caller passes a list
and later appends to it, the "frozen" record changes too, and `hash()` of it
raises. Where a record did convert, a bare `tuple(x)` split a `str` into
characters: `HistoryReport(entries="abc")` became three one-character entries
(`src/protokit/_records.py:3-12`). Of 25 public records with a collection field,
nine converted some of their fields and sixteen converted none
(`src/protokit/_records.py:11-12`).

This unit (U6) fixed that in two parts:

1. **One owner of the conversion.** `src/protokit/_records.py` is a layer-0
   module that imports nothing from `protokit` (`src/protokit/_records.py:34-35`).
   Every record's `__post_init__` goes through it.
2. **A reflection guard.** `tests/meta/test_frozen_records.py` discovers every
   public frozen dataclass, reads each field's kind from its annotation, builds
   the record from probe values, and asserts that the record owns what it
   stores (`tests/meta/test_frozen_records.py:1-63`).

Whether a record converts its fields can be decided by running it, so the guard
is a reflection test, not a call-site search (`src/protokit/_records.py:26-32`).
That choice is right, but a reflection guard has two weak points the name
"every public frozen record" hides. First, it sees only the fields its
annotation classifier recognises as collections. Second, it catches only the
failures its probes trigger. In this unit, review and a cross-model
(`gpt-6-astra`) falsification pass found gaps in both, one concrete escape at a
time. The plan's audit list and the first version of the guard also missed three
structural siblings of the original bug.

The frozen-record learning from 2026-05-02
([[frozen-dataclass-mutable-fields-need-post-init-snapshot-2026-05-02]])
recommended `dict(self.field)` and "snapshot the union's dict arm only when
`isinstance(value, dict)`". Both patterns turned out to be escape routes. See
Guidance section 2.

## Guidance

### 1. Classify by the annotation's arms and element types. Resolve aliases and quotes. Fail on anything the classifier cannot read.

Every widening of the classifier was forced by a record that had a collection
field the guard classified as "no collection", so the field was never probed.
Each widening has a self-test record in the same file that shows the escape,
listed in `tests/meta/test_frozen_records.py:771-796`.

| Escape | Why the naive classifier missed it | Fix (current tree) | Self-test |
|---|---|---|---|
| `Optional[X]`, `Union[A, X]`, `Annotated[X, ...]`, `X \| None` | The head is `Optional` / `Union` / `Annotated`, which is not a container | `_union_arms` walks `\|`, `Optional`, `Union`, and `Annotated`'s first argument (`tests/meta/test_frozen_records.py:169-192`) | `_OptionalTupleAliases`, `_UnionTupleAliases`, `_AnnotatedTupleAliases` (`:710-722`) |
| A module-level alias (`Paths = tuple[str, ...]`, a `Union` alias, a `NewType`, PEP 695 `type`) | A bare name looks like a class | `_resolve_alias` + `_alias_text` read the module's globals (`:136-156`, `:195-208`); self-referential aliases terminate through a `seen` set | `_AliasAliases` (`:725-730`), `test_classify_resolves_a_module_alias_to_its_arms` (`:821-839`) |
| A quoted annotation under `from __future__ import annotations` | `f.type` is already a string. A quoted annotation inside it arrives as a string inside the string, which parses to an `ast.Constant` | The `ast.Constant` branch reparses the inner string (`:182-186`) | `_QuotedAnnotation` (`:738-740`) |
| A quoted **element** annotation: `tuple["tuple[str, int]", ...]` | The outer head was read, but the element that decides "pairs, check one level down" was a string | `_element_tuple` unquotes and resolves elements in a loop (`:228-236`) | `_SharesQuotedInnerPairs` (`:753-760`) |
| A frozen record nested in a class | Discovery looked only at module globals | `_classes_defined_in` descends into classes defined in the module (`:335-352`) | `test_discovery_descends_into_classes` (`:857-872`) |
| Fixed-length inner pairs: `tuple[tuple[str, int], ...]`, `Sequence[tuple[str, Plugin]]`, `tuple[ApproxOverlay, ...]` | Only a variadic inner `tuple[X, ...]` counted as nested | `_Kind.inner_len` records element arity (`:111`, `:211-242`). The nested probe builds an inner list of that length (`:561-566`) | `_SharesInnerPairs` (`:743-750`) |

Treat an annotation the classifier cannot interpret as a failure that names the
field, never as "no collection":

- An alias or quoted annotation that does not parse raises
  `ValueError("cannot classify alias Weird: ...")`
  (`tests/meta/test_frozen_records.py:159-166`, test at `:842-844`).
- Abstract heads (`Iterable`, `Collection`, `AbstractSet`, ...) and mutable heads
  (`list`, `MutableSequence`, `deque`, ...) are reported as defects on their
  own. An abstract head names no container the guard could check, and it
  promises readers neither re-iteration nor hashability
  (`:87-96`, `:516-521`).
- A new public record with a collection field and no build recipe fails by
  name. A recipe for a record that no longer qualifies also fails
  (`:617-624`).
- A discovery rule that silently shrank would pass every other test, so the
  records the audit named are pinned to the discovered set (`:635-645`).

The rule is that silence from the classifier must mean "this field provably
holds no collection". It must never mean "this field is written in a form I
didn't anticipate".

### 2. Structural siblings of "a record aliases or splits caller input" do not look like the original bug

The original bug was a tuple field that stored a list. Three siblings had the
same failure (the record keeps caller-owned or caller-split data) in a
different form. The plan's record list and the first guard (commit 1 of this
unit) missed all three. Each one was found by feeding the field exactly what
`tuple()` or `dict()` silently accepts.

**a. Mapping fields converted with a bare `dict()`.** `dict()` accepts any
iterable of pairs, and a two-character string is a pair:
`dict(["ab"]) == {"a": "b"}`. `LintFinding.params` and
`LintProfile.rule_severity_overrides` snapshotted with `dict(...)`, so they
copied correctly but also built a mapping out of a list of strings.

```python
# At this unit's base: LintFinding.__post_init__
object.__setattr__(self, "params", dict(self.params))

# Now (src/protokit/schema/lint/model.py:371)
object.__setattr__(self, "params", as_dict(self.params, "LintFinding.params"))
```

`as_dict` refuses anything without `keys()` (`src/protokit/_records.py:204-208`).
The same change is at `src/protokit/schema/lint/model.py:803` for
`rule_severity_overrides`.

**b. A union's dict arm.** `LintRuleSpec.severity: LintSeverity | dict[str,
LintSeverity]` (`src/protokit/schema/lint/model.py:972`). The earlier code
copied only when `isinstance(severity, dict)`. A list is neither a
`LintSeverity` nor a `dict`, so it passed the shape-parity check (both
"not dict") and was stored and shared as-is:

```python
# At this unit's base
severity_is_dict = isinstance(severity, dict)
template_is_dict = isinstance(template, dict)
if severity_is_dict != template_is_dict:
    raise TypeError(...)
if isinstance(severity, dict):
    object.__setattr__(self, "severity", dict(severity))

# Now (src/protokit/schema/lint/model.py:996-1002)
# Anything else is the multi-kind arm: a mapping, never a list stored as-is.
severity = self.severity
if not isinstance(severity, LintSeverity):
    severity = as_dict(severity, "LintRuleSpec.severity")
template = self.message_template
if not isinstance(template, str):
    template = as_dict(template, "LintRuleSpec.message_template")
```

In a union field, test for the scalar arm and send everything else through the
collection arm's converter. Testing for the collection arm lets a third type
through untouched. The classifier handles this by reading the union's dict arm
(`tests/meta/test_frozen_records.py:803`). The recipe supplies the
paired-shape companion field so the dict arm can be built at all
(`:360-373`, `:435-436`).

**c. Inner pairs of pair-typed fields.** `MatchPolicy.approx_overlays`
(`tuple[ApproxOverlay, ...]`, with `ApproxOverlay = tuple[SelectorSpec, Approx]`,
`src/protokit/message/matchers.py:115`, `:162`) and
`CompatibilityPolicy.custom_rules` / `message_rules`
(`src/protokit/schema/profiles.py:140-141`) copied only the outer sequence. A
caller's inner `[selector, Approx]` list stayed shared, including through
`dataclasses.replace`.

```python
# At this unit's base: MatchPolicy.__post_init__
# approx_overlays holds (selector, Approx) PAIRS, not bare selectors,
# so a plain snapshot is right here — a tuple of 2-tuples.
object.__setattr__(self, "approx_overlays", tuple(self.approx_overlays))

# Now (src/protokit/message/matchers.py:184)
own_tuples_of_tuples(self, "approx_overlays")
```

The old comment claimed the result was "a tuple of 2-tuples", but only the
outer tuple was built. `own_tuples_of_tuples` converts each element as well,
and a `str` element is refused under the name `Record.field[]`
(`src/protokit/_records.py:116-133`). `CompatibilityPolicy` uses it at
`src/protokit/schema/profiles.py:152`, and `CompiledSelection.paths` at
`src/protokit/storage/_fields.py:83`.

**What finds these siblings:** probe every collection field with the inputs
that `tuple()` / `dict()` accept without complaint, and assert that the record
either refuses the input or stores it whole. The record must never store the
pieces.

- Sequence fields get a `str`, `bytes`, and a `dict`
  (`tests/meta/test_frozen_records.py:577-583`, applied at `:554-560`). For
  nested fields the same probes run one level down (`:567-573`).
- Nested fields also get a caller-held inner list of the element's arity, which
  the test mutates after construction (`:561-566`).
- Mapping fields get a caller dict that the test then mutates (`:588-592`), and
  a list of strings and a list of pairs, which must both be refused (`:595-602`).

### 3. The fix pattern: one layer-0 owner with a small set of helpers

`src/protokit/_records.py` has one helper per storage shape:

| Helper | Use | Refuses |
|---|---|---|
| `as_tuple` (`:78-97`) | `tuple[...]` / `Sequence[...]` fields | `str`, `bytes`, `bytearray`, any `Mapping`, non-iterables (`:50-75`) |
| `own_tuples` (`:100-113`) | several tuple fields in one `__post_init__`; errors name `Record.field` | as `as_tuple` |
| `own_tuples_of_tuples` (`:116-133`) | fields of pairs or paths | as `as_tuple`, at both levels |
| `as_frozenset` (`:136-151`) | `frozenset[...]` fields | as `as_tuple` |
| `as_mapping` (`:154-183`) | `Mapping[...]` fields; returns a read-only `MappingProxyType` over a top-level copy | anything without `keys()` |
| `as_dict` (`:186-208`) | fields whose public type is `dict` | anything without `keys()` |
| `one_of` (`:211-233`) | closed-vocabulary strings (`Diagnostic.level`, `src/protokit/message/model.py:124`) | a value outside the set |

Records call the helpers declaratively:
`own_tuples(self, "differences", "diagnostics", "truncated_paths")` in
`DiffResult` (`src/protokit/message/model.py:647`).

Fast paths keep records on hot paths cheap:

- `as_tuple` returns a plain `tuple` unchanged after one `type(x) is tuple`
  check (`src/protokit/_records.py:95-96`). `as_frozenset` does the same for
  `frozenset` (`:149-150`).
- `FieldPath` skips the call entirely for a tuple
  (`src/protokit/message/model.py:268`), because the differ builds one path per
  visited field.
- `as_mapping` passes a `MappingProxyType` through uncopied
  (`src/protokit/_records.py:177-178`). The lint-context mixin skips the call
  for one (`src/protokit/schema/lint/model.py:1083`), because the engine hands
  a proxy to every context it builds, once per schema element per rule.

Settled scope choices (context, not open questions):

- **Any iterable except `str` / `bytes` / `bytearray` / `Mapping` is accepted**,
  including generators, sets and `range`. Every one of those already worked on
  the records that converted, and nothing that worked is broken
  (`src/protokit/_records.py:19-24`).
- **`MappingProxyType` passes through uncopied.** The cost is that a caller who
  wraps their own dict in a proxy keeps a handle on it
  (`src/protokit/_records.py:157-161`).
- **Nested mappings are not deep-frozen.** `as_mapping` copies the top level
  only (`src/protokit/_records.py:161`). The guard states this as out of scope
  (`tests/meta/test_frozen_records.py:53-57`).

## Why This Matters

A reflection guard reports on everything it enumerates. A field it failed to
classify, or a failure its probes never trigger, raises no error, so the guard
passes and its "every public frozen record" claim is false. In this unit, each
escape was a real record: a list stored and shared on a union's dict arm, or
`dict(["ab"])` becoming `{"a": "b"}`. The first guard would have passed on
each one, and each looked covered because the guard's docstring said "every".

The structural siblings matter for the same reason
[[sibling-blindness-fix-survives-review-structural-siblings-stay-broken]]
describes. The fix was scoped to the bug's first form (a tuple field storing a
list). The same failure (the record keeps caller-owned or caller-split data)
also occurred in mapping fields, union arms, and inner elements. It stayed
open until probes aimed at the converters, rather than at the bug report,
exposed it. Checking what the converter silently accepts (`tuple(str)`,
`dict(list_of_pairs)`) found all three. Enumerating the record types did not.

Centralising the conversion in one layer-0 module turns the next escape into a
one-helper fix. It also means the guard only has to show that each field goes
through a helper that refuses the right inputs.

## When to Apply

- You write or extend a guard that claims coverage of "every X" by reflection
  (every public record, every rule, every CLI subcommand). Check what its
  classifier ignores and what its discovery cannot reach. Add a self-test that
  shows each form the guard must catch.
- A field's annotation is a union, an alias, a quoted string, or a
  parameterised element type. Classify it by its arms and elements. Do not stop
  at the outer head.
- Code converts caller input with a bare `tuple()`, `frozenset()` or `dict()`.
  Ask what those accept silently: a `str`, `bytes`, a `Mapping` (keys only), or
  a list of two-character strings for `dict()`.
- A union field has a collection arm. Branch on the scalar arm and send
  everything else to the collection converter.
- A field holds pairs or paths. Copying the outer container leaves the inner
  ones shared.
- A cross-model or adversarial pass returns a counterexample against a guard.
  Fix the guard, then add a self-test record that shows the escape, so the
  widening cannot silently regress.

## Examples

**Self-test records: one escape each, and the guard must name it**
(`tests/meta/test_frozen_records.py:763-796`):

```python
@dataclass(frozen=True)
class _DictFromPairs:
    table: dict[str, int] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "table", dict(self.table))

@pytest.mark.parametrize(("cls", "expected"), [
    ...
    (_SharesInnerPairs, "keeps the caller's inner list"),
    (_SharesQuotedInnerPairs, "keeps the caller's inner list"),
    (_DictFromPairs, "builds a mapping from a str list"),
])
def test_checks_catch_each_defect(cls, expected):
    found = violations(cls, Recipe(_no_fields))
    assert any(expected in v for v in found), found
```

**The probes: what the converter accepts silently, asserted refused or stored
whole** (`tests/meta/test_frozen_records.py:554-560`, `:579-583`):

```python
_TAKEN_APART = (
    ("ab", ("a", "b"), "splits a str into its characters"),
    (b"ab", (97, 98), "splits bytes into integers"),
    ({"a": 1, "b": 2}, ("a", "b"), "keeps a mapping's keys alone"),
)
for probe, pieces, defect in _TAKEN_APART:
    try:
        from_probe = getattr(_build(cls, recipe, field_name, probe), field_name)
    except TypeError:
        continue            # refused: fine
    if from_probe == stored_type(pieces):
        problems.append(defect)   # stored the pieces: a defect
```

**Behaviour in the current tree** (run against `src/`):

```python
>>> dict(["ab"])
{'a': 'b'}
>>> LintFinding(..., params=["ab"])
TypeError: LintFinding.params must be a mapping, not a list
>>> LintRuleSpec(rule_id="r", severity=[("k", LintSeverity.ERROR)], ...)
TypeError: LintRuleSpec.severity must be a mapping, not a list
>>> inner = ["a.b", None]; p = MatchPolicy(approx_overlays=[inner]); inner.append(1)
>>> p.approx_overlays
(('a.b', None),)
>>> MatchPolicy(approx_overlays="ab")
TypeError: MatchPolicy.approx_overlays must be a collection of items, not a str: iterating it would split it into characters
>>> DiffResult(differences="ab")
TypeError: DiffResult.differences must be a collection of items, not a str: iterating it would split it into characters
```

**Order in which the guard was widened, and what forced each step** (from this
unit's commits):

1. First version: list, set and dict sources for tuple, frozenset and mapping
   heads, plus a `str` probe. The recipe table was forced by discovery.
2. Review follow-up: `bytes` and `dict` probes (one level down for nested
   tuples). `Optional` / `Union` / `Annotated` / module-alias classification.
   Abstract and mutable heads flagged as defects.
3. Cross-model falsification pass (five counterexamples, each reproduced on
   both protobuf backends before fixing): quoted annotations, classes nested in
   classes, fixed-length inner pairs, and mapping fields built from lists of
   pairs. `as_dict` and `own_tuples_of_tuples` were added to `_records`.
4. A second falsification pass: `LintRuleSpec`'s dict arm accepted a list, and
   the classifier missed a quoted element annotation
   (`tuple["tuple[str, int]", ...]`).

Each step came with the self-test record that shows its escape. That is why
the guard's coverage claim can now be checked instead of assumed.
