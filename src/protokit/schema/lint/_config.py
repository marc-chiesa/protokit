"""Pyproject `[tool.protokit.lint]` config loader.

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

**Security posture**:

- Walk-up termination uses ``(parent / ".git").exists()`` to cover both
  ``.git`` directories AND ``.git`` files (git worktrees, submodules).
  The ``.git`` path is checked for existence only; its contents (the
  ``gitdir: ...`` pointer in worktree ``.git`` files) are NEVER read,
  parsed, or followed.
- All shadow paths (missing file, unreadable, table-absent, invalid
  TOML) produce exit 2 via ``error_exit_with_code("pyproject-config-load",
  ...)`` with newline-sanitized stderr.
- ``tomllib.TOMLDecodeError`` messages may include raw file bytes per
  cpython issue; the loader replaces the raw error message with the
  structured form ``"TOML parse error at {path}:{line}:{col}"`` using
  only safe exception attributes.
- Triple-arm exception guards ``(SystemExit, KeyboardInterrupt,
  Exception)`` around ``tomllib`` calls so a malicious config body
  cannot bypass the error surface via ``BaseException`` subclasses.
  ``KeyboardInterrupt`` is caught and re-raised so the user's SIGINT
  propagates to Python's default handler (exit 130) rather than being
  absorbed.
"""

from __future__ import annotations

import dataclasses
import re
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, NamedTuple, cast

import pathspec

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from protokit.schema.lint._cli_utils import _safe_for_stderr, error_exit_with_code
from protokit.schema.lint._custom_rules import synthetic_rule_ids
from protokit.schema.lint.model import (
    SEVERITY_RANK,
    ElementKind,
    LintRuntimeWarning,
    LintSeverity,
)

# Per-key source attribution for ResolvedLintConfig message branches.
# Used for `min_severity_source`: cli vs pyproject is mutually exclusive
# (CLI replaces pyproject); a "both" message branch is encoded by
# `min_severity_source="cli"` + `pyproject_min_severity is not None`.
#
# - "cli":       CLI flag (--profile/--min-severity/etc) explicitly provided.
# - "pyproject": Pyproject set this key; CLI did not override.
# - "profile":   Neither CLI nor pyproject set this key; the composed
#                profile's intrinsic floor is in effect. Emission code may
#                transition "default" to "profile" at emission time when
#                min_severity is None.
# - "default":   Neither CLI nor pyproject nor profile set this key.
ConfigSource = Literal["cli", "pyproject", "profile", "default"]

# Exclude-specific source attribution for `all_files_excluded` message
# branches. Unlike `min_severity` (where CLI replaces pyproject),
# `exclude` APPENDS CLI patterns to pyproject patterns, so the "both"
# case is structurally distinct — both sources CONTRIBUTE patterns
# rather than one overriding the other.
#
# - "cli":       CLI `--exclude` patterns only (no pyproject exclude).
# - "pyproject": Pyproject `exclude` patterns only (no CLI flags).
# - "both":      Both CLI AND pyproject contributed patterns.
# - "default":   No exclude configured (resolved.exclude is the empty tuple).
ExcludeSource = Literal["cli", "pyproject", "both", "default"]

# Source-attribution descriptors for the ``all_files_excluded``
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

    Resolution order:

    1. If ``no_config`` is True, return ``None`` immediately (bypass).
    2. If ``explicit_path`` is provided, load it in **strict mode**:
       all shadow paths (missing file, unreadable, missing table,
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
        "pyproject-config-load", ...)`` for any shadow path or
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
# Walk-up discovery
# ---------------------------------------------------------------------------


