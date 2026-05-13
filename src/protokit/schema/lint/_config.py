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

import dataclasses
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

import pathspec

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from protokit.schema.lint._cli_utils import _safe_for_stderr, error_exit_with_code
from protokit.schema.lint.model import SEVERITY_RANK, LintSeverity

# Per-key source attribution for ResolvedLintConfig (R20 message branches).
# Used for `min_severity_source`: cli vs pyproject is mutually exclusive
# (CLI replaces pyproject); a "both" message branch is encoded by
# `min_severity_source="cli"` + `pyproject_min_severity is not None`.
#
# - "cli":       CLI flag (--profile/--min-severity/etc) explicitly provided.
# - "pyproject": Pyproject set this key; CLI did not override.
# - "profile":   Neither CLI nor pyproject set this key; the composed
#                profile's intrinsic floor is in effect. U4 may transition
#                "default" to "profile" at emission time when min_severity
#                is None.
# - "default":   Neither CLI nor pyproject nor profile set this key.
ConfigSource = Literal["cli", "pyproject", "profile", "default"]

# Exclude-specific source attribution (R20 message branches for
# `all_files_excluded`). Unlike `min_severity` (where CLI replaces
# pyproject), `exclude` APPENDS CLI patterns to pyproject patterns,
# so the "both" case is structurally distinct — both sources
# CONTRIBUTE patterns rather than one overriding the other.
#
# - "cli":       CLI `--exclude` patterns only (no pyproject exclude).
# - "pyproject": Pyproject `exclude` patterns only (no CLI flags).
# - "both":      Both CLI AND pyproject contributed patterns.
# - "default":   No exclude configured (resolved.exclude is the empty tuple).
ExcludeSource = Literal["cli", "pyproject", "both", "default"]

# Source-attribution descriptors for the R20 ``all_files_excluded``
# message. ``"default"`` is excluded from the mapping because the
# ``__post_init__`` invariant on ``ResolvedLintConfig`` rejects
# ``exclude_source == "default"`` when ``exclude`` is non-empty, so
# the descriptor is never needed at the emit site.
_EXCLUDE_SOURCE_DESC: dict[ExcludeSource, str] = {
    "cli": "--exclude",
    "pyproject": "[tool.protokit.lint] exclude",
    "both": "--exclude and [tool.protokit.lint] exclude",
}


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

    # Fix #13: Path.cwd() can raise FileNotFoundError (deleted CWD) or
    # PermissionError (sandboxed environments). Wrap with the same
    # pyproject-config-load surface so users see a stable error prefix
    # rather than an uncaught OSError traceback.
    try:
        cwd = Path.cwd()
    except OSError as exc:
        error_exit_with_code(
            "pyproject-config-load",
            (
                "walk-up aborted: current working directory is unavailable "
                f"(deleted or unreachable): {_safe_for_stderr(exc)}"
            ),
        )

    pyproject_path = _walk_up_find_pyproject(cwd)
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
        # Fix #3: Wrap each iteration's stat calls in try/except so a
        # PermissionError on a mid-walk-up directory routes to the stable
        # pyproject-config-load surface rather than escaping as an
        # uncaught OSError traceback. Do NOT silently swallow — that
        # would let an unreadable parent silently skip past the .git
        # boundary check.
        try:
            pyproject = candidate / "pyproject.toml"
            if pyproject.is_file():
                return pyproject
            # `.git` content is never read — existence check only (KTD-7).
            if (candidate / ".git").exists():
                return None
        except OSError as exc:
            error_exit_with_code(
                "pyproject-config-load",
                (
                    f"walk-up filesystem error at "
                    f"{_safe_for_stderr(candidate)}: {_safe_for_stderr(exc)}"
                ),
            )
    return None


# ---------------------------------------------------------------------------
# Loading: explicit path (R5a strict mode) and walk-up path (silent fallback)
# ---------------------------------------------------------------------------


def _load_explicit(path: Path) -> dict[str, Any]:
    """Load ``--config PATH`` in strict R5a mode (table-absent is an error)."""
    table = _read_and_parse(path, source_label="--config path")
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
    table = _read_and_parse(
        path, source_label="walk-up-discovered pyproject",
    )
    # Walk-up: table-absent returns None silently (run with built-in defaults
    # per R5). Only parse-time errors are hard.
    return _extract_lint_table(table)


