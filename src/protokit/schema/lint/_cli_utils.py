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

# ``_safe_for_stderr`` uses the redundant-``as`` form: that is the
# explicit re-export mypy strict's ``no_implicit_reexport`` requires, and
# the ~20 lint-subpackage modules importing it from HERE (its original
# home, before it moved down to ``protokit._cli_utils`` — see the note
# where it used to live) keep working unchanged.
from protokit._cli_utils import (
    _safe_for_stderr as _safe_for_stderr,
)
from protokit._cli_utils import (
    _scrub_exc_message,
    run_formatter_safely,
)
from protokit.schema.compile import CompileResult, LintCompileDiagnostic

if TYPE_CHECKING:
    from protokit.formatters import Formatter, FormatterContext
    from protokit.schema.lint.engine import LintEngine
from protokit.schema.lint.decorator import get_lint_spec
from protokit.schema.lint.model import DuplicateRuleError

# ---------------------------------------------------------------------------
# Stable error-prefix codes (R20a)
# ---------------------------------------------------------------------------

#: Closed set of stable error-prefix codes for ``protokit lint`` exit-2
#: paths. CI scripts can filter on the ``error[lint-`` prefix to detect
#: lint-internal failures vs. click-side flag errors (which keep their
#: own ``Usage:`` prefix per click's defaults).
#:
#: The set was assembled incrementally as the lint CLI grew: input-
#: side codes (bad-input, pool-conflict, missing-imports,
#: compile-failed) landed first; the rule-loading codes (no-rules,
#: unknown-profile, rule-collision, rule-pack-load) followed; and
#: format-unavailable + formatter-exception closed the set. Order is
#: the Reachability Matrix order — stable for documentation and CI
#: grep contracts.
#:
#: Prefix family (stable, closed set per delivery):
#:   info[lint-compile]:                backend info/warning diagnostics in --proto mode
#:   info[lint-pack-profiles]:          R11 per-pack introspection (pack= profiles= ...)
#:   warning[lint-compile]:             backend warning diagnostics in --proto mode
#:   warning[lint-cli]:                 CLI-layer advisories (e.g. ignored flags)
#:   protokit lint: warning [<category>]: runtime-warning stderr family
#:                                         (5 categories at present)
#:   error[lint-CODE]:                  exit-2 paths; CODE must be in this tuple
#:
#: Note: the legacy ``warning[lint-runtime]:`` stderr prefix has
#: been removed and is not restored. Runtime warnings
#: (``rule_exception``, ``unloaded_rule``, ``severities_unloaded_rule``,
#: ``min_severity_relaxed``, ``all_files_excluded``) are carried in
#: ``LintReport.runtime_warnings``. Under ``--format=human`` (the
#: default) they surface on stderr via the CLI-side hook as
#: ``protokit lint: warning [<category>]: <message>`` — see
#: ``_emit_human_runtime_warnings`` in ``cli.py``. Machine
#: formatters (``--format=json`` / ``--format=junit`` /
#: ``--format=sarif``) embed warnings in their structured payloads
#: with no stderr emission.
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
    # Pyproject `[tool.protokit.lint]` discovery / loading errors.
    # Covers walk-up failures, explicit `--config PATH` shadow paths
    # (missing file, unreadable, table-absent, invalid TOML), and any
    # `tomllib.load` triple-arm-guarded failure surface. The message
    # body is newline-sanitized; `TOMLDecodeError` content is replaced
    # with the structured form
    # `TOML parse error at {filename}:{line}:{col}` to prevent
    # raw-bytes echoing per content-safety.
    "pyproject-config-load",
    # Pyproject `[tool.protokit.lint]` schema validation errors —
    # unknown keys, type mismatches, heterogeneous list elements.
    # Distinct from `pyproject-config-load` (parse-time failure) —
    # this code surfaces post-parse-success validation failures.
    "pyproject-config-invalid",
    # `--exclude PATTERN` (CLI) or pyproject `exclude = [...]`
    # contains a pattern that `pathspec.PathSpec.from_lines` rejects.
    # Distinct from `pyproject-config-invalid` because exclude patterns
    # can come from CLI flags, not just pyproject — reusing the
    # pyproject-specific code would mis-attribute the source.
    "exclude-pattern-invalid",
    # R9b directives disabled every rule in the resolved profile. The
    # profile WAS declared (otherwise the `unknown-profile` code would
    # fire); the user has disabled all its rules via `disabled_rules`
    # / `[severities] = "off"` / `--disable-rule`. Fires BEFORE
    # `unknown-profile` so the more specific error wins. Alphabetically
    # inserted.
    "no-rules-after-disable",
    # A CLI `--disable-rule` / `--enable-rule` option value failed
    # format validation. Distinct from `pyproject-config-invalid`
    # (which attributes pyproject-sourced coercion failures) so CI
    # scripts can distinguish a bad CLI flag value from a bad
    # pyproject entry without parsing freeform text.
    "cli-option-invalid",
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
            ``_scrub_exc_message`` (nor ``_safe_for_stderr``) on
            the message itself, since many callers compose
            multi-segment messages where only specific exception
            substrings need scrubbing. Callers interpolating an
            exception apply BOTH layers, as
            ``_safe_for_stderr(_scrub_exc_message(exc))``: the
            inner one redacts ``OSError`` filenames, the outer one
            stops the message forging its own ``error[lint-CODE]:``
            line.

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

# ``_CONTROL_CHAR_TABLE`` / ``_safe_for_stderr`` used to be defined
# here. They moved down to ``protokit._cli_utils`` once the compat side
# needed them too (a formatter exception message can forge an ``Error:``
# line exactly the way a pack name could forge an ``error[lint-`` one);
# this module already imports upward from there, so keeping them here
# would have made the compat-side import circular. ``_safe_for_stderr``
# is re-exported by the import above so the ~20 existing
# ``from protokit.schema.lint._cli_utils import _safe_for_stderr`` sites
# across the lint subpackage keep working unchanged.


