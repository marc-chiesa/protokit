"""Tests for EQUAL vs EQUIVALENT field-presence semantics (U5, R10, KTD-7).

Two presence-comparison modes, selected via
:meth:`MessageDifferencer.set_message_field_comparison`:

* **EQUIVALENT** (the default) — a presence-bearing field set to its DEFAULT
  value is treated as equal to an unset field. The "set-to-default ≈ unset"
  collapse. A field set to a *non-default* value vs unset is still reported as a
  presence difference (today's pinned behavior, unchanged).
* **EQUAL** (opt-in) — a presence-bearing field set on one side (even to its
  default value) and unset on the other is reported as a presence difference.

EQUAL is observable only where presence exists: proto2 fields, proto3
``optional`` fields, oneof members, and singular message fields. It is a
documented NO-OP for proto3 implicit-presence scalars, which carry no presence
bit and so cannot distinguish a default value from unset.

Each behavioral test follows baseline-then-mechanism: under EQUIVALENT the
default-vs-unset pair collapses (the baseline), then under EQUAL the same pair
distinguishes — so the mechanism is non-vacuous and the difference is
attributable to the mode, not the fixture.
"""

from __future__ import annotations

from typing import Any

from google.protobuf import descriptor_pb2

from protokit.message import (
    ChangeType,
    DiffResult,
    MessageDifferencer,
    MessageFieldComparison,
    diff_messages,
)
from tests.proto_builder import ProtoBuilder

T = descriptor_pb2.FieldDescriptorProto


def _equal_differ() -> MessageDifferencer:
    """A differ configured for strict EQUAL presence comparison."""
    md = MessageDifferencer()
    md.set_message_field_comparison(MessageFieldComparison.EQUAL)
    return md


# ---------------------------------------------------------------------------
# proto3 optional scalar — the AE5 acceptance scenario
# ---------------------------------------------------------------------------


class TestProto3OptionalScalar:
    """proto3 ``optional int32 score`` set to 0 vs unset (AE5)."""

    @staticmethod
    def _builder() -> ProtoBuilder:
        b = ProtoBuilder()
        b.message(
            "test.Score",
            {"score": (T.TYPE_INT32, 1)},
            optional_fields={"score"},
            syntax="proto3",
        )
        return b

    def test_proto3_optional_has_genuine_presence(self) -> None:
        """The builder produces a real proto3-optional field (presence works)."""
        b = self._builder()
        cls = b.get_message_class("test.Score")
        fd = cls.DESCRIPTOR.fields_by_name["score"]
        assert fd.has_presence is True
        # set-to-default is observable as present.
        assert cls(score=0).HasField("score") is True
        assert cls().HasField("score") is False

    def test_equivalent_collapses_default_vs_unset(self) -> None:
        """EQUIVALENT (default): score=0 (present) vs unset → equal."""
        b = self._builder()
        cls = b.get_message_class("test.Score")
        result = diff_messages(cls(score=0), cls())
        assert not result.has_changes()

    def test_equal_reports_default_vs_unset(self) -> None:
        """EQUAL: score=0 (present) vs unset → a presence difference."""
        b = self._builder()
        cls = b.get_message_class("test.Score")
        result = _equal_differ().compare(cls(score=0), cls())
        assert result.has_changes()
        assert len(result.differences) == 1
        d = result.differences[0]
        # left (expected) has it set, right (actual) does not → REMOVED.
        assert d.change_type == ChangeType.REMOVED
        assert str(d.path) == "score"

    def test_equal_added_direction(self) -> None:
        """EQUAL: unset on expected, set-to-default on actual → ADDED."""
        b = self._builder()
        cls = b.get_message_class("test.Score")
        result = _equal_differ().compare(cls(), cls(score=0))
        assert len(result.differences) == 1
        assert result.differences[0].change_type == ChangeType.ADDED
        assert str(result.differences[0].path) == "score"


# ---------------------------------------------------------------------------
# proto3 implicit scalar — the documented NO-OP
# ---------------------------------------------------------------------------


class TestProto3ImplicitScalar:
    """proto3 implicit ``int32 count`` = 0 vs unset: indistinguishable."""

    @staticmethod
    def _builder() -> ProtoBuilder:
        b = ProtoBuilder()
        b.message("test.Counter", {"count": (T.TYPE_INT32, 1)}, syntax="proto3")
        return b

    def test_field_has_no_presence(self) -> None:
        b = self._builder()
        fd = b.get_message_class("test.Counter").DESCRIPTOR.fields_by_name["count"]
        assert fd.has_presence is False

    def test_equivalent_no_diff(self) -> None:
        b = self._builder()
        cls = b.get_message_class("test.Counter")
        assert not diff_messages(cls(count=0), cls()).has_changes()

    def test_equal_is_a_noop(self) -> None:
        """EQUAL cannot fabricate presence for an implicit scalar — no diff."""
        b = self._builder()
        cls = b.get_message_class("test.Counter")
        result = _equal_differ().compare(cls(count=0), cls())
        assert not result.has_changes()

    def test_equal_still_reports_real_value_change(self) -> None:
        """EQUAL is a presence no-op here, but real value diffs still fire."""
        b = self._builder()
        cls = b.get_message_class("test.Counter")
        result = _equal_differ().compare(cls(count=1), cls(count=2))
        assert len(result.differences) == 1
        assert result.differences[0].change_type == ChangeType.MODIFIED


