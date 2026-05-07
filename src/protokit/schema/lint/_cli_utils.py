"""Shared CLI helpers for ``protokit lint``.

Internal extraction point for the ``protokit.schema.lint.cli`` click
subcommand. The ``_`` prefix marks the module as not-public-API —
consumers invoke the CLI, they do not import from here.

This module is loaded only when ``protokit.schema.lint.cli`` itself
is loaded, which happens at ``protokit.cli`` import time (i.e., on
every ``protokit ...`` CLI invocation, regardless of subcommand).
The cold-import contract from D1 is preserved because
``protokit.schema`` does NOT import ``protokit.cli``.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, NoReturn

import click
from google.protobuf import descriptor_pb2, descriptor_pool
from google.protobuf.message import DecodeError

from protokit._cli_utils import _scrub_exc_message, run_formatter_safely
from protokit.schema.compile import CompileResult, LintCompileDiagnostic

if TYPE_CHECKING:
    from protokit.formatters import Formatter, FormatterContext
from protokit.schema.lint.decorator import get_lint_spec
from protokit.schema.lint.engine import LintEngine
from protokit.schema.lint.model import DuplicateRuleError

# ---------------------------------------------------------------------------
# Stable error-prefix codes (R20a)
# ---------------------------------------------------------------------------

#: Closed set of stable error-prefix codes for ``protokit lint`` exit-2
#: paths. CI scripts can filter on the ``error[lint-`` prefix to detect
#: lint-internal failures vs. click-side flag errors (which keep their
#: own ``Usage:`` prefix per click's defaults).
#:
#: U2 shipped the input-side codes (bad-input, pool-conflict,
#: missing-imports, compile-failed); U3 added the rule-loading codes
#: (no-rules, unknown-profile, rule-collision, rule-pack-load);
#: U4a closes the set with format-unavailable and formatter-exception.
#: Order is the R20a Reachability Matrix order — stable for
#: documentation and CI grep contracts.
#:
#: Prefix family (stable, closed set per delivery):
#:   info[lint-compile]:    backend info/warning diagnostics in --proto mode
#:   warning[lint-compile]: backend warning diagnostics in --proto mode
#:   warning[lint-runtime]: engine runtime warnings (rule_exception, unloaded_rule)
#:   warning[lint-cli]:     CLI-layer advisories (e.g. ignored flags)
#:   error[lint-CODE]:      exit-2 paths; CODE must be in this tuple
_LINT_ERROR_CODES: tuple[str, ...] = (
    "no-rules",
    "unknown-profile",
    "format-unavailable",
    "compile-failed",
    "formatter-exception",
    "bad-input",
    "pool-conflict",
    "missing-imports",
    "rule-collision",
    "rule-pack-load",
)


def error_exit_with_code(code: str, message: str) -> NoReturn:
    """Emit ``error[lint-<code>]: <message>`` to stderr and exit 2.

    Stable-prefix-code surface for lint's exit-2 paths. CI scripts
    that need to distinguish lint-internal failures from click-side
    flag errors filter on ``error[lint-`` specifically; click usage
    errors carry click's own ``Usage:`` prefix and never route
    through this helper.

    The ``code`` MUST be a member of :data:`_LINT_ERROR_CODES`.
    Validation is via ``assert`` rather than a soft fall-through:
    surfacing implementation drift between the constant and call
    sites as a hard test failure beats silently writing an
    undeclared prefix that CI scripts then learn to depend on.

    Args:
        code: Short identifier (no ``lint-`` prefix; the helper
            prepends it). Must be in :data:`_LINT_ERROR_CODES`.
        message: Human-readable explanation. Already-scrubbed by
            the caller — this helper does NOT call
            ``_scrub_exc_message`` on the message itself, since
            many callers compose multi-segment messages where
            only specific exception substrings need scrubbing.

    Raises:
        AssertionError: If ``code`` is not in the closed set.
            Hard test failure; never falls through to write an
            undeclared prefix.
        SystemExit: Always (exit code 2).
    """
    # Use an explicit raise (not assert) so the validation survives
    # `python -O` / `PYTHONOPTIMIZE=1` — assertions are stripped under
    # optimization mode and the guard would silently degrade in
    # production CI containers that pass `-O`.
    if code not in _LINT_ERROR_CODES:
        raise AssertionError(
            f"undeclared lint error code: {code!r} "
            f"(known: {_LINT_ERROR_CODES})"
        )
    click.echo(f"error[lint-{code}]: {message}", err=True)
    sys.exit(2)


def _run_lint_formatter_safely(
    fn: Formatter, report: object, ctx: FormatterContext, *, name: str,
) -> str:
    """Lint-side wrapper around ``run_formatter_safely``.

    Routes the four formatter contract violations (SystemExit,
    generic Exception, stdout-leak, non-str return) through
    ``error_exit_with_code("formatter-exception", ...)`` so they
    land under the lint stable-prefix family on stderr.
    """
    def lint_error_exit(msg: str) -> NoReturn:
        error_exit_with_code("formatter-exception", msg)

    return run_formatter_safely(
        fn, report, ctx, name=name, error_exit_fn=lint_error_exit,
    )


# ---------------------------------------------------------------------------
# Descriptor-set ingestion (R24)
# ---------------------------------------------------------------------------

# Substrings that route a ``descriptor_pool.DescriptorPool.Add`` TypeError
# to ``error[lint-missing-imports]:`` rather than the default
# ``error[lint-pool-conflict]:``. Verified empirically against
# google.protobuf-python's C++ runtime output (see plan U2 test
# obligation).
_MISSING_IMPORT_MARKERS: tuple[str, ...] = (
    "has not been loaded",
    "couldn't resolve name",
)

def _safe_module_name(module: ModuleType) -> str:
    """Return ``module.__name__`` with embedded newlines collapsed to spaces.

    Defense-in-depth against attacker-controlled module names flowing
    into ``click.echo`` output lines. Newlines in a module ``__name__``
    are pathological but theoretically injectable; collapsing them
    prevents multi-line injection into single-line output fields.
    """
    return module.__name__.replace("\n", " ").replace("\r", " ")


def _load_descriptor_sets_to_result(
    paths: tuple[Path, ...],
) -> CompileResult:
    """Merge one or more ``.descriptor_set`` files into a CompileResult.

    Algorithm:

    1. Iterate ``paths`` in argv order.
    2. For each path, ``read_bytes()`` and ``FileDescriptorSet.FromString()``.
       OSError or DecodeError → exit 2 via ``lint-bad-input``.
    3. Iterate ``fds.file`` in protobuf parse order. For each ``fd``:

       - If ``fd.name`` was already seen, append a ``LintCompileDiagnostic``
         with ``category="same_basename_collision"`` (semantic stretch:
         the closed-set Literal's nearest match — see "Trust model"
         note below) and skip. First occurrence wins.
       - Else add to ``seen_names``, call ``pool.Add(fd)``, append
         ``fd.name`` to ``root_files``.

    4. ``pool.Add(fd)`` may raise ``TypeError`` for two distinct
       reasons that share the exception type. We discriminate via
       message-text matching:

       - ``has not been loaded`` / ``couldn't resolve name`` →
         ``lint-missing-imports`` (descriptor_set missing transitive
         dependency files; most often produced by ``protoc`` without
         ``--include_imports``).
       - ``duplicate symbol`` → ``lint-pool-conflict`` (cross-set
         collision: two paths define the same FQN under different
         file names).
       - Unmatched → falls through to ``lint-pool-conflict`` with
         the raw exception text (preserves legacy behavior; future
         protobuf versions that change message wording surface
         here rather than misroute).

    5. Returns a ``CompileResult`` with ``diagnostics`` carrying the
       duplicate-filename info entries — formatters in any output
       format (``human``/``json``/``junit``/``sarif``) can surface
       them uniformly.

    **Trust model**: descriptor-set files are trusted build artifacts
    from the operator's own build system. No size cap is enforced
    before ``read_bytes()`` / ``FileDescriptorSet.FromString()``.
    Stderr error messages may include proto file paths and
    fully-qualified type names from the analyzed schemas; operators
    treating these as sensitive should redirect stderr to a secured
    log sink.

    The ``same_basename_collision`` category is reused here for
    descriptor-set duplicate-filename diagnostics. The category was
    originally introduced for ``protoc`` pre-flight basename-collision
    detection (two ``.proto`` files with the same basename in
    different directories). The user-facing meaning generalizes to
    "you passed two inputs that conflict on file name" cleanly
    enough to avoid extending the closed-set ``DiagnosticCategory``
    Literal type (per origin KD-8: don't extend D2's locked types
    in D3 when avoidable).

    Args:
        paths: One or more ``.descriptor_set`` paths (absolute or
            relative). Click validates path existence + non-directory
            via ``Path(exists=True, dir_okay=False)`` before this
            helper runs.

    Returns:
        A ``CompileResult`` with the merged ``DescriptorPool``,
        ``root_files`` ordered by argv-then-parse-order with
        first-occurrence-wins dedup, and any duplicate-filename
        diagnostics surfaced via ``diagnostics``.

    Raises:
        SystemExit: Via :func:`error_exit_with_code` for any of:
            ``bad-input`` (read or parse failure),
            ``missing-imports`` (TypeError matching missing-import
            markers), ``pool-conflict`` (TypeError matching
            duplicate-symbol marker, or unmatched).
    """
    pool = descriptor_pool.DescriptorPool()
    seen_names: set[str] = set()
    duplicates: list[LintCompileDiagnostic] = []
    root_files: list[str] = []

    for input_path in paths:
        try:
            data = input_path.read_bytes()
            fds = descriptor_pb2.FileDescriptorSet.FromString(data)
        except (OSError, DecodeError) as exc:
            error_exit_with_code(
                "bad-input",
                f"{input_path}: {_scrub_exc_message(exc)}",
            )

        for fd in fds.file:
            if fd.name in seen_names:
                duplicates.append(
                    LintCompileDiagnostic(
                        level="info",
                        message=(
                            f"deduplicated duplicate file path "
                            f"{fd.name!r} across input sets "
                            f"(first occurrence wins)"
                        ),
                        category="same_basename_collision",
                    )
                )
                continue
            seen_names.add(fd.name)
            try:
                pool.Add(fd)
            except (TypeError, ValueError) as exc:
                # protobuf-python's C++ runtime raises TypeError for
                # the documented failure shapes (missing-imports,
                # duplicate-symbol). The (TypeError, ValueError) catch
                # mirrors compile.py:403's defensive over-catch — if a
                # future protobuf release narrows or widens the
                # exception type, lint's stable-prefix path stays
                # intact rather than letting ValueError escape to
                # click as exit 1 + traceback (no error[lint-...]
                # prefix).
                msg = str(exc)
                if any(marker in msg for marker in _MISSING_IMPORT_MARKERS):
                    error_exit_with_code(
                        "missing-imports",
                        (
                            f"{input_path}: "
                            f"{_scrub_exc_message(exc)}. "
                            "Rebuild the descriptor set with "
                            "'protoc --include_imports' or include "
                            "WKT descriptor files."
                        ),
                    )
                # Either explicit duplicate-symbol or unmatched —
                # both route to pool-conflict (legacy behavior
                # preserved for unmatched paths).
                error_exit_with_code(
                    "pool-conflict",
                    f"{input_path}: {_scrub_exc_message(exc)}",
                )
            root_files.append(fd.name)

    return CompileResult(
        pool=pool,
        root_files=tuple(root_files),
        diagnostics=tuple(duplicates),
    )


# ---------------------------------------------------------------------------
# User rule-pack loading (R8)
# ---------------------------------------------------------------------------


def _load_user_rule_pack(
    module_name: str, engine: LintEngine,
) -> ModuleType:
    """Import ``module_name`` and load its ``RULES`` into ``engine``.

    Wraps three failure modes into the single ``rule-pack-load``
    stable error code with a discriminating ``kind=`` token in the
    message body so CI scripts can branch on the failure mode
    without parsing freeform text:

    - ``kind=import``: ``importlib.import_module`` raised any
      ``Exception`` (module path typo, missing install, broken
      ``__init__.py``, top-level ``NameError`` /
      ``ZeroDivisionError`` / etc.) OR raised ``SystemExit`` —
      the latter would otherwise bypass the broad ``except
      Exception`` and produce a false-green CI exit if a user
      pack's module body called ``sys.exit(0)``. The
      ``except SystemExit`` guard is FIRST in the chain.
    - ``kind=shape``: import succeeded but
      ``engine.load_rule_pack`` raised ``TypeError`` (most
      commonly because ``RULES`` contains compat-style
      ``(rule_id, fn)`` tuples instead of ``@lint_rule``-decorated
      callables — or any entry without a ``_lint_spec``
      attribute).

    Plus ``DuplicateRuleError`` from ``engine.load_rule_pack``
    routes to the separate ``rule-collision`` code, since that's
    a different remediation (rename a rule_id, not fix a wire
    format).

    Args:
        module_name: Fully-qualified Python module path (e.g.,
            ``acme.lint_rules``). Passed to
            ``importlib.import_module``.
        engine: The ``LintEngine`` to register the pack into.

    Returns:
        The successfully-imported module object (so the caller
        can introspect ``module.RULES`` or ``module.__name__``
        for downstream rendering, e.g., R25 provenance).

    Raises:
        SystemExit: Via :func:`error_exit_with_code` for any of:
            ``rule-pack-load`` (import or wire-format failure),
            ``rule-collision`` (cross-pack rule_id collision).
    """
    try:
        module = importlib.import_module(module_name)
    except SystemExit as exc:
        error_exit_with_code(
            "rule-pack-load",
            f"kind=import: pack {module_name!r} called sys.exit("
            f"{exc.code!r}) at module-body load time",
        )
    except KeyboardInterrupt:
        error_exit_with_code(
            "rule-pack-load",
            f"kind=import: pack {module_name!r} raised KeyboardInterrupt "
            f"at module-body load time",
        )
    except Exception as exc:  # noqa: BLE001 -- mirrors compat's load_formatter_packs broad catch
        error_exit_with_code(
            "rule-pack-load",
            f"kind=import: failed to import pack {module_name!r}: "
            f"{type(exc).__name__}: {_scrub_exc_message(exc)}",
        )

    try:
        engine.load_rule_pack(module)
    except DuplicateRuleError as exc:
        error_exit_with_code(
            "rule-collision",
            f"pack {module_name!r}: {_scrub_exc_message(exc)}",
        )
    except AttributeError as exc:
        error_exit_with_code(
            "rule-pack-load",
            f"kind=shape: pack {module_name!r} has no RULES attribute "
            f"(engine reported: {_scrub_exc_message(exc)})",
        )
    except TypeError as exc:
        error_exit_with_code(
            "rule-pack-load",
            f"kind=shape: pack {module_name!r} has wrong RULES wire "
            f"format: {_scrub_exc_message(exc)}. lint expects "
            f"RULES = (decorated_fn, ...); compat's "
            f"RULES = ((rule_id, fn), ...) is incompatible. See "
            f"docs/solutions/best-practices/audit-wire-format-"
            f"before-claiming-sibling-parity-2026-05-03.md",
        )

    return module


def _declared_profiles_per_pack(
    packs: tuple[ModuleType, ...],
) -> dict[str, frozenset[str]]:
    """Map ``module.__name__`` to the set of profile names its rules declare.

    Used by R11's unknown-profile error message (``Pack X declares
    profiles: {a, b}``) and by R25's provenance line (which lists
    contributing rule_ids per pack — see
    :func:`_active_rule_ids_per_pack`).

    Args:
        packs: Successfully-loaded pack module objects (each
            exposing a ``RULES`` tuple of ``@lint_rule``-decorated
            callables).

    Returns:
        Dict from ``module.__name__`` to the union of all profile
        names declared by any rule in that pack's ``RULES`` tuple.
    """
    result: dict[str, frozenset[str]] = {}
    for pack in packs:
        declared: set[str] = set()
        for fn in getattr(pack, "RULES", ()):
            spec = get_lint_spec(fn)
            declared.update(spec.profiles)
        result[pack.__name__] = frozenset(declared)
    return result


def _active_rule_ids_per_pack(
    packs: tuple[ModuleType, ...],
    active_rule_ids: frozenset[str],
) -> dict[str, list[str]]:
    """Map ``module.__name__`` to the rule_ids contributing to the active profile.

    Walks each pack's ``RULES`` tuple and intersects the rule_id
    set with ``active_rule_ids`` (the resolved profile's
    ``rule_ids``). Used by R25's provenance line to render
    ``PACK=[rid1,rid2]`` per loaded pack.

    Args:
        packs: Successfully-loaded pack module objects.
        active_rule_ids: The composed profile's ``rule_ids``
            field — only rule_ids in this set are "active" in
            the run.

    Returns:
        Dict from ``module.__name__`` to a sorted list of
        rule_ids from that pack that contribute to the active
        profile. Packs with zero active rule_ids appear with an
        empty list. Packs appear in argv insertion order:
        BUILTIN_PACKS first, then ``--rule-pack`` argv order.
        Within each pack, rule_ids are sorted lexicographically.
    """
    result: dict[str, list[str]] = {}
    for pack in packs:
        contributing: list[str] = []
        for fn in getattr(pack, "RULES", ()):
            spec = get_lint_spec(fn)
            if spec.rule_id in active_rule_ids:
                contributing.append(spec.rule_id)
        result[pack.__name__] = sorted(contributing)
    return result
