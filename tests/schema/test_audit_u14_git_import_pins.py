"""Regression pins for U1 audit findings U14-6/7/8 (schema/git.py import handling).

Each pin is a strict xfail: it fails today (pinning current, believed-wrong
behaviour) and flips loudly to XPASS the moment the behaviour is fixed.
Every pin is paired with a plain (non-xfail) *guard* test that establishes the
construction is valid, so an environment breakage shows up as a red guard
rather than silently keeping a pin "green" for the wrong reason.

U14-6 -- git.py:680: ``_is_well_known`` is a bare ``startswith`` over
         ``google/protobuf/`` applied in ``_extract_proto_tree``'s BFS
         (git.py:810) BEFORE ``_resolve_proto_root`` is ever consulted, so git
         is never asked whether the ref OWNS the path. A repository-owned
         ``google/protobuf/*.proto`` is silently replaced by the compiler's
         bundled copy while ``fd.name`` still advertises the repo path.
U14-7 -- git.py:804: ``visited`` is keyed on the import path alone and the
         import ``kind`` is discarded, so a WEAK import dequeued first writes a
         stub and marks the path visited, suppressing a later REQUIRED import
         of the same missing file. Import order alone decides whether
         compilation correctly fails.
U14-8 -- git.py:416: with overlapping ``proto_roots``, ``_strip_proto_root()``
         returns on the FIRST prefix match with no knowledge of which root
         actually resolved the file, while ``walk_dep_graph()`` records deps
         under the name produced by whichever root DID resolve them.
         ``_commits_affecting_exact()`` intersects the two, so the
         dependency-breaking commit is dropped from exact history.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from protokit.schema.git import (
    ProtoImportError,
    _is_well_known,
    commits_affecting_dep_tree,
    extract_pool_from_ref,
    walk_dep_graph,
)


def _git(*args: str, cwd: Path) -> str:
    """Shell-out helper for test setup (mirrors tests/schema/test_git.py)."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _init_repo(path: Path) -> Path:
    """Throwaway git repo with deterministic, signature-free identity."""
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", "-b", "main", cwd=path)
    _git("config", "user.email", "test@example.com", cwd=path)
    _git("config", "user.name", "Test", cwd=path)
    _git("config", "commit.gpgsign", "false", cwd=path)
    return path


def _write(repo: Path, rel: str, text: str) -> None:
    full = repo / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(text)


def _commit_all(repo: Path, msg: str) -> str:
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", msg, cwd=repo)
    return _git("rev-parse", "HEAD", cwd=repo)


# ---------------------------------------------------------------------------
# U14-6 -- repo-OWNED google/protobuf/*.proto is silently replaced
# ---------------------------------------------------------------------------

_REPO_OWNED_TIMESTAMP = (
    'syntax = "proto3";\n'
    "package google.protobuf;\n"
    "message Timestamp {\n"
    "  int64 seconds = 1;\n"
    "  int32 nanos = 2;\n"
    "  string repo_owned_tz = 3;\n"
    "}\n"
)


@pytest.fixture
def wkt_shadow_repo(tmp_path: Path) -> Path:
    """A repo that OWNS ``google/protobuf/timestamp.proto``.

    The forked copy carries an extra field (``repo_owned_tz``) that the
    compiler's bundled ``Timestamp`` does not have, which is what makes
    "did the pool come from the ref or from the compiler?" observable.
    """
    repo = _init_repo(tmp_path / "wkt_shadow")
    _write(repo, "google/protobuf/timestamp.proto", _REPO_OWNED_TIMESTAMP)
    _write(
        repo,
        "demo/event.proto",
        'syntax = "proto3";\n'
        "package demo;\n"
        'import "google/protobuf/timestamp.proto";\n'
        "message Event { google.protobuf.Timestamp at = 1; }\n",
    )
    _commit_all(repo, "repo-owned forked timestamp.proto + event.proto")
    return repo


def test_u14_6_guard_repo_really_owns_the_wkt_path(
    wkt_shadow_repo: Path,
) -> None:
    """Guard: the construction is valid, and the skip is unconditional.

    ``git show`` proves the ref genuinely carries the forked file, and
    ``_is_well_known`` proves the BFS's skip predicate matches it on path
    alone -- it never asks git whether the ref owns the path.
    """
    blob = _git(
        "show", "HEAD:google/protobuf/timestamp.proto", cwd=wkt_shadow_repo,
    )
    assert "repo_owned_tz" in blob
    assert _is_well_known("google/protobuf/timestamp.proto") is True


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "U14-6: git.py:810 applies _is_well_known() before _resolve_proto_root(), "
        "so a repo-OWNED google/protobuf/timestamp.proto at the requested ref is "
        "silently replaced by the compiler's bundled copy -- the pool advertises "
        "the ref's path (fd.name) while carrying content the ref does not have, "
        "with no diagnostic of any kind. Either outcome counts as fixed: the pool "
        "reflects the ref, or extraction fails loudly with ProtoImportError."
    ),
)
def test_u14_6_repo_owned_wkt_is_silently_replaced_by_bundled_copy(
    wkt_shadow_repo: Path,
) -> None:
    try:
        pool = extract_pool_from_ref(
            "HEAD", "demo/event.proto", cwd=wkt_shadow_repo,
        )
    except ProtoImportError:
        # A loud, typed refusal to shadow a well-known path is an acceptable
        # fix: the failure mode pinned here is *silence*, not the policy.
        return

    ts = pool.FindMessageTypeByName("google.protobuf.Timestamp")
    # The pool still claims to be the ref's file...
    assert ts.file.name == "google/protobuf/timestamp.proto"
    # ...but today it carries the compiler's bundled Timestamp, so the
    # repo-owned field is absent and the pool does not represent the ref.
    assert "repo_owned_tz" in ts.fields_by_name