# ---------------------------------------------------------------------------
# proto2 optional scalar
# ---------------------------------------------------------------------------


class TestProto2OptionalScalar:
    """proto2 ``optional int32 value`` set-to-default vs unset."""

    @staticmethod
    def _builder() -> ProtoBuilder:
        b = ProtoBuilder()
        b.message("test.P2", {"value": (T.TYPE_INT32, 1)}, syntax="proto2")
        return b

    def test_field_has_presence(self) -> None:
        b = self._builder()
        fd = b.get_message_class("test.P2").DESCRIPTOR.fields_by_name["value"]
        assert fd.has_presence is True

    def test_equivalent_collapses_default_vs_unset(self) -> None:
        b = self._builder()
        cls = b.get_message_class("test.P2")
        assert not diff_messages(cls(value=0), cls()).has_changes()

    def test_equal_distinguishes_default_vs_unset(self) -> None:
        b = self._builder()
        cls = b.get_message_class("test.P2")
        result = _equal_differ().compare(cls(value=0), cls())
        assert len(result.differences) == 1
        assert result.differences[0].change_type == ChangeType.REMOVED
        assert str(result.differences[0].path) == "value"

    def test_non_default_vs_unset_reports_in_both_modes(self) -> None:
        """Set-to-NON-default vs unset is a presence diff in BOTH modes
        (the pre-existing, regression-pinned behavior, unchanged by U5)."""
        b = self._builder()
        cls = b.get_message_class("test.P2")
        equiv = diff_messages(cls(value=7), cls())
        equal = _equal_differ().compare(cls(value=7), cls())
        assert len(equiv.differences) == 1
        assert len(equal.differences) == 1
        assert equiv.differences[0].change_type == ChangeType.REMOVED
        assert equal.differences[0].change_type == ChangeType.REMOVED


# ---------------------------------------------------------------------------
# Singular message field set-to-empty vs unset (+ no double-report)
# ---------------------------------------------------------------------------


class TestSingularMessageField:
    """Empty-but-present singular message field vs unset."""

    @staticmethod
    def _builder() -> ProtoBuilder:
        b = ProtoBuilder()
        b.message("test.Inner", {"x": (T.TYPE_INT32, 1)}, syntax="proto3")
        b.message(
            "test.Outer",
            {"inner": (T.TYPE_MESSAGE, 1, ".test.Inner")},
            syntax="proto3",
        )
        return b

    @staticmethod
    def _empty_present_vs_unset(b: ProtoBuilder) -> tuple[Any, Any]:
        outer_cls = b.get_message_class("test.Outer")
        present = outer_cls()
        present.inner.SetInParent()  # present-but-empty
        absent = outer_cls()
        return present, absent

    def test_presence_setup_is_real(self) -> None:
        b = self._builder()
        present, absent = self._empty_present_vs_unset(b)
        assert present.HasField("inner") is True
        assert absent.HasField("inner") is False

    def test_equivalent_collapses_empty_vs_unset(self) -> None:
        b = self._builder()
        present, absent = self._empty_present_vs_unset(b)
        assert not diff_messages(present, absent).has_changes()

    def test_equal_distinguishes_and_does_not_double_report(self) -> None:
        """EQUAL reports the empty-but-present message as exactly ONE diff.

        Reconciles with the engine's pre-existing empty-but-present message
        exception: the U5 layer makes that single exception mode-aware rather
        than emitting a second presence diff alongside it (no double-report).
        """
        b = self._builder()
        present, absent = self._empty_present_vs_unset(b)
        result = _equal_differ().compare(present, absent)
        assert len(result.differences) == 1
        d = result.differences[0]
        assert d.change_type == ChangeType.REMOVED
        assert str(d.path) == "inner"

    def test_equal_added_direction(self) -> None:
        b = self._builder()
        outer_cls = b.get_message_class("test.Outer")
        absent = outer_cls()
        present = outer_cls()
        present.inner.SetInParent()
        result = _equal_differ().compare(absent, present)
        assert len(result.differences) == 1
        assert result.differences[0].change_type == ChangeType.ADDED
        assert str(result.differences[0].path) == "inner"

    def test_populated_message_unchanged_in_both_modes(self) -> None:
        """A NON-empty one-sided message still reports its populated leaves
        (recursive walk), identically in both modes — U5 only governs the
        empty-but-present exception, not real subtree content."""
        b = self._builder()
        inner_cls = b.get_message_class("test.Inner")
        outer_cls = b.get_message_class("test.Outer")
        populated = outer_cls(inner=inner_cls(x=5))
        absent = outer_cls()
        equiv = diff_messages(populated, absent)
        equal = _equal_differ().compare(populated, absent)
        assert [str(d.path) for d in equiv.differences] == ["inner.x"]
        assert [str(d.path) for d in equal.differences] == ["inner.x"]