def _walk_up_find_pyproject(start: Path) -> Path | None:
    """Walk up from ``start`` looking for ``pyproject.toml``; terminate at ``.git``.

    The ``.git`` boundary check uses ``(parent / ".git").exists()`` so
    both ``.git`` directories (standard checkouts) AND ``.git`` files
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
            # `.git` content is never read — existence check only.
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
# Loading: explicit path (strict mode) and walk-up path (silent fallback)
# ---------------------------------------------------------------------------


def _load_explicit(path: Path) -> dict[str, Any]:
    """Load ``--config PATH`` in strict mode (table-absent is an error)."""
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
    # Walk-up: table-absent returns None silently (run with built-in
    # defaults). Only parse-time errors are hard.
    return _extract_lint_table(table)


def _read_and_parse(
    path: Path, *, source_label: str = "--config path",
) -> dict[str, Any]:
    """Read bytes from ``path`` and parse as TOML; produce shadow-path errors.

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
    """Decode and parse TOML bytes; produce content-safe error messages.

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
        # absorbing the interrupt signal.
        raise
    except UnicodeDecodeError:
        # Not valid UTF-8 (invalid-input case before TOML-level parse).
        # Don't echo the raw bytes/position — just name the file.
        error_exit_with_code(
            "pyproject-config-load",
            f"TOML parse error in {_safe_for_stderr(path)}: not valid UTF-8",
        )
    except tomllib.TOMLDecodeError as exc:
        # Content-safety: tomllib.TOMLDecodeError.args[0] may include
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
# Stderr-safe rendering helpers (newline sanitization)
# `_safe_for_stderr` is consolidated in `protokit.schema.lint._cli_utils`
# so the canonical implementation is shared with `_safe_module_name`
# (which now delegates to it). The import is at the top of this module
# alongside `error_exit_with_code`. Sanitization scope covers all ASCII
# control characters (\n, \r, \x00, \x1b, \t, etc.) — see the helper's
# docstring for the threat model.


# ---------------------------------------------------------------------------
# Schema validation + precedence
# ---------------------------------------------------------------------------

#: Top-level keys allowed inside ``[tool.protokit.lint]`` (allowlist).
#: Anything else surfaces via :func:`_validate_table_keys` as an error,
#: including nested tables like ``[tool.protokit.lint.rules.foo]`` whose
#: TOP-LEVEL key (``"rules"``) is not in this set. The contract remains
#: "top-level allowlist only".
#:
#: Note: ``schema_version`` is wire-format OUTPUT only — it is
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
        "custom_annotation_rules",
        # ``disabled_rules`` / ``enabled_rules`` lists drive the R9b
        # per-rule disable surface. Both accept the same R9b rule_id
        # format (``_R9B_RULE_ID_REGEX``); cross-list and cross-tier
        # interactions resolve via polarity-first / tier-second
        # precedence in ``ResolvedLintConfig.from_dict``.
        "disabled_rules",
        "enabled_rules",
    },
)


#: Regex contract for ``[[custom_annotation_rules]].rule_suffix``.
#: Anchored, lowercase-ASCII kebab-case, must start with a letter, no
#: leading/trailing/double hyphens. Underscores are forbidden so synthetic
#: rule_ids stay consistent with the project's ``<category>/<short-name>``
#: lowercase-kebab convention (every built-in rule_id today obeys this
#: shape).
_CUSTOM_RULE_SUFFIX_REGEX: re.Pattern[str] = re.compile(
    r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$",
)

#: Regex contract for entries in the R9b per-rule disable surface:
#: ``disabled_rules`` / ``enabled_rules`` (and their CLI overrides
#: ``--disable-rule`` / ``--enable-rule``). Three shapes accepted:
#:
#: - Canonical ``pack/rule-suffix`` (e.g., ``naming/snake-case-fields``,
#:   ``options/deprecated-field-must-have-replacement-comment``).
#: - Bare custom ``custom/<suffix>`` (e.g., ``custom/audit-required``)
#:   — triggers multi-kind prefix expansion at the config-resolution
#:   layer when the suffix matches a declared custom annotation rule.
#: - Mangled custom ``custom/<suffix>__<kind>`` (e.g.,
#:   ``custom/audit-required__method``,
#:   ``custom/audit-required__enum_value``) — per-kind disable bypasses
#:   the bare-prefix expansion.
#:
#: Distinct from :data:`_CUSTOM_RULE_SUFFIX_REGEX` (which rejects
#: underscores per the kebab-case rule_suffix contract): R9b directive
#: entries MUST accept the ``__`` separator + underscore-bearing kind
#: names (``enum_value``) emitted by ``synthetic_rule_ids()`` at
#: ``_custom_rules.py:507-511``. Mixing the two regexes would cause
#: ``disabled_rules = ["custom/audit-required__enum_value"]`` to
#: silently reject a legitimate per-kind disable.
_R9B_RULE_ID_REGEX: re.Pattern[str] = re.compile(
    r"^[a-z][a-z0-9]*(-[a-z0-9]+)*\/"
    r"[a-z][a-z0-9]*(-[a-z0-9]+)*"
    r"(__[a-z]+(_[a-z]+)*)?$",
)

#: Allowed lowercase ElementKind values for the ``element_kinds`` array
#: entry. Pyproject TOML uses lowercase identifiers ("field", "method", ...)
#: which map to ``ElementKind`` via ``ElementKind(value)``.
_VALID_ELEMENT_KIND_NAMES: frozenset[str] = frozenset(
    kind.value for kind in ElementKind
)

#: Buf-compatibility profile aliases resolved at the
#: ``_coerce_profile`` input boundary (per the
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
    """Hard-error on any key outside the top-level allowlist.

    Single-pass posture: nested tables like
    ``[tool.protokit.lint.rules.foo]`` surface as the top-level
    unknown key ``"rules"``, not the dotted path. A future revision
    may extend to dotted-path messages when nested tables become
    first-class.

    Error message names the unknown top-level key(s) AND the
    recognized keys, so users see both what they typed wrong and
    what they meant. The offending VALUE is never echoed (content-safety
    carries over from the parse-time posture).
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
    """Coerce ``profile`` to ``tuple[str, ...]``.

    ``profile`` is the ONLY field that accepts BOTH a scalar string
    AND a list of strings. All other list-typed fields are list-only.
    Strings are normalized at the input boundary (strip whitespace +
    lowercase) per the ``normalize-at-input-boundary`` learning.

    After ``.strip().lower()`` normalization, the buf-compatibility
    aliases declared in ``_PROFILE_ALIASES`` are resolved to their
    primary protokit-native names. This happens at the input boundary
    so downstream code (``LintProfile.compose`` and rule-pack
    profile-name matching) sees only primary names. Both pyproject
    and CLI input paths flow through this helper, so the alias
    resolution covers both surfaces with a single declaration.
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
    """Coerce ``exclude`` to ``tuple[str, ...]`` (list-only).

    Unlike :func:`_coerce_profile`, ``exclude`` rejects scalar input
    even when it would coerce cleanly — the contract is "list of
    glob patterns", not "string or list" (the schema explicitly
    distinguishes profile from exclude on this dimension).

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
    """Coerce ``min_severity`` to ``LintSeverity`` with boundary normalization.

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
            f"{valid}; got a severity name outside the closed set."
        ),
    )


def _coerce_max_warnings(value: Any) -> int:
    """Coerce ``max_warnings`` to ``int`` (non-negative).

    Explicitly rejects ``bool`` inputs even though ``bool`` is an
    ``int`` subclass in Python — accepting ``max_warnings = true``
    as ``1`` would be a surprising silent coercion that TOML users
    would not expect.

    Positive-form isinstance narrowing: structure the type check so
    mypy can narrow ``value`` to ``int`` for the remainder of the
    function without an explicit ``int(value)`` cast at the return
    statement. Content-safety carries forward by naming only the
    *type* on negative-int input (never the raw integer value).
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
    """Coerce ``format`` to lowercased string with boundary normalization.

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


class _CoercedSeverities(NamedTuple):
    """Two-part return shape for :func:`_coerce_severities`.

    The ``"off"`` value is intercepted at the coercion layer BEFORE
    ``LintSeverity(normalized)`` construction (per the
    ``semantic-category-conflation-accepted-tradeoff-literal-widening``
    learning). ``LintSeverity`` stays a closed 3-member enum; the
    sentinel is propagated to the disable layer via the second tuple
    member.

    Attributes:
        severities: The non-``off`` per-rule severity overrides as
            ``dict[str, LintSeverity]``. Keys normalized to lowercase
            for canonical-form lookup.
        off_rule_ids: Frozen set of normalized (lowercase) rule_ids
            whose ``[severities]`` value was the sentinel ``"off"``.
            Merged into the unified ``ResolvedLintConfig.disabled_rules``
            by ``from_dict`` per the sentinel propagation contract.
    """

    severities: Mapping[str, LintSeverity]
    off_rule_ids: frozenset[str]


def _coerce_severities(value: Any) -> _CoercedSeverities:
    """Coerce ``severities`` to ``_CoercedSeverities``.

    The ``[tool.protokit.lint.severities]`` table is a flat
    rule_id-to-severity mapping (no nested rules-pack grouping).
    Validates:

    - Value is a TOML table (``dict``) — scalar / list inputs are
      hard-errors.
    - Each key is a non-empty string (TOML keys are always strings,
      but empty-string keys would silently no-op against rule_id
      lookups and are flagged here as a typo signal).
    - Each value coerces to ``LintSeverity`` via the same
      severity-string semantics as :func:`_coerce_min_severity`
      (case-insensitive, whitespace-stripped at the boundary). The
      ``"off"`` value is intercepted before ``LintSeverity()``
      construction; matching rule_ids accumulate in ``off_rule_ids``
      and are NOT written to the ``severities`` dict (so
      ``LintSeverity`` stays a closed 3-member enum).

    Empty table (``severities = {}``) is valid — explicit empty is
    indistinguishable from omitting the key, but the coercion
    accepts it so users can stage a configuration scaffold.

    Per the ``source-aware-error-messages`` learning, error messages
    name the offending rule_id (the dict KEY) via ``{rule_id!r}`` so
    users can locate the typo without re-reading their pyproject.
    Python's ``repr()`` escapes control characters and surrogate
    pairs to their ``\\xNN`` / ``\\uNNNN`` form, so embedding control
    chars in a TOML key cannot forge fake stderr lines or smuggle
    ANSI escapes through (content-safety holds via repr's escaping,
    not by suppressing the key entirely).

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
    off_rule_ids: set[str] = set()
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
        # no-ops (or produces an ``unloaded_rule`` warning naming the
        # user's wrong casing, not the canonical id).
        # Mirrors ``_coerce_profile``'s normalize-then-resolve order.
        normalized_rule_id = rule_id.strip().lower()
        normalized = sev_value.strip().lower()
        # Intercept ``"off"`` BEFORE constructing LintSeverity. The
        # matching rule_id is propagated to the disable layer via
        # ``off_rule_ids`` and NOT written into the severities dict —
        # preserving the closed 3-member enum and the SARIF formatter
        # ``assert_never`` wire-safety invariant.
        if normalized == "off":
            off_rule_ids.add(normalized_rule_id)
            continue
        try:
            result[normalized_rule_id] = LintSeverity(normalized)
        except ValueError:
            valid = ", ".join(repr(s.value) for s in LintSeverity)
            # The "valid values" message advertises the closed enum
            # names PLUS the ``"off"`` sentinel so the user discovers
            # the disable mechanism from the error without needing to
            # read the CHANGELOG.
            error_exit_with_code(
                "pyproject-config-invalid",
                (
                    f"[tool.protokit.lint] severities[{rule_id!r}] must "
                    f"be one of {valid} or 'off' to disable the rule; "
                    f"got a severity name outside the closed set."
                ),
            )
    return _CoercedSeverities(
        severities=result, off_rule_ids=frozenset(off_rule_ids),
    )


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


def _empty_rule_id_set() -> frozenset[str]:
    """Typed factory for the R9b ``disabled_rules`` / ``enabled_rules`` defaults.

    Used as ``dataclasses.field(default_factory=_empty_rule_id_set)``
    on ``ResolvedLintConfig.disabled_rules`` and ``enabled_rules`` so
    mypy narrows the field type to ``frozenset[str]`` rather than the
    bare ``frozenset`` callable's inferred ``frozenset[Any]``. Mirrors
    the :func:`_empty_severities` pattern.
    """
    return frozenset()


