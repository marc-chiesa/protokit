"""Extension-value helpers for option-aware lint rules.

Reading a protobuf option-message extension that was registered
through a protoxy-built :class:`DescriptorPool` (rather than via a
generated ``_pb2`` module) takes two steps. The first — re-reading
``descriptor.GetOptions()`` through a pool-bound options class, because
the bootstrap-pool-bound instance ``GetOptions()`` returns raises
``KeyError`` on a dynamic-pool extension descriptor — lives in
:mod:`protokit._extensions` since U5, shared with
:func:`protokit.options.get_option_value`. This module keeps the
second, lint-specific step: turning the value read into the form a
rule compares against.

The pattern is used by:

- :mod:`protokit.schema.lint._custom_rules` for the synthetic
  ``custom/<suffix>`` rule closures.
- :mod:`protokit.schema.lint.rules.options.field_behavior` for the
  ``options/field-behavior-consistent`` rule.
- Future built-in option-aware rules that consume arbitrary custom
  extensions.

See :func:`resolve_enum_value_for_comparison` for the helper exposed
by this module.

**Visibility note:** the leading underscore on the module name marks
this as an implementation detail of the lint package — NOT part of the
protokit public API. The helper intentionally lacks an underscore
prefix so internal callers within the lint package can import it
by name; it is ``package-internal public`` (callable from any
module under ``protokit.schema.lint.*``) but not stable across
protokit releases. External rule-pack authors should pin a protokit
version range if they depend on this helper; the Public Surface
(DRAFT) appendix in README classifies this module as INTERNAL.

References:

- Extracted from ``_custom_rules.py`` as part of SSOT discipline
  (the helper must serve both synthetic rules and built-in
  option-aware rules without cross-module private imports).
- Regression contract pinned at
  ``tests/schema/lint/test_protoxy_option_value_encoding_contract.py``;
  the re-read's own contract at ``tests/core/test_extensions.py``.
"""

from __future__ import annotations

from typing import Any

from google.protobuf import descriptor_pb2

#: Protobuf ``FieldDescriptorProto.Type.TYPE_ENUM`` constant.
#: Inlined to avoid importing ``descriptor_pb2`` at the call site just
#: for the enum value (the value is wire-format-stable per the protobuf
#: backwards-compat contract).
_TYPE_ENUM: int = descriptor_pb2.FieldDescriptorProto.TYPE_ENUM


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