# ---------------------------------------------------------------------------
# oneof members + synthetic-oneof safety
# ---------------------------------------------------------------------------


class TestOneofMembers:
    """User-declared oneof member presence under EQUAL/EQUIVALENT."""

    @staticmethod
    def _builder() -> ProtoBuilder:
        b = ProtoBuilder()
        b.message(
            "test.Choice",
            {"text": (T.TYPE_STRING, 1), "number": (T.TYPE_INT32, 2)},
            oneofs={"value": ["text", "number"]},
            syntax="proto3",
        )
        return b

    def test_equivalent_collapses_default_member_vs_unset(self) -> None:
        b = self._builder()
        cls = b.get_message_class("test.Choice")
        selected = cls()
        selected.text = ""  # select the text variant at its default value
        unselected = cls()
        assert selected.WhichOneof("value") == "text"
        assert unselected.WhichOneof("value") is None
        assert not diff_messages(selected, unselected).has_changes()

    def test_equal_distinguishes_default_member_vs_unset(self) -> None:
        b = self._builder()
        cls = b.get_message_class("test.Choice")
        selected = cls()
        selected.text = ""
        result = _equal_differ().compare(selected, cls())
        assert len(result.differences) == 1
        assert result.differences[0].change_type == ChangeType.REMOVED
        assert str(result.differences[0].path) == "text"


class TestSyntheticOneofNotReported:
    """A proto3-optional synthetic oneof is never itself a oneof/field diff."""

    def test_synthetic_oneof_skipped_under_equal(self) -> None:
        """Switching a proto3-optional from set to a different set value reports
        the field path (``score``), NEVER the synthetic ``_score`` oneof."""
        b = ProtoBuilder()
        b.message(
            "test.Score",
            {"score": (T.TYPE_INT32, 1)},
            optional_fields={"score"},
            syntax="proto3",
        )
        cls = b.get_message_class("test.Score")
        # Genuine value change, both present.
        result = _equal_differ().compare(cls(score=1), cls(score=2))
        paths = {str(d.path) for d in result.differences}
        assert paths == {"score"}
        assert not any("_score" in p for p in paths)

    def test_synthetic_oneof_not_reported_on_presence_delta(self) -> None:
        """The presence delta names ``score``, not the synthetic oneof."""
        b = ProtoBuilder()
        b.message(
            "test.Score",
            {"score": (T.TYPE_INT32, 1)},
            optional_fields={"score"},
            syntax="proto3",
        )
        cls = b.get_message_class("test.Score")
        result = _equal_differ().compare(cls(score=0), cls())
        paths = {str(d.path) for d in result.differences}
        assert paths == {"score"}
        assert not any(p.startswith("_") for p in paths)


# ---------------------------------------------------------------------------
# Default-mode regression (R12): explicit EQUIVALENT == implicit default
# ---------------------------------------------------------------------------


class TestDefaultModeRegression:
    """An explicit ``set_message_field_comparison(EQUIVALENT)`` is byte-identical
    to the implicit default across a representative comparison (R12)."""

    @staticmethod
    def _representative_builder() -> ProtoBuilder:
        b = ProtoBuilder()
        b.message("test.Inner", {"x": (T.TYPE_INT32, 1)}, syntax="proto3")
        b.message(
            "test.Rich",
            {
                "name": (T.TYPE_STRING, 1),
                "count": (T.TYPE_INT32, 2),
                "score": (T.TYPE_INT32, 3),
                "inner": (T.TYPE_MESSAGE, 4, ".test.Inner"),
                "tags": (T.TYPE_STRING, 5),
            },
            optional_fields={"score"},
            repeated_fields={"tags"},
            syntax="proto3",
        )
        return b

    def test_explicit_equivalent_matches_default(self) -> None:
        b = self._representative_builder()
        inner_cls = b.get_message_class("test.Inner")
        rich_cls = b.get_message_class("test.Rich")
        left = rich_cls(name="a", count=1, score=0, inner=inner_cls(x=1), tags=["t1"])
        right = rich_cls(name="b", count=1, inner=inner_cls(x=2), tags=["t1", "t2"])

        default_result = MessageDifferencer().compare(left, right)
        explicit = MessageDifferencer()
        explicit.set_message_field_comparison(MessageFieldComparison.EQUIVALENT)
        explicit_result = explicit.compare(left, right)

        def _norm(r: DiffResult) -> list[tuple[str, str]]:
            return [(str(d.path), d.change_type.value) for d in r.differences]

        assert _norm(default_result) == _norm(explicit_result)
        # And it is genuinely non-vacuous (there ARE differences to compare).
        assert _norm(default_result)

    def test_diff_messages_unaffected_by_mode_plumbing(self) -> None:
        """The module-level ``diff_messages`` helper keeps EQUIVALENT default."""
        b = self._representative_builder()
        rich_cls = b.get_message_class("test.Rich")
        # score=0 set vs unset must collapse under the default.
        left = rich_cls(name="x", score=0)
        right = rich_cls(name="x")
        assert not diff_messages(left, right).has_changes()
