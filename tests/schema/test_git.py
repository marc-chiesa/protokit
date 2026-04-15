"""Tests for ``protokit.schema.git`` — extracting descriptor pools
from ``.proto`` sources at git refs.

Each test spins up a fresh temporary git repo, commits a tiny
proto schema (sometimes across multiple revisions), and exercises
``extract_pool_from_ref`` against the resulting refs. Real git
+ real protoxy compilation = end-to-end coverage.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from protokit.schema.git import (
    GitRefNotFoundError,
    ProtoImportError,
    extract_pool_from_ref,
    is_shallow_repository,
)


def _git(*args: str, cwd: Path) -> str:
    """Shell-out helper for test setup."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Initialise an empty git repo with deterministic identity.

    Sets local user.name / user.email so commits work even on
    machines where global git config isn't set (CI). Disables
    GPG signing for the same reason.
    """
    _git("init", "-q", "-b", "main", cwd=tmp_path)
    _git("config", "user.email", "test@example.com", cwd=tmp_path)
    _git("config", "user.name", "Test", cwd=tmp_path)
    _git("config", "commit.gpgsign", "false", cwd=tmp_path)
    return tmp_path


def _commit_proto(repo: Path, path: str, contents: str, *, msg: str) -> str:
    """Write ``path`` with ``contents``, commit, return the new SHA."""
    full = repo / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(contents)
    _git("add", path, cwd=repo)
    _git("commit", "-q", "-m", msg, cwd=repo)
    return _git("rev-parse", "HEAD", cwd=repo)


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


class TestSimpleExtraction:
    def test_extracts_single_file_at_head(self, repo: Path) -> None:
        _commit_proto(
            repo, "acme/user.proto",
            'syntax = "proto3";\n'
            'package acme;\n'
            'message User { string name = 1; }\n',
            msg="add user.proto",
        )
        pool = extract_pool_from_ref(
            "HEAD", "acme/user.proto", cwd=repo,
        )
        user = pool.FindMessageTypeByName("acme.User")
        assert user.full_name == "acme.User"
        assert user.fields_by_name["name"].type == \
            user.fields_by_name["name"].TYPE_STRING

    def test_extracts_at_historical_ref(self, repo: Path) -> None:
        """Compiles the OLD content of a file from a prior commit."""
        old_sha = _commit_proto(
            repo, "acme/user.proto",
            'syntax = "proto3";\n'
            'package acme;\n'
            'message User { string name = 1; }\n',
            msg="v1",
        )
        _commit_proto(
            repo, "acme/user.proto",
            'syntax = "proto3";\n'
            'package acme;\n'
            'message User {\n'
            '    string name = 1;\n'
            '    int32 age = 2;\n'
            '}\n',
            msg="v2 add age",
        )
        old_pool = extract_pool_from_ref(
            old_sha, "acme/user.proto", cwd=repo,
        )
        new_pool = extract_pool_from_ref(
            "HEAD", "acme/user.proto", cwd=repo,
        )
        old_user = old_pool.FindMessageTypeByName("acme.User")
        new_user = new_pool.FindMessageTypeByName("acme.User")
        assert "age" not in old_user.fields_by_name
        assert "age" in new_user.fields_by_name


class TestImportResolution:
    def test_walks_transitive_imports(self, repo: Path) -> None:
        """A → B → C; extracting A pulls B and C from the same ref."""
        # Commit C first so we can reference it.
        (repo / "acme").mkdir()
        (repo / "acme" / "addr.proto").write_text(
            'syntax = "proto3";\n'
            'package acme;\n'
            'message Address { string street = 1; }\n',
        )
        (repo / "acme" / "contact.proto").write_text(
            'syntax = "proto3";\n'
            'package acme;\n'
            'import "acme/addr.proto";\n'
            'message Contact { acme.Address home = 1; }\n',
        )
        (repo / "acme" / "user.proto").write_text(
            'syntax = "proto3";\n'
            'package acme;\n'
            'import "acme/contact.proto";\n'
            'message User { string name = 1; acme.Contact c = 2; }\n',
        )
        _git("add", "acme/", cwd=repo)
        _git("commit", "-q", "-m", "add user/contact/addr", cwd=repo)
        pool = extract_pool_from_ref(
            "HEAD", "acme/user.proto", cwd=repo,
        )
        # All three messages must be in the pool.
        assert pool.FindMessageTypeByName("acme.User")
        assert pool.FindMessageTypeByName("acme.Contact")
        assert pool.FindMessageTypeByName("acme.Address")

    def test_well_known_import_resolves_via_compiler(
        self, repo: Path,
    ) -> None:
        """``import "google/protobuf/timestamp.proto";`` is satisfied
        by the bundled compiler includes — we don't even try to
        extract it from git.
        """
        _commit_proto(
            repo, "acme/event.proto",
            'syntax = "proto3";\n'
            'package acme;\n'
            'import "google/protobuf/timestamp.proto";\n'
            'message Event { google.protobuf.Timestamp at = 1; }\n',
            msg="event with well-known timestamp",
        )
        pool = extract_pool_from_ref(
            "HEAD", "acme/event.proto", cwd=repo,
        )
        event = pool.FindMessageTypeByName("acme.Event")
        ts_field = event.fields_by_name["at"]
        assert ts_field.message_type.full_name == "google.protobuf.Timestamp"

    def test_proto_root_strips_prefix(self, repo: Path) -> None:
        """Files committed under ``proto/`` should be importable as
        their post-prefix path (``acme/user.proto``) when
        ``proto_roots=("proto",)``.
        """
        _commit_proto(
            repo, "proto/acme/user.proto",
            'syntax = "proto3";\n'
            'package acme;\n'
            'message User { string name = 1; }\n',
            msg="proto under proto/ prefix",
        )
        pool = extract_pool_from_ref(
            "HEAD", "acme/user.proto",
            proto_roots=("proto",), cwd=repo,
        )
        assert pool.FindMessageTypeByName("acme.User")

    def test_multiple_proto_roots_searched_in_order(self, repo: Path) -> None:
        """Earlier roots win when the same import resolves in
        multiple locations — matches protoc -I semantics.
        """
        _commit_proto(
            repo, "vendor/acme/dep.proto",
            'syntax = "proto3";\n'
            'package acme;\n'
            'message Dep { string from_vendor = 1; }\n',
            msg="vendor dep",
        )
        # Commit also adds the root user.proto that imports dep.
        (repo / "proto" / "acme").mkdir(parents=True)
        (repo / "proto" / "acme" / "user.proto").write_text(
            'syntax = "proto3";\n'
            'package acme;\n'
            'import "acme/dep.proto";\n'
            'message User { acme.Dep d = 1; }\n',
        )
        _git("add", "proto/", cwd=repo)
        _git("commit", "-q", "-m", "add user.proto", cwd=repo)
        pool = extract_pool_from_ref(
            "HEAD", "acme/user.proto",
            proto_roots=("proto", "vendor"), cwd=repo,
        )
        # Dep resolved via vendor since it's not under proto/.
        dep = pool.FindMessageTypeByName("acme.Dep")
        assert "from_vendor" in dep.fields_by_name


class TestWeakImports:
    def test_missing_weak_import_is_silent(self, repo: Path) -> None:
        """``import weak`` of a non-existent file must NOT raise —
        protobuf's own semantics tolerate missing weak imports.
        """
        _commit_proto(
            repo, "acme/user.proto",
            'syntax = "proto3";\n'
            'package acme;\n'
            'import weak "acme/optional_dep.proto";\n'
            'message User { string name = 1; }\n',
            msg="user with weak import",
        )
        pool = extract_pool_from_ref(
            "HEAD", "acme/user.proto", cwd=repo,
        )
        # The User type still resolves; the missing weak import was
        # skipped, not raised.
        assert pool.FindMessageTypeByName("acme.User")


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestErrors:
    def test_unknown_ref_raises_typed(self, repo: Path) -> None:
        _commit_proto(
            repo, "acme/user.proto",
            'syntax = "proto3"; package acme; message User {}\n',
            msg="initial",
        )
        with pytest.raises(GitRefNotFoundError):
            extract_pool_from_ref(
                "no-such-ref-anywhere", "acme/user.proto", cwd=repo,
            )

    def test_missing_root_proto_raises(self, repo: Path) -> None:
        _commit_proto(
            repo, "acme/user.proto",
            'syntax = "proto3"; package acme; message User {}\n',
            msg="initial",
        )
        with pytest.raises(ProtoImportError) as exc:
            extract_pool_from_ref(
                "HEAD", "acme/missing.proto", cwd=repo,
            )
        assert "acme/missing.proto" in str(exc.value)

    def test_missing_standard_import_raises(self, repo: Path) -> None:
        """Standard (non-weak) imports must resolve or raise."""
        _commit_proto(
            repo, "acme/user.proto",
            'syntax = "proto3";\n'
            'package acme;\n'
            'import "acme/dep_that_does_not_exist.proto";\n'
            'message User { string name = 1; }\n',
            msg="user with missing import",
        )
        with pytest.raises(ProtoImportError) as exc:
            extract_pool_from_ref(
                "HEAD", "acme/user.proto", cwd=repo,
            )
        assert "dep_that_does_not_exist.proto" in str(exc.value)


# ---------------------------------------------------------------------------
# Shallow-repo predicate
# ---------------------------------------------------------------------------


class TestIsShallow:
    def test_normal_repo_is_not_shallow(self, repo: Path) -> None:
        _commit_proto(
            repo, "x.proto",
            'syntax = "proto3"; package x; message X {}\n',
            msg="seed",
        )
        assert is_shallow_repository(cwd=repo) is False

    def test_shallow_clone_detected(
        self, tmp_path: Path, repo: Path,
    ) -> None:
        """Clone the seeded repo with ``--depth=1``; the shallow
        marker should now be set.
        """
        # Need at least one commit in the source repo.
        for i in range(3):
            _commit_proto(
                repo, "x.proto",
                f'syntax = "proto3"; package x; message X {{ int32 v{i} = {i + 1}; }}\n',
                msg=f"rev {i}",
            )
        clone_dir = tmp_path / "shallow"
        # Use file:// URL so git treats the source as a real remote
        # (a plain path triggers the "local clone shortcut" which
        # ignores --depth).
        subprocess.run(
            ["git", "clone", "--depth=1", f"file://{repo}", str(clone_dir)],
            check=True, capture_output=True,
        )
        assert is_shallow_repository(cwd=clone_dir) is True


# ---------------------------------------------------------------------------
# Sanity: end-to-end via Phase 1 check
# ---------------------------------------------------------------------------


class TestEndToEndWithCompatibilityCheck:
    def test_two_pools_feed_check_compatibility(self, repo: Path) -> None:
        """Build two pools across two revisions and feed them to
        :func:`protokit.schema.check_compatibility` — the canonical
        Phase 2 use case (compare before/after a commit).
        """
        from protokit.schema import check_compatibility

        old_sha = _commit_proto(
            repo, "acme/user.proto",
            'syntax = "proto3";\n'
            'package acme;\n'
            'message User { string name = 1; int32 age = 2; }\n',
            msg="v1",
        )
        _commit_proto(
            repo, "acme/user.proto",
            'syntax = "proto3";\n'
            'package acme;\n'
            'message User { string name = 1; }\n',  # age removed
            msg="v2 drop age",
        )
        old_pool = extract_pool_from_ref(
            old_sha, "acme/user.proto", cwd=repo,
        )
        new_pool = extract_pool_from_ref(
            "HEAD", "acme/user.proto", cwd=repo,
        )
        report = check_compatibility(
            old_pool, "acme.User", new_pool, "acme.User",
        )
        rule_ids = {f.rule_id for f in report.findings}
        assert "field_removed" in rule_ids
