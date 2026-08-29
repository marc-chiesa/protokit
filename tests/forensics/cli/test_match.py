"""U5 — the ``forensics match`` command end-to-end (compiler-free .desc schemas)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from protokit.cli import main
from protokit.storage.schema_source import ProtoFileSchema
from tests.forensics.fixtures import (
    fdp,
    msg_bytes,
    proto2_required_fdp,
    write_desc,
    write_message,
)


def _invoke(runner: CliRunner, *args: str) -> object:
    return runner.invoke(main, ["forensics", "match", *args], catch_exceptions=False)


def test_clean_winner_human(runner: CliRunner, tmp_path: Path) -> None:
    full, old = fdp({"x": 1, "y": 2}), fdp({"x": 1})
    write_desc(tmp_path / "full.desc", full)
    write_desc(tmp_path / "old.desc", old)
    write_message(tmp_path / "msg.bin", full, {"x": 5, "y": 7})

    result = _invoke(
        runner,
        str(tmp_path / "msg.bin"),
        "--schema", f"full={tmp_path / 'full.desc'}",
        "--schema", f"old={tmp_path / 'old.desc'}",
        "--type", "a.A",
    )

    assert result.exit_code == 0
    assert "full" in result.stdout
    assert "clean match" in result.stderr


def test_no_clean_match(runner: CliRunner, tmp_path: Path) -> None:
    producer = fdp({"x": 1, "y": 2, "z": 3})
    write_desc(tmp_path / "x.desc", fdp({"x": 1}))
    write_desc(tmp_path / "y.desc", fdp({"y": 2}))
    write_message(tmp_path / "msg.bin", producer, {"x": 5, "y": 7, "z": 9})

    result = _invoke(
        runner,
        str(tmp_path / "msg.bin"),
        "--schema", f"x={tmp_path / 'x.desc'}",
        "--schema", f"y={tmp_path / 'y.desc'}",
        "--type", "a.A",
    )

    assert result.exit_code == 0
    assert "no clean match" in result.stderr


def test_json_format_carries_schema_version(runner: CliRunner, tmp_path: Path) -> None:
    full = fdp({"x": 1, "y": 2})
    write_desc(tmp_path / "full.desc", full)
    write_message(tmp_path / "msg.bin", full, {"x": 5, "y": 7})

    result = _invoke(
        runner,
        str(tmp_path / "msg.bin"),
        "--schema", f"full={tmp_path / 'full.desc'}",
        "--type", "a.A",
        "--format", "json",
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "0.1"
    assert payload["verdict"] == "clean_winner"
    assert payload["candidates"][0]["label"] == "full"


def test_label_defaults_to_filename_stem(runner: CliRunner, tmp_path: Path) -> None:
    schema = fdp({"x": 1})
    write_desc(tmp_path / "v3.desc", schema)
    write_message(tmp_path / "msg.bin", schema, {"x": 5})

    result = _invoke(
        runner,
        str(tmp_path / "msg.bin"),
        "--schema", str(tmp_path / "v3.desc"),  # bare path, no LABEL=
        "--type", "a.A",
        "--format", "json",
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)["candidates"][0]["label"] == "v3"


def test_missing_type_exits_2(runner: CliRunner, tmp_path: Path) -> None:
    write_desc(tmp_path / "v.desc", fdp({"x": 1}))
    write_message(tmp_path / "msg.bin", fdp({"x": 1}), {"x": 5})

    result = _invoke(
        runner,
        str(tmp_path / "msg.bin"),
        "--schema", f"v={tmp_path / 'v.desc'}",
    )

    assert result.exit_code == 2
    assert "Error:" in result.stderr


def test_missing_schema_exits_2(runner: CliRunner, tmp_path: Path) -> None:
    write_message(tmp_path / "msg.bin", fdp({"x": 1}), {"x": 5})

    result = _invoke(runner, str(tmp_path / "msg.bin"), "--type", "a.A")

    assert result.exit_code == 2
    assert "Error:" in result.stderr


def test_oversized_message_exits_2(runner: CliRunner, tmp_path: Path) -> None:
    schema = fdp({"x": 1})
    write_desc(tmp_path / "v.desc", schema)
    write_message(tmp_path / "msg.bin", schema, {"x": 5})

    result = _invoke(
        runner,
        str(tmp_path / "msg.bin"),
        "--schema", f"v={tmp_path / 'v.desc'}",
        "--type", "a.A",
        "--max-message-bytes", "1",
    )

    assert result.exit_code == 2
    assert "exceeding --max-message-bytes" in result.stderr
    assert "is 2 bytes" in result.stderr  # regular file: the real size, exactly


@pytest.mark.skipif(not Path("/dev/zero").exists(), reason="needs a POSIX /dev/zero")
def test_oversized_non_regular_input_does_not_claim_zero_bytes(
    runner: CliRunner, tmp_path: Path
) -> None:
    """A non-regular input must not be refused as "0 bytes".

    ``stat().st_size`` is 0 for exactly the inputs the cap matters most for — a
    FIFO, ``/dev/stdin``, a process substitution — so reporting it there claimed
    the input was 0 bytes while refusing it for being too large. ``/dev/zero``
    stands in: an endless reader whose ``st_size`` is 0.
    """
    schema = fdp({"x": 1})
    write_desc(tmp_path / "v.desc", schema)

    result = _invoke(
        runner,
        "/dev/zero",
        "--schema", f"v={tmp_path / 'v.desc'}",
        "--type", "a.A",
        "--max-message-bytes", "16",
    )

    assert result.exit_code == 2
    assert "exceeding --max-message-bytes" in result.stderr
    assert "is 0 bytes" not in result.stderr
    assert "at least 17 bytes" in result.stderr


def test_malformed_desc_exits_2(runner: CliRunner, tmp_path: Path) -> None:
    (tmp_path / "bad.desc").write_bytes(b"\xff\xff\xff\xff not a descriptor set")
    write_message(tmp_path / "msg.bin", fdp({"x": 1}), {"x": 5})

    result = _invoke(
        runner,
        str(tmp_path / "msg.bin"),
        "--schema", f"v={tmp_path / 'bad.desc'}",
        "--type", "a.A",
    )

    assert result.exit_code == 2
    assert "Error:" in result.stderr


def test_match_with_proto_sources_compiles_and_ranks(
    runner: CliRunner, tmp_path: Path
) -> None:
    """The headline .proto path: candidate schemas compiled end-to-end via the backend."""
    v1 = tmp_path / "v1.proto"
    v1.write_text('syntax = "proto3";\npackage ev;\nmessage E { int32 x = 1; }\n')
    v2 = tmp_path / "v2.proto"
    v2.write_text(
        'syntax = "proto3";\npackage ev;\nmessage E { int32 x = 1; string y = 2; }\n'
    )
    produced = ProtoFileSchema(v2, "ev.E").resolve().message_class()
    produced.x, produced.y = 5, "hi"
    (tmp_path / "msg.bin").write_bytes(produced.SerializeToString())

    result = _invoke(
        runner,
        str(tmp_path / "msg.bin"),
        "--schema", f"v1={v1}",
        "--schema", f"v2={v2}",
        "--type", "ev.E",
    )

    assert result.exit_code == 0
    assert "clean match" in result.stderr  # v2 fully models the message
    assert result.stdout.splitlines()[1].split()[1] == "v2"  # v2 ranks first


def test_duplicate_schema_labels_exit_2(runner: CliRunner, tmp_path: Path) -> None:
    write_desc(tmp_path / "a.desc", fdp({"x": 1}))
    write_desc(tmp_path / "b.desc", fdp({"x": 1, "y": 2}))
    write_message(tmp_path / "msg.bin", fdp({"x": 1}), {"x": 5})

    result = _invoke(
        runner,
        str(tmp_path / "msg.bin"),
        "--schema", f"v={tmp_path / 'a.desc'}",
        "--schema", f"v={tmp_path / 'b.desc'}",  # same label
        "--type", "a.A",
    )

    assert result.exit_code == 2
    assert "duplicate --schema label" in result.stderr


def test_fault_row_renders_dashes(runner: CliRunner, tmp_path: Path) -> None:
    """A fault-tier (incomplete) row renders dash cells without breaking the table."""
    optional_only = proto2_required_fdp(required={}, optional={"x": 1, "y": 2})
    requires_x = proto2_required_fdp(required={"x": 1}, optional={"y": 2})
    write_desc(tmp_path / "opt.desc", optional_only)
    write_desc(tmp_path / "req.desc", requires_x)
    (tmp_path / "msg.bin").write_bytes(msg_bytes(optional_only, {"y": 7}))  # x absent

    result = _invoke(
        runner,
        str(tmp_path / "msg.bin"),
        "--schema", f"opt={tmp_path / 'opt.desc'}",
        "--schema", f"req={tmp_path / 'req.desc'}",  # incomplete: missing required x
        "--type", "a.A",
    )

    assert result.exit_code == 0
    assert "incomplete" in result.stdout
    assert " -" in result.stdout  # the fault row's dash cells rendered


def test_unparseable_under_all_exits_2(runner: CliRunner, tmp_path: Path) -> None:
    write_desc(tmp_path / "v.desc", fdp({"x": 1}))
    (tmp_path / "msg.bin").write_bytes(b"\x08")  # truncated varint — DecodeError

    result = _invoke(
        runner,
        str(tmp_path / "msg.bin"),
        "--schema", f"v={tmp_path / 'v.desc'}",
        "--type", "a.A",
    )

    assert result.exit_code == 2
    assert "does not parse under any candidate schema" in result.stderr
