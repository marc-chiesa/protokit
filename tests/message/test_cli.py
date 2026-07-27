"""CLI integration tests for protokit diff."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

from protokit.message.cli import main


# ---------------------------------------------------------------------------
# Test helpers: create descriptor sets and binary message files on disk
# ---------------------------------------------------------------------------

T = descriptor_pb2.FieldDescriptorProto


def _make_descriptor_set(
    package: str,
    msg_name: str,
    fields: dict[str, tuple[int, int]],
    *,
    syntax: str = "proto3",
) -> bytes:
    """Build a FileDescriptorSet with a single message type."""
    file_proto = descriptor_pb2.FileDescriptorProto(
        name=f"{msg_name.lower()}.proto",
        package=package,
        syntax=syntax,
    )
    msg_proto = file_proto.message_type.add()
    msg_proto.name = msg_name
    for fname, (ftype, fnum) in fields.items():
        fp = msg_proto.field.add()
        fp.name = fname
        fp.type = ftype
        fp.number = fnum
        fp.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL

    fds = descriptor_pb2.FileDescriptorSet()
    fds.file.append(file_proto)
    return fds.SerializeToString()


def _build_message(desc_set_bytes: bytes, full_name: str, **kwargs: Any) -> bytes:
    """Parse a descriptor set, build a message, and serialize to binary."""
    fds = descriptor_pb2.FileDescriptorSet()
    fds.ParseFromString(desc_set_bytes)
    pool = descriptor_pool.DescriptorPool()
    for fd in fds.file:
        pool.Add(fd)
    desc = pool.FindMessageTypeByName(full_name)
    cls = message_factory.GetMessageClass(desc)
    return cls(**kwargs).SerializeToString()


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def simple_setup(tmp_path: Path) -> dict[str, Path]:
    """Create a descriptor set and two binary message files for same-schema mode."""
    desc_bytes = _make_descriptor_set("test", "Msg", {
        "name": (T.TYPE_STRING, 1),
        "value": (T.TYPE_INT32, 2),
    })
    desc_file = tmp_path / "test.descriptor_set"
    desc_file.write_bytes(desc_bytes)

    left = tmp_path / "left.pb"
    left.write_bytes(_build_message(desc_bytes, "test.Msg", name="Alice", value=42))

    right_same = tmp_path / "right_same.pb"
    right_same.write_bytes(_build_message(desc_bytes, "test.Msg", name="Alice", value=42))

    right_diff = tmp_path / "right_diff.pb"
    right_diff.write_bytes(_build_message(desc_bytes, "test.Msg", name="Bob", value=99))

    return {
        "desc": desc_file,
        "left": left,
        "right_same": right_same,
        "right_diff": right_diff,
    }


# ---------------------------------------------------------------------------
# Flag group validation
# ---------------------------------------------------------------------------


class TestFlagValidation:
    def test_no_descriptor_source(self, runner: CliRunner, tmp_path: Path) -> None:
        f1 = tmp_path / "a.pb"
        f2 = tmp_path / "b.pb"
        f1.write_bytes(b"")
        f2.write_bytes(b"")
        result = runner.invoke(main, [str(f1), str(f2)])
        assert result.exit_code == 2
        assert "No descriptor source" in result.output

    def test_desc_without_message_type(self, runner: CliRunner, simple_setup: dict[str, Path]) -> None:
        result = runner.invoke(main, [
            str(simple_setup["left"]),
            str(simple_setup["right_same"]),
            "--desc", str(simple_setup["desc"]),
        ])
        assert result.exit_code == 2
        assert "--message-type" in result.output

    def test_partial_cross_schema(self, runner: CliRunner, simple_setup: dict[str, Path]) -> None:
        result = runner.invoke(main, [
            str(simple_setup["left"]),
            str(simple_setup["right_same"]),
            "--left-desc", str(simple_setup["desc"]),
        ])
        assert result.exit_code == 2
        assert "Missing" in result.output

    def test_conflicting_groups(self, runner: CliRunner, simple_setup: dict[str, Path]) -> None:
        result = runner.invoke(main, [
            str(simple_setup["left"]),
            str(simple_setup["right_same"]),
            "--desc", str(simple_setup["desc"]),
            "--left-desc", str(simple_setup["desc"]),
            "--message-type", "test.Msg",
        ])
        assert result.exit_code == 2
        assert "Conflicting" in result.output

    def test_proto_path_without_proto(
        self, runner: CliRunner, simple_setup: dict[str, Path], tmp_path: Path
    ) -> None:
        """--proto-path is a group-C flag; silently discarding it in
        group A would let a user believe their import path took effect.
        """
        result = runner.invoke(main, [
            str(simple_setup["left"]),
            str(simple_setup["right_same"]),
            "--desc", str(simple_setup["desc"]),
            "--message-type", "test.Msg",
            "--proto-path", str(tmp_path),
        ])
        assert result.exit_code == 2
        assert "--proto-path" in result.output

    def test_proto_path_with_no_descriptor_source(
        self, runner: CliRunner, simple_setup: dict[str, Path], tmp_path: Path
    ) -> None:
        result = runner.invoke(main, [
            str(simple_setup["left"]),
            str(simple_setup["right_same"]),
            "--proto-path", str(tmp_path),
        ])
        assert result.exit_code == 2
        assert "--proto-path" in result.output


# ---------------------------------------------------------------------------
# Same-schema mode (Group A)
# ---------------------------------------------------------------------------


class TestSameSchemaMode:
    def test_equal_messages_exit_0(self, runner: CliRunner, simple_setup: dict[str, Path]) -> None:
        result = runner.invoke(main, [
            str(simple_setup["left"]),
            str(simple_setup["right_same"]),
            "--desc", str(simple_setup["desc"]),
            "--message-type", "test.Msg",
        ])
        assert result.exit_code == 0
        assert "equal" in result.output.lower()

    def test_different_messages_exit_1(self, runner: CliRunner, simple_setup: dict[str, Path]) -> None:
        result = runner.invoke(main, [
            str(simple_setup["left"]),
            str(simple_setup["right_diff"]),
            "--desc", str(simple_setup["desc"]),
            "--message-type", "test.Msg",
        ])
        assert result.exit_code == 1
        assert "difference" in result.output.lower()

    def test_bad_message_type(self, runner: CliRunner, simple_setup: dict[str, Path]) -> None:
        result = runner.invoke(main, [
            str(simple_setup["left"]),
            str(simple_setup["right_same"]),
            "--desc", str(simple_setup["desc"]),
            "--message-type", "nonexistent.Msg",
        ])
        assert result.exit_code == 2

    def test_malformed_descriptor_set_exit_2_not_traceback(
        self, runner: CliRunner, simple_setup: dict[str, Path], tmp_path: Path,
    ) -> None:
        # A descriptor set carrying two files with the same name (e.g. two
        # concatenated sets) must fail loudly with exit 2, not silently drop a
        # definition or surface a traceback. Exercises message/cli._safe_load_pool.
        fds = descriptor_pb2.FileDescriptorSet()
        for _ in range(2):
            fp = fds.file.add()
            fp.name = "dup.proto"
            fp.package = "dup"
            fp.syntax = "proto3"
            fp.message_type.add().name = "M"
        dup = tmp_path / "dup.descriptor_set"
        dup.write_bytes(fds.SerializeToString())
        result = runner.invoke(main, [
            str(simple_setup["left"]),
            str(simple_setup["right_same"]),
            "--desc", str(dup),
            "--message-type", "dup.M",
        ])
        assert result.exit_code == 2  # clean exit-2, not an uncaught traceback


# ---------------------------------------------------------------------------
# Input-file I/O errors
# ---------------------------------------------------------------------------


class TestInputFileErrors:
    """Unreadable message inputs must exit 2, never 1 ("messages differ")."""

    @pytest.mark.parametrize("position", [0, 1])
    def test_directory_argument_exits_2(
        self, runner: CliRunner, simple_setup: dict[str, Path], tmp_path: Path, position: int,
    ) -> None:
        # ``exists=True`` alone lets a directory through, and the unguarded
        # read then raised IsADirectoryError as a traceback under Click's
        # standalone mode — which exits 1, the code reserved for "different".
        # A CI gate keying on the exit code would record an unreadable input
        # as a real diff.
        adir = tmp_path / "adir"
        adir.mkdir()
        args = [str(simple_setup["left"]), str(simple_setup["right_same"])]
        args[position] = str(adir)
        result = runner.invoke(main, [
            *args,
            "--desc", str(simple_setup["desc"]),
            "--message-type", "test.Msg",
        ])
        assert result.exit_code == 2

    def test_read_failure_after_click_check_exits_2(
        self,
        runner: CliRunner,
        simple_setup: dict[str, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Click's up-front existence/readability check is a TOCTOU snapshot:
        # the file can be deleted or chmod'ed between the check and the read.
        # The read itself must therefore route to exit 2 as well.
        real_read_bytes = Path.read_bytes
        target = simple_setup["left"]

        def fail_for_left(self: Path) -> bytes:
            if self == target:
                raise PermissionError(13, "Permission denied")
            return real_read_bytes(self)

        monkeypatch.setattr(Path, "read_bytes", fail_for_left)
        result = runner.invoke(main, [
            str(simple_setup["left"]),
            str(simple_setup["right_same"]),
            "--desc", str(simple_setup["desc"]),
            "--message-type", "test.Msg",
        ])
        assert result.exit_code == 2
        assert "cannot read" in result.output.lower()


# ---------------------------------------------------------------------------
# Output formats
# ---------------------------------------------------------------------------


class TestOutputFormats:
    def test_json_output_equal(self, runner: CliRunner, simple_setup: dict[str, Path]) -> None:
        result = runner.invoke(main, [
            str(simple_setup["left"]),
            str(simple_setup["right_same"]),
            "--desc", str(simple_setup["desc"]),
            "--message-type", "test.Msg",
            "--format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["equal"] is True
        assert data["differences"] == []

    def test_json_output_different(self, runner: CliRunner, simple_setup: dict[str, Path]) -> None:
        result = runner.invoke(main, [
            str(simple_setup["left"]),
            str(simple_setup["right_diff"]),
            "--desc", str(simple_setup["desc"]),
            "--message-type", "test.Msg",
            "--format", "json",
        ])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["equal"] is False
        assert len(data["differences"]) == 2
        paths = {d["path"] for d in data["differences"]}
        assert paths == {"name", "value"}

    def test_quiet_exit_0(self, runner: CliRunner, simple_setup: dict[str, Path]) -> None:
        result = runner.invoke(main, [
            str(simple_setup["left"]),
            str(simple_setup["right_same"]),
            "--desc", str(simple_setup["desc"]),
            "--message-type", "test.Msg",
            "--quiet",
        ])
        assert result.exit_code == 0
        assert result.output == ""

    def test_quiet_exit_1(self, runner: CliRunner, simple_setup: dict[str, Path]) -> None:
        result = runner.invoke(main, [
            str(simple_setup["left"]),
            str(simple_setup["right_diff"]),
            "--desc", str(simple_setup["desc"]),
            "--message-type", "test.Msg",
            "--quiet",
        ])
        assert result.exit_code == 1
        assert result.output == ""

    def test_human_output_shows_paths(self, runner: CliRunner, simple_setup: dict[str, Path]) -> None:
        result = runner.invoke(main, [
            str(simple_setup["left"]),
            str(simple_setup["right_diff"]),
            "--desc", str(simple_setup["desc"]),
            "--message-type", "test.Msg",
        ], color=False)
        assert result.exit_code == 1
        assert "name" in result.output
        assert "value" in result.output


# ---------------------------------------------------------------------------
# Input formats
# ---------------------------------------------------------------------------


class TestInputFormats:
    def test_text_format_input(self, runner: CliRunner, tmp_path: Path) -> None:
        desc_bytes = _make_descriptor_set("test", "Msg", {
            "name": (T.TYPE_STRING, 1),
        })
        desc_file = tmp_path / "test.descriptor_set"
        desc_file.write_bytes(desc_bytes)

        left = tmp_path / "left.textproto"
        left.write_text('name: "Alice"')
        right = tmp_path / "right.textproto"
        right.write_text('name: "Bob"')

        result = runner.invoke(main, [
            str(left), str(right),
            "--desc", str(desc_file),
            "--message-type", "test.Msg",
            "--text-format",
            "--format", "json",
        ])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["differences"][0]["left_value"] == "Alice"
        assert data["differences"][0]["old_value"] == "Alice"  # deprecated alias key

    def test_json_input(self, runner: CliRunner, tmp_path: Path) -> None:
        desc_bytes = _make_descriptor_set("test", "Msg", {
            "name": (T.TYPE_STRING, 1),
            "value": (T.TYPE_INT32, 2),
        })
        desc_file = tmp_path / "test.descriptor_set"
        desc_file.write_bytes(desc_bytes)

        left = tmp_path / "left.json"
        left.write_text('{"name": "Alice", "value": 1}')
        right = tmp_path / "right.json"
        right.write_text('{"name": "Alice", "value": 2}')

        result = runner.invoke(main, [
            str(left), str(right),
            "--desc", str(desc_file),
            "--message-type", "test.Msg",
            "--json",
            "--format", "json",
        ])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert len(data["differences"]) == 1
        assert data["differences"][0]["path"] == "value"


# ---------------------------------------------------------------------------
# Filter and diff options
# ---------------------------------------------------------------------------


class TestDiffOptions:
    def test_filter_path(self, runner: CliRunner, simple_setup: dict[str, Path]) -> None:
        result = runner.invoke(main, [
            str(simple_setup["left"]),
            str(simple_setup["right_diff"]),
            "--desc", str(simple_setup["desc"]),
            "--message-type", "test.Msg",
            "--filter", "name",
            "--format", "json",
        ])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert len(data["differences"]) == 1
        assert data["differences"][0]["path"] == "name"

    def test_negative_max_depth_exits_2_not_false_equal(
        self, runner: CliRunner, simple_setup: dict[str, Path],
    ) -> None:
        # A negative depth truncates the ROOT work item (depth 0), so every
        # difference vanishes and the CLI used to report two differing messages
        # as "equal" with exit 0 — the exit-code contract (0=equal, 1=different,
        # 2=error) inverted by a typo'd or templated flag value. Nonsense input
        # is an error, not equality.
        result = runner.invoke(main, [
            str(simple_setup["left"]),
            str(simple_setup["right_diff"]),
            "--desc", str(simple_setup["desc"]),
            "--message-type", "test.Msg",
            "--max-depth", "-1",
        ])
        assert result.exit_code == 2
        assert "equal" not in result.output.lower()

    def test_max_depth_zero_still_accepted(
        self, runner: CliRunner, simple_setup: dict[str, Path],
    ) -> None:
        # Guards the negative-value rejection from over-correcting: 0 is a
        # meaningful depth (root fields compared, nested subtrees truncated).
        result = runner.invoke(main, [
            str(simple_setup["left"]),
            str(simple_setup["right_diff"]),
            "--desc", str(simple_setup["desc"]),
            "--message-type", "test.Msg",
            "--max-depth", "0",
            "--format", "json",
        ])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert {d["path"] for d in data["differences"]} == {"name", "value"}

    def test_ignore_field(self, runner: CliRunner, simple_setup: dict[str, Path]) -> None:
        result = runner.invoke(main, [
            str(simple_setup["left"]),
            str(simple_setup["right_diff"]),
            "--desc", str(simple_setup["desc"]),
            "--message-type", "test.Msg",
            "--ignore", "name",
            "--ignore", "value",
            "--format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["equal"] is True


# ---------------------------------------------------------------------------
# Cross-schema mode (Group B)
# ---------------------------------------------------------------------------


class TestCrossSchemaMode:
    def test_cross_schema_same_values(self, runner: CliRunner, tmp_path: Path) -> None:
        left_desc_bytes = _make_descriptor_set("v1", "Msg", {
            "name": (T.TYPE_STRING, 1),
        })
        right_desc_bytes = _make_descriptor_set("v2", "Msg", {
            "name": (T.TYPE_STRING, 1),
        })

        left_desc_file = tmp_path / "left.descriptor_set"
        left_desc_file.write_bytes(left_desc_bytes)
        right_desc_file = tmp_path / "right.descriptor_set"
        right_desc_file.write_bytes(right_desc_bytes)

        left = tmp_path / "left.pb"
        left.write_bytes(_build_message(left_desc_bytes, "v1.Msg", name="Alice"))
        right = tmp_path / "right.pb"
        right.write_bytes(_build_message(right_desc_bytes, "v2.Msg", name="Alice"))

        result = runner.invoke(main, [
            str(left), str(right),
            "--left-desc", str(left_desc_file),
            "--right-desc", str(right_desc_file),
            "--left-type", "v1.Msg",
            "--right-type", "v2.Msg",
            "--format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["equal"] is True

    def test_cross_schema_field_number_change(self, runner: CliRunner, tmp_path: Path) -> None:
        left_desc_bytes = _make_descriptor_set("v1", "Msg", {
            "name": (T.TYPE_STRING, 1),
        })
        right_desc_bytes = _make_descriptor_set("v2", "Msg", {
            "name": (T.TYPE_STRING, 2),  # field number changed
        })

        left_desc_file = tmp_path / "left.descriptor_set"
        left_desc_file.write_bytes(left_desc_bytes)
        right_desc_file = tmp_path / "right.descriptor_set"
        right_desc_file.write_bytes(right_desc_bytes)

        left = tmp_path / "left.pb"
        left.write_bytes(_build_message(left_desc_bytes, "v1.Msg", name="Alice"))
        right = tmp_path / "right.pb"
        right.write_bytes(_build_message(right_desc_bytes, "v2.Msg", name="Alice"))

        result = runner.invoke(main, [
            str(left), str(right),
            "--left-desc", str(left_desc_file),
            "--right-desc", str(right_desc_file),
            "--left-type", "v1.Msg",
            "--right-type", "v2.Msg",
            "--format", "json",
        ])
        assert result.exit_code == 1
        data = json.loads(result.output)
        fn_changes = [d for d in data["differences"] if d["change_type"] == "FIELD_NUMBER_CHANGED"]
        assert len(fn_changes) == 1
