"""Shared CLI helpers for ``protokit diff`` and ``protokit compat``.

Small, dependency-free utilities used by both subcommand modules. The
``_`` prefix on the module name marks it as an internal extraction
point — consumers should invoke the CLIs, not import from here.
"""

from __future__ import annotations

import importlib
import io
import os
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, NoReturn

import click
from google.protobuf import descriptor_pb2, descriptor_pool

from protokit.formatters import (
    Formatter,
    FormatterContext,
    FormatterError,
    FormatterKind,
    get_formatter,
    list_formatters,
    load_formatter_pack,
)

# Default ceiling on protoc invocation runtime. A pathological proto
# (deeply nested imports, future protoc bug, generated input) could
# otherwise hang indefinitely. Override via PROTOKIT_PROTOC_TIMEOUT.
# On timeout, subprocess raises TimeoutExpired which routes to
# category #4 (infrastructure) at the compile_protos_to_result layer.
_PROTOC_TIMEOUT_SECONDS_DEFAULT = 60.0


def _protoc_timeout_seconds() -> float:
    """Return the configured protoc subprocess timeout in seconds.

    Reads ``PROTOKIT_PROTOC_TIMEOUT`` from the environment; falls back
    to :data:`_PROTOC_TIMEOUT_SECONDS_DEFAULT` if unset or unparseable.
    """
    raw = os.environ.get("PROTOKIT_PROTOC_TIMEOUT")
    if raw is None:
        return _PROTOC_TIMEOUT_SECONDS_DEFAULT
    try:
        return float(raw)
    except ValueError:
        return _PROTOC_TIMEOUT_SECONDS_DEFAULT


def error_exit(message: str) -> NoReturn:
    """Print an error to stderr and exit with code 2.

    Used by CLI subcommands to surface user-facing errors (bad flags,
    missing types, protoc failures) with a consistent format and exit
    code. Never returns.

    Args:
        message: Human-readable error text. ``"Error: "`` is prefixed
            automatically before display.
    """
    click.echo(f"Error: {message}", err=True)
    sys.exit(2)


def load_descriptor_pool(desc_path: Path) -> descriptor_pool.DescriptorPool:
    """Load a ``.descriptor_set`` file into a fresh ``DescriptorPool``.

    The caller is responsible for validating the path exists; a
    malformed file surfaces as a protobuf parse exception.

    Args:
        desc_path: Path to a compiled ``.descriptor_set`` file (i.e.,
            the output of ``protoc --descriptor_set_out``).

    Returns:
        A new ``DescriptorPool`` populated with every file descriptor
        from the set.
    """
    data = desc_path.read_bytes()
    fds = descriptor_pb2.FileDescriptorSet()
    fds.ParseFromString(data)
    pool = descriptor_pool.DescriptorPool()
    for fd in fds.file:
        pool.Add(fd)
    return pool


def _has_protoxy() -> bool:
    """Return True when the optional ``protoxy`` backend is importable.

    Kept out of module scope so tests can monkeypatch the import
    surface without leaking state, and so the main import cost is
    pay-on-first-use.
    """
    import importlib.util
    return importlib.util.find_spec("protoxy") is not None


