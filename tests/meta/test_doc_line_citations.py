"""A learning's line citation points inside the file it names.

``docs/solutions/`` cites source by line (``src/protokit/_pools.py:251``,
``tests/core/test_pools.py:237-260``), and source edits are made so those lines
keep their numbers. Nothing checked the other direction. This holds the one
part of it a machine can decide: a cited line exists. A file that shrinks below
a line a learning cites fails here, at the commit that shrank it.

It does not say the line still shows what the learning describes; that needs a
reader. It reads only citations written with a path from the repository root
that names a file in the tree, so a library source cited by version
(``_pytest/skipping.py:288-304``) and a bare file name are left alone.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LEARNINGS = _REPO_ROOT / "docs" / "solutions"
_CITATION = re.compile(
    r"(?<![\w/.-])((?:src|tests|scripts|\.github)/[\w./-]+\.(?:py|yml|toml|txt|md)):(\d+)(?:-(\d+))?"
)


def _citations() -> list[tuple[str, int, str, int]]:
    """``(learning, its line, cited path, last cited line)`` for every readable citation."""
    found: list[tuple[str, int, str, int]] = []
    for learning in sorted(_LEARNINGS.rglob("*.md")):
        text = learning.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            for match in _CITATION.finditer(line):
                cited = match.group(1)
                if (_REPO_ROOT / cited).is_file():
                    last = int(match.group(3) or match.group(2))
                    found.append((str(learning.relative_to(_REPO_ROOT)), number, cited, last))
    return found


def test_the_walk_finds_citations() -> None:
    # A regex that matched nothing would pass the test below for ever.
    assert len(_citations()) > 300


def test_every_cited_line_exists() -> None:
    lengths: dict[str, int] = {}
    past_the_end: list[str] = []
    for learning, number, cited, last in _citations():
        if cited not in lengths:
            with (_REPO_ROOT / cited).open(encoding="utf-8", errors="replace") as handle:
                lengths[cited] = sum(1 for _ in handle)
        if last > lengths[cited]:
            past_the_end.append(
                f"{learning}:{number} cites {cited}:{last}, and the file has {lengths[cited]} lines"
            )
    assert not past_the_end, (
        "a learning cites a line past the end of its file. Either the file lost lines "
        "(restore them, or move the citation with the code), or the citation was never "
        "right:\n  " + "\n  ".join(past_the_end)
    )


def test_the_pattern_reads_what_it_should_and_nothing_else() -> None:
    match = _CITATION.search("see `tests/meta/test_doc_line_citations.py:99999` for it")
    assert match is not None
    assert (match.group(1), match.group(2)) == ("tests/meta/test_doc_line_citations.py", "99999")
    ranged = _CITATION.search("(`src/protokit/_pools.py:182-183`)")
    assert ranged is not None
    assert ranged.group(3) == "183"
    # Not read: a library source, and a bare file name.
    assert _CITATION.search("`_pytest/skipping.py:288-304`") is None
    assert _CITATION.search("`skipping.py:306-308`") is None
