"""``protokit storage --on-error`` — raise/skip/warn, and the framing-vs-decode limit.

The load-bearing distinction (KD-7): the length-delimited reader is a generator,
so a *framing* fault (truncated / oversized frame) ENDS the scan even under
skip/warn, while a *decode* fault (a bad message body) leaves the source alive and
is recovered past. The tests assert both so the contract is not oversold.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from click.testing import CliRunner

from protokit.cli import main
from tests.storage.proto_fixtures import delimited, encode_varint

# A 1-byte frame body that is a truncated A{int32 x=1} -> a DECODE fault
# (recoverable: the source keeps yielding).
_DECODE_BAD = b"\x08"


def _run(runner: CliRunner, args: list[str]):  # noqa: ANN202
    return runner.invoke(main, args, catch_exceptions=False)


def _base(data: Path, desc: Path) -> list[str]:
    return ["storage", "scan", str(data), "--desc", str(desc), "--type", "a.A"]


def test_raise_default_aborts_on_bad_record(
    runner: CliRunner,
    desc_and_cls: tuple[Path, type],
    data_file_factory: Callable[..., Path],
) -> None:
    desc, cls = desc_and_cls
    data = data_file_factory([cls(x=7).SerializeToString(), _DECODE_BAD])
    result = _run(runner, _base(data, desc))
    assert result.exit_code == 2
    assert "Error:" in result.stderr


def test_skip_recovers_past_decode_faults(
    runner: CliRunner,
    desc_and_cls: tuple[Path, type],
    data_file_factory: Callable[..., Path],
) -> None:
    desc, cls = desc_and_cls
    data = data_file_factory(
        [cls(x=7).SerializeToString(), _DECODE_BAD, cls(x=9).SerializeToString()]
    )
    result = _run(runner, [*_base(data, desc), "--on-error", "skip"])
    assert result.exit_code == 0
    # Both good records survive the bad one in the middle.
    assert result.output.count("# stream=") == 2


def test_warn_recovers_and_reports_decode_faults(
    runner: CliRunner,
    desc_and_cls: tuple[Path, type],
    data_file_factory: Callable[..., Path],
) -> None:
    desc, cls = desc_and_cls
    data = data_file_factory(
        [cls(x=7).SerializeToString(), _DECODE_BAD, cls(x=9).SerializeToString()]
    )
    result = _run(runner, [*_base(data, desc), "--on-error", "warn"])
    assert result.exit_code == 0
    assert result.output.count("# stream=") == 2  # good records on stdout
    assert "Warning:" in result.stderr  # the fault on stderr
    assert "scanned 2 records, 1 faults" in result.stderr  # trailing summary


def test_warn_framing_fault_stops_the_scan(
    runner: CliRunner,
    desc_and_cls: tuple[Path, type],
    raw_file_factory: Callable[..., Path],
) -> None:
    desc, cls = desc_and_cls
    # good1, then an OVERSIZED-length frame (declares ~1GB > the 64 MiB cap -> a
    # framing fault raised by the reader), then good2 which is now unreachable.
    raw = (
        delimited(cls(x=7).SerializeToString())
        + encode_varint(10**9)
        + delimited(cls(x=9).SerializeToString())
    )
    data = raw_file_factory(raw)
    result = _run(runner, [*_base(data, desc), "--on-error", "warn"])
    assert result.exit_code == 0
    # Only good1 emerges; the framing fault exhausts the reader so good2 is lost.
    assert result.output.count("# stream=") == 1
    assert "x: 7" in result.output and "x: 9" not in result.output
    assert "Warning:" in result.stderr


def test_warn_json_stdout_stays_valid_jsonl(
    runner: CliRunner,
    desc_and_cls: tuple[Path, type],
    data_file_factory: Callable[..., Path],
) -> None:
    desc, cls = desc_and_cls
    data = data_file_factory(
        [cls(x=7).SerializeToString(), _DECODE_BAD, cls(x=9).SerializeToString()]
    )
    result = _run(runner, [*_base(data, desc), "--on-error", "warn", "--format", "json"])
    assert result.exit_code == 0
    # stdout (separate from stderr) is clean JSONL: warnings did not interleave.
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert [json.loads(ln) for ln in lines] == [{"x": 7}, {"x": 9}]
    assert "Warning:" not in result.stdout
    assert "Warning:" in result.stderr