def _safe_module_name(module: ModuleType) -> str:
    """Return ``module.__name__`` with embedded control characters replaced.

    Defense-in-depth against attacker-controlled module names flowing
    into ``click.echo`` output lines. Delegates to :func:`_safe_for_stderr`
    so the sanitization scope (newlines, null bytes, ANSI escapes,
    other control chars) stays in lockstep with the canonical helper.
    """
    return _safe_for_stderr(module.__name__)


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
    Literal type (the original discipline was: don't extend the
    locked diagnostic-category set when reuse is semantically clean).

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
    # ce:review follow-up (Finding #2): track pool membership separately
    # from root_files. They are CURRENTLY identical content (the loader
    # treats every fd in fds.file as a "root"), but the semantic meanings
    # diverge: root_files is "files the lint engine emits findings on";
    # pool_names is "files available for cross-file lookups in pre-walks".
    # A future refactor that distinguishes user-passed roots from
    # transitively-bundled --include_imports files needs pool_names to
    # remain the SUPERSET per the CompileResult.pool_file_names docstring's
    # documented invariant. Maintained in parse-order parallel to
    # root_files so the two stay in step.
    pool_names: list[str] = []
    # Capture FileDescriptorProto references BEFORE pool.Add() consumes
    # source_code_info. The Python-level fd reference retains its
    # .source_code_info field for downstream R6 comment-aware rules.
    # When the input descriptor set was built without
    # ``protoc --include_source_info``, each fd's source_code_info.location
    # array will be empty — leading_comment() returns None for every
    # lookup, R6 rules emit findings for every deprecated element (the
    # documented descriptor-set-mode caveat). Mirrors the
    # capture-around-Add pattern at src/protokit/_cli_utils.py:264-267
    # (_populate_pool_with_capture).
    source_info_descriptors: dict[
        str, descriptor_pb2.FileDescriptorProto,
    ] = {}

    for input_path in paths:
        try:
            data = input_path.read_bytes()
            fds = descriptor_pb2.FileDescriptorSet.FromString(data)
        except (OSError, DecodeError) as exc:
            error_exit_with_code(
                "bad-input",
                f"{input_path}: {_safe_for_stderr(_scrub_exc_message(exc))}",
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
                # Dedup-skipped fds are NOT inserted into the accumulator
                # — symmetric with their absence from pool.Add. The
                # invariant is: source_info_descriptors keys exactly
                # match the set of fd.name strings that made it into
                # the pool.
                continue
            seen_names.add(fd.name)
            # PRE-ADD capture: pool.Add(fd) consumes source_code_info
            # regardless of fd's serialized state, so the capture must
            # precede Add. See the _populate_pool_with_capture
            # docstring at src/protokit/_cli_utils.py:230-238 for the
            # load-bearing invariant this mirrors.
            source_info_descriptors[fd.name] = fd
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
                            f"{_safe_for_stderr(_scrub_exc_message(exc))}. "
                            "Rebuild the descriptor set with "
                            "'protoc --include_imports' or include "
                            "WKT descriptor files."
                        ),
                    )
                # Either explicit duplicate-symbol or unmatched —
                # both route to pool-conflict (legacy behavior
                # preserved for unmatched paths).
                # The partial source_info_descriptors state (carrying
                # the failing fd's entry) is harmlessly discarded by
                # SystemExit — no caller observes the partial dict
                # because the CompileResult is never constructed on
                # this path.
                error_exit_with_code(
                    "pool-conflict",
                    f"{input_path}: {_safe_for_stderr(_scrub_exc_message(exc))}",
                )
            root_files.append(fd.name)
            pool_names.append(fd.name)

    return CompileResult(
        pool=pool,
        root_files=tuple(root_files),
        # pool_file_names tracks pool membership via the parallel
        # `pool_names` list (NOT root_files; the rename was a
        # code-review follow-up),
        # so the invariant set(pool_file_names) >= set(root_files) is
        # source-of-truth-driven rather than incidental. Today the two
        # lists are identical content because this loader treats every fd
        # in fds.file as a root, but the rename future-proofs against a
        # refactor that distinguishes user-passed roots from
        # transitively-bundled --include_imports files. Dedup-skipped fds
        # (continue branch above) are absent from both lists, preserving
        # the invariant.
        pool_file_names=tuple(pool_names),
        # CompileResult.__post_init__ wraps the dict in MappingProxyType
        # per the U1-established pattern at
        # src/protokit/schema/compile.py:225-229. We pass a plain dict
        # here; the wrap is automatic.
        source_info_descriptors=source_info_descriptors,
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
            f"{type(exc).__name__}: {_safe_for_stderr(_scrub_exc_message(exc))}",
        )

    try:
        engine.load_rule_pack(module)
    except DuplicateRuleError as exc:
        error_exit_with_code(
            "rule-collision",
            f"pack {module_name!r}: {_safe_for_stderr(_scrub_exc_message(exc))}",
        )
    except AttributeError as exc:
        error_exit_with_code(
            "rule-pack-load",
            f"kind=shape: pack {module_name!r} has no RULES attribute "
            f"(engine reported: {_safe_for_stderr(_scrub_exc_message(exc))})",
        )
    except TypeError as exc:
        error_exit_with_code(
            "rule-pack-load",
            f"kind=shape: pack {module_name!r} has wrong RULES wire "
            f"format: {_safe_for_stderr(_scrub_exc_message(exc))}. lint expects "
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
