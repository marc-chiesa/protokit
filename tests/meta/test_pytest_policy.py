"""Tests for the U9 pytest config path + configured-matcher fixture.

Covers the two halves of the message-differ pytest integration's policy
surface (KTD-9):

1. PRESENTATION config for the bare-``==`` rich-diff rendering — resolved from
   the pytest ini option and/or pyproject ``[tool.protokit.message]``, with
   ini-wins-over-pyproject precedence and source-accurate error messages. These
   knobs change ONLY rendering, never ``==``'s pass/fail.
2. The ``proto_matcher`` fixture — yields a factory over U7's matchers so a
   test author applies NON-default comparison policies (partial / set / ignore
   / presence / tolerance) explicitly.

Most cases call the resolution / rendering / fixture functions directly (the
repo's established pattern — see ``tests/schema/test_pytest_plugin.py``, which
tests fixtures via ``__wrapped__``). A small ``_StubConfig`` stands in for the
pytest ``Config`` (only ``getini`` + ``rootpath`` are consulted), and real
``tmp_path`` pyproject files exercise the actual TOML-reading path.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import pytest
from google.protobuf import descriptor_pb2

from protokit.message.comparators import MessageFieldComparison
from protokit.message.matchers import Approx, MatcherError, ProtoMatcher
from protokit.message.pytest_plugin import (
    ProtoMatcherFactory,
    RenderConfig,
    _coerce_enhanced,
    _coerce_max_diff_lines,
    _read_pyproject_message_table,
    _resolve_render_config,
    proto_matcher,
    pytest_assertrepr_compare,
    render_diff_lines,
)
from tests.proto_builder import ProtoBuilder

T = descriptor_pb2.FieldDescriptorProto


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubConfig:
    """Minimal stand-in for pytest's ``Config`` for resolution tests.

    ``_resolve_render_config`` consults exactly two surfaces: ``getini(name)``
    (the pytest ini options) and ``rootpath`` (to locate pyproject.toml). This
    stub supplies both without spinning up a full pytest session, so the
    resolution + precedence + source-attribution logic is exercised directly.
    """

    def __init__(self, *, rootpath: Path, ini: dict[str, Any] | None = None) -> None:
        self.rootpath = rootpath
        self._ini = ini or {}

    def getini(self, name: str) -> Any:
        # Mirror pytest: an unset addini(default=None) option returns None.
        return self._ini.get(name)


def _make_builder() -> ProtoBuilder:
    builder = ProtoBuilder()
    builder.message(
        "test.Msg",
        {
            "name": (T.TYPE_STRING, 1),
            "value": (T.TYPE_INT32, 2),
        },
    )
    return builder


def _make_many_field_builder() -> ProtoBuilder:
    builder = ProtoBuilder()
    builder.message(
        "test.Many",
        {
            "a": (T.TYPE_STRING, 1),
            "b": (T.TYPE_STRING, 2),
            "c": (T.TYPE_STRING, 3),
            "d": (T.TYPE_STRING, 4),
            "e": (T.TYPE_STRING, 5),
        },
    )
    return builder


def _write_pyproject(tmp_path: Path, body: str) -> Path:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(body, encoding="utf-8")
    return pyproject


# ---------------------------------------------------------------------------
# RenderConfig defaults + render_diff_lines cap (presentation only)
# ---------------------------------------------------------------------------


class TestRenderConfigDefaults:
    def test_defaults_are_enhanced_and_unlimited(self) -> None:
        cfg = RenderConfig()
        assert cfg.enhanced is True
        assert cfg.max_diff_lines == 0


class TestRenderDiffLinesCap:
    def _result_with_five_diffs(self):
        b1 = _make_many_field_builder()
        b2 = _make_many_field_builder()
        msg1 = b1.build("test.Many", a="1", b="2", c="3", d="4", e="5")
        msg2 = b2.build("test.Many", a="x", b="y", c="z", d="w", e="v")
        from protokit.message.differ import MessageDifferencer

        return MessageDifferencer().compare(msg1, msg2)

    def test_uncapped_renders_every_difference_row(self) -> None:
        result = self._result_with_five_diffs()
        assert len(result) == 5
        lines = render_diff_lines(result, "H")
        diff_rows = [ln for ln in lines if ln.lstrip().startswith("~")]
        assert len(diff_rows) == 5
        assert not any("more difference" in ln for ln in lines)

    def test_cap_limits_rendered_rows_and_adds_footer(self) -> None:
        result = self._result_with_five_diffs()
        lines = render_diff_lines(result, "H", max_diff_lines=2)
        diff_rows = [ln for ln in lines if ln.lstrip().startswith("~")]
        # Only 2 of 5 rendered, with a truncation footer naming the cap.
        assert len(diff_rows) == 2
        footer = [ln for ln in lines if "more difference" in ln]
        assert len(footer) == 1
        assert "3 more difference(s)" in footer[0]
        assert "max_diff_lines=2" in footer[0]
        # The TRUE total is still reported (the engine found all 5).
        assert "5 difference(s)" in lines[1]

    def test_cap_zero_means_unlimited(self) -> None:
        result = self._result_with_five_diffs()
        lines = render_diff_lines(result, "H", max_diff_lines=0)
        diff_rows = [ln for ln in lines if ln.lstrip().startswith("~")]
        assert len(diff_rows) == 5


# ---------------------------------------------------------------------------
# Hook regression + presentation config honored
# ---------------------------------------------------------------------------


class TestHookRendering:
    def test_bare_eq_still_produces_rich_diff_default_config(self) -> None:
        """Regression: with no config, the hook returns the rich diff."""
        b = _make_builder()
        msg1 = b.build("test.Msg", name="Alice", value=1)
        msg2 = b.build("test.Msg", name="Bob", value=2)
        result = pytest_assertrepr_compare(None, "==", msg1, msg2)
        assert result is not None
        assert "2 difference(s)" in result[1]

    def test_enhanced_toggle_off_returns_none(self, tmp_path: Path) -> None:
        """enhanced_diff=false disables the rich rendering (pytest falls back)."""
        b = _make_builder()
        msg1 = b.build("test.Msg", name="Alice")
        msg2 = b.build("test.Msg", name="Bob")
        config = _StubConfig(
            rootpath=tmp_path,
            ini={"protokit_message_enhanced_diff": "false"},
        )
        result = pytest_assertrepr_compare(config, "==", msg1, msg2)
        assert result is None

    def test_max_diff_lines_cap_honored_through_hook(self, tmp_path: Path) -> None:
        """The ini cap limits rendered rows in the hook output."""
        b1 = _make_many_field_builder()
        b2 = _make_many_field_builder()
        msg1 = b1.build("test.Many", a="1", b="2", c="3", d="4", e="5")
        msg2 = b2.build("test.Many", a="x", b="y", c="z", d="w", e="v")
        config = _StubConfig(
            rootpath=tmp_path,
            ini={"protokit_message_max_diff_lines": "2"},
        )
        result = pytest_assertrepr_compare(config, "==", msg1, msg2)
        assert result is not None
        diff_rows = [ln for ln in result if ln.lstrip().startswith("~")]
        assert len(diff_rows) == 2
        assert any("3 more difference(s)" in ln for ln in result)

    def test_invalid_config_warns_and_falls_back(self, tmp_path: Path) -> None:
        """A malformed config value never masks the failure — warn + None."""
        b = _make_builder()
        msg1 = b.build("test.Msg", name="Alice")
        msg2 = b.build("test.Msg", name="Bob")
        config = _StubConfig(
            rootpath=tmp_path,
            ini={"protokit_message_max_diff_lines": "not-an-int"},
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = pytest_assertrepr_compare(config, "==", msg1, msg2)
        assert result is None
        assert len(w) == 1
        assert "protokit plugin config invalid" in str(w[0].message)


# ---------------------------------------------------------------------------
# Config resolution: two sources, precedence, source-aware errors
# ---------------------------------------------------------------------------


class TestResolveFromIni:
    def test_ini_max_diff_lines(self, tmp_path: Path) -> None:
        config = _StubConfig(
            rootpath=tmp_path, ini={"protokit_message_max_diff_lines": "7"}
        )
        cfg = _resolve_render_config(config)
        assert cfg.max_diff_lines == 7
        assert cfg.enhanced is True  # unset -> default

    def test_ini_enhanced_false(self, tmp_path: Path) -> None:
        config = _StubConfig(
            rootpath=tmp_path, ini={"protokit_message_enhanced_diff": "false"}
        )
        cfg = _resolve_render_config(config)
        assert cfg.enhanced is False

    def test_unset_everything_is_default(self, tmp_path: Path) -> None:
        cfg = _resolve_render_config(_StubConfig(rootpath=tmp_path))
        assert cfg == RenderConfig()


class TestResolveFromPyproject:
    def test_pyproject_max_diff_lines(self, tmp_path: Path) -> None:
        _write_pyproject(
            tmp_path,
            "[tool.protokit.message]\nmax_diff_lines = 4\n",
        )
        cfg = _resolve_render_config(_StubConfig(rootpath=tmp_path))
        assert cfg.max_diff_lines == 4

    def test_pyproject_enhanced_diff(self, tmp_path: Path) -> None:
        _write_pyproject(
            tmp_path,
            "[tool.protokit.message]\nenhanced_diff = false\n",
        )
        cfg = _resolve_render_config(_StubConfig(rootpath=tmp_path))
        assert cfg.enhanced is False

    def test_missing_pyproject_table_is_default(self, tmp_path: Path) -> None:
        _write_pyproject(tmp_path, "[tool.other]\nx = 1\n")
        cfg = _resolve_render_config(_StubConfig(rootpath=tmp_path))
        assert cfg == RenderConfig()

    def test_missing_pyproject_file_is_default(self, tmp_path: Path) -> None:
        # No pyproject.toml written at all.
        assert _read_pyproject_message_table(tmp_path) == {}


class TestPrecedence:
    def test_ini_wins_over_pyproject_for_max_diff_lines(self, tmp_path: Path) -> None:
        _write_pyproject(
            tmp_path,
            "[tool.protokit.message]\nmax_diff_lines = 99\n",
        )
        config = _StubConfig(
            rootpath=tmp_path, ini={"protokit_message_max_diff_lines": "3"}
        )
        cfg = _resolve_render_config(config)
        assert cfg.max_diff_lines == 3  # ini wins

    def test_ini_wins_over_pyproject_for_enhanced(self, tmp_path: Path) -> None:
        _write_pyproject(
            tmp_path,
            "[tool.protokit.message]\nenhanced_diff = true\n",
        )
        config = _StubConfig(
            rootpath=tmp_path, ini={"protokit_message_enhanced_diff": "false"}
        )
        cfg = _resolve_render_config(config)
        assert cfg.enhanced is False  # ini wins

    def test_pyproject_used_when_ini_unset(self, tmp_path: Path) -> None:
        _write_pyproject(
            tmp_path,
            "[tool.protokit.message]\nmax_diff_lines = 8\nenhanced_diff = false\n",
        )
        cfg = _resolve_render_config(_StubConfig(rootpath=tmp_path))
        assert cfg.max_diff_lines == 8
        assert cfg.enhanced is False


class TestSourceAwareErrors:
    """Any error names the ACTUAL source of the offending value, never a
    hard-coded one (source-aware-error-messages-multi-source-resolved-value)."""

    def test_coerce_max_diff_lines_names_ini_source(self) -> None:
        with pytest.raises(ValueError) as exc:
            _coerce_max_diff_lines("nope", "protokit_message_max_diff_lines")
        assert "protokit_message_max_diff_lines" in str(exc.value)
        assert "[tool.protokit.message]" not in str(exc.value)

    def test_coerce_max_diff_lines_names_pyproject_source(self) -> None:
        with pytest.raises(ValueError) as exc:
            _coerce_max_diff_lines(
                -5, "[tool.protokit.message] max_diff_lines"
            )
        assert "[tool.protokit.message] max_diff_lines" in str(exc.value)
        assert "protokit_message_max_diff_lines" not in str(exc.value)

    def test_coerce_max_diff_lines_rejects_bool(self) -> None:
        with pytest.raises(ValueError) as exc:
            _coerce_max_diff_lines(True, "protokit_message_max_diff_lines")
        assert "boolean" in str(exc.value)

    def test_coerce_enhanced_names_pyproject_source(self) -> None:
        with pytest.raises(ValueError) as exc:
            _coerce_enhanced(123, "[tool.protokit.message] enhanced_diff")
        assert "[tool.protokit.message] enhanced_diff" in str(exc.value)
        assert "protokit_message_enhanced_diff" not in str(exc.value)

    def test_bad_ini_value_resolution_names_ini_source(self, tmp_path: Path) -> None:
        """End-to-end: a bad INI value's error names the ini key, not pyproject."""
        config = _StubConfig(
            rootpath=tmp_path,
            ini={"protokit_message_max_diff_lines": "garbage"},
        )
        with pytest.raises(ValueError) as exc:
            _resolve_render_config(config)
        assert "protokit_message_max_diff_lines" in str(exc.value)
        assert "[tool.protokit.message]" not in str(exc.value)

    def test_bad_pyproject_value_resolution_names_pyproject_source(
        self, tmp_path: Path
    ) -> None:
        """End-to-end: a bad PYPROJECT value's error names the table, not the
        ini key (the value never came from the ini option)."""
        _write_pyproject(
            tmp_path,
            "[tool.protokit.message]\nmax_diff_lines = -3\n",
        )
        with pytest.raises(ValueError) as exc:
            _resolve_render_config(_StubConfig(rootpath=tmp_path))
        assert "[tool.protokit.message] max_diff_lines" in str(exc.value)
        assert "protokit_message_max_diff_lines" not in str(exc.value)


