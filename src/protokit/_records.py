"""The one place that turns a caller's collection into a frozen record's field.

``@dataclass(frozen=True)`` stops attribute rebinding and nothing else. A
record annotated ``tuple[...]`` stores whatever it is handed, so a caller who
passes a list keeps a live handle on the record's contents:
``DiffResult(differences=items)`` followed by ``items.append(d)`` flips
``bool(result)`` after construction, and ``hash()`` of the "frozen" report
raises (V6, V11). Where a record did convert, it used a bare ``tuple(x)``,
which is worse in one way: a ``str`` is iterable, so
``HistoryReport(entries="abc")`` became three one-character entries that
crashed only later, in a renderer (V11). Of 25 public records with a
collection field, nine converted some of theirs and sixteen none.

This module is the single owner of that conversion (R5). A record's
``__post_init__`` passes each collection field through :func:`as_tuple`,
:func:`as_frozenset`, :func:`as_mapping` or :func:`as_dict`, and each closed-vocabulary string
field through :func:`one_of`.

**What is accepted.** Any iterable, including a generator, a set or a
``range``: every one of those already worked on the records that converted,
and nothing that worked is broken here. What is refused is the input a
conversion would silently take apart — a ``str``, ``bytes`` or ``bytearray``
(iterated into characters or integers) and a ``Mapping`` (iterated into its
keys alone) — with a ``TypeError`` naming the field.

**Failure mode and guard (KTD1, KTD2).** This is *bypass drift*: the right
conversion existed in a few records and the rest went without it. Whether a
record converts is decidable by running it, so the guard is a reflection
test, not a call-site search: ``tests/meta/test_frozen_records.py`` builds
every public frozen dataclass with a list, a set and a dict in its collection
fields and asserts the record owns what it stores. A new public record is
covered as soon as it exists; one the test cannot build fails by name.

**Layer 0 (KTD8).** This module imports nothing from ``protokit`` at any
scope, so every model module can depend on it.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from types import MappingProxyType
from typing import TypeVar

_T = TypeVar("_T")
_K = TypeVar("_K")
_V = TypeVar("_V")

# Iterable, but iterating one takes it apart. A caller who passes one meant a
# single item, or made a mistake; either way the result is not what they had.
def _refuse_taken_apart(value: object, field_name: str) -> None:
    if isinstance(value, Mapping):
        pieces = "its keys"
    elif isinstance(value, str):
        pieces = "characters"
    elif isinstance(value, (bytes, bytearray)):
        pieces = "integers"
    else:
        return
    raise TypeError(
        f"{field_name} must be a collection of items, not a "
        f"{type(value).__name__}: iterating it would split it into {pieces}",
    )


def _iterate(value: Iterable[_T], field_name: str) -> Iterator[_T]:
    _refuse_taken_apart(value, field_name)
    # ``iter()`` alone, so a ``TypeError`` raised by a generator's own body
    # propagates as itself instead of being reported as "not iterable".
    try:
        return iter(value)
    except TypeError as exc:
        raise TypeError(
            f"{field_name} must be a collection of items, not a "
            f"{type(value).__name__}",
        ) from exc


def as_tuple(value: Iterable[_T], field_name: str) -> tuple[_T, ...]:
    """Return ``value`` as a tuple the caller holds no handle on.

    A plain tuple is returned as it is: it is already immutable, and records
    built on hot paths (``FieldPath``) pay one type check for it.

    Args:
        value: Any iterable of items.
        field_name: ``Record.field``, for the error message.

    Returns:
        The items of ``value``, in iteration order.

    Raises:
        TypeError: ``value`` is a ``str``, ``bytes``, ``bytearray`` or
            ``Mapping``, or is not iterable.
    """
    if type(value) is tuple:
        return value
    return tuple(_iterate(value, field_name))


def own_tuples(record: object, *names: str) -> None:
    """Replace each named field of a frozen ``record`` with :func:`as_tuple` of it.

    For a ``__post_init__`` whose record holds several tuple fields; the
    error names ``Record.field``.

    Args:
        record: The dataclass instance being initialised.
        *names: The fields to convert.
    """
    owner = type(record).__name__
    for name in names:
        value = as_tuple(getattr(record, name), f"{owner}.{name}")
        object.__setattr__(record, name, value)


def own_tuples_of_tuples(record: object, *names: str) -> None:
    """Like :func:`own_tuples`, and convert each element to a tuple too.

    For fields of pairs or of paths (``MatchPolicy.approx_overlays``,
    ``CompatibilityPolicy.custom_rules``, ``CompiledSelection.paths``): a
    caller's inner list would otherwise stay shared with the record. An
    element that is a ``str`` is refused like any other, naming
    ``Record.field[]``.

    Args:
        record: The dataclass instance being initialised.
        *names: The fields to convert.
    """
    owner = type(record).__name__
    for name in names:
        outer = as_tuple(getattr(record, name), f"{owner}.{name}")
        inner = f"{owner}.{name}[]"
        object.__setattr__(record, name, tuple(as_tuple(i, inner) for i in outer))


def as_frozenset(value: Iterable[_T], field_name: str) -> frozenset[_T]:
    """Return ``value`` as a frozenset; refuses what :func:`as_tuple` refuses.

    Args:
        value: Any iterable of hashable items.
        field_name: ``Record.field``, for the error message.

    Returns:
        The distinct items of ``value``.

    Raises:
        TypeError: as :func:`as_tuple`.
    """
    if type(value) is frozenset:
        return value
    return frozenset(_iterate(value, field_name))


def as_mapping(value: Mapping[_K, _V], field_name: str) -> Mapping[_K, _V]:
    """Return a read-only copy of ``value``'s top level.

    A ``MappingProxyType`` is returned as it is. That is what protokit's own
    producers hand over (``CompileResult``, the lint engine's accumulators),
    so the lint contexts built once per schema element copy nothing; the cost
    is that a caller who wraps their *own* dict in a proxy keeps a handle on
    it. Values are not copied: a nested mapping stays whatever it was.

    "Mapping" means what ``dict()`` means by it — anything with ``keys()`` —
    so an object that quacks like one is still accepted, and whatever its
    iteration raises reaches the caller as itself.

    Args:
        value: A mapping.
        field_name: ``Record.field``, for the error message.

    Returns:
        A ``MappingProxyType`` over a copy of ``value``, or ``value``.

    Raises:
        TypeError: ``value`` has no ``keys()``: a list of pairs, a string.
    """
    if type(value) is MappingProxyType:
        return value
    if not isinstance(value, Mapping) and not hasattr(value, "keys"):
        raise TypeError(
            f"{field_name} must be a mapping, not a {type(value).__name__}",
        )
    return MappingProxyType(dict(value))


def as_dict(value: Mapping[_K, _V], field_name: str) -> dict[_K, _V]:
    """Return a copy of ``value`` as a ``dict`` the caller holds no handle on.

    For fields whose public type is ``dict`` (``LintFinding.params``): the
    record keeps a ``dict``, but its own one. "Mapping" means what
    :func:`as_mapping` means by it; a list of pairs, which ``dict()`` would
    accept, is refused, because ``dict(["ab"])`` is ``{"a": "b"}``.

    Args:
        value: A mapping.
        field_name: ``Record.field``, for the error message.

    Returns:
        A new ``dict`` with ``value``'s items.

    Raises:
        TypeError: ``value`` has no ``keys()``.
    """
    if not isinstance(value, Mapping) and not hasattr(value, "keys"):
        raise TypeError(
            f"{field_name} must be a mapping, not a {type(value).__name__}",
        )
    return dict(value)


def one_of(value: str, allowed: frozenset[str], field_name: str) -> str:
    """Return ``value`` if it is one of ``allowed``.

    A level outside the vocabulary its readers filter on is invisible to all
    of them: ``Diagnostic(level="fatal")`` is neither a warning nor an error,
    so a report carrying one reads as clean (V7).

    Args:
        value: The field's value.
        allowed: The closed vocabulary.
        field_name: ``Record.field``, for the error message.

    Returns:
        ``value``.

    Raises:
        ValueError: ``value`` is not in ``allowed``.
    """
    if value not in allowed:
        raise ValueError(
            f"{field_name} must be one of {sorted(allowed)}, got {value!r}",
        )
    return value
