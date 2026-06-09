"""Extra-guard tests for the PyHamcrest adapter (U8 / R3).

Deliberately does NOT ``importorskip("hamcrest")``: it tests the extra-ABSENT
error path, which must run even on an environment WITHOUT the ``[hamcrest]``
extra. ``protokit.message.hamcrest`` imports ``hamcrest`` lazily (inside the
guarded factory), so the module imports fine without the extra; absence is
simulated by monkeypatching ``importlib.util.find_spec``.

The fake ``find_spec`` returns ``None`` ONLY for the targeted name and a
non-``None`` sentinel for every other name — it NEVER delegates to the real
env. A guard test that controls one probe but lets others fall through to the
real interpreter is only accidentally correct (see
``docs/solutions/best-practices/ordered-preflight-guard-test-must-control-every-probe.md``);
``equals_proto``'s guard probes only ``"hamcrest"`` today, but stubbing every
name keeps the test correct if the guard ever grows a second probe.
"""

from __future__ import annotations

import importlib.util

import pytest

from protokit.message.hamcrest import (
    HamcrestExtraNotInstalledError,
    _has_hamcrest,
    _require_hamcrest,
    equals_proto,
)
from protokit.message.matchers import MatcherError


def _stub_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``find_spec`` report hamcrest absent and everything else present.

    Controls EVERY probe: ``None`` for ``"hamcrest"``, a non-``None`` sentinel
    (``object()``) for any other name — never delegating to the real env.
    """

    def fake(name: str, *a: object, **k: object) -> object | None:
        if name == "hamcrest":
            return None
        return object()

    monkeypatch.setattr(importlib.util, "find_spec", fake)


def test_equals_proto_without_extra_raises_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_absent(monkeypatch)
    with pytest.raises(HamcrestExtraNotInstalledError) as exc:
        equals_proto(object())  # type: ignore[arg-type]  # guard fires before use
    assert "protokit[hamcrest]" in str(exc.value)
    assert exc.value.missing == "hamcrest"


def test_require_hamcrest_raises_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_absent(monkeypatch)
    with pytest.raises(HamcrestExtraNotInstalledError):
        _require_hamcrest()


def test_has_hamcrest_false_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_absent(monkeypatch)
    assert _has_hamcrest() is False


def test_has_hamcrest_reflects_find_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    # Without stubbing, the boolean reflects the real env (either value is fine).
    assert _has_hamcrest() in (True, False)
    # Force-absent -> False, regardless of the real env.
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a, **k: None)
    assert _has_hamcrest() is False


def test_error_is_a_matcher_error_subclass() -> None:
    # Coherent exception family: HamcrestExtraNotInstalledError is a MatcherError
    # so callers catching configuration problems catch it too.
    assert issubclass(HamcrestExtraNotInstalledError, MatcherError)


def test_error_subclasses_matcher_error_at_raise_site(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The raised instance is catchable as MatcherError (the documented family).
    _stub_absent(monkeypatch)
    with pytest.raises(MatcherError):
        equals_proto(object())  # type: ignore[arg-type]


def test_module_imports_without_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    # Importing the adapter module (done at test-module top) must succeed even
    # with the extra reported absent — the BaseMatcher subclass is built lazily,
    # never at module top (F1). Re-import under the stub to prove no eager import.
    _stub_absent(monkeypatch)
    import importlib

    import protokit.message.hamcrest as mod

    reimported = importlib.reload(mod)
    assert reimported.equals_proto is not None
