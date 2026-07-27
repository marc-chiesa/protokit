"""CLI integration tests for ``protokit compat``."""

from __future__ import annotations

import json
import sys
import types
import warnings
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
                "--compat-rule-pack", pack_name,
            ], catch_exceptions=False)
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
                "--compat-rule-pack", pack_name,
            ], catch_exceptions=False)
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
            "--compat-rule-pack", "definitely.not.a.real.module",
        ], catch_exceptions=False)
        assert result.exit_code == 2
        assert "rule pack" in result.output

    # D7 — `--compat-rule-pack` rename + `--rule-pack` deprecation alias.
    # Each AE test wraps the invoke in `warnings.catch_warnings(record=True)
    # + simplefilter("always")`. record=True is load-bearing: CliRunner
    # intercepts stdout/stderr streams but does NOT route Python's warning
    # machinery into result.output, so a warning fired by warnings.warn()
    # without record=True is invisible to result.output assertions. With
    # record=True the AE assertions inspect the captured warning objects
    # directly (category, message text, count), which is also the in-repo
    # idiom at tests/formatters/test_formatters_registry.py:265 for similar UserWarning
    # checks. simplefilter("always") bypasses Python's per-message dedupe
    # registry that earlier --rule-pack tests in this class would otherwise
    # consume.

    def test_compat_rule_pack_loads_pack_no_warning(self, tmp_path: Path) -> None:
        """AE2 (R1, R5): `--compat-rule-pack` loads the pack and fires no deprecation warning."""
        pack_name = "protokit_test_compat_rule_pack_canonical"

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
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                result = CliRunner().invoke(main, ["check",
                    str(old_path), str(new_path), "--type", "t.M",
                    "--level", "wire",
                    "--compat-rule-pack", pack_name,
                ], catch_exceptions=False)
            assert result.exit_code == 1
            assert "every_field" in result.output
            # No --rule-pack deprecation warning on the canonical name.
            assert not [w for w in caught if "--rule-pack" in str(w.message)]
        finally:
            sys.modules.pop(pack_name, None)

    def test_rule_pack_legacy_emits_user_warning(self, tmp_path: Path) -> None:
        """AE1 (R3, R4, R10): `--rule-pack` loads the pack and emits a UserWarning containing all four required tokens."""
        pack_name = "protokit_test_rule_pack_legacy_warns"

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
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                result = CliRunner().invoke(main, ["check",
                    str(old_path), str(new_path), "--type", "t.M",
                    "--level", "wire",
                    "--rule-pack", pack_name,
                ], catch_exceptions=False)
            assert result.exit_code == 1
            assert "every_field" in result.output
            # Exactly one UserWarning mentioning --rule-pack (R6 once-per-invocation).
            rule_pack_warnings = [
                w for w in caught
                if issubclass(w.category, UserWarning) and "--rule-pack" in str(w.message)
            ]
            assert len(rule_pack_warnings) == 1, (
                f"expected exactly 1 --rule-pack deprecation warning, got {len(rule_pack_warnings)}"
            )
            msg = str(rule_pack_warnings[0].message)
            # R4 + R10 token presence (literal "1.0" pins the removal commitment).
            for token in ("--rule-pack", "deprecated", "1.0", "--compat-rule-pack"):
                assert token in msg, f"deprecation message missing token {token!r}: {msg!r}"
        finally:
            sys.modules.pop(pack_name, None)

    def test_both_flags_accumulate_warn_once(self, tmp_path: Path) -> None:
        """AE3 (R6): both flags supplied → both packs load AND deprecation warning fires exactly once."""
        legacy_pack = "protokit_test_rule_pack_both_legacy"
        canonical_pack = "protokit_test_rule_pack_both_canonical"

        def emit_legacy(ctx):
            from protokit.schema.model import Direction, Severity
            ctx.emit(severity=Severity.WIRE, message="legacy fired",
                     direction=Direction.BOTH)

        def emit_canonical(ctx):
            from protokit.schema.model import Direction, Severity
            ctx.emit(severity=Severity.WIRE, message="canonical fired",
                     direction=Direction.BOTH)

        legacy_module = types.ModuleType(legacy_pack)
        legacy_module.RULES = [("legacy_rule", emit_legacy)]
        canonical_module = types.ModuleType(canonical_pack)
        canonical_module.RULES = [("canonical_rule", emit_canonical)]
        sys.modules[legacy_pack] = legacy_module
        sys.modules[canonical_pack] = canonical_module
        try:
            old, new = _simple_pair(
                [{"name": "x", "number": 1, "type": T.TYPE_STRING}],
                [{"name": "x", "number": 1, "type": T.TYPE_STRING}],
            )
            old_path = _write_desc(tmp_path, "old", old, ["t.M"])
            new_path = _write_desc(tmp_path, "new", new, ["t.M"])
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                result = CliRunner().invoke(main, ["check",
                    str(old_path), str(new_path), "--type", "t.M",
                    "--level", "wire",
                    "--rule-pack", legacy_pack,
                    "--compat-rule-pack", canonical_pack,
                ], catch_exceptions=False)
            assert result.exit_code == 1
            # Both packs fired.
            assert "legacy_rule" in result.output
            assert "canonical_rule" in result.output
            # Exactly one deprecation warning, not two.
            rule_pack_warnings = [
                w for w in caught
                if issubclass(w.category, UserWarning) and "--rule-pack" in str(w.message)
            ]
            assert len(rule_pack_warnings) == 1, (
                f"expected exactly 1 deprecation warning even with both flags, got {len(rule_pack_warnings)}"
            )
        finally:
            sys.modules.pop(legacy_pack, None)
            sys.modules.pop(canonical_pack, None)


