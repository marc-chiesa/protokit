"""Shared CLI helpers for ``protokit diff`` and ``protokit compat``.

Small, dependency-free utilities used by both subcommand modules. The
``_`` prefix on the module name marks it as an internal extraction
point — consumers should invoke the CLIs, not import from here.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NoReturn

import click
from google.protobuf import descriptor_pb2, descriptor_pool


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
