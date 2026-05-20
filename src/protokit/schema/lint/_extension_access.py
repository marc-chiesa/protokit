"""Dynamic-pool extension access helpers.

Shared utilities for reading protobuf option-message extensions that
were registered through a protoxy-built :class:`DescriptorPool` (rather
than via a generated ``_pb2`` module).

The naive ``options_msg.Extensions[ext_desc]`` accessor raises
``KeyError`` on a dynamic-pool extension descriptor because
``descriptor.GetOptions()`` returns a bootstrap-pool-bound options
instance whose ``Extensions[]`` accessor doesn't know about the
dynamic-pool extension. The workaround re-parses the options message
through a pool-bound options class, restoring proto2 presence semantics.

The pattern is used by:

- :mod:`protokit.schema.lint._custom_rules` for the synthetic
  ``custom/<suffix>`` rule closures (D6d U1).
- :mod:`protokit.schema.lint.rules.options.field_behavior` for the
  ``options/field-behavior-consistent`` rule (D6d U2).
- Future built-in option-aware rules that consume arbitrary custom
  extensions.

See :func:`get_pool_bound_options_class` and
:func:`resolve_enum_value_for_comparison` for the public surface.

References:

- D6d U1 plan: ``docs/plans/2026-05-19-001-feat-d6d-option-aware-pack-expansion-plan.md``
- Extracted from ``_custom_rules.py`` during D6d U2 per SSOT discipline
  (the helpers must serve both synthetic rules and built-in
  option-aware rules without cross-module private imports).
- Regression contract pinned at
  ``tests/schema/lint/test_protoxy_option_value_encoding_contract.py``.
"""

from __future__ import annotations

from typing import Any

from google.protobuf import descriptor_pb2, message_factory

#: Protobuf ``FieldDescriptorProto.Type.TYPE_ENUM`` constant.
#: Inlined to avoid importing ``descriptor_pb2`` at the call site just
#: for the enum value (the value is wire-format-stable per the protobuf
#: backwards-compat contract).
_TYPE_ENUM: int = descriptor_pb2.FieldDescriptorProto.TYPE_ENUM


def get_pool_bound_options_class(
    pool: Any, options_full_name: str,
) -> type | None:
    """Return a pool-bound options message class, or ``None`` on failure.

    The dynamic-pool options class is the hinge of the extension-
    resolution model — without it, ``options_msg.Extensions[ext_desc]``
    raises ``KeyError`` for any extension descriptor that wasn't
    registered through a generated ``_pb2`` module.

    Returns ``None`` if the options message descriptor is not in the
    pool (e.g., extremely minimal compile sets that exclude
    ``descriptor.proto``); callers treat that as a soft no-op and skip
    rather than raising.

    Uses :func:`google.protobuf.message_factory.GetMessageClass`
    (protobuf 5.26+) when available; falls back to
    ``MessageFactory(pool=pool).GetPrototype()`` for older protobuf
    releases. The fallback raises a deprecation warning on newer
    protobuf but still functions.

    Args:
        pool: The :class:`google.protobuf.descriptor_pool.DescriptorPool`
            the options descriptor should be looked up in. Typically
            :attr:`CompileResult.pool` from a protoxy compile.
        options_full_name: Fully-qualified options message name, e.g.,
            ``"google.protobuf.FieldOptions"``.

    Returns:
        The pool-bound options message class, or ``None`` when the
        options descriptor is absent from the pool.
    """
    try:
        options_desc = pool.FindMessageTypeByName(options_full_name)
    except KeyError:
        return None
    # Newer protobuf (5.26+) exposes ``GetMessageClass`` at module
    # scope; older releases use ``MessageFactory(pool).GetPrototype``.
    get_message_class = getattr(message_factory, "GetMessageClass", None)
    if get_message_class is not None:
        cls: type = get_message_class(options_desc)
        return cls
    # Fallback for protobuf 4.21–5.25.
    factory = message_factory.MessageFactory(pool=pool)
    fallback_cls: type = factory.GetPrototype(options_desc)
    return fallback_cls


def resolve_enum_value_for_comparison(
    ext_desc: Any, value: Any,
) -> Any:
    """Normalize a raw extension value for identifier-string comparison.

    For enum-typed extensions, translates the runtime integer to its
    identifier name via ``ext_desc.enum_type.values_by_number[value].name``.
    For unknown enum numbers (e.g., a buf-time enum that was removed
    from a later proto revision and now appears as a stale integer),
    returns the raw integer unchanged so callers can distinguish the
    unknown-number case from a successful lookup.

    Other scalar types pass through unchanged.

    Args:
        ext_desc: The extension's
            :class:`google.protobuf.descriptor.FieldDescriptor`.
        value: The raw runtime value (int for enum/int32, str for
            string, bool for bool, etc.).

    Returns:
        The identifier-string name for known enum values; the raw
        integer for unknown enum numbers; the input value unchanged
        for non-enum scalars.
    """
    if ext_desc.type != _TYPE_ENUM:
        return value
    enum_type = ext_desc.enum_type
    if enum_type is None:
        return value
    enum_value = enum_type.values_by_number.get(value)
    if enum_value is None:
        # Unknown enum number — keep raw int for diagnostic value.
        return value
    return enum_value.name
