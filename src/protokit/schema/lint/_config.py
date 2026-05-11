"""Pyproject `[tool.protokit.lint]` config loader (D5 U1).

Internal module: imported only from ``protokit.schema.lint.cli``; never
re-exported from ``protokit.schema.lint.__init__``. The leading
underscore marks the module as not-public-API — consumers invoke the
CLI, they do not import from here.

**Cold-import contract**: this module sits under
``protokit.schema.lint.`` so the broader cold-import-extended test's
substring check (``'protokit.schema.lint' in k``) auto-quarantines it
from ``import protokit.schema`` consumers. The lint-cli-specific test
(``'protokit.schema.lint.cli' in k``) also covers it transitively
via cli.py's import. No edits to the cold-import test required.

**Scope (U1)**: discovery + parsing only. Schema validation (R3, R3a),
precedence resolution (R11-R14), and the ``ResolvedLintConfig`` carrier
land in U2. U1 returns the raw ``dict[str, Any]`` parsed from the
``[tool.protokit.lint]`` table (or ``None`` when no config applies).

**Security posture (per plan KTD-7, KTD-9, R5a)**:

- Walk-up termination uses ``(parent / ".git").exists()`` to cover both
  ``.git`` directories AND ``.git`` files (git worktrees, submodules).
  The ``.git`` path is checked for existence only; its contents (the
  ``gitdir: ...`` pointer in worktree ``.git`` files) are NEVER read,
  parsed, or followed.
- All R5a shadow paths (missing file, unreadable, table-absent, invalid
  TOML) produce exit 2 via ``error_exit_with_code("pyproject-config-load",
  ...)`` with newline-sanitized stderr.
- ``tomllib.TOMLDecodeError`` messages may include raw file bytes per
  cpython issue; D5 replaces the raw error message with the structured
  form ``"TOML parse error at {path}:{line}:{col}"`` using only safe
  exception attributes.
- Triple-arm exception guards ``(SystemExit, KeyboardInterrupt,
  Exception)`` around ``tomllib`` calls per the
  ``keyboardinterrupt-baseexception-bypass-rule-pack-load-2026-05-07.md``
  learning. ``KeyboardInterrupt`` is caught and re-raised so the user's
  SIGINT propagates to Python's default handler (exit 130) rather than
  being absorbed.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from protokit.schema.lint._cli_utils import error_exit_with_code

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_pyproject_config(
    *,
    explicit_path: Path | None,
    no_config: bool,
) -> dict[str, Any] | None:
    """Load the ``[tool.protokit.lint]`` table from pyproject.toml.

    Resolution order (per plan R1, R1a, R5, R5a):

    1. If ``no_config`` is True, return ``None`` immediately (bypass).
    2. If ``explicit_path`` is provided, load it in **strict mode**:
       all R5a shadow paths (missing file, unreadable, missing table,
       invalid TOML) produce exit 2 with ``pyproject-config-load`` error
       code. This is the explicit-intent path: a user who typed
       ``--config PATH`` deserves a hard error if their path can't load.
    3. Otherwise, walk up from CWD looking for ``pyproject.toml``,
       terminating at the first ``.git`` boundary (worktree-safe via
       ``.exists()``). Walk-up uses **silent fallback**: not-found,
       table-absent, etc. return ``None`` (run with built-in defaults).
       Hard errors (unreadable file, invalid TOML) still produce exit 2.

    Walk-up ordering when both ``.git`` AND ``pyproject.toml`` exist at
    the same parent: check ``pyproject.toml`` FIRST at that level
    (return it), THEN apply the ``.git`` termination signal. This
    preserves "first-match-wins" for pyproject discovery while keeping
    ``.git`` as the OUTER walk-up bound.

    Args:
        explicit_path: Path supplied via ``--config PATH``. ``None``
            means walk-up should run.
        no_config: ``True`` when ``--no-config`` was given. Bypasses
            both walk-up and explicit-path resolution.

    Returns:
        The parsed ``[tool.protokit.lint]`` dict, OR ``None`` when no
        config applies. ``None`` is returned for:

        - ``no_config=True``
        - Walk-up reached the boundary without finding a pyproject
        - Walk-up found a pyproject but it has no
          ``[tool.protokit.lint]`` table (silent fallback)

    Raises:
        SystemExit: Exit code 2 via ``error_exit_with_code(
        "pyproject-config-load", ...)`` for any R5a shadow path or
        unrecoverable parse error.
    """
    if no_config:
        return None

    if explicit_path is not None:
        return _load_explicit(explicit_path)

    pyproject_path = _walk_up_find_pyproject(Path.cwd())
    if pyproject_path is None:
        return None

    return _load_from_walkup(pyproject_path)


# ---------------------------------------------------------------------------
# Walk-up discovery (R1, R1a, KTD-7)
# ---------------------------------------------------------------------------


def _walk_up_find_pyproject(start: Path) -> Path | None:
    """Walk up from ``start`` looking for ``pyproject.toml``; terminate at ``.git``.

    Per KTD-7: the ``.git`` boundary check uses ``(parent / ".git").exists()``
    so both ``.git`` directories (standard checkouts) AND ``.git`` files
    (git worktrees, submodules — where ``.git`` contains
    ``gitdir: <path>``) terminate the walk-up. Using ``.is_dir()`` would
    silently skip past worktree roots into attacker-writable parent
    directories.

    Order of operations when both ``.git`` AND ``pyproject.toml`` exist
    at the same level: pyproject FIRST (return it), THEN .git (terminate).

    Args:
        start: The starting directory (typically ``Path.cwd()``). Tests
            inject a controlled path to avoid CWD coupling.

    Returns:
        Absolute path to the discovered ``pyproject.toml`` file, OR
        ``None`` if walk-up reached the filesystem root or a ``.git``
        boundary without finding one.
    """
    for candidate in (start, *start.parents):
        pyproject = candidate / "pyproject.toml"
        if pyproject.is_file():
            return pyproject
        # `.git` content is never read — existence check only (KTD-7).
        if (candidate / ".git").exists():
            return None
    return None


# ---------------------------------------------------------------------------
# Loading: explicit path (R5a strict mode) and walk-up path (silent fallback)
# ---------------------------------------------------------------------------


def _load_explicit(path: Path) -> dict[str, Any]:
    """Load ``--config PATH`` in strict R5a mode (table-absent is an error)."""
    table = _read_and_parse(path)
    lint_table = _extract_lint_table(table)
    if lint_table is None:
        error_exit_with_code(
            "pyproject-config-load",
            (
                f"--config path has no [tool.protokit.lint] table: "
                f"{_safe_for_stderr(path)}"
            ),
        )
    return lint_table


def _load_from_walkup(path: Path) -> dict[str, Any] | None:
    """Load walk-up-discovered pyproject (silent fallback on table-absent)."""
    table = _read_and_parse(path)
    # Walk-up: table-absent returns None silently (run with built-in defaults
    # per R5). Only parse-time errors are hard.
    return _extract_lint_table(table)


def _read_and_parse(path: Path) -> dict[str, Any]:
    """Read bytes from ``path`` and parse as TOML; produce R5a shadow-path errors.

    Triple-arm guard wraps the ``tomllib.loads`` call: ``SystemExit`` is
    rerouted to ``error_exit_with_code`` (prevents malicious config
    bodies from emitting a fake-clean exit); ``KeyboardInterrupt``
    propagates to Python's default handler (catch-and-reraise per
    KTD-9 / scope-guardian F5); other exceptions route to the
    ``pyproject-config-load`` error code with sanitized stderr.

    R5a content-safety: ``TOMLDecodeError`` is normalized to
    ``"TOML parse error at {path}:{line}:{col}"`` so raw file bytes
    can never leak via the error message.
    """
    if not path.exists():
        error_exit_with_code(
            "pyproject-config-load",
            f"--config path does not exist: {_safe_for_stderr(path)}",
        )

    try:
        data = path.read_bytes()
    except OSError as exc:
        error_exit_with_code(
            "pyproject-config-load",
            (
                f"--config path unreadable: {_safe_for_stderr(path)}: "
                f"{_safe_for_stderr(exc)}"
            ),
        )

    return _parse_toml_bytes(data, path)


def _parse_toml_bytes(data: bytes, path: Path) -> dict[str, Any]:
    """Decode and parse TOML bytes; produce R5a-safe error messages.

    Decoupled from ``_read_and_parse`` so tests can inject TOML bytes
    directly without round-tripping through the filesystem.
    """
    try:
        parsed: dict[str, Any] = tomllib.loads(data.decode("utf-8"))
        return parsed
    except SystemExit as exc:
        # A malicious config body that calls ``sys.exit()`` at parse
        # time would otherwise produce a false-clean exit. Triple-arm
        # catch routes it to the lint-internal error surface.
        error_exit_with_code(
            "pyproject-config-load",
            (
                f"TOML parser raised SystemExit({exc.code!r}) parsing "
                f"{_safe_for_stderr(path)} (malicious config?)"
            ),
        )
    except KeyboardInterrupt:
        # User SIGINT — propagate to Python's default handler (exit 130).
        # Catch-and-reraise prevents the bare-Exception arm from
        # absorbing the interrupt signal (per KTD-9).
        raise
    except UnicodeDecodeError:
        # Not valid UTF-8 (R5a invalid-input case before TOML-level parse).
        # Don't echo the raw bytes/position — just name the file.
        error_exit_with_code(
            "pyproject-config-load",
            f"TOML parse error in {_safe_for_stderr(path)}: not valid UTF-8",
        )
    except tomllib.TOMLDecodeError as exc:
        # R5a content-safety: tomllib.TOMLDecodeError.args[0] may include
        # raw file bytes / fragments. NEVER expose. Use only structured
        # attributes (lineno, colno) if present on the exception.
        line = getattr(exc, "lineno", None)
        col = getattr(exc, "colno", None)
        if line is not None and col is not None:
            msg = (
                f"TOML parse error at {_safe_for_stderr(path)}:{line}:{col}"
            )
        else:
            msg = f"TOML parse error in {_safe_for_stderr(path)}"
        error_exit_with_code("pyproject-config-load", msg)
    except Exception as exc:  # noqa: BLE001 -- triple-arm guard tail
        # Defense-in-depth for any future tomllib exception type.
        error_exit_with_code(
            "pyproject-config-load",
            (
                f"TOML parse error in {_safe_for_stderr(path)}: "
                f"{type(exc).__name__}"
            ),
        )

    # Unreachable: error_exit_with_code is NoReturn. mypy / type checkers
    # may not infer that, so the assertion below makes the function's
    # return-type guarantee explicit.
    raise AssertionError("_parse_toml_bytes: unreachable")  # pragma: no cover


# ---------------------------------------------------------------------------
# Table extraction
# ---------------------------------------------------------------------------


def _extract_lint_table(table: dict[str, Any]) -> dict[str, Any] | None:
    """Extract ``[tool.protokit.lint]`` sub-table; return ``None`` if absent.

    Tomllib returns nested tables as nested ``dict[str, Any]``. We walk
    three levels and bail at any non-dict shape (defends against
    pathological inputs like ``[tool] = "not a table"``).
    """
    tool = table.get("tool")
    if not isinstance(tool, dict):
        return None
    protokit = tool.get("protokit")
    if not isinstance(protokit, dict):
        return None
    lint = protokit.get("lint")
    if not isinstance(lint, dict):
        return None
    return lint


# ---------------------------------------------------------------------------
# Stderr-safe rendering helpers (KTD-9 newline sanitization)
# ---------------------------------------------------------------------------


def _safe_for_stderr(value: object) -> str:
    """Collapse newlines/carriage returns in a stringified value.

    Defense-in-depth against attacker-controlled strings flowing into
    single-line ``click.echo(..., err=True)`` output. Paths, exception
    messages, and any other stringified field that may include
    user-controlled bytes is passed through this helper before being
    interpolated into stderr error messages.

    Mirrors ``_safe_module_name`` in ``protokit.schema.lint._cli_utils``
    but generalized to arbitrary values (Path, Exception, str).
    """
    return str(value).replace("\n", " ").replace("\r", " ")
