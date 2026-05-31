"""``protokit storage scan`` — readable dump, JSON, --where, empty/garbage input."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from click.testing import CliRunner

from protokit.cli import main
from tests.storage.cli.conftest import cmd


def _run(runner: CliRunner, args: list[str]):  # noqa: ANN202
    return runner.invoke(main, args, catch_exceptions=False)


class TestScanHappy:
    def test_human_dump_shows_every_record(
        self,
        runner: CliRunner,
        desc_and_cls: tuple[Path, type],
        data_file_factory: Callable[..., Path],
    ) -> None:
        desc, cls = desc_and_cls
        data = data_file_factory([cls(x=7).SerializeToString(), cls(x=9).SerializeToString()])
        result = _run(runner, ["storage", "scan", str(data), "--desc", str(desc), "--type", "a.A"])
        assert result.exit_code == 0
        assert result.output.count("# stream=") == 2
        assert "x: 7" in result.output and "x: 9" in result.output

    def test_json_is_compact_jsonl(
        self,
        runner: CliRunner,
        desc_and_cls: tuple[Path, type],
        data_file_factory: Callable[..., Path],
    ) -> None:
        desc, cls = desc_and_cls
        data = data_file_factory([cls(x=7).SerializeToString(), cls(x=9).SerializeToString()])
        result = _run(runner, cmd("scan", data, desc, "--format", "json"))
        assert result.exit_code == 0
        lines = [ln for ln in result.output.splitlines() if ln.strip()]
        assert len(lines) == 2  # one object per line
        assert [json.loads(ln) for ln in lines] == [{"x": 7}, {"x": 9}]

    def test_where_filters(
        self,
        runner: CliRunner,
        desc_and_cls: tuple[Path, type],
        data_file_factory: Callable[..., Path],
    ) -> None:
        desc, cls = desc_and_cls
        data = data_file_factory([cls(x=v).SerializeToString() for v in (1, 7, 7)])
        result = _run(runner, cmd("scan", data, desc, "--where", "x == 7"))
        assert result.exit_code == 0
        assert result.output.count("# stream=") == 2


class TestScanEdgeInputs:
    def test_empty_file_yields_nothing(
        self,
        runner: CliRunner,
        desc_and_cls: tuple[Path, type],
        data_file_factory: Callable[..., Path],
    ) -> None:
        desc, _cls = desc_and_cls
        data = data_file_factory([])  # zero frames
        result = _run(runner, ["storage", "scan", str(data), "--desc", str(desc), "--type", "a.A"])
        assert result.exit_code == 0
        assert "# stream=" not in result.output

    def test_zero_match_where_yields_nothing(
        self,
        runner: CliRunner,
        desc_and_cls: tuple[Path, type],
        data_file_factory: Callable[..., Path],
    ) -> None:
        desc, cls = desc_and_cls
        data = data_file_factory([cls(x=1).SerializeToString()])
        result = _run(runner, cmd("scan", data, desc, "--where", "x == 999"))
        assert result.exit_code == 0
        assert "# stream=" not in result.output

    def test_garbage_file_under_raise_is_clean_exit_2(
        self,
        runner: CliRunner,
        desc_and_cls: tuple[Path, type],
        raw_file_factory: Callable[..., Path],
    ) -> None:
        desc, _cls = desc_and_cls
        garbage = raw_file_factory(b"this is not a length-delimited proto stream\n")
        result = _run(runner, cmd("scan", garbage, desc))
        assert result.exit_code == 2
        assert "Error:" in result.stderr