def _empty_runtime_warnings() -> tuple[LintRuntimeWarning, ...]:
    """Typed factory for ``ResolvedLintConfig.runtime_warnings`` default.

    ``contradictory_disable_config`` warnings produced inside
    ``from_dict`` are accumulated on the resolved config so the CLI
    can append them to the final ``LintReport.runtime_warnings``
    tuple. The empty-tuple default keeps the "no contradictions /
    nothing to emit" path zero-allocation.
    """
    return ()


def _coerce_r9b_rule_id_list(
    value: Any,
    *,
    error_label: str,
    error_code: str = "pyproject-config-invalid",
) -> frozenset[str]:
    """Coerce an R9b rule_id list (pyproject ``disabled_rules`` /
    ``enabled_rules`` OR CLI ``--disable-rule`` / ``--enable-rule``
    tuple-of-strings) into a frozen set of normalized canonical ids.

    Shared implementation for both pyproject keys AND their CLI
    overrides under the symmetric-coercion-strictness principle for
    multi-source field resolvers: same strictness on both sides so
    the CLI cannot smuggle in a malformed rule_id that pyproject
    would reject.

    Validation:

    - List-only (no scalar coercion); mirrors :func:`_coerce_exclude`
      at 575-607.
    - Per-element ``isinstance(str)``.
    - Per-element ``.strip().lower()`` normalization (normalize at the
      input boundary).
    - Per-element non-empty (after strip) check.
    - Per-element format validation against
      :data:`_R9B_RULE_ID_REGEX` — accepts canonical
      ``pack/rule-suffix``, bare ``custom/<suffix>``, AND mangled
      ``custom/<suffix>__<kind>``.

    Returns a frozenset (deduplicated, immutable). The deduplication
    is intentional — an entry repeated in the list is a no-op rather
    than an error so users can stitch lists together programmatically
    without pre-deduplicating.

    Args:
        value: Raw value to validate. Expected shape:
            ``list[str]`` / ``tuple[str, ...]``.
        error_label: Source-attributed prefix interpolated into
            error messages (e.g.,
            ``"[tool.protokit.lint] disabled_rules"`` for pyproject,
            ``"--disable-rule"`` for CLI overrides). Pre-formatted so
            the helper does not need to know which source called it.
        error_code: The stable error-prefix code to use when emitting
            validation failures. Defaults to ``"pyproject-config-invalid"``
            for the pyproject path; CLI callers pass
            ``"cli-option-invalid"`` so CI scripts can distinguish a
            bad CLI flag value from a bad pyproject entry without
            parsing freeform text.

    Returns:
        Frozen set of normalized rule_ids.

    Raises:
        SystemExit: Exit code 2 via :func:`error_exit_with_code`
            using ``error_code`` for any validation failure.
    """
    if not isinstance(value, (list, tuple)):
        error_exit_with_code(
            error_code,
            (
                f"{error_label} must be a list of strings; "
                f"got {type(value).__name__}."
            ),
        )
    normalized: set[str] = set()
    for index, elem in enumerate(value):
        if not isinstance(elem, str):
            error_exit_with_code(
                error_code,
                (
                    f"{error_label}[{index}] must be a string rule_id; "
                    f"got {type(elem).__name__}."
                ),
            )
        # Normalize FIRST (whitespace + case) so format validation
        # matches the canonical form the engine compares against, and
        # so error messages cite the form that would have been looked
        # up. Mirrors ``_coerce_severities`` key normalization.
        stripped_lower = elem.strip().lower()
        if not stripped_lower:
            error_exit_with_code(
                error_code,
                (
                    f"{error_label}[{index}] must be a non-empty "
                    f"rule_id."
                ),
            )
        if not _R9B_RULE_ID_REGEX.match(stripped_lower):
            error_exit_with_code(
                error_code,
                (
                    f"{error_label}[{index}] {stripped_lower!r} is not a "
                    f"valid rule_id: expected the canonical form "
                    f"'pack/rule-suffix' (e.g., 'naming/snake-case-fields') "
                    f"or the custom forms 'custom/<suffix>' / "
                    f"'custom/<suffix>__<kind>'."
                ),
            )
        normalized.add(stripped_lower)
    return frozenset(normalized)


def _coerce_disabled_rules(value: Any) -> frozenset[str]:
    """Coerce ``disabled_rules`` to ``frozenset[str]``."""
    return _coerce_r9b_rule_id_list(
        value, error_label="[tool.protokit.lint] disabled_rules",
    )


def _coerce_enabled_rules(value: Any) -> frozenset[str]:
    """Coerce ``enabled_rules`` to ``frozenset[str]``."""
    return _coerce_r9b_rule_id_list(
        value, error_label="[tool.protokit.lint] enabled_rules",
    )


def _expand_custom_prefix(
    rule_ids: frozenset[str],
    specs: tuple[CustomAnnotationRuleSpec, ...],
) -> frozenset[str]:
    """Expand bare ``custom/<suffix>`` entries to all mangled forms.

    Multi-kind custom rule prefix expansion. For each entry in
    ``rule_ids`` matching the bare ``custom/<suffix>`` shape (no
    ``__<kind>`` mangling), look up the spec by **suffix equality**
    (NOT substring match — ``"custom/foo"`` must NOT match
    ``"custom/foobar"``) and replace the bare entry with the full
    set of mangled rule_ids returned by ``synthetic_rule_ids()``
    for that spec.

    Per-kind disable via the explicit mangled form
    (e.g., ``"custom/audit-required__method"``) bypasses expansion —
    the mangled form already addresses one specific kind, and the
    regex permits it through ``_R9B_RULE_ID_REGEX``.

    If no spec matches a bare ``custom/<suffix>`` entry, the entry
    is preserved as-is (it may match a future-shipped or external
    rule; the unknown-rule_id warning fires from the CLI
    orchestration layer later).

    Args:
        rule_ids: Validated, normalized rule_ids to expand
            (typically from ``_coerce_disabled_rules`` /
            ``_coerce_enabled_rules`` output).
        specs: Resolved ``CustomAnnotationRuleSpec`` entries from
            ``_coerce_custom_annotation_rules``. Empty tuple is
            permitted — expansion is a no-op (bare entries flow
            through unchanged for unknown-rule_id diagnosis).

    Returns:
        New frozenset with bare-prefix entries expanded.
    """
    if not rule_ids:
        return rule_ids
    spec_by_suffix = {spec.rule_suffix: spec for spec in specs}
    result: set[str] = set()
    for rid in rule_ids:
        if rid.startswith("custom/") and "__" not in rid:
            suffix = rid[len("custom/"):]
            matching_spec = spec_by_suffix.get(suffix)
            if matching_spec is not None:
                # Materialize every kind-mangled rule_id for this
                # spec (single-kind specs return just the bare form;
                # multi-kind specs return bare + N-1 mangled forms).
                result.update(synthetic_rule_ids((matching_spec,)))
                continue
        result.add(rid)
    return frozenset(result)


