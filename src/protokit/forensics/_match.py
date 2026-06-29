"""Schema-less single-message match: rank candidate schemas by fit.

Given one serialized proto message that carries no co-located schema and a set
of candidate schema versions, rank which version most plausibly produced it. The
fit signal is three-part and printable (no magic numbers):

  1. parse tier — clean (no unmodeled bytes) > unmodeled bytes present > fault
     (un-parseable, or proto2-uninitialized so bytes cannot be measured)
  2. modeled-byte fraction — ``1 - unmodeled_bytes / total_bytes`` (under-coverage)
  3. declared-field coverage — the share of the candidate's declared top-level
     fields the message exercises (over-coverage: an exact producer outranks a
     superset that also models every byte)

Ties fall to deterministic input order. Output is ranked hypotheses with a
verdict (``clean_winner`` / ``multiple_clean_matches`` / ``no_clean_match``) —
never an assertion that a candidate *is* the schema.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Literal

from google.protobuf.descriptor import Descriptor
from google.protobuf.message import DecodeError, Message

from protokit.storage._fidelity_probe import unmodeled_byte_delta
from protokit.storage.schema_source import ResolvedSchema, SchemaSource

Verdict = Literal["clean_winner", "multiple_clean_matches", "no_clean_match"]
ParseOutcome = Literal["clean", "unmodeled", "incomplete", "decode_error"]

#: Default closeness epsilon (a fraction of total bytes) below which two
#: candidates' modeled-byte fractions are "near-identical" — the Phase-B
#: wire-walker tie-break engages on the flagged pair (R12 / AE3).
DEFAULT_TIE_MARGIN = 0.005


class ParseTier(Enum):
    """Coarse parse outcome, ordered best-first by ``value`` (lower ranks higher)."""

    CLEAN = 0  # parsed, delta == 0 (the residual tolerance is applied in match())
    UNMODELED = 1  # parsed, but carried bytes the descriptor does not model
    FAULT = 2  # un-parseable (DecodeError) or proto2-uninitialized (cannot measure)


@dataclass(frozen=True)
class Candidate:
    """One candidate schema version: a display label and a resolvable source."""

    label: str
    source: SchemaSource


@dataclass(frozen=True)
class CandidateFit:
    """The fit of one candidate schema to the message — all evidence printable."""

    label: str
    tier: ParseTier
    parse_outcome: ParseOutcome
    total_bytes: int
    unmodeled_bytes: int | None
    modeled_fraction: float | None
    declared_field_coverage: float | None
    present_field_count: int
    declared_field_count: int
    detail: str | None = None


@dataclass(frozen=True)
class MatchReport:
    """A ranked match result and its honest verdict."""

    ranked: tuple[CandidateFit, ...]
    verdict: Verdict
    ambiguous_top: bool  # top-2 modeled fractions within the tie-margin (Phase-B hook)


def _present_declared_field_count(message: Message) -> int:
    """Count the message's set, non-extension top-level fields.

    ``ListFields`` returns ``(FieldDescriptor, value)`` for every field that is
    present (set / non-default). Extensions are excluded so the count is
    comparable to ``len(descriptor.fields)`` (which never includes extensions),
    keeping declared-field coverage in ``[0.0, 1.0]``.
    """
    return sum(1 for fd, _ in message.ListFields() if not fd.is_extension)


def fit_candidate(message_bytes: bytes, candidate: Candidate) -> CandidateFit:
    """Parse ``message_bytes`` under one candidate and measure its fit.

    Resolution failures (a ``.proto`` that will not compile, an unknown type)
    propagate — a broken candidate schema is a user error, not a per-candidate
    fault. A ``DecodeError`` (the *message* does not parse under this schema) is
    caught and recorded as a fault so one bad fit never aborts the whole ranking.
    """
    total = len(message_bytes)
    resolved: ResolvedSchema = candidate.source.resolve()
    descriptor: Descriptor = resolved.message_class.DESCRIPTOR
    declared_count: int = len(descriptor.fields)

    message = resolved.message_class()
    try:
        message.MergeFromString(message_bytes)
    except DecodeError as exc:
        return CandidateFit(
            label=candidate.label,
            tier=ParseTier.FAULT,
            parse_outcome="decode_error",
            total_bytes=total,
            unmodeled_bytes=None,
            modeled_fraction=None,
            declared_field_coverage=None,
            present_field_count=0,
            declared_field_count=declared_count,
            detail=str(exc) or "message does not parse under this schema",
        )

    present_count = _present_declared_field_count(message)
    coverage = present_count / declared_count if declared_count else 1.0
    delta = unmodeled_byte_delta(message)

    if delta is None:
        # Parsed, but proto2-uninitialized (a required field is absent), so the
        # modeled-byte fraction cannot be measured. Sorts into the fault tier
        # (KTD4) while still carrying coverage for an in-tier comparison.
        return CandidateFit(
            label=candidate.label,
            tier=ParseTier.FAULT,
            parse_outcome="incomplete",
            total_bytes=total,
            unmodeled_bytes=None,
            modeled_fraction=None,
            declared_field_coverage=coverage,
            present_field_count=present_count,
            declared_field_count=declared_count,
            detail="message is missing a required field (cannot measure modeled bytes)",
        )

    fraction = 1.0 - (delta / total) if total else 1.0
    tier = ParseTier.CLEAN if delta == 0 else ParseTier.UNMODELED
    outcome: ParseOutcome = "clean" if delta == 0 else "unmodeled"
    return CandidateFit(
        label=candidate.label,
        tier=tier,
        parse_outcome=outcome,
        total_bytes=total,
        unmodeled_bytes=delta,
        modeled_fraction=fraction,
        declared_field_coverage=coverage,
        present_field_count=present_count,
        declared_field_count=declared_count,
        detail=None,
    )


def _coerce_scalars(fit: CandidateFit) -> tuple[float, float]:
    """The (fraction, coverage) pair with ``None`` coerced to the worst sentinel."""
    fraction = fit.modeled_fraction if fit.modeled_fraction is not None else -1.0
    coverage = (
        fit.declared_field_coverage if fit.declared_field_coverage is not None else -1.0
    )
    return fraction, coverage


def _sort_key(fit: CandidateFit, index: int) -> tuple[int, float, float, int]:
    """Rank key, lowest first: tier, then higher fraction, higher coverage, order."""
    fraction, coverage = _coerce_scalars(fit)
    return (fit.tier.value, -fraction, -coverage, index)


def _signature(fit: CandidateFit) -> tuple[int, float, float]:
    """The discriminating triple used to decide whether two fits are equivalent."""
    fraction, coverage = _coerce_scalars(fit)
    return (fit.tier.value, fraction, coverage)


def match(
    message_bytes: bytes,
    candidates: Sequence[Candidate],
    *,
    max_residual_bytes: int = 0,
    tie_margin: float = DEFAULT_TIE_MARGIN,
) -> MatchReport:
    """Rank ``candidates`` by how plausibly each produced ``message_bytes``.

    Args:
        message_bytes: The single serialized message under analysis.
        candidates: Candidate schema versions, each a label + resolvable source.
        max_residual_bytes: A candidate counts as a clean match when it parses
            and leaves at most this many unmodeled bytes (default ``0``).
        tie_margin: Top-2 modeled fractions within this epsilon flag an ambiguous
            pair for the Phase-B wire-walker tie-break.

    Returns:
        A :class:`MatchReport`: candidates ranked best-first and an honest
        verdict (``clean_winner`` / ``multiple_clean_matches`` / ``no_clean_match``).
    """
    fits = [fit_candidate(message_bytes, c) for c in candidates]
    order = sorted(range(len(fits)), key=lambda i: _sort_key(fits[i], i))
    ranked = tuple(fits[i] for i in order)

    clean = [
        f
        for f in ranked
        if f.tier is not ParseTier.FAULT
        and f.unmodeled_bytes is not None
        and f.unmodeled_bytes <= max_residual_bytes
    ]
    if not clean:
        verdict: Verdict = "no_clean_match"
    else:
        top_sig = _signature(clean[0])
        tied = sum(1 for f in clean if _signature(f) == top_sig)
        verdict = "multiple_clean_matches" if tied >= 2 else "clean_winner"

    ambiguous_top = False
    if len(ranked) >= 2:
        f0, f1 = ranked[0].modeled_fraction, ranked[1].modeled_fraction
        if f0 is not None and f1 is not None and abs(f0 - f1) <= tie_margin:
            ambiguous_top = True

    return MatchReport(ranked=ranked, verdict=verdict, ambiguous_top=ambiguous_top)
