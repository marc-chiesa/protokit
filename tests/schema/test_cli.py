"""CLI integration tests for ``protokit compat``."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest
from click.testing import CliRunner
from google.protobuf import descriptor_pb2, descriptor_pool

from protokit.schema.cli import main
from tests.schema.helpers import T, build_enum, build_message


# ---------------------------------------------------------------------------
# Helpers: write descriptor sets to disk so the CLI can read them
# ---------------------------------------------------------------------------


def _pool_to_descriptor_set_bytes(pool: descriptor_pool.DescriptorPool, type_names: list[str]) -> bytes:
    """Build a FileDescriptorSet covering the listed types (and deps)."""
    # Walk back from each type to its file descriptor proto.
    files: dict[str, descriptor_pb2.FileDescriptorProto] = {}
    pending = list(type_names)
    while pending:
        name = pending.pop()
        try:
            desc = pool.FindMessageTypeByName(name)
        except KeyError:
            desc = pool.FindEnumTypeByName(name)
        file_desc = desc.file
        if file_desc.name in files:
            continue
        fp = descriptor_pb2.FileDescriptorProto()
        file_desc.CopyToProto(fp)
        files[file_desc.name] = fp
        for dep in file_desc.dependencies:
            # Walk deps too — simple recursion.
            dep_fp = descriptor_pb2.FileDescriptorProto()
            dep.CopyToProto(dep_fp)
            files.setdefault(dep.name, dep_fp)

    fds = descriptor_pb2.FileDescriptorSet()
    for fp in files.values():
        fds.file.add().CopyFrom(fp)
    return fds.SerializeToString()


def _write_desc(tmp_path: Path, label: str, pool: descriptor_pool.DescriptorPool,
                type_names: list[str]) -> Path:
    p = tmp_path / f"{label}.descriptor_set"
    p.write_bytes(_pool_to_descriptor_set_bytes(pool, type_names))
    return p


def _simple_pair(old_fields: list[dict], new_fields: list[dict]):
    """Build two pools each with a single message ``t.M``."""
    old = descriptor_pool.DescriptorPool()
    new = descriptor_pool.DescriptorPool()
    build_message(old, "t.M", fields=old_fields)
    build_message(new, "t.M", fields=new_fields)
    return old, new


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


class TestCompatibleExit0:
    def test_identical_schemas_exit_0(self, tmp_path: Path) -> None:
        old, new = _simple_pair(
            [{"name": "x", "number": 1, "type": T.TYPE_STRING}],
            [{"name": "x", "number": 1, "type": T.TYPE_STRING}],
        )
        old_path = _write_desc(tmp_path, "old", old, ["t.M"])
        new_path = _write_desc(tmp_path, "new", new, ["t.M"])
        result = CliRunner().invoke(main, ["check", 
            str(old_path), str(new_path), "--type", "t.M",
        ])
        assert result.exit_code == 0
        assert "COMPATIBLE" in result.output


class TestIncompatibleExit1:
    def test_field_removed_exits_1(self, tmp_path: Path) -> None:
        old, new = _simple_pair(
            [{"name": "x", "number": 1, "type": T.TYPE_STRING}],
            [],
        )
        old_path = _write_desc(tmp_path, "old", old, ["t.M"])
        new_path = _write_desc(tmp_path, "new", new, ["t.M"])
        result = CliRunner().invoke(main, ["check", 
            str(old_path), str(new_path), "--type", "t.M",
        ])
        assert result.exit_code == 1
        assert "INCOMPATIBLE" in result.output
        assert "field_removed" in result.output


# ---------------------------------------------------------------------------
# Cross-type
# ---------------------------------------------------------------------------


class TestCrossType:
    def test_old_and_new_type_flags(self, tmp_path: Path) -> None:
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        build_message(old, "t.UserV1", fields=[
            {"name": "name", "number": 1, "type": T.TYPE_STRING},
            {"name": "email", "number": 2, "type": T.TYPE_STRING},
        ])
        build_message(new, "t.UserV2", fields=[
            {"name": "name", "number": 1, "type": T.TYPE_STRING},
        ])
        old_path = _write_desc(tmp_path, "old", old, ["t.UserV1"])
        new_path = _write_desc(tmp_path, "new", new, ["t.UserV2"])
        result = CliRunner().invoke(main, ["check", 
            str(old_path), str(new_path),
            "--old-type", "t.UserV1",
            "--new-type", "t.UserV2",
        ])
        assert result.exit_code == 1
        assert "field_removed" in result.output
        assert "email" in result.output


# ---------------------------------------------------------------------------
# Level filtering
# ---------------------------------------------------------------------------


class TestLevel:
    def test_consumer_safe_surfaces_field_added(self, tmp_path: Path) -> None:
        # Under compat-risk directions, field_added is BACKWARD
        # (old consumer reading new data sees unknown field).
        # CONSUMER_SAFE should surface it.
        old, new = _simple_pair(
            [],
            [{"name": "x", "number": 1, "type": T.TYPE_STRING}],
        )
        old_path = _write_desc(tmp_path, "old", old, ["t.M"])
        new_path = _write_desc(tmp_path, "new", new, ["t.M"])
        result = CliRunner().invoke(main, ["check", 
            str(old_path), str(new_path), "--type", "t.M",
            "--level", "consumer-safe",
        ])
        assert result.exit_code == 1
        assert "field_added" in result.output

    def test_producer_safe_filters_field_added(self, tmp_path: Path) -> None:
        # field_added is BACKWARD → filtered out of PRODUCER_SAFE.
        old, new = _simple_pair(
            [],
            [{"name": "x", "number": 1, "type": T.TYPE_STRING}],
        )
        old_path = _write_desc(tmp_path, "old", old, ["t.M"])
        new_path = _write_desc(tmp_path, "new", new, ["t.M"])
        result = CliRunner().invoke(main, ["check", 
            str(old_path), str(new_path), "--type", "t.M",
            "--level", "producer-safe",
        ])
        assert result.exit_code == 0
        assert "COMPATIBLE" in result.output

    def test_wire_only(self, tmp_path: Path) -> None:
        # Field number change is WIRE + BOTH → always visible.
        old, new = _simple_pair(
            [{"name": "x", "number": 1, "type": T.TYPE_STRING}],
            [{"name": "x", "number": 7, "type": T.TYPE_STRING}],
        )
        old_path = _write_desc(tmp_path, "old", old, ["t.M"])
        new_path = _write_desc(tmp_path, "new", new, ["t.M"])
        result = CliRunner().invoke(main, ["check", 
            str(old_path), str(new_path), "--type", "t.M",
            "--level", "wire",
        ])
        assert result.exit_code == 1
        assert "field_number_changed" in result.output


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------


class TestJsonOutput:
    def test_json_shape(self, tmp_path: Path) -> None:
        old, new = _simple_pair(
            [{"name": "x", "number": 1, "type": T.TYPE_STRING}],
            [],
        )
        old_path = _write_desc(tmp_path, "old", old, ["t.M"])
        new_path = _write_desc(tmp_path, "new", new, ["t.M"])
        result = CliRunner().invoke(main, ["check", 
            str(old_path), str(new_path), "--type", "t.M",
            "--format", "json",
        ])
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["compatible"] is False
        assert payload["level"] == "CONSUMER_SAFE"
        assert len(payload["findings"]) >= 1
        f = payload["findings"][0]
        assert set(f) == {"path", "rule_id", "severity", "direction", "message"}
        assert payload["summary"]["total"] == len(payload["findings"])
        assert payload["summary"]["semantic_breaks"] >= 1


# ---------------------------------------------------------------------------
# Ignore paths
# ---------------------------------------------------------------------------


class TestIgnore:
    def test_ignore_suppresses_path(self, tmp_path: Path) -> None:
        old, new = _simple_pair(
            [
                {"name": "x", "number": 1, "type": T.TYPE_STRING},
                {"name": "debug", "number": 2, "type": T.TYPE_STRING},
            ],
            [],
        )
        old_path = _write_desc(tmp_path, "old", old, ["t.M"])
        new_path = _write_desc(tmp_path, "new", new, ["t.M"])
        result = CliRunner().invoke(main, ["check", 
            str(old_path), str(new_path), "--type", "t.M",
            "--ignore", "debug",
        ])
        # x removal still fires; debug suppressed.
        assert result.exit_code == 1
        assert "debug" not in result.output
        assert "x" in result.output


# ---------------------------------------------------------------------------
# Quiet mode
# ---------------------------------------------------------------------------


class TestDedupeByType:
    """``--dedupe-by-type`` opts back into the original single-path behavior."""

    def _build_shared_pair(
        self, tmp_path: Path,
    ) -> tuple[Path, Path]:
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        from tests.schema.helpers import build_message as _build
        _build(old, "t.Shared", fields=[
            {"name": "secret", "number": 1, "type": T.TYPE_STRING},
        ])
        _build(new, "t.Shared", fields=[])
        for p, label in ((old, "old"), (new, "new")):
            _build(p, "t.Outer", fields=[
                {"name": "a", "number": 1, "type": T.TYPE_MESSAGE,
                 "type_name": "t.Shared"},
                {"name": "b", "number": 2, "type": T.TYPE_MESSAGE,
                 "type_name": "t.Shared"},
            ], file_name=f"cli_outer_{label}.proto")
        # Include both types so the emitted descriptor set carries
        # the Shared file alongside Outer (build_message doesn't
        # auto-wire dependency edges between sibling files).
        return (
            _write_desc(tmp_path, "old_shared", old, ["t.Outer", "t.Shared"]),
            _write_desc(tmp_path, "new_shared", new, ["t.Outer", "t.Shared"]),
        )

    def test_default_is_path_complete(self, tmp_path: Path) -> None:
        old_path, new_path = self._build_shared_pair(tmp_path)
        result = CliRunner().invoke(main, ["check", 
            str(old_path), str(new_path), "--type", "t.Outer",
            "--level", "strict",
        ])
        assert result.exit_code == 1
        # Both paths surface.
        assert "a.secret" in result.output
        assert "b.secret" in result.output

    def test_dedupe_flag_collapses_to_first_path(self, tmp_path: Path) -> None:
        old_path, new_path = self._build_shared_pair(tmp_path)
        result = CliRunner().invoke(main, ["check", 
            str(old_path), str(new_path), "--type", "t.Outer",
            "--level", "strict",
            "--dedupe-by-type",
        ])
        assert result.exit_code == 1
        # Exactly one of the two paths surfaces (first popped off the stack).
        assert ("a.secret" in result.output) != ("b.secret" in result.output)


class TestQuiet:
    def test_quiet_no_output_exit_0(self, tmp_path: Path) -> None:
        old, new = _simple_pair(
            [{"name": "x", "number": 1, "type": T.TYPE_STRING}],
            [{"name": "x", "number": 1, "type": T.TYPE_STRING}],
        )
        old_path = _write_desc(tmp_path, "old", old, ["t.M"])
        new_path = _write_desc(tmp_path, "new", new, ["t.M"])
        result = CliRunner().invoke(main, ["check", 
            str(old_path), str(new_path), "--type", "t.M", "--quiet",
        ])
        assert result.exit_code == 0
        assert result.output == ""

    def test_quiet_no_output_exit_1(self, tmp_path: Path) -> None:
        old, new = _simple_pair(
            [{"name": "x", "number": 1, "type": T.TYPE_STRING}],
            [],
        )
        old_path = _write_desc(tmp_path, "old", old, ["t.M"])
        new_path = _write_desc(tmp_path, "new", new, ["t.M"])
        result = CliRunner().invoke(main, ["check", 
            str(old_path), str(new_path), "--type", "t.M", "--quiet",
        ])
        assert result.exit_code == 1
        assert result.output == ""


# ---------------------------------------------------------------------------
# Rule pack
# ---------------------------------------------------------------------------


class TestRulePack:
    def test_rule_pack_plugin_fires(self, tmp_path: Path) -> None:
        # Build a throwaway rule-pack module accessible via importlib.
        pack_name = "protokit_test_rule_pack_cli"

        def every_field(ctx):
            from protokit.schema.model import Direction, Severity
            ctx.emit(
                severity=Severity.WIRE,
                message="every field flagged",
                direction=Direction.BOTH,
            )

        module = types.ModuleType(pack_name)
        module.RULES = [("every_field", every_field)]
        sys.modules[pack_name] = module
        try:
            old, new = _simple_pair(
                [{"name": "x", "number": 1, "type": T.TYPE_STRING}],
                [{"name": "x", "number": 1, "type": T.TYPE_STRING}],
            )
            old_path = _write_desc(tmp_path, "old", old, ["t.M"])
            new_path = _write_desc(tmp_path, "new", new, ["t.M"])
            result = CliRunner().invoke(main, ["check", 
                str(old_path), str(new_path), "--type", "t.M",
                "--level", "wire",
                "--rule-pack", pack_name,
            ])
            assert result.exit_code == 1
            assert "every_field" in result.output
        finally:
            sys.modules.pop(pack_name, None)

    def test_rule_pack_plugin_failure_exits_2(self, tmp_path: Path) -> None:
        """A plugin that raises must fail the CLI with exit 2.

        Otherwise a broken custom policy would silently pass CI
        with exit 0.
        """
        import types
        pack_name = "protokit_test_rule_pack_fail_closed"

        def boom(ctx):
            raise RuntimeError("policy logic exploded")

        module = types.ModuleType(pack_name)
        module.RULES = [("boom_rule", boom)]
        sys.modules[pack_name] = module
        try:
            old, new = _simple_pair(
                [{"name": "x", "number": 1, "type": T.TYPE_STRING}],
                [{"name": "x", "number": 1, "type": T.TYPE_STRING}],
            )
            old_path = _write_desc(tmp_path, "old", old, ["t.M"])
            new_path = _write_desc(tmp_path, "new", new, ["t.M"])
            result = CliRunner().invoke(main, ["check", 
                str(old_path), str(new_path), "--type", "t.M",
                "--rule-pack", pack_name,
            ])
            assert result.exit_code == 2
            # Warning surfaces to stderr (via mix_stderr=True default).
            assert "boom_rule" in result.output
            assert "RuntimeError" in result.output
        finally:
            sys.modules.pop(pack_name, None)

    def test_missing_rule_pack_module_exits_2(self, tmp_path: Path) -> None:
        old, new = _simple_pair([], [])
        old_path = _write_desc(tmp_path, "old", old, ["t.M"])
        new_path = _write_desc(tmp_path, "new", new, ["t.M"])
        result = CliRunner().invoke(main, ["check", 
            str(old_path), str(new_path), "--type", "t.M",
            "--rule-pack", "definitely.not.a.real.module",
        ])
        assert result.exit_code == 2
        assert "rule pack" in result.output


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestErrors:
    def test_missing_type_flag_exits_2(self, tmp_path: Path) -> None:
        old, new = _simple_pair([], [])
        old_path = _write_desc(tmp_path, "old", old, ["t.M"])
        new_path = _write_desc(tmp_path, "new", new, ["t.M"])
        result = CliRunner().invoke(main, ["check", str(old_path), str(new_path)])
        assert result.exit_code == 2
        assert "type" in result.output.lower()

    def test_conflicting_type_flags_exits_2(self, tmp_path: Path) -> None:
        old, new = _simple_pair([], [])
        old_path = _write_desc(tmp_path, "old", old, ["t.M"])
        new_path = _write_desc(tmp_path, "new", new, ["t.M"])
        result = CliRunner().invoke(main, ["check", 
            str(old_path), str(new_path),
            "--type", "t.M",
            "--old-type", "t.M",
        ])
        assert result.exit_code == 2

    def test_missing_new_type_in_cross_mode(self, tmp_path: Path) -> None:
        old, new = _simple_pair([], [])
        old_path = _write_desc(tmp_path, "old", old, ["t.M"])
        new_path = _write_desc(tmp_path, "new", new, ["t.M"])
        result = CliRunner().invoke(main, ["check", 
            str(old_path), str(new_path),
            "--old-type", "t.M",
        ])
        assert result.exit_code == 2
        assert "--new-type" in result.output

    def test_missing_type_in_pool_exits_2(self, tmp_path: Path) -> None:
        old, new = _simple_pair([], [])
        old_path = _write_desc(tmp_path, "old", old, ["t.M"])
        new_path = _write_desc(tmp_path, "new", new, ["t.M"])
        result = CliRunner().invoke(main, ["check", 
            str(old_path), str(new_path), "--type", "t.Nonexistent",
        ])
        assert result.exit_code == 2
        assert "not found" in result.output

    def test_proto_path_without_proto_exits_2(self, tmp_path: Path) -> None:
        old, new = _simple_pair([], [])
        old_path = _write_desc(tmp_path, "old", old, ["t.M"])
        new_path = _write_desc(tmp_path, "new", new, ["t.M"])
        result = CliRunner().invoke(main, ["check", 
            str(old_path), str(new_path), "--type", "t.M",
            "--proto-path", str(tmp_path),
        ])
        assert result.exit_code == 2
        assert "--proto" in result.output

    def test_malformed_descriptor_set_exits_2(self, tmp_path: Path) -> None:
        bad = tmp_path / "junk.descriptor_set"
        bad.write_bytes(b"this is not a FileDescriptorSet")
        old, new = _simple_pair([], [])
        new_path = _write_desc(tmp_path, "new", new, ["t.M"])
        result = CliRunner().invoke(main, ["check", 
            str(bad), str(new_path), "--type", "t.M",
        ])
        assert result.exit_code == 2
        assert "OLD_INPUT" in result.output

    def test_invalid_ignore_path_exits_2(self, tmp_path: Path) -> None:
        old, new = _simple_pair([], [])
        old_path = _write_desc(tmp_path, "old", old, ["t.M"])
        new_path = _write_desc(tmp_path, "new", new, ["t.M"])
        result = CliRunner().invoke(main, ["check",
            str(old_path), str(new_path), "--type", "t.M",
            "--ignore", "bad.trailing.",
        ])
        assert result.exit_code == 2
        assert "--ignore" in result.output


# ---------------------------------------------------------------------------
# Git-mode CLI tests (Phase 2)
# ---------------------------------------------------------------------------

import subprocess


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Initialise a git repo with deterministic identity."""
    _git("init", "-q", "-b", "main", cwd=tmp_path)
    _git("config", "user.email", "t@t", cwd=tmp_path)
    _git("config", "user.name", "Test", cwd=tmp_path)
    _git("config", "commit.gpgsign", "false", cwd=tmp_path)
    return tmp_path


