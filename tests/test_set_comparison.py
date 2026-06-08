"""Tests for keyless ("set") repeated-field comparison (U3, KTD-8).

``treat_as_set`` pairs a repeated field's elements order-independently, as a
multiset, via greedy first-fit equality. Set-membership equality is STRICT
exact equality backed by the engine (cross-pool name-matching, enum
wire-compatibility, presence) — NOT Python ``==`` and NOT the per-instance
tolerance/partial policies.

Each behavioral test follows baseline-then-mechanism: first assert the diff
exists (or the pair is unordered) WITHOUT set mode, then assert set mode
changes the outcome — so the suppression/equality signal is non-vacuous.
"""

from __future__ import annotations

import pytest
from google.protobuf import descriptor_pb2

from protokit.message import ChangeType, MessageDifferencer
from protokit.message._selector import FieldSelector
from tests.proto_builder import ProtoBuilder

T = descriptor_pb2.FieldDescriptorProto


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _tags_builder() -> ProtoBuilder:
    """Message with one repeated string field ``tags``."""
    b = ProtoBuilder()
    b.message_with_repeated(
        "test.Msg",
        {"tags": (T.TYPE_STRING, 1)},
        repeated_fields={"tags"},
    )
    return b


def _two_repeated_builder() -> ProtoBuilder:
    """Message with two sibling repeated string fields ``tags`` and ``labels``."""
    b = ProtoBuilder()
    b.message_with_repeated(
        "test.Msg",
        {
            "tags": (T.TYPE_STRING, 1),
            "labels": (T.TYPE_STRING, 2),
        },
        repeated_fields={"tags", "labels"},
    )
    return b


def _items_builder() -> ProtoBuilder:
    """Message with a repeated message field ``items`` (Item{id, value})."""
    b = ProtoBuilder()
    b.message("test.Item", {
        "id": (T.TYPE_STRING, 1),
        "value": (T.TYPE_INT32, 2),
    })
    b.message_with_repeated(
        "test.Container",
        {"items": (T.TYPE_MESSAGE, 1, ".test.Item")},
        repeated_fields={"items"},
    )
    return b


def _enum_elem_builder(active_name: str) -> ProtoBuilder:
    """Isolated-pool builder: repeated Elem{status} where status enum 1 == active_name."""
    b = ProtoBuilder()
    b.message(
        "test.Elem",
        {"status": (T.TYPE_ENUM, 1, ".test.Elem.Status")},
        enums={"Status": {"UNKNOWN": 0, active_name: 1}},
    )
    b.message_with_repeated(
        "test.Container",
        {"elems": (T.TYPE_MESSAGE, 1, ".test.Elem")},
        repeated_fields={"elems"},
    )
    return b


# ---------------------------------------------------------------------------
# AE2: order-independence + per-side leftover reporting (scalar elements)
# ---------------------------------------------------------------------------


class TestScalarSetSemantics:
    def test_unordered_equal_under_set_baseline_index_diffs(self) -> None:
        """['x','y'] vs ['y','x']: index mode reports diffs; set mode equal."""
        b = _tags_builder()
        msg1 = b.build("test.Msg", tags=["x", "y"])
        msg2 = b.build("test.Msg", tags=["y", "x"])

        # Baseline: without set mode the unordered pair reports index diffs.
        baseline = MessageDifferencer().compare(msg1, msg2)
        assert baseline.has_changes()

        # Mechanism: set mode pairs order-independently -> equal.
        d = MessageDifferencer()
        d.treat_as_set("tags")
        result = d.compare(msg1, msg2)
        assert not result.has_changes()

    def test_leftovers_named_per_side(self) -> None:
        """['x','z'] vs ['y','x']: z unmatched on actual, y unmatched on expected."""
        b = _tags_builder()
        # left/expected = msg1, right/actual = msg2
        msg1 = b.build("test.Msg", tags=["x", "z"])
        msg2 = b.build("test.Msg", tags=["y", "x"])

        d = MessageDifferencer()
        d.treat_as_set("tags")
        result = d.compare(msg1, msg2)

        assert result.has_changes()
        removed = [r for r in result if r.change_type == ChangeType.REMOVED]
        added = [a for a in result if a.change_type == ChangeType.ADDED]
        # 'z' is on the expected (left) side only -> REMOVED.
        assert [r.left_value for r in removed] == ["z"]
        # 'y' is on the actual (right) side only -> ADDED.
        assert [a.right_value for a in added] == ["y"]

    def test_multiset_one_leftover(self) -> None:
        """['x','x'] vs ['x']: exactly one 'x' unmatched (multiset, not plain set)."""
        b = _tags_builder()
        msg1 = b.build("test.Msg", tags=["x", "x"])
        msg2 = b.build("test.Msg", tags=["x"])

        d = MessageDifferencer()
        d.treat_as_set("tags")
        result = d.compare(msg1, msg2)

        removed = [r for r in result if r.change_type == ChangeType.REMOVED]
        added = [a for a in result if a.change_type == ChangeType.ADDED]
        assert [r.left_value for r in removed] == ["x"]
        assert added == []

    def test_multiset_extra_on_actual(self) -> None:
        """['x'] vs ['x','x']: exactly one extra 'x' on the actual side -> ADDED."""
        b = _tags_builder()
        msg1 = b.build("test.Msg", tags=["x"])
        msg2 = b.build("test.Msg", tags=["x", "x"])

        d = MessageDifferencer()
        d.treat_as_set("tags")
        result = d.compare(msg1, msg2)

        added = [a for a in result if a.change_type == ChangeType.ADDED]
        removed = [r for r in result if r.change_type == ChangeType.REMOVED]
        assert [a.right_value for a in added] == ["x"]
        assert removed == []


