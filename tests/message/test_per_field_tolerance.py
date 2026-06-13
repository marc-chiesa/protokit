"""Tests for selective / per-field float tolerance (U6, KTD-6, R11).

``set_float_comparison(mode, fraction, margin, *, selector=...)`` registers a
``(FieldSelector, FloatConfig)`` OVERLAY over the global float setting rather
than replacing it. During comparison the overlays are consulted FIRST: the
first overlay whose selector matches the field supplies the FloatConfig;
otherwise an unscoped float field falls back to the global config. This LAYERS
approximate tolerance onto chosen fields/paths while every other float field
keeps the global behavior.

Each behavioral test follows baseline-then-mechanism: a sub-tolerance
difference is real (an EXACT-compared sibling still reports it), and only the
scoped field is loosened by the overlay — so the suppression signal is
non-vacuous.

Map / repeated coverage exercises BOTH a path-form selector and a
descriptor-predicate selector, since the descriptor at a map element's compare
site is the synthetic ``MapEntry.value`` descriptor (name ``"value"``); the
overlay must resolve the container field so a predicate over ``fd.name`` still
matches (the AE6 singular-scalar case alone does not cover this).
"""

from __future__ import annotations

import math

from google.protobuf import descriptor_pb2

from protokit.message import ChangeType, FloatComparison, MessageDifferencer
from protokit.message._selector import FieldSelector
from tests.proto_builder import ProtoBuilder

T = descriptor_pb2.FieldDescriptorProto


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _two_double_builder() -> ProtoBuilder:
    """Message with two sibling double fields ``ratio`` and ``other``."""
    b = ProtoBuilder()
    b.message(
        "test.Msg",
        {
            "ratio": (T.TYPE_DOUBLE, 1),
            "other": (T.TYPE_DOUBLE, 2),
        },
    )
    return b


def _scale_builder() -> ProtoBuilder:
    """Message with a large-magnitude ``big`` and a small-magnitude ``tiny``."""
    b = ProtoBuilder()
    b.message(
        "test.Msg",
        {
            "big": (T.TYPE_DOUBLE, 1),
            "tiny": (T.TYPE_DOUBLE, 2),
        },
    )
    return b


def _repeated_double_builder() -> ProtoBuilder:
    """Message with a repeated double field ``ratios``."""
    b = ProtoBuilder()
    b.message_with_repeated(
        "test.Msg",
        {"ratios": (T.TYPE_DOUBLE, 1)},
        repeated_fields={"ratios"},
    )
    return b


def _map_double_builder() -> ProtoBuilder:
    """Message with a ``map<string, double>`` field ``ratios``."""
    b = ProtoBuilder()
    b.map_message(
        "test.Msg",
        {},
        {"ratios": (T.TYPE_STRING, T.TYPE_DOUBLE, 1)},
    )
    return b


# ---------------------------------------------------------------------------
# AE6: singular scalar overlay scoped to one field; EXACT sibling still diffs
# ---------------------------------------------------------------------------


class TestSingularScalarOverlay:
    def test_baseline_both_fields_diff_under_exact(self) -> None:
        """Baseline: with no overlay, BOTH sub-tolerance deltas are differences."""
        b = _two_double_builder()
        left = b.build("test.Msg", ratio=0.1, other=0.1)
        right = b.build("test.Msg", ratio=0.1000001, other=0.1000001)
        result = MessageDifferencer().compare(left, right)
        paths = {str(d.path) for d in result.differences}
        assert paths == {"ratio", "other"}

    def test_overlay_scoped_to_ratio_only(self) -> None:
        """AE6: margin 1e-6 scoped to ``ratio`` -> equal; ``other`` still diffs."""
        b = _two_double_builder()
        left = b.build("test.Msg", ratio=0.1, other=0.1)
        right = b.build("test.Msg", ratio=0.1000001, other=0.1000001)
        d = MessageDifferencer()
        d.set_float_comparison(
            FloatComparison.APPROXIMATE, fraction=0.0, margin=1e-6, selector="ratio"
        )
        result = d.compare(left, right)
        # ratio is within the per-field margin; other is still EXACT-compared.
        paths = {str(diff.path) for diff in result.differences}
        assert paths == {"other"}
        (only,) = result.differences
        assert only.change_type is ChangeType.MODIFIED

    def test_overlay_does_not_set_global(self) -> None:
        """An overlay must NOT bleed into the global config (R11 layer, not replace)."""
        b = _two_double_builder()
        left = b.build("test.Msg", ratio=0.1, other=0.1)
        right = b.build("test.Msg", ratio=0.1000001, other=0.1000001)
        d = MessageDifferencer()
        d.set_float_comparison(
            FloatComparison.APPROXIMATE, fraction=0.0, margin=1e-6, selector="ratio"
        )
        # The global config is untouched (still EXACT) so ``other`` reports.
        assert d._float_config.mode is FloatComparison.EXACT
        result = d.compare(left, right)
        assert any(str(diff.path) == "other" for diff in result.differences)


