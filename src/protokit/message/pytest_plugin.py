"""pytest assertion hook for protobuf message comparison.

Provides rich diff output when `assert msg1 == msg2` fails for protobuf messages.

Usage — add to your project's conftest.py:

    from protokit.message.pytest_plugin import pytest_assertrepr_compare  # noqa: F401

Or register as a pytest plugin in pyproject.toml:

    [tool.pytest.ini_options]
    plugins = ["protokit.message.pytest_plugin"]
"""

from __future__ import annotations

import warnings
from typing import Any

from google.protobuf.message import Message

from protokit.message.differ import MessageDifferencer
from protokit.message.formatting import format_value as _format_value
from protokit.message.model import ChangeType


def pytest_assertrepr_compare(op: str, left: Any, right: Any) -> list[str] | None:
    """Rich diff output for protobuf message assertions.

    Called automatically by pytest when an ``assert left == right``
    statement fails. Activates only when both operands are protobuf
    ``Message`` instances and ``op == "=="`` — all other cases fall
    back to pytest's default representation.

    Comparison is done with a default ``MessageDifferencer`` (no
    ignore fields, no ``treat_as_map``, exact float comparison,
    unlimited depth). If the differencer raises for any reason, the
    exception is caught, a ``UserWarning`` is emitted, and pytest
    falls back to its default output — so a misconfigured plugin
    never masks a test failure.

    Args:
        op: The comparison operator pytest caught (e.g. ``"=="``,
            ``"!="``, ``"<"``). Only ``"=="`` is handled.
        left: Left operand of the failing assertion.
        right: Right operand of the failing assertion.

    Returns:
        A list of display lines for pytest (header + per-difference
        rows + optional warning rows), or ``None`` to defer to the
        default representation. Returning ``None`` happens when:
        the op isn't ``"=="``; either operand isn't a ``Message``;
        the differencer raised; or no differences were found (which
        shouldn't happen since ``==`` failed, but we handle the
        edge case).
    """
    if op != "==" or not isinstance(left, Message) or not isinstance(right, Message):
        return None

    differ = MessageDifferencer()
    try:
        result = differ.compare(left, right)
    except Exception as exc:
        warnings.warn(
            f"protokit plugin failed ({type(exc).__name__}: {exc}); "
            "falling back to default assertion output",
            stacklevel=2,
        )
        return None

    if not result.has_changes():
        return None  # let pytest handle it (shouldn't happen since == failed)

    left_type = left.DESCRIPTOR.full_name
    right_type = right.DESCRIPTOR.full_name
    if left_type == right_type:
        header = f"{left_type} != {right_type}"
    else:
        header = f"{left_type} != {right_type} (cross-schema)"

    lines = [header, f"  {len(result)} difference(s):"]

    for diff in result:
        path_str = str(diff.path) if diff.path else "(root)"
        match diff.change_type:
            case ChangeType.ADDED:
                lines.append(f"  + {path_str}: {_format_value(diff.new_value)}")
            case ChangeType.REMOVED:
                lines.append(f"  - {path_str}: {_format_value(diff.old_value)}")
            case ChangeType.MODIFIED:
                lines.append(
                    f"  ~ {path_str}: {_format_value(diff.old_value)} -> {_format_value(diff.new_value)}"
                )
            case ChangeType.TYPE_CHANGED:
                lines.append(f"  T {path_str}: {diff.left_type} -> {diff.right_type}")
            case ChangeType.FIELD_NUMBER_CHANGED:
                lines.append(
                    f"  # {path_str}: field {diff.left_field_number} -> {diff.right_field_number}"
                )
            case ChangeType.CARDINALITY_CHANGED:
                lines.append(
                    f"  C {path_str}: {diff.left_label} -> {diff.right_label}"
                )

    for d in result.diagnostics:
        prefix = "error" if d.level == "error" else "warning"
        lines.append(f"  {prefix}: {d}")

    return lines
