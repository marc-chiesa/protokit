"""Cross-file test helpers for ``protokit lint`` CLI tests.

D5 U4 removed the legacy ``warning[lint-runtime]:`` stderr loop.
Tests now inspect ``LintReport.runtime_warnings`` via
``--format=json``. The single source of truth for the JSON parsing
lives here so test files do not drift apart on the helper's
behaviour (empty-list vs. KeyError on the missing-key path, etc.).
"""

from __future__ import annotations

import json
from typing import Any


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