# ---------------------------------------------------------------------------
# Both numeric regimes: fractional for large magnitude, absolute for small
# ---------------------------------------------------------------------------


class TestNumericRegimes:
    def test_fractional_overlay_on_large_field(self) -> None:
        """Fractional tolerance scoped to a large-magnitude field absorbs noise."""
        b = _scale_builder()
        # big differs by 1.0 out of 1e6 (relative 1e-6); tiny differs by 1e-3.
        left = b.build("test.Msg", big=1_000_000.0, tiny=0.0)
        right = b.build("test.Msg", big=1_000_001.0, tiny=1e-3)
        # Baseline: both differ under EXACT.
        baseline = MessageDifferencer().compare(left, right)
        assert {str(x.path) for x in baseline.differences} == {"big", "tiny"}
        d = MessageDifferencer()
        d.set_float_comparison(
            FloatComparison.APPROXIMATE, fraction=1e-5, margin=0.0, selector="big"
        )
        result = d.compare(left, right)
        # Fraction absorbs big's relative delta; tiny is still EXACT.
        assert {str(x.path) for x in result.differences} == {"tiny"}

    def test_absolute_margin_overlay_on_small_field(self) -> None:
        """Absolute margin scoped to a small-magnitude field absorbs noise."""
        b = _scale_builder()
        left = b.build("test.Msg", big=1_000_000.0, tiny=0.0)
        right = b.build("test.Msg", big=1_000_001.0, tiny=1e-10)
        d = MessageDifferencer()
        d.set_float_comparison(
            FloatComparison.APPROXIMATE, fraction=0.0, margin=1e-9, selector="tiny"
        )
        result = d.compare(left, right)
        # Margin absorbs tiny's absolute delta; big is still EXACT.
        assert {str(x.path) for x in result.differences} == {"big"}


# ---------------------------------------------------------------------------
# Overlay falls back to the GLOBAL config for unscoped fields
# ---------------------------------------------------------------------------


class TestGlobalFallback:
    def test_unscoped_field_uses_global_approximate(self) -> None:
        """A global APPROXIMATE config still applies to fields no overlay selects."""
        b = _two_double_builder()
        # Both deltas 1e-4: inside a loose global margin, outside a tight overlay.
        left = b.build("test.Msg", ratio=1.0, other=1.0)
        right = b.build("test.Msg", ratio=1.0001, other=1.0001)
        d = MessageDifferencer()
        # Global: loose margin -> both would be equal globally.
        d.set_float_comparison(FloatComparison.APPROXIMATE, fraction=0.0, margin=1e-3)
        # Overlay on ``ratio``: TIGHTER margin -> ratio now reports.
        d.set_float_comparison(
            FloatComparison.APPROXIMATE, fraction=0.0, margin=1e-9, selector="ratio"
        )
        result = d.compare(left, right)
        # ratio fails its tight overlay; other falls back to the loose global.
        assert {str(x.path) for x in result.differences} == {"ratio"}

    def test_overlay_looser_than_global(self) -> None:
        """An overlay LOOSER than a tight global suppresses only the scoped field."""
        b = _two_double_builder()
        left = b.build("test.Msg", ratio=1.0, other=1.0)
        right = b.build("test.Msg", ratio=1.0001, other=1.0001)
        d = MessageDifferencer()
        # Global: tight margin -> both would report globally.
        d.set_float_comparison(FloatComparison.APPROXIMATE, fraction=0.0, margin=1e-9)
        # Overlay on ``ratio``: LOOSER margin -> ratio is suppressed.
        d.set_float_comparison(
            FloatComparison.APPROXIMATE, fraction=0.0, margin=1e-3, selector="ratio"
        )
        result = d.compare(left, right)
        assert {str(x.path) for x in result.differences} == {"other"}


