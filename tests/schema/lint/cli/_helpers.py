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
share one definition — a 5th category lands by editing this file
alone.
"""

from __future__ import annotations

import json
from typing import Any

from protokit.schema.lint.model import LintRuntimeWarning

#: The four ``LintRuntimeWarning`` categories that exist as of D5
#: U5. Keep this tuple in sync with ``LintRuntimeWarning.category``'s
#: ``Literal[...]`` in ``protokit.schema.lint.model``. Adding a 5th
#: category is a deliberate D6+ act that requires updating both the
#: model Literal AND this tuple — the cross-formatter parametrized
#: matrix tests will then fail until every formatter render site is
#: covered.
LINT_RUNTIME_WARNING_CATEGORIES: tuple[str, ...] = (
    "rule_exception",
    "unloaded_rule",
    "min_severity_relaxed",
    "all_files_excluded",
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

    - Engine-emitted (``rule_exception`` / ``unloaded_rule``):
      ``rule_id`` is a non-``None`` string + ``descriptor_path`` is
      populated for ``rule_exception``.
    - CLI-emitted (``min_severity_relaxed`` / ``all_files_excluded``):
      ``rule_id`` is ``None``.

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
    raise AssertionError(f"unrecognized category: {category}")
