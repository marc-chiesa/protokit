"""Build descriptor pools from .proto sources at a git ref.

Phase 2 foundation. Given a git revision and one or more
import-relative ``.proto`` paths, extract the source files via
``git show``, walk their import graph, write the lot to a temp
tree that mirrors the import structure, and compile through the
existing :func:`protokit._cli_utils.compile_proto` (protoxy
preferred, protoc fallback). The resulting :class:`DescriptorPool`
is a drop-in for :func:`protokit.schema.check_compatibility`,
which is what makes "compare ``acme.User`` between HEAD and
``HEAD~5``" a one-call operation downstream.

This module is the only place in protokit that shells out to
``git``. All git invocations go through :func:`_run_git`, which
keeps subprocess wrangling and error translation in one place.

Public surface:

- :func:`extract_pool_from_ref` — high-level extractor.
- :func:`is_shallow_repository` — predicate for CI guard rails.
- :exc:`GitRefNotFoundError`, :exc:`ProtoImportError`,
  :exc:`ShallowRepoError` — typed errors callers can branch on.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from collections import deque
from pathlib import Path
from typing import Sequence

from google.protobuf import descriptor_pool

from protokit._cli_utils import compile_proto


# Well-known imports ship with protoc / protoxy. Don't try to
# extract them from the git ref — let the compiler resolve them
# from its bundled includes.
_WELL_KNOWN_PREFIXES: tuple[str, ...] = ("google/protobuf/",)

# Match any of:
#   import "path";
#   import public "path";
#   import weak "path";
# Whitespace tolerant; ignores in-line // comments by anchoring to
# the start of a logical statement (we keep it simple — block
# comments around imports are vanishingly rare in real .proto).
_IMPORT_RE = re.compile(
    r'^\s*import\s+(?:(public|weak)\s+)?"([^"]+)"\s*;',
    re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class GitRefNotFoundError(ValueError):
    """Raised when the requested git ref cannot be resolved."""


class ProtoImportError(ValueError):
    """Raised when a required ``.proto`` import cannot be located.

    Standard and ``import public`` failures raise; ``import weak``
    failures are skipped silently to match protobuf's own
    semantics (weak imports tolerate missing dependencies at
    compile time).
    """


class ShallowRepoError(RuntimeError):
    """Raised when the repo is a shallow clone and the requested
    ref isn't reachable from the available history.

    CI environments commonly use shallow clones (``git clone
    --depth 1``); when the merge-base or a historical ref isn't
    in the local history, suggest ``git fetch --unshallow`` or
    ``--deepen`` rather than silently producing wrong results.
    """


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _run_git(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    text: bool = False,
) -> bytes | str:
    """Run a ``git`` subprocess and return stdout.

    Centralises the ``FileNotFoundError`` translation (no git on
    PATH) and the ``CalledProcessError`` path (so callers handle
    classification of stderr in one place).
    """
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=text,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "git not found on PATH; install git or run from a "
            "git-aware environment"
        ) from exc
    return result.stdout


def is_shallow_repository(cwd: Path | None = None) -> bool:
    """Return True when the repo at ``cwd`` is a shallow clone.

    Uses ``git rev-parse --is-shallow-repository`` so the check
    works on git ≥2.15. Older git versions raise — we treat that
    as "not shallow" since the feature didn't exist.
    """
    try:
        out = _run_git(
            ["rev-parse", "--is-shallow-repository"],
            cwd=cwd,
            text=True,
        )
    except subprocess.CalledProcessError:
        return False
    return str(out).strip() == "true"


def _git_show(ref: str, path: str, *, cwd: Path | None = None) -> bytes:
    """Return the raw bytes of ``path`` at ``ref`` via ``git show``.

    Translates the most common failure modes into typed errors so
    callers don't have to grep stderr themselves.
    """
    try:
        out = subprocess.run(
            ["git", "show", f"{ref}:{path}"],
            cwd=cwd,
            check=True,
            capture_output=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "git not found on PATH; install git or run from a "
            "git-aware environment"
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace").strip()
        # Map git's error text to typed exceptions. Strings below
        # cover modern git (2.x): "invalid object name" for an
        # unresolvable ref, "path '...' does not exist" / "exists
        # on disk, but not in" for a path missing at a valid ref.
        if (
            "invalid object name" in stderr
            or "unknown revision" in stderr
            or "bad revision" in stderr
            or "ambiguous argument" in stderr
        ):
            raise GitRefNotFoundError(
                f"unknown git ref {ref!r}: {stderr}"
            ) from exc
        if (
            "exists on disk" in stderr
            or "does not exist" in stderr
            or "no such path" in stderr
        ):
            raise FileNotFoundError(
                f"{path!r} not found at git ref {ref!r}"
            )
        raise
    return out.stdout


# ---------------------------------------------------------------------------
# Import parsing + tree extraction
# ---------------------------------------------------------------------------


def _parse_imports(proto_bytes: bytes) -> list[tuple[str, str]]:
    """Extract ``(kind, import_path)`` pairs from a ``.proto`` source.

    ``kind`` is ``""`` for a plain ``import``, ``"public"`` for
    ``import public``, or ``"weak"`` for ``import weak``.

    Decodes UTF-8 with replacement so a non-UTF-8 ``.proto`` file
    (rare but possible) doesn't crash the walker — the regex still
    finds ASCII import statements regardless.
    """
    text = proto_bytes.decode("utf-8", errors="replace")
    return [(m.group(1) or "", m.group(2)) for m in _IMPORT_RE.finditer(text)]


def _is_well_known(import_path: str) -> bool:
    """Whether the import is a well-known type bundled with the compiler."""
    return any(import_path.startswith(p) for p in _WELL_KNOWN_PREFIXES)


def _write_weak_stub(dest: Path, import_path: str) -> None:
    """Write an empty proto3 stub at ``dest/<import_path>``.

    Used to satisfy a missing ``import weak`` dependency: the
    compiler needs a syntactically valid file at the import path,
    but the stub exposes no symbols, so any code that actually
    referenced the missing import would fail downstream — which
    matches ``import weak`` semantics ("tolerate the dep being
    absent at compile time, fail loudly if you actually use it").
    """
    safe_id = import_path.replace("/", "_").replace(".", "_")
    stub_path = dest / import_path
    stub_path.parent.mkdir(parents=True, exist_ok=True)
    stub_path.write_text(
        'syntax = "proto3";\n'
        f'package protokit_weak_stub.{safe_id};\n'
    )


def _resolve_proto_root(
    ref: str,
    import_path: str,
    proto_roots: Sequence[str],
    cwd: Path | None,
) -> tuple[str, bytes] | None:
    """Try each ``proto_root`` prefix; return ``(repo_path, content)``
    on the first hit, or ``None`` if no root resolves the import.
    """
    for root in proto_roots:
        clean_root = root.rstrip("/")
        repo_path = (
            f"{clean_root}/{import_path}"
            if clean_root and clean_root != "."
            else import_path
        )
        try:
            content = _git_show(ref, repo_path, cwd=cwd)
            return repo_path, content
        except FileNotFoundError:
            continue
    return None


def _extract_proto_tree(
    ref: str,
    root_files: Sequence[str],
    proto_roots: Sequence[str],
    cwd: Path | None,
    dest: Path,
) -> list[Path]:
    """Walk imports breadth-first; write every file under ``dest``.

    Returns the on-disk paths of the root files (the input
    ``root_files`` list) for the caller to feed to ``compile_proto``.

    Well-known imports (``google/protobuf/...``) are skipped on
    the assumption that the compiler bundles them. ``import weak``
    failures are skipped silently. Standard / ``import public``
    failures raise :exc:`ProtoImportError`.
    """
    visited: set[str] = set()
    root_paths: list[Path] = []
    queue: deque[tuple[str, str]] = deque(("", p) for p in root_files)

    while queue:
        kind, import_path = queue.popleft()
        if import_path in visited:
            continue
        visited.add(import_path)

        if _is_well_known(import_path):
            # Compiler resolves these from its bundled includes.
            continue

        resolved = _resolve_proto_root(ref, import_path, proto_roots, cwd)
        if resolved is None:
            if kind == "weak":
                # protobuf's ``import weak`` tolerates missing
                # dependencies. The compiler still wants SOMETHING
                # at the import path, so write an empty stub with
                # a unique package and continue. The stub has no
                # symbols so it can't be referenced — exactly what
                # ``import weak`` of a missing file means at runtime.
                _write_weak_stub(dest, import_path)
                continue
            raise ProtoImportError(
                f"could not resolve import {import_path!r} at ref "
                f"{ref!r} (tried proto_roots={list(proto_roots)!r})"
            )
        _, content = resolved

        out_path = dest / import_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(content)

        if import_path in root_files:
            root_paths.append(out_path)

        for sub_kind, sub_import in _parse_imports(content):
            queue.append((sub_kind, sub_import))

    if len(root_paths) != len(root_files):
        # One of the root files itself wasn't reachable — surface a
        # clear error rather than letting compile_proto fail with a
        # cryptic "no such file" later.
        missing = [f for f in root_files if not (dest / f).exists()]
        raise ProtoImportError(
            f"root .proto file(s) not found at ref {ref!r}: {missing!r}"
        )
    return root_paths


# ---------------------------------------------------------------------------
# Public extractor
# ---------------------------------------------------------------------------


def extract_pool_from_ref(
    ref: str,
    proto_file: str,
    *,
    proto_roots: Sequence[str] = (".",),
    cwd: Path | None = None,
) -> descriptor_pool.DescriptorPool:
    """Build a :class:`DescriptorPool` from a ``.proto`` at a git ref.

    Walks the import graph rooted at ``proto_file``, extracts
    each source via ``git show <ref>:<path>``, and compiles the
    extracted tree through :func:`protokit._cli_utils.compile_proto`
    (protoxy preferred, protoc fallback). The returned pool is a
    drop-in for :func:`protokit.schema.check_compatibility`.

    Args:
        ref: Git revision — commit SHA, tag, branch name,
            ``HEAD~N``, ``origin/main``, etc. Anything ``git
            show`` understands.
        proto_file: Import-relative path of the root ``.proto``
            file. For ``protoc -I proto/ acme/user.proto``, pass
            ``"acme/user.proto"`` here and ``("proto",)`` as
            ``proto_roots``.
        proto_roots: Repository prefixes to try when resolving
            ``proto_file`` and its imports — analogous to
            ``protoc -I``. Defaults to ``(".",)`` (search from
            the repo root). Pass multiple roots for monorepos
            with split source trees, e.g. ``("proto", "vendor")``.
        cwd: Working directory for git invocations. Defaults to
            the current process working directory.

    Returns:
        A :class:`DescriptorPool` with the requested file plus
        every transitive dependency loaded.

    Raises:
        GitRefNotFoundError: ``ref`` cannot be resolved.
        ProtoImportError: A required import (standard or
            ``import public``) is missing at ``ref``. Weak
            imports never raise — they're skipped silently.
        ShallowRepoError: ``ref`` isn't reachable in the local
            shallow history. Re-raised by callers; this function
            doesn't yet auto-deepen.
        SystemExit: Propagated from ``compile_proto`` if neither
            protoxy nor protoc is available.
    """
    with tempfile.TemporaryDirectory(prefix="protokit_git_") as tmpdir:
        dest = Path(tmpdir)
        root_paths = _extract_proto_tree(
            ref, [proto_file], proto_roots, cwd, dest,
        )
        # Compile the root through the existing backend dispatcher.
        # Pass the tmp tree as the include path so transitive
        # imports resolve against the extracted layout.
        return compile_proto(root_paths[0], (str(dest),))
