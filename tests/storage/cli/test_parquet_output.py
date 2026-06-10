"""End-to-end ``scan --format parquet`` tests: real write + pyarrow read-back.

Module-top ``importorskip`` (NOT ``pytestmark``) guards the pyarrow import so
the no-extra CI axis skips at collection instead of erroring; the rejection
surface that must run extra-absent lives in ``test_parquet_guards.py``. This
module runs in full in the ``storage-parquet`` CI job.

The corrupt-input fixture places a good record AFTER the fault (per the
generator-source framing-fault learning: a fault-at-end fixture never exposes
the lost tail).
"""

from __future__ import annotations

import stat
from collections.abc import Callable
from pathlib import Path

import pytest

pytest.importorskip("ptars")
pa = pytest.importorskip("pyarrow")
import pyarrow.parquet as pq  # noqa: E402 - after importorskip by design
from click.testing import CliRunner  # noqa: E402
from google.protobuf import descriptor_pb2  # noqa: E402

from protokit.cli import main  # noqa: E402
from protokit.storage.schema_source import FileDescriptorSetSchema  # noqa: E402
from tests.storage.cli.conftest import cmd  # noqa: E402

F = descriptor_pb2.FieldDescriptorProto

# A framing-valid frame whose 1-byte body is a truncated a.A{int32 x=1}: a
# DECODE fault, recovered past under the sink's collect mode — so the scan
# provably continues to the record after it, and the file is still withheld.
BAD_PAYLOAD = b"\x08"


def _run(runner: CliRunner, args: list[str], env: dict[str, str] | None = None):  # noqa: ANN202
    return runner.invoke(main, args, env=env, catch_exceptions=False)


def _no_partial_left(directory: Path) -> bool:
    return not list(directory.glob(".*.partial"))


class TestHappyPath:
    def test_f1_writes_typed_parquet(
        self,
        runner: CliRunner,
        desc_and_cls: tuple[Path, type],
        data_file_factory: Callable[..., Path],
        tmp_path: Path,
    ) -> None:
        desc, cls = desc_and_cls
        data = data_file_factory([cls(x=n).SerializeToString() for n in (1, 2, 3)])
        out = tmp_path / "out.parquet"
        result = _run(runner, cmd("scan", data, desc, "--format", "parquet", "-o", str(out)))
        assert result.exit_code == 0, result.stderr
        # stdout stays clean for scripting; the summary goes to stderr (R19).
        assert result.stdout == ""
        assert f"wrote 3 rows to {out}" in result.stderr
        table = pq.read_table(out)
        assert table.num_rows == 3
        assert table.column("x").to_pylist() == [1, 2, 3]
        assert pa.types.is_integer(table.schema.field("x").type)

    def test_r16_pre_existing_output_replaced_on_success(
        self,
        runner: CliRunner,
        desc_and_cls: tuple[Path, type],
        data_file_factory: Callable[..., Path],
        tmp_path: Path,
    ) -> None:
        desc, cls = desc_and_cls
        data = data_file_factory([cls(x=7).SerializeToString()])
        out = tmp_path / "out.parquet"
        out.write_bytes(b"stale previous output")
        result = _run(runner, cmd("scan", data, desc, "--format", "parquet", "-o", str(out)))
        assert result.exit_code == 0, result.stderr
        assert pq.read_table(out).column("x").to_pylist() == [7]

    def test_r17_file_mode_honors_umask(
        self,
        runner: CliRunner,
        desc_and_cls: tuple[Path, type],
        data_file_factory: Callable[..., Path],
        tmp_path: Path,
    ) -> None:
        # mkstemp creates 0600; the publish step must restore the mode a plain
        # open() would have produced, or downstream readers get locked out.
        desc, cls = desc_and_cls
        data = data_file_factory([cls(x=1).SerializeToString()])
        out = tmp_path / "out.parquet"
        result = _run(runner, cmd("scan", data, desc, "--format", "parquet", "-o", str(out)))
        assert result.exit_code == 0, result.stderr
        sibling = tmp_path / "normally-created.txt"
        sibling.write_text("x")
        assert stat.S_IMODE(out.stat().st_mode) == stat.S_IMODE(sibling.stat().st_mode)