def _compute_r8b_contradiction_warnings(
    *,
    off_severity_ids: frozenset[str],
    pyproject_disabled: frozenset[str],
    cli_disabled: frozenset[str],
    pyproject_enabled: frozenset[str],
    cli_enabled: frozenset[str],
    non_off_severity_overrides: frozenset[str],
) -> tuple[LintRuntimeWarning, ...]:
    """Compute ``contradictory_disable_config`` warnings.

    Detects collisions where polarity-first / tier-second resolution
    silently overrides a user-supplied directive at a lower tier. The
    five contradiction patterns are:

    1. ``disabled_rules ⊃ R AND enabled_rules ⊃ R`` (within-pyproject)
    2. ``--disable-rule R AND --enable-rule R`` (within-CLI)
    3. ``--enable-rule R AND pyproject disabled_rules ⊃ R``
       (cross-tier disable wins; ``--no-config`` is the escape hatch
       but drops ALL pyproject config — message names this caveat)
    4. ``disabled_rules ⊃ R AND [severities] R = <non-off>``
       (severity override is moot under polarity-first)
    5. ``[severities] R = "off" AND enabled_rules ⊃ R``

    Idempotent disables (D_off ⊃ R AND D_pyp ⊃ R; D_pyp ⊃ R AND
    D_cli ⊃ R; etc.) are NOT contradictions — both directives have
    the same polarity, so neither overrides the other.

    One warning per contradicted rule_id (deterministic sorted order
    so test fixtures pin a stable sequence). The message names
    every involved mechanism so the user sees both sides of the
    collision in a single line.

    Args:
        off_severity_ids: rule_ids extracted from
            ``[severities] X = "off"`` (the off-sentinel set).
        pyproject_disabled: rule_ids from pyproject
            ``disabled_rules``.
        cli_disabled: rule_ids from CLI ``--disable-rule``.
        pyproject_enabled: rule_ids from pyproject ``enabled_rules``.
        cli_enabled: rule_ids from CLI ``--enable-rule``.
        non_off_severity_overrides: rule_ids from
            ``[severities] X = <non-off>`` (the surviving severities
            after off-interception). Used to detect pattern 4.

    Returns:
        Tuple of one warning per contradicted rule_id, sorted by
        rule_id for deterministic output.
    """
    all_disable_sources = (
        off_severity_ids | pyproject_disabled | cli_disabled
    )
    all_enable_sources = pyproject_enabled | cli_enabled
    warnings: list[LintRuntimeWarning] = []
    for rid in sorted(all_disable_sources | all_enable_sources):
        disable_mechs: list[str] = []
        if rid in off_severity_ids:
            disable_mechs.append("[severities] = 'off'")
        if rid in pyproject_disabled:
            disable_mechs.append("[tool.protokit.lint] disabled_rules")
        if rid in cli_disabled:
            disable_mechs.append("--disable-rule")
        enable_mechs: list[str] = []
        if rid in pyproject_enabled:
            enable_mechs.append("[tool.protokit.lint] enabled_rules")
        if rid in cli_enabled:
            enable_mechs.append("--enable-rule")
        severity_moot = (
            rid in non_off_severity_overrides
            and bool(disable_mechs)
        )
        polarity_clash = bool(disable_mechs) and bool(enable_mechs)
        if not (polarity_clash or severity_moot):
            continue
        message_parts: list[str] = [
            f"rule {rid!r} appears in conflicting R9b directives:",
        ]
        if disable_mechs:
            message_parts.append(f"disabled by {', '.join(disable_mechs)}")
        if enable_mechs:
            message_parts.append(f"enabled by {', '.join(enable_mechs)}")
        if polarity_clash:
            message_parts.append(
                "disable wins per R8 polarity-first precedence",
            )
        # Note: non_off_severity_overrides is a key-only set; the specific
        # severity value (e.g., "warning") that conflicts is not available at
        # this layer, so the message says "non-'off' [severities] override has
        # no effect" without echoing the value. This is intentional —
        # _coerce_severities returns only key→value pairs, and the values
        # aren't plumbed to from_dict's contradiction-detection step.
        if severity_moot:
            message_parts.append(
                "non-'off' [severities] override has no effect "
                "(disable wins per R8 polarity-first precedence)",
            )
        # The cross-tier --enable-rule + pyproject disabled_rules
        # case is the one most likely to surprise users; surface the
        # --no-config escape hatch + the caveat that it drops ALL
        # pyproject config (not just disabled_rules) inline so users
        # do not misuse it. Other clash patterns can be resolved by
        # editing pyproject directly.
        cross_tier_cli_enable = (
            rid in cli_enabled
            and (rid in pyproject_disabled or rid in off_severity_ids)
        )
        if cross_tier_cli_enable:
            message_parts.append(
                "to override, edit pyproject directly OR pass "
                "--no-config (note: --no-config drops ALL pyproject "
                "configuration, not just disabled_rules)",
            )
        warnings.append(
            LintRuntimeWarning(
                category="contradictory_disable_config",
                rule_id=rid,
                message="; ".join(message_parts) + ".",
            ),
        )
    return tuple(warnings)


@dataclass(frozen=True)
class CustomAnnotationRuleSpec:
    """Validated entry from ``[[tool.protokit.lint.custom_annotation_rules]]``.

    Produced by :func:`_coerce_custom_annotation_rules`. Each entry
    materializes into one or more synthetic ``custom/<rule_suffix>``
    lint rules — one closure per ``element_kinds`` member, all sharing
    the same ``rule_id`` (verified at implementation time that
    ``LintEngine._loaded_specs`` is keyed by ``rule_id`` alone, so
    multi-kind entries register N closures under one key via the
    synthetic ModuleType's RULES tuple — the engine accepts repeated
    keys silently because intra-pack dedup operates only inside
    ``load_rule_pack``'s staging dict, which the synthetic loader
    bypasses by appending closures for distinct kinds before handoff).

    All fields are read-only post-construction. The dataclass is
    ``frozen=True`` to satisfy the frozen-dataclass post-init
    snapshot rule (mutable fields must be snapshotted in
    ``__post_init__``): ``element_kinds`` is a tuple and
    ``allowed_values`` is a tuple (or ``None``) so no mutable nesting
    is exposed.

    Attributes:
        rule_suffix: The user-supplied suffix; the materialized
            ``rule_id`` is ``f"custom/{rule_suffix}"``. Must match
            ``^[a-z][a-z0-9]*(-[a-z0-9]+)*$``.
        option: The custom-extension full name as it would appear in
            a ``.proto`` file (e.g., ``"mycorp.audit_level"``). No
            surrounding parentheses — the synthetic-rule closure
            resolves the extension via ``pool.FindExtensionByName(
            option)`` and the parens are protobuf source syntax, not
            part of the descriptor full name.
        element_kinds: Tuple of ``ElementKind`` values the synthetic
            rule applies to. Non-empty (the validator rejects an
            empty list). Each kind produces one closure attached to
            the same ``rule_id``.
        allowed_values: Optional tuple of allowed scalar values. When
            ``None``, the rule is presence-only (fires if the option
            is absent). When non-``None``, the rule fires on absence
            AND on a value not in ``allowed_values``. Values are
            homogeneous (all same Python type — ``str | int | bool``;
            ``float`` and mixed types are rejected at config-load per
            the schema contract). For enum-typed options, the values
            are identifier strings (e.g., ``["HIGH", "CRITICAL"]``);
            the synthetic-rule closure translates the runtime integer
            to its enum identifier name for comparison.
        severity: Default severity for findings produced by this
            synthetic rule. Defaults to ``LintSeverity.WARNING``.
            ``[tool.protokit.lint.severities]`` overrides apply per
            the usual precedence (severity overrides outrank
            built-in defaults but lose to polarity-first disable
            directives).
    """

    rule_suffix: str
    option: str
    element_kinds: tuple[ElementKind, ...]
    allowed_values: tuple[str, ...] | tuple[int, ...] | tuple[bool, ...] | None = None
    severity: LintSeverity = LintSeverity.WARNING

    @property
    def rule_id(self) -> str:
        """The fully-qualified ``custom/<suffix>`` rule_id."""
        return f"custom/{self.rule_suffix}"


def _empty_custom_annotation_rules() -> tuple[CustomAnnotationRuleSpec, ...]:
    """Module-level typed factory for the ``custom_annotation_rules`` default.

    Mirrors :func:`_empty_severities` — a typed factory makes the
    field's element type explicit to mypy across dataclass-stub
    versions.
    """
    return ()


