"""``protokit storage`` schema-source flags — mutual exclusivity, --type, --proto, errors."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from click.testing import CliRunner

from protokit.cli import main


def _run(runner: CliRunner, args: list[str]):  # noqa: ANN202
    return runner.invoke(main, args, catch_exceptions=False)


_PROTO = """\
syntax = "proto3";
package demo;
message Order { int32 id = 1; }
"""


def test_no_schema_source_is_exit_2(
    runner: CliRunner, data_file_factory: Callable[..., Path]
) -> None:
    data = data_file_factory([])
    result = _run(runner, ["storage", "count", str(data), "--type", "a.A"])
    assert result.exit_code == 2
    assert "schema source is required" in result.stderr


def test_both_schema_sources_is_exit_2(
    runner: CliRunner, desc_and_cls: tuple[Path, type], data_file_factory: Callable[..., Path]
) -> None:
    desc, _cls = desc_and_cls
    data = data_file_factory([])
    result = _run(
        runner,
        ["storage", "count", str(data), "--desc", str(desc), "--proto", str(desc), "--type", "a.A"],
    )
    assert result.exit_code == 2
    assert "mutually exclusive" in result.stderr


def test_missing_type_is_exit_2(
    runner: CliRunner, desc_and_cls: tuple[Path, type], data_file_factory: Callable[..., Path]
) -> None:
    desc, _cls = desc_and_cls
    data = data_file_factory([])
    result = _run(runner, ["storage", "count", str(data), "--desc", str(desc)])
    assert result.exit_code == 2
    assert "--type" in result.stderr


def test_message_type_alias_works(
    runner: CliRunner, desc_and_cls: tuple[Path, type], data_file_factory: Callable[..., Path]
) -> None:
    desc, cls = desc_and_cls
    data = data_file_factory([cls(x=1).SerializeToString()])
    result = _run(
        runner,
        ["storage", "count", str(data), "--desc", str(desc), "--message-type", "a.A"],
    )
    assert result.exit_code == 0
    assert result.output.strip() == "1"


def test_proto_source_resolves_and_scans(
    runner: CliRunner, tmp_path: Path, data_file_factory: Callable[..., Path]
) -> None:
    from protokit.storage.schema_source import ProtoFileSchema

    proto = tmp_path / "order.proto"
    proto.write_text(_PROTO)
    cls = ProtoFileSchema(proto, "demo.Order").resolve().message_class
    data = data_file_factory([cls(id=7).SerializeToString()])
    result = _run(
        runner,
        ["storage", "scan", str(data), "--proto", str(proto), "--type", "demo.Order"],
    )
    assert result.exit_code == 0
    assert "id: 7" in result.output


def test_unknown_type_is_exit_2(
    runner: CliRunner, desc_and_cls: tuple[Path, type], data_file_factory: Callable[..., Path]
) -> None:
    desc, _cls = desc_and_cls
    data = data_file_factory([])
    result = _run(runner, ["storage", "count", str(data), "--desc", str(desc), "--type", "a.Nope"])
    assert result.exit_code == 2
    assert "Error:" in result.stderr


def test_malformed_descriptor_set_is_exit_2(
    runner: CliRunner, tmp_path: Path, data_file_factory: Callable[..., Path]
) -> None:
    desc = tmp_path / "bad.desc"
    desc.write_bytes(b"\xff\xff not a descriptor set \x00")
    data = data_file_factory([])
    result = _run(runner, ["storage", "count", str(data), "--desc", str(desc), "--type", "a.A"])
    assert result.exit_code == 2
    assert "Error:" in result.stderr


def test_bad_where_is_exit_2(
    runner: CliRunner, desc_and_cls: tuple[Path, type], data_file_factory: Callable[..., Path]
) -> None:
    desc, _cls = desc_and_cls
    data = data_file_factory([])
    result = _run(
        runner,
        ["storage", "count", str(data), "--desc", str(desc), "--type", "a.A", "--where", "x > 5"],
    )
    assert result.exit_code == 2
    assert "Python callable API" in result.stderr