# ---------------------------------------------------------------------------
# Order-independence: partition is identical regardless of element order
# ---------------------------------------------------------------------------


class TestOrderIndependence:
    @pytest.mark.parametrize(
        ("left_tags", "right_tags"),
        [
            (["a", "b", "z"], ["b", "a", "y"]),
            (["z", "a", "b"], ["y", "b", "a"]),
            (["b", "z", "a"], ["a", "y", "b"]),
        ],
    )
    def test_partition_invariant_to_order(
        self, left_tags: list[str], right_tags: list[str],
    ) -> None:
        """The matched/unmatched partition is the same for any element order.

        Every permutation of {a, b, z} vs {a, b, y} must pair a+b and report
        exactly z removed (expected-only) and y added (actual-only).
        """
        b = _tags_builder()
        msg1 = b.build("test.Msg", tags=left_tags)
        msg2 = b.build("test.Msg", tags=right_tags)

        d = MessageDifferencer()
        d.treat_as_set("tags")
        result = d.compare(msg1, msg2)

        removed = sorted(
            r.left_value for r in result if r.change_type == ChangeType.REMOVED
        )
        added = sorted(
            a.right_value for a in result if a.change_type == ChangeType.ADDED
        )
        assert removed == ["z"]
        assert added == ["y"]


# ---------------------------------------------------------------------------
# Selective application: a sibling repeated field still index-pairs
# ---------------------------------------------------------------------------


class TestSelectiveApplication:
    def test_only_marked_field_is_set_sibling_index_pairs(self) -> None:
        """Set mode on 'tags' only; sibling 'labels' keeps ordered index pairing."""
        b = _two_repeated_builder()
        # Both fields are unordered between sides.
        msg1 = b.build("test.Msg", tags=["x", "y"], labels=["p", "q"])
        msg2 = b.build("test.Msg", tags=["y", "x"], labels=["q", "p"])

        d = MessageDifferencer()
        d.treat_as_set("tags")
        result = d.compare(msg1, msg2)

        # 'tags' is set-compared -> no diffs for it.
        tag_diffs = [r for r in result if "tags" in str(r.path)]
        assert tag_diffs == []

        # 'labels' still index-pairs -> the swapped order reports MODIFIED diffs.
        label_diffs = [r for r in result if "labels" in str(r.path)]
        assert label_diffs
        assert all(r.change_type == ChangeType.MODIFIED for r in label_diffs)


# ---------------------------------------------------------------------------
# Message elements: structural pairing; near-equal -> remove+add, not modify
# ---------------------------------------------------------------------------


