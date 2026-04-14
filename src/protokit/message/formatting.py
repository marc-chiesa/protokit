"""Shared value formatting for human-readable diff output."""

from __future__ import annotations

from protokit.message.model import EnumValue


def format_value(val: object) -> str:
    """Format a diff value for human display.

    Type-specific rendering:

    - ``None`` → ``"<unset>"``
    - ``EnumValue`` → ``"NAME(number)"``
    - ``bytes`` ≤ 32 bytes → ``repr()`` (e.g. ``b'\\x01\\x02'``),
      otherwise a length summary ``"<N bytes>"`` to keep CLI output
      terse.
    - ``str`` → ``repr()`` so quotes and escapes are visible.
    - ``bool`` → lowercase ``"true"`` / ``"false"`` (protobuf style).
    - ``float`` → ``str()``.
    - anything else → ``str()``.

    Args:
        val: The value to format. Any Python object is accepted;
            unknown types fall through to ``str(val)``.

    Returns:
        A single-line string suitable for CLI / pytest-hook output.
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
