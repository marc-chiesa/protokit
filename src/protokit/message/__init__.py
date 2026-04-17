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
    Diagnostic,
    DiagnosticLevel,
    Difference,
    DiffResult,
    DuplicateKeyError,
    EnumValue,
    FieldHook,
    FieldHookContext,
    FieldPath,
    HookStage,
    MessageHookContext,
    MessageValidateHook,
    MissingKeyError,
    PathSegment,
    Warning,  # deprecated alias for Diagnostic; kept for migration
)

__all__ = [
    "ChangeType",
    "Diagnostic",
    "DiagnosticLevel",
    "Difference",
    "DiffResult",
    "DuplicateKeyError",
    "EnumValue",
    "FieldHook",
    "FieldHookContext",
    "FieldPath",
    "FloatComparison",
    "HookStage",
    "MessageDifferencer",
    "MessageHookContext",
    "MessageValidateHook",
    "MissingKeyError",
    "PathSegment",
    "Warning",  # deprecated alias; remove in a later release
    "diff_messages",
]
