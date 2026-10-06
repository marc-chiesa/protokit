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

V30, R20-C1, R20-C2 and R20-C4 -- four more ways ``compat history`` /
         ``compat bisect`` drop a dependency-breaking commit and exit 0 with
         "no commits touch": a non-ASCII dependency name, ``--proto-root
         ./proto``, a run from a repository subdirectory, and four import
         spellings the import regex cannot see. All owned by the parent
         plan's U13 (0.18.0); the comment above their section at the end of
         this file has each mechanism.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from protokit.schema.cli import main as compat_main
from protokit.schema.compile import compile_protos_to_result
from protokit.schema.git import (
    ProtoImportError,
    _is_well_known,
    _parse_imports,
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


# ---------------------------------------------------------------------------
# V30, R20-C1, R20-C2, R20-C4 -- a dependency-breaking commit is dropped and
# compat history / compat bisect exit 0 with "no commits touch"
# ---------------------------------------------------------------------------
#
# All four are owned by the parent plan's U13 (0.18.0). Every pin below is a
# strict xfail whose reason leads with its ID, and each flips to XPASS on the
# fix. They share one construction (``_dep_break_repo``): ``acme/user.proto``
# imports a dependency, and the second commit removes ``Date.month`` from the
# dependency only -- a break ``compat check --since`` reports with exit 1. In
# every case the commit enumeration comes back empty, so the walk takes its
# empty-range branch and exits 0.
#
# V30    -- ``_files_changed_in_commit`` reads ``git show --name-only`` as
#           text. Under git's default ``core.quotePath`` a path holding a
#           non-ASCII byte is printed C-quoted inside double quotes
#           (``"acme/dat\303\251.proto"``), which fails the
#           ``endswith(".proto")`` filter, so the commit appears to change no
#           proto at all. ``--fast`` (a per-path ``git log``) finds it.
#           Cycle 1 re-confirmed this as R20-C3.
# R20-C1 -- ``_strip_proto_root`` compares changed paths against the root as
#           typed. git never prints a leading ``./``, so with ``--proto-root
#           ./proto`` the changed path ``proto/acme/date.proto`` is left
#           unstripped and never matches the dep set's ``acme/date.proto``.
#           The same root spelled ``proto`` works, and every other reader of
#           ``./proto`` (the dep graph, ``--fast``, ``check --since``) accepts
#           it.
# R20-C2 -- the enumeration's pathspecs (``*.proto`` in exact mode, each
#           dependency path under ``--fast``) are resolved by ``git log``
#           against the working directory, while ``git show REF:path`` stays
#           relative to the repository root. Run from a subdirectory, both
#           modes match nothing, while ``check --since`` from the same
#           directory reads the same files and exits 1.
# R20-C4 -- ``_parse_imports`` is a line-anchored, double-quote-only regex
#           applied after block comments are blanked. It sees no import in
#           four spellings the compiler accepts: a single-quoted path, an
#           import sharing its line with another statement, an import between
#           two ``//`` comments that happen to contain ``/*`` and ``*/``, and
#           an import on the closing line of a block comment (the comment's
#           newline is blanked with it). The dependency is then missing from
#           the dep graph (history / bisect exit 0) and from the tree
#           extracted from the ref (``check --since`` exits 2).

_DATE_WITH_MONTH = (
    'syntax = "proto3";\n'
    "package acme;\n"
    "message Date { int32 year = 1; int32 month = 2; }\n"
)
_DATE_WITHOUT_MONTH = (
    'syntax = "proto3";\n'
    "package acme;\n"
    "message Date { int32 year = 1; }\n"
)
_ASCII_DEP = "acme/date.proto"
_NON_ASCII_DEP = "acme/dat\u00e9.proto"  # U+00E9, precomposed
_USER_ARGS = ("--proto-file", "acme/user.proto", "--type", "acme.User")
_WALKS = ("history", "bisect")

# Each header replaces the plain one ``_import_header`` writes. All four
# compile (``test_r20_c4_guard_each_import_form_compiles_directly``).
_ODD_IMPORT_HEADERS: dict[str, str] = {
    "single_quotes": (
        'syntax = "proto3";\n'
        "package acme;\n"
        "import 'acme/date.proto';\n"
    ),
    "same_line_as_package": (
        'syntax = "proto3";\n'
        'package acme; import "acme/date.proto";\n'
    ),
    "between_line_comments_holding_comment_marks": (
        'syntax = "proto3";\n'
        "// generated from specs/*\n"
        "package acme;\n"
        'import "acme/date.proto";\n'
        "// see v1/*/old\n"
    ),
    "on_a_block_comments_closing_line": (
        'syntax = "proto3"; /*\n'
        '*/ import "acme/date.proto";\n'
        "package acme;\n"
    ),
}
_ODD_IMPORT_FORMS = tuple(_ODD_IMPORT_HEADERS)


def _import_header(dep: str) -> str:
    return f'syntax = "proto3";\npackage acme;\nimport "{dep}";\n'


def _write_utf8(repo: Path, rel: str, text: str) -> None:
    """``_write`` with the encoding fixed: V30's root file names a non-ASCII path."""
    full = repo / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(text, encoding="utf-8")


def _dep_break_repo(
    base: Path,
    name: str,
    *,
    prefix: str = "",
    dep: str = _ASCII_DEP,
    header: str | None = None,
) -> tuple[Path, str, str]:
    """Repo whose second commit breaks ``acme.User`` through its dependency only.

    c1: ``acme/user.proto`` imports ``dep`` and uses ``acme.Date``; c2 removes
    ``Date.month`` from ``dep`` and touches nothing else. ``prefix`` puts both
    files under a source root; ``header`` replaces the root file's
    syntax/package/import lines.

    Returns ``(repo, base_sha, breaking_sha)``.
    """
    repo = _init_repo(base / name)
    user = (header or _import_header(dep)) + "message User { string name = 1; Date bday = 2; }\n"
    _write_utf8(repo, f"{prefix}{dep}", _DATE_WITH_MONTH)
    _write_utf8(repo, f"{prefix}acme/user.proto", user)
    base_sha = _commit_all(repo, "c1: user imports date")
    _write_utf8(repo, f"{prefix}{dep}", _DATE_WITHOUT_MONTH)
    breaking_sha = _commit_all(repo, "c2: remove Date.month (breaking, dependency only)")
    return repo, base_sha, breaking_sha


def _compat(monkeypatch: pytest.MonkeyPatch, cwd: Path, args: list[str]) -> Result:
    """Run ``protokit compat`` with the working directory at ``cwd``.

    The CLI's git calls use the process working directory, so the test has to
    move there; ``monkeypatch`` puts it back when the test ends.
    """
    monkeypatch.chdir(cwd)
    return CliRunner().invoke(compat_main, args, catch_exceptions=False)


def _walk_args(walk: str, base_sha: str, *extra: str) -> list[str]:
    """argv for ``compat history`` / ``compat bisect`` over ``base_sha..HEAD``."""
    endpoints = (
        ["--range", f"{base_sha}..HEAD"]
        if walk == "history"
        else ["--old", base_sha, "--new", "HEAD"]
    )
    return [walk, *endpoints, *_USER_ARGS, *extra]


def _check_since_args(base_sha: str, *extra: str) -> list[str]:
    return ["check", "--since", base_sha, *_USER_ARGS, *extra]


def _assert_walk_names_the_break(result: Result, breaking_sha: str) -> None:
    """What every history / bisect pin and control in this section asserts.

    Exit 2 means the walk could not run. That is never the defect pinned here
    (a clean exit 0), so it is reported through ``pytest.fail``: a pin whose
    ``raises=`` is ``AssertionError`` then goes red instead of absorbing it.
    """
    if result.exit_code not in (0, 1):
        pytest.fail(
            f"compat walk could not run (exit {result.exit_code}): {result.stderr.strip()!r}"
        )
    assert result.exit_code == 1, (
        f"exit {result.exit_code} over a breaking dependency change: {result.stdout.strip()!r}"
    )
    assert breaking_sha[:12] in result.stdout
    assert "field_removed" in result.stdout


def _assert_check_reports_the_break(result: Result) -> None:
    assert result.exit_code == 1, (
        f"exit {result.exit_code}: {(result.stdout or result.stderr).strip()!r}"
    )
    assert "field_removed" in result.stdout


# --- V30: a non-ASCII dependency name -------------------------------------


@pytest.fixture
def non_ascii_dep_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """The shared construction with a non-ASCII dependency name (``_NON_ASCII_DEP``).

    ``core.quotePath`` is set to git's default in the repository so that a
    developer's global ``core.quotePath=false`` cannot make the pins XPASS on
    one machine. ``-z`` or a command-line ``-c core.quotePath=false``, the two
    fixes on record, both take precedence over it.
    """
    repo, base_sha, breaking_sha = _dep_break_repo(tmp_path, "non_ascii_dep", dep=_NON_ASCII_DEP)
    _git("config", "core.quotePath", "true", cwd=repo)
    return repo, base_sha, breaking_sha


def test_v30_control_ascii_dependency_name_is_walked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control: the same repository with an ASCII dependency name."""
    repo, base_sha, breaking_sha = _dep_break_repo(tmp_path, "ascii_dep")
    _git("config", "core.quotePath", "true", cwd=repo)
    assert commits_affecting_dep_tree(
        f"{base_sha}..HEAD", "acme/user.proto", cwd=repo,
    ) == [breaking_sha]
    for walk in _WALKS:
        _assert_walk_names_the_break(
            _compat(monkeypatch, repo, _walk_args(walk, base_sha)), breaking_sha,
        )


def test_v30_guard_git_quotes_the_name_and_every_other_path_finds_the_break(
    non_ascii_dep_repo: tuple[Path, str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guard: the construction is valid and the quoted name is the only gap.

    git prints the changed path C-quoted; the dep graph still holds the real
    name; the fast enumeration and ``check --since`` both find the break.
    """
    repo, base_sha, breaking_sha = non_ascii_dep_repo
    changed = _git("show", "--name-only", "--format=", breaking_sha, cwd=repo)
    assert changed == r'"acme/dat\303\251.proto"'
    assert walk_dep_graph("HEAD", "acme/user.proto", cwd=repo) == {
        "acme/user.proto", _NON_ASCII_DEP,
    }
    assert commits_affecting_dep_tree(
        f"{base_sha}..HEAD", "acme/user.proto", fast=True, cwd=repo,
    ) == [breaking_sha]
    _assert_check_reports_the_break(_compat(monkeypatch, repo, _check_since_args(base_sha)))


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "V30: owned by the parent plan's U13 (0.18.0). _files_changed_in_commit() "
        "reads `git show --name-only` as text; under git's default "
        "core.quotePath a path holding a non-ASCII byte is printed C-quoted "
        "inside double quotes, fails the endswith('.proto') filter, and the "
        "commit that changes the dependency is dropped from exact history."
    ),
)
def test_v30_exact_history_must_keep_a_commit_that_changes_a_non_ascii_dependency(
    non_ascii_dep_repo: tuple[Path, str, str],
) -> None:
    repo, base_sha, breaking_sha = non_ascii_dep_repo
    assert commits_affecting_dep_tree(
        f"{base_sha}..HEAD", "acme/user.proto", cwd=repo,
    ) == [breaking_sha]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "V30: owned by the parent plan's U13 (0.18.0). With the commit dropped "
        "from exact history for its C-quoted non-ASCII path, compat history and "
        "compat bisect take the empty-range branch and exit 0 with 'no commits "
        "touch' over a break that --fast and check --since both report "
        "(R20-C3)."
    ),
)
@pytest.mark.parametrize("walk", _WALKS)
def test_v30_walk_must_report_a_break_in_a_non_ascii_dependency(
    non_ascii_dep_repo: tuple[Path, str, str], monkeypatch: pytest.MonkeyPatch, walk: str,
) -> None:
    repo, base_sha, breaking_sha = non_ascii_dep_repo
    _assert_walk_names_the_break(
        _compat(monkeypatch, repo, _walk_args(walk, base_sha)), breaking_sha,
    )


