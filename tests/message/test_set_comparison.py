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
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

from protokit.message import (
    ChangeType,
    FieldHookContext,
    FloatComparison,
    MessageDifferencer,
    MessageFieldComparison,
)
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


class TestSelectorExceptionsPropagate:
    def test_stop_iteration_from_a_predicate_is_not_rewrapped(self) -> None:
        """A selector's own ``StopIteration`` reaches the caller unchanged.

        Matching selectors inside a generator (``any(...)``) would turn it into
        ``RuntimeError`` under PEP 479, so the lookup stays a plain loop.
        """
        b = _tags_builder()
        msg1 = b.build("test.Msg", tags=["x"])
        msg2 = b.build("test.Msg", tags=["y"])

        def exhausted(fd: object, path: object) -> bool:
            raise StopIteration("selector exhausted")

        d = MessageDifferencer()
        d.treat_as_set(FieldSelector.from_predicate(exhausted))
        with pytest.raises(StopIteration, match="selector exhausted"):
            d.compare(msg1, msg2)


# ---------------------------------------------------------------------------
# Pairing carries the caller's configuration (0.17.0)
#
# Elements pair when a trial comparison under the differ's own ignore rules,
# presence mode and nested set and map policies finds no difference, with
# floats exact, no hooks, partial off and no depth cut. The chosen pairs then
# run through the main walk with the full configuration, at the left element's
# index.
# ---------------------------------------------------------------------------


def _messages(file_proto: descriptor_pb2.FileDescriptorProto) -> dict[str, type]:
    """Every top-level message class in ``file_proto``, built in its own pool."""
    pool = descriptor_pool.DescriptorPool()
    pool.Add(file_proto)
    return {
        m.name: message_factory.GetMessageClass(
            pool.FindMessageTypeByName(f"{file_proto.package}.{m.name}")
        )
        for m in file_proto.message_type
    }


def _deep_items_file() -> descriptor_pb2.FileDescriptorProto:
    """``Container { repeated Item items }``, ``Item { id; Inner inner }``, ``Inner { v }``."""
    fdp = descriptor_pb2.FileDescriptorProto(name="deep.proto", package="t", syntax="proto3")
    inner = fdp.message_type.add(name="Inner")
    inner.field.add(name="v", number=1, type=T.TYPE_INT32, label=T.LABEL_OPTIONAL)
    item = fdp.message_type.add(name="Item")
    item.field.add(name="id", number=1, type=T.TYPE_STRING, label=T.LABEL_OPTIONAL)
    item.field.add(
        name="inner", number=2, type=T.TYPE_MESSAGE, type_name=".t.Inner",
        label=T.LABEL_OPTIONAL,
    )
    fdp.message_type.add(name="Container").field.add(
        name="items", number=1, type=T.TYPE_MESSAGE, type_name=".t.Item",
        label=T.LABEL_REPEATED,
    )
    return fdp


def _observed(result: object) -> list[tuple[str, str]]:
    return sorted((str(d.path), d.change_type.name) for d in result)  # type: ignore[attr-defined]