class TestEmptyAndWhere:
    def test_ae5_empty_input_writes_zero_row_full_schema(
        self,
        runner: CliRunner,
        desc_and_cls: tuple[Path, type],
        data_file_factory: Callable[..., Path],
        tmp_path: Path,
    ) -> None:
        desc, _cls = desc_and_cls
        data = data_file_factory([])
        out = tmp_path / "out.parquet"
        result = _run(runner, cmd("scan", data, desc, "--format", "parquet", "-o", str(out)))
        assert result.exit_code == 0, result.stderr
        assert f"wrote 0 rows to {out}" in result.stderr
        table = pq.read_table(out)
        assert table.num_rows == 0
        # Schema is descriptor-derived, not record-inferred: present even with
        # zero rows.
        assert table.schema.field("x") is not None

    def test_ae5_where_matching_nothing_writes_zero_row(
        self,
        runner: CliRunner,
        desc_and_cls: tuple[Path, type],
        data_file_factory: Callable[..., Path],
        tmp_path: Path,
    ) -> None:
        desc, cls = desc_and_cls
        data = data_file_factory([cls(x=1).SerializeToString()])
        out = tmp_path / "out.parquet"
        result = _run(
            runner,
            cmd(
                "scan",
                data,
                desc,
                "--where",
                "x == 99",
                "--format",
                "parquet",
                "-o",
                str(out),
            ),
        )
        assert result.exit_code == 0, result.stderr
        assert pq.read_table(out).num_rows == 0

    def test_r9_where_filters_before_conversion(
        self,
        runner: CliRunner,
        desc_and_cls: tuple[Path, type],
        data_file_factory: Callable[..., Path],
        tmp_path: Path,
    ) -> None:
        desc, cls = desc_and_cls
        data = data_file_factory([cls(x=n).SerializeToString() for n in (1, 2, 3)])
        out = tmp_path / "out.parquet"
        result = _run(
            runner,
            cmd(
                "scan",
                data,
                desc,
                "--where",
                "x == 2",
                "--format",
                "parquet",
                "-o",
                str(out),
            ),
        )
        assert result.exit_code == 0, result.stderr
        assert f"wrote 1 rows to {out}" in result.stderr
        assert pq.read_table(out).column("x").to_pylist() == [2]


class TestFaultDiscard:
    def test_ae3_mid_file_fault_withholds_output(
        self,
        runner: CliRunner,
        desc_and_cls: tuple[Path, type],
        data_file_factory: Callable[..., Path],
        tmp_path: Path,
    ) -> None:
        desc, cls = desc_and_cls
        # Good record AFTER the fault: the scan continues past the decode
        # fault under collect, yet the complete-looking file is withheld.
        data = data_file_factory(
            [
                cls(x=1).SerializeToString(),
                BAD_PAYLOAD,
                cls(x=3).SerializeToString(),
            ]
        )
        out = tmp_path / "out.parquet"
        result = _run(runner, cmd("scan", data, desc, "--format", "parquet", "-o", str(out)))
        assert result.exit_code == 2
        assert "Error:" in result.stderr
        assert "1 record fault(s)" in result.stderr
        # The reworded message carries the first fault's location (R20).
        assert "record 1" in result.stderr
        assert result.stdout == ""
        assert not out.exists()
        assert _no_partial_left(tmp_path)

    def test_r16_pre_existing_output_preserved_on_fault(
        self,
        runner: CliRunner,
        desc_and_cls: tuple[Path, type],
        data_file_factory: Callable[..., Path],
        tmp_path: Path,
    ) -> None:
        desc, cls = desc_and_cls
        data = data_file_factory([BAD_PAYLOAD])
        out = tmp_path / "out.parquet"
        out.write_bytes(b"precious previous output")
        result = _run(runner, cmd("scan", data, desc, "--format", "parquet", "-o", str(out)))
        assert result.exit_code == 2
        assert out.read_bytes() == b"precious previous output"
        assert _no_partial_left(tmp_path)


