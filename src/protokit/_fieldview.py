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

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from functools import cached_property
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from google.protobuf import descriptor as _d

if TYPE_CHECKING:  # pragma: no cover — typing-only import
    from google.protobuf.message import Message

_FD = _d.FieldDescriptor


def field_value(msg: Message, fd: _d.FieldDescriptor) -> object:
    """Read a field's value, whether it is declared or an extension.

    A declared field is an attribute (``msg.name``); a declared *extension*
    is not — it lives in ``msg.Extensions[fd]``, keyed by descriptor, and its
    short name may even collide with a declared field's. Every value read
    that an extension descriptor can reach must go through here (KTD1): the
    differ and the presence helper both do, so extensions traverse the same
    leaf/message/repeated/presence paths as declared fields rather than a
    parallel implementation beside them.
    """
    if fd.is_extension:
        return msg.Extensions[fd]
    return getattr(msg, fd.name)


def field_present(msg: Message, fd: _d.FieldDescriptor) -> bool:
    """Presence for a declared field or an extension.

    ``HasField`` raises on an extension descriptor; ``HasExtension`` is the
    corresponding call. Both answer the same proto2 question. The caller
    owns the precondition that ``fd`` is presence-bearing.
    """
    if fd.is_extension:
        return bool(msg.HasExtension(fd))
    return bool(msg.HasField(fd.name))


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


def is_message_like(field_desc: _d.FieldDescriptor) -> bool:
    """Return True when ``field_desc`` holds a message: ``TYPE_MESSAGE`` or ``TYPE_GROUP``.

    A proto2 group and an editions field with ``message_encoding = DELIMITED``
    are both ``TYPE_GROUP``: a nested message with different wire framing. A
    site that tests ``TYPE_MESSAGE`` alone silently skips them, so every "is
    this a message?" question asks here.
    """
    return field_desc.type in (_FD.TYPE_MESSAGE, _FD.TYPE_GROUP)


def same_message_kind(left: _d.FieldDescriptor, right: _d.FieldDescriptor) -> bool:
    """Whether a comparison may descend from ``left`` into ``right``.

    True only when both are messages or both are groups. A group↔message
    switch changes the wire framing and is reported as its own finding;
    descending as well would pile nested findings on top of it. Map fields and
    map values stay ``TYPE_MESSAGE`` even under DELIMITED, so they pair only
    with messages.
    """
    return is_message_like(left) and left.type == right.type


def extension_key(fd: _d.FieldDescriptor) -> str:
    """Key for an extension: ``(pkg.ext)``.

    Parenthesised and fully qualified — the spelling proto uses for custom
    options (text format spells an extension ``[pkg.ext]``, but brackets are
    the path grammar's index syntax) — so an extension can never be confused
    with, or shadowed by, a declared field of the same short name.
    """
    return f"({fd.full_name})"


def first_undecodable_string(message: Message) -> tuple[_d.FieldDescriptor, bytes] | None:
    """Return the first string field in ``message`` that holds bytes, else ``None``.

    The two runtimes disagree about an undecodable string. Pure-Python rejects
    it while parsing (``UnicodeDecodeError``). upb validates UTF-8 only where
    the field requires it (every proto3 string; an editions string unless it
    sets ``utf8_validation = NONE``; never a proto2 string) and otherwise hands
    the field back as ``bytes``, at any depth. Nothing downstream complains
    about those bytes, so a seam that wants pure-Python's verdict on upb walks
    the parsed message with this and classifies a hit its own way. Only set
    fields are walked: an unset field reads its schema default, and protokit's
    pool loaders reject a schema whose default is not UTF-8.
    """
    stack: list[Message] = [message]  # iterative: messages can nest deeply
    while stack:
        current = stack.pop()
        # ListFields includes registered extensions, so custom options are
        # walked too; an unregistered one stays as unparsed unknown bytes.
        for field, value in current.ListFields():
            for item_field, item in _field_items(field, value):
                if item_field.type == _FD.TYPE_STRING and isinstance(item, bytes):
                    return item_field, item
                if is_message_like(item_field):
                    stack.append(item)
    return None


def _field_items(
    field: _d.FieldDescriptor, value: Any,
) -> Iterator[tuple[_d.FieldDescriptor, Any]]:
    """Yield ``(descriptor, item)`` for each value one set field holds."""
    entry = map_entry(field)
    if entry is not None:
        # Iterating a map yields its keys; check keys and values. Keys come
        # first and values are read only after: on upb, reading a value looks
        # its key up again, which raises UnicodeDecodeError for a bytes key.
        yield from ((entry.key, k) for k in value)
        yield from ((entry.value, v) for v in value.values())
    elif field.label == _FD.LABEL_REPEATED:
        yield from ((field, item) for item in value)
    else:
        yield field, value


def may_hold_unvalidated_string(descriptor: _d.Descriptor) -> bool:
    """Whether a message of this type can hold a string upb did not validate.

    A seam may skip :func:`first_undecodable_string` for a type where this is
    False. The answer is conservative: any string field declared in a file
    that is not proto3 counts (an editions string may opt out of validation),
    and so does any extension range (an extension can carry any string),
    across every message type ``descriptor`` can reach. It walks the type
    graph, so compute it once per type rather than once per message. It
    assumes the pool uses protobuf's standard feature defaults, as every pool
    protokit builds does: a pool given custom ``FeatureSetDefaults`` can turn
    proto3 validation off, and this would then answer False wrongly.
    """
    # Function-level: published docs cite line numbers in this module.
    from google.protobuf import descriptor_pb2

    proto3_files: dict[str, bool] = {}
    seen: set[str] = set()
    stack: list[_d.Descriptor] = [descriptor]
    while stack:
        current = stack.pop()
        if current.full_name in seen:
            continue
        seen.add(current.full_name)
        if current.extension_ranges:
            return True
        file = current.file
        if file.name not in proto3_files:
            # FileDescriptor has no public syntax attribute on protobuf 5.
            syntax = descriptor_pb2.FileDescriptorProto.FromString(file.serialized_pb).syntax
            proto3_files[file.name] = syntax == "proto3"
        for field in current.fields:
            if field.type == _FD.TYPE_STRING and not proto3_files[file.name]:
                return True
            if is_message_like(field):
                stack.append(field.message_type)
    return False


# Messages defined here are descriptor options; their extensions are custom options.
_DESCRIPTOR_PROTO = "google/protobuf/descriptor.proto"


def data_extensions(descriptor: _d.Descriptor) -> tuple[_d.FieldDescriptor, ...]:
    """The declared extensions of ``descriptor`` that a schema comparison pairs.

    This is :attr:`FieldView.extensions`, except that a message defined in
    ``google/protobuf/descriptor.proto`` has none: its extensions are custom
    options, and which of them a pool holds depends on which files it loaded,
    so pairing them would report a difference in the load set rather than in
    the schema. The cost is deliberate: a schema that carries an options
    message as ordinary data has that message's extensions left out.

    Like :attr:`FieldView.extensions`, this sees an extension declared in
    another file only once the pure-Python pool has built that file; every
    protokit loader resolves each file as it adds it (``_pools.add_and_resolve``),
    but a caller that builds its own pool with a bare ``Add`` must do the same.
    """
    if descriptor.file.name == _DESCRIPTOR_PROTO:
        return ()
    return FieldView.of(descriptor).extensions