def compile_proto(
    proto_path: Path,
    proto_paths: tuple[str, ...] = (),
) -> descriptor_pool.DescriptorPool:
    """Compile a ``.proto`` source file and return a ``DescriptorPool``.

    Compat-CLI adapter (single-path, ``error_exit`` on failure). Wraps
    the multi-path raising helpers ``_compile_with_protoxy`` /
    ``_compile_with_protoc`` and routes typed exceptions to
    ``error_exit`` with category-specific stderr prefixes.

    Compiler backend selection:

    - ``protoxy`` (Rust ``protox`` bindings) when the package is
      importable. Preferred — no external ``protoc`` on PATH
      required. Install with ``pip install protokit[compiler]``.
    - Shelling out to ``protoc`` otherwise. Matches the pre-1.5
      behavior; users who already have ``protoc`` on PATH don't
      need to install anything extra.

    Both backends request ``--include_imports`` equivalent so the
    returned pool has every transitive dependency resolved. The
    ``.proto`` file's parent directory is always added to the
    include path in addition to any the caller provides.

    Args:
        proto_path: Path to the ``.proto`` source file.
        proto_paths: Additional import path strings. Empty tuple
            means only the source file's parent directory is on
            the include path.

    Returns:
        A ``DescriptorPool`` built from the compiled descriptor set.

    Raises:
        SystemExit: Via :func:`error_exit` if compilation fails.
            Exits with code 2. Stderr text is prefixed by category
            per the post-refactor contract:

            - ``"protoxy compile failed: "`` for ``ProtoxyError`` or ``ValueError``
            - ``"protoc compile failed: "`` for ``CalledProcessError``
            - ``"compile backend missing: "`` for ``FileNotFoundError``
            - ``"compile infrastructure error: "`` for ``OSError`` / ``TimeoutExpired``
    """
    has_protoxy = _has_protoxy()
    if has_protoxy:
        import protoxy
        protoxy_caught: tuple[type[BaseException], ...] = (
            protoxy.ProtoxyError, ValueError,
        )
    else:
        # protoxy is absent — _compile_with_protoxy is unreachable, but
        # keep ValueError in the catch tuple so a hypothetical ValueError
        # from _compile_with_protoc surfaces through error_exit instead
        # of escaping uncaught. The prefix below switches on has_protoxy
        # so the label is honest about which backend ran.
        protoxy_caught = (ValueError,)

    pool: descriptor_pool.DescriptorPool | None = None
    try:
        if has_protoxy:
            pool, _ = _compile_with_protoxy([proto_path], proto_paths)
        else:
            pool, _ = _compile_with_protoc([proto_path], proto_paths)
    except FileNotFoundError:
        # Both backends absent — preserve the install-hint message that
        # the previous implementation emitted from inside _compile_with_protoc.
        error_exit(
            "compile backend missing: Neither protoxy nor protoc is "
            "available. Install the optional compiler backend with "
            "`pip install protokit[compiler]`, or put protoc on PATH, "
            "or use a pre-compiled .descriptor_set instead."
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else str(exc)
        error_exit(f"protoc compile failed: {stderr}")
    except subprocess.TimeoutExpired as exc:
        # subprocess.TimeoutExpired is NOT an OSError subclass — sibling
        # tree under SubprocessError. Today's _compile_with_protoc does
        # not pass timeout=, so this catch is defensive coverage for the
        # future case where a timeout is added.
        error_exit(f"compile infrastructure error: {exc}")
    except OSError as exc:
        # PermissionError, BrokenPipeError, etc.
        error_exit(f"compile infrastructure error: {exc}")
    except protoxy_caught as exc:
        prefix = "protoxy compile failed" if has_protoxy else "protoc compile failed"
        error_exit(f"{prefix}: {exc}")
    return pool


def _compile_with_protoxy(
    proto_paths_in: Sequence[Path],
    include_paths: Sequence[str] = (),
) -> tuple[descriptor_pool.DescriptorPool, tuple[str, ...]]:
    """Multi-path compile via the in-process ``protoxy`` (Rust) backend.

    Raises on failure (does NOT call ``error_exit``); callers translate
    typed exceptions into ``error_exit`` (legacy ``compile_proto``) or
    ``LintCompileDiagnostic`` (new ``compile_protos_to_result`` in
    ``protokit.schema.compile``).

    Args:
        proto_paths_in: Sequence of root ``.proto`` file paths.
        include_paths: Additional ``-I``-style include directories. Each
            input path's parent is automatically added to the include
            list (deduped via ``dict.fromkeys`` for deterministic order).

    Returns:
        Tuple of ``(DescriptorPool, root_names)`` where ``root_names`` is
        a tuple of the ``.proto``-relative names that came from the
        user's input paths (NOT including transitive imports), in input
        order. Used by ``compile_protos_to_result`` to populate
        ``CompileResult.root_files``.

    Raises:
        protoxy.ProtoxyError: On parse / compile failure.
        ValueError: protoxy 0.7 docstring claims this; in practice
            ProtoxyError is what's raised. Defensive over-catch.
    """
    import protoxy
    parents = list(dict.fromkeys(str(p.parent) for p in proto_paths_in))
    includes = [*include_paths, *parents]
    fds = protoxy.compile(
        files=[str(p) for p in proto_paths_in],
        includes=includes,
        include_imports=True,
        # Keep the in-memory FileDescriptorSet byte-equivalent between
        # backends — neither carries source-location info into the pool.
        include_source_info=False,
    )
    pool = descriptor_pool.DescriptorPool()
    expected_in_order = _expected_root_names_ordered(proto_paths_in, includes)
    expected_set = set(expected_in_order)
    emitted: set[str] = set()
    for fd in fds.file:
        pool.Add(fd)
        if fd.name in expected_set:
            emitted.add(fd.name)
    # Walk expected_in_order so root_names preserves the user's input
    # order (fds.file iterates in backend topological order, wrong for
    # CompileResult.root_files). Filter by `emitted` for defensiveness
    # against any future matcher/backend skew.
    root_names = tuple(name for name in expected_in_order if name in emitted)
    return pool, root_names


def _compile_with_protoc(
    proto_paths_in: Sequence[Path],
    include_paths: Sequence[str] = (),
) -> tuple[descriptor_pool.DescriptorPool, tuple[str, ...]]:
    """Multi-path compile by shelling out to ``protoc`` on PATH.

    Raises on failure (does NOT call ``error_exit``).

    Args:
        proto_paths_in: Sequence of root ``.proto`` file paths.
        include_paths: Additional ``-I``-style include directories.

    Returns:
        Tuple of ``(DescriptorPool, root_names)`` where ``root_names`` is
        a tuple of input-order ``fd.name`` strings.

    Raises:
        FileNotFoundError: ``protoc`` not on PATH.
        subprocess.CalledProcessError: ``protoc`` returned non-zero.
        subprocess.TimeoutExpired: ``protoc`` exceeded a future
            ``timeout=`` kwarg (not currently passed; defensive).
        OSError: Other infrastructure failures (permission denied, etc.).
    """
    parents = list(dict.fromkeys(str(p.parent) for p in proto_paths_in))
    includes = [*include_paths, *parents]

    with tempfile.NamedTemporaryFile(suffix=".descriptor_set", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        cmd = ["protoc", "--descriptor_set_out", str(tmp_path), "--include_imports"]
        for inc in includes:
            cmd.extend(["-I", inc])
        # End-of-options separator: protoc treats positional args
        # starting with "--" as flags; the separator forces every
        # subsequent token to be parsed as an input path.
        cmd.append("--")
        for p in proto_paths_in:
            cmd.append(str(p))

        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=_protoc_timeout_seconds(),
        )

        data = tmp_path.read_bytes()
        fds = descriptor_pb2.FileDescriptorSet()
        fds.ParseFromString(data)
        # Guard against silent success: protoc exited 0 but produced
        # an empty FileDescriptorSet (write-truncated tmpfile, future
        # protoc bug, disk-full mid-write that didn't propagate as a
        # non-zero exit). Without this check the function returns
        # (empty_pool, ()) and the caller can't distinguish
        # "compiled nothing" from "compile silently dropped output".
        if proto_paths_in and not fds.file:
            raise OSError(
                "protoc exited 0 but produced an empty descriptor set "
                f"for inputs {[str(p) for p in proto_paths_in]}"
            )
        pool = descriptor_pool.DescriptorPool()
        expected_in_order = _expected_root_names_ordered(proto_paths_in, includes)
        expected_set = set(expected_in_order)
        emitted: set[str] = set()
        for fd in fds.file:
            pool.Add(fd)
            if fd.name in expected_set:
                emitted.add(fd.name)
        root_names = tuple(name for name in expected_in_order if name in emitted)
        return pool, root_names
    finally:
        tmp_path.unlink(missing_ok=True)


def _expected_root_names_ordered(
    proto_paths_in: Sequence[Path],
    includes: Sequence[str],
) -> list[str]:
    """Compute expected ``fd.name`` per input path, preserving input order.

    Backends emit ``fds.file`` in dependency (topological) order; that is
    the wrong sequencing for ``CompileResult.root_files``, which is
    contracted to preserve the user's input order. Returning a list
    (not a set) lets callers walk in input order while still using a
    set for membership checks against the backend's emitted names.

    Args:
        proto_paths_in: Input paths in their declared order.
        includes: Include directories in declared order (search order).

    Returns:
        List of expected ``fd.name`` strings, one per input path,
        preserving input order. May contain duplicates if two inputs
        resolve to the same name (caller's responsibility — pre-flight
        same-basename detection happens at the ``compile_protos_to_result``
        layer).
    """
    return [_resolve_expected_name(p, includes) for p in proto_paths_in]


def _resolve_expected_name(p: Path, includes: Sequence[str]) -> str:
    """Compute the expected ``fd.name`` for one input proto path.

    Walks ``includes`` in declared order; the first include that is a
    prefix of ``p`` determines the relative form (which is what
    protoxy/protoc emit as ``fd.name``). Falls back to ``p.name`` if
    no include is a prefix (rare; caller convention is to include
    ``p.parent``).

    Path components are matched LITERALLY — neither ``p`` nor the
    includes are passed through ``Path.resolve()``. Both backends
    resolve ``-I`` arguments and input paths against the literal
    string the user passed (no symlink expansion of the include
    against the input). Calling ``.resolve()`` here would diverge
    from the backend on macOS (``/var`` -> ``/private/var``), Bazel
    ``bazel-out`` symlinks, and any container bind-mount where the
    user-passed path does not byte-match the realpath. The skew
    silently empties ``CompileResult.root_files`` for compiles
    that otherwise succeed.
    """
    for inc in includes:
        inc_path = Path(inc)
        try:
            return str(p.relative_to(inc_path))
        except ValueError:
            continue
    return p.name


def load_formatter_packs(module_names: tuple[str, ...]) -> None:
    """Import each ``--formatter-module`` and load its FORMATTERS pack.

    Mirrors :func:`_load_rule_packs` in ``schema/cli.py``: each
    name resolves via ``importlib.import_module`` and any error
    surfaces verbatim through :func:`error_exit`. The
    underlying :func:`~protokit.formatters.load_formatter_pack`
    runs a two-phase load — staging entries first so a malformed
    later entry doesn't leave half-loaded formatters behind.

    Built-in shadowing errors get a distinct error prefix so
    pattern-matching agents can branch without parsing the
    embedded exception text — collisions with reserved built-in
    names are conceptually different from "the pack failed to
    load" and benefit from their own surface.
    """
    for name in module_names:
        try:
            module = importlib.import_module(name)
        except Exception as exc:
            error_exit(f"failed to import formatter pack '{name}': {exc}")
        try:
            load_formatter_pack(module)
        except FormatterError as exc:
            error_exit(
                f"formatter pack '{name}' conflicts with a reserved "
                f"built-in name: {exc}"
            )
        except (AttributeError, TypeError) as exc:
            error_exit(f"failed to load formatter pack '{name}': {exc}")


def resolve_and_validate_formatter(
    name: str, kind: FormatterKind,
) -> Formatter:
    """Look up a formatter; exit with an actionable list on miss.

    Always-on lower-casing matches the registry's
    case-insensitive lookup so users can type ``JUnit`` or
    ``junit`` interchangeably.

    Raises:
        SystemExit: Via :func:`error_exit` (code 2) when no
            formatter is registered for ``(kind, name.lower())``.
            The error names every available formatter for the
            kind so the user can fix the typo without re-reading
            the docs.
    """
    try:
        return get_formatter(name, kind)
    except KeyError:
        available = ", ".join(list_formatters(kind))
        error_exit(
            f"unknown formatter '{name}'. "
            f"Available for {kind.value}: {available}"
        )


def reject_quiet_plus_structured(
    *, quiet: bool, output_format: str,
) -> None:
    """Reject ``--quiet --format <structured>`` combinations.

    The two flags conflict in spirit: ``--quiet`` says "give me
    no output, just an exit code"; a structured format says
    "give me machine-parseable output." The legacy check only
    rejected ``--quiet --format json``; this widened version
    rejects every non-``human`` formatter so user-registered
    structured formats (junit, sarif, custom slack-pack) get
    the same loud-fail treatment instead of silently
    swallowing their output under ``--quiet``.
    """
    if quiet and output_format.lower() != "human":
        error_exit(
            f"--quiet is incompatible with structured output format "
            f"'{output_format}'. Drop --quiet, or pick --format human."
        )


def _scrub_exc_message(exc: BaseException) -> str:
    """Return a safe ``str(exc)`` for error-path surfacing.

    ``OSError`` subclasses embed ``filename`` / ``filename2``
    into their ``str()`` — a formatter that touched the
    filesystem could leak absolute paths (or path-shaped
    secrets) onto stderr via our generic error handler. For
    those, emit only the errno string so the failure mode is
    still recognisable without exposing filesystem layout.
    Other exception types keep their full message.
    """
    if isinstance(exc, OSError):
        import errno
        # exc.errno is Optional[int]; errorcode.get expects int. Treat
        # missing errno as a label so the formatter still surfaces
        # something useful.
        if exc.errno is None:
            errno_label = "Errno-unknown"
        else:
            errno_label = errno.errorcode.get(exc.errno, str(exc.errno))
        return f"[Errno {exc.errno} {errno_label}] {exc.strerror or ''}".strip()
    return str(exc)


def run_formatter_safely(
    fn: Formatter,
    report: Any,
    ctx: FormatterContext,
    *,
    name: str,
) -> str:
    """Invoke a formatter with stdout-capture and exception fail-fast.

    Two guarantees:

    1. **Stdout-write guard.** Formatters MUST be pure
       str-returning functions. If a third-party formatter
       writes to ``sys.stdout`` mid-render and then either
       raises or returns, those bytes leak out of order
       relative to whatever the CLI eventually echoes. We
       redirect stdout into an in-memory buffer for the
       duration of the call; non-empty buffer triggers a
       contract-violation error (exit 2).
    2. **Exception fail-fast.** Any exception from ``fn``
       converts to ``error_exit("formatter '{name}' raised
       {ExceptionType}: {message}")``. No traceback. The
       project doesn't have a ``--verbose`` flag today, so
       there's no opt-in for tracebacks; the one-line error
       matches every other CLI failure path.

    Returns:
        The formatter's returned string. Caller is responsible
        for echoing it (:func:`click.echo`).
    """
    buffer = io.StringIO()
    try:
        with redirect_stdout(buffer):
            output = fn(report, ctx)
    except SystemExit as exc:
        # SystemExit subclasses BaseException, not Exception, so
        # the general handler below would let it through. A
        # formatter calling sys.exit(0) would otherwise flip the
        # CI exit code from 1 (incompatible) to 0 (compatible),
        # defeating the gate. Forced through error_exit so
        # exit code stays the report's verdict.
        error_exit(
            f"formatter '{name}' called sys.exit({exc.code!r}); "
            "formatters must return str only"
        )
    except Exception as exc:
        error_exit(
            f"formatter '{name}' raised {type(exc).__name__}: "
            f"{_scrub_exc_message(exc)}"
        )
    leaked = buffer.getvalue()
    if leaked:
        error_exit(
            f"formatter '{name}' wrote to sys.stdout directly "
            "(low-level fd writes such as os.write(1, ...) are not "
            "intercepted); formatters must return str only"
        )
    if not isinstance(output, str):
        error_exit(
            f"formatter '{name}' returned {type(output).__name__}, "
            "expected str"
        )
    return output
