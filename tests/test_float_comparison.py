"""Tests for float comparison (exact and approximate modes)."""

from google.protobuf import descriptor_pb2

from proto_differ import FloatComparison, MessageDifferencer, diff_messages
from tests.proto_builder import ProtoBuilder

T = descriptor_pb2.FieldDescriptorProto


def _make_float_builder() -> ProtoBuilder:
    builder = ProtoBuilder()
    builder.message("test.Msg", {"value": (T.TYPE_FLOAT, 1)})
    return builder


def _make_double_builder() -> ProtoBuilder:
    builder = ProtoBuilder()
    builder.message("test.Msg", {"value": (T.TYPE_DOUBLE, 1)})
    return builder


class TestExactFloatComparison:
    def test_equal_floats(self) -> None:
        b = _make_float_builder()
        msg1 = b.build("test.Msg", value=1.5)
        msg2 = b.build("test.Msg", value=1.5)
        result = diff_messages(msg1, msg2)
        assert not result.has_changes()

    def test_different_floats(self) -> None:
        b = _make_float_builder()
        msg1 = b.build("test.Msg", value=1.0)
        msg2 = b.build("test.Msg", value=2.0)
        result = diff_messages(msg1, msg2)
        assert result.has_changes()

    def test_nan_not_equal_exact(self) -> None:
        """In exact mode, NaN != NaN (IEEE 754 semantics)."""
        b = _make_double_builder()
        msg1 = b.build("test.Msg", value=float("nan"))
        msg2 = b.build("test.Msg", value=float("nan"))
        result = diff_messages(msg1, msg2)
        assert result.has_changes()

    def test_negative_zero_equals_zero_exact(self) -> None:
        """In exact mode, -0.0 == 0.0 (Python semantics)."""
        b = _make_double_builder()
        msg1 = b.build("test.Msg", value=-0.0)
        msg2 = b.build("test.Msg", value=0.0)
        result = diff_messages(msg1, msg2)
        assert not result.has_changes()


class TestApproximateFloatComparison:
    def _approx_differ(self, fraction: float = 1e-6, margin: float = 1e-9) -> MessageDifferencer:
        d = MessageDifferencer()
        d.set_float_comparison(FloatComparison.APPROXIMATE, fraction=fraction, margin=margin)
        return d

    def test_within_fraction(self) -> None:
        b = _make_double_builder()
        msg1 = b.build("test.Msg", value=1000.0)
        msg2 = b.build("test.Msg", value=1000.0005)
        result = self._approx_differ(fraction=1e-3).compare(msg1, msg2)
        assert not result.has_changes()

    def test_outside_fraction(self) -> None:
        b = _make_double_builder()
        msg1 = b.build("test.Msg", value=1000.0)
        msg2 = b.build("test.Msg", value=1010.0)
        result = self._approx_differ(fraction=1e-6, margin=1e-9).compare(msg1, msg2)
        assert result.has_changes()

    def test_within_margin(self) -> None:
        b = _make_double_builder()
        msg1 = b.build("test.Msg", value=0.0)
        msg2 = b.build("test.Msg", value=1e-10)
        result = self._approx_differ(fraction=0.0, margin=1e-9).compare(msg1, msg2)
        assert not result.has_changes()

    def test_nan_equals_nan_approx(self) -> None:
        """In approximate mode, NaN == NaN."""
        b = _make_double_builder()
        msg1 = b.build("test.Msg", value=float("nan"))
        msg2 = b.build("test.Msg", value=float("nan"))
        result = self._approx_differ().compare(msg1, msg2)
        assert not result.has_changes()

    def test_inf_equals_inf_approx(self) -> None:
        b = _make_double_builder()
        msg1 = b.build("test.Msg", value=float("inf"))
        msg2 = b.build("test.Msg", value=float("inf"))
        result = self._approx_differ().compare(msg1, msg2)
        assert not result.has_changes()

    def test_neg_inf_equals_neg_inf_approx(self) -> None:
        b = _make_double_builder()
        msg1 = b.build("test.Msg", value=float("-inf"))
        msg2 = b.build("test.Msg", value=float("-inf"))
        result = self._approx_differ().compare(msg1, msg2)
        assert not result.has_changes()

    def test_inf_not_equal_neg_inf(self) -> None:
        b = _make_double_builder()
        msg1 = b.build("test.Msg", value=float("inf"))
        msg2 = b.build("test.Msg", value=float("-inf"))
        result = self._approx_differ().compare(msg1, msg2)
        assert result.has_changes()

    def test_nan_not_equal_number(self) -> None:
        b = _make_double_builder()
        msg1 = b.build("test.Msg", value=float("nan"))
        msg2 = b.build("test.Msg", value=1.0)
        result = self._approx_differ().compare(msg1, msg2)
        assert result.has_changes()

    def test_inf_not_equal_number(self) -> None:
        b = _make_double_builder()
        msg1 = b.build("test.Msg", value=float("inf"))
        msg2 = b.build("test.Msg", value=1e308)
        result = self._approx_differ().compare(msg1, msg2)
        assert result.has_changes()
