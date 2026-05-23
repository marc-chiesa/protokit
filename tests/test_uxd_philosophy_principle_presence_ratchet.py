"""Presence ratchet for the D6e UX philosophy claims in source.

Two substrings are pinned via this ratchet:

1. **D6e KD-1 (the hard-inverted UX philosophy principle)** —
   protokit-UX overrides buf-parity when they conflict; proto2-
   specific strict rules ship in opt-in ``proto2-strict`` profile.

2. **D6e POSITIONING_STATEMENT** (resolves Product-lens F1 from
   the document-review pass) — names the bet explicitly:
   protokit claims parity at COVERAGE (26 of 26 rules implemented),
   not at DEFAULTS (severity placements diverge by design — see
   ``file/syntax-specified`` R4b WARNING demotion).

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
    # Rephrased ce:review P1 #2 (2026-05-22): the prior substring
    # claimed "26 BASIC rules" at U1+U2 when only 25 had shipped
    # (PACKAGE_NO_IMPORT_CYCLE lands at U3). The current phrasing
    # is accurate at every commit on the D6e branch (U1+U2 with
    # 25 rules, U3 with 26 rules, U4 with the 0.6.0 release) AND
    # fits on a single source line per the
    # [[presence-ratchet-test-pattern-for-prose-substrings]] rule 5.
    substring = (
        "protokit targets buf BASIC coverage; defaults reflect "
        "Python-protobuf-dev ergonomics."
    )
    assert substring in source, (
        "D6e POSITIONING_STATEMENT substring missing from "
        "src/protokit/schema/lint/rules/__init__.py. Either "
        "restore the substring OR update this test after "
        "confirming the parity-at-COVERAGE vs ergonomics-at-"
        "DEFAULTS framing is still documented. See "
        "docs/plans/2026-05-22-001-feat-d6e-buf-basic-closure-"
        "and-philosophy-revision-plan.md Product-lens F1 + the "
        "canonical headline phrasing block in U4."
    )
