"""End-to-end CLI tests for the formatter wire-up.

Covers ``--format`` validation, ``--formatter-module`` pack
loading, the widened ``--quiet`` mutex, formatter exception
fail-fast, and the stdout-write guard.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

from protokit.formatters import clear_user_formatters
from protokit.message.cli import main as diff_main
from protokit.schema.cli import main as compat_main


@pytest.fixture(autouse=True)
def _isolate_formatter_registry() -> None:
    """Wipe user formatters around every test.

    Built-ins survive (they're in the reservation set);
    user-supplied packs from ``--formatter-module`` get cleared
    so one test's load doesn't leak into another's lookup.
    """
    clear_user_formatters()
    yield
    clear_user_formatters()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_msg_class(pool: descriptor_pool.DescriptorPool) -> type:
    fdp = descriptor_pb2.FileDescriptorProto()
    fdp.name = "cli_test.proto"
    fdp.syntax = "proto3"
    msg = fdp.message_type.add()
    msg.name = "M"
    fld = msg.field.add()
    fld.name = "name"
    fld.number = 1
    fld.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING
    fld.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    pool.Add(fdp)
    return message_factory.GetMessageClass(pool.FindMessageTypeByName("M"))


def _write_descriptor_set(path: Path, type_name: str, value: str = "x") -> None:
    """Build a single-message FileDescriptorSet, serialize, and write to disk."""
    fdp = descriptor_pb2.FileDescriptorProto()
    fdp.name = f"{path.stem}.proto"
    fdp.syntax = "proto3"
    msg = fdp.message_type.add()
    msg.name = type_name
    fld = msg.field.add()
    fld.name = "name"
    fld.number = 1
    fld.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING
    fld.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    fds = descriptor_pb2.FileDescriptorSet()
    fds.file.append(fdp)
    path.write_bytes(fds.SerializeToString())


def _binary_message(pool: descriptor_pool.DescriptorPool, name: str) -> bytes:
    cls = _build_msg_class(pool)
    return cls(name=name).SerializeToString()


# ---------------------------------------------------------------------------
# protokit diff — --format and --formatter-module
# ---------------------------------------------------------------------------


class TestDiffFormatFlag:
    def test_default_format_is_human(self, tmp_path: Path) -> None:
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        left = tmp_path / "a.pb"
        right = tmp_path / "b.pb"
        left.write_bytes(cls(name="A").SerializeToString())
        right.write_bytes(cls(name="A").SerializeToString())
        desc = tmp_path / "schema.descriptor_set"
        _write_descriptor_set(desc, "M")
        result = CliRunner().invoke(diff_main, [
            str(left), str(right),
            "--desc", str(desc), "--message-type", "M",
        ])
        assert result.exit_code == 0
        assert "Messages are equal" in result.output

    def test_unknown_format_exits_2(self, tmp_path: Path) -> None:
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        left = tmp_path / "a.pb"
        right = tmp_path / "b.pb"
        left.write_bytes(cls(name="A").SerializeToString())
        right.write_bytes(cls(name="A").SerializeToString())
        desc = tmp_path / "schema.descriptor_set"
        _write_descriptor_set(desc, "M")
        result = CliRunner().invoke(diff_main, [
            str(left), str(right),
            "--desc", str(desc), "--message-type", "M",
            "--format", "nonsense",
        ])
        assert result.exit_code == 2
        assert "unknown formatter 'nonsense'" in result.output
        # Error names the available formatters for DIFF.
        assert "human" in result.output
        assert "json" in result.output
        assert "junit" in result.output

    def test_case_insensitive_format(self, tmp_path: Path) -> None:
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        left = tmp_path / "a.pb"
        right = tmp_path / "b.pb"
        left.write_bytes(cls(name="A").SerializeToString())
        right.write_bytes(cls(name="B").SerializeToString())
        desc = tmp_path / "schema.descriptor_set"
        _write_descriptor_set(desc, "M")
        result = CliRunner().invoke(diff_main, [
            str(left), str(right),
            "--desc", str(desc), "--message-type", "M",
            "--format", "JSON",  # uppercase
        ])
        assert result.exit_code == 1
        assert '"equal": false' in result.output

    def test_quiet_plus_junit_rejected(self, tmp_path: Path) -> None:
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        left = tmp_path / "a.pb"
        right = tmp_path / "b.pb"
        left.write_bytes(cls(name="A").SerializeToString())
        right.write_bytes(cls(name="A").SerializeToString())
        desc = tmp_path / "schema.descriptor_set"
        _write_descriptor_set(desc, "M")
        result = CliRunner().invoke(diff_main, [
            str(left), str(right),
            "--desc", str(desc), "--message-type", "M",
            "--quiet", "--format", "junit",
        ])
        assert result.exit_code == 2
        assert "--quiet" in result.output
        assert "junit" in result.output


# ---------------------------------------------------------------------------
# Formatter pack loading
# ---------------------------------------------------------------------------


_PACK_COUNTER = [0]


def _write_pack(tmp_path: Path, body: str) -> str:
    """Write a small formatter-pack module under ``tmp_path`` and return its dotted name.

    Each call creates a fresh subdirectory and uses a unique
    module name so sys.modules caching doesn't conflate test
    runs. importlib's caches are invalidated so the new file
    is discoverable on the path. The test's autouse cleanup
    wipes the user-registered formatters afterwards; the on-
    disk module stays under ``tmp_path`` and is cleaned up by
    pytest.
    """
    import importlib
    _PACK_COUNTER[0] += 1
    pack_dir = tmp_path / f"pack_dir_{_PACK_COUNTER[0]}"
    pack_dir.mkdir()
    name = f"protokit_test_pack_{_PACK_COUNTER[0]}"
    (pack_dir / f"{name}.py").write_text(body)
    sys.path.insert(0, str(pack_dir))
    importlib.invalidate_caches()
    # Drop any stale cache entry from a prior test run.
    sys.modules.pop(name, None)
    return name


class TestFormatterModule:
    def test_loads_user_pack(self, tmp_path: Path) -> None:
        pack = _write_pack(tmp_path, textwrap.dedent("""
            from protokit.formatters import FormatterKind
            def my_format(report, ctx):
                return "USER-FORMATTER " + str(report.has_changes())
            FORMATTERS = [("my-format", my_format, FormatterKind.DIFF)]
        """))
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        left = tmp_path / "a.pb"
        right = tmp_path / "b.pb"
        left.write_bytes(cls(name="A").SerializeToString())
        right.write_bytes(cls(name="A").SerializeToString())
        desc = tmp_path / "schema.descriptor_set"
        _write_descriptor_set(desc, "M")
        result = CliRunner().invoke(diff_main, [
            str(left), str(right),
            "--desc", str(desc), "--message-type", "M",
            "--formatter-module", pack,
            "--format", "my-format",
        ])
        assert result.exit_code == 0
        assert "USER-FORMATTER False" in result.output

    def test_pack_cannot_shadow_built_in(self, tmp_path: Path) -> None:
        pack = _write_pack(tmp_path, textwrap.dedent("""
            from protokit.formatters import FormatterKind
            def fake(report, ctx):
                return "fake"
            FORMATTERS = [("junit", fake, FormatterKind.COMPAT)]
        """))
        old = tmp_path / "old.descriptor_set"
        new = tmp_path / "new.descriptor_set"
        _write_descriptor_set(old, "M")
        _write_descriptor_set(new, "M")
        result = CliRunner().invoke(compat_main, [
            "check", str(old), str(new), "--type", "M",
            "--formatter-module", pack,
        ])
        assert result.exit_code == 2
        assert "built-in" in result.output
        assert "junit" in result.output

    def test_pack_partial_load_rolls_back(self, tmp_path: Path) -> None:
        pack = _write_pack(tmp_path, textwrap.dedent("""
            from protokit.formatters import FormatterKind
            def good(report, ctx):
                return "good"
            # Last entry is malformed (2-tuple instead of 3-tuple).
            FORMATTERS = [
                ("good", good, FormatterKind.DIFF),
                ("bad-entry", good),
            ]
        """))
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        left = tmp_path / "a.pb"
        right = tmp_path / "b.pb"
        left.write_bytes(cls(name="A").SerializeToString())
        right.write_bytes(cls(name="A").SerializeToString())
        desc = tmp_path / "schema.descriptor_set"
        _write_descriptor_set(desc, "M")
        result = CliRunner().invoke(diff_main, [
            str(left), str(right),
            "--desc", str(desc), "--message-type", "M",
            "--formatter-module", pack,
        ])
        assert result.exit_code == 2
        assert "failed to load formatter pack" in result.output
        # Verify the "good" entry didn't land — try to use it
        # in a fresh invocation (no --formatter-module this time).
        result2 = CliRunner().invoke(diff_main, [
            str(left), str(right),
            "--desc", str(desc), "--message-type", "M",
            "--format", "good",
        ])
        assert result2.exit_code == 2
        assert "unknown formatter 'good'" in result2.output

    def test_missing_module_exits_2(self, tmp_path: Path) -> None:
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        left = tmp_path / "a.pb"
        right = tmp_path / "b.pb"
        left.write_bytes(cls(name="A").SerializeToString())
        right.write_bytes(cls(name="A").SerializeToString())
        desc = tmp_path / "schema.descriptor_set"
        _write_descriptor_set(desc, "M")
        result = CliRunner().invoke(diff_main, [
            str(left), str(right),
            "--desc", str(desc), "--message-type", "M",
            "--formatter-module", "no.such.module",
        ])
        assert result.exit_code == 2
        assert "failed to import formatter pack" in result.output


# ---------------------------------------------------------------------------
# Formatter exception & stdout-write guard
# ---------------------------------------------------------------------------


class TestFormatterFailFast:
    def test_formatter_exception_exits_2(self, tmp_path: Path) -> None:
        pack = _write_pack(tmp_path, textwrap.dedent("""
            from protokit.formatters import FormatterKind
            def crashy(report, ctx):
                raise RuntimeError("intentional crash")
            FORMATTERS = [("crashy", crashy, FormatterKind.DIFF)]
        """))
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        left = tmp_path / "a.pb"
        right = tmp_path / "b.pb"
        left.write_bytes(cls(name="A").SerializeToString())
        right.write_bytes(cls(name="B").SerializeToString())
        desc = tmp_path / "schema.descriptor_set"
        _write_descriptor_set(desc, "M")
        result = CliRunner().invoke(diff_main, [
            str(left), str(right),
            "--desc", str(desc), "--message-type", "M",
            "--formatter-module", pack,
            "--format", "crashy",
        ])
        assert result.exit_code == 2
        assert "formatter 'crashy' raised RuntimeError" in result.output
        assert "intentional crash" in result.output

    def test_stdout_write_guard(self, tmp_path: Path) -> None:
        pack = _write_pack(tmp_path, textwrap.dedent("""
            import sys
            from protokit.formatters import FormatterKind
            def leaky(report, ctx):
                sys.stdout.write("LEAKED STDOUT BYTES")
                return "returned-value"
            FORMATTERS = [("leaky", leaky, FormatterKind.DIFF)]
        """))
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        left = tmp_path / "a.pb"
        right = tmp_path / "b.pb"
        left.write_bytes(cls(name="A").SerializeToString())
        right.write_bytes(cls(name="A").SerializeToString())
        desc = tmp_path / "schema.descriptor_set"
        _write_descriptor_set(desc, "M")
        result = CliRunner().invoke(diff_main, [
            str(left), str(right),
            "--desc", str(desc), "--message-type", "M",
            "--formatter-module", pack,
            "--format", "leaky",
        ])
        assert result.exit_code == 2
        assert "wrote to stdout directly" in result.output


# ---------------------------------------------------------------------------
# protokit compat — formatter dispatch on every subcommand
# ---------------------------------------------------------------------------


class TestCompatFormatDispatch:
    def test_check_unknown_format(self, tmp_path: Path) -> None:
        old = tmp_path / "old.descriptor_set"
        new = tmp_path / "new.descriptor_set"
        _write_descriptor_set(old, "M")
        _write_descriptor_set(new, "M")
        result = CliRunner().invoke(compat_main, [
            "check", str(old), str(new), "--type", "M",
            "--format", "nonsense",
        ])
        assert result.exit_code == 2
        assert "unknown formatter 'nonsense'" in result.output
        assert "COMPAT" in result.output  # kind is in error
        assert "junit" in result.output
        assert "sarif" in result.output

    def test_check_junit_succeeds(self, tmp_path: Path) -> None:
        old = tmp_path / "old.descriptor_set"
        new = tmp_path / "new.descriptor_set"
        _write_descriptor_set(old, "M")
        _write_descriptor_set(new, "M")
        result = CliRunner().invoke(compat_main, [
            "check", str(old), str(new), "--type", "M",
            "--format", "junit",
        ])
        assert result.exit_code == 0
        assert '<?xml' in result.output
        assert '<testsuite' in result.output

    def test_check_sarif_succeeds(self, tmp_path: Path) -> None:
        old = tmp_path / "old.descriptor_set"
        new = tmp_path / "new.descriptor_set"
        _write_descriptor_set(old, "M")
        _write_descriptor_set(new, "M")
        result = CliRunner().invoke(compat_main, [
            "check", str(old), str(new), "--type", "M",
            "--format", "sarif",
        ])
        assert result.exit_code == 0
        assert '"version": "2.1.0"' in result.output
        assert '"protokit"' in result.output

    def test_diff_sarif_unknown_for_diff_kind(self, tmp_path: Path) -> None:
        # SARIF intentionally not registered for DIFF — error
        # message reflects that.
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        left = tmp_path / "a.pb"
        right = tmp_path / "b.pb"
        left.write_bytes(cls(name="A").SerializeToString())
        right.write_bytes(cls(name="A").SerializeToString())
        desc = tmp_path / "schema.descriptor_set"
        _write_descriptor_set(desc, "M")
        result = CliRunner().invoke(diff_main, [
            str(left), str(right),
            "--desc", str(desc), "--message-type", "M",
            "--format", "sarif",
        ])
        assert result.exit_code == 2
        assert "unknown formatter 'sarif'" in result.output
        assert "DIFF" in result.output