class TestFilesystemErrors:
    def test_r18_missing_parent_directory_clean_exit_2(
        self,
        runner: CliRunner,
        desc_and_cls: tuple[Path, type],
        data_file_factory: Callable[..., Path],
        tmp_path: Path,
    ) -> None:
        desc, cls = desc_and_cls
        data = data_file_factory([cls(x=1).SerializeToString()])
        out = tmp_path / "no-such-dir" / "out.parquet"
        # catch_exceptions=False: a traceback would raise out of the runner,
        # so reaching the assertions at all proves the clean exit-2 path.
        result = _run(runner, cmd("scan", data, desc, "--format", "parquet", "-o", str(out)))
        assert result.exit_code == 2
        assert "Error:" in result.stderr
        assert not out.exists()

    def test_r18_output_at_existing_directory_rejected_at_parse(
        self,
        runner: CliRunner,
        desc_and_cls: tuple[Path, type],
        data_file_factory: Callable[..., Path],
        tmp_path: Path,
    ) -> None:
        desc, cls = desc_and_cls
        data = data_file_factory([cls(x=1).SerializeToString()])
        target_dir = tmp_path / "results"
        target_dir.mkdir()
        result = _run(
            runner,
            cmd("scan", data, desc, "--format", "parquet", "-o", str(target_dir)),
        )
        assert result.exit_code == 2
        assert "Error:" in result.stderr


class TestValueEncoding:
    def _enum_bytes_setup(self, tmp_path: Path) -> tuple[Path, type]:
        """A descriptor with enum + bytes fields (the conftest ``a.A`` carries
        only ``int32 x``), following the ``_build_fds`` pattern from
        ``tests/storage/test_columnar.py``."""
        fds = descriptor_pb2.FileDescriptorSet()
        f = fds.file.add()
        f.name = "ev2.proto"
        f.package = "ev2"
        f.syntax = "proto3"
        color = f.enum_type.add()
        color.name = "Color"
        for n, num in (("UNKNOWN", 0), ("RED", 1)):
            v = color.value.add()
            v.name, v.number = n, num
        m = f.message_type.add()
        m.name = "E"
        fid = m.field.add()
        fid.name, fid.number, fid.type, fid.label = "id", 1, F.TYPE_INT32, F.LABEL_OPTIONAL
        fp = m.field.add()
        fp.name, fp.number, fp.type, fp.label = (
            "payload",
            2,
            F.TYPE_BYTES,
            F.LABEL_OPTIONAL,
        )
        fc = m.field.add()
        fc.name, fc.number, fc.type, fc.label = "color", 3, F.TYPE_ENUM, F.LABEL_OPTIONAL
        fc.type_name = ".ev2.Color"
        desc_path = tmp_path / "ev2.desc"
        desc_path.write_bytes(fds.SerializeToString())
        cls = FileDescriptorSetSchema(fds, "ev2.E").resolve().message_class
        return desc_path, cls

    def test_arrow_native_values_diverge_from_json_view(
        self,
        runner: CliRunner,
        data_file_factory: Callable[..., Path],
        tmp_path: Path,
    ) -> None:
        # Parquet leaf values are Arrow-native by design: bytes -> binary (not
        # base64 strings), enums -> int32 (not names). Spot check only — the
        # library's own tests cover the mapping deeply.
        desc_path, cls = self._enum_bytes_setup(tmp_path)
        data = data_file_factory([cls(id=1, payload=b"\x01\x02", color=1).SerializeToString()])
        out = tmp_path / "out.parquet"
        result = _run(
            runner,
            [
                "storage",
                "scan",
                str(data),
                "--desc",
                str(desc_path),
                "--type",
                "ev2.E",
                "--format",
                "parquet",
                "-o",
                str(out),
            ],
        )
        assert result.exit_code == 0, result.stderr
        table = pq.read_table(out)
        assert pa.types.is_binary(table.schema.field("payload").type)
        assert pa.types.is_integer(table.schema.field("color").type)
        assert table.column("payload").to_pylist() == [b"\x01\x02"]
        assert table.column("color").to_pylist() == [1]