class TestCompatRulePackBinding:
    """Smoke tests: --compat-rule-pack + --rule-pack alias are wired uniformly
    across all 4 compat sub-subcommands.

    Full pack-load semantics are exercised on `check` via TestRulePack
    above. The parametrized tests here prove the decorator stack landed
    uniformly (canonical option, hidden alias, deprecation callback) without
    re-proving load depth on every sub-subcommand. A 5th sub-subcommand
    added later that forgets any piece of the pattern will fail one of
    these cases.
    """

    @pytest.mark.parametrize("subcommand", ["check", "history", "bisect", "ci"])
    def test_compat_rule_pack_decorator_wiring(self, subcommand: str) -> None:
        """Each compat sub-subcommand has --compat-rule-pack (visible) and
        --rule-pack (hidden alias with _warn_rule_pack_deprecated callback)."""
        from protokit.schema.cli import _warn_rule_pack_deprecated
        cmd = main.get_command(None, subcommand)
        canonical = next(
            (p for p in cmd.params if "--compat-rule-pack" in getattr(p, "opts", [])),
            None,
        )
        legacy = next(
            (
                p for p in cmd.params
                if "--rule-pack" in getattr(p, "opts", [])
                and "--compat-rule-pack" not in getattr(p, "opts", [])
            ),
            None,
        )
        assert canonical is not None, f"{subcommand}: --compat-rule-pack not registered"
        assert canonical.hidden is False, f"{subcommand}: --compat-rule-pack should be visible"
        assert legacy is not None, f"{subcommand}: --rule-pack alias not registered"
        assert legacy.hidden is True, f"{subcommand}: --rule-pack alias should be hidden"
        assert legacy.callback is _warn_rule_pack_deprecated, (
            f"{subcommand}: --rule-pack alias missing _warn_rule_pack_deprecated callback"
        )

    @pytest.mark.parametrize("subcommand", ["check", "history", "bisect", "ci"])
    def test_compat_rule_pack_visible_in_help(self, subcommand: str) -> None:
        """--compat-rule-pack appears in --help; the hidden --rule-pack alias does not.

        Per-line check is robust against Click's help wrapping — any line that
        mentions --rule-pack must also mention --compat-rule-pack, so the hidden
        legacy flag cannot slip through line-wrapped formatting.
        """
        result = CliRunner().invoke(
            main, [subcommand, "--help"], catch_exceptions=False,
        )
        assert result.exit_code == 0
        assert "--compat-rule-pack" in result.output
        for line in result.output.splitlines():
            if "--rule-pack" in line:
                assert "--compat-rule-pack" in line, (
                    f"{subcommand}: --rule-pack appeared in --help without "
                    f"--compat-rule-pack on the same line: {line!r}"
                )


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

    def test_compat_compile_failure_exit_code_2(self, tmp_path: Path) -> None:
        """End-to-end: ``protokit compat check --proto`` on a syntactically
        broken .proto exits 2 and surfaces the per-backend
        ``"X compile failed: "`` stderr prefix.

        Replaces the helper-level invariant from the deleted
        ``tests/core/test_cli_utils.py::TestProtoxyBackend::test_compile_failure_exits_with_code_2``
        which was testing the helper's ``error_exit`` behavior at the
        wrong layer post-refactor (helpers now raise typed exceptions;
        only the legacy adapter / CLI surface translates to ``SystemExit``).
        See protokit-lint Delivery 1 plan for the test-relayering audit.

        The asserted prefix is parameterized on the live backend: the
        ``has_protoxy=true`` matrix cell sees the ``protoxy compile failed:``
        path, the ``has_protoxy=false`` cell falls back to protoc and sees
        ``protoc compile failed:``. The contract under test is that
        EITHER backend's compile failure produces ``exit_code == 2`` plus
        the locked ``"<backend> compile failed: "`` stderr prefix.
        """
        from protokit import _cli_utils

        good = tmp_path / "good.proto"
        good.write_text(
            'syntax = "proto3";\npackage t;\nmessage M { string s = 1; }\n'
        )
        bad = tmp_path / "bad.proto"
        bad.write_text('syntax = "proto3";\nmessage {')  # broken
        result = CliRunner().invoke(main, ["check",
            "--proto", str(bad), str(good), "--type", "t.M",
        ])
        assert result.exit_code == 2
        # Locked stderr-string prefix per the post-refactor contract. The
        # exact word ("protoxy" vs "protoc") depends on which backend the
        # dispatcher selected at runtime.
        expected_prefix = (
            "protoxy compile failed: "
            if _cli_utils._has_protoxy()
            else "protoc compile failed: "
        )
        assert expected_prefix in result.output


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

    def test_missing_proto_file_surfaces_before_missing_type(
        self, git_repo: Path,
    ) -> None:
        """Gap 4: mode-specific missing-flag errors must fire BEFORE
        the generic 'no message type specified' error. A user who
        forgot both ``--type`` and ``--proto-file`` with ``--since``
        should see the proto-file error first — it's the next
        thing they need to fix for the mode they chose.
        """
        old_sha = _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        result = _invoke_in_repo(git_repo, [
            "check", "--since", old_sha,
            # Note: no --type and no --proto-file.
        ])
        assert result.exit_code == 2
        assert "--proto-file" in result.output
        # Must NOT surface the generic type error first.
        assert "No message type specified" not in result.output

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

    def test_proto_path_in_git_mode_exits_2(self, git_repo: Path) -> None:
        """``--proto-path`` is a local-mode flag. Combining with
        ``--since`` previously silently ignored the path; must
        now error with a clear message.
        """
        old_sha = _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        result = _invoke_in_repo(git_repo, [
            "check", "--since", old_sha,
            "--proto-file", "acme/user.proto",
            "--proto-path", "/custom/include",
            "--type", "acme.User",
        ])
        assert result.exit_code == 2
        assert "--proto-path" in result.output
        assert "--proto-root" in result.output

    def test_proto_flag_in_git_mode_exits_2(self, git_repo: Path) -> None:
        old_sha = _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        result = _invoke_in_repo(git_repo, [
            "check", "--since", old_sha,
            "--proto-file", "acme/user.proto",
            "--proto",
            "--type", "acme.User",
        ])
        assert result.exit_code == 2
        assert "--proto only applies in local-file mode" in result.output


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

    def test_json_has_resolved_shas_and_walk_count(
        self, git_repo: Path,
    ) -> None:
        """Gap 3: JSON payload includes top-level ``old`` / ``new``
        (resolved SHAs), ``commits_walked``, and aggregated
        ``diagnostics`` alongside the existing entries array.
        """
        _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        _commit(git_repo, "acme/user.proto", _USER_V2_DROP, msg="v2")
        result = _invoke_in_repo(git_repo, [
            "history", "--range", "HEAD~..HEAD",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
            "--format", "json",
        ])
        payload = json.loads(result.output)
        assert "old" in payload and len(payload["old"]) == 40  # full SHA
        assert "new" in payload and len(payload["new"]) == 40
        assert payload["commits_walked"] == 1
        assert payload["diagnostics"] == []  # no plugins registered

    def test_empty_range_json_shape_matches(
        self, git_repo: Path,
    ) -> None:
        """Empty-range JSON still carries the full top-level keys."""
        _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        result = _invoke_in_repo(git_repo, [
            "history", "--range", "HEAD..HEAD",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
            "--format", "json",
        ])
        payload = json.loads(result.output)
        assert payload["range"] == "HEAD..HEAD"
        assert payload["commits_walked"] == 0
        assert payload["entries"] == []
        assert payload["diagnostics"] == []
        assert "old" in payload and "new" in payload


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


