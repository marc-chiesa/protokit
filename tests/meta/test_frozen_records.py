"""Every public frozen record owns the collections it stores (U6, KTD2).

``@dataclass(frozen=True)`` blocks attribute rebinding and nothing else. A
record annotated ``tuple[...]`` that is handed a list keeps the caller's list,
so the "frozen" record changes when the caller's list does, and cannot be
hashed (V6, V11). The fix is a ``__post_init__`` through ``protokit._records``;
this test is the guard that makes the fix hold for records nobody has written
yet.

**What it checks, per collection field** — the field's kind is read off its
annotation, which is decidable:

* ``tuple[...]`` / ``Sequence[...]``: built from a list the test then appends
  to, the record stores a ``tuple`` that did not change. Built from a ``str``,
  the record either refuses it or stores it whole — never its characters.
  A variadic ``tuple[tuple[...], ...]`` is checked one level down as well.
* ``frozenset[...]``: the same, with a set.
* ``Mapping[...]``: built from a dict the test then adds to, the record stores
  a read-only mapping that did not change.
* ``dict[...]``: built from a dict the test then adds to, the record's dict
  did not change. It stays a ``dict`` because that is its public type.

* ``Iterable[...]``, ``Collection[...]``, ``AbstractSet[...]`` and the other
  abstract heads: a defect in itself. The annotation does not say which
  container the record owns, so nothing here could decide what to probe for,
  and readers of the record cannot rely on it being re-iterable or hashable.
* ``list``, ``set``, ``dict``-like mutable heads (``MutableSequence``,
  ``MutableMapping``, ``deque``, ...): a defect in itself.

Each probed sequence field is also built from a ``str``, ``bytes`` and a
``dict``: the record refuses each or stores it whole, and never keeps the
characters, the integers or the keys alone.

Optional and union fields (``X | None``, ``Optional[X]``, ``Union[X, Y]``,
``Annotated[X, ...]``) are checked for their collection arms. A bare name that
the record's module binds to a type alias rather than a class
(``Paths = tuple[str, ...]``, a ``Union`` alias, a ``NewType``) is resolved and
its arms classified the same way; a name the module does not bind at runtime
(a ``TYPE_CHECKING`` import) is taken to be a class. An alias that cannot be
read fails by name instead of classifying as "no collection".

**What "public" means**, read from the code rather than from a list: a frozen
dataclass that a package exports in ``__all__``, or one whose class name and
every module component are free of a leading underscore.

**Why a recipe table.** A record's other required fields have to be filled
in, and some ``__post_init__`` hooks check them. ``_RECIPES`` holds those
values, and it must name exactly the public records that have a collection
field: a new record without an entry fails here by name, so it cannot sit
outside the guard unnoticed, and an entry for a record that no longer
qualifies fails too.

**What it does not check.** Closed-vocabulary fields (``Diagnostic.level``)
are not collections and are not decidable from an annotation that is a plain
``str``; their tests live beside each record. Nested mappings stay as mutable
as the caller made them (``protokit._records.as_mapping`` copies the top
level only).

KTD2 proof: the self-tests at the bottom run the same checks over records
defined here — one that aliases, one that splits a string, one that forgets a
field — and assert each is caught; a meta test has no ``src`` anchor for
``scripts/mutation_check.py``.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import pkgutil
import sys
import types
from collections.abc import Callable, Iterable, Iterator, Mapping, MutableMapping
from dataclasses import dataclass
from types import ModuleType
from typing import Annotated, Any, Literal, NewType, Optional, TypeVar, Union

import pytest

import protokit

# Annotation heads, by the kind of container the field must end up holding.
_TUPLE_HEADS = frozenset({"tuple", "Tuple", "Sequence"})
_FROZENSET_HEADS = frozenset({"frozenset", "FrozenSet"})
_MAPPING_HEADS = frozenset({"Mapping"})
_DICT_HEADS = frozenset({"dict", "Dict"})
# A mutable container annotation on a frozen record is a defect in itself.
_MUTABLE_HEADS = frozenset({
    "list", "List", "set", "Set", "MutableSequence", "MutableSet", "MutableMapping",
    "deque", "Deque", "defaultdict", "DefaultDict", "OrderedDict", "Counter",
})
# So is an abstract one: it names no container the record could be checked
# for owning, and promises its readers neither re-iteration nor hashing.
_ABSTRACT_HEADS = frozenset({
    "Iterable", "Iterator", "Collection", "Container", "Reversible", "AbstractSet",
})
# Heads whose arguments are the annotation's arms, not its elements.
_UNION_HEADS = frozenset({"Optional", "Union"})
_KNOWN_HEADS = (
    _TUPLE_HEADS | _FROZENSET_HEADS | _MAPPING_HEADS | _DICT_HEADS
    | _MUTABLE_HEADS | _ABSTRACT_HEADS | _UNION_HEADS | {"Annotated"}
)


@dataclass(frozen=True)
class _Kind:
    """The container a field must hold, and what its elements are."""

    head: str  # "tuple", "frozenset", "mapping", "dict", "mutable" or "abstract"
    nested_tuple: bool = False  # variadic tuple of variadic tuples


def _head_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Subscript):
        node = node.value
    if isinstance(node, ast.Attribute):  # typing.Sequence, collections.abc.Mapping
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _is_variadic_tuple(node: ast.expr) -> bool:
    if not (isinstance(node, ast.Subscript) and _head_name(node) in {"tuple", "Tuple"}):
        return False
    args = node.slice
    return (
        isinstance(args, ast.Tuple)
        and len(args.elts) == 2
        and isinstance(args.elts[1], ast.Constant)
        and args.elts[1].value is Ellipsis
    )


def _alias_text(value: object) -> str | None:
    """The annotation text a module-level binding stands for, or ``None``.

    ``None`` means the binding is a class (or a ``TypeVar``, or not a typing
    construct at all), whose name is its own annotation.
    """
    if isinstance(value, str):  # a quoted alias: ``Paths = "tuple[str, ...]"``
        return value
    if isinstance(value, (type, TypeVar)):
        return None
    supertype = getattr(value, "__supertype__", None)  # NewType
    if supertype is not None:
        return _alias_text(supertype) or getattr(supertype, "__name__", None)
    alias_value = getattr(value, "__value__", None)  # ``type Paths = ...`` (3.12+)
    if alias_value is not None:
        return _alias_text(alias_value) or getattr(alias_value, "__name__", None)
    if isinstance(value, (types.GenericAlias, types.UnionType)) or type(
        value,
    ).__module__ in {"typing", "typing_extensions"}:
        return repr(value)
    return None


def _parse(annotation: str, what: str) -> ast.expr:
    try:
        return ast.parse(annotation, mode="eval").body
    except SyntaxError:
        raise ValueError(
            f"cannot classify {what}: {annotation!r} is not an annotation this "
            "guard can read; annotate the field with the container it stores",
        ) from None


def _union_arms(
    node: ast.expr, namespace: Mapping[str, object], seen: frozenset[str],
) -> Iterator[ast.expr]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        yield from _union_arms(node.left, namespace, seen)
        yield from _union_arms(node.right, namespace, seen)
        return
    head = _head_name(node)
    if isinstance(node, ast.Subscript) and head in _UNION_HEADS | {"Annotated"}:
        args = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
        for arg in args[:1] if head == "Annotated" else args:
            yield from _union_arms(arg, namespace, seen)
        return
    if (
        isinstance(node, ast.Name)
        and node.id not in _KNOWN_HEADS
        and node.id not in seen
        and node.id in namespace
    ):
        text = _alias_text(namespace[node.id])
        if text is not None:
            alias = _parse(text, f"alias {node.id}")
            yield from _union_arms(alias, namespace, seen | {node.id})
            return
    yield node


def classify(annotation: str, namespace: Mapping[str, object] | None = None) -> list[_Kind]:
    """Return the collection kinds among ``annotation``'s union arms.

    ``namespace`` is the globals of the module the annotation was written in;
    a bare name it binds to a type alias is classified as the alias's value.
    """
    tree = _parse(annotation, "annotation")
    kinds: list[_Kind] = []
    for arm in _union_arms(tree, namespace or {}, frozenset()):
        head = _head_name(arm)
        if head in _TUPLE_HEADS:
            nested = False
            if _is_variadic_tuple(arm):
                assert isinstance(arm, ast.Subscript)
                assert isinstance(arm.slice, ast.Tuple)
                nested = _is_variadic_tuple(arm.slice.elts[0])
            kinds.append(_Kind("tuple", nested))
        elif head in _FROZENSET_HEADS:
            kinds.append(_Kind("frozenset"))
        elif head in _MAPPING_HEADS:
            kinds.append(_Kind("mapping"))
        elif head in _DICT_HEADS:
            kinds.append(_Kind("dict"))
        elif head in _MUTABLE_HEADS:
            kinds.append(_Kind("mutable"))
        elif head in _ABSTRACT_HEADS:
            kinds.append(_Kind("abstract"))
    return kinds


def collection_fields(cls: type) -> dict[str, list[_Kind]]:
    """Map each init field of ``cls`` holding a collection to its kinds."""
    found: dict[str, list[_Kind]] = {}
    module = sys.modules.get(cls.__module__)
    namespace = vars(module) if module is not None else {}
    for f in dataclasses.fields(cls):
        if not f.init:
            continue
        annotation = f.type if isinstance(f.type, str) else (
            _alias_text(f.type) or getattr(f.type, "__name__", repr(f.type))
        )
        kinds = classify(annotation, namespace)
        if kinds:
            found[f.name] = kinds
    return found


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _all_modules() -> list[ModuleType]:
    modules = [protokit]
    for info in pkgutil.walk_packages(protokit.__path__, "protokit."):
        modules.append(importlib.import_module(info.name))
    return modules


def _is_frozen_dataclass(obj: object) -> bool:
    return (
        isinstance(obj, type)
        and dataclasses.is_dataclass(obj)
        and obj.__dataclass_params__.frozen  # type: ignore[attr-defined]
    )


def _qualname(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def public_frozen_records(modules: list[ModuleType]) -> dict[str, type]:
    """Every public frozen dataclass defined in ``modules``."""
    exported: set[int] = set()
    for module in modules:
        for name in getattr(module, "__all__", ()):
            exported.add(id(getattr(module, name, None)))
    records: dict[str, type] = {}
    for module in modules:
        for obj in vars(module).values():
            if not _is_frozen_dataclass(obj) or obj.__module__ != module.__name__:
                continue
            named_public = not obj.__name__.startswith("_") and not any(
                part.startswith("_") for part in module.__name__.split(".")
            )
            if named_public or id(obj) in exported:
                records[_qualname(obj)] = obj
    return records


# ---------------------------------------------------------------------------
# Recipes: the non-collection fields each record needs to be built at all
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Recipe:
    """How to build one record around a probed collection field.

    ``required`` fills the record's other required fields. ``companions``
    names, per probed field, the fields a paired-shape invariant needs set
    alongside it (``LintRuleSpec`` takes a dict ``severity`` only with a dict
    ``message_template``).
    """

    required: Callable[[], dict[str, Any]]
    companions: Mapping[str, Mapping[str, Any]] = dataclasses.field(
        default_factory=dict,
    )


def _no_fields() -> dict[str, Any]:
    return {}


def _lint_context(**extra: Any) -> Callable[[], dict[str, Any]]:
    def build() -> dict[str, Any]:
        return {
            "file": None,
            "pool": None,
            "profile": "default",
            "_emit_fn": lambda *a, **k: None,
            "_rule_id": "r",
            "_effective_severity": lambda kind: None,
            **extra,
        }
    return build


def _descriptor_context(*element_fields: str) -> Callable[[], dict[str, Any]]:
    return _lint_context(
        source_info_descriptors=None, **dict.fromkeys(element_fields),
    )


def _field_path() -> dict[str, Any]:
    from protokit.message.model import ChangeType, FieldPath

    return {"path": FieldPath(segments=()), "change_type": ChangeType.MODIFIED}


def _lint_finding() -> dict[str, Any]:
    from protokit.schema.lint.model import FileLocation, LintSeverity

    return {
        "rule_id": "r",
        "severity": LintSeverity.ERROR,
        "location": FileLocation(file="a.proto"),
        "violation_kind": "",
    }


def _lint_rule_spec() -> dict[str, Any]:
    from protokit.schema.lint.model import LintSeverity

    return {"rule_id": "r", "severity": LintSeverity.ERROR, "profiles": ()}


def _compile_result() -> dict[str, Any]:
    from google.protobuf import descriptor_pool

    return {"pool": descriptor_pool.DescriptorPool()}


def _compatibility_report() -> dict[str, Any]:
    from protokit.schema.model import CompatibilityLevel

    return {"level": CompatibilityLevel.STRICT}


def _severity_dict_companion() -> Mapping[str, Mapping[str, Any]]:
    return {"severity": {"message_template": {}}, "message_template": {"severity": {}}}


_RANGE = {"range_spec": "a..b", "old_sha": "a", "new_sha": "b", "commits_walked": 0}

_RECIPES: dict[str, Recipe] = {
    "protokit.forensics._drift.DriftReport": Recipe(
        lambda: {"divergences": (), "observed_field_count": 0},
    ),
    "protokit.forensics._match.MatchReport": Recipe(
        lambda: {"ranked": (), "verdict": "no_clean_match", "ambiguous_top": False},
    ),
    "protokit.message.matchers.MatchPolicy": Recipe(_no_fields),
    "protokit.message.model.FieldPath": Recipe(lambda: {"segments": ()}),
    "protokit.message.model.Difference": Recipe(_field_path),
    "protokit.message.model.DiffResult": Recipe(lambda: {"differences": ()}),
    "protokit.schema.compile.LintCompileDiagnostic": Recipe(
        lambda: {"level": "error", "message": "m"},
    ),
    "protokit.schema.compile.CompileResult": Recipe(_compile_result),
    "protokit.schema.lint.model.CycleEdge": Recipe(
        lambda: {"imported_file": "a.proto", "target_package": "p", "cycle_path": ()},
    ),
    "protokit.schema.lint.model.EnumLintContext": Recipe(_descriptor_context("enum")),
    "protokit.schema.lint.model.EnumValueLintContext": Recipe(
        _descriptor_context("value", "enum"),
    ),
    "protokit.schema.lint.model.FieldLintContext": Recipe(
        _descriptor_context("field", "message"),
    ),
    "protokit.schema.lint.model.FileLintContext": Recipe(_lint_context()),
    "protokit.schema.lint.model.LintFinding": Recipe(_lint_finding),
    "protokit.schema.lint.model.LintProfile": Recipe(lambda: {"name": "p"}),
    "protokit.schema.lint.model.LintReport": Recipe(_no_fields),
    "protokit.schema.lint.model.LintRuleSpec": Recipe(
        _lint_rule_spec, _severity_dict_companion(),
    ),
    "protokit.schema.lint.model.MessageLintContext": Recipe(
        _descriptor_context("message"),
    ),
    "protokit.schema.lint.model.MethodLintContext": Recipe(
        _descriptor_context("method", "service"),
    ),
    "protokit.schema.model.BisectReport": Recipe(
        lambda: {**_RANGE, "breaking_commit": None},
    ),
    "protokit.schema.model.CompatibilityReport": Recipe(_compatibility_report),
    "protokit.schema.model.HistoryReport": Recipe(lambda: dict(_RANGE)),
    "protokit.schema.profiles.CompatibilityPolicy": Recipe(_no_fields),
    "protokit.storage._columnar.FidelityReport": Recipe(
        lambda: {"rows": 0, "measured": False, "unmodeled_records": 0, "unmodeled_bytes": 0},
    ),
    "protokit.storage._fields.CompiledSelection": Recipe(lambda: {"paths": ()}),
}


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------


def _build(cls: type, recipe: Recipe, field_name: str, value: object) -> Any:
    kwargs = recipe.required()
    kwargs.update(recipe.companions.get(field_name, {}))
    kwargs[field_name] = value
    return cls(**kwargs)


def violations(cls: type, recipe: Recipe) -> list[str]:
    """Every way ``cls`` fails to own a collection it stores."""
    found: list[str] = []
    name = cls.__qualname__
    for field_name, kinds in collection_fields(cls).items():
        where = f"{name}.{field_name}"
        for kind in kinds:
            found.extend(f"{where}: {v}" for v in _check(cls, recipe, field_name, kind))
    return found


def _check(cls: type, recipe: Recipe, field_name: str, kind: _Kind) -> list[str]:
    if kind.head == "mutable":
        return ["annotated as a mutable container; a frozen record stores tuple, "
                "frozenset or Mapping"]
    if kind.head == "abstract":
        return ["annotated as an abstract collection; a frozen record annotates "
                "the tuple, frozenset or Mapping it stores"]
    if kind.head == "tuple":
        return _check_sequence(cls, recipe, field_name, list, tuple, kind.nested_tuple)
    if kind.head == "frozenset":
        return _check_sequence(cls, recipe, field_name, set, frozenset, nested=False)
    return _check_mapping(cls, recipe, field_name, read_only=kind.head == "mapping")


def _check_sequence(
    cls: type,
    recipe: Recipe,
    field_name: str,
    source_type: type,
    stored_type: type,
    nested: bool,
) -> list[str]:
    problems: list[str] = []
    source: Any = source_type()
    stored = getattr(_build(cls, recipe, field_name, source), field_name)
    add = source.append if source_type is list else source.add
    add(object())
    if type(stored) is not stored_type:
        problems.append(
            f"built from a {source_type.__name__}, stores a {type(stored).__name__}, "
            f"not a {stored_type.__name__}",
        )
    elif stored:
        problems.append(f"shares the caller's {source_type.__name__}")
    for probe, pieces, defect in _TAKEN_APART:
        try:
            from_probe = getattr(_build(cls, recipe, field_name, probe), field_name)
        except TypeError:
            continue
        if from_probe == stored_type(pieces):
            problems.append(defect)
    if nested:
        inner: list[object] = []
        stored = getattr(_build(cls, recipe, field_name, [inner]), field_name)
        inner.append(object())
        if type(stored[0]) is not tuple or stored[0]:
            problems.append("keeps the caller's inner list")
        for probe, pieces, defect in _TAKEN_APART:
            try:
                from_probe = getattr(_build(cls, recipe, field_name, [probe]), field_name)
            except TypeError:
                continue
            if from_probe == (tuple(pieces),):
                problems.append(f"{defect}, one level down")
    return problems


# Iterable, but iterating one takes it apart: a record must refuse each of
# these or store it whole, never the pieces.
_TAKEN_APART: tuple[tuple[object, tuple[object, ...], str], ...] = (
    ("ab", ("a", "b"), "splits a str into its characters"),
    (b"ab", (97, 98), "splits bytes into integers"),
    ({"a": 1, "b": 2}, ("a", "b"), "keeps a mapping's keys alone"),
)


def _check_mapping(cls: type, recipe: Recipe, field_name: str, read_only: bool) -> list[str]:
    problems: list[str] = []
    source: dict[str, object] = {}
    stored = getattr(_build(cls, recipe, field_name, source), field_name)
    source["added"] = object()
    if "added" in stored:
        problems.append("shares the caller's dict")
    if read_only and isinstance(stored, MutableMapping):
        problems.append(f"stores a mutable {type(stored).__name__}")
    return problems


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

_MODULES = _all_modules()
_PUBLIC = public_frozen_records(_MODULES)
_WITH_COLLECTIONS = {
    name: cls for name, cls in _PUBLIC.items() if collection_fields(cls)
}


def test_every_public_record_with_a_collection_has_a_recipe() -> None:
    missing = sorted(set(_WITH_COLLECTIONS) - set(_RECIPES))
    stale = sorted(set(_RECIPES) - set(_WITH_COLLECTIONS))
    assert not missing, (
        "public frozen records with collection fields that this guard cannot "
        f"build — add a Recipe to _RECIPES: {missing}"
    )
    assert not stale, f"_RECIPES entries that are no longer public records: {stale}"


@pytest.mark.parametrize("name", sorted(_RECIPES))
def test_record_owns_its_collections(name: str) -> None:
    cls = _WITH_COLLECTIONS.get(name)
    if cls is None:
        pytest.fail(f"{name} is not a public frozen record with a collection field")
    assert violations(cls, _RECIPES[name]) == []


def test_discovery_sees_the_records_the_audit_named() -> None:
    """A discovery rule that silently shrank would pass every other test here."""
    audited = {
        "protokit.message.model.DiffResult",
        "protokit.schema.model.CompatibilityReport",
        "protokit.schema.model.HistoryReport",
        "protokit.schema.model.BisectReport",
    }
    assert audited <= set(_WITH_COLLECTIONS)
    assert "protokit.message.model.Diagnostic" in _PUBLIC
    assert "protokit.schema.model.Finding" in _PUBLIC


# ---------------------------------------------------------------------------
# Self-tests: the checks catch each defect they exist for
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Aliases:
    items: tuple[int, ...] = ()


@dataclass(frozen=True)
class _SplitsStrings:
    items: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))


@dataclass(frozen=True)
class _SharesMapping:
    table: Mapping[str, int] | None = None


@dataclass(frozen=True)
class _MutableAnnotation:
    names: list[str] = dataclasses.field(default_factory=list)


@dataclass(frozen=True)
class _FlatNested:
    paths: tuple[tuple[str, ...], ...] = ()

    def __post_init__(self) -> None:
        from protokit._records import as_tuple

        object.__setattr__(self, "paths", as_tuple(self.paths, "paths"))


@dataclass(frozen=True)
class _SplitsNestedStrings:
    paths: tuple[tuple[str, ...], ...] = ()

    def __post_init__(self) -> None:
        from protokit._records import as_tuple

        paths = as_tuple(self.paths, "paths")
        object.__setattr__(self, "paths", tuple(tuple(p) for p in paths))


@dataclass(frozen=True)
class _SplitsBytesAndMappings:
    """The pre-U6 ``MatchPolicy._as_tuple``: a ``str`` is kept whole, the rest split."""

    items: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        items = self.items
        object.__setattr__(
            self, "items", (items,) if isinstance(items, str) else tuple(items),
        )


@dataclass(frozen=True)
class _OptionalTupleAliases:
    items: Optional[tuple[int, ...]] = None  # noqa: UP045 -- the form under test


@dataclass(frozen=True)
class _UnionTupleAliases:
    items: Union[int, tuple[int, ...]] = ()  # noqa: UP007 -- the form under test


@dataclass(frozen=True)
class _AnnotatedTupleAliases:
    items: Annotated[tuple[int, ...], "meta"] = ()


_Items = tuple[int, ...]


@dataclass(frozen=True)
class _AliasAliases:
    items: _Items = ()


@dataclass(frozen=True)
class _AbstractAnnotation:
    items: Iterable[int] = ()


@pytest.mark.parametrize(
    ("cls", "expected"),
    [
        (_Aliases, "stores a list, not a tuple"),
        (_SplitsStrings, "splits a str into its characters"),
        (_SharesMapping, "shares the caller's dict"),
        (_MutableAnnotation, "annotated as a mutable container"),
        (_FlatNested, "keeps the caller's inner list"),
        (_SplitsNestedStrings, "splits a str into its characters, one level down"),
        (_SplitsNestedStrings, "splits bytes into integers, one level down"),
        (_SplitsBytesAndMappings, "splits bytes into integers"),
        (_SplitsBytesAndMappings, "keeps a mapping's keys alone"),
        (_OptionalTupleAliases, "stores a list, not a tuple"),
        (_UnionTupleAliases, "stores a list, not a tuple"),
        (_AnnotatedTupleAliases, "stores a list, not a tuple"),
        (_AliasAliases, "stores a list, not a tuple"),
        (_AbstractAnnotation, "annotated as an abstract collection"),
    ],
)
def test_checks_catch_each_defect(cls: type, expected: str) -> None:
    found = violations(cls, Recipe(_no_fields))
    assert any(expected in v for v in found), found


def test_classify_reads_union_optional_and_nested_annotations() -> None:
    assert classify("tuple[str, ...] | None") == [_Kind("tuple")]
    assert classify("tuple[tuple[str, ...], ...]") == [_Kind("tuple", nested_tuple=True)]
    assert classify("Sequence[tuple[str, 'Plugin']]") == [_Kind("tuple")]
    assert classify("LintSeverity | dict[str, LintSeverity]") == [_Kind("dict")]
    assert classify("Literal['contradictory_disable_config']") == []
    assert classify("Verdict") == []


def test_classify_reads_typing_unions_and_abstract_or_mutable_heads() -> None:
    assert classify("Optional[tuple[str, ...]]") == [_Kind("tuple")]
    assert classify("typing.Optional[Mapping[str, int]]") == [_Kind("mapping")]
    assert classify("Union[int, tuple[str, ...]]") == [_Kind("tuple")]
    assert classify("Union[frozenset[str], None] | int") == [_Kind("frozenset")]
    assert classify("Annotated[tuple[str, ...], 'meta']") == [_Kind("tuple")]
    assert classify("Iterable[str]") == [_Kind("abstract")]
    assert classify("Collection[str] | None") == [_Kind("abstract")]
    assert classify("collections.abc.AbstractSet[str]") == [_Kind("abstract")]
    assert classify("MutableSequence[str]") == [_Kind("mutable")]
    assert classify("MutableSet[str]") == [_Kind("mutable")]


def test_classify_resolves_a_module_alias_to_its_arms() -> None:
    namespace: dict[str, object] = {
        "Paths": tuple[str, ...],
        "MaybeNames": Optional[frozenset[str]],  # noqa: UP045 -- the form under test
        "Quoted": "Mapping[str, int] | None",
        "Ids": NewType("Ids", tuple[int, ...]),
        "Level": Literal["info", "error"],
        "Plugin": int,
        "Loop": "Loop | None",
    }
    assert classify("Paths", namespace) == [_Kind("tuple")]
    assert classify("MaybeNames | None", namespace) == [_Kind("frozenset")]
    assert classify("Quoted", namespace) == [_Kind("mapping")]
    assert classify("Ids", namespace) == [_Kind("tuple")]
    assert classify("Level", namespace) == []
    assert classify("Plugin", namespace) == []
    assert classify("Loop", namespace) == []  # a self-referential alias terminates
    # Without the module's namespace a bare name is taken to be a class.
    assert classify("Paths") == []


def test_classify_fails_by_name_on_an_alias_it_cannot_read() -> None:
    with pytest.raises(ValueError, match="cannot classify alias Weird"):
        classify("Weird", {"Weird": "tuple[str,"})


def test_discovery_skips_private_records_and_keeps_exported_ones() -> None:
    names = set(_PUBLIC)
    # Underscore module, not exported: private.
    assert "protokit.schema.lint._config.ResolvedLintConfig" not in names
    # Underscore class: private.
    assert "protokit.storage.cli._ScanReport" not in names
    # Underscore module, but exported from ``protokit.forensics``: public.
    assert "protokit.forensics._drift.DriftReport" in names