def _commit(repo: Path, path: str, contents: str, *, msg: str) -> str:
    full = repo / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(contents)
    _git("add", path, cwd=repo)
    _git("commit", "-q", "-m", msg, cwd=repo)
    return _git("rev-parse", "HEAD", cwd=repo)


def _invoke_in_repo(repo: Path, args: list[str]):
    """Run the CLI with cwd=repo so git commands resolve correctly."""
    import os
    runner = CliRunner()
    cwd = os.getcwd()
    try:
        os.chdir(repo)
        return runner.invoke(main, args)
    finally:
        os.chdir(cwd)


_USER_V1 = (
    'syntax = "proto3";\n'
    'package acme;\n'
    'message User { string name = 1; int32 age = 2; }\n'
)
_USER_V2_DROP = (
    'syntax = "proto3";\n'
    'package acme;\n'
    'message User { string name = 1; }\n'  # age removed
)


class TestCheckSince:
    def test_against_prior_commit_detects_break(self, git_repo: Path) -> None:
        old_sha = _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        _commit(git_repo, "acme/user.proto", _USER_V2_DROP, msg="v2")
        result = _invoke_in_repo(git_repo, [
            "check", "--since", old_sha,
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
            "--level", "consumer-safe",
        ])
        assert result.exit_code == 1
        assert "field_removed" in result.output

    def test_unchanged_schema_is_compatible(self, git_repo: Path) -> None:
        old_sha = _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        # Same descriptors, only a comment differs → no findings.
        _commit(
            git_repo, "acme/user.proto",
            _USER_V1 + "// touched comment\n",
            msg="v1 + comment",
        )
        result = _invoke_in_repo(git_repo, [
            "check", "--since", old_sha,
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
        ])
        assert result.exit_code == 0
        assert "COMPATIBLE" in result.output

    def test_unknown_ref_exits_2(self, git_repo: Path) -> None:
        _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        result = _invoke_in_repo(git_repo, [
            "check", "--since", "no-such-ref",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
        ])
        assert result.exit_code == 2

    def test_missing_proto_file_flag_exits_2(self, git_repo: Path) -> None:
        old_sha = _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        result = _invoke_in_repo(git_repo, [
            "check", "--since", old_sha,
            "--type", "acme.User",
        ])
        assert result.exit_code == 2
        assert "--proto-file" in result.output

    def test_positional_inputs_with_since_exits_2(
        self, git_repo: Path, tmp_path: Path,
    ) -> None:
        old_sha = _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        # Create dummy files so click's exists=True doesn't fail first.
        a = tmp_path / "a.bin"; a.write_bytes(b"")
        b = tmp_path / "b.bin"; b.write_bytes(b"")
        result = _invoke_in_repo(git_repo, [
            "check", str(a), str(b),
            "--since", old_sha,
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
        ])
        assert result.exit_code == 2
        assert "Positional inputs cannot be combined" in result.output