class TestPluginParity:
    """Gap 2: history / bisect / ci all accept the full plugin
    surface (--compat-rule-pack, --ignore, --dedupe-by-type).
    """

    def test_history_accepts_ignore(self, git_repo: Path) -> None:
        _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        _commit(git_repo, "acme/user.proto", _USER_V2_DROP, msg="v2")
        # Without --ignore: break surfaces.
        result_plain = _invoke_in_repo(git_repo, [
            "history", "--range", "HEAD~..HEAD",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
        ])
        assert result_plain.exit_code == 1
        # With --ignore covering the dropped field's path: no break.
        result_ignored = _invoke_in_repo(git_repo, [
            "history", "--range", "HEAD~..HEAD",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
            "--ignore", "age",
        ])
        assert result_ignored.exit_code == 0

    def test_bisect_accepts_ignore(self, git_repo: Path) -> None:
        old_sha = _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        _commit(git_repo, "acme/user.proto", _USER_V2_DROP, msg="v2")
        result = _invoke_in_repo(git_repo, [
            "bisect",
            "--old", old_sha, "--new", "HEAD",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
            "--ignore", "age",
        ])
        assert result.exit_code == 0
        assert "no break found" in result.output

    def test_ci_accepts_ignore(self, git_repo: Path) -> None:
        _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1 on main")
        _git("checkout", "-q", "-b", "feature", cwd=git_repo)
        _commit(git_repo, "acme/user.proto", _USER_V2_DROP, msg="v2 on feature")
        # Without --ignore: break.
        result_plain = _invoke_in_repo(git_repo, [
            "ci", "--base", "main",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
        ])
        assert result_plain.exit_code == 1
        # With --ignore: clean.
        result_ignored = _invoke_in_repo(git_repo, [
            "ci", "--base", "main",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
            "--ignore", "age",
        ])
        assert result_ignored.exit_code == 0


