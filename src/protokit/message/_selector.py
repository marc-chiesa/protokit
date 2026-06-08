"""Unified field selection for selective comparison policies.

A :class:`FieldSelector` names protobuf fields by EITHER a dotted-path /
bare-name string OR a ``(FieldDescriptor, FieldPath)`` predicate. Every
selective comparison policy in the differ — ignore, keyless-set, partial
overrides, per-field tolerance — consumes one of these, so there is a single
selection concept rather than one parser per policy (KTD-1, R9).

Path-form matching delegates to :meth:`FieldPath.matches_selector`, the same
bracket-blind, exact-length segment-name comparison the engine's ``_is_ignored``
and ``_get_treat_as_map_key`` gates use. Both forms therefore agree on the same
selector/path pair; the regression test in ``tests/test_field_selector.py``
pins that equivalence.

This module is strict-typed (``mypy --strict``) and gated by
``tests/test_static_analysis.py``.
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
      segment-name matching. A bare name (``"name"``) matches that field at
      any depth; a dotted path (``"items.name"``) matches that scoped location
      and matches ``"items[0].name"`` but NOT ``"a.items.name"``.
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

    def matches(
        self,
        fd: proto_descriptor.FieldDescriptor,
        path: FieldPath,
    ) -> bool:
        """Return whether this selector matches the given field.

        Path form delegates to :meth:`FieldPath.matches_selector` (the shared
        bracket-blind, exact-length comparison the engine gates use), ignoring
        ``fd``. Predicate form calls the predicate with ``(fd, path)`` as
        explicit arguments; any exception it raises propagates unchanged.

        Args:
            fd: The descriptor of the field being tested.
            path: The concrete field path being tested.

        Returns:
            True if this selector selects the field at ``path``.
        """
        if self._path is not None:
            return self._path.matches_selector(path)
        assert self._predicate is not None  # invariant: exactly one form
        return self._predicate(fd, path)


def should_visit(
    fd: proto_descriptor.FieldDescriptor,
    path: FieldPath,
    expected_side_present: bool,
) -> bool:
    """Partial-mode field-visit decision (KTD-2 / U4).

    In partial / sub-shape matching, only fields present on the ``expected``
    side participate in comparison; extra fields on ``actual`` are not
    differences. This is the pure decision the differ consults at its visit
    gates — it does NOT itself wire into ``differ.py`` (U4 does that).

    Args:
        fd: The descriptor of the field under consideration. Accepted for a
            uniform field-visit decision signature; the partial decision is
            presence-driven and does not consult it today.
        path: The concrete field path under consideration. Accepted for the
            same uniform signature; unused by the partial decision today.
        expected_side_present: Whether the field is present on the expected
            (left) side.

    Returns:
        True if the field should be visited under partial mode, i.e. iff it is
        present on the expected side.
    """
    del fd, path  # presence-driven decision; args kept for a uniform signature
    return expected_side_present
