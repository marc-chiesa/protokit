"""``protokit storage --on-error`` — raise/skip/warn, and the framing-vs-decode limit.

The load-bearing distinction (KD-7): the length-delimited reader is a generator,
so a *framing* fault (truncated / oversized frame) ENDS the scan even under
skip/warn, while a *decode* fault (a bad message body) leaves the source alive and
is recovered past. The tests assert both so the contract is not oversold.

**U8 changed the exit code, not the output.** ``skip`` / ``warn`` used to exit
0 whenever the run reached the end, so a scan that silently dropped records was
indistinguishable from a clean one. They now exit 2 once any record was not
read; the good records still reach stdout exactly as before, and ``skip`` is
still silent about the individual faults. What changed is only whether the
process claims the scan succeeded.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from click.testing import CliRunner

from protokit.cli import main
from tests.storage.cli.conftest import DECODE_BAD as _DECODE_BAD
from tests.storage.proto_fixtures import delimited, encode_varint


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
    # U8: a dropped record means the scan did not read the whole input.
    assert result.exit_code == 2
    # Both good records survive the bad one in the middle.
    assert result.output.count("# stream=") == 2
    # ``skip`` stays silent about each fault -- only the closing reason line.
    assert "Warning:" not in result.stderr
    assert "1 record(s)" in result.stderr


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
    assert result.exit_code == 2  # U8: a record was dropped
    assert result.output.count("# stream=") == 2  # good records on stdout
    assert "Warning:" in result.stderr  # the fault on stderr
    assert "matched 2 records, 1 faults" in result.stderr  # trailing summary


def test_warn_summary_counts_matched_not_total_under_where(
    runner: CliRunner,
    desc_and_cls: tuple[Path, type],
    data_file_factory: Callable[..., Path],
) -> None:
    # The summary reports records that PASSED the predicate, labeled "matched"
    # (not "scanned") — so it never overstates as total volume. Here 3 records
    # match x==7 among 5 good + 1 decode-bad.
    desc, cls = desc_and_cls
    payloads = [cls(x=v).SerializeToString() for v in (7, 1, 7)] + [_DECODE_BAD] + [
        cls(x=v).SerializeToString() for v in (7, 2)
    ]
    data = data_file_factory(payloads)
    result = _run(runner, [*_base(data, desc), "--on-error", "warn", "--where", "x == 7"])
    assert result.exit_code == 2  # U8: a record was dropped
    assert "matched 3 records, 1 faults" in result.stderr
    assert "scanned" not in result.stderr  # never the misleading label


def test_count_under_warn_recovers_and_summarizes(
    runner: CliRunner,
    desc_and_cls: tuple[Path, type],
    data_file_factory: Callable[..., Path],
) -> None:
    # head/count share the warn->route wiring; exercise it via count.
    desc, cls = desc_and_cls
    data = data_file_factory(
        [cls(x=7).SerializeToString(), _DECODE_BAD, cls(x=9).SerializeToString()]
    )
    result = _run(
        runner,
        ["storage", "count", str(data), "--desc", str(desc), "--type", "a.A", "--on-error", "warn"],
    )
    assert result.exit_code == 2  # U8: a record was dropped
    assert result.stdout.strip() == "2"  # the count on stdout, separate from warnings
    assert "matched 2 records, 1 faults" in result.stderr


def test_unreadable_data_file_is_exit_2(
    runner: CliRunner,
    desc_and_cls: tuple[Path, type],
    tmp_path: Path,
) -> None:
    import os
    import sys

    if sys.platform == "win32":  # chmod read-bit semantics differ on Windows
        return
    desc, _cls = desc_and_cls
    unreadable = tmp_path / "noperm.bin"
    unreadable.write_bytes(b"")
    os.chmod(unreadable, 0o000)
    try:
        result = _run(runner, _base(unreadable, desc))
        # An unreadable file -> clean exit 2 (not a traceback / exit 1). Click's
        # Path(readable=True) catches this case at parse; the _open_data guard
        # covers the rarer TOCTOU window where the file becomes unreadable after
        # the check. Either way the 0/2 contract holds.
        assert result.exit_code == 2
        assert "readable" in result.stderr or "cannot read" in result.stderr
    finally:
        os.chmod(unreadable, 0o600)  # let tmp cleanup remove it


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
    assert result.exit_code == 2  # U8: good2 was never read
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
    assert result.exit_code == 2  # U8: a record was dropped
    # stdout (separate from stderr) is clean JSONL: warnings did not interleave.
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert [json.loads(ln) for ln in lines] == [{"x": 7}, {"x": 9}]
    assert "Warning:" not in result.stdout
    assert "Warning:" in result.stderr


# ---------------------------------------------------------------------------
# U8 adjacent behavior: the gate fires on a dropped record and on nothing else.
# ---------------------------------------------------------------------------


def test_skip_without_a_fault_still_exits_0(
    runner: CliRunner,
    desc_and_cls: tuple[Path, type],
    data_file_factory: Callable[..., Path],
) -> None:
    """The gate keys on records dropped, not on the mode being tolerant."""
    desc, cls = desc_and_cls
    data = data_file_factory(
        [cls(x=7).SerializeToString(), cls(x=9).SerializeToString()]
    )
    result = _run(runner, [*_base(data, desc), "--on-error", "skip"])
    assert result.exit_code == 0
    assert result.output.count("# stream=") == 2
    assert "record(s) were not read" not in result.stderr


def test_head_that_stops_before_the_fault_exits_0(
    runner: CliRunner,
    desc_and_cls: tuple[Path, type],
    data_file_factory: Callable[..., Path],
) -> None:
    """``-n`` is the user's own limit; records past it were never in scope."""
    desc, cls = desc_and_cls
    data = data_file_factory(
        [cls(x=7).SerializeToString(), cls(x=9).SerializeToString(), _DECODE_BAD]
    )
    result = _run(runner, [
        "storage", "head", str(data), "--desc", str(desc), "--type", "a.A",
        "-n", "2", "--on-error", "skip",
    ])
    assert result.exit_code == 0
    assert result.output.count("# stream=") == 2


