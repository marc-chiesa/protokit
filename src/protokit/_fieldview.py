"""The one canonical way to enumerate a message's fields.

``_descriptors.get_field_map()`` was protokit's de-facto enumeration
chokepoint, and its contract was wrong in two ways its four consumers all
inherited uniformly:

* **It keys only by name.** A consumer that needs to reason about wire
  compatibility wants field *numbers*; keying by name forced each one to
  rebuild a number map or, worse, to compare by name and miss a renumber.
* **It cannot reach extensions at all.** Its ``if not f.is_extension``
  filter reads like a deliberate exclusion, but ``Descriptor.fields``
  never contains extensions in the first place — the filter is vestigial.
  Declared extensions of a message live in the *pool*
  (``pool.FindAllExtensions``), which no consumer consulted, so a proto2
  message carrying a declared extension compared equal on that extension
  no matter what it held (V19).

Nobody bypassed ``get_field_map``; all four consumers already routed
through it. That makes this a **wrong-contract-at-the-chokepoint** seam,
not a bypass-drift one, and per KTD1 its guard is a *contract test* on the
owner (``tests/meta/test_fieldview_contract.py``) rather than a
call-site-enumerating bypass guard. A bypass guard is structurally blind
to the failure this module exists to fix.

**Layer 0 (KTD8).** This module imports nothing from ``protokit`` at any
scope — not at module level, not inside a function body. The import-layer
gate in ``tests/meta/test_import_layers.py`` asserts that on the
deferred-inclusive graph, so a function-level import would fail it too.

**Extensions are a separate namespace, deliberately.** ``by_name`` and
``by_number`` cover *declared, non-extension* fields only; extensions are
reached through :attr:`FieldView.extensions`. Merging them would be
actively wrong here: an extension's identity is its fully-qualified name
(``pkg.ext``), and protobuf lets an extension's short name collide with a
declared field's name on the same message, so a merged map could shadow a
real field. It also keeps ``--where`` / ``--fields`` path resolution
unchanged: those split a user path on ``.`` and require each segment to be
a Python identifier, so a dotted extension name can never match a segment
anyway. Extension access is therefore explicit at the one consumer that
wants it (the differ), instead of implicit everywhere.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import cached_property
from types import MappingProxyType

from google.protobuf import descriptor as _d

_FD = _d.FieldDescriptor


def is_map_field(field_desc: _d.FieldDescriptor) -> bool:
    """Return True when ``field_desc`` is a protobuf ``map<k, v>`` field.

    A map field is encoded as a repeated message whose message type carries
    the synthetic ``map_entry`` option. Owning this predicate here keeps the
    map-entry question and the enumeration question in one module;
    ``_descriptors.is_map_field`` delegates to this function so the two
    cannot drift apart.
    """
    return (
        field_desc.label == _FD.LABEL_REPEATED
        and field_desc.type == _FD.TYPE_MESSAGE
        and bool(field_desc.message_type.GetOptions().map_entry)
    )


@dataclass(frozen=True)
class MapEntry:
    """The ``key`` and ``value`` field descriptors of a map entry."""

    key: _d.FieldDescriptor
    value: _d.FieldDescriptor


def map_entry(field_desc: _d.FieldDescriptor) -> MapEntry | None:
    """Return the ``key``/``value`` descriptors of a map field, else ``None``.

    Returns ``None`` for any field that is not a map field, so a caller can
    branch on the result instead of pairing a predicate call with an
    unchecked attribute walk.
    """
    if not is_map_field(field_desc):
        return None
    entry = field_desc.message_type
    return MapEntry(key=entry.fields_by_name["key"], value=entry.fields_by_name["value"])


@dataclass(frozen=True)
class FieldView:
    """A complete, immutable view of one message descriptor's fields.

    Build with :meth:`of`. ``by_name`` and ``by_number`` are two indexes over
    the same declared non-extension fields, so ``len(by_name) ==
    len(by_number)`` always holds — protobuf forbids duplicate field names
    and duplicate field numbers within a message.

    **Both indexes are built lazily and cached.** The differ constructs a view
    per message pair in its comparison loop and reads only ``by_name``;
    building ``by_number`` eagerly there was measurable waste. Each index is
    computed on first access and frozen behind a ``MappingProxyType``, so the
    view is still immutable — ``frozen=True`` alone only prevents attribute
    rebinding, not mutation of a dict it holds.

    ``extensions`` is resolved against the descriptor's own pool on every
    access rather than snapshotted, because a pool can gain extension
    definitions after this view is built (a later ``pool.Add`` of a file that
    extends this message); snapshotting would reintroduce the staleness this
    seam exists to remove. That makes it the one member with a per-access
    cost — do not call it in a loop without hoisting the result.
    """

    descriptor: _d.Descriptor

    @cached_property
    def by_name(self) -> Mapping[str, _d.FieldDescriptor]:
        """Declared non-extension fields, keyed by name."""
        return MappingProxyType({f.name: f for f in self.descriptor.fields})

    @cached_property
    def by_number(self) -> Mapping[int, _d.FieldDescriptor]:
        """Declared non-extension fields, keyed by field number."""
        return MappingProxyType({f.number: f for f in self.descriptor.fields})

    def name_map(self) -> dict[str, _d.FieldDescriptor]:
        """A FRESH, mutable ``{name: field}`` the caller may modify.

        :attr:`by_name` is cached and frozen, so a caller that needs to add
        entries — the differ folds set extensions into its copy — would have to
        copy it, building two dicts and a proxy per call in a loop that runs at
        every node of a comparison. This builds exactly one dict and hands over
        ownership. Use :attr:`by_name` for read-only access.
        """
        return {f.name: f for f in self.descriptor.fields}

    @property
    def has_extension_ranges(self) -> bool:
        """Whether this message declares any ``extensions N to M;`` range.

        A message with no extension range cannot carry a set extension, by
        protobuf's own invariant. Callers use this to skip extension discovery
        entirely — the common case, and far cheaper than asking a message what
        it has set.
        """
        return bool(self.descriptor.extension_ranges)

    @classmethod
    def of(cls, descriptor: _d.Descriptor) -> FieldView:
        """Build the view for ``descriptor``.

        Args:
            descriptor: A protobuf message ``Descriptor``.

        Returns:
            A :class:`FieldView` over ``descriptor``'s declared fields.
        """
        return cls(descriptor=descriptor)

    @property
    def extensions(self) -> tuple[_d.FieldDescriptor, ...]:
        """Every extension of this message declared in its descriptor's pool.

        This is ``pool.FindAllExtensions``, not ``Descriptor.extensions``.
        The two differ and the distinction is load-bearing:
        ``Descriptor.extensions`` is the set of extensions *declared inside*
        this message's scope, which may extend some other message entirely,
        whereas this property returns the extensions that *extend* this
        message, wherever in the pool they were declared. The latter is the
        set that can actually appear on the wire for a message of this type.

        Ordered by field number so callers get deterministic output without
        re-sorting.
        """
        pool = self.descriptor.file.pool
        return tuple(sorted(pool.FindAllExtensions(self.descriptor), key=lambda f: f.number))
