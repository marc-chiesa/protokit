"""CLI acceptance + process-survival for recursive-schema rejection (U3).

These need the real parquet extra so the conversion reaches the recursion
pre-flight (the up-front flag guards, which never touch ptars, live in
``test_parquet_guards.py``). The subprocess cases are the load-bearing
regression: a recursive schema used to segfault ptars 0.0.17 and kill the
process (exit -11 / 139), which cannot be asserted in-process — so they run the
CLI in a child process and assert a clean ``exit 2``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("ptars")
pytest.importorskip("pyarrow")

from click.testing import CliRunner  # noqa: E402
from google.protobuf import (  # noqa: E402
    descriptor_pb2,
    struct_pb2,
    timestamp_pb2,
)

from protokit.cli import main  # noqa: E402
from protokit.storage.schema_source import FileDescriptorSetSchema  # noqa: E402
from tests.storage.proto_fixtures import delimited  # noqa: E402

F = descriptor_pb2.FieldDescriptorProto

# Run the CLI in a child process so a hypothetical segfault is observable as a
# negative return code instead of taking down the pytest process.
_CHILD = "from protokit.cli import main; main()"


def _self_ref_fds() -> descriptor_pb2.FileDescriptorSet:
    fds = descriptor_pb2.FileDescriptorSet()
    f = fds.file.add()
    f.name, f.package, f.syntax = "node.proto", "n", "proto3"
    node = f.message_type.add()
    node.name = "Node"
    fld = node.field.add()
    fld.name, fld.number, fld.type, fld.label = (
        "children", 1, F.TYPE_MESSAGE, F.LABEL_REPEATED,
    )
    fld.type_name = ".n.Node"
    return fds


def _wkt_embed_fds(wkt_module: object, wkt_type: str) -> descriptor_pb2.FileDescriptorSet:
    fds = descriptor_pb2.FileDescriptorSet()
    wkt_module.DESCRIPTOR.CopyToProto(fds.file.add())  # type: ignore[attr-defined]
    f = fds.file.add()
    f.name, f.package, f.syntax = "u.proto", "u", "proto3"
    f.dependency.append(wkt_module.DESCRIPTOR.name)  # type: ignore[attr-defined]
    h = f.message_type.add()
    h.name = "Holder"
    fld = h.field.add()
    fld.name, fld.number, fld.type, fld.label = "w", 1, F.TYPE_MESSAGE, F.LABEL_OPTIONAL
    fld.type_name = f".google.protobuf.{wkt_type}"
    return fds


def _write(
    tmp_path: Path, fds: descriptor_pb2.FileDescriptorSet, payloads: tuple[bytes, ...] = ()
) -> tuple[Path, Path]:
    desc = tmp_path / "schema.desc"
    desc.write_bytes(fds.SerializeToString())
    data = tmp_path / "data.bin"
    data.write_bytes(delimited(*payloads))
    return data, desc


def _argv(data: Path, desc: Path, type_name: str, out: Path) -> list[str]:
    return [
        "storage", "scan", str(data), "--desc", str(desc),
        "--type", type_name, "--format", "parquet", "-o", str(out),
    ]


def _reject(result: object, out: Path) -> None:
    assert result.exit_code == 2  # type: ignore[attr-defined]
    assert "Error:" in result.stderr  # type: ignore[attr-defined]
    assert result.stdout == ""  # type: ignore[attr-defined]
    assert not out.exists()


# --- in-process: rejection contract + stderr content -------------------------


def test_self_ref_rejected(runner: CliRunner, tmp_path: Path) -> None:
    data, desc = _write(tmp_path, _self_ref_fds())
    out = tmp_path / "o.parquet"
    result = runner.invoke(main, _argv(data, desc, "n.Node", out), catch_exceptions=False)
    _reject(result, out)
    assert "recursive" in result.stderr.lower()
    assert "n.Node" in result.stderr


def test_struct_embed_rejected(runner: CliRunner, tmp_path: Path) -> None:
    data, desc = _write(tmp_path, _wkt_embed_fds(struct_pb2, "Struct"))
    out = tmp_path / "o.parquet"
    result = runner.invoke(main, _argv(data, desc, "u.Holder", out), catch_exceptions=False)
    _reject(result, out)
    assert "google.protobuf.Struct" in result.stderr


def test_non_recursive_wkt_converts(runner: CliRunner, tmp_path: Path) -> None:
    fds = _wkt_embed_fds(timestamp_pb2, "Timestamp")
    cls = FileDescriptorSetSchema(fds, "u.Holder").resolve().message_class
    msg = cls()
    msg.w.seconds = 7
    data, desc = _write(tmp_path, fds, (msg.SerializeToString(),))
    out = tmp_path / "o.parquet"
    result = runner.invoke(main, _argv(data, desc, "u.Holder", out), catch_exceptions=False)
    assert result.exit_code == 0, result.stderr
    assert out.exists()


# --- subprocess: the process survives (exit 2, never a segfault) -------------


def test_subprocess_survives_self_reference(tmp_path: Path) -> None:
    data, desc = _write(tmp_path, _self_ref_fds())
    out = tmp_path / "o.parquet"
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD, *_argv(data, desc, "n.Node", out)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2, (
        f"expected clean exit 2, got {proc.returncode}: {proc.stderr[-300:]}"
    )
    assert not out.exists()


@pytest.mark.parametrize("wkt", ["Struct", "Value", "ListValue"])
def test_subprocess_survives_recursive_wkt(tmp_path: Path, wkt: str) -> None:
    data, desc = _write(tmp_path, _wkt_embed_fds(struct_pb2, wkt))
    out = tmp_path / "o.parquet"
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD, *_argv(data, desc, "u.Holder", out)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2, (
        f"expected clean exit 2, got {proc.returncode}: {proc.stderr[-300:]}"
    )
    assert not out.exists()
