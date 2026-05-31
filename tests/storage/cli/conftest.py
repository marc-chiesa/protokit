"""Shared fixtures for the ``protokit storage`` CLI tests.

The CLI is invoked through the top-level group (``protokit.cli.main``) so the
``storage`` group registration is exercised, with ``catch_exceptions=False`` so a
crash surfaces as a real exception rather than a masked ``exit_code=1`` + empty
stdout (per the clirunner-catch-exceptions-false learning).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from click.testing import CliRunner

from protokit.storage.schema_source import FileDescriptorSetSchema
from tests.storage.proto_fixtures import delimited, fds, file_proto


def a_fds() -> object:
    """A FileDescriptorSet for ``a.A { int32 x = 1 }`` — the common CLI fixture."""
    return fds(file_proto("a.proto", "a", message="A"))


def cmd(subcommand: str, data: Path, desc: Path, *extra: str) -> list[str]:
    """Build a ``protokit storage <subcommand>`` argv over ``a.A`` (data, desc).

    Keeps the many invocations short and under the line-length limit; the schema
    flag tests that exercise non-standard flag combinations build argv inline.
    """
    return [
        "storage",
        subcommand,
        str(data),
        "--desc",
        str(desc),
        "--type",
        "a.A",
        *extra,
    ]


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def desc_and_cls(tmp_path: Path) -> tuple[Path, type]:
    """Write ``a.A``'s descriptor set to disk; return ``(desc_path, message_class)``."""
    f = a_fds()
    desc = tmp_path / "a.desc"
    desc.write_bytes(f.SerializeToString())  # type: ignore[attr-defined]
    cls = FileDescriptorSetSchema(f, "a.A").resolve().message_class  # type: ignore[arg-type]
    return desc, cls


@pytest.fixture
def data_file_factory(tmp_path: Path) -> Callable[..., Path]:
    """Factory: write a length-delimited file from message payloads."""

    def make(payloads: list[bytes], name: str = "data.bin") -> Path:
        p = tmp_path / name
        p.write_bytes(delimited(*payloads))
        return p

    return make


@pytest.fixture
def raw_file_factory(tmp_path: Path) -> Callable[..., Path]:
    """Factory: write raw bytes (for garbage / hand-built framing tests)."""

    def make(raw: bytes, name: str = "raw.bin") -> Path:
        p = tmp_path / name
        p.write_bytes(raw)
        return p

    return make