class TestCheckAgainstBase:
    def test_explicit_base_branch(self, git_repo: Path) -> None:
        """--against-base BRANCH: compare HEAD vs merge-base with BRANCH."""
        # Setup: main has v1; create branch 'feature' with v2 (drop).
        _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1 on main")
        _git("checkout", "-q", "-b", "feature", cwd=git_repo)
        _commit(git_repo, "acme/user.proto", _USER_V2_DROP, msg="v2 on feature")
        result = _invoke_in_repo(git_repo, [
            "check", "--against-base", "main",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
        ])
        assert result.exit_code == 1
        assert "field_removed" in result.output

    def test_auto_base_falls_through_resolution(
        self, git_repo: Path,
    ) -> None:
        """Without an upstream / origin/main / origin/master, the
        auto-resolution must error with a clear message.
        """
        _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        result = _invoke_in_repo(git_repo, [
            "check", "--against-base",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
        ])
        assert result.exit_code == 2
        assert "no default base branch" in result.output

    def test_against_base_and_since_mutually_exclusive(
        self, git_repo: Path,
    ) -> None:
        old_sha = _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        result = _invoke_in_repo(git_repo, [
            "check",
            "--since", old_sha,
            "--against-base", "main",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
        ])
        assert result.exit_code == 2
        assert "mutually exclusive" in result.output