# ---------------------------------------------------------------------------
# U14-7 -- a WEAK import dequeued first suppresses a later REQUIRED import
# ---------------------------------------------------------------------------

_A_PROTO = (
    'syntax = "proto3";\n'
    "package demo;\n"
    'import weak "demo/missing.proto";\n'
    "message A { int32 x = 1; }\n"
)
_B_PROTO = (
    'syntax = "proto3";\n'
    "package demo;\n"
    'import "demo/missing.proto";\n'
    "message B { int32 y = 1; }\n"
)
_IMPORT_A = 'import "demo/a.proto";'
_IMPORT_B = 'import "demo/b.proto";'


def _root_proto(first: str, second: str) -> str:
    return (
        'syntax = "proto3";\n'
        "package demo;\n"
        f"{first}\n"
        f"{second}\n"
        "message Root { A a = 1; B b = 2; }\n"
    )


def _weak_order_repo(base: Path, name: str, first: str, second: str) -> Path:
    """Repo whose root.proto imports two files in a chosen order.

    ``demo/missing.proto`` exists at no ref. ``demo/a.proto`` imports it
    WEAKLY, ``demo/b.proto`` imports it as a REQUIRED import. The only
    difference between the two repos this builds is which of the two
    ``import`` lines in ``root.proto`` comes first -- i.e. which ``kind``
    is attached to the FIRST dequeued occurrence of ``demo/missing.proto``.
    """
    repo = _init_repo(base / name)
    _write(repo, "demo/a.proto", _A_PROTO)
    _write(repo, "demo/b.proto", _B_PROTO)
    _write(repo, "demo/root.proto", _root_proto(first, second))
    _commit_all(repo, f"{name}: root imports {first} then {second}")
    return repo


@pytest.fixture
def weak_first_repo(tmp_path: Path) -> Path:
    return _weak_order_repo(tmp_path, "weak_first", _IMPORT_A, _IMPORT_B)


@pytest.fixture
def required_first_repo(tmp_path: Path) -> Path:
    return _weak_order_repo(tmp_path, "req_first", _IMPORT_B, _IMPORT_A)


def test_u14_7_guard_required_first_correctly_refuses_to_compile(
    weak_first_repo: Path, required_first_repo: Path,
) -> None:
    """Guard: the two repos are line-order permutations of each other, and
    with the REQUIRED import dequeued first the missing dep is correctly
    fatal. This is the behaviour the weak-first repo must match.
    """
    weak_root = (weak_first_repo / "demo/root.proto").read_text()
    req_root = (required_first_repo / "demo/root.proto").read_text()
    assert weak_root != req_root
    assert sorted(weak_root.splitlines()) == sorted(req_root.splitlines())

    with pytest.raises(ProtoImportError) as excinfo:
        extract_pool_from_ref(
            "HEAD", "demo/root.proto", cwd=required_first_repo,
        )
    assert "demo/missing.proto" in str(excinfo.value)


@pytest.mark.xfail(
    strict=True,
    raises=pytest.fail.Exception,
    reason=(
        "U14-7: _extract_proto_tree's `visited` set (git.py:800-808) is keyed on "
        "the import PATH alone and the dequeued `kind` is discarded, so when the "
        "WEAK occurrence of demo/missing.proto is dequeued first it writes a stub "
        "and marks the path visited -- the later REQUIRED occurrence is dropped by "
        "the `if import_path in visited` guard and never raises. Swapping the two "
        "import lines in root.proto is the ONLY difference from the guard test "
        "above, which does raise: import order alone decides whether compilation "
        "correctly fails."
    ),
)
def test_u14_7_weak_first_suppresses_required_import_of_same_missing_file(
    weak_first_repo: Path,
) -> None:
    with pytest.raises(ProtoImportError):
        extract_pool_from_ref("HEAD", "demo/root.proto", cwd=weak_first_repo)


# ---------------------------------------------------------------------------
# U14-8 -- overlapping proto_roots: first-match stripping drops the commit
# ---------------------------------------------------------------------------

_OUTER_FIRST: tuple[str, ...] = ("proto", "proto/acme")
_INNER_FIRST: tuple[str, ...] = ("proto/acme", "proto")

