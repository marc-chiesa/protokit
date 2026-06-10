"""Up-front rejection surface for ``--format parquet`` (extra-independent).

Nothing here imports ptars/pyarrow, so the module runs identically on the
with-extra and no-extra CI axes. The missing-extra cases stub the
``find_spec`` probes deterministically — every probe the guard reads is faked
(per the ordered-preflight-guard learning) — and the env-dependent cases (the
explicit-flag-wins test, the guard-ordering pin) stub the extra ABSENT so
their outcome never depends on the local install.

Every rejection here is the up-front ``_prepare`` contract: exit 2,
``Error:`` on stderr, nothing on stdout, and the output file never created —
firing even on an empty data file.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from protokit.cli import main
from tests.storage.cli.conftest import cmd, pq_cmd


def _run(runner: CliRunner, args: list[str], env: dict[str, str] | None = None):  # noqa: ANN202
    return runner.invoke(main, args, env=env, catch_exceptions=False)


def _stub_probes(monkeypatch: pytest.MonkeyPatch, *, ptars: bool, pyarrow: bool) -> None:
    """Fake every probe the parquet extra guard reads, deterministically.

    Other ``find_spec`` lookups delegate to the real function so unrelated
    machinery inside the CLI invocation keeps working.
    """
    real = importlib.util.find_spec
    state = {"ptars": ptars, "pyarrow": pyarrow}

    def fake(name: str, *a: object, **k: object) -> object | None:
        if name in state:
            return object() if state[name] else None
        return real(name, *a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(importlib.util, "find_spec", fake)


@pytest.fixture
def data_and_desc(
    desc_and_cls: tuple[Path, type], data_file_factory: Callable[..., Path]
) -> tuple[Path, Path]:
    """One-record ``a.A`` data file plus its descriptor set path."""
    desc, cls = desc_and_cls
    data = data_file_factory([cls(x=1).SerializeToString()])
    return data, desc


def _reject(result: Result, out: Path | None = None) -> None:
    """Assert the shared up-front rejection contract."""
    assert result.exit_code == 2
    assert "Error:" in result.stderr
    assert result.stdout == ""
    if out is not None:
        assert not out.exists()


class TestParquetRequiresOutput:
    def test_ae1_no_output_rejected(
        self, runner: CliRunner, data_and_desc: tuple[Path, Path]
    ) -> None:
        data, desc = data_and_desc
        result = _run(runner, cmd("scan", data, desc, "--format", "parquet"))
        _reject(result)
        assert "--output" in result.stderr

    def test_ae1_rejected_even_on_empty_file(
        self,
        runner: CliRunner,
        desc_and_cls: tuple[Path, type],
        data_file_factory: Callable[..., Path],
    ) -> None:
        # The guard fires before any record is read: an empty data file must
        # not turn the missing -o into a silent no-op.
        desc, _cls = desc_and_cls
        data = data_file_factory([])
        result = _run(runner, cmd("scan", data, desc, "--format", "parquet"))
        _reject(result)
        assert "--output" in result.stderr


class TestOutputRequiresParquet:
    def test_r11_output_with_json_rejected(
        self, runner: CliRunner, data_and_desc: tuple[Path, Path], tmp_path: Path
    ) -> None:
        data, desc = data_and_desc
        out = tmp_path / "out.parquet"
        result = _run(runner, cmd("scan", data, desc, "--format", "json", "-o", str(out)))
        _reject(result, out)
        assert "--output" in result.stderr

    def test_r11_output_with_default_format_rejected(
        self, runner: CliRunner, data_and_desc: tuple[Path, Path], tmp_path: Path
    ) -> None:
        data, desc = data_and_desc
        out = tmp_path / "out.parquet"
        result = _run(runner, cmd("scan", data, desc, "-o", str(out)))
        _reject(result, out)
        assert "--output" in result.stderr


class TestTolerantModesRejected:
    @pytest.mark.parametrize("mode", ["skip", "warn"])
    def test_ae2_tolerant_mode_rejected_up_front(
        self,
        runner: CliRunner,
        data_and_desc: tuple[Path, Path],
        tmp_path: Path,
        mode: str,
    ) -> None:
        data, desc = data_and_desc
        out = tmp_path / "out.parquet"
        result = _run(runner, pq_cmd(data, desc, out, "--on-error", mode))
        _reject(result, out)
        assert "--on-error" in result.stderr


class TestProjectionFlagsRejected:
    def test_r12_fields_rejected(
        self, runner: CliRunner, data_and_desc: tuple[Path, Path], tmp_path: Path
    ) -> None:
        data, desc = data_and_desc
        out = tmp_path / "out.parquet"
        result = _run(runner, pq_cmd(data, desc, out, "--fields", "x"))
        _reject(result, out)
        assert "--fields" in result.stderr

    def test_r13_explicit_defaults_rejected(
        self, runner: CliRunner, data_and_desc: tuple[Path, Path], tmp_path: Path
    ) -> None:
        # The JSON-only guard generalizes: parquet is not JSON either.
        data, desc = data_and_desc
        out = tmp_path / "out.parquet"
        result = _run(runner, pq_cmd(data, desc, out, "--explicit-defaults"))
        _reject(result, out)
        assert "--explicit-defaults" in result.stderr
        assert "json" in result.stderr.lower()


class TestScanOnly:
    def test_ae4_head_format_parquet_invalid_choice(
        self, runner: CliRunner, data_and_desc: tuple[Path, Path]
    ) -> None:
        # head keeps the two-value choice, so Click itself rejects parquet.
        data, desc = data_and_desc
        result = _run(runner, cmd("head", data, desc, "--format", "parquet"))
        _reject(result)
        assert "parquet" in result.stderr

    def test_ae4_head_env_parquet_invalid_choice(
        self, runner: CliRunner, data_and_desc: tuple[Path, Path]
    ) -> None:
        # The shared PROTOKIT_FORMAT envvar feeds head's Choice too — an
        # env-sourced parquet is rejected at parse, same as the flag form.
        data, desc = data_and_desc
        result = _run(runner, cmd("head", data, desc), env={"PROTOKIT_FORMAT": "parquet"})
        _reject(result)
        assert "parquet" in result.stderr

    def test_ae4_count_has_no_format_option(
        self, runner: CliRunner, data_and_desc: tuple[Path, Path]
    ) -> None:
        data, desc = data_and_desc
        result = _run(runner, cmd("count", data, desc, "--format", "parquet"))
        _reject(result)
        assert "No such option" in result.stderr

    @pytest.mark.parametrize("sub", ["head", "count"])
    def test_head_count_have_no_output_option(
        self, runner: CliRunner, data_and_desc: tuple[Path, Path], sub: str
    ) -> None:
        data, desc = data_and_desc
        result = _run(runner, cmd(sub, data, desc, "--output", "x.parquet"))
        _reject(result)
        assert "No such option" in result.stderr


class TestEnvSourcedParquetRejected:
    def test_r14_env_parquet_rejected_on_scan(
        self, runner: CliRunner, data_and_desc: tuple[Path, Path], tmp_path: Path
    ) -> None:
        # File-writing output must be explicit per invocation: parquet is
        # accepted only when --format comes from the command line.
        data, desc = data_and_desc
        out = tmp_path / "out.parquet"
        result = _run(
            runner,
            cmd("scan", data, desc, "-o", str(out)),
            env={"PROTOKIT_FORMAT": "parquet"},
        )
        _reject(result, out)
        assert "PROTOKIT_FORMAT" in result.stderr

    def test_r14_explicit_flag_wins_over_env(
        self,
        runner: CliRunner,
        data_and_desc: tuple[Path, Path],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # With --format parquet typed explicitly, the source guard passes even
        # when the envvar is also set. The extra is stubbed ABSENT so the flow
        # provably reaches the probe (and the test behaves identically on the
        # with-extra and no-extra CI axes).
        _stub_probes(monkeypatch, ptars=False, pyarrow=False)
        data, desc = data_and_desc
        out = tmp_path / "out.parquet"
        result = _run(runner, pq_cmd(data, desc, out), env={"PROTOKIT_FORMAT": "parquet"})
        _reject(result, out)
        assert "protokit[parquet]" in result.stderr
        assert "PROTOKIT_FORMAT" not in result.stderr


class TestOutputInputCollisionRejected:
    def test_output_equal_to_data_file_rejected(
        self, runner: CliRunner, data_and_desc: tuple[Path, Path]
    ) -> None:
        # The publish step replaces the output path on success — pointing -o
        # at the input would destroy the just-read source. Rejected up front.
        data, desc = data_and_desc
        before = data.read_bytes()
        result = _run(runner, pq_cmd(data, desc, data))
        _reject(result)
        assert "--output" in result.stderr
        assert data.read_bytes() == before

    def test_output_equal_to_desc_rejected(
        self, runner: CliRunner, data_and_desc: tuple[Path, Path]
    ) -> None:
        data, desc = data_and_desc
        before = desc.read_bytes()
        result = _run(runner, pq_cmd(data, desc, desc))
        _reject(result)
        assert desc.read_bytes() == before


class TestStdoutDashRejected:
    def test_r15_output_dash_rejected(
        self, runner: CliRunner, data_and_desc: tuple[Path, Path]
    ) -> None:
        # Parquet needs a seekable file; '-' would create a literal file named
        # '-' rather than streaming to stdout. Reject it honestly.
        data, desc = data_and_desc
        result = _run(runner, pq_cmd(data, desc, "-"))
        _reject(result)
        assert "'-'" in result.stderr
        assert not Path("-").exists()


class TestMissingExtra:
    def test_r5_missing_ptars_exit_2(
        self,
        runner: CliRunner,
        data_and_desc: tuple[Path, Path],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_probes(monkeypatch, ptars=False, pyarrow=False)
        data, desc = data_and_desc
        out = tmp_path / "out.parquet"
        result = _run(runner, pq_cmd(data, desc, out))
        _reject(result, out)
        assert "protokit[parquet]" in result.stderr

    def test_r5_missing_pyarrow_named(
        self,
        runner: CliRunner,
        data_and_desc: tuple[Path, Path],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # ptars faked present so the guard, which probes ptars first, reports
        # pyarrow — independent of whether the extra is installed locally.
        _stub_probes(monkeypatch, ptars=True, pyarrow=False)
        data, desc = data_and_desc
        out = tmp_path / "out.parquet"
        result = _run(runner, pq_cmd(data, desc, out))
        _reject(result, out)
        assert "pyarrow" in result.stderr

    def test_flag_guards_precede_extra_probe(
        self,
        runner: CliRunner,
        data_and_desc: tuple[Path, Path],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Misuse rejection must not depend on the environment: with the extra
        # stubbed absent, a flag conflict still reports the flag conflict.
        _stub_probes(monkeypatch, ptars=False, pyarrow=False)
        data, desc = data_and_desc
        out = tmp_path / "out.parquet"
        result = _run(runner, pq_cmd(data, desc, out, "--on-error", "skip"))
        _reject(result, out)
        assert "--on-error" in result.stderr
        assert "protokit[parquet]" not in result.stderr