class TestHistory:
    def test_empty_range_exits_0_with_message(
        self, git_repo: Path,
    ) -> None:
        _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        # No further proto commits — range is empty.
        result = _invoke_in_repo(git_repo, [
            "history", "--range", "HEAD..HEAD",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
        ])
        assert result.exit_code == 0
        assert "no commits touch" in result.output

    def test_finds_break_in_range(self, git_repo: Path) -> None:
        _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        _commit(git_repo, "acme/user.proto", _USER_V2_DROP, msg="v2")
        result = _invoke_in_repo(git_repo, [
            "history", "--range", "HEAD~..HEAD",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
        ])
        assert result.exit_code == 1
        assert "BROKEN" in result.output
        assert "field_removed" in result.output

    def test_json_format(self, git_repo: Path) -> None:
        _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        _commit(git_repo, "acme/user.proto", _USER_V2_DROP, msg="v2")
        result = _invoke_in_repo(git_repo, [
            "history", "--range", "HEAD~..HEAD",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
            "--format", "json",
        ])
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["range"] == "HEAD~..HEAD"
        assert len(payload["entries"]) == 1
        entry = payload["entries"][0]
        assert entry["compatible"] is False
        rule_ids = [f["rule_id"] for f in entry["findings"]]
        assert "field_removed" in rule_ids


