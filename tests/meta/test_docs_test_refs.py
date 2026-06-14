"""Tests for the reference-drift reporter (plan U1).

Covers parse (rename/remove vs ignored statuses), doc-reference confidence
(full path = high, basename-only = low), basename-collision disambiguation,
and the empty / historical-mention cases. The pure functions take their
inputs directly, so no git repo or subprocess is needed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_docs_test_refs import (
    Move,
    build_report,
    find_doc_refs,
    parse_moves,
    render_markdown,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


# --- parse_moves ------------------------------------------------------------


def test_parse_moves_rename_and_remove_of_test_files() -> None:
    diff = (
        "R100\ttests/test_foo.py\ttests/meta/test_foo.py\n"
        "D\ttests/test_gone.py\n"
    )
    assert parse_moves(diff) == [
        Move(old_path="tests/test_foo.py", new_path="tests/meta/test_foo.py"),
        Move(old_path="tests/test_gone.py", new_path=None),
    ]


def test_parse_moves_ignores_non_test_and_non_move_statuses() -> None:
    diff = (
        "M\ttests/test_kept.py\n"  # modified, not moved
        "A\ttests/test_new.py\n"  # added
        "R100\tsrc/protokit/foo.py\tsrc/protokit/bar.py\n"  # not a test path
        "D\tsrc/protokit/gone.py\n"  # not a test path
        "R100\ttests/test_real.py\ttests/meta/test_real.py\n"  # the only hit
    )
    assert parse_moves(diff) == [
        Move(old_path="tests/test_real.py", new_path="tests/meta/test_real.py"),
    ]


def test_parse_moves_low_similarity_rename_surfaces_as_removal() -> None:
    # A heavily-rewritten-then-moved file git scores below threshold appears
    # as delete-of-old (+ add-of-new); the reporter surfaces the removal.
    diff = "D\ttests/test_rewritten.py\nA\ttests/meta/test_rewritten.py\n"
    assert parse_moves(diff) == [
        Move(old_path="tests/test_rewritten.py", new_path=None),
    ]


# --- find_doc_refs ----------------------------------------------------------


def _write(docs: Path, name: str, body: str) -> None:
    (docs / name).write_text(body, encoding="utf-8")


def test_find_doc_refs_full_path_is_high_confidence(tmp_path: Path) -> None:
    docs = tmp_path / "docs" / "solutions"
    docs.mkdir(parents=True)
    _write(docs, "a.md", "see the test at `tests/test_foo.py` for details\n")
    hits = find_doc_refs("tests/test_foo.py", docs)
    assert len(hits) == 1
    assert hits[0].confidence == "high"
    assert hits[0].line_no == 1


def test_find_doc_refs_basename_only_is_low_confidence(tmp_path: Path) -> None:
    docs = tmp_path / "docs" / "solutions"
    docs.mkdir(parents=True)
    # Names the basename but a DIFFERENT directory than the moved path.
    _write(docs, "b.md", "the helper lives in tests/other/test_foo.py\n")
    hits = find_doc_refs("tests/test_foo.py", docs)
    assert len(hits) == 1
    assert hits[0].confidence == "low"


def test_find_doc_refs_no_reference_yields_nothing(tmp_path: Path) -> None:
    docs = tmp_path / "docs" / "solutions"
    docs.mkdir(parents=True)
    _write(docs, "c.md", "nothing relevant here\n")
    assert find_doc_refs("tests/test_foo.py", docs) == []


def test_find_doc_refs_full_path_disambiguates_basename_collision(
    tmp_path: Path,
) -> None:
    # Covers AE1 + KTD2: the doc naming the full old path is high-confidence;
    # a doc naming only a same-named file in another dir is low-confidence.
    docs = tmp_path / "docs" / "solutions"
    docs.mkdir(parents=True)
    _write(docs, "moved.md", "pin at `tests/core/test_cli_utils.py`\n")
    _write(docs, "other.md", "unrelated `tests/schema/lint/cli/test_cli_utils.py`\n")
    hits = find_doc_refs("tests/core/test_cli_utils.py", docs)
    by_doc = {h.doc.rsplit("/", 1)[-1]: h.confidence for h in hits}
    assert by_doc["moved.md"] == "high"
    assert by_doc["other.md"] == "low"


def test_find_doc_refs_surfaces_historical_mention_without_judging(
    tmp_path: Path,
) -> None:
    # A "was at X" historical line IS surfaced — triage is the human's job.
    docs = tmp_path / "docs" / "solutions"
    docs.mkdir(parents=True)
    _write(docs, "hist.md", '"tests/meta/test_x.py", # was tests/test_x.py\n')
    hits = find_doc_refs("tests/test_x.py", docs)
    assert len(hits) == 1
    assert hits[0].confidence == "high"


# --- build_report / render_markdown -----------------------------------------


def test_build_report_empty_diff_has_no_hits(tmp_path: Path) -> None:
    docs = tmp_path / "docs" / "solutions"
    docs.mkdir(parents=True)
    report = build_report("", docs)
    assert report.moves_with_hits == []
    assert report.has_hits is False
    assert "No test moves reference" in render_markdown(report)


def test_render_markdown_lists_moves_and_hits(tmp_path: Path) -> None:
    docs = tmp_path / "docs" / "solutions"
    docs.mkdir(parents=True)
    _write(docs, "a.md", "see `tests/test_foo.py`\n")
    diff = "R100\ttests/test_foo.py\ttests/meta/test_foo.py\n"
    md = render_markdown(build_report(diff, docs))
    assert "tests/test_foo.py" in md
    assert "tests/meta/test_foo.py" in md
    assert "a.md:1" in md


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("tests/test_foo.py", True),
        ("tests/meta/test_foo.py", True),
        ("tests/conftest.py", True),
        ("src/protokit/foo.py", False),
        ("tests/fixtures/data.proto", False),
        ("docs/solutions/x.md", False),
    ],
)
def test_is_test_path(path: str, expected: bool) -> None:
    from scripts.check_docs_test_refs import _is_test_path

    assert _is_test_path(path) is expected
