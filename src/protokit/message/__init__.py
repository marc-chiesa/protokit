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

from protokit.message.comparators import FloatComparison, MessageFieldComparison
from protokit.message.differ import MessageDifferencer, diff_messages
from protokit.message.hamcrest import (
    HamcrestExtraNotInstalledError,
    equals_proto,
)
from protokit.message.matchers import (
    Approx,
    MatcherError,
    MatchPolicy,
    expect_proto,
    proto_match,
)
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
    "Approx",
    "ChangeType",
    "Diagnostic",
    "DiagnosticLevel",
    "DiffResult",
    "Difference",
    "DuplicateKeyError",
    "EnumValue",
    "FieldHook",
    "FieldHookContext",
    "FieldPath",
    "FloatComparison",
    "HamcrestExtraNotInstalledError",
    "HookStage",
    "MatchPolicy",
    "MatcherError",
    "MessageDifferencer",
    "MessageFieldComparison",
    "MessageHookContext",
    "MessageValidateHook",
    "MissingKeyError",
    "PathSegment",
    "Warning",  # deprecated alias; remove in a later release
    "diff_messages",
    "equals_proto",
    "expect_proto",
    "proto_match",
]
