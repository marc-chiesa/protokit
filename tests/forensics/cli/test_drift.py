"""U7 — the ``forensics drift`` command end-to-end (compiler-free .desc schemas)."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from protokit.cli import main
from tests.forensics.fixtures import fdp, write_desc, write_message


def _invoke(runner: CliRunner, *args: str) -> object:
    return runner.invoke(main, ["forensics", "drift", *args], catch_exceptions=False)


def test_drift_clean_message(runner: CliRunner, tmp_path: Path) -> None:
    schema = fdp({"x": 1, "y": 2})
    write_desc(tmp_path / "v.desc", schema)
    write_message(tmp_path / "msg.bin", schema, {"x": 5, "y": 7})

    result = _invoke(
        runner,
        str(tmp_path / "msg.bin"),
        "--schema", f"v={tmp_path / 'v.desc'}",
        "--type", "a.A",
    )

    assert result.exit_code == 0
    assert "no divergences" in result.stdout


def test_drift_writes_grep_able_stderr_summary(runner: CliRunner, tmp_path: Path) -> None:
    clean = fdp({"x": 1, "y": 2})
    write_desc(tmp_path / "clean.desc", clean)
    write_message(tmp_path / "clean.bin", clean, {"x": 5, "y": 7})
    rich, poor = fdp({"x": 1, "y": 5}), fdp({"x": 1})
    write_desc(tmp_path / "poor.desc", poor)
    write_message(tmp_path / "drift.bin", rich, {"x": 5, "y": 7})

    ok = _invoke(
        runner, str(tmp_path / "clean.bin"),
        "--schema", f"v={tmp_path / 'clean.desc'}", "--type", "a.A",
    )
    assert ok.exit_code == 0
    assert "consistent" in ok.stderr  # match-style stderr verdict line

    drifted = _invoke(
        runner, str(tmp_path / "drift.bin"),
        "--schema", f"poor={tmp_path / 'poor.desc'}", "--type", "a.A",
    )
    assert drifted.exit_code == 0
    assert "divergence" in drifted.stderr


def test_drift_reports_undeclared(runner: CliRunner, tmp_path: Path) -> None:
    rich, poor = fdp({"x": 1, "y": 5}), fdp({"x": 1})
    write_desc(tmp_path / "poor.desc", poor)
    write_message(tmp_path / "msg.bin", rich, {"x": 5, "y": 7})

    result = _invoke(
        runner,
        str(tmp_path / "msg.bin"),
        "--schema", f"poor={tmp_path / 'poor.desc'}",
        "--type", "a.A",
    )

    assert result.exit_code == 0
    assert "undeclared" in result.stdout


def test_drift_json_carries_schema_version(runner: CliRunner, tmp_path: Path) -> None:
    rich, poor = fdp({"x": 1, "y": 5}), fdp({"x": 1})
    write_desc(tmp_path / "poor.desc", poor)
    write_message(tmp_path / "msg.bin", rich, {"x": 5, "y": 7})

    result = _invoke(
        runner,
        str(tmp_path / "msg.bin"),
        "--schema", f"poor={tmp_path / 'poor.desc'}",
        "--type", "a.A",
        "--format", "json",
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "0.1"
    assert any(d["kind"] == "undeclared" for d in payload["divergences"])


def test_drift_missing_schema_exits_2(runner: CliRunner, tmp_path: Path) -> None:
    write_message(tmp_path / "msg.bin", fdp({"x": 1}), {"x": 5})

    result = _invoke(runner, str(tmp_path / "msg.bin"), "--type", "a.A")

    assert result.exit_code == 2
    assert "Error:" in result.stderr


def test_drift_malformed_message_exits_2(runner: CliRunner, tmp_path: Path) -> None:
    write_desc(tmp_path / "v.desc", fdp({"x": 1}))
    (tmp_path / "msg.bin").write_bytes(b"\x80")  # truncated varint — WalkError

    result = _invoke(
        runner,
        str(tmp_path / "msg.bin"),
        "--schema", f"v={tmp_path / 'v.desc'}",
        "--type", "a.A",
    )

    assert result.exit_code == 2
    assert "Error:" in result.stderr
