"""Shared value formatting for human-readable diff output."""

from __future__ import annotations

from proto_differ.model import EnumValue


def format_value(val: object) -> str:
    """Format a diff value for human display.

    Args:
        val: The value to format (may be None, EnumValue, bytes, str,
            bool, float, or any other type).

    Returns:
        A human-readable string representation of the value.
    """
    if val is None:
        return "<unset>"
    if isinstance(val, EnumValue):
        return str(val)
    if isinstance(val, bytes):
        if len(val) <= 32:
            return repr(val)
        return f"<{len(val)} bytes>"
    if isinstance(val, str):
        return repr(val)
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, float):
        return str(val)
    return str(val)