def _read_and_parse(
    path: Path, *, source_label: str = "--config path",
) -> dict[str, Any]:
    """Read bytes from ``path`` and parse as TOML; produce R5a shadow-path errors.

    The ``source_label`` parameter controls the wording of OS-level
    error messages (missing file / unreadable file) so walk-up-discovered
    pyprojects and explicit ``--config PATH`` callers each get
    accurate attribution. Defaults to ``"--config path"`` so any future
    caller that forgets to pass the label still gets the strict
    explicit-mode wording rather than a misleading walk-up message.

    Fix #1 (5-persona converged finding): walk-up callers used to
    inherit the "``--config path``" wording from explicit-mode
    error messages, which mis-attributed walk-up filesystem errors
    (e.g., ``PermissionError`` on a walked-into parent pyproject) as
    a flag the user never passed.

    Fix #20: ``path.exists()`` is no longer pre-checked. ``OSError``
    from ``path.read_bytes()`` discriminates ``FileNotFoundError``
    (missing) vs other ``OSError`` (unreadable / EACCES / EISDIR).
    This eliminates the TOCTOU window between the walk-up
    ``is_file()`` check and the post-walk-up ``exists()`` check and
    removes a redundant stat syscall.

    Parse-time error handling (triple-arm guard for ``tomllib.loads``,
    ``TOMLDecodeError`` content-safety normalization, UTF-8 decode
    handling) is the responsibility of :func:`_parse_toml_bytes`. This
    function only owns the read-bytes-from-disk surface.
    """
    # Fix #7: Initialize `data` so mypy's flow analysis treats it as
    # bound on all paths reaching `_parse_toml_bytes` below. The
    # `error_exit_with_code` call is NoReturn, but type checkers may
    # not always infer that across an except clause.
    data: bytes = b""
    try:
        data = path.read_bytes()
    except OSError as exc:
        # Fix #20: discriminate missing-file vs other OSError variants
        # (PermissionError, IsADirectoryError) via isinstance — no
        # redundant pre-check needed.
        if isinstance(exc, FileNotFoundError):
            error_exit_with_code(
                "pyproject-config-load",
                f"{source_label} does not exist: {_safe_for_stderr(path)}",
            )
        error_exit_with_code(
            "pyproject-config-load",
            (
                f"{source_label} unreadable: {_safe_for_stderr(path)}: "
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
        #
        # Fix #14 documentation note: the structured `at {path}:line:col`
        # form is reachable only when the TOML library exposes lineno/
        # colno as attributes. The two cases:
        #   - tomli (py<3.11 backport): exposes lineno/colno → structured form.
        #   - stdlib tomllib (py3.11+): does NOT expose lineno/colno;
        #     args[0] contains free-form text instead → falls through
        #     to the unstructured `"TOML parse error in {path}"` form.
        # The fallback is correct under both libraries; the asymmetry is
        # documented here so the structured branch isn't mistaken for
        # dead code on py3.11+.
        #
        # Fix #22: tighten the precondition to require both attributes
        # be `int`. `getattr(..., None)` could in principle return a
        # non-int from a future tomli release with a different attr
        # shape, and that value would otherwise be interpolated
        # unsanitized into the stderr message.
        line = getattr(exc, "lineno", None)
        col = getattr(exc, "colno", None)
        if isinstance(line, int) and isinstance(col, int):
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
# Per ce:review finding #9, `_safe_for_stderr` was consolidated to
# `protokit.schema.lint._cli_utils` so the canonical implementation is
# shared with `_safe_module_name` (which now delegates to it). The
# import is at the top of this module alongside `error_exit_with_code`.
# Per ce:review finding #11, the sanitization scope was extended from
# newlines only to all ASCII control characters (\n, \r, \x00, \x1b,
# \t, etc.) — see the helper's docstring for the threat model.


# ---------------------------------------------------------------------------
# Schema validation + precedence (D5 U2: R2, R3, R3a, R11-R14, KTD-2, KTD-5)
# ---------------------------------------------------------------------------

#: Top-level keys allowed inside ``[tool.protokit.lint]`` (R2 allowlist).
#: Anything else surfaces via :func:`_validate_table_keys` as an R3 error,
#: including nested tables like ``[tool.protokit.lint.rules.foo]`` whose
#: TOP-LEVEL key (``"rules"``) is not in this set. D6a admits two new
#: keys (``severities``, ``no_builtin_rules``) per R9a / R9c; until
#: cross-language profiles arrive in D6b the contract remains "top-level
#: allowlist only" per KTD-2.
#:
#: Note: ``schema_version`` is wire-format OUTPUT only (R9d) — it is
#: emitted by formatters, never accepted as pyproject input.
_ALLOWED_KEYS: frozenset[str] = frozenset(
    {
        "profile",
        "exclude",
        "min_severity",
        "max_warnings",
        "format",
        "severities",
        "no_builtin_rules",
    },
)

#: Buf-compatibility profile aliases resolved at the
#: ``_coerce_profile`` input boundary (per KTD-1 and the
#: ``normalize-at-input-boundary`` learning). Both pyproject and CLI
#: input paths flow through ``_coerce_profile`` via ``from_dict``'s
#: coercion step, so this single mapping covers both surfaces.
#:
#: Downstream code (rule pack profile-name matching, ``LintProfile.compose``)
#: sees only primary protokit-native names; aliases never leak past the
#: coercion boundary. A user pack declaring ``profiles=("basic",)`` would
#: never match because ``"basic"`` is resolved to ``"recommended"`` before
#: lookup — this is the intended trade-off (users can extend recommended
#: but not the buf-alias name itself).
_PROFILE_ALIASES: dict[str, str] = {
    "minimal": "essentials",
    "basic": "recommended",
}


def _validate_table_keys(table: Mapping[str, Any]) -> None:
    """Hard-error on any key outside R2's allowlist.

    Per R3 / KTD-2's single-pass posture: nested tables like
    ``[tool.protokit.lint.rules.foo]`` surface as the top-level
    unknown key ``"rules"``, not the dotted path. D6 may extend to
    dotted-path messages when nested tables become first-class.

    Error message names the unknown top-level key(s) AND the
    recognized keys, so users see both what they typed wrong and
    what they meant. The offending VALUE is never echoed (R5a
    content-safety carries over from U1's parse-time posture).
    """
    unknown = sorted(set(table) - _ALLOWED_KEYS)
    if unknown:
        unknown_repr = ", ".join(repr(k) for k in unknown)
        allowed_repr = ", ".join(repr(k) for k in sorted(_ALLOWED_KEYS))
        error_exit_with_code(
            "pyproject-config-invalid",
            (
                f"[tool.protokit.lint] has unknown key(s): {unknown_repr}. "
                f"Allowed keys: {allowed_repr}."
            ),
        )


def _coerce_profile(value: Any) -> tuple[str, ...]:
    """Coerce ``profile`` to ``tuple[str, ...]`` per R15 + R3a/KTD-5.

    ``profile`` is the ONLY field that accepts BOTH a scalar string
    AND a list of strings (origin R15). All other list-typed fields
    are list-only. Strings are normalized at the input boundary
    (strip whitespace + lowercase) per the
    ``normalize-at-input-boundary`` learning.

    D6a (R7 / KTD-1): after ``.strip().lower()`` normalization, the
    buf-compatibility aliases declared in ``_PROFILE_ALIASES`` are
    resolved to their primary protokit-native names. This happens at
    the input boundary so downstream code (``LintProfile.compose`` and
    rule-pack profile-name matching) sees only primary names. Both
    pyproject and CLI input paths flow through this helper, so the
    alias resolution covers both surfaces with a single declaration.
    """
    if isinstance(value, str):
        normalized = value.strip().lower()
        return (_PROFILE_ALIASES.get(normalized, normalized),)
    if isinstance(value, list):
        if not value:
            error_exit_with_code(
                "pyproject-config-invalid",
                (
                    "[tool.protokit.lint] profile must not be empty; "
                    "at least one profile name is required."
                ),
            )
        for index, elem in enumerate(value):
            if not isinstance(elem, str):
                error_exit_with_code(
                    "pyproject-config-invalid",
                    (
                        f"[tool.protokit.lint] profile[{index}] must be "
                        f"a string; got {type(elem).__name__}."
                    ),
                )
        normalized_elements = [elem.strip().lower() for elem in value]
        return tuple(
            _PROFILE_ALIASES.get(normalized, normalized)
            for normalized in normalized_elements
        )
    error_exit_with_code(
        "pyproject-config-invalid",
        (
            f"[tool.protokit.lint] profile must be a string or list of "
            f"strings; got {type(value).__name__}."
        ),
    )


def _coerce_exclude(value: Any) -> tuple[str, ...]:
    """Coerce ``exclude`` to ``tuple[str, ...]`` per R3a/KTD-5 (list-only).

    Unlike :func:`_coerce_profile`, ``exclude`` rejects scalar input
    even when it would coerce cleanly — the contract is "list of
    glob patterns", not "string or list" (R15 explicitly distinguishes
    profile from exclude on this dimension).

    Elements are NOT lowercased (path patterns are case-sensitive on
    POSIX, and pathspec handles its own normalization for negation
    and trailing-slash semantics).
    """
    if not isinstance(value, list):
        error_exit_with_code(
            "pyproject-config-invalid",
            (
                f"[tool.protokit.lint] exclude must be a list of "
                f"strings; got {type(value).__name__}."
            ),
        )
    for index, elem in enumerate(value):
        # ``bool`` is a subclass of ``int`` (but NOT ``str``); the
        # isinstance check below is therefore tight without an
        # explicit bool guard.
        if not isinstance(elem, str):
            error_exit_with_code(
                "pyproject-config-invalid",
                (
                    f"[tool.protokit.lint] exclude[{index}] must be "
                    f"a string; got {type(elem).__name__}."
                ),
            )
    return tuple(value)


def _coerce_min_severity(value: Any) -> LintSeverity:
    """Coerce ``min_severity`` to ``LintSeverity`` per R3a + boundary-normalize.

    Accepts only string input matching one of the three severity
    levels (``"info"``, ``"warning"``, ``"error"``), case-insensitive
    with whitespace stripped at the boundary per the
    ``normalize-at-input-boundary`` learning. Mismatches name the
    valid values explicitly so the user sees the closed set.
    """
    if not isinstance(value, str):
        error_exit_with_code(
            "pyproject-config-invalid",
            (
                f"[tool.protokit.lint] min_severity must be a string; "
                f"got {type(value).__name__}."
            ),
        )
    normalized = value.strip().lower()
    try:
        return LintSeverity(normalized)
    except ValueError:
        pass
    valid = ", ".join(repr(s.value) for s in LintSeverity)
    error_exit_with_code(
        "pyproject-config-invalid",
        (
            f"[tool.protokit.lint] min_severity must be one of "
            f"{valid}; got {type(value).__name__!r}."
        ),
    )


def _coerce_max_warnings(value: Any) -> int:
    """Coerce ``max_warnings`` to ``int`` per R3a (non-negative).

    Explicitly rejects ``bool`` inputs even though ``bool`` is an
    ``int`` subclass in Python — accepting ``max_warnings = true``
    as ``1`` would be a surprising silent coercion that TOML users
    would not expect.

    Positive-form isinstance narrowing (F-10): structure the type
    check so mypy can narrow ``value`` to ``int`` for the remainder
    of the function without an explicit ``int(value)`` cast at the
    return statement. F-18 / R5a content-safety carries forward by
    naming only the *type* on negative-int input (never the raw
    integer value).
    """
    if not isinstance(value, int) or isinstance(value, bool):
        error_exit_with_code(
            "pyproject-config-invalid",
            (
                f"[tool.protokit.lint] max_warnings must be a "
                f"non-negative integer; got {type(value).__name__}."
            ),
        )
    if value < 0:
        error_exit_with_code(
            "pyproject-config-invalid",
            (
                "[tool.protokit.lint] max_warnings must be a "
                "non-negative integer; got a negative integer."
            ),
        )
    return value


def _coerce_format(value: Any) -> str:
    """Coerce ``format`` to lowercased string per R3a + boundary-normalize.

    Does NOT validate against the formatter registry — the registry
    is mutable across plugin loads, and ``error[lint-format-unavailable]``
    surfaces unknown formats at dispatch time. Schema validation here
    is purely type + normalization.
    """
    if not isinstance(value, str):
        error_exit_with_code(
            "pyproject-config-invalid",
            (
                f"[tool.protokit.lint] format must be a string; "
                f"got {type(value).__name__}."
            ),
        )
    return value.strip().lower()


def _coerce_severities(value: Any) -> dict[str, LintSeverity]:
    """Coerce ``severities`` to ``dict[str, LintSeverity]`` per R9a.

    The ``[tool.protokit.lint.severities]`` table is a flat
    rule_id-to-severity mapping (no nested rules-pack grouping in
    D6a). Validates:

    - Value is a TOML table (``dict``) — scalar / list inputs are
      hard-errors.
    - Each key is a non-empty string (TOML keys are always strings,
      but empty-string keys would silently no-op against rule_id
      lookups and are flagged here as a typo signal).
    - Each value coerces to ``LintSeverity`` via the same
      severity-string semantics as :func:`_coerce_min_severity`
      (case-insensitive, whitespace-stripped at the boundary).

    Empty table (``severities = {}``) is valid — explicit empty is
    indistinguishable from omitting the key, but the coercion
    accepts it so users can stage a configuration scaffold.

    Per the ``source-aware-error-messages`` learning, error messages
    name the offending rule_id (the dict KEY) via ``{rule_id!r}`` so
    users can locate the typo without re-reading their pyproject.
    Python's ``repr()`` escapes control characters and surrogate
    pairs to their ``\\xNN`` / ``\\uNNNN`` form, so embedding control
    chars in a TOML key cannot forge fake stderr lines or smuggle
    ANSI escapes through (R5a content-safety holds via repr's
    escaping, not by suppressing the key entirely).

    The rejected VALUE's content is never echoed — only its Python
    type name appears in error messages — so a TOML value like
    ``severities = {"foo" = "warn\\x1b[31mmagenta"}`` produces an
    error naming the key (``'foo'``) and the type (``str``), never
    the raw value bytes.
    """
    if not isinstance(value, dict):
        error_exit_with_code(
            "pyproject-config-invalid",
            (
                f"[tool.protokit.lint] severities must be a table; "
                f"got {type(value).__name__}."
            ),
        )
    result: dict[str, LintSeverity] = {}
    for rule_id, sev_value in value.items():
        # TOML guarantees keys are strings, but defensive isinstance
        # check covers the case where someone constructs the dict
        # programmatically (e.g., from_dict called from a test with
        # a hand-built dict) and accidentally passes a non-string key.
        if not isinstance(rule_id, str):
            error_exit_with_code(
                "pyproject-config-invalid",
                (
                    f"[tool.protokit.lint] severities key must be a "
                    f"string rule_id; got {type(rule_id).__name__}."
                ),
            )
        if not rule_id.strip():
            error_exit_with_code(
                "pyproject-config-invalid",
                (
                    "[tool.protokit.lint] severities key must be a "
                    "non-empty rule_id."
                ),
            )
        if not isinstance(sev_value, str):
            error_exit_with_code(
                "pyproject-config-invalid",
                (
                    f"[tool.protokit.lint] severities[{rule_id!r}] must "
                    f"be a string severity name; got "
                    f"{type(sev_value).__name__}."
                ),
            )
        # Normalize keys at the input boundary per the
        # ``normalize-at-input-boundary`` learning: rule_ids in
        # ``BUILTIN_PACKS`` are lowercase by ``@lint_rule`` convention,
        # so a user who writes ``"Naming/Snake-Case-Fields"`` in their
        # pyproject expects the override to apply to the canonical
        # rule. Without this normalization the override silently
        # no-ops (or in U9 produces an ``unloaded_rule`` warning
        # naming the user's wrong casing, not the canonical id).
        # Mirrors ``_coerce_profile``'s normalize-then-resolve order.
        normalized_rule_id = rule_id.strip().lower()
        normalized = sev_value.strip().lower()
        try:
            result[normalized_rule_id] = LintSeverity(normalized)
        except ValueError:
            valid = ", ".join(repr(s.value) for s in LintSeverity)
            error_exit_with_code(
                "pyproject-config-invalid",
                (
                    f"[tool.protokit.lint] severities[{rule_id!r}] must "
                    f"be one of {valid}; got a severity name outside "
                    f"the closed set."
                ),
            )
    return result


def _empty_severities() -> dict[str, LintSeverity]:
    """Module-level typed factory for the ``severities`` default.

    Used as ``dataclasses.field(default_factory=_empty_severities)``
    on ``ResolvedLintConfig.severities``. A typed factory makes the
    field's Mapping element types explicit to mypy across dataclasses
    stubs versions (the bare ``dict`` callable returns ``dict[Any, Any]``
    in some mypy inferences, which may or may not narrow cleanly to
    ``Mapping[str, LintSeverity]``).
    """
    return {}


def _coerce_no_builtin_rules(value: Any) -> bool:
    """Coerce ``no_builtin_rules`` to ``bool`` per R9c.

    TOML ``true`` / ``false`` only. String ``"true"`` is rejected
    explicitly — accepting it would surprise users who expect TOML
    type-strictness, and conflating it with the boolean would
    create a footgun for typos like ``"True"`` or ``"yes"`` that
    silently parse to truthy values in a less strict coercion path.
    """
    if not isinstance(value, bool):
        error_exit_with_code(
            "pyproject-config-invalid",
            (
                f"[tool.protokit.lint] no_builtin_rules must be a "
                f"boolean; got {type(value).__name__}. TOML treats "
                f"integers and booleans as distinct types; write "
                f"`true`/`false`, not `1`/`0` or `\"true\"`/`\"false\"`."
            ),
        )
    return value


@dataclass(frozen=True)
class ResolvedLintConfig:
    """Merged result of pyproject ``[tool.protokit.lint]`` + CLI + defaults.

    Produced by :meth:`from_dict` after R3 / R3a schema validation
    and R11-R14 precedence application. The CLI passes one of these
    to ``_main_impl``; subsequent D5 units consume specific fields
    (U3: ``exclude``; U4: ``min_severity_source`` + ``pyproject_min_severity``
    for the R20 relaxation messages).

    Source attribution semantics (R20 — only ``min_severity_source``
    is exposed for now, since it's the only attribution the D5
    runtime warnings rely on):

    - ``"cli"``:       The CLI flag was explicitly provided.
    - ``"pyproject"``: Pyproject set this key; CLI did not override.
    - ``"profile"``:   Neither CLI nor pyproject set this key; the
                       composed profile's intrinsic floor is in effect.
                       (U4 may transition ``"default"`` to ``"profile"``
                       at emission time when ``min_severity is None``.)
    - ``"default"``:   Neither CLI nor pyproject nor profile set
                       this key; the built-in default applies.

    Defaults:
    - ``profile`` defaults to ``("default",)`` (a 1-tuple of the
      built-in profile name) when neither CLI nor pyproject set it.
      Consumers can iterate ``resolved.profile`` for multi-profile
      composition via ``LintProfile.compose``.
    - ``format`` defaults to ``"human"``. Other fields default to
      ``None``, signalling "no override / use built-in semantics".

    Frozen + tuple-snapshotted: list-valued constructor arguments
    are coerced to tuples in ``__post_init__`` per the
    ``frozen-dataclass-mutable-fields-need-post-init-snapshot`` learning,
    so callers can pass lists without breaking immutability guarantees.
    """

    profile: tuple[str, ...] = ("default",)
    exclude: tuple[str, ...] = ()
    min_severity: LintSeverity | None = None
    max_warnings: int | None = None
    format: str = "human"
    min_severity_source: ConfigSource = "default"
    pyproject_min_severity: LintSeverity | None = None
    exclude_source: ExcludeSource = "default"
    #: D6a R9a — per-rule severity overrides resolved from
    #: ``[tool.protokit.lint.severities]``. Empty dict when no
    #: overrides are configured. CLI side-channel for this knob is
    #: deferred to a later delivery (D7+); D6a is pyproject-only.
    #: ``__post_init__`` wraps the input in ``MappingProxyType(dict(...))``
    #: per the ``frozen-dataclass-mutable-fields-need-post-init-snapshot``
    #: learning so a caller passing a mutable dict cannot leak mutations
    #: through the frozen wrapper.
    severities: Mapping[str, LintSeverity] = dataclasses.field(
        default_factory=_empty_severities,
    )
    #: D6a R9c — when ``True``, ``cli.py`` skips the BUILTIN_PACKS
    #: auto-load loop. Resolved from either ``--no-builtin-rules`` CLI
    #: flag OR ``[tool.protokit.lint] no_builtin_rules = true``; CLI
    #: takes precedence per the standard CLI > pyproject precedence
    #: applied to the other knobs.
    no_builtin_rules: bool = False

    def __post_init__(self) -> None:
        # Tuple-snapshot list inputs per the
        # ``frozen-dataclass-mutable-fields-need-post-init-snapshot`` learning.
        # Without this, a caller passing ``profile=["a", "b"]`` would
        # expose the original list through the frozen wrapper and
        # mutations on it would leak through to the dataclass.
        object.__setattr__(self, "profile", tuple(self.profile))
        object.__setattr__(self, "exclude", tuple(self.exclude))
        # Mapping-snapshot per the same learning: ``severities`` field's
        # ``default_factory=dict`` returns a fresh mutable dict; wrap in
        # ``MappingProxyType`` over a defensive ``dict()`` copy so callers
        # that pass an external dict cannot leak mutations through and
        # the frozen-dataclass contract holds for the new field.
        object.__setattr__(
            self,
            "severities",
            MappingProxyType(dict(self.severities)),
        )
        # Construction-time invariant: when ``exclude`` is non-empty,
        # ``exclude_source`` MUST be one of "cli" / "pyproject" / "both"
        # so ``all_files_excluded_message`` can attribute the patterns.
        # The default value ``"default"`` is only valid for an empty
        # ``exclude`` tuple. Catches programmatic misuse where a caller
        # constructs ``ResolvedLintConfig(exclude=(...))`` without
        # specifying ``exclude_source``, or where
        # ``dataclasses.replace(resolved, exclude=new)`` is used without
        # also updating ``exclude_source``. Without this guard, the
        # R20-attributed message silently degrades to an unattributed
        # fallback.
        if self.exclude and self.exclude_source == "default":
            raise ValueError(
                "ResolvedLintConfig.exclude_source must be set to "
                "'cli', 'pyproject', or 'both' when exclude is "
                "non-empty (got 'default').",
            )

    def relaxation_message(
        self, composed_floor: LintSeverity,
    ) -> str | None:
        """Return the R20 relaxation message, or ``None`` when no relaxation.

        Three R20 message templates pinned at the ``ResolvedLintConfig``
        boundary per the
        ``cross-format-enum-string-parity-2026-05-08`` learning, so
        every CLI/formatter consumer emits identical text:

        - **CLI-source** (``min_severity_source == "cli"`` with no
          pyproject contribution):
          ``--min-severity=warning relaxes profile floor from error
          to warning``
        - **Pyproject-source** (``min_severity_source == "pyproject"``):
          ``[tool.protokit.lint] min_severity=warning relaxes profile
          floor from error to warning``
        - **Both** (``min_severity_source == "cli"`` AND
          ``pyproject_min_severity is not None``):
          ``--min-severity=warning relaxes profile floor from error
          to warning (overriding pyproject min_severity=info)``

        Returns ``None`` when:

        - ``self.min_severity is None`` (no override at all);
        - ``SEVERITY_RANK[self.min_severity] >= SEVERITY_RANK[
          composed_floor]`` (the resolved severity is at or above the
          floor, so no relaxation occurred — pyproject relaxed but
          CLI restored, or the override matched the floor exactly).

        Args:
            composed_floor: The composed profile's intrinsic
                ``min_severity`` BEFORE the override was applied.
                Callers in ``cli.py`` capture this just before calling
                ``dataclasses.replace(composed_profile, min_severity=
                override_severity)``.

        Returns:
            The R20-attributed relaxation message, or ``None``.
        """
        if self.min_severity is None:
            return None
        if SEVERITY_RANK[self.min_severity] >= SEVERITY_RANK[composed_floor]:
            return None
        floor_name = composed_floor.value
        resolved_name = self.min_severity.value
        if self.min_severity_source == "cli":
            if self.pyproject_min_severity is not None:
                pyp_name = self.pyproject_min_severity.value
                return (
                    f"--min-severity={resolved_name} relaxes profile "
                    f"floor from {floor_name} to {resolved_name} "
                    f"(overriding pyproject min_severity={pyp_name})"
                )
            return (
                f"--min-severity={resolved_name} relaxes profile "
                f"floor from {floor_name} to {resolved_name}"
            )
        if self.min_severity_source == "pyproject":
            return (
                f"[tool.protokit.lint] min_severity={resolved_name} "
                f"relaxes profile floor from {floor_name} to "
                f"{resolved_name}"
            )
        # "profile" / "default" cannot reach a relaxation message
        # (no override is set when source is "default"; "profile"
        # is reserved for future U5+ emission code that may emit
        # different message branches).
        return None

    def all_files_excluded_message(self, file_count: int) -> str:
        """Return the R20-attributed message for the all_files_excluded warning.

        Pins the source-aware message templates at the
        ``ResolvedLintConfig`` boundary per the
        ``cross-format-enum-string-parity-2026-05-08`` learning AND
        the
        ``source-aware-error-messages-multi-source-resolved-value-2026-05-11``
        learning. The three message branches mirror the relaxation-message
        structure:

        - **CLI-source** (``exclude_source == "cli"``):
          ``all N input file(s) excluded by --exclude patterns:
          vendor/**``
        - **Pyproject-source** (``exclude_source == "pyproject"``):
          ``all N input file(s) excluded by [tool.protokit.lint]
          exclude patterns: vendor/**``
        - **Both** (``exclude_source == "both"``):
          ``all N input file(s) excluded by --exclude and
          [tool.protokit.lint] exclude patterns:
          vendor/**, third_party/**``

        Per KTD-9, individual patterns are passed through
        ``_safe_for_stderr`` before joining so a pattern with
        embedded control characters cannot forge a fake stderr line.

        The ``exclude_source == "default"`` case is rejected at
        construction time by ``__post_init__`` when ``exclude`` is
        non-empty, so this method's branches are exhaustive for any
        ``ResolvedLintConfig`` that can reach the
        ``all_files_excluded`` emit site (which is guarded by
        ``if resolved.exclude:`` in the CLI).

        Args:
            file_count: The number of input files that were excluded
                (i.e., ``len(result.root_files)`` at the call site).

        Returns:
            The R20-attributed message string.
        """
        safe_patterns = ", ".join(
            _safe_for_stderr(p) for p in self.exclude
        )
        source_desc = _EXCLUDE_SOURCE_DESC[self.exclude_source]
        return (
            f"all {file_count} input file(s) excluded by {source_desc} "
            f"patterns: {safe_patterns}"
        )

    @classmethod
    def from_dict(
        cls,
        table: Mapping[str, Any] | None,
        cli_overrides: Mapping[str, Any],
    ) -> ResolvedLintConfig:
        """Validate the pyproject table and merge with CLI overrides.

        Validation phase (single-pass per KTD-2):

        - R3 (unknown keys): :func:`_validate_table_keys` hard-errors
          on any key outside R2's allowlist.
        - R3a / KTD-5 (type mismatches): per-field ``_coerce_*``
          helpers validate scalar-vs-list shape, element type, and
          value range; mismatches exit 2 with
          ``error[lint-pyproject-config-invalid]:``.

        Precedence (R11-R14, per the plan's decision matrix):

        - ``profile``:      CLI replaces pyproject entirely. Empty
                            CLI override (``None``) defers to
                            pyproject, then to ``("default",)``.
        - ``exclude``:      CLI appends to pyproject. A
                            ``--no-exclude`` sentinel (CLI override
                            set to the empty tuple by the caller)
                            clears BOTH CLI and pyproject. Default
                            is the empty tuple.
        - ``min_severity``: CLI replaces pyproject. Source attribution
                            (``min_severity_source``) records which
                            tier won, so U4 can emit the right R20
                            relaxation message branch.
        - ``max_warnings``: CLI replaces pyproject; otherwise ``None``.
        - ``format``:       CLI replaces pyproject; otherwise ``"human"``.

        ``cli_overrides`` shape — each key is optional and ``None``
        means "CLI did not explicitly supply this key" (typically
        because the click default applied and the user did not type
        the flag):

        - ``"profile"``:          ``tuple[str, ...] | None``
        - ``"exclude"``:          ``tuple[str, ...] | None`` — the
                                  empty tuple represents ``--no-exclude``
        - ``"min_severity"``:     ``LintSeverity | None``
        - ``"max_warnings"``:     ``int | None``
        - ``"format"``:           ``str | None``
        - ``"no_builtin_rules"``: ``bool | None`` — D6a R9c CLI side;
                                  the actual CLI flag wiring lands in
                                  D6a U9. ``None`` means "CLI did not
                                  set this flag"; the pyproject value
                                  (or default ``False``) wins.

        Intentionally absent: ``"severities"``. D6a U2 ships the
        pyproject-only parsing surface for R9a; no CLI side-channel
        exists yet. If a future delivery wires a CLI severities
        override, the key must be added to this shape table AND
        ``from_dict`` updated to read it — otherwise the override
        is silently dropped.

        Returns:
            A frozen ``ResolvedLintConfig`` with defaults applied
            and per-key source attribution computed.

        Raises:
            SystemExit: Exit code 2 via ``error_exit_with_code(
            "pyproject-config-invalid", ...)`` for any R3 / R3a /
            KTD-5 violation.
        """
        validated: dict[str, Any] = {}
        if table is not None:
            _validate_table_keys(table)
            for key, value in table.items():
                if key == "profile":
                    validated[key] = _coerce_profile(value)
                elif key == "exclude":
                    validated[key] = _coerce_exclude(value)
                elif key == "min_severity":
                    validated[key] = _coerce_min_severity(value)
                elif key == "max_warnings":
                    validated[key] = _coerce_max_warnings(value)
                elif key == "format":
                    validated[key] = _coerce_format(value)
                elif key == "severities":
                    validated[key] = _coerce_severities(value)
                elif key == "no_builtin_rules":
                    validated[key] = _coerce_no_builtin_rules(value)
                # Unreachable: `_validate_table_keys` already exited
                # on any key not in `_ALLOWED_KEYS`. The else-branch
                # is omitted intentionally.

        # profile: CLI replaces pyproject; default ("default",).
        cli_profile = cli_overrides.get("profile")
        if cli_profile is not None:
            resolved_profile: tuple[str, ...] = tuple(cli_profile)
        elif "profile" in validated:
            resolved_profile = validated["profile"]
        else:
            resolved_profile = ("default",)

        # exclude: CLI APPENDS to pyproject. --no-exclude (signalled
        # by an empty cli_overrides["exclude"] tuple) clears BOTH.
        # None means "no --exclude flags were passed; use pyproject".
        cli_exclude = cli_overrides.get("exclude")
        pyproject_exclude = validated.get("exclude", ())
        exclude_source: ExcludeSource
        if cli_exclude is None:
            # No CLI --exclude flag; pyproject patterns (if any) drive.
            resolved_exclude: tuple[str, ...] = pyproject_exclude
            exclude_source = (
                "pyproject" if pyproject_exclude else "default"
            )
        elif len(cli_exclude) == 0:
            # --no-exclude semantics: clear pyproject too. The user
            # explicitly asked for "no exclude"; attribute the empty
            # result to "default" since neither CLI patterns nor
            # pyproject patterns ended up applying.
            resolved_exclude = ()
            exclude_source = "default"
        else:
            # CLI patterns appended to pyproject patterns.
            resolved_exclude = pyproject_exclude + tuple(cli_exclude)
            exclude_source = "both" if pyproject_exclude else "cli"

        # min_severity: CLI replaces pyproject; track source for R20.
        cli_min_sev = cli_overrides.get("min_severity")
        pyproject_min_sev = validated.get("min_severity")
        resolved_min_sev: LintSeverity | None
        min_sev_source: ConfigSource
        if cli_min_sev is not None:
            resolved_min_sev = cli_min_sev
            min_sev_source = "cli"
        elif pyproject_min_sev is not None:
            resolved_min_sev = pyproject_min_sev
            min_sev_source = "pyproject"
        else:
            resolved_min_sev = None
            # ``"profile"`` source state in ``ConfigSource`` is reserved
            # for future emission code that may want to attribute a
            # message to the composed profile's intrinsic floor (rather
            # than to a CLI/pyproject override). U4 shipped the R20
            # relaxation message without using the ``"profile"`` source
            # — when no override is set, ``relaxation_message`` returns
            # ``None``. ``"default"`` is correct here.
            min_sev_source = "default"

        # max_warnings: CLI replaces pyproject.
        cli_max = cli_overrides.get("max_warnings")
        resolved_max = (
            cli_max if cli_max is not None
            else validated.get("max_warnings")
        )

        # format: CLI replaces pyproject; default "human".
        cli_fmt = cli_overrides.get("format")
        resolved_fmt: str
        if cli_fmt is not None:
            resolved_fmt = cli_fmt
        elif "format" in validated:
            resolved_fmt = validated["format"]
        else:
            resolved_fmt = "human"

        # severities (R9a): pyproject-only in D6a — no CLI side-channel
        # yet. Defaults to empty dict when the table key is absent.
        # CLI's user-wins post-compose overlay (KTD-2) is applied in
        # cli.py around the LintProfile.compose call, NOT here; this
        # method only resolves the input-boundary value.
        #
        # Guard against silent-drop: if a future delivery wires a CLI
        # severities override without updating this method, the
        # override would be silently ignored (the dict key exists but
        # is never read). Hard-fail at the boundary so the integration
        # bug surfaces immediately rather than in user-visible
        # production behavior.
        if "severities" in cli_overrides:
            raise NotImplementedError(
                "cli_overrides['severities'] is not yet wired into "
                "ResolvedLintConfig.from_dict — D6a U2 ships pyproject "
                "parsing only. Add the precedence branch here before "
                "exposing a CLI severities override.",
            )
        resolved_severities: Mapping[str, LintSeverity] = validated.get(
            "severities", {},
        )

        # no_builtin_rules (R9c): CLI replaces pyproject. The CLI flag's
        # ``ParameterSource`` detection happens in cli.py — by the time
        # ``from_dict`` is called, ``cli_overrides["no_builtin_rules"]``
        # is either ``True``/``False`` (the user explicitly typed the
        # flag) or absent / ``None`` (defer to pyproject, then to
        # ``False``).
        #
        # Strict isinstance check rather than ``bool(...)`` coercion:
        # the pyproject path hard-errors on non-bool inputs via
        # ``_coerce_no_builtin_rules``, and asymmetric strictness
        # between CLI and pyproject would silently accept falsy
        # non-bools (``[]``, ``0``, ``""``) from a programmatic
        # ``from_dict`` caller. The expected CLI shape is
        # ``True | False | None`` (None meaning "CLI didn't set this").
        cli_no_builtin = cli_overrides.get("no_builtin_rules")
        resolved_no_builtin: bool
        if cli_no_builtin is None:
            resolved_no_builtin = validated.get("no_builtin_rules", False)
        elif isinstance(cli_no_builtin, bool):
            resolved_no_builtin = cli_no_builtin
        else:
            raise TypeError(
                "cli_overrides['no_builtin_rules'] must be bool or None; "
                f"got {type(cli_no_builtin).__name__}. Click's is_flag "
                "delivers Python bools by default — check the CLI wiring "
                "in cli.py if this fires.",
            )

        return cls(
            profile=resolved_profile,
            exclude=resolved_exclude,
            min_severity=resolved_min_sev,
            max_warnings=resolved_max,
            format=resolved_fmt,
            min_severity_source=min_sev_source,
            pyproject_min_severity=pyproject_min_sev,
            exclude_source=exclude_source,
            severities=resolved_severities,
            no_builtin_rules=resolved_no_builtin,
        )


# ---------------------------------------------------------------------------
# pathspec compilation (D5 U3: R7-R10, R13, R13a)
# ---------------------------------------------------------------------------


def compile_exclude_patterns(
    patterns: Iterable[str],
) -> pathspec.PathSpec:  # type: ignore[type-arg]
    """Compile gitignore-style exclude patterns to a ``pathspec.PathSpec``.

    Wraps ``pathspec.PathSpec.from_lines("gitignore", patterns)`` so
    the CLI's `--exclude` flag and pyproject ``[tool.protokit.lint]
    exclude`` entries share a single compilation path. The returned
    spec is used to filter ``compile_result.root_files`` post-compile
    and pre-``engine.run`` (per plan U3 approach).

    The current call site (``protokit.schema.lint.cli`` U3 filter
    block) guards on ``if resolved.exclude:`` before calling, so the
    empty-pattern path is not exercised in production. An empty
    iterable would return an empty PathSpec that matches nothing,
    but callers should prefer the truthiness guard on a tuple over
    calling with an empty input.

    Args:
        patterns: An iterable of gitignore-style glob patterns. Each
            pattern is consumed once; the iterable is materialized
            inside pathspec. Negation patterns (``!path``) are
            honored per gitignore semantics.

    Returns:
        A ``pathspec.PathSpec`` whose ``match_file(path)`` returns
        ``True`` when ``path`` should be EXCLUDED.

    Raises:
        SystemExit: Exit code 2 via ``error_exit_with_code(
        "exclude-pattern-invalid", ...)`` when pathspec rejects any
        pattern. The error code is distinct from
        ``pyproject-config-invalid`` because exclude patterns can
        come from CLI flags as well as pyproject — reusing the
        pyproject-specific code would mis-attribute the source. Per
        KTD-9, the rejected pattern is newline-sanitized before
        being interpolated into the stderr message.
    """
    # pathspec is highly permissive about gitignore-shaped input —
    # most invalid-looking patterns parse silently and just match
    # nothing. The catch-all here is defense-in-depth: when pathspec
    # DOES raise (a rare GitWildMatchPatternError, or any future
    # exception type), route the failure through the stable
    # ``error[lint-exclude-pattern-invalid]:`` prefix rather than
    # letting an uncaught traceback escape. Per KTD-9, the exception
    # message body is newline-sanitized before interpolation so a
    # crafted pattern with embedded newlines cannot forge a fake
    # second stderr line.
    try:
        return pathspec.PathSpec.from_lines("gitignore", patterns)
    except Exception as exc:  # noqa: BLE001 - intentional broad catch
        error_exit_with_code(
            "exclude-pattern-invalid",
            (
                f"invalid exclude pattern "
                f"({type(exc).__name__}): {_safe_for_stderr(exc)}"
            ),
        )
