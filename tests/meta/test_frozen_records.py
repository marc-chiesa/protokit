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

Optional fields (``X | None``) are checked for their collection arm.

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
from collections.abc import Callable, Iterator, Mapping, MutableMapping
from dataclasses import dataclass
from types import ModuleType
from typing import Any

import pytest

import protokit

# Annotation heads, by the kind of container the field must end up holding.
_TUPLE_HEADS = frozenset({"tuple", "Tuple", "Sequence"})
_FROZENSET_HEADS = frozenset({"frozenset", "FrozenSet"})
_MAPPING_HEADS = frozenset({"Mapping"})
_DICT_HEADS = frozenset({"dict", "Dict"})
# A mutable container annotation on a frozen record is a defect in itself.
_MUTABLE_HEADS = frozenset({"list", "List", "set", "Set", "MutableMapping"})


@dataclass(frozen=True)
class _Kind:
    """The container a field must hold, and what its elements are."""

    head: str  # "tuple", "frozenset", "mapping", "dict" or "mutable"
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


def _union_arms(node: ast.expr) -> Iterator[ast.expr]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        yield from _union_arms(node.left)
        yield from _union_arms(node.right)
    else:
        yield node


def classify(annotation: str) -> list[_Kind]:
    """Return the collection kinds among ``annotation``'s union arms."""
    tree = ast.parse(annotation, mode="eval").body
    kinds: list[_Kind] = []
    for arm in _union_arms(tree):
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
    return kinds


def collection_fields(cls: type) -> dict[str, list[_Kind]]:
    """Map each init field of ``cls`` holding a collection to its kinds."""
    found: dict[str, list[_Kind]] = {}
    for f in dataclasses.fields(cls):
        if not f.init:
            continue
        annotation = f.type if isinstance(f.type, str) else repr(f.type)
        kinds = classify(annotation)
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
    try:
        from_str = getattr(_build(cls, recipe, field_name, "ab"), field_name)
    except TypeError:
        pass
    else:
        if from_str == stored_type(("a", "b")):
            problems.append("splits a str into its characters")
    if nested:
        inner: list[object] = []
        stored = getattr(_build(cls, recipe, field_name, [inner]), field_name)
        inner.append(object())
        if type(stored[0]) is not tuple or stored[0]:
            problems.append("keeps the caller's inner list")
    return problems


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


@pytest.mark.parametrize(
    ("cls", "expected"),
    [
        (_Aliases, "stores a list, not a tuple"),
        (_SplitsStrings, "splits a str into its characters"),
        (_SharesMapping, "shares the caller's dict"),
        (_MutableAnnotation, "annotated as a mutable container"),
        (_FlatNested, "keeps the caller's inner list"),
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


def test_discovery_skips_private_records_and_keeps_exported_ones() -> None:
    names = set(_PUBLIC)
    # Underscore module, not exported: private.
    assert "protokit.schema.lint._config.ResolvedLintConfig" not in names
    # Underscore class: private.
    assert "protokit.storage.cli._ScanReport" not in names
    # Underscore module, but exported from ``protokit.forensics``: public.
    assert "protokit.forensics._drift.DriftReport" in names