class TestPairingCarriesConfiguration:
    """Set pairing uses the caller's configuration, not a default differ's."""

    def test_a_dotted_ignore_reaches_inside_pairing(self) -> None:
        """``ignore_fields("items.value")`` lets elements differing only there pair."""
        b = _items_builder()
        item = b.get_message_class("test.Item")
        left = b.build("test.Container", items=[item(id="a", value=1), item(id="b", value=2)])
        right = b.build("test.Container", items=[item(id="b", value=7), item(id="a", value=8)])

        d = MessageDifferencer()
        d.ignore_fields("items.value")
        d.treat_as_set("items")

        assert _observed(d.compare(left, right)) == []

    def test_float_tolerance_does_not_reach_inside_pairing(self) -> None:
        """Pairing stays exact: elements 1e-12 apart do not pair under APPROXIMATE."""
        fdp = descriptor_pb2.FileDescriptorProto(name="f.proto", package="t", syntax="proto3")
        fdp.message_type.add(name="Pt").field.add(
            name="x", number=1, type=T.TYPE_DOUBLE, label=T.LABEL_OPTIONAL,
        )
        fdp.message_type.add(name="Box").field.add(
            name="pts", number=1, type=T.TYPE_MESSAGE, type_name=".t.Pt",
            label=T.LABEL_REPEATED,
        )
        cls = _messages(fdp)
        left = cls["Box"](pts=[cls["Pt"](x=1.0)])
        right = cls["Box"](pts=[cls["Pt"](x=1.0 + 1e-12)])

        tolerant = MessageDifferencer()
        tolerant.set_float_comparison(FloatComparison.APPROXIMATE)
        assert _observed(tolerant.compare(left, right)) == []

        tolerant.treat_as_set("pts")
        assert _observed(tolerant.compare(left, right)) == [
            ("pts[0].x", "ADDED"), ("pts[0].x", "REMOVED"),
        ]

    def test_a_validate_hook_runs_once_per_chosen_pair_never_per_trial(self) -> None:
        """5x5 reversed elements: one hook call per chosen pair's field, at its left index."""
        b = _items_builder()
        item = b.get_message_class("test.Item")
        ids = ["a", "b", "c", "d", "e"]
        left = b.build("test.Container", items=[item(id=i, value=n) for n, i in enumerate(ids)])
        right = b.build(
            "test.Container",
            items=[item(id=i, value=n) for n, i in reversed(list(enumerate(ids)))],
        )
        seen: list[str] = []

        d = MessageDifferencer()
        d.treat_as_set("items")
        d.register_validate_hook(lambda ctx: seen.append(str(ctx.path)))
        result = d.compare(left, right)

        assert _observed(result) == []
        assert sorted(seen) == sorted(
            f"items[{n}].{field}" for n in range(5) for field in ("id", "value")
        )

    def test_a_raising_hook_on_a_chosen_pair_gives_one_error(self) -> None:
        """A hook that raises on one element's field reports exactly one error."""
        b = _items_builder()
        item = b.get_message_class("test.Item")
        ids = ["a", "b", "c", "d", "e"]
        left = b.build("test.Container", items=[item(id=i) for i in ids])
        right = b.build("test.Container", items=[item(id=i) for i in reversed(ids)])

        def hook(ctx: FieldHookContext) -> None:
            if ctx.left_value == "c":
                raise RuntimeError("bad c")

        d = MessageDifferencer()
        d.treat_as_set("items")
        d.register_validate_hook(hook)
        result = d.compare(left, right)

        assert _observed(result) == []
        assert [(e.path, "bad c" in e.message) for e in result.errors] == [("items[2].id", True)]

    def test_elements_differing_below_the_depth_cut_do_not_pair(self) -> None:
        """``max_depth=1``: a difference below the cut keeps elements apart; truncation shows."""
        cls = _messages(_deep_items_file())
        item, inner = cls["Item"], cls["Inner"]
        left = cls["Container"](items=[item(id="a", inner=inner(v=1))])
        right = cls["Container"](items=[item(id="a", inner=inner(v=2))])

        d = MessageDifferencer()
        d.max_depth = 1
        d.treat_as_set("items")
        result = d.compare(left, right)

        assert _observed(result) == [("items[0].id", "ADDED"), ("items[0].id", "REMOVED")]
        assert [str(p) for p in result.truncated_paths] == ["items[0].inner", "items[0].inner"]

    def test_identical_elements_pair_under_a_depth_cut(self) -> None:
        """``max_depth=1``: identical elements pair, and the chosen pair's walk stops at the cut.

        This is the answer index pairing gives for the same messages.
        """
        cls = _messages(_deep_items_file())
        item, inner = cls["Item"], cls["Inner"]
        left = cls["Container"](items=[item(id="b"), item(id="a", inner=inner(v=1))])
        right = cls["Container"](items=[item(id="a", inner=inner(v=1)), item(id="b")])

        d = MessageDifferencer()
        d.max_depth = 1
        result = d.compare(left, left)
        assert (_observed(result), [str(p) for p in result.truncated_paths]) == (
            [], ["items[1].inner"],
        )

        d.treat_as_set("items")
        result = d.compare(left, right)
        assert (_observed(result), [str(p) for p in result.truncated_paths]) == (
            [], ["items[1].inner"],
        )

    def test_a_nested_set_policy_applies_inside_pairing(self) -> None:
        """``treat_as_set`` on an element's own repeated field applies while pairing."""
        fdp = descriptor_pb2.FileDescriptorProto(name="n.proto", package="t", syntax="proto3")
        fdp.message_type.add(name="Group").field.add(
            name="tags", number=1, type=T.TYPE_STRING, label=T.LABEL_REPEATED,
        )
        fdp.message_type.add(name="Root").field.add(
            name="groups", number=1, type=T.TYPE_MESSAGE, type_name=".t.Group",
            label=T.LABEL_REPEATED,
        )
        cls = _messages(fdp)
        left = cls["Root"](groups=[cls["Group"](tags=["x", "y"]), cls["Group"](tags=["z"])])
        right = cls["Root"](groups=[cls["Group"](tags=["z"]), cls["Group"](tags=["y", "x"])])

        d = MessageDifferencer()
        d.treat_as_set("groups")
        d.treat_as_set("tags")

        assert _observed(d.compare(left, right)) == []

    def test_an_ignored_extension_is_ignored_inside_pairing(self) -> None:
        """``ignore_fields("(t.note)")`` reaches an extension set on a set element."""
        fdp = descriptor_pb2.FileDescriptorProto(name="x.proto", package="t", syntax="proto2")
        elem = fdp.message_type.add(name="Elem")
        elem.field.add(name="id", number=1, type=T.TYPE_STRING, label=T.LABEL_OPTIONAL)
        elem.extension_range.add(start=100, end=200)
        fdp.message_type.add(name="Bag").field.add(
            name="elems", number=1, type=T.TYPE_MESSAGE, type_name=".t.Elem",
            label=T.LABEL_REPEATED,
        )
        fdp.extension.add(
            name="note", number=100, type=T.TYPE_STRING, label=T.LABEL_OPTIONAL,
            extendee=".t.Elem",
        )
        pool = descriptor_pool.DescriptorPool()
        pool.Add(fdp)
        bag = message_factory.GetMessageClass(pool.FindMessageTypeByName("t.Bag"))
        note = pool.FindExtensionByName("t.note")
        left, right = bag(), bag()
        for msg, notes in ((left, ("p", "q")), (right, ("r", "s"))):
            for elem_id, text in zip(("a", "b"), notes, strict=True):
                e = msg.elems.add(id=elem_id)
                e.Extensions[note] = text
        right.elems.reverse()

        d = MessageDifferencer()
        d.ignore_fields("(t.note)")
        d.treat_as_set("elems")

        assert _observed(d.compare(left, right)) == []

    def test_a_schema_change_does_not_stop_pairing_and_is_reported_once(self) -> None:
        """Cross-pool elements whose field changed type pair; each pair reports it once."""

        def _file(value_type: int) -> descriptor_pb2.FileDescriptorProto:
            fdp = descriptor_pb2.FileDescriptorProto(name="s.proto", package="t", syntax="proto3")
            it = fdp.message_type.add(name="It")
            it.field.add(name="id", number=1, type=T.TYPE_STRING, label=T.LABEL_OPTIONAL)
            it.field.add(name="n", number=2, type=value_type, label=T.LABEL_OPTIONAL)
            fdp.message_type.add(name="Box").field.add(
                name="its", number=1, type=T.TYPE_MESSAGE, type_name=".t.It",
                label=T.LABEL_REPEATED,
            )
            return fdp

        old, new = _messages(_file(T.TYPE_INT32)), _messages(_file(T.TYPE_INT64))
        left = old["Box"](its=[old["It"](id="a", n=1), old["It"](id="b", n=2)])
        right = new["Box"](its=[new["It"](id="b", n=2), new["It"](id="a", n=1)])

        d = MessageDifferencer()
        d.treat_as_set("its")

        assert _observed(d.compare(left, right)) == [
            ("its[0].n", "TYPE_CHANGED"), ("its[1].n", "TYPE_CHANGED"),
        ]

    def test_a_nested_compare_inside_a_hook_keeps_each_calls_pools(self) -> None:
        """A hook may call ``compare()`` on the same differ; each call sees its own pools."""
        outer_b, inner_b = ProtoBuilder(), ProtoBuilder()
        for b in (outer_b, inner_b):
            b.message("t.M", {"a": (T.TYPE_INT32, 1), "b": (T.TYPE_INT32, 2)})
        outer_left, outer_right = outer_b.build("t.M", a=1, b=1), outer_b.build("t.M", a=2, b=2)
        inner_left, inner_right = inner_b.build("t.M", a=1), inner_b.build("t.M", a=1)
        seen: list[tuple[str, bool]] = []
        d = MessageDifferencer()

        def hook(ctx: FieldHookContext) -> None:
            if ctx.left_pool is outer_left.DESCRIPTOR.file.pool:
                seen.append((str(ctx.path), True))
                if str(ctx.path) == "b":
                    assert not d.compare(inner_left, inner_right).has_changes()
            else:
                seen.append((str(ctx.path), ctx.left_pool is inner_left.DESCRIPTOR.file.pool))

        d.register_validate_hook(hook)
        result = d.compare(outer_left, outer_right)

        assert _observed(result) == [("a", "MODIFIED"), ("b", "MODIFIED")]
        # Fields are visited last-declared first, so the nested call runs at
        # ``b``, and its hook sees both of its own fields.
        assert seen == [("b", True), ("b", True), ("a", True), ("a", True)]

    def test_an_empty_set_against_an_empty_set(self) -> None:
        b = _items_builder()
        d = MessageDifferencer()
        d.treat_as_set("items")
        d.register_validate_hook(lambda ctx: pytest.fail("no element, no hook"))

        result = d.compare(b.build("test.Container"), b.build("test.Container"))

        assert _observed(result) == []
        assert not result.diagnostics

    def test_strict_presence_decides_which_elements_pair(self) -> None:
        """Under EQUAL presence an unset field pairs only with an unset one, in either order."""
        fdp = descriptor_pb2.FileDescriptorProto(name="p.proto", package="t", syntax="proto3")
        it = fdp.message_type.add(name="It")
        it.field.add(name="id", number=1, type=T.TYPE_STRING, label=T.LABEL_OPTIONAL)
        it.field.add(
            name="flag", number=2, type=T.TYPE_INT32, label=T.LABEL_OPTIONAL,
            oneof_index=0, proto3_optional=True,
        )
        it.oneof_decl.add(name="_flag")
        fdp.message_type.add(name="Box").field.add(
            name="its", number=1, type=T.TYPE_MESSAGE, type_name=".t.It",
            label=T.LABEL_REPEATED,
        )
        cls = _messages(fdp)
        unset, at_default = cls["It"](id="a"), cls["It"](id="a", flag=0)
        left = cls["Box"](its=[unset, at_default])
        right = cls["Box"](its=[at_default, unset])

        d = MessageDifferencer()
        d.set_message_field_comparison(MessageFieldComparison.EQUAL)
        assert _observed(d.compare(left, right)) == [
            ("its[0].flag", "ADDED"), ("its[1].flag", "REMOVED"),
        ]

        d.treat_as_set("its")
        assert _observed(d.compare(left, right)) == []

    def test_a_chosen_pair_is_reported_at_the_left_elements_index(self) -> None:
        """Left ``[a]`` against right ``[b, a]``: the pair reports at ``its[0]``, its left index."""

        def _file(value_type: int) -> descriptor_pb2.FileDescriptorProto:
            fdp = descriptor_pb2.FileDescriptorProto(name="s.proto", package="t", syntax="proto3")
            it = fdp.message_type.add(name="It")
            it.field.add(name="id", number=1, type=T.TYPE_STRING, label=T.LABEL_OPTIONAL)
            it.field.add(name="n", number=2, type=value_type, label=T.LABEL_OPTIONAL)
            fdp.message_type.add(name="Box").field.add(
                name="its", number=1, type=T.TYPE_MESSAGE, type_name=".t.It",
                label=T.LABEL_REPEATED,
            )
            return fdp

        old, new = _messages(_file(T.TYPE_INT32)), _messages(_file(T.TYPE_INT64))
        left = old["Box"](its=[old["It"](id="a", n=1)])
        right = new["Box"](its=[new["It"](id="b"), new["It"](id="a", n=1)])

        d = MessageDifferencer()
        d.treat_as_set("its")

        # The pair (left 0, right 1) reports at the left index; the leftover ``b``
        # is ADDED at its own index in the right list.
        assert _observed(d.compare(left, right)) == [
            ("its[0].id", "ADDED"), ("its[0].n", "TYPE_CHANGED"),
        ]

    def test_an_index_sensitive_ignore_does_not_make_pairing_order_dependent(self) -> None:
        """Trials see elements unindexed: pairing decides the index, so no index applies yet.

        A predicate that ignores ``items[0].value`` applies to the walk of the
        chosen pair at left index 0, never to the choice of partner.
        """
        b = _items_builder()
        item = b.get_message_class("test.Item")
        left = b.build(
            "test.Container", items=[item(id="same", value=1), item(id="same", value=2)],
        )

        d = MessageDifferencer()
        d.treat_as_set("items")
        index_zero = FieldSelector.from_predicate(lambda fd, path: str(path) == "items[0].value")
        d.ignore_fields(index_zero)

        for values in ((1, 2), (2, 1)):
            right = b.build("test.Container", items=[item(id="same", value=v) for v in values])
            assert _observed(d.compare(left, right)) == [], values

    @pytest.mark.parametrize("change", ["type", "cardinality"])
    def test_partial_still_reports_a_schema_change_in_a_paired_element(self, change: str) -> None:
        """Partial does not apply inside a set field, so a paired element is compared in full."""

        def _file(changed: bool) -> descriptor_pb2.FileDescriptorProto:
            fdp = descriptor_pb2.FileDescriptorProto(name="s.proto", package="t", syntax="proto3")
            it = fdp.message_type.add(name="It")
            it.field.add(name="id", number=1, type=T.TYPE_STRING, label=T.LABEL_OPTIONAL)
            v_type = T.TYPE_STRING if changed and change == "type" else T.TYPE_INT32
            v_label = T.LABEL_REPEATED if changed and change == "cardinality" else T.LABEL_OPTIONAL
            it.field.add(name="v", number=2, type=v_type, label=v_label)
            fdp.message_type.add(name="Box").field.add(
                name="its", number=1, type=T.TYPE_MESSAGE, type_name=".t.It",
                label=T.LABEL_REPEATED,
            )
            return fdp

        old, new = _messages(_file(False)), _messages(_file(True))
        new_item = new["It"](id="a")
        if change == "type":
            new_item.v = "changed"
        else:
            new_item.v.append(3)
        left = old["Box"](its=[old["It"](id="a")])
        right = new["Box"](its=[new_item])
        kind = "TYPE_CHANGED" if change == "type" else "CARDINALITY_CHANGED"

        d = MessageDifferencer()
        d.treat_as_set("its")
        assert _observed(d.compare(left, right)) == [("its[0].v", kind)]

        d.set_partial()
        assert _observed(d.compare(left, right)) == [("its[0].v", kind)]

    def test_nested_set_fields_compare_in_time_linear_in_their_depth(self) -> None:
        """A 100-level tree with ``treat_as_set`` on its children compares equal.

        A trial does not walk the pairs it chooses, so nested trials are not
        repeated at every level (each level used to double the cost).
        """
        fdp = descriptor_pb2.FileDescriptorProto(name="n.proto", package="t", syntax="proto3")
        node = fdp.message_type.add(name="Node")
        node.field.add(name="id", number=1, type=T.TYPE_INT32, label=T.LABEL_OPTIONAL)
        node.field.add(
            name="children", number=2, type=T.TYPE_MESSAGE, type_name=".t.Node",
            label=T.LABEL_REPEATED,
        )
        cls = _messages(fdp)["Node"]

        def chain() -> object:
            root = cls(id=0)
            cur = root
            for n in range(1, 101):
                cur = cur.children.add(id=n)
            return root

        d = MessageDifferencer()
        d.treat_as_set("children")

        assert _observed(d.compare(chain(), chain())) == []

    def test_paired_scalar_elements_run_hooks_and_report_enum_renames(self) -> None:
        """Chosen scalar pairs are walked at the left index: hooks run, name drift warns."""

        def _tags(values: dict[str, int]) -> ProtoBuilder:
            b = ProtoBuilder()
            b.message(
                "test.Msg",
                {"tags": (T.TYPE_ENUM, 1, ".test.Msg.E")},
                enums={"E": values},
                repeated_fields={"tags"},
            )
            return b

        left = _tags({"ZERO": 0, "P": 1, "Q": 5}).build("test.Msg", tags=[1, 5])
        right = _tags({"ZERO": 0, "Z": 1, "P": 5}).build("test.Msg", tags=[5, 1])
        seen: list[str] = []

        d = MessageDifferencer()
        d.treat_as_set("tags")
        d.register_validate_hook(lambda ctx: seen.append(str(ctx.path)))
        result = d.compare(left, right)

        assert _observed(result) == []
        assert sorted(seen) == ["tags[0]", "tags[1]"]
        assert sorted((w.path, w.message) for w in result.warnings) == [
            ("tags[0]", "enum value 1 has different names across schemas (P vs Z)"),
            ("tags[1]", "enum value 5 has different names across schemas (Q vs P)"),
        ]

    def test_a_key_error_in_a_set_element_names_that_element(self) -> None:
        """A duplicate key in right element 1 is reported at ``[1]``, as without set pairing."""
        from protokit.message import DuplicateKeyError

        def fdp(name: str, *fields: str) -> descriptor_pb2.DescriptorProto:
            msg = descriptor_pb2.DescriptorProto(name=name)
            for n, field in enumerate(fields, start=1):
                msg.field.add(name=field, number=n, type=T.TYPE_INT32, label=T.LABEL_OPTIONAL)
            return msg

        left = descriptor_pb2.FileDescriptorProto(message_type=[fdp("A", "x"), fdp("B", "y")])
        right = descriptor_pb2.FileDescriptorProto(message_type=[fdp("B", "y"), fdp("C", "z", "z")])

        d = MessageDifferencer()
        d.treat_as_map("field", key="name")
        with pytest.raises(DuplicateKeyError, match=r"message_type\[1\]\.field"):
            d.compare(left, right)

        d.treat_as_set("message_type")
        with pytest.raises(DuplicateKeyError, match=r"message_type\[1\]\.field"):
            d.compare(left, right)
        assert d._call.left_pool is None
