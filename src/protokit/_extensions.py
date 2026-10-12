"""The one place that reads a custom option through the pool declaring it.

``desc.GetOptions()`` always returns an instance of a bootstrap
``descriptor_pb2`` options class — ``FieldOptions``, ``MethodOptions`` and the
rest — whatever pool ``desc`` came from. That class's extension registry knows
only the default pool, so for an extension declared anywhere else protobuf
refuses ``HasExtension`` / ``Extensions[]`` **by identity**, raising
``KeyError`` even though the full names match. That is every schema protokit
loads from a descriptor set: ``protokit._pools`` builds each one into a fresh,
isolated pool. The option's bytes are intact in the schema's file (and, see
:func:`options_of`, usually on the message); the class reading them is wrong.

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
:func:`rebind_options`, :func:`extends` and :func:`options_of`, none of which
hands out the class. A caller cannot get it without writing the construction
from scratch, and nothing short of that reproduces the defect.

**Layer 0 (KTD8).** This module imports nothing from ``protokit`` at any
scope, so ``protokit.options`` (core) and ``protokit.schema.lint`` can both
depend on it without either depending on the other.
"""

from __future__ import annotations

from typing import Any

from google.protobuf import descriptor, descriptor_pb2, descriptor_pool, message, message_factory


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
        _merge(rebound, options.SerializePartialToString())
    except (message.DecodeError, UnicodeDecodeError, RecursionError):
        # Any option's bytes can fail the whole read (pure-Python also rejects a bad
        # string, and overflows the stack on deep nesting): read just this one's.
        rebound = _only_extension(target, options.SerializePartialToString(), ext_desc)
    return _checked(rebound, ext_desc)


