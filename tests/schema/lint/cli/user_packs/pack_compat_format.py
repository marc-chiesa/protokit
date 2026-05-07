"""Synthetic user pack with compat-style RULES wire format.

Compat expects ``RULES = ((rule_id, fn), ...)``; lint expects
``RULES = (decorated_fn, ...)``. This pack uses compat's tuple
form, which raises ``TypeError`` from ``LintEngine.load_rule_pack``
because the entries lack a ``_lint_spec`` attribute. Routes to
``error[lint-rule-pack-load]:`` with ``kind=shape`` token.
"""

from __future__ import annotations


def _undecorated_rule(ctx: object) -> None:
    """A plain function NOT @lint_rule-decorated (no _lint_spec)."""


# Compat wire format — INTENTIONALLY WRONG for lint.
RULES = (
    ("acme/some-rule", _undecorated_rule),
)
