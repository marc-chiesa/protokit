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
        result = CliRunner().invoke(main, [
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
        result = CliRunner().invoke(main, [
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
        result = CliRunner().invoke(main, [
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
        result = CliRunner().invoke(main, [
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
        result = CliRunner().invoke(main, [
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
        result = CliRunner().invoke(main, [
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
        result = CliRunner().invoke(main, [
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
        result = CliRunner().invoke(main, [
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


class TestQuiet:
    def test_quiet_no_output_exit_0(self, tmp_path: Path) -> None:
        old, new = _simple_pair(
            [{"name": "x", "number": 1, "type": T.TYPE_STRING}],
            [{"name": "x", "number": 1, "type": T.TYPE_STRING}],
        )
        old_path = _write_desc(tmp_path, "old", old, ["t.M"])
        new_path = _write_desc(tmp_path, "new", new, ["t.M"])
        result = CliRunner().invoke(main, [
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
        result = CliRunner().invoke(main, [
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
            result = CliRunner().invoke(main, [
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
            result = CliRunner().invoke(main, [
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
        result = CliRunner().invoke(main, [
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
        result = CliRunner().invoke(main, [str(old_path), str(new_path)])
        assert result.exit_code == 2
        assert "type" in result.output.lower()

    def test_conflicting_type_flags_exits_2(self, tmp_path: Path) -> None:
        old, new = _simple_pair([], [])
        old_path = _write_desc(tmp_path, "old", old, ["t.M"])
        new_path = _write_desc(tmp_path, "new", new, ["t.M"])
        result = CliRunner().invoke(main, [
            str(old_path), str(new_path),
            "--type", "t.M",
            "--old-type", "t.M",
        ])
        assert result.exit_code == 2

    def test_missing_new_type_in_cross_mode(self, tmp_path: Path) -> None:
        old, new = _simple_pair([], [])
        old_path = _write_desc(tmp_path, "old", old, ["t.M"])
        new_path = _write_desc(tmp_path, "new", new, ["t.M"])
        result = CliRunner().invoke(main, [
            str(old_path), str(new_path),
            "--old-type", "t.M",
        ])
        assert result.exit_code == 2
        assert "--new-type" in result.output

    def test_missing_type_in_pool_exits_2(self, tmp_path: Path) -> None:
        old, new = _simple_pair([], [])
        old_path = _write_desc(tmp_path, "old", old, ["t.M"])
        new_path = _write_desc(tmp_path, "new", new, ["t.M"])
        result = CliRunner().invoke(main, [
            str(old_path), str(new_path), "--type", "t.Nonexistent",
        ])
        assert result.exit_code == 2
        assert "not found" in result.output

    def test_proto_path_without_proto_exits_2(self, tmp_path: Path) -> None:
        old, new = _simple_pair([], [])
        old_path = _write_desc(tmp_path, "old", old, ["t.M"])
        new_path = _write_desc(tmp_path, "new", new, ["t.M"])
        result = CliRunner().invoke(main, [
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
        result = CliRunner().invoke(main, [
            str(bad), str(new_path), "--type", "t.M",
        ])
        assert result.exit_code == 2
        assert "OLD_INPUT" in result.output

    def test_invalid_ignore_path_exits_2(self, tmp_path: Path) -> None:
        old, new = _simple_pair([], [])
        old_path = _write_desc(tmp_path, "old", old, ["t.M"])
        new_path = _write_desc(tmp_path, "new", new, ["t.M"])
        result = CliRunner().invoke(main, [
            str(old_path), str(new_path), "--type", "t.M",
            "--ignore", "bad.trailing.",
        ])
        assert result.exit_code == 2
        assert "--ignore" in result.output
