"""Synthetic user pack — module-body raises non-ImportError exception.

Tests the `except Exception` broad catch in `_load_user_rule_pack`
that follows the `except SystemExit` guard. Any module body that
fails with a non-BaseException error (NameError, ZeroDivisionError,
RuntimeError, etc.) routes to `error[lint-rule-pack-load]:` with
`kind=import` token.
"""

from __future__ import annotations

# Intentional ZeroDivisionError at module body load time.
1 / 0  # noqa: B018 -- intentional fixture
