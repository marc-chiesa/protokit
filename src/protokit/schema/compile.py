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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

from google.protobuf import descriptor_pool

from protokit._cli_utils import (
    _compile_with_protoc,
    _compile_with_protoxy,
    _has_protoxy,
)

if TYPE_CHECKING:
    from google.protobuf.descriptor_pb2 import FileDescriptorProto

DiagnosticCategory = Literal[
    "protoxy_fallback",
    "protoc_subprocess",
    "backend_missing",
    "infrastructure",
    "unexpected",
    "same_basename_collision",
]
"""Closed set of diagnostic categories.

Agents and formatters should branch on this rather than on
``exception_type``. ``exception_type`` is open-ended (any
``Exception`` subclass name reaches category ``"unexpected"``);
this Literal is the stable, exhaustive discriminator.
"""


@dataclass(frozen=True)
class LintCompileDiagnostic:
    """A structured diagnostic emitted during proto compilation.

    Carries enough machine-readable detail for downstream consumers
    (formatters, plugins, the lint engine) to branch on category
    without parsing free-form text. Each compile-failure category in
    :func:`compile_protos_to_result` populates a documented subset
    of fields:

    - **#1 protoxy fallback** (``category="protoxy_fallback"``,
      ``level="info"``): ``message``, ``exception_type`` populated.
    - **#2 protoc subprocess error** (``category="protoc_subprocess"``,
      ``level="error"``): ``message``, ``command``, ``exit_code``,
      ``stderr``, ``exception_type="CalledProcessError"`` populated.
    - **#3 backend missing** (``category="backend_missing"``,
      ``level="error"``): ``message``,
      ``exception_type="FileNotFoundError"`` populated.
    - **#4 infrastructure error** (``category="infrastructure"``,
      ``level="error"``): ``message``, ``exception_type`` populated.
    - **#5 unexpected backend exception** (``category="unexpected"``,
      ``level="error"``): ``message`` (with ``repr`` of the
      exception), ``exception_type`` populated.
    - **Pre-flight same-basename collision**
      (``category="same_basename_collision"``, ``level="error"``):
      ``message`` (lists the colliding paths),
      ``exception_type="SameBasenameCollision"`` populated.

    Attributes:
        level: Severity ladder. ``"info"`` is reserved for the
            protoxy-fallback notice; ``"warning"`` is reserved for
            future use; every actual failure uses ``"error"``. String
            values match :class:`LintSeverity` so formatters can
            render findings and diagnostics through the same code
            path; the ``Literal`` type avoids requiring agents to
            import :class:`LintSeverity` (and thus preserves the
            cold-import shape for ``compile.py`` consumers).
        category: Closed-set discriminator for the failure kind.
            Stable across protoxy/protoc/stdlib version changes;
            agents should branch on this rather than ``exception_type``.
        message: Human-readable explanation.
        command: For subprocess failures, the argv tuple that ran.
            ``None`` for non-subprocess failures.
        exit_code: For subprocess failures, the non-zero return
            code. ``None`` for non-subprocess failures.
        stderr: For subprocess failures, the captured stderr (with
            trailing whitespace stripped). Always a string for
            ``CalledProcessError`` (empty string if stderr was
            empty). Reserved for ``None`` in future categories that
            don't capture stderr.
        exception_type: ``type(exc).__name__`` of the underlying
            exception, or a synthetic name (``"SameBasenameCollision"``)
            for pre-flight rejections. Open-ended for categories #4
            and #5 (any OSError subclass / Exception subclass name).
            Use ``category`` for closed-set branching.
    """

    level: Literal["info", "warning", "error"]
    message: str
    category: DiagnosticCategory = "unexpected"
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
        source_locations: Optional read-only mapping from
            ``fd.name`` to the raw :class:`FileDescriptorProto`
            captured BEFORE ``pool.Add()`` discards
            ``source_code_info``. Populated only when
            :func:`compile_protos_to_result` is called with
            ``include_source_info=True``; ``None`` otherwise. The
            lint engine reads this via the module-level
            ``leading_comment`` helper in
            ``protokit.schema.lint.rules.options._comments`` to
            implement comment-aware rules (D6b R6 family). The
            field is wrapped in :class:`types.MappingProxyType` at
            construction time so the frozen-dataclass guarantee
            holds against post-hoc mutation. Defaults to ``None``
            so D1-D5 callers and the ``protokit compat`` /
            non-lint paths pay zero descriptor-size cost.
    """

    pool: descriptor_pool.DescriptorPool
    root_files: tuple[str, ...] = ()
    diagnostics: tuple[LintCompileDiagnostic, ...] = ()
    source_locations: Mapping[str, FileDescriptorProto] | None = None

    def __post_init__(self) -> None:
        """Snapshot caller-supplied sequences into immutable tuples / mappings.

        The dataclass is ``frozen=True``, but a caller could still
        pass a ``list`` for ``root_files`` / ``diagnostics`` and
        mutate it later. We snapshot here so the frozen guarantee
        is real. Mirrors the pattern in
        :class:`protokit.schema.profiles.LintProfile`.

        ``source_locations`` (D6b R6b) follows the same discipline:
        when non-None, the caller's mapping is wrapped in
        :class:`types.MappingProxyType` so post-construction mutation
        cannot affect the stored mapping.
        """
        object.__setattr__(self, "root_files", tuple(self.root_files))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        if self.source_locations is not None:
            object.__setattr__(
                self,
                "source_locations",
                MappingProxyType(dict(self.source_locations)),
            )


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
        category="protoxy_fallback",
        message="protoxy parse error; falling back to protoc",
        exception_type=type(exc).__name__,
    )


def _diagnostic_protoc_subprocess(
    exc: subprocess.CalledProcessError,
) -> LintCompileDiagnostic:
    """Build a category #2 error diagnostic (protoc subprocess failure)."""
    # exc.stderr is None if subprocess.run was called without
    # capture_output=True / stderr=PIPE; preserve that distinction
    # rather than collapsing to "" (per the LintCompileDiagnostic
    # docstring: "" means stderr was empty, None means not captured).
    if exc.stderr is None:
        stderr: str | None = None
    else:
        stderr = exc.stderr.strip()
    return LintCompileDiagnostic(
        level="error",
        category="protoc_subprocess",
        message="protoc compilation failed",
        command=tuple(str(a) for a in exc.cmd),
        exit_code=exc.returncode,
        stderr=stderr,
        exception_type="CalledProcessError",
    )


