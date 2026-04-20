"""Module-level singleton registry for output formatters.

The registry maps ``(FormatterKind, name)`` keys to formatter
callables. A separate ``_BUILTIN_NAMES`` set records the names
that built-in formatters claim so user-supplied packs cannot
silently shadow them.

Names are normalised to lowercase to preserve the
case-insensitive behaviour the CLI's ``--format`` flag has had
since it was a ``click.Choice``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable


class FormatterKind(Enum):
    """Which report shape a formatter consumes.

    Each kind corresponds to one of the report types produced
    by protokit's CLIs:

    Members:
        DIFF: ``protokit.message.DiffResult`` — structural diff
            between two protobuf messages produced by
            ``protokit diff``.
        COMPAT: ``protokit.schema.CompatibilityReport`` — single
            schema-pair compatibility check produced by
            ``protokit compat check`` and ``ci``.
        COMPAT_HISTORY: ``protokit.schema.HistoryReport`` —
            multi-commit walk produced by
            ``protokit compat history``.
        COMPAT_BISECT: ``protokit.schema.BisectReport`` —
            range-bisect result produced by
            ``protokit compat bisect``.

    Naming convention for future kinds: noun form (e.g.
    ``LINT_REPORT``, ``SCHEMA_DIFF``) for consistency with the
    existing ``COMPAT_*`` names. ``Enum`` (not ``IntEnum``) so
    new members can be appended without re-numbering existing
    ones.
    """

    DIFF = "DIFF"
    COMPAT = "COMPAT"
    COMPAT_HISTORY = "COMPAT_HISTORY"
    COMPAT_BISECT = "COMPAT_BISECT"


@dataclass(frozen=True)
class FormatterContext:
    """Side-channel context passed to formatters alongside a report.

    Carries CLI invocation context that a formatter may want to
    embed in its output (e.g., target type FQN in a JUnit
    testsuite name) or surface as metadata. All fields except
    ``subcommand`` are optional — formatters should treat
    ``None`` defensively.

    Attributes:
        subcommand: Human-readable subcommand identifier
            (``"diff"``, ``"compat-check"``, ``"compat-history"``,
            ``"compat-bisect"``, ``"compat-ci"``). Used for suite
            naming and operator identification.
        target_type: Fully-qualified protobuf message type FQN
            when the user passed ``--type NAME`` and both sides
            agree. ``None`` for cross-type comparisons (use
            ``old_target_type`` / ``new_target_type``) and for
            subcommands without a single type.
        old_target_type: Old-side type FQN when the user passed
            ``--old-type``. ``None`` otherwise.
        new_target_type: New-side type FQN when the user passed
            ``--new-type``. ``None`` otherwise.
        level: Compatibility profile name as the user supplied it
            on ``--level`` (CLI-flag form, e.g. ``"consumer-safe"``,
            NOT enum name ``"CONSUMER_SAFE"``). ``None`` for diff.
        range_spec: Range expression as the user supplied it on
            git-mode subcommands (e.g. ``"HEAD~5..HEAD"``).
        old_ref: Resolved SHA of the old endpoint in git-mode.
        new_ref: Resolved SHA of the new endpoint in git-mode.
        proto_file: Import-relative ``.proto`` file path passed
            to git-mode subcommands.
    """

    subcommand: str
    target_type: str | None = None
    old_target_type: str | None = None
    new_target_type: str | None = None
    level: str | None = None
    range_spec: str | None = None
    old_ref: str | None = None
    new_ref: str | None = None
    proto_file: str | None = None


# ``Any`` for the report parameter is deliberate: each
# ``FormatterKind`` dispatches at runtime to a different
# concrete report type (DiffResult / CompatibilityReport /
# HistoryReport / BisectReport). Static narrowing belongs to
# the formatter author, not this alias — narrowing here would
# break user-supplied formatters that consume more than one
# kind via runtime dispatch.
Formatter = Callable[[Any, FormatterContext], str]


# Module-level singletons. Mutated at built-in registration time
# (Unit 3+) and at CLI startup when the user passes
# ``--formatter-module``. Tests should call
# :func:`clear_user_formatters` between cases or use a fixture
# that restores the registry.
_REGISTRY: dict[tuple[FormatterKind, str], Formatter] = {}
_BUILTIN_NAMES: set[tuple[FormatterKind, str]] = set()


class FormatterError(Exception):
    """Base class for formatter-registration errors.

    Distinct from ``KeyError`` (raised by ``get_formatter`` for
    missing names) so callers can disambiguate registration
    problems from lookup problems without catching both.
    """


def register_formatter(
    name: str,
    fn: Formatter,
    *,
    kind: FormatterKind,
    replace: bool = False,
) -> None:
    """Register a formatter under ``(kind, name.lower())``.

    Three guard rails:

    1. **Built-in names are reserved.** Attempting to register
       under a key in ``_BUILTIN_NAMES`` raises ``FormatterError``
       even with ``replace=True``. This prevents a third-party
       ``--formatter-module`` from silently shadowing protokit's
       own ``human`` / ``json`` / ``junit`` / ``sarif`` outputs.
    2. **Non-built-in re-registration is opt-in.** If
       ``(kind, name)`` is already in the registry and
       ``replace`` is False, raises ``FormatterError``. Pass
       ``replace=True`` to deliberately override.
    3. **Names are case-insensitive.** Stored as lowercase so
       the CLI's resolved value (whatever case the user typed)
       hits the same entry.

    Args:
        name: Formatter name as the user types it on
            ``--format``. Lowercased internally.
        fn: Callable accepting ``(report, FormatterContext)`` and
            returning the formatted output as a ``str``.
            Formatters MUST be pure str-returning functions —
            side-effect writes to stdout/stderr are unsupported
            and the CLI guards against them.
        kind: Which report shape ``fn`` consumes.
        replace: When True, allow overwriting an existing
            non-built-in registration. Has no effect on built-in
            names — those always raise.

    Raises:
        FormatterError: Built-in shadowing, or non-replace
            re-registration of an existing name.
    """
    key = (kind, name.lower())
    if key in _BUILTIN_NAMES:
        raise FormatterError(
            f"cannot override built-in formatter ({kind.value}, {name.lower()!r}); "
            "built-in names are reserved"
        )
    if key in _REGISTRY and not replace:
        raise FormatterError(
            f"formatter ({kind.value}, {name.lower()!r}) already registered; "
            "pass replace=True to override"
        )
    _REGISTRY[key] = fn


def _register_builtin(
    name: str,
    fn: Formatter,
    *,
    kind: FormatterKind,
) -> None:
    """Register a built-in formatter and mark its name reserved.

    Internal helper used by ``protokit.formatters._builtin_*``
    modules at package-import time. The reservation is what
    makes ``register_formatter`` reject user attempts to shadow
    a built-in name later. Idempotent: re-registering the same
    built-in (e.g. due to a test reload) replaces the callable
    without raising.
    """
    key = (kind, name.lower())
    _BUILTIN_NAMES.add(key)
    _REGISTRY[key] = fn


def get_formatter(name: str, kind: FormatterKind) -> Formatter:
    """Look up a registered formatter.

    Args:
        name: Formatter name (case-insensitive).
        kind: Which kind to look in.

    Returns:
        The registered callable.

    Raises:
        KeyError: No formatter is registered under ``(kind, name)``.
            Callers (typically the CLI) should catch this and
            translate to ``error_exit`` with the available list
            for context.
    """
    return _REGISTRY[(kind, name.lower())]


def list_formatters(kind: FormatterKind) -> list[str]:
    """Return all registered formatter names for ``kind``.

    Returns:
        A sorted list of lowercase names. Sorted so error
        messages and ``--help`` output are deterministic.
    """
    return sorted(name for (k, name) in _REGISTRY if k is kind)


def clear_user_formatters() -> None:
    """Remove every registration that is not a reserved built-in.

    Intended for test fixtures and dev-time module reloads. The
    built-in registrations stay in place (their entries in
    ``_REGISTRY`` come from the same package import that
    populated ``_BUILTIN_NAMES``, so they remain available).
    """
    for key in list(_REGISTRY.keys()):
        if key not in _BUILTIN_NAMES:
            del _REGISTRY[key]


def load_formatter_pack(module: Any) -> None:
    """Load a user-supplied formatter pack module.

    A pack module exposes a ``FORMATTERS`` attribute, an
    iterable of ``(name, fn, kind)`` 3-tuples. The loader runs
    in **two phases**:

    1. **Stage**: read ``module.FORMATTERS`` and validate every
       entry is the expected shape. ``AttributeError`` propagates
       when ``FORMATTERS`` is missing; ``TypeError`` propagates
       when an entry is not a 3-tuple of the right types.
    2. **Commit**: register each staged entry via
       :func:`register_formatter`. If any registration fails
       (built-in collision, duplicate without ``replace=True``),
       the loader rolls back any registrations it made earlier
       in this call so partial state never reaches the live
       registry.

    Two-phase load matters because ``--formatter-module`` is
    repeatable — a malformed entry deep in one pack must not
    leave half-loaded formatters from earlier packs.

    Args:
        module: Imported Python module (typically returned by
            ``importlib.import_module``).
    """
    formatters_attr = module.FORMATTERS  # AttributeError propagates
    staged: list[tuple[str, Formatter, FormatterKind]] = []
    for entry in formatters_attr:
        if not (isinstance(entry, tuple) and len(entry) == 3):
            raise TypeError(
                f"formatter pack {module.__name__!r}: "
                f"each FORMATTERS entry must be a (name, fn, kind) tuple, "
                f"got {entry!r}"
            )
        name, fn, kind = entry
        if not isinstance(name, str):
            raise TypeError(
                f"formatter pack {module.__name__!r}: name must be str, "
                f"got {type(name).__name__}"
            )
        if not isinstance(kind, FormatterKind):
            raise TypeError(
                f"formatter pack {module.__name__!r}: kind must be FormatterKind, "
                f"got {type(kind).__name__}"
            )
        if not callable(fn):
            raise TypeError(
                f"formatter pack {module.__name__!r}: fn must be callable, "
                f"got {type(fn).__name__}"
            )
        staged.append((name, fn, kind))

    # Commit phase. Track what we registered so we can roll back
    # on partial failure. Catch ``Exception`` (not just
    # ``FormatterError``) so any unexpected error inside
    # ``register_formatter`` still triggers cleanup — fail-loud
    # but never leave the registry half-loaded.
    committed: list[tuple[FormatterKind, str]] = []
    try:
        for name, fn, kind in staged:
            register_formatter(name, fn, kind=kind)
            committed.append((kind, name.lower()))
    except Exception:
        for key in committed:
            # Only delete entries we ourselves added — never touch
            # a built-in (we couldn't have added it; built-in
            # registration goes through _register_builtin).
            if key in _REGISTRY and key not in _BUILTIN_NAMES:
                del _REGISTRY[key]
        raise
