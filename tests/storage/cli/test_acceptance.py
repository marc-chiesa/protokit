"""Cross-cutting CLI acceptance — the maintainer's real questions, via the CLI.

Proves the office-hours success criteria at the granularity each names: answer
"how many records where X" (Q1) and "show me record N readably" (Q3) from the
command line, beat ``protoc --decode`` (many records, filtered, in one call), and
honor the exit-code contract. Cross-channel correlation (Q2) is asserted as a
*library* capability with an explicit note that the single-stream CLI does not
expose it. No C-extension mocks — every fault is driven with real bytes.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from click.testing import CliRunner

from protokit.cli import main
from protokit.storage import FileDescriptorSetSchema, ScanRecord, StreamRegistry, scan
from tests.storage.cli.conftest import cmd
from tests.storage.proto_fixtures import fds, file_proto


def _run(runner: CliRunner, args: list[str]):  # noqa: ANN202
    return runner.invoke(main, args, catch_exceptions=False)


class TestAssignmentViaCli:
    def test_q1_how_many_records_where_x(
        self,
        runner: CliRunner,
        desc_and_cls: tuple[Path, type],
        data_file_factory: Callable[..., Path],
    ) -> None:
        desc, cls = desc_and_cls
        data = data_file_factory([cls(x=v).SerializeToString() for v in (7, 1, 7, 7, 2)])
        result = _run(runner, cmd("count", data, desc, "--where", "x == 7"))
        assert result.exit_code == 0
        assert result.output.strip() == "3"

    def test_q3_show_record_n_readably(
        self,
        runner: CliRunner,
        desc_and_cls: tuple[Path, type],
        data_file_factory: Callable[..., Path],
    ) -> None:
        desc, cls = desc_and_cls
        data = data_file_factory([cls(x=v).SerializeToString() for v in (10, 20, 30)])
        # head -n 2 surfaces the first two records readably; the 2nd is shown.
        result = _run(runner, cmd("head", data, desc, "-n", "2"))
        assert result.exit_code == 0
        assert result.output.count("# stream=") == 2
        assert "x: 20" in result.output  # the Nth record, human-readable
        assert "x: 30" not in result.output

    def test_beats_protoc_decode_scan_filter_dump_in_one_call(
        self,
        runner: CliRunner,
        desc_and_cls: tuple[Path, type],
        data_file_factory: Callable[..., Path],
    ) -> None:
        # protoc --decode is one message at a time, unfilterable. This is many
        # records, filtered, materialized, in a single pipeable command.
        desc, cls = desc_and_cls
        data = data_file_factory([cls(x=v).SerializeToString() for v in range(10)])
        result = _run(runner, cmd("scan", data, desc, "--where", "x != 0", "--format", "json"))
        assert result.exit_code == 0
        lines = [ln for ln in result.output.splitlines() if ln.strip()]
        assert len(lines) == 9  # all but x==0


class TestQ2CrossChannelCorrelationIsLibraryOnly:
    def test_library_scan_tags_records_by_stream_for_correlation(self) -> None:
        # Two related streams; a single interleaved scan tags each record with
        # its stream_id so a downstream join correlates across channels.
        a = file_proto("a.proto", "a", message="A")
        b = file_proto("b.proto", "b", message="B", field_name="y")
        registry = StreamRegistry()
        registry.register_stream("orders", FileDescriptorSetSchema(fds(a), "a.A"))
        registry.register_stream("events", FileDescriptorSetSchema(fds(b), "b.B"))
        a_cls = registry.get("orders").message_class  # type: ignore[union-attr]
        b_cls = registry.get("events").message_class  # type: ignore[union-attr]
        feed = [
            ("orders", a_cls(x=1).SerializeToString()),
            ("events", b_cls(y=2).SerializeToString()),
            ("orders", a_cls(x=3).SerializeToString()),
        ]
        records = list(scan(iter(feed), registry))
        by_stream: dict[str, list[ScanRecord]] = {}
        for r in records:
            by_stream.setdefault(r.stream_id, []).append(r)
        assert [r.message.x for r in by_stream["orders"]] == [1, 3]
        assert [r.message.y for r in by_stream["events"]] == [2]

    def test_cli_scan_has_no_stream_flag(self, runner: CliRunner) -> None:
        # The CLI is single-stream in PR1.5: no multi-stream flag is exposed.
        result = _run(runner, ["storage", "scan", "--help"])
        assert "--stream" not in result.output


class TestExitCodeMatrix:
    @pytest.mark.parametrize(
        "extra,where,expected",
        [
            ([], None, 0),  # clean scan
            (["--quiet"], "x == 999", 1),  # count --quiet, zero matches (grep-like)
            ([], "x > 5", 2),  # malformed --where (richer)
        ],
    )
    def test_count_matrix(
        self,
        runner: CliRunner,
        desc_and_cls: tuple[Path, type],
        data_file_factory: Callable[..., Path],
        extra: list[str],
        where: str | None,
        expected: int,
    ) -> None:
        desc, cls = desc_and_cls
        data = data_file_factory([cls(x=7).SerializeToString()])
        args = cmd("count", data, desc, *extra)
        if where is not None:
            args += ["--where", where]
        result = _run(runner, args)
        assert result.exit_code == expected

    def test_decode_fault_under_raise_is_exit_2(
        self,
        runner: CliRunner,
        desc_and_cls: tuple[Path, type],
        data_file_factory: Callable[..., Path],
    ) -> None:
        desc, cls = desc_and_cls
        # a good record then a truncated A body (b"\x08") -> decode FrameError.
        data = data_file_factory([cls(x=7).SerializeToString(), b"\x08"])
        result = _run(runner, cmd("scan", data, desc))
        assert result.exit_code == 2
        assert "Error:" in result.stderr

    def test_no_schema_source_is_exit_2(
        self,
        runner: CliRunner,
        data_file_factory: Callable[..., Path],
    ) -> None:
        data = data_file_factory([])
        result = _run(runner, ["storage", "count", str(data), "--type", "a.A"])
        assert result.exit_code == 2