def _diagnostic_backend_missing(
    exc: FileNotFoundError | ImportError,
) -> LintCompileDiagnostic:
    """Build a category #3 error diagnostic (no compile backend available).

    Accepts ``FileNotFoundError`` (protoc not on PATH) and
    ``ImportError`` (protoxy partially installed — ``find_spec``
    succeeds but the actual import raises). Both surface the same
    install-hint message.
    """
    return LintCompileDiagnostic(
        level="error",
        category="backend_missing",
        message=(
            "compile backend missing: install protokit[compiler] or "
            "put protoc on PATH"
        ),
        exception_type=type(exc).__name__,
    )


def _diagnostic_infrastructure(exc: BaseException) -> LintCompileDiagnostic:
    """Build a category #4 error diagnostic (OSError / TimeoutExpired)."""
    return LintCompileDiagnostic(
        level="error",
        category="infrastructure",
        message=f"compile infrastructure error: {exc}",
        exception_type=type(exc).__name__,
    )


def _diagnostic_unexpected(exc: Exception) -> LintCompileDiagnostic:
    """Build a category #5 error diagnostic (catch-all for Exception)."""
    return LintCompileDiagnostic(
        level="error",
        category="unexpected",
        message=f"unexpected backend exception: {exc!r}",
        exception_type=type(exc).__name__,
    )


def _diagnostic_same_basename_collision(
    colliding: list[Path],
) -> LintCompileDiagnostic:
    """Build the pre-flight error diagnostic for same-basename collisions.

    The diagnostic message names the colliding paths by basename only;
    absolute paths are dropped to avoid leaking developer filesystem
    layout into downstream artifacts (CI logs, formatter output). The
    full paths are still available on the colliding ``Path`` objects
    if a future ``LintCompileDiagnostic`` field exposes them
    structurally.
    """
    parents_by_basename: dict[str, list[str]] = {}
    for p in colliding:
        parents_by_basename.setdefault(p.name, []).append(str(p.parent))
    rendered = "; ".join(
        f"{name} (parents: {sorted(parents)})"
        for name, parents in sorted(parents_by_basename.items())
    )
    return LintCompileDiagnostic(
        level="error",
        category="same_basename_collision",
        message=(
            "multi-path roots with same basename in different parent "
            f"dirs is unsupported: {rendered}"
        ),
        exception_type="SameBasenameCollision",
    )


