"""protokit.forensics — wire-format forensics over schema-less proto (Phase 2).

Given a single serialized proto message that carries no co-located schema,
identify which candidate ``.proto`` schema version most plausibly produced it
(``match``), or reconcile it field by field against one chosen candidate
(``drift``) — one message at a time. Read-only: it ranks hypotheses with
evidence and never asserts that a candidate *is* the schema.

Public surface (this list is ``__all__``; keep the two in step):

- :func:`match` — rank candidate schemas against one message; returns a
  :class:`MatchReport`.
- :class:`Candidate` / :class:`CandidateFit` / :class:`MatchReport` — the input
  and result types. ``Verdict`` is the ``clean_winner`` / ``multiple_clean_matches``
  / ``no_clean_match`` literal, and ``ParseTier`` the per-candidate parse outcome.
- :func:`drift` — reconcile one message against one chosen candidate schema;
  returns a :class:`DriftReport` of :class:`FieldDivergence` entries (an
  undeclared tag, a wire-type mismatch, a reserved tag in use, or a proto2
  ``required`` field absent).
- :class:`ForensicsError` / :class:`MessageTooLargeError` / :class:`CandidateSpecError`
  / :class:`WalkError` — the typed exception family (all subclass
  ``protokit.storage.StorageError``).
"""

from __future__ import annotations

from protokit.forensics._drift import DriftReport, FieldDivergence, drift
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
from protokit.forensics._wire import WalkError

__all__ = [
    "Candidate",
    "CandidateFit",
    "CandidateSpecError",
    "DriftReport",
    "FieldDivergence",
    "ForensicsError",
    "MatchReport",
    "MessageTooLargeError",
    "ParseTier",
    "Verdict",
    "WalkError",
    "drift",
    "match",
]
