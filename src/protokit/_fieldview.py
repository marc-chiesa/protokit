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

    The walk reads only fields that can hold such a string (:class:`StringWalk`
    has the rule), so a proto3 message costs one lookup per type: upb validates
    every proto3 string, assuming protobuf's standard feature defaults
    (:func:`may_hold_unvalidated_string`). This plans each type afresh; a seam
    that walks many messages of the same types, as a storage scan does, keeps
    one :class:`StringWalk` and calls its ``first`` instead, so each type is
    planned once rather than once per message. A seam reporting a hit can word
    it with :func:`not_utf8_detail`.

    It runs after each payload parse: storage scans, ``forensics match``, ``diff``.
    """
    return StringWalk().first(message)


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


def _message_api() -> frozenset[str]:
    """Public attributes of a generated message class that a field name can collide with.

    Read from a real generated class as well as the abstract ``Message``, so the
    runtime's own additions count (pure-Python adds ``Extensions`` and
    ``FindInitializationErrors``). That class's own fields, nested types and
    enum values are left out: protoc stops a field from sharing their names.
    Per-field ``*_FIELD_NUMBER`` constants are matched by suffix instead.
    """
    # Function-level: published docs cite line numbers in this module.
    from google.protobuf import descriptor_pb2
    from google.protobuf.message import Message as _Message

    sample = descriptor_pb2.FileOptions
    own = {field.name for field in sample.DESCRIPTOR.fields}
    own |= {nested.name for nested in sample.DESCRIPTOR.nested_types}
    for enum in sample.DESCRIPTOR.enum_types:
        own |= {enum.name, *(value.name for value in enum.values)}
    names = set(dir(_Message)) | set(dir(sample))
    return frozenset(
        name for name in names
        if not name.startswith("_") and name not in own and not name.endswith("_FIELD_NUMBER")
    )


# Field names that collide with a generated class's attributes. Such a field
# hides the attribute on upb (field access wins) and is hidden by it on
# pure-Python (the attribute wins), so the walk reads a type holding one
# through ListFields.
_SHADOWING = _message_api()


def _shadows(name: str) -> bool:
    """Whether a field called ``name`` collides with a generated class attribute."""
    # Pure-Python gives each field ``f`` a constant ``F_FIELD_NUMBER``.
    return name in _SHADOWING or name.endswith("_FIELD_NUMBER")


def _unshadowed(cls: type, method: str) -> Any:
    """The message class's own ``method``, even where a field of that name hides it."""
    for base in cls.__mro__:
        attr = base.__dict__.get(method)
        if attr is not None and callable(attr) and not isinstance(attr, property):
            return attr
    raise AttributeError(f"{cls.__name__} has no {method} method")


# What one planned field of a message type can hold (see StringWalk).
_STRING, _STRINGS, _MESSAGE, _MESSAGES, _MAP = range(5)

_MapPlan = tuple[MapEntry, bool, "int | None"]
# (attribute name, kind, map plan, descriptor): the name is stored because reading
# ``descriptor.name`` once per field per message is measurable in a scan.
_FieldPlan = tuple[str, int, "_MapPlan | None", _d.FieldDescriptor]


