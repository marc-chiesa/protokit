"""``protokit storage head`` — -n limit, including the 0 and negative boundaries."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from click.testing import CliRunner

from protokit.cli import main
from tests.storage.cli.conftest import cmd


def _run(runner: CliRunner, args: list[str]):  # noqa: ANN202
    return runner.invoke(main, args, catch_exceptions=False)


def _records(cls: type, n: int) -> list[bytes]:
    return [cls(x=i).SerializeToString() for i in range(n)]


def test_head_limits_to_n(
    runner: CliRunner,
    desc_and_cls: tuple[Path, type],
    data_file_factory: Callable[..., Path],
) -> None:
    desc, cls = desc_and_cls
    data = data_file_factory(_records(cls, 5))
    result = _run(runner, cmd("head", data, desc, "-n", "2"))
    assert result.exit_code == 0
    assert result.output.count("# stream=") == 2


def test_head_n_zero_shows_nothing(
    runner: CliRunner,
    desc_and_cls: tuple[Path, type],
    data_file_factory: Callable[..., Path],
) -> None:
    desc, cls = desc_and_cls
    data = data_file_factory(_records(cls, 3))
    result = _run(runner, cmd("head", data, desc, "-n", "0"))
    assert result.exit_code == 0
    assert "# stream=" not in result.output


def test_head_negative_n_is_usage_error(
    runner: CliRunner,
    desc_and_cls: tuple[Path, type],
    data_file_factory: Callable[..., Path],
) -> None:
    desc, cls = desc_and_cls
    data = data_file_factory(_records(cls, 3))
    result = _run(runner, cmd("head", data, desc, "-n", "-1"))
    assert result.exit_code == 2  # Click IntRange(min=0) UsageError


def test_head_n_greater_than_available_shows_all(
    runner: CliRunner,
    desc_and_cls: tuple[Path, type],
    data_file_factory: Callable[..., Path],
) -> None:
    desc, cls = desc_and_cls
    data = data_file_factory(_records(cls, 2))
    result = _run(runner, cmd("head", data, desc, "-n", "10"))
    assert result.exit_code == 0
    assert result.output.count("# stream=") == 2
