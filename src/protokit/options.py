"""Custom-option access for descriptors.

Shared by the schema checker plugin system and the differ hook
system. Reads a custom option from any descriptor that exposes
``GetOptions()`` and can name its owning pool — FieldDescriptor,
Descriptor, EnumDescriptor, EnumValueDescriptor, FileDescriptor,
ServiceDescriptor, MethodDescriptor, OneofDescriptor. They don't
reach their pool the same way (see ``_owning_pool``), so don't
assume ``desc.file`` exists.

The helper has two access tiers:

1. ``Extensions[]`` via ``pool.FindExtensionByName``. This is the
   happy path when the extension's ``FieldDescriptor`` is
   registered in the pool — a generated ``_pb2`` module, or a
   descriptor set built with ``--include_imports`` and loaded into an
   isolated pool, whose options ``protokit._extensions`` re-reads.
2. ``uninterpreted_option`` linear scan. Always available — this
   is what ends up on the options message when a descriptor set is
   built programmatically (or loaded from a ``.descriptor_set``
   without the extension's generated class registered globally).

Both tiers handle the common dotted-path case where the option
value is itself a message and the caller wants a sub-field — tier
1 walks the path via attribute access on the extension value; tier
2 matches the name exactly against the ``uninterpreted_option``
``NamePart`` sequence.

Returns ``None`` when the option is not present in either tier —
"present" meaning explicitly set, never merely registered (see the
presence guard in tier 1).
"""

from __future__ import annotations

from typing import Any

from google.protobuf import descriptor_pool

from protokit._descriptors import is_repeated
from protokit._extensions import extends, rebind_options

_UOP_VALUE_FIELDS: tuple[str, ...] = (
    "identifier_value",
    "positive_int_value",
    "negative_int_value",
    "double_value",
    "string_value",
    "aggregate_value",
)


def _owning_pool(desc: Any) -> descriptor_pool.DescriptorPool:
    """Resolve the descriptor pool that ``desc`` was loaded into.

    The accepted descriptor types don't agree on how to reach their
    file, and the disagreement is backend-specific. Under upb (the
    default backend) a ``FileDescriptor`` has no ``file`` — it *is*
    the file, and exposes ``pool`` directly — while a
    ``MethodDescriptor``, a ``OneofDescriptor`` and an
    ``EnumValueDescriptor`` have neither and reach their file only
    through their service, message and enum type respectively.
    Pure-python protobuf gives all of them a ``file``, so ``file`` is
    tried first and the fallbacks only engage where it is genuinely
    absent.

    ``file`` must be probed before ``type``: a ``FieldDescriptor``
    has a ``type`` attribute too, but it holds the wire type, not
    the owning enum.
    """
    file = getattr(desc, "file", None)
    if file is not None:
        return file.pool
    pool = getattr(desc, "pool", None)
    if pool is not None:
        return pool
    # Under upb a MethodDescriptor reaches its file only through its
    # service, and a OneofDescriptor only through its message.
    service = getattr(desc, "containing_service", None)
    if service is not None:
        return service.file.pool
    message = getattr(desc, "containing_type", None)
    if message is not None:
        return message.file.pool
    # EnumValueDescriptor. A descriptor type with none of these is a
    # caller bug, so let the AttributeError propagate.
    return desc.type.file.pool


def get_option_value(
    desc: Any,
    option_path: str,
    pool: descriptor_pool.DescriptorPool | None = None,
) -> object | None:
    """Read a custom option value from a descriptor's options message.

    Tries tier 1 (``Extensions[]``) then tier 2
    (``uninterpreted_option``) and returns ``None`` if the option
    is not found. See the module docstring for a longer
    explanation of the two tiers.

    The ``option_path`` supports dotted sub-field traversal of
    message-typed extensions. The helper tries successively shorter
    prefixes of the path as an extension full name (greedy
    right-to-left), and on match walks the remainder via attribute
    access on the extension's value message.

    Args:
        desc: Any descriptor exposing ``GetOptions()`` and a route
            to its pool. Raises ``AttributeError`` if not — the
            helper treats a wrong descriptor type as a programming
            error, not an "option absent" result.
        option_path: Dotted path of the option, e.g.
            ``"validate.rules.repeated.max_items"``. For a top-
            level extension with a scalar value, just the
            extension's full name (``"my_label"``). For a nested
            sub-field of a message-valued extension, the extension
            name followed by the field path
            (``"my_ext.nested.deeper"``).
        pool: Descriptor pool to search for the extension in tier
            1. When ``None``, uses the pool that owns ``desc``.
            Pass an explicit pool when the extension lives in a
            different pool than the descriptor.

    Returns:
        The option value (scalar Python value or message) when the
        option is *present* on the descriptor, else ``None``.
        Presence is strict: an extension that is registered in the
        pool but never set on this descriptor reads as ``None``, not
        as its type default (0, "", b"", an empty sub-message, or a
        proto2 ``default_value``). That holds for proto3 extensions
        too — extension fields always carry explicit presence,
        whatever the syntax of the file that declares them.
        Repeated extensions have no presence bit, so an empty
        repeated extension is what reads as ``None``.
    """
    options = desc.GetOptions()
    if pool is None:
        pool = _owning_pool(desc)
    parts = option_path.split(".")

    # Tier 1: extension lookup with greedy prefix matching.
    for split_at in range(len(parts), 0, -1):
        ext_name = ".".join(parts[:split_at])
        try:
            ext_desc = pool.FindExtensionByName(ext_name)
        except KeyError:
            continue
        # An extension of another options type (a method option asked
        # of a field) cannot be set here, so it is absent — tested
        # explicitly, never inferred from a ``KeyError``: that catch is
        # what turned every isolated-pool option into ``None`` (V9).
        if not extends(options, ext_desc):
            continue
        readable = rebind_options(options, ext_desc)
        # Presence guard. ``Extensions[]`` alone happily hands back
        # the type default (or an empty sub-message) for an extension
        # that is merely REGISTERED, which would make the caller's
        # ``is not None`` test true on every unannotated descriptor in
        # the schema. Extension fields always track explicit presence
        # — in proto3 as much as proto2 — so ``HasExtension`` is
        # authoritative for every singular extension; it is
        # *unsupported* for repeated ones (raises), where emptiness is
        # the only absence signal.
        ext_value: object
        if is_repeated(ext_desc):
            values = readable.Extensions[ext_desc]
            if len(values) == 0:
                continue
            ext_value = values
        else:
            if not readable.HasExtension(ext_desc):
                continue
            ext_value = readable.Extensions[ext_desc]
        sub_parts = parts[split_at:]
        if not sub_parts:
            return ext_value
        current: object | None = ext_value
        for part in sub_parts:
            current = getattr(current, part, None)
            if current is None:
                break
        if current is not None:
            return current

    # Tier 2: uninterpreted_option linear scan.
    for uop in options.uninterpreted_option:
        name = ".".join(np.name_part for np in uop.name)
        if name != option_path:
            continue
        for fld in _UOP_VALUE_FIELDS:
            if uop.HasField(fld):
                value: object = getattr(uop, fld)
                return value
        return None

    return None
