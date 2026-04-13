"""proto-differ: Python equivalent of Google's C++ MessageDifferencer."""

from proto_differ.comparators import FloatComparison
from proto_differ.differ import MessageDifferencer, diff_messages
from proto_differ.model import (
    ChangeType,
    Difference,
    DiffResult,
    DuplicateKeyError,
    EnumValue,
    FieldPath,
    MissingKeyError,
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
    "Warning",
    "diff_messages",
]