def compile_protos_to_result(
    paths: Sequence[Path],
    proto_paths: Sequence[str] = (),
    *,
    include_source_info: bool = False,
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
        include_source_info: When ``True`` (D6b R6a), both backends
            preserve ``source_code_info`` and the returned
            :class:`CompileResult` carries a non-None
            :attr:`CompileResult.source_locations` mapping. Default
            ``False`` preserves pre-D6b behavior for ``protokit
            compat``, codegen, and other non-lint consumers. The
            lint CLI sets ``True`` so comment-aware rules (D6b R6
            family) can read leading comments. Early-return paths
            (basename collision, empty input, irrecoverable failure)
            pass ``source_locations=None`` regardless of the flag.

    Returns:
        A :class:`CompileResult`. On any failure, ``pool`` is a
        fresh empty :class:`DescriptorPool` (does NOT contain WKTs),
        ``root_files`` is empty, ``source_locations`` is ``None``,
        and ``diagnostics`` carries one or two entries describing
        what went wrong.
    """
    collision = _detect_same_basename_collision(paths)
    if collision:
        return CompileResult(
            pool=descriptor_pool.DescriptorPool(),
            root_files=(),
            diagnostics=(_diagnostic_same_basename_collision(collision),),
            source_locations=None,
        )
    if not paths:
        return CompileResult(
            pool=descriptor_pool.DescriptorPool(),
            source_locations=None,
        )

    diagnostics: list[LintCompileDiagnostic] = []
    pool: descriptor_pool.DescriptorPool | None = None
    root_files: tuple[str, ...] = ()
    source_locations: Mapping[str, FileDescriptorProto] | None = None

    try:
        if _has_protoxy():
            try:
                import protoxy
            except ImportError as exc:
                # find_spec returned non-None but the actual import
                # failed — partially-installed package, broken native
                # extension, etc. Surface as backend-missing rather
                # than the catch-all category #5.
                diagnostics.append(_diagnostic_backend_missing(exc))
                return CompileResult(
                    pool=descriptor_pool.DescriptorPool(),
                    root_files=(),
                    diagnostics=tuple(diagnostics),
                    source_locations=None,
                )
            try:
                pool, root_files, source_locations = _compile_with_protoxy(
                    paths,
                    proto_paths,
                    include_source_info=include_source_info,
                )
            except (protoxy.ProtoxyError, ValueError, TypeError) as exc:
                # ProtoxyError/ValueError: parse-time failures from
                # protoxy.compile itself.
                # TypeError: pool.Add() rejecting a FileDescriptorProto
                # that protoxy accepted but the python protobuf runtime
                # rejects (e.g., proto2 group-syntax interop, malformed
                # custom options). Both flavours mean "protoxy didn't
                # produce a usable result for this input"; protoc is
                # the documented fallback for either.
                #
                # Per A2-2: info-fallback diagnostic comes FIRST so the
                # tuple's leading entry tells the consumer which backend
                # was tried and why protoc was attempted.
                diagnostics.append(_diagnostic_protoxy_fallback(exc))
                # Re-attempt with protoc. Any exception here propagates
                # to the outer catch tree, which appends the SECOND
                # diagnostic (the both-fail composition contract).
                pool, root_files, source_locations = _compile_with_protoc(
                    paths,
                    proto_paths,
                    include_source_info=include_source_info,
                )
        else:
            pool, root_files, source_locations = _compile_with_protoc(
                paths,
                proto_paths,
                include_source_info=include_source_info,
            )
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
        # Source locations from a partial-success backend are not
        # actionable when the pool itself is invalid; clear them.
        source_locations = None

    return CompileResult(
        pool=pool,
        root_files=root_files,
        diagnostics=tuple(diagnostics),
        source_locations=source_locations,
    )