class StringWalk:
    """The walk behind :func:`first_undecodable_string`, planned once per message type.

    The first time the walk meets a message type it records which of the
    type's fields can hold a string upb did not validate: a string field (or a
    map key or value) declared in a file that is not proto3, and a message,
    group or map field whose type can reach one
    (:func:`may_hold_unvalidated_string`). Only those fields are read after
    that, so a type that cannot hold such a string costs one lookup. A type
    with an extension range also has its set extensions read, whatever file
    declares them. A seam that parses many messages of the same types keeps
    one walk for all of them. A walk holds descriptors, so it should not
    outlive the pools it was used with.
    """

    def __init__(self) -> None:
        self._plans: dict[_d.Descriptor, tuple[tuple[_FieldPlan, ...], bool, bool]] = {}
        self._reaches: dict[_d.Descriptor, bool] = {}
        # Keyed by the file descriptor, not its name: two pools may each hold
        # a file of the same name, one proto3 and one not.
        self._proto3_files: dict[_d.FileDescriptor, bool] = {}

    def first(self, message: Message) -> tuple[_d.FieldDescriptor, bytes] | None:
        """Return the first string field in ``message`` that holds bytes, else ``None``."""
        # type(...).DESCRIPTOR: a field may be named DESCRIPTOR (see _SHADOWING).
        plan = self._plans.get(type(message).DESCRIPTOR)
        if plan is None:
            plan = self._plan(type(message).DESCRIPTOR)
        if not plan[0] and not plan[1] and not plan[2]:
            return None  # the common proto3 case: nothing in this type to read
        stack: list[Message] = [message]  # iterative: messages can nest deeply
        while stack:
            current = stack.pop()
            plan = self._plans.get(type(current).DESCRIPTOR)
            if plan is None:
                plan = self._plan(type(current).DESCRIPTOR)
            fields, has_extensions, shadowed = plan
            if shadowed:
                # A field named like a Message method hides the method on upb and
                # the field on pure-Python, so neither ``current.HasField`` nor
                # ``getattr(current, name)`` can be trusted: read every set field
                # through the class's own ListFields instead.
                for field, value in _unshadowed(type(current), "ListFields")(current):
                    for item_field, item in _field_items(field, value):
                        if item_field.type == _FD.TYPE_STRING and isinstance(item, bytes):
                            return item_field, item
                        if is_message_like(item_field):
                            stack.append(item)
                continue
            for name, kind, map_plan, field in fields:
                if kind == _MESSAGE:
                    if current.HasField(name):
                        stack.append(getattr(current, name))
                    continue
                value = getattr(current, name)
                if kind == _STRING:
                    if isinstance(value, bytes):
                        return field, value
                elif kind == _STRINGS:
                    for item in value:
                        if isinstance(item, bytes):
                            return field, item
                elif kind == _MESSAGES:
                    stack.extend(value)
                else:
                    assert map_plan is not None  # invariant: _MAP carries its plan
                    entry, check_keys, value_kind = map_plan
                    # Keys first, values only after: on upb, reading a value
                    # looks its key up again, which raises UnicodeDecodeError
                    # for a bytes key.
                    if check_keys:
                        for key in value:
                            if isinstance(key, bytes):
                                return entry.key, key
                    if value_kind == _STRING:
                        for item in value.values():
                            if isinstance(item, bytes):
                                return entry.value, item
                    elif value_kind == _MESSAGE:
                        stack.extend(value.values())
            if has_extensions:
                # ListFields includes registered extensions, so custom options are
                # walked too; an unregistered one stays as unparsed unknown bytes.
                for field, value in current.ListFields():
                    if not field.is_extension:
                        continue
                    for item_field, item in _field_items(field, value):
                        if item_field.type == _FD.TYPE_STRING and isinstance(item, bytes):
                            return item_field, item
                        if is_message_like(item_field):
                            stack.append(item)
        return None

    def _plan(self, descriptor: _d.Descriptor) -> tuple[tuple[_FieldPlan, ...], bool, bool]:
        """Record which of ``descriptor``'s own fields the walk has to read."""
        unvalidated = not self._is_proto3(descriptor.file)
        planned: list[_FieldPlan] = []
        # Field-number order, as ListFields reports, so a message with several bad
        # declared strings names the one it always did (extensions are read last).
        for field in sorted(descriptor.fields, key=lambda f: f.number):
            entry = map_entry(field)
            if entry is not None:
                check_keys = unvalidated and entry.key.type == _FD.TYPE_STRING
                value_kind: int | None = None
                if entry.value.type == _FD.TYPE_STRING:
                    value_kind = _STRING if unvalidated else None
                elif is_message_like(entry.value) and self._can_reach(entry.value.message_type):
                    value_kind = _MESSAGE
                if check_keys or value_kind is not None:
                    planned.append((field.name, _MAP, (entry, check_keys, value_kind), field))
            elif field.type == _FD.TYPE_STRING:
                if unvalidated:
                    repeated = field.label == _FD.LABEL_REPEATED
                    planned.append((field.name, _STRINGS if repeated else _STRING, None, field))
            elif is_message_like(field) and self._can_reach(field.message_type):
                repeated = field.label == _FD.LABEL_REPEATED
                planned.append((field.name, _MESSAGES if repeated else _MESSAGE, None, field))
        shadowed = any(_shadows(field.name) for field in descriptor.fields)
        plan = (tuple(planned), bool(descriptor.extension_ranges), shadowed)
        self._plans[descriptor] = plan
        return plan

    def _can_reach(self, descriptor: _d.Descriptor) -> bool:
        reaches = self._reaches.get(descriptor)
        if reaches is None:
            reaches = self._reaches[descriptor] = may_hold_unvalidated_string(descriptor)
        return reaches

    def _is_proto3(self, file: _d.FileDescriptor) -> bool:
        proto3 = self._proto3_files.get(file)
        if proto3 is None:
            # Function-level: published docs cite line numbers in this module.
            from google.protobuf import descriptor_pb2

            # FileDescriptor has no public syntax attribute on protobuf 5.
            syntax = descriptor_pb2.FileDescriptorProto.FromString(file.serialized_pb).syntax
            proto3 = self._proto3_files[file] = syntax == "proto3"
        return proto3


def not_utf8_detail(field: _d.FieldDescriptor) -> str:
    """How a seam words a :func:`first_undecodable_string` hit on ``field``."""
    return f"string field {field.full_name} is not valid UTF-8"
