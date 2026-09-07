"""Regression pins for audit unit U1 / family U14 — ``schema/git.py`` ref
resolution and extraction.

Each test below pins the *mechanism* of a finding with a strict xfail: it
fails today (documenting the defect) and will flip loudly to ``xpassed`` the
moment the behaviour is fixed.

Findings pinned here:

* **U14-3** — ``extract_pool_from_ref()`` compiles via the legacy
  ``compile_proto()`` helper, losing the protoxy -> protoc fallback that
  ``compile_protos_to_result()`` implements.
* **U14-4** — a *moving* ref (e.g. ``origin/main``) is re-resolved on every
  ``_git_show()`` call, so a fetch landing mid-extraction can assemble a pool
  from two different commits.
* **U14-5** — an *empty* ref degenerates to ``git show :path``, which reads the
  staging index, so ``extract_pool_from_ref("", path)`` silently builds a pool
  from staged, uncommitted content.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from protokit.schema.git import (
    GitRefNotFoundError,
    extract_pool_from_ref,
    resolve_ref_sha,
    verify_ref,
)

# ---------------------------------------------------------------------------
# Throwaway-repo helpers (never touch the real repository's git state)
# ---------------------------------------------------------------------------


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Initialise a throwaway git repo with deterministic identity."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", "-b", "main", cwd=repo)
    _git("config", "user.email", "t@t", cwd=repo)
    _git("config", "user.name", "Test", cwd=repo)
    _git("config", "commit.gpgsign", "false", cwd=repo)
    return repo


def _commit(repo: Path, path: str, contents: str, *, msg: str) -> str:
    full = repo / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(contents)
    _git("add", path, cwd=repo)
    _git("commit", "-q", "-m", msg, cwd=repo)
    return _git("rev-parse", "HEAD", cwd=repo)


def _field_names(pool, full_name: str) -> list[str]:
    return [f.name for f in pool.FindMessageTypeByName(full_name).fields]


# ---------------------------------------------------------------------------
# U14-3
# ---------------------------------------------------------------------------


# ``edition = "2023"`` is valid protobuf that real protoc >= 27 compiles and
# that the installed protoxy (Rust ``protox``) cannot parse at all — the
# cleanest available "protoc can, protoxy cannot" input.
_EDITIONS_PROTO = (
    'edition = "2023";\n'
    'package probe;\n'
    'message M { int32 a = 1; }\n'
)


@pytest.fixture
def editions_repo(git_repo: Path) -> Path:
    _commit(git_repo, "demo/ed.proto", _EDITIONS_PROTO, msg="editions schema")
    return git_repo


def test_u14_3_protoxy_cannot_parse_the_editions_file(tmp_path: Path) -> None:
    """Premise control: the installed protoxy really does reject this input.

    Without this the pins below could pass for the wrong reason (e.g. a
    protoxy release that learned editions).
    """
    protoxy = pytest.importorskip("protoxy")
    src = tmp_path / "demo"
    src.mkdir()
    (src / "ed.proto").write_text(_EDITIONS_PROTO)
    with pytest.raises(protoxy.ProtoxyError):
        protoxy.compile(
            files=["demo/ed.proto"], includes=[str(tmp_path)],
            include_imports=True,
        )


def _editions_descriptor_set_bytes() -> bytes:
    """The ``FileDescriptorSet`` a real protoc emits for ``_EDITIONS_PROTO``.

    Hand-built rather than shelled out for, because this machine has no
    protoc: ``edition: EDITION_2023`` / ``syntax: "editions"`` is exactly what
    protoc >= 27 writes, and the python-protobuf runtime accepts it into a
    ``DescriptorPool`` unchanged.
    """
    from google.protobuf import descriptor_pb2

    fds = descriptor_pb2.FileDescriptorSet()
    fd = fds.file.add()
    fd.name = "demo/ed.proto"
    fd.package = "probe"
    fd.syntax = "editions"
    fd.edition = descriptor_pb2.Edition.EDITION_2023
    msg = fd.message_type.add()
    msg.name = "M"
    field = msg.field.add()
    field.name = "a"
    field.number = 1
    field.type = descriptor_pb2.FieldDescriptorProto.TYPE_INT32
    field.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    return fds.SerializeToString()


_FAKE_PROTOC = r'''
: > "$PROTOKIT_PROTOC_MARKER"
out=""
prev=""
for a in "$@"; do
  case "$a" in
    --descriptor_set_out=*) out="${a#--descriptor_set_out=}" ;;
  esac
  if [ "$prev" = "--descriptor_set_out" ]; then out="$a"; fi
  prev="$a"
done
if [ -z "$PROTOKIT_FAKE_FDS" ]; then
  echo "stand-in protoc: refusing to compile" >&2
  exit 1
fi
if [ -z "$out" ]; then
  echo "stand-in protoc: no --descriptor_set_out in argv" >&2
  exit 3
fi
cp "$PROTOKIT_FAKE_FDS" "$out"
exit 0
'''


def _install_fake_protoc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    succeeds: bool,
) -> Path:
    """Put a stand-in ``protoc`` first on ``PATH``; return the marker path.

    The marker file exists iff ``protoc`` was executed at all — that alone
    answers "was the fallback attempted?". When ``succeeds`` is true the
    stand-in also writes the descriptor set a real protoc would have emitted,
    so the caller can observe the fallback's *result* and not just its
    attempt. (No real protoc is installed on this machine; the stand-in is
    the only way to represent "protoc is available".)
    """
    marker = tmp_path / "protoc-was-invoked"
    fds_path = tmp_path / "editions.descriptor_set"
    if succeeds:
        fds_path.write_bytes(_editions_descriptor_set_bytes())
    bindir = tmp_path / "protoc-bin"
    bindir.mkdir()
    shim = bindir / "protoc"
    shim.write_text(f"#!/bin/sh\n{_FAKE_PROTOC}\n")
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PROTOKIT_PROTOC_MARKER", str(marker))
    monkeypatch.setenv("PROTOKIT_FAKE_FDS", str(fds_path) if succeeds else "")
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    return marker


def test_u14_3_library_entrypoint_does_fall_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control: ``compile_protos_to_result`` falls back and succeeds.

    Same process, same input, same stand-in protoc as the pins below. This is
    what makes the asymmetry attributable to the code path rather than to the
    environment — and it fails loudly if the stand-in ever stops working.
    """
    pytest.importorskip("protoxy")
    from protokit.schema.compile import compile_protos_to_result

    src = tmp_path / "src" / "demo"
    src.mkdir(parents=True)
    (src / "ed.proto").write_text(_EDITIONS_PROTO)
    _install_fake_protoc(tmp_path, monkeypatch, succeeds=True)

    result = compile_protos_to_result(
        [src / "ed.proto"], [str(tmp_path / "src")],
    )
    assert [d.category for d in result.diagnostics] == ["protoxy_fallback"]
    assert result.pool.FindMessageTypeByName("probe.M")


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "U14-3: extract_pool_from_ref() compiles through the legacy "
        "compile_proto(), whose backend choice is a hard if/else — protoxy "
        "when importable, protoc otherwise. When protoxy raises, protoc is "
        "never even executed, so the protoxy->protoc fallback that "
        "compile_protos_to_result() implements is absent from the git path."
    ),
)
def test_u14_3_protoc_fallback_is_attempted_when_protoxy_fails(
    editions_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("protoxy")
    marker = _install_fake_protoc(tmp_path, monkeypatch, succeeds=False)
    # Both backends failing is fine here — the stand-in protoc deliberately
    # exits non-zero. The pin is only about whether it was ever executed.
    with contextlib.suppress(SystemExit):
        extract_pool_from_ref("HEAD", "demo/ed.proto", cwd=editions_repo)
    assert marker.exists(), (
        "U14-3: protoxy failed and protoc was never executed — no fallback"
    )


@pytest.mark.xfail(
    strict=True,
    raises=SystemExit,
    reason=(
        "U14-3: with a working protoc on PATH, extract_pool_from_ref() still "
        "dies with SystemExit(2) 'protoxy compile failed' on a schema protoc "
        "compiles fine. Installing protoxy therefore turns a passing "
        "git-based compat check into a failing one."
    ),
)
def test_u14_3_extraction_succeeds_when_only_protoc_can_compile(
    editions_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("protoxy")
    _install_fake_protoc(tmp_path, monkeypatch, succeeds=True)
    pool = extract_pool_from_ref("HEAD", "demo/ed.proto", cwd=editions_repo)
    assert _field_names(pool, "probe.M") == ["a"]


# ---------------------------------------------------------------------------
# U14-4
# ---------------------------------------------------------------------------


_A_C1 = (
    'syntax = "proto3";\n'
    'package demo;\n'
    'import "demo/b.proto";\n'
    'message A { demo.B b = 1; }\n'
)
_B_C1 = (
    'syntax = "proto3";\n'
    'package demo;\n'
    'message B { int32 x = 1; }\n'
)
_A_C2 = (
    'syntax = "proto3";\n'
    'package demo;\n'
    'import "demo/b.proto";\n'
    'message A {\n'
    '  demo.B b = 1;\n'
    '  int32 only_in_c2 = 2;\n'
    '}\n'
)
_B_C2 = (
    'syntax = "proto3";\n'
    'package demo;\n'
    'message B {\n'
    '  int32 x = 1;\n'
    '  string only_in_c2 = 2;\n'
    '}\n'
)


@pytest.fixture
def two_commit_repo(git_repo: Path) -> tuple[Path, str, str]:
    """Repo on branch ``main`` with two commits; ``main`` reset back to c1.

    Returns ``(repo, c1_sha, c2_sha)``. ``demo/a.proto`` imports
    ``demo/b.proto`` so one extraction needs two ``git show`` calls, and every
    message gains a ``only_in_c2`` field at c2 so a pool's provenance is
    readable off its fields.
    """
    (git_repo / "demo").mkdir()
    (git_repo / "demo/a.proto").write_text(_A_C1)
    (git_repo / "demo/b.proto").write_text(_B_C1)
    _git("add", "demo", cwd=git_repo)
    _git("commit", "-q", "-m", "c1", cwd=git_repo)
    c1 = _git("rev-parse", "HEAD", cwd=git_repo)

    (git_repo / "demo/a.proto").write_text(_A_C2)
    (git_repo / "demo/b.proto").write_text(_B_C2)
    _git("add", "demo", cwd=git_repo)
    _git("commit", "-q", "-m", "c2", cwd=git_repo)
    c2 = _git("rev-parse", "HEAD", cwd=git_repo)

    # Put the branch back on c1; c2 stays a real, fetchable commit object.
    _git("update-ref", "refs/heads/main", c1, cwd=git_repo)
    return git_repo, c1, c2


def _install_git_shim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    body: str,
) -> Path:
    """Put a ``git`` wrapper first on ``PATH`` and return its bin directory.

    The wrapper always ends up executing the *real* git — nothing in
    ``protokit`` is patched, and no git behaviour is simulated. ``body`` is
    POSIX sh with ``$REAL_GIT`` bound to the genuine binary.
    """
    real_git = shutil.which("git")
    assert real_git, "git must be on PATH for these tests"
    bindir = tmp_path / "shim-bin"
    bindir.mkdir()
    shim = bindir / "git"
    shim.write_text(f'#!/bin/sh\nREAL_GIT="{real_git}"\n{body}\n')
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    return bindir


_LOGGING_SHIM = r'''
tab=$(printf '\t')
{
  sep=""
  for a in "$@"; do
    printf '%s%s' "$sep" "$a"
    sep="$tab"
  done
  printf '\n'
} >> "$PROTOKIT_GIT_LOG"
exec "$REAL_GIT" "$@"
'''


def _read_log(log: Path) -> list[list[str]]:
    if not log.exists():
        return []
    return [
        line.split("\t")
        for line in log.read_text().splitlines()
        if line
    ]


def _is_immutable_object_id(token: str, *, resolves_to: str) -> bool:
    """True when ``token`` is a raw object id (not a movable ref name)."""
    return (
        re.fullmatch(r"[0-9a-f]{7,40}", token) is not None
        and resolves_to.startswith(token)
    )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "U14-4: extract_pool_from_ref() hands the caller's symbolic ref to "
        "every _git_show() call, so `git show main:<path>` re-resolves the "
        "branch name once per file instead of pinning it to a SHA up front. "
        "resolve_ref_sha() exists for exactly this and is never used here."
    ),
)
def test_u14_4_ref_is_resolved_once_to_an_immutable_id(
    two_commit_repo: tuple[Path, str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Structural pin: every ``git show`` must name an immutable object.

    This is the precondition for the reported harm, asserted without any
    timing: if all of an extraction's ``git show`` invocations name one raw
    object id, a fetch landing mid-extraction cannot change what they read.
    Today they all name ``main``, which is re-resolved per process.

    Deliberately narrow: the shim only observes argv. If a fix stops using
    ``git show`` altogether the test fails (stays ``xfailed``) rather than
    flipping, which is the conservative direction.
    """
    repo, c1, _c2 = two_commit_repo
    log = tmp_path / "git-argv.log"
    monkeypatch.setenv("PROTOKIT_GIT_LOG", str(log))
    _install_git_shim(tmp_path, monkeypatch, _LOGGING_SHIM)

    extract_pool_from_ref("main", "demo/a.proto", cwd=repo)

    shows = [rec for rec in _read_log(log) if rec[:1] == ["show"]]
    assert len(shows) >= 2, f"expected a show per file, got {shows!r}"
    refs = {rec[1].split(":", 1)[0] for rec in shows}
    assert len(refs) == 1, f"one extraction used several refs: {refs!r}"
    (ref_used,) = refs
    assert _is_immutable_object_id(ref_used, resolves_to=c1), (
        f"U14-4: git show named the movable ref {ref_used!r} rather than the "
        f"SHA it resolved to ({c1}); each of the {len(shows)} calls re-resolves "
        "it independently"
    )


# The shim below performs a REAL `git update-ref refs/heads/main <c2>` — the
# same operation `git fetch` performs on a remote-tracking ref — after the
# first `git show` of the extraction has returned. Nothing about git or
# protokit is simulated and there is no timing dependence: the branch move is
# scheduled at a fixed interleaving point that a concurrent fetch genuinely
# hits, so the test is deterministic rather than racy.
_FETCH_MIDWAY_SHIM = r'''
if [ "$1" = "show" ]; then
  n=$(cat "$PROTOKIT_SHOW_COUNT" 2>/dev/null || echo 0)
  n=$((n + 1))
  echo "$n" > "$PROTOKIT_SHOW_COUNT"
  "$REAL_GIT" "$@"
  rc=$?
  if [ "$n" -eq 1 ]; then
    "$REAL_GIT" -C "$PROTOKIT_SHIM_REPO" update-ref refs/heads/main \
      "$PROTOKIT_SHIM_NEWSHA" >/dev/null 2>&1
  fi
  exit $rc
fi
exec "$REAL_GIT" "$@"
'''


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "U14-4: with the branch moved between two of the extraction's "
        "`git show` calls (a real `git update-ref`, i.e. what `git fetch` "
        "does), the returned pool mixes demo.A from the old commit with "
        "demo.B from the new one — a tree that exists in no commit."
    ),
)
def test_u14_4_pool_must_not_mix_two_commits(
    two_commit_repo: tuple[Path, str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, _c1, c2 = two_commit_repo
    monkeypatch.setenv("PROTOKIT_SHOW_COUNT", str(tmp_path / "show.count"))
    monkeypatch.setenv("PROTOKIT_SHIM_REPO", str(repo))
    monkeypatch.setenv("PROTOKIT_SHIM_NEWSHA", c2)
    _install_git_shim(tmp_path, monkeypatch, _FETCH_MIDWAY_SHIM)

    pool = extract_pool_from_ref("main", "demo/a.proto", cwd=repo)

    a_is_c2 = "only_in_c2" in _field_names(pool, "demo.A")
    b_is_c2 = "only_in_c2" in _field_names(pool, "demo.B")
    assert a_is_c2 == b_is_c2, (
        "U14-4: pool is a chimera — demo.A came from "
        f"{'c2' if a_is_c2 else 'c1'} and demo.B from "
        f"{'c2' if b_is_c2 else 'c1'}; no commit in the repository has that "
        "combination"
    )


# ---------------------------------------------------------------------------
# U14-5 — an empty ref silently reads the staging index
# ---------------------------------------------------------------------------


_M_HEAD = (
    'syntax = "proto3";\n'
    'package demo;\n'
    'message M { int32 committed_field = 1; }\n'
)
_M_INDEX = (
    'syntax = "proto3";\n'
    'package demo;\n'
    'message M {\n'
    '  int32 committed_field = 1;\n'
    '  string staged_only_field = 2;\n'
    '}\n'
)
_M_WORKTREE = (
    'syntax = "proto3";\n'
    'package demo;\n'
    'message M {\n'
    '  int32 committed_field = 1;\n'
    '  string staged_only_field = 2;\n'
    '  bool worktree_only_field = 3;\n'
    '}\n'
)


@pytest.fixture
def three_state_repo(git_repo: Path) -> Path:
    """Repo whose HEAD, index and worktree hold three distinct schemas.

    HEAD has one field, the staging index has two, the worktree has three,
    so whichever source a pool came from is identifiable from its fields
    alone.
    """
    _commit(git_repo, "demo/m.proto", _M_HEAD, msg="c1")
    (git_repo / "demo/m.proto").write_text(_M_INDEX)
    _git("add", "demo/m.proto", cwd=git_repo)          # index != HEAD
    (git_repo / "demo/m.proto").write_text(_M_WORKTREE)  # worktree != index
    return git_repo


def test_u14_5_empty_ref_is_not_resolvable(three_state_repo: Path) -> None:
    """Precondition: the module itself considers ``""`` an invalid ref.

    Not a pin — this is the control that makes the pin below meaningful.
    ``verify_ref``/``resolve_ref_sha`` are the module's own answer to "is
    this a ref?", and for ``""`` the answer is no.
    """
    assert verify_ref("", cwd=three_state_repo) is False
    with pytest.raises(GitRefNotFoundError):
        resolve_ref_sha("", cwd=three_state_repo)


def test_u14_5_head_ref_reads_the_commit(three_state_repo: Path) -> None:
    """Control: a real ref reads the commit, not the index or worktree."""
    pool = extract_pool_from_ref("HEAD", "demo/m.proto", cwd=three_state_repo)
    assert _field_names(pool, "demo.M") == ["committed_field"]


@pytest.mark.xfail(
    strict=True,
    raises=pytest.fail.Exception,
    reason=(
        "U14-5: extract_pool_from_ref('') builds `git show :demo/m.proto`, which "
        "reads the STAGING INDEX. An unresolvable ref (verify_ref -> False, "
        "resolve_ref_sha -> GitRefNotFoundError) silently succeeds against a "
        "different source of truth than every other ref."
    ),
)
def test_u14_5_empty_ref_must_not_silently_read_the_index(
    three_state_repo: Path,
) -> None:
    try:
        pool = extract_pool_from_ref("", "demo/m.proto", cwd=three_state_repo)
    except ValueError:
        # Fixed: the empty ref is rejected the way every other unresolvable
        # ref is (GitRefNotFoundError subclasses ValueError).
        return
    pytest.fail(
        "U14-5: extract_pool_from_ref('') returned a pool instead of "
        f"rejecting the ref; demo.M fields = {_field_names(pool, 'demo.M')!r} "
        "(the staging index's content, matching neither HEAD nor the worktree)"
    )
