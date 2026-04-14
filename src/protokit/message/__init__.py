"""Protobuf message comparison engine.

Python equivalent of Google's C++ ``MessageDifferencer``: structural
comparison of two protobuf messages with cross-pool support, schema
evolution detection, and a pytest hook for rich diff output in test
failures.

See ``protokit.message.differ`` for the engine,
``protokit.message.cli`` for the ``protokit diff`` command, and
``protokit.message.pytest_plugin`` for the assertion-rewrite hook.
"""

from __future__ import annotations

from protokit.message.comparators import FloatComparison
from protokit.message.differ import MessageDifferencer, diff_messages
from protokit.message.model import (
    ChangeType,
    Difference,
    DiffResult,
    DuplicateKeyError,
    EnumValue,
    FieldPath,
    MissingKeyError,
    PathSegment,
    Warning,
)

__all__ = [
    "ChangeType",
    "Difference",
    "DiffResult",
    "DuplicateKeyError",
    "EnumValue",
    "FieldPath",
    "FloatComparison",
    "MessageDifferencer",
    "MissingKeyError",
    "PathSegment",
    "Warning",
    "diff_messages",
]
