"""The one place that reads a custom option through the pool declaring it.

``desc.GetOptions()`` always returns an instance of a bootstrap
``descriptor_pb2`` options class — ``FieldOptions``, ``MethodOptions`` and the
rest — whatever pool ``desc`` came from. That class's extension registry knows
only the default pool, so for an extension declared anywhere else protobuf
refuses ``HasExtension`` / ``Extensions[]`` **by identity**, raising
``KeyError`` even though the full names match. That is every schema protokit
loads from a descriptor set: ``protokit._pools`` builds each one into a fresh,
isolated pool. The option's bytes are intact on the message; only the class
reading them is wrong.

So the fix is to re-read those bytes through the class of the options message
the extension actually extends — ``ext_desc.containing_type``, from the
extension's own pool — which restores ``HasExtension`` with its presence
semantics. Binding on the extension rather than on a pool argument keeps the
answer right when a caller looks the extension up in a pool other than the
descriptor's.

Before this module existed the re-read was hand-written twice in
``schema.lint`` and missing from ``protokit.options.get_option_value``, which
swallowed the ``KeyError`` and returned ``None`` for every custom option on an
isolated pool — the same answer as an absent option (V9).

**Failure mode and guard (KTD1, KTD2).** This is *bypass drift*: a correct
implementation existed and the shared helper never adopted it. Whether a call
site builds "a pool-bound options class" is not statically decidable — the
same ``message_factory.GetMessageClass`` call builds ordinary message classes
in ``protokit._pools`` — so the guard is **by construction**, not a name
match: the class builder here is private and the only exported ways in are
:func:`rebind_options` and :func:`extends`. A caller cannot get the class
without writing the construction from scratch, and nothing short of that
reproduces the defect.

**Layer 0 (KTD8).** This module imports nothing from ``protokit`` at any
scope, so ``protokit.options`` (core) and ``protokit.schema.lint`` can both
depend on it without either depending on the other.
"""

from __future__ import annotations

from typing import Any

from google.protobuf import descriptor, message, message_factory


def extends(options: Any, ext_desc: Any) -> bool:
    """Whether ``ext_desc`` extends the options message type of ``options``.

    An extension of ``MethodOptions`` can never be set on a field's
    ``FieldOptions``: asking for it there is asking for an option that type
    cannot hold. Callers that treat that as "absent" test it here, instead of
    catching the ``KeyError`` protobuf raises — a catch that cannot tell this
    case from the identity refusal :func:`rebind_options` exists to fix.

    Compared by full name because the two sides may come from different pools:
    ``options`` is usually a bootstrap-class instance, ``ext_desc`` an
    isolated-pool extension.
    """
    options_type: str = options.DESCRIPTOR.full_name
    extended: str = ext_desc.containing_type.full_name
    return options_type == extended


def rebind_options(options: Any, ext_desc: Any) -> Any:
    """Return ``options`` readable for ``ext_desc``.

    The result supports ``HasExtension(ext_desc)`` and
    ``Extensions[ext_desc]`` with protobuf's own presence semantics. When the
    class of ``options`` already knows the extension — a generated ``_pb2``,
    or a message this function returned — ``options`` itself is returned.
    Otherwise the result is a fresh message of the pool-bound class holding
    the same bytes (declared fields, ``uninterpreted_option`` and all), or,
    if another option's bytes do not parse, only ``ext_desc``'s own records.

    Args:
        options: An options message, typically ``desc.GetOptions()``.
        ext_desc: The extension's ``FieldDescriptor``, from any pool.

    Returns:
        An options message on which ``ext_desc`` resolves.

    Raises:
        KeyError: ``ext_desc`` extends a different options type than
            ``options`` (see :func:`extends`). Re-reading field options as
            method options would decode unrelated bytes, so this refuses, the
            way protobuf itself does.
        google.protobuf.message.DecodeError: the bytes ``options`` holds for
            ``ext_desc`` do not parse as its type, or hold a string that is
            not UTF-8 (on both backends). Another option's bad bytes do not
            raise: the requested option is read on its own instead.
    """
    target = ext_desc.containing_type
    if options.DESCRIPTOR is target:
        return _checked(options, ext_desc)
    if not extends(options, ext_desc):
        raise KeyError(
            f"extension {ext_desc.full_name!r} extends {target.full_name!r}, "
            f"not {options.DESCRIPTOR.full_name!r}"
        )
    rebound = _options_class(target)()
    try:
        rebound.MergeFromString(options.SerializeToString())
    except (message.DecodeError, UnicodeDecodeError):
        # Any option's bytes can fail the whole read (pure-Python also rejects
        # a bad string while parsing), so read just this one's records instead.
        rebound = _only_extension(target, options.SerializeToString(), ext_desc)
    return _checked(rebound, ext_desc)


def _options_class(options_desc: Any) -> Any:
    """Build the message class for ``options_desc`` in its own pool.

    ``message_factory.GetMessageClass`` is absent from protobuf 4.21, the
    declared floor, and present by 4.25, the floor CI runs; a release without
    it reaches the same class through ``MessageFactory(pool).GetPrototype``,
    which newer ones deprecate.
    """
    get_message_class = getattr(message_factory, "GetMessageClass", None)
    if get_message_class is not None:
        return get_message_class(options_desc)
    factory = message_factory.MessageFactory(pool=options_desc.file.pool)
    return factory.GetPrototype(options_desc)


