"""D6d U1 — KD-8 invariant: ``BUILTIN_PACKS`` must NEVER ship a ``custom/*`` rule_id.

The ``custom/`` namespace is reserved for user-declared synthetic
rules materialized from
``[[tool.protokit.lint.custom_annotation_rules]]``. Built-in rule
packs MUST NOT register any rule whose ``rule_id`` matches the
regex ``^custom/`` — accidentally shipping one would collide with
user synthetic rules' namespace and break the public R10 contract.

The regex check (vs ``startswith("custom/")``) explicitly defends
against accidental relaxation in future BUILTIN_PACKS additions
(``customer/`` or ``custom-*/`` rule_ids would be REJECTED by the
plain startswith check, but they share the prefix substring; the
anchored regex prevents that ambiguity by terminating on the
trailing slash).
"""

from __future__ import annotations

import re

from protokit.schema.lint.decorator import get_lint_spec
from protokit.schema.lint.rules import BUILTIN_PACKS

#: Anchored regex per D6d KD-8 (ADV-6 refinement). Matches exactly
#: rule_ids beginning with ``"custom/"``; rejects ``"customer/"``,
#: ``"customs/"``, ``"custom-foo/"``.
_CUSTOM_NAMESPACE_REGEX: re.Pattern[str] = re.compile(r"^custom/")


def test_no_builtin_rule_uses_custom_prefix() -> None:
    """Every rule across every ``BUILTIN_PACKS`` module's ``RULES``
    tuple must have a ``rule_id`` outside the ``custom/`` namespace.
    """
    offenders: list[str] = []
    for pack in BUILTIN_PACKS:
        for fn in getattr(pack, "RULES", ()):
            spec = get_lint_spec(fn)
            if _CUSTOM_NAMESPACE_REGEX.match(spec.rule_id):
                offenders.append(
                    f"{pack.__name__}.{fn.__name__}: rule_id={spec.rule_id!r}",
                )
    assert not offenders, (
        f"BUILTIN_PACKS contains rule(s) in the reserved 'custom/' "
        f"namespace (KD-8 invariant violation): {offenders}. "
        f"Move the rule(s) to a non-custom/ prefix or document the "
        f"namespace policy change in D6d's KD-8 record."
    )
