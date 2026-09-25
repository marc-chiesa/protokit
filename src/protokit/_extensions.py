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

from google.protobuf import message, message_factory


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
    the same bytes, so declared fields and ``uninterpreted_option`` survive;
    ``options`` is never modified.

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
            an extension do not parse as that extension's type. The bootstrap
            class keeps them opaque; this is the first read that interprets
            them.
    """
    target = ext_desc.containing_type
    if options.DESCRIPTOR is target:
        return options
    if not extends(options, ext_desc):
        raise KeyError(
            f"extension {ext_desc.full_name!r} extends {target.full_name!r}, "
            f"not {options.DESCRIPTOR.full_name!r}"
        )
    rebound = _options_class(target)()
    try:
        rebound.MergeFromString(options.SerializeToString())
    except UnicodeDecodeError as exc:
        # Pure-python validates proto3 string UTF-8 while parsing and raises
        # this where upb raises DecodeError; callers get one type on both.
        raise message.DecodeError(f"{ext_desc.full_name}: {exc}") from exc
    return rebound


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