def _options_class(options_desc: Any) -> Any:
    """Build the message class for ``options_desc`` in its own pool.

    ``message_factory.GetMessageClass`` is absent from protobuf 4.21, the
    declared floor until 0.16.0, and present in 4.25, the floor since. A
    release without it reaches the same class through
    ``MessageFactory(pool).GetPrototype``, which newer ones deprecate.
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
        _merge(rebound, kept)
    except (message.DecodeError, UnicodeDecodeError, RecursionError) as exc:
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


# Imported here, not at the top: published docs cite line numbers in this file.
import functools  # noqa: E402


def options_of(desc: Any) -> Any:
    """Return ``desc``'s options, every custom option's bytes as the schema's file holds them.

    That is ``desc.GetOptions()`` unless the default pool declares an extension
    those options could hold. upb builds ``GetOptions()`` by decoding the
    options again through the *default* pool's extension registry, and when
    that decode fails it keeps what it had and raises nothing. So an extension
    registered there — the schema's own, or an unrelated one that uses the same
    number for another type — decides what an isolated-pool schema reads as:
    the options after a record that does not decode are gone, that record keeps
    only what decoded, and a record that does decode is written back as the
    other type (an ``int32`` 7 under a ``bool`` comes back as 1).

    The file ``desc`` was built from still holds every byte, so in that case the
    options are read from it, through a class that knows no extension at all.
    The result is then not a ``descriptor_pb2`` class; it has the same declared
    fields, and :func:`rebind_options` reads an extension from it as it does
    from ``GetOptions()``. It also holds ``features`` as an editions file
    declares them, which ``GetOptions()`` leaves out on protobuf 5.27 (4.25
    keeps them). A descriptor that names no file gets ``GetOptions()``, and so
    does one the file cannot tell from another (see :class:`_AmbiguousNameError`).

    Args:
        desc: Any descriptor exposing ``GetOptions()``.

    Returns:
        An options message of ``desc``'s options type. It is shared, like the
        one ``GetOptions()`` returns: do not modify it.
    """
    options = desc.GetOptions()
    kind: str = options.DESCRIPTOR.name
    if kind not in _DECLARATION or not _default_pool_extends(kind):
        return options
    file, find = _DECLARATION[kind]
    file_desc = file(desc)
    if file_desc is None:
        return options
    try:
        file_proto = _file_proto(file_desc)
    except RecursionError:
        # Pure-Python only: its parser recurses once per nested message, and a
        # file its pool built from a shallower stack can be too deep for this one.
        return options
    try:
        return find(file_proto, desc).options
    except _AmbiguousNameError:
        return options


class _AmbiguousNameError(LookupError):
    """Two declarations in one scope share a name, so the file cannot say which one is meant.

    Pure-Python builds a file that declares two messages, or two enums, of one
    name; upb refuses it. Neither kind of descriptor carries an index, so the
    file read gives way to ``GetOptions()``, which pure-Python builds from the
    right declaration and never re-decodes through the default pool.
    """


def _default_pool_extends(options_type: str) -> bool:
    """Whether the default pool declares an extension ``options_type`` could hold.

    Its own, or one of ``FeatureSet``: every options message holds ``features``,
    the one other message in ``descriptor.proto`` that takes extensions, and
    decodes it through the same registry.
    """
    pool = descriptor_pool.Default()
    for name in (options_type, "FeatureSet"):
        try:
            holder = pool.FindMessageTypeByName(f"google.protobuf.{name}")
        except KeyError:  # protobuf before editions has no FeatureSet
            continue
        if pool.FindAllExtensions(holder):
            return True
    return False


# Parsing a file is the cost of one read; the files a caller is working through
# stay parsed. Each entry keeps its file, and so that file's pool, alive.
@functools.lru_cache(maxsize=32)
def _file_proto(file_desc: Any) -> Any:
    """``file_desc`` as a ``FileDescriptorProto`` whose options hold every extension unread."""
    proto = _bare_file_class()()
    proto.MergeFromString(file_desc.serialized_pb)
    return proto


@functools.cache
def _bare_file_class() -> Any:
    """``FileDescriptorProto`` in a pool of its own, which no extension is ever added to."""
    pool = descriptor_pool.DescriptorPool()
    pool.AddSerializedFile(descriptor_pb2.DESCRIPTOR.serialized_pb)
    return _options_class(pool.FindMessageTypeByName("google.protobuf.FileDescriptorProto"))


def _named(protos: Any, name: str) -> Any:
    """The declaration called ``name``: how a message or an enum, which carry no index, is found."""
    found = [proto for proto in protos if proto.name == name]
    if len(found) > 1:
        raise _AmbiguousNameError(f"{name!r} is declared {len(found)} times in one scope")
    if not found:
        raise LookupError(f"{name!r} is not declared where its descriptor says it is")
    return found[0]


def _indexed(protos: Any, desc: Any) -> Any:
    """The declaration of ``desc`` among ``protos``, by its position.

    Not by name: pure-Python builds a message that declares two fields of one
    name (upb refuses the file), and both backends a service with two methods
    of one name. A name would find the first declaration for either.
    """
    proto = protos[desc.index]
    if proto.name != desc.name:
        raise LookupError(f"{desc.name!r} is not declared where its descriptor says it is")
    return proto


def _message_proto(file_proto: Any, desc: Any) -> Any:
    parent = desc.containing_type
    if parent is None:
        return _named(file_proto.message_type, desc.name)
    return _named(_message_proto(file_proto, parent).nested_type, desc.name)


def _enum_proto(file_proto: Any, desc: Any) -> Any:
    parent = desc.containing_type
    scope = file_proto if parent is None else _message_proto(file_proto, parent)
    return _named(scope.enum_type, desc.name)


def _field_proto(file_proto: Any, desc: Any) -> Any:
    if not desc.is_extension:
        return _indexed(_message_proto(file_proto, desc.containing_type).field, desc)
    # An extension is declared in a file or inside a message, neither of which
    # is the message it extends (its ``containing_type``).
    scope = desc.extension_scope
    return _indexed(
        (file_proto if scope is None else _message_proto(file_proto, scope)).extension, desc,
    )


def _method_proto(file_proto: Any, desc: Any) -> Any:
    return _indexed(_indexed(file_proto.service, desc.containing_service).method, desc)


# Options message name -> (the file of a descriptor carrying it, its declaration in that file).
_DECLARATION: dict[str, tuple[Any, Any]] = {
    "FileOptions": (lambda desc: desc, lambda file_proto, desc: file_proto),
    "MessageOptions": (lambda desc: desc.file, _message_proto),
    "FieldOptions": (lambda desc: desc.file, _field_proto),
    "OneofOptions": (
        lambda desc: desc.containing_type.file,
        lambda file_proto, desc: _indexed(
            _message_proto(file_proto, desc.containing_type).oneof_decl, desc,
        ),
    ),
    "EnumOptions": (lambda desc: desc.file, _enum_proto),
    "EnumValueOptions": (
        lambda desc: desc.type.file,
        lambda file_proto, desc: _indexed(_enum_proto(file_proto, desc.type).value, desc),
    ),
    "ServiceOptions": (
        lambda desc: desc.file, lambda file_proto, desc: _indexed(file_proto.service, desc),
    ),
    "MethodOptions": (lambda desc: desc.containing_service.file, _method_proto),
}


def _merge(options: Any, data: bytes) -> None:
    """Parse ``data`` into ``options``, an empty message, building any class pure-Python did not.

    Pure-Python builds a message class only when asked, and nothing asks for
    the element type of a *repeated* message-typed extension: parsing one
    raises ``AttributeError: 'Descriptor' object has no attribute
    '_concrete_class'``, and one such option in an element's bytes failed the
    read of every option beside it. The error carries the descriptor it was
    raised on, so exactly that class is built and the bytes are parsed again,
    once for each class the parse turns out to miss.

    An ``AttributeError`` about anything else propagates, and so does one
    about a class already built here. upb never raises it, so the first parse
    is the only one there.
    """
    built: set[str] = set()
    while True:
        try:
            options.MergeFromString(data)
        except AttributeError as exc:
            missing = getattr(exc, "obj", None)
            if (
                getattr(exc, "name", None) != "_concrete_class"
                or not isinstance(missing, descriptor.Descriptor)
                or missing.full_name in built
            ):
                raise
            built.add(missing.full_name)
            message_factory.GetMessageClass(missing)
            options.Clear()
        else:
            return
