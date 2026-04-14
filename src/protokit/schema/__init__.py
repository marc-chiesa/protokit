"""Protobuf schema compatibility policy engine.

Descriptor-level compatibility checking for protobuf schema evolution.
Given two descriptor pools and a type name, reports wire / semantic /
policy-level differences under a chosen compatibility profile.

Public surface:

- ``SchemaChecker`` and ``check_compatibility`` — the engine.
- ``CompatibilityLevel`` / ``CompatibilityReport`` / ``Finding`` /
  ``Severity`` / ``Direction`` / ``Verdict`` — data model.
- ``CompatibilityPolicy`` — bundle a profile with custom rules and
  ignore paths.
- ``FieldRuleContext`` / ``MessageRuleContext`` / ``FieldPlugin`` /
  ``MessagePlugin`` — write custom plugins.
- ``filter_for_level`` — apply a profile filter to raw findings.
"""

from __future__ import annotations

from protokit.schema.checker import SchemaChecker, check_compatibility
from protokit.schema.model import (
    CompatibilityLevel,
    CompatibilityReport,
    Direction,
    Finding,
    Severity,
    Verdict,
)
from protokit.schema.plugins import (
    FieldPlugin,
    FieldRuleContext,
    MessagePlugin,
    MessageRuleContext,
)
from protokit.schema.profiles import (
    CompatibilityPolicy,
    filter_for_level,
)

__all__ = [
    "CompatibilityLevel",
    "CompatibilityPolicy",
    "CompatibilityReport",
    "Direction",
    "FieldPlugin",
    "FieldRuleContext",
    "Finding",
    "MessagePlugin",
    "MessageRuleContext",
    "SchemaChecker",
    "Severity",
    "Verdict",
    "check_compatibility",
    "filter_for_level",
]