class TestBisectKeepGoing:
    """Gap 2: ``--keep-going`` walks every commit, aggregating
    diagnostics AND finding the first break in one pass.
    """

    def test_without_keep_going_stops_at_first_break(
        self, git_repo: Path,
    ) -> None:
        old_sha = _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        # Two breaks in the range; default bisect stops at the first.
        _commit(git_repo, "acme/user.proto", _USER_V2_DROP, msg="v2 drop age")
        _commit(
            git_repo, "acme/user.proto",
            'syntax = "proto3";\n'
            'package acme;\n'
            'message User {}\n',  # name also dropped
            msg="v3 drop name too",
        )
        result = _invoke_in_repo(git_repo, [
            "bisect",
            "--old", old_sha, "--new", "HEAD",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
        ])
        assert result.exit_code == 1
        # The first breaking commit is printed; second break isn't
        # referenced in the output because the walk stopped early.
        lines = result.output.splitlines()
        assert sum(1 for line in lines if line.startswith("first breaking")) == 1

    def test_keep_going_still_reports_first_break(
        self, git_repo: Path,
    ) -> None:
        """With --keep-going, bisect walks to the end but still
        reports the EARLIEST breaking commit (bisect semantics).
        """
        old_sha = _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        first_break = _commit(
            git_repo, "acme/user.proto", _USER_V2_DROP,
            msg="v2 drop age",
        )
        _commit(
            git_repo, "acme/user.proto",
            'syntax = "proto3";\n'
            'package acme;\n'
            'message User {}\n',
            msg="v3 drop name too",
        )
        result = _invoke_in_repo(git_repo, [
            "bisect",
            "--old", old_sha, "--new", "HEAD",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
            "--keep-going",
        ])
        assert result.exit_code == 1
        assert first_break in result.output
        assert "first breaking commit" in result.output


class TestBisectDepAware:
    """Gap 1: bisect's default (exact) mode finds commits that
    broke the root proto via dep changes. ``--fast`` opts into
    E+ enumeration (faster but misses mid-range-only deps).
    """

    def _setup_dep_break(self, git_repo: Path) -> dict[str, str]:
        shas: dict[str, str] = {}
        shas["c1"] = _commit(
            git_repo, "acme/date.proto",
            'syntax = "proto3";\n'
            'package acme;\n'
            'message Date { int32 year = 1; int32 month = 2; }\n',
            msg="c1 date.proto",
        )
        shas["c2"] = _commit(
            git_repo, "acme/user.proto",
            'syntax = "proto3";\n'
            'package acme;\n'
            'import "acme/date.proto";\n'
            'message User { string name = 1; acme.Date bday = 2; }\n',
            msg="c2 user.proto imports date",
        )
        # c3 breaks date.proto WITHOUT touching user.proto.
        shas["c3"] = _commit(
            git_repo, "acme/date.proto",
            'syntax = "proto3";\n'
            'package acme;\n'
            'message Date { int32 year = 1; }\n',
            msg="c3 drop date.month",
        )
        return shas

    def test_default_mode_finds_dep_only_break(
        self, git_repo: Path,
    ) -> None:
        """The root-only enumeration would miss c3 (it doesn't
        touch user.proto). The dep-aware default catches it —
        ``field_removed`` on ``date.month`` surfaces at
        ``consumer-safe`` because it's SEMANTIC/BACKWARD.
        """
        shas = self._setup_dep_break(git_repo)
        result = _invoke_in_repo(git_repo, [
            "bisect",
            "--old", shas["c2"],  # after user.proto exists
            "--new", "HEAD",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
        ])
        assert result.exit_code == 1
        assert shas["c3"] in result.output
        assert "field_removed" in result.output

    def test_fast_mode_also_finds_dep_break(
        self, git_repo: Path,
    ) -> None:
        """In this scenario date.proto is in HEAD's dep tree, so
        fast mode also catches c3. (It would miss only in
        dep-swap cases where the broken dep isn't live at either
        endpoint.)
        """
        shas = self._setup_dep_break(git_repo)
        result = _invoke_in_repo(git_repo, [
            "bisect",
            "--old", shas["c2"],
            "--new", "HEAD",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
            "--fast",
        ])
        assert result.exit_code == 1
        assert shas["c3"] in result.output