class TestCoerceHappyPaths:
    def test_enhanced_string_truthy_falsy(self) -> None:
        assert _coerce_enhanced("true", "s") is True
        assert _coerce_enhanced("False", "s") is False
        assert _coerce_enhanced("on", "s") is True
        assert _coerce_enhanced("0", "s") is False

    def test_enhanced_real_bool(self) -> None:
        assert _coerce_enhanced(True, "s") is True
        assert _coerce_enhanced(False, "s") is False

    def test_max_diff_lines_coerces_string_int(self) -> None:
        assert _coerce_max_diff_lines("5", "s") == 5
        assert _coerce_max_diff_lines(0, "s") == 0


# ---------------------------------------------------------------------------
# proto_matcher fixture: yields a factory pre-wired to U7's matchers
# ---------------------------------------------------------------------------


class TestProtoMatcherFixture:
    def test_fixture_yields_factory(self) -> None:
        factory = proto_matcher.__wrapped__()  # unwrap @pytest.fixture
        assert isinstance(factory, ProtoMatcherFactory)

    def test_fluent_form_returns_matcher(self) -> None:
        b = _make_builder()
        expected = b.build("test.Msg", name="Alice")
        factory = ProtoMatcherFactory()
        matcher = factory(expected)
        assert isinstance(matcher, ProtoMatcher)

    def test_fluent_partial_applies_policy(self) -> None:
        """proto_matcher(expected).partially().assert_matches(actual) honors
        partial (extra actual fields are not differences)."""
        b1 = ProtoBuilder()
        b1.message("test.Sub", {"name": (T.TYPE_STRING, 1)})
        b2 = ProtoBuilder()
        b2.message(
            "test.Sub",
            {"name": (T.TYPE_STRING, 1), "extra": (T.TYPE_STRING, 2)},
        )
        expected = b1.build("test.Sub", name="Alice")
        actual = b2.build("test.Sub", name="Alice", extra="more")

        factory = ProtoMatcherFactory()
        # Partial: passes despite the extra field on actual.
        factory(expected).partially().assert_matches(actual)

        # Baseline: WITHOUT partial it would fail (extra field is a difference).
        with pytest.raises(AssertionError):
            factory(expected).assert_matches(actual)

    def test_single_call_form_applies_partial(self) -> None:
        """proto_matcher(actual, expected, partial=True) runs immediately."""
        b1 = ProtoBuilder()
        b1.message("test.Sub2", {"name": (T.TYPE_STRING, 1)})
        b2 = ProtoBuilder()
        b2.message(
            "test.Sub2",
            {"name": (T.TYPE_STRING, 1), "extra": (T.TYPE_STRING, 2)},
        )
        expected = b1.build("test.Sub2", name="Alice")
        actual = b2.build("test.Sub2", name="Alice", extra="more")

        factory = ProtoMatcherFactory()
        # Single-call partial passes.
        assert factory(actual, expected, partial=True) is None

        # Single-call full mode fails on the extra field.
        with pytest.raises(AssertionError):
            factory(actual, expected)

    def test_single_call_ignore_applies(self) -> None:
        b = _make_builder()
        expected = b.build("test.Msg", name="Alice", value=1)
        actual = b.build("test.Msg", name="Alice", value=999)
        factory = ProtoMatcherFactory()
        # Ignoring `value` makes the mismatch disappear.
        assert factory(actual, expected, ignore="value") is None
        # Baseline: without ignore it fails.
        with pytest.raises(AssertionError):
            factory(actual, expected)

    def test_single_call_presence_passthrough(self) -> None:
        """The presence knob reaches the engine via the factory."""
        b = _make_builder()
        expected = b.build("test.Msg", name="Alice")
        actual = b.build("test.Msg", name="Alice")
        factory = ProtoMatcherFactory()
        # Equal messages match under EQUAL presence too.
        assert (
            factory(actual, expected, presence=MessageFieldComparison.EQUAL)
            is None
        )

    def test_single_call_approx_passthrough(self) -> None:
        """The ``approx=`` knob reaches the engine via the factory (U6).

        Regression guard: the factory's single-call form previously omitted
        ``approx`` from its signature, so a per-field/global ``Approx`` could
        not be applied through the fixture (would raise ``TypeError``).
        """
        b = ProtoBuilder()
        b.message("test.Ratio", {"ratio": (T.TYPE_DOUBLE, 1)})
        expected = b.build("test.Ratio", ratio=0.1)
        actual = b.build("test.Ratio", ratio=0.1000001)
        factory = ProtoMatcherFactory()

        # Approx tolerance admits the sub-margin difference.
        assert factory(actual, expected, approx=Approx(margin=1e-5)) is None
        # Baseline: exact comparison fails.
        with pytest.raises(AssertionError):
            factory(actual, expected)

    def test_single_call_contradictory_tolerance_raises_matcher_error(self) -> None:
        """A genuinely malformed policy surfaces as MatcherError, not a silent
        pass. (proto_match rejects margin+fraction... only via approx clash;
        here we prove the factory propagates MatcherError-class config faults.)"""
        b = ProtoBuilder()
        b.message("test.M", {"x": (T.TYPE_INT32, 1)})
        expected = b.build("test.M", x=1)
        actual = b.build("test.M", x=1)
        factory = ProtoMatcherFactory()
        # presence must be a MessageFieldComparison; a bad value is a config bug.
        with pytest.raises(MatcherError):
            factory(actual, expected, presence="EQUAL")  # type: ignore[arg-type]

    def test_fluent_form_rejects_single_call_policy_kwargs(self) -> None:
        """A policy kwarg in the fluent form is an error, not a silent no-op.

        ``proto_matcher(expected, partial=True)`` looks like it configures the
        matcher, but the policy kwargs are single-call-only: the fluent form
        returned a DEFAULT-policy matcher and dropped them, so a test written
        that way silently asserted something stricter than its author intended.
        """
        b = _make_builder()
        expected = b.build("test.Msg", name="Alice")
        factory = ProtoMatcherFactory()
        with pytest.raises(MatcherError) as exc:
            factory(expected, partial=True)
        message = str(exc.value)
        assert "partial" in message
        assert ".partially()" in message  # names the fluent equivalent

    def test_fluent_form_names_every_dropped_kwarg(self) -> None:
        b = _make_builder()
        expected = b.build("test.Msg", name="Alice")
        factory = ProtoMatcherFactory()
        with pytest.raises(MatcherError) as exc:
            factory(
                expected,
                partial=True,
                ignore="value",
                presence=MessageFieldComparison.EQUAL,
                margin=1e-5,
            )
        message = str(exc.value)
        for name in ("partial", "ignore", "presence", "margin"):
            assert name in message

    def test_fluent_form_still_accepts_explicit_defaults(self) -> None:
        """Passing a kwarg at its default value is a no-op, not an error."""
        b = _make_builder()
        expected = b.build("test.Msg", name="Alice")
        factory = ProtoMatcherFactory()
        matcher = factory(expected, partial=False, ignore=None, approx=None)
        assert isinstance(matcher, ProtoMatcher)

    def test_fluent_diff_message_shape(self) -> None:
        """On mismatch the fluent matcher's AssertionError carries the rich
        per-field diff (same formatter as the == hook)."""
        b = _make_builder()
        expected = b.build("test.Msg", name="Alice")
        actual = b.build("test.Msg", name="Bob")
        factory = ProtoMatcherFactory()
        with pytest.raises(AssertionError) as exc:
            factory(expected).assert_matches(actual)
        msg = str(exc.value)
        assert "difference(s)" in msg
        assert "name" in msg
