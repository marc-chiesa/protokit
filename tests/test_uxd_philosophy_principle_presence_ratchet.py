"""Presence ratchet for the D6e UX philosophy claims in source.

Two UX philosophy claims are pinned, backed by three substring
assertions total (one for KD-1 + two for POSITIONING_STATEMENT
after the U4 ce:review M2 dual-pin split):

1. **D6e KD-1 (the hard-inverted UX philosophy principle)** —
   protokit-UX overrides buf-parity when they conflict; proto2-
   specific strict rules ship in opt-in ``proto2-strict`` profile.
   Pinned by ONE substring.

2. **D6e POSITIONING_STATEMENT** (resolves Product-lens F1 from
   the document-review pass) — names the bet explicitly:
   protokit claims parity at COVERAGE (26 of 26 rules implemented),
   not at DEFAULTS (severity placements diverge by design — see
   ``file/syntax-specified`` R4b WARNING demotion).
   Pinned by TWO substrings (one per content line of the 3-line
   docstring statement): the load-bearing "not buf's defaults"
   clause + the "see proto2-strict" cross-reference pointer. The
   two-pin strategy closes a U4 ce:review M2 gap where a single
   pin against the truncated docstring form would have allowed
   silent drift if the canonical README/CHANGELOG form was
   shortened to match the docstring.

Per the 5th discipline rule of
[[presence-ratchet-test-pattern-for-prose-substrings-2026-05-14]]
each substring fits on a single source line — no Sphinx ``#:``
continuation interrupts the assertion. The test reads source via
``inspect.getsource`` (Pattern B) since the BUILTIN_PACKS module
docstring uses ``#:`` continuation prefixes rather than a Python
``__doc__`` attribute.

The ratchet protects against silent reversion of the inverted
philosophy stance. Without it, a future stale-text edit could
remove KD-1 or the POSITIONING_STATEMENT and the test suite
would not notice.
"""

from __future__ import annotations

import inspect


def test_kd_1_philosophy_principle_pinned_in_builtin_packs_docstring() -> None:
    """D6e KD-1 substring present in the BUILTIN_PACKS docstring."""
    from protokit.schema.lint import rules

    source = inspect.getsource(rules)
    substring = (
        "D6e KD-1: protokit-UX overrides buf-parity; "
        "proto2-specific strict rules ship in proto2-strict."
    )
    assert substring in source, (
        "D6e KD-1 philosophy principle substring missing from "
        "src/protokit/schema/lint/rules/__init__.py. Either "
        "restore the substring OR update this test after "
        "confirming the inverted UX philosophy is still "
        "documented somewhere durable. See "
        "docs/plans/2026-05-22-001-feat-d6e-buf-basic-closure-"
        "and-philosophy-revision-plan.md PD-1 for the bound text."
    )


def test_positioning_statement_pinned_in_builtin_packs_docstring() -> None:
    """D6e POSITIONING_STATEMENT pinned in the BUILTIN_PACKS docstring.

    Resolves Product-lens F1 (KD-1-vs-26/26 headline tension) by
    naming the bet explicitly. Should be byte-identical to the
    README Schema Linting section header (via the U4 README refresh).
    """
    from protokit.schema.lint import rules

    source = inspect.getsource(rules)
    # U4 ce:review M2 (2026-05-23): the prior substring carried a
    # truncated form ("Python-protobuf-dev ergonomics.") that
    # diverged from the README + CHANGELOG canonical form. A future
    # editor shortening README to match the docstring would have
    # passed CI while silently dropping the load-bearing "not buf's
    # defaults" clause (the rationale for D6e KD-1). Pin two
    # substrings now to lock the load-bearing phrase ("not buf's
    # defaults") AND the proto2-strict pointer ("see proto2-strict")
    # — each fits on a single source line per
    # [[presence-ratchet-test-pattern-for-prose-substrings]] rule 5.
    substrings = (
        "Python-protobuf-developer ergonomics, not buf's defaults",
        "see proto2-strict for opt-in proto2 strictness",
    )
    for substring in substrings:
        assert substring in source, (
            f"D6e POSITIONING_STATEMENT substring {substring!r} "
            "missing from src/protokit/schema/lint/rules/__init__.py. "
            "Either restore the substring OR update this test after "
            "confirming the parity-at-COVERAGE vs ergonomics-at-"
            "DEFAULTS framing is still documented. See "
            "docs/plans/2026-05-22-001-feat-d6e-buf-basic-closure-"
            "and-philosophy-revision-plan.md Product-lens F1 + the "
            "canonical headline phrasing block in U4."
        )