class TestBisectJson:
    """Gap 3: ``bisect --format json`` emits structured output
    with resolved SHAs, commits_walked, and diagnostics.
    """

    def test_break_json_payload(self, git_repo: Path) -> None:
        old_sha = _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        breaker = _commit(
            git_repo, "acme/user.proto", _USER_V2_DROP,
            msg="v2 drop age",
        )
        result = _invoke_in_repo(git_repo, [
            "bisect",
            "--old", old_sha, "--new", "HEAD",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
            "--format", "json",
        ])
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["range"] == f"{old_sha}..HEAD"
        assert payload["old"] == old_sha
        assert len(payload["new"]) == 40
        assert payload["breaking_commit"] == breaker
        rule_ids = [f["rule_id"] for f in payload["findings"]]
        assert "field_removed" in rule_ids
        assert payload["commits_walked"] == 1
        assert payload["diagnostics"] == []

    def test_clean_json_payload(self, git_repo: Path) -> None:
        """No break in range → breaking_commit is null, exit 0."""
        old_sha = _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        _commit(
            git_repo, "acme/user.proto",
            _USER_V1 + "// no-op\n",
            msg="comment edit",
        )
        result = _invoke_in_repo(git_repo, [
            "bisect",
            "--old", old_sha, "--new", "HEAD",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
            "--format", "json",
        ])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["breaking_commit"] is None
        assert payload["findings"] == []
        assert payload["commits_walked"] >= 1

    def test_no_commits_json_payload(self, git_repo: Path) -> None:
        """Empty range JSON still carries every top-level key."""
        _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        result = _invoke_in_repo(git_repo, [
            "bisect",
            "--old", "HEAD", "--new", "HEAD",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
            "--format", "json",
        ])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["breaking_commit"] is None
        assert payload["commits_walked"] == 0
        assert payload["findings"] == []
        assert payload["diagnostics"] == []


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

    def test_auto_base_error_message_names_base_flag(
        self, git_repo: Path,
    ) -> None:
        """Regression lock: when ``ci`` auto-resolution fails, the
        error message must reference ``--base`` (the ci flag), not
        ``--against-base`` (the check flag). Before the fix the
        shared ``resolve_default_base`` always said
        ``--against-base``, which was wrong when invoked via ``ci``.
        """
        _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        # No --base, no upstream, no origin/main, no origin/master.
        result = _invoke_in_repo(git_repo, [
            "ci",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
        ])
        assert result.exit_code == 2
        assert "--base BRANCH" in result.output
        # And must NOT mention the check flag.
        assert "--against-base BRANCH" not in result.output


class TestQuietOnHistoryBisect:
    """Low-severity follow-up: ``--quiet`` suppresses stdout on
    ``history`` and ``bisect`` (diagnostics still stream to
    stderr; exit code unchanged).
    """

    def test_history_quiet_suppresses_stdout(self, git_repo: Path) -> None:
        _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        _commit(git_repo, "acme/user.proto", _USER_V2_DROP, msg="v2")
        result = _invoke_in_repo(git_repo, [
            "history", "--range", "HEAD~..HEAD",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
            "--quiet",
        ])
        assert result.exit_code == 1
        assert result.stdout == ""

    def test_bisect_quiet_suppresses_stdout(self, git_repo: Path) -> None:
        old_sha = _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        _commit(git_repo, "acme/user.proto", _USER_V2_DROP, msg="v2")
        result = _invoke_in_repo(git_repo, [
            "bisect",
            "--old", old_sha, "--new", "HEAD",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
            "--quiet",
        ])
        assert result.exit_code == 1
        assert result.stdout == ""


class TestProtoFilePrecheck:
    """Low-severity follow-up: a typoed ``--proto-file`` in git
    mode surfaces a clear CLI-layer error instead of a deep
    ``ProtoImportError``.
    """

    def test_check_since_missing_file_has_clean_error(
        self, git_repo: Path,
    ) -> None:
        old_sha = _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        result = _invoke_in_repo(git_repo, [
            "check", "--since", old_sha,
            "--proto-file", "acme/doesnotexist.proto",
            "--type", "acme.User",
        ])
        assert result.exit_code == 2
        assert "--proto-file" in result.output
        assert "doesnotexist.proto" in result.output
        assert "not found" in result.output.lower()

    def test_ci_missing_file_has_clean_error(
        self, git_repo: Path,
    ) -> None:
        _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1 on main")
        _git("checkout", "-q", "-b", "feature", cwd=git_repo)
        _commit(git_repo, "acme/user.proto", _USER_V2_DROP, msg="v2 on feature")
        result = _invoke_in_repo(git_repo, [
            "ci", "--base", "main",
            "--proto-file", "acme/nope.proto",
            "--type", "acme.User",
        ])
        assert result.exit_code == 2
        assert "nope.proto" in result.output