# --- R20-C1: --proto-root ./proto -----------------------------------------


@pytest.fixture
def proto_root_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """The shared construction under a ``proto/`` source root."""
    return _dep_break_repo(tmp_path, "proto_root", prefix="proto/")


def test_r20_c1_control_the_root_spelled_without_dot_slash_is_walked(
    proto_root_repo: tuple[Path, str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control: ``proto`` works, and ``./proto`` is a root everything else accepts."""
    repo, base_sha, breaking_sha = proto_root_repo
    rng = f"{base_sha}..HEAD"
    for root in ("proto", "proto/"):
        assert commits_affecting_dep_tree(
            rng, "acme/user.proto", (root,), cwd=repo,
        ) == [breaking_sha]
    for walk in _WALKS:
        _assert_walk_names_the_break(
            _compat(monkeypatch, repo, _walk_args(walk, base_sha, "--proto-root", "proto")),
            breaking_sha,
        )

    # ``./proto`` resolves the dep graph, the fast enumeration and
    # ``check --since``: the exact enumeration's stripping is the one reader
    # that rejects the spelling.
    assert walk_dep_graph("HEAD", "acme/user.proto", ("./proto",), cwd=repo) == {
        "acme/user.proto", _ASCII_DEP,
    }
    assert commits_affecting_dep_tree(
        rng, "acme/user.proto", ("./proto",), fast=True, cwd=repo,
    ) == [breaking_sha]
    _assert_check_reports_the_break(
        _compat(monkeypatch, repo, _check_since_args(base_sha, "--proto-root", "./proto")),
    )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "R20-C1: owned by the parent plan's U13 (0.18.0). _strip_proto_root() "
        "compares changed paths against the root as typed; git never prints a "
        "leading './', so with proto_roots=('./proto',) the changed path "
        "proto/acme/date.proto is left unstripped and never matches the dep "
        "set's acme/date.proto. The exact enumeration returns no commit; the "
        "same root spelled 'proto' returns the breaking one."
    ),
)
def test_r20_c1_exact_history_must_accept_a_dot_slash_proto_root(
    proto_root_repo: tuple[Path, str, str],
) -> None:
    repo, base_sha, breaking_sha = proto_root_repo
    assert commits_affecting_dep_tree(
        f"{base_sha}..HEAD", "acme/user.proto", ("./proto",), cwd=repo,
    ) == [breaking_sha]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "R20-C1: owned by the parent plan's U13 (0.18.0). compat history and "
        "compat bisect with --proto-root ./proto exit 0 with 'no commits touch' "
        "over a breaking dependency change that --proto-root proto, --fast and "
        "check --since all report with exit 1."
    ),
)
@pytest.mark.parametrize("walk", _WALKS)
def test_r20_c1_walk_with_a_dot_slash_proto_root_must_report_the_break(
    proto_root_repo: tuple[Path, str, str], monkeypatch: pytest.MonkeyPatch, walk: str,
) -> None:
    repo, base_sha, breaking_sha = proto_root_repo
    _assert_walk_names_the_break(
        _compat(monkeypatch, repo, _walk_args(walk, base_sha, "--proto-root", "./proto")),
        breaking_sha,
    )


# --- R20-C2: run from a repository subdirectory ---------------------------

_EXACT_AND_FAST = pytest.mark.parametrize("mode", [(), ("--fast",)], ids=["exact", "fast"])


@pytest.fixture
def subdir_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """The shared construction plus an empty ``docs/`` directory to run from."""
    repo, base_sha, breaking_sha = _dep_break_repo(tmp_path, "subdir")
    (repo / "docs").mkdir()
    return repo, base_sha, breaking_sha


def test_r20_c2_control_the_repo_root_is_walked_and_check_since_works_from_the_subdirectory(
    subdir_repo: tuple[Path, str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control: only the working directory differs from the pin below.

    ``check --since`` from ``docs/`` shows that running in a subdirectory is
    otherwise supported, and what the walks should report from there.
    """
    repo, base_sha, breaking_sha = subdir_repo
    for walk in _WALKS:
        for mode in ((), ("--fast",)):
            _assert_walk_names_the_break(
                _compat(monkeypatch, repo, _walk_args(walk, base_sha, *mode)), breaking_sha,
            )
    _assert_check_reports_the_break(
        _compat(monkeypatch, repo / "docs", _check_since_args(base_sha)),
    )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "R20-C2: owned by the parent plan's U13 (0.18.0). Run from a repository "
        "subdirectory, the commit enumeration's pathspecs ('*.proto' in exact "
        "mode, each dependency path under --fast) are resolved by `git log` "
        "against the working directory and match nothing, while `git show "
        "REF:path` stays root-relative. compat history and compat bisect exit 0 "
        "with 'no commits touch'; check --since from the same directory exits 1."
    ),
)
@_EXACT_AND_FAST
@pytest.mark.parametrize("walk", _WALKS)
def test_r20_c2_walk_from_a_subdirectory_must_report_the_break(
    subdir_repo: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
    walk: str,
    mode: tuple[str, ...],
) -> None:
    """A fix that refuses to run from a subdirectory (exit 2) fails this pin
    red rather than leaving it xfailed: see ``_assert_walk_names_the_break``.
    """
    repo, base_sha, breaking_sha = subdir_repo
    _assert_walk_names_the_break(
        _compat(monkeypatch, repo / "docs", _walk_args(walk, base_sha, *mode)), breaking_sha,
    )


