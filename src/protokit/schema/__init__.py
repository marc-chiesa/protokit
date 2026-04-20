"""Protobuf schema compatibility policy engine.

Descriptor-level compatibility checking for protobuf schema evolution.
Given two descriptor pools and a type name, reports wire / semantic /
policy-level differences under a chosen compatibility profile.

Public surface:

- ``SchemaChecker`` and ``check_compatibility`` — the engine.
- ``CompatibilityLevel`` / ``CompatibilityReport`` / ``Finding`` /
  ``Severity`` / ``Direction`` / ``Verdict`` / ``Diagnostic`` — data
  model for a single compatibility check.
- ``CommitDiagnostic`` / ``HistoryEntry`` / ``HistoryReport`` /
  ``BisectReport`` — aggregate data model for git-mode subcommands
  (``history`` and ``bisect``).
- ``CompatibilityPolicy`` — bundle a profile with custom rules and
  ignore paths.
- ``FieldRuleContext`` / ``MessageRuleContext`` / ``FieldPlugin`` /
  ``MessagePlugin`` — write custom plugins.
- ``filter_for_level`` — apply a profile filter to raw findings.
"""

from __future__ import annotations

# Diagnostic lives in protokit.message.model (where it
# originated with the differ) and is re-exported here for
# ergonomics: schema callers work with CompatibilityReport
# whose .diagnostics field carries Diagnostic instances, so
# importing the type from the same namespace as the report
# reads more naturally than reaching into the sibling package.
# Both import paths resolve to the same class object — there
# is no divergence risk as long as this file keeps the
# re-export aligned. If a future refactor relocates Diagnostic,
# update both call sites together.
from protokit.message.model import Diagnostic
from protokit.schema.checker import SchemaChecker, check_compatibility
from protokit.schema.model import (
    BisectReport,
    CommitDiagnostic,
    CompatibilityLevel,
    CompatibilityReport,
    Direction,
    Finding,
    HistoryEntry,
    HistoryReport,
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
    "BisectReport",
    "CommitDiagnostic",
    "CompatibilityLevel",
    "CompatibilityPolicy",
    "CompatibilityReport",
    "Diagnostic",
    "Direction",
    "FieldPlugin",
    "FieldRuleContext",
    "Finding",
    "HistoryEntry",
    "HistoryReport",
    "MessagePlugin",
    "MessageRuleContext",
    "SchemaChecker",
    "Severity",
    "Verdict",
    "check_compatibility",
    "filter_for_level",
]
