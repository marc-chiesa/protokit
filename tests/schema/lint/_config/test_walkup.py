"""Tests for ``_walk_up_find_pyproject`` (D5 U1, R1, R1a, KTD-7).

Covers walk-up discovery semantics:

- pyproject in CWD.
- pyproject in a parent directory (no ``.git`` between).
- Walk-up terminates at first ``.git`` directory (standard checkout).
- **Walk-up terminates at first ``.git`` FILE** (git worktree;
  ``.git`` is a ``gitdir: ...`` pointer file). This is the
  load-bearing KTD-7 test — using ``Path.is_dir()`` would silently
  skip past worktree roots into attacker-writable parent directories.
- Walk-up reaches filesystem root without finding ``.git``
  (no-checkout CI scenario).
- Walk-up finds ``pyproject.toml`` before ``.git`` boundary when
  both exist at the same level (pyproject FIRST per KTD-7 ordering).
- Walk-up terminates at ``.git`` even when no pyproject is present at
  that level.

All tests use ``tmp_path`` to inject a controlled directory hierarchy
so the walk-up logic is exercised against synthetic filesystems
rather than the real CWD.
"""

from __future__ import annotations

from pathlib import Path

from protokit.schema.lint._config import _walk_up_find_pyproject


class TestWalkupHappyPaths:
    def test_pyproject_in_start_directory(self, tmp_path: Path) -> None:
        """Walk-up returns immediately when pyproject is at start."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[tool.protokit.lint]\nprofile = 'default'\n")
        # .git boundary outside the search range — synthesize so walk-up
        # stops cleanly above tmp_path if pyproject weren't there.
        (tmp_path / ".git").mkdir()

        result = _walk_up_find_pyproject(tmp_path)

        assert result == pyproject

    def test_pyproject_in_parent_no_git_between(self, tmp_path: Path) -> None:
        """Walk-up climbs one level when CWD has no pyproject."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[tool.protokit.lint]\n")
        (tmp_path / ".git").mkdir()
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        result = _walk_up_find_pyproject(subdir)

        assert result == pyproject

    def test_pyproject_in_grandparent(self, tmp_path: Path) -> None:
        """Walk-up climbs multiple levels when intermediate dirs are empty."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[tool.protokit.lint]\n")
        (tmp_path / ".git").mkdir()
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)

        result = _walk_up_find_pyproject(deep)

        assert result == pyproject


class TestWalkupGitBoundary:
    """KTD-7: walk-up terminates at first ``.git`` (existence check; covers
    both directory and file shapes)."""

    def test_terminates_at_git_directory(self, tmp_path: Path) -> None:
        """Standard git checkout: ``.git`` is a directory."""
        (tmp_path / ".git").mkdir()
        # No pyproject.toml at or below tmp_path; one exists above but is
        # outside the .git boundary.
        outer_pyproject = tmp_path.parent / "pyproject.toml"
        outer_pyproject.write_text("[tool.protokit.lint]\n")
        subdir = tmp_path / "src"
        subdir.mkdir()

        try:
            result = _walk_up_find_pyproject(subdir)
        finally:
            outer_pyproject.unlink(missing_ok=True)

        # Must NOT return the outer pyproject — walk-up stops at .git.
        assert result is None

    def test_terminates_at_git_file_worktree(self, tmp_path: Path) -> None:
        """**KEY TEST**: git worktrees use ``.git`` as a FILE pointer.

        Verifies KTD-7: the ``.exists()`` check (not ``.is_dir()``)
        correctly terminates at file-shaped ``.git``. A buggy
        implementation using ``.is_dir()`` would silently skip past
        the worktree root and walk into attacker-writable parents.
        """
        # Create a `.git` FILE (worktree pointer shape).
        git_file = tmp_path / ".git"
        git_file.write_text(
            "gitdir: /path/to/main/.git/worktrees/test-worktree\n",
        )
        # Place a pyproject ABOVE the worktree boundary.
        outer_pyproject = tmp_path.parent / "pyproject.toml"
        outer_pyproject.write_text("[tool.protokit.lint]\n")
        subdir = tmp_path / "src"
        subdir.mkdir()

        try:
            result = _walk_up_find_pyproject(subdir)
        finally:
            outer_pyproject.unlink(missing_ok=True)

        # Walk-up must STOP at the .git FILE, not skip past it.
        assert result is None, (
            "Walk-up crossed worktree .git FILE boundary — "
            "implementation likely uses .is_dir() instead of .exists()."
        )

    def test_pyproject_first_then_git_at_same_level(
        self, tmp_path: Path,
    ) -> None:
        """KTD-7 order: pyproject FIRST, .git is OUTER bound only.

        When both ``.git`` AND ``pyproject.toml`` exist at the same
        parent level, walk-up returns the pyproject (first-match-wins)
        — the .git termination is only relevant if pyproject was NOT
        found at the same level.
        """
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[tool.protokit.lint]\n")
        (tmp_path / ".git").mkdir()

        result = _walk_up_find_pyproject(tmp_path)

        # Pyproject wins over .git termination at the SAME level.
        assert result == pyproject


class TestWalkupNoConfig:
    def test_no_pyproject_no_git_reaches_root(self, tmp_path: Path) -> None:
        """Walk-up traverses to filesystem root and returns None when no
        ``pyproject.toml`` and no ``.git`` exist anywhere in the chain.

        Note: this test relies on the real filesystem above tmp_path
        not having ``pyproject.toml`` at any ancestor up to ``/``. If
        the harness CWD happens to be inside a project tree, the test
        may inadvertently discover that project's pyproject. Use
        tmp_path which is under ``/tmp`` (no expected ancestor
        pyproject on standard CI environments).
        """
        # tmp_path itself has no pyproject and no .git.
        deep = tmp_path / "a" / "b"
        deep.mkdir(parents=True)

        result = _walk_up_find_pyproject(deep)

        # tmp_path's ancestors (/tmp, /) typically have no pyproject
        # or .git on a clean CI environment.
        assert result is None

    def test_terminates_at_git_with_no_pyproject_at_boundary(
        self, tmp_path: Path,
    ) -> None:
        """``.git`` boundary terminates walk-up even when no pyproject
        is present at that level — the boundary is an UPPER bound,
        not a precondition for pyproject discovery."""
        (tmp_path / ".git").mkdir()
        subdir = tmp_path / "src" / "deeply" / "nested"
        subdir.mkdir(parents=True)

        result = _walk_up_find_pyproject(subdir)

        assert result is None


class TestWalkupSecurityNotes:
    """KTD-7 contracts that are verified architecturally rather than
    by direct test:

    - The ``.git`` path is checked for existence ONLY; its contents
      (e.g. a worktree's ``gitdir: ...`` pointer) are NEVER read,
      parsed, or followed.
    - The ``.git``-as-terminator becomes an attacker primitive on
      shared filesystems (attacker who can ``mkdir /tmp/attack/.git``
      controls walk-up termination). The plan accepts this as a
      code-review-discipline concern; the existence-only check
      prevents widening the attack surface to .git CONTENT parsing.
    """

    def test_worktree_gitdir_content_is_not_read(self, tmp_path: Path) -> None:
        """A ``.git`` FILE with malicious gitdir pointer is treated as
        existence-only — the pointer text is never parsed or followed."""
        # An attacker-controlled gitdir pointer would normally be a
        # path-injection vector if read; the implementation MUST NOT
        # read this file's contents.
        git_file = tmp_path / ".git"
        git_file.write_text("gitdir: /etc/shadow\n")
        subdir = tmp_path / "src"
        subdir.mkdir()

        # If the implementation tried to follow the gitdir pointer,
        # this call would either fail (permission denied on /etc/shadow)
        # or return something unexpected. Existence-only semantics mean
        # the call returns None cleanly — walk-up terminated at the .git
        # FILE with no further action.
        result = _walk_up_find_pyproject(subdir)

        assert result is None
