"""``protokit storage scan/head --explicit-defaults`` — dense full-record JSON (U4).

Mirrors ``test_fields.py``/``test_scan.py`` conventions: the top-level
``protokit.cli.main`` is invoked through ``CliRunner`` with
``catch_exceptions=False`` so a crash surfaces as a real exception (not a masked
``exit_code=1``), and failures assert on both stdout and stderr (the
exit-code-discipline learning; per the Click 8.3 note, ``result.stdout`` and
``result.stderr`` are separate streams).

``--explicit-defaults`` is a JSON-only density flag (R7/R8/R9/R10/R14): with
``--format json`` it fills no-presence fields at their default and leaves
presence-bearing fields by presence, in *camelCase* — a density variant of the
shipped PR1.5 JSON. The fixture carries an ``error_code`` no-presence scalar and
an ``opt`` proto3 ``optional`` so AE3 can assert the camelCase fill (``errorCode``)
and the absent presence-bearing field on the same record, and so the casing
contrast against the snake_case ``--fields`` view (U3) is exercised on the same
underlying field.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from click.testing import CliRunner

from protokit.cli import main
from protokit.storage.schema_source import ProtoFileSchema

_PROTO = """\
syntax = "proto3";
package demo;

message Header {
  int32 code = 1;
}

message Event {
  Header header = 1;
  string source = 2;
  int32 n = 3;
  optional int32 opt = 4;
  bool internal_flag = 5;
  int32 error_code = 8;
  oneof choice {
    int32 a = 6;
    string b = 7;
  }
}
"""


def _run(runner: CliRunner, args: list[str]):  # noqa: ANN202
    return runner.invoke(main, args, catch_exceptions=False)


@pytest.fixture(scope="module")
def event_cls() -> type:
    import tempfile

    d = Path(tempfile.mkdtemp(prefix="cli_explicit_defaults_"))
    p = d / "event.proto"
    p.write_text(_PROTO)
    return ProtoFileSchema(p, "demo.Event").resolve().message_class


@pytest.fixture
def proto_file(tmp_path: Path) -> Path:
    p = tmp_path / "event.proto"
    p.write_text(_PROTO)
    return p


def _argv(sub: str, data: Path, proto: Path, *extra: str) -> list[str]:
    return [
        "storage",
        sub,
        str(data),
        "--proto",
        str(proto),
        "--type",
        "demo.Event",
        *extra,
    ]


def _jsonl(output: str) -> list[dict]:
    return [json.loads(ln) for ln in output.splitlines() if ln.strip()]


class TestExplicitDefaultsJson:
    def test_ae3_dense_fills_no_presence_omits_presence_bearing(
        self,
        runner: CliRunner,
        event_cls: type,
        proto_file: Path,
        data_file_factory: Callable[..., Path],
    ) -> None:
        # source set; error_code/n/internal_flag are no-presence scalars at their
        # default; opt (optional) and the oneof are presence-bearing and unset.
        m = event_cls(source="svc")
        data = data_file_factory([m.SerializeToString()])
        result = _run(
            runner,
            _argv(
                "scan", data, proto_file, "--format", "json", "--explicit-defaults"
            ),
        )
        assert result.exit_code == 0, result.stderr
        rows = _jsonl(result.output)
        assert len(rows) == 1
        row = rows[0]
        # R7: every no-presence field present at its default, keys camelCase (R10/KTD4).
        assert row["errorCode"] == 0
        assert row["n"] == 0
        assert row["internalFlag"] is False
        assert row["source"] == "svc"
        # presence-bearing fields stay absent (never fabricated).
        assert "opt" not in row
        assert "a" not in row and "b" not in row
        # header (singular submessage, presence-bearing) is unset -> absent.
        assert "header" not in row
        # camelCase, not snake_case: error_code surfaces as errorCode only.
        assert "error_code" not in row
        assert "internal_flag" not in row

    def test_ae3_without_flag_byte_compatible_with_pr15(
        self,
        runner: CliRunner,
        event_cls: type,
        proto_file: Path,
        data_file_factory: Callable[..., Path],
    ) -> None:
        # R8: without the flag, full-record JSON is the shipped PR1.5 output —
        # defaults omitted, camelCase. Same record as the dense test above.
        m = event_cls(source="svc")
        data = data_file_factory([m.SerializeToString()])
        plain = _run(
            runner, _argv("scan", data, proto_file, "--format", "json")
        )
        assert plain.exit_code == 0, plain.stderr
        plain_rows = _jsonl(plain.output)
        # Defaults omitted: only the explicitly-set field survives.
        assert plain_rows == [{"source": "svc"}]
        # And the dense variant is strictly denser (a superset of keys).
        dense = _run(
            runner,
            _argv(
                "scan", data, proto_file, "--format", "json", "--explicit-defaults"
            ),
        )
        assert dense.exit_code == 0, dense.stderr
        dense_keys = set(_jsonl(dense.output)[0])
        assert set(plain_rows[0]).issubset(dense_keys)
        assert {"errorCode", "n", "internalFlag"} <= dense_keys

    def test_set_optional_at_default_appears_dense(
        self,
        runner: CliRunner,
        event_cls: type,
        proto_file: Path,
        data_file_factory: Callable[..., Path],
    ) -> None:
        # A *set* presence-bearing field at its default value IS shown (presence,
        # not value). The dense fill does not change that.
        m = event_cls(source="svc")
        m.opt = 0
        data = data_file_factory([m.SerializeToString()])
        result = _run(
            runner,
            _argv(
                "scan", data, proto_file, "--format", "json", "--explicit-defaults"
            ),
        )
        assert result.exit_code == 0, result.stderr
        assert _jsonl(result.output)[0]["opt"] == 0


class TestExplicitDefaultsHead:
    def test_head_n_truncates_dense(
        self,
        runner: CliRunner,
        event_cls: type,
        proto_file: Path,
        data_file_factory: Callable[..., Path],
    ) -> None:
        data = data_file_factory(
            [event_cls(source=f"s{i}").SerializeToString() for i in range(5)]
        )
        result = _run(
            runner,
            _argv(
                "head",
                data,
                proto_file,
                "-n",
                "2",
                "--format",
                "json",
                "--explicit-defaults",
            ),
        )
        assert result.exit_code == 0, result.stderr
        rows = _jsonl(result.output)
        assert len(rows) == 2
        assert [r["source"] for r in rows] == ["s0", "s1"]
        # Dense even when headed: no-presence default filled.
        assert all(r["errorCode"] == 0 for r in rows)


class TestExplicitDefaultsHumanRejected:
    def test_r9_human_format_is_clean_exit_2(
        self,
        runner: CliRunner,
        event_cls: type,
        proto_file: Path,
        data_file_factory: Callable[..., Path],
    ) -> None:
        # R9: --explicit-defaults is JSON only; under --format human it is a clean
        # error (exit 2), NOT a silent no-op.
        data = data_file_factory([event_cls(source="svc").SerializeToString()])
        result = _run(
            runner,
            _argv(
                "scan", data, proto_file, "--format", "human", "--explicit-defaults"
            ),
        )
        assert result.exit_code == 2
        assert "Error:" in result.stderr
        assert "--explicit-defaults" in result.stderr
        assert "json" in result.stderr.lower()
        # Up-front failure: no records rendered to stdout (not a no-op pass).
        assert result.stdout == ""

    def test_r9_human_default_format_is_clean_exit_2(
        self,
        runner: CliRunner,
        event_cls: type,
        proto_file: Path,
        data_file_factory: Callable[..., Path],
    ) -> None:
        # The default format is human, so --explicit-defaults with no --format
        # flag is also rejected (not silently rendered human / silently ignored).
        data = data_file_factory([event_cls(source="svc").SerializeToString()])
        result = _run(
            runner, _argv("scan", data, proto_file, "--explicit-defaults")
        )
        assert result.exit_code == 2
        assert "Error:" in result.stderr
        assert "--explicit-defaults" in result.stderr
        assert result.stdout == ""

    def test_r9_rejected_even_on_empty_file(
        self,
        runner: CliRunner,
        event_cls: type,
        proto_file: Path,
        data_file_factory: Callable[..., Path],
    ) -> None:
        # R9 must fail up front, independent of record count: an empty data file
        # must NOT make --explicit-defaults --format human a silent no-op.
        data = data_file_factory([])  # zero frames
        result = _run(
            runner,
            _argv(
                "scan", data, proto_file, "--format", "human", "--explicit-defaults"
            ),
        )
        assert result.exit_code == 2
        assert "--explicit-defaults" in result.stderr
        assert result.stdout == ""


class TestExplicitDefaultsMutualExclusion:
    def test_r14_with_fields_is_clean_exit_2(
        self,
        runner: CliRunner,
        event_cls: type,
        proto_file: Path,
        data_file_factory: Callable[..., Path],
    ) -> None:
        # R14: --explicit-defaults and --fields are mutually exclusive.
        data = data_file_factory([event_cls(source="svc").SerializeToString()])
        result = _run(
            runner,
            _argv(
                "scan",
                data,
                proto_file,
                "--format",
                "json",
                "--explicit-defaults",
                "--fields",
                "source",
            ),
        )
        assert result.exit_code == 2
        assert "Error:" in result.stderr
        assert "mutually exclusive" in result.stderr
        assert "--fields" in result.stderr
        assert "--explicit-defaults" in result.stderr
        assert result.stdout == ""


class TestExplicitDefaultsKeyCasingContrast:
    def test_explicit_defaults_camelcase_vs_fields_snakecase(
        self,
        runner: CliRunner,
        event_cls: type,
        proto_file: Path,
        data_file_factory: Callable[..., Path],
    ) -> None:
        # Same underlying no-presence scalar (error_code) at its default 0:
        # --explicit-defaults emits camelCase (errorCode); --fields emits
        # snake_case (error_code) — the R10/KTD4 casing distinction.
        m = event_cls(source="svc")
        data = data_file_factory([m.SerializeToString()])

        dense = _run(
            runner,
            _argv(
                "scan", data, proto_file, "--format", "json", "--explicit-defaults"
            ),
        )
        assert dense.exit_code == 0, dense.stderr
        dense_row = _jsonl(dense.output)[0]
        assert "errorCode" in dense_row
        assert "error_code" not in dense_row

        fields = _run(
            runner,
            _argv(
                "scan",
                data,
                proto_file,
                "--format",
                "json",
                "--fields",
                "error_code",
            ),
        )
        assert fields.exit_code == 0, fields.stderr
        fields_row = _jsonl(fields.output)[0]
        assert fields_row == {"error_code": 0}
        assert "errorCode" not in fields_row


class TestCountRejectsExplicitDefaults:
    def test_count_has_no_explicit_defaults_option(
        self,
        runner: CliRunner,
        event_cls: type,
        proto_file: Path,
        data_file_factory: Callable[..., Path],
    ) -> None:
        # count never accepts --explicit-defaults (kept off, like --fields);
        # Click rejects the unknown option with exit 2.
        data = data_file_factory([event_cls(source="svc").SerializeToString()])
        result = _run(
            runner, _argv("count", data, proto_file, "--explicit-defaults")
        )
        assert result.exit_code == 2
        assert "No such option" in result.stderr
        assert "--explicit-defaults" in result.stderr
        assert result.stdout == ""  # no count printed
