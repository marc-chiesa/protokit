"""Shared CLI helpers for ``protokit diff`` and ``protokit compat``.

Small, dependency-free utilities used by both subcommand modules. The
``_`` prefix on the module name marks it as an internal extraction
point — consumers should invoke the CLIs, not import from here.
"""

from __future__ import annotations

import importlib
import io
import subprocess
import sys
import tempfile
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
    proto_paths: tuple[str, ...],
) -> descriptor_pool.DescriptorPool:
    """Compile a ``.proto`` source file and return a ``DescriptorPool``.

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
        SystemExit: Via :func:`error_exit` if neither ``protoxy``
            is importable nor ``protoc`` is on PATH, or if
            compilation fails. Exits with code 2.
    """
    if _has_protoxy():
        return _compile_with_protoxy(proto_path, proto_paths)
    return _compile_with_protoc(proto_path, proto_paths)


def _compile_with_protoxy(
    proto_path: Path,
    proto_paths: tuple[str, ...],
) -> descriptor_pool.DescriptorPool:
    """Compile via the in-process ``protoxy`` (Rust) backend."""
    import protoxy  # type: ignore[import-not-found]
    includes: list[str] = list(proto_paths)
    includes.append(str(proto_path.parent))
    try:
        fds = protoxy.compile(
            files=[str(proto_path)],
            includes=includes,
            include_imports=True,
            # Match the protoc path — neither backend carries source
            # location info into the pool, so keep the in-memory
            # FileDescriptorSet byte-equivalent between backends.
            include_source_info=False,
        )
    except (protoxy.ProtoxyError, ValueError) as exc:
        error_exit(f"protoxy failed:\n{exc}")
    pool = descriptor_pool.DescriptorPool()
    for fd in fds.file:
        pool.Add(fd)
    return pool


def _compile_with_protoc(
    proto_path: Path,
    proto_paths: tuple[str, ...],
) -> descriptor_pool.DescriptorPool:
    """Compile by shelling out to ``protoc`` on PATH."""
    with tempfile.NamedTemporaryFile(suffix=".descriptor_set", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        cmd = ["protoc", "--descriptor_set_out", str(tmp_path), "--include_imports"]
        for pp in proto_paths:
            cmd.extend(["-I", pp])
        # Always include the proto file's parent directory
        cmd.extend(["-I", str(proto_path.parent)])
        cmd.append(str(proto_path))

        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except FileNotFoundError:
            error_exit(
                "Neither protoxy nor protoc is available. Install the "
                "optional compiler backend with `pip install "
                "protokit[compiler]`, or put protoc on PATH, or use a "
                "pre-compiled .descriptor_set instead."
            )
        except subprocess.CalledProcessError as e:
            error_exit(f"protoc failed:\n{e.stderr.strip()}")

        return load_descriptor_pool(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Formatter helpers — shared by every CLI subcommand that has --format
# ---------------------------------------------------------------------------


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
            f"formatter '{name}' raised {type(exc).__name__}: {exc}"
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
