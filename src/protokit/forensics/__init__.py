"""protokit.forensics — wire-format forensics over schema-less proto (Phase 2).

Given a single serialized proto message that carries no co-located schema,
identify which candidate ``.proto`` schema version most plausibly produced it
(``match``), one message at a time. Read-only: it ranks hypotheses with evidence
and never asserts that a candidate *is* the schema.

Public surface:

- :func:`match` — rank candidate schemas against one message; returns a
  :class:`MatchReport`.
- :class:`Candidate` / :class:`CandidateFit` / :class:`MatchReport` — the input
  and result types. ``Verdict`` is the ``clean_winner`` / ``multiple_clean_matches``
  / ``no_clean_match`` literal.
- :class:`ForensicsError` / :class:`MessageTooLargeError` / :class:`CandidateSpecError`
  — the typed exception family (all subclass ``protokit.storage.StorageError``).
"""

from __future__ import annotations

from protokit.forensics._errors import (
    CandidateSpecError,
    ForensicsError,
    MessageTooLargeError,
)
from protokit.forensics._match import (
    Candidate,
    CandidateFit,
    MatchReport,
    ParseTier,
    Verdict,
    match,
)

__all__ = [
    "Candidate",
    "CandidateFit",
    "CandidateSpecError",
    "ForensicsError",
    "MatchReport",
    "MessageTooLargeError",
    "ParseTier",
    "Verdict",
    "match",
]