class TestCrossTypeBisect:
    """Low-severity follow-up: ``--old-type`` / ``--new-type``
    are accepted by ``bisect`` but were only tested on
    ``check``. Bisect pins the OLD pool once (so the OLD type
    name needs to exist only there) and compares each commit's
    NEW-type-named shape against it — the clean cross-type use
    case. (``history`` also accepts the flags, but each pair in
    the walk would need BOTH names resolvable on each side,
    which doesn't map cleanly onto a rename timeline.)
    """

    _USER_V1_NAMED_V1 = (
        'syntax = "proto3";\n'
        'package acme;\n'
        'message UserV1 { string name = 1; int32 age = 2; }\n'
    )
    _USER_V1_NAMED_V2 = (
        'syntax = "proto3";\n'
        'package acme;\n'
        'message UserV2 { string name = 1; int32 age = 2; }\n'
    )
    _USER_V2_NAMED_V2 = (
        'syntax = "proto3";\n'
        'package acme;\n'
        'message UserV2 { string name = 1; }\n'  # drop age
    )

    def test_bisect_cross_type_finds_rename_break(
        self, git_repo: Path,
    ) -> None:
        old_sha = _commit(
            git_repo, "acme/user.proto",
            self._USER_V1_NAMED_V1, msg="v1 UserV1",
        )
        rename_sha = _commit(
            git_repo, "acme/user.proto",
            self._USER_V1_NAMED_V2, msg="v2 rename to UserV2",
        )
        breaker = _commit(
            git_repo, "acme/user.proto",
            self._USER_V2_NAMED_V2, msg="v3 UserV2 drop age",
        )
        result = _invoke_in_repo(git_repo, [
            "bisect",
            "--old", old_sha,  # UserV1 existed here
            "--new", "HEAD",
            "--proto-file", "acme/user.proto",
            "--old-type", "acme.UserV1",
            "--new-type", "acme.UserV2",
        ])
        # The rename commit (rename_sha) itself produces no breaks
        # — both schemas have {name, age}. The drop at `breaker` is
        # the first commit where UserV2's shape diverges from UserV1.
        assert result.exit_code == 1
        assert breaker in result.output
        # And NOT the rename commit (that one is compatible).
        assert "first breaking commit: " + rename_sha not in result.output


class TestQuietJsonMutex:
    """Review follow-up: ``--quiet --format json`` used to emit
    empty stdout (CI scripts parsing the JSON hit zero bytes).
    The combination is now rejected with a clear error.
    """

    def test_check_rejects_quiet_plus_json(
        self, git_repo: Path, tmp_path: Path,
    ) -> None:
        # Build a minimal descriptor-set pair for local-file mode.
        from google.protobuf import descriptor_pool
        from tests.schema.helpers import build_message
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        build_message(old, "t.M", fields=[])
        build_message(new, "t.M", fields=[])
        old_path = _write_desc(tmp_path, "old", old, ["t.M"])
        new_path = _write_desc(tmp_path, "new", new, ["t.M"])
        result = CliRunner().invoke(main, [
            "check", str(old_path), str(new_path),
            "--type", "t.M",
            "--quiet", "--format", "json",
        ])
        assert result.exit_code == 2
        assert "--quiet" in result.output
        assert "json" in result.output.lower()

    def test_bisect_rejects_quiet_plus_json(
        self, git_repo: Path,
    ) -> None:
        _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        result = _invoke_in_repo(git_repo, [
            "bisect", "--old", "HEAD", "--new", "HEAD",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
            "--quiet", "--format", "json",
        ])
        assert result.exit_code == 2
        assert "--quiet" in result.output
        assert "json" in result.output.lower()

    def test_history_rejects_quiet_plus_json(
        self, git_repo: Path,
    ) -> None:
        _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        result = _invoke_in_repo(git_repo, [
            "history", "--range", "HEAD..HEAD",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
            "--quiet", "--format", "json",
        ])
        assert result.exit_code == 2
        assert "--quiet" in result.output
        assert "json" in result.output.lower()

    def test_ci_rejects_quiet_plus_json(
        self, git_repo: Path,
    ) -> None:
        _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1 main")
        _git("checkout", "-q", "-b", "feature", cwd=git_repo)
        _commit(
            git_repo, "acme/user.proto",
            _USER_V1 + "// comment edit\n",
            msg="feature edit",
        )
        result = _invoke_in_repo(git_repo, [
            "ci", "--base", "main",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
            "--quiet", "--format", "json",
        ])
        assert result.exit_code == 2
        assert "--quiet" in result.output
        assert "json" in result.output.lower()

    @pytest.mark.parametrize("structured_format", ["junit", "sarif"])
    def test_history_rejects_quiet_plus_structured(
        self, git_repo: Path, structured_format: str,
    ) -> None:
        # Regression for the 2026-04-19 review (testing P2): the
        # widened reject_quiet_plus_structured must reject every
        # non-human format, not just json. junit and sarif on
        # history/bisect/ci had no test coverage prior.
        _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        result = _invoke_in_repo(git_repo, [
            "history", "--range", "HEAD..HEAD",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
            "--quiet", "--format", structured_format,
        ])
        assert result.exit_code == 2
        assert "--quiet" in result.output
        assert structured_format in result.output

    @pytest.mark.parametrize("structured_format", ["junit", "sarif"])
    def test_bisect_rejects_quiet_plus_structured(
        self, git_repo: Path, structured_format: str,
    ) -> None:
        _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        result = _invoke_in_repo(git_repo, [
            "bisect", "--old", "HEAD", "--new", "HEAD",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
            "--quiet", "--format", structured_format,
        ])
        assert result.exit_code == 2
        assert "--quiet" in result.output
        assert structured_format in result.output

    @pytest.mark.parametrize("structured_format", ["junit", "sarif"])
    def test_ci_rejects_quiet_plus_structured(
        self, git_repo: Path, structured_format: str,
    ) -> None:
        _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1 main")
        _git("checkout", "-q", "-b", "feature", cwd=git_repo)
        _commit(
            git_repo, "acme/user.proto",
            _USER_V1 + "// comment edit\n",
            msg="feature edit",
        )
        result = _invoke_in_repo(git_repo, [
            "ci", "--base", "main",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
            "--quiet", "--format", structured_format,
        ])
        assert result.exit_code == 2
        assert "--quiet" in result.output
        assert structured_format in result.output


