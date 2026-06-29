"""U4 — ranking + clean-winner / multiple-clean / no-clean-match verdicts."""

from __future__ import annotations

from protokit.forensics._match import match
from tests.forensics.fixtures import candidate, fdp, msg_bytes


def test_clean_winner_ranks_exact_producer_first() -> None:
    """The fully-modeling candidate ranks first with a clean-winner verdict."""
    full = fdp({"x": 1, "y": 2})
    old = fdp({"x": 1})
    data = msg_bytes(full, {"x": 5, "y": 7})

    report = match(data, [candidate("old", old), candidate("full", full)])

    assert report.ranked[0].label == "full"
    assert report.verdict == "clean_winner"


def test_no_clean_match_when_every_candidate_leaves_residual() -> None:
    """When no candidate fully models the message, the verdict is no-clean-match."""
    producer = fdp({"x": 1, "y": 2, "z": 3})
    only_x = fdp({"x": 1})
    only_y = fdp({"y": 2})
    data = msg_bytes(producer, {"x": 5, "y": 7, "z": 9})

    report = match(data, [candidate("only_x", only_x), candidate("only_y", only_y)])

    assert report.verdict == "no_clean_match"
    assert all(f.unmodeled_bytes for f in report.ranked)


def test_superset_ranks_below_exact_producer() -> None:
    """Two clean candidates: declared-field coverage ranks the exact one first (AE5)."""
    exact = fdp({"x": 1})
    superset = fdp({"x": 1, "y": 2})
    data = msg_bytes(exact, {"x": 5})

    report = match(data, [candidate("super", superset), candidate("exact", exact)])

    assert report.ranked[0].label == "exact"
    assert report.verdict == "clean_winner"


def test_multiple_clean_matches_when_indistinguishable() -> None:
    """Two schemas identical on the exercised fields are reported as ambiguous (AE5)."""
    a = fdp({"x": 1})
    b = fdp({"x": 1})
    data = msg_bytes(a, {"x": 5})

    report = match(data, [candidate("a", a), candidate("b", b)])

    assert report.verdict == "multiple_clean_matches"
    assert report.ambiguous_top is True


def test_ranking_is_deterministic() -> None:
    """Identical inputs produce an identical ranking and verdict."""
    full = fdp({"x": 1, "y": 2})
    old = fdp({"x": 1})
    data = msg_bytes(full, {"x": 5, "y": 7})
    cands = [candidate("old", old), candidate("full", full)]

    first = match(data, cands)
    second = match(data, cands)

    assert [f.label for f in first.ranked] == [f.label for f in second.ranked]
    assert first.verdict == second.verdict


def test_max_residual_bytes_promotes_near_clean_to_clean() -> None:
    """A small residual within --max-residual-bytes counts as a clean match."""
    rich = fdp({"x": 1, "y": 2})
    poor = fdp({"x": 1})
    data = msg_bytes(rich, {"x": 5, "y": 7})

    strict = match(data, [candidate("poor", poor)])
    assert strict.verdict == "no_clean_match"

    residual = strict.ranked[0].unmodeled_bytes
    assert residual is not None
    tolerant = match(data, [candidate("poor", poor)], max_residual_bytes=residual)
    assert tolerant.verdict in {"clean_winner", "multiple_clean_matches"}