# --- R20-C4: import spellings the regex cannot see ------------------------

_EVERY_ODD_IMPORT_FORM = pytest.mark.parametrize("form", _ODD_IMPORT_FORMS)


def test_r20_c4_control_the_plain_import_is_parsed_walked_and_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control: the same repository with ``import "acme/date.proto";`` on its own line."""
    assert _parse_imports(_import_header(_ASCII_DEP).encode()) == [("", _ASCII_DEP)]
    repo, base_sha, breaking_sha = _dep_break_repo(tmp_path, "plain_import")
    for walk in _WALKS:
        _assert_walk_names_the_break(
            _compat(monkeypatch, repo, _walk_args(walk, base_sha)), breaking_sha,
        )
    _assert_check_reports_the_break(_compat(monkeypatch, repo, _check_since_args(base_sha)))


@_EVERY_ODD_IMPORT_FORM
def test_r20_c4_guard_each_import_form_compiles_directly(tmp_path: Path, form: str) -> None:
    """Guard: the compiler accepts every spelling and resolves the import."""
    repo, _base_sha, _breaking_sha = _dep_break_repo(
        tmp_path, form, header=_ODD_IMPORT_HEADERS[form],
    )
    compiled = compile_protos_to_result([repo / "acme/user.proto"], [str(repo)])
    assert [d.category for d in compiled.diagnostics] == []
    bday = compiled.pool.FindMessageTypeByName("acme.User").fields_by_name["bday"]
    assert bday.message_type.full_name == "acme.Date"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "R20-C4: owned by the parent plan's U13 (0.18.0). _parse_imports() is a "
        "line-anchored, double-quote-only regex applied after block comments "
        "are blanked. It returns no import for a single-quoted path, for an "
        "import sharing its line with another statement, for an import between "
        "two // comments that contain '/*' and '*/', and for an import on the "
        "closing line of a block comment, whose newline is blanked with it."
    ),
)
@_EVERY_ODD_IMPORT_FORM
def test_r20_c4_parse_imports_must_see_the_import(form: str) -> None:
    assert _parse_imports(_ODD_IMPORT_HEADERS[form].encode()) == [("", _ASCII_DEP)]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "R20-C4: owned by the parent plan's U13 (0.18.0). An import "
        "_parse_imports() cannot see leaves the dependency out of the dep "
        "graph, so the commit that breaks it is dropped and compat history / "
        "compat bisect exit 0 with 'no commits touch' on a schema that compiles."
    ),
)
@_EVERY_ODD_IMPORT_FORM
@pytest.mark.parametrize("walk", _WALKS)
def test_r20_c4_walk_must_report_a_break_behind_the_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, walk: str, form: str,
) -> None:
    repo, base_sha, breaking_sha = _dep_break_repo(
        tmp_path, form, header=_ODD_IMPORT_HEADERS[form],
    )
    _assert_walk_names_the_break(
        _compat(monkeypatch, repo, _walk_args(walk, base_sha)), breaking_sha,
    )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "R20-C4: owned by the parent plan's U13 (0.18.0). The same unseen import "
        "leaves the dependency out of the tree extracted from the ref, so compat "
        "check --since exits 2 with an import-not-found compile error on a "
        "schema the compiler accepts, instead of reporting the break with exit 1."
    ),
)
@_EVERY_ODD_IMPORT_FORM
def test_r20_c4_check_since_must_compile_a_schema_the_compiler_accepts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, form: str,
) -> None:
    repo, base_sha, _breaking_sha = _dep_break_repo(
        tmp_path, form, header=_ODD_IMPORT_HEADERS[form],
    )
    _assert_check_reports_the_break(_compat(monkeypatch, repo, _check_since_args(base_sha)))
