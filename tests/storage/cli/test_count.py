"""``protokit storage count`` — count, the zero case, --quiet grep-like exit, --where."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from click.testing import CliRunner

from protokit.cli import main
from tests.storage.cli.conftest import cmd


def _run(runner: CliRunner, args: list[str]):  # noqa: ANN202
    return runner.invoke(main, args, catch_exceptions=False)


def test_count_prints_number(
    runner: CliRunner,
    desc_and_cls: tuple[Path, type],
    data_file_factory: Callable[..., Path],
) -> None:
    desc, cls = desc_and_cls
    data = data_file_factory([cls(x=i).SerializeToString() for i in range(3)])
    result = _run(runner, ["storage", "count", str(data), "--desc", str(desc), "--type", "a.A"])
    assert result.exit_code == 0
    assert result.output.strip() == "3"


def test_count_zero_is_exit_0_and_prints_zero(
    runner: CliRunner,
    desc_and_cls: tuple[Path, type],
    data_file_factory: Callable[..., Path],
) -> None:
    desc, _cls = desc_and_cls
    data = data_file_factory([])  # empty -> count 0 is a valid result, not an error
    result = _run(runner, ["storage", "count", str(data), "--desc", str(desc), "--type", "a.A"])
    assert result.exit_code == 0
    assert result.output.strip() == "0"


def test_count_quiet_zero_matches_exits_1(
    runner: CliRunner,
    desc_and_cls: tuple[Path, type],
    data_file_factory: Callable[..., Path],
) -> None:
    desc, cls = desc_and_cls
    data = data_file_factory([cls(x=1).SerializeToString()])
    result = _run(runner, cmd("count", data, desc, "--where", "x == 999", "--quiet"))
    assert result.exit_code == 1  # grep-like: no match
    assert result.output.strip() == ""  # quiet suppresses the number


def test_count_quiet_with_matches_exits_0_no_output(
    runner: CliRunner,
    desc_and_cls: tuple[Path, type],
    data_file_factory: Callable[..., Path],
) -> None:
    desc, cls = desc_and_cls
    data = data_file_factory([cls(x=7).SerializeToString()])
    result = _run(
        runner,
        ["storage", "count", str(data), "--desc", str(desc), "--type", "a.A", "-q"],
    )
    assert result.exit_code == 0
    assert result.output.strip() == ""


def test_count_with_where(
    runner: CliRunner,
    desc_and_cls: tuple[Path, type],
    data_file_factory: Callable[..., Path],
) -> None:
    desc, cls = desc_and_cls
    data = data_file_factory(
        [cls(x=7).SerializeToString(), cls(x=1).SerializeToString(), cls(x=7).SerializeToString()]
    )
    result = _run(
        runner,
        ["storage", "count", str(data), "--desc", str(desc), "--type", "a.A", "--where", "x == 7"],
    )
    assert result.exit_code == 0
    assert result.output.strip() == "2"
