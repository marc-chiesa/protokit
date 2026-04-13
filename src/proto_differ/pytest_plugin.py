"""pytest assertion hook for protobuf message comparison.

Provides rich diff output when `assert msg1 == msg2` fails for protobuf messages.

Usage — add to your project's conftest.py:

    from proto_differ.pytest_plugin import pytest_assertrepr_compare  # noqa: F401

Or register as a pytest plugin in pyproject.toml:

    [tool.pytest.ini_options]
    plugins = ["proto_differ.pytest_plugin"]
"""

from __future__ import annotations

import warnings
from typing import Any

from google.protobuf.message import Message

from proto_differ.differ import MessageDifferencer
from proto_differ.formatting import format_value as _format_value
from proto_differ.model import ChangeType


def pytest_assertrepr_compare(op: str, left: Any, right: Any) -> list[str] | None:
    """Rich diff output for protobuf message assertions.

    Called by pytest when an ``assert left == right`` fails. Only activates
    when both operands are protobuf ``Message`` instances.

    Args:
        op: The comparison operator (only ``"=="`` is handled).
        left: The left operand of the assertion.
        right: The right operand of the assertion.

    Returns:
        A list of strings for pytest to display as the failure explanation,
        or ``None`` to fall back to the default representation.
    """
    if op != "==" or not isinstance(left, Message) or not isinstance(right, Message):
        return None

    differ = MessageDifferencer()
    try:
        result = differ.compare(left, right)
    except Exception as exc:
        warnings.warn(
            f"proto_differ plugin failed ({type(exc).__name__}: {exc}); "
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

    for warning in result.warnings:
        lines.append(f"  warning: {warning}")

    return lines