class TestHistoryBisectStructuredFormats:
    """End-to-end CLI dispatch of structured formatters
    on history and bisect — closes the integration-test gap
    flagged in the 2026-04-19 review (testing P2). The unit
    tests in ``test_formatters_junit.py`` /
    ``test_formatters_sarif.py`` cover formatter shape; these
    tests cover the full pipeline (CLI args → report → context
    → formatter → stdout → schema validation).
    """

    def _validate_junit(self, xml_str: str) -> None:
        import xmlschema
        from pathlib import Path as _Path
        xsd = _Path(__file__).parent.parent / "fixtures" / "junit-xml" / "JUnit.xsd"
        xmlschema.XMLSchema(str(xsd)).validate(xml_str)

    def _validate_sarif(self, json_str: str) -> None:
        import json as _json
        import jsonschema
        from pathlib import Path as _Path
        schema_path = _Path(__file__).parent.parent / "fixtures" / "sarif" / "sarif-2.1.0.json"
        with open(schema_path) as f:
            schema = _json.load(f)
        validator = jsonschema.Draft7Validator(schema)
        payload = _json.loads(json_str)
        errors = list(validator.iter_errors(payload))
        assert not errors, "\n".join(
            f"{list(e.path)}: {e.message}" for e in errors
        )

    def test_history_junit_round_trip_validates(
        self, git_repo: Path,
    ) -> None:
        _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        _commit(git_repo, "acme/user.proto", _USER_V2_DROP, msg="v2")
        result = _invoke_in_repo(git_repo, [
            "history", "--range", "HEAD~1..HEAD",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
            "--format", "junit",
        ])
        # exit 1 on findings, 2 on diagnostics (none here).
        assert result.exit_code in (0, 1)
        self._validate_junit(result.output)

    def test_history_sarif_round_trip_validates(
        self, git_repo: Path,
    ) -> None:
        _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        _commit(git_repo, "acme/user.proto", _USER_V2_DROP, msg="v2")
        result = _invoke_in_repo(git_repo, [
            "history", "--range", "HEAD~1..HEAD",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
            "--format", "sarif",
        ])
        assert result.exit_code in (0, 1)
        self._validate_sarif(result.output)

    def test_bisect_junit_round_trip_validates(
        self, git_repo: Path,
    ) -> None:
        old_sha = _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        _commit(git_repo, "acme/user.proto", _USER_V2_DROP, msg="v2 break")
        result = _invoke_in_repo(git_repo, [
            "bisect", "--old", old_sha, "--new", "HEAD",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
            "--format", "junit",
        ])
        assert result.exit_code in (0, 1)
        self._validate_junit(result.output)

    def test_bisect_sarif_round_trip_validates(
        self, git_repo: Path,
    ) -> None:
        old_sha = _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        _commit(git_repo, "acme/user.proto", _USER_V2_DROP, msg="v2 break")
        result = _invoke_in_repo(git_repo, [
            "bisect", "--old", old_sha, "--new", "HEAD",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
            "--format", "sarif",
        ])
        assert result.exit_code in (0, 1)
        self._validate_sarif(result.output)


