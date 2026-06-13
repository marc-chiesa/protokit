"""Tests for the ``protokit.message`` public surface (U10).

Pins the public contract the matcher delivery (U1–U9) establishes — the message
package had NO surface test before this unit. It asserts: ``__all__`` is sorted
and every name resolves and is non-underscore; the internal selector / set-match
/ presence helpers are NOT exported; the matcher/adapter exception family is
coherent (``HamcrestExtraNotInstalledError`` is a ``MatcherError``); the new
names do NOT leak onto the top-level ``protokit`` namespace (mirrors storage's
no-top-level-re-export rule); ``equals_proto`` is referenceable while importing
``protokit.message`` does NOT eagerly import ``hamcrest``, and using it without
the extra raises the actionable error (find_spec fully stubbed).

It also carries the SWI-2 structural check: the front-end modules
(``matchers.py`` / ``hamcrest.py`` / ``pytest_plugin.py``) configure the differ
ONLY through ``MatchPolicy`` / ``matchers._build_differ`` — they contain no
direct differ-config calls, so the policy→differ mapping stays the single
enforceable chokepoint.

Modeled on ``tests/storage/test_public_surface.py``.
"""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

import protokit.message as message
from protokit.message import (
    HamcrestExtraNotInstalledError,
    MatcherError,
    equals_proto,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MESSAGE_PKG = _REPO_ROOT / "src" / "protokit" / "message"

# The five differ-config builder methods that, per SWI-2, may be called ONLY
# inside ``matchers._build_differ`` — the single policy→differ mapping point.
# Front-ends hold a MatchPolicy, never a differ, so these must not appear in
# matchers.py outside _build_differ, nor anywhere in hamcrest.py /
# pytest_plugin.py. (treat_as_map is the legacy keyed-set name; included for
# completeness even though the matcher surface uses treat_as_set.)
_DIFFER_CONFIG_CALLS = frozenset(
    {
        "set_partial",
        "treat_as_set",
        "treat_as_map",
        "ignore_fields",
        "set_message_field_comparison",
        "set_float_comparison",
    }
)


class TestPublicImports:
    def test_core_names_resolve_from_package(self) -> None:
        # The module-top import block already exercises resolution; assert the
        # representative U7/U5/U8 slice is present on the package object too.
        for name in (
            "proto_match",
            "expect_proto",
            "MatchPolicy",
            "Approx",
            "MatcherError",
            "MessageFieldComparison",
            "equals_proto",
            "HamcrestExtraNotInstalledError",
        ):
            assert hasattr(message, name), name
            assert name in message.__all__, name

    def test_all_is_sorted_and_fully_importable(self) -> None:
        assert message.__all__ == sorted(message.__all__)
        for name in message.__all__:
            assert hasattr(message, name), name
            assert not name.startswith("_"), name


class TestInternalsNotExported:
    def test_helper_modules_not_exported(self) -> None:
        # The selector / set-match / presence helpers are strict-gated internals;
        # only the matcher/adapter facade is public surface.
        for name in ("_selector", "_setmatch", "_presence"):
            assert name not in message.__all__, name

    def test_internal_symbols_not_exported(self) -> None:
        # Concrete internal classes/functions from the helper modules must not
        # have leaked onto the package surface or into __all__.
        for name in (
            "FieldSelector",
            "SelectorSpec",
            "should_visit",
            "greedy_multiset_pairing",
            "PresenceVerdict",
            "presence_verdict",
            "_build_differ",
            "ProtoMatcher",
        ):
            assert name not in message.__all__, name


class TestExceptionHierarchy:
    def test_hamcrest_error_is_a_matcher_error(self) -> None:
        # The adapter's configuration error joins the matcher exception family,
        # so a caller catching MatcherError catches it too.
        assert issubclass(HamcrestExtraNotInstalledError, MatcherError)

    def test_matcher_error_is_an_exception(self) -> None:
        assert issubclass(MatcherError, Exception)


class TestNoTopLevelReExport:
    def test_message_symbols_not_leaked_to_top_level_protokit(self) -> None:
        import protokit

        for name in (
            "proto_match",
            "expect_proto",
            "MatchPolicy",
            "Approx",
            "equals_proto",
            "HamcrestExtraNotInstalledError",
            "MatcherError",
        ):
            assert not hasattr(protokit, name), f"protokit.{name} leaked to top level"


class TestHamcrestLazyImport:
    def test_importing_message_does_not_import_hamcrest(self) -> None:
        # CRITICAL (R3 / F1): importing protokit.message must NOT eagerly import
        # the optional ``hamcrest`` package — hamcrest.py builds its BaseMatcher
        # subclass lazily inside the guarded factory. pyhamcrest IS installed in
        # this venv, so a same-process check is unreliable (another test may have
        # imported it). Run a FRESH interpreter that imports only the package and
        # reports whether ``hamcrest`` landed in sys.modules.
        code = (
            "import sys; import protokit.message; "
            "print('hamcrest' in sys.modules)"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
        )
        assert proc.stdout.strip() == "False", (
            "importing protokit.message eagerly imported `hamcrest`:\n"
            f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )

    def test_equals_proto_is_referenceable(self) -> None:
        # The name resolves at package import time (it is a plain function),
        # independent of whether the extra is installed.
        assert callable(equals_proto)
        assert message.equals_proto is equals_proto

    def test_equals_proto_without_extra_raises_actionable_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Simulate the extra being ABSENT by FULLY stubbing find_spec — None for
        # the targeted name, a non-None sentinel for every other name, never
        # delegating to the real env (pyhamcrest IS installed here). Per
        # docs/solutions/best-practices/ordered-preflight-guard-test-must-control-every-probe.md.
        #
        # Resolve BOTH the callable and the expected exception from the LIVE
        # ``protokit.message.hamcrest`` module rather than this file's module-top
        # imports: ``tests/message/test_hamcrest_extra.py`` may have ``importlib.reload``-d
        # that submodule earlier in the session, which rebinds its
        # ``HamcrestExtraNotInstalledError`` to a NEW class object. A module-top
        # binding captured at collection time would then mismatch the class the
        # reloaded ``equals_proto`` raises, so ``pytest.raises`` would let it
        # escape. Reading the symbols live makes this order-independent.
        import protokit.message.hamcrest as live

        def fake_find_spec(name: str, *a: object, **k: object) -> object | None:
            if name == "hamcrest":
                return None
            return object()

        monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)

        with pytest.raises(live.HamcrestExtraNotInstalledError) as exc:
            live.equals_proto(object())  # type: ignore[arg-type]  # guard fires first
        assert "protokit[hamcrest]" in str(exc.value)
        # The live error class still belongs to the documented matcher family.
        assert issubclass(live.HamcrestExtraNotInstalledError, live.MatcherError)