# ---------------------------------------------------------------------------
# MAP / REPEATED float element values scoped by path AND by predicate
# ---------------------------------------------------------------------------


class TestRepeatedFloatOverlay:
    def test_baseline_repeated_diffs_under_exact(self) -> None:
        """Baseline: sub-tolerance repeated deltas report per index under EXACT."""
        b = _repeated_double_builder()
        left = b.build("test.Msg", ratios=[0.1, 0.2])
        right = b.build("test.Msg", ratios=[0.1000001, 0.2000001])
        result = MessageDifferencer().compare(left, right)
        assert result.has_changes()

    def test_repeated_path_form_selector(self) -> None:
        """A path-form selector ``"ratios"`` loosens repeated float elements."""
        b = _repeated_double_builder()
        left = b.build("test.Msg", ratios=[0.1, 0.2])
        right = b.build("test.Msg", ratios=[0.1000001, 0.2000001])
        d = MessageDifferencer()
        d.set_float_comparison(
            FloatComparison.APPROXIMATE, fraction=0.0, margin=1e-6, selector="ratios"
        )
        result = d.compare(left, right)
        assert not result.has_changes()

    def test_repeated_predicate_form_selector(self) -> None:
        """A descriptor-predicate selector matches repeated float elements.

        For a repeated (non-map) field the element-compare site already passes
        the container descriptor, so ``fd.name`` is ``"ratios"``.
        """
        b = _repeated_double_builder()
        left = b.build("test.Msg", ratios=[0.1, 0.2])
        right = b.build("test.Msg", ratios=[0.1000001, 0.2000001])
        d = MessageDifferencer()
        selector = FieldSelector.of(lambda fd, _path: fd.name == "ratios")
        d.set_float_comparison(
            FloatComparison.APPROXIMATE, fraction=0.0, margin=1e-6, selector=selector
        )
        result = d.compare(left, right)
        assert not result.has_changes()