def _coerce_custom_annotation_rules(
    value: Any,
) -> tuple[CustomAnnotationRuleSpec, ...]:
    """Coerce ``[[custom_annotation_rules]]`` to a tuple of validated specs.

    The TOML wire format is array-of-tables:

    .. code-block:: toml

        [[tool.protokit.lint.custom_annotation_rules]]
        rule_suffix    = "audit-required"
        option         = "mycorp.audit_level"
        element_kinds  = ["method"]
        allowed_values = ["LOW", "HIGH", "CRITICAL"]   # optional
        severity       = "error"                       # optional

    ``tomllib`` parses array-of-tables as ``list[dict]``. Per-entry
    validation:

    - ``rule_suffix``: non-empty string matching :data:`_CUSTOM_RULE_SUFFIX_REGEX`.
    - ``option``: non-empty string. No leading/trailing whitespace.
    - ``element_kinds``: non-empty list of lowercase strings drawn
      from :data:`_VALID_ELEMENT_KIND_NAMES` (the 8 ElementKind values).
      Duplicates within a single entry are rejected to surface typos
      cleanly.
    - ``allowed_values``: optional homogeneous list of scalars (all
      ``str``, all ``int``, or all ``bool``). Empty list rejected.
      Mixed-type lists rejected. Floats rejected: scalar protobuf
      option values comparable by equality include
      str/int/bool/enum-identifier; floats compare unsafely under
      ULP drift.
    - ``severity``: optional string ∈ ``{"error", "warning", "info"}``;
      default ``"warning"``.

    Cross-entry: collision detection on ``rule_suffix``. Two entries
    declaring the same suffix raise ``pyproject-config-invalid``
    naming both pyproject positions (index 0-based).

    Args:
        value: The raw value parsed from
            ``[tool.protokit.lint.custom_annotation_rules]``. Expected
            shape: ``list[dict[str, Any]]``.

    Returns:
        A tuple of validated :class:`CustomAnnotationRuleSpec`
        entries. Empty tuple if the input list is empty (the empty
        list is accepted as a no-op — users can stage a configuration
        scaffold).

    Raises:
        SystemExit: Exit code 2 via :func:`error_exit_with_code`
            ``pyproject-config-invalid`` for any validation failure.
            The error message names the offending entry index when
            applicable.
    """
    if not isinstance(value, list):
        error_exit_with_code(
            "pyproject-config-invalid",
            (
                f"[tool.protokit.lint] custom_annotation_rules must be "
                f"an array of tables ([[custom_annotation_rules]]); "
                f"got {type(value).__name__}."
            ),
        )

    seen_suffixes: dict[str, int] = {}
    specs: list[CustomAnnotationRuleSpec] = []
    for index, entry in enumerate(value):
        if not isinstance(entry, dict):
            error_exit_with_code(
                "pyproject-config-invalid",
                (
                    f"[tool.protokit.lint] custom_annotation_rules[{index}] "
                    f"must be a table; got {type(entry).__name__}."
                ),
            )

        allowed_entry_keys = frozenset(
            {
                "rule_suffix",
                "option",
                "element_kinds",
                "allowed_values",
                "severity",
            },
        )
        unknown = sorted(set(entry) - allowed_entry_keys)
        if unknown:
            unknown_repr = ", ".join(repr(k) for k in unknown)
            allowed_repr = ", ".join(repr(k) for k in sorted(allowed_entry_keys))
            error_exit_with_code(
                "pyproject-config-invalid",
                (
                    f"[tool.protokit.lint] custom_annotation_rules[{index}] "
                    f"has unknown key(s): {unknown_repr}. Allowed keys: "
                    f"{allowed_repr}."
                ),
            )

        # rule_suffix: required, regex-validated.
        if "rule_suffix" not in entry:
            error_exit_with_code(
                "pyproject-config-invalid",
                (
                    f"[tool.protokit.lint] custom_annotation_rules[{index}] "
                    f"is missing required key 'rule_suffix'."
                ),
            )
        raw_suffix = entry["rule_suffix"]
        if not isinstance(raw_suffix, str):
            error_exit_with_code(
                "pyproject-config-invalid",
                (
                    f"[tool.protokit.lint] custom_annotation_rules[{index}]"
                    f".rule_suffix must be a string; got "
                    f"{type(raw_suffix).__name__}."
                ),
            )
        if not _CUSTOM_RULE_SUFFIX_REGEX.match(raw_suffix):
            error_exit_with_code(
                "pyproject-config-invalid",
                (
                    f"[tool.protokit.lint] custom_annotation_rules[{index}]"
                    f".rule_suffix must match "
                    f"{_CUSTOM_RULE_SUFFIX_REGEX.pattern!r} "
                    f"(lowercase ASCII letters, digits, single hyphens; "
                    f"must start with a letter)."
                ),
            )
        if raw_suffix in seen_suffixes:
            prior_index = seen_suffixes[raw_suffix]
            error_exit_with_code(
                "pyproject-config-invalid",
                (
                    f"[tool.protokit.lint] custom_annotation_rules[{index}]"
                    f".rule_suffix={raw_suffix!r} collides with entry "
                    f"[{prior_index}]; each rule_suffix must be unique."
                ),
            )
        seen_suffixes[raw_suffix] = index

        # option: required non-empty string.
        if "option" not in entry:
            error_exit_with_code(
                "pyproject-config-invalid",
                (
                    f"[tool.protokit.lint] custom_annotation_rules[{index}] "
                    f"is missing required key 'option'."
                ),
            )
        raw_option = entry["option"]
        if not isinstance(raw_option, str):
            error_exit_with_code(
                "pyproject-config-invalid",
                (
                    f"[tool.protokit.lint] custom_annotation_rules[{index}]"
                    f".option must be a string; got "
                    f"{type(raw_option).__name__}."
                ),
            )
        stripped_option = raw_option.strip()
        if not stripped_option:
            error_exit_with_code(
                "pyproject-config-invalid",
                (
                    f"[tool.protokit.lint] custom_annotation_rules[{index}]"
                    f".option must be a non-empty string."
                ),
            )

        # element_kinds: required non-empty list of valid ElementKind names.
        if "element_kinds" not in entry:
            error_exit_with_code(
                "pyproject-config-invalid",
                (
                    f"[tool.protokit.lint] custom_annotation_rules[{index}] "
                    f"is missing required key 'element_kinds'."
                ),
            )
        raw_kinds = entry["element_kinds"]
        if not isinstance(raw_kinds, list):
            error_exit_with_code(
                "pyproject-config-invalid",
                (
                    f"[tool.protokit.lint] custom_annotation_rules[{index}]"
                    f".element_kinds must be a list of strings; got "
                    f"{type(raw_kinds).__name__}."
                ),
            )
        if not raw_kinds:
            error_exit_with_code(
                "pyproject-config-invalid",
                (
                    f"[tool.protokit.lint] custom_annotation_rules[{index}]"
                    f".element_kinds must be a non-empty list."
                ),
            )
        seen_kinds: set[str] = set()
        kinds_list: list[ElementKind] = []
        for k_index, kind_name in enumerate(raw_kinds):
            if not isinstance(kind_name, str):
                error_exit_with_code(
                    "pyproject-config-invalid",
                    (
                        f"[tool.protokit.lint] custom_annotation_rules[{index}]"
                        f".element_kinds[{k_index}] must be a string; got "
                        f"{type(kind_name).__name__}."
                    ),
                )
            if kind_name not in _VALID_ELEMENT_KIND_NAMES:
                valid = ", ".join(repr(v) for v in sorted(_VALID_ELEMENT_KIND_NAMES))
                error_exit_with_code(
                    "pyproject-config-invalid",
                    (
                        f"[tool.protokit.lint] custom_annotation_rules[{index}]"
                        f".element_kinds[{k_index}] must be one of {valid}; "
                        f"got an unrecognized ElementKind name."
                    ),
                )
            if kind_name in seen_kinds:
                error_exit_with_code(
                    "pyproject-config-invalid",
                    (
                        f"[tool.protokit.lint] custom_annotation_rules[{index}]"
                        f".element_kinds has duplicate value {kind_name!r}."
                    ),
                )
            seen_kinds.add(kind_name)
            kinds_list.append(ElementKind(kind_name))

        # allowed_values: optional homogeneous scalar list (str / int /
        # bool). Floats + mixed-type lists rejected.
        allowed: tuple[Any, ...] | None = None
        if "allowed_values" in entry:
            raw_allowed = entry["allowed_values"]
            if not isinstance(raw_allowed, list):
                error_exit_with_code(
                    "pyproject-config-invalid",
                    (
                        f"[tool.protokit.lint] custom_annotation_rules[{index}]"
                        f".allowed_values must be a list; got "
                        f"{type(raw_allowed).__name__}."
                    ),
                )
            if not raw_allowed:
                error_exit_with_code(
                    "pyproject-config-invalid",
                    (
                        f"[tool.protokit.lint] custom_annotation_rules[{index}]"
                        f".allowed_values must be a non-empty list when "
                        f"specified (omit the key for presence-only rules)."
                    ),
                )
            # ``bool`` is a subclass of ``int`` in Python; check ``bool``
            # FIRST so a list of bools binds to the ``bool`` element type
            # rather than masquerading as ``int``. Per pyproject's
            # ``_coerce_max_warnings`` precedent.
            first = raw_allowed[0]
            if isinstance(first, bool):
                element_type: type = bool
                element_label = "bool"
            elif isinstance(first, int):
                element_type = int
                element_label = "int"
            elif isinstance(first, str):
                element_type = str
                element_label = "str"
            else:
                # Float, list, dict, etc. — explicitly rejected.
                error_exit_with_code(
                    "pyproject-config-invalid",
                    (
                        f"[tool.protokit.lint] custom_annotation_rules[{index}]"
                        f".allowed_values[0] must be one of "
                        f"str / int / bool; got "
                        f"{type(first).__name__}. "
                        f"(Float-valued options compare unsafely under ULP drift.)"
                    ),
                )
            seen_values: set[Any] = set()
            normalized_values: list[Any] = []
            for v_index, raw_value in enumerate(raw_allowed):
                # ``bool``-first check matches the first-element branch.
                if element_type is bool:
                    if not isinstance(raw_value, bool):
                        error_exit_with_code(
                            "pyproject-config-invalid",
                            (
                                f"[tool.protokit.lint] custom_annotation_rules"
                                f"[{index}].allowed_values[{v_index}] must be "
                                f"a {element_label} to match the first element; "
                                f"got {type(raw_value).__name__}."
                            ),
                        )
                elif element_type is int:
                    # Reject booleans masquerading as ints in a mixed list.
                    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
                        error_exit_with_code(
                            "pyproject-config-invalid",
                            (
                                f"[tool.protokit.lint] custom_annotation_rules"
                                f"[{index}].allowed_values[{v_index}] must be "
                                f"a {element_label} to match the first element; "
                                f"got {type(raw_value).__name__}."
                            ),
                        )
                else:  # element_type is str
                    if not isinstance(raw_value, str):
                        error_exit_with_code(
                            "pyproject-config-invalid",
                            (
                                f"[tool.protokit.lint] custom_annotation_rules"
                                f"[{index}].allowed_values[{v_index}] must be "
                                f"a {element_label} to match the first element; "
                                f"got {type(raw_value).__name__}."
                            ),
                        )
                if raw_value in seen_values:
                    error_exit_with_code(
                        "pyproject-config-invalid",
                        (
                            f"[tool.protokit.lint] custom_annotation_rules"
                            f"[{index}].allowed_values has duplicate entry "
                            f"at position {v_index}."
                        ),
                    )
                seen_values.add(raw_value)
                normalized_values.append(raw_value)
            allowed = tuple(normalized_values)

        # severity: optional string. Defaults to "warning".
        severity: LintSeverity = LintSeverity.WARNING
        if "severity" in entry:
            raw_severity = entry["severity"]
            if not isinstance(raw_severity, str):
                error_exit_with_code(
                    "pyproject-config-invalid",
                    (
                        f"[tool.protokit.lint] custom_annotation_rules[{index}]"
                        f".severity must be a string; got "
                        f"{type(raw_severity).__name__}."
                    ),
                )
            normalized_severity = raw_severity.strip().lower()
            try:
                severity = LintSeverity(normalized_severity)
            except ValueError:
                valid = ", ".join(repr(s.value) for s in LintSeverity)
                error_exit_with_code(
                    "pyproject-config-invalid",
                    (
                        f"[tool.protokit.lint] custom_annotation_rules[{index}]"
                        f".severity must be one of {valid}; got a severity "
                        f"name outside the closed set."
                    ),
                )

        specs.append(
            CustomAnnotationRuleSpec(
                rule_suffix=raw_suffix,
                option=stripped_option,
                element_kinds=tuple(kinds_list),
                allowed_values=allowed,
                severity=severity,
            ),
        )

    return tuple(specs)


