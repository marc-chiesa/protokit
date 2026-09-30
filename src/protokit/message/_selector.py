"""Unified field selection for selective comparison policies.

A :class:`FieldSelector` names protobuf fields by EITHER a dotted-path /
bare-name string OR a ``(FieldDescriptor, FieldPath)`` predicate. Every
selective comparison policy in the differ — ignore, keyless-set, partial
overrides, per-field tolerance — consumes one of these, so there is a single
selection concept rather than one parser per policy (KTD-1, R9).

Path-form matching is :func:`selects`: the bracket-blind, exact-length name
comparison the engine's ``_is_ignored`` and ``_get_treat_as_map_key`` gates use,
where a lone ``(pkg.ext)`` matches at any depth as those gates' name tables do.
The regression test in ``tests/message/test_field_selector.py``
pins that equivalence.

This module is strict-typed (``mypy --strict``) and gated by
``tests/meta/test_static_analysis.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Union

from protokit.message.model import FieldPath

if TYPE_CHECKING:  # pragma: no cover — typing-only import
    from google.protobuf import descriptor as proto_descriptor

# A predicate decides per field whether the selector matches, receiving the
# field's descriptor and its concrete path as explicit positional arguments
# (KTD-10 — never reached via ``__self__`` or private engine surface).
FieldPredicate = Callable[["proto_descriptor.FieldDescriptor", FieldPath], bool]

# Anything that can be normalized into a FieldSelector: a bare name / dotted
# path string, a predicate, or an already-constructed selector. (``Union`` is
# used rather than ``X | Y`` because the forward reference to ``FieldSelector``
# is evaluated lazily by typing — a runtime ``str | ... | "FieldSelector"`` on
# this module-level alias would need the class to already exist.)
SelectorSpec = Union[str, FieldPredicate, "FieldSelector"]


class FieldSelector:
    """Selects protobuf fields by dotted path/bare name OR by predicate.

    Construct via :meth:`of`, which normalizes a string, a predicate, or an
    existing selector. The two forms share one public surface,
    :meth:`matches`:

    * **Path form** holds a parsed :class:`FieldPath` and delegates to
      :meth:`FieldPath.matches_selector` — bracket-blind, exact-length
      segment-name matching. A bare name (``"name"``) is one segment, so it
      matches only a top-level ``name`` (unlike a bare name given to
      ``ignore_fields`` as a string, which applies at any depth); a dotted path
      (``"items.name"``) matches that scoped location and matches
      ``"items[0].name"`` but NOT ``"a.items.name"``. A lone extension name
      (``"(pkg.ext)"``) matches that extension at any depth, as
      :func:`selects` describes.
    * **Predicate form** calls a ``(FieldDescriptor, FieldPath) -> bool``
      callable with the descriptor and path as explicit arguments. Exceptions
      raised by the predicate PROPAGATE — they are author bugs, not engine
      faults (KTD-10).

    A selector is exactly one of the two forms; the unused attribute is
    ``None``.
    """

    __slots__ = ("_path", "_predicate")

    def __init__(
        self,
        *,
        path: FieldPath | None = None,
        predicate: FieldPredicate | None = None,
    ) -> None:
        """Construct a selector from exactly one form.

        Prefer :meth:`of`, :meth:`from_path`, or :meth:`from_predicate` —
        this constructor enforces the one-form invariant but the factory
        methods read more clearly at call sites.

        Args:
            path: The parsed selector path (path form).
            predicate: The ``(FieldDescriptor, FieldPath) -> bool`` callable
                (predicate form).

        Raises:
            ValueError: If neither or both of ``path``/``predicate`` are given.
        """
        if (path is None) == (predicate is None):
            raise ValueError(
                "FieldSelector requires exactly one of 'path' or 'predicate'"
            )
        self._path = path
        self._predicate = predicate

    @classmethod
    def of(cls, spec: SelectorSpec) -> FieldSelector:
        """Normalize a spec into a :class:`FieldSelector`.

        Args:
            spec: A bare name / dotted-path string, a
                ``(FieldDescriptor, FieldPath) -> bool`` predicate, or an
                already-constructed :class:`FieldSelector` (returned as-is).

        Returns:
            A :class:`FieldSelector` for ``spec``.

        Raises:
            TypeError: If ``spec`` is neither a string, a callable, nor a
                :class:`FieldSelector`.
            ValueError: If a string spec is not a valid dotted path (e.g.
                contains bracket syntax or is malformed — propagated from
                :meth:`FieldPath.parse`).
        """
        if isinstance(spec, FieldSelector):
            return spec
        if isinstance(spec, str):
            return cls.from_path(spec)
        if callable(spec):
            return cls.from_predicate(spec)
        raise TypeError(
            "FieldSelector.of expects a str, a "
            "(FieldDescriptor, FieldPath) -> bool callable, or a FieldSelector; "
            f"got {type(spec).__name__}"
        )

    @classmethod
    def from_path(cls, spec: str) -> FieldSelector:
        """Build a path-form selector from a bare name or dotted path string.

        Args:
            spec: A bare field name (``"name"``) or dotted path
                (``"items.name"``). Brackets are not permitted in selector
                strings.

        Returns:
            A path-form :class:`FieldSelector`.

        Raises:
            ValueError: If ``spec`` is malformed (propagated from
                :meth:`FieldPath.parse`).
        """
        return cls(path=FieldPath.parse(spec))

    @classmethod
    def from_predicate(cls, predicate: FieldPredicate) -> FieldSelector:
        """Build a predicate-form selector from a callable.

        Args:
            predicate: A ``(FieldDescriptor, FieldPath) -> bool`` callable.

        Returns:
            A predicate-form :class:`FieldSelector`.
        """
        return cls(predicate=predicate)

    @property
    def is_predicate(self) -> bool:
        """Whether this selector is the predicate form."""
        return self._predicate is not None

    @property
    def path(self) -> FieldPath | None:
        """The parsed path for a path-form selector, else ``None``.

        Exposed read-only so registration-time conflict checks (e.g. a field
        configured as both ``treat_as_map`` and ``treat_as_set``) can compare
        a path-form selector against other configured paths. Predicate-form
        selectors return ``None`` — they are opaque and cannot be
        conflict-checked at registration (KTD-1, mirroring predicate ignore).
        """
        return self._path

    def matches(
        self,
        fd: proto_descriptor.FieldDescriptor,
        path: FieldPath,
    ) -> bool:
        """Return whether this selector matches the given field.

        Path form ignores ``fd`` and applies :func:`selects`: the shared
        bracket-blind, exact-length comparison the engine gates use, except
        that a lone extension name ``(pkg.ext)`` matches that extension at any
        depth, as ``ignore_fields`` and ``treat_as_map`` always applied it.
        Predicate form calls the predicate with ``(fd, path)`` as explicit
        arguments; any exception it raises propagates unchanged.

        Args:
            fd: The descriptor of the field being tested.
            path: The concrete field path being tested.

        Returns:
            True if this selector selects the field at ``path``.
        """
        if self._path is not None:
            return selects(self._path, path)
        assert self._predicate is not None  # invariant: exactly one form
        return self._predicate(fd, path)


def selects(selector: FieldPath, path: FieldPath) -> bool:
    """Whether a path-form ``selector`` selects the concrete ``path``.

    Bracket-blind, exact-length segment-name matching
    (:meth:`FieldPath.matches_selector`), with one exception: a selector that
    is a lone extension name ``(pkg.ext)`` names the extension, not a location,
    so it selects the path's last segment at any depth. A plain bare name
    keeps exact-length matching here.

    Args:
        selector: The parsed selector path.
        path: The concrete field path being tested.

    Returns:
        True if ``selector`` selects ``path``.
    """
    if is_extension_name(selector):
        return bool(path.segments) and path.segments[-1].name == selector.segments[0].name
    return selector.matches_selector(path)


def is_extension_name(selector: FieldPath) -> bool:
    """Whether ``selector`` is a lone extension name ``(pkg.ext)``.

    Such a selector names an extension rather than a location, so it applies
    at any depth.

    Args:
        selector: The parsed selector path.

    Returns:
        True if the selector is one parenthesised segment.
    """
    return len(selector.segments) == 1 and selector.segments[0].name.startswith("(")


def overlaps(first: FieldPath, second: FieldPath) -> bool:
    """Whether two path-form selectors can select the same field.

    The registration conflict checks use this, so a set/map or ignore/map
    overlap through the extension spelling is caught. For two plain selectors
    it is the same exact-length comparison as before.

    Args:
        first: One parsed selector path.
        second: The other parsed selector path.

    Returns:
        True if either selector selects the other's path.
    """
    return selects(first, second) or selects(second, first)