def test_head_that_reaches_the_fault_exits_2(
    runner: CliRunner,
    desc_and_cls: tuple[Path, type],
    data_file_factory: Callable[..., Path],
) -> None:
    desc, cls = desc_and_cls
    data = data_file_factory(
        [cls(x=7).SerializeToString(), _DECODE_BAD, cls(x=9).SerializeToString()]
    )
    result = _run(runner, [
        "storage", "head", str(data), "--desc", str(desc), "--type", "a.A",
        "-n", "2", "--on-error", "skip",
    ])
    assert result.exit_code == 2
    assert result.output.count("# stream=") == 2  # both good records still shown


def test_the_reason_names_the_count_and_one_example(
    runner: CliRunner,
    desc_and_cls: tuple[Path, type],
    data_file_factory: Callable[..., Path],
) -> None:
    """One bounded line, whatever the fault count: the seam's reason."""
    desc, cls = desc_and_cls
    data = data_file_factory(
        [_DECODE_BAD, _DECODE_BAD, cls(x=9).SerializeToString()]
    )
    result = _run(runner, [*_base(data, desc), "--on-error", "skip"])
    assert result.exit_code == 2
    assert "Error: 2 record(s) were not read (first: stream" in result.stderr
    assert result.stderr.count("record(s) were not read") == 1


def test_count_quiet_prefers_the_incompleteness_over_the_grep_signal(
    runner: CliRunner,
    desc_and_cls: tuple[Path, type],
    data_file_factory: Callable[..., Path],
) -> None:
    """Zero matches on an unreadable file is not "nothing matched"."""
    desc, cls = desc_and_cls
    data = data_file_factory([_DECODE_BAD, cls(x=9).SerializeToString()])
    result = _run(runner, [
        "storage", "count", str(data), "--desc", str(desc), "--type", "a.A",
        "--quiet", "--on-error", "skip", "--where", "x == 1",
    ])
    assert result.exit_code == 2  # not 1 ("nothing matched")
    assert result.stdout == ""  # --quiet still means no stdout