class TestMapFloatOverlay:
    def test_baseline_map_diffs_under_exact(self) -> None:
        """Baseline: sub-tolerance map value deltas report under EXACT."""
        b = _map_double_builder()
        left = b.build("test.Msg", ratios={"a": 0.1, "b": 0.2})
        right = b.build("test.Msg", ratios={"a": 0.1000001, "b": 0.2000001})
        result = MessageDifferencer().compare(left, right)
        assert result.has_changes()

    def test_map_path_form_selector(self) -> None:
        """A path-form selector ``"ratios"`` matches map float VALUES.

        The element path is ``ratios[<key>]``; bracket-blind, exact-length
        matching makes the single-segment selector ``"ratios"`` match it.
        """
        b = _map_double_builder()
        left = b.build("test.Msg", ratios={"a": 0.1, "b": 0.2})
        right = b.build("test.Msg", ratios={"a": 0.1000001, "b": 0.2000001})
        d = MessageDifferencer()
        d.set_float_comparison(
            FloatComparison.APPROXIMATE, fraction=0.0, margin=1e-6, selector="ratios"
        )
        result = d.compare(left, right)
        assert not result.has_changes()

    def test_map_predicate_form_selector_resolves_container(self) -> None:
        """A descriptor-predicate matches map values via the CONTAINER fd.

        At a map value's compare site the descriptor is the synthetic
        ``MapEntry.value`` (name ``"value"``). The overlay resolves the
        container field so a predicate over ``fd.name == "ratios"`` matches —
        guarding the synthetic-MapEntry.value resolution.
        """
        b = _map_double_builder()
        left = b.build("test.Msg", ratios={"a": 0.1, "b": 0.2})
        right = b.build("test.Msg", ratios={"a": 0.1000001, "b": 0.2000001})
        d = MessageDifferencer()
        selector = FieldSelector.of(lambda fd, _path: fd.name == "ratios")
        d.set_float_comparison(
            FloatComparison.APPROXIMATE, fraction=0.0, margin=1e-6, selector=selector
        )
        result = d.compare(left, right)
        assert not result.has_changes()

    def test_map_predicate_on_entry_value_name_does_not_match(self) -> None:
        """A predicate keyed on the synthetic ``"value"`` name must NOT match.

        Proves the resolution swaps in the container descriptor: a predicate
        looking for the entry-value name ``"value"`` sees the container name
        ``"ratios"`` instead and therefore does NOT loosen the field, so the
        sub-tolerance map deltas still report.
        """
        b = _map_double_builder()
        left = b.build("test.Msg", ratios={"a": 0.1})
        right = b.build("test.Msg", ratios={"a": 0.1000001})
        d = MessageDifferencer()
        selector = FieldSelector.of(lambda fd, _path: fd.name == "value")
        d.set_float_comparison(
            FloatComparison.APPROXIMATE, fraction=0.0, margin=1e-6, selector=selector
        )
        result = d.compare(left, right)
        assert result.has_changes()


# ---------------------------------------------------------------------------
# NaN / inf handling preserved under a per-field overlay
# ---------------------------------------------------------------------------


class TestNanInfUnderOverlay:
    def test_nan_equal_under_approximate_overlay(self) -> None:
        """APPROXIMATE overlay: NaN == NaN on the scoped field."""
        b = _two_double_builder()
        left = b.build("test.Msg", ratio=math.nan, other=1.0)
        right = b.build("test.Msg", ratio=math.nan, other=1.0)
        d = MessageDifferencer()
        d.set_float_comparison(
            FloatComparison.APPROXIMATE, selector="ratio"
        )
        result = d.compare(left, right)
        assert not result.has_changes()

    def test_nan_not_equal_when_field_unscoped(self) -> None:
        """An unscoped field stays EXACT (global): NaN != NaN still reports."""
        b = _two_double_builder()
        left = b.build("test.Msg", ratio=math.nan, other=math.nan)
        right = b.build("test.Msg", ratio=math.nan, other=math.nan)
        d = MessageDifferencer()
        # Overlay scopes only ``ratio`` to APPROXIMATE; ``other`` stays EXACT.
        d.set_float_comparison(
            FloatComparison.APPROXIMATE, selector="ratio"
        )
        result = d.compare(left, right)
        # ratio: NaN == NaN under APPROXIMATE; other: NaN != NaN under EXACT.
        assert {str(x.path) for x in result.differences} == {"other"}

    def test_same_sign_inf_equal_under_overlay(self) -> None:
        """Same-sign infinities are equal under an APPROXIMATE overlay."""
        b = _two_double_builder()
        left = b.build("test.Msg", ratio=math.inf, other=1.0)
        right = b.build("test.Msg", ratio=math.inf, other=1.0)
        d = MessageDifferencer()
        d.set_float_comparison(
            FloatComparison.APPROXIMATE, selector="ratio"
        )
        result = d.compare(left, right)
        assert not result.has_changes()

    def test_opposite_sign_inf_not_equal_under_overlay(self) -> None:
        """Opposite-sign infinities still differ even under an APPROXIMATE overlay."""
        b = _two_double_builder()
        left = b.build("test.Msg", ratio=math.inf, other=1.0)
        right = b.build("test.Msg", ratio=-math.inf, other=1.0)
        d = MessageDifferencer()
        d.set_float_comparison(
            FloatComparison.APPROXIMATE, selector="ratio"
        )
        result = d.compare(left, right)
        assert {str(x.path) for x in result.differences} == {"ratio"}