class TestCiQuiet:
    """Review follow-up: ``ci`` now accepts ``--quiet`` for
    pipeline gates that want exit-code-only output.
    """

    def test_ci_quiet_suppresses_stdout(
        self, git_repo: Path,
    ) -> None:
        _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1 main")
        _git("checkout", "-q", "-b", "feature", cwd=git_repo)
        _commit(git_repo, "acme/user.proto", _USER_V2_DROP, msg="v2 drop")
        result = _invoke_in_repo(git_repo, [
            "ci", "--base", "main",
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
            "--quiet",
        ])
        assert result.exit_code == 1  # break detected
        assert result.stdout == ""


class TestEntryPointDispatch:
    """Low-severity follow-up: all schema-CLI tests invoke
    ``protokit.schema.cli.main`` directly, bypassing the
    top-level ``protokit.cli:main`` group. A typo in the
    top-level dispatch could never be caught. One end-to-end
    test forces the full dispatch chain to run.
    """

    def test_compat_check_via_top_level_cli(
        self, git_repo: Path,
    ) -> None:
        import os
        from protokit.cli import main as top_level_main
        _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
        prev = os.getcwd()
        os.chdir(git_repo)
        try:
            result = CliRunner().invoke(top_level_main, [
                "compat", "check",
                "--since", "HEAD",
                "--proto-file", "acme/user.proto",
                "--type", "acme.User",
            ])
        finally:
            os.chdir(prev)
        # HEAD vs HEAD → compatible, exit 0. The important thing is
        # that the invocation was dispatched correctly through the
        # top-level group.
        assert result.exit_code == 0
        assert "COMPATIBLE" in result.output


class TestUnclassifiedGitFailureExitCode:
    """P2-12: a ``git show`` failure that ``_git_show`` deliberately
    does NOT classify must exit 2 (error), never 1.

    The documented contract is 0=compatible / 1=incompatible /
    2=error. ``_git_show`` re-raises the bare
    ``subprocess.CalledProcessError`` for anything outside its six
    known stderr substrings — on purpose, because re-labelling the
    unknown as ``FileNotFoundError`` would turn a corrupt object DB
    or an unreadable ``.git`` into "this import doesn't exist" and
    silently produce a truncated dependency graph. The CLI boundary
    is therefore where the unclassified failure must be caught:
    without that catch it escapes through Click as a traceback and
    the process exits 1, so a pipeline gating on exit codes records
    a compatibility BREAK that never happened.
    """

    def test_path_outside_repository_exits_2_not_1(
        self, git_repo: Path,
    ) -> None:
        # ``git show HEAD:../outside.proto`` fails with "fatal:
        # '../outside.proto' is outside repository", which matches
        # none of _git_show's classifier substrings.
        _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1 on main")
        _git("checkout", "-q", "-b", "feature", cwd=git_repo)
        _commit(git_repo, "acme/user.proto", _USER_V2_DROP, msg="v2")
        result = _invoke_in_repo(git_repo, [
            "ci", "--base", "main",
            "--proto-file", "../outside.proto",
            "--type", "acme.User",
        ])
        assert result.exit_code == 2, (
            f"expected exit 2 (error), got {result.exit_code}; "
            f"exception={result.exception!r}"
        )
        assert "Error:" in result.stderr

    @pytest.mark.parametrize(
        "subcommand,extra_args",
        [
            ("check", ["--since", "HEAD~"]),
            ("ci", ["--base", "main"]),
            ("history", ["--range", "HEAD~..HEAD"]),
            ("bisect", ["--old", "HEAD~", "--new", "HEAD"]),
        ],
    )
    def test_unclassified_git_failure_exits_2_for_every_subcommand(
        self,
        git_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        subcommand: str,
        extra_args: list[str],
    ) -> None:
        """Every git-mode subcommand needs the same boundary guard.

        Simulates the general case (corrupt object DB, permission
        denied on .git, gitlink) by forcing ``_git_show`` down its
        deliberate bare-``raise`` path.
        """
        import subprocess as _subprocess

        from protokit.schema import git as git_mod

        _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1 on main")
        _git("checkout", "-q", "-b", "feature", cwd=git_repo)
        _commit(git_repo, "acme/user.proto", _USER_V2_DROP, msg="v2")

        def _boom(ref: str, path: str, **kwargs: object) -> bytes:
            raise _subprocess.CalledProcessError(
                128,
                ["git", "show", f"{ref}:{path}"],
                output=b"",
                stderr=b"fatal: unable to read tree (deadbeef)",
            )

        monkeypatch.setattr(git_mod, "_git_show", _boom)
        result = _invoke_in_repo(git_repo, [
            subcommand, *extra_args,
            "--proto-file", "acme/user.proto",
            "--type", "acme.User",
        ])
        assert result.exit_code == 2, (
            f"{subcommand}: expected exit 2 (error), got "
            f"{result.exit_code}; exception={result.exception!r}"
        )
        assert "unable to read tree" in result.stderr
