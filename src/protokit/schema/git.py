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

import os
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
# Whitespace tolerant. We pre-strip block comments (``/* ... */``)
# before applying this regex so ``import`` statements inside block
# comments aren't matched. Line comments (``// ...``) don't need
# special handling: they don't start with ``import``, and the
# ``^\s*`` anchor keeps the match to statement-level imports.
_IMPORT_RE = re.compile(
    r'^\s*import\s+(?:(public|weak)\s+)?"([^"]+)"\s*;',
    re.MULTILINE,
)

# Matches any ``/* ... */`` block, including multi-line. Replaced
# with an equal-length run of spaces so line/column offsets for any
# subsequent error reporting stay accurate.
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)

# Strip characters not legal in a protobuf identifier when building
# a synthetic package name for weak-import stubs. Protobuf
# identifiers are ``[A-Za-z_][A-Za-z0-9_]*``.
_NOT_IDENT_RE = re.compile(r"[^A-Za-z0-9_]")

# Force English stderr so our error-classification string matches
# stay portable across user locales. ``_run_git`` / ``_git_show``
# inject this into every subprocess env.
_C_LOCALE_ENV: dict[str, str] = {"LC_ALL": "C", "LANG": "C"}


def _git_env() -> dict[str, str]:
    """Return a process env dict forcing C locale for git subprocesses."""
    env = dict(os.environ)
    env.update(_C_LOCALE_ENV)
    return env


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
    classification of stderr in one place). Forces a C locale on
    the child process so stderr text stays English — ref-error
    classification later relies on literal string matching that
    would otherwise break under ``LANG=es_ES`` and friends.
    """
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=text,
            env=_git_env(),
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


def verify_ref(ref: str, *, cwd: Path | None = None) -> bool:
    """Return True iff ``ref`` resolves to a valid git revision."""
    try:
        _run_git(
            ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
            cwd=cwd, text=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def commit_subject(ref: str, *, cwd: Path | None = None) -> str:
    """Return the single-line subject of a commit.

    Uses ``git log -1 --format=%s`` so the output is just the
    commit message's first line (or the full message when it
    has no newline). Empty subjects (pathological commits) are
    returned as the empty string.

    Args:
        ref: Any git revision expression that resolves to a
            single commit (SHA, tag, branch name).
        cwd: Working directory for the git invocation.

    Returns:
        The commit's subject line, without trailing newline.

    Raises:
        GitRefNotFoundError: ``ref`` does not resolve.
    """
    try:
        out = _run_git(
            ["log", "-1", "--format=%s", ref], cwd=cwd, text=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise GitRefNotFoundError(
            f"could not read subject for {ref!r}: {stderr}"
        ) from exc
    return str(out).rstrip("\n")


def merge_base(
    ref_a: str, ref_b: str, *, cwd: Path | None = None,
) -> str:
    """Return the merge-base SHA of two refs.

    Raises:
        GitRefNotFoundError: Either ref doesn't resolve, or no
            merge-base exists in the local history (common in
            shallow clones — the fix is to fetch more history).
    """
    try:
        out = _run_git(
            ["merge-base", ref_a, ref_b], cwd=cwd, text=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        if is_shallow_repository(cwd=cwd):
            raise ShallowRepoError(
                f"could not find merge-base of {ref_a!r} and {ref_b!r} in "
                "shallow clone — run `git fetch --unshallow` or "
                "`git fetch --deepen N` to widen the available history"
            ) from exc
        raise GitRefNotFoundError(
            f"no merge-base for {ref_a!r} and {ref_b!r}: {stderr}"
        ) from exc
    return str(out).strip()


def resolve_default_base(
    *,
    cwd: Path | None = None,
    flag_hint: str = "--against-base",
) -> str:
    """Pick a sensible default base branch when the user invokes
    the auto-resolve form of a base-comparing command.

    Resolution order matches the design doc:

    1. The current branch's tracked upstream (``@{upstream}``).
    2. ``origin/main`` if it resolves.
    3. ``origin/master`` if it resolves.

    Args:
        cwd: Working directory for git invocations.
        flag_hint: Name of the CLI flag the caller surfaces for
            manual override. Spliced into the error message so
            ``ci`` users see "Pass --base BRANCH" while ``check``
            users see "Pass --against-base BRANCH".

    Raises:
        GitRefNotFoundError: When none of the candidates resolve.
    """
    # 1. @{upstream} of the current branch
    try:
        upstream = _run_git(
            ["rev-parse", "--abbrev-ref", "@{upstream}"],
            cwd=cwd, text=True,
        )
        upstream = str(upstream).strip()
        if upstream:
            return upstream
    except subprocess.CalledProcessError:
        pass

    # 2. origin/main
    if verify_ref("origin/main", cwd=cwd):
        return "origin/main"

    # 3. origin/master
    if verify_ref("origin/master", cwd=cwd):
        return "origin/master"

    raise GitRefNotFoundError(
        "no default base branch found — tracked upstream is unset "
        f"and neither origin/main nor origin/master resolves. Pass "
        f"{flag_hint} BRANCH explicitly."
    )


def commits_in_range(
    range_spec: str,
    *,
    paths: Sequence[str] = (),
    cwd: Path | None = None,
) -> list[str]:
    """Return commit SHAs in ``range_spec`` (e.g. ``"old..new"``).

    Order is oldest → newest (reverse of git's default). Restricts
    to commits that touch ``paths`` (typically a glob like
    ``"*.proto"``) when given, so history walks ignore unrelated
    commits.

    Raises:
        GitRefNotFoundError: When either endpoint of the range
            doesn't resolve.
    """
    args = ["log", "--reverse", "--format=%H", range_spec]
    if paths:
        args.append("--")
        args.extend(paths)
    try:
        out = _run_git(args, cwd=cwd, text=True)
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise GitRefNotFoundError(
            f"could not enumerate commits in {range_spec!r}: {stderr}"
        ) from exc
    return [line for line in str(out).splitlines() if line]


def walk_dep_graph(
    ref: str,
    root_proto: str,
    proto_roots: Sequence[str] = (".",),
    *,
    cwd: Path | None = None,
) -> set[str]:
    """Return the import-relative paths in ``root_proto``'s transitive
    dep tree at ``ref`` — parse-only, no compilation.

    Walks imports via :func:`_parse_imports` without shelling out
    to the compiler, so it's cheap enough to call once per commit
    during a range walk. The returned set includes ``root_proto``
    itself. Well-known imports (``google/protobuf/...``) and
    unresolvable paths are omitted.

    Missing ``import weak`` deps are silently skipped (matching
    :func:`extract_pool_from_ref`). Missing standard deps at an
    intermediate commit ARE skipped too — dep-graph walking
    tolerates partial resolution; the caller is responsible for
    re-validating when they actually compile at that commit.
    """
    visited: set[str] = set()
    queue: deque[str] = deque([root_proto])
    while queue:
        import_path = queue.popleft()
        if import_path in visited:
            continue
        visited.add(import_path)
        if _is_well_known(import_path):
            continue
        content: bytes | None = None
        for root in proto_roots:
            clean_root = root.rstrip("/")
            repo_path = (
                f"{clean_root}/{import_path}"
                if clean_root and clean_root != "."
                else import_path
            )
            try:
                content = _git_show(ref, repo_path, cwd=cwd)
                break
            except FileNotFoundError:
                continue
        if content is None:
            continue
        for _, sub_import in _parse_imports(content):
            if sub_import not in visited:
                queue.append(sub_import)
    return visited


def _strip_proto_root(
    repo_path: str, proto_roots: Sequence[str],
) -> str:
    """Translate a git repo path to its import-relative form.

    For ``proto_roots=("proto",)`` and ``repo_path="proto/acme/u.proto"``
    returns ``"acme/u.proto"``. Unrecognised paths are returned
    unchanged (they may already be import-relative, or may live
    outside any declared root).
    """
    for root in proto_roots:
        clean_root = root.rstrip("/")
        if clean_root and clean_root != "." and repo_path.startswith(
            f"{clean_root}/",
        ):
            return repo_path[len(clean_root) + 1:]
    return repo_path


def _files_changed_in_commit(
    sha: str, *, cwd: Path | None = None,
) -> list[str]:
    """Return repo-relative paths of files changed in ``sha``.

    Uses ``git show --name-only``. Empty list if the commit
    introduced no changes to tracked files (root commit, merge
    resolutions with no content differences, etc.).
    """
    try:
        out = _run_git(
            ["show", "--name-only", "--format=", sha],
            cwd=cwd, text=True,
        )
    except subprocess.CalledProcessError:
        return []
    return [line for line in str(out).splitlines() if line.strip()]


def commits_affecting_dep_tree(
    range_spec: str,
    root_proto: str,
    proto_roots: Sequence[str] = (".",),
    *,
    fast: bool = False,
    cwd: Path | None = None,
) -> list[str]:
    """Enumerate commits in ``range_spec`` whose changes affect
    ``root_proto``'s compatibility — dep-aware.

    Two modes. Both return a chronologically-ordered list of
    commit SHAs (oldest → newest).

    **Default (``fast=False``) — D from the design discussion.**
    Walks every commit that touched a ``.proto`` in the range.
    At each candidate, parses ``root_proto``'s transitive dep
    graph AT THAT REF via :func:`walk_dep_graph`, then keeps the
    commit only if its changed files intersect the dep graph.
    Catches every real break, including dep changes active only
    mid-range. Pays one dep-graph parse per ``.proto``-touching
    commit — typically cheap since parse avoids compilation.

    **``fast=True`` — E+ from the design discussion.**
    Unions the dep graphs at the range's OLD and NEW endpoints,
    then issues one ``git log --follow -- PATH`` per path in the
    union, merging the results. Tracks renames per-path (a win
    over the default). Misses commits that modified a file which
    was a dep only at intermediate refs — rare, documented in
    the README's bisect-accuracy section.

    Args:
        range_spec: ``"OLD..NEW"`` git range.
        root_proto: Import-relative path of the root file to
            track compatibility of.
        proto_roots: Repository prefixes for import resolution,
            analogous to ``protoc -I``.
        fast: Use the fast E+ enumeration. Default False (D,
            full correctness).
        cwd: Working directory for git commands.

    Returns:
        Ordered list of commit SHAs whose changes affected the
        root proto's compat, oldest first.

    Raises:
        GitRefNotFoundError: Either range endpoint fails to resolve.
    """
    if fast:
        return _commits_affecting_fast(
            range_spec, root_proto, proto_roots, cwd=cwd,
        )
    return _commits_affecting_exact(
        range_spec, root_proto, proto_roots, cwd=cwd,
    )


def _commits_affecting_exact(
    range_spec: str,
    root_proto: str,
    proto_roots: Sequence[str],
    *,
    cwd: Path | None = None,
) -> list[str]:
    """D: broad enumeration + per-ref dep-tree filter."""
    candidates = commits_in_range(
        range_spec, paths=["*.proto"], cwd=cwd,
    )
    affecting: list[str] = []
    for sha in candidates:
        changed_files = _files_changed_in_commit(sha, cwd=cwd)
        changed_protos = [
            _strip_proto_root(f, proto_roots)
            for f in changed_files
            if f.endswith(".proto")
        ]
        if not changed_protos:
            continue
        try:
            dep_set = walk_dep_graph(sha, root_proto, proto_roots, cwd=cwd)
        except (GitRefNotFoundError, FileNotFoundError):
            # The root proto doesn't resolve at this ref yet —
            # treat as "this commit doesn't affect root_proto."
            continue
        if any(p in dep_set for p in changed_protos):
            affecting.append(sha)
    return affecting


def _commits_affecting_fast(
    range_spec: str,
    root_proto: str,
    proto_roots: Sequence[str],
    *,
    cwd: Path | None = None,
) -> list[str]:
    """E+: multi-``git log --follow`` of OLD ∪ NEW dep graphs."""
    if ".." not in range_spec:
        raise GitRefNotFoundError(
            f"invalid range {range_spec!r}: expected OLD..NEW"
        )
    sep = "..." if "..." in range_spec else ".."
    old_name, new_name = range_spec.split(sep, 1)

    # Gather deps at each endpoint; tolerate missing roots (the
    # root may only exist at one end of the range, e.g. newly
    # added or newly removed).
    try:
        old_deps = walk_dep_graph(old_name, root_proto, proto_roots, cwd=cwd)
    except (GitRefNotFoundError, FileNotFoundError):
        old_deps = set()
    try:
        new_deps = walk_dep_graph(new_name, root_proto, proto_roots, cwd=cwd)
    except (GitRefNotFoundError, FileNotFoundError):
        new_deps = set()
    all_paths = old_deps | new_deps
    all_paths.add(root_proto)

    # One ``git log --follow -- PATH`` per import path. ``--follow``
    # only works with a single path argument, which is why we issue
    # N calls and merge.
    seen: set[str] = set()
    for import_path in all_paths:
        if _is_well_known(import_path):
            continue
        # Union commits across every proto_root that resolves this
        # import path. Do NOT break on the first non-exception —
        # an empty log under one root doesn't imply the file isn't
        # tracked elsewhere. Pre-Gap-1 review this short-circuit
        # silently dropped commits when a dep lived only in the
        # second root (e.g. vendor/).
        for root in proto_roots:
            clean_root = root.rstrip("/")
            repo_path = (
                f"{clean_root}/{import_path}"
                if clean_root and clean_root != "."
                else import_path
            )
            try:
                out = _run_git(
                    [
                        "log", "--reverse", "--format=%H", "--follow",
                        range_spec, "--", repo_path,
                    ],
                    cwd=cwd, text=True,
                )
                for line in str(out).splitlines():
                    if line:
                        seen.add(line)
            except subprocess.CalledProcessError:
                continue

    # Return commits in the range's natural chronological order.
    ordered = commits_in_range(range_spec, cwd=cwd)
    return [sha for sha in ordered if sha in seen]


def _git_show(ref: str, path: str, *, cwd: Path | None = None) -> bytes:
    """Return the raw bytes of ``path`` at ``ref`` via ``git show``.

    Translates the most common failure modes into typed errors so
    callers don't have to grep stderr themselves. Subprocess env
    is forced to a C locale for portability of the error-text
    classification below.
    """
    try:
        out = subprocess.run(
            ["git", "show", f"{ref}:{path}"],
            cwd=cwd,
            check=True,
            capture_output=True,
            env=_git_env(),
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

    Block comments (``/* ... */``) are blanked out before matching
    so ``import`` statements inside comments aren't collected.
    Line comments don't need special handling — the ``^\\s*``
    anchor on the import regex keeps the match to statement-level
    imports, and a ``//`` prefix never starts with ``import``.

    Decodes UTF-8 with replacement so a non-UTF-8 ``.proto`` file
    (rare but possible) doesn't crash the walker — the regex still
    finds ASCII import statements regardless.
    """
    text = proto_bytes.decode("utf-8", errors="replace")
    # Replace block comments with equal-length space runs so line
    # offsets stay stable for any future diagnostic reporting.
    text = _BLOCK_COMMENT_RE.sub(
        lambda m: " " * (m.end() - m.start()),
        text,
    )
    return [(m.group(1) or "", m.group(2)) for m in _IMPORT_RE.finditer(text)]


def _is_well_known(import_path: str) -> bool:
    """Whether the import is a well-known type bundled with the compiler."""
    return any(import_path.startswith(p) for p in _WELL_KNOWN_PREFIXES)


def _safe_dest_path(dest: Path, import_path: str) -> Path:
    """Resolve ``dest/import_path``, refusing anything that escapes ``dest``.

    **Security boundary.** ``import_path`` is attacker-controlled: it
    comes from a ``.proto`` at an arbitrary git ref, which on the
    documented ``protokit compat ci`` fork-PR path is untrusted. Both
    write sites in :func:`_extract_proto_tree` compose ``dest /
    import_path``, and ``pathlib`` silently *discards* ``dest`` when the
    right-hand side is absolute (``Path("/tmp/x") / "/etc/passwd"`` is
    ``Path("/etc/passwd")``), so an unguarded join escapes the
    ``TemporaryDirectory`` and clobbers a real file. ``..`` segments
    escape the same way.

    A repo-tracked proto path can never legitimately be absolute or
    contain ``..``, so this rejects nothing a valid schema would emit.

    Raises:
        ProtoImportError: if the import path is absolute, contains a
            ``..`` segment, or otherwise resolves outside ``dest``.
    """
    candidate = Path(import_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ProtoImportError(
            f"refusing import path {import_path!r}: absolute paths and "
            f"'..' segments cannot appear in a repo-tracked .proto import"
        )
    resolved = (dest / candidate).resolve()
    # `dest` may itself be a symlink (macOS /tmp -> /private/tmp), so
    # compare resolved-to-resolved rather than against the raw `dest`.
    if not resolved.is_relative_to(dest.resolve()):
        raise ProtoImportError(
            f"refusing import path {import_path!r}: resolves outside the "
            f"extraction directory"
        )
    return resolved


def _write_weak_stub(dest: Path, import_path: str) -> None:
    """Write an empty proto3 stub at ``dest/<import_path>``.

    Used to satisfy a missing ``import weak`` dependency: the
    compiler needs a syntactically valid file at the import path,
    but the stub exposes no symbols, so any code that actually
    referenced the missing import would fail downstream — which
    matches ``import weak`` semantics ("tolerate the dep being
    absent at compile time, fail loudly if you actually use it").

    The synthetic package name is sanitised to the protobuf
    identifier grammar (``[A-Za-z_][A-Za-z0-9_]*``) so paths with
    hyphens, spaces, or other non-identifier chars don't produce
    a compile error in the stub itself.
    """
    safe_id = _NOT_IDENT_RE.sub("_", import_path)
    # Identifiers can't start with a digit. Prefix if necessary.
    if safe_id and safe_id[0].isdigit():
        safe_id = "_" + safe_id
    # `safe_id` sanitises the package name written INTO the stub; the
    # write LOCATION needs its own guard -- see `_safe_dest_path`.
    stub_path = _safe_dest_path(dest, import_path)
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

        out_path = _safe_dest_path(dest, import_path)
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
