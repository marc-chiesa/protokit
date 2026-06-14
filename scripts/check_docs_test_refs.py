#!/usr/bin/env python3
"""Reference-drift reporter for ``docs/solutions/`` (plan U1).

When a test file is renamed or removed on a branch, learnings under
``docs/solutions/`` that name its old path go stale. This script surfaces
those references for human triage — it never edits a doc and never fails
the build (the CI job that runs it is non-blocking, plan R2/R3/SC3). Triage
(navigational pointer → update, intentional/historical → leave) is a human
judgement the reporter deliberately does not make.

Detection keys on ``git diff --name-status -M``, which reports renames as
``R<score>\\told\\tnew`` and removals as ``D\\told``. The doc search keys on
the *full* old path (high confidence); a doc that names only the bare
basename is reported low-confidence, because ``tests/`` has colliding
basenames (e.g. ``conftest.py`` in five directories) and a basename-only
match cannot prove it is the moved file (plan KTD2).

Usage::

    python scripts/check_docs_test_refs.py [BASE_REF]

``BASE_REF`` defaults to ``origin/main``. Output goes to stdout and, when
``$GITHUB_STEP_SUMMARY`` is set, is appended there as a Markdown summary.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOCS_ROOT = _REPO_ROOT / "docs" / "solutions"
_DEFAULT_BASE = "origin/main"


def _is_test_path(path: str) -> bool:
    """A path is a test file iff it lives under ``tests/`` and ends ``.py``."""
    return path.startswith("tests/") and path.endswith(".py")


@dataclass(frozen=True)
class Move:
    """A renamed or removed test file.

    ``new_path`` is the post-rename path, or ``None`` for a removal.
    """

    old_path: str
    new_path: str | None


def parse_moves(diff_output: str) -> list[Move]:
    """Parse ``git diff --name-status -M`` output into test-file moves.

    Only renames (``R``) and removals (``D``) of test files are returned;
    additions, modifications, and non-test paths are ignored. A heavily
    rewritten-then-moved file that git scores below its rename threshold
    surfaces as a removal (``D`` on the old path) rather than a rename —
    still surfaced for triage, just without a new-path suggestion.
    """
    moves: list[Move] = []
    for raw in diff_output.splitlines():
        line = raw.rstrip("\n")
        if not line:
            continue
        fields = line.split("\t")
        status = fields[0]
        if status.startswith("R") and len(fields) >= 3:
            old, new = fields[1], fields[2]
            if _is_test_path(old):
                moves.append(Move(old_path=old, new_path=new))
        elif status.startswith("D") and len(fields) >= 2:
            old = fields[1]
            if _is_test_path(old):
                moves.append(Move(old_path=old, new_path=None))
    return moves


@dataclass(frozen=True)
class Hit:
    """A ``docs/solutions/`` line that references a moved test path."""

    doc: str  # repo-relative path
    line_no: int  # 1-based
    line: str
    confidence: str  # "high" (full path) | "low" (basename only)


def find_doc_refs(old_path: str, docs_root: Path) -> list[Hit]:
    """Find ``docs/solutions/`` lines that name ``old_path``.

    A line containing the full ``old_path`` is a high-confidence hit. A line
    containing only the basename (and not the full path) is low-confidence —
    it may name a same-named file in a different directory. Both are reported
    so a human can triage; the reporter never decides which to update.
    """
    basename = old_path.rsplit("/", 1)[-1]
    hits: list[Hit] = []
    for md in sorted(docs_root.rglob("*.md")):
        try:
            rel = md.relative_to(_REPO_ROOT).as_posix()
        except ValueError:
            # docs_root outside the repo (tests) — report relative to it.
            rel = md.relative_to(docs_root).as_posix()
        text = md.read_text(encoding="utf-8")
        for idx, line in enumerate(text.splitlines(), start=1):
            if old_path in line:
                hits.append(Hit(doc=rel, line_no=idx, line=line.strip(), confidence="high"))
            elif basename in line:
                hits.append(Hit(doc=rel, line_no=idx, line=line.strip(), confidence="low"))
    return hits


def _git_diff(base: str, repo_root: Path) -> str:
    """Return ``git diff --name-status -M <base>...HEAD`` output."""
    result = subprocess.run(
        ["git", "diff", "--name-status", "-M", f"{base}...HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


@dataclass(frozen=True)
class Report:
    """The full reference-drift report: every move and its doc references."""

    moves_with_hits: list[tuple[Move, list[Hit]]]

    @property
    def has_hits(self) -> bool:
        return any(hits for _, hits in self.moves_with_hits)


def build_report(diff_output: str, docs_root: Path) -> Report:
    """Compose a report from a diff and a docs root (no git/subprocess)."""
    moves = parse_moves(diff_output)
    return Report(
        moves_with_hits=[(m, find_doc_refs(m.old_path, docs_root)) for m in moves]
    )


def render_markdown(report: Report) -> str:
    """Render the report as a Markdown summary for humans / CI step summary."""
    if not report.has_hits:
        return (
            "### docs/solutions reference check\n\n"
            "No test moves reference `docs/solutions/`. ✓\n"
        )
    lines = [
        "### docs/solutions reference check",
        "",
        "A test file moved; the docs below name its old path. "
        "Update navigational pointers; leave intentional/historical mentions. "
        "(Non-blocking — this is a review prompt, not a gate.)",
        "",
    ]
    for move, hits in report.moves_with_hits:
        if not hits:
            continue
        target = move.new_path if move.new_path else "(removed)"
        lines.append(f"- `{move.old_path}` → `{target}`")
        for hit in hits:
            flag = "" if hit.confidence == "high" else " _(basename only — verify)_"
            lines.append(f"  - `{hit.doc}:{hit.line_no}`{flag}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Print the report; append to ``$GITHUB_STEP_SUMMARY`` if set. Always 0."""
    args = sys.argv[1:] if argv is None else argv
    base = args[0] if args else _DEFAULT_BASE
    report = build_report(_git_diff(base, _REPO_ROOT), _DOCS_ROOT)
    md = render_markdown(report)
    print(md)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(md)
    return 0  # non-blocking: report, never fail the build


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
