"""Public library compile entry point for protokit.schema.

Distinct from :func:`protokit._cli_utils.compile_proto` (the compat-CLI
adapter that calls :func:`error_exit` on failure). Library callers use::

    from protokit.schema.compile import compile_protos_to_result

The CLI adapter is preserved unchanged for backward compatibility; new
library code (the lint engine, formatters, plugins) should consume the
:class:`CompileResult` shape returned by :func:`compile_protos_to_result`
instead of catching :class:`SystemExit`.

**Module placement (per pass-2 doc-review S2-2):**
:class:`LintCompileDiagnostic` lives HERE rather than in
``schema/lint/model.py`` to preserve the cold-import contract for
``protokit compat`` — a transitive import of ``schema.lint`` from
``schema.compile`` would defeat the lazy-load guarantee the lint
package is structured around. The :class:`LintReport.diagnostics`
field uses a string forward reference back to this module.

**Re-export policy (per upstream design doc T5):**
This module is NOT re-exported through ``protokit/__init__.py``.
Callers must import directly from ``protokit.schema.compile``.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from google.protobuf import descriptor_pool

from protokit._cli_utils import (
    _compile_with_protoc,
    _compile_with_protoxy,
    _has_protoxy,
)


@dataclass(frozen=True)
class LintCompileDiagnostic:
    """A structured diagnostic emitted during proto compilation.

    Carries enough machine-readable detail for downstream consumers
    (formatters, plugins, the lint engine) to branch on category
    without parsing free-form text. Each compile-failure category in
    :func:`compile_protos_to_result` populates a documented subset
    of fields:

    - **#1 protoxy fallback** (``level="info"``):
      ``message``, ``exception_type`` populated.
    - **#2 protoc subprocess error** (``level="error"``):
      ``message``, ``command``, ``exit_code``, ``stderr``,
      ``exception_type="CalledProcessError"`` populated.
    - **#3 backend missing** (``level="error"``):
      ``message``, ``exception_type="FileNotFoundError"`` populated.
    - **#4 infrastructure error** (``level="error"``):
      ``message``, ``exception_type`` populated.
    - **#5 unexpected backend exception** (``level="error"``):
      ``message`` (with ``repr`` of the exception), ``exception_type``
      populated.
    - **Pre-flight same-basename collision** (``level="error"``):
      ``message`` (lists the colliding paths),
      ``exception_type="SameBasenameCollision"`` populated.

    Attributes:
        level: Severity ladder. ``"info"`` is reserved for the
            protoxy-fallback notice; ``"warning"`` is reserved for
            future use; every actual failure uses ``"error"``.
        message: Human-readable explanation.
        command: For subprocess failures, the argv tuple that ran.
            ``None`` for non-subprocess failures.
        exit_code: For subprocess failures, the non-zero return
            code. ``None`` for non-subprocess failures.
        stderr: For subprocess failures, the captured stderr (with
            trailing whitespace stripped). ``None`` if no stderr
            was captured; ``""`` if stderr was empty.
        exception_type: ``type(exc).__name__`` of the underlying
            exception, or a synthetic name (``"SameBasenameCollision"``)
            for pre-flight rejections. ``None`` only if the
            diagnostic was constructed without an originating
            exception (no current code path does this).
    """

    level: Literal["info", "warning", "error"]
    message: str
    command: tuple[str, ...] | None = None
    exit_code: int | None = None
    stderr: str | None = None
    exception_type: str | None = None

    def __str__(self) -> str:
        """Render as a deterministic single-line human form.

        Format::

            [<level>] <message>[ (<exception_type>)][ cmd=<command> exit=<exit_code>]

        The optional fragments only appear when their backing
        attribute is populated, so successful single-category
        diagnostics stay compact.
        """
        parts = [f"[{self.level}] {self.message}"]
        if self.exception_type is not None:
            parts.append(f"({self.exception_type})")
        if self.command is not None or self.exit_code is not None:
            cmd_str = " ".join(self.command) if self.command is not None else ""
            exit_str = str(self.exit_code) if self.exit_code is not None else ""
            parts.append(f"cmd={cmd_str!r} exit={exit_str}")
        return " ".join(parts)


@dataclass(frozen=True)
class CompileResult:
    """Outcome of a :func:`compile_protos_to_result` call.

    Always returned (never raised); failures surface as entries in
    :attr:`diagnostics` rather than exceptions. Per the
    "all ``Exception`` subclasses produce a Diagnostic" contract,
    only ``BaseException``-but-not-``Exception`` (KeyboardInterrupt,
    SystemExit, GeneratorExit) escapes the dispatch tree.

    Attributes:
        pool: The compiled :class:`DescriptorPool`. Always non-None
            — on irrecoverable failure a fresh empty pool is
            substituted (does NOT contain WKTs; the caller must
            check :attr:`diagnostics` to distinguish "successfully
            compiled nothing" from "failed".)
        root_files: Tuple of ``fd.name`` strings for each input
            ``.proto`` path the user passed (NOT including
            transitive imports). Empty tuple on failure or when
            no input paths were given.
        diagnostics: Tuple of :class:`LintCompileDiagnostic`
            instances. Empty tuple on clean success. On
            both-backend failure (protoxy parse error followed by
            protoc failure), the protoxy-fallback info diagnostic
            comes FIRST per the A2-2 ordering invariant; the
            protoc-failure error diagnostic comes second.
    """

    pool: descriptor_pool.DescriptorPool
    root_files: tuple[str, ...] = ()
    diagnostics: tuple[LintCompileDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        """Snapshot caller-supplied sequences into immutable tuples.

        The dataclass is ``frozen=True``, but a caller could still
        pass a ``list`` for ``root_files`` / ``diagnostics`` and
        mutate it later. We snapshot here so the frozen guarantee
        is real. Mirrors the pattern in
        :class:`protokit.schema.profiles.LintProfile`.
        """
        object.__setattr__(self, "root_files", tuple(self.root_files))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


# ---------------------------------------------------------------------------
# Internal diagnostic factories — one per compile-failure category. Keeping
# them as small private helpers makes the dispatch tree in
# compile_protos_to_result readable line-by-line.
# ---------------------------------------------------------------------------


def _detect_same_basename_collision(
    paths: Sequence[Path],
) -> list[Path] | None:
    """Pre-flight check for the same-basename-different-parent case.

    Both compile backends emit ``fd.name`` as the input path
    relative to whichever ``-I`` directory resolved it. When two
    inputs share a basename but live under different parents, the
    parent-directory auto-include logic produces ambiguous
    ``fd.name`` resolution — a known input-validation error
    distinct from any backend exception.

    Args:
        paths: Sequence of input ``.proto`` file paths.

    Returns:
        Sorted list of colliding paths if 2+ inputs share a
        basename but have different parents; otherwise ``None``.
        Sort order is by string representation, for deterministic
        diagnostic output.
    """
    by_name: dict[str, list[Path]] = {}
    for p in paths:
        by_name.setdefault(p.name, []).append(p)
    for group in by_name.values():
        if len(group) < 2:
            continue
        parents = {p.parent for p in group}
        if len(parents) > 1:
            return sorted(group, key=str)
    return None


def _diagnostic_protoxy_fallback(exc: Exception) -> LintCompileDiagnostic:
    """Build a category #1 info diagnostic (protoxy → protoc fallback)."""
    return LintCompileDiagnostic(
        level="info",
        message="protoxy parse error; falling back to protoc",
        exception_type=type(exc).__name__,
    )


def _diagnostic_protoc_subprocess(
    exc: subprocess.CalledProcessError,
) -> LintCompileDiagnostic:
    """Build a category #2 error diagnostic (protoc subprocess failure)."""
    return LintCompileDiagnostic(
        level="error",
        message="protoc compilation failed",
        command=tuple(str(a) for a in exc.cmd),
        exit_code=exc.returncode,
        stderr=exc.stderr.strip() if exc.stderr else "",
        exception_type="CalledProcessError",
    )


def _diagnostic_backend_missing(
    exc: FileNotFoundError,
) -> LintCompileDiagnostic:
    """Build a category #3 error diagnostic (no compile backend available)."""
    del exc  # Message is fixed; the exception itself carries no useful detail.
    return LintCompileDiagnostic(
        level="error",
        message=(
            "compile backend missing: install protokit[compiler] or "
            "put protoc on PATH"
        ),
        exception_type="FileNotFoundError",
    )


def _diagnostic_infrastructure(exc: BaseException) -> LintCompileDiagnostic:
    """Build a category #4 error diagnostic (OSError / TimeoutExpired)."""
    return LintCompileDiagnostic(
        level="error",
        message=f"compile infrastructure error: {exc}",
        exception_type=type(exc).__name__,
    )


def _diagnostic_unexpected(exc: Exception) -> LintCompileDiagnostic:
    """Build a category #5 error diagnostic (catch-all for Exception)."""
    return LintCompileDiagnostic(
        level="error",
        message=f"unexpected backend exception: {exc!r}",
        exception_type=type(exc).__name__,
    )


def _diagnostic_same_basename_collision(
    colliding: list[Path],
) -> LintCompileDiagnostic:
    """Build the pre-flight error diagnostic for same-basename collisions."""
    return LintCompileDiagnostic(
        level="error",
        message=(
            "multi-path roots with same basename in different parent "
            f"dirs is unsupported: {[str(p) for p in colliding]}"
        ),
        exception_type="SameBasenameCollision",
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def compile_protos_to_result(
    paths: Sequence[Path],
    proto_paths: tuple[str, ...] = (),
) -> CompileResult:
    """Compile one or more ``.proto`` files into a :class:`CompileResult`.

    The library-shaped counterpart to
    :func:`protokit._cli_utils.compile_proto`. Always returns a
    :class:`CompileResult`; never calls :func:`error_exit` and never
    raises on backend failure. Per the A2-1 BaseException posture,
    only ``BaseException``-but-not-``Exception`` (KeyboardInterrupt,
    SystemExit, GeneratorExit) propagates.

    Dispatch:

    1. **Pre-flight:** if 2+ input paths share a basename but live
       under different parent directories, return early with a
       single ``SameBasenameCollision`` diagnostic — neither backend
       is invoked.
    2. **Empty input:** ``paths == []`` returns a
       :class:`CompileResult` with an empty pool, empty
       ``root_files``, and no diagnostics. Semantically: "compiled
       nothing"; not an error.
    3. **Backend dispatch:** if ``protoxy`` is importable, attempt
       it first. On ``ProtoxyError`` / ``ValueError``, append an
       info diagnostic (FIRST in the tuple, per the A2-2 ordering
       invariant) and fall back to ``protoc``. Without ``protoxy``,
       call ``protoc`` directly.
    4. **Failure categorization:** five distinct ``except`` clauses
       map to categories #1–#5 in :class:`LintCompileDiagnostic`.
       Both-backend failure produces TWO diagnostics — the info
       fallback and the protoc-failure error.

    Args:
        paths: Input ``.proto`` file paths. Empty sequence returns
            an empty :class:`CompileResult` (no error).
        proto_paths: Additional ``-I``-style include directories.
            Each input's parent directory is automatically added.

    Returns:
        A :class:`CompileResult`. On any failure, ``pool`` is a
        fresh empty :class:`DescriptorPool` (does NOT contain WKTs),
        ``root_files`` is empty, and ``diagnostics`` carries one or
        two entries describing what went wrong.
    """
    collision = _detect_same_basename_collision(paths)
    if collision:
        return CompileResult(
            pool=descriptor_pool.DescriptorPool(),
            root_files=(),
            diagnostics=(_diagnostic_same_basename_collision(collision),),
        )
    if not paths:
        return CompileResult(pool=descriptor_pool.DescriptorPool())

    diagnostics: list[LintCompileDiagnostic] = []
    pool: descriptor_pool.DescriptorPool | None = None
    root_files: tuple[str, ...] = ()

    try:
        if _has_protoxy():
            import protoxy  # type: ignore[import-not-found]
            try:
                pool, names = _compile_with_protoxy(paths, proto_paths)
                root_files = tuple(names)
            except (protoxy.ProtoxyError, ValueError) as exc:
                # Per A2-2: info-fallback diagnostic comes FIRST so the
                # tuple's leading entry tells the consumer which backend
                # was tried and why protoc was attempted.
                diagnostics.append(_diagnostic_protoxy_fallback(exc))
                # Re-attempt with protoc. Any exception here propagates
                # to the outer catch tree, which appends the SECOND
                # diagnostic (the both-fail composition contract).
                pool, names = _compile_with_protoc(paths, proto_paths)
                root_files = tuple(names)
        else:
            pool, names = _compile_with_protoc(paths, proto_paths)
            root_files = tuple(names)
    except FileNotFoundError as exc:
        diagnostics.append(_diagnostic_backend_missing(exc))
    except subprocess.CalledProcessError as exc:
        diagnostics.append(_diagnostic_protoc_subprocess(exc))
    except subprocess.TimeoutExpired as exc:
        # subprocess.TimeoutExpired is NOT an OSError subclass — it sits
        # under SubprocessError. Listed before OSError so the catch order
        # is unambiguous even though they're disjoint trees today; the
        # current _compile_with_protoc doesn't pass timeout=, so this
        # is defensive coverage for future changes.
        diagnostics.append(_diagnostic_infrastructure(exc))
    except OSError as exc:
        # PermissionError, BrokenPipeError, etc.
        diagnostics.append(_diagnostic_infrastructure(exc))
    except Exception as exc:
        # Catch-all for any other Exception subclass. Crucially this is
        # NOT `except BaseException` — KeyboardInterrupt, SystemExit, and
        # GeneratorExit propagate by design per the A2-1 posture.
        diagnostics.append(_diagnostic_unexpected(exc))

    if pool is None:
        # Irrecoverable failure: substitute a fresh empty pool so
        # CompileResult.pool stays non-Optional. Per the empirical
        # correction, DescriptorPool() does NOT contain WKTs — callers
        # that need WKTs must check diagnostics first.
        pool = descriptor_pool.DescriptorPool()

    return CompileResult(
        pool=pool,
        root_files=root_files,
        diagnostics=tuple(diagnostics),
    )
