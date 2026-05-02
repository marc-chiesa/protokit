"""Lint subpackage for protokit schema (D1 foundation).

Houses the lint-side type system, engine, rule registry, and CLI
formatters. This module is intentionally a lazy-import boundary:
``protokit.schema`` does not import ``protokit.schema.lint`` at top
level, so callers that only use the compatibility checker do not
pay lint-side import cost.
"""

from __future__ import annotations
