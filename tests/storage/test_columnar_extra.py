"""Extra-guard tests (PR3 U2 / R9 / AE6).

Deliberately does NOT ``importorskip`` ptars/pyarrow: it tests the
extra-absent error path, which must run even on an environment without the
``[parquet]`` extra. ``_columnar`` imports ptars/pyarrow lazily (inside
functions), so the module imports fine without the extra; absence is simulated
by monkeypatching ``importlib.util.find_spec``.
"""

from __future__ import annotations

import importlib.util

import pytest

from protokit.storage import ParquetExtraNotInstalledError, _columnar
from protokit.storage.registry import StreamRegistry
from protokit.storage.schema_source import FileDescriptorSetSchema
from tests.storage.proto_fixtures import fds, file_proto


def _registry():
    reg = StreamRegistry()
    schema = FileDescriptorSetSchema(fds(file_proto("a.proto", "a", message="A")), "a.A")
    reg.register_stream("s", schema)
    return reg


def test_ae6_missing_extra_raises_actionable_error(monkeypatch):
    real = importlib.util.find_spec

    def fake(name, *a, **k):
        if name == "ptars":
            return None
        return real(name, *a, **k)

    monkeypatch.setattr(importlib.util, "find_spec", fake)
    reg = _registry()
    with pytest.raises(ParquetExtraNotInstalledError) as exc:
        # to_arrow_batches is a generator — must consume it to trigger the guard
        list(_columnar.to_arrow_batches([], reg, stream_id="s"))
    assert "protokit[parquet]" in str(exc.value)
    assert exc.value.missing == "ptars"


def test_ae6_missing_pyarrow_named(monkeypatch):
    real = importlib.util.find_spec

    def fake(name, *a, **k):
        if name == "pyarrow":
            return None
        return real(name, *a, **k)

    monkeypatch.setattr(importlib.util, "find_spec", fake)
    with pytest.raises(ParquetExtraNotInstalledError) as exc:
        _columnar._require_parquet()
    assert exc.value.missing == "pyarrow"
    assert "protokit[parquet]" in str(exc.value)


def test_has_parquet_reflects_find_spec(monkeypatch):
    assert _columnar._has_parquet() in (True, False)
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda name, *a, **k: None
    )
    assert _columnar._has_parquet() is False