def _checked(options: Any, ext_desc: Any) -> Any:
    """Return ``options``, or raise if its ``ext_desc`` value holds a string that is not UTF-8.

    upb does not check UTF-8 in a proto2 string (or an editions one with
    validation off) and hands the value back as ``bytes``; pure-Python rejects
    it while parsing. This gives the read pure-Python's answer on both.
    """
    if ext_desc.label == _REPEATED:
        value = options.Extensions[ext_desc]
        if len(value) == 0:
            return options
    elif not options.HasExtension(ext_desc):
        return options
    else:
        value = options.Extensions[ext_desc]
    if _holds_undecodable(ext_desc, value):
        raise message.DecodeError(f"{ext_desc.full_name}: a string is not valid UTF-8")
    return options


def _only_extension(options_desc: Any, data: bytes, ext_desc: Any) -> Any:
    """Parse only ``ext_desc``'s records of ``data`` into a fresh options message.

    Every record is framed first, so a framing error anywhere raises
    ``DecodeError`` instead of yielding the records before it (a repeated
    option would read as a partial list).
    """
    kept = b"".join(record for number, record in _records(data) if number == ext_desc.number)
    rebound = _options_class(options_desc)()
    try:
        rebound.MergeFromString(kept)
    except (message.DecodeError, UnicodeDecodeError) as exc:
        raise message.DecodeError(f"{ext_desc.full_name}: {exc}") from exc
    return rebound


def _records(data: bytes) -> list[tuple[int, bytes]]:
    """Split ``data`` into ``(field number, record bytes)`` pairs; raise on bad framing."""
    records: list[tuple[int, bytes]] = []
    pos = 0
    while pos < len(data):
        start = pos
        number, wire_type, pos = _key(data, pos)
        pos = _skip(data, pos, number, wire_type)
        records.append((number, data[start:pos]))
    return records


def _skip(data: bytes, pos: int, number: int, wire_type: int) -> int:
    """Return the position after one field value, its key already read."""
    open_groups = [number] if wire_type == _START_GROUP else []
    while True:
        if wire_type == _VARINT:
            _value, pos = _varint(data, pos)
        elif wire_type == _FIXED64:
            pos += 8
        elif wire_type == _LENGTH_DELIMITED:
            length, pos = _varint(data, pos)
            pos += length
        elif wire_type == _FIXED32:
            pos += 4
        elif wire_type == _END_GROUP:
            if not open_groups or open_groups.pop() != number:
                raise message.DecodeError("end-group marker does not match its group")
        elif wire_type != _START_GROUP:
            raise message.DecodeError(f"invalid wire type {wire_type}")
        if pos > len(data):
            raise message.DecodeError("truncated record")
        if not open_groups:
            return pos
        number, wire_type, pos = _key(data, pos)
        if wire_type == _START_GROUP:
            open_groups.append(number)


def _key(data: bytes, pos: int) -> tuple[int, int, int]:
    key, pos = _varint(data, pos)
    number = key >> 3
    if not 0 < number <= _MAX_FIELD_NUMBER:
        raise message.DecodeError(f"field number {number} out of range")
    return number, key & 7, pos


def _varint(data: bytes, pos: int) -> tuple[int, int]:
    value = shift = 0
    while pos < len(data) and shift < 70:
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7
    raise message.DecodeError("truncated or overlong varint")


# Protobuf wire types (they have no public named constants).
_VARINT, _FIXED64, _LENGTH_DELIMITED, _START_GROUP, _END_GROUP, _FIXED32 = range(6)
_MAX_FIELD_NUMBER = descriptor.FieldDescriptor.MAX_FIELD_NUMBER
_REPEATED = descriptor.FieldDescriptor.LABEL_REPEATED
_STRING = descriptor.FieldDescriptor.TYPE_STRING
_MESSAGE_TYPES = (descriptor.FieldDescriptor.TYPE_GROUP, descriptor.FieldDescriptor.TYPE_MESSAGE)


def _holds_undecodable(field: Any, value: Any) -> bool:
    """Whether ``value`` (of ``field``) holds a string upb returned as bytes, at any depth.

    A private copy of ``protokit._fieldview.first_undecodable_string`` (this
    module may not import it), kept in step by a parity test: map keys before
    values (on upb, reading a value re-reads its key), groups are messages, and
    extensions are found through ``ListFields``, read off the class so a field
    named ``ListFields`` cannot hide it.
    """
    stack: list[tuple[Any, Any]] = [(field, value)]
    while stack:
        current_field, current = stack.pop()
        for item_field, item in _field_items(current_field, current):
            if item_field.type == _STRING and isinstance(item, bytes):
                return True
            if item_field.type in _MESSAGE_TYPES:
                stack.extend(_list_fields(item))
    return False


def _field_items(field: Any, value: Any) -> Any:
    """Yield ``(descriptor, item)`` for each value one set field holds, map keys first."""
    entry = field.message_type
    if field.label == _REPEATED and entry is not None and entry.GetOptions().map_entry:
        yield from ((entry.fields_by_name["key"], key) for key in value)
        yield from ((entry.fields_by_name["value"], item) for item in value.values())
    elif field.label == _REPEATED:
        yield from ((field, item) for item in value)
    else:
        yield field, value


def _list_fields(msg: Any) -> Any:
    """``msg.ListFields()``, found on the class even where a field of that name hides it."""
    for base in type(msg).__mro__:
        attr = base.__dict__.get("ListFields")
        if attr is not None and callable(attr) and not isinstance(attr, property):
            return attr(msg)
    raise AttributeError(f"{type(msg).__name__} has no ListFields")
