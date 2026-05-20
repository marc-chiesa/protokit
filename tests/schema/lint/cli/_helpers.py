"""Cross-file test helpers for ``protokit lint`` CLI + formatter tests.

D5 U4 removed the legacy ``warning[lint-runtime]:`` stderr loop.
Tests now inspect ``LintReport.runtime_warnings`` via
``--format=json``. The single source of truth for the JSON parsing
lives here so test files do not drift apart on the helper's
behaviour (empty-list vs. KeyError on the missing-key path, etc.).

D5 U5 added the cross-formatter render contract. The
``LINT_RUNTIME_WARNING_CATEGORIES`` tuple + ``warning_for_category``
factory live here so the formatter test (``tests/test_builtin_lint_runtime_warnings.py``)
and the CLI human-stderr test (``test_human_stderr_render.py``)
share one definition — an 8th category lands by editing this file
alone (D6b U5 added the 5th, ``severities_unloaded_rule``; D6d U1
added the 6th, ``custom_annotation_extension_unresolved``; D6d U2
added the 7th, ``extension_unresolved``).
"""

from __future__ import annotations

import json
from typing import Any

from protokit.schema.lint.model import LintRuntimeWarning

#: The seven ``LintRuntimeWarning`` categories that exist as of D6d
#: U2. Keep this tuple in sync with ``LintRuntimeWarning.category``'s
#: ``Literal[...]`` in ``protokit.schema.lint.model``. Adding an 8th
#: category is a deliberate act that requires updating both the
#: model Literal AND this tuple — the cross-formatter parametrized
#: matrix tests will then fail until every formatter render site is
#: covered.
LINT_RUNTIME_WARNING_CATEGORIES: tuple[str, ...] = (
    "rule_exception",
    "unloaded_rule",
    "severities_unloaded_rule",
    "min_severity_relaxed",
    "all_files_excluded",
    "custom_annotation_extension_unresolved",
    "extension_unresolved",
)


def runtime_warnings_from_json(stdout: str) -> list[dict[str, Any]]:
    """Parse ``--format=json`` stdout and return its runtime_warnings list.

    Returns the parsed ``runtime_warnings`` array (which may be
    empty). Raises ``json.JSONDecodeError`` if ``stdout`` is not
    valid JSON, or ``KeyError`` if the top-level object lacks a
    ``runtime_warnings`` key — both signal a real wire-format
    regression and should fail the test loudly rather than
    masquerading as "no warnings".
    """
    return json.loads(stdout)["runtime_warnings"]


def first_warning_by_category(
    stdout: str, category: str,
) -> dict[str, Any] | None:
    """Return the first runtime_warning with ``category``, or ``None``."""
    for w in runtime_warnings_from_json(stdout):
        if w["category"] == category:
            return w
    return None


def warning_for_category(
    category: str, *, index: int = 0,
) -> LintRuntimeWarning:
    """Construct a representative ``LintRuntimeWarning`` per category.

    Mirrors the engine/CLI emission contract:

    - Rule-scoped (``rule_exception`` / ``unloaded_rule`` /
      ``severities_unloaded_rule``): ``rule_id`` is a non-``None``
      string + ``descriptor_path`` is populated for ``rule_exception``.
    - Non-rule-scoped CLI-emitted (``min_severity_relaxed`` /
      ``all_files_excluded``): ``rule_id`` is ``None``.

    The optional ``index`` parameter makes each invocation produce
    a distinguishable instance — useful for threshold-boundary tests
    that need N warnings of the same category with unique payloads.
    Default ``index=0`` preserves single-instance semantics for the
    formatter parametrized matrix tests.
    """
    if category == "rule_exception":
        return LintRuntimeWarning(
            category="rule_exception",
            rule_id="naming/snake-case-fields",
            message=f"ValueError: synthetic rule failure #{index}",
            exception_type="ValueError",
            descriptor_path=f"acme.User.bad_field_{index}",
        )
    if category == "unloaded_rule":
        return LintRuntimeWarning(
            category="unloaded_rule",
            rule_id=f"missing/never-registered-{index}",
            message=f"rule pack 'missing.pack.{index}' could not be loaded",
        )
    if category == "severities_unloaded_rule":
        return LintRuntimeWarning(
            category="severities_unloaded_rule",
            rule_id=f"missing/severities-key-{index}",
            message=(
                f"rule 'missing/severities-key-{index}' is named in "
                f"[tool.protokit.lint.severities] but is not in the "
                f"composed profile — the severity override has no "
                f"effect"
            ),
        )
    if category == "min_severity_relaxed":
        return LintRuntimeWarning(
            category="min_severity_relaxed",
            rule_id=None,
            message=(
                f"--min-severity=info relaxes profile floor from "
                f"warning to info ({index})"
            ),
        )
    if category == "all_files_excluded":
        return LintRuntimeWarning(
            category="all_files_excluded",
            rule_id=None,
            message=(
                f"all {index + 1} input file(s) excluded by --exclude "
                f"patterns: **/*"
            ),
        )
    if category == "custom_annotation_extension_unresolved":
        return LintRuntimeWarning(
            category="custom_annotation_extension_unresolved",
            rule_id=f"custom/missing-extension-{index}",
            message=(
                f"synthetic rule 'custom/missing-extension-{index}' "
                f"skipped on file 'acme/example_{index}.proto': "
                f"extension 'notinpool.foo' is not registered in the "
                f"compile pool"
            ),
        )
    if category == "extension_unresolved":
        return LintRuntimeWarning(
            category="extension_unresolved",
            rule_id=f"options/builtin-rule-{index}",
            message=(
                f"rule 'options/builtin-rule-{index}' skipped on file "
                f"'acme/example_{index}.proto': extension "
                f"'google.api.field_behavior' is not registered in "
                f"the compile pool"
            ),
        )
    raise AssertionError(f"unrecognized category: {category}")
