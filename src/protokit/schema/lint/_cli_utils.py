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

import sys
from pathlib import Path
from typing import NoReturn

import click
from google.protobuf import descriptor_pb2, descriptor_pool
from google.protobuf.message import DecodeError

from protokit._cli_utils import _scrub_exc_message
from protokit.schema.compile import CompileResult, LintCompileDiagnostic

# ---------------------------------------------------------------------------
# Stable error-prefix codes (R20a)
# ---------------------------------------------------------------------------

#: Closed set of stable error-prefix codes for ``protokit lint`` exit-2
#: paths. CI scripts can filter on the ``error[lint-`` prefix to detect
#: lint-internal failures vs. click-side flag errors (which keep their
#: own ``Usage:`` prefix per click's defaults).
#:
#: This is U2's initial set; U3 extends with rule-loading codes
#: (``no-rules``, ``unknown-profile``, ``rule-collision``,
#: ``rule-pack-load``); U4a extends with ``format-unavailable`` and
#: ``formatter-exception``. The full D3 list (10 codes) lives in the
#: plan's R20a Reachability Matrix.
_LINT_ERROR_CODES: tuple[str, ...] = (
    "bad-input",
    "pool-conflict",
    "missing-imports",
    "compile-failed",
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


# ---------------------------------------------------------------------------
# Descriptor-set ingestion (R24)
# ---------------------------------------------------------------------------

# Substrings that route a ``descriptor_pool.DescriptorPool.Add`` TypeError
# to ``error[lint-missing-imports]:`` rather than the default
# ``error[lint-pool-conflict]:``. Verified empirically against
# google.protobuf-python's C++ runtime output (see plan U2 test
# obligation).
_MISSING_IMPORT_MARKERS = (
    "has not been loaded",
    "couldn't resolve name",
)

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