_COMMON_WITH_B = (
    'syntax = "proto3";\n'
    "package acme;\n"
    "message Common { int32 a = 1; string b = 2; }\n"
)
_COMMON_WITHOUT_B = (
    'syntax = "proto3";\n'
    "package acme;\n"
    "message Common { int32 a = 1; }\n"
)


@pytest.fixture
def overlapping_roots_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """Repo with nested proto roots and an INNER-root-relative import.

    ``proto/acme/user.proto`` imports its sibling as ``"common.proto"``,
    which only resolves through the inner root ``proto/acme``, while the
    root file ``acme/user.proto`` only resolves through the outer root
    ``proto``. Both roots are therefore genuinely needed.

    Returns ``(repo, base_sha, breaking_sha)``.
    """
    repo = _init_repo(tmp_path / "overlapping_roots")
    _write(
        repo,
        "proto/acme/user.proto",
        'syntax = "proto3";\n'
        "package acme;\n"
        'import "common.proto";\n'
        "message User { Common c = 1; int32 id = 2; }\n",
    )
    _write(repo, "proto/acme/common.proto", _COMMON_WITH_B)
    base_sha = _commit_all(repo, "c1: user + common")

    _write(
        repo,
        "proto/acme/unrelated.proto",
        'syntax = "proto3";\npackage acme;\nmessage Unrelated { int32 z = 1; }\n',
    )
    _commit_all(repo, "c2: add an unrelated proto")

    # c3: BREAKING -- removes Common.b, a field User depends on.
    _write(repo, "proto/acme/common.proto", _COMMON_WITHOUT_B)
    breaking_sha = _commit_all(repo, "c3: remove Common.b (breaking)")
    return repo, base_sha, breaking_sha


def test_u14_8_guard_construction_and_order_independent_dep_graph(
    overlapping_roots_repo: tuple[Path, str, str],
) -> None:
    """Guard: the dep graph is order-INdependent and the breaking commit is
    real and detectable.

    ``walk_dep_graph`` records the dep under the import-relative name
    produced by whichever root resolved it (``common.proto``), identically
    under both root orders -- so the dep side of the intersection is not
    what varies. ``fast=True`` and the inner-first exact walk both find the
    breaking commit, proving the commit genuinely touches the dep tree.
    """
    repo, base_sha, breaking_sha = overlapping_roots_repo
    rng = f"{base_sha}..HEAD"

    # The breaking commit really removes the field User depends on.
    blob = _git("show", f"{breaking_sha}:proto/acme/common.proto", cwd=repo)
    assert "string b = 2" not in blob
    changed = _git(
        "show", "--name-only", "--format=", breaking_sha, cwd=repo,
    ).splitlines()
    assert "proto/acme/common.proto" in changed

    deps_outer = walk_dep_graph("HEAD", "acme/user.proto", _OUTER_FIRST, cwd=repo)
    deps_inner = walk_dep_graph("HEAD", "acme/user.proto", _INNER_FIRST, cwd=repo)
    assert deps_outer == deps_inner == {"acme/user.proto", "common.proto"}

    # Detectable today via the fast walk (both orders) and via the exact
    # walk when the INNER root happens to be listed first.
    for roots in (_OUTER_FIRST, _INNER_FIRST):
        assert commits_affecting_dep_tree(
            rng, "acme/user.proto", roots, fast=True, cwd=repo,
        ) == [breaking_sha]
    assert commits_affecting_dep_tree(
        rng, "acme/user.proto", _INNER_FIRST, cwd=repo,
    ) == [breaking_sha]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "U14-8: _strip_proto_root() (git.py:406-419) returns on the FIRST "
        "prefix match with no knowledge of which root actually resolved the "
        "file, so with proto_roots=('proto', 'proto/acme') the changed path "
        "proto/acme/common.proto strips to 'acme/common.proto' while "
        "walk_dep_graph() recorded the same dep as 'common.proto' (resolved via "
        "the inner root). _commits_affecting_exact() intersects the two, so the "
        "breaking commit is dropped -- and listing the SAME two roots in the "
        "opposite order finds it. Exact history (the documented full-correctness "
        "mode) must not depend on proto_roots ordering."
    ),
)
def test_u14_8_exact_history_depends_on_proto_root_ordering(
    overlapping_roots_repo: tuple[Path, str, str],
) -> None:
    repo, base_sha, breaking_sha = overlapping_roots_repo
    rng = f"{base_sha}..HEAD"

    outer_first = commits_affecting_dep_tree(
        rng, "acme/user.proto", _OUTER_FIRST, cwd=repo,
    )
    inner_first = commits_affecting_dep_tree(
        rng, "acme/user.proto", _INNER_FIRST, cwd=repo,
    )
    # Same roots, same range, same root proto -- only the ORDER of the two
    # overlapping roots differs, so the two results must agree...
    assert outer_first == inner_first
    # ...and both must name the dependency-breaking commit, and only it.
    assert outer_first == [breaking_sha]