# ---------------------------------------------------------------------------
# SWI-2: policy→differ mapping is the single enforceable chokepoint.
# ---------------------------------------------------------------------------
#
# Front-ends hold a MatchPolicy and never touch the differ directly; the ONLY
# place that calls the differ's config builders is matchers._build_differ. An
# AST walk over each front-end module pins that invariant structurally so a
# future edit that reaches around MatchPolicy fails this test rather than
# silently forking the configuration surface.


def _config_call_names(node: ast.AST) -> list[tuple[str, int]]:
    """Return ``(method_name, lineno)`` for every differ-config method call.

    Matches ``<expr>.<method>(...)`` where ``<method>`` is one of
    ``_DIFFER_CONFIG_CALLS`` — the attribute-call shape the differ builders use
    (e.g. ``differ.set_partial(True)``). Bare-name calls are not differ-config
    calls and are ignored.
    """
    found: list[tuple[str, int]] = []
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr in _DIFFER_CONFIG_CALLS
        ):
            found.append((child.func.attr, child.lineno))
    return found


def _function_def_named(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    """Find a top-level (or nested) ``def name(...)`` in ``tree``, or ``None``."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


class TestSwi2SingleMappingPoint:
    def test_matchers_config_calls_only_in_build_differ(self) -> None:
        source = (_MESSAGE_PKG / "matchers.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        build_differ = _function_def_named(tree, "_build_differ")
        assert build_differ is not None, "matchers._build_differ not found"

        in_build_differ = {lineno for _, lineno in _config_call_names(build_differ)}
        all_calls = _config_call_names(tree)
        assert all_calls, (
            "expected matchers.py to contain differ-config calls (in "
            "_build_differ) — none found; the test target may have moved."
        )

        leaked = [
            (name, lineno)
            for name, lineno in all_calls
            if lineno not in in_build_differ
        ]
        assert not leaked, (
            "differ-config calls in matchers.py outside _build_differ "
            f"(SWI-2 single-mapping-point violated): {leaked}"
        )

    def test_hamcrest_has_no_direct_differ_config_calls(self) -> None:
        source = (_MESSAGE_PKG / "hamcrest.py").read_text(encoding="utf-8")
        calls = _config_call_names(ast.parse(source))
        assert not calls, (
            "hamcrest.py must configure the differ only via MatchPolicy / "
            f"_build_differ; found direct differ-config calls: {calls}"
        )

    def test_pytest_plugin_has_no_direct_differ_config_calls(self) -> None:
        source = (_MESSAGE_PKG / "pytest_plugin.py").read_text(encoding="utf-8")
        calls = _config_call_names(ast.parse(source))
        assert not calls, (
            "pytest_plugin.py must not apply pass/fail-altering policies via "
            f"direct differ config (KTD-9 / SWI-2); found: {calls}"
        )
