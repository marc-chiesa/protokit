"""Custom-option access for descriptors.

Shared by the schema checker plugin system and the differ hook
system. Reads a custom option from any descriptor that exposes
``GetOptions()`` and ``file`` — FieldDescriptor, Descriptor,
EnumDescriptor, EnumValueDescriptor, FileDescriptor.

The helper has two access tiers:

1. ``Extensions[]`` via ``pool.FindExtensionByName``. This is the
   happy path when the extension's ``FieldDescriptor`` is
   registered in the pool (the typical case for runtime-loaded
   generated ``_pb2`` modules and protoc-compiled descriptor sets
   built with ``--include_imports``).
2. ``uninterpreted_option`` linear scan. Always available — this
   is what ends up on the options message when a descriptor set is
   built programmatically (or loaded from a ``.descriptor_set``
   without the extension's generated class registered globally).

Both tiers handle the common dotted-path case where the option
value is itself a message and the caller wants a sub-field — tier
1 walks the path via attribute access on the extension value; tier
2 matches the name exactly against the ``uninterpreted_option``
``NamePart`` sequence.

Returns ``None`` when the option is not present in either tier.
"""

from __future__ import annotations

from google.protobuf import descriptor_pool

_UOP_VALUE_FIELDS: tuple[str, ...] = (
    "identifier_value",
    "positive_int_value",
    "negative_int_value",
    "double_value",
    "string_value",
    "aggregate_value",
)


def get_option_value(
    desc: object,
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
        desc: Any descriptor exposing ``GetOptions()`` and a
            ``file`` attribute. Raises ``AttributeError`` if not
            — the helper treats a wrong descriptor type as a
            programming error, not an "option absent" result.
        option_path: Dotted path of the option, e.g.
            ``"validate.rules.repeated.max_items"``. For a top-
            level extension with a scalar value, just the
            extension's full name (``"my_label"``). For a nested
            sub-field of a message-valued extension, the extension
            name followed by the field path
            (``"my_ext.nested.deeper"``).
        pool: Descriptor pool to search for the extension in tier
            1. When ``None``, uses ``desc.file.pool``. Pass an
            explicit pool when the extension lives in a different
            pool than the descriptor.

    Returns:
        The option value (scalar Python value or message) when
        found, else ``None``. For proto3 scalar extensions, the
        returned value is the type default (0, "", b"") when the
        extension is registered but not explicitly set — proto3
        doesn't preserve the "unset vs. default" distinction for
        scalars. Use proto2 or a message-valued extension if you
        need strict presence semantics.
    """
    options = desc.GetOptions()
    if pool is None:
        pool = desc.file.pool
    parts = option_path.split(".")

    # Tier 1: extension lookup with greedy prefix matching.
    for split_at in range(len(parts), 0, -1):
        ext_name = ".".join(parts[:split_at])
        try:
            ext_desc = pool.FindExtensionByName(ext_name)
        except KeyError:
            continue
        try:
            ext_value = options.Extensions[ext_desc]
        except (KeyError, ValueError):
            continue
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
                return getattr(uop, fld)
        return None

    return None
