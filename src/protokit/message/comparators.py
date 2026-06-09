"""Leaf-level field comparators for protobuf field types.

Comparators handle scalar, enum, bytes, and float comparison only.
All container traversal (messages, repeated, maps, oneofs) is handled
by the engine in differ.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from google.protobuf import descriptor as proto_descriptor

from protokit.message.model import EnumValue


class MessageFieldComparison(Enum):
    """Field-presence comparison mode for ``MessageDifferencer``.

    Pass to :meth:`MessageDifferencer.set_message_field_comparison` to choose
    how a singular field's *presence* (set vs unset) participates in comparison.
    Mirrors C++ ``MessageDifferencer::set_message_field_comparison``.

    Members:
        EQUIVALENT: The default. A field set to its default value is treated as
            equal to an unset field — the "set-to-default ≈ unset" collapse.
            Today's behavior; non-default-vs-unset still reports a presence
            difference.
        EQUAL: Opt-in strict presence. A presence-bearing field set on one side
            (even to its default value) and unset on the other is reported as a
            presence difference. Observable only where presence exists — proto2
            fields, proto3 ``optional`` fields, oneof members, and singular
            message fields. It is a documented NO-OP for proto3
            implicit-presence scalars, which carry no presence bit and so cannot
            distinguish a default value from unset.
    """

    EQUIVALENT = "EQUIVALENT"
    EQUAL = "EQUAL"


class FloatComparison(Enum):
    """Float comparison mode for ``MessageDifferencer``.

    Pass to :meth:`MessageDifferencer.set_float_comparison` to select
    between bit-exact and tolerance-based float comparison.

    Members:
        EXACT: Python ``==`` semantics: bit-identical. ``NaN != NaN``,
            ``+0.0 == -0.0``. The default mode.
        APPROXIMATE: Tolerance-based via ``fraction`` (relative) or
            ``margin`` (absolute) — combined as a logical OR.
            Under this mode, ``NaN == NaN`` and same-sign infinities
            are equal, so float diffs don't spuriously fire on
            representational noise.
    """

    EXACT = "EXACT"
    APPROXIMATE = "APPROXIMATE"


@dataclass
class FloatConfig:
    """Configuration for float comparison.

    Internal holder used by ``MessageDifferencer`` to bundle mode +
    tolerances. Prefer configuring via
    :meth:`MessageDifferencer.set_float_comparison` rather than
    constructing directly.

    Attributes:
        mode: Which ``FloatComparison`` mode to use. Defaults to
            ``EXACT``.
        fraction: Relative tolerance for ``APPROXIMATE`` mode:
            values are equal if
            ``|a - b| <= fraction * max(|a|, |b|)``.
        margin: Absolute tolerance for ``APPROXIMATE`` mode: values
            are equal if ``|a - b| <= margin``. Combined with
            ``fraction`` as logical OR.
    """

    mode: FloatComparison = FloatComparison.EXACT
    fraction: float = 1e-6
    margin: float = 1e-9


def compare_scalar(left: object, right: object) -> bool:
    """Compare two scalar values for equality.

    Works for int, bool, str, bytes. For float, use compare_float.

    Args:
        left: The left-hand value.
        right: The right-hand value.

    Returns:
        True if the values are equal via ``==``.
    """
    return left == right


def compare_float(left: float, right: float, config: FloatConfig) -> bool:
    """Compare two float values according to the configured mode.

    EXACT: Python == semantics. NaN != NaN, -0.0 == 0.0.
    APPROXIMATE: WithinFractionOrMargin. NaN == NaN, inf == inf.

    Args:
        left: The left-hand float value.
        right: The right-hand float value.
        config: FloatConfig controlling comparison mode and tolerances.

    Returns:
        True if the values are considered equal under the configured mode.
    """
    if config.mode == FloatComparison.EXACT:
        return left == right

    # APPROXIMATE mode
    if math.isnan(left) and math.isnan(right):
        return True
    if math.isnan(left) or math.isnan(right):
        return False
    if math.isinf(left) and math.isinf(right):
        return (left > 0) == (right > 0)  # same sign infinity
    if math.isinf(left) or math.isinf(right):
        return False

    diff = abs(left - right)
    return diff <= config.fraction * max(abs(left), abs(right)) or diff <= config.margin


def compare_enum_same_pool(left: int, right: int) -> bool:
    """Compare enum values from the same descriptor pool (by number).

    Args:
        left: Numeric enum value from the left message.
        right: Numeric enum value from the right message.

    Returns:
        True if the integer values are equal.
    """
    return left == right


def compare_enum_cross_pool(
    left_value: int,
    left_name: str,
    right_value: int,
    right_name: str,
) -> tuple[bool, str | None]:
    """Compare enum values across descriptor pools.

    Rules:
    - Name match + number match -> SAME, no warning
    - Name match + number mismatch -> SAME, warning about number drift
    - Name mismatch + number match -> SAME (wire-compatible)
    - Name mismatch + number mismatch -> DIFFERENT

    Args:
        left_value: Numeric enum value from the left message.
        left_name: Canonical enum name from the left descriptor.
        right_value: Numeric enum value from the right message.
        right_name: Canonical enum name from the right descriptor.

    Returns:
        A ``(is_equal, warning_message)`` tuple. ``warning_message`` is
        ``None`` unless the names match but numbers differ.
    """
    if left_name == right_name:
        if left_value == right_value:
            return True, None
        return True, (
            f"enum value '{left_name}' has different numbers "
            f"across schemas ({left_value} vs {right_value})"
        )
    if left_value == right_value:
        return True, None  # wire-compatible
    return False, None


def to_enum_value(value: int, enum_descriptor: proto_descriptor.EnumDescriptor) -> EnumValue:
    """Convert a protobuf enum int value to an EnumValue with canonical name.

    Uses the first name for the number (canonical name, handles aliases).

    Args:
        value: The integer enum value from the wire format.
        enum_descriptor: The enum's descriptor.

    Returns:
        An EnumValue with the canonical name and number. If the value
        is not defined in the descriptor, the name is ``"UNKNOWN_<value>"``.
    """
    name = enum_descriptor.values_by_number.get(value)
    if name is not None:
        return EnumValue(name=name.name, number=value)
    return EnumValue(name=f"UNKNOWN_{value}", number=value)