def _coerce_no_builtin_rules(value: Any) -> bool:
    """Coerce ``no_builtin_rules`` to ``bool``.

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

    Produced by :meth:`from_dict` after schema validation and
    precedence application. The CLI passes one of these to
    ``_main_impl``; downstream code consumes specific fields
    (``exclude``; ``min_severity_source`` + ``pyproject_min_severity``
    for source-attributed relaxation messages).

    Source attribution semantics (only ``min_severity_source`` is
    exposed for now, since it's the only attribution the runtime
    warnings rely on):

    - ``"cli"``:       The CLI flag was explicitly provided.
    - ``"pyproject"``: Pyproject set this key; CLI did not override.
    - ``"profile"``:   Neither CLI nor pyproject set this key; the
                       composed profile's intrinsic floor is in effect.
                       (Emission code may transition ``"default"`` to
                       ``"profile"`` when ``min_severity is None``.)
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
    #: Per-rule severity overrides resolved from
    #: ``[tool.protokit.lint.severities]``. Empty dict when no
    #: overrides are configured. CLI side-channel for this knob is
    #: deferred to a future release; currently pyproject-only.
    #: ``__post_init__`` wraps the input in ``MappingProxyType(dict(...))``
    #: per the ``frozen-dataclass-mutable-fields-need-post-init-snapshot``
    #: learning so a caller passing a mutable dict cannot leak mutations
    #: through the frozen wrapper.
    severities: Mapping[str, LintSeverity] = dataclasses.field(
        default_factory=_empty_severities,
    )
    #: When ``True``, ``cli.py`` skips the BUILTIN_PACKS auto-load loop.
    #: Resolved from either ``--no-builtin-rules`` CLI flag OR
    #: ``[tool.protokit.lint] no_builtin_rules = true``; CLI takes
    #: precedence per the standard CLI > pyproject precedence applied
    #: to the other knobs.
    no_builtin_rules: bool = False
    #: Validated entries from
    #: ``[[tool.protokit.lint.custom_annotation_rules]]``. Empty tuple
    #: when no entries are configured. No CLI side-channel — synthetic
    #: rule declarations are pyproject-only by intent (the
    #: array-of-tables shape doesn't roundtrip through Click's flag
    #: surface).
    custom_annotation_rules: tuple[CustomAnnotationRuleSpec, ...] = (
        dataclasses.field(default_factory=_empty_custom_annotation_rules)
    )
    #: UNIFIED disabled-rule set merging three sources:
    #: ``[severities] X = "off"`` sentinel ids (intercepted at the
    #: coercion layer), pyproject ``disabled_rules`` list, and CLI
    #: ``--disable-rule`` overrides. Merging happens inside
    #: ``from_dict`` BEFORE returning, so callers see ONE
    #: ``frozenset[str]`` — no separate ``disabled_via_off_severity``
    #: field leaks past the boundary. ``cli.py`` subtracts this set
    #: from ``composed_profile.rule_ids`` to actuate the disable per
    #: the sentinel propagation contract. Custom-prefix expansion
    #: materializes any bare ``custom/<suffix>`` entry into the
    #: full set of mangled rule_ids for the matching spec before merge.
    disabled_rules: frozenset[str] = dataclasses.field(
        default_factory=_empty_rule_id_set,
    )
    #: Pyproject ``enabled_rules`` ∪ CLI ``--enable-rule`` directives.
    #: Kept distinct from :attr:`disabled_rules` (NOT merged into a
    #: single "effective" set) because contradiction warnings need
    #: both sides attributable: knowing only that R is disabled would
    #: lose the information needed to emit "rule R appears in both
    #: disabled_rules and enabled_rules; disable wins per polarity-first
    #: precedence". Custom-prefix expansion applies symmetrically.
    #: ``cli.py`` does NOT consume this field to actuate disables —
    #: precedence is already resolved in ``from_dict``, so the
    #: surviving set is informational from the engine's perspective
    #: (the engine sees an effective rule_ids set with disables
    #: already removed). It IS read by the unknown-rule_id check in
    #: ``cli.py`` to detect rule_ids named in enable directives that
    #: match no loaded rule (the diff
    #: ``(resolved.disabled_rules | resolved.enabled_rules) - loaded_rule_ids``
    #: covers both sets).
    enabled_rules: frozenset[str] = dataclasses.field(
        default_factory=_empty_rule_id_set,
    )
    #: ``contradictory_disable_config`` warnings produced inside
    #: ``from_dict`` when R9b directives across disable + enable
    #: mechanisms collide per the precedence table. The CLI appends
    #: this tuple to ``LintReport.runtime_warnings`` so the warnings
    #: surface in every formatter alongside engine-emitted warnings.
    #: Empty tuple in the common case (no contradictions).
    #: ``unknown_rule_id`` warnings are NOT carried here — they fire
    #: at CLI orchestration time when the full loaded-rule registry is
    #: available, mirroring the existing ``severities_unloaded_rule``
    #: emission pattern at ``cli.py:1160-1177``.
    runtime_warnings: tuple[LintRuntimeWarning, ...] = dataclasses.field(
        default_factory=_empty_runtime_warnings,
    )

    def __post_init__(self) -> None:
        # Tuple-snapshot list inputs per the
        # ``frozen-dataclass-mutable-fields-need-post-init-snapshot`` learning.
        # Without this, a caller passing ``profile=["a", "b"]`` would
        # expose the original list through the frozen wrapper and
        # mutations on it would leak through to the dataclass.
        object.__setattr__(self, "profile", tuple(self.profile))
        object.__setattr__(self, "exclude", tuple(self.exclude))
        # custom_annotation_rules tuple-snapshot for the same
        # frozen-dataclass safety reason. ``_coerce_custom_annotation_rules``
        # already returns a tuple; programmatic callers (tests) may
        # pass a list which we normalize here.
        object.__setattr__(
            self,
            "custom_annotation_rules",
            tuple(self.custom_annotation_rules),
        )
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
        # Frozenset-snapshot the two R9b rule_id sets.
        # ``from_dict`` produces frozensets already; programmatic
        # callers (tests, R9b smoke fixtures) may pass list/tuple/set
        # which we normalize here so the frozen-dataclass invariant
        # holds regardless of construction site.
        object.__setattr__(self, "disabled_rules", frozenset(self.disabled_rules))
        object.__setattr__(self, "enabled_rules", frozenset(self.enabled_rules))
        # Tuple-snapshot accumulated contradiction warnings so a caller
        # passing a list does not leak mutations into the frozen
        # ResolvedLintConfig (the warnings are appended to
        # ``LintReport.runtime_warnings`` in ``cli.py``; a mutated
        # source list would silently corrupt the report).
        object.__setattr__(
            self, "runtime_warnings", tuple(self.runtime_warnings),
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
        # source-attributed message silently degrades to an unattributed
        # fallback.
        if self.exclude and self.exclude_source == "default":
            raise ValueError(
                "ResolvedLintConfig.exclude_source must be set to "
                "'cli', 'pyproject', or 'both' when exclude is "
                "non-empty (got 'default').",
            )
        # Paired-field invariant for contradiction warnings.
        # Every contradictory_disable_config warning's rule_id must be
        # present in disabled_rules or enabled_rules. Catches programmatic
        # dataclasses.replace() callers who mutate the disable/enable sets
        # without updating runtime_warnings, which would leave stale
        # warnings naming rule_ids no longer in conflict.
        r8b_rule_ids = {
            w.rule_id
            for w in self.runtime_warnings
            if w.category == "contradictory_disable_config"
            and w.rule_id is not None
        }
        directive_rule_ids = self.disabled_rules | self.enabled_rules
        stale_warnings = r8b_rule_ids - directive_rule_ids
        if stale_warnings:
            raise ValueError(
                f"ResolvedLintConfig invariant violation: "
                f"contradictory_disable_config warnings reference "
                f"rule_id(s) {sorted(stale_warnings)!r} not present in "
                f"disabled_rules or enabled_rules. This usually means "
                f"dataclasses.replace() was called to mutate the disable "
                f"sets without refreshing runtime_warnings."
            )

    def relaxation_message(
        self, composed_floor: LintSeverity,
    ) -> str | None:
        """Return the relaxation message, or ``None`` when no relaxation.

        Three message templates pinned at the ``ResolvedLintConfig``
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
            The source-attributed relaxation message, or ``None``.
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
        # is reserved for future emission code that may emit different
        # message branches).
        return None

    def all_files_excluded_message(self, file_count: int) -> str:
        """Return the source-attributed message for the all_files_excluded warning.

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

        Individual patterns are passed through ``_safe_for_stderr``
        before joining so a pattern with embedded control characters
        cannot forge a fake stderr line.

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
            The source-attributed message string.
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

        Validation phase (single-pass):

        - Unknown keys: :func:`_validate_table_keys` hard-errors
          on any key outside the allowlist.
        - Type mismatches: per-field ``_coerce_*`` helpers validate
          scalar-vs-list shape, element type, and value range;
          mismatches exit 2 with
          ``error[lint-pyproject-config-invalid]:``.

        Precedence:

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
                            tier won, so emission code can choose the
                            right relaxation message branch.
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
        - ``"no_builtin_rules"``: ``bool | None``. ``None`` means
                                  "CLI did not set this flag"; the
                                  pyproject value (or default
                                  ``False``) wins.

        Intentionally absent: ``"severities"``. Currently ships the
        pyproject-only parsing surface for per-rule severity
        overrides; no CLI side-channel exists yet. If a future
        delivery wires a CLI severities override, the key must be
        added to this shape table AND ``from_dict`` updated to read
        it — otherwise the override is silently dropped.

        Returns:
            A frozen ``ResolvedLintConfig`` with defaults applied
            and per-key source attribution computed.

        Raises:
            SystemExit: Exit code 2 via ``error_exit_with_code(
            "pyproject-config-invalid", ...)`` for any validation
            violation.
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
                    # _coerce_severities returns a _CoercedSeverities
                    # NamedTuple carrying the non-"off" severities
                    # dict + the off_rule_ids frozenset (intercepted
                    # "off" sentinel).
                    validated[key] = _coerce_severities(value)
                elif key == "no_builtin_rules":
                    validated[key] = _coerce_no_builtin_rules(value)
                elif key == "custom_annotation_rules":
                    validated[key] = _coerce_custom_annotation_rules(value)
                elif key == "disabled_rules":
                    validated[key] = _coerce_disabled_rules(value)
                elif key == "enabled_rules":
                    validated[key] = _coerce_enabled_rules(value)
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

        # min_severity: CLI replaces pyproject; track source for the
        # source-attributed relaxation message.
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
            # than to a CLI/pyproject override). The current relaxation
            # message implementation does not use the ``"profile"``
            # source — when no override is set, ``relaxation_message``
            # returns ``None``. ``"default"`` is correct here.
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

        # severities: pyproject-only — no CLI side-channel yet.
        # Defaults to empty dict when the table key is absent. CLI's
        # user-wins post-compose overlay is applied in cli.py around
        # the LintProfile.compose call, NOT here; this method only
        # resolves the input-boundary value.
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
                "ResolvedLintConfig.from_dict — currently ships "
                "pyproject parsing only. Add the precedence branch "
                "here before exposing a CLI severities override.",
            )
        # Unpack the _CoercedSeverities NamedTuple. The off_rule_ids
        # set is merged into the unified disabled_rules field BELOW
        # (after the precedence + contradiction-warning step).
        validated_severities_raw = validated.get("severities")
        if validated_severities_raw is None:
            resolved_severities: Mapping[str, LintSeverity] = {}
            off_severity_rule_ids: frozenset[str] = frozenset()
        else:
            coerced = cast(_CoercedSeverities, validated_severities_raw)
            resolved_severities = coerced.severities
            off_severity_rule_ids = coerced.off_rule_ids

        # no_builtin_rules: CLI replaces pyproject. The CLI flag's
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

        # custom_annotation_rules is pyproject-only (no CLI
        # side-channel). The validated tuple flows through unchanged;
        # cli.py reads ``resolved.custom_annotation_rules`` to drive
        # the synthetic-rule loader and composed-profile augmentation.
        # Mirror the silent-drop guard from the ``severities`` branch:
        # if a future delivery wires a CLI override without updating
        # this method, surface the integration bug immediately.
        if "custom_annotation_rules" in cli_overrides:
            raise NotImplementedError(
                "cli_overrides['custom_annotation_rules'] is not yet "
                "wired into ResolvedLintConfig.from_dict — currently "
                "ships pyproject-only declarations. Add the precedence "
                "branch here before exposing a CLI custom-annotation "
                "override.",
            )
        resolved_custom_annotation_rules: tuple[
            CustomAnnotationRuleSpec, ...
        ] = validated.get("custom_annotation_rules", ())

        # R9b per-rule disable dispatch. Ordering: (1)
        # custom_annotation_rules already resolved above, (2) coerce
        # pyproject disabled/enabled lists, (3) coerce CLI overrides
        # with the SAME strictness (symmetric-coercion-strictness for
        # multi-source field resolvers), (4) expand custom/<suffix>
        # bare entries via synthetic_rule_ids((spec,)) using
        # suffix-equality matching, (5) compute contradiction
        # warnings BEFORE the disable-set merge (warnings need
        # attribution), (6) merge off_severity_rule_ids into the
        # final unified disabled_rules frozenset that cli.py
        # subtracts from composed_profile.rule_ids.
        #
        # No NotImplementedError trip-wires: pyproject parsing AND
        # CLI flags ship atomically — no inter-unit window.
        cli_disabled_raw = cli_overrides.get("disabled_rules")
        cli_disabled_rules: frozenset[str]
        if cli_disabled_raw is None:
            cli_disabled_rules = frozenset()
        else:
            cli_disabled_rules = _coerce_r9b_rule_id_list(
                cli_disabled_raw,
                error_label="--disable-rule",
                error_code="cli-option-invalid",
            )
        cli_enabled_raw = cli_overrides.get("enabled_rules")
        cli_enabled_rules: frozenset[str]
        if cli_enabled_raw is None:
            cli_enabled_rules = frozenset()
        else:
            cli_enabled_rules = _coerce_r9b_rule_id_list(
                cli_enabled_raw,
                error_label="--enable-rule",
                error_code="cli-option-invalid",
            )
        pyproject_disabled_rules: frozenset[str] = validated.get(
            "disabled_rules", frozenset(),
        )
        pyproject_enabled_rules: frozenset[str] = validated.get(
            "enabled_rules", frozenset(),
        )
        # CONTRACT: every R9b input source must have a corresponding
        # _expand_custom_prefix call BEFORE _compute_r8b_contradiction_warnings
        # runs. Adding a sixth source (e.g., env-var-only directive) requires
        # extending this block. The contradiction-warning emission compares
        # post-expansion sets — partial expansion produces incorrect
        # contradiction detection.
        #
        # Custom prefix expansion: apply to every R9b set that may
        # contain bare ``custom/<suffix>`` entries. The off-severity
        # set is also subject to expansion because [severities] keys
        # can name custom rules too.
        expanded_off = _expand_custom_prefix(
            off_severity_rule_ids, resolved_custom_annotation_rules,
        )
        expanded_pyp_disabled = _expand_custom_prefix(
            pyproject_disabled_rules, resolved_custom_annotation_rules,
        )
        expanded_cli_disabled = _expand_custom_prefix(
            cli_disabled_rules, resolved_custom_annotation_rules,
        )
        expanded_pyp_enabled = _expand_custom_prefix(
            pyproject_enabled_rules, resolved_custom_annotation_rules,
        )
        expanded_cli_enabled = _expand_custom_prefix(
            cli_enabled_rules, resolved_custom_annotation_rules,
        )
        # Contradictory-R9b-directives warnings. Computed BEFORE the
        # unified-disable merge so the warning text can name BOTH the
        # disable and enable mechanisms (post-merge, both lists would
        # be flattened and attribution would be lost).
        r8b_warnings = _compute_r8b_contradiction_warnings(
            off_severity_ids=expanded_off,
            pyproject_disabled=expanded_pyp_disabled,
            cli_disabled=expanded_cli_disabled,
            pyproject_enabled=expanded_pyp_enabled,
            cli_enabled=expanded_cli_enabled,
            non_off_severity_overrides=frozenset(resolved_severities.keys()),
        )
        # Unified disabled_rules: merge ALL disable sources per the
        # sentinel propagation contract. cli.py subtracts this single
        # set from composed_profile.rule_ids to actuate the suppression
        # without exposing the three-source provenance externally.
        unified_disabled_rules = (
            expanded_off | expanded_pyp_disabled | expanded_cli_disabled
        )
        # enabled_rules: union of pyproject + CLI; kept distinct from
        # disabled_rules (NOT merged into one effective set) so
        # contradiction warnings have the both-sides attribution they
        # need.
        unified_enabled_rules = expanded_pyp_enabled | expanded_cli_enabled

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
            custom_annotation_rules=resolved_custom_annotation_rules,
            disabled_rules=unified_disabled_rules,
            enabled_rules=unified_enabled_rules,
            runtime_warnings=r8b_warnings,
        )


# ---------------------------------------------------------------------------
# pathspec compilation
# ---------------------------------------------------------------------------


def compile_exclude_patterns(
    patterns: Iterable[str],
) -> pathspec.PathSpec:  # type: ignore[type-arg]
    """Compile gitignore-style exclude patterns to a ``pathspec.PathSpec``.

    Wraps ``pathspec.PathSpec.from_lines("gitignore", patterns)`` so
    the CLI's `--exclude` flag and pyproject ``[tool.protokit.lint]
    exclude`` entries share a single compilation path. The returned
    spec is used to filter ``compile_result.root_files`` post-compile
    and pre-``engine.run``.

    The current call site (the exclude-filter block in
    ``protokit.schema.lint.cli``) guards on ``if resolved.exclude:``
    before calling, so the empty-pattern path is not exercised in
    production. An empty iterable would return an empty PathSpec
    that matches nothing, but callers should prefer the truthiness
    guard on a tuple over calling with an empty input.

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
        pyproject-specific code would mis-attribute the source. The
        rejected pattern is newline-sanitized before being
        interpolated into the stderr message.
    """
    # pathspec is highly permissive about gitignore-shaped input —
    # most invalid-looking patterns parse silently and just match
    # nothing. The catch-all here is defense-in-depth: when pathspec
    # DOES raise (a rare GitWildMatchPatternError, or any future
    # exception type), route the failure through the stable
    # ``error[lint-exclude-pattern-invalid]:`` prefix rather than
    # letting an uncaught traceback escape. The exception message
    # body is newline-sanitized before interpolation so a crafted
    # pattern with embedded newlines cannot forge a fake second
    # stderr line.
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
