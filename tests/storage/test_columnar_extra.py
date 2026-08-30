"""Extra-guard tests (PR3 U2 / R9 / AE6).

Deliberately does NOT ``importorskip`` ptars/pyarrow: it tests the
extra-absent error path, which must run even on an environment without the
``[parquet]`` extra. ``_columnar`` imports ptars/pyarrow lazily (inside
functions), so the module imports fine without the extra; absence is simulated
by monkeypatching ``importlib.util.find_spec``.
"""

from __future__ import annotations

import importlib.util
from types import SimpleNamespace

import pytest

from protokit.storage import ParquetExtraNotInstalledError, _columnar
from protokit.storage._columnar import DEFAULT_BATCH_SIZE, _batched
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
        # to_arrow_batches defers bind to first iteration — must consume it
        # (list) to trigger the extra guard, which runs inside the stream body
        list(_columnar.to_arrow_batches([], reg, stream_id="s"))
    assert "protokit[parquet]" in str(exc.value)
    assert exc.value.missing == "ptars"


def test_ae6_missing_pyarrow_named(monkeypatch):
    # ptars present, pyarrow absent -> the guard names pyarrow. Fake ptars as
    # *present* (non-None) so this is independent of whether the [parquet] extra
    # is installed in the test env: in a bare env ptars is also absent and the
    # guard, which probes ptars first, would otherwise report it instead.
    def fake(name, *a, **k):
        return None if name == "pyarrow" else object()

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


# ---------------------------------------------------------------------------
# The batch size is a memory bound, not a tuning hint
# ---------------------------------------------------------------------------


class TestBatchSizeBound:
    """``DEFAULT_BATCH_SIZE`` bounds peak memory; nothing pinned it.

    A mutation audit raised it to ``10**30`` and the whole suite stayed green.
    At that value ``_batched`` never flushes, so a conversion buffers the entire
    input instead of O(batch_size) — the documented memory bound silently
    becomes "the size of your data".

    Lives here rather than in ``test_columnar.py`` because neither test needs
    ptars or pyarrow: ``_batched`` is pure Python and the constant is just a
    number, so these keep running on an environment without the extra.
    """

    @staticmethod
    def _records(count: int) -> list[SimpleNamespace]:
        """Minimal stand-ins — ``_batched`` only reads ``.message``."""
        return [SimpleNamespace(message=object()) for _ in range(count)]

    def test_batches_are_flushed_at_the_size_limit(self) -> None:
        batches = list(_batched(self._records(7), 3))
        assert [len(b) for b in batches] == [3, 3, 1]

    def test_a_batch_is_never_larger_than_requested(self) -> None:
        for size in (1, 2, 5):
            batches = list(_batched(self._records(11), size))
            assert all(len(b) <= size for b in batches)
            assert sum(len(b) for b in batches) == 11  # nothing dropped

    def test_default_stays_within_its_documented_guidance(self) -> None:
        """The constant's own comment names the 64k-1M range it must sit in.

        Pinning the documented range rather than the literal 65_536 lets a
        deliberate retune inside the guidance stay green, while a value that
        abandons the memory bound entirely does not.
        """
        assert 65_536 <= DEFAULT_BATCH_SIZE <= 1_048_576
