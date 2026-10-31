"""Unified field selection for selective comparison policies.

A :class:`FieldSelector` names protobuf fields by EITHER a dotted-path /
bare-name string OR a ``(FieldDescriptor, FieldPath)`` predicate. Every
selective comparison policy in the differ — ignore, keyless-set, partial
overrides, per-field tolerance — consumes one of these, so there is a single
selection concept rather than one parser per policy (KTD-1, R9).

Path-form matching is :func:`selects`, the rule every engine gate applies: a
selector of one segment (a bare name such as ``"name"``, or ``(pkg.ext)``)
selects that field at any depth, and a dotted path selects one location from
the root, bracket-blind. The regression tests in
``tests/message/test_field_selector.py`` pin that equivalence.

Every entry point that takes selector text goes through :func:`parse_selector`,
and every path-form :class:`FieldSelector` is checked when it is built, so an
empty selector (which parses to the root and would select every field) and
bracket syntax (which matching ignores, so ``items[0]`` would select every
element) are refused wherever a selector is given.

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

    * **Path form** holds a parsed :class:`FieldPath` and applies
      :func:`selects`. A bare name (``"name"``) or a lone extension name
      (``"(pkg.ext)"``) selects that field at any depth, exactly as the same
      string does under every policy; a dotted path (``"items.name"``)
      matches that location from the root, bracket-blind, so it matches
      ``"items[0].name"`` but NOT ``"a.items.name"``.
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
            ValueError: If neither or both of ``path``/``predicate`` are given,
                or if ``path`` is empty or has a bracket (see
                :func:`check_selector_path`).
        """
        if (path is None) == (predicate is None):
            raise ValueError(
                "FieldSelector requires exactly one of 'path' or 'predicate'"
            )
        if path is not None:
            check_selector_path(path)
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
            ValueError: If a string spec is empty, contains bracket syntax or
                is malformed (from :func:`parse_selector`).
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
            ValueError: If ``spec`` is empty, contains bracket syntax or is
                malformed (from :func:`parse_selector`).
        """
        return cls(path=parse_selector(spec))

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

        Path form ignores ``fd`` and applies :func:`selects`, the rule the
        engine gates use: one segment selects at any depth, a dotted path from
        the root, bracket-blind.
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

    A selector of one segment (a bare name ``name`` or an extension name
    ``(pkg.ext)``) names a field, not a location, so it selects the path's
    last segment at any depth. A dotted selector selects one location from
    the root: bracket-blind, exact-length segment-name matching
    (:meth:`FieldPath.matches_selector`).

    Args:
        selector: The parsed selector path.
        path: The concrete field path being tested.

    Returns:
        True if ``selector`` selects ``path``.
    """
    if len(selector.segments) == 1:
        return bool(path.segments) and path.segments[-1].name == selector.segments[0].name
    return selector.matches_selector(path)


def overlaps(first: FieldPath, second: FieldPath) -> bool:
    """Whether two path-form selectors can select the same field.

    The registration conflict checks use this, so two policies on one field
    are caught however each selector is spelled: ``items`` (any depth)
    overlaps ``outer.items``, and two dotted paths overlap when they name the
    same location.

    Args:
        first: One parsed selector path.
        second: The other parsed selector path.

    Returns:
        True if either selector selects the other's path.
    """
    return selects(first, second) or selects(second, first)


_EMPTY_SELECTOR = (
    "An empty selector selects every field (it parses to the root path); "
    "omit it instead"
)


def check_selector_path(path: FieldPath, text: str | None = None) -> None:
    """Refuse a selector path that is empty, has a bracket, or does not print as itself.

    Args:
        path: The parsed selector.
        text: The text it was parsed from (``None`` for a path built directly).

    Raises:
        ValueError: If ``path`` has no segments, or any segment a bracket.
            Matching ignores brackets, so ``items[0]`` would select every
            element of ``items``; there is no per-element selector. Also if a
            path built directly from segments does not parse back to itself
            (a segment named ``a.b`` prints as two): a path-form selector
            registers as its text, so the text must mean the same path.
    """
    if len(path.segments) == 0:
        raise ValueError(_EMPTY_SELECTOR)
    if any(segment.bracket is not None for segment in path.segments):
        raise _bracket_error(str(path) if text is None else text)
    if text is None:
        try:
            reparsed = FieldPath.parse(str(path))
        except ValueError:
            reparsed = None
        if reparsed != path:
            raise ValueError(
                f"Selector path {str(path)!r} does not parse back to its own segments "
                f"{[segment.name for segment in path.segments]!r}; each segment must "
                "be one field name, (pkg.ext) or #N"
            )


def _bracket_error(text: str) -> ValueError:
    return ValueError(
        f"Bracket syntax is not supported in selectors: '{text}'. "
        "Use bare field names or dotted paths (e.g. 'field' or 'parent.field')."
    )


def parse_selector(text: str) -> FieldPath:
    """Parse selector text: the one coercion every string entry point uses (KTD1).

    Args:
        text: A bare name, ``(pkg.ext)``, or a dotted path.

    Returns:
        The parsed selector path.

    Raises:
        ValueError: If ``text`` is empty, contains bracket syntax, or is
            malformed.
    """
    if "[" in text:
        raise _bracket_error(text)
    path = FieldPath.parse(text)
    check_selector_path(path, text)
    return path