class TestMessageElements:
    def test_equal_submessages_match_unordered(self) -> None:
        """Repeated submessages pair structurally, order-independently."""
        b = _items_builder()
        item_cls = b.get_message_class("test.Item")
        msg1 = b.build("test.Container", items=[
            item_cls(id="a", value=1), item_cls(id="b", value=2),
        ])
        msg2 = b.build("test.Container", items=[
            item_cls(id="b", value=2), item_cls(id="a", value=1),
        ])

        # Baseline: index pairing reports diffs for the swapped order.
        assert MessageDifferencer().compare(msg1, msg2).has_changes()

        d = MessageDifferencer()
        d.treat_as_set("items")
        assert not d.compare(msg1, msg2).has_changes()

    def test_one_field_different_reports_remove_plus_add_not_modify(self) -> None:
        """A near-equal element pair surfaces as remove + add, NOT a modify.

        Documented v1 behavior: set-membership equality is strict, so a
        one-field-different element does not pair — it leaves one expected
        element unmatched (REMOVED) and one actual element unmatched (ADDED).
        """
        b = _items_builder()
        item_cls = b.get_message_class("test.Item")
        msg1 = b.build("test.Container", items=[
            item_cls(id="a", value=1), item_cls(id="b", value=2),
        ])
        # 'b' element differs by one field (value 2 -> 99); 'a' is identical.
        msg2 = b.build("test.Container", items=[
            item_cls(id="b", value=99), item_cls(id="a", value=1),
        ])

        d = MessageDifferencer()
        d.treat_as_set("items")
        result = d.compare(msg1, msg2)

        # No MODIFIED diff — strict set equality never produces an element modify.
        assert not any(r.change_type == ChangeType.MODIFIED for r in result)
        removed = [r for r in result if r.change_type == ChangeType.REMOVED]
        added = [a for a in result if a.change_type == ChangeType.ADDED]
        # The unmatched 'b' (value=2) is removed; the unmatched 'b' (value=99) is added.
        assert removed
        assert added


# ---------------------------------------------------------------------------
# Cross-pool / enum-wire-compat: PROVES engine equality, not Python ==
# ---------------------------------------------------------------------------


class TestEngineEqualityNotPythonEq:
    def test_cross_pool_enum_wire_compatible_elements_match(self) -> None:
        """Set pairing uses engine equality (cross-pool, enum wire-compat).

        Two isolated pools define Elem{status} where enum value 1 is named
        differently (ACTIVE vs ENABLED). Element messages with status=1 are
        engine-equal (same wire number) but NOT Python ``==``-equal (different
        pool descriptors). If set pairing matched them, it cannot be using
        Python ``==``.
        """
        b1 = _enum_elem_builder("ACTIVE")
        b2 = _enum_elem_builder("ENABLED")
        elem1_cls = b1.get_message_class("test.Elem")
        elem2_cls = b2.get_message_class("test.Elem")

        # Sanity: the element messages are NOT Python ==-equal across pools.
        assert elem1_cls(status=1) != elem2_cls(status=1)

        # Build containers with the elements in DIFFERENT orders so a match
        # requires both order-independence AND cross-pool engine equality.
        msg1 = b1.build("test.Container", elems=[
            elem1_cls(status=0), elem1_cls(status=1),
        ])
        msg2 = b2.build("test.Container", elems=[
            elem2_cls(status=1), elem2_cls(status=0),
        ])

        d = MessageDifferencer()
        d.treat_as_set("elems")
        result = d.compare(msg1, msg2)
        assert not result.has_changes()


# ---------------------------------------------------------------------------
# Selector forms (path / predicate) reach the set policy
# ---------------------------------------------------------------------------


class TestSelectorForms:
    def test_predicate_selector_marks_field(self) -> None:
        """A predicate FieldSelector can mark a repeated field as a set."""
        b = _tags_builder()
        msg1 = b.build("test.Msg", tags=["x", "y"])
        msg2 = b.build("test.Msg", tags=["y", "x"])

        d = MessageDifferencer()
        d.treat_as_set(FieldSelector.from_predicate(lambda fd, path: fd.name == "tags"))
        assert not d.compare(msg1, msg2).has_changes()


# ---------------------------------------------------------------------------
# Registration-time conflict: treat_as_set + treat_as_map on the same field
# ---------------------------------------------------------------------------


class TestRegistrationConflict:
    def test_set_then_map_raises(self) -> None:
        d = MessageDifferencer()
        d.treat_as_set("items")
        with pytest.raises(ValueError, match="treat_as_set"):
            d.treat_as_map("items", key="id")

    def test_map_then_set_raises(self) -> None:
        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        with pytest.raises(ValueError, match="treat_as_map"):
            d.treat_as_set("items")

    def test_predicate_set_not_conflict_checked_at_registration(self) -> None:
        """A predicate-form set selector is opaque -> no registration conflict."""
        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        # No raise: a predicate cannot be conflict-checked at registration.
        d.treat_as_set(lambda fd, path: fd.name == "items")