class TestBisect:
    def test_finds_first_breaking_commit(self, git_repo: Path) -> None:
        """Three commits: v1, v1.1 (comment-only), v2 (drops age = WIRE break).
        Bisect at --level wire must report v2 as the breaker —
        v1.1's no-op change must NOT trip the bisect.
        """
        _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        old_sha = _git("rev-parse", "HEAD", cwd=git_repo)
        _commit(
            git_repo, "acme/user.proto",
            _USER_V1 + "// v1.1 comment-only edit\n",
            msg="v1.1 comment-only (no descriptor change)",
        )
        breaker = _commit(git_repo, "acme/user.proto", _USER_V2_DROP, msg="v2 drop age")
        result = _invoke_in_repo(git_repo, [
            "bisect",
            "--old", old_sha,
            "--new", "HEAD",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
            "--level", "consumer-safe",
        ])
        assert result.exit_code == 1
        assert breaker in result.output
        assert "first breaking commit" in result.output

    def test_no_break_in_range_exits_0(self, git_repo: Path) -> None:
        """Comment-only edit produces no descriptor change —
        bisect should report no break at any level.
        """
        old_sha = _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        _commit(
            git_repo, "acme/user.proto",
            _USER_V1 + "// add a comment, descriptor unchanged\n",
            msg="comment-only edit",
        )
        result = _invoke_in_repo(git_repo, [
            "bisect",
            "--old", old_sha,
            "--new", "HEAD",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
        ])
        assert result.exit_code == 0
        assert "no break found" in result.output

    def test_unknown_old_ref_exits_2(self, git_repo: Path) -> None:
        _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        result = _invoke_in_repo(git_repo, [
            "bisect",
            "--old", "no-such-ref",
            "--new", "HEAD",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
        ])
        assert result.exit_code == 2


class TestCi:
    def test_against_explicit_base(self, git_repo: Path) -> None:
        _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1 on main")
        _git("checkout", "-q", "-b", "feature", cwd=git_repo)
        _commit(git_repo, "acme/user.proto", _USER_V2_DROP, msg="v2 on feature")
        result = _invoke_in_repo(git_repo, [
            "ci",
            "--base", "main",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
        ])
        assert result.exit_code == 1
        assert "field_removed" in result.output

    def test_clean_branch_exits_0(self, git_repo: Path) -> None:
        _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1 on main")
        _git("checkout", "-q", "-b", "feature", cwd=git_repo)
        _commit(
            git_repo, "acme/user.proto",
            _USER_V1 + "// add a comment\n",
            msg="comment-only edit on feature",
        )
        result = _invoke_in_repo(git_repo, [
            "ci",
            "--base", "main",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
        ])
        assert result.exit_code == 0
        assert "COMPATIBLE" in result.output

    def test_proto_file_required(self, git_repo: Path) -> None:
        _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        result = _invoke_in_repo(git_repo, [
            "ci", "--base", "main",
            "--type", "acme.User",
        ])
        # Click rejects missing required option → exit 2.
        assert result.exit_code == 2
