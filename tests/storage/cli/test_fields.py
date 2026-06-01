"""``protokit storage scan/head --fields`` — end-to-end CLI field selection (U3).

Mirrors ``test_scan.py``'s conventions: the top-level ``protokit.cli.main`` is
invoked through ``CliRunner`` with ``catch_exceptions=False`` so a crash surfaces
as a real exception (not a masked ``exit_code=1``), and failures assert on both
stdout and stderr (the exit-code-discipline learning).

The fixture proto is a single rich ``.proto`` compiled once via
``ProtoFileSchema`` (the ``test_project.py`` / ``test_schema_flags.py`` pattern):
a nested ``Header`` submessage with a no-presence scalar (``code``), a
``source``-like scalar, a proto3 ``optional`` scalar (``opt``), a singular
submessage (``header``), and a ``oneof`` — covering the presence classes AE1/AE6
exercise.
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

    d = Path(tempfile.mkdtemp(prefix="cli_fields_"))
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


class TestScanFieldsJson:
    def test_ae1_no_presence_scalar_under_present_parent_shown(
        self,
        runner: CliRunner,
        event_cls: type,
        proto_file: Path,
        data_file_factory: Callable[..., Path],
    ) -> None:
        # header is present, header.code is a no-presence scalar at its default 0.
        m = event_cls(source="svc")
        m.header.SetInParent()  # present, code stays at 0
        data = data_file_factory([m.SerializeToString()])
        result = _run(
            runner,
            _argv("scan", data, proto_file, "--fields", "header.code,source", "--format", "json"),
        )
        assert result.exit_code == 0, result.stderr
        rows = _jsonl(result.output)
        assert rows == [{"header": {"code": 0}, "source": "svc"}]
        # snake_case key; unselected fields (n, opt, etc.) excluded.
        assert "n" not in rows[0]
        assert "internal_flag" not in rows[0]

    def test_ae6_presence_bearing_by_presence_unset_omitted(
        self,
        runner: CliRunner,
        event_cls: type,
        proto_file: Path,
        data_file_factory: Callable[..., Path],
    ) -> None:
        # Nothing set: opt (optional), the oneof member a, and header (submessage)
        # are all presence-bearing and unset -> omitted, NOT fabricated.
        data = data_file_factory([event_cls().SerializeToString()])
        result = _run(
            runner,
            _argv(
                "scan",
                data,
                proto_file,
                "--fields",
                "opt,a,header.code",
                "--format",
                "json",
            ),
        )
        assert result.exit_code == 0, result.stderr
        assert _jsonl(result.output) == [{}]

    def test_ae6_presence_bearing_set_appears(
        self,
        runner: CliRunner,
        event_cls: type,
        proto_file: Path,
        data_file_factory: Callable[..., Path],
    ) -> None:
        # When the presence-bearing fields ARE set (opt at its default, the oneof
        # active), they appear; the inactive oneof member stays omitted.
        m = event_cls()
        m.opt = 0
        m.a = 5
        data = data_file_factory([m.SerializeToString()])
        result = _run(
            runner,
            _argv("scan", data, proto_file, "--fields", "opt,a,b", "--format", "json"),
        )
        assert result.exit_code == 0, result.stderr
        assert _jsonl(result.output) == [{"opt": 0, "a": 5}]

    def test_ae2_where_on_unselected_field_then_project(
        self,
        runner: CliRunner,
        event_cls: type,
        proto_file: Path,
        data_file_factory: Callable[..., Path],
    ) -> None:
        # --where filters on internal_flag (unselected); --fields emits only source.
        m_keep = event_cls(source="keep", internal_flag=True)
        m_drop = event_cls(source="drop", internal_flag=False)
        data = data_file_factory(
            [m_keep.SerializeToString(), m_drop.SerializeToString()]
        )
        result = _run(
            runner,
            _argv(
                "scan",
                data,
                proto_file,
                "--fields",
                "source",
                "--where",
                "internal_flag == true",
                "--format",
                "json",
            ),
        )
        assert result.exit_code == 0, result.stderr
        rows = _jsonl(result.output)
        assert rows == [{"source": "keep"}]
        assert "internal_flag" not in rows[0]


class TestHeadFields:
    def test_head_n_truncates_with_fields(
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
            _argv("head", data, proto_file, "-n", "2", "--fields", "source", "--format", "json"),
        )
        assert result.exit_code == 0, result.stderr
        rows = _jsonl(result.output)
        assert rows == [{"source": "s0"}, {"source": "s1"}]


class TestCountRejectsFields:
    def test_count_has_no_fields_option(
        self,
        runner: CliRunner,
        event_cls: type,
        proto_file: Path,
        data_file_factory: Callable[..., Path],
    ) -> None:
        # R1: count does not accept --fields; Click rejects the unknown option.
        data = data_file_factory([event_cls().SerializeToString()])
        result = _run(runner, _argv("count", data, proto_file, "--fields", "source"))
        assert result.exit_code == 2
        assert "No such option" in result.stderr
        assert "--fields" in result.stderr
        assert result.stdout == ""  # no count printed


class TestInvalidFields:
    def test_ae5_unknown_field_path_is_exit_2(
        self,
        runner: CliRunner,
        event_cls: type,
        proto_file: Path,
        data_file_factory: Callable[..., Path],
    ) -> None:
        data = data_file_factory([event_cls().SerializeToString()])
        result = _run(
            runner,
            _argv("scan", data, proto_file, "--fields", "nope", "--format", "json"),
        )
        assert result.exit_code == 2
        assert "Error:" in result.stderr
        assert "no field 'nope'" in result.stderr
        # Up-front failure: no records rendered to stdout.
        assert result.stdout == ""

    def test_descend_into_scalar_is_exit_2(
        self,
        runner: CliRunner,
        event_cls: type,
        proto_file: Path,
        data_file_factory: Callable[..., Path],
    ) -> None:
        data = data_file_factory([event_cls().SerializeToString()])
        result = _run(
            runner,
            _argv("scan", data, proto_file, "--fields", "source.x", "--format", "json"),
        )
        assert result.exit_code == 2
        assert "Error:" in result.stderr
        assert "descend into scalar" in result.stderr


class TestHumanFields:
    def test_r13_human_shows_default_valued_no_presence_field(
        self,
        runner: CliRunner,
        event_cls: type,
        proto_file: Path,
        data_file_factory: Callable[..., Path],
    ) -> None:
        # The footgun fix in human mode: a selected no-presence scalar at its
        # default (header.code == 0 under a present header) MUST appear.
        m = event_cls()
        m.header.SetInParent()
        data = data_file_factory([m.SerializeToString()])
        result = _run(
            runner,
            _argv("scan", data, proto_file, "--fields", "header.code", "--format", "human"),
        )
        assert result.exit_code == 0, result.stderr
        # path: value line with the dotted path preserved, default value present.
        assert "header.code: 0" in result.output
        # The record header is kept, consistent with full-record human output.
        assert "# stream=" in result.output

    def test_human_multiple_paths_and_scalar(
        self,
        runner: CliRunner,
        event_cls: type,
        proto_file: Path,
        data_file_factory: Callable[..., Path],
    ) -> None:
        m = event_cls(source="svc", n=7)
        m.header.code = 3
        data = data_file_factory([m.SerializeToString()])
        result = _run(
            runner,
            _argv(
                "scan",
                data,
                proto_file,
                "--fields",
                "header.code,source,n",
                "--format",
                "human",
            ),
        )
        assert result.exit_code == 0, result.stderr
        assert "header.code: 3" in result.output
        assert "source: svc" in result.output
        assert "n: 7" in result.output
