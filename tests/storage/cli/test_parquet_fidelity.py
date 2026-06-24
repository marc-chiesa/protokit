"""End-to-end ``scan --format parquet --fidelity ...`` CLI tests (U5).

Frames carry an unknown field (#50) absent from the ``a.A`` descriptor the CLI is
given, so the columnar fidelity probe sees unmodeled wire data. Covers the
``--fidelity`` policy surface: ``warn`` (default) prints a stderr count and writes
the file; ``ignore`` is silent; ``error`` fails the conversion (exit 2, no file).

Module-top ``importorskip`` guards the pyarrow import (the no-extra axis skips at
collection); this runs in full in the ``storage-parquet`` CI job.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

pytest.importorskip("ptars")
pytest.importorskip("pyarrow")
import pyarrow.parquet as pq  # noqa: E402 - after importorskip by design
from click.testing import CliRunner  # noqa: E402
from google.protobuf import descriptor_pb2  # noqa: E402

from protokit.cli import main  # noqa: E402
from tests.storage.cli.conftest import cmd, pq_cmd  # noqa: E402

_F = descriptor_pb2.FieldDescriptorProto
# Base{id=7}: field 1 (int64 varint) = 7. The declared extension is never set —
# the structural oracle fires on the DECLARED extension regardless.
_BASE_ID7 = bytes([0x08, 0x07])

# Wire bytes for an unknown field #50 (varint 99): tag (50<<3)|0 = 400 -> 0x90 0x03,
# value 0x63. Appended to a serialized a.A so the record carries data the descriptor
# does not model (the shape of a real vendor extension outside the schema).
_UNKNOWN_TAIL = bytes([0x90, 0x03, 0x63])


def _run(runner: CliRunner, args: list[str]):  # noqa: ANN202
    return runner.invoke(main, args, catch_exceptions=False)


def _no_partial_left(directory: Path) -> bool:
    return not list(directory.glob(".*.partial"))


def _unmodeled(cls: type, x: int) -> bytes:
    return cls(x=x).SerializeToString() + _UNKNOWN_TAIL


def test_warn_default_writes_and_reports_count(
    runner: CliRunner,
    desc_and_cls: tuple[Path, type],
    data_file_factory: Callable[..., Path],
    tmp_path: Path,
) -> None:
    desc, cls = desc_and_cls
    data = data_file_factory([_unmodeled(cls, 1), cls(x=2).SerializeToString()])
    out = tmp_path / "out.parquet"
    result = _run(runner, pq_cmd(data, desc, out))  # default --fidelity warn
    assert result.exit_code == 0, result.stderr
    assert result.stdout == ""  # stdout stays clean for scripting
    assert f"wrote 2 rows to {out}" in result.stderr
    assert "fidelity: 1 record(s) carried" in result.stderr
    # the file is written regardless under warn; the modeled column round-trips
    assert pq.read_table(out).column("x").to_pylist() == [1, 2]


def test_warn_clean_input_no_fidelity_line(
    runner: CliRunner,
    desc_and_cls: tuple[Path, type],
    data_file_factory: Callable[..., Path],
    tmp_path: Path,
) -> None:
    desc, cls = desc_and_cls
    data = data_file_factory([cls(x=n).SerializeToString() for n in (1, 2)])
    out = tmp_path / "out.parquet"
    result = _run(runner, pq_cmd(data, desc, out))
    assert result.exit_code == 0, result.stderr
    assert f"wrote 2 rows to {out}" in result.stderr
    assert "fidelity:" not in result.stderr  # clean scan -> no extra line


def test_ignore_is_silent(
    runner: CliRunner,
    desc_and_cls: tuple[Path, type],
    data_file_factory: Callable[..., Path],
    tmp_path: Path,
) -> None:
    desc, cls = desc_and_cls
    data = data_file_factory([_unmodeled(cls, 1)])
    out = tmp_path / "out.parquet"
    result = _run(runner, pq_cmd(data, desc, out, "--fidelity", "ignore"))
    assert result.exit_code == 0, result.stderr
    assert f"wrote 1 rows to {out}" in result.stderr
    assert "fidelity:" not in result.stderr  # ignore -> no measurement, no line
    assert out.exists()


def test_error_fails_and_writes_nothing(
    runner: CliRunner,
    desc_and_cls: tuple[Path, type],
    data_file_factory: Callable[..., Path],
    tmp_path: Path,
) -> None:
    desc, cls = desc_and_cls
    data = data_file_factory([_unmodeled(cls, 1), cls(x=2).SerializeToString()])
    out = tmp_path / "out.parquet"
    result = _run(runner, pq_cmd(data, desc, out, "--fidelity", "error"))
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "fidelity check failed" in result.stderr
    assert "1 record(s)" in result.stderr  # the count reaches the operator
    assert "byte(s)" in result.stderr
    assert not out.exists()  # all-or-nothing: nothing published
    assert _no_partial_left(tmp_path)  # and no temp left behind


def test_error_clean_input_writes(
    runner: CliRunner,
    desc_and_cls: tuple[Path, type],
    data_file_factory: Callable[..., Path],
    tmp_path: Path,
) -> None:
    desc, cls = desc_and_cls
    data = data_file_factory([cls(x=1).SerializeToString()])
    out = tmp_path / "out.parquet"
    result = _run(runner, pq_cmd(data, desc, out, "--fidelity", "error"))
    assert result.exit_code == 0, result.stderr
    assert out.exists()  # nothing unmodeled -> error mode writes normally


def test_invalid_fidelity_value_rejected(
    runner: CliRunner,
    desc_and_cls: tuple[Path, type],
    data_file_factory: Callable[..., Path],
    tmp_path: Path,
) -> None:
    desc, cls = desc_and_cls
    data = data_file_factory([cls(x=1).SerializeToString()])
    out = tmp_path / "out.parquet"
    result = _run(runner, pq_cmd(data, desc, out, "--fidelity", "bogus"))
    assert result.exit_code == 2  # click usage error
    assert not out.exists()


def test_fidelity_rejected_without_parquet(
    runner: CliRunner,
    desc_and_cls: tuple[Path, type],
    data_file_factory: Callable[..., Path],
) -> None:
    # --fidelity only governs parquet output; passing it on a text format must
    # fail up front, not silently no-op a data-integrity gate.
    desc, cls = desc_and_cls
    data = data_file_factory([cls(x=1).SerializeToString()])
    result = _run(runner, cmd("scan", data, desc, "--fidelity", "error"))
    assert result.exit_code == 2
    assert "only valid with --format parquet" in result.stderr


# --- structural oracle: declared proto2 extensions ptars drops (U5) -----------


def _struct_desc(tmp_path: Path, *, with_extension: bool) -> Path:
    """Write a proto2 ``so.Base { optional int64 id = 1; extensions 100..200; }``
    descriptor set (optionally declaring extension ``ext_val`` #100) to disk."""
    fset = descriptor_pb2.FileDescriptorSet()
    f = fset.file.add()
    f.name, f.package, f.syntax = "so.proto", "so", "proto2"
    m = f.message_type.add()
    m.name = "Base"
    idf = m.field.add()
    idf.name, idf.number, idf.type, idf.label = "id", 1, _F.TYPE_INT64, _F.LABEL_OPTIONAL
    m.extension_range.add(start=100, end=201)
    if with_extension:
        ext = f.extension.add()
        ext.name, ext.number, ext.type = "ext_val", 100, _F.TYPE_INT32
        ext.label, ext.extendee = _F.LABEL_OPTIONAL, ".so.Base"
    desc = tmp_path / "so.desc"
    desc.write_bytes(fset.SerializeToString())
    return desc


def _struct_argv(data: Path, desc: Path, out: Path, *extra: str) -> list[str]:
    return [
        "storage", "scan", str(data), "--desc", str(desc), "--type", "so.Base",
        "--format", "parquet", "-o", str(out), *extra,
    ]


def test_structural_warn_prints_distinct_line(
    runner: CliRunner,
    data_file_factory: Callable[..., Path],
    tmp_path: Path,
) -> None:  # G10
    desc = _struct_desc(tmp_path, with_extension=True)
    data = data_file_factory([_BASE_ID7])
    out = tmp_path / "out.parquet"
    result = _run(runner, _struct_argv(data, desc, out))  # default warn
    assert result.exit_code == 0, result.stderr
    assert result.stdout == ""
    assert f"wrote 1 rows to {out}" in result.stderr
    assert "declared extension(s) dropped" in result.stderr
    assert "so.ext_val" in result.stderr
    assert pq.read_table(out).schema.names == ["id"]


def test_structural_clean_descriptor_no_line(
    runner: CliRunner,
    data_file_factory: Callable[..., Path],
    tmp_path: Path,
) -> None:
    desc = _struct_desc(tmp_path, with_extension=False)
    data = data_file_factory([_BASE_ID7])
    out = tmp_path / "out.parquet"
    result = _run(runner, _struct_argv(data, desc, out))
    assert result.exit_code == 0, result.stderr
    assert "fidelity:" not in result.stderr  # no declared extension -> no line


def test_structural_error_exit2_no_file(
    runner: CliRunner,
    data_file_factory: Callable[..., Path],
    tmp_path: Path,
) -> None:  # AE6
    desc = _struct_desc(tmp_path, with_extension=True)
    data = data_file_factory([_BASE_ID7])
    out = tmp_path / "out.parquet"
    result = _run(runner, _struct_argv(data, desc, out, "--fidelity", "error"))
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "fidelity check failed" in result.stderr
    assert "so.ext_val" in result.stderr
    assert "declared extension(s) dropped" in result.stderr
    assert not out.exists()
    assert _no_partial_left(tmp_path)


def test_structural_and_per_record_two_lines_under_warn(
    runner: CliRunner,
    data_file_factory: Callable[..., Path],
    tmp_path: Path,
) -> None:  # G10 (both signals)
    desc = _struct_desc(tmp_path, with_extension=True)
    # Base{id=7} + an UNDECLARED field #50 -> the per-record probe fires too.
    data = data_file_factory([_BASE_ID7 + _UNKNOWN_TAIL])
    out = tmp_path / "out.parquet"
    result = _run(runner, _struct_argv(data, desc, out))
    assert result.exit_code == 0, result.stderr
    assert "record(s) carried" in result.stderr  # per-record line
    assert "declared extension(s) dropped" in result.stderr  # structural line
    assert result.stderr.count("fidelity:") == 2  # two distinct lines
