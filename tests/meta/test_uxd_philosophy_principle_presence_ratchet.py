"""Presence ratchet for the UX philosophy claims in source.

Two UX philosophy claims are pinned, backed by three substring
assertions total (one for the UX-philosophy principle + two for
POSITIONING_STATEMENT after the dual-pin split):

1. **The hard-inverted UX philosophy principle** —
   protokit-UX overrides buf-parity when they conflict; proto2-
   specific strict rules ship in opt-in ``proto2-strict`` profile.
   Pinned by ONE substring.

2. **POSITIONING_STATEMENT** (resolves the parity-vs-defaults
   tension surfaced by the document-review pass) — names the bet
   explicitly: protokit claims parity at COVERAGE (26 of 26 rules
   implemented), not at DEFAULTS (severity placements diverge by
   design — see the ``file/syntax-specified`` WARNING demotion).
   Pinned by TWO substrings (one per content line of the 3-line
   docstring statement): the load-bearing "not buf's defaults"
   clause + the "see proto2-strict" cross-reference pointer. The
   two-pin strategy closes a gap where a single pin against the
   truncated docstring form would have allowed silent drift if the
   canonical README/CHANGELOG form was shortened to match the
   docstring.

Per the 5th discipline rule of the presence-ratchet pattern for
prose substrings, each substring fits on a single source line —
no Sphinx ``#:`` continuation interrupts the assertion. The test
reads source via ``inspect.getsource`` (Pattern B) since the
BUILTIN_PACKS module docstring uses ``#:`` continuation prefixes
rather than a Python ``__doc__`` attribute.

The ratchet protects against silent reversion of the inverted
philosophy stance. Without it, a future stale-text edit could
remove the UX-philosophy line or the POSITIONING_STATEMENT and
the test suite would not notice.
"""

from __future__ import annotations

import inspect


def test_ux_philosophy_principle_pinned_in_builtin_packs_docstring() -> None:
    """UX-philosophy substring present in the BUILTIN_PACKS docstring."""
    from protokit.schema.lint import rules

    source = inspect.getsource(rules)
    substring = (
        "UX philosophy: protokit-UX overrides buf-parity; "
        "proto2-specific strict rules ship in proto2-strict."
    )
    assert substring in source, (
        "UX philosophy principle substring missing from "
        "src/protokit/schema/lint/rules/__init__.py. Either "
        "restore the substring OR update this test after "
        "confirming the inverted UX philosophy is still "
        "documented somewhere durable."
    )


def test_positioning_statement_pinned_in_builtin_packs_docstring() -> None:
    """POSITIONING_STATEMENT pinned in the BUILTIN_PACKS docstring.

    Resolves the parity-vs-defaults headline tension by naming the
    bet explicitly. Should be byte-identical to the README Schema
    Linting section header.
    """
    from protokit.schema.lint import rules

    source = inspect.getsource(rules)
    # The prior substring carried a truncated form
    # ("Python-protobuf-dev ergonomics.") that diverged from the
    # README + CHANGELOG canonical form. A future editor shortening
    # README to match the docstring would have passed CI while
    # silently dropping the load-bearing "not buf's defaults" clause
    # (the rationale for the inverted UX philosophy). Pin two
    # substrings now to lock the load-bearing phrase ("not buf's
    # defaults") AND the proto2-strict pointer ("see proto2-strict")
    # — each fits on a single source line per the presence-ratchet
    # pattern for prose substrings (rule 5).
    substrings = (
        "Python-protobuf-developer ergonomics, not buf's defaults",
        "see proto2-strict for opt-in proto2 strictness",
    )
    for substring in substrings:
        assert substring in source, (
            f"POSITIONING_STATEMENT substring {substring!r} "
            "missing from src/protokit/schema/lint/rules/__init__.py. "
            "Either restore the substring OR update this test after "
            "confirming the parity-at-COVERAGE vs ergonomics-at-"
            "DEFAULTS framing is still documented."
        )
